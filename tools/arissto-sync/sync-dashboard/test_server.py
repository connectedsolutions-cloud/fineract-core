import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server import (
    CYCLE_CONFIRMATION,
    LAUNCH_CONFIRMATION,
    Launcher,
    Store,
    attach_step_item_counts,
    attach_live_item_counts,
    classify_failure,
    readonly_connection,
)


class FakeStore:
    def cycle(self, cycle_id):
        return {"id": cycle_id, "status": "open", "target_name": "local"}

    def cycles(self):
        return [self.cycle("cycle-a")]

    def active_runs(self, cycle_id):
        return []

    def all_active_runs(self):
        return []


class FakeLauncher(Launcher):
    def __init__(self):
        super().__init__(FakeStore(), Path("/tmp/arissto-sync"))
        self.calls = []

    def _run(self, arguments, timeout):
        self.calls.append((arguments, timeout))
        if arguments == ["workflow", "list"]:
            return {"workflows": [{"id": "workflow-a", "ready": True}]}
        if arguments[1:3] == ["cycle", "create"]:
            return {"cycle_id": arguments[4], "status": "open"}
        if arguments[1] == "plan":
            return {"workflow_plan_id": "a" * 32}
        return {"workflow_run_id": "b" * 32, "status": "queued"}

    def options(self):
        return {"workflows": [{
            "id": "workflow-a", "ready": True,
            "targets": ["local"],
            "run_modes": ["fresh-clean", "full-resync"],
        }]}


class DashboardStoreTest(unittest.TestCase):
    def test_live_counts_refresh_before_child_run_is_attached(self):
        from arissto_sync.state import SCHEMA
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)",
            ("child", "plan", "target", "clients", "2026-10-29T12:01:00", None, "running", "{}"))
        # A finished earlier execution of the same plan must not leak into this one.
        connection.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)",
            ("old", "plan", "target", "clients", "2026-10-29T11:00:00", None, "failed", "{}"))
        for index, status in enumerate(["succeeded", "recovered", "failed", "blocked", "unchanged", "quarantined"]):
            connection.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?)",
                ("child", str(index), "write", "hash", None, status, None))
        connection.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?)",
            ("old", "old", "write", "hash", None, "failed", None))
        step = {"workflow_run_id": "workflow", "service_id": "clients", "attempt": 1,
                "plan_id": "plan", "phase": "apply", "started_at": "2026-10-29T12:00:00"}
        attach_live_item_counts(connection, step)
        self.assertEqual((step["succeeded_item_count"], step["failed_item_count"],
                          step["unchanged_item_count"], step["processed_item_count"]), (2, 1, 1, 6))
        connection.execute("UPDATE items SET status='succeeded' WHERE run_id='child' AND status='failed'")
        attach_live_item_counts(connection, step)
        self.assertEqual((step["succeeded_item_count"], step["failed_item_count"]), (3, 0))
        # Attached runs work after completion too.
        step.update(child_run_id="child", phase="completed")
        attach_live_item_counts(connection, step)
        self.assertEqual(step["succeeded_item_count"], 3)
        # Queued services show zeros, never counts from a previous execution.
        step.update(child_run_id=None, phase="pending")
        attach_live_item_counts(connection, step)
        self.assertEqual((step["succeeded_item_count"], step["failed_item_count"]), (0, 0))
        self.assertIsNone(step["processed_item_count"])
        # A live retry may not yet have its prior plan attached.
        connection.execute("INSERT INTO workflow_steps "
            "(id,workflow_run_id,service_id,ordinal,attempt,status,phase,plan_id) "
            "VALUES('prior','workflow','clients',1,1,'failed','apply','plan')")
        step.update(plan_id=None, attempt=2, phase="apply")
        attach_live_item_counts(connection, step)
        self.assertEqual(step["succeeded_item_count"], 3)

    def test_run_detail_exposes_only_active_metric_comparison_from_recorded_reconciliation(self):
        from arissto_sync.loan_metric_alignment import METRICS
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.sqlite3'
            conn=sqlite3.connect(path)
            conn.executescript("""
              CREATE TABLE workflow_runs(id TEXT,summary TEXT);
              CREATE TABLE workflow_steps(id TEXT,workflow_run_id TEXT,service_id TEXT,ordinal INT,attempt INT,child_run_id TEXT,plan_id TEXT,summary TEXT);
              CREATE TABLE plans(id TEXT,document TEXT);
              CREATE TABLE items(run_id TEXT,status TEXT);
              CREATE TABLE workflow_failures(workflow_run_id TEXT,workflow_step_id TEXT,service_id TEXT,item_status TEXT,source_key TEXT,fingerprint TEXT);
              CREATE TABLE workflow_events(sequence INT,workflow_run_id TEXT,service_id TEXT,attempt INT,phase TEXT,event_type TEXT,status TEXT,severity TEXT,source_key TEXT,error_code TEXT,message TEXT,created_at TEXT);
              CREATE TABLE reconciliations(run_id TEXT,summary TEXT);
            """)
            actions=[{'entity_type':'loan','source_key':'loan:1','action':'create-loan',
                'lifecycle':{'expected':{'source_state':'1'},'final_metric_alignment':{'targets':dict.fromkeys(METRICS,'1.00')}}}]
            result={'ok':True,'counts':{'continuation_schedules_reconciled':1},'mismatches':[],
                'variances':[{'source_key':'loan:1','kind':'schedule_due_date','classification':'verified_final_continuation_schedule_variance'}]}
            conn.execute("INSERT INTO workflow_runs VALUES('workflow','{}')")
            conn.execute("INSERT INTO workflow_steps VALUES('step','workflow','loans',1,1,'child','plan','{}')")
            conn.execute('INSERT INTO plans VALUES(?,?)',('plan',json.dumps({'actions':actions})))
            conn.execute('INSERT INTO reconciliations VALUES(?,?)',('child',json.dumps(result)))
            conn.commit();conn.close()
            store=Store(Path(directory))
            with patch.object(store,'state_path',return_value=path),patch.object(store,'cycle',return_value={'id':'cycle'}):
                detail=store.run_detail('cycle','workflow')
            report=detail['loan_reporting']
            self.assertEqual((report['active_loans'],report['matched'],report['mismatched']),(1,8,0))
            self.assertEqual(report['reference_details']['expected_schedule_count'],1)
            self.assertEqual(report['insurance_breakdowns_verified'],0)
            self.assertNotIn('_plan_document',detail['latest_steps'][0])

    def test_full_sync_is_marked_as_dashboard_default(self):
        launcher = Launcher(FakeStore(), Path("/tmp/arissto-sync"))
        registry = {
            "services": [{
                "id": "clients", "name": "Clients", "depends_on": [],
                "status": "available", "executable": True,
            }]
        }
        workflows = {
            "workflows": [
                {"id": "local-credit-collections", "ready": True, "ordered_services": ["clients"]},
                {"id": "local-full-sync", "ready": True, "ordered_services": ["clients"]},
                {"id": "local-full-resync", "ready": True, "ordered_services": ["clients"]},
            ]
        }
        with (
            patch.object(launcher, "_run", return_value=workflows),
            patch("server.json.loads", return_value=registry),
            patch("server.Path.read_text", return_value="{}"),
        ):
            options = launcher.options()

        defaults = [item["id"] for item in options["workflows"] if item["default_for_mode"]]
        self.assertEqual(defaults, ["local-full-sync", "local-full-resync"])

    def test_step_item_count_prefers_frozen_plan_total(self):
        step = {
            "_plan_document": '{"actions":[{"action":"create"},{"action":"update"}]}',
            "summary": {"apply_counts": {"create": 1}},
            "processed_item_count": 1,
        }

        attach_step_item_counts(step)

        self.assertEqual(step["sync_item_count"], 2)
        self.assertEqual(step["processed_item_count"], 1)
        self.assertNotIn("_plan_document", step)

    def test_launcher_keeps_stderr_warnings_out_of_json_response(self):
        launcher = Launcher(FakeStore(), Path("/tmp/arissto-sync"))
        completed = SimpleNamespace(
            stdout='{"ok": true, "status": "open"}\n',
            stderr="InsecureRequestWarning: Unverified HTTPS request\n",
            returncode=0,
        )

        with patch("server.subprocess.run", return_value=completed) as run:
            result = launcher._run(["workflow", "list"], timeout=20)

        self.assertEqual(result, {"ok": True, "status": "open"})
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.PIPE)

    def test_cycle_creation_is_fresh_local_and_requires_baseline_confirmation(self):
        launcher = FakeLauncher()
        with self.assertRaises(ValueError):
            launcher.create_cycle({
                "cycle_id": "sandbox-new", "baseline_ref": "snapshot-42",
                "confirmation": "yes",
            })
        result = launcher.create_cycle({
            "cycle_id": "sandbox-new", "baseline_ref": "snapshot-42",
            "confirmation": CYCLE_CONFIRMATION,
        })
        self.assertEqual(result["status"], "open")
        self.assertEqual(launcher.calls[-1][0], [
            "workflow", "cycle", "create", "--cycle", "sandbox-new",
            "--baseline-ref", "snapshot-42", "--note",
            "Created from the local sync dashboard", "--target", "local",
        ])

    def test_cycle_creation_can_request_guarded_local_baseline_reset(self):
        launcher = FakeLauncher()
        launcher.create_cycle({
            "cycle_id": "sandbox-reset", "baseline_ref": "snapshot-42",
            "reset_target": True, "reset_tenant": "sandbox",
            "reset_confirmation": "sandbox:fineract_sandbox",
        })
        arguments, timeout = launcher.calls[-1]
        self.assertEqual(arguments[-4:], [
            "--reset-tenant", "sandbox", "--reset-confirm", "sandbox:fineract_sandbox",
        ])
        self.assertEqual(timeout, 1200)
        with self.assertRaises(ValueError):
            launcher.create_cycle({
                "cycle_id": "bad-reset", "baseline_ref": "snapshot-42",
                "reset_target": True, "reset_tenant": "default",
                "reset_confirmation": "default:fineract_default",
            })

    def test_launcher_hard_codes_local_target_and_requires_confirmation(self):
        launcher = FakeLauncher()
        launcher.prepare({
            "cycle_id": "cycle-a", "workflow_id": "workflow-a", "services": ["loans"],
        })
        self.assertIn("local", launcher.calls[-1][0])
        self.assertEqual(launcher.calls[-1][0][-2:], ["--include-service", "loans"])
        with self.assertRaises(ValueError):
            launcher.launch({
                "cycle_id": "cycle-a", "workflow_plan_id": "a" * 32,
                "confirmation": "yes",
            })
        result = launcher.launch({
            "cycle_id": "cycle-a", "workflow_plan_id": "a" * 32,
            "confirmation": LAUNCH_CONFIRMATION,
        })
        self.assertEqual(result["status"], "queued")
        self.assertEqual(launcher.calls[-1][0][-2:], ["--target", "local"])

    def test_launcher_forwards_local_full_resync_without_creating_a_cycle(self):
        launcher = FakeLauncher()
        launcher.prepare({
            "cycle_id": "cycle-a", "workflow_id": "workflow-a",
            "run_mode": "full-resync", "services": ["loans"],
        })
        arguments = launcher.calls[-1][0]
        self.assertIn("--cycle", arguments)
        self.assertEqual(arguments[arguments.index("--run-mode") + 1], "full-resync")
        self.assertEqual(arguments[-2:], ["--include-service", "loans"])

    def test_ledger_selection_defaults_to_full_scope_and_can_forward_period(self):
        launcher = FakeLauncher()
        launcher.prepare({
            "cycle_id": "cycle-a", "workflow_id": "workflow-a",
            "services": ["accounting-journal-entries"],
        })
        self.assertNotIn("--accounting-period", launcher.calls[-1][0])
        launcher.prepare({
            "cycle_id": "cycle-a", "workflow_id": "workflow-a",
            "services": ["accounting-journal-entries"], "accounting_period": "00028",
        })
        self.assertEqual(launcher.calls[-1][0][-2:], ["--accounting-period", "00028"])

    def test_classifies_structural_and_transient_failures(self):
        structural = classify_failure({
            "source_key": "account:1", "item_status": "failed",
            "error_code": "RuntimeError:Expected one native DPF interest transfer",
            "seen_in_executions": 3,
        })
        transient = classify_failure({
            "source_key": "account:2", "item_status": "failed",
            "error_code": "Fineract API failed (503): temporarily unavailable",
            "seen_in_executions": 1,
        })
        self.assertEqual(structural["failure_class"], "structural")
        self.assertEqual(transient["failure_class"], "retryable")

    def test_repeated_unknown_failure_is_persistent(self):
        result = classify_failure({
            "source_key": "account:1", "item_status": "failed",
            "error_code": "unclassified-invariant", "seen_in_executions": 2,
        })
        self.assertEqual(result["failure_class"], "persistent")

    def test_readonly_connection_rejects_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE sample(id INTEGER)")
            connection.commit()
            connection.close()

            with readonly_connection(path) as readonly:
                with self.assertRaises(sqlite3.OperationalError):
                    readonly.execute("INSERT INTO sample VALUES(1)")

    def test_unknown_cycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(root / "cycles.sqlite3")
            connection.execute("""
                CREATE TABLE sync_cycles (
                  id TEXT PRIMARY KEY, created_at TEXT, closed_at TEXT, status TEXT,
                  target_name TEXT, target_fingerprint TEXT, baseline_ref TEXT,
                  state_path TEXT, note TEXT
                )
            """)
            connection.commit()
            connection.close()
            with self.assertRaises(KeyError):
                Store(root).cycle("missing")


if __name__ == "__main__":
    unittest.main()
