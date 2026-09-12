from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
from typing import Any, Iterable

from .arissto import select_rows, source_connection
from .config import Settings
from .fixed_deposit_lifecycle_proof import DpfCanary, DpfInterest, _date as dpf_date, _decimal as dpf_decimal
from .savings import SavingsContract, clean_text
from .savings_lifecycle_proof import (
    SUPPORTED_ROLES,
    VistaCanary,
    VistaEvent,
    _date as vista_date,
    _decimal as vista_decimal,
)


SOURCE_BATCH_SIZE = 500


def _chunks(values: list[tuple[str, str, str]], size: int = SOURCE_BATCH_SIZE) -> Iterable[list[tuple[str, str, str]]]:
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def _requested_cte(keys: list[tuple[str, str, str]]) -> tuple[str, tuple[str, ...]]:
    values = ",".join("(?,?,?)" for _ in keys)
    return (
        f"WITH requested(company_id,branch_id,account_id) AS "
        f"(SELECT * FROM (VALUES {values}) v(company_id,branch_id,account_id))",
        tuple(part for key in keys for part in key),
    )


def _key(row: dict[str, Any], company: str, branch: str, account: str) -> tuple[str, str, str]:
    return (
        clean_text(row.get(company)) or "",
        clean_text(row.get(branch)) or "",
        clean_text(row.get(account)) or "",
    )


def _group(
    rows: list[dict[str, Any]], company: str, branch: str, account: str,
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_key(row, company, branch, account)].append(row)
    return grouped


def build_vista_canary(
    contract: SavingsContract,
    source_key: str,
    account: dict[str, Any],
    movements: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> VistaCanary:
    company_id, branch_id, account_id = source_key.split(":")
    if clean_text(account.get("ID_TIPO_CUENTA_AHORRO")) != "001":
        raise ValueError("Controlled VISTA proof requires source account type 001")
    type_one_history = [row for row in history if clean_text(row.get("TIPO_HISTORICO")) == "1"]
    gross_by_interest = {
        clean_text(row.get("ID_MOVIMIENTO_AHORRO")) or "": vista_decimal(row["MONTO_INTERES"], "MONTO_INTERES")
        for row in type_one_history
    }
    gross_by_tax = {
        clean_text(row.get("ID_MOV_AHO_RENTA")) or "": vista_decimal(row["MONTO_INTERES"], "MONTO_INTERES")
        for row in type_one_history if clean_text(row.get("APLICA_RENTA")) == "1"
    }
    events: list[VistaEvent] = []
    for row in movements:
        normalized = contract.movement_event(row, row["transaction_label"])
        role = str(normalized["role"])
        if role not in SUPPORTED_ROLES:
            raise ValueError(f"VISTA canary is not isolated; unsupported event role: {role}")
        business_id = clean_text(row.get("ID_MOVIMIENTO_AHORRO")) or ""
        gross = gross_by_tax.get(business_id) if role == "WITHHOLDING_TAX" else gross_by_interest.get(business_id)
        if role == "WITHHOLDING_TAX" and gross is None:
            role = "FIXED_DEPOSIT_WITHHOLDING_TAX"
        if role == "SAVINGS_INTEREST_POSTING" and gross is None:
            raise ValueError(f"VISTA {role} event does not resolve to type-1 history")
        events.append(VistaEvent(
            source_key=str(normalized["source_key"]), source_business_id=business_id, role=role,
            event_date=vista_date(normalized["event_date"], "event_date"),
            amount=vista_decimal(normalized["amount"], "amount"),
            previous_balance=vista_decimal(normalized["previous_balance"], "previous_balance"),
            final_balance=vista_decimal(normalized["final_balance"], "final_balance"),
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
    if not events or events[-1].final_balance != vista_decimal(account["SALDO"], "ending_balance"):
        raise ValueError("VISTA canary movement stream does not reconcile to its account balance")
    return VistaCanary(
        source_key=source_key, company_id=company_id, branch_id=branch_id, account_id=account_id,
        line_id=clean_text(account.get("line_id")) or "",
        client_external_id=clean_text(account.get("client_external_id")) or "",
        opening_date=vista_date(account["FECHA_APERTURA"], "opening_date"),
        annual_rate=vista_decimal(account["PORCENTAJE_INTERES"], "annual_rate"),
        ending_balance=vista_decimal(account["SALDO"], "ending_balance"),
        source_gl_codes={
            "savingsControlAccountId": clean_text(account.get("principal_gl")) or "",
            "interestOnSavingsAccountId": clean_text(account.get("interest_expense_gl")) or "",
            "interestPayableAccountId": clean_text(account.get("interest_payable_gl")) or "",
            "taxComponentCreditAccountId": clean_text(account.get("tax_gl")) or "",
        }, events=tuple(events),
    )


def build_dpf_canary(
    contract: SavingsContract,
    source_key: str,
    account: dict[str, Any],
    movements: list[dict[str, Any]],
    history: list[dict[str, Any]],
    owners: list[dict[str, Any]],
    cutoff: list[dict[str, Any]],
) -> DpfCanary:
    company_id, branch_id, account_id = source_key.split(":")
    owners = [{
        "owner_id": row["owner_id"],
        "client_external_id": row["client_external_id"],
        "primary_match": row["primary_match"],
    } for row in owners]
    if clean_text(account.get("ID_TIPO_CUENTA_AHORRO")) != "003":
        raise ValueError("Expected exactly one Arissto fixed-deposit account")
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
    principal = (dpf_decimal(valid_openings[0]["MONTO"], "DPF opening principal") if valid_openings else
                 dpf_decimal(account.get("MONTO_APERTURA") or 0, "DPF submitted amount"))
    cycles = contract.fixed_deposit_cycles(account, opening_rows, history)
    interests: list[DpfInterest] = []
    linked_key = (
        f"{clean_text(account.get('ID_EMPRESA_CAP'))}:"
        f"{clean_text(account.get('ID_SUCURSAL_CAP'))}:"
        f"{clean_text(account.get('ID_CUENTA_CAP'))}"
    )
    for row in history:
        if clean_text(row.get("TIPO_HISTORICO")) != "1":
            continue
        row_linked_key = (
            f"{company_id}:{clean_text(row.get('vista_branch'))}:{clean_text(row.get('vista_account'))}"
        )
        amount_matches = (
            dpf_decimal(row.get("vista_amount"), "linked VISTA amount")
            == dpf_decimal(row.get("MONTO_INTERES"), "interest")
        )
        if (
            clean_text(row.get("vista_label")) != "CAP. INT. PLAZO FIJO"
            or row_linked_key != linked_key
            or not amount_matches
        ):
            raise ValueError("DPF interest history does not reconcile to its linked VISTA movement")
        cycle = contract.fixed_deposit_history_cycle(row, cycles)
        taxed = clean_text(row.get("APLICA_RENTA")) == "1"
        if not clean_text(row.get("vista_movement_id")) or (taxed and not clean_text(row.get("tax_movement_id"))):
            raise ValueError("DPF interest history does not resolve to native VISTA movement identities")
        interests.append(DpfInterest(
            history_id=clean_text(row.get("ID_HISTORICO")) or "", cycle_sequence=int(cycle["cycle_sequence"]),
            posted_on=dpf_date(row.get("FECHA_APERTURA"), "interest date"),
            amount=dpf_decimal(row.get("MONTO_INTERES"), "interest amount"),
            tax_amount=dpf_decimal(row.get("MONTO_RENTA"), "tax amount"), taxed=taxed,
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
    reversal_notes = [
        row for row in movements
        if clean_text(row.get("transaction_label")) == "NOTA DE CARGO (REVERSION)"
    ]
    if len(reversed_openings) != len(reversal_notes):
        raise ValueError("DPF reversed opening does not have a one-for-one debit counterpart")
    return DpfCanary(
        source_key=source_key, company_id=company_id, branch_id=branch_id, account_id=account_id,
        line_id=clean_text(account.get("line_id")) or "", state=source_state,
        source_status=clean_text(account.get("source_state")) or "",
        client_external_id=clean_text(account.get("client_external_id")) or "", principal=principal,
        annual_rate=dpf_decimal(account.get("PORCENTAJE_INTERES"), "annual rate"), term_days=int(account["PLAZO"]),
        capitalization_period=clean_text(account.get("PERIODO_CAPITALIZACION")) or "", linked_vista_key=linked_key,
        cancellation_date=dpf_date(cancellations[0]["FECHA_OPERACION"], "cancellation date") if cancellations else None,
        cutoff_date=dpf_date(cutoff[0]["cutoff_date"], "cutoff date"),
        cutoff_accrual=dpf_decimal(cutoff[0]["INTERESES_PROVISIONADOS"], "cutoff accrued interest"),
        cycles=tuple(cycles), interests=tuple(interests), owners=tuple(owners),
        source_gl_codes={"savingsControlAccountId": clean_text(account.get("principal_gl")) or "",
                         "interestOnSavingsAccountId": clean_text(account.get("interest_expense_gl")) or "",
                         "interestPayableAccountId": clean_text(account.get("interest_payable_gl")) or ""},
        reversed_opening_pairs=len(reversed_openings),
        opening_movement_id=(clean_text(valid_openings[0].get("ID_AHO_MOVIMIENTO")) or "" if valid_openings else ""),
        cancellation_movement_id=(clean_text(cancellations[0].get("ID_AHO_MOVIMIENTO")) if cancellations else None),
        reversed_opening_events=tuple({
            "movement_id": clean_text(row.get("ID_AHO_MOVIMIENTO")) or "",
            "event_date": dpf_date(row.get("FECHA_OPERACION"), "reversed opening event date"),
            "amount": dpf_decimal(row.get("MONTO"), "reversed opening event amount"),
            "label": clean_text(row.get("transaction_label")) or "",
            "is_reversal": clean_text(row.get("REVERSION")) == "1",
        } for row in (*reversed_openings, *reversal_notes)),
    )


def extract_savings_lifecycles(
    settings: Settings, contract: SavingsContract, keys: list[tuple[str, str, str]], conn: Any | None = None,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    if not keys:
        return {}
    source = contract.raw["source"]
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    connection_context = nullcontext(conn) if conn is not None else source_connection(settings.source)
    with connection_context as conn:
        for batch in _chunks(keys):
            cte, params = _requested_cte(batch)
            accounts = select_rows(conn, f"""{cte}
                SELECT a.*,RTRIM(l.ID_TIPO_CUENTA_AHORRO) ID_TIPO_CUENTA_AHORRO,
                       RTRIM(a.ID_LINEA_AHORRO) line_id,RTRIM(a.ESTADO_CUENTA) source_state,
                       RTRIM(s.NUMERO_AFILIACION) client_external_id,
                       RTRIM(principal.CODIGO_CUENTA) principal_gl,
                       RTRIM(expense.CODIGO_CUENTA) interest_expense_gl,
                       RTRIM(payable.CODIGO_CUENTA) interest_payable_gl,RTRIM(tax.CODIGO_CUENTA) tax_gl
                FROM requested r JOIN dbo.{source['account_table']} a
                  ON a.ID_EMPRESA=r.company_id AND a.ID_SUCURSAL=r.branch_id AND a.ID_CUENTA_AHORRO=r.account_id
                JOIN dbo.{source['product_table']} l
                  ON l.ID_EMPRESA=a.ID_EMPRESA AND l.ID_LINEA_AHORRO=a.ID_LINEA_AHORRO
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
            """, params)
            movements = select_rows(conn, f"""{cte}
                SELECT m.*,RTRIM(t.TRANSACCION) transaction_label
                FROM requested r JOIN dbo.{source['movement_table']} m
                  ON m.ID_EMPRESA=r.company_id AND m.ID_SUCURSAL_CUENTA=r.branch_id AND m.ID_CUENTA_AHORRO=r.account_id
                JOIN dbo.TRANSACCIONES t ON t.CODIGO_SISTEMA=m.CODIGO_SISTEMA AND t.ID_TRANSACCION=m.ID_TRANSACCION
                ORDER BY m.ID_EMPRESA,m.ID_SUCURSAL_CUENTA,m.ID_CUENTA_AHORRO,
                         m.FECHA_OPERACION,m.DT_MOVIMIENTO,m.ID_AHO_MOVIMIENTO
            """, params)
            history = select_rows(conn, f"""{cte}
                SELECT h.*,CAST(vm.FECHA_OPERACION AS date) vista_event_date,
                       RTRIM(vt.TRANSACCION) vista_label,vm.MONTO vista_amount,
                       RTRIM(vm.ID_SUCURSAL_CUENTA) vista_branch,RTRIM(vm.ID_CUENTA_AHORRO) vista_account,
                       vm.ID_AHO_MOVIMIENTO vista_movement_id,tm.ID_AHO_MOVIMIENTO tax_movement_id
                FROM requested r JOIN dbo.{source['history_table']} h
                  ON h.ID_EMPRESA=r.company_id AND h.ID_SUCURSAL=r.branch_id AND h.ID_CUENTA_AHORRO=r.account_id
                LEFT JOIN dbo.{source['movement_table']} vm ON vm.ID_MOVIMIENTO_AHORRO=h.ID_MOVIMIENTO_AHORRO
                LEFT JOIN dbo.TRANSACCIONES vt
                  ON vt.CODIGO_SISTEMA=vm.CODIGO_SISTEMA AND vt.ID_TRANSACCION=vm.ID_TRANSACCION
                LEFT JOIN dbo.{source['movement_table']} tm ON tm.ID_MOVIMIENTO_AHORRO=h.ID_MOV_AHO_RENTA
                ORDER BY h.ID_EMPRESA,h.ID_SUCURSAL,h.ID_CUENTA_AHORRO,h.FECHA_APERTURA,h.ID_HISTORICO
            """, params)
            owners = select_rows(conn, f"""{cte}
                SELECT p.ID_EMPRESA,p.ID_SUCURSAL,p.ID_CUENTA_AHORRO,RTRIM(p.ID_PROPIETARIO) owner_id,
                       RTRIM(s.NUMERO_AFILIACION) client_external_id,
                       CASE WHEN p.ID_SUCURSAL_SOCIO=a.ID_SUCURSAL_SOCIO AND p.ID_SOCIO=a.ID_SOCIO
                            THEN 1 ELSE 0 END primary_match
                FROM requested r JOIN dbo.{source['owner_table']} p
                  ON p.ID_EMPRESA=r.company_id AND p.ID_SUCURSAL=r.branch_id AND p.ID_CUENTA_AHORRO=r.account_id
                JOIN dbo.{source['account_table']} a
                  ON a.ID_EMPRESA=p.ID_EMPRESA AND a.ID_SUCURSAL=p.ID_SUCURSAL AND a.ID_CUENTA_AHORRO=p.ID_CUENTA_AHORRO
                JOIN dbo.AFI_SOCIO s ON s.ID_EMPRESA=p.ID_EMPRESA
                 AND s.ID_SUCURSAL=p.ID_SUCURSAL_SOCIO AND s.ID_SOCIO=p.ID_SOCIO
                ORDER BY p.ID_EMPRESA,p.ID_SUCURSAL,p.ID_CUENTA_AHORRO,p.ID_PROPIETARIO
            """, params)
            cutoff = select_rows(conn, f"""{cte},
                x AS (SELECT MAX(CAST(FECHA_OPERACION AS date)) cutoff_date FROM dbo.CIERRE_DIARIO WHERE CIERRE='1')
                SELECT a.ID_EMPRESA,a.ID_SUCURSAL,a.ID_CUENTA_AHORRO,x.cutoff_date,d.INTERESES_PROVISIONADOS
                FROM requested r JOIN dbo.{source['account_table']} a
                  ON a.ID_EMPRESA=r.company_id AND a.ID_SUCURSAL=r.branch_id AND a.ID_CUENTA_AHORRO=r.account_id
                CROSS JOIN x JOIN dbo.AHO_HISTORICO_DIARIO d ON d.ID_AHORRO=a.ID_AHORRO
                JOIN dbo.CIERRE_DIARIO c ON c.ID_CIERRE_DIARIO=d.ID_CIERRE_DIARIO
                 AND CAST(c.FECHA_OPERACION AS date)=x.cutoff_date
            """, params)
            account_by_key = {_key(row, "ID_EMPRESA", "ID_SUCURSAL", "ID_CUENTA_AHORRO"): row for row in accounts}
            movement_by_key = _group(movements, "ID_EMPRESA", "ID_SUCURSAL_CUENTA", "ID_CUENTA_AHORRO")
            history_by_key = _group(history, "ID_EMPRESA", "ID_SUCURSAL", "ID_CUENTA_AHORRO")
            owner_by_key = _group(owners, "ID_EMPRESA", "ID_SUCURSAL", "ID_CUENTA_AHORRO")
            cutoff_by_key = _group(cutoff, "ID_EMPRESA", "ID_SUCURSAL", "ID_CUENTA_AHORRO")
            for key in batch:
                account = account_by_key.get(key)
                if account is None:
                    raise ValueError(f"Expected exactly one Arissto savings account for {':'.join(key)}")
                result[key] = {
                    "account": account,
                    "movements": movement_by_key.get(key, []),
                    "history": history_by_key.get(key, []),
                    "owners": owner_by_key.get(key, []),
                    "cutoff": cutoff_by_key.get(key, []),
                }
    return result
