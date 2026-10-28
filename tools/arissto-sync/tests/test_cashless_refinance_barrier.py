"""Cash and settlement disbursements must each be represented exactly once."""
import unittest
from unittest.mock import MagicMock, patch
from arissto_sync.loans import _verify_complete_historical_replay


class CashlessRefinanceBarrierTests(unittest.TestCase):
    def verify(self, gross, cash, portions):
        day = '2026-07-14'
        disbursement = 'ARISSTO:CRD-MOV:100'
        settlements = []
        transactions = {}
        if cash is not None:
            transactions[disbursement] = {'externalId': disbursement, 'amount': str(cash), 'date': [2026, 7, 14]}
        for index, amount in enumerate(portions, 1):
            transfer = f'{disbursement}:REFINANCE:{index}'
            payoff = f'ARISSTO:CRD-MOV:{index}'
            transactions[transfer] = {'externalId': transfer, 'amount': str(amount), 'date': [2026, 7, 14]}
            transactions[payoff] = {'externalId': payoff, 'amount': str(amount), 'date': [2026, 7, 14],
                                    'principalPortion': str(amount), 'interestPortion': '0',
                                    'feeChargesPortion': '0', 'penaltyChargesPortion': '0'}
            settlements.append({'transfer_external_id': transfer, 'payoff_external_id': payoff,
                'payoff_date': day, 'payoff_amount': str(amount), 'predecessor_external_id': f'ARISSTO:CRD:{index}',
                'payoff_allocation': {'principal': str(amount), 'interest': '0', 'fee': '0', 'penalty': '0'},
                'adjustment_external_id': f'bridge:{index}', 'final_adjustment_external_id': f'final:{index}'})
        action = {'external_id': 'ARISSTO:CRD:3', 'lifecycle': {
            'migration_cutover_date': '2026-10-27',
            'events': [{'external_id': disbursement, 'role': 'disbursement', 'date': day, 'amount': str(gross)}],
            'refinance': {'disbursement_external_id': disbursement, 'settlements': settlements}}}
        native = {'id': 3, 'isInterestRecalculationEnabled': False}
        with patch('arissto_sync.loans._find_loan', return_value=native), \
             patch('arissto_sync.loans._find_loan_transaction', side_effect=lambda api, loan, external: transactions.get(external)), \
             patch('arissto_sync.loans._find_reconciliation_transaction', side_effect=AssertionError('Must not alias a cash transaction to a transfer')):
            _verify_complete_historical_replay(MagicMock(), action)

    def test_cashless_refinance_counts_single_or_multiple_transfers_once(self):
        for portions in ([100], [40, 60]):
            with self.subTest(portions=portions): self.verify(100, None, portions)

    def test_cash_and_transfers_must_reconcile_to_gross(self):
        self.verify(120, 20, [40, 60])
        with self.assertRaisesRegex(RuntimeError, 'event_amount_mismatch'):
            self.verify(120, None, [40, 60])
        with self.assertRaisesRegex(RuntimeError, 'event_amount_mismatch'):
            self.verify(120, 30, [40, 60])
