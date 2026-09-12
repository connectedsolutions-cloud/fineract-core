import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arissto_sync.cli import parser
from arissto_sync.loan_debug import debug_loan_run


class LoanDebugTests(unittest.TestCase):
    def test_cli_accepts_read_only_debug_report_options(self):
        args = parser().parse_args([
            "debug-loans", "--target", "local", "--run", "run-1",
            "--source-key", "1", "--source-key", "loan:3", "--report", "/tmp/report.json",
        ])
        self.assertEqual(args.command, "debug-loans")
        self.assertEqual(args.source_key, ["1", "loan:3"])
        self.assertFalse(args.include_clean)

    def test_report_includes_fineract_events_and_chain_dispositions(self):
        predecessor = {
            "source_key": "loan:1", "entity_type": "loan", "external_id": "ARISSTO:CRD:1",
            "action": "recover-loan", "depends_on": ["product:00010"],
            "lifecycle": {
                "expected": {"source_state": "3", "principal_balance": "0", "total_outstanding": "0"},
                "events": [{
                    "role": "native-refinance-payoff", "source_movement_id": "91",
                    "external_id": "ARISSTO:CRD-MOV:91", "date": "2026-01-01", "amount": "100",
                    "allocation": {"principal": "100", "interest": "0", "fee": "0", "penalty": "0"},
                    "successor_source_key": "99",
                }],
            },
        }
        successor = {
            "source_key": "loan:99", "entity_type": "loan", "external_id": "ARISSTO:CRD:99",
            "action": "quarantine-loan", "depends_on": ["product:00010", "loan:1"],
            "quarantine_reasons": ["cross_client_refinance_requires_authorization"],
            "lifecycle": {"expected": {}, "events": []},
        }
        alias = {
            "source_key": "loan:3", "entity_type": "loan", "external_id": "ARISSTO:CRD:3",
            "action": "recover-loan", "depends_on": ["product:00010"],
            "lifecycle": {
                "expected": {"source_state": "3", "principal_balance": "0", "total_outstanding": "0"},
                "events": [{
                    "role": "disbursement", "source_movement_id": "30",
                    "external_id": "ARISSTO:CRD-MOV:30", "date": "2026-01-01", "amount": "25",
                    "allocation": {"principal": "25", "interest": "0", "fee": "0", "penalty": "0"},
                }],
            },
        }
        state = MagicMock()
        state.run.return_value = {
            "id": "run-1", "plan_id": "plan-1", "block": "loans", "target_fingerprint": "fp",
        }
        state.plan.return_value = {
            "id": "plan-1", "contract_hash": "old", "document": {"actions": [predecessor, successor, alias]},
        }
        state.run_items.return_value = [
            {"source_key": "loan:1", "status": "recovered", "target_id": "10"},
            {"source_key": "loan:99", "status": "quarantined", "error_code": "cross_client_refinance_requires_authorization"},
            {"source_key": "loan:3", "status": "succeeded", "target_id": "30"},
        ]
        settings = SimpleNamespace(target=SimpleNamespace(pg_url="postgresql://local", name="local", fingerprint="fp"))
        contract = SimpleNamespace(digest="new")
        connection = MagicMock()
        connection.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[
                (10, "ARISSTO:CRD:1", 300, 100, 0, 0, 0, 100),
                (30, "ARISSTO:CRD:3", 600, 0, 0, 0, 0, 0),
            ])),
            MagicMock(fetchall=MagicMock(return_value=[
                (30, 300, "ARISSTO:CRD-MOV:30:REFINANCE:2", None, 1, "2026-01-01", 25,
                 25, 0, 0, 0, False, True),
            ])),
        ]

        @contextmanager
        def connection_context(_url):
            yield connection

        with patch("arissto_sync.loan_debug.postgres_connection", connection_context):
            report = debug_loan_run(settings, state, contract, "run-1")

        self.assertTrue(report["read_only"])
        self.assertTrue(report["contract_changed"])
        self.assertEqual(report["affected_loan_count"], 2)
        self.assertEqual(report["mismatch_counts"], {
            "terminal_status": 1, "principal_balance": 1, "cutover_total": 1,
            "transaction_missing": 2,
        })
        dispositions = {row["source_key"]: row["suggested_disposition"] for row in report["loans"]}
        self.assertEqual(dispositions["loan:1"], "review-or-quarantine-refinance-chain")
        self.assertEqual(dispositions["loan:3"], "fix-reconciliation-identity")
        alias_event = next(row for row in report["loans"] if row["source_key"] == "loan:3")
        self.assertEqual(alias_event["planned_events"][0]["diagnostic_match"], "refinance-disbursement-alias")
        self.assertEqual(alias_event["fineract_events"][0]["amount"], 25)


if __name__ == "__main__":
    unittest.main()
