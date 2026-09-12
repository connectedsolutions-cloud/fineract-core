from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
DEFAULT_MAX_RUN_LOG_BYTES = 50 * 1024 * 1024
DEFAULT_STALE_OPEN_DAYS = 2
DEFAULT_CLOSED_RETENTION_DAYS = 14
DEFAULT_MIN_CLOSED_CYCLES = 5
WARNING_NEEDLE = b"InsecureRequestWarning"


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _warning_count(path: Path) -> int:
    count = 0
    carry = b""
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            material = carry + chunk
            count += material.count(WARNING_NEEDLE)
            carry = material[-(len(WARNING_NEEDLE) - 1):]
    return count


def _read_state_metrics(path: Path) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "path": str(path.resolve()),
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else 0,
    }
    if not path.is_file():
        return metrics
    def inspect(connection: sqlite3.Connection) -> None:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "plans" in tables:
            row = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(LENGTH(document)),0) FROM plans"
            ).fetchone()
            metrics.update(plan_count=row[0], plan_document_bytes=row[1])
        for table, key in (("items", "item_count"), ("mappings", "mapping_count")):
            if table in tables:
                metrics[key] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if "workflow_runs" in tables:
            metrics["active_workflow_run_count"] = connection.execute(
                "SELECT COUNT(*) FROM workflow_runs WHERE status IN ('queued','running')"
            ).fetchone()[0]

    connection: sqlite3.Connection | None = None
    try:
        try:
            connection = sqlite3.connect(
                f"file:{path.resolve()}?mode=ro", uri=True, timeout=2
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            inspect(connection)
        except sqlite3.Error:
            if connection is not None:
                connection.close()
            connection = sqlite3.connect(
                f"file:{path.resolve()}?immutable=1", uri=True, timeout=2
            )
            connection.row_factory = sqlite3.Row
            inspect(connection)
            metrics["inspection_mode"] = "immutable-snapshot"
    except sqlite3.Error as error:
        metrics["inspection_error"] = str(error)
    finally:
        if connection is not None:
            connection.close()
    return metrics


def _parse_instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        instant = datetime.fromisoformat(value)
    except ValueError:
        return None
    return instant if instant.tzinfo else instant.replace(tzinfo=timezone.utc)


def storage_health(
    base_state_path: Path,
    *,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_run_log_bytes: int = DEFAULT_MAX_RUN_LOG_BYTES,
    stale_open_days: int = DEFAULT_STALE_OPEN_DAYS,
    clock: datetime | None = None,
) -> dict[str, Any]:
    state_root = base_state_path.resolve().parent
    now = clock or datetime.now(timezone.utc)
    findings: list[dict[str, Any]] = []
    cycle_reports: list[dict[str, Any]] = []
    catalog_path = state_root / "cycles.sqlite3"
    cycles: list[dict[str, Any]] = []

    if catalog_path.is_file():
        connection: sqlite3.Connection | None = None
        try:
            try:
                connection = sqlite3.connect(
                    f"file:{catalog_path.resolve()}?mode=ro", uri=True, timeout=2
                )
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            except sqlite3.Error:
                if connection is not None:
                    connection.close()
                connection = sqlite3.connect(
                    f"file:{catalog_path.resolve()}?immutable=1", uri=True, timeout=2
                )
                connection.row_factory = sqlite3.Row
            if "sync_cycles" in {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }:
                cycles = [dict(row) for row in connection.execute(
                    "SELECT * FROM sync_cycles ORDER BY created_at DESC"
                )]
        except sqlite3.Error as error:
            findings.append({
                "code": "cycle-catalog-unreadable", "severity": "warning", "message": str(error),
            })
        finally:
            if connection is not None:
                connection.close()

    total_log_bytes = 0
    total_warning_count = 0
    for cycle in cycles:
        state_path = Path(cycle["state_path"])
        cycle_dir = state_path.parent
        log_reports = []
        log_paths = [
            path for path in (cycle_dir / "workflow-runs").glob("*.log*")
            if path.name.endswith(".log") or path.name.endswith(".log.gz")
        ]
        for log_path in sorted(log_paths):
            size = log_path.stat().st_size
            compressed = log_path.name.endswith(".gz")
            warning_count = 0 if compressed else _warning_count(log_path)
            total_log_bytes += size
            total_warning_count += warning_count
            log_reports.append({
                "path": str(log_path.resolve()), "bytes": size,
                "compressed": compressed, "insecure_request_warning_count": warning_count,
            })
            if size >= max_run_log_bytes:
                findings.append({
                    "code": "large-run-log", "severity": "warning", "cycle_id": cycle["id"],
                    "path": str(log_path.resolve()), "bytes": size,
                    "message": "Workflow log exceeds the configured per-log budget.",
                })

        created_at = _parse_instant(cycle.get("created_at"))
        age_days = (now - created_at).total_seconds() / 86400 if created_at else None
        state_metrics = _read_state_metrics(state_path)
        report = {
            "id": cycle["id"], "status": cycle["status"], "created_at": cycle["created_at"],
            "closed_at": cycle.get("closed_at"), "age_days": round(age_days, 2) if age_days is not None else None,
            "bytes": _tree_size(cycle_dir), "state": state_metrics, "logs": log_reports,
        }
        cycle_reports.append(report)
        if (
            cycle["status"] == "open" and age_days is not None and age_days >= stale_open_days
            and not state_metrics.get("active_workflow_run_count", 0)
        ):
            findings.append({
                "code": "stale-open-cycle", "severity": "warning", "cycle_id": cycle["id"],
                "age_days": round(age_days, 2),
                "message": "Review and close this inactive cycle if its tenant baseline is no longer current.",
            })

    newest_cycle_id = cycle_reports[0]["id"] if cycle_reports else None
    for cycle in cycle_reports:
        if cycle["id"] != newest_cycle_id:
            findings.append({
                "code": "obsolete-cycle-retention-candidate", "severity": "warning",
                "cycle_id": cycle["id"], "bytes": cycle["bytes"],
                "message": "Only the newest local sync cycle is retained.",
            })

    legacy = _read_state_metrics(base_state_path)
    sqlite_bytes = legacy["bytes"] + sum(
        cycle["state"]["bytes"] for cycle in cycle_reports
    ) + (catalog_path.stat().st_size if catalog_path.is_file() else 0)
    total_bytes = _tree_size(state_root)
    if total_bytes >= max_total_bytes:
        findings.append({
            "code": "storage-budget-exceeded", "severity": "warning", "bytes": total_bytes,
            "budget_bytes": max_total_bytes,
            "message": "Arissto sync state exceeds the configured storage budget.",
        })
    if total_warning_count:
        findings.append({
            "code": "repeated-tls-warning-output", "severity": "warning",
            "count": total_warning_count, "bytes": total_log_bytes,
            "message": "Runner logs contain repeated TLS verification warnings.",
        })

    return {
        "ok": not findings,
        "state_root": str(state_root),
        "generated_at": now.isoformat(),
        "policy": {
            "max_total_bytes": max_total_bytes,
            "max_run_log_bytes": max_run_log_bytes,
            "stale_open_days": stale_open_days,
            "retained_local_cycles": 1,
        },
        "usage": {
            "total_bytes": total_bytes,
            "sqlite_bytes": sqlite_bytes,
            "workflow_log_bytes": total_log_bytes,
            "other_bytes": max(0, total_bytes - sqlite_bytes - total_log_bytes),
            "insecure_request_warning_count": total_warning_count,
        },
        "legacy_state": legacy,
        "cycles": cycle_reports,
        "findings": findings,
        "retention": {
            "active_cycle": "retain complete state",
            "obsolete_local_cycles": "delete databases, logs, summaries, and catalog entries",
            "note": "This command reports candidates only and never deletes files or rows.",
        },
    }
