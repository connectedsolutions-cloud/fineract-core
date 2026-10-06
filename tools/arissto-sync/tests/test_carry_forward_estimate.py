import unittest
import json
import sqlite3
import tempfile
from pathlib import Path

from arissto_sync.carry_forward_estimate import estimate, estimate_from_state


def loan(key, *, state="3", events=(), predecessor=None, balance="0.00"):
    refinance = {"settlements": [{"predecessor_source_key": predecessor}]} if predecessor else None
    return {
        "source_key": f"loan:{key}", "entity_type": "loan", "action": "create-loan",
        "quarantine_reasons": [],
        "lifecycle": {
            "expected": {"source_state": state, "principal_balance": balance,
                         "interest_balance": "0", "penalty_balance": "0",
                         "fee_balance": "0", "total_outstanding": balance},
            "events": [{"date": value} for value in events],
            "refinance": refinance,
        },
    }


class CarryForwardEstimateTests(unittest.TestCase):
    def plan(self, actions):
        return {"scope": {"mode": "full-block", "proof_namespace": None},
                "accounting_cutoff": {"date": "2026-09-18"}, "actions": actions}

    def test_only_terminal_zero_balance_pre_cutoff_accepted_loans_are_potential(self):
        actions = [loan(1, events=["2026-09-17"]),
                   loan(2, events=["2026-09-18"]), loan(3, state="1"),
                   loan(4, balance="0.01"), loan(5)]
        statuses = {f"loan:{n}": "succeeded" for n in range(1, 5)}
        result = estimate(self.plan(actions), statuses, "2026-09-19")
        self.assertEqual(result["potential_closed_loans"], 1)
        self.assertFalse(result["ready_for_reset"])
        self.assertEqual(result["fineract_starts"], "2026-09-20")
        self.assertEqual(result["excluded_by_reason"]["event_on_or_after_old_cutoff"], 1)

    def test_refinance_component_is_excluded_together(self):
        actions = [loan(1), loan(2, state="1", predecessor=1), loan(3)]
        statuses = {f"loan:{n}": "succeeded" for n in range(1, 4)}
        result = estimate(self.plan(actions), statuses, "2026-09-18")
        self.assertEqual(result["potential_closed_loans"], 1)
        self.assertEqual(result["excluded_by_reason"]["refinance_component_not_closed"], 1)

    def test_reads_accepted_quarantine_run_without_writing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with sqlite3.connect(path) as conn:
                conn.executescript("""
                    CREATE TABLE plans (id TEXT, block TEXT, document TEXT);
                    CREATE TABLE runs (id TEXT, plan_id TEXT, status TEXT, started_at TEXT);
                    CREATE TABLE reconciliations (run_id TEXT, ok INTEGER);
                    CREATE TABLE items (run_id TEXT, source_key TEXT, status TEXT);
                """)
                conn.execute("INSERT INTO plans VALUES (?,?,?)", ("plan", "loans", json.dumps(self.plan([loan(1)]))))
                conn.execute("INSERT INTO runs VALUES (?,?,?,?)", ("run", "plan", "completed-with-quarantine", "2026-09-18"))
                conn.execute("INSERT INTO reconciliations VALUES (?,?)", ("run", 1))
                conn.execute("INSERT INTO items VALUES (?,?,?)", ("run", "loan:1", "succeeded"))
            report = estimate_from_state(path, "2026-09-18")
            self.assertEqual(report["potential_closed_loans"], 1)
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0], 1)

    def test_rejects_same_or_earlier_cutoff_and_scoped_plan(self):
        with self.assertRaisesRegex(ValueError, "later Fineract"):
            estimate(self.plan([loan(1)]), {"loan:1": "succeeded"}, "2026-09-17")
        scoped = self.plan([loan(1)])
        scoped["scope"]["mode"] = "selected-keys"
        with self.assertRaisesRegex(ValueError, "full-block"):
            estimate(scoped, {"loan:1": "succeeded"}, "2026-09-18")


if __name__ == "__main__":
    unittest.main()
