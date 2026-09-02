from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from .arissto import IDENTIFIER, select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import postgres_connection, postgres_schema


BLOCK = "savings-deposits"
ACCOUNT_SOURCE = "account"
OWNER_SOURCE = "owner"
MOVEMENT_SOURCE = "movement"
PRODUCT_SOURCE = "product"
HISTORY_SOURCE = "history"

REQUIRED_ACCOUNT_TYPES = {"001", "002", "003"}
REQUIRED_ACCOUNT_STATES = {"0", "1", "2", "3", "4"}
REQUIRED_MOVEMENT_LABELS = {
    "APERTURA DE DPF",
    "CANCELACIÓN DE DPF",
    "DEPOSITO DE AHORRO",
    "RETIRO DE AHORRO",
    "CAP. INT. PLAZO FIJO",
    "CAPITALIZACION INTERES",
    "RETENCIÓN DE RENTA-ISR (10%)",
    "NOTA DE ABONO (REVERSION)",
    "NOTA DE CARGO (REVERSION)",
}
REQUIRED_TARGET_COLUMNS = {
    "m_client": {"id", "external_id"},
    "m_savings_product": {
        "id", "name", "short_name", "numbering_code", "deposit_type_enum", "currency_code", "nominal_annual_interest_rate",
        "interest_compounding_period_enum", "interest_posting_period_enum", "interest_calculation_type_enum",
        "interest_calculation_days_in_year_type_enum", "accounting_type", "withhold_tax", "tax_group_id",
    },
    "acc_product_mapping": {"id", "product_id", "product_type", "gl_account_id", "financial_account_type"},
    "acc_gl_account": {"id", "gl_code", "name", "classification_enum", "disabled", "manual_journal_entries_allowed"},
    "m_savings_account": {
        "id", "account_no", "external_id", "client_id", "product_id", "status_enum", "deposit_type_enum",
        "currency_code", "nominal_annual_interest_rate", "interest_compounding_period_enum", "interest_posting_period_enum",
        "interest_calculation_days_in_year_type_enum", "account_balance_derived", "withhold_tax", "tax_group_id",
    },
    "m_savings_account_transaction": {
        "id", "savings_account_id", "transaction_type_enum", "is_reversed", "transaction_date", "amount", "ref_no",
    },
    "m_savings_account_transaction_tax_details": {
        "id", "savings_transaction_id", "tax_component_id", "amount",
    },
    "m_tax_group": {"id", "name"},
    "m_tax_component": {"id", "name", "percentage", "credit_account_type_enum", "credit_account_id", "start_date"},
    "m_tax_group_mappings": {"id", "tax_group_id", "tax_component_id", "start_date", "end_date"},
    "m_permission": {"id", "code", "entity_name", "action_name"},
    "c_configuration": {"id", "name", "enabled"},
    "credesal_savings_migration_account": {
        "id", "source_system", "source_key", "source_hash", "contract_hash", "client_id", "savings_account_id",
        "deposit_type", "cutoff_date", "accrued_interest_exact", "accrued_interest_accounting", "migration_status",
    },
    "credesal_savings_product_map": {
        "id", "source_system", "source_key", "source_hash", "contract_hash", "savings_product_id",
        "arissto_company_id", "arissto_line_id", "deposit_type", "mapping_status",
    },
    "credesal_savings_migration_owner": {
        "id", "migration_account_id", "client_id", "source_system", "source_key", "source_hash", "is_native_owner",
    },
    "credesal_savings_migration_cycle": {
        "id", "migration_account_id", "previous_cycle_id", "source_system", "source_key", "source_hash",
        "contract_hash", "savings_account_id", "cycle_sequence", "source_boundary_history_id",
        "source_opened_on", "source_matures_on", "opening_inference", "cycle_status", "is_current_cycle",
        "migration_status",
    },
    "credesal_savings_native_event_map": {
        "id", "migration_account_id", "source_system", "source_table", "source_key", "source_hash", "contract_hash",
        "migration_cycle_id", "savings_account_id", "savings_transaction_id", "event_kind", "event_status",
        "event_date", "amount",
    },
}


class SavingsDataIssue(RuntimeError):
    """Non-sensitive reason why savings source data is unsafe to migrate."""


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    result = re.sub(r"\s+", " ", str(value).strip())
    return result or None


def date_value(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def decimal_value(value: Any, issue: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SavingsDataIssue(issue) from exc
    if not result.is_finite():
        raise SavingsDataIssue(issue)
    return result


def json_value(value: Any) -> Any:
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
    if isinstance(value, float):
        return repr(value)
    return str(value)


def canonical_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): json_value(value) for key, value in sorted(row.items())}


@dataclass(frozen=True)
class SavingsContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "SavingsContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("version") != 2:
            raise ValueError("Savings mapping requires version 2")
        for section in (
            "source",
            "account_types",
            "account_states",
            "movement_roles",
            "history_roles",
            "ownership",
            "cutoff",
            "interest_basis",
            "interest_schedule",
            "historical_interest_posting",
            "historical_isr",
            "fixed_deposit_cycles",
            "target",
            "write_policy",
            "gl_roles",
            "target_shared_gl",
            "blockers",
        ):
            if section not in value:
                raise ValueError(f"Savings mapping is missing {section!r}")

        source = value["source"]
        target = value["target"]
        table_names = [source.get(name) for name in (
            "product_table",
            "account_table",
            "owner_table",
            "movement_table",
            "history_table",
            "daily_table",
            "daily_close_table",
            "provision_table",
            "party_table",
            "transaction_catalog_table",
            "gl_account_table",
        )]
        target_names = [target.get(name) for name in (
            "client_table",
            "savings_product_table",
            "product_map_table",
            "savings_account_table",
            "savings_transaction_table",
            "migration_account_table",
            "migration_owner_table",
            "migration_cycle_table",
            "event_map_table",
        )]
        key_names: list[Any] = []
        for key_group in ("account_keys", "owner_keys", "movement_keys", "history_keys", "product_keys"):
            keys = source.get(key_group)
            if not isinstance(keys, list) or not keys:
                raise ValueError(f"Savings mapping requires {key_group}")
            key_names.extend(keys)
        cutoff = value["cutoff"]
        cutoff_names = [cutoff.get("date_field")]
        cutoff_names.extend(cutoff.get("exact_field_candidates", []))
        cutoff_names.extend(cutoff.get("accounting_field_candidates", []))
        for selected in (cutoff.get("selected_exact_field"), cutoff.get("selected_accounting_field")):
            if selected is not None:
                cutoff_names.append(selected)
        historical_isr = value["historical_isr"]
        isr_names = [
            historical_isr.get("decision_field"), historical_isr.get("gross_field"),
            historical_isr.get("tax_field"), historical_isr.get("tax_movement_field"),
        ]
        identifiers = [*table_names, *target_names, *key_names, *cutoff_names, *isr_names]
        if not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Unsafe or missing SQL identifier in savings mapping")

        if set(value["account_types"]) != REQUIRED_ACCOUNT_TYPES:
            raise ValueError("Savings account-type mapping must cover 001, 002, and 003")
        for source_type, mapping in value["account_types"].items():
            if mapping.get("disposition") not in {"migrate", "inspect-only"}:
                raise ValueError(f"Savings account type {source_type} has an invalid disposition")
            if mapping.get("target") not in {"savings", "recurring-deposit", "fixed-deposit"}:
                raise ValueError(f"Savings account type {source_type} has an invalid target")

        if set(value["account_states"]) != REQUIRED_ACCOUNT_STATES:
            raise ValueError("Savings state mapping must cover all reviewed source states")
        if set(value["movement_roles"]) != REQUIRED_MOVEMENT_LABELS:
            raise ValueError("Savings movement mapping must cover the reviewed source labels exactly")
        for label, mapping in value["movement_roles"].items():
            if not isinstance(mapping, dict) or not clean_text(mapping.get("role")):
                raise ValueError(f"Savings movement {label!r} requires a role")
            if mapping.get("direction") not in {"1", "2"}:
                raise ValueError(f"Savings movement {label!r} requires direction 1 or 2")

        if value["history_roles"] != {
            "1": "POSTED_INTEREST",
            "2": "CATCH_UP_ACCRUAL_EVIDENCE",
        }:
            raise ValueError("Savings history mapping must preserve reviewed type 1 and 2 meanings")
        if value["ownership"] != {
            "authoritative_source": source["owner_table"],
            "native_primary_rule": "account_master_socio_match",
            "preserve_all_source_owners": True,
        }:
            raise ValueError("Savings ownership mapping must preserve all owners and use the reviewed primary-owner rule")
        if cutoff.get("selection_required") is not True:
            raise ValueError("Savings cutoff field selection must remain an explicit gate")
        if cutoff.get("selected_exact_field") not in {None, *cutoff["exact_field_candidates"]}:
            raise ValueError("Selected exact savings cutoff field is not a reviewed candidate")
        if cutoff.get("selected_accounting_field") not in {None, *cutoff["accounting_field_candidates"]}:
            raise ValueError("Selected accounting savings cutoff field is not a reviewed candidate")
        if cutoff.get("completed_close_value") != "1":
            raise ValueError("Savings cutoff must use completed daily closes")
        if cutoff.get("precision_policy") != "source_operational_amount_plus_native_recalculation":
            raise ValueError("Savings cutoff must retain the source amount and reconstruct native precision")

        if value["interest_basis"] != {
            "source_convention": "actual_calendar_year",
            "target_api_parameter": "interestCalculationDaysInYearType",
            "target_enum_value": 1,
            "target_enum_code": "savingsInterestCalculationDaysInYearType.actual",
            "target_product_column": "interest_calculation_days_in_year_type_enum",
            "target_account_column": "interest_calculation_days_in_year_type_enum",
            "require_product_account_match": True,
        }:
            raise ValueError("Savings interest basis must preserve the reviewed native Actual/Actual contract")
        if value["interest_schedule"] != {
            "source_period_code": "06",
            "source_period_name": "MENSUAL(DIA APERTURA)",
            "anchor_source_column": "FECHA_APERTURA",
            "target_posting_enum_value": 9,
            "target_posting_enum_code": "savingsPostingInterestPeriodType.monthlyOnActivationDate",
            "target_compounding_enum_value": 9,
            "target_compounding_enum_code": "savingsCompoundingInterestPeriodType.monthlyOnActivationDate",
            "short_month_rule": "last_day_then_restore_anchor",
            "require_product_account_match": True,
        }:
            raise ValueError("Savings interest schedule must preserve the reviewed activation-anchored monthly contract")
        if value["historical_interest_posting"] != {
            "source_role": "SAVINGS_INTEREST_POSTING",
            "target_transaction_type_enum": 3,
            "target_transaction_type_code": "savingsAccountTransactionType.interestPosting",
            "target_api_command": "explicitInterestPosting",
            "target_permission": "EXPLICITINTERESTPOSTING_SAVINGSACCOUNT",
            "idempotency_reference_field": "transactionReference",
            "future_interest_policy": "native_actual_actual_calculator",
        }:
            raise ValueError("Savings historical interest must preserve native type-3 postings and future calculation policy")
        if value["historical_isr"] != {
            "decision_field": "APLICA_RENTA",
            "taxed_value": "1",
            "gross_field": "MONTO_INTERES",
            "tax_field": "MONTO_RENTA",
            "tax_movement_field": "ID_MOV_AHO_RENTA",
            "rate_percent": 10,
            "target_transaction_type_enum": 18,
            "target_transaction_type_code": "savingsAccountTransactionType.withholdTax",
            "target_api_command": "explicitWithholdTax",
            "target_permission": "EXPLICITWITHHOLDTAX_SAVINGSACCOUNT",
            "posting_account": "linked_vista",
            "tax_group_required": True,
            "automatic_withholding_enabled": False,
            "idempotency_reference_field": "transactionReference",
            "future_eligibility_policy": "separate_business_rule_required",
        }:
            raise ValueError("Savings historical ISR must preserve the reviewed event-level linked-VISTA contract")
        if value["fixed_deposit_cycles"] != {
            "source_account_type": "003",
            "renewal_boundary_history_type": "2",
            "posted_interest_history_type": "1",
            "initial_opening_precedence": [
                "nonreversed_opening_movement",
                "first_renewal_minus_term_days",
                "account_master_opening",
            ],
            "cycle_end_semantics": "exclusive",
            "allowed_next_cycle_gap_days": [0, 1],
            "historical_maturity_instruction_id": 400,
            "historical_maturity_instruction": "reinvest_principal_only",
            "current_native_account_pointer": "credesal_savings_migration_account.savings_account_id",
        }:
            raise ValueError("Savings DPF cycles must preserve the reviewed native renewal-chain contract")

        batch_size = int(target.get("batch_size", 0))
        if batch_size < 1 or batch_size > 2000:
            raise ValueError("Savings batch size must be between 1 and 2000")
        if target.get("currency") != "USD":
            raise ValueError("Savings mapping currently requires the reviewed USD currency")
        if value["write_policy"] != {
            "native_financial_tables": "api-domain-only",
            "extension_tables": "controlled-sql",
            "sequential_by_account": True,
            "chronological_within_account": True,
            "account_atomic_quarantine": True,
        }:
            raise ValueError("Savings write policy cannot weaken native financial-table safety")
        if value["gl_roles"] != {
            "savingsControlAccountId": "ID_CUENTA",
            "interestOnSavingsAccountId": "ID_CUENTA_CAPIT",
            "interestPayableAccountId": "ID_CUENTA_PROVI",
            "taxComponentCreditAccountId": "ID_CUENTA_RENTA",
        }:
            raise ValueError("Savings GL roles must preserve the reviewed Arissto line mappings")
        if value["target_shared_gl"] != {
            "savingsReferenceAccountId": {"gl_code": "1110040202", "classification_enum": 1},
            "transfersInSuspenseAccountId": {"gl_code": "213005", "classification_enum": 2},
            "incomeFromFeeAccountId": {"gl_code": "6420", "classification_enum": 4},
            "incomeFromPenaltyAccountId": {"gl_code": "6430", "classification_enum": 4},
            "feesReceivableAccountId": {"gl_code": "1530", "classification_enum": 1},
            "penaltiesReceivableAccountId": {"gl_code": "1540", "classification_enum": 1},
        }:
            raise ValueError("Savings shared target GL mapping must preserve the reviewed local accounting convention")
        if not isinstance(value["blockers"], list):
            raise ValueError("Savings mapping blockers must be a list")
        return cls(value)

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True).encode()).hexdigest()

    @property
    def cutoff_ready(self) -> bool:
        cutoff = self.raw["cutoff"]
        return bool(cutoff.get("selected_exact_field") and cutoff.get("selected_accounting_field"))

    def _source_key(self, table_name: str, columns: list[str], row: dict[str, Any]) -> str:
        parts = [table_name]
        for column in columns:
            value = clean_text(row.get(column))
            if value is None:
                raise SavingsDataIssue(f"missing_source_key:{table_name}:{column}")
            parts.append(quote(value, safe=""))
        return "|".join(parts)

    def source_key(self, kind: str, row: dict[str, Any]) -> str:
        source = self.raw["source"]
        mapping = {
            ACCOUNT_SOURCE: (source["account_table"], source["account_keys"]),
            OWNER_SOURCE: (source["owner_table"], source["owner_keys"]),
            MOVEMENT_SOURCE: (source["movement_table"], source["movement_keys"]),
            PRODUCT_SOURCE: (source["product_table"], source["product_keys"]),
            HISTORY_SOURCE: (source["history_table"], source["history_keys"]),
        }
        if kind not in mapping:
            raise ValueError(f"Unsupported savings source-key kind: {kind}")
        table_name, columns = mapping[kind]
        return self._source_key(table_name, columns, row)

    def parse_account_source_key(self, value: str) -> tuple[str, str, str]:
        source = self.raw["source"]
        parts = value.split("|")
        if len(parts) != 4 or parts[0] != source["account_table"]:
            raise ValueError("Savings source key must be AHO_CUENTA_AHORRO|ID_EMPRESA|ID_SUCURSAL|ID_CUENTA_AHORRO")
        decoded = tuple(unquote(part).strip() for part in parts[1:])
        if not all(decoded):
            raise ValueError("Savings account source-key components cannot be blank")
        return decoded  # type: ignore[return-value]

    def account_type(self, value: Any) -> dict[str, Any]:
        source_type = clean_text(value)
        mapping = self.raw["account_types"].get(source_type or "")
        if mapping is None:
            raise SavingsDataIssue("unmapped_savings_account_type")
        return dict(mapping)

    def account_state(self, value: Any) -> str:
        source_state = clean_text(value)
        mapping = self.raw["account_states"].get(source_state or "")
        if mapping is None:
            raise SavingsDataIssue("unmapped_savings_account_state")
        return str(mapping)

    def history_role(self, value: Any) -> str:
        source_type = clean_text(value)
        mapping = self.raw["history_roles"].get(source_type or "")
        if mapping is None:
            raise SavingsDataIssue("unmapped_savings_history_type")
        return str(mapping)

    def fixed_deposit_cycles(
        self,
        account: dict[str, Any],
        opening_movements: list[dict[str, Any]],
        history_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build one native Fineract fixed-deposit term per Arissto DPF cycle."""
        if clean_text(account.get("ID_TIPO_CUENTA_AHORRO")) != "003":
            raise SavingsDataIssue("fixed_deposit_cycle_non_dpf_account")
        term_days = int(account.get("PLAZO") or 0)
        if term_days <= 0:
            raise SavingsDataIssue("fixed_deposit_cycle_invalid_term")
        current_opening = date_value(account.get("FECHA_APERTURA"))
        current_maturity = date_value(account.get("FECHA_VENCIMIENTO"))
        if current_opening is None or current_maturity is None:
            raise SavingsDataIssue("fixed_deposit_cycle_missing_current_dates")

        boundary_type = self.raw["fixed_deposit_cycles"]["renewal_boundary_history_type"]
        boundaries = sorted(
            (row for row in history_rows if clean_text(row.get("TIPO_HISTORICO")) == boundary_type),
            key=lambda row: (
                date_value(row.get("FECHA_APERTURA")) or date.min,
                date_value(row.get("FECHA_VENCIMIENTO")) or date.min,
                clean_text(row.get("ID_HISTORICO")) or "",
            ),
        )
        valid_openings = sorted(
            event_date
            for row in opening_movements
            if clean_text(row.get("REVERSION")) != "1"
            if (
                event_date := next(
                    (
                        date_value(row.get(column))
                        for column in ("FECHA_OPERACION", "DT_MOVIMIENTO", "DT_CREO")
                        if row.get(column) not in (None, "")
                    ),
                    None,
                )
            ) is not None
        )
        if valid_openings:
            initial_opening = valid_openings[0]
            opening_inference = "NONREVERSED_OPENING_MOVEMENT"
        elif boundaries:
            first_boundary = date_value(boundaries[0].get("FECHA_APERTURA"))
            if first_boundary is None:
                raise SavingsDataIssue("fixed_deposit_cycle_invalid_boundary")
            initial_opening = first_boundary - timedelta(days=term_days)
            opening_inference = "FIRST_RENEWAL_MINUS_TERM_DAYS"
        else:
            initial_opening = current_opening
            opening_inference = "ACCOUNT_MASTER_OPENING"

        # One reviewed DPF was contractually opened on the master date and
        # funded on the following day. With no renewal boundary, the master
        # dates define the term while the movement remains the native funding
        # event. Do not shift the contractual maturity by one day.
        if not boundaries and abs((initial_opening - current_opening).days) <= 1:
            if initial_opening != current_opening:
                opening_inference = "ACCOUNT_MASTER_WITH_ADJACENT_FUNDING"
            initial_opening = current_opening

        account_key = self.source_key(ACCOUNT_SOURCE, account)
        first_maturity = date_value(boundaries[0].get("FECHA_APERTURA")) if boundaries else current_maturity
        raw_cycles = [{
            "source_key": f"{account_key}|DPF-CYCLE|INITIAL",
            "source_boundary_history_id": None,
            "source_opened_on": initial_opening,
            "source_matures_on": first_maturity,
            "opening_inference": opening_inference,
        }]
        for row in boundaries:
            raw_cycles.append({
                "source_key": f"{self.source_key(HISTORY_SOURCE, row)}|DPF-CYCLE",
                "source_boundary_history_id": clean_text(row.get("ID_HISTORICO")),
                "source_opened_on": date_value(row.get("FECHA_APERTURA")),
                "source_matures_on": date_value(row.get("FECHA_VENCIMIENTO")),
                "opening_inference": "TYPE_2_RENEWAL_BOUNDARY",
            })

        allowed_gaps = set(self.raw["fixed_deposit_cycles"]["allowed_next_cycle_gap_days"])
        current_state = self.account_state(account.get("ESTADO_CUENTA"))
        cycles: list[dict[str, Any]] = []
        for index, cycle in enumerate(raw_cycles, start=1):
            opened_on = cycle["source_opened_on"]
            matures_on = cycle["source_matures_on"]
            if opened_on is None or matures_on is None or matures_on <= opened_on:
                raise SavingsDataIssue("fixed_deposit_cycle_invalid_dates")
            if cycles:
                gap = (opened_on - cycles[-1]["source_matures_on"]).days
                if gap not in allowed_gaps:
                    raise SavingsDataIssue("fixed_deposit_cycle_unreviewed_boundary_gap")
            is_current = index == len(raw_cycles)
            cycle.update({
                "cycle_sequence": index,
                "cycle_status": current_state if is_current else "RENEWED",
                "is_current_cycle": is_current,
            })
            cycles.append(cycle)

        current = cycles[-1]
        if current["source_opened_on"] != current_opening or current["source_matures_on"] != current_maturity:
            raise SavingsDataIssue("fixed_deposit_cycle_current_master_mismatch")
        return cycles

    def fixed_deposit_history_cycle(
        self, history_row: dict[str, Any], cycles: list[dict[str, Any]]
    ) -> dict[str, Any]:
        event_date = date_value(history_row.get("FECHA_APERTURA"))
        if event_date is None:
            raise SavingsDataIssue("fixed_deposit_history_missing_date")
        matches = [
            cycle
            for cycle in cycles
            if cycle["source_opened_on"] <= event_date < cycle["source_matures_on"]
        ]
        if len(matches) != 1:
            raise SavingsDataIssue("fixed_deposit_history_cycle_placement")
        return matches[0]

    def movement_event(self, row: dict[str, Any], transaction_label: Any) -> dict[str, Any]:
        label = clean_text(transaction_label)
        mapping = self.raw["movement_roles"].get(label or "")
        if mapping is None:
            raise SavingsDataIssue("unmapped_savings_movement")
        direction = clean_text(row.get("TIPO_MOVIMIENTO"))
        if direction != mapping["direction"]:
            raise SavingsDataIssue("savings_movement_direction_mismatch")
        amount = decimal_value(row.get("MONTO"), "invalid_savings_movement_amount")
        if amount <= 0:
            raise SavingsDataIssue("nonpositive_savings_movement_amount")
        event_date = next((date_value(row.get(column)) for column in (
            "FECHA_OPERACION", "DT_MOVIMIENTO", "DT_CREO"
        ) if row.get(column) not in (None, "")), None)
        if event_date is None:
            raise SavingsDataIssue("missing_savings_movement_date")
        return {
            "source_key": self.source_key(MOVEMENT_SOURCE, row),
            "role": mapping["role"],
            "direction": direction,
            "event_date": event_date.isoformat(),
            "amount": format(amount, "f"),
            "is_reversal": clean_text(row.get("REVERSION")) == "1",
            "previous_balance": (
                format(decimal_value(row["SALDO_ANTERIOR"], "invalid_savings_previous_balance"), "f")
                if row.get("SALDO_ANTERIOR") is not None else None
            ),
            "final_balance": (
                format(decimal_value(row["SALDO_FINAL"], "invalid_savings_final_balance"), "f")
                if row.get("SALDO_FINAL") is not None else None
            ),
        }

    def hash_record(self, kind: str, source_key: str, payload: dict[str, Any]) -> str:
        material = {
            "contract": self.contract_hash,
            "kind": kind,
            "source_key": source_key,
            "payload": canonical_payload(payload),
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source_requirements(contract: SavingsContract) -> dict[str, set[str]]:
    source = contract.raw["source"]
    cutoff = contract.raw["cutoff"]
    historical_isr = contract.raw["historical_isr"]
    return {
        source["product_table"]: {
            "ID_EMPRESA", "ID_LINEA_AHORRO", "ID_TIPO_CUENTA_AHORRO", "LINEA_AHORRO", "PORCENTAJE_INTERES",
            "PERIODO_CAPITALIZACION", "METODO_CAPITALIZACION", "AFECTA_ISR",
        },
        source["account_table"]: {
            "ID_EMPRESA", "ID_SUCURSAL", "ID_CUENTA_AHORRO", "NO_CUENTA", "ID_LINEA_AHORRO", "ESTADO_CUENTA",
            "SALDO", "PORCENTAJE_INTERES", "FECHA_APERTURA", "FECHA_VENCIMIENTO", "PLAZO", "ID_AHORRO",
            "ID_EMPRESA_CAP", "ID_SUCURSAL_CAP", "ID_CUENTA_CAP", "ULTIMA_FECHA_CALC",
            "ID_SUCURSAL_SOCIO", "ID_SOCIO",
            *cutoff["exact_field_candidates"], *cutoff["accounting_field_candidates"],
        },
        source["owner_table"]: {
            "ID_EMPRESA", "ID_SUCURSAL", "ID_CUENTA_AHORRO", "ID_PROPIETARIO", "ID_SUCURSAL_SOCIO", "ID_SOCIO",
        },
        source["movement_table"]: {
            "ID_AHO_MOVIMIENTO", "ID_EMPRESA", "ID_SUCURSAL", "ID_SUCURSAL_CUENTA", "ID_CUENTA_AHORRO",
            "ID_MOVIMIENTO_AHORRO",
            "CODIGO_SISTEMA", "ID_TRANSACCION", "TIPO_MOVIMIENTO", "MONTO", "FECHA_OPERACION", "DT_MOVIMIENTO",
            "DT_CREO", "SALDO_ANTERIOR", "SALDO_FINAL", "REVERSION",
        },
        source["history_table"]: {
            "ID_EMPRESA", "ID_SUCURSAL", "ID_CUENTA_AHORRO", "ID_HISTORICO", "TIPO_HISTORICO", "MONTO_INTERES",
            "FECHA_APERTURA", "FECHA_VENCIMIENTO",
            "MONTO_RENTA", "APLICA_RENTA", "ID_MOVIMIENTO_AHORRO", "ID_MOV_AHO_RENTA",
            historical_isr["decision_field"], historical_isr["gross_field"], historical_isr["tax_field"],
            historical_isr["tax_movement_field"],
        },
        source["daily_table"]: {
            "ID_AHORRO", "ID_CIERRE_DIARIO", cutoff["selected_exact_field"], cutoff["selected_accounting_field"],
        },
        source["daily_close_table"]: {"ID_CIERRE_DIARIO", cutoff["date_field"], "CIERRE"},
        source["provision_table"]: set(),
        source["party_table"]: {"ID_EMPRESA", "ID_SUCURSAL", "ID_SOCIO", "NUMERO_AFILIACION"},
        source["transaction_catalog_table"]: {"CODIGO_SISTEMA", "ID_TRANSACCION", "TRANSACCION"},
        source["gl_account_table"]: {"ID_EMPRESA", "ID_CUENTA", "CODIGO_CUENTA", "NOMBRE_CUENTA"},
    }


def _schema_signature(source_tables: list[dict[str, Any]], target_schema: dict[str, dict[str, str]]) -> str:
    material = {"source_tables": source_tables, "target_schema": target_schema}
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inspect_savings(settings: Settings, contract: SavingsContract) -> dict[str, Any]:
    requirements = _source_requirements(contract)
    source_schema: list[dict[str, Any]] = []
    blockers: list[str] = []
    source = contract.raw["source"]
    cutoff = contract.raw["cutoff"]
    historical_interest = contract.raw["historical_interest_posting"]
    historical_isr = contract.raw["historical_isr"]
    with source_connection(settings.source) as conn:
        for table, required_columns in requirements.items():
            columns = select_rows(
                conn,
                "SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
                ("dbo", table),
            )
            available = {str(row["column_name"]) for row in columns}
            missing = sorted(required_columns - available)
            source_schema.append({
                "table": table,
                "column_count": len(columns),
                "missing_required_columns": missing,
            })
            if not columns:
                blockers.append(f"missing_source_table:{table}")
            for column in missing:
                blockers.append(f"missing_source_column:{table}:{column}")

        account_rows = select_rows(conn, f"""
            SELECT RTRIM(l.ID_TIPO_CUENTA_AHORRO) AS account_type,
                   RTRIM(a.ESTADO_CUENTA) AS account_state,
                   COUNT(*) AS account_count,
                   CAST(COALESCE(SUM(a.SALDO),0) AS DECIMAL(20,2)) AS balance
            FROM [dbo].[{source['account_table']}] a
            JOIN [dbo].[{source['product_table']}] l
              ON l.ID_EMPRESA=a.ID_EMPRESA AND l.ID_LINEA_AHORRO=a.ID_LINEA_AHORRO
            GROUP BY l.ID_TIPO_CUENTA_AHORRO,a.ESTADO_CUENTA
            ORDER BY l.ID_TIPO_CUENTA_AHORRO,a.ESTADO_CUENTA
        """)
        owner_rows = select_rows(conn, f"""
            WITH owner_counts AS (
                SELECT ID_EMPRESA,ID_SUCURSAL,ID_CUENTA_AHORRO,COUNT(*) AS owner_count
                FROM [dbo].[{source['owner_table']}]
                GROUP BY ID_EMPRESA,ID_SUCURSAL,ID_CUENTA_AHORRO
            ), joint_designation AS (
                SELECT oc.ID_EMPRESA,oc.ID_SUCURSAL,oc.ID_CUENTA_AHORRO,
                       SUM(CASE WHEN p.ID_SOCIO=a.ID_SOCIO AND p.ID_SUCURSAL_SOCIO=a.ID_SUCURSAL_SOCIO
                                THEN 1 ELSE 0 END) AS primary_matches
                FROM owner_counts oc
                JOIN [dbo].[{source['account_table']}] a
                  ON a.ID_EMPRESA=oc.ID_EMPRESA AND a.ID_SUCURSAL=oc.ID_SUCURSAL
                 AND a.ID_CUENTA_AHORRO=oc.ID_CUENTA_AHORRO
                JOIN [dbo].[{source['owner_table']}] p
                  ON p.ID_EMPRESA=oc.ID_EMPRESA AND p.ID_SUCURSAL=oc.ID_SUCURSAL
                 AND p.ID_CUENTA_AHORRO=oc.ID_CUENTA_AHORRO
                WHERE oc.owner_count>1
                GROUP BY oc.ID_EMPRESA,oc.ID_SUCURSAL,oc.ID_CUENTA_AHORRO
            )
            SELECT (SELECT COUNT(*) FROM [dbo].[{source['owner_table']}]) AS ownership_links,
                   (SELECT COUNT(*) FROM owner_counts) AS owned_accounts,
                   (SELECT SUM(CASE WHEN owner_count>1 THEN 1 ELSE 0 END) FROM owner_counts) AS joint_accounts,
                   (SELECT MAX(owner_count) FROM owner_counts) AS maximum_owner_count,
                   (SELECT COUNT(*) FROM joint_designation WHERE primary_matches=1) AS joint_accounts_with_unique_primary,
                   (SELECT COUNT(*) FROM joint_designation WHERE primary_matches<>1) AS joint_accounts_with_ambiguous_primary
        """)[0]
        movement_rows = select_rows(conn, f"""
            SELECT RTRIM(t.TRANSACCION) AS transaction_label,
                   RTRIM(m.TIPO_MOVIMIENTO) AS direction,
                   CASE WHEN COALESCE(RTRIM(m.REVERSION),'')='1' THEN 1 ELSE 0 END AS reversed,
                   COUNT(*) AS movement_count,
                   CAST(COALESCE(SUM(m.MONTO),0) AS DECIMAL(20,2)) AS amount
            FROM [dbo].[{source['movement_table']}] m
            LEFT JOIN [dbo].[{source['transaction_catalog_table']}] t
              ON t.CODIGO_SISTEMA=m.CODIGO_SISTEMA AND t.ID_TRANSACCION=m.ID_TRANSACCION
            GROUP BY t.TRANSACCION,m.TIPO_MOVIMIENTO,
                     CASE WHEN COALESCE(RTRIM(m.REVERSION),'')='1' THEN 1 ELSE 0 END
            ORDER BY t.TRANSACCION,m.TIPO_MOVIMIENTO,reversed
        """)
        history_rows = select_rows(conn, f"""
            SELECT RTRIM(TIPO_HISTORICO) AS history_type,
                   COUNT(*) AS history_count,
                   CAST(COALESCE(SUM(MONTO_INTERES),0) AS DECIMAL(20,2)) AS interest_amount,
                   CAST(COALESCE(SUM(MONTO_RENTA),0) AS DECIMAL(20,2)) AS tax_amount,
                   SUM(CASE WHEN ID_MOVIMIENTO_AHORRO IS NOT NULL THEN 1 ELSE 0 END) AS linked_movement_count
            FROM [dbo].[{source['history_table']}]
            GROUP BY TIPO_HISTORICO ORDER BY TIPO_HISTORICO
        """)
        dpf_cycle_rows = select_rows(conn, f"""
            WITH dpf AS (
                SELECT a.ID_EMPRESA,a.ID_SUCURSAL,a.ID_CUENTA_AHORRO,a.PLAZO,
                       CAST(a.FECHA_APERTURA AS date) current_opening,
                       CAST(a.FECHA_VENCIMIENTO AS date) current_maturity
                FROM [dbo].[{source['account_table']}] a
                JOIN [dbo].[{source['product_table']}] l
                  ON l.ID_EMPRESA=a.ID_EMPRESA AND l.ID_LINEA_AHORRO=a.ID_LINEA_AHORRO
                WHERE RTRIM(l.ID_TIPO_CUENTA_AHORRO)='003'
            ), openings AS (
                SELECT m.ID_EMPRESA,m.ID_SUCURSAL_CUENTA AS ID_SUCURSAL,m.ID_CUENTA_AHORRO,
                       MIN(CASE WHEN COALESCE(RTRIM(m.REVERSION),'')<>'1'
                                THEN CAST(m.FECHA_OPERACION AS date) END) AS first_opening
                FROM [dbo].[{source['movement_table']}] m
                JOIN [dbo].[{source['transaction_catalog_table']}] t
                  ON t.CODIGO_SISTEMA=m.CODIGO_SISTEMA AND t.ID_TRANSACCION=m.ID_TRANSACCION
                JOIN dpf d ON d.ID_EMPRESA=m.ID_EMPRESA AND d.ID_SUCURSAL=m.ID_SUCURSAL_CUENTA
                          AND d.ID_CUENTA_AHORRO=m.ID_CUENTA_AHORRO
                WHERE RTRIM(t.TRANSACCION)='APERTURA DE DPF'
                GROUP BY m.ID_EMPRESA,m.ID_SUCURSAL_CUENTA,m.ID_CUENTA_AHORRO
            ), boundaries AS (
                SELECT h.ID_EMPRESA,h.ID_SUCURSAL,h.ID_CUENTA_AHORRO,RTRIM(h.ID_HISTORICO) history_id,
                       CAST(h.FECHA_APERTURA AS date) cycle_start,
                       CAST(h.FECHA_VENCIMIENTO AS date) cycle_end,
                       LEAD(CAST(h.FECHA_APERTURA AS date)) OVER (
                           PARTITION BY h.ID_EMPRESA,h.ID_SUCURSAL,h.ID_CUENTA_AHORRO
                           ORDER BY h.FECHA_APERTURA,h.FECHA_VENCIMIENTO,h.ID_HISTORICO
                       ) AS next_start,
                       ROW_NUMBER() OVER (
                           PARTITION BY h.ID_EMPRESA,h.ID_SUCURSAL,h.ID_CUENTA_AHORRO
                           ORDER BY h.FECHA_APERTURA DESC,h.FECHA_VENCIMIENTO DESC,h.ID_HISTORICO DESC
                       ) AS reverse_sequence
                FROM [dbo].[{source['history_table']}] h
                JOIN dpf d ON d.ID_EMPRESA=h.ID_EMPRESA AND d.ID_SUCURSAL=h.ID_SUCURSAL
                          AND d.ID_CUENTA_AHORRO=h.ID_CUENTA_AHORRO
                WHERE RTRIM(h.TIPO_HISTORICO)='2'
            ), cycles AS (
                SELECT d.ID_EMPRESA,d.ID_SUCURSAL,d.ID_CUENTA_AHORRO,'INITIAL' AS history_id,
                       COALESCE(o.first_opening,
                                DATEADD(day,-d.PLAZO,(SELECT MIN(b.cycle_start) FROM boundaries b
                                                     WHERE b.ID_EMPRESA=d.ID_EMPRESA AND b.ID_SUCURSAL=d.ID_SUCURSAL
                                                       AND b.ID_CUENTA_AHORRO=d.ID_CUENTA_AHORRO)),
                                d.current_opening) AS cycle_start,
                       COALESCE((SELECT MIN(b.cycle_start) FROM boundaries b
                                 WHERE b.ID_EMPRESA=d.ID_EMPRESA AND b.ID_SUCURSAL=d.ID_SUCURSAL
                                   AND b.ID_CUENTA_AHORRO=d.ID_CUENTA_AHORRO),d.current_maturity) AS cycle_end
                FROM dpf d LEFT JOIN openings o
                  ON o.ID_EMPRESA=d.ID_EMPRESA AND o.ID_SUCURSAL=d.ID_SUCURSAL
                 AND o.ID_CUENTA_AHORRO=d.ID_CUENTA_AHORRO
                UNION ALL
                SELECT ID_EMPRESA,ID_SUCURSAL,ID_CUENTA_AHORRO,history_id,cycle_start,cycle_end FROM boundaries
            ), posted AS (
                SELECT h.ID_EMPRESA,h.ID_SUCURSAL,h.ID_CUENTA_AHORRO,RTRIM(h.ID_HISTORICO) history_id,
                       CAST(h.FECHA_APERTURA AS date) posted_on
                FROM [dbo].[{source['history_table']}] h JOIN dpf d
                  ON d.ID_EMPRESA=h.ID_EMPRESA AND d.ID_SUCURSAL=h.ID_SUCURSAL
                 AND d.ID_CUENTA_AHORRO=h.ID_CUENTA_AHORRO
                WHERE RTRIM(h.TIPO_HISTORICO)='1'
            ), placement AS (
                SELECT p.ID_EMPRESA,p.ID_SUCURSAL,p.ID_CUENTA_AHORRO,p.history_id,
                       COUNT(c.history_id) matching_cycles
                FROM posted p LEFT JOIN cycles c
                  ON c.ID_EMPRESA=p.ID_EMPRESA AND c.ID_SUCURSAL=p.ID_SUCURSAL
                 AND c.ID_CUENTA_AHORRO=p.ID_CUENTA_AHORRO
                 AND p.posted_on>=c.cycle_start AND p.posted_on<c.cycle_end
                GROUP BY p.ID_EMPRESA,p.ID_SUCURSAL,p.ID_CUENTA_AHORRO,p.history_id
            )
            SELECT (SELECT COUNT(*) FROM dpf) AS dpf_accounts,
                   (SELECT COUNT(*) FROM cycles) AS cycle_count,
                   (SELECT COUNT(*) FROM boundaries) AS renewal_boundary_count,
                   (SELECT COUNT(DISTINCT CONCAT(ID_EMPRESA,'|',ID_SUCURSAL,'|',ID_CUENTA_AHORRO))
                      FROM boundaries) AS accounts_with_renewals,
                   (SELECT COUNT(*) FROM cycles
                     WHERE cycle_start IS NULL OR cycle_end IS NULL OR cycle_end<=cycle_start) AS invalid_cycles,
                   (SELECT COUNT(*) FROM boundaries
                     WHERE next_start IS NOT NULL AND DATEDIFF(day,cycle_end,next_start) NOT IN (0,1))
                       AS unreviewed_boundary_gaps,
                   (SELECT COUNT(*) FROM boundaries b JOIN dpf d
                     ON d.ID_EMPRESA=b.ID_EMPRESA AND d.ID_SUCURSAL=b.ID_SUCURSAL
                    AND d.ID_CUENTA_AHORRO=b.ID_CUENTA_AHORRO
                     WHERE b.reverse_sequence=1
                       AND (b.cycle_start<>d.current_opening OR b.cycle_end<>d.current_maturity))
                       AS current_master_mismatches,
                   (SELECT COUNT(*) FROM placement) AS posted_interest_rows,
                   (SELECT COUNT(*) FROM placement WHERE matching_cycles=0) AS unplaced_interest_rows,
                   (SELECT COUNT(*) FROM placement WHERE matching_cycles>1) AS multiply_placed_interest_rows
        """)
        cutoff_rows = select_rows(conn, f"""
            WITH cutoff AS (
                SELECT MAX(CAST(c.{cutoff['date_field']} AS date)) AS cutoff_date
                FROM [dbo].[{source['daily_close_table']}] c
                JOIN [dbo].[{source['daily_table']}] d
                  ON d.ID_CIERRE_DIARIO=c.ID_CIERRE_DIARIO
                WHERE RTRIM(c.CIERRE)=?
            ), snapshot AS (
                SELECT d.*
                FROM [dbo].[{source['daily_table']}] d
                JOIN [dbo].[{source['daily_close_table']}] c
                  ON c.ID_CIERRE_DIARIO=d.ID_CIERRE_DIARIO
                CROSS JOIN cutoff x
                WHERE CAST(c.{cutoff['date_field']} AS date)=x.cutoff_date
                  AND RTRIM(c.CIERRE)=?
            )
            SELECT MAX(x.cutoff_date) AS cutoff_date,
                   COUNT_BIG(s.ID_AHORRO) AS snapshot_rows,
                   COUNT_BIG(DISTINCT s.ID_AHORRO) AS distinct_accounts,
                   SUM(CASE WHEN COALESCE(s.{cutoff['selected_exact_field']},0)<>0 THEN 1 ELSE 0 END)
                       AS nonzero_accrual_accounts,
                   CAST(COALESCE(SUM(s.{cutoff['selected_exact_field']}),0) AS DECIMAL(20,8))
                       AS accrued_interest_exact,
                   CAST(COALESCE(SUM(s.{cutoff['selected_accounting_field']}),0) AS DECIMAL(20,8))
                       AS accrued_interest_accounting
            FROM cutoff x LEFT JOIN snapshot s ON 1=1
        """, (cutoff["completed_close_value"], cutoff["completed_close_value"]))
        isr_rows = select_rows(conn, f"""
            SELECT
                SUM(CASE WHEN RTRIM(h.TIPO_HISTORICO)='1'
                              AND RTRIM(h.{historical_isr['decision_field']})=? THEN 1 ELSE 0 END) AS taxed_events,
                CAST(COALESCE(SUM(CASE WHEN RTRIM(h.TIPO_HISTORICO)='1'
                                           AND RTRIM(h.{historical_isr['decision_field']})=?
                                      THEN h.{historical_isr['gross_field']} ELSE 0 END),0)
                     AS DECIMAL(20,2)) AS taxed_gross_interest,
                CAST(COALESCE(SUM(CASE WHEN RTRIM(h.TIPO_HISTORICO)='1'
                                           AND RTRIM(h.{historical_isr['decision_field']})=?
                                      THEN h.{historical_isr['tax_field']} ELSE 0 END),0)
                     AS DECIMAL(20,2)) AS withheld_tax,
                SUM(CASE WHEN RTRIM(h.TIPO_HISTORICO)='1'
                              AND RTRIM(h.{historical_isr['decision_field']})=?
                              AND ABS(h.{historical_isr['tax_field']}
                                  - ROUND(h.{historical_isr['gross_field']} * ? / 100.0,2)) > 0.001
                         THEN 1 ELSE 0 END) AS rate_mismatches,
                SUM(CASE WHEN RTRIM(h.TIPO_HISTORICO)='1'
                              AND RTRIM(h.{historical_isr['decision_field']})=?
                              AND (tax.ID_AHO_MOVIMIENTO IS NULL OR RTRIM(t.TRANSACCION)<>?
                                   OR RTRIM(tax.TIPO_MOVIMIENTO)<>'2'
                                   OR ABS(tax.MONTO-h.{historical_isr['tax_field']})>0.001)
                         THEN 1 ELSE 0 END) AS linked_movement_mismatches,
                SUM(CASE WHEN RTRIM(h.TIPO_HISTORICO)='1'
                              AND COALESCE(RTRIM(h.{historical_isr['decision_field']}),'')<>?
                              AND COALESCE(h.{historical_isr['tax_field']},0)<>0
                         THEN 1 ELSE 0 END) AS untaxed_event_mismatches,
                SUM(CASE WHEN RTRIM(h.TIPO_HISTORICO)='1'
                              AND COALESCE(RTRIM(h.{historical_isr['decision_field']}),'')<>?
                              AND COALESCE(TRY_CONVERT(bigint,h.{historical_isr['tax_movement_field']}),0)<>0
                         THEN 1 ELSE 0 END) AS untaxed_nonzero_tax_links,
                SUM(CASE WHEN RTRIM(h.TIPO_HISTORICO)='2'
                              AND (COALESCE(h.{historical_isr['tax_field']},0)<>0
                                   OR h.{historical_isr['tax_movement_field']} IS NOT NULL)
                         THEN 1 ELSE 0 END) AS catch_up_tax_mismatches
            FROM [dbo].[{source['history_table']}] h
            LEFT JOIN [dbo].[{source['movement_table']}] tax
              ON tax.ID_MOVIMIENTO_AHORRO=h.{historical_isr['tax_movement_field']}
            LEFT JOIN [dbo].[{source['transaction_catalog_table']}] t
              ON t.CODIGO_SISTEMA=tax.CODIGO_SISTEMA AND t.ID_TRANSACCION=tax.ID_TRANSACCION
        """, (
            historical_isr["taxed_value"], historical_isr["taxed_value"], historical_isr["taxed_value"],
            historical_isr["taxed_value"], historical_isr["rate_percent"], historical_isr["taxed_value"],
            "RETENCIÓN DE RENTA-ISR (10%)", historical_isr["taxed_value"], historical_isr["taxed_value"],
        ))
        source_product_rows = select_rows(conn, f"""
            SELECT RTRIM(l.ID_EMPRESA) AS company_id,RTRIM(l.ID_LINEA_AHORRO) AS line_id,
                   RTRIM(l.LINEA_AHORRO) AS line_name,RTRIM(l.ID_TIPO_CUENTA_AHORRO) AS account_type,
                   l.PORCENTAJE_INTERES AS default_rate,l.PLAZO_INI AS minimum_term_days,
                   l.PLAZO_FIN AS maximum_term_days,RTRIM(l.PERIODO_CAPITALIZACION) AS capitalization_period,
                   RTRIM(l.METODO_CAPITALIZACION) AS capitalization_method,l.AFECTA_ISR AS tax_capable,
                   RTRIM(principal.CODIGO_CUENTA) AS principal_gl,
                   RTRIM(expense.CODIGO_CUENTA) AS interest_expense_gl,
                   RTRIM(payable.CODIGO_CUENTA) AS interest_payable_gl,
                   RTRIM(tax.CODIGO_CUENTA) AS tax_gl,
                   COUNT(a.ID_AHORRO) AS account_count,
                   MIN(a.PORCENTAJE_INTERES) AS observed_minimum_rate,
                   MAX(a.PORCENTAJE_INTERES) AS observed_maximum_rate
            FROM [dbo].[{source['product_table']}] l
            LEFT JOIN [dbo].[{source['gl_account_table']}] principal
              ON principal.ID_EMPRESA=l.ID_EMPRESA AND principal.ID_CUENTA=l.ID_CUENTA
            LEFT JOIN [dbo].[{source['gl_account_table']}] expense
              ON expense.ID_EMPRESA=l.ID_EMPRESA AND expense.ID_CUENTA=l.ID_CUENTA_CAPIT
            LEFT JOIN [dbo].[{source['gl_account_table']}] payable
              ON payable.ID_EMPRESA=l.ID_EMPRESA AND payable.ID_CUENTA=l.ID_CUENTA_PROVI
            LEFT JOIN [dbo].[{source['gl_account_table']}] tax
              ON tax.ID_EMPRESA=l.ID_EMPRESA AND tax.ID_CUENTA=l.ID_CUENTA_RENTA
            LEFT JOIN [dbo].[{source['account_table']}] a
              ON a.ID_EMPRESA=l.ID_EMPRESA AND a.ID_LINEA_AHORRO=l.ID_LINEA_AHORRO
            GROUP BY l.ID_EMPRESA,l.ID_LINEA_AHORRO,l.LINEA_AHORRO,l.ID_TIPO_CUENTA_AHORRO,
                     l.PORCENTAJE_INTERES,l.PLAZO_INI,l.PLAZO_FIN,l.PERIODO_CAPITALIZACION,
                     l.METODO_CAPITALIZACION,l.AFECTA_ISR,principal.CODIGO_CUENTA,
                     expense.CODIGO_CUENTA,payable.CODIGO_CUENTA,tax.CODIGO_CUENTA
            ORDER BY l.ID_TIPO_CUENTA_AHORRO,l.ID_LINEA_AHORRO
        """)

    known_types = set(contract.raw["account_types"])
    known_states = set(contract.raw["account_states"])
    for row in account_rows:
        if clean_text(row.get("account_type")) not in known_types:
            blockers.append("unmapped_savings_account_type")
        if clean_text(row.get("account_state")) not in known_states:
            blockers.append("unmapped_savings_account_state")
    for row in movement_rows:
        label = clean_text(row.get("transaction_label"))
        mapping = contract.raw["movement_roles"].get(label or "")
        if mapping is None:
            blockers.append("unmapped_savings_movement")
        elif clean_text(row.get("direction")) != mapping["direction"]:
            blockers.append("savings_movement_direction_mismatch")
    for row in history_rows:
        if clean_text(row.get("history_type")) not in contract.raw["history_roles"]:
            blockers.append("unmapped_savings_history_type")
    if int(owner_rows.get("joint_accounts_with_ambiguous_primary") or 0) > 0:
        blockers.append("joint_account_primary_owner_ambiguous")
    cutoff_snapshot = cutoff_rows[0] if cutoff_rows else {}
    isr_audit = isr_rows[0] if isr_rows else {}
    dpf_cycle_audit = dpf_cycle_rows[0] if dpf_cycle_rows else {}
    for mismatch in (
        "invalid_cycles", "unreviewed_boundary_gaps", "current_master_mismatches",
        "unplaced_interest_rows", "multiply_placed_interest_rows",
    ):
        if int(dpf_cycle_audit.get(mismatch) or 0) > 0:
            blockers.append(f"fixed_deposit_cycles:{mismatch}")
    if not contract.cutoff_ready:
        blockers.append("cutoff_field_selection")
    if not cutoff_snapshot.get("cutoff_date"):
        blockers.append("cutoff_completed_close_snapshot_missing")
    if int(cutoff_snapshot.get("snapshot_rows") or 0) != int(cutoff_snapshot.get("distinct_accounts") or 0):
        blockers.append("cutoff_snapshot_duplicate_accounts")
    for mismatch in ("rate_mismatches", "linked_movement_mismatches", "untaxed_event_mismatches", "catch_up_tax_mismatches"):
        if int(isr_audit.get(mismatch) or 0) > 0:
            blockers.append(f"historical_isr:{mismatch}")
    blockers.extend(f"implementation_gate:{item}" for item in contract.raw["blockers"] if item != "cutoff_field_selection")

    target_schema: dict[str, dict[str, str]] = {table: {} for table in REQUIRED_TARGET_COLUMNS}
    target: dict[str, Any]
    if not settings.target.pg_url:
        blockers.append("target_postgres_inspection_not_configured")
        target = {"postgres_inspection": "not-configured"}
    else:
        try:
            with postgres_connection(settings.target.pg_url) as conn:
                target_schema = postgres_schema(conn, list(REQUIRED_TARGET_COLUMNS))
                target_counts: dict[str, int] = {}
                for table in (
                    "m_savings_product", "m_savings_account", "m_savings_account_transaction",
                    "acc_product_mapping", "acc_gl_account",
                    "credesal_savings_product_map",
                    "credesal_savings_migration_account", "credesal_savings_migration_owner",
                    "credesal_savings_migration_cycle",
                    "credesal_savings_native_event_map",
                ):
                    if target_schema.get(table):
                        target_counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                target_product_rows = conn.execute("""
                    SELECT id,name,short_name,deposit_type_enum,currency_code,
                           nominal_annual_interest_rate::text AS nominal_annual_interest_rate,
                           interest_compounding_period_enum,interest_posting_period_enum,
                           interest_calculation_type_enum,interest_calculation_days_in_year_type_enum,
                           accounting_type,withhold_tax,tax_group_id
                    FROM m_savings_product ORDER BY id
                """).fetchall()
                product_columns = (
                    "id", "name", "short_name", "deposit_type_enum", "currency_code",
                    "nominal_annual_interest_rate", "interest_compounding_period_enum",
                    "interest_posting_period_enum", "interest_calculation_type_enum",
                    "interest_calculation_days_in_year_type_enum", "accounting_type", "withhold_tax", "tax_group_id",
                )
                products = [dict(zip(product_columns, row)) for row in target_product_rows]
                explicit_tax_product_count = sum(
                    1 for product in products if product["tax_group_id"] is not None and not product["withhold_tax"]
                )
                explicit_tax_permission_count = int(conn.execute("""
                    SELECT COUNT(*) FROM m_permission
                    WHERE code='EXPLICITWITHHOLDTAX_SAVINGSACCOUNT'
                      AND entity_name='SAVINGSACCOUNT' AND action_name='EXPLICITWITHHOLDTAX'
                """).fetchone()[0])
                if explicit_tax_permission_count != 1:
                    blockers.append("target_explicit_withhold_tax_permission_missing")
                explicit_interest_permission_count = int(conn.execute("""
                    SELECT COUNT(*) FROM m_permission
                    WHERE code='EXPLICITINTERESTPOSTING_SAVINGSACCOUNT'
                      AND entity_name='SAVINGSACCOUNT' AND action_name='EXPLICITINTERESTPOSTING'
                """).fetchone()[0])
                if explicit_interest_permission_count != 1:
                    blockers.append("target_explicit_interest_posting_permission_missing")
                migration_link_permission_count = int(conn.execute("""
                    SELECT COUNT(*) FROM m_permission
                    WHERE code='MIGRATIONLINK_FIXEDDEPOSITACCOUNT'
                      AND entity_name='FIXEDDEPOSITACCOUNT' AND action_name='MIGRATIONLINK'
                """).fetchone()[0])
                if migration_link_permission_count != 1:
                    blockers.append("target_fixed_deposit_migration_link_permission_missing")
                period_end_rows = conn.execute("""
                    SELECT enabled FROM c_configuration
                    WHERE name='savings-interest-posting-current-period-end'
                """).fetchall()
                period_end_enabled = len(period_end_rows) == 1 and bool(period_end_rows[0][0])
                if not period_end_enabled:
                    blockers.append("target_savings_interest_period_end_not_enabled")
                actual_basis_value = int(contract.raw["interest_basis"]["target_enum_value"])
                account_basis_rows = conn.execute("""
                    SELECT interest_calculation_days_in_year_type_enum,COUNT(*)
                    FROM m_savings_account
                    GROUP BY interest_calculation_days_in_year_type_enum
                    ORDER BY interest_calculation_days_in_year_type_enum
                """).fetchall()
                product_basis_counts: dict[str, int] = {}
                for product in products:
                    basis = str(product["interest_calculation_days_in_year_type_enum"])
                    product_basis_counts[basis] = product_basis_counts.get(basis, 0) + 1
                account_basis_counts = {str(row[0]): int(row[1]) for row in account_basis_rows}
                schedule = contract.raw["interest_schedule"]
                posting_value = int(schedule["target_posting_enum_value"])
                compounding_value = int(schedule["target_compounding_enum_value"])
                account_schedule_rows = conn.execute("""
                    SELECT interest_posting_period_enum,interest_compounding_period_enum,COUNT(*)
                    FROM m_savings_account
                    GROUP BY interest_posting_period_enum,interest_compounding_period_enum
                    ORDER BY interest_posting_period_enum,interest_compounding_period_enum
                """).fetchall()
                product_schedule_counts: dict[str, int] = {}
                for product in products:
                    key = f"{product['interest_posting_period_enum']}:{product['interest_compounding_period_enum']}"
                    product_schedule_counts[key] = product_schedule_counts.get(key, 0) + 1
                account_schedule_counts = {f"{row[0]}:{row[1]}": int(row[2]) for row in account_schedule_rows}
                required_schedule_key = f"{posting_value}:{compounding_value}"
                mapping_rows = conn.execute("""
                    SELECT p.id AS product_id,p.name,
                           COUNT(apm.id) AS mapping_count,
                           COUNT(DISTINCT apm.financial_account_type) AS financial_role_count,
                           SUM(CASE WHEN apm.gl_account_id IS NULL OR g.id IS NULL THEN 1 ELSE 0 END) AS invalid_gl_links
                    FROM m_savings_product p
                    LEFT JOIN acc_product_mapping apm ON apm.product_id=p.id AND apm.product_type=2
                    LEFT JOIN acc_gl_account g ON g.id=apm.gl_account_id
                    GROUP BY p.id,p.name ORDER BY p.id
                """).fetchall()
                mapping_columns = ("product_id", "name", "mapping_count", "financial_role_count", "invalid_gl_links")
                product_gl_mappings = [dict(zip(mapping_columns, row)) for row in mapping_rows]
                target_gl_rows = conn.execute("""
                    SELECT gl_code,name,classification_enum,disabled FROM acc_gl_account
                """).fetchall()
                target_gl = {
                    str(row[0]): {"name": row[1], "classification_enum": row[2], "disabled": row[3]}
                    for row in target_gl_rows
                }
                expected_source_gl = sorted({
                    str(code)
                    for product in source_product_rows
                    for code in (
                        product.get("principal_gl"), product.get("interest_expense_gl"),
                        product.get("interest_payable_gl"), product.get("tax_gl"),
                    )
                    if code
                })
                unresolved_source_gl = [code for code in expected_source_gl if code not in target_gl]
                disabled_source_gl = [code for code in expected_source_gl if target_gl.get(code, {}).get("disabled")]
                shared_gl = contract.raw["target_shared_gl"]
                shared_gl_resolution: dict[str, Any] = {}
                for parameter, expected in shared_gl.items():
                    gl_code = expected["gl_code"]
                    actual = target_gl.get(gl_code)
                    shared_gl_resolution[parameter] = {"gl_code": gl_code, "resolved": actual is not None, **(actual or {})}
                    if actual is None:
                        blockers.append(f"target_shared_gl_unresolved:{parameter}")
                    elif actual.get("disabled"):
                        blockers.append(f"target_shared_gl_disabled:{parameter}")
                    elif int(actual.get("classification_enum")) != int(expected["classification_enum"]):
                        blockers.append(f"target_shared_gl_classification_mismatch:{parameter}")
                target = {
                    "postgres_inspection": "ok",
                    "counts": target_counts,
                    "products": products,
                    "explicit_withhold_tax": {
                        "api_command": historical_isr["target_api_command"],
                        "permission": historical_isr["target_permission"],
                        "permission_count": explicit_tax_permission_count,
                        "products_with_tax_group_and_automatic_withholding_disabled": explicit_tax_product_count,
                    },
                    "explicit_interest_posting": {
                        "api_command": historical_interest["target_api_command"],
                        "transaction_type_enum": historical_interest["target_transaction_type_enum"],
                        "transaction_type_code": historical_interest["target_transaction_type_code"],
                        "permission": historical_interest["target_permission"],
                        "permission_count": explicit_interest_permission_count,
                        "future_interest_policy": historical_interest["future_interest_policy"],
                    },
                    "fixed_deposit_migration_link": {
                        "api_command": "migrationLink",
                        "permission": "MIGRATIONLINK_FIXEDDEPOSITACCOUNT",
                        "permission_count": migration_link_permission_count,
                        "principal_transfer": False,
                    },
                    "interest_basis": {
                        "required_api_parameter": contract.raw["interest_basis"]["target_api_parameter"],
                        "required_enum_value": actual_basis_value,
                        "required_enum_code": contract.raw["interest_basis"]["target_enum_code"],
                        "product_column": contract.raw["interest_basis"]["target_product_column"],
                        "account_column": contract.raw["interest_basis"]["target_account_column"],
                        "product_value_counts": product_basis_counts,
                        "account_value_counts": account_basis_counts,
                        "matching_product_count": product_basis_counts.get(str(actual_basis_value), 0),
                        "matching_account_count": account_basis_counts.get(str(actual_basis_value), 0),
                    },
                    "interest_schedule": {
                        "source_period_code": schedule["source_period_code"],
                        "anchor_source_column": schedule["anchor_source_column"],
                        "short_month_rule": schedule["short_month_rule"],
                        "required_posting_enum_value": posting_value,
                        "required_posting_enum_code": schedule["target_posting_enum_code"],
                        "required_compounding_enum_value": compounding_value,
                        "required_compounding_enum_code": schedule["target_compounding_enum_code"],
                        "product_value_counts": product_schedule_counts,
                        "account_value_counts": account_schedule_counts,
                        "matching_product_count": product_schedule_counts.get(required_schedule_key, 0),
                        "matching_account_count": account_schedule_counts.get(required_schedule_key, 0),
                        "posting_current_period_end": period_end_enabled,
                    },
                    "product_gl_mappings": product_gl_mappings,
                    "source_gl_resolution": {
                        "expected": len(expected_source_gl),
                        "resolved": len(expected_source_gl) - len(unresolved_source_gl),
                        "unresolved": unresolved_source_gl,
                        "disabled": disabled_source_gl,
                    },
                    "shared_gl_resolution": shared_gl_resolution,
                }
                if unresolved_source_gl:
                    blockers.append("target_source_gl_codes_unresolved")
                if disabled_source_gl:
                    blockers.append("target_source_gl_codes_disabled")
        except Exception as exc:
            blockers.append("target_postgres_inspection_failed")
            target = {"postgres_inspection": "failed", "error_type": type(exc).__name__}
    for table, required_columns in REQUIRED_TARGET_COLUMNS.items():
        missing = sorted(required_columns - set(target_schema.get(table, {})))
        if missing:
            target.setdefault("missing_required_columns", {})[table] = missing
            blockers.append(f"target_schema_incomplete:{table}")

    blockers = sorted(set(blockers))
    signature = _schema_signature(source_schema, target_schema)
    return {
        "block": BLOCK,
        "ready": False,
        "read_ready": not any(item.startswith("missing_source_") for item in blockers),
        "contract_hash": contract.contract_hash,
        "schema_signature": signature,
        "source_fingerprint": source_fingerprint(settings.source),
        "source": {
            "schema": source_schema,
            "accounts": account_rows,
            "ownership": owner_rows,
            "movements": movement_rows,
            "interest_history": history_rows,
            "fixed_deposit_cycles": {
                "native_maturity_instruction_id": contract.raw["fixed_deposit_cycles"]["historical_maturity_instruction_id"],
                "native_maturity_instruction": contract.raw["fixed_deposit_cycles"]["historical_maturity_instruction"],
                **dpf_cycle_audit,
            },
            "cutoff": {
                "source_table": source["daily_table"],
                "close_table": source["daily_close_table"],
                "selected_exact_field": cutoff["selected_exact_field"],
                "selected_accounting_field": cutoff["selected_accounting_field"],
                "precision_policy": cutoff["precision_policy"],
                **cutoff_snapshot,
            },
            "historical_isr": {
                "decision_field": historical_isr["decision_field"],
                "target_transaction_type_enum": historical_isr["target_transaction_type_enum"],
                "target_transaction_type_code": historical_isr["target_transaction_type_code"],
                "posting_account": historical_isr["posting_account"],
                "future_eligibility_policy": historical_isr["future_eligibility_policy"],
                **isr_audit,
            },
            "product_lines": source_product_rows,
        },
        "target": target,
        "blockers": blockers,
    }
