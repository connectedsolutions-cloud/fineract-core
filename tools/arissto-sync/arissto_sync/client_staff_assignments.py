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


BLOCK = "client-staff-assignments"
ROLES = ("promoter", "account_executive", "collections_manager")


class ClientStaffAssignmentDataIssue(RuntimeError):
    """Non-PII reason why an assignment cannot be synchronized safely."""


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class ClientStaffAssignmentContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "ClientStaffAssignmentContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        source, target = value.get("source", {}), value.get("target", {})
        identifiers = [
            source.get("table"), source.get("external_key"), source.get("company_key"),
            target.get("client_table"), target.get("staff_table"), target.get("datatable"),
            target.get("client_key"), target.get("company_column"),
        ]
        if set(source.get("roles", {})) != set(ROLES) or set(target.get("roles", {})) != set(ROLES):
            raise ValueError("Client staff assignment mapping must define all three reviewed roles")
        identifiers.extend(source["roles"].values())
        for role in ROLES:
            identifiers.extend((target["roles"][role].get("legacy_column"), target["roles"][role].get("staff_column")))
        if not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Unsafe or missing identifier in client staff assignment mapping")
        if value.get("depends_on") != ["clients", "employees"]:
            raise ValueError("Client staff assignments must depend on clients and employees")
        if value.get("missing_dependency_policy") != "quarantine":
            raise ValueError("Missing client or employee dependencies must quarantine")
        if value.get("unexpected_row_policy") != "quarantine-no-delete":
            raise ValueError("Unexpected assignment rows must never be deleted")
        return cls(value)

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True).encode()).hexdigest()

    def source_key(self, row: dict[str, Any]) -> str:
        value = clean(row.get("source_key"))
        if not value or ":" in value:
            raise ClientStaffAssignmentDataIssue("missing_client_affiliation_number")
        return value

    def company(self, row: dict[str, Any]) -> str:
        value = clean(row.get("company_id"))
        if not value or ":" in value:
            raise ClientStaffAssignmentDataIssue("missing_company_id")
        return value

    def staff_external_id(self, row: dict[str, Any], role: str) -> str | None:
        person_id = clean(row.get(role))
        return f"{self.company(row)}:{person_id}" if person_id else None

    def normalized(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_key": self.source_key(row),
            "company_id": self.company(row),
            **{role: clean(row.get(role)) for role in ROLES},
            **{f"{role}_external_id": self.staff_external_id(row, role) for role in ROLES},
        }

    def hash_row(self, row: dict[str, Any]) -> str:
        material = {"contract": self.contract_hash, **self.normalized(row)}
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()

    def query(self, source_key: str | None = None) -> tuple[str, tuple[Any, ...]]:
        source = self.raw["source"]
        role_sql = ", ".join(f"[{column}] AS {role}" for role, column in source["roles"].items())
        sql = (
            f"SELECT [{source['external_key']}] AS source_key, [{source['company_key']}] AS company_id, "
            f"{role_sql} FROM [dbo].[{source['table']}]"
        )
        params: tuple[Any, ...] = ()
        if source_key is not None:
            key = source_key.strip()
            if not key or ":" in key:
                raise ValueError("Assignment source key must be an exact NUMERO_AFILIACION")
            sql += f" WHERE [{source['external_key']}] = ?"
            params = (key,)
        sql += f" ORDER BY [{source['external_key']}]"
        return sql, params

    def payload(self, row: dict[str, Any], staff_ids: dict[str, int]) -> dict[str, Any]:
        normalized, target = self.normalized(row), self.raw["target"]
        payload: dict[str, Any] = {target["company_column"]: normalized["company_id"]}
        for role in ROLES:
            mapping = target["roles"][role]
            external_id = normalized[f"{role}_external_id"]
            payload[mapping["legacy_column"]] = normalized[role]
            payload[mapping["staff_column"]] = staff_ids.get(external_id) if external_id else None
        return payload


def extract_assignments(conn: Any, contract: ClientStaffAssignmentContract,
                        source_key: str | None = None) -> list[dict[str, Any]]:
    sql, params = contract.query(source_key)
    return select_rows(conn, sql, params)


def _schema_signature(source_columns: dict[str, str], target_schema: dict[str, dict[str, str]],
                      registered: bool) -> str:
    material = {"source": source_columns, "target": target_schema, "registered": registered}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def inspect_client_staff_assignments(settings: Settings, contract: ClientStaffAssignmentContract) -> dict[str, Any]:
    source, target = contract.raw["source"], contract.raw["target"]
    with source_connection(settings.source) as conn:
        columns = select_rows(
            conn,
            "SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA=? AND TABLE_NAME=?",
            ("dbo", source["table"]),
        )
        rows = extract_assignments(conn, contract)
    source_columns = {row["column_name"]: row["data_type"] for row in columns}
    required_source = {source["external_key"], source["company_key"], *source["roles"].values()}
    blockers: list[dict[str, Any]] = []
    missing_source = sorted(required_source - set(source_columns))
    if missing_source:
        blockers.append({"source_table": source["table"], "missing_columns": missing_source})

    target_schema: dict[str, dict[str, str]] = {}
    registered = False
    target_summary: dict[str, Any] = {"postgres_inspection": "not-configured"}
    if not settings.target.pg_url:
        blockers.append({"target": "postgres_inspection_required"})
    else:
        try:
            with postgres_connection(settings.target.pg_url) as conn:
                target_schema = postgres_schema(conn, [target["client_table"], target["staff_table"], target["datatable"]])
                required_target = {target["client_key"], target["company_column"], "created_at", "updated_at"}
                for role in ROLES:
                    required_target.update(target["roles"][role].values())
                missing_target = sorted(required_target - set(target_schema.get(target["datatable"], {})))
                if missing_target:
                    blockers.append({"target_table": target["datatable"], "missing_columns": missing_target})
                missing_staff = sorted({"id", "external_id", "is_active"} - set(target_schema.get(target["staff_table"], {})))
                if missing_staff:
                    blockers.append({"target_table": target["staff_table"], "missing_columns": missing_staff})
                registration = conn.execute(
                    "SELECT application_table_name FROM x_registered_table WHERE registered_table_name=%s",
                    (target["datatable"],),
                ).fetchone()
                registered = bool(registration and registration[0] == target["client_table"])
                if not registered:
                    blockers.append({"target_datatable": "client_staff_assignment_not_registered"})
                required_permissions = {
                    f"READ_{target['datatable']}", f"CREATE_{target['datatable']}", f"UPDATE_{target['datatable']}",
                }
                permissions = {row[0] for row in conn.execute(
                    "SELECT DISTINCT p.code FROM m_appuser u JOIN m_appuser_role ur ON ur.appuser_id=u.id "
                    "JOIN m_role_permission rp ON rp.role_id=ur.role_id JOIN m_permission p ON p.id=rp.permission_id "
                    "WHERE u.username=%s AND (p.code='ALL_FUNCTIONS' OR p.code = ANY(%s))",
                    (settings.target.api_user, sorted(required_permissions)),
                ).fetchall()}
                effective = required_permissions if "ALL_FUNCTIONS" in permissions else permissions
                if not required_permissions <= effective:
                    blockers.append({"target_permissions_missing": sorted(required_permissions - permissions)})
                target_summary = {
                    "datatable_registered": registered,
                    "existing_rows": int(conn.execute(f"SELECT COUNT(*) FROM {target['datatable']}").fetchone()[0])
                    if not missing_target else 0,
                    "permissions": sorted(permissions),
                }
        except Exception as exc:
            blockers.append({"target": "postgres_inspection_failed", "error_type": type(exc).__name__})
            target_summary = {"postgres_inspection": "failed", "error_type": type(exc).__name__}

    keys: list[str] = []
    issues = Counter()
    for row in rows:
        try:
            keys.append(contract.source_key(row))
            contract.company(row)
        except ClientStaffAssignmentDataIssue as exc:
            issues[str(exc)] += 1
    duplicates = len(keys) - len(set(keys))
    if duplicates:
        blockers.append({"source_identity": "duplicate_source_keys", "rows": duplicates})
    source_summary = {
        "rows": len(rows), "distinct_source_keys": len(set(keys)), "duplicate_source_keys": duplicates,
        **{f"{role}_populated": sum(clean(row.get(role)) is not None for row in rows) for role in ROLES},
        "rows_with_any_assignment": sum(any(clean(row.get(role)) is not None for role in ROLES) for row in rows),
        "rows_without_assignments": sum(all(clean(row.get(role)) is None for role in ROLES) for row in rows),
        "issues": dict(issues),
    }
    return {
        "ready": not blockers, "block": BLOCK, "target_fingerprint": settings.target.fingerprint,
        "contract_hash": contract.contract_hash,
        "schema_signature": _schema_signature(source_columns, target_schema, registered),
        "depends_on": contract.raw["depends_on"], "source": source_summary, "target": target_summary,
        "blockers": blockers, "notes": contract.raw.get("notes", []),
    }


def _target_rows(conn: Any, contract: ClientStaffAssignmentContract) -> dict[str, dict[str, Any]]:
    target = contract.raw["target"]
    role_joins, selected = [], []
    for index, role in enumerate(ROLES):
        alias = f"s{index}"
        staff_column = target["roles"][role]["staff_column"]
        role_joins.append(f"LEFT JOIN {target['staff_table']} {alias} ON {alias}.id=a.{staff_column}")
        selected.extend((f"a.{target['roles'][role]['legacy_column']}", f"{alias}.external_id", f"a.{staff_column}"))
    values = conn.execute(
        f"SELECT c.id,c.external_id,a.{target['client_key']} IS NOT NULL,a.{target['company_column']},"
        f"{','.join(selected)} FROM {target['client_table']} c "
        f"LEFT JOIN {target['datatable']} a ON a.{target['client_key']}=c.id {' '.join(role_joins)} "
        "WHERE c.external_id IS NOT NULL"
    ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        row: dict[str, Any] = {"client_id": int(value[0]), "exists": bool(value[2]), "company_id": clean(value[3])}
        offset = 4
        for role in ROLES:
            row[role] = clean(value[offset])
            row[f"{role}_external_id"] = clean(value[offset + 1])
            row[f"{role}_staff_id"] = int(value[offset + 2]) if value[offset + 2] is not None else None
            offset += 3
        result[str(value[1])] = row
    return result


def _staff_by_external(conn: Any, contract: ClientStaffAssignmentContract) -> dict[str, dict[str, Any]]:
    table = contract.raw["target"]["staff_table"]
    rows = conn.execute(
        f"SELECT id,external_id,is_active FROM {table} WHERE external_id IS NOT NULL"
    ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for staff_id, external_id, is_active in rows:
        key = str(external_id)
        if key in result:
            raise RuntimeError("Duplicate Fineract staff external ID")
        result[key] = {
            "id": int(staff_id), "active": bool(is_active),
        }
    return result


def _staff_ids(staff: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {external_id: int(value["id"]) for external_id, value in staff.items()}


def _matches(current: dict[str, Any], normalized: dict[str, Any]) -> bool:
    return current["company_id"] == normalized["company_id"] and all(
        current[role] == normalized[role]
        and current[f"{role}_external_id"] == normalized[f"{role}_external_id"]
        for role in ROLES
    )


def build_client_staff_assignment_plan(
    settings: Settings, state: State, contract: ClientStaffAssignmentContract,
    source_keys: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    inspection = inspect_client_staff_assignments(settings, contract)
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for assignment planning")
    with source_connection(settings.source) as source:
        if source_keys:
            rows: list[dict[str, Any]] = []
            for key in dict.fromkeys(source_keys):
                matches = extract_assignments(source, contract, key)
                if len(matches) != 1:
                    raise RuntimeError(f"Expected exactly one Arissto assignment row for source key {key}")
                rows.extend(matches)
        else:
            rows = extract_assignments(source, contract)
    with postgres_connection(settings.target.pg_url) as target_db:
        targets = _target_rows(target_db, contract) if inspection["ready"] else {}
        staff = _staff_by_external(target_db, contract)

    actions: list[dict[str, Any]] = []
    counts = Counter()
    missing_dependencies = 0
    seen: set[str] = set()
    for row in rows:
        issue: str | None = None
        try:
            normalized = contract.normalized(row)
            key, row_hash = normalized["source_key"], contract.hash_row(row)
        except ClientStaffAssignmentDataIssue as exc:
            key = clean(row.get("source_key")) or "invalid-source-key"
            normalized, issue = {}, str(exc)
            row_hash = hashlib.sha256(f"{contract.contract_hash}:{key}:{issue}".encode()).hexdigest()
        if key in seen:
            raise RuntimeError(f"Duplicate Arissto assignment source key: {key}")
        seen.add(key)
        current = targets.get(key)
        target_id = current["client_id"] if current else None
        if issue is None and current is None:
            issue = "missing_target_client"
        if issue is None:
            missing_roles = [role for role in ROLES if normalized[f"{role}_external_id"]
                             and normalized[f"{role}_external_id"] not in staff]
            if missing_roles:
                issue = "missing_target_staff:" + ",".join(missing_roles)
        if issue:
            action = "quarantine"
            missing_dependencies += 1
        elif not current["exists"]:
            action = "create"
        elif _matches(current, normalized):
            action = "unchanged"
        else:
            action = "update"
        item = {
            "entity_type": "client-assignment", "source_key": key, "source_hash": row_hash,
            "action": action, "target_id": target_id,
        }
        if issue:
            item["reason"] = issue
        actions.append(item)
        counts[action] += 1
    document = {
        "version": 1, "block": BLOCK, "target_fingerprint": settings.target.fingerprint,
        "source_fingerprint": source_fingerprint(settings.source), "contract_hash": contract.contract_hash,
        "schema_signature": inspection["schema_signature"], "depends_on": contract.raw["depends_on"],
        "applicable": inspection["ready"] and missing_dependencies == 0,
        "readiness_blocker_count": len(inspection["blockers"]) + missing_dependencies,
        "scope": {"mode": "explicit-source-keys" if source_keys else "full-block", "entity_count": len(rows)},
        "counts": dict(counts), "actions": actions,
    }
    plan_id = state.save_plan(
        settings.target.fingerprint, BLOCK, document["source_fingerprint"], contract.contract_hash, document
    )
    return plan_id, document


def apply_client_staff_assignment_plan(
    settings: Settings, state: State, contract: ClientStaffAssignmentContract, plan_id: str,
    production_confirmation: str | None = None, only_keys: set[str] | None = None,
) -> tuple[str, dict[str, int]]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Plan belongs to a different block or target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source) or plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Plan is stale: source or assignment contract changed")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_client_staff_assignments(settings, contract)
    if not inspection["ready"] or not plan["document"].get("applicable"):
        raise RuntimeError("Client staff assignment plan is not applicable to the current source and target")
    if plan["document"].get("schema_signature") != inspection["schema_signature"]:
        raise RuntimeError("Client staff assignment destination readiness changed; apply refused")
    with postgres_connection(settings.target.pg_url or "") as conn:
        current_targets, staff = _target_rows(conn, contract), _staff_by_external(conn, contract)
    api, counts = FineractApi(settings.target), Counter()
    target_table = contract.raw["target"]["datatable"]
    run_id = state.start_run(plan)
    for action in plan["document"]["actions"]:
        key, target_id = action["source_key"], action.get("target_id")
        if only_keys is not None and key not in only_keys:
            continue
        if action["action"] == "quarantine":
            state.record_item(run_id, key, "quarantine", action["source_hash"], "quarantined", target_id,
                              f"ClientStaffAssignmentDataIssue:{action.get('reason', 'unspecified')}")
            counts["quarantined"] += 1
            continue
        if action["action"] == "unchanged":
            state.record_item(run_id, key, "unchanged", action["source_hash"], "unchanged", target_id)
            counts["unchanged"] += 1
            continue
        try:
            with source_connection(settings.source) as source:
                rows = extract_assignments(source, contract, key)
            if len(rows) != 1 or contract.hash_row(rows[0]) != action["source_hash"]:
                raise RuntimeError("source_changed_after_plan")
            current = current_targets.get(key)
            if not current or str(current["client_id"]) != str(target_id):
                raise RuntimeError("client_identity_changed_after_plan")
            normalized = contract.normalized(rows[0])
            missing = [role for role in ROLES if normalized[f"{role}_external_id"]
                       and normalized[f"{role}_external_id"] not in staff]
            if missing:
                raise RuntimeError("staff_identity_changed_after_plan")
            payload = contract.payload(rows[0], _staff_ids(staff))
            body = datatable_api_payload(payload)
            if action["action"] == "create":
                api.create_datatable(target_table, str(target_id), body)
            else:
                api.upsert_datatable(target_table, str(target_id), body)
            state.save_mapping(settings.target.fingerprint, BLOCK, key, str(target_id), action["source_hash"])
            state.record_item(run_id, key, action["action"], action["source_hash"], "succeeded", str(target_id))
            counts[action["action"]] += 1
        except Exception as exc:
            message = str(exc).splitlines()[0]
            safe = message if message in {
                "source_changed_after_plan", "client_identity_changed_after_plan", "staff_identity_changed_after_plan",
            } else "redacted"
            state.record_item(run_id, key, action["action"], action["source_hash"], "failed", target_id,
                              f"{type(exc).__name__}:{safe}"[:240])
            counts["failed"] += 1
    state.finish_run(run_id, "completed_with_errors" if counts["failed"] or counts["quarantined"] else "completed",
                     dict(counts))
    return run_id, dict(counts)


def reconcile_client_staff_assignments(
    settings: Settings, state: State, contract: ClientStaffAssignmentContract, run_id: str,
) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Run belongs to a different block or target")
    plan = state.plan(run["plan_id"])
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Run belongs to a stale client staff assignment contract")
    results = Counter()
    with source_connection(settings.source) as source, postgres_connection(settings.target.pg_url or "") as target_db:
        targets, staff = _target_rows(target_db, contract), _staff_by_external(target_db, contract)
        for item in state.run_items(run_id):
            if item["status"] == "failed":
                results["failed"] += 1
                continue
            if item["status"] == "quarantined":
                results["quarantined"] += 1
                continue
            try:
                rows = extract_assignments(source, contract, item["source_key"])
                if len(rows) != 1 or contract.hash_row(rows[0]) != item["source_hash"]:
                    results["source_changed"] += 1
                    continue
                normalized = contract.normalized(rows[0])
                current = targets.get(item["source_key"])
                expected_staff_present = all(
                    not normalized[f"{role}_external_id"] or normalized[f"{role}_external_id"] in staff for role in ROLES
                )
                matches = bool(
                    current and current["exists"] and expected_staff_present and _matches(current, normalized)
                )
                results["matched" if matches else "mismatched"] += 1
            except Exception:
                results["reconcile_error"] += 1
    failed = {"failed", "quarantined", "source_changed", "mismatched", "reconcile_error"}
    return {"run_id": run_id, "status": run["status"], "counts": dict(results),
            "ok": not any(results[name] for name in failed)}
