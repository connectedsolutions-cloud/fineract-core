import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from arissto_sync.backup import backup_state
from arissto_sync.state import State


class BackupTests(unittest.TestCase):
    def test_creates_consistent_private_backup_and_prunes_expired_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.sqlite3"
            state = State(state_path)
            state.conn.execute("INSERT INTO state_metadata(key,value) VALUES('proof','present')")
            state.conn.commit()
            state.conn.close()
            output = root / "backups"
            output.mkdir()
            old = output / "state-20200101T000000.000000Z.sqlite3"
            old.write_bytes(b"expired")
            current = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
            old_time = (current - timedelta(days=31)).timestamp()
            os.utime(old, (old_time, old_time))

            report = backup_state(state_path, output, keep_days=30, clock=current)

            backup = Path(report["backup"])
            self.assertTrue(report["ok"])
            self.assertTrue(backup.is_file())
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertFalse(old.exists())
            with sqlite3.connect(backup) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT value FROM state_metadata WHERE key='proof'"
                    ).fetchone()[0],
                    "present",
                )

    def test_refuses_missing_state_and_invalid_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "at least one day"):
                backup_state(root / "missing.sqlite3", root / "backups", keep_days=0)
            with self.assertRaisesRegex(ValueError, "does not exist"):
                backup_state(root / "missing.sqlite3", root / "backups")


if __name__ == "__main__":
    unittest.main()
