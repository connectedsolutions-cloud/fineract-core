import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.accounting_g9_acceptance import (
    SOURCE_DAILY_QUERY,
    SOURCE_JANUARY_CONTINUITY_QUERY,
    SOURCE_MAYOR_QUERY,
    SOURCE_TRACE_QUERY,
    TARGET_READINESS_QUERY,
    TARGET_JANUARY_OPENING_QUERY,
    TARGET_TRACE_QUERY,
    _daily_mayor_variances,
    _content_sha256,
    _source_target_activity_variances,
    _source_january_continuity_variances,
    _target_january_opening_variances,
    _write_artifact,
    compare_statement_artifact,
    inspect_g9_readiness,
)
from arissto_sync.arissto import READ_ONLY_SQL


def artifact(amount="10.00"):
    return {
        "cases": [{
            "report_type": "trial-balance",
            "closing_mode": "post-closing",
            "scope": "consolidated",
            "rows": [{
                "gl_code": "100",
                "account_name": "Cash",
                "opening_balance": "1.00",
                "debits": amount,
                "credits": "2.00",
                "closing_balance": "9.00",
            }],
            "controls": {"assets": "9.00", "dimension_scope": "consolidated"},
        }]
    }


class AccountingG9AcceptanceTests(unittest.TestCase):

    def test_readiness_returns_frozen_count_result(self):
        counts = {
            "imported_journals": 5563,
            "provenance_lines": 26820,
            "december_journals": 380,
            "december_lines": 2065,
            "december_closing_journals": 3,
            "imported_2024_lines": 16728,
            "nonzero_opening_flags": 0,
            "invalid_annual_shapes": 0,
            "dimension_mismatches": 0,
            "missing_target_lines": 0,
            "unprovenanced_pre_cutoff_lines": 0,
        }
        cursor = MagicMock()
        cursor.description = [SimpleNamespace(name=name) for name in counts]
        cursor.fetchone.return_value = tuple(counts.values())
        connection = MagicMock()
        connection.execute.return_value = cursor
        manager = MagicMock()
        manager.__enter__.return_value = connection
        settings = SimpleNamespace(target=SimpleNamespace(name="local", pg_url="postgresql://local", tenant="sandbox"))
        with patch("arissto_sync.accounting_g9_acceptance.postgres_connection", return_value=manager):
            result = inspect_g9_readiness(settings)
        self.assertTrue(result["ready"])
        self.assertEqual(result["counts"], counts)

    def test_all_database_queries_are_read_only(self):
        for query in (
            SOURCE_TRACE_QUERY,
            SOURCE_MAYOR_QUERY,
            SOURCE_DAILY_QUERY,
            SOURCE_JANUARY_CONTINUITY_QUERY,
            TARGET_READINESS_QUERY,
            TARGET_JANUARY_OPENING_QUERY,
            TARGET_TRACE_QUERY,
        ):
            self.assertRegex(query, READ_ONLY_SQL)

    def test_identical_statement_artifacts_pass(self):
        result = compare_statement_artifact(artifact(), artifact())
        self.assertTrue(result["accepted"])
        self.assertEqual(result["finding_count"], 0)

    def test_cent_difference_fails_with_exact_field(self):
        result = compare_statement_artifact(artifact("10.00"), artifact("10.02"))
        self.assertFalse(result["accepted"])
        self.assertEqual(result["finding_count"], 1)
        self.assertEqual(result["findings"][0]["fields"], ["debits"])

    def test_accumulated_income_difference_fails_at_currency_precision(self):
        expected = artifact()
        actual = artifact()
        expected["cases"][0]["rows"][0]["accumulated_balance"] = "100.00"
        actual["cases"][0]["rows"][0]["accumulated_balance"] = "100.01"
        result = compare_statement_artifact(expected, actual)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["findings"][0]["fields"], ["accumulated_balance"])

    def test_missing_case_and_row_fail_closed(self):
        missing_case = compare_statement_artifact(artifact(), {"cases": []})
        self.assertEqual(missing_case["findings"][0]["reason"], "CASE_MISSING")
        missing_row = artifact()
        missing_row["cases"][0]["rows"] = []
        result = compare_statement_artifact(artifact(), missing_row)
        self.assertIn("ROW_MISSING", {item["reason"] for item in result["findings"]})

    def test_control_difference_fails_at_currency_precision(self):
        actual = artifact()
        actual["cases"][0]["controls"]["assets"] = "9.01"
        result = compare_statement_artifact(artifact(), actual)
        self.assertIn("assets", result["findings"][0]["fields"])

    def test_written_artifact_has_stable_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            first = _write_artifact(Path(directory), "proof.json", artifact())
            second = _write_artifact(Path(directory), "proof.json", artifact())
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual(len(first["sha256"]), 64)

    def test_content_hash_is_key_order_independent(self):
        self.assertEqual(_content_sha256({"a": 1, "b": 2}), _content_sha256({"b": 2, "a": 1}))

    def test_daily_trace_identifies_first_cent_variance(self):
        activity = [{
            "control_gl_code": "2220050501", "branch_id": "001",
            "activity_date": __import__("datetime").date(2024, 1, 1),
            "signed_amount": 1,
        }]
        daily = [{
            "gl_code": "2220050501", "branch_id": "001", "daily_close_id": "1",
            "activity_date": __import__("datetime").date(2024, 1, 1),
            "closing_balance": "1.02",
        }]
        findings = _daily_mayor_variances(activity, daily)
        self.assertEqual(findings[0]["first"]["variance"], "0.02")

    def test_source_target_activity_comparison_is_exact(self):
        source = [{
            "posting_gl_code": "222005050102", "branch_id": "001",
            "debit": "0.00", "credit": "0.02",
        }]
        target = [{
            "gl_code": "222005050102", "office_external_id": "1",
            "debit": "0.00", "credit": "0.02",
        }]
        self.assertEqual(_source_target_activity_variances(source, target), [])
        target[0]["credit"] = "0.00"
        self.assertEqual(len(_source_target_activity_variances(source, target)), 1)

    def test_january_continuity_helpers_compare_source_and_target_exactly(self):
        source = [{
            "gl_code": "222005050102", "branch_id": "001", "balance_nature": "A",
            "december_closing_balance": "0.02", "january_opening_balance": "0.02",
        }]
        target = [{
            "gl_code": "222005050102", "office_external_id": "1",
            "debit": "0.00", "credit": "0.02",
        }]
        self.assertEqual(_source_january_continuity_variances(source), [])
        self.assertEqual(_target_january_opening_variances(source, target), [])
        source[0]["january_opening_balance"] = "0.00"
        self.assertEqual(len(_source_january_continuity_variances(source)), 1)
        self.assertEqual(len(_target_january_opening_variances(source, target)), 1)

    def test_target_january_opening_applies_account_overrides_and_rollups(self):
        source = [
            {
                "gl_code": "314002", "branch_id": "001", "balance_nature": "A",
                "december_closing_balance": "-12.00", "january_opening_balance": "-12.00",
            },
            {
                "gl_code": "3140020100", "branch_id": "001", "balance_nature": "A",
                "december_closing_balance": "5.00", "january_opening_balance": "5.00",
            },
            {
                "gl_code": "3140020200", "branch_id": "001", "balance_nature": "A",
                "december_closing_balance": "-17.00", "january_opening_balance": "-17.00",
            },
            {
                "gl_code": "SOURCE-CASH", "branch_id": "002", "balance_nature": "D",
                "december_closing_balance": "9.00", "january_opening_balance": "9.00",
            },
        ]
        target = [
            {"gl_code": "314002", "office_external_id": "1", "debit": "1.00", "credit": "1.00"},
            {"gl_code": "3140020100", "office_external_id": "1", "debit": "0.00", "credit": "5.00"},
            {"gl_code": "3140020200", "office_external_id": "1", "debit": "17.00", "credit": "0.00"},
            {"gl_code": "TARGET-CASH", "office_external_id": "2", "debit": "9.00", "credit": "0.00"},
        ]
        self.assertEqual(
            _target_january_opening_variances(source, target, {"SOURCE-CASH": "TARGET-CASH"}),
            [],
        )

    def test_target_january_opening_aggregates_many_to_one_aliases(self):
        source = [
            {
                "gl_code": "SOURCE-CASH-1", "branch_id": "002", "balance_nature": "D",
                "december_closing_balance": "0.00", "january_opening_balance": "0.00",
            },
            {
                "gl_code": "SOURCE-CASH-2", "branch_id": "002", "balance_nature": "D",
                "december_closing_balance": "9.00", "january_opening_balance": "9.00",
            },
        ]
        target = [{
            "gl_code": "TARGET-CASH", "office_external_id": "2", "debit": "9.00", "credit": "0.00",
        }]
        overrides = {"SOURCE-CASH-1": "TARGET-CASH", "SOURCE-CASH-2": "TARGET-CASH"}
        self.assertEqual(_target_january_opening_variances(source, target, overrides), [])


if __name__ == "__main__":
    unittest.main()
