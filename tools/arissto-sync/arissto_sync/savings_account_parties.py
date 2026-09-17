from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .arissto import IDENTIFIER, select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import FineractApi, postgres_connection, postgres_schema
from .state import State


BLOCK = "savings-account-parties"
ACCOUNT_TABLE = "AHO_CUENTA_AHORRO"
TARGET_COLUMNS = {
    "credesal_savings_beneficiary": {
        "id", "savings_account_id", "external_id", "given_name", "surname", "allocation_percentage",
        "date_of_birth", "source_age", "dui", "relationship", "address", "phone", "communicate_designation",
        "source_hash", "is_active",
    },
    "credesal_savings_authorized_person": {
        "id", "savings_account_id", "external_id", "given_name", "surname", "date_of_birth", "dui",
        "relationship", "address", "phone", "print_on_contract", "print_on_passbook", "signature_reference",
        "source_hash", "is_active",
    },
    "credesal_savings_migration_account": {
        "source_system", "source_key", "savings_account_id", "migration_status",
    },
}


class SavingsAccountPartyDataIssue(RuntimeError):
    """Non-sensitive reason why an account party collection cannot be migrated safely."""


def clean(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).strip().split())
    return result or None


def truth(value: Any) -> bool | None:
    text = clean(value)
    if text is None:
        return None
    return text.upper() in {"1", "S", "Y", "TRUE"}


def iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, list) and len(value) == 3:
        return f"{value[0]}-{int(value[1]):02d}-{int(value[2]):02d}"
    return str(value)[:10]


def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in sorted(value.items()):
            if key in {"id", "savingsAccountId", "sourceHash"} or item is None:
                continue
            if key == "allocationPercentage" and item is not None:
                result[key] = format(Decimal(str(item)), ".2f")
            elif key == "dateOfBirth":
                result[key] = iso_date(item)
            else:
                result[key] = canonical(item)
        return result
    if isinstance(value, list):
        items = [canonical(item) for item in value]
        return sorted(items, key=lambda item: str(item.get("externalId"))) if all(isinstance(item, dict) for item in items) else items
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return iso_date(value)
    return value


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class SavingsAccountPartyContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "SavingsAccountPartyContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        for key in ("source", "target", "identity", "rules", "depends_on"):
            if key not in value:
                raise ValueError(f"Savings-account-party mapping is missing {key!r}")
        identifiers = list(value["source"].values()) + [
            value["target"]["beneficiary_table"], value["target"]["authorized_person_table"],
            value["target"]["account_map_table"], value["target"]["api_root"],
        ]
        if not all(IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Unsafe SQL or API identifier in savings-account-party mapping")
        if Decimal(value["rules"]["beneficiary_allocations_must_total"]) != Decimal("100.00"):
            raise ValueError("Beneficiary allocation contract must total 100.00")
        return cls(value)

    @property
    def contract_hash(self) -> str:
        return digest(self.raw)

    def account_key(self, company: Any, branch: Any, account: Any) -> str:
        parts = [clean(company), clean(branch), clean(account)]
        if not all(parts) or any("|" in item for item in parts if item):
            raise SavingsAccountPartyDataIssue("missing_or_unsafe_account_identity")
        return f"{ACCOUNT_TABLE}|{'|'.join(parts)}"

    def collection_key(self, company: Any, branch: Any, account: Any) -> str:
        return "AHO_ACCOUNT_PARTIES|" + "|".join(self.account_key(company, branch, account).split("|")[1:])

    def external_id(self, kind: str, row: dict[str, Any]) -> str:
        identifier = clean(row["party_id"])
        if not identifier or ":" in identifier:
            raise SavingsAccountPartyDataIssue(f"missing_or_unsafe_{kind}_identity")
        prefix = self.raw["identity"]["beneficiary_prefix" if kind == "beneficiary" else "authorized_person_prefix"]
        return prefix + ":".join(clean(row[name]) or "" for name in ("company_id", "branch_id", "account_id")) + ":" + identifier


BENEFICIARY_SQL = """
    SELECT RTRIM(ID_EMPRESA) AS company_id,RTRIM(ID_SUCURSAL) AS branch_id,
           RTRIM(ID_CUENTA_AHORRO) AS account_id,RTRIM(ID_BENEFICIARIO) AS party_id,
           NOMBRE_BENEFICIARIO AS given_name,APELLIDO_PROPIETARIO AS surname,PORCENTAJE AS allocation_percentage,
           FECHA_NACIMIENTO AS date_of_birth,EDAD AS source_age,DUI AS dui,PARENTESCO AS relationship,
           DIRECCION AS address,TELEFONO AS phone,COMUNICAR_DESIGNACION AS communicate_designation
    FROM dbo.AHO_BENEFICIARIO
"""

AUTHORIZED_SQL = """
    SELECT RTRIM(ID_EMPRESA) AS company_id,RTRIM(ID_SUCURSAL) AS branch_id,
           RTRIM(ID_CUENTA_AHORRO) AS account_id,RTRIM(ID_AUTORIZADO) AS party_id,
           NOMBRE_AUTORIZADO AS given_name,APELLIDO_AUTORIZADO AS surname,FECHA_NACIMIENTO AS date_of_birth,
           DUI AS dui,PARENTESCO AS relationship,DIRECCION AS address,TELEFONO AS phone,
           IMP_CONTRATO AS print_on_contract,IMP_LIBRETA AS print_on_passbook,FIRMA AS signature_reference
    FROM dbo.AHO_AUTORIZADO
"""


def extract(settings: Settings) -> dict[str, list[dict[str, Any]]]:
    with source_connection(settings.source) as conn:
        return {
            "beneficiaries": select_rows(conn, BENEFICIARY_SQL + " ORDER BY ID_EMPRESA,ID_SUCURSAL,ID_CUENTA_AHORRO,ID_BENEFICIARIO"),
            "authorizedPersons": select_rows(conn, AUTHORIZED_SQL + " ORDER BY ID_EMPRESA,ID_SUCURSAL,ID_CUENTA_AHORRO,ID_AUTORIZADO"),
        }


def beneficiary_payload(contract: SavingsAccountPartyContract, row: dict[str, Any]) -> dict[str, Any]:
    name = clean(row.get("given_name"))
    amount = row.get("allocation_percentage")
    if not name:
        raise SavingsAccountPartyDataIssue("missing_beneficiary_name")
    if amount is None or Decimal(str(amount)) <= 0:
        raise SavingsAccountPartyDataIssue("invalid_beneficiary_allocation")
    payload = {
        "externalId": contract.external_id("beneficiary", row), "givenName": name, "surname": clean(row.get("surname")),
        "allocationPercentage": format(Decimal(str(amount)), ".2f"), "dateOfBirth": iso_date(row.get("date_of_birth")),
        "sourceAge": clean(row.get("source_age")), "dui": clean(row.get("dui")),
        "relationship": clean(row.get("relationship")), "address": clean(row.get("address")),
        "phone": clean(row.get("phone")), "communicateDesignation": truth(row.get("communicate_designation")),
        "linkedClientId": None,
    }
    payload["sourceHash"] = digest(payload)
    return payload


def authorized_payload(contract: SavingsAccountPartyContract, row: dict[str, Any]) -> dict[str, Any]:
    name = clean(row.get("given_name"))
    if not name:
        raise SavingsAccountPartyDataIssue("missing_authorized_person_name")
    payload = {
        "externalId": contract.external_id("authorized_person", row), "givenName": name,
        "surname": clean(row.get("surname")), "dateOfBirth": iso_date(row.get("date_of_birth")),
        "dui": clean(row.get("dui")), "relationship": clean(row.get("relationship")),
        "address": clean(row.get("address")), "phone": clean(row.get("phone")),
        "printOnContract": truth(row.get("print_on_contract")),
        "printOnPassbook": truth(row.get("print_on_passbook")),
        "signatureReference": clean(row.get("signature_reference")), "linkedClientId": None,
    }
    payload["sourceHash"] = digest(payload)
    return payload


def collections(settings: Settings, contract: SavingsAccountPartyContract) -> dict[str, dict[str, Any]]:
    rows = extract(settings)
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"beneficiaries": [], "authorizedPersons": [], "issue": None})
    identities: set[str] = set()
    for kind, values in rows.items():
        for row in values:
            key = contract.collection_key(row["company_id"], row["branch_id"], row["account_id"])
            try:
                payload = beneficiary_payload(contract, row) if kind == "beneficiaries" else authorized_payload(contract, row)
                external_id = payload["externalId"]
                if external_id in identities:
                    raise SavingsAccountPartyDataIssue("duplicate_source_party_identity")
                identities.add(external_id)
                grouped[key][kind].append(payload)
                grouped[key]["accountKey"] = contract.account_key(row["company_id"], row["branch_id"], row["account_id"])
            except SavingsAccountPartyDataIssue as exc:
                grouped[key]["issue"] = str(exc)
    required_total = Decimal(contract.raw["rules"]["beneficiary_allocations_must_total"])
    for value in grouped.values():
        beneficiaries = value["beneficiaries"]
        if beneficiaries and sum((Decimal(item["allocationPercentage"]) for item in beneficiaries), Decimal()) != required_total:
            value["issue"] = "beneficiary_allocations_do_not_total_100"
        value["sourceHash"] = digest({"beneficiaries": beneficiaries, "authorizedPersons": value["authorizedPersons"]})
    return dict(grouped)


def _target_accounts(settings: Settings, account_keys: list[str]) -> dict[str, int]:
    if not settings.target.pg_url:
        raise RuntimeError("Target PostgreSQL URL is required for savings-account-party migration")
    with postgres_connection(settings.target.pg_url) as conn:
        rows = conn.execute(
            "SELECT source_key,savings_account_id FROM credesal_savings_migration_account "
            "WHERE source_system='arissto' AND source_key=ANY(%s) AND migration_status IN ('APPLIED','RECONCILED')",
            (account_keys,),
        ).fetchall()
    return {str(key): int(account_id) for key, account_id in rows}


def inspect_savings_account_parties(settings: Settings, contract: SavingsAccountPartyContract) -> dict[str, Any]:
    blockers: list[Any] = []
    source_schema: dict[str, Any] = {}
    extracted: dict[str, list[dict[str, Any]]] = {}
    try:
        extracted = extract(settings)
        source_schema = {kind: sorted(values[0]) if values else [] for kind, values in extracted.items()}
    except Exception as exc:
        blockers.append({"source_extraction": type(exc).__name__})
    target_schema: dict[str, Any] = {}
    target_counts: dict[str, int] = {}
    permissions: set[str] = set()
    if not settings.target.pg_url:
        blockers.append({"target": "postgres_inspection_required"})
    else:
        with postgres_connection(settings.target.pg_url) as conn:
            target_schema = postgres_schema(conn, list(TARGET_COLUMNS))
            for table, required in TARGET_COLUMNS.items():
                missing = sorted(required - set(target_schema.get(table, {})))
                if missing:
                    blockers.append({"target_table": table, "missing_columns": missing})
                else:
                    target_counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            permissions = {str(row[0]) for row in conn.execute(
                "SELECT DISTINCT p.code FROM m_appuser u JOIN m_appuser_role ur ON ur.appuser_id=u.id "
                "JOIN m_role_permission rp ON rp.role_id=ur.role_id JOIN m_permission p ON p.id=rp.permission_id "
                "WHERE u.username=%s AND p.code IN ('ALL_FUNCTIONS','READ_SAVINGSACCOUNT','UPDATE_SAVINGSACCOUNT')",
                (settings.target.api_user,),
            ).fetchall()}
            required = {"READ_SAVINGSACCOUNT", "UPDATE_SAVINGSACCOUNT"}
            effective = required if "ALL_FUNCTIONS" in permissions else permissions
            if not required <= effective:
                blockers.append({"target_permissions_missing": sorted(required - permissions)})
    source_counts = {kind: len(values) for kind, values in extracted.items()}
    return {
        "block": BLOCK, "ready": not blockers, "target_fingerprint": settings.target.fingerprint,
        "contract_hash": contract.contract_hash, "schema_signature": digest({"source": source_schema, "target": target_schema}),
        "depends_on": contract.raw["depends_on"], "source": {"counts": source_counts},
        "target": {"counts": target_counts, "inherited_savings_permissions": sorted(permissions)}, "blockers": blockers,
    }


def _api_collections(api: FineractApi, api_root: str, account_id: int) -> dict[str, Any]:
    return {
        "beneficiaries": api.request("GET", f"{api_root}/{account_id}/beneficiaries"),
        "authorizedPersons": api.request("GET", f"{api_root}/{account_id}/authorized-persons"),
    }


def build_savings_account_party_plan(settings: Settings, state: State, contract: SavingsAccountPartyContract,
                                     source_keys: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    inspection = inspect_savings_account_parties(settings, contract)
    if not inspection["ready"]:
        raise RuntimeError("Savings-account-party source or destination prerequisites are not ready")
    source = collections(settings, contract)
    wanted = set(source_keys or [])
    if wanted:
        missing = sorted(wanted - set(source))
        if missing:
            raise ValueError(f"Unknown savings-account-party source keys: {missing}")
        source = {key: value for key, value in source.items() if key in wanted}
    accounts = _target_accounts(settings, [value["accountKey"] for value in source.values()])
    api = FineractApi(settings.target)
    api_root = contract.raw["target"]["api_root"]
    actions: list[dict[str, Any]] = []
    counts = Counter()
    for key, value in sorted(source.items()):
        account_id = accounts.get(value["accountKey"])
        issue = value.get("issue") or (None if account_id else "missing_migrated_savings_account")
        if issue:
            action = "quarantine"
        else:
            current = _api_collections(api, api_root, int(account_id))
            desired = {"beneficiaries": value["beneficiaries"], "authorizedPersons": value["authorizedPersons"]}
            action = "unchanged" if digest(current) == digest(desired) else "replace"
        actions.append({
            "source_key": key, "source_hash": value["sourceHash"], "action": action,
            "target_id": str(account_id) if account_id else None, **({"reason": issue} if issue else {}),
        })
        counts[action] += 1
    document = {
        "version": 1, "block": BLOCK, "target_fingerprint": settings.target.fingerprint,
        "source_fingerprint": source_fingerprint(settings.source), "contract_hash": contract.contract_hash,
        "schema_signature": inspection["schema_signature"], "applicable": inspection["ready"],
        "readiness_blocker_count": len(inspection["blockers"]),
        "scope": {"mode": "explicit-source-keys" if source_keys else "full-block", "account_count": len(source)},
        "counts": dict(counts), "actions": actions,
    }
    plan_id = state.save_plan(settings.target.fingerprint, BLOCK, document["source_fingerprint"], contract.contract_hash, document)
    return plan_id, document


def apply_savings_account_party_plan(settings: Settings, state: State, contract: SavingsAccountPartyContract, plan_id: str,
                                     production_confirmation: str | None = None,
                                     only_keys: set[str] | None = None) -> tuple[str, dict[str, int]]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Plan belongs to a different block or target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source) or plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Plan is stale: source or savings-account-party contract changed")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_savings_account_parties(settings, contract)
    if not inspection["ready"] or plan["document"].get("schema_signature") != inspection["schema_signature"]:
        raise RuntimeError("Destination readiness changed; apply refused")
    source = collections(settings, contract)
    api = FineractApi(settings.target)
    api_root = contract.raw["target"]["api_root"]
    counts = Counter()
    run_id = state.start_run(plan)
    for action in plan["document"]["actions"]:
        key = action["source_key"]
        if only_keys is not None and key not in only_keys:
            continue
        if action["action"] == "quarantine":
            state.record_item(run_id, key, "quarantine", action["source_hash"], "quarantined", action.get("target_id"),
                              f"SavingsAccountPartyDataIssue:{action.get('reason', 'unspecified')}")
            counts["quarantined"] += 1
            continue
        if action["action"] == "unchanged":
            state.record_item(run_id, key, "unchanged", action["source_hash"], "unchanged", action.get("target_id"))
            counts["unchanged"] += 1
            continue
        try:
            value = source.get(key)
            if value is None or value["sourceHash"] != action["source_hash"]:
                raise RuntimeError("source_changed_after_plan")
            account_id = int(action["target_id"])
            api.request("PUT", f"{api_root}/{account_id}/beneficiaries", value["beneficiaries"])
            api.request("PUT", f"{api_root}/{account_id}/authorized-persons", value["authorizedPersons"])
            state.save_mapping(settings.target.fingerprint, BLOCK, key, str(account_id), action["source_hash"])
            state.record_item(run_id, key, "replace", action["source_hash"], "succeeded", str(account_id))
            counts["replace"] += 1
        except Exception as exc:
            safe = str(exc).splitlines()[0] if str(exc) == "source_changed_after_plan" else "redacted"
            state.record_item(run_id, key, action["action"], action["source_hash"], "failed", action.get("target_id"),
                              f"{type(exc).__name__}:{safe}"[:240])
            counts["failed"] += 1
    state.finish_run(run_id, "completed_with_errors" if counts["failed"] or counts["quarantined"] else "completed", dict(counts))
    return run_id, dict(counts)


def reconcile_savings_account_parties(settings: Settings, state: State, contract: SavingsAccountPartyContract,
                                      run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Run belongs to a different block or target")
    source = collections(settings, contract)
    api = FineractApi(settings.target)
    api_root = contract.raw["target"]["api_root"]
    counts = Counter()
    for item in state.run_items(run_id):
        if item["status"] in {"failed", "quarantined"}:
            counts[item["status"]] += 1
            continue
        desired = source.get(item["source_key"])
        if not desired or desired["sourceHash"] != item["source_hash"]:
            counts["source_changed"] += 1
            continue
        try:
            current = _api_collections(api, api_root, int(item["target_id"]))
            expected = {"beneficiaries": desired["beneficiaries"], "authorizedPersons": desired["authorizedPersons"]}
            counts["matched" if digest(current) == digest(expected) else "mismatched"] += 1
        except Exception:
            counts["reconcile_error"] += 1
    failed = {"failed", "quarantined", "source_changed", "mismatched", "reconcile_error"}
    return {"run_id": run_id, "status": run["status"], "counts": dict(counts),
            "ok": not any(counts[name] for name in failed)}
