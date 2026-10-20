"""Carry reviewed GL master differences into an isolated seed database.

Only absent GL master rows and disabled-state changes are supported. The full
rowset must match the captured input afterward. Journals are never copied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from typing import Any

import psycopg
from psycopg import sql

from .carry_forward_classify import write_private_classification
from .carry_forward_seed_refs import isolated_url
from .carry_forward_seed_stage import _columns, _copy_table
from .config import load_settings
from .connections import postgres_connection


VERIFY_DB = re.compile(r"fineract_carry_seed_verify_[0-9]{8}\Z")


def _rows(conn: Any) -> dict[int, dict[str, Any]]:
    return {int(identifier): value for identifier, value in conn.execute(
        "SELECT id,to_jsonb(account) FROM acc_gl_account account",
    ).fetchall()}


def _digest(rows: dict[int, dict[str, Any]]) -> str:
    encoded = json.dumps(rows, sort_keys=True, default=str,
                         separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def reconcile_gl_masters(
    source_db: str, destination_db: str, output: Path,
) -> dict[str, Any]:
    settings = load_settings("local")
    if not settings.target.pg_url or settings.target.tenant != "sandbox":
        raise ValueError("GL seed configuration requires local sandbox profile")
    root = (settings.state_path.parent / "carry-forward").resolve()
    if not output.resolve().is_relative_to(root):
        raise ValueError("GL seed report must stay in private carry-forward state")
    source_url = isolated_url(settings.target.pg_url, source_db, "input")
    if VERIFY_DB.fullmatch(destination_db):
        parsed = urlparse(source_url)
        destination_url = urlunparse(parsed._replace(path="/" + destination_db))
    else:
        destination_url = isolated_url(settings.target.pg_url, destination_db, "stage")
    with postgres_connection(source_url) as source, psycopg.connect(destination_url) as stage:
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        stage.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        if stage.execute("SELECT COUNT(*) FROM acc_gl_journal_entry").fetchone()[0]:
            raise ValueError("Isolated destination contains journal postings")
        if _columns(source, "acc_gl_account") != _columns(stage, "acc_gl_account"):
            raise ValueError("GL master schemas differ")
        source_rows = _rows(source)
        stage_rows = _rows(stage)
        extra = set(stage_rows) - set(source_rows)
        if extra:
            raise ValueError("Clean seed has GL master IDs absent from captured input")
        disabled_changes: list[tuple[int, bool]] = []
        for identifier in sorted(set(source_rows) & set(stage_rows)):
            old = source_rows[identifier]
            current = stage_rows[identifier]
            if old == current:
                continue
            if {key for key in old if old[key] != current[key]} != {"disabled"}:
                raise ValueError("GL master differs beyond the reviewed disabled flag")
            disabled_changes.append((identifier, bool(old["disabled"])))
        missing = set(source_rows) - set(stage_rows)
        inserted = 0
        while missing:
            ready = sorted(identifier for identifier in missing
                           if source_rows[identifier]["parent_id"] is None
                           or int(source_rows[identifier]["parent_id"]) in stage_rows)
            if not ready:
                raise ValueError("Missing GL masters have an unresolved parent")
            for identifier in ready:
                _copy_table(source, stage, "acc_gl_account", _columns(source, "acc_gl_account"),
                            sql.SQL("id = %s"), (identifier,))
                stage_rows[identifier] = source_rows[identifier]
                missing.remove(identifier)
                inserted += 1
        for identifier, disabled in disabled_changes:
            stage.execute("UPDATE acc_gl_account SET disabled=%s WHERE id=%s",
                          (disabled, identifier))
        sequence = stage.execute(
            "SELECT pg_get_serial_sequence('public.acc_gl_account','id')"
        ).fetchone()[0]
        if sequence:
            stage.execute("SELECT setval(%s::regclass,%s,true)",
                          (sequence, max(source_rows)))
        if _rows(stage) != source_rows:
            raise ValueError("GL master configuration did not match captured input")
        stage.commit()
    result = {
        "report_kind": "isolated-carry-forward-gl-master-configuration-v1",
        "source_database": source_db,
        "destination_database": destination_db,
        "source_gl_master_count": len(source_rows),
        "inserted_gl_masters": inserted,
        "updated_disabled_flags": len(disabled_changes),
        "gl_master_content_hash": _digest(source_rows),
        "journal_rows_copied": 0,
        "ready_for_tenant_replacement": False,
    }
    write_private_classification(result, output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--destination-db", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = reconcile_gl_masters(args.source_db, args.destination_db, args.output)
    print(json.dumps({key: result[key] for key in (
        "source_gl_master_count", "inserted_gl_masters",
        "updated_disabled_flags", "journal_rows_copied",
        "ready_for_tenant_replacement",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
