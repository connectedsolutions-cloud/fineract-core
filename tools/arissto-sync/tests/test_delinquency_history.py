import unittest
import sqlite3
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from arissto_sync.delinquency_history import (
    DailyClassification, TagInterval, compress_classifications, compress_sorted_classifications,
)
from arissto_sync.delinquency_history_import import (
    NativeInterval, SourceTimeline, _check_manifest, _compare, _loan_quarantine, _native_handoff_candidates,
    _manifest_values, _native_intervals,
)


class HistoricalClassificationTests(unittest.TestCase):
    def test_stored_e_at_zero_days_remains_e(self):
        rows = [
            DailyClassification("42", date(2026, 9, 1), "1", 0),
            DailyClassification("42", date(2026, 9, 2), "8", 0),
            DailyClassification("42", date(2026, 9, 3), "8", 4),
        ]
        self.assertEqual(compress_classifications(rows, source_through_date=date(2026, 9, 3)), [
            TagInterval("42", "A1", date(2026, 9, 1), date(2026, 9, 2)),
            TagInterval("42", "E", date(2026, 9, 2), date(2026, 9, 4)),
        ])

    def test_gap_does_not_invent_a_classification(self):
        rows = [
            DailyClassification("42", date(2026, 9, 1), "1", 0),
            DailyClassification("42", date(2026, 9, 3), "1", 0),
        ]
        self.assertEqual(compress_classifications(rows, source_through_date=date(2026, 9, 3)), [
            TagInterval("42", "A1", date(2026, 9, 1), date(2026, 9, 2)),
            TagInterval("42", "A1", date(2026, 9, 3), date(2026, 9, 4)),
        ])

    def test_duplicate_day_is_rejected(self):
        rows = [DailyClassification("42", date(2026, 9, 1), "1", 0)] * 2
        with self.assertRaisesRegex(ValueError, "Duplicate historical close"):
            compress_classifications(rows, source_through_date=date(2026, 9, 1))

    def test_stream_rejects_out_of_order_day(self):
        rows = [
            DailyClassification("42", date(2026, 9, 2), "1", 0),
            DailyClassification("42", date(2026, 9, 1), "1", 0),
        ]
        with self.assertRaisesRegex(ValueError, "not ordered"):
            list(compress_sorted_classifications(rows, source_through_date=date(2026, 9, 2)))

    def test_native_interval_uses_source_category_independent_of_days(self):
        timeline = SourceTimeline(date(2026, 9, 2), 2, "hash", [
            TagInterval("42", "E", date(2026, 9, 1), date(2026, 9, 3)),
            TagInterval("missing", "A1", date(2026, 9, 1), date(2026, 9, 2)),
        ])
        result, unmapped, excluded = _native_intervals(timeline, {"42": 7}, {"E": 8, "A1": 1})
        self.assertEqual((result[0].classification, result[0].range_id), ("E", 8))
        self.assertEqual(unmapped, ["missing"])
        self.assertEqual(excluded, [])

    def test_reviewed_quarantine_is_excluded_but_new_unmapped_loan_is_pending(self):
        timeline = SourceTimeline(date(2026, 9, 2), 3, "hash", [
            TagInterval("42", "E", date(2026, 9, 1), date(2026, 9, 3)),
            TagInterval("quarantined", "A1", date(2026, 9, 1), date(2026, 9, 2)),
            TagInterval("new", "A1", date(2026, 9, 1), date(2026, 9, 2)),
        ])
        result, unmapped, excluded = _native_intervals(
            timeline, {"42": 7}, {"E": 8, "A1": 1}, frozenset({"quarantined"}))
        self.assertEqual([item.source_loan_id for item in result], ["42"])
        self.assertEqual(unmapped, ["new"])
        self.assertEqual(excluded, ["quarantined"])

    def test_quarantined_loan_with_native_mapping_is_rejected(self):
        timeline = SourceTimeline(date(2026, 9, 2), 1, "hash", [
            TagInterval("42", "E", date(2026, 9, 1), date(2026, 9, 3)),
        ])
        with self.assertRaisesRegex(RuntimeError, "Quarantined source loan 42 has a native loan mapping"):
            _native_intervals(timeline, {"42": 7}, {"E": 8}, frozenset({"42"}))

    def test_quarantine_reads_only_reconciled_current_cycle(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = sqlite3.connect(root / "cycles.sqlite3")
            catalog.execute("CREATE TABLE sync_cycles (id TEXT,status TEXT,target_name TEXT,target_fingerprint TEXT,state_path TEXT)")
            current = root / "current.sqlite3"
            catalog.executemany("INSERT INTO sync_cycles VALUES (?,?,?,?,?)", [
                ("old", "closed", "local", "target", str(root / "old.sqlite3")),
                ("current", "open", "local", "target", str(current)),
            ])
            catalog.commit()
            catalog.close()
            state = sqlite3.connect(current)
            state.executescript("""
                CREATE TABLE runs (id TEXT,plan_id TEXT,block TEXT,status TEXT,target_fingerprint TEXT,started_at TEXT);
                CREATE TABLE plans (id TEXT,source_fingerprint TEXT);
                CREATE TABLE reconciliations (run_id TEXT,ok INTEGER);
                CREATE TABLE items (run_id TEXT,source_key TEXT,status TEXT);
                INSERT INTO plans VALUES ('plan','source');
                INSERT INTO runs VALUES ('run','plan','loans','completed-with-quarantine','target','2026-10-07');
                INSERT INTO reconciliations VALUES ('run',1);
                INSERT INTO items VALUES ('run','loan:42','quarantined');
                INSERT INTO items VALUES ('run','loan:43','succeeded');
            """)
            state.commit()
            state.close()
            settings = SimpleNamespace(state_path=root / "state.sqlite3", source=object(),
                                       target=SimpleNamespace(name="local", fingerprint="target"))
            with patch("arissto_sync.delinquency_history_import.source_fingerprint", return_value="source"):
                evidence = _loan_quarantine(settings)
            self.assertEqual((evidence.cycle_id, evidence.run_id, evidence.source_ids),
                             ("current", "run", frozenset({"42"})))

    def test_exact_native_replay_is_idempotent(self):
        item = NativeInterval("42", 7, 8, "E", date(2026, 9, 1), date(2026, 9, 3), "abc")
        tags = [(99, 7, 8, item.added_on_date, item.lifted_on_date,
                 "42", item.added_on_date, item.lifted_on_date, "E", "abc")]
        self.assertEqual(_compare([item], tags), ([], 1))

    def test_native_overlap_is_rejected(self):
        item = NativeInterval("42", 7, 8, "E", date(2026, 9, 1), date(2026, 9, 3), "abc")
        tags = [(99, 7, 1, date(2026, 9, 2), None, None, None, None, None, None)]
        with self.assertRaisesRegex(RuntimeError, "overlaps"):
            _compare([item], tags)

    def test_overlap_inspect_reports_all_conflicting_native_tags(self):
        items = [
            NativeInterval("42", 7, 8, "E", date(2026, 9, 1), date(2026, 9, 3), "abc"),
            NativeInterval("43", 8, 8, "E", date(2026, 9, 1), date(2026, 9, 3), "def"),
        ]
        tags = [
            (99, 7, 1, date(2026, 9, 2), None, None, None, None, None, None),
            (100, 8, 1, date(2026, 9, 2), None, None, None, None, None, None),
        ]
        with self.assertRaisesRegex(RuntimeError, "2 native tags across 2 loans"):
            _compare(items, tags)

    def test_native_handoff_moves_open_and_boundary_lifted_tags_on_final_source_day(self):
        through = date(2026, 10, 10)
        tags = [
            (10, 7, 1, through, None, None, None, None, None, None),
            (11, 7, 1, through, through, None, None, None, None, None),
            (12, 7, 1, date(2026, 10, 11), None, None, None, None, None, None),
            (14, 7, 1, through, date(2026, 10, 11), None, None, None, None, None),
            (13, 7, 8, through, date(2026, 10, 11), "42", through,
             date(2026, 10, 11), "E", "abc"),
        ]
        self.assertEqual(_native_handoff_candidates(tags, through), [(10, 7, 1), (14, 7, 1)])

    def test_earlier_positive_native_interval_requires_review(self):
        tags = [(10, 7, 1, date(2026, 10, 9), None, None, None, None, None, None)]
        with self.assertRaisesRegex(RuntimeError, "Unreviewed native delinquency interval"):
            _native_handoff_candidates(tags, date(2026, 10, 10))

    def test_later_native_overlap_is_detected_during_reconciliation(self):
        item = NativeInterval("42", 7, 8, "E", date(2026, 9, 1), date(2026, 9, 3), "abc")
        tags = [
            (99, 7, 8, item.added_on_date, item.lifted_on_date,
             "42", item.added_on_date, item.lifted_on_date, "E", "abc"),
            (100, 7, 1, date(2026, 9, 2), None, None, None, None, None, None),
        ]
        with self.assertRaisesRegex(RuntimeError, "overlaps"):
            _compare([item], tags)

    def test_changed_source_tag_is_rejected(self):
        item = NativeInterval("42", 7, 8, "E", date(2026, 9, 1), date(2026, 9, 3), "abc")
        tags = [(99, 7, 1, item.added_on_date, item.lifted_on_date,
                 "42", item.added_on_date, item.lifted_on_date, "A1", "wrong")]
        with self.assertRaisesRegex(RuntimeError, "provenance conflicts"):
            _compare([item], tags)

    def test_manifest_freezes_source_timeline(self):
        timeline = SourceTimeline(date(2026, 9, 2), 2, "hash", [
            TagInterval("42", "E", date(2026, 9, 1), date(2026, 9, 3)),
        ])
        expected = _manifest_values(timeline, 1, 0)
        _check_manifest(expected, expected, 1)
        # A later target loan mapping can add intervals under the same frozen source timeline.
        _check_manifest((expected[0], expected[1], expected[2], expected[3], 0, 1), expected, 0)
        with self.assertRaisesRegex(RuntimeError, "conflicts"):
            _check_manifest((date(2026, 9, 3), *expected[1:]), expected, 1)
        with self.assertRaisesRegex(RuntimeError, "count conflicts"):
            _check_manifest(expected, expected, 0)
        with self.assertRaisesRegex(RuntimeError, "without an accepted manifest"):
            _check_manifest(None, expected, 1)


if __name__ == "__main__":
    unittest.main()
