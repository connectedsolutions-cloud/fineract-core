import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.family_references import (
    PersonalFamilyReferenceContract,
    apply_family_reference_plan,
    normalize_relationship,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/client_personal_family_references.json"


class PersonalFamilyReferenceContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = PersonalFamilyReferenceContract.load(CONFIG)
        labels = set(self.contract.relationships.values())
        self.relationship_ids = {
            normalize_relationship(label): index for index, label in enumerate(sorted(labels), 1)
        }

    def test_full_query_unions_both_reviewed_sources(self):
        sql, params = self.contract.query()
        self.assertIn("AFI_REF_PERSONAL_SOCIO", sql)
        self.assertIn("AFI_FAMILIA_SOCIO", sql)
        self.assertIn("UNION ALL", sql)
        self.assertEqual(params, ())

    def test_source_identities_are_namespaced(self):
        personal = {
            "source_kind": "personal", "affiliation_number": "C0001", "reference_slot": Decimal("2")
        }
        family = {
            "source_kind": "family", "affiliation_number": "C0001", "reference_slot": "00002"
        }
        self.assertEqual(self.contract.source_key(personal), "personal:C0001:2")
        self.assertEqual(self.contract.external_id(personal), "arissto:afi_ref_personal:C0001:2")
        self.assertEqual(self.contract.source_key(family), "family:C0001:00002")
        self.assertEqual(self.contract.external_id(family), "arissto:afi_familia_socio:C0001:00002")

    def test_personal_reference_payload_uses_false_flag_and_no_invented_kinship(self):
        payload = self.contract.payload({
            "source_kind": "personal",
            "affiliation_number": "C0001",
            "reference_slot": Decimal("3"),
            "full_name": " Ana María ",
            "primary_phone": " 2222-2222 ",
            "secondary_phone": None,
            "address": " San Salvador ",
            "source_relationship": "CRÉDITO PERSONAL",
            "relationship_lookup": None,
            "is_family_member": False,
        }, self.relationship_ids)
        self.assertFalse(payload["isFamilyMember"])
        self.assertEqual(payload["sourceRelationship"], "CRÉDITO PERSONAL")
        self.assertEqual(
            payload["relationshipId"], self.relationship_ids[normalize_relationship("Sin especificar")]
        )

    def test_detailed_family_payload_uses_native_supported_fields(self):
        payload = self.contract.payload({
            "source_kind": "family",
            "affiliation_number": "C0001",
            "reference_slot": "00004",
            "full_name": "Ana",
            "last_name": "Pérez",
            "source_relationship": "MADRE",
            "relationship_lookup": "MADRE",
            "date_of_birth": datetime(1980, 5, 7),
            "is_dependent": "S",
            "is_family_member": True,
        }, self.relationship_ids)
        self.assertTrue(payload["isFamilyMember"])
        self.assertEqual(payload["lastName"], "Pérez")
        self.assertEqual(payload["dateOfBirth"], "1980-05-07")
        self.assertTrue(payload["isDependent"])

    def test_source_key_scope_selects_only_requested_table(self):
        personal_sql, personal_params = self.contract.query("personal:C0001:2")
        family_sql, family_params = self.contract.query("family:C0001:00002")
        self.assertIn("AFI_REF_PERSONAL_SOCIO", personal_sql)
        self.assertNotIn("AFI_FAMILIA_SOCIO", personal_sql)
        self.assertEqual(personal_params, ("C0001", 2))
        self.assertIn("AFI_FAMILIA_SOCIO", family_sql)
        self.assertNotIn("AFI_REF_PERSONAL_SOCIO", family_sql)
        self.assertEqual(family_params, ("C0001", "00002"))

    def test_apply_bulk_loads_source_and_target_identity_once(self):
        rows = [
            {
                "source_kind": "personal", "affiliation_number": "C0001", "reference_slot": Decimal("1"),
                "full_name": "Ana", "source_relationship": "PERSONAL", "relationship_lookup": None,
                "is_family_member": False,
            },
            {
                "source_kind": "personal", "affiliation_number": "C0002", "reference_slot": Decimal("1"),
                "full_name": "Luis", "source_relationship": "PERSONAL", "relationship_lookup": None,
                "is_family_member": False,
            },
        ]
        actions = [
            {
                "source_key": self.contract.source_key(row),
                "source_hash": self.contract.hash_row(row, self.relationship_ids),
                "action": "create",
                "target_id": None,
                "client_id": str(index),
            }
            for index, row in enumerate(rows, 1)
        ]
        plan = {
            "block": self.contract.block,
            "target_fingerprint": "local-fingerprint",
            "source_fingerprint": "source-fingerprint",
            "contract_hash": self.contract.contract_hash,
            "document": {"applicable": True, "schema_signature": "schema", "actions": actions},
        }
        state = SimpleNamespace(
            plan=lambda _plan_id: plan,
            start_run=lambda _plan: "run-1",
            record_item=MagicMock(),
            save_mapping=MagicMock(),
            finish_run=MagicMock(),
        )
        settings = SimpleNamespace(
            source=object(),
            target=SimpleNamespace(name="local", fingerprint="local-fingerprint", pg_url="postgres"),
        )
        target = MagicMock()
        target.execute.side_effect = [
            SimpleNamespace(fetchall=lambda: [(1, "C0001"), (2, "C0002")]),
            SimpleNamespace(fetchall=lambda: []),
        ]
        target_context = MagicMock()
        target_context.__enter__.return_value = target
        source_context = MagicMock()
        source_context.__enter__.return_value = object()
        api = MagicMock()
        api.create_family_member.side_effect = ["11", "12"]

        with (
            patch("arissto_sync.family_references.source_fingerprint", return_value="source-fingerprint"),
            patch(
                "arissto_sync.family_references.inspect_family_references",
                return_value={"ready": True, "schema_signature": "schema"},
            ),
            patch("arissto_sync.family_references.postgres_connection", return_value=target_context),
            patch("arissto_sync.family_references.target_relationship_ids", return_value=self.relationship_ids),
            patch("arissto_sync.family_references.source_connection", return_value=source_context),
            patch("arissto_sync.family_references.extract_family_references", return_value=rows) as extract,
            patch("arissto_sync.family_references.FineractApi", return_value=api),
        ):
            run_id, counts = apply_family_reference_plan(settings, state, self.contract, "plan-1")

        self.assertEqual(run_id, "run-1")
        self.assertEqual(counts, {"create": 2})
        extract.assert_called_once()
        self.assertEqual(api.create_family_member.call_count, 2)
        api.find_client.assert_not_called()
        api.family_members.assert_not_called()


if __name__ == "__main__":
    unittest.main()
