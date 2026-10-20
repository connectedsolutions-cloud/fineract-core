"""Dump and restore-test an isolated carry-forward seed stage.

The restore target is a separate unregistered local database. The populated
sandbox, clean baseline, and input capture are never changed here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse
from typing import Any

from psycopg import sql

from .carry_forward_capture import sha256_file
from .carry_forward_classify import write_private_classification
from .carry_forward_seed_refs import isolated_url
from .carry_forward_seed_stage import _row_digest
from .config import load_settings
from .connections import postgres_connection


RESTORE_DB = re.compile(r"fineract_carry_seed_verify_[0-9]{8}\Z")


def _run(args: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(args, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    if result.returncode:
        raise RuntimeError(f"Isolated seed archive command failed: {args[0]}")


def archive_seed(
    stage_report: Path, restored_db: str, dump_path: Path, output: Path,
) -> dict[str, Any]:
    settings = load_settings("local")
    if not settings.target.pg_url or settings.target.tenant != "sandbox":
        raise ValueError("Only local sandbox seed stages can be archived")
    root = (settings.state_path.parent / "carry-forward").resolve()
    for path in (stage_report, dump_path, output):
        if not path.resolve().is_relative_to(root):
            raise ValueError("Seed archive paths must stay in private carry-forward state")
    report = json.loads(stage_report.read_text(encoding="utf-8"))
    if report.get("report_kind") != "isolated-carry-forward-closed-loan-stage-v1":
        raise ValueError("Unexpected staged seed report")
    stage_db = report["stage_database"]
    stage_url = isolated_url(settings.target.pg_url, stage_db, "stage")
    if not RESTORE_DB.fullmatch(restored_db) or restored_db == stage_db:
        raise ValueError("Restore verification needs an isolated verify database")
    # Preserve the same local host, port, and credentials; only the database varies.
    parsed = urlparse(stage_url)
    verify_url = parsed._replace(path="/" + restored_db).geturl()
    env = os.environ.copy()
    env["PGPASSWORD"] = unquote(parsed.password or "")
    connection_args = [
        "--host", str(parsed.hostname), "--port", str(parsed.port or 5432),
        "--username", unquote(parsed.username or ""),
    ]
    if dump_path.exists() or output.exists():
        raise ValueError("Seed archive output already exists")
    dump_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    dump_path.parent.chmod(0o700)
    with postgres_connection(stage_url) as stage:
        for table, expected in report["stage_table_counts"].items():
            actual = int(stage.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table),
            )).fetchone()[0])
            if actual != expected:
                raise ValueError(f"Staged table count changed: {table}")
            if _row_digest(stage, table, sql.SQL("TRUE"), ()) != report["stage_table_hashes"][table]:
                raise ValueError(f"Staged table content changed: {table}")
    _run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges",
          *connection_args, "--dbname", stage_db, "--file", str(dump_path)], env)
    dump_path.chmod(0o600)
    _run(["pg_restore", "--list", str(dump_path)], env)
    _run(["createdb", *connection_args, restored_db], env)
    _run(["pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
          *connection_args, "--dbname", restored_db, str(dump_path)], env)
    with postgres_connection(verify_url) as restored:
        for table, expected in report["stage_table_counts"].items():
            actual = int(restored.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table),
            )).fetchone()[0])
            if actual != expected:
                raise ValueError(f"Restored table count differs: {table}")
            if _row_digest(restored, table, sql.SQL("TRUE"), ()) != report["stage_table_hashes"][table]:
                raise ValueError(f"Restored table content differs: {table}")
        for table in ("acc_gl_journal_entry", "m_savings_account", "m_share_account", "m_invoice"):
            if restored.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table),
            )).fetchone()[0]:
                raise ValueError(f"Restored seed contains excluded financial rows: {table}")
        changelog = int(restored.execute("SELECT COUNT(*) FROM databasechangelog").fetchone()[0])
    result = {
        "report_kind": "isolated-carry-forward-seed-archive-v1",
        "arissto_through": report["arissto_through"],
        "fineract_starts": report["fineract_starts"],
        "classification_hash": report["classification_hash"],
        "capture_manifest_sha256": report["capture_manifest_sha256"],
        "baseline_sha256": report["baseline_sha256"],
        "stage_database": stage_db, "restore_test_database": restored_db,
        "dump_path": str(dump_path.resolve()), "dump_sha256": sha256_file(dump_path),
        "liquibase_entries": changelog,
        "retained_loan_count": report["retained_loan_count"],
        "restored_table_counts_and_hashes_match": True,
        "ready_for_tenant_replacement": False,
    }
    write_private_classification(result, output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-report", type=Path, required=True)
    parser.add_argument("--restore-db", required=True)
    parser.add_argument("--dump", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = archive_seed(args.stage_report, args.restore_db, args.dump, args.output)
    print(json.dumps({key: result[key] for key in (
        "stage_database", "restore_test_database", "dump_sha256",
        "liquibase_entries", "retained_loan_count", "restored_table_counts_and_hashes_match",
        "ready_for_tenant_replacement",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
