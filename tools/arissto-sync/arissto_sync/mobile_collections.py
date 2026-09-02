from __future__ import annotations

import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from .arissto import IDENTIFIER, select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import postgres_connection, postgres_schema
from .sql_writer import ControlledSqlWriter
from .state import State


BLOCK = "mobile-collections"
OPERATION = "upsert_mobile_collection_metadata"
ENTITY_ORDER = ("route", "assignment", "account", "batch", "item")

TABLES = {
    "route": "credesal_mobile_collection_route",
    "assignment": "credesal_mobile_collection_assignment",
    "account": "credesal_mobile_collection_account_assignment",
    "batch": "credesal_mobile_collection_batch",
    "item": "credesal_mobile_collection_item",
}
CONFLICT_COLUMNS = {
    "route": ("arissto_route_id",),
    "assignment": ("arissto_assignment_id",),
    "account": ("arissto_account_id",),
    "batch": ("arissto_master_id",),
    "item": (
        "arissto_company_id", "arissto_branch_id", "arissto_period_id",
        "arissto_collection_id", "arissto_collection_item_id",
    ),
}
COLUMNS = {
    "route": (
        "arissto_route_id", "arissto_company_id", "arissto_branch_id", "office_id",
        "arissto_responsible_person_id", "responsible_staff_id", "route_name", "source_status",
    ),
    "assignment": ("arissto_assignment_id", "route_id", "arissto_associate_id", "client_id"),
    "account": (
        "arissto_account_id", "route_id", "arissto_operational_client_id", "client_id",
        "arissto_product_type_id", "arissto_transaction_id", "arissto_account_number",
        "account_type", "loan_id", "savings_account_id", "link_status",
    ),
    "batch": (
        "arissto_master_id", "arissto_company_id", "arissto_branch_id", "arissto_period_id",
        "arissto_collection_id", "office_id", "arissto_responsible_person_id",
        "responsible_staff_id", "arissto_promoter_person_id", "promoter_staff_id", "source_date",
        "collection_date", "observation", "arissto_daily_close_id", "arissto_collection_close_id",
        "arissto_remittance_close_id", "source_total", "source_difference", "source_remitted",
        "source_status", "source_created_at", "source_updated_at",
    ),
    "item": (
        "batch_id", "arissto_company_id", "arissto_branch_id", "arissto_period_id",
        "arissto_collection_id", "arissto_collection_item_id", "arissto_detail_id",
        "arissto_member_branch_id", "arissto_member_id", "client_id",
        "arissto_promoter_person_id", "promoter_staff_id", "arissto_account_number", "loan_id",
        "loan_transaction_id", "link_status", "source_amount", "source_receipt_number",
        "arissto_receipt_book_id", "arissto_receipt_stub", "source_movement_date",
        "arissto_daily_close_id", "source_system_code", "source_transaction_code", "source_applied",
        "source_apply_requested", "source_verified", "source_inconsistency", "collected_at", "loaded_at",
        "applied_at", "arissto_mcd_movement_id", "arissto_loan_movement_id", "source_created_at",
        "source_updated_at",
    ),
}


def clean(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(type(value).__name__)


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(_canonical(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class MobileCollectionContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "MobileCollectionContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("version") != 1:
            raise ValueError("Unsupported mobile collections contract version")
        if value.get("depends_on") != ["clients", "employees", "savings-deposits", "loans"]:
            raise ValueError("Mobile collections dependency order is not the reviewed order")
        source, target = value.get("source", {}), value.get("target", {})
        identifiers = [*source.values(), *(target.get(f"{entity}_table") for entity in ENTITY_ORDER)]
        if not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Unsafe table identifier in mobile collections contract")
        expected_source = {
            "route_table": "MCD_RUTA", "assignment_table": "MCD_ASIGNACION_RUTA",
            "account_table": "cuenta", "batch_table": "MCD_MST_COBRODIARIO",
            "item_table": "MCD_MOV_COBRODIARIO", "movement_table": "MCD_MOVIMIENTOS",
        }
        if source != expected_source:
            raise ValueError("Mobile collections source table contract changed")
        if {entity: target.get(f"{entity}_table") for entity in ENTITY_ORDER} != TABLES:
            raise ValueError("Mobile collections target table contract changed")
        if value.get("write_policy") != {
            "extension_tables": "controlled-parameterized-sql-only",
            "native_financial_tables": "forbidden",
            "delete": "forbidden",
        }:
            raise ValueError("Mobile collections write boundary changed")
        offices = target.get("office_mapping")
        if not isinstance(offices, dict) or any(not clean(key) or int(item) <= 0 for key, item in offices.items()):
            raise ValueError("Mobile collections office mapping is invalid")
        return cls(value)

    @property
    def contract_hash(self) -> str:
        return _hash(self.raw)

    @property
    def office_mapping(self) -> dict[str, int]:
        return {clean(key) or "": int(value) for key, value in self.raw["target"]["office_mapping"].items()}

    def source_hash(self, entity: str, row: dict[str, Any]) -> str:
        return _hash({"contract": self.contract_hash, "entity": entity, "source": row})


SOURCE_QUERIES = {
    "route": """
        SELECT ID_RUTA AS route_id,ID_EMPRESA AS company_id,ID_SUCURSAL AS branch_id,
               ID_PERSONA AS responsible_person_id,RUTA AS route_name,ESTADO AS source_status
        FROM dbo.MCD_RUTA ORDER BY ID_RUTA
    """,
    "assignment": """
        SELECT a.ID_ASIGNACION_RUTA AS assignment_id,a.ID_ASOCIADO AS associate_id,a.ID_RUTA AS route_id,
               s.NUMERO_AFILIACION AS client_external_id
        FROM dbo.MCD_ASIGNACION_RUTA a
        OUTER APPLY (
          SELECT TOP 1 x.NUMERO_AFILIACION FROM dbo.AFI_SOCIO x
          WHERE TRY_CONVERT(INT,x.ID_SOCIO)=a.ID_ASOCIADO
          ORDER BY CASE WHEN x.ID_EMPRESA='001' THEN 0 ELSE 1 END,x.ID_SUCURSAL
        ) s
        ORDER BY a.ID_ASIGNACION_RUTA
    """,
    "account": """
        SELECT c.id_cuenta AS account_id,c.id_tipo_producto AS product_type_id,
               c.id_cliente AS operational_client_id,c.id_ruta AS route_id,
               c.id_transaccion AS transaction_id,c.numero_cuenta AS account_number,
               tp.TIPO_PRODUCTO AS account_type,c2.numero_cliente AS client_external_id,
               cr.ID_CREDITO AS credit_id,sa.ID_EMPRESA AS savings_company_id,
               sa.ID_SUCURSAL AS savings_branch_id,sa.ID_CUENTA_AHORRO AS savings_account_number
        FROM dbo.cuenta c
        JOIN dbo.TIPO_PRODUCTO tp ON tp.ID_TIPO_PRODUCTO=c.id_tipo_producto
        JOIN dbo.cliente2 c2 ON c2.id_cliente=c.id_cliente
        OUTER APPLY (
          SELECT TOP 1 x.ID_CREDITO FROM dbo.CRD_CARTERA x WHERE x.NO_PRESTAMO=c.numero_cuenta
          ORDER BY x.ID_CREDITO
        ) cr
        OUTER APPLY (
          SELECT TOP 1 x.ID_EMPRESA,x.ID_SUCURSAL,x.ID_CUENTA_AHORRO
          FROM dbo.AHO_CUENTA_AHORRO x WHERE x.NO_CUENTA=c.numero_cuenta
          ORDER BY x.ID_EMPRESA,x.ID_SUCURSAL
        ) sa
        ORDER BY c.id_cuenta
    """,
    "batch": """
        SELECT ID_MST_COBRODIARIO AS master_id,ID_EMPRESA AS company_id,ID_SUCURSAL AS branch_id,
               ID_PERIODO AS period_id,ID_COBRODIARIO AS collection_id,
               ID_PERSONA_RESPONSABLE AS responsible_person_id,ID_PROMOTOR AS promoter_person_id,
               FECHA AS source_date,FECHA_COBRO AS collection_date,OBSERVACION AS observation,
               ID_CIERRE_DIARIO AS daily_close_id,ID_CIERRE_COBRO AS collection_close_id,
               ID_CIERRE_REMESA AS remittance_close_id,TOTAL AS source_total,DIFERENCIA AS source_difference,
               REMESADO AS source_remitted,ESTADO AS source_status,DT_CREO AS source_created_at,
               DT_MOD AS source_updated_at
        FROM dbo.MCD_MST_COBRODIARIO ORDER BY ID_MST_COBRODIARIO
    """,
    "item": """
        SELECT d.ID_EMPRESA AS company_id,d.ID_SUCURSAL AS branch_id,d.ID_PERIODO AS period_id,
               d.ID_COBRODIARIO AS collection_id,d.ID_MOV_COBRODIARIO AS collection_item_id,
               d.ID_DET_COBRODIARIO AS detail_id,d.ID_MST_COBRODIARIO AS master_id,
               d.ID_SUCURSAL_SOCIO AS member_branch_id,d.ID_SOCIO AS member_id,
               s.NUMERO_AFILIACION AS client_external_id,d.ID_PROMOTOR AS promoter_person_id,
               d.NUM_CUENTA AS account_number,d.MONTO AS source_amount,d.NUM_COMPROBANTE AS receipt_number,
               d.ID_TALONARIO AS receipt_book_id,d.NO_TALON AS receipt_stub,d.FECHA_MOV AS movement_date,
               d.ID_CIERRE_DIARIO AS daily_close_id,d.CODIGO_SISTEMA AS system_code,
               d.ID_TRANSACCION AS transaction_code,d.APLICADO AS applied,d.APLICAR AS apply_requested,
               d.VERIFICADO AS verified,d.INCONSISTENCIA AS inconsistency,d.DT_COBRO AS collected_at,
               d.DT_CARGA AS loaded_at,d.DT_APLICACION AS applied_at,d.ID_MCD_MOVIMIENTO AS mcd_movement_id,
               m.ID_MOVIMIENTO_CARTERA AS loan_movement_id,m.MONTO AS bridge_amount,
               cr.ID_CREDITO AS credit_id,d.DT_CREO AS source_created_at,d.DT_MOD AS source_updated_at
        FROM dbo.MCD_MOV_COBRODIARIO d
        LEFT JOIN dbo.AFI_SOCIO s ON s.ID_EMPRESA=d.ID_EMPRESA
          AND s.ID_SUCURSAL=d.ID_SUCURSAL_SOCIO AND s.ID_SOCIO=d.ID_SOCIO
        LEFT JOIN dbo.MCD_MOVIMIENTOS m ON m.ID_MCD_MOVIMIENTO=d.ID_MCD_MOVIMIENTO
        OUTER APPLY (
          SELECT TOP 1 x.ID_CREDITO FROM dbo.CRD_CARTERA x WHERE x.NO_PRESTAMO=d.NUM_CUENTA
          ORDER BY x.ID_CREDITO
        ) cr
        ORDER BY d.ID_EMPRESA,d.ID_SUCURSAL,d.ID_PERIODO,d.ID_COBRODIARIO,d.ID_MOV_COBRODIARIO
    """,
}


def source_key(entity: str, row: dict[str, Any]) -> str:
    if entity == "route":
        value = clean(row.get("route_id"))
    elif entity == "assignment":
        value = clean(row.get("assignment_id"))
    elif entity == "account":
        value = clean(row.get("account_id"))
    elif entity == "batch":
        value = clean(row.get("master_id"))
    else:
        parts = [clean(row.get(name)) for name in (
            "company_id", "branch_id", "period_id", "collection_id", "collection_item_id"
        )]
        value = "|".join(item or "" for item in parts)
    if not value or (entity == "item" and "||" in f"|{value}|"):
        raise ValueError(f"Missing {entity} source identity")
    return f"{entity}:{value}"


def extract_mobile_collections(settings: Settings) -> dict[str, list[dict[str, Any]]]:
    with source_connection(settings.source) as conn:
        return {entity: select_rows(conn, SOURCE_QUERIES[entity]) for entity in ENTITY_ORDER}


def _pg_dicts(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _unique_index(rows: list[tuple[Any, ...]], label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in rows:
        key = clean(value[1])
        if not key:
            continue
        if key in result:
            raise RuntimeError(f"Duplicate target {label} identity")
        result[key] = value[0] if len(value) == 2 else value
    return result


def _target_catalog(conn: Any) -> dict[str, Any]:
    catalog: dict[str, Any] = {
        "clients": _unique_index(conn.execute(
            "SELECT id,external_id FROM m_client WHERE external_id IS NOT NULL"
        ).fetchall(), "client"),
        "staff": _unique_index(conn.execute(
            "SELECT id,external_id FROM m_staff WHERE external_id IS NOT NULL"
        ).fetchall(), "staff"),
        "loans": _unique_index(conn.execute(
            "SELECT id,external_id FROM m_loan WHERE external_id IS NOT NULL"
        ).fetchall(), "loan"),
        "savings": _unique_index(conn.execute(
            "SELECT id,external_id FROM m_savings_account WHERE external_id IS NOT NULL"
        ).fetchall(), "savings account"),
        "transactions": {},
        "offices": {int(row[0]) for row in conn.execute("SELECT id FROM m_office").fetchall()},
        "existing": {},
    }
    for row in conn.execute(
        "SELECT id,external_id,loan_id,amount FROM m_loan_transaction WHERE external_id IS NOT NULL"
    ).fetchall():
        key = clean(row[1])
        if key in catalog["transactions"]:
            raise RuntimeError("Duplicate target loan transaction identity")
        catalog["transactions"][key] = {"id": int(row[0]), "loan_id": int(row[2]), "amount": row[3]}
    for entity in ENTITY_ORDER:
        table, columns = TABLES[entity], COLUMNS[entity]
        rows = _pg_dicts(conn, f"SELECT id,{','.join(columns)} FROM {table}")
        migrated: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                migrated[source_key(entity, _target_source_row(entity, row))] = row
            except ValueError:
                # Native API-created routes/assignments intentionally have no Arissto identity.
                if entity not in {"route", "assignment"}:
                    raise
        catalog["existing"][entity] = migrated
    catalog["route_ids"] = {
        clean(row["arissto_route_id"]): int(row["id"])
        for row in catalog["existing"]["route"].values()
    }
    catalog["batch_ids"] = {
        clean(row["arissto_master_id"]): int(row["id"])
        for row in catalog["existing"]["batch"].values()
    }
    return catalog


def _target_source_row(entity: str, row: dict[str, Any]) -> dict[str, Any]:
    if entity == "route": return {"route_id": row["arissto_route_id"]}
    if entity == "assignment": return {"assignment_id": row["arissto_assignment_id"]}
    if entity == "account": return {"account_id": row["arissto_account_id"]}
    if entity == "batch": return {"master_id": row["arissto_master_id"]}
    return {
        "company_id": row["arissto_company_id"], "branch_id": row["arissto_branch_id"],
        "period_id": row["arissto_period_id"], "collection_id": row["arissto_collection_id"],
        "collection_item_id": row["arissto_collection_item_id"],
    }


def _staff(catalog: dict[str, Any], company: Any, person: Any) -> int | None:
    company_id, person_id = clean(company), clean(person)
    if not company_id or not person_id:
        return None
    value = catalog["staff"].get(f"{company_id}:{person_id}")
    return int(value) if value is not None else None


def _payload(entity: str, row: dict[str, Any], contract: MobileCollectionContract,
             catalog: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    company, branch = clean(row.get("company_id")), clean(row.get("branch_id"))
    if entity == "route":
        office = contract.office_mapping.get(branch or "")
        return {
            "arissto_route_id": int(row["route_id"]), "arissto_company_id": company,
            "arissto_branch_id": branch, "office_id": office,
            "arissto_responsible_person_id": clean(row.get("responsible_person_id")),
            "responsible_staff_id": _staff(catalog, company, row.get("responsible_person_id")),
            "route_name": clean(row.get("route_name")), "source_status": clean(row.get("source_status")),
        }, None if office else "unmapped_office"
    if entity == "assignment":
        route_id = catalog["route_ids"].get(clean(row.get("route_id")))
        client_id = catalog["clients"].get(clean(row.get("client_external_id")))
        if route_id is None: return None, "missing_target_route"
        if client_id is None: return None, "missing_target_client"
        return {
            "arissto_assignment_id": int(row["assignment_id"]), "route_id": int(route_id),
            "arissto_associate_id": int(row["associate_id"]), "client_id": int(client_id),
        }, None
    if entity == "account":
        route_id = catalog["route_ids"].get(clean(row.get("route_id")))
        client_id = catalog["clients"].get(clean(row.get("client_external_id")))
        if route_id is None: return None, "missing_target_route"
        if client_id is None: return None, "missing_target_client"
        account_type = clean(row.get("account_type")) or "UNKNOWN"
        loan_id = savings_id = None
        if account_type == "CREDITOS" and clean(row.get("credit_id")):
            loan_id = catalog["loans"].get(f"ARISSTO:CRD:{clean(row['credit_id'])}")
        elif account_type == "AHORROS" and clean(row.get("savings_account_number")):
            ext = "arissto:savings:" + ":".join(clean(row.get(name)) or "" for name in (
                "savings_company_id", "savings_branch_id", "savings_account_number"
            ))
            savings_id = catalog["savings"].get(ext)
        linked = loan_id is not None or savings_id is not None
        return {
            "arissto_account_id": int(row["account_id"]), "route_id": int(route_id),
            "arissto_operational_client_id": int(row["operational_client_id"]), "client_id": int(client_id),
            "arissto_product_type_id": int(row["product_type_id"]),
            "arissto_transaction_id": int(row["transaction_id"]),
            "arissto_account_number": clean(row.get("account_number")), "account_type": account_type,
            "loan_id": int(loan_id) if loan_id is not None else None,
            "savings_account_id": int(savings_id) if savings_id is not None else None,
            "link_status": "LINKED" if linked else "UNRESOLVED_TARGET_ACCOUNT",
        }, None
    if entity == "batch":
        office = contract.office_mapping.get(branch or "")
        return {
            "arissto_master_id": int(row["master_id"]), "arissto_company_id": company,
            "arissto_branch_id": branch, "arissto_period_id": clean(row.get("period_id")),
            "arissto_collection_id": clean(row.get("collection_id")), "office_id": office,
            "arissto_responsible_person_id": clean(row.get("responsible_person_id")),
            "responsible_staff_id": _staff(catalog, company, row.get("responsible_person_id")),
            "arissto_promoter_person_id": clean(row.get("promoter_person_id")),
            "promoter_staff_id": _staff(catalog, company, row.get("promoter_person_id")),
            "source_date": row.get("source_date"), "collection_date": row.get("collection_date"),
            "observation": row.get("observation"), "arissto_daily_close_id": clean(row.get("daily_close_id")),
            "arissto_collection_close_id": clean(row.get("collection_close_id")),
            "arissto_remittance_close_id": clean(row.get("remittance_close_id")),
            "source_total": row.get("source_total"), "source_difference": row.get("source_difference"),
            "source_remitted": row.get("source_remitted"), "source_status": clean(row.get("source_status")),
            "source_created_at": row.get("source_created_at"), "source_updated_at": row.get("source_updated_at"),
        }, None if office else "unmapped_office"
    batch_id = catalog["batch_ids"].get(clean(row.get("master_id")))
    if batch_id is None:
        return None, "missing_target_batch"
    client_id = catalog["clients"].get(clean(row.get("client_external_id")))
    loan_id = catalog["loans"].get(f"ARISSTO:CRD:{clean(row.get('credit_id'))}") if clean(row.get("credit_id")) else None
    movement_id = clean(row.get("loan_movement_id"))
    transaction = catalog["transactions"].get(f"ARISSTO:CRD-MOV:{movement_id}") if movement_id else None
    applied = (clean(row.get("applied")) or "").upper() in {"S", "Y", "1"}
    requested = (clean(row.get("apply_requested")) or "").upper() in {"S", "Y", "1"}
    if transaction:
        link_status, loan_id = "LINKED", transaction["loan_id"]
    elif movement_id:
        link_status = "MISSING_REPAYMENT"
    elif applied:
        link_status = "UNRESOLVED_LEGACY"
    elif requested:
        link_status = "PENDING"
    else:
        link_status = "NOT_APPLICABLE"
    return {
        "batch_id": int(batch_id), "arissto_company_id": company, "arissto_branch_id": branch,
        "arissto_period_id": clean(row.get("period_id")), "arissto_collection_id": clean(row.get("collection_id")),
        "arissto_collection_item_id": clean(row.get("collection_item_id")),
        "arissto_detail_id": int(row["detail_id"]), "arissto_member_branch_id": clean(row.get("member_branch_id")),
        "arissto_member_id": clean(row.get("member_id")),
        "client_id": int(client_id) if client_id is not None else None,
        "arissto_promoter_person_id": clean(row.get("promoter_person_id")),
        "promoter_staff_id": _staff(catalog, company, row.get("promoter_person_id")),
        "arissto_account_number": clean(row.get("account_number")),
        "loan_id": int(loan_id) if loan_id is not None else None,
        "loan_transaction_id": int(transaction["id"]) if transaction else None, "link_status": link_status,
        "source_amount": row.get("source_amount"), "source_receipt_number": row.get("receipt_number"),
        "arissto_receipt_book_id": clean(row.get("receipt_book_id")),
        "arissto_receipt_stub": clean(row.get("receipt_stub")), "source_movement_date": row.get("movement_date"),
        "arissto_daily_close_id": clean(row.get("daily_close_id")),
        "source_system_code": int(row["system_code"]) if row.get("system_code") is not None else None,
        "source_transaction_code": clean(row.get("transaction_code")), "source_applied": clean(row.get("applied")),
        "source_apply_requested": clean(row.get("apply_requested")), "source_verified": clean(row.get("verified")),
        "source_inconsistency": clean(row.get("inconsistency")), "collected_at": row.get("collected_at"),
        "loaded_at": row.get("loaded_at"), "applied_at": row.get("applied_at"),
        "arissto_mcd_movement_id": row.get("mcd_movement_id"),
        "arissto_loan_movement_id": movement_id, "source_created_at": row.get("source_created_at"),
        "source_updated_at": row.get("source_updated_at"),
    }, None


def _payload_matches(current: dict[str, Any], payload: dict[str, Any], columns: tuple[str, ...]) -> bool:
    return _canonical({key: current.get(key) for key in columns}) == _canonical(payload)


def _schema_signature(source_schema: dict[str, Any], target_schema: dict[str, Any]) -> str:
    return _hash({"source": source_schema, "target": target_schema})


def inspect_mobile_collections(settings: Settings, contract: MobileCollectionContract) -> dict[str, Any]:
    blockers: list[Any] = []
    source_schema: dict[str, Any] = {}
    counts: dict[str, int] = {}
    try:
        with source_connection(settings.source) as conn:
            for entity in ENTITY_ORDER:
                rows = select_rows(conn, SOURCE_QUERIES[entity])
                counts[entity] = len(rows)
                source_schema[entity] = sorted(rows[0]) if rows else []
    except Exception as exc:
        blockers.append({"source_extraction": type(exc).__name__})
    target_schema: dict[str, Any] = {}
    target_counts: dict[str, int] = {}
    if not settings.target.pg_url:
        blockers.append({"target": "postgres_inspection_required"})
    else:
        try:
            with postgres_connection(settings.target.pg_url) as conn:
                target_schema = postgres_schema(conn, list(TABLES.values()))
                for entity, table in TABLES.items():
                    missing = sorted({"id", *COLUMNS[entity]} - set(target_schema.get(table, {})))
                    if missing:
                        blockers.append({"target_table": table, "missing_columns": missing})
                    else:
                        target_counts[entity] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                missing_offices = sorted(set(contract.office_mapping.values()) - {
                    int(row[0]) for row in conn.execute("SELECT id FROM m_office").fetchall()
                })
                if missing_offices:
                    blockers.append({"target_offices_missing": missing_offices})
        except Exception as exc:
            blockers.append({"target_inspection": type(exc).__name__})
    return {
        "block": BLOCK, "ready": not blockers, "target_fingerprint": settings.target.fingerprint,
        "contract_hash": contract.contract_hash, "schema_signature": _schema_signature(source_schema, target_schema),
        "depends_on": contract.raw["depends_on"], "source": {"counts": counts},
        "target": {"counts": target_counts}, "blockers": blockers,
        "financial_write_boundary": "no native repayment, journal, teller, or cashier writes",
    }


def build_mobile_collection_plan(settings: Settings, state: State, contract: MobileCollectionContract,
                                 source_keys: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    inspection = inspect_mobile_collections(settings, contract)
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for mobile collection planning")
    extracted = extract_mobile_collections(settings)
    wanted = set(source_keys or [])
    if wanted:
        known = {source_key(entity, row) for entity, rows in extracted.items() for row in rows}
        missing = sorted(wanted - known)
        if missing:
            raise ValueError(f"Unknown mobile collection source keys: {missing}")
    with postgres_connection(settings.target.pg_url) as conn:
        catalog = _target_catalog(conn)
    planning_catalog = dict(catalog)
    planning_catalog["route_ids"] = dict(catalog["route_ids"])
    planning_catalog["batch_ids"] = dict(catalog["batch_ids"])
    for row in extracted["route"]:
        planning_catalog["route_ids"].setdefault(clean(row["route_id"]), -1)
    for row in extracted["batch"]:
        planning_catalog["batch_ids"].setdefault(clean(row["master_id"]), -1)
    actions: list[dict[str, Any]] = []
    counts = Counter()
    for entity in ENTITY_ORDER:
        for row in extracted[entity]:
            key = source_key(entity, row)
            if wanted and key not in wanted:
                continue
            row_hash = contract.source_hash(entity, row)
            issue: str | None = None
            payload, issue = _payload(entity, row, contract, planning_catalog)
            current = catalog["existing"][entity].get(key)
            if issue:
                action = "quarantine"
            elif current is None:
                action = "create"
            elif payload is not None and _payload_matches(current, payload, COLUMNS[entity]):
                action = "unchanged"
            else:
                action = "update"
            item = {"entity": entity, "source_key": key, "source_hash": row_hash, "action": action,
                    "target_id": int(current["id"]) if current else None}
            if issue: item["reason"] = issue
            actions.append(item)
            counts[f"{entity}_{action}"] += 1
    document = {
        "version": 1, "block": BLOCK, "target_fingerprint": settings.target.fingerprint,
        "source_fingerprint": source_fingerprint(settings.source), "contract_hash": contract.contract_hash,
        "schema_signature": inspection["schema_signature"], "depends_on": contract.raw["depends_on"],
        "applicable": inspection["ready"], "readiness_blocker_count": len(inspection["blockers"]),
        "scope": {"mode": "explicit-source-keys" if wanted else "full-block", "entity_count": len(actions)},
        "counts": dict(counts), "actions": actions,
    }
    plan_id = state.save_plan(settings.target.fingerprint, BLOCK, document["source_fingerprint"],
                              contract.contract_hash, document)
    return plan_id, document


@contextmanager
def _write_connection(url: str) -> Iterator[Any]:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for mobile collection writes") from exc
    with psycopg.connect(url, autocommit=False) as conn:
        yield conn


def _upsert(conn: Any, entity: str, payload: dict[str, Any]) -> int:
    table, columns, conflict = TABLES[entity], COLUMNS[entity], CONFLICT_COLUMNS[entity]
    update_columns = [column for column in columns if column not in conflict]
    sql = (
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(['%s'] * len(columns))}) "
        f"ON CONFLICT ({','.join(conflict)}) DO UPDATE SET "
        + ",".join(f"{column}=EXCLUDED.{column}" for column in update_columns)
        + ",updated_at=CURRENT_TIMESTAMP RETURNING id"
    )
    return int(conn.execute(sql, tuple(payload[column] for column in columns)).fetchone()[0])


def _chunks(values: list[dict[str, Any]], size: int = 250) -> Iterator[list[dict[str, Any]]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def apply_mobile_collection_plan(settings: Settings, state: State, contract: MobileCollectionContract,
                                 plan_id: str, production_confirmation: str | None = None,
                                 only_keys: set[str] | None = None) -> tuple[str, dict[str, int]]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Plan belongs to a different block or target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source) or plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Plan is stale: source or mobile collection contract changed")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_mobile_collections(settings, contract)
    if not inspection["ready"] or not plan["document"].get("applicable"):
        raise RuntimeError("Mobile collection plan is not applicable")
    if inspection["schema_signature"] != plan["document"].get("schema_signature"):
        raise RuntimeError("Mobile collection destination readiness changed; apply refused")
    extracted = extract_mobile_collections(settings)
    source_rows = {
        source_key(entity, row): (entity, row) for entity, rows in extracted.items() for row in rows
    }
    selected = [item for item in plan["document"]["actions"]
                if only_keys is None or item["source_key"] in only_keys]
    run_id, counts = state.start_run(plan), Counter()
    with _write_connection(settings.target.pg_url or "") as conn:
        writer = ControlledSqlWriter(conn, BLOCK)
        catalog = _target_catalog(conn)
        for entity in ENTITY_ORDER:
            entity_actions = [item for item in selected if item["entity"] == entity]
            writable: list[dict[str, Any]] = []
            for action in entity_actions:
                key = action["source_key"]
                if action["action"] == "quarantine":
                    state.record_item(run_id, key, "quarantine", action["source_hash"], "quarantined",
                                      action.get("target_id"), f"MobileCollectionDataIssue:{action.get('reason')}")
                    counts["quarantined"] += 1
                    continue
                if action["action"] == "unchanged":
                    state.record_item(run_id, key, "unchanged", action["source_hash"], "unchanged",
                                      str(action.get("target_id")) if action.get("target_id") else None)
                    counts["unchanged"] += 1
                    continue
                current = source_rows.get(key)
                if not current or current[0] != entity or contract.source_hash(entity, current[1]) != action["source_hash"]:
                    state.record_item(run_id, key, action["action"], action["source_hash"], "failed",
                                      action.get("target_id"), "RuntimeError:source_changed_after_plan")
                    counts["failed"] += 1
                    continue
                payload, issue = _payload(entity, current[1], contract, catalog)
                if issue or payload is None:
                    state.record_item(run_id, key, action["action"], action["source_hash"], "failed",
                                      action.get("target_id"), f"MobileCollectionDataIssue:{issue}")
                    counts["failed"] += 1
                    continue
                writable.append({**action, "payload": payload})
            for chunk in _chunks(writable):
                written: list[tuple[dict[str, Any], int]] = []
                try:
                    with writer.entity_transaction(OPERATION):
                        for action in chunk:
                            written.append((action, _upsert(conn, entity, action["payload"])))
                except Exception as exc:
                    written = []
                    for action in chunk:
                        try:
                            with writer.entity_transaction(OPERATION):
                                target_id = _upsert(conn, entity, action["payload"])
                            written.append((action, target_id))
                        except Exception as item_exc:
                            state.record_item(run_id, action["source_key"], action["action"], action["source_hash"],
                                              "failed", action.get("target_id"),
                                              f"{type(item_exc).__name__}:redacted"[:240])
                            counts["failed"] += 1
                for action, target_id in written:
                    key = action["source_key"]
                    state.save_mapping(settings.target.fingerprint, BLOCK, key, str(target_id), action["source_hash"])
                    state.record_item(run_id, key, action["action"], action["source_hash"], "succeeded", str(target_id))
                    counts[action["action"]] += 1
                    catalog["existing"][entity][key] = {"id": target_id, **action["payload"]}
                    if entity == "route": catalog["route_ids"][clean(action["payload"]["arissto_route_id"])] = target_id
                    if entity == "batch": catalog["batch_ids"][clean(action["payload"]["arissto_master_id"])] = target_id
    status = "completed_with_errors" if counts["failed"] else (
        "completed_with_quarantine" if counts["quarantined"] else "completed"
    )
    state.finish_run(run_id, status, dict(counts))
    return run_id, dict(counts)


def reconcile_mobile_collections(settings: Settings, state: State, contract: MobileCollectionContract,
                                 run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Run belongs to a different block or target")
    plan = state.plan(run["plan_id"])
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Run belongs to a stale mobile collection contract")
    extracted = extract_mobile_collections(settings)
    source_rows = {source_key(entity, row): (entity, row) for entity, rows in extracted.items() for row in rows}
    results, links, dependency_links, amount_variances = Counter(), Counter(), Counter(), []
    batch_total_variances: list[dict[str, Any]] = []
    with postgres_connection(settings.target.pg_url or "") as conn:
        catalog = _target_catalog(conn)
        for item in state.run_items(run_id):
            if item["status"] in {"failed", "quarantined"}:
                results[item["status"]] += 1
                continue
            source = source_rows.get(item["source_key"])
            if not source or contract.source_hash(source[0], source[1]) != item["source_hash"]:
                results["source_changed"] += 1
                continue
            payload, issue = _payload(source[0], source[1], contract, catalog)
            current = catalog["existing"][source[0]].get(item["source_key"])
            matches = not issue and payload is not None and current is not None and _payload_matches(
                current, payload, COLUMNS[source[0]]
            )
            results["matched" if matches else "mismatched"] += 1
            if source[0] in {"account", "item"} and payload:
                links[f"{source[0]}:{payload['link_status']}"] += 1
            if source[0] == "route" and payload and payload.get("arissto_responsible_person_id"):
                dependency_links[
                    "route_staff_linked" if payload.get("responsible_staff_id") else "route_staff_unresolved"
                ] += 1
            if source[0] == "batch" and payload:
                for role in ("responsible", "promoter"):
                    if payload.get(f"arissto_{role}_person_id"):
                        dependency_links[
                            f"batch_{role}_staff_linked" if payload.get(f"{role}_staff_id")
                            else f"batch_{role}_staff_unresolved"
                        ] += 1
            if source[0] == "item" and payload and payload.get("loan_transaction_id"):
                transaction = catalog["transactions"].get(
                    f"ARISSTO:CRD-MOV:{clean(source[1].get('loan_movement_id'))}"
                )
                if transaction and source[1].get("source_amount") is not None:
                    difference = Decimal(str(source[1]["source_amount"])) - Decimal(str(transaction["amount"]))
                    if difference:
                        amount_variances.append({"source_key": item["source_key"], "difference": format(difference, "f")})
        for master_id, source_total, item_total, item_count in conn.execute("""
            SELECT b.arissto_master_id,b.source_total,COALESCE(SUM(i.source_amount),0),COUNT(i.id)
            FROM credesal_mobile_collection_batch b
            LEFT JOIN credesal_mobile_collection_item i ON i.batch_id=b.id
            GROUP BY b.id,b.arissto_master_id,b.source_total ORDER BY b.arissto_master_id
        """).fetchall():
            if source_total is not None:
                difference = Decimal(str(source_total)) - Decimal(str(item_total))
                if difference:
                    batch_total_variances.append({
                        "arissto_master_id": int(master_id), "difference": format(difference, "f"),
                        "item_count": int(item_count),
                    })
    failed_names = {"failed", "source_changed", "mismatched"}
    return {
        "run_id": run_id, "status": run["status"], "counts": dict(results), "link_statuses": dict(links),
        "dependency_links": dict(dependency_links),
        "batch_total_variance_count": len(batch_total_variances),
        "batch_total_variances": batch_total_variances[:100],
        "linked_repayment_amount_variance_count": len(amount_variances),
        "linked_repayment_amount_variances": amount_variances[:100],
        "financial_rows_created_by_this_service": 0,
        "ok": not any(results[name] for name in failed_names),
    }
