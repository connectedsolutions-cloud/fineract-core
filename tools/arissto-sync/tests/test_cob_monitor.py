from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from arissto_sync.cob_monitor import CobStore, build_snapshot, capture_snapshot, remote_execution_gaps
from arissto_sync.config import SourceConfig


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def payload(*, complete: bool = False) -> dict:
    processes = [
        {
            "process_id": "1", "system_code": "0", "process_order": "1",
            "process_name": "CREACION REGISTROS DE CIERRE", "process_status": "1",
            "started_at_utc": dt("2026-09-16T23:14:49"),
            "finished_at_utc": dt("2026-09-16T23:14:50"), "lock_flag": 0,
        },
        {
            "process_id": "1", "system_code": "1", "process_order": "19",
            "process_name": "MAYORIZACION CONTABLE", "process_status": "1" if complete else None,
            "started_at_utc": dt("2026-09-17T13:55:24") if complete else None,
            "finished_at_utc": dt("2026-09-17T13:58:10") if complete else None,
            "lock_flag": 0,
        },
    ]
    return {
        "daily": {
            "company_id": "001", "close_id": "000000002177", "operation_date": date(2026, 9, 16),
            "global_close_status": "1" if complete else "0",
            "source_server_time_utc": dt("2026-09-17T14:00:00") if complete else dt("2026-09-16T23:20:00"),
            "expected_module_count": 2, "module_count": 2,
            "closed_module_count": 2 if complete else 0,
            "open_module_count": 0 if complete else 2, "null_module_count": 0,
            "expected_process_count": 2,
            "previous_open_modules_finish": dt("2026-09-16T14:02:47"),
        },
        "processes": processes,
        "mayorization": {
            "mayorization_rows": 1 if complete else 0,
            "first_mayorization_created_at_utc": dt("2026-09-17T13:55:24.303") if complete else None,
            "last_mayorization_created_at_utc": dt("2026-09-17T13:55:24.303") if complete else None,
        },
        "accruals": [
            {"product_type_id": 3, "accrual_count": 398,
             "first_created_at_utc": dt("2026-09-16T23:15:21.640"),
             "last_created_at_utc": dt("2026-09-16T23:17:41.940")},
            {"product_type_id": 4, "accrual_count": 42,
             "first_created_at_utc": dt("2026-09-16T23:15:00.290"),
             "last_created_at_utc": dt("2026-09-16T23:15:02.633")},
        ],
    }


class CobMonitorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.directory.name) / "state.sqlite3"
        self.config = SourceConfig(
            server="sql.example.test", port=1433, database="arissto", user="reader",
            password="secret", driver="ODBC Driver 18 for SQL Server", extra="ApplicationIntent=ReadOnly",
            connect_timeout=1, query_timeout=1,
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_builds_in_progress_and_complete_snapshots(self):
        running = build_snapshot(payload(), dt("2026-09-16T23:20:00"))
        completed = build_snapshot(payload(complete=True), dt("2026-09-17T14:00:00"))
        self.assertEqual(running["summary"]["state"], "RUNNING")
        self.assertEqual(completed["summary"]["state"], "COMPLETE")
        self.assertTrue(completed["summary"]["ready_to_sync"])

    def test_finished_process_with_failed_status_is_not_complete(self):
        failed = payload(complete=True)
        failed["processes"][1]["process_status"] = "0"
        snapshot = build_snapshot(failed, dt("2026-09-17T14:00:00"))
        self.assertEqual(snapshot["summary"]["state"], "INCONSISTENT")
        self.assertFalse(snapshot["summary"]["ready_to_sync"])

    def test_later_snapshot_backfills_finish_and_deduplicates_start(self):
        moments = iter([
            dt("2026-09-16T23:20:00"), dt("2026-09-16T23:20:01"),
            dt("2026-09-17T14:00:00"), dt("2026-09-17T14:00:01"),
        ])
        first = capture_snapshot(
            self.config, self.state_path, date(2026, 9, 16),
            clock=lambda: next(moments), fetcher=lambda *_: payload(),
        )
        second = capture_snapshot(
            self.config, self.state_path, date(2026, 9, 16),
            clock=lambda: next(moments), fetcher=lambda *_: payload(complete=True),
        )
        self.assertEqual(first["state"], "RUNNING")
        self.assertEqual(second["state"], "COMPLETE")
        store = CobStore(self.state_path)
        try:
            timeline = store.timeline(date(2026, 9, 16))
        finally:
            store.close()
        event_types = [item["event_type"] for item in timeline["events"]]
        self.assertEqual(event_types.count("BUSINESS_DAY_OPENED"), 1)
        self.assertEqual(event_types.count("COB_STARTED"), 1)
        self.assertIn("COB_FINISHED", event_types)
        self.assertIn("READY_TO_SYNC", event_types)
        self.assertTrue(any(item["gap_type"] == "OBSERVATION_GAP" for item in timeline["gaps"]))

    def test_failed_connection_is_persisted_and_closed_on_recovery(self):
        moments = iter([
            dt("2026-09-17T01:00:00"), dt("2026-09-17T01:00:01"),
            dt("2026-09-17T14:00:00"), dt("2026-09-17T14:00:01"),
        ])

        def unavailable(*_):
            raise TimeoutError("source unavailable")

        failed = capture_snapshot(
            self.config, self.state_path, date(2026, 9, 16),
            clock=lambda: next(moments), fetcher=unavailable,
        )
        recovered = capture_snapshot(
            self.config, self.state_path, date(2026, 9, 16),
            clock=lambda: next(moments), fetcher=lambda *_: payload(complete=True),
        )
        self.assertEqual(failed["state"], "DATABASE_UNREACHABLE")
        self.assertEqual(recovered["closed_outages"], 1)
        store = CobStore(self.state_path)
        try:
            gaps = store.timeline(date(2026, 9, 16))["gaps"]
        finally:
            store.close()
        outage = next(item for item in gaps if item["gap_type"] == "CONFIRMED_DATABASE_OUTAGE")
        self.assertIsNotNone(outage["ended_at_utc"])
        self.assertEqual(outage["overlaps_shutdown_window"], 1)

    def test_detects_split_execution_gap_and_shutdown_overlap(self):
        snapshot = build_snapshot(payload(complete=True), dt("2026-09-17T14:00:00"))
        gaps = remote_execution_gaps(snapshot["processes"])
        self.assertEqual(len(gaps), 1)
        self.assertTrue(gaps[0]["overlaps_shutdown_window"])
        self.assertGreater(gaps[0]["details"]["elapsed_seconds"], 14 * 60 * 60)


if __name__ == "__main__":
    unittest.main()
