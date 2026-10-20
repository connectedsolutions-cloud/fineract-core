"""Isolated, reviewed schedule-transition probes on namespaced local loans.

This proves the native source-exact schedule mechanism. It does not claim to
create a dated Fineract reschedule request or import interest waivers.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from .arissto import select_rows, source_connection, source_fingerprint
from .config import ROOT, Settings
from .connections import FineractApi, postgres_connection
from .loans import (
    _enum_id, _find_loan, _iso_date, _loan_schedule_differences,
    _source_exact_schedule_hash,
    _target_transaction_is_reversed,
)

PLAN_DIR = ROOT / ".arissto-sync" / "loan-event-canaries"
ALLOWED_LOANS = {1597: 240, 2355: 178}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _source_versions(settings: Settings, loan_id: int, revision_id: int) -> dict[str, Any]:
    with source_connection(settings.source) as conn:
        revisions = select_rows(conn, """
            SELECT ID_CREDITO,ID_REESTRUCTURACION,DT_CREO,FECHA_REESTRUCTURACION
            FROM dbo.CRD_REESTRUCTURACION
            WHERE ID_CREDITO=? ORDER BY DT_CREO,ID_REESTRUCTURACION
        """, (loan_id,))
        archived = select_rows(conn, """
            SELECT NO_CUOTA,FECHA_PAGO,MONTO_CAPITAL,MONTO_INTERES
            FROM dbo.CRD_PLAN_PAGO WHERE ID_REESTRUCTURACION=?
            ORDER BY NO_CUOTA,FECHA_PAGO,ID_PLAN_PAGO
        """, (revision_id,))
        current = select_rows(conn, """
            SELECT NO_CUOTA,FECHA_PAGO,MONTO_CAPITAL,MONTO_INTERES
            FROM dbo.CRD_PLAN_PAGO WHERE ID_CREDITO=?
            ORDER BY NO_CUOTA,FECHA_PAGO,ID_PLAN_PAGO
        """, (loan_id,))
    if len(revisions) != 1 or int(revisions[0]["ID_REESTRUCTURACION"]) != revision_id:
        raise ValueError("Canary requires exactly one matching source revision")
    if not archived or not current:
        raise ValueError("Canary requires both archived and current schedule rows")
    return {"revision": revisions[0], "before": archived, "after": current}


def _installments(rows: list[dict[str, Any]], origin: str) -> list[dict[str, Any]]:
    result = []
    previous = date.fromisoformat(origin)
    for index, row in enumerate(rows, 1):
        number = int(row["NO_CUOTA"])
        due = date.fromisoformat(_iso_date(row["FECHA_PAGO"], "FECHA_PAGO"))
        principal = Decimal(str(row["MONTO_CAPITAL"] or 0))
        interest = Decimal(str(row["MONTO_INTERES"] or 0))
        defects = []
        if number != index:
            defects.append("nonsequential installment number")
        if due <= previous:
            defects.append("nonmonotonic due date")
        if principal < 0 or interest < 0:
            defects.append("negative principal or interest")
        if defects:
            raise ValueError(f"Unrepresentable source installment {index}: {', '.join(defects)}")
        result.append({"installmentNumber": number, "fromDate": previous.isoformat(),
                       "dueDate": due.isoformat(), "principal": format(principal, "f"),
                       "interest": format(interest, "f")})
        previous = due
    return result


def _loan(settings: Settings, loan_id: int, namespace: str) -> dict[str, Any]:
    if settings.target.name != "local" or settings.target.tenant != "sandbox":
        raise ValueError("Loan event canaries require the local sandbox tenant")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,23}", namespace):
        raise ValueError("Invalid proof namespace")
    external_id = f"PROOF:{namespace}:ARISSTO:CRD:{loan_id}"
    loan = _find_loan(FineractApi(settings.target), external_id)
    if loan is None:
        raise ValueError(f"Proof loan {external_id} is absent; import it with scoped loans plan/apply")
    if loan.get("externalId") != external_id or int((loan.get("status") or {}).get("id") or 0) != 300:
        raise ValueError("Proof loan identity or active status changed")
    return loan


def _origin(loan: dict[str, Any]) -> str:
    timeline = loan.get("timeline") or {}
    value = timeline.get("actualDisbursementDate") or timeline.get("expectedDisbursementDate")
    if value is None:
        raise ValueError("Proof loan disbursement date is absent")
    return _iso_date(value, "loan disbursement date")


def _non_disbursement_count(loan: dict[str, Any]) -> int:
    return sum(1 for row in loan.get("transactions") or []
               if not _target_transaction_is_reversed(row) and _enum_id(row.get("type")) != 1)


def _persisted_rows(settings: Settings, target_loan_id: int) -> list[dict[str, Any]]:
    if not settings.target.pg_url:
        raise ValueError("Canary requires a read-only local target PostgreSQL connection")
    with postgres_connection(settings.target.pg_url) as conn:
        rows = conn.execute("""
            SELECT installment,fromdate,duedate,principal_amount,interest_amount
            FROM m_loan_repayment_schedule
            WHERE loan_id=%s AND NOT is_down_payment AND NOT is_additional
            ORDER BY installment
        """, (target_loan_id,)).fetchall()
    if not rows:
        raise ValueError("Proof loan has no persisted repayment installments")
    return [{"installmentNumber": int(number), "fromDate": start.isoformat(),
             "dueDate": due.isoformat(), "principal": format(principal, "f"),
             "interest": format(interest, "f")}
            for number, start, due, principal, interest in rows]


def _portfolio_account_selection(settings: Settings, target_loan_id: int) -> dict[str, Any]:
    if not settings.target.pg_url:
        raise ValueError("Canary requires a read-only local target PostgreSQL connection")
    with postgres_connection(settings.target.pg_url) as conn:
        row = conn.execute("""
            SELECT portfolio_account_gl_id,portfolio_account_expected_maturedon_date
            FROM m_loan WHERE id=%s
        """, (target_loan_id,)).fetchone()
    if row is None:
        raise ValueError("Proof loan disappeared from local target")
    return {"gl_id": row[0], "maturity": row[1].isoformat() if row[1] else None}


def build_plan(settings: Settings, loan_id: int, revision_id: int, namespace: str,
               phase: str, source_through_date: str) -> dict[str, Any]:
    if ALLOWED_LOANS.get(loan_id) != revision_id or phase not in {"before", "after"}:
        raise ValueError("Only the reviewed 1597/240 and 2355/178 schedule canaries are supported")
    source_through = date.fromisoformat(source_through_date)
    boundary = FineractApi(settings.target).request("GET", "accountingcutoff")
    if boundary.get("lifecycleState") != "ACTIVE" or boundary.get("cutoffDate") != (
        source_through + timedelta(days=1)
    ).isoformat():
        raise ValueError("Canary source-through date must match the active sandbox accounting boundary")
    versions = _source_versions(settings, loan_id, revision_id)
    recorded = versions["revision"]["DT_CREO"]
    if not isinstance(recorded, datetime) or recorded.date() > source_through:
        raise ValueError("Revision is later than Arissto source-through date")
    # Validate intrinsic source shape before requiring a proof clone. This
    # makes exceptional source plans safe to inspect without importing a chain.
    _installments(versions["before"], "1970-01-01")
    _installments(versions["after"], "1970-01-01")
    loan = _loan(settings, loan_id, namespace)
    origin = _origin(loan)
    before = _installments(versions["before"], origin)
    replacement = _installments(versions[phase], origin)
    selection = _portfolio_account_selection(settings, int(loan["id"]))
    if selection["gl_id"] is not None and selection["maturity"] != replacement[-1]["dueDate"]:
        raise ValueError(
            "Native schedule replacement requires reviewed term portfolio account reclassification: "
            f"selected maturity {selection['maturity']}, replacement maturity {replacement[-1]['dueDate']}"
        )
    target_rows = _persisted_rows(settings, int(loan["id"]))
    if phase == "after" and _source_exact_schedule_hash(target_rows) != _source_exact_schedule_hash(before):
        raise ValueError("After-phase requires the archived before-plan on the proof loan")
    document = {
        "kind": "loan-event-canary-schedule-v2", "source_loan_id": loan_id,
        "revision_id": revision_id, "recorded_at": recorded.isoformat(),
        "phase": phase, "external_id": loan["externalId"], "target_loan_id": int(loan["id"]),
        "target_fingerprint": settings.target.fingerprint,
        "source_fingerprint": source_fingerprint(settings.source),
        "arissto_through": source_through.isoformat(),
        "fineract_starts": (source_through + timedelta(days=1)).isoformat(),
        "origin": origin, "source_before_hash": _source_exact_schedule_hash(before),
        "portfolio_account_selection": selection,
        "source_after_hash": _source_exact_schedule_hash(_installments(versions["after"], origin)),
        "expected_target_hash": _source_exact_schedule_hash(target_rows),
        "expected_non_disbursement_count": _non_disbursement_count(loan),
        "replacement": replacement,
    }
    plan_id = hashlib.sha256(_canonical(document)).hexdigest()
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    path = PLAN_DIR / f"{plan_id}.json"
    if not path.exists():
        path.write_bytes(_canonical(document))
    elif path.read_bytes() != _canonical(document):
        raise RuntimeError("Immutable canary plan collision")
    return {"plan_id": plan_id, "path": str(path), "phase": phase,
            "source_loan_id": loan_id, "revision_id": revision_id,
            "target_external_id": document["external_id"],
            "arissto_through": document["arissto_through"],
            "fineract_starts": document["fineract_starts"],
            "expected_target_hash": document["expected_target_hash"],
            "replacement_hash": _source_exact_schedule_hash(replacement),
            "installments": len(replacement)}


def apply_plan(settings: Settings, plan_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", plan_id):
        raise ValueError("Invalid canary plan ID")
    document = json.loads((PLAN_DIR / f"{plan_id}.json").read_text())
    if hashlib.sha256(_canonical(document)).hexdigest() != plan_id:
        raise ValueError("Canary plan checksum changed")
    if document["kind"] != "loan-event-canary-schedule-v2":
        raise ValueError("Wrong canary plan kind")
    loan_id = int(document["source_loan_id"])
    revision_id = int(document["revision_id"])
    namespace = document["external_id"].split(":", 2)[1]
    if ALLOWED_LOANS.get(loan_id) != revision_id:
        raise ValueError("Source revision is outside canary allowlist")
    if settings.target.fingerprint != document["target_fingerprint"] or source_fingerprint(settings.source) != document["source_fingerprint"]:
        raise ValueError("Source or target fingerprint changed")
    boundary = FineractApi(settings.target).request("GET", "accountingcutoff")
    if boundary.get("lifecycleState") != "ACTIVE" or boundary.get("cutoffDate") != document["fineract_starts"]:
        raise ValueError("Sandbox accounting boundary changed after canary plan")
    versions = _source_versions(settings, loan_id, revision_id)
    if versions["revision"]["DT_CREO"].isoformat() != document["recorded_at"]:
        raise ValueError("Source revision timestamp changed")
    current_source = _installments(versions[document["phase"]], document["origin"])
    if current_source != document["replacement"]:
        raise ValueError("Source schedule changed after plan")
    if (_source_exact_schedule_hash(_installments(versions["before"], document["origin"]))
            != document["source_before_hash"]
            or _source_exact_schedule_hash(_installments(versions["after"], document["origin"]))
            != document["source_after_hash"]):
        raise ValueError("Source before/after signatures changed after plan")
    loan = _loan(settings, loan_id, namespace)
    if loan["externalId"] != document["external_id"] or int(loan["id"]) != document["target_loan_id"]:
        raise ValueError("Target loan identity changed")
    if _portfolio_account_selection(settings, int(loan["id"])) != document["portfolio_account_selection"]:
        raise ValueError("Term portfolio account selection changed after canary plan")
    target_hash = _source_exact_schedule_hash(_persisted_rows(settings, int(loan["id"])))
    replacement_hash = _source_exact_schedule_hash(document["replacement"])
    if target_hash == replacement_hash:
        return {"plan_id": plan_id, "status": "already_applied", "target_loan_id": loan["id"]}
    if target_hash != document["expected_target_hash"] or _non_disbursement_count(loan) != document["expected_non_disbursement_count"]:
        raise ValueError("Proof loan schedule or transaction count changed after plan")
    api = FineractApi(settings.target)
    api.request("POST", f"loans/{loan['id']}", {
        "sourceSystem": "ARISSTO", "sourceLoanExternalId": loan["externalId"],
        "installments": document["replacement"],
        "expectedCurrentScheduleHash": target_hash,
        "replacementScheduleHash": replacement_hash,
        "expectedNonDisbursementTransactionCount": document["expected_non_disbursement_count"],
        "dateFormat": "yyyy-MM-dd", "locale": "en",
    }, query={"command": "sourceExactResyncSchedule"}, idempotency_key=f"loan-event-canary:{plan_id[:30]}")
    refreshed = _loan(settings, loan_id, namespace)
    persisted_hash = _source_exact_schedule_hash(_persisted_rows(settings, int(refreshed["id"])))
    expected = [{"number": r["installmentNumber"], "due_date": r["dueDate"],
                 "principal": r["principal"], "interest": r["interest"]}
                for r in document["replacement"]]
    differences = _loan_schedule_differences(expected, refreshed.get("repaymentSchedule") or {})
    return {"plan_id": plan_id, "status": "applied" if not differences and persisted_hash == replacement_hash else "mismatch",
            "target_loan_id": refreshed["id"], "schedule_differences": differences,
            "persisted_schedule_hash": persisted_hash,
            "summary": refreshed.get("summary")}
