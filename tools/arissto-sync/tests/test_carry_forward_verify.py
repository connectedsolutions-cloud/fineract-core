import unittest
from datetime import date
from decimal import Decimal

from arissto_sync.carry_forward_verify import candidate_rejection


class CarryForwardCandidateVerificationTests(unittest.TestCase):
    def setUp(self):
        self.action = {"source_hash": "hash-a", "target_id": 12}
        self.mapping = ("12", "hash-a")
        self.row = ("ARISSTO:CRD:1", 12, 600, date(2026, 10, 5),
                    Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
        self.cutoff = date(2026, 10, 6)

    def check(self, mapping=None, row=None, late=0, charge=Decimal("0")):
        return candidate_rejection(self.action, self.mapping if mapping is None else mapping,
                                   self.row if row is None else row, late, charge, self.cutoff)

    def test_closed_zero_balance_loan_passes_loan_level_check(self):
        self.assertIsNone(self.check())

    def test_fresh_plan_without_target_id_uses_accepted_mapping(self):
        self.action["target_id"] = None
        self.assertIsNone(self.check())

    def test_mapping_drift_fails(self):
        self.assertEqual(self.check(mapping=("12", "hash-b")),
                         "mapping_missing_or_source_hash_changed")

    def test_cutoff_day_close_or_late_transaction_fails(self):
        row = self.row[:3] + (date(2026, 10, 6),) + self.row[4:]
        self.assertEqual(self.check(row=row), "target_not_closed_before_seed_cutoff")
        self.assertEqual(self.check(late=1), "target_transaction_on_or_after_seed_cutoff")

    def test_residual_balance_or_charge_fails(self):
        row = self.row[:4] + (Decimal("0.01"),) + self.row[5:]
        self.assertEqual(self.check(row=row), "target_balance_not_zero")
        self.assertEqual(self.check(charge=Decimal("0.01")), "target_balance_not_zero")


if __name__ == "__main__":
    unittest.main()
