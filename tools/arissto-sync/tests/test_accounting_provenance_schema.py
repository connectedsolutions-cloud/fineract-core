import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "fineract-provider/src/main/resources/db/changelog/tenant/parts/0336_add_arissto_gl_journal_provenance.xml"
MASTER = ROOT / "fineract-provider/src/main/resources/db/changelog/tenant/changelog-tenant.xml"
NS = {"lb": "http://www.liquibase.org/xml/ns/dbchangelog"}


class AccountingProvenanceSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ET.parse(MIGRATION).getroot()

    def table(self, name):
        for table in self.root.findall(".//lb:createTable", NS):
            if table.attrib["tableName"] == name:
                return table
        self.fail(f"missing table {name}")

    @staticmethod
    def columns(table):
        return {column.attrib["name"]: column for column in table.findall("lb:column", NS)}

    def unique_columns(self, table_name):
        return {
            constraint.attrib["columnNames"]
            for constraint in self.root.findall(".//lb:addUniqueConstraint", NS)
            if constraint.attrib["tableName"] == table_name
        }

    def test_master_includes_versioned_migration(self):
        master = ET.parse(MASTER).getroot()
        includes = {include.attrib["file"] for include in master.findall("lb:include", NS)}
        self.assertIn("parts/0336_add_arissto_gl_journal_provenance.xml", includes)

    def test_schema_uses_the_frozen_accounting_contract_table_names(self):
        contract = json.loads((ROOT / "tools/arissto-sync/config/accounting.json").read_text(encoding="utf-8"))
        tables = {table.attrib["tableName"] for table in self.root.findall(".//lb:createTable", NS)}
        self.assertEqual(
            {contract["target"]["provenance_parent_table"], contract["target"]["provenance_line_table"]},
            tables,
        )

    def test_header_has_complete_source_and_recovery_identity(self):
        columns = self.columns(self.table("credesal_arissto_gl_journal"))
        required = {
            "provenance_schema_version",
            "source_system",
            "source_company_id",
            "source_branch_id",
            "source_period_id",
            "source_journal_id",
            "source_hash",
            "planned_hash",
            "contract_hash",
            "source_schema_signature",
            "cutoff_configuration_hash",
            "target_baseline_hash",
            "plan_id",
            "run_id",
            "target_transaction_id",
            "result",
            "reason_code",
        }
        self.assertTrue(required.issubset(columns))
        self.assertIn(
            "source_system,source_company_id,source_branch_id,source_period_id,source_journal_id",
            self.unique_columns("credesal_arissto_gl_journal"),
        )
        self.assertIn("target_transaction_id", self.unique_columns("credesal_arissto_gl_journal"))

    def test_legacy_text_values_are_independent_and_lossless(self):
        header = self.columns(self.table("credesal_arissto_gl_journal"))
        line = self.columns(self.table("credesal_arissto_gl_journal_line"))
        for name in ("source_header_concept", "source_header_description"):
            self.assertEqual("TEXT", header[name].attrib["type"])
            self.assertEqual("VARCHAR(64)", header[f"{name}_sha256"].attrib["type"])
        for name in ("source_line_concept", "source_line_aux_concept"):
            self.assertEqual("TEXT", line[name].attrib["type"])
            self.assertEqual("VARCHAR(64)", line[f"{name}_sha256"].attrib["type"])

    def test_source_and_target_precision_remain_distinct(self):
        line = self.columns(self.table("credesal_arissto_gl_journal_line"))
        self.assertEqual("DECIMAL(18,2)", line["source_amount"].attrib["type"])
        self.assertEqual("DECIMAL(19,6)", line["target_amount"].attrib["type"])
        self.assertEqual("SMALLINT", line["target_type_enum"].attrib["type"])

    def test_line_identity_cannot_duplicate_source_or_target(self):
        uniques = self.unique_columns("credesal_arissto_gl_journal_line")
        self.assertIn("journal_provenance_id,source_line_id", uniques)
        self.assertIn("journal_provenance_id,source_line_sequence", uniques)
        self.assertIn("target_journal_entry_id", uniques)

    def test_native_targets_are_foreign_keyed(self):
        targets = {
            constraint.attrib["referencedTableName"]
            for constraint in self.root.findall(".//lb:addForeignKeyConstraint", NS)
        }
        self.assertTrue(
            {
                "credesal_arissto_gl_journal",
                "acc_gl_account",
                "m_office",
                "acc_gl_journal_entry",
            }.issubset(targets)
        )


if __name__ == "__main__":
    unittest.main()
