from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .arissto import select_rows, source_connection
from .config import Settings
from .connections import FineractApi, postgres_connection
from .savings import SavingsContract, clean_text


PROOF_PRODUCT_NAME = "Credesal VISTA Lifecycle Proof"
PROOF_PRODUCT_SHORT_NAME = "VPRF"
# v10 was accepted before the 2026-08-30 scheduler boundary, then retained
# the legacy correction damage (referenced manual interest was reversed and
# replaced). v11 proved that Fineract's reference collision check is global,
# not account-scoped, and stopped at the first repeated historical reference.
# Preserve those accounts as audit evidence. v12 demonstrated that current-period-end
# handling shifted manual boundaries back one day and created duplicate interest.
# v13 is the clean generation for the corrected date rule.
PROOF_GENERATION = "v13"
PROOF_ACCOUNT_PREFIX = f"proof:arissto:vista:{PROOF_GENERATION}:"
SUPPORTED_ROLES = {
    "DEPOSIT", "WITHDRAWAL", "SAVINGS_INTEREST_POSTING", "WITHHOLDING_TAX",
    # These credits are authored by the linked DPF lifecycle. The general
    # engine retains them in the VISTA source stream/hash but must not post a
    # second deposit when the DPF transfer is replayed natively.
    "FIXED_DEPOSIT_INTEREST_TRANSFER",
    "FIXED_DEPOSIT_WITHHOLDING_TAX",
    "CREDIT_REVERSAL", "DEBIT_REVERSAL",
}


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


def _date_payload(value: date) -> dict[str, str]:
    return {"dateFormat": "yyyy-MM-dd", "locale": "en", "transactionDate": value.isoformat()}


def _proof_reference(event: "VistaEvent") -> str:
    return f"VPRF:{PROOF_GENERATION}:{event.source_key}"


def _enum_id(value: Any, field: str) -> int:
    if not isinstance(value, dict) or value.get("id") is None:
        raise ValueError(f"Fineract response is missing {field}")
    return int(value["id"])


@dataclass(frozen=True)
class VistaEvent:
    source_key: str
    source_business_id: str
    role: str
    event_date: date
    amount: Decimal
    previous_balance: Decimal
    final_balance: Decimal
    reversed: bool
    gross_interest: Decimal | None = None


@dataclass(frozen=True)
class VistaCanary:
    source_key: str
    company_id: str
    branch_id: str
    account_id: str
    line_id: str
    client_external_id: str
    opening_date: date
    annual_rate: Decimal
    ending_balance: Decimal
    source_gl_codes: dict[str, str]
    events: tuple[VistaEvent, ...]


def parse_canary_key(value: str) -> tuple[str, str, str]:
    parts = tuple(part.strip() for part in value.split(":"))
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError("VISTA proof source key must be COMPANY:BRANCH:ACCOUNT using digits only")
    if tuple(map(len, parts)) != (3, 3, 10):
        raise ValueError("VISTA proof source key must use lengths 3:3:10")
    return parts  # type: ignore[return-value]


def fetch_vista_canary(settings: Settings, contract: SavingsContract, source_key: str) -> VistaCanary:
    company_id, branch_id, account_id = parse_canary_key(source_key)
    with source_connection(settings.source) as conn:
        accounts = select_rows(conn, """
            SELECT RTRIM(a.ID_EMPRESA) AS company_id,RTRIM(a.ID_SUCURSAL) AS branch_id,
                   RTRIM(a.ID_CUENTA_AHORRO) AS account_id,RTRIM(a.ID_LINEA_AHORRO) AS line_id,
                   RTRIM(l.ID_TIPO_CUENTA_AHORRO) AS account_type,
                   RTRIM(s.NUMERO_AFILIACION) AS client_external_id,
                   a.FECHA_APERTURA AS opening_date,a.PORCENTAJE_INTERES AS annual_rate,a.SALDO AS ending_balance,
                   RTRIM(principal.CODIGO_CUENTA) AS principal_gl,
                   RTRIM(expense.CODIGO_CUENTA) AS interest_expense_gl,
                   RTRIM(payable.CODIGO_CUENTA) AS interest_payable_gl,
                   RTRIM(tax.CODIGO_CUENTA) AS tax_gl
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
            LEFT JOIN dbo.CNT_CATALOGO_CUENTAS tax
              ON tax.ID_EMPRESA=l.ID_EMPRESA AND tax.ID_CUENTA=l.ID_CUENTA_RENTA
            WHERE RTRIM(a.ID_EMPRESA)=? AND RTRIM(a.ID_SUCURSAL)=? AND RTRIM(a.ID_CUENTA_AHORRO)=?
        """, (company_id, branch_id, account_id))
        if len(accounts) != 1:
            raise ValueError("Expected exactly one Arissto VISTA account for the proof key")
        account = accounts[0]
        if clean_text(account.get("account_type")) != "001":
            raise ValueError("Controlled VISTA proof requires source account type 001")
        movements = select_rows(conn, """
            SELECT m.ID_AHO_MOVIMIENTO,m.ID_MOVIMIENTO_AHORRO,
                   m.FECHA_OPERACION,RTRIM(t.TRANSACCION) AS transaction_label,
                   m.TIPO_MOVIMIENTO,m.MONTO,m.SALDO_ANTERIOR,m.SALDO_FINAL,m.REVERSION
            FROM dbo.AHO_MOVIMIENTOS m
            JOIN dbo.TRANSACCIONES t
              ON t.CODIGO_SISTEMA=m.CODIGO_SISTEMA AND t.ID_TRANSACCION=m.ID_TRANSACCION
            WHERE RTRIM(m.ID_EMPRESA)=? AND RTRIM(m.ID_SUCURSAL_CUENTA)=?
              AND RTRIM(m.ID_CUENTA_AHORRO)=?
            ORDER BY m.FECHA_OPERACION,m.DT_MOVIMIENTO,m.ID_AHO_MOVIMIENTO
        """, (company_id, branch_id, account_id))
        history = select_rows(conn, """
            SELECT ID_HISTORICO,TIPO_HISTORICO,MONTO_INTERES,MONTO_RENTA,APLICA_RENTA,
                   ID_MOVIMIENTO_AHORRO,ID_MOV_AHO_RENTA
            FROM dbo.AHO_HISTORICO_PLAZOS
            WHERE RTRIM(ID_EMPRESA)=? AND RTRIM(ID_SUCURSAL)=? AND RTRIM(ID_CUENTA_AHORRO)=?
              AND RTRIM(TIPO_HISTORICO)='1'
        """, (company_id, branch_id, account_id))

    gross_by_interest = {str(row["ID_MOVIMIENTO_AHORRO"]).strip(): _decimal(row["MONTO_INTERES"], "MONTO_INTERES")
                         for row in history}
    gross_by_tax = {str(row["ID_MOV_AHO_RENTA"]).strip(): _decimal(row["MONTO_INTERES"], "MONTO_INTERES")
                    for row in history if clean_text(row.get("APLICA_RENTA")) == "1"}
    events: list[VistaEvent] = []
    for row in movements:
        normalized = contract.movement_event(row, row["transaction_label"])
        role = str(normalized["role"])
        if role not in SUPPORTED_ROLES:
            raise ValueError(f"VISTA canary is not isolated; unsupported event role: {role}")
        business_id = str(row["ID_MOVIMIENTO_AHORRO"]).strip()
        gross = gross_by_tax.get(business_id) if role == "WITHHOLDING_TAX" else gross_by_interest.get(business_id)
        if role == "WITHHOLDING_TAX" and gross is None:
            # DPF ISR is recorded on the destination VISTA movement but its
            # authoritative gross/tax decision lives on the DPF history row.
            # The DPF engine posts it once to this linked account.
            role = "FIXED_DEPOSIT_WITHHOLDING_TAX"
        if role == "SAVINGS_INTEREST_POSTING" and gross is None:
            raise ValueError(f"VISTA {role} event does not resolve to type-1 history")
        events.append(VistaEvent(
            source_key=str(normalized["source_key"]), source_business_id=business_id, role=role,
            event_date=_date(normalized["event_date"], "event_date"), amount=_decimal(normalized["amount"], "amount"),
            previous_balance=_decimal(normalized["previous_balance"], "previous_balance"),
            final_balance=_decimal(normalized["final_balance"], "final_balance"),
            reversed=bool(normalized["is_reversal"]), gross_interest=gross,
        ))
    reversal_roles = {"CREDIT_REVERSAL", "DEBIT_REVERSAL"}
    for index, event in enumerate(events):
        if not event.reversed:
            continue
        if index + 1 >= len(events):
            raise ValueError("VISTA reversed movement is missing its balancing correction")
        correction = events[index + 1]
        expected_role = "CREDIT_REVERSAL" if event.role == "WITHDRAWAL" else "DEBIT_REVERSAL"
        if (correction.role != expected_role or correction.event_date != event.event_date
                or correction.amount != event.amount or correction.final_balance != event.previous_balance):
            raise ValueError("VISTA reversed movement pair is not deterministic")
    for event in events:
        if event.role in reversal_roles and not any(
            prior.reversed and prior.event_date == event.event_date and prior.amount == event.amount
            for prior in events
        ):
            raise ValueError("VISTA correction note is missing its reversed movement")
    if not events or events[-1].final_balance != _decimal(account["ending_balance"], "ending_balance"):
        raise ValueError("VISTA canary movement stream does not reconcile to its account balance")
    return VistaCanary(
        source_key=source_key, company_id=company_id, branch_id=branch_id, account_id=account_id,
        line_id=str(account["line_id"]), client_external_id=str(account["client_external_id"]),
        opening_date=_date(account["opening_date"], "opening_date"),
        annual_rate=_decimal(account["annual_rate"], "annual_rate"),
        ending_balance=_decimal(account["ending_balance"], "ending_balance"),
        source_gl_codes={
            "savingsControlAccountId": str(account["principal_gl"]),
            "interestOnSavingsAccountId": str(account["interest_expense_gl"]),
            "interestPayableAccountId": str(account["interest_payable_gl"]),
            "taxComponentCreditAccountId": str(account["tax_gl"]),
        }, events=tuple(events),
    )


def _resolve_target(settings: Settings, contract: SavingsContract, canary: VistaCanary) -> dict[str, Any]:
    if not settings.target.pg_url:
        raise ValueError("VISTA proof requires target PostgreSQL inspection")
    wanted = {role: item["gl_code"] for role, item in contract.raw["target_shared_gl"].items()}
    wanted.update({role: code for role, code in canary.source_gl_codes.items() if role != "taxComponentCreditAccountId"})
    with postgres_connection(settings.target.pg_url) as conn:
        clients = conn.execute(
            "SELECT id,status_enum FROM m_client WHERE external_id=%s", (canary.client_external_id,)
        ).fetchall()
        if len(clients) != 1 or int(clients[0][1]) != 300:
            raise ValueError("VISTA canary owner must resolve to one active Fineract client")
        rows = conn.execute(
            "SELECT id,gl_code,classification_enum,disabled FROM acc_gl_account WHERE gl_code=ANY(%s)",
            (list(set(wanted.values())),),
        ).fetchall()
        by_code = {str(row[1]): {"id": int(row[0]), "classification": int(row[2]), "disabled": bool(row[3])}
                   for row in rows}
        if set(by_code) != set(wanted.values()) or any(row["disabled"] for row in by_code.values()):
            raise ValueError("VISTA proof GL mappings are incomplete or disabled")
        products = conn.execute(
            "SELECT id,name,short_name FROM m_savings_product WHERE name=%s OR short_name=%s",
            (PROOF_PRODUCT_NAME, PROOF_PRODUCT_SHORT_NAME),
        ).fetchall()
        accounts = conn.execute(
            "SELECT id,status_enum FROM m_savings_account WHERE external_id=%s",
            (f"{PROOF_ACCOUNT_PREFIX}{canary.source_key}",),
        ).fetchall()
    if len(products) > 1 or len(accounts) > 1:
        raise ValueError("Duplicate VISTA proof identity exists in Fineract")
    return {
        "client_id": int(clients[0][0]),
        "gl_ids": {role: by_code[code]["id"] for role, code in wanted.items()},
        "existing_product_id": int(products[0][0]) if products else None,
        "existing_account_id": int(accounts[0][0]) if accounts else None,
        "existing_account_status": int(accounts[0][1]) if accounts else None,
    }


def build_product_payload(canary: VistaCanary, target: dict[str, Any], tax_group_id: int) -> dict[str, Any]:
    gl = target["gl_ids"]
    return {
        "name": PROOF_PRODUCT_NAME, "shortName": PROOF_PRODUCT_SHORT_NAME,
        "description": "Controlled local proof of the Arissto VISTA lifecycle",
        "currencyCode": "USD", "digitsAfterDecimal": 2, "inMultiplesOf": 0,
        "nominalAnnualInterestRate": format(canary.annual_rate, "f"),
        "interestCompoundingPeriodType": 5, "interestPostingPeriodType": 5,
        "interestCalculationType": 1, "interestCalculationDaysInYearType": 1,
        "minRequiredOpeningBalance": "50.00", "minBalanceForInterestCalculation": "50.00",
        "lockinPeriodFrequency": 0, "lockinPeriodFrequencyType": 0,
        "withdrawalFeeForTransfers": False, "allowOverdraft": False,
        "withHoldTax": False, "taxGroupId": tax_group_id, "accountingRule": 3,
        "savingsReferenceAccountId": gl["savingsReferenceAccountId"],
        "overdraftPortfolioControlId": gl["savingsReferenceAccountId"],
        "savingsControlAccountId": gl["savingsControlAccountId"],
        "transfersInSuspenseAccountId": gl["transfersInSuspenseAccountId"],
        "interestOnSavingsAccountId": gl["interestOnSavingsAccountId"],
        "writeOffAccountId": gl["interestOnSavingsAccountId"],
        "interestPayableAccountId": gl["interestPayableAccountId"],
        "incomeFromFeeAccountId": gl["incomeFromFeeAccountId"],
        "incomeFromPenaltyAccountId": gl["incomeFromPenaltyAccountId"],
        "incomeFromInterestId": gl["incomeFromFeeAccountId"],
        "feesReceivableAccountId": gl["feesReceivableAccountId"],
        "penaltiesReceivableAccountId": gl["penaltiesReceivableAccountId"],
        "locale": "en", "paymentChannelToFundSourceMappings": [],
        "feeToIncomeAccountMappings": [], "penaltyToIncomeAccountMappings": [], "charges": [],
    }


def _verify_native_configuration(product: dict[str, Any], account: dict[str, Any] | None = None) -> None:
    expected = {
        "interestCalculationDaysInYearType": 1, "interestCompoundingPeriodType": 5,
        "interestPostingPeriodType": 5, "interestCalculationType": 1,
    }
    for field, value in expected.items():
        if _enum_id(product.get(field), f"product.{field}") != value:
            raise ValueError(f"VISTA proof product has incorrect {field}")
    if product.get("withHoldTax") is not False or int((product.get("taxGroup") or {}).get("id") or 0) != 2:
        raise ValueError("VISTA proof product must link ISR group 2 with automatic withholding disabled")
    if account:
        for field, value in expected.items():
            if _enum_id(account.get(field), f"account.{field}") != value:
                raise ValueError(f"VISTA proof account has incorrect {field}")
        if account.get("withHoldTax") is not False or int((account.get("taxGroup") or {}).get("id") or 0) != 2:
            raise ValueError("VISTA proof account must link ISR group 2 with automatic withholding disabled")


def _resource_id(result: dict[str, Any], field: str) -> int:
    # Transaction commands return the account in resourceId and the native
    # transaction in subResourceId; creation commands usually do the reverse.
    value = result.get(field) or result.get("resourceId")
    if value is None:
        raise ValueError(f"Fineract command did not return {field}")
    return int(value)


def _transaction_amount(transaction: dict[str, Any]) -> Decimal:
    return _decimal(transaction.get("amount"), "target transaction amount")


def _account_balance(account: dict[str, Any]) -> Decimal:
    summary = account.get("summary") or {}
    return _decimal(summary.get("accountBalance"), "target account balance")


def _native_transaction_id(settings: Settings, account_id: int, event: VistaEvent) -> int:
    target_type = {"DEPOSIT": 1, "WITHDRAWAL": 2, "SAVINGS_INTEREST_POSTING": 3, "WITHHOLDING_TAX": 18}[event.role]
    with postgres_connection(settings.target.pg_url) as conn:
        rows = conn.execute("""
            SELECT id FROM m_savings_account_transaction
            WHERE savings_account_id=%s AND transaction_type_enum=%s AND transaction_date=%s
              AND amount=%s AND is_reversed=false ORDER BY id
        """, (account_id, target_type, event.event_date, event.amount)).fetchall()
    if len(rows) != 1:
        raise ValueError(f"Expected one native transaction for {event.source_key}; found {len(rows)}")
    return int(rows[0][0])


def _replay(settings: Settings, api: FineractApi, canary: VistaCanary, account_id: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for event in canary.events:
        payload = {**_date_payload(event.event_date), "transactionAmount": format(event.amount, "f")}
        command = ""
        if event.role == "DEPOSIT":
            command = "deposit"
            payload["paymentTypeId"] = 4
        elif event.role == "WITHDRAWAL":
            command = "withdrawal"
            payload["paymentTypeId"] = 4
        elif event.role == "SAVINGS_INTEREST_POSTING":
            command = "explicitInterestPosting"
            # Historical postings are source ledger facts. Their cent amount
            # can differ from a fresh calculation because Arissto retained
            # posting-time adjustments that are not present in the movement
            # stream. Keep the native type-3 transaction and accounting while
            # preserving the authoritative source amount and identity.
            payload.update({"transactionReference": _proof_reference(event)})
        elif event.role == "WITHHOLDING_TAX":
            command = "explicitWithholdTax"
            payload.update({
                "grossInterestAmount": format(event.gross_interest or Decimal("0"), "f"),
                "transactionReference": _proof_reference(event),
            })
        result = api.request(
            "POST", f"savingsaccounts/{account_id}/transactions", payload, {"command": command},
            # Fineract idempotency keys are not scoped to an account. Include
            # the native account identity so the same source event can never
            # recover a response created for a different account.
            idempotency_key=f"vista-proof:{account_id}:{event.source_key}",
        )
        transaction_id = _native_transaction_id(settings, account_id, event)
        actual_amount = event.amount
        actual_balance = _account_balance(api.request("GET", f"savingsaccounts/{account_id}"))
        if actual_amount != event.amount:
            raise ValueError(f"Native {event.role} amount differs for {event.source_key}: {actual_amount} != {event.amount}")
        if actual_balance != event.final_balance:
            raise ValueError(f"Native running balance differs for {event.source_key}: {actual_balance} != {event.final_balance}")
        results.append({
            "source_key": event.source_key, "role": event.role, "date": event.event_date.isoformat(),
            "amount": format(event.amount, "f"), "transaction_id": transaction_id,
            "balance": format(actual_balance, "f"),
        })
    return results


def _journal_summary(settings: Settings, account_id: int) -> dict[str, Any]:
    with postgres_connection(settings.target.pg_url) as conn:
        rows = conn.execute("""
            SELECT ga.gl_code,je.type_enum,COUNT(*),COALESCE(SUM(je.amount),0)::text
            FROM acc_gl_journal_entry je
            JOIN acc_gl_account ga ON ga.id=je.account_id
            JOIN m_savings_account_transaction st ON st.id=je.savings_transaction_id
            WHERE st.savings_account_id=%s AND je.reversed=false
            GROUP BY ga.gl_code,je.type_enum ORDER BY ga.gl_code,je.type_enum
        """, (account_id,)).fetchall()
        unbalanced = int(conn.execute("""
            SELECT COUNT(*) FROM (
              SELECT je.transaction_id FROM acc_gl_journal_entry je
              JOIN m_savings_account_transaction st ON st.id=je.savings_transaction_id
              WHERE st.savings_account_id=%s AND je.reversed=false GROUP BY je.transaction_id
              HAVING SUM(CASE WHEN je.type_enum=1 THEN je.amount ELSE -je.amount END)<>0
            ) x
        """, (account_id,)).fetchone()[0])
    if unbalanced:
        raise ValueError("VISTA proof produced unbalanced native journals")
    return {"unbalanced_transactions": unbalanced,
            "by_gl_and_entry_type": [{"gl_code": r[0], "entry_type": int(r[1]), "count": int(r[2]), "amount": r[3]}
                                     for r in rows]}


def _reconcile_transactions(settings: Settings, canary: VistaCanary, account_id: int) -> list[dict[str, Any]]:
    role_by_type = {1: "DEPOSIT", 2: "WITHDRAWAL", 3: "SAVINGS_INTEREST_POSTING", 18: "WITHHOLDING_TAX"}
    with postgres_connection(settings.target.pg_url) as conn:
        rows = conn.execute("""
            SELECT transaction_type_enum,transaction_date,amount,running_balance_derived,ref_no,id
            FROM m_savings_account_transaction
            WHERE savings_account_id=%s AND is_reversed=false ORDER BY transaction_date,id
        """, (account_id,)).fetchall()
    if len(rows) != len(canary.events):
        raise ValueError(f"Native VISTA event count differs: {len(rows)} != {len(canary.events)}")
    reconciled: list[dict[str, Any]] = []
    for event, row in zip(canary.events, rows):
        role = role_by_type.get(int(row[0]))
        actual_date = _date(row[1], "target transaction date")
        actual_amount = _decimal(row[2], "target transaction amount")
        actual_balance = _decimal(row[3], "target running balance")
        actual_reference = clean_text(row[4])
        if (role, actual_date, actual_amount, actual_balance) != (
            event.role, event.event_date, event.amount, event.final_balance,
        ):
            raise ValueError(f"Native transaction differs for {event.source_key}")
        if (event.role in {"SAVINGS_INTEREST_POSTING", "WITHHOLDING_TAX"}
                and actual_reference != _proof_reference(event)):
            raise ValueError(f"Native source reference differs for {event.source_key}")
        reconciled.append({
            "source_key": event.source_key, "role": role, "date": actual_date.isoformat(),
            "amount": format(actual_amount, "f"), "transaction_id": int(row[5]),
            "balance": format(actual_balance, "f"),
        })
    return reconciled


def prove_vista_lifecycle(
    settings: Settings, contract: SavingsContract, source_key: str, execute: bool = False,
    reconcile_existing: bool = False,
) -> dict[str, Any]:
    if settings.target.name != "local":
        raise ValueError("VISTA lifecycle proof is local-only")
    canary = fetch_vista_canary(settings, contract, source_key)
    target = _resolve_target(settings, contract, canary)
    report: dict[str, Any] = {
        "proof": "native_vista_lifecycle", "target": "local", "execute": execute,
        "reconcile_existing": reconcile_existing,
        "source_key": source_key, "client_id": target["client_id"], "line_id": canary.line_id,
        "opening_date": canary.opening_date.isoformat(), "annual_rate": format(canary.annual_rate, "f"),
        "event_counts": {role: sum(event.role == role for event in canary.events) for role in sorted(SUPPORTED_ROLES)},
        "source_ending_balance": format(canary.ending_balance, "f"),
        "existing_product_id": target["existing_product_id"], "existing_account_id": target["existing_account_id"],
        "accepted": False,
    }
    if reconcile_existing:
        account_id = target["existing_account_id"]
        product_id = target["existing_product_id"]
        if account_id is None or product_id is None:
            raise ValueError("VISTA proof account and product must exist before reconciliation")
        api = FineractApi(settings.target)
        product = api.request("GET", f"savingsproducts/{product_id}")
        account = api.request("GET", f"savingsaccounts/{account_id}")
        _verify_native_configuration(product, account)
        transactions = _reconcile_transactions(settings, canary, account_id)
        final_balance = _account_balance(account)
        journals = _journal_summary(settings, account_id)
        report.update({
            "product_id": product_id, "account_id": account_id, "transactions": transactions,
            "target_ending_balance": format(final_balance, "f"), "journals": journals,
            "accepted": final_balance == canary.ending_balance and len(transactions) == len(canary.events),
        })
        return report
    if not execute:
        report["ready_to_execute"] = target["existing_account_id"] is None
        report["planned_product"] = build_product_payload(canary, target, 2)
        report["planned_product"].pop("description", None)
        return report
    if target["existing_account_id"] is not None:
        raise ValueError("VISTA proof account already exists; refusing to duplicate or partially replay it")
    api = FineractApi(settings.target)
    product_id = target["existing_product_id"]
    if product_id is None:
        product_id = _resource_id(api.request("POST", "savingsproducts", build_product_payload(canary, target, 2)), "resourceId")
    product = api.request("GET", f"savingsproducts/{product_id}")
    _verify_native_configuration(product)
    account_external_id = f"{PROOF_ACCOUNT_PREFIX}{canary.source_key}"
    account_id = _resource_id(api.request("POST", "savingsaccounts", {
        "clientId": target["client_id"], "productId": product_id, "externalId": account_external_id,
        "submittedOnDate": canary.opening_date.isoformat(), "dateFormat": "yyyy-MM-dd", "locale": "en",
        "nominalAnnualInterestRate": format(canary.annual_rate, "f"), "withdrawalFeeForTransfers": False,
        # The product's 50.00 minimum is the rule for new business. Historical
        # migration accounts must not synthesize an activation deposit: their
        # first Arissto deposit is replayed as the sole opening balance event.
        "minRequiredOpeningBalance": "0",
    }), "savingsId")
    lifecycle = {"dateFormat": "yyyy-MM-dd", "locale": "en"}
    api.request("POST", f"savingsaccounts/{account_id}", {**lifecycle, "approvedOnDate": canary.opening_date.isoformat()},
                {"command": "approve"})
    api.request("POST", f"savingsaccounts/{account_id}", {**lifecycle, "activatedOnDate": canary.opening_date.isoformat()},
                {"command": "activate"})
    account = api.request("GET", f"savingsaccounts/{account_id}")
    _verify_native_configuration(product, account)
    transactions = _replay(settings, api, canary, account_id)
    final_account = api.request("GET", f"savingsaccounts/{account_id}")
    final_balance = _account_balance(final_account)
    journals = _journal_summary(settings, account_id)
    report.update({
        "product_id": product_id, "account_id": account_id, "transactions": transactions,
        "target_ending_balance": format(final_balance, "f"), "journals": journals,
        "accepted": final_balance == canary.ending_balance and len(transactions) == len(canary.events),
    })
    return report
