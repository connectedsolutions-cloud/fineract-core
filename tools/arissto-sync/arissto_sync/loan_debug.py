from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from .config import Settings
from .connections import postgres_connection
from .loans import BLOCK, LoanContract, _amount
from .state import State


ELIGIBLE_ITEM_STATUSES = {"succeeded", "recovered"}
TERMINAL_TARGET_STATUSES = {600, 601, 602, 700}
REVERSAL_ROLES = {"repayment-reversal", "disbursement-reversal"}


def _status_matches(source_state: str, target_status: int, terminal_disbursement_reversal: bool) -> bool:
    if source_state == "1":
        return target_status == 300
    if source_state == "2":
        return target_status in {100, 200}
    if source_state == "3":
        return target_status == 200 if terminal_disbursement_reversal else target_status in TERMINAL_TARGET_STATUSES
    return False


def _transaction(row: tuple[Any, ...]) -> dict[str, Any]:
    columns = (
        "id", "external_id", "reversal_external_id", "type", "date", "amount",
        "principal", "interest", "fee", "penalty", "reversed", "source_exact_allocation",
    )
    return dict(zip(columns, row))


def _successor_context(
    event: dict[str, Any], actions: dict[str, dict[str, Any]], items: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    successor_id = event.get("successor_source_key")
    if successor_id in (None, ""):
        return None
    successor_key = f"loan:{successor_id}"
    successor = actions.get(successor_key) or {}
    item = items.get(successor_key) or {}
    return {
        "source_key": successor_key,
        "action": successor.get("action"),
        "external_id": successor.get("external_id"),
        "depends_on": list(successor.get("depends_on") or []),
        "quarantine_reasons": list(successor.get("quarantine_reasons") or []),
        "run_status": item.get("status"),
        "run_error": item.get("error_code"),
        "target_id": item.get("target_id") or successor.get("target_id"),
    }


def _suggested_disposition(
    mismatches: list[dict[str, Any]], event_rows: list[dict[str, Any]],
) -> tuple[str, str]:
    if not mismatches:
        return "clean", "All bounded event, status, and cutover checks match."
    aliases = [row for row in event_rows if row["diagnostic_match"] == "refinance-disbursement-alias"]
    strict_missing = [row for row in event_rows if row["strict_match"] == "missing"]
    genuine_missing = [row for row in strict_missing if row not in aliases]
    if strict_missing and not genuine_missing:
        return (
            "fix-reconciliation-identity",
            "Fineract contains the disbursement under a deterministic refinancing alias; no financial replay is needed.",
        )
    missing_payoffs = [row for row in genuine_missing if row["role"] == "native-refinance-payoff"]
    if missing_payoffs:
        successors = [row.get("successor") or {} for row in missing_payoffs]
        if any(row.get("run_status") == "quarantined" for row in successors):
            return (
                "review-or-quarantine-refinance-chain",
                "The predecessor payoff is created by a successor that was quarantined; disposition must cover the whole chain.",
            )
        return (
            "repair-successor-then-replay-chain",
            "The predecessor payoff is created atomically by its successor refinancing disbursement.",
        )
    kinds = {row["kind"] for row in mismatches}
    if kinds and kinds <= {"terminal_status", "cutover_total"}:
        return (
            "replan-terminal-adjustment",
            "All planned source events exist, but the closed source loan still has native target residuals.",
        )
    return "manual-review", "The event and balance evidence does not match a bounded automated recovery policy."


def debug_loan_run(
    settings: Settings,
    state: State,
    contract: LoanContract,
    run_id: str,
    source_keys: set[str] | None = None,
    include_clean: bool = False,
) -> dict[str, Any]:
    """Build a read-only, event-level Arissto-plan versus Fineract-Postgres report."""
    if not settings.target.pg_url:
        raise ValueError("Loan debug requires the selected target PostgreSQL URL")
    run = state.run(run_id)
    if run["block"] != BLOCK:
        raise ValueError("Debug run is not a loans run")
    if run["target_fingerprint"] != settings.target.fingerprint:
        raise ValueError("Debug run belongs to a different target fingerprint")
    plan = state.plan(run["plan_id"])
    actions = {
        row["source_key"]: row for row in plan["document"]["actions"]
        if row.get("entity_type") == "loan"
    }
    items = {row["source_key"]: row for row in state.run_items(run_id)}
    if source_keys:
        unknown = sorted(source_keys - set(actions))
        if unknown:
            raise ValueError("Source keys are absent from the run plan: " + ",".join(unknown))

    external_ids = [
        action["external_id"] for key, action in actions.items()
        if items.get(key, {}).get("status") in ELIGIBLE_ITEM_STATUSES
        and (not source_keys or key in source_keys)
    ]
    target_loans: dict[str, dict[str, Any]] = {}
    target_events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    with postgres_connection(settings.target.pg_url) as conn:
        if external_ids:
            rows = conn.execute(
                """
                SELECT id,external_id,loan_status_id,principal_outstanding_derived,
                       interest_outstanding_derived,fee_charges_outstanding_derived,
                       penalty_charges_outstanding_derived,total_outstanding_derived
                FROM m_loan WHERE external_id = ANY(%s)
                """,
                (external_ids,),
            ).fetchall()
            for row in rows:
                target_loans[str(row[1])] = {
                    "id": int(row[0]), "external_id": row[1], "status_id": int(row[2]),
                    "principal_outstanding": row[3], "interest_outstanding": row[4],
                    "fee_outstanding": row[5], "penalty_outstanding": row[6],
                    "total_outstanding": row[7],
                }
            loan_ids = [row["id"] for row in target_loans.values()]
            if loan_ids:
                rows = conn.execute(
                    """
                    SELECT loan_id,id,external_id,reversal_external_id,transaction_type_enum,
                           transaction_date,amount,principal_portion_derived,interest_portion_derived,
                           fee_charges_portion_derived,penalty_charges_portion_derived,is_reversed,
                           is_source_exact_allocation
                    FROM m_loan_transaction WHERE loan_id = ANY(%s)
                    ORDER BY loan_id,transaction_date,id
                    """,
                    (loan_ids,),
                ).fetchall()
                for row in rows:
                    target_events[int(row[0])].append(_transaction(row[1:]))

    results = []
    mismatch_counts: Counter[str] = Counter()
    disposition_counts: Counter[str] = Counter()
    for source_key, action in sorted(actions.items(), key=lambda item: int(item[0].split(":", 1)[1])):
        item = items.get(source_key) or {}
        if item.get("status") not in ELIGIBLE_ITEM_STATUSES or (source_keys and source_key not in source_keys):
            continue
        target = target_loans.get(action["external_id"])
        mismatches: list[dict[str, Any]] = []
        if target is None:
            mismatches.append({"kind": "target_loan_missing"})
            event_rows: list[dict[str, Any]] = []
        else:
            lifecycle = action["lifecycle"]
            expected = lifecycle["expected"]
            events = target_events[target["id"]]
            by_external_id = {str(row["external_id"]): row for row in events if row.get("external_id")}
            terminal_reversal = bool(lifecycle["events"]) and lifecycle["events"][-1]["role"] == "disbursement-reversal"
            if not _status_matches(expected["source_state"], target["status_id"], terminal_reversal):
                mismatches.append({
                    "kind": "terminal_status", "source": expected["source_state"],
                    "target": target["status_id"],
                })
            principal_delta = _amount(expected["principal_balance"]) - _amount(target["principal_outstanding"])
            if abs(principal_delta) > Decimal("0.01") and expected["source_state"] != "1":
                mismatches.append({
                    "kind": "principal_balance", "source": expected["principal_balance"],
                    "target": target["principal_outstanding"], "delta": principal_delta,
                })
            cutover_delta = _amount(expected["total_outstanding"]) - _amount(target["total_outstanding"])
            if abs(cutover_delta) > Decimal("0.01") and expected["source_state"] != "1":
                mismatches.append({
                    "kind": "cutover_total", "source": expected["total_outstanding"],
                    "target": target["total_outstanding"], "delta": cutover_delta,
                })
            event_rows = []
            for planned in lifecycle["events"]:
                external_id = str(planned["external_id"])
                target_event = by_external_id.get(external_id)
                strict_match = "exact" if target_event else "missing"
                diagnostic_match = strict_match
                alias_event = None
                if target_event is None and planned["role"] == "disbursement":
                    aliases = [
                        row for row in events
                        if str(row.get("external_id") or "").startswith(external_id + ":REFINANCE:")
                        and int(row.get("type") or -1) == 1
                    ]
                    if len(aliases) == 1:
                        alias_event = aliases[0]
                        diagnostic_match = "refinance-disbursement-alias"
                if target_event is None and planned["role"] not in REVERSAL_ROLES:
                    mismatches.append({
                        "kind": "transaction_missing", "movement": planned.get("source_movement_id"),
                        "role": planned["role"], "external_id": external_id,
                        "diagnostic_match": diagnostic_match,
                    })
                event_rows.append({
                    "role": planned["role"], "source_movement_id": planned.get("source_movement_id"),
                    "external_id": external_id, "date": planned.get("date"),
                    "amount": planned.get("amount"), "allocation": planned.get("allocation"),
                    "strict_match": strict_match, "diagnostic_match": diagnostic_match,
                    "target_event": target_event or alias_event,
                    "successor": _successor_context(planned, actions, items),
                })
        if not mismatches and not include_clean:
            continue
        disposition, reason = _suggested_disposition(mismatches, event_rows)
        mismatch_counts.update(row["kind"] for row in mismatches)
        disposition_counts[disposition] += 1
        results.append({
            "source_key": source_key, "external_id": action["external_id"],
            "run_item": item, "expected": (action.get("lifecycle") or {}).get("expected"),
            "target": target, "mismatches": mismatches,
            "suggested_disposition": disposition, "disposition_reason": reason,
            "planned_events": event_rows,
            "fineract_events": target_events[target["id"]] if target else [],
        })

    return {
        "run_id": run_id, "plan_id": run["plan_id"], "target": settings.target.name,
        "plan_contract_hash": plan["contract_hash"], "current_contract_hash": contract.digest,
        "contract_changed": plan["contract_hash"] != contract.digest,
        "read_only": True, "affected_loan_count": len(results),
        "mismatch_counts": dict(mismatch_counts),
        "suggested_disposition_counts": dict(disposition_counts),
        "loans": results,
    }
