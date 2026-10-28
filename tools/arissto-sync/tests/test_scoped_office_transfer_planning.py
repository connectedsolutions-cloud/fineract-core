import copy
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.client_office_transfers import (
    client_office_transfer_cohort_blockers, extract_client_office_transfer_cohorts,
)
from arissto_sync.loans import build_loan_plan, apply_loan_plan, _loan_apply_guard


class ScopedOfficeTransferPlanningTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(source=object(), target=SimpleNamespace(name="local", fingerprint="target"))
        self.contract = SimpleNamespace(digest="contract", raw={"supported_transactions": {}})
        self.events = [{"source_client_id": 1, "client_external_id": "client-A",
                        "active_source_loans": [{"source_loan_id": 3}]}]
        self.cohorts = [{"client_external_id": "client-A", "source_loan_keys": ["loan:1", "loan:2", "loan:3"]}]
        self.actions = [{"entity_type": "loan", "source_key": f"loan:{n}",
                         "client_external_id": "client-A", "action": "recover-loan",
                         "lifecycle": {"interest_recalculation_policy": "source-exact-off-v1"}} for n in (1, 2, 3)]

    def test_inventory_includes_inactive_loans_and_queries_only_touched_clients(self):
        with (patch("arissto_sync.arissto.source_connection") as conn,
              patch("arissto_sync.client_office_transfers.select_rows", return_value=[
                  {"source_loan_id": n} for n in (3, 1, 2, 2)]) as select):
            result = extract_client_office_transfer_cohorts(self.settings, self.events * 2)
        self.assertEqual(result, self.cohorts)
        select.assert_called_once()
        sql, params = select.call_args.args[1:]
        self.assertEqual(params, (1,))
        self.assertIn("WHERE s.ID_ASOCIADO=?", sql)
        self.assertNotIn("SALDO", sql)
        self.assertNotIn("ESTADO", sql)
        with patch("arissto_sync.arissto.source_connection") as conn:
            self.assertEqual(extract_client_office_transfer_cohorts(self.settings, []), [])
            conn.assert_not_called()

    def test_complete_cohort_is_allowed_without_mutating_inputs(self):
        before = copy.deepcopy((self.events, self.cohorts, self.actions))
        self.assertEqual(client_office_transfer_cohort_blockers(self.events, self.cohorts, self.actions), [])
        self.assertEqual((self.events, self.cohorts, self.actions), before)

    def test_missing_closed_or_zero_balance_member_is_blocked(self):
        self.assertEqual(client_office_transfer_cohort_blockers(self.events, self.cohorts, self.actions[1:]),
                         ["scoped_client_office_transfer_cohort_incomplete"])

    def test_wrong_owner_uninventoried_active_and_empty_proofs_are_blocked(self):
        actions = copy.deepcopy(self.actions)
        actions[0]["client_external_id"] = "client-B"
        for cohorts, candidate in ((self.cohorts, actions), ([], self.actions),
                                   ([{**self.cohorts[0], "source_loan_keys": ["loan:1", "loan:2"]}], self.actions[:2])):
            self.assertTrue(client_office_transfer_cohort_blockers(self.events, cohorts, candidate))

    def build(self, actions=None, target_blockers=None, events=None, keys=("3",)):
        events = self.events if events is None else events
        document = {"actions": copy.deepcopy(self.actions if actions is None else actions),
                    "readiness_blockers": [], "applicable": True, "source_fingerprint": "source"}
        inspection = {"source_blockers": [], "target_blockers": [],
                      "schema_signature": "s", "target_schema_signature": "t"}
        state = MagicMock()
        with ExitStack() as stack:
            mocks = {
                "_plan_scope_inspections": [inspection], "extract_loan_plan_rows": ([], []),
                "extract_loan_lifecycle_rows": {}, "attach_loan_cutover_source_evidence": None,
                "bound_active_loan_histories": None, "resolve_loan_product_target": {"clients": {}},
                "compose_loan_plan": document, "plan_client_office_transfers": events,
                "attach_pretransfer_loan_balances": events,
                "extract_client_office_transfer_cohorts": self.cohorts,
                "target_client_office_transfer_blockers": target_blockers or [],
            }
            for name, value in mocks.items():
                stack.enter_context(patch(f"arissto_sync.loans.{name}", return_value=value))
            return build_loan_plan(self.settings, state, self.contract, list(keys) if keys else None,
                                   migration_cutover_date="2026-10-27")[1]

    def test_build_allows_complete_scoped_transfer_and_freezes_proof(self):
        plan = self.build()
        self.assertTrue(plan["applicable"])
        self.assertEqual(plan["readiness_blockers"], [])
        self.assertEqual(plan["client_office_transfer_cohorts"], self.cohorts)

    def test_build_still_blocks_incomplete_quarantined_and_multiple_transfers(self):
        for actions, events, expected in (
            (self.actions[1:], self.events, "scoped_client_office_transfer_cohort_incomplete"),
            ([{**a, "action": "quarantine-loan"} for a in self.actions], self.events,
             "transfer_client_has_quarantined_loan"),
            (self.actions, self.events * 2, "multiple_client_office_transfers_need_review"),
        ):
            plan = self.build(actions, events=events)
            self.assertFalse(plan["applicable"])
            self.assertIn(expected, plan["readiness_blockers"])

    def test_existing_target_and_mixed_retention_guards_stay_blocking(self):
        for blocker in ("client_office_transfer_requires_savings_after_loans",
                        "historical_office_transfer_requires_fresh_or_prefixed_loan_target"):
            plan = self.build(target_blockers=[blocker])
            self.assertFalse(plan["applicable"])
            self.assertIn(blocker, plan["readiness_blockers"])
        actions = copy.deepcopy(self.actions)
        actions[0]["action"] = "unchanged-loan"
        self.assertIn("mixed_retained_and_replayed_transfer_cohort", self.build(actions)["readiness_blockers"])

    def test_full_and_no_transfer_plans_do_not_require_new_proof(self):
        self.assertNotIn("client_office_transfer_cohorts", self.build(keys=()))
        self.assertNotIn("client_office_transfer_cohorts", self.build(events=[]))

    def guard_plan(self):
        return {"block": "loans", "target_fingerprint": "target", "source_fingerprint": "source",
                "contract_hash": "contract", "document": {
                    "component_alignment_plan_revision": 10, "historical_replay_policy": "source-exact-off-v1", "final_metric_alignment_revision": 2,
                    "accrual_control_revision": 1, "source_observed_at": "2026-10-27",
                    "applicable": True, "scope": {"mode": "explicit-source-keys", "requested_source_keys": ["3"]},
                    "client_office_transfers": self.events, "actions": self.actions,
                    "client_office_transfer_cohorts": copy.deepcopy(self.cohorts),
                    "product_writer_registered": True, "loan_writer_registered": True,
                    "collateral_writer_registered": True}}

    def test_drift_missing_proof_and_incomplete_actions_fail_before_any_writes(self):
        for kind, expected in (("drift", "cohort_changed_after_plan"),
                               ("removed", "cohort_changed_after_plan"),
                               ("legacy", "predates_client_office_transfer_cohort_proof"),
                               ("incomplete", "cohort_incomplete")):
            state = MagicMock()
            plan = self.guard_plan()
            actual = copy.deepcopy(self.cohorts)
            if kind == "drift":
                actual[0]["source_loan_keys"].append("loan:4")
            elif kind == "removed":
                actual[0]["source_loan_keys"].pop()
            elif kind == "legacy":
                del plan["document"]["client_office_transfer_cohorts"]
            else:
                plan["document"]["actions"] = self.actions[1:]
            state.plan.return_value = plan
            with (patch("arissto_sync.loans.source_fingerprint", return_value="source"),
                  patch("arissto_sync.loans.extract_client_office_transfer_cohorts", return_value=actual),
                  patch("arissto_sync.loans.FineractApi") as api,
                  patch("arissto_sync.loans._plan_scope_inspections") as inspect):
                with self.assertRaisesRegex(RuntimeError, expected):
                    apply_loan_plan(self.settings, state, self.contract, "plan")
                api.assert_not_called()
                state.start_run.assert_not_called()
                inspect.assert_not_called()

    def test_complete_proof_reaches_existing_source_guard_and_full_plan_is_compatible(self):
        for mode in ("explicit-source-keys", "full-block"):
            plan = self.guard_plan()
            plan["document"]["scope"]["mode"] = mode
            state = MagicMock()
            state.plan.return_value = plan
            with (patch("arissto_sync.loans.source_fingerprint", return_value="source"),
                  patch("arissto_sync.loans.extract_client_office_transfer_cohorts", return_value=self.cohorts) as extract,
                  patch("arissto_sync.loans._plan_scope_inspections", side_effect=RuntimeError("existing source guard"))):
                with self.assertRaisesRegex(RuntimeError, "existing source guard"):
                    _loan_apply_guard(self.settings, state, self.contract, "plan", None)
                self.assertEqual(extract.call_count, int(mode == "explicit-source-keys"))


if __name__ == "__main__":
    unittest.main()
