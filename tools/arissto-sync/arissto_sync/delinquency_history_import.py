"""Guarded one-time import of Arissto classifications into native tag history."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .arissto import select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import postgres_connection
from .delinquency_history import CLASSIFICATIONS, DailyClassification, TagInterval, compress_sorted_classifications
from .sql_writer import ControlledSqlWriter
from .state import State


BLOCK = "delinquency-history"
POLICY = "arissto-native-tag-intervals-v4-native-handoff"
SOURCE_SYSTEM = "ARISSTO_CLOSE"
WRITE_OPERATION = "replace_historical_delinquency_tags"


@dataclass(frozen=True)
class SourceTimeline:
    source_through_date: date
    source_rows: int
    source_hash: str
    intervals: list[TagInterval]


@dataclass(frozen=True)
class NativeInterval:
    source_loan_id: str
    loan_id: int
    range_id: int
    classification: str
    added_on_date: date
    lifted_on_date: date
    interval_hash: str

    @property
    def key(self) -> tuple[str, date]:
        return self.source_loan_id, self.added_on_date


@dataclass(frozen=True)
class LoanQuarantine:
    cycle_id: str | None
    run_id: str
    source_ids: frozenset[str]

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(sorted(self.source_ids), separators=(",", ":")).encode()).hexdigest()


def _loan_quarantine(settings: Settings) -> LoanQuarantine:
    """Read the accepted loan disposition for this exact target lifetime."""
    state_path = settings.state_path
    cycle_id = None
    if settings.target.name == "local":
        catalog_path = state_path.parent / "cycles.sqlite3"
        if catalog_path.is_file():
            with sqlite3.connect(f"file:{catalog_path}?mode=ro", uri=True) as catalog:
                cycles = catalog.execute(
                    "SELECT id,state_path FROM sync_cycles WHERE status='open' "
                    "AND target_name=? AND target_fingerprint=?", 
                    (settings.target.name, settings.target.fingerprint),
                ).fetchall()
            if len(cycles) > 1:
                raise RuntimeError("Multiple open loan migration cycles for selected target")
            if cycles:
                cycle_id, selected_path = cycles[0]
                state_path = Path(selected_path)
    if not state_path.is_file():
        raise RuntimeError("No loan migration state for selected target lifetime")
    with sqlite3.connect(f"file:{state_path}?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        run = source.execute("""
            SELECT r.id,r.plan_id FROM runs r
            JOIN reconciliations x ON x.run_id=r.id AND x.ok=1
            JOIN plans p ON p.id=r.plan_id
            WHERE r.block='loans' AND r.status IN ('completed','completed-with-quarantine')
              AND r.target_fingerprint=? AND p.source_fingerprint=?
            ORDER BY r.started_at DESC LIMIT 1
        """, (settings.target.fingerprint, source_fingerprint(settings.source))).fetchone()
        if run is None:
            raise RuntimeError("No reconciled loan migration run for selected target lifetime")
        # The latest terminal disposition across retries of the accepted plan is authoritative.
        rows = source.execute("""
            SELECT i.source_key,i.status FROM runs r JOIN items i ON i.run_id=r.id
            WHERE r.plan_id=? ORDER BY r.started_at,i.rowid
        """, (run["plan_id"],)).fetchall()
    terminal = {"succeeded", "recovered", "unchanged", "quarantined", "deferred", "reconciled"}
    latest: dict[str, str] = {}
    for row in rows:
        key, status = str(row["source_key"]), str(row["status"])
        if key not in latest or latest[key] not in terminal:
            latest[key] = status
    ids = frozenset(key.removeprefix("loan:") for key, status in latest.items()
                    if status == "quarantined" and key.startswith("loan:"))
    return LoanQuarantine(cycle_id, str(run["id"]), ids)


def _date(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else value


def _source_timeline(settings: Settings, source_through_date: str) -> SourceTimeline:
    through = date.fromisoformat(source_through_date)
    if through.isoformat() != source_through_date:
        raise ValueError("Source through date must use YYYY-MM-DD")
    if through > datetime.now(ZoneInfo("America/El_Salvador")).date():
        raise ValueError("Historical tag import cannot use a future Arissto day")
    digest = hashlib.sha256()
    count = 0
    with source_connection(settings.source) as conn:
        duplicate_closes = select_rows(conn, """
            SELECT FECHA_OPERACION,COUNT(*) AS N
              FROM dbo.CIERRE_DIARIO
             WHERE ID_EMPRESA='001' AND CIERRE='1' AND FECHA_OPERACION<=?
             GROUP BY FECHA_OPERACION HAVING COUNT(*)<>1
        """, (source_through_date,))
        if duplicate_closes:
            raise RuntimeError("Multiple completed Arissto closes on a historical date")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT h.ID_CREDITO,c.FECHA_OPERACION,c.ID_CIERRE_DIARIO,
                   h.CLASIFICACION,h.DIAS_MORA
              FROM dbo.CRD_HISTORICO_DIARIO h
              JOIN dbo.CIERRE_DIARIO c ON c.ID_CIERRE_DIARIO=h.ID_CIERRE_DIARIO
             WHERE c.ID_EMPRESA='001' AND c.CIERRE='1' AND c.FECHA_OPERACION<=?
               AND h.ID_ESTADO_CARTERA=1 AND h.ID_ESTADO_EMBARGO IS NULL
             ORDER BY h.ID_CREDITO,c.FECHA_OPERACION
        """, (source_through_date,))

        def facts():
            nonlocal count
            while batch := cursor.fetchmany(5000):
                for source_id, close_date, close_id, category, dpd in batch:
                    source_id = str(source_id).strip()
                    category = str(category).strip()
                    day = _date(close_date)
                    days = int(dpd) if dpd is not None else None
                    digest.update(json.dumps((source_id, day.isoformat(), str(close_id).strip(), category, days),
                                             separators=(",", ":")).encode() + b"\n")
                    count += 1
                    yield DailyClassification(source_id, day, category, days)

        intervals = list(compress_sorted_classifications(facts(), source_through_date=through))
    if count == 0:
        raise RuntimeError("No eligible rows in completed Arissto closes through selected date")
    return SourceTimeline(through, count, digest.hexdigest(), intervals)


def _catalog(conn: Any, settings: Settings) -> tuple[dict[str, int], dict[str, int], int]:
    if not conn.execute("SELECT to_regclass('public.credesal_loan_delinquency_tag_source') IS NOT NULL").fetchone()[0]:
        raise RuntimeError("Fineract delinquency tag provenance migration has not run")
    loans = conn.execute("SELECT external_id,id FROM m_loan WHERE external_id LIKE 'ARISSTO:CRD:%%'").fetchall()
    mapping = {str(external).split(":")[-1]: int(identifier) for external, identifier in loans}
    if len(mapping) != len(loans):
        raise RuntimeError("Duplicate Arissto loan mapping in Fineract")
    rows = conn.execute("SELECT classification,id FROM m_delinquency_range WHERE classification = ANY(%s)",
                        (list(CLASSIFICATIONS.values()),)).fetchall()
    ranges = {str(label): int(identifier) for label, identifier in rows}
    if len(rows) != len(CLASSIFICATIONS) or len(ranges) != len(CLASSIFICATIONS):
        raise RuntimeError("Fineract must have one range for each Arissto classification")
    users = conn.execute("SELECT id FROM m_appuser WHERE username=%s", (settings.target.api_user,)).fetchall()
    if len(users) != 1:
        raise RuntimeError("Selected Fineract API user must resolve to one audit user")
    return mapping, ranges, int(users[0][0])


def _native_intervals(timeline: SourceTimeline, loans: dict[str, int], ranges: dict[str, int],
                      quarantined_ids: frozenset[str] = frozenset()) -> tuple[list[NativeInterval], list[str], list[str]]:
    result: list[NativeInterval] = []
    unmapped: set[str] = set()
    excluded: set[str] = set()
    for interval in timeline.intervals:
        if interval.source_loan_id in quarantined_ids:
            if interval.source_loan_id in loans:
                raise RuntimeError(f"Quarantined source loan {interval.source_loan_id} has a native loan mapping")
            excluded.add(interval.source_loan_id)
            continue
        loan_id = loans.get(interval.source_loan_id)
        if loan_id is None:
            unmapped.add(interval.source_loan_id)
            continue
        key = (interval.source_loan_id, interval.classification,
               interval.added_on_date.isoformat(), interval.lifted_on_date.isoformat())
        interval_hash = hashlib.sha256(json.dumps(key, separators=(",", ":")).encode()).hexdigest()
        result.append(NativeInterval(interval.source_loan_id, loan_id, ranges[interval.classification],
                                     interval.classification, interval.added_on_date,
                                     interval.lifted_on_date, interval_hash))
    return result, sorted(unmapped), sorted(excluded)


def _existing(conn: Any, loan_ids: list[int], source_through_date: date) -> tuple[list[tuple[Any, ...]], tuple[Any, ...] | None]:
    tags = conn.execute("""
        SELECT h.id,h.loan_id,h.delinquency_range_id,h.addedon_date,h.liftedon_date,
               p.source_loan_id,p.added_on_date,p.lifted_on_date,p.classification,p.interval_hash
          FROM m_loan_delinquency_tag_history h
          LEFT JOIN credesal_loan_delinquency_tag_source p ON p.tag_history_id=h.id
          LEFT JOIN m_loan l ON l.id=h.loan_id
         WHERE h.loan_id=ANY(%s) OR p.source_system=%s
            OR (l.external_id LIKE 'ARISSTO:CRD:%%' AND h.addedon_date<=%s)
         ORDER BY h.loan_id,h.addedon_date,h.id
    """, (loan_ids, SOURCE_SYSTEM, source_through_date)).fetchall()
    manifest = conn.execute("""
        SELECT source_through_date,source_row_count,source_hash,source_interval_count,
               imported_interval_count,unmapped_source_loan_count
          FROM credesal_loan_delinquency_history_manifest WHERE source_system=%s
    """, (SOURCE_SYSTEM,)).fetchone()
    return tags, manifest


def _native_handoff_candidates(tags: list[tuple[Any, ...]], source_through_date: date) -> list[tuple[int, int, int]]:
    """Freeze native tags born on the final Arissto-owned day.

    Empty same-day native transitions carry no classification interval. Other
    positive native intervals in Arissto-owned time require separate review.
    """
    candidates: list[tuple[int, int, int]] = []
    for tag_id, loan_id, range_id, added, lifted, source_id, *_ in tags:
        added = _date(added)
        lifted = _date(lifted) if lifted is not None else None
        if source_id is not None or added > source_through_date:
            continue
        if lifted is not None and lifted <= added:
            continue
        if added == source_through_date and (lifted is None or lifted == source_through_date + timedelta(days=1)):
            candidates.append((int(tag_id), int(loan_id), int(range_id)))
        else:
            raise RuntimeError(f"Unreviewed native delinquency interval in Arissto-owned dates: tag {tag_id}")
    return sorted(candidates)


def _verify_native_handoff(conn: Any, candidates: list[tuple[int, int, int]], fineract_starts: date) -> bool:
    if not candidates:
        return True
    rows = conn.execute("""
        SELECT h.id,h.loan_id,h.delinquency_range_id,h.addedon_date,h.liftedon_date,p.tag_history_id
          FROM m_loan_delinquency_tag_history h
          LEFT JOIN credesal_loan_delinquency_tag_source p ON p.tag_history_id=h.id
         WHERE h.id=ANY(%s)
    """, ([item[0] for item in candidates],)).fetchall()
    actual = {(int(tag_id), int(loan_id), int(range_id)) for tag_id, loan_id, range_id,
              added, lifted, provenance in rows
              if _date(added) == fineract_starts and (lifted is None or _date(lifted) >= fineract_starts)
              and provenance is None}
    return len(rows) == len(candidates) and actual == set(candidates)


def _compare(expected: list[NativeInterval], tags: list[tuple[Any, ...]]) -> tuple[list[NativeInterval], int]:
    wanted = {row.key: row for row in expected}
    if len(wanted) != len(expected):
        raise RuntimeError("Duplicate expected historical interval start")
    by_loan: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
    sourced: set[tuple[str, date]] = set()
    for tag in tags:
        _, loan_id, range_id, added, lifted, source_id, source_added, source_lifted, label, row_hash = tag
        by_loan[int(loan_id)].append(tag)
        if source_id is None:
            continue
        key = (str(source_id), _date(source_added))
        item = wanted.get(key)
        if item is None or key in sourced or (item.loan_id, item.range_id, item.added_on_date,
                                               item.lifted_on_date, item.classification, item.interval_hash) != (
                                                   int(loan_id), int(range_id), _date(added), _date(lifted),
                                                   str(label), str(row_hash).strip()):
            raise RuntimeError("Existing source-tag provenance conflicts with Arissto timeline")
        if _date(source_lifted) != item.lifted_on_date:
            raise RuntimeError("Existing source-tag interval end conflicts with Arissto timeline")
        sourced.add(key)
    missing = [row for row in expected if row.key not in sourced]
    overlapping_native: set[tuple[int, str]] = set()
    for item in expected:
        for tag in by_loan[item.loan_id]:
            _, _, _, added, lifted, source_id, source_added, *_ = tag
            if source_id is not None and (str(source_id), _date(source_added)) == item.key:
                continue
            # A native same-day add/lift records a transition with an empty
            # interval; it cannot overlap an Arissto historical interval.
            if lifted is not None and _date(lifted) <= _date(added):
                continue
            if _date(added) < item.lifted_on_date and (lifted is None or _date(lifted) > item.added_on_date):
                overlapping_native.add((int(tag[0]), item.source_loan_id))
    if overlapping_native:
        loan_ids = sorted({loan_id for _, loan_id in overlapping_native}, key=int)
        raise RuntimeError(
            "Native delinquency tag overlaps Arissto history: "
            f"{len(overlapping_native)} native tags across {len(loan_ids)} loans; "
            f"source loan examples {','.join(loan_ids[:10])}. "
            "Review exact-match provenance and cutoff-date ownership before resuming."
        )
    return missing, len(sourced)


def _manifest_values(timeline: SourceTimeline, mapped_count: int, unmapped_count: int) -> tuple[Any, ...]:
    return (timeline.source_through_date, timeline.source_rows, timeline.source_hash,
            len(timeline.intervals), mapped_count, unmapped_count)


def _check_manifest(manifest: tuple[Any, ...] | None, expected: tuple[Any, ...], unchanged: int) -> None:
    if manifest is not None and tuple(manifest[:4]) != expected[:4]:
        raise RuntimeError("Accepted native delinquency history manifest conflicts with source timeline")
    if manifest is None and unchanged:
        raise RuntimeError("Source-tag rows exist without an accepted manifest")
    if manifest is not None and unchanged != int(manifest[4]):
        raise RuntimeError("Accepted native delinquency history count conflicts with tag provenance")


def _snapshot(settings: Settings, source_through_date: str, conn: Any) -> tuple[SourceTimeline, list[NativeInterval], list[str], list[str], LoanQuarantine, int, list[NativeInterval], int, list[tuple[int, int, int]]]:
    timeline = _source_timeline(settings, source_through_date)
    quarantine = _loan_quarantine(settings)
    loans, ranges, user_id = _catalog(conn, settings)
    expected, unmapped, excluded = _native_intervals(timeline, loans, ranges, quarantine.source_ids)
    tags, manifest = _existing(conn, sorted({row.loan_id for row in expected}), timeline.source_through_date)
    handoff = _native_handoff_candidates(tags, timeline.source_through_date)
    handoff_ids = {tag_id for tag_id, _, _ in handoff}
    missing, unchanged = _compare(expected, [tag for tag in tags if int(tag[0]) not in handoff_ids])
    _check_manifest(manifest, _manifest_values(timeline, len(expected), len(unmapped)), unchanged)
    return timeline, expected, unmapped, excluded, quarantine, user_id, missing, unchanged, handoff


def inspect(settings: Settings, source_through_date: str) -> dict[str, Any]:
    settings.target.assert_expected_host()
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for native delinquency history")
    with postgres_connection(settings.target.pg_url) as conn:
        timeline, expected, unmapped, excluded, quarantine, _, missing, unchanged, handoff = _snapshot(
            settings, source_through_date, conn
        )
    return {
        "block": BLOCK, "ready": True, "source_through_date": source_through_date,
        "source_rows": timeline.source_rows, "source_intervals": len(timeline.intervals),
        "mapped_intervals": len(expected), "create_count": len(missing),
        "unchanged_count": unchanged, "native_handoff_count": len(handoff),
        "unmapped_source_loans": len(unmapped),
        "excluded_quarantined_loans": len(excluded),
        "loan_quarantine_run": quarantine.run_id,
    }


def build_plan(settings: Settings, state: State, source_through_date: str) -> tuple[str, dict[str, Any]]:
    settings.target.assert_expected_host()
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for native delinquency history")
    with postgres_connection(settings.target.pg_url) as conn:
        timeline, expected, unmapped, excluded, quarantine, _, missing, unchanged, handoff = _snapshot(
            settings, source_through_date, conn)
    document = {
        "version": 1, "block": BLOCK, "source_through_date": source_through_date,
        "fineract_starts": (timeline.source_through_date + timedelta(days=1)).isoformat(),
        "source_rows": timeline.source_rows, "source_hash": timeline.source_hash,
        "source_intervals": len(timeline.intervals), "mapped_intervals": len(expected),
        "unmapped_source_loans": len(unmapped), "unmapped_source_ids": unmapped[:50],
        "excluded_quarantined_loans": len(excluded), "excluded_quarantined_ids": excluded,
        "loan_quarantine_cycle": quarantine.cycle_id, "loan_quarantine_run": quarantine.run_id,
        "loan_quarantine_hash": quarantine.digest,
        "create_count": len(missing), "unchanged_count": unchanged,
        "native_handoff_tags": handoff, "native_handoff_count": len(handoff),
        "target_fingerprint": settings.target.fingerprint,
    }
    plan_id = state.save_plan(settings.target.fingerprint, BLOCK, source_fingerprint(settings.source), POLICY, document)
    return plan_id, document


def _assert_plan(settings: Settings, state: State, plan_id: str) -> dict[str, Any]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Delinquency history plan belongs to another block or target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source) or plan["contract_hash"] != POLICY:
        raise RuntimeError("Delinquency history plan source or contract changed")
    return plan


def apply_plan(settings: Settings, state: State, plan_id: str, confirmation: str | None = None) -> tuple[str, dict[str, int]]:
    settings.target.assert_expected_host()
    plan = _assert_plan(settings, state, plan_id)
    doc = plan["document"]
    if settings.target.name == "prod" and confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for native delinquency history")
    run_id = state.start_run(plan)
    try:
        import psycopg
        with psycopg.connect(settings.target.pg_url, autocommit=False) as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            writer = ControlledSqlWriter(conn, BLOCK)
            with writer.entity_transaction(WRITE_OPERATION):
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (BLOCK,))
                timeline, expected, unmapped, excluded, quarantine, user_id, missing, unchanged, handoff = _snapshot(
                    settings, doc["source_through_date"], conn)
                if (timeline.source_rows, timeline.source_hash, len(timeline.intervals), len(expected),
                    len(unmapped), unmapped[:50], excluded, quarantine.cycle_id, quarantine.run_id,
                    quarantine.digest, len(missing), unchanged, handoff) != (
                        doc["source_rows"], doc["source_hash"], doc["source_intervals"],
                        doc["mapped_intervals"], doc["unmapped_source_loans"], doc["unmapped_source_ids"],
                        doc["excluded_quarantined_ids"], doc["loan_quarantine_cycle"],
                        doc["loan_quarantine_run"], doc["loan_quarantine_hash"],
                        doc["create_count"], doc["unchanged_count"],
                        [tuple(tag) for tag in doc["native_handoff_tags"]]):
                    raise RuntimeError("Source or target changed since the delinquency history plan")
                observed = datetime.now(timezone.utc)
                fineract_starts = timeline.source_through_date + timedelta(days=1)
                if handoff:
                    shifted = conn.execute("""
                        UPDATE m_loan_delinquency_tag_history h
                           SET addedon_date=%s,last_modified_by=%s,last_modified_on_utc=%s,
                               version=h.version+1
                          FROM m_loan l
                         WHERE h.loan_id=l.id AND h.id=ANY(%s)
                           AND l.external_id LIKE 'ARISSTO:CRD:%%'
                           AND h.addedon_date=%s
                           AND (h.liftedon_date IS NULL OR h.liftedon_date=%s)
                           AND NOT EXISTS (
                               SELECT 1 FROM credesal_loan_delinquency_tag_source p
                                WHERE p.tag_history_id=h.id
                           )
                    """, (fineract_starts, user_id, observed, [tag[0] for tag in handoff],
                          timeline.source_through_date, fineract_starts)).rowcount
                    if shifted != len(handoff) or not _verify_native_handoff(conn, handoff, fineract_starts):
                        raise RuntimeError("Native delinquency handoff changed during apply")
                for item in missing:
                    tag_id = conn.execute("""
                        INSERT INTO m_loan_delinquency_tag_history (
                            delinquency_range_id,loan_id,addedon_date,liftedon_date,
                            created_by,created_on_utc,version,last_modified_by,last_modified_on_utc
                        ) VALUES (%s,%s,%s,%s,%s,%s,0,%s,%s) RETURNING id
                    """, (item.range_id, item.loan_id, item.added_on_date, item.lifted_on_date,
                          user_id, observed, user_id, observed)).fetchone()[0]
                    conn.execute("""
                        INSERT INTO credesal_loan_delinquency_tag_source (
                            tag_history_id,source_system,source_loan_id,added_on_date,lifted_on_date,
                            classification,interval_hash,observed_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (tag_id, SOURCE_SYSTEM, item.source_loan_id, item.added_on_date,
                          item.lifted_on_date, item.classification, item.interval_hash, observed))
                tags, manifest = _existing(conn, sorted({row.loan_id for row in expected}), timeline.source_through_date)
                remaining, verified = _compare(expected, tags)
                if remaining or verified != len(expected) or not _verify_native_handoff(conn, handoff, fineract_starts):
                    raise RuntimeError("Native delinquency tag post-write verification failed")
                if missing or manifest is None or int(manifest[5]) != len(unmapped):
                    conn.execute("""
                        INSERT INTO credesal_loan_delinquency_history_manifest (
                            source_system,source_through_date,source_row_count,source_hash,
                            source_interval_count,imported_interval_count,unmapped_source_loan_count,accepted_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (source_system) DO UPDATE SET
                            imported_interval_count=EXCLUDED.imported_interval_count,
                            unmapped_source_loan_count=EXCLUDED.unmapped_source_loan_count,
                            accepted_at=EXCLUDED.accepted_at
                    """, (SOURCE_SYSTEM, timeline.source_through_date, timeline.source_rows,
                          timeline.source_hash, len(timeline.intervals), len(expected), len(unmapped), observed))
        summary = {"created": len(missing), "unchanged": unchanged, "native_handoff_shifted": len(handoff),
                   "unmapped_source_loans": len(unmapped),
                   "excluded_quarantined_loans": len(excluded)}
        state.finish_run(run_id, "completed", summary)
        return run_id, summary
    except Exception as exc:
        state.finish_run(run_id, "failed", {"error": type(exc).__name__})
        raise


def reconcile(settings: Settings, state: State, run_id: str) -> dict[str, Any]:
    settings.target.assert_expected_host()
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Delinquency history run belongs to another block or target")
    plan = _assert_plan(settings, state, run["plan_id"])
    doc = plan["document"]
    with postgres_connection(settings.target.pg_url or "") as conn:
        timeline, expected, unmapped, excluded, quarantine, _, missing, unchanged, handoff = _snapshot(
            settings, doc["source_through_date"], conn)
        handoff_ok = not handoff and _verify_native_handoff(
            conn, [tuple(tag) for tag in doc["native_handoff_tags"]], timeline.source_through_date + timedelta(days=1))
    ok = (handoff_ok and not missing and unchanged == len(expected) and
          (timeline.source_rows, timeline.source_hash, len(timeline.intervals), len(unmapped),
           unmapped[:50], excluded, quarantine.cycle_id, quarantine.run_id, quarantine.digest) ==
          (doc["source_rows"], doc["source_hash"], doc["source_intervals"], doc["unmapped_source_loans"],
           doc["unmapped_source_ids"], doc["excluded_quarantined_ids"],
           doc["loan_quarantine_cycle"], doc["loan_quarantine_run"], doc["loan_quarantine_hash"]))
    result = {"ok": ok, "source_through_date": doc["source_through_date"],
              "source_rows": timeline.source_rows, "source_intervals": len(timeline.intervals),
              "mapped_intervals": len(expected), "verified_intervals": unchanged,
              "native_handoff_verified": len(doc["native_handoff_tags"]) if handoff_ok else 0,
              "unmapped_source_loans": len(unmapped), "excluded_quarantined_loans": len(excluded),
              "loan_quarantine_run": quarantine.run_id, "difference_count": len(missing)}
    state.record_reconciliation(run_id, result)
    return result
