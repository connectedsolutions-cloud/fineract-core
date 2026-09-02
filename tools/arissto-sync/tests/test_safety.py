import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from arissto_sync.clients import ClientContract, TargetCatalogs
from arissto_sync.connections import FineractApi, select_rows
from arissto_sync.engine import (apply_plan, build_plan, client_update_api_payload, core_api_payload, datatable_api_payload,
                                 boolean_group_summary, resolve_client_identity, resolve_indexed_client_identity,
                                 load_target_payload_snapshots, snapshot_payload_matches, target_client_index,
                                 target_payload_matches)
from arissto_sync.sql_writer import ControlledSqlWriter, SqlWritePolicy
from arissto_sync.state import State


class FakeCursor:
    description = [("value",)]

    def execute(self, sql, params):
        self.sql = sql
        return self

    def fetchall(self):
        return [(1,)]


class FakeConnection:
    def cursor(self):
        return FakeCursor()


class SafetyTests(unittest.TestCase):
    def test_fineract_api_reuses_injected_http_session(self):
        response = Mock(content=b"{}")
        response.json.return_value = {}
        session = Mock()
        session.request.return_value = response
        config = SimpleNamespace(
            api_url="https://fineract.example.test/api/v1", api_user="user", api_password="secret",
            tenant="default", tls_verify=True,
        )
        api = FineractApi(config, session=session)

        api.ping()
        api.datatables()

        self.assertEqual(session.request.call_count, 2)
        self.assertTrue(all(call.kwargs["verify"] is True for call in session.request.call_args_list))

    def test_fineract_api_passes_explicit_idempotency_key(self):
        response = Mock(content=b"{}")
        response.json.return_value = {}
        session = Mock()
        session.request.return_value = response
        config = SimpleNamespace(
            api_url="https://fineract.example.test/api/v1", api_user="user", api_password="secret",
            tenant="default", tls_verify=True,
        )

        FineractApi(config, session=session).request(
            "POST", "savingsaccounts/3/transactions", {},
            {"command": "explicitWithholdTax"}, "arissto-event-key",
        )

        headers = session.request.call_args.kwargs["headers"]
        self.assertEqual(headers["Idempotency-Key"], "arissto-event-key")

    def test_fresh_identifier_create_skips_lookup_and_normalizes_status(self):
        api = FineractApi(SimpleNamespace())
        with patch.object(api, "request") as request:
            api.create_client_identifier("9", {
                "documentTypeId": 3, "documentKey": "masked", "status": "Active"
            })
        request.assert_called_once_with("POST", "clients/9/identifiers", {
            "documentTypeId": 3, "documentKey": "masked", "status": "ACTIVE"
        })

    def test_empty_generic_datatable_result_is_missing(self):
        api = FineractApi(SimpleNamespace())
        with patch.object(api, "request", return_value={"columnHeaders": [{"columnName": "id"}], "data": []}):
            self.assertIsNone(api.datatable_data("client_profile", "9"))

    def test_populated_generic_datatable_result_exists(self):
        result = {"columnHeaders": [{"columnName": "id"}], "data": [{"row": [9]}]}
        api = FineractApi(SimpleNamespace())
        with patch.object(api, "request", return_value=result):
            self.assertEqual(api.datatable_data("client_profile", "9"), result)

    def test_identifier_status_uses_enum_token_on_update(self):
        api = FineractApi(SimpleNamespace())
        existing = [{"id": 7, "documentType": {"id": 3}}]
        payload = {"documentTypeId": 3, "documentKey": "masked", "status": "Active"}
        with patch.object(api, "client_identifiers", return_value=existing), patch.object(api, "request") as request:
            api.upsert_client_identifier("9", payload)
        request.assert_called_once_with(
            "PUT", "clients/9/identifiers/7", {**payload, "status": "ACTIVE"}
        )
        self.assertEqual(payload["status"], "Active")

    def test_datatable_payload_uses_decimal_dot_locale(self):
        payload = {"monthlyIncome": 1234.5}
        self.assertEqual(datatable_api_payload(payload), {
            "monthlyIncome": 1234.5, "locale": "en", "dateFormat": "yyyy-MM-dd"
        })
        self.assertEqual(payload, {"monthlyIncome": 1234.5})

    def test_source_query_guard_allows_select_only(self):
        self.assertEqual(select_rows(FakeConnection(), "SELECT 1 AS value"), [{"value": 1}])
        with self.assertRaises(ValueError):
            select_rows(FakeConnection(), "UPDATE dbo.AFI_SOCIO SET X=1")
        with self.assertRaises(ValueError):
            select_rows(FakeConnection(), "SELECT 1; DELETE FROM dbo.AFI_SOCIO")

    def test_clients_direct_sql_is_denied(self):
        with self.assertRaises(PermissionError):
            SqlWritePolicy.assert_allowed("clients", "upsert_profile")

    def test_loans_direct_sql_is_limited_to_product_crosswalk(self):
        SqlWritePolicy.assert_allowed("loans", "upsert_loan_product_crosswalk")
        with self.assertRaises(PermissionError):
            SqlWritePolicy.assert_allowed("loans", "create_native_loan")

    def test_mobile_collection_sql_is_limited_to_metadata_upsert(self):
        SqlWritePolicy.assert_allowed("mobile-collections", "upsert_mobile_collection_metadata")
        for operation in ("create_repayment", "create_journal", "delete_mobile_collection"):
            with self.assertRaises(PermissionError):
                SqlWritePolicy.assert_allowed("mobile-collections", operation)

    def test_direct_sql_entity_transaction_rolls_back(self):
        connection = Mock()
        writer = ControlledSqlWriter(connection, "test")
        with patch.dict(SqlWritePolicy.ALLOWED, {"test": frozenset({"operation"})}):
            with self.assertRaises(RuntimeError):
                with writer.entity_transaction("operation"):
                    raise RuntimeError("failure")
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    def test_production_apply_requires_exact_fingerprint(self):
        settings = SimpleNamespace(
            target=SimpleNamespace(name="prod", fingerprint="prod-fingerprint"),
            source=SimpleNamespace(server="source", port=1433, database="arissto"),
        )
        contract = SimpleNamespace(contract_hash="contract")
        plan = {"id": "p", "target_fingerprint": "prod-fingerprint",
                "source_fingerprint": "ignored", "contract_hash": "contract", "document": {}}
        state = Mock()
        state.plan.return_value = plan
        with patch("arissto_sync.engine.source_fingerprint", return_value="ignored"):
            with self.assertRaisesRegex(RuntimeError, "confirm-production"):
                apply_plan(settings, state, contract, "p")

    def test_plan_document_and_state_are_target_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            plan_id = state.save_plan("target-a", "clients", "source-a", "contract-a", {
                "actions": [{"source_key": "1:1:9", "source_hash": "abc", "action": "create", "target_id": None}]
            })
            plan = state.plan(plan_id)
            self.assertEqual(plan["target_fingerprint"], "target-a")
            self.assertNotIn("customer name", plan["document"])

    def test_client_plan_applicability_depends_only_on_selected_target_readiness(self):
        settings = SimpleNamespace(
            target=SimpleNamespace(name="prod", fingerprint="prod-fingerprint", pg_url="postgresql://target"),
            source=SimpleNamespace(),
        )
        contract = SimpleNamespace(contract_hash="contract")
        state = Mock()
        state.save_plan.return_value = "plan-id"
        inspection = {"ready": True, "blockers": [], "fields": [], "schema_signature": "prod-schema"}
        with patch("arissto_sync.engine.inspect_clients", return_value=inspection), \
                patch("arissto_sync.engine.postgres_connection") as postgres, \
                patch("arissto_sync.engine.TargetCatalogs.from_postgres"), \
                patch("arissto_sync.engine.source_connection") as source, \
                patch("arissto_sync.engine.extract_clients", return_value=[]), \
                patch("arissto_sync.engine.source_fingerprint", return_value="source-fingerprint"):
            postgres.return_value.__enter__.return_value = Mock()
            source.return_value.__enter__.return_value = Mock()
            _, document = build_plan(settings, state, contract)

        self.assertTrue(document["applicable"])
        self.assertNotIn("other_target_drift", document)

    def test_client_contract_rejects_sql_identifiers(self):
        config = {
            "source": {"table": "AFI_SOCIO; DROP TABLE x", "company_key": "ID_EMPRESA",
                       "branch_key": "ID_SUCURSAL", "party_key": "ID_SOCIO", "status_key": "STATUS"},
            "core": {}, "datatables": {}, "status": {}
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clients.json"
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                ClientContract.load(path)

    def test_external_id_and_hash_are_deterministic(self):
        config = {
            "source": {"table": "AFI_SOCIO", "company_key": "ID_EMPRESA", "branch_key": "ID_SUCURSAL",
                       "party_key": "ID_SOCIO", "external_key": "NUMERO_AFILIACION", "status_key": "STATUS"},
            "core": {"firstname": {"source": "NAME", "disposition": "migrate", "ownership": "legacy-owned"}},
            "datatables": {}, "status": {"ACTIVO": "active"}
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clients.json"
            path.write_text(json.dumps(config))
            contract = ClientContract.load(path)
            row = {"ID_EMPRESA": "01", "ID_SUCURSAL": "02", "ID_SOCIO": "0003",
                   "NUMERO_AFILIACION": "0000000003", "STATUS": "ACTIVO", "NAME": " Ana  María "}
            self.assertEqual(contract.external_id(row), "0000000003")
            self.assertEqual(contract.payload(row)["core"]["externalId"], "0000000003")
            self.assertEqual(contract.legacy_external_id(row), "arissto:afi_socio:01:02:0003")
            sql, params = contract.query("0000000003")
            self.assertIn("[src].[NUMERO_AFILIACION] = ?", sql)
            self.assertEqual(params, ("0000000003",))
            with self.assertRaisesRegex(ValueError, "affiliation number"):
                contract.query("01:02:0003")
            self.assertEqual(contract.hash_row(row), contract.hash_row(dict(row)))

    def test_client_identity_transition_resolves_legacy_row_without_creating(self):
        contract = Mock()
        contract.external_id.return_value = "0000000003"
        contract.legacy_external_id.return_value = "arissto:afi_socio:01:02:0003"
        api = Mock()
        api.find_client.side_effect = [None, {"id": 9, "externalId": "arissto:afi_socio:01:02:0003"}]
        self.assertEqual(resolve_client_identity(api, contract, {}), {
            "id": 9, "externalId": "arissto:afi_socio:01:02:0003"
        })

    def test_client_identity_transition_refuses_two_target_clients(self):
        contract = Mock()
        contract.external_id.return_value = "0000000003"
        contract.legacy_external_id.return_value = "arissto:afi_socio:01:02:0003"
        api = Mock()
        api.find_client.side_effect = [{"id": 8}, {"id": 9}]
        with self.assertRaisesRegex(RuntimeError, "client_identity_collision"):
            resolve_client_identity(api, contract, {})

    def test_bulk_target_index_preserves_identity_status_and_tags(self):
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = [
            (8, "0000000003", 300, 6, "tipo_cliente", "socio", True),
            (8, "0000000003", 300, 9, "other", "vip", True),
        ]
        by_external, by_id = target_client_index(connection, ["0000000003"])
        self.assertIs(by_external["0000000003"], by_id["8"])
        self.assertTrue(by_external["0000000003"]["active"])
        self.assertEqual({tag["id"] for tag in by_external["0000000003"]["tags"]}, {6, 9})

    def test_indexed_identity_resolution_avoids_api_for_normal_mapping(self):
        contract = Mock()
        contract.external_id.return_value = "0000000003"
        contract.legacy_external_id.return_value = "arissto:afi_socio:01:02:0003"
        current = {"id": "8", "externalId": "0000000003", "active": True, "tags": []}
        api = Mock()

        result = resolve_indexed_client_identity(
            api, contract, {}, {"0000000003": current}, {"8": current}, "8"
        )

        self.assertIs(result, current)
        api.get_client.assert_not_called()

    def test_bulk_reconciliation_snapshot_matches_expected_payload(self):
        result = Mock()

        def execute(sql, params):
            if "FROM m_client WHERE" in sql:
                result.fetchall.return_value = [(9, 300, "Ana")]
            elif "m_client_tag_mapping" in sql:
                result.fetchall.return_value = [(9, 6, "tipo_cliente")]
            elif "m_client_identifier" in sql:
                result.fetchall.return_value = [(9, 3, "masked")]
            elif "m_client_address" in sql:
                result.fetchall.return_value = []
            elif "FROM client_profile" in sql:
                result.fetchall.return_value = [(9, True)]
            else:
                self.fail(f"Unexpected reconciliation SQL: {sql}")
            return result

        connection = Mock()
        connection.execute.side_effect = execute
        payload = {
            "core": {"firstname": "Ana"},
            "client_type_tag": {"id": 6, "group": "tipo_cliente"},
            "identifiers": [{"documentTypeId": 3, "documentKey": "masked"}],
            "addresses": [],
            "datatables": {"client_profile": {"isPep": True}},
            "absent_datatables": [],
        }

        snapshots = load_target_payload_snapshots(connection, {"9": payload})

        self.assertTrue(snapshot_payload_matches(snapshots["9"], payload, expected_active=True))
        self.assertEqual(connection.execute.call_count, 5)

    def test_state_can_retire_legacy_client_mapping_and_link(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            state.save_mapping("target", "clients", "01:02:0003", "9", "hash")
            state.add_link("target", "clients", "01:02:0003", "9")
            state.save_mapping("target", "clients", "0000000003", "9", "new-hash")
            state.delete_mapping("target", "clients", "01:02:0003")
            state.delete_link("target", "clients", "01:02:0003")
            self.assertIsNone(state.mapping("target", "clients", "01:02:0003"))
            self.assertIsNone(state.link("target", "clients", "01:02:0003"))
            self.assertEqual(state.mapping("target", "clients", "0000000003")["target_id"], "9")

    def test_client_creation_values_are_branch_scoped(self):
        config = {
            "source": {"table": "AFI_SOCIO", "company_key": "ID_EMPRESA", "branch_key": "ID_SUCURSAL",
                       "party_key": "ID_SOCIO", "status_key": "STATUS"},
            "core": {}, "datatables": {}, "status": {}, "create_defaults": {"active": False},
            "office_mapping": {"001": 1, "002": 2},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clients.json"
            path.write_text(json.dumps(config))
            contract = ClientContract.load(path)
            self.assertEqual(contract.create_values({"ID_SUCURSAL": "002"}), {"active": False, "officeId": 2})
            with self.assertRaisesRegex(RuntimeError, "source_branch_not_mapped"):
                contract.create_values({"ID_SUCURSAL": "999"})

    def test_active_client_creation_includes_activation_metadata(self):
        config = {
            "source": {"table": "AFI_SOCIO", "company_key": "ID_EMPRESA", "branch_key": "ID_SUCURSAL",
                       "party_key": "ID_SOCIO", "status_key": "STATUS"},
            "activation": {"source": "FECHA_REGISTRO", "type": "date", "disposition": "migrate", "ownership": "legacy-owned", "required": True},
            "core": {}, "datatables": {}, "status": {}, "create_defaults": {"active": True},
            "office_mapping": {"001": 1},
            "activation_floor_by_branch": {"001": "2023-01-15"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clients.json"
            path.write_text(json.dumps(config))
            contract = ClientContract.load(path)
            row = {"ID_EMPRESA": "001", "ID_SUCURSAL": "001", "ID_SOCIO": "1", "STATUS": "001",
                   "FECHA_REGISTRO": "2023-02-01"}
            self.assertEqual(contract.create_values(row), {
                "active": True, "officeId": 1, "dateFormat": "yyyy-MM-dd", "locale": "en",
            })
            self.assertEqual(contract.payload(row)["core"]["activationDate"], "2023-02-01")
            self.assertEqual(contract.payload(row)["core"]["submittedOnDate"], "2023-02-01")
            self.assertTrue(contract.import_active)

            earlier = {**row, "FECHA_REGISTRO": "2023-01-01"}
            self.assertEqual(contract.payload(earlier)["core"]["activationDate"], "2023-01-15")
            self.assertEqual(contract.payload(earlier)["core"]["submittedOnDate"], "2023-01-15")

    def test_core_payload_uses_iso_date_locale(self):
        payload = {"activationDate": "2023-02-01", "submittedOnDate": "2023-02-01"}
        self.assertEqual(core_api_payload(payload), {
            "activationDate": "2023-02-01", "submittedOnDate": "2023-02-01", "locale": "en",
            "dateFormat": "yyyy-MM-dd", "active": True
        })
        self.assertEqual(payload, {"activationDate": "2023-02-01", "submittedOnDate": "2023-02-01"})

    def test_client_type_tag_is_derived_from_status_and_originated_credit(self):
        config = {
            "source": {"table": "AFI_SOCIO", "company_key": "ID_EMPRESA", "branch_key": "ID_SUCURSAL",
                       "party_key": "ID_SOCIO", "status_key": "STATUS"},
            "client_type_tag": {
                "group": "tipo_cliente", "status_map": {"001": "socio", "003": "cliente"},
                "combined": {"base_status": "001", "tag": "cliente-socio", "when_exists": {
                    "table": "CRD_CARTERA", "join": {"ID_EMPRESA": "ID_EMPRESA",
                                                        "ID_SUCURSAL_SOCIO": "ID_SUCURSAL",
                                                        "ID_SOCIO": "ID_SOCIO"}}}},
            "core": {}, "datatables": {}, "status": {},
        }
        catalogs = TargetCatalogs({}, {}, {}, {}, {}, {}, False, "catalogs", {
            ("tipo_cliente", "socio"): 5, ("tipo_cliente", "cliente"): 2,
            ("tipo_cliente", "cliente-socio"): 6,
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clients.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            contract = ClientContract.load(path)
            sql, _ = contract.query()
            self.assertIn("[dbo].[CRD_CARTERA]", sql)
            base = {"ID_EMPRESA": "001", "ID_SUCURSAL": "001", "ID_SOCIO": "1"}
            self.assertEqual(contract.payload({**base, "STATUS": "003", "__client_type_related_exists": 1}, catalogs)
                             ["core"]["tagIds"], [2])
            combined = contract.payload({**base, "STATUS": "001", "__client_type_related_exists": 1}, catalogs)
            self.assertEqual(combined["core"]["tagIds"], [6])
            self.assertEqual(combined["client_type_tag"]["name"], "cliente-socio")
            self.assertEqual(contract.payload({**base, "STATUS": "001", "__client_type_related_exists": 0}, catalogs)
                             ["core"]["tagIds"], [5])

    def test_client_tag_update_preserves_active_unrelated_tags(self):
        payload = {"firstname": "Ana", "tagIds": [6]}
        current = {"tags": [
            {"id": 5, "tagGroup": "tipo_cliente", "isActive": True},
            {"id": 20, "tagGroup": "risk", "isActive": True},
            {"id": 21, "tagGroup": "legacy", "isActive": False},
        ]}
        result = client_update_api_payload(payload, current, {"id": 6, "group": "tipo_cliente"})
        self.assertEqual(result["tagIds"], [6, 20])
        self.assertEqual(payload["tagIds"], [6])

    def test_client_tag_update_omits_tag_ids_when_type_is_already_correct(self):
        result = client_update_api_payload(
            {"firstname": "Ana", "tagIds": [6]},
            {"tags": [{"id": 6, "tagGroup": "tipo_cliente", "isActive": True},
                      {"id": 20, "tagGroup": "risk", "isActive": True}]},
            {"id": 6, "group": "tipo_cliente"},
        )
        self.assertNotIn("tagIds", result)

    def test_reconciliation_requires_exactly_one_expected_type_tag(self):
        result = Mock()

        def execute(sql, params):
            if "m_client_tag_mapping" in sql:
                result.fetchall.return_value = [(6,)]
            else:
                result.fetchall.return_value = []
            return result

        connection = Mock()
        connection.execute.side_effect = execute
        payload = {"core": {}, "client_type_tag": {"id": 6, "group": "tipo_cliente"},
                   "identifiers": [], "addresses": [], "datatables": {}}
        self.assertTrue(target_payload_matches(connection, "9", payload))
        result.fetchall.return_value = [(5,), (6,)]

        def duplicate_execute(sql, params):
            result.fetchall.return_value = [(5,), (6,)] if "m_client_tag_mapping" in sql else []
            return result

        connection.execute.side_effect = duplicate_execute
        self.assertFalse(target_payload_matches(connection, "9", payload))

    def test_pep_inspection_summary_uses_strict_contract_values(self):
        mapping = {"source": "PEP", "type": "boolean", "value_map": {"0": False, "1": True}}
        summary = boolean_group_summary([
            {"source_value": None, "row_count": 610},
            {"source_value": "0", "row_count": 416},
            {"source_value": "1", "row_count": 3},
            {"source_value": "S", "row_count": 2},
        ], mapping)
        self.assertEqual(summary, {
            "source": "PEP", "total_rows": 1031, "true_rows": 3, "false_rows": 416,
            "unknown_rows": 610, "invalid_rows": 2, "expected_datatable_rows": 419,
        })

    def test_reconciliation_matches_expected_pep_row(self):
        connection = Mock()

        def execute(sql, params):
            result = Mock()
            if "m_client_identifier" in sql or "m_client_address" in sql:
                result.fetchall.return_value = []
            elif "SELECT es_pep FROM credesal_client_pep" in sql:
                result.fetchone.return_value = (True,)
            return result

        connection.execute.side_effect = execute
        payload = {"core": {}, "identifiers": [], "addresses": [],
                   "datatables": {"credesal_client_pep": {"es_pep": True}}, "absent_datatables": []}
        self.assertTrue(target_payload_matches(connection, "9", payload))

    def test_reconciliation_rejects_wrong_or_missing_pep_row(self):
        for actual in ((False,), None):
            with self.subTest(actual=actual):
                connection = Mock()

                def execute(sql, params):
                    result = Mock()
                    if "m_client_identifier" in sql or "m_client_address" in sql:
                        result.fetchall.return_value = []
                    elif "SELECT es_pep FROM credesal_client_pep" in sql:
                        result.fetchone.return_value = actual
                    return result

                connection.execute.side_effect = execute
                payload = {"core": {}, "identifiers": [], "addresses": [],
                           "datatables": {"credesal_client_pep": {"es_pep": True}},
                           "absent_datatables": []}
                self.assertFalse(target_payload_matches(connection, "9", payload))

    def test_reconciliation_matches_expected_absent_pep_row(self):
        connection = Mock()

        def execute(sql, params):
            result = Mock()
            if "m_client_identifier" in sql or "m_client_address" in sql:
                result.fetchall.return_value = []
            elif "SELECT 1 FROM credesal_client_pep" in sql:
                result.fetchone.return_value = None
            return result

        connection.execute.side_effect = execute
        payload = {"core": {}, "identifiers": [], "addresses": [], "datatables": {},
                   "absent_datatables": ["credesal_client_pep"]}
        self.assertTrue(target_payload_matches(connection, "9", payload))

    def test_reconciliation_rejects_unexpected_pep_row(self):
        connection = Mock()

        def execute(sql, params):
            result = Mock()
            if "m_client_identifier" in sql or "m_client_address" in sql:
                result.fetchall.return_value = []
            elif "SELECT 1 FROM credesal_client_pep" in sql:
                result.fetchone.return_value = (1,)
            return result

        connection.execute.side_effect = execute
        payload = {"core": {}, "identifiers": [], "addresses": [], "datatables": {},
                   "absent_datatables": ["credesal_client_pep"]}
        self.assertFalse(target_payload_matches(connection, "9", payload))


if __name__ == "__main__":
    unittest.main()
