"""A later correction failure must override an earlier historical replay success."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from arissto_sync.state import State
from arissto_sync.service_runtime import ServiceRuntime


class FinalCorrectionRetryTests(unittest.TestCase):
    def test_correction_failure_remains_a_retry_root_after_a_blocked_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            state = State(Path(temp) / 'state.sqlite3')
            try:
                actions = [{'source_key': f'loan:{key}', 'entity_type': 'loan', 'depends_on': ['loan:1'] if key == 2 else []} for key in (1, 2)]
                plan_id = state.save_plan('target', 'loans', 'source', 'contract', {'actions': actions})
                plan = state.plan(plan_id)
                history = state.start_run(plan)
                for key in (1, 2): state.record_item(history, f'loan:{key}', 'recover-loan', 'hash', 'recovered', str(key))
                correction = state.start_run(plan)
                state.record_item(correction, 'loan:1', 'recover-loan', 'hash', 'failed', '1', 'final_metrics:closure_failed')
                blocked = state.start_run(plan)
                state.record_item(blocked, 'loan:1', 'recover-loan', 'hash', 'blocked', '1', 'dependency_failed')
                runtime = object.__new__(ServiceRuntime)
                runtime.settings = SimpleNamespace(); runtime.state = state
                runtime.contracts = {'loans': object()}; runtime.loan_controls = None
                with patch('arissto_sync.service_runtime.apply_loan_plan', return_value=('new-run', {})) as apply:
                    runtime.retry('loans', blocked)
                self.assertEqual(apply.call_count, 1)
                self.assertEqual(apply.call_args.args[5], {'loan:1'})
                state.record_item(blocked, 'loan:2', 'recover-loan', 'hash', 'blocked', '2', 'dependency_failed')
                with patch('arissto_sync.service_runtime.apply_loan_plan', return_value=('new-run', {})) as apply:
                    runtime.retry('loans', blocked)
                self.assertEqual(apply.call_args.args[5], {'loan:1', 'loan:2'})
                # The global barrier still sees the actual latest blocked outcome.
                self.assertEqual({x['source_key']: x['status'] for x in state.latest_plan_run_items(plan_id)}['loan:1'], 'blocked')
            finally:
                state.conn.close()
