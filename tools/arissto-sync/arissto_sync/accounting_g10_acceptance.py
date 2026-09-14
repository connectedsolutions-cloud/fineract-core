from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from .accounting import (
    AccountingContract,
    _hash,
    _load_accounting_plan_inputs,
    _reconcile_accounting_action,
    _source_key,
    _target_reconciliation_snapshot,
    _target_snapshot,
    build_historical_journal_request,
    classify_accounting,
    plan_accounting_rows,
    source_key_text,
)
from .arissto import source_fingerprint
from .config import Settings
from .connections import FineractApi, FineractError, postgres_connection
from .state import State


VERSION = "accounting-g10-canary-acceptance-v2"
POSITIVE_KEYS = {
    "ordinary_multiline": "001:001:00028:0000000097",
    "both_agencies_and_cross_branch": "001:001:00052:0000005132",
    "bank_cash_linked": "001:001:00028:0000000002",
    "opposite_posting_a": "001:001:00032:0000000101",
    "opposite_posting_b": "001:001:00032:0000000104",
    "annual_liquidation": "001:001:00041:0000003078",
}
NEGATIVE_KEYS = {
    "status_2": "001:001:00071:0000013957",
    "empty": "001:001:00045:0000003217",
}
NORMALIZED_DATE_KEY = "001:002:00058:0000007509"
RECOVERY_KEY = "001:001:00031:0000000001"
NATIVE_CUTOFF_REFERENCE = "G10-CUTOFF-20260910"


def _key(row: dict[str, Any]) -> str:
    return source_key_text(_source_key(row))


def _signature(rows: list[dict[str, Any]], reverse: bool = False) -> tuple[tuple[Any, ...], ...]:
    values = []
    for row in rows:
        debit = Decimal(str(row.get("debit") or 0))
        credit = Decimal(str(row.get("credit") or 0))
        values.append((
            str(row.get("account_code") or "").rstrip(),
            str(row.get("destination_branch_id") or "").rstrip(),
            credit if reverse else debit,
            debit if reverse else credit,
        ))
    return tuple(sorted(values))


def _synthetic_quarantine_result(contract: AccountingContract, target: dict[str, Any]) -> dict[str, Any]:
    header = {
        "company_id": "001", "header_branch_id": "001", "period_id": "00065", "journal_id": "G10",
        "journal_number": "2025120010", "journal_date": date(2025, 12, 15), "journal_status": "3",
        "journal_type": "001", "liquidation_flag": "0", "opening_flag": "0", "source_system": 1,
        "daily_close_id": "1", "mayorization_close_id": "1", "period_year": "2025", "period_month": "12",
        "header_concept": None, "header_description": None,
    }
    base = {
        "company_id": "001", "header_branch_id": "001", "period_id": "00065", "journal_id": "G10",
        "source_account_code_count": 1, "line_concept": None, "line_aux_concept": None,
    }
    lines = [
        {**base, "line_id": "1", "account_id": "1", "account_code": "1110010101",
         "destination_branch_id": "001", "debit": Decimal("2.00"), "credit": Decimal("0.00")},
        {**base, "line_id": "2", "account_id": "2", "account_code": None,
         "destination_branch_id": "999", "debit": Decimal("0.00"), "credit": Decimal("1.00")},
    ]
    synthetic_target = dict(target)
    synthetic_target["closure_by_office"] = {1: date(2025, 12, 31)}
    report = classify_accounting([header], lines, contract, date(2026, 9, 10), synthetic_target)
    reasons = set(report["findings"][0]["reason_codes"])
    expected = {
        "SOURCE_JOURNAL_UNBALANCED", "SOURCE_ACCOUNT_UNRESOLVED",
        "SOURCE_DESTINATION_BRANCH_UNMAPPED", "TARGET_OFFICE_CLOSURE_CONFLICT",
    }
    return {"passed": expected <= reasons, "expected_reason_codes": sorted(expected), "reason_codes": sorted(reasons)}


def _active_cutoff(api: FineractApi, cutoff_date: str) -> dict[str, Any]:
    value = api.request("GET", "accountingcutoff")
    return {
        "date": str(value.get("cutoffDate")), "timezone": str(value.get("timezoneId")),
        "source": "explicit", "configuration_revision": value.get("configurationRevision"),
        "configuration_hash": str(value.get("configurationHash")),
        "lifecycle_state": str(value.get("lifecycleState") or "").upper(),
        "matches_requested_date": str(value.get("cutoffDate")) == cutoff_date,
    }


def _target_special_checks(settings: Settings, positive_keys: list[str], cutoff_date: str,
                           native_reference: str) -> dict[str, Any]:
    with postgres_connection(settings.target.pg_url or "") as conn:
        anomaly = conn.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE l.known_transferred_loan_office_mismatch),
                   COUNT(*) FILTER (WHERE l.known_anomaly_codes IS NOT NULL)
              FROM credesal_arissto_gl_journal_line l
              JOIN credesal_arissto_gl_journal p ON p.id=l.journal_provenance_id
             WHERE concat_ws(':',p.source_company_id,p.source_branch_id,p.source_period_id,p.source_journal_id)=ANY(%s)
            """, (positive_keys,),
        ).fetchone()
        native = conn.execute(
            """
            SELECT COUNT(*),COUNT(DISTINCT transaction_id),MIN(entry_date),MAX(entry_date),
                   SUM(CASE WHEN type_enum=2 THEN amount ELSE 0 END),
                   SUM(CASE WHEN type_enum=1 THEN amount ELSE 0 END)
              FROM acc_gl_journal_entry WHERE ref_num=%s
            """, (native_reference,),
        ).fetchone()
    anomaly_result = {
        "line_count": int(anomaly[0]), "flagged_lines": int(anomaly[1]), "coded_lines": int(anomaly[2]),
        "contract_expectation": "preserve_without_flag_until_exact_line_manifest",
    }
    native_result = {
        "line_count": int(native[0]), "transaction_count": int(native[1]),
        "min_date": str(native[2]) if native[2] else None, "max_date": str(native[3]) if native[3] else None,
        "debit": format(Decimal(str(native[4] or 0)), "f"), "credit": format(Decimal(str(native[5] or 0)), "f"),
    }
    native_result["passed"] = (
        native_result["line_count"] == 2 and native_result["transaction_count"] == 1
        and native_result["min_date"] == cutoff_date and native_result["max_date"] == cutoff_date
        and native_result["debit"] == native_result["credit"]
    )
    anomaly_result["passed"] = anomaly_result["line_count"] > 0 and not anomaly_result["flagged_lines"] and not anomaly_result["coded_lines"]
    return {"anomaly_preservation": anomaly_result, "native_cutoff_transaction": native_result}


def _recovery_result(state: State) -> dict[str, Any]:
    rows = state.conn.execute(
        """
        SELECT i.status,a.request_idempotency_key,a.request_run_id,a.error_class,a.retryable
          FROM items i JOIN accounting_attempts a
            ON a.run_id=i.run_id AND a.source_key=i.source_key
         WHERE i.source_key=? ORDER BY i.rowid
        """, (RECOVERY_KEY,),
    ).fetchall()
    values = [dict(row) for row in rows]
    failures = [row for row in values if row["status"] == "failed" and row["error_class"] == "retryable" and row["retryable"]]
    recovered = [row for row in values if row["status"] in {"recovered", "unchanged", "reconciled"}]
    shared = bool(failures and recovered and failures[-1]["request_idempotency_key"] == recovered[0]["request_idempotency_key"]
                  and failures[-1]["request_run_id"] == recovered[0]["request_run_id"])
    return {"passed": shared, "retryable_failure_count": len(failures), "recovered_count": len(recovered),
            "request_identity_reused": shared}


def prove_g10(settings: Settings, contract: AccountingContract, state: State, cutoff_date: str,
              native_reference: str = NATIVE_CUTOFF_REFERENCE) -> dict[str, Any]:
    if settings.target.name != "local":
        raise ValueError("G10 acceptance is restricted to the local target")
    if not settings.target.pg_url:
        raise ValueError("FINERACT_LOCAL_PG_URL is required for G10 acceptance")
    api = FineractApi(settings.target)
    cutoff = _active_cutoff(api, cutoff_date)
    all_keys = sorted(set(POSITIVE_KEYS.values()) | set(NEGATIVE_KEYS.values()) | {NORMALIZED_DATE_KEY, RECOVERY_KEY})
    headers, lines, schema, currencies = _load_accounting_plan_inputs(settings, contract, all_keys)
    target = _target_snapshot(settings.target.pg_url, contract)
    document = plan_accounting_rows(
        headers, lines, contract, cutoff, source_fingerprint(settings.source), settings.target.fingerprint,
        target, all_keys, _hash(schema),
    )
    actions = {row["source_key"]: row for row in document["actions"]}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in lines:
        grouped[_key(row)].append(row)
    header_by_key = {_key(row): row for row in headers}
    snapshot = _target_reconciliation_snapshot(settings.target.pg_url, contract, sorted(set(POSITIVE_KEYS.values()) | {RECOVERY_KEY}), cutoff_date)
    target_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshot["rows"]:
        target_rows[str(row["source_key"])].append(row)
    journal_findings = {
        key: _reconcile_accounting_action(actions[key], target_rows[key], document)
        for key in sorted(set(POSITIVE_KEYS.values()) | {RECOVERY_KEY})
    }
    ordinary = grouped[POSITIVE_KEYS["ordinary_multiline"]]
    multi = grouped[POSITIVE_KEYS["both_agencies_and_cross_branch"]]
    multi_header = header_by_key[POSITIVE_KEYS["both_agencies_and_cross_branch"]]
    annual_header = header_by_key[POSITIVE_KEYS["annual_liquidation"]]
    features = {
        "ordinary_multiline": len(ordinary) >= 3,
        "both_agencies": {str(row["destination_branch_id"]).rstrip() for row in multi} == {"001", "002"},
        "destination_differs_header": any(str(row["destination_branch_id"]).rstrip() != str(multi_header.get("header_branch_id") or "").rstrip()
                                                  for row in multi),
        "bank_cash_linked": any(str(row.get("account_code") or "").rstrip().startswith("111001")
                                for row in grouped[POSITIVE_KEYS["bank_cash_linked"]]),
        "opposite_postings": _signature(grouped[POSITIVE_KEYS["opposite_posting_a"]], reverse=True)
                             == _signature(grouped[POSITIVE_KEYS["opposite_posting_b"]]),
        "annual_liquidation": str(annual_header.get("journal_type") or "").rstrip() == "003"
                              and str(annual_header.get("liquidation_flag") or "").rstrip() == "1",
        "normalized_accounting_period_date": (
            actions[NORMALIZED_DATE_KEY]["disposition"] in {"APPLICABLE", "UNCHANGED"}
            and actions[NORMALIZED_DATE_KEY]["payload"]["entry_date"] == "2025-05-31"
            and actions[NORMALIZED_DATE_KEY]["payload"]["provenance"]["source_journal_date"] == "2025-06-04"
            and set(actions[NORMALIZED_DATE_KEY]["payload"]["provenance"]["date_anomaly_codes"])
            == {"SOURCE_JOURNAL_BACK_PERIOD", "SOURCE_JOURNAL_REFERENCE_DATE_MISMATCH"}
        ),
    }
    expected_negative = {
        NEGATIVE_KEYS["status_2"]: {"SOURCE_JOURNAL_EXCLUDED_FROM_LEDGER"},
        NEGATIVE_KEYS["empty"]: {"SOURCE_JOURNAL_EMPTY"},
    }
    live_quarantines = {
        key: {"passed": actions[key]["disposition"] == "QUARANTINED" and expected <= set(actions[key]["reason_codes"]),
              "reason_codes": actions[key]["reason_codes"]}
        for key, expected in expected_negative.items()
    }
    special = _target_special_checks(settings, sorted(set(POSITIVE_KEYS.values())), cutoff_date, native_reference)
    recovery = _recovery_result(state)
    changed = dict(actions[RECOVERY_KEY])
    request = build_historical_journal_request(
        "g10-proof", "g10-changed-hash-proof", document, changed, header_by_key[RECOVERY_KEY], grouped[RECOVERY_KEY], contract,
    )
    request["sourceHash"] = "f" * 64
    changed_hash_rejected = False
    try:
        api.request("POST", "arisstohistoricaljournals", request, idempotency_key="g10-changed-hash-proof-v1")
    except FineractError as exc:
        changed_hash_rejected = "source.key.conflict" in str(exc)
    synthetic = _synthetic_quarantine_result(contract, target)
    checks = [
        cutoff["matches_requested_date"], cutoff["lifecycle_state"] == "ACTIVE",
        not any(journal_findings.values()), not snapshot["boundary"]["native_non_manual_pre_cutoff"],
        not snapshot["boundary"]["imported_on_or_after_cutoff"], all(features.values()),
        all(item["passed"] for item in live_quarantines.values()), synthetic["passed"], recovery["passed"],
        changed_hash_rejected, special["anomaly_preservation"]["passed"], special["native_cutoff_transaction"]["passed"],
    ]
    result = {
        "version": VERSION, "accepted": all(checks), "cutoff": cutoff, "features": features,
        "journal_findings": journal_findings, "live_quarantines": live_quarantines,
        "synthetic_quarantines": synthetic, "recovery": recovery,
        "changed_hash_rejected": changed_hash_rejected, "boundary": snapshot["boundary"], **special,
    }
    result["evidence_hash"] = _hash(result)
    return result
