from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import requests

from .config import ROOT, Settings
from .connections import FineractApi, FineractError, postgres_connection
from .engine import preflight
from .dte_history import DteApplyControls
from .loans import LoanApplyControls
from .service_registry import load_registry
from .service_runtime import ServiceRuntime
from .state import State
from .workflow_definitions import (
    inspect_workflow, load_workflow, require_workflow_ready, select_workflow_services,
)


FAILURE_ITEM_STATUSES = {"failed", "quarantined", "blocked"}
PLAN_FAILURE_ACTIONS = {"blocked", "conflict-product", "quarantine", "quarantine-loan"}
DEFAULT_FINERACT_RESTART_ATTEMPTS = 1
DEFAULT_FINERACT_RESTART_TIMEOUT_SECONDS = 180.0
DEFAULT_FINERACT_RESTART_POLL_SECONDS = 5.0
DEFAULT_FINERACT_RESET_TIMEOUT_SECONDS = 900.0
FINERACT_ROOT = ROOT.parents[1]
ARISSTO_OFFICES = (
    {
        "id": 1,
        "branch": "001",
        "name": "Santiago de María",
        "externalId": "1",
        "openingDate": "2022-12-10",
        "parentId": None,
    },
    {
        "id": 2,
        "branch": "002",
        "name": "Usulutan",
        "externalId": "2",
        "openingDate": "2024-11-27",
        "parentId": 1,
    },
)


@dataclass(frozen=True)
class FineractRestartControls:
    attempts: int = DEFAULT_FINERACT_RESTART_ATTEMPTS
    timeout_seconds: float = DEFAULT_FINERACT_RESTART_TIMEOUT_SECONDS
    poll_seconds: float = DEFAULT_FINERACT_RESTART_POLL_SECONDS
    command: tuple[str, ...] = (
        "./scripts/local-fineract.sh", "restart",
    )

    @classmethod
    def configured(
        cls, attempts: int | None = None, timeout_seconds: float | None = None,
        poll_seconds: float | None = None,
    ) -> "FineractRestartControls":
        configured_command = os.getenv("ARISSTO_SYNC_FINERACT_RESTART_COMMAND", "").strip()
        command = tuple(shlex.split(configured_command)) if configured_command else cls.command
        return cls(
            attempts=(int(os.getenv("ARISSTO_SYNC_FINERACT_RESTART_ATTEMPTS", "1"))
                      if attempts is None else attempts),
            timeout_seconds=(float(os.getenv("ARISSTO_SYNC_FINERACT_RESTART_TIMEOUT_SECONDS", "180"))
                             if timeout_seconds is None else timeout_seconds),
            poll_seconds=(float(os.getenv("ARISSTO_SYNC_FINERACT_RESTART_POLL_SECONDS", "5"))
                          if poll_seconds is None else poll_seconds),
            command=command,
        )

    def __post_init__(self) -> None:
        if not 0 <= self.attempts <= 3:
            raise ValueError("Fineract restart attempts must be between 0 and 3")
        if not 1 <= self.timeout_seconds <= 900:
            raise ValueError("Fineract restart timeout must be between 1 and 900 seconds")
        if not 0.1 <= self.poll_seconds <= 60:
            raise ValueError("Fineract restart poll interval must be between 0.1 and 60 seconds")
        if not self.command:
            raise ValueError("Fineract restart command cannot be empty")


@dataclass(frozen=True)
class FineractResetControls:
    timeout_seconds: float = DEFAULT_FINERACT_RESET_TIMEOUT_SECONDS
    stop_command: tuple[str, ...] = (
        "./scripts/local-fineract.sh", "stop",
    )

    @classmethod
    def configured(cls) -> "FineractResetControls":
        configured_command = os.getenv("ARISSTO_SYNC_FINERACT_STOP_COMMAND", "").strip()
        command = tuple(shlex.split(configured_command)) if configured_command else cls.stop_command
        return cls(
            timeout_seconds=float(os.getenv("ARISSTO_SYNC_FINERACT_RESET_TIMEOUT_SECONDS", "900")),
            stop_command=command,
        )

    def __post_init__(self) -> None:
        if not 10 <= self.timeout_seconds <= 3600:
            raise ValueError("Fineract reset timeout must be between 10 and 3600 seconds")
        if not self.stop_command:
            raise ValueError("Fineract stop command cannot be empty")


def _is_fineract_outage_error(exc: Exception) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    return isinstance(exc, FineractError) and exc.status_code in {502, 503, 504}


def _fineract_api_ready(settings: Settings) -> bool:
    try:
        FineractApi(settings.target).ping()
        return True
    except (requests.ConnectionError, requests.Timeout):
        return False
    except FineractError as exc:
        if exc.status_code in {502, 503, 504}:
            return False
        raise


def _fineract_recovery_needed(settings: Settings, exc: Exception) -> bool:
    """Detect both direct transport failures and outages hidden by service-level summaries."""
    if _is_fineract_outage_error(exc):
        return True
    try:
        return not _fineract_api_ready(settings)
    except Exception:
        # Authentication, validation, and other reachable-API failures must not
        # turn an ordinary migration error into an infrastructure restart.
        return False


def _office_date(value: Any) -> str | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return f"{int(value[0]):04d}-{int(value[1]):02d}-{int(value[2]):02d}"
    if isinstance(value, str):
        match = re.match(r"\d{4}-\d{2}-\d{2}", value)
        return match.group(0) if match else value
    return None


def ensure_arissto_offices(api: FineractApi) -> dict[str, Any]:
    """Create or repair the fixed local Arissto office prerequisites through the API."""
    offices = {int(item["id"]): item for item in api.offices() if item.get("id") is not None}
    actions: list[dict[str, Any]] = []

    # A valid Fineract tenant always owns its root office. If it is absent, the
    # authenticated application user and tenant bootstrap are already corrupt,
    # so the office API cannot safely reconstruct it.
    if 1 not in offices:
        raise RuntimeError("Fineract root office 1 is missing; restore a valid tenant baseline")

    for expected in ARISSTO_OFFICES:
        office_id = int(expected["id"])
        office = offices.get(office_id)
        payload = {
            "name": expected["name"],
            "externalId": expected["externalId"],
            "openingDate": expected["openingDate"],
            "dateFormat": "yyyy-MM-dd",
            "locale": "en",
        }
        if expected["parentId"] is not None:
            payload["parentId"] = expected["parentId"]

        if office is None:
            result = api.request("POST", "offices", payload)
            created_id = result.get("officeId") or result.get("resourceId") or result.get("entityId")
            if int(created_id or 0) != office_id:
                raise RuntimeError(
                    f"Created Arissto branch {expected['branch']} as office {created_id}; "
                    f"the migration contract requires office {office_id}"
                )
            actions.append({"office_id": office_id, "branch": expected["branch"], "action": "created"})
            continue

        actual_parent = office.get("parentId")
        expected_parent = expected["parentId"]
        differs = (
            office.get("name") != expected["name"]
            or str(office.get("externalId") or "") != expected["externalId"]
            or _office_date(office.get("openingDate")) != expected["openingDate"]
            or (expected_parent is not None and int(actual_parent or 0) != expected_parent)
        )
        if differs:
            api.request("PUT", f"offices/{office_id}", payload)
            actions.append({"office_id": office_id, "branch": expected["branch"], "action": "updated"})
        else:
            actions.append({"office_id": office_id, "branch": expected["branch"], "action": "unchanged"})

    refreshed = {int(item["id"]): item for item in api.offices() if item.get("id") is not None}
    for expected in ARISSTO_OFFICES:
        office = refreshed.get(int(expected["id"]))
        if office is None or _office_date(office.get("openingDate")) != expected["openingDate"]:
            raise RuntimeError(f"Arissto office {expected['id']} failed post-bootstrap verification")
    return {"performed": True, "actions": actions}


def _api_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value.get("pageItems") or value.get("content") or []
    return []


def _enum_identifier(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def ensure_financial_activity_mappings(
    api: FineractApi,
    prerequisites: dict[str, Any] | None,
    selected_services: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Create reviewed workflow-scoped accounting mappings through the Fineract API."""
    configured = (prerequisites or {}).get("financial_activity_mappings", [])
    selected = set(selected_services)
    required = [
        item for item in configured
        if selected.intersection(item.get("required_by_services", []))
    ]
    if not required:
        return {"performed": False, "actions": []}

    gl_accounts = _api_items(api.request("GET", "glaccounts"))
    mappings = _api_items(api.request("GET", "financialactivityaccounts"))
    actions: list[dict[str, Any]] = []

    for expected in required:
        activity_id = int(expected["financial_activity_id"])
        gl_code = str(expected["gl_code"])
        matches = [row for row in gl_accounts if str(row.get("glCode") or "") == gl_code]
        if len(matches) != 1:
            raise RuntimeError(
                f"Financial activity {activity_id} requires exactly one GL account {gl_code}; "
                f"found {len(matches)}"
            )
        account = matches[0]
        if (
            bool(account.get("disabled"))
            or _enum_identifier(account.get("type")) != int(expected["gl_classification"])
            or _enum_identifier(account.get("usage")) != int(expected["gl_usage"])
        ):
            raise RuntimeError(
                f"GL account {gl_code} does not satisfy the reviewed financial activity contract"
            )

        activity_matches = [
            row for row in mappings
            if _enum_identifier(row.get("financialActivityData")) == activity_id
        ]
        if len(activity_matches) > 1:
            raise RuntimeError(f"Financial activity {activity_id} has multiple account mappings")
        if activity_matches:
            mapped_account = activity_matches[0].get("glAccountData") or {}
            if (
                _enum_identifier(mapped_account) != int(account["id"])
                or str(mapped_account.get("glCode") or "") != gl_code
            ):
                raise RuntimeError(
                    f"Financial activity {activity_id} is already mapped to a different GL account"
                )
            actions.append({
                "financial_activity_id": activity_id,
                "gl_code": gl_code,
                "action": "unchanged",
            })
            continue

        api.request("POST", "financialactivityaccounts", {
            "financialActivityId": activity_id,
            "glAccountId": int(account["id"]),
        })
        mappings = _api_items(api.request("GET", "financialactivityaccounts"))
        created = [
            row for row in mappings
            if _enum_identifier(row.get("financialActivityData")) == activity_id
            and _enum_identifier(row.get("glAccountData")) == int(account["id"])
            and str((row.get("glAccountData") or {}).get("glCode") or "") == gl_code
        ]
        if len(created) != 1:
            raise RuntimeError(f"Financial activity {activity_id} failed post-bootstrap verification")
        actions.append({
            "financial_activity_id": activity_id,
            "gl_code": gl_code,
            "action": "created",
        })

    return {"performed": True, "actions": actions}


def _restart_local_fineract(settings: Settings, controls: FineractRestartControls) -> None:
    if settings.target.name != "local":
        raise ValueError("Automatic Fineract restart is strictly local")
    # Recheck immediately so an already-recovered API is never restarted.
    if _fineract_api_ready(settings):
        return
    try:
        subprocess.run(
            list(controls.command), cwd=FINERACT_ROOT, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=controls.timeout_seconds, check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Local Fineract restart command timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Local Fineract restart command failed with exit code {exc.returncode}"
        ) from exc

    deadline = time.monotonic() + controls.timeout_seconds
    while time.monotonic() < deadline:
        if _fineract_api_ready(settings):
            return
        time.sleep(min(controls.poll_seconds, max(0.0, deadline - time.monotonic())))
    raise RuntimeError("Local Fineract API did not become ready after restart")


def reset_local_fineract(
    settings: Settings, tenant: str, confirmation: str,
    reset_controls: FineractResetControls | None = None,
    restart_controls: FineractRestartControls | None = None,
) -> dict[str, Any]:
    """Restore one disposable local tenant baseline, then bring Fineract back."""
    if settings.target.name != "local":
        raise ValueError("Fineract baseline reset is strictly local")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", tenant or "") or tenant == "default":
        raise ValueError("Reset requires a non-default disposable tenant identifier")
    if settings.target.tenant != tenant:
        raise ValueError(
            f"Reset tenant {tenant!r} does not match configured local API tenant "
            f"{settings.target.tenant!r}"
        )
    pg_url = settings.target.pg_url or ""
    database = urlparse(pg_url).path.lstrip("/").split("?", 1)[0]
    if not database:
        raise ValueError("Reset requires FINERACT_LOCAL_PG_URL for the disposable tenant")
    expected_confirmation = f"{tenant}:{database}"
    if confirmation != expected_confirmation:
        raise ValueError(f"Reset confirmation must be exactly {expected_confirmation}")

    reset_controls = reset_controls or FineractResetControls.configured()
    restart_controls = restart_controls or FineractRestartControls.configured()
    reset_script = FINERACT_ROOT / "scripts" / "reset-test-tenant.sh"
    if not reset_script.is_file():
        raise RuntimeError("The local test-tenant reset tool is unavailable")

    try:
        subprocess.run(
            list(reset_controls.stop_command), cwd=FINERACT_ROOT, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=reset_controls.timeout_seconds, check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Stopping local Fineract timed out; the tenant was not reset") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Stopping local Fineract failed with exit code {exc.returncode}; the tenant was not reset"
        ) from exc

    reset_error: Exception | None = None
    try:
        subprocess.run(
            [str(reset_script), "reset", tenant, "--confirm", confirmation],
            cwd=FINERACT_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=reset_controls.timeout_seconds,
            check=True,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        reset_error = exc

    try:
        _restart_local_fineract(settings, restart_controls)
    except Exception as restart_error:
        if reset_error:
            raise RuntimeError("Tenant reset failed, and local Fineract could not be restarted") from restart_error
        raise
    if reset_error:
        if isinstance(reset_error, subprocess.TimeoutExpired):
            raise RuntimeError("Tenant reset timed out; local Fineract was restarted") from reset_error
        raise RuntimeError(
            f"Tenant reset failed with exit code {reset_error.returncode}; local Fineract was restarted"
        ) from reset_error
    return {"performed": True, "tenant": tenant, "target": "local"}


def failure_fingerprint(
    service_id: str, phase: str, source_key: str | None, error_code: str | None
) -> str:
    material = "|".join((service_id, phase, source_key or "", error_code or ""))
    return hashlib.sha256(material.encode()).hexdigest()


def _safe_message(value: object, limit: int = 2000) -> str:
    return str(value).replace("\x00", "")[:limit]


def ensure_active_accounting_cutoff(
    api: FineractApi, snapshot: dict[str, Any]
) -> dict[str, Any]:
    expected_date = str(snapshot["date"])
    expected_timezone = str(snapshot["timezone"])
    try:
        current = api.request("GET", "accountingcutoff")
    except FineractError as exc:
        not_configured = (
            exc.status_code == 403
            and "error.msg.accounting.cutoff.not.configured" in str(exc)
        )
        if exc.status_code != 404 and not not_configured:
            raise
        current = None

    if current is not None:
        lifecycle = str(current.get("lifecycleState") or "").upper()
        current_date = str(current.get("cutoffDate") or "")
        current_timezone = str(current.get("timezoneId") or "")
        if lifecycle == "SEALED":
            raise RuntimeError("Tenant accounting cutoff is sealed")
        if lifecycle == "ACTIVE":
            if (current_date, current_timezone) != (expected_date, expected_timezone):
                raise RuntimeError("Active tenant accounting cutoff does not match workflow plan")
            return current
        if lifecycle != "DRAFT":
            raise RuntimeError(
                f"Unsupported tenant accounting cutoff state: {lifecycle or 'missing'}"
            )

    if current is None or (
        str(current.get("cutoffDate") or ""), str(current.get("timezoneId") or "")
    ) != (expected_date, expected_timezone):
        current = api.request("POST", "accountingcutoff", {
            "cutoffDate": expected_date,
            "timezoneId": expected_timezone,
        })
    if str(current.get("lifecycleState") or "").upper() != "DRAFT":
        raise RuntimeError("Tenant accounting cutoff configuration did not enter DRAFT")
    active = api.request("POST", "accountingcutoff/activate", {})
    if (
        str(active.get("lifecycleState") or "").upper() != "ACTIVE"
        or str(active.get("cutoffDate") or "") != expected_date
        or str(active.get("timezoneId") or "") != expected_timezone
    ):
        raise RuntimeError("Tenant accounting cutoff activation did not match workflow plan")
    return active


def assert_scheduler_paused(api: FineractApi) -> dict[str, Any]:
    """Fail closed unless the tenant scheduler was paused by the operator."""
    current = api.request("GET", "scheduler")
    active = current.get("active")
    if not isinstance(active, bool):
        raise RuntimeError("Fineract scheduler status did not return an active flag")
    if active:
        raise RuntimeError("Fineract scheduler must be paused during migration")
    return {"active": False}


def bind_active_accounting_cutoff(
    snapshot: dict[str, Any], configuration: dict[str, Any]
) -> dict[str, Any]:
    """Bind a workflow cutoff to one exact ACTIVE tenant configuration."""
    lifecycle = str(configuration.get("lifecycleState") or "").upper()
    actual_date = str(configuration.get("cutoffDate") or "")
    actual_timezone = str(configuration.get("timezoneId") or "")
    revision = configuration.get("configurationRevision")
    configuration_hash = str(configuration.get("configurationHash") or "")
    if lifecycle != "ACTIVE":
        raise RuntimeError("Tenant accounting cutoff must be ACTIVE")
    if (actual_date, actual_timezone) != (
        str(snapshot.get("date") or ""), str(snapshot.get("timezone") or "")
    ):
        raise RuntimeError("Active tenant accounting cutoff does not match workflow plan")
    if not isinstance(revision, int) or revision <= 0 or not configuration_hash:
        raise RuntimeError("Active tenant accounting cutoff has no stable revision/hash")
    return {
        **snapshot,
        "configuration_revision": revision,
        "configuration_hash": configuration_hash,
        "lifecycle_state": lifecycle,
    }


def verify_active_accounting_cutoff(
    api: FineractApi, snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Refuse a child plan whose exact tenant cutoff binding has drifted."""
    required = ("configuration_revision", "configuration_hash", "lifecycle_state")
    if not set(required).issubset(snapshot):
        raise RuntimeError("Child plan is not bound to an active tenant accounting cutoff")
    bound = bind_active_accounting_cutoff(
        snapshot, api.request("GET", "accountingcutoff")
    )
    for field in required:
        if snapshot[field] != bound[field]:
            raise RuntimeError(f"Tenant accounting cutoff {field} changed after planning")
    return bound


def pre_cutoff_native_gl_report(
    settings: Settings, snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Return an aggregate-only proof that migration produced no historical native GL."""
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for the accounting boundary check")
    with postgres_connection(settings.target.pg_url) as conn:
        row = conn.execute(
            "SELECT COUNT(*)::bigint,COUNT(DISTINCT transaction_id)::bigint,"
            "MIN(entry_date),MAX(entry_date) FROM acc_gl_journal_entry "
            "WHERE manual_entry=FALSE AND entry_date < %s",
            (snapshot["date"],),
        ).fetchone()
    report = {
        "cutoff_date": snapshot["date"],
        "native_entry_count": int(row[0]),
        "native_transaction_count": int(row[1]),
        "first_entry_date": row[2].isoformat() if row[2] is not None else None,
        "last_entry_date": row[3].isoformat() if row[3] is not None else None,
    }
    report["ok"] = report["native_entry_count"] == 0
    return report


def assert_zero_pre_cutoff_native_gl(
    settings: Settings, snapshot: dict[str, Any]
) -> dict[str, Any]:
    report = pre_cutoff_native_gl_report(settings, snapshot)
    if not report["ok"]:
        raise RuntimeError(
            "Accounting boundary violation: found "
            f"{report['native_entry_count']} native GL entries before {snapshot['date']}"
        )
    return report


def inspect_local_workflow(identifier: str) -> dict[str, Any]:
    return inspect_workflow(load_workflow(identifier))


def build_workflow_plan(
    settings: Settings, state: State, identifier: str, cycle_id: str,
    loan_controls: LoanApplyControls | None = None,
    fineract_restart_controls: FineractRestartControls | None = None,
    selected_services: list[str] | tuple[str, ...] | None = None,
    dte_controls: DteApplyControls | None = None,
    accounting_periods: list[str] | tuple[str, ...] | None = None,
    resume_from_run_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if settings.target.name != "local":
        raise ValueError("Workflow orchestration is strictly local; target must be local")
    cycle = state.require_cycle(cycle_id, settings.target.fingerprint)
    definition = load_workflow(identifier)
    if selected_services is not None:
        definition = select_workflow_services(definition, selected_services)
    report = require_workflow_ready(definition)
    target_report = preflight(settings)
    if target_report.get("ok") is False:
        raise RuntimeError("Local target preflight failed")
    loan_controls = loan_controls or LoanApplyControls.configured()
    dte_controls = dte_controls or DteApplyControls.configured()
    fineract_restart_controls = fineract_restart_controls or FineractRestartControls.configured()
    accounting_periods = tuple(dict.fromkeys(accounting_periods or ()))
    if any(not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", period) for period in accounting_periods):
        raise ValueError("Accounting period contains an unsafe component")
    satisfied_services: dict[str, dict[str, Any]] = {}
    parent_run: dict[str, Any] | None = None
    if resume_from_run_id:
        parent_run = state.workflow_run(resume_from_run_id)
        if parent_run["target_fingerprint"] != settings.target.fingerprint:
            raise ValueError("Parent workflow run belongs to a different target fingerprint")
        if parent_run["status"] not in {"completed", "failed", "interrupted"}:
            raise ValueError(
                "Resumed planning requires a completed, failed, or interrupted parent workflow run"
            )
        parent_plan = state.workflow_plan(parent_run["workflow_plan_id"])
        if parent_plan["document"].get("accounting_cutoff") != state.accounting_cutoff:
            raise ValueError("Parent workflow run uses a different accounting cutoff")
        requested = set(selected_services or ())
        for service_id, step in _latest_steps(state, resume_from_run_id).items():
            if service_id not in report["ordered_services"] or service_id in requested:
                continue
            if (
                step["status"] == "completed"
                and step.get("child_run_id")
                and step.get("summary", {}).get("reconciliation_ok") is True
            ):
                satisfied_services[service_id] = {
                    "workflow_run_id": resume_from_run_id,
                    "workflow_step_id": step["id"],
                    "child_run_id": step["child_run_id"],
                    "child_plan_id": step.get("plan_id"),
                    "action": "validate-and-skip",
                }
    document = {
        "workflow_id": definition.identifier,
        "workflow_version": definition.version,
        "definition_hash": definition.definition_hash,
        "ordered_services": report["ordered_services"],
        "readiness": {
            "blockers": report["blockers"],
            "warnings": report["warnings"],
        },
        "definition": definition.document,
        "target_fingerprint": settings.target.fingerprint,
        "preflight": target_report,
        "sync_cycle": {**cycle, "state_path": str(settings.state_path)},
        "runtime_controls": {
            "loans": {
                "workers": loan_controls.workers,
                "pause_seconds": loan_controls.pause_seconds,
                "recovery_attempts": loan_controls.recovery_attempts,
            },
            "dte-history": {
                "workers": dte_controls.workers,
                "batch_size": dte_controls.batch_size,
            },
            "fineract_restart": {
                "attempts": fineract_restart_controls.attempts,
                "timeout_seconds": fineract_restart_controls.timeout_seconds,
                "poll_seconds": fineract_restart_controls.poll_seconds,
                "command": list(fineract_restart_controls.command),
            },
        },
    }
    if parent_run is not None:
        document.update({
            "run_mode": "resumed",
            "parent_workflow_run_id": resume_from_run_id,
            "satisfied_services": satisfied_services,
            "service_actions": {
                service_id: (
                    "validate-and-skip" if service_id in satisfied_services else "continue"
                )
                for service_id in report["ordered_services"]
            },
        })
    if "accounting-journal-entries" in report["ordered_services"]:
        document["runtime_controls"]["accounting-journal-entries"] = {
            "scope": "source-periods" if accounting_periods else "full-company",
            "source_periods": list(accounting_periods),
        }
    plan_id = state.save_workflow_plan(
        definition.identifier, definition.version, definition.definition_hash,
        settings.target.name, settings.target.fingerprint, document,
    )
    return plan_id, document


def _process_is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def refresh_workflow_run(state: State, run_id: str) -> dict[str, Any]:
    run = state.workflow_run(run_id)
    if run["status"] in {"queued", "running"} and run["runner_pid"] and not _process_is_alive(run["runner_pid"]):
        state.interrupt_workflow_run(run_id, "The recorded local runner process is no longer active")
        run = state.workflow_run(run_id)
    return run


def workflow_report(state: State, run_id: str) -> dict[str, Any]:
    run = refresh_workflow_run(state, run_id)
    return {
        "sync_cycle": {**state.cycle_metadata(), "state_path": str(state.path)},
        "workflow_run": run,
        "steps": state.workflow_steps(run_id),
        "failures": state.workflow_failures(run_id),
        "failure_links": state.workflow_failure_links(run_id),
        "events": state.workflow_events(run_id),
        "event_links": state.workflow_event_links(run_id),
    }


@contextmanager
def target_workflow_lock(settings: Settings) -> Iterator[None]:
    lock_path = settings.state_path.parent / f"workflow-{settings.target.fingerprint}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another workflow is already running for this local target") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _latest_steps(state: State, run_id: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for step in state.workflow_steps(run_id):
        latest[step["service_id"]] = step
    return latest


def _record_failure(
    state: State, run_id: str, step_id: str | None, service_id: str, phase: str,
    source_key: str | None, item_status: str, error_code: str | None,
    error_message: str | None,
) -> str:
    return state.record_workflow_failure(
        run_id, step_id, service_id, phase, source_key, item_status,
        error_code, _safe_message(error_message) if error_message else None,
        failure_fingerprint(service_id, phase, source_key, error_code),
    )


def _record_child_item_failures(
    state: State, workflow_run_id: str, step: dict[str, Any], child_run_id: str,
    document: dict[str, Any],
) -> list[str]:
    failure_ids = []
    failures_by_source: dict[str, str] = {}
    for item in state.run_items(child_run_id):
        if item["status"] not in FAILURE_ITEM_STATUSES:
            continue
        failure_id = _record_failure(
            state, workflow_run_id, step["id"], step["service_id"], "apply",
            item["source_key"], item["status"], item.get("error_code"), None,
        )
        failure_ids.append(failure_id)
        failures_by_source[item["source_key"]] = failure_id

    for action in document.get("actions", []):
        dependent_failure = failures_by_source.get(str(action.get("source_key") or ""))
        if not dependent_failure:
            continue
        for dependency in action.get("depends_on", []):
            upstream_failure = failures_by_source.get(str(dependency))
            if upstream_failure:
                state.link_workflow_failure(dependent_failure, upstream_failure, "blocked-by")
    return failure_ids


def _record_plan_failures(
    state: State, workflow_run_id: str, step: dict[str, Any], document: dict[str, Any],
) -> list[str]:
    failure_ids = []
    for action in document.get("actions", []):
        action_name = str(action.get("action") or "")
        if action_name not in PLAN_FAILURE_ACTIONS:
            continue
        source_key = action.get("source_key") or action.get("entity_source_key")
        reason = action.get("reason") or action.get("error_code") or action_name
        failure_ids.append(_record_failure(
            state, workflow_run_id, step["id"], step["service_id"], "plan",
            str(source_key) if source_key is not None else None,
            "planned-failure", str(reason), None,
        ))
    return failure_ids


def _dependencies() -> dict[str, list[str]]:
    return {service["id"]: service.get("depends_on", []) for service in load_registry()["services"]}


def _link_exact_source_lineage(
    state: State, run_id: str, dependencies: dict[str, list[str]],
) -> None:
    ancestors: dict[str, set[str]] = {}

    def collect(service_id: str) -> set[str]:
        if service_id not in ancestors:
            direct = set(dependencies.get(service_id, []))
            ancestors[service_id] = direct | {item for dependency in direct for item in collect(dependency)}
        return ancestors[service_id]

    failures = state.workflow_failures(run_id)
    for failure in failures:
        if not failure["source_key"]:
            continue
        for related in failures:
            if related["id"] == failure["id"] or related["source_key"] != failure["source_key"]:
                continue
            if related["service_id"] in collect(failure["service_id"]):
                state.link_workflow_failure(failure["id"], related["id"], "same-source-key")


def _execute_workflow(settings: Settings, state: State, run_id: str, cycle_id: str) -> dict[str, Any]:
    if settings.target.name != "local":
        raise ValueError("Workflow orchestration is strictly local; target must be local")
    state.require_cycle(cycle_id, settings.target.fingerprint)
    run = state.workflow_run(run_id)
    plan = state.workflow_plan(run["workflow_plan_id"])
    state.adopt_accounting_cutoff(plan["document"]["accounting_cutoff"])
    if plan["target_fingerprint"] != settings.target.fingerprint:
        raise ValueError("Workflow plan belongs to a different local target fingerprint")
    current_definition = load_workflow(plan["workflow_id"])
    frozen_selection = plan["document"].get("definition", {}).get("selection")
    if frozen_selection is not None:
        if frozen_selection.get("mode") != "dependency-closure":
            raise ValueError("Workflow plan contains an unsupported service selection")
        requested_services = frozen_selection.get("requested_services")
        if not isinstance(requested_services, list) or not requested_services:
            raise ValueError("Workflow plan contains an invalid service selection")
        current_definition = select_workflow_services(
            current_definition, requested_services,
        )
    if current_definition.definition_hash != plan["definition_hash"]:
        raise ValueError("Workflow definition changed after planning; create a new workflow plan")
    require_workflow_ready(current_definition)

    frozen_controls = plan["document"].get("runtime_controls", {}).get("loans", {})
    loan_controls = LoanApplyControls.configured(
        frozen_controls.get("workers"),
        frozen_controls.get("pause_seconds"),
        frozen_controls.get("recovery_attempts"),
    )
    frozen_dte_controls = plan["document"].get("runtime_controls", {}).get("dte-history", {})
    dte_controls = DteApplyControls.configured(
        frozen_dte_controls.get("workers"), frozen_dte_controls.get("batch_size"),
    )
    frozen_restart = plan["document"].get("runtime_controls", {}).get("fineract_restart", {})
    restart_controls = (
        FineractRestartControls(
            attempts=int(frozen_restart["attempts"]),
            timeout_seconds=float(frozen_restart["timeout_seconds"]),
            poll_seconds=float(frozen_restart["poll_seconds"]),
            command=tuple(frozen_restart["command"]),
        )
        if frozen_restart
        else FineractRestartControls(attempts=0)
    )
    frozen_accounting = plan["document"].get("runtime_controls", {}).get(
        "accounting-journal-entries", {}
    )
    runtime = ServiceRuntime(
        settings, state, loan_controls, dte_controls,
        tuple(frozen_accounting.get("source_periods", ())),
    )
    dependencies = _dependencies()
    failures_by_service: dict[str, list[str]] = defaultdict(list)
    restart_attempts_used = 0

    with target_workflow_lock(settings):
        state.claim_workflow_run(run_id, os.getpid())
        try:
            office_bootstrap = ensure_arissto_offices(FineractApi(settings.target))
            state.record_workflow_event(
                run_id, "arissto-offices-ready", "workflow-prerequisite",
                status="ready", details=office_bootstrap,
            )
            try:
                prerequisite_bootstrap = ensure_financial_activity_mappings(
                    FineractApi(settings.target),
                    plan["document"]["definition"].get("target_prerequisites"),
                    plan["document"]["ordered_services"],
                )
            except Exception as exc:
                state.record_workflow_event(
                    run_id, "target-prerequisite-failed", "workflow-prerequisite",
                    status="failed", severity="error", error_code=type(exc).__name__,
                    message=_safe_message(exc),
                )
                raise
            if prerequisite_bootstrap["performed"]:
                state.record_workflow_event(
                    run_id, "target-prerequisites-ready", "workflow-prerequisite",
                    status="ready", details=prerequisite_bootstrap,
                )
            cutoff_policy = plan["document"]["definition"].get(
                "accounting_cutoff_policy", "snapshot-only"
            )
            if cutoff_policy == "activate-frozen-plan":
                cutoff_api = FineractApi(settings.target)
                scheduler_status = assert_scheduler_paused(cutoff_api)
                state.record_workflow_event(
                    run_id, "fineract-scheduler-pause-verified", "workflow-prerequisite",
                    status="verified", details=scheduler_status,
                )
                active_cutoff = ensure_active_accounting_cutoff(
                    cutoff_api, plan["document"]["accounting_cutoff"]
                )
                bound_cutoff = bind_active_accounting_cutoff(
                    plan["document"]["accounting_cutoff"], active_cutoff
                )
                state.adopt_accounting_cutoff(bound_cutoff)
                state.record_workflow_event(
                    run_id, "accounting-cutoff-active", "workflow-prerequisite",
                    status="active",
                    details={
                        "cutoff_date": active_cutoff.get("cutoffDate"),
                        "timezone": active_cutoff.get("timezoneId"),
                        "revision": active_cutoff.get("configurationRevision"),
                        "hash": active_cutoff.get("configurationHash"),
                    },
                )
                baseline_gl = assert_zero_pre_cutoff_native_gl(settings, bound_cutoff)
                state.record_workflow_event(
                    run_id, "workflow-pre-cutoff-native-gl-verified",
                    "workflow-prerequisite", status="verified", details=baseline_gl,
                )
            for service_id in plan["document"]["ordered_services"]:
                latest = _latest_steps(state, run_id)
                step = latest[service_id]
                if step["status"] == "completed":
                    state.record_workflow_event(
                        run_id, "workflow-step-skipped", "resume",
                        step_id=step["id"], service_id=service_id,
                        attempt=step["attempt"], status="completed",
                        details={"reason": "already-completed"},
                    )
                    continue
                satisfied = plan["document"].get("satisfied_services", {}).get(service_id)
                if satisfied is not None:
                    phase = "resume-prerequisite-validation"
                    try:
                        state.heartbeat_workflow(run_id, service_id, phase)
                        state.update_workflow_step(
                            step["id"], status="running", phase=phase, start=True,
                        )
                        reconciliation = runtime.reconcile(
                            service_id, satisfied["child_run_id"],
                        )
                        if not reconciliation.get("ok"):
                            raise RuntimeError(
                                "Parent service reconciliation is no longer valid"
                            )
                        summary = {
                            "reconciliation_ok": True,
                            "reconciliation_counts": reconciliation.get("counts", {}),
                            "satisfied_by_parent_workflow_run": satisfied["workflow_run_id"],
                            "parent_child_run_id": satisfied["child_run_id"],
                            "execution_action": "validated-and-skipped",
                        }
                        state.update_workflow_step(
                            step["id"], status="completed", phase="completed",
                            plan_id=satisfied.get("child_plan_id"),
                            child_run_id=satisfied["child_run_id"], summary=summary,
                            finish=True,
                        )
                        state.record_workflow_event(
                            run_id, "workflow-parent-prerequisite-validated", phase,
                            step_id=step["id"], service_id=service_id,
                            attempt=step["attempt"], status="completed",
                            details=summary,
                        )
                    except Exception as exc:
                        code = type(exc).__name__
                        message = _safe_message(exc)
                        failure_id = _record_failure(
                            state, run_id, step["id"], service_id, phase, None,
                            "failed", code, message,
                        )
                        failures_by_service[service_id].append(failure_id)
                        state.update_workflow_step(
                            step["id"], status="failed", phase=phase,
                            error_code=code, error_message=message, finish=True,
                        )
                    continue
                recovery_child = next(
                    (
                        prior for prior in reversed(state.workflow_steps(run_id))
                        if prior["service_id"] == service_id and prior.get("child_run_id")
                    ),
                    None,
                )
                if step["status"] != "pending":
                    step = state.retry_workflow_step(run_id, service_id)

                blocked_by = [
                    dependency for dependency in dependencies[service_id]
                    if latest.get(dependency, {}).get("status") != "completed"
                ]
                if blocked_by:
                    message = f"Blocked by unsuccessful dependencies: {', '.join(blocked_by)}"
                    state.update_workflow_step(
                        step["id"], status="blocked", phase="dependency-gate",
                        error_code="upstream-dependency-failed", error_message=message,
                        start=True, finish=True,
                    )
                    blocked_failure = _record_failure(
                        state, run_id, step["id"], service_id, "dependency-gate", None,
                        "blocked", "upstream-dependency-failed", message,
                    )
                    failures_by_service[service_id].append(blocked_failure)
                    for dependency in blocked_by:
                        for upstream_failure in failures_by_service[dependency]:
                            state.link_workflow_failure(blocked_failure, upstream_failure, "blocked-by")
                    continue

                while True:
                    phase = "prepare"
                    try:
                        state.heartbeat_workflow(run_id, service_id, phase)
                        state.update_workflow_step(step["id"], status="running", phase=phase, start=True)
                        preparation = runtime.prepare(service_id)
                        if preparation.get("performed"):
                            state.record_workflow_event(
                                run_id, "workflow-service-prerequisites-ready", phase,
                                step_id=step["id"], service_id=service_id,
                                attempt=step["attempt"], status="ready", details=preparation,
                            )

                        phase = "inspect"
                        state.heartbeat_workflow(run_id, service_id, phase)
                        state.update_workflow_step(step["id"], phase=phase)
                        inspection = runtime.inspect(service_id)
                        state.save_inspection(
                            settings.target.name, settings.target.fingerprint, service_id,
                            inspection["contract_hash"], inspection["schema_signature"], inspection["ready"],
                        )
                        if not inspection["ready"]:
                            raise RuntimeError("Service inspection reported readiness blockers")

                        if recovery_child is not None:
                            recovery_plan = state.plan(recovery_child["plan_id"])
                            recovery_cutoff = recovery_plan["document"].get("accounting_cutoff")
                            if (
                                recovery_plan["contract_hash"] != inspection["contract_hash"]
                                or recovery_cutoff != state.accounting_cutoff
                            ):
                                state.record_workflow_event(
                                    run_id, "workflow-stale-child-plan-discarded", "resume",
                                    step_id=step["id"], service_id=service_id,
                                    attempt=step["attempt"], status="stale",
                                    details={
                                        "previous_plan_id": recovery_child["plan_id"],
                                        "previous_contract_hash": recovery_plan["contract_hash"],
                                        "current_contract_hash": inspection["contract_hash"],
                                        "accounting_cutoff_changed": (
                                            recovery_cutoff != state.accounting_cutoff
                                        ),
                                    },
                                )
                                recovery_child = None

                        phase = "apply"
                        state.heartbeat_workflow(run_id, service_id, phase)
                        state.update_workflow_step(step["id"], phase=phase)
                        if recovery_child is not None:
                            child_plan_id = recovery_child["plan_id"]
                            child_plan = state.plan(child_plan_id)["document"]
                            if cutoff_policy == "activate-frozen-plan":
                                verify_active_accounting_cutoff(
                                    FineractApi(settings.target),
                                    child_plan["accounting_cutoff"],
                                )
                            child_run_id, counts = runtime.retry(
                                service_id, recovery_child["child_run_id"]
                            )
                            state.record_workflow_event(
                                run_id, "workflow-child-run-retried", phase,
                                step_id=step["id"], service_id=service_id,
                                attempt=step["attempt"], status="running",
                                details={
                                    "previous_child_run_id": recovery_child["child_run_id"],
                                    "frozen_plan_id": child_plan_id,
                                    "retry_child_run_id": child_run_id,
                                },
                            )
                        else:
                            phase = "plan"
                            state.heartbeat_workflow(run_id, service_id, phase)
                            state.update_workflow_step(step["id"], phase=phase)
                            child_plan_id, child_plan = runtime.plan(service_id)
                            state.update_workflow_step(step["id"], plan_id=child_plan_id)
                            failures_by_service[service_id].extend(
                                _record_plan_failures(state, run_id, step, child_plan)
                            )
                            if child_plan.get("applicable") is False:
                                raise RuntimeError("Service plan is not applicable")
                            phase = "apply"
                            state.heartbeat_workflow(run_id, service_id, phase)
                            state.update_workflow_step(step["id"], phase=phase)
                            if cutoff_policy == "activate-frozen-plan":
                                verify_active_accounting_cutoff(
                                    FineractApi(settings.target),
                                    child_plan["accounting_cutoff"],
                                )
                            child_run_id, counts = runtime.apply(service_id, child_plan_id)
                        state.update_workflow_step(
                            step["id"], plan_id=child_plan_id, child_run_id=child_run_id
                        )
                        failures_by_service[service_id].extend(
                            _record_child_item_failures(
                                state, run_id, step, child_run_id, child_plan
                            )
                        )

                        phase = "reconcile"
                        state.heartbeat_workflow(run_id, service_id, phase)
                        state.update_workflow_step(step["id"], phase=phase)
                        reconciliation = runtime.reconcile(service_id, child_run_id)
                        summary = {
                            "plan_id": child_plan_id,
                            "run_id": child_run_id,
                            "apply_counts": counts,
                            "reconciliation_ok": bool(reconciliation.get("ok")),
                            "reconciliation_counts": reconciliation.get("counts", {}),
                        }
                        if not reconciliation.get("ok"):
                            raise RuntimeError("Service reconciliation failed")
                        if cutoff_policy == "activate-frozen-plan":
                            phase = "accounting-boundary"
                            state.heartbeat_workflow(run_id, service_id, phase)
                            state.update_workflow_step(step["id"], phase=phase)
                            verify_active_accounting_cutoff(
                                FineractApi(settings.target),
                                child_plan["accounting_cutoff"],
                            )
                            gl_report = assert_zero_pre_cutoff_native_gl(
                                settings, child_plan["accounting_cutoff"]
                            )
                            state.record_workflow_event(
                                run_id, "workflow-pre-cutoff-native-gl-verified", phase,
                                step_id=step["id"], service_id=service_id,
                                attempt=step["attempt"], status="verified",
                                details=gl_report,
                            )
                            summary["accounting_boundary"] = gl_report
                        state.update_workflow_step(
                            step["id"], status="completed", phase="completed",
                            summary=summary, finish=True,
                        )
                        break
                    except Exception as exc:
                        can_restart = (
                            restart_attempts_used < restart_controls.attempts
                            and _fineract_recovery_needed(settings, exc)
                        )
                        if can_restart:
                            restart_attempts_used += 1
                            try:
                                _restart_local_fineract(settings, restart_controls)
                            except Exception as restart_exc:
                                code = "fineract-restart-failed"
                                message = _safe_message(
                                    f"{exc}; automatic local recovery failed: {restart_exc}"
                                )
                                failure_id = _record_failure(
                                    state, run_id, step["id"], service_id, "fineract-recovery",
                                    None, "failed", code, message,
                                )
                                failures_by_service[service_id].append(failure_id)
                                state.update_workflow_step(
                                    step["id"], status="failed", phase="fineract-recovery",
                                    error_code=code, error_message=message, finish=True,
                                )
                                break

                            code = "fineract-recovered"
                            message = _safe_message(
                                f"{exc}; local Fineract recovered and the service step will retry"
                            )
                            failure_id = _record_failure(
                                state, run_id, step["id"], service_id, phase, None,
                                "recovered", code, message,
                            )
                            failures_by_service[service_id].append(failure_id)
                            state.update_workflow_step(
                                step["id"], status="failed", phase=phase,
                                error_code=code, error_message=message, finish=True,
                            )
                            step = state.retry_workflow_step(run_id, service_id)
                            continue

                        code = type(exc).__name__
                        message = _safe_message(exc)
                        failure_id = _record_failure(
                            state, run_id, step["id"], service_id, phase, None,
                            "failed", code, message,
                        )
                        failures_by_service[service_id].append(failure_id)
                        state.update_workflow_step(
                            step["id"], status="failed", phase=phase,
                            error_code=code, error_message=message, finish=True,
                        )
                        break

            _link_exact_source_lineage(state, run_id, dependencies)
            final_steps = _latest_steps(state, run_id)
            status_counts = Counter(step["status"] for step in final_steps.values())
            complete = bool(final_steps) and all(step["status"] == "completed" for step in final_steps.values())
            summary = {
                "step_statuses": dict(status_counts),
                "failure_count": len(state.workflow_failures(run_id)),
            }
            state.finish_workflow_run(run_id, "completed" if complete else "failed", summary)
        except BaseException as exc:
            interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
            code = "runner-interrupted" if interrupted else type(exc).__name__
            state.finish_workflow_run(
                run_id, "interrupted" if interrupted else "failed", {}, code, _safe_message(exc)
            )
            raise
    return workflow_report(state, run_id)


def execute_workflow(settings: Settings, state: State, run_id: str, cycle_id: str) -> dict[str, Any]:
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def terminate(_signum: int, _frame: object) -> None:
        raise SystemExit("Local workflow runner received SIGTERM")

    signal.signal(signal.SIGTERM, terminate)
    try:
        return _execute_workflow(settings, state, run_id, cycle_id)
    except BaseException as exc:
        run = state.workflow_run(run_id)
        if run["status"] in {"queued", "running"}:
            interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
            state.finish_workflow_run(
                run_id, "interrupted" if interrupted else "failed", {},
                "runner-interrupted" if interrupted else type(exc).__name__, _safe_message(exc),
            )
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)


def start_workflow(
    settings: Settings, state: State, workflow_plan_id: str, cycle_id: str,
    env_file: str | None = None,
) -> dict[str, Any]:
    if settings.target.name != "local":
        raise ValueError("Workflow orchestration is strictly local; target must be local")
    state.require_cycle(cycle_id, settings.target.fingerprint)
    plan = state.workflow_plan(workflow_plan_id)
    if plan["target_fingerprint"] != settings.target.fingerprint:
        raise ValueError("Workflow plan belongs to a different local target fingerprint")
    run_id = state.create_workflow_run(plan)
    log_dir = settings.state_path.parent / "workflow-runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{run_id}.log"
    command = [sys.executable, "-m", "arissto_sync.cli"]
    if env_file:
        command.extend(["--env-file", str(Path(env_file).resolve())])
    command.extend([
        "workflow", "execute", "--target", "local", "--cycle", cycle_id, "--run", run_id,
    ])
    try:
        with log_path.open("ab") as output:
            process = subprocess.Popen(
                command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
            )
    except Exception as exc:
        state.finish_workflow_run(
            run_id, "failed", {}, type(exc).__name__, f"Could not start local workflow runner: {_safe_message(exc)}"
        )
        raise
    state.set_workflow_runner(run_id, process.pid, str(log_path))
    return {
        "sync_cycle_id": cycle_id, "workflow_run_id": run_id, "status": "queued",
        "runner_pid": process.pid, "state_path": str(settings.state_path), "log_path": str(log_path),
    }


def resume_workflow(
    settings: Settings, state: State, run_id: str, cycle_id: str,
    env_file: str | None = None,
) -> dict[str, Any]:
    state.require_cycle(cycle_id, settings.target.fingerprint)
    run = refresh_workflow_run(state, run_id)
    if run["status"] not in {"failed", "interrupted"}:
        raise ValueError(f"Workflow run {run_id} cannot resume from status {run['status']}")
    state.queue_workflow_run(run_id)
    log_path = Path(run["log_path"] or settings.state_path.parent / "workflow-runs" / f"{run_id}.log")
    command = [sys.executable, "-m", "arissto_sync.cli"]
    if env_file:
        command.extend(["--env-file", str(Path(env_file).resolve())])
    command.extend([
        "workflow", "execute", "--target", "local", "--cycle", cycle_id, "--run", run_id,
    ])
    try:
        with log_path.open("ab") as output:
            process = subprocess.Popen(
                command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
            )
    except Exception as exc:
        state.finish_workflow_run(
            run_id, "failed", {}, type(exc).__name__, f"Could not resume local workflow runner: {_safe_message(exc)}"
        )
        raise
    state.set_workflow_runner(run_id, process.pid, str(log_path))
    return {
        "sync_cycle_id": cycle_id, "workflow_run_id": run_id, "status": "queued",
        "runner_pid": process.pid, "state_path": str(settings.state_path), "log_path": str(log_path),
    }


def stop_workflow(state: State, run_id: str) -> dict[str, Any]:
    run = refresh_workflow_run(state, run_id)
    if run["status"] != "running" or not run["runner_pid"]:
        raise ValueError(f"Workflow run {run_id} is not running")
    os.kill(int(run["runner_pid"]), signal.SIGTERM)
    return {"workflow_run_id": run_id, "signal": "SIGTERM", "status": "stopping"}
