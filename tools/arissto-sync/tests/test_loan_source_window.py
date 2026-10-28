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
