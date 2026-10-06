"""Reviewed local treasury bank-account prerequisite for composed sync workflows."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .arissto import select_rows, source_connection
from .config import Settings
from .connections import FineractApi


# Operational account 2 is deliberately excluded: its institution conflicts
# with the COA label and its source number is a placeholder.
REVIEWED_BANKS = {
    1: ("111004020101", "BANCO ATLANTIDA"),
    3: ("111004020102", "BANCO CUSCATLAN"),
    4: ("111004010101", "AMC DE R.L. DE C.V."),
}


def _enum_id(value: Any) -> int | None:
    try:
        return int(value.get("id") if isinstance(value, dict) else value)
    except (TypeError, ValueError):
        return None


def ensure_treasury_bank_accounts(
    settings: Settings,
    api: FineractApi,
    prerequisites: dict[str, Any] | None,
    selected_services: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Verify reviewed banks and create missing entries only in the local sandbox.

    Source numbers stay in memory and in the target API; the returned workflow
    evidence contains only operational IDs, GL codes, and action labels.
    """
    configured = (prerequisites or {}).get("treasury_bank_accounts")
    if not configured or not set(selected_services).intersection(configured["required_by_services"]):
        return {"performed": False, "actions": []}
    target = settings.target
    if (
        target.name != "local" or target.tenant != "sandbox"
        or urlparse(target.api_url).hostname not in {"localhost", "127.0.0.1"}
        or urlparse(target.pg_url or "").path.lstrip("/") != "fineract_sandbox"
    ):
        raise RuntimeError("Treasury bank bootstrap requires the local sandbox tenant and database")
    if set(configured["source_account_ids"]) != set(REVIEWED_BANKS):
        raise RuntimeError("Treasury bank prerequisite differs from the reviewed source account set")

    sql = """SELECT CAST(a.ID_CUENTA_BANCARIA AS int) AS source_id,
                    RTRIM(a.ID_SUCURSAL) AS branch,
                    RTRIM(a.ESTADO_CUENTA) AS status,
                    RTRIM(a.NUMERO_CUENTA) AS account_number,
                    RTRIM(b.NOMBRE_BANCO) AS bank_name,
                    RTRIM(c.CODIGO_CUENTA) AS gl_code
             FROM dbo.BNC_CUENTA_BANCARIA AS a
             JOIN dbo.BNC_BANCO AS b ON b.ID_BANCO = a.ID_BANCO
             JOIN dbo.CNT_CATALOGO_CUENTAS AS c
               ON c.ID_EMPRESA = a.ID_EMPRESA AND c.ID_CUENTA = a.ID_CUENTA
             WHERE a.ID_CUENTA_BANCARIA IN (1, 3, 4)"""
    with source_connection(settings.source) as conn:
        source_rows = select_rows(conn, sql)
    if len(source_rows) != len(REVIEWED_BANKS):
        raise RuntimeError("The reviewed Arissto bank-account set is incomplete or duplicated")
    source: dict[int, dict[str, Any]] = {}
    for row in source_rows:
        source_id = int(row["source_id"])
        expected = REVIEWED_BANKS.get(source_id)
        number = str(row.get("account_number") or "").strip()
        if (
            expected is None or source_id in source
            or str(row.get("branch") or "").strip() != "001"
            or str(row.get("status") or "").strip() != "1"
            or str(row.get("gl_code") or "").strip() != expected[0]
            or str(row.get("bank_name") or "").strip() != expected[1]
            or not re.search(r"\d", number) or re.search(r"[Xx*]", number)
        ):
            raise RuntimeError(f"Arissto bank account {source_id} differs from the reviewed master")
        source[source_id] = {"number": number, "gl_code": expected[0], "name": expected[1]}
    if set(source) != set(REVIEWED_BANKS):
        raise RuntimeError("The reviewed Arissto bank-account set is incomplete")

    gl_accounts = api.request("GET", "glaccounts")
    target_banks = api.request("GET", "treasury/bankaccounts")
    prepared = []
    for source_id in sorted(REVIEWED_BANKS):
        expected = source[source_id]
        code = expected["gl_code"]
        gl_matches = [item for item in gl_accounts if str(item.get("glCode")) == code]
        if len(gl_matches) != 1:
            raise RuntimeError(f"Treasury bank {source_id} requires exactly one GL account {code}")
        gl = gl_matches[0]
        if gl.get("disabled") or _enum_id(gl.get("type")) != 1 or _enum_id(gl.get("usage")) != 1:
            raise RuntimeError(f"Treasury bank {source_id} requires an enabled asset detail GL account")
        matches = [item for item in target_banks if int(item.get("glAccountId") or 0) == int(gl["id"])]
        if len(matches) > 1:
            raise RuntimeError(f"Treasury bank {source_id} has duplicate target GL mappings")
        if matches:
            _verify_bank(matches[0], source_id, expected, int(gl["id"]))
        elif any(item.get("externalAccountReference") == expected["number"] for item in target_banks):
            raise RuntimeError(f"Treasury bank {source_id} account number belongs to another target bank")
        prepared.append((source_id, expected, int(gl["id"]), bool(matches)))

    actions = []
    for source_id, expected, gl_id, exists in prepared:
        action = "unchanged"
        if not exists:
            api.request("POST", "treasury/bankaccounts", {
                "name": expected["name"], "glAccountId": gl_id,
                "currencyCode": "USD", "officeId": 1,
                "externalAccountReference": expected["number"],
                "alias": "Cuenta corriente",
            })
            action = "created"
        refreshed = api.request("GET", "treasury/bankaccounts")
        matches = [item for item in refreshed if int(item.get("glAccountId") or 0) == gl_id]
        if len(matches) != 1:
            raise RuntimeError(f"Treasury bank {source_id} failed post-bootstrap verification")
        _verify_bank(matches[0], source_id, expected, gl_id)
        actions.append({"source_account_id": source_id, "gl_code": expected["gl_code"], "action": action})
    return {"performed": True, "actions": actions}


def _verify_bank(bank: dict[str, Any], source_id: int, expected: dict[str, str], gl_id: int) -> None:
    if (
        bank.get("name") != expected["name"]
        or int(bank.get("glAccountId") or 0) != gl_id
        or bank.get("glCode") != expected["gl_code"]
        or bank.get("externalAccountReference") != expected["number"]
        or bank.get("currencyCode") != "USD"
        or int(bank.get("officeId") or 0) != 1
        or bank.get("active") is not True
    ):
        raise RuntimeError(f"Treasury bank {source_id} differs from the reviewed target mapping")
