import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from arissto_sync.savings import (
    ACCOUNT_SOURCE,
    HISTORY_SOURCE,
    MOVEMENT_SOURCE,
    SavingsContract,
    SavingsDataIssue,
    _source_requirements,
    inspect_savings,
)
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.savings_engine import (
    _dpf_product_payload,
    _can_repair_existing_drift,
    _planning_drift_reasons,
    _reconcile_record,
    _next_replacement_reference,
    _replacement_reference,
    _transaction_id,
    _vista_product_payload,
    _reverse_unmapped_dpf_interest,
    _reverse_unmapped_dpf_transfers,
    _reverse_unmapped_vista_interest_tax,
)
from arissto_sync.savings_lifecycle_proof import VistaCanary


CONFIG = Path(__file__).resolve().parents[1] / "config" / "savings_deposits.json"


class SavingsContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = SavingsContract.load(CONFIG)

    def movement_row(self, **changes):
        value = {
            "ID_EMPRESA": "001",
            "ID_SUCURSAL": "001",
            "ID_AHO_MOVIMIENTO": 9001,
            "ID_MOVIMIENTO_AHORRO": "42",
            "TIPO_MOVIMIENTO": "1",
            "MONTO": "25.50",
            "FECHA_OPERACION": datetime(2026, 8, 24, 10, 30),
            "DT_MOVIMIENTO": None,
            "DT_CREO": None,
            "REVERSION": "0",
            "SALDO_ANTERIOR": "100.00",
            "SALDO_FINAL": "125.50",
        }
        value.update(changes)
        return value

    def test_planned_contract_loads_with_reviewed_cutoff(self):
        self.assertTrue(self.contract.cutoff_ready)
        self.assertEqual(self.contract.account_type("001")["target"], "savings")
        self.assertEqual(self.contract.account_type("003")["target"], "fixed-deposit")
        self.assertEqual(self.contract.account_state("0"), "CLOSED")
        self.assertEqual(self.contract.history_role("2"), "CATCH_UP_ACCRUAL_EVIDENCE")
        self.assertEqual(self.contract.raw["interest_basis"]["target_api_parameter"], "interestCalculationDaysInYearType")
        self.assertEqual(self.contract.raw["interest_basis"]["target_enum_value"], 1)
        self.assertTrue(self.contract.raw["interest_basis"]["require_product_account_match"])
        self.assertEqual(self.contract.raw["interest_schedule"]["target_posting_enum_value"], 9)
        self.assertEqual(self.contract.raw["interest_schedule"]["target_compounding_enum_value"], 9)
        self.assertEqual(self.contract.raw["interest_schedule"]["anchor_source_column"], "FECHA_APERTURA")
        self.assertEqual(self.contract.raw["interest_schedule"]["short_month_rule"], "last_day_then_restore_anchor")
        self.assertEqual(self.contract.raw["cutoff"]["selected_exact_field"], "INTERESES_PROVISIONADOS")
        self.assertEqual(self.contract.raw["cutoff"]["selected_accounting_field"], "INTERESES_PROVISIONADOS")
        self.assertNotIn("cutoff_field_selection", self.contract.raw["blockers"])
        self.assertEqual(self.contract.raw["historical_interest_posting"]["target_transaction_type_enum"], 3)
        self.assertEqual(
            self.contract.raw["historical_interest_posting"]["target_api_command"], "explicitInterestPosting"
        )
        self.assertEqual(
            self.contract.raw["historical_interest_posting"]["future_interest_policy"],
            "native_actual_actual_calculator",
        )
        self.assertEqual(self.contract.raw["historical_isr"]["target_transaction_type_enum"], 18)
        self.assertEqual(self.contract.raw["historical_isr"]["posting_account"], "linked_vista")
        self.assertEqual(self.contract.raw["target_shared_gl"]["savingsReferenceAccountId"]["gl_code"], "1110040202")
        self.assertNotIn("target_shared_gl_mapping", self.contract.raw["blockers"])
        self.assertNotIn("native_actual_actual_interest_basis", self.contract.raw["blockers"])
        self.assertNotIn("native_opening_day_interest_schedule", self.contract.raw["blockers"])
        self.assertNotIn("deterministic_plan_apply_reconcile_and_full_population", self.contract.raw["blockers"])

    def test_product_payloads_include_approved_numbering_codes(self):
        gl = {
            key: index
            for index, key in enumerate((
                "savingsReferenceAccountId", "savingsControlAccountId", "transfersInSuspenseAccountId",
                "interestOnSavingsAccountId", "interestPayableAccountId", "incomeFromFeeAccountId",
                "incomeFromPenaltyAccountId", "feesReceivableAccountId", "penaltiesReceivableAccountId",
            ), start=1)
        }
        vista = SimpleNamespace(line_id="00001")
        dpf = SimpleNamespace(line_id="00010", principal=Decimal("1000.00"))
        self.assertEqual(_vista_product_payload(vista, gl, Decimal("3.00"))["numberingCode"], "4V1")
        self.assertEqual(
            _dpf_product_payload(dpf, gl, 360, 360, Decimal("7.25"), "06")["numberingCode"],
            "5D8",
        )

    def test_canonical_account_identity_is_stable_and_parseable(self):
        row = {"ID_EMPRESA": "001", "ID_SUCURSAL": "002", "ID_CUENTA_AHORRO": "A|10%"}
        key = self.contract.source_key(ACCOUNT_SOURCE, row)
        self.assertEqual(key, "AHO_CUENTA_AHORRO|001|002|A%7C10%25")
        self.assertEqual(self.contract.parse_account_source_key(key), ("001", "002", "A|10%"))

    def test_unmapped_native_interest_tax_is_undone_and_verified(self):
        select_connection = MagicMock()
        select_connection.execute.return_value.fetchall.return_value = [(8035,)]
        verify_connection = MagicMock()
        verify_connection.execute.return_value.fetchone.return_value = (True,)
        connections = iter((select_connection, verify_connection))

        @contextmanager
        def connection(_url):
            yield next(connections)

        settings = SimpleNamespace(target=SimpleNamespace(pg_url="postgresql://local"))
        api = MagicMock()
        with patch("arissto_sync.savings_engine.postgres_connection", connection):
            reversed_ids = _reverse_unmapped_vista_interest_tax(settings, api, 43)

        self.assertEqual(reversed_ids, [8035])
        self.assertEqual(api.request.call_count, 2)
        self.assertEqual(api.request.call_args_list[0].args[:4], (
            "POST", "savingsaccounts/43/transactions/8035", {"sourceAuthoritativeCleanup": True}, {"command": "undo"}
        ))
        self.assertEqual(api.request.call_args_list[1].args[:4], (
            "POST", "savingsaccounts/43", {}, {"command": "calculateInterest"}
        ))

    def test_unmapped_dpf_interest_transfer_is_undone_and_verified(self):
        select_connection = MagicMock()
        select_connection.execute.return_value.fetchall.return_value = [(664, 36)]
        verify_connection = MagicMock()
        verify_connection.execute.return_value.fetchone.return_value = (True, 0)
        connections = iter((select_connection, verify_connection))

        @contextmanager
        def connection(_url):
            yield next(connections)

        settings = SimpleNamespace(target=SimpleNamespace(pg_url="postgresql://local"))
        api = MagicMock()
        with patch("arissto_sync.savings_engine.postgres_connection", connection):
            reversed_ids = _reverse_unmapped_dpf_interest(settings, api, [36])

        self.assertEqual(reversed_ids, [664])
        self.assertEqual(api.request.call_args.args[:4], (
            "POST", "fixeddepositaccounts/36/transactions/664",
            {"sourceAuthoritativeCleanup": True}, {"command": "undo"}
        ))

    def test_unmapped_dpf_principal_transfer_is_undone_and_verified(self):
        select_connection = MagicMock()
        select_connection.execute.return_value.fetchall.return_value = [(997, 12175, 12177, 36)]
        verify_connection = MagicMock()
        verify_connection.execute.return_value.fetchone.return_value = (True, True, True)
        connections = iter((select_connection, verify_connection))

        @contextmanager
        def connection(_url):
            yield next(connections)

        settings = SimpleNamespace(target=SimpleNamespace(pg_url="postgresql://local"))
        api = MagicMock()
        with patch("arissto_sync.savings_engine.postgres_connection", connection):
            reversed_ids = _reverse_unmapped_dpf_transfers(settings, api, [36], 35)

        self.assertEqual(reversed_ids, [997])
        self.assertEqual(api.request.call_args.args[:4], (
            "POST", "fixeddepositaccounts/36/transactions/12175",
            {"sourceAuthoritativeCleanup": True}, {"command": "undo"}
        ))

    def test_planning_blocks_contract_and_native_drift(self):
        vista = VistaCanary(
            source_key="001:001:1", company_id="001", branch_id="001", account_id="1",
            line_id="1", client_external_id="1", opening_date=datetime(2026, 1, 1).date(),
            annual_rate=Decimal("1"), ending_balance=Decimal("25.00"), source_gl_codes={}, events=(),
        )
        record = {"payload": vista}
        native = {"balance": Decimal("25.00")}
        existing = {
            "contract_hash": "old", "reversed_event_count": 0, "unmapped_interest_count": 0,
        }
        self.assertEqual(_planning_drift_reasons(record, existing, native, "current"), ["contract_hash_mismatch"])
        existing["contract_hash"] = "current"
        existing["reversed_event_count"] = 1
        self.assertEqual(
            _planning_drift_reasons(record, existing, native, "current"), ["mapped_native_transaction_reversed"]
        )
        existing["reversed_event_count"] = 0
        existing["unmapped_interest_count"] = 1
        self.assertEqual(_planning_drift_reasons(record, existing, native, "current"), ["unmapped_native_interest"])
        existing["unmapped_interest_count"] = 0
        native["balance"] = Decimal("24.00")
        self.assertEqual(_planning_drift_reasons(record, existing, native, "current"), ["native_balance_mismatch"])

    def test_planning_detects_missing_migration_interest_start(self):
        cutoff = datetime(2026, 8, 30).date()
        record = {"payload": None, "cutoff_date": cutoff}
        existing = {"contract_hash": "current", "reversed_event_count": 0, "unmapped_interest_count": 0}
        native = {"balance": Decimal("25.00"), "interest_start": None}

        self.assertEqual(
            _planning_drift_reasons(record, existing, native, "current"),
            ["migration_interest_start_mismatch"],
        )

    def test_repair_requires_unchanged_source_and_known_drift(self):
        record = {"source_hash": "same"}
        existing = {"source_hash": "same"}
        reasons = ["contract_hash_mismatch", "mapped_native_transaction_reversed"]
        self.assertTrue(_can_repair_existing_drift(record, existing, reasons))
        existing["source_hash"] = "different"
        self.assertFalse(_can_repair_existing_drift(record, existing, reasons))
        existing["source_hash"] = "same"
        self.assertFalse(_can_repair_existing_drift(record, existing, ["unknown_native_drift"]))

    def test_stale_native_transaction_uses_deterministic_repair_reference(self):
        reference = "VSTI:001:001:84:817"
        self.assertEqual(_next_replacement_reference(reference, {reference}), f"{reference}:R1")
        self.assertEqual(
            _next_replacement_reference(reference, {reference, f"{reference}:R1", f"{reference}:R2"}),
            f"{reference}:R3",
        )

    def test_retained_reference_uses_repair_generation_even_without_event_map(self):
        reference = "MIGT:001:001:0000000140:000000001798"
        connection_mock = MagicMock()
        connection_mock.execute.return_value.fetchall.return_value = [(reference,)]

        @contextmanager
        def connection(_url):
            yield connection_mock

        settings = SimpleNamespace(target=SimpleNamespace(pg_url="postgresql://local"))
        with patch("arissto_sync.savings_engine.postgres_connection", connection):
            self.assertEqual(_replacement_reference(settings, reference, None), f"{reference}:R1")

    def test_savings_transaction_response_accepts_resource_id(self):
        self.assertEqual(_transaction_id({"savingsId": 43, "resourceId": 25518}), 25518)

    def test_reconciliation_splits_hashes_and_continues_native_diagnostics(self):
        vista = VistaCanary(
            source_key="001:001:1", company_id="001", branch_id="001", account_id="1",
            line_id="1", client_external_id="1", opening_date=datetime(2026, 1, 1).date(),
            annual_rate=Decimal("1"), ending_balance=Decimal("25.00"), source_gl_codes={}, events=(),
        )
        record = {"source_hash": "current-source", "payload": vista}
        migration = {"source_hash": "old-source", "contract_hash": "old-contract"}
        contract = SimpleNamespace(contract_hash="current-contract")
        with patch("arissto_sync.savings_engine._reconcile_vista", return_value=["ending_balance"]) as diagnostic:
            reasons = _reconcile_record(SimpleNamespace(), contract, record, migration)
        self.assertEqual(reasons, ["source_hash_mismatch", "contract_hash_mismatch", "ending_balance"])
        diagnostic.assert_called_once()

    def test_dpf_reused_position_builds_native_cycle_chain_and_places_interest(self):
        account = {
            "ID_EMPRESA": "001", "ID_SUCURSAL": "001", "ID_CUENTA_AHORRO": "0000000141",
            "ID_TIPO_CUENTA_AHORRO": "003", "PLAZO": 30, "ESTADO_CUENTA": "4",
            "FECHA_APERTURA": "2026-07-26", "FECHA_VENCIMIENTO": "2026-08-25",
        }
        opening = [{"FECHA_OPERACION": "2026-04-27", "REVERSION": "0"}]
        history = [
            {"ID_EMPRESA": "001", "ID_SUCURSAL": "001", "ID_CUENTA_AHORRO": "0000000141",
             "ID_HISTORICO": "2", "TIPO_HISTORICO": "2", "FECHA_APERTURA": "2026-05-27",
             "FECHA_VENCIMIENTO": "2026-06-26"},
            {"ID_EMPRESA": "001", "ID_SUCURSAL": "001", "ID_CUENTA_AHORRO": "0000000141",
             "ID_HISTORICO": "4", "TIPO_HISTORICO": "2", "FECHA_APERTURA": "2026-06-26",
             "FECHA_VENCIMIENTO": "2026-07-26"},
            {"ID_EMPRESA": "001", "ID_SUCURSAL": "001", "ID_CUENTA_AHORRO": "0000000141",
             "ID_HISTORICO": "6", "TIPO_HISTORICO": "2", "FECHA_APERTURA": "2026-07-26",
             "FECHA_VENCIMIENTO": "2026-08-25"},
        ]
        cycles = self.contract.fixed_deposit_cycles(account, opening, history)
        self.assertEqual(len(cycles), 4)
        self.assertEqual(cycles[0]["source_opened_on"].isoformat(), "2026-04-27")
        self.assertEqual(cycles[0]["opening_inference"], "NONREVERSED_OPENING_MOVEMENT")
        self.assertTrue(cycles[-1]["is_current_cycle"])
        self.assertEqual(cycles[-1]["cycle_status"], "MATURED")
        event = {"FECHA_APERTURA": "2026-08-24"}
        self.assertIs(self.contract.fixed_deposit_history_cycle(event, cycles), cycles[-1])
        self.assertIn("AHO_HISTORICO_PLAZOS", self.contract.source_key(HISTORY_SOURCE, history[0]))

    def test_dpf_legacy_cycle_falls_back_to_first_boundary_minus_term(self):
        account = {
            "ID_EMPRESA": "001", "ID_SUCURSAL": "001", "ID_CUENTA_AHORRO": "0000000002",
            "ID_TIPO_CUENTA_AHORRO": "003", "PLAZO": 180, "ESTADO_CUENTA": "4",
            "FECHA_APERTURA": "2023-08-12", "FECHA_VENCIMIENTO": "2024-02-08",
        }
        history = [{
            "ID_EMPRESA": "001", "ID_SUCURSAL": "001", "ID_CUENTA_AHORRO": "0000000002",
            "ID_HISTORICO": "10", "TIPO_HISTORICO": "2", "FECHA_APERTURA": "2023-08-12",
            "FECHA_VENCIMIENTO": "2024-02-08",
        }]
        cycles = self.contract.fixed_deposit_cycles(account, [], history)
        self.assertEqual(cycles[0]["source_opened_on"].isoformat(), "2023-02-13")
        self.assertEqual(cycles[0]["opening_inference"], "FIRST_RENEWAL_MINUS_TERM_DAYS")
        self.assertEqual(len(cycles), 2)

    def test_movement_event_preserves_financial_fields(self):
        row = self.movement_row()
        event = self.contract.movement_event(row, " DEPOSITO   DE AHORRO ")
        self.assertEqual(event["source_key"], "AHO_MOVIMIENTOS|9001")
        self.assertEqual(event["role"], "DEPOSIT")
        self.assertEqual(event["direction"], "1")
        self.assertEqual(event["event_date"], "2026-08-24")
        self.assertEqual(event["amount"], "25.50")
        self.assertEqual(event["previous_balance"], "100.00")
        self.assertEqual(event["final_balance"], "125.50")
        self.assertFalse(event["is_reversal"])
        self.assertEqual(self.contract.source_key(MOVEMENT_SOURCE, row), event["source_key"])

    def test_direction_unknown_type_and_nonpositive_amount_are_blockers(self):
        with self.assertRaisesRegex(SavingsDataIssue, "direction_mismatch"):
            self.contract.movement_event(self.movement_row(TIPO_MOVIMIENTO="2"), "DEPOSITO DE AHORRO")
        with self.assertRaisesRegex(SavingsDataIssue, "unmapped_savings_movement"):
            self.contract.movement_event(self.movement_row(), "UNREVIEWED MOVEMENT")
        with self.assertRaisesRegex(SavingsDataIssue, "nonpositive"):
            self.contract.movement_event(self.movement_row(MONTO="0"), "DEPOSITO DE AHORRO")

    def test_record_hash_changes_with_payload_and_contract(self):
        key = "AHO_CUENTA_AHORRO|001|001|1"
        first = self.contract.hash_record("account", key, {"balance": "1.00"})
        second = self.contract.hash_record("account", key, {"balance": "2.00"})
        self.assertNotEqual(first, second)
        self.assertEqual(first, self.contract.hash_record("account", key, {"balance": "1.00"}))

    def test_contract_rejects_weakened_write_policy(self):
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["write_policy"]["native_financial_tables"] = "direct-sql"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "savings.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot weaken"):
                SavingsContract.load(path)

    def test_contract_rejects_approximate_interest_basis(self):
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["interest_basis"]["target_enum_value"] = 365
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "savings.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Actual/Actual"):
                SavingsContract.load(path)

    def test_contract_rejects_missing_movement_and_unknown_cutoff_field(self):
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["movement_roles"].pop("RETIRO DE AHORRO")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "savings.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reviewed source labels"):
                SavingsContract.load(path)

    def test_savings_support_migration_is_well_formed_and_registered(self):
        core = Path(__file__).resolve().parents[3]
        parts = core / "fineract-provider/src/main/resources/db/changelog/tenant/parts"
        migration = parts / "0288_add_arissto_savings_migration_support.xml"
        master = parts.parent / "changelog-tenant.xml"
        root = ET.parse(migration).getroot()
        tables = {
            element.attrib["tableName"]
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "createTable"
        }
        self.assertEqual(tables, {
            "credesal_savings_migration_account",
            "credesal_savings_migration_owner",
            "credesal_savings_native_event_map",
        })
        self.assertIn(migration.name, master.read_text(encoding="utf-8"))

        product_map_migration = parts / "0290_add_arissto_savings_product_map.xml"
        product_map_root = ET.parse(product_map_migration).getroot()
        product_map_tables = {
            element.attrib["tableName"]
            for element in product_map_root.iter()
            if element.tag.rsplit("}", 1)[-1] == "createTable"
        }
        self.assertEqual(product_map_tables, {"credesal_savings_product_map"})
        self.assertIn(product_map_migration.name, master.read_text(encoding="utf-8"))

        permission_migration = parts / "0292_add_explicit_savings_withhold_tax_permission.xml"
        permission_root = ET.parse(permission_migration).getroot()
        permission_values = {
            element.attrib.get("name"): element.attrib.get("value")
            for element in permission_root.iter()
            if element.tag.rsplit("}", 1)[-1] == "column"
        }
        self.assertEqual(permission_values["code"], "EXPLICITWITHHOLDTAX_SAVINGSACCOUNT")
        self.assertEqual(permission_values["entity_name"], "SAVINGSACCOUNT")
        self.assertEqual(permission_values["action_name"], "EXPLICITWITHHOLDTAX")
        self.assertIn(permission_migration.name, master.read_text(encoding="utf-8"))

        period_end_migration = parts / "0296_configure_savings_interest_period_end.xml"
        period_end_root = ET.parse(period_end_migration).getroot()
        updates = [
            element for element in period_end_root.iter()
            if element.tag.rsplit("}", 1)[-1] == "update"
        ]
        self.assertEqual([item.attrib["tableName"] for item in updates], ["c_configuration"])
        self.assertIn("savings-interest-posting-current-period-end", period_end_migration.read_text(encoding="utf-8"))
        self.assertIn(period_end_migration.name, master.read_text(encoding="utf-8"))

        interest_permission = parts / "0299_add_explicit_savings_interest_posting_permission.xml"
        interest_permission_root = ET.parse(interest_permission).getroot()
        interest_permission_values = {
            element.attrib.get("name"): element.attrib.get("value")
            for element in interest_permission_root.iter()
            if element.tag.rsplit("}", 1)[-1] == "column"
        }
        self.assertEqual(interest_permission_values["code"], "EXPLICITINTERESTPOSTING_SAVINGSACCOUNT")
        self.assertEqual(interest_permission_values["entity_name"], "SAVINGSACCOUNT")
        self.assertEqual(interest_permission_values["action_name"], "EXPLICITINTERESTPOSTING")
        self.assertIn(interest_permission.name, master.read_text(encoding="utf-8"))

        cycle_migration = parts / "0300_add_arissto_fixed_deposit_cycles.xml"
        cycle_root = ET.parse(cycle_migration).getroot()
        cycle_tables = {
            element.attrib["tableName"]
            for element in cycle_root.iter()
            if element.tag.rsplit("}", 1)[-1] == "createTable"
        }
        self.assertEqual(cycle_tables, {"credesal_savings_migration_cycle"})
        self.assertIn("migration_cycle_id", cycle_migration.read_text(encoding="utf-8"))
        self.assertIn(cycle_migration.name, master.read_text(encoding="utf-8"))

        inference_migration = parts / "0304_expand_arissto_dpf_opening_inference.xml"
        inference_root = ET.parse(inference_migration).getroot()
        modifications = [
            element for element in inference_root.iter()
            if element.tag.rsplit("}", 1)[-1] == "modifyDataType"
        ]
        self.assertEqual(len(modifications), 1)
        self.assertEqual(modifications[0].attrib["tableName"], "credesal_savings_migration_cycle")
        self.assertEqual(modifications[0].attrib["columnName"], "opening_inference")
        self.assertEqual(modifications[0].attrib["newDataType"], "VARCHAR(64)")
        self.assertIn(inference_migration.name, master.read_text(encoding="utf-8"))

    def test_inspection_is_read_only_and_reports_missing_target_configuration(self):
        requirements = _source_requirements(self.contract)
        metadata = [
            [{"column_name": column, "data_type": "varchar"} for column in sorted(columns)]
            or [{"column_name": "ID_PROVISION", "data_type": "integer"}]
            for columns in requirements.values()
        ]
        source_results = [
            *metadata,
            [{"account_type": "001", "account_state": "1", "account_count": 38, "balance": "1.00"}],
            [{"ownership_links": 158, "owned_accounts": 157, "joint_accounts": 1, "maximum_owner_count": 2,
              "joint_accounts_with_unique_primary": 1, "joint_accounts_with_ambiguous_primary": 0}],
            [{"transaction_label": "DEPOSITO DE AHORRO", "direction": "1", "reversed": 0,
              "movement_count": 1, "amount": "1.00"}],
            [{"history_type": "1", "history_count": 1, "interest_amount": "0.01",
              "tax_amount": "0.00", "linked_movement_count": 1}],
            [{"dpf_accounts": 119, "cycle_count": 405, "renewal_boundary_count": 286,
              "accounts_with_renewals": 53, "invalid_cycles": 0, "unreviewed_boundary_gaps": 0,
              "current_master_mismatches": 0, "posted_interest_rows": 969,
              "unplaced_interest_rows": 0, "multiply_placed_interest_rows": 0}],
            [{"cutoff_date": datetime(2026, 8, 25), "snapshot_rows": 157, "distinct_accounts": 157,
              "nonzero_accrual_accounts": 35, "accrued_interest_exact": "1799.71",
              "accrued_interest_accounting": "1799.71"}],
            [{"taxed_events": 256, "taxed_gross_interest": "37054.40", "withheld_tax": "3705.44",
              "rate_mismatches": 0, "linked_movement_mismatches": 0, "untaxed_event_mismatches": 0,
              "untaxed_nonzero_tax_links": 273, "catch_up_tax_mismatches": 0}],
            [{"company_id": "001", "line_id": "00001", "line_name": "VISTA", "account_type": "001",
              "default_rate": "3.00", "minimum_term_days": None, "maximum_term_days": None,
              "capitalization_period": "02", "capitalization_method": "01", "tax_capable": True,
              "principal_gl": "211002", "interest_expense_gl": "711001010001",
              "interest_payable_gl": "2110029901", "tax_gl": "2230000100", "account_count": 38,
              "observed_minimum_rate": "3.00", "observed_maximum_rate": "3.00"}],
        ]
        source_context = MagicMock()
        source_context.__enter__.return_value = object()
        settings = SimpleNamespace(
            source=SimpleNamespace(server="source", port=1433, database="arissto"),
            target=SimpleNamespace(pg_url=None),
        )
        with (
            patch("arissto_sync.savings.source_connection", return_value=source_context),
            patch("arissto_sync.savings.select_rows", side_effect=source_results),
            patch("arissto_sync.savings.source_fingerprint", return_value="source-fingerprint"),
        ):
            report = inspect_savings(settings, self.contract)
        self.assertTrue(report["read_ready"])
        self.assertFalse(report["ready"])
        self.assertNotIn("cutoff_field_selection", report["blockers"])
        self.assertNotIn("cutoff_completed_close_snapshot_missing", report["blockers"])
        self.assertEqual(report["source"]["cutoff"]["distinct_accounts"], 157)
        self.assertEqual(report["source"]["fixed_deposit_cycles"]["cycle_count"], 405)
        self.assertNotIn("fixed_deposit_cycles:unplaced_interest_rows", report["blockers"])
        self.assertIn("target_postgres_inspection_not_configured", report["blockers"])
        self.assertNotIn("implementation_gate:native_actual_actual_interest_basis", report["blockers"])
        self.assertNotIn("implementation_gate:native_opening_day_interest_schedule", report["blockers"])
        self.assertNotIn("implementation_gate:controlled_native_lifecycle_proof", report["blockers"])
        self.assertNotIn("implementation_gate:deterministic_plan_apply_reconcile_and_full_population", report["blockers"])
        self.assertNotIn("implementation_gate:native_linked_account_isr_transaction", report["blockers"])
        self.assertNotIn("implementation_gate:event_level_isr_contract", report["blockers"])
        self.assertEqual(report["source"]["historical_isr"]["rate_mismatches"], 0)
        self.assertNotIn("joint_account_primary_owner_ambiguous", report["blockers"])
        self.assertNotIn("customer name", str(report))

        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["cutoff"]["selected_exact_field"] = "UNREVIEWED"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "savings.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a reviewed candidate"):
                SavingsContract.load(path)


if __name__ == "__main__":
    unittest.main()
