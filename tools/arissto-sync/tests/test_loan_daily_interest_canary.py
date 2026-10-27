import unittest
from datetime import date
from decimal import Decimal

from arissto_sync.loan_daily_interest_canary import native_interest_as_of


class DailyInterestProjectionTests(unittest.TestCase):
    def test_current_period_uses_next_business_day_and_respects_waiver(self):
        loan = {"repaymentSchedule": {"periods": [{
            "period": 1, "fromDate": [2026, 10, 15], "dueDate": [2026, 11, 15],
            "interestDue": "142.68", "interestPaid": "0.00",
            "interestWaived": "0.00", "interestOutstanding": "142.68",
        }]}}
        self.assertEqual(native_interest_as_of(loan, date(2026, 10, 20)), Decimal("23.01"))
        self.assertEqual(native_interest_as_of(loan, date(2026, 10, 24)), Decimal("41.42"))

        loan["repaymentSchedule"]["periods"][0]["interestWaived"] = "18.41"
        self.assertEqual(native_interest_as_of(loan, date(2026, 10, 20)), Decimal("4.60"))

    def test_due_interest_uses_outstanding_installments(self):
        loan = {"repaymentSchedule": {"periods": [
            {"period": 1, "fromDate": [2026, 9, 20], "dueDate": [2026, 10, 20],
             "interestDue": "10.00", "interestPaid": "3.00", "interestWaived": "2.00",
             "interestOutstanding": "5.00"},
            {"period": 2, "fromDate": [2026, 10, 20], "dueDate": [2026, 11, 20],
             "interestDue": "31.00", "interestPaid": "0.00", "interestWaived": "0.00",
             "interestOutstanding": "31.00"},
        ]}}
        self.assertEqual(native_interest_as_of(loan, date(2026, 10, 21)), Decimal("6.00"))


if __name__ == "__main__":
    unittest.main()
