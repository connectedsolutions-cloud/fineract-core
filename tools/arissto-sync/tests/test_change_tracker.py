from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from arissto_sync.change_tracker import ChangeTracker, change_tracker_path
from arissto_sync.cycles import CycleCatalog
from arissto_sync.retention import APPLY_CONFIRMATION, apply_retention
from arissto_sync.state import State


class ChangeTrackerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.base_state = self.root / "state.sqlite3"
        self.catalog = CycleCatalog(self.base_state)

    def tearDown(self):
        self.catalog.conn.close()
        self.directory.cleanup()

    def test_new_operational_state_does_not_create_tracker_tables(self):
        state = State(self.base_state)
        try:
            tables = {
                row[0] for row in state.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            state.conn.close()

        self.assertNotIn("loan_sync_changes", tables)
        self.assertNotIn("loan_sync_change_loans", tables)
        self.assertNotIn("loan_sync_change_decisions", tables)

    def test_durable_tracker_survives_cycle_retention(self):
        tracker = ChangeTracker(self.base_state)
        try:
            change_id = tracker.record_change(
                "a" * 40, "Repair refinance closures", commit_sha="a" * 40,
            )
            tracker.add_loan(change_id, "889", "fixed", target_loan_id="42")
            tracker.add_decision(change_id, "Use reversal", "Preserves the audit trail")
        finally:
            tracker.close()

        old_cycle = self.catalog.create("old", "local", "target-a", "baseline-a")
        self.catalog.create("new", "local", "target-a", "baseline-b")
        apply_retention(self.base_state, confirmation=APPLY_CONFIRMATION, scope="local")

        self.assertFalse(Path(old_cycle["state_path"]).parent.exists())
        with sqlite3.connect(change_tracker_path(self.base_state)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM loan_sync_changes").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM loan_sync_change_loans").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM loan_sync_change_decisions").fetchone()[0], 1)

    def test_cycle_creation_migrates_legacy_tracker_before_retention(self):
        old_cycle = self.catalog.create("old", "local", "target-a", "baseline-a")
        with sqlite3.connect(old_cycle["state_path"]) as connection:
            connection.executescript("""
                CREATE TABLE loan_sync_changes (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, pr_reference TEXT NOT NULL UNIQUE,
                 description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                 created_at TEXT NOT NULL, closed_at TEXT
                );
                CREATE TABLE loan_sync_change_loans (
                 change_id INTEGER NOT NULL, source_loan_id TEXT NOT NULL, target_loan_id TEXT,
                 result TEXT NOT NULL, notes TEXT, PRIMARY KEY (change_id, source_loan_id)
                );
                CREATE TABLE loan_sync_change_decisions (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, change_id INTEGER NOT NULL,
                 decision TEXT NOT NULL, rationale TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            connection.execute(
                "INSERT INTO loan_sync_changes VALUES(1,?,?,?,?,?)",
                ("b" * 40, "Repair allocations", "open", "2026-09-13T00:00:00+00:00", None),
            )
            connection.execute(
                "INSERT INTO loan_sync_change_loans VALUES(?,?,?,?,?)",
                (1, "889", "72", "fixed", None),
            )
            connection.execute(
                "INSERT INTO loan_sync_change_decisions VALUES(1,?,?,?,?)",
                (1, "Keep history", "Auditability", "2026-09-13T00:00:00+00:00"),
            )

        self.catalog.create("new", "local", "target-a", "baseline-b")
        apply_retention(self.base_state, confirmation=APPLY_CONFIRMATION, scope="local")

        with sqlite3.connect(change_tracker_path(self.base_state)) as connection:
            self.assertEqual(connection.execute(
                "SELECT change_reference,commit_sha FROM loan_sync_changes"
            ).fetchone(), ("b" * 40, "b" * 40))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM loan_sync_change_loans").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM loan_sync_change_decisions").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
