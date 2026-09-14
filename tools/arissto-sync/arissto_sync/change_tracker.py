from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .state import now


CHANGE_TRACKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS loan_sync_changes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_reference TEXT NOT NULL UNIQUE,
 commit_sha TEXT,
 pr_reference TEXT,
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
 UNIQUE (change_id, decision, rationale),
 FOREIGN KEY (change_id) REFERENCES loan_sync_changes(id)
);
CREATE INDEX IF NOT EXISTS loan_sync_change_loans_source_idx
 ON loan_sync_change_loans(source_loan_id);
CREATE INDEX IF NOT EXISTS loan_sync_change_decisions_change_idx
 ON loan_sync_change_decisions(change_id, created_at);
"""

COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def change_tracker_path(base_state_path: Path) -> Path:
    """Return the durable tracker beside, but outside, cycle state directories."""
    return base_state_path.resolve().parent / "change-tracker.sqlite3"


class ChangeTracker:
    def __init__(self, base_state_path: Path):
        self.path = change_tracker_path(base_state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(CHANGE_TRACKER_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def record_change(
        self,
        change_reference: str,
        description: str,
        *,
        commit_sha: str | None = None,
        pr_reference: str | None = None,
        status: str = "open",
        created_at: str | None = None,
    ) -> int:
        reference = change_reference.strip()
        if not reference:
            raise ValueError("change_reference is required")
        cursor = self.conn.execute(
            "INSERT INTO loan_sync_changes(change_reference,commit_sha,pr_reference,description,"
            "status,created_at) VALUES(?,?,?,?,?,?)",
            (reference, commit_sha, pr_reference, description.strip(), status, created_at or now()),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def add_loan(
        self,
        change_id: int,
        source_loan_id: str,
        result: str,
        *,
        target_loan_id: str | None = None,
        notes: str | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO loan_sync_change_loans(change_id,source_loan_id,target_loan_id,result,notes) "
            "VALUES(?,?,?,?,?)",
            (change_id, source_loan_id, target_loan_id, result, notes),
        )
        self.conn.commit()

    def add_decision(self, change_id: int, decision: str, rationale: str) -> None:
        self.conn.execute(
            "INSERT INTO loan_sync_change_decisions(change_id,decision,rationale,created_at) "
            "VALUES(?,?,?,?)",
            (change_id, decision, rationale, now()),
        )
        self.conn.commit()


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def migrate_legacy_change_tracking(base_state_path: Path, state_paths: Iterable[Path]) -> dict[str, Any]:
    """Copy legacy cycle-local tracker rows into durable storage, idempotently."""
    tracker = ChangeTracker(base_state_path)
    migrated_changes = 0
    migrated_loans = 0
    migrated_decisions = 0
    try:
        candidates = [base_state_path, *state_paths]
        seen: set[Path] = set()
        for candidate in candidates:
            path = candidate.resolve()
            if path in seen or not path.is_file() or path == tracker.path:
                continue
            seen.add(path)
            source = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
            source.row_factory = sqlite3.Row
            try:
                tables = _tables(source)
                if "loan_sync_changes" not in tables:
                    continue
                changes = source.execute("SELECT * FROM loan_sync_changes ORDER BY id").fetchall()
                for change in changes:
                    legacy_reference = str(change["pr_reference"])
                    commit_sha = legacy_reference if COMMIT_SHA.fullmatch(legacy_reference) else None
                    pr_reference = None if commit_sha else legacy_reference
                    cursor = tracker.conn.execute(
                        "INSERT OR IGNORE INTO loan_sync_changes(change_reference,commit_sha,pr_reference,"
                        "description,status,created_at,closed_at) VALUES(?,?,?,?,?,?,?)",
                        (legacy_reference, commit_sha, pr_reference, change["description"], change["status"],
                         change["created_at"], change["closed_at"]),
                    )
                    migrated_changes += cursor.rowcount
                    durable_id = tracker.conn.execute(
                        "SELECT id FROM loan_sync_changes WHERE change_reference=?", (legacy_reference,),
                    ).fetchone()[0]
                    if "loan_sync_change_loans" in tables:
                        for loan in source.execute(
                            "SELECT * FROM loan_sync_change_loans WHERE change_id=?", (change["id"],),
                        ):
                            cursor = tracker.conn.execute(
                                "INSERT OR IGNORE INTO loan_sync_change_loans(change_id,source_loan_id,"
                                "target_loan_id,result,notes) VALUES(?,?,?,?,?)",
                                (durable_id, loan["source_loan_id"], loan["target_loan_id"],
                                 loan["result"], loan["notes"]),
                            )
                            migrated_loans += cursor.rowcount
                    if "loan_sync_change_decisions" in tables:
                        for decision in source.execute(
                            "SELECT * FROM loan_sync_change_decisions WHERE change_id=?", (change["id"],),
                        ):
                            cursor = tracker.conn.execute(
                                "INSERT OR IGNORE INTO loan_sync_change_decisions(change_id,decision,"
                                "rationale,created_at) VALUES(?,?,?,?)",
                                (durable_id, decision["decision"], decision["rationale"], decision["created_at"]),
                            )
                            migrated_decisions += cursor.rowcount
            finally:
                source.close()
        tracker.conn.commit()
        return {
            "path": str(tracker.path),
            "changes": migrated_changes,
            "loans": migrated_loans,
            "decisions": migrated_decisions,
        }
    except Exception:
        tracker.conn.rollback()
        raise
    finally:
        tracker.close()
