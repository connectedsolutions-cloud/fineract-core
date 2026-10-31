import hashlib
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from arissto_sync.clients import ClientDataIssue
from arissto_sync.engine import reconcile
from arissto_sync.cli import parser
from arissto_sync.orchestration import build_workflow_plan


class ApplicantQuarantineTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(source=object(), target=SimpleNamespace(
            name="local", fingerprint="target", pg_url="local"))
        self.reason = "unmapped_client_type_status:007"
        self.qhash = hashlib.sha256(f"contract:q:{self.reason}".encode()).hexdigest()
        self.approval = {"source_key": "q", "source_hash": self.qhash,
                         "error_code": "ClientDataIssue:" + self.reason}
        self.rows = [{"key": "valid", "status": "003"}, {"key": "q", "status": "007"}]
        self.items = [
            {"source_key": "valid", "source_hash": "validhash", "target_id": "1", "status": "succeeded"},
            {**self.approval, "target_id": None, "status": "quarantined"},
        ]
        self.state = Mock()
        self.state.run.return_value = {"target_fingerprint": "target", "plan_id": "plan", "status": "completed_with_errors"}
        self.state.plan.return_value = {"contract_hash": "contract"}
        self.state.run_items.return_value = self.items
        self.contract = Mock(contract_hash="contract", import_active=True)
        self.contract.raw = {"source": {"status_key": "status"}}
        self.contract.source_key.side_effect = lambda row: row["key"]
        self.contract.external_id.side_effect = lambda row: row["key"]
        self.contract.legacy_external_id.side_effect = lambda row: "legacy:" + row["key"]
        def row_hash(row, catalogs):
            if row["key"] == "q":
                raise ClientDataIssue(self.reason if row["status"] == "007" else "changed")
            return "validhash"
        self.contract.hash_row.side_effect = row_hash
        self.contract.payload.return_value = {"payload": "valid"}

    def evaluate(self, approvals=None, matches=True, existing=False):
        with (
            patch("arissto_sync.engine.postgres_connection", side_effect=lambda _: nullcontext(object())),
            patch("arissto_sync.engine.source_connection", side_effect=lambda _: nullcontext(object())),
            patch("arissto_sync.engine.TargetCatalogs.from_postgres", return_value=object()),
            patch("arissto_sync.engine.extract_clients", return_value=self.rows),
            patch("arissto_sync.engine.target_client_index", return_value=({"q": {"id": "99"}} if existing else {}, {})),
            patch("arissto_sync.engine.load_target_payload_snapshots", return_value={"1": {}}),
            patch("arissto_sync.engine.snapshot_payload_matches", return_value=matches),
        ):
            return reconcile(self.settings, self.state, self.contract, "run", approvals)

    def test_default_remains_strict(self):
        self.assertFalse(self.evaluate()["ok"])

    def test_approved_applicant_stays_quarantined_and_valid_client_is_matched(self):
        report = self.evaluate([self.approval])
        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"], {"quarantined": 1, "accepted_quarantined": 1, "matched": 1})
        self.assertEqual(self.items[1]["status"], "quarantined")

    def test_imported_client_mismatch_still_blocks(self):
        self.assertFalse(self.evaluate([self.approval], matches=False)["ok"])

    def test_changed_classification_still_blocks(self):
        self.rows[1]["status"] = "003"
        self.assertFalse(self.evaluate([self.approval])["ok"])

    def test_changed_issue_or_hash_still_blocks(self):
        for field in ("error_code", "source_hash"):
            with self.subTest(field=field):
                self.assertFalse(self.evaluate([{**self.approval, field: "changed"}])["ok"])

    def test_existing_applicant_target_still_blocks(self):
        self.assertFalse(self.evaluate([self.approval], existing=True)["ok"])

    def test_extra_quarantine_still_blocks(self):
        self.items.append({**self.items[1], "source_key": "unapproved"})
        self.assertFalse(self.evaluate([self.approval])["ok"])

    def test_missing_approved_item_and_duplicate_approval_are_rejected(self):
        for approvals in ([{**self.approval, "source_key": "absent"}], [self.approval, self.approval]):
            with self.assertRaises(ValueError):
                self.evaluate(approvals)

    def test_production_acceptance_is_rejected(self):
        self.settings.target.name = "prod"
        with self.assertRaises(ValueError):
            self.evaluate([self.approval])

    def test_fresh_plan_cannot_accept_quarantines(self):
        with self.assertRaisesRegex(ValueError, "local resumed"):
            build_workflow_plan(self.settings, self.state, "local-full-sync", "cycle",
                                accept_client_applicant_quarantines=["q"])

    def test_cli_requires_each_explicit_key(self):
        args = parser().parse_args([
            "workflow", "plan", "--workflow", "local-full-sync", "--target", "local",
            "--cycle", "cycle", "--resume-from-workflow-run", "parent",
            "--accept-client-applicant-quarantine", "q1",
            "--accept-client-applicant-quarantine", "q2",
        ])
        self.assertEqual(args.accept_client_applicant_quarantines, ["q1", "q2"])


class ApplicantOwnerScopeTests(unittest.TestCase):
    def test_profile_adapters_pass_frozen_imported_owners(self):
        from arissto_sync.service_runtime import ServiceRuntime
        runtime = object.__new__(ServiceRuntime)
        runtime.settings, runtime.state = object(), object()
        runtime.client_owner_keys = ["valid"]
        runtime.contracts = {block: object() for block in (
            "client-staff-assignments", "client-pep", "client-family-references",
            "client-personal-family-references",
        )}
        for block, function in (
            ("client-staff-assignments", "build_client_staff_assignment_plan"),
            ("client-pep", "build_pep_plan"),
            ("client-family-references", "build_family_reference_plan"),
            ("client-personal-family-references", "build_family_reference_plan"),
        ):
            with self.subTest(block=block), patch("arissto_sync.service_runtime." + function) as plan:
                runtime.plan(block)
                plan.assert_called_once_with(runtime.settings, runtime.state, runtime.contracts[block],
                                             owner_keys={"valid"})

    def test_assignment_owner_filter_refuses_missing_owner(self):
        from arissto_sync.client_staff_assignments import build_client_staff_assignment_plan
        settings = SimpleNamespace(source=object(), target=SimpleNamespace(pg_url="local"))
        contract = Mock()
        contract.source_key.side_effect = lambda row: row["key"]
        with (
            patch("arissto_sync.client_staff_assignments.inspect_client_staff_assignments", return_value={}),
            patch("arissto_sync.client_staff_assignments.source_connection", return_value=nullcontext(object())),
            patch("arissto_sync.client_staff_assignments.extract_assignments", return_value=[{"key": "q"}]),
        ):
            with self.assertRaisesRegex(RuntimeError, "missing assignment owners"):
                build_client_staff_assignment_plan(settings, Mock(), contract, owner_keys={"valid"})
