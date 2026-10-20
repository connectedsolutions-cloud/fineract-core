"""Re-read Arissto to check closed-loan carry-forward candidates.

This is a read-only source/target diagnostic. It writes a temporary SQLite
plan, never the accepted cycle, and cannot authorize seed capture or restore.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .carry_forward_estimate import evaluate_candidates, load_accepted_run_details
from .config import ROOT, load_settings
from .loans import LoanContract, build_loan_plan
from .state import State


def source_candidate_rejections(
    accepted: dict[str, Any], fresh: dict[str, Any], candidate_keys: list[str],
) -> dict[str, str]:
    """Return one stable source reason for each candidate that changed."""
    accepted_actions = {
        str(action["source_key"]): action for action in accepted.get("actions", [])
        if action.get("entity_type") == "loan"
    }
    fresh_actions = {
        str(action["source_key"]): action for action in fresh.get("actions", [])
        if action.get("entity_type") == "loan"
    }
    rejected: dict[str, str] = {}
    for key in candidate_keys:
        previous = accepted_actions.get(key)
        current = fresh_actions.get(key)
        if previous is None or current is None:
            rejected[key] = "source_loan_missing"
        elif current.get("quarantine_reasons") or current.get("action") == "quarantine-loan":
            rejected[key] = "source_loan_now_quarantined"
        elif (current.get("source_hash") != previous.get("source_hash")
              or current.get("lifecycle_hash") != previous.get("lifecycle_hash")):
            rejected[key] = "source_lifecycle_changed"
    return rejected


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
    rejected = source_candidate_rejections(accepted, fresh, candidate_keys)
    reasons.update(rejected.values())
    unchanged = len(candidate_keys) - len(rejected)
    return {
        "candidate_count": len(candidate_keys),
        "fresh_source_unchanged": unchanged,
        "fresh_source_rejections": dict(sorted(reasons.items())),
        "source_candidates_match": not reasons and unchanged == len(candidate_keys),
        "ready_for_reset": False,
    }


def build_fresh_source_snapshot(
    state_path: Path, source_through_date: str, env_file: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str], str, str, dict[str, str]]:
    accepted, item_status, binding = load_accepted_run_details(state_path)
    estimate, candidate_keys = evaluate_candidates(
        accepted, item_status, source_through_date,
    )
    settings = load_settings("local", env_file)
    if settings.target.tenant != "sandbox" or accepted.get("target_fingerprint") != settings.target.fingerprint:
        raise ValueError("Accepted loan run does not belong to the local sandbox target")
    contract = LoanContract.load(ROOT / "config" / "loans.json")
    # A full-block source read uses one inspection. Explicit keys would run a
    # separate inspection for every candidate and become prohibitively slow.
    source_read_started_at = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="arissto-carry-forward-source-") as directory:
        scratch = State(Path(directory) / "state.sqlite3")
        try:
            _, fresh = build_loan_plan(
                settings, scratch, contract,
                migration_cutover_date=accepted.get("migration_cutover_date"),
            )
        finally:
            scratch.conn.close()
    source_read_finished_at = datetime.now(timezone.utc).isoformat()
    return accepted, fresh, estimate, candidate_keys, source_read_started_at, source_read_finished_at, binding


def verify_fresh_source(state_path: Path, source_through_date: str) -> dict[str, Any]:
    accepted, fresh, estimate, candidate_keys, started_at, finished_at, _ = (
        build_fresh_source_snapshot(state_path, source_through_date)
    )
    return {
        "run_mode": "carry-forward-rebuild",
        "report_kind": "read-only-fresh-source-verification",
        "arissto_through": estimate["arissto_through"],
        "fineract_starts": estimate["fineract_starts"],
        "source_read_started_at": started_at,
        "source_read_finished_at": finished_at,
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
