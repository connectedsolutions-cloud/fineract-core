from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import unittest

from arissto_sync.share_yield import _expected_exact, _source_key, _summarize, _target_accrual_matches


class ShareYieldTest(unittest.TestCase):

    def test_contract_uses_reviewed_target_payable_account(self) -> None:
        config = json.loads(
            (Path(__file__).resolve().parents[1] / "config" / "native_share_yield.json").read_text()
        )
        self.assertEqual(config["target"]["payable_gl_code"], "222099910101")

    def test_source_key_is_stable(self) -> None:
        self.assertEqual(_source_key(123), "FNC_PROVISIONES|123")

    def test_actual_actual_source_precision(self) -> None:
        self.assertEqual(_expected_exact(Decimal("1125.00"), Decimal("7.00"), date(2025, 1, 1)), Decimal("0.21575342"))
        self.assertEqual(_expected_exact(Decimal("1125.00"), Decimal("7.00"), date(2024, 1, 1)), Decimal("0.21516393"))

    def test_summary_preserves_financial_totals_and_scope(self) -> None:
        records = [
            {
                "certificate_key": "AFI_CERTIFICADO|1|10|2", "accrual_date": "2024-11-12",
                "accrued_amount": "0.12345678", "booked_amount": "0.12",
            },
            {
                "certificate_key": "AFI_CERTIFICADO|2|10|2", "accrual_date": "2024-11-13",
                "accrued_amount": "0.87654322", "booked_amount": "0.88",
            },
        ]

        self.assertEqual(_summarize(records), {
            "rows": 2, "certificates": 2, "exact": "1.00000000", "booked": "1.00",
            "min_date": "2024-11-12", "max_date": "2024-11-13",
        })

    def test_existing_target_match_checks_all_source_exact_fields(self) -> None:
        record = {
            "accrual_date": "2024-11-12", "entry_type": "ACCRUAL", "base_amount": "1125.00",
            "annual_rate": "7.00", "day_count_basis": 366, "accrued_amount": "0.21516393",
            "booked_amount": "0.22",
        }
        existing = {
            "account_id": 91, "date": "2024-11-12", "entry_type": "ACCRUAL", "base": "1125.000000",
            "rate": "7.000000", "basis": 366, "exact": "0.21516393", "booked": "0.220000",
            "imported": True,
        }

        self.assertTrue(_target_accrual_matches(existing, 91, record))
        for field, drifted in {
            "account_id": 92, "date": "2024-11-13", "entry_type": "OPENING", "base": "1126.000000",
            "rate": "6.000000", "basis": 365, "exact": "0.21516394", "booked": "0.230000",
            "imported": False,
        }.items():
            changed = {**existing, field: drifted}
            self.assertFalse(_target_accrual_matches(changed, 91, record), field)
