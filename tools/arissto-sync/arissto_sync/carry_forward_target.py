"""Read-only local sandbox preflight for a future carry-forward seed.

Passing this target-side check is necessary but does not authorize seed capture,
cutoff reinitialization, tenant restore, or a workflow run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from urllib.parse import urlparse
from typing import Any

from .config import TargetConfig, load_settings
from .connections import postgres_connection

REQUIRED_TABLES = (
    "acc_accounting_cutoff_configuration", "m_loan", "m_loan_transaction",
    "acc_gl_journal_entry",
)
EMPTY_DOMAIN_TABLES = (
    "acc_gl_journal_entry", "acc_gl_journal_entry_annual_summary",
    "credesal_arissto_gl_journal", "credesal_arissto_gl_journal_line",
    "m_journal_entry_aggregation_summary", "m_journal_entry_aggregation_tracking",
    "m_trial_balance", "m_savings_account", "m_share_account",
    "m_invoice", "m_invoice_issuer", "m_invoice_receiver", "m_invoice_line",
    "m_invoice_related_document", "m_invoice_summary",
    "credesal_mobile_collection_item",
)
CLOSED_STATUSES = frozenset((600, 601, 602, 700))
LOCAL_HOSTS = frozenset(("localhost", "127.0.0.1", "::1"))


def cutoff_hash(cutoff_date: date, state: str, revision: int) -> str:
    canonical = f"{cutoff_date.isoformat()}|America/El_Salvador|{state}|{revision}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_target(
    target: TargetConfig, cutoff: tuple[Any, ...] | None,
    loan_status_counts: dict[int, int], non_arissto_loans: int,
    late_transactions: int, table_counts: dict[str, int | None],
) -> dict[str, Any]:
    blockers: list[str] = []
    pg = urlparse(target.pg_url or "")
    api_host = urlparse(target.api_url or "").hostname
    if (target.name != "local" or target.tenant != "sandbox"
            or pg.hostname not in LOCAL_HOSTS or pg.path != "/fineract_sandbox"
            or api_host not in LOCAL_HOSTS):
        blockers.append("not_local_sandbox")
    missing = [name for name in REQUIRED_TABLES if table_counts.get(name) is None]
    blockers.extend(f"required_table_missing:{name}" for name in missing)
    if cutoff is None:
        blockers.append("cutoff_missing")
    else:
        cutoff_date, lifecycle_state, revision = cutoff[:3]
        if str(lifecycle_state).upper() != "ACTIVE":
            blockers.append("cutoff_not_active")
        if not isinstance(cutoff_date, date):
            blockers.append("cutoff_date_invalid")
        if len(cutoff) < 4 or not isinstance(revision, int) or not isinstance(cutoff_date, date) or (
            str(cutoff[3]) != cutoff_hash(cutoff_date, str(lifecycle_state), revision)
        ):
            blockers.append("cutoff_hash_invalid")
    for status, count in loan_status_counts.items():
        if status not in CLOSED_STATUSES and count:
            blockers.append("nonclosed_loans_present")
            break
    if non_arissto_loans:
        blockers.append("non_arissto_loans_present")
    if late_transactions:
        blockers.append("loan_transactions_on_or_after_seed_cutoff")
    for table, count in table_counts.items():
        if table in EMPTY_DOMAIN_TABLES and count:
            blockers.append(f"nonempty_domain:{table}")
    return {
        "report_kind": "read-only-target-preflight",
        "target": target.name,
        "tenant": target.tenant,
        "seed_cutoff": cutoff[0].isoformat() if cutoff and isinstance(cutoff[0], date) else None,
        "cutoff_state": str(cutoff[1]) if cutoff else None,
        "loan_status_counts": {str(key): value for key, value in sorted(loan_status_counts.items())},
        "non_arissto_loans": non_arissto_loans,
        "late_loan_transactions": late_transactions,
        "nonempty_excluded_domains": {name: count for name, count in table_counts.items()
                                      if name in EMPTY_DOMAIN_TABLES and count},
        "blockers": sorted(set(blockers)),
        "target_preconditions_pass": not blockers,
        "ready_for_reset": False,
    }


def inspect_target(target: TargetConfig) -> dict[str, Any]:
    if target.name != "local" or target.tenant != "sandbox":
        raise ValueError("Carry-forward target inspection is restricted to local sandbox")
    if not target.pg_url:
        raise ValueError("Local sandbox PostgreSQL URL is required")
    if (urlparse(target.pg_url).hostname not in LOCAL_HOSTS
            or urlparse(target.pg_url).path != "/fineract_sandbox"
            or urlparse(target.api_url).hostname not in LOCAL_HOSTS):
        raise ValueError("Carry-forward target inspection requires local sandbox PostgreSQL and API")
    with postgres_connection(target.pg_url) as conn:
        present = {str(name) for (name,) in conn.execute("""
            SELECT tablename FROM pg_catalog.pg_tables
            WHERE schemaname = 'public' AND tablename = ANY(%s)
        """, (list(set(REQUIRED_TABLES) | set(EMPTY_DOMAIN_TABLES)),)).fetchall()}
        table_counts: dict[str, int | None] = {}
        for name in set(REQUIRED_TABLES) | set(EMPTY_DOMAIN_TABLES):
            table_counts[name] = int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]) if name in present else None
        cutoff = conn.execute("""
            SELECT cutoff_date,lifecycle_state,configuration_revision,configuration_hash
            FROM acc_accounting_cutoff_configuration WHERE id=1
        """).fetchone() if "acc_accounting_cutoff_configuration" in present else None
        loan_status_counts = dict(conn.execute(
            "SELECT loan_status_id,COUNT(*) FROM m_loan GROUP BY loan_status_id"
        ).fetchall()) if "m_loan" in present else {}
        non_arissto = int(conn.execute("""
            SELECT COUNT(*) FROM m_loan
            WHERE external_id IS NULL OR external_id NOT LIKE 'ARISSTO:CRD:%'
        """).fetchone()[0]) if "m_loan" in present else 0
        late_transactions = int(conn.execute("""
            SELECT COUNT(*) FROM m_loan_transaction
            WHERE transaction_date >= %s
        """, (cutoff[0],)).fetchone()[0]) if cutoff and "m_loan_transaction" in present else 0
    return classify_target(target, cutoff, loan_status_counts, non_arissto, late_transactions, table_counts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local",), required=True)
    args = parser.parse_args()
    report = inspect_target(load_settings(args.target).target)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["target_preconditions_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
