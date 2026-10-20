"""Copy a proven closed-loan graph into an isolated local seed stage.

This is an offline preparation tool. It cannot connect to or replace the
registered sandbox tenant and it never writes to the input capture database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from .carry_forward_capture import sha256_file, verify_capture
from .carry_forward_classify import write_private_classification
from .carry_forward_graph import audit_retention_related_rows, direct_loan_edges
from .carry_forward_seed_refs import (
    COPY_TABLES, _dependency_closure, _foreign_keys, _selection,
    audit_seed_references, isolated_url,
)
from .config import load_settings
from .connections import postgres_connection

PROTECTED_CONFIGURATION_TABLES = frozenset({
    "m_office", "m_staff", "m_staff_office", "credesal_staff_profile",
    "m_permission", "m_role", "m_appuser", "m_password_validation_policy",
    "m_appuser_office", "m_appuser_role", "m_role_permission",
    "m_appuser_previous_password", "m_appuser_password_reset_token",
    "twofactor_access_token", "m_appuser_saved_report",
    "acc_gl_account", "acc_gl_financial_activity_account",
})


def _columns(conn: Any, table: str) -> list[str]:
    return [str(row[0]) for row in conn.execute("""
        SELECT attname FROM pg_attribute
        WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped
        ORDER BY attnum
    """, ("public." + table,)).fetchall()]


def _copy_order(source: Any, tables: set[str]) -> list[str]:
    parents: dict[str, set[str]] = {table: set() for table in tables}
    for child, _, parent, _, width in _foreign_keys(source, tables):
        if width != 1:
            raise ValueError(f"Composite foreign key in staged table: {child}")
        if parent in tables and parent != child:
            parents[child].add(parent)
    ordered: list[str] = []
    while parents:
        ready = sorted(table for table, deps in parents.items() if not deps)
        if not ready:
            raise ValueError("Foreign-key cycle in staged table graph")
        for table in ready:
            ordered.append(table)
            del parents[table]
        for deps in parents.values():
            deps.difference_update(ready)
    return ordered


def _predicate(
    table: str, parent_ids: dict[str, set[int]], loan_ids: list[int],
    product_ids: list[int],
    loan_fk_columns: dict[str, set[str]],
) -> tuple[Any, tuple[Any, ...]]:
    if table in COPY_TABLES:
        return _selection(table, loan_ids, product_ids, loan_fk_columns)
    return sql.SQL("id = ANY(%s)"), (sorted(parent_ids[table]),)


def _row_digest(conn: Any, table: str, condition: Any, params: tuple[Any, ...]) -> str:
    query = sql.SQL("SELECT md5(to_jsonb(t)::text) FROM {} t WHERE ({}) ORDER BY 1").format(
        sql.Identifier(table), condition,
    )
    digest = hashlib.sha256()
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        while rows := cursor.fetchmany(1000):
            for (row_hash,) in rows:
                digest.update(row_hash.encode("ascii"))
                digest.update(b"\n")
    return digest.hexdigest()


def _copy_table(
    source: Any, stage: Any, table: str, columns: list[str],
    condition: Any, params: tuple[Any, ...],
) -> None:
    names = sql.SQL(", ").join(map(sql.Identifier, columns))
    export = sql.SQL("COPY (SELECT {} FROM {} WHERE ({})) TO STDOUT (FORMAT BINARY)").format(
        names, sql.Identifier(table), condition,
    )
    ingest = sql.SQL("COPY {} ({}) FROM STDIN (FORMAT BINARY)").format(
        sql.Identifier(table), names,
    )
    with source.cursor().copy(export, params) as outbound:
        with stage.cursor().copy(ingest) as inbound:
            for block in outbound:
                inbound.write(block)


def _advance_sequence(stage: Any, table: str) -> None:
    if "id" not in _columns(stage, table):
        return
    sequence = stage.execute("SELECT pg_get_serial_sequence(%s,'id')", (
        "public." + table,
    )).fetchone()[0]
    if not sequence:
        return
    maximum = stage.execute(sql.SQL("SELECT MAX(id) FROM {}").format(
        sql.Identifier(table),
    )).fetchone()[0]
    if maximum is not None:
        stage.execute("SELECT setval(%s::regclass,%s,true)", (sequence, maximum))


def stage_closed_loan_seed(
    classification_path: Path, source_db: str, stage_db: str,
    capture_id: str, manifest_sha256: str, baseline_dump: Path,
    baseline_sha256: str, access_manifest: Path,
    gl_config_report: Path, output: Path,
) -> dict[str, Any]:
    settings = load_settings("local")
    if not settings.target.pg_url or settings.target.tenant != "sandbox":
        raise ValueError("Only the local sandbox profile can prepare a seed")
    input_url = isolated_url(settings.target.pg_url, source_db, "input")
    stage_url = isolated_url(settings.target.pg_url, stage_db, "stage")
    capture = verify_capture(settings, capture_id, manifest_sha256)
    if sha256_file(baseline_dump) != baseline_sha256:
        raise ValueError("Clean baseline dump checksum mismatch")
    private_root = (settings.state_path.parent / "carry-forward").resolve()
    if any(not path.resolve().is_relative_to(private_root)
           for path in (access_manifest, gl_config_report)):
        raise ValueError("Protected seed evidence must stay in private state")
    access = json.loads(access_manifest.read_text(encoding="utf-8"))
    gl_config = json.loads(gl_config_report.read_text(encoding="utf-8"))
    if (access.get("database") != source_db
            or gl_config.get("report_kind") != "isolated-carry-forward-gl-master-configuration-v1"
            or gl_config.get("source_database") != source_db
            or gl_config.get("destination_database") != stage_db
            or gl_config.get("journal_rows_copied") != 0):
        raise ValueError("Protected access or GL configuration evidence differs")
    classification = json.loads(classification_path.read_text(encoding="utf-8"))
    if (classification["arissto_through"] != capture["arissto_through"]
            or classification["fineract_starts"] != capture["fineract_starts"]):
        raise ValueError("Classification and recovery boundary differ")
    audit = audit_seed_references(classification_path, source_db, stage_db)
    if audit["blockers"]:
        raise ValueError("Seed reference audit has blockers: " + ", ".join(audit["blockers"]))
    if audit["classification_hash"] != classification["classification_hash"]:
        raise ValueError("Classification changed during seed audit")
    loan_ids = sorted(int(row["target_id"]) for row in classification["loans"]
                      if row["disposition"] in {"retain-candidate", "retain-review"})
    with postgres_connection(input_url) as source, psycopg.connect(stage_url) as stage:
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        stage.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        for table in ("m_appuser", "m_staff", "m_appuser_saved_report"):
            expected = int(access["tables"][table]["count"])
            actual = int(stage.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table),
            )).fetchone()[0])
            if actual != expected:
                raise ValueError(f"Protected access table count differs: {table}")
        if int(stage.execute("SELECT COUNT(*) FROM acc_gl_account").fetchone()[0]) != gl_config["source_gl_master_count"]:
            raise ValueError("GL master configuration was not applied to the stage")
        loan_fk_columns: dict[str, set[str]] = {}
        for table, _, column, width in direct_loan_edges(source):
            if table in COPY_TABLES:
                if width != 1:
                    raise ValueError(f"Composite loan foreign key in {table}")
                loan_fk_columns.setdefault(table, set()).add(column)
        product_ids = sorted(int(row[0]) for row in source.execute(
            "SELECT DISTINCT product_id FROM m_loan WHERE id = ANY(%s)", (loan_ids,),
        ).fetchall())
        selected = {table for table, count in audit["selected_rows"].items() if count}
        parents, blockers, _ = _dependency_closure(
            source, stage, selected, loan_ids, product_ids, loan_fk_columns,
        )
        if blockers or {table: len(ids) for table, ids in parents.items()} != audit["planned_parent_rows_by_table"]:
            raise ValueError("Parent dependency closure changed since audit")
        tables = selected | set(parents)
        order = _copy_order(source, tables)
        for table in sorted(selected):
            if int(stage.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table),
            )).fetchone()[0]):
                raise ValueError(f"Stage already contains selected table rows: {table}")
        checksums: dict[str, str] = {}
        counts: dict[str, int] = {}
        for table in order:
            source_columns = _columns(source, table)
            if source_columns != _columns(stage, table):
                raise ValueError(f"Schema differs between input and stage: {table}")
            condition, params = _predicate(
                table, parents, loan_ids, product_ids, loan_fk_columns,
            )
            expected_hash = _row_digest(source, table, condition, params)
            _copy_table(source, stage, table, source_columns, condition, params)
            if table in selected:
                # Selected tables were required to be empty before the copy.
                # Their selector may depend on another table inserted later.
                stage_condition, stage_params = sql.SQL("TRUE"), ()
                expected_count = audit["selected_rows"][table]
            else:
                stage_condition = sql.SQL("id = ANY(%s)")
                stage_params = (sorted(parents[table]),)
                expected_count = len(parents[table])
            actual_count = int(stage.execute(sql.SQL("SELECT COUNT(*) FROM {} WHERE ({})").format(
                sql.Identifier(table), stage_condition,
            ), stage_params).fetchone()[0])
            if actual_count != expected_count or _row_digest(
                stage, table, stage_condition, stage_params,
            ) != expected_hash:
                raise ValueError(f"Staged row count or content mismatch: {table}")
            checksums[table] = expected_hash
            counts[table] = actual_count
            _advance_sequence(stage, table)
        related = audit_retention_related_rows(stage, loan_ids)
        expected_related = audit_retention_related_rows(source, loan_ids)
        checked_keys = (
            "transfer_rows", "topup_rows", "settlement_rows",
            "transfers_with_both_loans_in_set", "topups_with_both_loans_in_set",
            "settlements_with_both_loans_in_set", "valid_consolidation_headers_without_transfer_link",
        )
        if any(related[key] != expected_related[key] for key in checked_keys):
            raise ValueError("Staged refinance row counts differ from input")
        bad_keys = (
            "invalid_topups_without_transfer_link", "topups_with_wrong_transfer_loans",
            "settlements_missing_transfer", "settlements_missing_repayment",
            "settlements_with_wrong_repayment_loan", "settlements_with_wrong_transfer_loans",
            "settlements_with_amount_mismatch", "transfers_with_savings_side",
        )
        if any(related[key] for key in bad_keys):
            raise ValueError("Staged refinance application-level link is invalid")
        if related["mobile_item_rows"]:
            raise ValueError("Mobile metadata must be rebuilt, not copied")
        for table in ("acc_gl_journal_entry", "m_savings_account", "m_share_account", "m_invoice"):
            if stage.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table),
            )).fetchone()[0]:
                raise ValueError(f"Staged seed contains excluded financial rows: {table}")
        signature_tables = sorted(set(order) | PROTECTED_CONFIGURATION_TABLES)
        stage_table_counts = {
            table: int(stage.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table),
            )).fetchone()[0]) for table in signature_tables
        }
        stage_table_hashes = {
            table: _row_digest(stage, table, sql.SQL("TRUE"), ()) for table in signature_tables
        }
        stage.commit()
    result = {
        "report_kind": "isolated-carry-forward-closed-loan-stage-v1",
        "arissto_through": classification["arissto_through"],
        "fineract_starts": classification["fineract_starts"],
        "capture_id": capture_id, "capture_manifest_sha256": manifest_sha256,
        "baseline_sha256": baseline_sha256,
        "protected_access_manifest_sha256": sha256_file(access_manifest),
        "gl_config_report_sha256": sha256_file(gl_config_report),
        "classification_hash": classification["classification_hash"],
        "input_database": source_db, "stage_database": stage_db,
        "retained_loan_count": len(loan_ids), "copied_rows": counts,
        "table_row_hashes": checksums,
        "stage_table_counts": stage_table_counts,
        "stage_table_hashes": stage_table_hashes,
        "copy_order": order, "refinance_links": related,
        "ready_for_tenant_replacement": False,
    }
    write_private_classification(result, output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--stage-db", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--baseline-dump", type=Path, required=True)
    parser.add_argument("--baseline-sha256", required=True)
    parser.add_argument("--access-manifest", type=Path, required=True)
    parser.add_argument("--gl-config-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = stage_closed_loan_seed(
        args.classification, args.source_db, args.stage_db, args.capture_id,
        args.manifest_sha256, args.baseline_dump, args.baseline_sha256,
        args.access_manifest, args.gl_config_report, args.output,
    )
    print(json.dumps({"stage_database": result["stage_database"],
                      "retained_loan_count": result["retained_loan_count"],
                      "copied_rows": result["copied_rows"],
                      "ready_for_tenant_replacement": False}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
