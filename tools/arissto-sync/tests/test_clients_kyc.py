import json
import tempfile
import unittest
from pathlib import Path

from arissto_sync.clients import ClientContract, ClientDataIssue, TargetCatalogs


class ClientKycContractTests(unittest.TestCase):
    def contract(self):
        config = {
            "source": {"table": "AFI_SOCIO", "company_key": "ID_EMPRESA", "branch_key": "ID_SUCURSAL",
                       "party_key": "ID_SOCIO", "status_key": "STATUS"},
            "core": {
                "firstname": {"source": "NAME", "type": "text", "disposition": "migrate",
                              "ownership": "legacy-owned", "required": True},
                "mobileNo": {"source": "PHONE", "type": "text", "disposition": "migrate",
                             "ownership": "legacy-owned"},
                "emailAddress": {"source": "EMAIL", "type": "email", "disposition": "migrate",
                                 "ownership": "legacy-owned"},
                "genderId": {"source": "SEX", "type": "gender-code", "catalog": "Gender",
                             "value_map": {"1": "masculino"}, "disposition": "migrate",
                             "ownership": "legacy-owned"},
            },
            "identifiers": {
                "DUI": {"source": "DUI", "type": "text", "document_type": "Id", "source_unique": False,
                        "disposition": "migrate", "ownership": "legacy-owned"},
                "NIT": {"source": "NIT", "type": "text", "document_type": "NIT", "source_unique": True,
                        "disposition": "migrate", "ownership": "legacy-owned"}
            },
            "addresses": {
                "home": {"address_type": "Hogar", "fields": {
                    "city": {"source": "MUNICIPALITY", "type": "municipality-name", "disposition": "migrate",
                             "ownership": "legacy-owned"},
                    "isActive": {"value": True, "type": "boolean", "disposition": "derived",
                                 "ownership": "legacy-owned"},
                }}
            },
            "datatables": {
                "credesal_client_datos_personales": {
                    "estado_civil": {"source": "CIVIL", "type": "catalog-label", "catalog": "MARITAL STATUS",
                                     "disposition": "migrate", "ownership": "legacy-owned"}
                },
                "credesal_client_pep": {
                    "es_pep": {"source": "PEP", "type": "boolean", "value_map": {"0": False, "1": True},
                               "disposition": "migrate",
                               "ownership": "legacy-owned"}
                },
            },
            "reconcile_absent_datatables": ["credesal_client_pep"],
            "status": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clients.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            return ClientContract.load(path)

    def catalogs(self):
        return TargetCatalogs(
            code_values={("MARITAL STATUS", "01"): (81, "CASADO(A)")},
            named_values={("gender", "masculino"): 24, ("customer identifier", "id"): 2,
                          ("customer identifier", "nit"): 919,
                          ("address_type", "hogar"): 16},
            countries={}, departments={},
            municipalities={"0101": {"name": "AHUACHAPAN", "district": "Ahuachapán", "postal_code": "CP 2101"}},
            activities={}, address_enabled=True, signature="catalogs",
        )

    def row(self, **changes):
        row = {"ID_EMPRESA": "001", "ID_SUCURSAL": "001", "ID_SOCIO": "1", "STATUS": "001",
               "NAME": " Ana ", "PHONE": "2222-2222", "EMAIL": "ana@example.test", "SEX": "1",
               "DUI": "00000000-0", "__duplicate_DUI": 1, "NIT": None, "__duplicate_NIT": 0,
               "MUNICIPALITY": "0101", "CIVIL": "01", "PEP": None}
        row.update(changes)
        return row

    def test_payload_resolves_catalogs_and_skips_all_null_datatable(self):
        payload = self.contract().payload(self.row(), self.catalogs())
        self.assertEqual(payload["core"]["genderId"], 24)
        self.assertEqual(payload["core"]["mobileNo"], "2222-2222")
        self.assertEqual(payload["identifiers"][0]["documentTypeId"], 2)
        self.assertEqual(payload["addresses"][0]["city"], "AHUACHAPAN")
        self.assertEqual(payload["datatables"]["credesal_client_datos_personales"]["estado_civil"], "CASADO(A)")
        self.assertNotIn("credesal_client_pep", payload["datatables"])
        self.assertEqual(payload["absent_datatables"], ["credesal_client_pep"])

    def test_blank_pep_is_unknown_and_omits_datatable(self):
        payload = self.contract().payload(self.row(PEP="  "), self.catalogs())
        self.assertNotIn("credesal_client_pep", payload["datatables"])
        self.assertEqual(payload["absent_datatables"], ["credesal_client_pep"])

    def test_explicit_false_pep_creates_false_datatable_row(self):
        payload = self.contract().payload(self.row(PEP="0"), self.catalogs())
        self.assertEqual(payload["datatables"]["credesal_client_pep"], {"es_pep": False})
        self.assertEqual(payload["absent_datatables"], [])

    def test_explicit_true_pep_creates_true_datatable_row(self):
        payload = self.contract().payload(self.row(PEP="1"), self.catalogs())
        self.assertEqual(payload["datatables"]["credesal_client_pep"], {"es_pep": True})
        self.assertEqual(payload["absent_datatables"], [])

    def test_unrecognized_pep_value_is_quarantined(self):
        with self.assertRaisesRegex(ClientDataIssue, "^invalid_boolean$"):
            self.contract().payload(self.row(PEP="S"), self.catalogs())

    def test_pep_payload_contains_only_approved_destination(self):
        values = self.contract().payload(self.row(PEP="1"), self.catalogs())["datatables"]["credesal_client_pep"]
        self.assertEqual(set(values), {"es_pep"})

    def test_pep_unknown_false_and_true_have_distinct_hashes(self):
        contract, catalogs = self.contract(), self.catalogs()
        hashes = {contract.hash_row(self.row(PEP=value), catalogs) for value in (None, "0", "1")}
        self.assertEqual(len(hashes), 3)

    def test_duplicate_phone_is_not_a_data_issue(self):
        first = self.contract().payload(self.row(ID_SOCIO="1"), self.catalogs())
        second = self.contract().payload(self.row(ID_SOCIO="2"), self.catalogs())
        self.assertEqual(first["core"]["mobileNo"], second["core"]["mobileNo"])

    def test_duplicate_dui_is_preserved(self):
        payload = self.contract().payload(self.row(__duplicate_DUI=2), self.catalogs())
        self.assertEqual(payload["identifiers"][0]["documentKey"], "00000000-0")

    def test_other_duplicate_identifier_is_still_quarantined(self):
        with self.assertRaisesRegex(ClientDataIssue, "duplicate_source_identifier:NIT"):
            self.contract().payload(self.row(NIT="0614-000000-000-0", __duplicate_NIT=2), self.catalogs())

    def test_malformed_email_is_omitted(self):
        payload = self.contract().payload(self.row(EMAIL="not-an-email"), self.catalogs())
        self.assertIsNone(payload["core"]["emailAddress"])

    def test_zero_economic_activity_is_treated_as_missing(self):
        catalogs = self.catalogs()
        self.assertIsNone(catalogs.activity(0))
        self.assertIsNone(catalogs.activity("0"))

    def test_unknown_nonzero_economic_activity_is_quarantined(self):
        with self.assertRaisesRegex(ClientDataIssue, "^unresolved_catalog:economic_activity$"):
            self.catalogs().activity(999999)


if __name__ == "__main__":
    unittest.main()
