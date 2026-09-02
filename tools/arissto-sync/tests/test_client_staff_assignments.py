import json
import tempfile
import unittest
from pathlib import Path

from arissto_sync.client_staff_assignments import (
    ClientStaffAssignmentContract,
    ClientStaffAssignmentDataIssue,
)


class ClientStaffAssignmentContractTests(unittest.TestCase):
    def contract(self):
        return ClientStaffAssignmentContract.load(
            Path(__file__).parents[1] / "config" / "client_staff_assignments.json"
        )

    def row(self, **changes):
        row = {
            "source_key": "100", "company_id": "001", "promoter": "10",
            "account_executive": "11", "collections_manager": None,
        }
        row.update(changes)
        return row

    def test_all_three_roles_resolve_with_company_scoped_staff_identity(self):
        normalized = self.contract().normalized(self.row())
        self.assertEqual(normalized["promoter_external_id"], "001:10")
        self.assertEqual(normalized["account_executive_external_id"], "001:11")
        self.assertIsNone(normalized["collections_manager_external_id"])

    def test_roles_remain_independent_when_all_are_populated(self):
        normalized = self.contract().normalized(self.row(collections_manager="12"))
        self.assertEqual(normalized["promoter_external_id"], "001:10")
        self.assertEqual(normalized["account_executive_external_id"], "001:11")
        self.assertEqual(normalized["collections_manager_external_id"], "001:12")
        self.assertNotIn("effective_loan_officer_external_id", normalized)

    def test_payload_preserves_legacy_ids_and_resolved_staff_fks(self):
        payload = self.contract().payload(self.row(), {"001:10": 70, "001:11": 71})
        self.assertEqual(payload["arissto_company_id"], "001")
        self.assertEqual(payload["arissto_promoter_person_id"], "10")
        self.assertEqual(payload["promoter_staff_id"], 70)
        self.assertEqual(payload["arissto_account_executive_person_id"], "11")
        self.assertEqual(payload["account_executive_staff_id"], 71)
        self.assertIsNone(payload["collections_manager_staff_id"])

    def test_all_null_assignment_still_has_complete_payload(self):
        payload = self.contract().payload(
            self.row(promoter=None, account_executive=" ", collections_manager=None), {}
        )
        self.assertEqual(len(payload), 7)
        self.assertTrue(all(value is None for key, value in payload.items() if key != "arissto_company_id"))

    def test_hash_changes_for_each_role(self):
        contract = self.contract()
        base = contract.hash_row(self.row())
        for role in ("promoter", "account_executive", "collections_manager"):
            self.assertNotEqual(base, contract.hash_row(self.row(**{role: "99"})))

    def test_query_uses_exact_affiliation_parameter(self):
        sql, params = self.contract().query("100")
        self.assertIn("WHERE [NUMERO_AFILIACION] = ?", sql)
        self.assertEqual(params, ("100",))

    def test_invalid_client_and_company_keys_are_rejected(self):
        with self.assertRaises(ClientStaffAssignmentDataIssue):
            self.contract().source_key(self.row(source_key=""))
        with self.assertRaises(ClientStaffAssignmentDataIssue):
            self.contract().company(self.row(company_id=None))

    def test_contract_rejects_missing_role(self):
        source = Path(__file__).parents[1] / "config" / "client_staff_assignments.json"
        value = json.loads(source.read_text())
        value["source"]["roles"].pop("promoter")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "all three"):
                ClientStaffAssignmentContract.load(path)


if __name__ == "__main__":
    unittest.main()
