import unittest

from arissto_sync.carry_forward_boundary import CarryForwardBoundary
from arissto_sync.carry_forward_ownership import inventory_counts


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class _Connection:
    def __init__(self, surfaces, counts):
        self.surfaces = surfaces
        self.counts = counts

    def execute(self, query, params=None):
        if params is None:
            return _Rows(self.surfaces)
        table = query.as_string().split('FROM "')[1].split('"')[0]
        return _Rows([(self.counts.get(table, 0),)])


class CarryForwardOwnershipTests(unittest.TestCase):
    def test_inventory_counts_newly_owned_interval_and_blocks_unreviewed_events(self):
        boundary = CarryForwardBoundary.select("2026-10-06", "2026-10-08")
        surfaces = (("m_loan_transaction", "transaction_date"),
                    ("acc_gl_journal_entry", "entry_date"))
        conn = _Connection(surfaces, {"acc_gl_journal_entry": 2})
        report = inventory_counts(conn, boundary, surfaces)
        self.assertEqual(report["interval_start_inclusive"], "2026-10-06")
        self.assertEqual(report["interval_end_inclusive"], "2026-10-08")
        self.assertEqual(report["known_interval_event_count"], 2)
        self.assertIn("unreviewed_interval_events:acc_gl_journal_entry", report["blockers"])
        self.assertFalse(report["ready_for_replacement"])

    def test_missing_event_surface_fails_closed(self):
        boundary = CarryForwardBoundary.select("2026-10-06", "2026-10-06")
        report = inventory_counts(_Connection([], {}), boundary,
                                  (("m_loan_transaction", "transaction_date"),))
        self.assertEqual(report["blockers"],
                         ["missing_event_surface:m_loan_transaction.transaction_date"])


if __name__ == "__main__":
    unittest.main()
