import csv
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "fineract-provider/src/main/resources/db/changelog/tenant/parts/data/0310"


class ChartOfAccountsSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.csv_path = DATA / "chart_of_accounts.csv"
        self.migration_path = DATA.parent.parent / "0310_bootstrap_credesal_chart_of_accounts.xml"
        self.manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
        with self.csv_path.open(encoding="utf-8", newline="") as source:
            self.rows = list(csv.DictReader(source))

    def test_snapshot_matches_manifest(self):
        expected = self.manifest["files"]["chart_of_accounts.csv"]
        self.assertEqual(len(self.rows), expected["rows"])
        self.assertEqual(hashlib.sha256(self.csv_path.read_bytes()).hexdigest(), expected["sha256"])

    def test_codes_and_hierarchy_are_complete(self):
        by_code = {row["gl_code"]: row for row in self.rows}
        self.assertEqual(len(by_code), 2523)
        self.assertEqual(sum(not row["parent_gl_code"] for row in self.rows), 9)
        self.assertEqual(max(int(row["acc_level"]) for row in self.rows), 9)
        for row in self.rows:
            parent_code = row["parent_gl_code"]
            if not parent_code:
                self.assertEqual(row["acc_level"], "1")
                continue
            self.assertIn(parent_code, by_code)
            parent = by_code[parent_code]
            self.assertLess(int(parent["acc_level"]), int(row["acc_level"]))
            self.assertEqual(parent["classification_enum"], row["classification_enum"])

    def test_migration_normalizes_liquibase_blank_parent_values_before_validation(self):
        migration = self.migration_path.read_text(encoding="utf-8")
        normalization = "SET parent_gl_code = NULL"
        validation = "Credesal COA snapshot has an invalid parent hierarchy"
        self.assertIn(normalization, migration)
        self.assertLess(migration.index(normalization), migration.index(validation))


if __name__ == "__main__":
    unittest.main()
