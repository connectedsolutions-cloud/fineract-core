import json
import tempfile
import unittest
from pathlib import Path

from arissto_sync.cli import parser
from arissto_sync.service_registry import load_registry, service_report


class MigrationServiceRegistryTests(unittest.TestCase):
    def test_services_command_requires_no_target(self):
        args = parser().parse_args(["services"])
        self.assertEqual(args.command, "services")
        self.assertIsNone(args.service)

    def test_registry_executable_blocks_match_current_registry(self):
        registry = load_registry()
        executable = [service for service in registry["services"] if service["executable"]]
        self.assertEqual(
            [(service["id"], service["cli_block"]) for service in executable],
            [("clients", "clients"), ("client-pep", "client-pep"),
             ("client-family-references", "client-family-references"),
             ("client-personal-family-references", "client-personal-family-references"),
             ("employees", "employees"),
             ("client-staff-assignments", "client-staff-assignments"),
             ("membership-share-capital", "membership-share-capital"),
             ("savings-deposits", "savings-deposits"),
             ("native-share-capital", "native-share-capital"),
             ("aml-alerts", "aml-alerts"),
             ("loans", "loans"),
             ("dte-history", "dte-history"),
             ("mobile-collections", "mobile-collections"),
             ("accounting-journal-entries", "accounting")],
        )

    def test_service_report_selects_one_service(self):
        report = service_report("clients")
        self.assertEqual(report["service"]["status"], "available")
        self.assertTrue(report["service"]["executable"])

    def test_accounting_journal_entries_is_planned_but_executable_for_local_acceptance(self):
        service = service_report("accounting-journal-entries")["service"]
        self.assertEqual(service["status"], "planned")
        self.assertTrue(service["executable"])
        self.assertEqual(service["category"], "accounting")
        self.assertEqual(service["cli_block"], "accounting")
        self.assertEqual(service["commands"], ["inspect", "plan", "apply", "retry", "reconcile", "status"])
        parsed = parser().parse_args([
            "inspect", "--block", "accounting", "--cutoff-date", "2026-10-01"
        ])
        self.assertEqual(parsed.block, "accounting")
        self.assertIsNone(parsed.target)
        planned = parser().parse_args([
            "plan", "--block", "accounting", "--target", "local",
            "--source-key", "001:001:00065:10", "--cutoff-date", "2026-01-01",
        ])
        self.assertEqual(planned.block, "accounting")
        self.assertEqual(planned.source_key, ["001:001:00065:10"])
        period_plan = parser().parse_args([
            "plan", "--block", "accounting", "--target", "local",
            "--period", "00028", "--cutoff-date", "2026-01-01",
        ])
        self.assertEqual(period_plan.period, ["00028"])
        self.assertEqual(
            service["depends_on"],
            ["savings-deposits", "native-share-capital", "loans", "mobile-collections"],
        )
        self.assertEqual(service["configuration"], "config/accounting.json")
        self.assertEqual(
            service["detail_documents"],
            [
                "migration-services/accounting-journal-entries/contract.md",
                "migration-services/accounting-journal-entries/implementation-sequence.md",
            ],
        )
        config = json.loads((Path(__file__).resolve().parents[1] / service["configuration"]).read_text())
        self.assertEqual(config["category"], "accounting")
        self.assertIsNone(config["cutoff"]["date"])
        self.assertEqual(config["cutoff"]["post_cutoff_owner"], "fineract")
        self.assertEqual(config["account_mapping"]["default"], "exact_code")
        self.assertEqual(config["account_mapping"]["overrides"]["222099940102"], "222099910201")
        origin = config["historical_origin"]
        self.assertEqual(origin["first_period_id"], "00028")
        self.assertEqual(origin["first_eligible_journal_date"], "2022-11-18")
        self.assertEqual(origin["opening_balance_basis"], "demonstrated_zero_at_first_journal_bearing_period")
        self.assertFalse(origin["synthetic_opening_journal_allowed"])
        self.assertFalse(origin["residual_balance_journal_allowed"])
        eligibility = config["source_eligibility"]
        self.assertEqual(eligibility["importable_journal_statuses"], ["3"])
        self.assertEqual(
            eligibility["journal_status_dispositions"]["1"]["reason_code"],
            "SOURCE_JOURNAL_NOT_MAYORIZED",
        )
        self.assertEqual(
            eligibility["journal_status_dispositions"]["2"]["reason_code"],
            "SOURCE_JOURNAL_EXCLUDED_FROM_LEDGER",
        )
        self.assertEqual(
            eligibility["unexpected_status"]["reason_code"],
            "SOURCE_JOURNAL_STATUS_UNSUPPORTED",
        )
        self.assertEqual(eligibility["empty_journal"]["reason_code"], "SOURCE_JOURNAL_EMPTY")
        self.assertEqual(eligibility["unbalanced_journal"]["reason_code"], "SOURCE_JOURNAL_UNBALANCED")
        reversal = config["reversal_policy"]
        self.assertEqual(reversal["reporting_requirement"], "preserve_posted_gl_effects")
        self.assertEqual(
            reversal["historical_representation"],
            "import_each_eligible_source_journal_as_ordinary_journal",
        )
        self.assertFalse(reversal["pairing_required"])
        self.assertFalse(reversal["classification_required"])
        self.assertEqual(reversal["native_reversal_operation"], "never_for_historical_import")
        self.assertEqual(reversal["native_reversal_columns"], "leave_defaults_unlinked")
        self.assertEqual(
            reversal["opposite_posting_behavior"],
            "import_independently_when_eligible",
        )
        annual = config["annual_liquidation_policy"]
        self.assertEqual(annual["source_journal_type"], "003")
        self.assertEqual(annual["source_liquidation_flag"], "1")
        self.assertEqual(annual["expected_opening_flag"], "0")
        self.assertEqual(
            annual["unsupported_shape"]["reason_code"],
            "SOURCE_ANNUAL_LIQUIDATION_SHAPE_UNSUPPORTED",
        )
        self.assertEqual(
            annual["unexpected_opening_journal"]["reason_code"],
            "SOURCE_OPENING_JOURNAL_REQUIRES_REVIEW",
        )
        self.assertEqual(
            annual["historical_representation"],
            "import_complete_posted_closing_journal_on_source_date",
        )
        self.assertFalse(annual["generate_fineract_year_end_journal"])
        self.assertFalse(annual["import_cnt_mayor_carry_forward"])
        self.assertFalse(annual["generate_opening_or_residual_journal"])
        self.assertEqual(annual["report_filters"]["general_ledger"], "include")
        self.assertEqual(annual["report_filters"]["balance_sheet"], "include")
        self.assertEqual(
            annual["report_filters"]["income_statement"],
            "exclude_imported_journals_with_source_journal_type_003",
        )
        self.assertEqual(
            annual["report_filters"]["filter_authority"],
            "immutable_header_provenance_transaction_id",
        )
        self.assertIn("entry_date", annual["report_filters"]["forbidden_inference_fields"])
        text_policy = config["legacy_text_policy"]
        self.assertEqual(
            text_policy["preservation"],
            "verbatim_decoded_unicode_in_separate_provenance_columns",
        )
        self.assertEqual(text_policy["core_journal_description_role"], "display_projection_only")
        self.assertEqual(text_policy["core_journal_description_limit"], 500)
        self.assertEqual(
            set(text_policy["header_provenance_columns"]),
            {"CNT_PARTIDAS.CONCEPTO", "CNT_PARTIDAS.DESCRIPCION"},
        )
        self.assertEqual(
            set(text_policy["line_provenance_columns"]),
            {"CNT_DETALLE_PARTIDAS.CONCEPTO", "CNT_DETALLE_PARTIDAS.CONCEPTO_AUX"},
        )
        self.assertTrue(
            text_policy["raw_value_semantics"]["preserve_null_empty_and_whitespace_distinction"]
        )
        self.assertEqual(text_policy["raw_value_semantics"]["normalization_before_provenance_storage"], "none")
        self.assertEqual(
            text_policy["display_projection"]["line_precedence"],
            [
                "CNT_DETALLE_PARTIDAS.CONCEPTO",
                "CNT_PARTIDAS.DESCRIPCION",
                "CNT_PARTIDAS.CONCEPTO",
            ],
        )
        self.assertEqual(
            text_policy["display_projection"]["exclude_from_display"],
            ["CNT_DETALLE_PARTIDAS.CONCEPTO_AUX"],
        )
        self.assertFalse(text_policy["privacy"]["full_legacy_fields_in_standard_journal_api"])
        self.assertTrue(text_policy["privacy"]["display_projection_in_standard_journal_api"])
        self.assertFalse(text_policy["privacy"]["raw_text_in_plan_status_error_or_reconciliation_logs"])
        agency_dimension = config["agency_dimension"]
        self.assertEqual(agency_dimension["mapping_version"], "fineract-office-external-id-v1")
        self.assertEqual(agency_dimension["source_company"], "001")
        self.assertEqual(agency_dimension["source_column"], "ID_SUCURSAL_DESTINO")
        self.assertEqual(agency_dimension["target_json_column"], "acc_gl_journal_entry.dimensions")
        self.assertEqual(agency_dimension["target_key"], "office")
        self.assertEqual(agency_dimension["target_value_authority"], "m_office.external_id")
        self.assertEqual(agency_dimension["target_value_json_type"], "string")
        self.assertTrue(agency_dimension["line_value_overrides_transaction_value"])
        self.assertTrue(agency_dimension["mapping_selection_required"])
        self.assertEqual(set(agency_dimension["mapping"]), {"001", "002"})
        self.assertEqual(
            agency_dimension["mapping"]["001"],
            {
                "source_name": "AGENCIA CENTRAL",
                "target_office_id": 1,
                "target_office_external_id": "1",
                "dimension_value": "1",
            },
        )
        self.assertEqual(
            agency_dimension["mapping"]["002"],
            {
                "source_name": "USULUTAN",
                "target_office_id": 2,
                "target_office_external_id": "2",
                "dimension_value": "2",
            },
        )
        self.assertEqual(
            agency_dimension["unmapped_source"]["reason_code"],
            "SOURCE_DESTINATION_BRANCH_UNMAPPED",
        )
        self.assertIn("header_branch", agency_dimension["forbidden_fallbacks"])
        self.assertIn("single_fixed_office_id", agency_dimension["forbidden_fallbacks"])
        self.assertEqual(
            agency_dimension["native_post_cutoff_requirement"],
            "derive_same_dimension_value_from_posting_m_office_external_id",
        )
        self.assertEqual(
            agency_dimension["native_office_id_policy"],
            "per_line_from_destination_branch_mapping",
        )
        self.assertEqual(agency_dimension["native_office_id_authority"], "mapping.target_office_id")
        self.assertEqual(
            agency_dimension["transaction_balance_scope"],
            "complete_source_journal_across_all_offices",
        )
        self.assertFalse(agency_dimension["per_office_balance_required"])
        self.assertEqual(
            agency_dimension["closure_validation"],
            "all_distinct_mapped_line_offices_before_atomic_write",
        )
        self.assertFalse(agency_dimension["closure_bypass"])
        currency_precision = config["currency_precision"]
        self.assertEqual(currency_precision["policy_version"], "usd-numeric-18-2-v1")
        self.assertEqual(currency_precision["source_base_currency_iso"], "USD")
        self.assertEqual(
            currency_precision["source_amount_columns"],
            {"DEBE": "NUMERIC(18,2)", "HABER": "NUMERIC(18,2)"},
        )
        self.assertEqual(currency_precision["target_currency_code"], "USD")
        self.assertEqual(currency_precision["target_currency_decimal_places"], 2)
        self.assertEqual(currency_precision["target_amount_column"], "DECIMAL(19,6)")
        self.assertFalse(currency_precision["binary_float_allowed"])
        self.assertFalse(currency_precision["rounding_allowed"])
        self.assertFalse(currency_precision["recomputation_allowed"])
        self.assertEqual(currency_precision["target_range_max_integer_digits"], 13)
        self.assertEqual(
            currency_precision["unsupported_scale"]["reason_code"],
            "SOURCE_AMOUNT_SCALE_UNSUPPORTED",
        )
        self.assertEqual(
            currency_precision["target_overflow"]["reason_code"],
            "SOURCE_AMOUNT_TARGET_OVERFLOW",
        )
        self.assertEqual(
            currency_precision["currency_mismatch"]["reason_code"],
            "SOURCE_OR_TARGET_CURRENCY_UNSUPPORTED",
        )
        presentation = config["report_presentation"]
        self.assertEqual(presentation["policy_version"], "arissto-coa-presentation-v1")
        self.assertEqual(presentation["ledger_authority"], "acc_gl_journal_entry")
        self.assertFalse(presentation["amount_mutation_allowed"])
        self.assertEqual(
            presentation["source_metadata"]["target_table"],
            "credesal_gl_account_presentation",
        )
        self.assertTrue(presentation["source_metadata"]["parent_graph_authoritative_over_ultimo_nivel"])
        self.assertEqual(presentation["balance_orientation"]["D"], "debits_minus_credits")
        self.assertEqual(presentation["balance_orientation"]["A"], "credits_minus_debits")
        self.assertTrue(presentation["balance_orientation"]["preserve_negative_balances"])
        self.assertFalse(presentation["balance_orientation"]["absolute_value_allowed"])
        reports = presentation["reports"]
        self.assertEqual(reports["trial_balance"]["selector"], "BC=1")
        self.assertEqual(reports["balance_sheet"]["selected_row_count_at_audit"], 64)
        self.assertEqual(
            reports["balance_sheet"]["equation"],
            "assets=liabilities_plus_equity_plus_current_period_result",
        )
        self.assertEqual(
            reports["income_statement"]["selector"],
            "BC=1_and_BG=0_and_classifier_in_004_005",
        )
        self.assertEqual(reports["income_statement"]["net_result"], "income_minus_expense")
        self.assertEqual(
            reports["income_statement"]["annual_closing_journals"],
            "exclude_source_type_003_by_immutable_transaction_provenance",
        )
        self.assertFalse(presentation["legacy_templates"]["authoritative_for_target_reports"])
        self.assertEqual(
            set(presentation["legacy_templates"]["populated_but_rejected"]),
            {"00009", "00010", "00014"},
        )
        self.assertTrue(presentation["acceptance"]["consolidated_trial_balance_sides_must_match"])
        self.assertTrue(presentation["acceptance"]["balance_sheet_equation_must_equal_zero"])
        self.assertEqual(presentation["acceptance"]["report_to_direct_journal_variance"], "0.00")
        correction = config["transferred_loan_accrual_correction"]
        self.assertEqual(
            correction["policy_version"],
            "explicit-cross-office-reclassification-v1",
        )
        self.assertEqual(
            correction["historical_import_behavior"],
            "preserve_source_accounts_sides_amounts_and_posted_office",
        )
        self.assertFalse(correction["candidate_detection_authorizes_posting"])
        self.assertFalse(correction["automatic_correction_allowed"])
        self.assertIn("source_transaction_ids", correction["approval_input"]["required_fields"])
        self.assertIn("account_lines", correction["approval_input"]["required_fields"])
        self.assertIn(
            "source_provenance_line_ids",
            correction["approval_input"]["account_line_fields"],
        )
        self.assertEqual(
            correction["journal"]["origin"],
            "native_accounting_correction_not_migration",
        )
        self.assertEqual(correction["journal"]["permission"], "CREATE_CREDESAL_GL_CORRECTION")
        self.assertFalse(correction["journal"]["backdating_before_cutoff_allowed"])
        self.assertTrue(correction["journal"]["atomic"])
        self.assertFalse(correction["journal"]["core_direct_sql_allowed"])
        self.assertFalse(correction["line_generation"]["account_substitution_allowed"])
        self.assertFalse(correction["line_generation"]["amount_recomputation_allowed"])
        self.assertEqual(
            correction["invariants"]["consolidated_net_change_per_gl_account"],
            "0.00",
        )
        self.assertEqual(
            correction["invariants"]["consolidated_financial_statements_change"],
            "0.00",
        )
        self.assertTrue(correction["invariants"]["only_office_distribution_changes"])
        self.assertFalse(correction["invariants"]["product_or_customer_subledger_changes"])
        self.assertFalse(correction["invariants"]["imported_journal_or_provenance_mutation"])
        self.assertFalse(config["target"]["allow_core_gl_direct_sql"])
        self.assertFalse(config["test_reset"]["allow_row_level_accounting_wipe"])

    def test_family_references_service_is_available_after_local_reconciliation(self):
        report = service_report("client-family-references")
        self.assertEqual(report["service"]["status"], "available")
        self.assertTrue(report["service"]["executable"])
        self.assertEqual(report["service"]["cli_block"], "client-family-references")
        self.assertEqual(report["service"]["depends_on"], ["clients"])
        self.assertIn("inspect", report["service"]["commands"])

    def test_personal_family_references_service_is_acceptance_gated_and_depends_on_clients(self):
        service = service_report("client-personal-family-references")["service"]
        self.assertEqual(service["status"], "blocked")
        self.assertTrue(service["executable"])
        self.assertEqual(service["depends_on"], ["clients"])
        self.assertEqual(service["configuration"], "config/client_personal_family_references.json")
        args = parser().parse_args([
            "plan", "--target", "local", "--block", "client-personal-family-references",
            "--source-key", "personal:C0001:1",
        ])
        self.assertEqual(args.block, "client-personal-family-references")

    def test_employee_service_is_available_after_local_reconciliation(self):
        report = service_report("employees")["service"]
        self.assertEqual(report["status"], "available")
        self.assertTrue(report["executable"])
        self.assertEqual(report["cli_block"], "employees")
        args = parser().parse_args(["inspect", "--target", "local", "--block", "employees"])
        self.assertEqual(args.block, "employees")

    def test_loans_depends_directly_on_clients_and_employees(self):
        report = service_report("loans")["service"]
        self.assertEqual(report["depends_on"], ["clients", "employees"])

    def test_dte_history_is_an_executable_blocked_client_and_loan_dependent(self):
        report = service_report("dte-history")["service"]
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(report["executable"])
        self.assertEqual(report["depends_on"], ["clients", "loans"])
        self.assertEqual(report["configuration"], "config/dte_history.json")
        self.assertEqual(set(report["commands"]), {"inspect", "plan", "apply", "retry", "reconcile", "status"})
        args = parser().parse_args(["plan", "--target", "local", "--block", "dte-history"])
        self.assertEqual(args.block, "dte-history")

    def test_client_staff_assignment_service_is_available_after_expanded_local_acceptance(self):
        report = service_report("client-staff-assignments")["service"]
        self.assertEqual(report["status"], "available")
        self.assertTrue(report["executable"])
        self.assertEqual(report["depends_on"], ["clients", "employees"])
        self.assertEqual(report["configuration"], "config/client_staff_assignments.json")
        args = parser().parse_args([
            "inspect", "--target", "local", "--block", "client-staff-assignments"
        ])
        self.assertEqual(args.block, "client-staff-assignments")

    def test_membership_service_is_available_after_scoped_local_reconciliation(self):
        report = service_report("membership-share-capital")["service"]
        self.assertEqual(report["status"], "available")
        self.assertTrue(report["executable"])
        self.assertEqual(report["depends_on"], ["clients"])
        args = parser().parse_args([
            "inspect", "--target", "local", "--block", "membership-share-capital"
        ])
        self.assertEqual(args.block, "membership-share-capital")

    def test_aml_alert_service_is_available_and_executable(self):
        report = service_report("aml-alerts")["service"]
        self.assertEqual(report["status"], "available")
        self.assertTrue(report["executable"])
        self.assertEqual(report["cli_block"], "aml-alerts")
        self.assertEqual(report["depends_on"], ["clients"])
        self.assertEqual(report["configuration"], "config/aml_alerts.json")
        args = parser().parse_args(["inspect", "--target", "local", "--block", "aml-alerts"])
        self.assertEqual(args.block, "aml-alerts")

    def test_savings_service_is_available_after_full_population_reconciliation(self):
        report = service_report("savings-deposits")["service"]
        self.assertEqual(report["status"], "available")
        self.assertTrue(report["executable"])
        self.assertEqual(report["depends_on"], ["clients"])
        self.assertEqual(report["configuration"], "config/savings_deposits.json")
        self.assertEqual(report["cli_block"], "savings-deposits")
        self.assertEqual(set(report["commands"]), {"inspect", "plan", "apply", "reconcile", "status"})
        args = parser().parse_args(["inspect", "--target", "local", "--block", "savings-deposits"])
        self.assertEqual(args.block, "savings-deposits")
        planned = parser().parse_args(["plan", "--target", "local", "--block", "savings-deposits"])
        self.assertEqual(planned.block, "savings-deposits")

    def test_native_share_service_is_available_after_controlled_local_acceptance(self):
        report = service_report("native-share-capital")["service"]
        self.assertEqual(report["status"], "available")
        self.assertTrue(report["executable"])
        self.assertEqual(report["depends_on"], ["clients", "membership-share-capital", "savings-deposits"])
        self.assertEqual(set(report["commands"]), {"inspect", "plan", "apply", "retry", "reconcile", "status"})
        args = parser().parse_args(["inspect", "--target", "local", "--block", "native-share-capital"])
        self.assertEqual(args.block, "native-share-capital")
        planned = parser().parse_args(["plan", "--target", "local", "--block", "native-share-capital"])
        self.assertEqual(planned.block, "native-share-capital")

    def test_mobile_collections_is_available_after_local_reconciliation(self):
        loans = service_report("loans")["service"]
        mobile = service_report("mobile-collections")["service"]

        self.assertEqual(loans["status"], "available")
        self.assertTrue(loans["executable"])
        self.assertEqual(loans["cli_block"], "loans")
        self.assertEqual(loans["configuration"], "config/loans.json")
        self.assertEqual(set(loans["commands"]), {
            "inspect", "plan", "apply", "retry", "reconcile", "status", "schedule_proof"
        })
        args = parser().parse_args(["inspect", "--block", "loans", "--source-key", "123"])
        self.assertIsNone(args.target)
        self.assertEqual(args.source_key, "123")
        planned = parser().parse_args(["plan", "--target", "local", "--block", "loans", "--source-key", "123"])
        self.assertEqual(planned.block, "loans")
        self.assertEqual(planned.source_key, ["123"])
        status = parser().parse_args(["status", "--target", "local", "--block", "loans"])
        self.assertEqual(status.block, "loans")
        self.assertEqual(loans["post_sync_services"], ["mobile-collections", "dte-history"])
        self.assertEqual(mobile["status"], "available")
        self.assertTrue(mobile["executable"])
        self.assertEqual(mobile["cli_block"], "mobile-collections")
        self.assertEqual(mobile["depends_on"], ["clients", "employees", "savings-deposits", "loans"])
        self.assertEqual(mobile["configuration"], "config/mobile_collections.json")
        self.assertEqual(set(mobile["commands"]), {"inspect", "plan", "apply", "retry", "reconcile", "status"})
        parsed = parser().parse_args(["plan", "--target", "local", "--block", "mobile-collections"])
        self.assertEqual(parsed.block, "mobile-collections")

    def test_apply_accepts_opt_in_family_reference_workflow(self):
        args = parser().parse_args([
            "apply", "--target", "local", "--plan", "client-plan", "--with-family-references"
        ])
        self.assertTrue(args.with_family_references)

    def test_reconcile_accepts_compact_report_artifact_options(self):
        args = parser().parse_args([
            "reconcile", "--target", "local", "--run", "run-1",
            "--report", "/tmp/loan-report.json", "--sample-limit", "5",
        ])
        self.assertEqual(args.report, "/tmp/loan-report.json")
        self.assertEqual(args.sample_limit, 5)

    def test_pep_service_depends_on_clients_and_has_chained_trigger(self):
        report = service_report("client-pep")["service"]
        self.assertEqual(report["status"], "available")
        self.assertTrue(report["executable"])
        self.assertEqual(report["depends_on"], ["clients"])
        self.assertEqual(report["trigger"]["condition"], "successful-client-reconciliation")
        self.assertIn("--with-pep", report["trigger"]["command"])

    def test_apply_accepts_opt_in_pep_workflow(self):
        args = parser().parse_args([
            "apply", "--target", "local", "--plan", "client-plan", "--with-pep"
        ])
        self.assertTrue(args.with_pep)

    def test_unknown_service_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown migration service"):
            service_report("does-not-exist")

    def test_registry_rejects_unknown_and_cyclic_dependencies(self):
        for dependencies, message in [(["missing"], "unknown dependencies"), (["second"], "cycle")]:
            registry = {
                "version": 1,
                "services": [
                    {"id": "first", "status": "available", "executable": True,
                     "cli_block": "first", "depends_on": dependencies},
                    {"id": "second", "status": "available", "executable": True,
                     "cli_block": "second", "depends_on": ["first"]},
                ],
            }
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "registry.json"
                path.write_text(json.dumps(registry), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    load_registry(path)

    def test_registry_accepts_forward_post_sync_reference(self):
        registry = {
            "version": 1,
            "services": [
                {"id": "first", "status": "available", "executable": True,
                 "cli_block": "first", "post_sync_services": ["second"]},
                {"id": "second", "status": "available", "executable": True,
                 "cli_block": "second", "depends_on": ["first"]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(registry), encoding="utf-8")
            self.assertEqual(load_registry(path), registry)


if __name__ == "__main__":
    unittest.main()
