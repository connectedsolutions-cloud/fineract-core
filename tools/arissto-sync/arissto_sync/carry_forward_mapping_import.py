"""Import only proven retained mappings into an empty carry-forward cycle.

The caller must have restored the reviewed seed and initialized its cutoff.
No plans, runs, or checkpoints are inherited from the previous cycle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .carry_forward_capture import sha256_file
from .carry_forward_plan import _canonical_hash
from .carry_forward_target import inspect_target
from .config import Settings, load_settings
from .connections import postgres_connection
from .cycles import CycleCatalog
from .state import State, now


def import_retained_mappings(
    settings: Settings, cycle_id: str, mapping_path: Path,
    archive_path: Path, cutoff_path: Path, proof_path: Path,
    classification_path: Path, replacement_plan: dict[str, Any], plan_hash: str,
) -> dict[str, Any]:
    """Fail closed unless the restored sandbox and all private proofs agree."""
    if settings.target.name != "local" or settings.target.tenant != "sandbox":
        raise ValueError("Carry-forward mappings require the local sandbox")
    private_root = (settings.state_path.parent / "carry-forward").resolve()
    for path in (mapping_path, archive_path, cutoff_path, proof_path, classification_path):
        if not path.resolve().is_relative_to(private_root):
            raise ValueError("Carry-forward evidence must stay in private state")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    cutoff = json.loads(cutoff_path.read_text(encoding="utf-8"))
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    classification = json.loads(classification_path.read_text(encoding="utf-8"))
    if (_canonical_hash(replacement_plan) != plan_hash
            or replacement_plan.get("run_mode") != "carry-forward"
            or replacement_plan.get("target") != "sandbox:fineract_sandbox"
            or replacement_plan.get("target_fingerprint") != settings.target.fingerprint
            or replacement_plan.get("new_cycle") != cycle_id
            or replacement_plan.get("arissto_through") != classification["arissto_through"]
            or replacement_plan.get("fineract_starts") != classification["fineract_starts"]
            or replacement_plan.get("mapping_hash") != mapping["mapping_hash"]
            or replacement_plan.get("mapping_count") != mapping["mapping_count"]
            or replacement_plan.get("retained_loans") != proof["retained_loan_count"]
            or replacement_plan.get("stage_dump_sha256") != archive["dump_sha256"]
            or replacement_plan.get("retained_proof_hash") != proof["retained_loan_proof_set_hash"]):
        raise ValueError("New cycle mapping import differs from reviewed replacement plan")
    if (mapping.get("report_kind") != "private-carry-forward-mapping-seed-v1"
            or archive.get("report_kind") != "isolated-carry-forward-seed-archive-v1"
            or proof.get("report_kind") != "isolated-carry-forward-retained-loan-proof-v1"):
        raise ValueError("Unexpected carry-forward evidence format")
    rows = mapping["mappings"]
    classified = classification["loans"]
    classification_hash = hashlib.sha256(json.dumps(
        classified, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    if classification_hash != mapping["classification_hash"]:
        raise ValueError("Loan classification hash changed")
    retained = {
        row["source_key"]: row for row in classified
        if row["disposition"] in {"retain-candidate", "retain-review"}
    }
    retained_mappings = {
        row["source_key"]: row for row in rows
        if row["block"] == "loans" and row["source_key"].startswith("loan:")
    }
    if (set(retained) != set(retained_mappings)
            or any(str(row["target_id"]) != str(retained[key]["target_id"])
                   or row["source_hash"] != retained[key]["source_hash"]
                   for key, row in retained_mappings.items())):
        raise ValueError("Retained loan mappings differ from classification")
    proof_rows = [
        (key, int(row["target_id"]), row["source_hash"], row["lifecycle_hash"])
        for key, row in sorted(retained.items())
    ]
    proof_hash = hashlib.sha256(json.dumps(proof_rows, separators=(",", ":")).encode()).hexdigest()
    if proof_hash != proof["retained_loan_proof_set_hash"]:
        raise ValueError("Retained loan proof set changed")
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(encoded).hexdigest() != mapping["mapping_hash"]:
        raise ValueError("Mapping seed hash changed")
    if (mapping["target_fingerprint"] != settings.target.fingerprint
            or mapping["mapping_count"] != len(rows)
            or mapping["stage_dump_sha256"] != archive["dump_sha256"]
            or mapping["classification_hash"] != archive["classification_hash"]
            or proof["classification_hash"] != mapping["classification_hash"]
            or proof["stage_dump_sha256"] != archive["dump_sha256"]
            or proof["retained_loan_count"] != mapping["counts"]["loans"]
            or proof["retained_loans_missing_or_changed"] != 0
            or mapping["arissto_through"] != archive["arissto_through"]
            or mapping["fineract_starts"] != archive["fineract_starts"]
            or cutoff["fineract_starts"] != mapping["fineract_starts"]
            or cutoff["old_configuration_revision"]
               != classification["old_cutoff_binding"]["configuration_revision"]
            or not cutoff["restored_seed_cutoff_advanced"]):
        raise ValueError("Carry-forward mapping proof chain differs")
    dump_path = Path(archive["dump_path"])
    if (not dump_path.resolve().is_relative_to(private_root)
            or sha256_file(dump_path) != archive["dump_sha256"]):
        raise ValueError("Staged seed archive changed")
    keys = {(row["block"], row["source_key"]) for row in rows}
    if len(keys) != len(rows) or set(mapping["counts"]) != {"loans", "clients", "products"}:
        raise ValueError("Mapping seed contains duplicate or unexpected keys")
    if any(row["block"] not in {"clients", "loans"}
           or not row["target_id"] or not row["source_hash"] for row in rows):
        raise ValueError("Mapping seed contains an invalid row")
    actual_counts = {
        "loans": sum(row["block"] == "loans" and row["source_key"].startswith("loan:") for row in rows),
        "products": sum(row["block"] == "loans" and row["source_key"].startswith("product:") for row in rows),
        "clients": sum(row["block"] == "clients" for row in rows),
    }
    if actual_counts != mapping["counts"] or sum(actual_counts.values()) != len(rows):
        raise ValueError("Mapping seed counts do not match its rows")
    target = inspect_target(settings.target, phase="seed")
    if not target["target_preconditions_pass"] or target["seed_cutoff"] != mapping["fineract_starts"]:
        raise ValueError("Restored sandbox or its accounting boundary differs")
    with postgres_connection(settings.target.pg_url) as conn:
        cutoff_row = conn.execute(
            "SELECT configuration_revision,configuration_hash "
            "FROM acc_accounting_cutoff_configuration WHERE id=1"
        ).fetchone()
        loan_ids = {str(row[0]) for row in conn.execute("SELECT id FROM m_loan")}
        client_ids = {str(row[0]) for row in conn.execute("SELECT id FROM m_client")}
        product_ids = {str(row[0]) for row in conn.execute("SELECT id FROM m_product_loan")}
    if cutoff_row != (cutoff["new_configuration_revision"], cutoff["new_configuration_hash"]):
        raise ValueError("Restored sandbox cutoff revision or hash differs")
    if (loan_ids != {str(row["target_id"]) for row in retained_mappings.values()}
            or client_ids != {str(row["target_id"]) for row in rows if row["block"] == "clients"}
            or product_ids != {str(row["target_id"]) for row in rows
                               if row["block"] == "loans" and row["source_key"].startswith("product:")}):
        raise ValueError("Restored sandbox mapped identities differ")
    catalog = CycleCatalog(settings.state_path)
    try:
        cycle = catalog.require_open(cycle_id, settings.target.fingerprint)
        if catalog.active_workflow_runs():
            raise ValueError("Another local workflow is active")
        state = State(Path(cycle["state_path"]))
        try:
            if (state.cycle_metadata().get("baseline_ref") != archive["dump_sha256"]
                    or state.conn.execute("SELECT COUNT(*) FROM mappings").fetchone()[0]
                    or state.conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
                    or state.conn.execute("SELECT COUNT(*) FROM workflow_plans").fetchone()[0]
                    or state.conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]):
                raise ValueError("New cycle is not an empty cycle for this staged seed")
            timestamp = now()
            with state.conn:
                state.conn.executemany(
                    "INSERT INTO mappings VALUES(?,?,?,?,?,?)",
                    [
                        (settings.target.fingerprint, row["block"], row["source_key"],
                         str(row["target_id"]), row["source_hash"], timestamp)
                        for row in rows
                    ],
                )
                state.conn.executemany(
                    "INSERT INTO state_metadata(key,value) VALUES(?,?)",
                    [
                        ("carry_forward_source_through", mapping["arissto_through"]),
                        ("carry_forward_fineract_starts", mapping["fineract_starts"]),
                        ("carry_forward_old_fineract_starts", classification["old_fineract_starts"]),
                        ("carry_forward_mapping_hash", mapping["mapping_hash"]),
                        ("carry_forward_classification_hash", mapping["classification_hash"]),
                        ("carry_forward_retained_proof_hash", proof_hash),
                        ("carry_forward_stage_dump_sha256", archive["dump_sha256"]),
                        ("carry_forward_plan_hash", plan_hash),
                        ("carry_forward_old_cycle", replacement_plan["old_cycle"]),
                        ("carry_forward_capture_manifest_sha256", replacement_plan["capture_manifest_sha256"]),
                        ("carry_forward_source_read_started_at", replacement_plan["source_read_started_at"]),
                        ("carry_forward_source_read_finished_at", replacement_plan["source_read_finished_at"]),
                        ("carry_forward_retained_loan_count", str(replacement_plan["retained_loans"])),
                        ("carry_forward_mapping_count", str(replacement_plan["mapping_count"])),
                        ("carry_forward_ownership_interval_event_count",
                         str(replacement_plan["ownership_interval_event_count"])),
                        ("carry_forward_ownership_reviewed_retained_copy_count",
                         str(replacement_plan["ownership_reviewed_retained_copy_count"])),
                        ("carry_forward_ownership_reviewed_source_replay_count",
                         str(replacement_plan["ownership_reviewed_source_replay_count"])),
                    ],
                )
        finally:
            state.conn.close()
    finally:
        catalog.conn.close()
    return {
        "cycle_id": cycle_id,
        "arissto_through": mapping["arissto_through"],
        "fineract_starts": mapping["fineract_starts"],
        "mapping_count": len(rows),
        "counts": actual_counts,
        "mapping_hash": mapping["mapping_hash"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--archive-report", required=True, type=Path)
    parser.add_argument("--cutoff-report", required=True, type=Path)
    parser.add_argument("--retained-proof", required=True, type=Path)
    parser.add_argument("--classification", required=True, type=Path)
    parser.add_argument("--plan-hash", required=True)
    args = parser.parse_args()
    from .carry_forward_replace import _load_plan
    settings = load_settings("local")
    reviewed_plan = _load_plan(settings, args.plan_hash)
    result = import_retained_mappings(
        settings, args.cycle, args.mapping, args.archive_report,
        args.cutoff_report, args.retained_proof, args.classification,
        reviewed_plan, args.plan_hash,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
