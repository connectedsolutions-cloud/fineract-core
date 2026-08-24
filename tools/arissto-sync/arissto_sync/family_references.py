from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .arissto import IDENTIFIER, select_rows, source_connection
from .config import Settings
from .connections import FineractApi, postgres_connection, postgres_schema
from .engine import source_fingerprint
from .state import State


BLOCK = "client-family-references"
REQUIRED_TARGET_COLUMNS = {
    "id", "client_id", "firstname", "middlename", "lastname", "qualification", "relationship_cv_id",
    "marital_status_cv_id", "gender_cv_id", "date_of_birth", "age", "profession_cv_id", "mobile_number",
    "secondary_mobile_number", "address", "external_id", "source_relationship", "is_dependent",
}


class FamilyReferenceDataIssue(RuntimeError):
    """Non-PII reason why a reference cannot be synchronized safely."""


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    result = re.sub(r"\s+", " ", str(value).strip())
    return result or None


def normalize_relationship(value: Any) -> str:
    text = clean_text(value) or ""
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def normalize_slot(value: Any) -> str:
    if isinstance(value, Decimal):
        value = int(value)
    text = str(value).strip()
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise FamilyReferenceDataIssue("invalid_reference_slot")
    return text


@dataclass(frozen=True)
class FamilyReferenceContract:
    raw: dict[str, Any]
    relationships: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> "FamilyReferenceContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        for key in ("source", "target", "relationship_map"):
            if key not in value:
                raise ValueError(f"Family-reference mapping is missing {key!r}")
        source = value["source"]
        identifiers = [source[name] for name in (
            "table", "party_table", "company_key", "branch_key", "party_key", "external_key", "reference_key"
        )]
        identifiers.extend([value["target"]["table"]])
        if not all(IDENTIFIER.fullmatch(name) for name in identifiers):
            raise ValueError("Unsafe SQL identifier in family-reference mapping")
        relationships: dict[str, str] = {}
        for label, source_values in value["relationship_map"].items():
            if not label or not isinstance(source_values, list):
                raise ValueError("Invalid family-reference relationship mapping")
            for source_value in source_values:
                key = normalize_relationship(source_value)
                if key in relationships and relationships[key] != label:
                    raise ValueError(f"Duplicate relationship mapping: {source_value!r}")
                relationships[key] = label
        if "" not in relationships:
            raise ValueError("Family-reference relationship mapping must handle blank values explicitly")
        return cls(value, relationships)

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def query(self, source_key: str | None = None) -> tuple[str, tuple[Any, ...]]:
        source = self.raw["source"]
        sql = f"""
            SELECT
                [party].[{source['external_key']}] AS affiliation_number,
                [ref].[{source['reference_key']}] AS reference_slot,
                [ref].[NOMBRE_FAMILIAR] AS full_name,
                [ref].[TELEFONO] AS primary_phone,
                [ref].[TELEFONO2] AS secondary_phone,
                [ref].[DIRECCION] AS address,
                [ref].[PARENTESCO] AS source_relationship,
                [ref].[ID_EMPRESA] AS company_key,
                [ref].[ID_SUCURSAL] AS branch_key,
                [ref].[ID_SOCIO] AS party_key
            FROM [dbo].[{source['table']}] [ref]
            JOIN [dbo].[{source['party_table']}] [party]
              ON [party].[{source['company_key']}] = [ref].[{source['company_key']}]
             AND [party].[{source['branch_key']}] = [ref].[{source['branch_key']}]
             AND [party].[{source['party_key']}] = [ref].[{source['party_key']}]
        """
        params: tuple[Any, ...] = ()
        if source_key is not None:
            affiliation, slot = self.parse_source_key(source_key)
            sql += f" WHERE [party].[{source['external_key']}] = ? AND [ref].[{source['reference_key']}] = ?"
            params = (affiliation, int(slot))
        sql += f" ORDER BY [party].[{source['external_key']}], [ref].[{source['reference_key']}]"
        return sql, params

    def parse_source_key(self, value: str) -> tuple[str, str]:
        parts = value.strip().split(":")
        if len(parts) != 2 or not parts[0]:
            raise ValueError("Family-reference source key must be NUMERO_AFILIACION:ID_REF_FAM")
        return parts[0], normalize_slot(parts[1])

    def source_key(self, row: dict[str, Any]) -> str:
        affiliation = clean_text(row.get("affiliation_number"))
        if not affiliation or ":" in affiliation:
            raise FamilyReferenceDataIssue("missing_client_affiliation_number")
        return f"{affiliation}:{normalize_slot(row.get('reference_slot'))}"

    def external_id(self, row: dict[str, Any]) -> str:
        return self.raw["target"]["external_id_prefix"] + self.source_key(row)

    def relationship_label(self, value: Any) -> str:
        label = self.relationships.get(normalize_relationship(value))
        if label is None:
            raise FamilyReferenceDataIssue("unresolved_relationship")
        return label

    def payload(self, row: dict[str, Any], relationship_ids: dict[str, int]) -> dict[str, Any]:
        name = clean_text(row.get("full_name"))
        if not name:
            raise FamilyReferenceDataIssue("missing_reference_name")
        label = self.relationship_label(row.get("source_relationship"))
        relationship_id = relationship_ids.get(normalize_relationship(label))
        if relationship_id is None:
            raise FamilyReferenceDataIssue("missing_target_relationship")
        return {
            "externalId": self.external_id(row),
            "firstName": name,
            "middleName": None,
            "lastName": None,
            "qualification": None,
            "mobileNumber": clean_text(row.get("primary_phone")),
            "secondaryMobileNumber": clean_text(row.get("secondary_phone")),
            "address": clean_text(row.get("address")),
            "sourceRelationship": clean_text(row.get("source_relationship")),
            "relationshipId": int(relationship_id),
            "maritalStatusId": None,
            "genderId": None,
            "dateOfBirth": None,
            "age": None,
            "professionId": None,
            "isDependent": None,
            "locale": "es",
            "dateFormat": "yyyy-MM-dd",
        }

    def hash_row(self, row: dict[str, Any], relationship_ids: dict[str, int]) -> str:
        return hashlib.sha256(json.dumps(self.payload(row, relationship_ids), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def extract_family_references(conn: Any, contract: FamilyReferenceContract, source_key: str | None = None) -> list[dict[str, Any]]:
    sql, params = contract.query(source_key)
    return select_rows(conn, sql, params)


def filter_family_references_by_owner(rows: list[dict[str, Any]], owner_keys: set[str]) -> list[dict[str, Any]]:
    owners = {clean_text(key) for key in owner_keys}
    if None in owners or any(":" in key for key in owners if key):
        raise ValueError("Family-reference owner keys must be exact NUMERO_AFILIACION values")
    return [row for row in rows if clean_text(row.get("affiliation_number")) in owners]


def target_relationship_ids(conn: Any, contract: FamilyReferenceContract) -> dict[str, int]:
    code = contract.raw["target"]["relationship_code"]
    rows = conn.execute(
        "SELECT cv.id,cv.code_value FROM m_code c JOIN m_code_value cv ON cv.code_id=c.id "
        "WHERE c.code_name=%s AND cv.is_active=true", (code,),
    ).fetchall()
    result: dict[str, int] = {}
    for identifier, label in rows:
        key = normalize_relationship(label)
        if key in result:
            raise RuntimeError("duplicate_target_relationship")
        result[key] = int(identifier)
    return result


def _schema_signature(schema: dict[str, dict[str, str]], relationship_ids: dict[str, int]) -> str:
    material = {"schema": schema, "relationships": sorted(relationship_ids.items())}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def inspect_family_references(settings: Settings, contract: FamilyReferenceContract) -> dict[str, Any]:
    required_source = {
        contract.raw["source"]["table"]: {
            contract.raw["source"][name] for name in ("company_key", "branch_key", "party_key", "reference_key")
        } | {"NOMBRE_FAMILIAR", "TELEFONO", "TELEFONO2", "DIRECCION", "PARENTESCO"},
        contract.raw["source"]["party_table"]: {
            contract.raw["source"][name] for name in ("company_key", "branch_key", "party_key", "external_key")
        },
    }
    source_tables: list[dict[str, Any]] = []
    with source_connection(settings.source) as source:
        for table, required in required_source.items():
            rows = select_rows(source,
                "SELECT COLUMN_NAME AS column_name,DATA_TYPE AS data_type FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA=? AND TABLE_NAME=?", ("dbo", table))
            columns = {str(row["column_name"]): str(row["data_type"]) for row in rows}
            source_tables.append({"table": f"dbo.{table}", "columns": columns,
                                  "missing_columns": sorted(required - set(columns)),
                                  "ready": required <= set(columns)})
        rows = extract_family_references(source, contract)
    keys, unresolved = [], Counter()
    for row in rows:
        try:
            keys.append(contract.source_key(row))
            contract.relationship_label(row.get("source_relationship"))
        except FamilyReferenceDataIssue as exc:
            unresolved[str(exc)] += 1
    source_summary = {
        "rows": len(rows), "distinct_source_keys": len(set(keys)),
        "duplicate_source_keys": len(keys) - len(set(keys)),
        "distinct_owners": len({clean_text(row.get("affiliation_number")) for row in rows}),
        "issues": dict(unresolved),
    }
    blockers: list[dict[str, Any]] = []
    blockers.extend({"source_table": item["table"], "missing_columns": item["missing_columns"]}
                    for item in source_tables if not item["ready"])
    if source_summary["duplicate_source_keys"]:
        blockers.append({"source_identity": "duplicate_source_keys"})

    target_schema: dict[str, dict[str, str]] = {}
    relationship_ids: dict[str, int] = {}
    target_summary: dict[str, Any] = {"postgres_inspection": "not-configured"}
    if not settings.target.pg_url:
        blockers.append({"target": "postgres_inspection_required"})
        signature = _schema_signature({}, {})
    else:
        with postgres_connection(settings.target.pg_url) as target:
            target_schema = postgres_schema(target, [contract.raw["target"]["table"]])
            available = set(target_schema.get(contract.raw["target"]["table"], {}))
            missing_target = sorted(REQUIRED_TARGET_COLUMNS - available)
            if missing_target:
                blockers.append({"target_table": contract.raw["target"]["table"], "missing_columns": missing_target})
            relationship_ids = target_relationship_ids(target, contract)
            missing_relationships = sorted({label for label in contract.relationships.values()
                                            if normalize_relationship(label) not in relationship_ids})
            if missing_relationships:
                blockers.append({"target_relationships_missing": missing_relationships})
            unique_external_id = bool(target.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='m_family_members'::regclass "
                "AND conname='uk_m_family_members_external_id')"
            ).fetchone()[0])
            if not unique_external_id:
                blockers.append({"target_identity": "unique_external_id_constraint_missing"})
            client_rows = target.execute("SELECT id,external_id FROM m_client WHERE external_id IS NOT NULL").fetchall()
            clients = {str(external_id): int(identifier) for identifier, external_id in client_rows}
            owners = {clean_text(row.get("affiliation_number")) for row in rows}
            missing_owners = sorted(owner for owner in owners if owner and owner not in clients)
            if missing_owners:
                blockers.append({"client_linking": "unresolved_owners", "count": len(missing_owners)})
            duplicate_external_ids = target.execute(
                "SELECT COUNT(*) FROM (SELECT external_id FROM m_family_members WHERE external_id IS NOT NULL "
                "GROUP BY external_id HAVING COUNT(*)>1) duplicate"
            ).fetchone()[0]
            if duplicate_external_ids:
                blockers.append({"target_identity": "duplicate_external_ids", "count": int(duplicate_external_ids)})
            permissions = {row[0] for row in target.execute(
                "SELECT DISTINCT p.code FROM m_appuser u JOIN m_appuser_role ur ON ur.appuser_id=u.id "
                "JOIN m_role_permission rp ON rp.role_id=ur.role_id JOIN m_permission p ON p.id=rp.permission_id "
                "WHERE u.username=%s AND p.code IN "
                "('ALL_FUNCTIONS','READ_FAMILYMEMBERS','CREATE_FAMILYMEMBERS','UPDATE_FAMILYMEMBERS')",
                (settings.target.api_user,),
            ).fetchall()}
            required_permissions = {"READ_FAMILYMEMBERS", "CREATE_FAMILYMEMBERS", "UPDATE_FAMILYMEMBERS"}
            effective_permissions = required_permissions if "ALL_FUNCTIONS" in permissions else permissions
            if not required_permissions <= effective_permissions:
                blockers.append({"target_permissions_missing": sorted(required_permissions - permissions)})
            target_summary = {
                "schema_columns": sorted(available), "missing_columns": missing_target,
                "unique_external_id": unique_external_id,
                "relationship_values": len(relationship_ids),
                "resolved_owners": len(owners) - len(missing_owners), "unresolved_owners": len(missing_owners),
                "existing_family_members": int(target.execute("SELECT COUNT(*) FROM m_family_members").fetchone()[0]),
                "permissions": sorted(permissions),
            }
        signature = _schema_signature(target_schema, relationship_ids)
    return {
        "ready": not blockers, "block": BLOCK, "target_fingerprint": settings.target.fingerprint,
        "contract_hash": contract.contract_hash, "schema_signature": signature,
        "source_tables": source_tables, "source": source_summary, "target": target_summary,
        "blockers": blockers, "notes": contract.raw.get("notes", []),
    }


def _target_row_matches(row: dict[str, Any], client_id: int, payload: dict[str, Any]) -> bool:
    expected = {
        "client_id": int(client_id), "firstname": payload["firstName"], "middlename": None, "lastname": None,
        "qualification": None, "relationship_cv_id": int(payload["relationshipId"]), "marital_status_cv_id": None,
        "gender_cv_id": None, "date_of_birth": None, "age": None, "profession_cv_id": None,
        "mobile_number": payload["mobileNumber"], "secondary_mobile_number": payload["secondaryMobileNumber"],
        "address": payload["address"], "external_id": payload["externalId"],
        "source_relationship": payload["sourceRelationship"], "is_dependent": None,
    }
    return all(row.get(key) == value for key, value in expected.items())


def build_family_reference_plan(settings: Settings, state: State, contract: FamilyReferenceContract,
                                source_keys: list[str] | None = None,
                                owner_keys: set[str] | None = None) -> tuple[str, dict[str, Any]]:
    if source_keys is not None and owner_keys is not None:
        raise ValueError("Family-reference planning accepts source keys or owner keys, not both")
    inspection = inspect_family_references(settings, contract)
    if any(not item["ready"] for item in inspection["source_tables"]):
        raise RuntimeError("Required Arissto family-reference columns are missing")
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for family-reference planning")
    with source_connection(settings.source) as source:
        if source_keys:
            rows: list[dict[str, Any]] = []
            for key in dict.fromkeys(source_keys):
                matches = extract_family_references(source, contract, key)
                if len(matches) != 1:
                    raise RuntimeError(f"Expected exactly one Arissto family reference for source key {key}")
                rows.extend(matches)
        elif owner_keys is not None:
            rows = filter_family_references_by_owner(extract_family_references(source, contract), owner_keys)
        else:
            rows = extract_family_references(source, contract)
    with postgres_connection(settings.target.pg_url) as target:
        relationships = target_relationship_ids(target, contract)
        clients = {str(external_id): int(identifier) for identifier, external_id in target.execute(
            "SELECT id,external_id FROM m_client WHERE external_id IS NOT NULL"
        ).fetchall()}
        columns = ["id", *sorted(REQUIRED_TARGET_COLUMNS - {"id"})]
        target_rows = [dict(zip(columns, row)) for row in target.execute(
            f"SELECT {','.join(columns)} FROM m_family_members"
        ).fetchall()]
    by_external = {row["external_id"]: row for row in target_rows if row.get("external_id")}
    by_id = {str(row["id"]): row for row in target_rows}
    actions: list[dict[str, Any]] = []
    counts = Counter()
    seen: set[str] = set()
    for row in rows:
        try:
            key = contract.source_key(row)
        except FamilyReferenceDataIssue as exc:
            raise RuntimeError(str(exc)) from exc
        if key in seen:
            raise RuntimeError(f"Duplicate Arissto family-reference source key: {key}")
        seen.add(key)
        issue = None
        payload = None
        try:
            payload = contract.payload(row, relationships)
            row_hash = contract.hash_row(row, relationships)
        except FamilyReferenceDataIssue as exc:
            issue = str(exc)
            row_hash = hashlib.sha256(f"{contract.contract_hash}:{key}:{issue}".encode()).hexdigest()
        affiliation = clean_text(row.get("affiliation_number"))
        client_id = clients.get(affiliation or "")
        if client_id is None and issue is None:
            issue = "missing_target_client"
        external_id = contract.external_id(row)
        current = by_external.get(external_id)
        prior = state.mapping(settings.target.fingerprint, BLOCK, key)
        if prior and current and str(current["id"]) != str(prior["target_id"]):
            issue = "family_reference_identity_collision"
        elif prior and not current and prior["target_id"] in by_id:
            issue = "mapped_target_missing_external_id"
        target_id = str(current["id"]) if current else None
        if issue:
            action = "quarantine"
        elif current is None:
            action = "create"
        elif _target_row_matches(current, int(client_id), payload):
            action = "unchanged"
        else:
            action = "update"
        item = {"source_key": key, "source_hash": row_hash, "action": action,
                "target_id": target_id, "client_id": str(client_id) if client_id is not None else None}
        if issue:
            item["reason"] = issue
        actions.append(item)
        counts[action] += 1
    document = {
        "version": 1, "block": BLOCK, "target_fingerprint": settings.target.fingerprint,
        "source_fingerprint": source_fingerprint(settings), "contract_hash": contract.contract_hash,
        "schema_signature": inspection["schema_signature"],
        "applicable": inspection["ready"],
        "readiness_blocker_count": len(inspection["blockers"]),
        "scope": {
            "mode": "explicit-source-keys" if source_keys is not None else
                    "parent-client-source-keys" if owner_keys is not None else "full-block",
            "entity_count": len(rows),
            **({"owner_count": len(owner_keys)} if owner_keys is not None else {}),
        },
        "counts": dict(counts), "actions": actions,
    }
    plan_id = state.save_plan(settings.target.fingerprint, BLOCK, document["source_fingerprint"], contract.contract_hash, document)
    return plan_id, document


def apply_family_reference_plan(settings: Settings, state: State, contract: FamilyReferenceContract, plan_id: str,
                                production_confirmation: str | None = None,
                                only_keys: set[str] | None = None) -> tuple[str, dict[str, int]]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Plan belongs to a different block or target")
    if plan["source_fingerprint"] != source_fingerprint(settings) or plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Plan is stale: source or family-reference contract changed")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_family_references(settings, contract)
    if not inspection["ready"]:
        raise RuntimeError("Destination readiness changed; apply refused")
    if not plan["document"].get("applicable") or plan["document"].get("schema_signature") != inspection["schema_signature"]:
        raise RuntimeError("Plan is not applicable to the current destination schema")
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for family-reference apply")
    with postgres_connection(settings.target.pg_url) as target:
        relationships = target_relationship_ids(target, contract)
    api = FineractApi(settings.target)
    counts = Counter()
    run_id = state.start_run(plan)
    for action in plan["document"]["actions"]:
        key = action["source_key"]
        target_id = action.get("target_id")
        if only_keys is not None and key not in only_keys:
            continue
        if action["action"] == "quarantine":
            state.record_item(run_id, key, "quarantine", action["source_hash"], "quarantined", target_id,
                              f"FamilyReferenceDataIssue:{action.get('reason', 'unspecified')}")
            counts["quarantined"] += 1
            continue
        if action["action"] == "unchanged":
            state.record_item(run_id, key, "unchanged", action["source_hash"], "unchanged", target_id)
            counts["unchanged"] += 1
            continue
        try:
            with source_connection(settings.source) as source:
                rows = extract_family_references(source, contract, key)
            if len(rows) != 1 or contract.hash_row(rows[0], relationships) != action["source_hash"]:
                raise RuntimeError("source_changed_after_plan")
            payload = contract.payload(rows[0], relationships)
            affiliation = clean_text(rows[0].get("affiliation_number"))
            client = api.find_client(affiliation or "")
            if not client or str(client["id"]) != str(action.get("client_id")):
                raise RuntimeError("client_identity_changed_after_plan")
            client_id = str(client["id"])
            effective_action = action["action"]
            if effective_action == "create":
                recovered = [item for item in api.family_members(client_id)
                             if item.get("externalId") == payload["externalId"]]
                if len(recovered) > 1:
                    raise RuntimeError("family_reference_identity_collision")
                if recovered:
                    target_id = str(recovered[0]["id"])
                    effective_action = "update"
            if effective_action == "create":
                target_id = api.create_family_member(client_id, payload)
            elif effective_action == "update":
                if not target_id:
                    raise RuntimeError("missing_target_id")
                api.update_family_member(client_id, target_id, payload)
            state.save_mapping(settings.target.fingerprint, BLOCK, key, str(target_id), action["source_hash"])
            state.record_item(run_id, key, action["action"], action["source_hash"], "succeeded", str(target_id))
            counts[action["action"]] += 1
        except Exception as exc:
            message = str(exc).splitlines()[0]
            safe = message if message in {
                "source_changed_after_plan", "client_identity_changed_after_plan", "family_reference_identity_collision",
                "missing_target_id",
            } or isinstance(exc, FamilyReferenceDataIssue) else "redacted"
            state.record_item(run_id, key, action["action"], action["source_hash"], "failed", target_id,
                              f"{type(exc).__name__}:{safe}"[:240])
            counts["failed"] += 1
    state.finish_run(run_id, "completed_with_errors" if counts["failed"] or counts["quarantined"] else "completed", dict(counts))
    return run_id, dict(counts)


def _api_member_matches(member: dict[str, Any], payload: dict[str, Any], client_id: str) -> bool:
    expected = {
        "clientId": int(client_id), "firstName": payload["firstName"], "middleName": None, "lastName": None,
        "qualification": None, "relationshipId": int(payload["relationshipId"]), "maritalStatusId": None,
        "genderId": None, "dateOfBirth": None, "age": None, "professionId": None,
        "mobileNumber": payload["mobileNumber"], "secondaryMobileNumber": payload["secondaryMobileNumber"],
        "address": payload["address"], "externalId": payload["externalId"],
        "sourceRelationship": payload["sourceRelationship"], "isDependent": None,
    }
    return all(member.get(key) == value for key, value in expected.items())


def reconcile_family_references(settings: Settings, state: State, contract: FamilyReferenceContract,
                                run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Run belongs to a different block or target")
    plan = state.plan(run["plan_id"])
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Run belongs to a stale family-reference contract")
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for family-reference reconciliation")
    with postgres_connection(settings.target.pg_url) as target:
        relationships = target_relationship_ids(target, contract)
    api = FineractApi(settings.target)
    results = Counter()
    with source_connection(settings.source) as source:
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
                rows = extract_family_references(source, contract, item["source_key"])
                if len(rows) != 1 or contract.hash_row(rows[0], relationships) != item["source_hash"]:
                    results["source_changed"] += 1
                    continue
                affiliation = clean_text(rows[0].get("affiliation_number"))
                client = api.find_client(affiliation or "")
                if not client:
                    results["missing_client"] += 1
                    continue
                payload = contract.payload(rows[0], relationships)
                member = api.get_family_member(str(client["id"]), item["target_id"])
                results["matched" if _api_member_matches(member, payload, str(client["id"])) else "mismatched"] += 1
            except Exception:
                results["reconcile_error"] += 1
    failed = {"failed", "quarantined", "unresolved", "source_changed", "missing_client", "mismatched", "reconcile_error"}
    return {"run_id": run_id, "status": run["status"], "counts": dict(results),
            "ok": not any(results[name] for name in failed)}
