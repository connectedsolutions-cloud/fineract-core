from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .accounting_report_proof import MEASURES
from .accounting_g9_source_reports import normalize_authoritative_report_directory, target_presentation_controls
from .arissto import select_rows, source_connection
from .config import ROOT, Settings, load_settings
from .connections import FineractApi, postgres_connection


G9_VERSION = "accounting-g9-statement-acceptance-v1"
CURRENCY_FIELDS = (*MEASURES, "accumulated_balance")
DECEMBER_PERIOD = "00053"
JANUARY_PERIOD = "00054"
YEAR_FROM = date(2024, 1, 1)
DECEMBER_FROM = date(2024, 12, 1)
DECEMBER_TO = date(2024, 12, 31)
JANUARY_FROM = date(2025, 1, 1)
CONTROL_ACCOUNTS = ("314002", "2220050501")

TARGET_READINESS_QUERY = """
WITH imported AS (
    SELECT j.id, j.source_period_id, j.source_journal_type,
           j.source_liquidation_flag, j.source_opening_flag,
           j.source_journal_date, j.target_transaction_id, j.cutoff_date
      FROM credesal_arissto_gl_journal j
     WHERE j.result IN ('IMPORTED', 'UNCHANGED', 'RECONCILED')
), imported_lines AS (
    SELECT l.*, j.source_period_id, j.source_journal_type,
           j.source_liquidation_flag, j.source_opening_flag,
           j.source_journal_date, j.target_transaction_id
      FROM credesal_arissto_gl_journal_line l
      JOIN imported j ON j.id = l.journal_provenance_id
     WHERE l.result IN ('IMPORTED', 'UNCHANGED', 'RECONCILED')
)
SELECT
    (SELECT COUNT(*) FROM imported) AS imported_journals,
    (SELECT COUNT(*) FROM imported_lines) AS provenance_lines,
    (SELECT COUNT(*) FROM imported WHERE source_period_id=%s) AS december_journals,
    (SELECT COUNT(*) FROM imported_lines WHERE source_period_id=%s) AS december_lines,
    (SELECT COUNT(*) FROM imported
      WHERE source_period_id=%s AND source_journal_type='003') AS december_closing_journals,
    (SELECT COUNT(*) FROM imported_lines
      WHERE source_journal_date BETWEEN %s AND %s) AS imported_2024_lines,
    (SELECT COUNT(*) FROM imported
      WHERE COALESCE(source_opening_flag, '0') <> '0') AS nonzero_opening_flags,
    (SELECT COUNT(*) FROM imported
      WHERE source_journal_type='003'
        AND (source_liquidation_flag <> '1'
          OR EXTRACT(MONTH FROM source_journal_date) <> 12
          OR EXTRACT(DAY FROM source_journal_date) <> 31
          OR COALESCE(source_opening_flag, '0') <> '0')) AS invalid_annual_shapes,
    (SELECT COUNT(*) FROM imported_lines l
      JOIN acc_gl_journal_entry e ON e.id=l.target_journal_entry_id
      JOIN m_office o ON o.id=e.office_id
     WHERE e.dimensions->>'office' IS DISTINCT FROM o.external_id
        OR e.dimensions->>'office' IS DISTINCT FROM l.target_office_external_id
        OR e.office_id <> l.target_office_id) AS dimension_mismatches,
    (SELECT COUNT(*) FROM imported_lines l
      LEFT JOIN acc_gl_journal_entry e ON e.id=l.target_journal_entry_id
     WHERE e.id IS NULL) AS missing_target_lines,
    (SELECT COUNT(*) FROM acc_gl_journal_entry e
     WHERE e.entry_date < (SELECT MIN(cutoff_date) FROM imported)
       AND NOT EXISTS (
           SELECT 1 FROM imported_lines l WHERE l.target_journal_entry_id=e.id
       )) AS unprovenanced_pre_cutoff_lines
"""

SOURCE_TRACE_QUERY = """
WITH roots AS (
    SELECT c.ID_EMPRESA,c.ID_CUENTA,RTRIM(c.CODIGO_CUENTA) AS control_gl_code
      FROM dbo.CNT_CATALOGO_CUENTAS c
     WHERE c.ID_EMPRESA=? AND RTRIM(c.CODIGO_CUENTA) IN (?,?)
), descendants AS (
    SELECT ID_EMPRESA,ID_CUENTA,control_gl_code FROM roots
    UNION ALL
    SELECT c.ID_EMPRESA,c.ID_CUENTA,d.control_gl_code
      FROM dbo.CNT_CATALOGO_CUENTAS c
      JOIN descendants d
        ON d.ID_EMPRESA=c.ID_EMPRESA AND d.ID_CUENTA=c.ID_CUENTA_PADRE
), journal_activity AS (
    SELECT CAST(p.FECHA_PARTIDA AS date) AS activity_date,
           RTRIM(p.ID_PERIODO) AS period_id,
           RTRIM(d.ID_SUCURSAL_DESTINO) AS branch_id,
           tree.control_gl_code,
           RTRIM(c.CODIGO_CUENTA) AS posting_gl_code,
           RTRIM(c.TIPO_SALDO) AS balance_nature,
           RTRIM(p.ID_TIPO_PARTIDA) AS journal_type,
           SUM(d.DEBE) AS debit,
           SUM(d.HABER) AS credit,
           SUM(CASE WHEN RTRIM(c.TIPO_SALDO)='A'
                    THEN d.HABER-d.DEBE ELSE d.DEBE-d.HABER END) AS signed_amount
      FROM dbo.CNT_PARTIDAS p
      JOIN dbo.CNT_DETALLE_PARTIDAS d
        ON d.ID_EMPRESA=p.ID_EMPRESA AND d.ID_SUCURSAL=p.ID_SUCURSAL
       AND d.ID_PERIODO=p.ID_PERIODO AND d.ID_PARTIDA=p.ID_PARTIDA
      JOIN dbo.CNT_CATALOGO_CUENTAS c
        ON c.ID_EMPRESA=d.ID_EMPRESA AND c.ID_CUENTA=d.ID_CUENTA
      JOIN descendants tree
        ON tree.ID_EMPRESA=d.ID_EMPRESA AND tree.ID_CUENTA=d.ID_CUENTA
     WHERE p.ID_EMPRESA=? AND p.ESTADO_PARTIDA='3'
       AND CAST(p.FECHA_PARTIDA AS date)<=?
     GROUP BY CAST(p.FECHA_PARTIDA AS date),p.ID_PERIODO,d.ID_SUCURSAL_DESTINO,
              tree.control_gl_code,c.CODIGO_CUENTA,c.TIPO_SALDO,p.ID_TIPO_PARTIDA
)
SELECT * FROM journal_activity
ORDER BY control_gl_code,branch_id,activity_date,posting_gl_code,journal_type
"""

SOURCE_MAYOR_QUERY = """
SELECT RTRIM(m.ID_PERIODO) AS period_id,
       RTRIM(m.ID_SUCURSAL) AS branch_id,
       RTRIM(c.CODIGO_CUENTA) AS gl_code,
       RTRIM(c.TIPO_SALDO) AS balance_nature,
       m.SALDO_INICIAL AS opening_balance,
       m.MONTO_CARGOS AS debit,
       m.MONTO_ABONOS AS credit,
       m.SALDO_FINAL AS closing_balance,
       m.SALDO_FINAL_LIQ AS liquidation_closing_balance
  FROM dbo.CNT_MAYOR m
  JOIN dbo.CNT_CATALOGO_CUENTAS c
    ON c.ID_EMPRESA=m.ID_EMPRESA AND c.ID_CUENTA=m.ID_CUENTA
 WHERE m.ID_EMPRESA=? AND m.ID_PERIODO IN (?,?)
   AND (RTRIM(c.CODIGO_CUENTA) LIKE ? OR RTRIM(c.CODIGO_CUENTA) LIKE ?)
 ORDER BY gl_code,branch_id,period_id
"""

SOURCE_JANUARY_CONTINUITY_QUERY = """
WITH used_accounts AS (
    SELECT DISTINCT d.ID_EMPRESA,d.ID_SUCURSAL_DESTINO,d.ID_CUENTA
      FROM dbo.CNT_PARTIDAS p
      JOIN dbo.CNT_DETALLE_PARTIDAS d
        ON d.ID_EMPRESA=p.ID_EMPRESA AND d.ID_SUCURSAL=p.ID_SUCURSAL
       AND d.ID_PERIODO=p.ID_PERIODO AND d.ID_PARTIDA=p.ID_PARTIDA
     WHERE p.ID_EMPRESA=? AND p.ESTADO_PARTIDA='3'
       AND CAST(p.FECHA_PARTIDA AS date)<=?
)
SELECT RTRIM(u.ID_SUCURSAL_DESTINO) AS branch_id,
       RTRIM(c.CODIGO_CUENTA) AS gl_code,
       RTRIM(c.ID_TIPO_CUENTA) AS account_type,
       RTRIM(c.TIPO_SALDO) AS balance_nature,
       d.SALDO_FINAL AS december_closing_balance,
       j.SALDO_INICIAL AS january_opening_balance
  FROM used_accounts u
  JOIN dbo.CNT_CATALOGO_CUENTAS c
    ON c.ID_EMPRESA=u.ID_EMPRESA AND c.ID_CUENTA=u.ID_CUENTA
  LEFT JOIN dbo.CNT_MAYOR d
    ON d.ID_EMPRESA=u.ID_EMPRESA AND d.ID_SUCURSAL=u.ID_SUCURSAL_DESTINO
   AND d.ID_CUENTA=u.ID_CUENTA AND d.ID_PERIODO=?
  LEFT JOIN dbo.CNT_MAYOR j
    ON j.ID_EMPRESA=u.ID_EMPRESA AND j.ID_SUCURSAL=u.ID_SUCURSAL_DESTINO
   AND j.ID_CUENTA=u.ID_CUENTA AND j.ID_PERIODO=?
 WHERE d.ID_CUENTA IS NOT NULL OR j.ID_CUENTA IS NOT NULL
 ORDER BY branch_id,gl_code
"""

SOURCE_DAILY_QUERY = """
SELECT RTRIM(md.ID_PERIODO) AS period_id,
       RTRIM(md.ID_SUCURSAL) AS branch_id,
       RTRIM(c.CODIGO_CUENTA) AS gl_code,
       RTRIM(md.ID_CIERRE_DIARIO) AS daily_close_id,
       CAST(cd.FECHA_OPERACION AS date) AS activity_date,
       RTRIM(c.TIPO_SALDO) AS balance_nature,
       md.SALDO_INICIAL AS opening_balance,
       md.MONTO_CARGOS AS debit,
       md.MONTO_ABONOS AS credit,
       md.SALDO_FINAL AS closing_balance
  FROM dbo.CNT_MAYOR_DIARIO md
  JOIN dbo.CNT_CATALOGO_CUENTAS c
    ON c.ID_EMPRESA=md.ID_EMPRESA AND c.ID_CUENTA=md.ID_CUENTA
  JOIN dbo.CIERRE_DIARIO cd
    ON cd.ID_EMPRESA=md.ID_EMPRESA AND cd.ID_CIERRE_DIARIO=md.ID_CIERRE_DIARIO
 WHERE md.ID_EMPRESA=? AND CAST(cd.FECHA_OPERACION AS date)<=?
   AND RTRIM(c.CODIGO_CUENTA) IN (?,?)
 ORDER BY gl_code,branch_id,cd.FECHA_OPERACION,md.ID_CIERRE_DIARIO
"""

TARGET_TRACE_QUERY = """
SELECT e.entry_date AS activity_date,
       p.source_period_id AS period_id,
       o.external_id AS office_external_id,
       a.gl_code,
       p.source_journal_type AS journal_type,
       SUM(CASE WHEN e.type_enum=2 THEN e.amount ELSE 0 END) AS debit,
       SUM(CASE WHEN e.type_enum=1 THEN e.amount ELSE 0 END) AS credit
  FROM acc_gl_journal_entry e
  JOIN acc_gl_account a ON a.id=e.account_id
  JOIN m_office o ON o.id=e.office_id
  JOIN credesal_arissto_gl_journal_line l ON l.target_journal_entry_id=e.id
  JOIN credesal_arissto_gl_journal p ON p.id=l.journal_provenance_id
 WHERE e.entry_date<=%s AND (a.gl_code LIKE %s OR a.gl_code LIKE %s)
 GROUP BY e.entry_date,p.source_period_id,o.external_id,a.gl_code,p.source_journal_type
 ORDER BY a.gl_code,o.external_id,e.entry_date,p.source_journal_type
"""

TARGET_JANUARY_OPENING_QUERY = """
SELECT a.gl_code,o.external_id AS office_external_id,
       SUM(CASE WHEN e.type_enum=2 THEN e.amount ELSE 0 END) AS debit,
       SUM(CASE WHEN e.type_enum=1 THEN e.amount ELSE 0 END) AS credit
  FROM acc_gl_journal_entry e
  JOIN acc_gl_account a ON a.id=e.account_id
  JOIN m_office o ON o.id=e.office_id
 WHERE e.entry_date<%s
 GROUP BY a.gl_code,o.external_id
 ORDER BY o.external_id,a.gl_code
"""


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_sha256(value: Any) -> str:
    payload = json.dumps(_json_value(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _query_one(conn: Any, query: str, params: tuple[Any, ...]) -> dict[str, Any]:
    cursor = conn.execute(query, params)
    values = cursor.fetchone()
    return dict(zip((item.name for item in cursor.description), values, strict=True))


def inspect_g9_readiness(settings: Settings) -> dict[str, Any]:
    if settings.target.name != "local":
        raise ValueError("G9 acceptance is restricted to the local target")
    if not settings.target.pg_url:
        raise ValueError("FINERACT_LOCAL_PG_URL is required for G9 acceptance")
    with postgres_connection(settings.target.pg_url) as conn:
        counts = _query_one(
            conn,
            TARGET_READINESS_QUERY,
            (DECEMBER_PERIOD, DECEMBER_PERIOD, DECEMBER_PERIOD, YEAR_FROM, DECEMBER_TO),
        )
    blockers = []
    exact_expectations = {
        "imported_journals": 5563,
        "provenance_lines": 26820,
        "december_journals": 380,
        "december_lines": 2065,
        "december_closing_journals": 3,
        "imported_2024_lines": 16728,
        "nonzero_opening_flags": 0,
        "invalid_annual_shapes": 0,
        "dimension_mismatches": 0,
        "missing_target_lines": 0,
        "unprovenanced_pre_cutoff_lines": 0,
    }
    for field, expected in exact_expectations.items():
        if int(counts[field]) != expected:
            blockers.append({"check": field, "expected": expected, "actual": int(counts[field])})
    return {
        "ready": not blockers,
        "version": G9_VERSION,
        "target": settings.target.name,
        "tenant": settings.target.tenant,
        "period_id": DECEMBER_PERIOD,
        "counts": _json_value(counts),
        "expectations": exact_expectations,
        "blockers": blockers,
        "api_required_for_reports": True,
    }


def _daily_mayor_variances(
    source_activity: list[dict[str, Any]], source_daily: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    activity_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in source_activity:
        activity_by_key.setdefault((row["control_gl_code"], row["branch_id"]), []).append(row)
    findings = []
    for key in sorted({(row["gl_code"], row["branch_id"]) for row in source_daily}):
        activities = sorted(activity_by_key.get(key, []), key=lambda row: row["activity_date"])
        running = Decimal("0.00")
        activity_index = 0
        first = None
        last = None
        for mayor in sorted(
            (row for row in source_daily if (row["gl_code"], row["branch_id"]) == key),
            key=lambda row: (row["activity_date"], row["daily_close_id"]),
        ):
            while activity_index < len(activities) and activities[activity_index]["activity_date"] <= mayor["activity_date"]:
                running += Decimal(str(activities[activity_index]["signed_amount"] or 0))
                activity_index += 1
            variance = Decimal(str(mayor["closing_balance"] or 0)) - running
            if variance:
                item = {
                    "gl_code": key[0],
                    "branch_id": key[1],
                    "activity_date": mayor["activity_date"],
                    "journal_derived_closing": running,
                    "daily_mayor_closing": mayor["closing_balance"],
                    "variance": variance,
                }
                first = first or item
                last = item
        if first:
            findings.append({"gl_code": key[0], "branch_id": key[1], "first": first, "last": last})
    return _json_value(findings)


def _source_target_activity_variances(
    source_activity: list[dict[str, Any]], target_activity: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    branch_to_office = {"001": "1", "002": "2"}
    source_totals: dict[tuple[str, str], dict[str, Decimal]] = {}
    target_totals: dict[tuple[str, str], dict[str, Decimal]] = {}
    for row in source_activity:
        total = source_totals.setdefault(
            (row["posting_gl_code"], branch_to_office.get(row["branch_id"], row["branch_id"])),
            {"debit": Decimal(), "credit": Decimal()},
        )
        total["debit"] += Decimal(str(row["debit"] or 0))
        total["credit"] += Decimal(str(row["credit"] or 0))
    for row in target_activity:
        total = target_totals.setdefault(
            (row["gl_code"], row["office_external_id"]), {"debit": Decimal(), "credit": Decimal()}
        )
        total["debit"] += Decimal(str(row["debit"] or 0))
        total["credit"] += Decimal(str(row["credit"] or 0))
    findings = []
    for key in sorted(set(source_totals) | set(target_totals)):
        source = source_totals.get(key, {"debit": Decimal(), "credit": Decimal()})
        target = target_totals.get(key, {"debit": Decimal(), "credit": Decimal()})
        if source != target:
            findings.append({
                "gl_code": key[0], "office_external_id": key[1],
                "source": source, "target": target,
            })
    return _json_value(findings)


def _source_january_continuity_variances(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for row in rows:
        december = Decimal(str(row["december_closing_balance"] or 0)).quantize(Decimal("0.01"))
        january = Decimal(str(row["january_opening_balance"] or 0)).quantize(Decimal("0.01"))
        if december != january:
            findings.append({
                "gl_code": row["gl_code"],
                "branch_id": row["branch_id"],
                "december_closing_balance": december,
                "january_opening_balance": january,
                "variance": january - december,
            })
    return _json_value(findings)


def _target_january_opening_variances(
    source_rows: list[dict[str, Any]], target_rows: list[dict[str, Any]],
    account_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    branch_to_office = {"001": "1", "002": "2"}
    overrides = account_overrides or {}
    target = {(row["gl_code"], row["office_external_id"]): row for row in target_rows}
    findings = []
    covered_target_keys: set[tuple[str, str]] = set()
    compared_alias_groups: set[tuple[str, str]] = set()
    for source_row in source_rows:
        office = branch_to_office.get(source_row["branch_id"], source_row["branch_id"])
        source_code = source_row["gl_code"]
        # CNT_MAYOR materializes hierarchy nodes such as 314002 and
        # 2220050501. Reconstruct the equivalent target presentation balance
        # from native direct-account balances, after applying the frozen
        # Arissto-to-Fineract account overrides.
        target_codes = {
            overrides.get(candidate["gl_code"], candidate["gl_code"])
            for candidate in source_rows
            if candidate["branch_id"] == source_row["branch_id"]
            and candidate["gl_code"].startswith(source_code)
        }
        covered_target_keys.update((code, office) for code in target_codes)
        direct_target_code = overrides.get(source_code, source_code)
        direct_aliases = [
            candidate
            for candidate in source_rows
            if candidate["branch_id"] == source_row["branch_id"]
            and overrides.get(candidate["gl_code"], candidate["gl_code"]) == direct_target_code
        ]
        is_leaf_comparison = target_codes == {direct_target_code}
        if is_leaf_comparison and len(direct_aliases) > 1:
            alias_key = (office, direct_target_code)
            if alias_key in compared_alias_groups:
                continue
            compared_alias_groups.add(alias_key)
            expected = sum(
                (Decimal(str(candidate["january_opening_balance"] or 0)) for candidate in direct_aliases),
                Decimal(),
            )
            source_codes = sorted(candidate["gl_code"] for candidate in direct_aliases)
        else:
            expected = Decimal(str(source_row["january_opening_balance"] or 0))
            source_codes = [source_code]
        debit = sum(
            (Decimal(str(target[(code, office)]["debit"] or 0)) for code in target_codes if (code, office) in target),
            Decimal(),
        )
        credit = sum(
            (Decimal(str(target[(code, office)]["credit"] or 0)) for code in target_codes if (code, office) in target),
            Decimal(),
        )
        actual = debit - credit if source_row["balance_nature"] == "D" else credit - debit
        expected = expected.quantize(Decimal("0.01"))
        actual = actual.quantize(Decimal("0.01"))
        if expected != actual:
            findings.append({
                "gl_code": source_code,
                "source_gl_codes": source_codes,
                "target_gl_codes": sorted(target_codes),
                "office_external_id": office,
                "source_january_opening": expected,
                "target_pre_january_balance": actual,
                "variance": actual - expected,
            })
    for gl_code, office in sorted(set(target) - covered_target_keys):
        row = target[(gl_code, office)]
        debit = Decimal(str(row["debit"] or 0))
        credit = Decimal(str(row["credit"] or 0))
        if debit != credit:
            findings.append({
                "gl_code": None,
                "target_gl_codes": [gl_code],
                "office_external_id": office,
                "source_january_opening": Decimal(),
                "target_pre_january_balance": debit - credit,
                "variance": debit - credit,
                "reason": "TARGET_ACCOUNT_WITHOUT_SOURCE_MAYOR_ROW",
            })
    return _json_value(findings)


def trace_g9_controls(settings: Settings) -> dict[str, Any]:
    if settings.target.name != "local" or not settings.target.pg_url:
        raise ValueError("G9 control tracing requires the local target and FINERACT_LOCAL_PG_URL")
    company = "001"
    account_like = "314002%"
    account_prefix = "2220050501%"
    with source_connection(settings.source) as conn:
        source_activity = select_rows(
            conn,
            SOURCE_TRACE_QUERY,
            (company, CONTROL_ACCOUNTS[0], CONTROL_ACCOUNTS[1], company, DECEMBER_TO),
        )
        source_mayor = select_rows(
            conn,
            SOURCE_MAYOR_QUERY,
            (company, DECEMBER_PERIOD, JANUARY_PERIOD, account_like, account_prefix),
        )
        source_daily = select_rows(
            conn, SOURCE_DAILY_QUERY, (company, DECEMBER_TO, CONTROL_ACCOUNTS[0], CONTROL_ACCOUNTS[1])
        )
        source_continuity = select_rows(
            conn,
            SOURCE_JANUARY_CONTINUITY_QUERY,
            (company, DECEMBER_TO, DECEMBER_PERIOD, JANUARY_PERIOD),
        )
    with postgres_connection(settings.target.pg_url) as conn:
        cursor = conn.execute(TARGET_TRACE_QUERY, (DECEMBER_TO, account_like, account_prefix))
        target_activity = [
            dict(zip((item.name for item in cursor.description), row, strict=True)) for row in cursor.fetchall()
        ]
        cursor = conn.execute(TARGET_JANUARY_OPENING_QUERY, (JANUARY_FROM,))
        target_opening = [
            dict(zip((item.name for item in cursor.description), row, strict=True)) for row in cursor.fetchall()
        ]
    source_continuity_variances = _source_january_continuity_variances(source_continuity)
    account_contract = json.loads((ROOT / "config/accounting.json").read_text(encoding="utf-8"))
    target_opening_variances = _target_january_opening_variances(
        source_continuity,
        target_opening,
        account_contract["account_mapping"]["overrides"],
    )
    result = {
        "version": G9_VERSION,
        "period_id": DECEMBER_PERIOD,
        "next_period_id": JANUARY_PERIOD,
        "control_accounts": list(CONTROL_ACCOUNTS),
        "source_activity": _json_value(source_activity),
        "source_mayor": _json_value(source_mayor),
        "source_daily": _json_value(source_daily),
        "target_activity": _json_value(target_activity),
        "source_january_continuity": _json_value(source_continuity),
        "target_pre_january_balances": _json_value(target_opening),
        "daily_mayor_variances": _daily_mayor_variances(source_activity, source_daily),
        "source_target_activity_variances": _source_target_activity_variances(source_activity, target_activity),
        "source_january_continuity_variances": source_continuity_variances,
        "target_january_opening_variances": target_opening_variances,
        "january_continuity_accepted": not source_continuity_variances and not target_opening_variances,
    }
    return result


def capture_target_reports(settings: Settings) -> dict[str, Any]:
    if settings.target.name != "local":
        raise ValueError("G9 report capture is restricted to the local target")
    api = FineractApi(settings.target)
    cases = []
    for report_type in ("trial-balance", "balance-sheet", "income-statement"):
        modes = ("pre-closing", "post-closing") if report_type == "trial-balance" else ("post-closing",)
        for closing_mode in modes:
            for scope in ("consolidated", "1", "2"):
                response = api.request(
                    "GET",
                    f"credesalfinancialreports/{report_type}",
                    query={
                        "fromDate": DECEMBER_FROM.isoformat(),
                        "toDate": DECEMBER_TO.isoformat(),
                        "officeExternalId": None if scope == "consolidated" else scope,
                        "closingMode": closing_mode,
                        "includeZero": "true",
                    },
                )
                rows = response["rows"]
                if report_type == "income-statement":
                    accumulated_response = api.request(
                        "GET",
                        f"credesalfinancialreports/{report_type}",
                        query={
                            "fromDate": YEAR_FROM.isoformat(),
                            "toDate": DECEMBER_TO.isoformat(),
                            "officeExternalId": None if scope == "consolidated" else scope,
                            "closingMode": closing_mode,
                            "includeZero": "true",
                        },
                    )
                    accumulated_by_code = {
                        str(row["gl_code"]): row["closing_balance"] for row in accumulated_response["rows"]
                    }
                    rows = [
                        {**row, "accumulated_balance": accumulated_by_code[str(row["gl_code"])]}
                        for row in rows
                    ]
                presentation_controls = target_presentation_controls({"report_type": report_type, "rows": rows})
                cases.append({
                    "report_type": report_type,
                    "closing_mode": response["closingMode"],
                    "scope": scope,
                    "rows": rows,
                    "controls": presentation_controls,
                    "native_controls": response.get("controls", {}),
                })
    result = {
        "version": G9_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target": settings.target.name,
        "tenant": settings.target.tenant,
        "period_id": DECEMBER_PERIOD,
        "from_date": DECEMBER_FROM.isoformat(),
        "to_date": DECEMBER_TO.isoformat(),
        "cases": _json_value(cases),
    }
    result["case_content_sha256"] = _content_sha256(result["cases"])
    return result


def compare_statement_artifact(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    identity = ("report_type", "closing_mode", "scope")
    expected_cases = {tuple(case[field] for field in identity): case for case in expected["cases"]}
    actual_cases = {tuple(case[field] for field in identity): case for case in actual["cases"]}
    findings = []
    for key in sorted(set(expected_cases) | set(actual_cases)):
        if key not in expected_cases or key not in actual_cases:
            findings.append({"case": key, "reason": "CASE_MISSING"})
            continue
        expected_order = [str(row["gl_code"]) for row in expected_cases[key]["rows"]]
        actual_order = [str(row["gl_code"]) for row in actual_cases[key]["rows"]]
        if expected_order != actual_order:
            findings.append({"case": key, "reason": "ROW_ORDER_DIFFERENCE"})
        expected_rows = {str(row["gl_code"]): row for row in expected_cases[key]["rows"]}
        actual_rows = {str(row["gl_code"]): row for row in actual_cases[key]["rows"]}
        for code in sorted(set(expected_rows) | set(actual_rows)):
            if code not in expected_rows or code not in actual_rows:
                findings.append({"case": key, "gl_code": code, "reason": "ROW_MISSING"})
                continue
            wanted, received = expected_rows[code], actual_rows[code]
            fields = tuple(field for field in wanted if field != "gl_code")
            different = []
            for field in fields:
                left, right = wanted.get(field), received.get(field)
                if field in CURRENCY_FIELDS:
                    left = Decimal(str(left or 0)).quantize(Decimal("0.01"))
                    right = Decimal(str(right or 0)).quantize(Decimal("0.01"))
                if left != right:
                    different.append(field)
            if different:
                findings.append({"case": key, "gl_code": code, "reason": "ROW_DIFFERENCE", "fields": different})
        wanted_controls = expected_cases[key].get("controls", {})
        received_controls = actual_cases[key].get("controls", {})
        control_fields = []
        for field, left in wanted_controls.items():
            right = received_controls.get(field)
            if field != "dimension_scope":
                try:
                    left = Decimal(str(left or 0)).quantize(Decimal("0.01"))
                    right = Decimal(str(right or 0)).quantize(Decimal("0.01"))
                except Exception:
                    pass
            if left != right:
                control_fields.append(field)
        if control_fields:
            findings.append({"case": key, "reason": "CONTROL_DIFFERENCE", "fields": control_fields})
    return {
        "accepted": not findings,
        "version": G9_VERSION,
        "expected_case_count": len(expected_cases),
        "actual_case_count": len(actual_cases),
        "finding_count": len(findings),
        "findings": findings,
    }


def _write_artifact(output_dir: Path, name: str, value: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / name
    path.write_text(json.dumps(_json_value(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Read-only G9 accounting statement acceptance harness")
    root.add_argument("--env-file")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("readiness")
    trace = commands.add_parser("trace-controls")
    trace.add_argument("--output-dir", type=Path, default=ROOT / ".arissto-sync/g9-evidence")
    capture = commands.add_parser("capture-target")
    capture.add_argument("--output-dir", type=Path, default=ROOT / ".arissto-sync/g9-evidence")
    compare = commands.add_parser("compare")
    compare.add_argument("--expected", type=Path, required=True)
    compare.add_argument("--actual", type=Path, required=True)
    compare.add_argument("--output-dir", type=Path, default=ROOT / ".arissto-sync/g9-evidence")
    normalize = commands.add_parser("normalize-source")
    normalize.add_argument("--input-dir", type=Path, required=True)
    normalize.add_argument("--output-dir", type=Path, default=ROOT / ".arissto-sync/g9-evidence")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "normalize-source":
        result = normalize_authoritative_report_directory(args.input_dir)
        artifact = _write_artifact(args.output_dir, "authoritative-arissto-statements.json", result)
        print(json.dumps({
            "ok": result["ready"],
            "required_office_case_count": result["required_office_case_count"],
            "normalized_case_count": result["normalized_case_count"],
            "case_content_sha256": result["case_content_sha256"],
            "blockers": result["blockers"],
            "warnings": result["warnings"],
            "artifact": artifact,
        }, indent=2, default=str))
        return 0 if result["ready"] else 2
    if args.command == "compare":
        expected = json.loads(args.expected.read_text(encoding="utf-8"))
        actual = json.loads(args.actual.read_text(encoding="utf-8"))
        result = compare_statement_artifact(expected, actual)
        artifact = _write_artifact(args.output_dir, "statement-comparison.json", result)
        print(json.dumps({**result, "artifact": artifact}, indent=2, default=str))
        return 0 if result["accepted"] else 2
    settings = load_settings("local", args.env_file)
    if args.command == "readiness":
        result = inspect_g9_readiness(settings)
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0 if result["ready"] else 2
    if args.command == "trace-controls":
        result = trace_g9_controls(settings)
        artifact = _write_artifact(args.output_dir, "control-account-trace.json", result)
    else:
        result = capture_target_reports(settings)
        artifact = _write_artifact(args.output_dir, "target-statements.json", result)
    print(json.dumps({"ok": True, "artifact": artifact}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
