"""LS-24: bounded retry roots must survive dependency and office-cohort closure."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.loans import LoanApplyControls, _selected_loan_actions, apply_loan_plan


class LoanRetryScopeTests(unittest.TestCase):
    def actions(self):
        return [
            {"source_key": "collateral-product:arissto", "entity_type": "collateral-product", "depends_on": []},
            {"source_key": "product:00010", "entity_type": "product", "depends_on": []},
            {"source_key": "product:00001", "entity_type": "product", "depends_on": []},
            {"source_key": "loan:1", "entity_type": "loan", "client_external_id": "transfer-A",
             "depends_on": ["product:00010", "collateral-product:arissto"]},
            {"source_key": "loan:2", "entity_type": "loan", "client_external_id": "transfer-A",
             "depends_on": ["product:00010", "loan:1"]},
            {"source_key": "loan:3", "entity_type": "loan", "client_external_id": "transfer-A",
             "depends_on": ["product:00010"]},
            {"source_key": "loan:4", "entity_type": "loan", "client_external_id": "unrelated",
             "depends_on": ["product:00010"]},
            {"source_key": "loan:5", "entity_type": "loan", "client_external_id": "other-product",
             "depends_on": ["product:00001", "collateral-product:arissto"]},
        ]

    @staticmethod
    def keys(actions):
        return [action["source_key"] for action in actions]

    def test_apply_keeps_original_roots_when_it_adds_a_transfer_cohort(self):
        # Probe the real apply selection path, stopping before API creation or any state journal write.
        actions = self.actions()
        transfers = [{"client_external_id": "transfer-A"}]
        plan = {"document": {"actions": actions, "client_office_transfers": transfers,
                             "scope": {"mode": "full-block"}}}
        state = MagicMock()
        calls = []

        def capture(*args, **kwargs):
            selected = _selected_loan_actions(*args, **kwargs)
            calls.append(self.keys(selected))
            return selected

        with (
            patch("arissto_sync.loans._loan_apply_guard", return_value=(plan, {"clients": {}})) as guard,
            patch("arissto_sync.loans._selected_loan_actions", side_effect=capture),
            patch("arissto_sync.loans.plan_client_office_transfers", return_value=transfers),
            patch("arissto_sync.loans.attach_pretransfer_loan_balances", return_value=transfers),
            patch("arissto_sync.loans.target_client_office_transfer_blockers", return_value=[]),
            patch("arissto_sync.loans.FineractApi", side_effect=RuntimeError("stop-before-writes")),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop-before-writes"):
                apply_loan_plan(SimpleNamespace(target=SimpleNamespace()), state, MagicMock(), "frozen-plan", only_keys={"loan:2"},
                                controls=LoanApplyControls(workers=1, pause_seconds=0, recovery_attempts=1))
        guard.assert_called_once()
        state.start_run.assert_not_called()
        state.record_item.assert_not_called()
        self.assertEqual(calls[-1], ["collateral-product:arissto", "product:00010", "loan:1", "loan:2", "loan:3"])

    def test_cohort_does_not_promote_product_or_collateral_prerequisites_to_roots(self):
        actions = self.actions()
        selected = _selected_loan_actions(actions, {"loan:2"}, client_office_transfers=[
            {"client_external_id": "transfer-A"},
        ])
        self.assertEqual(self.keys(selected), ["collateral-product:arissto", "product:00010",
                                               "loan:1", "loan:2", "loan:3"])

    def test_dependencies_discovered_through_a_cohort_expand_their_own_required_cohort(self):
        actions = self.actions()
        # A newly added A-cohort member depends on a B-cohort predecessor.
        actions[5]["depends_on"].append("loan:6")
        actions += [
            {"source_key": "loan:6", "entity_type": "loan", "client_external_id": "transfer-B",
             "depends_on": ["product:00001"]},
            {"source_key": "loan:7", "entity_type": "loan", "client_external_id": "transfer-B",
             "depends_on": ["product:00001"]},
        ]
        selected = _selected_loan_actions(actions, {"loan:2"}, client_office_transfers=[
            {"client_external_id": "transfer-A"}, {"client_external_id": "transfer-B"},
        ])
        self.assertEqual(self.keys(selected), ["collateral-product:arissto", "product:00010", "product:00001",
                                               "loan:1", "loan:2", "loan:3", "loan:6", "loan:7"])
        self.assertNotIn("loan:4", self.keys(selected))
        self.assertNotIn("loan:5", self.keys(selected))

    def test_explicit_failed_product_remains_a_root_but_added_product_does_not(self):
        actions = self.actions()
        actions[6]["depends_on"] = ["product:00001"]
        selected = _selected_loan_actions(actions, {"product:00010"}, client_office_transfers=[
            {"client_external_id": "transfer-A"},
        ])
        self.assertEqual(self.keys(selected), ["collateral-product:arissto", "product:00010",
                                               "loan:1", "loan:2", "loan:3"])
        # Explicitly selected collateral product still brings its own dependants and their prerequisites.
        selected = _selected_loan_actions(actions, {"collateral-product:arissto"}, client_office_transfers=[
            {"client_external_id": "transfer-A"},
        ])
        self.assertEqual(self.keys(selected), ["collateral-product:arissto", "product:00010", "product:00001",
                                               "loan:1", "loan:2", "loan:3", "loan:5"])

    def test_no_cohort_event_means_no_same_client_sibling_expansion(self):
        self.assertEqual(self.keys(_selected_loan_actions(self.actions(), {"loan:2"})),
                         ["collateral-product:arissto", "product:00010", "loan:1", "loan:2"])

    def test_selection_preserves_plan_order_objects_and_inputs(self):
        actions = self.actions()
        transfers = [{"client_external_id": "transfer-A"}]
        roots = {"loan:2"}
        before = copy.deepcopy((actions, transfers, roots))
        selected = _selected_loan_actions(actions, roots, client_office_transfers=transfers)
        self.assertEqual((actions, transfers, roots), before)
        for item in selected:
            self.assertIs(item, actions[self.keys(actions).index(item["source_key"])])
        self.assertEqual(self.keys(_selected_loan_actions(actions, set(self.keys(selected)) & {"loan:1", "loan:2", "loan:3"},
                                                          client_office_transfers=transfers)), self.keys(selected))

    def test_full_and_empty_scopes_keep_their_existing_meaning(self):
        actions = self.actions()
        transfers = [{"client_external_id": "transfer-A"}]
        self.assertIs(_selected_loan_actions(actions, None, client_office_transfers=transfers), actions)
        self.assertEqual(_selected_loan_actions(actions, set(), client_office_transfers=transfers), [])

    def test_unknown_requested_key_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "absent from the loans plan"):
            _selected_loan_actions(self.actions(), {"loan:missing"}, client_office_transfers=[])
