import unittest
from decimal import Decimal
from pathlib import Path

from arissto_sync.native_shares import (
    NativeShareContract,
    accounting_configuration_approved,
    project_source,
    validate_approved_limits,
)
from arissto_sync.native_share_engine import _idempotency_key, _product_contracts, _product_payload, account_external_id


CONFIG = Path(__file__).resolve().parents[1] / "config" / "native_share_capital.json"


class NativeShareContractTests(unittest.TestCase):
    def test_idempotency_keys_are_stable_distinct_and_fit_fineract(self):
        identity = "f" * 64
        account_key = _idempotency_key("account", identity)
        self.assertEqual(account_key, _idempotency_key("account", identity))
        self.assertNotEqual(account_key, _idempotency_key("approve", identity))
        self.assertNotEqual(_idempotency_key("product-map", f"2|{identity}"),
                            _idempotency_key("product-map", f"3|{identity}"))
        self.assertLessEqual(len(_idempotency_key("approve-additional", identity)), 50)

    def test_contract_keeps_two_classes_and_all_release_gates(self):
        contract = NativeShareContract.load(CONFIG)
        self.assertEqual(set(contract.raw["share_classes"]), {"1", "2"})
        self.assertEqual(contract.raw["expected"]["accounts"], 57)
        self.assertIn("reconciled_native_savings_prerequisite", contract.raw["release_gates"])
        self.assertEqual(contract.raw["share_classes"]["1"]["approved_total_shares"], 6375)
        self.assertEqual(contract.raw["share_classes"]["1"]["numbering_code"], "1AC")
        self.assertEqual(contract.raw["share_classes"]["2"]["numbering_code"], "1AP")
        self.assertEqual(contract.raw["share_classes"]["1"]["approved_maximum_client_shares"], 375)
        self.assertEqual(contract.raw["share_classes"]["2"]["approved_total_shares"], 50000)
        self.assertEqual(contract.raw["share_classes"]["2"]["approved_maximum_client_shares"], 825)
        self.assertFalse(contract.raw["accounting_candidates"]["shared"]["shareSuspenseId"]["source_purchase_journal_supported"])
        self.assertFalse(contract.raw["accounting_candidates"]["COMMON"]["shareEquityId"]["source_purchase_journal_supported"])
        self.assertTrue(contract.raw["accounting_candidates"]["PREFERRED"]["shareEquityId"]["source_purchase_journal_supported"])
        self.assertEqual(contract.raw["source_journal_evidence"]["distinct_journals"], 26)
        self.assertFalse(contract.raw["source_journal_evidence"]["yield_used_by_purchase_journals"])

        products = _product_contracts(contract)
        payload = _product_payload(products["1"], {
            "shareReferenceId": 1, "shareSuspenseId": 2, "shareEquityIds": {"1": 3},
            "incomeFromFeeAccountId": 4, "paymentChannelToFundSourceMappings": [],
        })
        self.assertEqual(payload["numberingCode"], "1AC")

    def test_accounting_policy_uses_office_dimension_and_approved_native_accounts(self):
        contract = NativeShareContract.load(CONFIG)
        shared = contract.raw["accounting_candidates"]["shared"]
        self.assertEqual(shared["shareReferenceId"]["gl_code"], "1250990901")
        self.assertEqual(shared["shareSuspenseId"]["gl_code"], "2220070303")
        self.assertEqual(shared["incomeFromFeeAccountId"]["gl_code"], "6423")
        self.assertTrue(all(
            definition["approval_status"] == "approved"
            for mappings in contract.raw["accounting_candidates"].values()
            for definition in mappings.values()
        ))
        strategy = contract.raw["accounting_strategy"]
        self.assertEqual(strategy["office_dimension"], "acc_gl_journal_entry.office_id")
        self.assertEqual(strategy["canonical_cash_gl_code"], "1110010199")
        mappings = {item["source_payment_type_id"]: item for item in strategy["payment_channel_mappings"]}
        self.assertEqual(mappings[1]["gl_code"], "1110010199")
        self.assertEqual(mappings[2]["gl_code"], "1110010199")
        self.assertEqual(mappings[3]["gl_code"], "111004020101")
        self.assertEqual(mappings[4]["gl_code"], "111004020102")

    def test_accounting_gate_requires_approval_and_resolution(self):
        candidates = {"shared": {"reference": {"approval_status": "approved"}}}
        self.assertTrue(accounting_configuration_approved(
            candidates, {("shared", "reference"): True}, {1: True},
        ))
        self.assertFalse(accounting_configuration_approved(
            candidates, {("shared", "reference"): False}, {1: True},
        ))
        self.assertFalse(accounting_configuration_approved(
            {"shared": {"reference": {"approval_status": "unapproved"}}},
            {("shared", "reference"): True}, {1: True},
        ))

    def test_approved_limits_cover_subscribed_population(self):
        contract = NativeShareContract.load(CONFIG)
        totals = {
            "1": {"paid_shares": 6375, "subscribed_shares": 6375,
                  "largest_client_paid_shares": 375, "largest_client_subscribed_shares": 375},
            "2": {"paid_shares": 848, "subscribed_shares": 2048,
                  "largest_client_paid_shares": 225, "largest_client_subscribed_shares": 825},
        }
        self.assertEqual(validate_approved_limits(contract.raw["share_classes"], totals), [])

    def test_limit_validation_rejects_capacity_and_order_regressions(self):
        classes = {
            "1": {"approved_total_shares": 100, "approved_minimum_client_shares": 2,
                  "approved_nominal_client_shares": 1, "approved_maximum_client_shares": 50,
                  "capacity_basis": "subscribed"},
        }
        totals = {
            "1": {"paid_shares": 90, "subscribed_shares": 120,
                  "largest_client_paid_shares": 40, "largest_client_subscribed_shares": 60},
        }
        self.assertEqual(validate_approved_limits(classes, totals), [
            "total_below_subscribed:1", "invalid_order:1", "maximum_below_subscribed:1",
        ])

    def test_projection_uses_paid_not_subscribed_shares(self):
        result = project_source(
            [{"ID_ACCION": 8, "ID_ASOCIADO": 4, "ID_TIPO_ACCION": 2,
              "NUMERO_AFILIACION": "A-4", "SALDO_ACCIONES": "10.00"}],
            [{"ID_CERTIFICADO": 9, "ID_ASOCIADO": 4, "ID_TIPO_ACCION": 2,
              "ACCIONES_PAGADAS": 2, "ACCIONES_SUSCRITAS": 7}],
            [{"ID_EMPRESA": "001", "ID_SUCURSAL": "001", "ID_MOV_APORTACION": "3",
              "ID_ASOCIADO": 4, "ID_TIPO_ACCION": 2, "FECHA": "2023-02-01",
              "MONTO": "10.00", "REVERSION": "0"}],
            Decimal("5.00"),
        )
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["accounts"][0]["paid_shares"], 2)
        self.assertEqual(result["accounts"][0]["subscribed_shares"], 7)
        self.assertEqual(result["class_totals"]["2"]["paid_shares"], 2)
        self.assertEqual(result["class_totals"]["2"]["largest_client_paid_shares"], 2)
        self.assertEqual(result["class_totals"]["2"]["largest_client_subscribed_shares"], 7)

    def test_projection_rejects_non_integral_and_reversed_purchase(self):
        result = project_source(
            [{"ID_ACCION": 8, "ID_ASOCIADO": 4, "ID_TIPO_ACCION": 1,
              "NUMERO_AFILIACION": "A-4", "SALDO_ACCIONES": "7.00"}],
            [{"ID_CERTIFICADO": 9, "ID_ASOCIADO": 4, "ID_TIPO_ACCION": 1,
              "ACCIONES_PAGADAS": 1, "ACCIONES_SUSCRITAS": 1}],
            [{"ID_EMPRESA": "001", "ID_SUCURSAL": "001", "ID_MOV_APORTACION": "3",
              "ID_ASOCIADO": 4, "ID_TIPO_ACCION": 1, "FECHA": "2023-02-01",
              "MONTO": "7.00", "REVERSION": "1"}],
            Decimal("5.00"),
        )
        self.assertTrue(any(item.startswith("non_integral_purchase_shares") for item in result["issues"]))
        self.assertTrue(any(item.startswith("reversed_purchase_event") for item in result["issues"]))

    def test_account_external_id_is_stable_and_rejects_noncanonical_keys(self):
        self.assertEqual(account_external_id("AFI_ACCION|42"), "arissto:share:42")
        with self.assertRaisesRegex(ValueError, "Invalid native share account source key"):
            account_external_id("42")

    def test_product_payload_freezes_limits_accounting_and_payment_channels(self):
        contract = NativeShareContract.load(CONFIG)
        product = _product_contracts(contract)["1"]
        payload = _product_payload(product, {
            "shareReferenceId": 10, "shareSuspenseId": 20, "incomeFromFeeAccountId": 30,
            "shareEquityIds": {"1": 40, "2": 41},
            "paymentChannelToFundSourceMappings": [
                {"paymentTypeId": 4, "fundSourceAccountId": 50},
            ],
        })
        self.assertEqual(payload["externalId"], "arissto-share-common")
        self.assertEqual(payload["totalShares"], 6375)
        self.assertEqual(payload["maximumShares"], 375)
        self.assertEqual(payload["shareEquityId"], 40)
        self.assertEqual(payload["paymentChannelToFundSourceMappings"][0]["paymentTypeId"], 4)


if __name__ == "__main__":
    unittest.main()
