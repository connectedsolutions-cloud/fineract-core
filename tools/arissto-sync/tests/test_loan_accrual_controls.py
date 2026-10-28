from copy import deepcopy
import unittest
from unittest.mock import MagicMock, patch
from arissto_sync.loan_accrual_controls import freeze, verify
from arissto_sync.loans import _guard_unmapped_loan_events, _ensure_source_exact_freeze_history, _finalize_loan_history


class AccrualControlTests(unittest.TestCase):
    def events(self):
        return [{'source_event_id':1,'effective_date':'2026-09-01','blocked':True},
                {'source_event_id':2,'effective_date':'2026-09-15','blocked':False}]

    def test_whole_freeze_and_resume_are_two_independent_expected_states(self):
        for events,flag,paused in [(self.events()[:1],'1',True),(self.events(),'0',False),([],None,False)]:
            controls=freeze({'_mora_cutover_snapshot':{'CRD_CONGELADO':flag}},'2026-10-20',events)
            self.assertEqual(controls['ordinaryInterestPaused'],paused)
            self.assertEqual(controls['moraPaused'],paused)
            self.assertEqual(controls['fineractStarts'],'2026-10-20')

    def test_missing_or_conflicting_history_is_not_silently_treated_as_running(self):
        for events,flag in [([], '1'),(self.events()[:1],'0')]:
            with self.assertRaisesRegex(ValueError,'snapshot_history_conflict'):
                freeze({'_mora_cutover_snapshot':{'CRD_CONGELADO':flag}},'2026-10-20',events)

    def test_invalid_history_and_post_boundary_events_are_rejected(self):
        cases=[self.events()[1:],self.events()[:1]*2,
               [{'source_event_id':1,'effective_date':'2026-10-20','blocked':True}]]
        for events in cases:
            with self.subTest(events=events),self.assertRaisesRegex(ValueError,'invalid_source'):
                freeze({},'2026-10-20',events)

    def test_plan_guard_freezes_controls_and_quarantines_snapshot_conflict(self):
        action={'lifecycle':{'expected':{'source_state':'1'},'migration_cutover_date':'2026-10-20'},'quarantine_reasons':[]}
        loan={'_source_freeze_events':self.events()[:1],'_mora_cutover_snapshot':{'CRD_CONGELADO':'1'}}
        actual=_guard_unmapped_loan_events(deepcopy(action),loan)
        self.assertTrue(actual['lifecycle']['accrual_controls']['moraPaused'])
        loan['_mora_cutover_snapshot']['CRD_CONGELADO']='0'
        actual=_guard_unmapped_loan_events(deepcopy(action),loan)
        self.assertIn('source_accrual_control_snapshot_history_conflict',actual['quarantine_reasons'])

    def test_closed_history_is_preserved_without_active_metric_or_accrual_controls(self):
        action={'lifecycle':{'expected':{'source_state':'3'},'migration_cutover_date':'2026-10-20'},'quarantine_reasons':[]}
        loan={'_source_freeze_events':self.events()[:1], '_mora_cutover_snapshot':{'CRD_CONGELADO':'0'}}
        actual=_guard_unmapped_loan_events(deepcopy(action),loan)
        self.assertEqual(actual['quarantine_reasons'],[])
        self.assertEqual(actual['lifecycle']['source_freeze_events'],loan['_source_freeze_events'])
        self.assertEqual(actual['lifecycle']['source_freeze_history_mode'],'repaid-history-v2')
        self.assertNotIn('accrual_controls',actual['lifecycle'])
        self.assertNotIn('final_metric_alignment',actual['lifecycle'])

    def test_invalid_closed_history_still_rejects_before_native_import(self):
        action={'lifecycle':{'expected':{'source_state':'3'},'migration_cutover_date':'2026-10-20'},'quarantine_reasons':[]}
        for events in [self.events()[1:],self.events()[:1]*2,[{'source_event_id':1,'effective_date':'2026-10-20','blocked':True}]]:
            with self.subTest(events=events):
                actual=_guard_unmapped_loan_events(deepcopy(action),{'_source_freeze_events':events})
                self.assertIn('invalid_source_accrual_control_history',actual['quarantine_reasons'])
                self.assertNotIn('source_freeze_history_mode',actual['lifecycle'])

    def test_voided_history_stays_provenance_without_terminal_import_mode(self):
        action={'lifecycle':{'expected':{'source_state':'3'},'migration_cutover_date':'2026-10-20',
                            'financial_reconstruction_omitted':True},'quarantine_reasons':['reviewed_voided_refinance_attempt_omitted']}
        actual=_guard_unmapped_loan_events(deepcopy(action),{'_source_freeze_events':self.events()})
        self.assertEqual(actual['quarantine_reasons'],['reviewed_voided_refinance_attempt_omitted'])
        self.assertNotIn('source_freeze_history_mode',actual['lifecycle'])

    def test_final_closed_history_import_does_not_run_active_catchup(self):
        action={'external_id':'ARISSTO:CRD:1','lifecycle':{'events':[], 'expected':{'source_state':'3'},
                'migration_cutover_date':'2026-10-20','source_freeze_history_mode':'repaid-history-v2',
                'source_freeze_events':self.events()}}
        loan={'id':1,'status':{'id':600},'transactions':[]}
        api=MagicMock();api.request.return_value=loan
        with patch('arissto_sync.loans._ensure_source_exact_freeze_history',return_value=loan) as history, \
             patch('arissto_sync.loans._ensure_source_exact_accrual_catchup') as catchup, \
             patch('arissto_sync.loans._ensure_source_mora_opening_charge') as mora:
            self.assertEqual(_finalize_loan_history(api,loan,action,'attempt',defer_term_selection=False),(1,True))
            history.assert_called_once();catchup.assert_not_called();mora.assert_not_called()

    def test_native_readback_checks_running_and_frozen_controls_without_writes(self):
        for paused in (False,True):
            api=MagicMock();history=[{'action':'FREEZE','effectiveDate':[2026,9,1]}] if paused else []
            api.request.side_effect=[history,[]]
            verify(api,{'id':42,'isFrozen':paused},{'fineractStarts':'2026-10-20','ordinaryInterestPaused':paused,'moraPaused':paused})
            self.assertEqual([c.args[0] for c in api.request.call_args_list],['GET','GET'])

    def test_extra_independent_pause_cannot_pass_running_source_state(self):
        for history,pauses in [([{'action':'MORA_FREEZE','effectiveDate':[2026,9,1]}],[]),
                               ([],[{'startDate':[2026,9,1],'endDate':[2026,10,20]}])]:
            api=MagicMock();api.request.side_effect=[history,pauses]
            with self.assertRaisesRegex(RuntimeError,'native_state_mismatch'):
                verify(api,{'id':42,'isFrozen':False},{'fineractStarts':'2026-10-20','ordinaryInterestPaused':False,'moraPaused':False})

    def test_completed_independent_pause_does_not_stop_handoff(self):
        api=MagicMock();api.request.side_effect=[[],[{'startDate':'2026-09-01','endDate':'2026-10-19'}]]
        verify(api,{'id':42,'isFrozen':False},{'fineractStarts':'2026-10-20','ordinaryInterestPaused':False,'moraPaused':False})

    def test_history_import_installs_resume_and_reads_back_before_completion(self):
        source=self.events();action={'external_id':'ARISSTO:CRD:1572','lifecycle':{'migration_cutover_date':'2026-10-20','source_freeze_events':source}}
        target=[{'sourceEventExternalId':'ARISSTO:AFI-BLOQUEO:'+str(e['source_event_id']),
                 'effectiveDate':e['effective_date'],'action':'FREEZE' if e['blocked'] else 'UNFREEZE'} for e in source]
        api=MagicMock();api.request.side_effect=[[],{},target,{'id':42,'isFrozen':False}]
        result=_ensure_source_exact_freeze_history(api,{'id':42},action,None)
        self.assertFalse(result['isFrozen'])
        request=api.request.call_args_list[1]
        self.assertEqual(request.kwargs['query'],{'command':'sourceExactFreezeHistory'})
        self.assertEqual([e['blocked'] for e in request.args[2]['events']],[True,False])
