import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from arissto_sync.service_registry import service_report


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "tools/arissto-sync/migration-services/loans/contract.md"
README = ROOT / "tools/arissto-sync/migration-services/loans/README.md"
IMPLEMENTATION_SEQUENCE = (
    ROOT / "tools/arissto-sync/migration-services/loans/implementation-sequence.md"
)
ORCHESTRATION = ROOT / "tools/arissto-sync/migration-services/orchestration.md"
MIGRATION = ROOT / "fineract-provider/src/main/resources/db/changelog/tenant/parts/0293_add_arissto_loan_product_map.xml"
TENANT_CHANGELOG = ROOT / "fineract-provider/src/main/resources/db/changelog/tenant/changelog-tenant.xml"


class LoansContractTests(unittest.TestCase):
    def test_registry_promotes_loans_and_orders_mobile_after_it(self):
        loans = service_report("loans")["service"]
        mobile = service_report("mobile-collections")["service"]

        self.assertEqual(loans["status"], "blocked")
        self.assertTrue(loans["executable"])
        self.assertEqual(loans["cli_block"], "loans")
        self.assertEqual(set(loans["commands"]), {
            "inspect", "plan", "apply", "retry", "reconcile", "status", "schedule_proof"
        })
        self.assertEqual(loans["post_sync_services"], ["mobile-collections"])
        self.assertIn("loans", mobile["depends_on"])
        self.assertIn(
            "migration-services/loans/implementation-sequence.md",
            loans["detail_documents"],
        )

    def test_gate_five_has_no_global_implementation_gate(self):
        config = json.loads((ROOT / "tools/arissto-sync/config/loans.json").read_text(encoding="utf-8"))

        self.assertEqual(config["implementation_gates"], [])

    def test_contract_freezes_namespaced_loan_and_transaction_identity(self):
        contract = CONTRACT.read_text(encoding="utf-8")

        self.assertIn("ARISSTO:CRD:{ID_CREDITO}", contract)
        self.assertIn("ARISSTO:CRD-MOV:{ID_MOVIMIENTO_CARTERA}", contract)
        self.assertIn("100-character limit", contract)
        self.assertIn("No service may resolve a transaction from date and amount", contract)

    def test_contract_assigns_financial_ownership_only_to_loans(self):
        contract = CONTRACT.read_text(encoding="utf-8")

        self.assertIn("sole migration owner", contract)
        self.assertIn("cannot call a repayment", contract)
        self.assertIn("by amount alone is prohibited", contract)
        self.assertIn("A second unchanged run produces zero new native loans", contract)

    def test_contract_freezes_post_due_interest_strategy(self):
        config = json.loads((ROOT / "tools/arissto-sync/config/loans.json").read_text(encoding="utf-8"))
        contract = CONTRACT.read_text(encoding="utf-8")

        self.assertEqual(
            config["product_contract"]["transaction_strategy"],
            "credesal-accrued-interest-first-strategy",
        )
        self.assertNotIn("native_schedule_proof", config["implementation_gates"])
        self.assertNotIn("native_reversal_pairing_proof", config["implementation_gates"])
        self.assertEqual(config["movement_order"], ["FECHA_OPERACION", "ID_MOVIMIENTO_CARTERA"])
        self.assertEqual(config["supported_transactions"]["4:00004"], "repayment-reversal")
        self.assertEqual(config["supported_transactions"]["4:00013"], "adjusted-repayment")
        self.assertEqual(config["supported_transactions"]["4:00030"], "disbursement-reversal")
        self.assertIn("post-due interest", contract)
        self.assertIn("fixed `360`, `364`, or `365`", contract)
        self.assertIn("`ACTUAL` splits a cross-year interval", contract)
        self.assertIn("mixed 360/365 schedule", contract)

    def test_docs_distinguish_local_acceptance_from_full_target_migration(self):
        readme = README.read_text(encoding="utf-8")
        contract = CONTRACT.read_text(encoding="utf-8")
        sequence = IMPLEMENTATION_SEQUENCE.read_text(encoding="utf-8")

        self.assertIn("implementation acceptance, not evidence", readme)
        self.assertIn("not a full-target portfolio apply", sequence)
        self.assertIn("blocks on count, number, date, principal, interest", contract)
        self.assertIn("Gate 5 was completed under", sequence)
        self.assertNotIn("MONTO_OTROS` and contributions remain subject", readme)

    def test_orchestration_freezes_loans_before_mobile_financial_boundary(self):
        orchestration = ORCHESTRATION.read_text(encoding="utf-8")

        self.assertIn("Current manual loans-to-mobile-collections flow", orchestration)
        self.assertIn("loans --> mobile", orchestration)
        self.assertIn("Mobile Collections never repairs a missing loan repayment", orchestration)
        self.assertIn("222099940104 CUOTAS PENDIENTES DE", orchestration)

    def test_line_00001_manual_schedule_adjustments_are_narrow_and_non_blocking(self):
        config = json.loads((ROOT / "tools/arissto-sync/config/loans.json").read_text(encoding="utf-8"))
        contract = CONTRACT.read_text(encoding="utf-8")
        exception = config["historical_schedule_exceptions"]["00001"]

        self.assertEqual(exception["classification"], "manual-adjustment")
        self.assertEqual(exception["source_loan_ids"], [24, 435, 945])
        self.assertEqual(exception["plan_behavior"], "accept-native-schedule")
        self.assertFalse(exception["blocking"])
        self.assertFalse(exception["synthesize_missing_installments"])
        self.assertFalse(exception["synthesize_adjustment_transactions"])
        self.assertEqual(
            exception["required_reconciliation"],
            [
                "source-movement-identities",
                "source-movement-component-totals",
                "cutover-balances",
                "terminal-status",
            ],
        )
        self.assertIn("does not quarantine", contract)
        self.assertIn("loans `24`, `435`, or `945`", contract)
        self.assertIn("must not be generalized", contract)

    def test_line_00010_manual_schedule_adjustments_are_narrow_and_non_blocking(self):
        config = json.loads((ROOT / "tools/arissto-sync/config/loans.json").read_text(encoding="utf-8"))
        contract = CONTRACT.read_text(encoding="utf-8")
        exception = config["historical_schedule_exceptions"]["00010"]

        self.assertEqual(exception["classification"], "manual-adjustment")
        self.assertEqual(
            exception["source_loan_ids"],
            [23, 90, 317, 340, 359, 1117, 1484, 1743, 1748, 2069, 2241, 2254, 2355],
        )
        self.assertEqual(exception["plan_behavior"], "accept-native-schedule")
        self.assertFalse(exception["blocking"])
        self.assertFalse(exception["synthesize_missing_installments"])
        self.assertFalse(exception["synthesize_adjustment_transactions"])
        self.assertEqual(
            exception["required_reconciliation"],
            [
                "source-movement-identities",
                "source-movement-component-totals",
                "cutover-balances",
                "terminal-status",
            ],
        )
        self.assertIn("`1484`", contract)
        self.assertIn("two archived edits", contract)
        self.assertIn("Closed loans `23`, `90`, `317`, `340`, and `359`", contract)

    def test_loan_83_incomplete_schedule_is_reference_only_not_manual(self):
        config = json.loads((ROOT / "tools/arissto-sync/config/loans.json").read_text(encoding="utf-8"))
        contract = CONTRACT.read_text(encoding="utf-8")
        exception = config["historical_reference_only_schedules"]

        self.assertEqual(
            set(exception),
            {
                "26", "83", "8", "381", "1739", "1775", "1795", "1871",
                "1893", "2006", "2063", "2111", "2482",
            },
        )
        self.assertEqual(
            exception["26"]["classification"],
            "closed-zero-principal-schedule-with-exact-lifecycle",
        )
        self.assertIn("runtime signature", contract)
        self.assertIn("reviewed `26 -> 108` chain", contract)
        self.assertEqual(exception["83"]["classification"], "incomplete-source-contractual-schedule")
        self.assertEqual(exception["83"]["plan_behavior"], "accept-native-schedule")
        self.assertFalse(exception["83"]["blocking"])
        for loan_id in (8, 1739, 1795, 1893, 2063, 2111, 2482):
            reviewed = exception[str(loan_id)]
            self.assertEqual(reviewed["classification"], "trailing-zero-core-schedule-rows")
            self.assertEqual(reviewed["plan_behavior"], "accept-native-schedule")
            self.assertFalse(reviewed["blocking"])
            self.assertFalse(reviewed["synthesize_missing_installments"])
            self.assertFalse(reviewed["synthesize_adjustment_transactions"])
        for loan_id in (381, 1775, 1871, 2006):
            reviewed = exception[str(loan_id)]
            self.assertEqual(reviewed["classification"], "terminal-zero-core-charge-only-row")
            self.assertEqual(reviewed["plan_behavior"], "accept-native-schedule")
            self.assertFalse(reviewed["blocking"])
            self.assertFalse(reviewed["synthesize_missing_installments"])
            self.assertFalse(reviewed["synthesize_adjustment_transactions"])
        self.assertIn("Loan `83`", contract)
        self.assertIn("not classified as a manual adjustment", contract)
        self.assertIn("Loans `8`, `1739`, `1795`, `1893`, `2063`, `2111`, and `2482`", contract)
        self.assertIn("trailing zero-core", contract)
        self.assertIn("Loans `381`, `1775`, `1871`, and `2006`", contract)
        self.assertIn("single terminal", contract)
        self.assertIn("charge-only cohort", contract)
        self.assertIn("Loan `2374` is not covered", contract)

    def test_loan_2120_is_a_narrow_source_error_quarantine(self):
        config = json.loads((ROOT / "tools/arissto-sync/config/loans.json").read_text(encoding="utf-8"))
        contract = CONTRACT.read_text(encoding="utf-8")
        quarantine = config["source_error_quarantines"]

        self.assertEqual(quarantine, {
            "2120": {
                "classification": "superseded-undisbursed-shell",
                "plan_behavior": "quarantine-loan",
                "replacement_loan_id": 2121,
                "create_target_loan": False,
            },
        })
        self.assertIn("Source loan `2120`", contract)
        self.assertIn("replacement loan `2121`", contract)

    def test_product_uses_one_portfolio_account_and_native_dimensions(self):
        config = json.loads((ROOT / "tools/arissto-sync/config/loans.json").read_text(encoding="utf-8"))
        contract = CONTRACT.read_text(encoding="utf-8")
        product = config["product_contract"]
        portfolio = product["portfolio_account_policy"]
        dimensions = product["dimension_contract"]

        self.assertEqual(portfolio["mode"], "single-native-account-per-product")
        self.assertFalse(portfolio["dynamic_gl_switching"])
        self.assertFalse(portfolio["split_products_by_historical_account"])
        self.assertEqual(
            portfolio["reviewed_primary_gl_by_line"],
            {"00001": "1141040101", "00010": "1141030101"},
        )
        self.assertEqual(
            portfolio["historical_alternate_gl_for_reconciliation"],
            {"00001": ["1142040101"], "00010": ["1142030101"]},
        )
        self.assertEqual(dimensions["report_filter"], "json-containment")
        self.assertEqual(
            dimensions["product_native_type_field"]["target"],
            "m_product_loan.id_tipo_linea",
        )
        self.assertIn("exactly one `loanPortfolioAccountId`", contract)
        self.assertIn("acc_gl_journal_entry.dimensions", contract)

    def test_implementation_sequence_preserves_gate_order(self):
        sequence = IMPLEMENTATION_SEQUENCE.read_text(encoding="utf-8")

        self.assertIn("Gate 1: read-only source inspection", sequence)
        self.assertIn("Gate 3: native lifecycle spikes", sequence)
        self.assertIn("order that must remain intact", sequence)

    def test_gate_two_schema_is_minimal_and_uses_native_external_ids(self):
        config = json.loads((ROOT / "tools/arissto-sync/config/loans.json").read_text(encoding="utf-8"))
        contract = CONTRACT.read_text(encoding="utf-8")
        migration = MIGRATION.read_text(encoding="utf-8")
        ET.parse(MIGRATION)

        product_contract = config["product_contract"]
        self.assertEqual(product_contract["target_baseline"], "empty-business-data")
        self.assertEqual(product_contract["product_ownership"], "loans-service-creates-native-products")
        self.assertEqual(product_contract["resolution_policy"], "external-id-create-or-validate")
        self.assertFalse(product_contract["reuse_unowned_products"])
        self.assertEqual(product_contract["crosswalk_write_timing"], "after-native-product-create")
        self.assertEqual(product_contract["creation_scope"], "reviewed-lines-required-by-selected-loans")

        self.assertIn("ARISSTO:CRD-LINE:{ID_LINEA_CREDITO}", contract)
        self.assertNotIn("ARISSTO:CRD-LINE:{ID_EMPRESA}", contract)
        self.assertIn('columnNames="arissto_line_id"', migration)
        self.assertNotIn('columnNames="arissto_company_id,arissto_line_id"', migration)
        self.assertIn("No loan or transaction shadow table is introduced", contract)
        self.assertIn("crosswalk is an idempotency and", contract)
        self.assertIn("not a bootstrap list", contract)
        self.assertIn("never reuses or auto-binds an unowned product", contract)
        self.assertIn('tableName="credesal_loan_product_map"', migration)
        self.assertIn('referencedTableName="m_product_loan"', migration)
        self.assertNotIn("credesal_loan_migration", migration)
        self.assertNotIn("credesal_loan_event", migration)
        self.assertIn("parts/0293_add_arissto_loan_product_map.xml", TENANT_CHANGELOG.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
