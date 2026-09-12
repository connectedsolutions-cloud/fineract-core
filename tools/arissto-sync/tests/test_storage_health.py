from __future__ import annotations

import tempfile
import unittest
import warnings
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import arissto_sync.connections as connections
from arissto_sync.cycles import CycleCatalog
from arissto_sync.state import State
from arissto_sync.storage_health import storage_health


class StorageHealthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.base_state = self.root / "state.sqlite3"
        self.catalog = CycleCatalog(self.base_state)

    def tearDown(self):
        self.catalog.conn.close()
        self.directory.cleanup()

    def test_reports_storage_without_modifying_cycle_state(self):
        cycle = self.catalog.create(
            "cycle-a", "local", "target-a", "baseline-a"
        )
        state = State(Path(cycle["state_path"]))
        try:
            state.save_plan("target-a", "clients", "source", "contract", {
                "actions": [{"source_key": "1", "action": "create"}],
            })
        finally:
            state.conn.close()
        log_dir = Path(cycle["state_path"]).parent / "workflow-runs"
        log_dir.mkdir()
        log_path = log_dir / "run.log"
        log_path.write_text("InsecureRequestWarning\nInsecureRequestWarning\n", encoding="utf-8")

        report = storage_health(
            self.base_state,
            max_total_bytes=1,
            max_run_log_bytes=1,
            stale_open_days=2,
            clock=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["usage"]["insecure_request_warning_count"], 2)
        self.assertEqual(report["cycles"][0]["state"]["plan_count"], 1)
        self.assertEqual(
            {finding["code"] for finding in report["findings"]},
            {"large-run-log", "storage-budget-exceeded", "repeated-tls-warning-output"},
        )
        self.assertTrue(Path(cycle["state_path"]).exists())

    def test_flags_old_inactive_open_cycle_but_not_closed_cycle(self):
        first = self.catalog.create("old-open", "local", "target-a", "baseline-a")
        self.catalog.conn.execute(
            "UPDATE sync_cycles SET created_at=? WHERE id=?",
            ("2026-09-01T00:00:00+00:00", "old-open"),
        )
        self.catalog.conn.commit()
        self.catalog.create("closed", "local", "target-b", "baseline-b")
        self.catalog.close("closed")
        self.catalog.conn.execute(
            "UPDATE sync_cycles SET status='open',closed_at=NULL WHERE id=?",
            (first["id"],),
        )
        self.catalog.conn.commit()

        report = storage_health(
            self.base_state,
            max_total_bytes=10**9,
            max_run_log_bytes=10**9,
            stale_open_days=2,
            clock=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )

        stale = [finding for finding in report["findings"] if finding["code"] == "stale-open-cycle"]
        self.assertEqual([finding["cycle_id"] for finding in stale], [first["id"]])

    def test_legacy_state_metrics_are_included(self):
        state = State(self.base_state)
        try:
            state.save_plan("target-a", "clients", "source", "contract", {"actions": []})
        finally:
            state.conn.close()

        report = storage_health(
            self.base_state,
            max_total_bytes=10**9,
            max_run_log_bytes=10**9,
            clock=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )

        self.assertEqual(report["legacy_state"]["plan_count"], 1)
        self.assertNotIn("inspection_error", report["legacy_state"])

    def test_state_inspection_falls_back_to_immutable_snapshot(self):
        state = State(self.base_state)
        state.conn.close()
        real_connect = __import__("sqlite3").connect

        def connect(database, *args, **kwargs):
            if "mode=ro" in str(database):
                raise __import__("sqlite3").OperationalError("read-only WAL unavailable")
            return real_connect(database, *args, **kwargs)

        with patch("arissto_sync.storage_health.sqlite3.connect", side_effect=connect):
            report = storage_health(
                self.base_state,
                max_total_bytes=10**9,
                max_run_log_bytes=10**9,
                clock=datetime(2026, 9, 5, tzinfo=timezone.utc),
            )

        self.assertEqual(report["legacy_state"]["inspection_mode"], "immutable-snapshot")
        self.assertNotIn("inspection_error", report["legacy_state"])

    def test_every_cycle_except_the_newest_is_a_retention_candidate(self):
        for index in range(6):
            cycle_id = f"closed-{index}"
            self.catalog.create(cycle_id, "local", "target-a", f"baseline-{index}")
            self.catalog.close(cycle_id)
            self.catalog.conn.execute(
                "UPDATE sync_cycles SET created_at=?,closed_at=? WHERE id=?",
                (f"2026-08-{index + 1:02d}T00:00:00+00:00", f"2026-08-{index + 1:02d}T01:00:00+00:00", cycle_id),
            )
        self.catalog.conn.commit()

        report = storage_health(
            self.base_state,
            max_total_bytes=10**9,
            max_run_log_bytes=10**9,
            clock=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )

        candidates = [
            finding["cycle_id"] for finding in report["findings"]
            if finding["code"] == "obsolete-cycle-retention-candidate"
        ]
        self.assertEqual(candidates, [
            "closed-4", "closed-3", "closed-2", "closed-1", "closed-0",
        ])


class TlsWarningTests(unittest.TestCase):
    def test_disabled_tls_warning_is_emitted_once_per_process(self):
        previous = connections._tls_warning_emitted
        connections._tls_warning_emitted = False
        try:
            config = SimpleNamespace(tls_verify=False)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                connections.FineractApi(config)
                connections.FineractApi(config)
            self.assertEqual(len(caught), 1)
            self.assertIn("TLS certificate verification is disabled", str(caught[0].message))
        finally:
            connections._tls_warning_emitted = previous


if __name__ == "__main__":
    unittest.main()
