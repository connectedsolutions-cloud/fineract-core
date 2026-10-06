"""Read-only upper bound for closed loans a future carry-forward seed might retain.

This report is deliberately not an eligibility proof or a reset command. It uses
an accepted loan run's frozen source plan; the eventual seed builder must also
re-read Arissto and verify the complete Fineract dependency graph.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def _zero(value: Any) -> bool:
    try:
        return Decimal(str(value or 0)) == 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def evaluate_candidates(
    plan: dict[str, Any], item_status: dict[str, str], proposed_source_through: str,
) -> tuple[dict[str, Any], list[str]]:
    prior = plan.get("accounting_cutoff") or {}
    old_t = date.fromisoformat(str(prior["date"]))
    proposed_s = date.fromisoformat(proposed_source_through)
    if proposed_s.isoformat() != proposed_source_through:
        raise ValueError("Arissto through date must use YYYY-MM-DD")
    new_t = proposed_s + timedelta(days=1)
    if new_t <= old_t:
        raise ValueError("Carry-forward estimate requires a later Fineract start date")
    scope = plan.get("scope") or {}
    if scope.get("mode") != "full-block" or scope.get("proof_namespace"):
        raise ValueError("Carry-forward estimate requires a full-block, non-proof loan plan")
    actions = {str(a["source_key"]): a for a in plan.get("actions", []) if a.get("entity_type") == "loan"}
    reasons: dict[str, set[str]] = defaultdict(set)
    edges: dict[str, set[str]] = defaultdict(set)
    for key, action in actions.items():
        lifecycle = action.get("lifecycle") or {}
        expected = lifecycle.get("expected") or {}
        if expected.get("source_state") != "3":
            reasons[key].add("not_source_closed")
        if action.get("action") == "quarantine-loan" or action.get("quarantine_reasons"):
            reasons[key].add("quarantined")
        if item_status.get(key) not in {"succeeded", "recovered", "unchanged", "reconciled"}:
            reasons[key].add("not_accepted_in_run")
        if any(not _zero(expected.get(field)) for field in (
            "principal_balance", "interest_balance", "penalty_balance", "fee_balance", "total_outstanding"
        )):
            reasons[key].add("nonzero_expected_balance")
        if any(not event.get("date") or date.fromisoformat(str(event["date"])) >= old_t
               for event in lifecycle.get("events") or []):
            reasons[key].add("event_on_or_after_old_cutoff")
        refinance = lifecycle.get("refinance") or {}
        for settlement in refinance.get("settlements") or []:
            predecessor = "loan:" + str(settlement["predecessor_source_key"])
            if predecessor not in actions:
                reasons[key].add("missing_refinance_member")
                continue
            edges[key].add(predecessor)
            edges[predecessor].add(key)
    visited: set[str] = set()
    for key in actions:
        if key in visited:
            continue
        component = {key}
        pending = [key]
        while pending:
            current = pending.pop()
            for neighbor in edges[current] - component:
                component.add(neighbor)
                pending.append(neighbor)
        visited.update(component)
        if any(reasons[member] for member in component):
            for member in component:
                if not reasons[member]:
                    reasons[member].add("refinance_component_not_closed")
    candidate_keys = sorted(key for key in actions if not reasons[key])
    candidates = len(candidate_keys)
    report = {
        "run_mode": "carry-forward-rebuild",
        "report_kind": "read-only-upper-bound",
        "arissto_through": proposed_source_through,
        "fineract_starts": new_t.isoformat(),
        "prior_fineract_starts": old_t.isoformat(),
        "total_loans": len(actions),
        "potential_closed_loans": candidates,
        "excluded_by_reason": dict(sorted(Counter(reason for values in reasons.values() for reason in values).items())),
        "ready_for_reset": False,
        "missing_proofs": ["fresh_source_hashes", "target_terminal_state_and_balances", "dependency_graph", "zero_GL_seed", "seed_checksum"],
    }
    return report, candidate_keys


def estimate(plan: dict[str, Any], item_status: dict[str, str], proposed_source_through: str) -> dict[str, Any]:
    return evaluate_candidates(plan, item_status, proposed_source_through)[0]


def load_accepted_run(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """Read the latest accepted full-block loan run without changing cycle state."""
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        row = conn.execute("""
            SELECT p.document, r.id
            FROM runs r JOIN plans p ON p.id = r.plan_id
            JOIN reconciliations rec ON rec.run_id = r.id
            WHERE p.block = 'loans' AND rec.ok = 1 AND r.status IN ('completed', 'completed-with-quarantine')
            ORDER BY r.started_at DESC LIMIT 1
        """).fetchone()
        if row is None:
            raise ValueError("No completed, reconciled loan run is available in this cycle")
        plan = json.loads(row[0])
        item_status = {key: status for key, status in conn.execute(
            "SELECT source_key,status FROM items WHERE run_id = ?", (row[1],)
        )}
    return plan, item_status


def estimate_from_state(path: Path, proposed_source_through: str) -> dict[str, Any]:
    plan, item_status = load_accepted_run(path)
    return estimate(plan, item_status, proposed_source_through)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", required=True, type=Path)
    parser.add_argument("--source-through-date", required=True)
    args = parser.parse_args()
    print(json.dumps(estimate_from_state(args.state_file, args.source_through_date), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
