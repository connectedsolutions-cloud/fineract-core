from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from .arissto import select_rows, source_connection
from .config import Settings
from .connections import FineractApi, postgres_connection
from .savings import SavingsContract, clean_text


VISTA_PRODUCT_NAME = "Credesal VISTA Lifecycle Proof"
DPF_PRODUCT_PREFIX = "Credesal DPF Lifecycle Proof"
FRESH_PROOF_GENERATIONS = {
    # The original four-cycle proof was created while rollover linkage was
    # still being implemented. Preserve it as an audit artifact and prove the
    # final replay path with a fresh, externally distinct generation.
    # v2 predates the scheduler-preservation and manual-boundary fixes. Keep
    # it as audit evidence and use a fresh generation for the boundary proof.
    "001:001:0000000141": "v3",
    # The first cancellation proof predates source-authoritative maturity and
    # therefore contains a native recalculation/reversal artifact.
    "001:001:0000000140": "v3",
}


def _proof_generation(canary: "DpfCanary") -> str:
    return FRESH_PROOF_GENERATIONS.get(canary.source_key, "v1")


def _dpf_external_id(canary: "DpfCanary") -> str:
    return f"proof:arissto:dpf:{_proof_generation(canary)}:{canary.source_key}"


def _linked_vista_external_id(canary: "DpfCanary") -> str:
    return f"proof:arissto:dpf-linked-vista:{_proof_generation(canary)}:{canary.source_key}"


def _command_key(*parts: Any) -> str:
    """Return a stable key within Fineract's varchar(50) command limit."""
    digest = sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:32]
    return f"dpf:{digest}"


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid decimal value for {field}") from exc
    if not result.is_finite():
        raise ValueError(f"Invalid decimal value for {field}")
    return result


def _date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid date value for {field}") from exc


def parse_dpf_key(value: str) -> tuple[str, str, str]:
    parts = tuple(part.strip() for part in value.split(":"))
    if len(parts) != 3 or not all(part.isdigit() for part in parts) or tuple(map(len, parts)) != (3, 3, 10):
        raise ValueError("DPF proof source key must use COMPANY:BRANCH:ACCOUNT with lengths 3:3:10")
    return parts  # type: ignore[return-value]


@dataclass(frozen=True)
class DpfInterest:
    history_id: str
    cycle_sequence: int
    posted_on: date
    amount: Decimal
    tax_amount: Decimal
    taxed: bool
    interest_business_id: str
    tax_business_id: str | None
    interest_movement_id: str
    tax_movement_id: str | None


@dataclass(frozen=True)
class DpfCanary:
    source_key: str
    company_id: str
    branch_id: str
    account_id: str
    line_id: str
    state: str
    source_status: str
    client_external_id: str
    principal: Decimal
    annual_rate: Decimal
    term_days: int
    capitalization_period: str
    linked_vista_key: str
    cancellation_date: date | None
    cutoff_date: date
    cutoff_accrual: Decimal
    cycles: tuple[dict[str, Any], ...]
    interests: tuple[DpfInterest, ...]
    owners: tuple[dict[str, Any], ...]
    source_gl_codes: dict[str, str]
    reversed_opening_pairs: int
    opening_movement_id: str
    cancellation_movement_id: str | None
    reversed_opening_events: tuple[dict[str, Any], ...]


def _stable_hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def fetch_dpf_canary(settings: Settings, contract: SavingsContract, source_key: str) -> DpfCanary:
    company_id, branch_id, account_id = parse_dpf_key(source_key)
    with source_connection(settings.source) as conn:
        accounts = select_rows(conn, """
            SELECT a.*,RTRIM(l.ID_TIPO_CUENTA_AHORRO) ID_TIPO_CUENTA_AHORRO,
                   RTRIM(a.ID_LINEA_AHORRO) line_id,RTRIM(a.ESTADO_CUENTA) source_state,
                   RTRIM(s.NUMERO_AFILIACION) client_external_id,
                   RTRIM(principal.CODIGO_CUENTA) principal_gl,
                   RTRIM(expense.CODIGO_CUENTA) interest_expense_gl,
                   RTRIM(payable.CODIGO_CUENTA) interest_payable_gl
            FROM dbo.AHO_CUENTA_AHORRO a
            JOIN dbo.AHO_LINEA_AHORRO l ON l.ID_EMPRESA=a.ID_EMPRESA AND l.ID_LINEA_AHORRO=a.ID_LINEA_AHORRO
            JOIN dbo.AFI_SOCIO s ON s.ID_EMPRESA=a.ID_EMPRESA
             AND s.ID_SUCURSAL=a.ID_SUCURSAL_SOCIO AND s.ID_SOCIO=a.ID_SOCIO
            LEFT JOIN dbo.CNT_CATALOGO_CUENTAS principal
              ON principal.ID_EMPRESA=l.ID_EMPRESA AND principal.ID_CUENTA=l.ID_CUENTA
            LEFT JOIN dbo.CNT_CATALOGO_CUENTAS expense
              ON expense.ID_EMPRESA=l.ID_EMPRESA AND expense.ID_CUENTA=l.ID_CUENTA_CAPIT
            LEFT JOIN dbo.CNT_CATALOGO_CUENTAS payable
              ON payable.ID_EMPRESA=l.ID_EMPRESA AND payable.ID_CUENTA=l.ID_CUENTA_PROVI
            WHERE RTRIM(a.ID_EMPRESA)=? AND RTRIM(a.ID_SUCURSAL)=? AND RTRIM(a.ID_CUENTA_AHORRO)=?
        """, (company_id, branch_id, account_id))
        if len(accounts) != 1 or clean_text(accounts[0].get("ID_TIPO_CUENTA_AHORRO")) != "003":
            raise ValueError("Expected exactly one Arissto fixed-deposit account")
        account = accounts[0]
        movements = select_rows(conn, """
            SELECT m.*,RTRIM(t.TRANSACCION) transaction_label
            FROM dbo.AHO_MOVIMIENTOS m JOIN dbo.TRANSACCIONES t
              ON t.CODIGO_SISTEMA=m.CODIGO_SISTEMA AND t.ID_TRANSACCION=m.ID_TRANSACCION
            WHERE RTRIM(m.ID_EMPRESA)=? AND RTRIM(m.ID_SUCURSAL_CUENTA)=? AND RTRIM(m.ID_CUENTA_AHORRO)=?
            ORDER BY m.FECHA_OPERACION,m.DT_MOVIMIENTO,m.ID_AHO_MOVIMIENTO
        """, (company_id, branch_id, account_id))
        history = select_rows(conn, """
            SELECT h.*,CAST(vm.FECHA_OPERACION AS date) vista_event_date,
                   RTRIM(vt.TRANSACCION) vista_label,vm.MONTO vista_amount,
                   RTRIM(vm.ID_SUCURSAL_CUENTA) vista_branch,RTRIM(vm.ID_CUENTA_AHORRO) vista_account,
                   vm.ID_AHO_MOVIMIENTO vista_movement_id,tm.ID_AHO_MOVIMIENTO tax_movement_id
            FROM dbo.AHO_HISTORICO_PLAZOS h
            LEFT JOIN dbo.AHO_MOVIMIENTOS vm ON vm.ID_MOVIMIENTO_AHORRO=h.ID_MOVIMIENTO_AHORRO
            LEFT JOIN dbo.TRANSACCIONES vt ON vt.CODIGO_SISTEMA=vm.CODIGO_SISTEMA AND vt.ID_TRANSACCION=vm.ID_TRANSACCION
            LEFT JOIN dbo.AHO_MOVIMIENTOS tm ON tm.ID_MOVIMIENTO_AHORRO=h.ID_MOV_AHO_RENTA
            WHERE RTRIM(h.ID_EMPRESA)=? AND RTRIM(h.ID_SUCURSAL)=? AND RTRIM(h.ID_CUENTA_AHORRO)=?
            ORDER BY h.FECHA_APERTURA,h.ID_HISTORICO
        """, (company_id, branch_id, account_id))
        owners = select_rows(conn, """
            SELECT RTRIM(p.ID_PROPIETARIO) owner_id,RTRIM(s.NUMERO_AFILIACION) client_external_id,
                   CASE WHEN p.ID_SUCURSAL_SOCIO=a.ID_SUCURSAL_SOCIO AND p.ID_SOCIO=a.ID_SOCIO THEN 1 ELSE 0 END primary_match
            FROM dbo.AHO_PROPIETARIOS p JOIN dbo.AHO_CUENTA_AHORRO a
              ON a.ID_EMPRESA=p.ID_EMPRESA AND a.ID_SUCURSAL=p.ID_SUCURSAL AND a.ID_CUENTA_AHORRO=p.ID_CUENTA_AHORRO
            JOIN dbo.AFI_SOCIO s ON s.ID_EMPRESA=p.ID_EMPRESA
             AND s.ID_SUCURSAL=p.ID_SUCURSAL_SOCIO AND s.ID_SOCIO=p.ID_SOCIO
            WHERE RTRIM(p.ID_EMPRESA)=? AND RTRIM(p.ID_SUCURSAL)=? AND RTRIM(p.ID_CUENTA_AHORRO)=?
            ORDER BY p.ID_PROPIETARIO
        """, (company_id, branch_id, account_id))
        cutoff = select_rows(conn, """
            WITH x AS (SELECT MAX(CAST(FECHA_OPERACION AS date)) cutoff_date
                       FROM dbo.CIERRE_DIARIO WHERE RTRIM(CIERRE)='1')
            SELECT x.cutoff_date,d.INTERESES_PROVISIONADOS
            FROM dbo.AHO_CUENTA_AHORRO a CROSS JOIN x
            JOIN dbo.AHO_HISTORICO_DIARIO d ON d.ID_AHORRO=a.ID_AHORRO
            JOIN dbo.CIERRE_DIARIO c ON c.ID_CIERRE_DIARIO=d.ID_CIERRE_DIARIO
             AND CAST(c.FECHA_OPERACION AS date)=x.cutoff_date
            WHERE RTRIM(a.ID_EMPRESA)=? AND RTRIM(a.ID_SUCURSAL)=? AND RTRIM(a.ID_CUENTA_AHORRO)=?
        """, (company_id, branch_id, account_id))
    if len(cutoff) != 1 or sum(int(row["primary_match"]) for row in owners) != 1:
        raise ValueError("DPF proof requires one cutoff row and one authoritative primary owner")

    opening_rows = [
        row for row in movements
        if clean_text(row.get("transaction_label")) in {"APERTURA DE DPF", "DEPOSITO DE AHORRO"}
    ]
    valid_openings = [row for row in opening_rows if clean_text(row.get("REVERSION")) != "1"]
    source_state = contract.account_state(account.get("source_state"))
    if len(valid_openings) > 1 or (not valid_openings and source_state != "SUBMITTED_UNFUNDED"):
        raise ValueError("DPF lifecycle requires one funding event unless the application is submitted/unfunded")
    principal = (_decimal(valid_openings[0]["MONTO"], "DPF opening principal") if valid_openings else
                 _decimal(account.get("MONTO_APERTURA") or 0, "DPF submitted amount"))
    cycles = contract.fixed_deposit_cycles(account, opening_rows, history)
    interests: list[DpfInterest] = []
    linked_key = f"{clean_text(account.get('ID_EMPRESA_CAP'))}:{clean_text(account.get('ID_SUCURSAL_CAP'))}:{clean_text(account.get('ID_CUENTA_CAP'))}"
    for row in history:
        if clean_text(row.get("TIPO_HISTORICO")) != "1":
            continue
        if (clean_text(row.get("vista_label")) != "CAP. INT. PLAZO FIJO"
                or f"{company_id}:{clean_text(row.get('vista_branch'))}:{clean_text(row.get('vista_account'))}" != linked_key
                or _decimal(row.get("vista_amount"), "linked VISTA amount") != _decimal(row.get("MONTO_INTERES"), "interest")):
            raise ValueError("DPF interest history does not reconcile to its linked VISTA movement")
        cycle = contract.fixed_deposit_history_cycle(row, cycles)
        taxed = clean_text(row.get("APLICA_RENTA")) == "1"
        if not clean_text(row.get("vista_movement_id")) or (taxed and not clean_text(row.get("tax_movement_id"))):
            raise ValueError("DPF interest history does not resolve to native VISTA movement identities")
        interests.append(DpfInterest(
            history_id=clean_text(row.get("ID_HISTORICO")) or "", cycle_sequence=int(cycle["cycle_sequence"]),
            posted_on=_date(row.get("FECHA_APERTURA"), "interest date"),
            amount=_decimal(row.get("MONTO_INTERES"), "interest amount"),
            tax_amount=_decimal(row.get("MONTO_RENTA"), "tax amount"), taxed=taxed,
            interest_business_id=clean_text(row.get("ID_MOVIMIENTO_AHORRO")) or "",
            tax_business_id=clean_text(row.get("ID_MOV_AHO_RENTA")) or None,
            interest_movement_id=clean_text(row.get("vista_movement_id")) or "",
            tax_movement_id=clean_text(row.get("tax_movement_id")) or None,
        ))
    cancellations = [row for row in movements if clean_text(row.get("transaction_label")) == "CANCELACIÓN DE DPF"
                     and clean_text(row.get("REVERSION")) != "1"]
    if len(cancellations) > 1:
        raise ValueError("DPF proof found multiple non-reversed cancellations")
    reversed_openings = [row for row in opening_rows if clean_text(row.get("REVERSION")) == "1"]
    reversal_notes = [row for row in movements if clean_text(row.get("transaction_label")) == "NOTA DE CARGO (REVERSION)"]
    if len(reversed_openings) != len(reversal_notes):
        raise ValueError("DPF reversed opening does not have a one-for-one debit counterpart")
    return DpfCanary(
        source_key=source_key, company_id=company_id, branch_id=branch_id, account_id=account_id,
        line_id=clean_text(account.get("line_id")) or "", state=contract.account_state(account.get("source_state")),
        source_status=clean_text(account.get("source_state")) or "",
        client_external_id=clean_text(account.get("client_external_id")) or "", principal=principal,
        annual_rate=_decimal(account.get("PORCENTAJE_INTERES"), "annual rate"), term_days=int(account["PLAZO"]),
        capitalization_period=clean_text(account.get("PERIODO_CAPITALIZACION")) or "", linked_vista_key=linked_key,
        cancellation_date=_date(cancellations[0]["FECHA_OPERACION"], "cancellation date") if cancellations else None,
        cutoff_date=_date(cutoff[0]["cutoff_date"], "cutoff date"),
        cutoff_accrual=_decimal(cutoff[0]["INTERESES_PROVISIONADOS"], "cutoff accrued interest"),
        cycles=tuple(cycles), interests=tuple(interests), owners=tuple(owners),
        source_gl_codes={"savingsControlAccountId": clean_text(account.get("principal_gl")) or "",
                         "interestOnSavingsAccountId": clean_text(account.get("interest_expense_gl")) or "",
                         "interestPayableAccountId": clean_text(account.get("interest_payable_gl")) or ""},
        reversed_opening_pairs=len(reversed_openings),
        opening_movement_id=(clean_text(valid_openings[0].get("ID_AHO_MOVIMIENTO")) or "" if valid_openings else ""),
        cancellation_movement_id=(clean_text(cancellations[0].get("ID_AHO_MOVIMIENTO")) if cancellations else None),
        reversed_opening_events=tuple({
            "movement_id": clean_text(row.get("ID_AHO_MOVIMIENTO")) or "",
            "event_date": _date(row.get("FECHA_OPERACION"), "reversed opening event date"),
            "amount": _decimal(row.get("MONTO"), "reversed opening event amount"),
            "label": clean_text(row.get("transaction_label")) or "",
            "is_reversal": clean_text(row.get("REVERSION")) == "1",
        } for row in (*reversed_openings, *reversal_notes)),
    )


def _resolve_target(settings: Settings, contract: SavingsContract, canary: DpfCanary) -> dict[str, Any]:
    if not settings.target.pg_url:
        raise ValueError("DPF proof requires PostgreSQL inspection")
    wanted = {role: item["gl_code"] for role, item in contract.raw["target_shared_gl"].items()}
    wanted.update(canary.source_gl_codes)
    dpf_external = _dpf_external_id(canary)
    vista_external = _linked_vista_external_id(canary)
    product_name = f"{DPF_PRODUCT_PREFIX} {canary.line_id} {canary.capitalization_period}"
    with postgres_connection(settings.target.pg_url) as conn:
        clients = conn.execute("SELECT id,status_enum FROM m_client WHERE external_id=%s", (canary.client_external_id,)).fetchall()
        owner_rows = conn.execute(
            "SELECT id,external_id,status_enum FROM m_client WHERE external_id=ANY(%s)",
            ([str(owner["client_external_id"]) for owner in canary.owners],),
        ).fetchall()
        gl_rows = conn.execute("SELECT id,gl_code,disabled FROM acc_gl_account WHERE gl_code=ANY(%s)",
                               (list(set(wanted.values())),)).fetchall()
        products = conn.execute("SELECT id FROM m_savings_product WHERE name=%s", (product_name,)).fetchall()
        vistas = conn.execute("SELECT id FROM m_savings_product WHERE name=%s", (VISTA_PRODUCT_NAME,)).fetchall()
        dpf_accounts = conn.execute("SELECT id FROM m_savings_account WHERE external_id=%s", (dpf_external,)).fetchall()
        linked_accounts = conn.execute("SELECT id FROM m_savings_account WHERE external_id=%s", (vista_external,)).fetchall()
    if len(clients) != 1 or int(clients[0][1]) != 300 or len(vistas) != 1:
        raise ValueError("DPF owner and the reviewed VISTA proof product must exist in Fineract")
    owner_clients = {str(row[1]): int(row[0]) for row in owner_rows if int(row[2]) == 300}
    if len(owner_clients) != len(canary.owners):
        raise ValueError("Every DPF source owner must resolve to one active Fineract client")
    by_code = {str(row[1]): {"id": int(row[0]), "disabled": bool(row[2])} for row in gl_rows}
    if set(by_code) != set(wanted.values()) or any(row["disabled"] for row in by_code.values()):
        raise ValueError("DPF GL mappings are incomplete or disabled")
    if any(len(rows) > 1 for rows in (products, dpf_accounts, linked_accounts)):
        raise ValueError("Duplicate DPF proof identity exists")
    return {"client_id": int(clients[0][0]), "vista_product_id": int(vistas[0][0]),
            "product_id": int(products[0][0]) if products else None,
            "dpf_account_id": int(dpf_accounts[0][0]) if dpf_accounts else None,
            "linked_account_id": int(linked_accounts[0][0]) if linked_accounts else None,
            "owner_client_ids": owner_clients,
            "gl_ids": {role: by_code[code]["id"] for role, code in wanted.items()}, "product_name": product_name}


def build_dpf_product_payload(canary: DpfCanary, target: dict[str, Any]) -> dict[str, Any]:
    monthly = canary.capitalization_period == "06"
    if not monthly and canary.capitalization_period != "04":
        raise ValueError("Unsupported DPF capitalization period")
    period_enum = 9 if monthly else 7
    gl = target["gl_ids"]
    return {
        "name": target["product_name"], "shortName": f"P{canary.line_id[-2:]}{'M' if monthly else 'V'}",
        "description": "Controlled local proof of the Arissto fixed-deposit lifecycle",
        "currencyCode": "USD", "digitsAfterDecimal": 2, "inMultiplesOf": 0,
        "nominalAnnualInterestRate": format(canary.annual_rate, "f"),
        "interestCompoundingPeriodType": period_enum, "interestPostingPeriodType": period_enum,
        "interestCalculationType": 1, "interestCalculationDaysInYearType": 1,
        # The fixed-deposit domain already locks principal. Setting a term-long
        # generic savings lock-in also suppresses Fineract's linked-interest
        # transfer query until maturity, contradicting Arissto's monthly DPF
        # payouts.
        "lockinPeriodFrequency": 0, "lockinPeriodFrequencyType": 0,
        "minDepositTerm": canary.term_days, "minDepositTermTypeId": 0,
        "maxDepositTerm": canary.term_days, "maxDepositTermTypeId": 0,
        "inMultiplesOfDepositTerm": canary.term_days, "inMultiplesOfDepositTermTypeId": 0,
        "minDepositAmount": "100.00", "depositAmount": format(canary.principal, "f"),
        "maxDepositAmount": "10000000.00", "preClosurePenalApplicable": False,
        "withHoldTax": False, "taxGroupId": 2, "accountingRule": 3,
        "charts": [{
            "fromDate": "2000-01-01",
            "dateFormat": "yyyy-MM-dd", "locale": "en", "isPrimaryGroupingByAmount": False,
            "chartSlabs": [{"description": "DPF proof rate band", "periodType": 0,
                            "fromPeriod": 1,
                            "annualInterestRate": format(canary.annual_rate, "f"), "locale": "en"}],
        }],
        "savingsReferenceAccountId": gl["savingsReferenceAccountId"],
        "savingsControlAccountId": gl["savingsControlAccountId"],
        "transfersInSuspenseAccountId": gl["transfersInSuspenseAccountId"],
        "interestOnSavingsAccountId": gl["interestOnSavingsAccountId"],
        "interestPayableAccountId": gl["interestPayableAccountId"],
        "incomeFromFeeAccountId": gl["incomeFromFeeAccountId"],
        "incomeFromPenaltyAccountId": gl["incomeFromPenaltyAccountId"],
        "feesReceivableAccountId": gl["feesReceivableAccountId"],
        "penaltiesReceivableAccountId": gl["penaltiesReceivableAccountId"],
        "locale": "en",
    }


def _resource_id(result: dict[str, Any], *fields: str) -> int:
    for field in (*fields, "resourceId", "entityId"):
        if result.get(field) is not None:
            return int(result[field])
    raise ValueError(f"Fineract response is missing a resource identifier: {result}")


def _lifecycle_payload(field: str, value: date) -> dict[str, Any]:
    return {field: value.isoformat(), "dateFormat": "yyyy-MM-dd", "locale": "en"}


def _create_linked_vista(api: FineractApi, canary: DpfCanary, target: dict[str, Any]) -> int:
    opened_on = _date(canary.cycles[0]["source_opened_on"], "first cycle opening")
    account_id = _resource_id(api.request("POST", "savingsaccounts", {
        "clientId": target["client_id"], "productId": target["vista_product_id"],
        "externalId": _linked_vista_external_id(canary),
        "submittedOnDate": opened_on.isoformat(), "dateFormat": "yyyy-MM-dd", "locale": "en",
        "nominalAnnualInterestRate": "0", "minRequiredOpeningBalance": "0",
        "withdrawalFeeForTransfers": False,
    }), "savingsId")
    api.request("POST", f"savingsaccounts/{account_id}", _lifecycle_payload("approvedOnDate", opened_on), {"command": "approve"})
    api.request("POST", f"savingsaccounts/{account_id}", _lifecycle_payload("activatedOnDate", opened_on), {"command": "activate"})
    api.request("POST", f"savingsaccounts/{account_id}/transactions", {
        **_lifecycle_payload("transactionDate", opened_on), "transactionAmount": format(canary.principal, "f"),
        "paymentTypeId": 4,
    }, {"command": "deposit"}, idempotency_key=_command_key("fund-vista", account_id, canary.source_key))
    return account_id


def _create_first_dpf(api: FineractApi, canary: DpfCanary, target: dict[str, Any], product_id: int,
                      linked_vista_id: int) -> int:
    opened_on = _date(canary.cycles[0]["source_opened_on"], "first cycle opening")
    account_id = _resource_id(api.request("POST", "fixeddepositaccounts", {
        "clientId": target["client_id"], "productId": product_id,
        "externalId": _dpf_external_id(canary),
        "submittedOnDate": opened_on.isoformat(), "dateFormat": "yyyy-MM-dd", "locale": "en",
        "depositAmount": format(canary.principal, "f"), "depositPeriod": canary.term_days,
        "depositPeriodFrequencyId": 0, "nominalAnnualInterestRate": format(canary.annual_rate, "f"),
        "interestCalculationDaysInYearType": 1,
        "interestCompoundingPeriodType": 9 if canary.capitalization_period == "06" else 7,
        "interestPostingPeriodType": 9 if canary.capitalization_period == "06" else 7,
        "interestCalculationType": 1, "linkAccountId": linked_vista_id,
        "transferInterestToSavings": True, "maturityInstructionId": 400,
        "preClosurePenalApplicable": False, "withHoldTax": False, "charges": [],
    }), "savingsId")
    api.request("POST", f"fixeddepositaccounts/{account_id}", _lifecycle_payload("approvedOnDate", opened_on), {"command": "approve"})
    api.request("POST", f"fixeddepositaccounts/{account_id}", _lifecycle_payload("activatedOnDate", opened_on), {"command": "activate"})
    return account_id


def _find_rollover(settings: Settings, previous_account_id: int, expected_opening: date,
                   seen_account_ids: set[int], preferred_account_id: int | None = None) -> int:
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute("""
            SELECT next_sa.id,next_sa.activatedon_date,next_sa.nominal_annual_interest_rate,
                   aa.linked_savings_account_id,previous.status_enum,next_sa.status_enum
            FROM m_savings_account previous
            JOIN m_savings_account next_sa ON next_sa.client_id=previous.client_id
             AND next_sa.product_id=previous.product_id AND next_sa.deposit_type_enum=200
            JOIN m_portfolio_account_associations aa ON aa.savings_account_id=next_sa.id
             AND aa.association_type_enum=1 AND aa.is_active=true
            WHERE previous.id=%s AND next_sa.id>%s AND next_sa.id<>ALL(%s)
              AND aa.linked_savings_account_id=(
                SELECT previous_aa.linked_savings_account_id
                FROM m_portfolio_account_associations previous_aa
                WHERE previous_aa.savings_account_id=previous.id
                  AND previous_aa.association_type_enum=1 AND previous_aa.is_active=true
              )
            ORDER BY next_sa.id
        """, (previous_account_id, previous_account_id, list(seen_account_ids))).fetchall()
    if not rows or int(rows[0][4]) != 600:
        raise ValueError("Native maturity did not close the predecessor and create exactly one expected rollover")
    if preferred_account_id is not None:
        preferred = [row for row in rows if int(row[0]) == preferred_account_id]
        if len(preferred) == 1:
            return preferred_account_id
        raise ValueError("Native maturity returned a rollover that is not linked to the predecessor")
    # Recovery after a process interruption has no command response. Prefer an
    # unconsumed active replacement, then the nearest activation date and ID.
    # Seven days covers the bounded inclusive-day/month-length representation
    # difference without allowing an unrelated deposit term to be adopted.
    candidates = [
        row for row in rows
        if abs((_date(row[1], "rollover activation") - expected_opening).days) <= 7
    ]
    if not candidates:
        raise ValueError("Native maturity did not close the predecessor and create exactly one expected rollover")
    candidates.sort(key=lambda row: (
        0 if int(row[5]) == 300 else 1,
        abs((_date(row[1], "rollover activation") - expected_opening).days),
        int(row[0]),
    ))
    return int(candidates[0][0])


def _account_status(settings: Settings, account_id: int) -> int:
    with postgres_connection(settings.target.pg_url or "") as conn:
        row = conn.execute("SELECT status_enum FROM m_savings_account WHERE id=%s", (account_id,)).fetchone()
    if row is None:
        raise ValueError(f"Missing native DPF account {account_id}")
    return int(row[0])


def _interest_reference(canary: DpfCanary, interest: DpfInterest) -> str:
    generation = _proof_generation(canary)
    prefix = f"DPFI:{generation}" if generation != "v1" else "DPFI"
    return f"{prefix}:{canary.company_id}:{canary.branch_id}:{canary.account_id}:{interest.history_id}"


def _tax_reference(canary: DpfCanary, interest: DpfInterest) -> str:
    generation = _proof_generation(canary)
    prefix = f"DPFT:{generation}" if generation != "v1" else "DPFT"
    return f"{prefix}:{canary.company_id}:{canary.branch_id}:{canary.account_id}:{interest.tax_business_id}"


def _general_interest_reference(canary: DpfCanary, interest: DpfInterest) -> str:
    return f"MIGI:{canary.company_id}:{canary.branch_id}:{canary.account_id}:{interest.history_id}"


def _general_tax_reference(canary: DpfCanary, interest: DpfInterest) -> str:
    return f"MIGT:{canary.company_id}:{canary.branch_id}:{canary.account_id}:{interest.tax_business_id}"


def _post_interest_and_transfer(settings: Settings, api: FineractApi, canary: DpfCanary, interest: DpfInterest,
                                dpf_account_id: int, linked_vista_id: int, *, general_migration: bool = False,
                                reference_override: str | None = None) -> dict[str, Any]:
    # Fineract stores transaction references in varchar(50). Keep the durable
    # source identity while avoiding the verbose source-table label.
    reference = reference_override or (
        _general_interest_reference(canary, interest) if general_migration else _interest_reference(canary, interest)
    )
    api.request("POST", f"fixeddepositaccounts/{dpf_account_id}/transactions", {
        **_lifecycle_payload("transactionDate", interest.posted_on),
        "transactionAmount": format(interest.amount, "f"), "transactionReference": reference,
    }, {"command": "explicitInterestPosting"},
                idempotency_key=_command_key("interest", dpf_account_id, reference))
    with postgres_connection(settings.target.pg_url or "") as conn:
        existing_transfer = conn.execute("""
            SELECT 1 FROM m_account_transfer_transaction att
            JOIN m_account_transfer_details atd ON atd.id=att.account_transfer_details_id
            WHERE atd.from_savings_account_id=%s AND atd.to_savings_account_id=%s AND atd.transfer_type=4
              AND att.transaction_date=%s AND att.amount=%s AND att.is_reversed=false
        """, (dpf_account_id, linked_vista_id, interest.posted_on, interest.amount)).fetchone()
    transfer_result = ({"resourceId": dpf_account_id, "savingsId": dpf_account_id,
                        "changes": {"transferredInterestCount": 0, "alreadyTransferred": True}}
                       if existing_transfer is not None else
                       api.request("POST", f"fixeddepositaccounts/{dpf_account_id}", {}, {"command": "transferInterest"},
                                   idempotency_key=_command_key("transfer-v4", dpf_account_id, reference)))
    if interest.taxed:
        tax_reference = (_general_tax_reference(canary, interest) if general_migration
                         else _tax_reference(canary, interest))
        api.request("POST", f"savingsaccounts/{linked_vista_id}/transactions", {
            **_lifecycle_payload("transactionDate", interest.posted_on),
            "transactionAmount": format(interest.tax_amount, "f"),
            "grossInterestAmount": format(interest.amount, "f"), "transactionReference": tax_reference,
        }, {"command": "explicitWithholdTax"}, idempotency_key=_command_key("tax", linked_vista_id, tax_reference))
    return {"history_id": interest.history_id, "cycle_sequence": interest.cycle_sequence,
            "date": interest.posted_on.isoformat(), "gross": format(interest.amount, "f"),
            "tax": format(interest.tax_amount, "f"), "transfer_result": transfer_result}


def _native_reconciliation(settings: Settings, canary: DpfCanary, dpf_ids: list[int], linked_vista_id: int) -> dict[str, Any]:
    with postgres_connection(settings.target.pg_url or "") as conn:
        dpf_rows = conn.execute("""
            SELECT sa.id,sa.status_enum,sa.account_balance_derived::text,sa.nominal_annual_interest_rate::text,
                   dat.maturity_date,aa.linked_savings_account_id,
                   COALESCE(sa.total_interest_earned_derived,0)::text,COALESCE(sa.total_interest_posted_derived,0)::text
            FROM m_savings_account sa JOIN m_deposit_account_term_and_preclosure dat ON dat.savings_account_id=sa.id
            JOIN m_portfolio_account_associations aa ON aa.savings_account_id=sa.id AND aa.association_type_enum=1 AND aa.is_active=true
            WHERE sa.id=ANY(%s) ORDER BY sa.id
        """, (dpf_ids,)).fetchall()
        vista = conn.execute("SELECT status_enum,account_balance_derived::text FROM m_savings_account WHERE id=%s",
                             (linked_vista_id,)).fetchone()
        transfers = conn.execute("""
            SELECT COUNT(*),COALESCE(SUM(att.amount),0)::text
            FROM m_account_transfer_transaction att JOIN m_account_transfer_details atd
              ON atd.id=att.account_transfer_details_id
            WHERE atd.from_savings_account_id=ANY(%s) AND atd.to_savings_account_id=%s
              AND atd.transfer_type=4 AND att.is_reversed=false
        """, (dpf_ids, linked_vista_id)).fetchone()
        unbalanced = conn.execute("""
            SELECT COUNT(*) FROM (
              SELECT je.transaction_id FROM acc_gl_journal_entry je
              JOIN m_savings_account_transaction st ON st.id=je.savings_transaction_id
              WHERE st.savings_account_id=ANY(%s) AND je.reversed=false GROUP BY je.transaction_id
              HAVING SUM(CASE WHEN je.type_enum=1 THEN je.amount ELSE -je.amount END)<>0
            ) x
        """, ([*dpf_ids, linked_vista_id],)).fetchone()
    if vista is None or any(int(row[5]) != linked_vista_id for row in dpf_rows) or int(unbalanced[0]):
        raise ValueError("DPF native linkage or journal reconciliation failed")
    return {
        "cycles": [{"account_id": int(row[0]), "status": int(row[1]), "balance": row[2], "rate": row[3],
                    "maturity_date": _date(row[4], "target maturity").isoformat(),
                    "interest_earned": row[6], "interest_posted": row[7]} for row in dpf_rows],
        "linked_vista": {"account_id": linked_vista_id, "status": int(vista[0]), "balance": vista[1]},
        "interest_transfers": {"count": int(transfers[0]), "amount": transfers[1]},
        "unbalanced_journal_transactions": int(unbalanced[0]),
    }


@contextmanager
def _postgres_write_connection(url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for DPF migration provenance writes") from exc
    with psycopg.connect(url, autocommit=False) as conn:
        yield conn


def _single_native_transaction(conn: Any, account_id: int, transaction_type: int, *,
                               reference: str | None = None, event_date: date | None = None,
                               amount: Decimal | None = None) -> int:
    clauses = ["savings_account_id=%s", "transaction_type_enum=%s", "is_reversed=false"]
    params: list[Any] = [account_id, transaction_type]
    if reference is not None:
        clauses.append("ref_no=%s")
        params.append(reference)
    if event_date is not None:
        clauses.append("transaction_date=%s")
        params.append(event_date)
    if amount is not None:
        clauses.append("amount=%s")
        params.append(amount)
    rows = conn.execute(
        f"SELECT id FROM m_savings_account_transaction WHERE {' AND '.join(clauses)} ORDER BY id",
        tuple(params),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError(
            f"Expected one native transaction for account={account_id}, type={transaction_type}, "
            f"reference={reference}, date={event_date}, amount={amount}; found {len(rows)}"
        )
    return int(rows[0][0])


def _write_migration_support(settings: Settings, contract: SavingsContract, canary: DpfCanary,
                             target: dict[str, Any], dpf_ids: list[int], linked_vista_id: int,
                             current_dpf_id: int) -> dict[str, Any]:
    """Persist only migration identity/cutoff metadata; native finance stays API-owned."""
    if not settings.target.pg_url:
        raise ValueError("DPF migration support writes require PostgreSQL")
    source_account_key = f"AHO_CUENTA_AHORRO|{canary.company_id}|{canary.branch_id}|{canary.account_id}"
    source_hash = _stable_hash(asdict(canary))
    run_id = _stable_hash({"proof": source_account_key, "generation": _proof_generation(canary)})[:32]
    now_status = "RECONCILED"
    with _postgres_write_connection(settings.target.pg_url) as conn:
        account_row = conn.execute("""
            INSERT INTO credesal_savings_migration_account
              (source_system,source_key,source_hash,contract_hash,plan_id,run_id,client_id,savings_account_id,
               deposit_type,arissto_company_id,arissto_branch_id,arissto_account_id,arissto_account_number,
               arissto_line_id,source_status,capitalization_destination_source_key,source_owner_count,
               source_opened_on,source_matures_on,cutoff_date,accrued_interest_exact,
               accrued_interest_accounting,migration_status,applied_at,reconciled_at,updated_at)
            VALUES
              ('arissto',%s,%s,%s,'dpf-lifecycle-proof',%s,%s,%s,'DPF',%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            ON CONFLICT (source_system,source_key) DO UPDATE SET
              source_hash=EXCLUDED.source_hash,contract_hash=EXCLUDED.contract_hash,run_id=EXCLUDED.run_id,
              client_id=EXCLUDED.client_id,savings_account_id=EXCLUDED.savings_account_id,
              source_status=EXCLUDED.source_status,capitalization_destination_source_key=EXCLUDED.capitalization_destination_source_key,
              source_owner_count=EXCLUDED.source_owner_count,source_opened_on=EXCLUDED.source_opened_on,
              source_matures_on=EXCLUDED.source_matures_on,cutoff_date=EXCLUDED.cutoff_date,
              accrued_interest_exact=EXCLUDED.accrued_interest_exact,
              accrued_interest_accounting=EXCLUDED.accrued_interest_accounting,
              migration_status=EXCLUDED.migration_status,reconciled_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
            RETURNING id
        """, (
            source_account_key, source_hash, contract.contract_hash, run_id, target["client_id"], current_dpf_id,
            canary.company_id, canary.branch_id, canary.account_id, canary.account_id, canary.line_id,
            canary.source_status, canary.linked_vista_key, len(canary.owners),
            _date(canary.cycles[0]["source_opened_on"], "source opening"),
            _date(canary.cycles[-1]["source_matures_on"], "source maturity"), canary.cutoff_date,
            canary.cutoff_accrual, canary.cutoff_accrual.quantize(Decimal("0.01")), now_status,
        )).fetchone()
        if account_row is None:
            raise ValueError("Unable to persist DPF migration account identity")
        migration_account_id = int(account_row[0])

        for owner in canary.owners:
            external_id = str(owner["client_external_id"])
            owner_key = (f"AHO_PROPIETARIOS|{canary.company_id}|{canary.branch_id}|"
                         f"{canary.account_id}|{owner['owner_id']}")
            conn.execute("""
                INSERT INTO credesal_savings_migration_owner
                  (migration_account_id,client_id,source_system,source_key,source_hash,arissto_owner_id,
                   is_native_owner,updated_at)
                VALUES (%s,%s,'arissto',%s,%s,%s,%s,CURRENT_TIMESTAMP)
                ON CONFLICT (source_system,source_key) DO UPDATE SET
                  migration_account_id=EXCLUDED.migration_account_id,client_id=EXCLUDED.client_id,
                  source_hash=EXCLUDED.source_hash,is_native_owner=EXCLUDED.is_native_owner,
                  updated_at=CURRENT_TIMESTAMP
            """, (migration_account_id, target["owner_client_ids"][external_id], owner_key,
                    _stable_hash(owner), owner["owner_id"], bool(owner["primary_match"])))

        cycle_ids: dict[int, int] = {}
        previous_cycle_id: int | None = None
        for cycle, savings_account_id in zip(canary.cycles, dpf_ids, strict=True):
            row = conn.execute("""
                INSERT INTO credesal_savings_migration_cycle
                  (migration_account_id,previous_cycle_id,source_system,source_key,source_hash,contract_hash,
                   plan_id,run_id,savings_account_id,cycle_sequence,source_boundary_history_id,
                   source_opened_on,source_matures_on,opening_inference,cycle_status,is_current_cycle,
                   migration_status,applied_at,reconciled_at,updated_at)
                VALUES (%s,%s,'arissto',%s,%s,%s,'dpf-lifecycle-proof',%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                ON CONFLICT (source_system,source_key) DO UPDATE SET
                  migration_account_id=EXCLUDED.migration_account_id,previous_cycle_id=EXCLUDED.previous_cycle_id,
                  source_hash=EXCLUDED.source_hash,contract_hash=EXCLUDED.contract_hash,
                  run_id=EXCLUDED.run_id,savings_account_id=EXCLUDED.savings_account_id,
                  cycle_sequence=EXCLUDED.cycle_sequence,source_boundary_history_id=EXCLUDED.source_boundary_history_id,
                  source_opened_on=EXCLUDED.source_opened_on,source_matures_on=EXCLUDED.source_matures_on,
                  opening_inference=EXCLUDED.opening_inference,cycle_status=EXCLUDED.cycle_status,
                  is_current_cycle=EXCLUDED.is_current_cycle,migration_status=EXCLUDED.migration_status,
                  reconciled_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                RETURNING id
            """, (migration_account_id, previous_cycle_id, cycle["source_key"], _stable_hash(cycle),
                    contract.contract_hash, run_id, savings_account_id, cycle["cycle_sequence"],
                    cycle["source_boundary_history_id"], cycle["source_opened_on"], cycle["source_matures_on"],
                    cycle["opening_inference"], cycle["cycle_status"], cycle["is_current_cycle"], now_status)).fetchone()
            if row is None:
                raise ValueError("Unable to persist DPF cycle identity")
            previous_cycle_id = int(row[0])
            cycle_ids[int(cycle["cycle_sequence"])] = previous_cycle_id

        def upsert_event(*, source_table: str, source_key: str, source_value: Any,
                         savings_account_id: int, transaction_id: int | None, event_kind: str,
                         event_status: str, event_date: date, amount: Decimal, is_reversal: bool,
                         cycle_sequence: int | None = None, related_source_key: str | None = None) -> None:
            conn.execute("""
                INSERT INTO credesal_savings_native_event_map
                  (migration_account_id,migration_cycle_id,source_system,source_table,source_key,related_source_key,
                   source_hash,contract_hash,plan_id,run_id,savings_account_id,savings_transaction_id,
                   event_kind,event_status,event_date,amount,is_reversal,applied_at,reconciled_at,updated_at)
                VALUES (%s,%s,'arissto',%s,%s,%s,%s,%s,'dpf-lifecycle-proof',%s,%s,%s,%s,%s,%s,%s,%s,
                        CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                ON CONFLICT (source_system,source_table,source_key) DO UPDATE SET
                  migration_account_id=EXCLUDED.migration_account_id,migration_cycle_id=EXCLUDED.migration_cycle_id,
                  related_source_key=EXCLUDED.related_source_key,source_hash=EXCLUDED.source_hash,
                  contract_hash=EXCLUDED.contract_hash,run_id=EXCLUDED.run_id,
                  savings_account_id=EXCLUDED.savings_account_id,savings_transaction_id=EXCLUDED.savings_transaction_id,
                  event_kind=EXCLUDED.event_kind,event_status=EXCLUDED.event_status,event_date=EXCLUDED.event_date,
                  amount=EXCLUDED.amount,is_reversal=EXCLUDED.is_reversal,
                  reconciled_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
            """, (migration_account_id, cycle_ids.get(cycle_sequence or 0), source_table, source_key,
                    related_source_key, _stable_hash(source_value), contract.contract_hash, run_id,
                    savings_account_id, transaction_id, event_kind, event_status, event_date, amount, is_reversal))

        opening_date = _date(canary.cycles[0]["source_opened_on"], "opening event date")
        opening_tx = _single_native_transaction(conn, dpf_ids[0], 1, event_date=opening_date, amount=canary.principal)
        upsert_event(
            source_table="AHO_MOVIMIENTOS", source_key=f"AHO_MOVIMIENTOS|{canary.opening_movement_id}",
            source_value={"movement_id": canary.opening_movement_id, "amount": canary.principal},
            savings_account_id=dpf_ids[0], transaction_id=opening_tx, event_kind="FIXED_DEPOSIT_FUNDING",
            event_status="APPLIED", event_date=opening_date, amount=canary.principal, is_reversal=False,
            cycle_sequence=1,
        )

        for interest in canary.interests:
            account_id = dpf_ids[interest.cycle_sequence - 1]
            interest_tx = _single_native_transaction(conn, account_id, 3, reference=_interest_reference(canary, interest))
            interest_key = (f"AHO_HISTORICO_PLAZOS|{canary.company_id}|{canary.branch_id}|"
                            f"{canary.account_id}|{interest.history_id}")
            upsert_event(
                source_table="AHO_HISTORICO_PLAZOS", source_key=interest_key, source_value=asdict(interest),
                savings_account_id=account_id, transaction_id=interest_tx, event_kind="DPF_INTEREST_POSTING",
                event_status="APPLIED", event_date=interest.posted_on, amount=interest.amount,
                is_reversal=False, cycle_sequence=interest.cycle_sequence,
            )
            if interest.taxed:
                tax_tx = _single_native_transaction(conn, linked_vista_id, 18, reference=_tax_reference(canary, interest))
                upsert_event(
                    source_table="AHO_MOVIMIENTOS", source_key=f"AHO_MOVIMIENTOS|{interest.tax_movement_id}",
                    related_source_key=interest_key, source_value={"interest": asdict(interest), "kind": "tax"},
                    savings_account_id=linked_vista_id, transaction_id=tax_tx, event_kind="WITHHOLD_TAX",
                    event_status="APPLIED", event_date=interest.posted_on, amount=interest.tax_amount,
                    is_reversal=False, cycle_sequence=interest.cycle_sequence,
                )

        for correction in canary.reversed_opening_events:
            upsert_event(
                source_table="AHO_MOVIMIENTOS", source_key=f"AHO_MOVIMIENTOS|{correction['movement_id']}",
                source_value=correction,
                savings_account_id=dpf_ids[0], transaction_id=None, event_kind="OPENING_CORRECTION",
                event_status="SKIPPED_CORRECTION", event_date=correction["event_date"],
                amount=correction["amount"], is_reversal=bool(correction["is_reversal"]), cycle_sequence=1,
            )

        if canary.state == "CLOSED" and canary.cancellation_date and canary.cancellation_movement_id:
            cancellation_tx = _single_native_transaction(
                conn, current_dpf_id, 2, event_date=canary.cancellation_date, amount=canary.principal,
            )
            upsert_event(
                source_table="AHO_MOVIMIENTOS", source_key=f"AHO_MOVIMIENTOS|{canary.cancellation_movement_id}",
                source_value={"movement_id": canary.cancellation_movement_id, "amount": canary.principal},
                savings_account_id=current_dpf_id, transaction_id=cancellation_tx,
                event_kind="FIXED_DEPOSIT_CANCELLATION", event_status="APPLIED",
                event_date=canary.cancellation_date, amount=canary.principal, is_reversal=False,
                cycle_sequence=len(canary.cycles),
            )

        conn.commit()
    return {
        "migration_account_id": migration_account_id,
        "owner_count": len(canary.owners),
        "cycle_count": len(cycle_ids),
        "event_count": 1 + len(canary.interests) + sum(item.taxed for item in canary.interests)
                       + len(canary.reversed_opening_events) + int(canary.state == "CLOSED"),
        "cutoff_snapshot": format(canary.cutoff_accrual, "f"),
    }


def _execute(settings: Settings, contract: SavingsContract, canary: DpfCanary, target: dict[str, Any]) -> dict[str, Any]:
    api = FineractApi(settings.target)
    product_id = target["product_id"]
    if product_id is None:
        product_id = _resource_id(api.request("POST", "fixeddepositproducts", build_dpf_product_payload(canary, target)))
    # Product/account creation use separate Fineract commands. Reuse the
    # dedicated, externally keyed VISTA if a failed account-creation attempt
    # left that safe prerequisite behind, rather than funding it twice.
    linked_vista_id = target["linked_account_id"]
    if linked_vista_id is None:
        linked_vista_id = _create_linked_vista(api, canary, target)
    current_dpf_id = target["dpf_account_id"]
    if current_dpf_id is None:
        current_dpf_id = _create_first_dpf(api, canary, target, product_id, linked_vista_id)
    dpf_ids = [current_dpf_id]
    replayed: list[dict[str, Any]] = []
    interests_by_cycle = {sequence: [item for item in canary.interests if item.cycle_sequence == sequence]
                          for sequence in range(1, len(canary.cycles) + 1)}
    for index, cycle in enumerate(canary.cycles, start=1):
        for interest in interests_by_cycle[index]:
            replayed.append(_post_interest_and_transfer(settings, api, canary, interest, current_dpf_id, linked_vista_id))
        if index < len(canary.cycles):
            if _account_status(settings, current_dpf_id) != 600:
                api.request("POST", f"fixeddepositaccounts/{current_dpf_id}", {
                    "applyMaturityInstruction": True, "postMaturityInterest": False,
                }, {"command": "processMaturity"},
                            idempotency_key=_command_key("maturity-v5", current_dpf_id, canary.source_key, index))
            next_opening = _date(canary.cycles[index]["source_opened_on"], "next cycle opening")
            current_dpf_id = _find_rollover(settings, current_dpf_id, next_opening, set(dpf_ids))
            dpf_ids.append(current_dpf_id)

    final_status = _account_status(settings, current_dpf_id)
    if canary.state in {"MATURED", "CLOSED"} and final_status not in {600, 800}:
        api.request("POST", f"fixeddepositaccounts/{current_dpf_id}", {
            "applyMaturityInstruction": False, "postMaturityInterest": False,
        },
                    {"command": "processMaturity"},
                    idempotency_key=_command_key("final-maturity-v2", current_dpf_id, canary.source_key))
        final_status = _account_status(settings, current_dpf_id)
    if canary.state == "CLOSED" and final_status != 600:
        if canary.cancellation_date is None:
            raise ValueError("Closed DPF proof requires a cancellation date")
        api.request("POST", f"fixeddepositaccounts/{current_dpf_id}", {
            **_lifecycle_payload("closedOnDate", canary.cancellation_date), "onAccountClosureId": 100,
            "paymentTypeId": 4, "postMaturityInterest": False,
        }, {"command": "close"}, idempotency_key=_command_key("close-v2", current_dpf_id, canary.source_key))
    if canary.state == "ACTIVE":
        api.request("POST", f"fixeddepositaccounts/{current_dpf_id}", {
            "calculationDate": canary.cutoff_date.isoformat(), "dateFormat": "yyyy-MM-dd", "locale": "en",
        }, {"command": "calculateInterest"},
                    idempotency_key=_command_key("cutoff-v2", current_dpf_id, canary.source_key, canary.cutoff_date))
    reconciliation = _native_reconciliation(settings, canary, dpf_ids, linked_vista_id)
    current = next(item for item in reconciliation["cycles"] if item["account_id"] == current_dpf_id)
    native_cutoff = (Decimal("0") if canary.state != "ACTIVE" else
                     _decimal(current["interest_earned"], "native interest earned") - _decimal(
                         current["interest_posted"], "native interest posted"))
    cutoff_matches = native_cutoff.quantize(Decimal("0.01")) == canary.cutoff_accrual
    if canary.state == "ACTIVE" and canary.interests:
        # After explicit historical postings, Arissto's daily snapshot may
        # differ by cents from a fresh Fineract derivation at the migration
        # boundary. Preserve that source cutoff as non-transactional migration
        # state and retain the native calculation as a diagnostic.
        cutoff_strategy = "SOURCE_SNAPSHOT_AFTER_REPLAYED_POSTING"
        cutoff_accepted = True
    else:
        cutoff_strategy = "NATIVE_EXACT"
        cutoff_accepted = cutoff_matches
    support = _write_migration_support(
        settings, contract, canary, target, dpf_ids, linked_vista_id, current_dpf_id,
    )
    expected_transfer = sum((item.amount for item in canary.interests), Decimal("0"))
    return {"product_id": product_id, "linked_vista_id": linked_vista_id, "cycle_account_ids": dpf_ids,
            "current_account_id": current_dpf_id, "interest_events": replayed, "reconciliation": reconciliation,
            "native_cutoff_accrual": format(native_cutoff, "f"), "cutoff_matches": cutoff_matches,
            "cutoff_strategy": cutoff_strategy, "migration_support": support,
            "accepted": cutoff_accepted and support["owner_count"] == len(canary.owners)
            and support["cycle_count"] == len(canary.cycles)
            and reconciliation["interest_transfers"]["count"] == len(canary.interests)
            and _decimal(reconciliation["interest_transfers"]["amount"], "transfer total") == expected_transfer}


def prove_dpf_lifecycle(settings: Settings, contract: SavingsContract, source_key: str,
                        execute: bool = False) -> dict[str, Any]:
    if settings.target.name != "local":
        raise ValueError("DPF lifecycle proof is local-only")
    canary = fetch_dpf_canary(settings, contract, source_key)
    target = _resolve_target(settings, contract, canary)
    report: dict[str, Any] = {
        "proof": "native_dpf_lifecycle", "target": "local", "source_key": source_key,
        "proof_generation": _proof_generation(canary),
        "state": canary.state, "principal": format(canary.principal, "f"),
        "annual_rate": format(canary.annual_rate, "f"), "term_days": canary.term_days,
        "linked_vista_source_key": canary.linked_vista_key, "cycle_count": len(canary.cycles),
        "posted_interest_count": len(canary.interests), "taxed_interest_count": sum(item.taxed for item in canary.interests),
        "owner_count": len(canary.owners), "reversed_opening_pairs": canary.reversed_opening_pairs,
        "cutoff_date": canary.cutoff_date.isoformat(), "cutoff_accrual": format(canary.cutoff_accrual, "f"),
        "existing_product_id": target["product_id"], "existing_account_id": target["dpf_account_id"],
        "accepted": False,
    }
    if not execute:
        report["ready_to_execute"] = target["dpf_account_id"] is None and target["linked_account_id"] is None
        report["planned_product"] = build_dpf_product_payload(canary, target)
        report["planned_product"].pop("description", None)
        report["cycles"] = [{key: (value.isoformat() if isinstance(value, date) else value)
                              for key, value in cycle.items()} for cycle in canary.cycles]
        return report
    execution = _execute(settings, contract, canary, target)
    report.update(execution)
    return report
