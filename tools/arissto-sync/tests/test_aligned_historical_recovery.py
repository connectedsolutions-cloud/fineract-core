"""A regenerated child plan must preserve final schedules only on full proof."""
import copy
import unittest
from unittest.mock import MagicMock, patch
from arissto_sync.loans import _recover_aligned_historical_loan, _apply_loan_lifecycle, HISTORICAL_REPLAY_POLICY
from arissto_sync.loan_metric_alignment import METRICS

class AlignedHistoricalRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.metrics = dict.fromkeys(METRICS, '0.00')
        self.frozen = dict(revision=1,cutoffDate='2026-10-27',insuranceChargeId=2,
                           recurringInsuranceChargeId=3,targets=self.metrics)
        self.event = dict(role='repayment', external_id='ARISSTO:CRD-PAY:1',date='2026-10-20',
                          amount='10.00', allocation=dict(principal='8.00',interest='2.00',fee='0.00',penalty='0.00'))
        self.action = dict(external_id='ARISSTO:CRD:1',lifecycle=dict(
            expected=dict(source_state='1'),interest_recalculation_policy=HISTORICAL_REPLAY_POLICY,
            migration_cutover_date='2026-10-27',final_metric_alignment=self.frozen,events=[self.event]))
        self.loan = dict(id=1,externalId=self.action['external_id'],isInterestRecalculationEnabled=False,
                         status=dict(id=300),transactions=[dict(id=10,externalId=self.event['external_id'],
                         date=[2026,10,20],amount='10.00',principalPortion='8.00',interestPortion='2.00',
                         feeChargesPortion='0.00',penaltyChargesPortion='0.00',type=dict(id=2),reversed=False)])
        self.observation=dict(loanId=1,cutoffDate='2026-10-27',alignmentVersion=1,
                              continuationReady=True,metrics=self.metrics)
        self.api=MagicMock()
        def request(method,path,*args,**kwargs):
            self.assertEqual(method,'GET')
            if path.endswith('/migration-metrics'):return self.observation
            if '/transactions/external-id/' in path:return None
            raise AssertionError(path)
        self.api.request.side_effect=request
        self.find=patch('arissto_sync.loans._find_loan',return_value=self.loan).start()
        self.term=patch('arissto_sync.loans._verify_loan_term_account_contract').start()
        self.addCleanup(patch.stopall)

    def recover(self):return _recover_aligned_historical_loan(self.api,self.loan,self.action)

    def test_complete_aligned_history_is_read_only_and_preserves_schedule(self):
        self.loan['repaymentSchedule']={'periods':[{'migrationBaseline':True}]}
        before=copy.deepcopy((self.loan,self.action))
        self.assertTrue(self.recover())
        self.assertEqual((self.loan,self.action),before)
        self.term.assert_called_once_with(self.loan,self.action['lifecycle'],selected=True)

    def test_missing_or_changed_history_cannot_skip_replay(self):
        for field,value in [('amount','11.00'),('principalPortion','7.00'),('date',[2026,10,21]),('reversed',True)]:
            original=self.loan['transactions'][0][field]
            with self.subTest(field=field):
                self.loan['transactions'][0][field]=value
                with self.assertRaises(RuntimeError):self.recover()
                self.loan['transactions'][0][field]=original
        self.loan['transactions']=[]
        with self.assertRaises(RuntimeError):self.recover()

    def test_each_metric_drift_blocks_recovery_without_writes(self):
        for metric in METRICS:
            with self.subTest(metric=metric):
                self.observation['metrics']={**self.metrics,metric:'0.01'}
                with self.assertRaises(RuntimeError):self.recover()

    def test_invalid_identity_status_flag_and_continuation_fail_closed(self):
        cases=[(self.loan,'id',2),(self.loan,'externalId','wrong'),(self.loan,'isInterestRecalculationEnabled',True),
               (self.loan,'status',dict(id=600)),(self.observation,'loanId',2),
               (self.observation,'cutoffDate','2026-10-28'),(self.observation,'alignmentVersion',True),
               (self.observation,'alignmentVersion',-1),(self.observation,'continuationReady',False)]
        for obj,key,value in cases:
            with self.subTest(key=key):
                old=obj[key];obj[key]=value
                with self.assertRaises(RuntimeError):self.recover()
                obj[key]=old

    def test_unaligned_initial_loan_follows_normal_replay(self):
        self.observation.update(alignmentVersion=0,continuationReady=False)
        self.assertFalse(self.recover());self.find.assert_not_called()

    def test_closed_pending_and_recalculated_policies_do_not_probe_metrics(self):
        for state in ['2','3']:
            self.action['lifecycle']['expected']['source_state']=state
            self.assertFalse(self.recover())
        self.action['lifecycle']['expected']['source_state']='1'
        self.action['lifecycle']['interest_recalculation_policy']='daily-native-v1'
        self.assertFalse(self.recover());self.api.request.assert_not_called()

    def test_selected_term_drift_is_not_skipped(self):
        self.term.side_effect=RuntimeError('term_mismatch')
        with self.assertRaisesRegex(RuntimeError,'term_mismatch'):self.recover()

    def test_insurance_baseline_is_verified_before_recovery(self):
        self.action['lifecycle']['cutover_insurance_charge']={'external_id':'insurance'}
        with patch('arissto_sync.loans._ensure_cutover_insurance_charge',side_effect=RuntimeError('charge_drift')) as charge:
            with self.assertRaisesRegex(RuntimeError,'charge_drift'):self.recover()
            charge.assert_called_once()

    def test_regenerated_plan_recovers_before_any_schedule_or_metadata_write(self):
        self.loan.update(loanProductId=3,clientId=2,principal='100.00',portfolioAccountGlId=9)
        self.action['lifecycle']['application_payload']=dict(clientId=2,principal='100.00')
        for writer in ['fineract-variable-installments-v1', 'fineract-source-exact-active-schedule-v1',
                       'fineract-source-exact-remaining-schedule-v1', None]:
            with self.subTest(writer=writer):
                self.action['lifecycle']['schedule_writer']=writer
                self.assertEqual(_apply_loan_lifecycle(self.api,self.action,3), (1,True))
        self.assertTrue(all(call.args[0]=='GET' for call in self.api.request.call_args_list))
