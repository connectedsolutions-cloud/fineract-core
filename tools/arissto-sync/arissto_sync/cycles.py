from __future__ import annotations

import re
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import Settings
from .state import State, now


CYCLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
CYCLE_CATALOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_cycles (
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL, closed_at TEXT,
 status TEXT NOT NULL, target_name TEXT NOT NULL, target_fingerprint TEXT NOT NULL,
 baseline_ref TEXT NOT NULL, state_path TEXT NOT NULL UNIQUE, note TEXT,
 purged_at TEXT, summary_path TEXT
);
CREATE INDEX IF NOT EXISTS sync_cycles_created_idx ON sync_cycles(created_at);
"""


def cycle_catalog_path(base_state_path: Path) -> Path:
    return base_state_path.parent / "cycles.sqlite3"


def cycle_state_path(base_state_path: Path, cycle_id: str) -> Path:
    if not CYCLE_ID.fullmatch(cycle_id):
        raise ValueError(f"Invalid sync cycle ID: {cycle_id!r}")
    return base_state_path.parent / "cycles" / cycle_id / "state.sqlite3"


class CycleCatalog:
    def __init__(self, base_state_path: Path):
        self.base_state_path = base_state_path
        path = cycle_catalog_path(base_state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(CYCLE_CATALOG_SCHEMA)
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(sync_cycles)")}
        for column in ("purged_at", "summary_path"):
            if column not in columns:
                self.conn.execute(f"ALTER TABLE sync_cycles ADD COLUMN {column} TEXT")
        self.conn.commit()

    def create(
        self, cycle_id: str, target_name: str, target_fingerprint: str,
        baseline_ref: str, note: str | None = None,
    ) -> dict[str, Any]:
        if not CYCLE_ID.fullmatch(cycle_id):
            raise ValueError(f"Invalid sync cycle ID: {cycle_id!r}")
        baseline_ref = baseline_ref.strip()
        if not baseline_ref:
            raise ValueError("--baseline-ref must identify the restored or newly captured tenant baseline")
        if self.conn.execute("SELECT 1 FROM sync_cycles WHERE id=?", (cycle_id,)).fetchone():
            raise ValueError(f"Sync cycle already exists: {cycle_id}")
        state_path = cycle_state_path(self.base_state_path, cycle_id)
        if state_path.exists():
            raise ValueError(f"Cycle state path already exists but is not cataloged: {state_path}")
        created_at = now()
        superseded = self.conn.execute(
            "SELECT id,state_path FROM sync_cycles "
            "WHERE target_name=? AND status='open' ORDER BY created_at",
            (target_name,),
        ).fetchall()
        for previous in superseded:
            previous_path = Path(previous["state_path"])
            if not previous_path.is_file():
                raise ValueError(
                    f"Cannot replace sync cycle {previous['id']!r}; its state database is missing"
                )
            previous_state = State(previous_path)
            try:
                active = previous_state.conn.execute(
                    "SELECT COUNT(*) FROM workflow_runs WHERE status IN ('queued','running')"
                ).fetchone()[0]
            finally:
                previous_state.conn.close()
            if active:
                raise ValueError(
                    f"Cannot replace sync cycle {previous['id']!r} while it has an active workflow"
                )
        state = State(state_path)
        try:
            state.initialize_cycle(cycle_id, target_name, target_fingerprint, baseline_ref, created_at)
        finally:
            state.conn.close()
        self.conn.execute(
            "INSERT INTO sync_cycles(id,created_at,closed_at,status,target_name,target_fingerprint,"
            "baseline_ref,state_path,note,purged_at,summary_path) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (cycle_id, created_at, None, "open", target_name, target_fingerprint,
             baseline_ref, str(state_path), note.strip() if note else None, None, None),
        )
        self.conn.execute(
            "UPDATE sync_cycles SET status='closed',closed_at=? "
            "WHERE target_name=? AND status='open' AND id<>?",
            (created_at, target_name, cycle_id),
        )
        self.conn.commit()
        return self.get(cycle_id)

    def get(self, cycle_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM sync_cycles WHERE id=?", (cycle_id,)).fetchone()
        if not row:
            raise ValueError(f"Unknown sync cycle: {cycle_id}")
        return dict(row)

    def list(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM sync_cycles ORDER BY created_at DESC"
        )]

    def active_workflow_runs(self) -> list[dict[str, Any]]:
        active: list[dict[str, Any]] = []
        for cycle in self.list():
            state_path = Path(cycle["state_path"])
            if not state_path.is_file():
                continue
            state = State(state_path)
            try:
                rows = state.conn.execute(
                    "SELECT id,workflow_id,status,created_at FROM workflow_runs "
                    "WHERE status IN ('queued','running') ORDER BY created_at DESC"
                ).fetchall()
            finally:
                state.conn.close()
            active.extend({**dict(row), "cycle_id": cycle["id"]} for row in rows)
        return active

    def require_open(self, cycle_id: str, target_fingerprint: str) -> dict[str, Any]:
        cycle = self.get(cycle_id)
        if cycle["status"] != "open":
            raise ValueError(f"Sync cycle {cycle_id!r} is {cycle['status']}")
        if cycle["target_name"] != "local" or cycle["target_fingerprint"] != target_fingerprint:
            raise ValueError("Sync cycle belongs to a different local target fingerprint")
        return cycle

    def close(self, cycle_id: str) -> dict[str, Any]:
        cycle = self.get(cycle_id)
        if cycle["status"] == "closed":
            return cycle
        state = State(Path(cycle["state_path"]))
        try:
            active = state.conn.execute(
                "SELECT COUNT(*) FROM workflow_runs WHERE status IN ('queued','running')"
            ).fetchone()[0]
        finally:
            state.conn.close()
        if active:
            raise ValueError(f"Sync cycle {cycle_id!r} still has queued or running workflows")
        self.conn.execute(
            "UPDATE sync_cycles SET status='closed',closed_at=? WHERE id=?", (now(), cycle_id)
        )
        self.conn.commit()
        return self.get(cycle_id)


def settings_for_cycle(settings: Settings, cycle: dict[str, Any]) -> Settings:
    state_path = Path(cycle["state_path"])
    return replace(settings, state_path=state_path)


def workflow_history_across_cycles(catalog: CycleCatalog, workflow_id: str) -> dict[str, Any]:
    cycles = []
    occurrences: dict[str, dict[str, Any]] = {}
    latest_run: tuple[str, str] | None = None
    latest_fingerprints: set[str] = set()
    for cycle in catalog.list():
        state_path = Path(cycle["state_path"])
        if not state_path.is_file():
            cycles.append({"cycle": cycle, "state": "missing", "runs": [], "failure_trends": []})
            continue
        state = State(state_path)
        try:
            runs = state.workflow_history(workflow_id)
            trends = state.workflow_failure_trends(workflow_id)
            failures = [dict(row) for row in state.conn.execute(
                "SELECT f.*,r.created_at AS workflow_created_at FROM workflow_failures f "
                "JOIN workflow_runs r ON r.id=f.workflow_run_id WHERE r.workflow_id=?",
                (workflow_id,),
            )]
        finally:
            state.conn.close()
        if runs:
            cycles.append({"cycle": cycle, "state": "available", "runs": runs, "failure_trends": trends})
            cycle_latest = max(runs, key=lambda item: item["created_at"])
            if latest_run is None or cycle_latest["created_at"] > latest_run[1]:
                latest_run = (cycle_latest["id"], cycle_latest["created_at"])
                latest_fingerprints = {
                    failure["fingerprint"] for failure in failures
                    if failure["workflow_run_id"] == cycle_latest["id"]
                }
        for failure in failures:
            entry = occurrences.setdefault(failure["fingerprint"], {
                "fingerprint": failure["fingerprint"],
                "service_id": failure["service_id"],
                "phase": failure["phase"],
                "source_key": failure["source_key"],
                "error_code": failure["error_code"],
                "cycle_ids": set(),
                "workflow_run_ids": set(),
                "first_seen_at": failure["created_at"],
                "last_seen_at": failure["created_at"],
            })
            entry["cycle_ids"].add(cycle["id"])
            entry["workflow_run_ids"].add(failure["workflow_run_id"])
            entry["first_seen_at"] = min(entry["first_seen_at"], failure["created_at"])
            entry["last_seen_at"] = max(entry["last_seen_at"], failure["created_at"])

    aggregate = []
    for entry in occurrences.values():
        present = entry["fingerprint"] in latest_fingerprints
        cycle_ids = sorted(entry.pop("cycle_ids"))
        run_ids = entry.pop("workflow_run_ids")
        entry["cycle_ids"] = cycle_ids
        entry["cycle_count"] = len(cycle_ids)
        entry["run_count"] = len(run_ids)
        entry["latest_run_id"] = latest_run[0] if latest_run else None
        entry["present_in_latest_run"] = present
        entry["trend"] = (
            "recurring" if present and len(run_ids) > 1
            else "new" if present
            else "not-seen-in-latest"
        )
        aggregate.append(entry)
    aggregate.sort(key=lambda item: item["last_seen_at"], reverse=True)
    return {"workflow_id": workflow_id, "cycles": cycles, "failure_trends": aggregate}
