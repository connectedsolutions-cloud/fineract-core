import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from arissto_sync.loans import (
    ACCOUNTING_RESPONSE_KEYS,
    REQUIRED_COLUMNS,
    LoanContract,
    _apply_loan_lifecycle,
    _attempt_idempotency_key,
    _build_loan_lifecycle_action,
    _classify_voided_refinance_attempts,
    _ensure_recurring_insurance_charge,
    _ensure_source_insurance_charges,
    _ensure_source_penalty_charge,
    _ensure_refinance_prepayment_ready,
    _loan_outstanding_allocation,
    _loan_legacy_timeline_differences,
    _proof_namespace_lifecycle,
    _refinance_component_bridge,
    _loan_schedule_differences,
    _resolve_or_create_loan_product,
    _selected_loan_actions,
    apply_loan_plan,
    build_loan_plan,
    build_loan_product_payload,
    canonical_source_key,
    classify_source_exact_component_reallocations,
    compact_loan_reconciliation_report,
    compose_loan_plan,
    extract_loan_lifecycle_rows,
    inspect_loans,
    loan_action_key,
    loan_retry_keys,
    loan_product_conflicts,
    pair_loan_reversals,
    product_action_key,
    reconcile_loans,
)
from arissto_sync.engine import datatable_api_payload
from arissto_sync.state import State


CONFIG = Path(__file__).resolve().parents[1] / "config" / "loans.json"


class LoanInspectionTests(unittest.TestCase):
    def test_refinance_bridge_credits_only_target_component_excess(self):
        bridge = _refinance_component_bridge({
            "principalPortion": "35.71", "interestPortion": "4.75",
            "feeChargesPortion": "0.60", "penaltyChargesPortion": "0.00",
        }, {
            "principal": "35.71", "interest": "0.00", "fee": "0.00", "penalty": "0.00",
        })

        self.assertEqual(bridge, {
            "principal": Decimal("0.00"), "interest": Decimal("4.75"),
            "fee": Decimal("0.60"), "penalty": Decimal("0.00"),
        })

    def test_refinance_bridge_rejects_target_component_shortfall(self):
        with self.assertRaisesRegex(RuntimeError, "refinance_target_components_below_source"):
            _refinance_component_bridge({
                "principalPortion": "49.18", "interestPortion": "0.20",
                "feeChargesPortion": "0.00", "penaltyChargesPortion": "0.00",
            }, {
                "principal": "49.18", "interest": "0.24", "fee": "0.00", "penalty": "0.00",
            })

    def test_refinance_bridge_allows_source_interest_to_be_materialized(self):
        bridge = _refinance_component_bridge({
            "principalPortion": "48.94", "interestPortion": "0.00",
            "feeChargesPortion": "0.00", "penaltyChargesPortion": "0.00",
        }, {
            "principal": "48.94", "interest": "1.34", "fee": "0.00", "penalty": "0.00",
        }, allow_interest_shortfall=True)

        self.assertEqual(bridge, {
            "principal": Decimal("0.00"), "interest": Decimal("0.00"),
            "fee": Decimal("0.00"), "penalty": Decimal("0.00"),
        })

    def test_refinance_bridge_still_rejects_principal_shortfall(self):
        with self.assertRaisesRegex(RuntimeError, "refinance_target_components_below_source"):
            _refinance_component_bridge({
                "principalPortion": "48.92", "interestPortion": "0.00",
                "feeChargesPortion": "0.00", "penaltyChargesPortion": "0.00",
            }, {
                "principal": "48.94", "interest": "1.34", "fee": "0.00", "penalty": "0.00",
            }, allow_interest_shortfall=True)

    def test_refinance_residual_bridge_uses_exact_outstanding_components(self):
        allocation = _loan_outstanding_allocation({"summary": {
            "principalOutstanding": "0.00", "interestOutstanding": "0.24",
            "feeChargesOutstanding": "0.00", "penaltyChargesOutstanding": "0.00",
            "totalOutstanding": "0.24",
        }})

        self.assertEqual(allocation, {
            "principal": Decimal("0.00"), "interest": Decimal("0.24"),
            "fee": Decimal("0.00"), "penalty": Decimal("0.00"),
        })

    def test_refinance_residual_bridge_rejects_inconsistent_summary(self):
        with self.assertRaisesRegex(RuntimeError, "refinance_residual_components_mismatch"):
            _loan_outstanding_allocation({"summary": {
                "principalOutstanding": "0.00", "interestOutstanding": "0.24",
                "feeChargesOutstanding": "0.00", "penaltyChargesOutstanding": "0.00",
                "totalOutstanding": "0.26",
            }})

    def test_refinance_component_bridge_converges_before_successor_creation(self):
        api = MagicMock()
        predecessor = {"id": 342}
        refinance = {
            "predecessor_external_id": "ARISSTO:CRD:1965",
            "payoff_date": "2026-06-08", "payoff_amount": "815.17",
            "payoff_allocation": {
                "principal": "804.15", "interest": "11.02",
                "fee": "0.00", "penalty": "0.00",
            },
            "adjustment_external_id": "ARISSTO:CRD-REFI-CUTOVER:1965:2049",
        }
        initial_quote = {
            "amount": "1063.17", "principalPortion": "804.15",
            "interestPortion": "228.94", "feeChargesPortion": "30.08",
            "penaltyChargesPortion": "0.00",
        }
        exact_quote = {
            "amount": "815.17", "principalPortion": "804.15",
            "interestPortion": "11.02", "feeChargesPortion": "0.00",
            "penaltyChargesPortion": "0.00",
        }
        bridge_transaction = {
            "amount": "248.00", "principalPortion": "0.00",
            "interestPortion": "217.92", "feeChargesPortion": "30.08",
            "penaltyChargesPortion": "0.00",
        }
        api.request.side_effect = [initial_quote, {}, exact_quote]

        with (
            patch("arissto_sync.loans._find_loan_transaction", side_effect=[None, bridge_transaction]),
            patch("arissto_sync.loans._find_loan", return_value=predecessor),
        ):
            result = _ensure_refinance_prepayment_ready(api, predecessor, refinance, "run-1")

        self.assertIs(result, predecessor)
        bridge_call = api.request.call_args_list[1]
        self.assertEqual(bridge_call.kwargs["query"], {"command": "sourceExactGoodwillCredit"})
        self.assertEqual(bridge_call.args[2]["transactionAmount"], "248.00")
        self.assertEqual(bridge_call.args[2]["interestPortion"], "217.92")
        self.assertEqual(bridge_call.args[2]["feeChargesPortion"], "30.08")

    def test_refinance_penalty_is_assessed_before_prepayment_quote(self):
        api = MagicMock()
        predecessor = {"id": 415}
        refinance = {
            "predecessor_external_id": "ARISSTO:CRD:2096",
            "payoff_date": "2026-07-10", "payoff_amount": "785.60",
            "payoff_allocation": {
                "principal": "754.50", "interest": "31.01",
                "fee": "0.00", "penalty": "0.09",
            },
            "payoff_external_id": "ARISSTO:CRD-MOV:0000024133",
            "penalty_charge_external_id": "ARISSTO:CRD-MOV:0000024133:PENALTY",
            "penalty_charge_id": 9,
            "adjustment_external_id": "ARISSTO:CRD-REFI-CUTOVER:2096:2243",
        }
        api.request.return_value = {
            "amount": "785.60", "principalPortion": "754.50",
            "interestPortion": "31.01", "feeChargesPortion": "0.00",
            "penaltyChargesPortion": "0.09",
        }

        with (
            patch("arissto_sync.loans._ensure_source_penalty_charge", return_value=predecessor) as ensure_penalty,
            patch("arissto_sync.loans._find_loan_transaction", return_value=None),
        ):
            result = _ensure_refinance_prepayment_ready(api, predecessor, refinance, "run-1")

        self.assertIs(result, predecessor)
        ensure_penalty.assert_called_once()
        self.assertEqual(ensure_penalty.call_args.args[2]["allocation"]["penalty"], "0.09")
        self.assertEqual(ensure_penalty.call_args.args[2]["date"], "2026-07-10")

    def test_refinance_insurance_is_assessed_before_prepayment_quote(self):
        api = MagicMock()
        predecessor = {"id": 489}
        charge = {
            "external_id": "ARISSTO:CRD-INS:198241:0000006750:0046",
            "charge_id": 12,
            "amount": "0.44",
            "due_date": "2024-12-21",
        }
        refinance = {
            "predecessor_external_id": "ARISSTO:CRD:83",
            "payoff_date": "2024-12-21", "payoff_amount": "405.67",
            "payoff_allocation": {
                "principal": "367.30", "interest": "37.93",
                "fee": "0.44", "penalty": "0.00",
            },
            "historical_insurance_charges": [charge],
            "adjustment_external_id": "ARISSTO:CRD-REFI-CUTOVER:83:934",
        }
        api.request.return_value = {
            "amount": "405.67", "principalPortion": "367.30",
            "interestPortion": "37.93", "feeChargesPortion": "0.44",
            "penaltyChargesPortion": "0.00",
        }

        with (
            patch("arissto_sync.loans._ensure_source_insurance_charges", return_value=predecessor) as ensure_insurance,
            patch("arissto_sync.loans._find_loan_transaction", return_value=None),
        ):
            result = _ensure_refinance_prepayment_ready(api, predecessor, refinance, "run-1")

        self.assertIs(result, predecessor)
        ensure_insurance.assert_called_once_with(
            api, predecessor, {"historical_insurance_charges": [charge]}, "run-1"
        )

    def test_existing_refinance_bridge_must_have_converged(self):
        api = MagicMock()
        api.request.return_value = {
            "amount": "1063.17", "principalPortion": "804.15",
            "interestPortion": "228.94", "feeChargesPortion": "30.08",
            "penaltyChargesPortion": "0.00",
        }
        refinance = {
            "payoff_date": "2026-06-08", "payoff_amount": "815.17",
            "payoff_allocation": {
                "principal": "804.15", "interest": "11.02",
                "fee": "0.00", "penalty": "0.00",
            },
            "adjustment_external_id": "ARISSTO:CRD-REFI-CUTOVER:1965:2049",
        }

        with (
            patch("arissto_sync.loans._find_loan_transaction", return_value={"id": 1}),
            self.assertRaisesRegex(RuntimeError, "existing_component_bridge_did_not_converge"),
        ):
            _ensure_refinance_prepayment_ready(api, {"id": 342}, refinance, "run-1")

    def test_penalty_charge_is_created_with_deterministic_identity_and_exact_amount(self):
        api = MagicMock()
        event = {
            "date": "2026-05-20",
            "allocation": {"penalty": "0.08"},
            "penalty_charge_id": 9,
            "penalty_charge_external_id": "PROOF:p:ARISSTO:CRD-MOV:1:PENALTY",
        }
        api.request.side_effect = [
            {"resourceId": 77},
            {"id": 5, "charges": [{
                "id": 77, "externalId": event["penalty_charge_external_id"], "amount": 0.08,
            }]},
        ]

        loan = _ensure_source_penalty_charge(api, {"id": 5, "charges": []}, event, "retry-1")

        self.assertEqual(loan["charges"][0]["amount"], 0.08)
        payload = api.request.call_args_list[0].args[2]
        self.assertEqual(payload, {
            "chargeId": 9, "amount": "0.08", "dueDate": "2026-05-20",
            "externalId": event["penalty_charge_external_id"],
            "dateFormat": "yyyy-MM-dd", "locale": "en",
        })

    def test_insurance_charge_is_created_with_deterministic_identity_and_exact_amount(self):
        api = MagicMock()
        event = {"historical_insurance_charges": [{
            "external_id": "ARISSTO:CRD-INS:7:101:1", "charge_id": 10,
            "amount": "0.10", "due_date": "2026-06-20",
        }]}
        api.request.side_effect = [
            {"resourceId": 77},
            {"id": 5, "charges": [{
                "id": 77, "externalId": "ARISSTO:CRD-INS:7:101:1", "amount": 0.10,
            }]},
        ]

        loan = _ensure_source_insurance_charges(api, {"id": 5, "charges": []}, event, "retry-1")

        self.assertEqual(loan["charges"][0]["amount"], 0.10)
        self.assertEqual(api.request.call_args_list[0].args[2], {
            "chargeId": 10, "amount": "0.10", "dueDate": "2026-06-20",
            "externalId": "ARISSTO:CRD-INS:7:101:1",
            "dateFormat": "yyyy-MM-dd", "locale": "en",
        })

    def test_recurring_insurance_charge_is_opt_in_and_starts_at_cutover(self):
        api = MagicMock()
        charge = {
            "external_id": "ARISSTO:CRD-INS-FUTURE:2068",
            "charge_id": 8,
            "amount": "0.06",
            "submitted_on_date": "2026-08-31",
        }
        api.request.side_effect = [
            {"resourceId": 78},
            {"id": 5, "charges": [{
                "id": 78,
                "externalId": charge["external_id"],
                "amountOrPercentage": 0.06,
                "submittedOnDate": [2026, 8, 31],
            }]},
        ]

        loan = _ensure_recurring_insurance_charge(api, {"id": 5, "charges": []}, charge, "retry-1")

        self.assertEqual(loan["charges"][0]["amountOrPercentage"], 0.06)
        self.assertEqual(api.request.call_args_list[0].args[2], {
            "chargeId": 8,
            "amount": "0.06",
            "submittedOnDate": "2026-08-31",
            "externalId": "ARISSTO:CRD-INS-FUTURE:2068",
            "dateFormat": "yyyy-MM-dd",
            "locale": "en",
        })

    def test_schedule_reconciliation_uses_original_contract_amounts_after_accrual(self):
        source = [{"number": 1, "due_date": "2026-05-14", "principal": "10.09", "interest": "1.01"}]
        target = {
            "periods": [{
                "period": 1, "dueDate": [2026, 5, 14],
                "principalOriginalDue": 10.09, "principalDue": 10.09,
                "interestOriginalDue": 1.01, "interestDue": 3.35,
            }],
            "totalPrincipalExpected": 10.09, "totalInterestCharged": 3.35,
        }

        self.assertEqual(_loan_schedule_differences(source, target), [])

    def test_schedule_reconciliation_ignores_post_maturity_penalty_only_period(self):
        source = [{"number": 1, "due_date": "2026-05-14", "principal": "10.09", "interest": "1.01"}]
        target = {
            "periods": [
                {
                    "period": 1, "dueDate": [2026, 5, 14],
                    "principalOriginalDue": 10.09, "interestOriginalDue": 1.01,
                    "penaltyChargesDue": 0,
                },
                {
                    "period": 2, "dueDate": [2026, 5, 20],
                    "principalOriginalDue": 0, "interestOriginalDue": 0,
                    "penaltyChargesDue": 0.08,
                },
            ],
        }

        self.assertEqual(_loan_schedule_differences(source, target), [])

    def test_attempt_idempotency_keys_remain_unique_for_long_proof_ids(self):
        first = "PROOF:alloc1254-20260830:ARISSTO:CRD-MOV:0000010987"
        second = "PROOF:alloc1254-20260830:ARISSTO:CRD-MOV:0000011203"

        first_key = _attempt_idempotency_key(first, "run-1")
        second_key = _attempt_idempotency_key(second, "run-1")

        self.assertNotEqual(first_key, second_key)
        self.assertLessEqual(len(first_key), 50)
        self.assertEqual(first_key, _attempt_idempotency_key(first, "run-1"))
        self.assertLessEqual(len(_attempt_idempotency_key(first, None)), 50)

    def setUp(self):
        self.contract = LoanContract.load(CONFIG)

    def test_contract_and_source_key_are_strict(self):
        self.assertEqual(canonical_source_key(" 123 "), 123)
        self.assertIsNone(canonical_source_key(None))
        for invalid in ("0", "-1", "1:2", "abc", ""):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                canonical_source_key(invalid)

        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["source"]["loan_table"] = "CRD_CARTERA; DELETE"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loans.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsafe loans source table"):
                LoanContract.load(path)

        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["identity"]["product_key"] = ["ID_EMPRESA", "ID_LINEA_CREDITO"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loans.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "only ID_LINEA_CREDITO"):
                LoanContract.load(path)

    def target_resources(self):
        product = self.contract.raw["product_contract"]
        codes = set(product["accounting_gl_codes"].values())
        codes.update(product["portfolio_account_policy"]["reviewed_primary_gl_by_line"].values())
        codes.add(product["target_resources"]["debt_insurance_charge"]["income_or_liability_gl"])
        codes.add(product["target_resources"]["historical_debt_insurance_charge"]["income_or_liability_gl"])
        codes.add(product["target_resources"]["mobile_collection_fund_source_gl"])
        return {
            "gl_ids": {code: index + 100 for index, code in enumerate(sorted(codes))},
            "debt_insurance_charge_id": 8,
            "historical_debt_insurance_charge_id": 10,
            "historical_penalty_charge_id": 11,
            "mobile_collection_payment_type_id": 9,
        }

    @staticmethod
    def product(line_id, line_type, name):
        return {
            "company_id": "001", "line_id": line_id, "line_type": line_type,
            "line_code": line_id, "line_name": name,
        }

    @staticmethod
    def loan(loan_id, line_id):
        return {"ID_CREDITO": loan_id, "line_id": line_id, "company_id": "001"}

    @staticmethod
    def api_product(payload, identifier=90):
        response = dict(payload)
        response["id"] = identifier
        response["currency"] = {
            "code": payload["currencyCode"], "decimalPlaces": payload["digitsAfterDecimal"],
            "inMultiplesOf": payload["inMultiplesOf"],
        }
        for field in (
            "repaymentFrequencyType", "interestRateFrequencyType", "amortizationType", "interestType",
            "interestCalculationPeriodType", "accountingRule", "daysInMonthType", "daysInYearType",
        ):
            response[field] = {"id": payload[field]}
        response["loanScheduleType"] = {"code": payload["loanScheduleType"]}
        response["loanScheduleProcessingType"] = {"code": payload["loanScheduleProcessingType"]}
        response["accountingMappings"] = {
            response_key: {"id": payload[parameter]}
            for parameter, response_key in ACCOUNTING_RESPONSE_KEYS.items()
        }
        response["paymentChannelToFundSourceMappings"] = [{
            "paymentType": {"id": item["paymentTypeId"]},
            "fundSourceAccount": {"id": item["fundSourceAccountId"]},
        } for item in payload["paymentChannelToFundSourceMappings"]]
        response["feeToIncomeAccountMappings"] = [{
            "charge": {"id": item["chargeId"]}, "incomeAccount": {"id": item["incomeAccountId"]},
        } for item in payload["feeToIncomeAccountMappings"]]
        return response

    def lifecycle_fixture(self):
        loan = {
            "ID_CREDITO": 2068, "company_id": "001", "line_id": "00010",
            "client_source_key": "0000000832", "source_state": "1", "loan_type": "001",
            "slu_id": 5, "application_id": "42", "account_executive_id": "00012",
            "promoter_id": "00037", "collections_manager_id": None,
            "MONTO_APROBADO": "350.00", "MONTO_DESEMBOLSADO": "350.00",
            "PORC_INTERES_APROBADO": "84.00", "NO_CUOTAS_APROBADO": 2,
            "ID_FRECUENCIA": 15, "FECHA_OTORGAMIENTO": "2026-06-11",
            "ULTIMO_SALDO": "342.00", "SALDO_INTERES": "1.90",
            "SALDO_INTERES_PENDIENTE": "0", "SALDO_MORA": "0",
            "SALDO_SEGURO": "0.10", "SALDO_RECARGOS": "0", "SALDO_TOTAL": "344.00",
        }
        lifecycle = {
            "application": {
                "FECHA_SOLICITUD": "2026-06-10", "FECHA_APROBADO": "2026-06-11",
                "FECHA_RESOLUCION": None, "FECHA_DESEMBOLSO": "2026-06-11",
                "FECHA_PACTADA": None, "FECHA_FIRMA": None,
            },
            "schedule": [
                {"NO_CUOTA": 1, "FECHA_PAGO": "2026-06-26", "MONTO_CAPITAL": "175",
                 "MONTO_INTERES": "12", "MONTO_OTROS": "0.10", "MONTO_APORTACION": 0,
                 "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
                {"NO_CUOTA": 2, "FECHA_PAGO": "2026-07-11", "MONTO_CAPITAL": "175",
                 "MONTO_INTERES": "6", "MONTO_OTROS": "0.10", "MONTO_APORTACION": 0,
                 "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
            ],
            "movements": [
                {"ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "100", "CODIGO_SISTEMA": 4,
                 "ID_TRANSACCION": "00002", "REVERSION": "", "FECHA_OPERACION": "2026-06-11",
                 "MONTO": "350", "MONTO_CAPITAL": "350"},
                {"ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "101", "CODIGO_SISTEMA": 14,
                 "ID_TRANSACCION": "00011", "REVERSION": "", "FECHA_OPERACION": "2026-06-20",
                 "MONTO": "10", "MONTO_CAPITAL": "8", "MONTO_INTERES": "1.90",
                "MONTO_SEGURO": "0.10"},
            ],
            "charge_details": [{
                "ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "101",
                "ID_RECARGO_CARTERA": 7001, "ID_PAGOS": "0001",
                "MONTO_COBRADO": "0.10", "NOMBRE_CARGO": "SEGURO DE DEUDA",
                "ID_TIPO_CARGO": 2,
            }],
        }
        product = self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO")
        payload = build_loan_product_payload(self.contract, product, self.target_resources())
        target = {
            "resources": self.target_resources(),
            "clients": {"0000000832": {"id": 900, "status": 300, "office_id": 1}},
            "staff": {"001:00037": {
                "id": 40, "active": True, "loan_officer": True, "office_id": 1,
            }, "001:00012": {
                "id": 41, "active": True, "loan_officer": False, "office_id": 1,
            }},
        }
        return loan, lifecycle, target, payload

    @staticmethod
    def calculated_schedule(lifecycle):
        schedule = lifecycle["schedule"]
        return {
            "totalPrincipalExpected": sum(Decimal(row["principal"]) for row in schedule),
            "totalInterestCharged": sum(Decimal(row["interest"]) for row in schedule),
            "periods": [
                {
                    "period": row["number"],
                    "dueDate": [int(value) for value in row["due_date"].split("-")],
                    "principalDue": row["principal"],
                    "interestDue": row["interest"],
                }
                for row in schedule
            ],
        }

    def test_lifecycle_plan_freezes_ordered_events_and_outstanding_balances(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        result = _build_loan_lifecycle_action(
            self.contract, loan, lifecycle, target, payload, migration_cutover_date="2026-08-31"
        )

        self.assertEqual(result["quarantine_reasons"], [])
        frozen = result["lifecycle"]
        self.assertEqual([event["role"] for event in frozen["events"]],
                         ["disbursement", "mobile-collection-repayment"])
        self.assertEqual(frozen["events"][1]["payment_type_id"], 9)
        self.assertEqual(frozen["events"][1]["allocation"], {
            "principal": "8.00", "interest": "1.90", "penalty": "0.00", "fee": "0.10",
        })
        self.assertEqual(frozen["application_payload"]["charges"], [])
        self.assertEqual(frozen["events"][1]["historical_insurance_charges"], [{
            "source_charge_id": "7001", "source_payment_id": "0001",
            "external_id": "ARISSTO:CRD-INS:7001:101:0001", "charge_id": 10,
            "amount": "0.10", "due_date": "2026-06-20",
        }])
        self.assertEqual(frozen["cutover_insurance_charge"], {
            "external_id": "ARISSTO:CRD-INS-CUTOVER:2068", "charge_id": 10,
            "amount": "0.10", "due_date": "2026-06-20",
            "classification": "source_insurance_cutover_outstanding",
        })
        self.assertEqual(frozen["recurring_insurance_charge"], {
            "external_id": "ARISSTO:CRD-INS-FUTURE:2068", "charge_id": 8,
            "amount": "0.06", "submitted_on_date": "2026-08-31",
            "classification": "post_migration_recurring_debt_insurance",
        })
        self.assertEqual(frozen["expected"]["principal_balance"], "342.00")
        self.assertEqual(frozen["expected"]["total_outstanding"], "344.00")
        self.assertIsNone(frozen["legacy_timeline"])
        self.assertEqual(len(result["lifecycle_hash"]), 64)

    def test_legacy_insurance_uses_typed_detail_when_monto_seguro_is_empty(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["movements"][-1]["MONTO_SEGURO"] = "0.00"
        lifecycle["movements"][-1]["MONTO_OTROS"] = "0.10"

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        self.assertEqual(result["lifecycle"]["events"][-1]["allocation"]["fee"], "0.10")

    def test_insurance_component_without_typed_detail_is_quarantined(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["charge_details"] = []

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertIn("insurance_detail_missing:101", result["quarantine_reasons"])

    def test_refunded_cash_uses_applied_amount_without_changing_components(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        movement = lifecycle["movements"][-1]
        movement.update({"MONTO": "10.50", "MONTO_PAGADO": "10.00", "REINTEGRO_MONTO": "0.50"})

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        event = result["lifecycle"]["events"][-1]
        self.assertEqual(event["amount"], "10.00")
        self.assertEqual(event["source_gross_amount"], "10.50")
        self.assertEqual(event["source_refund_amount"], "0.50")
        self.assertEqual(event["amount_classification"], "source-applied-amount-after-refund")

    def test_fully_refunded_collection_is_not_posted_as_a_loan_payment(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        movement = lifecycle["movements"][-1]
        movement.update({
            "MONTO": "20.00", "MONTO_PAGADO": "0.00", "REINTEGRO_MONTO": "20.00",
            "MONTO_CAPITAL": "0.00", "MONTO_INTERES": "0.00", "MONTO_SEGURO": "0.00",
        })
        lifecycle["charge_details"] = []

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        self.assertEqual([event["role"] for event in result["lifecycle"]["events"]], ["disbursement"])
        self.assertEqual(result["lifecycle"]["refunded_unapplied_movements"], [{
            "source_movement_id": "101", "source_transaction": "14:00011",
            "gross_amount": "20.00", "refund_amount": "20.00",
            "classification": "fully-refunded-unapplied-collection",
        }])

    def test_verified_legacy_other_balance_becomes_historical_insurance_fee(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        movement = lifecycle["movements"][-1]
        movement.update({
            "MONTO_SEGURO": "0.00", "MONTO_OTROS": "0.10",
            "LEGACY_OTHER_PRE_BALANCE": "0.10", "LEGACY_OTHER_POST_BALANCE": "0.00",
            "LEGACY_OTHER_PRE_PAID": "0.00", "LEGACY_OTHER_POST_PAID": "0.10",
            "LEGACY_OTHER_INSURANCE_LEDGER_COUNT": 1,
        })
        lifecycle["charge_details"] = []

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        event = result["lifecycle"]["events"][-1]
        self.assertEqual(event["allocation"]["fee"], "0.10")
        self.assertEqual(event["historical_insurance_charges"], [{
            "source_charge_id": None, "source_payment_id": None,
            "external_id": "ARISSTO:CRD-INS-LEGACY:101", "charge_id": 10,
            "amount": "0.10", "due_date": "2026-06-20",
            "classification": "legacy-other-balance-confirmed-as-debt-insurance",
        }])

    def test_unproved_legacy_other_is_not_silently_mapped(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        movement = lifecycle["movements"][-1]
        movement.update({"MONTO_SEGURO": "0.00", "MONTO_OTROS": "0.10"})
        lifecycle["charge_details"] = []

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertIn("component_residual:101", result["quarantine_reasons"])
        self.assertEqual(result["lifecycle"]["events"][-1]["allocation"]["fee"], "0.00")

    def test_reversed_manual_adjusted_payment_pair_is_discarded(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["charge_details"] = []
        lifecycle["movements"] = [lifecycle["movements"][0], {
            "ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "101", "CODIGO_SISTEMA": 4,
            "ID_TRANSACCION": "00013", "REVERSION": "1", "FECHA_OPERACION": "2026-06-20",
            "MONTO": "1.00", "MONTO_CAPITAL": "1.00", "MONTO_INTERES": "1.00",
        }, {
            "ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "102", "CODIGO_SISTEMA": 4,
            "ID_TRANSACCION": "00004", "REVERSION": "", "FECHA_OPERACION": "2026-06-21",
            "MONTO": "1.00", "MONTO_CAPITAL": "1.00", "MONTO_INTERES": "1.00",
        }]

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        self.assertEqual([event["role"] for event in result["lifecycle"]["events"]], ["disbursement"])
        self.assertEqual(result["lifecycle"]["discarded_manual_adjustments"], [{
            "original_movement_id": "101", "reversal_movement_id": "102",
            "classification": "paired-reversed-manual-adjusted-payment",
        }])

    def test_late_approval_uses_general_compatibility_rule_and_preserves_provenance(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan["ID_CREDITO"] = 9999
        lifecycle["application"]["FECHA_APROBADO"] = "2026-07-01"
        lifecycle["application"]["FECHA_RESOLUCION"] = "2026-07-02"

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        frozen = result["lifecycle"]
        self.assertEqual(frozen["approval_payload"]["approvedOnDate"], "2026-06-11")
        self.assertEqual(frozen["legacy_timeline"], {
            "source_submitted_on": "2026-06-10",
            "source_approved_on": "2026-07-01",
            "source_resolution_on": "2026-07-02",
            "source_disbursed_on": "2026-06-11",
            "effective_approved_on": "2026-06-11",
            "classification": "legacy-late-approval-stamp",
        })

    def test_pre_client_activation_application_stamp_uses_activation_and_preserves_provenance(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        target["clients"]["0000000832"]["activation_date"] = "2026-06-11"
        lifecycle["application"]["FECHA_APROBADO"] = "2026-06-10"
        lifecycle["application"]["FECHA_RESOLUCION"] = "2026-06-10"

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        frozen = result["lifecycle"]
        self.assertEqual(frozen["application_payload"]["submittedOnDate"], "2026-06-11")
        self.assertEqual(frozen["approval_payload"]["approvedOnDate"], "2026-06-11")
        self.assertEqual(frozen["legacy_timeline"], {
            "source_submitted_on": "2026-06-10",
            "source_approved_on": "2026-06-10",
            "source_resolution_on": "2026-06-10",
            "source_disbursed_on": "2026-06-11",
            "effective_approved_on": "2026-06-11",
            "classification": "legacy-pre-client-activation-application-stamp",
        })

    def test_client_activation_after_disbursement_is_an_explicit_upstream_prerequisite(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        target["clients"]["0000000832"]["activation_date"] = "2026-06-12"

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertIn(
            "target_client_activation_after_effective_disbursement",
            result["quarantine_reasons"],
        )
        self.assertIsNone(result["lifecycle"]["legacy_timeline"])

    def test_pre_client_activation_compatibility_rejects_prior_financial_movement(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        target["clients"]["0000000832"]["activation_date"] = "2026-06-11"
        lifecycle["application"]["FECHA_APROBADO"] = "2026-06-10"
        lifecycle["movements"].insert(0, {
            "ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "99", "CODIGO_SISTEMA": 4,
            "ID_TRANSACCION": "00001", "REVERSION": "", "FECHA_OPERACION": "2026-06-10",
            "MONTO": "1", "MONTO_CAPITAL": "1",
        })

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertIn(
            "invalid_target_client_activation_date_order",
            result["quarantine_reasons"],
        )
        self.assertIsNone(result["lifecycle"]["legacy_timeline"])

    def test_late_approval_with_prior_financial_movement_stays_quarantined(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["application"]["FECHA_APROBADO"] = "2026-07-01"
        lifecycle["movements"].insert(0, {
            "ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "99", "CODIGO_SISTEMA": 4,
            "ID_TRANSACCION": "00001", "REVERSION": "", "FECHA_OPERACION": "2026-06-10",
            "MONTO": "1", "MONTO_CAPITAL": "1",
        })

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertIn("invalid_source_application_date_order", result["quarantine_reasons"])
        self.assertIsNone(result["lifecycle"]["legacy_timeline"])

    def test_late_approval_without_post_disbursement_first_due_stays_quarantined(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["application"]["FECHA_APROBADO"] = "2026-07-01"
        lifecycle["schedule"][0]["FECHA_PAGO"] = "2026-06-11"

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertIn("invalid_source_application_date_order", result["quarantine_reasons"])
        self.assertIsNone(result["lifecycle"]["legacy_timeline"])

    def test_legacy_timeline_reconciliation_accepts_fineract_date_arrays(self):
        expected = {
            "source_submitted_on": "2023-03-21",
            "source_approved_on": "2023-05-25",
            "source_resolution_on": "2023-05-25",
            "source_disbursed_on": "2023-03-30",
            "effective_approved_on": "2023-03-30",
            "classification": "legacy-late-approval-stamp",
        }
        actual = {
            "source_submitted_on": [2023, 3, 21],
            "source_approved_on": [2023, 5, 25],
            "source_resolution_on": [2023, 5, 25],
            "source_disbursed_on": [2023, 3, 30],
            "effective_approved_on": [2023, 3, 30],
            "classification": "legacy-late-approval-stamp",
        }

        self.assertEqual(_loan_legacy_timeline_differences(expected, actual), [])
        actual["effective_approved_on"] = [2023, 3, 31]
        self.assertEqual(
            _loan_legacy_timeline_differences(expected, actual),
            ["effective_approved_on"],
        )

    def test_inclusive_first_accrual_day_is_derived_from_schedule_signature(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan["ID_CREDITO"] = 9999
        loan["ID_FRECUENCIA"] = 30
        lifecycle["schedule"] = [
            {"NO_CUOTA": 1, "FECHA_PAGO": "2026-07-11", "MONTO_CAPITAL": "175.00",
             "MONTO_INTERES": "24.97", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
            {"NO_CUOTA": 2, "FECHA_PAGO": "2026-08-11", "MONTO_CAPITAL": "175.00",
             "MONTO_INTERES": "12.48", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
        ]

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        frozen = result["lifecycle"]
        self.assertEqual(frozen["application_payload"]["interestChargedFromDate"], "2026-06-10")
        self.assertEqual(frozen["application_payload"]["daysInYearType"], 365)
        self.assertEqual(frozen["first_accrual_day_policy"], {
            "classification": "legacy-inclusive-first-accrual-day",
            "interest_charged_from_date": "2026-06-10",
            "days_in_year_type": 365,
            "source_origin_date": "2026-06-11",
            "first_due_date": "2026-07-11",
            "first_interest": "24.97",
        })

    def test_exclusive_first_accrual_day_is_retained_as_normal_control(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan["ID_FRECUENCIA"] = 30
        lifecycle["schedule"] = [
            {"NO_CUOTA": 1, "FECHA_PAGO": "2026-07-11", "MONTO_CAPITAL": "175.00",
             "MONTO_INTERES": "24.16", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
            {"NO_CUOTA": 2, "FECHA_PAGO": "2026-08-11", "MONTO_CAPITAL": "175.00",
             "MONTO_INTERES": "12.48", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
        ]

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        frozen = result["lifecycle"]
        self.assertNotIn("interestChargedFromDate", frozen["application_payload"])
        self.assertEqual(frozen["first_accrual_day_policy"], {
            "classification": "normal-exclusive-first-accrual-day",
        })

    def test_partial_inclusive_first_accrual_signature_fails_closed(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan["ID_FRECUENCIA"] = 30
        lifecycle["schedule"] = [
            {"NO_CUOTA": 1, "FECHA_PAGO": "2026-07-11", "MONTO_CAPITAL": "175.00",
             "MONTO_INTERES": "24.97", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
            {"NO_CUOTA": 2, "FECHA_PAGO": "2026-08-11", "MONTO_CAPITAL": "175.00",
             "MONTO_INTERES": "12.47", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
        ]

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertIn("ambiguous_first_accrual_day_signature", result["quarantine_reasons"])
        self.assertNotIn("interestChargedFromDate", result["lifecycle"]["application_payload"])
        self.assertEqual(
            result["lifecycle"]["first_accrual_day_policy"]["classification"],
            "ambiguous-first-accrual-day-signature",
        )

    def test_loan_1484_uses_reviewed_manual_schedule_policy(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan["ID_CREDITO"] = 1484

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        self.assertEqual(
            result["lifecycle"]["schedule_reconciliation_policy"],
            "reviewed-manual-adjustment",
        )
        self.assertIsNone(result["lifecycle"]["schedule_writer"])

    def test_loan_83_keeps_incomplete_schedule_as_reference_only(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan["ID_CREDITO"] = 83

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        self.assertEqual(
            result["lifecycle"]["schedule_reconciliation_policy"],
            "historical-reference-only",
        )
        self.assertIsNone(result["lifecycle"]["schedule_writer"])

    def test_loan_26_keeps_zero_principal_schedule_as_reference_only_only_for_exact_closed_lifecycle(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan["ID_CREDITO"] = 26
        loan["source_state"] = "3"
        loan["MONTO_APROBADO"] = "350.00"
        lifecycle["schedule"] = [
            {
                "NO_CUOTA": 1, "FECHA_PAGO": "2026-06-26",
                "MONTO_CAPITAL": "0.00", "MONTO_INTERES": "17.26",
                "MONTO_OTROS": "0.00", "MONTO_APORTACION": 0,
                "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0,
            },
        ]
        lifecycle["movements"] = [
            {
                "ID_CREDITO": 26, "ID_MOVIMIENTO_CARTERA": "0001", "ID_CRD_MOVIMIENTO": 1,
                "CODIGO_SISTEMA": 4, "ID_TRANSACCION": "00002", "REVERSION": 0,
                "FECHA_OPERACION": "2026-06-11", "FECHA_VALOR": "2026-06-11",
                "FECHA_PAGO": None, "DT_MOVIMIENTO": "2026-06-11", "DT_CREO": "2026-06-11",
                "ID_CIERRE_DIARIO": "1", "ID_USUARIO": "1", "ID_USR_CREO": "1",
                "ID_CAJA": None, "ID_PARTIDA": None, "ID_TIPO_PAGO": None,
                "MONTO": "350.00", "MONTO_PAGADO": "350.00", "REINTEGRO_MONTO": "0.00",
                "MONTO_CAPITAL": "350.00", "MONTO_INTERES": "0.00",
                "MONTO_INT_PENDIENTES": "0.00", "MONTO_MORA": "0.00",
                "MONTO_OTROS": "0.00", "MONTO_SEGURO": "0.00", "MONTO_RECARGOS": "0.00",
                "MONTO_CXC": "0.00", "MONTO_AHORRO": "0.00", "MONTO_APORTACION": "0.00",
                "MONTO_IVA": "0.00", "MONTO_IVA_INTERES": "0.00", "MONTO_IVA_MORA": "0.00",
                "MONTO_IVA_INTERES_PEND": "0.00", "MONTO_IVA_OTROS": "0.00",
            },
            {
                "ID_CREDITO": 26, "ID_MOVIMIENTO_CARTERA": "0002", "ID_CRD_MOVIMIENTO": 2,
                "CODIGO_SISTEMA": 4, "ID_TRANSACCION": "00019", "REVERSION": 0,
                "FECHA_OPERACION": "2026-06-26", "FECHA_VALOR": "2026-06-26",
                "FECHA_PAGO": None, "DT_MOVIMIENTO": "2026-06-26", "DT_CREO": "2026-06-26",
                "ID_CIERRE_DIARIO": "2", "ID_USUARIO": "1", "ID_USR_CREO": "1",
                "ID_CAJA": None, "ID_PARTIDA": None, "ID_TIPO_PAGO": None,
                "MONTO": "350.00", "MONTO_PAGADO": "350.00", "REINTEGRO_MONTO": "0.00",
                "MONTO_CAPITAL": "350.00", "MONTO_INTERES": "0.00",
                "MONTO_INT_PENDIENTES": "0.00", "MONTO_MORA": "0.00",
                "MONTO_OTROS": "0.00", "MONTO_SEGURO": "0.00", "MONTO_RECARGOS": "0.00",
                "MONTO_CXC": "0.00", "MONTO_AHORRO": "0.00", "MONTO_APORTACION": "0.00",
                "MONTO_IVA": "0.00", "MONTO_IVA_INTERES": "0.00", "MONTO_IVA_MORA": "0.00",
                "MONTO_IVA_INTERES_PEND": "0.00", "MONTO_IVA_OTROS": "0.00",
            },
        ]
        lifecycle["refinance_outgoing"] = [{
            "old_credit_id": 26, "new_credit_id": 108,
            "payoff_movement_id": "0002", "disbursement_movement_id": "0003",
            "payoff_date": "2026-06-26", "payoff_amount": "350.00",
            "payoff_principal": "350.00", "payoff_interest": "0.00",
            "payoff_fee": "0.00", "payoff_penalty": "0.00", "payoff_reversed": 0,
        }]

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        self.assertEqual(
            result["lifecycle"]["schedule_reconciliation_policy"],
            "historical-reference-only",
        )
        self.assertIsNone(result["lifecycle"]["schedule_writer"])

        lifecycle["schedule"][0]["MONTO_CAPITAL"] = "1.00"
        near_match = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        self.assertIn(
            "historical_reference_schedule_signature_mismatch:"
            "closed-zero-principal-schedule-with-exact-lifecycle",
            near_match["quarantine_reasons"],
        )
        self.assertEqual(
            near_match["lifecycle"]["schedule_reconciliation_policy"],
            "exact-source-schedule",
        )

        lifecycle["schedule"][0]["MONTO_CAPITAL"] = "0.00"
        loan["source_state"] = "1"
        active_near_match = _build_loan_lifecycle_action(
            self.contract, loan, lifecycle, target, payload,
        )
        self.assertIn(
            "historical_reference_schedule_signature_mismatch:"
            "closed-zero-principal-schedule-with-exact-lifecycle",
            active_near_match["quarantine_reasons"],
        )

    def test_trailing_zero_core_schedule_loans_are_reference_only(self):
        for loan_id in (8, 1739, 1795, 1893, 2063, 2111, 2482):
            with self.subTest(loan_id=loan_id):
                loan, lifecycle, target, payload = self.lifecycle_fixture()
                loan["ID_CREDITO"] = loan_id
                lifecycle["schedule"].append({
                    "NO_CUOTA": 3,
                    "FECHA_PAGO": "2026-07-26",
                    "MONTO_CAPITAL": "0.00",
                    "MONTO_INTERES": "0.00",
                    "MONTO_OTROS": "1.00",
                    "MONTO_APORTACION": 0,
                    "ID_REESTRUCTURACION": None,
                    "CUOTA_DIFERIDA": 0,
                })

                result = _build_loan_lifecycle_action(
                    self.contract, loan, lifecycle, target, payload,
                )

                self.assertEqual(result["quarantine_reasons"], [])
                self.assertEqual(
                    result["lifecycle"]["schedule_reconciliation_policy"],
                    "historical-reference-only",
                )
                self.assertIsNone(result["lifecycle"]["schedule_writer"])
                self.assertEqual(result["lifecycle"]["discarded_manual_adjustments"], [])

    def test_terminal_charge_only_schedule_loans_are_reference_only_for_exact_signature(self):
        for loan_id in (381, 1775, 1871, 2006):
            with self.subTest(loan_id=loan_id):
                loan, lifecycle, target, payload = self.lifecycle_fixture()
                loan["ID_CREDITO"] = loan_id
                lifecycle["schedule"].append({
                    "NO_CUOTA": 3,
                    "FECHA_PAGO": "2026-07-26",
                    "MONTO_CAPITAL": "0.00",
                    "MONTO_INTERES": "0.00",
                    "MONTO_OTROS": "0.10",
                    "MONTO_APORTACION": 0,
                    "ID_REESTRUCTURACION": None,
                    "CUOTA_DIFERIDA": 0,
                })

                result = _build_loan_lifecycle_action(
                    self.contract, loan, lifecycle, target, payload,
                )

                self.assertEqual(result["quarantine_reasons"], [])
                self.assertEqual(
                    result["lifecycle"]["schedule_reconciliation_policy"],
                    "historical-reference-only",
                )
                self.assertIsNone(result["lifecycle"]["schedule_writer"])

    def test_terminal_charge_only_schedule_near_matches_fail_closed(self):
        mutations = {
            "terminal-principal": lambda rows: rows[-1].update(MONTO_CAPITAL="0.01"),
            "terminal-interest": lambda rows: rows[-1].update(MONTO_INTERES="0.01"),
            "missing-other": lambda rows: rows[-1].update(MONTO_OTROS="0.00"),
            "contribution": lambda rows: rows[-1].update(MONTO_APORTACION="0.01"),
            "restructured": lambda rows: rows[-1].update(ID_REESTRUCTURACION=1),
            "deferred": lambda rows: rows[-1].update(CUOTA_DIFERIDA=1),
            "principal-not-settled": lambda rows: rows[0].update(MONTO_CAPITAL="174.99"),
            "duplicate-number": lambda rows: rows[-1].update(NO_CUOTA=2),
            "non-monotonic": lambda rows: rows[-1].update(FECHA_PAGO="2026-07-11"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                loan, lifecycle, target, payload = self.lifecycle_fixture()
                loan["ID_CREDITO"] = 381
                lifecycle["schedule"].append({
                    "NO_CUOTA": 3,
                    "FECHA_PAGO": "2026-07-26",
                    "MONTO_CAPITAL": "0.00",
                    "MONTO_INTERES": "0.00",
                    "MONTO_OTROS": "0.10",
                    "MONTO_APORTACION": 0,
                    "ID_REESTRUCTURACION": None,
                    "CUOTA_DIFERIDA": 0,
                })
                mutate(lifecycle["schedule"])

                result = _build_loan_lifecycle_action(
                    self.contract, loan, lifecycle, target, payload,
                )

                self.assertIn(
                    "historical_reference_schedule_signature_mismatch:"
                    "terminal-zero-core-charge-only-row",
                    result["quarantine_reasons"],
                )
                self.assertEqual(
                    result["lifecycle"]["schedule_reconciliation_policy"],
                    "exact-source-schedule",
                )

    def test_non_monotonic_source_schedule_is_quarantined_before_fineract(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan["ID_CREDITO"] = 2374
        lifecycle["schedule"][1]["FECHA_PAGO"] = "2026-06-26"

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertIn(
            "non_monotonic_source_schedule_dates",
            result["quarantine_reasons"],
        )
        self.assertEqual(
            result["lifecycle"]["schedule_reconciliation_policy"],
            "exact-source-schedule",
        )

    def test_reviewed_manual_schedule_exception_can_keep_non_monotonic_dates(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan["ID_CREDITO"] = 945
        loan["line_id"] = "00001"
        lifecycle["schedule"][1]["FECHA_PAGO"] = "2026-06-26"

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertNotIn(
            "non_monotonic_source_schedule_dates",
            result["quarantine_reasons"],
        )
        self.assertEqual(
            result["lifecycle"]["schedule_reconciliation_policy"],
            "reviewed-manual-adjustment",
        )

    def test_reviewed_line_00010_manual_adjustments_can_keep_non_monotonic_dates(self):
        for loan_id in (23, 90, 317, 340, 359, 1117, 1743, 1748, 2069, 2241, 2254, 2355):
            with self.subTest(loan_id=loan_id):
                loan, lifecycle, target, payload = self.lifecycle_fixture()
                loan["ID_CREDITO"] = loan_id
                lifecycle["schedule"][1]["FECHA_PAGO"] = "2026-06-26"

                result = _build_loan_lifecycle_action(
                    self.contract, loan, lifecycle, target, payload,
                )

                self.assertNotIn(
                    "non_monotonic_source_schedule_dates",
                    result["quarantine_reasons"],
                )
                self.assertEqual(
                    result["lifecycle"]["schedule_reconciliation_policy"],
                    "reviewed-manual-adjustment",
                )

    def test_loan_2120_is_quarantined_as_superseded_undisbursed_source_shell(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan["ID_CREDITO"] = 2120

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(
            result["quarantine_reasons"],
            ["reviewed_source_error:superseded-undisbursed-shell:replacement-loan-2121"],
        )

    def test_local_proof_namespace_isolates_loan_and_every_transaction_identity(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        source_product = self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO")
        target.update({
            "products": {"00010": self.api_product(payload)},
            "crosswalks": {},
            "loans": {"ARISSTO:CRD:2068": {"id": 55}},
        })

        with patch("arissto_sync.loans.source_fingerprint", return_value="source"):
            plan = compose_loan_plan(
                SimpleNamespace(target=SimpleNamespace(fingerprint="target"), source=SimpleNamespace()),
                self.contract, [loan], [source_product], target, source_keys=["2068"],
                source_lifecycles={2068: lifecycle}, proof_namespace="allocation-1",
            )

        action = plan["actions"][1]
        self.assertEqual(action["action"], "create-loan")
        self.assertEqual(action["external_id"], "PROOF:allocation-1:ARISSTO:CRD:2068")
        self.assertEqual(action["lifecycle"]["application_payload"]["externalId"], action["external_id"])
        self.assertTrue(all(
            event["external_id"].startswith("PROOF:allocation-1:")
            for event in action["lifecycle"]["events"]
        ))
        self.assertEqual(plan["scope"]["proof_namespace"], "allocation-1")

        with patch("arissto_sync.loans.source_fingerprint", return_value="source"):
            canonical_plan = compose_loan_plan(
                SimpleNamespace(target=SimpleNamespace(fingerprint="target"), source=SimpleNamespace()),
                self.contract, [loan], [source_product], target, source_keys=["2068"],
                source_lifecycles={2068: lifecycle},
            )
        self.assertEqual(action["source_hash"], canonical_plan["actions"][1]["source_hash"])

    def test_proof_namespace_covers_reversal_and_refinance_identifiers(self):
        lifecycle = {
            "application_payload": {"externalId": "ARISSTO:CRD:1"},
            "events": [{
                "external_id": "ARISSTO:CRD-MOV:2",
                "original_external_id": "ARISSTO:CRD-MOV:1",
                "successor_disbursement_external_id": "ARISSTO:CRD-MOV:3",
            }],
            "refinance": {
                "predecessor_external_id": "ARISSTO:CRD:0",
                "payoff_external_id": "ARISSTO:CRD-MOV:4",
                "disbursement_external_id": "ARISSTO:CRD-MOV:5",
                "topup_transfer_external_id": "ARISSTO:CRD-MOV:5:TOPUP",
                "adjustment_external_id": "ARISSTO:CRD-REFI:0:1",
                "final_adjustment_external_id": "ARISSTO:CRD-REFI-FINAL:0:1",
                "penalty_charge_external_id": "ARISSTO:CRD-MOV:4:PENALTY",
            },
            "terminal_adjustment": {"external_id": "ARISSTO:CRD-CUTOVER:1"},
        }

        result = _proof_namespace_lifecycle(lifecycle, "allocation-1")

        identifiers = [result["application_payload"]["externalId"]]
        identifiers.extend(value for key, value in result["events"][0].items() if key.endswith("external_id"))
        identifiers.extend(value for key, value in result["refinance"].items() if key.endswith("external_id"))
        identifiers.append(result["terminal_adjustment"]["external_id"])
        self.assertTrue(all(value.startswith("PROOF:allocation-1:") for value in identifiers))

    def test_lifecycle_plan_freezes_native_refinance_relationship(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["movements"].append({
            "ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "102", "CODIGO_SISTEMA": 4,
            "ID_TRANSACCION": "00019", "REVERSION": "", "FECHA_OPERACION": "2026-06-21",
            "MONTO": "0",
        })
        lifecycle["refinance_outgoing"] = [{
            "old_credit_id": 2068, "new_credit_id": 3000,
            "payoff_movement_id": "102", "payoff_amount": "0",
            "payoff_date": "2026-06-21", "disbursement_movement_id": "200",
        }]
        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        self.assertEqual(result["quarantine_reasons"], [])
        event = result["lifecycle"]["events"][-1]
        self.assertEqual(event["role"], "native-refinance-payoff")
        self.assertEqual(event["successor_source_key"], "3000")
        self.assertIsNone(result["lifecycle"]["terminal_adjustment"])

    def test_lifecycle_plan_freezes_source_exact_incoming_refinance_payoff(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["refinance_incoming"] = [{
            "old_credit_id": 1000, "new_credit_id": 2068,
            "payoff_movement_id": "99", "payoff_amount": "42.50",
            "payoff_principal": "40.00", "payoff_interest": "2.00",
            "payoff_fee": "0.50", "payoff_penalty": "0.00",
            "payoff_date": "2026-06-11", "disbursement_movement_id": "100",
            "payoff_insurance_details": [{
                "ID_RECARGO_CARTERA": "200362", "ID_PAGOS": "0046",
                "MONTO_COBRADO": "0.50",
            }],
        }]

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        refinance = result["lifecycle"]["refinance"]
        self.assertEqual(refinance["payoff_allocation"], {
            "principal": "40.00", "interest": "2.00", "fee": "0.50", "penalty": "0.00",
        })
        self.assertEqual(refinance["operation_type"], "SINGLE_REFINANCE")
        self.assertEqual(refinance["topup_transfer_external_id"], "ARISSTO:CRD-MOV:100:REFINANCE:1000")
        self.assertEqual(refinance["historical_insurance_charges"], [{
            "source_charge_id": "200362",
            "source_payment_id": "0046",
            "external_id": "ARISSTO:CRD-INS:200362:99:0046",
            "charge_id": target["resources"]["historical_debt_insurance_charge_id"],
            "amount": "0.50",
            "due_date": "2026-06-11",
        }])

    def test_lifecycle_plan_builds_multi_predecessor_consolidation(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["refinance_incoming"] = [
            {
                "old_credit_id": 1, "new_credit_id": 2068,
                "payoff_movement_id": "91", "payoff_amount": "42.00",
                "payoff_principal": "40.00", "payoff_interest": "2.00",
                "payoff_fee": "0.00", "payoff_penalty": "0.00",
                "payoff_date": "2026-06-11", "disbursement_movement_id": "100",
            },
            {
                "old_credit_id": 2, "new_credit_id": 2068,
                "payoff_movement_id": "92", "payoff_amount": "30.50",
                "payoff_principal": "30.00", "payoff_interest": "0.50",
                "payoff_fee": "0.00", "payoff_penalty": "0.00",
                "payoff_date": "2026-06-11", "disbursement_movement_id": "100",
            },
        ]
        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        refinance = result["lifecycle"]["refinance"]
        self.assertEqual(refinance["operation_type"], "CONSOLIDATION")
        self.assertEqual([item["predecessor_source_key"] for item in refinance["settlements"]], ["1", "2"])
        self.assertEqual(
            [item["transfer_external_id"] for item in refinance["settlements"]],
            ["ARISSTO:CRD-MOV:100:REFINANCE:1", "ARISSTO:CRD-MOV:100:REFINANCE:2"],
        )

    def test_lifecycle_plan_quarantines_inconsistent_consolidation_liquidations(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["refinance_incoming"] = [
            {"old_credit_id": 1, "payoff_date": "2026-06-11", "disbursement_movement_id": "100"},
            {"old_credit_id": 2, "payoff_date": "2026-06-12", "disbursement_movement_id": "101"},
        ]

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertIn("multi_predecessor_refinance_inconsistent_liquidation", result["quarantine_reasons"])

    def test_lifecycle_plan_quarantines_cross_client_consolidation(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["refinance_incoming"] = [
            {
                "old_credit_id": 1, "payoff_date": "2026-06-11",
                "disbursement_movement_id": "100", "same_owner": 1,
                "payoff_movement_id": "91", "payoff_amount": "42.00",
                "payoff_principal": "40.00", "payoff_interest": "2.00",
                "payoff_fee": "0.00", "payoff_penalty": "0.00",
            },
            {
                "old_credit_id": 2, "payoff_date": "2026-06-11",
                "disbursement_movement_id": "100", "same_owner": 0,
                "payoff_movement_id": "92", "payoff_amount": "30.50",
                "payoff_principal": "30.00", "payoff_interest": "0.50",
                "payoff_fee": "0.00", "payoff_penalty": "0.00",
            },
        ]

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertIn("cross_client_refinance_requires_authorization", result["quarantine_reasons"])

    def test_lifecycle_plan_quarantines_reversed_refinance_relationship(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["refinance_incoming"] = [{
            "old_credit_id": 1000, "new_credit_id": 2068,
            "payoff_movement_id": "99", "payoff_amount": "42.00",
            "payoff_date": "2026-06-11", "disbursement_movement_id": "100",
            "payoff_reversed": "1",
        }]

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertIn("reversed_refinance_topup_not_supported", result["quarantine_reasons"])

    def test_voided_refinance_classifier_removes_only_complete_net_zero_edge(self):
        voided_link = {
            "old_credit_id": 1, "new_credit_id": 2,
            "payoff_movement_id": "10", "payoff_amount": "42.00",
            "payoff_date": "2026-01-02", "disbursement_movement_id": "20",
            "payoff_reversed": "1",
        }
        active_link = {
            "old_credit_id": 1, "new_credit_id": 3,
            "payoff_movement_id": "12", "payoff_amount": "40.00",
            "payoff_date": "2026-02-02", "disbursement_movement_id": "30",
            "payoff_reversed": "",
        }
        loans = [
            {"ID_CREDITO": 1},
            {
                "ID_CREDITO": 2, "source_state": "3", "MONTO_DESEMBOLSADO": "0",
                "ULTIMO_SALDO": "0", "SALDO_INTERES": "0",
                "SALDO_INTERES_PENDIENTE": "0", "SALDO_MORA": "0",
                "SALDO_SEGURO": "0", "SALDO_RECARGOS": "0", "SALDO_CXC": "0",
                "SALDO_TOTAL": "0",
            },
            {"ID_CREDITO": 3},
        ]
        lifecycles = {
            1: {
                "movements": [
                    {"ID_CREDITO": 1, "ID_MOVIMIENTO_CARTERA": "10", "CODIGO_SISTEMA": 4,
                     "ID_TRANSACCION": "00019", "REVERSION": "1",
                     "FECHA_OPERACION": "2026-01-02", "MONTO": "42", "MONTO_CAPITAL": "42"},
                    {"ID_CREDITO": 1, "ID_MOVIMIENTO_CARTERA": "11", "CODIGO_SISTEMA": 4,
                     "ID_TRANSACCION": "00004", "REVERSION": "",
                     "FECHA_OPERACION": "2026-01-03", "MONTO": "42", "MONTO_CAPITAL": "42"},
                ],
                "refinance_incoming": [], "refinance_outgoing": [voided_link, active_link],
            },
            2: {
                "movements": [
                    {"ID_CREDITO": 2, "ID_MOVIMIENTO_CARTERA": "20", "CODIGO_SISTEMA": 4,
                     "ID_TRANSACCION": "00002", "REVERSION": "1",
                     "FECHA_OPERACION": "2026-01-02", "MONTO": "100", "MONTO_CAPITAL": "100"},
                    {"ID_CREDITO": 2, "ID_MOVIMIENTO_CARTERA": "21", "CODIGO_SISTEMA": 4,
                     "ID_TRANSACCION": "00030", "REVERSION": "",
                     "FECHA_OPERACION": "2026-01-03", "MONTO": "100", "MONTO_CAPITAL": "100"},
                ],
                "refinance_incoming": [voided_link], "refinance_outgoing": [],
            },
            3: {
                "movements": [], "refinance_incoming": [active_link], "refinance_outgoing": [],
            },
        }

        result = _classify_voided_refinance_attempts(loans, lifecycles)

        self.assertEqual(len(result), 1)
        self.assertEqual(lifecycles[1]["refinance_outgoing"], [active_link])
        self.assertEqual(lifecycles[2]["refinance_incoming"], [])
        self.assertEqual(lifecycles[3]["refinance_incoming"], [active_link])
        self.assertEqual(lifecycles[1]["discarded_voided_refinance_movement_ids"], ["10", "11"])
        self.assertEqual(lifecycles[2]["discarded_voided_refinance_movement_ids"], ["20", "21"])
        self.assertTrue(lifecycles[2]["omit_financial_reconstruction"])

    def test_voided_refinance_classifier_fails_closed_on_nonzero_successor(self):
        link = {
            "old_credit_id": 1, "new_credit_id": 2,
            "payoff_movement_id": "10", "payoff_amount": "42.00",
            "payoff_date": "2026-01-02", "disbursement_movement_id": "20",
            "payoff_reversed": "1",
        }
        loans = [
            {"ID_CREDITO": 1},
            {
                "ID_CREDITO": 2, "source_state": "3", "MONTO_DESEMBOLSADO": "0",
                "ULTIMO_SALDO": "0", "SALDO_INTERES": "0",
                "SALDO_INTERES_PENDIENTE": "0", "SALDO_MORA": "0",
                "SALDO_SEGURO": "0", "SALDO_RECARGOS": "0", "SALDO_CXC": "0",
                "SALDO_TOTAL": "0.01",
            },
        ]
        lifecycles = {
            1: {
                "movements": [
                    {"ID_CREDITO": 1, "ID_MOVIMIENTO_CARTERA": "10", "CODIGO_SISTEMA": 4,
                     "ID_TRANSACCION": "00019", "REVERSION": "1",
                     "FECHA_OPERACION": "2026-01-02", "MONTO": "42", "MONTO_CAPITAL": "42"},
                    {"ID_CREDITO": 1, "ID_MOVIMIENTO_CARTERA": "11", "CODIGO_SISTEMA": 4,
                     "ID_TRANSACCION": "00004", "REVERSION": "",
                     "FECHA_OPERACION": "2026-01-03", "MONTO": "42", "MONTO_CAPITAL": "42"},
                ],
                "refinance_incoming": [], "refinance_outgoing": [link],
            },
            2: {
                "movements": [
                    {"ID_CREDITO": 2, "ID_MOVIMIENTO_CARTERA": "20", "CODIGO_SISTEMA": 4,
                     "ID_TRANSACCION": "00002", "REVERSION": "",
                     "FECHA_OPERACION": "2026-01-02", "MONTO": "100", "MONTO_CAPITAL": "100"},
                    {"ID_CREDITO": 2, "ID_MOVIMIENTO_CARTERA": "21", "CODIGO_SISTEMA": 4,
                     "ID_TRANSACCION": "00030", "REVERSION": "",
                     "FECHA_OPERACION": "2026-01-03", "MONTO": "100", "MONTO_CAPITAL": "100"},
                ],
                "refinance_incoming": [link], "refinance_outgoing": [],
            },
        }

        result = _classify_voided_refinance_attempts(loans, lifecycles)

        self.assertEqual(result, [])
        self.assertEqual(lifecycles[1]["refinance_outgoing"], [link])
        self.assertEqual(lifecycles[2]["refinance_incoming"], [link])
        self.assertNotIn("omit_financial_reconstruction", lifecycles[2])

    def test_lifecycle_plan_omits_classified_voided_refinance_movements(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["movements"].extend([
            {"ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "102", "CODIGO_SISTEMA": 4,
             "ID_TRANSACCION": "00019", "REVERSION": "1", "FECHA_OPERACION": "2026-06-21",
             "MONTO": "42", "MONTO_CAPITAL": "42"},
            {"ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "103", "CODIGO_SISTEMA": 4,
             "ID_TRANSACCION": "00004", "REVERSION": "", "FECHA_OPERACION": "2026-06-22",
             "MONTO": "42", "MONTO_CAPITAL": "42"},
            {"ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "104", "CODIGO_SISTEMA": 4,
             "ID_TRANSACCION": "00019", "REVERSION": "", "FECHA_OPERACION": "2026-06-23",
             "MONTO": "0"},
        ])
        lifecycle["refinance_outgoing"] = [{
            "old_credit_id": 2068, "new_credit_id": 3001,
            "payoff_movement_id": "104", "payoff_amount": "0",
            "payoff_date": "2026-06-23", "disbursement_movement_id": "200",
        }]
        lifecycle["voided_refinance_attempts"] = [{
            "classification": "reviewed-voided-refinance-attempt",
            "abandoned_successor_source_key": "3000",
        }]
        lifecycle["discarded_voided_refinance_movement_ids"] = ["102", "103"]

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        self.assertEqual(
            [event["source_movement_id"] for event in result["lifecycle"]["events"]],
            ["100", "101", "104"],
        )
        self.assertEqual(
            result["lifecycle"]["discarded_voided_refinance_movement_ids"], ["102", "103"]
        )

    def test_lifecycle_plan_quarantines_omitted_voided_successor_without_events(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan.update({
            "source_state": "3", "MONTO_DESEMBOLSADO": "0", "ULTIMO_SALDO": "0",
            "SALDO_INTERES": "0", "SALDO_INTERES_PENDIENTE": "0", "SALDO_MORA": "0",
            "SALDO_SEGURO": "0", "SALDO_RECARGOS": "0", "SALDO_TOTAL": "0",
        })
        lifecycle["movements"] = [
            {"ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "100", "CODIGO_SISTEMA": 4,
             "ID_TRANSACCION": "00002", "REVERSION": "1", "FECHA_OPERACION": "2026-06-11",
             "MONTO": "350", "MONTO_CAPITAL": "350"},
            {"ID_CREDITO": 2068, "ID_MOVIMIENTO_CARTERA": "102", "CODIGO_SISTEMA": 4,
             "ID_TRANSACCION": "00030", "REVERSION": "", "FECHA_OPERACION": "2026-06-12",
             "MONTO": "350", "MONTO_CAPITAL": "350"},
        ]
        lifecycle["charge_details"] = []
        lifecycle["voided_refinance_attempts"] = [{
            "classification": "reviewed-voided-refinance-attempt",
            "predecessor_source_key": "1000",
        }]
        lifecycle["discarded_voided_refinance_movement_ids"] = ["100", "102"]
        lifecycle["omit_financial_reconstruction"] = True

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(
            result["quarantine_reasons"], ["reviewed_voided_refinance_attempt_omitted"]
        )
        self.assertEqual(result["lifecycle"]["events"], [])
        self.assertTrue(result["lifecycle"]["financial_reconstruction_omitted"])

    def test_lifecycle_plan_accepts_approved_undisbursed_without_origination_date(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan.update({
            "source_state": "2", "FECHA_OTORGAMIENTO": None, "ULTIMO_SALDO": "0",
            "SALDO_TOTAL": "0", "MONTO_APROBADO": "0", "MONTO_DESEMBOLSADO": "0",
            "NO_CUOTAS_APROBADO": 0,
        })
        lifecycle["movements"] = []
        lifecycle["schedule"] = []
        lifecycle["application"].update({
            "FECHA_DESEMBOLSO": "2026-06-20", "FECHA_PACTADA": "2026-06-21",
            "MONTO_APROBADO": "400", "MONTO_SOLICITADO": "500",
            "NO_CUOTAS_APROBADO": 20, "INTERES_MONTO_APROBADO": "84",
        })

        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)

        self.assertEqual(result["quarantine_reasons"], [])
        frozen = result["lifecycle"]
        self.assertEqual(frozen["application_payload"]["expectedDisbursementDate"], "2026-06-20")
        self.assertEqual(frozen["approval_payload"]["expectedDisbursementDate"], "2026-06-20")
        self.assertEqual(frozen["application_payload"]["principal"], "400.00")
        self.assertEqual(frozen["application_payload"]["numberOfRepayments"], 20)
        self.assertEqual(frozen["events"], [])

    def test_lifecycle_plan_does_not_require_native_loan_officer_role(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        target["staff"]["001:00037"]["loan_officer"] = False
        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        self.assertEqual(result["quarantine_reasons"], [])
        self.assertNotIn("loanOfficerId", result["lifecycle"]["application_payload"])

    def test_lifecycle_preserves_all_three_staff_roles_independently(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan["collections_manager_id"] = "00044"
        loan["account_executive_id"] = "00045"
        target["staff"]["001:00044"] = {
            "id": 44, "active": True, "loan_officer": True, "office_id": 1,
        }
        target["staff"]["001:00045"] = {
            "id": 45, "active": False, "loan_officer": False, "office_id": 1,
        }
        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        self.assertEqual(result["staff_external_ids"], {
            "promoter": "001:00037", "account_executive": "001:00045",
            "collections_manager": "001:00044",
        })
        self.assertEqual(result["lifecycle"]["staff_assignment"]["promoter_staff_id"], 40)
        self.assertEqual(result["lifecycle"]["staff_assignment"]["account_executive_staff_id"], 45)
        self.assertEqual(result["lifecycle"]["staff_assignment"]["collections_manager_staff_id"], 44)
        self.assertNotIn("loanOfficerId", result["lifecycle"]["application_payload"])

    def test_lifecycle_preserves_promoter_without_deriving_loan_officer(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        result = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        self.assertEqual(result["staff_external_ids"]["promoter"], "001:00037")
        self.assertEqual(result["lifecycle"]["staff_assignment"]["promoter_staff_id"], 40)
        self.assertNotIn("loanOfficerId", result["lifecycle"]["application_payload"])

    def test_lifecycle_writer_persists_legacy_timeline_and_recovers_payment(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        lifecycle["application"]["FECHA_APROBADO"] = "2026-07-01"
        lifecycle["application"]["FECHA_RESOLUCION"] = "2026-07-02"
        built = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        action = {"external_id": "ARISSTO:CRD:2068", "lifecycle": built["lifecycle"]}
        pending = {"id": 55, "loanProductId": 90, "clientId": 900, "principal": 350,
                   "status": {"id": 100}, "transactions": [],
                   "repaymentSchedule": self.calculated_schedule(built["lifecycle"])}
        approved = {**pending, "status": {"id": 200}}
        active = {**pending, "status": {"id": 300}, "transactions": [
            {"id": 1, "externalId": "ARISSTO:CRD-MOV:100", "amount": 350},
        ]}
        paid = {**active, "transactions": active["transactions"] + [{
            "id": 2, "externalId": "ARISSTO:CRD-MOV:101", "amount": 10,
            "principalPortion": 8, "interestPortion": 1.9,
            "feeChargesPortion": .1, "penaltyChargesPortion": 0,
        }]}
        api = MagicMock()
        api.calculate_loan_schedule.return_value = self.calculated_schedule(built["lifecycle"])
        api.request.side_effect = [
            {"resourceId": 55}, {}, approved, {}, active, {}, paid,
        ]
        with (
            patch("arissto_sync.loans._find_loan", side_effect=[None, pending]),
            patch("arissto_sync.loans._ensure_source_insurance_charges", side_effect=lambda api, loan, *_: loan),
            patch("arissto_sync.loans._ensure_recurring_insurance_charge", side_effect=lambda api, loan, *_: loan),
        ):
            loan_id, recovered = _apply_loan_lifecycle(api, action, 90)

        self.assertEqual((loan_id, recovered), (55, False))
        self.assertEqual(api.upsert_datatable.call_args_list, [
            call(
                "credesal_loan_staff_assignment", "55",
                datatable_api_payload(built["lifecycle"]["staff_assignment"]),
            ),
            call(
                "credesal_loan_legacy_timeline", "55",
                datatable_api_payload(built["lifecycle"]["legacy_timeline"]),
            ),
        ])
        commands = [call.kwargs.get("query", {}).get("command") for call in api.request.call_args_list]
        self.assertEqual(commands, [None, "approve", None, "disburse", None, "sourceExactRepayment", None])
        repayment_payload = api.request.call_args_list[5].args[2]
        self.assertEqual(
            {key: repayment_payload[key] for key in (
                "principalPortion", "interestPortion", "feeChargesPortion", "penaltyChargesPortion",
            )},
            {"principalPortion": "8.00", "interestPortion": "1.90", "feeChargesPortion": "0.10",
             "penaltyChargesPortion": "0.00"},
        )

    def test_lifecycle_writer_writes_source_exact_variations_before_approval(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        built = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        built["lifecycle"]["cutover_insurance_charge"] = None
        built["lifecycle"]["recurring_insurance_charge"] = None
        built["lifecycle"]["events"] = []
        action = {"external_id": "ARISSTO:CRD:2068", "lifecycle": built["lifecycle"]}
        calculated = self.calculated_schedule(built["lifecycle"])
        calculated["periods"][0]["interestDue"] = "12.01"
        calculated["totalInterestCharged"] = Decimal("18.01")
        api = MagicMock()
        exact = self.calculated_schedule(built["lifecycle"])
        pending_drift = {
            "id": 55, "loanProductId": 90, "clientId": 900, "principal": 350,
            "status": {"id": 100}, "transactions": [], "repaymentSchedule": calculated,
        }
        pending_exact = {**pending_drift, "repaymentSchedule": exact}
        api.calculate_loan_schedule.return_value = calculated
        api.calculate_variable_loan_schedule.return_value = exact
        api.request.side_effect = [{"resourceId": 55}, {}]
        with patch(
            "arissto_sync.loans._find_loan",
            side_effect=[None, pending_drift, pending_exact],
        ):
            loan_id, recovered = _apply_loan_lifecycle(api, action, 90)

        self.assertEqual((loan_id, recovered), (55, False))
        variations = api.calculate_variable_loan_schedule.call_args.args[1]
        self.assertEqual(
            variations["exceptions"]["modifiedinstallments"],
            [{"dueDate": "2026-06-26", "installmentAmount": "187.00"}],
        )
        api.add_loan_schedule_variations.assert_called_once()
        self.assertEqual(
            api.request.call_args.kwargs.get("query", {}).get("command"), "approve",
        )

    def test_lifecycle_writer_prepares_refinance_before_source_exact_preview(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        built = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        built["lifecycle"]["cutover_insurance_charge"] = None
        built["lifecycle"]["recurring_insurance_charge"] = None
        built["lifecycle"]["events"] = []
        built["lifecycle"]["refinance"] = {
            "predecessor_external_id": "ARISSTO:CRD:2096",
        }
        action = {"external_id": "ARISSTO:CRD:2243", "lifecycle": built["lifecycle"]}
        predecessor = {"id": 342, "clientId": 900}
        pending = {
            "id": 55, "loanProductId": 90, "clientId": 900, "principal": 350,
            "status": {"id": 100}, "transactions": [],
            "repaymentSchedule": self.calculated_schedule(built["lifecycle"]),
        }
        api = MagicMock()
        api.calculate_loan_schedule.return_value = self.calculated_schedule(built["lifecycle"])
        api.request.side_effect = [{"resourceId": 55}, {}]

        def prepare_before_preview(api_arg, predecessor_arg, refinance_arg, attempt_key):
            self.assertEqual(api.calculate_loan_schedule.call_count, 0)
            return predecessor_arg

        with (
            patch("arissto_sync.loans._find_loan", side_effect=[None, predecessor, pending]),
            patch(
                "arissto_sync.loans._ensure_refinance_prepayment_ready",
                side_effect=prepare_before_preview,
            ) as prepare,
        ):
            loan_id, recovered = _apply_loan_lifecycle(api, action, 90)

        self.assertEqual((loan_id, recovered), (55, False))
        prepare.assert_called_once()
        preview_payload = api.calculate_loan_schedule.call_args.args[0]
        self.assertEqual(preview_payload["loanIdToClose"], 342)

    def test_lifecycle_writer_rejects_recovered_schedule_drift_before_continuing(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        built = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        action = {"external_id": "ARISSTO:CRD:2068", "lifecycle": built["lifecycle"]}
        calculated = self.calculated_schedule(built["lifecycle"])
        calculated["periods"][0]["dueDate"] = [2026, 6, 27]
        existing = {
            "id": 55, "loanProductId": 90, "clientId": 900, "principal": 350,
            "status": {"id": 300}, "transactions": [], "repaymentSchedule": calculated,
        }
        api = MagicMock()

        with (
            patch("arissto_sync.loans._find_loan", return_value=existing),
            self.assertRaisesRegex(RuntimeError, "existing_loan_schedule_mismatch_before_continue"),
        ):
            _apply_loan_lifecycle(api, action, 90)

        api.request.assert_not_called()

    def test_lifecycle_writer_rejects_plan_without_frozen_writer_version(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        built = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        built["lifecycle"].pop("schedule_writer")
        action = {"external_id": "ARISSTO:CRD:2068", "lifecycle": built["lifecycle"]}

        with self.assertRaisesRegex(
            RuntimeError, "loan_plan_predates_source_exact_schedule_writer",
        ):
            _apply_loan_lifecycle(MagicMock(), action, 90)

    def test_closed_source_loan_keeps_cash_exact_and_uses_explicit_cutover_adjustment(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan.update({
            "source_state": "3", "ULTIMO_SALDO": "0", "SALDO_INTERES": "0",
            "SALDO_SEGURO": "0", "SALDO_TOTAL": "0",
        })
        lifecycle["movements"][-1].update({"CODIGO_SISTEMA": 4, "ID_TRANSACCION": "00001"})
        built = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        self.assertEqual(built["lifecycle"]["events"][-1]["role"], "repayment")
        self.assertEqual(
            built["lifecycle"]["terminal_adjustment"]["external_id"],
            "ARISSTO:CRD-CUTOVER:2068",
        )
        action = {"external_id": "ARISSTO:CRD:2068", "lifecycle": built["lifecycle"]}
        pending = {"id": 55, "loanProductId": 90, "clientId": 900, "principal": 350,
                   "status": {"id": 100}, "transactions": [],
                   "repaymentSchedule": self.calculated_schedule(built["lifecycle"])}
        approved = {**pending, "status": {"id": 200}}
        active = {**pending, "status": {"id": 300}, "transactions": [
            {"id": 1, "externalId": "ARISSTO:CRD-MOV:100", "amount": 350},
        ]}
        paid = {**active, "summary": {"totalOutstanding": 2},
                "transactions": active["transactions"] + [{
            "id": 2, "externalId": "ARISSTO:CRD-MOV:101", "amount": 10,
            "principalPortion": 8, "interestPortion": 1.9,
            "feeChargesPortion": .1, "penaltyChargesPortion": 0,
        }]}
        closed = {**pending, "status": {"id": 600}, "summary": {"totalOutstanding": 0},
                  "transactions": paid["transactions"] + [{
            "id": 3, "externalId": "ARISSTO:CRD-CUTOVER:2068", "amount": 2,
        }]}
        api = MagicMock()
        api.calculate_loan_schedule.return_value = self.calculated_schedule(built["lifecycle"])
        api.request.side_effect = [
            {"resourceId": 55}, {}, approved, {}, active, {}, paid, paid, {}, closed,
        ]
        with (
            patch("arissto_sync.loans._find_loan", side_effect=[None, pending]),
            patch("arissto_sync.loans._ensure_source_insurance_charges", side_effect=lambda api, loan, *_: loan),
        ):
            loan_id, recovered = _apply_loan_lifecycle(api, action, 90)

        self.assertEqual((loan_id, recovered), (55, False))
        commands = [call.kwargs.get("query", {}).get("command") for call in api.request.call_args_list]
        self.assertEqual(
            commands,
            [None, "approve", None, "disburse", None, "sourceExactRepayment", None, None, "goodwillCredit", None],
        )

    def test_closed_mobile_collection_payoff_keeps_payment_type_and_separate_adjustment(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        loan.update({"source_state": "3", "ULTIMO_SALDO": "0", "SALDO_TOTAL": "0"})
        built = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        self.assertEqual(built["quarantine_reasons"], [])
        self.assertEqual(built["lifecycle"]["events"][-1]["role"], "mobile-collection-repayment")
        self.assertEqual(built["lifecycle"]["events"][-1]["payment_type_id"], 9)
        self.assertIsNotNone(built["lifecycle"]["terminal_adjustment"])

    def test_reconcile_validates_balances_transactions_and_balanced_journal(self):
        loan, lifecycle, target, payload = self.lifecycle_fixture()
        built = _build_loan_lifecycle_action(self.contract, loan, lifecycle, target, payload)
        action = {
            "source_key": "loan:2068", "entity_type": "loan", "external_id": "ARISSTO:CRD:2068",
            "lifecycle": built["lifecycle"],
        }
        target_loan = {
            "id": 55, "status": {"id": 300, "value": "Active"},
            "summary": {"principalOutstanding": 342, "interestOutstanding": 1.9,
                        "feeChargesOutstanding": .1, "penaltyChargesOutstanding": 0,
                        "totalOutstanding": 344},
            "repaymentSchedule": {
                "totalPrincipalExpected": 350, "totalInterestCharged": 18,
                "periods": [
                    {"period": 1, "dueDate": [2026, 6, 26], "principalDue": 175,
                     "interestDue": 12},
                    {"period": 2, "dueDate": [2026, 7, 11], "principalDue": 175,
                     "interestDue": 6},
                ],
            },
            "transactions": [
                {"id": 1, "externalId": "ARISSTO:CRD-MOV:100", "amount": 350},
                {"id": 2, "externalId": "ARISSTO:CRD-MOV:101", "amount": 10,
                 "principalPortion": 8, "interestPortion": 1.9,
                 "feeChargesPortion": .1, "penaltyChargesPortion": 0},
            ],
        }
        state = MagicMock()
        state.run.return_value = {"block": "loans", "target_fingerprint": "target", "plan_id": "plan"}
        state.plan.return_value = {
            "contract_hash": self.contract.digest, "document": {"actions": [action]},
        }
        state.run_items.return_value = [{"source_key": "loan:2068", "status": "succeeded"}]
        api = MagicMock()
        assignment = built["lifecycle"]["staff_assignment"]
        api.datatable_data.return_value = {
            "columnHeaders": [{"columnName": column} for column in assignment],
            "data": [{"row": list(assignment.values())}],
        }
        api.request.return_value = {"pageItems": [
            {"amount": 10, "entryType": {"value": "DEBIT"}},
            {"amount": 10, "entryType": {"value": "CREDIT"}},
        ]}
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target"))
        with (
            patch("arissto_sync.loans.FineractApi", return_value=api),
            patch("arissto_sync.loans._find_loan", return_value=target_loan),
        ):
            result = reconcile_loans(settings, state, self.contract, "run")
        self.assertTrue(result["ok"])
        self.assertEqual(result["mismatches"], [])

        target_loan["repaymentSchedule"]["periods"][0]["dueDate"] = [2026, 6, 27]
        with (
            patch("arissto_sync.loans.FineractApi", return_value=api),
            patch("arissto_sync.loans._find_loan", return_value=target_loan),
        ):
            schedule_date_drift = reconcile_loans(settings, state, self.contract, "run")
        self.assertFalse(schedule_date_drift["ok"])
        self.assertIn("schedule_due_date", {row["kind"] for row in schedule_date_drift["mismatches"]})
        target_loan["repaymentSchedule"]["periods"][0]["dueDate"] = [2026, 6, 26]

        target_loan["repaymentSchedule"]["periods"][0]["principalDue"] = 174.99
        with (
            patch("arissto_sync.loans.FineractApi", return_value=api),
            patch("arissto_sync.loans._find_loan", return_value=target_loan),
        ):
            installment_amount_drift = reconcile_loans(settings, state, self.contract, "run")
        self.assertFalse(installment_amount_drift["ok"])
        self.assertIn(
            "schedule_principal", {row["kind"] for row in installment_amount_drift["mismatches"]}
        )
        target_loan["repaymentSchedule"]["periods"][0]["principalDue"] = 175

        target_loan["transactions"][1]["interestPortion"] = 1.8
        with (
            patch("arissto_sync.loans.FineractApi", return_value=api),
            patch("arissto_sync.loans._find_loan", return_value=target_loan),
        ):
            allocation_drift = reconcile_loans(settings, state, self.contract, "run")
        self.assertFalse(allocation_drift["ok"])
        allocation = next(
            row for row in allocation_drift["mismatches"] if row["kind"] == "transaction_allocation"
        )
        self.assertEqual(allocation["classification"], "blocking_historical_allocation_mismatch")
        target_loan["transactions"][1]["interestPortion"] = 1.9

        built["lifecycle"]["schedule_reconciliation_policy"] = "reviewed-manual-adjustment"
        target_loan["repaymentSchedule"]["periods"][0]["dueDate"] = [2026, 6, 27]
        with (
            patch("arissto_sync.loans.FineractApi", return_value=api),
            patch("arissto_sync.loans._find_loan", return_value=target_loan),
        ):
            reviewed_exception = reconcile_loans(settings, state, self.contract, "run")
        self.assertTrue(reviewed_exception["ok"])
        exception = next(
            row for row in reviewed_exception["variances"] if row["kind"] == "schedule_due_date"
        )
        self.assertEqual(exception["classification"], "reviewed_manual_adjustment_schedule_variance")
        built["lifecycle"]["schedule_reconciliation_policy"] = "exact-source-schedule"
        target_loan["repaymentSchedule"]["periods"][0]["dueDate"] = [2026, 6, 26]

        target_loan["summary"]["principalOutstanding"] = 341
        with (
            patch("arissto_sync.loans.FineractApi", return_value=api),
            patch("arissto_sync.loans._find_loan", return_value=target_loan),
        ):
            drifted = reconcile_loans(settings, state, self.contract, "run")
        self.assertTrue(drifted["ok"])
        self.assertIn("principal_balance", {row["kind"] for row in drifted["variances"]})

        built["lifecycle"]["expected"]["source_state"] = "3"
        with (
            patch("arissto_sync.loans.FineractApi", return_value=api),
            patch("arissto_sync.loans._find_loan", return_value=target_loan),
        ):
            closed_drift = reconcile_loans(settings, state, self.contract, "run")
        self.assertFalse(closed_drift["ok"])
        self.assertIn("principal_balance", {row["kind"] for row in closed_drift["mismatches"]})

    def test_product_payload_is_complete_and_target_specific(self):
        resources = self.target_resources()
        payload = build_loan_product_payload(
            self.contract, self.product("00001", "002", "C-CONSUMO MULTIDESTINOS"), resources
        )

        self.assertEqual(payload["externalId"], "ARISSTO:CRD-LINE:00001")
        self.assertEqual(payload["numberingCode"], "3C1")
        self.assertEqual(payload["idTipoLinea"], "002")
        self.assertEqual(payload["dimensions"], {
            "arisstoCreditLineId": "00001", "arisstoCreditLineTypeId": "002",
        })
        self.assertEqual(payload["principal"], "500.00")
        self.assertEqual(payload["maxPrincipal"], "3300.00")
        self.assertEqual(payload["transactionProcessingStrategyCode"],
                         "credesal-accrued-interest-first-strategy")
        self.assertEqual(payload["charges"], [{"id": 8}])
        self.assertEqual(payload["paymentChannelToFundSourceMappings"][0]["paymentTypeId"], 9)
        self.assertTrue(payload["allowVariableInstallments"])
        self.assertEqual(payload["minimumGap"], 1)
        self.assertEqual(payload["maximumGap"], 366)
        for parameter in ACCOUNTING_RESPONSE_KEYS:
            self.assertIsInstance(payload[parameter], int)

        microcredit = build_loan_product_payload(
            self.contract,
            self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO"),
            resources,
        )
        self.assertEqual(microcredit["maxInterestRatePerPeriod"], "30.00")
        self.assertEqual(microcredit["numberingCode"], "3M1")

    def test_missing_product_numbering_code_is_a_backfillable_update(self):
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target"), source=SimpleNamespace())
        source_product = self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO")
        payload = build_loan_product_payload(self.contract, source_product, self.target_resources())
        existing = self.api_product(payload)
        existing["numberingCode"] = None
        target = {"resources": self.target_resources(), "products": {"00010": existing}, "crosswalks": {}}
        with patch("arissto_sync.loans.source_fingerprint", return_value="source"):
            plan = compose_loan_plan(
                settings, self.contract, [self.loan(2068, "00010")], [source_product], target
            )
        self.assertTrue(plan["applicable"])
        self.assertEqual(plan["actions"][0]["action"], "update-product")

    def test_scoped_plan_emits_only_required_product_before_dependent_loan(self):
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target"), source=SimpleNamespace())
        source_product = self.product("00001", "002", "C-CONSUMO MULTIDESTINOS")
        target = {"resources": self.target_resources(), "products": {"00001": None}, "crosswalks": {}}
        with patch("arissto_sync.loans.source_fingerprint", return_value="source"):
            plan = compose_loan_plan(
                settings, self.contract, [self.loan(24, "00001")], [source_product], target,
                source_keys=["24"],
            )

        self.assertTrue(plan["applicable"])
        self.assertEqual([row["source_key"] for row in plan["actions"]], ["product:00001", "loan:24"])
        self.assertEqual(plan["actions"][0]["action"], "create-product")
        self.assertEqual(plan["actions"][1]["action"], "create-loan")
        self.assertEqual(plan["actions"][1]["depends_on"], ["product:00001"])
        self.assertEqual(plan["scope"]["required_product_lines"], ["00001"])

    def test_consolidation_plan_depends_on_every_predecessor(self):
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target"), source=SimpleNamespace())
        successor, lifecycle, target, payload = self.lifecycle_fixture()
        source_product = self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO")
        target.update({"products": {"00010": self.api_product(payload)}, "crosswalks": {}, "loans": {}})
        lifecycle["refinance_incoming"] = [
            {
                "old_credit_id": 1, "new_credit_id": 2068,
                "payoff_movement_id": "91", "payoff_amount": "42.00",
                "payoff_principal": "40.00", "payoff_interest": "2.00",
                "payoff_fee": "0.00", "payoff_penalty": "0.00",
                "payoff_date": "2026-06-11", "disbursement_movement_id": "100",
            },
            {
                "old_credit_id": 2, "new_credit_id": 2068,
                "payoff_movement_id": "92", "payoff_amount": "30.50",
                "payoff_principal": "30.00", "payoff_interest": "0.50",
                "payoff_fee": "0.00", "payoff_penalty": "0.00",
                "payoff_date": "2026-06-11", "disbursement_movement_id": "100",
            },
        ]

        with patch("arissto_sync.loans.source_fingerprint", return_value="source"):
            plan = compose_loan_plan(
                settings,
                self.contract,
                [self.loan(1, "00010"), self.loan(2, "00010"), successor],
                [source_product],
                target,
                source_lifecycles={2068: lifecycle},
            )

        actions = {row["source_key"]: row for row in plan["actions"]}
        self.assertEqual(
            actions["loan:2068"]["depends_on"],
            ["product:00010", "loan:1", "loan:2"],
        )

    def test_build_plan_inspects_only_the_selected_loans(self):
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target", pg_url="pg"), source=SimpleNamespace())
        inspection = {
            "source_blockers": [], "target_blockers": [],
            "schema_signature": "source-schema", "target_schema_signature": "target-schema",
        }
        source_product = self.product("00001", "002", "C-CONSUMO MULTIDESTINOS")
        target = {"resources": self.target_resources(), "products": {"00001": None}, "crosswalks": {}}
        state = MagicMock()
        state.save_plan.return_value = "plan-id"
        with (
            patch("arissto_sync.loans.inspect_loans", side_effect=[inspection, inspection]) as inspect,
            patch("arissto_sync.loans.extract_loan_plan_rows", return_value=(
                [self.loan(24, "00001"), self.loan(25, "00001")], [source_product],
            )),
            patch("arissto_sync.loans.extract_loan_lifecycle_rows", return_value={}),
            patch("arissto_sync.loans.resolve_loan_product_target", return_value=target),
            patch("arissto_sync.loans.source_fingerprint", return_value="source"),
        ):
            plan_id, plan = build_loan_plan(settings, state, self.contract, ["24", "25"])

        self.assertEqual(plan_id, "plan-id")
        self.assertEqual(
            [call.kwargs["source_key"] for call in inspect.call_args_list],
            [24, 25],
        )
        self.assertEqual(plan["scope"]["required_product_lines"], ["00001"])

    def test_full_plan_emits_both_products_before_all_loans(self):
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target"), source=SimpleNamespace())
        products = [
            self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO"),
            self.product("00001", "002", "C-CONSUMO MULTIDESTINOS"),
        ]
        target = {"resources": self.target_resources(),
                  "products": {"00001": None, "00010": None}, "crosswalks": {}}
        with patch("arissto_sync.loans.source_fingerprint", return_value="source"):
            plan = compose_loan_plan(
                settings, self.contract, [self.loan(2068, "00010"), self.loan(24, "00001")], products, target
            )

        keys = [row["source_key"] for row in plan["actions"]]
        self.assertEqual(keys[:2], ["product:00001", "product:00010"])
        self.assertEqual(set(keys[2:]), {"loan:24", "loan:2068"})
        actions = {row["source_key"]: row for row in plan["actions"]}
        self.assertEqual(actions["loan:24"]["depends_on"], ["product:00001"])
        self.assertEqual(actions["loan:2068"]["depends_on"], ["product:00010"])

    def test_full_lifecycle_extraction_batches_sql_server_parameters(self):
        settings = SimpleNamespace(source=SimpleNamespace())
        connection = MagicMock()
        connection.__enter__.return_value = object()
        loans = [self.loan(loan_id, "00010") for loan_id in range(1, 902)]
        with (
            patch("arissto_sync.loans.source_connection", return_value=connection),
            patch("arissto_sync.loans.select_rows", return_value=[]) as select,
        ):
            result = extract_loan_lifecycle_rows(settings, self.contract, loans)

        self.assertEqual(len(result), 901)
        self.assertEqual(select.call_count, 10)
        parameter_counts = [len(call.args[2]) for call in select.call_args_list]
        self.assertEqual(parameter_counts, [900, 900, 900, 900, 1800, 1, 1, 1, 1, 2])
        self.assertLessEqual(max(parameter_counts), 2100)

    def test_exact_existing_product_is_unchanged_and_missing_crosswalk_is_repairable(self):
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target"), source=SimpleNamespace())
        source_product = self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO")
        payload = build_loan_product_payload(self.contract, source_product, self.target_resources())
        existing = self.api_product(payload)
        self.assertEqual(loan_product_conflicts(payload, existing), [])
        target = {"resources": self.target_resources(), "products": {"00010": existing}, "crosswalks": {}}
        with patch("arissto_sync.loans.source_fingerprint", return_value="source"):
            plan = compose_loan_plan(
                settings, self.contract, [self.loan(2068, "00010")], [source_product], target
            )
        product_action = plan["actions"][0]
        self.assertEqual(product_action["action"], "unchanged-product")
        self.assertTrue(product_action["crosswalk"]["repair_after_product_resolution"])

    def test_api_only_attribute_override_fields_do_not_create_false_product_drift(self):
        source_product = self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO")
        payload = build_loan_product_payload(self.contract, source_product, self.target_resources())
        existing = self.api_product(payload)
        existing["allowAttributeOverrides"] = {
            **payload["allowAttributeOverrides"],
            "isNew": True,
        }
        self.assertEqual(loan_product_conflicts(payload, existing), [])

    def test_existing_external_id_with_contract_drift_blocks_plan(self):
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target"), source=SimpleNamespace())
        source_product = self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO")
        payload = build_loan_product_payload(self.contract, source_product, self.target_resources())
        existing = self.api_product(payload)
        existing["transactionProcessingStrategyCode"] = "mifos-standard-strategy"
        target = {"resources": self.target_resources(), "products": {"00010": existing}, "crosswalks": {}}
        with patch("arissto_sync.loans.source_fingerprint", return_value="source"):
            plan = compose_loan_plan(
                settings, self.contract, [self.loan(2068, "00010")], [source_product], target
            )
        self.assertFalse(plan["applicable"])
        self.assertEqual(plan["actions"][0]["action"], "conflict-product")
        self.assertEqual(plan["actions"][0]["reason"], "external_id_product_contract_differs")
        self.assertEqual(plan["actions"][1]["depends_on"], ["product:00010"])

    def test_historical_rate_envelope_can_widen_existing_migration_product(self):
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target"), source=SimpleNamespace())
        source_product = self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO")
        payload = build_loan_product_payload(self.contract, source_product, self.target_resources())
        existing = self.api_product(payload)
        existing["maxInterestRatePerPeriod"] = 20
        target = {
            "resources": self.target_resources(), "products": {"00010": existing}, "crosswalks": {},
        }
        with patch("arissto_sync.loans.source_fingerprint", return_value="source"):
            plan = compose_loan_plan(
                settings, self.contract, [self.loan(2068, "00010")], [source_product], target
            )
        self.assertTrue(plan["applicable"])
        self.assertEqual(plan["actions"][0]["action"], "update-product")
        self.assertEqual(plan["actions"][0]["payload"]["maxInterestRatePerPeriod"], "30.00")

    def test_crosswalk_without_exact_external_id_product_blocks_plan(self):
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target"), source=SimpleNamespace())
        source_product = self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO")
        target = {
            "resources": self.target_resources(),
            "products": {"00010": None},
            "crosswalks": {"00010": {
                "source_key": "00010", "line_id": "00010", "company_id": "001",
                "loan_product_id": 90, "source_hash": "old", "contract_hash": "old",
            }},
        }
        with patch("arissto_sync.loans.source_fingerprint", return_value="source"):
            plan = compose_loan_plan(
                settings, self.contract, [self.loan(2068, "00010")], [source_product], target
            )
        self.assertFalse(plan["applicable"])
        self.assertEqual(plan["actions"][0]["action"], "conflict-product")
        self.assertEqual(
            plan["actions"][0]["reason"],
            "crosswalk_points_to_missing_external_id_product",
        )

    def test_product_apply_recovers_exact_external_id_without_duplicate_create(self):
        source_product = self.product("00010", "001", "M-MICROCREDITO MULTIDESTINO")
        payload = build_loan_product_payload(self.contract, source_product, self.target_resources())
        existing = self.api_product(payload, 90)
        action = {"action": "create-product", "external_id": payload["externalId"], "payload": payload}
        api = MagicMock()
        with patch("arissto_sync.loans._find_loan_product", return_value=existing):
            product_id, recovered = _resolve_or_create_loan_product(api, action, None)
        self.assertEqual(product_id, 90)
        self.assertTrue(recovered)
        api.request.assert_not_called()

    def test_product_apply_creates_with_deterministic_key_then_resolves_exact_identity(self):
        source_product = self.product("00001", "002", "C-CONSUMO MULTIDESTINOS")
        payload = build_loan_product_payload(self.contract, source_product, self.target_resources())
        existing = self.api_product(payload, 91)
        action = {"action": "create-product", "external_id": payload["externalId"], "payload": payload}
        api = MagicMock()
        api.request.return_value = {"resourceId": 91}
        with patch("arissto_sync.loans._find_loan_product", side_effect=[None, existing]):
            product_id, recovered = _resolve_or_create_loan_product(api, action, None)
        self.assertEqual(product_id, 91)
        self.assertFalse(recovered)
        api.request.assert_called_once_with(
            "POST", "loanproducts", payload, idempotency_key="ARISSTO:CRD-LINE:00001"
        )

    def test_failed_product_blocks_dependent_loan_without_attempt(self):
        product = {
            "source_key": "product:00001", "entity_type": "product", "entity_source_key": "00001",
            "source_company_id": "001", "action": "create-product", "depends_on": [],
            "source_hash": "product-hash", "external_id": "ARISSTO:CRD-LINE:00001", "payload": {},
            "crosswalk": {"repair_after_product_resolution": True}, "target_id": None,
        }
        loan = {
            "source_key": "loan:24", "entity_type": "loan", "entity_source_key": "24",
            "action": "create-loan", "depends_on": ["product:00001"],
            "product_action_key": "product:00001", "source_hash": "loan-hash", "target_id": None,
        }
        plan = {"id": "plan", "document": {"actions": [product, loan]}}
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target"))
        state = MagicMock()
        state.start_run.return_value = "run"
        with (
            patch("arissto_sync.loans._loan_apply_guard", return_value=(
                plan, {"products": {"00001": None}, "crosswalks": {}},
            )),
            patch("arissto_sync.loans.FineractApi"),
            patch("arissto_sync.loans._resolve_or_create_loan_product", side_effect=RuntimeError("failed")),
            patch("arissto_sync.loans._upsert_loan_product_crosswalk") as upsert,
        ):
            _, counts = apply_loan_plan(settings, state, self.contract, "plan")
        self.assertEqual(counts, {"products_failed": 1, "loans_blocked": 1})
        upsert.assert_not_called()
        statuses = {call.args[1]: call.args[4] for call in state.record_item.call_args_list}
        self.assertEqual(statuses, {"product:00001": "failed", "loan:24": "blocked"})

    def test_legacy_loan_action_without_frozen_lifecycle_fails_closed(self):
        product = {
            "source_key": "product:00001", "entity_type": "product", "entity_source_key": "00001",
            "source_company_id": "001", "action": "create-product", "depends_on": [],
            "source_hash": "product-hash", "external_id": "ARISSTO:CRD-LINE:00001", "payload": {},
            "crosswalk": {"repair_after_product_resolution": True}, "target_id": None,
        }
        loan = {
            "source_key": "loan:24", "entity_type": "loan", "entity_source_key": "24",
            "action": "create-loan", "depends_on": ["product:00001"],
            "product_action_key": "product:00001", "source_hash": "loan-hash", "target_id": None,
        }
        plan = {"id": "plan", "document": {"actions": [product, loan]}}
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target"))
        state = MagicMock()
        state.start_run.return_value = "run"
        with (
            patch("arissto_sync.loans._loan_apply_guard", return_value=(
                plan, {"products": {"00001": None}, "crosswalks": {}},
            )),
            patch("arissto_sync.loans.FineractApi"),
            patch("arissto_sync.loans._resolve_or_create_loan_product", return_value=(91, False)),
            patch("arissto_sync.loans._upsert_loan_product_crosswalk") as upsert,
        ):
            _, counts = apply_loan_plan(settings, state, self.contract, "plan")
        upsert.assert_called_once_with(settings, self.contract, product, 91)
        self.assertEqual(counts, {"succeeded": 1, "loans_failed": 1})
        statuses = {call.args[1]: call.args[4] for call in state.record_item.call_args_list}
        self.assertEqual(statuses, {"product:00001": "succeeded", "loan:24": "failed"})

    def test_product_retry_selection_includes_its_dependent_loans(self):
        actions = [
            {"source_key": "product:00001", "entity_type": "product", "depends_on": []},
            {"source_key": "product:00010", "entity_type": "product", "depends_on": []},
            {"source_key": "loan:24", "entity_type": "loan", "depends_on": ["product:00001"]},
            {"source_key": "loan:2068", "entity_type": "loan", "depends_on": ["product:00010"]},
        ]
        selected = _selected_loan_actions(actions, {"product:00001"})
        self.assertEqual([action["source_key"] for action in selected], ["product:00001", "loan:24"])

    def test_failed_loan_retry_does_not_expand_to_product_siblings(self):
        actions = [
            {"source_key": "product:00001", "entity_type": "product", "depends_on": []},
            {"source_key": "loan:24", "entity_type": "loan", "depends_on": ["product:00001"]},
            {"source_key": "loan:25", "entity_type": "loan", "depends_on": ["product:00001"]},
        ]
        selected = _selected_loan_actions(actions, {"loan:24"})
        self.assertEqual(
            [action["source_key"] for action in selected], ["product:00001", "loan:24"]
        )

    def test_retry_recovers_failed_and_unjournaled_crash_actions(self):
        actions = [
            {"source_key": "product:00001"},
            {"source_key": "product:00010"},
            {"source_key": "loan:24"},
            {"source_key": "loan:2068"},
        ]
        items = [
            {"source_key": "product:00001", "status": "succeeded"},
            {"source_key": "product:00010", "status": "failed"},
            {"source_key": "loan:24", "status": "deferred"},
        ]
        self.assertEqual(loan_retry_keys(actions, items), {"product:00010", "loan:2068"})

    def test_retry_includes_only_blocked_descendants_of_failures(self):
        actions = [
            {"source_key": "product:00001", "depends_on": []},
            {"source_key": "loan:1", "depends_on": ["product:00001"]},
            {"source_key": "loan:2", "depends_on": ["loan:1", "product:00001"]},
            {"source_key": "loan:3", "depends_on": ["product:00001"]},
        ]
        items = [
            {"source_key": "product:00001", "status": "succeeded"},
            {"source_key": "loan:1", "status": "failed"},
            {"source_key": "loan:2", "status": "blocked"},
            {"source_key": "loan:3", "status": "blocked"},
        ]
        self.assertEqual(loan_retry_keys(actions, items), {"loan:1", "loan:2"})

    def test_namespaced_plan_keys_prevent_product_and_loan_collision(self):
        self.assertEqual(product_action_key("00001"), "product:00001")
        self.assertEqual(loan_action_key(1), "loan:1")
        self.assertNotEqual(product_action_key("00001"), loan_action_key(1))
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            plan_id = state.save_plan("target", "loans", "source", "contract", {"actions": []})
            run_id = state.start_run({
                "id": plan_id,
                "target_fingerprint": "target",
                "block": "loans",
            })
            state.record_item(run_id, "product:00001", "create-product", "product-hash", "succeeded")
            state.record_item(run_id, "loan:1", "create-loan", "loan-hash", "succeeded")
            self.assertEqual(
                {item["source_key"] for item in state.run_items(run_id)},
                {"product:00001", "loan:1"},
            )

    def test_reversal_pairing_consumes_exact_signatures_in_lifo_order(self):
        def row(loan, movement, transaction, amount, *, reversed="", system=4, day=1, principal=None):
            return {
                "ID_CREDITO": loan, "ID_MOVIMIENTO_CARTERA": movement, "CODIGO_SISTEMA": system,
                "ID_TRANSACCION": transaction, "REVERSION": reversed,
                "FECHA_OPERACION": f"2026-01-{day:02d}", "MONTO": amount,
                "MONTO_CAPITAL": amount if principal is None else principal,
            }

        rows = [
            row(1, "0001", "00002", "100", day=1),
            row(1, "0002", "00030", "100", day=2),
            row(1, "0003", "00001", "10", reversed="1", day=3),
            row(1, "0004", "00001", "10", reversed="1", day=4),
            row(1, "0005", "00004", "10", day=5),
            row(1, "0006", "00004", "10", day=6),
            row(2, "0007", "00004", "7", day=7),
        ]
        result = pair_loan_reversals(rows)

        self.assertEqual(result["pair_count"], 3)
        self.assertEqual(result["repayment_pair_count"], 2)
        self.assertEqual(result["disbursement_pair_count"], 1)
        repayment_pairs = [item for item in result["pairs"] if item["kind"] == "repayment"]
        self.assertEqual(
            [(item["original_movement_id"], item["reversal_movement_id"]) for item in repayment_pairs],
            [("0004", "0005"), ("0003", "0006")],
        )
        self.assertEqual(result["lifo_disambiguated_count"], 1)
        self.assertEqual(result["duplicate_original_count"], 0)
        self.assertEqual(result["unpaired_reversed_original_count"], 0)
        self.assertEqual(result["issues"], [
            {"code": "orphan_repayment_reversal", "loan_id": 2, "reversal_movement_id": "0007"}
        ])

    def test_classifier_recognizes_only_complete_zero_cash_component_reallocation(self):
        def row(movement, transaction, amount, principal, interest, *, reversed="", day=1, close="1430"):
            return {
                "ID_CREDITO": 83, "ID_MOVIMIENTO_CARTERA": movement, "CODIGO_SISTEMA": 4,
                "ID_TRANSACCION": transaction, "REVERSION": reversed,
                "FECHA_OPERACION": f"2024-09-{day:02d}", "MONTO": amount,
                "MONTO_CAPITAL": principal, "MONTO_INTERES": interest,
                "ID_CIERRE_DIARIO": close, "ID_USUARIO": "00001", "ID_USR_CREO": "00001",
                "ID_CAJA": None, "ID_PARTIDA": None, "ID_TIPO_PAGO": 9,
            }

        rows = [
            row("5020", "00001", "10.00", "7.85", "2.15", reversed="1", day=1),
            row("5021", "00001", "10.00", "10.00", "0.00", reversed="1", day=1),
            row("5026", "00004", "10.00", "7.85", "2.15", day=1),
            row("5027", "00004", "10.00", "10.00", "0.00", day=1),
            row("5037", "00004", "10.00", "7.85", "2.15", day=2, close="1431"),
            row("5038", "00004", "10.00", "10.00", "0.00", day=2, close="1431"),
            row("5039", "00001", "20.00", "20.00", "0.00", day=2, close="1431"),
        ]
        pairing = pair_loan_reversals(rows)
        result = classify_source_exact_component_reallocations(rows, pairing)

        self.assertEqual(result["movement_ids"], {"5037", "5038", "5039"})
        self.assertEqual(result["classifications"], [{
            "loan_id": 83, "source_reversal_movement_ids": ["5037", "5038"],
            "source_repayment_movement_id": "5039", "date": "2024-09-02",
            "principal": "2.15", "interest": "-2.15", "source_close_id": "1431",
            "source_actor_id": "00001", "source_payment_type_id": "9",
        }])

        rows[-1]["MONTO"] = "19.99"
        self.assertEqual(
            classify_source_exact_component_reallocations(rows, pair_loan_reversals(rows))["classifications"], []
        )

    def test_source_only_canary_reports_gate_five_readiness(self):
        complete_schema = [
            [{"column_name": column, "data_type": "varchar"} for column in sorted(required)]
            for required in REQUIRED_COLUMNS.values()
        ]
        results = complete_schema + [
            [{"loan_count": 1, "null_loan_keys": 0, "distinct_loan_keys": 1,
              "blank_account_numbers": 0, "distinct_account_numbers": 1}],
            [{"company_id": "001", "line_id": "00010", "loan_count": 1}],
            [{"loan_state": "1", "loan_type": "1", "loan_count": 1}],
            [{"loan_count": 1, "missing_application_count": 0}],
            [{"loan_count": 1, "loans_with_schedule": 1, "loans_without_schedule": 0,
              "installment_count": 12, "null_due_dates": 0, "first_due_date_mismatches": 0}],
            [{"movement_count": 2, "blank_movement_keys": 0, "distinct_movement_keys": 2,
              "missing_loan_keys": 0, "loans_with_movements": 1}],
            [
                {"system_code": "4", "transaction_code": "00002", "transaction_name": "DESEMBOLSO",
                 "reversed": 0, "movement_count": 1},
                {"system_code": "14", "transaction_code": "00011", "transaction_name": "CD-PAGO CREDITO",
                 "reversed": 0, "movement_count": 1},
            ],
            [{"movement_count": 2, "null_fecha_operacion": 0, "null_fecha_valor": 0,
              "null_fecha_pago": 0, "null_dt_movimiento": 0, "null_dt_creo": 0,
              "movements_without_timestamp": 0}],
            [{"movement_count": 2, "savings_component_count": 0, "contribution_component_count": 0,
              "overlapping_other_and_insurance_count": 0, "component_residual_count": 0}],
            [{"link_count": 0, "predecessor_count": 0, "successor_count": 0,
              "active_link_count": 0, "reversed_link_count": 0,
              "multi_predecessor_successor_count": 0,
              "ambiguous_successor_predecessor_count": 0}],
            [{"tagged_schedule_rows": 6603, "restructure_snapshot_count": 174,
              "linked_loan_count": 0, "archival_unlinked_rows": 6603,
              "linked_schedule_rows": 0}],
            [],
        ]
        connection = MagicMock()
        connection.__enter__.return_value = object()
        source = SimpleNamespace(server="source", port=1433, database="arissto")
        with (
            patch("arissto_sync.loans.source_connection", return_value=connection),
            patch("arissto_sync.loans.select_rows", side_effect=results),
            patch("arissto_sync.loans.source_fingerprint", return_value="source-fingerprint"),
        ):
            report = inspect_loans(source, self.contract, "123")

        self.assertTrue(report["read_ready"])
        self.assertTrue(report["ready"])
        self.assertEqual(report["scope"], {"kind": "loan", "source_key": 123})
        self.assertEqual(report["source_blockers"], [])
        self.assertNotIn("implementation_gate:native_schedule_proof", report["blockers"])
        self.assertNotIn("implementation_gate:native_reversal_pairing_proof", report["blockers"])
        self.assertEqual(report["source"]["reversal_pairing"]["movement_order"],
                         ["FECHA_OPERACION", "ID_MOVIMIENTO_CARTERA"])
        self.assertEqual(report["source"]["transactions"][1]["contract_role"], "mobile-collection-repayment")
        self.assertEqual(
            report["source"]["historical_schedule_exception"]["reviewed_source_loan_ids"],
            [24, 435, 945],
        )
        self.assertFalse(report["source"]["historical_schedule_exception"]["scope_applies"])
        self.assertFalse(report["source"]["historical_schedule_exception"]["blocking"])
        self.assertEqual(
            report["source"]["refinance_graph"]["supported_native_path"],
            "fineract_refinancing_settlement_transfers",
        )
        self.assertEqual(
            report["source"]["refinance_graph"]["multi_predecessor_policy"],
            "same_client_atomic_multi_settlement_cross_client_quarantine",
        )
        self.assertEqual(report["target"], {"postgres_inspection": "not-requested"})
        self.assertFalse(report["target_ready"])

    def test_unmapped_transaction_is_a_source_blocker(self):
        complete_schema = [
            [{"column_name": column, "data_type": "varchar"} for column in sorted(required)]
            for required in REQUIRED_COLUMNS.values()
        ]
        results = complete_schema + [
            [{"loan_count": 1, "null_loan_keys": 0, "distinct_loan_keys": 1,
              "blank_account_numbers": 0, "distinct_account_numbers": 1}],
            [{"company_id": "001", "line_id": "00010", "loan_count": 1}],
            [],
            [{"loan_count": 1, "missing_application_count": 0}],
            [{"loan_count": 1, "loans_with_schedule": 0, "loans_without_schedule": 1,
              "installment_count": 0, "null_due_dates": 0, "first_due_date_mismatches": 0}],
            [{"movement_count": 1, "blank_movement_keys": 0, "distinct_movement_keys": 1,
              "missing_loan_keys": 0, "loans_with_movements": 1}],
            [{"system_code": "9", "transaction_code": "99999", "transaction_name": "UNKNOWN",
              "reversed": 0, "movement_count": 1}],
            [{"movement_count": 1, "movements_without_timestamp": 0}],
            [{"movement_count": 1, "savings_component_count": 0, "contribution_component_count": 0,
              "overlapping_other_and_insurance_count": 0, "component_residual_count": 0}],
            [{"link_count": 0, "predecessor_count": 0, "successor_count": 0,
              "active_link_count": 0, "reversed_link_count": 0,
              "multi_predecessor_successor_count": 0,
              "ambiguous_successor_predecessor_count": 0}],
            [{"tagged_schedule_rows": 0, "restructure_snapshot_count": 0,
              "linked_loan_count": 0, "archival_unlinked_rows": 0,
              "linked_schedule_rows": 0}],
            [],
        ]
        connection = MagicMock()
        connection.__enter__.return_value = object()
        source = SimpleNamespace(server="source", port=1433, database="arissto")
        with (
            patch("arissto_sync.loans.source_connection", return_value=connection),
            patch("arissto_sync.loans.select_rows", side_effect=results),
            patch("arissto_sync.loans.source_fingerprint", return_value="source-fingerprint"),
        ):
            report = inspect_loans(source, self.contract, "123")
        self.assertFalse(report["read_ready"])
        self.assertIn("unmapped_loan_transaction:9:99999", report["source_blockers"])

    def test_compact_reconciliation_report_groups_findings_and_preserves_identities(self):
        result = {
            "run_id": "run-1",
            "ok": False,
            "counts": {"loans": 3},
            "mismatches": [
                {"source_key": "loan:1254", "kind": "transaction_allocation",
                 "classification": "blocking_historical_allocation_mismatch", "movement": "1"},
                {"source_key": "loan:1254", "kind": "transaction_allocation",
                 "classification": "blocking_historical_allocation_mismatch", "movement": "2"},
                {"source_key": "loan:1315", "kind": "transaction_allocation",
                 "classification": "blocking_historical_allocation_mismatch", "movement": "3"},
                {"source_key": "loan:1934", "kind": "schedule_interest"},
            ],
            "variances": [
                {"source_key": "loan:1254", "kind": "native_schedule_component_variance"},
            ],
            "failed_or_quarantined": [
                {"source_key": "loan:2120", "status": "failed", "error_code": "invalid-variation"},
            ],
            "adjustments": [],
        }

        report = compact_loan_reconciliation_report(result, sample_limit=1)

        self.assertEqual(report["blocking_mismatch_count"], 4)
        self.assertEqual(report["blocking_affected_source_keys"], ["loan:1254", "loan:1315", "loan:1934"])
        allocation = next(row for row in report["mismatch_groups"]
                          if row["kind"] == "transaction_allocation")
        self.assertEqual(allocation["count"], 3)
        self.assertEqual(allocation["affected_source_keys"], ["loan:1254", "loan:1315"])
        self.assertEqual(len(allocation["samples"]), 1)
        self.assertEqual(report["variance_count"], 1)
        self.assertEqual(report["failed_or_quarantined_count"], 1)

        with self.assertRaisesRegex(ValueError, "sample_limit"):
            compact_loan_reconciliation_report(result, sample_limit=-1)


if __name__ == "__main__":
    unittest.main()
