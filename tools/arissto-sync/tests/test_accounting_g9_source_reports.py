import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from arissto_sync.accounting_g9_source_reports import normalize_authoritative_report_directory


REQUIRED_FILES = (
    "balance-comprobacion-dec-2024-santiago.xlsx",
    "balance-comprobacion-dec-2024-usulutan.xlsx",
    "balance-comprobacion-pre-liquidacion-dec-2024-santiago.xlsx",
    "balance-comprobacion-pre-liquidacion-dec-2024-usulutan.xlsx",
    "balance-gral-dec-2024-santiago.xlsx",
    "balance-gral-dec-2024-usulutan.xlsx",
    "estado de resultados-pre-liq-ene-dec-2024-santiago.xlsx",
    "estado de resultados-pre-liq-ene-dec-2024-usulutan.xlsx",
)


def write_export(path: Path, scope: str | None = None) -> None:
    workbook = Workbook()
    sheet = workbook.active
    scope = scope or ("USULUTAN" if "usulutan" in path.name else "AGENCIA CENTRAL")
    sheet["A3"] = f"Balance de Comprobación - {scope}"
    sheet["A4"] = "Al 31 de DICIEMBRE de 2024"
    sheet["A5"] = f"SUCURSAL: {scope}"
    sheet["A7"] = "09/09/2026 05:34"
    workbook.save(path)


class AccountingG9SourceReportTests(unittest.TestCase):

    def test_required_office_exports_create_twelve_cases_with_derived_consolidated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in REQUIRED_FILES:
                write_export(root / name)
            result = normalize_authoritative_report_directory(root)
        self.assertTrue(result["ready"])
        self.assertEqual(result["required_office_case_count"], 8)
        self.assertEqual(result["normalized_case_count"], 12)
        self.assertEqual(sum(case["scope"] == "consolidated" for case in result["cases"]), 4)

    def test_required_filename_header_scope_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in REQUIRED_FILES:
                write_export(root / name)
            write_export(root / "balance-gral-dec-2024-usulutan.xlsx", scope="AGENCIA CENTRAL")
            result = normalize_authoritative_report_directory(root)
        self.assertFalse(result["ready"])
        self.assertIn("FILENAME_HEADER_SCOPE_MISMATCH", result["blockers"][0]["reasons"])

    def test_mislabeled_post_closing_income_export_is_a_warning_not_a_statement_parity_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in REQUIRED_FILES:
                write_export(root / name)
            write_export(root / "estado de resultados-ene-dec-2024-usulutan.xlsx", scope="AGENCIA CENTRAL")
            result = normalize_authoritative_report_directory(root)
        self.assertTrue(result["ready"])
        self.assertEqual(result["warnings"][0]["reasons"], ["FILENAME_HEADER_SCOPE_MISMATCH"])


if __name__ == "__main__":
    unittest.main()
