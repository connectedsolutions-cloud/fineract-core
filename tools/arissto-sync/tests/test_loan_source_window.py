import copy
import unittest
from decimal import Decimal
from arissto_sync.loan_source_window import bound_active_loan_histories

ROLES = {'4:00001': 'repayment', '4:00002': 'disbursement', '4:00004': 'repayment-reversal',
         '4:00019': 'refinance-payoff-candidate', '14:00011': 'mobile-collection-repayment'}

class LoanSourceWindowTests(unittest.TestCase):
    def setUp(self):
        self.loan = {'ID_CREDITO': 1, 'source_state': '1', '_post_cutover_source_events': {'movements': 1},
                     '_mora_cutover_snapshot': {'ID_ESTADO_CARTERA': 1, 'source_day': '2026-10-19',
                       'MONTO_DESEMBOLSADO': '100', 'SALDO_PAGADO_CAPITAL': '20', 'SALDO_PAGADO_INTERES': '5',
                       'SALDO_INTERES': '2', 'SALDO_SEGURO': '0.20', 'SALDO_TOTAL': '82.20'}}
        self.history = {'movements': [self.movement('a', '2026-10-19', '20', '5'),
                                    self.movement('b', '2026-10-20', '10', '2')],
                        'charge_details': [{'ID_MOVIMIENTO_CARTERA': 'a'}, {'ID_MOVIMIENTO_CARTERA': 'b'}]}
    @staticmethod
    def movement(key, day, principal, interest):
        return {'ID_MOVIMIENTO_CARTERA': key, 'FECHA_OPERACION': day, 'CODIGO_SISTEMA': 4,
                'ID_TRANSACCION': '00001', 'REVERSION': None, 'MONTO_CAPITAL': principal, 'MONTO_INTERES': interest}
    def apply(self):
        bound_active_loan_histories([self.loan], {1: self.history}, '2026-10-20', ROLES)
    def test_inclusive_source_day_and_exclusive_native_boundary(self):
        self.apply()
        self.assertEqual([r['ID_MOVIMIENTO_CARTERA'] for r in self.history['movements']], ['a'])
        self.assertEqual(self.history['charge_details'], [{'ID_MOVIMIENTO_CARTERA': 'a'}])
        self.assertEqual(self.loan['ULTIMO_SALDO'], Decimal('80'))
        self.assertEqual(self.loan['SALDO_INTERES'], '2')
        self.assertNotIn('_post_cutover_source_events', self.loan)
        self.assertEqual(self.loan['_bounded_source_window']['excluded_movement_ids'], ['b'])
    def test_preserves_guard_for_unsupported_temporal_histories(self):
        mutations = [lambda: self.loan.update(source_state='3'),
                     lambda: self.loan['_mora_cutover_snapshot'].update(ID_ESTADO_CARTERA=3),
                     lambda: self.loan['_mora_cutover_snapshot'].update(source_day='2026-10-18'),
                     lambda: self.loan['_mora_cutover_snapshot'].update(SALDO_PAGADO_CAPITAL='19'),
                     lambda: self.loan['_mora_cutover_snapshot'].update(SALDO_PAGADO_INTERES=None),
                     lambda: self.history['movements'][1].update(ID_TRANSACCION='00004'),
                     lambda: self.history['movements'][0].update(REVERSION=1),
                     lambda: self.history.update(refinance_incoming=[{}]),
                     lambda: self.history.update(schedule_adjustment_summary={'adjustment_count': 1}),
                     lambda: self.loan['_post_cutover_source_events'].update(revisions=1),
                     lambda: self.loan['_post_cutover_source_events'].update(movements=2)]
        for mutate in mutations:
            self.setUp();mutate();before=copy.deepcopy(self.history)
            self.apply()
            self.assertIn('_post_cutover_source_events', self.loan)
            self.assertEqual(self.history, before)
    def test_future_mobile_payment_is_outside_snapshot(self):
        self.history['movements'][1].update(CODIGO_SISTEMA=14, ID_TRANSACCION='00011')
        self.apply()
        self.assertNotIn('_post_cutover_source_events', self.loan)
    def test_no_later_events_does_not_change_existing_plan(self):
        del self.loan['_post_cutover_source_events'];before=copy.deepcopy((self.loan,self.history))
        self.apply();self.assertEqual((self.loan,self.history),before)

    def test_proven_past_adjustments_do_not_exclude_later_ordinary_cash(self):
        adjustment={'ID_REESTRUCTURACION':9,'DT_CREO':'2026-09-01','FECHA_REESTRUCTURACION':'2026-09-01'}
        self.history['schedule_adjustment_summary']={'adjustment_count':1,'adjustments':[adjustment]}
        before=copy.deepcopy(self.history['schedule_adjustment_summary'])
        self.apply()
        self.assertNotIn('_post_cutover_source_events',self.loan)
        self.assertEqual(self.history['schedule_adjustment_summary'],before)
        self.assertEqual([r['ID_MOVIMIENTO_CARTERA'] for r in self.history['movements']],['a'])

    def test_later_or_unproved_adjustments_still_stop_projection(self):
        for change in [{'DT_CREO':'2026-10-20'},{'FECHA_REESTRUCTURACION':'2026-10-20'},
                       {'DT_CREO':None},{'DT_CREO':'invalid'}]:
            self.setUp()
            row={'ID_REESTRUCTURACION':9,'DT_CREO':'2026-09-01','FECHA_REESTRUCTURACION':'2026-09-01',**change}
            self.history['schedule_adjustment_summary']={'adjustment_count':1,'adjustments':[row]}
            before=copy.deepcopy((self.loan,self.history));self.apply()
            self.assertEqual((self.loan,self.history),before)

    def test_paired_past_reversal_is_preserved_but_not_counted_as_paid_cash(self):
        original=self.movement('reversed','2026-10-17','7','1')
        original.update(ID_CREDITO=1,REVERSION=1)
        reversal={**original,'ID_MOVIMIENTO_CARTERA':'reversal','FECHA_OPERACION':'2026-10-18',
                  'ID_TRANSACCION':'00004','REVERSION':None}
        for row in self.history['movements']:row['ID_CREDITO']=1
        self.history['movements'][:0]=[original,reversal]
        self.apply()
        self.assertNotIn('_post_cutover_source_events',self.loan)
        self.assertEqual([r['ID_MOVIMIENTO_CARTERA'] for r in self.history['movements']],
                         ['reversed','reversal','a'])
        self.assertEqual(self.history['movements'][0]['REVERSION'],1)

    def test_mismatched_past_reversal_does_not_remove_boundary_guard(self):
        original=self.movement('reversed','2026-10-17','7','1')
        original.update(ID_CREDITO=1,REVERSION=1)
        reversal={**original,'ID_MOVIMIENTO_CARTERA':'reversal','FECHA_OPERACION':'2026-10-18',
                  'ID_TRANSACCION':'00004','REVERSION':None,'MONTO_CAPITAL':'6'}
        for row in self.history['movements']:row['ID_CREDITO']=1
        self.history['movements'][:0]=[original,reversal]
        before=copy.deepcopy((self.loan,self.history));self.apply()
        self.assertEqual((self.loan,self.history),before)

    def test_later_adjusted_payment_is_excluded_from_source_day(self):
        self.history['movements'][1]['ID_TRANSACCION']='00013'
        roles={**ROLES,'4:00013':'adjusted-repayment'}
        bound_active_loan_histories([self.loan],{1:self.history},'2026-10-20',roles)
        self.assertNotIn('_post_cutover_source_events',self.loan)
        self.assertEqual(len(self.history['movements']),1)

    def test_future_reversal_restores_original_as_of_source_day(self):
        original=self.history['movements'][0]
        original.update(ID_CREDITO=1,REVERSION=1)
        reversal={**original,'ID_MOVIMIENTO_CARTERA':'reverse-later',
                  'FECHA_OPERACION':'2026-10-20','ID_TRANSACCION':'00004','REVERSION':None}
        self.history['movements'].append(reversal)
        self.history['movements'][1]['ID_CREDITO']=1
        self.loan['_post_cutover_source_events']['movements']=2
        self.apply()
        self.assertNotIn('_post_cutover_source_events',self.loan)
        self.assertEqual(self.history['movements'][0]['REVERSION'],0)
        self.assertEqual(self.loan['_bounded_source_window']['reversals_effective_after_source_day'],['a'])

    def test_future_reversal_pair_is_excluded_as_a_whole(self):
        original=self.history['movements'][1]
        original.update(ID_CREDITO=1,REVERSION=1)
        self.history['movements'][0]['ID_CREDITO']=1
        reversal={**original,'ID_MOVIMIENTO_CARTERA':'reverse-later',
                  'FECHA_OPERACION':'2026-10-21','ID_TRANSACCION':'00004','REVERSION':None}
        self.history['movements'].append(reversal)
        self.loan['_post_cutover_source_events']['movements']=2
        self.apply()
        self.assertNotIn('_post_cutover_source_events',self.loan)
        self.assertEqual([r['ID_MOVIMIENTO_CARTERA'] for r in self.history['movements']],['a'])

    def with_later_revision(self):
        from arissto_sync.loan_source_window import _ARCHIVED_CONTRACT_FIELDS
        snapshot=self.loan['_mora_cutover_snapshot']
        snapshot.update({field:None for field in _ARCHIVED_CONTRACT_FIELDS})
        snapshot.update(ID_CRD_HISTORICO_DIARIO=77,FECHA_VENCIMIENTO='2027-01-01')
        self.loan['FECHA_VENCIMIENTO']='2028-01-01'
        self.loan['_post_cutover_source_events']['revisions']=1
        row={field:snapshot[field] for field in _ARCHIVED_CONTRACT_FIELDS}
        row.update(ID_REESTRUCTURACION=9,DT_CREO='2026-10-20')
        self.history['schedule']=[{'NO_CUOTA':1,'MONTO_CAPITAL':'999','FECHA_PAGO':'2028-01-01'}]
        self.history['schedule_adjustment_summary']={
            'adjustment_count':1,'adjustments':[row],'archived_schedules':{'9':[
                {'ID_REESTRUCTURACION':9,'NO_CUOTA':1,'MONTO_CAPITAL':'100','FECHA_PAGO':'2027-01-01'}]}}

    def test_first_later_archive_restores_dated_terms_and_schedule(self):
        self.with_later_revision();self.apply()
        self.assertNotIn('_post_cutover_source_events',self.loan)
        self.assertEqual(self.loan['FECHA_VENCIMIENTO'],'2027-01-01')
        self.assertEqual(self.history['schedule'][0]['MONTO_CAPITAL'],'100')
        self.assertIsNone(self.history['schedule'][0]['ID_REESTRUCTURACION'])
        self.assertEqual(self.history['schedule_adjustment_summary']['adjustment_count'],0)
        self.assertEqual(self.loan['_bounded_source_window']['schedule_evidence']['archive_adjustment_id'],'9')

    def test_revision_without_later_cash_can_restore_source_schedule(self):
        self.with_later_revision();self.history['movements'].pop()
        del self.loan['_post_cutover_source_events']['movements']
        self.apply()
        self.assertNotIn('_post_cutover_source_events',self.loan)
        self.assertEqual(self.loan['_bounded_source_window']['excluded_movement_count'],0)

    def test_archive_proof_or_cash_failure_leaves_all_input_unchanged(self):
        mutations=[lambda:self.loan['_mora_cutover_snapshot'].update(FLAT='different'),
                   lambda:self.history['schedule_adjustment_summary']['archived_schedules'].clear(),
                   lambda:self.loan['_mora_cutover_snapshot'].update(SALDO_PAGADO_CAPITAL='19'),
                   lambda:self.loan['_post_cutover_source_events'].update(revisions=2)]
        for mutate in mutations:
            self.setUp();self.with_later_revision();mutate()
            before=copy.deepcopy((self.loan,self.history));self.apply()
            self.assertEqual((self.loan,self.history),before)

    def test_only_fully_repaid_zero_debt_can_retain_historical_mora_balance_variance(self):
        from arissto_sync.loans import _repaid_schedule_balance_reference
        loan={'source_state':'3','ULTIMO_SALDO':0,'SALDO_TOTAL':0,'SALDO_MORA':0,
              '_mora_cutover_snapshot':{'ID_ESTADO_CARTERA':3,'ID_CRD_HISTORICO_DIARIO':7,
               'source_day':'2026-10-19','MONTO_DESEMBOLSADO':100,'SALDO_PAGADO_CAPITAL':100,
               'SALDO_TOTAL':0,'SALDO_INTERES':0,'SALDO_MORA':0,'SALDO_RECARGOS':0}}
        self.assertIsNotNone(_repaid_schedule_balance_reference(loan,'2026-10-20'))
        for change in [{'source_state':'1'},{'ULTIMO_SALDO':1},
                       {'_post_cutover_source_events':{'movements':1}}]:
            self.assertIsNone(_repaid_schedule_balance_reference({**loan,**change},'2026-10-20'))
        for change in [{'ID_ESTADO_CARTERA':1},{'SALDO_PAGADO_CAPITAL':99},
                       {'SALDO_INTERES':1},{'SALDO_MORA':None},{'source_day':'2026-10-18'}]:
            mutated={**loan,'_mora_cutover_snapshot':{**loan['_mora_cutover_snapshot'],**change}}
            self.assertIsNone(_repaid_schedule_balance_reference(mutated,'2026-10-20'))

    def test_later_refinance_does_not_connect_source_day_to_future_loan(self):
        self.loan['source_state']='3'
        payoff=self.history['movements'][1]
        payoff['ID_TRANSACCION']='00019'
        link={'old_credit_id':1,'new_credit_id':2,'payoff_date':'2026-10-20',
              'payoff_movement_id':'b','disbursement_movement_id':'new-disbursement'}
        self.history['refinance_outgoing']=[link]
        successor={'movements':[{'ID_MOVIMIENTO_CARTERA':'new-disbursement','FECHA_OPERACION':'2026-10-20',
                                'CODIGO_SISTEMA':4,'ID_TRANSACCION':'00002'}], 'refinance_incoming':[link]}
        bound_active_loan_histories([self.loan],{1:self.history,2:successor},'2026-10-20',ROLES)
        self.assertNotIn('_post_cutover_source_events',self.loan)
        self.assertEqual(self.loan['source_state'],'1')
        self.assertEqual(self.history['refinance_outgoing'],[])
        self.assertEqual(successor['refinance_incoming'],[])
        self.assertEqual(self.history['after_boundary_refinance_links'],[link])
        self.assertEqual([r['ID_MOVIMIENTO_CARTERA'] for r in self.history['movements']],['a'])
