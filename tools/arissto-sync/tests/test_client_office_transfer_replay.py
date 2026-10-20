import unittest

from arissto_sync.loans import _replay_client_office_transfer_timeline


def loan(key, events, *, refinance=None, depends_on=None):
    return {
        "source_key": f"loan:{key}",
        "client_external_id": "client-a",
        "depends_on": depends_on or [],
        "lifecycle": {"events": events, "refinance": refinance},
    }


def event(role, day, external_id):
    return {"role": role, "date": day, "external_id": external_id}


class ClientOfficeReplayTests(unittest.TestCase):
    def test_pretransfer_phase_error_identifies_loan(self):
        from arissto_sync.loans import LoanComponentApplyError

        action = loan(688, [event("disbursement", "2024-07-15", "disb-688")])

        def apply_phase(_action, _events, _finalize):
            raise RuntimeError("loan_phase_failed")

        with self.assertRaises(LoanComponentApplyError) as raised:
            _replay_client_office_transfer_timeline(
                [action], [
                    {"client_external_id": "client-a", "client_id": 1,
                     "effective_date": "2024-11-27"}
                ], apply_phase, lambda _transfer: self.fail("transfer should not run"),
            )
        self.assertEqual(raised.exception.source_key, "loan:688")

    def test_finalizes_source_closed_loan_before_transfer_active_set_check(self):
        closed = loan(688, [
            event("disbursement", "2024-07-15", "disb-688"),
            event("mobile-collection-repayment", "2024-10-16", "pay-688"),
        ])
        closed["lifecycle"]["terminal_adjustment"] = {"date": "2024-10-16"}
        active = loan(689, [event("disbursement", "2024-07-15", "disb-689")])
        calls = []
        active_at_transfer = {"loan:688", "loan:689"}

        def apply_phase(action, events, finalize):
            key = action["source_key"]
            calls.append((key, finalize))
            if finalize and key == "loan:688":
                active_at_transfer.discard(key)
            return int(key.split(":")[1]), False

        def transfer_client(_transfer):
            self.assertEqual(active_at_transfer, {"loan:689"})
            calls.append(("transfer", None))

        _replay_client_office_transfer_timeline(
            [closed, active], [
                {"client_external_id": "client-a", "client_id": 1,
                 "effective_date": "2024-11-27"}
            ], apply_phase, transfer_client,
        )
        transfer_index = calls.index(("transfer", None))
        self.assertIn(("loan:688", True), calls[:transfer_index])
        self.assertNotIn(("loan:689", True), calls[:transfer_index])
        self.assertEqual(calls.count(("loan:688", True)), 2)

    def test_does_not_finalize_loan_with_later_events_before_transfer(self):
        later = loan(1, [
            event("disbursement", "2024-07-15", "disb-1"),
            event("repayment", "2024-12-01", "pay-1"),
        ])
        later["lifecycle"]["terminal_adjustment"] = {"date": "2024-10-16"}
        calls = []

        def apply_phase(action, events, finalize):
            calls.append((action["source_key"], finalize))
            return 1, False

        _replay_client_office_transfer_timeline(
            [later], [
                {"client_external_id": "client-a", "client_id": 1,
                 "effective_date": "2024-11-27"}
            ], apply_phase, lambda _transfer: calls.append(("transfer", None)),
        )
        transfer_index = calls.index(("transfer", None))
        self.assertNotIn(("loan:1", True), calls[:transfer_index])
        self.assertIn(("loan:1", True), calls[transfer_index + 1:])

    def test_defers_finalization_when_cutover_insurance_is_pending(self):
        insured = loan(1, [event("disbursement", "2024-07-15", "disb-1")])
        insured["lifecycle"]["terminal_adjustment"] = {"date": "2024-10-16"}
        insured["lifecycle"]["cutover_insurance_charge"] = {"date": "2026-10-09"}
        calls = []

        def apply_phase(action, events, finalize):
            calls.append((action["source_key"], finalize))
            return 1, False

        _replay_client_office_transfer_timeline(
            [insured], [
                {"client_external_id": "client-a", "client_id": 1,
                 "effective_date": "2024-11-27"}
            ], apply_phase, lambda _transfer: calls.append(("transfer", None)),
        )
        transfer_index = calls.index(("transfer", None))
        self.assertNotIn(("loan:1", True), calls[:transfer_index])

    def test_does_not_finalize_other_client_in_connected_component(self):
        moving = loan(1, [event("disbursement", "2024-07-15", "disb-1")])
        other = loan(2, [event("disbursement", "2024-07-15", "disb-2")],
                     depends_on=["loan:1"])
        other["client_external_id"] = "client-b"
        other["lifecycle"]["terminal_adjustment"] = {"date": "2024-10-16"}
        calls = []

        def apply_phase(action, events, finalize):
            calls.append((action["source_key"], finalize))
            return int(action["source_key"].split(":")[1]), False

        _replay_client_office_transfer_timeline(
            [moving, other], [
                {"client_external_id": "client-a", "client_id": 1,
                 "effective_date": "2024-11-27"}
            ], apply_phase, lambda _transfer: calls.append(("transfer", None)),
        )
        transfer_index = calls.index(("transfer", None))
        self.assertNotIn(("loan:2", True), calls[:transfer_index])
        self.assertIn(("loan:2", True), calls[transfer_index + 1:])

    def test_pauses_active_loan_before_transfer_and_replays_later_refinance(self):
        predecessor = loan(1, [
            event("disbursement", "2025-01-01", "disb-1"),
            event("native-refinance-payoff", "2025-05-01", "payoff-1"),
        ])
        successor = loan(2, [event("disbursement", "2025-05-01", "disb-2")],
                         refinance={"disbursement_external_id": "disb-2", "settlements": [
                             {"predecessor_source_key": 1, "payoff_external_id": "payoff-1"}
                         ]}, depends_on=["loan:1"])
        calls = []

        def apply_phase(action, events, finalize):
            calls.append((action["source_key"], [row["external_id"] for row in events], finalize))
            return int(action["source_key"].split(":")[1]), False

        def transfer_client(transfer):
            calls.append(("transfer", transfer["effective_date"]))

        outcomes, keys = _replay_client_office_transfer_timeline(
            [predecessor, successor], [
                {"client_external_id": "client-a", "client_id": 1, "effective_date": "2025-04-01"}
            ], apply_phase, transfer_client,
        )
        self.assertEqual(keys, {"loan:1", "loan:2"})
        self.assertEqual(set(outcomes), keys)
        transfer_index = calls.index(("transfer", "2025-04-01"))
        self.assertEqual(calls[transfer_index - 1], ("loan:1", ["disb-1"], False))
        self.assertTrue(any(call[0] == "loan:2" for call in calls[transfer_index + 1:]))
        self.assertFalse(any(call[0] == "loan:2" for call in calls[:transfer_index]))

    def test_completes_pre_transfer_refinance_before_client_moves(self):
        predecessor = loan(1, [
            event("disbursement", "2025-01-01", "disb-1"),
            event("native-refinance-payoff", "2025-03-01", "payoff-1"),
        ])
        successor = loan(2, [event("disbursement", "2025-03-01", "disb-2")],
                         refinance={"disbursement_external_id": "disb-2", "settlements": [
                             {"predecessor_source_key": 1, "payoff_external_id": "payoff-1"}
                         ]}, depends_on=["loan:1"])
        calls = []

        def apply_phase(action, events, finalize):
            calls.append((action["source_key"], [row["external_id"] for row in events], finalize))
            return int(action["source_key"].split(":")[1]), False

        _replay_client_office_transfer_timeline(
            [predecessor, successor], [
                {"client_external_id": "client-a", "client_id": 1, "effective_date": "2025-04-01"}
            ], apply_phase, lambda transfer: calls.append(("transfer", transfer["effective_date"])),
        )
        transfer_index = calls.index(("transfer", "2025-04-01"))
        self.assertTrue(any(call[0] == "loan:2" and call[1] == ["disb-2"]
                            for call in calls[:transfer_index]))


class NativeTransferAdapterTests(unittest.TestCase):
    def test_active_set_mismatch_identifies_single_offending_loan(self):
        from contextlib import contextmanager
        from decimal import Decimal
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from arissto_sync.loans import (
            ClientOfficeTransferLoanMismatch, _expected_native_transfer_loan_ids,
        )

        connection = MagicMock()
        connection.execute.return_value.fetchall.return_value = [
            ("ARISSTO:CRD:688", 42, 300, Decimal("156.59")),
        ]

        @contextmanager
        def fake_postgres(_):
            yield connection

        with patch("arissto_sync.loans.postgres_connection", fake_postgres):
            with self.assertRaises(ClientOfficeTransferLoanMismatch) as raised:
                _expected_native_transfer_loan_ids(
                    SimpleNamespace(target=SimpleNamespace(pg_url="pg")),
                    {"client_id": 15, "active_source_loans": []},
                    verify_pretransfer_balance=True,
                )
        self.assertEqual(raised.exception.source_key, "loan:688")
        self.assertEqual(str(raised.exception), "client_office_transfer_active_loan_set_mismatch")

    def test_principal_mismatch_identifies_the_actual_loan(self):
        from contextlib import contextmanager
        from decimal import Decimal
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from arissto_sync.loans import (
            ClientOfficeTransferLoanMismatch, _expected_native_transfer_loan_ids,
        )

        connection = MagicMock()
        connection.execute.return_value.fetchall.return_value = [
            ("ARISSTO:CRD:921", 11, 300, Decimal("893.87")),
        ]

        @contextmanager
        def fake_postgres(_):
            yield connection

        with patch("arissto_sync.loans.postgres_connection", fake_postgres):
            with self.assertRaises(ClientOfficeTransferLoanMismatch) as raised:
                _expected_native_transfer_loan_ids(
                    SimpleNamespace(target=SimpleNamespace(pg_url="pg")),
                    {"client_id": 322, "active_source_loans": [
                        {"source_loan_id": 921, "total_balance": "895.89",
                         "principal_balance": "893.90"},
                    ]},
                    verify_pretransfer_balance=True,
                )
        self.assertEqual(raised.exception.source_key, "loan:921")
        self.assertEqual(str(raised.exception),
                         "client_office_transfer_pretransfer_principal_mismatch")

    def test_posts_exact_effective_day_and_verifies_native_pairs(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from arissto_sync.loans import _apply_native_client_office_transfer

        transfer = {
            "client_id": 15, "source_client_id": 157,
            "observed_date": "2024-11-23", "effective_date": "2024-11-27",
            "from_office_id": 1, "to_office_id": 2, "to_branch": "002",
        }
        api = MagicMock()
        connection = MagicMock()
        connection.execute.return_value.fetchall.return_value = []

        @contextmanager
        def fake_postgres(_):
            yield connection

        snapshot = [(1, None, 0, 0, []), (2, "2024-11-27", 1, 1, [])]
        with (patch("arissto_sync.loans._native_client_office_transfer_snapshot", side_effect=snapshot),
              patch("arissto_sync.loans._expected_native_transfer_loan_ids", return_value=[]) as ids,
              patch("arissto_sync.loans.postgres_connection", fake_postgres),
              patch("arissto_sync.loans._verify_native_client_office_transfer_loans") as verify,
              patch("arissto_sync.loans._with_fineract_recovery", side_effect=lambda fn, *_: fn())):
            _apply_native_client_office_transfer(
                SimpleNamespace(target=SimpleNamespace(pg_url="pg")), api, transfer,
                MagicMock(), SimpleNamespace(recovery_attempts=1)
            )
        ids.assert_called_once_with(unittest.mock.ANY, transfer, verify_pretransfer_balance=True)
        verify.assert_called_once_with(unittest.mock.ANY, transfer, [])
        api.request.assert_called_once_with(
            "POST", "clients/15", {
                "destinationOfficeId": 2, "transferDate": "2024-11-27",
                "dateFormat": "yyyy-MM-dd", "locale": "en",
                "loanTransferBalances": [],
            }, query={"command": "sourceExactProposeAndAcceptTransfer"},
            idempotency_key="ARISSTO:CLIENT-OFFICE:157:2024-11-23:002",
        )

    def test_posts_arissto_balance_even_when_native_total_includes_future_interest(self):
        from contextlib import contextmanager
        from decimal import Decimal
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from arissto_sync.loans import _apply_native_client_office_transfer

        transfer = {
            "client_id": 322, "source_client_id": 142,
            "observed_date": "2025-04-01", "effective_date": "2025-04-01",
            "from_office_id": 1, "to_office_id": 2, "to_branch": "002",
            "active_source_loans": [{
                "source_loan_id": 921, "total_balance": "895.89",
                "principal_balance": "893.88", "interest_balance": "1.47",
                "other_balance": "0.54", "penalty_balance": "0.00",
            }],
        }
        connection = MagicMock()
        connection.execute.return_value.fetchall.side_effect = [
            [("ARISSTO:CRD:921", 11, 300, Decimal("893.88"))],
            [("ARISSTO:CRD:921", 11)],
        ]

        @contextmanager
        def fake_postgres(_):
            yield connection

        api = MagicMock()
        with (patch("arissto_sync.loans._native_client_office_transfer_snapshot",
                    side_effect=[(1, None, 0, 0, [11]), (2, "2025-04-01", 1, 1, [11])]),
              patch("arissto_sync.loans.postgres_connection", fake_postgres),
              patch("arissto_sync.loans._verify_native_client_office_transfer_loans"),
              patch("arissto_sync.loans._with_fineract_recovery", side_effect=lambda fn, *_: fn())):
            _apply_native_client_office_transfer(
                SimpleNamespace(target=SimpleNamespace(pg_url="pg")), api, transfer,
                MagicMock(), SimpleNamespace(recovery_attempts=1),
            )
        payload = api.request.call_args.args[2]
        self.assertEqual(payload["loanTransferBalances"], [{
            "loanId": 11, "amount": "895.89", "principal": "893.88",
            "interest": "1.47", "fee": "0.54", "penalty": "0.00",
        }])

    def test_rejects_native_pair_with_wrong_source_balance(self):
        from contextlib import contextmanager
        from datetime import date
        from decimal import Decimal
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from arissto_sync.loans import _verify_native_client_office_transfer_loans

        transfer = {
            "effective_date": "2025-04-01", "from_office_id": 1, "to_office_id": 2,
            "active_source_loans": [{"source_loan_id": 987, "total_balance": "2905.10"}],
        }
        rows = [
            (42, "ARISSTO:CRD:987", 12, 1, date(2025, 4, 1), Decimal("2904.10"),
             Decimal("2904.10"), Decimal("0"), Decimal("0"), Decimal("0")),
            (42, "ARISSTO:CRD:987", 13, 2, date(2025, 4, 1), Decimal("2904.10"),
             Decimal("2904.10"), Decimal("0"), Decimal("0"), Decimal("0")),
        ]
        connection = MagicMock()
        connection.execute.return_value.fetchall.return_value = rows

        @contextmanager
        def fake_postgres(_):
            yield connection

        with patch("arissto_sync.loans.postgres_connection", fake_postgres):
            with self.assertRaisesRegex(RuntimeError, "source_balance_mismatch"):
                _verify_native_client_office_transfer_loans(
                    SimpleNamespace(target=SimpleNamespace(pg_url="pg")), transfer, [42]
                )


if __name__ == "__main__":
    unittest.main()
