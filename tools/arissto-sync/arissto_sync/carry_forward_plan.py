"""Freeze a reviewed, read-only plan for a local carry-forward replacement."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .carry_forward_capture import _cycle_evidence, sha256_file, verify_capture
from .carry_forward_classify import inspect_classification, write_private_classification
from .carry_forward_ownership import inspect_ownership
from .carry_forward_target import inspect_target
from .config import ROOT, load_settings
from .cycles import CYCLE_ID
from .workflow_definitions import load_workflow, require_workflow_ready


def _canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare_carry_forward_plan(
    capture_id: str, manifest_sha256: str, new_cycle: str,
    classification_path: Path, stage_path: Path, archive_path: Path,
    cutoff_path: Path, mapping_path: Path, retained_proof_path: Path,
    *, env_file: str | None = None,
) -> dict[str, Any]:
    settings = load_settings("local", env_file)
    if not CYCLE_ID.fullmatch(new_cycle):
        raise ValueError("Invalid new cycle ID")
    private_root = (settings.state_path.parent / "carry-forward").resolve()
    paths = {
        "classification": classification_path, "stage": stage_path,
        "archive": archive_path, "cutoff": cutoff_path,
        "mapping": mapping_path, "retained_proof": retained_proof_path,
    }
    for path in paths.values():
        if not path.resolve().is_relative_to(private_root):
            raise ValueError("Carry-forward plan evidence must stay in private state")
    capture = verify_capture(settings, capture_id, manifest_sha256)
    manifest = json.loads((private_root / "captures" / capture_id / "manifest.json").read_text())
    old_cycle = manifest["old_cycle"]
    _cycle_evidence(settings, old_cycle)
    if new_cycle == old_cycle or (settings.state_path.parent / "cycles" / new_cycle).exists():
        raise ValueError("New cycle already exists or equals the old cycle")
    expected_input = manifest["input_preflight"]
    before = inspect_target(settings.target, phase="input")
    if before != expected_input or not before["target_preconditions_pass"]:
        raise ValueError("Registered sandbox differs from the captured input")
    reports = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()}
    classification = reports["classification"]
    archive = reports["archive"]
    stage = reports["stage"]
    cutoff = reports["cutoff"]
    mapping = reports["mapping"]
    proof = reports["retained_proof"]
    source_date = manifest["arissto_through"]
    fineract_starts = manifest["fineract_starts"]
    if (classification["arissto_through"] != source_date
            or classification["fineract_starts"] != fineract_starts
            or classification["old_fineract_starts"] != manifest["old_fineract_starts"]
            or stage["capture_id"] != capture_id
            or stage["capture_manifest_sha256"] != manifest_sha256
            or archive["capture_manifest_sha256"] != manifest_sha256
            or mapping["capture_manifest_sha256"] != manifest_sha256
            or archive["dump_sha256"] != mapping["stage_dump_sha256"]
            or proof["stage_dump_sha256"] != archive["dump_sha256"]
            or cutoff["stage_dump_sha256"] != archive["dump_sha256"]
            or any(report["classification_hash"] != classification["classification_hash"]
                   for report in (stage, archive, mapping, proof))
            or cutoff["fineract_starts"] != fineract_starts
            or not cutoff["restored_seed_cutoff_advanced"]
            or not archive["restored_table_counts_and_hashes_match"]
            or proof["retained_loans_missing_or_changed"] != 0):
        raise ValueError("Carry-forward staged evidence chain differs")
    dump_path = Path(archive["dump_path"])
    if (not dump_path.resolve().is_relative_to(private_root)
            or sha256_file(dump_path) != archive["dump_sha256"]):
        raise ValueError("Carry-forward seed dump changed")
    # A new Arissto read is required for every selected date and every plan.
    fresh = inspect_classification(
        settings.state_path.parent / "cycles" / old_cycle / "state.sqlite3",
        source_date, env_file,
    )
    if fresh["classification_hash"] != classification["classification_hash"]:
        raise ValueError("Arissto loan classification changed; rebuild the staged seed")
    ownership = inspect_ownership(
        settings.target, manifest["old_fineract_starts"], source_date,
        classification_path=classification_path,
        old_state_path=settings.state_path.parent / "cycles" / old_cycle / "state.sqlite3",
        source=settings.source,
    )
    if not ownership["ownership_interval_clear"]:
        raise ValueError("New ownership interval contains unreviewed Fineract events")
    if inspect_target(settings.target, phase="input") != before:
        raise ValueError("Registered sandbox changed during carry-forward planning")
    definition = load_workflow("carry-forward-rebuild")
    workflow = require_workflow_ready(definition, target="local", run_mode="carry-forward")
    code_dir = ROOT / "arissto_sync"
    code_files = sorted(code_dir.glob("carry_forward_*.py")) + [
        code_dir / name for name in (
            "loans.py", "orchestration.py", "service_runtime.py",
            "workflow_definitions.py", "cli.py",
        )
    ]
    document = {
        "version": 1,
        "kind": "local-carry-forward-replacement-plan",
        "run_mode": "carry-forward",
        "target": "sandbox:fineract_sandbox",
        "target_fingerprint": settings.target.fingerprint,
        "old_cycle": old_cycle,
        "new_cycle": new_cycle,
        "arissto_through": source_date,
        "fineract_starts": fineract_starts,
        "source_read_started_at": classification["source_read_started_at"],
        "source_read_finished_at": classification["source_read_finished_at"],
        "capture_id": capture_id,
        "capture_manifest_sha256": manifest_sha256,
        "captured_input_preflight_hash": _canonical_hash(before),
        "evidence": {name: {"path": str(path.resolve()), "sha256": sha256_file(path)}
                     for name, path in paths.items()},
        "stage_dump_path": str(dump_path.resolve()),
        "stage_dump_sha256": archive["dump_sha256"],
        "restore_test_database": archive["restore_test_database"],
        "retained_loans": proof["retained_loan_count"],
        "mapping_count": mapping["mapping_count"],
        "mapping_hash": mapping["mapping_hash"],
        "retained_proof_hash": proof["retained_loan_proof_set_hash"],
        "ownership_interval_event_count": ownership["known_interval_event_count"],
        "ownership_reviewed_retained_copy_count": ownership["reviewed_retained_copy_count"],
        "ownership_reviewed_source_replay_count": ownership["reviewed_source_replay_count"],
        "ownership_inventory": ownership,
        "workflow_definition_hash": definition.definition_hash,
        "implementation_sha256": {
            path.name: sha256_file(path) for path in code_files
        },
        "ordered_services": workflow["ordered_services"],
        "rollback_capture": capture_id,
    }
    plan_hash = _canonical_hash(document)
    report = {"plan_hash": plan_hash, "plan": document, "approved": False}
    output = private_root / "plans" / f"{plan_hash}.json"
    if output.exists():
        if json.loads(output.read_text(encoding="utf-8")) != report:
            raise ValueError("Existing immutable carry-forward plan differs")
    else:
        write_private_classification(report, output)
    return {"plan_path": str(output), "plan_hash": plan_hash, **document,
            "review_required_before_tenant_replacement": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--new-cycle", required=True)
    for name in ("classification", "stage", "archive", "cutoff", "mapping", "retained-proof"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    report = prepare_carry_forward_plan(
        args.capture_id, args.manifest_sha256, args.new_cycle,
        args.classification, args.stage, args.archive, args.cutoff,
        args.mapping, args.retained_proof,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
