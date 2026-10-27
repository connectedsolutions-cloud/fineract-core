"""Historical top-up evidence must survive projection; later cash must not."""
import copy
import unittest

from arissto_sync.loan_source_window import bound_active_loan_histories

ROLES = {'4:00001': 'repayment', '4:00002': 'disbursement',
         '4:00004': 'repayment-reversal', '4:00019': 'refinance-payoff-candidate',
         '14:00011': 'mobile-collection-repayment'}


class HistoricalRefinanceSourceWindowTests(unittest.TestCase):
    def setUp(self):
        self.link = {'old_credit_id': 1, 'new_credit_id': 2, 'same_owner': 1,
                     'payoff_date': '2026-01-01', 'payoff_reversed': None,
                     'predecessor_post_payoff_state': 3, 'predecessor_current_state': '3',
                     'predecessor_current_balance': '0', 'later_posted_payment_count': 0,
                     'payoff_movement_id': 'payoff', 'disbursement_movement_id': 'disbursement',
                     'liquidation_id': 'L1', 'payoff_amount': '42', 'payoff_principal': '40',
                     'payoff_interest': '2', 'payoff_fee': '0', 'payoff_penalty': '0'}
        self.predecessor = {'ID_CREDITO': 1, 'source_state': '3', 'client_source_key': 'A',
                            '_mora_cutover_snapshot': {
                                'ID_CRD_HISTORICO_DIARIO': 501, 'ID_ESTADO_CARTERA': 3,
                                'source_day': '2026-10-19', 'MONTO_DESEMBOLSADO': '40',
                                'SALDO_PAGADO_CAPITAL': '40', 'SALDO_TOTAL': '0',
                                'SALDO_INTERES': '0', 'SALDO_MORA': '0',
                                'SALDO_RECARGOS': '0', 'SALDO_SEGURO': '0'}}
        self.loan = {'ID_CREDITO': 2, 'source_state': '1', 'client_source_key': 'A',
                     '_post_cutover_source_events': {'movements': 1},
                     '_mora_cutover_snapshot': {
                         'ID_CRD_HISTORICO_DIARIO': 502, 'ID_ESTADO_CARTERA': 1,
                         'source_day': '2026-10-19', 'MONTO_DESEMBOLSADO': '100',
                         'SALDO_PAGADO_CAPITAL': '20', 'SALDO_PAGADO_INTERES': '5',
                         'SALDO_INTERES': '2', 'SALDO_SEGURO': '0.20', 'SALDO_TOTAL': '82.20'}}
        self.predecessor_history = {'refinance_outgoing': [self.link], 'movements': [
            self.movement('old-disbursement', '2025-01-01', '00002', '40', '40', '0'),
            self.movement('payoff', '2026-01-01', '00019', '42', '40', '2')]}
        self.history = {'refinance_incoming': [self.link], 'movements': [
            self.movement('disbursement', '2026-01-01', '00002', '100', '100', '0'),
            self.movement('prior', '2026-10-19', '00001', '25', '20', '5'),
            self.movement('later', '2026-10-20', '00001', '12', '10', '2')],
            'charge_details': [{'ID_MOVIMIENTO_CARTERA': 'prior'}, {'ID_MOVIMIENTO_CARTERA': 'later'}]}
        self.loans = [self.predecessor, self.loan]
        self.histories = {1: self.predecessor_history, 2: self.history}

    @staticmethod
    def movement(key, day, code, total, principal, interest):
        return {'ID_MOVIMIENTO_CARTERA': key, 'FECHA_OPERACION': day, 'CODIGO_SISTEMA': 4,
                'ID_TRANSACCION': code, 'REVERSION': None, 'MONTO': total,
                'MONTO_CAPITAL': principal, 'MONTO_INTERES': interest}

    def apply(self):
        bound_active_loan_histories(self.loans, self.histories, '2026-10-20', ROLES)

    def assert_rejected_unchanged(self):
        before = copy.deepcopy((self.loans, self.histories))
        self.apply()
        self.assertEqual((self.loans, self.histories), before)
        self.assertIn('_post_cutover_source_events', self.loan)

    def test_projects_historical_topup_and_keeps_both_sides_of_refinance(self):
        predecessor_before = copy.deepcopy((self.predecessor, self.predecessor_history))
        link_before = copy.deepcopy(self.link)
        self.apply()
        self.assertNotIn('_post_cutover_source_events', self.loan)
        self.assertEqual([m['ID_MOVIMIENTO_CARTERA'] for m in self.history['movements']], ['disbursement', 'prior'])
        self.assertEqual(self.history['charge_details'], [{'ID_MOVIMIENTO_CARTERA': 'prior'}])
        self.assertEqual((self.predecessor, self.predecessor_history), predecessor_before)
        self.assertEqual(self.link, link_before)
        self.assertEqual(self.loan['ULTIMO_SALDO'], 80)
        window = self.loan['_bounded_source_window']
        self.assertEqual(window['policy'], 'active-historical-refinance-before-later-payments-v1')
        self.assertEqual(window['excluded_movement_ids'], ['later'])
        self.assertEqual(window['refinance_evidence']['predecessor_source_key'], '1')
        self.assertEqual(window['refinance_evidence']['predecessor_snapshot_id'], '501')

    def test_projection_is_idempotent_and_input_order_independent(self):
        expected_loans, expected_histories = copy.deepcopy((self.loans, self.histories))
        self.apply()
        before = copy.deepcopy((self.loans, self.histories))
        self.apply()
        self.assertEqual((self.loans, self.histories), before)
        expected_loans.reverse()
        bound_active_loan_histories(expected_loans, expected_histories, '2026-10-20', ROLES)
        self.assertEqual({r['ID_CREDITO']: r for r in expected_loans}, {r['ID_CREDITO']: r for r in self.loans})
        self.assertEqual(expected_histories, self.histories)

    def test_refinance_on_inclusive_source_day_is_preserved(self):
        self.link['payoff_date'] = '2026-10-19'
        self.predecessor_history['movements'][-1]['FECHA_OPERACION'] = '2026-10-19'
        self.history['movements'][0]['FECHA_OPERACION'] = '2026-10-19'
        self.apply()
        self.assertNotIn('_post_cutover_source_events', self.loan)
        self.assertEqual(self.loan['_bounded_source_window']['refinance_evidence']['payoff_date'], '2026-10-19')

    def test_unsupported_links_do_not_partially_mutate_source_evidence(self):
        mutations = [
            lambda: self.link.update(payoff_date='2026-10-20'),
            lambda: self.link.update(payoff_date='invalid'),
            lambda: self.link.update(payoff_reversed=1),
            lambda: self.link.update(same_owner=0),
            lambda: self.link.update(old_credit_id=2),
            lambda: self.link.update(new_credit_id=3),
            lambda: self.link.update(predecessor_post_payoff_state=1),
            lambda: self.link.update(predecessor_current_balance='1'),
            lambda: self.link.update(later_posted_payment_count=1),
            lambda: self.link.update(payoff_amount='41'),
            lambda: self.link.update(payoff_interest='3'),
            lambda: self.link.update(liquidation_id=''),
            lambda: self.history.update(refinance_outgoing=[self.link]),
            lambda: self.history['refinance_incoming'].append(copy.deepcopy(self.link)),
            lambda: self.predecessor_history.update(refinance_outgoing=[]),
            lambda: self.predecessor_history.update(refinance_outgoing=[{**self.link, 'payoff_amount': '99'}]),
            lambda: self.predecessor_history['movements'][-1].update(REVERSION=1),
            lambda: self.predecessor_history['movements'][-1].update(FECHA_OPERACION='2026-10-20'),
            lambda: self.history['movements'][0].update(FECHA_OPERACION='2026-01-02'),
            lambda: self.history['movements'][0].update(MONTO='99'),
            lambda: self.history['movements'].append(copy.deepcopy(self.history['movements'][0])),
            lambda: self.history['movements'][2].update(ID_TRANSACCION='00019'),
            lambda: self.history['movements'][2].update(REVERSION=1),
            lambda: self.history['movements'][2].update(FECHA_OPERACION='bad-date'),
            lambda: self.loan['_post_cutover_source_events'].update(revisions=1),
            lambda: self.loan['_post_cutover_source_events'].update(movements=2),
            lambda: self.loan['_mora_cutover_snapshot'].update(SALDO_PAGADO_CAPITAL='19'),
            lambda: self.loan['_mora_cutover_snapshot'].update(SALDO_PAGADO_INTERES='4'),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i):
                self.setUp()
                mutate()
                self.assert_rejected_unchanged()

    def test_proven_closed_insurance_residue_reuses_existing_terminal_policy(self):
        self.predecessor['SALDO_SEGURO'] = '0.30'
        self.predecessor['_mora_cutover_snapshot']['SALDO_SEGURO'] = '0.30'
        self.apply()
        self.assertNotIn('_post_cutover_source_events', self.loan)
        self.assertEqual(self.loan['_bounded_source_window']['refinance_evidence']['predecessor_insurance_policy'],
                         'closed-stale-source-insurance-residue')
        self.assertEqual(self.predecessor['SALDO_SEGURO'], '0.30')

    def test_unproven_residue_and_positive_collectible_balance_are_rejected(self):
        for field, value in [('SALDO_CXC', '1'), ('SALDO_SEGURO', '0.40')]:
            with self.subTest(field=field):
                self.setUp()
                self.predecessor['SALDO_SEGURO'] = '0.30'
                self.predecessor['_mora_cutover_snapshot']['SALDO_SEGURO'] = '0.30'
                self.predecessor[field] = value
                self.assert_rejected_unchanged()

    def test_missing_or_unclosed_predecessor_evidence_is_rejected(self):
        mutations = [
            lambda: self.loans.remove(self.predecessor),
            lambda: self.histories.pop(1),
            lambda: self.predecessor.update(client_source_key='B'),
            lambda: self.predecessor.update(source_state='1'),
            lambda: self.predecessor.update(SALDO_CXC='1'),
            lambda: self.predecessor.update(ULTIMO_SALDO='1'),
            lambda: self.predecessor.update(_post_cutover_source_events={'movements': 1}),
            lambda: self.predecessor_history.update(schedule_adjustment_summary={'adjustment_count': 1}),
            lambda: self.predecessor_history.update(omit_financial_reconstruction=True),
            lambda: self.predecessor['_mora_cutover_snapshot'].update(ID_ESTADO_CARTERA=1),
            lambda: self.predecessor['_mora_cutover_snapshot'].update(source_day='2026-10-18'),
            lambda: self.predecessor['_mora_cutover_snapshot'].update(SALDO_TOTAL='1'),
            lambda: self.predecessor['_mora_cutover_snapshot'].update(SALDO_INTERES=None),
            lambda: self.predecessor['_mora_cutover_snapshot'].update(SALDO_SEGURO=None),
            lambda: self.predecessor['_mora_cutover_snapshot'].update(SALDO_SEGURO='-1'),
            lambda: self.predecessor['_mora_cutover_snapshot'].update(SALDO_PAGADO_CAPITAL='39'),
            lambda: self.predecessor['_mora_cutover_snapshot'].pop('ID_CRD_HISTORICO_DIARIO'),
            lambda: self.loan['_mora_cutover_snapshot'].pop('ID_CRD_HISTORICO_DIARIO'),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i):
                self.setUp()
                mutate()
                self.assert_rejected_unchanged()


if __name__ == '__main__':
    unittest.main()
