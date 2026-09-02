import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.cli import parser
from arissto_sync.loan_schedule_proof import (
    LoanScheduleCanary,
    SourceInstallment,
    build_schedule_payload,
    compare_schedules,
    fetch_schedule_canary,
)


class LoanScheduleProofTests(unittest.TestCase):
    def canary(self, frequency_id=30):
        return LoanScheduleCanary(
            source_key=123,
            line_id="00010",
            principal=Decimal("100.00"),
            annual_interest_rate=Decimal("24.00"),
            origin_date=date(2024, 1, 31),
            first_due_date=date(2024, 2, 29),
            frequency_id=frequency_id,
            installments=(
                SourceInstallment(1, date(2024, 2, 29), Decimal("49.00"), Decimal("2.00"), Decimal("0"), Decimal("0")),
                SourceInstallment(2, date(2024, 3, 31), Decimal("51.00"), Decimal("1.00"), Decimal("0"), Decimal("0")),
            ),
        )

    def test_fetch_rejects_restructured_or_count_drifted_canary(self):
        settings = SimpleNamespace(source=object())
        source_context = MagicMock()
        source_context.__enter__.return_value = object()
        loan = [{
            "ID_CREDITO": 123, "ID_LINEA_CREDITO": "00010", "PRINCIPAL": "100.00",
            "PORC_INTERES_APROBADO": "24.00", "FECHA_OTORGAMIENTO": datetime(2024, 1, 31),
            "FECHA_PRIMER_PAGO": datetime(2024, 2, 29), "ID_FRECUENCIA": 30,
            "NO_CUOTAS_APROBADO": 1,
        }]
        periods = [{
            "NO_CUOTA": 1, "FECHA_PAGO": datetime(2024, 2, 29), "MONTO_CAPITAL": "100.00",
            "MONTO_INTERES": "2.00", "MONTO_OTROS": 0, "MONTO_APORTACION": 0,
            "ID_REESTRUCTURACION": 9, "CUOTA_DIFERIDA": None,
        }]
        with (
            patch("arissto_sync.loan_schedule_proof.source_connection", return_value=source_context),
            patch("arissto_sync.loan_schedule_proof.select_rows", side_effect=[loan, periods]),
            self.assertRaisesRegex(ValueError, "restructuring"),
        ):
            fetch_schedule_canary(settings, 123)

    def test_monthly_payload_preserves_first_due_anchor_and_annual_rate(self):
        payload = build_schedule_payload(
            self.canary(), 3, 7, "credesal-strategy", interest_rate_frequency_type=2
        )
        self.assertEqual(payload["repaymentFrequencyType"], 2)
        self.assertEqual(payload["repaymentEvery"], 1)
        self.assertEqual(payload["loanTermFrequency"], 2)
        self.assertEqual(payload["repaymentsStartingFromDate"], "2024-02-29")
        self.assertEqual(payload["interestRatePerPeriod"], "2.00")
        self.assertEqual(payload["interestRateFrequencyType"], 2)

    def test_fortnightly_payload_uses_fifteen_fixed_days(self):
        payload = build_schedule_payload(self.canary(15), 3, 7, "credesal-strategy")
        self.assertEqual(payload["repaymentFrequencyType"], 0)
        self.assertEqual(payload["repaymentEvery"], 15)
        self.assertEqual(payload["loanTermFrequency"], 30)

    def test_exact_schedule_comparison_accepts_fineract_date_arrays(self):
        schedule = {"periods": [
            {"period": 0, "dueDate": [2024, 1, 31]},
            {"period": 1, "dueDate": [2024, 2, 29], "principalDue": 49, "interestDue": 2},
            {"period": 2, "dueDate": [2024, 3, 31], "principalDue": 51, "interestDue": 1},
        ]}
        result = compare_schedules(self.canary(), schedule)
        self.assertTrue(result["exact"])
        self.assertTrue(result["core_exact"])
        self.assertTrue(result["accepted"])
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["totals"]["principal_delta"], "0.00")
        self.assertEqual(result["totals"]["interest_delta"], "0.00")

    def test_comparison_reports_installment_level_amount_and_date_differences(self):
        schedule = {"periods": [
            {"period": 1, "dueDate": [2024, 2, 28], "principalDue": 48, "interestDue": 2},
            {"period": 2, "dueDate": [2024, 3, 31], "principalDue": 51, "interestDue": 1},
        ]}
        result = compare_schedules(self.canary(), schedule)
        self.assertFalse(result["exact"])
        self.assertFalse(result["core_exact"])
        self.assertFalse(result["accepted"])
        self.assertEqual({item["kind"] for item in result["mismatches"]}, {"due_date", "principal"})

    def test_comparison_rejects_native_redistribution_even_when_totals_match(self):
        schedule = {"periods": [
            {"period": 1, "dueDate": [2024, 2, 29], "principalDue": 48.99, "interestDue": 2.01},
            {"period": 2, "dueDate": [2024, 3, 31], "principalDue": 51.01, "interestDue": 0.99},
        ]}
        result = compare_schedules(self.canary(), schedule)
        self.assertFalse(result["core_exact"])
        self.assertFalse(result["accepted"])
        self.assertTrue(result["acceptance"]["dates_match"])
        self.assertTrue(result["acceptance"]["principal_total_matches"])
        self.assertTrue(result["acceptance"]["interest_total_matches"])

    def test_comparison_rejects_component_total_drift(self):
        schedule = {"periods": [
            {"period": 1, "dueDate": [2024, 2, 29], "principalDue": 49, "interestDue": 2},
            {"period": 2, "dueDate": [2024, 3, 31], "principalDue": 50.98, "interestDue": 1},
        ]}
        result = compare_schedules(self.canary(), schedule)
        self.assertFalse(result["accepted"])
        self.assertFalse(result["acceptance"]["principal_total_matches"])

    def test_cli_limits_schedule_proof_to_local_target(self):
        args = parser().parse_args([
            "prove-loan-schedule", "--target", "local", "--source-key", "123",
            "--product-id", "3", "--client-id", "7",
        ])
        self.assertEqual(args.source_key, 123)
        self.assertEqual(args.product_id, 3)
        self.assertEqual(args.client_id, 7)


if __name__ == "__main__":
    unittest.main()
