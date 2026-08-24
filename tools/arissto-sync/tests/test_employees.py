import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.employees import (
    EmployeeContract,
    EmployeeDataIssue,
    _source_requirements,
    _target_row_matches,
    inspect_employees,
)


CONFIG = Path(__file__).resolve().parents[1] / "config" / "employees.json"


class EmployeeContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = EmployeeContract.load(CONFIG)

    def row(self, **changes):
        value = {
            "company_key": "001",
            "person_key": "00001",
            "firstname": "  ANA   MARIA ",
            "lastname": "  LOPEZ ",
            "employee_status": "01",
            "employee_joining_date": datetime(2020, 2, 3),
            "profile_branch_key": "001",
            "branch_key": "001",
            "assignment_status": "1",
            "assignment_start_date": datetime(2020, 10, 1),
            "mobile_no": " 2222-3333 ",
            "email_address": " employee@example.test ",
            "profile__salary": 725.50,
            "profile__dui": "01234567-8",
            "profile__legacy_username": "legacy.user",
        }
        value.update(changes)
        return value

    def test_identity_and_payload_are_stable(self):
        row = self.row()
        self.assertEqual(self.contract.source_key(row), "001:00001")
        payload = self.contract.payload(row)
        self.assertEqual(payload["externalId"], "001:00001")
        self.assertEqual(payload["firstname"], "ANA MARIA")
        self.assertEqual(payload["lastname"], "LOPEZ")
        self.assertEqual(payload["officeIds"], [1])
        self.assertEqual(payload["joiningDate"], "2020-02-03")
        self.assertTrue(payload["isActive"])
        self.assertNotIn("isLoanOfficer", payload)
        self.assertEqual(payload["mobileNo"], "2222-3333")
        self.assertEqual(payload["emailAddress"], "employee@example.test")
        profile = self.contract.profile_payload(row)
        self.assertEqual(profile["salary"], 725.5)
        self.assertEqual(profile["dui"], "01234567-8")
        self.assertEqual(profile["legacy_username"], "legacy.user")

    def test_assignment_start_date_is_reviewed_fallback(self):
        payload = self.contract.payload(self.row(employee_joining_date=None))
        self.assertEqual(payload["joiningDate"], "2020-10-01")

    def test_inactive_employee_requires_inactive_assignment(self):
        payload = self.contract.payload(self.row(employee_status="02", assignment_status="0"))
        self.assertFalse(payload["isActive"])
        with self.assertRaisesRegex(EmployeeDataIssue, "employee_office_status_mismatch"):
            self.contract.payload(self.row(employee_status="02", assignment_status="1"))

    def test_legacy_snapshot_date_is_final_fallback(self):
        payload = self.contract.payload(self.row(employee_joining_date=None, assignment_start_date=None))
        self.assertEqual(payload["joiningDate"], "2020-10-01")

    def test_profile_branch_is_fallback_when_assignment_is_absent(self):
        payload = self.contract.payload(self.row(branch_key=None, assignment_status=None, profile_branch_key="002"))
        self.assertEqual(payload["officeIds"], [2])

    def test_invalid_office_data_is_quarantinable(self):
        with self.assertRaisesRegex(EmployeeDataIssue, "missing_employee_office_assignment"):
            self.contract.payload(self.row(branch_key=None, assignment_status=None, profile_branch_key=None))
        with self.assertRaisesRegex(EmployeeDataIssue, "missing_employee_office_assignment_status"):
            self.contract.payload(self.row(branch_key="001", assignment_status=None))
        with self.assertRaisesRegex(EmployeeDataIssue, "unmapped_employee_office"):
            self.contract.payload(self.row(branch_key=None, assignment_status=None, profile_branch_key="999"))

    def test_target_match_ignores_loan_officer_but_requires_exact_office_set(self):
        payload = self.contract.payload(self.row())
        target = {
            "office_id": 1,
            "office_ids": [1],
            "firstname": "ANA MARIA",
            "lastname": "LOPEZ",
            "external_id": "001:00001",
            "is_active": True,
            "joining_date": datetime(2020, 2, 3),
            "is_loan_officer": True,
        }
        target["mobile_no"] = "2222-3333"
        target["email_address"] = "employee@example.test"
        target["profile"] = self.contract.profile_payload(self.row())
        self.assertTrue(_target_row_matches(target, payload, self.contract.profile_payload(self.row())))
        target["office_ids"] = [1, 2]
        self.assertFalse(_target_row_matches(target, payload, self.contract.profile_payload(self.row())))

    def test_profile_mismatch_requires_update(self):
        row = self.row()
        payload = self.contract.payload(row)
        target = {
            "office_id": 1, "office_ids": [1], "firstname": "ANA MARIA", "lastname": "LOPEZ",
            "external_id": "001:00001", "mobile_no": "2222-3333", "email_address": "employee@example.test",
            "is_active": True, "joining_date": datetime(2020, 2, 3),
            "profile": self.contract.profile_payload(row),
        }
        target["profile"] = {**target["profile"], "salary": 700.0}
        self.assertFalse(_target_row_matches(target, payload, self.contract.profile_payload(row)))

    def test_contract_rejects_password_and_permission_profile_sources(self):
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        for source in ("USUARIO.PASSWORD", "USUARIO.AUT_CRD_SALDOS"):
            raw["profile"]["unsafe"] = {"source": source, "type": "text"}
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "employees.json"
                path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Credentials and permission"):
                    EmployeeContract.load(path)

    def test_contract_rejects_invalid_status_coverage(self):
        raw = CONFIG.read_text(encoding="utf-8").replace('"02": "0"', '"03": "0"')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "employees.json"
            path.write_text(raw, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "same source statuses"):
                EmployeeContract.load(path)

    def test_contract_requires_valid_joining_date_fallback(self):
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["core"]["joiningDate"]["fallback"] = "not-a-date"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "employees.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "joining-date fallback"):
                EmployeeContract.load(path)

    def test_inspection_keeps_source_summary_when_target_postgres_is_unavailable(self):
        metadata = []
        for required in _source_requirements(self.contract).values():
            metadata.append([{"column_name": column, "data_type": "varchar"} for column in required])
        source_context = MagicMock()
        source_context.__enter__.return_value = object()
        settings = SimpleNamespace(
            source=object(),
            target=SimpleNamespace(pg_url="postgresql://unavailable", fingerprint="local", api_user="operator"),
        )
        with (
            patch("arissto_sync.employees.source_connection", return_value=source_context),
            patch("arissto_sync.employees.select_rows", side_effect=metadata),
            patch("arissto_sync.employees.extract_employees", return_value=[self.row()]),
            patch("arissto_sync.employees.postgres_connection", side_effect=RuntimeError("sensitive detail")),
        ):
            report = inspect_employees(settings, self.contract)
        self.assertFalse(report["ready"])
        self.assertEqual(report["source"]["migratable_rows"], 1)
        self.assertEqual(report["target"], {"postgres_inspection": "failed", "error_type": "RuntimeError"})
        self.assertNotIn("sensitive detail", str(report))


if __name__ == "__main__":
    unittest.main()
