"""Conservatively reconstruct active source-day state before later ordinary payments.

Historical revisions and paired repayment reversals remain in the retained
history. Unsupported after-boundary changes keep the existing quarantine.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _day(value: Any) -> str:
    return str(value or "")[:10]


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _adjustments_are_historical(history: dict, cutoff: str) -> bool:
    """Past revisions remain part of history; only later/unproved revisions block projection."""
    summary = history.get("schedule_adjustment_summary") or {}
    count = int(summary.get("adjustment_count") or 0)
    adjustments = summary.get("adjustments") or []
    if count != len(adjustments):
        return False
    for row in adjustments:
        try:
            created = date.fromisoformat(_day(row.get("DT_CREO")))
            effective = date.fromisoformat(_day(row["FECHA_REESTRUCTURACION"])) if row.get("FECHA_REESTRUCTURACION") else created
        except (ValueError, TypeError):
            return False
        if created.isoformat() >= cutoff or effective.isoformat() >= cutoff:
            return False
    return True


def _historically_reversed_payment_ids(movements: list[dict], cutoff: str,
                                      supported: dict[str, str]) -> set[str] | None:
    """Use the canonical exact-component pairing; never infer a reversal by total alone."""
    def role(row: dict) -> str:
        return supported.get(f'{row.get("CODIGO_SISTEMA")}:{_text(row.get("ID_TRANSACCION"))}', "")
    if not any(_text(row.get("REVERSION")) not in {"", "0"} or "reversal" in role(row)
               for row in movements):
        return set()
    from .loans import pair_loan_reversals
    try:
        pairing = pair_loan_reversals(movements)
    except (KeyError, ValueError, TypeError):
        return None
    if pairing["issue_count"] or pairing["duplicate_original_count"]:
        return None
    by_id = {_text(row.get("ID_MOVIMIENTO_CARTERA")): row for row in movements}
    if any(pair["kind"] != "repayment"
           or _day(by_id[pair["reversal_movement_id"]].get("FECHA_OPERACION")) >= cutoff
           for pair in pairing["pairs"]):
        return None
    return {pair["original_movement_id"] for pair in pairing["pairs"]}


def _single_historical_refinance_proof(loan: dict, history: dict, loans: dict[int, dict],
                                lifecycles: dict[int, dict], source_day: str,
                                cutoff: str, supported: dict[str, str]) -> dict | None:
    """Prove one historical payoff and its dated/current closed predecessor.

    Source-authorized legacy cross-client links use the same liquidation proof
    as the canonical writer. This function proves one leg; the wrapper proves
    all consolidation legs and their combined disbursement conservation.
    """
    incoming = history.get("refinance_incoming") or []
    if history.get("refinance_outgoing"):
        return None
    if not incoming:
        return {}
    if len(incoming) != 1:
        return None
    link = incoming[0]
    try:
        predecessor_id = int(link["old_credit_id"])
        successor_id = int(link["new_credit_id"])
        payoff_day = date.fromisoformat(_day(link["payoff_date"])).isoformat()
    except (KeyError, TypeError, ValueError):
        return None
    predecessor = loans.get(predecessor_id) or {}
    predecessor_history = lifecycles.get(predecessor_id) or {}
    snapshot = predecessor.get("_mora_cutover_snapshot") or {}
    successor_snapshot = loan.get("_mora_cutover_snapshot") or {}
    if (successor_id != int(loan["ID_CREDITO"]) or predecessor_id == successor_id
            or not payoff_day < cutoff
            or _text(link.get("payoff_reversed")) not in {"", "0"}
            or _text(link.get("predecessor_current_state")) != "3"
            or link.get("later_posted_payment_count") != 0
            or link.get("predecessor_current_balance") is None
            or _money(link["predecessor_current_balance"]) != 0
            or not _text(loan.get("client_source_key"))
            or _text(predecessor.get("source_state")) != "3"
            or _text(snapshot.get("ID_ESTADO_CARTERA")) != "3"
            or _day(snapshot.get("source_day")) != source_day
            or predecessor.get("_mora_cutover_snapshot_missing")
            or predecessor.get("_post_cutover_source_events")
            or not snapshot.get("ID_CRD_HISTORICO_DIARIO")
            or not successor_snapshot.get("ID_CRD_HISTORICO_DIARIO")
            or predecessor_history.get("omit_financial_reconstruction")
            or not _adjustments_are_historical(predecessor_history, cutoff)):
        return None
    same_owner = loan.get("client_source_key") == predecessor.get("client_source_key")
    if str(link.get("same_owner")).strip() != ("1" if same_owner else "0"):
        return None
    if not same_owner and (not predecessor.get("client_source_key")
            or any(not _text(link.get(field)) for field in
                   ("liquidation_id", "payoff_movement_id", "liquidation_operator_id"))):
        return None
    zero_fields = ("SALDO_TOTAL", "SALDO_INTERES", "SALDO_MORA", "SALDO_RECARGOS")
    if (any(snapshot.get(field) is None or _money(snapshot[field]) != 0 for field in zero_fields)
            or snapshot.get("SALDO_PAGADO_CAPITAL") is None
            or snapshot.get("MONTO_DESEMBOLSADO") is None
            or _money(snapshot["MONTO_DESEMBOLSADO"]) <= 0
            or _money(snapshot["SALDO_PAGADO_CAPITAL"]) != _money(snapshot["MONTO_DESEMBOLSADO"])):
        return None

    # Arissto can capture the POST row before the separate closed-state flag
    # update. Prove full principal settlement at that exact payoff snapshot;
    # never confuse a state-1 partial paydown with a fully closed predecessor.
    post_state = _text(link.get("predecessor_post_payoff_state"))
    terminal_proof = {}
    if post_state == "1":
        paid = link.get("predecessor_post_payoff_paid_principal")
        if (link.get("predecessor_post_payoff_snapshot_count") != 1
                or not link.get("predecessor_post_payoff_snapshot_id") or paid is None
                or _money(paid) != _money(snapshot["MONTO_DESEMBOLSADO"])):
            return None
        terminal_proof = {
            "terminal_state_policy": "fully-paid-post-snapshot-and-closed-cutover-v1",
            "post_payoff_snapshot_id": str(link["predecessor_post_payoff_snapshot_id"]),
            "principal_fully_paid_at_payoff": True,
        }
    elif post_state != "3":
        return None

    current_zero_fields = (
        "ULTIMO_SALDO", "SALDO_INTERES", "SALDO_INTERES_PENDIENTE", "SALDO_MORA",
        "SALDO_RECARGOS", "SALDO_CXC", "SALDO_TOTAL",
    )
    if any(_money(predecessor.get(field)) != 0 for field in current_zero_fields):
        return None
    insurance = snapshot.get("SALDO_SEGURO")
    if insurance is None or _money(insurance) < 0:
        return None
    insurance_policy = "zero-balance"
    if _money(insurance) > 0:
        # Reuse the canonical closed-loan classifier. Import at call time:
        # loans imports this module, but both modules are initialized by now.
        from .loans import _classify_closed_stale_insurance_residue
        stale = _classify_closed_stale_insurance_residue(predecessor)
        if stale is None or _money(stale["source_insurance_residue"]) != _money(insurance):
            return None
        insurance_policy = stale["classification"]

    def role(row: dict) -> str:
        return supported.get(f'{row.get("CODIGO_SISTEMA")}:{_text(row.get("ID_TRANSACCION"))}', "")

    predecessor_movements = predecessor_history.get("movements") or []
    try:
        # A malformed date must never be treated as a later payment to discard.
        for row in history.get("movements") or []:
            date.fromisoformat(_day(row.get("FECHA_OPERACION")))
        predecessor_days = [date.fromisoformat(_day(row.get("FECHA_OPERACION"))).isoformat()
                            for row in predecessor_movements]
    except ValueError:
        return None
    if (not predecessor_movements or any(day >= cutoff for day in predecessor_days)
            or _historically_reversed_payment_ids(predecessor_movements, cutoff, supported) is None):
        return None
    outgoing = predecessor_history.get("refinance_outgoing") or []
    # Both lifecycle views must contain the same unambiguous source link.
    if len(outgoing) != 1 or outgoing[0] != link:
        return None
    payoff_id = _text(link.get("payoff_movement_id"))
    disbursement_id = _text(link.get("disbursement_movement_id"))
    if not payoff_id or not disbursement_id or not _text(link.get("liquidation_id")):
        return None
    payoffs = [row for row in predecessor_movements if _text(row.get("ID_MOVIMIENTO_CARTERA")) == payoff_id]
    disbursements = [row for row in history.get("movements") or [] if role(row) == "disbursement"]
    if len(payoffs) != 1 or len(disbursements) != 1:
        return None
    payoff, disbursement = payoffs[0], disbursements[0]
    if (role(payoff) != "refinance-payoff-candidate"
            or _day(payoff.get("FECHA_OPERACION")) != payoff_day
            or _text(disbursement.get("ID_MOVIMIENTO_CARTERA")) != disbursement_id
            or _day(disbursement.get("FECHA_OPERACION")) != payoff_day
            or disbursement.get("MONTO") is None
            or _money(disbursement["MONTO"]) != _money(successor_snapshot.get("MONTO_DESEMBOLSADO"))
            or _money(disbursement["MONTO"]) <= 0):
        return None
    components = {
        "payoff_amount": _money(payoff.get("MONTO")),
        "payoff_principal": _money(payoff.get("MONTO_CAPITAL")),
        "payoff_interest": _money(payoff.get("MONTO_INTERES")) + _money(payoff.get("MONTO_INT_PENDIENTES")),
        "payoff_fee": _money(payoff.get("MONTO_SEGURO")),
        "payoff_penalty": _money(payoff.get("MONTO_MORA")) + _money(payoff.get("MONTO_RECARGOS")),
    }
    if (any(link.get(field) is None or _money(link[field]) != amount or amount < 0
            for field, amount in components.items())
            or components["payoff_amount"] <= 0
            or components["payoff_amount"] > _money(disbursement["MONTO"])):
        return None
    return {
        "policy": ("single-same-owner-historical-topup-v1" if same_owner
                   else "single-source-authorized-historical-topup-v2"),
        "predecessor_source_key": str(predecessor_id),
        "payoff_movement_id": payoff_id, "disbursement_movement_id": disbursement_id,
        "liquidation_id": _text(link["liquidation_id"]), "payoff_date": payoff_day,
        "predecessor_snapshot_id": str(snapshot["ID_CRD_HISTORICO_DIARIO"]),
        "successor_snapshot_id": str(successor_snapshot["ID_CRD_HISTORICO_DIARIO"]),
        "predecessor_closed_at_source_day": True,
        "predecessor_insurance_policy": insurance_policy,
        **terminal_proof,
    }


def _historical_refinance_proof(loan: dict, history: dict, loans: dict[int, dict],
                                lifecycles: dict[int, dict], source_day: str,
                                cutoff: str, supported: dict[str, str]) -> dict | None:
    incoming = history.get("refinance_incoming") or []
    if len(incoming) <= 1:
        return _single_historical_refinance_proof(loan, history, loans, lifecycles, source_day, cutoff, supported)
    proofs = []
    predecessors = set()
    payoffs = Decimal(0)
    for link in incoming:
        try:
            predecessor = int(link["old_credit_id"])
        except (KeyError, TypeError, ValueError):
            return None
        if predecessor in predecessors:
            return None
        proof = _single_historical_refinance_proof(loan, {**history, "refinance_incoming": [link]},
                                                   loans, lifecycles, source_day, cutoff, supported)
        if proof is None:
            return None
        predecessors.add(predecessor)
        proofs.append(proof)
        payoffs += _money(link["payoff_amount"])
    if payoffs > _money((loan.get("_mora_cutover_snapshot") or {}).get("MONTO_DESEMBOLSADO")):
        return None
    return {"policy": "complete-historical-consolidation-v2", "settlements": proofs,
            "all_predecessors_closed_at_source_day": True, "payoffs_within_disbursement": True}


def bound_active_loan_histories(loans: list[dict], lifecycles: dict[int, dict], cutoff: str,
                                supported_transactions: dict[str, str]) -> None:
    source_day = (date.fromisoformat(cutoff) - timedelta(days=1)).isoformat()
    loans_by_id = {int(loan["ID_CREDITO"]): loan for loan in loans}
    for loan in loans:
        counts = loan.get("_post_cutover_source_events") or {}
        history = lifecycles.get(int(loan["ID_CREDITO"])) or {}
        snapshot = loan.get("_mora_cutover_snapshot") or {}
        if (not counts or set(counts) != {"movements"} or loan.get("_mora_cutover_snapshot_missing")
                or _text(loan.get("source_state")) != "1" or _text(snapshot.get("ID_ESTADO_CARTERA")) != "1"
                or _day(snapshot.get("source_day")) != source_day
                or not _adjustments_are_historical(history, cutoff)):
            continue
        refinance_proof = _historical_refinance_proof(
            loan, history, loans_by_id, lifecycles, source_day, cutoff, supported_transactions,
        )
        if refinance_proof is None:
            continue
        movements = history.get("movements") or []
        later = [row for row in movements if _day(row.get("FECHA_OPERACION")) >= cutoff]
        prior = [row for row in movements if _day(row.get("FECHA_OPERACION")) < cutoff]
        def role(row: dict) -> str:
            return supported_transactions.get(f'{row.get("CODIGO_SISTEMA")}:{_text(row.get("ID_TRANSACCION"))}', "")
        payment_roles = {"repayment", "mobile-collection-repayment"}
        reversed_ids = _historically_reversed_payment_ids(movements, cutoff, supported_transactions)
        if (not later or len(later) != counts["movements"]
                or any(role(row) not in payment_roles for row in later)
                or reversed_ids is None
                or any(not _day(row.get("FECHA_OPERACION")) for row in movements)):
            continue
        payments = [row for row in prior if role(row) in payment_roles | {"adjusted-repayment"}
                    and _text(row.get("ID_MOVIMIENTO_CARTERA")) not in reversed_ids]
        # A dated close plus exact paid counters corroborates completeness of
        # retained principal/interest cash history; never just discard a guard.
        if any(snapshot.get(counter) is None or sum((_money(row.get(component)) for row in payments), Decimal(0))
               != _money(snapshot[counter]) for component, counter in
               (("MONTO_CAPITAL", "SALDO_PAGADO_CAPITAL"), ("MONTO_INTERES", "SALDO_PAGADO_INTERES"))):
            continue
        if snapshot.get("MONTO_DESEMBOLSADO") is None:
            continue
        later_ids = {_text(row["ID_MOVIMIENTO_CARTERA"]) for row in later}
        history["movements"] = prior
        history["charge_details"] = [row for row in history.get("charge_details") or []
                                     if _text(row.get("ID_MOVIMIENTO_CARTERA")) not in later_ids]
        for field in ("SALDO_INTERES", "SALDO_MORA", "SALDO_RECARGOS", "SALDO_SEGURO", "SALDO_TOTAL", "MONTO_DESEMBOLSADO"):
            if snapshot.get(field) is not None:
                loan[field] = snapshot[field]
        loan["ULTIMO_SALDO"] = _money(snapshot["MONTO_DESEMBOLSADO"]) - _money(snapshot["SALDO_PAGADO_CAPITAL"])
        loan["SALDO_CAPITAL"] = snapshot["SALDO_PAGADO_CAPITAL"]
        loan["_bounded_source_window"] = {
            "policy": "active-close-before-later-payments-v1", "source_through_date": source_day,
            "fineract_starts": cutoff, "excluded_movement_count": len(later),
            "excluded_movement_ids": sorted(later_ids), "paid_counters_corroborated": True,
        }
        if refinance_proof:
            loan["_bounded_source_window"]["policy"] = "active-historical-refinance-before-later-payments-v1"
            loan["_bounded_source_window"]["refinance_evidence"] = refinance_proof
        del loan["_post_cutover_source_events"]
