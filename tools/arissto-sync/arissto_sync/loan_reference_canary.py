from __future__ import annotations

from collections import Counter
from typing import Any

from .loans import CLOSED_REFINANCE_HISTORICAL_SCHEDULE_LOANS


CLOSED_REFINANCE_HISTORICAL_SCHEDULE_DESCENDANTS = (
    457, 481, 520, 553, 571, 597, 601, 707, 776, 820, 846, 847, 848, 876,
    878, 883, 900, 921, 949, 952, 1014, 1142, 1207, 1211, 1218, 1251, 1260,
    1276, 1317, 1323, 1343, 1345, 1357, 1374, 1416, 1500, 1509, 1542, 1559,
    1578, 1583, 1598, 1612, 1631, 1634, 1780, 1792, 1800, 1825, 1879, 1926,
    1935, 1941, 1974, 2135, 2155, 2322,
)

CONTRACTUAL_ANCHOR_CLASSIFICATION = "source-exact-contractual-origin-anchor"
REVIEWED_CONTRACTUAL_ANCHOR_QUARANTINE_COUNTS = {
    "reviewed_voided_refinance_attempt_omitted": 1,
}

CLOSED_ADJUSTED_SCHEDULE_LOANS = (23, 90, 317, 340, 359)
ACTIVE_ADJUSTED_SCHEDULE_LOANS = (479, 1738, 1841, 1869)
CLOSED_STALE_INSURANCE_RESIDUE_LOANS = (23, 317, 359)
REVIEWED_MANUAL_SCHEDULE_VARIANCE = "reviewed_manual_adjustment_schedule_variance"


def verify_adjusted_schedule_cohort(
    plan: dict[str, Any],
    *,
    run_items: list[dict[str, Any]] | None = None,
    reconciliation: dict[str, Any] | None = None,
    replay_items: list[dict[str, Any]] | None = None,
    replay_reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify the closed and active G5-SCH-009 adjusted-schedule contract."""
    actions = {
        str(action.get("source_key")): action
        for action in plan.get("document", {}).get("actions", [])
    }
    closed = {f"loan:{loan_id}" for loan_id in CLOSED_ADJUSTED_SCHEDULE_LOANS}
    active = {f"loan:{loan_id}" for loan_id in ACTIVE_ADJUSTED_SCHEDULE_LOANS}
    closed_stale_insurance = {
        f"loan:{loan_id}" for loan_id in CLOSED_STALE_INSURANCE_RESIDUE_LOANS
    }
    cohort = closed | active

    missing = sorted(cohort - actions.keys())
    quarantined = sorted(
        source_key for source_key in cohort & actions.keys()
        if actions[source_key].get("action") == "quarantine-loan"
        or actions[source_key].get("quarantine_reasons")
    )
    policy_failures: list[dict[str, Any]] = []
    for source_key in sorted(cohort & actions.keys()):
        lifecycle = actions[source_key].get("lifecycle") or {}
        policy = lifecycle.get("schedule_reconciliation_policy")
        writer = lifecycle.get("schedule_writer")
        active_policy = lifecycle.get("active_manual_schedule_import_policy") or {}
        stale_insurance_policy = lifecycle.get("closed_stale_insurance_residue_policy") or {}
        if source_key in closed:
            valid = policy == "reviewed-manual-adjustment" and writer is None
            if source_key in closed_stale_insurance:
                valid = valid and (
                    stale_insurance_policy.get("classification")
                    == "closed-stale-source-insurance-residue"
                    and stale_insurance_policy.get("native_fee_balance") == "0.00"
                    and stale_insurance_policy.get("authoritative_terminal_total") == "0.00"
                    and stale_insurance_policy.get("requires_source_exact_event_reconstruction") is True
                    and bool(lifecycle.get("events"))
                )
        else:
            valid = (
                policy == "exact-source-schedule"
                and writer == "fineract-source-exact-active-schedule-v1"
                and active_policy.get("classification")
                == "reviewed-active-manual-schedule-import"
            )
        if not valid:
            policy_failures.append({
                "source_key": source_key,
                "schedule_reconciliation_policy": policy,
                "schedule_writer": writer,
                "active_classification": active_policy.get("classification"),
                "stale_insurance_classification": stale_insurance_policy.get("classification"),
            })

    def incomplete(
        items: list[dict[str, Any]] | None, accepted_statuses: set[str],
    ) -> list[dict[str, Any]]:
        if items is None:
            return []
        items_by_key = {str(item.get("source_key")): item for item in items}
        return [
            {
                "source_key": source_key,
                "status": None if (item := items_by_key.get(source_key)) is None else item.get("status"),
                "error_code": None if item is None else item.get("error_code"),
            }
            for source_key in sorted(cohort)
            if (item := items_by_key.get(source_key)) is None
            or item.get("status") not in accepted_statuses
        ]

    def reconciliation_findings(result: dict[str, Any] | None) -> tuple[list, list]:
        if result is None:
            return [], []
        blocking = [
            row
            for field in ("failed_or_quarantined", "mismatches")
            for row in result.get(field, [])
            if str(row.get("source_key")) in cohort
        ]
        unexpected_variances = [
            row for row in result.get("variances", [])
            if str(row.get("source_key")) in cohort
            and not (
                str(row.get("source_key")) in closed
                and row.get("classification") == REVIEWED_MANUAL_SCHEDULE_VARIANCE
            )
        ]
        return blocking, unexpected_variances

    run_incomplete = incomplete(run_items, {"succeeded", "recovered", "unchanged"})
    replay_incomplete = incomplete(replay_items, {"recovered", "unchanged"})
    blocking_findings, unexpected_variances = reconciliation_findings(reconciliation)
    replay_blocking_findings, replay_unexpected_variances = reconciliation_findings(
        replay_reconciliation
    )
    missing_evidence = []
    if run_items is None:
        missing_evidence.append("run")
    if reconciliation is None:
        missing_evidence.append("reconciliation")
    if replay_items is None:
        missing_evidence.append("replay")
    if replay_reconciliation is None:
        missing_evidence.append("replay_reconciliation")

    accepted = not (
        missing or quarantined or policy_failures or missing_evidence
        or run_incomplete or replay_incomplete
        or blocking_findings or unexpected_variances
        or replay_blocking_findings or replay_unexpected_variances
    )
    accepted = accepted and bool(reconciliation and reconciliation.get("ok"))
    accepted = accepted and bool(replay_reconciliation and replay_reconciliation.get("ok"))
    return {
        "accepted": accepted,
        "closed_members": sorted(closed),
        "active_members": sorted(active),
        "missing_members": missing,
        "quarantined_members": quarantined,
        "policy_failures": policy_failures,
        "run_incomplete": run_incomplete,
        "replay_incomplete": replay_incomplete,
        "blocking_findings": blocking_findings,
        "unexpected_variances": unexpected_variances,
        "replay_blocking_findings": replay_blocking_findings,
        "replay_unexpected_variances": replay_unexpected_variances,
        "missing_evidence": missing_evidence,
    }


def verify_contractual_anchor_cohort(
    plan: dict[str, Any],
    *,
    run_items: list[dict[str, Any]] | None = None,
    reconciliation: dict[str, Any] | None = None,
    replay_items: list[dict[str, Any]] | None = None,
    replay_reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify G5-SCH-008 from the plan classifier, never a frozen loan-ID list."""
    actions = {
        str(action.get("source_key")): action
        for action in plan.get("document", {}).get("actions", [])
    }
    members = {
        source_key for source_key, action in actions.items()
        if ((action.get("lifecycle") or {}).get("contractual_schedule_anchor_policy") or {}).get(
            "classification"
        ) == CONTRACTUAL_ANCHOR_CLASSIFICATION
    }
    quarantined_members = {
        source_key for source_key in members
        if actions[source_key].get("action") == "quarantine-loan"
        or actions[source_key].get("quarantine_reasons")
    }
    supported_members = members - quarantined_members

    quarantine_counts = Counter(
        reason
        for source_key, action in actions.items()
        if source_key in members
        if action.get("action") == "quarantine-loan"
        for reason in action.get("quarantine_reasons", [])
    )
    quarantine_set_matches = (
        dict(quarantine_counts) == REVIEWED_CONTRACTUAL_ANCHOR_QUARANTINE_COUNTS
    )

    def incomplete(
        items: list[dict[str, Any]] | None, accepted_statuses: set[str],
    ) -> list[dict[str, Any]]:
        if items is None:
            return []
        items_by_key = {str(item.get("source_key")): item for item in items}
        return [
            {
                "source_key": source_key,
                "status": None if (item := items_by_key.get(source_key)) is None else item.get("status"),
                "error_code": None if item is None else item.get("error_code"),
            }
            for source_key in sorted(supported_members)
            if (item := items_by_key.get(source_key)) is None
            or item.get("status") not in accepted_statuses
        ]

    run_incomplete = incomplete(run_items, {"succeeded", "recovered", "unchanged"})
    replay_incomplete = incomplete(replay_items, {"recovered", "unchanged"})

    def schedule_findings(result: dict[str, Any] | None) -> list[dict[str, Any]]:
        if result is None:
            return []
        return [
            row for row in result.get("mismatches", [])
            if str(row.get("source_key")) in members
            and "schedule" in str(row.get("kind", "")).lower()
        ]

    reconciliation_schedule_findings = schedule_findings(reconciliation)
    replay_schedule_findings = schedule_findings(replay_reconciliation)
    missing_evidence = []
    if run_items is None:
        missing_evidence.append("run")
    if reconciliation is None:
        missing_evidence.append("reconciliation")
    if replay_items is None:
        missing_evidence.append("replay")
    if replay_reconciliation is None:
        missing_evidence.append("replay_reconciliation")

    accepted = bool(members) and quarantine_set_matches and not missing_evidence
    accepted = accepted and not run_incomplete and not replay_incomplete
    accepted = accepted and bool(reconciliation and reconciliation.get("ok"))
    accepted = accepted and bool(replay_reconciliation and replay_reconciliation.get("ok"))
    accepted = accepted and not reconciliation_schedule_findings and not replay_schedule_findings
    return {
        "accepted": accepted,
        "classification": CONTRACTUAL_ANCHOR_CLASSIFICATION,
        "member_count": len(members),
        "supported_member_count": len(supported_members),
        "quarantined_member_count": len(quarantined_members),
        "quarantined_members": sorted(quarantined_members),
        "reviewed_quarantine_counts": dict(sorted(quarantine_counts.items())),
        "expected_reviewed_quarantine_counts": REVIEWED_CONTRACTUAL_ANCHOR_QUARANTINE_COUNTS,
        "quarantine_set_matches": quarantine_set_matches,
        "run_incomplete": run_incomplete,
        "replay_incomplete": replay_incomplete,
        "reconciliation_schedule_findings": reconciliation_schedule_findings,
        "replay_schedule_findings": replay_schedule_findings,
        "missing_evidence": missing_evidence,
    }


def verify_closed_refinance_historical_canary(
    plan: dict[str, Any],
    *,
    run_items: list[dict[str, Any]] | None = None,
    reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify the reviewed 20 roots and their 57 dependency descendants."""
    actions = {
        str(action.get("source_key")): action
        for action in plan.get("document", {}).get("actions", [])
    }
    roots = {f"loan:{loan_id}" for loan_id in CLOSED_REFINANCE_HISTORICAL_SCHEDULE_LOANS}
    descendants = {
        f"loan:{loan_id}" for loan_id in CLOSED_REFINANCE_HISTORICAL_SCHEDULE_DESCENDANTS
    }
    impacted = roots | descendants

    missing_roots = sorted(roots - actions.keys())
    missing_descendants = sorted(descendants - actions.keys())
    root_policy_failures = []
    quarantined = []
    for source_key in sorted(impacted & actions.keys()):
        action = actions[source_key]
        lifecycle = action.get("lifecycle") or {}
        if action.get("action") == "quarantine-loan" or action.get("quarantine_reasons"):
            quarantined.append(source_key)
        if source_key in roots and (
            lifecycle.get("schedule_reconciliation_policy") != "historical-reference-only"
            or lifecycle.get("schedule_writer") is not None
        ):
            root_policy_failures.append(source_key)

    incomplete_items: list[dict[str, Any]] = []
    if run_items is not None:
        items_by_key = {str(item.get("source_key")): item for item in run_items}
        accepted_statuses = {"succeeded", "recovered", "unchanged"}
        for source_key in sorted(impacted):
            item = items_by_key.get(source_key)
            if item is None or item.get("status") not in accepted_statuses:
                incomplete_items.append({
                    "source_key": source_key,
                    "status": None if item is None else item.get("status"),
                    "error_code": None if item is None else item.get("error_code"),
                })

    blocking_findings: list[dict[str, Any]] = []
    if reconciliation is not None:
        blocking_findings.extend(
            row for row in reconciliation.get("failed_or_quarantined", [])
            if str(row.get("source_key")) in impacted
        )
        blocking_findings.extend(
            row for row in reconciliation.get("mismatches", [])
            if str(row.get("source_key")) in impacted
        )

    plan_ready = not (
        missing_roots or missing_descendants or root_policy_failures or quarantined
    )
    run_ready = run_items is None or not incomplete_items
    reconciliation_ready = reconciliation is None or (
        bool(reconciliation.get("ok")) and not blocking_findings
    )
    return {
        "accepted": plan_ready and run_ready and reconciliation_ready,
        "root_count": len(roots),
        "descendant_count": len(descendants),
        "impacted_count": len(impacted),
        "missing_roots": missing_roots,
        "missing_descendants": missing_descendants,
        "root_policy_failures": root_policy_failures,
        "quarantined": quarantined,
        "incomplete_items": incomplete_items,
        "blocking_findings": blocking_findings,
        "phase": (
            "reconciled" if reconciliation is not None
            else "applied" if run_items is not None
            else "planned"
        ),
    }
