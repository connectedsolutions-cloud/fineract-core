from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .arissto import IDENTIFIER
from .clients import (ADDRESS_COLUMNS, CATALOG_TABLES, CORE_COLUMNS, ClientContract, ClientDataIssue,
                      TargetCatalogs, _fold, extract_clients, resolve_value)
from .config import Settings
from .connections import FineractApi, postgres_connection, postgres_schema, select_rows, source_connection
from .state import State


REPO_ROOT = Path(__file__).resolve().parents[3]


def liquibase_schema() -> dict[str, dict[str, str]]:
    """Extract declared columns from versioned tenant changelogs without executing them."""
    result: dict[str, dict[str, str]] = {}
    parts = REPO_ROOT / "fineract-provider/src/main/resources/db/changelog/tenant/parts"
    for path in parts.glob("*.xml"):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag not in {"createTable", "addColumn"}:
                continue
            table = element.attrib.get("tableName")
            if not table:
                continue
            columns = result.setdefault(table, {})
            for child in element:
                if child.tag.rsplit("}", 1)[-1] == "column" and child.attrib.get("name"):
                    columns[child.attrib["name"]] = child.attrib.get("type", "unknown")
    return result


def compatible_type(expected: str, actual: str) -> bool:
    expected = expected.lower().replace(" ", "")
    actual = actual.lower().replace(" ", "")
    expected = expected.split("default", 1)[0]
    aliases = {"varchar": "charactervarying", "text": "text", "bigint": "bigint", "int": "integer",
               "boolean": "boolean", "date": "date", "decimal": "numeric", "timestamp": "timestampwithouttimezone"}
    base = re.split(r"[<(]", expected, 1)[0]
    return aliases.get(base, base) == re.split(r"[<(]", actual, 1)[0]


def source_fingerprint(settings: Settings) -> str:
    value = f"{settings.source.server}:{settings.source.port}/{settings.source.database}"
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def preflight(settings: Settings) -> dict[str, Any]:
    api = FineractApi(settings.target)
    with source_connection(settings.source) as conn:
        version = select_rows(conn, "SELECT DB_NAME() AS database_name, @@VERSION AS version")[0]
    api_result = api.ping()
    result: dict[str, Any] = {
        "ok": True, "source": {"fingerprint": source_fingerprint(settings), "database": version["database_name"]},
        "target": {"name": settings.target.name, "fingerprint": settings.target.fingerprint,
                   "api": settings.target.api_url, "tenant": settings.target.tenant},
        "api_reachable": bool(api_result is not None), "postgres_inspection": "not-configured",
    }
    if settings.target.pg_url:
        with postgres_connection(settings.target.pg_url) as conn:
            row = conn.execute("SELECT current_database(), current_user, version()").fetchone()
        result["postgres_inspection"] = {"database": row[0], "user": row[1]}
    return result


def boolean_group_summary(rows: list[dict[str, Any]], mapping: dict[str, Any]) -> dict[str, Any]:
    """Summarize grouped source booleans through the same contract normalization used by payloads."""
    source = mapping["source"]
    summary = {"source": source, "total_rows": 0, "true_rows": 0, "false_rows": 0,
               "unknown_rows": 0, "invalid_rows": 0, "expected_datatable_rows": 0}
    for row in rows:
        count = int(row["row_count"])
        summary["total_rows"] += count
        try:
            value = resolve_value(mapping, {source: row.get("source_value")}, None)
        except ClientDataIssue:
            summary["invalid_rows"] += count
            continue
        if value is True:
            summary["true_rows"] += count
            summary["expected_datatable_rows"] += count
        elif value is False:
            summary["false_rows"] += count
            summary["expected_datatable_rows"] += count
        else:
            summary["unknown_rows"] += count
    return summary


def inspect_clients(settings: Settings, contract: ClientContract) -> dict[str, Any]:
    api = FineractApi(settings.target)
    source_catalog_rows: dict[str, list[tuple[Any, int]]] = {}
    source_relationships = []
    source_identity: dict[str, Any] = {}
    source_identity_rows: list[dict[str, Any]] = []
    pep_summary: dict[str, Any] | None = None
    with source_connection(settings.source) as conn:
        source_columns = select_rows(conn,
            "SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?", ("dbo", contract.raw["source"]["table"]))
        source_table = contract.raw["source"]["table"]
        source = contract.raw["source"]
        external_key = source.get("external_key", source["party_key"])
        available_source_columns = {row["column_name"] for row in source_columns}
        if external_key in available_source_columns:
            identity_sql = (
                f"SELECT [{external_key}] AS canonical_key, [{source['company_key']}] AS company_key, "
                f"[{source['branch_key']}] AS branch_key, [{source['party_key']}] AS party_key "
                f"FROM [dbo].[{source_table}]"
            )
            source_identity_rows = select_rows(conn, identity_sql)
            canonical_keys = [str(row["canonical_key"] or "").strip() for row in source_identity_rows]
            populated_keys = [key for key in canonical_keys if key]
            source_identity = {
                "source": external_key,
                "total_rows": len(canonical_keys),
                "blank_rows": len(canonical_keys) - len(populated_keys),
                "distinct_nonblank": len(set(populated_keys)),
                "matches_party_key": sum(
                    key == str(row["party_key"] or "").strip()
                    for key, row in zip(canonical_keys, source_identity_rows)
                ),
            }
            source_identity["ready"] = (
                source_identity["blank_rows"] == 0
                and source_identity["distinct_nonblank"] == source_identity["total_rows"]
            )
        else:
            source_identity = {"source": external_key, "ready": False, "reason": "source_column_missing"}
        pep_mapping = ((contract.raw.get("datatables", {}).get("credesal_client_pep", {})
                        .get("es_pep")) or {})
        pep_source = pep_mapping.get("source")
        if pep_mapping.get("disposition") in {"migrate", "derived"} and pep_source:
            if pep_source in available_source_columns:
                pep_rows = select_rows(conn,
                    f"SELECT [{pep_source}] AS source_value, COUNT_BIG(*) AS row_count "
                    f"FROM [dbo].[{source_table}] GROUP BY [{pep_source}]")
                pep_summary = boolean_group_summary(pep_rows, pep_mapping)
            else:
                pep_summary = {"source": pep_source, "ready": False, "reason": "source_column_missing"}
        for related_table, required_columns in contract.related_source_requirements().items():
            related_columns = select_rows(conn,
                "SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?", ("dbo", related_table))
            available_related = {row["column_name"] for row in related_columns}
            missing = [column for column in required_columns if column not in available_related]
            source_relationships.append({"table": related_table, "required_columns": required_columns,
                                         "missing_columns": missing, "ready": not missing})
        for source_column, _, _ in contract.catalog_sources():
            if source_column in source_catalog_rows:
                continue
            rows = select_rows(conn,
                f"SELECT [{source_column}] AS source_key, COUNT(*) AS row_count FROM [dbo].[{source_table}] "
                f"WHERE [{source_column}] IS NOT NULL GROUP BY [{source_column}]")
            source_catalog_rows[source_column] = [(row["source_key"], int(row["row_count"])) for row in rows]
    available_source = {row["column_name"]: row["data_type"] for row in source_columns}
    api_tables = {row.get("registeredTableName") or row.get("registered_table_name"): row for row in api.datatables()}
    destination_schema: dict[str, dict[str, str]] = {}
    declared_schema = liquibase_schema()
    catalogs = None
    catalog_error = None
    identifier_keys_globally_unique = None
    office_activation_floors = []
    target_identity = None
    if settings.target.pg_url:
        with postgres_connection(settings.target.pg_url) as conn:
            destination_schema = postgres_schema(conn, ["m_client", "m_client_identifier", "m_address", "m_client_address",
                                                  *contract.raw.get("datatables", {}), *CATALOG_TABLES])
            identifier_keys_globally_unique = bool(conn.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_constraint "
                "WHERE conrelid='m_client_identifier'::regclass AND conname='unique_identifier_key')"
            ).fetchone()[0])
            try:
                catalogs = TargetCatalogs.from_postgres(conn)
            except Exception as exc:
                catalog_error = type(exc).__name__
            for branch, office_id in contract.raw.get("office_mapping", {}).items():
                row = conn.execute("SELECT opening_date FROM m_office WHERE id=%s", (int(office_id),)).fetchone()
                actual = row[0].isoformat() if row and row[0] else None
                expected = contract.raw.get("activation_floor_by_branch", {}).get(branch)
                office_activation_floors.append({"branch": branch, "office_id": int(office_id),
                                                 "expected_opening_date": expected,
                                                 "actual_opening_date": actual,
                                                 "ready": bool(expected and actual == expected)})
            target_rows = conn.execute(
                "SELECT id,external_id FROM m_client WHERE external_id IS NOT NULL"
            ).fetchall()
            target_by_external_id = {str(external_id): str(target_id) for target_id, external_id in target_rows}
            canonical_existing = legacy_existing = collisions = 0
            for row in source_identity_rows:
                canonical = str(row["canonical_key"] or "").strip()
                legacy = "arissto:afi_socio:" + ":".join(
                    str(row[name] or "").strip() for name in ("company_key", "branch_key", "party_key")
                )
                canonical_target = target_by_external_id.get(canonical)
                legacy_target = target_by_external_id.get(legacy)
                canonical_existing += canonical_target is not None
                legacy_existing += legacy_target is not None
                collisions += bool(canonical_target and legacy_target and canonical_target != legacy_target)
            target_identity = {
                "canonical_external_ids": canonical_existing,
                "legacy_prefixed_external_ids": legacy_existing,
                "identity_collisions": collisions,
                "ready": collisions == 0,
            }
    matrix = []
    for field in contract.fields():
        table, column = field["destination"].split(".", 1)
        sources = contract._mapping_sources(field)
        source_exists = field.get("disposition") not in {"migrate", "derived"} or all(source in available_source for source in sources)
        if field["kind"] == "identifier":
            db_exists = None if not destination_schema else bool(destination_schema.get("m_client_identifier"))
        else:
            db_exists = None if not destination_schema else column in destination_schema.get(table, {})
        declared_type = declared_schema.get(table, {}).get(column)
        actual_type = destination_schema.get(table, {}).get(column) if destination_schema else None
        type_matches = None if not actual_type or not declared_type else compatible_type(declared_type, actual_type)
        api_exists = True if table in {"m_client", "m_client_identifier", "m_address", "m_client_address"} else table in api_tables
        status = field["kind"]
        if field.get("disposition") == "derived": status = "derived-field"
        elif field.get("disposition") == "excluded": status = "excluded-field"
        elif not source_exists or db_exists is False or not api_exists: status = "missing-field"
        matrix.append({"source": field.get("source"), "destination": field["destination"],
                       "classification": status, "source_exists": source_exists,
                       "database_exists": db_exists, "api_exposed": api_exists,
                       "liquibase_type": declared_type, "database_type": actual_type, "type_matches": type_matches,
                       "required": bool(field.get("required"))})
    expected_tables = set(contract.raw.get("datatables", {}))
    tables = [{"name": name, "api_exposed": name in api_tables,
               "database_exists": None if not destination_schema else bool(destination_schema.get(name)),
               "liquibase_declared": bool(declared_schema.get(name)),
               "columns_match": None if not destination_schema else all(
                   column in destination_schema.get(name, {}) and compatible_type(expected_type, destination_schema[name][column])
                   for column, expected_type in declared_schema.get(name, {}).items())}
              for name in sorted(expected_tables)]
    blockers = [item for item in matrix if item["classification"] == "missing-field" and item["required"]]
    if not source_identity.get("ready"):
        blockers.append({"source_identity": source_identity, "reason": "Canonical client IDs must be populated and unique"})
    if target_identity and not target_identity["ready"]:
        blockers.append({"target_identity": target_identity,
                         "reason": "Canonical and legacy external IDs resolve to different Fineract clients"})
    blockers += [item for item in source_relationships if not item["ready"]]
    blockers += [item for item in tables if not item["liquibase_declared"] or not item["api_exposed"]
                 or item["database_exists"] is False or item["columns_match"] is False]
    blockers += [item for item in office_activation_floors if not item["ready"]]
    if not contract.raw.get("create_defaults"):
        blockers.append({"configuration": "create_defaults", "reason": "Client creation policy is not configured"})
    allows_duplicate_identifiers = any(
        item.get("disposition") in {"migrate", "derived"} and not item.get("source_unique", True)
        for item in contract.raw.get("identifiers", {}).values()
    )
    if allows_duplicate_identifiers and identifier_keys_globally_unique:
        blockers.append({"constraint": "unique_identifier_key",
                         "reason": "Target still rejects duplicate client identifier keys; apply migration 0275"})
    catalog_readiness = []
    if not settings.target.pg_url:
        blockers.append({"configuration": "target_pg_url", "reason": "KYC catalog resolution requires read-only target PostgreSQL inspection"})
    elif catalog_error:
        blockers.append({"configuration": "target_catalogs", "reason": f"Could not load target catalogs: {catalog_error}"})
    elif catalogs:
        for code, label in contract.required_named_codes():
            present = (code.casefold(), label.casefold()) in catalogs.named_values
            item = {"kind": "named-code", "catalog": code, "label": label, "ready": present}
            catalog_readiness.append(item)
            if not present: blockers.append(item)
        for group, name in contract.required_client_tags():
            present = (_fold(group), _fold(name)) in catalogs.client_tags
            item = {"kind": "client-tag", "group": group, "name": name, "ready": present}
            catalog_readiness.append(item)
            if not present:
                blockers.append(item)
        for source_column, kind, catalog_name in contract.catalog_sources():
            unresolved_rows = unresolved_keys = populated_rows = 0
            for key, count in source_catalog_rows.get(source_column, []):
                populated_rows += count
                try:
                    if kind == "code": catalogs.catalog_value(catalog_name, key)
                    elif kind == "activity": catalogs.activity(key)
                    else: catalogs.reference(kind, key)
                except ClientDataIssue:
                    unresolved_rows += count
                    unresolved_keys += 1
            item = {"kind": "source-catalog", "source": source_column, "catalog": catalog_name,
                    "populated_rows": populated_rows, "unresolved_rows": unresolved_rows,
                    "unresolved_keys": unresolved_keys, "ready": unresolved_rows == 0,
                    "plan_behavior": "quarantine" if unresolved_rows else "resolve"}
            catalog_readiness.append(item)
        if contract.raw.get("addresses") and not catalogs.address_enabled:
            blockers.append({"configuration": "enable-address", "reason": "Fineract address module is disabled"})
    schema_material = {
        "fields": [{"destination": item["destination"], "database_type": item["database_type"],
                    "liquibase_type": item["liquibase_type"], "api_exposed": item["api_exposed"]} for item in matrix],
        "datatables": tables,
        "catalog_signature": catalogs.signature if catalogs else None,
        "identifier_keys_globally_unique": identifier_keys_globally_unique,
        "office_activation_floors": office_activation_floors,
        "source_relationships": source_relationships,
    }
    schema_signature = hashlib.sha256(json.dumps(schema_material, sort_keys=True).encode()).hexdigest()
    return {"ready": not blockers, "block": "clients", "target_fingerprint": settings.target.fingerprint,
            "contract_hash": contract.contract_hash, "fields": matrix, "datatables": tables,
            "catalogs": catalog_readiness, "address_module_enabled": catalogs.address_enabled if catalogs else None,
            "identifier_keys_globally_unique": identifier_keys_globally_unique,
            "office_activation_floors": office_activation_floors,
            "source_relationships": source_relationships,
            "source_identity": source_identity, "target_identity": target_identity, "pep": pep_summary,
            "schema_signature": schema_signature, "blockers": blockers, "notes": contract.raw.get("notes", [])}


def resolve_client_identity(api: FineractApi, contract: ClientContract, row: dict[str, Any],
                            target_id: str | None = None) -> dict[str, Any] | None:
    """Resolve canonical and legacy external IDs to one target client during the ID transition."""
    canonical = api.find_client(contract.external_id(row))
    if target_id:
        if canonical and str(canonical["id"]) != str(target_id):
            raise RuntimeError("client_identity_collision")
        return canonical or api.get_client(target_id)
    candidates: dict[str, dict[str, Any]] = {}
    if canonical:
        candidates[str(canonical["id"])] = canonical
    legacy = api.find_client(contract.legacy_external_id(row))
    if legacy:
        candidates[str(legacy["id"])] = legacy
    if len(candidates) > 1:
        raise RuntimeError("client_identity_collision")
    return next(iter(candidates.values()), None)


def target_client_index(conn: Any, external_ids: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load target identities, active state, and tags in one PostgreSQL round trip."""
    if not external_ids:
        return {}, {}
    rows = conn.execute(
        "SELECT c.id,c.external_id,c.status_enum,t.id,t.tag_group,t.name,t.is_active "
        "FROM m_client c "
        "LEFT JOIN m_client_tag_mapping tm ON tm.client_id=c.id "
        "LEFT JOIN m_client_tag t ON t.id=tm.tag_id "
        "WHERE c.external_id = ANY(%s)",
        (list(dict.fromkeys(external_ids)),),
    ).fetchall()
    by_external: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for client_id, external_id, status_enum, tag_id, tag_group, tag_name, tag_active in rows:
        key, identifier = str(external_id), str(client_id)
        current = by_external.get(key)
        if current and current["id"] != identifier:
            raise RuntimeError(f"duplicate_target_external_id:{key}")
        if current is None:
            current = {"id": identifier, "externalId": key, "active": int(status_enum) == 300, "tags": []}
            by_external[key] = current
            by_id[identifier] = current
        if tag_id is not None:
            current["tags"].append({
                "id": int(tag_id), "tagGroup": tag_group, "name": tag_name, "isActive": bool(tag_active)
            })
    return by_external, by_id


def resolve_indexed_client_identity(api: FineractApi, contract: ClientContract, row: dict[str, Any],
                                    by_external: dict[str, dict[str, Any]],
                                    by_id: dict[str, dict[str, Any]],
                                    target_id: str | None = None) -> dict[str, Any] | None:
    canonical = by_external.get(contract.external_id(row))
    if target_id:
        if canonical and canonical["id"] != str(target_id):
            raise RuntimeError("client_identity_collision")
        # The API fallback is exceptional: it preserves stale-mapping diagnostics
        # without imposing a request on every normally indexed client.
        return canonical or by_id.get(str(target_id)) or api.get_client(str(target_id))
    candidates = {
        current["id"]: current for current in (
            canonical, by_external.get(contract.legacy_external_id(row))
        ) if current is not None
    }
    if len(candidates) > 1:
        raise RuntimeError("client_identity_collision")
    return next(iter(candidates.values()), None)


def build_plan(settings: Settings, state: State, contract: ClientContract,
               source_keys: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    inspection = inspect_clients(settings, contract)
    source_blockers = [item for item in inspection["fields"]
                       if item["required"] and not item["source_exists"]]
    if source_blockers:
        raise RuntimeError("Required Arissto columns are missing; extraction cannot be planned")
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for KYC catalog resolution")
    actions, counts = [], Counter()
    with source_connection(settings.source) as conn:
        if source_keys:
            rows = []
            for key in dict.fromkeys(source_keys):
                matches = extract_clients(conn, contract, key)
                if len(matches) != 1:
                    raise RuntimeError(f"Expected exactly one Arissto client for source key {key}")
                rows.extend(matches)
        else:
            rows = extract_clients(conn, contract)
    external_ids = [value for row in rows for value in (
        contract.external_id(row), contract.legacy_external_id(row)
    )]
    with postgres_connection(settings.target.pg_url) as conn:
        catalogs = TargetCatalogs.from_postgres(conn)
        by_external, by_id = target_client_index(conn, external_ids)
    api = FineractApi(settings.target)
    seen = set()
    for row in rows:
        key = contract.source_key(row)
        if key in seen:
            raise RuntimeError(f"Duplicate Arissto client source key: {key}")
        seen.add(key)
        try:
            row_hash = contract.hash_row(row, catalogs)
            issue = None
        except ClientDataIssue as exc:
            issue = str(exc)
            row_hash = hashlib.sha256(f"{contract.contract_hash}:{key}:{issue}".encode()).hexdigest()
        legacy_key = contract.legacy_source_key(row)
        prior = (state.mapping(settings.target.fingerprint, "clients", key)
                 or state.mapping(settings.target.fingerprint, "clients", legacy_key))
        link = (state.link(settings.target.fingerprint, "clients", key)
                or state.link(settings.target.fingerprint, "clients", legacy_key))
        target_id = link["target_id"] if link else (prior["target_id"] if prior else None)
        current = resolve_indexed_client_identity(api, contract, row, by_external, by_id, target_id)
        target_id = str(current["id"]) if current else None
        activation_required = bool(current and contract.import_active and not current.get("active"))
        tag_update_required = bool(current and not contract.client_type_tag_matches(row, current, catalogs))
        status_action = contract.status_action(row)
        if issue:
            action = "quarantine"
        elif status_action == "deactivate" and target_id:
            action = "deactivate"
        elif not target_id:
            action = "create"
        elif prior and prior["source_hash"] == row_hash and not activation_required and not tag_update_required:
            action = "unchanged"
        else:
            action = "update"
        counts[action] += 1
        item = {"source_key": key, "source_hash": row_hash, "action": action, "target_id": target_id}
        if activation_required:
            item["activate"] = True
        if tag_update_required:
            item["client_type_tag_update"] = True
        if issue: item["reason"] = issue
        actions.append(item)
    document = {"version": 1, "block": "clients", "target_fingerprint": settings.target.fingerprint,
                "source_fingerprint": source_fingerprint(settings), "contract_hash": contract.contract_hash,
                "schema_signature": inspection["schema_signature"],
                "applicable": inspection["ready"],
                "readiness_blocker_count": len(inspection["blockers"]),
                "scope": {"mode": "explicit-source-keys" if source_keys else "full-block", "entity_count": len(rows)},
                "counts": dict(counts), "actions": actions}
    plan_id = state.save_plan(settings.target.fingerprint, "clients", document["source_fingerprint"],
                              contract.contract_hash, document)
    return plan_id, document


def apply_plan(settings: Settings, state: State, contract: ClientContract, plan_id: str,
               production_confirmation: str | None = None, only_keys: set[str] | None = None) -> tuple[str, dict[str, int]]:
    plan = state.plan(plan_id)
    if plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Plan belongs to a different target")
    if plan["source_fingerprint"] != source_fingerprint(settings) or plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Plan is stale: source or client contract changed")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_clients(settings, contract)
    if not inspection["ready"]:
        raise RuntimeError("Destination readiness changed; apply refused")
    if not plan["document"].get("applicable") or plan["document"].get("schema_signature") != inspection["schema_signature"]:
        raise RuntimeError("Plan is not applicable to the current destination schema")
    api, counts = FineractApi(settings.target), Counter()
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for KYC catalog resolution")
    with postgres_connection(settings.target.pg_url) as conn:
        catalogs = TargetCatalogs.from_postgres(conn)
    run_id = state.start_run(plan)
    with source_connection(settings.source) as source:
        for action in plan["document"]["actions"]:
            key = action["source_key"]
            target_id = action.get("target_id")
            if only_keys is not None and key not in only_keys:
                continue
            if action["action"] == "quarantine":
                state.record_item(run_id, key, "quarantine", action["source_hash"], "quarantined",
                                  action.get("target_id"), f"ClientDataIssue:{action.get('reason', 'unspecified')}")
                counts["quarantined"] += 1
                continue
            if action["action"] == "unchanged":
                state.record_item(run_id, key, "unchanged", action["source_hash"], "unchanged", action.get("target_id"))
                counts["unchanged"] += 1
                continue
            try:
                rows = extract_clients(source, contract, key)
                if len(rows) != 1 or contract.hash_row(rows[0], catalogs) != action["source_hash"]:
                    raise RuntimeError("source_changed_after_plan")
                payload = contract.payload(rows[0], catalogs)
                core, datatables = payload["core"], payload["datatables"]
                effective_action = action["action"]
                freshly_created = False
                if effective_action == "create":
                    # A prior interrupted attempt may have created the core client before a
                    # datatable failed. Recover it by deterministic external ID.
                    recovered = resolve_client_identity(api, contract, rows[0])
                    if recovered:
                        target_id = str(recovered["id"])
                        effective_action = "update"
                if effective_action == "create":
                    defaults = contract.raw.get("create_defaults", {})
                    if not defaults:
                        raise RuntimeError("client_create_defaults_not_configured")
                    core.update(contract.create_values(rows[0]))
                    target_id = api.create_client(core)
                    freshly_created = True
                elif effective_action == "update":
                    if not target_id: raise RuntimeError("missing_target_id")
                    current = api.get_client(target_id)
                    api.update_client(target_id, client_update_api_payload(core, current, payload.get("client_type_tag")))
                elif effective_action == "deactivate":
                    reason = contract.raw.get("deactivation", {}).get("closure_reason_id")
                    if not reason: raise RuntimeError("deactivation_closure_reason_not_configured")
                    api.deactivate_client(target_id, int(reason), date.today().isoformat())
                if effective_action == "update" and contract.import_active:
                    current = api.get_client(target_id)
                    if not current.get("active"):
                        api.activate_client(target_id, core["activationDate"])
                if effective_action != "deactivate":
                    for identifier in payload["identifiers"]:
                        body = {field: value for field, value in identifier.items() if field != "name"}
                        (api.create_client_identifier if freshly_created else api.upsert_client_identifier)(target_id, body)
                    for address in payload["addresses"]:
                        (api.create_client_address if freshly_created else api.upsert_client_address)(target_id, address)
                    for table, table_payload in datatables.items():
                        body = datatable_api_payload(table_payload)
                        (api.create_datatable if freshly_created else api.upsert_datatable)(table, target_id, body)
                state.save_mapping(settings.target.fingerprint, "clients", key, str(target_id), action["source_hash"])
                legacy_key = contract.legacy_source_key(rows[0])
                if legacy_key != key:
                    state.delete_mapping(settings.target.fingerprint, "clients", legacy_key)
                    state.delete_link(settings.target.fingerprint, "clients", legacy_key)
                state.record_item(run_id, key, action["action"], action["source_hash"], "succeeded", str(target_id))
                counts[action["action"]] += 1
            except Exception as exc:
                # Persist only a coarse error classification; API responses can contain customer data.
                message = str(exc).splitlines()[0]
                safe_message = message if message in {
                    "source_changed_after_plan", "client_create_defaults_not_configured",
                    "missing_target_id", "deactivation_closure_reason_not_configured", "client_identity_collision",
                } or isinstance(exc, ClientDataIssue) else "redacted"
                code = f"{type(exc).__name__}:{safe_message}"[:240]
                state.record_item(run_id, key, action["action"], action["source_hash"], "failed", target_id, code)
                counts["failed"] += 1
    state.finish_run(run_id, "completed_with_errors" if counts["failed"] or counts["quarantined"] else "completed", dict(counts))
    return run_id, dict(counts)


def datatable_api_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Add parsing metadata that matches JSON's decimal-dot number syntax."""
    return {**payload, "locale": "en", "dateFormat": "yyyy-MM-dd"}


def core_api_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Add ISO date parsing metadata without changing the hashed source payload."""
    result = {**payload, "locale": "en", "dateFormat": "yyyy-MM-dd"}
    if payload.get("activationDate"):
        # Fineract's client update validator only considers activationDate when
        # active=true is present in the same request.
        result["active"] = True
    return result


def client_update_api_payload(payload: dict[str, Any], current: dict[str, Any],
                              client_type_tag: dict[str, Any] | None) -> dict[str, Any]:
    """Replace only the managed client-type tag while preserving active tags in other groups."""
    result = dict(payload)
    if not client_type_tag:
        return core_api_payload(result)
    desired_id = int(client_type_tag["id"])
    group = str(client_type_tag["group"]).strip().casefold()
    current_tags = current.get("tags") or []
    current_type_ids = {
        int(tag["id"]) for tag in current_tags
        if str(tag.get("tagGroup", "")).strip().casefold() == group
    }
    if current_type_ids == {desired_id}:
        result.pop("tagIds", None)
    else:
        preserved = {
            int(tag["id"]) for tag in current_tags
            if str(tag.get("tagGroup", "")).strip().casefold() != group and tag.get("isActive", True)
        }
        result["tagIds"] = sorted(preserved | {desired_id})
    return core_api_payload(result)


def values_match(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    if isinstance(actual, (date, datetime)):
        return actual.isoformat()[:10] == str(expected)[:10]
    if isinstance(actual, Decimal) or isinstance(expected, float):
        return Decimal(str(actual)) == Decimal(str(expected))
    if isinstance(expected, bool):
        return bool(actual) is expected
    if isinstance(expected, int):
        return int(actual) == expected
    return str(actual) == str(expected)


def target_payload_matches(conn: Any, target_id: str, payload: dict[str, Any], expected_active: bool = False) -> bool:
    if expected_active:
        status = conn.execute("SELECT status_enum FROM m_client WHERE id=%s", (int(target_id),)).fetchone()
        if not status or int(status[0]) != 300:
            return False
    core_columns = {key: column for key, column in CORE_COLUMNS.items() if key in payload["core"]}
    if core_columns:
        row = conn.execute(
            f"SELECT {','.join(core_columns.values())} FROM m_client WHERE id=%s", (int(target_id),)
        ).fetchone()
        if not row or any(not values_match(row[index], payload["core"][key])
                          for index, key in enumerate(core_columns)):
            return False

    expected_tag = payload.get("client_type_tag")
    if expected_tag:
        tag_rows = conn.execute(
            "SELECT t.id FROM m_client_tag_mapping tm JOIN m_client_tag t ON t.id=tm.tag_id "
            "WHERE tm.client_id=%s AND LOWER(t.tag_group)=LOWER(%s)",
            (int(target_id), expected_tag["group"]),
        ).fetchall()
        if {int(row[0]) for row in tag_rows} != {int(expected_tag["id"])}:
            return False

    identifier_rows = conn.execute(
        "SELECT document_type_id,document_key FROM m_client_identifier WHERE client_id=%s AND status=200",
        (int(target_id),),
    ).fetchall()
    identifiers = {int(document_type): document_key for document_type, document_key in identifier_rows}
    for expected in payload["identifiers"]:
        if not values_match(identifiers.get(int(expected["documentTypeId"])), expected["documentKey"]):
            return False

    address_rows = conn.execute(
        "SELECT ca.address_type_id,ca.is_active,a.address_line_1,a.address_line_2,a.address_line_3,a.town_village,"
        "a.city,a.county_district,a.state_province_id,a.country_id,a.postal_code "
        "FROM m_client_address ca JOIN m_address a ON a.id=ca.address_id WHERE ca.client_id=%s",
        (int(target_id),),
    ).fetchall()
    address_columns = ["addressTypeId", "isActive", "addressLine1", "addressLine2", "addressLine3", "townVillage",
                       "city", "countyDistrict", "stateProvinceId", "countryId", "postalCode"]
    addresses = {int(row[0]): dict(zip(address_columns, row)) for row in address_rows}
    for expected in payload["addresses"]:
        actual = addresses.get(int(expected["addressTypeId"]))
        if not actual or any(not values_match(actual.get(key), value)
                             for key, value in expected.items() if key not in {"name"}):
            return False

    for table, expected in payload["datatables"].items():
        columns = list(expected)
        row = conn.execute(
            f"SELECT {','.join(columns)} FROM {table} WHERE client_id=%s", (int(target_id),)
        ).fetchone()
        if not row or any(not values_match(row[index], expected[column]) for index, column in enumerate(columns)):
            return False
    for table in payload.get("absent_datatables", []):
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE client_id=%s", (int(target_id),)
        ).fetchone()
        if row:
            return False
    return True


def load_target_payload_snapshots(conn: Any, expected: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Bulk-load every destination value required for client reconciliation."""
    if not expected:
        return {}
    identifiers = [int(value) for value in expected]
    core_keys = sorted({key for payload in expected.values() for key in payload["core"] if key in CORE_COLUMNS})
    core_columns = [CORE_COLUMNS[key] for key in core_keys]
    select_columns = ",".join(["id", "status_enum", *core_columns])
    snapshots: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
        f"SELECT {select_columns} FROM m_client WHERE id = ANY(%s)", (identifiers,)
    ).fetchall():
        client_id = str(row[0])
        snapshots[client_id] = {
            "status_enum": int(row[1]),
            "core": {key: row[index + 2] for index, key in enumerate(core_keys)},
            "tags": {}, "identifiers": {}, "addresses": {}, "datatables": {},
        }

    for client_id, tag_id, tag_group in conn.execute(
        "SELECT tm.client_id,t.id,t.tag_group FROM m_client_tag_mapping tm "
        "JOIN m_client_tag t ON t.id=tm.tag_id WHERE tm.client_id = ANY(%s)", (identifiers,)
    ).fetchall():
        snapshot = snapshots.get(str(client_id))
        if snapshot is not None:
            snapshot["tags"].setdefault(_fold(tag_group), set()).add(int(tag_id))

    for client_id, document_type, document_key in conn.execute(
        "SELECT client_id,document_type_id,document_key FROM m_client_identifier "
        "WHERE status=200 AND client_id = ANY(%s)", (identifiers,)
    ).fetchall():
        snapshot = snapshots.get(str(client_id))
        if snapshot is not None:
            snapshot["identifiers"][int(document_type)] = document_key

    address_columns = [
        "addressTypeId", "isActive", "addressLine1", "addressLine2", "addressLine3", "townVillage",
        "city", "countyDistrict", "stateProvinceId", "countryId", "postalCode",
    ]
    address_rows = conn.execute(
        "SELECT ca.client_id,ca.address_type_id,ca.is_active,a.address_line_1,a.address_line_2,a.address_line_3,"
        "a.town_village,a.city,a.county_district,a.state_province_id,a.country_id,a.postal_code "
        "FROM m_client_address ca JOIN m_address a ON a.id=ca.address_id WHERE ca.client_id = ANY(%s)",
        (identifiers,),
    ).fetchall()
    for row in address_rows:
        snapshot = snapshots.get(str(row[0]))
        if snapshot is not None:
            snapshot["addresses"][int(row[1])] = dict(zip(address_columns, row[1:]))

    tables = sorted({
        table for payload in expected.values()
        for table in [*payload["datatables"], *payload.get("absent_datatables", [])]
    })
    for table in tables:
        columns = sorted({
            column for payload in expected.values() for column in payload["datatables"].get(table, {})
        })
        if not IDENTIFIER.fullmatch(table) or any(not IDENTIFIER.fullmatch(column) for column in columns):
            raise ValueError("Unsafe datatable identifier during reconciliation")
        selected = ",".join(["client_id", *columns])
        for row in conn.execute(
            f"SELECT {selected} FROM {table} WHERE client_id = ANY(%s)", (identifiers,)
        ).fetchall():
            snapshot = snapshots.get(str(row[0]))
            if snapshot is not None:
                snapshot["datatables"][table] = {
                    column: row[index + 1] for index, column in enumerate(columns)
                }
    return snapshots


def snapshot_payload_matches(snapshot: dict[str, Any], payload: dict[str, Any],
                             expected_active: bool = False) -> bool:
    if expected_active and snapshot["status_enum"] != 300:
        return False
    for key, expected_value in payload["core"].items():
        if key in CORE_COLUMNS and not values_match(snapshot["core"].get(key), expected_value):
            return False
    expected_tag = payload.get("client_type_tag")
    if expected_tag and snapshot["tags"].get(_fold(expected_tag["group"]), set()) != {int(expected_tag["id"])}:
        return False
    for identifier in payload["identifiers"]:
        actual = snapshot["identifiers"].get(int(identifier["documentTypeId"]))
        if not values_match(actual, identifier["documentKey"]):
            return False
    for address in payload["addresses"]:
        actual = snapshot["addresses"].get(int(address["addressTypeId"]))
        if not actual or any(not values_match(actual.get(key), value)
                             for key, value in address.items() if key != "name"):
            return False
    for table, expected_row in payload["datatables"].items():
        actual = snapshot["datatables"].get(table)
        if actual is None or any(not values_match(actual.get(column), value)
                                 for column, value in expected_row.items()):
            return False
    if any(table in snapshot["datatables"] for table in payload.get("absent_datatables", [])):
        return False
    return True


def reconcile(settings: Settings, state: State, contract: ClientContract, run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    if run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Run belongs to a different target")
    plan = state.plan(run["plan_id"])
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Run belongs to a stale client contract")
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for KYC reconciliation")
    with postgres_connection(settings.target.pg_url) as conn:
        catalogs = TargetCatalogs.from_postgres(conn)
    items = state.run_items(run_id)
    results = Counter()
    # Load source and target state in bulk, then compare entirely in memory.
    with source_connection(settings.source) as source, postgres_connection(settings.target.pg_url) as target:
        source_rows = extract_clients(source, contract)
        source_by_key = {contract.source_key(row): row for row in source_rows}
        if len(source_by_key) != len(source_rows):
            raise RuntimeError("Duplicate Arissto client source key during reconciliation")
        expected: dict[str, dict[str, Any]] = {}
        pending: list[tuple[dict[str, Any], str]] = []
        for item in items:
            if item["status"] == "failed": results["failed"] += 1; continue
            if item["status"] == "quarantined": results["quarantined"] += 1; continue
            if not item["target_id"]: results["unresolved"] += 1; continue
            try:
                row = source_by_key.get(item["source_key"])
                if row is None or contract.hash_row(row, catalogs) != item["source_hash"]:
                    results["source_changed"] += 1
                    continue
                payload = contract.payload(row, catalogs)
                target_id = str(item["target_id"])
                if target_id in expected and expected[target_id] != payload:
                    results["reconcile_error"] += 1
                    continue
                expected[target_id] = payload
                pending.append((item, target_id))
            except Exception:
                results["reconcile_error"] += 1
        snapshots = load_target_payload_snapshots(target, expected)
        for _, target_id in pending:
            snapshot = snapshots.get(target_id)
            if snapshot is None:
                results["missing"] += 1
                continue
            matches = snapshot_payload_matches(snapshot, expected[target_id], contract.import_active)
            results["matched" if matches else "mismatched"] += 1
    return {"run_id": run_id, "status": run["status"], "counts": dict(results),
            "ok": not results["failed"] and not results["quarantined"] and not results["missing"]
                  and not results["unresolved"] and not results["source_changed"] and not results["mismatched"]
                  and not results["reconcile_error"]}
