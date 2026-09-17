#!/usr/bin/env python3
"""Local dashboard and guarded launcher for Arissto sync workflows."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import subprocess
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_STATE_DIR = HERE.parent / ".arissto-sync"
STATIC_FILES = {"/": "index.html", "/app.js": "app.js", "/styles.css": "styles.css", "/og.svg": "og.svg"}
SAFE_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
SAFE_PLAN_ID = re.compile(r"^[a-f0-9]{32}$")
LAUNCH_CONFIRMATION = "LAUNCH LOCAL SYNC"
CYCLE_CONFIRMATION = "LOCAL FINERACT BASELINE RESTORED"

TRANSIENT_MARKERS = (
    "connection refused", "connection reset", "connection aborted", "timed out", "timeout",
    "http 502", "http 503", "http 504", "failed (502)", "failed (503)", "failed (504)",
    "temporarily unavailable", "runner-process-exited", "fineract-recovered",
)
STRUCTURAL_MARKERS = (
    "schedule_preview_mismatch", "cutover_adjustment_exceeds_frozen_maximum",
    "expected one native dpf interest transfer", "insufficient account balance",
    "numberofrepayments", "service plan is not applicable", "tax group with identifier",
    "does not exist", "validation errors", "domain rule violation", "failed (400)",
    "failed (403)", "failed (404)", "migration_interest_start_mismatch",
    "submitted_unfunded_zero_principal", "quarantine-loan",
)


def classify_failure(record: dict[str, Any]) -> dict[str, str]:
    """Classify retry posture conservatively from durable evidence."""
    status = (record.get("item_status") or "").lower()
    source_key = record.get("source_key")
    text = " ".join(
        str(record.get(field) or "") for field in ("error_code", "error_message")
    ).lower()
    seen = int(record.get("seen_in_executions") or 1)

    if status == "blocked":
        return {
            "failure_class": "dependency",
            "class_reason": "An upstream service has not completed successfully.",
            "retry_advice": "Resolve and reconcile the upstream dependency before rerunning this service.",
        }
    if status in {"quarantined", "planned-failure"}:
        return {
            "failure_class": "structural",
            "class_reason": "The plan deliberately identified a data or contract condition.",
            "retry_advice": "Review or correct the condition before retrying; time alone will not change it.",
        }
    if not source_key:
        return {
            "failure_class": "aggregate",
            "class_reason": "This is a service-level result caused by item failures below it.",
            "retry_advice": "Use the entity-level records to decide what must change.",
        }
    if any(marker in text for marker in TRANSIENT_MARKERS):
        return {
            "failure_class": "retryable",
            "class_reason": "The signature matches a connectivity, timeout, or process-health failure.",
            "retry_advice": "Retry after the affected service is healthy.",
        }
    if any(marker in text for marker in STRUCTURAL_MARKERS):
        if "schedule_preview_mismatch" in text:
            reason = "The source schedule and Fineract's calculated schedule differ."
        elif "native dpf interest transfer" in text:
            reason = "A required native DPF interest transfer is absent."
        elif "insufficient account balance" in text:
            reason = "Fineract cannot apply the event against the current account balance."
        elif "numberofrepayments" in text:
            reason = "The source repayment count violates Fineract's configured range."
        elif "cutover_adjustment_exceeds" in text:
            reason = "The required cutover adjustment exceeds the frozen policy limit."
        else:
            reason = "The signature matches a validation, configuration, contract, or target-state condition."
        return {
            "failure_class": "structural",
            "class_reason": reason,
            "retry_advice": "Retry alone will repeat this failure; change data, configuration, policy, or code first.",
        }
    if seen >= 2:
        return {
            "failure_class": "persistent",
            "class_reason": f"The same failure signature was recorded in {seen} service executions.",
            "retry_advice": "Treat it as non-retryable until its root cause is reviewed or changed.",
        }
    return {
        "failure_class": "unknown",
        "class_reason": "There is not enough evidence to call this transient or structural.",
        "retry_advice": "Review the underlying error before deciding to retry.",
    }


def readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def rows(connection: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


def row(connection: sqlite3.Connection, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    result = connection.execute(sql, parameters).fetchone()
    return dict(result) if result else None


def decode_json_fields(record: dict[str, Any] | None, *fields: str) -> dict[str, Any] | None:
    if not record:
        return record
    for field in fields:
        value = record.get(field)
        if isinstance(value, str):
            try:
                record[field] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return record


def attach_step_item_counts(step: dict[str, Any]) -> None:
    """Expose stable plan totals plus the number of child items recorded so far."""
    plan_document = step.pop("_plan_document", None)
    if isinstance(plan_document, str):
        try:
            plan_document = json.loads(plan_document)
        except json.JSONDecodeError:
            plan_document = None
    actions = plan_document.get("actions") if isinstance(plan_document, dict) else None
    planned_count = len(actions) if isinstance(actions, list) else None
    apply_counts = step.get("summary", {}).get("apply_counts", {})
    applied_count = (
        sum(value for value in apply_counts.values() if isinstance(value, int))
        if isinstance(apply_counts, dict) and apply_counts else None
    )
    step["sync_item_count"] = planned_count if planned_count is not None else applied_count


class Store:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir.resolve()

    def cycles(self) -> list[dict[str, Any]]:
        catalog = self.state_dir / "cycles.sqlite3"
        with readonly_connection(catalog) as connection:
            return rows(connection, "SELECT * FROM sync_cycles ORDER BY created_at DESC")

    def cycle(self, cycle_id: str) -> dict[str, Any]:
        with readonly_connection(self.state_dir / "cycles.sqlite3") as connection:
            result = row(connection, "SELECT * FROM sync_cycles WHERE id=?", (cycle_id,))
        if not result:
            raise KeyError(f"Unknown cycle: {cycle_id}")
        return result

    def state_path(self, cycle_id: str) -> Path:
        configured = Path(self.cycle(cycle_id)["state_path"]).resolve()
        expected = (self.state_dir / "cycles" / cycle_id / "state.sqlite3").resolve()
        if configured != expected:
            raise ValueError("Cycle state path does not match the local cycle catalog")
        return configured

    def active_runs(self, cycle_id: str) -> list[dict[str, Any]]:
        with readonly_connection(self.state_path(cycle_id)) as connection:
            return rows(
                connection,
                "SELECT id,workflow_id,status,runner_pid,created_at FROM workflow_runs "
                "WHERE status IN ('queued','running') ORDER BY created_at DESC",
            )

    def all_active_runs(self) -> list[dict[str, Any]]:
        active: list[dict[str, Any]] = []
        for cycle in self.cycles():
            if not Path(cycle["state_path"]).is_file():
                continue
            for run in self.active_runs(cycle["id"]):
                active.append({**run, "cycle_id": cycle["id"]})
        return active

    def runs(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for cycle in self.cycles():
            state_path = self.state_path(cycle["id"])
            if not state_path.is_file():
                continue
            with readonly_connection(state_path) as connection:
                cycle_runs = rows(
                    connection,
                    """
                    SELECT r.*,
                           (SELECT COUNT(*) FROM workflow_steps s WHERE s.workflow_run_id=r.id) AS attempt_count,
                           (SELECT COUNT(*) FROM workflow_failures f WHERE f.workflow_run_id=r.id) AS failure_record_count
                    FROM workflow_runs r ORDER BY r.created_at DESC
                    """,
                )
            for run in cycle_runs:
                run["cycle_id"] = cycle["id"]
                run["cycle_status"] = cycle["status"]
                run["baseline_ref"] = cycle["baseline_ref"]
                decode_json_fields(run, "summary")
                output.append(run)
        return sorted(output, key=lambda item: item["created_at"], reverse=True)

    def run_detail(self, cycle_id: str, run_id: str) -> dict[str, Any]:
        with readonly_connection(self.state_path(cycle_id)) as connection:
            run = row(connection, "SELECT * FROM workflow_runs WHERE id=?", (run_id,))
            if not run:
                raise KeyError(f"Unknown workflow run: {run_id}")
            steps = rows(
                connection,
                "SELECT * FROM workflow_steps WHERE workflow_run_id=? ORDER BY ordinal,attempt",
                (run_id,),
            )
            latest_steps = rows(
                connection,
                """
                SELECT s.*,p.document AS _plan_document,
                       CASE WHEN s.child_run_id IS NULL THEN NULL ELSE
                         (SELECT COUNT(*) FROM items i WHERE i.run_id=s.child_run_id)
                       END AS processed_item_count
                FROM workflow_steps s
                JOIN (
                  SELECT service_id,MAX(attempt) AS attempt FROM workflow_steps
                  WHERE workflow_run_id=? GROUP BY service_id
                ) latest ON latest.service_id=s.service_id AND latest.attempt=s.attempt
                LEFT JOIN plans p ON p.id=s.plan_id
                WHERE s.workflow_run_id=? ORDER BY s.ordinal
                """,
                (run_id, run_id),
            )
            summary = rows(
                connection,
                """
                WITH latest AS (
                  SELECT service_id,MAX(attempt) AS attempt FROM workflow_steps
                  WHERE workflow_run_id=? GROUP BY service_id
                ), selected AS (
                  SELECT s.id FROM workflow_steps s JOIN latest l
                    ON l.service_id=s.service_id AND l.attempt=s.attempt
                  WHERE s.workflow_run_id=?
                )
                SELECT f.service_id,f.item_status,COUNT(*) AS count,
                       COUNT(DISTINCT f.source_key) AS distinct_source_keys
                FROM workflow_failures f JOIN selected s ON s.id=f.workflow_step_id
                GROUP BY f.service_id,f.item_status ORDER BY f.service_id,f.item_status
                """,
                (run_id, run_id),
            )
            recent_events = rows(
                connection,
                """
                SELECT sequence,service_id,attempt,phase,event_type,status,severity,source_key,
                       error_code,message,created_at
                FROM workflow_events WHERE workflow_run_id=?
                ORDER BY sequence DESC LIMIT 80
                """,
                (run_id,),
            )
            execution_summary = row(
                connection,
                """
                SELECT
                  SUM(CASE WHEN event_type='workflow-run-queued' THEN 1 ELSE 0 END) AS workflow_resumes,
                  SUM(CASE WHEN event_type='workflow-step-retry-created' THEN 1 ELSE 0 END) AS service_retries,
                  SUM(CASE WHEN error_code='fineract-recovered' THEN 1 ELSE 0 END) AS automatic_recoveries
                FROM workflow_events WHERE workflow_run_id=?
                """,
                (run_id,),
            )
            latest_failure_evidence = rows(
                connection,
                """
                WITH latest AS (
                  SELECT service_id,MAX(attempt) AS attempt FROM workflow_steps
                  WHERE workflow_run_id=? GROUP BY service_id
                )
                SELECT f.*,
                  (SELECT COUNT(DISTINCT hs.attempt)
                   FROM workflow_failures hf JOIN workflow_steps hs ON hs.id=hf.workflow_step_id
                   WHERE hf.workflow_run_id=f.workflow_run_id
                     AND hf.service_id=f.service_id AND hf.fingerprint=f.fingerprint) AS seen_in_executions
                FROM workflow_failures f JOIN workflow_steps s ON s.id=f.workflow_step_id
                JOIN latest l ON l.service_id=s.service_id AND l.attempt=s.attempt
                WHERE f.workflow_run_id=?
                """,
                (run_id, run_id),
            )
        decode_json_fields(run, "summary")
        for step in steps + latest_steps:
            decode_json_fields(step, "summary")
        for step in latest_steps:
            attach_step_item_counts(step)
        retry_analysis: dict[str, int] = {}
        for failure in latest_failure_evidence:
            classification = classify_failure(failure)
            failure.update(classification)
            key = classification["failure_class"]
            retry_analysis[key] = retry_analysis.get(key, 0) + 1
        return {
            "run": run,
            "cycle": self.cycle(cycle_id),
            "steps": steps,
            "latest_steps": latest_steps,
            "failure_summary": summary,
            "recent_events": recent_events,
            "execution_summary": execution_summary,
            "retry_analysis": retry_analysis,
        }

    def failures(self, cycle_id: str, run_id: str, query: dict[str, list[str]]) -> dict[str, Any]:
        page = max(1, int(query.get("page", ["1"])[0]))
        page_size = min(250, max(10, int(query.get("page_size", ["75"])[0])))
        attempt_mode = query.get("attempt", ["latest"])[0]
        clauses = ["f.workflow_run_id=?"]
        parameters: list[Any] = [run_id]
        for field in ("service_id", "item_status"):
            value = query.get(field, [""])[0]
            if value:
                clauses.append(f"f.{field}=?")
                parameters.append(value)
        search = query.get("search", [""])[0].strip()
        if search:
            clauses.append("(f.source_key LIKE ? OR f.error_code LIKE ? OR f.error_message LIKE ?)")
            token = f"%{search}%"
            parameters.extend([token, token, token])
        join = "LEFT JOIN workflow_steps s ON s.id=f.workflow_step_id"
        if attempt_mode == "latest":
            join += " JOIN (SELECT service_id,MAX(attempt) attempt FROM workflow_steps WHERE workflow_run_id=? GROUP BY service_id) latest ON latest.service_id=s.service_id AND latest.attempt=s.attempt"
            parameters.insert(0, run_id)
        where = " AND ".join(clauses)
        offset = (page - 1) * page_size
        with readonly_connection(self.state_path(cycle_id)) as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM workflow_failures f {join} WHERE {where}", tuple(parameters)
            ).fetchone()[0]
            items = rows(
                connection,
                f"""
                SELECT f.id,f.service_id,f.phase,f.source_key,f.item_status,f.error_code,
                       f.error_message,f.fingerprint,f.created_at,s.attempt,
                       (SELECT COUNT(DISTINCT hs.attempt)
                        FROM workflow_failures hf JOIN workflow_steps hs ON hs.id=hf.workflow_step_id
                        WHERE hf.workflow_run_id=f.workflow_run_id
                          AND hf.service_id=f.service_id AND hf.fingerprint=f.fingerprint) AS seen_in_executions
                FROM workflow_failures f {join} WHERE {where}
                ORDER BY f.created_at DESC LIMIT ? OFFSET ?
                """,
                (*parameters, page_size, offset),
            )
        for item in items:
            item.update(classify_failure(item))
        return {"items": items, "total": total, "page": page, "page_size": page_size}


class Launcher:
    """Validated adapter around the existing local-only workflow CLI."""

    def __init__(self, store: Store, executable: Path = ROOT / "arissto-sync"):
        self.store = store
        self.executable = executable.resolve()
        self.launch_lock = threading.Lock()

    @staticmethod
    def _identifier(value: Any, label: str) -> str:
        normalized = str(value or "")
        if not SAFE_IDENTIFIER.fullmatch(normalized):
            raise ValueError(f"Invalid {label}")
        return normalized

    def _run(self, arguments: list[str], timeout: int) -> dict[str, Any]:
        completed = subprocess.run(
            [str(self.executable), *arguments], cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
            check=False, env=os.environ.copy(),
        )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("The sync command returned an unreadable response") from error
        if completed.returncode != 0 or result.get("ok") is False:
            raise RuntimeError(result.get("message") or result.get("error") or "The sync command failed")
        return result

    def options(self) -> dict[str, Any]:
        workflow_report = self._run(["workflow", "list"], timeout=20)
        registry = json.loads((ROOT / "migration-services" / "registry.json").read_text(encoding="utf-8"))
        catalog = {service["id"]: service for service in registry["services"]}
        for workflow in workflow_report.get("workflows", []):
            workflow["default_for_mode"] = workflow["id"] in {
                "local-full-sync", "local-full-resync",
            }
            workflow["services"] = [
                {
                    "id": service_id,
                    "name": catalog[service_id].get("name", service_id),
                    "depends_on": catalog[service_id].get("depends_on", []),
                    "status": catalog[service_id].get("status"),
                    "executable": catalog[service_id].get("executable", False),
                }
                for service_id in workflow.get("ordered_services", [])
            ]
        cycles = self.store.cycles()
        local_date = datetime.now(ZoneInfo("America/El_Salvador")).date().isoformat()
        used_ids = {cycle["id"] for cycle in cycles}
        suggested_cycle_id = next(
            (f"sandbox-{local_date}-{suffix}" for suffix in "abcdefghijklmnopqrstuvwxyz"
             if f"sandbox-{local_date}-{suffix}" not in used_ids),
            f"sandbox-{local_date}-{secrets.token_hex(3)}",
        )
        return {
            "target": "local",
            "confirmation": LAUNCH_CONFIRMATION,
            "cycle_confirmation": CYCLE_CONFIRMATION,
            "cycles": cycles,
            "active_runs": self.store.all_active_runs(),
            "suggested_cycle": {
                "id": suggested_cycle_id,
                "baseline_ref": f"sandbox-restored-baseline-{local_date}",
            },
            "workflows": workflow_report.get("workflows", []),
        }

    def create_cycle(self, document: dict[str, Any]) -> dict[str, Any]:
        cycle_id = self._identifier(document.get("cycle_id"), "cycle ID")
        baseline_ref = str(document.get("baseline_ref") or "").strip()
        if not baseline_ref or len(baseline_ref) > 200:
            raise ValueError("A baseline reference of at most 200 characters is required")
        reset_target = document.get("reset_target") is True
        reset_tenant = ""
        reset_confirmation = ""
        if reset_target:
            reset_tenant = str(document.get("reset_tenant") or "")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", reset_tenant) or reset_tenant == "default":
                raise ValueError("Choose a non-default disposable tenant to reset")
            reset_confirmation = str(document.get("reset_confirmation") or "")
            if not reset_confirmation.startswith(f"{reset_tenant}:"):
                raise ValueError("Enter the exact TENANT:DATABASE reset confirmation")
        elif document.get("confirmation") != CYCLE_CONFIRMATION:
            raise ValueError("Confirm that local Fineract was reset or restored before creating the cycle")
        with self.launch_lock:
            if self.store.all_active_runs():
                raise ValueError("Another local workflow is queued or running")
            arguments = [
                "workflow", "cycle", "create",
                "--cycle", cycle_id,
                "--baseline-ref", baseline_ref,
                "--note", "Created from the local sync dashboard",
                "--target", "local",
            ]
            if reset_target:
                arguments.extend([
                    "--reset-tenant", reset_tenant,
                    "--reset-confirm", reset_confirmation,
                ])
            return self._run(arguments, timeout=1200 if reset_target else 60)

    def prepare(self, document: dict[str, Any]) -> dict[str, Any]:
        cycle_id = self._identifier(document.get("cycle_id"), "cycle ID")
        workflow_id = self._identifier(document.get("workflow_id"), "workflow ID")
        run_mode = str(document.get("run_mode") or "fresh-clean")
        if run_mode not in {"fresh-clean", "full-resync"}:
            raise ValueError("Local planning supports fresh-clean or full-resync")
        requested_services = document.get("services")
        if not isinstance(requested_services, list) or not requested_services:
            raise ValueError("Select at least one workflow service")
        requested_services = [self._identifier(value, "service ID") for value in requested_services]
        if len(requested_services) != len(set(requested_services)):
            raise ValueError("Selected workflow services must be unique")
        cycle = self.store.cycle(cycle_id)
        if cycle["status"] != "open" or cycle["target_name"] != "local":
            raise ValueError(f"A {run_mode} run requires an open local sync cycle")
        with self.launch_lock:
            if self.store.active_runs(cycle_id):
                raise ValueError("This cycle already has a queued or running workflow")
            available = {
                item["id"] for item in self.options()["workflows"]
                if item.get("ready")
                and "local" in item.get("targets", [])
                and run_mode in item.get("run_modes", [])
            }
            if workflow_id not in available:
                raise ValueError("The selected workflow is not ready for this run mode")
            arguments = [
                "workflow", "plan", "--workflow", workflow_id,
                "--cycle", cycle_id, "--target", "local", "--run-mode", run_mode,
            ]
            for service_id in requested_services:
                arguments.extend(["--include-service", service_id])
            source_through_date = str(document.get("source_through_date") or "").strip()
            cutoff_date = str(document.get("cutoff_date") or "").strip()
            if source_through_date and cutoff_date:
                raise ValueError("Choose either source through date or advanced cutoff date")
            if source_through_date:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", source_through_date):
                    raise ValueError("Source through date must use YYYY-MM-DD")
                arguments.extend(["--source-through-date", source_through_date])
            elif cutoff_date:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cutoff_date):
                    raise ValueError("Cutoff date must use YYYY-MM-DD")
                arguments.extend(["--cutoff-date", cutoff_date])
            accounting_period = str(document.get("accounting_period") or "").strip()
            if "accounting-journal-entries" in requested_services:
                if accounting_period:
                    if not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", accounting_period):
                        raise ValueError("Accounting period contains an unsafe component")
                    arguments.extend(["--accounting-period", accounting_period])
            return self._run(arguments, timeout=300)

    def launch(self, document: dict[str, Any]) -> dict[str, Any]:
        cycle_id = self._identifier(document.get("cycle_id"), "cycle ID")
        plan_id = str(document.get("workflow_plan_id") or "")
        if not SAFE_PLAN_ID.fullmatch(plan_id):
            raise ValueError("Invalid workflow plan ID")
        if document.get("confirmation") != LAUNCH_CONFIRMATION:
            raise ValueError("Local sync launch was not explicitly confirmed")
        cycle = self.store.cycle(cycle_id)
        if cycle["status"] != "open" or cycle["target_name"] != "local":
            raise ValueError("A fresh/clean run requires an open local sync cycle")
        with self.launch_lock:
            if self.store.active_runs(cycle_id):
                raise ValueError("This cycle already has a queued or running workflow")
            return self._run([
                "workflow", "start", "--workflow-plan", plan_id,
                "--cycle", cycle_id, "--target", "local",
            ], timeout=60)


class Handler(BaseHTTPRequestHandler):
    store: Store
    launcher: Launcher
    launch_token: str

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[sync-dashboard] {format % args}")

    def send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_static(self, filename: str) -> None:
        path = HERE / filename
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def request_document(self) -> dict[str, Any]:
        if self.headers.get("X-Launch-Token") != self.launch_token:
            raise PermissionError("Invalid local launch token")
        origin = self.headers.get("Origin")
        allowed_origins = {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }
        if origin and origin not in allowed_origins:
            raise PermissionError("Cross-origin launch requests are not allowed")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Launch requests must use application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 65536:
            raise ValueError("Invalid request size")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/runs":
                self.send_json({"runs": self.store.runs()})
                return
            if parsed.path == "/api/launch/options":
                self.send_json({**self.launcher.options(), "launch_token": self.launch_token})
                return
            if parsed.path.startswith("/api/runs/"):
                parts = [unquote(part) for part in parsed.path.split("/") if part]
                if len(parts) not in (3, 4):
                    raise KeyError("Unknown API route")
                run_id = parts[2]
                query = parse_qs(parsed.query)
                cycle_id = query.get("cycle", [""])[0]
                if not cycle_id:
                    raise ValueError("cycle is required")
                if len(parts) == 4 and parts[3] == "failures":
                    self.send_json(self.store.failures(cycle_id, run_id, query))
                elif len(parts) == 3:
                    self.send_json(self.store.run_detail(cycle_id, run_id))
                else:
                    raise KeyError("Unknown API route")
                return
            filename = STATIC_FILES.get(parsed.path)
            if filename:
                self.send_static(filename)
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (KeyError, FileNotFoundError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
        except (ValueError, sqlite3.Error) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:  # defensive boundary for a local diagnostics UI
            self.send_json({"error": f"Dashboard could not read sync state: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            document = self.request_document()
            if parsed.path == "/api/sync-cycles":
                self.send_json(self.launcher.create_cycle(document), HTTPStatus.CREATED)
            elif parsed.path == "/api/workflow-plans":
                self.send_json(self.launcher.prepare(document), HTTPStatus.CREATED)
            elif parsed.path == "/api/workflow-runs":
                self.send_json(self.launcher.launch(document), HTTPStatus.ACCEPTED)
            else:
                self.send_json({"error": "Unknown API route"}, HTTPStatus.NOT_FOUND)
        except PermissionError as error:
            self.send_json({"error": str(error)}, HTTPStatus.FORBIDDEN)
        except (ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as error:
            self.send_json({"error": str(error)}, HTTPStatus.CONFLICT)
        except Exception as error:
            self.send_json({"error": f"Dashboard could not launch the local workflow: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the read-only Arissto sync run dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    Handler.store = Store(args.state_dir)
    Handler.launcher = Launcher(Handler.store)
    Handler.launch_token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Arissto Sync Runs: http://{args.host}:{args.port}")
    print(f"Read-only state: {args.state_dir.resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
