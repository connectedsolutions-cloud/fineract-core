"""LS-31: recover proven final insurance baselines without restoring old debt."""
import copy
import unittest
from unittest.mock import MagicMock, patch

from arissto_sync.loans import _ensure_cutover_insurance_charge, _apply_loan_lifecycle, _build_loan_lifecycle_action
from arissto_sync.loan_metric_alignment import METRICS
from tests import test_loans as fixtures


class CutoverInsuranceBaselineRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.metrics = dict.fromkeys(METRICS, '1.00')
        self.metrics.update(insurancePaid='4.22', insuranceOutstanding='6.45')
        self.frozen = {'revision': 1, 'cutoffDate': '2026-10-27', 'insuranceChargeId': 2,
                       'recurringInsuranceChargeId': 3, 'penaltyChargeId': 4, 'targets': self.metrics}
        self.template = {'amount': '6.45', 'charge_id': 2, 'classification': 'source_insurance_cutover_outstanding',
                         'due_date': '2026-05-26', 'external_id': 'ARISSTO:CRD-INS-CUTOVER:515'}
        self.action = {'external_id': 'ARISSTO:CRD:515', 'lifecycle': {
            'migration_cutover_date': '2026-10-27', 'final_metric_alignment': self.frozen,
            'cutover_insurance_charge': self.template}}
        self.old = self.charge('ARISSTO:CRD-INS-CUTOVER:515', '2026-05-26', '0', '0', '0')
        self.baseline = self.charge('ARISSTO:CRD-METRICS:INS:55', '2026-10-26', '7.41', '0.96', '6.45')
        self.loan = {'id': 55, 'externalId': 'ARISSTO:CRD:515', 'currency': {'code': 'USD'},
                     'charges': [self.old, self.baseline]}
        self.observation = {'loanId': 55, 'cutoffDate': '2026-10-27', 'alignmentVersion': 21,
                            'continuationReady': True, 'metrics': copy.deepcopy(self.metrics)}
        self.api = MagicMock()
        self.api.request.side_effect = self.request

    def charge(self, external, due, amount, paid, outstanding):
        return {'id': 101 if 'CUTOVER' in external else 102, 'externalId': external,
                'loanId': 55, 'externalLoanId': 'ARISSTO:CRD:515', 'chargeId': 2, 'penalty': False,
                'chargeTimeType': {'id': 2}, 'chargeCalculationType': {'id': 1}, 'currency': {'code': 'USD'},
                'dueDate': [int(x) for x in due.split('-')], 'amount': amount, 'amountPaid': paid,
                'amountOutstanding': outstanding, 'amountWaived': '0', 'amountWrittenOff': '0'}

    def request(self, method, path, *args, **kwargs):
        self.assertEqual(method, 'GET', 'A proven baseline must be recovered without writes')
        if path.endswith('/migration-metrics'):
            return self.observation
        if '/charges/external-id/' in path:
            return self.old
        raise AssertionError(path)

    def ensure(self):
        return _ensure_cutover_insurance_charge(self.api, self.loan, self.action, 'retry')

    def test_proven_paid_and_outstanding_baseline_recovers_without_changing_any_state(self):
        before = copy.deepcopy((self.loan, self.action, self.observation))
        self.assertIs(self.ensure(), self.loan)
        self.assertEqual((self.loan, self.action, self.observation), before)
        self.assertTrue(all(c.args[0] == 'GET' for c in self.api.request.call_args_list))

    def test_all_three_demonstrated_balances_recover_without_recreating_old_charge(self):
        for amount in ['12.54', '7.82', '6.45']:
            with self.subTest(amount=amount):
                self.metrics['insuranceOutstanding'] = amount
                self.observation['metrics']['insuranceOutstanding'] = amount
                self.template['amount'] = amount
                self.baseline.update(amount=amount, amountPaid='0', amountOutstanding=amount)
                self.assertIs(self.ensure(), self.loan)

    def test_metric_drift_in_any_component_fails_without_adjusting_staff_activity(self):
        for metric in METRICS:
            with self.subTest(metric=metric):
                old = self.observation['metrics'][metric]
                self.observation['metrics'][metric] = '0.50'
                with self.assertRaisesRegex(RuntimeError, 'cutover_insurance_baseline_'):
                    self.ensure()
                self.observation['metrics'][metric] = old
        self.assertTrue(all(c.args[0] == 'GET' for c in self.api.request.call_args_list))

    def test_prior_alignment_metadata_must_match_loan_cutoff_and_continuation(self):
        for field, value in [('loanId', 56), ('cutoffDate', '2026-10-28'), ('alignmentVersion', None),
                             ('alignmentVersion', -1), ('alignmentVersion', 0), ('continuationReady', False)]:
            with self.subTest(field=field, value=value):
                before = self.observation[field]
                self.observation[field] = value
                with self.assertRaisesRegex(RuntimeError, 'cutover_insurance_baseline_'):
                    self.ensure()
                self.observation[field] = before

    def test_missing_or_duplicate_active_baseline_does_not_fall_back_to_creating_debt(self):
        for charges in [[self.old], [self.old, self.baseline, dict(self.baseline)]]:
            with self.subTest(count=len(charges)):
                self.loan['charges'] = charges
                with self.assertRaises(RuntimeError):
                    self.ensure()

    def test_charge_owner_identity_definition_dates_and_amounts_are_required(self):
        changes = [('loanId', 99), ('externalLoanId', 'ARISSTO:CRD:999'), ('chargeId', 99), ('penalty', True),
                   ('currency', {'code': 'EUR'}), ('chargeTimeType', {'id': 1}), ('chargeCalculationType', {'id': 2}),
                   ('dueDate', [2026, 10, 27]), ('amountOutstanding', '6.44'), ('amount', '8.00'),
                   ('amountPaid', '-1'), ('amountWaived', '1'), ('amountWrittenOff', '1')]
        for field, value in changes:
            with self.subTest(field=field):
                before = self.baseline[field]
                self.baseline[field] = value
                with self.assertRaisesRegex(RuntimeError, 'cutover_insurance_baseline_'):
                    self.ensure()
                self.baseline[field] = before

    def test_original_charge_must_be_zeroed_and_still_belong_to_this_loan(self):
        for field, value in [('amount', '6.45'), ('amountPaid', '0.01'), ('amountOutstanding', '0.01'),
                             ('amountWaived', '1'), ('loanId', 99), ('externalLoanId', 'ARISSTO:CRD:999'),
                             ('chargeId', 99), ('dueDate', [2026, 5, 27])]:
            with self.subTest(field=field):
                before = self.old[field]
                self.old[field] = value
                with self.assertRaisesRegex(RuntimeError, 'cutover_insurance_baseline_'):
                    self.ensure()
                self.old[field] = before

    def test_frozen_insurance_target_and_loan_identity_must_agree(self):
        self.template['amount'] = '7.00'
        with self.assertRaisesRegex(RuntimeError, 'cutover_insurance_baseline_'):
            self.ensure()
        self.template['amount'] = '6.45'
        self.loan['externalId'] = 'ARISSTO:CRD:999'
        with self.assertRaisesRegex(RuntimeError, 'cutover_insurance_baseline_'):
            self.ensure()

    def test_unaligned_initial_loan_still_uses_normal_charge_provisioning(self):
        self.loan['charges'] = []
        self.observation.update(alignmentVersion=0, continuationReady=False)
        with patch('arissto_sync.loans._ensure_source_insurance_charges', return_value=self.loan) as normal:
            self.assertIs(self.ensure(), self.loan)
            normal.assert_called_once()

    def test_legacy_plan_without_final_metrics_keeps_existing_guard(self):
        self.action['lifecycle']['final_metric_alignment'] = None
        with self.assertRaisesRegex(RuntimeError, 'existing_insurance_charge_outstanding_mismatch'):
            self.ensure()
        self.api.request.assert_not_called()

    def test_native_lifecycle_uses_baseline_proof_instead_of_restoring_cutover_charge(self):
        fixture = fixtures.LoanInspectionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        row, history, target, payload = fixture.lifecycle_fixture()
        built = _build_loan_lifecycle_action(fixture.contract, row, history, target, payload)
        lifecycle = built['lifecycle']
        lifecycle.update(events=[], cutover_insurance_charge=self.template, recurring_insurance_charge=None,
                         interest_recalculation_policy='daily-native-v1',
                         terminal_adjustment=None, final_metric_alignment=self.frozen)
        lifecycle['mora_terms']['fineract_starts_on'] = '2026-06-21'
        action = {**self.action, 'entity_source_key': '515', 'lifecycle': lifecycle}
        self.loan.update(loanProductId=90, clientId=900, principal=350, isInterestRecalculationEnabled=True,
                         status={'id': 300}, transactions=[], repaymentSchedule=fixture.calculated_schedule(lifecycle))
        with (patch('arissto_sync.loans._find_loan', return_value=self.loan),
              patch('arissto_sync.loans._ensure_source_exact_guarantors')):
            self.assertEqual(_apply_loan_lifecycle(self.api, action, 90), (55, True))


    def test_initial_missing_charge_is_still_created_and_verified(self):
        self.loan['charges'] = []
        self.observation.update(alignmentVersion=0, continuationReady=False)
        posts = []
        def request(method, path, payload=None, **kwargs):
            if method == 'POST':
                posts.append((path, payload, kwargs))
                self.loan['charges'] = [dict(self.old, amount='6.45', amountOutstanding='6.45')]
                return {}
            return self.observation if path.endswith('/migration-metrics') else self.loan
        self.api.request.side_effect = request
        self.assertIs(self.ensure(), self.loan)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][2]['query'], {'command': 'sourceExactAddCharge'})
        self.assertEqual(posts[0][1]['externalId'], self.template['external_id'])
        self.assertEqual(posts[0][1]['amount'], '6.45')

    def test_hidden_zero_original_is_verified_by_exact_identity_without_creation(self):
        self.loan['charges'] = [self.baseline]
        self.assertIs(self.ensure(), self.loan)
        self.assertEqual(self.api.request.call_args.args[:2],
                         ('GET', 'loans/55/charges/external-id/ARISSTO:CRD-INS-CUTOVER:515'))

    def test_missing_or_malformed_amounts_are_rejected_read_only(self):
        for value in [None, 'bad', 'NaN', 'Infinity', '-0.01', '7.4101']:
            with self.subTest(value=value):
                self.baseline['amount'] = value
                with self.assertRaisesRegex(RuntimeError, 'cutover_insurance_baseline_'):
                    self.ensure()
        self.assertTrue(all(c.args[0] == 'GET' for c in self.api.request.call_args_list))

    def test_incomplete_metric_vector_and_missing_currency_cannot_supply_proof(self):
        self.observation['metrics'].pop('mora')
        with self.assertRaisesRegex(RuntimeError, 'cutover_insurance_baseline_metrics_invalid'):
            self.ensure()
        self.observation['metrics'] = copy.deepcopy(self.metrics)
        self.loan.pop('currency')
        self.baseline.pop('currency')
        with self.assertRaisesRegex(RuntimeError, 'cutover_insurance_baseline_'):
            self.ensure()


if __name__ == '__main__':
    unittest.main()
