"""Deterministic, read-only inspection and planning of the Arissto general ledger.

The inspector intentionally keeps source prose in memory only long enough to
hash it. Reports contain structural keys, counts, hashes, and stable reason
codes, never journal descriptions, concepts, customer data, or amounts.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from calendar import monthrange
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests

from .arissto import IDENTIFIER, select_rows, source_connection, source_fingerprint
from .connections import FineractApi, FineractError, postgres_connection
from .config import Settings, SourceConfig
from .state import State


BLOCK = "accounting"
PLAN_VERSION = "accounting-explicit-key-plan-v2"
RECONCILIATION_VERSION = "accounting-direct-journal-reconciliation-v4"
PROVENANCE_SCHEMA_VERSION = "arissto-gl-v1"
DESCRIPTION_POLICY_VERSION = "arissto-description-projection-v1"
IMPORT_ENDPOINT = "arisstohistoricaljournals"
JOURNAL_NUMBER = re.compile(r"^\d{10}$")
SOURCE_KEY_FIELDS = ("company_id", "header_branch_id", "period_id", "journal_id")
COUNT_KEYS = (
    "populated", "empty", "balanced", "unbalanced", "annual_liquidation",
    "SOURCE_JOURNAL_HEADER_KEY_DUPLICATE", "SOURCE_JOURNAL_LINE_KEY_DUPLICATE",
    "SOURCE_JOURNAL_HEADER_MISSING", "SOURCE_JOURNAL_EMPTY", "SOURCE_JOURNAL_UNBALANCED",
    "SOURCE_JOURNAL_LINE_ZERO", "SOURCE_JOURNAL_LINE_BOTH_SIDES",
    "SOURCE_JOURNAL_NOT_MAYORIZED", "SOURCE_JOURNAL_EXCLUDED_FROM_LEDGER",
    "SOURCE_JOURNAL_STATUS_UNSUPPORTED", "SOURCE_ANNUAL_LIQUIDATION_SHAPE_UNSUPPORTED",
    "SOURCE_OPENING_JOURNAL_REQUIRES_REVIEW", "SOURCE_ACCOUNTING_PERIOD_UNRESOLVED",
    "SOURCE_JOURNAL_BACK_PERIOD", "SOURCE_JOURNAL_REFERENCE_BLANK",
    "SOURCE_JOURNAL_REFERENCE_INVALID", "SOURCE_JOURNAL_REFERENCE_DATE_MISMATCH",
    "SOURCE_JOURNAL_DATE_INVALID", "SOURCE_AMOUNT_INVALID", "SOURCE_AMOUNT_NEGATIVE",
    "SOURCE_AMOUNT_SCALE_UNSUPPORTED", "SOURCE_AMOUNT_TARGET_OVERFLOW",
    "SOURCE_ACCOUNT_UNRESOLVED", "SOURCE_ACCOUNT_AMBIGUOUS",
    "TARGET_ACCOUNT_UNRESOLVED_OR_AMBIGUOUS", "SOURCE_DESTINATION_BRANCH_UNMAPPED",
    "TARGET_OFFICE_MAPPING_DRIFT", "TARGET_OFFICE_CLOSURE_CONFLICT",
    "SOURCE_JOURNAL_BEFORE_HISTORICAL_ORIGIN", "SOURCE_JOURNAL_ON_OR_AFTER_CUTOFF",
    "SOURCE_OR_TARGET_CURRENCY_UNSUPPORTED",
    "TARGET_PROVENANCE_HASH_DRIFT",
)


def _trim(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).rstrip()


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_value)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text_hash(field: str, value: Any) -> str:
    marker = "<NULL>" if value is None else str(value)
    return hashlib.sha256(f"{field}\0{marker}".encode("utf-8")).hexdigest()


def _source_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(_trim(row.get(field)) or "" for field in SOURCE_KEY_FIELDS)  # type: ignore[return-value]


def source_key_text(key: tuple[str, str, str, str]) -> str:
    return ":".join(key)


def parse_source_key(value: str | None) -> tuple[str, str, str, str] | None:
    if value is None:
        return None
    parts = tuple(part.strip() for part in value.split(":"))
    if len(parts) != 4 or any(not part for part in parts):
        raise ValueError("Accounting source key must be COMPANY:BRANCH:PERIOD:JOURNAL")
    if any(len(part) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in parts):
        raise ValueError("Accounting source key contains an unsafe component")
    return parts  # type: ignore[return-value]


@dataclass(frozen=True)
class AccountingContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "AccountingContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        source = value.get("source", {})
        identifiers = [source.get("header_table"), source.get("detail_table"), *source.get("source_key", []), source.get("line_key")]
        for identifier in identifiers:
            if not isinstance(identifier, str):
                raise ValueError("Accounting contract has a missing SQL identifier")
            for component in identifier.split("."):
                if not IDENTIFIER.fullmatch(component):
                    raise ValueError(f"Unsafe accounting SQL identifier: {identifier}")
        eligibility = value.get("source_eligibility", {})
        if eligibility.get("importable_journal_statuses") != ["3"]:
            raise ValueError("Accounting contract must freeze status 3 as the only importable status")
        origin = value.get("historical_origin", {})
        try:
            origin_date = date.fromisoformat(str(origin.get("first_eligible_journal_date")))
        except ValueError as exc:
            raise ValueError("Accounting contract requires an ISO historical origin date") from exc
        if (
            origin_date.isoformat() != origin.get("first_eligible_journal_date")
            or origin.get("source_company") != value.get("currency_precision", {}).get("source_company")
            or origin.get("opening_balance_basis") != "demonstrated_zero_at_first_journal_bearing_period"
            or origin.get("synthetic_opening_journal_allowed") is not False
            or origin.get("residual_balance_journal_allowed") is not False
        ):
            raise ValueError("Accounting contract must freeze the demonstrated zero historical origin")
        mapping = value.get("agency_dimension", {}).get("mapping", {})
        if not mapping or any(not re.fullmatch(r"[0-9A-Za-z_-]+", str(key)) for key in mapping):
            raise ValueError("Accounting contract requires safe agency mappings")
        account_mapping = value.get("account_mapping", {})
        if account_mapping.get("default") != "exact_code":
            raise ValueError("Accounting contract must define the exact-code account default")
        overrides = account_mapping.get("overrides", {})
        if any(not re.fullmatch(r"[0-9A-Za-z_-]+", str(key)) or not re.fullmatch(r"[0-9A-Za-z_-]+", str(target))
               for key, target in overrides.items()):
            raise ValueError("Accounting account mapping contains an unsafe code")
        date_policy = value.get("journal_date_policy", {})
        if (
            date_policy.get("accounting_period_authority") != "CNT_PERIODO.ANIO_and_MES"
            or date_policy.get("within_period_effective_date") != "preserve_CNT_PARTIDAS.FECHA_PARTIDA"
            or date_policy.get("outside_period_effective_date") != "last_calendar_day_of_CNT_PERIODO"
            or date_policy.get("source_date_provenance") != "preserve_CNT_PARTIDAS.FECHA_PARTIDA_separately"
            or date_policy.get("journal_number_role") != "preserve_exactly_as_ref_num_never_derive_effective_date"
            or date_policy.get("recognized_nonblocking_anomalies")
            != ["SOURCE_JOURNAL_BACK_PERIOD", "SOURCE_JOURNAL_REFERENCE_DATE_MISMATCH"]
        ):
            raise ValueError("Accounting contract must freeze the intended journal-date policy")
        return cls(value)

    @property
    def hash(self) -> str:
        return _hash(self.raw)

    def target_code(self, source_code: str) -> str:
        return str(self.raw["account_mapping"]["overrides"].get(source_code, source_code))


HEADER_QUERY = """
SELECT
       RTRIM(p.ID_EMPRESA) AS company_id,
       RTRIM(p.ID_SUCURSAL) AS header_branch_id,
       RTRIM(p.ID_PERIODO) AS period_id,
       RTRIM(p.ID_PARTIDA) AS journal_id,
       RTRIM(p.NUMERO_PARTIDA) AS journal_number,
       CAST(p.FECHA_PARTIDA AS date) AS journal_date,
       RTRIM(p.ESTADO_PARTIDA) AS journal_status,
       RTRIM(p.ID_TIPO_PARTIDA) AS journal_type,
       RTRIM(p.LIQ_ING_EGR) AS liquidation_flag,
       RTRIM(p.PARTIDA_INICIAL) AS opening_flag,
       p.CODIGO_SISTEMA AS source_system,
       RTRIM(p.ID_CIERRE_DIARIO) AS daily_close_id,
       RTRIM(p.ID_CIERRE_MAYORIZAR) AS mayorization_close_id,
       pe.ANIO AS period_year,
       pe.MES AS period_month,
       tp.TIPO_PARTIDA AS journal_type_name,
       p.CONCEPTO AS header_concept,
       p.DESCRIPCION AS header_description
FROM dbo.CNT_PARTIDAS p
LEFT JOIN dbo.CNT_PERIODO pe
  ON pe.ID_EMPRESA=p.ID_EMPRESA AND pe.ID_PERIODO=p.ID_PERIODO
LEFT JOIN dbo.CNT_TIPO_PARTIDA tp
  ON tp.ID_TIPO_PARTIDA=p.ID_TIPO_PARTIDA
WHERE p.ID_EMPRESA=?
  AND (? IS NULL OR (p.ID_EMPRESA=? AND p.ID_SUCURSAL=? AND p.ID_PERIODO=? AND p.ID_PARTIDA=?))
ORDER BY p.ID_EMPRESA,p.ID_SUCURSAL,p.ID_PERIODO,p.ID_PARTIDA
"""

LINE_QUERY = """
SELECT
       RTRIM(d.ID_EMPRESA) AS company_id,
       RTRIM(d.ID_SUCURSAL) AS header_branch_id,
       RTRIM(d.ID_PERIODO) AS period_id,
       RTRIM(d.ID_PARTIDA) AS journal_id,
       RTRIM(d.ID_DETALLE_PARTIDA) AS line_id,
       RTRIM(d.ID_CUENTA) AS account_id,
       RTRIM(c.CODIGO_CUENTA) AS account_code,
       ac.account_code_count AS source_account_code_count,
       RTRIM(d.ID_SUCURSAL_DESTINO) AS destination_branch_id,
       d.DEBE AS debit,
       d.HABER AS credit,
       d.CONCEPTO AS line_concept,
       d.CONCEPTO_AUX AS line_aux_concept
FROM dbo.CNT_DETALLE_PARTIDAS d
LEFT JOIN dbo.CNT_CATALOGO_CUENTAS c
  ON c.ID_EMPRESA=d.ID_EMPRESA AND c.ID_CUENTA=d.ID_CUENTA
LEFT JOIN (
    SELECT ID_EMPRESA,CODIGO_CUENTA,COUNT_BIG(*) AS account_code_count
    FROM dbo.CNT_CATALOGO_CUENTAS
    GROUP BY ID_EMPRESA,CODIGO_CUENTA
) ac ON ac.ID_EMPRESA=c.ID_EMPRESA AND ac.CODIGO_CUENTA=c.CODIGO_CUENTA
WHERE d.ID_EMPRESA=?
  AND (? IS NULL OR (d.ID_EMPRESA=? AND d.ID_SUCURSAL=? AND d.ID_PERIODO=? AND d.ID_PARTIDA=?))
ORDER BY d.ID_EMPRESA,d.ID_SUCURSAL,d.ID_PERIODO,d.ID_PARTIDA,d.ID_DETALLE_PARTIDA
"""

HEADER_PERIOD_QUERY = HEADER_QUERY.replace(
    "AND (? IS NULL OR (p.ID_EMPRESA=? AND p.ID_SUCURSAL=? AND p.ID_PERIODO=? AND p.ID_PARTIDA=?))",
    "AND p.ID_PERIODO=?",
)
LINE_PERIOD_QUERY = LINE_QUERY.replace(
    "AND (? IS NULL OR (d.ID_EMPRESA=? AND d.ID_SUCURSAL=? AND d.ID_PERIODO=? AND d.ID_PARTIDA=?))",
    "AND d.ID_PERIODO=?",
)

SOURCE_SCHEMA_QUERY = """
SELECT s.name AS schema_name,t.name AS table_name,c.name AS column_name,
       ty.name AS data_type,c.precision AS numeric_precision,c.scale AS numeric_scale
FROM sys.tables t
JOIN sys.schemas s ON s.schema_id=t.schema_id
JOIN sys.columns c ON c.object_id=t.object_id
JOIN sys.types ty ON ty.user_type_id=c.user_type_id
WHERE s.name='dbo' AND t.name IN
      ('CNT_PARTIDAS','CNT_DETALLE_PARTIDAS','CNT_PERIODO','CNT_TIPO_PARTIDA','CNT_CATALOGO_CUENTAS')
ORDER BY s.name,t.name,c.column_id
"""

CURRENCY_QUERY = """
SELECT RTRIM(e.ID_EMPRESA) AS company_id,RTRIM(e.MULTIMONEDA) AS multicurrency_flag,
       RTRIM(m.ISO) AS iso_code,RTRIM(me.TIPO_MONEDA) AS currency_type,
       RTRIM(me.ACTIVO) AS active_flag
FROM dbo.EMPRESA e
JOIN dbo.MONEDA_EMPRESA me ON me.ID_EMPRESA=e.ID_EMPRESA
JOIN dbo.MONEDA m ON m.ID_MONEDA=me.ID_MONEDA
WHERE e.ID_EMPRESA=?
ORDER BY me.ID_MONEDA_EMPRESA
"""

SOURCE_LEDGER_CONTROL_SUMMARY_QUERY = """
SELECT TOP (1) RTRIM(cp.ID_PERIODO) AS control_period_id,
       CAST(EOMONTH(DATEFROMPARTS(cp.ANIO,cp.MES,1)) AS date) AS control_period_end,
       CAST(1 AS int) AS closed_before_cutoff,
       (
         SELECT COUNT_BIG(*)
         FROM dbo.CNT_PARTIDAS p
         JOIN dbo.CNT_PERIODO pe
           ON pe.ID_EMPRESA=p.ID_EMPRESA AND pe.ID_PERIODO=p.ID_PERIODO
         WHERE p.ID_EMPRESA=? AND p.ESTADO_PARTIDA='3'
           AND CASE
                 WHEN CAST(p.FECHA_PARTIDA AS date) BETWEEN DATEFROMPARTS(pe.ANIO,pe.MES,1)
                                                             AND EOMONTH(DATEFROMPARTS(pe.ANIO,pe.MES,1))
                   THEN CAST(p.FECHA_PARTIDA AS date)
                 ELSE EOMONTH(DATEFROMPARTS(pe.ANIO,pe.MES,1))
               END>=CAST(? AS date)
           AND (pe.ANIO<cp.ANIO OR (pe.ANIO=cp.ANIO AND pe.MES<=cp.MES))
           AND EXISTS (
               SELECT 1 FROM dbo.CNT_DETALLE_PARTIDAS d
               WHERE d.ID_EMPRESA=p.ID_EMPRESA AND d.ID_SUCURSAL=p.ID_SUCURSAL
                 AND d.ID_PERIODO=p.ID_PERIODO AND d.ID_PARTIDA=p.ID_PARTIDA
           )
       ) AS eligible_journal_count
FROM dbo.CNT_PERIODO cp
WHERE cp.ID_EMPRESA=?
  AND EOMONTH(DATEFROMPARTS(cp.ANIO,cp.MES,1))<CAST(? AS date)
ORDER BY cp.ANIO DESC,cp.MES DESC,cp.ID_PERIODO DESC
"""

SOURCE_LEDGER_CONTROL_QUERY = """
SELECT RTRIM(d.ID_SUCURSAL_DESTINO) AS destination_branch_id,
       RTRIM(d.ID_CUENTA) AS account_id,
       SUM(CASE WHEN c.TIPO_SALDO='A' THEN d.HABER-d.DEBE ELSE d.DEBE-d.HABER END) AS journal_closing,
       COUNT_BIG(*) AS direct_line_count,
       SUM(CASE WHEN RTRIM(COALESCE(p.ID_TIPO_PARTIDA,''))='003'
                      AND RTRIM(COALESCE(p.LIQ_ING_EGR,''))='1'
                THEN 0 ELSE 1 END) AS non_annual_liquidation_line_count
FROM dbo.CNT_PARTIDAS p
JOIN dbo.CNT_PERIODO pe
  ON pe.ID_EMPRESA=p.ID_EMPRESA AND pe.ID_PERIODO=p.ID_PERIODO
JOIN dbo.CNT_PERIODO cp
  ON cp.ID_EMPRESA=p.ID_EMPRESA AND cp.ID_PERIODO=?
JOIN dbo.CNT_DETALLE_PARTIDAS d
  ON d.ID_EMPRESA=p.ID_EMPRESA AND d.ID_SUCURSAL=p.ID_SUCURSAL
 AND d.ID_PERIODO=p.ID_PERIODO AND d.ID_PARTIDA=p.ID_PARTIDA
JOIN dbo.CNT_CATALOGO_CUENTAS c
  ON c.ID_EMPRESA=d.ID_EMPRESA AND c.ID_CUENTA=d.ID_CUENTA
WHERE p.ID_EMPRESA=? AND p.ESTADO_PARTIDA='3'
  AND CASE
        WHEN CAST(p.FECHA_PARTIDA AS date) BETWEEN DATEFROMPARTS(pe.ANIO,pe.MES,1)
                                                    AND EOMONTH(DATEFROMPARTS(pe.ANIO,pe.MES,1))
          THEN CAST(p.FECHA_PARTIDA AS date)
        ELSE EOMONTH(DATEFROMPARTS(pe.ANIO,pe.MES,1))
      END>=CAST(? AS date)
  AND (pe.ANIO<cp.ANIO OR (pe.ANIO=cp.ANIO AND pe.MES<=cp.MES))
GROUP BY d.ID_SUCURSAL_DESTINO,d.ID_CUENTA
"""

SOURCE_LEDGER_MAYOR_QUERY = """
SELECT RTRIM(ID_SUCURSAL) AS destination_branch_id,
       RTRIM(ID_CUENTA) AS account_id,
       SALDO_FINAL AS ledger_closing
FROM dbo.CNT_MAYOR
WHERE ID_EMPRESA=? AND ID_PERIODO=?
"""

SOURCE_HYBRID_ROLLUP_QUERY_PREFIX = """
WITH requested(destination_branch_id,ID_CUENTA) AS (
"""

SOURCE_HYBRID_ROLLUP_QUERY_SUFFIX = """
)
SELECT RTRIM(r.destination_branch_id) AS destination_branch_id,
       RTRIM(r.ID_CUENTA) AS account_id,
       COUNT(child.ID_CUENTA) AS child_account_count,
       COUNT(child_mayor.ID_CUENTA) AS child_ledger_row_count,
       COALESCE(SUM(child_mayor.SALDO_FINAL),0) AS child_ledger_closing
FROM requested r
LEFT JOIN dbo.CNT_CATALOGO_CUENTAS child
  ON child.ID_EMPRESA_PADRE=? AND child.ID_CUENTA_PADRE=r.ID_CUENTA
LEFT JOIN dbo.CNT_MAYOR child_mayor
  ON child_mayor.ID_EMPRESA=child.ID_EMPRESA AND child_mayor.ID_CUENTA=child.ID_CUENTA
 AND child_mayor.ID_PERIODO=? AND child_mayor.ID_SUCURSAL=r.destination_branch_id
GROUP BY r.destination_branch_id,r.ID_CUENTA
"""


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except InvalidOperation:
        return Decimal("NaN")


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value not in (None, "") else None
    except ValueError:
        return None


def _journal_date_policy(header: dict[str, Any]) -> dict[str, Any]:
    """Resolve the effective accounting date without trusting journal numbering.

    Arissto can create a journal after the month to which it was intentionally
    posted. CNT_PERIODO is the accounting-period authority; NUMERO_PARTIDA is
    preserved as business evidence but never used to derive a date.
    """
    source_date = _date(header.get("journal_date"))
    period_year = _trim(header.get("period_year"))
    period_month = (_trim(header.get("period_month")) or "").zfill(2)
    try:
        year, month = int(period_year or ""), int(period_month)
        period_start = date(year, month, 1)
        period_end = date(year, month, monthrange(year, month)[1])
    except (TypeError, ValueError):
        return {
            "source_date": source_date, "effective_date": source_date,
            "period_start": None, "period_end": None, "rule": "unresolved-accounting-period",
            "anomaly_codes": [],
        }

    anomaly_codes: list[str] = []
    if source_date is not None and not period_start <= source_date <= period_end:
        anomaly_codes.append("SOURCE_JOURNAL_BACK_PERIOD")
        effective_date = period_end
        rule = "accounting-period-end-normalization"
    else:
        effective_date = source_date
        rule = "source-date-within-accounting-period"

    number = _trim(header.get("journal_number"))
    if number and JOURNAL_NUMBER.fullmatch(number) and source_date is not None:
        if number[:6] != f"{source_date.year:04d}{source_date.month:02d}":
            anomaly_codes.append("SOURCE_JOURNAL_REFERENCE_DATE_MISMATCH")
    return {
        "source_date": source_date, "effective_date": effective_date,
        "period_start": period_start, "period_end": period_end, "rule": rule,
        "anomaly_codes": sorted(anomaly_codes),
    }


def _line_hash(row: dict[str, Any], contract: AccountingContract) -> str:
    source_code = _trim(row.get("account_code"))
    safe = {
        "line_id": _trim(row.get("line_id")),
        "account_id": _trim(row.get("account_id")),
        "source_account_code": source_code,
        "destination_branch_id": _trim(row.get("destination_branch_id")),
        "debit": format(_decimal(row.get("debit")), "f"),
        "credit": format(_decimal(row.get("credit")), "f"),
        "line_concept_sha256": _text_hash("CNT_DETALLE_PARTIDAS.CONCEPTO", row.get("line_concept")),
        "line_aux_concept_sha256": _text_hash("CNT_DETALLE_PARTIDAS.CONCEPTO_AUX", row.get("line_aux_concept")),
    }
    return _hash(safe)


def _money(value: Any) -> str:
    return format(_decimal(value).quantize(Decimal("0.01")), ".2f")


def _display_description(line_value: Any, header_description: Any, header_concept: Any) -> tuple[str | None, bool]:
    """Create the approved non-provenance display projection without retaining raw text."""
    for candidate in (line_value, header_description, header_concept):
        if candidate is None:
            continue
        normalized = unicodedata.normalize("NFC", str(candidate))
        normalized = "".join(" " if char.isspace() else char for char in normalized)
        normalized = "".join(char for char in normalized if not unicodedata.category(char).startswith("C"))
        normalized = " ".join(normalized.split())
        if not normalized:
            continue
        if len(normalized) > 500:
            return normalized[:499] + "…", True
        return normalized, False
    return None, False


def _coa_mapping_hash(contract: AccountingContract) -> str:
    mapping = contract.raw["account_mapping"]
    return _hash({
        "version": mapping["version"], "default": mapping["default"],
        "overrides": mapping.get("overrides", {}),
        "reviewed_exact_codes": mapping.get("reviewed_exact_codes", []),
    })


def _agency_mapping_hash(contract: AccountingContract) -> str:
    agency = contract.raw["agency_dimension"]
    return _hash({
        "version": agency["mapping_version"],
        "mapping": {
            key: {
                "target_office_id": value["target_office_id"],
                "target_office_external_id": str(value["target_office_external_id"]),
                "dimension_value": str(value["dimension_value"]),
            }
            for key, value in sorted(agency["mapping"].items())
        },
    })


def _policy_hash(contract: AccountingContract) -> str:
    return _hash({
        "contract_version": contract.raw["contract_version"],
        "historical_origin": contract.raw["historical_origin"],
        "source_eligibility": contract.raw["source_eligibility"],
        "annual_liquidation_policy": contract.raw["annual_liquidation_policy"],
        "journal_date_policy": contract.raw["journal_date_policy"],
        "legacy_text_policy": contract.raw["legacy_text_policy"],
        "currency_precision": contract.raw["currency_precision"],
        "cutoff": contract.raw["cutoff"],
    })


def _journal_hash(header: dict[str, Any], lines: list[dict[str, Any]], contract: AccountingContract) -> str:
    safe_header = {
        key: _json_value(header.get(key)) for key in (
            *SOURCE_KEY_FIELDS, "journal_number", "journal_date", "journal_status", "journal_type",
            "liquidation_flag", "opening_flag", "source_system", "daily_close_id", "mayorization_close_id",
            "period_year", "period_month",
        )
    }
    safe_header["header_concept_sha256"] = _text_hash("CNT_PARTIDAS.CONCEPTO", header.get("header_concept"))
    safe_header["header_description_sha256"] = _text_hash("CNT_PARTIDAS.DESCRIPCION", header.get("header_description"))
    safe_header["line_hashes"] = [
        value[1] for value in sorted(
            ((_trim(line.get("line_id")) or "", _line_hash(line, contract)) for line in lines)
        )
    ]
    return _hash(safe_header)


def classify_accounting(headers: list[dict[str, Any]], lines: list[dict[str, Any]],
                        contract: AccountingContract, cutoff: date,
                        target: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify already-bulk-loaded rows without source or target I/O."""
    header_counts = Counter(_source_key(row) for row in headers)
    line_counts = Counter((*_source_key(row), _trim(row.get("line_id")) or "") for row in lines)
    grouped_lines: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for line in lines:
        grouped_lines[_source_key(line)].append(line)
    for values in grouped_lines.values():
        values.sort(key=lambda row: _trim(row.get("line_id")) or "")

    agency_mapping = contract.raw["agency_dimension"]["mapping"]
    importable = set(contract.raw["source_eligibility"]["importable_journal_statuses"])
    status_dispositions = contract.raw["source_eligibility"]["journal_status_dispositions"]
    annual = contract.raw["annual_liquidation_policy"]
    historical_origin = date.fromisoformat(contract.raw["historical_origin"]["first_eligible_journal_date"])
    target_accounts = (target or {}).get("accounts", {})
    closure_by_office = (target or {}).get("closure_by_office", {})
    findings: list[dict[str, Any]] = []
    classification_counts: Counter[str] = Counter({key: 0 for key in COUNT_KEYS})
    boundary_counts: Counter[str] = Counter({
        "before_cutoff": 0, "on_cutoff": 0, "after_cutoff": 0, "invalid": 0,
    })
    date_policy_observations: list[dict[str, Any]] = []
    hash_by_key: dict[str, str] = {}

    for header in sorted(headers, key=_source_key):
        key = _source_key(header)
        key_text = source_key_text(key)
        journal_lines = grouped_lines.get(key, [])
        reasons: set[str] = set()
        date_policy = _journal_date_policy(header)
        source_journal_date = date_policy["source_date"]
        journal_date = date_policy["effective_date"]
        if date_policy["anomaly_codes"]:
            for code in date_policy["anomaly_codes"]:
                classification_counts[code] += 1
            date_policy_observations.append({
                "source_key": key_text,
                "source_journal_date": source_journal_date.isoformat() if source_journal_date else None,
                "effective_entry_date": journal_date.isoformat() if journal_date else None,
                "rule": date_policy["rule"],
                "anomaly_codes": date_policy["anomaly_codes"],
            })
        if journal_date is None:
            boundary = "invalid"
            reasons.add("SOURCE_JOURNAL_DATE_INVALID")
        elif journal_date < cutoff:
            boundary = "before_cutoff"
            if journal_date < historical_origin:
                reasons.add("SOURCE_JOURNAL_BEFORE_HISTORICAL_ORIGIN")
        elif journal_date == cutoff:
            boundary = "on_cutoff"
        else:
            boundary = "after_cutoff"
        boundary_counts[boundary] += 1

        if header_counts[key] > 1:
            reasons.add("SOURCE_JOURNAL_HEADER_KEY_DUPLICATE")
        if not journal_lines:
            reasons.add("SOURCE_JOURNAL_EMPTY")
            classification_counts["empty"] += 1
        else:
            classification_counts["populated"] += 1
        debit_total = sum((_decimal(line.get("debit")) for line in journal_lines), Decimal(0))
        credit_total = sum((_decimal(line.get("credit")) for line in journal_lines), Decimal(0))
        if journal_lines and debit_total.is_finite() and credit_total.is_finite() and debit_total == credit_total:
            classification_counts["balanced"] += 1
        elif journal_lines:
            classification_counts["unbalanced"] += 1
            reasons.add("SOURCE_JOURNAL_UNBALANCED")

        status = _trim(header.get("journal_status"))
        if status not in importable:
            disposition = status_dispositions.get(status or "", contract.raw["source_eligibility"]["unexpected_status"])
            reasons.add(str(disposition["reason_code"]))
        journal_type = _trim(header.get("journal_type"))
        liquidation = _trim(header.get("liquidation_flag"))
        opening = _trim(header.get("opening_flag"))
        annual_signal = journal_type == annual["source_journal_type"] or liquidation == annual["source_liquidation_flag"]
        if opening not in (None, "", annual["expected_opening_flag"]):
            reasons.add("SOURCE_OPENING_JOURNAL_REQUIRES_REVIEW")
        if annual_signal and not (
            journal_type == annual["source_journal_type"]
            and liquidation == annual["source_liquidation_flag"]
            and journal_date is not None and journal_date.month == 12 and journal_date.day == 31
            and opening in (None, "", annual["expected_opening_flag"])
        ):
            reasons.add("SOURCE_ANNUAL_LIQUIDATION_SHAPE_UNSUPPORTED")
        if annual_signal:
            classification_counts["annual_liquidation"] += 1

        if date_policy["period_start"] is None:
            reasons.add("SOURCE_ACCOUNTING_PERIOD_UNRESOLVED")

        number = _trim(header.get("journal_number"))
        if not number:
            reasons.add("SOURCE_JOURNAL_REFERENCE_BLANK")
        elif not JOURNAL_NUMBER.fullmatch(number):
            reasons.add("SOURCE_JOURNAL_REFERENCE_INVALID")

        involved_offices: set[int] = set()
        for line in journal_lines:
            line_key = (*key, _trim(line.get("line_id")) or "")
            if line_counts[line_key] > 1:
                reasons.add("SOURCE_JOURNAL_LINE_KEY_DUPLICATE")
            debit, credit = _decimal(line.get("debit")), _decimal(line.get("credit"))
            if not debit.is_finite() or not credit.is_finite():
                reasons.add("SOURCE_AMOUNT_INVALID")
            else:
                if debit == 0 and credit == 0:
                    reasons.add("SOURCE_JOURNAL_LINE_ZERO")
                if debit != 0 and credit != 0:
                    reasons.add("SOURCE_JOURNAL_LINE_BOTH_SIDES")
                if debit < 0 or credit < 0:
                    reasons.add("SOURCE_AMOUNT_NEGATIVE")
                if debit.as_tuple().exponent < -2 or credit.as_tuple().exponent < -2:
                    reasons.add("SOURCE_AMOUNT_SCALE_UNSUPPORTED")
                if abs(debit) >= Decimal("10000000000000") or abs(credit) >= Decimal("10000000000000"):
                    reasons.add("SOURCE_AMOUNT_TARGET_OVERFLOW")
            source_code = _trim(line.get("account_code"))
            if not source_code:
                reasons.add("SOURCE_ACCOUNT_UNRESOLVED")
            elif int(line.get("source_account_code_count") or 1) != 1:
                reasons.add("SOURCE_ACCOUNT_AMBIGUOUS")
            elif target is not None:
                candidates = target_accounts.get(contract.target_code(source_code), [])
                if len(candidates) != 1 or candidates[0].get("disabled") or not candidates[0].get("manual_allowed", True):
                    reasons.add("TARGET_ACCOUNT_UNRESOLVED_OR_AMBIGUOUS")
            branch = _trim(line.get("destination_branch_id"))
            mapped = agency_mapping.get(branch or "")
            if not mapped:
                reasons.add("SOURCE_DESTINATION_BRANCH_UNMAPPED")
            else:
                office_id = int(mapped["target_office_id"])
                involved_offices.add(office_id)
                if target is not None:
                    office = target.get("offices", {}).get(office_id)
                    if not office or office.get("external_id") != str(mapped["target_office_external_id"]):
                        reasons.add("TARGET_OFFICE_MAPPING_DRIFT")
        if target is not None and journal_date:
            for office_id in involved_offices:
                closure = closure_by_office.get(office_id)
                if closure and journal_date <= closure:
                    reasons.add("TARGET_OFFICE_CLOSURE_CONFLICT")

        journal_hash = _journal_hash(header, journal_lines, contract)
        hash_by_key[key_text] = journal_hash
        if reasons:
            for reason in reasons:
                classification_counts[reason] += 1
            findings.append({"source_key": key_text, "boundary": boundary, "reason_codes": sorted(reasons), "source_hash": journal_hash})

    orphan_line_keys = sorted(source_key_text(key) for key in set(grouped_lines) - set(header_counts))
    for key in orphan_line_keys:
        classification_counts["SOURCE_JOURNAL_HEADER_MISSING"] += 1
        findings.append({"source_key": key, "boundary": "unknown", "reason_codes": ["SOURCE_JOURNAL_HEADER_MISSING"]})
    findings.sort(key=lambda item: (item["source_key"], item["reason_codes"]))
    return {
        "header_count": len(headers),
        "line_count": len(lines),
        "boundary_counts": dict(sorted(boundary_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "date_policy_observations": sorted(date_policy_observations, key=lambda item: item["source_key"]),
        "finding_count": len(findings),
        "findings": findings,
        "source_hashes": hash_by_key,
    }


def _required_accounting_office_ids(contract: AccountingContract) -> set[int]:
    return {
        int(mapped["target_office_id"])
        for mapped in contract.raw["agency_dimension"]["mapping"].values()
    }


def _missing_api_user_office_ids(target: dict[str, Any], contract: AccountingContract) -> list[int]:
    if not target.get("api_user_selected"):
        return []
    assigned = {int(value) for value in target.get("api_user_office_ids", [])}
    return sorted(_required_accounting_office_ids(contract) - assigned)


def _source_control_period_readiness(
    headers: list[dict[str, Any]], classified: dict[str, Any], contract: AccountingContract, cutoff: date,
) -> dict[str, Any]:
    finding_keys = {str(item["source_key"]) for item in classified.get("findings", [])}
    candidates: list[tuple[date, str, date]] = []
    for header in headers:
        key = source_key_text(_source_key(header))
        policy = _journal_date_policy(header)
        effective_date = policy.get("effective_date")
        period_end = policy.get("period_end")
        if key in finding_keys or not isinstance(effective_date, date) or not isinstance(period_end, date):
            continue
        if effective_date >= cutoff or period_end >= cutoff:
            continue
        candidates.append((effective_date, key, period_end))
    if not candidates:
        return {"resolved": False, "closed_before_cutoff": False}
    _effective_date, key, period_end = max(candidates)
    return {
        "resolved": True,
        "source_key": key,
        "period_id": key.split(":")[2],
        "period_end": period_end.isoformat(),
        "closed_before_cutoff": True,
    }


def _target_snapshot(pg_url: str, contract: AccountingContract, api_user: str | None = None) -> dict[str, Any]:
    with postgres_connection(pg_url) as conn:
        tables = {str(row[0]) for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name=ANY(%s)",
            (["acc_gl_account", "m_office", "m_appuser", "m_appuser_office", "acc_gl_closure", "m_organisation_currency",
              contract.raw["target"]["provenance_parent_table"], contract.raw["target"]["provenance_line_table"]],),
        ).fetchall()}
        accounts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if "acc_gl_account" in tables:
            for identifier, code, disabled, manual_allowed in conn.execute(
                "SELECT id,gl_code,disabled,manual_journal_entries_allowed FROM acc_gl_account ORDER BY gl_code,id"
            ).fetchall():
                accounts[str(code)].append({"id": int(identifier), "disabled": bool(disabled), "manual_allowed": bool(manual_allowed)})
        offices: dict[int, dict[str, Any]] = {}
        if "m_office" in tables:
            offices = {int(identifier): {"external_id": str(external_id) if external_id is not None else None}
                       for identifier, external_id in conn.execute("SELECT id,external_id FROM m_office ORDER BY id").fetchall()}
        closures: dict[int, date] = {}
        if "acc_gl_closure" in tables:
            closures = {int(office): closed_on for office, closed_on in conn.execute(
                "SELECT office_id,MAX(closing_date) FROM acc_gl_closure GROUP BY office_id"
            ).fetchall() if closed_on is not None}
        currencies: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if "m_organisation_currency" in tables:
            for identifier, code, decimal_places in conn.execute(
                "SELECT id,code,decimal_places FROM m_organisation_currency ORDER BY code,id"
            ).fetchall():
                currencies[str(code)].append({"id": int(identifier), "decimal_places": int(decimal_places)})
        api_user_count = 0
        api_user_office_ids: list[int] = []
        if api_user and {"m_appuser", "m_appuser_office"} <= tables:
            user_rows = conn.execute("SELECT id FROM m_appuser WHERE username=%s", (api_user,)).fetchall()
            api_user_count = len(user_rows)
            if api_user_count == 1:
                api_user_office_ids = [
                    int(row[0]) for row in conn.execute(
                        "SELECT office_id FROM m_appuser_office WHERE appuser_id=%s ORDER BY office_id",
                        (user_rows[0][0],),
                    ).fetchall()
                ]
        parent = contract.raw["target"]["provenance_parent_table"]
        imported: dict[str, str] = {}
        imported_target_ids: dict[str, str] = {}
        if parent in tables:
            columns = {str(row[0]) for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s", (parent,),
            ).fetchall()}
            required = {"source_company_id", "source_branch_id", "source_period_id", "source_journal_id", "source_hash"}
            if required <= columns:
                has_target_id = "target_transaction_id" in columns
                target_expression = "target_transaction_id" if has_target_id else "NULL"
                for company, branch, period, journal, source_hash, target_id in conn.execute(
                    f'SELECT source_company_id,source_branch_id,source_period_id,source_journal_id,source_hash,'
                    f'{target_expression} FROM "{parent}"'
                ).fetchall():
                    key = ":".join(map(str, (company, branch, period, journal)))
                    imported[key] = str(source_hash)
                    if target_id is not None:
                        imported_target_ids[key] = str(target_id)
        return {"tables": sorted(tables), "accounts": dict(accounts), "offices": offices,
                "closure_by_office": closures, "currencies": dict(currencies), "imported": imported,
                "imported_target_ids": imported_target_ids, "api_user_selected": bool(api_user),
                "api_user_count": api_user_count, "api_user_office_ids": api_user_office_ids}


def inspect_accounting(source_config: SourceConfig, contract: AccountingContract, cutoff_date: str,
                       source_key: str | None = None, target_pg_url: str | None = None,
                       source_conn: Any | None = None, target_snapshot: dict[str, Any] | None = None,
                       target_api_user: str | None = None) -> dict[str, Any]:
    cutoff = date.fromisoformat(cutoff_date)
    exact_key = parse_source_key(source_key)
    company = str(contract.raw["currency_precision"]["source_company"])
    if exact_key is not None and exact_key[0] != company:
        raise ValueError(f"Accounting source key must belong to configured company {company}")
    key_params: tuple[Any, ...] = (None, company, "", "", "") if exact_key is None else (exact_key[0], *exact_key)

    def load(conn: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        headers = select_rows(conn, HEADER_QUERY, (company, *key_params))
        lines = select_rows(conn, LINE_QUERY, (company, *key_params))
        return headers, lines, select_rows(conn, SOURCE_SCHEMA_QUERY), select_rows(conn, CURRENCY_QUERY, (company,))

    if source_conn is None:
        with source_connection(source_config) as conn:
            headers, lines, schema, currencies = load(conn)
    else:
        headers, lines, schema, currencies = load(source_conn)

    target = target_snapshot
    if target is None and target_pg_url:
        target = _target_snapshot(target_pg_url, contract, target_api_user)
    classified = classify_accounting(headers, lines, contract, cutoff, target)
    source_hashes = classified.pop("source_hashes")
    control_period = _source_control_period_readiness(headers, classified, contract, cutoff)
    imported = (target or {}).get("imported", {})
    provenance = {
        "inspection": "not_selected" if target is None else ("available" if imported else "schema_absent_or_empty"),
        "source_journals": len(source_hashes),
        "imported_keys": len(imported),
        "matching_hashes": sum(1 for key, value in imported.items() if source_hashes.get(key) == value),
        "hash_mismatches": sorted(key for key, value in imported.items() if key in source_hashes and source_hashes[key] != value),
        "target_only_keys": sorted(set(imported) - set(source_hashes)),
        "source_only_keys": sorted(set(source_hashes) - set(imported)) if imported else [],
    }
    currency_ok = [row for row in currencies if _trim(row.get("currency_type")) == "1"
                   and _trim(row.get("iso_code")) == contract.raw["currency_precision"]["source_base_currency_iso"]]
    source_blockers: list[str] = []
    if len(currency_ok) != 1 or _trim(currency_ok[0].get("active_flag")) not in ("1", "S", "Y"):
        source_blockers.append("SOURCE_OR_TARGET_CURRENCY_UNSUPPORTED")
    target_blockers: list[str] = []
    if target is not None:
        required_target_tables = {
            "acc_gl_account", "m_office", "m_organisation_currency",
            contract.raw["target"]["provenance_parent_table"],
            contract.raw["target"]["provenance_line_table"],
        }
        if required_target_tables - set(target.get("tables", [])):
            target_blockers.append("TARGET_SCHEMA_PREREQUISITES_MISSING")
        for mapped in contract.raw["agency_dimension"]["mapping"].values():
            office = target.get("offices", {}).get(int(mapped["target_office_id"]))
            if not office or office.get("external_id") != str(mapped["target_office_external_id"]):
                target_blockers.append("TARGET_OFFICE_MAPPING_DRIFT")
                break
        target_currency = str(contract.raw["currency_precision"]["target_currency_code"])
        currency_rows = target.get("currencies", {}).get(target_currency, [])
        if len(currency_rows) != 1 or currency_rows[0].get("decimal_places") != 2:
            target_blockers.append("TARGET_CURRENCY_UNSUPPORTED")
        if classified["classification_counts"].get("TARGET_ACCOUNT_UNRESOLVED_OR_AMBIGUOUS", 0):
            target_blockers.append("TARGET_ACCOUNT_UNRESOLVED_OR_AMBIGUOUS")
        if target.get("api_user_selected") and target.get("api_user_count") != 1:
            target_blockers.append("TARGET_API_USER_UNRESOLVED")
        if _missing_api_user_office_ids(target, contract):
            target_blockers.append("TARGET_API_USER_OFFICE_ACCESS_INCOMPLETE")
    schema_signature = _hash(schema)
    stable_material = {"cutoff_date": cutoff_date, "scope": source_key or f"company:{company}",
                       "schema_signature": schema_signature, "classification": classified,
                       "control_period": control_period, "provenance": provenance}
    report = {
        "block": BLOCK,
        "mode": "read-only",
        "ready": not source_blockers and not target_blockers,
        "contract_hash": contract.hash,
        "schema_signature": schema_signature,
        "source_fingerprint": source_fingerprint(source_config),
        "cutoff": {"date": cutoff_date, "timezone": contract.raw["cutoff"]["timezone"]},
        "scope": {"source_key": source_key, "company_id": company},
        "source_blockers": sorted(source_blockers),
        "target_blockers": sorted(target_blockers),
        "source": classified,
        "source_ledger_control_period": control_period,
        "target": {
            "selected": target is not None,
            "tables": (target or {}).get("tables", []),
            "account_count": sum(len(values) for values in (target or {}).get("accounts", {}).values()),
            "office_count": len((target or {}).get("offices", {})),
            "closure_office_count": len((target or {}).get("closure_by_office", {})),
            "missing_required_tables": sorted(
                {
                    "acc_gl_account", "m_office", "m_organisation_currency",
                    contract.raw["target"]["provenance_parent_table"],
                    contract.raw["target"]["provenance_line_table"],
                } - set((target or {}).get("tables", []))
            ),
            "api_user_office_access": {
                "selected": bool((target or {}).get("api_user_selected")),
                "assigned_office_ids": (target or {}).get("api_user_office_ids", []),
                "required_office_ids": sorted(_required_accounting_office_ids(contract)),
                "missing_office_ids": _missing_api_user_office_ids(target or {}, contract),
            },
            "provenance": provenance,
        },
        "transferred_loan_accrual_anomalies": {
            "classified_count": 0,
            "status": "no_physical_loan_to_gl_line_allocation_in_frozen_contract",
        },
    }
    report["inspection_hash"] = _hash(stable_material)
    return report


def _target_baseline_hash(target: dict[str, Any]) -> str:
    """Hash only target facts that can change an accounting plan's disposition or payload."""
    return _hash({
        "tables": target.get("tables", []),
        "accounts": target.get("accounts", {}),
        "offices": target.get("offices", {}),
        "closure_by_office": target.get("closure_by_office", {}),
        "currencies": target.get("currencies", {}),
    })


def _canonical_payload(header: dict[str, Any], lines: list[dict[str, Any]],
                       contract: AccountingContract, target: dict[str, Any]) -> dict[str, Any]:
    key = _source_key(header)
    key_text = source_key_text(key)
    agency = contract.raw["agency_dimension"]
    currency = contract.raw["currency_precision"]
    canonical_lines: list[dict[str, Any]] = []
    for row in sorted(lines, key=lambda value: _trim(value.get("line_id")) or ""):
        source_code = _trim(row.get("account_code")) or ""
        target_code = contract.target_code(source_code)
        account = target["accounts"][target_code][0]
        source_branch = _trim(row.get("destination_branch_id")) or ""
        office = agency["mapping"][source_branch]
        description, truncated = _display_description(
            row.get("line_concept"), header.get("header_description"), header.get("header_concept")
        )
        line_id = _trim(row.get("line_id")) or ""
        canonical_lines.append({
            "source_line_key": f"{key_text}:{line_id}",
            "source_line_id": line_id,
            "source_account_id": _trim(row.get("account_id")),
            "source_account_code": source_code,
            "target_account_code": target_code,
            "target_gl_account_id": int(account["id"]),
            "source_destination_branch_id": source_branch,
            "office_id": int(office["target_office_id"]),
            "dimensions": {str(agency["target_key"]): str(office["dimension_value"])},
            "debit": _money(row.get("debit")),
            "credit": _money(row.get("credit")),
            "description": description,
            "description_sha256": _text_hash("acc_gl_journal_entry.description", description),
            "description_truncated": truncated,
            "provenance": {
                "line_concept_sha256": _text_hash("CNT_DETALLE_PARTIDAS.CONCEPTO", row.get("line_concept")),
                "line_aux_concept_sha256": _text_hash("CNT_DETALLE_PARTIDAS.CONCEPTO_AUX", row.get("line_aux_concept")),
            },
            "mappings": {
                "coa_version": contract.raw["account_mapping"]["version"],
                "agency_version": agency["mapping_version"],
            },
        })
    date_policy = _journal_date_policy(header)
    source_journal_date = date_policy["source_date"]
    effective_entry_date = date_policy["effective_date"]
    return {
        "source_key": key_text,
        "entry_date": effective_entry_date.isoformat(),  # type: ignore[union-attr]
        "ref_num": _trim(header.get("journal_number")),
        "currency": str(currency["target_currency_code"]),
        "debit_total": _money(sum((_decimal(line.get("debit")) for line in lines), Decimal(0))),
        "credit_total": _money(sum((_decimal(line.get("credit")) for line in lines), Decimal(0))),
        "lines": canonical_lines,
        "provenance": {
            "source_company_id": key[0],
            "source_header_branch_id": key[1],
            "source_period_id": key[2],
            "source_journal_id": key[3],
            "source_journal_status": _trim(header.get("journal_status")),
            "source_journal_type": _trim(header.get("journal_type")),
            "source_liquidation_flag": _trim(header.get("liquidation_flag")),
            "source_opening_flag": _trim(header.get("opening_flag")),
            "source_journal_date": source_journal_date.isoformat(),  # type: ignore[union-attr]
            "effective_entry_date_rule": date_policy["rule"],
            "date_anomaly_codes": date_policy["anomaly_codes"],
            "header_concept_sha256": _text_hash("CNT_PARTIDAS.CONCEPTO", header.get("header_concept")),
            "header_description_sha256": _text_hash("CNT_PARTIDAS.DESCRIPCION", header.get("header_description")),
        },
    }


def plan_accounting_rows(headers: list[dict[str, Any]], lines: list[dict[str, Any]],
                         contract: AccountingContract, cutoff_snapshot: dict[str, Any],
                         source_fingerprint_value: str, target_fingerprint: str,
                         target: dict[str, Any], requested_keys: list[str],
                         source_schema_signature: str,
                         global_reason_codes: list[str] | None = None,
                         scope: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a canonical explicit-key plan from already loaded source and target rows."""
    normalized_keys = sorted({source_key_text(parse_source_key(value)) for value in requested_keys})  # type: ignore[arg-type]
    if not normalized_keys:
        raise ValueError("Accounting planning requires at least one explicit --source-key")
    cutoff = date.fromisoformat(str(cutoff_snapshot["date"]))
    classification = classify_accounting(headers, lines, contract, cutoff, target)
    findings: dict[str, set[str]] = defaultdict(set)
    for item in classification["findings"]:
        findings[item["source_key"]].update(item["reason_codes"])
    header_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    line_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in headers:
        header_groups[source_key_text(_source_key(row))].append(row)
    for row in lines:
        line_groups[source_key_text(_source_key(row))].append(row)

    target_currency = str(contract.raw["currency_precision"]["target_currency_code"])
    currency_rows = target.get("currencies", {}).get(target_currency, [])
    currency_ready = len(currency_rows) == 1 and currency_rows[0].get("decimal_places") == 2
    imported = target.get("imported", {})
    actions: list[dict[str, Any]] = []
    for key in normalized_keys:
        matching_headers = header_groups.get(key, [])
        reasons = set(findings.get(key, set()))
        reasons.update(global_reason_codes or [])
        if not matching_headers:
            reasons.add("SOURCE_JOURNAL_HEADER_MISSING")
            source_hash = _hash({"missing_source_key": key})
            payload = None
        else:
            header = min(matching_headers, key=_canonical_json)
            journal_date = _journal_date_policy(header)["effective_date"]
            if journal_date is not None and journal_date >= cutoff:
                reasons.add("SOURCE_JOURNAL_ON_OR_AFTER_CUTOFF")
            if not currency_ready:
                reasons.add("SOURCE_OR_TARGET_CURRENCY_UNSUPPORTED")
            journal_lines = sorted(line_groups.get(key, []), key=lambda row: _trim(row.get("line_id")) or "")
            if len(matching_headers) == 1:
                source_hash = _journal_hash(header, journal_lines, contract)
            else:
                source_hash = _hash({
                    "duplicate_header_hashes": sorted(
                        _journal_hash(value, journal_lines, contract) for value in matching_headers
                    )
                })
            existing_hash = imported.get(key)
            if existing_hash is not None and existing_hash != source_hash:
                reasons.add("TARGET_PROVENANCE_HASH_DRIFT")
            payload = None if reasons else _canonical_payload(header, journal_lines, contract, target)

        if reasons:
            disposition = "QUARANTINED"
        elif imported.get(key) == source_hash:
            disposition = "UNCHANGED"
        else:
            disposition = "APPLICABLE"
        action_material = {
            "source_key": key, "source_hash": source_hash, "disposition": disposition,
            "reason_codes": sorted(reasons), "payload": payload,
        }
        actions.append({**action_material, "planned_hash": _hash(action_material)})

    bindings = {
        "contract_hash": contract.hash,
        "source_schema_signature": source_schema_signature,
        "coa_mapping": {
            "version": contract.raw["account_mapping"]["version"],
            "hash": _coa_mapping_hash(contract),
        },
        "agency_mapping": {
            "version": contract.raw["agency_dimension"]["mapping_version"],
            "hash": _agency_mapping_hash(contract),
        },
        "policy": {
            "contract_version": contract.raw["contract_version"],
            "planner_version": PLAN_VERSION,
            "hash": _policy_hash(contract),
        },
        "target_baseline_hash": _target_baseline_hash(target),
    }
    document: dict[str, Any] = {
        "block": BLOCK,
        "plan_version": PLAN_VERSION,
        "scope": scope or {"type": "explicit-source-keys", "source_keys": normalized_keys},
        "source_fingerprint": source_fingerprint_value,
        "target_fingerprint": target_fingerprint,
        "accounting_cutoff": dict(cutoff_snapshot),
        "bindings": bindings,
        "counts": dict(sorted(Counter(action["disposition"] for action in actions).items())),
        "actions": actions,
    }
    document["plan_hash"] = _hash(document)
    return document


def assert_accounting_plan_current(frozen: dict[str, Any], current: dict[str, Any]) -> None:
    """Reject reuse whenever any deterministic planning input or output has drifted."""
    if frozen.get("plan_hash") == current.get("plan_hash"):
        return
    checks = (
        ("source_fingerprint", "SOURCE_FINGERPRINT_DRIFT"),
        ("target_fingerprint", "TARGET_FINGERPRINT_DRIFT"),
        ("accounting_cutoff", "ACCOUNTING_CUTOFF_DRIFT"),
        ("bindings", "ACCOUNTING_PLAN_BINDING_DRIFT"),
        ("actions", "ACCOUNTING_SOURCE_OR_PAYLOAD_DRIFT"),
    )
    for field, reason in checks:
        if frozen.get(field) != current.get(field):
            raise RuntimeError(reason)
    raise RuntimeError("ACCOUNTING_PLAN_HASH_DRIFT")


def build_accounting_plan(settings: Settings, state: State, contract: AccountingContract,
                          source_keys: list[str] | None, source_conn: Any | None = None,
                          target_snapshot: dict[str, Any] | None = None,
                          source_periods: list[str] | None = None,
                          full_scope: bool = False) -> tuple[str, dict[str, Any]]:
    """Load and persist a deterministic explicit-key or accounting-period plan."""
    requested = sorted({source_key_text(parse_source_key(value)) for value in (source_keys or [])})  # type: ignore[arg-type]
    periods = sorted(set(source_periods or []))
    if full_scope and (requested or periods):
        raise ValueError("Full accounting scope cannot be combined with source keys or periods")
    if not full_scope and bool(requested) == bool(periods):
        raise ValueError("plan --block accounting requires either --source-key or --period, but not both")
    if any(not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", period) for period in periods):
        raise ValueError("Accounting period contains an unsafe component")
    company = str(contract.raw["currency_precision"]["source_company"])
    parsed = [parse_source_key(value) for value in requested]
    if any(key is None or key[0] != company for key in parsed):
        raise ValueError(f"Accounting source keys must belong to configured company {company}")

    def load(conn: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        loaded_headers: list[dict[str, Any]] = []
        loaded_lines: list[dict[str, Any]] = []
        if full_scope:
            key_params: tuple[Any, ...] = (None, company, "", "", "")
            loaded_headers.extend(select_rows(conn, HEADER_QUERY, (company, *key_params)))
            loaded_lines.extend(select_rows(conn, LINE_QUERY, (company, *key_params)))
        elif periods:
            for period in periods:
                loaded_headers.extend(select_rows(conn, HEADER_PERIOD_QUERY, (company, period)))
                loaded_lines.extend(select_rows(conn, LINE_PERIOD_QUERY, (company, period)))
        else:
            for key in parsed:
                assert key is not None
                params: tuple[Any, ...] = (key[0], *key)
                loaded_headers.extend(select_rows(conn, HEADER_QUERY, (company, *params)))
                loaded_lines.extend(select_rows(conn, LINE_QUERY, (company, *params)))
        return loaded_headers, loaded_lines, select_rows(conn, SOURCE_SCHEMA_QUERY), select_rows(conn, CURRENCY_QUERY, (company,))

    if source_conn is None:
        with source_connection(settings.source) as conn:
            headers, lines, schema, currencies = load(conn)
    else:
        headers, lines, schema, currencies = load(source_conn)
    if periods or full_scope:
        requested = sorted({source_key_text(_source_key(row)) for row in headers})
        if not requested:
            raise ValueError("Accounting scope contains no journal headers")
    if full_scope:
        periods = sorted({_trim(row.get("period_id")) or "" for row in headers})
    target = target_snapshot
    if target is None:
        if not settings.target.pg_url:
            raise ValueError("Accounting planning requires a read-only Fineract PostgreSQL profile")
        target = _target_snapshot(settings.target.pg_url, contract, settings.target.api_user)
    missing_api_offices = _missing_api_user_office_ids(target, contract)
    if target.get("api_user_selected") and target.get("api_user_count") != 1:
        raise RuntimeError("TARGET_API_USER_UNRESOLVED")
    if missing_api_offices:
        raise RuntimeError(
            "TARGET_API_USER_OFFICE_ACCESS_INCOMPLETE: missing office IDs "
            + ",".join(str(value) for value in missing_api_offices)
        )
    currency_ok = [row for row in currencies if _trim(row.get("currency_type")) == "1"
                   and _trim(row.get("iso_code")) == contract.raw["currency_precision"]["source_base_currency_iso"]]
    global_reasons = []
    if (len(currency_ok) != 1
            or _trim(currency_ok[0].get("active_flag")) not in ("1", "S", "Y")
            or _trim(currency_ok[0].get("multicurrency_flag")) != str(
                contract.raw["currency_precision"]["source_multicurrency_flag"]
            )):
        global_reasons.append("SOURCE_OR_TARGET_CURRENCY_UNSUPPORTED")
    document = plan_accounting_rows(
        headers, lines, contract, state.accounting_cutoff, source_fingerprint(settings.source),
        settings.target.fingerprint, target, requested, _hash(schema), global_reasons,
        ({"type": "full-company", "source_periods": periods, "source_keys": requested}
         if full_scope else
         ({"type": "source-periods", "source_periods": periods, "source_keys": requested} if periods else None)),
    )
    plan_id = state.save_plan(
        settings.target.fingerprint, BLOCK, source_fingerprint(settings.source), contract.hash, document,
    )
    return plan_id, document


def _load_accounting_plan_inputs(
    settings: Settings, contract: AccountingContract, source_keys: list[str],
    source_conn: Any | None = None,
    source_periods: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    company = str(contract.raw["currency_precision"]["source_company"])
    parsed = [parse_source_key(value) for value in source_keys]
    periods = sorted(set(source_periods or []))

    def load(conn: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        headers: list[dict[str, Any]] = []
        lines: list[dict[str, Any]] = []
        if periods:
            for period in periods:
                headers.extend(select_rows(conn, HEADER_PERIOD_QUERY, (company, period)))
                lines.extend(select_rows(conn, LINE_PERIOD_QUERY, (company, period)))
        else:
            for key in parsed:
                if key is None or key[0] != company:
                    raise ValueError(f"Accounting source keys must belong to configured company {company}")
                params: tuple[Any, ...] = (key[0], *key)
                headers.extend(select_rows(conn, HEADER_QUERY, (company, *params)))
                lines.extend(select_rows(conn, LINE_QUERY, (company, *params)))
        return headers, lines, select_rows(conn, SOURCE_SCHEMA_QUERY), select_rows(conn, CURRENCY_QUERY, (company,))

    if source_conn is not None:
        return load(source_conn)
    with source_connection(settings.source) as conn:
        return load(conn)


def _current_accounting_plan(
    settings: Settings, contract: AccountingContract, frozen: dict[str, Any],
    headers: list[dict[str, Any]], lines: list[dict[str, Any]], schema: list[dict[str, Any]],
    currencies: list[dict[str, Any]], target: dict[str, Any],
) -> dict[str, Any]:
    company = str(contract.raw["currency_precision"]["source_company"])
    currency_ok = [row for row in currencies if _trim(row.get("currency_type")) == "1"
                   and _trim(row.get("iso_code")) == contract.raw["currency_precision"]["source_base_currency_iso"]]
    global_reasons = []
    if (len(currency_ok) != 1 or _trim(currency_ok[0].get("active_flag")) not in ("1", "S", "Y")
            or _trim(currency_ok[0].get("multicurrency_flag")) != str(
                contract.raw["currency_precision"]["source_multicurrency_flag"]
            )):
        global_reasons.append("SOURCE_OR_TARGET_CURRENCY_UNSUPPORTED")
    return plan_accounting_rows(
        headers, lines, contract, frozen["accounting_cutoff"], source_fingerprint(settings.source),
        settings.target.fingerprint, target, list(frozen["scope"]["source_keys"]), _hash(schema), global_reasons,
        dict(frozen["scope"]),
    )


def assert_accounting_apply_current(frozen: dict[str, Any], current: dict[str, Any]) -> None:
    """Allow only the expected APPLICABLE-to-UNCHANGED transition caused by this importer."""
    for field, reason in (
        ("source_fingerprint", "SOURCE_FINGERPRINT_DRIFT"),
        ("target_fingerprint", "TARGET_FINGERPRINT_DRIFT"),
        ("accounting_cutoff", "ACCOUNTING_CUTOFF_DRIFT"),
        ("bindings", "ACCOUNTING_PLAN_BINDING_DRIFT"),
        ("scope", "ACCOUNTING_PLAN_SCOPE_DRIFT"),
    ):
        if frozen.get(field) != current.get(field):
            raise RuntimeError(reason)
    current_actions = {row["source_key"]: row for row in current.get("actions", [])}
    for expected in frozen.get("actions", []):
        actual = current_actions.get(expected["source_key"])
        if actual is None:
            raise RuntimeError("ACCOUNTING_SOURCE_OR_PAYLOAD_DRIFT")
        if expected.get("source_hash") != actual.get("source_hash") or expected.get("payload") != actual.get("payload"):
            raise RuntimeError("ACCOUNTING_SOURCE_OR_PAYLOAD_DRIFT")
        if expected["disposition"] == "QUARANTINED":
            if expected.get("reason_codes") != actual.get("reason_codes"):
                raise RuntimeError("ACCOUNTING_SOURCE_OR_PAYLOAD_DRIFT")
        elif actual["disposition"] not in {expected["disposition"], "UNCHANGED"}:
            reasons = set(actual.get("reason_codes") or [])
            if "TARGET_PROVENANCE_HASH_DRIFT" in reasons:
                raise RuntimeError("TARGET_PROVENANCE_HASH_DRIFT")
            raise RuntimeError("ACCOUNTING_SOURCE_OR_PAYLOAD_DRIFT")


def _verify_cutoff_binding(api: FineractApi, snapshot: dict[str, Any]) -> None:
    required = {"configuration_revision", "configuration_hash", "lifecycle_state"}
    if not required <= set(snapshot):
        raise RuntimeError("Accounting plan is not bound to an ACTIVE tenant cutoff")
    current = api.request("GET", "accountingcutoff")
    comparisons = {
        "date": str(current.get("cutoffDate") or ""),
        "timezone": str(current.get("timezoneId") or ""),
        "configuration_revision": current.get("configurationRevision"),
        "configuration_hash": str(current.get("configurationHash") or ""),
        "lifecycle_state": str(current.get("lifecycleState") or "").upper(),
    }
    for field, value in comparisons.items():
        if snapshot.get(field) != value:
            raise RuntimeError(f"ACCOUNTING_CUTOFF_DRIFT:{field}")
    if comparisons["lifecycle_state"] != "ACTIVE":
        raise RuntimeError("ACCOUNTING_CUTOFF_NOT_ACTIVE")


def _request_identity(action: dict[str, Any]) -> str:
    material = f"{action['source_key']}|{action['source_hash']}|{action['planned_hash']}"
    return f"acct:{hashlib.sha256(material.encode()).hexdigest()[:48]}"


def build_historical_journal_request(
    plan_id: str, request_run_id: str, document: dict[str, Any], action: dict[str, Any],
    header: dict[str, Any], source_lines: list[dict[str, Any]], contract: AccountingContract,
) -> dict[str, Any]:
    payload = action.get("payload")
    if not payload:
        raise RuntimeError("Accounting write requires an applicable canonical payload")
    lines_by_id = {_trim(row.get("line_id")) or "": row for row in source_lines}
    request_lines: list[dict[str, Any]] = []
    for sequence, planned in enumerate(payload["lines"], 1):
        raw = lines_by_id.get(planned["source_line_id"])
        if raw is None:
            raise RuntimeError("ACCOUNTING_SOURCE_OR_PAYLOAD_DRIFT")
        request_lines.append({
            "sourceLineId": planned["source_line_id"],
            "sourceLineSequence": sequence,
            "sourceLineHash": _line_hash(raw, contract),
            "sourceAccountId": planned["source_account_id"],
            "sourceAccountCode": planned["source_account_code"],
            "targetAccountCode": planned["target_account_code"],
            "targetGlAccountId": planned["target_gl_account_id"],
            "debit": planned["debit"], "credit": planned["credit"],
            "sourceMovementReference": None, "sourceDocumentReference": None,
            "sourceDestinationBranchId": planned["source_destination_branch_id"],
            "officeId": planned["office_id"],
            "officeExternalId": str(planned["dimensions"]["office"]),
            "dimensions": planned["dimensions"],
            "sourceLineConcept": raw.get("line_concept"),
            "sourceLineConceptSha256": planned["provenance"]["line_concept_sha256"],
            "sourceLineAuxConcept": raw.get("line_aux_concept"),
            "sourceLineAuxConceptSha256": planned["provenance"]["line_aux_concept_sha256"],
            "description": planned["description"],
            "descriptionSha256": planned["description_sha256"],
            "descriptionTruncated": planned["description_truncated"],
            "knownTransferredLoanOfficeMismatch": False, "knownAnomalyCodes": None,
        })
    key = parse_source_key(action["source_key"])
    assert key is not None
    cutoff, bindings = document["accounting_cutoff"], document["bindings"]
    provenance = payload["provenance"]
    return {
        "provenanceSchemaVersion": PROVENANCE_SCHEMA_VERSION, "sourceSystem": "ARISSTO",
        "sourceCompanyId": key[0], "sourceBranchId": key[1], "sourcePeriodId": key[2],
        "sourceJournalId": key[3], "sourceJournalNumber": payload["ref_num"],
        "sourceJournalDate": provenance["source_journal_date"],
        "entryDate": payload["entry_date"], "sourceJournalType": provenance["source_journal_type"],
        "sourceModuleCode": _trim(header.get("source_system")), "sourceStatus": provenance["source_journal_status"],
        "sourceLiquidationFlag": provenance["source_liquidation_flag"],
        "sourceOpeningFlag": provenance["source_opening_flag"],
        "sourceHeaderConcept": header.get("header_concept"),
        "sourceHeaderConceptSha256": provenance["header_concept_sha256"],
        "sourceHeaderDescription": header.get("header_description"),
        "sourceHeaderDescriptionSha256": provenance["header_description_sha256"],
        "sourceHash": action["source_hash"], "plannedHash": action["planned_hash"],
        "contractHash": bindings["contract_hash"],
        "sourceSchemaSignature": bindings["source_schema_signature"],
        "coaMappingVersion": bindings["coa_mapping"]["version"], "coaMappingHash": bindings["coa_mapping"]["hash"],
        "officeMappingVersion": bindings["agency_mapping"]["version"],
        "officeMappingHash": bindings["agency_mapping"]["hash"],
        "policyVersion": f"accounting-contract-v{bindings['policy']['contract_version']}",
        "policyHash": bindings["policy"]["hash"], "descriptionPolicyVersion": DESCRIPTION_POLICY_VERSION,
        "knownAnomalyCodes": ",".join(provenance["date_anomaly_codes"]) or None,
        "sourceFingerprint": document["source_fingerprint"], "targetFingerprint": document["target_fingerprint"],
        "targetBaselineHash": bindings["target_baseline_hash"], "cutoffDate": cutoff["date"],
        "cutoffTimezoneId": cutoff["timezone"], "cutoffConfigurationRevision": cutoff["configuration_revision"],
        "cutoffConfigurationHash": cutoff["configuration_hash"], "planId": plan_id, "runId": request_run_id,
        "refNum": payload["ref_num"], "currency": payload["currency"],
        "debitTotal": payload["debit_total"], "creditTotal": payload["credit_total"],
        "knownTransferredLoanOfficeMismatch": False, "lines": request_lines,
    }


def _classify_apply_error(exc: Exception) -> tuple[str, str, bool]:
    status = exc.status_code if isinstance(exc, FineractError) else None
    match = re.search(r"error\.msg\.arissto\.historical\.gl\.([a-z0-9_.-]+)", str(exc), re.IGNORECASE)
    reason = (match.group(1) if match else type(exc).__name__).upper().replace(".", "_").replace("-", "_")
    code = f"ACCOUNTING_IMPORT_{reason}"[:240]
    retryable = (
        isinstance(exc, requests.RequestException)
        or status in {408, 425, 429}
        or (isinstance(status, int) and status >= 500)
    )
    fatal_markers = {
        "BINDING_DRIFT", "SOURCE_KEY_CONFLICT", "ACCOUNT_MAPPING_DRIFT", "OFFICE_DIMENSION_DRIFT",
        "OFFICE_UNAUTHORIZED",
    }
    error_class = "fatal" if any(marker in reason for marker in fatal_markers) else ("retryable" if retryable else "quarantined")
    return code, error_class, error_class == "retryable"


def _verify_scheduler_paused(api: FineractApi) -> None:
    current = api.request("GET", "scheduler")
    active = current.get("active")
    if not isinstance(active, bool):
        raise RuntimeError("Fineract scheduler status did not return an active flag")
    if active:
        raise RuntimeError("Fineract scheduler must be paused during accounting migration")


def apply_accounting_plan(
    settings: Settings, state: State, contract: AccountingContract, plan_id: str,
    production_confirmation: str | None = None, only_keys: set[str] | None = None,
    retry_from_run: str | None = None, api: FineractApi | None = None,
    source_rows: tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None = None,
    target_snapshot: dict[str, Any] | None = None,
) -> tuple[str, dict[str, int]]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Accounting plan belongs to a different block or target")
    if plan["contract_hash"] != contract.hash:
        raise RuntimeError("Accounting contract changed after planning")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    api = api or FineractApi(settings.target)
    document = plan["document"]
    _verify_scheduler_paused(api)
    _verify_cutoff_binding(api, document["accounting_cutoff"])
    keys = list(document["scope"]["source_keys"])
    headers, lines, schema, currencies = source_rows or _load_accounting_plan_inputs(
        settings, contract, keys, source_periods=document.get("scope", {}).get("source_periods")
    )
    target = target_snapshot or _target_snapshot(
        settings.target.pg_url or "", contract, settings.target.api_user
    )
    missing_api_offices = _missing_api_user_office_ids(target, contract)
    if target.get("api_user_selected") and target.get("api_user_count") != 1:
        raise RuntimeError("TARGET_API_USER_UNRESOLVED")
    if missing_api_offices:
        raise RuntimeError(
            "TARGET_API_USER_OFFICE_ACCESS_INCOMPLETE: missing office IDs "
            + ",".join(str(value) for value in missing_api_offices)
        )
    current = _current_accounting_plan(settings, contract, document, headers, lines, schema, currencies, target)
    assert_accounting_apply_current(document, current)
    current_actions = {row["source_key"]: row for row in current["actions"]}
    header_by_key = {source_key_text(_source_key(row)): row for row in headers}
    lines_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in lines:
        lines_by_key[source_key_text(_source_key(row))].append(row)
    prior = {row["source_key"]: row for row in state.accounting_retry_items(retry_from_run)} if retry_from_run else {}
    actions = [row for row in document["actions"] if only_keys is None or row["source_key"] in only_keys]
    run_id, counts = state.start_run(plan), Counter()
    fatal = False
    for action in actions:
        key = action["source_key"]
        current_action = current_actions[key]
        request_key = str(prior.get(key, {}).get("request_idempotency_key") or _request_identity(action))
        request_run_id = str(prior.get(key, {}).get("request_run_id") or run_id)
        if action["disposition"] == "QUARANTINED":
            code = ",".join(action.get("reason_codes") or ["ACCOUNTING_QUARANTINED"])
            state.record_accounting_item(run_id, key, "quarantine", action["source_hash"], "quarantined",
                                         document["plan_hash"], action["planned_hash"], request_key, request_run_id,
                                         error_code=code, disposition="QUARANTINED", error_class="quarantined")
            counts["quarantined"] += 1
            continue
        if action["disposition"] == "UNCHANGED" or current_action["disposition"] == "UNCHANGED":
            transaction_id = target.get("imported_target_ids", {}).get(key)
            status = "unchanged" if action["disposition"] == "UNCHANGED" else "recovered"
            state.record_accounting_item(run_id, key, "unchanged", action["source_hash"], status,
                                         document["plan_hash"], action["planned_hash"], request_key, request_run_id,
                                         target_transaction_id=transaction_id, disposition="UNCHANGED")
            if transaction_id:
                state.save_mapping(settings.target.fingerprint, BLOCK, key, transaction_id, action["source_hash"])
            counts[status] += 1
            continue
        request = build_historical_journal_request(
            plan_id, request_run_id, document, action, header_by_key[key], lines_by_key[key], contract,
        )
        state.record_accounting_item(run_id, key, "import", action["source_hash"], "pending",
                                     document["plan_hash"], action["planned_hash"], request_key, request_run_id)
        try:
            result = api.request("POST", IMPORT_ENDPOINT, request, idempotency_key=request_key)
            transaction_id = str(result["transactionId"])
            line_ids = [int(value) for value in result.get("journalEntryIds", [])]
            status = "recovered" if bool(result.get("unchanged")) else "succeeded"
            state.record_accounting_item(run_id, key, "import", action["source_hash"], status,
                                         document["plan_hash"], action["planned_hash"], request_key, request_run_id,
                                         target_transaction_id=transaction_id, target_line_ids=line_ids,
                                         disposition="UNCHANGED" if status == "recovered" else "IMPORTED")
            state.save_mapping(settings.target.fingerprint, BLOCK, key, transaction_id, action["source_hash"])
            counts["imported" if status == "succeeded" else "recovered"] += 1
        except Exception as exc:
            code, error_class, retryable = _classify_apply_error(exc)
            state.record_accounting_item(run_id, key, "import", action["source_hash"], "failed",
                                         document["plan_hash"], action["planned_hash"], request_key, request_run_id,
                                         error_code=code, disposition="FAILED", error_class=error_class,
                                         retryable=retryable)
            counts["failed"] += 1
            counts[f"{error_class}_failures"] += 1
            if error_class == "fatal":
                fatal = True
                break
    status = "completed-with-errors" if counts["failed"] else ("completed-with-quarantine" if counts["quarantined"] else "completed")
    if fatal:
        status = "failed"
    state.finish_run(run_id, status, dict(counts))
    return run_id, dict(counts)


def accounting_retry_keys(state: State, run_id: str) -> set[str]:
    return {row["source_key"] for row in state.accounting_retry_items(run_id)}


def _amount_text(value: Any, scale: int) -> str:
    return format(Decimal(str(value or 0)).quantize(Decimal(1).scaleb(-scale)), "f")


def _dimensions(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if value is None:
        return None
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _target_reconciliation_snapshot(
    pg_url: str, contract: AccountingContract, source_keys: list[str], cutoff_date: str,
) -> dict[str, Any]:
    if not pg_url:
        raise RuntimeError("Accounting reconciliation requires target PostgreSQL read access")
    parent = contract.raw["target"]["provenance_parent_table"]
    line = contract.raw["target"]["provenance_line_table"]
    with postgres_connection(pg_url) as conn:
        cursor = conn.execute(
            f"""
            SELECT concat_ws(':',p.source_company_id,p.source_branch_id,p.source_period_id,p.source_journal_id) source_key,
                   p.target_transaction_id,p.target_ref_num,p.source_journal_date,p.source_hash,p.planned_hash,
                   p.contract_hash,p.source_schema_signature,p.coa_mapping_hash,p.office_mapping_hash,p.policy_hash,
                   p.cutoff_date,p.cutoff_timezone_id,p.cutoff_configuration_revision,p.cutoff_configuration_hash,
                   p.result provenance_result,
                   l.source_line_id,l.source_line_sequence,l.source_line_hash,l.source_account_id,l.source_account_code,
                   l.target_gl_account_id,l.source_debit_amount,l.source_credit_amount,l.source_side,l.source_amount,
                   l.target_side,l.target_type_enum,l.target_amount,l.target_entry_date,l.source_destination_branch_id,
                   l.target_office_id,l.target_office_external_id,l.target_dimensions,l.target_description_sha256,
                   l.target_journal_entry_id,l.result line_result,
                   j.id journal_entry_id,j.account_id journal_account_id,a.gl_code journal_account_code,
                   j.office_id journal_office_id,o.external_id journal_office_external_id,j.currency_code,
                   j.transaction_id journal_transaction_id,j.reversed,j.reversal_id,j.ref_num journal_ref_num,
                   j.manual_entry,j.entry_date journal_entry_date,j.type_enum journal_type_enum,j.amount journal_amount,
                   j.description journal_description,j.dimensions::text journal_dimensions,
                   j.loan_transaction_id,j.savings_transaction_id,j.client_transaction_id,j.share_transaction_id,
                   j.entity_type_enum,j.entity_id
            FROM "{parent}" p
            LEFT JOIN "{line}" l ON l.journal_provenance_id=p.id
            LEFT JOIN acc_gl_journal_entry j ON j.id=l.target_journal_entry_id
            LEFT JOIN acc_gl_account a ON a.id=j.account_id
            LEFT JOIN m_office o ON o.id=j.office_id
            WHERE concat_ws(':',p.source_company_id,p.source_branch_id,p.source_period_id,p.source_journal_id)=ANY(%s)
            ORDER BY source_key,l.source_line_sequence,l.id
            """, (source_keys,),
        )
        columns = [column.name for column in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        native_pre_cutoff = int(conn.execute(
            "SELECT COUNT(*) FROM acc_gl_journal_entry WHERE entry_date<%s AND manual_entry=FALSE",
            (cutoff_date,),
        ).fetchone()[0])
        imported_on_or_after_cutoff = int(conn.execute(
            f"SELECT COUNT(*) FROM \"{parent}\" p JOIN acc_gl_journal_entry j "
            f"ON j.transaction_id=p.target_transaction_id WHERE j.entry_date>=%s",
            (cutoff_date,),
        ).fetchone()[0])
    return {
        "rows": rows,
        "boundary": {
            "native_non_manual_pre_cutoff": native_pre_cutoff,
            "imported_on_or_after_cutoff": imported_on_or_after_cutoff,
        },
    }


def _reconcile_accounting_action(action: dict[str, Any], rows: list[dict[str, Any]],
                                 document: dict[str, Any]) -> list[str]:
    reasons: set[str] = set()
    payload = action.get("payload") or {}
    if not rows:
        return ["TARGET_JOURNAL_MISSING"]
    transaction_ids = {str(row.get("target_transaction_id") or "") for row in rows}
    if len(transaction_ids) != 1 or "" in transaction_ids:
        reasons.add("TARGET_JOURNAL_IDENTITY_DRIFT")
    bindings = document["bindings"]
    cutoff = document["accounting_cutoff"]
    imported_planned_hash = action["planned_hash"]
    if action["disposition"] == "UNCHANGED":
        imported_planned_hash = _hash({
            "source_key": action["source_key"], "source_hash": action["source_hash"],
            "disposition": "APPLICABLE", "reason_codes": [], "payload": payload,
        })
    for row in rows:
        header_actual = {
            "source_hash": row.get("source_hash"),
            "planned_hash": row.get("planned_hash"),
            "source_schema_signature": row.get("source_schema_signature"),
            "coa_mapping_hash": row.get("coa_mapping_hash"),
            "office_mapping_hash": row.get("office_mapping_hash"),
            "cutoff_date": str(row.get("cutoff_date")),
            "cutoff_timezone_id": row.get("cutoff_timezone_id"),
            "cutoff_configuration_revision": row.get("cutoff_configuration_revision"),
            "cutoff_configuration_hash": row.get("cutoff_configuration_hash"),
            "provenance_result": row.get("provenance_result"),
            "target_ref_num": row.get("target_ref_num"),
            "source_journal_date": str(row.get("source_journal_date")),
        }
        header_expected = {
            "source_hash": action["source_hash"],
            "planned_hash": imported_planned_hash,
            "source_schema_signature": bindings["source_schema_signature"],
            "coa_mapping_hash": bindings["coa_mapping"]["hash"],
            "office_mapping_hash": bindings["agency_mapping"]["hash"],
            "cutoff_date": cutoff["date"],
            "cutoff_timezone_id": cutoff["timezone"],
            "cutoff_configuration_revision": cutoff["configuration_revision"],
            "cutoff_configuration_hash": cutoff["configuration_hash"],
            "provenance_result": "IMPORTED",
            "target_ref_num": payload["ref_num"],
            "source_journal_date": payload["provenance"]["source_journal_date"],
        }
        if header_actual != header_expected:
            reasons.add("TARGET_JOURNAL_PROVENANCE_DRIFT")
        if action["disposition"] == "UNCHANGED":
            if any(not re.fullmatch(r"[0-9a-f]{64}", str(row.get(field) or ""))
                   for field in ("contract_hash", "policy_hash")):
                reasons.add("TARGET_JOURNAL_PROVENANCE_DRIFT")
        elif (
            row.get("contract_hash") != bindings["contract_hash"]
            or row.get("policy_hash") != bindings["policy"]["hash"]
        ):
            reasons.add("TARGET_JOURNAL_PROVENANCE_DRIFT")
    expected_lines = {row["source_line_id"]: row for row in payload.get("lines", [])}
    actual_lines: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        actual_lines[str(row.get("source_line_id") or "")].append(row)
    if len(rows) != len(expected_lines):
        reasons.add("TARGET_JOURNAL_LINE_COUNT_DRIFT")
    if any(len(values) != 1 for values in actual_lines.values()):
        reasons.add("TARGET_JOURNAL_LINE_IDENTITY_DRIFT")
    transaction_id = next(iter(transaction_ids)) if len(transaction_ids) == 1 else ""
    debit_total = Decimal("0")
    credit_total = Decimal("0")
    for line_id, expected in expected_lines.items():
        candidates = actual_lines.get(line_id, [])
        if len(candidates) != 1:
            reasons.add("TARGET_JOURNAL_LINE_MISSING")
            continue
        row = candidates[0]
        side = "DEBIT" if Decimal(expected["debit"]) > 0 else "CREDIT"
        type_enum = 2 if side == "DEBIT" else 1
        amount = expected["debit"] if side == "DEBIT" else expected["credit"]
        if side == "DEBIT":
            debit_total += Decimal(str(row.get("journal_amount") or 0))
        else:
            credit_total += Decimal(str(row.get("journal_amount") or 0))
        actual = {
            "source_account_id": str(row.get("source_account_id") or ""),
            "source_account_code": str(row.get("source_account_code") or ""),
            "target_gl_account_id": row.get("target_gl_account_id"),
            "journal_account_id": row.get("journal_account_id"),
            "journal_account_code": str(row.get("journal_account_code") or ""),
            "source_debit_amount": _amount_text(row.get("source_debit_amount"), 2),
            "source_credit_amount": _amount_text(row.get("source_credit_amount"), 2),
            "source_side": row.get("source_side"),
            "source_amount": _amount_text(row.get("source_amount"), 2),
            "target_side": row.get("target_side"),
            "target_type_enum": row.get("target_type_enum"),
            "target_amount": _amount_text(row.get("target_amount"), 6),
            "target_entry_date": str(row.get("target_entry_date")),
            "source_destination_branch_id": str(row.get("source_destination_branch_id") or ""),
            "target_office_id": row.get("target_office_id"),
            "target_office_external_id": str(row.get("target_office_external_id") or ""),
            "target_dimensions": _dimensions(row.get("target_dimensions")),
            "target_description_sha256": row.get("target_description_sha256"),
            "line_result": row.get("line_result"),
            "journal_identity": row.get("target_journal_entry_id") == row.get("journal_entry_id"),
            "journal_account_matches": row.get("target_gl_account_id") == row.get("journal_account_id"),
            "journal_office_id": row.get("journal_office_id"),
            "journal_office_external_id": str(row.get("journal_office_external_id") or ""),
            "currency_code": row.get("currency_code"),
            "journal_transaction_id": str(row.get("journal_transaction_id") or ""),
            "reversed": bool(row.get("reversed")),
            "reversal_id": row.get("reversal_id"),
            "journal_ref_num": row.get("journal_ref_num"),
            "manual_entry": bool(row.get("manual_entry")),
            "journal_entry_date": str(row.get("journal_entry_date")),
            "journal_type_enum": row.get("journal_type_enum"),
            "journal_amount": _amount_text(row.get("journal_amount"), 6),
            "journal_description": row.get("journal_description"),
            "journal_dimensions": _dimensions(row.get("journal_dimensions")),
            "product_links_absent": all(row.get(field) is None for field in (
                "loan_transaction_id", "savings_transaction_id", "client_transaction_id",
                "share_transaction_id", "entity_type_enum", "entity_id",
            )),
        }
        expected_values = {
            "source_account_id": expected["source_account_id"],
            "source_account_code": expected["source_account_code"],
            "target_gl_account_id": expected["target_gl_account_id"],
            "journal_account_id": expected["target_gl_account_id"],
            "journal_account_code": expected["target_account_code"],
            "source_debit_amount": _amount_text(expected["debit"], 2),
            "source_credit_amount": _amount_text(expected["credit"], 2),
            "source_side": side,
            "source_amount": _amount_text(amount, 2),
            "target_side": side,
            "target_type_enum": type_enum,
            "target_amount": _amount_text(amount, 6),
            "target_entry_date": payload["entry_date"],
            "source_destination_branch_id": expected["source_destination_branch_id"],
            "target_office_id": expected["office_id"],
            "target_office_external_id": str(expected["dimensions"]["office"]),
            "target_dimensions": expected["dimensions"],
            "target_description_sha256": expected["description_sha256"],
            "line_result": "IMPORTED",
            "journal_identity": True,
            "journal_account_matches": True,
            "journal_office_id": expected["office_id"],
            "journal_office_external_id": str(expected["dimensions"]["office"]),
            "currency_code": payload["currency"],
            "journal_transaction_id": transaction_id,
            "reversed": False,
            "reversal_id": None,
            "journal_ref_num": payload["ref_num"],
            "manual_entry": True,
            "journal_entry_date": payload["entry_date"],
            "journal_type_enum": type_enum,
            "journal_amount": _amount_text(amount, 6),
            "journal_description": expected["description"],
            "journal_dimensions": expected["dimensions"],
            "product_links_absent": True,
        }
        if actual != expected_values:
            reasons.add("TARGET_JOURNAL_LINE_DRIFT")
    if _amount_text(debit_total, 6) != _amount_text(payload.get("debit_total"), 6) or \
            _amount_text(credit_total, 6) != _amount_text(payload.get("credit_total"), 6):
        reasons.add("TARGET_JOURNAL_TOTAL_DRIFT")
    return sorted(reasons)


def _direct_balance_control(actions: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected_agency: Counter[tuple[str, int, str]] = Counter()
    actual_agency: Counter[tuple[str, int, str]] = Counter()
    for action in actions:
        payload = action.get("payload") or {}
        for line in payload.get("lines", []):
            side = "DEBIT" if Decimal(line["debit"]) > 0 else "CREDIT"
            amount = Decimal(line["debit"] if side == "DEBIT" else line["credit"])
            expected_agency[(line["target_account_code"], int(line["office_id"]), side)] += amount
    for row in rows:
        side = "DEBIT" if int(row.get("journal_type_enum") or 0) == 2 else "CREDIT"
        actual_agency[(str(row.get("journal_account_code") or ""), int(row.get("journal_office_id") or 0), side)] += Decimal(
            str(row.get("journal_amount") or 0)
        )
    expected_consolidated: Counter[tuple[str, str]] = Counter()
    actual_consolidated: Counter[tuple[str, str]] = Counter()
    for (account, _office, side), amount in expected_agency.items():
        expected_consolidated[(account, side)] += amount
    for (account, _office, side), amount in actual_agency.items():
        actual_consolidated[(account, side)] += amount
    agency_keys = set(expected_agency) | set(actual_agency)
    consolidated_keys = set(expected_consolidated) | set(actual_consolidated)
    agency_variances = sum(1 for key in agency_keys if expected_agency[key] != actual_agency[key])
    consolidated_variances = sum(
        1 for key in consolidated_keys if expected_consolidated[key] != actual_consolidated[key]
    )
    return {
        "scope": "frozen_plan_journals",
        "opening_basis": "direct_journals_from_approved_historical_origin",
        "agency_bucket_count": len(agency_keys),
        "agency_variance_count": agency_variances,
        "consolidated_bucket_count": len(consolidated_keys),
        "consolidated_variance_count": consolidated_variances,
        "expected_hash": _hash({str(key): _amount_text(value, 6) for key, value in sorted(expected_agency.items())}),
        "actual_hash": _hash({str(key): _amount_text(value, 6) for key, value in sorted(actual_agency.items())}),
    }


def _source_ledger_control(
    settings: Settings, contract: AccountingContract, document: dict[str, Any],
) -> dict[str, Any]:
    eligible = [action for action in document["actions"] if action["disposition"] != "QUARANTINED"]
    if not eligible:
        raise RuntimeError("Accounting ledger control requires at least one eligible journal")
    company = str(contract.raw["currency_precision"]["source_company"])
    origin = str(contract.raw["historical_origin"]["first_eligible_journal_date"])
    cutoff = str(document["accounting_cutoff"]["date"])
    with source_connection(settings.source) as conn:
        summary_rows = select_rows(
            conn, SOURCE_LEDGER_CONTROL_SUMMARY_QUERY,
            (company, origin, company, cutoff),
        )
        if not summary_rows or not summary_rows[0].get("control_period_id"):
            raise RuntimeError("SOURCE_LEDGER_CONTROL_PERIOD_UNRESOLVED")
        control_period_id = str(summary_rows[0]["control_period_id"])
        journal_rows = select_rows(
            conn, SOURCE_LEDGER_CONTROL_QUERY,
            (control_period_id, company, origin),
        )
        mayor_rows = select_rows(
            conn, SOURCE_LEDGER_MAYOR_QUERY,
            (company, control_period_id),
        )
        mayor_by_key = {
            (str(row["destination_branch_id"]), str(row["account_id"])): row.get("ledger_closing")
            for row in mayor_rows
        }
        comparisons = []
        for row in journal_rows:
            comparison = dict(row)
            key = (str(row["destination_branch_id"]), str(row["account_id"]))
            comparison["ledger_closing"] = mayor_by_key.get(key, Decimal("0"))
            comparisons.append(comparison)
        mismatches = [
            row for row in comparisons
            if _decimal(row.get("journal_closing")) != _decimal(row.get("ledger_closing"))
        ]
        rollups: dict[tuple[str, str], dict[str, Any]] = {}
        if mismatches:
            requested = "\nUNION ALL\n".join(
                "SELECT CAST(? AS char(3)),CAST(? AS char(10))" for _ in mismatches
            )
            params: list[Any] = []
            for row in mismatches:
                params.extend([row["destination_branch_id"], row["account_id"]])
            params.extend([company, control_period_id])
            rollup_rows = select_rows(
                conn,
                SOURCE_HYBRID_ROLLUP_QUERY_PREFIX + requested + SOURCE_HYBRID_ROLLUP_QUERY_SUFFIX,
                tuple(params),
            )
            rollups = {
                (str(row["destination_branch_id"]), str(row["account_id"])): row
                for row in rollup_rows
            }
    base = summary_rows[0]
    accepted: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    unsafe_hybrid_count = 0
    for row in mismatches:
        rollup = rollups.get((str(row["destination_branch_id"]), str(row["account_id"])), {})
        child_count = int(rollup.get("child_account_count") or 0)
        child_rows = int(rollup.get("child_ledger_row_count") or 0)
        safe_hybrid = (
            child_count > 0
            and child_rows == child_count
            and int(row.get("non_annual_liquidation_line_count") or 0) == 0
            and _decimal(row.get("journal_closing")) == 0
            and _decimal(row.get("ledger_closing")) == _decimal(rollup.get("child_ledger_closing"))
        )
        if safe_hybrid:
            accepted.append(row)
        else:
            unresolved.append(row)
            unsafe_hybrid_count += int(child_count > 0)
    accepted_variance = sum(
        (abs(_decimal(row["journal_closing"]) - _decimal(row["ledger_closing"])) for row in accepted),
        Decimal("0"),
    )
    unresolved_variance = sum(
        (abs(_decimal(row["journal_closing"]) - _decimal(row["ledger_closing"])) for row in unresolved),
        Decimal("0"),
    )
    return {
        "control_period_id": str(base["control_period_id"]),
        "control_period_end": str(base.get("control_period_end") or ""),
        "closed_before_cutoff": int(base.get("closed_before_cutoff") or 0),
        "eligible_journal_count": int(base.get("eligible_journal_count") or 0),
        "compared_account_branch_count": len(comparisons),
        "raw_closing_mismatch_count": len(mismatches),
        "accepted_hybrid_rollup_count": len(accepted),
        "accepted_hybrid_rollup_variance": accepted_variance,
        "accepted_hybrid_rollup_hash": _hash([
            {
                "destination_branch_id": row["destination_branch_id"],
                "account_id": row["account_id"],
                "journal_closing": _amount_text(row["journal_closing"], 2),
                "ledger_closing": _amount_text(row["ledger_closing"], 2),
            }
            for row in sorted(accepted, key=lambda value: (value["destination_branch_id"], value["account_id"]))
        ]),
        "unsafe_hybrid_account_count": unsafe_hybrid_count,
        "closing_mismatch_count": len(unresolved),
        "absolute_closing_variance": unresolved_variance,
    }


def reconcile_accounting(
    settings: Settings, state: State, contract: AccountingContract, run_id: str,
    target_snapshot: dict[str, Any] | None = None,
    source_ledger_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Accounting run belongs to a different block or target")
    plan = state.plan(run["plan_id"])
    document = plan["document"]
    cutoff = document["accounting_cutoff"]
    actions = document["actions"]
    keys = [action["source_key"] for action in actions if action["disposition"] != "QUARANTINED"]
    snapshot = target_snapshot or _target_reconciliation_snapshot(
        settings.target.pg_url or "", contract, keys, cutoff["date"]
    )
    rows_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshot.get("rows", []):
        rows_by_key[str(row.get("source_key") or "")].append(row)
    # Reconciliation may be retried from a zero-write child run after the
    # original apply completed. Read the durable outcome across the frozen
    # plan's complete retry chain instead of treating that child in isolation.
    apply_items = {item["source_key"]: item for item in state.plan_run_items(plan["id"])}
    findings: list[dict[str, Any]] = []
    counts = Counter()
    for action in actions:
        key = action["source_key"]
        item = apply_items.get(key)
        reasons: list[str] = []
        if action["disposition"] == "QUARANTINED":
            if item is None or item["status"] != "quarantined":
                reasons = ["SOURCE_DISPOSITION_NOT_RECORDED"]
            else:
                counts["quarantined"] += 1
        elif item is None or (
            item["status"] not in {"succeeded", "recovered", "unchanged", "reconciled"}
            and not (
                item["status"] == "failed"
                and (state.accounting_attempt(item["run_id"], key) or {}).get("error_class") == "reconciliation"
            )
        ):
            reasons = ["ACCOUNTING_APPLY_NOT_TERMINAL"]
        else:
            reasons = _reconcile_accounting_action(action, rows_by_key.get(key, []), document)
            recorded_target = str(item.get("target_id") or "")
            target_ids = {str(row.get("target_transaction_id") or "") for row in rows_by_key.get(key, [])}
            if recorded_target and target_ids != {recorded_target}:
                reasons = sorted(set(reasons) | {"TARGET_TRANSACTION_ID_DRIFT"})
        if reasons:
            findings.append({"source_key": key, "reason_codes": reasons})
            state.record_accounting_reconciliation(run_id, key, False, ",".join(reasons))
            counts["mismatched"] += 1
        elif action["disposition"] != "QUARANTINED":
            state.record_accounting_reconciliation(item["run_id"], key, True)
            counts["reconciled"] += 1
    boundary = snapshot.get("boundary", {})
    boundary_findings = []
    if int(boundary.get("native_non_manual_pre_cutoff", 0)):
        boundary_findings.append("TARGET_NATIVE_NON_MANUAL_PRE_CUTOFF_GL")
    if int(boundary.get("imported_on_or_after_cutoff", 0)):
        boundary_findings.append("TARGET_IMPORTED_ON_OR_AFTER_CUTOFF")
    balance_control = _direct_balance_control(
        [action for action in actions if action["disposition"] != "QUARANTINED"], snapshot.get("rows", [])
    )
    balance_findings = []
    if balance_control["agency_variance_count"]:
        balance_findings.append("TARGET_AGENCY_BALANCE_DRIFT")
    if balance_control["consolidated_variance_count"]:
        balance_findings.append("TARGET_CONSOLIDATED_BALANCE_DRIFT")
    source_ledger_control = source_ledger_snapshot or _source_ledger_control(settings, contract, document)
    source_ledger_findings = []
    control_period_end = _date(source_ledger_control.get("control_period_end"))
    if control_period_end is None and int(source_ledger_control.get("closed_before_cutoff", 0)):
        # Compatibility for stored reconciliation evidence created before the
        # control-period end became explicit. New live controls always return it.
        controlled_dates = [
            _date(action["payload"].get("entry_date")) for action in actions
            if action["disposition"] != "QUARANTINED"
        ]
        control_period_end = max((value for value in controlled_dates if value is not None), default=None)
    controlled_action_count = sum(
        1 for action in actions
        if action["disposition"] != "QUARANTINED"
        and control_period_end is not None
        and _date(action["payload"].get("entry_date")) is not None
        and _date(action["payload"].get("entry_date")) <= control_period_end
    )
    if control_period_end is None or not int(source_ledger_control.get("closed_before_cutoff", 0)):
        source_ledger_findings.append("SOURCE_LEDGER_CONTROL_PERIOD_UNRESOLVED")
    if int(source_ledger_control.get("eligible_journal_count", -1)) != controlled_action_count:
        source_ledger_findings.append("SOURCE_LEDGER_CONTROL_SCOPE_INCOMPLETE")
    if int(source_ledger_control.get("unsafe_hybrid_account_count", 0)):
        source_ledger_findings.append("SOURCE_HYBRID_ACCOUNT_ROLLUP_UNSAFE")
    if int(source_ledger_control.get("closing_mismatch_count", -1)):
        source_ledger_findings.append("SOURCE_JOURNAL_TO_CNT_MAYOR_CLOSING_DRIFT")
    ok = not findings and not boundary_findings and not balance_findings and not source_ledger_findings
    summary = {
        "reconciled": counts["reconciled"], "quarantined": counts["quarantined"],
        "mismatched": counts["mismatched"], "boundary_mismatches": len(boundary_findings),
        "balance_mismatches": len(balance_findings),
        "source_ledger_mismatches": len(source_ledger_findings),
    }
    state.finish_run(run_id, "reconciled" if ok else "reconciliation-failed", summary)
    result = {
        "ok": ok, "block": BLOCK, "reconciliation_version": RECONCILIATION_VERSION,
        "run_id": run_id, "plan_id": plan["id"],
        "counts": summary, "finding_count": len(findings), "findings": findings,
        "boundary_findings": boundary_findings, "balance_findings": balance_findings,
        "direct_balance_control": balance_control,
        "source_ledger_control": source_ledger_control,
        "source_ledger_findings": source_ledger_findings,
        "gate8_acceptance_ok": ok,
        "direct_journal_control_hash": _hash({
            "source_keys": sorted(keys), "rows": snapshot.get("rows", []), "boundary": boundary,
        }),
    }
    state.record_reconciliation(run_id, result)
    return result


def accounting_status(state: State, target_fingerprint: str) -> dict[str, Any]:
    runs = state.recent(BLOCK, target_fingerprint)
    counts = {key: 0 for key in ("planned", "imported", "unchanged", "failed", "quarantined", "drifted", "reconciled")}
    if not runs:
        return {"block": BLOCK, "target_fingerprint": target_fingerprint, "counts": counts, "runs": []}
    latest = runs[0]
    plan = state.plan(latest["plan_id"])
    outcomes = {row["source_key"]: row for row in state.plan_run_items(plan["id"])}
    for action in plan["document"]["actions"]:
        item = outcomes.get(action["source_key"])
        if item is None or item["status"] == "pending":
            counts["planned"] += 1
        elif item["status"] in {"succeeded", "recovered"}:
            counts["imported"] += 1
        elif item["status"] == "unchanged":
            counts["unchanged"] += 1
        elif item["status"] == "quarantined":
            counts["quarantined"] += 1
        elif item["status"] == "reconciled":
            counts["reconciled"] += 1
        elif item["status"] == "failed":
            if "DRIFT" in str(item.get("error_code") or ""):
                counts["drifted"] += 1
            else:
                counts["failed"] += 1
    return {"block": BLOCK, "target_fingerprint": target_fingerprint, "plan_id": plan["id"],
            "counts": counts, "runs": runs}
