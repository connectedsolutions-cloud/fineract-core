from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from arissto_sync.cycles import CycleCatalog
from arissto_sync.retention import APPLY_CONFIRMATION, apply_retention, retention_plan
from arissto_sync.state import State


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.base_state = self.root / "state.sqlite3"
        self.catalog = CycleCatalog(self.base_state)

    def tearDown(self):
        self.catalog.conn.close()
        self.directory.cleanup()

    def add_workflow_run(
        self, cycle: dict, run_id: str, status: str, finished_at: str, content: str,
    ) -> Path:
        state = State(Path(cycle["state_path"]))
        log_dir = Path(cycle["state_path"]).parent / "workflow-runs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"{run_id}.log"
        log_path.write_text(content, encoding="utf-8")
        state.conn.execute(
            "INSERT INTO workflow_plans(id,workflow_id,workflow_version,definition_hash,target_name,"
            "target_fingerprint,created_at,status,document) VALUES(?,?,?,?,?,?,?,?,?)",
            (f"plan-{run_id}", "test", 1, "hash", "local", "target-a", finished_at, "planned", "{}"),
        )
        state.conn.execute(
            "INSERT INTO workflow_runs(id,workflow_plan_id,workflow_id,target_name,target_fingerprint,"
            "created_at,started_at,finished_at,status,log_path) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (run_id, f"plan-{run_id}", "test", "local", "target-a", finished_at,
             finished_at, finished_at, status, str(log_path)),
        )
        state.conn.commit()
        state.conn.close()
        return log_path

    def test_new_cycle_closes_superseded_inactive_cycle(self):
        first = self.catalog.create("first", "local", "target-a", "baseline-a")
        second = self.catalog.create("second", "local", "target-a", "baseline-b")

        self.assertEqual(self.catalog.get(first["id"])["status"], "closed")
        self.assertEqual(self.catalog.get(second["id"])["status"], "open")

    def test_plan_preserves_only_newest_cycle(self):
        closed = self.catalog.create("closed", "local", "target-a", "baseline-a")
        active = self.catalog.create("active", "local", "target-a", "baseline-b")
        failed = self.add_workflow_run(
            closed, "failed-run", "failed", "2026-08-20T00:00:00+00:00", "failure details\n" * 100,
        )
        successful = self.add_workflow_run(
            closed, "success-run", "completed", "2026-08-20T00:00:00+00:00", "success details\n",
        )

        plan = retention_plan(
            self.base_state, scope="local", clock=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )
        names = {action["action"] for action in plan["actions"]}
        self.assertEqual(names, {"delete-obsolete-cycle"})
        self.assertTrue(Path(active["state_path"]).is_file())

        result = apply_retention(
            self.base_state, confirmation=APPLY_CONFIRMATION, scope="local",
        )

        self.assertTrue(result["ok"])
        self.assertFalse(failed.exists())
        self.assertFalse(successful.exists())
        self.assertFalse(Path(closed["state_path"]).parent.exists())
        self.assertTrue(Path(active["state_path"]).is_file())

    def test_all_obsolete_cycles_are_removed_without_archives(self):
        cycles = []
        for index in range(7):
            cycles.append(self.catalog.create(
                f"cycle-{index}", "local", "target-a", f"baseline-{index}",
            ))
        for index, cycle in enumerate(cycles[:-1]):
            self.catalog.conn.execute(
                "UPDATE sync_cycles SET created_at=?,closed_at=? WHERE id=?",
                (f"2026-07-{index + 1:02d}T00:00:00+00:00",
                 f"2026-07-{index + 1:02d}T01:00:00+00:00", cycle["id"]),
            )
        self.catalog.conn.commit()

        result = apply_retention(
            self.base_state, confirmation=APPLY_CONFIRMATION, scope="local",
        )

        self.assertTrue(result["ok"])
        for cycle in cycles[:-1]:
            self.assertFalse(Path(cycle["state_path"]).parent.exists())
            with self.assertRaisesRegex(ValueError, "Unknown sync cycle"):
                self.catalog.get(cycle["id"])
        self.assertTrue(Path(cycles[-1]["state_path"]).is_file())

    def test_production_preserves_run_plan_and_failure_identities_while_compacting_items(self):
        state = State(self.base_state)
        fingerprint = "prod-fingerprint"
        try:
            state.save_inspection("prod", fingerprint, "clients", "contract", "schema", True)
            state.save_inspection("prod", fingerprint, "mobile-collections", "contract", "schema", True)
            run_ids = []
            old_plan = state.save_plan(
                fingerprint, "mobile-collections", "source", "contract", {"actions": [{"source_key": "old"}]},
            )
            old_run = state.start_run(state.plan(old_plan))
            state.record_item(old_run, "old", "create", "old-hash", "succeeded", "old")
            state.finish_run(old_run, "completed", {"index": "old"})
            for index in range(3):
                plan_id = state.save_plan(
                    fingerprint, "clients", "source", "contract", {"actions": [{"source_key": str(index)}]},
                )
                run_id = state.start_run(state.plan(plan_id))
                state.record_item(run_id, str(index), "create", f"hash-{index}", "succeeded", str(index))
                state.finish_run(run_id, "completed", {"index": index})
                run_ids.append(run_id)
            state.save_mapping(fingerprint, "clients", "source", "target", "hash")
            state.save_mapping(fingerprint, "mobile-collections", "old", "old-target", "old-hash")
        finally:
            state.conn.close()

        apply_retention(self.base_state, confirmation=APPLY_CONFIRMATION, scope="prod")

        state = State(self.base_state)
        try:
            retained_runs = state.conn.execute(
                "SELECT id FROM runs WHERE target_fingerprint=?", (fingerprint,)
            ).fetchall()
            self.assertEqual(len(retained_runs), 4)
            self.assertEqual(state.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0], 2)
            self.assertEqual(state.conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0], 4)
            self.assertEqual(state.conn.execute("SELECT COUNT(*) FROM mappings").fetchone()[0], 2)
            self.assertEqual(state.conn.execute("SELECT COUNT(*) FROM inspections").fetchone()[0], 2)
        finally:
            state.conn.close()

    def test_legacy_local_state_is_deleted_without_touching_production(self):
        state = State(self.base_state)
        try:
            for target_name, fingerprint in (("local", "local-fp"), ("prod", "prod-fp")):
                state.save_inspection(target_name, fingerprint, "clients", "contract", "schema", True)
                plan_id = state.save_plan(
                    fingerprint, "clients", "source", "contract", {"actions": [target_name]},
                )
                run_id = state.start_run(state.plan(plan_id))
                state.record_item(run_id, target_name, "create", "hash", "succeeded", target_name)
                state.finish_run(run_id, "completed", {"target": target_name})
                state.save_mapping(fingerprint, "clients", target_name, target_name, "hash")
        finally:
            state.conn.close()

        apply_retention(self.base_state, confirmation=APPLY_CONFIRMATION, scope="local")

        state = State(self.base_state)
        try:
            for table in ("plans", "runs", "mappings"):
                self.assertEqual(state.conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE target_fingerprint='local-fp'"
                ).fetchone()[0], 0)
                self.assertEqual(state.conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE target_fingerprint='prod-fp'"
                ).fetchone()[0], 1)
            self.assertEqual(state.conn.execute(
                "SELECT COUNT(*) FROM inspections WHERE target_name='local'"
            ).fetchone()[0], 0)
            self.assertEqual(state.conn.execute(
                "SELECT COUNT(*) FROM inspections WHERE target_name='prod'"
            ).fetchone()[0], 1)
        finally:
            state.conn.close()

    def test_legacy_local_cleanup_blocks_a_running_run(self):
        state = State(self.base_state)
        try:
            state.save_inspection("local", "local-fp", "clients", "contract", "schema", True)
            plan_id = state.save_plan(
                "local-fp", "clients", "source", "contract", {"actions": ["active"]},
            )
            state.start_run(state.plan(plan_id))
        finally:
            state.conn.close()

        plan = retention_plan(self.base_state, scope="local")

        self.assertEqual(plan["blocked_action_count"], 1)
        self.assertIn("blocked-delete-active-legacy-local-state", {
            action["action"] for action in plan["actions"]
        })

    def test_obsolete_cycle_is_deleted_and_active_cycle_is_untouched(self):
        closed = self.catalog.create("closed", "local", "target-a", "baseline-a")
        active = self.catalog.create("active", "local", "target-a", "baseline-b")
        state = State(Path(closed["state_path"]))
        try:
            successful_plans = []
            successful_runs = []
            for index in range(2):
                plan_id = state.save_plan(
                    "target-a", "clients", "source", "contract",
                    {"actions": [{"source_key": str(value)} for value in range(100)]},
                )
                run_id = state.start_run(state.plan(plan_id))
                state.record_item(run_id, str(index), "create", "hash", "succeeded", str(index))
                state.finish_run(run_id, "completed", {"count": 1})
                successful_plans.append(plan_id)
                successful_runs.append(run_id)
            failed_plan = state.save_plan(
                "target-a", "loans", "source", "contract", {"actions": ["retain-me"] * 100},
            )
            failed_run = state.start_run(state.plan(failed_plan))
            state.record_item(failed_run, "failed", "create", "hash", "failed", error_code="boom")
            state.finish_run(failed_run, "completed-with-errors", {"failed": 1})
            state.save_mapping("target-a", "clients", "source", "target", "hash")
        finally:
            state.conn.close()

        active_state = State(Path(active["state_path"]))
        try:
            active_plan = active_state.save_plan(
                "target-a", "clients", "source", "contract", {"actions": ["active"] * 100},
            )
            active_run = active_state.start_run(active_state.plan(active_plan))
            active_state.record_item(active_run, "active", "create", "hash", "succeeded", "active")
            active_state.finish_run(active_run, "completed", {"count": 1})
        finally:
            active_state.conn.close()

        apply_retention(self.base_state, confirmation=APPLY_CONFIRMATION, scope="local")

        self.assertFalse(Path(closed["state_path"]).parent.exists())
        active_state = State(Path(active["state_path"]))
        try:
            self.assertNotIn("retention_compacted", active_state.plan(active_plan)["document"])
            self.assertEqual(len(active_state.run_items(active_run)), 1)
        finally:
            active_state.conn.close()

    def test_apply_requires_exact_confirmation(self):
        with self.assertRaisesRegex(ValueError, APPLY_CONFIRMATION):
            apply_retention(self.base_state, confirmation="no", scope="local")

    def test_local_retention_archive_is_deleted_immediately(self):
        path = self.root / "retention" / "failed-logs" / "old" / "run.log.gz"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"old")
        plan = retention_plan(
            self.base_state, scope="local", clock=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )

        self.assertIn("delete-local-retention-archive", {
            action["action"] for action in plan["actions"]
        })


if __name__ == "__main__":
    unittest.main()
