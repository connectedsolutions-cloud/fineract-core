"""Prepare exact new-cycle mappings for copied closed loans and dependencies.

This reads the immutable old-cycle capture and an isolated seed stage. It does
not create a cycle or change either database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .carry_forward_capture import verify_capture
from .carry_forward_classify import write_private_classification
from .carry_forward_seed_refs import isolated_url
from .config import load_settings
from .connections import postgres_connection


def prepare_mapping_seed(
    classification_path: Path, stage_report_path: Path, archive_report_path: Path,
    capture_id: str, manifest_sha256: str, output: Path,
) -> dict[str, Any]:
    settings = load_settings("local")
    if not settings.target.pg_url or settings.target.tenant != "sandbox":
        raise ValueError("Mapping seed requires the local sandbox profile")
    root = (settings.state_path.parent / "carry-forward").resolve()
    for path in (classification_path, stage_report_path, archive_report_path, output):
        if not path.resolve().is_relative_to(root):
            raise ValueError("Mapping seed files must stay in private state")
    verify_capture(settings, capture_id, manifest_sha256)
    classification = json.loads(classification_path.read_text(encoding="utf-8"))
    stage_report = json.loads(stage_report_path.read_text(encoding="utf-8"))
    archive = json.loads(archive_report_path.read_text(encoding="utf-8"))
    if (classification["classification_hash"] != stage_report["classification_hash"]
            or classification["classification_hash"] != archive["classification_hash"]
            or archive["capture_manifest_sha256"] != manifest_sha256
            or archive["stage_database"] != stage_report["stage_database"]
            or not archive["restored_table_counts_and_hashes_match"]):
        raise ValueError("Mapping seed evidence does not match the staged archive")
    stage_url = isolated_url(settings.target.pg_url, stage_report["stage_database"], "stage")
    with postgres_connection(stage_url) as stage:
        copied_ids = {
            "loans": {str(row[0]) for row in stage.execute("SELECT id FROM m_loan").fetchall()},
            "clients": {str(row[0]) for row in stage.execute("SELECT id FROM m_client").fetchall()},
            "products": {str(row[0]) for row in stage.execute("SELECT id FROM m_product_loan").fetchall()},
        }
    retained = {
        row["source_key"]: row for row in classification["loans"]
        if row["disposition"] in {"retain-candidate", "retain-review"}
    }
    if copied_ids["loans"] != {str(row["target_id"]) for row in retained.values()}:
        raise ValueError("Stage loan IDs differ from retained classification")
    cycle_path = root / "captures" / capture_id / "cycle.sqlite3"
    with sqlite3.connect(cycle_path.resolve().as_uri() + "?immutable=1", uri=True) as cycle:
        cycle.row_factory = sqlite3.Row
        metadata = dict(cycle.execute("SELECT key,value FROM state_metadata"))
        if metadata.get("target_fingerprint") != settings.target.fingerprint:
            raise ValueError("Captured cycle target fingerprint changed")
        binding = classification["accepted_run_binding"]
        reconciliation = cycle.execute(
            "SELECT result_hash,ok FROM reconciliations WHERE run_id=? AND block='loans'",
            (binding["accepted_run_id"],),
        ).fetchone()
        if (reconciliation is None or not reconciliation["ok"]
                or reconciliation["result_hash"] != binding["accepted_reconciliation_hash"]):
            raise ValueError("Accepted loan reconciliation is absent from captured cycle")
        mappings = [dict(row) for row in cycle.execute(
            "SELECT block,source_key,target_id,source_hash FROM mappings "
            "WHERE target_fingerprint=? AND block IN ('loans','clients')",
            (settings.target.fingerprint,),
        )]
    prepared: list[dict[str, str]] = []
    matched = {"loans": set(), "clients": set(), "products": set()}
    for row in mappings:
        block = row["block"]
        target_id = str(row["target_id"])
        if block == "clients" and target_id in copied_ids["clients"]:
            prepared.append(row)
            matched["clients"].add(target_id)
        elif block == "loans" and row["source_key"].startswith("product:") and target_id in copied_ids["products"]:
            prepared.append(row)
            matched["products"].add(target_id)
        elif block == "loans" and row["source_key"] in retained:
            proof = retained[row["source_key"]]
            if (target_id != str(proof["target_id"])
                    or row["source_hash"] != proof["mapping_source_hash"]):
                raise ValueError("Retained loan mapping identity or source hash differs")
            prepared.append({**row, "source_hash": proof["source_hash"]})
            matched["loans"].add(target_id)
    for kind, ids in copied_ids.items():
        if matched[kind] != ids:
            raise ValueError(f"Copied {kind} lack exact old-cycle mappings")
    prepared.sort(key=lambda row: (row["block"], row["source_key"]))
    encoded = json.dumps(prepared, sort_keys=True, separators=(",", ":")).encode()
    result = {
        "report_kind": "private-carry-forward-mapping-seed-v1",
        "arissto_through": classification["arissto_through"],
        "fineract_starts": classification["fineract_starts"],
        "target_fingerprint": settings.target.fingerprint,
        "capture_manifest_sha256": manifest_sha256,
        "stage_dump_sha256": archive["dump_sha256"],
        "classification_hash": classification["classification_hash"],
        "counts": {kind: len(ids) for kind, ids in copied_ids.items()},
        "mapping_count": len(prepared),
        "mapping_hash": hashlib.sha256(encoded).hexdigest(),
        "mappings": prepared,
        "ready_for_new_cycle_import": False,
    }
    write_private_classification(result, output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument("--stage-report", type=Path, required=True)
    parser.add_argument("--archive-report", type=Path, required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare_mapping_seed(
        args.classification, args.stage_report, args.archive_report,
        args.capture_id, args.manifest_sha256, args.output,
    )
    print(json.dumps({key: result[key] for key in (
        "counts", "mapping_count", "mapping_hash", "ready_for_new_cycle_import",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
