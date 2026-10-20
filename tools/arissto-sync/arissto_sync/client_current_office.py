"""Guarded current-client-office correction from each borrower's latest loan.

This service changes only m_client.office_id. Historical transfer, loan
transaction, and accounting offices are deliberately outside its scope.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .arissto import select_rows, source_connection
from .config import Settings
from .connections import postgres_connection
from .engine import source_fingerprint
from .state import State


BLOCK = "client-current-office"
VERSION = "latest-dated-originated-loan-v1"


def _mapping(settings: Settings) -> dict[str, int]:
    raw = json.loads(settings.mapping_path.read_text(encoding="utf-8"))
    return {str(branch): int(office) for branch, office in raw["office_mapping"].items()}


def _contract_hash(settings: Settings) -> str:
    material = {"version": VERSION, "office_mapping": _mapping(settings)}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def _source_rows(settings: Settings) -> list[dict[str, Any]]:
    with source_connection(settings.source) as conn:
        rows = select_rows(conn, """
            WITH ranked AS (
                SELECT c.ID_EMPRESA,c.ID_SUCURSAL_SOCIO,c.ID_SOCIO,
                       c.ID_CREDITO,c.FECHA_OTORGAMIENTO,
                       RTRIM(c.ID_SUCURSAL_ACTIVA) AS loan_branch,
                       ROW_NUMBER() OVER (
                           PARTITION BY c.ID_EMPRESA,c.ID_SUCURSAL_SOCIO,c.ID_SOCIO
                           ORDER BY c.FECHA_OTORGAMIENTO DESC,c.ID_CREDITO DESC
                       ) AS ordinal
                FROM dbo.CRD_CARTERA c
                WHERE c.FECHA_OTORGAMIENTO IS NOT NULL
            )
            SELECT RTRIM(a.NUMERO_AFILIACION) AS client_external_id,
                   r.ID_CREDITO AS source_loan_id,
                   CAST(r.FECHA_OTORGAMIENTO AS date) AS loan_date,
                   r.loan_branch
            FROM dbo.AFI_SOCIO a
            JOIN ranked r ON r.ID_EMPRESA=a.ID_EMPRESA
                         AND r.ID_SUCURSAL_SOCIO=a.ID_SUCURSAL
                         AND r.ID_SOCIO=a.ID_SOCIO AND r.ordinal=1
            ORDER BY a.NUMERO_AFILIACION
        """)
    mapping = _mapping(settings)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row["client_external_id"] or "").strip()
        branch = str(row["loan_branch"] or "").strip()
        if not key or key in seen:
            raise RuntimeError("missing_or_duplicate_borrower_affiliation")
        if branch not in mapping:
            raise RuntimeError("latest_loan_office_unmapped")
        seen.add(key)
        result.append({
            "source_key": key,
            "source_loan_id": int(row["source_loan_id"]),
            "loan_date": row["loan_date"].isoformat(),
            "source_branch": branch,
            "desired_office_id": mapping[branch],
        })
    return result


def _source_hash(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inspect(settings: Settings) -> dict[str, Any]:
    if not settings.target.pg_url:
        raise RuntimeError("target_postgres_required")
    rows = _source_rows(settings)
    keys = [row["source_key"] for row in rows]
    with postgres_connection(settings.target.pg_url) as conn:
        database = str(conn.execute("SELECT current_database()").fetchone()[0])
        target = conn.execute(
            "SELECT id,external_id,office_id FROM m_client WHERE external_id=ANY(%s)",
            (keys,),
        ).fetchall()
    if settings.target.name == "local" and (
        settings.target.tenant != "sandbox" or database != "fineract_sandbox"
    ):
        raise RuntimeError("local_target_is_not_sandbox")
    by_key = {str(external): (int(identifier), int(office)) for identifier, external, office in target}
    if len(by_key) != len(target):
        raise RuntimeError("duplicate_target_client_external_id")
    missing = [row["source_key"] for row in rows if row["source_key"] not in by_key]
    if missing:
        raise RuntimeError(f"borrower_target_clients_missing:{len(missing)}")
    changes = [
        {**row, "target_id": by_key[row["source_key"]][0],
         "observed_office_id": by_key[row["source_key"]][1]}
        for row in rows
        if by_key[row["source_key"]][1] != row["desired_office_id"]
    ]
    return {
        "block": BLOCK, "version": VERSION, "target": settings.target.name,
        "tenant": settings.target.tenant, "database": database,
        "target_fingerprint": settings.target.fingerprint,
        "source_fingerprint": source_fingerprint(settings),
        "contract_hash": _contract_hash(settings),
        "source_hash": _source_hash(rows),
        "borrowers_checked": len(rows), "change_count": len(changes),
        "changes": changes,
    }


def build_plan(settings: Settings, state: State) -> tuple[str, dict[str, Any]]:
    document = inspect(settings)
    plan_id = state.save_plan(
        settings.target.fingerprint, BLOCK, document["source_fingerprint"],
        document["contract_hash"], document,
    )
    return plan_id, document


def apply_plan(settings: Settings, state: State, plan_id: str,
               production_confirmation: str | None = None) -> tuple[str, dict[str, int]]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("client_office_plan_target_mismatch")
    if plan["status"] != "planned":
        raise RuntimeError("client_office_plan_not_planned")
    if state.conn.execute("SELECT 1 FROM runs WHERE plan_id=? LIMIT 1", (plan_id,)).fetchone():
        raise RuntimeError("client_office_plan_already_applied")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError("production_fingerprint_confirmation_required")
    current = inspect(settings)
    frozen = plan["document"]
    if any(current[key] != frozen[key] for key in
           ("source_fingerprint", "contract_hash", "source_hash", "changes", "database")):
        raise RuntimeError("client_office_plan_stale")
    if not settings.target.pg_url:
        raise RuntimeError("target_postgres_required")
    import psycopg

    changes = frozen["changes"]
    run_id = state.start_run(plan)
    # Verify the whole reviewed set under one lock before updating any row.
    try:
        with psycopg.connect(settings.target.pg_url, autocommit=False) as conn:
            if str(conn.execute("SELECT current_database()").fetchone()[0]) != frozen["database"]:
                raise RuntimeError("client_office_target_database_changed")
            for item in changes:
                row = conn.execute(
                    "SELECT external_id,office_id FROM m_client WHERE id=%s FOR UPDATE",
                    (item["target_id"],),
                ).fetchone()
                if row != (item["source_key"], item["observed_office_id"]):
                    raise RuntimeError("client_office_target_changed_after_plan")
            for item in changes:
                updated = conn.execute(
                    "UPDATE m_client SET office_id=%s WHERE id=%s AND external_id=%s "
                    "AND office_id=%s RETURNING id",
                    (item["desired_office_id"], item["target_id"], item["source_key"],
                     item["observed_office_id"]),
                ).fetchone()
                if updated != (item["target_id"],):
                    raise RuntimeError("client_office_update_conflict")
            conn.commit()
    except Exception:
        state.finish_run(run_id, "failed", {"corrected": 0})
        raise
    for item in changes:
        state.record_item(
            run_id, item["source_key"], "correct-office", frozen["source_hash"],
            "succeeded", str(item["target_id"]),
        )
    summary = {"corrected": len(changes)}
    state.finish_run(run_id, "completed", summary)
    return run_id, summary


def reconcile(settings: Settings, state: State, run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    plan = state.plan(run["plan_id"])
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("client_office_run_target_mismatch")
    if not settings.target.pg_url:
        raise RuntimeError("target_postgres_required")
    changes = plan["document"]["changes"]
    with postgres_connection(settings.target.pg_url) as conn:
        rows = conn.execute(
            "SELECT id,external_id,office_id FROM m_client WHERE id=ANY(%s)",
            ([item["target_id"] for item in changes],),
        ).fetchall()
    by_id = {int(identifier): (str(external), int(office)) for identifier, external, office in rows}
    mismatches = [
        item["source_key"] for item in changes
        if by_id.get(item["target_id"]) != (item["source_key"], item["desired_office_id"])
    ]
    return {"run_id": run_id, "ok": not mismatches, "matched": len(changes) - len(mismatches),
            "mismatched_source_keys": mismatches}
