import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from arissto_sync.family_references import (
    FamilyReferenceContract,
    FamilyReferenceDataIssue,
    normalize_relationship,
    normalize_slot,
)


CONFIG = Path(__file__).resolve().parents[1] / "config" / "client_family_references.json"


class FamilyReferenceContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = FamilyReferenceContract.load(CONFIG)
        labels = set(self.contract.relationships.values())
        self.relationship_ids = {normalize_relationship(label): index for index, label in enumerate(sorted(labels), 1)}

    def row(self, **changes):
        value = {
            "affiliation_number": "C0001",
            "reference_slot": Decimal("2"),
            "full_name": "  ANA   MARIA  ",
            "primary_phone": " 2222-2222 ",
            "secondary_phone": " ",
            "address": "  San Salvador  ",
            "source_relationship": "MAMÁ",
        }
        value.update(changes)
        return value

    def test_source_and_target_identity_are_stable(self):
        row = self.row()
        self.assertEqual(self.contract.source_key(row), "C0001:2")
        self.assertEqual(self.contract.external_id(row), "arissto:afi_ref_familiar:C0001:2")

    def test_relationship_variants_are_accent_and_case_insensitive(self):
        self.assertEqual(self.contract.relationship_label(" mamá "), "Padre/Madre")
        self.assertEqual(self.contract.relationship_label("CONYUGUE"), "Esposo(a)/Pareja")
        self.assertEqual(self.contract.relationship_label(None), "Sin especificar")

    def test_payload_preserves_source_without_inventing_unknowns(self):
        payload = self.contract.payload(self.row(), self.relationship_ids)
        self.assertEqual(payload["firstName"], "ANA MARIA")
        self.assertEqual(payload["mobileNumber"], "2222-2222")
        self.assertIsNone(payload["secondaryMobileNumber"])
        self.assertEqual(payload["address"], "San Salvador")
        self.assertEqual(payload["sourceRelationship"], "MAMÁ")
        for field in ("lastName", "genderId", "isDependent", "age", "dateOfBirth", "professionId"):
            self.assertIsNone(payload[field])

    def test_invalid_slot_and_unmapped_relationship_are_rejected(self):
        for value in ("0", "1.5", "abc"):
            with self.assertRaises(FamilyReferenceDataIssue):
                normalize_slot(value)
        with self.assertRaisesRegex(FamilyReferenceDataIssue, "unresolved_relationship"):
            self.contract.relationship_label("relationship not in contract")

    def test_contract_rejects_duplicate_normalized_mapping(self):
        raw = CONFIG.read_text(encoding="utf-8").replace(
            '"Sin especificar": [""]', '"Sin especificar": [""], "Other": ["MAMA"]'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.json"
            path.write_text(raw, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate relationship mapping"):
                FamilyReferenceContract.load(path)


if __name__ == "__main__":
    unittest.main()
