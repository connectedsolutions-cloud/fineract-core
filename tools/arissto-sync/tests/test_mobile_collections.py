import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from arissto_sync.mobile_collections import BLOCK, COLUMNS, TABLES, MobileCollectionContract, _payload, source_key


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT
    / "fineract-provider/src/main/resources/db/changelog/tenant/parts/0291_add_arissto_mobile_collections.xml"
)
ACCOUNT_MIGRATION = (
    ROOT
    / "fineract-provider/src/main/resources/db/changelog/tenant/parts/0303_add_mobile_collection_account_assignments.xml"
)
TENANT_CHANGELOG = MIGRATION.parent.parent / "changelog-tenant.xml"
CONTRACT = ROOT / "tools/arissto-sync/migration-services/mobile-collections/contract.md"
README = ROOT / "tools/arissto-sync/migration-services/mobile-collections/README.md"
IMPLEMENTATION_SEQUENCE = (
    ROOT / "tools/arissto-sync/migration-services/mobile-collections/implementation-sequence.md"
)
NS = {"db": "http://www.liquibase.org/xml/ns/dbchangelog"}


class MobileCollectionsSchemaTests(unittest.TestCase):
    def test_migration_is_included_and_creates_only_metadata_tables(self):
        self.assertIn(MIGRATION.name, TENANT_CHANGELOG.read_text(encoding="utf-8"))
        root = ET.parse(MIGRATION).getroot()
        tables = {node.attrib["tableName"] for node in root.findall(".//db:createTable", NS)}
        self.assertEqual(
            tables,
            {
                "credesal_mobile_collection_route",
                "credesal_mobile_collection_assignment",
                "credesal_mobile_collection_batch",
                "credesal_mobile_collection_item",
            },
        )
        self.assertEqual(root.findall(".//db:insert", NS), [])
        self.assertEqual(root.findall(".//db:sql", NS), [])

    def test_item_links_to_native_entities_but_keeps_repayment_nullable(self):
        root = ET.parse(MIGRATION).getroot()
        item = next(
            node
            for node in root.findall(".//db:createTable", NS)
            if node.attrib["tableName"] == "credesal_mobile_collection_item"
        )
        columns = {node.attrib["name"]: node for node in item.findall("db:column", NS)}
        self.assertIn("client_id", columns)
        self.assertIn("loan_id", columns)
        self.assertIn("loan_transaction_id", columns)
        self.assertNotEqual(
            columns["loan_transaction_id"].find("db:constraints", NS).attrib.get("nullable")
            if columns["loan_transaction_id"].find("db:constraints", NS) is not None
            else None,
            "false",
        )

        referenced_tables = {
            node.attrib["referencedTableName"]
            for node in root.findall(".//db:addForeignKeyConstraint", NS)
        }
        self.assertTrue({"m_client", "m_staff", "m_loan", "m_loan_transaction"} <= referenced_tables)

    def test_account_assignment_migration_preserves_exact_routed_accounts(self):
        self.assertIn(ACCOUNT_MIGRATION.name, TENANT_CHANGELOG.read_text(encoding="utf-8"))
        root = ET.parse(ACCOUNT_MIGRATION).getroot()
        tables = {node.attrib["tableName"] for node in root.findall(".//db:createTable", NS)}
        self.assertEqual(tables, {"credesal_mobile_collection_account_assignment"})

        table = root.find(".//db:createTable", NS)
        columns = {node.attrib["name"]: node for node in table.findall("db:column", NS)}
        self.assertTrue(
            {
                "arissto_account_id",
                "route_id",
                "client_id",
                "account_type",
                "loan_id",
                "savings_account_id",
                "link_status",
            }
            <= columns.keys()
        )
        referenced_tables = {
            node.attrib["referencedTableName"]
            for node in root.findall(".//db:addForeignKeyConstraint", NS)
        }
        self.assertEqual(
            referenced_tables,
            {"credesal_mobile_collection_route", "m_client", "m_loan", "m_savings_account"},
        )
        unique_columns = {
            node.attrib["columnNames"] for node in root.findall(".//db:addUniqueConstraint", NS)
        }
        self.assertEqual(unique_columns, {"arissto_account_id", "loan_id", "savings_account_id"})
        self.assertEqual(root.findall(".//db:insert", NS), [])
        self.assertEqual(root.findall(".//db:sql", NS), [])

    def test_contract_forbids_duplicate_financial_posting_and_guessed_links(self):
        contract = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("must never", contract)
        self.assertIn("call a loan repayment endpoint", contract)
        self.assertIn("create journal entries", contract)
        self.assertIn("must not be matched by amount and date alone", contract)
        self.assertIn("There is no verified Arissto route-to-batch foreign key", contract)

    def test_operator_docs_match_runtime_dependencies_and_native_route_schema(self):
        readme = README.read_text(encoding="utf-8")
        sequence = IMPLEMENTATION_SEQUENCE.read_text(encoding="utf-8")

        for document in (readme, sequence):
            self.assertIn("clients[clients] --> loans[loans]", document)
            self.assertIn("savings[savings-deposits] --> mobile", document)
            self.assertIn("loans --> mobile", document)
            self.assertIn("0305_enable_native_mobile_collection_routes.xml", document)
        self.assertIn("retry --run RUN_ID --failed-only", readme)

    def test_runtime_contract_freezes_dependencies_and_financial_boundary(self):
        contract = MobileCollectionContract.load(ROOT / "tools/arissto-sync/config/mobile_collections.json")
        self.assertEqual(BLOCK, "mobile-collections")
        self.assertEqual(contract.raw["depends_on"], ["clients", "employees", "savings-deposits", "loans"])
        self.assertEqual(contract.raw["write_policy"]["native_financial_tables"], "forbidden")
        self.assertTrue(all(table.startswith("credesal_mobile_collection_") for table in TABLES.values()))

    def test_runtime_contract_rejects_unsafe_table_identifier(self):
        config = ROOT / "tools/arissto-sync/config/mobile_collections.json"
        value = json.loads(config.read_text(encoding="utf-8"))
        value["source"]["route_table"] = "MCD_RUTA; DELETE FROM x"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mobile.json"
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "Unsafe table identifier"):
                MobileCollectionContract.load(path)

    def test_item_identity_uses_declared_five_column_primary_key(self):
        row = {"company_id": "001", "branch_id": "002", "period_id": "00073",
               "collection_id": "0000000052", "collection_item_id": "0000000024"}
        self.assertEqual(source_key("item", row), "item:001|002|00073|0000000052|0000000024")

    def test_missing_exact_repayment_is_preserved_without_guessing(self):
        contract = MobileCollectionContract.load(ROOT / "tools/arissto-sync/config/mobile_collections.json")
        catalog = {"batch_ids": {"1": 9}, "clients": {}, "loans": {}, "transactions": {}, "staff": {}}
        row = {"master_id": 1, "company_id": "001", "branch_id": "001", "period_id": "00073",
               "collection_id": "1", "collection_item_id": "1", "detail_id": 7,
               "applied": "S", "apply_requested": "S", "system_code": 14}
        payload, issue = _payload("item", row, contract, catalog)
        self.assertIsNone(issue)
        self.assertEqual(payload["link_status"], "UNRESOLVED_LEGACY")
        self.assertIsNone(payload["loan_transaction_id"])
        self.assertEqual(set(payload), set(COLUMNS["item"]))


if __name__ == "__main__":
    unittest.main()
