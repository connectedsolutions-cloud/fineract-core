"""Guard the reviewed financial mappings carried across a sandbox reset."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock


HELPER = Path(__file__).resolve().parents[3] / "scripts/preserve-test-tenant-access.py"
spec = importlib.util.spec_from_file_location("preserve_test_tenant_access", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class MappingCursor:
    def __init__(self, account=(88, 2, 1, False), mapped_account=None):
        self.account = account
        self.mapped_account = mapped_account
        self.result = None
        self.insert_count = 0

    def execute(self, query, params=None):
        if "FROM acc_gl_account WHERE gl_code" in query:
            self.result = [self.account] if self.account is not None else []
        elif query.startswith("SELECT gl_account_id FROM acc_gl_financial_activity_account"):
            self.result = None if self.mapped_account is None else (self.mapped_account,)
        elif query.startswith("INSERT INTO acc_gl_financial_activity_account"):
            self.mapped_account = params[1]
            self.insert_count += 1
        else:
            raise AssertionError(f"Unexpected query: {query}")

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result


class FinancialActivityResetTests(unittest.TestCase):
    def test_capture_only_accepts_reviewed_active_detail_accounts(self):
        cur = MagicMock()
        cur.fetchall.return_value = [(201, "222099910101", 2, 1, False)]
        self.assertEqual(helper.capture_financial_activity_mappings(cur), [
            {"financial_activity_id": 201, "gl_code": "222099910101"},
        ])
        cur.fetchall.return_value = [(201, "222099910101", 2, 2, False)]
        with self.assertRaisesRegex(RuntimeError, "differs from the reviewed mapping"):
            helper.capture_financial_activity_mappings(cur)

    def test_restore_resolves_new_gl_id_and_is_idempotent(self):
        saved = [{"financial_activity_id": 201, "gl_code": "222099910101"}]
        cur = MappingCursor()
        helper.restore_financial_activity_mappings(cur, saved)
        self.assertEqual(cur.mapped_account, 88)
        self.assertEqual(cur.insert_count, 1)
        helper.restore_financial_activity_mappings(cur, saved)
        self.assertEqual(cur.insert_count, 1)

    def test_restore_rejects_conflicting_mapping_and_invalid_account(self):
        saved = [{"financial_activity_id": 201, "gl_code": "222099910101"}]
        with self.assertRaisesRegex(RuntimeError, "conflicts with the restored baseline"):
            helper.restore_financial_activity_mappings(
                MappingCursor(mapped_account=89), saved,
            )
        with self.assertRaisesRegex(RuntimeError, "target GL account is invalid"):
            helper.restore_financial_activity_mappings(
                MappingCursor(account=(88, 2, 2, False)), saved,
            )

    def test_unreviewed_activity_cannot_be_restored(self):
        cur = MappingCursor()
        with self.assertRaisesRegex(RuntimeError, "differs from the reviewed mapping"):
            helper.restore_financial_activity_mappings(
                cur, [{"financial_activity_id": 300, "gl_code": "3000"}],
            )
        self.assertEqual(cur.insert_count, 0)


if __name__ == "__main__":
    unittest.main()
