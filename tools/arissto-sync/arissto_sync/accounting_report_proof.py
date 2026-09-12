from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from .accounting import AccountingContract
from .arissto import select_rows, source_connection
from .config import ROOT, Settings
from .connections import FineractApi


ORIGIN = date(2022, 11, 18)
PRESENTATION_CSV = (
    ROOT.parents[1]
    / "fineract-provider/src/main/resources/db/changelog/tenant/parts/data/0337/account_presentation.csv"
)

ACTIVITY_QUERY = """
SELECT RTRIM(d.ID_CUENTA) source_account_id,
       RTRIM(d.ID_SUCURSAL_DESTINO) source_branch_id,
       SUM(CASE WHEN CAST(p.FECHA_PARTIDA AS date)<? AND d.DEBE>0 THEN d.DEBE ELSE 0 END) opening_debit,
       SUM(CASE WHEN CAST(p.FECHA_PARTIDA AS date)<? AND d.HABER>0 THEN d.HABER ELSE 0 END) opening_credit,
       SUM(CASE WHEN CAST(p.FECHA_PARTIDA AS date) BETWEEN ? AND ? AND d.DEBE>0 THEN d.DEBE ELSE 0 END) period_debit,
       SUM(CASE WHEN CAST(p.FECHA_PARTIDA AS date) BETWEEN ? AND ? AND d.HABER>0 THEN d.HABER ELSE 0 END) period_credit,
       SUM(CASE WHEN CAST(p.FECHA_PARTIDA AS date)<=? AND d.DEBE>0 THEN d.DEBE ELSE 0 END) closing_debit,
       SUM(CASE WHEN CAST(p.FECHA_PARTIDA AS date)<=? AND d.HABER>0 THEN d.HABER ELSE 0 END) closing_credit
FROM dbo.CNT_PARTIDAS p
JOIN dbo.CNT_DETALLE_PARTIDAS d
  ON d.ID_EMPRESA=p.ID_EMPRESA AND d.ID_SUCURSAL=p.ID_SUCURSAL
 AND d.ID_PERIODO=p.ID_PERIODO AND d.ID_PARTIDA=p.ID_PARTIDA
WHERE p.ID_EMPRESA=? AND p.ESTADO_PARTIDA='3'
  AND CAST(p.FECHA_PARTIDA AS date)>=?
  AND CAST(p.FECHA_PARTIDA AS date)<=?
  AND (?=0 OR p.ID_TIPO_PARTIDA<>'003')
GROUP BY d.ID_CUENTA,d.ID_SUCURSAL_DESTINO
"""

GENERAL_LEDGER_QUERY = """
SELECT CAST(p.FECHA_PARTIDA AS date) entry_date,RTRIM(p.NUMERO_PARTIDA) ref_num,
       RTRIM(d.ID_CUENTA) source_account_id,RTRIM(d.ID_SUCURSAL_DESTINO) source_branch_id,
       d.DEBE debit,d.HABER credit
FROM dbo.CNT_PARTIDAS p
JOIN dbo.CNT_DETALLE_PARTIDAS d
  ON d.ID_EMPRESA=p.ID_EMPRESA AND d.ID_SUCURSAL=p.ID_SUCURSAL
 AND d.ID_PERIODO=p.ID_PERIODO AND d.ID_PARTIDA=p.ID_PARTIDA
WHERE p.ID_EMPRESA=? AND p.ESTADO_PARTIDA='3'
  AND CAST(p.FECHA_PARTIDA AS date) BETWEEN ? AND ?
ORDER BY p.FECHA_PARTIDA,p.ID_PARTIDA,d.ID_DETALLE_PARTIDA
"""

MEASURES = ("opening_balance", "debits", "credits", "closing_balance")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _optional_int(value: str | None) -> int | None:
    return int(value) if value not in (None, "") else None


def _load_presentation() -> list[dict[str, Any]]:
    with PRESENTATION_CSV.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for field in ("trial_balance_order", "income_statement_order", "account_order"):
            row[field] = _optional_int(row[field])
        for field in ("trial_balance_selected", "balance_sheet_selected"):
            row[field] = row[field] == "1"
    return rows


def _descendants(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    children: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row["source_parent_account_id"]:
            children[row["source_parent_account_id"]].append(row["source_account_id"])

    result: dict[str, set[str]] = {}

    def visit(account_id: str) -> set[str]:
        if account_id not in result:
            result[account_id] = {account_id}
            for child in children.get(account_id, []):
                result[account_id].update(visit(child))
        return result[account_id]

    for row in rows:
        visit(row["source_account_id"])
    return result


def _selected(row: dict[str, Any], report_type: str) -> bool:
    if report_type == "trial-balance":
        return row["trial_balance_selected"]
    if report_type == "balance-sheet":
        return row["balance_sheet_selected"]
    return (
        row["trial_balance_selected"]
        and not row["balance_sheet_selected"]
        and row["classifier_code"] in {"004", "005"}
    )


def _expected_rows(
    presentation: list[dict[str, Any]], activity: list[dict[str, Any]], report_type: str, branch_id: str | None,
) -> list[dict[str, Any]]:
    tree = _descendants(presentation)
    amounts: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for item in activity:
        if branch_id is not None and item["source_branch_id"] != branch_id:
            continue
        account = item["source_account_id"]
        for field in ("opening_debit", "opening_credit", "period_debit", "period_credit", "closing_debit", "closing_credit"):
            amounts[account][field] += _decimal(item[field])
    expected = []
    for row in presentation:
        if not _selected(row, report_type):
            continue
        total = defaultdict(Decimal)
        for account in tree[row["source_account_id"]]:
            for field, value in amounts[account].items():
                total[field] += value
        nature = row["balance_nature"]
        opening = total["opening_debit"] - total["opening_credit"] if nature == "D" else total["opening_credit"] - total["opening_debit"]
        closing = total["closing_debit"] - total["closing_credit"] if nature == "D" else total["closing_credit"] - total["closing_debit"]
        if report_type == "income-statement":
            opening = Decimal()
            closing = total["period_debit"] - total["period_credit"] if nature == "D" else total["period_credit"] - total["period_debit"]
        expected.append({
            "gl_code": row["gl_code"], "account_name": row["source_name"],
            "classifier_code": row["classifier_code"], "classifier_name": row["classifier_name"],
            "trial_balance_group": int(row["trial_balance_group"]),
            "trial_balance_order": row["trial_balance_order"],
            "income_statement_order": row["income_statement_order"], "account_order": row["account_order"],
            "balance_nature": nature, "opening_balance": opening.quantize(Decimal("0.01")),
            "debits": total["period_debit"].quantize(Decimal("0.01")),
            "credits": total["period_credit"].quantize(Decimal("0.01")),
            "closing_balance": closing.quantize(Decimal("0.01")),
        })
    return sorted(expected, key=lambda row: (
        row["trial_balance_order"] if row["trial_balance_order"] is not None else row["income_statement_order"] or 32767,
        row["account_order"] if row["account_order"] is not None else 9223372036854775807,
        row["gl_code"],
    ))


def _row_findings(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actual_by_code = {str(row.get("gl_code")): row for row in actual}
    expected_by_code = {row["gl_code"]: row for row in expected}
    findings = []
    for code in sorted(set(expected_by_code) | set(actual_by_code)):
        if code not in expected_by_code or code not in actual_by_code:
            findings.append({"gl_code": code, "reason": "ROW_SELECTOR_MISMATCH"})
            continue
        wanted, received = expected_by_code[code], actual_by_code[code]
        metadata = tuple(field for field in wanted if field not in MEASURES and wanted[field] != received.get(field))
        measures = tuple(field for field in MEASURES if wanted[field] != _decimal(received.get(field)))
        if metadata or measures:
            findings.append({"gl_code": code, "metadata": metadata, "measures": measures})
    return findings


def _hash_rows(rows: list[dict[str, Any]]) -> str:
    canonical = []
    for row in rows:
        canonical.append({key: format(value, "f") if isinstance(value, Decimal) else value for key, value in row.items()})
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prove_accounting_reports(settings: Settings, contract: AccountingContract, from_date: date, to_date: date) -> dict[str, Any]:
    if settings.target.name != "local":
        raise ValueError("Accounting report proof is restricted to the local target")
    presentation = _load_presentation()
    company = str(contract.raw["currency_precision"]["source_company"])
    agency = contract.raw["agency_dimension"]["mapping"]
    office_to_branch = {str(value["target_office_external_id"]): key for key, value in agency.items()}
    with source_connection(settings.source) as connection:
        activities = {}
        for effective_from, excluding in ((from_date, False), (from_date, True), (ORIGIN, False)):
            params = (
                effective_from, effective_from, effective_from, to_date, effective_from, to_date,
                to_date, to_date, company, ORIGIN, to_date, int(excluding),
            )
            activities[(effective_from, excluding)] = select_rows(connection, ACTIVITY_QUERY, params)
        source_gl = select_rows(connection, GENERAL_LEDGER_QUERY, (company, from_date, to_date))

    api = FineractApi(settings.target)
    scopes = ((None, None), *(sorted(office_to_branch.items())))
    cases = []
    actual_rows: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for report_type in ("trial-balance", "balance-sheet", "income-statement"):
        modes = ("pre-closing", "post-closing") if report_type == "trial-balance" else ("post-closing",)
        for closing_mode in modes:
            exclude_closing = report_type == "income-statement" or closing_mode == "pre-closing"
            for office_id, branch_id in scopes:
                effective_from = ORIGIN if report_type == "balance-sheet" else from_date
                expected = _expected_rows(
                    presentation, activities[(effective_from, exclude_closing)], report_type, branch_id
                )
                response = api.request("GET", f"credesalfinancialreports/{report_type}", query={
                    "fromDate": from_date.isoformat(), "toDate": to_date.isoformat(),
                    "officeExternalId": office_id, "closingMode": closing_mode, "includeZero": "true",
                })
                actual = response["rows"]
                key = (report_type, closing_mode, office_id or "consolidated")
                actual_rows[key] = actual
                findings = _row_findings(expected, actual)
                cases.append({
                    "report_type": report_type, "closing_mode": response["closingMode"],
                    "scope": office_id or "consolidated", "expected_rows": len(expected), "actual_rows": len(actual),
                    "expected_hash": _hash_rows(expected), "finding_count": len(findings), "findings": findings[:10],
                })

    additivity_findings = []
    for report_type in ("trial-balance", "balance-sheet", "income-statement"):
        modes = ("pre-closing", "post-closing") if report_type == "trial-balance" else ("post-closing",)
        for mode in modes:
            consolidated = {row["gl_code"]: row for row in actual_rows[(report_type, mode, "consolidated")]}
            agencies = [actual_rows[(report_type, mode, office)] for office in sorted(office_to_branch)]
            for code, row in consolidated.items():
                for measure in MEASURES:
                    summed = sum((_decimal(next(item[measure] for item in agency_rows if item["gl_code"] == code)) for agency_rows in agencies), Decimal())
                    if _decimal(row[measure]) != summed:
                        additivity_findings.append({"report_type": report_type, "closing_mode": mode, "gl_code": code, "measure": measure})

    closing_effect_rows = {}
    for scope, _branch in scopes:
        scope_name = scope or "consolidated"
        pre = {row["gl_code"]: row for row in actual_rows[("trial-balance", "pre-closing", scope_name)]}
        post = {row["gl_code"]: row for row in actual_rows[("trial-balance", "post-closing", scope_name)]}
        closing_effect_rows[scope_name] = sum(
            1 for code in pre if any(_decimal(pre[code][measure]) != _decimal(post[code][measure]) for measure in MEASURES)
        )

    code_by_id = {
        row["source_account_id"]: contract.target_code(row["gl_code"])
        for row in presentation
    }
    branch_to_office = {branch: office for office, branch in office_to_branch.items()}
    expected_gl = Counter((
        str(row["entry_date"]), row["ref_num"], code_by_id[row["source_account_id"]],
        branch_to_office[row["source_branch_id"]], _decimal(row["debit"]), _decimal(row["credit"]),
    ) for row in source_gl)
    gl_response = api.request("GET", "credesalfinancialreports/general-ledger", query={
        "fromDate": from_date.isoformat(), "toDate": to_date.isoformat(), "closingMode": "post-closing",
    })
    actual_gl = Counter((
        str(row["entry_date"]), row["ref_num"], row["gl_code"], row["office_external_id"],
        _decimal(row["debit"]), _decimal(row["credit"]),
    ) for row in gl_response["rows"])
    gl_variance_count = sum((expected_gl - actual_gl).values()) + sum((actual_gl - expected_gl).values())
    accepted = (
        not any(case["finding_count"] for case in cases)
        and not additivity_findings
        and gl_variance_count == 0
        and all(count > 0 for count in closing_effect_rows.values())
    )
    return {
        "accepted": accepted, "proof_version": "accounting-report-parity-v1", "target": "local",
        "from_date": from_date.isoformat(), "to_date": to_date.isoformat(),
        "presentation_version": contract.raw["report_presentation"]["policy_version"],
        "selector_counts": {
            "trial_balance": sum(row["trial_balance_selected"] for row in presentation),
            "balance_sheet": sum(row["balance_sheet_selected"] for row in presentation),
            "income_statement": sum(_selected(row, "income-statement") for row in presentation),
        },
        "case_count": len(cases), "cases": cases,
        "agency_additivity_finding_count": len(additivity_findings),
        "agency_additivity_findings": additivity_findings[:10],
        "annual_closing_effect_rows": closing_effect_rows,
        "general_ledger": {
            "source_line_count": sum(expected_gl.values()), "target_line_count": sum(actual_gl.values()),
            "variance_count": gl_variance_count,
        },
    }
