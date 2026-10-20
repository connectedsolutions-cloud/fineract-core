import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from arissto_sync.client_current_office import BLOCK, apply_plan


class CurrentClientOfficeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(target=SimpleNamespace(
            fingerprint="sandbox-fingerprint", name="local", pg_url="postgresql://unused",
        ))
        self.state = Mock()
        self.state.plan.return_value = {
            "id": "reviewed-plan", "block": BLOCK, "status": "planned",
            "target_fingerprint": "sandbox-fingerprint", "document": {
                "source_fingerprint": "source", "contract_hash": "mapping",
                "source_hash": "snapshot", "database": "fineract_sandbox",
                "changes": [{"source_key": "borrower", "target_id": 9,
                             "observed_office_id": 1, "desired_office_id": 2}],
            },
        }
        self.state.conn.execute.return_value.fetchone.return_value = None

    @patch("arissto_sync.client_current_office.inspect")
    def test_source_change_blocks_apply_before_any_run_or_target_write(self, inspect):
        inspect.return_value = {
            **self.state.plan.return_value["document"], "source_hash": "new-snapshot"
        }
        with self.assertRaisesRegex(RuntimeError, "client_office_plan_stale"):
            apply_plan(self.settings, self.state, "reviewed-plan")
        self.state.start_run.assert_not_called()

    @patch("arissto_sync.client_current_office.inspect")
    def test_reusing_a_plan_blocks_apply(self, inspect):
        self.state.conn.execute.return_value.fetchone.return_value = (1,)
        with self.assertRaisesRegex(RuntimeError, "client_office_plan_already_applied"):
            apply_plan(self.settings, self.state, "reviewed-plan")
        inspect.assert_not_called()
        self.state.start_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
