from __future__ import annotations

import unittest

from arissto_sync.loan_reference_canary import (
    ACTIVE_ADJUSTED_SCHEDULE_LOANS,
    CLOSED_ADJUSTED_SCHEDULE_LOANS,
    CLOSED_STALE_INSURANCE_RESIDUE_LOANS,
    CLOSED_REFINANCE_HISTORICAL_SCHEDULE_DESCENDANTS,
    REVIEWED_CONTRACTUAL_ANCHOR_QUARANTINE_COUNTS,
    verify_adjusted_schedule_cohort,
    verify_closed_refinance_historical_canary,
    verify_contractual_anchor_cohort,
)
from arissto_sync.loans import CLOSED_REFINANCE_HISTORICAL_SCHEDULE_LOANS


class ClosedRefinanceHistoricalCanaryTests(unittest.TestCase):
    def plan(self):
        actions = []
        for loan_id in CLOSED_REFINANCE_HISTORICAL_SCHEDULE_LOANS:
            actions.append({
                "source_key": f"loan:{loan_id}",
                "action": "create-loan",
                "quarantine_reasons": [],
                "lifecycle": {
                    "schedule_reconciliation_policy": "historical-reference-only",
                    "schedule_writer": None,
                },
            })
        for loan_id in CLOSED_REFINANCE_HISTORICAL_SCHEDULE_DESCENDANTS:
            actions.append({
                "source_key": f"loan:{loan_id}",
                "action": "create-loan",
                "quarantine_reasons": [],
                "lifecycle": {
                    "schedule_reconciliation_policy": "exact-source-schedule",
                    "schedule_writer": "fineract-variable-installments-v1",
                },
            })
        return {"document": {"actions": actions}}

    def test_plan_requires_all_20_roots_and_57_descendants(self):
        report = verify_closed_refinance_historical_canary(self.plan())

        self.assertTrue(report["accepted"])
        self.assertEqual(report["root_count"], 20)
        self.assertEqual(report["descendant_count"], 57)
        self.assertEqual(report["impacted_count"], 77)
        self.assertEqual(report["phase"], "planned")

    def test_runtime_and_reconciliation_must_be_clean_for_all_77(self):
        plan = self.plan()
        items = [
            {"source_key": action["source_key"], "status": "succeeded", "error_code": None}
            for action in plan["document"]["actions"]
        ]
        reconciliation = {
            "ok": True, "failed_or_quarantined": [], "mismatches": [], "variances": [],
        }

        clean = verify_closed_refinance_historical_canary(
            plan, run_items=items, reconciliation=reconciliation,
        )
        self.assertTrue(clean["accepted"])
        self.assertEqual(clean["phase"], "reconciled")

        items[-1]["status"] = "blocked"
        reconciliation["ok"] = False
        reconciliation["mismatches"] = [{
            "source_key": items[-1]["source_key"], "kind": "blocking_schedule_mismatch",
        }]
        failed = verify_closed_refinance_historical_canary(
            plan, run_items=items, reconciliation=reconciliation,
        )
        self.assertFalse(failed["accepted"])
        self.assertEqual(len(failed["incomplete_items"]), 1)
        self.assertEqual(len(failed["blocking_findings"]), 1)

    def test_policy_or_scope_regression_fails_closed(self):
        plan = self.plan()
        plan["document"]["actions"][0]["lifecycle"][
            "schedule_reconciliation_policy"
        ] = "exact-source-schedule"
        missing_key = f"loan:{CLOSED_REFINANCE_HISTORICAL_SCHEDULE_DESCENDANTS[-1]}"
        plan["document"]["actions"] = [
            action for action in plan["document"]["actions"]
            if action["source_key"] != missing_key
        ]

        report = verify_closed_refinance_historical_canary(plan)

        self.assertFalse(report["accepted"])
        self.assertEqual(len(report["root_policy_failures"]), 1)
        self.assertEqual(report["missing_descendants"], [missing_key])


class AdjustedScheduleCohortTests(unittest.TestCase):
    def plan(self):
        actions = []
        for loan_id in CLOSED_ADJUSTED_SCHEDULE_LOANS:
            stale_insurance_policy = None
            if loan_id in CLOSED_STALE_INSURANCE_RESIDUE_LOANS:
                stale_insurance_policy = {
                    "classification": "closed-stale-source-insurance-residue",
                    "source_insurance_residue": "0.01",
                    "authoritative_terminal_total": "0.00",
                    "native_fee_balance": "0.00",
                    "requires_source_exact_event_reconstruction": True,
                }
            actions.append({
                "source_key": f"loan:{loan_id}",
                "action": "recover-loan",
                "quarantine_reasons": [],
                "lifecycle": {
                    "schedule_reconciliation_policy": "reviewed-manual-adjustment",
                    "schedule_writer": None,
                    "active_manual_schedule_import_policy": None,
                    "closed_stale_insurance_residue_policy": stale_insurance_policy,
                    "events": [{"role": "repayment"}],
                },
            })
        for loan_id in ACTIVE_ADJUSTED_SCHEDULE_LOANS:
            actions.append({
                "source_key": f"loan:{loan_id}",
                "action": "recover-loan",
                "quarantine_reasons": [],
                "lifecycle": {
                    "schedule_reconciliation_policy": "exact-source-schedule",
                    "schedule_writer": "fineract-source-exact-active-schedule-v1",
                    "active_manual_schedule_import_policy": {
                        "classification": "reviewed-active-manual-schedule-import",
                    },
                },
            })
        return {"document": {"actions": actions}}

    def items(self, status="recovered"):
        return [
            {"source_key": action["source_key"], "status": status, "error_code": None}
            for action in self.plan()["document"]["actions"]
        ]

    def test_accepts_exact_active_schedules_and_closed_reviewed_variances(self):
        closed_key = f"loan:{CLOSED_ADJUSTED_SCHEDULE_LOANS[0]}"
        reconciliation = {
            "ok": True,
            "failed_or_quarantined": [],
            "mismatches": [],
            "variances": [{
                "source_key": closed_key,
                "kind": "installment_interest",
                "classification": "reviewed_manual_adjustment_schedule_variance",
            }],
        }

        report = verify_adjusted_schedule_cohort(
            self.plan(),
            run_items=self.items("succeeded"),
            reconciliation=reconciliation,
            replay_items=self.items(),
            replay_reconciliation=reconciliation,
        )

        self.assertTrue(report["accepted"])
        self.assertEqual(report["missing_members"], [])
        self.assertEqual(report["policy_failures"], [])

    def test_missing_evidence_and_policy_drift_fail_closed(self):
        plan = self.plan()
        plan["document"]["actions"][0]["lifecycle"][
            "schedule_reconciliation_policy"
        ] = "historical-reference-only"

        report = verify_adjusted_schedule_cohort(plan, run_items=self.items())

        self.assertFalse(report["accepted"])
        self.assertEqual(len(report["policy_failures"]), 1)
        self.assertEqual(
            report["missing_evidence"],
            ["reconciliation", "replay", "replay_reconciliation"],
        )

    def test_known_stale_insurance_canary_requires_dynamic_policy_and_events(self):
        plan = self.plan()
        stale_key = f"loan:{CLOSED_STALE_INSURANCE_RESIDUE_LOANS[0]}"
        action = next(
            row for row in plan["document"]["actions"] if row["source_key"] == stale_key
        )
        action["lifecycle"]["closed_stale_insurance_residue_policy"] = None

        report = verify_adjusted_schedule_cohort(plan)

        self.assertFalse(report["accepted"])
        self.assertEqual([row["source_key"] for row in report["policy_failures"]], [stale_key])

    def test_active_variance_blocking_finding_and_replay_write_fail_closed(self):
        active_key = f"loan:{ACTIVE_ADJUSTED_SCHEDULE_LOANS[0]}"
        run_items = self.items("succeeded")
        replay_items = self.items()
        replay_items[-1]["status"] = "succeeded"
        reconciliation = {
            "ok": False,
            "failed_or_quarantined": [],
            "mismatches": [{"source_key": active_key, "kind": "terminal_status"}],
            "variances": [{
                "source_key": active_key,
                "kind": "installment_interest",
                "classification": "native_schedule_component_variance",
            }],
        }

        report = verify_adjusted_schedule_cohort(
            self.plan(),
            run_items=run_items,
            reconciliation=reconciliation,
            replay_items=replay_items,
            replay_reconciliation={
                "ok": True, "failed_or_quarantined": [], "mismatches": [], "variances": [],
            },
        )

        self.assertFalse(report["accepted"])
        self.assertEqual(len(report["blocking_findings"]), 1)
        self.assertEqual(len(report["unexpected_variances"]), 1)
        self.assertEqual(len(report["replay_incomplete"]), 1)


class ContractualAnchorCohortTests(unittest.TestCase):
    def plan(self):
        actions = [
            {
                "source_key": "loan:dynamic-a",
                "action": "create-loan",
                "quarantine_reasons": [],
                "lifecycle": {
                    "contractual_schedule_anchor_policy": {
                        "classification": "source-exact-contractual-origin-anchor",
                    },
                },
            },
            {
                "source_key": "loan:dynamic-b",
                "action": "create-loan",
                "quarantine_reasons": [],
                "lifecycle": {
                    "contractual_schedule_anchor_policy": {
                        "classification": "source-exact-contractual-origin-anchor",
                    },
                },
            },
        ]
        for reason, count in REVIEWED_CONTRACTUAL_ANCHOR_QUARANTINE_COUNTS.items():
            for index in range(count):
                actions.append({
                    "source_key": f"quarantine:{reason}:{index}",
                    "action": "quarantine-loan",
                    "quarantine_reasons": [reason],
                    "lifecycle": {
                        "contractual_schedule_anchor_policy": {
                            "classification": "source-exact-contractual-origin-anchor",
                        },
                    },
                })
        return {"document": {"actions": actions}}

    def test_derives_members_and_accepts_clean_run_and_replay(self):
        plan = self.plan()
        run_items = [
            {"source_key": "loan:dynamic-a", "status": "succeeded", "error_code": None},
            {"source_key": "loan:dynamic-b", "status": "recovered", "error_code": None},
        ]
        replay_items = [
            {"source_key": "loan:dynamic-a", "status": "recovered", "error_code": None},
            {"source_key": "loan:dynamic-b", "status": "unchanged", "error_code": None},
        ]
        clean = {"ok": True, "mismatches": []}

        report = verify_contractual_anchor_cohort(
            plan,
            run_items=run_items,
            reconciliation=clean,
            replay_items=replay_items,
            replay_reconciliation=clean,
        )

        self.assertTrue(report["accepted"])
        self.assertEqual(report["member_count"], 3)
        self.assertEqual(report["supported_member_count"], 2)
        self.assertTrue(report["quarantine_set_matches"])

    def test_missing_reconciliation_and_replay_remain_explicit(self):
        plan = self.plan()
        run_items = [
            {"source_key": "loan:dynamic-a", "status": "recovered", "error_code": None},
            {"source_key": "loan:dynamic-b", "status": "recovered", "error_code": None},
        ]

        report = verify_contractual_anchor_cohort(plan, run_items=run_items)

        self.assertFalse(report["accepted"])
        self.assertEqual(
            report["missing_evidence"],
            ["reconciliation", "replay", "replay_reconciliation"],
        )
        self.assertEqual(report["run_incomplete"], [])

    def test_fails_on_schedule_mismatch_unreviewed_quarantine_or_replay_write(self):
        plan = self.plan()
        plan["document"]["actions"].append({
            "source_key": "loan:unexpected",
            "action": "quarantine-loan",
            "quarantine_reasons": ["unexpected_reason"],
            "lifecycle": {
                "contractual_schedule_anchor_policy": {
                    "classification": "source-exact-contractual-origin-anchor",
                },
            },
        })
        run_items = [
            {"source_key": "loan:dynamic-a", "status": "recovered", "error_code": None},
            {"source_key": "loan:dynamic-b", "status": "recovered", "error_code": None},
        ]
        replay_items = [
            {"source_key": "loan:dynamic-a", "status": "succeeded", "error_code": None},
            {"source_key": "loan:dynamic-b", "status": "recovered", "error_code": None},
        ]
        reconciliation = {
            "ok": False,
            "mismatches": [{
                "source_key": "loan:dynamic-b",
                "kind": "installment_schedule_mismatch",
            }],
        }

        report = verify_contractual_anchor_cohort(
            plan,
            run_items=run_items,
            reconciliation=reconciliation,
            replay_items=replay_items,
            replay_reconciliation={"ok": True, "mismatches": []},
        )

        self.assertFalse(report["accepted"])
        self.assertFalse(report["quarantine_set_matches"])
        self.assertEqual(len(report["reconciliation_schedule_findings"]), 1)
        self.assertEqual(len(report["replay_incomplete"]), 1)


if __name__ == "__main__":
    unittest.main()
