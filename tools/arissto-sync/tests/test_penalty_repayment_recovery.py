"""LS-29: recover posted penalty payments without recreating charge history."""
import copy
import unittest
from unittest.mock import MagicMock, patch

from tests import test_loans as fixtures
from arissto_sync.loans import _apply_loan_lifecycle, _build_loan_lifecycle_action


class PenaltyRepaymentRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.LoanInspectionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        row, history, target, payload = fixture.lifecycle_fixture()
        built = _build_loan_lifecycle_action(fixture.contract, row, history, target, payload)
        lifecycle = built['lifecycle']
        lifecycle['mora_terms']['fineract_starts_on'] = '2026-06-21'
        self.event = lifecycle['events'][-1]
        self.event.update(allocation={'principal': '8.00', 'interest': '0.69', 'fee': '0.00', 'penalty': '1.31'},
                          penalty_charge_id=9, penalty_charge_external_id='ARISSTO:CRD-MOV:101:PENALTY')
        lifecycle.update(events=[self.event], cutover_insurance_charge=None, recurring_insurance_charge=None,
                         terminal_adjustment=None)
        self.action = {'entity_source_key': '2068', 'external_id': 'ARISSTO:CRD:2068', 'lifecycle': lifecycle}
        self.tx = {'id': 2, 'externalId': self.event['external_id'], 'amount': '10.00', 'date': [2026, 6, 20],
                   'principalPortion': '8.00', 'interestPortion': '0.69', 'feeChargesPortion': '0.00',
                   'penaltyChargesPortion': '1.31', 'loanChargePaidByList': []}
        self.loan = {'id': 55, 'loanProductId': 90, 'clientId': 900, 'principal': 350,
                     'isInterestRecalculationEnabled': True, 'status': {'id': 300}, 'charges': [],
                     'transactions': [self.tx], 'repaymentSchedule': fixture.calculated_schedule(lifecycle)}
        self.api = MagicMock()
        self.api.request.side_effect = self.request
        self.posted = []

    def request(self, method, path, payload=None, **kwargs):
        if method == 'POST':
            self.posted.append((path, payload, kwargs))
            if kwargs.get('query') != {'command': 'sourceExactRepayment'}:
                raise AssertionError('Recovery must not recreate historical charges')
            self.loan['transactions'] = [self.tx]
            return {}
        return self.loan

    def apply(self, finalize=False):
        with (patch('arissto_sync.loans._find_loan', return_value=self.loan),
              patch('arissto_sync.loans._ensure_source_exact_guarantors')):
            return _apply_loan_lifecycle(self.api, self.action, 90, finalize=finalize)

    def test_existing_penalty_repayment_recovers_with_charge_omitted_for_all_payment_roles(self):
        for role in ['repayment', 'adjusted-repayment', 'mobile-collection-repayment']:
            with self.subTest(role=role):
                self.event['role'] = role
                before = copy.deepcopy(self.loan)
                self.assertEqual(self.apply(), (55, True))
                self.assertEqual(self.loan, before)
                self.assertEqual(self.posted, [])

    def test_existing_penalty_repayment_does_not_mutate_visible_charge_state(self):
        for charge in [{'active': False, 'amount': '1.31', 'amountPaid': '0', 'amountOutstanding': '1.31'},
                       {'active': True, 'amount': '1.31', 'amountPaid': '1.31', 'amountOutstanding': '0'}]:
            with self.subTest(active=charge['active']):
                self.loan['charges'] = [{'id': 17, 'externalId': self.event['penalty_charge_external_id'], **charge}]
                before = copy.deepcopy(self.loan)
                self.assertEqual(self.apply(), (55, True))
                self.assertEqual(self.loan, before)
                self.assertEqual(self.posted, [])

    def test_existing_payment_amount_drift_still_fails_without_charge_writes(self):
        self.tx['amount'] = '9.99'
        with self.assertRaisesRegex(RuntimeError, 'loan_transaction_amount_mismatch'):
            self.apply()
        self.assertEqual(self.posted, [])

    def test_existing_payment_date_drift_still_fails_without_charge_writes(self):
        self.tx['date'] = [2026, 6, 21]
        with self.assertRaisesRegex(RuntimeError, 'loan_transaction_date_mismatch'):
            self.apply()
        self.assertEqual(self.posted, [])

    def test_existing_payment_component_drift_still_fails_without_charge_writes(self):
        for field in ['principalPortion', 'interestPortion', 'feeChargesPortion', 'penaltyChargesPortion']:
            with self.subTest(field=field):
                old = self.tx[field]
                self.tx[field] = '0.01'
                with self.assertRaisesRegex(RuntimeError, 'loan_repayment_allocation_mismatch'):
                    self.apply()
                self.tx[field] = old
                self.assertEqual(self.posted, [])

    def test_duplicate_source_payment_identity_still_fails(self):
        self.loan['transactions'].append(dict(self.tx, id=3))
        with self.assertRaisesRegex(RuntimeError, 'duplicate_target_loan_transaction_external_id'):
            self.apply()
        self.assertEqual(self.posted, [])

    def test_new_payment_still_requires_penalty_charge_before_posting(self):
        self.loan['transactions'] = []
        with patch('arissto_sync.loans._ensure_source_penalty_charge', return_value=self.loan) as ensure:
            self.assertEqual(self.apply(), (55, True))
            ensure.assert_called_once_with(self.api, self.loan, self.event, None)
        self.assertEqual(len(self.posted), 1)
        self.assertEqual(self.posted[0][1]['penaltyChargesPortion'], '1.31')

    def test_new_payment_does_not_post_if_charge_provisioning_fails(self):
        self.loan['transactions'] = []
        with patch('arissto_sync.loans._ensure_source_penalty_charge', side_effect=RuntimeError('charge-proof-failed')):
            with self.assertRaisesRegex(RuntimeError, 'charge-proof-failed'):
                self.apply()
        self.assertEqual(self.posted, [])


    def add_insurance(self):
        self.event['allocation'].update(principal='7.68', fee='0.32')
        self.tx.update(principalPortion='7.68', feeChargesPortion='0.32')
        self.event['historical_insurance_charges'] = [{
            'external_id': 'ARISSTO:CRD-INS:7:101:1', 'amount': '0.32',
            'charge_id': 8, 'due_date': self.event['date']}]
        return {'id': 18, 'externalId': 'ARISSTO:CRD-INS:7:101:1',
                'amount': '0.32', 'amountPaid': '0.32', 'amountOutstanding': '0.00'}

    def insurance_lookup(self, charge):
        def request(method, path, payload=None, **kwargs):
            if method == 'GET' and '/charges/external-id/' in path:
                return charge
            return self.request(method, path, payload, **kwargs)
        self.api.request.side_effect = request

    def test_existing_payment_with_hidden_paid_insurance_verifies_without_recreation(self):
        charge = self.add_insurance()
        self.insurance_lookup(charge)
        for role in ['repayment', 'adjusted-repayment', 'mobile-collection-repayment']:
            with self.subTest(role=role):
                self.event['role'] = role
                before = copy.deepcopy((self.loan, charge))
                self.assertEqual(self.apply(finalize=True), (55, True))
                self.assertEqual((self.loan, charge), before)
                self.assertEqual(self.posted, [])
        self.assertTrue(any('/charges/external-id/' in call.args[1] for call in self.api.request.call_args_list))

    def test_missing_historical_insurance_still_fails_existing_payment_settlement(self):
        self.add_insurance()
        self.insurance_lookup(None)
        with self.assertRaisesRegex(RuntimeError, 'historical_insurance_charge_missing'):
            self.apply(finalize=True)
        self.assertEqual(self.posted, [])

    def test_unpaid_historical_insurance_still_fails_existing_payment_settlement(self):
        charge = self.add_insurance()
        charge['amountOutstanding'] = '0.32'
        self.insurance_lookup(charge)
        with self.assertRaisesRegex(RuntimeError, 'historical_insurance_charge_not_settled'):
            self.apply(finalize=True)
        self.assertEqual(self.posted, [])

    def test_historical_insurance_amount_drift_still_fails_settlement(self):
        charge = self.add_insurance()
        charge['amount'] = '0.31'
        self.insurance_lookup(charge)
        with self.assertRaisesRegex(RuntimeError, 'historical_insurance_charge_amount_mismatch'):
            self.apply(finalize=True)
        self.assertEqual(self.posted, [])

    def test_wrong_historical_insurance_identity_still_fails_settlement(self):
        charge = self.add_insurance()
        charge['externalId'] = 'OTHER'
        self.insurance_lookup(charge)
        with self.assertRaisesRegex(RuntimeError, 'historical_insurance_charge_identity_mismatch'):
            self.apply(finalize=True)
        self.assertEqual(self.posted, [])

    def test_new_fee_payment_still_provisions_insurance_before_posting(self):
        self.add_insurance()
        self.loan['transactions'] = []
        with (patch('arissto_sync.loans._ensure_source_penalty_charge', return_value=self.loan),
              patch('arissto_sync.loans._ensure_source_insurance_charges', return_value=self.loan) as ensure):
            self.assertEqual(self.apply(), (55, True))
            ensure.assert_called_once_with(self.api, self.loan, self.event, None)
        self.assertEqual(self.posted[0][1]['feeChargeExternalId'], 'ARISSTO:CRD-INS:7:101:1')


if __name__ == '__main__':
    unittest.main()
