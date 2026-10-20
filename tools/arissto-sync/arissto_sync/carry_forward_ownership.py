"""Read-only inventory of target events whose accounting owner would change.

This is a conservative inventory, not permission to replace the tenant. Every
event found in the interval needs a reviewed source match or carry rule.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from psycopg import sql

from .carry_forward_boundary import CarryForwardBoundary
from .arissto import select_rows, source_connection
from .config import SourceConfig, TargetConfig, load_settings
from .connections import postgres_connection


# Explicitly version the event surfaces. A missing surface blocks the audit.
EVENT_SURFACES_V1: tuple[tuple[str, str], ...] = (
    ("m_loan_transaction", "transaction_date"),
    ("m_loan_transaction", "reversed_on_date"),
    ("m_savings_account_transaction", "transaction_date"),
    ("m_share_account_transactions", "transaction_date"),
    ("acc_gl_journal_entry", "entry_date"),
    ("acc_gl_journal_entry", "transaction_date"),
    ("m_cashier_transactions", "txn_date"),
    ("m_invoice", "fec_emi"),
    ("credesal_mobile_collection_item", "source_movement_date"),
    ("credesal_mobile_collection_batch", "source_date"),
    ("credesal_mobile_collection_batch", "collection_date"),
    ("m_account_transfer_transaction", "transaction_date"),
    ("m_account_transfer_standing_instructions_history", "execution_time"),
    ("m_client_transaction", "transaction_date"),
    ("m_deposit_account_on_hold_transaction", "transaction_date"),
    ("m_office_transaction", "transaction_date"),
    ("m_share_account_yield_accrual", "accrual_date"),
    ("m_share_account_yield_settlement", "settlement_date"),
    ("credesal_cash_flow_transaction", "movement_date"),
    ("credesal_cash_flow_transaction", "operation_date"),
    ("credesal_savings_native_event_map", "event_date"),
    ("credesal_share_native_event_map", "event_date"),
    ("m_external_asset_owner_transfer", "settlement_date"),
    ("m_loan_disbursement_detail", "disbursedon_date"),
    ("m_loan_status_change_history", "status_change_business_date"),
    ("m_loan_freeze_history", "effective_date"),
    ("m_loan_delinquency_action", "start_date"),
    ("m_loan_reschedule_request", "submitted_on_date"),
    ("m_client_charge", "charge_due_date"),
    ("m_savings_account_charge", "charge_due_date"),
)

LOAN_DATED_ROWS_V1: tuple[tuple[str, str], ...] = (
    ("m_loan_charge", "submitted_on_date"),
    ("m_loan_term_variations", "applicable_date"),
)


def _native_accrual_proof(
    conn: Any, interval_start: date, interval_end: date,
    dispositions: dict[str, str],
) -> tuple[dict[str, Any], dict[tuple[int, str], tuple[Decimal, Decimal]]]:
    """Prove that every superseded Fineract event is a replayable COB accrual."""
    transactions = conn.execute("""
        SELECT t.id,t.loan_id,t.transaction_date,t.transaction_type_enum,
               t.is_reversed,t.external_id,t.amount,
               COALESCE(t.principal_portion_derived,0),
               COALESCE(t.interest_portion_derived,0),
               COALESCE(t.fee_charges_portion_derived,0),
               COALESCE(t.penalty_charges_portion_derived,0),l.external_id
        FROM m_loan_transaction t JOIN m_loan l ON l.id=t.loan_id
        WHERE t.transaction_date >= %s AND t.transaction_date < %s
        ORDER BY t.id
    """, (interval_start, interval_end)).fetchall()
    identifiers = [int(row[0]) for row in transactions]
    journals = conn.execute("""
        SELECT id,loan_transaction_id,entry_date,entity_type_enum,entity_id,
               manual_entry,reversed,type_enum,amount
        FROM acc_gl_journal_entry
        WHERE (entry_date >= %s AND entry_date < %s)
           OR loan_transaction_id = ANY(%s)
        ORDER BY id
    """, (interval_start, interval_end, identifiers)).fetchall()
    blockers: set[str] = set()
    by_id = {int(row[0]): row for row in transactions}
    totals = {identifier: [Decimal(0), Decimal(0)] for identifier in identifiers}
    native_by_source: dict[tuple[int, str], tuple[Decimal, Decimal]] = {}
    if len(by_id) != len(transactions):
        blockers.add("duplicate_native_accrual_identity")
    for row in transactions:
        identifier, _, day, kind, reversed_, external_id, amount = row[:7]
        principal, interest, fee, penalty, loan_external_id = row[7:]
        prefix = "ARISSTO:CRD:"
        source_id = str(loan_external_id or "")[len(prefix):]
        if (kind != 10 or reversed_ or external_id is not None
                or Decimal(principal) != 0
                or Decimal(amount) != sum((Decimal(interest), Decimal(fee), Decimal(penalty)))
                or not str(loan_external_id or "").startswith(prefix)
                or not source_id.isdecimal()
                or dispositions.get("loan:" + source_id) != "replay"):
            blockers.add("unproved_native_accrual_transaction")
        else:
            key = (int(source_id), day.isoformat())
            prior_interest, prior_fee = native_by_source.get(key, (Decimal(0), Decimal(0)))
            native_by_source[key] = (prior_interest + Decimal(interest),
                                     prior_fee + Decimal(fee) + Decimal(penalty))
    for row in journals:
        _, transaction_id, entry_day, entity_type, entity_id, manual, reversed_, side, amount = row
        transaction = by_id.get(int(transaction_id)) if transaction_id is not None else None
        if (transaction is None or entry_day != transaction[2]
                or entity_type != 1 or entity_id != transaction[1]
                or manual or reversed_ or side not in (1, 2)):
            blockers.add("unproved_native_accrual_journal")
            continue
        totals[int(transaction_id)][0 if side == 1 else 1] += Decimal(amount)
    for row in transactions:
        amount = Decimal(row[6])
        if totals[int(row[0])] != [amount, amount]:
            blockers.add("native_accrual_journal_not_balanced")
    payload = {
        "transactions": [tuple(str(item) for item in row) for row in transactions],
        "journals": [tuple(str(item) for item in row) for row in journals],
    }
    report = {
        "transaction_count": len(transactions),
        "journal_line_count": len(journals),
        "transaction_amount": str(sum((Decimal(row[6]) for row in transactions), Decimal(0))),
        "journal_debits": str(sum((amounts[1] for amounts in totals.values()), Decimal(0))),
        "journal_credits": str(sum((amounts[0] for amounts in totals.values()), Decimal(0))),
        "evidence_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        "blockers": sorted(blockers),
    }
    return report, native_by_source


def _source_accrual_comparison(
    source: SourceConfig, interval_start: date, interval_end: date,
    native_by_source: dict[tuple[int, str], tuple[Decimal, Decimal]],
) -> dict[str, Any]:
    """Freeze per-loan source differences without treating shadow accrual as GL."""
    with source_connection(source) as conn:
        snapshots = select_rows(conn, """
            WITH ranked AS (
                SELECT ID_CREDITO,CAST(ULTIMA_FECHA_CALC AS date) AS accrual_date,
                       COALESCE(INT_PROV_CNT,0) AS amount,
                       ROW_NUMBER() OVER (
                           PARTITION BY ID_CREDITO,CAST(ULTIMA_FECHA_CALC AS date)
                           ORDER BY ID_CIERRE_DIARIO DESC,ID_CRD_HISTORICO_DIARIO DESC
                       ) AS rn
                FROM dbo.CRD_HISTORICO_DIARIO
                WHERE ULTIMA_FECHA_CALC >= ? AND ULTIMA_FECHA_CALC < ?
            )
            SELECT ID_CREDITO,accrual_date,amount FROM ranked WHERE rn=1
        """, (interval_start, interval_end))
        journals = select_rows(conn, """
            SELECT CAST(p.FECHA_PARTIDA AS date) AS accrual_date,
                   COUNT(DISTINCT p.ID_PARTIDA) AS journal_count,
                   SUM(COALESCE(d.DEBE,0)) AS debit,
                   SUM(COALESCE(d.HABER,0)) AS credit
            FROM dbo.CNT_PARTIDAS p JOIN dbo.CNT_DETALLE_PARTIDAS d
              ON d.ID_EMPRESA=p.ID_EMPRESA AND d.ID_SUCURSAL=p.ID_SUCURSAL
             AND d.ID_PERIODO=p.ID_PERIODO AND d.ID_PARTIDA=p.ID_PARTIDA
            WHERE p.FECHA_PARTIDA >= ? AND p.FECHA_PARTIDA < ?
              AND p.ESTADO_PARTIDA='3'
              AND p.CONCEPTO LIKE 'PROVISION Y CONTABILIZACI%INTERESES NORMALES EN CREDITOS%'
            GROUP BY CAST(p.FECHA_PARTIDA AS date)
        """, (interval_start, interval_end))
    source_by_key = {
        (int(row["ID_CREDITO"]), row["accrual_date"].isoformat()): Decimal(row["amount"])
        for row in snapshots
    }
    details = []
    for key in sorted(source_by_key.keys() | native_by_source.keys()):
        source_amount = source_by_key.get(key)
        native = native_by_source.get(key)
        details.append({
            "source_loan_id": key[0], "date": key[1],
            "arissto_interest": str(source_amount) if source_amount is not None else None,
            "fineract_interest": str(native[0]) if native is not None else None,
            "fineract_fee_penalty": str(native[1]) if native is not None else None,
            "interest_variance": str(source_amount - native[0])
            if source_amount is not None and native is not None else None,
        })
    journal_days = {
        row["accrual_date"].isoformat(): row for row in journals
    }
    missing_days = sorted({
        key[1] for key in native_by_source
        if key[1] not in journal_days
    })
    unbalanced_days = sorted(
        day for day, row in journal_days.items()
        if row["debit"] != row["credit"] or row["debit"] <= 0
    )
    return {
        "source_snapshot_count": len(source_by_key),
        "source_interest_total": str(sum(source_by_key.values(), Decimal(0))),
        "native_interest_total": str(sum((v[0] for v in native_by_source.values()), Decimal(0))),
        "native_fee_penalty_total": str(sum((v[1] for v in native_by_source.values()), Decimal(0))),
        "shared_loan_days": sum(key in source_by_key for key in native_by_source),
        "matching_interest_loan_days": sum(
            source_by_key.get(key) == value[0] for key, value in native_by_source.items()
            if key in source_by_key
        ),
        "source_only_loan_days": sum(key not in native_by_source for key in source_by_key),
        "native_only_loan_days": sum(key not in source_by_key for key in native_by_source),
        # An open source day may have accrued snapshots before its GL journal
        # posts. Record that timing difference without gating a carry-forward.
        "source_accrual_journal_pending_days": missing_days,
        "source_posted_accrual_journals": [
            {"date": day, "journal_count": int(row["journal_count"]),
             "debit": str(row["debit"]), "credit": str(row["credit"])}
            for day, row in sorted(journal_days.items())
        ],
        "per_loan_differences": [
            item for item in details
            if item["arissto_interest"] is None or item["fineract_interest"] is None
            or Decimal(item["interest_variance"]) != 0
        ],
        "blockers": [
            "unbalanced_source_accrual_journal:" + day for day in unbalanced_days
        ],
    }


def inventory_counts(
    conn: Any, boundary: CarryForwardBoundary,
    surfaces: tuple[tuple[str, str], ...] = EVENT_SURFACES_V1,
) -> dict[str, Any]:
    """Count each known event class in [old T, new T) in one read transaction."""
    columns = {
        (str(table), str(column)) for table, column in conn.execute("""
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema='public'
        """).fetchall()
    }
    old_t = date.fromisoformat(boundary.old_fineract_starts)
    new_t = date.fromisoformat(boundary.fineract_starts)
    findings: list[dict[str, Any]] = []
    blockers: list[str] = []
    for table, column in surfaces:
        if (table, column) not in columns:
            blockers.append(f"missing_event_surface:{table}.{column}")
            continue
        query = sql.SQL("SELECT COUNT(*) FROM {} WHERE {} >= %s AND {} < %s").format(
            sql.Identifier(table), sql.Identifier(column), sql.Identifier(column),
        )
        count = int(conn.execute(query, (old_t, new_t)).fetchone()[0])
        findings.append({"table": table, "date_column": column, "event_count": count})
        if count:
            blockers.append(f"unreviewed_interval_events:{table}")
    return {
        "report_kind": "carry-forward-target-ownership-inventory-v1",
        "arissto_through": boundary.arissto_through,
        "fineract_starts": boundary.fineract_starts,
        "old_fineract_starts": boundary.old_fineract_starts,
        "interval_start_inclusive": old_t.isoformat(),
        "interval_end_inclusive": (new_t - timedelta(days=1)).isoformat(),
        "surfaces": findings,
        "blockers": blockers,
        "known_interval_event_count": sum(row["event_count"] for row in findings),
        "ownership_interval_clear": not blockers,
        "ready_for_replacement": False,
    }


def inspect_ownership(target: TargetConfig, old_fineract_starts: str,
                      arissto_through: str, *, classification_path: Path | None = None,
                      old_state_path: Path | None = None,
                      source: SourceConfig | None = None) -> dict[str, Any]:
    if target.name != "local" or target.tenant != "sandbox" or not target.pg_url:
        raise ValueError("Carry-forward ownership inventory requires the local sandbox")
    from urllib.parse import urlparse
    parsed = urlparse(target.pg_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.path != "/fineract_sandbox":
        raise ValueError("Carry-forward ownership inventory requires local fineract_sandbox")
    boundary = CarryForwardBoundary.select(old_fineract_starts, arissto_through)
    with postgres_connection(target.pg_url) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        report = inventory_counts(conn, boundary)
        disposition_by_target: dict[int, str] = {}
        classification: dict[str, Any] | None = None
        if classification_path is not None and old_state_path is not None:
            classification = json.loads(classification_path.read_text(encoding="utf-8"))
            if (classification["arissto_through"] != arissto_through
                    or classification["old_fineract_starts"] != old_fineract_starts):
                raise ValueError("Loan ownership classification uses another boundary")
            by_key = {row["source_key"]: row for row in classification["loans"]}
            with sqlite3.connect(old_state_path.resolve().as_uri() + "?immutable=1", uri=True) as state:
                for key, target_id in state.execute(
                    "SELECT source_key,target_id FROM mappings "
                    "WHERE target_fingerprint=? AND block='loans' AND source_key LIKE 'loan:%'",
                    (target.fingerprint,),
                ):
                    row = by_key.get(key)
                    if row and row["source_hash"] and row["disposition"] in {
                        "retain-candidate", "retain-review", "replay",
                    }:
                        disposition_by_target[int(target_id)] = (
                            "retained-copy" if row["disposition"].startswith("retain-")
                            else "source-replay"
                        )
        interval_start = date.fromisoformat(boundary.old_fineract_starts)
        interval_end = date.fromisoformat(boundary.fineract_starts)
        dispositions = {
            str(row["source_key"]): str(row["disposition"])
            for row in (classification or {}).get("loans", [])
        }
        native, native_by_source = _native_accrual_proof(
            conn, interval_start, interval_end, dispositions,
        )
        report["native_accrual_replacement"] = native
        if native["transaction_count"] or native["journal_line_count"]:
            if source is None:
                report["blockers"].append("source_accrual_comparison_required")
            elif native["blockers"]:
                report["blockers"].extend(native["blockers"])
            else:
                comparison = _source_accrual_comparison(
                    source, interval_start, interval_end, native_by_source,
                )
                report["source_accrual_comparison"] = comparison
                if comparison["blockers"]:
                    report["blockers"].extend(comparison["blockers"])
                else:
                    report["blockers"] = [
                        blocker for blocker in report["blockers"] if blocker not in {
                            "unreviewed_interval_events:m_loan_transaction",
                            "unreviewed_interval_events:acc_gl_journal_entry",
                        }
                    ]
        reviewed = []
        for table, column in LOAN_DATED_ROWS_V1:
            query = sql.SQL("SELECT loan_id{} FROM {} WHERE {} >= %s AND {} < %s").format(
                sql.SQL(",external_id") if table == "m_loan_charge" else sql.SQL(""),
                sql.Identifier(table), sql.Identifier(column), sql.Identifier(column),
            )
            rows = conn.execute(query, (interval_start, interval_end)).fetchall()
            outcomes = {"retained-copy": 0, "source-replay": 0, "unreviewed": 0}
            for row in rows:
                disposition = disposition_by_target.get(int(row[0]))
                if table == "m_loan_charge" and not str(row[1] or "").startswith(
                    "ARISSTO:CRD-INS-FUTURE:"
                ):
                    disposition = None
                outcomes[disposition or "unreviewed"] += 1
            reviewed.append({"table": table, "date_column": column, "event_count": len(rows),
                             "ownership": outcomes})
            if outcomes["unreviewed"]:
                report["blockers"].append(f"unreviewed_loan_dated_rows:{table}")
        report["loan_dated_rows"] = reviewed
        report["known_interval_event_count"] += sum(item["event_count"] for item in reviewed)
        report["reviewed_retained_copy_count"] = sum(
            item["ownership"]["retained-copy"] for item in reviewed
        )
        report["reviewed_source_replay_count"] = sum(
            item["ownership"]["source-replay"] for item in reviewed
        )
        report["blockers"] = sorted(set(report["blockers"]))
        report["ownership_interval_clear"] = not report["blockers"]
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local",), required=True)
    parser.add_argument("--old-fineract-starts", required=True)
    parser.add_argument("--source-through-date", required=True)
    args = parser.parse_args()
    report = inspect_ownership(load_settings(args.target).target,
                               args.old_fineract_starts, args.source_through_date)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ownership_interval_clear"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
