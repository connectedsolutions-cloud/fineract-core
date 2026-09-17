import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arissto_sync.dte_history import (
    BLOCK, SOURCE_ORIGIN, DteApplyControls, DteHistoryContract, _chunks, _payload,
    _merge_mh_config, _missing_mh_fields, _pg_database, _write_dte_batch_resilient,
    lifecycle_status, prepare_dte_history_target, source_key,
)
from arissto_sync.sql_writer import SqlWritePolicy


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "tools/arissto-sync/config/dte_history.json"
MIGRATION = ROOT / "fineract-provider/src/main/resources/db/changelog/tenant/parts/0335_add_arissto_dte_history_metadata.xml"
CHANGELOG = MIGRATION.parent.parent / "changelog-tenant.xml"
NS = {"db": "http://www.liquibase.org/xml/ns/dbchangelog"}


class DteHistoryTests(unittest.TestCase):
    def test_apply_controls_are_bounded(self):
        self.assertEqual(DteApplyControls(), DteApplyControls(workers=2, batch_size=500))
        with self.assertRaisesRegex(ValueError, "workers"):
            DteApplyControls(workers=5)
        with self.assertRaisesRegex(ValueError, "batch size"):
            DteApplyControls(batch_size=2001)

    def test_chunks_preserve_deterministic_order(self):
        self.assertEqual(list(_chunks([1, 2, 3, 4, 5], 2)), [[1, 2], [3, 4], [5]])

    def test_failed_batch_splits_until_bad_document_is_isolated(self):
        batch = [
            ({"source_key": key, "source_hash": key}, {"key": key})
            for key in ("A", "BAD", "C")
        ]

        def write(_url, values, _audit_user_id):
            if any(payload["key"] == "BAD" for _action, payload in values):
                raise RuntimeError("sensitive target detail")
            return [(action, index + 1) for index, (action, _payload) in enumerate(values)]

        with patch("arissto_sync.dte_history._write_dte_batch", side_effect=write):
            written, failed = _write_dte_batch_resilient("postgresql://target", batch, 1)

        self.assertEqual([action["source_key"] for action, _target_id in written], ["A", "C"])
        self.assertEqual(failed, [(batch[1][0], "RuntimeError:redacted")])

    def test_contract_freezes_dependencies_scope_and_write_boundary(self):
        contract = DteHistoryContract.load(CONFIG)
        self.assertEqual(BLOCK, "dte-history")
        self.assertEqual(contract.raw["depends_on"], ["clients", "loans"])
        self.assertEqual(contract.raw["scope"]["tipo_dte"], "01")
        self.assertEqual(contract.raw["missing_normal_mode"], {
            "model_type": 1,
            "operation_type": 1,
            "requires_no_contingency_signal": True,
        })
        self.assertEqual(contract.raw["write_policy"]["mh_submission"], "forbidden")
        self.assertEqual(contract.raw["write_policy"]["update"], "forbidden")
        self.assertEqual(
            contract.raw["target"]["issuer_bootstrap"]["mode"],
            "reviewed-static-identity",
        )
        SqlWritePolicy.assert_allowed(BLOCK, "create_historical_dte")
        with self.assertRaises(PermissionError):
            SqlWritePolicy.assert_allowed(BLOCK, "update_historical_dte")

    def test_mh_bootstrap_identifies_target_database_without_exposing_credentials(self):
        url = "postgresql://user:secret@localhost:5432/fineract_sandbox?sslmode=disable"
        self.assertEqual(_pg_database(url), "fineract_sandbox")

    def test_mh_required_fields_report_incomplete_issuer_without_requiring_optional_secret(self):
        complete = {
            "nit": "1", "nrc": "2", "nombre": "Issuer", "nombre_comercial": "Brand",
            "cod_actividad": "3", "desc_actividad": "Activity", "tipo_establecimiento": "01",
            "direccion_departamento": "11", "direccion_municipio": "01",
            "direccion_complemento": "Address", "telefono": "2222", "correo": "a@b.test",
            "firma_secret": None,
        }
        self.assertEqual(_missing_mh_fields(complete), [])
        complete["correo"] = " "
        self.assertEqual(_missing_mh_fields(complete), ["correo"])

    def test_mh_template_fills_missing_values_but_preserves_sandbox_overrides(self):
        template = {
            "nit": "template-nit", "nombre": "Template", "correo": "template@example.test",
        }
        current = {
            "nit": "sandbox-nit", "nombre": " ", "correo": None,
        }
        merged = _merge_mh_config(current, template)
        self.assertEqual(merged["nit"], "sandbox-nit")
        self.assertEqual(merged["nombre"], "Template")
        self.assertEqual(merged["correo"], "template@example.test")

    def test_mh_bootstrap_supports_prod_without_writing_secrets_or_correlativo(self):
        contract = DteHistoryContract.load(CONFIG)
        settings = SimpleNamespace(target=SimpleNamespace(
            name="prod", pg_url="postgresql://db.test/fineract_prod", tenant="default",
        ))
        connection = unittest.mock.MagicMock()
        manager = unittest.mock.MagicMock()
        manager.__enter__.return_value = connection
        manager.__exit__.return_value = False
        issuer = contract.raw["target"]["issuer_bootstrap"]["issuer"]

        with (
            patch("arissto_sync.dte_history._writable_postgres", return_value=manager),
            patch("arissto_sync.dte_history._mh_config", side_effect=[None, issuer]),
        ):
            report = prepare_dte_history_target(settings, contract)

        self.assertTrue(report["performed"])
        self.assertEqual(report["target_database"], "fineract_prod")
        sql = connection.execute.call_args.args[0]
        self.assertNotIn("password_pri", sql)
        self.assertNotIn("signing_api_key", sql)
        self.assertNotIn("last_dte_correlativo", sql)

    def test_contract_rejects_unsafe_identifier(self):
        value = json.loads(CONFIG.read_text())
        value["source"]["fiscal_table"] = "FAC_MOVIMIENTOS; DELETE"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "Unsafe table identifier"):
                DteHistoryContract.load(path)

    def test_generation_code_is_the_source_identity_and_all_uuid_versions_are_accepted(self):
        code = "550e8400-e29b-31d4-a716-446655440000"
        self.assertEqual(source_key({"generation_code": code}), code.upper())

    def test_source_hash_ignores_non_durable_local_ids_and_document_path(self):
        contract = DteHistoryContract.load(CONFIG)
        first = {"generation_code": "A", "projection_pk": 1, "source_document_path": "old\\path.pdf"}
        second = {"generation_code": "A", "projection_pk": 2, "source_document_path": "new\\path.pdf"}
        self.assertEqual(contract.source_hash(first), contract.source_hash(second))

    def test_lifecycle_uses_legal_evidence_not_numeric_state_alone(self):
        self.assertEqual(lifecycle_status({"annulled": "1", "reception_seal": "seal"}), "VOIDED")
        self.assertEqual(lifecycle_status({"annulled": "0", "reception_seal": "seal"}), "ACCEPTED")
        self.assertEqual(lifecycle_status({"dte_state": 3, "authority_error": "rejected"}), "REJECTED")
        self.assertIsNone(lifecycle_status({"dte_state": 2, "authority_error": "warning"}))

    def test_payload_requires_exact_client_and_loan_transaction(self):
        contract = DteHistoryContract.load(CONFIG)
        row = {
            "generation_code": "550e8400-e29b-31d4-a716-446655440000",
            "control_number": "DTE-01-00000000-000000000000001",
            "client_external_id": "123", "loan_movement_id": 9, "dte_version": 1,
            "dte_type": "01", "model_type": 1, "operation_type": 1,
            "emission_at": datetime(2025, 1, 2, 9, 30), "reception_seal": "x" * 40,
            "receiver_name": "Client", "global_fiscal_id": 1, "projection_pk": 2,
            "company_id": "001", "branch_id": "001", "fiscal_movement_id": "3", "iva_amount": 1.3,
            "lines": [{"item_number": 1, "item_type": 2, "quantity": 1,
                       "description": "Interest", "unit_price": 10}],
        }
        catalog = {"clients": {"123": 5}, "transactions": {}, "issuer": {"nombre": "Issuer"}}
        payload, issue = _payload(row, contract, catalog)
        self.assertIsNone(payload)
        self.assertEqual(issue, "missing_target_loan_transaction")
        catalog["transactions"]["ARISSTO:CRD-MOV:9"] = {"id": 7, "client_id": 6}
        self.assertEqual(_payload(row, contract, catalog)[1], "client_loan_mismatch")
        catalog["transactions"]["ARISSTO:CRD-MOV:9"]["client_id"] = 5
        payload, issue = _payload(row, contract, catalog)
        self.assertIsNone(issue)
        self.assertEqual(payload["invoice"]["loan_transaction_id"], 7)
        self.assertEqual(payload["invoice"]["source_origin"], SOURCE_ORIGIN)
        self.assertEqual(json.loads(payload["invoice"]["source_lifecycle_json"]), {
            "annulled": None, "dteState": None, "invalidated": None,
        })
        self.assertEqual(payload["summary"]["total_iva"], 1.3)
        self.assertEqual(payload["links"]["client_id"], 5)

        row["model_type"] = None
        row["operation_type"] = None
        payload, issue = _payload(row, contract, catalog)
        self.assertIsNone(issue)
        self.assertEqual(payload["invoice"]["tipo_modelo"], 1)
        self.assertEqual(payload["invoice"]["tipo_operacion"], 1)

        row["contingency_type"] = 2
        payload, issue = _payload(row, contract, catalog)
        self.assertIsNone(payload)
        self.assertEqual(issue, "missing_dte_identification")

    def test_migration_adds_minimal_native_history_metadata_without_shadow_table(self):
        self.assertIn(MIGRATION.name, CHANGELOG.read_text())
        root = ET.parse(MIGRATION).getroot()
        tables = {node.attrib["tableName"] for node in root.findall(".//db:createTable", NS)}
        self.assertEqual(tables, set())
        added = {
            node.attrib["tableName"]: {column.attrib["name"] for column in node.findall("db:column", NS)}
            for node in root.findall(".//db:addColumn", NS)
        }
        self.assertEqual(added["m_invoice"], {"source_origin", "source_hash", "source_lifecycle_json"})
        self.assertEqual(added["m_invoice_summary"], {"total_iva"})
        self.assertEqual(root.findall(".//db:addForeignKeyConstraint", NS), [])
        self.assertEqual(root.findall(".//db:insert", NS), [])
        self.assertEqual(root.findall(".//db:sql", NS), [])


if __name__ == "__main__":
    unittest.main()
