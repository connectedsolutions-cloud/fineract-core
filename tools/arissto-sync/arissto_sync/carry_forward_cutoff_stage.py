"""Prove offline cutoff advancement in an unregistered restored seed database.

This is a rehearsal for the guarded tenant replacement. It cannot connect to
the registered sandbox database and never invokes Fineract's active-cutoff API.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from typing import Any

import psycopg
from psycopg import sql

from .carry_forward_classify import write_private_classification
from .carry_forward_capture import verify_capture
from .carry_forward_seed_refs import isolated_url
from .carry_forward_target import CLOSED_STATUSES, EMPTY_DOMAIN_TABLES, cutoff_hash
from .config import load_settings


VERIFY_DB = re.compile(r"fineract_carry_seed_verify_[0-9]{8}\Z")


def rehearse_cutoff(stage_archive: Path, stage_report: Path,
                   classification_path: Path, verify_db: str,
                   output: Path) -> dict[str, Any]:
    settings = load_settings("local")
    if not settings.target.pg_url or settings.target.tenant != "sandbox":
        raise ValueError("Cutoff rehearsal requires the local sandbox profile")
    root = (settings.state_path.parent / "carry-forward").resolve()
    for path in (stage_archive, stage_report, classification_path, output):
        if not path.resolve().is_relative_to(root):
            raise ValueError("Cutoff rehearsal evidence must stay in private state")
    if not VERIFY_DB.fullmatch(verify_db):
        raise ValueError("Cutoff rehearsal requires an unregistered verify database")
    archive = json.loads(stage_archive.read_text(encoding="utf-8"))
    staged = json.loads(stage_report.read_text(encoding="utf-8"))
    classification = json.loads(classification_path.read_text(encoding="utf-8"))
    if (archive.get("report_kind") != "isolated-carry-forward-seed-archive-v1"
            or archive["restore_test_database"] != verify_db
            or not archive["restored_table_counts_and_hashes_match"]
            or archive["stage_database"] != staged["stage_database"]
            or archive["classification_hash"] != classification["classification_hash"]):
        raise ValueError("Restored seed and classification evidence differ")
    verify_capture(settings, staged["capture_id"], staged["capture_manifest_sha256"])
    old = classification["old_cutoff_binding"]
    old_date = date.fromisoformat(old["date"])
    new_date = date.fromisoformat(classification["fineract_starts"])
    if (new_date <= old_date
            or date.fromisoformat(classification["arissto_through"]) >= new_date):
        raise ValueError("New Fineract start must follow the old boundary and source day")
    parsed = urlparse(isolated_url(settings.target.pg_url,
                                   archive["stage_database"], "stage"))
    verify_url = urlunparse(parsed._replace(path="/" + verify_db))
    input_url = isolated_url(settings.target.pg_url, staged["input_database"], "input")
    with psycopg.connect(input_url) as captured_input:
        captured_input.execute("SET TRANSACTION READ ONLY")
        old_row = captured_input.execute("""
            SELECT cutoff_date,timezone_id,lifecycle_state,configuration_revision,
                   configuration_hash
            FROM acc_accounting_cutoff_configuration WHERE id=1
        """).fetchone()
        if old_row != (old_date, "America/El_Salvador", "ACTIVE",
                       old["configuration_revision"], old["configuration_hash"]):
            raise ValueError("Captured input old cutoff binding changed")
    with psycopg.connect(verify_url) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        if conn.execute("SELECT COUNT(*) FROM acc_accounting_cutoff_configuration").fetchone()[0]:
            raise ValueError("Clean staged seed unexpectedly has a cutoff row")
        if old["configuration_hash"] != cutoff_hash(
            old_date, "ACTIVE", int(old["configuration_revision"]),
        ):
            raise ValueError("Captured input cutoff hash is invalid")
        if conn.execute("SELECT COUNT(*) FROM m_appuser WHERE id=1").fetchone()[0] != 1:
            raise ValueError("Seed has no local bootstrap user for cutoff activation")
        if int(conn.execute("SELECT COUNT(*) FROM m_loan").fetchone()[0]) != archive["retained_loan_count"]:
            raise ValueError("Restored seed loan count changed")
        nonclosed = int(conn.execute(
            "SELECT COUNT(*) FROM m_loan WHERE loan_status_id <> ALL(%s)",
            (sorted(CLOSED_STATUSES),),
        ).fetchone()[0])
        if nonclosed:
            raise ValueError("Restored seed contains nonclosed loans")
        late = int(conn.execute(
            "SELECT COUNT(*) FROM m_loan_transaction WHERE transaction_date >= %s",
            (old_date,),
        ).fetchone()[0])
        if late:
            raise ValueError("Restored seed has post-old-cutoff loan transactions")
        for table in sorted(EMPTY_DOMAIN_TABLES):
            count = int(conn.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table),
            )).fetchone()[0])
            if count:
                raise ValueError(f"Restored seed contains excluded rows: {table}")
        new_revision = 2
        new_hash = cutoff_hash(new_date, "ACTIVE", new_revision)
        conn.execute("""
            INSERT INTO acc_accounting_cutoff_configuration
              (id,cutoff_date,timezone_id,lifecycle_state,configuration_revision,
               configuration_hash,activated_at,activated_by,version)
            VALUES (1,%s,'America/El_Salvador','ACTIVE',%s,%s,CURRENT_TIMESTAMP,1,0)
        """, (new_date, new_revision, new_hash))
        current = conn.execute("""
            SELECT cutoff_date,lifecycle_state,configuration_revision,configuration_hash
            FROM acc_accounting_cutoff_configuration WHERE id=1
        """).fetchone()
        if current != (new_date, "ACTIVE", new_revision, new_hash):
            raise ValueError("Offline cutoff update did not round-trip")
        conn.commit()
    result = {
        "report_kind": "isolated-carry-forward-cutoff-rehearsal-v1",
        "arissto_through": classification["arissto_through"],
        "fineract_starts": new_date.isoformat(),
        "restore_test_database": verify_db,
        "stage_dump_sha256": archive["dump_sha256"],
        "old_configuration_revision": int(old["configuration_revision"]),
        "new_configuration_revision": new_revision,
        "new_configuration_hash": new_hash,
        "restored_seed_cutoff_advanced": True,
        "registered_sandbox_changed": False,
        "ready_for_tenant_replacement": False,
    }
    write_private_classification(result, output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-report", type=Path, required=True)
    parser.add_argument("--stage-report", type=Path, required=True)
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument("--verify-db", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = rehearse_cutoff(args.archive_report, args.stage_report,
                            args.classification, args.verify_db, args.output)
    print(json.dumps({key: result[key] for key in (
        "arissto_through", "fineract_starts", "old_configuration_revision",
        "new_configuration_revision", "restored_seed_cutoff_advanced",
        "ready_for_tenant_replacement",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
