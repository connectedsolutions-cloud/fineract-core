"""Re-read Arissto to check closed-loan carry-forward candidates.

This is a read-only source/target diagnostic. It writes a temporary SQLite
plan, never the accepted cycle, and cannot authorize seed capture or restore.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from .carry_forward_estimate import evaluate_candidates, load_accepted_run
from .config import ROOT, load_settings
from .loans import LoanContract, build_loan_plan
from .state import State


def compare_source_candidates(
    accepted: dict[str, Any], fresh: dict[str, Any], candidate_keys: list[str],
) -> dict[str, Any]:
    """Compare the exact planner hashes, including the full loan lifecycle."""
    reasons: Counter[str] = Counter()
    if fresh.get("source_fingerprint") != accepted.get("source_fingerprint"):
        reasons["source_identity_changed"] += 1
    if fresh.get("contract_hash") != accepted.get("contract_hash"):
        reasons["loan_contract_changed"] += 1
    if fresh.get("migration_cutover_date") != accepted.get("migration_cutover_date"):
        reasons["planner_cutover_changed"] += 1
    if not fresh.get("applicable"):
        reasons["fresh_plan_not_applicable"] += 1
    accepted_actions = {
        str(action["source_key"]): action for action in accepted.get("actions", [])
        if action.get("entity_type") == "loan"
    }
    fresh_actions = {
        str(action["source_key"]): action for action in fresh.get("actions", [])
        if action.get("entity_type") == "loan"
    }
    unchanged = 0
    for key in candidate_keys:
        previous = accepted_actions.get(key)
        current = fresh_actions.get(key)
        if previous is None or current is None:
            reasons["source_loan_missing"] += 1
        elif current.get("quarantine_reasons") or current.get("action") == "quarantine-loan":
            reasons["source_loan_now_quarantined"] += 1
        elif (current.get("source_hash") != previous.get("source_hash")
              or current.get("lifecycle_hash") != previous.get("lifecycle_hash")):
            reasons["source_lifecycle_changed"] += 1
        else:
            unchanged += 1
    return {
        "candidate_count": len(candidate_keys),
        "fresh_source_unchanged": unchanged,
        "fresh_source_rejections": dict(sorted(reasons.items())),
        "source_candidates_match": not reasons and unchanged == len(candidate_keys),
        "ready_for_reset": False,
    }


def verify_fresh_source(state_path: Path, source_through_date: str) -> dict[str, Any]:
    accepted, item_status = load_accepted_run(state_path)
    estimate, candidate_keys = evaluate_candidates(
        accepted, item_status, source_through_date,
    )
    settings = load_settings("local")
    if settings.target.tenant != "sandbox" or accepted.get("target_fingerprint") != settings.target.fingerprint:
        raise ValueError("Accepted loan run does not belong to the local sandbox target")
    contract = LoanContract.load(ROOT / "config" / "loans.json")
    # A full-block source read uses one inspection. Explicit keys would run a
    # separate inspection for every candidate and become prohibitively slow.
    with tempfile.TemporaryDirectory(prefix="arissto-carry-forward-source-") as directory:
        scratch = State(Path(directory) / "state.sqlite3")
        try:
            _, fresh = build_loan_plan(
                settings, scratch, contract,
                migration_cutover_date=accepted.get("migration_cutover_date"),
            )
        finally:
            scratch.conn.close()
    return {
        "run_mode": "carry-forward-rebuild",
        "report_kind": "read-only-fresh-source-verification",
        "arissto_through": estimate["arissto_through"],
        "fineract_starts": estimate["fineract_starts"],
        **compare_source_candidates(accepted, fresh, candidate_keys),
        "missing_proofs": [
            "target_terminal_state_and_balances", "full_target_dependency_graph",
            "zero_GL_seed", "seed_checksum",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", required=True, type=Path)
    parser.add_argument("--source-through-date", required=True)
    args = parser.parse_args()
    report = verify_fresh_source(args.state_file, args.source_through_date)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["source_candidates_match"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
