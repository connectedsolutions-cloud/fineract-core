"""Historical off migration: native flag, complete replay, correction barrier and retry."""
import copy
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.loans import (
    HISTORICAL_REPLAY_POLICY, LoanApplyControls, _validate_existing_loan,
    _verify_complete_historical_replay, _prepare_refinance_predecessor, apply_loan_plan,
)
from arissto_sync.state import State
import tests.test_loans as fixtures


class HistoricalOffTests(unittest.TestCase):
    def test_missing_or_enabled_native_loan_flag_fails_closed(self):
        action = {'lifecycle': {'interest_recalculation_policy': HISTORICAL_REPLAY_POLICY,
                               'application_payload': {'clientId': 2, 'principal': '100'}}}
        loan = {'id': 1, 'loanProductId': 3, 'clientId': 2, 'principal': '100'}
        for flag in (None, True):
            with self.subTest(flag=flag), self.assertRaisesRegex(RuntimeError, 'interest_recalculation'):
                _validate_existing_loan({**loan, 'isInterestRecalculationEnabled': flag}, action, 3)
        _validate_existing_loan({**loan, 'isInterestRecalculationEnabled': False}, action, 3)

    def test_off_refinance_prepares_source_charges_without_quote_or_credit(self):
        predecessor = {'id': 1}
        settlement = {'historical_replay_policy': HISTORICAL_REPLAY_POLICY}
        api = MagicMock()
        with patch('arissto_sync.loans._ensure_refinance_settlement_charges', return_value=predecessor) as charges, \
             patch('arissto_sync.loans._ensure_refinance_prepayment_ready') as bridge:
            self.assertEqual(_prepare_refinance_predecessor(api, predecessor, settlement, 'run', full_close=True), predecessor)
        charges.assert_called_once()
        bridge.assert_not_called()
        api.request.assert_not_called()

    def action(self, key):
        return {'source_key': f'loan:{key}', 'entity_source_key': str(key), 'entity_type': 'loan',
                'external_id': f'ARISSTO:CRD:{key}', 'action': 'create-loan', 'depends_on': ['product:1'],
                'source_hash': f'h{key}', 'product_action_key': 'product:1', 'target_id': None,
                'lifecycle': {'interest_recalculation_policy': HISTORICAL_REPLAY_POLICY,
                              'migration_cutover_date': '2026-10-27', 'events': []}}

    def coordinator(self, failed=None, prior_missing=False, native_invalid=None, retry_subset=False):
        fixture = fixtures.LoanInspectionTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        product = {'source_key': 'product:1', 'entity_type': 'product', 'entity_source_key': '1',
                   'source_company_id': '001', 'action': 'create-product', 'depends_on': [], 'source_hash': 'p',
                   'external_id': 'ARISSTO:CRD-LINE:1', 'payload': {},
                   'crosswalk': {'repair_after_product_resolution': True}, 'target_id': None}
        loans = [self.action(1), self.action(2)]
        if prior_missing:
            loans[0]['action'] = 'unchanged-loan';loans[0]['target_id'] = 1
        plan = {'id': 'p', 'document': {'actions': [product, *loans],
                 'final_metric_alignment_revision': 1, 'source_observed_at': '2026-10-27T15:00:00Z'}}
        state = MagicMock(); state.start_run.return_value = 'run'
        outcomes = {}
        state.record_item.side_effect = lambda run, key, action, digest, status, *rest: outcomes.update({key: {
            'source_key': key, 'status': status, 'target_id': str(key.rsplit(':', 1)[1])}})
        state.run_items.side_effect = lambda _: list(outcomes.values())
        state.latest_plan_run_items.return_value = []
        log = []
        def history(api, action, product, run):
            log.append('history:' + action['source_key'])
            if action['source_key'] == failed:
                raise RuntimeError('complete_chain_replay_failed')
            return int(action['entity_source_key']), False
        def native_check(api, action):
            log.append('check:' + action['source_key'])
            if action['source_key'] == native_invalid:
                raise RuntimeError('native_history_drift')
        with ExitStack() as stack:
            values = {'_loan_apply_guard': (plan, {'products': {'1': None}, 'crosswalks': {}}),
                      '_resolve_or_create_loan_product': (91, False)}
            for name, value in values.items():
                stack.enter_context(patch('arissto_sync.loans.' + name, return_value=value))
            for name in ('FineractApi', '_upsert_loan_product_crosswalk'):
                stack.enter_context(patch('arissto_sync.loans.' + name))
            stack.enter_context(patch('arissto_sync.loans._apply_loan_lifecycle', side_effect=history))
            stack.enter_context(patch('arissto_sync.loans._verify_complete_historical_replay', side_effect=native_check))
            stack.enter_context(patch('arissto_sync.loans._find_loan', side_effect=lambda api, external: {
                'id': int(external.rsplit(':', 1)[1]), 'isInterestRecalculationEnabled': False}))
            final = stack.enter_context(patch('arissto_sync.loans._finalize_loan_history', side_effect=lambda api, loan, action, run: log.append('final:' + action['source_key'])))
            metrics = stack.enter_context(patch('arissto_sync.loan_metric_alignment.align', return_value={'changed': True}))
            result = apply_loan_plan(SimpleNamespace(target=SimpleNamespace(fingerprint='target')),
                                    state, fixture.contract, 'p', only_keys={'loan:2'} if retry_subset else None, controls=LoanApplyControls(workers=1, pause_seconds=0, recovery_attempts=1))
        return result[1], final.call_count, metrics.call_count, log, state

    def test_one_failed_history_prevents_every_final_correction(self):
        counts, final, metrics, _, state = self.coordinator(failed='loan:2')
        self.assertEqual((final, metrics), (0, 0))
        self.assertEqual(counts['final_corrections_deferred'], 2)
        self.assertEqual(state.finish_run.call_args.args[1], 'completed-with-errors')

    def test_complete_native_read_pass_precedes_any_final_write(self):
        counts, final, metrics, log, _ = self.coordinator()
        self.assertEqual((final, metrics), (2, 2))
        self.assertEqual(counts['metrics_reconciled'], 2)
        self.assertLess(log.index('history:loan:2'), log.index('check:loan:1'))
        self.assertLess(log.index('check:loan:2'), log.index('final:loan:1'))

    def test_native_history_drift_prevents_corrections_to_healthy_loan(self):
        counts, final, metrics, _, _ = self.coordinator(native_invalid='loan:2')
        self.assertEqual((final, metrics), (0, 0))
        self.assertEqual(counts['final_corrections_deferred'], 2)

    def test_missing_history_in_frozen_plan_prevents_retry_subset_finalization(self):
        counts, final, metrics, log, state = self.coordinator(retry_subset=True)
        self.assertEqual((final, metrics), (0, 0))
        self.assertEqual(counts['final_corrections_deferred'], 2)
        self.assertEqual(log, ['history:loan:2'])
        self.assertEqual(state.finish_run.call_args.args[1], 'completed-with-errors')

    def test_replay_readback_rejects_allocation_drift_and_post_boundary_event(self):
        action = self.action(1)
        event = {'external_id': 'p1', 'role': 'repayment', 'date': '2026-10-26', 'amount': '10',
                 'allocation': {'principal': '8', 'interest': '2', 'fee': '0', 'penalty': '0'}}
        action['lifecycle']['events'] = [event]
        native = {'id': 1, 'isInterestRecalculationEnabled': False, 'transactions': [{
            'externalId': 'p1', 'date': [2026, 10, 26], 'amount': '10',
            'principalPortion': '8', 'interestPortion': '2', 'feeChargesPortion': '0', 'penaltyChargesPortion': '0'}]}
        with patch('arissto_sync.loans._find_loan', return_value=native):
            _verify_complete_historical_replay(MagicMock(), action)
            native['transactions'][0]['principalPortion'] = '7'
            with self.assertRaisesRegex(RuntimeError, 'allocation_mismatch'):
                _verify_complete_historical_replay(MagicMock(), action)
            event['date'] = '2026-10-27'
            with self.assertRaisesRegex(RuntimeError, 'outside_source_window'):
                _verify_complete_historical_replay(MagicMock(), action)
