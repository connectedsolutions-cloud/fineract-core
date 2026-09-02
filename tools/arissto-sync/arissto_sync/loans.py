from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_DOWN
from pathlib import Path
from typing import Any

from .arissto import IDENTIFIER, select_rows, source_connection, source_fingerprint
from .config import Settings, SourceConfig
from .connections import FineractApi, FineractError, postgres_connection, postgres_schema
from .engine import datatable_api_payload
from .state import State
from .sql_writer import ControlledSqlWriter


BLOCK = "loans"
SOURCE_SYSTEM = "ARISSTO"

ACCOUNTING_RESPONSE_KEYS = {
    "fundSourceAccountId": "fundSourceAccount",
    "loanPortfolioAccountId": "loanPortfolioAccount",
    "transfersInSuspenseAccountId": "transfersInSuspenseAccount",
    "receivableInterestAccountId": "receivableInterestAccount",
    "receivableFeeAccountId": "receivableFeeAccount",
    "receivablePenaltyAccountId": "receivablePenaltyAccount",
    "interestOnLoanAccountId": "interestOnLoanAccount",
    "incomeFromFeeAccountId": "incomeFromFeeAccount",
    "incomeFromPenaltyAccountId": "incomeFromPenaltyAccount",
    "incomeFromRecoveryAccountId": "incomeFromRecoveryAccount",
    "incomeFromChargeOffFeesAccountId": "incomeFromChargeOffFeesAccount",
    "incomeFromChargeOffInterestAccountId": "incomeFromChargeOffInterestAccount",
    "incomeFromChargeOffPenaltyAccountId": "incomeFromChargeOffPenaltyAccount",
    "incomeFromGoodwillCreditInterestAccountId": "incomeFromGoodwillCreditInterestAccount",
    "incomeFromGoodwillCreditFeesAccountId": "incomeFromGoodwillCreditFeesAccount",
    "incomeFromGoodwillCreditPenaltyAccountId": "incomeFromGoodwillCreditPenaltyAccount",
    "writeOffAccountId": "writeOffAccount",
    "goodwillCreditAccountId": "goodwillCreditAccount",
    "chargeOffExpenseAccountId": "chargeOffExpenseAccount",
    "chargeOffFraudExpenseAccountId": "chargeOffFraudExpenseAccount",
    "overpaymentLiabilityAccountId": "overpaymentLiabilityAccount",
}

ATTRIBUTE_OVERRIDE_FIELDS = (
    "amortizationType",
    "interestType",
    "transactionProcessingStrategyCode",
    "interestCalculationPeriodType",
    "inArrearsTolerance",
    "repaymentEvery",
    "graceOnPrincipalAndInterestPayment",
    "graceOnArrearsAgeing",
)

REVERSAL_COMPONENTS = (
    "MONTO", "MONTO_CAPITAL", "MONTO_INTERES", "MONTO_INT_PENDIENTES", "MONTO_MORA",
    "MONTO_OTROS", "MONTO_SEGURO", "MONTO_RECARGOS", "MONTO_CXC", "MONTO_AHORRO",
    "MONTO_APORTACION", "MONTO_IVA", "MONTO_IVA_INTERES", "MONTO_IVA_MORA",
    "MONTO_IVA_INTERES_PEND", "MONTO_IVA_OTROS",
)

REQUIRED_COLUMNS = {
    "product_table": {
        "ID_EMPRESA", "ID_LINEA_CREDITO", "ID_TIPO_LINEA", "CODIGO_LINEA_CREDITO", "NOMBRE_LINEA",
        "ESTADO_LINEA", "MONTO_INI", "MONTO_FIN", "TASA_INTERES", "TASA_INTERES_INI", "TASA_INTERES_FIN",
        "PLAZO_INI", "PLAZO_FIN", "ID_TIPO_PLAN_PAGO", "PRIORIDAD_MORA", "PRIORIDAD_INTERES",
        "PRIORIDAD_CAPITAL", "COBRO_MOVIL", "PROVI_INT_NORMAL", "ID_CUENTA_CARGO_PROVI",
    },
    "loan_table": {
        "ID_CREDITO", "NO_PRESTAMO", "ID_EMPRESA", "ID_SUCURSAL", "ID_LINEA_CREDITO",
        "ID_SOCIO", "ID_SOLICITUD_CREDITO", "ID_PRESTAMO_NO", "ID_ESTADO_CARTERA",
        "ID_TIPO_CREDITO", "ID_SLU", "ID_PROMOTOR", "ID_EJECUTIVO_CUENTA", "ID_GESTOR_COBRO",
        "FECHA_PRIMER_PAGO", "MONTO_APROBADO",
        "MONTO_DESEMBOLSADO", "PORC_INTERES_APROBADO", "PLAZO_APROBADO",
        "NO_CUOTAS_APROBADO", "ID_FRECUENCIA", "FECHA_OTORGAMIENTO", "FECHA_VENCIMIENTO",
        "ULTIMO_SALDO", "SALDO_INTERES", "SALDO_INTERES_PENDIENTE", "SALDO_MORA",
        "SALDO_SEGURO", "SALDO_RECARGOS", "SALDO_TOTAL",
    },
    "application_table": {
        "ID_EMPRESA", "ID_SUCURSAL", "ID_LINEA_CREDITO", "ID_SOCIO", "ID_SOLICITUD_CREDITO",
        "FECHA_SOLICITUD", "FECHA_APROBADO", "FECHA_RESOLUCION", "FECHA_DESEMBOLSO",
        "FECHA_PACTADA", "FECHA_FIRMA",
    },
    "schedule_table": {
        "ID_CREDITO", "NO_CUOTA", "FECHA_PAGO", "MONTO_CAPITAL", "MONTO_INTERES",
        "MONTO_OTROS", "MONTO_APORTACION", "ID_REESTRUCTURACION", "CUOTA_DIFERIDA",
    },
    "movement_table": {
        "ID_CREDITO", "ID_MOVIMIENTO_CARTERA", "ID_CRD_MOVIMIENTO", "CODIGO_SISTEMA",
        "ID_TRANSACCION", "REVERSION", "MONTO", "MONTO_PAGADO", "REINTEGRO_MONTO",
        "MONTO_CAPITAL", "MONTO_INTERES",
        "MONTO_INT_PENDIENTES", "MONTO_MORA", "MONTO_OTROS", "MONTO_SEGURO", "MONTO_RECARGOS",
        "MONTO_CXC", "MONTO_AHORRO", "MONTO_APORTACION", "MONTO_IVA", "MONTO_IVA_INTERES",
        "MONTO_IVA_MORA", "MONTO_IVA_INTERES_PEND", "MONTO_IVA_OTROS", "FECHA_OPERACION",
        "FECHA_VALOR", "FECHA_PAGO", "DT_MOVIMIENTO", "DT_CREO",
        "ID_CIERRE_DIARIO", "ID_USUARIO", "ID_USR_CREO", "ID_CAJA", "ID_PARTIDA", "ID_TIPO_PAGO",
    },
    "charge_table": {
        "ID_RECARGO_CARTERA", "NOMBRE_CARGO", "ID_TIPO_CARGO",
    },
    "charge_detail_table": {
        "ID_RECARGO_CARTERA", "ID_MOVIMIENTO_CARTERA", "MONTO_COBRADO",
    },
    "liquidation_header_table": {
        "ID_LIQUIDACION", "ID_EMPRESA", "ID_SUCURSAL", "ID_SOLICITUD_CREDITO",
        "ID_LINEA_CREDITO", "ID_SOCIO", "ID_PRESTAMO_NO", "CLASE_LIQ",
    },
    "liquidation_detail_table": {
        "ID_LIQUIDACION", "ID_EMPRESA", "ID_SUCURSAL", "ID_SOLICITUD_CREDITO",
        "ID_LINEA_CREDITO", "ID_SOCIO", "ID_PRESTAMO_NO", "ID_CRD_MOVIMIENTO", "MONTO",
    },
    "transaction_catalog_table": {"CODIGO_SISTEMA", "ID_TRANSACCION", "TRANSACCION"},
}

REQUIRED_TARGET_COLUMNS = {
    "m_product_loan": {
        "id", "name", "short_name", "numbering_code", "external_id", "currency_code", "accounting_type", "id_tipo_linea",
        "loan_transaction_strategy_code", "principal_amount", "min_principal_amount", "max_principal_amount",
        "nominal_interest_rate_per_period", "min_nominal_interest_rate_per_period",
        "max_nominal_interest_rate_per_period", "repay_every", "repayment_period_frequency_enum",
        "number_of_repayments", "min_number_of_repayments", "max_number_of_repayments",
    },
    "m_client": {"id", "external_id", "status_enum", "office_id", "activation_date"},
    "m_staff": {"id", "external_id", "is_active", "office_id"},
    "credesal_loan_staff_assignment": {
        "loan_id", "client_id", "arissto_company_id", "arissto_promoter_person_id",
        "arissto_account_executive_person_id", "arissto_collections_manager_person_id",
        "promoter_staff_id", "account_executive_staff_id", "collections_manager_staff_id",
        "created_at", "updated_at",
    },
    "credesal_loan_legacy_timeline": {
        "loan_id", "source_submitted_on", "source_approved_on", "source_resolution_on",
        "source_disbursed_on", "effective_approved_on", "classification", "created_at", "updated_at",
    },
    "credesal_loan_product_map": {
        "id", "source_system", "source_key", "source_hash", "contract_hash", "loan_product_id",
        "arissto_company_id", "arissto_line_id", "mapping_status", "created_at", "updated_at",
    },
    "m_loan": {"id", "account_no", "external_id", "product_id", "client_id", "loan_officer_id", "loan_status_id"},
    "m_loan_topup": {"id", "loan_id", "closure_loan_id", "operation_type", "topup_amount"},
    "m_loan_refinancing_settlement": {
        "id", "refinancing_id", "closure_loan_id", "account_transfer_details_id",
        "repayment_transaction_id", "settlement_amount", "principal_portion", "interest_portion",
        "fee_charges_portion", "penalty_charges_portion",
    },
    "m_loan_transaction": {
        "id", "loan_id", "external_id", "reversal_external_id", "is_reversed", "transaction_type_enum",
        "transaction_date", "amount", "principal_portion_derived", "interest_portion_derived",
        "fee_charges_portion_derived", "penalty_charges_portion_derived", "is_source_exact_allocation",
        "source_exact_principal_portion", "source_exact_interest_portion",
        "source_exact_fee_charges_portion", "source_exact_penalty_charges_portion",
        "source_exact_reallocation_system", "source_exact_reversal_movement_ids",
        "source_exact_repayment_movement_id",
    },
    "m_permission": {"id", "code"},
    "acc_product_mapping": {"id", "product_id", "product_type", "gl_account_id", "financial_account_type", "payment_type"},
    "acc_gl_account": {"id", "gl_code", "name", "classification_enum", "disabled"},
}


@dataclass(frozen=True)
class LoanContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "LoanContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("version") != 1:
            raise ValueError("Loans mapping requires version 1")
        for section in (
            "source", "identity", "product_contract", "target", "supported_transactions",
            "historical_schedule_exceptions", "historical_reference_only_schedules",
            "source_error_quarantines",
            "timestamp_precedence_candidates", "movement_order",
            "implementation_gates",
        ):
            if section not in value:
                raise ValueError(f"Loans mapping is missing {section!r}")
        for table in value["source"].values():
            if not isinstance(table, str) or not IDENTIFIER.fullmatch(table):
                raise ValueError(f"Unsafe loans source table: {table!r}")
        if value["identity"].get("loan_key") != "ID_CREDITO":
            raise ValueError("Loans mapping must use ID_CREDITO as the loan key")
        if value["identity"].get("movement_key") != "ID_MOVIMIENTO_CARTERA":
            raise ValueError("Loans mapping must use ID_MOVIMIENTO_CARTERA as the movement key")
        if value["identity"].get("product_key") != ["ID_LINEA_CREDITO"]:
            raise ValueError("Loans mapping must use only ID_LINEA_CREDITO as the product key")
        if value["identity"].get("product_external_id") != "ARISSTO:CRD-LINE:{ID_LINEA_CREDITO}":
            raise ValueError("Loans mapping has an invalid product external ID template")
        if value["identity"].get("legacy_insurance_charge_external_id") != (
            "ARISSTO:CRD-INS-LEGACY:{ID_MOVIMIENTO_CARTERA}"
        ):
            raise ValueError("Loans mapping has an invalid legacy-insurance external ID template")
        product_contract = value["product_contract"]
        if product_contract.get("target_baseline") != "empty-business-data":
            raise ValueError("Loans product planning must assume an empty business-data target")
        if product_contract.get("product_ownership") != "loans-service-creates-native-products":
            raise ValueError("The loans service must own native loan-product creation")
        if product_contract.get("resolution_policy") != "external-id-create-or-validate":
            raise ValueError("Loan products must resolve only by their deterministic external ID")
        if product_contract.get("reuse_unowned_products") is not False:
            raise ValueError("Loans migration cannot reuse unowned native products")
        if product_contract.get("crosswalk_write_timing") != "after-native-product-create":
            raise ValueError("Loan product crosswalks must follow native product creation")
        if product_contract.get("creation_scope") != "reviewed-lines-required-by-selected-loans":
            raise ValueError("Loan product creation must remain limited to reviewed lines required by the plan")
        portfolio_policy = product_contract.get("portfolio_account_policy")
        if not isinstance(portfolio_policy, dict):
            raise ValueError("Loans product contract must define its portfolio-account policy")
        if portfolio_policy.get("mode") != "single-native-account-per-product":
            raise ValueError("Each native loan product must use one portfolio account")
        if portfolio_policy.get("source_primary_field") != "ID_CUENTA_CARGO_CAPITAL":
            raise ValueError("Native portfolio accounts must come from the reviewed source primary field")
        if portfolio_policy.get("dynamic_gl_switching") is not False:
            raise ValueError("Loan products cannot switch portfolio GL accounts dynamically")
        if portfolio_policy.get("split_products_by_historical_account") is not False:
            raise ValueError("Historical source accounts cannot split a native loan product")
        if portfolio_policy.get("reviewed_primary_gl_by_line") != {
            "00001": "1141040101", "00010": "1141030101",
        }:
            raise ValueError("Reviewed loan lines must retain their single primary portfolio accounts")
        if portfolio_policy.get("historical_alternate_gl_for_reconciliation") != {
            "00001": ["1142040101"], "00010": ["1142030101"],
        }:
            raise ValueError("Historical alternate portfolio accounts must remain reconciliation-only")
        dimension_contract = product_contract.get("dimension_contract")
        if not isinstance(dimension_contract, dict):
            raise ValueError("Loans product contract must define reporting dimensions")
        if dimension_contract.get("product_native_type_field") != {
            "target": "m_product_loan.id_tipo_linea", "source": "CRD_LINEA_CREDITO.ID_TIPO_LINEA",
        }:
            raise ValueError("Loan product type must preserve Arissto ID_TIPO_LINEA")
        if dimension_contract.get("journal_propagation") != "m_loan.dimensions-to-acc_gl_journal_entry.dimensions":
            raise ValueError("Loan dimensions must propagate to journal entries")
        if dimension_contract.get("report_filter") != "json-containment":
            raise ValueError("Loan journal reporting must use native JSON dimension containment")
        reviewed_terms = product_contract.get("reviewed_product_terms")
        if not isinstance(reviewed_terms, dict) or set(reviewed_terms) != {"00001", "00010"}:
            raise ValueError("Loans mapping must freeze product terms for the two populated source lines")
        required_terms = {
            "principal", "minPrincipal", "maxPrincipal", "numberOfRepayments",
            "minNumberOfRepayments", "maxNumberOfRepayments", "interestRatePerPeriod",
            "minInterestRatePerPeriod", "maxInterestRatePerPeriod",
        }
        for line_id, terms in reviewed_terms.items():
            if not isinstance(terms, dict) or set(terms) != required_terms:
                raise ValueError(f"Loan product terms are incomplete for line {line_id}")
        accounting_codes = product_contract.get("accounting_gl_codes")
        if not isinstance(accounting_codes, dict) or set(accounting_codes) != (
            set(ACCOUNTING_RESPONSE_KEYS) - {"loanPortfolioAccountId"}
        ):
            raise ValueError("Loans mapping must freeze every shared native accounting GL role")
        resources = product_contract.get("target_resources")
        if not isinstance(resources, dict) or set(resources) != {
            "debt_insurance_charge", "historical_debt_insurance_charge",
            "historical_penalty_charge", "mobile_collection_payment_type",
            "mobile_collection_fund_source_gl",
        }:
            raise ValueError("Loans mapping must freeze charge and payment-channel target resources")
        insurance = resources["debt_insurance_charge"]
        if insurance != {
            "amount": "0.06", "charge_time_type": 8, "calculation_type": 8,
            "income_or_liability_gl": "222007020102",
        }:
            raise ValueError("Loans mapping has an invalid debt-insurance target contract")
        if resources["historical_penalty_charge"] != {
            "name": "Arissto historical penalty allocation", "charge_time_type": 2, "calculation_type": 1,
        }:
            raise ValueError("Loans mapping has an invalid historical-penalty target contract")
        if resources["historical_debt_insurance_charge"] != {
            "name": "Arissto historical debt-insurance allocation", "charge_time_type": 2,
            "calculation_type": 1, "income_or_liability_gl": "222007020102",
        }:
            raise ValueError("Loans mapping has an invalid historical debt-insurance target contract")
        if value.get("movement_order") != ["FECHA_OPERACION", "ID_MOVIMIENTO_CARTERA"]:
            raise ValueError("Loans mapping must order movements by FECHA_OPERACION then ID_MOVIMIENTO_CARTERA")
        expected_schedule_exceptions = {
            "00001": [24, 435, 945],
            "00010": [23, 90, 317, 340, 359, 1117, 1484, 1743, 1748,
                      2069, 2241, 2254, 2355],
        }
        if set(value["historical_schedule_exceptions"]) != set(expected_schedule_exceptions):
            raise ValueError("Loans mapping has an unreviewed historical schedule exception scope")
        for line_id, expected_loan_ids in expected_schedule_exceptions.items():
            schedule_exception = value["historical_schedule_exceptions"].get(line_id)
            if not isinstance(schedule_exception, dict):
                raise ValueError(f"Loans mapping must define the reviewed line {line_id} schedule exception")
            if schedule_exception.get("classification") != "manual-adjustment":
                raise ValueError(f"Line {line_id} schedule exceptions must be classified as manual adjustments")
            if schedule_exception.get("plan_behavior") != "accept-native-schedule":
                raise ValueError(f"Line {line_id} manual adjustments must accept the native schedule")
            if schedule_exception.get("blocking") is not False:
                raise ValueError(f"Line {line_id} manual adjustments must be non-blocking")
            if schedule_exception.get("synthesize_missing_installments") is not False:
                raise ValueError(f"Line {line_id} manual adjustments cannot synthesize installments")
            if schedule_exception.get("synthesize_adjustment_transactions") is not False:
                raise ValueError(f"Line {line_id} manual adjustments cannot synthesize transactions")
            if schedule_exception.get("source_loan_ids") != expected_loan_ids:
                raise ValueError(
                    f"Line {line_id} manual adjustments must remain limited to reviewed loans {expected_loan_ids}"
                )
            if schedule_exception.get("required_reconciliation") != [
                "source-movement-identities", "source-movement-component-totals", "cutover-balances", "terminal-status",
            ]:
                raise ValueError(f"Line {line_id} manual adjustments must retain exact lifecycle reconciliation")
        reference_only_requirements = {
            "plan_behavior": "accept-native-schedule",
            "blocking": False,
            "synthesize_missing_installments": False,
            "synthesize_adjustment_transactions": False,
            "required_reconciliation": [
                "source-movement-identities", "source-movement-component-totals",
                "cutover-balances", "terminal-status",
            ],
        }
        expected_reference_only_schedules = {
            "26": {
                "classification": "closed-zero-principal-schedule-with-exact-lifecycle",
                **reference_only_requirements,
            },
            "83": {
                "classification": "incomplete-source-contractual-schedule",
                **reference_only_requirements,
            },
            **{
                str(loan_id): {
                    "classification": "trailing-zero-core-schedule-rows",
                    **reference_only_requirements,
                }
                for loan_id in (8, 1739, 1795, 1893, 2063, 2111, 2482)
            },
            **{
                str(loan_id): {
                    "classification": "terminal-zero-core-charge-only-row",
                    **reference_only_requirements,
                }
                for loan_id in (381, 1775, 1871, 2006)
            },
        }
        if value["historical_reference_only_schedules"] != expected_reference_only_schedules:
            raise ValueError("Loans mapping has an unreviewed reference-only schedule scope")
        expected_source_error_quarantines = {
            "2120": {
                "classification": "superseded-undisbursed-shell",
                "plan_behavior": "quarantine-loan",
                "replacement_loan_id": 2121,
                "create_target_loan": False,
            },
        }
        if value["source_error_quarantines"] != expected_source_error_quarantines:
            raise ValueError("Loans mapping has an unreviewed source-error quarantine scope")
        return cls(value)

    @property
    def digest(self) -> str:
        material = json.dumps(self.raw, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(material.encode()).hexdigest()


def canonical_source_key(value: str | int | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise ValueError("Loans source key must be a positive integer ID_CREDITO")
    return int(text)


def product_action_key(line_id: str) -> str:
    value = _clean(line_id)
    if not re.fullmatch(r"[0-9]{5}", value):
        raise ValueError(f"Invalid Arissto credit-line identity: {line_id!r}")
    return f"product:{value}"


def loan_action_key(loan_id: str | int) -> str:
    value = canonical_source_key(loan_id)
    if value is None:
        raise ValueError("Loan action key requires ID_CREDITO")
    return f"loan:{value}"


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _stable_hash(value: Any) -> str:
    material = json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(material.encode()).hexdigest()


def _enum_id(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("id")
    return int(value) if value is not None else None


def _decimal_text(value: Any) -> str:
    return format(Decimal(str(value or 0)).normalize(), "f")


def _dimensions(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("Loan product dimensions must be a JSON object")
        return parsed
    if not isinstance(value, dict):
        raise ValueError("Loan product dimensions must be an object")
    return value


def build_loan_product_payload(
    contract: LoanContract,
    source_product: dict[str, Any],
    target_resources: dict[str, Any],
) -> dict[str, Any]:
    """Freeze one complete, target-specific native product in the plan."""
    line_id = _clean(source_product.get("line_id") or source_product.get("ID_LINEA_CREDITO"))
    line_type = _clean(source_product.get("line_type") or source_product.get("ID_TIPO_LINEA"))
    line_name = _clean(source_product.get("line_name") or source_product.get("NOMBRE_LINEA"))
    line_family = line_name[:1].upper()
    if not re.fullmatch(r"[A-Z]", line_family):
        raise ValueError(f"Credit line {line_id} has no valid numbering family in its name")
    terms = contract.raw["product_contract"]["reviewed_product_terms"].get(line_id)
    if terms is None:
        raise ValueError(f"Credit line {line_id} has no reviewed native product terms")
    gl_ids = target_resources["gl_ids"]
    payload: dict[str, Any] = {
        "name": f"Arissto {line_id} {line_name}"[:100],
        "shortName": f"A{line_id[-3:]}",
        "numberingCode": f"3{line_family}1",
        "description": f"Native migration product for Arissto credit line {line_id}",
        "externalId": contract.raw["identity"]["product_external_id"].format(ID_LINEA_CREDITO=line_id),
        "idTipoLinea": line_type,
        "dimensions": {"arisstoCreditLineId": line_id, "arisstoCreditLineTypeId": line_type},
        "currencyCode": contract.raw["target"]["currency"],
        "digitsAfterDecimal": 2,
        "inMultiplesOf": 0,
        **terms,
        "repaymentEvery": 1,
        "repaymentFrequencyType": 2,
        "interestRateFrequencyType": 2,
        "amortizationType": 1,
        "interestType": 0,
        "interestCalculationPeriodType": 0,
        "transactionProcessingStrategyCode": contract.raw["product_contract"]["transaction_strategy"],
        "accountingRule": 3,
        "daysInMonthType": 1,
        "daysInYearType": 1,
        "isInterestRecalculationEnabled": False,
        "loanScheduleType": "CUMULATIVE",
        "loanScheduleProcessingType": "HORIZONTAL",
        "canUseForTopup": True,
        # Historical Arissto schedules are imposed while the application is
        # pending through Fineract's native term-variation API.
        "allowVariableInstallments": True,
        "minimumGap": 1,
        "maximumGap": 366,
        "allowAttributeOverrides": {
            "amortizationType": True,
            "interestType": True,
            "transactionProcessingStrategyCode": True,
            "interestCalculationPeriodType": True,
            "inArrearsTolerance": True,
            "repaymentEvery": True,
            "graceOnPrincipalAndInterestPayment": True,
            "graceOnArrearsAgeing": True,
        },
        "locale": "en",
    }
    for parameter, gl_code in contract.raw["product_contract"]["accounting_gl_codes"].items():
        payload[parameter] = int(gl_ids[gl_code])
    portfolio_code = contract.raw["product_contract"]["portfolio_account_policy"]["reviewed_primary_gl_by_line"][line_id]
    payload["loanPortfolioAccountId"] = int(gl_ids[portfolio_code])
    charge_id = int(target_resources["debt_insurance_charge_id"])
    insurance_account_id = int(gl_ids[
        contract.raw["product_contract"]["target_resources"]["debt_insurance_charge"]["income_or_liability_gl"]
    ])
    payload["charges"] = [{"id": charge_id}]
    payload["feeToIncomeAccountMappings"] = [{"chargeId": charge_id, "incomeAccountId": insurance_account_id}]
    payload["penaltyToIncomeAccountMappings"] = []
    payload["paymentChannelToFundSourceMappings"] = [{
        "paymentTypeId": int(target_resources["mobile_collection_payment_type_id"]),
        "fundSourceAccountId": int(gl_ids[
            contract.raw["product_contract"]["target_resources"]["mobile_collection_fund_source_gl"]
        ]),
    }]
    return payload


def loan_product_contract_view(value: dict[str, Any], *, planned: bool) -> dict[str, Any]:
    """Normalize create payloads and API reads to the same strict comparison shape."""
    def scalar(name: str, response_name: str | None = None) -> Any:
        result = value.get(name if planned else (response_name or name))
        return result

    view: dict[str, Any] = {
        "name": scalar("name"),
        "shortName": scalar("shortName"),
        "numberingCode": scalar("numberingCode"),
        "description": scalar("description") or "",
        "externalId": scalar("externalId"),
        "idTipoLinea": scalar("idTipoLinea"),
        "dimensions": _dimensions(scalar("dimensions")),
        "currencyCode": scalar("currencyCode") if planned else (value.get("currency") or {}).get("code"),
        "digitsAfterDecimal": int(scalar("digitsAfterDecimal") if planned else (value.get("currency") or {}).get("decimalPlaces", 0)),
        "inMultiplesOf": int(scalar("inMultiplesOf") if planned else (value.get("currency") or {}).get("inMultiplesOf", 0)),
    }
    decimal_fields = (
        "principal", "minPrincipal", "maxPrincipal", "interestRatePerPeriod",
        "minInterestRatePerPeriod", "maxInterestRatePerPeriod",
    )
    integer_fields = (
        "numberOfRepayments", "minNumberOfRepayments", "maxNumberOfRepayments", "repaymentEvery",
    )
    for name in decimal_fields:
        view[name] = _decimal_text(value.get(name))
    for name in integer_fields:
        view[name] = int(value.get(name) or 0)
    enum_fields = (
        "repaymentFrequencyType", "interestRateFrequencyType", "amortizationType", "interestType",
        "interestCalculationPeriodType", "accountingRule", "daysInMonthType", "daysInYearType",
    )
    for name in enum_fields:
        view[name] = _enum_id(value.get(name))
    view["transactionProcessingStrategyCode"] = value.get("transactionProcessingStrategyCode")
    view["isInterestRecalculationEnabled"] = bool(value.get("isInterestRecalculationEnabled", False))
    view["canUseForTopup"] = bool(value.get("canUseForTopup", False))
    view["allowVariableInstallments"] = bool(value.get("allowVariableInstallments", False))
    view["minimumGap"] = int(value.get("minimumGap") or 0)
    maximum_gap = value.get("maximumGap")
    view["maximumGap"] = int(maximum_gap) if maximum_gap not in (None, 0) else None
    view["loanScheduleType"] = value.get("loanScheduleType") if planned else (value.get("loanScheduleType") or {}).get("code")
    view["loanScheduleProcessingType"] = (
        value.get("loanScheduleProcessingType") if planned else (value.get("loanScheduleProcessingType") or {}).get("code")
    )
    overrides = value.get("allowAttributeOverrides") or {}
    view["allowAttributeOverrides"] = {
        name: bool(overrides.get(name, False)) for name in ATTRIBUTE_OVERRIDE_FIELDS
    }
    if planned:
        for parameter in ACCOUNTING_RESPONSE_KEYS:
            view[parameter] = int(value[parameter])
        view["charges"] = sorted(int(item["id"]) for item in value.get("charges", []))
        view["paymentChannelToFundSourceMappings"] = sorted(
            (int(item["paymentTypeId"]), int(item["fundSourceAccountId"]))
            for item in value.get("paymentChannelToFundSourceMappings", [])
        )
        view["feeToIncomeAccountMappings"] = sorted(
            (int(item["chargeId"]), int(item["incomeAccountId"]))
            for item in value.get("feeToIncomeAccountMappings", [])
        )
    else:
        mappings = value.get("accountingMappings") or {}
        for parameter, response_key in ACCOUNTING_RESPONSE_KEYS.items():
            account = mappings.get(response_key) or {}
            view[parameter] = int(account.get("id") or 0)
        view["charges"] = sorted(int(item["id"]) for item in value.get("charges", []))
        view["paymentChannelToFundSourceMappings"] = sorted(
            (int((item.get("paymentType") or {}).get("id") or 0), int((item.get("fundSourceAccount") or {}).get("id") or 0))
            for item in value.get("paymentChannelToFundSourceMappings") or []
        )
        view["feeToIncomeAccountMappings"] = sorted(
            (int((item.get("charge") or {}).get("id") or 0), int((item.get("incomeAccount") or {}).get("id") or 0))
            for item in value.get("feeToIncomeAccountMappings") or []
        )
    return view


def loan_product_conflicts(payload: dict[str, Any], existing: dict[str, Any]) -> list[dict[str, Any]]:
    expected = loan_product_contract_view(payload, planned=True)
    actual = loan_product_contract_view(existing, planned=False)
    return [
        {"field": field, "expected": expected[field], "actual": actual.get(field)}
        for field in expected if expected[field] != actual.get(field)
    ]


def _schema_signature(schema: Any) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _loan_staff_external_ids(loan: dict[str, Any]) -> dict[str, str | None]:
    """Preserve each Arissto role independently; none is projected to Fineract's loan officer."""
    company_id = _clean(loan.get("company_id"))
    role_fields = {
        "promoter": "promoter_id",
        "account_executive": "account_executive_id",
        "collections_manager": "collections_manager_id",
    }
    result: dict[str, str | None] = {}
    for role, field in role_fields.items():
        person_id = _clean(loan.get(field))
        result[role] = f"{company_id}:{person_id}" if company_id and person_id else None
    return result


def _amount(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _source_period_interest(
    opening_principal: Decimal, annual_rate: Decimal, start_date: date, due_date: date,
    *, include_start_date: bool, fixed_365: bool,
) -> Decimal:
    """Reproduce fixed-365 legacy or period-start Actual/Actual interest."""
    days = (due_date - start_date).days + (1 if include_start_date else 0)
    leap_start_year = start_date.year % 400 == 0 or (
        start_date.year % 4 == 0 and start_date.year % 100 != 0
    )
    denominator = Decimal("365" if fixed_365 or not leap_start_year else "366")
    return (
        opening_principal * annual_rate * Decimal(days) / Decimal("100") / denominator
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_DOWN)


def _classify_first_accrual_day(
    loan: dict[str, Any], schedule: list[dict[str, Any]], effective_disbursement_date: str,
) -> dict[str, Any] | None:
    """Classify the bounded legacy inclusive-first-day schedule signature.

    Applicability is derived from frozen product, frequency, date, rate, and
    installment facts. Source IDs and historical cutoff dates are deliberately
    excluded. A partial signature fails closed instead of receiving the rule by
    analogy.
    """
    if _clean(loan.get("line_id")) != "00010" or int(loan.get("ID_FRECUENCIA") or 0) != 30:
        return None
    if len(schedule) < 2:
        return None
    try:
        origin_date = date.fromisoformat(_iso_date(loan.get("FECHA_OTORGAMIENTO"), "loan origin"))
        disbursement_date = date.fromisoformat(effective_disbursement_date)
        due_dates = [date.fromisoformat(_iso_date(row.get("FECHA_PAGO"), "schedule due")) for row in schedule]
    except (TypeError, ValueError):
        return None
    principal = _amount(loan.get("MONTO_APROBADO") or loan.get("MONTO_DESEMBOLSADO"))
    annual_rate = Decimal(str(loan.get("PORC_INTERES_APROBADO") or 0))
    if principal <= 0 or annual_rate <= 0 or due_dates[0] <= origin_date:
        return None
    if any(current <= previous for previous, current in zip(due_dates, due_dates[1:])):
        return None
    if any(
        row.get("ID_REESTRUCTURACION") is not None or int(row.get("CUOTA_DIFERIDA") or 0) != 0
        for row in schedule
    ):
        return None

    first_interest = _amount(schedule[0].get("MONTO_INTERES"))
    inclusive_interest = _source_period_interest(
        principal, annual_rate, origin_date, due_dates[0], include_start_date=True, fixed_365=True,
    )
    exclusive_interest = _source_period_interest(
        principal, annual_rate, origin_date, due_dates[0], include_start_date=False, fixed_365=False,
    )
    opening_principal = principal - _amount(schedule[0].get("MONTO_CAPITAL"))
    later_legacy_periods_match = True
    later_normal_periods_match = True
    for previous_due, due_date, row in zip(due_dates, due_dates[1:], schedule[1:]):
        legacy_interest = _source_period_interest(
            opening_principal, annual_rate, previous_due, due_date,
            include_start_date=False, fixed_365=True,
        )
        normal_interest = _source_period_interest(
            opening_principal, annual_rate, previous_due, due_date,
            include_start_date=False, fixed_365=False,
        )
        actual_interest = _amount(row.get("MONTO_INTERES"))
        later_legacy_periods_match &= actual_interest == legacy_interest
        later_normal_periods_match &= actual_interest == normal_interest
        opening_principal -= _amount(row.get("MONTO_CAPITAL"))

    inclusive_first = first_interest == inclusive_interest and first_interest != exclusive_interest
    exclusive_first = first_interest == exclusive_interest
    if inclusive_first and later_legacy_periods_match and origin_date == disbursement_date:
        return {
            "classification": "legacy-inclusive-first-accrual-day",
            "interest_charged_from_date": (origin_date - timedelta(days=1)).isoformat(),
            "days_in_year_type": 365,
            "source_origin_date": origin_date.isoformat(),
            "first_due_date": due_dates[0].isoformat(),
            "first_interest": format(first_interest, "f"),
        }
    if exclusive_first and later_normal_periods_match:
        return {"classification": "normal-exclusive-first-accrual-day"}
    if inclusive_first or later_legacy_periods_match or later_normal_periods_match:
        return {"classification": "ambiguous-first-accrual-day-signature"}
    return None


def _iso_date(value: Any, field: str) -> str:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return date(int(value[0]), int(value[1]), int(value[2])).isoformat()
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid {field} date: {value!r}") from exc


def _frequency_terms(frequency_id: int, installment_count: int) -> tuple[int, int, int]:
    """Return Fineract loan term, repayment every, and frequency enum."""
    if frequency_id == 1:
        return installment_count, 1, 0
    if frequency_id == 7:
        return installment_count, 1, 1
    if frequency_id == 15:
        return installment_count * 15, 15, 0
    if frequency_id == 30:
        return installment_count, 1, 2
    raise ValueError(f"Unsupported Arissto repayment frequency: {frequency_id}")


def _movement_component_total(row: dict[str, Any]) -> Decimal:
    return sum((_amount(row.get(column)) for column in (
        "MONTO_CAPITAL", "MONTO_INTERES", "MONTO_INT_PENDIENTES", "MONTO_MORA",
        "MONTO_SEGURO", "MONTO_RECARGOS", "MONTO_CXC", "MONTO_AHORRO", "MONTO_APORTACION",
        "MONTO_IVA_INTERES", "MONTO_IVA_MORA", "MONTO_IVA_INTERES_PEND", "MONTO_IVA_OTROS",
    )), Decimal("0.00"))


def _movement_refund(row: dict[str, Any], component_total: Decimal) -> Decimal | None:
    """Return source cash returned to the payer when every refund fact agrees."""
    if row.get("MONTO_PAGADO") is None or row.get("REINTEGRO_MONTO") is None:
        return None
    gross = _amount(row.get("MONTO"))
    applied = _amount(row.get("MONTO_PAGADO"))
    refund = _amount(row.get("REINTEGRO_MONTO"))
    if gross < applied or refund <= 0:
        return None
    if gross - applied != refund or applied != component_total:
        return None
    return refund


def _is_verified_legacy_other_insurance(
    row: dict[str, Any], role: str, insurance_details: list[dict[str, Any]],
) -> bool:
    """Recognize pre-detail debt insurance only from balance and subledger provenance."""
    amount = _amount(row.get("MONTO_OTROS"))
    return (
        role in {"repayment", "adjusted-repayment", "mobile-collection-repayment"}
        and amount > 0
        and _amount(row.get("MONTO_SEGURO")) == 0
        and not insurance_details
        and _amount(row.get("LEGACY_OTHER_PRE_BALANCE")) == amount
        and _amount(row.get("LEGACY_OTHER_POST_BALANCE")) == 0
        and _amount(row.get("LEGACY_OTHER_PRE_PAID")) == 0
        and _amount(row.get("LEGACY_OTHER_POST_PAID")) == amount
        and int(row.get("LEGACY_OTHER_INSURANCE_LEDGER_COUNT") or 0) == 1
    )


def _loan_status_matches(source_state: str, target_status: dict[str, Any]) -> bool:
    status_id = int(target_status.get("id") or -1)
    if source_state == "1":
        return status_id == 300
    if source_state == "2":
        return status_id in {100, 200}
    if source_state == "3":
        return bool(target_status.get("closed")) or status_id in {600, 601, 602, 700}
    return False


def _reversal_signature(row: dict[str, Any]) -> tuple[Decimal, ...]:
    return tuple(_amount(row.get(column)) for column in REVERSAL_COMPONENTS)


def _movement_order(row: dict[str, Any]) -> tuple[Any, str]:
    operation_date = row.get("FECHA_OPERACION")
    if isinstance(operation_date, datetime):
        operation_date = operation_date.date()
    return operation_date, _clean(row.get("ID_MOVIMIENTO_CARTERA"))


def _is_reversed_repayment(row: dict[str, Any]) -> bool:
    system = str(row.get("CODIGO_SISTEMA"))
    transaction = _clean(row.get("ID_TRANSACCION"))
    return _clean(row.get("REVERSION")) == "1" and (
        (system == "4" and transaction in {"00001", "00013", "00019"})
        or (system == "14" and transaction == "00011")
    )


def pair_loan_reversals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pair source reversal notes without date/amount-only inference.

    Arissto marks the original repayment as reversed and then records a 00004
    compensating note. Disbursement reversals use 00030 but do not consistently
    mark the original 00002 row. Within a loan, exact component identity plus
    the frozen business order makes both relationships a LIFO event chain.
    """
    pools: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"payments": [], "disbursements": []}
    )
    pairs: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    disambiguated: Counter[str] = Counter()

    ordered = sorted(rows, key=lambda row: (int(row["ID_CREDITO"]), *_movement_order(row)))
    for row in ordered:
        loan_id = int(row["ID_CREDITO"])
        system = str(row.get("CODIGO_SISTEMA"))
        transaction = _clean(row.get("ID_TRANSACCION"))
        if _is_reversed_repayment(row):
            pools[loan_id]["payments"].append(row)
            continue
        if system == "4" and transaction == "00002":
            pools[loan_id]["disbursements"].append(row)
            continue
        if system != "4" or transaction not in {"00004", "00030"}:
            continue

        kind = "payments" if transaction == "00004" else "disbursements"
        matches = [candidate for candidate in pools[loan_id][kind]
                   if _reversal_signature(candidate) == _reversal_signature(row)]
        if not matches:
            reversal_kind = "repayment" if transaction == "00004" else "disbursement"
            issues.append({
                "code": f"orphan_{reversal_kind}_reversal",
                "loan_id": loan_id,
                "reversal_movement_id": _clean(row.get("ID_MOVIMIENTO_CARTERA")),
            })
            continue
        if len(matches) > 1:
            disambiguated[kind] += 1
        original = max(matches, key=_movement_order)
        pools[loan_id][kind].remove(original)
        pairs.append({
            "kind": "repayment" if transaction == "00004" else "disbursement",
            "loan_id": loan_id,
            "original_movement_id": _clean(original.get("ID_MOVIMIENTO_CARTERA")),
            "reversal_movement_id": _clean(row.get("ID_MOVIMIENTO_CARTERA")),
            "original_transaction": f"{original.get('CODIGO_SISTEMA')}:{_clean(original.get('ID_TRANSACCION'))}",
            "amount": str(_amount(row.get("MONTO"))),
            "candidate_count": len(matches),
        })

    unpaired_reversed = [
        {
            "code": "reversed_original_without_note",
            "loan_id": loan_id,
            "movement_id": _clean(row.get("ID_MOVIMIENTO_CARTERA")),
            "transaction": f"{row.get('CODIGO_SISTEMA')}:{_clean(row.get('ID_TRANSACCION'))}",
        }
        for loan_id, pool in pools.items() for row in pool["payments"]
    ]
    issues.extend(unpaired_reversed)
    original_counts = Counter(item["original_movement_id"] for item in pairs)
    duplicate_originals = sorted(key for key, count in original_counts.items() if count > 1)
    repayment_types = Counter(
        item["original_transaction"] for item in pairs if item["kind"] == "repayment"
    )
    return {
        "movement_order": ["FECHA_OPERACION", "ID_MOVIMIENTO_CARTERA"],
        "pair_count": len(pairs),
        "repayment_pair_count": sum(item["kind"] == "repayment" for item in pairs),
        "disbursement_pair_count": sum(item["kind"] == "disbursement" for item in pairs),
        "lifo_disambiguated_count": sum(disambiguated.values()),
        "lifo_disambiguated_by_kind": dict(sorted(disambiguated.items())),
        "repayment_original_type_counts": dict(sorted(repayment_types.items())),
        "duplicate_original_count": len(duplicate_originals),
        "duplicate_original_movement_ids": duplicate_originals,
        "unpaired_reversed_original_count": len(unpaired_reversed),
        "issue_count": len(issues),
        "affected_loan_count": len({int(issue["loan_id"]) for issue in issues}),
        "issues": issues,
        "pairs": pairs,
    }


def classify_source_exact_component_reallocations(
    rows: list[dict[str, Any]], pairing: dict[str, Any]
) -> dict[str, Any]:
    """Recognize a complete Arissto reversal/reapplication atom, never a lone note."""
    by_id = {_clean(row.get("ID_MOVIMIENTO_CARTERA")): row for row in rows}
    paired_signatures = {
        (int(pair["loan_id"]), _reversal_signature(by_id[pair["reversal_movement_id"]]))
        for pair in pairing["pairs"] if pair["kind"] == "repayment"
    }
    orphan_ids = {
        issue["reversal_movement_id"] for issue in pairing["issues"]
        if issue["code"] == "orphan_repayment_reversal"
    }
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for movement_id in orphan_ids:
        row = by_id[movement_id]
        groups[(int(row["ID_CREDITO"]), _movement_order(row)[0], _clean(row.get("ID_CIERRE_DIARIO")),
                _clean(row.get("ID_USUARIO")), row.get("ID_TIPO_PAGO"))].append(row)

    classified: list[dict[str, Any]] = []
    for key, notes in groups.items():
        loan_id, operation_date, close_id, actor_id, payment_type_id = key
        if not close_id or not actor_id or payment_type_id is None:
            continue
        if any((loan_id, _reversal_signature(note)) not in paired_signatures for note in notes):
            continue
        last_note = max(notes, key=_movement_order)
        candidates = [row for row in rows if int(row["ID_CREDITO"]) == loan_id
                      and _movement_order(row)[0] == operation_date
                      and _clean(row.get("ID_CIERRE_DIARIO")) == close_id
                      and _clean(row.get("ID_USUARIO")) == actor_id
                      and row.get("ID_TIPO_PAGO") == payment_type_id
                      and _movement_order(row) > _movement_order(last_note)
                      and not _is_reversed_repayment(row)
                      and f"{row.get('CODIGO_SISTEMA')}:{_clean(row.get('ID_TRANSACCION'))}"
                      in {"4:00001", "4:00013", "14:00011"}]
        if len(candidates) != 1:
            continue
        repayment = candidates[0]
        if sum((_amount(note.get("MONTO")) for note in notes), Decimal("0")) != _amount(repayment.get("MONTO")):
            continue
        principal = _amount(repayment.get("MONTO_CAPITAL")) - sum(
            (_amount(note.get("MONTO_CAPITAL")) for note in notes), Decimal("0"))
        interest = (_amount(repayment.get("MONTO_INTERES")) + _amount(repayment.get("MONTO_INT_PENDIENTES"))) - sum(
            (_amount(note.get("MONTO_INTERES")) + _amount(note.get("MONTO_INT_PENDIENTES")) for note in notes), Decimal("0"))
        unsupported = sum((_amount(row.get(column)) for row in notes + [repayment]
                           for column in ("MONTO_MORA", "MONTO_OTROS", "MONTO_SEGURO", "MONTO_RECARGOS", "MONTO_CXC",
                                          "MONTO_AHORRO", "MONTO_APORTACION", "MONTO_IVA", "MONTO_IVA_INTERES",
                                          "MONTO_IVA_MORA", "MONTO_IVA_INTERES_PEND", "MONTO_IVA_OTROS")), Decimal("0"))
        if unsupported != 0 or principal <= 0 or interest >= 0 or principal + interest != 0:
            continue
        classified.append({
            "loan_id": loan_id,
            "source_reversal_movement_ids": sorted(_clean(note["ID_MOVIMIENTO_CARTERA"]) for note in notes),
            "source_repayment_movement_id": _clean(repayment["ID_MOVIMIENTO_CARTERA"]),
            "date": _iso_date(repayment.get("FECHA_OPERACION"), "FECHA_OPERACION"),
            "principal": format(principal, "f"), "interest": format(interest, "f"),
            "source_close_id": close_id, "source_actor_id": actor_id,
            "source_payment_type_id": str(payment_type_id),
        })
    movement_ids = {movement_id for item in classified
                    for movement_id in item["source_reversal_movement_ids"] + [item["source_repayment_movement_id"]]}
    return {"classifications": classified, "movement_ids": movement_ids}


def _classify_voided_refinance_attempts(
    loans: list[dict[str, Any]], lifecycles: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove only source-proven net-zero refinance attempts from the effective graph.

    Arissto retains the abandoned successor and both sides of the reversed
    accounting lifecycle.  Those rows are valuable provenance but must not
    make a later valid successor look ambiguous or be replayed into Fineract.
    A partial signature changes nothing, leaving the existing graph quarantine
    to fail closed.
    """
    loan_by_id = {int(row["ID_CREDITO"]): row for row in loans}
    classifications: list[dict[str, Any]] = []
    classified_keys: set[tuple[int, int, str, str]] = set()

    for predecessor_id, predecessor_lifecycle in lifecycles.items():
        predecessor_movements = list(predecessor_lifecycle.get("movements") or [])
        predecessor_pairing = pair_loan_reversals(predecessor_movements)
        predecessor_pairs = {
            (item["original_movement_id"], item["original_transaction"]): item
            for item in predecessor_pairing["pairs"]
        }
        for link in list(predecessor_lifecycle.get("refinance_outgoing") or []):
            if _clean(link.get("payoff_reversed")) != "1":
                continue
            successor_id = int(link["new_credit_id"])
            successor = loan_by_id.get(successor_id)
            successor_lifecycle = lifecycles.get(successor_id)
            if successor is None or successor_lifecycle is None:
                continue

            payoff_movement_id = _clean(link.get("payoff_movement_id"))
            disbursement_movement_id = _clean(link.get("disbursement_movement_id"))
            payoff_pair = predecessor_pairs.get((payoff_movement_id, "4:00019"))
            if payoff_pair is None:
                continue

            successor_movements = list(successor_lifecycle.get("movements") or [])
            successor_pairing = pair_loan_reversals(successor_movements)
            disbursement_pair = next((
                item for item in successor_pairing["pairs"]
                if item["kind"] == "disbursement"
                and item["original_movement_id"] == disbursement_movement_id
                and item["original_transaction"] == "4:00002"
            ), None)
            movement_types = {
                (str(row.get("CODIGO_SISTEMA")), _clean(row.get("ID_TRANSACCION")))
                for row in successor_movements
            }
            zero_balance_fields = (
                "MONTO_DESEMBOLSADO", "ULTIMO_SALDO", "SALDO_INTERES",
                "SALDO_INTERES_PENDIENTE", "SALDO_MORA", "SALDO_SEGURO",
                "SALDO_RECARGOS", "SALDO_CXC", "SALDO_TOTAL",
            )
            complete_signature = (
                disbursement_pair is not None
                and not predecessor_pairing["issues"]
                and not successor_pairing["issues"]
                and len(successor_movements) == 2
                and movement_types == {("4", "00002"), ("4", "00030")}
                and _clean(successor.get("source_state")) == "3"
                and all(_amount(successor.get(field)) == 0 for field in zero_balance_fields)
            )
            if not complete_signature:
                continue

            key = (
                int(predecessor_id), successor_id, payoff_movement_id,
                disbursement_movement_id,
            )
            if key in classified_keys:
                continue
            classified_keys.add(key)
            classification = {
                "classification": "reviewed-voided-refinance-attempt",
                "predecessor_source_key": str(predecessor_id),
                "abandoned_successor_source_key": str(successor_id),
                "payoff_movement_id": payoff_movement_id,
                "payoff_reversal_movement_id": payoff_pair["reversal_movement_id"],
                "disbursement_movement_id": disbursement_movement_id,
                "disbursement_reversal_movement_id": disbursement_pair["reversal_movement_id"],
                "financial_effect": "net-zero-omitted-from-target",
            }
            classifications.append(classification)
            predecessor_lifecycle.setdefault("voided_refinance_attempts", []).append(classification)
            predecessor_lifecycle.setdefault("discarded_voided_refinance_movement_ids", []).extend([
                payoff_movement_id, payoff_pair["reversal_movement_id"],
            ])
            successor_lifecycle.setdefault("voided_refinance_attempts", []).append(classification)
            successor_lifecycle.setdefault("discarded_voided_refinance_movement_ids", []).extend([
                disbursement_movement_id, disbursement_pair["reversal_movement_id"],
            ])
            successor_lifecycle["omit_financial_reconstruction"] = True

    if not classifications:
        return []

    for lifecycle in lifecycles.values():
        outgoing = list(lifecycle.get("refinance_outgoing") or [])
        incoming = list(lifecycle.get("refinance_incoming") or [])
        lifecycle["refinance_outgoing"] = [
            link for link in outgoing
            if (
                int(link["old_credit_id"]), int(link["new_credit_id"]),
                _clean(link.get("payoff_movement_id")),
                _clean(link.get("disbursement_movement_id")),
            ) not in classified_keys
        ]
        lifecycle["refinance_incoming"] = [
            link for link in incoming
            if (
                int(link["old_credit_id"]), int(link["new_credit_id"]),
                _clean(link.get("payoff_movement_id")),
                _clean(link.get("disbursement_movement_id")),
            ) not in classified_keys
        ]
        if lifecycle.get("discarded_voided_refinance_movement_ids"):
            lifecycle["discarded_voided_refinance_movement_ids"] = sorted(set(
                lifecycle["discarded_voided_refinance_movement_ids"]
            ))
    return classifications


def extract_loan_plan_rows(
    settings: Settings, contract: LoanContract, source_keys: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = [canonical_source_key(value) for value in dict.fromkeys(source_keys or [])]
    loan_table = contract.raw["source"]["loan_table"]
    product_table = contract.raw["source"]["product_table"]
    where = ""
    params: tuple[Any, ...] = ()
    if selected:
        where = " WHERE c.ID_CREDITO IN (" + ",".join("?" for _ in selected) + ")"
        params = tuple(selected)
    with source_connection(settings.source) as conn:
        # A Fineract top-up is one atomic loan-to-loan lifecycle. Expand an
        # explicit scope to the complete predecessor/successor chain so a
        # reviewed scoped plan can never migrate only half of a refinance.
        if selected:
            expanded = set(selected)
            while True:
                selected_placeholders = ",".join("?" for _ in expanded)
                links = select_rows(conn, f"""
                    SELECT DISTINCT old.ID_CREDITO AS old_credit_id,newc.ID_CREDITO AS new_credit_id
                    FROM [dbo].[{contract.raw['source']['movement_table']}] old
                    JOIN [dbo].[{contract.raw['source']['liquidation_detail_table']}] d
                      ON d.ID_CRD_MOVIMIENTO=old.ID_CRD_MOVIMIENTO
                    JOIN [dbo].[{contract.raw['source']['liquidation_header_table']}] h
                      ON h.ID_LIQUIDACION=d.ID_LIQUIDACION
                     AND h.ID_EMPRESA=d.ID_EMPRESA AND h.ID_SUCURSAL=d.ID_SUCURSAL
                     AND h.ID_SOLICITUD_CREDITO=d.ID_SOLICITUD_CREDITO
                     AND h.ID_LINEA_CREDITO=d.ID_LINEA_CREDITO AND h.ID_SOCIO=d.ID_SOCIO
                     AND h.ID_PRESTAMO_NO=d.ID_PRESTAMO_NO
                    JOIN [dbo].[{loan_table}] newc
                      ON newc.ID_EMPRESA=h.ID_EMPRESA AND newc.ID_SUCURSAL=h.ID_SUCURSAL
                     AND newc.ID_SOLICITUD_CREDITO=h.ID_SOLICITUD_CREDITO
                     AND newc.ID_LINEA_CREDITO=h.ID_LINEA_CREDITO AND newc.ID_SOCIO=h.ID_SOCIO
                     AND newc.ID_PRESTAMO_NO=h.ID_PRESTAMO_NO
                    WHERE old.CODIGO_SISTEMA=4 AND RTRIM(old.ID_TRANSACCION)='00019'
                      AND (old.ID_CREDITO IN ({selected_placeholders})
                           OR newc.ID_CREDITO IN ({selected_placeholders}))
                """, tuple(expanded) + tuple(expanded))
                discovered = expanded | {
                    int(value) for row in links
                    for value in (row["old_credit_id"], row["new_credit_id"])
                }
                if discovered == expanded:
                    break
                expanded = discovered
            selected = sorted(expanded)
            where = " WHERE c.ID_CREDITO IN (" + ",".join("?" for _ in selected) + ")"
            params = tuple(selected)
        loans = select_rows(conn, f"""
            SELECT c.ID_CREDITO,RTRIM(c.ID_EMPRESA) AS company_id,
                   RTRIM(c.ID_LINEA_CREDITO) AS line_id,RTRIM(c.NO_PRESTAMO) AS account_number,
                   RTRIM(c.ID_SOCIO) AS client_source_key,RTRIM(c.ID_SUCURSAL) AS branch_id,
                   RTRIM(c.ID_ESTADO_CARTERA) AS source_state,RTRIM(c.ID_TIPO_CREDITO) AS loan_type,
                   c.ID_SLU AS slu_id,RTRIM(c.ID_SOLICITUD_CREDITO) AS application_id,
                   RTRIM(c.ID_PROMOTOR) AS promoter_id,RTRIM(c.ID_EJECUTIVO_CUENTA) AS account_executive_id,
                   RTRIM(c.ID_GESTOR_COBRO) AS collections_manager_id,
                   c.MONTO_APROBADO,c.MONTO_DESEMBOLSADO,
                   c.PORC_INTERES_APROBADO,c.PLAZO_APROBADO,c.NO_CUOTAS_APROBADO,c.ID_FRECUENCIA,
                   c.FECHA_OTORGAMIENTO,c.FECHA_PRIMER_PAGO,c.FECHA_VENCIMIENTO,
                   c.SALDO_CAPITAL,c.ULTIMO_SALDO,c.SALDO_INTERES,c.SALDO_INTERES_PENDIENTE,c.SALDO_MORA,
                   c.SALDO_SEGURO,c.SALDO_RECARGOS,c.SALDO_CXC,c.SALDO_TOTAL
            FROM [dbo].[{loan_table}] c{where}
            ORDER BY c.ID_CREDITO
        """, params)
        if selected:
            actual = {int(row["ID_CREDITO"]) for row in loans}
            missing = sorted(set(selected) - actual)
            if missing:
                raise ValueError(f"Selected Arissto loans do not exist: {missing}")
        required_lines = sorted({_clean(row["line_id"]) for row in loans})
        if not required_lines:
            products: list[dict[str, Any]] = []
        else:
            product_where = ",".join("?" for _ in required_lines)
            products = select_rows(conn, f"""
                SELECT RTRIM(l.ID_EMPRESA) AS company_id,RTRIM(l.ID_LINEA_CREDITO) AS line_id,
                       RTRIM(l.ID_TIPO_LINEA) AS line_type,RTRIM(l.CODIGO_LINEA_CREDITO) AS line_code,
                       RTRIM(l.NOMBRE_LINEA) AS line_name,RTRIM(l.ESTADO_LINEA) AS line_state,
                       l.MONTO_INI AS minimum_principal,l.MONTO_FIN AS maximum_principal,
                       l.TASA_INTERES AS default_interest_rate,l.TASA_INTERES_INI AS minimum_interest_rate,
                       l.TASA_INTERES_FIN AS maximum_interest_rate,l.PLAZO_INI AS minimum_term,
                       l.PLAZO_FIN AS maximum_term,l.ID_TIPO_PLAN_PAGO AS schedule_type,
                       l.PRIORIDAD_MORA AS penalty_priority,l.PRIORIDAD_INTERES AS interest_priority,
                       l.PRIORIDAD_CAPITAL AS principal_priority,l.COBRO_MOVIL AS mobile_collection_enabled,
                       l.PROVI_INT_NORMAL AS provision_interest,
                       RTRIM(l.ID_CUENTA_CARGO_PROVI) AS interest_receivable_source_account
                FROM [dbo].[{product_table}] l
                WHERE RTRIM(l.ID_LINEA_CREDITO) IN ({product_where})
                ORDER BY l.ID_LINEA_CREDITO
            """, tuple(required_lines))
    by_line = Counter(_clean(row["line_id"]) for row in products)
    invalid = [line for line in required_lines if by_line[line] != 1]
    if invalid:
        raise RuntimeError(f"Required credit lines are missing or duplicated: {invalid}")
    return loans, products


def extract_loan_lifecycle_rows(
    settings: Settings, contract: LoanContract, loans: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Extract every source fact that a loan plan must freeze before apply."""
    loan_ids = sorted(int(row["ID_CREDITO"]) for row in loans)
    if not loan_ids:
        return {}
    source = contract.raw["source"]
    # SQL Server accepts at most 2,100 parameters per statement. A complete
    # migration currently contains more loans than that, while scoped canaries
    # do not, so freeze the lifecycle in deterministic batches. Keep the batch
    # below half the limit because the refinance query binds the same IDs twice.
    loan_id_batches = [loan_ids[offset:offset + 900] for offset in range(0, len(loan_ids), 900)]
    applications: list[dict[str, Any]] = []
    schedules: list[dict[str, Any]] = []
    movements: list[dict[str, Any]] = []
    charge_details: list[dict[str, Any]] = []
    refinance_links: list[dict[str, Any]] = []
    with source_connection(settings.source) as conn:
        for batch in loan_id_batches:
            placeholders = ",".join("?" for _ in batch)
            applications.extend(select_rows(conn, f"""
            SELECT c.ID_CREDITO,s.FECHA_SOLICITUD,s.FECHA_APROBADO,s.FECHA_RESOLUCION,
                   s.FECHA_DESEMBOLSO,s.FECHA_PACTADA,s.FECHA_FIRMA,
                   s.MONTO_APROBADO,s.MONTO_SOLICITADO,s.CANTIDAD_SOLICITADA,
                   s.NO_CUOTAS_APROBADO,s.PLAZO_APROBADO,s.INTERES_MONTO_APROBADO
            FROM [dbo].[{source['loan_table']}] c
            LEFT JOIN [dbo].[{source['application_table']}] s
              ON s.ID_EMPRESA=c.ID_EMPRESA AND s.ID_SUCURSAL=c.ID_SUCURSAL
             AND s.ID_LINEA_CREDITO=c.ID_LINEA_CREDITO AND s.ID_SOCIO=c.ID_SOCIO
             AND s.ID_SOLICITUD_CREDITO=c.ID_SOLICITUD_CREDITO
            WHERE c.ID_CREDITO IN ({placeholders})
        """, tuple(batch)))
            schedules.extend(select_rows(conn, f"""
            SELECT p.ID_CREDITO,p.NO_CUOTA,p.FECHA_PAGO,p.MONTO_CAPITAL,p.MONTO_INTERES,
                   p.MONTO_OTROS,p.MONTO_APORTACION,p.ID_REESTRUCTURACION,p.CUOTA_DIFERIDA
            FROM [dbo].[{source['schedule_table']}] p
            WHERE p.ID_CREDITO IN ({placeholders})
            ORDER BY p.ID_CREDITO,p.NO_CUOTA,p.FECHA_PAGO,p.ID_PLAN_PAGO
        """, tuple(batch)))
            movements.extend(select_rows(conn, f"""
            SELECT m.ID_CREDITO,m.ID_MOVIMIENTO_CARTERA,m.ID_CRD_MOVIMIENTO,
                   m.CODIGO_SISTEMA,m.ID_TRANSACCION,m.REVERSION,
                   m.FECHA_OPERACION,m.FECHA_VALOR,m.FECHA_PAGO,m.DT_MOVIMIENTO,m.DT_CREO,
                   m.ID_CIERRE_DIARIO,m.ID_USUARIO,m.ID_USR_CREO,m.ID_CAJA,m.ID_PARTIDA,m.ID_TIPO_PAGO,
                   m.MONTO,m.MONTO_PAGADO,m.REINTEGRO_MONTO,
                   m.MONTO_CAPITAL,m.MONTO_INTERES,m.MONTO_INT_PENDIENTES,m.MONTO_MORA,
                   m.MONTO_OTROS,m.MONTO_SEGURO,m.MONTO_RECARGOS,m.MONTO_CXC,m.MONTO_AHORRO,
                   m.MONTO_APORTACION,m.MONTO_IVA,m.MONTO_IVA_INTERES,m.MONTO_IVA_MORA,
                   m.MONTO_IVA_INTERES_PEND,m.MONTO_IVA_OTROS,
                   (SELECT TOP (1) p.SALDO_OTROS FROM dbo.CRD_MOVIMIENTO_PRE_POS p
                    WHERE p.ID_CRD_MOVIMIENTO=m.ID_CRD_MOVIMIENTO AND p.PRE_POS='1')
                       AS LEGACY_OTHER_PRE_BALANCE,
                   (SELECT TOP (1) p.SALDO_OTROS FROM dbo.CRD_MOVIMIENTO_PRE_POS p
                    WHERE p.ID_CRD_MOVIMIENTO=m.ID_CRD_MOVIMIENTO AND p.PRE_POS='2')
                       AS LEGACY_OTHER_POST_BALANCE,
                   (SELECT TOP (1) p.SALDO_PAGADO_OTROS FROM dbo.CRD_MOVIMIENTO_PRE_POS p
                    WHERE p.ID_CRD_MOVIMIENTO=m.ID_CRD_MOVIMIENTO AND p.PRE_POS='1')
                       AS LEGACY_OTHER_PRE_PAID,
                   (SELECT TOP (1) p.SALDO_PAGADO_OTROS FROM dbo.CRD_MOVIMIENTO_PRE_POS p
                    WHERE p.ID_CRD_MOVIMIENTO=m.ID_CRD_MOVIMIENTO AND p.PRE_POS='2')
                       AS LEGACY_OTHER_POST_PAID,
                   (SELECT COUNT(*)
                    FROM dbo.CRD_MOV_CARTERA_CONTABLE x
                    JOIN dbo.CNT_CATALOGO_CUENTAS a
                      ON a.ID_EMPRESA=x.ID_EMPRESA AND a.ID_CUENTA=x.ID_CUENTA
                    WHERE x.ID_MOVIMIENTO_CARTERA=m.ID_MOVIMIENTO_CARTERA
                      AND COALESCE(x.CARGO,0)=0 AND COALESCE(x.ABONO,0)=COALESCE(m.MONTO_OTROS,0)
                      AND RTRIM(a.NOMBRE_CUENTA) IN ('SEGURO DE DEUDA','INTERESES Y OTROS POR COBRAR'))
                       AS LEGACY_OTHER_INSURANCE_LEDGER_COUNT
            FROM [dbo].[{source['movement_table']}] m
            WHERE m.ID_CREDITO IN ({placeholders})
            ORDER BY m.ID_CREDITO,m.FECHA_OPERACION,m.ID_MOVIMIENTO_CARTERA
        """, tuple(batch)))
            charge_details.extend(select_rows(conn, f"""
            SELECT m.ID_CREDITO,d.ID_MOVIMIENTO_CARTERA,d.ID_RECARGO_CARTERA,
                   d.ID_PAGOS,d.MONTO_COBRADO,c.NOMBRE_CARGO,c.ID_TIPO_CARGO
            FROM [dbo].[{source['charge_detail_table']}] d
            JOIN [dbo].[{source['movement_table']}] m
              ON m.ID_MOVIMIENTO_CARTERA=d.ID_MOVIMIENTO_CARTERA
            JOIN [dbo].[{source['charge_table']}] c
              ON c.ID_RECARGO_CARTERA=d.ID_RECARGO_CARTERA
            WHERE m.ID_CREDITO IN ({placeholders})
              AND RTRIM(c.NOMBRE_CARGO)='SEGURO DE DEUDA'
            ORDER BY m.ID_CREDITO,d.ID_MOVIMIENTO_CARTERA,d.ID_RECARGO_CARTERA,d.ID_PAGOS
        """, tuple(batch)))
            refinance_links.extend(select_rows(conn, f"""
            SELECT old.ID_CREDITO AS old_credit_id,
                   old.ID_MOVIMIENTO_CARTERA AS payoff_movement_id,
                   old.FECHA_OPERACION AS payoff_date,old.MONTO AS payoff_amount,
                   old.MONTO_CAPITAL AS payoff_principal,
                   old.MONTO_INTERES + old.MONTO_INT_PENDIENTES AS payoff_interest,
                   old.MONTO_SEGURO AS payoff_fee,
                   old.MONTO_MORA + old.MONTO_RECARGOS AS payoff_penalty,
                   old.REVERSION AS payoff_reversed,
                   newc.ID_CREDITO AS new_credit_id,
                   CASE WHEN oldc.ID_SOCIO=newc.ID_SOCIO THEN 1 ELSE 0 END AS same_owner,
                   newdis.ID_MOVIMIENTO_CARTERA AS disbursement_movement_id
            FROM [dbo].[{source['movement_table']}] old
            JOIN [dbo].[{source['loan_table']}] oldc ON oldc.ID_CREDITO=old.ID_CREDITO
            JOIN [dbo].[{source['liquidation_detail_table']}] d
              ON d.ID_CRD_MOVIMIENTO=old.ID_CRD_MOVIMIENTO
            JOIN [dbo].[{source['liquidation_header_table']}] h
              ON h.ID_LIQUIDACION=d.ID_LIQUIDACION
             AND h.ID_EMPRESA=d.ID_EMPRESA AND h.ID_SUCURSAL=d.ID_SUCURSAL
             AND h.ID_SOLICITUD_CREDITO=d.ID_SOLICITUD_CREDITO
             AND h.ID_LINEA_CREDITO=d.ID_LINEA_CREDITO AND h.ID_SOCIO=d.ID_SOCIO
             AND h.ID_PRESTAMO_NO=d.ID_PRESTAMO_NO
            JOIN [dbo].[{source['loan_table']}] newc
              ON newc.ID_EMPRESA=h.ID_EMPRESA AND newc.ID_SUCURSAL=h.ID_SUCURSAL
             AND newc.ID_SOLICITUD_CREDITO=h.ID_SOLICITUD_CREDITO
             AND newc.ID_LINEA_CREDITO=h.ID_LINEA_CREDITO AND newc.ID_SOCIO=h.ID_SOCIO
             AND newc.ID_PRESTAMO_NO=h.ID_PRESTAMO_NO
            LEFT JOIN [dbo].[{source['movement_table']}] newdis
              ON newdis.ID_CREDITO=newc.ID_CREDITO
             AND newdis.CODIGO_SISTEMA=4 AND RTRIM(newdis.ID_TRANSACCION)='00002'
            WHERE old.CODIGO_SISTEMA=4 AND RTRIM(old.ID_TRANSACCION)='00019'
              AND h.CLASE_LIQ=2
              AND (old.ID_CREDITO IN ({placeholders}) OR newc.ID_CREDITO IN ({placeholders}))
            ORDER BY old.ID_CREDITO,newc.ID_CREDITO
        """, tuple(batch) + tuple(batch)))

    # A refinance whose predecessor and successor fall into different batches
    # is selected once by each batch. Collapse it before attaching the link to
    # either lifecycle so the frozen plan stays stable across batch boundaries.
    unique_refinance_links: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in refinance_links:
        key = (
            row["old_credit_id"], row["new_credit_id"], row["payoff_movement_id"],
            row.get("disbursement_movement_id"),
        )
        unique_refinance_links[key] = row
    refinance_links = list(unique_refinance_links.values())
    insurance_details_by_movement: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for detail in charge_details:
        insurance_details_by_movement[_clean(detail.get("ID_MOVIMIENTO_CARTERA"))].append(detail)
    for link in refinance_links:
        link["payoff_insurance_details"] = insurance_details_by_movement.get(
            _clean(link.get("payoff_movement_id")), []
        )

    result = {loan_id: {
        "application": None, "schedule": [], "movements": [], "charge_details": [],
        "refinance_incoming": [], "refinance_outgoing": [],
    } for loan_id in loan_ids}
    for row in applications:
        result[int(row["ID_CREDITO"])]["application"] = row
    for row in schedules:
        result[int(row["ID_CREDITO"])]["schedule"].append(row)
    for row in movements:
        result[int(row["ID_CREDITO"])]["movements"].append(row)
    for row in charge_details:
        result[int(row["ID_CREDITO"])]["charge_details"].append(row)
    for row in refinance_links:
        old_id, new_id = int(row["old_credit_id"]), int(row["new_credit_id"])
        if old_id in result:
            result[old_id]["refinance_outgoing"].append(row)
        if new_id in result:
            result[new_id]["refinance_incoming"].append(row)
    _classify_voided_refinance_attempts(loans, result)
    return result


def _api_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value.get("pageItems") or value.get("content") or []
    return []


def _find_loan_product(api: FineractApi, external_id: str) -> dict[str, Any] | None:
    try:
        return api.request("GET", f"loanproducts/external-id/{external_id}")
    except FineractError as exc:
        if "(404)" in str(exc):
            return None
        raise


def _resource_id(result: dict[str, Any]) -> int:
    for field in ("resourceId", "entityId", "loanProductId"):
        if result.get(field) is not None:
            return int(result[field])
    raise RuntimeError("Fineract loan-product response has no resource identifier")


@contextmanager
def _postgres_write_connection(url: str):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise RuntimeError("psycopg is required for loan-product provenance writes") from exc
    with psycopg.connect(url, autocommit=False) as conn:
        yield conn


def _upsert_loan_product_crosswalk(
    settings: Settings, contract: LoanContract, action: dict[str, Any], product_id: int,
) -> None:
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for loan-product crosswalk writes")
    line_id = str(action["entity_source_key"])
    company_id = str(action["source_company_id"])
    with _postgres_write_connection(settings.target.pg_url) as conn:
        writer = ControlledSqlWriter(conn, BLOCK)
        with writer.entity_transaction("upsert_loan_product_crosswalk"):
            existing = conn.execute(
                "SELECT loan_product_id,arissto_company_id,arissto_line_id "
                "FROM credesal_loan_product_map WHERE source_system=%s AND source_key=%s FOR UPDATE",
                (SOURCE_SYSTEM, line_id),
            ).fetchone()
            if existing and (
                int(existing[0]) != int(product_id)
                or str(existing[1]) != company_id
                or str(existing[2]) != line_id
            ):
                raise RuntimeError("loan_product_crosswalk_identity_changed_after_plan")
            if existing:
                conn.execute(
                    "UPDATE credesal_loan_product_map SET source_hash=%s,contract_hash=%s,"
                    "mapping_status='ACTIVE',updated_at=CURRENT_TIMESTAMP "
                    "WHERE source_system=%s AND source_key=%s",
                    (action["source_hash"], contract.digest, SOURCE_SYSTEM, line_id),
                )
            else:
                conn.execute(
                    "INSERT INTO credesal_loan_product_map "
                    "(source_system,source_key,source_hash,contract_hash,loan_product_id,"
                    "arissto_company_id,arissto_line_id,mapping_status,updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,'ACTIVE',CURRENT_TIMESTAMP)",
                    (
                        SOURCE_SYSTEM, line_id, action["source_hash"], contract.digest,
                        int(product_id), company_id, line_id,
                    ),
                )


def _plan_scope_inspections(
    settings: Settings, contract: LoanContract, source_keys: list[str] | None,
) -> list[dict[str, Any]]:
    selected = [canonical_source_key(value) for value in dict.fromkeys(source_keys or [])]
    if selected:
        return [
            inspect_loans(settings.source, contract, source_key=source_key, target_pg_url=settings.target.pg_url)
            for source_key in selected
        ]
    return [inspect_loans(settings.source, contract, target_pg_url=settings.target.pg_url)]


def resolve_loan_product_target(
    settings: Settings, contract: LoanContract, source_products: list[dict[str, Any]],
    loans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for loans planning")
    lines = sorted(_clean(row["line_id"]) for row in source_products)
    product_contract = contract.raw["product_contract"]
    shared_codes = set(product_contract["accounting_gl_codes"].values())
    shared_codes.add(product_contract["target_resources"]["debt_insurance_charge"]["income_or_liability_gl"])
    shared_codes.add(product_contract["target_resources"]["mobile_collection_fund_source_gl"])
    portfolio = product_contract["portfolio_account_policy"]["reviewed_primary_gl_by_line"]
    for line_id in lines:
        if line_id not in portfolio:
            raise RuntimeError(f"Credit line {line_id} has no reviewed portfolio GL mapping")
        shared_codes.add(portfolio[line_id])
    loans = loans or []
    client_external_ids = sorted({_clean(row.get("client_source_key")) for row in loans if _clean(row.get("client_source_key"))})
    staff_external_ids = sorted({
        external_id for row in loans for external_id in _loan_staff_external_ids(row).values() if external_id
    })
    loan_external_ids = sorted({
        contract.raw["identity"]["loan_external_id"].format(ID_CREDITO=int(row["ID_CREDITO"]))
        for row in loans
    })
    with postgres_connection(settings.target.pg_url) as conn:
        rows = conn.execute(
            "SELECT id,gl_code,disabled FROM acc_gl_account WHERE gl_code=ANY(%s) ORDER BY gl_code,id",
            (sorted(shared_codes),),
        ).fetchall()
        by_code: dict[str, list[tuple[int, bool]]] = defaultdict(list)
        for identifier, code, disabled in rows:
            by_code[str(code)].append((int(identifier), bool(disabled)))
        invalid = sorted(code for code in shared_codes if len(by_code.get(code, [])) != 1 or by_code[code][0][1])
        if invalid:
            raise RuntimeError(f"Loan product GL codes are missing, duplicated, or disabled: {invalid}")
        gl_ids = {code: values[0][0] for code, values in by_code.items()}
        crosswalk_rows = conn.execute(
            "SELECT source_key,source_hash,contract_hash,loan_product_id,arissto_company_id,arissto_line_id,mapping_status "
            "FROM credesal_loan_product_map WHERE source_system=%s AND source_key=ANY(%s)",
            (SOURCE_SYSTEM, lines),
        ).fetchall()
        client_rows = conn.execute(
            "SELECT external_id,id,status_enum,office_id,activation_date "
            "FROM m_client WHERE external_id=ANY(%s)",
            (client_external_ids,),
        ).fetchall() if client_external_ids else []
        staff_rows = conn.execute(
            "SELECT external_id,id,is_active,office_id FROM m_staff WHERE external_id=ANY(%s)",
            (staff_external_ids,),
        ).fetchall() if staff_external_ids else []
        loan_rows = conn.execute(
            "SELECT external_id,id,product_id,client_id,loan_status_id FROM m_loan WHERE external_id=ANY(%s)",
            (loan_external_ids,),
        ).fetchall() if loan_external_ids else []
    crosswalks = {
        str(row[0]): {
            "source_key": str(row[0]), "source_hash": str(row[1]), "contract_hash": str(row[2]),
            "loan_product_id": int(row[3]), "company_id": str(row[4]), "line_id": str(row[5]),
            "mapping_status": str(row[6]),
        }
        for row in crosswalk_rows
    }
    api = FineractApi(settings.target)
    charge_contract = product_contract["target_resources"]["debt_insurance_charge"]
    matching_charges = []
    for charge in _api_list(api.request("GET", "charges")):
        income = charge.get("incomeOrLiabilityAccount") or charge.get("creditAccount") or {}
        if (
            _enum_id(charge.get("chargeTimeType")) == int(charge_contract["charge_time_type"])
            and _enum_id(charge.get("chargeCalculationType")) == int(charge_contract["calculation_type"])
            and _decimal_text(charge.get("amount")) == _decimal_text(charge_contract["amount"])
            and str(income.get("glCode") or "") == charge_contract["income_or_liability_gl"]
        ):
            matching_charges.append(charge)
    if len(matching_charges) != 1:
        raise RuntimeError(f"Expected one reviewed debt-insurance charge; found {len(matching_charges)}")
    historical_insurance_contract = product_contract["target_resources"]["historical_debt_insurance_charge"]
    historical_insurance_charges = []
    for charge in _api_list(api.request("GET", "charges")):
        income = charge.get("incomeOrLiabilityAccount") or charge.get("creditAccount") or {}
        if (
            charge.get("name") == historical_insurance_contract["name"]
            and not bool(charge.get("penalty"))
            and bool(charge.get("active"))
            and _enum_id(charge.get("chargeTimeType"))
            == int(historical_insurance_contract["charge_time_type"])
            and _enum_id(charge.get("chargeCalculationType"))
            == int(historical_insurance_contract["calculation_type"])
            and str(income.get("glCode") or "")
            == historical_insurance_contract["income_or_liability_gl"]
        ):
            historical_insurance_charges.append(charge)
    if len(historical_insurance_charges) != 1:
        raise RuntimeError(
            "Expected one reviewed historical debt-insurance charge; "
            f"found {len(historical_insurance_charges)}"
        )
    penalty_contract = product_contract["target_resources"]["historical_penalty_charge"]
    penalty_charges = [
        charge for charge in _api_list(api.request("GET", "charges"))
        if charge.get("name") == penalty_contract["name"]
        and bool(charge.get("penalty"))
        and bool(charge.get("active"))
        and _enum_id(charge.get("chargeTimeType")) == int(penalty_contract["charge_time_type"])
        and _enum_id(charge.get("chargeCalculationType")) == int(penalty_contract["calculation_type"])
    ]
    if len(penalty_charges) != 1:
        raise RuntimeError(f"Expected one reviewed historical penalty charge; found {len(penalty_charges)}")
    payment_name = product_contract["target_resources"]["mobile_collection_payment_type"]
    payment_types = [row for row in _api_list(api.request("GET", "paymenttypes")) if row.get("name") == payment_name]
    if len(payment_types) != 1:
        raise RuntimeError(f"Expected one {payment_name!r} payment type; found {len(payment_types)}")
    products = {}
    for line_id in lines:
        external_id = contract.raw["identity"]["product_external_id"].format(ID_LINEA_CREDITO=line_id)
        products[line_id] = _find_loan_product(api, external_id)
    return {
        "resources": {
            "gl_ids": gl_ids,
            "debt_insurance_charge_id": int(matching_charges[0]["id"]),
            "historical_debt_insurance_charge_id": int(historical_insurance_charges[0]["id"]),
            "historical_penalty_charge_id": int(penalty_charges[0]["id"]),
            "mobile_collection_payment_type_id": int(payment_types[0]["id"]),
        },
        "products": products,
        "crosswalks": crosswalks,
        "clients": {
            str(external_id): {
                "id": int(identifier), "status": int(status), "office_id": int(office_id),
                "activation_date": activation_date.isoformat() if activation_date else None,
            }
            for external_id, identifier, status, office_id, activation_date in client_rows
        },
        "staff": {
            str(external_id): {
                "id": int(identifier), "active": bool(active), "office_id": int(office_id),
            }
            for external_id, identifier, active, office_id in staff_rows
        },
        "loans": {
            str(external_id): {
                "id": int(identifier), "product_id": int(product_id), "client_id": int(client_id),
                "status": int(status),
            }
            for external_id, identifier, product_id, client_id, status in loan_rows
        },
    }


def _build_loan_lifecycle_action(
    contract: LoanContract,
    loan: dict[str, Any],
    source_lifecycle: dict[str, Any] | None,
    target: dict[str, Any],
    product_payload: dict[str, Any],
    migration_cutover_date: str | None = None,
) -> dict[str, Any]:
    loan_id = int(loan["ID_CREDITO"])
    line_id = _clean(loan["line_id"])
    application = (source_lifecycle or {}).get("application")
    schedule = list((source_lifecycle or {}).get("schedule") or [])
    movements = list((source_lifecycle or {}).get("movements") or [])
    charge_details = list((source_lifecycle or {}).get("charge_details") or [])
    refinance_incoming = list((source_lifecycle or {}).get("refinance_incoming") or [])
    refinance_outgoing = list((source_lifecycle or {}).get("refinance_outgoing") or [])
    voided_refinance_attempts = list(
        (source_lifecycle or {}).get("voided_refinance_attempts") or []
    )
    discarded_voided_refinance_movement_ids = {
        _clean(value) for value in
        ((source_lifecycle or {}).get("discarded_voided_refinance_movement_ids") or [])
    }
    quarantines: list[str] = []

    source_error = contract.raw["source_error_quarantines"].get(str(loan_id))
    if source_error is not None:
        quarantines.append(
            "reviewed_source_error:"
            f"{source_error['classification']}:replacement-loan-{source_error['replacement_loan_id']}"
        )

    client_external_id = _clean(loan.get("client_source_key"))
    client = target.get("clients", {}).get(client_external_id)
    if client is None:
        quarantines.append("missing_target_client")
    elif int(client.get("status") or -1) != 300:
        quarantines.append("target_client_not_active")

    staff_external_ids = _loan_staff_external_ids(loan)
    staff_by_role = {
        role: target.get("staff", {}).get(external_id) if external_id else None
        for role, external_id in staff_external_ids.items()
    }
    missing_staff_roles = [
        role for role, external_id in staff_external_ids.items() if external_id and staff_by_role[role] is None
    ]
    if missing_staff_roles:
        quarantines.append("missing_target_assigned_staff:" + ",".join(missing_staff_roles))
    if application is None:
        quarantines.append("missing_source_application")
    if (source_lifecycle or {}).get("omit_financial_reconstruction"):
        quarantines.append("reviewed_voided_refinance_attempt_omitted")

    if any(row.get("ID_REESTRUCTURACION") is not None for row in schedule):
        quarantines.append("native_restructure_proof_pending")
    if len(refinance_incoming) > 1:
        consolidation_disbursements = {
            _clean(link.get("disbursement_movement_id")) for link in refinance_incoming
        }
        consolidation_dates = {_iso_date(link.get("payoff_date"), "refinance payoff") for link in refinance_incoming}
        if len(consolidation_disbursements) != 1 or len(consolidation_dates) != 1:
            quarantines.append("multi_predecessor_refinance_inconsistent_liquidation")
    if any(str(link.get("same_owner")) in {"0", "False", "false"} for link in refinance_incoming):
        quarantines.append("cross_client_refinance_requires_authorization")
    if len(refinance_outgoing) > 1:
        quarantines.append("ambiguous_refinance_successor")
    if any(_clean(link.get("payoff_reversed")) == "1" for link in refinance_incoming + refinance_outgoing):
        quarantines.append("reversed_refinance_topup_not_supported")
    if not schedule and any(
        str(row.get("CODIGO_SISTEMA")) == "4" and _clean(row.get("ID_TRANSACCION")) == "00002"
        for row in movements
    ):
        quarantines.append("disbursed_loan_has_no_schedule")

    pairing = pair_loan_reversals(movements)
    component_reallocations = classify_source_exact_component_reallocations(movements, pairing)
    classified_reversal_ids = {
        movement_id for item in component_reallocations["classifications"]
        for movement_id in item["source_reversal_movement_ids"]
    }
    unresolved_pairing_issues = [
        issue for issue in pairing["issues"]
        if issue.get("reversal_movement_id") not in classified_reversal_ids
    ]
    if unresolved_pairing_issues:
        quarantines.extend(sorted({str(issue["code"]) for issue in unresolved_pairing_issues}))
    pair_by_reversal = {item["reversal_movement_id"]: item for item in pairing["pairs"]}
    movement_by_id = {_clean(row.get("ID_MOVIMIENTO_CARTERA")): row for row in movements}
    discarded_manual_adjustments: list[dict[str, Any]] = []
    discarded_manual_adjustment_ids: set[str] = set()
    for pair in pairing["pairs"]:
        original = movement_by_id.get(pair["original_movement_id"])
        reversal = movement_by_id.get(pair["reversal_movement_id"])
        if (
            pair["kind"] == "repayment"
            and pair["original_transaction"] == "4:00013"
            and original is not None and reversal is not None
            and _movement_component_total(original) != _amount(original.get("MONTO"))
            and _movement_component_total(reversal) != _amount(reversal.get("MONTO"))
        ):
            discarded_manual_adjustment_ids.update({
                pair["original_movement_id"], pair["reversal_movement_id"],
            })
            discarded_manual_adjustments.append({
                "original_movement_id": pair["original_movement_id"],
                "reversal_movement_id": pair["reversal_movement_id"],
                "classification": "paired-reversed-manual-adjusted-payment",
            })
    supported = contract.raw["supported_transactions"]
    insurance_details_by_movement: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for detail in charge_details:
        insurance_details_by_movement[_clean(detail.get("ID_MOVIMIENTO_CARTERA"))].append(detail)
    events: list[dict[str, Any]] = []
    refunded_unapplied_movements: list[dict[str, Any]] = []
    for row in sorted(movements, key=_movement_order):
        movement_id = _clean(row["ID_MOVIMIENTO_CARTERA"])
        if (
            movement_id in discarded_manual_adjustment_ids
            or movement_id in discarded_voided_refinance_movement_ids
            or movement_id in component_reallocations["movement_ids"]
        ):
            continue
        code = f"{row.get('CODIGO_SISTEMA')}:{_clean(row.get('ID_TRANSACCION'))}"
        role = supported.get(code)
        if role is None:
            quarantines.append(f"unsupported_transaction:{code}")
            continue
        if role == "refinance-payoff-candidate":
            links = [
                link for link in refinance_outgoing
                if _clean(link.get("payoff_movement_id")) == movement_id
            ]
            if len(links) != 1:
                quarantines.append(f"unresolved_refinance_link:{movement_id}")
                continue
            role = "native-refinance-payoff"
            refinance_link = links[0]
        insurance_details = insurance_details_by_movement.get(movement_id, [])
        insurance_detail_total = sum(
            (_amount(detail.get("MONTO_COBRADO")) for detail in insurance_details), Decimal("0.00")
        )
        movement_insurance = _amount(row.get("MONTO_SEGURO"))
        movement_other = _amount(row.get("MONTO_OTROS"))
        component_total = _movement_component_total(row)
        legacy_other_insurance = _is_verified_legacy_other_insurance(row, role, insurance_details)
        if movement_insurance == 0 and insurance_details:
            component_total += insurance_detail_total
        elif legacy_other_insurance:
            component_total += movement_other
        refund = _movement_refund(row, component_total)
        applied_amount = _amount(row.get("MONTO_PAGADO")) if refund is not None else _amount(row.get("MONTO"))
        if abs(applied_amount - component_total) > Decimal("0.01"):
            quarantines.append(f"component_residual:{movement_id}")
        if any(_amount(row.get(name)) for name in ("MONTO_AHORRO", "MONTO_APORTACION", "MONTO_CXC")):
            quarantines.append(f"unsupported_cross_product_component:{movement_id}")
        if insurance_details:
            if movement_insurance > 0 and abs(movement_insurance - insurance_detail_total) > Decimal("0.01"):
                quarantines.append(f"insurance_detail_mismatch:{movement_id}")
            elif movement_insurance == 0 and abs(movement_other - insurance_detail_total) > Decimal("0.01"):
                quarantines.append(f"legacy_insurance_detail_mismatch:{movement_id}")
        elif movement_insurance > 0 and role in {
            "repayment", "adjusted-repayment", "mobile-collection-repayment"
        }:
            quarantines.append(f"insurance_detail_missing:{movement_id}")
        if refund is not None and applied_amount == 0:
            refunded_unapplied_movements.append({
                "source_movement_id": movement_id,
                "source_transaction": code,
                "gross_amount": format(_amount(row.get("MONTO")), "f"),
                "refund_amount": format(refund, "f"),
                "classification": "fully-refunded-unapplied-collection",
            })
            continue
        fee_allocation = insurance_detail_total if insurance_details else (
            movement_other if legacy_other_insurance else Decimal("0.00")
        )
        event: dict[str, Any] = {
            "source_movement_id": movement_id,
            "external_id": contract.raw["identity"]["movement_external_id"].format(
                ID_MOVIMIENTO_CARTERA=movement_id
            ),
            "source_transaction": code,
            "role": role,
            "date": _iso_date(row.get("FECHA_OPERACION"), "FECHA_OPERACION"),
            "amount": format(applied_amount, "f"),
            "source_reversed": _clean(row.get("REVERSION")) == "1",
            "allocation": {
                "principal": format(_amount(row.get("MONTO_CAPITAL")), "f"),
                "interest": format(
                    _amount(row.get("MONTO_INTERES")) + _amount(row.get("MONTO_INT_PENDIENTES")), "f"
                ),
                "penalty": format(_amount(row.get("MONTO_MORA")) + _amount(row.get("MONTO_RECARGOS")), "f"),
                "fee": format(fee_allocation, "f"),
            },
        }
        if refund is not None:
            event["source_gross_amount"] = format(_amount(row.get("MONTO")), "f")
            event["source_refund_amount"] = format(refund, "f")
            event["amount_classification"] = "source-applied-amount-after-refund"
        if insurance_details:
            event["historical_insurance_charges"] = [
                {
                    "source_charge_id": _clean(detail.get("ID_RECARGO_CARTERA")),
                    "source_payment_id": _clean(detail.get("ID_PAGOS")),
                    "external_id": contract.raw["identity"]["insurance_charge_external_id"].format(
                        ID_RECARGO_CARTERA=_clean(detail.get("ID_RECARGO_CARTERA")),
                        ID_MOVIMIENTO_CARTERA=movement_id,
                        ID_PAGOS=_clean(detail.get("ID_PAGOS")),
                    ),
                    "charge_id": int(target["resources"]["historical_debt_insurance_charge_id"]),
                    "amount": format(_amount(detail.get("MONTO_COBRADO")), "f"),
                    "due_date": _iso_date(row.get("FECHA_OPERACION"), "FECHA_OPERACION"),
                }
                for detail in insurance_details
            ]
        elif legacy_other_insurance:
            event["historical_insurance_charges"] = [{
                "source_charge_id": None,
                "source_payment_id": None,
                "external_id": contract.raw["identity"]["legacy_insurance_charge_external_id"].format(
                    ID_MOVIMIENTO_CARTERA=movement_id,
                ),
                "charge_id": int(target["resources"]["historical_debt_insurance_charge_id"]),
                "amount": format(movement_other, "f"),
                "due_date": _iso_date(row.get("FECHA_OPERACION"), "FECHA_OPERACION"),
                "classification": "legacy-other-balance-confirmed-as-debt-insurance",
            }]
        if _amount(event["allocation"]["penalty"]) > 0:
            event["penalty_charge_external_id"] = f"{event['external_id']}:PENALTY"
            event["penalty_charge_id"] = int(target["resources"]["historical_penalty_charge_id"])
        if role == "native-refinance-payoff":
            successor_id = int(refinance_link["new_credit_id"])
            event.update({
                "successor_source_key": str(successor_id),
                "successor_disbursement_external_id": contract.raw["identity"]["movement_external_id"].format(
                    ID_MOVIMIENTO_CARTERA=_clean(refinance_link["disbursement_movement_id"])
                ),
                "adjustment_external_id": contract.raw["identity"]["refinance_adjustment_external_id"].format(
                    OLD_ID_CREDITO=loan_id, NEW_ID_CREDITO=successor_id
                ),
                "final_adjustment_external_id": contract.raw["identity"]["refinance_final_adjustment_external_id"].format(
                    OLD_ID_CREDITO=loan_id, NEW_ID_CREDITO=successor_id
                ),
            })
        if role in {"repayment-reversal", "disbursement-reversal"}:
            pair = pair_by_reversal.get(movement_id)
            if pair is None:
                quarantines.append(f"unpaired_reversal:{movement_id}")
            else:
                event["original_external_id"] = contract.raw["identity"]["movement_external_id"].format(
                    ID_MOVIMIENTO_CARTERA=pair["original_movement_id"]
                )
        if role == "mobile-collection-repayment":
            event["payment_type_id"] = int(target["resources"]["mobile_collection_payment_type_id"])
        event["event_hash"] = _stable_hash(event)
        events.append(event)

    for reallocation in component_reallocations["classifications"]:
        repayment_id = reallocation["source_repayment_movement_id"]
        event = {
            "source_movement_id": repayment_id,
            "source_reversal_movement_ids": reallocation["source_reversal_movement_ids"],
            "source_repayment_movement_id": repayment_id,
            "external_id": contract.raw["identity"]["component_reallocation_external_id"].format(
                ID_MOVIMIENTO_CARTERA=repayment_id
            ),
            "source_transaction": "ARISSTO:COMPOSITE-REALLOCATION",
            "role": "source-exact-component-reallocation",
            "date": reallocation["date"], "amount": "0.00", "source_reversed": False,
            "allocation": {"principal": reallocation["principal"], "interest": reallocation["interest"],
                           "fee": "0.00", "penalty": "0.00"},
            "source_close_id": reallocation["source_close_id"],
            "source_actor_id": reallocation["source_actor_id"],
            "source_payment_type_id": reallocation["source_payment_type_id"],
        }
        event["event_hash"] = _stable_hash(event)
        events.append(event)
    events.sort(key=lambda event: (event["date"], event["source_movement_id"]))

    # Closed source loans can retain a target residual because Fineract owns the
    # native historical allocation. Keep every cash movement exact and freeze a
    # separate, deterministic native goodwill adjustment policy for that cutover
    # bridge; never disguise the bridge as a customer repayment.
    has_disbursement_reversal = any(event["role"] == "disbursement-reversal" for event in events)
    terminal_adjustment = None
    if (
        _clean(loan.get("source_state")) == "3"
        and _amount(loan.get("SALDO_TOTAL")) == 0
        and not has_disbursement_reversal
        and not refinance_outgoing
    ):
        payoff_candidates = [
            event for event in events
            if event["role"] in {"repayment", "adjusted-repayment", "mobile-collection-repayment"}
            and not event["source_reversed"]
        ]
        if payoff_candidates:
            payoff = payoff_candidates[-1]
            terminal_adjustment = {
                "command": "goodwillCredit",
                "external_id": contract.raw["identity"]["cutover_adjustment_external_id"].format(
                    ID_CREDITO=loan_id
                ),
                "date": payoff["date"],
                "amount_policy": "exact_target_outstanding_after_source_events",
                "maximum_amount": format(_amount(loan.get("MONTO_APROBADO")), "f"),
                "classification": "explicit_migration_cutover_adjustment",
            }

    cutover_insurance_charge = None
    recurring_insurance_charge = None
    source_insurance_outstanding = _amount(loan.get("SALDO_SEGURO"))
    if source_insurance_outstanding > 0 and _clean(loan.get("source_state")) == "1":
        cutover_date = max(
            (event["date"] for event in events),
            default=_iso_date(loan.get("FECHA_OTORGAMIENTO"), "insurance cutover date"),
        )
        cutover_insurance_charge = {
            "external_id": contract.raw["identity"]["insurance_cutover_charge_external_id"].format(
                ID_CREDITO=loan_id
            ),
            "charge_id": int(target["resources"]["historical_debt_insurance_charge_id"]),
            "amount": format(source_insurance_outstanding, "f"),
            "due_date": cutover_date,
            "classification": "source_insurance_cutover_outstanding",
        }
        recurring_insurance_charge = {
            "external_id": contract.raw["identity"]["insurance_recurring_charge_external_id"].format(
                ID_CREDITO=loan_id
            ),
            "charge_id": int(target["resources"]["debt_insurance_charge_id"]),
            "amount": contract.raw["product_contract"]["target_resources"]["debt_insurance_charge"]["amount"],
            "submitted_on_date": migration_cutover_date or date.today().isoformat(),
            "classification": "post_migration_recurring_debt_insurance",
        }

    disbursements = [event for event in events if event["role"] == "disbursement"]
    planned_disbursement_value = None if application is None else (
        application.get("FECHA_DESEMBOLSO") or application.get("FECHA_PACTADA")
        or application.get("FECHA_FIRMA") or application.get("FECHA_APROBADO")
        or application.get("FECHA_RESOLUCION") or application.get("FECHA_SOLICITUD")
    )
    effective_disbursement_date = (
        disbursements[0]["date"] if disbursements else
        _iso_date(
            loan.get("FECHA_OTORGAMIENTO") or planned_disbursement_value,
            "planned disbursement",
        )
    )
    approval_value = None if application is None else (
        application.get("FECHA_APROBADO") or application.get("FECHA_RESOLUCION")
    )
    submitted_value = None if application is None else application.get("FECHA_SOLICITUD")
    approved_date = _iso_date(approval_value or effective_disbursement_date, "approval")
    submitted_date = _iso_date(submitted_value or approved_date, "submission")
    source_submitted_date = submitted_date
    source_approved_date = approved_date
    client_activation_date = (
        _iso_date(client.get("activation_date"), "client activation")
        if client and client.get("activation_date") else None
    )
    legacy_timeline = None
    ordered_movements = sorted(movements, key=_movement_order)
    first_movement = ordered_movements[0] if ordered_movements else None
    first_due_date = (
        min(_iso_date(row["FECHA_PAGO"], "first due") for row in schedule)
        if schedule else None
    )
    first_is_effective_disbursement = bool(first_movement) and (
        str(first_movement.get("CODIGO_SISTEMA") or "").strip() == "4"
        and _clean(first_movement.get("ID_TRANSACCION")) == "00002"
        and _iso_date(first_movement.get("FECHA_OPERACION"), "first movement")
        == effective_disbursement_date
    )
    coherent_financial_start = (
        bool(disbursements)
        and first_is_effective_disbursement
        and first_due_date is not None
        and first_due_date > effective_disbursement_date
    )
    if submitted_date > approved_date:
        quarantines.append("invalid_source_application_date_order")
    elif client_activation_date and submitted_date < client_activation_date:
        coherent_pre_activation_stamp = (
            approved_date < client_activation_date <= effective_disbursement_date
            and coherent_financial_start
        )
        if coherent_pre_activation_stamp:
            legacy_timeline = {
                "source_submitted_on": source_submitted_date,
                "source_approved_on": (
                    _iso_date(application.get("FECHA_APROBADO"), "source approval")
                    if application and application.get("FECHA_APROBADO") else None
                ),
                "source_resolution_on": (
                    _iso_date(application.get("FECHA_RESOLUCION"), "source resolution")
                    if application and application.get("FECHA_RESOLUCION") else None
                ),
                "source_disbursed_on": effective_disbursement_date,
                "effective_approved_on": client_activation_date,
                "classification": "legacy-pre-client-activation-application-stamp",
            }
            submitted_date = client_activation_date
            approved_date = client_activation_date
        elif client_activation_date > effective_disbursement_date:
            quarantines.append("target_client_activation_after_effective_disbursement")
        else:
            quarantines.append("invalid_target_client_activation_date_order")
    elif approved_date > effective_disbursement_date:
        coherent_legacy_timeline = (
            submitted_date <= effective_disbursement_date
            and coherent_financial_start
        )
        if coherent_legacy_timeline:
            legacy_timeline = {
                "source_submitted_on": submitted_date,
                "source_approved_on": (
                    _iso_date(application.get("FECHA_APROBADO"), "source approval")
                    if application and application.get("FECHA_APROBADO") else None
                ),
                "source_resolution_on": (
                    _iso_date(application.get("FECHA_RESOLUCION"), "source resolution")
                    if application and application.get("FECHA_RESOLUCION") else None
                ),
                "source_disbursed_on": effective_disbursement_date,
                "effective_approved_on": effective_disbursement_date,
                "classification": "legacy-late-approval-stamp",
            }
            approved_date = effective_disbursement_date
        else:
            quarantines.append("invalid_source_application_date_order")

    application_installments = None if application is None else application.get("NO_CUOTAS_APROBADO")
    installment_count = len(schedule) or int(
        loan.get("NO_CUOTAS_APROBADO") or application_installments or 0
    )
    try:
        loan_term, repay_every, frequency_type = _frequency_terms(
            int(loan.get("ID_FRECUENCIA") or 0), installment_count
        )
    except ValueError:
        quarantines.append(f"unsupported_frequency:{loan.get('ID_FRECUENCIA')}")
        loan_term, repay_every, frequency_type = 0, 0, 0
    application_rate = None if application is None else application.get("INTERES_MONTO_APROBADO")
    annual_rate = Decimal(str(loan.get("PORC_INTERES_APROBADO") or application_rate or 0))
    periodic_rate = annual_rate / Decimal("12")
    application_principal = None if application is None else (
        application.get("MONTO_APROBADO")
        or application.get("MONTO_SOLICITADO")
        or application.get("CANTIDAD_SOLICITADA")
    )
    principal = _amount(loan.get("MONTO_APROBADO"))
    if principal == 0:
        principal = _amount(loan.get("MONTO_DESEMBOLSADO"))
    if principal == 0:
        principal = _amount(application_principal)
    first_accrual_day_policy = _classify_first_accrual_day(
        loan, schedule, effective_disbursement_date,
    )
    if (
        first_accrual_day_policy is not None
        and first_accrual_day_policy["classification"] == "ambiguous-first-accrual-day-signature"
    ):
        quarantines.append("ambiguous_first_accrual_day_signature")
    application_payload: dict[str, Any] = {
        "clientId": int(client["id"]) if client else None,
        "principal": format(principal, "f"),
        "loanTermFrequency": loan_term,
        "loanTermFrequencyType": frequency_type,
        "numberOfRepayments": installment_count,
        "repaymentEvery": repay_every,
        "repaymentFrequencyType": frequency_type,
        "interestRatePerPeriod": format(periodic_rate.normalize(), "f"),
        "interestRateFrequencyType": int(product_payload["interestRateFrequencyType"]),
        "amortizationType": int(product_payload["amortizationType"]),
        "interestType": int(product_payload["interestType"]),
        "interestCalculationPeriodType": int(product_payload["interestCalculationPeriodType"]),
        "transactionProcessingStrategyCode": product_payload["transactionProcessingStrategyCode"],
        "loanType": "individual",
        "externalId": contract.raw["identity"]["loan_external_id"].format(ID_CREDITO=loan_id),
        "submittedOnDate": submitted_date,
        "expectedDisbursementDate": effective_disbursement_date,
        "dateFormat": "yyyy-MM-dd",
        "locale": "en",
        "charges": [],
        "dimensions": {
            "arisstoCreditLineId": line_id,
            "arisstoCreditTypeId": _clean(loan.get("loan_type")),
            "arisstoSluId": loan.get("slu_id"),
        },
    }
    if (
        first_accrual_day_policy is not None
        and first_accrual_day_policy["classification"] == "legacy-inclusive-first-accrual-day"
    ):
        application_payload["interestChargedFromDate"] = first_accrual_day_policy[
            "interest_charged_from_date"
        ]
        application_payload["daysInYearType"] = first_accrual_day_policy["days_in_year_type"]
    if schedule:
        application_payload["repaymentsStartingFromDate"] = _iso_date(schedule[0]["FECHA_PAGO"], "first due")
    staff_assignment = {
        "client_id": int(client["id"]) if client else None,
        "arissto_company_id": _clean(loan.get("company_id")) or None,
        "arissto_promoter_person_id": _clean(loan.get("promoter_id")) or None,
        "arissto_account_executive_person_id": _clean(loan.get("account_executive_id")) or None,
        "arissto_collections_manager_person_id": _clean(loan.get("collections_manager_id")) or None,
        "promoter_staff_id": int(staff_by_role["promoter"]["id"]) if staff_by_role["promoter"] else None,
        "account_executive_staff_id": int(staff_by_role["account_executive"]["id"])
        if staff_by_role["account_executive"] else None,
        "collections_manager_staff_id": int(staff_by_role["collections_manager"]["id"])
        if staff_by_role["collections_manager"] else None,
    }

    refinance = None
    if refinance_incoming and "multi_predecessor_refinance_inconsistent_liquidation" not in quarantines:
        settlements = []
        for link in sorted(refinance_incoming, key=lambda value: int(value["old_credit_id"])):
            predecessor_id = int(link["old_credit_id"])
            settlement = {
            "predecessor_source_key": str(predecessor_id),
            "predecessor_external_id": contract.raw["identity"]["loan_external_id"].format(
                ID_CREDITO=predecessor_id
            ),
            "payoff_external_id": contract.raw["identity"]["movement_external_id"].format(
                ID_MOVIMIENTO_CARTERA=_clean(link["payoff_movement_id"])
            ),
            "payoff_amount": format(_amount(link["payoff_amount"]), "f"),
            "payoff_date": _iso_date(link["payoff_date"], "refinance payoff"),
            "payoff_allocation": {
                "principal": format(_amount(link.get("payoff_principal")), "f"),
                "interest": format(_amount(link.get("payoff_interest")), "f"),
                "fee": format(_amount(link.get("payoff_fee")), "f"),
                "penalty": format(_amount(link.get("payoff_penalty")), "f"),
            },
            "adjustment_external_id": contract.raw["identity"]["refinance_adjustment_external_id"].format(
                OLD_ID_CREDITO=predecessor_id, NEW_ID_CREDITO=loan_id
            ),
            "final_adjustment_external_id": contract.raw["identity"]["refinance_final_adjustment_external_id"].format(
                OLD_ID_CREDITO=predecessor_id, NEW_ID_CREDITO=loan_id
            ),
            }
            payoff_insurance_details = link.get("payoff_insurance_details") or []
            payoff_fee = _amount(settlement["payoff_allocation"]["fee"])
            payoff_insurance_total = sum(
                (_amount(detail.get("MONTO_COBRADO")) for detail in payoff_insurance_details),
                Decimal("0.00"),
            )
            if abs(payoff_fee - payoff_insurance_total) > Decimal("0.01"):
                quarantines.append(
                    f"refinance_payoff_insurance_detail_mismatch:{_clean(link['payoff_movement_id'])}"
                )
            if payoff_insurance_details:
                settlement["historical_insurance_charges"] = [
                {
                    "source_charge_id": _clean(detail.get("ID_RECARGO_CARTERA")),
                    "source_payment_id": _clean(detail.get("ID_PAGOS")),
                    "external_id": contract.raw["identity"]["insurance_charge_external_id"].format(
                        ID_RECARGO_CARTERA=_clean(detail.get("ID_RECARGO_CARTERA")),
                        ID_MOVIMIENTO_CARTERA=_clean(link["payoff_movement_id"]),
                        ID_PAGOS=_clean(detail.get("ID_PAGOS")),
                    ),
                    "charge_id": int(target["resources"]["historical_debt_insurance_charge_id"]),
                    "amount": format(_amount(detail.get("MONTO_COBRADO")), "f"),
                    "due_date": _iso_date(link["payoff_date"], "payoff_date"),
                }
                for detail in payoff_insurance_details
                ]
            if _amount(settlement["payoff_allocation"]["penalty"]) > 0:
                settlement["penalty_charge_external_id"] = f"{settlement['payoff_external_id']}:PENALTY"
                settlement["penalty_charge_id"] = int(target["resources"]["historical_penalty_charge_id"])
            settlements.append(settlement)
        disbursement_external_id = contract.raw["identity"]["movement_external_id"].format(
            ID_MOVIMIENTO_CARTERA=_clean(refinance_incoming[0]["disbursement_movement_id"])
        )
        for settlement in settlements:
            settlement["transfer_external_id"] = (
                f"{disbursement_external_id}:REFINANCE:{settlement['predecessor_source_key']}"
            )
        refinance = {
            "operation_type": "SINGLE_REFINANCE" if len(settlements) == 1 else "CONSOLIDATION",
            "disbursement_external_id": disbursement_external_id,
            "settlements": settlements,
            "classification": "native_fineract_refinancing_with_source_exact_component_bridge",
        }
        if len(settlements) == 1:
            # Preserve the frozen-plan shape accepted by older recovery and reporting code.
            refinance.update(settlements[0])
            refinance["topup_transfer_external_id"] = settlements[0]["transfer_external_id"]
        application_payload["isTopup"] = True

    normalized_schedule = [{
        "number": int(row["NO_CUOTA"]),
        "due_date": _iso_date(row["FECHA_PAGO"], "FECHA_PAGO"),
        "principal": format(_amount(row.get("MONTO_CAPITAL")), "f"),
        "interest": format(_amount(row.get("MONTO_INTERES")), "f"),
        "other": format(_amount(row.get("MONTO_OTROS")), "f"),
    } for row in schedule]
    schedule_exception = contract.raw["historical_schedule_exceptions"].get(line_id) or {}
    reviewed_schedule_exception = (
        loan_id in {int(value) for value in schedule_exception.get("source_loan_ids", [])}
        and schedule_exception.get("plan_behavior") == "accept-native-schedule"
    )
    reference_only_schedule = (
        contract.raw["historical_reference_only_schedules"].get(str(loan_id)) or {}
    )
    reference_only_classification = reference_only_schedule.get("classification")
    reference_only_signature_matches = True
    if reference_only_classification == "closed-zero-principal-schedule-with-exact-lifecycle":
        lifecycle_principal = sum(
            (_amount(event.get("allocation", {}).get("principal")) for event in events
             if event.get("role") != "disbursement"),
            Decimal("0.00"),
        )
        reference_only_signature_matches = bool(
            _clean(loan.get("source_state")) == "3"
            and principal > 0
            and normalized_schedule
            and all(_amount(period.get("principal")) == 0 for period in normalized_schedule)
            and any(_amount(period.get("interest")) > 0 for period in normalized_schedule)
            and sum(1 for event in events if event.get("role") == "disbursement") == 1
            and sum(1 for event in events if event.get("role") == "native-refinance-payoff") == 1
            and lifecycle_principal == principal
        )
        if not reference_only_signature_matches:
            quarantines.append(
                "historical_reference_schedule_signature_mismatch:"
                "closed-zero-principal-schedule-with-exact-lifecycle"
            )
    elif reference_only_classification == "terminal-zero-core-charge-only-row":
        terminal_period = normalized_schedule[-1] if normalized_schedule else None
        zero_core_periods = [
            period for period in normalized_schedule
            if _amount(period.get("principal")) == 0 and _amount(period.get("interest")) == 0
        ]
        schedule_numbers = [period["number"] for period in normalized_schedule]
        reference_only_signature_matches = bool(
            len(normalized_schedule) >= 2
            and terminal_period is not None
            and zero_core_periods == [terminal_period]
            and _amount(terminal_period.get("other")) > 0
            and _amount(schedule[-1].get("MONTO_APORTACION")) == 0
            and sum(
                (_amount(period.get("principal")) for period in normalized_schedule[:-1]),
                Decimal("0.00"),
            ) == principal
            and schedule_numbers == list(range(1, len(normalized_schedule) + 1))
            and all(
                current["due_date"] > previous["due_date"]
                for previous, current in zip(normalized_schedule, normalized_schedule[1:])
            )
            and all(
                row.get("ID_REESTRUCTURACION") is None
                and int(row.get("CUOTA_DIFERIDA") or 0) == 0
                for row in schedule
            )
        )
        if not reference_only_signature_matches:
            quarantines.append(
                "historical_reference_schedule_signature_mismatch:"
                "terminal-zero-core-charge-only-row"
            )
    reviewed_reference_only_schedule = (
        reference_only_schedule.get("plan_behavior") == "accept-native-schedule"
        and reference_only_signature_matches
    )
    reviewed_native_schedule = reviewed_schedule_exception or reviewed_reference_only_schedule
    if not reviewed_native_schedule and any(
        current["due_date"] <= previous["due_date"]
        for previous, current in zip(normalized_schedule, normalized_schedule[1:])
    ):
        quarantines.append("non_monotonic_source_schedule_dates")
    lifecycle = {
        "application_payload": application_payload,
        "staff_assignment": staff_assignment,
        "legacy_timeline": legacy_timeline,
        "first_accrual_day_policy": first_accrual_day_policy,
        "approval_payload": {
            "approvedOnDate": approved_date,
            "approvedLoanAmount": format(principal, "f"),
            "expectedDisbursementDate": effective_disbursement_date,
            "dateFormat": "yyyy-MM-dd",
            "locale": "en",
        },
        "schedule": normalized_schedule,
        "schedule_reconciliation_policy": (
            "reviewed-manual-adjustment" if reviewed_schedule_exception
            else "historical-reference-only" if reviewed_reference_only_schedule
            else "exact-source-schedule"
        ),
        "schedule_writer": (
            None if reviewed_native_schedule else "fineract-variable-installments-v1"
        ),
        "events": events,
        "discarded_manual_adjustments": discarded_manual_adjustments,
        "voided_refinance_attempts": voided_refinance_attempts,
        "discarded_voided_refinance_movement_ids": sorted(
            discarded_voided_refinance_movement_ids
        ),
        "financial_reconstruction_omitted": bool(
            (source_lifecycle or {}).get("omit_financial_reconstruction")
        ),
        "refunded_unapplied_movements": refunded_unapplied_movements,
        "refinance": refinance,
        "terminal_adjustment": terminal_adjustment,
        "cutover_insurance_charge": cutover_insurance_charge,
        "recurring_insurance_charge": recurring_insurance_charge,
        "expected": {
            "source_state": _clean(loan.get("source_state")),
            # SALDO_CAPITAL mirrors capital paid for active loans; ULTIMO_SALDO is the
            # remaining principal.  SALDO_TOTAL adds current interest/fees/penalties.
            "principal_balance": format(_amount(loan.get("ULTIMO_SALDO")), "f"),
            "interest_balance": format(
                _amount(loan.get("SALDO_INTERES")) + _amount(loan.get("SALDO_INTERES_PENDIENTE")), "f"
            ),
            "penalty_balance": format(_amount(loan.get("SALDO_MORA")) + _amount(loan.get("SALDO_RECARGOS")), "f"),
            "fee_balance": format(_amount(loan.get("SALDO_SEGURO")), "f"),
            "total_outstanding": format(_amount(loan.get("SALDO_TOTAL")), "f"),
        },
        "reversal_pairing": {key: pairing[key] for key in (
            "pair_count", "repayment_pair_count", "disbursement_pair_count", "issues"
        )},
    }
    return {
        "lifecycle": lifecycle,
        "lifecycle_hash": _stable_hash(lifecycle),
        "quarantine_reasons": sorted(set(quarantines)),
        "client_external_id": client_external_id,
        "staff_external_ids": staff_external_ids,
    }


def _proof_external_id(namespace: str, external_id: str) -> str:
    value = f"PROOF:{namespace}:{external_id}"
    if len(value) > 100:
        raise ValueError(f"Namespaced loan proof external ID exceeds 100 characters: {external_id}")
    return value


def _proof_namespace_lifecycle(lifecycle: dict[str, Any], namespace: str) -> dict[str, Any]:
    result = json.loads(json.dumps(lifecycle))
    result["application_payload"]["externalId"] = _proof_external_id(
        namespace, result["application_payload"]["externalId"]
    )
    for event in result["events"]:
        for field, value in list(event.items()):
            if field.endswith("external_id") and value:
                event[field] = _proof_external_id(namespace, value)
        for charge in event.get("historical_insurance_charges") or []:
            charge["external_id"] = _proof_external_id(namespace, charge["external_id"])
    refinance = result.get("refinance")
    if refinance:
        for field in (
            "predecessor_external_id", "payoff_external_id", "disbursement_external_id",
            "topup_transfer_external_id", "adjustment_external_id", "final_adjustment_external_id",
            "penalty_charge_external_id",
        ):
            if refinance.get(field):
                refinance[field] = _proof_external_id(namespace, refinance[field])
        for charge in refinance.get("historical_insurance_charges") or []:
            charge["external_id"] = _proof_external_id(namespace, charge["external_id"])
        for settlement in refinance.get("settlements") or []:
            for field in (
                "predecessor_external_id", "payoff_external_id", "transfer_external_id",
                "adjustment_external_id", "final_adjustment_external_id", "penalty_charge_external_id",
            ):
                if settlement.get(field):
                    settlement[field] = _proof_external_id(namespace, settlement[field])
            for charge in settlement.get("historical_insurance_charges") or []:
                charge["external_id"] = _proof_external_id(namespace, charge["external_id"])
    adjustment = result.get("terminal_adjustment")
    if adjustment and adjustment.get("external_id"):
        adjustment["external_id"] = _proof_external_id(namespace, adjustment["external_id"])
    cutover_charge = result.get("cutover_insurance_charge")
    if cutover_charge and cutover_charge.get("external_id"):
        cutover_charge["external_id"] = _proof_external_id(namespace, cutover_charge["external_id"])
    recurring_charge = result.get("recurring_insurance_charge")
    if recurring_charge and recurring_charge.get("external_id"):
        recurring_charge["external_id"] = _proof_external_id(namespace, recurring_charge["external_id"])
    return result


def compose_loan_plan(
    settings: Settings,
    contract: LoanContract,
    loans: list[dict[str, Any]],
    source_products: list[dict[str, Any]],
    target: dict[str, Any],
    readiness_blockers: list[str] | None = None,
    source_keys: list[str] | None = None,
    source_lifecycles: dict[int, dict[str, Any]] | None = None,
    proof_namespace: str | None = None,
    migration_cutover_date: str | None = None,
) -> dict[str, Any]:
    migration_cutover_date = migration_cutover_date or date.today().isoformat()
    by_line = {_clean(row["line_id"]): row for row in source_products}
    product_actions: list[dict[str, Any]] = []
    conflicts: list[str] = []
    counts: Counter[str] = Counter()
    for line_id in sorted(by_line):
        source_product = by_line[line_id]
        action_key = product_action_key(line_id)
        source_hash = _stable_hash(source_product)
        payload = build_loan_product_payload(contract, source_product, target["resources"])
        existing = target["products"].get(line_id)
        crosswalk = target["crosswalks"].get(line_id)
        mismatch: list[dict[str, Any]] = []
        reason: str | None = None
        if existing is None:
            action = "create-product"
            if crosswalk is not None:
                action, reason = "conflict-product", "crosswalk_points_to_missing_external_id_product"
        else:
            mismatch = loan_product_conflicts(payload, existing)
            if mismatch:
                fields = {row["field"] for row in mismatch}
                migration_enablement_fields = {
                    "canUseForTopup", "allowVariableInstallments", "minimumGap", "maximumGap",
                    # Widening the rate ceiling is migration-safe: it admits
                    # frozen historical contracts without repricing existing
                    # or future loans. The reviewed envelope is still fixed in
                    # config/loans.json and compared exactly after the update.
                    "maxInterestRatePerPeriod",
                }
                numbering_code_backfill = all(
                    row["field"] != "numberingCode" or row["actual"] in (None, "")
                    for row in mismatch
                )
                if fields.issubset(migration_enablement_fields | {"numberingCode"}) and numbering_code_backfill:
                    action, reason = "update-product", None
                else:
                    action, reason = "conflict-product", "external_id_product_contract_differs"
            elif crosswalk is not None and int(crosswalk["loan_product_id"]) != int(existing["id"]):
                action, reason = "conflict-product", "crosswalk_product_identity_differs"
            elif crosswalk is not None and (
                crosswalk["source_key"] != line_id or crosswalk["line_id"] != line_id
                or crosswalk["company_id"] != _clean(source_product["company_id"])
            ):
                action, reason = "conflict-product", "crosswalk_source_identity_differs"
            else:
                action = "unchanged-product"
        repair_crosswalk = bool(
            action == "unchanged-product" and (
                crosswalk is None or crosswalk["source_hash"] != source_hash
                or crosswalk["contract_hash"] != contract.digest
            )
        )
        item = {
            "source_key": action_key,
            "entity_type": "product",
            "entity_source_key": line_id,
            "source_company_id": _clean(source_product["company_id"]),
            "action": action,
            "depends_on": [],
            "source_hash": source_hash,
            "external_id": payload["externalId"],
            "target_id": int(existing["id"]) if existing else None,
            "payload": payload,
            "payload_hash": _stable_hash(loan_product_contract_view(payload, planned=True)),
            "crosswalk": {
                "exists": crosswalk is not None,
                "repair_after_product_resolution": repair_crosswalk or action == "create-product",
            },
        }
        if reason:
            item["reason"] = reason
            item["conflicts"] = mismatch
            conflicts.append(f"{action_key}:{reason}")
        product_actions.append(item)
        counts[action] += 1

    product_payloads = {
        action["entity_source_key"]: action["payload"] for action in product_actions
    }
    loan_actions: list[dict[str, Any]] = []
    for loan in sorted(loans, key=lambda row: int(row["ID_CREDITO"])):
        loan_id = int(loan["ID_CREDITO"])
        line_id = _clean(loan["line_id"])
        dependency = product_action_key(line_id)
        external_id = contract.raw["identity"]["loan_external_id"].format(ID_CREDITO=loan_id)
        raw_lifecycle = (source_lifecycles or {}).get(loan_id)
        if raw_lifecycle is not None:
            lifecycle_action = _build_loan_lifecycle_action(
                contract, loan, raw_lifecycle, target, product_payloads[line_id], migration_cutover_date
            )
        else:
            lifecycle_action = {
                "lifecycle": None, "lifecycle_hash": None,
                "quarantine_reasons": ["missing_frozen_source_lifecycle"] if source_lifecycles is not None else [],
                "client_external_id": _clean(loan.get("client_source_key")), "staff_external_id": None,
            }
        # The source guard must describe Arissto, not the local-only proof
        # identity overlay applied to the frozen writer payload below.
        source_hash = _stable_hash({"header": loan, "lifecycle": lifecycle_action["lifecycle"]})
        if proof_namespace and lifecycle_action.get("lifecycle"):
            external_id = _proof_external_id(proof_namespace, external_id)
            lifecycle_action["lifecycle"] = _proof_namespace_lifecycle(
                lifecycle_action["lifecycle"], proof_namespace
            )
            lifecycle_action["lifecycle_hash"] = _stable_hash(lifecycle_action["lifecycle"])
        existing_loan = target.get("loans", {}).get(external_id)
        action_name = "quarantine-loan" if lifecycle_action["quarantine_reasons"] else (
            "recover-loan" if existing_loan else "create-loan"
        )
        refinance_dependencies = []
        if lifecycle_action.get("lifecycle") and lifecycle_action["lifecycle"].get("refinance"):
            refinance_dependencies = [
                loan_action_key(int(settlement["predecessor_source_key"]))
                for settlement in lifecycle_action["lifecycle"]["refinance"]["settlements"]
            ]
        action = {
            "source_key": loan_action_key(loan_id),
            "entity_type": "loan",
            "entity_source_key": str(loan_id),
            "action": action_name,
            "depends_on": [dependency] + refinance_dependencies,
            "product_action_key": dependency,
            "product_line_id": line_id,
            "external_id": external_id,
            "source_hash": source_hash,
            "target_id": int(existing_loan["id"]) if existing_loan else None,
            **lifecycle_action,
        }
        loan_actions.append(action)
        counts[action_name] += 1
    actions = product_actions + loan_actions
    action_keys = [action["source_key"] for action in actions]
    if len(action_keys) != len(set(action_keys)):
        raise RuntimeError("Loan plan action keys are not unique after namespacing")
    blockers = sorted(set(readiness_blockers or []) | set(conflicts))
    return {
        "version": 1,
        "block": BLOCK,
        "target_fingerprint": settings.target.fingerprint,
        "source_fingerprint": source_fingerprint(settings.source),
        "contract_hash": contract.digest,
        "migration_cutover_date": migration_cutover_date,
        "applicable": not blockers,
        "planner_phase": "product-aware-sequential-actions",
        "writer_registered": source_lifecycles is not None,
        "product_writer_registered": True,
        "loan_writer_registered": source_lifecycles is not None,
        "scope": {
            "mode": "explicit-source-keys" if source_keys else "full-block",
            "requested_source_keys": source_keys or [],
            "loan_count": len(loans),
            "required_product_lines": sorted(by_line),
            "proof_namespace": proof_namespace,
        },
        "counts": dict(counts),
        "readiness_blockers": blockers,
        "actions": actions,
    }


def build_loan_plan(
    settings: Settings, state: State, contract: LoanContract, source_keys: list[str] | None = None,
    proof_namespace: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if proof_namespace:
        if settings.target.name != "local":
            raise ValueError("Loan proof namespaces are restricted to the local target")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,23}", proof_namespace):
            raise ValueError("Loan proof namespace must match [a-z0-9][a-z0-9-]{0,23}")
    inspections = _plan_scope_inspections(settings, contract, source_keys)
    loans, source_products = extract_loan_plan_rows(settings, contract, source_keys)
    source_lifecycles = extract_loan_lifecycle_rows(settings, contract, loans)
    target = resolve_loan_product_target(settings, contract, source_products, loans)
    blockers = sorted({
        blocker
        for inspection in inspections
        for blocker in list(inspection["source_blockers"]) + list(inspection["target_blockers"])
    })
    document = compose_loan_plan(
        settings, contract, loans, source_products, target, blockers, source_keys, source_lifecycles,
        proof_namespace,
    )
    document["schema_signature"] = inspections[0]["schema_signature"]
    document["target_schema_signature"] = inspections[0]["target_schema_signature"]
    plan_id = state.save_plan(
        settings.target.fingerprint, BLOCK, document["source_fingerprint"], contract.digest, document
    )
    return plan_id, document


def _loan_apply_guard(
    settings: Settings, state: State, contract: LoanContract, plan_id: str,
    production_confirmation: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK:
        raise RuntimeError("Plan is not a loans plan")
    if plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Loans plan belongs to a different target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source):
        raise RuntimeError("Loans plan source fingerprint changed")
    if plan["contract_hash"] != contract.digest:
        raise RuntimeError("Loans contract changed after planning")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    document = plan["document"]
    if not document.get("applicable"):
        raise RuntimeError("Loans plan is not applicable")
    if not document.get("product_writer_registered"):
        raise RuntimeError("Loans plan predates the Gate 4 product writer; create a new plan")
    if not document.get("loan_writer_registered"):
        raise RuntimeError("Loans plan predates the Gate 4 lifecycle writer; create a new plan")
    requested = document.get("scope", {}).get("requested_source_keys") or None
    inspections = _plan_scope_inspections(settings, contract, requested)
    blockers = sorted({
        blocker
        for inspection in inspections
        for blocker in list(inspection["source_blockers"]) + list(inspection["target_blockers"])
    })
    if blockers:
        raise RuntimeError(f"Loans destination/source readiness changed: {blockers}")
    if any(inspection["schema_signature"] != document.get("schema_signature") for inspection in inspections):
        raise RuntimeError("Loans source schema changed after planning")
    if any(
        inspection["target_schema_signature"] != document.get("target_schema_signature")
        for inspection in inspections
    ):
        raise RuntimeError("Loans destination schema changed after planning")

    loans, source_products = extract_loan_plan_rows(settings, contract, requested)
    source_lifecycles = extract_loan_lifecycle_rows(settings, contract, loans)
    target = resolve_loan_product_target(settings, contract, source_products, loans)
    products_by_line = {_clean(row["line_id"]): row for row in source_products}
    loans_by_id = {str(int(row["ID_CREDITO"])): row for row in loans}
    for action in document["actions"]:
        if action["entity_type"] == "product":
            current = products_by_line.get(action["entity_source_key"])
            if current is None or _stable_hash(current) != action["source_hash"]:
                raise RuntimeError(f"Loan product source changed after planning: {action['source_key']}")
            rebuilt = build_loan_product_payload(contract, current, target["resources"])
            if _stable_hash(loan_product_contract_view(rebuilt, planned=True)) != action["payload_hash"]:
                raise RuntimeError(f"Loan product target resources changed after planning: {action['source_key']}")
            crosswalk = target["crosswalks"].get(action["entity_source_key"])
            target_product = target["products"].get(action["entity_source_key"])
            if crosswalk is not None and (
                crosswalk["source_key"] != action["entity_source_key"]
                or crosswalk["line_id"] != action["entity_source_key"]
                or crosswalk["company_id"] != action["source_company_id"]
                or target_product is None
                or int(crosswalk["loan_product_id"]) != int(target_product["id"])
            ):
                raise RuntimeError(f"Loan product crosswalk changed after planning: {action['source_key']}")
        elif action["entity_type"] == "loan":
            current = loans_by_id.get(action["entity_source_key"])
            line_id = _clean(current.get("line_id")) if current else ""
            source_product = products_by_line.get(line_id)
            rebuilt_lifecycle = _build_loan_lifecycle_action(
                contract, current, source_lifecycles.get(int(action["entity_source_key"])), target,
                build_loan_product_payload(contract, source_product, target["resources"]),
                document.get("migration_cutover_date"),
            ) if current and source_product else None
            current_hash = _stable_hash({
                "header": current, "lifecycle": rebuilt_lifecycle["lifecycle"]
            }) if rebuilt_lifecycle else None
            if current is None or current_hash != action["source_hash"]:
                raise RuntimeError(f"Loan source changed after planning: {action['source_key']}")
        else:
            raise RuntimeError(f"Unsupported loans plan action type: {action.get('entity_type')}")
    return plan, target


def _selected_loan_actions(
    actions: list[dict[str, Any]], only_keys: set[str] | None,
) -> list[dict[str, Any]]:
    if only_keys is None:
        return actions
    by_key = {action["source_key"]: action for action in actions}
    unknown = sorted(set(only_keys) - set(by_key))
    if unknown:
        raise RuntimeError(f"Retry keys are absent from the loans plan: {unknown}")
    explicitly_selected = set(only_keys)
    selected = set(explicitly_selected)
    for key in list(selected):
        selected.update(by_key[key].get("depends_on", []))
    # A product explicitly selected because it failed must bring its dependent
    # loans into the retry. A healthy product added only as a prerequisite of a
    # failed loan must not expand that retry to every loan sharing the product.
    selected_products = {
        key for key in explicitly_selected if by_key[key]["entity_type"] == "product"
    }
    selected.update(
        action["source_key"] for action in actions
        if selected_products.intersection(action.get("depends_on", []))
    )
    return [action for action in actions if action["source_key"] in selected]


def loan_retry_keys(actions: list[dict[str, Any]], run_items: list[dict[str, Any]]) -> set[str]:
    """Select failures, crash gaps, and only their blocked dependants."""
    journal = {item["source_key"]: item["status"] for item in run_items}
    selected = {
        action["source_key"] for action in actions
        if action["source_key"] not in journal or journal[action["source_key"]] == "failed"
    }
    # A blocked action was never attempted. Retry it only when the failed or
    # unjournaled dependency that blocked it is part of this retry, rather than
    # re-evaluating every independent quarantine/dependency chain in the plan.
    changed = True
    while changed:
        changed = False
        for action in actions:
            key = action["source_key"]
            if journal.get(key) != "blocked" or key in selected:
                continue
            if selected.intersection(action.get("depends_on", [])):
                selected.add(key)
                changed = True
    return selected


def _resolve_or_create_loan_product(
    api: FineractApi, action: dict[str, Any], planned_existing: dict[str, Any] | None,
) -> tuple[int, bool]:
    existing = _find_loan_product(api, action["external_id"])
    if existing is None and planned_existing is not None:
        # The target changed after the guard read; never recreate a product that
        # was present under this deterministic identity when the plan ran.
        raise RuntimeError("loan_product_disappeared_after_plan")
    recovered = existing is not None and action["action"] == "create-product"
    if existing is None:
        if action["action"] != "create-product":
            raise RuntimeError("unchanged_loan_product_missing_at_apply")
        result = api.request(
            "POST", "loanproducts", action["payload"],
            idempotency_key=action["external_id"],
        )
        _resource_id(result)
        existing = _find_loan_product(api, action["external_id"])
        if existing is None:
            raise RuntimeError("created_loan_product_not_recoverable_by_external_id")
    elif action["action"] == "update-product":
        capability_payload = {
            key: action["payload"][key]
            for key in (
                "canUseForTopup", "allowVariableInstallments", "minimumGap", "maximumGap",
                "maxInterestRatePerPeriod", "numberingCode",
            )
            if key in action["payload"]
        }
        capability_payload["locale"] = action["payload"].get("locale", "en")
        api.request(
            "PUT", f"loanproducts/{int(existing['id'])}", capability_payload,
            idempotency_key=_attempt_idempotency_key(
                f"{action['external_id']}:capabilities",
                _stable_hash(capability_payload),
            ),
        )
        existing = _find_loan_product(api, action["external_id"])
        if existing is None:
            raise RuntimeError("updated_loan_product_not_recoverable_by_external_id")
    conflicts = loan_product_conflicts(action["payload"], existing)
    if conflicts:
        raise RuntimeError("loan_product_contract_changed_after_plan")
    return int(existing["id"]), recovered


def _find_loan(api: FineractApi, external_id: str) -> dict[str, Any] | None:
    try:
        return api.request("GET", f"loans/external-id/{external_id}", query={"associations": "all"})
    except FineractError as exc:
        if "(404)" in str(exc):
            return None
        raise


def _loan_transactions(loan: dict[str, Any]) -> list[dict[str, Any]]:
    return list(loan.get("transactions") or [])


def _transaction_by_external_id(loan: dict[str, Any], external_id: str) -> dict[str, Any] | None:
    matches = [row for row in _loan_transactions(loan) if row.get("externalId") == external_id]
    if len(matches) > 1:
        raise RuntimeError(f"duplicate_target_loan_transaction_external_id:{external_id}")
    return matches[0] if matches else None


def _loan_charge_by_external_id(loan: dict[str, Any], external_id: str) -> dict[str, Any] | None:
    matches = [row for row in list(loan.get("charges") or []) if row.get("externalId") == external_id]
    if len(matches) > 1:
        raise RuntimeError(f"duplicate_target_loan_charge_external_id:{external_id}")
    return matches[0] if matches else None


def _ensure_source_penalty_charge(
    api: FineractApi, loan: dict[str, Any], event: dict[str, Any], attempt_key: str | None,
) -> dict[str, Any]:
    external_id = event["penalty_charge_external_id"]
    existing = _loan_charge_by_external_id(loan, external_id)
    if existing is None:
        api.request("POST", f"loans/{int(loan['id'])}/charges", {
            "chargeId": int(event["penalty_charge_id"]),
            "amount": event["allocation"]["penalty"],
            "dueDate": event["date"],
            "externalId": external_id,
            "dateFormat": "yyyy-MM-dd", "locale": "en",
        }, idempotency_key=_attempt_idempotency_key(external_id, attempt_key))
        loan = api.request("GET", f"loans/{int(loan['id'])}", query={"associations": "all"})
        existing = _loan_charge_by_external_id(loan, external_id)
    if existing is None:
        raise RuntimeError(f"created_penalty_charge_not_recoverable:{external_id}")
    if _amount(existing.get("amount")) != _amount(event["allocation"]["penalty"]):
        raise RuntimeError(f"existing_penalty_charge_amount_mismatch:{external_id}")
    return loan


def _ensure_source_insurance_charges(
    api: FineractApi, loan: dict[str, Any], event: dict[str, Any], attempt_key: str | None,
) -> dict[str, Any]:
    for charge in event.get("historical_insurance_charges") or []:
        external_id = charge["external_id"]
        existing = _loan_charge_by_external_id(loan, external_id)
        if existing is None:
            api.request(
                "POST",
                f"loans/{int(loan['id'])}/charges",
                {
                    "chargeId": int(charge["charge_id"]),
                    "amount": charge["amount"],
                    "dueDate": charge["due_date"],
                    "externalId": external_id,
                    "dateFormat": "yyyy-MM-dd",
                    "locale": "en",
                },
                idempotency_key=_attempt_idempotency_key(external_id, attempt_key),
            )
            loan = api.request("GET", f"loans/{int(loan['id'])}", query={"associations": "all"})
            existing = _loan_charge_by_external_id(loan, external_id)
        if existing is None:
            raise RuntimeError(f"created_insurance_charge_not_recoverable:{external_id}")
        if _amount(existing.get("amount")) != _amount(charge["amount"]):
            raise RuntimeError(f"existing_insurance_charge_amount_mismatch:{external_id}")
    return loan


def _ensure_recurring_insurance_charge(
    api: FineractApi, loan: dict[str, Any], charge: dict[str, Any], attempt_key: str | None,
) -> dict[str, Any]:
    external_id = charge["external_id"]
    existing = _loan_charge_by_external_id(loan, external_id)
    if existing is None:
        api.request(
            "POST",
            f"loans/{int(loan['id'])}/charges",
            {
                "chargeId": int(charge["charge_id"]),
                "amount": charge["amount"],
                "submittedOnDate": charge["submitted_on_date"],
                "externalId": external_id,
                "dateFormat": "yyyy-MM-dd",
                "locale": "en",
            },
            idempotency_key=_attempt_idempotency_key(external_id, attempt_key),
        )
        loan = api.request("GET", f"loans/{int(loan['id'])}", query={"associations": "all"})
        existing = _loan_charge_by_external_id(loan, external_id)
    if existing is None:
        raise RuntimeError(f"created_recurring_insurance_charge_not_recoverable:{external_id}")
    existing_percentage = existing.get("amountOrPercentage", existing.get("percentage"))
    if _amount(existing_percentage) != _amount(charge["amount"]):
        raise RuntimeError(f"existing_recurring_insurance_percentage_mismatch:{external_id}")
    if _iso_date(existing.get("submittedOnDate"), "recurring insurance submittedOnDate") != charge["submitted_on_date"]:
        raise RuntimeError(f"existing_recurring_insurance_cutover_mismatch:{external_id}")
    return loan


def _refinance_component_bridge(
    prepayment: dict[str, Any], source_allocation: dict[str, Any],
    allow_interest_shortfall: bool = False,
) -> dict[str, Decimal]:
    target_allocation = {
        "principal": _amount(prepayment.get("principalPortion")),
        "interest": _amount(prepayment.get("interestPortion")),
        "fee": _amount(prepayment.get("feeChargesPortion")),
        "penalty": _amount(prepayment.get("penaltyChargesPortion")),
    }
    bridge = {
        component: target_allocation[component] - _amount(source_allocation[component])
        for component in ("principal", "interest", "fee", "penalty")
    }
    shortfalls = {
        component: amount for component, amount in bridge.items()
        if amount < Decimal("-0.01")
    }
    if allow_interest_shortfall:
        shortfalls.pop("interest", None)
    if shortfalls:
        raise RuntimeError(f"refinance_target_components_below_source:{shortfalls}")
    return {
        component: max(amount, Decimal("0.00"))
        for component, amount in bridge.items()
    }


def _loan_outstanding_allocation(loan: dict[str, Any]) -> dict[str, Decimal]:
    summary = loan.get("summary") or {}
    allocation = {
        "principal": _amount(summary.get("principalOutstanding")),
        "interest": _amount(summary.get("interestOutstanding")),
        "fee": _amount(summary.get("feeChargesOutstanding")),
        "penalty": _amount(summary.get("penaltyChargesOutstanding")),
    }
    component_total = sum(allocation.values(), Decimal("0.00"))
    total_outstanding = _amount(summary.get("totalOutstanding"))
    if abs(component_total - total_outstanding) > Decimal("0.01"):
        raise RuntimeError(
            f"refinance_residual_components_mismatch:{component_total}:{total_outstanding}"
        )
    return allocation


def _find_loan_transaction(
    api: FineractApi, loan: dict[str, Any], external_id: str,
) -> dict[str, Any] | None:
    transaction = _transaction_by_external_id(loan, external_id)
    if transaction is not None:
        return transaction
    try:
        return api.request(
            "GET", f"loans/{int(loan['id'])}/transactions/external-id/{external_id}"
        )
    except FineractError as exc:
        if "(404)" in str(exc):
            return None
        raise


def _ensure_refinance_prepayment_ready(
    api: FineractApi, predecessor: dict[str, Any], refinance: dict[str, Any],
    attempt_key: str | None,
) -> dict[str, Any]:
    if refinance.get("historical_insurance_charges"):
        predecessor = _ensure_source_insurance_charges(
            api, predecessor,
            {"historical_insurance_charges": refinance["historical_insurance_charges"]},
            attempt_key,
        )
    if _amount(refinance["payoff_allocation"]["penalty"]) > 0:
        predecessor = _ensure_source_penalty_charge(api, predecessor, {
            "penalty_charge_external_id": refinance["penalty_charge_external_id"],
            "penalty_charge_id": refinance["penalty_charge_id"],
            "allocation": {"penalty": refinance["payoff_allocation"]["penalty"]},
            "date": refinance["payoff_date"],
        }, attempt_key)
    prepayment = api.request(
        "GET", f"loans/{int(predecessor['id'])}/transactions/template",
        query={
            "command": "prepayLoan", "transactionDate": refinance["payoff_date"],
            "dateFormat": "yyyy-MM-dd", "locale": "en",
        },
    )
    payoff = _amount(refinance["payoff_amount"])
    source_allocation = refinance["payoff_allocation"]
    component_bridge = _refinance_component_bridge(
        prepayment, source_allocation, allow_interest_shortfall=True,
    )
    bridge = sum(component_bridge.values(), Decimal("0.00"))
    prepayment_amount = _amount(prepayment.get("amount"))
    missing_source_interest = max(
        _amount(source_allocation["interest"])
        - _amount(prepayment.get("interestPortion")),
        Decimal("0.00"),
    )
    existing_bridge = _find_loan_transaction(
        api, predecessor, refinance["adjustment_external_id"]
    )

    if existing_bridge is not None:
        if bridge > Decimal("0.01") or abs(
            prepayment_amount + missing_source_interest - payoff
        ) > Decimal("0.01"):
            raise RuntimeError(
                f"refinance_existing_component_bridge_did_not_converge:"
                f"{prepayment_amount}:{payoff}:{bridge}"
            )
        return predecessor

    if abs(
        prepayment_amount + missing_source_interest - payoff - bridge
    ) > Decimal("0.01"):
        raise RuntimeError(
            f"refinance_prepayment_component_total_mismatch:"
            f"{prepayment_amount}:{payoff}:{bridge}"
        )
    if bridge <= Decimal("0.01"):
        return predecessor

    api.request(
        "POST", f"loans/{int(predecessor['id'])}/transactions", {
            "transactionDate": refinance["payoff_date"],
            "transactionAmount": format(bridge, "f"),
            "externalId": refinance["adjustment_external_id"],
            "principalPortion": format(component_bridge["principal"], "f"),
            "interestPortion": format(component_bridge["interest"], "f"),
            "feeChargesPortion": format(component_bridge["fee"], "f"),
            "penaltyChargesPortion": format(component_bridge["penalty"], "f"),
            "dateFormat": "yyyy-MM-dd", "locale": "en",
        }, query={"command": "sourceExactGoodwillCredit"},
        idempotency_key=_attempt_idempotency_key(
            refinance["adjustment_external_id"], attempt_key
        ),
    )
    predecessor = _find_loan(api, refinance["predecessor_external_id"])
    if predecessor is None:
        raise RuntimeError("refinance_predecessor_missing_after_component_bridge")
    existing_bridge = _find_loan_transaction(
        api, predecessor, refinance["adjustment_external_id"]
    )
    if existing_bridge is None:
        raise RuntimeError("refinance_component_bridge_not_recoverable")
    _verify_repayment_allocation(existing_bridge, {
        "allocation": {key: format(value, "f") for key, value in component_bridge.items()}
    })

    refreshed_prepayment = api.request(
        "GET", f"loans/{int(predecessor['id'])}/transactions/template",
        query={
            "command": "prepayLoan", "transactionDate": refinance["payoff_date"],
            "dateFormat": "yyyy-MM-dd", "locale": "en",
        },
    )
    remaining_bridge = _refinance_component_bridge(
        refreshed_prepayment, source_allocation, allow_interest_shortfall=True,
    )
    remaining_total = sum(remaining_bridge.values(), Decimal("0.00"))
    refreshed_amount = _amount(refreshed_prepayment.get("amount"))
    remaining_source_interest = max(
        _amount(source_allocation["interest"])
        - _amount(refreshed_prepayment.get("interestPortion")),
        Decimal("0.00"),
    )
    if remaining_total > Decimal("0.01") or abs(
        refreshed_amount + remaining_source_interest - payoff
    ) > Decimal("0.01"):
        raise RuntimeError(
            f"refinance_component_bridge_did_not_converge:"
            f"{refreshed_amount}:{payoff}:{remaining_total}"
        )
    return predecessor


def _target_transaction_is_reversed(transaction: dict[str, Any]) -> bool:
    return bool(
        transaction.get("manuallyReversed")
        or transaction.get("reversed")
        or transaction.get("reversedOnDate")
    )


def _verify_repayment_allocation(transaction: dict[str, Any], event: dict[str, Any]) -> None:
    expected = event["allocation"]
    actual = {
        "principal": _amount(transaction.get("principalPortion")),
        "interest": _amount(transaction.get("interestPortion")),
        "penalty": _amount(transaction.get("penaltyChargesPortion")),
        "fee": _amount(transaction.get("feeChargesPortion")),
    }
    mismatches = {
        field: {"source": value, "target": format(actual[field], "f")}
        for field, value in expected.items() if _amount(value) != actual[field]
    }
    if mismatches:
        raise RuntimeError(f"loan_repayment_allocation_mismatch:{json.dumps(mismatches, sort_keys=True)}")


def _loan_schedule_differences(
    source_schedule: list[dict[str, Any]], repayment_schedule: dict[str, Any],
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    repayment_periods = [
        period for period in repayment_schedule.get("periods", [])
        if period.get("period") not in (None, 0) and period.get("dueDate") is not None
    ]
    # Fineract can append a charge-only period when a historical penalty is
    # assessed after contractual maturity. It has no original principal or
    # interest and is not an Arissto repayment-plan installment. Penalty
    # identity, amount, paid-by allocation, and accounting are reconciled
    # independently, so including that extension here creates a false
    # contractual schedule-count mismatch.
    target_periods = [
        period for period in repayment_periods
        if _amount(period.get("principalOriginalDue", period.get("principalDue")))
        or _amount(period.get("interestOriginalDue", period.get("interestDue")))
    ]
    if source_schedule and not repayment_schedule:
        differences.append({"kind": "schedule_missing"})
    if source_schedule and repayment_schedule and len(source_schedule) != len(target_periods):
        differences.append({
            "kind": "schedule_installment_count",
            "source": len(source_schedule),
            "target": len(target_periods),
        })
    for source_period, target_period in zip(source_schedule, target_periods):
        installment = int(source_period["number"])
        fields = {
            "schedule_installment_number": (
                installment, int(target_period.get("period") or 0)
            ),
            "schedule_due_date": (
                source_period["due_date"],
                _iso_date(target_period.get("dueDate"), "target schedule due date"),
            ),
            "schedule_principal": (
                _amount(source_period.get("principal")),
                _amount(target_period.get("principalOriginalDue", target_period.get("principalDue"))),
            ),
            "schedule_interest": (
                _amount(source_period.get("interest")),
                _amount(target_period.get("interestOriginalDue", target_period.get("interestDue"))),
            ),
        }
        for kind, (source_value, target_value) in fields.items():
            if source_value != target_value:
                differences.append({
                    "kind": kind,
                    "installment": installment,
                    "source": str(source_value),
                    "target": str(target_value),
                })
    schedule_totals = {
        "schedule_principal_total": (
            sum((_amount(row.get("principal")) for row in source_schedule), Decimal("0.00")),
            sum((
                _amount(row.get("principalOriginalDue", row.get("principalDue")))
                for row in target_periods
            ), Decimal("0.00")),
        ),
        "schedule_interest_total": (
            sum((_amount(row.get("interest")) for row in source_schedule), Decimal("0.00")),
            sum((
                _amount(row.get("interestOriginalDue", row.get("interestDue")))
                for row in target_periods
            ), Decimal("0.00")),
        ),
    }
    for kind, (source_amount, target_amount) in schedule_totals.items():
        if source_schedule and repayment_schedule and source_amount != target_amount:
            differences.append({
                "kind": kind,
                "source": format(source_amount, "f"),
                "target": format(target_amount, "f"),
            })
    return differences


def _source_exact_schedule_variations(
    source_schedule: list[dict[str, Any]], repayment_schedule: dict[str, Any],
) -> dict[str, Any]:
    """Translate a native pending schedule into source-exact term variations.

    Equal-installment declining-balance products accept an installment total,
    not a principal override. Freezing source principal + interest for every
    installment except the last makes Fineract derive the source principal from
    its native interest calculation; Fineract owns the final residual period.
    The preview must prove every resulting component before anything is posted.
    """
    target_periods = [
        period for period in repayment_schedule.get("periods", [])
        if period.get("period") not in (None, 0) and period.get("dueDate") is not None
    ]
    if len(source_schedule) != len(target_periods):
        raise RuntimeError(
            "loan_source_exact_schedule_installment_count_unsupported:"
            f"{len(source_schedule)}:{len(target_periods)}"
        )
    modifications: list[dict[str, Any]] = []
    last_index = len(source_schedule) - 1
    for index, (source_period, target_period) in enumerate(zip(source_schedule, target_periods)):
        target_due_date = _iso_date(target_period.get("dueDate"), "target schedule due date")
        source_due_date = source_period["due_date"]
        modification: dict[str, Any] = {"dueDate": target_due_date}
        if source_due_date != target_due_date:
            modification["modifiedDueDate"] = source_due_date
        # Fineract forbids amount variations on the final installment because it
        # must settle the remaining principal. Strict preview validates it too.
        if index != last_index:
            installment_amount = (
                _amount(source_period.get("principal"))
                + _amount(source_period.get("interest"))
            )
            modification["installmentAmount"] = format(installment_amount, "f")
        if len(modification) > 1:
            modifications.append(modification)
    return {
        "locale": "en", "dateFormat": "yyyy-MM-dd",
        "exceptions": {"modifiedinstallments": modifications},
    }


def _loan_schedule_calculation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove write-only Credesal metadata unsupported by Fineract's calculator."""
    return {
        key: value for key, value in payload.items()
        if key not in {"dimensions", "externalId"}
    }


def _ensure_source_exact_pending_schedule(
    api: FineractApi, loan: dict[str, Any], action: dict[str, Any], attempt_key: str | None,
) -> dict[str, Any]:
    lifecycle = action["lifecycle"]
    source_schedule = lifecycle.get("schedule") or []
    repayment_schedule = loan.get("repaymentSchedule") or {}
    differences = _loan_schedule_differences(source_schedule, repayment_schedule)
    if not differences:
        return loan
    status = int((loan.get("status") or {}).get("id") or -1)
    if status != 100:
        raise RuntimeError(
            "existing_loan_schedule_mismatch_before_continue:"
            f"{json.dumps(differences, sort_keys=True)}"
        )
    variations = _source_exact_schedule_variations(source_schedule, repayment_schedule)
    if not variations["exceptions"]["modifiedinstallments"]:
        raise RuntimeError(
            "loan_source_exact_schedule_has_no_supported_variations:"
            f"{json.dumps(differences, sort_keys=True)}"
        )
    loan_id = int(loan["id"])
    preview = api.calculate_variable_loan_schedule(loan_id, variations)
    preview_differences = _loan_schedule_differences(source_schedule, preview)
    if preview_differences:
        raise RuntimeError(
            "loan_source_exact_schedule_preview_mismatch:"
            f"{json.dumps(preview_differences, sort_keys=True)}"
        )
    api.add_loan_schedule_variations(
        loan_id, variations,
        _attempt_idempotency_key(f"{action['external_id']}:source-schedule", attempt_key),
    )
    refreshed = _find_loan(api, action["external_id"])
    if refreshed is None:
        raise RuntimeError("loan_missing_after_source_schedule_write")
    persisted_differences = _loan_schedule_differences(
        source_schedule, refreshed.get("repaymentSchedule") or {},
    )
    if persisted_differences:
        raise RuntimeError(
            "loan_source_exact_schedule_persisted_mismatch:"
            f"{json.dumps(persisted_differences, sort_keys=True)}"
        )
    return refreshed


def _verify_transaction_amount(transaction: dict[str, Any], event: dict[str, Any]) -> None:
    if _amount(transaction.get("amount")) != _amount(event["amount"]):
        raise RuntimeError(
            f"loan_transaction_amount_mismatch:{event['external_id']}:"
            f"{transaction.get('amount')}:{event['amount']}"
        )


def _validate_existing_loan(
    loan: dict[str, Any], action: dict[str, Any], product_id: int,
) -> None:
    payload = action["lifecycle"]["application_payload"]
    conflicts = []
    if int(loan.get("loanProductId") or (loan.get("loanProduct") or {}).get("id") or -1) != int(product_id):
        conflicts.append("product")
    if int(loan.get("clientId") or (loan.get("client") or {}).get("id") or -1) != int(payload["clientId"]):
        conflicts.append("client")
    if _amount(loan.get("principal")) != _amount(payload["principal"]):
        conflicts.append("principal")
    if conflicts:
        raise RuntimeError(f"existing_loan_contract_conflict:{','.join(conflicts)}")


def _generic_datatable_row(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    headers = value.get("columnHeaders") or []
    rows = value.get("data") or []
    row = rows[0].get("row") if rows and isinstance(rows[0], dict) else None
    if not headers or row is None:
        return None
    return {
        str(header.get("columnName")): row[index]
        for index, header in enumerate(headers)
        if isinstance(header, dict) and header.get("columnName") and index < len(row)
    }


def _loan_staff_assignment_differences(expected: dict[str, Any], actual: dict[str, Any] | None) -> list[str]:
    if actual is None:
        return ["row_missing"]
    differences = []
    for column, expected_value in expected.items():
        actual_value = actual.get(column)
        if column.endswith("_staff_id") or column == "client_id":
            actual_value = int(actual_value) if actual_value not in (None, "") else None
        else:
            actual_value = _clean(actual_value) or None
        if actual_value != expected_value:
            differences.append(column)
    return differences


def _loan_legacy_timeline_differences(expected: dict[str, Any], actual: dict[str, Any] | None) -> list[str]:
    if actual is None:
        return ["row_missing"]
    differences = []
    for column, expected_value in expected.items():
        actual_value = actual.get(column)
        if column.endswith("_on"):
            actual_value = _iso_date(actual_value, column) if actual_value not in (None, "") else None
        else:
            actual_value = _clean(actual_value) or None
        if actual_value != expected_value:
            differences.append(column)
    return differences


def _attempt_idempotency_key(base: str, attempt_key: str | None) -> str:
    """Let a reviewed retry escape a cached failed command without weakening identity recovery."""
    if not attempt_key:
        return base if len(base) <= 50 else f"ars:{hashlib.sha256(base.encode()).hexdigest()[:46]}"
    base_digest = hashlib.sha256(base.encode()).hexdigest()[:32]
    attempt_digest = hashlib.sha256(attempt_key.encode()).hexdigest()[:12]
    return f"ars:{base_digest}:{attempt_digest}"


def _refinance_settlements(refinance: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not refinance:
        return []
    if refinance.get("settlements"):
        return list(refinance["settlements"])
    return [refinance]


def _apply_loan_lifecycle(
    api: FineractApi, action: dict[str, Any], product_id: int, attempt_key: str | None = None,
) -> tuple[int, bool]:
    lifecycle = action.get("lifecycle")
    if not lifecycle:
        raise RuntimeError("loan_plan_missing_frozen_lifecycle")
    if (
        lifecycle.get("schedule_reconciliation_policy") == "exact-source-schedule"
        and lifecycle.get("schedule_writer") != "fineract-variable-installments-v1"
    ):
        raise RuntimeError("loan_plan_predates_source_exact_schedule_writer")
    existing = _find_loan(api, action["external_id"])
    recovered = existing is not None
    if existing is None:
        payload = {key: value for key, value in lifecycle["application_payload"].items() if value is not None}
        payload["productId"] = int(product_id)
        refinance = lifecycle.get("refinance")
        predecessors = []
        if refinance:
            for settlement in _refinance_settlements(refinance):
                predecessor = _find_loan(api, settlement["predecessor_external_id"])
                if predecessor is None:
                    raise RuntimeError(
                        f"refinance_predecessor_missing:{settlement['predecessor_external_id']}"
                    )
                if int(predecessor.get("clientId") or (predecessor.get("client") or {}).get("id") or -1) != int(payload["clientId"]):
                    raise RuntimeError("refinance_predecessor_client_mismatch")
                predecessors.append((predecessor, settlement))
            payload["loanIdsToClose"] = sorted(int(predecessor["id"]) for predecessor, _ in predecessors)
            if len(predecessors) == 1:
                payload["loanIdToClose"] = int(predecessors[0][0]["id"])
            # The non-posting calculator validates loanIdToClose with the same
            # refinancing rule as application creation. Prepare every predecessor
            # before preview so replay-created interest and fees cannot reject
            # an otherwise source-valid successor amount.
            for predecessor, settlement in predecessors:
                _ensure_refinance_prepayment_ready(api, predecessor, settlement, attempt_key)
        if lifecycle.get("schedule_reconciliation_policy") == "exact-source-schedule":
            calculated_schedule = api.calculate_loan_schedule(
                _loan_schedule_calculation_payload(payload)
            )
            schedule_differences = _loan_schedule_differences(
                lifecycle.get("schedule") or [], calculated_schedule,
            )
            if schedule_differences:
                # Amount/date variations require a persisted pending application.
                # Prove that the native base schedule has the same row cardinality
                # before creating that non-posting application.
                _source_exact_schedule_variations(
                    lifecycle.get("schedule") or [], calculated_schedule,
                )
        result = api.request(
            "POST", "loans", payload,
            idempotency_key=_attempt_idempotency_key(action["external_id"], attempt_key),
        )
        loan_id = int(result.get("loanId") or result.get("resourceId"))
        existing = _find_loan(api, action["external_id"])
        if existing is None or int(existing["id"]) != loan_id:
            raise RuntimeError("created_loan_not_recoverable_by_external_id")
    loan_id = int(existing["id"])
    _validate_existing_loan(existing, action, product_id)
    staff_assignment = lifecycle.get("staff_assignment")
    if staff_assignment is None:
        raise RuntimeError("loan_plan_predates_staff_assignment_writer")
    api.upsert_datatable(
        "credesal_loan_staff_assignment", str(loan_id), datatable_api_payload(staff_assignment)
    )
    legacy_timeline = lifecycle.get("legacy_timeline")
    if legacy_timeline is not None:
        api.upsert_datatable(
            "credesal_loan_legacy_timeline", str(loan_id), datatable_api_payload(legacy_timeline)
        )
    if lifecycle.get("schedule_reconciliation_policy") == "exact-source-schedule":
        existing = _ensure_source_exact_pending_schedule(api, existing, action, attempt_key)

    status = int((existing.get("status") or {}).get("id") or -1)
    if status == 100:
        api.request(
            "POST", f"loans/{loan_id}", lifecycle["approval_payload"],
            query={"command": "approve"},
            idempotency_key=_attempt_idempotency_key(f"{action['external_id']}:approve", attempt_key),
        )

    reversed_disbursements = {
        event["original_external_id"] for event in lifecycle["events"]
        if event["role"] == "disbursement-reversal" and event.get("original_external_id")
    }
    refinance = lifecycle.get("refinance")
    loan = existing
    for event in lifecycle["events"]:
        loan = api.request("GET", f"loans/{loan_id}", query={"associations": "all"})
        role = event["role"]
        existing_transaction = _transaction_by_external_id(loan, event["external_id"])
        if role == "disbursement" and refinance and event["external_id"] == refinance["disbursement_external_id"]:
            topup_disbursements = [
                row for row in _loan_transactions(loan)
                if _enum_id(row.get("type")) == 1 and not _target_transaction_is_reversed(row)
            ]
            if existing_transaction is None and topup_disbursements:
                existing_transaction = topup_disbursements[0]
        if role == "disbursement" and event["external_id"] in reversed_disbursements:
            reversed_transaction = _find_loan_transaction(api, loan, event["external_id"])
            if reversed_transaction is not None and _target_transaction_is_reversed(reversed_transaction):
                continue
        if role == "disbursement":
            if existing_transaction is None:
                status = int((loan.get("status") or {}).get("id") or -1)
                if status != 200:
                    raise RuntimeError(f"loan_not_approved_before_disbursement:{status}")
                if refinance and event["external_id"] == refinance["disbursement_external_id"]:
                    for settlement in _refinance_settlements(refinance):
                        predecessor = _find_loan(api, settlement["predecessor_external_id"])
                        if predecessor is None:
                            raise RuntimeError("refinance_predecessor_missing_before_disbursement")
                        predecessor_status = int((predecessor.get("status") or {}).get("id") or -1)
                        if predecessor_status != 300:
                            raise RuntimeError(f"refinance_predecessor_not_active:{predecessor_status}")
                        _ensure_refinance_prepayment_ready(api, predecessor, settlement, attempt_key)
                disbursement_payload = {
                    "actualDisbursementDate": event["date"], "transactionAmount": event["amount"],
                    "dateFormat": "yyyy-MM-dd", "locale": "en",
                }
                disbursement_command = "disburse"
                disbursement_payload["externalId"] = event["external_id"]
                if refinance and event["external_id"] == refinance["disbursement_external_id"]:
                    disbursement_command = "sourceExactRefinancingDisburse"
                    settlements = _refinance_settlements(refinance)
                    disbursement_payload["refinancingSettlements"] = [{
                        "loanIdToClose": int(_find_loan(api, settlement["predecessor_external_id"])["id"]),
                        "repaymentExternalId": settlement["payoff_external_id"],
                        "transferExternalId": settlement.get("transfer_external_id")
                        or settlement["topup_transfer_external_id"],
                        "principalPortion": settlement["payoff_allocation"]["principal"],
                        "interestPortion": settlement["payoff_allocation"]["interest"],
                        "feeChargesPortion": settlement["payoff_allocation"]["fee"],
                        "penaltyChargesPortion": settlement["payoff_allocation"]["penalty"],
                        "locale": "en",
                    } for settlement in settlements]
                api.request("POST", f"loans/{loan_id}", disbursement_payload, query={"command": disbursement_command},
                    idempotency_key=_attempt_idempotency_key(event["external_id"], attempt_key))
            if refinance and event["external_id"] == refinance["disbursement_external_id"]:
                for settlement in _refinance_settlements(refinance):
                    predecessor = _find_loan(api, settlement["predecessor_external_id"])
                    if predecessor is None:
                        raise RuntimeError("refinance_predecessor_missing_after_disbursement")
                    predecessor_status = int((predecessor.get("status") or {}).get("id") or -1)
                    residual = _amount((predecessor.get("summary") or {}).get("totalOutstanding"))
                    final_bridge = _find_loan_transaction(
                        api, predecessor, settlement["final_adjustment_external_id"]
                    )
                    if residual > Decimal("0.01"):
                        residual_allocation = _loan_outstanding_allocation(predecessor)
                        if final_bridge is None:
                            api.request(
                                "POST", f"loans/{int(predecessor['id'])}/transactions", {
                                "transactionDate": settlement["payoff_date"],
                                "transactionAmount": format(residual, "f"),
                                "externalId": settlement["final_adjustment_external_id"],
                                "principalPortion": format(residual_allocation["principal"], "f"),
                                "interestPortion": format(residual_allocation["interest"], "f"),
                                "feeChargesPortion": format(residual_allocation["fee"], "f"),
                                "penaltyChargesPortion": format(residual_allocation["penalty"], "f"),
                                "dateFormat": "yyyy-MM-dd", "locale": "en",
                            }, query={"command": "sourceExactGoodwillCredit"},
                            idempotency_key=_attempt_idempotency_key(
                                settlement["final_adjustment_external_id"], attempt_key
                            ),
                        )
                        predecessor = _find_loan(api, settlement["predecessor_external_id"])
                        final_bridge = _find_loan_transaction(
                            api, predecessor, settlement["final_adjustment_external_id"]
                        )
                        if final_bridge is None:
                            raise RuntimeError("refinance_final_component_bridge_not_recoverable")
                        _verify_repayment_allocation(final_bridge, {
                            "allocation": {
                                key: format(value, "f") for key, value in residual_allocation.items()
                            }
                        })
                        predecessor_status = int((predecessor.get("status") or {}).get("id") or -1)
                        residual = _amount((predecessor.get("summary") or {}).get("totalOutstanding"))
                    if predecessor_status not in {600, 601, 602, 700} or residual > Decimal("0.01"):
                        raise RuntimeError(
                            f"refinance_predecessor_not_closed_after_refinancing:{predecessor_status}:{residual}"
                        )
        elif role == "source-exact-component-reallocation":
            if existing_transaction is None:
                status = int((loan.get("status") or {}).get("id") or -1)
                if status != 300:
                    raise RuntimeError(f"loan_not_active_before_component_reallocation:{status}")
                reversal_ids = ",".join(event["source_reversal_movement_ids"])
                payload = {
                    "transactionDate": event["date"], "transactionAmount": "0.00",
                    "externalId": event["external_id"], "dateFormat": "yyyy-MM-dd", "locale": "en",
                    "principalPortion": event["allocation"]["principal"],
                    "interestPortion": event["allocation"]["interest"],
                    "feeChargesPortion": "0.00", "penaltyChargesPortion": "0.00",
                    "sourceSystem": SOURCE_SYSTEM, "sourceReversalMovementIds": reversal_ids,
                    "sourceRepaymentMovementId": event["source_repayment_movement_id"],
                    "note": (f"Arissto component reallocation: reversals {reversal_ids}; "
                             f"repayment {event['source_repayment_movement_id']}"),
                }
                api.request(
                    "POST", f"loans/{loan_id}/transactions", payload,
                    query={"command": "sourceExactComponentReallocation"},
                    idempotency_key=_attempt_idempotency_key(event["external_id"], attempt_key),
                )
                loan = api.request("GET", f"loans/{loan_id}", query={"associations": "all"})
                existing_transaction = _transaction_by_external_id(loan, event["external_id"])
                if existing_transaction is None:
                    raise RuntimeError(f"created_component_reallocation_not_recoverable:{event['external_id']}")
            _verify_transaction_amount(existing_transaction, event)
            _verify_repayment_allocation(existing_transaction, event)
        elif role in {"repayment", "adjusted-repayment", "mobile-collection-repayment"}:
            if existing_transaction is None:
                status = int((loan.get("status") or {}).get("id") or -1)
                if status != 300:
                    raise RuntimeError(f"loan_not_active_before_repayment:{status}")
                if _amount(event["allocation"]["penalty"]) > 0:
                    loan = _ensure_source_penalty_charge(api, loan, event, attempt_key)
                if _amount(event["allocation"]["fee"]) > 0:
                    loan = _ensure_source_insurance_charges(api, loan, event, attempt_key)
                payload = {
                    "transactionDate": event["date"], "transactionAmount": event["amount"],
                    "externalId": event["external_id"], "dateFormat": "yyyy-MM-dd", "locale": "en",
                    "principalPortion": event["allocation"]["principal"],
                    "interestPortion": event["allocation"]["interest"],
                    "feeChargesPortion": event["allocation"]["fee"],
                    "penaltyChargesPortion": event["allocation"]["penalty"],
                }
                if event.get("payment_type_id") is not None:
                    payload["paymentTypeId"] = int(event["payment_type_id"])
                api.request(
                    "POST", f"loans/{loan_id}/transactions", payload,
                    query={"command": "sourceExactRepayment"},
                    idempotency_key=_attempt_idempotency_key(event["external_id"], attempt_key),
                )
                loan = api.request("GET", f"loans/{loan_id}", query={"associations": "all"})
                existing_transaction = _transaction_by_external_id(loan, event["external_id"])
                if existing_transaction is None:
                    raise RuntimeError(f"created_repayment_not_recoverable:{event['external_id']}")
            _verify_transaction_amount(existing_transaction, event)
            _verify_repayment_allocation(existing_transaction, event)
        elif role == "native-refinance-payoff":
            # The successor top-up disbursement creates this repayment
            # atomically; the predecessor action only freezes the source fact.
            continue
        elif role == "repayment-reversal":
            original = _find_loan_transaction(api, loan, event["original_external_id"])
            if original is None:
                raise RuntimeError(f"reversal_original_missing:{event['original_external_id']}")
            if not _target_transaction_is_reversed(original):
                api.request("POST", f"loans/{loan_id}/transactions/{int(original['id'])}", {
                    "transactionDate": event["date"], "transactionAmount": "0.00",
                    "reversalExternalId": event["external_id"], "dateFormat": "yyyy-MM-dd", "locale": "en",
                }, idempotency_key=_attempt_idempotency_key(event["external_id"], attempt_key))
        elif role == "disbursement-reversal":
            original = _find_loan_transaction(api, loan, event["original_external_id"])
            if original is None:
                raise RuntimeError(f"reversal_original_missing:{event['original_external_id']}")
            if not _target_transaction_is_reversed(original):
                api.request(
                    "POST", f"loans/{loan_id}", {}, query={"command": "undodisbursal"},
                    idempotency_key=_attempt_idempotency_key(event["external_id"], attempt_key),
                )
        else:
            raise RuntimeError(f"unsupported_frozen_loan_event:{role}")

    cutover_charge = lifecycle.get("cutover_insurance_charge")
    if cutover_charge is not None:
        loan = _ensure_source_insurance_charges(
            api,
            loan,
            {"historical_insurance_charges": [cutover_charge]},
            attempt_key,
        )

    recurring_charge = lifecycle.get("recurring_insurance_charge")
    if recurring_charge is not None:
        loan = _ensure_recurring_insurance_charge(api, loan, recurring_charge, attempt_key)

    adjustment = lifecycle.get("terminal_adjustment")
    if adjustment is not None:
        loan = api.request("GET", f"loans/{loan_id}", query={"associations": "all"})
        status = int((loan.get("status") or {}).get("id") or -1)
        existing_adjustment = _transaction_by_external_id(loan, adjustment["external_id"])
        if existing_adjustment is None and status in {600, 601, 602, 700}:
            existing_adjustment = _find_loan_transaction(api, loan, adjustment["external_id"])
        if existing_adjustment is None and status == 300:
            amount = _amount((loan.get("summary") or {}).get("totalOutstanding"))
            maximum = _amount(adjustment["maximum_amount"])
            if amount > maximum:
                raise RuntimeError(
                    f"loan_cutover_adjustment_exceeds_frozen_maximum:"
                    f"{adjustment['external_id']}:{amount}:{maximum}"
                )
            if amount > Decimal("0.01"):
                api.request(
                    "POST", f"loans/{loan_id}/transactions", {
                        "transactionDate": adjustment["date"], "transactionAmount": format(amount, "f"),
                        "externalId": adjustment["external_id"], "dateFormat": "yyyy-MM-dd", "locale": "en",
                    }, query={"command": adjustment["command"]},
                    idempotency_key=_attempt_idempotency_key(adjustment["external_id"], attempt_key),
                )
        loan = api.request("GET", f"loans/{loan_id}", query={"associations": "all"})
        status = int((loan.get("status") or {}).get("id") or -1)
        outstanding = _amount((loan.get("summary") or {}).get("totalOutstanding"))
        if status not in {600, 601, 602, 700} or outstanding > Decimal("0.01"):
            raise RuntimeError(f"loan_cutover_adjustment_did_not_close:{status}:{outstanding}")
    return loan_id, recovered


def apply_loan_plan(
    settings: Settings, state: State, contract: LoanContract, plan_id: str,
    production_confirmation: str | None = None, only_keys: set[str] | None = None,
) -> tuple[str, dict[str, int]]:
    plan, current_target = _loan_apply_guard(
        settings, state, contract, plan_id, production_confirmation
    )
    actions = _selected_loan_actions(plan["document"]["actions"], only_keys)
    product_actions = [action for action in actions if action["entity_type"] == "product"]
    loan_actions = [action for action in actions if action["entity_type"] == "loan"]
    if actions != product_actions + loan_actions:
        raise RuntimeError("Loans plan is not ordered with products before loans")

    api = FineractApi(settings.target)
    run_id = state.start_run(plan)
    counts: Counter[str] = Counter()
    product_outcomes: dict[str, int | None] = {}
    for action in product_actions:
        key = action["source_key"]
        try:
            product_id, recovered = _resolve_or_create_loan_product(
                api, action, current_target["products"].get(action["entity_source_key"])
            )
            current_crosswalk = current_target["crosswalks"].get(action["entity_source_key"])
            repair_crosswalk = action["crosswalk"]["repair_after_product_resolution"] or (
                current_crosswalk is None
                or current_crosswalk["source_hash"] != action["source_hash"]
                or current_crosswalk["contract_hash"] != contract.digest
                or current_crosswalk["mapping_status"] != "ACTIVE"
            )
            if repair_crosswalk:
                _upsert_loan_product_crosswalk(settings, contract, action, product_id)
            state.save_mapping(
                settings.target.fingerprint, BLOCK, key, str(product_id), action["source_hash"]
            )
            status = "unchanged" if action["action"] == "unchanged-product" else "succeeded"
            state.record_item(run_id, key, action["action"], action["source_hash"], status, str(product_id))
            product_outcomes[key] = product_id
            counts["products_recovered" if recovered else status] += 1
        except Exception as exc:
            safe_detail = str(exc).splitlines()[0] if isinstance(exc, RuntimeError) else ""
            error_code = f"{type(exc).__name__}:{safe_detail}".rstrip(":")[:240]
            state.record_item(
                run_id, key, action["action"], action["source_hash"], "failed",
                action.get("target_id"), error_code,
            )
            product_outcomes[key] = None
            counts["products_failed"] += 1

    loan_outcomes: dict[str, bool] = {}
    for action in loan_actions:
        dependency = action["product_action_key"]
        product_id = product_outcomes.get(dependency)
        if product_id is None:
            status, reason = "blocked", "product_dependency_failed"
            counts["loans_blocked"] += 1
            state.record_item(
                run_id, action["source_key"], action["action"], action["source_hash"],
                status, action.get("target_id"), reason,
            )
            loan_outcomes[action["source_key"]] = False
            continue
        loan_dependencies = [
            key for key in action.get("depends_on", []) if key.startswith("loan:")
        ]
        if any(loan_outcomes.get(key) is not True for key in loan_dependencies):
            state.record_item(
                run_id, action["source_key"], action["action"], action["source_hash"],
                "blocked", action.get("target_id"), "loan_dependency_failed",
            )
            loan_outcomes[action["source_key"]] = False
            counts["loans_blocked"] += 1
            continue
        if action["action"] == "quarantine-loan":
            reason = ",".join(action.get("quarantine_reasons") or ["loan_quarantined"])
            state.record_item(
                run_id, action["source_key"], action["action"], action["source_hash"],
                "quarantined", action.get("target_id"), reason[:240],
            )
            counts["loans_quarantined"] += 1
            loan_outcomes[action["source_key"]] = False
            continue
        try:
            loan_id, recovered = _apply_loan_lifecycle(api, action, int(product_id), run_id)
            state.save_mapping(
                settings.target.fingerprint, BLOCK, action["source_key"], str(loan_id), action["source_hash"]
            )
            status = "recovered" if recovered else "succeeded"
            state.record_item(
                run_id, action["source_key"], action["action"], action["source_hash"], status, str(loan_id)
            )
            counts[f"loans_{status}"] += 1
            loan_outcomes[action["source_key"]] = True
        except Exception as exc:
            safe_detail = str(exc).splitlines()[0] if isinstance(exc, RuntimeError) else type(exc).__name__
            state.record_item(
                run_id, action["source_key"], action["action"], action["source_hash"], "failed",
                # Fineract validation responses put the actionable error code
                # after a generic envelope that already exceeds 240 chars.
                # SQLite TEXT has no practical 240-char restriction; retain a
                # bounded diagnostic body so failed-only retries are operable.
                action.get("target_id"), safe_detail[:4000],
            )
            counts["loans_failed"] += 1
            loan_outcomes[action["source_key"]] = False

    run_status = "completed-with-errors" if counts["products_failed"] or counts["loans_failed"] else (
        "completed-with-quarantine" if counts["loans_quarantined"] else "completed"
    )
    state.finish_run(run_id, run_status, dict(counts))
    return run_id, dict(counts)


def reconcile_loans(
    settings: Settings, state: State, contract: LoanContract, run_id: str,
) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Loan run belongs to a different block or target")
    plan = state.plan(run["plan_id"])
    if plan["contract_hash"] != contract.digest:
        raise RuntimeError("Loans contract changed after the run")
    actions = {row["source_key"]: row for row in plan["document"]["actions"]}
    items = state.run_items(run_id)
    api = FineractApi(settings.target)
    mismatches: list[dict[str, Any]] = []
    variances: list[dict[str, Any]] = []
    adjustments: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    failed_or_quarantined = []

    for item in items:
        action = actions.get(item["source_key"])
        if action is None:
            mismatches.append({"source_key": item["source_key"], "kind": "run_item_missing_from_plan"})
            continue
        if action["entity_type"] != "loan":
            counts["products"] += 1
            continue
        if item["status"] in {"failed", "blocked", "quarantined"}:
            failed_or_quarantined.append({
                "source_key": item["source_key"], "status": item["status"], "error_code": item.get("error_code")
            })
            counts[item["status"]] += 1
            continue
        loan = _find_loan(api, action["external_id"])
        if loan is None:
            mismatches.append({"source_key": item["source_key"], "kind": "target_loan_missing"})
            continue
        counts["loans"] += 1
        lifecycle = action["lifecycle"]
        expected_assignment = lifecycle.get("staff_assignment")
        assignment_row = _generic_datatable_row(
            api.datatable_data("credesal_loan_staff_assignment", str(loan["id"]))
        )
        assignment_differences = _loan_staff_assignment_differences(expected_assignment or {}, assignment_row)
        if expected_assignment is None:
            assignment_differences = ["plan_missing_staff_assignment"]
        if assignment_differences:
            mismatches.append({
                "source_key": item["source_key"], "kind": "loan_staff_assignment",
                "columns": assignment_differences,
            })
        else:
            counts["staff_assignments"] += 1
        expected_legacy_timeline = lifecycle.get("legacy_timeline")
        if expected_legacy_timeline is not None:
            legacy_timeline_row = _generic_datatable_row(
                api.datatable_data("credesal_loan_legacy_timeline", str(loan["id"]))
            )
            legacy_timeline_differences = _loan_legacy_timeline_differences(
                expected_legacy_timeline, legacy_timeline_row,
            )
            if legacy_timeline_differences:
                mismatches.append({
                    "source_key": item["source_key"], "kind": "loan_legacy_timeline",
                    "columns": legacy_timeline_differences,
                })
            else:
                counts["legacy_timelines"] += 1
        expected = lifecycle["expected"]
        terminal_disbursement_reversal = bool(lifecycle["events"]) and (
            lifecycle["events"][-1]["role"] == "disbursement-reversal"
        )
        target_status = loan.get("status") or {}
        status_matches = _loan_status_matches(expected["source_state"], target_status)
        if terminal_disbursement_reversal and expected["source_state"] == "3":
            status_matches = int(target_status.get("id") or -1) == 200
        if not status_matches:
            mismatches.append({
                "source_key": item["source_key"], "kind": "terminal_status",
                "source": expected["source_state"], "target": target_status.get("value"),
            })
        summary = loan.get("summary") or {}
        balance_fields = {
            "principal_balance": "principalOutstanding",
            "interest_balance": "interestOutstanding",
            "penalty_balance": "penaltyChargesOutstanding",
            "fee_balance": "feeChargesOutstanding",
        }
        for source_field, target_field in balance_fields.items():
            source_amount = _amount(expected[source_field])
            target_amount = _amount(summary.get(target_field))
            if abs(source_amount - target_amount) > Decimal("0.01"):
                difference = {
                    "source_key": item["source_key"], "kind": source_field,
                    "source": format(source_amount, "f"), "target": format(target_amount, "f"),
                }
                if source_field == "principal_balance" and expected["source_state"] != "1":
                    difference["classification"] = "blocking_cutover_balance"
                    mismatches.append(difference)
                else:
                    difference["classification"] = (
                        "accepted_native_allocation_balance_variance"
                        if source_field == "principal_balance" else "native_schedule_component_variance"
                    )
                    variances.append(difference)
        source_total = _amount(expected["total_outstanding"])
        target_total = _amount(summary.get("totalOutstanding"))
        if abs(source_total - target_total) > Decimal("0.01"):
            variances.append({
                "source_key": item["source_key"], "kind": "total_outstanding",
                "source": format(source_total, "f"), "target": format(target_total, "f"),
                "classification": "full_native_schedule_not_cutover_comparable",
            })
        overdue_fields = (
            "interestOverdue", "feeChargesOverdue", "penaltyChargesOverdue",
        )
        if any(field in summary for field in overdue_fields):
            target_cutover_total = _amount(summary.get("principalOutstanding")) + sum(
                (_amount(summary.get(field)) for field in overdue_fields), Decimal("0.00")
            )
        else:
            # Some older/test API representations omit overdue component fields.
            target_cutover_total = target_total
        if abs(source_total - target_cutover_total) > Decimal("0.01"):
            difference = {
                "source_key": item["source_key"], "kind": "cutover_total",
                "source": format(source_total, "f"), "target": format(target_cutover_total, "f"),
                "classification": (
                    "accepted_native_allocation_balance_variance"
                    if expected["source_state"] == "1" else "blocking_cutover_balance"
                ),
            }
            (variances if expected["source_state"] == "1" else mismatches).append(difference)

        repayment_schedule = loan.get("repaymentSchedule") or {}
        source_schedule = lifecycle.get("schedule") or []
        schedule_differences = _loan_schedule_differences(source_schedule, repayment_schedule)
        schedule_reconciliation_policy = lifecycle.get("schedule_reconciliation_policy")
        reviewed_schedule_exception = schedule_reconciliation_policy in {
            "reviewed-manual-adjustment", "historical-reference-only",
        }
        for difference in schedule_differences:
            difference["source_key"] = item["source_key"]
            difference["classification"] = (
                "historical_reference_only_schedule_variance"
                if schedule_reconciliation_policy == "historical-reference-only"
                else "reviewed_manual_adjustment_schedule_variance"
                if reviewed_schedule_exception
                else "blocking_schedule_mismatch"
            )
            (variances if reviewed_schedule_exception else mismatches).append(difference)

        refinance = lifecycle.get("refinance")
        for event in lifecycle["events"]:
            if event["role"] in {"repayment-reversal", "disbursement-reversal"}:
                original = _find_loan_transaction(api, loan, event["original_external_id"])
                if original is None or not _target_transaction_is_reversed(original):
                    mismatches.append({
                        "source_key": item["source_key"], "kind": "reversal_state",
                        "movement": event["source_movement_id"],
                    })
                continue
            transaction_external_id = event["external_id"]
            transaction = _find_loan_transaction(api, loan, transaction_external_id)
            is_topup_disbursement = bool(
                refinance and event["role"] == "disbursement"
                and event["external_id"] == refinance["disbursement_external_id"]
            )
            if transaction is None:
                mismatches.append({
                    "source_key": item["source_key"], "kind": "transaction_missing",
                    "movement": event["source_movement_id"],
                })
                continue
            represented_amount = _amount(transaction.get("amount"))
            if is_topup_disbursement:
                for settlement in _refinance_settlements(refinance):
                    transfer_external_id = settlement.get("transfer_external_id") or settlement.get(
                        "topup_transfer_external_id"
                    )
                    transfer = _find_loan_transaction(api, loan, transfer_external_id)
                    if transfer is None:
                        mismatches.append({
                            "source_key": item["source_key"],
                            "kind": "refinancing_transfer_transaction_missing",
                            "movement": event["source_movement_id"],
                            "predecessor_source_key": settlement["predecessor_source_key"],
                        })
                    else:
                        represented_amount += _amount(transfer.get("amount"))
            if represented_amount != _amount(event["amount"]):
                mismatches.append({
                    "source_key": item["source_key"], "kind": "transaction_amount",
                    "movement": event["source_movement_id"],
                    "source": event["amount"], "target_represented": format(represented_amount, "f"),
                })
            if event["role"] in {
                "repayment", "adjusted-repayment", "mobile-collection-repayment",
                "native-refinance-payoff", "source-exact-component-reallocation",
            }:
                try:
                    _verify_repayment_allocation(transaction, event)
                except RuntimeError as exc:
                    mismatches.append({
                        "source_key": item["source_key"], "kind": "transaction_allocation",
                        "movement": event["source_movement_id"], "detail": str(exc),
                        "classification": "blocking_historical_allocation_mismatch",
                    })
            if event["role"] == "native-refinance-payoff":
                bridge = _find_loan_transaction(api, loan, event["adjustment_external_id"])
                final_bridge = _find_loan_transaction(api, loan, event["final_adjustment_external_id"])
                for adjustment_transaction, external_id, phase in (
                    (bridge, event["adjustment_external_id"], "dated_prepayment_quote"),
                    (final_bridge, event["final_adjustment_external_id"], "post_topup_residual"),
                ):
                    adjustments.append({
                        "source_key": item["source_key"],
                        "applied": adjustment_transaction is not None,
                        "external_id": external_id,
                        "amount": format(_amount((adjustment_transaction or {}).get("amount")), "f"),
                        "phase": phase,
                        "classification": "native_fineract_topup_with_source_exact_component_bridge",
                    })

        terminal_adjustment = lifecycle.get("terminal_adjustment")
        if terminal_adjustment is not None:
            adjustment_transaction = _find_loan_transaction(
                api, loan, terminal_adjustment["external_id"]
            )
            if adjustment_transaction is None:
                if _amount(summary.get("totalOutstanding")) > Decimal("0.01"):
                    mismatches.append({
                        "source_key": item["source_key"], "kind": "cutover_adjustment_missing",
                        "external_id": terminal_adjustment["external_id"],
                    })
                else:
                    adjustments.append({
                        "source_key": item["source_key"], "applied": False,
                        "amount": "0.00", "classification": terminal_adjustment["classification"],
                    })
            else:
                adjustments.append({
                    "source_key": item["source_key"], "applied": True,
                    "external_id": terminal_adjustment["external_id"],
                    "amount": format(_amount(adjustment_transaction.get("amount")), "f"),
                    "classification": terminal_adjustment["classification"],
                })

        journals = api.request("GET", "journalentries", query={"loanId": int(loan["id"]), "limit": 10000})
        journal_rows = journals.get("pageItems") or journals.get("content") or []
        debits = sum((_amount(row.get("amount")) for row in journal_rows
                      if (row.get("entryType") or {}).get("value") == "DEBIT"), Decimal("0.00"))
        credits = sum((_amount(row.get("amount")) for row in journal_rows
                       if (row.get("entryType") or {}).get("value") == "CREDIT"), Decimal("0.00"))
        if debits != credits:
            mismatches.append({
                "source_key": item["source_key"], "kind": "journal_unbalanced",
                "debits": format(debits, "f"), "credits": format(credits, "f"),
            })

    ok = not mismatches and not any(row["status"] in {"failed", "blocked"} for row in failed_or_quarantined)
    return {
        "run_id": run_id,
        "ok": ok,
        "counts": dict(counts),
        "failed_or_quarantined": failed_or_quarantined,
        "mismatches": mismatches,
        "variances": variances,
        "adjustments": adjustments,
    }


def compact_loan_reconciliation_report(
    result: dict[str, Any], sample_limit: int = 3,
) -> dict[str, Any]:
    """Group a strict loan reconciliation result without discarding affected identities."""
    if sample_limit < 0:
        raise ValueError("sample_limit must be zero or greater")

    def grouped_findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[(str(row.get("kind") or "unclassified"), row.get("classification"))].append(row)
        output = []
        for (kind, classification), findings in sorted(
            groups.items(), key=lambda item: (item[0][0], item[0][1] or "")
        ):
            source_keys = sorted({str(row["source_key"]) for row in findings if row.get("source_key")})
            output.append({
                "kind": kind,
                "classification": classification,
                "count": len(findings),
                "affected_source_key_count": len(source_keys),
                "affected_source_keys": source_keys,
                "samples": findings[:sample_limit],
            })
        return output

    failed_rows = list(result.get("failed_or_quarantined") or [])
    failed_groups: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for row in failed_rows:
        failed_groups[(str(row.get("status") or "unknown"), row.get("error_code"))].append(row)
    grouped_failures = []
    for (status, error_code), findings in sorted(
        failed_groups.items(), key=lambda item: (item[0][0], item[0][1] or "")
    ):
        source_keys = sorted({str(row["source_key"]) for row in findings if row.get("source_key")})
        grouped_failures.append({
            "status": status,
            "error_code": error_code,
            "count": len(findings),
            "affected_source_keys": source_keys,
            "samples": findings[:sample_limit],
        })

    mismatches = list(result.get("mismatches") or [])
    variances = list(result.get("variances") or [])
    mismatch_source_keys = sorted({
        str(row["source_key"]) for row in mismatches if row.get("source_key")
    })
    return {
        "run_id": result.get("run_id"),
        "ok": bool(result.get("ok")),
        "counts": dict(result.get("counts") or {}),
        "blocking_mismatch_count": len(mismatches),
        "blocking_affected_source_key_count": len(mismatch_source_keys),
        "blocking_affected_source_keys": mismatch_source_keys,
        "mismatch_groups": grouped_findings(mismatches),
        "variance_count": len(variances),
        "variance_groups": grouped_findings(variances),
        "failed_or_quarantined_count": len(failed_rows),
        "failed_or_quarantined_groups": grouped_failures,
        "adjustments": list(result.get("adjustments") or []),
    }


def inspect_loans(
    source_config: SourceConfig,
    contract: LoanContract,
    source_key: str | int | None = None,
    target_pg_url: str | None = None,
) -> dict[str, Any]:
    key = canonical_source_key(source_key)
    source = contract.raw["source"]
    schema: list[dict[str, Any]] = []
    source_blockers: list[str] = []
    params: tuple[Any, ...] = () if key is None else (key,)
    loan_filter = "" if key is None else " WHERE c.ID_CREDITO=?"
    movement_filter = "" if key is None else " WHERE m.ID_CREDITO=?"
    schedule_filter = "" if key is None else " WHERE p.ID_CREDITO=?"

    with source_connection(source_config) as conn:
        for role, required in REQUIRED_COLUMNS.items():
            table = source[role]
            columns = select_rows(
                conn,
                "SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA=? AND TABLE_NAME=? ORDER BY ORDINAL_POSITION",
                ("dbo", table),
            )
            available = {str(row["column_name"]) for row in columns}
            missing = sorted(required - available)
            schema.append({"role": role, "table": table, "column_count": len(columns), "missing_required_columns": missing})
            if not columns:
                source_blockers.append(f"missing_source_table:{table}")
            source_blockers.extend(f"missing_source_column:{table}:{column}" for column in missing)

        loan_identity = select_rows(conn, f"""
            SELECT COUNT_BIG(*) AS loan_count,
                   SUM(CASE WHEN c.ID_CREDITO IS NULL THEN 1 ELSE 0 END) AS null_loan_keys,
                   COUNT_BIG(DISTINCT c.ID_CREDITO) AS distinct_loan_keys,
                   SUM(CASE WHEN NULLIF(RTRIM(c.NO_PRESTAMO),'') IS NULL THEN 1 ELSE 0 END) AS blank_account_numbers,
                   COUNT_BIG(DISTINCT NULLIF(RTRIM(c.NO_PRESTAMO),'')) AS distinct_account_numbers
            FROM [dbo].[{source['loan_table']}] c{loan_filter}
        """, params)[0]
        product_filter = "" if key is None else " WHERE c.ID_CREDITO=?"
        products = select_rows(conn, f"""
            SELECT RTRIM(l.ID_EMPRESA) AS company_id,RTRIM(l.ID_LINEA_CREDITO) AS line_id,
                   RTRIM(l.CODIGO_LINEA_CREDITO) AS line_code,RTRIM(l.NOMBRE_LINEA) AS line_name,
                   RTRIM(l.ID_TIPO_LINEA) AS line_type,RTRIM(l.ESTADO_LINEA) AS line_state,
                   l.MONTO_INI AS minimum_principal,l.MONTO_FIN AS maximum_principal,
                   l.TASA_INTERES AS default_interest_rate,l.TASA_INTERES_INI AS minimum_interest_rate,
                   l.TASA_INTERES_FIN AS maximum_interest_rate,l.PLAZO_INI AS minimum_term,l.PLAZO_FIN AS maximum_term,
                   l.ID_TIPO_PLAN_PAGO AS schedule_type,l.PRIORIDAD_MORA AS penalty_priority,
                   l.PRIORIDAD_INTERES AS interest_priority,l.PRIORIDAD_CAPITAL AS principal_priority,
                   l.COBRO_MOVIL AS mobile_collection_enabled,l.PROVI_INT_NORMAL AS provision_interest,
                   RTRIM(l.ID_CUENTA_CARGO_PROVI) AS interest_receivable_source_account,COUNT(c.ID_CREDITO) AS loan_count
            FROM [dbo].[{source['product_table']}] l
            LEFT JOIN [dbo].[{source['loan_table']}] c
              ON c.ID_EMPRESA=l.ID_EMPRESA AND c.ID_LINEA_CREDITO=l.ID_LINEA_CREDITO{product_filter}
            GROUP BY l.ID_EMPRESA,l.ID_LINEA_CREDITO,l.CODIGO_LINEA_CREDITO,l.NOMBRE_LINEA,l.ID_TIPO_LINEA,
                     l.ESTADO_LINEA,l.MONTO_INI,l.MONTO_FIN,l.TASA_INTERES,l.TASA_INTERES_INI,l.TASA_INTERES_FIN,
                     l.PLAZO_INI,l.PLAZO_FIN,l.ID_TIPO_PLAN_PAGO,l.PRIORIDAD_MORA,l.PRIORIDAD_INTERES,
                     l.PRIORIDAD_CAPITAL,l.COBRO_MOVIL,l.PROVI_INT_NORMAL,l.ID_CUENTA_CARGO_PROVI
            ORDER BY l.ID_EMPRESA,l.ID_LINEA_CREDITO
        """, params)
        lifecycle = select_rows(conn, f"""
            SELECT RTRIM(c.ID_ESTADO_CARTERA) AS loan_state,RTRIM(c.ID_TIPO_CREDITO) AS loan_type,
                   COUNT_BIG(*) AS loan_count
            FROM [dbo].[{source['loan_table']}] c{loan_filter}
            GROUP BY c.ID_ESTADO_CARTERA,c.ID_TIPO_CREDITO ORDER BY c.ID_ESTADO_CARTERA,c.ID_TIPO_CREDITO
        """, params)
        application = select_rows(conn, f"""
            SELECT COUNT_BIG(*) AS loan_count,
                   SUM(CASE WHEN s.ID_SOLICITUD_CREDITO IS NULL THEN 1 ELSE 0 END) AS missing_application_count
            FROM [dbo].[{source['loan_table']}] c
            LEFT JOIN [dbo].[{source['application_table']}] s
              ON s.ID_EMPRESA=c.ID_EMPRESA AND s.ID_SUCURSAL=c.ID_SUCURSAL
             AND s.ID_LINEA_CREDITO=c.ID_LINEA_CREDITO AND s.ID_SOCIO=c.ID_SOCIO
             AND s.ID_SOLICITUD_CREDITO=c.ID_SOLICITUD_CREDITO{loan_filter}
        """, params)[0]
        schedule = select_rows(conn, f"""
            WITH schedule AS (
                SELECT p.ID_CREDITO,COUNT_BIG(*) AS installment_count,MIN(p.FECHA_PAGO) AS first_due_date,
                       MAX(p.FECHA_PAGO) AS last_due_date,
                       SUM(CASE WHEN p.FECHA_PAGO IS NULL THEN 1 ELSE 0 END) AS null_due_dates
                FROM [dbo].[{source['schedule_table']}] p{schedule_filter}
                GROUP BY p.ID_CREDITO
            )
            SELECT COUNT_BIG(c.ID_CREDITO) AS loan_count,COUNT_BIG(s.ID_CREDITO) AS loans_with_schedule,
                   SUM(CASE WHEN s.ID_CREDITO IS NULL THEN 1 ELSE 0 END) AS loans_without_schedule,
                   SUM(COALESCE(s.installment_count,0)) AS installment_count,
                   SUM(COALESCE(s.null_due_dates,0)) AS null_due_dates,
                   SUM(CASE WHEN s.first_due_date IS NOT NULL AND CAST(s.first_due_date AS date)
                                      <>CAST(c.FECHA_PRIMER_PAGO AS date) THEN 1 ELSE 0 END) AS first_due_date_mismatches
            FROM [dbo].[{source['loan_table']}] c LEFT JOIN schedule s ON s.ID_CREDITO=c.ID_CREDITO{loan_filter}
        """, params + params)[0] if key is not None else select_rows(conn, f"""
            WITH schedule AS (
                SELECT p.ID_CREDITO,COUNT_BIG(*) AS installment_count,MIN(p.FECHA_PAGO) AS first_due_date,
                       SUM(CASE WHEN p.FECHA_PAGO IS NULL THEN 1 ELSE 0 END) AS null_due_dates
                FROM [dbo].[{source['schedule_table']}] p WHERE p.ID_CREDITO IS NOT NULL GROUP BY p.ID_CREDITO
            )
            SELECT COUNT_BIG(c.ID_CREDITO) AS loan_count,COUNT_BIG(s.ID_CREDITO) AS loans_with_schedule,
                   SUM(CASE WHEN s.ID_CREDITO IS NULL THEN 1 ELSE 0 END) AS loans_without_schedule,
                   SUM(COALESCE(s.installment_count,0)) AS installment_count,
                   SUM(COALESCE(s.null_due_dates,0)) AS null_due_dates,
                   SUM(CASE WHEN s.first_due_date IS NOT NULL AND CAST(s.first_due_date AS date)
                                      <>CAST(c.FECHA_PRIMER_PAGO AS date) THEN 1 ELSE 0 END) AS first_due_date_mismatches
            FROM [dbo].[{source['loan_table']}] c LEFT JOIN schedule s ON s.ID_CREDITO=c.ID_CREDITO
        """)[0]
        movement_identity = select_rows(conn, f"""
            SELECT COUNT_BIG(*) AS movement_count,
                   SUM(CASE WHEN NULLIF(RTRIM(m.ID_MOVIMIENTO_CARTERA),'') IS NULL THEN 1 ELSE 0 END) AS blank_movement_keys,
                   COUNT_BIG(DISTINCT NULLIF(RTRIM(m.ID_MOVIMIENTO_CARTERA),'')) AS distinct_movement_keys,
                   SUM(CASE WHEN m.ID_CREDITO IS NULL THEN 1 ELSE 0 END) AS missing_loan_keys,
                   COUNT_BIG(DISTINCT m.ID_CREDITO) AS loans_with_movements
            FROM [dbo].[{source['movement_table']}] m{movement_filter}
        """, params)[0]
        transactions = select_rows(conn, f"""
            SELECT CONVERT(varchar(10),m.CODIGO_SISTEMA) AS system_code,RTRIM(m.ID_TRANSACCION) AS transaction_code,
                   RTRIM(t.TRANSACCION) AS transaction_name,
                   CASE WHEN COALESCE(RTRIM(m.REVERSION),'')='1' THEN 1 ELSE 0 END AS reversed,
                   COUNT_BIG(*) AS movement_count
            FROM [dbo].[{source['movement_table']}] m
            LEFT JOIN [dbo].[{source['transaction_catalog_table']}] t
              ON t.CODIGO_SISTEMA=m.CODIGO_SISTEMA AND t.ID_TRANSACCION=m.ID_TRANSACCION{movement_filter}
            GROUP BY m.CODIGO_SISTEMA,m.ID_TRANSACCION,t.TRANSACCION,
                     CASE WHEN COALESCE(RTRIM(m.REVERSION),'')='1' THEN 1 ELSE 0 END
            ORDER BY m.CODIGO_SISTEMA,m.ID_TRANSACCION,reversed
        """, params)
        timestamp_coverage = select_rows(conn, f"""
            SELECT COUNT_BIG(*) AS movement_count,
                   SUM(CASE WHEN m.FECHA_OPERACION IS NULL THEN 1 ELSE 0 END) AS null_fecha_operacion,
                   SUM(CASE WHEN m.FECHA_VALOR IS NULL THEN 1 ELSE 0 END) AS null_fecha_valor,
                   SUM(CASE WHEN m.FECHA_PAGO IS NULL THEN 1 ELSE 0 END) AS null_fecha_pago,
                   SUM(CASE WHEN m.DT_MOVIMIENTO IS NULL THEN 1 ELSE 0 END) AS null_dt_movimiento,
                   SUM(CASE WHEN m.DT_CREO IS NULL THEN 1 ELSE 0 END) AS null_dt_creo,
                   SUM(CASE WHEN COALESCE(m.FECHA_OPERACION,m.FECHA_VALOR,m.FECHA_PAGO,m.DT_MOVIMIENTO,m.DT_CREO)
                                      IS NULL THEN 1 ELSE 0 END) AS movements_without_timestamp
            FROM [dbo].[{source['movement_table']}] m{movement_filter}
        """, params)[0]
        components = select_rows(conn, f"""
            SELECT COUNT_BIG(*) AS movement_count,
                   SUM(CASE WHEN COALESCE(m.MONTO_AHORRO,0)<>0 THEN 1 ELSE 0 END) AS savings_component_count,
                   SUM(CASE WHEN COALESCE(m.MONTO_APORTACION,0)<>0 THEN 1 ELSE 0 END) AS contribution_component_count,
                   SUM(CASE WHEN COALESCE(m.MONTO_OTROS,0)<>0 AND COALESCE(m.MONTO_SEGURO,0)<>0 THEN 1 ELSE 0 END)
                       AS overlapping_other_and_insurance_count,
                   SUM(CASE WHEN ABS(COALESCE(m.MONTO,0) - (
                        COALESCE(m.MONTO_CAPITAL,0)+COALESCE(m.MONTO_INTERES,0)+COALESCE(m.MONTO_INT_PENDIENTES,0)
                       +COALESCE(m.MONTO_MORA,0)+COALESCE(m.MONTO_SEGURO,0)+COALESCE(m.MONTO_RECARGOS,0)
                       +COALESCE(m.MONTO_CXC,0)+COALESCE(m.MONTO_AHORRO,0)+COALESCE(m.MONTO_APORTACION,0)
                       +COALESCE(m.MONTO_IVA_INTERES,0)+COALESCE(m.MONTO_IVA_MORA,0)
                       +COALESCE(m.MONTO_IVA_INTERES_PEND,0)+COALESCE(m.MONTO_IVA_OTROS,0)))>0.01
                       THEN 1 ELSE 0 END) AS component_residual_count
            FROM [dbo].[{source['movement_table']}] m{movement_filter}
        """, params)[0]
        refinance_links = select_rows(conn, f"""
            WITH links AS (
                SELECT DISTINCT old.ID_CREDITO AS predecessor_id,newc.ID_CREDITO AS successor_id,
                       CASE WHEN COALESCE(RTRIM(old.REVERSION),'')='1' THEN 1 ELSE 0 END AS source_reversed,
                       CASE WHEN oldc.ID_SOCIO=newc.ID_SOCIO THEN 1 ELSE 0 END AS same_owner
                FROM [dbo].[{source['movement_table']}] old
                JOIN [dbo].[{source['loan_table']}] oldc ON oldc.ID_CREDITO=old.ID_CREDITO
                JOIN [dbo].[{source['liquidation_detail_table']}] d
                  ON d.ID_CRD_MOVIMIENTO=old.ID_CRD_MOVIMIENTO
                JOIN [dbo].[{source['liquidation_header_table']}] h
                  ON h.ID_LIQUIDACION=d.ID_LIQUIDACION AND h.ID_EMPRESA=d.ID_EMPRESA
                 AND h.ID_SUCURSAL=d.ID_SUCURSAL AND h.ID_SOLICITUD_CREDITO=d.ID_SOLICITUD_CREDITO
                 AND h.ID_LINEA_CREDITO=d.ID_LINEA_CREDITO AND h.ID_SOCIO=d.ID_SOCIO
                 AND h.ID_PRESTAMO_NO=d.ID_PRESTAMO_NO
                JOIN [dbo].[{source['loan_table']}] newc
                  ON newc.ID_EMPRESA=h.ID_EMPRESA AND newc.ID_SUCURSAL=h.ID_SUCURSAL
                 AND newc.ID_SOLICITUD_CREDITO=h.ID_SOLICITUD_CREDITO
                 AND newc.ID_LINEA_CREDITO=h.ID_LINEA_CREDITO AND newc.ID_SOCIO=h.ID_SOCIO
                 AND newc.ID_PRESTAMO_NO=h.ID_PRESTAMO_NO
                WHERE old.CODIGO_SISTEMA=4 AND RTRIM(old.ID_TRANSACCION)='00019'
                  AND h.CLASE_LIQ=2
            ), predecessor_counts AS (
                SELECT successor_id,COUNT(*) AS predecessor_count FROM links GROUP BY successor_id
            ), successor_counts AS (
                SELECT predecessor_id,COUNT(*) AS successor_count FROM links GROUP BY predecessor_id
            ), multi_owner AS (
                SELECT l.successor_id,
                       SUM(CASE WHEN l.same_owner=0 THEN 1 ELSE 0 END) AS cross_owner_predecessor_count
                FROM links l
                JOIN predecessor_counts p ON p.successor_id=l.successor_id AND p.predecessor_count>1
                WHERE l.source_reversed=0
                GROUP BY l.successor_id
            )
            SELECT
                (SELECT COUNT(*) FROM links) AS link_count,
                (SELECT COUNT(DISTINCT predecessor_id) FROM links) AS predecessor_count,
                (SELECT COUNT(DISTINCT successor_id) FROM links) AS successor_count,
                (SELECT COUNT(*) FROM links WHERE source_reversed=0) AS active_link_count,
                (SELECT COUNT(*) FROM links WHERE source_reversed=1) AS reversed_link_count,
                (SELECT COUNT(*) FROM predecessor_counts WHERE predecessor_count>1)
                    AS multi_predecessor_successor_count,
                (SELECT COUNT(*) FROM multi_owner WHERE cross_owner_predecessor_count=0)
                    AS same_client_multi_predecessor_successor_count,
                (SELECT COUNT(*) FROM multi_owner WHERE cross_owner_predecessor_count>0)
                    AS cross_client_multi_predecessor_successor_count,
                (SELECT COUNT(*) FROM successor_counts WHERE successor_count>1)
                    AS ambiguous_successor_predecessor_count
        """)[0]
        restructure_population = select_rows(conn, f"""
            SELECT COUNT_BIG(*) AS tagged_schedule_rows,
                   COUNT_BIG(DISTINCT ID_REESTRUCTURACION) AS restructure_snapshot_count,
                   COUNT_BIG(DISTINCT ID_CREDITO) AS linked_loan_count,
                   SUM(CASE WHEN ID_CREDITO IS NULL THEN 1 ELSE 0 END) AS archival_unlinked_rows,
                   SUM(CASE WHEN ID_CREDITO IS NOT NULL THEN 1 ELSE 0 END) AS linked_schedule_rows
            FROM [dbo].[{source['schedule_table']}]
            WHERE ID_REESTRUCTURACION IS NOT NULL
        """)[0]
        reversal_scope = "" if key is None else " AND m.ID_CREDITO=?"
        reversal_rows = select_rows(conn, f"""
            SELECT m.ID_CREDITO,m.ID_MOVIMIENTO_CARTERA,m.CODIGO_SISTEMA,m.ID_TRANSACCION,m.REVERSION,
                   m.FECHA_OPERACION,m.MONTO,m.MONTO_CAPITAL,m.MONTO_INTERES,m.MONTO_INT_PENDIENTES,
                   m.MONTO_MORA,m.MONTO_OTROS,m.MONTO_SEGURO,m.MONTO_RECARGOS,m.MONTO_CXC,
                   m.MONTO_AHORRO,m.MONTO_APORTACION,m.MONTO_IVA,m.MONTO_IVA_INTERES,m.MONTO_IVA_MORA,
                   m.MONTO_IVA_INTERES_PEND,m.MONTO_IVA_OTROS
            FROM [dbo].[{source['movement_table']}] m
            WHERE ((m.CODIGO_SISTEMA=4 AND RTRIM(m.ID_TRANSACCION) IN ('00002','00004','00030'))
               OR (COALESCE(RTRIM(m.REVERSION),'')='1' AND
                  ((m.CODIGO_SISTEMA=4 AND RTRIM(m.ID_TRANSACCION) IN ('00001','00013','00019'))
                    OR (m.CODIGO_SISTEMA=14 AND RTRIM(m.ID_TRANSACCION)='00011')))){reversal_scope}
            ORDER BY m.ID_CREDITO,m.FECHA_OPERACION,m.ID_MOVIMIENTO_CARTERA
        """, params)

    reversal_pairing = pair_loan_reversals(reversal_rows)

    loan_count = int(loan_identity.get("loan_count") or 0)
    movement_count = int(movement_identity.get("movement_count") or 0)
    if key is not None and loan_count == 0:
        source_blockers.append("source_loan_not_found")
    if int(loan_identity.get("null_loan_keys") or 0) or int(loan_identity.get("distinct_loan_keys") or 0) != loan_count:
        source_blockers.append("loan_identity_not_unique")
    if int(loan_identity.get("blank_account_numbers") or 0) or int(loan_identity.get("distinct_account_numbers") or 0) != loan_count:
        source_blockers.append("loan_account_number_not_unique")
    if int(application.get("missing_application_count") or 0):
        source_blockers.append("loan_application_link_missing")
    if int(movement_identity.get("blank_movement_keys") or 0) or int(movement_identity.get("distinct_movement_keys") or 0) != movement_count:
        source_blockers.append("movement_identity_not_unique")
    if int(movement_identity.get("missing_loan_keys") or 0):
        source_blockers.append("movement_loan_link_missing")
    if int(timestamp_coverage.get("movements_without_timestamp") or 0):
        source_blockers.append("movement_timestamp_missing")
    product_companies = {str(row.get("company_id") or "").strip() for row in products}
    product_companies.discard("")
    if len(product_companies) != 1:
        source_blockers.append("loan_product_source_must_have_exactly_one_company")

    supported = contract.raw["supported_transactions"]
    transaction_inventory: list[dict[str, Any]] = []
    for row in transactions:
        code = f"{str(row.get('system_code')).strip()}:{str(row.get('transaction_code') or '').strip()}"
        item = dict(row)
        item["contract_role"] = supported.get(code)
        item["supported"] = code in supported
        transaction_inventory.append(item)
        if code not in supported:
            source_blockers.append(f"unmapped_loan_transaction:{code}")

    implementation_blockers = [f"implementation_gate:{gate}" for gate in contract.raw["implementation_gates"]]
    line_00001_exception = contract.raw["historical_schedule_exceptions"]["00001"]
    schedule_exception_report = {
        "line_id": "00001",
        "classification": line_00001_exception["classification"],
        "plan_behavior": line_00001_exception["plan_behavior"],
        "blocking": line_00001_exception["blocking"],
        "reviewed_source_loan_ids": line_00001_exception["source_loan_ids"],
        "scope_applies": key in line_00001_exception["source_loan_ids"] if key is not None else None,
        "required_reconciliation": line_00001_exception["required_reconciliation"],
    }
    source_blockers = sorted(set(source_blockers))
    target_schema: dict[str, dict[str, str]] = {table: {} for table in REQUIRED_TARGET_COLUMNS}
    target_blockers: list[str] = []
    target: dict[str, Any] = {"postgres_inspection": "not-requested"}
    if target_pg_url:
        with postgres_connection(target_pg_url) as conn:
            target_schema = postgres_schema(conn, list(REQUIRED_TARGET_COLUMNS))
            counts: dict[str, int] = {}
            for table in REQUIRED_TARGET_COLUMNS:
                available = set(target_schema.get(table, {}))
                missing = sorted(REQUIRED_TARGET_COLUMNS[table] - available)
                if not available:
                    target_blockers.append(f"missing_target_table:{table}")
                else:
                    target_blockers.extend(f"missing_target_column:{table}:{column}" for column in missing)
                    counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            native_products = []
            if target_schema.get("m_product_loan"):
                rows = conn.execute("""
                    SELECT id,name,short_name,external_id,currency_code,accounting_type,id_tipo_linea,
                           loan_transaction_strategy_code
                    FROM m_product_loan ORDER BY id
                """).fetchall()
                columns = (
                    "id", "name", "short_name", "external_id", "currency_code", "accounting_type",
                    "id_tipo_linea", "transaction_strategy",
                )
                native_products = [dict(zip(columns, row)) for row in rows]
            required_permissions = {
                "SOURCEEXACTREPAYMENT_LOAN", "SOURCEEXACTGOODWILLCREDIT_LOAN",
                "SOURCEEXACTTOPUPDISBURSE_LOAN", "SOURCEEXACTCOMPONENTREALLOCATION_LOAN",
                "SOURCEEXACTREFINANCINGDISBURSE_LOAN",
                "READ_credesal_loan_staff_assignment", "CREATE_credesal_loan_staff_assignment",
                "UPDATE_credesal_loan_staff_assignment",
                "READ_credesal_loan_legacy_timeline", "CREATE_credesal_loan_legacy_timeline",
                "UPDATE_credesal_loan_legacy_timeline",
            }
            available_permissions = set()
            if target_schema.get("m_permission"):
                available_permissions = {
                    str(row[0]) for row in conn.execute(
                        "SELECT code FROM m_permission WHERE code = ANY(%s)",
                        (list(required_permissions),),
                    ).fetchall()
                }
            target_blockers.extend(
                f"missing_target_permission:{code}"
                for code in sorted(required_permissions - available_permissions)
            )
            for datatable in ("credesal_loan_staff_assignment", "credesal_loan_legacy_timeline"):
                registration = conn.execute(
                    "SELECT application_table_name FROM x_registered_table WHERE registered_table_name=%s",
                    (datatable,),
                ).fetchone()
                if not registration or registration[0] != "m_loan":
                    target_blockers.append(f"missing_target_datatable_registration:{datatable}")
            target = {
                "postgres_inspection": "configured", "counts": counts, "loan_products": native_products,
                "source_exact_permissions": sorted(available_permissions),
            }
    target_blockers = sorted(set(target_blockers))
    return {
        "block": BLOCK,
        "scope": {"kind": "loan" if key is not None else "all", "source_key": key},
        "read_ready": not source_blockers,
        "target_ready": bool(target_pg_url) and not target_blockers,
        "ready": not source_blockers and not target_blockers and not implementation_blockers,
        "contract_hash": contract.digest,
        "schema_signature": _schema_signature(schema),
        "target_schema_signature": _schema_signature(target_schema) if target_pg_url else None,
        "source_fingerprint": source_fingerprint(source_config),
        "source_schema": schema,
        "source": {
            "identity": loan_identity,
            "products": products,
            "application_links": application,
            "lifecycle": lifecycle,
            "schedule": schedule,
            "movement_identity": movement_identity,
            "transactions": transaction_inventory,
            "timestamp_coverage": timestamp_coverage,
            "component_audit": components,
            "refinance_graph": {
                **refinance_links,
                "supported_native_path": "fineract_refinancing_settlement_transfers",
                "multi_predecessor_policy": "same_client_atomic_multi_settlement_cross_client_quarantine",
            },
            "restructure_population": {
                **restructure_population,
                "classification": "not_applicable_to_current_loan_portfolio"
                if int(restructure_population.get("linked_loan_count") or 0) == 0
                else "linked_restructure_requires_native_proof",
                "future_linked_row_policy": "whole_loan_quarantine",
            },
            "reversal_pairing": reversal_pairing,
            "historical_schedule_exception": schedule_exception_report,
        },
        "source_blockers": source_blockers,
        "target": target,
        "target_blockers": target_blockers,
        "implementation_blockers": implementation_blockers,
        "blockers": source_blockers + target_blockers + implementation_blockers,
        "note": "The native loan lifecycle writer and Gate 5 reconciliation are registered for reviewed local runs.",
    }
