import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from arissto_sync.membership import (
    PROFILE_VALUE_COLUMNS,
    SUMMARY_TABLE,
    MembershipContract,
    _source_table_report,
    _summary_rows,
    _table_query,
    canonical_payload,
    _write_record,
)
from arissto_sync.sql_writer import SqlWritePolicy


CONFIG = Path(__file__).resolve().parents[1] / "config" / "membership_share_capital.json"
FINERACT_CORE = Path(__file__).resolve().parents[3]
SHARE_SUPPORT_MIGRATION = (
    FINERACT_CORE
    / "fineract-provider/src/main/resources/db/changelog/tenant/parts/0283_add_credesal_share_migration_support.xml"
)
TENANT_CHANGELOG = (
    FINERACT_CORE
    / "fineract-provider/src/main/resources/db/changelog/tenant/changelog-tenant.xml"
)


class MembershipContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = MembershipContract.load(CONFIG)

    def test_contract_covers_interpreting_catalogs_and_history(self):
        tables = {item["table"] for item in self.contract.raw["source"]["tables"]}
        self.assertTrue({
            "AFI_SOCIO", "AFI_ESTADO_SOCIO", "AFI_ESTATUS_SOCIO", "AFI_ACCION",
            "AFI_CERTIFICADO", "MOV_APORTACIONES", "OPR_OPERACIONES", "OPR_TIPO_OPERACION",
        }.issubset(tables))
        self.assertGreaterEqual(len(tables), 40)

    def test_operation_log_is_scoped_to_current_parties_and_membership_types(self):
        operations = next(
            item for item in self.contract.raw["source"]["tables"]
            if item["table"] == "OPR_OPERACIONES"
        )
        sql = _table_query(self.contract, operations)
        self.assertIn("[ID_TIPO_OPERACION] IN (4,5,6,10,60,61)", sql)
        self.assertIn("SELECT [ID_ASOCIADO] FROM [dbo].[AFI_SOCIO]", sql)
        self.assertIn("'PLUS SILVER','PLUS PLATINUM','PLUS INFINITE'", sql)

        operation_types = next(
            item for item in self.contract.raw["source"]["tables"]
            if item["table"] == "OPR_TIPO_OPERACION"
        )
        type_sql = _table_query(self.contract, operation_types)
        self.assertIn("[ID_TIPO_OPERACION] IN (4,5,6,10,60,61)", type_sql)

    def test_contract_rejects_unsafe_excluded_product(self):
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        operations = next(
            item for item in raw["source"]["tables"]
            if item["table"] == "OPR_OPERACIONES"
        )
        operations["excluded_products"] = ["PLUS'); DELETE"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "excluded products"):
                MembershipContract.load(path)

    def test_inspection_counts_the_scoped_operation_query(self):
        operations = next(
            item for item in self.contract.raw["source"]["tables"]
            if item["table"] == "OPR_OPERACIONES"
        )
        contract = MembershipContract({
            "source": {"tables": [operations], "member_relationship_states": ["001"]},
            "target": {},
        })
        columns = [
            {"column_name": "ID_OPERACION", "data_type": "bigint"},
            {"column_name": "FECHA_APERTURA", "data_type": "datetime"},
            {"column_name": "ID_TIPO_OPERACION", "data_type": "smallint"},
            {"column_name": "ID_ASOCIADO", "data_type": "int"},
            {"column_name": "TIPO_PRODUCTO", "data_type": "varchar"},
        ]
        with patch("arissto_sync.membership.select_rows", side_effect=[columns, [{"row_count": 380}]]) as selected:
            report = _source_table_report(Mock(), contract)
        self.assertEqual(report[0]["row_count"], 380)
        count_sql = selected.call_args_list[1].args[1]
        self.assertIn("FROM (SELECT * FROM [dbo].[OPR_OPERACIONES]", count_sql)
        self.assertIn("'PLUS SILVER','PLUS PLATINUM','PLUS INFINITE'", count_sql)

    def test_canonical_payload_is_lossless_and_deterministic(self):
        payload = canonical_payload({
            "money": Decimal("1.2300"), "when": datetime(2026, 8, 21, 1, 2, 3, 4),
            "day": date(2026, 8, 21), "binary": b"\x00\xff", "blank": None,
        })
        self.assertEqual(payload["money"], "1.2300")
        self.assertEqual(payload["when"], "2026-08-21T01:02:03.000004")
        self.assertEqual(payload["day"], "2026-08-21")
        self.assertEqual(payload["binary"], "00ff")
        self.assertIsNone(payload["blank"])

    def test_source_key_escapes_delimiters(self):
        table = {"table": "AFI_TEST", "keys": ["A", "B"]}
        self.assertEqual(self.contract.source_key(table, {"A": "x|y", "B": "9%"}),
                         "AFI_TEST|x%7Cy|9%25")

    def test_contract_rejects_unsafe_state_filter(self):
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        raw["source"]["member_relationship_states"] = ["001'); DELETE"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                MembershipContract.load(path)

    def test_summary_profile_uses_record_hash(self):
        result = Mock()
        result.fetchone.return_value = (17,)
        connection = Mock()
        connection.execute.return_value = result
        payload = {column: None for column in PROFILE_VALUE_COLUMNS if column != "source_hash"}
        record = {
            "source_table": SUMMARY_TABLE, "source_key": "AFI_SOCIO_SUMMARY|1",
            "record_kind": "member-summary", "parent_source_key": None,
            "effective_date": None, "payload": payload, "source_hash": "a" * 64,
        }
        self.assertEqual(_write_record(connection, self.contract, record, 9), "17")
        profile_params = connection.execute.call_args_list[1].args[1]
        hash_offset = 1 + PROFILE_VALUE_COLUMNS.index("source_hash")
        self.assertEqual(profile_params[hash_offset], "a" * 64)

    def test_summary_profile_separates_subscribed_and_paid_shares_by_class(self):
        with patch("arissto_sync.membership.select_rows", return_value=[]) as selected:
            _summary_rows(Mock(), self.contract)
        sql = selected.call_args.args[1]
        self.assertIn("common_subscribed_share_count", sql)
        self.assertIn("common_paid_share_count", sql)
        self.assertIn("preferred_subscribed_share_count", sql)
        self.assertIn("preferred_paid_share_count", sql)
        self.assertIn("ID_TIPO_ACCION=2 THEN ACCIONES_PAGADAS", sql)

    def test_share_support_migration_is_well_formed_and_registered(self):
        ET.parse(SHARE_SUPPORT_MIGRATION)
        migration = SHARE_SUPPORT_MIGRATION.read_text(encoding="utf-8")
        changelog = TENANT_CHANGELOG.read_text(encoding="utf-8")
        self.assertIn("credesal_share_certificate", migration)
        self.assertIn("credesal_share_certificate_beneficiary", migration)
        self.assertIn("credesal_share_native_event_map", migration)
        self.assertIn("common_paid_share_count", migration)
        self.assertIn("preferred_paid_share_count", migration)
        self.assertNotIn('<addColumn tableName="m_share_', migration)
        self.assertNotIn('<insert tableName="m_share_', migration)
        self.assertIn(SHARE_SUPPORT_MIGRATION.name, changelog)

    def test_direct_sql_policy_is_narrow(self):
        SqlWritePolicy.assert_allowed("membership-share-capital", "upsert_membership_archive")
        with self.assertRaises(PermissionError):
            SqlWritePolicy.assert_allowed("membership-share-capital", "delete_membership_archive")


if __name__ == "__main__":
    unittest.main()
