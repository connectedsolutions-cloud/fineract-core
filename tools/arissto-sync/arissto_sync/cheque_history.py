"""Reviewed, metadata-only Arissto cheque lookup import."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from .arissto import select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import postgres_connection
from .sql_writer import ControlledSqlWriter
from .state import State


BLOCK = "cheque-history"
POLICY = "basic-cheque-facts-and-exact-links-v2-source-through"
WRITE_OPERATION = "insert_historical_cheque_metadata"


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _part(value: Any) -> str:
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return str(int(value))
    return _clean(value) or ""


def _day(value: Any) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def _money(value: Any) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class Link:
    relationship_type: str
    source_key: str
    target_type: str | None = None
    target_id: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return self.relationship_type, self.source_key


@dataclass(frozen=True)
class Cheque:
    kind: str
    source_id: int
    number: str | None
    bank: str
    amount: str
    cheque_date: date | None
    cancelled: bool | None
    links: tuple[Link, ...]
    source_hash: str

    @property
    def key(self) -> tuple[str, int]:
        return self.kind, self.source_id


def _make_cheque(kind: str, row: dict[str, Any], links: list[Link]) -> Cheque:
    source_id = int(row["source_id"])
    unique = {link.key: link for link in links}
    if len(unique) != len(links):
        raise RuntimeError(f"Duplicate source relationship for {kind} cheque {source_id}")
    ordered = tuple(sorted(unique.values(), key=lambda link: link.key))
    number = _clean(row["cheque_number"])
    bank = _clean(row["bank_name"])
    if bank is None:
        raise RuntimeError(f"Missing bank for {kind} cheque {source_id}")
    cancelled = _clean(row.get("cancelled")) == "1" if kind == "issued" else None
    cheque_date = _day(row["cheque_date"])
    facts = (kind, source_id, number, bank, _money(row["amount"]), cheque_date, cancelled,
             [(link.relationship_type, link.source_key) for link in ordered])
    return Cheque(kind, source_id, number, bank, _money(row["amount"]), cheque_date,
                  cancelled, ordered, _digest(facts))


def _extract(settings: Settings, source_through_date: str) -> list[Cheque]:
    """Only fixed SELECTs run against the read-only Arissto connection."""
    through = date.fromisoformat(source_through_date)
    if through.isoformat() != source_through_date:
        raise ValueError("Source through date must use YYYY-MM-DD")
    first_fineract_day = (through + timedelta(days=1)).isoformat()
    with source_connection(settings.source) as source:
        issued = select_rows(source, """
            SELECT b.ID_LIBRO_BANCO source_id,b.COMPROBANTE cheque_number,
                   bank.NOMBRE_BANCO bank_name,b.MONTO amount,
                   b.FECHA_MOVIMIENTO cheque_date,b.ANULADO cancelled
              FROM dbo.BNC_LIBRO_BANCO b
              JOIN dbo.BNC_CUENTA_BANCARIA account ON account.ID_CUENTA_BANCARIA=b.ID_CUENTA_BANCARIA
              JOIN dbo.BNC_BANCO bank ON bank.ID_BANCO=account.ID_BANCO
             WHERE b.CODIGO_SISTEMA=11 AND b.ID_TRANSACCION='00002'
               AND b.FECHA_MOVIMIENTO < ?
             ORDER BY b.ID_LIBRO_BANCO
        """, (first_fineract_day,))
        received = select_rows(source, """
            SELECT r.ID_REF_CHEQUE source_id,r.NUMERO_CHEQUE cheque_number,
                   bank.BANCO bank_name,r.MONTO_CHEQUE amount,
                   r.FECHA_CHEQUE cheque_date,CAST(NULL AS varchar(1)) cancelled
              FROM dbo.CJA_REF_CHEQUE r
              JOIN dbo.CJA_BANCO bank ON bank.ID_BANCO=r.ID_BANCO
             WHERE r.DT_CREO < ?
             ORDER BY r.ID_REF_CHEQUE
        """, (first_fineract_day,))
        eligible = {(kind, int(row["source_id"]))
                    for kind, rows in (("issued", issued), ("received", received)) for row in rows}
        specs = (
            ("issued", "GL_LINE", """SELECT d.ID_LIBRO_BANCO source_id,d.ID_EMPRESA p1,d.ID_SUCURSAL p2,
                d.ID_PERIODO p3,d.ID_PARTIDA p4,d.ID_DETALLE_PARTIDA p5
                FROM dbo.CNT_DETALLE_PARTIDAS d JOIN dbo.BNC_LIBRO_BANCO b ON b.ID_LIBRO_BANCO=d.ID_LIBRO_BANCO
                WHERE b.CODIGO_SISTEMA=11 AND b.ID_TRANSACCION='00002'"""),
            ("issued", "ACCOUNTING_COMPONENT", """SELECT d.ID_LIBRO_BANCO source_id,d.ID_TRANSAC p1,
                d.ID_DET_TRANSAC p2 FROM dbo.CNT_DET_TRANSAC d JOIN dbo.BNC_LIBRO_BANCO b
                ON b.ID_LIBRO_BANCO=d.ID_LIBRO_BANCO WHERE b.CODIGO_SISTEMA=11 AND b.ID_TRANSACCION='00002'"""),
            ("issued", "VAULT_BANK_DETAIL", """SELECT d.ID_LIBRO_BANCO source_id,d.ID_DET_BANCO p1
                FROM dbo.BVD_DET_BANCO d JOIN dbo.BNC_LIBRO_BANCO b ON b.ID_LIBRO_BANCO=d.ID_LIBRO_BANCO
                WHERE b.CODIGO_SISTEMA=11 AND b.ID_TRANSACCION='00002'"""),
            ("issued", "SAVINGS_MOVEMENT", """SELECT m.ID_LIBRO_BANCO source_id,m.ID_AHO_MOVIMIENTO p1
                FROM dbo.AHO_MOVIMIENTOS m JOIN dbo.BNC_LIBRO_BANCO b ON b.ID_LIBRO_BANCO=m.ID_LIBRO_BANCO
                WHERE b.CODIGO_SISTEMA=11 AND b.ID_TRANSACCION='00002'"""),
            ("issued", "LOAN_LIQUIDATION", """SELECT d.ID_LIBRO_BANCO source_id,d.ID_EMPRESA p1,
                d.ID_SUCURSAL p2,d.ID_LIQUIDACION p3,d.ID_DETALLE_LIQ p4
                FROM dbo.CRD_DET_LIQUIDACION d JOIN dbo.BNC_LIBRO_BANCO b ON b.ID_LIBRO_BANCO=d.ID_LIBRO_BANCO
                WHERE b.CODIGO_SISTEMA=11 AND b.ID_TRANSACCION='00002'"""),
            ("received", "LOAN_MOVEMENT", """SELECT m.ID_REF_CHEQUE source_id,m.ID_MOVIMIENTO_CARTERA p1
                FROM dbo.CRD_MOVIMIENTOS_CARTERA m WHERE m.ID_REF_CHEQUE>0"""),
            ("received", "SAVINGS_MOVEMENT", """SELECT m.ID_REF_CHEQUE source_id,m.ID_AHO_MOVIMIENTO p1
                FROM dbo.AHO_MOVIMIENTOS m WHERE m.ID_REF_CHEQUE>0"""),
            ("received", "CASHIER_MOVEMENT", """SELECT m.ID_REF_CHEQUE source_id,m.ID_EMPRESA p1,
                m.ID_SUCURSAL p2,m.CODIGO_SISTEMA p3,m.ID_MOVIMIENTO p4,m.ID_CAJA p5
                FROM dbo.CAJA_MOVIMIENTOS m WHERE m.ID_REF_CHEQUE>0"""),
            ("received", "COMBINED_PAYMENT", """SELECT p.ID_REF_CHEQUE source_id,p.ID_PAGO_COMBINADO p1
                FROM dbo.CNT_PAGO_COMBINADO p WHERE p.ID_REF_CHEQUE>0"""),
            ("received", "LOAN_MOVEMENT", """SELECT p.ID_REF_CHEQUE source_id,m.ID_MOVIMIENTO_CARTERA p1
                FROM dbo.CNT_PAGO_COMBINADO p JOIN dbo.CRD_MOVIMIENTOS_CARTERA m
                  ON p.CODIGO_SISTEMA=4 AND m.ID_CRD_MOVIMIENTO=p.ID_MOVIMIENTO
                WHERE p.ID_REF_CHEQUE>0"""),
            ("received", "SAVINGS_MOVEMENT", """SELECT p.ID_REF_CHEQUE source_id,m.ID_AHO_MOVIMIENTO p1
                FROM dbo.CNT_PAGO_COMBINADO p JOIN dbo.AHO_MOVIMIENTOS m
                  ON p.CODIGO_SISTEMA=5 AND m.ID_AHO_MOVIMIENTO=p.ID_MOVIMIENTO
                WHERE p.ID_REF_CHEQUE>0"""),
        )
        collected: dict[tuple[str, int], dict[tuple[str, str], Link]] = {}
        for kind, relationship, query in specs:
            for row in select_rows(source, query):
                source_id = int(row["source_id"])
                if (kind, source_id) not in eligible:
                    continue
                source_key = "|".join(_part(row[name]) for name in ("p1", "p2", "p3", "p4", "p5") if name in row)
                link = Link(relationship, source_key)
                collected.setdefault((kind, source_id), {})[link.key] = link
    result = []
    for kind, rows in (("issued", issued), ("received", received)):
        for row in rows:
            key = kind, int(row["source_id"])
            result.append(_make_cheque(kind, row, list(collected.pop(key, {}).values())))
    if collected:
        raise RuntimeError("Cheque relationships point to missing source cheque records")
    if not result or len({row.key for row in result}) != len(result):
        raise RuntimeError("Empty or duplicate Arissto cheque population")
    return sorted(result, key=lambda row: row.key)


def _target_link_catalog(conn: Any) -> dict[tuple[str, str], tuple[str, str]]:
    mapping: dict[tuple[str, str], tuple[str, str]] = {}
    for company, branch, period, journal, line, target in conn.execute("""
        SELECT h.source_company_id,h.source_branch_id,h.source_period_id,h.source_journal_id,
               l.source_line_id,e.transaction_id
          FROM credesal_arissto_gl_journal_line l
          JOIN credesal_arissto_gl_journal h ON h.id=l.journal_provenance_id
          JOIN acc_gl_journal_entry e ON e.id=l.target_journal_entry_id
         WHERE l.target_journal_entry_id IS NOT NULL
    """):
        key = "|".join(_part(v) for v in (company, branch, period, journal, line))
        mapping[("GL_LINE", key)] = ("gl_journal", str(target))
    for external, target, loan_id, client_id in conn.execute("""
        SELECT t.external_id,t.id,t.loan_id,l.client_id FROM m_loan_transaction t
          JOIN m_loan l ON l.id=t.loan_id
         WHERE t.external_id LIKE 'ARISSTO:CRD-MOV:%%'
    """):
        key = str(external).removeprefix("ARISSTO:CRD-MOV:")
        mapping[("LOAN_MOVEMENT", key)] = ("loan_transaction", f"{client_id}|{loan_id}|{target}")
    # One Arissto savings movement may create several native events. Only an
    # unambiguous single target transaction is linkable.
    savings: dict[str, set[str]] = {}
    for key, target, account_id, client_id in conn.execute("""
        SELECT event.source_key,t.id,t.savings_account_id,a.client_id
          FROM credesal_savings_native_event_map event
          JOIN m_savings_account_transaction t ON t.id=event.savings_transaction_id
          JOIN m_savings_account a ON a.id=t.savings_account_id
         WHERE event.source_table='AHO_MOVIMIENTOS' AND event.event_status='APPLIED'
    """):
        savings.setdefault(str(key).removeprefix("AHO_MOVIMIENTOS|"), set()).add(f"{client_id}|{account_id}|{target}")
    for key, targets in savings.items():
        if len(targets) == 1:
            mapping[("SAVINGS_MOVEMENT", key)] = ("savings_transaction", next(iter(targets)))
    return mapping


def _with_target_links(rows: list[Cheque], catalog: dict[tuple[str, str], tuple[str, str]]) -> list[Cheque]:
    return [replace(row, links=tuple(replace(link, target_type=(match[0] if match else None),
                                           target_id=(match[1] if match else None))
                                    for link in row.links
                                    for match in (catalog.get(link.key),))) for row in rows]


def _existing(conn: Any) -> dict[tuple[str, int], tuple[Any, ...]]:
    result: dict[tuple[str, int], tuple[Any, ...]] = {}
    links: dict[int, list[Link]] = {}
    for cheque_id, relationship, source_key, target_type, target_id in conn.execute("""
        SELECT cheque_id,relationship_type,source_key,target_type,target_id
          FROM credesal_historical_cheque_link
    """):
        links.setdefault(int(cheque_id), []).append(Link(relationship, source_key, target_type, target_id))
    for identifier, kind, source_id, number, bank, amount, cheque_date, cancelled, source_hash, fingerprint in conn.execute("""
        SELECT id,source_kind,source_id,cheque_number,bank_name,amount,cheque_date,
               cancelled,source_hash,source_fingerprint
          FROM credesal_historical_cheque
    """):
        result[(kind, int(source_id))] = (int(identifier), source_hash, fingerprint,
                                          tuple(sorted(links.get(int(identifier), []), key=lambda link: link.key)),
                                          number, bank, _money(amount), _day(cheque_date), cancelled)
    return result


def _comparison(rows: list[Cheque], existing: dict[tuple[str, int], tuple[Any, ...]],
                fingerprint: str) -> dict[str, Any]:
    wanted = {row.key: row for row in rows}
    if set(existing) - set(wanted):
        raise RuntimeError("Target contains historical cheque keys absent from the current Arissto snapshot")
    create: list[Cheque] = []
    link_updates: list[tuple[int, Cheque]] = []
    unchanged = 0
    conflicts = 0
    for row in rows:
        target = existing.get(row.key)
        if target is None:
            create.append(row)
        elif (target[1] != row.source_hash or target[2] != fingerprint
              or target[4:] != (row.number, row.bank, row.amount, row.cheque_date, row.cancelled)):
            conflicts += 1
        elif target[3] != row.links:
            if {link.key for link in target[3]} != {link.key for link in row.links}:
                conflicts += 1
            else:
                link_updates.append((target[0], row))
        else:
            unchanged += 1
    return {"create": create, "link_updates": link_updates, "unchanged": unchanged, "conflicts": conflicts}


def _snapshot(settings: Settings, conn: Any, source_through_date: str) -> tuple[list[Cheque], dict[str, Any], str, str]:
    if conn.execute("SELECT to_regclass('public.credesal_historical_cheque') IS NULL").fetchone()[0]:
        raise RuntimeError("Fineract historical cheque migration 0397 has not run")
    rows = _with_target_links(_extract(settings, source_through_date), _target_link_catalog(conn))
    existing = _existing(conn)
    comparison = _comparison(rows, existing, source_fingerprint(settings.source))
    source_digest = _digest([(row.key, row.source_hash) for row in rows])
    target_digest = _digest([(key, value) for key, value in sorted(existing.items())])
    return rows, comparison, source_digest, target_digest


def _summary(rows: list[Cheque], comparison: dict[str, Any], source_digest: str, target_digest: str,
             settings: Settings, source_through_date: str) -> dict[str, Any]:
    issued = sum(row.kind == "issued" for row in rows)
    fineract_starts = (date.fromisoformat(source_through_date) + timedelta(days=1)).isoformat()
    return {"version": 2, "block": BLOCK, "arissto_through": source_through_date,
            "fineract_starts": fineract_starts, "issued": issued, "received": len(rows) - issued,
            "relationship_count": sum(len(row.links) for row in rows),
            "resolved_relationship_count": sum(link.target_id is not None for row in rows for link in row.links),
            "create_count": len(comparison["create"]), "link_update_count": len(comparison["link_updates"]),
            "unchanged_count": comparison["unchanged"], "conflict_count": comparison["conflicts"],
            "source_hash": source_digest, "target_hash": target_digest,
            "target_fingerprint": settings.target.fingerprint}


def inspect(settings: Settings, source_through_date: str) -> dict[str, Any]:
    settings.target.assert_expected_host()
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for cheque history inspection")
    with postgres_connection(settings.target.pg_url) as conn:
        rows, comparison, source_digest, target_digest = _snapshot(settings, conn, source_through_date)
    return _summary(rows, comparison, source_digest, target_digest, settings, source_through_date)


def build_plan(settings: Settings, state: State, source_through_date: str) -> tuple[str, dict[str, Any]]:
    frozen_through = state.accounting_cutoff.get("source_through_date")
    if frozen_through != source_through_date:
        if state.accounting_cutoff.get("configuration_hash"):
            raise RuntimeError("Cheque source date differs from the frozen workflow accounting boundary")
        state.set_accounting_source_through(source_through_date)
    document = inspect(settings, source_through_date)
    if document["conflict_count"]:
        raise RuntimeError("Existing historical cheque facts conflict with Arissto; review before planning")
    plan_id = state.save_plan(settings.target.fingerprint, BLOCK, source_fingerprint(settings.source), POLICY, document)
    return plan_id, document


def _plan(settings: Settings, state: State, plan_id: str) -> dict[str, Any]:
    plan = state.plan(plan_id)
    if (plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint
            or plan["source_fingerprint"] != source_fingerprint(settings.source)
            or plan["contract_hash"] != POLICY):
        raise RuntimeError("Cheque history plan belongs to another source, target, or contract")
    return plan


def _financial_totals(conn: Any) -> tuple[Any, ...]:
    journal = conn.execute("SELECT COUNT(*),COALESCE(SUM(amount),0) FROM acc_gl_journal_entry").fetchone()
    treasury = conn.execute("SELECT COUNT(*),COALESCE(SUM(balance),0) FROM m_treasury_bank_account").fetchone()
    return (*journal, *treasury)


def _write_links(conn: Any, cheque_id: int, links: tuple[Link, ...]) -> None:
    for link in links:
        conn.execute("""
            INSERT INTO credesal_historical_cheque_link
              (cheque_id,relationship_type,source_key,target_type,target_id)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (cheque_id,relationship_type,source_key) DO UPDATE
              SET target_type=EXCLUDED.target_type,target_id=EXCLUDED.target_id
        """, (cheque_id, link.relationship_type, link.source_key, link.target_type, link.target_id))


def apply_plan(settings: Settings, state: State, plan_id: str,
               confirmation: str | None = None) -> tuple[str, dict[str, int]]:
    settings.target.assert_expected_host()
    plan = _plan(settings, state, plan_id)
    if settings.target.name != "local":
        raise RuntimeError("Historical cheque service is in local acceptance testing")
    if settings.target.name == "prod" and confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for cheque history apply")
    run_id = state.start_run(plan)
    try:
        import psycopg
        with psycopg.connect(settings.target.pg_url, autocommit=False) as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            writer = ControlledSqlWriter(conn, BLOCK)
            with writer.entity_transaction(WRITE_OPERATION):
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (BLOCK,))
                source_through_date = plan["document"]["arissto_through"]
                rows, comparison, source_digest, target_digest = _snapshot(settings, conn, source_through_date)
                summary = _summary(rows, comparison, source_digest, target_digest, settings, source_through_date)
                planned = {key: value for key, value in plan["document"].items() if key != "accounting_cutoff"}
                if summary != planned or comparison["conflicts"]:
                    raise RuntimeError("Source or target changed since the reviewed cheque plan")
                financial_before = _financial_totals(conn)
                fingerprint = source_fingerprint(settings.source)
                for row in comparison["create"]:
                    cheque_id = conn.execute("""
                        INSERT INTO credesal_historical_cheque
                          (source_kind,source_id,cheque_number,bank_name,amount,cheque_date,
                           cancelled,source_hash,source_fingerprint)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                    """, (row.kind, row.source_id, row.number, row.bank, row.amount,
                          row.cheque_date, row.cancelled, row.source_hash, fingerprint)).fetchone()[0]
                    _write_links(conn, int(cheque_id), row.links)
                for cheque_id, row in comparison["link_updates"]:
                    _write_links(conn, cheque_id, row.links)
                after = _existing(conn)
                verified = _comparison(rows, after, fingerprint)
                if verified["create"] or verified["link_updates"] or verified["conflicts"] or verified["unchanged"] != len(rows):
                    raise RuntimeError("Historical cheque post-write verification failed")
                if _financial_totals(conn) != financial_before:
                    raise RuntimeError("Historical cheque import changed accounting or treasury totals")
        counts = {"created": len(comparison["create"]), "updated_links": len(comparison["link_updates"]),
                  "unchanged": comparison["unchanged"]}
        state.finish_run(run_id, "completed", counts)
        return run_id, counts
    except Exception as exc:
        state.finish_run(run_id, "failed", {"error": type(exc).__name__})
        raise


def reconcile(settings: Settings, state: State, run_id: str) -> dict[str, Any]:
    settings.target.assert_expected_host()
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Cheque history run belongs to another block or target")
    plan = _plan(settings, state, run["plan_id"])
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows, comparison, source_digest, _ = _snapshot(settings, conn, plan["document"]["arissto_through"])
    ok = (source_digest == plan["document"]["source_hash"] and not comparison["create"]
          and not comparison["link_updates"] and comparison["conflicts"] == 0
          and comparison["unchanged"] == len(rows))
    result = {"ok": ok, "issued": sum(row.kind == "issued" for row in rows),
              "received": sum(row.kind == "received" for row in rows),
              "verified": comparison["unchanged"], "missing": len(comparison["create"]),
              "link_updates": len(comparison["link_updates"]), "conflicts": comparison["conflicts"]}
    state.record_reconciliation(run_id, result)
    return result
