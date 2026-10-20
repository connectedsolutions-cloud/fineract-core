"""Capture a private, restorable local sandbox input without changing it.

The full PostgreSQL dump and SQLite backups are sensitive and stay under the
ignored local state directory. This command does not stage or replace a tenant.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from typing import Any

from .carry_forward_boundary import CarryForwardBoundary
from .carry_forward_target import inspect_target
from .config import Settings, load_settings
from .cycles import CYCLE_ID, cycle_catalog_path, cycle_state_path


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_backup(source: Path, destination: Path) -> None:
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dest:
            src.backup(dest)
            if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite recovery backup failed integrity check")
    destination.chmod(0o600)


def _cycle_evidence(settings: Settings, cycle_id: str) -> tuple[dict[str, Any], Path, Path]:
    if not CYCLE_ID.fullmatch(cycle_id):
        raise ValueError("Invalid cycle ID")
    catalog_path = cycle_catalog_path(settings.state_path)
    state_path = cycle_state_path(settings.state_path, cycle_id)
    if not catalog_path.is_file() or not state_path.is_file():
        raise ValueError("Cycle catalog or state is missing")
    with sqlite3.connect(catalog_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM sync_cycles WHERE id=?", (cycle_id,)).fetchone()
        if row is None or row["status"] != "open":
            raise ValueError("Carry-forward input requires the open local cycle")
        cycle = dict(row)
        if (cycle["target_name"] != "local"
                or cycle["target_fingerprint"] != settings.target.fingerprint
                or Path(cycle["state_path"]).resolve() != state_path.resolve()):
            raise ValueError("Cycle does not belong to this local sandbox lifetime")
        for other in conn.execute("SELECT state_path FROM sync_cycles WHERE target_name='local' AND purged_at IS NULL"):
            path = Path(other[0])
            if not path.is_file():
                continue
            with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as state:
                active = state.execute(
                    "SELECT COUNT(*) FROM workflow_runs WHERE status IN ('queued','running')"
                ).fetchone()[0]
                if active:
                    raise ValueError("A local workflow is queued or running")
    return cycle, state_path, catalog_path


def _require_local_stopped_target(settings: Settings, *, require_stopped: bool = True) -> tuple[Any, Any]:
    target = settings.target
    if target.name != "local" or target.tenant != "sandbox" or not target.pg_url:
        raise ValueError("Capture requires the exact local sandbox target")
    pg = urlparse(target.pg_url)
    api = urlparse(target.api_url)
    if (pg.hostname not in LOCAL_HOSTS or pg.path != "/fineract_sandbox"
            or api.hostname not in LOCAL_HOSTS):
        raise ValueError("Capture refuses remote, default, or production targets")
    if require_stopped:
        try:
            with socket.create_connection((api.hostname, api.port or 8443), timeout=0.5):
                raise ValueError("Stop the local Fineract API before input capture")
        except (ConnectionRefusedError, TimeoutError, OSError):
            pass
    return pg, api


def _dump_database(pg: Any, output: Path) -> None:
    env = os.environ.copy()
    if pg.password is not None:
        env["PGPASSWORD"] = unquote(pg.password)
    args = [
        "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
        "--host", str(pg.hostname), "--port", str(pg.port or 5432),
        "--username", unquote(pg.username or ""), "--dbname", "fineract_sandbox",
        "--file", str(output),
    ]
    result = subprocess.run(args, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    if result.returncode:
        raise RuntimeError(f"PostgreSQL input dump failed (exit {result.returncode})")
    result = subprocess.run(["pg_restore", "--list", str(output)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            check=False)
    if result.returncode:
        raise RuntimeError("PostgreSQL input dump did not pass archive validation")
    output.chmod(0o600)


def capture_input(settings: Settings, cycle_id: str,
                  source_through_date: str) -> dict[str, Any]:
    pg, _ = _require_local_stopped_target(settings)
    cycle, state_path, catalog_path = _cycle_evidence(settings, cycle_id)
    before = inspect_target(settings.target, phase="input")
    if not before["target_preconditions_pass"]:
        raise ValueError("Populated sandbox input preflight failed")
    boundary = CarryForwardBoundary.select(before["current_fineract_starts"],
                                           source_through_date)
    private_root = settings.state_path.parent / "carry-forward"
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_root.chmod(0o700)
    root = private_root / "captures"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    capture_id = uuid.uuid4().hex
    previous_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix=f".{capture_id}-", dir=root) as temporary:
            work = Path(temporary)
            dump = work / "tenant.dump"
            cycle_copy = work / "cycle.sqlite3"
            catalog_copy = work / "cycles.sqlite3"
            _dump_database(pg, dump)
            sqlite_backup(state_path, cycle_copy)
            sqlite_backup(catalog_path, catalog_copy)
            after = inspect_target(settings.target, phase="input")
            if after != before:
                raise RuntimeError("Sandbox changed while the recovery capture was being made")
            _cycle_evidence(settings, cycle_id)
            manifest = {
                "version": 1,
                "capture_id": capture_id,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "target": "local",
                "tenant": "sandbox",
                "database": "fineract_sandbox",
                "target_fingerprint": settings.target.fingerprint,
                "old_cycle": cycle_id,
                "old_cycle_baseline_ref": cycle["baseline_ref"],
                "old_arissto_through": boundary.old_arissto_through,
                "old_fineract_starts": boundary.old_fineract_starts,
                "arissto_through": boundary.arissto_through,
                "fineract_starts": boundary.fineract_starts,
                "input_preflight": before,
                "files": {
                    name: {"sha256": sha256_file(work / name),
                           "bytes": (work / name).stat().st_size}
                    for name in ("tenant.dump", "cycle.sqlite3", "cycles.sqlite3")
                },
                "protected_access_in_full_tenant_dump": True,
                "restore_instruction": (
                    "Restore this private tenant.dump and cycles.sqlite3/cycle.sqlite3 "
                    "through the dedicated guarded recovery procedure; do not use "
                    "the fresh/clean baseline reset."
                ),
            }
            manifest_path = work / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                     encoding="utf-8")
            manifest_path.chmod(0o600)
            final = root / capture_id
            work.rename(final)
    finally:
        os.umask(previous_umask)
    return {"capture_id": capture_id, "capture_path": str(final),
            "manifest_sha256": sha256_file(final / "manifest.json"),
            "arissto_through": boundary.arissto_through,
            "fineract_starts": boundary.fineract_starts,
            "tenant_replaced": False}


def verify_capture(settings: Settings, capture_id: str,
                   expected_manifest_sha256: str) -> dict[str, Any]:
    """Verify the immutable private archive before any staging operation."""
    if len(capture_id) != 32 or any(ch not in "0123456789abcdef" for ch in capture_id):
        raise ValueError("Invalid capture ID")
    if len(expected_manifest_sha256) != 64 or any(
        ch not in "0123456789abcdef" for ch in expected_manifest_sha256
    ):
        raise ValueError("Expected manifest SHA-256 is required")
    _require_local_stopped_target(settings, require_stopped=False)
    root = settings.state_path.parent / "carry-forward" / "captures"
    directory = root / capture_id
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file() or sha256_file(manifest_path) != expected_manifest_sha256:
        raise ValueError("Recovery manifest checksum mismatch or missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("version") != 1 or manifest.get("capture_id") != capture_id
            or manifest.get("target_fingerprint") != settings.target.fingerprint
            or manifest.get("tenant") != "sandbox"
            or manifest.get("database") != "fineract_sandbox"):
        raise ValueError("Recovery manifest target identity mismatch")
    if set(manifest.get("files", {})) != {"tenant.dump", "cycle.sqlite3", "cycles.sqlite3"}:
        raise ValueError("Recovery manifest file set mismatch")
    for name, expected in manifest["files"].items():
        path = directory / name
        if (not path.is_file() or path.stat().st_size != expected.get("bytes")
                or sha256_file(path) != expected.get("sha256")):
            raise ValueError(f"Recovery file checksum mismatch: {name}")
    result = subprocess.run(["pg_restore", "--list", str(directory / "tenant.dump")],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            check=False)
    if result.returncode:
        raise ValueError("Recovery PostgreSQL archive is not readable")
    for name in ("cycle.sqlite3", "cycles.sqlite3"):
        with sqlite3.connect((directory / name).resolve().as_uri() + "?immutable=1",
                             uri=True) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError(f"Recovery SQLite archive failed integrity check: {name}")
    return {
        "capture_id": capture_id,
        "manifest_sha256": expected_manifest_sha256,
        "arissto_through": manifest["arissto_through"],
        "fineract_starts": manifest["fineract_starts"],
        "archive_verified": True,
        "ready_for_replacement": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local",), required=True)
    parser.add_argument("--cycle")
    parser.add_argument("--source-through-date")
    parser.add_argument("--verify-capture-id")
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    settings = load_settings(args.target)
    if args.verify_capture_id:
        if args.cycle or args.source_through_date or not args.manifest_sha256:
            parser.error("Verification requires --verify-capture-id and --manifest-sha256 only")
        report = verify_capture(settings, args.verify_capture_id, args.manifest_sha256)
    else:
        if not args.cycle or not args.source_through_date or args.manifest_sha256:
            parser.error("Capture requires --cycle and --source-through-date")
        report = capture_input(settings, args.cycle, args.source_through_date)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
