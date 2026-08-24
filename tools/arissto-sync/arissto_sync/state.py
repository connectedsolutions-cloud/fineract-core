from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
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
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def save_plan(self, target: str, block: str, source_fingerprint: str,
                  contract_hash: str, document: dict[str, Any]) -> str:
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

    def finish_run(self, run_id: str, status: str, summary: dict[str, Any]) -> None:
        self.conn.execute("UPDATE runs SET finished_at=?,status=?,summary=? WHERE id=?",
                          (now(), status, json.dumps(summary, sort_keys=True), run_id))
        self.conn.commit()

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
