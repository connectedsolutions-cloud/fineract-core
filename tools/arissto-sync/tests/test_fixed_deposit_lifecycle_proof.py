from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.fixed_deposit_lifecycle_proof import (
    DpfCanary,
    _dpf_external_id,
    _find_rollover,
    _linked_vista_external_id,
    build_dpf_product_payload,
    parse_dpf_key,
)


class FixedDepositLifecycleProofTest(unittest.TestCase):
    def _canary(self, period: str = "06") -> DpfCanary:
        return DpfCanary(
            source_key="001:001:0000000141", company_id="001", branch_id="001", account_id="0000000141",
            line_id="00003", state="MATURED", source_status="4", client_external_id="0000000001",
            principal=Decimal("24576.25"),
            annual_rate=Decimal("10.00"), term_days=30, capitalization_period=period,
            linked_vista_key="001:001:0000000010", cancellation_date=None,
            cutoff_date=__import__("datetime").date(2026, 8, 26), cutoff_accrual=Decimal("0"), cycles=(),
            interests=(), owners=(), source_gl_codes={}, reversed_opening_pairs=0,
            opening_movement_id="1", cancellation_movement_id=None, reversed_opening_events=(),
        )

    def test_source_key_is_strict(self) -> None:
        self.assertEqual(("001", "001", "0000000141"), parse_dpf_key("001:001:0000000141"))
        with self.assertRaises(ValueError):
            parse_dpf_key("1:1:141")

    def test_contaminated_four_cycle_canary_uses_fresh_identity(self) -> None:
        canary = self._canary()
        self.assertEqual("proof:arissto:dpf:v3:001:001:0000000141", _dpf_external_id(canary))
        self.assertEqual("proof:arissto:dpf-linked-vista:v3:001:001:0000000141",
                         _linked_vista_external_id(canary))

    def test_monthly_product_uses_anchor_and_does_not_block_interest_transfers(self) -> None:
        gl_ids = {name: index for index, name in enumerate((
            "savingsReferenceAccountId", "savingsControlAccountId", "transfersInSuspenseAccountId",
            "interestOnSavingsAccountId", "interestPayableAccountId", "incomeFromFeeAccountId",
            "incomeFromPenaltyAccountId", "feesReceivableAccountId", "penaltiesReceivableAccountId",
        ), start=1)}
        payload = build_dpf_product_payload(self._canary(), {"product_name": "proof", "gl_ids": gl_ids})
        self.assertEqual(9, payload["interestPostingPeriodType"])
        self.assertEqual(9, payload["interestCompoundingPeriodType"])
        self.assertEqual(0, payload["lockinPeriodFrequency"])
        self.assertEqual(1, payload["interestCalculationDaysInYearType"])

    def test_at_maturity_product_uses_annual_boundary(self) -> None:
        roles = ("savingsReferenceAccountId", "savingsControlAccountId", "transfersInSuspenseAccountId",
                 "interestOnSavingsAccountId", "interestPayableAccountId", "incomeFromFeeAccountId",
                 "incomeFromPenaltyAccountId", "feesReceivableAccountId", "penaltiesReceivableAccountId")
        payload = build_dpf_product_payload(self._canary("04"),
                                            {"product_name": "proof", "gl_ids": {role: 1 for role in roles}})
        self.assertEqual(7, payload["interestPostingPeriodType"])

    def test_rollover_accepts_fineract_inclusive_term_end_one_day_before_source_cycle(self) -> None:
        connection = MagicMock()
        connection.execute.return_value.fetchall.return_value = [
            (76, date(2023, 9, 10), Decimal("6.00"), 39, 600, 300),
        ]
        context = MagicMock()
        context.__enter__.return_value = connection
        settings = SimpleNamespace(target=SimpleNamespace(pg_url="postgresql://local"))
        with patch("arissto_sync.fixed_deposit_lifecycle_proof.postgres_connection", return_value=context):
            self.assertEqual(76, _find_rollover(settings, 75, date(2023, 9, 11), {75}))


if __name__ == "__main__":
    unittest.main()
