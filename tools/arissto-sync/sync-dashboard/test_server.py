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
