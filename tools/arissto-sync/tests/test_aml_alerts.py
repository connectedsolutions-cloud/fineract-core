import json
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from arissto_sync.aml_alerts import (
    AmlAlertContract,
    _alert_query,
    _normalize_record,
    _write_batch,
    extract_aml_alerts,
)
from arissto_sync.sql_writer import SqlWritePolicy


CONFIG = Path(__file__).resolve().parents[1] / "config" / "aml_alerts.json"


def alert_row(**changes):
    row = {
        "ID_EVENTO": 500,
        "EVENTO": "Alerta de prueba",
        "DT_EVENTO": datetime(2026, 8, 22, 10, 11, 12, 123000),
        "TIPO_PRODUCTO": "3",
        "REF_CUENTA": "LOAN-1",
        "ID_USR_CREO": "USR1",
        "ID_USR_MOD": None,
        "DT_CREO": datetime(2026, 8, 22, 10, 11, 13),
        "DT_MOD": None,
        "ID_ASOCIADO": 42,
        "ID_TIPO_EVENTO": 1,
        "ID_SUBTIPO_EVENTO": 69,
        "ID_ESTADO_EVENTO": 1,
        "ID_REFERENCIA": None,
        "ID_TIPO_ALERTA": 3,
        "FECHA_EVENTO": datetime(2026, 8, 22),
        "TEMPORAL": False,
        "NUMERO_COMPROBANTE": None,
        "ID_SUCURSAL": "001",
        "CODIGO_SISTEMA": Decimal("2"),
        "ID_TRANSACCION": "PAY",
        "MONTO": Decimal("125.50"),
        "ID_PERSONA": None,
        "ID_TIPO_PAGO": None,
        "FECHA_ENVIO_REPORTE": None,
        "DECLARACION_JURADA": None,
        "ID_FUENTE_ING": None,
        "ID_ACT_ECONOMICA": None,
        "__owner_external_id": "0000000042",
        "__relationship_state_id": "003",
        "__subtype_message": "Subtype 69",
        "__catalog_event_type_code": 1,
    }
    row.update(changes)
    return row


def movement_row(**changes):
    row = {
        "ID_EVE_MOVIMIENTOS": 900,
        "ID_APO_MOVIMIENTO": None,
        "ID_AHO_MOVIMIENTO": None,
        "ID_CRD_MOVIMIENTO": 700,
        "ID_EVENTO": 500,
    }
    row.update(changes)
    return row


class AmlAlertContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = AmlAlertContract.load(CONFIG)

    def test_contract_covers_only_reviewed_primary_alerts(self):
        self.assertEqual(self.contract.included_subtypes, [69, 70])
        self.assertEqual(self.contract.raw["type_map"], {"69": "ARISSTO_69", "70": "ARISSTO_70"})
        self.assertEqual(self.contract.raw["target"]["batch_size"], 500)

    def test_contract_rejects_unsafe_source_identifier(self):
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["source"]["alert_table"] = "EVE_EVENTO; DELETE"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aml.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                AmlAlertContract.load(path)

    def test_scoped_source_query_is_parameterized(self):
        sql, params = _alert_query(self.contract, ["500", "501"])
        self.assertIn("e.[ID_EVENTO] IN (?,?)", sql)
        self.assertNotIn("500", sql)
        self.assertEqual(params[-2:], (500, 501))

    def test_normalization_maps_client_and_preserves_all_movement_references(self):
        movements = [movement_row(ID_APO_MOVIMIENTO=11, ID_AHO_MOVIMIENTO=22)]
        record = _normalize_record(self.contract, alert_row(), movements)
        self.assertEqual(record["source_key"], "500")
        self.assertEqual(record["type_code"], "ARISSTO_69")
        self.assertEqual(record["subject"]["subject_type"], "CLIENT")
        self.assertEqual(record["subject"]["client_external_id"], "0000000042")
        self.assertEqual(record["triggering_amount"], Decimal("125.50"))
        self.assertEqual(len(record["references"]), 3)
        self.assertEqual({item["source_entity_type"] for item in record["references"]}, {
            "MOV_APORTACIONES", "AHO_MOVIMIENTOS", "CRD_MOVIMIENTOS_CARTERA",
        })
        self.assertEqual(record["payload"]["ID_EVENTO"], 500)
        self.assertNotIn("__owner_external_id", record["payload"])
        self.assertEqual(record["issues"], [])

    def test_membership_role_and_child_changes_affect_hash(self):
        client = _normalize_record(self.contract, alert_row(), [movement_row()])
        member = _normalize_record(
            self.contract,
            alert_row(__relationship_state_id="001"),
            [movement_row(ID_CRD_MOVIMIENTO=701)],
        )
        self.assertEqual(member["subject"]["subject_type"], "MEMBERSHIP")
        self.assertNotEqual(client["source_hash"], member["source_hash"])

    @patch("arissto_sync.aml_alerts.select_rows")
    def test_full_extraction_uses_one_header_and_one_movement_query(self, selected):
        selected.side_effect = [[alert_row()], [movement_row()]]
        records = extract_aml_alerts(Mock(), self.contract)
        self.assertEqual(len(records), 1)
        self.assertEqual(selected.call_count, 2)

    def test_direct_sql_policy_is_narrow(self):
        SqlWritePolicy.assert_allowed("aml-alerts", "upsert_aml_alerts")
        with self.assertRaises(PermissionError):
            SqlWritePolicy.assert_allowed("aml-alerts", "delete_aml_alert")

    def test_batch_writer_uses_upserts_and_no_delete(self):
        record = _normalize_record(self.contract, alert_row(), [movement_row()])
        action = {
            "source_key": "500", "source_hash": record["source_hash"], "action": "create",
            "alert_type_id": "9", "client_id": "42",
        }
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        connection = Mock()
        connection.cursor.return_value = cursor
        recovered = Mock()
        recovered.fetchall.return_value = [(101, "500")]
        connection.execute.return_value = recovered

        result = _write_batch(connection, self.contract, [(action, record)])

        self.assertEqual(result, {"500": "101"})
        statements = "\n".join(call.args[0] for call in cursor.executemany.call_args_list)
        self.assertIn("ON CONFLICT", statements)
        self.assertNotIn("DELETE", statements.upper())
        self.assertIn("WHERE NOT EXISTS", statements)


if __name__ == "__main__":
    unittest.main()
