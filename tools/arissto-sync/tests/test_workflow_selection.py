import unittest

from arissto_sync.workflow_definitions import (
    inspect_workflow,
    load_workflow,
    select_workflow_services,
)


class WorkflowSelectionTests(unittest.TestCase):
    LIABILITY_TRANSFER_PREREQUISITE = {
        "required_by_services": ["savings-deposits"],
        "financial_activity_id": 200,
        "gl_code": "2130050101",
        "gl_classification": 2,
        "gl_usage": 1,
    }

    def test_full_sync_exposes_every_executable_registry_service(self):
        definition = load_workflow("local-full-sync")
        report = inspect_workflow(definition)

        self.assertTrue(report["ready"])
        self.assertEqual(len(report["ordered_services"]), 14)
        self.assertIn("membership-share-capital", report["ordered_services"])
        self.assertIn("native-share-capital", report["ordered_services"])
        self.assertIn("aml-alerts", report["ordered_services"])
        self.assertEqual(report["ordered_services"][-1], "accounting-journal-entries")

    def test_native_share_selection_adds_membership_and_savings_dependencies(self):
        selected = select_workflow_services(
            load_workflow("local-full-sync"), ["native-share-capital"]
        )

        self.assertEqual(selected.services, (
            "clients", "membership-share-capital", "savings-deposits",
            "native-share-capital",
        ))

    def test_every_savings_workflow_bootstraps_liability_transfer_mapping(self):
        for workflow_id in (
            "local-full-sync", "local-membership-financial", "local-credit-collections",
        ):
            with self.subTest(workflow_id=workflow_id):
                definition = load_workflow(workflow_id)
                mappings = definition.document["target_prerequisites"][
                    "financial_activity_mappings"
                ]
                self.assertIn(self.LIABILITY_TRANSFER_PREREQUISITE, mappings)

    def test_savings_selection_keeps_liability_transfer_mapping_in_scope(self):
        selected = select_workflow_services(
            load_workflow("local-full-sync"), ["savings-deposits"]
        )
        mappings = selected.document["target_prerequisites"]["financial_activity_mappings"]

        self.assertIn(self.LIABILITY_TRANSFER_PREREQUISITE, mappings)
        required = [
            mapping for mapping in mappings
            if set(mapping["required_by_services"]).intersection(selected.services)
        ]
        self.assertEqual(required, [self.LIABILITY_TRANSFER_PREREQUISITE])

    def test_client_staff_assignment_selection_adds_clients_and_employees(self):
        selected = select_workflow_services(
            load_workflow("local-party-profile"), ["client-staff-assignments"]
        )
        report = inspect_workflow(selected)

        self.assertTrue(report["ready"])
        self.assertEqual(
            report["ordered_services"],
            ["clients", "employees", "client-staff-assignments"],
        )
        self.assertEqual(selected.document["selection"], {
            "mode": "dependency-closure",
            "requested_services": ["client-staff-assignments"],
            "included_services": ["clients", "employees", "client-staff-assignments"],
        })

    def test_personal_family_reference_selection_adds_only_clients(self):
        selected = select_workflow_services(
            load_workflow("local-party-profile"), ["client-personal-family-references"]
        )
        report = inspect_workflow(selected)

        self.assertTrue(report["ready"])
        self.assertEqual(report["ordered_services"], ["clients", "client-personal-family-references"])
        self.assertEqual(selected.document["selection"]["included_services"], [
            "clients", "client-personal-family-references",
        ])

    def test_loans_selection_adds_only_its_prerequisites(self):
        selected = select_workflow_services(
            load_workflow("local-credit-collections"), ["loans"]
        )
        report = inspect_workflow(selected)

        self.assertTrue(report["ready"])
        self.assertEqual(report["ordered_services"], ["clients", "employees", "loans"])
        self.assertNotIn("savings-deposits", selected.services)
        self.assertNotIn("mobile-collections", selected.services)
        self.assertEqual(selected.document["selection"], {
            "mode": "dependency-closure",
            "requested_services": ["loans"],
            "included_services": ["clients", "employees", "loans"],
        })

    def test_mobile_collections_selection_includes_full_dependency_closure(self):
        selected = select_workflow_services(
            load_workflow("local-credit-collections"), ["mobile-collections"]
        )
        self.assertEqual(selected.services, (
            "clients", "employees", "loans", "savings-deposits", "mobile-collections",
        ))

    def test_dte_history_selection_includes_clients_and_loans(self):
        selected = select_workflow_services(
            load_workflow("local-credit-collections"), ["dte-history"]
        )
        self.assertEqual(selected.services, ("clients", "employees", "loans", "dte-history"))

    def test_rejects_empty_or_out_of_workflow_selection(self):
        definition = load_workflow("local-credit-collections")
        with self.assertRaisesRegex(ValueError, "at least one"):
            select_workflow_services(definition, [])
        with self.assertRaisesRegex(ValueError, "not part of workflow"):
            select_workflow_services(definition, ["client-pep"])


if __name__ == "__main__":
    unittest.main()
