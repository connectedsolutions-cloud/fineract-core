import unittest
from datetime import date
from decimal import Decimal

from arissto_sync.savings_lifecycle_proof import (
    PROOF_ACCOUNT_PREFIX,
    PROOF_PRODUCT_NAME,
    VistaCanary,
    VistaEvent,
    _proof_reference,
    _resource_id,
    build_product_payload,
    parse_canary_key,
)


class VistaLifecycleProofTests(unittest.TestCase):
    def canary(self):
        return VistaCanary(
            source_key="001:001:0000000100", company_id="001", branch_id="001",
            account_id="0000000100", line_id="00001", client_external_id="0000000039",
            opening_date=date(2025, 1, 7), annual_rate=Decimal("3.00"),
            ending_balance=Decimal("972.70"), source_gl_codes={}, events=(),
        )

    def test_canary_key_is_strict_and_safe(self):
        self.assertEqual(parse_canary_key("001:001:0000000100"), ("001", "001", "0000000100"))
        for invalid in ("1:1:100", "001|001|0000000100", "001:001:abc", "001:001:0000000100;drop"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_canary_key(invalid)

    def test_product_payload_pins_native_vista_contract(self):
        roles = (
            "savingsReferenceAccountId", "transfersInSuspenseAccountId", "incomeFromFeeAccountId",
            "incomeFromPenaltyAccountId", "feesReceivableAccountId", "penaltiesReceivableAccountId",
            "savingsControlAccountId", "interestOnSavingsAccountId", "interestPayableAccountId",
        )
        payload = build_product_payload(self.canary(), {"gl_ids": {role: index + 1 for index, role in enumerate(roles)}}, 2)
        self.assertEqual(payload["name"], PROOF_PRODUCT_NAME)
        self.assertEqual(payload["interestCalculationDaysInYearType"], 1)
        self.assertEqual(payload["interestPostingPeriodType"], 5)
        self.assertEqual(payload["interestCompoundingPeriodType"], 5)
        self.assertEqual(payload["minBalanceForInterestCalculation"], "50.00")
        self.assertFalse(payload["withHoldTax"])
        self.assertEqual(payload["taxGroupId"], 2)
        self.assertEqual(payload["accountingRule"], 3)

    def test_proof_account_uses_fresh_post_scheduler_generation(self):
        self.assertEqual("proof:arissto:vista:v13:", PROOF_ACCOUNT_PREFIX)

    def test_proof_reference_is_namespaced_from_general_migration(self):
        event = VistaEvent(
            source_key="AHO_MOVIMIENTOS|950", source_business_id="950",
            role="SAVINGS_INTEREST_POSTING", event_date=date(2025, 3, 31), amount=Decimal("1.21"),
            previous_balance=Decimal("200.00"), final_balance=Decimal("201.21"), reversed=False,
        )
        self.assertEqual("VPRF:v13:AHO_MOVIMIENTOS|950", _proof_reference(event))

    def test_transaction_resource_prefers_subresource(self):
        self.assertEqual(_resource_id({"resourceId": 7, "subResourceId": 495}, "subResourceId"), 495)
        self.assertEqual(_resource_id({"resourceId": 7}, "savingsId"), 7)


if __name__ == "__main__":
    unittest.main()
