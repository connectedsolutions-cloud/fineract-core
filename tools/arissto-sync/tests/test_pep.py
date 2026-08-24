import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from arissto_sync.pep import PepContract, PepDataIssue
from arissto_sync.workflows import apply_clients_with_pep


class PepContractTests(unittest.TestCase):
    def contract(self) -> PepContract:
        return PepContract.load(Path(__file__).parents[1] / "config" / "client_pep.json")

    def test_strict_tri_state_normalization(self):
        contract = self.contract()
        self.assertIsNone(contract.normalize(None))
        self.assertIsNone(contract.normalize("  "))
        self.assertIs(contract.normalize("0"), False)
        self.assertIs(contract.normalize("1"), True)
        with self.assertRaisesRegex(PepDataIssue, "invalid_boolean"):
            contract.normalize("S")

    def test_unknown_false_and_true_hash_differ(self):
        contract = self.contract()
        hashes = {
            contract.hash_row({"source_key": "100", "pep_value": value})
            for value in (None, "0", "1")
        }
        self.assertEqual(len(hashes), 3)

    def test_contract_requires_clients_dependency_and_no_delete_policy(self):
        raw = self.contract().raw
        raw["depends_on"] = "something-else"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pep.json"
            path.write_text(__import__("json").dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "depend on clients"):
                PepContract.load(path)


class PepWorkflowTests(unittest.TestCase):
    @patch("arissto_sync.workflows.reconcile_pep")
    @patch("arissto_sync.workflows.apply_pep_plan")
    @patch("arissto_sync.workflows.build_pep_plan")
    @patch("arissto_sync.workflows.reconcile")
    @patch("arissto_sync.workflows.apply_plan")
    def test_pep_runs_only_after_successful_client_reconciliation(
        self, apply_clients, reconcile_clients, build_pep, apply_pep, reconcile_pep
    ):
        events = []
        apply_clients.side_effect = lambda *args: (events.append("client-apply") or ("client-run", {"update": 1}))
        reconcile_clients.side_effect = lambda *args: (events.append("client-reconcile") or {"ok": True})
        build_pep.side_effect = lambda *args, **kwargs: (
            events.append("pep-plan") or ("pep-plan", {
                "applicable": True, "scope": {"entity_count": 1}, "counts": {"create": 1}
            })
        )
        apply_pep.side_effect = lambda *args: (events.append("pep-apply") or ("pep-run", {"create": 1}))
        reconcile_pep.side_effect = lambda *args: (events.append("pep-reconcile") or {"ok": True})
        state = Mock()
        state.plan.return_value = {"block": "clients"}
        state.run_items.return_value = [{"source_key": "100", "status": "succeeded"}]

        result = apply_clients_with_pep(Mock(), state, Mock(), Mock(), "client-plan")

        self.assertTrue(result["ok"])
        self.assertEqual(events, ["client-apply", "client-reconcile", "pep-plan", "pep-apply", "pep-reconcile"])
        self.assertEqual(build_pep.call_args.kwargs["owner_keys"], {"100"})

    @patch("arissto_sync.workflows.build_pep_plan")
    @patch("arissto_sync.workflows.reconcile", return_value={"ok": False})
    @patch("arissto_sync.workflows.apply_plan", return_value=("client-run", {"failed": 1}))
    def test_pep_does_not_start_when_client_reconciliation_fails(
        self, apply_clients, reconcile_clients, build_pep
    ):
        state = Mock()
        state.plan.return_value = {"block": "clients"}

        result = apply_clients_with_pep(Mock(), state, Mock(), Mock(), "client-plan")

        self.assertFalse(result["ok"])
        self.assertEqual(result["stopped_after"], "client-reconciliation")
        build_pep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
