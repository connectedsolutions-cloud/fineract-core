"""Final operational metric alignment, after all historical loan mutations."""
from __future__ import annotations
import hashlib
import json
from decimal import Decimal
from typing import Any

METRICS = ("paidPrincipal", "outstandingPrincipal", "paidInterest", "accruedInterest", "duePrincipal", "mora", "insurancePaid", "insuranceOutstanding")

def amounts(values: dict[str, Any]) -> dict[str, str]:
    if set(values) != set(METRICS):
        raise RuntimeError("final_metrics_incomplete_vector")
    result = {}
    for key in METRICS:
        if values[key] is None:
            raise RuntimeError("final_metrics_missing_value:" + key)
        value = Decimal(str(values[key]))
        if not value.is_finite() or value < 0 or value != value.quantize(Decimal(".01")):
            raise RuntimeError("final_metrics_invalid_amount:" + key)
        result[key] = format(value.quantize(Decimal(".01")), "f")
    if Decimal(result["duePrincipal"]) > Decimal(result["outstandingPrincipal"]):
        raise RuntimeError("final_metrics_due_exceeds_outstanding")
    return result

def freeze(loan: dict[str, Any], expected: dict[str, Any], resources: dict[str, Any], cutoff: str | None, events: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    snapshot = loan.get("_mora_cutover_snapshot") or {}
    required = ("SALDO_PAGADO_CAPITAL", "SALDO_PAGADO_INTERES", "SALDO_VENCIDO_CAPITAL", "MONTO_DESEMBOLSADO",
                "SALDO_INTERES", "SALDO_MORA", "SALDO_RECARGOS", "SALDO_SEGURO")
    if not cutoff or any(snapshot.get(k) is None for k in required):
        return None
    # Never reinterpret a generic other-paid counter without per-loan insurance evidence.
    # Existing history guards classify each fee allocation as identified debt insurance.
    insurance_paid = snapshot.get("SALDO_PAGADO_SEGURO")
    insurance_basis = "SALDO_PAGADO_SEGURO"
    if insurance_paid is None:
        insurance_paid = snapshot.get("SALDO_PAGADO_OTROS")
        insurance_basis = "corroborated-legacy-SALDO_PAGADO_OTROS"
        reversed_ids = {e.get("original_external_id") for e in events or [] if e.get("role") == "repayment-reversal"}
        insurance_allocations = sum((Decimal(str(e.get("allocation", {}).get("fee", "0"))) for e in events or []
                                    if e.get("role") in {"repayment", "adjusted-repayment", "mobile-collection-repayment", "native-refinance-payoff"}
                                    and not e.get("source_reversed") and e.get("external_id") not in reversed_ids), Decimal("0"))
        if insurance_paid is None or Decimal(str(insurance_paid)) != insurance_allocations:
            return None
    if insurance_paid is None or loan.get("_mora_cutover_snapshot_missing"):
        return None
    targets = amounts({
        "paidPrincipal": snapshot["SALDO_PAGADO_CAPITAL"], "outstandingPrincipal": expected["principal_balance"],
        "paidInterest": snapshot["SALDO_PAGADO_INTERES"], "accruedInterest": expected["interest_balance"],
        "duePrincipal": snapshot["SALDO_VENCIDO_CAPITAL"], "mora": expected["penalty_balance"],
        "insurancePaid": insurance_paid, "insuranceOutstanding": expected["fee_balance"],
    })
    return {"revision": 1, "cutoffDate": cutoff, "targets": targets, "insurancePaidSource": insurance_basis,
            "insuranceChargeId": int(resources["historical_debt_insurance_charge_id"]),
            "recurringInsuranceChargeId": int(resources["debt_insurance_charge_id"]),
            "penaltyChargeId": int(resources["historical_penalty_charge_id"])}

def align(api: Any, loan_id: int, action: dict[str, Any], observed_at: str) -> dict[str, Any]:
    frozen = action["lifecycle"].get("final_metric_alignment")
    if not frozen or frozen.get("revision") != 1:
        raise RuntimeError("loan_plan_missing_final_metric_targets")
    path = f"loans/{loan_id}/migration-metrics"
    query = {k: frozen[k] for k in ("cutoffDate", "insuranceChargeId", "recurringInsuranceChargeId")}
    observation = api.request("GET", path, query=query)
    before = amounts(observation["metrics"])
    targets = amounts(frozen["targets"])
    if before == targets:
        return {"loan_id": loan_id, "changed": False, "metrics": before}
    payload = {k: frozen[k] for k in ("cutoffDate", "insuranceChargeId", "recurringInsuranceChargeId", "penaltyChargeId")}
    payload.update(sourceObservedAt=observed_at, sourceSystem="ARISSTO", sourceLoanExternalId=action["external_id"], expected=before, targets=targets)
    identity = hashlib.sha256(json.dumps({"payload": payload, "alignmentVersion": observation.get("alignmentVersion", 0)},
                                         sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload["requestId"] = "final-metrics:" + identity
    response = api.request("POST", path, payload, idempotency_key="fm:" + identity[:46])
    if amounts(response["metrics"]) != targets:
        raise RuntimeError("final_metrics_write_readback_mismatch")
    after = amounts(api.request("GET", path, query=query)["metrics"])
    if after != targets:
        raise RuntimeError("final_metrics_persisted_readback_mismatch")
    return {"loan_id": loan_id, "changed": True, "request_id": payload["requestId"], "metrics": after}
