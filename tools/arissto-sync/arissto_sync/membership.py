from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .arissto import IDENTIFIER, select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import postgres_connection, postgres_schema
from .sql_writer import ControlledSqlWriter
from .state import State


BLOCK = "membership-share-capital"
SUMMARY_TABLE = "AFI_SOCIO_SUMMARY"
REQUIRED_ARCHIVE_COLUMNS = {
    "id", "source_table", "source_key", "client_id", "record_kind",
    "parent_source_key", "effective_date", "source_payload", "source_hash",
    "created_at", "updated_at",
}
REQUIRED_PROFILE_COLUMNS = {
    "client_id", "arissto_associate_id", "arissto_company_id", "arissto_branch_id",
    "arissto_member_id", "affiliation_number", "relationship_state_id",
    "relationship_state", "lifecycle_status_id", "lifecycle_status", "request_date",
    "initial_entry_date", "entry_date", "entry_approval_date", "entry_reason",
    "withdrawal_approval_date", "withdrawal_date", "withdrawal_reason", "entry_type",
    "common_share_count", "common_share_balance", "preferred_share_count",
    "preferred_share_balance", "subscribed_share_count", "subscribed_share_balance",
    "paid_share_count", "paid_share_balance", "common_subscribed_share_count",
    "common_paid_share_count", "preferred_subscribed_share_count",
    "preferred_paid_share_count", "certificate_count",
    "contribution_movement_count", "contribution_amount", "last_contribution_date",
    "source_hash", "created_at", "updated_at",
}
PROFILE_VALUE_COLUMNS = sorted(REQUIRED_PROFILE_COLUMNS - {"client_id", "created_at", "updated_at"})


class MembershipDataIssue(RuntimeError):
    """Non-sensitive reason why a membership source record is unsafe to synchronize."""


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    result = re.sub(r"\s+", " ", str(value).strip())
    return result or None


def date_value(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, float):
        return repr(value)
    return str(value)


def canonical_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): json_value(value) for key, value in sorted(row.items())}


@dataclass(frozen=True)
class MembershipContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "MembershipContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value.get("source", {}).get("tables"), list):
            raise ValueError("Membership mapping requires source tables")
        target = value.get("target", {})
        identifiers = [
            value["source"].get("member_table"), target.get("archive_table"),
            target.get("profile_table"), target.get("client_table"), target.get("client_external_id"),
        ]
        seen: set[str] = set()
        for table in value["source"]["tables"]:
            identifiers.extend([table.get("table"), *table.get("keys", [])])
            if table.get("effective_date"):
                identifiers.append(table["effective_date"])
            if table.get("table") in seen:
                raise ValueError("Membership source tables must be unique")
            seen.add(table.get("table"))
            if table.get("disposition") not in {"migrate", "inspect-only"}:
                raise ValueError("Membership table has an invalid disposition")
            if table.get("owner") not in {
                "none", "id_asociado", "certificate", "movement", "member_composite",
                "member_composite_branch_socio",
            }:
                raise ValueError("Membership table has an invalid owner strategy")
            if not table.get("keys"):
                raise ValueError("Membership source table requires a stable key")
            excluded_products = table.get("excluded_products", [])
            if not isinstance(excluded_products, list) or not all(
                isinstance(product, str) and re.fullmatch(r"[A-Z0-9 _-]+", product)
                for product in excluded_products
            ):
                raise ValueError("Membership excluded products contain an unsafe value")
            if "require_current_party" in table and not isinstance(table["require_current_party"], bool):
                raise ValueError("Membership current-party requirement must be boolean")
        if not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Unsafe or missing SQL identifier in membership mapping")
        if not value["source"].get("member_relationship_states"):
            raise ValueError("Membership mapping requires reviewed relationship states")
        if not all(
            isinstance(state, str) and re.fullmatch(r"[A-Za-z0-9_-]+", state)
            for state in value["source"]["member_relationship_states"]
        ):
            raise ValueError("Membership relationship states contain an unsafe value")
        batch_size = int(target.get("batch_size", 0))
        if batch_size < 1 or batch_size > 2000:
            raise ValueError("Membership batch size must be between 1 and 2000")
        return cls(value)

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True).encode()).hexdigest()

    @property
    def archive_table(self) -> str:
        return self.raw["target"]["archive_table"]

    @property
    def profile_table(self) -> str:
        return self.raw["target"]["profile_table"]

    @property
    def migrated_tables(self) -> list[dict[str, Any]]:
        return [item for item in self.raw["source"]["tables"] if item["disposition"] == "migrate"]

    def source_key(self, table: dict[str, Any], row: dict[str, Any]) -> str:
        values: list[str] = []
        for column in table["keys"]:
            value = clean_text(row.get(column))
            if value is None:
                raise MembershipDataIssue(f"missing_source_key:{table['table']}:{column}")
            values.append(value.replace("%", "%25").replace("|", "%7C"))
        return "|".join([table["table"], *values])

    def record_hash(self, source_table: str, source_key: str, owner_external_id: str | None,
                    payload: dict[str, Any]) -> str:
        material = {
            "contract": self.contract_hash,
            "source_table": source_table,
            "source_key": source_key,
            "owner_external_id": owner_external_id,
            "payload": payload,
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _table_query(contract: MembershipContract, table: dict[str, Any]) -> str:
    sql = f"SELECT * FROM [dbo].[{table['table']}]"
    if table.get("scope") == "membership-parties":
        states = ",".join(f"'{state}'" for state in contract.raw["source"]["member_relationship_states"])
        sql += f" WHERE [ID_ESTADO_SOCIO] IN ({states})"
    elif table.get("scope") == "membership-operations":
        sql += " WHERE [ID_TIPO_OPERACION] IN (4,5,6,10,60,61)"
        if table.get("require_current_party"):
            sql += (
                " AND [ID_ASOCIADO] IN "
                "(SELECT [ID_ASOCIADO] FROM [dbo].[AFI_SOCIO] WHERE [ID_ASOCIADO] IS NOT NULL)"
            )
        excluded_products = table.get("excluded_products", [])
        if excluded_products:
            literals = ",".join(f"'{product}'" for product in excluded_products)
            sql += (
                " AND UPPER(LTRIM(RTRIM(COALESCE([TIPO_PRODUCTO],'')))) "
                f"NOT IN ({literals})"
            )
    elif table.get("scope") == "membership-operation-types":
        sql += " WHERE [ID_TIPO_OPERACION] IN (4,5,6,10,60,61)"
    return sql


def _member_indexes(conn: Any) -> tuple[dict[int, str], dict[tuple[str, str, str], str], dict[int, str]]:
    socios = select_rows(
        conn,
        "SELECT [ID_ASOCIADO],[ID_EMPRESA],[ID_SUCURSAL],[ID_SOCIO],[NUMERO_AFILIACION] "
        "FROM [dbo].[AFI_SOCIO]",
    )
    by_associate: dict[int, str] = {}
    by_composite: dict[tuple[str, str, str], str] = {}
    for row in socios:
        external = clean_text(row.get("NUMERO_AFILIACION"))
        associate = row.get("ID_ASOCIADO")
        composite = tuple(clean_text(row.get(key)) or "" for key in ("ID_EMPRESA", "ID_SUCURSAL", "ID_SOCIO"))
        if external and associate is not None:
            by_associate[int(associate)] = external
        if external and all(composite):
            by_composite[composite] = external
    certificates = select_rows(conn, "SELECT [ID_CERTIFICADO],[ID_ASOCIADO] FROM [dbo].[AFI_CERTIFICADO]")
    by_certificate = {
        int(row["ID_CERTIFICADO"]): by_associate[int(row["ID_ASOCIADO"])]
        for row in certificates
        if row.get("ID_CERTIFICADO") is not None
        and row.get("ID_ASOCIADO") is not None
        and int(row["ID_ASOCIADO"]) in by_associate
    }
    return by_associate, by_composite, by_certificate


def _owner_external_id(table: dict[str, Any], row: dict[str, Any], by_associate: dict[int, str],
                       by_composite: dict[tuple[str, str, str], str], by_certificate: dict[int, str]) -> str | None:
    strategy = table["owner"]
    if strategy == "none":
        return None
    if strategy == "id_asociado":
        value = row.get("ID_ASOCIADO")
        return by_associate.get(int(value)) if value is not None else None
    if strategy == "certificate":
        value = row.get("ID_CERTIFICADO")
        return by_certificate.get(int(value)) if value is not None else None
    if strategy == "movement":
        composite = tuple(clean_text(row.get(key)) or "" for key in ("ID_EMPRESA", "ID_SUCURSAL_SOCIO", "ID_SOCIO"))
        return by_composite.get(composite)
    if strategy == "member_composite":
        composite = tuple(clean_text(row.get(key)) or "" for key in ("ID_EMPRESA", "ID_SUCURSAL", "ID_SOCIO"))
        return by_composite.get(composite)
    if strategy == "member_composite_branch_socio":
        composite = tuple(clean_text(row.get(key)) or "" for key in ("ID_EMPRESA", "ID_SUCURSAL_SOCIO", "ID_SOCIO"))
        return by_composite.get(composite)
    raise ValueError(f"Unsupported membership owner strategy: {strategy}")


def _summary_rows(conn: Any, contract: MembershipContract) -> list[dict[str, Any]]:
    states = ",".join(f"'{state}'" for state in contract.raw["source"]["member_relationship_states"])
    return select_rows(conn, f"""
        SELECT
            s.ID_ASOCIADO AS arissto_associate_id,
            s.ID_EMPRESA AS arissto_company_id,
            s.ID_SUCURSAL AS arissto_branch_id,
            s.ID_SOCIO AS arissto_member_id,
            s.NUMERO_AFILIACION AS affiliation_number,
            s.ID_ESTADO_SOCIO AS relationship_state_id,
            es.ESTADO_SOCIO AS relationship_state,
            s.ID_ESTATUS_SOCIO AS lifecycle_status_id,
            ets.ESTATUS_SOCIO AS lifecycle_status,
            s.FECHA_SOLICITUD_INGRESO AS request_date,
            s.FECHA_INGRESO_INI AS initial_entry_date,
            s.FECHA_INGRESO AS entry_date,
            s.FECHA_APROBACION_INGRESO AS entry_approval_date,
            s.RAZON_INGRESO AS entry_reason,
            s.FECHA_APROBACION_RETIRO AS withdrawal_approval_date,
            s.FECHA_RETIRO AS withdrawal_date,
            s.MOTIVO_RETIRO AS withdrawal_reason,
            s.TIPO_INGRESO AS entry_type,
            COALESCE(a.common_share_count,0) AS common_share_count,
            COALESCE(a.common_share_balance,0) AS common_share_balance,
            COALESCE(a.preferred_share_count,0) AS preferred_share_count,
            COALESCE(a.preferred_share_balance,0) AS preferred_share_balance,
            COALESCE(c.subscribed_share_count,0) AS subscribed_share_count,
            COALESCE(c.subscribed_share_balance,0) AS subscribed_share_balance,
            COALESCE(c.paid_share_count,0) AS paid_share_count,
            COALESCE(c.paid_share_balance,0) AS paid_share_balance,
            COALESCE(c.common_subscribed_share_count,0) AS common_subscribed_share_count,
            COALESCE(c.common_paid_share_count,0) AS common_paid_share_count,
            COALESCE(c.preferred_subscribed_share_count,0) AS preferred_subscribed_share_count,
            COALESCE(c.preferred_paid_share_count,0) AS preferred_paid_share_count,
            COALESCE(c.certificate_count,0) AS certificate_count,
            COALESCE(m.contribution_movement_count,0) AS contribution_movement_count,
            COALESCE(m.contribution_amount,0) AS contribution_amount,
            m.last_contribution_date
        FROM dbo.AFI_SOCIO s
        LEFT JOIN dbo.AFI_ESTADO_SOCIO es ON es.ID_ESTADO_SOCIO=s.ID_ESTADO_SOCIO
        LEFT JOIN dbo.AFI_ESTATUS_SOCIO ets ON ets.ID_ESTATUS_SOCIO=s.ID_ESTATUS_SOCIO
        LEFT JOIN (
            SELECT ID_ASOCIADO,
                SUM(CASE WHEN ID_TIPO_ACCION=1 THEN NUMERO_ACCIONES ELSE 0 END) common_share_count,
                SUM(CASE WHEN ID_TIPO_ACCION=1 THEN SALDO_ACCIONES ELSE 0 END) common_share_balance,
                SUM(CASE WHEN ID_TIPO_ACCION=2 THEN NUMERO_ACCIONES ELSE 0 END) preferred_share_count,
                SUM(CASE WHEN ID_TIPO_ACCION=2 THEN SALDO_ACCIONES ELSE 0 END) preferred_share_balance
            FROM dbo.AFI_ACCION GROUP BY ID_ASOCIADO
        ) a ON a.ID_ASOCIADO=s.ID_ASOCIADO
        LEFT JOIN (
            SELECT ID_ASOCIADO, COUNT(*) certificate_count,
                SUM(ACCIONES_SUSCRITAS) subscribed_share_count,
                SUM(SALDO_SUSCRITO) subscribed_share_balance,
                SUM(ACCIONES_PAGADAS) paid_share_count,
                SUM(SALDO_PAGADO) paid_share_balance,
                SUM(CASE WHEN ID_TIPO_ACCION=1 THEN ACCIONES_SUSCRITAS ELSE 0 END)
                    common_subscribed_share_count,
                SUM(CASE WHEN ID_TIPO_ACCION=1 THEN ACCIONES_PAGADAS ELSE 0 END)
                    common_paid_share_count,
                SUM(CASE WHEN ID_TIPO_ACCION=2 THEN ACCIONES_SUSCRITAS ELSE 0 END)
                    preferred_subscribed_share_count,
                SUM(CASE WHEN ID_TIPO_ACCION=2 THEN ACCIONES_PAGADAS ELSE 0 END)
                    preferred_paid_share_count
            FROM dbo.AFI_CERTIFICADO GROUP BY ID_ASOCIADO
        ) c ON c.ID_ASOCIADO=s.ID_ASOCIADO
        LEFT JOIN (
            SELECT ID_ASOCIADO, COUNT(*) contribution_movement_count,
                SUM(MONTO) contribution_amount, MAX(FECHA) last_contribution_date
            FROM dbo.MOV_APORTACIONES GROUP BY ID_ASOCIADO
        ) m ON m.ID_ASOCIADO=s.ID_ASOCIADO
        WHERE s.ID_ESTADO_SOCIO IN ({states})
        ORDER BY s.ID_ASOCIADO
    """)


def extract_membership_records(conn: Any, contract: MembershipContract,
                               source_keys: Iterable[str] | None = None) -> list[dict[str, Any]]:
    selected = set(source_keys or [])
    by_associate, by_composite, by_certificate = _member_indexes(conn)
    result: list[dict[str, Any]] = []
    for table in contract.migrated_tables:
        for row in select_rows(conn, _table_query(contract, table)):
            source_key = contract.source_key(table, row)
            if selected and source_key not in selected:
                continue
            payload = canonical_payload(row)
            owner = _owner_external_id(table, row, by_associate, by_composite, by_certificate)
            effective = date_value(row.get(table.get("effective_date"))) if table.get("effective_date") else None
            result.append({
                "source_table": table["table"],
                "source_key": source_key,
                "record_kind": table["kind"],
                "owner_external_id": owner,
                "parent_source_key": None,
                "effective_date": effective.isoformat() if effective else None,
                "payload": payload,
                "source_hash": contract.record_hash(table["table"], source_key, owner, payload),
            })
    for row in _summary_rows(conn, contract):
        owner = clean_text(row.get("affiliation_number"))
        if not owner:
            raise MembershipDataIssue("member_summary_missing_affiliation_number")
        source_key = f"{SUMMARY_TABLE}|{owner.replace('%', '%25').replace('|', '%7C')}"
        if selected and source_key not in selected:
            continue
        payload = canonical_payload(row)
        result.append({
            "source_table": SUMMARY_TABLE,
            "source_key": source_key,
            "record_kind": "member-summary",
            "owner_external_id": owner,
            "parent_source_key": None,
            "effective_date": date_value(row.get("entry_date")).isoformat() if row.get("entry_date") else None,
            "payload": payload,
            "source_hash": contract.record_hash(SUMMARY_TABLE, source_key, owner, payload),
        })
    return result


def _source_table_report(conn: Any, contract: MembershipContract) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    for table in contract.raw["source"]["tables"]:
        columns = {
            str(row["column_name"]): str(row["data_type"])
            for row in select_rows(
                conn,
                "SELECT COLUMN_NAME AS column_name,DATA_TYPE AS data_type FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA=? AND TABLE_NAME=?",
                ("dbo", table["table"]),
            )
        }
        required_columns = set(table["keys"]) | ({table["effective_date"]} if table.get("effective_date") else set())
        if table.get("scope") == "membership-parties":
            required_columns.add("ID_ESTADO_SOCIO")
        elif table.get("scope") == "membership-operations":
            required_columns.add("ID_TIPO_OPERACION")
            if table.get("require_current_party"):
                required_columns.add("ID_ASOCIADO")
            if table.get("excluded_products"):
                required_columns.add("TIPO_PRODUCTO")
        elif table.get("scope") == "membership-operation-types":
            required_columns.add("ID_TIPO_OPERACION")
        missing = sorted(required_columns - set(columns))
        count = 0
        if columns:
            scoped_query = _table_query(contract, table)
            count = int(select_rows(
                conn,
                f"SELECT COUNT_BIG(*) AS row_count FROM ({scoped_query}) AS [scoped_source]",
            )[0]["row_count"])
        report.append({
            "table": f"dbo.{table['table']}",
            "disposition": table["disposition"],
            "row_count": count,
            "column_count": len(columns),
            "schema_hash": hashlib.sha256(
                json.dumps(columns, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "missing_columns": missing,
            "ready": bool(columns) and not missing,
        })
    return report


def _schema_signature(source_tables: list[dict[str, Any]], target_schema: dict[str, dict[str, str]],
                      target_contract: dict[str, Any]) -> str:
    source_schema = [
        {
            "table": item["table"],
            "disposition": item["disposition"],
            "column_count": item["column_count"],
            "schema_hash": item["schema_hash"],
            "missing_columns": item["missing_columns"],
        }
        for item in source_tables
    ]
    material = {
        "source_schema": source_schema,
        "target_schema": target_schema,
        "target_contract": target_contract,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def inspect_membership(settings: Settings, contract: MembershipContract) -> dict[str, Any]:
    with source_connection(settings.source) as source:
        source_tables = _source_table_report(source, contract)
        summary_count = len(_summary_rows(source, contract))
    blockers = [
        {"source_table": item["table"], "missing_columns": item["missing_columns"]}
        for item in source_tables if not item["ready"]
    ]
    target_schema: dict[str, dict[str, str]] = {}
    target_summary: dict[str, Any] = {"postgres_inspection": "not-configured"}
    target_contract: dict[str, Any] = {
        "archive_source_unique": False,
        "profile_registered": False,
        "profile_permissions": [],
    }
    if not settings.target.pg_url:
        blockers.append({"target": "postgres_inspection_required"})
    else:
        try:
            with postgres_connection(settings.target.pg_url) as target:
                target_schema = postgres_schema(target, [
                    contract.archive_table, contract.profile_table,
                    contract.raw["target"]["client_table"], "m_savings_account",
                    "m_share_product", "m_share_account",
                ])
                archive_columns = set(target_schema.get(contract.archive_table, {}))
                profile_columns = set(target_schema.get(contract.profile_table, {}))
                missing_archive = sorted(REQUIRED_ARCHIVE_COLUMNS - archive_columns)
                missing_profile = sorted(REQUIRED_PROFILE_COLUMNS - profile_columns)
                if missing_archive:
                    blockers.append({"target_table": contract.archive_table, "missing_columns": missing_archive})
                if missing_profile:
                    blockers.append({"target_table": contract.profile_table, "missing_columns": missing_profile})
                target_contract["archive_source_unique"] = bool(target.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                    "WHERE n.nspname='public' AND t.relname=%s AND c.contype='u' "
                    "AND pg_get_constraintdef(c.oid)='UNIQUE (source_table, source_key)')",
                    (contract.archive_table,),
                ).fetchone()[0])
                if not target_contract["archive_source_unique"]:
                    blockers.append({"target_table": contract.archive_table, "reason": "source_identity_unique_constraint_missing"})
                target_contract["profile_registered"] = bool(target.execute(
                    "SELECT EXISTS (SELECT 1 FROM x_registered_table "
                    "WHERE registered_table_name=%s AND application_table_name='m_client' "
                    "AND entity_subtype='Person')",
                    (contract.profile_table,),
                ).fetchone()[0])
                if not target_contract["profile_registered"]:
                    blockers.append({"target_table": contract.profile_table, "reason": "client_datatable_registration_missing"})
                required_permissions = {
                    f"{action}_{contract.profile_table}"
                    for action in ("CREATE", "READ", "UPDATE", "DELETE")
                }
                target_contract["profile_permissions"] = sorted(
                    str(row[0]) for row in target.execute(
                        "SELECT code FROM m_permission WHERE code=ANY(%s)",
                        (list(required_permissions),),
                    ).fetchall()
                )
                missing_permissions = sorted(required_permissions - set(target_contract["profile_permissions"]))
                if missing_permissions:
                    blockers.append({"target_table": contract.profile_table, "missing_permissions": missing_permissions})
                counts = target.execute(
                    "SELECT (SELECT COUNT(*) FROM m_client),"
                    "(SELECT COUNT(DISTINCT client_id) FROM m_savings_account),"
                    "(SELECT COUNT(*) FROM m_share_product),"
                    "(SELECT COUNT(*) FROM m_share_account)"
                ).fetchone()
                target_summary = {
                    "postgres_inspection": "ok",
                    "clients": int(counts[0]),
                    "clients_with_savings": int(counts[1]),
                    "share_products": int(counts[2]),
                    "share_accounts": int(counts[3]),
                    "profile_registered": target_contract["profile_registered"],
                    "profile_permission_count": len(target_contract["profile_permissions"]),
                    "native_share_mapping": "deferred-until-real-dividend-savings-accounts-exist",
                }
        except Exception as exc:
            blockers.append({"target": "postgres_inspection_failed", "error_type": type(exc).__name__})
            target_summary = {"postgres_inspection": "failed", "error_type": type(exc).__name__}
    return {
        "block": BLOCK,
        "ready": not blockers,
        "contract_hash": contract.contract_hash,
        "schema_signature": _schema_signature(source_tables, target_schema, target_contract),
        "source": {
            "tables": source_tables,
            "member_summary_rows": summary_count,
            "migrated_source_rows": sum(item["row_count"] for item in source_tables if item["disposition"] == "migrate"),
            "inspect_only_source_rows": sum(item["row_count"] for item in source_tables if item["disposition"] == "inspect-only"),
        },
        "target": target_summary,
        "blockers": blockers,
    }


def _chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def _target_clients(conn: Any, external_ids: set[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for chunk in _chunks(sorted(external_ids), 1000):
        rows = conn.execute("SELECT id,external_id FROM m_client WHERE external_id=ANY(%s)", (chunk,)).fetchall()
        for target_id, external_id in rows:
            if external_id in result:
                raise RuntimeError("duplicate_target_client_external_id")
            result[str(external_id)] = int(target_id)
    return result


def _target_archive(conn: Any, table: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        f'SELECT id,source_table,source_key,client_id,source_hash FROM "{table}"'
    ).fetchall()
    return {
        str(source_key): {
            "id": int(identifier), "source_table": str(source_table),
            "client_id": int(client_id) if client_id is not None else None,
            "source_hash": str(source_hash),
        }
        for identifier, source_table, source_key, client_id, source_hash in rows
    }


def build_membership_plan(settings: Settings, state: State, contract: MembershipContract,
                          source_keys: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    inspection = inspect_membership(settings, contract)
    selected = set(source_keys or [])
    actions: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    issues = Counter()
    if inspection["ready"]:
        with source_connection(settings.source) as source:
            records = extract_membership_records(source, contract, selected or None)
        keys = [record["source_key"] for record in records]
        duplicate_keys = {key for key, count in Counter(keys).items() if count > 1}
        if duplicate_keys:
            issues["duplicate_source_key"] += len(duplicate_keys)
        with postgres_connection(settings.target.pg_url) as target:
            clients = _target_clients(target, {
                record["owner_external_id"] for record in records if record["owner_external_id"]
            })
            existing = _target_archive(target, contract.archive_table)
        for record in records:
            key = record["source_key"]
            client_id = clients.get(record["owner_external_id"]) if record["owner_external_id"] else None
            target_row = existing.get(key)
            if key in duplicate_keys:
                action, reason = "quarantine", "duplicate_source_key"
            elif record["source_table"] == SUMMARY_TABLE and client_id is None:
                action, reason = "quarantine", "member_client_dependency_missing"
            elif target_row and target_row["source_table"] != record["source_table"]:
                action, reason = "quarantine", "target_source_key_collision"
            elif target_row and target_row["source_hash"] == record["source_hash"] and target_row["client_id"] == client_id:
                action, reason = "unchanged", None
            elif target_row:
                action, reason = "update", None
            else:
                action, reason = "create", None
            actions.append({
                "source_key": key,
                "source_hash": record["source_hash"],
                "action": action,
                "reason": reason,
                "target_id": str(target_row["id"]) if target_row else None,
                "client_id": str(client_id) if client_id is not None else None,
            })
    counts = Counter(action["action"] for action in actions)
    document = {
        "applicable": inspection["ready"] and not issues,
        "scope": {"requested_source_keys": sorted(selected), "source_rows": len(records)},
        "counts": dict(counts),
        "unlinked_archive_rows": sum(
            1 for record, action in zip(records, actions)
            if record["owner_external_id"] and action["client_id"] is None and record["source_table"] != SUMMARY_TABLE
        ),
        "readiness_blocker_count": len(inspection["blockers"]),
        "issues": dict(issues),
        "schema_signature": inspection["schema_signature"],
        "actions": actions,
    }
    plan_id = state.save_plan(
        settings.target.fingerprint, BLOCK, source_fingerprint(settings.source),
        contract.contract_hash, document,
    )
    return plan_id, document


@contextmanager
def _postgres_write_connection(url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for PostgreSQL membership writes") from exc
    with psycopg.connect(url, autocommit=False) as conn:
        yield conn


def _write_record(conn: Any, contract: MembershipContract, record: dict[str, Any],
                  client_id: int | None) -> str:
    archive = contract.archive_table
    payload_text = json.dumps(record["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    row = conn.execute(
        f'''INSERT INTO "{archive}"
            (source_table,source_key,client_id,record_kind,parent_source_key,effective_date,
             source_payload,source_hash,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            ON CONFLICT (source_table,source_key) DO UPDATE SET
              client_id=EXCLUDED.client_id,record_kind=EXCLUDED.record_kind,
              parent_source_key=EXCLUDED.parent_source_key,effective_date=EXCLUDED.effective_date,
              source_payload=EXCLUDED.source_payload,source_hash=EXCLUDED.source_hash,
              updated_at=CURRENT_TIMESTAMP
            RETURNING id''',
        (
            record["source_table"], record["source_key"], client_id, record["record_kind"],
            record["parent_source_key"], record["effective_date"], payload_text, record["source_hash"],
        ),
    ).fetchone()
    if record["source_table"] == SUMMARY_TABLE:
        if client_id is None:
            raise MembershipDataIssue("member_client_dependency_missing")
        profile = record["payload"]
        columns = PROFILE_VALUE_COLUMNS
        values = []
        for column in columns:
            value = record["source_hash"] if column == "source_hash" else profile.get(column)
            if column.endswith("_date"):
                value = date_value(value)
            values.append(value)
        column_sql = ",".join(f'"{column}"' for column in columns)
        placeholder_sql = ",".join(["%s"] * len(columns))
        update_sql = ",".join(f'"{column}"=EXCLUDED."{column}"' for column in columns)
        conn.execute(
            f'''INSERT INTO "{contract.profile_table}"
                (client_id,{column_sql},created_at,updated_at)
                VALUES (%s,{placeholder_sql},CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                ON CONFLICT (client_id) DO UPDATE SET {update_sql},updated_at=CURRENT_TIMESTAMP''',
            (client_id, *values),
        )
    return str(row[0])


def _apply_guard(settings: Settings, state: State, contract: MembershipContract,
                 plan_id: str, production_confirmation: str | None) -> dict[str, Any]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK:
        raise ValueError("Plan is not a membership-share-capital plan")
    if plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Plan target fingerprint does not match selected target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source):
        raise RuntimeError("Plan source fingerprint no longer matches")
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Membership contract changed after planning")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_membership(settings, contract)
    if not inspection["ready"] or inspection["schema_signature"] != plan["document"]["schema_signature"]:
        raise RuntimeError("Membership destination readiness/schema changed after planning")
    if not plan["document"].get("applicable"):
        raise RuntimeError("Membership plan is not applicable")
    return plan


def apply_membership_plan(settings: Settings, state: State, contract: MembershipContract, plan_id: str,
                          production_confirmation: str | None = None,
                          source_keys: set[str] | None = None) -> tuple[str, dict[str, int]]:
    plan = _apply_guard(settings, state, contract, plan_id, production_confirmation)
    actions = [
        action for action in plan["document"]["actions"]
        if source_keys is None or action["source_key"] in source_keys
    ]
    with source_connection(settings.source) as source:
        current_records = {
            record["source_key"]: record
            for record in extract_membership_records(source, contract, [action["source_key"] for action in actions])
        }
    run_id = state.start_run(plan)
    counts = Counter()
    for action in actions:
        if action["action"] in {"unchanged", "quarantine"}:
            status = "unchanged" if action["action"] == "unchanged" else "quarantined"
            state.record_item(run_id, action["source_key"], action["action"], action["source_hash"],
                              status, action.get("target_id"), action.get("reason"))
            counts[status] += 1

    writable = [action for action in actions if action["action"] in {"create", "update"}]
    batch_size = int(contract.raw["target"]["batch_size"])
    with _postgres_write_connection(settings.target.pg_url) as target:
        writer = ControlledSqlWriter(target, BLOCK)
        for batch in _chunks(writable, batch_size):
            completed: list[tuple[dict[str, Any], str]] = []
            try:
                with writer.entity_transaction("upsert_membership_archive"):
                    for action in batch:
                        record = current_records.get(action["source_key"])
                        if record is None:
                            raise MembershipDataIssue("planned_source_record_missing")
                        if record["source_hash"] != action["source_hash"]:
                            raise MembershipDataIssue("source_hash_changed_after_planning")
                        client_id = int(action["client_id"]) if action.get("client_id") is not None else None
                        target_id = _write_record(target, contract, record, client_id)
                        completed.append((action, target_id))
                state.record_items([
                    (run_id, action["source_key"], action["action"], action["source_hash"],
                     target_id, "succeeded", None)
                    for action, target_id in completed
                ])
                state.save_mappings([
                    (settings.target.fingerprint, BLOCK, action["source_key"], target_id,
                     action["source_hash"], datetime.utcnow().isoformat())
                    for action, target_id in completed
                ])
                counts["succeeded"] += len(completed)
            except Exception as exc:
                state.record_items([
                    (run_id, action["source_key"], action["action"], action["source_hash"],
                     action.get("target_id"), "failed", type(exc).__name__)
                    for action in batch
                ])
                counts["failed"] += len(batch)
    status = "completed" if counts["failed"] == 0 else "completed-with-errors"
    state.finish_run(run_id, status, dict(counts))
    return run_id, dict(counts)


def reconcile_membership(settings: Settings, state: State, contract: MembershipContract,
                         run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Membership run does not belong to the selected target")
    items = state.run_items(run_id)
    keys = {item["source_key"] for item in items if item["status"] in {"succeeded", "unchanged"}}
    with source_connection(settings.source) as source:
        records = {record["source_key"]: record for record in extract_membership_records(source, contract, keys)}
    target_rows: dict[str, dict[str, Any]] = {}
    profile_hashes: dict[int, str] = {}
    with postgres_connection(settings.target.pg_url) as target:
        for chunk in _chunks(sorted(keys), 1000):
            rows = target.execute(
                f'SELECT id,source_table,source_key,client_id,source_payload,source_hash '
                f'FROM "{contract.archive_table}" WHERE source_key=ANY(%s)',
                (chunk,),
            ).fetchall()
            for identifier, source_table, source_key, client_id, payload, source_hash in rows:
                target_rows[str(source_key)] = {
                    "id": int(identifier), "source_table": str(source_table),
                    "client_id": int(client_id) if client_id is not None else None,
                    "payload": str(payload), "source_hash": str(source_hash),
                }
        profile_hashes = {
            int(client_id): str(source_hash)
            for client_id, source_hash in target.execute(
                f'SELECT client_id,source_hash FROM "{contract.profile_table}"'
            ).fetchall()
        }
    counts = Counter()
    mismatches: list[dict[str, str]] = []
    action_index = {action["source_key"]: action for action in state.plan(run["plan_id"])["document"]["actions"]}
    for key in keys:
        record = records.get(key)
        target_row = target_rows.get(key)
        action = action_index.get(key, {})
        expected_client = int(action["client_id"]) if action.get("client_id") is not None else None
        expected_payload = json.dumps(record["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False) if record else None
        if record is None:
            counts["source_missing"] += 1
            mismatches.append({"source_key": key, "reason": "source_missing"})
        elif target_row is None:
            counts["target_missing"] += 1
            mismatches.append({"source_key": key, "reason": "target_missing"})
        elif (
            target_row["source_table"] != record["source_table"]
            or target_row["source_hash"] != record["source_hash"]
            or target_row["client_id"] != expected_client
            or target_row["payload"] != expected_payload
        ):
            counts["mismatch"] += 1
            mismatches.append({"source_key": key, "reason": "archive_mismatch"})
        elif record["source_table"] == SUMMARY_TABLE and profile_hashes.get(expected_client) != record["source_hash"]:
            counts["mismatch"] += 1
            mismatches.append({"source_key": key, "reason": "member_profile_mismatch"})
        else:
            counts["matched"] += 1
    failed_or_quarantined = sum(item["status"] in {"failed", "quarantined"} for item in items)
    return {
        "run_id": run_id,
        "ok": not mismatches and failed_or_quarantined == 0,
        "counts": dict(counts),
        "failed_or_quarantined": failed_or_quarantined,
        "mismatches": mismatches[:100],
    }
