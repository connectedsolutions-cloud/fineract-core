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
             ("employees", "employees"),
             ("client-staff-assignments", "client-staff-assignments"),
             ("membership-share-capital", "membership-share-capital"),
             ("savings-deposits", "savings-deposits"),
             ("native-share-capital", "native-share-capital"),
             ("aml-alerts", "aml-alerts"),
             ("loans", "loans"),
             ("mobile-collections", "mobile-collections")],
        )

    def test_service_report_selects_one_service(self):
        report = service_report("clients")
        self.assertEqual(report["service"]["status"], "available")
        self.assertTrue(report["service"]["executable"])

    def test_accounting_journal_entries_is_registered_as_planned_and_non_executable(self):
        service = service_report("accounting-journal-entries")["service"]
        self.assertEqual(service["status"], "planned")
        self.assertFalse(service["executable"])
        self.assertNotIn("cli_block", service)
        self.assertNotIn("commands", service)
        self.assertEqual(service["depends_on"], [])
        self.assertEqual(
            service["detail_documents"],
            ["migration-services/accounting-journal-entries/contract.md"],
        )

    def test_family_references_service_is_available_after_local_reconciliation(self):
        report = service_report("client-family-references")
        self.assertEqual(report["service"]["status"], "available")
        self.assertTrue(report["service"]["executable"])
        self.assertEqual(report["service"]["cli_block"], "client-family-references")
        self.assertEqual(report["service"]["depends_on"], ["clients"])
        self.assertIn("inspect", report["service"]["commands"])

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

    def test_client_staff_assignment_service_is_blocked_pending_expanded_local_acceptance(self):
        report = service_report("client-staff-assignments")["service"]
        self.assertEqual(report["status"], "blocked")
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

        self.assertEqual(loans["status"], "blocked")
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
        self.assertEqual(loans["post_sync_services"], ["mobile-collections"])
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
