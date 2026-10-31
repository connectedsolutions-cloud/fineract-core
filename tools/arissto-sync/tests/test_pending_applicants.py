import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from arissto_sync.clients import ClientContract, ClientDataIssue
from arissto_sync.engine import apply_plan, build_plan, snapshot_payload_matches, target_payload_matches


class PendingApplicantTests(unittest.TestCase):
    def setUp(self):
        self.contract = ClientContract({
            "source": {"table": "AFI_SOCIO", "company_key": "COMPANY", "branch_key": "BRANCH",
                       "party_key": "KEY", "status_key": "STATUS"},
            "core": {"firstname": {"source": "NAME", "type": "text", "disposition": "migrate",
                                   "ownership": "legacy-owned", "required": True}},
            "datatables": {}, "identifiers": {},
            "status": {"001": "active", "003": "active", "007": "pending"},
            "client_type_tag": {"group": "tipo_cliente", "status_map": {
                "001": "socio", "003": "cliente", "007": "cliente"}},
            "activation": {"source": "REGISTERED"},
            "create_defaults": {"active": True, "legalFormId": 1},
            "office_mapping": {"001": 1},
        })
        self.row = {"COMPANY": "001", "BRANCH": "001", "KEY": "100", "STATUS": "007",
                    "NAME": "Test", "REGISTERED": "2026-10-28"}
        self.catalogs = Mock()
        self.catalogs.client_tag_id.return_value = 7
        self.settings = SimpleNamespace(source=object(), target=SimpleNamespace(
            name="local", fingerprint="local", pg_url="local"))

    def test_real_config_maps_applicants_to_cliente_pending(self):
        c = ClientContract.load(Path(__file__).parents[1] / "config/clients.json")
        row = {"ID_ESTADO_SOCIO": "007", "ID_SUCURSAL": "001"}
        self.assertEqual(c.client_type_tag_name(row), "cliente")
        self.assertFalse(c.create_values(row)["active"])
        self.assertFalse(c.import_active_for(row))

    def test_applicant_payload_has_cliente_tag_submission_and_no_activation(self):
        p = self.contract.payload(self.row, self.catalogs)
        self.assertEqual(p["client_type_tag"]["name"], "cliente")
        self.assertEqual(p["expected_status"], 100)
        self.assertEqual(p["core"]["submittedOnDate"], "2026-10-28")
        self.assertNotIn("activationDate", p["core"])
        self.assertFalse(self.contract.create_values(self.row)["active"])

    def test_applicant_does_not_require_activation_date(self):
        self.row["REGISTERED"] = None
        p = self.contract.payload(self.row, self.catalogs)
        self.assertNotIn("activationDate", p["core"])
        self.assertNotIn("submittedOnDate", p["core"])

    def test_promotion_changes_hash_and_requires_activation(self):
        before = self.contract.hash_row(self.row, self.catalogs)
        for status in ("003", "001"):
            row = {**self.row, "STATUS": status}
            self.assertTrue(self.contract.import_active_for(row))
            self.assertTrue(self.contract.create_values(row)["active"])
            self.assertNotEqual(before, self.contract.hash_row(row, self.catalogs))
            p = self.contract.payload(row, self.catalogs)
            self.assertEqual(p["core"]["activationDate"], "2026-10-28")

    def test_other_unknown_classifications_still_quarantine(self):
        with self.assertRaises(ClientDataIssue):
            self.contract.payload({**self.row, "STATUS": "999"}, self.catalogs)

    def test_reconciliation_requires_pending_not_just_inactive(self):
        p = self.contract.payload(self.row, self.catalogs)
        snapshot = {"status_enum": 100, "core": {}, "tags": {"tipo_cliente": {7}},
                    "identifiers": {}, "addresses": {}, "datatables": {}}
        # Use only the lifecycle/tag expectations for this focused status assertion.
        p["core"] = {}
        self.assertTrue(snapshot_payload_matches(snapshot, p, expected_active=True))
        for status in (300, 600, 700, 800):
            with self.subTest(status=status):
                self.assertFalse(snapshot_payload_matches({**snapshot, "status_enum": status}, p, True))
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = (600,)
        self.assertFalse(target_payload_matches(conn, "9", p, True))

    def apply(self, action="create", current_status=100, recovered=False):
        row_hash = self.contract.hash_row(self.row, self.catalogs)
        state = Mock()
        state.plan.return_value = {"id": "plan", "block": "clients", "target_fingerprint": "local",
            "source_fingerprint": "source", "contract_hash": self.contract.contract_hash,
            "document": {"applicable": True, "schema_signature": "schema", "actions": [{
                "source_key": "100", "source_hash": row_hash, "action": action,
                "target_id": "9" if action == "update" else None}]}}
        state.start_run.return_value = "run"
        api = Mock()
        api.create_client.return_value = "9"
        api.get_client.return_value = {"id": 9, "active": current_status == 300,
                                      "status": {"id": current_status}, "tags": []}
        with (
            patch("arissto_sync.engine.source_fingerprint", return_value="source"),
            patch("arissto_sync.engine.inspect_clients", return_value={"ready": True, "schema_signature": "schema"}),
            patch("arissto_sync.engine.FineractApi", return_value=api),
            patch("arissto_sync.engine.source_connection", return_value=nullcontext(object())),
            patch("arissto_sync.engine.postgres_connection", side_effect=lambda _: nullcontext(object())),
            patch("arissto_sync.engine.TargetCatalogs.from_postgres", return_value=self.catalogs),
            patch("arissto_sync.engine.extract_clients", return_value=[self.row]),
            patch("arissto_sync.engine.resolve_client_identity", return_value=api.get_client.return_value if recovered else None),
        ):
            _, counts = apply_plan(self.settings, state, self.contract, "plan")
        return api, counts

    def test_create_never_activates_applicant(self):
        api, counts = self.apply()
        self.assertEqual(counts, {"create": 1})
        body = api.create_client.call_args.args[0]
        self.assertFalse(body["active"])
        self.assertNotIn("activationDate", body)
        api.activate_client.assert_not_called()

    def test_repeat_and_interrupted_create_recovery_remain_pending(self):
        for action, recovered in (("update", False), ("create", True)):
            with self.subTest(action=action):
                api, counts = self.apply(action=action, recovered=recovered)
                self.assertNotIn("failed", counts)
                api.create_client.assert_not_called()
                api.activate_client.assert_not_called()
                self.assertNotIn("active", api.update_client.call_args.args[1])
                self.assertNotIn("activationDate", api.update_client.call_args.args[1])

    def test_active_or_closed_client_is_not_demoted(self):
        for status in (300, 600):
            api, counts = self.apply(action="update", current_status=status)
            self.assertEqual(counts, {"failed": 1})
            api.update_client.assert_not_called()
            api.deactivate_client.assert_not_called()

    def test_later_cliente_activates_existing_pending_client(self):
        self.row["STATUS"] = "003"
        api, counts = self.apply(action="update")
        self.assertEqual(counts, {"update": 1})
        api.activate_client.assert_called_once_with("9", "2026-10-28")


    def plan(self, current_status=100, promoted=False):
        pending_hash = self.contract.hash_row(self.row, self.catalogs)
        if promoted:
            self.row["STATUS"] = "003"
        current = {"id": "9", "active": current_status == 300, "status": {"id": current_status},
                   "tags": [{"id": 7, "tagGroup": "tipo_cliente", "name": "cliente", "isActive": True}]}
        state = Mock()
        state.mapping.return_value = {"source_hash": pending_hash, "target_id": "9"}
        state.link.return_value = None
        state.save_plan.return_value = "plan"
        with (
            patch("arissto_sync.engine.inspect_clients", return_value={"fields": [], "ready": True, "schema_signature": "schema", "blockers": []}),
            patch("arissto_sync.engine.source_connection", return_value=nullcontext(object())),
            patch("arissto_sync.engine.postgres_connection", side_effect=lambda _: nullcontext(object())),
            patch("arissto_sync.engine.TargetCatalogs.from_postgres", return_value=self.catalogs),
            patch("arissto_sync.engine.extract_clients", return_value=[self.row]),
            patch("arissto_sync.engine.target_client_index", return_value=({"100": current}, {"9": current})),
            patch("arissto_sync.engine.FineractApi", return_value=Mock()),
            patch("arissto_sync.engine.source_fingerprint", return_value="source"),
        ):
            _, document = build_plan(self.settings, state, self.contract)
        return document["actions"][0]

    def test_repeat_pending_plan_is_unchanged_without_activation(self):
        action = self.plan()
        self.assertEqual(action["action"], "unchanged")
        self.assertNotIn("activate", action)

    def test_promotion_plan_updates_and_activates_same_client(self):
        action = self.plan(promoted=True)
        self.assertEqual(action["action"], "update")
        self.assertEqual(action["target_id"], "9")
        self.assertTrue(action["activate"])

    def test_plan_quarantines_active_applicant_conflict(self):
        action = self.plan(current_status=300)
        self.assertEqual(action["action"], "quarantine")
        self.assertEqual(action["reason"], "pending_client_status_conflict")
