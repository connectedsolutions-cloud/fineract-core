from __future__ import annotations
import threading
import unittest
from collections import Counter
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from arissto_sync.loan_metric_alignment import METRICS, align, amounts, freeze
from arissto_sync.loans import apply_loan_plan, LoanApplyControls
import tests.test_loans as fixtures


class FinalMetricTests(unittest.TestCase):
    def vector(self, value='1.00'):
        return dict.fromkeys(METRICS, value)

    def action(self):
        return {'external_id': 'ARISSTO:CRD:1', 'lifecycle': {'expected': {'source_state':'1'}, 'final_metric_alignment': {
            'revision': 1, 'cutoffDate': '2026-10-20', 'targets': self.vector('2.00'),
            'insuranceChargeId': 3, 'recurringInsuranceChargeId': 5, 'penaltyChargeId': 4}}}

    def test_equal_metrics_are_zero_write(self):
        api=MagicMock(); api.request.return_value={'metrics': self.vector('2.00'), 'continuationReady': True}
        self.assertFalse(align(api,1,self.action(),'2026-10-26T15:00:00Z')['changed'])
        self.assertEqual([c.args[0] for c in api.request.call_args_list],['GET'])

    def test_correction_is_expected_state_guarded_and_verified_after_write(self):
        api=MagicMock(); api.request.side_effect=[{'metrics':self.vector()},{'metrics':self.vector('2.00'),'continuationReady':True},{'metrics':self.vector('2.00'),'continuationReady':True}]
        result=align(api,1,self.action(),'2026-10-26T15:00:00Z')
        self.assertTrue(result['changed'])
        payload=api.request.call_args_list[1].args[2]
        self.assertEqual(payload['expected'],self.vector())
        self.assertEqual(payload['targets'],self.vector('2.00'))
        self.assertEqual(payload['sourceLoanExternalId'],'ARISSTO:CRD:1')
        self.assertEqual([c.args[0] for c in api.request.call_args_list],['GET','POST','GET'])

    def test_equal_amounts_still_initialize_missing_continuation_state(self):
        api=MagicMock();api.request.side_effect=[{'metrics':self.vector('2.00'),'continuationReady':False},
            {'metrics':self.vector('2.00'),'changed':False},{'metrics':self.vector('2.00'),'continuationReady':True}]
        result=align(api,1,self.action(),'2026-10-26T15:00:00Z')
        self.assertFalse(result['changed'])
        self.assertEqual([c.args[0] for c in api.request.call_args_list],['GET','POST','GET'])

    def test_later_final_pass_can_repeat_a_previous_transition(self):
        identities=[]
        for version in (1,2):
            api=MagicMock();api.request.side_effect=[{'metrics':self.vector(),'alignmentVersion':version},
                {'metrics':self.vector('2.00'),'continuationReady':True},{'metrics':self.vector('2.00'),'continuationReady':True}]
            align(api,1,self.action(),'2026-10-26T15:00:00Z')
            identities.append(api.request.call_args_list[1].args[2]['requestId'])
        self.assertNotEqual(*identities)

    def test_failed_persisted_verification_is_not_success(self):
        api=MagicMock(); api.request.side_effect=[{'metrics':self.vector()},{'metrics':self.vector('2.00'),'continuationReady':True},{'metrics':self.vector(),'continuationReady':True}]
        with self.assertRaisesRegex(RuntimeError,'persisted_readback'):
            align(api,1,self.action(),'2026-10-26T15:00:00Z')

    def test_source_paid_insurance_uses_dedicated_counter_and_missing_is_not_zero(self):
        loan={'_mora_cutover_snapshot':{'SALDO_PAGADO_CAPITAL':'8','SALDO_PAGADO_INTERES':'3','SALDO_PAGADO_SEGURO':'2','SALDO_PAGADO_OTROS':'999','SALDO_VENCIDO_CAPITAL':'4','MONTO_DESEMBOLSADO':'18','SALDO_INTERES':'1','SALDO_MORA':'0','SALDO_RECARGOS':'0','SALDO_SEGURO':'0.5'}}
        expected={'source_state':'1','principal_balance':'10','interest_balance':'1','penalty_balance':'0','fee_balance':'0.5'}
        resources={'historical_debt_insurance_charge_id':3,'debt_insurance_charge_id':5,'historical_penalty_charge_id':4}
        frozen=freeze(loan,expected,resources,'2026-10-20')
        self.assertEqual(frozen['targets']['insurancePaid'],'2.00')
        loan['_mora_cutover_snapshot'].pop('SALDO_PAGADO_SEGURO')
        self.assertIsNone(freeze(loan,expected,resources,'2026-10-20'))
        events=[{'role':'repayment','external_id':'p1','allocation':{'fee':'999'}}]
        self.assertEqual(freeze(loan,expected,resources,'2026-10-20',events)['targets']['insurancePaid'],'999.00')
        events.append({'role':'repayment-reversal','original_external_id':'p1'})
        self.assertIsNone(freeze(loan,expected,resources,'2026-10-20',events))
        loan['_mora_cutover_snapshot'].pop('SALDO_PAGADO_OTROS')
        self.assertIsNone(freeze(loan,expected,resources,'2026-10-20'))

    def test_inconsistent_observation_can_be_corrected_but_cannot_be_a_target(self):
        before = self.vector(); before['duePrincipal'] = '2.00'
        api = MagicMock(); api.request.side_effect = [
            {'metrics': before}, {'metrics': self.vector('2.00')},
            {'metrics': self.vector('2.00'), 'continuationReady': True}]
        align(api, 1, self.action(), '2026-10-26T15:00:00Z')
        self.assertEqual(api.request.call_args_list[1].args[2]['expected'], before)
        with self.assertRaisesRegex(RuntimeError, 'due_exceeds'):
            amounts(before)

    def test_closed_and_pending_source_loans_never_call_metrics_api(self):
        for state in ('3', '2', None):
            action = self.action(); action['lifecycle']['expected']['source_state'] = state
            api = MagicMock()
            with self.assertRaisesRegex(RuntimeError, 'requires_active_source'):
                align(api, 1, action, '2026-10-26T15:00:00Z')
            api.request.assert_not_called()
            self.assertIsNone(freeze({}, {'source_state':state}, {}, '2026-10-27'))

    def test_invalid_target_vectors_are_rejected(self):
        for bad in ({},self.vector('-1'),self.vector('0.001'),self.vector('NaN')):
            with self.subTest(bad=bad),self.assertRaises(RuntimeError): amounts(bad)
        bad=self.vector();bad['duePrincipal']='2'
        with self.assertRaisesRegex(RuntimeError,'due_exceeds'): amounts(bad)

    def test_actual_apply_coordinator_runs_final_pass_after_all_workers(self):
        fixture=fixtures.LoanInspectionTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        product={'source_key':'product:00001','entity_type':'product','entity_source_key':'00001',
                 'source_company_id':'001','action':'create-product','depends_on':[],'source_hash':'p',
                 'external_id':'ARISSTO:CRD-LINE:00001','payload':{},'crosswalk':{'repair_after_product_resolution':True},'target_id':None}
        loans=[]
        for key in (1,2):
            action=self.action(); action.update(source_key=f'loan:{key}',entity_type='loan',entity_source_key=str(key),
                action='create-loan',depends_on=['product:00001'],product_action_key='product:00001',source_hash=f'h{key}',target_id=None,external_id=f'ARISSTO:CRD:{key}')
            action["lifecycle"]["accrual_controls"]={"ordinaryInterestPaused":False,"moraPaused":False,"fineractStarts":"2026-10-20"}
            loans.append(action)
        plan={'id':'p','document':{'actions':[product,*loans],'final_metric_alignment_revision':2,'source_observed_at':'2026-10-26T15:00:00Z'}}
        settings=SimpleNamespace(target=SimpleNamespace(fingerprint='target'));state=MagicMock();state.start_run.return_value='run'
        state.run_items.return_value=[{'source_key':f'loan:{k}','status':'succeeded','target_id':str(k)} for k in (1,2)]
        log=[];barrier=threading.Barrier(2)
        def history(_api,action,_product,_run):
            barrier.wait(timeout=3);log.append('history:'+action['entity_source_key']);return int(action['entity_source_key']),False
        def metrics(api,lid,action,observed):
            self.assertEqual(sum(e.startswith('history:') for e in log),2)
            self.assertIn('controls:'+str(lid),log)
            log.append('metrics:'+str(lid));return {'changed':True}
        with patch('arissto_sync.loans._loan_apply_guard',return_value=(plan,{'products':{'00001':None},'crosswalks':{}})), \
             patch('arissto_sync.loans.FineractApi'), \
             patch('arissto_sync.loans._resolve_or_create_loan_product',return_value=(91,False)), \
             patch('arissto_sync.loans._upsert_loan_product_crosswalk'), \
             patch('arissto_sync.loans._apply_loan_lifecycle',side_effect=history), \
             patch('arissto_sync.loans._find_loan',side_effect=lambda api,external:{'id':int(external.rsplit(':',1)[1]),'status':{'id':300}}), \
             patch('arissto_sync.loan_accrual_controls.verify',side_effect=lambda api,native,controls: log.append('controls:'+str(native['id']))), \
             patch('arissto_sync.loan_metric_alignment.align',side_effect=metrics):
            _,counts=apply_loan_plan(settings,state,fixture.contract,'p',controls=LoanApplyControls(workers=2,pause_seconds=0,recovery_attempts=1))
        self.assertEqual(counts['metrics_reconciled'],2)
        self.assertEqual(counts['metrics_adjusted'],2)
        self.assertTrue(all(e.startswith('history:') for e in log[:2]))
        state.finish_run.assert_called_once()

if __name__=='__main__': unittest.main()
