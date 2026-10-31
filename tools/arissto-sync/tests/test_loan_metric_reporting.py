import unittest
from copy import deepcopy
from arissto_sync.loan_metric_alignment import METRICS
from arissto_sync.loan_metric_reporting import build_active_metric_report

class ActiveMetricReportingTests(unittest.TestCase):
    def fixture(self):
        targets=dict.fromkeys(METRICS,'1.00')
        active={'source_key':'loan:1','entity_type':'loan','action':'recover-loan',
            'lifecycle':{'expected':{'source_state':'1'},'final_metric_alignment':{'targets':targets}}}
        closed=deepcopy(active);closed.update(source_key='loan:2');closed['lifecycle']['expected']['source_state']='3'
        result={'ok':True,'counts':{'continuation_schedules_reconciled':1},'mismatches':[],
            'metric_observations':[{'source_key':'loan:1','actual':dict(targets),
                'insurance':{'owed':'1.00','future':'4.00','scheduled':'5.00','undated':'0.00'}}],
            'variances':[{'source_key':'loan:1','kind':'schedule_due_date','classification':'verified_final_continuation_schedule_variance'},
                         {'source_key':'loan:1','kind':'fee_balance','classification':'native_schedule_component_variance'},
                         {'source_key':'loan:2','kind':'reference_extra','classification':'reference'}]}
        return [active,closed],result

    def test_eight_metrics_only_and_future_insurance_is_separate(self):
        actions,result=self.fixture();report=build_active_metric_report(actions,result)
        self.assertEqual((report['active_loans'],report['expected_checks'],report['matched']),(1,8,8))
        self.assertTrue(report['ok']);self.assertEqual(report['mismatched'],0)
        self.assertEqual(report['reference_details']['inactive_count'],1)
        self.assertEqual(report['insurance'][0],{'source_key':'loan:1','insuranceOwed':'1.00',
            'futureInsurance':'4.00','scheduledInsurance':'5.00','verified':True})
        result['variances'] += [{'source_key':'loan:1','kind':'untracked_report_extra','source':'999999999','target':'0'}]*100
        changed=build_active_metric_report(actions,result)
        self.assertEqual(changed['metrics'],report['metrics']);self.assertTrue(changed['ok'])

    def test_metric_drift_remains_visible_and_integrity_is_independent(self):
        actions,result=self.fixture();result['metric_observations'][0]['actual']['duePrincipal']='0.00'
        result['mismatches']=[{'source_key':'loan:1','kind':'loan_staff_assignment'}]
        report=build_active_metric_report(actions,result)
        self.assertFalse(report['ok']);self.assertEqual(report['mismatched'],1)
        self.assertEqual(report['metrics']['duePrincipal']['matched'],0)
        self.assertEqual(report['integrity_mismatch_count'],1)

    def test_missing_metric_observation_cannot_be_reported_as_matching(self):
        actions,result=self.fixture();result['metric_observations'][0]['actual'].pop('mora')
        report=build_active_metric_report(actions,result)
        self.assertFalse(report['ok']);self.assertFalse(report['complete']);self.assertEqual(report['matched'],0)

    def test_unproven_future_split_is_unknown_instead_of_zero(self):
        actions,result=self.fixture();result['metric_observations'][0]['insurance']['undated']='2.00'
        split=build_active_metric_report(actions,result)['insurance'][0]
        self.assertFalse(split['verified']);self.assertIsNone(split['futureInsurance'])

    def test_legacy_acceptance_requires_strict_continuation_coverage(self):
        actions,result=self.fixture();del result['metric_observations']
        report=build_active_metric_report(actions,result)
        self.assertEqual(report['matched'],8);self.assertEqual(report['verification_basis'],'strict-recorded-continuation')
        result['counts']['continuation_schedules_reconciled']=0
        self.assertFalse(build_active_metric_report(actions,result)['complete'])
