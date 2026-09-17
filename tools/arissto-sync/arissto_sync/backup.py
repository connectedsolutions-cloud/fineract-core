from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def backup_state(
    state_path: Path, output_dir: Path, keep_days: int = 30,
    clock: datetime | None = None,
) -> dict[str, Any]:
    if keep_days < 1:
        raise ValueError("Backup retention must be at least one day")
    source_path = state_path.resolve()
    if not source_path.is_file():
        raise ValueError(f"Sync state does not exist: {source_path}")
    destination_dir = output_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    current = clock or datetime.now(timezone.utc)
    stamp = current.strftime("%Y%m%dT%H%M%S.%fZ")
    destination = destination_dir / f"state-{stamp}.sqlite3"
    try:
        with (
            sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as source,
            sqlite3.connect(destination) as target,
        ):
            source.backup(target)
            integrity = target.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError("State backup failed SQLite integrity_check")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    os.chmod(destination, 0o600)

    cutoff = current - timedelta(days=keep_days)
    removed: list[str] = []
    for candidate in sorted(destination_dir.glob("state-*.sqlite3")):
        if candidate == destination or candidate.is_symlink() or not candidate.is_file():
            continue
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            candidate.unlink()
            removed.append(str(candidate))
    return {
        "ok": True,
        "source": str(source_path),
        "backup": str(destination),
        "bytes": destination.stat().st_size,
        "keep_days": keep_days,
        "removed": removed,
        "created_at": current.isoformat(),
    }
