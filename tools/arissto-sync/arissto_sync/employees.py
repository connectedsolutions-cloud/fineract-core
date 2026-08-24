from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .arissto import IDENTIFIER, select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import FineractApi, postgres_connection, postgres_schema
from .state import State


BLOCK = "employees"
REQUIRED_STAFF_COLUMNS = {
    "id", "office_id", "firstname", "lastname", "display_name", "external_id",
    "mobile_no", "email_address", "is_active", "joining_date", "is_loan_officer",
}
REQUIRED_STAFF_OFFICE_COLUMNS = {"staff_id", "office_id"}


class EmployeeDataIssue(RuntimeError):
    """Non-PII reason why an employee cannot be synchronized safely."""


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    result = re.sub(r"\s+", " ", str(value).strip())
    return result or None


def date_value(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


@dataclass(frozen=True)
class EmployeeContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "EmployeeContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        for key in ("source", "target", "core", "profile", "status_map", "assignment_status_map"):
            if key not in value:
                raise ValueError(f"Employee mapping is missing {key!r}")
        source, target = value["source"], value["target"]
        identifiers = [source.get(name) for name in (
            "table", "assignment_table", "company_key", "person_key", "branch_key",
            "status_key", "assignment_status_key",
        )]
        identifiers.extend([target.get("table"), target.get("office_table"), target.get("profile_table")])
        if not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Unsafe or missing SQL identifier in employee mapping")
        if set(value["status_map"].values()) != {False, True}:
            raise ValueError("Employee status mapping must include active and inactive values")
        if set(value["status_map"]) != set(value["assignment_status_map"]):
            raise ValueError("Employee and assignment status maps must cover the same source statuses")
        office_mapping = target.get("office_mapping")
        if not isinstance(office_mapping, dict) or not office_mapping:
            raise ValueError("Employee mapping requires at least one office mapping")
        if any(not str(branch).strip() or int(office_id) <= 0 for branch, office_id in office_mapping.items()):
            raise ValueError("Employee office mapping contains an invalid branch or office ID")
        required_core = {"firstname", "lastname", "joiningDate", "isActive", "officeIds", "externalId"}
        if not required_core <= set(value["core"]):
            raise ValueError("Employee mapping is missing required core-field classifications")
        try:
            joining_date_fallback = date_value(value["core"]["joiningDate"].get("fallback"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Employee joining-date fallback must be an ISO date") from exc
        if joining_date_fallback is None:
            raise ValueError("Employee joining-date fallback must be an ISO date")
        for field, mapping in value["core"].items():
            if mapping.get("disposition") not in {"migrate", "derived", "excluded"}:
                raise ValueError(f"Employee field {field!r} has an invalid disposition")
            if mapping.get("ownership") not in {"legacy-owned", "new-system-owned"}:
                raise ValueError(f"Employee field {field!r} has invalid ownership")
        if not isinstance(value["profile"], dict) or not value["profile"]:
            raise ValueError("Employee mapping requires profile fields")
        prohibited_user_fields = {
            "PASSWORD", "USER_GROUP", "GRUPO", "TIPO_ACCESO", "CHECK_OPR_INTERNA",
        }
        for destination, mapping in value["profile"].items():
            if not IDENTIFIER.fullmatch(destination):
                raise ValueError("Unsafe employee profile destination column")
            source_name = mapping.get("source", "")
            parts = source_name.split(".")
            if len(parts) != 2 or parts[0] not in {"PERSONAS_EMPRESA", "USUARIO"} or not IDENTIFIER.fullmatch(parts[1]):
                raise ValueError("Unsafe employee profile source column")
            if parts[0] == "USUARIO" and (parts[1] in prohibited_user_fields or parts[1].startswith("AUT_")):
                raise ValueError("Credentials and permission fields cannot be copied into the employee profile")
            if mapping.get("type") not in {"text", "date", "decimal", "integer"}:
                raise ValueError("Employee profile fields need a supported type")
        return cls(value)

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True).encode()).hexdigest()

    @property
    def office_mapping(self) -> dict[str, int]:
        return {str(key).strip(): int(value) for key, value in self.raw["target"]["office_mapping"].items()}

    @property
    def profile_table(self) -> str:
        return str(self.raw["target"]["profile_table"])

    def parse_source_key(self, value: str) -> tuple[str, str]:
        parts = [part.strip() for part in value.split(":")]
        if len(parts) != 2 or not all(parts):
            raise ValueError("Employee source key must be ID_EMPRESA:ID_PERSONA")
        return parts[0], parts[1]

    def source_key(self, row: dict[str, Any]) -> str:
        company = clean_text(row.get("company_key"))
        person = clean_text(row.get("person_key"))
        if not company or not person or ":" in company or ":" in person:
            raise EmployeeDataIssue("missing_employee_source_key")
        return f"{company}:{person}"

    def query(self, source_key: str | None = None) -> tuple[str, tuple[Any, ...]]:
        source = self.raw["source"]
        aliases = {"PERSONAS_EMPRESA": "person", "USUARIO": "legacy_user"}
        profile_columns = ",\n".join(
            f"                [{aliases[mapping['source'].split('.')[0]]}].[{mapping['source'].split('.')[1]}] "
            f"AS [profile__{destination}]"
            for destination, mapping in self.raw["profile"].items()
        )
        sql = f"""
            SELECT
                [person].[{source['company_key']}] AS company_key,
                [person].[{source['person_key']}] AS person_key,
                [person].[NOMBRE_PERSONA] AS firstname,
                [person].[APELLIDO_PERSONA] AS lastname,
                [person].[{source['status_key']}] AS employee_status,
                [person].[FECHA_INGRESO] AS employee_joining_date,
                [person].[ID_SUCURSAL] AS profile_branch_key,
                [person].[TELEFONO] AS mobile_no,
                [person].[TELEFONO1] AS mobile_no_1,
                [person].[TELEFONO2] AS mobile_no_2,
                [person].[EMAIL] AS email_address,
                [assignment].[{source['branch_key']}] AS branch_key,
                [assignment].[{source['assignment_status_key']}] AS assignment_status,
                [assignment].[FECHA_INICIO] AS assignment_start_date,
{profile_columns}
            FROM [dbo].[{source['table']}] [person]
            LEFT JOIN [dbo].[{source['assignment_table']}] [assignment]
              ON [assignment].[{source['company_key']}] = [person].[{source['company_key']}]
             AND [assignment].[{source['person_key']}] = [person].[{source['person_key']}]
            LEFT JOIN [dbo].[USUARIO] [legacy_user]
              ON [legacy_user].[ID_USUARIO] = [person].[ID_USUARIO]
        """
        params: tuple[Any, ...] = ()
        if source_key is not None:
            company, person = self.parse_source_key(source_key)
            sql += (
                f" WHERE [person].[{source['company_key']}] = ?"
                f" AND [person].[{source['person_key']}] = ?"
            )
            params = (company, person)
        sql += f" ORDER BY [person].[{source['company_key']}], [person].[{source['person_key']}]"
        return sql, params

    def payload(self, row: dict[str, Any]) -> dict[str, Any]:
        firstname = clean_text(row.get("firstname"))
        lastname = clean_text(row.get("lastname"))
        if not firstname:
            raise EmployeeDataIssue("missing_employee_firstname")
        if not lastname:
            raise EmployeeDataIssue("missing_employee_lastname")
        if len(firstname) > 50:
            raise EmployeeDataIssue("employee_firstname_too_long")
        if len(lastname) > 50:
            raise EmployeeDataIssue("employee_lastname_too_long")

        status = clean_text(row.get("employee_status"))
        status_map = self.raw["status_map"]
        if status not in status_map:
            raise EmployeeDataIssue("unmapped_employee_status")
        expected_assignment_status = str(self.raw["assignment_status_map"][status])
        assignment_status = clean_text(row.get("assignment_status"))
        assignment_branch = clean_text(row.get("branch_key"))
        if assignment_status is None and assignment_branch is not None:
            raise EmployeeDataIssue("missing_employee_office_assignment_status")
        if assignment_status is not None and assignment_status != expected_assignment_status:
            raise EmployeeDataIssue("employee_office_status_mismatch")

        branch = assignment_branch or clean_text(row.get("profile_branch_key"))
        if not branch:
            raise EmployeeDataIssue("missing_employee_office_assignment")
        office_id = self.office_mapping.get(branch)
        if office_id is None:
            raise EmployeeDataIssue("unmapped_employee_office")

        joining_date = (
            date_value(row.get("employee_joining_date"))
            or date_value(row.get("assignment_start_date"))
            or date_value(self.raw["core"]["joiningDate"]["fallback"])
        )

        mobile_no = next((value for value in (
            clean_text(row.get("mobile_no")), clean_text(row.get("mobile_no_1")), clean_text(row.get("mobile_no_2")),
        ) if value), None)
        email_address = clean_text(row.get("email_address"))
        if mobile_no and len(mobile_no) > 50:
            raise EmployeeDataIssue("employee_mobile_too_long")
        if email_address and len(email_address) > 150:
            raise EmployeeDataIssue("employee_email_too_long")

        return {
            "officeIds": [int(office_id)],
            "firstname": firstname,
            "lastname": lastname,
            "isActive": bool(status_map[status]),
            "joiningDate": joining_date.isoformat(),
            "externalId": self.source_key(row),
            "mobileNo": mobile_no,
            "emailAddress": email_address,
            "dateFormat": "yyyy-MM-dd",
            "locale": "en",
        }

    def profile_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for destination, mapping in self.raw["profile"].items():
            value = row.get(f"profile__{destination}")
            kind = mapping["type"]
            if kind == "text":
                normalized = clean_text(value)
            elif kind == "date":
                parsed = date_value(value)
                normalized = parsed.isoformat() if parsed else None
            elif kind == "decimal":
                normalized = float(Decimal(str(value))) if value is not None else None
            elif kind == "integer":
                normalized = int(value) if value is not None else None
            else:  # guarded by load()
                raise ValueError(f"Unsupported employee profile type: {kind}")
            result[destination] = normalized
        return result

    def hash_row(self, row: dict[str, Any]) -> str:
        material = {
            "contract": self.contract_hash,
            "core": self.payload(row),
            "profile": self.profile_payload(row),
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def extract_employees(conn: Any, contract: EmployeeContract, source_key: str | None = None) -> list[dict[str, Any]]:
    sql, params = contract.query(source_key)
    return select_rows(conn, sql, params)


def _source_requirements(contract: EmployeeContract) -> dict[str, set[str]]:
    source = contract.raw["source"]
    requirements = {
        source["table"]: {
            source["company_key"], source["person_key"], source["status_key"],
            "NOMBRE_PERSONA", "APELLIDO_PERSONA", "FECHA_INGRESO", "TELEFONO", "TELEFONO1", "TELEFONO2",
            "EMAIL", "ID_USUARIO",
        },
        source["assignment_table"]: {
            source["company_key"], source["person_key"], source["branch_key"],
            source["assignment_status_key"], "FECHA_INICIO",
        },
    }
    for mapping in contract.raw["profile"].values():
        table, column = mapping["source"].split(".")
        requirements.setdefault(table, set()).add(column)
    return requirements


def _schema_signature(
    source_tables: list[dict[str, Any]],
    target_schema: dict[str, dict[str, str]],
    offices: list[int],
    unique_external_id: bool,
    unique_display_name: bool,
    unique_mobile_no: bool,
) -> str:
    material = {
        "source_tables": source_tables,
        "target_schema": target_schema,
        "offices": sorted(offices),
        "unique_external_id": unique_external_id,
        "unique_display_name": unique_display_name,
        "unique_mobile_no": unique_mobile_no,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def _has_unique_column(conn: Any, table: str, column: str) -> bool:
    return bool(conn.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu ON kcu.constraint_name=tc.constraint_name "
        "AND kcu.table_schema=tc.table_schema WHERE tc.table_schema='public' AND tc.table_name=%s "
        "AND tc.constraint_type='UNIQUE' AND kcu.column_name=%s)",
        (table, column),
    ).fetchone()[0])


def inspect_employees(settings: Settings, contract: EmployeeContract) -> dict[str, Any]:
    source_tables: list[dict[str, Any]] = []
    with source_connection(settings.source) as source:
        for table, required in _source_requirements(contract).items():
            rows = select_rows(
                source,
                "SELECT COLUMN_NAME AS column_name,DATA_TYPE AS data_type FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA=? AND TABLE_NAME=?",
                ("dbo", table),
            )
            columns = {str(row["column_name"]): str(row["data_type"]) for row in rows}
            source_tables.append({
                "table": f"dbo.{table}",
                "columns": columns,
                "missing_columns": sorted(required - set(columns)),
                "ready": required <= set(columns),
            })
        rows = extract_employees(source, contract)

    keys: list[str] = []
    issues = Counter()
    display_names = Counter()
    valid_payload_rows = 0
    for row in rows:
        try:
            keys.append(contract.source_key(row))
            payload = contract.payload(row)
            display_names[f"{payload['lastname']}, {payload['firstname']}".casefold()] += 1
            valid_payload_rows += 1
        except EmployeeDataIssue as exc:
            issues[str(exc)] += 1
    duplicate_display_rows = sum(count for count in display_names.values() if count > 1)
    if duplicate_display_rows:
        issues["duplicate_employee_display_name"] += duplicate_display_rows
    source_summary = {
        "rows": len(rows),
        "distinct_source_keys": len(set(keys)),
        "duplicate_source_keys": len(keys) - len(set(keys)),
        "duplicate_display_name_rows": duplicate_display_rows,
        "migratable_rows": valid_payload_rows - duplicate_display_rows,
        "active_rows": sum(contract.raw["status_map"].get(clean_text(row.get("employee_status"))) is True for row in rows),
        "inactive_rows": sum(contract.raw["status_map"].get(clean_text(row.get("employee_status"))) is False for row in rows),
        "rows_using_assignment_date_fallback": sum(
            date_value(row.get("employee_joining_date")) is None and date_value(row.get("assignment_start_date")) is not None
            for row in rows
        ),
        "rows_using_snapshot_date_fallback": sum(
            date_value(row.get("employee_joining_date")) is None and date_value(row.get("assignment_start_date")) is None
            for row in rows
        ),
        "rows_using_profile_office_fallback": sum(
            clean_text(row.get("branch_key")) is None and clean_text(row.get("profile_branch_key")) is not None for row in rows
        ),
        "profiles_with_mobile": sum(bool(clean_text(row.get("mobile_no"))) for row in rows),
        "profiles_with_email": sum(bool(clean_text(row.get("email_address"))) for row in rows),
        "profiles_with_legacy_user_id": sum(bool(clean_text(row.get("profile__legacy_user_id"))) for row in rows),
        "profiles_with_legacy_username": sum(bool(clean_text(row.get("profile__legacy_username"))) for row in rows),
        "issues": dict(issues),
    }
    blockers: list[dict[str, Any]] = [
        {"source_table": item["table"], "missing_columns": item["missing_columns"]}
        for item in source_tables if not item["ready"]
    ]
    if source_summary["duplicate_source_keys"]:
        blockers.append({"source_identity": "duplicate_source_keys"})

    target_schema: dict[str, dict[str, str]] = {}
    target_summary: dict[str, Any] = {"postgres_inspection": "not-configured"}
    offices: list[int] = []
    unique_external_id = False
    unique_display_name = False
    unique_mobile_no = False
    if not settings.target.pg_url:
        blockers.append({"target": "postgres_inspection_required"})
    else:
        try:
            with postgres_connection(settings.target.pg_url) as target:
                target_schema = postgres_schema(target, [
                    contract.raw["target"]["table"], contract.raw["target"]["office_table"],
                    contract.profile_table, "m_office",
                ])
                staff_columns = set(target_schema.get(contract.raw["target"]["table"], {}))
                office_columns = set(target_schema.get(contract.raw["target"]["office_table"], {}))
                profile_columns = set(target_schema.get(contract.profile_table, {}))
                missing_staff = sorted(REQUIRED_STAFF_COLUMNS - staff_columns)
                missing_office = sorted(REQUIRED_STAFF_OFFICE_COLUMNS - office_columns)
                missing_profile = sorted(({"staff_id"} | set(contract.raw["profile"])) - profile_columns)
                if missing_staff:
                    blockers.append({"target_table": "m_staff", "missing_columns": missing_staff})
                if missing_office:
                    blockers.append({"target_table": "m_staff_office", "missing_columns": missing_office})
                if missing_profile:
                    blockers.append({"target_table": contract.profile_table, "missing_columns": missing_profile})
                offices = [int(row[0]) for row in target.execute("SELECT id FROM m_office").fetchall()]
                missing_mapped_offices = sorted(set(contract.office_mapping.values()) - set(offices))
                if missing_mapped_offices:
                    blockers.append({"target_offices_missing": missing_mapped_offices})
                unique_external_id = _has_unique_column(target, "m_staff", "external_id")
                unique_display_name = _has_unique_column(target, "m_staff", "display_name")
                unique_mobile_no = _has_unique_column(target, "m_staff", "mobile_no")
                if not unique_external_id:
                    blockers.append({"target_identity": "unique_staff_external_id_constraint_missing"})
                if not unique_display_name:
                    blockers.append({"target_identity": "unique_staff_display_name_constraint_missing"})
                if unique_mobile_no:
                    blockers.append({"target_contact": "unique_staff_mobile_constraint_must_be_removed"})
                registration = target.execute(
                    "SELECT application_table_name FROM x_registered_table WHERE registered_table_name=%s",
                    (contract.profile_table,),
                ).fetchone()
                if not registration or registration[0] != "m_staff":
                    blockers.append({"target_datatable": "staff_profile_not_registered"})
                profile_permissions = {
                    f"READ_{contract.profile_table}", f"CREATE_{contract.profile_table}", f"UPDATE_{contract.profile_table}",
                }
                core_permissions = {"READ_STAFF", "CREATE_STAFF", "UPDATE_STAFF"}
                all_required_permissions = core_permissions | profile_permissions
                permissions = {row[0] for row in target.execute(
                    "SELECT DISTINCT p.code FROM m_appuser u JOIN m_appuser_role ur ON ur.appuser_id=u.id "
                    "JOIN m_role_permission rp ON rp.role_id=ur.role_id JOIN m_permission p ON p.id=rp.permission_id "
                    "WHERE u.username=%s AND (p.code='ALL_FUNCTIONS' OR p.code = ANY(%s))",
                    (settings.target.api_user, sorted(all_required_permissions)),
                ).fetchall()}
                effective_permissions = all_required_permissions if "ALL_FUNCTIONS" in permissions else permissions
                if not all_required_permissions <= effective_permissions:
                    blockers.append({"target_permissions_missing": sorted(all_required_permissions - permissions)})
                target_summary = {
                    "schema_columns": sorted(staff_columns),
                    "staff_office_columns": sorted(office_columns),
                    "staff_profile_columns": sorted(profile_columns),
                    "missing_columns": missing_staff + missing_office + missing_profile,
                    "mapped_offices": sorted(set(contract.office_mapping.values()) & set(offices)),
                    "unique_external_id": unique_external_id,
                    "unique_display_name": unique_display_name,
                    "unique_mobile_no": unique_mobile_no,
                    "profile_registered": bool(registration and registration[0] == "m_staff"),
                    "existing_staff": int(target.execute("SELECT COUNT(*) FROM m_staff").fetchone()[0]),
                    "permissions": sorted(permissions),
                }
        except Exception as exc:
            # Inspection should still report source readiness when the local
            # destination is absent or offline. Do not leak connection details.
            target_summary = {"postgres_inspection": "failed", "error_type": type(exc).__name__}
            blockers.append({"target": "postgres_inspection_failed", "error_type": type(exc).__name__})
    signature = _schema_signature(
        source_tables, target_schema, offices, unique_external_id, unique_display_name, unique_mobile_no
    )
    return {
        "ready": not blockers,
        "block": BLOCK,
        "target_fingerprint": settings.target.fingerprint,
        "contract_hash": contract.contract_hash,
        "schema_signature": signature,
        "source_tables": source_tables,
        "source": source_summary,
        "target": target_summary,
        "blockers": blockers,
        "notes": contract.raw.get("notes", []),
    }


def _values_match(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    if isinstance(actual, (date, datetime)) or isinstance(expected, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", expected):
        try:
            return date_value(actual) == date_value(expected)
        except (TypeError, ValueError):
            pass
    if isinstance(actual, Decimal) or isinstance(expected, float):
        return Decimal(str(actual)) == Decimal(str(expected))
    return actual == expected


def _target_row_matches(
    row: dict[str, Any], payload: dict[str, Any], profile_payload: dict[str, Any] | None = None,
) -> bool:
    expected_offices = sorted(int(value) for value in payload["officeIds"])
    actual_offices = sorted(int(value) for value in row.get("office_ids", []))
    return (
        row.get("firstname") == payload["firstname"]
        and row.get("lastname") == payload["lastname"]
        and row.get("external_id") == payload["externalId"]
        and clean_text(row.get("mobile_no")) == payload.get("mobileNo")
        and clean_text(row.get("email_address")) == payload.get("emailAddress")
        and bool(row.get("is_active")) is payload["isActive"]
        and date_value(row.get("joining_date")) == date_value(payload["joiningDate"])
        and row.get("office_id") is not None
        and int(row["office_id"]) == expected_offices[0]
        and actual_offices == expected_offices
        and (
            profile_payload is None
            or all(_values_match((row.get("profile") or {}).get(column), expected)
                       for column, expected in profile_payload.items())
        )
    )


def _target_staff_rows(conn: Any, contract: EmployeeContract) -> list[dict[str, Any]]:
    columns = [
        "id", "office_id", "firstname", "lastname", "display_name", "external_id",
        "mobile_no", "email_address", "is_active", "joining_date", "is_loan_officer", "office_ids",
    ]
    values = conn.execute(
        "SELECT s.id,s.office_id,s.firstname,s.lastname,s.display_name,s.external_id,s.mobile_no,s.email_address,s.is_active,s.joining_date,"
        "s.is_loan_officer,COALESCE(array_agg(so.office_id ORDER BY so.office_id) "
        "FILTER (WHERE so.office_id IS NOT NULL),ARRAY[]::bigint[]) AS office_ids "
        "FROM m_staff s LEFT JOIN m_staff_office so ON so.staff_id=s.id GROUP BY s.id"
    ).fetchall()
    result = [dict(zip(columns, row)) for row in values]
    profile_columns = list(contract.raw["profile"])
    quoted_columns = ",".join(profile_columns)
    profile_values = conn.execute(
        f"SELECT staff_id,{quoted_columns} FROM {contract.profile_table}"
    ).fetchall()
    profiles = {
        str(row[0]): dict(zip(profile_columns, row[1:]))
        for row in profile_values
    }
    for row in result:
        row["profile"] = profiles.get(str(row["id"]))
    return result


def build_employee_plan(
    settings: Settings,
    state: State,
    contract: EmployeeContract,
    source_keys: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    inspection = inspect_employees(settings, contract)
    if any(not item["ready"] for item in inspection["source_tables"]):
        raise RuntimeError("Required Arissto employee columns are missing")
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for employee planning")
    with source_connection(settings.source) as source:
        if source_keys:
            rows: list[dict[str, Any]] = []
            for key in dict.fromkeys(source_keys):
                matches = extract_employees(source, contract, key)
                if len(matches) != 1:
                    raise RuntimeError(f"Expected exactly one Arissto employee for source key {key}")
                rows.extend(matches)
        else:
            rows = extract_employees(source, contract)
    with postgres_connection(settings.target.pg_url) as target:
        target_rows = _target_staff_rows(target, contract)

    by_external = {row["external_id"]: row for row in target_rows if row.get("external_id")}
    by_id = {str(row["id"]): row for row in target_rows}
    by_display = {str(row["display_name"]).casefold(): row for row in target_rows if row.get("display_name")}
    source_display_names = Counter()
    for row in rows:
        try:
            source_payload = contract.payload(row)
            source_display_names[
                f"{source_payload['lastname']}, {source_payload['firstname']}".casefold()
            ] += 1
        except EmployeeDataIssue:
            pass
    actions: list[dict[str, Any]] = []
    counts = Counter()
    seen: set[str] = set()
    for row in rows:
        key = contract.source_key(row)
        if key in seen:
            raise RuntimeError(f"Duplicate Arissto employee source key: {key}")
        seen.add(key)
        issue = None
        payload = None
        try:
            payload = contract.payload(row)
            row_hash = contract.hash_row(row)
        except EmployeeDataIssue as exc:
            issue = str(exc)
            row_hash = hashlib.sha256(f"{contract.contract_hash}:{key}:{issue}".encode()).hexdigest()

        current = by_external.get(key)
        prior = state.mapping(settings.target.fingerprint, BLOCK, key)
        if prior and current and str(current["id"]) != str(prior["target_id"]):
            issue = "employee_identity_collision"
        elif prior and not current and prior["target_id"] in by_id:
            issue = "mapped_staff_missing_external_id"
        if payload is not None:
            display_name = f"{payload['lastname']}, {payload['firstname']}".casefold()
            if source_display_names[display_name] > 1:
                issue = "duplicate_employee_display_name"
            display_collision = by_display.get(display_name)
            if display_collision and (current is None or display_collision["id"] != current["id"]):
                issue = "employee_display_name_collision"

        target_id = str(current["id"]) if current else None
        if issue:
            action = "quarantine"
        elif current is None:
            action = "create"
        elif _target_row_matches(current, payload, contract.profile_payload(row)):
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
        "applicable": inspection["ready"],
        "readiness_blocker_count": len(inspection["blockers"]),
        "scope": {
            "mode": "explicit-source-keys" if source_keys else "full-block",
            "entity_count": len(rows),
        },
        "counts": dict(counts),
        "actions": actions,
    }
    plan_id = state.save_plan(
        settings.target.fingerprint, BLOCK, document["source_fingerprint"], contract.contract_hash, document
    )
    return plan_id, document


def apply_employee_plan(
    settings: Settings,
    state: State,
    contract: EmployeeContract,
    plan_id: str,
    production_confirmation: str | None = None,
    only_keys: set[str] | None = None,
) -> tuple[str, dict[str, int]]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Plan belongs to a different block or target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source) or plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Plan is stale: source or employee contract changed")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_employees(settings, contract)
    if not inspection["ready"] or not plan["document"].get("applicable"):
        raise RuntimeError("Employee plan is not applicable to the current source and target")
    if plan["document"].get("schema_signature") != inspection["schema_signature"]:
        raise RuntimeError("Employee destination readiness changed; apply refused")

    api = FineractApi(settings.target)
    counts = Counter()
    run_id = state.start_run(plan)
    for action in plan["document"]["actions"]:
        key, target_id = action["source_key"], action.get("target_id")
        if only_keys is not None and key not in only_keys:
            continue
        if action["action"] == "quarantine":
            state.record_item(
                run_id, key, "quarantine", action["source_hash"], "quarantined", target_id,
                f"EmployeeDataIssue:{action.get('reason', 'unspecified')}",
            )
            counts["quarantined"] += 1
            continue
        if action["action"] == "unchanged":
            state.record_item(run_id, key, "unchanged", action["source_hash"], "unchanged", target_id)
            counts["unchanged"] += 1
            continue
        try:
            with source_connection(settings.source) as source:
                rows = extract_employees(source, contract, key)
            if len(rows) != 1 or contract.hash_row(rows[0]) != action["source_hash"]:
                raise RuntimeError("source_changed_after_plan")
            payload = contract.payload(rows[0])
            profile_payload = {
                **contract.profile_payload(rows[0]),
                "locale": "en",
                "dateFormat": "yyyy-MM-dd",
            }
            effective_action = action["action"]
            freshly_created = False
            if effective_action == "create":
                recovered = api.find_staff(payload["externalId"])
                if recovered:
                    target_id = str(recovered["id"])
                    effective_action = "update"
            if effective_action == "create":
                target_id = api.create_staff(payload)
                freshly_created = True
            elif effective_action == "update":
                if not target_id:
                    raise RuntimeError("missing_target_id")
                api.update_staff(target_id, payload)
            (api.create_datatable if freshly_created else api.upsert_datatable)(
                contract.profile_table, str(target_id), profile_payload
            )
            state.save_mapping(settings.target.fingerprint, BLOCK, key, str(target_id), action["source_hash"])
            state.record_item(run_id, key, action["action"], action["source_hash"], "succeeded", str(target_id))
            counts[action["action"]] += 1
        except Exception as exc:
            message = str(exc).splitlines()[0]
            safe = message if message in {
                "source_changed_after_plan", "employee_identity_collision", "employee_display_name_collision",
                "missing_target_id",
            } or isinstance(exc, EmployeeDataIssue) else "redacted"
            state.record_item(
                run_id, key, action["action"], action["source_hash"], "failed", target_id,
                f"{type(exc).__name__}:{safe}"[:240],
            )
            counts["failed"] += 1
    state.finish_run(
        run_id,
        "completed_with_errors" if counts["failed"] or counts["quarantined"] else "completed",
        dict(counts),
    )
    return run_id, dict(counts)


def reconcile_employees(
    settings: Settings,
    state: State,
    contract: EmployeeContract,
    run_id: str,
) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Run belongs to a different block or target")
    plan = state.plan(run["plan_id"])
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Run belongs to a stale employee contract")
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for employee reconciliation")

    results = Counter()
    with source_connection(settings.source) as source, postgres_connection(settings.target.pg_url) as target:
        target_rows = {str(row["id"]): row for row in _target_staff_rows(target, contract)}
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
                rows = extract_employees(source, contract, item["source_key"])
                if len(rows) != 1 or contract.hash_row(rows[0]) != item["source_hash"]:
                    results["source_changed"] += 1
                    continue
                current = target_rows.get(str(item["target_id"]))
                if current is None:
                    results["missing_staff"] += 1
                    continue
                payload = contract.payload(rows[0])
                results[
                    "matched" if _target_row_matches(current, payload, contract.profile_payload(rows[0])) else "mismatched"
                ] += 1
            except Exception:
                results["reconcile_error"] += 1
    failed = {
        "failed", "quarantined", "unresolved", "source_changed", "missing_staff", "mismatched", "reconcile_error",
    }
    return {
        "run_id": run_id,
        "status": run["status"],
        "counts": dict(results),
        "ok": not any(results[name] for name in failed),
    }
