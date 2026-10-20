"""Verify saved closed-loan candidates against the local sandbox, read-only.

This checks loan-level target state only. It cannot prove source freshness, full
foreign-key graph closure, or that the current tenant is a usable seed.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .carry_forward_estimate import evaluate_candidates, load_accepted_run
from .config import TargetConfig, load_settings
from .connections import postgres_connection


def _zero(value: Any) -> bool:
    return value is not None and Decimal(str(value)) == 0


def candidate_rejection(
    action: dict[str, Any], mapping: tuple[Any, Any] | None,
    row: tuple[Any, ...] | None, late_count: int, charge_outstanding: Any,
    old_cutoff: date,
) -> str | None:
    expected_mapping_hash = (action.get("seed_source_hash")
                             if action.get("action") == "retained-loan"
                             else action["source_hash"])
    if mapping is None or not expected_mapping_hash or mapping[1] != expected_mapping_hash:
        return "mapping_missing_or_source_hash_changed"
    if row is None or str(row[1]) != str(mapping[0]):
        return "target_loan_missing_or_identity_changed"
    if action.get("target_id") is not None and str(row[1]) != str(action["target_id"]):
        return "target_loan_missing_or_identity_changed"
    if row[2] not in (600, 601, 602, 700) or row[3] is None or row[3] >= old_cutoff:
        return "target_not_closed_before_seed_cutoff"
    if not all(_zero(value) for value in row[4:9]) or not _zero(charge_outstanding):
        return "target_balance_not_zero"
    if late_count:
        return "target_transaction_on_or_after_seed_cutoff"
    return None


def verify_local_candidates_with_details(
    state_path: Path, target: TargetConfig, proposed_source_through: str,
    *, expected_isolated_cutoff: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, int], dict[str, str]]:
    if (target.name != "local" or target.tenant != "sandbox" or not target.pg_url
            or urlparse(target.pg_url).hostname not in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("Carry-forward verification is restricted to local sandbox")
    if expected_isolated_cutoff is not None and not re.fullmatch(
        r"/fineract_carry_seed_verify_[0-9]{8}", urlparse(target.pg_url).path,
    ):
        raise ValueError("New-cutoff verification requires an isolated restored seed")
    plan, item_status = load_accepted_run(state_path)
    report, keys = evaluate_candidates(plan, item_status, proposed_source_through)
    if plan.get("target_fingerprint") != target.fingerprint:
        raise ValueError("Saved loan plan belongs to a different Fineract target")
    old_cutoff = date.fromisoformat(plan["accounting_cutoff"]["date"])
    actions = {str(a["source_key"]): a for a in plan["actions"] if a.get("entity_type") == "loan"}
    external_ids = [str(actions[key]["external_id"]) for key in keys]
    with sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        candidate_set = set(keys)
        mappings = {key: (target_id, source_hash) for key, target_id, source_hash in conn.execute(
            "SELECT source_key,target_id,source_hash FROM mappings "
            "WHERE target_fingerprint=? AND block='loans'", (target.fingerprint,)
        ) if key in candidate_set}
    with postgres_connection(target.pg_url) as conn:
        cutoff = conn.execute("""
            SELECT cutoff_date,lifecycle_state,configuration_revision,configuration_hash
            FROM acc_accounting_cutoff_configuration WHERE id=1
        """).fetchone()
        expected_binding = expected_isolated_cutoff or plan["accounting_cutoff"]
        expected_date = date.fromisoformat(expected_binding["date"])
        if not cutoff or cutoff[0] != expected_date or cutoff[1] != "ACTIVE":
            raise ValueError("Target cutoff does not match the expected loan proof binding")
        if (expected_binding.get("configuration_revision") != cutoff[2]
                or expected_binding.get("configuration_hash") != cutoff[3]):
            raise ValueError("Current sandbox cutoff revision or hash changed")
        rows = conn.execute("""
            SELECT external_id,id,loan_status_id,closedon_date,
                   principal_outstanding_derived,interest_outstanding_derived,
                   fee_charges_outstanding_derived,penalty_charges_outstanding_derived,
                   total_outstanding_derived
            FROM m_loan WHERE external_id = ANY(%s)
        """, (external_ids,)).fetchall() if external_ids else []
        target_loans = {str(row[0]): row for row in rows}
        ids = [int(row[1]) for row in rows]
        late = {int(loan_id): int(count) for loan_id, count in conn.execute("""
            SELECT loan_id,COUNT(*) FROM m_loan_transaction
            WHERE loan_id = ANY(%s) AND transaction_date >= %s GROUP BY loan_id
        """, (ids, old_cutoff)).fetchall()} if ids else {}
        charges = {int(loan_id): amount for loan_id, amount in conn.execute("""
            SELECT loan_id,COALESCE(SUM(amount_outstanding_derived),0)
            FROM m_loan_charge WHERE loan_id = ANY(%s) GROUP BY loan_id
        """, (ids,)).fetchall()} if ids else {}
    reasons: Counter[str] = Counter()
    verified = 0
    target_eligible: dict[str, int] = {}
    rejected: dict[str, str] = {}
    for key in keys:
        action = actions[key]
        row = target_loans.get(str(action["external_id"]))
        rejection = candidate_rejection(
            action, mappings.get(key), row,
            late.get(int(row[1]), 0) if row else 0,
            charges.get(int(row[1]), Decimal("0")) if row else None,
            old_cutoff,
        )
        if rejection:
            reasons[rejection] += 1
            rejected[key] = rejection
        else:
            verified += 1
            target_eligible[key] = int(row[1])
    report.update({
        "report_kind": "read-only-target-loan-verification",
        "missing_proofs": ["fresh_source_hashes", "full_target_dependency_graph", "zero_GL_seed", "seed_checksum"],
        "target_verified_candidates": verified,
        "target_rejections": dict(sorted(reasons.items())),
        "current_cutoff_revision": cutoff[2],
        "ready_for_reset": False,
    })
    return report, target_eligible, rejected


def verify_local_candidates_with_ids(
    state_path: Path, target: TargetConfig, proposed_source_through: str,
) -> tuple[dict[str, Any], list[int]]:
    report, eligible, _ = verify_local_candidates_with_details(
        state_path, target, proposed_source_through,
    )
    return report, sorted(eligible.values())


def verify_local_candidates(
    state_path: Path, target: TargetConfig, proposed_source_through: str,
) -> dict[str, Any]:
    return verify_local_candidates_with_ids(state_path, target, proposed_source_through)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", required=True, type=Path)
    parser.add_argument("--source-through-date", required=True)
    parser.add_argument("--target", choices=("local",), required=True)
    args = parser.parse_args()
    report = verify_local_candidates(
        args.state_file, load_settings(args.target).target, args.source_through_date
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
