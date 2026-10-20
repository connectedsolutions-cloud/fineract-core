"""Guarded local sandbox swap for a reviewed carry-forward plan.

The old populated database remains available under a rollback name. A failed
swap restores its registered name and reopens the previous cycle.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from typing import Any

import psycopg
from psycopg import sql

from .carry_forward_capture import _cycle_evidence, sha256_file, verify_capture
from .carry_forward_classify import write_private_classification
from .carry_forward_mapping_import import import_retained_mappings
from .carry_forward_plan import _canonical_hash, prepare_carry_forward_plan
from .carry_forward_seed_stage import _row_digest
from .carry_forward_target import inspect_target
from .config import ROOT, Settings, load_settings
from .connections import FineractApi, postgres_connection
from .cycles import CycleCatalog
from .state import State
from .orchestration import target_workflow_lock


def _load_plan(settings: Settings, plan_hash: str, *, resume_amendment: dict[str, Any] | None = None) -> dict[str, Any]:
    if len(plan_hash) != 64 or any(ch not in "0123456789abcdef" for ch in plan_hash):
        raise ValueError("Reviewed plan SHA-256 is invalid")
    private_root = settings.state_path.parent
    if private_root.parent.name == "cycles":
        private_root = private_root.parent.parent
    private_root = private_root / "carry-forward"
    path = private_root / "plans" / f"{plan_hash}.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    if (report.get("plan_hash") != plan_hash
            or report.get("approved") is not False
            or _canonical_hash(report.get("plan", {})) != plan_hash):
        raise ValueError("Reviewed carry-forward plan changed")
    plan = report["plan"]
    if plan.get("target") != "sandbox:fineract_sandbox" or plan.get("target_fingerprint") != settings.target.fingerprint:
        raise ValueError("Carry-forward plan targets another tenant")
    for evidence in plan["evidence"].values():
        path = Path(evidence["path"])
        if (not path.resolve().is_relative_to(private_root.resolve())
                or sha256_file(path) != evidence["sha256"]):
            raise ValueError("Carry-forward plan evidence changed")
    # The approved, run-specific amendment permits only four reviewed file
    # hashes after the sandbox swap has already completed. Initial replacement
    # and every other workflow continue to require the original plan hashes.
    amendment_hashes: dict[str, str] = {}
    if resume_amendment is not None:
        if (
            plan_hash != "6b64f838e804d4a4614462f6439b0dff7b4160ed15e2e9af87703970a41ccd6e"
            or resume_amendment.get("workflow_run_id") != "494db0368e3f4b538b898a7ba592b5e8"
            or resume_amendment.get("cycle_id") != "sandbox-2026-10-08-carry-forward-a"
            or resume_amendment.get("plan_hash") != plan_hash
            or resume_amendment.get("target_fingerprint") != settings.target.fingerprint
            or set(resume_amendment.get("implementation_sha256", {})) != {
                "loans.py", "carry_forward_seed_refs.py",
                "carry_forward_replace.py", "orchestration.py",
            }
        ):
            raise ValueError("Carry-forward resume amendment is not bound to this reviewed run")
        amendment_hashes = resume_amendment["implementation_sha256"]
    code_dir = ROOT / "arissto_sync"
    for name, expected_hash in plan["implementation_sha256"].items():
        actual_hash = sha256_file(code_dir / name)
        if not name.endswith(".py") or Path(name).name != name:
            raise ValueError("Carry-forward implementation changed after plan review")
        if actual_hash == expected_hash:
            continue
        if amendment_hashes.get(name) != actual_hash:
            raise ValueError("Carry-forward implementation changed after plan review")
    return plan


def _maintenance_url(settings: Settings) -> str:
    parsed = urlparse(settings.target.pg_url or "")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.path != "/fineract_sandbox":
        raise ValueError("Database swap requires the exact local sandbox URL")
    return urlunparse(parsed._replace(path="/postgres"))


def _database_url(settings: Settings, database: str) -> str:
    return urlunparse(urlparse(settings.target.pg_url or "")._replace(path="/" + database))


def _exists(conn: psycopg.Connection, database: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone())


def _rename(conn: psycopg.Connection, before: str, after: str) -> None:
    if not _exists(conn, before) or _exists(conn, after):
        raise RuntimeError("Carry-forward database rename preconditions changed")
    active = conn.execute(
        "SELECT COUNT(*) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
        (before,),
    ).fetchone()[0]
    if active:
        raise RuntimeError(f"Carry-forward database {before} has active connections")
    conn.execute(sql.SQL("ALTER DATABASE {} RENAME TO {}").format(
        sql.Identifier(before), sql.Identifier(after),
    ))


def _lifecycle(action: str) -> None:
    result = subprocess.run(
        [str(ROOT.parents[1] / "scripts" / "local-fineract.sh"), action],
        cwd=ROOT.parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=180, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Guarded local Fineract {action} failed")


def _lifecycle_running() -> bool:
    result = subprocess.run(
        [str(ROOT.parents[1] / "scripts" / "local-fineract.sh"), "status"],
        cwd=ROOT.parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=10, check=False,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError("Cannot determine guarded local Fineract status")
    return result.returncode == 0


def _api_ready(settings: Settings, timeout: float = 180) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            FineractApi(settings.target).ping()
            return True
        except Exception:
            time.sleep(2)
    return False


def _verify_staged_database(settings: Settings, plan: dict[str, Any]) -> None:
    stage = json.loads(Path(plan["evidence"]["stage"]["path"]).read_text(encoding="utf-8"))
    cutoff = json.loads(Path(plan["evidence"]["cutoff"]["path"]).read_text(encoding="utf-8"))
    database = plan["restore_test_database"]
    if not database.startswith("fineract_carry_seed_verify_"):
        raise ValueError("Seed database has an unsafe name")
    with postgres_connection(_database_url(settings, database)) as conn:
        for table, count in stage["stage_table_counts"].items():
            actual = conn.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
            if actual != count or _row_digest(conn, table, sql.SQL("TRUE"), ()) != stage["stage_table_hashes"][table]:
                raise RuntimeError(f"Restored seed changed: {table}")
        actual_cutoff = conn.execute(
            "SELECT cutoff_date,lifecycle_state,configuration_revision,configuration_hash "
            "FROM acc_accounting_cutoff_configuration WHERE id=1"
        ).fetchone()
        if (actual_cutoff is None or actual_cutoff[0].isoformat() != plan["fineract_starts"]
                or actual_cutoff[1:] != ("ACTIVE", cutoff["new_configuration_revision"],
                                           cutoff["new_configuration_hash"])):
            raise RuntimeError("Restored seed accounting boundary changed")


def _rollback_cycle(settings: Settings, old_cycle: str, new_cycle: str) -> None:
    catalog = CycleCatalog(settings.state_path)
    try:
        row = catalog.conn.execute("SELECT state_path FROM sync_cycles WHERE id=?", (new_cycle,)).fetchone()
        if row:
            path = Path(row["state_path"])
            _assert_unstarted_cycle(path)
            archive = settings.state_path.parent / "carry-forward" / "failed-cycles" / (
                new_cycle + "-" + uuid.uuid4().hex[:8]
            )
            archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with catalog.conn:
                catalog.conn.execute("DELETE FROM sync_cycles WHERE id=?", (new_cycle,))
                catalog.conn.execute(
                    "UPDATE sync_cycles SET status='open',closed_at=NULL WHERE id=?", (old_cycle,),
                )
            shutil.move(str(path.parent), str(archive))
    finally:
        catalog.conn.close()


def _assert_unstarted_cycle(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError("Carry-forward cycle state is missing")
    state = State(path)
    try:
        if (state.conn.execute("SELECT COUNT(*) FROM workflow_plans").fetchone()[0]
                or state.conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]):
            raise RuntimeError("Cannot roll back a carry-forward cycle with workflow activity")
    finally:
        state.conn.close()


def replace_from_reviewed_plan(
    plan_hash: str, confirmation: str, env_file: str | None = None,
) -> dict[str, Any]:
    settings = load_settings("local", env_file)
    if confirmation != "sandbox:fineract_sandbox":
        raise ValueError("Carry-forward replacement requires exact sandbox:fineract_sandbox confirmation")
    with target_workflow_lock(settings):
        return _replace_locked(settings, plan_hash, env_file)


def _replace_locked(settings: Settings, plan_hash: str, env_file: str | None) -> dict[str, Any]:
    plan = _load_plan(settings, plan_hash)
    evidence = plan["evidence"]
    # Recheck live Arissto and the registered sandbox immediately before stopping Fineract.
    current = prepare_carry_forward_plan(
        plan["capture_id"], plan["capture_manifest_sha256"], plan["new_cycle"],
        *(Path(evidence[name]["path"]) for name in (
            "classification", "stage", "archive", "cutoff", "mapping", "retained_proof"
        )),
        env_file=env_file,
    )
    if current["plan_hash"] != plan_hash:
        raise RuntimeError("Carry-forward plan changed on fresh read")
    _cycle_evidence(settings, plan["old_cycle"])
    verify_capture(settings, plan["capture_id"], plan["capture_manifest_sha256"])
    old_database = "fineract_carry_rollback_" + plan["capture_id"][:16]
    was_running = _lifecycle_running()
    _lifecycle("stop")
    swapped = False
    try:
        if inspect_target(settings.target, phase="input") != json.loads(
            (settings.state_path.parent / "carry-forward" / "captures" /
             plan["capture_id"] / "manifest.json").read_text(encoding="utf-8")
        )["input_preflight"]:
            raise RuntimeError("Registered sandbox changed before replacement")
        _verify_staged_database(settings, plan)
        with psycopg.connect(_maintenance_url(settings), autocommit=True) as conn:
            if _exists(conn, old_database):
                raise RuntimeError("Carry-forward rollback database already exists")
            _rename(conn, "fineract_sandbox", old_database)
            try:
                _rename(conn, plan["restore_test_database"], "fineract_sandbox")
            except Exception:
                _rename(conn, old_database, "fineract_sandbox")
                raise
        swapped = True
        seeded = inspect_target(settings.target, phase="seed")
        if (not seeded["target_preconditions_pass"]
                or seeded["seed_cutoff"] != plan["fineract_starts"]
                or sum(seeded["loan_status_counts"].values()) != plan["retained_loans"]):
            raise RuntimeError("Registered carry-forward seed failed verification")
        catalog = CycleCatalog(settings.state_path)
        try:
            cycle = catalog.create(
                plan["new_cycle"], "local", settings.target.fingerprint,
                plan["stage_dump_sha256"], f"carry-forward plan {plan_hash}",
            )
        finally:
            catalog.conn.close()
        imported = import_retained_mappings(
            settings, plan["new_cycle"],
            *(Path(evidence[name]["path"]) for name in (
                "mapping", "archive", "cutoff", "retained_proof", "classification"
            )),
            plan, plan_hash,
        )
        if was_running:
            _lifecycle("start")
            if not _api_ready(settings):
                raise RuntimeError("Fineract did not become healthy after carry-forward replacement")
        result = {
            "plan_hash": plan_hash, "cycle": cycle["id"],
            "arissto_through": plan["arissto_through"],
            "fineract_starts": plan["fineract_starts"],
            "retained_loans": plan["retained_loans"],
            "mapping_count": imported["mapping_count"],
            "rollback_database": old_database,
            "workflow": "carry-forward-rebuild",
            "workflow_started": False,
        }
        write_private_classification(
            result, settings.state_path.parent / "carry-forward" / "plans" /
            f"{plan_hash}-replacement.json",
            env_file,
        )
        return result
    except Exception:
        if swapped:
            _lifecycle("stop")
            with psycopg.connect(_maintenance_url(settings), autocommit=True) as conn:
                _rename(conn, "fineract_sandbox", plan["restore_test_database"])
                _rename(conn, old_database, "fineract_sandbox")
            _rollback_cycle(settings, plan["old_cycle"], plan["new_cycle"])
        if was_running:
            _lifecycle("start")
        raise


def recover_previous_sandbox(
    plan_hash: str, confirmation: str, env_file: str | None = None,
) -> dict[str, Any]:
    """Restore the old DB name after an interrupted swap, before any workflow."""
    settings = load_settings("local", env_file)
    if confirmation != "sandbox:fineract_sandbox":
        raise ValueError("Recovery requires exact sandbox:fineract_sandbox confirmation")
    with target_workflow_lock(settings):
        return _recover_locked(settings, plan_hash)


def _recover_locked(settings: Settings, plan_hash: str) -> dict[str, Any]:
    plan = _load_plan(settings, plan_hash)
    verify_capture(settings, plan["capture_id"], plan["capture_manifest_sha256"])
    catalog = CycleCatalog(settings.state_path)
    try:
        row = catalog.conn.execute(
            "SELECT state_path FROM sync_cycles WHERE id=?", (plan["new_cycle"],),
        ).fetchone()
        if row:
            _assert_unstarted_cycle(Path(row["state_path"]))
    finally:
        catalog.conn.close()
    rollback_database = "fineract_carry_rollback_" + plan["capture_id"][:16]
    was_running = _lifecycle_running()
    _lifecycle("stop")
    try:
        with psycopg.connect(_maintenance_url(settings), autocommit=True) as conn:
            if not _exists(conn, rollback_database):
                raise RuntimeError("No preserved rollback database exists for this plan")
            if _exists(conn, "fineract_sandbox"):
                seed = inspect_target(settings.target, phase="seed")
                if (not seed["target_preconditions_pass"]
                        or seed["seed_cutoff"] != plan["fineract_starts"]
                        or sum(seed["loan_status_counts"].values()) != plan["retained_loans"]):
                    raise RuntimeError("Current sandbox is not the untouched carry-forward seed")
                _rename(conn, "fineract_sandbox", plan["restore_test_database"])
            _rename(conn, rollback_database, "fineract_sandbox")
        _rollback_cycle(settings, plan["old_cycle"], plan["new_cycle"])
        original = json.loads(
            (settings.state_path.parent / "carry-forward" / "captures" /
             plan["capture_id"] / "manifest.json").read_text(encoding="utf-8")
        )["input_preflight"]
        if inspect_target(settings.target, phase="input") != original:
            raise RuntimeError("Recovered sandbox differs from the immutable input capture")
        return {"recovered_cycle": plan["old_cycle"], "target": "sandbox:fineract_sandbox",
                "plan_hash": plan_hash}
    finally:
        if was_running:
            _lifecycle("start")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-hash", required=True)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--recover", action="store_true", help="restore the preserved prior sandbox before workflow activity")
    args = parser.parse_args()
    report = (recover_previous_sandbox(args.plan_hash, args.confirm) if args.recover
              else replace_from_reviewed_plan(args.plan_hash, args.confirm))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
