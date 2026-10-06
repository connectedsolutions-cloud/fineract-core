import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from arissto_sync.treasury_prerequisite import ensure_treasury_bank_accounts
from arissto_sync.workflow_definitions import load_workflow


PREREQUISITES = {
    "treasury_bank_accounts": {
        "required_by_services": ["loans"], "source_account_ids": [1, 3, 4],
    }
}
SOURCE = [
    {"source_id": 1, "branch": "001", "status": "1", "account_number": "123456789",
     "bank_name": "BANCO ATLANTIDA", "gl_code": "111004020101"},
    {"source_id": 3, "branch": "001", "status": "1", "account_number": "007-123-456",
     "bank_name": "BANCO CUSCATLAN", "gl_code": "111004020102"},
    {"source_id": 4, "branch": "001", "status": "1", "account_number": "987654321",
     "bank_name": "AMC DE R.L. DE C.V.", "gl_code": "111004010101"},
]
GL = [
    {"id": n, "glCode": row["gl_code"], "disabled": False,
     "type": {"id": 1}, "usage": {"id": 1}}
    for n, row in enumerate(SOURCE, start=10)
]


class FakeApi:
    def __init__(self):
        self.banks = []
        self.posts = []

    def request(self, method, path, payload=None):
        if method == "GET" and path == "glaccounts":
            return GL
        if method == "GET" and path == "treasury/bankaccounts":
            return list(self.banks)
        if method == "POST" and path == "treasury/bankaccounts":
            self.posts.append(payload)
            gl = next(row for row in GL if row["id"] == payload["glAccountId"])
            bank = {**payload, "id": len(self.banks) + 1, "glCode": gl["glCode"], "active": True}
            self.banks.append(bank)
            return bank
        raise AssertionError((method, path))


class TreasuryPrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(
            source=object(), target=SimpleNamespace(
                name="local", tenant="sandbox", api_url="https://localhost:8443/fineract-provider/api/v1",
                pg_url="postgresql://localhost:5432/fineract_sandbox",
            )
        )
        self.api = FakeApi()
        self.connection = patch("arissto_sync.treasury_prerequisite.source_connection",
                                return_value=nullcontext(object()))
        self.rows = patch("arissto_sync.treasury_prerequisite.select_rows", return_value=SOURCE)
        self.connection.start()
        self.rows.start()
        self.addCleanup(self.connection.stop)
        self.addCleanup(self.rows.stop)

    def test_empty_target_creates_three_and_rerun_is_unchanged(self):
        report = ensure_treasury_bank_accounts(self.settings, self.api, PREREQUISITES, ["loans"])
        self.assertEqual([item["action"] for item in report["actions"]], ["created"] * 3)
        self.assertEqual(len(self.api.posts), 3)
        self.assertNotIn("account_number", str(report))
        second = ensure_treasury_bank_accounts(self.settings, self.api, PREREQUISITES, ["loans"])
        self.assertEqual([item["action"] for item in second["actions"]], ["unchanged"] * 3)
        self.assertEqual(len(self.api.posts), 3)

    def test_conflict_blocks_all_writes(self):
        self.api.banks.append({"id": 1, "name": "WRONG", "glAccountId": 11,
                               "glCode": "111004020101", "active": True})
        with self.assertRaisesRegex(RuntimeError, "differs from the reviewed target mapping"):
            ensure_treasury_bank_accounts(self.settings, self.api, PREREQUISITES, ["loans"])
        self.assertEqual(self.api.posts, [])

    def test_placeholder_source_blocks_all_writes(self):
        bad = [dict(row) for row in SOURCE]
        bad[1]["account_number"] = "XXXXX"
        with patch("arissto_sync.treasury_prerequisite.select_rows", return_value=bad):
            with self.assertRaisesRegex(RuntimeError, "differs from the reviewed master"):
                ensure_treasury_bank_accounts(self.settings, self.api, PREREQUISITES, ["loans"])
        self.assertEqual(self.api.posts, [])

    def test_nonfinancial_selection_skips_source_and_target(self):
        with patch("arissto_sync.treasury_prerequisite.select_rows") as read:
            result = ensure_treasury_bank_accounts(self.settings, self.api, PREREQUISITES, ["clients"])
        self.assertEqual(result, {"performed": False, "actions": []})
        read.assert_not_called()

    def test_production_target_is_rejected(self):
        self.settings.target.name = "prod"
        with self.assertRaisesRegex(RuntimeError, "local sandbox"):
            ensure_treasury_bank_accounts(self.settings, self.api, PREREQUISITES, ["loans"])
        self.assertEqual(self.api.posts, [])

    def test_local_financial_workflows_declare_reviewed_set(self):
        for workflow in ("local-full-sync", "local-full-resync",
                         "local-credit-collections", "local-membership-financial"):
            with self.subTest(workflow=workflow):
                config = load_workflow(workflow).document["target_prerequisites"]["treasury_bank_accounts"]
                self.assertEqual(config["source_account_ids"], [1, 3, 4])
