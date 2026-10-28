import copy
import unittest
from arissto_sync.loan_continuation_schedule import verify, required
from arissto_sync.loan_metric_alignment import METRICS

class ContinuationScheduleTests(unittest.TestCase):
    def setUp(self):
        self.targets=dict.fromkeys(METRICS,'0.00')
        self.targets.update(paidPrincipal='10.00',outstandingPrincipal='30.00',duePrincipal='5.00',paidInterest='2.00',accruedInterest='3.00')
        self.frozen=dict(revision=1,cutoffDate='2026-10-27',targets=self.targets)
        self.action=dict(external_id='ARISSTO:CRD:1',lifecycle=dict(expected=dict(source_state='1'),interest_recalculation_policy='source-exact-off-v1',migration_cutover_date='2026-10-27',final_metric_alignment=self.frozen,schedule_reconciliation_policy='exact-source-schedule'))
        self.loan=dict(id=1,externalId='ARISSTO:CRD:1',status=dict(id=300),isInterestRecalculationEnabled=False)
        self.obs=dict(loanId=1,cutoffDate='2026-10-27',alignmentVersion=9,continuationReady=True,metrics=self.targets)
        self.rows=[self.row(1,'2026-10-10',principal='5.00'),self.row(2,'2026-10-26',baseline=True,additional=True,forecast='0.00',principal='10.00',principal_paid='10.00',interest='5.00',interest_paid='2.00'),self.row(3,'2026-11-10',principal='25.00',forecast='4.00')]
        self.source=[dict(due_date='2026-10-10',interest='7.00'),dict(due_date='2026-11-10',interest='4.00')]

    def row(self,number,day,**changes):
        row=dict(external_id='ARISSTO:CRD:1',loan_id=1,number=number,due_date=day,additional=False,baseline=False,forecast=None,
                 principal='0.00',principal_paid='0.00',principal_written_off='0.00',interest='0.00',interest_paid='0.00',interest_waived='0.00',interest_written_off='0.00',audit_id=9,source_day='2026-10-26',targets=self.targets,after=self.targets)
        return {**row,**changes}
    def check(self):return verify(self.loan,self.action,self.obs,self.rows,self.source)

    def test_transformed_schedule_proves_source_calendar_forecast_and_final_native_obligations(self):
        before=copy.deepcopy((self.loan,self.action,self.obs,self.rows,self.source));self.assertEqual(self.check()['baseline_rows'],1)
        self.assertEqual((self.loan,self.action,self.obs,self.rows,self.source),before)
    def test_original_source_principal_and_paid_schedule_are_not_required_after_alignment(self):
        self.source[0].update(principal='400.00',number=99)
        self.assertEqual(self.check()['contractual_rows'],2)
    def test_calendar_date_drift_blocks_even_when_all_metrics_match(self):
        self.rows[-1]['due_date']='2026-11-11'
        with self.assertRaisesRegex(RuntimeError,'calendar_drift'):self.check()
    def test_future_forecast_drift_blocks_even_when_all_metrics_match(self):
        self.rows[-1]['forecast']='4.01'
        with self.assertRaisesRegex(RuntimeError,'forecast_drift'):self.check()
    def test_missing_forecast_is_not_zero(self):
        self.rows[-1]['forecast']=None
        with self.assertRaisesRegex(RuntimeError,'forecast_missing'):self.check()
    def test_future_collectible_interest_is_blocking(self):
        self.rows[-1]['interest']='0.01'
        with self.assertRaisesRegex(RuntimeError,'nonbaseline_settlement'):self.check()
    def test_future_supplemental_installment_cannot_hide_in_a_reference_exception(self):
        self.action['lifecycle']['schedule_reconciliation_policy']='reviewed-manual-adjustment'
        self.rows[-1]['additional']=True
        with self.assertRaisesRegex(RuntimeError,'extra_future'):self.check()
    def test_only_past_supplemental_rows_are_separated_from_contractual_calendar(self):
        self.rows.insert(0,self.row(1,'2026-09-01',additional=True))
        for i,r in enumerate(self.rows,1):r['number']=i
        self.assertEqual(self.check()['contractual_rows'],2)
    def test_reviewed_reference_policy_does_not_exempt_native_component_invariants(self):
        self.action['lifecycle']['schedule_reconciliation_policy']='historical-reference-only'
        self.source[-1]['interest']='5.00';self.assertTrue(self.check()['reviewed_reference_policy'])
        self.rows[-1]['principal']='24.00'
        with self.assertRaisesRegex(RuntimeError,'principal_projection'):self.check()
    def test_shift_between_due_and_future_principal_is_blocking(self):
        self.rows[0]['principal']='4.00';self.rows[-1]['principal']='26.00'
        with self.assertRaisesRegex(RuntimeError,'principal_projection'):self.check()
    def test_negative_outstanding_is_blocking(self):
        self.rows[0]['principal_written_off']='6.00'
        with self.assertRaisesRegex(RuntimeError,'negative_principal'):self.check()
    def test_paid_totals_cannot_be_moved_outside_the_baseline(self):
        self.rows[0].update(principal_paid='1.00',principal='6.00');self.rows[1].update(principal_paid='9.00',principal='9.00')
        with self.assertRaisesRegex(RuntimeError,'nonbaseline_settlement'):self.check()
    def test_audit_date_version_owner_and_vectors_are_strict(self):
        for key,value in [('audit_id',8),('source_day','2026-10-25'),('loan_id',2),('external_id','wrong'),('targets',dict.fromkeys(METRICS,'0.00')),('after',dict.fromkeys(METRICS,'0.00'))]:
            with self.subTest(key=key):
                before=self.rows[0][key];self.rows[0][key]=value
                with self.assertRaisesRegex(RuntimeError,'audit_mismatch'):self.check()
                self.rows[0][key]=before
    def test_duplicate_or_missing_baseline_is_blocking(self):
        for idx,value in [(0,True),(1,False)]:
            with self.subTest(idx=idx):
                before=self.rows[idx]['baseline'];self.rows[idx]['baseline']=value
                with self.assertRaises(RuntimeError):self.check()
                self.rows[idx]['baseline']=before
    def test_baseline_date_additional_flag_and_zero_forecast_are_required(self):
        for key,value in [('due_date','2026-10-25'),('additional',False),('forecast',None),('forecast','1.00')]:
            with self.subTest(key=key):
                before=self.rows[1][key];self.rows[1][key]=value
                with self.assertRaises(RuntimeError):self.check()
                self.rows[1][key]=before
    def test_native_metric_identity_status_and_off_flag_are_required(self):
        cases=[(self.loan,'id',2),(self.loan,'externalId','wrong'),(self.loan,'status',dict(id=600)),(self.loan,'isInterestRecalculationEnabled',True),(self.obs,'loanId',2),(self.obs,'cutoffDate','2026-10-28'),(self.obs,'alignmentVersion',True),(self.obs,'continuationReady',False),(self.obs,'metrics',dict.fromkeys(METRICS,'0.00'))]
        for obj,key,value in cases:
            with self.subTest(key=key):
                old=obj[key];obj[key]=value
                with self.assertRaises(RuntimeError):self.check()
                obj[key]=old
    def test_installment_numbers_must_be_chronological_and_contiguous(self):
        self.rows[-1]['number']=4
        with self.assertRaisesRegex(RuntimeError,'installment_order'):self.check()
    def test_closed_pending_and_recalculated_loans_keep_existing_reconciliation(self):
        for state in ['2','3']:
            self.action['lifecycle']['expected']['source_state']=state;self.assertFalse(required(self.action['lifecycle']))
        self.action['lifecycle']['expected']['source_state']='1'
        self.action['lifecycle']['interest_recalculation_policy']='daily-native-v1';self.assertFalse(required(self.action['lifecycle']))
