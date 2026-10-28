"""Keep boundary/source drift distinct from a planner inconsistency (LS-25)."""
import copy
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.loan_source_window import bound_active_loan_histories
from arissto_sync.loans import (
    LoanContract, _guard_unmapped_loan_events, _loan_apply_guard,
    _loan_source_hash_view, _stable_hash, apply_loan_plan,
)


class LoanBoundarySourceDriftTests(unittest.TestCase):
    def setUp(self):
        self.contract = LoanContract.load(Path(__file__).resolve().parents[1] / 'config/loans.json')
        self.settings = SimpleNamespace(target=SimpleNamespace(name='local', fingerprint='sandbox'), source=object())
        self.loan = {'ID_CREDITO': 921, 'line_id': '00010', 'source_state': '1',
                     '_mora_cutover_snapshot': {'ID_ESTADO_CARTERA': 1, 'source_day': '2026-10-26',
                         'MONTO_DESEMBOLSADO': '100', 'SALDO_PAGADO_CAPITAL': '20',
                         'SALDO_PAGADO_INTERES': '5'}}
        self.history = {'movements': [self.movement('prior', '2026-10-26')],
                        'refinance_incoming': [{'old_credit_id': 553, 'new_credit_id': 921}],
                        'charge_details': []}
        self.lifecycle = {'interest_recalculation_policy': 'source-exact-off-v1', 'refinance': {'historical_replay_policy': 'source-exact-off-v1', 'settlement_classifier': 'historical-post-payoff-state-v2'},
                          'events': [{'external_id': 'prior', 'date': '2026-10-26', 'role': 'repayment'}],
                          'migration_cutover_date': '2026-10-27', 'expected': {'source_state': '1'},
                          'final_metric_alignment': {'revision': 1}}
        guarded = _guard_unmapped_loan_events(
            {'lifecycle': copy.deepcopy(self.lifecycle), 'quarantine_reasons': []}, self.loan)
        action = {'entity_type': 'loan', 'entity_source_key': '921', 'source_key': 'loan:921',
                  'external_id': 'ARISSTO:CRD:921', 'action': 'create-loan', **guarded}
        action['source_hash'] = _stable_hash({'header': self.loan,
                                             'lifecycle': _loan_source_hash_view(action['lifecycle'])})
        self.state = MagicMock()
        self.plan = {'block': 'loans', 'target_fingerprint': 'sandbox', 'source_fingerprint': 'source',
                     'contract_hash': self.contract.digest, 'document': {
                         'component_alignment_plan_revision': 10, 'historical_replay_policy': 'source-exact-off-v1', 'final_metric_alignment_revision': 2,
                         'accrual_control_revision': 1, 'source_observed_at': '2026-10-27T17:33:57Z',
                         'applicable': True, 'product_writer_registered': True, 'loan_writer_registered': True,
                         'collateral_writer_registered': True, 'schema_signature': 's',
                         'target_schema_signature': 't', 'migration_cutover_date': '2026-10-27',
                         'scope': {'mode': 'explicit-source-keys', 'requested_source_keys': ['921']},
                         'actions': [action], 'client_office_transfers': []}}
        self.state.plan.side_effect = lambda _: copy.deepcopy(self.plan)

    @staticmethod
    def movement(key, day):
        return {'ID_MOVIMIENTO_CARTERA': key, 'FECHA_OPERACION': day, 'CODIGO_SISTEMA': 4,
                'ID_TRANSACCION': '00001', 'REVERSION': None, 'MONTO_CAPITAL': '20', 'MONTO_INTERES': '5'}

    def read_only_context(self, stack):
        # Freeze I/O and financial construction; exercise real source-window,
        # quarantine, hash comparison and apply-entry ordering with one snapshot.
        inspection = {'source_blockers': [], 'target_blockers': [],
                      'schema_signature': 's', 'target_schema_signature': 't'}
        values = {'source_fingerprint': 'source', '_plan_scope_inspections': [inspection],
                  'extract_loan_plan_rows': ([self.loan], [{'line_id': '00010'}]),
                  'extract_loan_lifecycle_rows': {921: self.history},
                  'attach_loan_cutover_source_evidence': None,
                  'resolve_loan_product_target': {'resources': {}},
                  'build_loan_product_payload': {},
                  '_collateral_runtime_contract': ([], [], [])}
        for name, value in values.items():
            stack.enter_context(patch('arissto_sync.loans.' + name, return_value=value))
        stack.enter_context(patch('arissto_sync.loans._build_loan_lifecycle_action',
                                  side_effect=lambda *a: {'lifecycle': copy.deepcopy(self.lifecycle),
                                                        'quarantine_reasons': []}))

    def test_unchanged_historical_refinance_passes_read_only_validation(self):
        with ExitStack() as stack:
            self.read_only_context(stack)
            plan, _ = _loan_apply_guard(self.settings, self.state, self.contract, 'plan', None)
        self.assertEqual(plan['document']['actions'][0]['source_hash'],
                         self.plan['document']['actions'][0]['source_hash'])
        self.state.start_run.assert_not_called()

    def test_new_boundary_day_payment_is_rejected_before_any_write(self):
        before = copy.deepcopy(self.plan)
        self.loan['_post_cutover_source_events'] = {'movements': 1}
        self.history['movements'].append(self.movement('later', '2026-10-27'))
        self.lifecycle['events'].append({'external_id': 'later', 'date': '2026-10-27', 'role': 'repayment'})
        with ExitStack() as stack:
            self.read_only_context(stack)
            api = stack.enter_context(patch('arissto_sync.loans.FineractApi'))
            fallback = stack.enter_context(patch('arissto_sync.loans._post_boundary_only_loan_drift', return_value=True))
            with self.assertRaisesRegex(RuntimeError, 'loan:921:source_events_after_fineract_accounting_boundary'):
                apply_loan_plan(self.settings, self.state, self.contract, 'plan')
            api.assert_not_called()
            fallback.assert_not_called()  # Hash fallback never overrides a new eligibility failure.
        self.state.start_run.assert_not_called()
        self.state.record_item.assert_not_called()
        self.assertEqual(self.plan, before)
        self.assertEqual(len(self.history['movements']), 2)

    def test_pre_boundary_edit_is_not_hidden_as_future_drift(self):
        self.lifecycle['events'][0]['amount'] = 'changed'
        with ExitStack() as stack:
            self.read_only_context(stack)
            api = stack.enter_context(patch('arissto_sync.loans.FineractApi'))
            with self.assertRaisesRegex(RuntimeError, 'Loan source changed after planning: loan:921'):
                apply_loan_plan(self.settings, self.state, self.contract, 'plan')
            api.assert_not_called()
        self.state.start_run.assert_not_called()

    def test_temporal_projection_requires_no_refinance_relationships(self):
        for relation in (None, 'refinance_incoming', 'refinance_outgoing'):
            with self.subTest(relation=relation):
                loan = copy.deepcopy(self.loan)
                loan['_post_cutover_source_events'] = {'movements': 1}
                history = copy.deepcopy(self.history)
                history.pop('refinance_incoming')
                if relation:
                    history[relation] = [{'old_credit_id': 553, 'new_credit_id': 921}]
                history['movements'].append(self.movement('later', '2026-10-27'))
                before = copy.deepcopy((loan, history))
                bound_active_loan_histories([loan], {921: history}, '2026-10-27',
                                            self.contract.raw['supported_transactions'])
                if relation:
                    self.assertEqual((loan, history), before)
                else:
                    self.assertNotIn('_post_cutover_source_events', loan)
                    self.assertEqual(loan['_bounded_source_window']['excluded_movement_ids'], ['later'])
                    self.assertEqual(len(history['movements']), 1)


if __name__ == '__main__':
    unittest.main()
