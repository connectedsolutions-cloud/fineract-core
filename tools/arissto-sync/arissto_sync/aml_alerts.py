from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
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


BLOCK = "aml-alerts"
SOURCE_SYSTEM = "ARISSTO"

REQUIRED_TARGET_COLUMNS: dict[str, set[str]] = {
    "alert_type_table": {
        "id", "code", "name", "description", "category_code", "source_system",
        "source_event_type_code", "source_subtype_code", "comparison_basis_code",
        "aggregation_mode_code", "default_severity_code", "settings_json", "active",
        "created_at", "updated_at",
    },
    "status_table": {"code", "name", "description", "terminal", "active", "sort_order"},
    "alert_table": {
        "id", "alert_type_id", "status_code", "source_system", "source_alert_key",
        "source_event_type_code", "source_status_code", "source_alert_class_code",
        "source_temporary", "occurred_at", "business_date", "detected_at",
        "evaluation_period_start", "evaluation_period_end", "source_message",
        "triggering_amount", "observed_amount", "threshold_amount", "currency_code",
        "product_type_code", "severity_code", "source_payload", "source_hash",
        "created_by", "updated_by", "created_at", "updated_at",
    },
    "subject_table": {
        "id", "alert_id", "subject_type", "subject_role", "client_id", "source_system",
        "source_subject_type", "source_subject_key", "primary_subject", "created_at",
    },
    "reference_table": {
        "id", "alert_id", "relationship_type", "source_system", "source_entity_type",
        "source_entity_key", "source_reference_key", "target_entity_type", "target_entity_id",
        "occurred_at", "amount", "currency_code", "details_json", "created_at",
    },
    "status_history_table": {
        "id", "alert_id", "previous_status_code", "status_code", "reason_code",
        "comment_text", "changed_by", "changed_at",
    },
}

SOURCE_REQUIREMENTS: dict[str, set[str]] = {
    "alert_table": {
        "ID_EVENTO", "EVENTO", "DT_EVENTO", "TIPO_PRODUCTO", "REF_CUENTA",
        "ID_USR_CREO", "ID_USR_MOD", "DT_CREO", "DT_MOD", "ID_ASOCIADO",
        "ID_TIPO_EVENTO", "ID_SUBTIPO_EVENTO", "ID_ESTADO_EVENTO", "ID_REFERENCIA",
        "ID_TIPO_ALERTA", "FECHA_EVENTO", "TEMPORAL", "NUMERO_COMPROBANTE",
        "ID_SUCURSAL", "CODIGO_SISTEMA", "ID_TRANSACCION", "MONTO", "ID_PERSONA",
        "ID_TIPO_PAGO", "FECHA_ENVIO_REPORTE", "DECLARACION_JURADA", "ID_FUENTE_ING",
        "ID_ACT_ECONOMICA",
    },
    "alert_type_table": {
        "ID_SUBTIPO_EVENTO", "SUBTIPO_EVENTO", "ACTIVO", "ID_TIPO_EVENTO",
        "EVENTO_OPERACIONES", "ALERTA_UNICA",
    },
    "movement_table": {
        "ID_EVE_MOVIMIENTOS", "ID_APO_MOVIMIENTO", "ID_AHO_MOVIMIENTO",
        "ID_CRD_MOVIMIENTO", "ID_EVENTO",
    },
    "party_table": {"ID_ASOCIADO", "NUMERO_AFILIACION", "ID_ESTADO_SOCIO"},
}


class AmlAlertDataIssue(RuntimeError):
    """Non-sensitive reason why an AML source alert cannot be synchronized safely."""


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    result = re.sub(r"\s+", " ", str(value).strip())
    return result or None


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
    return {
        str(key): json_value(value)
        for key, value in sorted(row.items())
        if not str(key).startswith("__")
    }


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _iso_datetime(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).isoformat(timespec="microseconds")


def _iso_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value).strip()[:10]).isoformat()


def _decimal(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value not in (None, "") else None


def _chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


@dataclass(frozen=True)
class AmlAlertContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "AmlAlertContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        source, target = value.get("source", {}), value.get("target", {})
        identifiers = [
            source.get("alert_table"), source.get("alert_key"), source.get("alert_type_table"),
            source.get("movement_table"), source.get("party_table"),
            *[target.get(name) for name in REQUIRED_TARGET_COLUMNS],
            target.get("client_table"), target.get("client_external_id"),
        ]
        party_join = source.get("party_join", {})
        identifiers.extend([
            party_join.get("alert_column"), party_join.get("party_column"),
            party_join.get("fineract_client_external_key"),
        ])
        movement_references = source.get("movement_references")
        if not isinstance(movement_references, list) or not movement_references:
            raise ValueError("AML mapping requires movement references")
        for mapping in movement_references:
            identifiers.extend([mapping.get("column"), mapping.get("entity_type")])
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(mapping.get("relationship_type") or "")):
                raise ValueError("AML movement relationship type is unsafe")
        if not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Unsafe or missing SQL identifier in AML mapping")

        subtypes = source.get("included_subtypes")
        if not isinstance(subtypes, list) or not subtypes or len(set(subtypes)) != len(subtypes):
            raise ValueError("AML included subtypes must be a non-empty unique list")
        if not all(isinstance(item, int) and 0 < item <= 32767 for item in subtypes):
            raise ValueError("AML subtype is outside SMALLINT range")
        expected_type_keys = {str(item) for item in subtypes}
        type_map = value.get("type_map", {})
        if set(type_map) != expected_type_keys or not all(
            isinstance(item, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", item)
            for item in type_map.values()
        ):
            raise ValueError("AML type map must exactly cover the included subtypes")

        subject_map = source.get("subject_type_by_relationship_state", {})
        if not subject_map or not all(
            re.fullmatch(r"[A-Za-z0-9_-]+", str(key)) and value in {"CLIENT", "MEMBERSHIP"}
            for key, value in subject_map.items()
        ):
            raise ValueError("AML subject-type mapping is invalid")
        if target.get("initial_status") != "NEW":
            raise ValueError("Initial AML target status must be NEW until workflow design is implemented")
        batch_size = int(target.get("batch_size", 0))
        if batch_size < 1 or batch_size > 2000:
            raise ValueError("AML batch size must be between 1 and 2000")
        if value.get("missing_client_policy") != "quarantine":
            raise ValueError("AML alerts with missing clients must quarantine")
        if value.get("unresolved_movement_policy") != "preserve-source-reference":
            raise ValueError("AML unresolved movement policy must preserve source references")
        if value.get("unexpected_subtype_policy") != "exclude-and-report":
            raise ValueError("AML unexpected subtypes must be excluded and reported")
        return cls(value)

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.raw).encode()).hexdigest()

    @property
    def included_subtypes(self) -> list[int]:
        return list(self.raw["source"]["included_subtypes"])

    @property
    def batch_size(self) -> int:
        return int(self.raw["target"]["batch_size"])

    def type_code(self, subtype: Any) -> str:
        key = str(int(subtype))
        try:
            return str(self.raw["type_map"][key])
        except (KeyError, TypeError, ValueError) as exc:
            raise AmlAlertDataIssue("unsupported_alert_subtype") from exc

    def source_key(self, value: Any) -> str:
        key = clean_text(value)
        if not key or not key.isdigit() or int(key) < 1:
            raise AmlAlertDataIssue("invalid_alert_source_key")
        return str(int(key))

    def subject_type(self, relationship_state: Any) -> str:
        state = clean_text(relationship_state)
        try:
            return str(self.raw["source"]["subject_type_by_relationship_state"][state])
        except KeyError as exc:
            raise AmlAlertDataIssue("unmapped_subject_relationship_state") from exc


def _placeholders(values: list[Any]) -> str:
    return ",".join("?" for _ in values)


def _alert_query(contract: AmlAlertContract, source_keys: list[str] | None = None) -> tuple[str, tuple[Any, ...]]:
    source = contract.raw["source"]
    subtypes = contract.included_subtypes
    sql = (
        f"SELECT e.*,p.[{source['party_join']['fineract_client_external_key']}] AS __owner_external_id,"
        "p.[ID_ESTADO_SOCIO] AS __relationship_state_id,"
        "st.[SUBTIPO_EVENTO] AS __subtype_message,st.[ID_TIPO_EVENTO] AS __catalog_event_type_code "
        f"FROM [dbo].[{source['alert_table']}] e "
        f"JOIN [dbo].[{source['alert_type_table']}] st ON st.[ID_SUBTIPO_EVENTO]=e.[ID_SUBTIPO_EVENTO] "
        f"LEFT JOIN [dbo].[{source['party_table']}] p "
        f"ON p.[{source['party_join']['party_column']}]=e.[{source['party_join']['alert_column']}] "
        f"WHERE e.[ID_SUBTIPO_EVENTO] IN ({_placeholders(subtypes)})"
    )
    params: list[Any] = list(subtypes)
    if source_keys:
        numeric = [int(contract.source_key(key)) for key in source_keys]
        sql += f" AND e.[{source['alert_key']}] IN ({_placeholders(numeric)})"
        params.extend(numeric)
    sql += f" ORDER BY e.[{source['alert_key']}]"
    return sql, tuple(params)


def _movement_query(contract: AmlAlertContract, source_keys: list[str] | None = None) -> tuple[str, tuple[Any, ...]]:
    source = contract.raw["source"]
    subtypes = contract.included_subtypes
    sql = (
        f"SELECT m.* FROM [dbo].[{source['movement_table']}] m "
        f"JOIN [dbo].[{source['alert_table']}] e ON e.[{source['alert_key']}]=m.[ID_EVENTO] "
        f"WHERE e.[ID_SUBTIPO_EVENTO] IN ({_placeholders(subtypes)})"
    )
    params: list[Any] = list(subtypes)
    if source_keys:
        numeric = [int(contract.source_key(key)) for key in source_keys]
        sql += f" AND e.[{source['alert_key']}] IN ({_placeholders(numeric)})"
        params.extend(numeric)
    sql += " ORDER BY m.[ID_EVENTO],m.[ID_EVE_MOVIMIENTOS]"
    return sql, tuple(params)


def _normalize_record(contract: AmlAlertContract, row: dict[str, Any], movements: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[str] = []
    source_key = contract.source_key(row.get("ID_EVENTO"))
    try:
        occurred_at = _iso_datetime(row.get("DT_EVENTO"))
        if occurred_at is None:
            raise ValueError("missing")
    except (TypeError, ValueError):
        occurred_at = None
        issues.append("invalid_alert_timestamp")

    owner_external_id = clean_text(row.get("__owner_external_id"))
    source_subject_key = clean_text(row.get("ID_ASOCIADO"))
    try:
        subject_type = contract.subject_type(row.get("__relationship_state_id"))
    except AmlAlertDataIssue as exc:
        subject_type = None
        issues.append(str(exc))
    if not owner_external_id:
        issues.append("missing_alert_owner_affiliation_number")
    if not source_subject_key:
        issues.append("missing_alert_owner_associate_id")

    references: list[dict[str, Any]] = []
    reference_identities: set[tuple[str, str, str, str]] = set()
    for movement in movements:
        child_key = clean_text(movement.get("ID_EVE_MOVIMIENTOS"))
        if not child_key:
            issues.append("missing_movement_child_key")
            continue
        details = canonical_payload(movement)
        for mapping in contract.raw["source"]["movement_references"]:
            entity_key = clean_text(movement.get(mapping["column"]))
            if not entity_key:
                continue
            identity = (mapping["relationship_type"], mapping["entity_type"], entity_key, child_key)
            if identity in reference_identities:
                issues.append("duplicate_alert_movement_reference")
                continue
            reference_identities.add(identity)
            references.append({
                "relationship_type": mapping["relationship_type"],
                "source_entity_type": mapping["entity_type"],
                "source_entity_key": entity_key,
                "source_reference_key": child_key,
                "occurred_at": occurred_at,
                "amount": None,
                "currency_code": None,
                "details": details,
            })
    references.sort(key=lambda item: (
        item["relationship_type"], item["source_entity_type"],
        item["source_entity_key"], item["source_reference_key"],
    ))
    payload = canonical_payload(row)
    try:
        type_code = contract.type_code(row.get("ID_SUBTIPO_EVENTO"))
    except AmlAlertDataIssue as exc:
        type_code = None
        issues.append(str(exc))
    subject = {
        "subject_type": subject_type,
        "subject_role": "PRIMARY",
        "client_external_id": owner_external_id,
        "source_subject_type": contract.raw["source"]["party_table"],
        "source_subject_key": source_subject_key,
        "primary_subject": True,
    }
    material = {
        "contract": contract.contract_hash,
        "source_key": source_key,
        "type_code": type_code,
        "payload": payload,
        "subject": subject,
        "references": references,
    }
    return {
        "source_key": source_key,
        "type_code": type_code,
        "source_event_type_code": clean_text(row.get("ID_TIPO_EVENTO")),
        "source_status_code": clean_text(row.get("ID_ESTADO_EVENTO")),
        "source_alert_class_code": clean_text(row.get("ID_TIPO_ALERTA")),
        "source_temporary": bool(row["TEMPORAL"]) if row.get("TEMPORAL") is not None else None,
        "occurred_at": occurred_at,
        "business_date": _iso_date(row.get("FECHA_EVENTO")),
        "detected_at": _iso_datetime(row.get("DT_CREO")) or occurred_at,
        "source_message": str(row["EVENTO"]) if row.get("EVENTO") is not None else None,
        "triggering_amount": _decimal(row.get("MONTO")),
        "product_type_code": clean_text(row.get("TIPO_PRODUCTO")),
        "payload": payload,
        "source_hash": hashlib.sha256(canonical_json(material).encode()).hexdigest(),
        "subject": subject,
        "references": references,
        "issues": sorted(set(issues)),
    }


def extract_aml_alerts(conn: Any, contract: AmlAlertContract,
                       source_keys: Iterable[str] | None = None) -> list[dict[str, Any]]:
    selected = list(dict.fromkeys(source_keys or []))
    header_rows: list[dict[str, Any]] = []
    movement_rows: list[dict[str, Any]] = []
    if selected:
        for chunk in _chunks(selected, 1000):
            sql, params = _alert_query(contract, chunk)
            header_rows.extend(select_rows(conn, sql, params))
            sql, params = _movement_query(contract, chunk)
            movement_rows.extend(select_rows(conn, sql, params))
    else:
        sql, params = _alert_query(contract)
        header_rows = select_rows(conn, sql, params)
        sql, params = _movement_query(contract)
        movement_rows = select_rows(conn, sql, params)
    by_alert: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in movement_rows:
        key = contract.source_key(row.get("ID_EVENTO"))
        by_alert[key].append(row)
    records = [
        _normalize_record(contract, row, by_alert.get(contract.source_key(row.get("ID_EVENTO")), []))
        for row in header_rows
    ]
    if selected:
        found = {record["source_key"] for record in records}
        missing = sorted(set(selected) - found)
        if missing:
            raise RuntimeError(f"Requested AML alert source keys were not found: {','.join(missing[:10])}")
    return records


def _source_table_report(conn: Any, contract: AmlAlertContract) -> list[dict[str, Any]]:
    source = contract.raw["source"]
    report: list[dict[str, Any]] = []
    for role, required in SOURCE_REQUIREMENTS.items():
        table = source[role]
        rows = select_rows(
            conn,
            "SELECT COLUMN_NAME AS column_name,DATA_TYPE AS data_type FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA=? AND TABLE_NAME=?",
            ("dbo", table),
        )
        columns = {str(row["column_name"]): str(row["data_type"]) for row in rows}
        missing = sorted(required - set(columns))
        report.append({
            "role": role,
            "table": f"dbo.{table}",
            "columns": columns,
            "missing_columns": missing,
            "ready": bool(columns) and not missing,
        })
    return report


def _unique_constraints(conn: Any, tables: list[str]) -> dict[str, set[tuple[str, ...]]]:
    rows = conn.execute(
        "SELECT tc.table_name,tc.constraint_name,kcu.column_name,kcu.ordinal_position "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "ON kcu.constraint_schema=tc.constraint_schema AND kcu.constraint_name=tc.constraint_name "
        "WHERE tc.table_schema='public' AND tc.constraint_type='UNIQUE' AND tc.table_name=ANY(%s) "
        "ORDER BY tc.table_name,tc.constraint_name,kcu.ordinal_position",
        (tables,),
    ).fetchall()
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for table, constraint, column, _ in rows:
        grouped[(str(table), str(constraint))].append(str(column))
    result: dict[str, set[tuple[str, ...]]] = {table: set() for table in tables}
    for (table, _), columns in grouped.items():
        result[table].add(tuple(columns))
    return result


def _schema_signature(source_tables: list[dict[str, Any]], target_schema: dict[str, dict[str, str]],
                      target_contract: dict[str, Any]) -> str:
    material = {
        "source_schema": [
            {"role": item["role"], "table": item["table"], "columns": item["columns"]}
            for item in source_tables
        ],
        "target_schema": target_schema,
        "target_contract": target_contract,
    }
    return hashlib.sha256(canonical_json(material).encode()).hexdigest()


def inspect_aml_alerts(settings: Settings, contract: AmlAlertContract,
                       source_conn: Any | None = None) -> dict[str, Any]:
    source_tables: list[dict[str, Any]] = []
    subtype_counts: list[dict[str, Any]] = []
    def inspect_source(source: Any) -> None:
        nonlocal source_tables, subtype_counts
        source_tables = _source_table_report(source, contract)
        subtypes = contract.included_subtypes
        subtype_counts = select_rows(
            source,
            "SELECT ID_SUBTIPO_EVENTO AS subtype,COUNT_BIG(*) AS alerts,"
            "COUNT(DISTINCT ID_ASOCIADO) AS parties "
            f"FROM [dbo].[{contract.raw['source']['alert_table']}] "
            f"WHERE ID_SUBTIPO_EVENTO IN ({_placeholders(subtypes)}) GROUP BY ID_SUBTIPO_EVENTO",
            tuple(subtypes),
        )
    if source_conn is None:
        with source_connection(settings.source) as source:
            inspect_source(source)
    else:
        inspect_source(source_conn)
    blockers: list[dict[str, Any]] = [
        {"source_table": item["table"], "missing_columns": item["missing_columns"]}
        for item in source_tables if not item["ready"]
    ]
    target_schema: dict[str, dict[str, str]] = {}
    target_contract: dict[str, Any] = {"unique_constraints": {}, "types": {}, "statuses": []}
    target_summary: dict[str, Any] = {"postgres_inspection": "not-configured"}
    target = contract.raw["target"]
    if not settings.target.pg_url:
        blockers.append({"target": "postgres_inspection_required"})
    else:
        try:
            with postgres_connection(settings.target.pg_url) as conn:
                table_names = [target[name] for name in REQUIRED_TARGET_COLUMNS]
                target_schema = postgres_schema(conn, [*table_names, target["client_table"]])
                for role, required in REQUIRED_TARGET_COLUMNS.items():
                    missing = sorted(required - set(target_schema.get(target[role], {})))
                    if missing:
                        blockers.append({"target_table": target[role], "missing_columns": missing})
                if target["client_external_id"] not in target_schema.get(target["client_table"], {}):
                    blockers.append({
                        "target_table": target["client_table"],
                        "missing_columns": [target["client_external_id"]],
                    })
                uniques = _unique_constraints(conn, table_names)
                expected_uniques = {
                    target["alert_type_table"]: {("code",), ("source_system", "source_subtype_code")},
                    target["alert_table"]: {("source_system", "source_alert_key")},
                    target["subject_table"]: {(
                        "alert_id", "subject_type", "subject_role", "source_system",
                        "source_subject_type", "source_subject_key",
                    )},
                    target["reference_table"]: {(
                        "alert_id", "relationship_type", "source_system", "source_entity_type",
                        "source_entity_key", "source_reference_key",
                    )},
                }
                for table, expected in expected_uniques.items():
                    missing = sorted(expected - uniques.get(table, set()))
                    if missing:
                        blockers.append({"target_table": table, "missing_unique_constraints": missing})
                target_contract["unique_constraints"] = {
                    table: sorted(list(values)) for table, values in uniques.items()
                }
                type_rows = conn.execute(
                    f'SELECT id,code,source_system,source_subtype_code,active '
                    f'FROM "{target["alert_type_table"]}" WHERE code=ANY(%s)',
                    (list(contract.raw["type_map"].values()),),
                ).fetchall()
                target_contract["types"] = {
                    str(code): {
                        "id": int(identifier), "source_system": str(system) if system is not None else None,
                        "source_subtype_code": str(subtype) if subtype is not None else None, "active": bool(active),
                    }
                    for identifier, code, system, subtype, active in type_rows
                }
                for subtype, code in contract.raw["type_map"].items():
                    actual = target_contract["types"].get(code)
                    if not actual or actual["source_system"] != SOURCE_SYSTEM or actual["source_subtype_code"] != subtype or not actual["active"]:
                        blockers.append({"target_alert_type": code, "reason": "catalog_mapping_missing_or_inactive"})
                statuses = [str(row[0]) for row in conn.execute(
                    f'SELECT code FROM "{target["status_table"]}" WHERE active=TRUE'
                ).fetchall()]
                target_contract["statuses"] = sorted(statuses)
                if target["initial_status"] not in statuses:
                    blockers.append({"target_status": target["initial_status"], "reason": "status_missing_or_inactive"})
                counts = conn.execute(
                    f'SELECT (SELECT COUNT(*) FROM "{target["alert_table"]}"),'
                    f'(SELECT COUNT(*) FROM "{target["subject_table"]}"),'
                    f'(SELECT COUNT(*) FROM "{target["reference_table"]}")'
                ).fetchone()
                target_summary = {
                    "postgres_inspection": "ok",
                    "alerts": int(counts[0]), "subjects": int(counts[1]), "references": int(counts[2]),
                    "configured_type_codes": sorted(target_contract["types"]),
                    "active_status_codes": sorted(statuses),
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
            "tables": [
                {key: value for key, value in item.items() if key != "columns"}
                for item in source_tables
            ],
            "subtypes": [
                {"subtype": int(row["subtype"]), "alerts": int(row["alerts"]), "parties": int(row["parties"])}
                for row in subtype_counts
            ],
        },
        "target": target_summary,
        "blockers": blockers,
    }


def _target_clients(conn: Any, contract: AmlAlertContract, external_ids: set[str]) -> dict[str, int]:
    target = contract.raw["target"]
    result: dict[str, int] = {}
    for chunk in _chunks(sorted(external_ids), 1000):
        rows = conn.execute(
            f'SELECT id,"{target["client_external_id"]}" FROM "{target["client_table"]}" '
            f'WHERE "{target["client_external_id"]}"=ANY(%s)',
            (chunk,),
        ).fetchall()
        for identifier, external_id in rows:
            key = str(external_id)
            if key in result:
                raise RuntimeError("duplicate_target_client_external_id")
            result[key] = int(identifier)
    return result


def _target_type_ids(conn: Any, contract: AmlAlertContract) -> dict[str, int]:
    table = contract.raw["target"]["alert_type_table"]
    rows = conn.execute(
        f'SELECT id,code FROM "{table}" WHERE code=ANY(%s)',
        (list(contract.raw["type_map"].values()),),
    ).fetchall()
    return {str(code): int(identifier) for identifier, code in rows}


def _target_snapshots(conn: Any, contract: AmlAlertContract,
                      source_keys: set[str] | None = None) -> dict[str, dict[str, Any]]:
    target = contract.raw["target"]
    params: list[Any] = [SOURCE_SYSTEM, list(contract.raw["type_map"].values())]
    sql = (
        f'SELECT a.id,a.source_alert_key,a.source_hash,t.code,a.source_event_type_code,'
        'a.source_status_code,a.source_alert_class_code,a.source_temporary,a.occurred_at,'
        'a.business_date,a.detected_at,a.source_message,a.triggering_amount,a.product_type_code,'
        f'a.source_payload FROM "{target["alert_table"]}" a '
        f'JOIN "{target["alert_type_table"]}" t ON t.id=a.alert_type_id '
        'WHERE a.source_system=%s AND t.code=ANY(%s)'
    )
    if source_keys:
        sql += " AND a.source_alert_key=ANY(%s)"
        params.append(sorted(source_keys))
    rows = conn.execute(sql, tuple(params)).fetchall()
    snapshots = {
        str(row[1]): {
            "id": int(row[0]), "source_hash": str(row[2]) if row[2] else None,
            "type_code": str(row[3]),
            "header": (
                str(row[4]) if row[4] is not None else None,
                str(row[5]) if row[5] is not None else None,
                str(row[6]) if row[6] is not None else None,
                bool(row[7]) if row[7] is not None else None,
                _iso_datetime(row[8]), _iso_date(row[9]), _iso_datetime(row[10]), row[11],
                _decimal(row[12]), str(row[13]) if row[13] is not None else None,
                str(row[14]) if row[14] is not None else None,
            ),
            "subjects": set(), "subject_values": set(),
            "references": set(), "reference_values": set(),
        }
        for row in rows
    }
    ids = [item["id"] for item in snapshots.values()]
    by_id = {item["id"]: item for item in snapshots.values()}
    for chunk in _chunks(ids, 1000):
        for row in conn.execute(
            f'SELECT alert_id,subject_type,subject_role,client_id,source_subject_type,source_subject_key,primary_subject '
            f'FROM "{target["subject_table"]}" WHERE source_system=%s AND alert_id=ANY(%s)',
            (SOURCE_SYSTEM, chunk),
        ).fetchall():
            identity = (str(row[1]), str(row[2]), int(row[3]) if row[3] is not None else None, str(row[4]), str(row[5]))
            by_id[int(row[0])]["subjects"].add(identity)
            by_id[int(row[0])]["subject_values"].add((*identity, bool(row[6])))
        for row in conn.execute(
            f'SELECT alert_id,relationship_type,source_entity_type,source_entity_key,source_reference_key,'
            f'occurred_at,amount,currency_code,details_json '
            f'FROM "{target["reference_table"]}" WHERE source_system=%s AND alert_id=ANY(%s)',
            (SOURCE_SYSTEM, chunk),
        ).fetchall():
            identity = (str(row[1]), str(row[2]), str(row[3]), str(row[4]) if row[4] is not None else None)
            by_id[int(row[0])]["references"].add(identity)
            by_id[int(row[0])]["reference_values"].add((
                *identity, _iso_datetime(row[5]), _decimal(row[6]),
                str(row[7]) if row[7] is not None else None,
                str(row[8]) if row[8] is not None else None,
            ))
    return snapshots


def _expected_subject(record: dict[str, Any], client_id: int) -> set[tuple[Any, ...]]:
    subject = record["subject"]
    return {(
        subject["subject_type"], subject["subject_role"], client_id,
        subject["source_subject_type"], subject["source_subject_key"],
    )}


def _expected_references(record: dict[str, Any]) -> set[tuple[Any, ...]]:
    return {
        (
            item["relationship_type"], item["source_entity_type"],
            item["source_entity_key"], item["source_reference_key"],
        )
        for item in record["references"]
    }


def _expected_header(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record["source_event_type_code"], record["source_status_code"],
        record["source_alert_class_code"], record["source_temporary"],
        record["occurred_at"], record["business_date"], record["detected_at"],
        record["source_message"], record["triggering_amount"], record["product_type_code"],
        canonical_json(record["payload"]),
    )


def _expected_subject_values(record: dict[str, Any], client_id: int) -> set[tuple[Any, ...]]:
    subject = record["subject"]
    return {(
        subject["subject_type"], subject["subject_role"], client_id,
        subject["source_subject_type"], subject["source_subject_key"], subject["primary_subject"],
    )}


def _expected_reference_values(record: dict[str, Any]) -> set[tuple[Any, ...]]:
    return {
        (
            item["relationship_type"], item["source_entity_type"], item["source_entity_key"],
            item["source_reference_key"], item["occurred_at"], item["amount"],
            item["currency_code"], canonical_json(item["details"]),
        )
        for item in record["references"]
    }


def build_aml_alert_plan(settings: Settings, state: State, contract: AmlAlertContract,
                         source_keys: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    selected = list(dict.fromkeys(contract.source_key(key) for key in (source_keys or [])))
    records: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    issues = Counter()
    with source_connection(settings.source) as source:
        inspection = inspect_aml_alerts(settings, contract, source_conn=source)
        if inspection["ready"]:
            records = extract_aml_alerts(source, contract, selected or None)
    if inspection["ready"]:
        keys = [record["source_key"] for record in records]
        duplicates = {key for key, count in Counter(keys).items() if count > 1}
        with postgres_connection(settings.target.pg_url or "") as target:
            clients = _target_clients(target, contract, {
                record["subject"]["client_external_id"]
                for record in records if record["subject"].get("client_external_id")
            })
            type_ids = _target_type_ids(target, contract)
            existing = _target_snapshots(target, contract, set(keys))
        for record in records:
            key = record["source_key"]
            reason = record["issues"][0] if record["issues"] else None
            issues.update(record["issues"])
            client_id = clients.get(record["subject"].get("client_external_id"))
            type_id = type_ids.get(record["type_code"])
            current = existing.get(key)
            if key in duplicates:
                action, reason = "quarantine", "duplicate_alert_source_key"
            elif reason:
                action = "quarantine"
            elif client_id is None:
                action, reason = "quarantine", "missing_target_client"
            elif type_id is None:
                action, reason = "quarantine", "missing_target_alert_type"
            elif current and (
                not current["subjects"].issubset(_expected_subject(record, client_id))
                or not current["references"].issubset(_expected_references(record))
            ):
                action, reason = "quarantine", "target_source_children_require_removal"
            elif current and current["source_hash"] == record["source_hash"] \
                    and current["subjects"] == _expected_subject(record, client_id) \
                    and current["references"] == _expected_references(record):
                action, reason = "unchanged", None
            elif current:
                action, reason = "update", None
            else:
                action, reason = "create", None
            actions.append({
                "source_key": key,
                "source_hash": record["source_hash"],
                "action": action,
                "reason": reason,
                "target_id": str(current["id"]) if current else None,
                "client_id": str(client_id) if client_id is not None else None,
                "alert_type_id": str(type_id) if type_id is not None else None,
            })
            if reason and reason not in record["issues"]:
                issues[reason] += 1
    counts = Counter(item["action"] for item in actions)
    document = {
        "applicable": inspection["ready"],
        "scope": {
            "mode": "explicit-source-keys" if selected else "full-block",
            "requested_source_keys": selected,
            "alert_count": len(records),
            "subject_count": len(records),
            "reference_count": sum(len(record["references"]) for record in records),
        },
        "counts": dict(counts),
        "issues": dict(issues),
        "readiness_blocker_count": len(inspection["blockers"]),
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
        raise RuntimeError("psycopg is required for PostgreSQL AML writes") from exc
    with psycopg.connect(url, autocommit=False) as conn:
        yield conn


def _write_batch(conn: Any, contract: AmlAlertContract,
                 items: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, str]:
    target = contract.raw["target"]
    alert_values = []
    for action, record in items:
        alert_values.append((
            int(action["alert_type_id"]), target["initial_status"], SOURCE_SYSTEM, record["source_key"],
            record["source_event_type_code"], record["source_status_code"],
            record["source_alert_class_code"], record["source_temporary"], record["occurred_at"],
            record["business_date"], record["detected_at"], record["source_message"],
            record["triggering_amount"], record["product_type_code"],
            canonical_json(record["payload"]), record["source_hash"],
        ))
    with conn.cursor() as cursor:
        cursor.executemany(
            f'''INSERT INTO "{target["alert_table"]}"
                (alert_type_id,status_code,source_system,source_alert_key,source_event_type_code,
                 source_status_code,source_alert_class_code,source_temporary,occurred_at,business_date,
                 detected_at,source_message,triggering_amount,product_type_code,source_payload,source_hash,
                 created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                ON CONFLICT (source_system,source_alert_key) DO UPDATE SET
                  alert_type_id=EXCLUDED.alert_type_id,source_event_type_code=EXCLUDED.source_event_type_code,
                  source_status_code=EXCLUDED.source_status_code,
                  source_alert_class_code=EXCLUDED.source_alert_class_code,
                  source_temporary=EXCLUDED.source_temporary,occurred_at=EXCLUDED.occurred_at,
                  business_date=EXCLUDED.business_date,detected_at=EXCLUDED.detected_at,
                  source_message=EXCLUDED.source_message,triggering_amount=EXCLUDED.triggering_amount,
                  product_type_code=EXCLUDED.product_type_code,source_payload=EXCLUDED.source_payload,
                  source_hash=EXCLUDED.source_hash,updated_at=CURRENT_TIMESTAMP''',
            alert_values,
        )
    source_keys = [record["source_key"] for _, record in items]
    target_ids = {
        str(source_key): int(identifier)
        for identifier, source_key in conn.execute(
            f'SELECT id,source_alert_key FROM "{target["alert_table"]}" '
            'WHERE source_system=%s AND source_alert_key=ANY(%s)',
            (SOURCE_SYSTEM, source_keys),
        ).fetchall()
    }
    if set(target_ids) != set(source_keys):
        raise AmlAlertDataIssue("written_alert_identity_not_recovered")
    subject_values = []
    reference_values = []
    history_values = []
    for action, record in items:
        alert_id = target_ids[record["source_key"]]
        subject = record["subject"]
        subject_values.append((
            alert_id, subject["subject_type"], subject["subject_role"], int(action["client_id"]),
            SOURCE_SYSTEM, subject["source_subject_type"], subject["source_subject_key"],
            subject["primary_subject"],
        ))
        for reference in record["references"]:
            reference_values.append((
                alert_id, reference["relationship_type"], SOURCE_SYSTEM,
                reference["source_entity_type"], reference["source_entity_key"],
                reference["source_reference_key"], reference["occurred_at"], reference["amount"],
                reference["currency_code"], canonical_json(reference["details"]),
            ))
        history_values.append((alert_id, target["initial_status"]))
    with conn.cursor() as cursor:
        cursor.executemany(
            f'''INSERT INTO "{target["subject_table"]}"
                (alert_id,subject_type,subject_role,client_id,source_system,source_subject_type,
                 source_subject_key,primary_subject,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
                ON CONFLICT (alert_id,subject_type,subject_role,source_system,source_subject_type,source_subject_key)
                DO UPDATE SET client_id=EXCLUDED.client_id,primary_subject=EXCLUDED.primary_subject''',
            subject_values,
        )
        if reference_values:
            cursor.executemany(
                f'''INSERT INTO "{target["reference_table"]}"
                    (alert_id,relationship_type,source_system,source_entity_type,source_entity_key,
                     source_reference_key,occurred_at,amount,currency_code,details_json,created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
                ON CONFLICT (alert_id,relationship_type,source_system,source_entity_type,source_entity_key,source_reference_key)
                DO UPDATE SET source_reference_key=EXCLUDED.source_reference_key,
                      occurred_at=EXCLUDED.occurred_at,amount=EXCLUDED.amount,
                      currency_code=EXCLUDED.currency_code,details_json=EXCLUDED.details_json''',
                reference_values,
            )
        cursor.executemany(
            f'''INSERT INTO "{target["status_history_table"]}"
                (alert_id,previous_status_code,status_code,reason_code,comment_text,changed_by,changed_at)
                SELECT %s,NULL,%s,'SOURCE_IMPORT','Initial status created by Arissto AML synchronization',NULL,CURRENT_TIMESTAMP
                WHERE NOT EXISTS (
                    SELECT 1 FROM "{target["status_history_table"]}" WHERE alert_id=%s
                )''',
            [(alert_id, status, alert_id) for alert_id, status in history_values],
        )
    return {key: str(identifier) for key, identifier in target_ids.items()}


def _apply_guard(settings: Settings, state: State, contract: AmlAlertContract,
                 plan_id: str, production_confirmation: str | None,
                 source_conn: Any | None = None) -> dict[str, Any]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK:
        raise ValueError("Plan is not an AML alert plan")
    if plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Plan target fingerprint does not match selected target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source):
        raise RuntimeError("Plan source fingerprint no longer matches")
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("AML alert contract changed after planning")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_aml_alerts(settings, contract, source_conn=source_conn)
    if not inspection["ready"] or inspection["schema_signature"] != plan["document"]["schema_signature"]:
        raise RuntimeError("AML destination readiness/schema changed after planning")
    if not plan["document"].get("applicable"):
        raise RuntimeError("AML alert plan is not applicable")
    return plan


def _record_successes(state: State, settings: Settings, run_id: str, items: list[tuple[dict[str, Any], dict[str, Any]]],
                      target_ids: dict[str, str]) -> None:
    now = datetime.utcnow().isoformat()
    state.record_items([
        (run_id, action["source_key"], action["action"], action["source_hash"],
         target_ids[action["source_key"]], "succeeded", None)
        for action, _ in items
    ])
    state.save_mappings([
        (settings.target.fingerprint, BLOCK, action["source_key"], target_ids[action["source_key"]],
         action["source_hash"], now)
        for action, _ in items
    ])


def apply_aml_alert_plan(settings: Settings, state: State, contract: AmlAlertContract, plan_id: str,
                         production_confirmation: str | None = None,
                         source_keys: set[str] | None = None) -> tuple[str, dict[str, int]]:
    records: dict[str, dict[str, Any]] = {}
    with source_connection(settings.source) as source:
        plan = _apply_guard(
            settings, state, contract, plan_id, production_confirmation, source_conn=source
        )
        actions = [
            action for action in plan["document"]["actions"]
            if source_keys is None or action["source_key"] in source_keys
        ]
        if actions:
            records = {
                record["source_key"]: record
                for record in extract_aml_alerts(source, contract, [action["source_key"] for action in actions])
            }
    run_id = state.start_run(plan)
    counts = Counter()
    writable: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for action in actions:
        if action["action"] in {"unchanged", "quarantine"}:
            status = "unchanged" if action["action"] == "unchanged" else "quarantined"
            state.record_item(
                run_id, action["source_key"], action["action"], action["source_hash"],
                status, action.get("target_id"), action.get("reason"),
            )
            counts[status] += 1
            continue
        record = records.get(action["source_key"])
        if record is None or record["source_hash"] != action["source_hash"]:
            state.record_item(
                run_id, action["source_key"], action["action"], action["source_hash"],
                "failed", action.get("target_id"), "AmlAlertDataIssue:source_changed_after_plan",
            )
            counts["failed"] += 1
            continue
        writable.append((action, record))

    with _postgres_write_connection(settings.target.pg_url or "") as target:
        writer = ControlledSqlWriter(target, BLOCK)
        for batch in _chunks(writable, contract.batch_size):
            try:
                with writer.entity_transaction("upsert_aml_alerts"):
                    target_ids = _write_batch(target, contract, batch)
                _record_successes(state, settings, run_id, batch, target_ids)
                counts["succeeded"] += len(batch)
            except Exception:
                # A failed batch is already rolled back. Retry one alert at a time so a
                # single malformed destination row does not block the remaining batch.
                for item in batch:
                    action, _ = item
                    try:
                        with writer.entity_transaction("upsert_aml_alerts"):
                            target_ids = _write_batch(target, contract, [item])
                        _record_successes(state, settings, run_id, [item], target_ids)
                        counts["succeeded"] += 1
                    except Exception as exc:
                        state.record_item(
                            run_id, action["source_key"], action["action"], action["source_hash"],
                            "failed", action.get("target_id"), type(exc).__name__,
                        )
                        counts["failed"] += 1
    status = "completed" if counts["failed"] == 0 and counts["quarantined"] == 0 else "completed-with-errors"
    state.finish_run(run_id, status, dict(counts))
    return run_id, dict(counts)


def reconcile_aml_alerts(settings: Settings, state: State, contract: AmlAlertContract,
                         run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("AML alert run does not belong to the selected target")
    plan = state.plan(run["plan_id"])
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("AML alert run belongs to a stale contract")
    items = state.run_items(run_id)
    keys = {item["source_key"] for item in items if item["status"] in {"succeeded", "unchanged"}}
    records: dict[str, dict[str, Any]] = {}
    if keys:
        with source_connection(settings.source) as source:
            records = {record["source_key"]: record for record in extract_aml_alerts(source, contract, keys)}
    action_index = {item["source_key"]: item for item in plan["document"]["actions"]}
    with postgres_connection(settings.target.pg_url or "") as target:
        snapshots = _target_snapshots(target, contract, keys)
    counts = Counter()
    mismatches: list[dict[str, str]] = []
    for key in sorted(keys):
        record = records.get(key)
        snapshot = snapshots.get(key)
        action = action_index.get(key, {})
        client_id = int(action["client_id"]) if action.get("client_id") else None
        if record is None:
            reason = "source_missing"
        elif snapshot is None:
            reason = "target_missing"
        elif client_id is None:
            reason = "target_client_missing"
        elif snapshot["source_hash"] != record["source_hash"]:
            reason = "source_hash_mismatch"
        elif snapshot["type_code"] != record["type_code"]:
            reason = "alert_type_mismatch"
        elif snapshot["header"] != _expected_header(record):
            reason = "alert_header_mismatch"
        elif snapshot["subject_values"] != _expected_subject_values(record, client_id):
            reason = "subject_mismatch"
        elif snapshot["reference_values"] != _expected_reference_values(record):
            reason = "reference_mismatch"
        else:
            reason = None
        if reason:
            counts["mismatch"] += 1
            mismatches.append({"source_key": key, "reason": reason})
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
