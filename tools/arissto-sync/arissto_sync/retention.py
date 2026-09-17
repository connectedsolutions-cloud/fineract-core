from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cycles import CycleCatalog
from .state import State, now
from .storage_health import (
    DEFAULT_CLOSED_RETENTION_DAYS,
    DEFAULT_MIN_CLOSED_CYCLES,
    _parse_instant,
    _tree_size,
)


SUCCESS_LOG_DAYS = 7
FAILED_LOG_DAYS = 30
SUMMARY_DAYS = 90
APPLY_CONFIRMATION = "APPLY-RETENTION"
ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_SUCCESS_ITEM_STATUSES = {"succeeded", "unchanged", "recovered"}


def _age_days(value: str | None, clock: datetime) -> float | None:
    instant = _parse_instant(value)
    return (clock - instant).total_seconds() / 86400 if instant else None


def _readonly(path: Path) -> sqlite3.Connection:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=2)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except sqlite3.Error:
        if connection is not None:
            connection.close()
        connection = sqlite3.connect(f"file:{path.resolve()}?immutable=1", uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    return connection


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _cycle_snapshot(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"workflow_runs": [], "active_run_count": 0}
    if not path.is_file():
        return result
    with _readonly(path) as connection:
        tables = _tables(connection)
        if "workflow_runs" in tables:
            result["workflow_runs"] = [dict(row) for row in connection.execute(
                "SELECT id,workflow_id,status,created_at,started_at,finished_at,log_path,"
                "summary,error_code FROM workflow_runs ORDER BY created_at"
            )]
            result["active_run_count"] = sum(
                run["status"] in ACTIVE_STATUSES for run in result["workflow_runs"]
            )
    return result


def _catalog_cycles(base_state_path: Path) -> list[dict[str, Any]]:
    path = base_state_path.resolve().parent / "cycles.sqlite3"
    if not path.is_file():
        return []
    with _readonly(path) as connection:
        if "sync_cycles" not in _tables(connection):
            return []
        return [dict(row) for row in connection.execute(
            "SELECT * FROM sync_cycles ORDER BY created_at DESC"
        )]


def _validated_cycle_dir(base_state_path: Path, cycle: dict[str, Any]) -> Path:
    cycles_root = (base_state_path.resolve().parent / "cycles").resolve()
    expected = (cycles_root / str(cycle["id"])).resolve()
    actual = Path(cycle["state_path"]).resolve().parent
    if actual != expected or not actual.is_relative_to(cycles_root):
        raise ValueError(f"Cycle {cycle['id']!r} has an unsafe state path")
    return actual


def _log_action(
    cycle: dict[str, Any], run: dict[str, Any], clock: datetime,
) -> dict[str, Any] | None:
    log_value = run.get("log_path")
    if not log_value:
        return None
    cycle_dir = Path(cycle["state_path"]).resolve().parent
    path = Path(str(log_value)).resolve()
    if not path.is_relative_to(cycle_dir / "workflow-runs"):
        return {
            "action": "blocked-unsafe-log-path", "cycle_id": cycle["id"],
            "workflow_run_id": run["id"], "path": str(path),
        }
    raw_path = path.with_suffix("") if path.suffix == ".gz" else path
    compressed_path = Path(f"{raw_path}.gz")
    existing = compressed_path if compressed_path.is_file() else raw_path
    if not existing.is_file():
        return None
    age = _age_days(run.get("finished_at") or run.get("created_at"), clock)
    if age is None or run["status"] in ACTIVE_STATUSES:
        return None
    common = {
        "cycle_id": cycle["id"], "workflow_run_id": run["id"],
        "run_status": run["status"], "age_days": round(age, 2),
        "path": str(existing), "bytes": existing.stat().st_size,
    }
    if run["status"] == "completed":
        return {"action": "delete-success-log", **common} if age >= SUCCESS_LOG_DAYS else None
    if age >= FAILED_LOG_DAYS:
        return {"action": "delete-failed-log", **common}
    if existing.suffix != ".gz":
        return {"action": "compress-failed-log", **common, "output_path": str(compressed_path)}
    return None


def _historical_state_action(
    state_path: Path, *, cycle_id: str | None = None,
    target_fingerprints: set[str] | None = None,
) -> dict[str, Any] | None:
    """Plan safe payload compaction without removing audit identities or failures."""
    if not state_path.is_file():
        return None
    with _readonly(state_path) as connection:
        tables = _tables(connection)
        if not {"plans", "runs", "items"}.issubset(tables):
            return None
        where = ""
        args: list[Any] = []
        if target_fingerprints is not None:
            if not target_fingerprints:
                return None
            placeholders = ",".join("?" for _ in target_fingerprints)
            where = f" WHERE target_fingerprint IN ({placeholders})"
            args = sorted(target_fingerprints)
        runs = [dict(row) for row in connection.execute(
            "SELECT id,plan_id,target_fingerprint,block,started_at,status FROM runs"
            + where + " ORDER BY target_fingerprint,block,started_at DESC,id DESC", args,
        )]
        plan_run_statuses: dict[str, set[str]] = {}
        for run in runs:
            plan_run_statuses.setdefault(str(run["plan_id"]), set()).add(str(run["status"]))
        # A failed/interrupted/quarantined chain may still need its immutable payload
        # for diagnosis or retry. Only an entirely successful chain is compactable.
        executed_plan_ids = {
            plan_id for plan_id, statuses in plan_run_statuses.items()
            if statuses == {"completed"}
        }
        compact_plan_ids: list[str] = []
        original_document_bytes = 0
        if executed_plan_ids:
            placeholders = ",".join("?" for _ in executed_plan_ids)
            for row in connection.execute(
                f"SELECT id,document,LENGTH(document) AS bytes FROM plans WHERE id IN ({placeholders})",
                sorted(executed_plan_ids),
            ):
                document = _json_value(row["document"])
                if isinstance(document, dict) and "retention_compacted" in document:
                    continue
                compact_plan_ids.append(str(row["id"]))
                original_document_bytes += int(row["bytes"] or 0)

        latest_runs: dict[tuple[str, str], str] = {}
        for run in runs:
            key = (str(run["target_fingerprint"]), str(run["block"]))
            latest_runs.setdefault(key, str(run["id"]))
        selected_run_ids = set(latest_runs.values())
        superseded_run_ids = [
            str(run["id"]) for run in runs
            if str(run["id"]) not in selected_run_ids and run["status"] == "completed"
        ]
        delete_item_count = 0
        if superseded_run_ids:
            run_placeholders = ",".join("?" for _ in superseded_run_ids)
            status_placeholders = ",".join("?" for _ in TERMINAL_SUCCESS_ITEM_STATUSES)
            delete_item_count = int(connection.execute(
                f"SELECT COUNT(*) FROM items WHERE run_id IN ({run_placeholders}) "
                f"AND status IN ({status_placeholders})",
                [*superseded_run_ids, *sorted(TERMINAL_SUCCESS_ITEM_STATUSES)],
            ).fetchone()[0])
    if not compact_plan_ids and not delete_item_count:
        return None
    return {
        "action": "compact-historical-state", "state_path": str(state_path.resolve()),
        "cycle_id": cycle_id, "target_fingerprints": sorted(target_fingerprints or []),
        "compact_plan_ids": compact_plan_ids,
        "original_plan_document_bytes": original_document_bytes,
        "superseded_run_ids": superseded_run_ids,
        "delete_success_item_count": delete_item_count,
        "preserves": [
            "plan and run metadata", "latest run items per service block", "failed/quarantined items",
            "mappings", "links", "workflow failures and summaries",
        ],
    }


def _production_action(base_state_path: Path, fingerprint: str) -> dict[str, Any] | None:
    if not base_state_path.is_file():
        return None
    with _readonly(base_state_path) as connection:
        tables = _tables(connection)
        if not {"plans", "runs", "items"}.issubset(tables):
            return None
        runs = [dict(row) for row in connection.execute(
            "SELECT id,plan_id,block,status,started_at FROM runs "
            "WHERE target_fingerprint=? ORDER BY started_at DESC,id DESC",
            (fingerprint,),
        )]
        active = [run["id"] for run in runs if run["status"] == "running"]
        if active:
            return {
                "action": "blocked-production-active-run", "target_fingerprint": fingerprint,
                "active_run_ids": active,
            }
        latest_run = runs[0] if runs else None
        keep_run_ids = {latest_run["id"]} if latest_run else set()
        delete_run_ids = [run["id"] for run in runs if run["id"] not in keep_run_ids]
        keep_plan_ids = {latest_run["plan_id"]} if latest_run else set()
        plans = [dict(row) for row in connection.execute(
            "SELECT id,block,created_at FROM plans WHERE target_fingerprint=? "
            "ORDER BY created_at DESC,id DESC",
            (fingerprint,),
        )]
        delete_plan_ids = [plan["id"] for plan in plans if plan["id"] not in keep_plan_ids]
        item_count = 0
        if delete_run_ids:
            placeholders = ",".join("?" for _ in delete_run_ids)
            item_count = connection.execute(
                f"SELECT COUNT(*) FROM items WHERE run_id IN ({placeholders})", delete_run_ids
            ).fetchone()[0]
        delete_inspection_ids: list[int] = []
        if "inspections" in tables:
            inspection_rows = list(connection.execute(
                "SELECT id FROM inspections WHERE target_name='prod' AND target_fingerprint=? "
                "ORDER BY inspected_at DESC,id DESC",
                (fingerprint,),
            ))
            delete_inspection_ids = [int(row["id"]) for row in inspection_rows[1:]]
    if not delete_run_ids and not delete_plan_ids and not delete_inspection_ids:
        return None
    return {
        "action": "prune-production-history", "target_fingerprint": fingerprint,
        "keep_latest_run": latest_run["id"] if latest_run else None,
        "delete_run_ids": delete_run_ids, "delete_plan_ids": delete_plan_ids,
        "delete_inspection_ids": delete_inspection_ids,
        "delete_item_count": item_count,
        "preserves": ["mappings", "links", "single latest run and its items/plan", "latest inspection"],
    }


def _legacy_local_action(base_state_path: Path) -> dict[str, Any] | None:
    if not base_state_path.is_file():
        return None
    with _readonly(base_state_path) as connection:
        tables = _tables(connection)
        if "inspections" not in tables:
            return None
        fingerprints = {
            str(row[0]) for row in connection.execute(
                "SELECT DISTINCT target_fingerprint FROM inspections WHERE target_name='local'"
            )
        }
        active_runs: list[str] = []
        if fingerprints and "runs" in tables:
            placeholders = ",".join("?" for _ in fingerprints)
            active_runs = [str(row[0]) for row in connection.execute(
                f"SELECT id FROM runs WHERE target_fingerprint IN ({placeholders}) AND status='running'",
                sorted(fingerprints),
            )]
        active_workflows = [str(row[0]) for row in connection.execute(
            "SELECT id FROM workflow_runs WHERE target_name='local' AND status IN ('queued','running')"
        )] if "workflow_runs" in tables else []
        if active_runs or active_workflows:
            return {
                "action": "blocked-delete-active-legacy-local-state",
                "active_run_ids": active_runs, "active_workflow_run_ids": active_workflows,
            }
        counts: dict[str, int] = {}
        if fingerprints:
            placeholders = ",".join("?" for _ in fingerprints)
            args = sorted(fingerprints)
            for table in ("plans", "runs", "mappings", "links"):
                if table in tables:
                    counts[table] = int(connection.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE target_fingerprint IN ({placeholders})",
                        args,
                    ).fetchone()[0])
            if "items" in tables:
                counts["items"] = int(connection.execute(
                    f"SELECT COUNT(*) FROM items WHERE run_id IN "
                    f"(SELECT id FROM runs WHERE target_fingerprint IN ({placeholders}))",
                    args,
                ).fetchone()[0])
        counts["inspections"] = int(connection.execute(
            "SELECT COUNT(*) FROM inspections WHERE target_name='local'"
        ).fetchone()[0])
        counts["workflow_runs"] = int(connection.execute(
            "SELECT COUNT(*) FROM workflow_runs WHERE target_name='local'"
        ).fetchone()[0]) if "workflow_runs" in tables else 0
    if not fingerprints and not counts["workflow_runs"]:
        return None
    return {
        "action": "delete-legacy-local-state", "state_path": str(base_state_path.resolve()),
        "target_fingerprints": sorted(fingerprints), "row_counts": counts,
        "preserves": ["all production state", "newest cycle database"],
    }


def retention_plan(
    base_state_path: Path, *, scope: str = "all", clock: datetime | None = None,
    production_fingerprints: list[str] | None = None,
) -> dict[str, Any]:
    if scope not in {"all", "local", "prod"}:
        raise ValueError("Retention scope must be all, local, or prod")
    current = clock or datetime.now(timezone.utc)
    actions: list[dict[str, Any]] = []
    cycles = _catalog_cycles(base_state_path) if scope in {"all", "local"} else []
    snapshots = {
        cycle["id"]: _cycle_snapshot(Path(cycle["state_path"])) for cycle in cycles
    }

    if cycles:
        newest = cycles[0]
        for cycle in cycles[1:]:
            if snapshots[cycle["id"]]["active_run_count"]:
                actions.append({
                    "action": "blocked-delete-active-cycle", "cycle_id": cycle["id"],
                    "active_run_count": snapshots[cycle["id"]]["active_run_count"],
                })
                continue
            cycle_dir = _validated_cycle_dir(base_state_path, cycle)
            actions.append({
                "action": "delete-obsolete-cycle", "cycle_id": cycle["id"],
                "replaced_by": newest["id"], "bytes": _tree_size(cycle_dir),
            })

    retention_root = base_state_path.resolve().parent / "retention"
    if retention_root.is_dir() and _tree_size(retention_root):
        actions.append({
            "action": "delete-local-retention-archive",
            "path": str(retention_root.resolve()), "bytes": _tree_size(retention_root),
        })

    if scope in {"all", "local"}:
        action = _legacy_local_action(base_state_path)
        if action:
            actions.append(action)

    if scope in {"all", "prod"}:
        fingerprints = set(production_fingerprints or [])
        if base_state_path.is_file():
            with _readonly(base_state_path) as connection:
                if "inspections" in _tables(connection):
                    fingerprints.update(
                        row[0] for row in connection.execute(
                            "SELECT DISTINCT target_fingerprint FROM inspections WHERE target_name='prod'"
                        )
                    )
        for fingerprint in sorted(fingerprints):
            action = _historical_state_action(
                base_state_path, target_fingerprints={fingerprint},
            )
            if action:
                action["scope"] = "production-history-compaction"
                actions.append(action)

    destructive = [action for action in actions if not action["action"].startswith("blocked-")]
    return {
        "scope": scope, "generated_at": current.isoformat(),
        "apply_confirmation": APPLY_CONFIRMATION,
        "actions": actions,
        "action_count": len(destructive),
        "blocked_action_count": len(actions) - len(destructive),
        "estimated_immediate_reclaim_bytes": sum(
            action.get("bytes", 0)
            for action in destructive
            if action["action"].startswith("delete-")
        ),
        "policy": {
            "local_cycles": "retain only the newest cycle and its complete state",
            "obsolete_local_cycles": "delete all databases, logs, summaries, and catalog entries",
            "legacy_local_state": "delete after confirming no local run is active",
            "production": "retain mappings/links and only the single latest run with its plan/items",
        },
    }


def _json_value(value: str | None) -> Any:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def _archive_cycle(base_state_path: Path, cycle: dict[str, Any]) -> Path:
    state_path = Path(cycle["state_path"])
    cycle_dir = _validated_cycle_dir(base_state_path, cycle)
    archive_root = base_state_path.resolve().parent / "retention"
    summary_path = archive_root / "summaries" / f"{cycle['id']}.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    document: dict[str, Any] = {
        "version": 1,
        "archived_at": now(),
        "cycle": {
            key: cycle.get(key) for key in (
                "id", "created_at", "closed_at", "status", "target_name",
                "target_fingerprint", "baseline_ref", "note",
            )
        },
        "workflow_runs": [], "block_runs": [], "failure_fingerprints": [],
    }
    if state_path.is_file():
        with _readonly(state_path) as connection:
            tables = _tables(connection)
            if "workflow_runs" in tables:
                document["workflow_runs"] = [
                    {
                        **{key: row[key] for key in (
                            "id", "workflow_id", "status", "created_at", "started_at",
                            "finished_at", "error_code",
                        )},
                        "summary": _json_value(row["summary"]),
                    }
                    for row in connection.execute(
                        "SELECT id,workflow_id,status,created_at,started_at,finished_at,"
                        "error_code,summary FROM workflow_runs ORDER BY created_at"
                    )
                ]
            if "runs" in tables:
                document["block_runs"] = [
                    {
                        **{key: row[key] for key in (
                            "id", "plan_id", "block", "status", "started_at", "finished_at",
                        )},
                        "summary": _json_value(row["summary"]),
                    }
                    for row in connection.execute(
                        "SELECT id,plan_id,block,status,started_at,finished_at,summary "
                        "FROM runs ORDER BY started_at"
                    )
                ]
            if "workflow_failures" in tables:
                document["failure_fingerprints"] = [dict(row) for row in connection.execute(
                    "SELECT fingerprint,service_id,phase,item_status,error_code,COUNT(*) AS occurrences,"
                    "MIN(created_at) AS first_seen_at,MAX(created_at) AS last_seen_at "
                    "FROM workflow_failures GROUP BY fingerprint,service_id,phase,item_status,error_code "
                    "ORDER BY last_seen_at"
                )]

    failed_log_root = archive_root / "failed-logs" / str(cycle["id"])
    snapshot = _cycle_snapshot(state_path)
    current = datetime.now(timezone.utc)
    for run in snapshot["workflow_runs"]:
        if run["status"] == "completed" or run["status"] in ACTIVE_STATUSES:
            continue
        age = _age_days(run.get("finished_at") or run.get("created_at"), current)
        if age is None or age >= FAILED_LOG_DAYS or not run.get("log_path"):
            continue
        source = Path(run["log_path"])
        if source.suffix != ".gz" and source.is_file():
            source = _gzip_log(source)
        if source.is_file() and source.resolve().is_relative_to(cycle_dir / "workflow-runs"):
            failed_log_root.mkdir(parents=True, exist_ok=True)
            destination = failed_log_root / f"{run['id']}.log.gz"
            shutil.move(str(source), destination)
            instant = _parse_instant(run.get("finished_at") or run.get("created_at"))
            if instant:
                os.utime(destination, (instant.timestamp(), instant.timestamp()))

    temporary = summary_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(summary_path)
    shutil.rmtree(cycle_dir)
    return summary_path


def _gzip_log(path: Path) -> Path:
    destination = Path(f"{path}.gz")
    temporary = Path(f"{destination}.tmp")
    if destination.exists():
        raise ValueError(f"Compressed log already exists: {destination}")
    with path.open("rb") as source, gzip.open(temporary, "wb", compresslevel=6) as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)
    temporary.replace(destination)
    os.utime(destination, (path.stat().st_atime, path.stat().st_mtime))
    path.unlink()
    return destination


def _prune_production(base_state_path: Path, action: dict[str, Any]) -> None:
    connection = sqlite3.connect(base_state_path, timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("BEGIN IMMEDIATE")
        fingerprint = action["target_fingerprint"]
        active = connection.execute(
            "SELECT COUNT(*) FROM runs WHERE target_fingerprint=? AND status='running'",
            (fingerprint,),
        ).fetchone()[0]
        if active:
            raise ValueError("Production retention refused because a sync run is active")
        connection.executemany("DELETE FROM items WHERE run_id=?", [(value,) for value in action["delete_run_ids"]])
        connection.executemany("DELETE FROM runs WHERE id=?", [(value,) for value in action["delete_run_ids"]])
        connection.executemany("DELETE FROM plans WHERE id=?", [(value,) for value in action["delete_plan_ids"]])
        connection.executemany(
            "DELETE FROM inspections WHERE id=?", [(value,) for value in action["delete_inspection_ids"]]
        )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _delete_legacy_local_state(base_state_path: Path, action: dict[str, Any]) -> None:
    connection = sqlite3.connect(base_state_path, timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("BEGIN IMMEDIATE")
        fingerprints = [str(value) for value in action["target_fingerprints"]]
        if fingerprints:
            placeholders = ",".join("?" for _ in fingerprints)
            active = connection.execute(
                f"SELECT COUNT(*) FROM runs WHERE target_fingerprint IN ({placeholders}) "
                "AND status='running'", fingerprints,
            ).fetchone()[0]
            if active:
                raise ValueError("Legacy-local cleanup refused because a block run is still active")
        active_workflows = connection.execute(
            "SELECT COUNT(*) FROM workflow_runs WHERE target_name='local' "
            "AND status IN ('queued','running')"
        ).fetchone()[0]
        if active_workflows:
            raise ValueError("Legacy-local cleanup refused because a workflow is still active")

        connection.execute(
            "DELETE FROM workflow_event_links WHERE event_id IN "
            "(SELECT id FROM workflow_events WHERE workflow_run_id IN "
            "(SELECT id FROM workflow_runs WHERE target_name='local')) OR related_event_id IN "
            "(SELECT id FROM workflow_events WHERE workflow_run_id IN "
            "(SELECT id FROM workflow_runs WHERE target_name='local'))"
        )
        connection.execute(
            "DELETE FROM workflow_failure_links WHERE failure_id IN "
            "(SELECT id FROM workflow_failures WHERE workflow_run_id IN "
            "(SELECT id FROM workflow_runs WHERE target_name='local')) OR related_failure_id IN "
            "(SELECT id FROM workflow_failures WHERE workflow_run_id IN "
            "(SELECT id FROM workflow_runs WHERE target_name='local'))"
        )
        for table in ("workflow_events", "workflow_failures", "workflow_steps"):
            connection.execute(
                f"DELETE FROM {table} WHERE workflow_run_id IN "
                "(SELECT id FROM workflow_runs WHERE target_name='local')"
            )
        connection.execute("DELETE FROM workflow_runs WHERE target_name='local'")
        connection.execute("DELETE FROM workflow_plans WHERE target_name='local'")

        if fingerprints:
            placeholders = ",".join("?" for _ in fingerprints)
            connection.execute(
                f"DELETE FROM items WHERE run_id IN "
                f"(SELECT id FROM runs WHERE target_fingerprint IN ({placeholders}))",
                fingerprints,
            )
            for table in ("runs", "plans", "mappings", "links"):
                connection.execute(
                    f"DELETE FROM {table} WHERE target_fingerprint IN ({placeholders})",
                    fingerprints,
                )
        connection.execute("DELETE FROM inspections WHERE target_name='local'")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _compact_successful_history(state_path: Path, action: dict[str, Any]) -> None:
    connection = sqlite3.connect(state_path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("BEGIN IMMEDIATE")
        plan_ids = [str(value) for value in action["compact_plan_ids"]]
        for plan_id in plan_ids:
            statuses = {
                str(row[0]) for row in connection.execute(
                    "SELECT DISTINCT status FROM runs WHERE plan_id=?", (plan_id,)
                )
            }
            if statuses != {"completed"}:
                raise ValueError(
                    f"Historical compaction refused because plan {plan_id} is not wholly successful"
                )
            row = connection.execute(
                "SELECT document,LENGTH(document) AS bytes FROM plans WHERE id=?", (plan_id,)
            ).fetchone()
            if not row:
                continue
            original = _json_value(row["document"])
            if isinstance(original, dict) and "retention_compacted" in original:
                continue
            collection_counts = (
                {key: len(value) for key, value in original.items() if isinstance(value, (list, dict))}
                if isinstance(original, dict) else {}
            )
            compact: dict[str, Any] = {
                "retention_compacted": {
                    "version": 1, "compacted_at": now(),
                    "original_bytes": int(row["bytes"] or 0),
                    "collection_counts": collection_counts,
                }
            }
            if isinstance(original, dict):
                for key in ("accounting_cutoff", "counts", "scope"):
                    if key in original:
                        compact[key] = original[key]
            connection.execute(
                "UPDATE plans SET document=? WHERE id=?",
                (json.dumps(compact, sort_keys=True, separators=(",", ":")), plan_id),
            )
        run_ids = [str(value) for value in action["superseded_run_ids"]]
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            statuses = ",".join("?" for _ in TERMINAL_SUCCESS_ITEM_STATUSES)
            connection.execute(
                f"DELETE FROM items WHERE run_id IN ({placeholders}) AND status IN ({statuses})",
                [*run_ids, *sorted(TERMINAL_SUCCESS_ITEM_STATUSES)],
            )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def apply_retention(
    base_state_path: Path, *, confirmation: str, scope: str = "all",
    production_fingerprints: list[str] | None = None,
) -> dict[str, Any]:
    if confirmation != APPLY_CONFIRMATION:
        raise ValueError(f"Retention apply requires --confirm {APPLY_CONFIRMATION}")
    plan = retention_plan(
        base_state_path, scope=scope, production_fingerprints=production_fingerprints,
    )
    if plan["blocked_action_count"]:
        raise ValueError("Retention apply refused because the current plan contains blocked actions")
    before = _tree_size(base_state_path.resolve().parent)
    catalog = CycleCatalog(base_state_path) if scope in {"all", "local"} else None
    applied: list[dict[str, Any]] = []
    try:
        for action in plan["actions"]:
            name = action["action"]
            if name == "delete-obsolete-cycle":
                assert catalog is not None
                cycle = catalog.get(action["cycle_id"])
                cycle_dir = _validated_cycle_dir(base_state_path, cycle)
                snapshot = _cycle_snapshot(Path(cycle["state_path"]))
                if snapshot["active_run_count"]:
                    raise ValueError(f"Obsolete cycle {cycle['id']!r} has an active workflow")
                if cycle_dir.is_dir():
                    shutil.rmtree(cycle_dir)
                catalog.conn.execute("DELETE FROM sync_cycles WHERE id=?", (cycle["id"],))
                catalog.conn.commit()
            elif name == "delete-local-retention-archive":
                path = Path(action["path"]).resolve()
                expected = (base_state_path.resolve().parent / "retention").resolve()
                if path != expected:
                    raise ValueError("Local retention archive has an unsafe path")
                if path.is_dir():
                    shutil.rmtree(path)
            elif name == "compress-failed-log":
                compressed = _gzip_log(Path(action["path"]))
                cycle = catalog.get(action["cycle_id"]) if catalog else None
                if cycle and Path(cycle["state_path"]).is_file():
                    state = State(Path(cycle["state_path"]))
                    try:
                        state.conn.execute(
                            "UPDATE workflow_runs SET log_path=? WHERE id=?",
                            (str(compressed), action["workflow_run_id"]),
                        )
                        state.conn.commit()
                    finally:
                        state.conn.close()
            elif name in {"delete-success-log", "delete-failed-log"}:
                path = Path(action["path"])
                cycle = catalog.get(action["cycle_id"]) if catalog else None
                if cycle and path.resolve().is_relative_to(Path(cycle["state_path"]).resolve().parent / "workflow-runs"):
                    path.unlink(missing_ok=True)
            elif name == "archive-and-purge-cycle":
                assert catalog is not None
                cycle = catalog.get(action["cycle_id"])
                summary_path = _archive_cycle(base_state_path, cycle)
                catalog.conn.execute(
                    "UPDATE sync_cycles SET purged_at=?,summary_path=? WHERE id=?",
                    (now(), str(summary_path), action["cycle_id"]),
                )
                catalog.conn.commit()
            elif name == "delete-expired-summary":
                path = Path(action["path"])
                root = (base_state_path.resolve().parent / "retention" / "summaries").resolve()
                if path.resolve().is_relative_to(root):
                    path.unlink(missing_ok=True)
            elif name == "delete-expired-archived-failed-log":
                path = Path(action["path"])
                root = (base_state_path.resolve().parent / "retention" / "failed-logs").resolve()
                if path.resolve().is_relative_to(root):
                    path.unlink(missing_ok=True)
            elif name == "prune-production-history":
                _prune_production(base_state_path, action)
            elif name == "delete-legacy-local-state":
                path = Path(action["state_path"]).resolve()
                if path != base_state_path.resolve():
                    raise ValueError("Legacy-local cleanup has an unsafe state path")
                _delete_legacy_local_state(base_state_path, action)
            elif name == "compact-historical-state":
                path = Path(action["state_path"]).resolve()
                if action.get("cycle_id"):
                    assert catalog is not None
                    cycle = catalog.get(action["cycle_id"])
                    if cycle["status"] != "closed" or path != Path(cycle["state_path"]).resolve():
                        raise ValueError("Historical compaction is limited to the selected closed cycle")
                elif path != base_state_path.resolve() or not action.get("target_fingerprints"):
                    raise ValueError("Legacy historical compaction has an unsafe state path or empty scope")
                _compact_successful_history(path, action)
            applied.append(action)
    finally:
        if catalog is not None:
            catalog.conn.close()
    after = _tree_size(base_state_path.resolve().parent)
    return {
        "ok": True, "scope": scope, "applied_at": now(), "applied_actions": applied,
        "before_bytes": before, "after_bytes": after, "reclaimed_bytes": max(0, before - after),
    }
