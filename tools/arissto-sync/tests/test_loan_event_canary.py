import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from arissto_sync.loan_event_canary import _installments, _non_disbursement_count, build_plan


class LoanEventCanaryTests(unittest.TestCase):
    def test_installments_freeze_ordered_source_version(self):
        rows = [
            {"NO_CUOTA": 1, "FECHA_PAGO": datetime(2026, 10, 20),
             "MONTO_CAPITAL": Decimal("4.30"), "MONTO_INTERES": Decimal("12.50")},
            {"NO_CUOTA": 2, "FECHA_PAGO": datetime(2026, 11, 20),
             "MONTO_CAPITAL": Decimal("5.00"), "MONTO_INTERES": Decimal("11.80")},
        ]
        result = _installments(rows, "2026-09-20")
        self.assertEqual(result[0]["fromDate"], "2026-09-20")
        self.assertEqual(result[1]["fromDate"], "2026-10-20")
        self.assertEqual(result[0]["principal"], "4.30")

    def test_rejects_backward_due_date_and_negative_interest(self):
        rows = [
            {"NO_CUOTA": 1, "FECHA_PAGO": "2026-11-27", "MONTO_CAPITAL": 1, "MONTO_INTERES": 1},
            {"NO_CUOTA": 2, "FECHA_PAGO": "2026-11-26", "MONTO_CAPITAL": 1, "MONTO_INTERES": -0.12},
        ]
        with self.assertRaisesRegex(ValueError, "Unrepresentable source installment 2"):
            _installments(rows, "2026-10-01")

    def test_transaction_guard_ignores_disbursement_and_reversed_rows(self):
        loan = {"transactions": [
            {"type": {"id": 1}}, {"type": {"id": 2}},
            {"type": {"id": 2}, "manuallyReversed": True},
        ]}
        self.assertEqual(_non_disbursement_count(loan), 1)

    def test_maturity_change_rejected_before_creating_plan(self):
        settings = SimpleNamespace(target=SimpleNamespace(name="local", tenant="sandbox"))
        versions = {
            "revision": {"DT_CREO": datetime(2026, 10, 15)},
            "before": [{"NO_CUOTA": 1, "FECHA_PAGO": "2027-06-05",
                        "MONTO_CAPITAL": 1180, "MONTO_INTERES": 636.03}],
            "after": [{"NO_CUOTA": 1, "FECHA_PAGO": "2027-06-20",
                       "MONTO_CAPITAL": 1180, "MONTO_INTERES": 702.63}],
        }
        loan = {"id": 2681, "timeline": {"actualDisbursementDate": [2025, 12, 4]}}
        with patch("arissto_sync.loan_event_canary.FineractApi") as api, \
             patch("arissto_sync.loan_event_canary._source_versions", return_value=versions), \
             patch("arissto_sync.loan_event_canary._loan", return_value=loan), \
             patch("arissto_sync.loan_event_canary._portfolio_account_selection",
                   return_value={"gl_id": 885, "maturity": "2027-06-20"}), \
             patch("arissto_sync.loan_event_canary._persisted_rows") as persisted:
            api.return_value.request.return_value = {
                "lifecycleState": "ACTIVE", "cutoffDate": "2026-10-20",
            }
            with self.assertRaisesRegex(ValueError, "reclassification"):
                build_plan(settings, 1597, 240, "hist-1597-oct17", "before", "2026-10-19")
            persisted.assert_not_called()


if __name__ == "__main__":
    unittest.main()
