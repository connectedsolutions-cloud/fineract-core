from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

from .arissto import IDENTIFIER, select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import postgres_connection, postgres_schema
from .sql_writer import ControlledSqlWriter
from .state import State, now


BLOCK = "dte-history"
OPERATION = "create_historical_dte"
SOURCE_ORIGIN = "ARISSTO_HISTORY"
DEFAULT_DTE_WORKERS = 2
DEFAULT_DTE_BATCH_SIZE = 500
MAX_DTE_WORKERS = 4
MAX_DTE_BATCH_SIZE = 2000
NON_DURABLE_SOURCE_FIELDS = {
    "company_id", "branch_id", "fiscal_movement_id", "global_fiscal_id",
    "projection_pk", "source_document_path",
}
TARGET_TABLES = (
    "m_invoice", "m_invoice_issuer", "m_invoice_receiver", "m_invoice_line",
    "m_invoice_summary",
)
REQUIRED_TARGET_COLUMNS = {
    "m_invoice": {"id", "status", "loan_transaction_id", "version", "ambiente", "tipo_dte",
                  "numero_control", "codigo_generacion", "tipo_modelo", "tipo_operacion",
                  "fec_emi", "hor_emi", "tipo_moneda", "createdby_id", "created_date",
                  "lastmodifiedby_id", "lastmodified_date", "source_origin", "source_hash",
                  "source_lifecycle_json"},
    "m_invoice_issuer": {"invoice_id", "nombre"},
    "m_invoice_receiver": {"invoice_id", "nombre", "tipo_documento"},
    "m_invoice_line": {"invoice_id", "num_item", "tipo_item", "cantidad", "descripcion", "precio_uni"},
    "m_invoice_summary": {"invoice_id", "monto_total_operacion", "total_pagar", "total_iva"},
}
MH_ISSUER_FIELDS = (
    "nit", "nrc", "nombre", "nombre_comercial", "cod_actividad", "desc_actividad",
    "tipo_establecimiento", "direccion_departamento", "direccion_municipio",
    "direccion_complemento", "telefono", "correo",
)
MH_ISSUER_REQUIRED_FIELDS = MH_ISSUER_FIELDS


def clean(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


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
    encoded = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _decimal(value: Any) -> Decimal:
    return Decimal("0") if value is None else Decimal(str(value))


@dataclass(frozen=True)
class DteHistoryContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "DteHistoryContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("version") != 1:
            raise ValueError("Unsupported DTE history contract version")
        if value.get("depends_on") != ["clients", "loans"]:
            raise ValueError("DTE history dependency order changed")
        source = value.get("source", {})
        target = value.get("target", {})
        identifiers = [*source.values(), target.get("invoice_table")]
        if not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Unsafe table identifier in DTE history contract")
        if source != {
            "fiscal_table": "FAC_MOVIMIENTOS",
            "projection_table": "comprobantes",
            "line_table": "comprobante_detalles",
            "loan_movement_table": "CRD_MOVIMIENTOS_CARTERA",
        }:
            raise ValueError("DTE history source table contract changed")
        if target.get("invoice_table") != "m_invoice" or target.get("source_origin") != SOURCE_ORIGIN:
            raise ValueError("DTE history target table contract changed")
        if target.get("ambiente") not in {"00", "01"} or target.get("tipo_moneda") != "USD":
            raise ValueError("DTE history target defaults are invalid")
        issuer_bootstrap = target.get("issuer_bootstrap", {})
        issuer = issuer_bootstrap.get("issuer", {})
        if (
            issuer_bootstrap.get("mode") != "reviewed-static-identity"
            or set(issuer) != set(MH_ISSUER_FIELDS)
            or any(not clean(issuer.get(field)) for field in MH_ISSUER_FIELDS)
        ):
            raise ValueError("DTE history issuer bootstrap contract is invalid")
        if value.get("scope") != {
            "tipo_dte": "01", "requires_normalized_detail": True,
            "requires_exactly_one_loan_movement": True,
        }:
            raise ValueError("DTE history v1 cohort changed")
        if value.get("missing_normal_mode") != {
            "model_type": 1, "operation_type": 1,
            "requires_no_contingency_signal": True,
        }:
            raise ValueError("DTE history missing-mode fallback changed")
        if value.get("write_policy") != {
            "historical_invoice_tables": "controlled-parameterized-sql-create-only",
            "mh_submission": "forbidden", "native_financial_tables": "forbidden",
            "update": "forbidden", "delete": "forbidden",
        }:
            raise ValueError("DTE history write boundary changed")
        return cls(value)

    @property
    def contract_hash(self) -> str:
        return _hash(self.raw)

    @property
    def ambiente(self) -> str:
        return self.raw["target"]["ambiente"]

    def source_hash(self, row: dict[str, Any]) -> str:
        durable_source = {key: value for key, value in row.items() if key not in NON_DURABLE_SOURCE_FIELDS}
        return _hash({"contract": self.contract_hash, "source": durable_source})


def _pg_database(url: str) -> str:
    database = urlsplit(url).path.lstrip("/")
    if not database or "/" in database:
        raise ValueError("PostgreSQL URL must identify exactly one database")
    return database


def _mh_config(conn: Any) -> dict[str, Any] | None:
    rows = _pg_dicts(
        conn,
        f"SELECT {','.join(MH_ISSUER_FIELDS)} FROM m_mh_company_config WHERE id=1",
    )
    if len(rows) > 1:
        raise RuntimeError("MH company configuration singleton is not unique")
    return rows[0] if rows else None


def _missing_mh_fields(config: dict[str, Any] | None) -> list[str]:
    if config is None:
        return list(MH_ISSUER_REQUIRED_FIELDS)
    return [field for field in MH_ISSUER_REQUIRED_FIELDS if not clean(config.get(field))]


def _merge_mh_config(
    current: dict[str, Any] | None, template: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(template)
    if current is None:
        return merged
    for field in MH_ISSUER_FIELDS:
        current_value = current.get(field)
        if clean(current_value):
            merged[field] = current_value
    return merged


@contextmanager
def _writable_postgres(url: str) -> Iterator[Any]:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for PostgreSQL prerequisite provisioning") from exc
    with psycopg.connect(url, autocommit=False) as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def prepare_dte_history_target(
    settings: Settings, contract: DteHistoryContract,
) -> dict[str, Any]:
    """Fill missing MH issuer identity from reviewed, non-secret contract values."""
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for DTE issuer provisioning")

    bootstrap = contract.raw["target"]["issuer_bootstrap"]
    target_database = _pg_database(settings.target.pg_url)
    with _writable_postgres(settings.target.pg_url) as target_conn:
        current = _mh_config(target_conn)
        missing = _missing_mh_fields(current)
        if not missing:
            return {"performed": False, "action": "unchanged", "missing_fields": []}

        template = bootstrap["issuer"]
        merged = _merge_mh_config(current, template)

        columns = ",".join(("id", *MH_ISSUER_FIELDS))
        placeholders = ",".join(["%s"] * (len(MH_ISSUER_FIELDS) + 1))
        assignments = ",".join(f"{field}=EXCLUDED.{field}" for field in MH_ISSUER_FIELDS)
        target_conn.execute(
            f"INSERT INTO m_mh_company_config ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT (id) DO UPDATE SET {assignments}",
            (1, *(merged[field] for field in MH_ISSUER_FIELDS)),
        )
        refreshed = _mh_config(target_conn)
        remaining = _missing_mh_fields(refreshed)
        if remaining:
            raise RuntimeError(
                "Target MH issuer configuration failed verification: " + ", ".join(remaining)
            )
        return {
            "performed": True,
            "action": "created" if current is None else "repaired",
            "filled_fields": missing,
            "target_database": target_database,
        }


@dataclass(frozen=True)
class DteApplyControls:
    workers: int = DEFAULT_DTE_WORKERS
    batch_size: int = DEFAULT_DTE_BATCH_SIZE

    @classmethod
    def configured(
        cls, workers: int | None = None, batch_size: int | None = None,
    ) -> "DteApplyControls":
        defaults = cls(
            workers=int(os.getenv("ARISSTO_SYNC_DTE_WORKERS", str(DEFAULT_DTE_WORKERS))),
            batch_size=int(os.getenv("ARISSTO_SYNC_DTE_BATCH_SIZE", str(DEFAULT_DTE_BATCH_SIZE))),
        )
        return cls(
            workers=defaults.workers if workers is None else workers,
            batch_size=defaults.batch_size if batch_size is None else batch_size,
        )

    def __post_init__(self) -> None:
        if not 1 <= self.workers <= MAX_DTE_WORKERS:
            raise ValueError(f"DTE workers must be between 1 and {MAX_DTE_WORKERS}")
        if not 1 <= self.batch_size <= MAX_DTE_BATCH_SIZE:
            raise ValueError(f"DTE batch size must be between 1 and {MAX_DTE_BATCH_SIZE}")


HEADER_QUERY = """
WITH loan_links AS (
    SELECT ID_EMPRESA,ID_SUCURSAL,ID_FAC_MOVIMIENTO,
           MIN(ID_MOVIMIENTO_CARTERA) AS loan_movement_id,COUNT_BIG(*) AS loan_link_count
    FROM dbo.CRD_MOVIMIENTOS_CARTERA
    WHERE ID_FAC_MOVIMIENTO IS NOT NULL
    GROUP BY ID_EMPRESA,ID_SUCURSAL,ID_FAC_MOVIMIENTO
), detail_keys AS (
    SELECT DISTINCT fk_comprobante FROM facturacion.comprobante_detalles
)
SELECT f.ID_EMPRESA AS company_id,f.ID_SUCURSAL AS branch_id,
       f.ID_FAC_MOVIMIENTO AS fiscal_movement_id,f.ID_FACT_MOVIMIENTO AS global_fiscal_id,
       c.pk AS projection_pk,f.CODIGO_GENERACION AS generation_code,
       f.NUMERO_CONTROL AS control_number,ll.loan_movement_id,
       s.NUMERO_AFILIACION AS client_external_id,t.version_json AS dte_version,
       c.tipodocumento AS dte_type,c.tipomodelo AS model_type,c.tipooperacion AS operation_type,
       c.fecha_emision AS emission_at,
       COALESCE(c.tipocontingencia,TRY_CONVERT(INT,c.tipo_contingencia)) AS contingency_type,
       COALESCE(c.motivocontin,c.motivo_contingencia) AS contingency_reason,f.ANULADO AS annulled,
       f.INVALIDADO AS invalidated,f.DTE_ESTADO AS dte_state,
       f.DTE_MOTIVO_ERROR AS authority_error,f.DTE_OBSERVACION AS authority_observation,
       f.SELLO_RECEPCION AS reception_seal,f.DT_ENVIO_MH AS submitted_at,
       f.DT_RECEPCION_MH AS received_at,f.DT_ANULA AS annulled_at,
       f.URL_DTE AS source_document_path,c.tipodocumentocliente AS receiver_document_type,
       c.documentocliente AS receiver_document,c.nit AS receiver_nit,c.nrc AS receiver_nrc,
       c.nombre AS receiver_name,c.codactividad AS receiver_activity_code,
       c.descactividad AS receiver_activity_description,c.departamento AS receiver_department,
       c.municipio AS receiver_municipality,c.distrito AS receiver_district,
       c.direccion AS receiver_address,c.telefono AS receiver_phone,c.correo AS receiver_email,
       c.v_no_sujeto AS total_non_subject,c.vex AS total_exempt,
       c.totalgravada AS total_taxable,c.subtotalventas AS subtotal_sales,
       c.totaldescuento AS total_discount,c.subtotal AS subtotal,c.monto_iva AS iva_amount,
       c.ivaretenido AS iva_withheld,c.retencionrenta AS income_withheld,
       c.v_total AS total_operation,c.totalletras AS total_words,
       c.condicionoperacion AS operation_condition
FROM dbo.FAC_MOVIMIENTOS f
JOIN facturacion.comprobantes c
  ON c.codigo_generacion=f.CODIGO_GENERACION AND c.numero_control=f.NUMERO_CONTROL
JOIN detail_keys d ON d.fk_comprobante=c.pk
JOIN loan_links ll ON ll.ID_EMPRESA=f.ID_EMPRESA AND ll.ID_SUCURSAL=f.ID_SUCURSAL
  AND ll.ID_FAC_MOVIMIENTO=f.ID_FAC_MOVIMIENTO AND ll.loan_link_count=1
JOIN dbo.CLIENTE cli ON cli.ID_CLIENTE=f.ID_CLIENTE
JOIN dbo.AFI_SOCIO s ON s.ID_EMPRESA=cli.ID_EMPRESA AND s.ID_SUCURSAL=cli.ID_SUCURSAL
  AND s.ID_SOCIO=cli.ID_SOCIO
LEFT JOIN facturacion.tipos_dte t ON t.id_tipo_dte=c.tipodocumento
WHERE f.CODIGO_GENERACION IS NOT NULL AND c.tipodocumento='01'
ORDER BY f.CODIGO_GENERACION
"""

LINE_QUERY = """
SELECT c.codigo_generacion AS generation_code,d.numitem AS item_number,
       d.tipoitem AS item_type,d.cantidad AS quantity,d.unimedida AS unit_measure,
       d.descripcion AS description,d.preciouni AS unit_price,d.descuento AS discount,
       d.venta_no_sujeta AS non_subject_sale,d.venta_exenta AS exempt_sale,
       d.ventagravada AS taxable_sale,d.ventanoafecta AS non_taxed_amount,
       d.tributoscodigo AS tax_code
FROM facturacion.comprobantes c
JOIN facturacion.comprobante_detalles d ON d.fk_comprobante=c.pk
WHERE c.codigo_generacion IS NOT NULL AND c.tipodocumento='01'
ORDER BY c.codigo_generacion,d.numitem
"""


def source_key(row: dict[str, Any]) -> str:
    value = clean(row.get("generation_code"))
    if not value:
        raise ValueError("DTE history row has no generation code")
    return value.upper()


def extract_dte_history(settings: Settings) -> list[dict[str, Any]]:
    with source_connection(settings.source) as conn:
        headers = select_rows(conn, HEADER_QUERY)
        lines = select_rows(conn, LINE_QUERY)
    by_code: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        by_code.setdefault(source_key(line), []).append(line)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for header in headers:
        key = source_key(header)
        if key in seen:
            raise RuntimeError(f"Duplicate eligible DTE generation code: {key}")
        seen.add(key)
        result.append({**header, "lines": by_code.get(key, [])})
    return result


def lifecycle_status(row: dict[str, Any]) -> str | None:
    if clean(row.get("annulled")) in {"1", "S", "Y"}:
        return "VOIDED"
    if clean(row.get("reception_seal")):
        return "ACCEPTED"
    if row.get("dte_state") == 3 and clean(row.get("authority_error")):
        return "REJECTED"
    return None


def _payload(row: dict[str, Any], contract: DteHistoryContract,
             catalog: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    key = source_key(row)
    try:
        uuid.UUID(key)
    except ValueError:
        return None, "invalid_generation_uuid"
    if len(clean(row.get("control_number")) or "") != 31:
        return None, "invalid_control_number"
    if row.get("dte_version") is None:
        return None, "missing_dte_identification"
    model_type = row.get("model_type")
    operation_type = row.get("operation_type")
    if model_type is None and operation_type is None:
        has_contingency_signal = (
            row.get("contingency_type") is not None
            or clean(row.get("contingency_reason")) is not None
        )
        if has_contingency_signal:
            return None, "missing_dte_identification"
        fallback = contract.raw["missing_normal_mode"]
        model_type = fallback["model_type"]
        operation_type = fallback["operation_type"]
    elif model_type is None or operation_type is None:
        return None, "missing_dte_identification"
    if len(clean(row.get("contingency_reason")) or "") > 255:
        return None, "contingency_reason_too_long"
    emitted = row.get("emission_at")
    if not isinstance(emitted, datetime):
        return None, "missing_emission_timestamp"
    status = lifecycle_status(row)
    if status is None:
        return None, "unsupported_lifecycle"
    client_id = catalog["clients"].get(clean(row.get("client_external_id")))
    transaction = catalog["transactions"].get(
        f"ARISSTO:CRD-MOV:{clean(row.get('loan_movement_id'))}"
    )
    if client_id is None:
        return None, "missing_target_client"
    if transaction is None:
        return None, "missing_target_loan_transaction"
    if int(transaction["client_id"]) != int(client_id):
        return None, "client_loan_mismatch"
    lines = []
    discounts = {"non_subject": Decimal("0"), "exempt": Decimal("0"), "taxable": Decimal("0")}
    for line in row["lines"]:
        if line.get("item_type") is None or line.get("quantity") is None or line.get("unit_price") is None:
            return None, "missing_line_structure"
        description = clean(line.get("description"))
        if not description or len(description) > 500:
            return None, "invalid_line_description"
        tax_code = clean(line.get("tax_code"))
        discount = _decimal(line.get("discount"))
        if discount:
            categories = [
                name for name, field in (("non_subject", "non_subject_sale"),
                                         ("exempt", "exempt_sale"), ("taxable", "taxable_sale"))
                if _decimal(line.get(field)) != 0
            ]
            if len(categories) != 1:
                return None, "ambiguous_discount_category"
            discounts[categories[0]] += discount
        lines.append({
            "num_item": int(line["item_number"]), "tipo_item": int(line["item_type"]),
            "cantidad": line["quantity"], "uni_medida": line.get("unit_measure"),
            "descripcion": description, "precio_uni": line["unit_price"],
            "monto_descu": line.get("discount"), "venta_no_suj": line.get("non_subject_sale"),
            "venta_exenta": line.get("exempt_sale"), "venta_gravada": line.get("taxable_sale"),
            "tributos_json": [tax_code] if tax_code else None,
            "no_gravado": line.get("non_taxed_amount"),
        })
    if not lines or len({line["num_item"] for line in lines}) != len(lines):
        return None, "invalid_line_identity"
    if abs(sum(discounts.values()) - _decimal(row.get("total_discount"))) >= Decimal("0.005"):
        return None, "discount_total_mismatch"
    receiver_type = clean(row.get("receiver_document_type"))
    receiver_name = clean(row.get("receiver_name"))
    if not receiver_name:
        return None, "missing_receiver_name"
    receiver_limits = {
        "receiver_nit": 20, "receiver_document": 30, "receiver_nrc": 20,
        "receiver_email": 100,
    }
    if any(len(clean(row.get(field)) or "") > limit for field, limit in receiver_limits.items()):
        return None, "receiver_value_too_long"
    address = clean(row.get("receiver_address"))
    district = clean(row.get("receiver_district"))
    if district:
        address = f"{address}; distrito: {district}" if address else f"Distrito: {district}"
    if len(address or "") > 255:
        return None, "receiver_address_too_long"
    target_receiver_type = receiver_type if len(receiver_type or "") <= 5 else None
    return {
        "invoice": {
            "status": status, "loan_transaction_id": int(transaction["id"]),
            "source_origin": SOURCE_ORIGIN,
            "source_lifecycle_json": json.dumps({
                "dteState": row.get("dte_state"),
                "annulled": clean(row.get("annulled")),
                "invalidated": clean(row.get("invalidated")),
            }, sort_keys=True, separators=(",", ":")),
            "version": int(row["dte_version"]), "ambiente": contract.ambiente,
            "tipo_dte": clean(row.get("dte_type")), "numero_control": clean(row.get("control_number")),
            "codigo_generacion": key, "tipo_modelo": int(model_type),
            "tipo_operacion": int(operation_type), "fec_emi": emitted.date(),
            "hor_emi": emitted.time(), "tipo_moneda": contract.raw["target"]["tipo_moneda"],
            "tipo_contingencia": row.get("contingency_type"),
            "motivo_contin": clean(row.get("contingency_reason")),
            "sello_recibido": clean(row.get("reception_seal")), "authority_status": status,
            "authority_message": clean(row.get("authority_error")) or clean(row.get("authority_observation")),
            "authority_processed_at": row.get("annulled_at") or row.get("received_at") or row.get("submitted_at"),
            "mh_transmission_status": status, "mh_last_error": clean(row.get("authority_error")),
            "mh_validation_status": status, "mh_submitted_at": row.get("submitted_at"),
            "mh_processed_at": row.get("received_at") or row.get("annulled_at"),
        },
        "issuer": catalog["issuer"],
        "receiver": {
            "nit": clean(row.get("receiver_nit")), "doc_id": clean(row.get("receiver_document")),
            "nrc": clean(row.get("receiver_nrc")), "nombre": receiver_name,
            "cod_actividad": clean(row.get("receiver_activity_code")),
            "desc_actividad": clean(row.get("receiver_activity_description")),
            "direccion_departamento": clean(row.get("receiver_department")),
            "direccion_municipio": clean(row.get("receiver_municipality")),
            "direccion_complemento": address, "telefono": clean(row.get("receiver_phone")),
            "correo": clean(row.get("receiver_email")), "tipo_documento": target_receiver_type,
        },
        "lines": lines,
        "summary": {
            "total_no_suj": row.get("total_non_subject"), "total_exenta": row.get("total_exempt"),
            "total_gravada": row.get("total_taxable"), "sub_total_ventas": row.get("subtotal_sales"),
            "descu_no_suj": discounts["non_subject"], "descu_exenta": discounts["exempt"],
            "descu_gravada": discounts["taxable"], "sub_total": row.get("subtotal"),
            "total_iva": row.get("iva_amount"),
            "iva_retenido": row.get("iva_withheld"), "rete_renta": row.get("income_withheld"),
            "monto_total_operacion": row.get("total_operation"), "total_pagar": row.get("total_operation"),
            "total_letras": clean(row.get("total_words")),
            "condicion_operacion": int(row["operation_condition"]) if row.get("operation_condition") is not None else None,
        },
        "links": {"client_id": int(client_id)},
    }, None


def _pg_dicts(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _target_catalog(conn: Any, settings: Settings) -> dict[str, Any]:
    clients = {clean(ext): int(identifier) for identifier, ext in conn.execute(
        "SELECT id,external_id FROM m_client WHERE external_id IS NOT NULL"
    ).fetchall()}
    transactions: dict[str, dict[str, int]] = {}
    for identifier, external_id, client_id in conn.execute("""
        SELECT t.id,t.external_id,l.client_id FROM m_loan_transaction t
        JOIN m_loan l ON l.id=t.loan_id WHERE t.external_id IS NOT NULL
    """).fetchall():
        key = clean(external_id)
        if key in transactions:
            raise RuntimeError("Duplicate target loan transaction external ID")
        transactions[key] = {"id": int(identifier), "client_id": int(client_id)}
    issuer_rows = _pg_dicts(conn, """
        SELECT nit,nrc,nombre,cod_actividad,desc_actividad,nombre_comercial,
               tipo_establecimiento,direccion_departamento,direccion_municipio,
               direccion_complemento,telefono,correo,NULL::varchar AS cod_estable_mh,
               NULL::varchar AS cod_estable,NULL::varchar AS cod_punto_venta_mh,
               NULL::varchar AS cod_punto_venta
        FROM m_mh_company_config WHERE id=1
    """)
    issuer = issuer_rows[0] if issuer_rows else {}
    users = conn.execute("SELECT id FROM m_appuser WHERE username=%s", (settings.target.api_user,)).fetchall()
    existing = {
        clean(row[0]): {"invoice_id": int(row[1]), "source_hash": clean(row[2])}
        for row in conn.execute(
            "SELECT codigo_generacion,id,source_hash FROM m_invoice WHERE source_origin=%s",
            (SOURCE_ORIGIN,),
        ).fetchall()
    }
    legal = {}
    for identifier, generation, control in conn.execute(
        "SELECT id,codigo_generacion,numero_control FROM m_invoice"
    ).fetchall():
        legal[clean(generation)] = int(identifier)
        legal[clean(control)] = int(identifier)
    return {
        "clients": clients, "transactions": transactions, "issuer": issuer,
        "audit_user_id": int(users[0][0]) if len(users) == 1 else None,
        "existing": existing, "legal": legal,
    }


def _schema_signature(source_schema: dict[str, Any], target_schema: dict[str, Any]) -> str:
    return _hash({"source": source_schema, "target": target_schema})


def inspect_dte_history(settings: Settings, contract: DteHistoryContract) -> dict[str, Any]:
    blockers: list[Any] = []
    source_schema: dict[str, Any] = {}
    counts: dict[str, int] = {}
    try:
        rows = extract_dte_history(settings)
        counts["eligible_source_documents"] = len(rows)
        counts["eligible_source_lines"] = sum(len(row["lines"]) for row in rows)
        source_schema = {"header": sorted(rows[0]) if rows else [], "line": sorted(rows[0]["lines"][0]) if rows and rows[0]["lines"] else []}
    except Exception as exc:
        blockers.append({"source_extraction": type(exc).__name__})
    target_schema: dict[str, Any] = {}
    target_counts: dict[str, int] = {}
    if not settings.target.pg_url:
        blockers.append({"target": "postgres_inspection_required"})
    else:
        try:
            with postgres_connection(settings.target.pg_url) as conn:
                target_schema = postgres_schema(conn, list(TARGET_TABLES))
                missing_tables = [table for table in TARGET_TABLES if not target_schema.get(table)]
                if missing_tables:
                    blockers.append({"target_tables_missing": missing_tables})
                else:
                    target_shape_blockers = []
                    for table, required in REQUIRED_TARGET_COLUMNS.items():
                        missing = sorted(required - set(target_schema[table]))
                        if missing:
                            target_shape_blockers.append({"target_table": table, "missing_columns": missing})
                    blockers.extend(target_shape_blockers)
                    if not target_shape_blockers:
                        catalog = _target_catalog(conn, settings)
                        if not catalog["audit_user_id"]:
                            blockers.append({"target": "unique_api_audit_user_required"})
                        missing_issuer_fields = _missing_mh_fields(catalog["issuer"])
                        if missing_issuer_fields:
                            blockers.append({
                                "target": "mh_issuer_configuration_required",
                                "missing_fields": missing_issuer_fields,
                            })
                        target_counts["imported_documents"] = len(catalog["existing"])
        except Exception as exc:
            blockers.append({"target_inspection": type(exc).__name__})
    return {
        "block": BLOCK, "ready": not blockers, "target_fingerprint": settings.target.fingerprint,
        "contract_hash": contract.contract_hash,
        "schema_signature": _schema_signature(source_schema, target_schema),
        "depends_on": contract.raw["depends_on"], "source": {"counts": counts},
        "target": {"counts": target_counts}, "blockers": blockers,
        "scope": "ordinary DTEs with normalized lines, client, and exactly one loan movement",
        "write_boundary": "create-only terminal invoice history; no MH or financial writes",
    }


def build_dte_history_plan(settings: Settings, state: State, contract: DteHistoryContract,
                           source_keys: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    inspection = inspect_dte_history(settings, contract)
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for DTE history planning")
    rows = extract_dte_history(settings)
    wanted = {key.upper() for key in (source_keys or [])}
    known = {source_key(row) for row in rows}
    missing = sorted(wanted - known)
    if missing:
        raise ValueError(f"Unknown DTE history source keys: {missing}")
    with postgres_connection(settings.target.pg_url) as conn:
        catalog = _target_catalog(conn, settings)
    actions: list[dict[str, Any]] = []
    counts = Counter()
    for row in rows:
        key = source_key(row)
        if wanted and key not in wanted:
            continue
        row_hash = contract.source_hash(row)
        current = catalog["existing"].get(key)
        payload, issue = _payload(row, contract, catalog)
        if current:
            action = "unchanged" if current["source_hash"] == row_hash else "conflict"
            if action == "conflict":
                issue = "immutable_source_changed"
        elif key in catalog["legal"] or clean(row.get("control_number")) in catalog["legal"]:
            action, issue = "conflict", "legal_identity_owned_by_non_history_invoice"
        elif issue:
            action = "quarantine"
        else:
            action = "create"
        item = {"source_key": key, "source_hash": row_hash, "action": action,
                "target_id": current["invoice_id"] if current else None}
        if issue:
            item["reason"] = issue
        actions.append(item)
        counts[action] += 1
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
        raise RuntimeError("psycopg is required for DTE history writes") from exc
    with psycopg.connect(url, autocommit=False) as conn:
        yield conn


def _insert(conn: Any, payload: dict[str, Any], source_hash: str, audit_user_id: int) -> int:
    invoice = {**payload["invoice"], "source_hash": source_hash}
    invoice_columns = tuple(invoice)
    invoice_id = int(conn.execute(
        f"INSERT INTO m_invoice ({','.join(invoice_columns)},createdby_id,created_date,lastmodifiedby_id,lastmodified_date) "
        f"VALUES ({','.join(['%s'] * len(invoice_columns))},%s,CURRENT_TIMESTAMP,%s,CURRENT_TIMESTAMP) RETURNING id",
        (*[invoice[column] for column in invoice_columns], audit_user_id, audit_user_id),
    ).fetchone()[0])
    for table, values in (("m_invoice_issuer", payload["issuer"]),
                          ("m_invoice_receiver", payload["receiver"]),
                          ("m_invoice_summary", payload["summary"])):
        columns = tuple(values)
        conn.execute(
            f"INSERT INTO {table} (invoice_id,{','.join(columns)}) VALUES (%s,{','.join(['%s'] * len(columns))})",
            (invoice_id, *[values[column] for column in columns]),
        )
    for line in payload["lines"]:
        values = dict(line)
        values["tributos_json"] = json.dumps(values["tributos_json"]) if values["tributos_json"] else None
        columns = tuple(values)
        expressions = ["%s::jsonb" if column == "tributos_json" else "%s" for column in columns]
        conn.execute(
            f"INSERT INTO m_invoice_line (invoice_id,{','.join(columns)}) VALUES (%s,{','.join(expressions)})",
            (invoice_id, *[values[column] for column in columns]),
        )
    return invoice_id


def _chunks(values: list[Any], size: int) -> Iterator[list[Any]]:
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def _write_dte_batch(
    target_url: str, batch: list[tuple[dict[str, Any], dict[str, Any]]], audit_user_id: int,
) -> list[tuple[dict[str, Any], int]]:
    """Write one destination batch atomically using a worker-owned connection."""
    written: list[tuple[dict[str, Any], int]] = []
    with _write_connection(target_url) as conn:
        writer = ControlledSqlWriter(conn, BLOCK)
        with writer.entity_transaction(OPERATION):
            for action, payload in batch:
                target_id = _insert(conn, payload, action["source_hash"], audit_user_id)
                written.append((action, target_id))
    return written


def _write_dte_batch_resilient(
    target_url: str, batch: list[tuple[dict[str, Any], dict[str, Any]]], audit_user_id: int,
) -> tuple[list[tuple[dict[str, Any], int]], list[tuple[dict[str, Any], str]]]:
    """Split a rolled-back batch recursively until a bad DTE is isolated."""
    try:
        return _write_dte_batch(target_url, batch, audit_user_id), []
    except Exception as exc:
        if len(batch) == 1:
            return [], [(batch[0][0], f"{type(exc).__name__}:redacted")]
        midpoint = len(batch) // 2
        left_written, left_failed = _write_dte_batch_resilient(
            target_url, batch[:midpoint], audit_user_id,
        )
        right_written, right_failed = _write_dte_batch_resilient(
            target_url, batch[midpoint:], audit_user_id,
        )
        return left_written + right_written, left_failed + right_failed


def apply_dte_history_plan(settings: Settings, state: State, contract: DteHistoryContract,
                           plan_id: str, production_confirmation: str | None = None,
                           only_keys: set[str] | None = None,
                           controls: DteApplyControls | None = None) -> tuple[str, dict[str, int]]:
    controls = controls or DteApplyControls.configured()
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Plan belongs to a different block or target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source) or plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Plan is stale: source or DTE history contract changed")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_dte_history(settings, contract)
    if not inspection["ready"] or not plan["document"].get("applicable"):
        raise RuntimeError("DTE history plan is not applicable")
    if inspection["schema_signature"] != plan["document"].get("schema_signature"):
        raise RuntimeError("DTE history destination readiness changed; apply refused")
    rows = {source_key(row): row for row in extract_dte_history(settings)}
    selected = sorted(
        (item for item in plan["document"]["actions"] if only_keys is None or item["source_key"] in only_keys),
        key=lambda item: item["source_key"],
    )
    run_id, counts = state.start_run(plan), Counter()
    with _write_connection(settings.target.pg_url or "") as conn:
        catalog = _target_catalog(conn, settings)
    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
    journal: list[tuple[str, str, str, str, str | None, str, str | None]] = []
    for action in selected:
        key = action["source_key"]
        if action["action"] in {"quarantine", "conflict"}:
            journal.append((run_id, key, action["action"], action["source_hash"],
                            action.get("target_id"), "quarantined",
                            f"DteHistoryDataIssue:{action.get('reason')}"))
            counts["quarantined"] += 1
            continue
        if action["action"] == "unchanged":
            target_id = str(action.get("target_id")) if action.get("target_id") else None
            journal.append((run_id, key, "unchanged", action["source_hash"], target_id, "unchanged", None))
            counts["unchanged"] += 1
            continue
        row = rows.get(key)
        if row is None or contract.source_hash(row) != action["source_hash"]:
            journal.append((run_id, key, "create", action["source_hash"], None, "failed",
                            "RuntimeError:source_changed_after_plan"))
            counts["failed"] += 1
            continue
        payload, issue = _payload(row, contract, catalog)
        if issue or payload is None:
            journal.append((run_id, key, "create", action["source_hash"], None, "failed",
                            f"DteHistoryDataIssue:{issue}"))
            counts["failed"] += 1
            continue
        pending.append((action, payload))
    if journal:
        state.record_items(journal)

    target_url = settings.target.pg_url or ""
    batches = list(_chunks(pending, controls.batch_size))
    if batches:
        with ThreadPoolExecutor(
            max_workers=min(controls.workers, len(batches)), thread_name_prefix="arissto-dte",
        ) as executor:
            futures = [
                executor.submit(_write_dte_batch_resilient, target_url, batch, catalog["audit_user_id"])
                for batch in batches
            ]
            for future in as_completed(futures):
                written, failed = future.result()
                completed_at = now()
                mappings = [
                    (settings.target.fingerprint, BLOCK, action["source_key"], str(target_id),
                     action["source_hash"], completed_at)
                    for action, target_id in written
                ]
                items = [
                    (run_id, action["source_key"], "create", action["source_hash"],
                     str(target_id), "succeeded", None)
                    for action, target_id in written
                ]
                items.extend(
                    (run_id, action["source_key"], "create", action["source_hash"], None, "failed", error)
                    for action, error in failed
                )
                if mappings:
                    state.save_mappings(mappings)
                if items:
                    state.record_items(items)
                counts["create"] += len(written)
                counts["failed"] += len(failed)
    status = "completed_with_errors" if counts["failed"] else (
        "completed_with_quarantine" if counts["quarantined"] else "completed"
    )
    state.finish_run(run_id, status, dict(counts))
    return run_id, dict(counts)


def reconcile_dte_history(settings: Settings, state: State, contract: DteHistoryContract,
                          run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Run belongs to a different block or target")
    plan = state.plan(run["plan_id"])
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Run belongs to a stale DTE history contract")
    rows = {source_key(row): row for row in extract_dte_history(settings)}
    results = Counter()
    mismatches: list[dict[str, Any]] = []
    with postgres_connection(settings.target.pg_url or "") as conn:
        target = {
            clean(row[0]): {
                "invoice_id": int(row[1]), "source_hash": clean(row[2]), "status": clean(row[3]),
                "generation_code": clean(row[4]), "control_number": clean(row[5]),
                "loan_transaction_id": int(row[6]), "client_id": int(row[7]),
                "line_count": int(row[8]),
            }
            for row in conn.execute("""
                SELECT i.codigo_generacion,i.id,i.source_hash,i.status,i.codigo_generacion,
                       i.numero_control,i.loan_transaction_id,loan.client_id,COUNT(line.id)
                FROM m_invoice i
                JOIN m_loan_transaction tx ON tx.id=i.loan_transaction_id
                JOIN m_loan loan ON loan.id=tx.loan_id
                LEFT JOIN m_invoice_line line ON line.invoice_id=i.id
                WHERE i.source_origin=%s
                GROUP BY i.codigo_generacion,i.id,i.source_hash,i.status,i.numero_control,
                         i.loan_transaction_id,loan.client_id
            """, (SOURCE_ORIGIN,)).fetchall()
        }
        catalog = _target_catalog(conn, settings)
        for item in state.run_items(run_id):
            if item["status"] in {"failed", "quarantined"}:
                results[item["status"]] += 1
                continue
            row = rows.get(item["source_key"])
            current = target.get(item["source_key"])
            payload, issue = _payload(row, contract, catalog) if row else (None, "missing_source")
            expected = payload["invoice"] if payload else {}
            ok = bool(
                current and not issue and contract.source_hash(row) == current["source_hash"]
                and current["status"] == expected.get("status")
                and current["generation_code"] == item["source_key"]
                and current["control_number"] == clean(row.get("control_number"))
                and current["loan_transaction_id"] == expected.get("loan_transaction_id")
                and current["client_id"] == payload["links"]["client_id"]
                and current["line_count"] == len(payload["lines"])
            )
            results["matched" if ok else "mismatched"] += 1
            if not ok and len(mismatches) < 20:
                mismatches.append({"source_key": item["source_key"], "reason": issue or "target_drift"})
    return {
        "ok": not results["mismatched"] and not results["failed"], "block": BLOCK,
        "run_id": run_id, "counts": dict(results), "mismatches": mismatches,
        "quarantine_is_nonblocking": True,
    }
