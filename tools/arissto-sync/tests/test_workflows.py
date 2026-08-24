import unittest
from unittest.mock import patch

from arissto_sync.family_references import filter_family_references_by_owner
from arissto_sync.workflows import apply_clients_with_family_references, successful_client_source_keys


class FakeState:
    def __init__(self, items=None):
        self.items = items or []

    def plan(self, plan_id):
        return {"id": plan_id, "block": "clients"}

    def run_items(self, run_id):
        return self.items


class ClientFamilyWorkflowTests(unittest.TestCase):
    def test_owner_filter_is_exact_and_empty_scope_stays_empty(self):
        rows = [
            {"affiliation_number": "A-1", "reference_slot": 1},
            {"affiliation_number": "A-2", "reference_slot": 1},
        ]
        self.assertEqual(filter_family_references_by_owner(rows, set()), [])
        self.assertEqual(filter_family_references_by_owner(rows, {" A-2 "}), [rows[1]])
        with self.assertRaisesRegex(ValueError, "exact NUMERO_AFILIACION"):
            filter_family_references_by_owner(rows, {"A-1:1"})

    def test_successful_client_keys_exclude_failed_and_quarantined_items(self):
        state = FakeState([
            {"source_key": "A", "status": "succeeded"},
            {"source_key": "B", "status": "unchanged"},
            {"source_key": "C", "status": "failed"},
            {"source_key": "D", "status": "quarantined"},
        ])
        self.assertEqual(successful_client_source_keys(state, "run"), {"A", "B"})

    @patch("arissto_sync.workflows.build_family_reference_plan")
    @patch("arissto_sync.workflows.reconcile")
    @patch("arissto_sync.workflows.apply_plan")
    def test_client_reconciliation_failure_stops_dependent_service(self, apply_client, reconcile_client, build_family):
        apply_client.return_value = ("client-run", {"failed": 1})
        reconcile_client.return_value = {"ok": False, "counts": {"failed": 1}}
        result = apply_clients_with_family_references(object(), FakeState(), object(), object(), "client-plan")
        self.assertFalse(result["ok"])
        self.assertEqual(result["stopped_after"], "client-reconciliation")
        build_family.assert_not_called()

    @patch("arissto_sync.workflows.reconcile_family_references")
    @patch("arissto_sync.workflows.apply_family_reference_plan")
    @patch("arissto_sync.workflows.build_family_reference_plan")
    @patch("arissto_sync.workflows.reconcile")
    @patch("arissto_sync.workflows.apply_plan")
    def test_successful_client_run_scopes_and_reconciles_family_service(
        self, apply_client, reconcile_client, build_family, apply_family, reconcile_family
    ):
        state = FakeState([
            {"source_key": "A", "status": "succeeded"},
            {"source_key": "B", "status": "unchanged"},
        ])
        apply_client.return_value = ("client-run", {"create": 1, "unchanged": 1})
        reconcile_client.return_value = {"ok": True, "counts": {"matched": 2}}
        build_family.return_value = ("family-plan", {"scope": {"mode": "parent-client-source-keys", "entity_count": 3}})
        apply_family.return_value = ("family-run", {"create": 3})
        reconcile_family.return_value = {"ok": True, "counts": {"matched": 3}}

        result = apply_clients_with_family_references(object(), state, object(), object(), "client-plan")

        self.assertTrue(result["ok"])
        self.assertEqual(result["family_references"]["status"], "completed")
        self.assertEqual(build_family.call_args.kwargs["owner_keys"], {"A", "B"})
        reconcile_family.assert_called_once()


if __name__ == "__main__":
    unittest.main()
