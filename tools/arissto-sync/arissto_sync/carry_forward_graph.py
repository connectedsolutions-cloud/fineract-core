"""Read-only direct foreign-key audit for target-eligible closed loans.

This reports one layer of the staged-seed graph. It deliberately cannot
authorize a seed until transitive and application-level edges are proved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from psycopg import sql

from .config import TargetConfig, load_settings
from .connections import postgres_connection
from .carry_forward_verify import verify_local_candidates_with_ids


LOAN_OWNED_V1 = frozenset({
    "credesal_loan_legacy_timeline", "credesal_loan_staff_assignment",
    "m_guarantor", "m_loan_amortization_allocation_mapping",
    "m_loan_approved_amount_history", "m_loan_buy_down_fee_balance",
    "m_loan_capitalized_income_balance", "m_loan_charge", "m_loan_collateral",
    "m_loan_collateral_management", "m_loan_credit_allocation_rule",
    "m_loan_delinquency_action", "m_loan_delinquency_tag_history",
    "m_loan_disbursement_detail", "m_loan_freeze_history",
    "m_loan_installment_delinquency_tag", "m_loan_officer_assignment_history",
    "m_loan_payment_allocation_rule", "m_loan_progressive_model", "m_loan_rate",
    "m_loan_recalculation_details", "m_loan_repayment_schedule",
    "m_loan_repayment_schedule_history", "m_loan_reschedule_request",
    "m_loan_status_change_history", "m_loan_term_variations",
    "m_loan_tranche_charges", "m_loan_transaction", "m_note",
})

# These edges are either financial domains rebuilt separately, derived state,
# or cross-loan references that need explicit component-level proof.
REVIEW_REQUIRED_V1 = frozenset({
    "credesal_mobile_collection_account_assignment",
    "credesal_mobile_collection_item",
    "m_account_transfer_details", "m_external_asset_owner_transfer",
    "m_external_asset_owner_transfer_loan_mapping", "m_loan_account_locks",
    "m_loan_arrears_aging", "m_loan_refinancing_settlement", "m_loan_topup",
    "m_portfolio_account_associations", "m_repayment_with_post_dated_checks",
})

# These are known cross-domain or refinance links. Each needs an explicit
# copy-or-rebuild proof before a retained loan can enter a staged seed.
KNOWN_REVIEW_EDGES_V1 = frozenset({
    "credesal_mobile_collection_account_assignment",
    "credesal_mobile_collection_item",
    "m_account_transfer_details", "m_loan_refinancing_settlement", "m_loan_topup",
})

# The complete carry-forward workflow rebuilds these source-owned operational
# rows through mobile-collections. That service does not write native loan
# transactions or GL; its links resolve to the retained loan/transaction IDs.
MOBILE_METADATA_REBUILT_V1 = frozenset({
    "credesal_mobile_collection_account_assignment",
    "credesal_mobile_collection_item",
})


def direct_loan_edges(conn: Any) -> list[tuple[str, str, str, int]]:
    return [
        (str(table), str(constraint), str(column), int(width))
        for table, constraint, column, width in conn.execute("""
            SELECT rel.relname, fk.conname, attr.attname, cardinality(fk.conkey)
            FROM pg_constraint AS fk
            JOIN pg_class AS rel ON rel.oid=fk.conrelid
            JOIN pg_namespace AS ns ON ns.oid=rel.relnamespace
            JOIN pg_attribute AS attr ON attr.attrelid=fk.conrelid
                                  AND attr.attnum=fk.conkey[1]
            WHERE fk.contype='f' AND fk.confrelid='public.m_loan'::regclass
              AND ns.nspname='public'
            ORDER BY rel.relname,fk.conname
        """).fetchall()
    ]


def audit_direct_graph(conn: Any, target_ids: list[int]) -> dict[str, Any]:
    if len(target_ids) != len(set(target_ids)) or any(value <= 0 for value in target_ids):
        raise ValueError("Target loan IDs must be unique positive integers")
    edges = direct_loan_edges(conn)
    findings: list[dict[str, Any]] = []
    blockers: list[str] = []
    for table, constraint, column, width in edges:
        if width != 1:
            blockers.append(f"composite_loan_foreign_key:{table}.{constraint}")
            continue
        count = 0
        if target_ids:
            query = sql.SQL("SELECT COUNT(*) FROM {} WHERE {} = ANY(%s)").format(
                sql.Identifier(table), sql.Identifier(column),
            )
            count = int(conn.execute(query, (target_ids,)).fetchone()[0])
        classification = (
            "loan-owned" if table in LOAN_OWNED_V1 else
            "review-required" if table in REVIEW_REQUIRED_V1 else "unknown"
        )
        findings.append({
            "table": table, "constraint": constraint, "loan_fk_column": column,
            "row_count": count, "classification": classification,
        })
        if count and classification != "loan-owned":
            blockers.append(f"unproved_loan_edge:{table}.{column}")
    encoded = json.dumps(findings, sort_keys=True, separators=(",", ":")).encode()
    return {
        "report_kind": "carry-forward-direct-loan-graph-v1",
        "target_eligible_loan_count": len(target_ids),
        "edge_catalog_hash": hashlib.sha256(encoded).hexdigest(),
        "edges": findings,
        "blockers": sorted(set(blockers)),
        "direct_graph_clear": not blockers,
        "ready_for_seed": False,
        "missing_proofs": ["transitive_foreign_keys", "application_level_references",
                           "row_checksums", "staged_restore"],
    }


def nonretained_loan_edges(
    conn: Any, target_ids: list[int], *, rebuild_mobile_metadata: bool = False,
) -> dict[int, set[str]]:
    """Identify loans with rows that cannot be copied by the v1 loan allowlist."""
    affected: dict[int, set[str]] = {}
    if not target_ids:
        return affected
    for table, constraint, column, width in direct_loan_edges(conn):
        if table in LOAN_OWNED_V1 or (rebuild_mobile_metadata and table in MOBILE_METADATA_REBUILT_V1):
            continue
        if width != 1:
            raise ValueError(f"Composite loan foreign key requires review: {table}.{constraint}")
        query = sql.SQL("SELECT DISTINCT {} FROM {} WHERE {} = ANY(%s)").format(
            sql.Identifier(column), sql.Identifier(table), sql.Identifier(column),
        )
        for (loan_id,) in conn.execute(query, (target_ids,)).fetchall():
            affected.setdefault(int(loan_id), set()).add(
                ("review_edge:" if table in KNOWN_REVIEW_EDGES_V1 else "unproved_edge:")
                + table
            )
    return affected


def audit_retention_related_rows(conn: Any, target_ids: list[int]) -> dict[str, Any]:
    """Count the refinance and mobile links that a larger seed must resolve."""
    if len(target_ids) != len(set(target_ids)) or any(value <= 0 for value in target_ids):
        raise ValueError("Target loan IDs must be unique positive integers")
    if not target_ids:
        return {"loan_count": 0, "ready_for_seed": False}
    transfer = conn.execute("""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE from_loan_account_id = ANY(%s)
                                  AND to_loan_account_id = ANY(%s)),
               COUNT(*) FILTER (WHERE from_savings_account_id IS NOT NULL
                                  OR to_savings_account_id IS NOT NULL)
        FROM m_account_transfer_details
        WHERE from_loan_account_id = ANY(%s) OR to_loan_account_id = ANY(%s)
    """, (target_ids,) * 4).fetchone()
    topup = conn.execute("""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE loan_id = ANY(%s) AND closure_loan_id = ANY(%s)),
               COUNT(*) FILTER (WHERE account_transfer_details_id IS NULL)
        FROM m_loan_topup
        WHERE loan_id = ANY(%s) OR closure_loan_id = ANY(%s)
    """, (target_ids,) * 4).fetchone()
    settlement = conn.execute("""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE t.loan_id = ANY(%s)
                                  AND s.closure_loan_id = ANY(%s)),
               COUNT(*) FILTER (WHERE s.account_transfer_details_id IS NULL
                                  OR transfer.id IS NULL),
               COUNT(*) FILTER (WHERE s.repayment_transaction_id IS NULL
                                  OR repayment.id IS NULL),
               COUNT(*) FILTER (WHERE repayment.loan_id <> s.closure_loan_id)
               ,COUNT(*) FILTER (WHERE transfer.from_loan_account_id <> t.loan_id
                                    OR transfer.to_loan_account_id <> s.closure_loan_id)
               ,COUNT(*) FILTER (WHERE s.settlement_amount <> repayment.amount
                                    OR s.settlement_amount <> s.principal_portion
                                       + s.interest_portion + s.fee_charges_portion
                                       + s.penalty_charges_portion)
        FROM m_loan_refinancing_settlement s
        JOIN m_loan_topup t ON t.id=s.refinancing_id
        LEFT JOIN m_account_transfer_details transfer ON transfer.id=s.account_transfer_details_id
        LEFT JOIN m_loan_transaction repayment ON repayment.id=s.repayment_transaction_id
        WHERE t.loan_id = ANY(%s) OR s.closure_loan_id = ANY(%s)
    """, (target_ids,) * 4).fetchone()
    header = conn.execute("""
        SELECT COUNT(*) FILTER (WHERE t.account_transfer_details_id IS NULL
                                  AND t.operation_type='CONSOLIDATION'
                                  AND settlement_count>=2
                                  AND linked_transfers=settlement_count
                                  AND linked_repayments=settlement_count),
               COUNT(*) FILTER (WHERE t.account_transfer_details_id IS NULL
                                  AND NOT (t.operation_type='CONSOLIDATION'
                                  AND settlement_count>=2
                                  AND linked_transfers=settlement_count
                                  AND linked_repayments=settlement_count))
               ,COUNT(*) FILTER (WHERE t.account_transfer_details_id IS NOT NULL
                                   AND (header_transfer.from_loan_account_id <> t.loan_id
                                        OR header_transfer.to_loan_account_id <> t.closure_loan_id))
        FROM m_loan_topup t
        LEFT JOIN m_account_transfer_details header_transfer
          ON header_transfer.id=t.account_transfer_details_id
        CROSS JOIN LATERAL (
            SELECT COUNT(*) AS settlement_count,
                   COUNT(*) FILTER (WHERE s.account_transfer_details_id IS NOT NULL
                                     AND transfer.id IS NOT NULL) AS linked_transfers,
                   COUNT(*) FILTER (WHERE s.repayment_transaction_id IS NOT NULL
                                     AND repayment.id IS NOT NULL) AS linked_repayments
            FROM m_loan_refinancing_settlement s
            LEFT JOIN m_account_transfer_details transfer ON transfer.id=s.account_transfer_details_id
            LEFT JOIN m_loan_transaction repayment ON repayment.id=s.repayment_transaction_id
            WHERE s.refinancing_id=t.id
        ) detail
        WHERE t.loan_id = ANY(%s) OR t.closure_loan_id = ANY(%s)
    """, (target_ids,) * 2).fetchone()
    mobile = conn.execute("""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE i.loan_transaction_id IS NOT NULL),
               COUNT(*) FILTER (WHERE i.loan_transaction_id IS NOT NULL
                                  AND tx.loan_id=i.loan_id)
        FROM credesal_mobile_collection_item i
        LEFT JOIN m_loan_transaction tx ON tx.id=i.loan_transaction_id
        WHERE i.loan_id = ANY(%s)
    """, (target_ids,)).fetchone()
    return {
        "loan_count": len(target_ids),
        "transfer_rows": int(transfer[0]),
        "transfers_with_both_loans_in_set": int(transfer[1]),
        "transfers_with_savings_side": int(transfer[2]),
        "topup_rows": int(topup[0]),
        "topups_with_both_loans_in_set": int(topup[1]),
        "topups_without_header_transfer_link": int(topup[2]),
        "valid_consolidation_headers_without_transfer_link": int(header[0]),
        "invalid_topups_without_transfer_link": int(header[1]),
        "topups_with_wrong_transfer_loans": int(header[2]),
        "settlement_rows": int(settlement[0]),
        "settlements_with_both_loans_in_set": int(settlement[1]),
        "settlements_missing_transfer": int(settlement[2]),
        "settlements_missing_repayment": int(settlement[3]),
        "settlements_with_wrong_repayment_loan": int(settlement[4]),
        "settlements_with_wrong_transfer_loans": int(settlement[5]),
        "settlements_with_amount_mismatch": int(settlement[6]),
        "mobile_item_rows": int(mobile[0]),
        "mobile_items_with_transaction": int(mobile[1]),
        "mobile_items_with_matching_loan_transaction": int(mobile[2]),
        "ready_for_seed": False,
    }


def inspect_graph(state_path: Path, target: TargetConfig,
                  source_through_date: str) -> dict[str, Any]:
    report, target_ids = verify_local_candidates_with_ids(
        state_path, target, source_through_date,
    )
    if report["target_verified_candidates"] != len(target_ids):
        raise RuntimeError("Target candidate count differs from verified ID set")
    with postgres_connection(target.pg_url) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        graph = audit_direct_graph(conn, target_ids)
    return {
        "arissto_through": report["arissto_through"],
        "fineract_starts": report["fineract_starts"],
        "target_rejections": report["target_rejections"],
        **graph,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--target", choices=("local",), required=True)
    parser.add_argument("--source-through-date", required=True)
    args = parser.parse_args()
    report = inspect_graph(args.state_file, load_settings(args.target).target,
                           args.source_through_date)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["direct_graph_clear"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
