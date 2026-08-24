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

    def test_registry_has_six_executable_blocks(self):
        registry = load_registry()
        executable = [service for service in registry["services"] if service["executable"]]
        self.assertEqual(
            [(service["id"], service["cli_block"]) for service in executable],
            [("clients", "clients"), ("client-pep", "client-pep"),
             ("client-family-references", "client-family-references"),
             ("employees", "employees"),
             ("membership-share-capital", "membership-share-capital"),
             ("aml-alerts", "aml-alerts")],
        )

    def test_service_report_selects_one_service(self):
        report = service_report("clients")
        self.assertEqual(report["service"]["status"], "available")
        self.assertTrue(report["service"]["executable"])

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

    def test_membership_service_is_blocked_pending_scoped_local_reconciliation(self):
        report = service_report("membership-share-capital")["service"]
        self.assertEqual(report["status"], "blocked")
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

    def test_apply_accepts_opt_in_family_reference_workflow(self):
        args = parser().parse_args([
            "apply", "--target", "local", "--plan", "client-plan", "--with-family-references"
        ])
        self.assertTrue(args.with_family_references)

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
