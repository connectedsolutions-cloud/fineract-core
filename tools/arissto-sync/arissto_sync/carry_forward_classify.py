"""Classify loans for a narrow, closed-and-unchanged carry-forward seed.

Closed, unchanged loans with unproved but known related-record edges remain
retention-review candidates. This report does not authorize staging or tenant
replacement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .carry_forward_graph import audit_retention_related_rows, nonretained_loan_edges
from .carry_forward_source import (
    build_fresh_source_snapshot, compare_source_candidates, source_candidate_rejections,
)
from .carry_forward_verify import verify_local_candidates_with_details
from .config import load_settings
from .connections import postgres_connection


def _loan_actions(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["source_key"]): item for item in document.get("actions", [])
        if item.get("entity_type") == "loan"
    }


def _refinance_edges(actions: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for key, action in actions.items():
        refinance = (action.get("lifecycle") or {}).get("refinance") or {}
        for settlement in refinance.get("settlements") or []:
            predecessor = "loan:" + str(settlement["predecessor_source_key"])
            graph[key].add(predecessor)
            graph[predecessor].add(key)
    return graph


def _propagate_refinance_exclusion(
    rows: dict[str, dict[str, Any]], *action_sets: dict[str, dict[str, Any]],
) -> None:
    graph: dict[str, set[str]] = defaultdict(set)
    for actions in action_sets:
        for key, neighbors in _refinance_edges(actions).items():
            graph[key].update(neighbors)
    visited: set[str] = set()
    for key in rows:
        if key in visited:
            continue
        component = {key}
        pending = [key]
        while pending:
            current = pending.pop()
            for neighbor in graph[current] - component:
                component.add(neighbor)
                pending.append(neighbor)
        visited.update(component)
        members = component & rows.keys()
        if len(members) < 2 or all(rows[member]["disposition"] == "retain-candidate" for member in members):
            continue
        dispositions = {rows[member]["disposition"] for member in members}
        disposition = (
            "block" if "block" in dispositions else
            "replay" if "replay" in dispositions else "retain-review"
        )
        for member in members:
            if rows[member]["disposition"] != disposition:
                rows[member]["disposition"] = disposition
                rows[member]["reasons"].append(
                    "refinance_component_requires_review" if disposition == "retain-review"
                    else "refinance_component_excluded"
                )


def classify_rows(
    accepted: dict[str, Any], fresh: dict[str, Any], candidate_keys: list[str],
    source_rejections: dict[str, str], target_eligible: dict[str, int],
    target_rejections: dict[str, str], edge_reasons: dict[int, set[str]],
) -> dict[str, dict[str, Any]]:
    accepted_actions = _loan_actions(accepted)
    fresh_actions = _loan_actions(fresh)
    candidate_set = set(candidate_keys)
    rows: dict[str, dict[str, Any]] = {}
    for key in sorted(accepted_actions.keys() | fresh_actions.keys()):
        previous = accepted_actions.get(key)
        current = fresh_actions.get(key)
        reasons: list[str] = []
        disposition = "replay"
        target_id = target_eligible.get(key)
        if current is None:
            disposition = "block"
            reasons.append("source_loan_missing")
        elif current.get("quarantine_reasons") or current.get("action") == "quarantine-loan":
            disposition = "block"
            reasons.append("source_loan_quarantined")
        elif key not in candidate_set:
            reasons.append("not_closed_unchanged_candidate" if previous else "new_source_loan")
        else:
            source_reason = source_rejections.get(key)
            target_reason = target_rejections.get(key)
            if source_reason:
                reasons.append(source_reason)
                if source_reason != "source_lifecycle_changed":
                    disposition = "block"
            if target_reason:
                reasons.append(target_reason)
                if target_reason in {
                    "mapping_missing_or_source_hash_changed",
                    "target_loan_missing_or_identity_changed",
                    "target_transaction_on_or_after_seed_cutoff",
                }:
                    disposition = "block"
            if not reasons and target_id is not None:
                for edge_reason in sorted(edge_reasons.get(target_id, ())):
                    reasons.append(edge_reason)
                    if edge_reason.startswith("unproved_edge:"):
                        disposition = "block"
                if reasons and disposition != "block":
                    disposition = "retain-review"
                elif not reasons:
                    disposition = "retain-candidate"
            elif not reasons:
                disposition = "block"
                reasons.append("target_candidate_unaccounted")
        rows[key] = {
            "source_key": key,
            "source_hash": current.get("source_hash") if current else None,
            "mapping_source_hash": (
                previous.get("seed_source_hash") or previous.get("source_hash")
            ) if previous else None,
            "lifecycle_hash": current.get("lifecycle_hash") if current else None,
            "target_id": target_id,
            "disposition": disposition,
            "reasons": reasons,
        }
    _propagate_refinance_exclusion(rows, accepted_actions, fresh_actions)
    return rows


def bind_retained_proofs(
    rows: dict[str, dict[str, Any]], binding: dict[str, str], old_cutoff: dict[str, Any],
) -> None:
    """Bind each provisional retention to the accepted run and old cutoff."""
    for row in rows.values():
        if row["disposition"] != "retain-candidate":
            continue
        proof = {
            "source_key": row["source_key"],
            "source_hash": row["source_hash"],
            "lifecycle_hash": row["lifecycle_hash"],
            "target_id": row["target_id"],
            "accepted_run_id": binding["accepted_run_id"],
            "accepted_plan_id": binding["accepted_plan_id"],
            "accepted_reconciliation_hash": binding["accepted_reconciliation_hash"],
            "old_cutoff": old_cutoff,
        }
        row["retention_proof_hash"] = hashlib.sha256(json.dumps(
            proof, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()


def summarize_refinance_review(
    accepted: dict[str, Any], fresh: dict[str, Any], candidate_keys: list[str],
    rows: dict[str, dict[str, Any]],
) -> dict[str, int]:
    """Show closed refinance groups excluded by unproved graph transfer."""
    graph: dict[str, set[str]] = defaultdict(set)
    for actions in (_loan_actions(accepted), _loan_actions(fresh)):
        for key, neighbors in _refinance_edges(actions).items():
            graph[key].update(neighbors)
    candidates = set(candidate_keys)
    refinance_only_edges = {
        "review_edge:m_loan_topup",
        "review_edge:m_loan_refinancing_settlement",
        "review_edge:m_account_transfer_details",
    }
    result = Counter()
    visited: set[str] = set()
    for key in graph:
        if key in visited:
            continue
        component = {key}
        pending = [key]
        while pending:
            current = pending.pop()
            for neighbor in graph[current] - component:
                component.add(neighbor)
                pending.append(neighbor)
        visited.update(component)
        frozen = component & candidates
        if not frozen:
            continue
        result["frozen_candidate_loans_in_refinance_groups"] += len(frozen)
        result["frozen_candidate_refinance_groups"] += 1
        if not component <= candidates:
            result["groups_with_non_candidate_member"] += 1
            continue
        reasons = {reason for member in component for reason in rows[member]["reasons"]}
        source_or_target_reasons = {
            reason for reason in reasons
            if not reason.startswith(("review_edge:", "unproved_edge:"))
            and reason not in {"refinance_component_excluded", "refinance_component_requires_review"}
        }
        if source_or_target_reasons:
            result["groups_needing_source_or_target_review"] += 1
            result["loans_needing_source_or_target_review"] += len(component)
        elif reasons <= refinance_only_edges:
            result["groups_with_only_refinance_direct_edges"] += 1
            result["loans_with_only_refinance_direct_edges"] += len(component)
        else:
            result["groups_with_other_direct_edges"] += 1
            result["loans_with_other_direct_edges"] += len(component)
    return dict(sorted(result.items()))


def inspect_classification(
    state_path: Path, source_through_date: str, env_file: str | None = None,
) -> dict[str, Any]:
    settings = load_settings("local", env_file)
    accepted, fresh, estimate, candidate_keys, started_at, finished_at, binding = (
        build_fresh_source_snapshot(state_path, source_through_date, env_file)
    )
    source_comparison = compare_source_candidates(accepted, fresh, candidate_keys)
    global_failures = {key: value for key, value in source_comparison["fresh_source_rejections"].items()
                       if key in {"source_identity_changed", "loan_contract_changed",
                                  "planner_cutover_changed", "fresh_plan_not_applicable"}}
    if global_failures:
        raise ValueError(f"Global source plan changed: {sorted(global_failures)}")
    target_report, target_eligible, target_rejections = verify_local_candidates_with_details(
        state_path, settings.target, source_through_date,
    )
    source_rejections = source_candidate_rejections(accepted, fresh, candidate_keys)
    with postgres_connection(settings.target.pg_url) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        edge_reasons = nonretained_loan_edges(
            conn, sorted(target_eligible.values()), rebuild_mobile_metadata=True,
        )
        target_external_ids = {str(external_id) for (external_id,) in conn.execute(
            "SELECT external_id FROM m_loan"
        ).fetchall()}
        rows = classify_rows(accepted, fresh, candidate_keys, source_rejections,
                             target_eligible, target_rejections, edge_reasons)
        bind_retained_proofs(rows, binding, accepted["accounting_cutoff"])
        potential_ids = sorted(int(row["target_id"]) for row in rows.values()
                               if row["disposition"] in {"retain-candidate", "retain-review"})
        related_rows = audit_retention_related_rows(conn, potential_ids)
    fresh_external_ids = {str(action["external_id"]) for action in _loan_actions(fresh).values()}
    target_only_count = len(target_external_ids - fresh_external_ids)
    refinance_review = summarize_refinance_review(accepted, fresh, candidate_keys, rows)
    ordered = [rows[key] for key in sorted(rows)]
    digest = hashlib.sha256(json.dumps(ordered, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    counts = Counter(row["disposition"] for row in ordered)
    reason_counts = Counter(reason for row in ordered for reason in row["reasons"])
    return {
        "report_kind": "read-only-carry-forward-loan-classification-v1",
        "arissto_through": estimate["arissto_through"],
        "fineract_starts": estimate["fineract_starts"],
        "old_fineract_starts": estimate["prior_fineract_starts"],
        "source_read_started_at": started_at,
        "source_read_finished_at": finished_at,
        "loan_count": len(ordered),
        "counts": dict(sorted(counts.items())),
        "reasons": dict(sorted(reason_counts.items())),
        "target_only_loan_count": target_only_count,
        "classification_hash": digest,
        "accepted_run_binding": binding,
        "old_cutoff_binding": accepted["accounting_cutoff"],
        "target_rejections": target_report["target_rejections"],
        "planned_mobile_metadata_action": "rebuild-through-mobile-collections-service",
        "refinance_retention_review": refinance_review,
        "related_row_audit": related_rows,
        "loans": ordered,
        "ready_for_seed": False,
        "missing_proofs": ["transitive_dependencies", "refinance_transfer_graph",
                           "mobile_collection_rebuild_and_reconcile", "target_lifecycle_row_hashes",
                           "staged_seed_restore", "new_cycle_mapping_import"],
    }


def write_private_classification(
    report: dict[str, Any], output: Path, env_file: str | None = None,
) -> None:
    root = (load_settings("local", env_file).state_path.parent / "carry-forward").resolve()
    output = output.resolve()
    if not output.is_relative_to(root):
        raise ValueError("Classification output must stay under private carry-forward state")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.parent.chmod(0o700)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent,
            prefix=".classification-", suffix=".json", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--source-through-date", required=True)
    parser.add_argument("--output", type=Path,
                        help="private JSON detail file inside .arissto-sync/carry-forward")
    args = parser.parse_args()
    report = inspect_classification(args.state_file, args.source_through_date)
    if args.output:
        write_private_classification(report, args.output)
    public = {key: value for key, value in report.items() if key != "loans"}
    print(json.dumps(public, indent=2, sort_keys=True))
    return 0 if public["counts"].get("block", 0) == 0 and public["target_only_loan_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
