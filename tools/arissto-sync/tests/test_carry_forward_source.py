import unittest

from arissto_sync.carry_forward_source import compare_source_candidates


def plan(source_hash="h1", lifecycle_hash="l1", **overrides):
    value = {
        "source_fingerprint": "source-a",
        "contract_hash": "contract-a",
        "migration_cutover_date": "2026-10-06",
        "applicable": True,
        "actions": [{
            "entity_type": "loan", "source_key": "loan:1", "source_hash": source_hash,
            "lifecycle_hash": lifecycle_hash, "action": "recover-loan",
            "quarantine_reasons": [],
        }],
    }
    value.update(overrides)
    return value


class CarryForwardSourceTests(unittest.TestCase):
    def test_exact_fresh_lifecycle_matches(self):
        result = compare_source_candidates(plan(), plan(), ["loan:1"])
        self.assertTrue(result["source_candidates_match"])
        self.assertEqual(result["fresh_source_unchanged"], 1)
        self.assertFalse(result["ready_for_reset"])

    def test_changed_lifecycle_or_missing_loan_fails_closed(self):
        changed = compare_source_candidates(plan(), plan(lifecycle_hash="l2"), ["loan:1"])
        self.assertEqual(changed["fresh_source_rejections"], {"source_lifecycle_changed": 1})
        missing = compare_source_candidates(plan(), plan(actions=[]), ["loan:1"])
        self.assertEqual(missing["fresh_source_rejections"], {"source_loan_missing": 1})

    def test_changed_contract_or_planner_cutover_fails_closed(self):
        fresh = plan(contract_hash="contract-b", migration_cutover_date="2026-10-07")
        result = compare_source_candidates(plan(), fresh, ["loan:1"])
        self.assertFalse(result["source_candidates_match"])
        self.assertIn("loan_contract_changed", result["fresh_source_rejections"])
        self.assertIn("planner_cutover_changed", result["fresh_source_rejections"])

    def test_fresh_quarantine_fails_even_with_matching_hash(self):
        action = plan()["actions"][0]
        fresh = plan(actions=[{**action, "action": "quarantine-loan", "quarantine_reasons": ["x"]}])
        result = compare_source_candidates(plan(), fresh, ["loan:1"])
        self.assertEqual(result["fresh_source_rejections"], {"source_loan_now_quarantined": 1})


if __name__ == "__main__":
    unittest.main()
