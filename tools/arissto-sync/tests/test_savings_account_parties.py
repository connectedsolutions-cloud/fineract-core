import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from arissto_sync.savings_account_parties import (
    SavingsAccountPartyContract,
    authorized_payload,
    beneficiary_payload,
    collections,
    digest,
)


CONFIG = Path(__file__).resolve().parents[1] / "config" / "savings_account_parties.json"
FINERACT_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    FINERACT_ROOT
    / "fineract-provider/src/main/resources/db/changelog/tenant/parts/0343_add_savings_account_parties.xml"
)
TENANT_CHANGELOG = MIGRATION.parent.parent / "changelog-tenant.xml"


class SavingsAccountPartyContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = SavingsAccountPartyContract.load(CONFIG)

    def beneficiary(self, **changes):
        row = {
            "company_id": "001", "branch_id": "001", "account_id": "0000000100", "party_id": "1",
            "given_name": " Ana ", "surname": " López ", "allocation_percentage": Decimal("100.00"),
            "date_of_birth": None, "source_age": "30", "dui": "00000000-0", "relationship": "HIJA",
            "address": "San Salvador", "phone": "2222-2222", "communicate_designation": True,
        }
        row.update(changes)
        return row

    def authorized(self, **changes):
        row = {
            "company_id": "001", "branch_id": "001", "account_id": "0000000100", "party_id": "1",
            "given_name": " Ana ", "surname": " López ", "date_of_birth": None, "dui": "00000000-0",
            "relationship": "HIJA", "address": "San Salvador", "phone": "2222-2222",
            "print_on_contract": "1", "print_on_passbook": "1", "signature_reference": None,
        }
        row.update(changes)
        return row

    def test_builds_stable_source_and_external_ids(self):
        payload = beneficiary_payload(self.contract, self.beneficiary())

        self.assertEqual(
            self.contract.collection_key("001", "001", "0000000100"),
            "AHO_ACCOUNT_PARTIES|001|001|0000000100",
        )
        self.assertEqual(payload["externalId"], "ARISSTO:AHO-BEN:001:001:0000000100:1")
        self.assertEqual(payload["allocationPercentage"], "100.00")
        self.assertEqual(len(payload["sourceHash"]), 64)

    def test_authorized_person_does_not_infer_transaction_authority(self):
        payload = authorized_payload(self.contract, self.authorized())

        self.assertTrue(payload["printOnContract"])
        self.assertTrue(payload["printOnPassbook"])
        self.assertNotIn("transactionAuthority", payload)
        self.assertIsNone(payload["linkedClientId"])

    @patch("arissto_sync.savings_account_parties.extract")
    def test_quarantines_account_when_beneficiary_allocations_do_not_total_100(self, mocked_extract):
        mocked_extract.return_value = {
            "beneficiaries": [self.beneficiary(allocation_percentage=Decimal("90.00"))],
            "authorizedPersons": [],
        }

        result = collections(None, self.contract)

        self.assertEqual(result["AHO_ACCOUNT_PARTIES|001|001|0000000100"]["issue"],
                         "beneficiary_allocations_do_not_total_100")

    def test_canonical_digest_ignores_api_ids_and_numeric_json_representation(self):
        expected = beneficiary_payload(self.contract, self.beneficiary())
        actual = dict(expected, id=9, savingsAccountId=31, allocationPercentage=100.0, dateOfBirth=[1990, 1, 2])
        expected["dateOfBirth"] = "1990-01-02"
        actual.pop("sourceHash")

        self.assertEqual(digest([expected]), digest([actual]))

    def test_migration_is_registered_in_tenant_changelog(self):
        self.assertTrue(MIGRATION.exists())
        self.assertIn(MIGRATION.name, TENANT_CHANGELOG.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
