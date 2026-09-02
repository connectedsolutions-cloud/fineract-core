from __future__ import annotations

import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

from .arissto import select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import FineractApi, postgres_connection
from .fixed_deposit_lifecycle_proof import (
    DpfCanary,
    DpfInterest,
    _account_status,
    _command_key,
    _find_rollover,
    _general_interest_reference,
    _general_tax_reference,
    _post_interest_and_transfer,
    fetch_dpf_canary,
)
from .savings import BLOCK, SavingsContract, inspect_savings
from .savings_lifecycle_proof import VistaCanary, VistaEvent, fetch_vista_canary
from .state import State


SOURCE_SYSTEM = "arissto"
ACCOUNT_EXTERNAL_PREFIX = "arissto:savings:"
PRODUCT_NAME_PREFIX = "Arissto Credesal"
PRODUCT_NUMBERING_CODES = {
    "00001": "4V1",
    "00003": "5D1",
    "00004": "5D2",
    "00005": "5D3",
    "00008": "5D6",
    "00009": "5D7",
    "00010": "5D8",
    "00011": "5D9",
}
SUPPORTED_VISTA_NATIVE_ROLES = {
    "DEPOSIT": ("deposit", 1),
    "WITHDRAWAL": ("withdrawal", 2),
    "SAVINGS_INTEREST_POSTING": ("explicitInterestPosting", 3),
    "WITHHOLDING_TAX": ("explicitWithholdTax", 18),
}
DPF_MANAGED_VISTA_ROLES = {"FIXED_DEPOSIT_INTEREST_TRANSFER", "FIXED_DEPOSIT_WITHHOLDING_TAX"}
REVERSAL_ROLES = {"CREDIT_REVERSAL", "DEBIT_REVERSAL"}


@contextmanager
def _postgres_write_connection(url: str):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - dependency is part of the runtime image
        raise RuntimeError("psycopg is required for savings migration provenance writes") from exc
    with psycopg.connect(url, autocommit=False) as conn:
        yield conn


def _stable_hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, default=_json_default, separators=(",", ":")).encode()).hexdigest()


def _resource_id(result: dict[str, Any], *fields: str) -> int:
    for field in (*fields, "resourceId", "entityId"):
        if result.get(field) is not None:
            return int(result[field])
    raise RuntimeError(f"Fineract response is missing a resource identifier: {result}")


def _transaction_id(result: dict[str, Any]) -> int | None:
    # Savings transaction commands in this Fineract build return the native
    # transaction identifier as resourceId (and the account as savingsId).
    value = result.get("subResourceId") or result.get("transactionId") or result.get("resourceId")
    return int(value) if value is not None else None


def _lifecycle_payload(field: str, value: date) -> dict[str, Any]:
    return {field: value.isoformat(), "dateFormat": "yyyy-MM-dd", "locale": "en"}


def _set_migration_interest_start(api: FineractApi, endpoint: str, account_id: int, cutoff_date: date) -> None:
    api.request(
        "POST", f"{endpoint}/{account_id}",
        _lifecycle_payload("startInterestCalculationDate", cutoff_date),
        {"command": "migrationInterestStart"},
        idempotency_key=_command_key("migration-interest-start-v1", endpoint, account_id, cutoff_date),
    )


def account_external_id(source_key: str) -> str:
    return f"{ACCOUNT_EXTERNAL_PREFIX}{compact_account_key_from_canonical(source_key)}"


def compact_account_key_from_canonical(source_key: str) -> str:
    parts = source_key.split("|")
    if len(parts) != 4 or any(not part for part in parts[1:]):
        raise ValueError(f"Invalid canonical savings source key: {source_key}")
    return ":".join(parts[1:])


def _product_source_key(canary: VistaCanary | DpfCanary) -> str:
    return f"AHO_LINEA_AHORRO|{canary.company_id}|{canary.line_id}"


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(type(value).__name__)


def savings_source_hash(value: VistaCanary | DpfCanary) -> str:
    payload = json.dumps(asdict(value), sort_keys=True, separators=(",", ":"), default=_json_default)
    return sha256(payload.encode("utf-8")).hexdigest()


def canonical_account_key(contract: SavingsContract, compact_key: str) -> str:
    company, branch, account = (part.strip() for part in compact_key.split(":"))
    table = contract.raw["source"]["account_table"]
    return f"{table}|{company}|{branch}|{account}"


def compact_account_key(contract: SavingsContract, canonical_key: str) -> str:
    return ":".join(contract.parse_account_source_key(canonical_key))


def _source_accounts(settings: Settings, contract: SavingsContract,
                     source_keys: list[str] | None) -> list[tuple[str, str]]:
    source = contract.raw["source"]
    wanted = set(source_keys or [])
    with source_connection(settings.source) as conn:
        rows = select_rows(conn, f"""
            SELECT RTRIM(a.ID_EMPRESA) company_id,RTRIM(a.ID_SUCURSAL) branch_id,
                   RTRIM(a.ID_CUENTA_AHORRO) account_id,RTRIM(l.ID_TIPO_CUENTA_AHORRO) account_type
            FROM dbo.{source['account_table']} a
            JOIN dbo.{source['product_table']} l
              ON l.ID_EMPRESA=a.ID_EMPRESA AND l.ID_LINEA_AHORRO=a.ID_LINEA_AHORRO
            ORDER BY a.ID_EMPRESA,a.ID_SUCURSAL,a.ID_CUENTA_AHORRO
        """)
    values: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        compact = f"{str(row['company_id']).strip()}:{str(row['branch_id']).strip()}:{str(row['account_id']).strip()}"
        canonical = canonical_account_key(contract, compact)
        account_type = str(row["account_type"]).strip()
        disposition = contract.account_type(account_type)["disposition"]
        if disposition != "migrate":
            continue
        if wanted and canonical not in wanted:
            continue
        values.append((canonical, account_type))
        seen.add(canonical)
    missing = sorted(wanted - seen)
    if missing:
        raise ValueError(f"Unknown or non-migratable savings source keys: {missing}")
    return values


def extract_savings_accounts(settings: Settings, contract: SavingsContract,
                             source_keys: list[str] | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for canonical, account_type in _source_accounts(settings, contract, source_keys):
        compact = compact_account_key(contract, canonical)
        try:
            value: VistaCanary | DpfCanary
            value = fetch_vista_canary(settings, contract, compact) if account_type == "001" else fetch_dpf_canary(
                settings, contract, compact
            )
            cutoff_date = (_vista_support_snapshot(settings, value)["cutoff_date"]
                           if isinstance(value, VistaCanary) else value.cutoff_date)
            record = {
                "source_key": canonical,
                "compact_key": compact,
                "account_type": account_type,
                "deposit_type": "VISTA" if account_type == "001" else "DPF",
                "source_hash": savings_source_hash(value),
                "client_external_id": value.client_external_id,
                "line_id": value.line_id,
                "source_state": "ACTIVE" if account_type == "001" else value.state,
                "linked_vista_source_key": (
                    canonical_account_key(contract, value.linked_vista_key) if isinstance(value, DpfCanary) else None
                ),
                "event_count": (
                    len(value.events) if isinstance(value, VistaCanary) else
                    len(value.interests) + sum(int(interest.taxed) for interest in value.interests)
                    + int(bool(value.opening_movement_id)) + len(value.reversed_opening_events)
                    + int(bool(value.cancellation_movement_id))
                ),
                "cycle_count": 1 if isinstance(value, VistaCanary) else len(value.cycles),
                "owner_count": 1 if isinstance(value, VistaCanary) else len(value.owners),
                "cutoff_date": cutoff_date,
                "payload": value,
            }
            if isinstance(value, DpfCanary) and value.state == "SUBMITTED_UNFUNDED" and value.principal <= 0:
                # Fineract correctly requires a positive fixed-deposit amount.
                # These Arissto placeholders have no funding or financial
                # events, so creating an artificial native position would be
                # misleading. Preserve the reviewed exclusion in the plan.
                record["quarantine_reason"] = "submitted_unfunded_zero_principal"
            records.append(record)
        except Exception as exc:
            records.append({
                "source_key": canonical, "compact_key": compact, "account_type": account_type,
                "deposit_type": "VISTA" if account_type == "001" else "DPF",
                "source_hash": sha256(f"{canonical}:{type(exc).__name__}:{exc}".encode()).hexdigest(),
                "quarantine_reason": f"{type(exc).__name__}:{exc}",
            })
    return records


def _target_context(settings: Settings, records: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.target.pg_url:
        raise RuntimeError("Savings planning requires target PostgreSQL inspection")
    external_ids = sorted({str(row["client_external_id"]) for row in records if row.get("client_external_id")})
    source_keys = sorted(row["source_key"] for row in records)
    with postgres_connection(settings.target.pg_url) as conn:
        clients = conn.execute(
            "SELECT external_id,id,status_enum FROM m_client WHERE external_id=ANY(%s)", (external_ids,)
        ).fetchall()
        migration = conn.execute("""
            SELECT id,source_key,source_hash,contract_hash,savings_account_id,migration_status,plan_id
            FROM credesal_savings_migration_account
            WHERE source_system='arissto' AND source_key=ANY(%s)
        """, (source_keys,)).fetchall()
        account_ids = [int(row[4]) for row in migration if row[4] is not None]
        native = conn.execute(
            "SELECT id,external_id,status_enum,account_balance_derived,start_interest_calculation_date "
            "FROM m_savings_account WHERE id=ANY(%s)", (account_ids,)
        ).fetchall() if account_ids else []
        migration_ids = [int(row[0]) for row in migration]
        event_counts = conn.execute("""
            SELECT migration_account_id,COUNT(*) FROM (
                SELECT e.id,e.migration_account_id
                FROM credesal_savings_native_event_map e
                WHERE e.migration_account_id=ANY(%s)
                  AND e.event_status IN ('APPLIED','SKIPPED_REVERSAL')
                UNION ALL
                SELECT e.id,c.migration_account_id
                FROM credesal_savings_native_event_map e
                JOIN credesal_savings_migration_cycle c ON c.id=e.migration_cycle_id
                WHERE c.migration_account_id=ANY(%s)
                  AND e.migration_account_id<>c.migration_account_id
                  AND e.event_kind IN ('WITHHOLD_TAX','WITHHOLDING_TAX')
                  AND e.event_status='APPLIED'
                UNION ALL
                SELECT e.id,a.id
                FROM credesal_savings_migration_account a
                JOIN credesal_savings_native_event_map e
                  ON e.savings_account_id=a.savings_account_id
                WHERE a.id=ANY(%s) AND a.deposit_type='VISTA'
                  AND e.migration_account_id<>a.id
                  AND e.event_kind IN (
                    'FIXED_DEPOSIT_INTEREST_TRANSFER','WITHHOLD_TAX','WITHHOLDING_TAX'
                  )
                  AND e.event_status='APPLIED'
            ) mapped_events GROUP BY migration_account_id
        """, (migration_ids, migration_ids, migration_ids)).fetchall() if migration_ids else []
        event_count_by_migration = {int(row[0]): int(row[1]) for row in event_counts}
        reversed_event_counts = conn.execute("""
            SELECT e.migration_account_id,COUNT(*)
            FROM credesal_savings_native_event_map e
            JOIN m_savings_account_transaction st ON st.id=e.savings_transaction_id
            WHERE e.migration_account_id=ANY(%s) AND e.event_status='APPLIED' AND st.is_reversed=true
            GROUP BY e.migration_account_id
        """, (migration_ids,)).fetchall() if migration_ids else []
        reversed_event_count_by_migration = {int(row[0]): int(row[1]) for row in reversed_event_counts}
        unmapped_interest_counts = conn.execute("""
            SELECT a.id,COUNT(*)
            FROM credesal_savings_migration_account a
            JOIN credesal_savings_migration_cycle c ON c.migration_account_id=a.id
            JOIN m_savings_account_transaction st ON st.savings_account_id=c.savings_account_id
            LEFT JOIN credesal_savings_native_event_map e ON e.savings_transaction_id=st.id
            WHERE a.id=ANY(%s) AND a.deposit_type='DPF'
              AND st.transaction_type_enum=3 AND st.is_reversed=false AND e.id IS NULL
            GROUP BY a.id
        """, (migration_ids,)).fetchall() if migration_ids else []
        unmapped_interest_count_by_migration = {int(row[0]): int(row[1]) for row in unmapped_interest_counts}
    return {
        "clients": {str(row[0]): {"id": int(row[1]), "status": int(row[2])} for row in clients},
        "migration": {str(row[1]): {"source_hash": str(row[2]), "contract_hash": str(row[3]),
                                      "target_id": int(row[4]), "status": str(row[5]),
                                      "plan_id": str(row[6]),
                                      "event_count": event_count_by_migration.get(int(row[0]), 0),
                                      "reversed_event_count": reversed_event_count_by_migration.get(int(row[0]), 0),
                                      "unmapped_interest_count": unmapped_interest_count_by_migration.get(int(row[0]), 0)}
                      for row in migration},
        "native": {int(row[0]): {"external_id": str(row[1]), "status": int(row[2]),
                                  "balance": Decimal(str(row[3])) if row[3] is not None else None,
                                  "interest_start": row[4]} for row in native},
    }


def _planning_drift_reasons(record: dict[str, Any], existing: dict[str, Any],
                            native: dict[str, Any], contract_hash: str) -> list[str]:
    reasons: list[str] = []
    if existing["contract_hash"] != contract_hash:
        reasons.append("contract_hash_mismatch")
    if existing.get("reversed_event_count", 0):
        reasons.append("mapped_native_transaction_reversed")
    if existing.get("unmapped_interest_count", 0):
        reasons.append("unmapped_native_interest")
    payload = record.get("payload")
    expected_cutoff = record.get("cutoff_date")
    if expected_cutoff is None and isinstance(payload, DpfCanary):
        expected_cutoff = payload.cutoff_date
    if expected_cutoff is not None and native.get("interest_start") != expected_cutoff:
        reasons.append("migration_interest_start_mismatch")
    if isinstance(payload, VistaCanary) and native["balance"] != payload.ending_balance:
        reasons.append("native_balance_mismatch")
    return reasons


REPAIRABLE_DRIFT_REASONS = {
    "contract_hash_mismatch",
    "mapped_native_transaction_reversed",
    "unmapped_native_interest",
    "native_balance_mismatch",
    "migration_interest_start_mismatch",
}


def _can_repair_existing_drift(record: dict[str, Any], existing: dict[str, Any],
                               drift_reasons: list[str]) -> bool:
    """Limit repair mode to unchanged source facts and known native drift."""
    return (
        bool(drift_reasons)
        and existing["source_hash"] == record["source_hash"]
        and set(drift_reasons).issubset(REPAIRABLE_DRIFT_REASONS)
    )


def build_savings_plan(settings: Settings, state: State, contract: SavingsContract,
                       source_keys: list[str] | None = None,
                       repair_existing_drift: bool = False) -> tuple[str, dict[str, Any]]:
    if repair_existing_drift and settings.target.name != "local":
        raise RuntimeError("Savings drift repair plans are restricted to the local target")
    inspection = inspect_savings(settings, contract)
    non_engine_blockers = [
        item for item in inspection["blockers"]
        if item != "implementation_gate:deterministic_plan_apply_reconcile_and_full_population"
    ]
    records = extract_savings_accounts(settings, contract, source_keys)
    target = _target_context(settings, records)
    by_key = {row["source_key"]: row for row in records}
    actions: list[dict[str, Any]] = []
    counts = Counter()
    blocker_counts = Counter()
    for record in records:
        key = record["source_key"]
        reason = record.get("quarantine_reason")
        drift_reasons: list[str] = []
        client = target["clients"].get(record.get("client_external_id"))
        existing = target["migration"].get(key)
        # Controlled proof rows deliberately retain the canonical source key,
        # but their native accounts use proof identities. They are evidence,
        # not a production migration mapping, and are replaced by the first
        # general apply rather than classified as a business update.
        if existing and existing["plan_id"] == "dpf-lifecycle-proof":
            existing = None
        action = "create"
        if reason:
            action = "quarantine"
        elif client is None:
            action, reason = "quarantine", "client_dependency_missing"
        elif client["status"] != 300:
            action, reason = "quarantine", "client_dependency_inactive"
        elif record["deposit_type"] == "DPF" and record["linked_vista_source_key"] not in by_key:
            action, reason = "quarantine", "linked_vista_not_in_plan_scope"
        elif existing:
            native = target["native"].get(existing["target_id"])
            if native is None:
                action, reason = "quarantine", "mapped_native_account_missing"
            elif drift_reasons := _planning_drift_reasons(record, existing, native, contract.contract_hash):
                if repair_existing_drift and _can_repair_existing_drift(record, existing, drift_reasons):
                    action, reason = "repair", "reviewed_existing_drift"
                else:
                    action, reason = "blocked", drift_reasons[0]
                    if existing["source_hash"] != record["source_hash"]:
                        drift_reasons = ["source_hash_mismatch", *drift_reasons]
                    blocker_counts.update(drift_reasons)
            elif (existing["source_hash"] == record["source_hash"]
                  and existing["status"] == "RECONCILED"
                  and existing["event_count"] == record.get("event_count", 0)):
                action = "unchanged"
            else:
                action = "update"
        counts[action] += 1
        actions.append({
            "source_key": key, "source_hash": record["source_hash"], "action": action,
            "reason": reason, "reasons": drift_reasons, "target_id": existing["target_id"] if existing else None,
            "client_id": client["id"] if client else None,
            "deposit_type": record["deposit_type"], "line_id": record.get("line_id"),
            "source_state": record.get("source_state"),
            "linked_vista_source_key": record.get("linked_vista_source_key"),
            "event_count": record.get("event_count", 0), "cycle_count": record.get("cycle_count", 0),
            "owner_count": record.get("owner_count", 0),
        })
    actions.sort(key=lambda row: (row["deposit_type"] != "VISTA", row["source_key"]))
    writable_keys = {
        item["source_key"] for item in actions if item["action"] in {"create", "update", "repair"}
    }
    product_contracts = _planned_product_contracts(
        settings, contract, [record for record in records if record["source_key"] in writable_keys]
    )
    document = {
        # Reviewed quarantines are deterministic per-record outcomes, not a
        # reason to prevent the rest of an otherwise ready population from
        # applying. The writer records them in the run and never writes them.
        "block": BLOCK, "applicable": not non_engine_blockers and counts["blocked"] == 0,
        "contract_hash": contract.contract_hash, "schema_signature": inspection["schema_signature"],
        "source_fingerprint": source_fingerprint(settings.source),
        "scope": source_keys or "all", "counts": dict(counts), "actions": actions,
        "repair_existing_drift": repair_existing_drift,
        "product_contracts": product_contracts,
        "readiness_blockers": non_engine_blockers + (["target_state_drift"] if counts["blocked"] else []),
        "blocker_counts": dict(blocker_counts),
        "quarantine_count": counts["quarantine"],
    }
    plan_id = state.save_plan(
        settings.target.fingerprint, BLOCK, source_fingerprint(settings.source), contract.contract_hash, document
    )
    return plan_id, document


def _resolve_gl_ids(conn: Any, contract: SavingsContract, canary: VistaCanary | DpfCanary) -> dict[str, int]:
    wanted = {role: item["gl_code"] for role, item in contract.raw["target_shared_gl"].items()}
    wanted.update(canary.source_gl_codes)
    rows = conn.execute(
        "SELECT id,gl_code,classification_enum,disabled FROM acc_gl_account WHERE gl_code=ANY(%s)",
        (sorted(set(wanted.values())),),
    ).fetchall()
    by_code = {
        str(row[1]): {"id": int(row[0]), "classification": int(row[2]), "disabled": bool(row[3])}
        for row in rows
    }
    if set(by_code) != set(wanted.values()):
        raise RuntimeError(f"Savings GL mapping is incomplete for line {canary.line_id}")
    if any(value["disabled"] for value in by_code.values()):
        raise RuntimeError(f"Savings GL mapping contains a disabled account for line {canary.line_id}")
    return {role: by_code[code]["id"] for role, code in wanted.items()}


def _vista_product_payload(canary: VistaCanary, gl: dict[str, int], default_rate: Decimal) -> dict[str, Any]:
    numbering_code = PRODUCT_NUMBERING_CODES.get(canary.line_id)
    if numbering_code is None:
        raise RuntimeError(f"Savings line {canary.line_id} has no approved numbering code")
    return {
        "name": f"{PRODUCT_NAME_PREFIX} VISTA {canary.line_id}",
        "shortName": f"AV{canary.line_id[-2:]}",
        "numberingCode": numbering_code,
        "description": f"Arissto VISTA line {canary.line_id} migrated under the reviewed Credesal contract",
        "currencyCode": "USD", "digitsAfterDecimal": 2, "inMultiplesOf": 0,
        "nominalAnnualInterestRate": format(default_rate, "f"),
        "interestCompoundingPeriodType": 5, "interestPostingPeriodType": 5,
        "interestCalculationType": 1, "interestCalculationDaysInYearType": 1,
        "minRequiredOpeningBalance": "50.00", "minBalanceForInterestCalculation": "50.00",
        "lockinPeriodFrequency": 0, "lockinPeriodFrequencyType": 0,
        "withdrawalFeeForTransfers": False, "allowOverdraft": False,
        "withHoldTax": False, "taxGroupId": 2, "accountingRule": 3,
        "savingsReferenceAccountId": gl["savingsReferenceAccountId"],
        "overdraftPortfolioControlId": gl["savingsReferenceAccountId"],
        "savingsControlAccountId": gl["savingsControlAccountId"],
        "transfersInSuspenseAccountId": gl["transfersInSuspenseAccountId"],
        "interestOnSavingsAccountId": gl["interestOnSavingsAccountId"],
        "writeOffAccountId": gl["interestOnSavingsAccountId"],
        "interestPayableAccountId": gl["interestPayableAccountId"],
        "incomeFromFeeAccountId": gl["incomeFromFeeAccountId"],
        "incomeFromPenaltyAccountId": gl["incomeFromPenaltyAccountId"],
        "incomeFromInterestId": gl["incomeFromFeeAccountId"],
        "feesReceivableAccountId": gl["feesReceivableAccountId"],
        "penaltiesReceivableAccountId": gl["penaltiesReceivableAccountId"],
        "locale": "en", "paymentChannelToFundSourceMappings": [],
        "feeToIncomeAccountMappings": [], "penaltyToIncomeAccountMappings": [], "charges": [],
    }


def _dpf_product_payload(canary: DpfCanary, gl: dict[str, int], term_min: int, term_max: int,
                         default_rate: Decimal, capitalization_period: str) -> dict[str, Any]:
    if capitalization_period not in {"04", "06"}:
        raise RuntimeError(f"Unsupported DPF capitalization period {capitalization_period}")
    period_enum = 9 if capitalization_period == "06" else 7
    numbering_code = PRODUCT_NUMBERING_CODES.get(canary.line_id)
    if numbering_code is None:
        raise RuntimeError(f"Savings line {canary.line_id} has no approved numbering code")
    return {
        "name": f"{PRODUCT_NAME_PREFIX} DPF {canary.line_id}",
        "shortName": f"AD{canary.line_id[-2:]}",
        "numberingCode": numbering_code,
        "description": f"Arissto fixed-deposit line {canary.line_id} migrated under the reviewed Credesal contract",
        "currencyCode": "USD", "digitsAfterDecimal": 2, "inMultiplesOf": 0,
        "nominalAnnualInterestRate": format(default_rate, "f"),
        "interestCompoundingPeriodType": period_enum, "interestPostingPeriodType": period_enum,
        "interestCalculationType": 1, "interestCalculationDaysInYearType": 1,
        "lockinPeriodFrequency": 0, "lockinPeriodFrequencyType": 0,
        "minDepositTerm": term_min, "minDepositTermTypeId": 0,
        "maxDepositTerm": term_max, "maxDepositTermTypeId": 0,
        "inMultiplesOfDepositTerm": 1, "inMultiplesOfDepositTermTypeId": 0,
        "minDepositAmount": "0.01", "depositAmount": format(canary.principal, "f"),
        "maxDepositAmount": "10000000.00", "preClosurePenalApplicable": False,
        "withHoldTax": False, "taxGroupId": 2, "accountingRule": 3,
        "charts": [{
            "fromDate": "2000-01-01", "dateFormat": "yyyy-MM-dd", "locale": "en",
            "isPrimaryGroupingByAmount": False,
            "chartSlabs": [{"description": "Migrated account-level rate", "periodType": 0,
                            "fromPeriod": 1, "annualInterestRate": format(default_rate, "f"), "locale": "en"}],
        }],
        "savingsReferenceAccountId": gl["savingsReferenceAccountId"],
        "savingsControlAccountId": gl["savingsControlAccountId"],
        "transfersInSuspenseAccountId": gl["transfersInSuspenseAccountId"],
        "interestOnSavingsAccountId": gl["interestOnSavingsAccountId"],
        "interestPayableAccountId": gl["interestPayableAccountId"],
        "incomeFromFeeAccountId": gl["incomeFromFeeAccountId"],
        "incomeFromPenaltyAccountId": gl["incomeFromPenaltyAccountId"],
        "feesReceivableAccountId": gl["feesReceivableAccountId"],
        "penaltiesReceivableAccountId": gl["penaltiesReceivableAccountId"],
        "locale": "en",
    }


def _ensure_product_numbering_code(settings: Settings, api: FineractApi, endpoint: str,
                                   product_id: int, expected: str) -> None:
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute(
            "SELECT numbering_code FROM m_savings_product WHERE id=%s", (product_id,),
        ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"Savings product {product_id} is missing or duplicated")
    observed = rows[0][0]
    if observed not in (None, "", expected):
        raise RuntimeError(f"Savings product {product_id} numbering code drifted")
    if observed in (None, ""):
        api.request("PUT", f"{endpoint}/{product_id}", {"numberingCode": expected, "locale": "en"})


def _source_product_contract(settings: Settings, canary: VistaCanary | DpfCanary) -> dict[str, Any]:
    with source_connection(settings.source) as conn:
        rows = select_rows(conn, """
            SELECT RTRIM(l.ID_TIPO_CUENTA_AHORRO) account_type,l.PORCENTAJE_INTERES default_rate,
                   l.PLAZO_INI minimum_term,l.PLAZO_FIN maximum_term,
                   RTRIM(l.PERIODO_CAPITALIZACION) capitalization_period
            FROM dbo.AHO_LINEA_AHORRO l
            WHERE RTRIM(l.ID_EMPRESA)=? AND RTRIM(l.ID_LINEA_AHORRO)=?
            GROUP BY l.ID_TIPO_CUENTA_AHORRO,l.PORCENTAJE_INTERES,l.PLAZO_INI,l.PLAZO_FIN,l.PERIODO_CAPITALIZACION
        """, (canary.company_id, canary.line_id))
    if len(rows) != 1:
        raise RuntimeError(f"Source savings line contract is not unique: {canary.company_id}:{canary.line_id}")
    row = rows[0]
    return {
        "account_type": str(row["account_type"]).strip(),
        "default_rate": Decimal(str(row["default_rate"])),
        "minimum_term": int(row["minimum_term"]) if row["minimum_term"] is not None else None,
        "maximum_term": int(row["maximum_term"]) if row["maximum_term"] is not None else None,
        "capitalization_period": str(row["capitalization_period"]).strip(),
    }


def _product_contract_snapshot(settings: Settings, contract: SavingsContract,
                               canary: VistaCanary | DpfCanary) -> dict[str, Any]:
    line_contract = _source_product_contract(settings, canary)
    expected_type = "001" if isinstance(canary, VistaCanary) else "003"
    if line_contract["account_type"] != expected_type:
        raise RuntimeError(
            f"Source savings line type changed for {canary.company_id}:{canary.line_id}: "
            f"{line_contract['account_type']}"
        )
    with postgres_connection(settings.target.pg_url or "") as conn:
        gl = _resolve_gl_ids(conn, contract, canary)
    serializable_contract = {
        "account_type": line_contract["account_type"],
        "default_rate": format(line_contract["default_rate"], "f"),
        "minimum_term": line_contract["minimum_term"],
        "maximum_term": line_contract["maximum_term"],
        "capitalization_period": line_contract["capitalization_period"],
    }
    snapshot = {"line": _product_source_key(canary), "contract": serializable_contract, "gl": gl}
    return {**snapshot, "source_hash": _stable_hash(snapshot)}


def _planned_product_contracts(settings: Settings, contract: SavingsContract,
                               records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    representatives: dict[str, VistaCanary | DpfCanary] = {}
    for record in records:
        canary = record.get("payload")
        if canary is not None:
            representatives.setdefault(_product_source_key(canary), canary)
    return [
        _product_contract_snapshot(settings, contract, representatives[key])
        for key in sorted(representatives)
    ]


def _ensure_products(settings: Settings, contract: SavingsContract,
                     records: list[dict[str, Any]],
                     planned_contracts: list[dict[str, Any]],
                     allow_contract_upgrade: bool = False) -> dict[str, int]:
    if not settings.target.pg_url:
        raise RuntimeError("Savings product mapping requires target PostgreSQL")
    canaries = [row["payload"] for row in records if row.get("payload") is not None]
    grouped: dict[str, list[VistaCanary | DpfCanary]] = {}
    for canary in canaries:
        grouped.setdefault(_product_source_key(canary), []).append(canary)
    api = FineractApi(settings.target)
    product_ids: dict[str, int] = {}
    frozen = {item["line"]: item for item in planned_contracts}
    expected = {key: frozen[key] for key in grouped if key in frozen}
    if set(expected) != set(grouped):
        raise RuntimeError("Savings product scope changed after planning")
    for source_key, values in sorted(grouped.items()):
        representative = values[0]
        snapshot = _product_contract_snapshot(settings, contract, representative)
        if snapshot != expected[source_key]:
            raise RuntimeError(f"Savings product contract changed after planning: {source_key}")
        line_contract = snapshot["contract"]
        with postgres_connection(settings.target.pg_url) as conn:
            mapped = conn.execute(
                "SELECT savings_product_id,source_hash,contract_hash FROM credesal_savings_product_map "
                "WHERE source_system=%s AND source_key=%s", (SOURCE_SYSTEM, source_key),
            ).fetchone()
        gl = snapshot["gl"]
        product_hash = snapshot["source_hash"]
        if isinstance(representative, VistaCanary):
            product_payload = _vista_product_payload(
                representative, gl, Decimal(line_contract["default_rate"])
            )
            product_endpoint = "savingsproducts"
        else:
            term_min = line_contract["minimum_term"] or min(
                item.term_days for item in values if isinstance(item, DpfCanary)
            )
            term_max = line_contract["maximum_term"] or max(
                item.term_days for item in values if isinstance(item, DpfCanary)
            )
            product_payload = _dpf_product_payload(
                representative, gl, term_min, term_max, Decimal(line_contract["default_rate"]),
                line_contract["capitalization_period"],
            )
            product_endpoint = "fixeddepositproducts"
        if mapped:
            if str(mapped[2]) != contract.contract_hash:
                if not allow_contract_upgrade or str(mapped[1]) != product_hash:
                    raise RuntimeError(f"Mapped savings product contract drifted for {source_key}")
                # Repair mode may advance metadata only when the frozen source
                # product snapshot is byte-for-byte unchanged. It never mutates
                # a native product under a new contract assumption.
                with _postgres_write_connection(settings.target.pg_url) as conn:
                    conn.execute("""
                        UPDATE credesal_savings_product_map
                        SET contract_hash=%s,updated_at=CURRENT_TIMESTAMP
                        WHERE source_system=%s AND source_key=%s AND source_hash=%s
                    """, (contract.contract_hash, SOURCE_SYSTEM, source_key, product_hash))
                    conn.commit()
            product_id = int(mapped[0])
            if str(mapped[1]) != product_hash:
                # Upgrade a product created by an earlier version of this
                # still-unreleased writer from scope-dependent observed values
                # to the stable source-line contract. Foreign/manual products
                # cannot enter this branch because the durable crosswalk and
                # contract hash are required.
                if product_endpoint == "fixeddepositproducts":
                    # Fineract appends fixed-deposit charts on update and then
                    # rejects their overlap with the existing open-ended chart.
                    # Create one deterministic replacement for pre-general
                    # products and move only the durable line crosswalk.
                    replacement_payload = dict(product_payload)
                    replacement_payload["name"] = f"{product_payload['name']} {product_hash[:8]}"
                    replacement_payload["shortName"] = f"D{representative.line_id[-2:]}{product_hash[0]}"
                    with postgres_connection(settings.target.pg_url) as conn:
                        replacements = conn.execute(
                            "SELECT id FROM m_savings_product WHERE name=%s",
                            (replacement_payload["name"],),
                        ).fetchall()
                    if len(replacements) > 1:
                        raise RuntimeError(f"Duplicate replacement savings product for {source_key}")
                    product_id = (
                        int(replacements[0][0]) if replacements
                        else _resource_id(api.request("POST", product_endpoint, replacement_payload))
                    )
                else:
                    api.request("PUT", f"{product_endpoint}/{product_id}", product_payload)
                with _postgres_write_connection(settings.target.pg_url) as conn:
                    conn.execute("""
                        UPDATE credesal_savings_product_map
                        SET source_hash=%s,savings_product_id=%s,mapping_status='ACTIVE',updated_at=CURRENT_TIMESTAMP
                        WHERE source_system=%s AND source_key=%s AND contract_hash=%s
                    """, (product_hash, product_id, SOURCE_SYSTEM, source_key, contract.contract_hash))
                    conn.commit()
            _ensure_product_numbering_code(
                settings, api, product_endpoint, product_id, product_payload["numberingCode"]
            )
            product_ids[source_key] = product_id
            continue
        name = (f"{PRODUCT_NAME_PREFIX} VISTA {representative.line_id}" if isinstance(representative, VistaCanary)
                else f"{PRODUCT_NAME_PREFIX} DPF {representative.line_id}")
        with postgres_connection(settings.target.pg_url) as conn:
            matches = conn.execute("SELECT id FROM m_savings_product WHERE name=%s", (name,)).fetchall()
        if len(matches) > 1:
            raise RuntimeError(f"Duplicate native savings product identity for {source_key}")
        if matches:
            product_id = int(matches[0][0])
        else:
            product_id = _resource_id(api.request("POST", product_endpoint, product_payload))
        _ensure_product_numbering_code(
            settings, api, product_endpoint, product_id, product_payload["numberingCode"]
        )
        company_id, line_id = source_key.split("|")[1:]
        with _postgres_write_connection(settings.target.pg_url) as conn:
            conn.execute("""
                INSERT INTO credesal_savings_product_map
                  (source_system,source_key,source_hash,contract_hash,savings_product_id,
                   arissto_company_id,arissto_line_id,deposit_type,mapping_status,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE',CURRENT_TIMESTAMP)
                ON CONFLICT (source_system,source_key) DO UPDATE SET
                  source_hash=EXCLUDED.source_hash,contract_hash=EXCLUDED.contract_hash,
                  savings_product_id=EXCLUDED.savings_product_id,mapping_status='ACTIVE',updated_at=CURRENT_TIMESTAMP
            """, (SOURCE_SYSTEM, source_key, product_hash, contract.contract_hash, product_id,
                    company_id, line_id, "VISTA" if isinstance(representative, VistaCanary) else "DPF"))
            conn.commit()
        product_ids[source_key] = product_id
    return product_ids


def _vista_support_snapshot(settings: Settings, canary: VistaCanary) -> dict[str, Any]:
    with source_connection(settings.source) as conn:
        rows = select_rows(conn, """
            WITH x AS (SELECT MAX(CAST(FECHA_OPERACION AS date)) cutoff_date
                       FROM dbo.CIERRE_DIARIO WHERE RTRIM(CIERRE)='1')
            SELECT x.cutoff_date,d.INTERESES_PROVISIONADOS,
                   RTRIM(p.ID_PROPIETARIO) owner_id,RTRIM(s.NUMERO_AFILIACION) owner_external_id
            FROM dbo.AHO_CUENTA_AHORRO a CROSS JOIN x
            JOIN dbo.AHO_HISTORICO_DIARIO d ON d.ID_AHORRO=a.ID_AHORRO
            JOIN dbo.CIERRE_DIARIO c ON c.ID_CIERRE_DIARIO=d.ID_CIERRE_DIARIO
             AND CAST(c.FECHA_OPERACION AS date)=x.cutoff_date
            JOIN dbo.AHO_PROPIETARIOS p ON p.ID_EMPRESA=a.ID_EMPRESA AND p.ID_SUCURSAL=a.ID_SUCURSAL
             AND p.ID_CUENTA_AHORRO=a.ID_CUENTA_AHORRO
            JOIN dbo.AFI_SOCIO s ON s.ID_EMPRESA=p.ID_EMPRESA
             AND s.ID_SUCURSAL=p.ID_SUCURSAL_SOCIO AND s.ID_SOCIO=p.ID_SOCIO
            WHERE RTRIM(a.ID_EMPRESA)=? AND RTRIM(a.ID_SUCURSAL)=? AND RTRIM(a.ID_CUENTA_AHORRO)=?
            ORDER BY p.ID_PROPIETARIO
        """, (canary.company_id, canary.branch_id, canary.account_id))
    if len(rows) != 1 or str(rows[0]["owner_external_id"]).strip() != canary.client_external_id:
        raise RuntimeError(f"VISTA ownership/cutoff support is not unique for {canary.source_key}")
    return {
        "cutoff_date": rows[0]["cutoff_date"],
        "cutoff_accrual": Decimal(str(rows[0]["INTERESES_PROVISIONADOS"])),
        "owner_id": str(rows[0]["owner_id"]).strip(),
    }


def _upsert_migration_account(conn: Any, contract: SavingsContract, plan_id: str, run_id: str,
                              source_key: str, source_hash: str, client_id: int, account_id: int,
                              canary: VistaCanary | DpfCanary, *, status: str = "APPLIED",
                              vista_support: dict[str, Any] | None = None) -> int:
    company, branch, account = source_key.split("|")[1:]
    if isinstance(canary, VistaCanary):
        if vista_support is None:
            raise RuntimeError("VISTA migration support snapshot is required")
        support = vista_support
        source_status, linked_key, owner_count = "1", None, 1
        opened_on, matures_on = canary.opening_date, None
    else:
        support = {"cutoff_date": canary.cutoff_date, "cutoff_accrual": canary.cutoff_accrual}
        source_status, linked_key, owner_count = canary.source_status, canonical_account_key(
            contract, canary.linked_vista_key
        ), len(canary.owners)
        opened_on = canary.cycles[0]["source_opened_on"]
        matures_on = canary.cycles[-1]["source_matures_on"]
    row = conn.execute("""
        INSERT INTO credesal_savings_migration_account
          (source_system,source_key,source_hash,contract_hash,plan_id,run_id,client_id,savings_account_id,
           deposit_type,arissto_company_id,arissto_branch_id,arissto_account_id,arissto_account_number,
           arissto_line_id,source_status,capitalization_destination_source_key,source_owner_count,
           source_opened_on,source_matures_on,cutoff_date,accrued_interest_exact,accrued_interest_accounting,
           migration_status,applied_at,updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
        ON CONFLICT (source_system,source_key) DO UPDATE SET
          source_hash=EXCLUDED.source_hash,contract_hash=EXCLUDED.contract_hash,plan_id=EXCLUDED.plan_id,
          run_id=EXCLUDED.run_id,client_id=EXCLUDED.client_id,savings_account_id=EXCLUDED.savings_account_id,
          source_status=EXCLUDED.source_status,
          capitalization_destination_source_key=EXCLUDED.capitalization_destination_source_key,
          source_owner_count=EXCLUDED.source_owner_count,source_opened_on=EXCLUDED.source_opened_on,
          source_matures_on=EXCLUDED.source_matures_on,cutoff_date=EXCLUDED.cutoff_date,
          accrued_interest_exact=EXCLUDED.accrued_interest_exact,
          accrued_interest_accounting=EXCLUDED.accrued_interest_accounting,
          migration_status=EXCLUDED.migration_status,error_code=NULL,applied_at=CURRENT_TIMESTAMP,
          reconciled_at=NULL,updated_at=CURRENT_TIMESTAMP
        RETURNING id
    """, (SOURCE_SYSTEM, source_key, source_hash, contract.contract_hash, plan_id, run_id, client_id, account_id,
            "VISTA" if isinstance(canary, VistaCanary) else "DPF", company, branch, account, account,
            canary.line_id, source_status, linked_key, owner_count, opened_on, matures_on,
            support["cutoff_date"], support["cutoff_accrual"],
            support["cutoff_accrual"].quantize(Decimal("0.01")), status)).fetchone()
    if row is None:
        raise RuntimeError(f"Unable to persist savings migration identity for {source_key}")
    return int(row[0])


def _upsert_owner(conn: Any, migration_account_id: int, client_id: int, canary: VistaCanary | DpfCanary,
                  owner_id: str, owner_external_id: str, is_native: bool) -> None:
    source_key = (f"AHO_PROPIETARIOS|{canary.company_id}|{canary.branch_id}|"
                  f"{canary.account_id}|{owner_id}")
    conn.execute("""
        INSERT INTO credesal_savings_migration_owner
          (migration_account_id,client_id,source_system,source_key,source_hash,arissto_owner_id,
           is_native_owner,updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
        ON CONFLICT (source_system,source_key) DO UPDATE SET
          migration_account_id=EXCLUDED.migration_account_id,client_id=EXCLUDED.client_id,
          source_hash=EXCLUDED.source_hash,is_native_owner=EXCLUDED.is_native_owner,updated_at=CURRENT_TIMESTAMP
    """, (migration_account_id, client_id, SOURCE_SYSTEM, source_key,
            _stable_hash({"external_id": owner_external_id, "native": is_native}), owner_id, is_native))


def _upsert_event(conn: Any, contract: SavingsContract, plan_id: str, run_id: str, migration_account_id: int,
                  account_id: int, source_table: str, source_key: str, source_value: Any, event_kind: str,
                  event_status: str, event_date: date, amount: Decimal, transaction_id: int | None,
                  *, cycle_id: int | None = None, related_source_key: str | None = None,
                  is_reversal: bool = False) -> None:
    conn.execute("""
        INSERT INTO credesal_savings_native_event_map
          (migration_account_id,migration_cycle_id,source_system,source_table,source_key,related_source_key,
           source_hash,contract_hash,plan_id,run_id,savings_account_id,savings_transaction_id,event_kind,
           event_status,event_date,amount,is_reversal,applied_at,updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
        ON CONFLICT (source_system,source_table,source_key) DO UPDATE SET
          migration_account_id=EXCLUDED.migration_account_id,migration_cycle_id=EXCLUDED.migration_cycle_id,
          related_source_key=EXCLUDED.related_source_key,source_hash=EXCLUDED.source_hash,
          contract_hash=EXCLUDED.contract_hash,plan_id=EXCLUDED.plan_id,run_id=EXCLUDED.run_id,
          savings_account_id=EXCLUDED.savings_account_id,
          savings_transaction_id=EXCLUDED.savings_transaction_id,event_kind=EXCLUDED.event_kind,
          event_status=EXCLUDED.event_status,event_date=EXCLUDED.event_date,amount=EXCLUDED.amount,
          is_reversal=EXCLUDED.is_reversal,error_code=NULL,applied_at=CURRENT_TIMESTAMP,
          reconciled_at=NULL,updated_at=CURRENT_TIMESTAMP
    """, (migration_account_id, cycle_id, SOURCE_SYSTEM, source_table, source_key, related_source_key,
            _stable_hash(source_value), contract.contract_hash, plan_id, run_id, account_id, transaction_id,
            event_kind, event_status, event_date, amount, is_reversal))


def _event_map(conn: Any, source_table: str, source_key: str) -> tuple[int | None, str, int] | None:
    row = conn.execute(
        "SELECT e.savings_transaction_id,e.event_status,e.savings_account_id,st.is_reversed "
        "FROM credesal_savings_native_event_map e "
        "LEFT JOIN m_savings_account_transaction st ON st.id=e.savings_transaction_id "
        "WHERE e.source_system=%s AND e.source_table=%s AND e.source_key=%s",
        (SOURCE_SYSTEM, source_table, source_key),
    ).fetchone()
    if row is None:
        return None
    transaction_id = int(row[0]) if row[0] is not None else None
    status = str(row[1])
    if status == "APPLIED" and (transaction_id is None or row[3] is None or bool(row[3])):
        status = "STALE_NATIVE_TRANSACTION"
    return transaction_id, status, int(row[2])


def _supersede_dpf_business_alias(conn: Any, business_id: str | None, movement_id: str | None,
                                  event_kind: str, related_source_key: str) -> None:
    """Preserve and deactivate rows written by the pre-general writer's business-ID key bug."""
    if not business_id or not movement_id or business_id == movement_id:
        return
    conn.execute("""
        UPDATE credesal_savings_native_event_map
        SET source_table='LEGACY_DPF_BUSINESS_ALIAS',event_status='SUPERSEDED',
            savings_transaction_id=NULL,updated_at=CURRENT_TIMESTAMP
        WHERE source_system=%s AND source_table='AHO_MOVIMIENTOS' AND source_key=%s
          AND event_kind IN (%s,'WITHHOLD_TAX') AND related_source_key=%s
    """, (SOURCE_SYSTEM, f"AHO_MOVIMIENTOS|{business_id}", event_kind, related_source_key))


def _recover_account(settings: Settings, external_id: str) -> tuple[int, int] | None:
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute(
            "SELECT id,status_enum FROM m_savings_account WHERE external_id=%s", (external_id,)
        ).fetchall()
    if len(rows) > 1:
        raise RuntimeError(f"Duplicate native savings external ID: {external_id}")
    return (int(rows[0][0]), int(rows[0][1])) if rows else None


def _matching_transactions(settings: Settings, account_id: int, transaction_type: int, event_date: date,
                           amount: Decimal, reference: str | None,
                           expected_running_balance: Decimal | None = None,
                           excluded_transaction_ids: set[int] | None = None) -> list[int]:
    clauses = [
        "savings_account_id=%s", "transaction_type_enum=%s", "transaction_date=%s", "amount=%s",
        "is_reversed=false",
    ]
    params: list[Any] = [account_id, transaction_type, event_date, amount]
    if reference is not None:
        clauses.append("ref_no=%s")
        params.append(reference)
    if expected_running_balance is not None:
        clauses.append("running_balance_derived=%s")
        params.append(expected_running_balance)
    if excluded_transaction_ids:
        clauses.append("id<>ALL(%s)")
        params.append(sorted(excluded_transaction_ids))
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute(
            f"SELECT id FROM m_savings_account_transaction WHERE {' AND '.join(clauses)} ORDER BY id", tuple(params)
        ).fetchall()
    return [int(row[0]) for row in rows]


def _resolve_transaction(settings: Settings, account_id: int, transaction_type: int, event_date: date,
                         amount: Decimal, reference: str | None, response: dict[str, Any] | None = None,
                         expected_running_balance: Decimal | None = None,
                         excluded_transaction_ids: set[int] | None = None) -> int:
    returned = _transaction_id(response or {})
    if returned is not None:
        clauses = [
            "id=%s", "savings_account_id=%s", "transaction_type_enum=%s",
            "transaction_date=%s", "amount=%s", "is_reversed=false",
        ]
        params: list[Any] = [returned, account_id, transaction_type, event_date, amount]
        if reference is not None:
            clauses.append("ref_no=%s")
            params.append(reference)
        with postgres_connection(settings.target.pg_url or "") as conn:
            row = conn.execute(
                f"SELECT id FROM m_savings_account_transaction WHERE {' AND '.join(clauses)}",
                tuple(params),
            ).fetchone()
        if row is not None:
            return int(row[0])
    matches = _matching_transactions(
        settings, account_id, transaction_type, event_date, amount, reference, expected_running_balance,
        excluded_transaction_ids,
    )
    if not matches and expected_running_balance is not None:
        # DPF-first replay can legitimately reverse two same-day native
        # operations relative to Arissto while preserving the daily endpoint.
        # Excluding already mapped transaction IDs remains deterministic.
        matches = _matching_transactions(
            settings, account_id, transaction_type, event_date, amount, reference, None,
            excluded_transaction_ids,
        )
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one native transaction account={account_id} type={transaction_type} "
            f"date={event_date} amount={amount}; found {len(matches)}"
        )
    return matches[0]


def _reverse_unmapped_vista_interest_tax(settings: Settings, api: FineractApi, account_id: int) -> list[int]:
    """Undo native accrual artifacts that have no Arissto provenance.

    Posting backdated savings transactions makes Fineract recalculate interest.
    The source-authoritative replay posts Arissto's retained interest and tax as
    explicit native transactions, so any remaining active type 3/18 transaction
    without an event-map row is a generated duplicate, not business history.
    """
    reversed_ids: list[int] = []
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute("""
            SELECT st.id
            FROM m_savings_account_transaction st
            WHERE st.savings_account_id=%s
              AND st.transaction_type_enum IN (3,18)
              AND st.is_reversed=false
              AND NOT EXISTS (
                SELECT 1 FROM credesal_savings_native_event_map em
                WHERE em.savings_transaction_id=st.id AND em.event_status='APPLIED'
              )
            ORDER BY st.transaction_date DESC,st.id DESC
            LIMIT 10001
        """, (account_id,)).fetchall()
    if len(rows) > 10_000:
        raise RuntimeError(f"More than 10,000 unmapped native interest/tax transactions remain for VISTA {account_id}")
    for row in rows:
        transaction_id = int(row[0])
        api.request(
            "POST", f"savingsaccounts/{account_id}/transactions/{transaction_id}",
            {"sourceAuthoritativeCleanup": True}, {"command": "undo"},
            idempotency_key=_command_key("undo-unmapped-interest-tax-v2", account_id, transaction_id),
        )
        with postgres_connection(settings.target.pg_url or "") as conn:
            reversed_row = conn.execute(
                "SELECT is_reversed FROM m_savings_account_transaction WHERE id=%s AND savings_account_id=%s",
                (transaction_id, account_id),
            ).fetchone()
        if reversed_row is None or not bool(reversed_row[0]):
            raise RuntimeError(
                f"Native unmapped interest/tax transaction {transaction_id} was not reversed for VISTA {account_id}"
            )
        reversed_ids.append(transaction_id)
    if reversed_ids:
        api.request(
            "POST", f"savingsaccounts/{account_id}", {}, {"command": "calculateInterest"},
            idempotency_key=_command_key("calculate-after-source-cleanup-v2", account_id, *reversed_ids),
        )
    return reversed_ids


def _reverse_unmapped_dpf_interest(settings: Settings, api: FineractApi, account_ids: list[int]) -> list[int]:
    """Undo transferred DPF interest that is not backed by Arissto history."""
    reversed_ids: list[int] = []
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute("""
            SELECT st.id,st.savings_account_id
            FROM m_savings_account_transaction st
            WHERE st.savings_account_id=ANY(%s)
              AND st.transaction_type_enum=3 AND st.is_reversed=false
              AND NOT EXISTS (
                SELECT 1 FROM credesal_savings_native_event_map em
                WHERE em.savings_transaction_id=st.id AND em.event_status='APPLIED'
                  AND em.event_kind='DPF_INTEREST_POSTING'
              )
            ORDER BY st.transaction_date DESC,st.id DESC
            LIMIT 10001
        """, (account_ids,)).fetchall()
    if len(rows) > 10_000:
        raise RuntimeError(f"More than 10,000 unmapped native DPF interest transactions remain for accounts {account_ids}")
    for row in rows:
        transaction_id, account_id = int(row[0]), int(row[1])
        api.request(
            "POST", f"fixeddepositaccounts/{account_id}/transactions/{transaction_id}",
            {"sourceAuthoritativeCleanup": True}, {"command": "undo"},
            # v6 bypasses both the pre-fallback failures and the generic-undo
            # recalculation behavior used by earlier repair attempts.
            idempotency_key=_command_key("undo-unmapped-dpf-interest-v6", account_id, transaction_id),
        )
        with postgres_connection(settings.target.pg_url or "") as conn:
            reversed_row = conn.execute("""
                SELECT st.is_reversed,
                       COUNT(att.id) FILTER (WHERE att.is_reversed=false)
                FROM m_savings_account_transaction st
                LEFT JOIN m_account_transfer_transaction att ON att.from_savings_transaction_id=st.id
                WHERE st.id=%s AND st.savings_account_id=%s
                GROUP BY st.is_reversed
            """, (transaction_id, account_id)).fetchone()
        if reversed_row is None or not bool(reversed_row[0]) or int(reversed_row[1]) != 0:
            raise RuntimeError(
                f"Native unmapped DPF interest transaction {transaction_id} was not fully reversed for account {account_id}"
            )
        reversed_ids.append(transaction_id)
    return reversed_ids


def _reverse_unmapped_dpf_transfers(settings: Settings, api: FineractApi, account_ids: list[int],
                                    linked_vista_id: int) -> list[int]:
    """Undo scheduler-created DPF transfers with no source event provenance."""
    reversed_ids: list[int] = []
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute("""
            SELECT att.id,att.from_savings_transaction_id,att.to_savings_transaction_id,
                   atd.from_savings_account_id
            FROM m_account_transfer_transaction att
            JOIN m_account_transfer_details atd ON atd.id=att.account_transfer_details_id
            JOIN m_savings_account_transaction from_tx ON from_tx.id=att.from_savings_transaction_id
            JOIN m_savings_account_transaction to_tx ON to_tx.id=att.to_savings_transaction_id
            WHERE atd.from_savings_account_id=ANY(%s)
              AND atd.to_savings_account_id=%s AND atd.transfer_type=4
              AND att.is_reversed=false AND from_tx.is_reversed=false AND to_tx.is_reversed=false
              AND from_tx.transaction_type_enum=2 AND to_tx.transaction_type_enum=1
              AND NOT EXISTS (
                SELECT 1 FROM credesal_savings_native_event_map em
                WHERE em.savings_transaction_id=to_tx.id AND em.event_status='APPLIED'
              )
            ORDER BY att.id
            LIMIT 10001
        """, (account_ids, linked_vista_id)).fetchall()
    if len(rows) > 10_000:
        raise RuntimeError(f"More than 10,000 unmapped DPF transfers remain for accounts {account_ids}")
    for transfer_id, from_transaction_id, to_transaction_id, from_account_id in rows:
        api.request(
            "POST", f"fixeddepositaccounts/{int(from_account_id)}/transactions/{int(from_transaction_id)}",
            {"sourceAuthoritativeCleanup": True}, {"command": "undo"},
            idempotency_key=_command_key("undo-unmapped-dpf-transfer-v1", int(transfer_id)),
        )
        with postgres_connection(settings.target.pg_url or "") as conn:
            reversed_row = conn.execute("""
                SELECT att.is_reversed,from_tx.is_reversed,to_tx.is_reversed
                FROM m_account_transfer_transaction att
                JOIN m_savings_account_transaction from_tx ON from_tx.id=att.from_savings_transaction_id
                JOIN m_savings_account_transaction to_tx ON to_tx.id=att.to_savings_transaction_id
                WHERE att.id=%s AND att.from_savings_transaction_id=%s AND att.to_savings_transaction_id=%s
            """, (int(transfer_id), int(from_transaction_id), int(to_transaction_id))).fetchone()
        if reversed_row is None or not all(bool(value) for value in reversed_row):
            raise RuntimeError(f"Native unmapped DPF transfer {int(transfer_id)} was not fully reversed")
        reversed_ids.append(int(transfer_id))
    return reversed_ids


def _ensure_vista_account(settings: Settings, api: FineractApi, canary: VistaCanary,
                          client_id: int, product_id: int, source_key: str) -> int:
    external_id = account_external_id(source_key)
    existing = _recover_account(settings, external_id)
    if existing is None:
        account_id = _resource_id(api.request("POST", "savingsaccounts", {
            "clientId": client_id, "productId": product_id, "externalId": external_id,
            "submittedOnDate": canary.opening_date.isoformat(), "dateFormat": "yyyy-MM-dd", "locale": "en",
            "nominalAnnualInterestRate": format(canary.annual_rate, "f"),
            "withdrawalFeeForTransfers": False, "minRequiredOpeningBalance": "0",
        }), "savingsId")
        status = 100
    else:
        account_id, status = existing
    if status == 100:
        api.request("POST", f"savingsaccounts/{account_id}",
                    _lifecycle_payload("approvedOnDate", canary.opening_date), {"command": "approve"})
        status = 200
    if status == 200:
        api.request("POST", f"savingsaccounts/{account_id}",
                    _lifecycle_payload("activatedOnDate", canary.opening_date), {"command": "activate"})
        status = 300
    if status != 300:
        raise RuntimeError(f"VISTA account {account_id} is not active after lifecycle recovery: {status}")
    return account_id


def _vista_reference(canary: VistaCanary, event: VistaEvent) -> str:
    prefix = "VSTT" if event.role == "WITHHOLDING_TAX" else "VSTI"
    return (f"{prefix}:{canary.company_id}:{canary.branch_id}:"
            f"{canary.account_id}:{event.source_business_id}")


def _next_replacement_reference(reference: str, used_references: set[str]) -> str:
    generation = 1
    while f"{reference}:R{generation}" in used_references:
        generation += 1
    return f"{reference}:R{generation}"


def _replacement_reference(settings: Settings, reference: str,
                           mapped: tuple[int | None, str, int] | None) -> str:
    """Use the next deterministic identity when prior references are retained on reversed rows."""
    with postgres_connection(settings.target.pg_url or "") as conn:
        used_references = {
            str(row[0]) for row in conn.execute(
                "SELECT ref_no FROM m_savings_account_transaction "
                "WHERE ref_no=%s OR ref_no LIKE %s",
                (reference, f"{reference}:R%"),
            ).fetchall()
            if row[0] is not None
        }
    if reference not in used_references:
        return reference
    return _next_replacement_reference(reference, used_references)


def _prepare_vista(settings: Settings, contract: SavingsContract, api: FineractApi, plan_id: str, run_id: str,
                   action: dict[str, Any], canary: VistaCanary, product_id: int) -> int:
    source_key, source_hash = action["source_key"], action["source_hash"]
    client_id = int(action["client_id"])
    account_id = _ensure_vista_account(settings, api, canary, client_id, product_id, source_key)
    support = _vista_support_snapshot(settings, canary)
    with _postgres_write_connection(settings.target.pg_url or "") as conn:
        migration_id = _upsert_migration_account(
            conn, contract, plan_id, run_id, source_key, source_hash, client_id, account_id, canary,
            vista_support=support,
        )
        _upsert_owner(conn, migration_id, client_id, canary, support["owner_id"], canary.client_external_id, True)
        conn.commit()
    return account_id


def _apply_vista(settings: Settings, contract: SavingsContract, api: FineractApi, plan_id: str, run_id: str,
                 action: dict[str, Any], canary: VistaCanary, product_id: int) -> int:
    account_id = _prepare_vista(settings, contract, api, plan_id, run_id, action, canary, product_id)
    source_key = action["source_key"]
    with postgres_connection(settings.target.pg_url or "") as conn:
        migration = conn.execute("""
            SELECT id,cutoff_date FROM credesal_savings_migration_account
            WHERE source_system=%s AND source_key=%s
        """, (SOURCE_SYSTEM, source_key)).fetchone()
    if migration is None:
        raise RuntimeError(f"Prepared VISTA migration identity is missing: {source_key}")
    migration_id = int(migration[0])
    migration_cutoff = migration[1]

    # Some retained Arissto movement streams begin after the account already
    # held money. Represent that source snapshot as one native opening deposit
    # so every later withdrawal continues to pass Fineract's balance rules.
    opening_balance = canary.events[0].previous_balance if canary.events else Decimal("0")
    opening_key = source_key
    if opening_balance > 0:
        with postgres_connection(settings.target.pg_url or "") as conn:
            opening_mapped = _event_map(conn, "AHO_CUENTA_AHORRO", opening_key)
        if not opening_mapped or opening_mapped[1] != "APPLIED" or opening_mapped[2] != account_id:
            response = api.request(
                "POST", f"savingsaccounts/{account_id}/transactions",
                {
                    **_lifecycle_payload("transactionDate", canary.opening_date),
                    "transactionAmount": format(opening_balance, "f"), "paymentTypeId": 4,
                },
                {"command": "deposit"},
                idempotency_key=f"sav:{sha256(f'opening|{account_id}|{source_key}'.encode()).hexdigest()[:32]}",
            )
            opening_tx = _resolve_transaction(
                settings, account_id, 1, canary.opening_date, opening_balance, None, response
            )
            with _postgres_write_connection(settings.target.pg_url or "") as conn:
                _upsert_event(
                    conn, contract, plan_id, run_id, migration_id, account_id, "AHO_CUENTA_AHORRO",
                    opening_key, {"opening_balance": opening_balance, "opening_date": canary.opening_date},
                    "MIGRATION_OPENING_BALANCE", "APPLIED", canary.opening_date, opening_balance, opening_tx,
                )
                conn.commit()

    for event in canary.events:
        source_table = "AHO_MOVIMIENTOS"
        with postgres_connection(settings.target.pg_url or "") as conn:
            mapped = _event_map(conn, source_table, event.source_key)
        if mapped and mapped[2] == account_id and mapped[1] in {"APPLIED", "SKIPPED_REVERSAL", "PENDING_DPF"}:
            continue
        if event.reversed or event.role in REVERSAL_ROLES:
            event_status, transaction_id = "SKIPPED_REVERSAL", None
        elif event.role in DPF_MANAGED_VISTA_ROLES:
            event_status, transaction_id = "PENDING_DPF", None
        else:
            if event.role not in SUPPORTED_VISTA_NATIVE_ROLES:
                raise RuntimeError(f"Unsupported VISTA migration event role {event.role}")
            command, transaction_type = SUPPORTED_VISTA_NATIVE_ROLES[event.role]
            payload: dict[str, Any] = {
                **_lifecycle_payload("transactionDate", event.event_date),
                "transactionAmount": format(event.amount, "f"),
            }
            reference = None
            if event.role in {"DEPOSIT", "WITHDRAWAL"}:
                payload["paymentTypeId"] = 4
            else:
                # ref_no is globally collision-checked by the narrow native
                # migration commands. Include the account identity; the full
                # canonical source key remains in the durable event map.
                reference = _replacement_reference(settings, _vista_reference(canary, event), mapped)
                payload["transactionReference"] = reference
                if event.role == "WITHHOLDING_TAX":
                    payload["grossInterestAmount"] = format(event.gross_interest or Decimal("0"), "f")
            with postgres_connection(settings.target.pg_url or "") as conn:
                used_transaction_ids = {
                    int(row[0]) for row in conn.execute(
                        "SELECT savings_transaction_id FROM credesal_savings_native_event_map "
                        "WHERE savings_account_id=%s AND savings_transaction_id IS NOT NULL",
                        (account_id,),
                    ).fetchall()
                }
            existing_matches = _matching_transactions(
                settings, account_id, transaction_type, event.event_date, event.amount, reference,
                event.final_balance, used_transaction_ids,
            )
            if not existing_matches and event.role in {"DEPOSIT", "WITHDRAWAL"}:
                existing_matches = _matching_transactions(
                    settings, account_id, transaction_type, event.event_date, event.amount, reference,
                    None, used_transaction_ids,
                )
            if len(existing_matches) == 1:
                transaction_id = existing_matches[0]
            elif len(existing_matches) > 1:
                raise RuntimeError(
                    f"Ambiguous unmapped native transactions for VISTA event {event.source_key}: "
                    f"{existing_matches}"
                )
            else:
                command_identity = f"v5|{account_id}|{event.source_key}|{reference or ''}"
                response = api.request(
                    "POST", f"savingsaccounts/{account_id}/transactions", payload, {"command": command},
                    # v4 supersedes cached domain failures created before DPF-first
                    # dependency ordering and source-rounding support were final.
                    # A stale mapped transaction uses a new R1 native reference
                    # and must not reuse the cached result of its original API
                    # command.
                    idempotency_key=f"sav:{sha256(command_identity.encode()).hexdigest()[:32]}",
                )
                transaction_id = _resolve_transaction(
                    settings, account_id, transaction_type, event.event_date, event.amount, reference, response,
                    event.final_balance, used_transaction_ids,
                )
            event_status = "APPLIED"
        with _postgres_write_connection(settings.target.pg_url or "") as conn:
            _upsert_event(
                conn, contract, plan_id, run_id, migration_id, account_id, source_table, event.source_key,
                asdict(event), event.role, event_status, event.event_date, event.amount, transaction_id,
                is_reversal=event.reversed or event.role in REVERSAL_ROLES,
            )
            conn.commit()
    _reverse_unmapped_vista_interest_tax(settings, api, account_id)
    _set_migration_interest_start(api, "savingsaccounts", account_id, migration_cutoff)
    return account_id


def _linked_vista_target(settings: Settings, canonical_key: str, client_id: int) -> tuple[int, int]:
    with postgres_connection(settings.target.pg_url or "") as conn:
        row = conn.execute("""
            SELECT ma.id,ma.savings_account_id,sa.client_id,sa.status_enum
            FROM credesal_savings_migration_account ma
            JOIN m_savings_account sa ON sa.id=ma.savings_account_id
            WHERE ma.source_system=%s AND ma.source_key=%s AND ma.deposit_type='VISTA'
        """, (SOURCE_SYSTEM, canonical_key)).fetchone()
    if row is None or int(row[2]) != client_id or int(row[3]) != 300:
        raise RuntimeError(f"DPF linked VISTA is missing, inactive, or belongs to another client: {canonical_key}")
    return int(row[0]), int(row[1])


def _owner_clients(settings: Settings, canary: DpfCanary) -> dict[str, int]:
    external_ids = [str(owner["client_external_id"]) for owner in canary.owners]
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute(
            "SELECT external_id,id,status_enum FROM m_client WHERE external_id=ANY(%s)", (external_ids,)
        ).fetchall()
    result = {str(row[0]): int(row[1]) for row in rows if int(row[2]) == 300}
    if set(result) != set(external_ids):
        raise RuntimeError(f"Not every DPF owner resolves to an active Fineract client: {canary.source_key}")
    return result


def _ensure_dpf_account(settings: Settings, api: FineractApi, canary: DpfCanary, client_id: int,
                        product_id: int, source_key: str, linked_vista_id: int) -> tuple[int, int]:
    external_id = account_external_id(source_key)
    existing = _recover_account(settings, external_id)
    opened_on = canary.cycles[0]["source_opened_on"]
    if not isinstance(opened_on, date):
        opened_on = date.fromisoformat(str(opened_on)[:10])
    if existing is None:
        account_id = _resource_id(api.request("POST", "fixeddepositaccounts", {
            "clientId": client_id, "productId": product_id, "externalId": external_id,
            "submittedOnDate": opened_on.isoformat(), "dateFormat": "yyyy-MM-dd", "locale": "en",
            "depositAmount": format(canary.principal, "f"), "depositPeriod": canary.term_days,
            "depositPeriodFrequencyId": 0, "nominalAnnualInterestRate": format(canary.annual_rate, "f"),
            "interestCalculationDaysInYearType": 1,
            "interestCompoundingPeriodType": 9 if canary.capitalization_period == "06" else 7,
            "interestPostingPeriodType": 9 if canary.capitalization_period == "06" else 7,
            "interestCalculationType": 1, "transferInterestToSavings": False,
            "maturityInstructionId": 400, "preClosurePenalApplicable": False,
            "withHoldTax": False, "charges": [],
        }), "savingsId")
        status = 100
    else:
        account_id, status = existing
    if canary.state == "SUBMITTED_UNFUNDED":
        if status != 100:
            raise RuntimeError(f"Submitted/unfunded DPF has unexpected native status {status}")
        return account_id, status
    if status == 100:
        api.request("POST", f"fixeddepositaccounts/{account_id}",
                    _lifecycle_payload("approvedOnDate", opened_on), {"command": "approve"})
        status = 200
    if status == 200:
        api.request("POST", f"fixeddepositaccounts/{account_id}",
                    _lifecycle_payload("activatedOnDate", opened_on), {"command": "activate"})
        status = 300
    if status == 300:
        api.request(
            "POST", f"fixeddepositaccounts/{account_id}", {"linkedSavingsAccountId": linked_vista_id},
            {"command": "migrationLink"}, idempotency_key=_command_key("migration-link", account_id, linked_vista_id),
        )
    elif status not in {600, 800}:
        raise RuntimeError(f"DPF account {account_id} has unsupported native status {status}")
    return account_id, status


def _upsert_cycle(conn: Any, contract: SavingsContract, plan_id: str, run_id: str, migration_id: int,
                  previous_cycle_id: int | None, cycle: dict[str, Any], account_id: int,
                  status: str = "APPLIED") -> int:
    row = conn.execute("""
        INSERT INTO credesal_savings_migration_cycle
          (migration_account_id,previous_cycle_id,source_system,source_key,source_hash,contract_hash,
           plan_id,run_id,savings_account_id,cycle_sequence,source_boundary_history_id,source_opened_on,
           source_matures_on,opening_inference,cycle_status,is_current_cycle,migration_status,applied_at,updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
        ON CONFLICT (source_system,source_key) DO UPDATE SET
          migration_account_id=EXCLUDED.migration_account_id,previous_cycle_id=EXCLUDED.previous_cycle_id,
          source_hash=EXCLUDED.source_hash,contract_hash=EXCLUDED.contract_hash,plan_id=EXCLUDED.plan_id,
          run_id=EXCLUDED.run_id,savings_account_id=EXCLUDED.savings_account_id,
          cycle_sequence=EXCLUDED.cycle_sequence,source_boundary_history_id=EXCLUDED.source_boundary_history_id,
          source_opened_on=EXCLUDED.source_opened_on,source_matures_on=EXCLUDED.source_matures_on,
          opening_inference=EXCLUDED.opening_inference,cycle_status=EXCLUDED.cycle_status,
          is_current_cycle=EXCLUDED.is_current_cycle,migration_status=EXCLUDED.migration_status,
          error_code=NULL,applied_at=CURRENT_TIMESTAMP,reconciled_at=NULL,updated_at=CURRENT_TIMESTAMP
        RETURNING id
    """, (migration_id, previous_cycle_id, SOURCE_SYSTEM, cycle["source_key"], _stable_hash(cycle),
            contract.contract_hash, plan_id, run_id, account_id, cycle["cycle_sequence"],
            cycle["source_boundary_history_id"], cycle["source_opened_on"], cycle["source_matures_on"],
            cycle["opening_inference"], cycle["cycle_status"], cycle["is_current_cycle"], status)).fetchone()
    if row is None:
        raise RuntimeError("Unable to persist DPF cycle identity")
    return int(row[0])


def _native_transfer(settings: Settings, dpf_id: int, vista_id: int, interest: DpfInterest) -> tuple[int, int]:
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute("""
            SELECT att.from_savings_transaction_id,att.to_savings_transaction_id
            FROM m_account_transfer_transaction att
            JOIN m_account_transfer_details atd ON atd.id=att.account_transfer_details_id
            WHERE atd.from_savings_account_id=%s AND atd.to_savings_account_id=%s AND atd.transfer_type=4
              AND att.transaction_date=%s AND att.amount=%s AND att.is_reversed=false
            ORDER BY att.id
        """, (dpf_id, vista_id, interest.posted_on, interest.amount)).fetchall()
    if len(rows) != 1 or rows[0][0] is None or rows[0][1] is None:
        raise RuntimeError(f"Expected one native DPF interest transfer for history {interest.history_id}")
    return int(rows[0][0]), int(rows[0][1])


def _apply_dpf(settings: Settings, contract: SavingsContract, api: FineractApi, plan_id: str, run_id: str,
               action: dict[str, Any], canary: DpfCanary, product_id: int) -> int:
    source_key, source_hash = action["source_key"], action["source_hash"]
    client_id = int(action["client_id"])
    linked_key = canonical_account_key(contract, canary.linked_vista_key)
    vista_migration_id, linked_vista_id = _linked_vista_target(settings, linked_key, client_id)
    owner_clients = _owner_clients(settings, canary)
    first_id, first_status = _ensure_dpf_account(
        settings, api, canary, client_id, product_id, source_key, linked_vista_id
    )
    with _postgres_write_connection(settings.target.pg_url or "") as conn:
        migration_id = _upsert_migration_account(
            conn, contract, plan_id, run_id, source_key, source_hash, client_id, first_id, canary
        )
        for owner in canary.owners:
            external_id = str(owner["client_external_id"])
            _upsert_owner(conn, migration_id, owner_clients[external_id], canary, str(owner["owner_id"]),
                          external_id, bool(owner["primary_match"]))
        first_cycle_id = _upsert_cycle(conn, contract, plan_id, run_id, migration_id, None,
                                       canary.cycles[0], first_id)
        conn.commit()
    if canary.state == "SUBMITTED_UNFUNDED":
        return first_id

    dpf_ids = [first_id]
    cycle_ids = [first_cycle_id]
    current_id = first_id
    interests_by_cycle = {
        sequence: [item for item in canary.interests if item.cycle_sequence == sequence]
        for sequence in range(1, len(canary.cycles) + 1)
    }
    if canary.opening_movement_id:
        opening_date = canary.cycles[0]["source_opened_on"]
        if not isinstance(opening_date, date):
            opening_date = date.fromisoformat(str(opening_date)[:10])
        tx_id = _resolve_transaction(settings, first_id, 1, opening_date, canary.principal, None)
        with _postgres_write_connection(settings.target.pg_url or "") as conn:
            _upsert_event(
                conn, contract, plan_id, run_id, migration_id, first_id, "AHO_MOVIMIENTOS",
                f"AHO_MOVIMIENTOS|{canary.opening_movement_id}",
                {"movement_id": canary.opening_movement_id, "amount": canary.principal},
                "FIXED_DEPOSIT_FUNDING", "APPLIED", opening_date, canary.principal, tx_id,
                cycle_id=first_cycle_id,
            )
            conn.commit()

    for sequence, cycle in enumerate(canary.cycles, start=1):
        for interest in interests_by_cycle[sequence]:
            interest_key = (f"AHO_HISTORICO_PLAZOS|{canary.company_id}|{canary.branch_id}|"
                            f"{canary.account_id}|{interest.history_id}")
            with postgres_connection(settings.target.pg_url or "") as conn:
                already = _event_map(conn, "AHO_HISTORICO_PLAZOS", interest_key)
            if not already or already[1] != "APPLIED" or already[2] != current_id:
                native_matches = _matching_transactions(
                    settings, current_id, 3, interest.posted_on, interest.amount, None
                )
                if len(native_matches) == 1:
                    interest_tx = native_matches[0]
                else:
                    interest_reference = _replacement_reference(
                        settings, _general_interest_reference(canary, interest), already
                    )
                    _post_interest_and_transfer(
                        settings, api, canary, interest, current_id, linked_vista_id,
                        general_migration=True, reference_override=interest_reference,
                    )
                    interest_tx = _resolve_transaction(
                        settings, current_id, 3, interest.posted_on, interest.amount,
                        interest_reference,
                    )
            elif already[0] is not None:
                # A prior proof/general attempt may have posted this exact
                # transaction under an older reference namespace. The durable
                # event map is the authoritative idempotency identity.
                interest_tx = already[0]
            else:
                raise RuntimeError(f"Applied DPF interest mapping has no native transaction: {interest_key}")
            _, vista_transfer_tx = _native_transfer(settings, current_id, linked_vista_id, interest)
            with _postgres_write_connection(settings.target.pg_url or "") as conn:
                _supersede_dpf_business_alias(
                    conn, interest.interest_business_id, interest.interest_movement_id,
                    "FIXED_DEPOSIT_INTEREST_TRANSFER", interest_key,
                )
                _upsert_event(
                    conn, contract, plan_id, run_id, migration_id, current_id, "AHO_HISTORICO_PLAZOS",
                    interest_key, asdict(interest), "DPF_INTEREST_POSTING", "APPLIED", interest.posted_on,
                    interest.amount, interest_tx, cycle_id=cycle_ids[sequence - 1],
                )
                _upsert_event(
                    conn, contract, plan_id, run_id, vista_migration_id, linked_vista_id, "AHO_MOVIMIENTOS",
                    f"AHO_MOVIMIENTOS|{interest.interest_movement_id}", asdict(interest),
                    "FIXED_DEPOSIT_INTEREST_TRANSFER", "APPLIED", interest.posted_on, interest.amount,
                    vista_transfer_tx, cycle_id=cycle_ids[sequence - 1], related_source_key=interest_key,
                )
                if interest.taxed:
                    tax_key = f"AHO_MOVIMIENTOS|{interest.tax_movement_id}"
                    tax_mapped = _event_map(conn, "AHO_MOVIMIENTOS", tax_key)
                    if tax_mapped and tax_mapped[0] is not None and tax_mapped[1] == "APPLIED" \
                            and tax_mapped[2] == linked_vista_id:
                        tax_tx = tax_mapped[0]
                    else:
                        native_tax_matches = _matching_transactions(
                            settings, linked_vista_id, 18, interest.posted_on, interest.tax_amount, None
                        )
                        if len(native_tax_matches) == 1:
                            tax_tx = native_tax_matches[0]
                        else:
                            tax_reference = _replacement_reference(
                                settings, _general_tax_reference(canary, interest), tax_mapped
                            )
                            tax_response = api.request(
                                "POST", f"savingsaccounts/{linked_vista_id}/transactions",
                                {
                                    **_lifecycle_payload("transactionDate", interest.posted_on),
                                    "transactionAmount": format(interest.tax_amount, "f"),
                                    "grossInterestAmount": format(interest.amount, "f"),
                                    "transactionReference": tax_reference,
                                },
                                {"command": "explicitWithholdTax"},
                                idempotency_key=_command_key("tax-v2", linked_vista_id, tax_reference),
                            )
                            tax_tx = _resolve_transaction(
                                settings, linked_vista_id, 18, interest.posted_on, interest.tax_amount,
                                tax_reference, tax_response,
                            )
                    _supersede_dpf_business_alias(
                        conn, interest.tax_business_id, interest.tax_movement_id,
                        "WITHHOLDING_TAX", interest_key,
                    )
                    _upsert_event(
                        conn, contract, plan_id, run_id, vista_migration_id, linked_vista_id, "AHO_MOVIMIENTOS",
                        tax_key, asdict(interest), "WITHHOLDING_TAX",
                        "APPLIED", interest.posted_on, interest.tax_amount, tax_tx,
                        cycle_id=cycle_ids[sequence - 1], related_source_key=interest_key,
                    )
                conn.commit()
        if sequence < len(canary.cycles):
            next_opening = canary.cycles[sequence]["source_opened_on"]
            if not isinstance(next_opening, date):
                next_opening = date.fromisoformat(str(next_opening)[:10])
            preferred_rollover_id = None
            if _account_status(settings, current_id) != 600:
                maturity_result = api.request(
                    "POST", f"fixeddepositaccounts/{current_id}",
                    {
                        "applyMaturityInstruction": True, "postMaturityInterest": False,
                        "sourceRolloverDate": next_opening.isoformat(), "dateFormat": "yyyy-MM-dd", "locale": "en",
                    },
                    {"command": "processMaturity"},
                    idempotency_key=_command_key("migration-maturity", current_id, source_key, sequence),
                )
                preferred_rollover_id = maturity_result.get("subResourceId")
                if preferred_rollover_id is None and isinstance(maturity_result.get("changes"), dict):
                    preferred_rollover_id = maturity_result["changes"].get("reinvestedDepositId")
            with postgres_connection(settings.target.pg_url or "") as conn:
                occupied_rollovers = {
                    int(row[0]) for row in conn.execute(
                        "SELECT savings_account_id FROM credesal_savings_migration_cycle "
                        "WHERE source_system=%s AND source_key<>%s",
                        (SOURCE_SYSTEM, canary.cycles[sequence]["source_key"]),
                    ).fetchall()
                }
            current_id = _find_rollover(
                settings, current_id, next_opening, set(dpf_ids) | occupied_rollovers,
                int(preferred_rollover_id) if preferred_rollover_id is not None else None,
            )
            dpf_ids.append(current_id)
            with _postgres_write_connection(settings.target.pg_url or "") as conn:
                cycle_ids.append(_upsert_cycle(
                    conn, contract, plan_id, run_id, migration_id, cycle_ids[-1],
                    canary.cycles[sequence], current_id,
                ))
                conn.commit()

    _reverse_unmapped_dpf_transfers(settings, api, dpf_ids, linked_vista_id)
    _reverse_unmapped_dpf_interest(settings, api, dpf_ids)
    _set_migration_interest_start(api, "fixeddepositaccounts", current_id, canary.cutoff_date)
    final_status = _account_status(settings, current_id)
    if canary.state in {"MATURED", "CLOSED"} and final_status not in {600, 800}:
        api.request(
            "POST", f"fixeddepositaccounts/{current_id}",
            {"applyMaturityInstruction": False, "postMaturityInterest": False},
            {"command": "processMaturity"},
            idempotency_key=_command_key("migration-final-maturity", current_id, source_key),
        )
        final_status = _account_status(settings, current_id)
    if canary.state == "CLOSED" and final_status != 600:
        if canary.cancellation_date is None:
            raise RuntimeError("Closed DPF requires a cancellation date")
        api.request(
            "POST", f"fixeddepositaccounts/{current_id}", {
                **_lifecycle_payload("closedOnDate", canary.cancellation_date),
                "onAccountClosureId": 100, "paymentTypeId": 4, "postMaturityInterest": False,
            }, {"command": "close"},
            idempotency_key=_command_key("migration-close", current_id, source_key),
        )
    # Do not invoke calculateInterest at the historical cutoff. On an
    # at-maturity DPF that command can materialize a financial-year-end
    # customer posting even though Arissto has no posted-interest event. The
    # exact cutoff accrual is migration state; future native jobs calculate
    # forward from the fully replayed account after the migration boundary.
    if canary.state == "CLOSED" and canary.cancellation_movement_id and canary.cancellation_date:
        cancellation_tx = _resolve_transaction(
            settings, current_id, 2, canary.cancellation_date, canary.principal, None
        )
        with _postgres_write_connection(settings.target.pg_url or "") as conn:
            _upsert_event(
                conn, contract, plan_id, run_id, migration_id, current_id, "AHO_MOVIMIENTOS",
                f"AHO_MOVIMIENTOS|{canary.cancellation_movement_id}",
                {"movement_id": canary.cancellation_movement_id, "amount": canary.principal},
                "FIXED_DEPOSIT_CANCELLATION", "APPLIED", canary.cancellation_date, canary.principal,
                cancellation_tx, cycle_id=cycle_ids[-1],
            )
            conn.commit()
    for correction in canary.reversed_opening_events:
        with _postgres_write_connection(settings.target.pg_url or "") as conn:
            _upsert_event(
                conn, contract, plan_id, run_id, migration_id, first_id, "AHO_MOVIMIENTOS",
                f"AHO_MOVIMIENTOS|{correction['movement_id']}", correction, "OPENING_CORRECTION",
                "SKIPPED_REVERSAL", correction["event_date"], correction["amount"], None,
                cycle_id=cycle_ids[0], is_reversal=bool(correction["is_reversal"]),
            )
            conn.commit()
    with _postgres_write_connection(settings.target.pg_url or "") as conn:
        conn.execute("""
            UPDATE credesal_savings_migration_account
            SET savings_account_id=%s,migration_status='APPLIED',updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
        """, (current_id, migration_id))
        conn.commit()
    return current_id


def _apply_guard(settings: Settings, state: State, contract: SavingsContract, plan_id: str,
                 production_confirmation: str | None) -> dict[str, Any]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK:
        raise RuntimeError("Plan is not a savings-deposits plan")
    if plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Savings plan belongs to a different target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source):
        raise RuntimeError("Savings plan source fingerprint changed")
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Savings contract changed after planning")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_savings(settings, contract)
    blockers = [
        item for item in inspection["blockers"]
        if item != "implementation_gate:deterministic_plan_apply_reconcile_and_full_population"
    ]
    if blockers:
        raise RuntimeError(f"Savings destination/source readiness changed: {blockers}")
    if inspection["schema_signature"] != plan["document"]["schema_signature"]:
        raise RuntimeError("Savings destination schema changed after planning")
    if not plan["document"].get("applicable"):
        raise RuntimeError("Savings plan is not applicable")
    if plan["document"].get("repair_existing_drift") and settings.target.name != "local":
        raise RuntimeError("Savings drift repair plans cannot be applied outside the local target")
    return plan


def apply_savings_plan(settings: Settings, state: State, contract: SavingsContract, plan_id: str,
                       production_confirmation: str | None = None,
                       source_keys: set[str] | None = None) -> tuple[str, dict[str, int]]:
    plan = _apply_guard(settings, state, contract, plan_id, production_confirmation)
    actions = [
        action for action in plan["document"]["actions"]
        if source_keys is None or action["source_key"] in source_keys
    ]
    records = extract_savings_accounts(settings, contract, [action["source_key"] for action in actions])
    current = {record["source_key"]: record for record in records}
    for action in actions:
        record = current.get(action["source_key"])
        if record is None or record["source_hash"] != action["source_hash"]:
            raise RuntimeError(f"Savings source changed after planning: {action['source_key']}")
        if action["action"] in {"create", "update", "repair"} and record.get("quarantine_reason"):
            raise RuntimeError(f"Savings source became invalid after planning: {action['source_key']}")
    writable_records = [
        current[action["source_key"]]
        for action in actions if action["action"] in {"create", "update", "repair"}
    ]
    planned_contracts = plan["document"].get("product_contracts")
    if not isinstance(planned_contracts, list):
        raise RuntimeError("Savings plan does not freeze product contracts")
    product_ids = (
        _ensure_products(
            settings, contract, writable_records, planned_contracts,
            allow_contract_upgrade=bool(plan["document"].get("repair_existing_drift")),
        )
        if writable_records else {}
    )
    api = FineractApi(settings.target)
    run_id = state.start_run(plan)
    counts = Counter()
    preparation_failures: dict[str, Exception] = {}
    # DPF interest transfers must exist on their linked VISTA accounts before
    # Fineract validates chronologically later VISTA withdrawals. Provision all
    # VISTA identities first, replay DPFs second, and ordinary VISTA events last.
    for action in actions:
        if action["action"] not in {"create", "update", "repair"}:
            continue
        record = current[action["source_key"]]
        canary = record["payload"]
        if not isinstance(canary, VistaCanary):
            continue
        try:
            _prepare_vista(
                settings, contract, api, plan_id, run_id, action, canary,
                product_ids[_product_source_key(canary)],
            )
        except Exception as exc:
            preparation_failures[action["source_key"]] = exc
    ordered_actions = sorted(actions, key=lambda action: (
        0 if action["action"] in {"create", "update", "repair"}
        and isinstance(current[action["source_key"]].get("payload"), DpfCanary) else 1,
        action["source_key"],
    ))
    for action in ordered_actions:
        key = action["source_key"]
        if action["action"] == "quarantine":
            state.record_item(run_id, key, "quarantine", action["source_hash"], "quarantined",
                              action.get("target_id"), action.get("reason"))
            counts["quarantined"] += 1
            continue
        if action["action"] == "unchanged":
            state.record_item(run_id, key, "unchanged", action["source_hash"], "unchanged",
                              action.get("target_id"))
            counts["unchanged"] += 1
            continue
        try:
            record = current[key]
            canary = record["payload"]
            if key in preparation_failures:
                raise preparation_failures[key]
            product_id = product_ids[_product_source_key(canary)]
            if isinstance(canary, VistaCanary):
                target_id = _apply_vista(settings, contract, api, plan_id, run_id, action, canary, product_id)
            elif isinstance(canary, DpfCanary):
                target_id = _apply_dpf(settings, contract, api, plan_id, run_id, action, canary, product_id)
            else:  # pragma: no cover - extractor owns the closed union
                raise RuntimeError("Unknown savings payload type")
            state.save_mapping(settings.target.fingerprint, BLOCK, key, str(target_id), action["source_hash"])
            state.record_item(run_id, key, action["action"], action["source_hash"], "succeeded", str(target_id))
            counts["succeeded"] += 1
        except Exception as exc:
            # Keep enough local, target-specific detail to make failed-only retries
            # actionable. The state database is ignored and never becomes migration
            # documentation; truncation also prevents an API response from bloating it.
            message = " ".join(str(exc).splitlines())[:1000]
            error_code = f"{type(exc).__name__}:{message}"[:1100]
            state.record_item(run_id, key, action["action"], action["source_hash"], "failed",
                              action.get("target_id"), error_code)
            counts["failed"] += 1
    state.finish_run(run_id, "completed" if counts["failed"] == 0 else "completed-with-errors", dict(counts))
    return run_id, dict(counts)


def _unbalanced_journals(conn: Any, account_ids: list[int]) -> int:
    return int(conn.execute("""
        SELECT COUNT(*) FROM (
          SELECT je.transaction_id
          FROM acc_gl_journal_entry je
          JOIN m_savings_account_transaction st ON st.id=je.savings_transaction_id
          WHERE st.savings_account_id=ANY(%s) AND je.reversed=false
          GROUP BY je.transaction_id
          HAVING SUM(CASE WHEN je.type_enum=1 THEN je.amount ELSE -je.amount END)<>0
        ) x
    """, (account_ids,)).fetchone()[0])


def _reconcile_vista(settings: Settings, canary: VistaCanary, migration: dict[str, Any],
                     expected_cutoff: date) -> list[str]:
    mismatches: list[str] = []
    account_id = int(migration["account_id"])
    with postgres_connection(settings.target.pg_url or "") as conn:
        account = conn.execute("""
            SELECT status_enum,account_balance_derived,interest_calculation_days_in_year_type_enum,
                   interest_compounding_period_enum,interest_posting_period_enum,start_interest_calculation_date
            FROM m_savings_account WHERE id=%s
        """, (account_id,)).fetchone()
        event_rows = conn.execute("""
            SELECT source_key,event_status,savings_transaction_id,event_kind,event_date,amount,is_reversal
            FROM credesal_savings_native_event_map
            WHERE source_table='AHO_MOVIMIENTOS' AND (
                migration_account_id=%s OR (
                    savings_account_id=%s
                    AND event_kind IN (
                        'FIXED_DEPOSIT_INTEREST_TRANSFER','WITHHOLD_TAX','WITHHOLDING_TAX'
                    )
                    AND event_status='APPLIED'
                )
            )
        """, (migration["migration_id"], account_id)).fetchall()
        opening_row = conn.execute("""
            SELECT source_key,event_status,savings_transaction_id,event_kind,event_date,amount,is_reversal
            FROM credesal_savings_native_event_map
            WHERE migration_account_id=%s AND source_table='AHO_CUENTA_AHORRO'
              AND event_kind='MIGRATION_OPENING_BALANCE'
        """, (migration["migration_id"],)).fetchone()
        owner_count = int(conn.execute(
            "SELECT COUNT(*) FROM credesal_savings_migration_owner WHERE migration_account_id=%s",
            (migration["migration_id"],),
        ).fetchone()[0])
        unbalanced = _unbalanced_journals(conn, [account_id])
        mapped = {str(row[0]): row for row in event_rows}
        transactions = {}
        transaction_ids = [int(row[2]) for row in event_rows if row[2] is not None]
        if opening_row is not None and opening_row[2] is not None:
            transaction_ids.append(int(opening_row[2]))
        if transaction_ids:
            transactions = {
                int(row[0]): row for row in conn.execute("""
                    SELECT id,transaction_type_enum,transaction_date,amount,running_balance_derived,is_reversed
                    FROM m_savings_account_transaction WHERE id=ANY(%s)
                """, (transaction_ids,)).fetchall()
            }
    if account is None:
        return ["native_account_missing"]
    if int(account[0]) != 300:
        mismatches.append("native_status")
    if Decimal(str(account[1])) != canary.ending_balance:
        mismatches.append("ending_balance")
    if (int(account[2]), int(account[3]), int(account[4])) != (1, 5, 5):
        mismatches.append("interest_configuration")
    if account[5] != expected_cutoff:
        mismatches.append("migration_interest_start")
    if owner_count != 1:
        mismatches.append("owner_count")
    if unbalanced:
        mismatches.append("unbalanced_journals")
    expected_opening = canary.events[0].previous_balance if canary.events else Decimal("0")
    if expected_opening > 0:
        if opening_row is None or str(opening_row[1]) != "APPLIED" or opening_row[2] is None:
            mismatches.append("opening_balance_mapping")
        else:
            opening_transaction = transactions.get(int(opening_row[2]))
            if opening_transaction is None or (
                int(opening_transaction[1]), opening_transaction[2], Decimal(str(opening_transaction[3])),
                bool(opening_transaction[5])
            ) != (1, canary.opening_date, expected_opening, False):
                mismatches.append("opening_balance_transaction")
    type_by_role = {
        "DEPOSIT": 1, "WITHDRAWAL": 2, "SAVINGS_INTEREST_POSTING": 3, "WITHHOLDING_TAX": 18,
        "FIXED_DEPOSIT_INTEREST_TRANSFER": 1, "FIXED_DEPOSIT_WITHHOLDING_TAX": 18,
    }
    source_daily_end: dict[date, Decimal] = {}
    native_daily_balances: dict[date, set[Decimal]] = {}
    native_required_dates: set[date] = set()
    for event in canary.events:
        source_daily_end[event.event_date] = event.final_balance
        row = mapped.get(event.source_key)
        if row is None:
            mismatches.append(f"event_missing:{event.source_key}")
            continue
        should_skip = event.reversed or event.role in REVERSAL_ROLES
        if should_skip:
            if str(row[1]) != "SKIPPED_REVERSAL" or row[2] is not None:
                mismatches.append(f"reversal_mapping:{event.source_key}")
            continue
        native_required_dates.add(event.event_date)
        if str(row[1]) != "APPLIED" or row[2] is None:
            mismatches.append(f"event_not_applied:{event.source_key}")
            continue
        transaction = transactions.get(int(row[2]))
        if transaction is None:
            mismatches.append(f"transaction_missing:{event.source_key}")
            continue
        expected_type = type_by_role.get(event.role)
        actual = (int(transaction[1]), transaction[2], Decimal(str(transaction[3])), bool(transaction[5]))
        expected = (expected_type, event.event_date, event.amount, False)
        if actual != expected:
            mismatches.append(f"transaction_mismatch:{event.source_key}")
        if transaction[4] is None:
            mismatches.append(f"running_balance_missing:{event.source_key}")
        else:
            native_daily_balances.setdefault(event.event_date, set()).add(Decimal(str(transaction[4])))
    for event_date in native_required_dates:
        expected_balance = source_daily_end[event_date]
        if expected_balance not in native_daily_balances.get(event_date, set()):
            mismatches.append(f"daily_running_balance:{event_date.isoformat()}")
    return mismatches


def _reconcile_dpf(settings: Settings, contract: SavingsContract, canary: DpfCanary,
                   migration: dict[str, Any], expected_cutoff: date) -> list[str]:
    mismatches: list[str] = []
    with postgres_connection(settings.target.pg_url or "") as conn:
        cycles = conn.execute("""
            SELECT c.id,c.savings_account_id,c.cycle_sequence,c.is_current_cycle,sa.status_enum,
                   sa.account_balance_derived,sa.interest_calculation_days_in_year_type_enum,
                   sa.interest_compounding_period_enum,sa.interest_posting_period_enum,
                   sa.start_interest_calculation_date
            FROM credesal_savings_migration_cycle c
            JOIN m_savings_account sa ON sa.id=c.savings_account_id
            WHERE c.migration_account_id=%s ORDER BY c.cycle_sequence
        """, (migration["migration_id"],)).fetchall()
        owner_count = int(conn.execute(
            "SELECT COUNT(*) FROM credesal_savings_migration_owner WHERE migration_account_id=%s",
            (migration["migration_id"],),
        ).fetchone()[0])
        event_rows = conn.execute("""
            SELECT source_table,source_key,event_status,savings_transaction_id,event_kind
            FROM credesal_savings_native_event_map e
            WHERE e.migration_account_id=%s OR (
                e.migration_cycle_id IN (
                    SELECT id FROM credesal_savings_migration_cycle WHERE migration_account_id=%s
                )
                AND e.event_kind IN ('WITHHOLD_TAX','WITHHOLDING_TAX')
            )
        """, (migration["migration_id"], migration["migration_id"])).fetchall()
        account_ids = [int(row[1]) for row in cycles]
        unbalanced = _unbalanced_journals(conn, account_ids) if account_ids else 0
        associations = int(conn.execute("""
            SELECT COUNT(*) FROM m_portfolio_account_associations
            WHERE savings_account_id=ANY(%s) AND association_type_enum=1 AND is_active=true
        """, (account_ids,)).fetchone()[0]) if account_ids else 0
        interest_count = int(conn.execute("""
            SELECT COUNT(*) FROM m_savings_account_transaction
            WHERE savings_account_id=ANY(%s) AND transaction_type_enum=3 AND is_reversed=false
        """, (account_ids,)).fetchone()[0]) if account_ids else 0
        transfers = int(conn.execute("""
            SELECT COUNT(*) FROM m_account_transfer_transaction att
            JOIN m_account_transfer_details atd ON atd.id=att.account_transfer_details_id
            WHERE atd.from_savings_account_id=ANY(%s) AND atd.transfer_type=4 AND att.is_reversed=false
        """, (account_ids,)).fetchone()[0]) if account_ids else 0
    if len(cycles) != len(canary.cycles):
        mismatches.append("cycle_count")
    if owner_count != len(canary.owners):
        mismatches.append("owner_count")
    if unbalanced:
        mismatches.append("unbalanced_journals")
    expected_associations = 0 if canary.state == "SUBMITTED_UNFUNDED" else len(cycles)
    if associations != expected_associations:
        mismatches.append("linked_vista_associations")
    if interest_count != len(canary.interests) or transfers != len(canary.interests):
        mismatches.append("interest_replay")
    period = 9 if canary.capitalization_period == "06" else 7
    for row in cycles:
        if (int(row[6]), int(row[7]), int(row[8])) != (1, period, period):
            mismatches.append(f"interest_configuration:cycle:{row[2]}")
    if cycles:
        current = cycles[-1]
        expected_statuses = {
            "SUBMITTED_UNFUNDED": {100}, "ACTIVE": {300}, "MATURED": {800, 600}, "CLOSED": {600},
        }[canary.state]
        if int(current[4]) not in expected_statuses:
            mismatches.append("native_status")
        if int(migration["account_id"]) != int(current[1]):
            mismatches.append("current_cycle_pointer")
        if current[9] != expected_cutoff:
            mismatches.append("migration_interest_start")
    expected_events = len(canary.interests) + sum(int(interest.taxed) for interest in canary.interests)
    expected_events += int(bool(canary.opening_movement_id))
    expected_events += len(canary.reversed_opening_events) + int(bool(canary.cancellation_movement_id))
    applied_or_skipped = [row for row in event_rows if str(row[2]) in {"APPLIED", "SKIPPED_REVERSAL"}]
    if len(applied_or_skipped) != expected_events:
        mismatches.append("event_map_count")
    return mismatches


def _reconcile_record(settings: Settings, contract: SavingsContract, record: dict[str, Any],
                      migration: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if migration["source_hash"] != record["source_hash"]:
        reasons.append("source_hash_mismatch")
    if migration["contract_hash"] != contract.contract_hash:
        reasons.append("contract_hash_mismatch")
    expected_cutoff = record.get("cutoff_date") or getattr(record["payload"], "cutoff_date", None)
    if isinstance(record["payload"], VistaCanary):
        reasons.extend(_reconcile_vista(settings, record["payload"], migration, expected_cutoff))
    else:
        reasons.extend(_reconcile_dpf(settings, contract, record["payload"], migration, expected_cutoff))
    return reasons


def reconcile_savings(settings: Settings, state: State, contract: SavingsContract,
                      run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Savings run does not belong to the selected target")
    items = state.run_items(run_id)
    keys = {item["source_key"] for item in items if item["status"] in {"succeeded", "unchanged"}}
    records = {row["source_key"]: row for row in extract_savings_accounts(settings, contract, sorted(keys))}
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute("""
            SELECT id,source_key,source_hash,contract_hash,savings_account_id,migration_status
            FROM credesal_savings_migration_account
            WHERE source_system=%s AND source_key=ANY(%s)
        """, (SOURCE_SYSTEM, sorted(keys))).fetchall() if keys else []
    migrations = {
        str(row[1]): {"migration_id": int(row[0]), "source_hash": str(row[2]), "contract_hash": str(row[3]),
                      "account_id": int(row[4]), "status": str(row[5])}
        for row in rows
    }
    counts = Counter()
    reason_counts = Counter()
    mismatches: list[dict[str, Any]] = []
    matched_keys: list[str] = []
    for key in sorted(keys):
        record, migration = records.get(key), migrations.get(key)
        reasons: list[str] = []
        if record is None or record.get("quarantine_reason"):
            reasons.append("source_missing_or_invalid")
        elif migration is None:
            reasons.append("migration_identity_missing")
        else:
            reasons.extend(_reconcile_record(settings, contract, record, migration))
        if reasons:
            counts["mismatch"] += 1
            reason_counts.update(reason.split(":", 1)[0] for reason in reasons)
            mismatches.append({"source_key": key, "reasons": reasons[:20]})
        else:
            counts["matched"] += 1
            matched_keys.append(key)
    if matched_keys:
        with _postgres_write_connection(settings.target.pg_url or "") as conn:
            conn.execute("""
                UPDATE credesal_savings_migration_account
                SET migration_status='RECONCILED',reconciled_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                WHERE source_system=%s AND source_key=ANY(%s)
            """, (SOURCE_SYSTEM, matched_keys))
            conn.execute("""
                UPDATE credesal_savings_migration_cycle c
                SET migration_status='RECONCILED',reconciled_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                FROM credesal_savings_migration_account a
                WHERE c.migration_account_id=a.id AND a.source_system=%s AND a.source_key=ANY(%s)
            """, (SOURCE_SYSTEM, matched_keys))
            conn.execute("""
                UPDATE credesal_savings_native_event_map e
                SET reconciled_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                FROM credesal_savings_migration_account a
                WHERE e.migration_account_id=a.id AND a.source_system=%s AND a.source_key=ANY(%s)
            """, (SOURCE_SYSTEM, matched_keys))
            conn.commit()
    failed = sum(item["status"] == "failed" for item in items)
    quarantined = sum(item["status"] == "quarantined" for item in items)
    return {
        # Reviewed quarantines were never written and do not invalidate the
        # reconciliation of the eligible financial population.
        "run_id": run_id, "ok": not mismatches and failed == 0,
        "counts": dict(counts), "failed": failed, "quarantined": quarantined,
        "failed_or_quarantined": failed + quarantined,
        "reason_counts": dict(reason_counts),
        "mismatches": mismatches[:100],
    }
