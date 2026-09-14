from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA = """
CREATE TABLE IF NOT EXISTS state_metadata (
 key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
 id TEXT PRIMARY KEY, target_fingerprint TEXT NOT NULL, block TEXT NOT NULL,
 created_at TEXT NOT NULL, source_fingerprint TEXT NOT NULL, contract_hash TEXT NOT NULL,
 status TEXT NOT NULL, document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, target_fingerprint TEXT NOT NULL,
 block TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
 summary TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS items (
 run_id TEXT NOT NULL, source_key TEXT NOT NULL, action TEXT NOT NULL,
 source_hash TEXT NOT NULL, target_id TEXT, status TEXT NOT NULL, error_code TEXT,
 PRIMARY KEY (run_id, source_key)
);
CREATE TABLE IF NOT EXISTS accounting_attempts (
 run_id TEXT NOT NULL, source_key TEXT NOT NULL, plan_hash TEXT NOT NULL,
 planned_hash TEXT NOT NULL, request_idempotency_key TEXT NOT NULL,
 request_run_id TEXT NOT NULL, target_transaction_id TEXT,
 target_line_ids TEXT NOT NULL DEFAULT '[]', disposition TEXT NOT NULL,
 error_class TEXT, retryable INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY (run_id, source_key)
);
CREATE TABLE IF NOT EXISTS reconciliations (
 run_id TEXT PRIMARY KEY, block TEXT NOT NULL, target_fingerprint TEXT NOT NULL,
 reconciled_at TEXT NOT NULL, ok INTEGER NOT NULL, result_hash TEXT NOT NULL,
 summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mappings (
 target_fingerprint TEXT NOT NULL, block TEXT NOT NULL, source_key TEXT NOT NULL,
 target_id TEXT NOT NULL, source_hash TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY (target_fingerprint, block, source_key)
);
CREATE TABLE IF NOT EXISTS links (
 target_fingerprint TEXT NOT NULL, block TEXT NOT NULL, source_key TEXT NOT NULL,
 target_id TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY (target_fingerprint, block, source_key)
);
CREATE TABLE IF NOT EXISTS inspections (
 id INTEGER PRIMARY KEY AUTOINCREMENT, target_name TEXT NOT NULL,
 target_fingerprint TEXT NOT NULL, block TEXT NOT NULL, inspected_at TEXT NOT NULL,
 contract_hash TEXT NOT NULL, schema_signature TEXT NOT NULL, ready INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_plans (
 id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, workflow_version INTEGER NOT NULL,
 definition_hash TEXT NOT NULL, target_name TEXT NOT NULL, target_fingerprint TEXT NOT NULL,
 created_at TEXT NOT NULL, status TEXT NOT NULL, document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_runs (
 id TEXT PRIMARY KEY, workflow_plan_id TEXT NOT NULL, workflow_id TEXT NOT NULL,
 target_name TEXT NOT NULL, target_fingerprint TEXT NOT NULL, created_at TEXT NOT NULL,
 started_at TEXT, finished_at TEXT, status TEXT NOT NULL, runner_pid INTEGER,
 heartbeat_at TEXT, current_service TEXT, current_phase TEXT, log_path TEXT,
 summary TEXT NOT NULL DEFAULT '{}', error_code TEXT, error_message TEXT
);
CREATE TABLE IF NOT EXISTS workflow_steps (
 id TEXT PRIMARY KEY, workflow_run_id TEXT NOT NULL, service_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL,
 phase TEXT NOT NULL, plan_id TEXT, child_run_id TEXT, started_at TEXT,
 finished_at TEXT, summary TEXT NOT NULL DEFAULT '{}', error_code TEXT,
 error_message TEXT, UNIQUE(workflow_run_id, service_id, attempt)
);
CREATE TABLE IF NOT EXISTS workflow_failures (
 id TEXT PRIMARY KEY, workflow_run_id TEXT NOT NULL, workflow_step_id TEXT,
 service_id TEXT NOT NULL, phase TEXT NOT NULL, source_key TEXT,
 item_status TEXT NOT NULL, error_code TEXT, error_message TEXT,
 fingerprint TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_failure_links (
 failure_id TEXT NOT NULL, related_failure_id TEXT NOT NULL,
 relationship TEXT NOT NULL,
 PRIMARY KEY(failure_id, related_failure_id, relationship)
);
CREATE TABLE IF NOT EXISTS workflow_events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 workflow_run_id TEXT NOT NULL, workflow_step_id TEXT, workflow_failure_id TEXT,
 service_id TEXT, attempt INTEGER, phase TEXT NOT NULL, event_type TEXT NOT NULL,
 status TEXT, severity TEXT NOT NULL, source_key TEXT, error_code TEXT,
 message TEXT, details TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_event_links (
 event_id TEXT NOT NULL, related_event_id TEXT NOT NULL,
 relationship TEXT NOT NULL,
 PRIMARY KEY(event_id, related_event_id, relationship)
);
CREATE TABLE IF NOT EXISTS loan_sync_changes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 pr_reference TEXT NOT NULL UNIQUE,
 description TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open',
 created_at TEXT NOT NULL,
 closed_at TEXT
);
CREATE TABLE IF NOT EXISTS loan_sync_change_loans (
 change_id INTEGER NOT NULL,
 source_loan_id TEXT NOT NULL,
 target_loan_id TEXT,
 result TEXT NOT NULL,
 notes TEXT,
 PRIMARY KEY (change_id, source_loan_id),
 FOREIGN KEY (change_id) REFERENCES loan_sync_changes(id)
);
CREATE TABLE IF NOT EXISTS loan_sync_change_decisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 rationale TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY (change_id) REFERENCES loan_sync_changes(id)
);
CREATE INDEX IF NOT EXISTS workflow_runs_status_idx
 ON workflow_runs(target_fingerprint, status, created_at);
CREATE INDEX IF NOT EXISTS workflow_steps_run_idx
 ON workflow_steps(workflow_run_id, ordinal, attempt);
CREATE INDEX IF NOT EXISTS workflow_failures_run_idx
 ON workflow_failures(workflow_run_id, service_id, fingerprint);
CREATE INDEX IF NOT EXISTS workflow_events_run_idx
 ON workflow_events(workflow_run_id, sequence);
CREATE INDEX IF NOT EXISTS workflow_events_failure_idx
 ON workflow_events(workflow_failure_id);
CREATE INDEX IF NOT EXISTS loan_sync_change_loans_source_idx
 ON loan_sync_change_loans(source_loan_id);
CREATE INDEX IF NOT EXISTS loan_sync_change_decisions_change_idx
 ON loan_sync_change_decisions(change_id, created_at);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


ACCOUNTING_CUTOFF_TIMEZONE = "America/El_Salvador"


def sync_run_cutoff_date(instant: datetime | None = None) -> str:
    current = instant or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Cutoff clock instant must include a timezone")
    return current.astimezone(ZoneInfo(ACCOUNTING_CUTOFF_TIMEZONE)).date().isoformat()


def accounting_cutoff_snapshot(cutoff_date: str | None = None, source: str | None = None) -> dict[str, str]:
    resolved = cutoff_date or sync_run_cutoff_date()
    try:
        parsed = date.fromisoformat(resolved)
    except ValueError as exc:
        raise ValueError("Accounting cutoff date must use ISO format YYYY-MM-DD") from exc
    if parsed.isoformat() != resolved:
        raise ValueError("Accounting cutoff date must use ISO format YYYY-MM-DD")
    return {
        "date": resolved,
        "timezone": ACCOUNTING_CUTOFF_TIMEZONE,
        "source": source or ("explicit" if cutoff_date else "sync-run-date-default"),
    }


class State:
    def __init__(self, path: Path, cutoff_date: str | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path.resolve()
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.accounting_cutoff = accounting_cutoff_snapshot(cutoff_date)

    def set_accounting_cutoff(self, cutoff_date: str, source: str = "explicit") -> None:
        self.accounting_cutoff = accounting_cutoff_snapshot(cutoff_date, source)

    def adopt_accounting_cutoff(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("timezone") != ACCOUNTING_CUTOFF_TIMEZONE:
            raise ValueError(f"Accounting cutoff timezone must be {ACCOUNTING_CUTOFF_TIMEZONE}")
        adopted: dict[str, Any] = accounting_cutoff_snapshot(
            str(snapshot.get("date") or ""), str(snapshot.get("source") or "frozen-plan")
        )
        binding_fields = (
            "configuration_revision", "configuration_hash", "lifecycle_state"
        )
        binding = {key: snapshot[key] for key in binding_fields if key in snapshot}
        if binding and set(binding) != set(binding_fields):
            raise ValueError("Accounting cutoff target binding is incomplete")
        adopted.update(binding)
        self.accounting_cutoff = adopted

    def _attach_accounting_cutoff(self, document: dict[str, Any]) -> None:
        existing = document.get("accounting_cutoff")
        if existing is None:
            document["accounting_cutoff"] = dict(self.accounting_cutoff)
            return
        if existing != self.accounting_cutoff:
            raise ValueError("Plan accounting cutoff does not match the active sync sequence cutoff")

    def initialize_cycle(
        self, cycle_id: str, target_name: str, target_fingerprint: str,
        baseline_ref: str, created_at: str,
    ) -> None:
        existing = self.cycle_metadata()
        if existing:
            if existing.get("cycle_id") != cycle_id:
                raise ValueError(
                    f"State database belongs to cycle {existing.get('cycle_id')!r}, not {cycle_id!r}"
                )
            return
        values = {
            "cycle_id": cycle_id,
            "target_name": target_name,
            "target_fingerprint": target_fingerprint,
            "baseline_ref": baseline_ref,
            "created_at": created_at,
        }
        self.conn.executemany("INSERT INTO state_metadata(key,value) VALUES(?,?)", values.items())
        self.conn.commit()

    def cycle_metadata(self) -> dict[str, str]:
        return {
            str(row["key"]): str(row["value"])
            for row in self.conn.execute("SELECT key,value FROM state_metadata")
        }

    def require_cycle(self, cycle_id: str, target_fingerprint: str) -> dict[str, str]:
        metadata = self.cycle_metadata()
        if not metadata:
            raise ValueError("Workflow state database has no sync-cycle identity")
        if metadata.get("cycle_id") != cycle_id:
            raise ValueError(
                f"State cycle mismatch: expected {cycle_id!r}, found {metadata.get('cycle_id')!r}"
            )
        if metadata.get("target_fingerprint") != target_fingerprint:
            raise ValueError("Sync cycle belongs to a different local target fingerprint")
        return metadata

    def save_plan(self, target: str, block: str, source_fingerprint: str,
                  contract_hash: str, document: dict[str, Any]) -> str:
        self._attach_accounting_cutoff(document)
        plan_id = uuid.uuid4().hex
        self.conn.execute("INSERT INTO plans VALUES (?,?,?,?,?,?,?,?)", (
            plan_id, target, block, now(), source_fingerprint, contract_hash, "planned",
            json.dumps(document, sort_keys=True, separators=(",", ":")),
        ))
        self.conn.commit()
        return plan_id

    def plan(self, plan_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            raise ValueError(f"Unknown plan: {plan_id}")
        value = dict(row)
        value["document"] = json.loads(value["document"])
        return value

    def start_run(self, plan: dict[str, Any]) -> str:
        run_id = uuid.uuid4().hex
        self.conn.execute("INSERT INTO runs(id,plan_id,target_fingerprint,block,started_at,status) VALUES(?,?,?,?,?,?)",
                          (run_id, plan["id"], plan["target_fingerprint"], plan["block"], now(), "running"))
        self.conn.commit()
        return run_id

    def record_item(self, run_id: str, source_key: str, action: str, source_hash: str,
                    status: str, target_id: str | None = None, error_code: str | None = None) -> None:
        self.conn.execute("INSERT OR REPLACE INTO items VALUES(?,?,?,?,?,?,?)",
                          (run_id, source_key, action, source_hash, target_id, status, error_code))
        self.conn.commit()

    def record_items(self, rows: list[tuple[str, str, str, str, str | None, str, str | None]]) -> None:
        """Journal one completed destination batch in a single local transaction."""
        self.conn.executemany("INSERT OR REPLACE INTO items VALUES(?,?,?,?,?,?,?)", rows)
        self.conn.commit()

    def record_accounting_item(
        self, run_id: str, source_key: str, action: str, source_hash: str,
        status: str, plan_hash: str, planned_hash: str,
        request_idempotency_key: str, request_run_id: str,
        target_transaction_id: str | None = None,
        target_line_ids: list[int] | None = None, error_code: str | None = None,
        disposition: str = "APPLICABLE", error_class: str | None = None,
        retryable: bool = False,
    ) -> None:
        """Persist one accounting outcome and its recovery identity atomically."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO items VALUES(?,?,?,?,?,?,?)",
                (run_id, source_key, action, source_hash, target_transaction_id, status, error_code),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO accounting_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, source_key, plan_hash, planned_hash,
                    request_idempotency_key, request_run_id, target_transaction_id,
                    json.dumps(target_line_ids or [], separators=(",", ":")),
                    disposition, error_class, int(retryable),
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def accounting_attempt(self, run_id: str, source_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM accounting_attempts WHERE run_id=? AND source_key=?",
            (run_id, source_key),
        ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["target_line_ids"] = json.loads(value["target_line_ids"])
        value["retryable"] = bool(value["retryable"])
        return value

    def accounting_retry_items(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT i.*,a.request_idempotency_key,a.request_run_id,a.retryable,a.error_class "
            "FROM items i LEFT JOIN accounting_attempts a "
            "ON a.run_id=i.run_id AND a.source_key=i.source_key "
            "WHERE i.run_id=? AND (i.status='pending' OR (i.status='failed' AND a.retryable=1)) "
            "ORDER BY i.source_key",
            (run_id,),
        )
        return [dict(row) for row in rows]

    def save_mapping(self, target: str, block: str, source_key: str, target_id: str, source_hash: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO mappings VALUES(?,?,?,?,?,?)",
                          (target, block, source_key, target_id, source_hash, now()))
        self.conn.commit()

    def save_mappings(self, rows: list[tuple[str, str, str, str, str, str]]) -> None:
        self.conn.executemany("INSERT OR REPLACE INTO mappings VALUES(?,?,?,?,?,?)", rows)
        self.conn.commit()

    def mapping(self, target: str, block: str, source_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM mappings WHERE target_fingerprint=? AND block=? AND source_key=?",
            (target, block, source_key),
        ).fetchone()
        return dict(row) if row else None

    def delete_mapping(self, target: str, block: str, source_key: str) -> None:
        self.conn.execute(
            "DELETE FROM mappings WHERE target_fingerprint=? AND block=? AND source_key=?",
            (target, block, source_key),
        )
        self.conn.commit()

    def link(self, target: str, block: str, source_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM links WHERE target_fingerprint=? AND block=? AND source_key=?",
            (target, block, source_key),
        ).fetchone()
        return dict(row) if row else None

    def delete_link(self, target: str, block: str, source_key: str) -> None:
        self.conn.execute(
            "DELETE FROM links WHERE target_fingerprint=? AND block=? AND source_key=?",
            (target, block, source_key),
        )
        self.conn.commit()

    def run(self, run_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError(f"Unknown run: {run_id}")
        value = dict(row)
        value["summary"] = json.loads(value["summary"])
        return value

    def run_items(self, run_id: str, failed_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM items WHERE run_id=?"
        if failed_only:
            sql += " AND status='failed'"
        return [dict(row) for row in self.conn.execute(sql, (run_id,))]

    def plan_run_items(self, plan_id: str) -> list[dict[str, Any]]:
        """Return durable progress per source key across a frozen plan's retry chain.

        Successful and intentionally terminal results are sticky. A later,
        accidentally repeated attempt must not turn already completed work back
        into a retry candidate. Failed and blocked results continue to follow
        their latest journal entry until one of those terminal states is reached.
        """
        latest: dict[str, dict[str, Any]] = {}
        terminal_statuses = {"succeeded", "recovered", "unchanged", "quarantined", "deferred", "reconciled"}
        rows = self.conn.execute(
            "SELECT i.* FROM runs r JOIN items i ON i.run_id=r.id "
            "WHERE r.plan_id=? ORDER BY r.started_at,i.rowid",
            (plan_id,),
        )
        for row in rows:
            item = dict(row)
            previous = latest.get(item["source_key"])
            # A dependency-blocked retry never attempted the item, so it must
            # not erase an earlier failure that still needs recovery. This is
            # especially important for loans, where an incomplete prerequisite
            # closure can otherwise turn every retry root into a permanent
            # blocked leaf.
            preserves_failed_retry_root = (
                previous is not None
                and previous["status"] == "failed"
                and item["status"] == "blocked"
            )
            if (
                previous is None
                or (
                    previous["status"] not in terminal_statuses
                    and not preserves_failed_retry_root
                )
            ):
                latest[item["source_key"]] = item
        return list(latest.values())

    def finish_run(self, run_id: str, status: str, summary: dict[str, Any]) -> None:
        self.conn.execute("UPDATE runs SET finished_at=?,status=?,summary=? WHERE id=?",
                          (now(), status, json.dumps(summary, sort_keys=True), run_id))
        self.conn.commit()

    def record_accounting_reconciliation(
        self, run_id: str, source_key: str, matched: bool, reason_code: str | None = None,
    ) -> None:
        """Record reconciliation without losing the immutable apply/retry identity."""
        if not matched:
            return
        status = "reconciled"
        disposition = "RECONCILED"
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                "UPDATE items SET status=?,error_code=? WHERE run_id=? AND source_key=?",
                (status, reason_code, run_id, source_key),
            )
            self.conn.execute(
                "UPDATE accounting_attempts SET disposition=?,error_class=?,retryable=0 "
                "WHERE run_id=? AND source_key=?",
                (disposition, None if matched else "reconciliation", run_id, source_key),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def record_reconciliation(self, run_id: str, result: dict[str, Any]) -> None:
        run = self.run(run_id)
        rendered = json.dumps(result, sort_keys=True, separators=(",", ":"), default=str)
        result_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        self.conn.execute(
            "INSERT OR REPLACE INTO reconciliations VALUES(?,?,?,?,?,?,?)",
            (
                run_id, run["block"], run["target_fingerprint"], now(),
                int(bool(result.get("ok"))), result_hash, rendered,
            ),
        )
        self.conn.commit()

    def latest_reconciliation(self, block: str, target_fingerprint: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM reconciliations WHERE block=? AND target_fingerprint=? "
            "ORDER BY reconciled_at DESC LIMIT 1",
            (block, target_fingerprint),
        ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["ok"] = bool(value["ok"])
        value["summary"] = json.loads(value["summary"])
        return value

    def run_reconciliation(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM reconciliations WHERE run_id=?", (run_id,),
        ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["ok"] = bool(value["ok"])
        value["summary"] = json.loads(value["summary"])
        return value

    def add_link(self, target: str, block: str, source_key: str, target_id: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO links VALUES(?,?,?,?,?)", (target, block, source_key, target_id, now()))
        self.conn.commit()

    def save_inspection(self, target_name: str, target: str, block: str, contract_hash: str,
                        schema_signature: str, ready: bool) -> None:
        self.conn.execute(
            "INSERT INTO inspections(target_name,target_fingerprint,block,inspected_at,contract_hash,schema_signature,ready) "
            "VALUES(?,?,?,?,?,?,?)",
            (target_name, target, block, now(), contract_hash, schema_signature, int(ready)),
        )
        self.conn.commit()

    def recent(self, block: str | None = None, target: str | None = None) -> list[dict[str, Any]]:
        where, args = [], []
        if block: where.append("block=?"); args.append(block)
        if target: where.append("target_fingerprint=?"); args.append(target)
        sql = "SELECT * FROM runs" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY started_at DESC LIMIT 30"
        return [dict(row) for row in self.conn.execute(sql, args)]

    def save_workflow_plan(
        self, workflow_id: str, workflow_version: int, definition_hash: str,
        target_name: str, target_fingerprint: str, document: dict[str, Any],
    ) -> str:
        self._attach_accounting_cutoff(document)
        plan_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO workflow_plans VALUES(?,?,?,?,?,?,?,?,?)",
            (plan_id, workflow_id, workflow_version, definition_hash, target_name,
             target_fingerprint, now(), "planned",
             json.dumps(document, sort_keys=True, separators=(",", ":"))),
        )
        self.conn.commit()
        return plan_id

    def workflow_plan(self, plan_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM workflow_plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            raise ValueError(f"Unknown workflow plan: {plan_id}")
        value = dict(row)
        value["document"] = json.loads(value["document"])
        return value

    def _insert_workflow_event(
        self, run_id: str, event_type: str, phase: str, *,
        step_id: str | None = None, failure_id: str | None = None,
        service_id: str | None = None, attempt: int | None = None,
        status: str | None = None, severity: str = "info",
        source_key: str | None = None, error_code: str | None = None,
        message: str | None = None, details: dict[str, Any] | None = None,
    ) -> str:
        event_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO workflow_events("
            "id,workflow_run_id,workflow_step_id,workflow_failure_id,service_id,attempt,"
            "phase,event_type,status,severity,source_key,error_code,message,details,created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, run_id, step_id, failure_id, service_id, attempt, phase,
             event_type, status, severity, source_key, error_code, message,
             json.dumps(details or {}, sort_keys=True, default=str), now()),
        )
        return event_id

    def record_workflow_event(
        self, run_id: str, event_type: str, phase: str, **values: Any,
    ) -> str:
        event_id = self._insert_workflow_event(run_id, event_type, phase, **values)
        self.conn.commit()
        return event_id

    def create_workflow_run(self, plan: dict[str, Any], log_path: str | None = None) -> str:
        run_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO workflow_runs(id,workflow_plan_id,workflow_id,target_name,target_fingerprint,"
            "created_at,status,heartbeat_at,log_path) VALUES(?,?,?,?,?,?,?,?,?)",
            (run_id, plan["id"], plan["workflow_id"], plan["target_name"],
             plan["target_fingerprint"], now(), "queued", now(), log_path),
        )
        self._insert_workflow_event(
            run_id, "workflow-run-created", "queued", status="queued",
            details={"workflow_plan_id": plan["id"], "workflow_id": plan["workflow_id"]},
        )
        for ordinal, service_id in enumerate(plan["document"]["ordered_services"]):
            step_id = uuid.uuid4().hex
            self.conn.execute(
                "INSERT INTO workflow_steps(id,workflow_run_id,service_id,ordinal,attempt,status,phase) "
                "VALUES(?,?,?,?,?,?,?)",
                (step_id, run_id, service_id, ordinal, 1, "pending", "not-started"),
            )
            self._insert_workflow_event(
                run_id, "workflow-step-created", "not-started", step_id=step_id,
                service_id=service_id, attempt=1, status="pending",
                details={"ordinal": ordinal},
            )
        self.conn.commit()
        return run_id

    def workflow_run(self, run_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError(f"Unknown workflow run: {run_id}")
        value = dict(row)
        value["summary"] = json.loads(value["summary"])
        return value

    def workflow_steps(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM workflow_steps WHERE workflow_run_id=? ORDER BY ordinal,attempt", (run_id,)
        )
        result = []
        for row in rows:
            value = dict(row)
            value["summary"] = json.loads(value["summary"])
            result.append(value)
        return result

    def claim_workflow_run(self, run_id: str, runner_pid: int) -> None:
        run = self.workflow_run(run_id)
        if run["status"] not in {"queued", "interrupted", "failed"}:
            raise ValueError(f"Workflow run {run_id} cannot start from status {run['status']}")
        timestamp = now()
        self.conn.execute(
            "UPDATE workflow_runs SET status='running',runner_pid=?,started_at=COALESCE(started_at,?),"
            "finished_at=NULL,heartbeat_at=?,error_code=NULL,error_message=NULL WHERE id=?",
            (runner_pid, timestamp, timestamp, run_id),
        )
        self._insert_workflow_event(
            run_id, "workflow-run-started", "running", status="running",
            details={"runner_pid": runner_pid},
        )
        self.conn.commit()

    def set_workflow_runner(self, run_id: str, runner_pid: int, log_path: str) -> None:
        self.conn.execute(
            "UPDATE workflow_runs SET runner_pid=?,log_path=?,heartbeat_at=? WHERE id=?",
            (runner_pid, log_path, now(), run_id),
        )
        self.conn.commit()

    def queue_workflow_run(self, run_id: str) -> None:
        run = self.workflow_run(run_id)
        if run["status"] not in {"failed", "interrupted"}:
            raise ValueError(f"Workflow run {run_id} cannot queue from status {run['status']}")
        self.conn.execute(
            "UPDATE workflow_runs SET status='queued',runner_pid=NULL,heartbeat_at=?,"
            "finished_at=NULL,current_service=NULL,current_phase='queued',error_code=NULL,error_message=NULL "
            "WHERE id=?", (now(), run_id),
        )
        self._insert_workflow_event(
            run_id, "workflow-run-queued", "queued", status="queued",
            details={"previous_status": run["status"]},
        )
        self.conn.commit()

    def heartbeat_workflow(self, run_id: str, service_id: str | None, phase: str) -> None:
        self.conn.execute(
            "UPDATE workflow_runs SET heartbeat_at=?,current_service=?,current_phase=? WHERE id=?",
            (now(), service_id, phase, run_id),
        )
        self.conn.commit()

    def update_workflow_step(
        self, step_id: str, *, status: str | None = None, phase: str | None = None,
        plan_id: str | None = None, child_run_id: str | None = None,
        summary: dict[str, Any] | None = None, error_code: str | None = None,
        error_message: str | None = None, start: bool = False, finish: bool = False,
    ) -> None:
        previous = self.conn.execute(
            "SELECT * FROM workflow_steps WHERE id=?", (step_id,)
        ).fetchone()
        if not previous:
            raise ValueError(f"Unknown workflow step: {step_id}")
        fields: list[str] = []
        values: list[Any] = []
        changes: dict[str, Any] = {}
        for column, value in (
            ("status", status), ("phase", phase), ("plan_id", plan_id),
            ("child_run_id", child_run_id), ("error_code", error_code),
            ("error_message", error_message),
        ):
            if value is not None:
                fields.append(f"{column}=?")
                values.append(value)
                changes[column] = value
        if summary is not None:
            fields.append("summary=?")
            values.append(json.dumps(summary, sort_keys=True, default=str))
            changes["summary"] = summary
        if start:
            fields.append("started_at=COALESCE(started_at,?)")
            values.append(now())
            changes["started"] = True
        if finish:
            fields.append("finished_at=?")
            values.append(now())
            changes["finished"] = True
        if not fields:
            return
        values.append(step_id)
        self.conn.execute(f"UPDATE workflow_steps SET {','.join(fields)} WHERE id=?", values)
        resulting_status = status or previous["status"]
        resulting_phase = phase or previous["phase"]
        if status == "completed":
            event_type = "workflow-step-completed"
        elif status in {"failed", "blocked"}:
            event_type = f"workflow-step-{status}"
        elif status == "running" and previous["status"] != "running":
            event_type = "workflow-step-started"
        elif phase is not None and phase != previous["phase"]:
            event_type = "workflow-step-phase-changed"
        else:
            event_type = "workflow-step-updated"
        severity = "error" if resulting_status == "failed" else (
            "warning" if resulting_status == "blocked" else "info"
        )
        self._insert_workflow_event(
            previous["workflow_run_id"], event_type, resulting_phase,
            step_id=step_id, service_id=previous["service_id"],
            attempt=previous["attempt"], status=resulting_status, severity=severity,
            error_code=error_code, message=error_message, details={"changes": changes},
        )
        self.conn.commit()

    def retry_workflow_step(self, run_id: str, service_id: str) -> dict[str, Any]:
        previous = self.conn.execute(
            "SELECT * FROM workflow_steps WHERE workflow_run_id=? AND service_id=? "
            "ORDER BY attempt DESC LIMIT 1", (run_id, service_id),
        ).fetchone()
        if not previous:
            raise ValueError(f"Unknown workflow step: {service_id}")
        step_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO workflow_steps(id,workflow_run_id,service_id,ordinal,attempt,status,phase) "
            "VALUES(?,?,?,?,?,?,?)",
            (step_id, run_id, service_id, previous["ordinal"], previous["attempt"] + 1,
             "pending", "not-started"),
        )
        event_id = self._insert_workflow_event(
            run_id, "workflow-step-retry-created", "not-started", step_id=step_id,
            service_id=service_id, attempt=previous["attempt"] + 1, status="pending",
            details={"previous_step_id": previous["id"], "previous_attempt": previous["attempt"]},
        )
        previous_event = self.conn.execute(
            "SELECT id FROM workflow_events WHERE workflow_step_id=? ORDER BY sequence DESC LIMIT 1",
            (previous["id"],),
        ).fetchone()
        if previous_event:
            self.conn.execute(
                "INSERT OR IGNORE INTO workflow_event_links VALUES(?,?,?)",
                (event_id, previous_event["id"], "retry-of"),
            )
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM workflow_steps WHERE id=?", (step_id,)).fetchone())

    def finish_workflow_run(
        self, run_id: str, status: str, summary: dict[str, Any],
        error_code: str | None = None, error_message: str | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE workflow_runs SET status=?,finished_at=?,heartbeat_at=?,current_service=NULL,"
            "current_phase=NULL,summary=?,error_code=?,error_message=? WHERE id=?",
            (status, now(), now(), json.dumps(summary, sort_keys=True, default=str),
             error_code, error_message, run_id),
        )
        self._insert_workflow_event(
            run_id, "workflow-run-finished", status, status=status,
            severity="error" if status in {"failed", "interrupted"} else "info",
            error_code=error_code, message=error_message, details={"summary": summary},
        )
        self.conn.commit()

    def interrupt_workflow_run(self, run_id: str, error_message: str) -> None:
        self.finish_workflow_run(
            run_id, "interrupted", self.workflow_run(run_id)["summary"],
            "runner-process-exited", error_message,
        )

    def workflow_history(self, workflow_id: str, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM workflow_runs WHERE workflow_id=? ORDER BY created_at DESC LIMIT ?",
            (workflow_id, limit),
        )
        result = []
        for row in rows:
            value = dict(row)
            value["summary"] = json.loads(value["summary"])
            result.append(value)
        return result

    def workflow_failure_trends(self, workflow_id: str) -> list[dict[str, Any]]:
        latest = self.conn.execute(
            "SELECT id FROM workflow_runs WHERE workflow_id=? ORDER BY created_at DESC LIMIT 1",
            (workflow_id,),
        ).fetchone()
        latest_run_id = latest["id"] if latest else None
        latest_fingerprints = {
            row["fingerprint"] for row in self.conn.execute(
                "SELECT DISTINCT fingerprint FROM workflow_failures WHERE workflow_run_id=?",
                (latest_run_id,),
            )
        } if latest_run_id else set()
        rows = self.conn.execute(
            "SELECT f.fingerprint,f.service_id,f.phase,f.source_key,f.error_code,"
            "COUNT(DISTINCT f.workflow_run_id) AS run_count,MIN(f.created_at) AS first_seen_at,"
            "MAX(f.created_at) AS last_seen_at "
            "FROM workflow_failures f JOIN workflow_runs r ON r.id=f.workflow_run_id "
            "WHERE r.workflow_id=? GROUP BY f.fingerprint,f.service_id,f.phase,f.source_key,f.error_code "
            "ORDER BY last_seen_at DESC", (workflow_id,),
        )
        result = []
        for row in rows:
            value = dict(row)
            present = value["fingerprint"] in latest_fingerprints
            value["latest_run_id"] = latest_run_id
            value["present_in_latest_run"] = present
            value["trend"] = (
                "recurring" if present and value["run_count"] > 1
                else "new" if present
                else "not-seen-in-latest"
            )
            result.append(value)
        return result

    def record_workflow_failure(
        self, run_id: str, step_id: str | None, service_id: str, phase: str,
        source_key: str | None, item_status: str, error_code: str | None,
        error_message: str | None, fingerprint: str,
    ) -> str:
        failure_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO workflow_failures VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (failure_id, run_id, step_id, service_id, phase, source_key, item_status,
             error_code, error_message, fingerprint, now()),
        )
        attempt = None
        if step_id:
            step = self.conn.execute(
                "SELECT attempt FROM workflow_steps WHERE id=?", (step_id,)
            ).fetchone()
            attempt = int(step["attempt"]) if step else None
        severity = "warning" if item_status in {
            "blocked", "quarantined", "planned-failure", "recovered"
        } else "error"
        self._insert_workflow_event(
            run_id, "workflow-failure-recorded", phase, step_id=step_id,
            failure_id=failure_id, service_id=service_id, attempt=attempt,
            status=item_status, severity=severity, source_key=source_key,
            error_code=error_code, message=error_message,
            details={"fingerprint": fingerprint},
        )
        self.conn.commit()
        return failure_id

    def link_workflow_failure(self, failure_id: str, related_failure_id: str, relationship: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO workflow_failure_links VALUES(?,?,?)",
            (failure_id, related_failure_id, relationship),
        )
        event = self.conn.execute(
            "SELECT id FROM workflow_events WHERE workflow_failure_id=?", (failure_id,)
        ).fetchone()
        related_event = self.conn.execute(
            "SELECT id FROM workflow_events WHERE workflow_failure_id=?", (related_failure_id,)
        ).fetchone()
        if event and related_event:
            self.conn.execute(
                "INSERT OR IGNORE INTO workflow_event_links VALUES(?,?,?)",
                (event["id"], related_event["id"], relationship),
            )
        self.conn.commit()

    def workflow_failures(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM workflow_failures WHERE workflow_run_id=? ORDER BY created_at", (run_id,)
        )]

    def workflow_failure_links(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            "SELECT l.* FROM workflow_failure_links l JOIN workflow_failures f ON f.id=l.failure_id "
            "WHERE f.workflow_run_id=? ORDER BY f.created_at", (run_id,)
        )]

    def workflow_events(self, run_id: str) -> list[dict[str, Any]]:
        result = []
        for row in self.conn.execute(
            "SELECT * FROM workflow_events WHERE workflow_run_id=? ORDER BY sequence", (run_id,)
        ):
            value = dict(row)
            value["details"] = json.loads(value["details"])
            result.append(value)
        return result

    def workflow_event_links(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            "SELECT l.* FROM workflow_event_links l JOIN workflow_events e ON e.id=l.event_id "
            "WHERE e.workflow_run_id=? ORDER BY e.sequence", (run_id,)
        )]
