from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from .arissto import IDENTIFIER, select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import FineractApi, postgres_connection, postgres_schema
from .state import State


BLOCK = "native-share-yield"
SOURCE_SYSTEM = "arissto"
REQUIRED_TARGET_SCHEMA = {
    "m_share_product": {"id", "external_id"},
    "m_share_account": {"id", "product_id", "status_enum"},
    "credesal_share_certificate": {"source_key", "share_account_id"},
    "m_share_product_yield_config": {
        "product_id", "enabled", "annual_rate", "accrual_start_date",
        "expense_gl_account_id", "payable_gl_account_id",
    },
    "m_share_account_yield_accrual": {
        "id", "share_account_id", "accrual_date", "entry_type", "base_amount",
        "annual_rate", "day_count_basis", "accrued_amount", "booked_amount",
        "source_reference", "imported",
    },
    "acc_gl_account": {"id", "gl_code", "classification_enum", "disabled"},
}


@dataclass(frozen=True)
class ShareYieldContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "ShareYieldContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("version") != 1:
            raise ValueError("Native share-yield contract version must be 1")
        identifiers = list(value.get("source", {}).values())
        if not identifiers or not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Native share-yield contract contains an unsafe SQL identifier")
        if Decimal(str(value.get("yield", {}).get("annual_rate", "0"))) <= 0:
            raise ValueError("Native share-yield annual rate must be positive")
        return cls(value)

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True).encode()).hexdigest()


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _date(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else value


def _source_key(identifier: Any) -> str:
    return f"FNC_PROVISIONES|{int(identifier)}"


def _certificate_key(row: dict[str, Any]) -> str:
    return "AFI_CERTIFICADO|{}|{}|{}".format(
        int(row["ID_CERTIFICADO"]), int(row["ID_ASOCIADO"]), int(row["ID_TIPO_ACCION"])
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _expected_exact(base: Decimal, rate: Decimal, accrual_date: date) -> Decimal:
    basis = 366 if accrual_date.year % 400 == 0 or (accrual_date.year % 4 == 0 and accrual_date.year % 100 != 0) else 365
    return (base * rate / Decimal(100 * basis)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(records),
        "certificates": len({record["certificate_key"] for record in records}),
        "exact": format(sum((_decimal(record["accrued_amount"]) for record in records), Decimal(0)), ".8f"),
        "booked": format(sum((_decimal(record["booked_amount"]) for record in records), Decimal(0)), ".2f"),
        "min_date": min((record["accrual_date"] for record in records), default=None),
        "max_date": max((record["accrual_date"] for record in records), default=None),
    }


def _target_accrual_matches(existing: dict[str, Any], account_id: int, record: dict[str, Any]) -> bool:
    return (
        existing["account_id"] == account_id
        and existing["date"] == record["accrual_date"]
        and existing["entry_type"] == record["entry_type"]
        and _decimal(existing["base"]) == _decimal(record["base_amount"])
        and _decimal(existing["rate"]) == _decimal(record["annual_rate"])
        and existing["basis"] == record["day_count_basis"]
        and _decimal(existing["exact"]) == _decimal(record["accrued_amount"])
        and _decimal(existing["booked"]) == _decimal(record["booked_amount"])
        and existing["imported"]
    )


def extract_share_yields(settings: Settings, contract: ShareYieldContract,
                         source_keys: list[str] | set[str] | None = None) -> list[dict[str, Any]]:
    source = contract.raw["source"]
    wanted = set(source_keys or [])
    with source_connection(settings.source) as conn:
        rows = select_rows(conn, f"""
            SELECT p.ID_FNC_PROVISION,p.FECHA_PROVISION,p.SALDO_CUENTA,p.TASA_INTERES,
                   p.INT_PROV,p.INT_PROV_CNT,p.SALDO_INT_PROV,p.SALDO_INT_PROV_CNT,
                   c.ID_CERTIFICADO,c.ID_ASOCIADO,c.ID_TIPO_ACCION
            FROM dbo.{source['accrual_table']} p
            JOIN dbo.{source['certificate_table']} c ON c.ID_CERTIFICADO=p.REF_ID
            WHERE p.ID_TIPO_PRODUCTO=? AND c.ID_TIPO_ACCION=?
            ORDER BY p.FECHA_PROVISION,p.ID_FNC_PROVISION
        """, (contract.raw["yield"]["source_product_type"], contract.raw["yield"]["source_share_type"]))
    records: list[dict[str, Any]] = []
    for row in rows:
        key = _source_key(row["ID_FNC_PROVISION"])
        if wanted and key not in wanted:
            continue
        accrual_date = _date(row["FECHA_PROVISION"])
        basis = 366 if accrual_date.year % 400 == 0 or (accrual_date.year % 4 == 0 and accrual_date.year % 100 != 0) else 365
        record = {
            "source_key": key,
            "certificate_key": _certificate_key(row),
            "accrual_date": accrual_date.isoformat(),
            "entry_type": "ACCRUAL",
            "base_amount": format(_decimal(row["SALDO_CUENTA"]), "f"),
            "annual_rate": format(_decimal(row["TASA_INTERES"]), "f"),
            "day_count_basis": basis,
            "accrued_amount": format(_decimal(row["INT_PROV"]), ".8f"),
            "booked_amount": format(_decimal(row["INT_PROV_CNT"]), ".2f"),
            "accumulated_exact": format(_decimal(row["SALDO_INT_PROV"]), ".8f"),
            "accumulated_booked": format(_decimal(row["SALDO_INT_PROV_CNT"]), ".2f"),
        }
        issues: list[str] = []
        if _decimal(record["annual_rate"]) != Decimal(str(contract.raw["yield"]["annual_rate"])):
            issues.append("unexpected_annual_rate")
        if _expected_exact(_decimal(record["base_amount"]), _decimal(record["annual_rate"]), accrual_date) != _decimal(
                record["accrued_amount"]):
            issues.append("daily_formula_mismatch")
        if _decimal(record["booked_amount"]) != _decimal(record["accrued_amount"]).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP):
            issues.append("booked_rounding_mismatch")
        record["issues"] = issues
        record["source_hash"] = _stable_hash({key: value for key, value in record.items() if key not in {"issues", "source_hash"}})
        records.append(record)
    return records


def _target_context_unchecked(settings: Settings, contract: ShareYieldContract) -> dict[str, Any]:
    target: dict[str, Any] = {"schema": {}, "accounts": {}, "existing": {}, "product": None, "gl": {}, "permissions": set()}
    if not settings.target.pg_url:
        return target
    with postgres_connection(settings.target.pg_url) as conn:
        target["schema"] = postgres_schema(conn, list(REQUIRED_TARGET_SCHEMA))
        if any(required - set(target["schema"].get(table, {})) for table, required in REQUIRED_TARGET_SCHEMA.items()):
            return target
        external_id = contract.raw["target"]["product_external_id"]
        products = conn.execute("SELECT id FROM m_share_product WHERE external_id=%s", (external_id,)).fetchall()
        if len(products) == 1:
            target["product"] = int(products[0][0])
        target["accounts"] = {str(row[0]): int(row[1]) for row in conn.execute(
            "SELECT source_key,share_account_id FROM credesal_share_certificate"
        ).fetchall()}
        target["existing"] = {str(row[0]): {
            "id": int(row[1]), "account_id": int(row[2]), "date": row[3].isoformat(),
            "entry_type": str(row[4]), "base": format(_decimal(row[5]), "f"),
            "rate": format(_decimal(row[6]), "f"), "basis": int(row[7]),
            "exact": format(_decimal(row[8]), ".8f"), "booked": format(_decimal(row[9]), ".2f"),
            "imported": bool(row[10]),
        } for row in conn.execute(
            "SELECT source_reference,id,share_account_id,accrual_date,entry_type,base_amount,annual_rate,"
            "day_count_basis,accrued_amount,booked_amount,imported "
            "FROM m_share_account_yield_accrual WHERE source_reference LIKE 'FNC_PROVISIONES|%'"
        ).fetchall()}
        gl_codes = [contract.raw["target"]["expense_gl_code"], contract.raw["target"]["payable_gl_code"]]
        target["gl"] = {str(row[1]): {"id": int(row[0]), "type": int(row[2]), "disabled": bool(row[3])}
                        for row in conn.execute(
                            "SELECT id,gl_code,classification_enum,disabled FROM acc_gl_account WHERE gl_code=ANY(%s)",
                            (gl_codes,),
                        ).fetchall()}
        target["permissions"] = {str(row[0]) for row in conn.execute(
            "SELECT code FROM m_permission WHERE code=ANY(%s)", (contract.raw["required_permissions"],)
        ).fetchall()}
        if target["product"] is not None:
            config = conn.execute(
                "SELECT enabled,annual_rate,accrual_start_date,expense_gl_account_id,payable_gl_account_id "
                "FROM m_share_product_yield_config WHERE product_id=%s", (target["product"],)
            ).fetchone()
            target["configuration"] = None if config is None else {
                "enabled": bool(config[0]), "rate": format(_decimal(config[1]), "f"),
                "start_date": config[2].isoformat(), "expense": int(config[3]), "payable": int(config[4]),
            }
    return target


def _target_context(settings: Settings, contract: ShareYieldContract) -> dict[str, Any]:
    try:
        return _target_context_unchecked(settings, contract)
    except Exception as exc:
        return {"schema": {}, "accounts": {}, "existing": {}, "product": None, "gl": {}, "permissions": set(),
                "error": type(exc).__name__}


def inspect_share_yields(settings: Settings, contract: ShareYieldContract) -> dict[str, Any]:
    records = extract_share_yields(settings, contract)
    target = _target_context(settings, contract)
    blockers = sorted({issue for record in records for issue in record["issues"]})
    if len(records) < int(contract.raw["expected"]["minimum_accrual_rows"]):
        blockers.append("source_accrual_population_below_reviewed_floor")
    if len({record["certificate_key"] for record in records}) < int(contract.raw["expected"]["minimum_certificates"]):
        blockers.append("source_certificate_population_below_reviewed_floor")
    if not settings.target.pg_url:
        blockers.append("postgres_inspection_required")
    elif target.get("error"):
        blockers.append(f"target_inspection_failed:{target['error']}")
    for table, required in REQUIRED_TARGET_SCHEMA.items():
        for column in sorted(required - set(target["schema"].get(table, {}))):
            blockers.append(f"missing_target_column:{table}:{column}")
    if target["product"] is None:
        blockers.append("preferred_share_product_missing")
    for code, expected_type in ((contract.raw["target"]["expense_gl_code"], 5),
                                (contract.raw["target"]["payable_gl_code"], 2)):
        account = target["gl"].get(code)
        if not account or account["type"] != expected_type or account["disabled"]:
            blockers.append(f"yield_gl_account_invalid:{code}")
    missing_permissions = sorted(set(contract.raw["required_permissions"]) - target["permissions"])
    blockers.extend(f"missing_permission:{value}" for value in missing_permissions)
    mapped = sum(1 for record in records if record["certificate_key"] in target["accounts"])
    if mapped != len(records):
        blockers.append("native_share_certificate_mapping_incomplete")
    configuration = target.get("configuration")
    expense = target["gl"].get(contract.raw["target"]["expense_gl_code"])
    payable = target["gl"].get(contract.raw["target"]["payable_gl_code"])
    if not configuration or not configuration["enabled"] \
            or _decimal(configuration["rate"]) != _decimal(contract.raw["yield"]["annual_rate"]) \
            or configuration["start_date"] != contract.raw["yield"]["accrual_start_date"] \
            or not expense or configuration["expense"] != expense["id"] \
            or not payable or configuration["payable"] != payable["id"]:
        blockers.append("preferred_share_yield_configuration_missing_or_drifted")
    totals = _summarize(records)
    certificate_keys = sorted({record["certificate_key"] for record in records})
    source_keys = sorted(record["source_key"] for record in records)
    signature = _stable_hash({
        "schema": target["schema"],
        "product": target["product"],
        "gl": target["gl"],
        "permissions": sorted(target["permissions"]),
        "configuration": target.get("configuration"),
        "accounts": {key: target["accounts"].get(key) for key in certificate_keys},
        "existing": {key: target["existing"].get(key) for key in source_keys},
    })
    return {"block": BLOCK, "ready": not blockers, "contract_hash": contract.contract_hash,
            "schema_signature": signature, "source": totals,
            "target": {"mapped_rows": mapped, "existing_rows": len(target["existing"])}, "blockers": blockers}


def prepare_share_yield_target(settings: Settings, contract: ShareYieldContract) -> dict[str, Any]:
    target = _target_context_unchecked(settings, contract)
    if target["product"] is None:
        raise RuntimeError("Preferred native share product must exist before share-yield configuration")
    expense = target["gl"].get(contract.raw["target"]["expense_gl_code"])
    payable = target["gl"].get(contract.raw["target"]["payable_gl_code"])
    if not expense or not payable:
        raise RuntimeError("Reviewed share-yield GL accounts must exist before configuration")
    payload = {
        "enabled": True, "annualRate": contract.raw["yield"]["annual_rate"],
        "accrualStartDate": contract.raw["yield"]["accrual_start_date"],
        "expenseAccountId": expense["id"], "payableAccountId": payable["id"],
        "dateFormat": "yyyy-MM-dd", "locale": "en",
    }
    FineractApi(settings.target).request("POST", f"shareyield/products/{target['product']}", payload,
                                         idempotency_key="share-yield-config-v1")
    return {"performed": True, "product_id": target["product"]}


def build_share_yield_plan(settings: Settings, state: State, contract: ShareYieldContract,
                           source_keys: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    inspection = inspect_share_yields(settings, contract)
    records = extract_share_yields(settings, contract, source_keys)
    target = _target_context(settings, contract)
    actions: list[dict[str, Any]] = []
    for record in records:
        account_id = target["accounts"].get(record["certificate_key"])
        existing = target["existing"].get(record["source_key"])
        reason = record["issues"][0] if record["issues"] else None
        if reason:
            action = "quarantine"
        elif account_id is None:
            action, reason = "quarantine", "native_share_account_missing"
        elif existing and not _target_accrual_matches(existing, account_id, record):
            action, reason = "quarantine", "target_source_reference_drift"
        elif existing:
            action = "unchanged"
        else:
            action = "create"
        actions.append({"source_key": record["source_key"], "source_hash": record["source_hash"], "action": action,
                        "reason": reason, "share_account_id": account_id,
                        "target_id": existing["id"] if existing else None})
    counts = Counter(item["action"] for item in actions)
    document = {"applicable": inspection["ready"], "scope": {"mode": "explicit-source-keys" if source_keys else "full-block",
                "accrual_count": len(records)}, "source": _summarize(records), "counts": dict(counts),
                "readiness_blocker_count": len(inspection["blockers"]), "readiness_blockers": inspection["blockers"],
                "schema_signature": inspection["schema_signature"], "actions": actions}
    plan_id = state.save_plan(settings.target.fingerprint, BLOCK, source_fingerprint(settings.source),
                              contract.contract_hash, document)
    return plan_id, document


def _guard(settings: Settings, state: State, contract: ShareYieldContract, plan_id: str,
           production_confirmation: str | None) -> dict[str, Any]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK or plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Share-yield plan does not belong to the selected target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source) or plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Share-yield source or contract changed after planning")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_share_yields(settings, contract)
    if not inspection["ready"] or inspection["schema_signature"] != plan["document"]["schema_signature"]:
        raise RuntimeError("Share-yield readiness/schema changed after planning")
    return plan


def apply_share_yield_plan(settings: Settings, state: State, contract: ShareYieldContract, plan_id: str,
                           production_confirmation: str | None = None,
                           source_keys: set[str] | None = None) -> tuple[str, dict[str, int]]:
    plan = _guard(settings, state, contract, plan_id, production_confirmation)
    actions = [item for item in plan["document"]["actions"] if source_keys is None or item["source_key"] in source_keys]
    records = {item["source_key"]: item for item in extract_share_yields(
        settings, contract, [item["source_key"] for item in actions]
    )}
    run_id = state.start_run(plan)
    counts = Counter()
    api = FineractApi(settings.target)
    for action in actions:
        if action["action"] in {"unchanged", "quarantine"}:
            status = "unchanged" if action["action"] == "unchanged" else "quarantined"
            state.record_item(run_id, action["source_key"], action["action"], action["source_hash"], status,
                              str(action["target_id"]) if action.get("target_id") else None, action.get("reason"))
            counts[status] += 1
            continue
        record = records.get(action["source_key"])
        if not record or record["source_hash"] != action["source_hash"]:
            state.record_item(run_id, action["source_key"], action["action"], action["source_hash"], "failed",
                              error_code="source_changed_after_plan")
            counts["failed"] += 1
            continue
        payload = {key: record[key] for key in ("accrual_date", "entry_type", "base_amount", "annual_rate",
                                                  "day_count_basis", "accrued_amount", "booked_amount")}
        payload = {
            "accrualDate": payload.pop("accrual_date"), "entryType": payload.pop("entry_type"),
            "baseAmount": payload.pop("base_amount"), "annualRate": payload.pop("annual_rate"),
            "dayCountBasis": payload.pop("day_count_basis"), "accruedAmount": payload.pop("accrued_amount"),
            "bookedAmount": payload.pop("booked_amount"), "sourceReference": record["source_key"],
            "dateFormat": "yyyy-MM-dd", "locale": "en",
        }
        try:
            response = api.request("POST", f"accounts/share/{action['share_account_id']}", payload,
                                   query={"command": "sourceExactYieldAccrual"},
                                   idempotency_key=f"shy:{record['source_key'].split('|')[1]}")
            target_id = response.get("subEntityId") or response.get("resourceId")
            state.record_item(run_id, action["source_key"], action["action"], action["source_hash"], "succeeded",
                              str(target_id) if target_id else None)
            counts["succeeded"] += 1
        except Exception as exc:
            state.record_item(run_id, action["source_key"], action["action"], action["source_hash"], "failed",
                              error_code=type(exc).__name__)
            counts["failed"] += 1
    status = "completed" if counts["failed"] == 0 and counts["quarantined"] == 0 else "completed-with-errors"
    state.finish_run(run_id, status, dict(counts))
    return run_id, dict(counts)


def reconcile_share_yields(settings: Settings, state: State, contract: ShareYieldContract, run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Share-yield run does not belong to the selected target")
    keys = {item["source_key"] for item in state.run_items(run_id) if item["status"] in {"succeeded", "unchanged"}}
    records = {item["source_key"]: item for item in extract_share_yields(settings, contract, keys)}
    target = _target_context(settings, contract)
    mismatches: list[dict[str, str]] = []
    for key in sorted(keys):
        record, actual = records.get(key), target["existing"].get(key)
        account_id = target["accounts"].get(record["certificate_key"]) if record else None
        if record is None:
            reason = "source_missing"
        elif actual is None:
            reason = "target_missing"
        elif not _target_accrual_matches(actual, account_id, record):
            reason = "financial_values_mismatch"
        else:
            reason = None
        if reason:
            mismatches.append({"source_key": key, "reason": reason})
    result = {"run_id": run_id, "ok": not mismatches, "checked": len(keys),
              "mismatch_count": len(mismatches), "mismatches": mismatches[:100]}
    state.record_reconciliation(run_id, result)
    return result
