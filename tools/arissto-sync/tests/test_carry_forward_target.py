import unittest
from datetime import date

from arissto_sync.carry_forward_target import CLOSED_STATUSES, EMPTY_DOMAIN_TABLES, REQUIRED_TABLES, classify_target, cutoff_hash
from arissto_sync.config import TargetConfig


def target(name="local", tenant="sandbox", pg_url="postgresql://localhost/fineract_sandbox"):
    return TargetConfig(name, "http://localhost:8080", "u", "p", tenant, pg_url, "localhost", False)


def counts():
    return {name: 0 for name in set(REQUIRED_TABLES) | set(EMPTY_DOMAIN_TABLES)}


def cutoff():
    value = date(2026, 10, 6)
    return value, "ACTIVE", 2, cutoff_hash(value, "ACTIVE", 2)


class CarryForwardTargetTests(unittest.TestCase):
    def test_clean_closed_only_local_seed_passes_target_preconditions(self):
        result = classify_target(target(), cutoff(),
                                 {600: 30, 601: 1}, 0, 0, counts())
        self.assertTrue(result["target_preconditions_pass"])
        self.assertFalse(result["ready_for_reset"])
        self.assertEqual(result["seed_cutoff"], "2026-10-06")

    def test_populated_tenant_fails_closed(self):
        domain_counts = counts()
        domain_counts["acc_gl_journal_entry"] = 10
        domain_counts["m_savings_account"] = 2
        result = classify_target(target(), cutoff(),
                                 {300: 1, 600: 30}, 1, 1, domain_counts)
        self.assertFalse(result["target_preconditions_pass"])
        self.assertIn("nonclosed_loans_present", result["blockers"])
        self.assertIn("loan_transactions_on_or_after_seed_cutoff", result["blockers"])
        self.assertIn("nonempty_domain:acc_gl_journal_entry", result["blockers"])

    def test_wrong_tenant_or_missing_core_table_fails_closed(self):
        domain_counts = counts()
        domain_counts["m_loan"] = None
        result = classify_target(target(tenant="default"), None,
                                 {}, 0, 0, domain_counts)
        self.assertFalse(result["target_preconditions_pass"])
        self.assertIn("not_local_sandbox", result["blockers"])
        self.assertIn("required_table_missing:m_loan", result["blockers"])
        self.assertIn("cutoff_missing", result["blockers"])

    def test_wrong_database_or_cutoff_hash_fails_closed(self):
        wrong_database = target(pg_url="postgresql://localhost/fineract_default")
        report = classify_target(wrong_database, cutoff(), {600: 1}, 0, 0, counts())
        self.assertIn("not_local_sandbox", report["blockers"])
        invalid_hash = (*cutoff()[:3], "invalid")
        report = classify_target(target(), invalid_hash, {600: 1}, 0, 0, counts())
        self.assertIn("cutoff_hash_invalid", report["blockers"])


if __name__ == "__main__":
    unittest.main()
