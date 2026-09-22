"""Local, read-only snapshots of Arissto close-of-business execution.

Every invocation is persisted, including failed connections. Source timestamps
are stored as UTC and rendered in America/El_Salvador for operator output.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .arissto import select_rows, source_connection, source_fingerprint
from .config import SourceConfig


LOCAL_TIMEZONE = ZoneInfo("America/El_Salvador")
PAUSE_THRESHOLD = timedelta(minutes=15)


COB_SCHEMA = """
CREATE TABLE IF NOT EXISTS cob_monitor_runs (
 id TEXT PRIMARY KEY,
 source_fingerprint TEXT,
 started_at_utc TEXT NOT NULL,
 finished_at_utc TEXT,
 requested_operation_date TEXT,
 database_reachable INTEGER,
 source_server_time_utc TEXT,
 error_category TEXT,
 error_message_safe TEXT
);
CREATE TABLE IF NOT EXISTS cob_close_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 monitor_run_id TEXT NOT NULL UNIQUE,
 source_fingerprint TEXT NOT NULL,
 company_id TEXT NOT NULL,
 operation_date TEXT NOT NULL,
 close_id TEXT NOT NULL,
 observed_at_utc TEXT NOT NULL,
 source_server_time_utc TEXT NOT NULL,
 derived_state TEXT NOT NULL,
 global_close_status TEXT NOT NULL,
 expected_module_count INTEGER NOT NULL,
 module_count INTEGER NOT NULL,
 closed_module_count INTEGER NOT NULL,
 open_module_count INTEGER NOT NULL,
 expected_process_count INTEGER NOT NULL,
 process_count INTEGER NOT NULL,
 started_process_count INTEGER NOT NULL,
 finished_process_count INTEGER NOT NULL,
 successful_process_count INTEGER NOT NULL,
 locked_process_count INTEGER NOT NULL,
 first_process_start_utc TEXT,
 latest_process_finish_utc TEXT,
 previous_open_modules_finish_utc TEXT,
 mayorization_present INTEGER NOT NULL,
 mayorization_created_at_utc TEXT,
 loan_accrual_count INTEGER NOT NULL,
 loan_accrual_first_utc TEXT,
 loan_accrual_last_utc TEXT,
 share_yield_count INTEGER NOT NULL,
 share_yield_first_utc TEXT,
 share_yield_last_utc TEXT,
 ready_to_sync INTEGER NOT NULL,
 raw_summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cob_process_snapshots (
 close_snapshot_id INTEGER NOT NULL,
 process_id TEXT NOT NULL,
 system_code TEXT NOT NULL,
 process_order TEXT,
 process_name TEXT NOT NULL,
 process_status TEXT,
 started_at_utc TEXT,
 finished_at_utc TEXT,
 lock_flag INTEGER NOT NULL,
 PRIMARY KEY(close_snapshot_id, process_id, system_code)
);
CREATE TABLE IF NOT EXISTS cob_timeline_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_key TEXT NOT NULL UNIQUE,
 source_fingerprint TEXT NOT NULL,
 close_id TEXT NOT NULL,
 operation_date TEXT NOT NULL,
 event_type TEXT NOT NULL,
 event_at_utc TEXT NOT NULL,
 first_observed_run_id TEXT NOT NULL,
 evidence_source TEXT NOT NULL,
 confidence TEXT NOT NULL,
 details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS cob_gap_intervals (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 gap_key TEXT NOT NULL UNIQUE,
 source_fingerprint TEXT,
 close_id TEXT,
 operation_date TEXT,
 gap_type TEXT NOT NULL,
 started_at_utc TEXT NOT NULL,
 ended_at_utc TEXT,
 detected_by_run_id TEXT NOT NULL,
 closed_by_run_id TEXT,
 confidence TEXT NOT NULL,
 overlaps_shutdown_window INTEGER NOT NULL DEFAULT 0,
 details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS cob_snapshots_date_idx
 ON cob_close_snapshots(source_fingerprint, operation_date, observed_at_utc);
CREATE INDEX IF NOT EXISTS cob_events_date_idx
 ON cob_timeline_events(source_fingerprint, operation_date, event_at_utc);
CREATE INDEX IF NOT EXISTS cob_gaps_date_idx
 ON cob_gap_intervals(source_fingerprint, operation_date, started_at_utc);
"""


DAILY_CLOSE_SQL = """
WITH selected AS (
    SELECT TOP (1) d.ID_EMPRESA, d.ID_CIERRE_DIARIO, d.FECHA_OPERACION, d.CIERRE
    FROM dbo.CIERRE_DIARIO AS d
    WHERE (? IS NULL OR CAST(d.FECHA_OPERACION AS date) = CAST(? AS date))
    ORDER BY d.FECHA_OPERACION DESC, d.ID_CIERRE_DIARIO DESC
), modules AS (
    SELECT m.ID_EMPRESA, m.ID_CIERRE_DIARIO,
           COUNT_BIG(*) AS module_count,
           SUM(CASE WHEN m.CIERRE = '1' THEN 1 ELSE 0 END) AS closed_modules,
           SUM(CASE WHEN m.CIERRE = '0' THEN 1 ELSE 0 END) AS open_modules,
           SUM(CASE WHEN m.CIERRE IS NULL THEN 1 ELSE 0 END) AS null_modules
    FROM dbo.CIERRE_MODULO AS m
    JOIN selected AS d
      ON d.ID_EMPRESA = m.ID_EMPRESA
     AND d.ID_CIERRE_DIARIO = m.ID_CIERRE_DIARIO
    GROUP BY m.ID_EMPRESA, m.ID_CIERRE_DIARIO
), previous_open AS (
    SELECT MAX(COALESCE(b.HORA_FIN, b.FinishProcess)) AS previous_open_modules_finish
    FROM selected AS current_day
    JOIN dbo.CIERRE_DIARIO AS previous_day
      ON previous_day.ID_EMPRESA = current_day.ID_EMPRESA
     AND previous_day.FECHA_OPERACION < current_day.FECHA_OPERACION
    JOIN dbo.PROCESOS_BITACORA AS b
      ON b.ID_EMPRESA = previous_day.ID_EMPRESA
     AND b.ID_CIERRE_DIARIO = previous_day.ID_CIERRE_DIARIO
    JOIN dbo.PROCESOS_CIERRE AS p
      ON p.ID_EMPRESA = b.ID_EMPRESA
     AND p.ID_PROCESO = b.ID_PROCESO
     AND p.CODIGO_SISTEMA = b.CODIGO_SISTEMA
    WHERE RTRIM(p.NOMBRE_PROCESO) = 'APERTURA DE MODULOS'
)
SELECT RTRIM(d.ID_EMPRESA) AS company_id,
       RTRIM(d.ID_CIERRE_DIARIO) AS close_id,
       CAST(d.FECHA_OPERACION AS date) AS operation_date,
       RTRIM(d.CIERRE) AS global_close_status,
       SYSUTCDATETIME() AS source_server_time_utc,
       (SELECT COUNT_BIG(*) FROM dbo.MODULOS_SUCURSAL AS c
        WHERE c.ID_EMPRESA = d.ID_EMPRESA AND c.ACTIVADO = '1') AS expected_module_count,
       COALESCE(m.module_count, 0) AS module_count,
       COALESCE(m.closed_modules, 0) AS closed_module_count,
       COALESCE(m.open_modules, 0) AS open_module_count,
       COALESCE(m.null_modules, 0) AS null_module_count,
       (SELECT COUNT_BIG(*) FROM dbo.PROCESOS_CIERRE AS p
        WHERE p.ID_EMPRESA = d.ID_EMPRESA) AS expected_process_count,
       previous_open.previous_open_modules_finish
FROM selected AS d
LEFT JOIN modules AS m
  ON m.ID_EMPRESA = d.ID_EMPRESA
 AND m.ID_CIERRE_DIARIO = d.ID_CIERRE_DIARIO
CROSS JOIN previous_open
"""


PROCESS_SQL = """
WITH selected AS (
    SELECT TOP (1) d.ID_EMPRESA, d.ID_CIERRE_DIARIO
    FROM dbo.CIERRE_DIARIO AS d
    WHERE (? IS NULL OR CAST(d.FECHA_OPERACION AS date) = CAST(? AS date))
    ORDER BY d.FECHA_OPERACION DESC, d.ID_CIERRE_DIARIO DESC
)
SELECT RTRIM(CAST(b.ID_PROCESO AS varchar(32))) AS process_id,
       RTRIM(CAST(b.CODIGO_SISTEMA AS varchar(32))) AS system_code,
       RTRIM(CAST(p.ORDEN AS varchar(32))) AS process_order,
       RTRIM(p.NOMBRE_PROCESO) AS process_name,
       RTRIM(b.ESTADO_PROCESO) AS process_status,
       COALESCE(b.HORA_INICIO, b.StartProcess) AS started_at_utc,
       COALESCE(b.HORA_FIN, b.FinishProcess) AS finished_at_utc,
       COALESCE(b.[Lock], 0) AS lock_flag
FROM selected AS d
JOIN dbo.PROCESOS_BITACORA AS b
  ON b.ID_EMPRESA = d.ID_EMPRESA
 AND b.ID_CIERRE_DIARIO = d.ID_CIERRE_DIARIO
JOIN dbo.PROCESOS_CIERRE AS p
  ON p.ID_EMPRESA = b.ID_EMPRESA
 AND p.ID_PROCESO = b.ID_PROCESO
 AND p.CODIGO_SISTEMA = b.CODIGO_SISTEMA
ORDER BY COALESCE(b.HORA_INICIO, b.StartProcess), p.ORDEN,
         b.CODIGO_SISTEMA, b.ID_PROCESO
"""


MAYORIZATION_SQL = """
WITH selected AS (
    SELECT TOP (1) d.ID_EMPRESA, d.ID_CIERRE_DIARIO
    FROM dbo.CIERRE_DIARIO AS d
    WHERE (? IS NULL OR CAST(d.FECHA_OPERACION AS date) = CAST(? AS date))
    ORDER BY d.FECHA_OPERACION DESC, d.ID_CIERRE_DIARIO DESC
)
SELECT COUNT_BIG(*) AS mayorization_rows,
       MIN(h.DT_CREO) AS first_mayorization_created_at_utc,
       MAX(h.DT_CREO) AS last_mayorization_created_at_utc
FROM selected AS d
JOIN dbo.CNT_HIST_MAYORIZACION AS h
  ON h.ID_EMPRESA = d.ID_EMPRESA
 AND (h.ID_CIERRE_DIARIO = d.ID_CIERRE_DIARIO
      OR d.ID_CIERRE_DIARIO BETWEEN h.ID_CIERRE_INI AND h.ID_CIERRE_FIN)
"""


ACCRUAL_SQL = """
WITH selected AS (
    SELECT TOP (1) d.ID_CIERRE_DIARIO
    FROM dbo.CIERRE_DIARIO AS d
    WHERE (? IS NULL OR CAST(d.FECHA_OPERACION AS date) = CAST(? AS date))
    ORDER BY d.FECHA_OPERACION DESC, d.ID_CIERRE_DIARIO DESC
)
SELECT f.ID_TIPO_PRODUCTO AS product_type_id,
       COUNT_BIG(*) AS accrual_count,
       MIN(f.DT_CREO) AS first_created_at_utc,
       MAX(f.DT_CREO) AS last_created_at_utc
FROM selected AS d
JOIN dbo.FNC_PROVISIONES AS f
  ON f.ID_CIERRE_DIARIO = d.ID_CIERRE_DIARIO
WHERE f.ID_TIPO_PRODUCTO IN (3, 4)
GROUP BY f.ID_TIPO_PRODUCTO
ORDER BY f.ID_TIPO_PRODUCTO
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime | str | None) -> str | None:
    parsed = _aware_utc(value)
    return parsed.isoformat() if parsed else None


def _local_text(value: datetime | str | None) -> str | None:
    parsed = _aware_utc(value)
    return parsed.astimezone(LOCAL_TIMEZONE).isoformat() if parsed else None


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _safe_error(exc: Exception) -> str:
    message = re.sub(r"(?i)(PWD|PASSWORD)=[^;\s]+", r"\1=<redacted>", str(exc))
    return message[:1000]


def _query_parameters(operation_date: date | None) -> tuple[str | None, str | None]:
    value = operation_date.isoformat() if operation_date else None
    return value, value


def fetch_source_snapshot(config: SourceConfig, operation_date: date | None) -> dict[str, Any]:
    parameters = _query_parameters(operation_date)
    with source_connection(config) as conn:
        daily_rows = select_rows(conn, DAILY_CLOSE_SQL, parameters)
        if not daily_rows:
            label = operation_date.isoformat() if operation_date else "latest"
            raise ValueError(f"Arissto has no CIERRE_DIARIO row for {label}")
        return {
            "daily": daily_rows[0],
            "processes": select_rows(conn, PROCESS_SQL, parameters),
            "mayorization": select_rows(conn, MAYORIZATION_SQL, parameters)[0],
            "accruals": select_rows(conn, ACCRUAL_SQL, parameters),
        }


def _derive_state(summary: dict[str, Any], source_now: datetime) -> str:
    global_closed = summary["global_close_status"] == "1"
    processes_complete = (
        summary["expected_process_count"] > 0
        and summary["process_count"] == summary["expected_process_count"]
        and summary["finished_process_count"] == summary["expected_process_count"]
        and summary["successful_process_count"] == summary["expected_process_count"]
        and summary["locked_process_count"] == 0
    )
    modules_complete = (
        summary["expected_module_count"] > 0
        and summary["module_count"] == summary["expected_module_count"]
        and summary["closed_module_count"] == summary["expected_module_count"]
        and summary["open_module_count"] == 0
    )
    if global_closed:
        if processes_complete and modules_complete and summary["mayorization_present"]:
            return "COMPLETE"
        return "INCONSISTENT"
    if summary["started_process_count"] == 0:
        return "NOT_STARTED"
    latest = _aware_utc(summary["latest_process_activity_utc"])
    if latest and source_now - latest >= PAUSE_THRESHOLD:
        return "PAUSED"
    return "RUNNING"


def build_snapshot(payload: dict[str, Any], observed_at: datetime) -> dict[str, Any]:
    daily = payload["daily"]
    processes = payload["processes"]
    mayorization = payload["mayorization"]
    accruals = {int(item["product_type_id"]): item for item in payload["accruals"]}
    starts = [_aware_utc(item.get("started_at_utc")) for item in processes]
    finishes = [_aware_utc(item.get("finished_at_utc")) for item in processes]
    starts = [item for item in starts if item]
    finishes = [item for item in finishes if item]
    activity = starts + finishes
    loan = accruals.get(3, {})
    shares = accruals.get(4, {})
    source_now = _aware_utc(daily["source_server_time_utc"])
    assert source_now is not None
    summary: dict[str, Any] = {
        "company_id": str(daily["company_id"]).strip(),
        "operation_date": str(daily["operation_date"]),
        "close_id": str(daily["close_id"]).strip(),
        "observed_at_utc": _utc_text(observed_at),
        "source_server_time_utc": _utc_text(source_now),
        "global_close_status": str(daily["global_close_status"]).strip(),
        "expected_module_count": int(daily["expected_module_count"] or 0),
        "module_count": int(daily["module_count"] or 0),
        "closed_module_count": int(daily["closed_module_count"] or 0),
        "open_module_count": int(daily["open_module_count"] or 0),
        "null_module_count": int(daily["null_module_count"] or 0),
        "expected_process_count": int(daily["expected_process_count"] or 0),
        "process_count": len(processes),
        "started_process_count": len(starts),
        "finished_process_count": len(finishes),
        "successful_process_count": sum(
            str(item.get("process_status") or "").strip() == "1" for item in processes
        ),
        "locked_process_count": sum(bool(item.get("lock_flag")) for item in processes),
        "first_process_start_utc": _utc_text(min(starts) if starts else None),
        "latest_process_finish_utc": _utc_text(max(finishes) if finishes else None),
        "latest_process_activity_utc": _utc_text(max(activity) if activity else None),
        "previous_open_modules_finish_utc": _utc_text(daily.get("previous_open_modules_finish")),
        "mayorization_present": int(mayorization.get("mayorization_rows") or 0) > 0,
        "mayorization_created_at_utc": _utc_text(mayorization.get("last_mayorization_created_at_utc")),
        "loan_accrual_count": int(loan.get("accrual_count") or 0),
        "loan_accrual_first_utc": _utc_text(loan.get("first_created_at_utc")),
        "loan_accrual_last_utc": _utc_text(loan.get("last_created_at_utc")),
        "share_yield_count": int(shares.get("accrual_count") or 0),
        "share_yield_first_utc": _utc_text(shares.get("first_created_at_utc")),
        "share_yield_last_utc": _utc_text(shares.get("last_created_at_utc")),
    }
    summary["state"] = _derive_state(summary, source_now)
    summary["ready_to_sync"] = summary["state"] == "COMPLETE"
    normalized_processes = [{
        "process_id": str(item["process_id"]).strip(),
        "system_code": str(item["system_code"]).strip(),
        "process_order": str(item.get("process_order") or "").strip() or None,
        "process_name": str(item["process_name"]).strip(),
        "process_status": str(item.get("process_status") or "").strip() or None,
        "started_at_utc": _utc_text(item.get("started_at_utc")),
        "finished_at_utc": _utc_text(item.get("finished_at_utc")),
        "lock_flag": bool(item.get("lock_flag")),
    } for item in processes]
    return {"summary": summary, "processes": normalized_processes}


def _overlaps_shutdown(started: datetime, ended: datetime) -> bool:
    local_start = started.astimezone(LOCAL_TIMEZONE)
    local_end = ended.astimezone(LOCAL_TIMEZONE)
    candidate = local_start.date() - timedelta(days=1)
    while candidate <= local_end.date():
        shutdown_start = datetime.combine(candidate, time(19, 0), LOCAL_TIMEZONE)
        shutdown_end = datetime.combine(candidate + timedelta(days=1), time(4, 0), LOCAL_TIMEZONE)
        if local_start < shutdown_end and local_end > shutdown_start:
            return True
        candidate += timedelta(days=1)
    return False


def remote_execution_gaps(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        (item for item in processes if item.get("started_at_utc")),
        key=lambda item: str(item["started_at_utc"]),
    )
    gaps: list[dict[str, Any]] = []
    previous_finish: datetime | None = None
    previous_name: str | None = None
    for item in ordered:
        started = _aware_utc(item["started_at_utc"])
        assert started is not None
        if previous_finish and started - previous_finish >= PAUSE_THRESHOLD:
            gaps.append({
                "gap_type": "REMOTE_EXECUTION_GAP",
                "started_at_utc": previous_finish.isoformat(),
                "ended_at_utc": started.isoformat(),
                "confidence": "exact-inactivity-inferred-cause",
                "overlaps_shutdown_window": _overlaps_shutdown(previous_finish, started),
                "details": {
                    "previous_process": previous_name,
                    "next_process": item["process_name"],
                    "elapsed_seconds": int((started - previous_finish).total_seconds()),
                },
            })
        previous_finish = _aware_utc(item.get("finished_at_utc")) or started
        previous_name = item["process_name"]
    return gaps


class CobStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path.resolve()
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(COB_SCHEMA)
        columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(cob_close_snapshots)")
        }
        if "successful_process_count" not in columns:
            self.conn.execute(
                "ALTER TABLE cob_close_snapshots "
                "ADD COLUMN successful_process_count INTEGER NOT NULL DEFAULT 0"
            )
            self.conn.execute(
                "UPDATE cob_close_snapshots SET successful_process_count=("
                "SELECT COUNT(*) FROM cob_process_snapshots AS p "
                "WHERE p.close_snapshot_id=cob_close_snapshots.id AND p.process_status='1')"
            )
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def start_run(self, source: str | None, requested_date: date | None, started_at: datetime) -> str:
        run_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO cob_monitor_runs(id,source_fingerprint,started_at_utc,requested_operation_date) "
            "VALUES(?,?,?,?)",
            (run_id, source, _utc_text(started_at), requested_date.isoformat() if requested_date else None),
        )
        self.conn.commit()
        return run_id

    def finish_run(
        self, run_id: str, finished_at: datetime, reachable: bool,
        server_time: str | None = None, error: Exception | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE cob_monitor_runs SET finished_at_utc=?,database_reachable=?,"
            "source_server_time_utc=?,error_category=?,error_message_safe=? WHERE id=?",
            (_utc_text(finished_at), int(reachable), server_time,
             type(error).__name__ if error else None, _safe_error(error) if error else None, run_id),
        )
        self.conn.commit()

    def latest_successful_snapshot(self, source: str | None = None) -> dict[str, Any] | None:
        where = "WHERE source_fingerprint=?" if source else ""
        params: tuple[Any, ...] = (source,) if source else ()
        row = self.conn.execute(
            f"SELECT * FROM cob_close_snapshots {where} ORDER BY observed_at_utc DESC LIMIT 1", params
        ).fetchone()
        return dict(row) if row else None

    def _event(
        self, event_key: str, source: str, summary: dict[str, Any], event_type: str,
        event_at: str, run_id: str, evidence: str, confidence: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO cob_timeline_events("
            "event_key,source_fingerprint,close_id,operation_date,event_type,event_at_utc,"
            "first_observed_run_id,evidence_source,confidence,details_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (event_key, source, summary["close_id"], summary["operation_date"], event_type,
             event_at, run_id, evidence, confidence, _json(details or {})),
        )
        return cursor.rowcount > 0

    def _gap(
        self, gap_key: str, source: str | None, close_id: str | None,
        operation_date: str | None, gap: dict[str, Any], run_id: str,
    ) -> bool:
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO cob_gap_intervals("
            "gap_key,source_fingerprint,close_id,operation_date,gap_type,started_at_utc,ended_at_utc,"
            "detected_by_run_id,confidence,overlaps_shutdown_window,details_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (gap_key, source, close_id, operation_date, gap["gap_type"], gap["started_at_utc"],
             gap.get("ended_at_utc"), run_id, gap["confidence"],
             int(bool(gap.get("overlaps_shutdown_window"))), _json(gap.get("details", {}))),
        )
        return cursor.rowcount > 0

    def record_unreachable(self, run_id: str, source: str | None, started_at: datetime) -> None:
        previous = self.latest_successful_snapshot(source)
        existing = self.conn.execute(
            "SELECT id FROM cob_gap_intervals WHERE gap_type='CONFIRMED_DATABASE_OUTAGE' "
            "AND ended_at_utc IS NULL AND COALESCE(source_fingerprint,'')=COALESCE(?, '')", (source,),
        ).fetchone()
        if not existing:
            gap_key = f"outage:{source or 'unknown'}:{_utc_text(started_at)}"
            self._gap(gap_key, source,
                      str(previous["close_id"]) if previous else None,
                      str(previous["operation_date"]) if previous else None, {
                "gap_type": "CONFIRMED_DATABASE_OUTAGE", "started_at_utc": _utc_text(started_at),
                "ended_at_utc": None, "confidence": "confirmed-by-failed-connection",
                "overlaps_shutdown_window": False,
                "details": {"previous_state": previous["derived_state"] if previous else None},
            }, run_id)
            if previous and source:
                self._event(
                    f"{source}:{previous['close_id']}:DATABASE_UNREACHABLE:{_utc_text(started_at)}",
                    source, {
                        "close_id": str(previous["close_id"]),
                        "operation_date": str(previous["operation_date"]),
                    }, "DATABASE_UNREACHABLE", _utc_text(started_at), run_id,
                    "failed source connection", "confirmed-by-failed-connection",
                    {"previous_state": previous["derived_state"], "gap_key": gap_key},
                )
        self.conn.commit()

    def _close_outages(
        self, run_id: str, source: str, summary: dict[str, Any], ended_at: str,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM cob_gap_intervals WHERE gap_type='CONFIRMED_DATABASE_OUTAGE' "
            "AND ended_at_utc IS NULL AND source_fingerprint=?", (source,),
        ).fetchall()
        closed = []
        for row in rows:
            started = _aware_utc(row["started_at_utc"])
            ended = _aware_utc(ended_at)
            assert started and ended
            overlap = _overlaps_shutdown(started, ended)
            self.conn.execute(
                "UPDATE cob_gap_intervals SET close_id=COALESCE(close_id,?),"
                "operation_date=COALESCE(operation_date,?),ended_at_utc=?,closed_by_run_id=?,"
                "overlaps_shutdown_window=? WHERE id=?",
                (summary["close_id"], summary["operation_date"], ended_at, run_id, int(overlap), row["id"]),
            )
            value = dict(row)
            value.update({"close_id": row["close_id"] or summary["close_id"],
                          "operation_date": row["operation_date"] or summary["operation_date"],
                          "ended_at_utc": ended_at, "closed_by_run_id": run_id,
                          "overlaps_shutdown_window": int(overlap)})
            closed.append(value)
        return closed

    def record_snapshot(self, run_id: str, source: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        summary = snapshot["summary"]
        processes = snapshot["processes"]
        previous = self.conn.execute(
            "SELECT * FROM cob_close_snapshots WHERE source_fingerprint=? AND close_id=? "
            "ORDER BY observed_at_utc DESC LIMIT 1", (source, summary["close_id"]),
        ).fetchone()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.conn.execute(
                "INSERT INTO cob_close_snapshots("
                "monitor_run_id,source_fingerprint,company_id,operation_date,close_id,observed_at_utc,"
                "source_server_time_utc,derived_state,global_close_status,expected_module_count,module_count,"
                "closed_module_count,open_module_count,expected_process_count,process_count,started_process_count,"
                "finished_process_count,successful_process_count,locked_process_count,"
                "first_process_start_utc,latest_process_finish_utc,"
                "previous_open_modules_finish_utc,mayorization_present,mayorization_created_at_utc,"
                "loan_accrual_count,loan_accrual_first_utc,loan_accrual_last_utc,share_yield_count,"
                "share_yield_first_utc,share_yield_last_utc,ready_to_sync,raw_summary_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, source, summary["company_id"], summary["operation_date"], summary["close_id"],
                 summary["observed_at_utc"], summary["source_server_time_utc"], summary["state"],
                 summary["global_close_status"], summary["expected_module_count"], summary["module_count"],
                 summary["closed_module_count"], summary["open_module_count"],
                 summary["expected_process_count"], summary["process_count"],
                 summary["started_process_count"], summary["finished_process_count"],
                 summary["successful_process_count"], summary["locked_process_count"],
                 summary["first_process_start_utc"],
                 summary["latest_process_finish_utc"], summary["previous_open_modules_finish_utc"],
                 int(summary["mayorization_present"]), summary["mayorization_created_at_utc"],
                 summary["loan_accrual_count"], summary["loan_accrual_first_utc"],
                 summary["loan_accrual_last_utc"], summary["share_yield_count"],
                 summary["share_yield_first_utc"], summary["share_yield_last_utc"],
                 int(summary["ready_to_sync"]), _json(summary)),
            )
            snapshot_id = int(cursor.lastrowid)
            self.conn.executemany("INSERT INTO cob_process_snapshots VALUES(?,?,?,?,?,?,?,?,?)", [
                (snapshot_id, item["process_id"], item["system_code"], item["process_order"],
                 item["process_name"], item["process_status"], item["started_at_utc"],
                 item["finished_at_utc"], int(item["lock_flag"])) for item in processes
            ])
            new_events: list[str] = []
            if summary["previous_open_modules_finish_utc"] and self._event(
                f"{source}:{summary['close_id']}:BUSINESS_DAY_OPENED", source, summary,
                "BUSINESS_DAY_OPENED", summary["previous_open_modules_finish_utc"], run_id,
                "previous PROCESOS_BITACORA APERTURA DE MODULOS", "exact-source-timestamp",
            ):
                new_events.append("BUSINESS_DAY_OPENED")
            if summary["global_close_status"] == "0" and self._event(
                f"{source}:{summary['close_id']}:DAY_OBSERVED_OPEN", source, summary,
                "DAY_OBSERVED_OPEN", summary["observed_at_utc"], run_id,
                "CIERRE_DIARIO snapshot", "observed-boundary",
            ):
                new_events.append("DAY_OBSERVED_OPEN")
            if summary["first_process_start_utc"] and self._event(
                f"{source}:{summary['close_id']}:COB_STARTED", source, summary,
                "COB_STARTED", summary["first_process_start_utc"], run_id,
                "PROCESOS_BITACORA", "exact-source-timestamp",
            ):
                new_events.append("COB_STARTED")
            changed = previous is None or (
                int(previous["started_process_count"]) != summary["started_process_count"]
                or int(previous["finished_process_count"]) != summary["finished_process_count"]
                or previous["latest_process_finish_utc"] != summary["latest_process_finish_utc"]
            )
            if summary["started_process_count"] and changed:
                progress_key = (f"{source}:{summary['close_id']}:COB_PROGRESS:"
                                f"{summary['started_process_count']}:{summary['finished_process_count']}:"
                                f"{summary['latest_process_activity_utc']}")
                if self._event(
                    progress_key, source, summary, "COB_PROGRESS",
                    summary["latest_process_activity_utc"] or summary["observed_at_utc"], run_id,
                    "PROCESOS_BITACORA snapshot", "exact-counts-and-timestamps",
                    {"started": summary["started_process_count"],
                     "finished": summary["finished_process_count"],
                     "expected": summary["expected_process_count"]},
                ):
                    new_events.append("COB_PROGRESS")
            mayorization = next((item for item in processes
                                 if item["process_name"] == "MAYORIZACION CONTABLE"), None)
            if mayorization and mayorization["started_at_utc"] and self._event(
                f"{source}:{summary['close_id']}:MAYORIZATION_STARTED", source, summary,
                "MAYORIZATION_STARTED", mayorization["started_at_utc"], run_id,
                "PROCESOS_BITACORA", "exact-source-timestamp",
            ):
                new_events.append("MAYORIZATION_STARTED")
            if summary["state"] == "COMPLETE" and summary["latest_process_finish_utc"]:
                if self._event(
                    f"{source}:{summary['close_id']}:COB_FINISHED", source, summary,
                    "COB_FINISHED", summary["latest_process_finish_utc"], run_id,
                    "processes+modules+global-gate+mayorization", "exact-finish-with-composite-gate",
                ):
                    new_events.append("COB_FINISHED")
                if self._event(
                    f"{source}:{summary['close_id']}:READY_TO_SYNC", source, summary,
                    "READY_TO_SYNC", summary["observed_at_utc"], run_id,
                    "local COB completion contract", "observed-ready",
                ):
                    new_events.append("READY_TO_SYNC")
            if summary["state"] == "INCONSISTENT" and self._event(
                f"{source}:{summary['close_id']}:INCONSISTENT:{summary['observed_at_utc']}",
                source, summary, "INCONSISTENT", summary["observed_at_utc"], run_id,
                "local COB completion contract", "observed-conflict",
            ):
                new_events.append("INCONSISTENT")
            if summary["state"] == "PAUSED" and self._event(
                f"{source}:{summary['close_id']}:COB_PAUSED:{summary['latest_process_activity_utc']}",
                source, summary, "COB_PAUSED", summary["observed_at_utc"], run_id,
                "no process progress beyond local threshold", "observed-pause",
                {"latest_process_activity_utc": summary["latest_process_activity_utc"],
                 "threshold_seconds": int(PAUSE_THRESHOLD.total_seconds())},
            ):
                new_events.append("COB_PAUSED")

            new_gaps: list[str] = []
            if previous:
                previous_observed = _aware_utc(previous["observed_at_utc"])
                current_observed = _aware_utc(summary["observed_at_utc"])
                assert previous_observed and current_observed
                observation_gap = {
                    "gap_type": "OBSERVATION_GAP", "started_at_utc": previous["observed_at_utc"],
                    "ended_at_utc": summary["observed_at_utc"],
                    "confidence": "exact-local-observation-boundary",
                    "overlaps_shutdown_window": _overlaps_shutdown(previous_observed, current_observed),
                    "details": {},
                }
                if self._gap(f"observation:{source}:{summary['close_id']}:{previous['id']}:{snapshot_id}",
                             source, summary["close_id"], summary["operation_date"], observation_gap, run_id):
                    new_gaps.append("OBSERVATION_GAP")
            for gap in remote_execution_gaps(processes):
                key = f"remote:{source}:{summary['close_id']}:{gap['started_at_utc']}:{gap['ended_at_utc']}"
                if self._gap(key, source, summary["close_id"], summary["operation_date"], gap, run_id):
                    new_gaps.append("REMOTE_EXECUTION_GAP")
                    if self._event(
                        f"{source}:{summary['close_id']}:COB_RESUMED:{gap['ended_at_utc']}",
                        source, summary, "COB_RESUMED", gap["ended_at_utc"], run_id,
                        "PROCESOS_BITACORA execution gap", "exact-resumption-inferred-pause", gap["details"],
                    ):
                        new_events.append("COB_RESUMED")
            closed_outages = self._close_outages(run_id, source, summary, summary["observed_at_utc"])
            self.conn.commit()
            return {"snapshot_id": snapshot_id, "new_events": new_events,
                    "new_gaps": new_gaps, "closed_outages": len(closed_outages)}
        except Exception:
            self.conn.rollback()
            raise

    def snapshots(self, operation_date: date | None = None) -> dict[str, Any]:
        where = "WHERE operation_date=?" if operation_date else ""
        params: tuple[Any, ...] = (operation_date.isoformat(),) if operation_date else ()
        rows = [dict(row) for row in self.conn.execute(
            f"SELECT * FROM cob_close_snapshots {where} ORDER BY operation_date,observed_at_utc", params
        )]
        for row in rows:
            row["local"] = {"observed_at": _local_text(row["observed_at_utc"]),
                            "cob_started_at": _local_text(row["first_process_start_utc"]),
                            "latest_process_finish_at": _local_text(row["latest_process_finish_utc"])}
            row.pop("raw_summary_json", None)
        return {"operation_date": operation_date.isoformat() if operation_date else None, "snapshots": rows}

    def timeline(self, operation_date: date | None = None) -> dict[str, Any]:
        if operation_date is None:
            row = self.conn.execute(
                "SELECT operation_date FROM cob_close_snapshots ORDER BY operation_date DESC LIMIT 1"
            ).fetchone()
            if not row:
                return {"operation_date": None, "events": [], "gaps": [], "runs": []}
            operation_date = date.fromisoformat(str(row["operation_date"]))
        value = operation_date.isoformat()
        events = [dict(row) for row in self.conn.execute(
            "SELECT * FROM cob_timeline_events WHERE operation_date=? ORDER BY event_at_utc,id", (value,)
        )]
        gaps = [dict(row) for row in self.conn.execute(
            "SELECT * FROM cob_gap_intervals WHERE operation_date=? ORDER BY started_at_utc,id", (value,)
        )]
        runs = [dict(row) for row in self.conn.execute(
            "SELECT DISTINCT r.* FROM cob_monitor_runs AS r LEFT JOIN cob_close_snapshots AS s "
            "ON s.monitor_run_id=r.id WHERE r.requested_operation_date=? OR s.operation_date=? "
            "ORDER BY r.started_at_utc", (value, value)
        )]
        for event in events:
            event["event_at_local"] = _local_text(event["event_at_utc"])
            event["details"] = json.loads(event.pop("details_json"))
        for gap in gaps:
            gap["started_at_local"] = _local_text(gap["started_at_utc"])
            gap["ended_at_local"] = _local_text(gap["ended_at_utc"])
            gap["details"] = json.loads(gap.pop("details_json"))
        return {"operation_date": value, "events": events, "gaps": gaps, "runs": runs}


def _operator_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation_date": summary["operation_date"], "close_id": summary["close_id"],
        "state": summary["state"], "ready_to_sync": summary["ready_to_sync"],
        "local_time": {
            "observed_at": _local_text(summary["observed_at_utc"]),
            "business_day_opened_from_previous_close": _local_text(summary["previous_open_modules_finish_utc"]),
            "cob_started_at": _local_text(summary["first_process_start_utc"]),
            "latest_process_finish_at": _local_text(summary["latest_process_finish_utc"]),
            "mayorization_created_at": _local_text(summary["mayorization_created_at_utc"]),
            "loan_accrual_first_at": _local_text(summary["loan_accrual_first_utc"]),
            "loan_accrual_last_at": _local_text(summary["loan_accrual_last_utc"]),
            "share_yield_first_at": _local_text(summary["share_yield_first_utc"]),
            "share_yield_last_at": _local_text(summary["share_yield_last_utc"]),
        },
        "gates": {
            "global_close_status": summary["global_close_status"],
            "modules": {"closed": summary["closed_module_count"], "open": summary["open_module_count"],
                        "observed": summary["module_count"], "expected": summary["expected_module_count"]},
            "processes": {"started": summary["started_process_count"],
                          "finished": summary["finished_process_count"],
                          "successful": summary["successful_process_count"],
                          "locked": summary["locked_process_count"],
                          "observed": summary["process_count"],
                          "expected": summary["expected_process_count"]},
            "mayorization_present": summary["mayorization_present"],
        },
        "outputs": {"loan_accrual_count": summary["loan_accrual_count"],
                    "share_yield_count": summary["share_yield_count"]},
    }


def capture_snapshot(
    config: SourceConfig, state_path: Path, operation_date: date | None = None,
    *, clock: Callable[[], datetime] = _utc_now,
    fetcher: Callable[[SourceConfig, date | None], dict[str, Any]] = fetch_source_snapshot,
) -> dict[str, Any]:
    source = source_fingerprint(config)
    started_at = clock()
    if started_at.tzinfo is None:
        raise ValueError("COB monitor clock must be timezone-aware")
    store = CobStore(state_path)
    try:
        run_id = store.start_run(source, operation_date, started_at)
        try:
            payload = fetcher(config, operation_date)
        except Exception as exc:
            store.finish_run(run_id, clock(), False, error=exc)
            store.record_unreachable(run_id, source, started_at)
            return {"ok": False, "run_id": run_id, "state": "DATABASE_UNREACHABLE",
                    "operation_date": operation_date.isoformat() if operation_date else None,
                    "observed_at_local": _local_text(started_at), "error": type(exc).__name__,
                    "message": _safe_error(exc), "recorded": True}
        snapshot = build_snapshot(payload, started_at)
        server_time = snapshot["summary"]["source_server_time_utc"]
        store.finish_run(run_id, clock(), True, server_time=server_time)
        changes = store.record_snapshot(run_id, source, snapshot)
        return {"ok": snapshot["summary"]["state"] != "INCONSISTENT", "run_id": run_id,
                "snapshot_id": changes["snapshot_id"], **_operator_summary(snapshot["summary"]),
                "new_events": changes["new_events"], "new_gaps": changes["new_gaps"],
                "closed_outages": changes["closed_outages"], "state_path": str(state_path.resolve())}
    finally:
        store.close()


def cob_snapshots(state_path: Path, operation_date: date | None = None) -> dict[str, Any]:
    with closing(CobStore(state_path)) as store:
        return store.snapshots(operation_date)


def cob_timeline(state_path: Path, operation_date: date | None = None) -> dict[str, Any]:
    with closing(CobStore(state_path)) as store:
        return store.timeline(operation_date)
