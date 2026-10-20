import unittest

from arissto_sync.loan_interest_events import classify_interest_revision


class LoanInterestEventClassificationTests(unittest.TestCase):
    def evidence(self, total_before, total_after, overdue_before, overdue_after,
                 *, pending=False, movement_count=0, paid_after="120.00", plan_unchanged=True):
        audits = [{"FieldName": "FECHA_ULTIMO_PAGOINT"}]
        if pending:
            audits.append({"FieldName": "SALDO_INTERES_PENDIENTE", "OldValue": "0.00",
                           "NewValue": total_after})
        return {
            "closes": [
                {"SALDO_INTERES": total_before, "SALDO_VENCIDO_INTERES": overdue_before,
                 "SALDO_PAGADO_INTERES": "120.00"},
                {"SALDO_INTERES": total_after, "SALDO_VENCIDO_INTERES": overdue_after,
                 "SALDO_PAGADO_INTERES": paid_after},
            ],
            "audits": audits, "movement_count": movement_count,
            "same_close_revision_count": 1,
            "plan_unchanged": plan_unchanged,
        }

    def test_distinguishes_pending_due_relief_from_balance_reduction(self):
        pending = self.evidence("82.79", "82.79", "72.45", "0.00", pending=True)
        reduction = self.evidence("34.21", "1.42", "30.93", "1.42")
        self.assertEqual(classify_interest_revision(pending), "pending_interest_due_relief")
        self.assertEqual(classify_interest_revision(reduction), "interest_balance_recalculation")

    def test_payment_or_plan_change_requires_review(self):
        pending = self.evidence("82.79", "82.79", "72.45", "0.00", pending=True)
        paid = self.evidence("82.79", "82.79", "72.45", "0.00", pending=True,
                             paid_after="125.00")
        for change in (pending | {"movement_count": 1}, paid,
                       pending | {"same_close_revision_count": 2},
                       pending | {"plan_unchanged": False}):
            with self.subTest(change=change):
                self.assertEqual(classify_interest_revision(change), "mixed_or_unresolved")

    def test_pending_marker_without_clean_due_effect_requires_review(self):
        evidence = self.evidence("82.79", "81.09", "72.45", "0.00", pending=True)
        self.assertEqual(classify_interest_revision(evidence), "mixed_or_unresolved")


if __name__ == "__main__":
    unittest.main()
