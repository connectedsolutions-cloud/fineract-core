from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .arissto import select_rows, source_connection
from .config import Settings
from .connections import FineractApi


@dataclass(frozen=True)
class SourceInstallment:
    number: int
    due_date: date
    principal: Decimal
    interest: Decimal
    other: Decimal
    contribution: Decimal


@dataclass(frozen=True)
class LoanScheduleCanary:
    source_key: int
    line_id: str
    principal: Decimal
    annual_interest_rate: Decimal
    origin_date: date
    first_due_date: date
    frequency_id: int
    installments: tuple[SourceInstallment, ...]


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value or 0))
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


def fetch_schedule_canary(settings: Settings, source_key: int) -> LoanScheduleCanary:
    with source_connection(settings.source) as conn:
        loans = select_rows(conn, """
            SELECT ID_CREDITO,RTRIM(ID_LINEA_CREDITO) AS ID_LINEA_CREDITO,
                   COALESCE(NULLIF(MONTO_DESEMBOLSADO,0),MONTO_APROBADO) AS PRINCIPAL,
                   PORC_INTERES_APROBADO,FECHA_OTORGAMIENTO,FECHA_PRIMER_PAGO,
                   ID_FRECUENCIA,NO_CUOTAS_APROBADO
            FROM dbo.CRD_CARTERA WHERE ID_CREDITO=?
        """, (source_key,))
        if len(loans) != 1:
            raise ValueError(f"Expected one CRD_CARTERA row for ID_CREDITO={source_key}")
        periods = select_rows(conn, """
            SELECT NO_CUOTA,FECHA_PAGO,MONTO_CAPITAL,MONTO_INTERES,MONTO_OTROS,
                   MONTO_APORTACION,ID_REESTRUCTURACION,CUOTA_DIFERIDA
            FROM dbo.CRD_PLAN_PAGO WHERE ID_CREDITO=?
            ORDER BY NO_CUOTA,FECHA_PAGO,ID_PLAN_PAGO
        """, (source_key,))

    loan = loans[0]
    if not periods:
        raise ValueError("Schedule canary has no CRD_PLAN_PAGO rows")
    if any(row.get("ID_REESTRUCTURACION") is not None for row in periods):
        raise ValueError("Schedule canary must not contain restructuring rows")
    if any(str(row.get("CUOTA_DIFERIDA") or "").strip() in {"1", "S", "Y"} for row in periods):
        raise ValueError("Schedule canary must not contain deferred installments")
    approved_count = int(loan.get("NO_CUOTAS_APROBADO") or 0)
    if approved_count != len(periods):
        raise ValueError("Approved installment count does not match CRD_PLAN_PAGO")

    installments = tuple(
        SourceInstallment(
            number=int(row["NO_CUOTA"]),
            due_date=_date(row["FECHA_PAGO"], "FECHA_PAGO"),
            principal=_decimal(row.get("MONTO_CAPITAL"), "MONTO_CAPITAL"),
            interest=_decimal(row.get("MONTO_INTERES"), "MONTO_INTERES"),
            other=_decimal(row.get("MONTO_OTROS"), "MONTO_OTROS"),
            contribution=_decimal(row.get("MONTO_APORTACION"), "MONTO_APORTACION"),
        )
        for row in periods
    )
    first_due = _date(loan["FECHA_PRIMER_PAGO"], "FECHA_PRIMER_PAGO")
    if installments[0].due_date != first_due:
        raise ValueError("First source installment does not match FECHA_PRIMER_PAGO")
    return LoanScheduleCanary(
        source_key=source_key,
        line_id=str(loan["ID_LINEA_CREDITO"]).strip(),
        principal=_decimal(loan["PRINCIPAL"], "PRINCIPAL"),
        annual_interest_rate=_decimal(loan["PORC_INTERES_APROBADO"], "PORC_INTERES_APROBADO"),
        origin_date=_date(loan["FECHA_OTORGAMIENTO"], "FECHA_OTORGAMIENTO"),
        first_due_date=first_due,
        frequency_id=int(loan["ID_FRECUENCIA"]),
        installments=installments,
    )


def _frequency(canary: LoanScheduleCanary) -> tuple[int, int, int]:
    count = len(canary.installments)
    if canary.frequency_id == 1:
        return count, 1, 0
    if canary.frequency_id == 7:
        return count, 1, 1
    if canary.frequency_id == 15:
        return count * 15, 15, 0
    if canary.frequency_id == 30:
        return count, 1, 2
    raise ValueError(f"Unsupported Arissto frequency for schedule proof: {canary.frequency_id}")


def build_schedule_payload(
    canary: LoanScheduleCanary,
    product_id: int,
    client_id: int,
    transaction_strategy: str,
    interest_rate_frequency_type: int = 3,
    amortization_type: int = 1,
    interest_type: int = 0,
    interest_calculation_period_type: int = 0,
) -> dict[str, Any]:
    loan_term, repay_every, frequency_type = _frequency(canary)
    divisors = {0: Decimal("365"), 1: Decimal("52"), 2: Decimal("12"), 3: Decimal("1")}
    if interest_rate_frequency_type not in divisors:
        raise ValueError(f"Unsupported Fineract interest-rate frequency: {interest_rate_frequency_type}")
    periodic_rate = canary.annual_interest_rate / divisors[interest_rate_frequency_type]
    return {
        "clientId": client_id,
        "productId": product_id,
        "principal": format(canary.principal, "f"),
        "loanTermFrequency": loan_term,
        "loanTermFrequencyType": frequency_type,
        "numberOfRepayments": len(canary.installments),
        "repaymentEvery": repay_every,
        "repaymentFrequencyType": frequency_type,
        "interestRatePerPeriod": format(periodic_rate, "f"),
        "interestRateFrequencyType": interest_rate_frequency_type,
        "amortizationType": amortization_type,
        "interestType": interest_type,
        "interestCalculationPeriodType": interest_calculation_period_type,
        "transactionProcessingStrategyCode": transaction_strategy,
        "expectedDisbursementDate": canary.origin_date.isoformat(),
        "submittedOnDate": canary.origin_date.isoformat(),
        "repaymentsStartingFromDate": canary.first_due_date.isoformat(),
        "dateFormat": "yyyy-MM-dd",
        "locale": "en",
        "loanType": "individual",
    }


def _fineract_date(value: Any) -> date:
    if isinstance(value, list) and len(value) == 3:
        return date(int(value[0]), int(value[1]), int(value[2]))
    return _date(value, "Fineract dueDate")


def compare_schedules(
    canary: LoanScheduleCanary,
    schedule: dict[str, Any],
    tolerance: Decimal = Decimal("0.01"),
) -> dict[str, Any]:
    target_periods = [
        period for period in schedule.get("periods", [])
        if period.get("period") not in (None, 0) and period.get("dueDate") is not None
    ]
    mismatches: list[dict[str, Any]] = []
    installment_count_matches = len(target_periods) == len(canary.installments)
    if not installment_count_matches:
        mismatches.append({
            "kind": "installment_count",
            "source": len(canary.installments),
            "target": len(target_periods),
        })
    for source, target in zip(canary.installments, target_periods):
        checks = {
            "due_date": (source.due_date, _fineract_date(target.get("dueDate"))),
            "principal": (source.principal, _decimal(target.get("principalDue"), "principalDue")),
            "interest": (source.interest, _decimal(target.get("interestDue"), "interestDue")),
        }
        for field, (source_value, target_value) in checks.items():
            different = source_value != target_value
            if different:
                mismatches.append({
                    "kind": field,
                    "installment": source.number,
                    "source": str(source_value),
                    "target": str(target_value),
                })
    unsupported_other = sum(1 for item in canary.installments if item.other or item.contribution)
    source_principal = sum((item.principal for item in canary.installments), Decimal("0"))
    source_interest = sum((item.interest for item in canary.installments), Decimal("0"))
    target_principal = sum(
        (_decimal(item.get("principalDue"), "principalDue") for item in target_periods), Decimal("0")
    )
    target_interest = sum(
        (_decimal(item.get("interestDue"), "interestDue") for item in target_periods), Decimal("0")
    )
    principal_delta = target_principal - source_principal
    interest_delta = target_interest - source_interest
    dates_match = installment_count_matches and not any(item["kind"] == "due_date" for item in mismatches)
    principal_total_matches = installment_count_matches and abs(principal_delta) < tolerance
    interest_total_matches = installment_count_matches and abs(interest_delta) < tolerance
    # Migration acceptance is source-exact at installment level. Aggregate
    # totals remain useful diagnostics, but can no longer hide redistribution.
    accepted = installment_count_matches and not mismatches
    return {
        "source_key": canary.source_key,
        "line_id": canary.line_id,
        "source_installments": len(canary.installments),
        "target_installments": len(target_periods),
        "unsupported_source_component_installments": unsupported_other,
        "core_exact": not mismatches,
        "exact": not mismatches and unsupported_other == 0,
        "accepted": accepted,
        "acceptance_policy": "exact_installment_dates_principal_and_interest",
        "acceptance": {
            "installment_count_matches": installment_count_matches,
            "dates_match": dates_match,
            "principal_total_matches": principal_total_matches,
            "interest_total_matches": interest_total_matches,
            "source_other_components_deferred_to_charge_proof": unsupported_other > 0,
        },
        "totals": {
            "source_principal": format(source_principal, "f"),
            "target_principal": format(target_principal, "f"),
            "principal_delta": format(principal_delta, "f"),
            "source_interest": format(source_interest, "f"),
            "target_interest": format(target_interest, "f"),
            "interest_delta": format(interest_delta, "f"),
        },
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def prove_schedule(settings: Settings, source_key: int, product_id: int, client_id: int) -> dict[str, Any]:
    canary = fetch_schedule_canary(settings, source_key)
    api = FineractApi(settings.target)
    product = api.request("GET", f"loanproducts/{product_id}")
    strategy = str(product.get("transactionProcessingStrategyCode") or "").strip()
    if not strategy:
        raise ValueError("Target loan product has no transaction-processing strategy")
    def enum_id(name: str) -> int:
        value = product.get(name) or {}
        if value.get("id") is None:
            raise ValueError(f"Target loan product is missing {name}")
        return int(value["id"])

    payload = build_schedule_payload(
        canary,
        product_id,
        client_id,
        strategy,
        interest_rate_frequency_type=enum_id("interestRateFrequencyType"),
        amortization_type=enum_id("amortizationType"),
        interest_type=enum_id("interestType"),
        interest_calculation_period_type=enum_id("interestCalculationPeriodType"),
    )
    calculated = api.calculate_loan_schedule(payload)
    result = compare_schedules(canary, calculated)
    return {
        "block": "loans",
        "proof": "native-schedule-calculation",
        "posting": False,
        "target": settings.target.name,
        "product_id": product_id,
        **result,
    }
