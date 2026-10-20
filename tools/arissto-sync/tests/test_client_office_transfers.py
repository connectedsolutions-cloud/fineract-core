import unittest
from datetime import date

from arissto_sync.client_office_transfers import normalize_client_office_observations


def observation(day="2024-11-23", previous="2024-11-22", current="002"):
    return {
        "source_client_id": 157,
        "client_external_id": "0000000155",
        "original_branch": "001",
        "current_branch": current,
        "previous_date": previous,
        "previous_branch": "001",
        "observed_date": day,
        "destination_branch": "002",
    }


class ClientOfficeTransferTests(unittest.TestCase):
    def test_floors_early_transfer_but_preserves_observed_day(self):
        events = normalize_client_office_observations(
            [observation()], {"001": 1, "002": 2}, {2: date(2024, 11, 27)}
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["observed_date"], "2024-11-23")
        self.assertEqual(events[0]["effective_date"], "2024-11-27")
        self.assertEqual(events[0]["date_adjustment"], "office-opening-floor")

    def test_keeps_later_transfer_day_and_rejects_snapshot_gap(self):
        events = normalize_client_office_observations(
            [observation("2025-04-01", "2025-03-31")],
            {"001": 1, "002": 2}, {2: date(2024, 11, 27)},
        )
        self.assertEqual(events[0]["effective_date"], "2025-04-01")
        self.assertIsNone(events[0]["date_adjustment"])
        with self.assertRaisesRegex(RuntimeError, "snapshot_gap"):
            normalize_client_office_observations(
                [observation("2025-04-01", "2025-03-30")],
                {"001": 1, "002": 2}, {2: date(2024, 11, 27)},
            )


if __name__ == "__main__":
    unittest.main()
