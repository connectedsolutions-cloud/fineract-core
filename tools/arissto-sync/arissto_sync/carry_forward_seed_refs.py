"""Audit the row and foreign-key closure needed by a retained-loan seed.

Both databases are isolated local copies: an immutable populated input capture
and a clean baseline stage. This command reads both and never copies rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from psycopg import sql

from .carry_forward_classify import write_private_classification
from .carry_forward_graph import LOAN_OWNED_V1, direct_loan_edges
from .config import load_settings
from .connections import postgres_connection


SOURCE_DB = re.compile(r"fineract_carry_input_[0-9]{8}\Z")
STAGE_DB = re.compile(r"fineract_carry_seed_stage_[0-9]{8}\Z")
REFINANCE_TABLES = frozenset({
    "m_account_transfer_details", "m_loan_topup", "m_loan_refinancing_settlement",
})
PRODUCT_CONFIG_SELECTORS = {
    "credesal_loan_product_map": "loan_product_id",
    "m_product_loan_charge": "product_loan_id",
    "m_product_loan_configurable_attributes": "loan_product_id",
    "m_product_loan_variable_installment_config": "loan_product_id",
}
LOAN_ACCOUNTING_CONFIG_TABLE = "acc_product_mapping"
TRANSITIVE_LOAN_TABLES = frozenset({
    "m_account_transfer_transaction", "m_loan_charge_paid_by",
    "m_loan_transaction_repayment_schedule_mapping",
    "m_client_collateral_property", "m_client_collateral_vehicle",
})
COPY_TABLES = frozenset({
    "m_loan", *LOAN_OWNED_V1, *REFINANCE_TABLES, *PRODUCT_CONFIG_SELECTORS,
    *TRANSITIVE_LOAN_TABLES, LOAN_ACCOUNTING_CONFIG_TABLE,
    "m_delinquency_bucket_mappings",
})
DENIED_PARENT_PREFIXES = ("acc_", "m_savings_", "m_share_", "m_invoice")
DENIED_PARENT_TABLES = frozenset({
    "m_loan_arrears_aging", "m_loan_account_locks", "m_loan_delinquency_action",
    "credesal_mobile_collection_item", "credesal_mobile_collection_batch",
})
REBUILT_REVERSE_CHILDREN = frozenset({
    "credesal_mobile_collection_item", "credesal_mobile_collection_account_assignment",
    "m_invoice",
})
REVERSE_AUDIT_PARENTS = frozenset({
    "m_loan", "m_loan_transaction", "m_loan_charge",
    "m_loan_repayment_schedule", "m_client_collateral_asset", "m_product_loan",
})


def isolated_url(sandbox_url: str, database: str, kind: str) -> str:
    parsed = urlparse(sandbox_url)
    expected = SOURCE_DB if kind == "input" else STAGE_DB if kind == "stage" else None
    if (expected is None or not expected.fullmatch(database)
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.path != "/fineract_sandbox"):
        raise ValueError("Seed audit requires isolated local input and stage databases")
    return urlunparse(parsed._replace(path="/" + database))


def _selected_predicate(table: str, loan_fk_columns: dict[str, set[str]]) -> tuple[Any, int]:
    if table == "m_loan":
        return sql.SQL("id = ANY(%s)"), 1
    if table == "m_account_transfer_transaction":
        owned = sql.SQL("SELECT id FROM m_loan_transaction WHERE loan_id = ANY(%s)")
        return sql.SQL("from_loan_transaction_id IN ({}) OR to_loan_transaction_id IN ({})").format(
            owned, owned,
        ), 2
    if table in {"m_loan_charge_paid_by", "m_loan_transaction_repayment_schedule_mapping"}:
        return sql.SQL("loan_transaction_id IN (SELECT id FROM m_loan_transaction WHERE loan_id = ANY(%s))"), 1
    if table in {"m_client_collateral_property", "m_client_collateral_vehicle"}:
        return sql.SQL("asset_id IN ("
                       "SELECT asset.id FROM m_client_collateral_asset asset "
                       "JOIN m_loan_collateral_management link "
                       "ON link.client_collateral_id=asset.client_collateral_id "
                       "WHERE link.loan_id = ANY(%s))"), 1
    if table == "m_account_transfer_details":
        columns = ["from_loan_account_id", "to_loan_account_id"]
    elif table == "m_loan_topup":
        columns = ["loan_id", "closure_loan_id"]
    elif table == "m_loan_refinancing_settlement":
        columns = ["closure_loan_id"]
    else:
        columns = sorted(loan_fk_columns.get(table, ()))
    if not columns:
        raise ValueError(f"No loan-owned selector for {table}")
    predicate = sql.SQL(" OR ").join(
        sql.SQL("{} = ANY(%s)").format(sql.Identifier(column)) for column in columns
    )
    return predicate, len(columns)


def _selection(
    table: str, loan_ids: list[int], product_ids: list[int],
    loan_fk_columns: dict[str, set[str]],
) -> tuple[Any, tuple[Any, ...]]:
    if table == LOAN_ACCOUNTING_CONFIG_TABLE:
        return sql.SQL("product_type = 1 AND product_id = ANY(%s)"), (product_ids,)
    if table == "m_delinquency_bucket_mappings":
        # A retained loan product brings its bucket and ranges through FK
        # closure. Preserve their join rows so the bucket is usable by the API.
        return sql.SQL("delinquency_bucket_id IN ("
                       "SELECT delinquency_bucket_id FROM m_product_loan "
                       "WHERE id = ANY(%s) AND delinquency_bucket_id IS NOT NULL)"), (product_ids,)
    if table in PRODUCT_CONFIG_SELECTORS:
        return sql.SQL("{} = ANY(%s)").format(
            sql.Identifier(PRODUCT_CONFIG_SELECTORS[table]),
        ), (product_ids,)
    predicate, n = _selected_predicate(table, loan_fk_columns)
    return predicate, (loan_ids,) * n


def _selected_values(
    conn: Any, table: str, column: str, loan_ids: list[int],
    product_ids: list[int], loan_fk_columns: dict[str, set[str]],
) -> set[str]:
    predicate, params = _selection(table, loan_ids, product_ids, loan_fk_columns)
    query = sql.SQL("SELECT DISTINCT {} FROM {} WHERE ({}) AND {} IS NOT NULL").format(
        sql.Identifier(column), sql.Identifier(table), predicate, sql.Identifier(column),
    )
    return {str(row[0]) for row in conn.execute(query, params).fetchall()}


def _foreign_keys(conn: Any, tables: set[str]) -> list[tuple[str, str, str, str, int]]:
    return [
        (str(table), str(column), str(reference_table), str(reference_column), int(width))
        for table, column, reference_table, reference_column, width in conn.execute("""
            SELECT child.relname, child_column.attname, parent.relname,
                   parent_column.attname, cardinality(fk.conkey)
            FROM pg_constraint fk
            JOIN pg_class child ON child.oid=fk.conrelid
            JOIN pg_namespace ns ON ns.oid=child.relnamespace
            JOIN pg_class parent ON parent.oid=fk.confrelid
            JOIN pg_attribute child_column ON child_column.attrelid=fk.conrelid
                                          AND child_column.attnum=fk.conkey[1]
            JOIN pg_attribute parent_column ON parent_column.attrelid=fk.confrelid
                                           AND parent_column.attnum=fk.confkey[1]
            WHERE fk.contype='f' AND ns.nspname='public' AND child.relname = ANY(%s)
            ORDER BY child.relname,fk.conname
        """, (sorted(tables),)).fetchall()
    ]


def _changelog_signature(conn: Any) -> str:
    rows = conn.execute("""
        SELECT id,author,filename,md5sum,exectype
        FROM databasechangelog ORDER BY filename,author,id
    """).fetchall()
    encoded = json.dumps(rows, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _stage_and_source_values(
    source: Any, stage: Any, table: str, column: str, values: set[str],
) -> tuple[set[str], set[str]]:
    if not values:
        return set(), set()
    query = sql.SQL("SELECT DISTINCT {} FROM {} WHERE {}::text = ANY(%s)").format(
        sql.Identifier(column), sql.Identifier(table), sql.Identifier(column),
    )
    params = (sorted(values),)
    source_values = {str(row[0]) for row in source.execute(query, params).fetchall()}
    stage_values = {str(row[0]) for row in stage.execute(query, params).fetchall()}
    return source_values, stage_values


def _dependency_closure(
    source: Any, stage: Any, initial_tables: set[str], loan_ids: list[int],
    product_ids: list[int], loan_fk_columns: dict[str, set[str]],
) -> tuple[dict[str, set[int]], list[str], list[dict[str, Any]]]:
    """Follow parent FKs only; never infer child rows or financial domains."""
    planned: dict[str, set[int]] = {}
    pending = set(initial_tables)
    blockers: set[str] = set()
    references: list[dict[str, Any]] = []
    # Fineract stores customer-guarantor client IDs in m_guarantor.entity_id
    # without a PostgreSQL FK. Preserve that application-level dependency.
    if "m_guarantor" in initial_tables:
        guarantor_ids = {str(row[0]) for row in source.execute(
            "SELECT DISTINCT entity_id FROM m_guarantor "
            "WHERE loan_id=ANY(%s) AND type_enum=1 AND entity_id IS NOT NULL",
            (loan_ids,),
        ).fetchall()}
        if guarantor_ids:
            source_clients, stage_clients = _stage_and_source_values(
                source, stage, "m_client", "id", guarantor_ids,
            )
            if guarantor_ids - source_clients:
                blockers.add("dangling_guarantor_client_reference")
            missing = guarantor_ids - stage_clients
            if missing:
                planned.setdefault("m_client", set()).update(int(value) for value in missing)
                pending.add("m_client")
            references.append({
                "table": "m_guarantor", "column": "entity_id",
                "references": "m_client", "required_values": len(guarantor_ids),
                "absent_from_stage": len(missing), "application_level": True,
            })
    while pending:
        table = pending.pop()
        for child, column, parent, parent_column, width in _foreign_keys(source, {table}):
            if width != 1:
                blockers.add(f"composite_foreign_key:{child}.{column}")
                continue
            if table in initial_tables:
                predicate, params = _selection(
                    table, loan_ids, product_ids, loan_fk_columns,
                )
            else:
                predicate = sql.SQL("id = ANY(%s)")
                params = (sorted(planned[table]),)
            query = sql.SQL("SELECT DISTINCT {} FROM {} WHERE ({}) AND {} IS NOT NULL").format(
                sql.Identifier(column), sql.Identifier(child), predicate,
                sql.Identifier(column),
            )
            values = {str(row[0]) for row in source.execute(query, params).fetchall()}
            if not values:
                continue
            source_values, stage_values = _stage_and_source_values(
                source, stage, parent, parent_column, values,
            )
            absent = values - stage_values
            if values - source_values:
                blockers.add(f"dangling_source_reference:{child}.{column}->{parent}")
            references.append({
                "table": child, "column": column, "references": parent,
                "required_values": len(values), "absent_from_stage": len(absent),
            })
            if not absent:
                continue
            if parent in initial_tables:
                # The exact component closure is checked by the direct audit below.
                continue
            if (parent.startswith(DENIED_PARENT_PREFIXES)
                    or parent in DENIED_PARENT_TABLES):
                blockers.add(f"cross_domain_dependency:{child}.{column}->{parent}")
                continue
            if parent_column != "id":
                blockers.add(f"non_id_dependency:{child}.{column}->{parent}.{parent_column}")
                continue
            new_ids = {int(value) for value in absent} - planned.get(parent, set())
            if new_ids:
                planned.setdefault(parent, set()).update(new_ids)
                pending.add(parent)
    return planned, sorted(blockers), references


def _reverse_fk_edges(conn: Any, parents: set[str]) -> list[tuple[str, str, str, int]]:
    return [
        (str(parent), str(child), str(column), int(width))
        for parent, child, column, width in conn.execute("""
            SELECT parent.relname, child.relname, attribute.attname,
                   cardinality(fk.conkey)
            FROM pg_constraint fk
            JOIN pg_class child ON child.oid=fk.conrelid
            JOIN pg_class parent ON parent.oid=fk.confrelid
            JOIN pg_namespace ns ON ns.oid=child.relnamespace
            JOIN pg_attribute attribute ON attribute.attrelid=child.oid
                                       AND attribute.attnum=fk.conkey[1]
            WHERE fk.contype='f' AND ns.nspname='public'
              AND parent.relname = ANY(%s)
            ORDER BY parent.relname,child.relname,fk.conname
        """, (sorted(parents),)).fetchall()
    ]


def _audit_reverse_edges(
    source: Any, loan_ids: list[int], product_ids: list[int],
    loan_fk_columns: dict[str, set[str]], planned: dict[str, set[int]],
    selected_rows: dict[str, int],
) -> tuple[list[dict[str, Any]], list[str]]:
    parent_ids: dict[str, set[int]] = {}
    for parent in REVERSE_AUDIT_PARENTS:
        if parent == "m_product_loan":
            parent_ids[parent] = set(product_ids)
        elif parent in planned:
            parent_ids[parent] = planned[parent]
        else:
            predicate, params = _selection(
                parent, loan_ids, product_ids, loan_fk_columns,
            )
            query = sql.SQL("SELECT id FROM {} WHERE ({})").format(
                sql.Identifier(parent), predicate,
            )
            parent_ids[parent] = {
                int(row[0]) for row in source.execute(query, params).fetchall()
            }
    findings: list[dict[str, Any]] = []
    blockers: set[str] = set()
    for parent, child, column, width in _reverse_fk_edges(source, set(REVERSE_AUDIT_PARENTS)):
        ids = parent_ids[parent]
        if not ids:
            continue
        if width != 1:
            blockers.add(f"composite_reverse_edge:{parent}->{child}")
            continue
        count = int(source.execute(sql.SQL(
            "SELECT COUNT(*) FROM {} WHERE {} = ANY(%s)"
        ).format(sql.Identifier(child), sql.Identifier(column)), (sorted(ids),)).fetchone()[0])
        if not count:
            continue
        disposition = (
            "copy" if child in COPY_TABLES or child in planned else
            "rebuild" if child in REBUILT_REVERSE_CHILDREN else "unreviewed"
        )
        findings.append({
            "parent": parent, "child": child, "column": column,
            "input_rows": count, "disposition": disposition,
        })
        if disposition == "unreviewed":
            blockers.add(f"unreviewed_reverse_edge:{parent}->{child}")
        elif (disposition == "copy" and child != "m_loan"
              and count > (selected_rows.get(child, 0)
                           if child in COPY_TABLES else len(planned[child]))):
            blockers.add(f"reverse_scope_exceeds_copy:{parent}->{child}")
    return findings, sorted(blockers)


def _loan_product_gl_masters(
    source: Any, stage: Any, product_ids: list[int],
) -> dict[str, int]:
    ids = [int(row[0]) for row in source.execute("""
        SELECT DISTINCT gl_account_id FROM acc_product_mapping
        WHERE product_type=1 AND product_id=ANY(%s)
    """, (product_ids,)).fetchall()]
    query = """
        SELECT id,gl_code,name,classification_enum,account_usage,disabled
        FROM acc_gl_account WHERE id=ANY(%s)
    """
    source_rows = {int(row[0]): tuple(row[1:]) for row in source.execute(query, (ids,))}
    stage_rows = {int(row[0]): tuple(row[1:]) for row in stage.execute(query, (ids,))}
    return {
        "required": len(ids),
        "missing_or_semantically_different": sum(
            source_rows.get(item) != stage_rows.get(item) for item in ids
        ),
    }


def audit_seed_references(
    classification_path: Path, source_db: str, stage_db: str,
    env_file: str | None = None,
) -> dict[str, Any]:
    settings = load_settings("local", env_file)
    if settings.target.tenant != "sandbox" or not settings.target.pg_url:
        raise ValueError("Seed audit is restricted to the local sandbox profile")
    root = (settings.state_path.parent / "carry-forward").resolve()
    if not classification_path.resolve().is_relative_to(root):
        raise ValueError("Classification must be inside private carry-forward state")
    report = json.loads(classification_path.read_text(encoding="utf-8"))
    if report.get("report_kind") != "read-only-carry-forward-loan-classification-v1":
        raise ValueError("Unexpected loan classification report")
    if report.get("old_cutoff_binding", {}).get("date") != report.get("old_fineract_starts"):
        raise ValueError("Classification cutoff binding mismatch")
    candidate_rows = [row for row in report["loans"]
                      if row["disposition"] in {"retain-candidate", "retain-review"}]
    loan_ids = sorted(int(row["target_id"]) for row in candidate_rows)
    if len(loan_ids) != len(set(loan_ids)) or not loan_ids or any(value <= 0 for value in loan_ids):
        raise ValueError("Potential retained loan IDs must be unique and positive")

    input_url = isolated_url(settings.target.pg_url, source_db, "input")
    stage_url = isolated_url(settings.target.pg_url, stage_db, "stage")
    with postgres_connection(input_url) as source, postgres_connection(stage_url) as stage:
        source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        stage.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        source_changelog = int(source.execute("SELECT COUNT(*) FROM databasechangelog").fetchone()[0])
        stage_changelog = int(stage.execute("SELECT COUNT(*) FROM databasechangelog").fetchone()[0])
        if source_changelog != stage_changelog:
            raise ValueError("Input and staged baseline Liquibase counts differ")
        changelog_signature = _changelog_signature(source)
        if changelog_signature != _changelog_signature(stage):
            raise ValueError("Input and staged baseline Liquibase entries differ")
        for table in ("m_loan", "m_product_loan", "acc_gl_journal_entry", "m_invoice"):
            if int(stage.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table))).fetchone()[0]):
                raise ValueError(f"Staged baseline is not clean: {table}")
        present = {int(row[0]) for row in source.execute(
            "SELECT id FROM m_loan WHERE id = ANY(%s)", (loan_ids,),
        ).fetchall()}
        if present != set(loan_ids):
            raise ValueError("Immutable input capture lacks a classified loan ID")
        loan_fk_columns: dict[str, set[str]] = defaultdict(set)
        for table, _, column, width in direct_loan_edges(source):
            if width != 1 and table in COPY_TABLES:
                raise ValueError(f"Composite loan foreign key requires review: {table}")
            loan_fk_columns[table].add(column)
        product_ids = sorted(int(row[0]) for row in source.execute(
            "SELECT DISTINCT product_id FROM m_loan WHERE id = ANY(%s)", (loan_ids,),
        ).fetchall())

        selected_rows: dict[str, int] = {}
        for table in sorted(COPY_TABLES):
            predicate, params = _selection(
                table, loan_ids, product_ids, loan_fk_columns,
            )
            query = sql.SQL("SELECT COUNT(*) FROM {} WHERE ({})").format(
                sql.Identifier(table), predicate,
            )
            selected_rows[table] = int(source.execute(
                query, params,
            ).fetchone()[0])
        planned, closure_blockers, closure_references = _dependency_closure(
            source, stage, {table for table, count in selected_rows.items() if count},
            loan_ids, product_ids, loan_fk_columns,
        )
        reverse_edges, reverse_blockers = _audit_reverse_edges(
            source, loan_ids, product_ids, loan_fk_columns, planned,
            selected_rows,
        )
        gl_masters = _loan_product_gl_masters(source, stage, product_ids)

        selected_cache: dict[tuple[str, str], set[str]] = {}
        stage_cache: dict[tuple[str, str], set[str]] = {}
        edges: list[dict[str, Any]] = []
        missing_by_table: dict[str, set[str]] = defaultdict(set)
        blockers: list[str] = []
        blockers.extend(closure_blockers)
        blockers.extend(reverse_blockers)
        if gl_masters["missing_or_semantically_different"]:
            blockers.append("loan_product_gl_master_mismatch")
        for table, column, parent, parent_column, width in _foreign_keys(source, set(COPY_TABLES)):
            if selected_rows[table] == 0:
                continue
            if width != 1:
                blockers.append(f"composite_foreign_key:{table}.{column}")
                continue
            values = _selected_values(
                source, table, column, loan_ids, product_ids, loan_fk_columns,
            )
            if not values:
                continue
            parent_key = (parent, parent_column)
            if parent_key not in stage_cache:
                stage_cache[parent_key] = {str(row[0]) for row in stage.execute(
                    sql.SQL("SELECT DISTINCT {} FROM {} WHERE {} IS NOT NULL").format(
                        sql.Identifier(parent_column), sql.Identifier(parent),
                        sql.Identifier(parent_column),
                    )).fetchall()}
            available = stage_cache[parent_key]
            if parent in COPY_TABLES:
                if parent_key not in selected_cache:
                    selected_cache[parent_key] = _selected_values(
                        source, parent, parent_column, loan_ids, product_ids,
                        loan_fk_columns,
                    )
                available = available | selected_cache[parent_key]
            missing = values - available
            missing_by_table[parent].update(missing)
            edges.append({
                "table": table, "column": column,
                "references": parent, "reference_column": parent_column,
                "referenced_ids": len(values), "missing_ids": len(missing),
                "parent_planned_for_copy": parent in COPY_TABLES,
            })
            if missing and parent in COPY_TABLES:
                blockers.append(f"selected_graph_not_closed:{table}.{column}->{parent}")
    return {
        "report_kind": "read-only-carry-forward-seed-reference-audit-v1",
        "arissto_through": report["arissto_through"],
        "fineract_starts": report["fineract_starts"],
        "classification_hash": report["classification_hash"],
        "input_database": source_db,
        "stage_database": stage_db,
        "liquibase_entries": source_changelog,
        "liquibase_signature": changelog_signature,
        "potential_retained_loans": len(loan_ids),
        "selected_rows": selected_rows,
        "planned_parent_rows_by_table": {table: len(ids) for table, ids in sorted(planned.items())},
        "closure_references": closure_references,
        "reverse_edges": reverse_edges,
        "loan_product_gl_masters": gl_masters,
        "missing_dependencies_by_table": {
            table: len(values) for table, values in sorted(missing_by_table.items()) if values
        },
        "edges": edges,
        "blockers": sorted(set(blockers)),
        "ready_for_seed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--stage-db", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_seed_references(args.classification, args.source_db, args.stage_db)
    if args.output:
        write_private_classification(report, args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not report["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
