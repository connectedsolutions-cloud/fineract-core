"""Verify retained closed loans in an isolated restored seed after cutoff init."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from typing import Any

from .carry_forward_classify import write_private_classification
from .carry_forward_capture import sha256_file
from .carry_forward_seed_refs import isolated_url
from .carry_forward_verify import verify_local_candidates_with_details
from .config import load_settings
from .connections import postgres_connection


def _verify_retained_product_delinquency_buckets(conn: Any, loan_ids: list[int]) -> None:
    """Catch a bucket that lost its mapping rows before replacing sandbox."""
    if not loan_ids:
        return
    missing = conn.execute("""
        SELECT DISTINCT p.id
          FROM m_loan l
          JOIN m_product_loan p ON p.id=l.product_id
         WHERE l.id=ANY(%s) AND p.delinquency_bucket_id IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM m_delinquency_bucket_mappings mapping
                WHERE mapping.delinquency_bucket_id=p.delinquency_bucket_id
           )
         ORDER BY p.id
    """, (loan_ids,)).fetchall()
    if missing:
        raise ValueError(
            "Restored seed is missing delinquency bucket mappings for retained loan products: "
            + ",".join(str(row[0]) for row in missing)
        )


def verify_restored_seed(
    classification_path: Path, stage_report_path: Path,
    archive_report_path: Path, cutoff_report_path: Path,
    old_state_path: Path, output: Path,
) -> dict[str, Any]:
    settings = load_settings("local")
    if not settings.target.pg_url or settings.target.tenant != "sandbox":
        raise ValueError("Restored seed verification requires local sandbox profile")
    root = (settings.state_path.parent / "carry-forward").resolve()
    for path in (classification_path, stage_report_path, archive_report_path,
                 cutoff_report_path, output):
        if not path.resolve().is_relative_to(root):
            raise ValueError("Seed evidence must stay in private carry-forward state")
    classification = json.loads(classification_path.read_text(encoding="utf-8"))
    staged = json.loads(stage_report_path.read_text(encoding="utf-8"))
    archive = json.loads(archive_report_path.read_text(encoding="utf-8"))
    cutoff = json.loads(cutoff_report_path.read_text(encoding="utf-8"))
    if (classification["classification_hash"] != staged["classification_hash"]
            or classification["classification_hash"] != archive["classification_hash"]
            or staged["capture_manifest_sha256"] != archive["capture_manifest_sha256"]
            or archive["dump_sha256"] != cutoff["stage_dump_sha256"]
            or not cutoff["restored_seed_cutoff_advanced"]):
        raise ValueError("Restored seed proof chain is inconsistent")
    manifest_path = root / "captures" / staged["capture_id"] / "manifest.json"
    if sha256_file(manifest_path) != staged["capture_manifest_sha256"]:
        raise ValueError("Captured input manifest changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_state = settings.state_path.parent / "cycles" / manifest["old_cycle"] / "state.sqlite3"
    if old_state_path.resolve() != expected_state.resolve() or not old_state_path.is_file():
        raise ValueError("Old accepted cycle state path differs from capture")
    parsed = urlparse(isolated_url(settings.target.pg_url, staged["stage_database"], "stage"))
    verify_db = archive["restore_test_database"]
    if verify_db != cutoff["restore_test_database"]:
        raise ValueError("Cutoff rehearsal used a different restored seed")
    target = replace(settings.target, pg_url=urlunparse(parsed._replace(
        path="/" + verify_db,
    )))
    binding = {
        "date": cutoff["fineract_starts"],
        "configuration_revision": cutoff["new_configuration_revision"],
        "configuration_hash": cutoff["new_configuration_hash"],
    }
    _, eligible, rejected = verify_local_candidates_with_details(
        old_state_path, target, classification["arissto_through"],
        expected_isolated_cutoff=binding,
    )
    retained = {
        row["source_key"]: row for row in classification["loans"]
        if row["disposition"] in {"retain-candidate", "retain-review"}
    }
    if (set(retained) - eligible.keys()
            or any(eligible[key] != int(row["target_id"])
                   for key, row in retained.items())
            or len(retained) != archive["retained_loan_count"]):
        raise ValueError("A retained loan failed restored-seed target verification")
    with postgres_connection(target.pg_url) as conn:
        _verify_retained_product_delinquency_buckets(
            conn, sorted(int(row["target_id"]) for row in retained.values()),
        )
    proofs = [
        (key, eligible[key], row["source_hash"], row["lifecycle_hash"])
        for key, row in sorted(retained.items())
    ]
    proof_hash = hashlib.sha256(json.dumps(
        proofs, separators=(",", ":"),
    ).encode()).hexdigest()
    result = {
        "report_kind": "isolated-carry-forward-retained-loan-proof-v1",
        "arissto_through": classification["arissto_through"],
        "fineract_starts": cutoff["fineract_starts"],
        "classification_hash": classification["classification_hash"],
        "stage_dump_sha256": archive["dump_sha256"],
        "retained_loan_count": len(retained),
        "retained_loan_proof_set_hash": proof_hash,
        "retained_loans_missing_or_changed": 0,
        "other_historical_candidate_rejections": len(rejected),
        "ready_for_tenant_replacement": False,
    }
    write_private_classification(result, output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument("--stage-report", type=Path, required=True)
    parser.add_argument("--archive-report", type=Path, required=True)
    parser.add_argument("--cutoff-report", type=Path, required=True)
    parser.add_argument("--old-state-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify_restored_seed(
        args.classification, args.stage_report, args.archive_report,
        args.cutoff_report, args.old_state_file, args.output,
    )
    print(json.dumps({key: result[key] for key in (
        "retained_loan_count", "retained_loan_proof_set_hash",
        "retained_loans_missing_or_changed", "other_historical_candidate_rejections",
        "ready_for_tenant_replacement",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
