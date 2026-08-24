from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .arissto import IDENTIFIER, select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import FineractApi, postgres_connection, postgres_schema
from .engine import datatable_api_payload
from .state import State


BLOCK = "client-pep"


class PepDataIssue(RuntimeError):
    """Non-PII reason why a client PEP value cannot be synchronized safely."""


@dataclass(frozen=True)
class PepContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "PepContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        source, target = value.get("source", {}), value.get("target", {})
        identifiers = [
            source.get("table"), source.get("external_key"), source.get("pep_key"),
            target.get("client_table"), target.get("datatable"), target.get("client_key"),
            target.get("pep_column"),
        ]
        if not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Unsafe or missing identifier in client PEP mapping")
        if value.get("value_map") != {"0": False, "1": True}:
            raise ValueError("Client PEP mapping must strictly map 0=false and 1=true")
        if value.get("depends_on") != "clients":
            raise ValueError("Client PEP mapping must depend on clients")
        if value.get("unknown_policy") != "require-row-absent":
            raise ValueError("Client PEP unknown values must require an absent target row")
        if value.get("unexpected_row_policy") != "quarantine-no-delete":
            raise ValueError("Client PEP unexpected rows must quarantine without deletion")
        return cls(value)

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True).encode()).hexdigest()

    def normalize(self, value: Any) -> bool | None:
        if value is None or not str(value).strip():
            return None
        key = str(value).strip()
        if key not in self.raw["value_map"]:
            raise PepDataIssue("invalid_boolean")
        return bool(self.raw["value_map"][key])

    def source_key(self, row: dict[str, Any]) -> str:
        value = str(row.get("source_key") or "").strip()
        if not value or ":" in value:
            raise PepDataIssue("missing_client_affiliation_number")
        return value

    def hash_row(self, row: dict[str, Any]) -> str:
        key = self.source_key(row)
        value = self.normalize(row.get("pep_value"))
        material = {"contract": self.contract_hash, "source_key": key, "es_pep": value}
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()

    def query(self, source_key: str | None = None) -> tuple[str, tuple[Any, ...]]:
        source = self.raw["source"]
        sql = (
            f"SELECT [{source['external_key']}] AS source_key, [{source['pep_key']}] AS pep_value "
            f"FROM [dbo].[{source['table']}]"
        )
        params: tuple[Any, ...] = ()
        if source_key is not None:
            key = source_key.strip()
            if not key or ":" in key:
                raise ValueError("Client PEP source key must be an exact NUMERO_AFILIACION")
            sql += f" WHERE [{source['external_key']}] = ?"
            params = (key,)
        sql += f" ORDER BY [{source['external_key']}]"
        return sql, params


def extract_pep(conn: Any, contract: PepContract, source_key: str | None = None) -> list[dict[str, Any]]:
    sql, params = contract.query(source_key)
    return select_rows(conn, sql, params)


def _summary(rows: list[dict[str, Any]], contract: PepContract) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        count = int(row["row_count"])
        counts["total_rows"] += count
        try:
            value = contract.normalize(row.get("pep_value"))
        except PepDataIssue:
            counts["invalid_rows"] += count
            continue
        counts["true_rows" if value is True else "false_rows" if value is False else "unknown_rows"] += count
        if value is not None:
            counts["expected_datatable_rows"] += count
    return {name: counts[name] for name in (
        "total_rows", "true_rows", "false_rows", "unknown_rows", "invalid_rows", "expected_datatable_rows"
    )}


def inspect_pep(settings: Settings, contract: PepContract) -> dict[str, Any]:
    source, target = contract.raw["source"], contract.raw["target"]
    with source_connection(settings.source) as conn:
        columns = select_rows(
            conn,
            "SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA=? AND TABLE_NAME=?",
            ("dbo", source["table"]),
        )
        grouped = select_rows(
            conn,
            f"SELECT [{source['pep_key']}] AS pep_value, COUNT_BIG(*) AS row_count "
            f"FROM [dbo].[{source['table']}] GROUP BY [{source['pep_key']}]",
        )
    source_columns = {row["column_name"]: row["data_type"] for row in columns}
    api_tables = {
        row.get("registeredTableName") or row.get("registered_table_name")
        for row in FineractApi(settings.target).datatables()
    }
    destination_schema: dict[str, dict[str, str]] = {}
    if settings.target.pg_url:
        with postgres_connection(settings.target.pg_url) as conn:
            destination_schema = postgres_schema(conn, [target["client_table"], target["datatable"]])
    blockers: list[dict[str, Any]] = []
    for column in (source["external_key"], source["pep_key"]):
        if column not in source_columns:
            blockers.append({"source_column": column, "reason": "source_column_missing"})
    target_columns = destination_schema.get(target["datatable"], {})
    for column in (target["client_key"], target["pep_column"]):
        if settings.target.pg_url and column not in target_columns:
            blockers.append({"target_column": f"{target['datatable']}.{column}", "reason": "target_column_missing"})
    if not settings.target.pg_url:
        blockers.append({"configuration": "target_pg_url", "reason": "PEP planning requires read-only target PostgreSQL"})
    if target["datatable"] not in api_tables:
        blockers.append({"target_datatable": target["datatable"], "reason": "datatable_not_registered"})
    schema_material = {
        "source": source_columns,
        "target": destination_schema,
        "api_exposed": target["datatable"] in api_tables,
    }
    return {
        "ready": not blockers,
        "block": BLOCK,
        "target_fingerprint": settings.target.fingerprint,
        "contract_hash": contract.contract_hash,
        "schema_signature": hashlib.sha256(json.dumps(schema_material, sort_keys=True).encode()).hexdigest(),
        "depends_on": contract.raw["depends_on"],
        "pep": _summary(grouped, contract),
        "blockers": blockers,
    }


def build_pep_plan(
    settings: Settings,
    state: State,
    contract: PepContract,
    source_keys: list[str] | None = None,
    owner_keys: set[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    if source_keys and owner_keys:
        raise ValueError("Client PEP planning accepts source keys or parent client keys, not both")
    inspection = inspect_pep(settings, contract)
    with source_connection(settings.source) as source:
        if source_keys:
            rows: list[dict[str, Any]] = []
            for key in dict.fromkeys(source_keys):
                matches = extract_pep(source, contract, key)
                if len(matches) != 1:
                    raise RuntimeError(f"Expected exactly one Arissto client PEP row for source key {key}")
                rows.extend(matches)
        elif owner_keys:
            requested = {key.strip() for key in owner_keys}
            if any(not key or ":" in key for key in requested):
                raise ValueError("Parent client keys must be exact NUMERO_AFILIACION values")
            rows = [row for row in extract_pep(source, contract) if str(row.get("source_key") or "").strip() in requested]
            found = {str(row.get("source_key") or "").strip() for row in rows}
            if found != requested:
                raise RuntimeError("Parent client scope contains keys missing from AFI_SOCIO")
        else:
            rows = extract_pep(source, contract)
    target = contract.raw["target"]
    with postgres_connection(settings.target.pg_url or "") as conn:
        target_rows = conn.execute(
            f"SELECT c.id,c.external_id,p.{target['client_key']} IS NOT NULL,p.{target['pep_column']} "
            f"FROM {target['client_table']} c LEFT JOIN {target['datatable']} p ON p.{target['client_key']}=c.id "
            "WHERE c.external_id IS NOT NULL"
        ).fetchall()
    by_external = {str(external_id): (str(client_id), bool(exists), pep) for client_id, external_id, exists, pep in target_rows}
    actions: list[dict[str, Any]] = []
    counts = Counter()
    seen: set[str] = set()
    missing_clients = 0
    for row in rows:
        key = contract.source_key(row)
        if key in seen:
            raise RuntimeError(f"Duplicate Arissto client PEP source key: {key}")
        seen.add(key)
        issue = None
        try:
            value = contract.normalize(row.get("pep_value"))
            row_hash = contract.hash_row(row)
        except PepDataIssue as exc:
            issue, value = str(exc), None
            row_hash = hashlib.sha256(f"{contract.contract_hash}:{key}:{issue}".encode()).hexdigest()
        current = by_external.get(key)
        target_id = current[0] if current else None
        if current is None:
            issue = issue or "missing_target_client"
            missing_clients += 1
        elif issue is None and value is None and current[1]:
            issue = "unexpected_target_row"
        if issue:
            action = "quarantine"
        elif value is None:
            action = "unchanged"
        elif not current[1]:
            action = "create"
        elif current[2] is value:
            action = "unchanged"
        else:
            action = "update"
        item = {"source_key": key, "source_hash": row_hash, "action": action, "target_id": target_id}
        if issue:
            item["reason"] = issue
        actions.append(item)
        counts[action] += 1
    document = {
        "version": 1,
        "block": BLOCK,
        "target_fingerprint": settings.target.fingerprint,
        "source_fingerprint": source_fingerprint(settings.source),
        "contract_hash": contract.contract_hash,
        "schema_signature": inspection["schema_signature"],
        "depends_on": "clients",
        "applicable": inspection["ready"] and missing_clients == 0,
        "readiness_blocker_count": len(inspection["blockers"]) + missing_clients,
        "scope": {
            "mode": "explicit-source-keys" if source_keys else "parent-client-source-keys" if owner_keys else "full-block",
            "entity_count": len(rows),
            **({"owner_count": len(owner_keys)} if owner_keys else {}),
        },
        "counts": dict(counts),
        "actions": actions,
    }
    plan_id = state.save_plan(
        settings.target.fingerprint, BLOCK, document["source_fingerprint"], contract.contract_hash, document
    )
    return plan_id, document


def apply_pep_plan(
    settings: Settings,
    state: State,
    contract: PepContract,
    plan_id: str,
    production_confirmation: str | None = None,
    only_keys: set[str] | None = None,
) -> tuple[str, dict[str, int]]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Plan belongs to a different block or target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source) or plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Plan is stale: source or client PEP contract changed")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_pep(settings, contract)
    if not inspection["ready"] or not plan["document"].get("applicable"):
        raise RuntimeError("Client PEP plan is not applicable to the current source and target")
    if plan["document"].get("schema_signature") != inspection["schema_signature"]:
        raise RuntimeError("Client PEP destination readiness changed; apply refused")
    api, counts = FineractApi(settings.target), Counter()
    target_table = contract.raw["target"]["datatable"]
    run_id = state.start_run(plan)
    for action in plan["document"]["actions"]:
        key, target_id = action["source_key"], action.get("target_id")
        if only_keys is not None and key not in only_keys:
            continue
        if action["action"] == "quarantine":
            state.record_item(run_id, key, "quarantine", action["source_hash"], "quarantined", target_id,
                              f"PepDataIssue:{action.get('reason', 'unspecified')}")
            counts["quarantined"] += 1
            continue
        if action["action"] == "unchanged":
            state.record_item(run_id, key, "unchanged", action["source_hash"], "unchanged", target_id)
            counts["unchanged"] += 1
            continue
        try:
            with source_connection(settings.source) as source:
                rows = extract_pep(source, contract, key)
            if len(rows) != 1 or contract.hash_row(rows[0]) != action["source_hash"]:
                raise RuntimeError("source_changed_after_plan")
            value = contract.normalize(rows[0].get("pep_value"))
            if value is None:
                raise RuntimeError("unknown_pep_cannot_write")
            client = api.find_client(key)
            if not client or str(client["id"]) != str(target_id):
                raise RuntimeError("client_identity_changed_after_plan")
            api.upsert_datatable(target_table, str(target_id), datatable_api_payload({"es_pep": value}))
            state.save_mapping(settings.target.fingerprint, BLOCK, key, str(target_id), action["source_hash"])
            state.record_item(run_id, key, action["action"], action["source_hash"], "succeeded", str(target_id))
            counts[action["action"]] += 1
        except Exception as exc:
            message = str(exc).splitlines()[0]
            safe = message if message in {
                "source_changed_after_plan", "unknown_pep_cannot_write", "client_identity_changed_after_plan",
            } or isinstance(exc, PepDataIssue) else "redacted"
            state.record_item(run_id, key, action["action"], action["source_hash"], "failed", target_id,
                              f"{type(exc).__name__}:{safe}"[:240])
            counts["failed"] += 1
    state.finish_run(run_id, "completed_with_errors" if counts["failed"] or counts["quarantined"] else "completed", dict(counts))
    return run_id, dict(counts)


def reconcile_pep(settings: Settings, state: State, contract: PepContract, run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Run belongs to a different block or target")
    plan = state.plan(run["plan_id"])
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Run belongs to a stale client PEP contract")
    target = contract.raw["target"]
    results = Counter()
    with source_connection(settings.source) as source, postgres_connection(settings.target.pg_url or "") as target_db:
        for item in state.run_items(run_id):
            if item["status"] == "failed":
                results["failed"] += 1
                continue
            if item["status"] == "quarantined":
                results["quarantined"] += 1
                continue
            if not item["target_id"]:
                results["unresolved"] += 1
                continue
            try:
                rows = extract_pep(source, contract, item["source_key"])
                if len(rows) != 1 or contract.hash_row(rows[0]) != item["source_hash"]:
                    results["source_changed"] += 1
                    continue
                expected = contract.normalize(rows[0].get("pep_value"))
                actual = target_db.execute(
                    f"SELECT {target['pep_column']} FROM {target['datatable']} WHERE {target['client_key']}=%s",
                    (int(item["target_id"]),),
                ).fetchone()
                matches = (actual is None) if expected is None else (actual is not None and actual[0] is expected)
                results["matched" if matches else "mismatched"] += 1
            except Exception:
                results["reconcile_error"] += 1
    failed = {"failed", "quarantined", "unresolved", "source_changed", "mismatched", "reconcile_error"}
    return {"run_id": run_id, "status": run["status"], "counts": dict(results),
            "ok": not any(results[name] for name in failed)}
