import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from arissto_sync.accounting import AccountingContract
from arissto_sync.accounting_g10_acceptance import _signature, _synthetic_quarantine_result


CONFIG = Path(__file__).resolve().parents[1] / "config/accounting.json"


class AccountingG10AcceptanceTests(unittest.TestCase):

    def test_opposite_signature_is_order_independent(self):
        first = [
            {"account_code": "100", "destination_branch_id": "001", "debit": Decimal("3.00"), "credit": 0},
            {"account_code": "200", "destination_branch_id": "001", "debit": 0, "credit": Decimal("3.00")},
        ]
        second = [
            {"account_code": "200", "destination_branch_id": "001", "debit": Decimal("3.00"), "credit": 0},
            {"account_code": "100", "destination_branch_id": "001", "debit": 0, "credit": Decimal("3.00")},
        ]
        self.assertEqual(_signature(first, reverse=True), _signature(second))

    def test_synthetic_negative_matrix_covers_unavailable_live_cases(self):
        target = {
            "accounts": {"1110010199": [{"id": 1, "disabled": False, "manual_allowed": True}]},
            "offices": {1: {"external_id": "1"}}, "closure_by_office": {},
        }
        result = _synthetic_quarantine_result(AccountingContract.load(CONFIG), target)
        self.assertTrue(result["passed"])
        self.assertTrue({
            "SOURCE_JOURNAL_UNBALANCED", "SOURCE_ACCOUNT_UNRESOLVED",
            "SOURCE_DESTINATION_BRANCH_UNMAPPED", "TARGET_OFFICE_CLOSURE_CONFLICT",
        } <= set(result["reason_codes"]))


if __name__ == "__main__":
    unittest.main()
