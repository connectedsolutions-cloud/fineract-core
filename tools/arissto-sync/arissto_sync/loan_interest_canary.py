"""Guarded native interest-waiver trial on one namespaced sandbox loan."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from .arissto import select_rows, source_connection, source_fingerprint
from .config import ROOT, Settings
from .connections import FineractApi, postgres_connection
from .loans import _find_loan

PLAN_DIR = ROOT / ".arissto-sync" / "loan-interest-canaries"
SOURCE_LOAN = 2331
REVISION_ID = 230
AUDIT_ID = 6396407
EVENT_DATE = "2026-10-12"
CLOSES = ("000000002202", "000000002203", "000000002208")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _source(settings: Settings) -> dict[str, Any]:
    with source_connection(settings.source) as conn:
        revisions = select_rows(conn, """
            SELECT ID_CREDITO,ID_REESTRUCTURACION,DT_CREO,ID_CIERRE_DIARIO
            FROM dbo.CRD_REESTRUCTURACION
            WHERE ID_CREDITO=? AND ID_REESTRUCTURACION=?
        """, (SOURCE_LOAN, REVISION_ID))
        audits = select_rows(conn, """
            SELECT IDAudit,TableName,FieldName,OldValue,NewValue,UpdateDate,ID_CIERRE_DIARIO
            FROM dbo.Audit WHERE IDAudit=?
        """, (AUDIT_ID,))
        closes = select_rows(conn, """
            SELECT ID_CIERRE_DIARIO,SALDO_INTERES,SALDO_VENCIDO_INTERES,
                   SALDO_VENCIDO_CAPITAL,SALDO_PAGADO_CAPITAL,SALDO_PAGADO_INTERES
            FROM dbo.CRD_HISTORICO_DIARIO
            WHERE ID_CREDITO=? AND ID_CIERRE_DIARIO IN (?,?,?)
            ORDER BY ID_CIERRE_DIARIO
        """, (SOURCE_LOAN, *CLOSES))
    if len(revisions) != 1 or len(audits) != 1 or len(closes) != 3:
        raise ValueError("Source event or completed close evidence is missing")
    revision, audit = revisions[0], audits[0]
    if (revision["ID_CIERRE_DIARIO"] != CLOSES[1]
            or revision["DT_CREO"].date().isoformat() != EVENT_DATE
            or audit["TableName"] != "CRD_CARTERA"
            or audit["FieldName"] != "FECHA_ULTIMO_PAGOINT"
            or audit["ID_CIERRE_DIARIO"] != CLOSES[1]
            or audit["UpdateDate"].date().isoformat() != EVENT_DATE):
        raise ValueError("Source revision and interest-date audit no longer identify the event")
    before, after, final = closes
    amount = Decimal(str(before["SALDO_INTERES"])) - Decimal(str(after["SALDO_INTERES"]))
    if amount != Decimal("32.7900"):
        raise ValueError(f"Source interest delta changed: {amount}")
    return {
        "revision_id": REVISION_ID, "revision_recorded_at": revision["DT_CREO"].isoformat(),
        "audit_id": AUDIT_ID, "audit_recorded_at": audit["UpdateDate"].isoformat(),
        "audit_old": audit["OldValue"], "audit_new": audit["NewValue"],
        "event_date": EVENT_DATE, "waiver_amount": "32.79",
        "closes": [{k: (format(v, "f") if isinstance(v, Decimal) else v)
                    for k, v in row.items()} for row in closes],
        "final_interest": format(final["SALDO_INTERES"], "f"),
    }


def _loan(settings: Settings, namespace: str) -> dict[str, Any]:
    if settings.target.name != "local" or settings.target.tenant != "sandbox":
        raise ValueError("Interest canary requires local sandbox")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,23}", namespace):
        raise ValueError("Invalid proof namespace")
    external_id = f"PROOF:{namespace}:ARISSTO:CRD:{SOURCE_LOAN}"
    loan = _find_loan(FineractApi(settings.target), external_id)
    if loan is None or loan.get("externalId") != external_id:
        raise ValueError("Namespaced proof loan is missing")
    if int((loan.get("status") or {}).get("id") or 0) != 300:
        raise ValueError("Proof loan is not active")
    return loan


def _target(loan: dict[str, Any]) -> dict[str, Any]:
    summary = loan.get("summary") or {}
    transactions = loan.get("transactions") or []
    ids = sorted(int(t["id"]) for t in transactions)
    return {
        "transaction_ids": ids,
        "interest_outstanding": str(summary.get("interestOutstanding")),
        "interest_overdue": str(summary.get("interestOverdue")),
        "interest_waived": str(summary.get("interestWaived")),
        "principal_outstanding": str(summary.get("principalOutstanding")),
    }


def _public_target(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in snapshot.items() if k != "transaction_ids"} | {
        "transaction_count": len(snapshot["transaction_ids"]),
        "transaction_ids_hash": hashlib.sha256(_canonical(snapshot["transaction_ids"])).hexdigest(),
    }


def _boundary(settings: Settings, source_through_date: str) -> str:
    source_through = date.fromisoformat(source_through_date)
    fineract_starts = (source_through + timedelta(days=1)).isoformat()
    boundary = FineractApi(settings.target).request("GET", "accountingcutoff")
    if boundary.get("lifecycleState") != "ACTIVE" or boundary.get("cutoffDate") != fineract_starts:
        raise ValueError("Source-through date does not match active sandbox accounting boundary")
    if date.fromisoformat(EVENT_DATE) > source_through:
        raise ValueError("Source event is after Arissto source-through date")
    return fineract_starts


def _external_id(namespace: str) -> str:
    return f"PROOF:{namespace}:CRD:{SOURCE_LOAN}:AUDIT:{AUDIT_ID}"


def _waiver(loan: dict[str, Any], external_id: str) -> dict[str, Any] | None:
    found = [t for t in loan.get("transactions") or [] if t.get("externalId") == external_id]
    if len(found) > 1:
        raise ValueError("Duplicate waiver external ID")
    return found[0] if found else None


def _journal(settings: Settings, transaction_id: int) -> list[dict[str, Any]]:
    if not settings.target.pg_url:
        raise ValueError("Read-only local PostgreSQL connection is required")
    with postgres_connection(settings.target.pg_url) as conn:
        rows = conn.execute("""
            SELECT j.id,j.entry_date,j.type_enum,j.amount,g.gl_code,j.reversed
            FROM acc_gl_journal_entry j JOIN acc_gl_account g ON g.id=j.account_id
            WHERE j.loan_transaction_id=%s ORDER BY j.id
        """, (transaction_id,)).fetchall()
    return [{"id": row[0], "date": row[1].isoformat(), "type": row[2],
             "amount": format(row[3], "f"), "gl_code": row[4], "reversed": row[5]}
            for row in rows]


def build_plan(settings: Settings, namespace: str, source_through_date: str) -> dict[str, Any]:
    fineract_starts = _boundary(settings, source_through_date)
    source = _source(settings)
    loan = _loan(settings, namespace)
    external_id = _external_id(namespace)
    if _waiver(loan, external_id):
        raise ValueError("Canary waiver already exists; reconcile its existing plan")
    target = _target(loan)
    if target["interest_waived"] not in {"0", "0.0", "0.00"}:
        raise ValueError("Proof loan already has an interest waiver")
    document = {
        "kind": "loan-interest-waiver-canary-v1", "source": source,
        "source_fingerprint": source_fingerprint(settings.source),
        "target_fingerprint": settings.target.fingerprint,
        "target_loan_id": int(loan["id"]), "target_external_id": loan["externalId"],
        "waiver_external_id": external_id, "baseline": target,
        "arissto_through": source_through_date, "fineract_starts": fineract_starts,
    }
    plan_id = hashlib.sha256(_canonical(document)).hexdigest()
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    path = PLAN_DIR / f"{plan_id}.json"
    if path.exists() and path.read_bytes() != _canonical(document):
        raise RuntimeError("Immutable plan collision")
    if not path.exists():
        path.write_bytes(_canonical(document))
    return {"plan_id": plan_id, "path": str(path), "source_loan_id": SOURCE_LOAN,
            "target_loan_id": loan["id"], "event_date": EVENT_DATE,
            "waiver_amount": source["waiver_amount"], "baseline": _public_target(target),
            "arissto_through": source_through_date, "fineract_starts": fineract_starts}


def _read_plan(plan_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", plan_id):
        raise ValueError("Invalid plan ID")
    document = json.loads((PLAN_DIR / f"{plan_id}.json").read_text())
    if hashlib.sha256(_canonical(document)).hexdigest() != plan_id:
        raise ValueError("Canary plan checksum changed")
    if document["kind"] != "loan-interest-waiver-canary-v1":
        raise ValueError("Wrong canary plan kind")
    return document


def reconcile(settings: Settings, plan_id: str) -> dict[str, Any]:
    document = _read_plan(plan_id)
    namespace = document["target_external_id"].split(":", 2)[1]
    loan = _loan(settings, namespace)
    if int(loan["id"]) != document["target_loan_id"]:
        raise ValueError("Proof loan identity changed")
    waiver = _waiver(loan, document["waiver_external_id"])
    after = _target(loan)
    if waiver is None:
        return {"plan_id": plan_id, "status": "not_applied",
                "baseline": _public_target(document["baseline"]), "current": _public_target(after)}
    transaction_id = int(waiver["id"])
    transaction = FineractApi(settings.target).request("GET", f"loans/{loan['id']}/transactions/{transaction_id}")
    actual_date = transaction.get("date")
    if isinstance(actual_date, list):
        actual_date = date(*actual_date[:3]).isoformat()
    valid = (transaction.get("type", {}).get("code") == "loanTransactionType.waiver"
             and Decimal(str(transaction.get("amount"))) == Decimal(document["source"]["waiver_amount"])
             and actual_date == document["source"]["event_date"])
    baseline = document["baseline"]
    closes = document["source"]["closes"]
    native_interest_drop = Decimal(baseline["interest_outstanding"]) - Decimal(after["interest_outstanding"])
    native_overdue_drop = Decimal(baseline["interest_overdue"]) - Decimal(after["interest_overdue"])
    source_interest_drop = Decimal(closes[0]["SALDO_INTERES"]) - Decimal(closes[1]["SALDO_INTERES"])
    source_overdue_drop = Decimal(closes[0]["SALDO_VENCIDO_INTERES"]) - Decimal(closes[1]["SALDO_VENCIDO_INTERES"])
    effects = {"native_interest_drop": format(native_interest_drop, "f"),
               "source_interest_drop": format(source_interest_drop, "f"),
               "interest_delta_matches": native_interest_drop == source_interest_drop,
               "native_overdue_drop": format(native_overdue_drop, "f"),
               "source_overdue_drop": format(source_overdue_drop, "f"),
               "overdue_delta_matches": native_overdue_drop == source_overdue_drop,
               "principal_unchanged": after["principal_outstanding"] == baseline["principal_outstanding"]}
    return {"plan_id": plan_id, "status": "reconciled" if valid else "mismatch",
            "target_loan_id": loan["id"], "transaction_id": transaction_id,
            "waiver": {"date": actual_date, "amount": transaction.get("amount"),
                       "interest_portion": transaction.get("interestPortion"),
                       "unrecognized_income_portion": transaction.get("unrecognizedIncomePortion"),
                       "reversed": transaction.get("manuallyReversed")},
            "baseline": _public_target(baseline), "after": _public_target(after), "effects": effects,
            "journals": _journal(settings, transaction_id),
            "source_closes": closes}


def apply_plan(settings: Settings, plan_id: str) -> dict[str, Any]:
    document = _read_plan(plan_id)
    if (settings.target.fingerprint != document["target_fingerprint"]
            or source_fingerprint(settings.source) != document["source_fingerprint"]):
        raise ValueError("Source or target fingerprint changed")
    if _boundary(settings, document["arissto_through"]) != document["fineract_starts"]:
        raise ValueError("Accounting boundary changed")
    if _source(settings) != document["source"]:
        raise ValueError("Source event or close values changed")
    namespace = document["target_external_id"].split(":", 2)[1]
    loan = _loan(settings, namespace)
    if loan["externalId"] != document["target_external_id"] or int(loan["id"]) != document["target_loan_id"]:
        raise ValueError("Proof loan identity changed")
    if _waiver(loan, document["waiver_external_id"]):
        return reconcile(settings, plan_id)
    if _target(loan) != document["baseline"]:
        raise ValueError("Proof loan changed after canary plan")
    source = document["source"]
    FineractApi(settings.target).request(
        "POST", f"loans/{loan['id']}/transactions",
        {"transactionDate": source["event_date"], "transactionAmount": source["waiver_amount"],
         "externalId": document["waiver_external_id"], "dateFormat": "yyyy-MM-dd", "locale": "en"},
        query={"command": "waiveinterest"}, idempotency_key=f"lwc2:{plan_id[:43]}",
    )
    return reconcile(settings, plan_id)
