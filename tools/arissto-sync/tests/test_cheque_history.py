from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from datetime import date
from decimal import Decimal

from arissto_sync.cheque_history import Link, _comparison, _make_cheque, _with_target_links, build_plan, apply_plan
from arissto_sync.sql_writer import SqlWritePolicy


class ChequeHistoryTest(unittest.TestCase):
    def setUp(self):
        self.fact = {
            "source_id": 21, "cheque_number": "  CH-007 ", "bank_name": "  Bank  ",
            "amount": Decimal("31.2"), "cheque_date": date(2026, 9, 17), "cancelled": None,
        }

    def test_same_number_is_not_cheque_identity_and_multiple_links_are_preserved(self):
        cashier = Link("COMBINED_PAYMENT", "33")
        loan = Link("LOAN_MOVEMENT", "441")
        first = _make_cheque("received", self.fact, [cashier, loan])
        second = _make_cheque("received", {**self.fact, "source_id": 22}, [])
        self.assertEqual(first.number, "CH-007")
        self.assertEqual(first.amount, "31.20")
        self.assertEqual(first.bank, "Bank")
        self.assertNotEqual(first.key, second.key)
        self.assertEqual({link.relationship_type for link in first.links}, {"COMBINED_PAYMENT", "LOAN_MOVEMENT"})

    def test_target_link_can_resolve_later_without_changing_source_hash(self):
        cheque = _make_cheque("received", self.fact, [Link("LOAN_MOVEMENT", "441")])
        target = _with_target_links([cheque], {("LOAN_MOVEMENT", "441"): ("loan_transaction", "5|7|9")})[0]
        self.assertEqual(target.source_hash, cheque.source_hash)
        existing = {cheque.key: (3, cheque.source_hash, "fp", cheque.links,
                                 cheque.number, cheque.bank, cheque.amount, cheque.cheque_date, cheque.cancelled)}
        self.assertEqual(len(_comparison([target], existing, "fp")["link_updates"]), 1)

    def test_changed_cheque_facts_and_missing_source_link_fail_closed(self):
        cheque = _make_cheque("issued", {**self.fact, "cancelled": "0"}, [Link("GL_LINE", "1|2|3|4|5")])
        existing = {cheque.key: (3, cheque.source_hash, "fp", cheque.links,
                                 cheque.number, cheque.bank, "999.00", cheque.cheque_date, cheque.cancelled)}
        self.assertEqual(_comparison([cheque], existing, "fp")["conflicts"], 1)
        existing[cheque.key] = (3, cheque.source_hash, "fp", (), cheque.number,
                                cheque.bank, cheque.amount, cheque.cheque_date, cheque.cancelled)
        self.assertEqual(_comparison([cheque], existing, "fp")["conflicts"], 1)

    def test_workflow_plan_preserves_frozen_accounting_binding(self):
        state = Mock()
        state.accounting_cutoff = {
            "date": "2026-10-08", "source_through_date": "2026-10-07",
            "configuration_hash": "frozen-hash",
        }
        state.save_plan.return_value = "plan-id"
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="local-fp"),
                                   source=SimpleNamespace())
        with patch("arissto_sync.cheque_history.inspect", return_value={"conflict_count": 0}), patch(
            "arissto_sync.cheque_history.source_fingerprint", return_value="source-fp"
        ):
            self.assertEqual(build_plan(settings, state, "2026-10-07")[0], "plan-id")
            with self.assertRaisesRegex(RuntimeError, "frozen workflow"):
                build_plan(settings, state, "2026-10-08")
        state.set_accounting_source_through.assert_not_called()

    def test_testing_phase_rejects_production_apply(self):
        target = SimpleNamespace(name="prod", fingerprint="prod-fp",
                                 assert_expected_host=Mock())
        settings = SimpleNamespace(target=target)
        with patch("arissto_sync.cheque_history._plan", return_value={"block": "cheque-history"}):
            with self.assertRaisesRegex(RuntimeError, "local acceptance testing"):
                apply_plan(settings, Mock(), "plan-id", "prod-fp")

    def test_direct_sql_is_limited_to_cheque_metadata_operation(self):
        SqlWritePolicy.assert_allowed("cheque-history", "insert_historical_cheque_metadata")
        with self.assertRaises(PermissionError):
            SqlWritePolicy.assert_allowed("cheque-history", "post_gl")


if __name__ == "__main__":
    unittest.main()
