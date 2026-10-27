"""LS-27: retry closure includes atomic successor payoffs, not generic siblings."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.loans import LoanApplyControls, _selected_loan_actions, apply_loan_plan


class LoanRetryPayoffScopeTests(unittest.TestCase):
    @staticmethod
    def payoff(successor):
        return {'role': 'native-refinance-payoff', 'successor_source_key': str(successor)}

    def actions(self):
        def loan(number, client, dependencies, successor=None):
            return {'source_key': f'loan:{number}', 'entity_type': 'loan', 'client_external_id': client,
                    'depends_on': dependencies, 'lifecycle': {'events': [] if successor is None else [self.payoff(successor)]}}
        return [
            {'source_key': 'collateral-product:arissto', 'entity_type': 'collateral-product', 'depends_on': []},
            {'source_key': 'product:00010', 'entity_type': 'product', 'depends_on': []},
            {'source_key': 'product:00001', 'entity_type': 'product', 'depends_on': []},
            loan(1, 'A', ['product:00010'], 2),
            loan(2, 'A', ['product:00010', 'loan:1'], 3),
            loan(4, 'B', ['product:00001', 'collateral-product:arissto'], 3),
            loan(3, 'B', ['product:00010', 'loan:2', 'loan:4'], 5),
            loan(5, 'C', ['product:00010', 'loan:3']),
            loan(6, 'C', ['product:00010'], 7),
            loan(7, 'D', ['product:00010', 'loan:6']),
            loan(8, 'unrelated', ['product:00010']),
            loan(9, 'unrelated', ['product:00001', 'collateral-product:arissto']),
        ]

    def select(self, actions=None, roots=None, events=None):
        return _selected_loan_actions(self.actions() if actions is None else actions,
                                      {'loan:2'} if roots is None else roots,
                                      client_office_transfers=events)

    @staticmethod
    def keys(actions):
        return {a['source_key'] for a in actions}

    def test_successor_closure_adds_later_descendants_and_consolidation_predecessors(self):
        selected = self.select()
        self.assertEqual(self.keys(selected), {f'loan:{n}' for n in range(1, 6)} |
                         {'product:00010', 'product:00001', 'collateral-product:arissto'})

    def test_successor_and_transfer_closure_reach_one_joint_fixed_point(self):
        selected = self.select(events=[{'client_external_id': 'C'}])
        self.assertEqual(self.keys(selected), {f'loan:{n}' for n in range(1, 8)} |
                         {'product:00010', 'product:00001', 'collateral-product:arissto'})
        self.assertNotIn('loan:8', self.keys(selected))
        self.assertNotIn('loan:9', self.keys(selected))

    def test_generic_reverse_dependencies_and_non_payoff_annotations_do_not_expand_scope(self):
        actions = self.actions()
        next(a for a in actions if a['source_key'] == 'loan:8')['depends_on'].append('loan:1')
        next(a for a in actions if a['source_key'] == 'loan:5')['lifecycle']['events'] = [
            {'role': 'repayment', 'successor_source_key': '8'}]
        self.assertNotIn('loan:8', self.keys(self.select(actions)))

    def test_explicit_failed_product_still_fans_out_but_discovered_product_does_not(self):
        selected = self.select(roots={'product:00010'}, events=[{'client_external_id': 'C'}])
        self.assertIn('loan:8', self.keys(selected))
        self.assertNotIn('loan:9', self.keys(selected))
        self.assertIn('product:00001', self.keys(selected))

    def test_missing_invalid_or_nonloan_successor_is_rejected(self):
        for kind in ('absent', 'missing-id', 'invalid-id', 'not-a-loan', 'missing-backlink'):
            with self.subTest(kind=kind):
                actions = self.actions()
                parent = next(a for a in actions if a['source_key'] == 'loan:2')
                successor = next(a for a in actions if a['source_key'] == 'loan:3')
                if kind == 'absent':
                    parent['lifecycle']['events'] = [self.payoff(50)]
                elif kind == 'missing-id':
                    parent['lifecycle']['events'] = [{'role': 'native-refinance-payoff'}]
                elif kind == 'invalid-id':
                    parent['lifecycle']['events'] = [self.payoff('product:00010')]
                elif kind == 'not-a-loan':
                    successor['entity_type'] = 'product'
                else:
                    successor['depends_on'].remove('loan:2')
                with self.assertRaisesRegex(RuntimeError, 'native_refinance_payoff_'):
                    self.select(actions)

    def test_missing_payoff_action_fails_in_apply_before_api_or_run_creation(self):
        actions = self.actions()
        next(a for a in actions if a['source_key'] == 'loan:2')['lifecycle']['events'] = [self.payoff(50)]
        state = MagicMock()
        plan = {'document': {'actions': actions, 'client_office_transfers': []}}
        with (patch('arissto_sync.loans._loan_apply_guard', return_value=(plan, {})),
              patch('arissto_sync.loans.FineractApi', side_effect=RuntimeError('must-not-reach-api')) as api):
            with self.assertRaisesRegex(RuntimeError, 'native_refinance_payoff_'):
                apply_loan_plan(SimpleNamespace(target=object()), state, MagicMock(), 'plan',
                                only_keys={'loan:2'}, controls=LoanApplyControls(workers=1, pause_seconds=0, recovery_attempts=1))
            api.assert_not_called()
        state.start_run.assert_not_called()
        state.record_item.assert_not_called()

    def test_new_successor_with_a_missing_required_predecessor_is_rejected(self):
        actions = self.actions()
        next(a for a in actions if a['source_key'] == 'loan:3')['depends_on'].append('loan:40')
        with self.assertRaisesRegex(RuntimeError, 'loan_retry_dependency_action_missing:loan:3:loan:40'):
            self.select(actions)

    def test_selection_preserves_inputs_order_and_objects(self):
        actions = self.actions()
        roots = {'loan:2'}
        events = [{'client_external_id': 'C'}]
        before = copy.deepcopy((actions, roots, events))
        selected = self.select(actions, roots, events)
        self.assertEqual((actions, roots, events), before)
        self.assertEqual(selected, [a for a in actions if a['source_key'] in self.keys(selected)])
        self.assertTrue(all(any(a is original for original in actions) for a in selected))
        self.assertEqual(self.keys(self.select(actions, self.keys(selected) & {f'loan:{n}' for n in range(1, 8)}, events)),
                         self.keys(selected))

    def test_only_selected_components_are_validated_and_empty_scope_is_empty(self):
        actions = self.actions()
        next(a for a in actions if a['source_key'] == 'loan:8')['lifecycle']['events'] = [self.payoff(99)]
        self.assertNotIn('loan:8', self.keys(self.select(actions)))
        self.assertEqual(self.select(actions, set()), [])
        self.assertIs(_selected_loan_actions(actions, None), actions)


if __name__ == '__main__':
    unittest.main()
