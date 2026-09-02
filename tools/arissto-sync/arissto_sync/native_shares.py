from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .arissto import IDENTIFIER, select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import postgres_connection, postgres_schema


BLOCK = "native-share-capital"
REQUIRED_TARGET_SCHEMA = {
    "acc_gl_account": {"id", "gl_code", "name", "classification_enum", "disabled"},
    "m_payment_type": {"id", "value", "code_name", "is_cash_payment"},
    "m_share_product": {"id", "external_id", "currency_code", "total_shares", "unit_price",
                        "minimum_client_shares", "nominal_client_shares", "maximum_client_shares", "accounting_type",
                        "numbering_code"},
    "m_share_product_market_price": {"product_id", "from_date", "share_value"},
    "m_share_account": {"id", "product_id", "client_id", "external_id", "status_enum", "total_approved_shares",
                        "savings_account_id", "currency_code"},
    "m_share_account_transactions": {"id", "account_id", "transaction_date", "total_shares", "unit_price", "amount",
                                     "status_enum", "type_enum", "payment_type_id"},
    "credesal_share_native_event_map": {"source_table", "source_key", "source_hash", "client_id", "share_product_id",
                                        "share_account_id", "share_transaction_id", "event_kind", "event_date", "total_shares",
                                        "unit_price", "amount", "event_status"},
    "credesal_share_certificate": {"source_key", "client_id", "share_account_id", "paid_shares", "subscribed_shares",
                                   "source_hash"},
    "credesal_savings_migration_account": {"id", "client_id", "savings_account_id", "deposit_type", "migration_status"},
    "credesal_savings_migration_owner": {"migration_account_id", "client_id", "is_native_owner"},
}


@dataclass(frozen=True)
class NativeShareContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "NativeShareContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("version") != 1:
            raise ValueError("Native share contract version must be 1")
        identifiers = list(value.get("source", {}).values()) + [
            item for key, item in value.get("target", {}).items() if key.endswith("_table")
        ]
        if not identifiers or not all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in identifiers):
            raise ValueError("Native share contract contains an unsafe SQL identifier")
        classes = value.get("share_classes", {})
        if set(classes) != {"1", "2"}:
            raise ValueError("Native share contract requires common and preferred classes")
        external_ids = [item.get("product_external_id") for item in classes.values()]
        if len(set(external_ids)) != 2 or not all(external_ids):
            raise ValueError("Native share product external IDs must be unique")
        if {key: item.get("numbering_code") for key, item in classes.items()} != {"1": "1AC", "2": "1AP"}:
            raise ValueError("Native share numbering codes must preserve common 1AC and preferred 1AP")
        expected = value.get("expected", {})
        if any(int(expected.get(key, 0)) <= 0 for key in ("accounts", "purchase_events", "paid_shares", "certificates")):
            raise ValueError("Native share expected counts must be positive")
        if Decimal(str(expected.get("unit_price", "0"))) <= 0:
            raise ValueError("Native share unit price must be positive")
        return cls(value)

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True).encode()).hexdigest()


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def project_source(position_rows: list[dict[str, Any]], certificate_rows: list[dict[str, Any]],
                   movement_rows: list[dict[str, Any]], unit_price: Decimal) -> dict[str, Any]:
    certificates: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    movements: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in certificate_rows:
        certificates[(int(row["ID_ASOCIADO"]), int(row["ID_TIPO_ACCION"]))].append(row)
    for row in movement_rows:
        movements[(int(row["ID_ASOCIADO"]), int(row["ID_TIPO_ACCION"]))].append(row)

    issues: list[str] = []
    accounts: list[dict[str, Any]] = []
    class_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"accounts": 0, "certificates": 0, "purchase_events": 0,
                 "paid_shares": 0, "subscribed_shares": 0, "paid_capital": Decimal("0"),
                 "largest_client_paid_shares": 0, "largest_client_subscribed_shares": 0}
    )
    for position in position_rows:
        associate = int(position["ID_ASOCIADO"])
        share_type = int(position["ID_TIPO_ACCION"])
        key = (associate, share_type)
        certs = certificates.get(key, [])
        events = sorted(movements.get(key, []), key=lambda row: (
            str(row.get("FECHA") or ""), str(row.get("ID_EMPRESA") or ""),
            str(row.get("ID_SUCURSAL") or ""), str(row.get("ID_MOV_APORTACION") or ""),
        ))
        paid = sum(int(_decimal(row.get("ACCIONES_PAGADAS"))) for row in certs)
        subscribed = sum(int(_decimal(row.get("ACCIONES_SUSCRITAS"))) for row in certs)
        amount = sum((_decimal(row.get("MONTO")) for row in events), Decimal("0"))
        event_shares = amount / unit_price if unit_price else Decimal("0")
        prefix = f"AFI_ACCION|{position['ID_ACCION']}"
        if not certs:
            issues.append(f"missing_certificate:{prefix}")
        if not events:
            issues.append(f"missing_purchase_event:{prefix}")
        if event_shares != event_shares.to_integral_value():
            issues.append(f"non_integral_purchase_shares:{prefix}")
        if int(event_shares) != paid:
            issues.append(f"movement_paid_share_mismatch:{prefix}")
        if _decimal(position.get("SALDO_ACCIONES")) != amount:
            issues.append(f"position_balance_mismatch:{prefix}")
        for event in events:
            event_amount = _decimal(event.get("MONTO"))
            if event_amount <= 0 or event_amount / unit_price != (event_amount / unit_price).to_integral_value():
                issues.append(f"invalid_purchase_amount:MOV_APORTACIONES|{event.get('ID_EMPRESA')}|"
                              f"{event.get('ID_SUCURSAL')}|{event.get('ID_MOV_APORTACION')}")
            if str(event.get("REVERSION") or "").strip() == "1":
                issues.append(f"reversed_purchase_event:{prefix}")
        totals = class_totals[str(share_type)]
        totals["accounts"] += 1
        totals["certificates"] += len(certs)
        totals["purchase_events"] += len(events)
        totals["paid_shares"] += paid
        totals["subscribed_shares"] += subscribed
        totals["paid_capital"] += amount
        totals["largest_client_paid_shares"] = max(totals["largest_client_paid_shares"], paid)
        totals["largest_client_subscribed_shares"] = max(totals["largest_client_subscribed_shares"], subscribed)
        accounts.append({
            "source_key": prefix,
            "share_type": share_type,
            "client_external_id": str(position.get("NUMERO_AFILIACION") or "").strip() or None,
            "certificate_count": len(certs),
            "purchase_event_count": len(events),
            "paid_shares": paid,
            "subscribed_shares": subscribed,
            "paid_capital": str(amount),
        })
    return {"accounts": accounts, "class_totals": dict(class_totals), "issues": sorted(set(issues))}


def validate_approved_limits(share_classes: dict[str, dict[str, Any]],
                             class_totals: dict[str, dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for share_type, item in share_classes.items():
        values = tuple(item.get(field) for field in (
            "approved_total_shares", "approved_minimum_client_shares",
            "approved_nominal_client_shares", "approved_maximum_client_shares",
        ))
        if any(value is None for value in values):
            issues.append(f"missing:{share_type}")
            continue
        total, minimum, nominal, maximum = (int(value) for value in values)
        class_total = class_totals[share_type]
        capacity_basis = item.get("capacity_basis", "paid")
        required_total = (class_total["subscribed_shares"] if capacity_basis == "subscribed"
                          else class_total["paid_shares"])
        required_client = (class_total["largest_client_subscribed_shares"] if capacity_basis == "subscribed"
                           else class_total["largest_client_paid_shares"])
        if total < required_total:
            issues.append(f"total_below_{capacity_basis}:{share_type}")
        if not (0 < minimum <= nominal <= maximum <= total):
            issues.append(f"invalid_order:{share_type}")
        if maximum < required_client:
            issues.append(f"maximum_below_{capacity_basis}:{share_type}")
    return issues


def accounting_configuration_approved(accounting_candidates: dict[str, dict[str, dict[str, Any]]],
                                       candidate_resolution: dict[tuple[str, str], bool],
                                       payment_resolution: dict[int, bool]) -> bool:
    """Return true only when every reviewed accounting role and payment channel resolves."""
    candidates = [
        (scope, role, definition)
        for scope, mappings in accounting_candidates.items()
        for role, definition in mappings.items()
    ]
    return bool(candidates and payment_resolution) and all(
        definition.get("approval_status") == "approved" and candidate_resolution.get((scope, role), False)
        for scope, role, definition in candidates
    ) and all(payment_resolution.values())


def inspect_native_shares(settings: Settings, contract: NativeShareContract, source_key: str | None = None) -> dict[str, Any]:
    source = contract.raw["source"]
    expected = contract.raw["expected"]
    required_source = {
        source["position_table"]: {"ID_ACCION", "ID_ASOCIADO", "ID_TIPO_ACCION", "SALDO_ACCIONES"},
        source["certificate_table"]: {"ID_CERTIFICADO", "ID_ASOCIADO", "ID_TIPO_ACCION", "ACCIONES_PAGADAS",
                                      "ACCIONES_SUSCRITAS", "SALDO_PAGADO", "VALOR_ACCION"},
        source["movement_table"]: {"ID_EMPRESA", "ID_SUCURSAL", "ID_MOV_APORTACION", "ID_ASOCIADO", "ID_TIPO_ACCION",
                                   "ID_CERTIFICADO", "FECHA", "MONTO", "SALDO_ANTERIOR", "SALDO_FINAL", "REVERSION"},
        source["party_table"]: {"ID_ASOCIADO", "NUMERO_AFILIACION"},
        source["type_table"]: {"ID_TIPO_ACCION", "TIPO_ACCION", "CODIGO", "ID_CUENTA"},
        source["emission_table"]: {"ID_TIPO_ACCION", "NUMERO_ACCIONES", "VALOR_ACCION", "FECHA_EMISION"},
    }
    blockers: list[str] = []
    source_schema: list[dict[str, Any]] = []
    with source_connection(settings.source) as conn:
        for table, required in required_source.items():
            columns = select_rows(conn, "SELECT COLUMN_NAME AS column_name FROM INFORMATION_SCHEMA.COLUMNS "
                                  "WHERE TABLE_SCHEMA=? AND TABLE_NAME=?", ("dbo", table))
            available = {str(row["column_name"]) for row in columns}
            missing = sorted(required - available)
            source_schema.append({"table": table, "column_count": len(columns), "missing_required_columns": missing})
            blockers.extend(f"missing_source_column:{table}:{column}" for column in missing)
            if not columns:
                blockers.append(f"missing_source_table:{table}")
        position_rows = select_rows(conn, f"SELECT a.*,s.NUMERO_AFILIACION FROM dbo.{source['position_table']} a "
                                    f"JOIN dbo.{source['party_table']} s ON s.ID_ASOCIADO=a.ID_ASOCIADO")
        certificate_rows = select_rows(conn, f"SELECT * FROM dbo.{source['certificate_table']}")
        movement_rows = select_rows(conn, f"SELECT * FROM dbo.{source['movement_table']}")
        emission_rows = select_rows(conn, f"SELECT * FROM dbo.{source['emission_table']}")
        if source_key:
            position_rows = [row for row in position_rows if f"AFI_ACCION|{row['ID_ACCION']}" == source_key]
            allowed = {(int(row["ID_ASOCIADO"]), int(row["ID_TIPO_ACCION"])) for row in position_rows}
            certificate_rows = [row for row in certificate_rows
                                if (int(row["ID_ASOCIADO"]), int(row["ID_TIPO_ACCION"])) in allowed]
            movement_rows = [row for row in movement_rows
                             if (int(row["ID_ASOCIADO"]), int(row["ID_TIPO_ACCION"])) in allowed]

    projection = project_source(position_rows, certificate_rows, movement_rows, Decimal(expected["unit_price"]))
    blockers.extend(projection["issues"])
    totals = {
        "accounts": len(projection["accounts"]),
        "purchase_events": sum(item["purchase_event_count"] for item in projection["accounts"]),
        "paid_shares": sum(item["paid_shares"] for item in projection["accounts"]),
        "paid_capital": str(sum((_decimal(item["paid_capital"]) for item in projection["accounts"]), Decimal("0"))),
        "certificates": sum(item["certificate_count"] for item in projection["accounts"]),
    }
    if not source_key:
        for field in ("accounts", "purchase_events", "paid_shares", "certificates"):
            if totals[field] != int(expected[field]):
                blockers.append(f"source_baseline_mismatch:{field}")
        if _decimal(totals["paid_capital"]) != _decimal(expected["paid_capital"]):
            blockers.append("source_baseline_mismatch:paid_capital")

    target_schema: dict[str, dict[str, str]] = {}
    target_report: dict[str, Any] = {"postgres_inspection": "not_configured"}
    gl_mapping_ready = False
    lifecycle_proof_ready = False
    if settings.target.pg_url:
        with postgres_connection(settings.target.pg_url) as conn:
            target_schema = postgres_schema(conn, list(REQUIRED_TARGET_SCHEMA))
            for table, required in REQUIRED_TARGET_SCHEMA.items():
                if not target_schema.get(table):
                    blockers.append(f"missing_target_table:{table}")
                blockers.extend(f"missing_target_column:{table}:{column}"
                                for column in sorted(required - set(target_schema.get(table, {}))))
            external_ids = [item["product_external_id"] for item in contract.raw["share_classes"].values()]
            products = conn.execute(
                "SELECT id,external_id,currency_code,total_shares,unit_price,minimum_client_shares,"
                "nominal_client_shares,maximum_client_shares,accounting_type FROM m_share_product "
                "WHERE external_id=ANY(%s) ORDER BY external_id", (external_ids,),
            ).fetchall()
            savings = conn.execute(
                "SELECT COUNT(DISTINCT sma.client_id),COUNT(DISTINCT sma.savings_account_id) "
                "FROM credesal_savings_migration_account sma JOIN m_savings_account sa ON sa.id=sma.savings_account_id "
                "WHERE sma.deposit_type='VISTA' AND sma.migration_status='RECONCILED' "
                "AND sa.deposit_type_enum=100 AND sa.status_enum=300",
            ).fetchone()
            permissions = conn.execute("SELECT code FROM m_permission WHERE code=ANY(%s)",
                                       (contract.raw["required_permissions"],)).fetchall()
            configured_candidates = [
                (scope, role, definition)
                for scope, mappings in contract.raw.get("accounting_candidates", {}).items()
                for role, definition in mappings.items()
            ]
            candidate_codes = sorted({item[2]["gl_code"] for item in configured_candidates})
            candidate_rows = conn.execute(
                "SELECT id,gl_code,name,classification_enum,disabled FROM acc_gl_account WHERE gl_code=ANY(%s)",
                (candidate_codes,),
            ).fetchall()
            candidate_by_code = {str(row[1]): row for row in candidate_rows}
            candidate_report = []
            candidate_resolution: dict[tuple[str, str], bool] = {}
            for scope, role, definition in configured_candidates:
                row = candidate_by_code.get(definition["gl_code"])
                resolved = bool(row and not row[4] and int(row[3]) == int(definition["classification_enum"]))
                candidate_resolution[(scope, role)] = resolved
                candidate_report.append({
                    "scope": scope, "role": role, "gl_code": definition["gl_code"],
                    "expected_classification_enum": definition["classification_enum"],
                    "evidence": definition.get("evidence"),
                    "source_configuration_supported": bool(definition.get("source_configuration_supported")),
                    "source_purchase_journal_supported": bool(definition.get("source_purchase_journal_supported")),
                    "approval_status": definition.get("approval_status", "unapproved"),
                    "resolved": resolved,
                })
                if not resolved:
                    blockers.append(f"share_gl_candidate_unresolved:{scope}:{role}")
            payment_mappings = contract.raw.get("accounting_strategy", {}).get("payment_channel_mappings", [])
            payment_codes = sorted({item["target_payment_type_code"] for item in payment_mappings
                                    if item.get("target_payment_type_code")})
            payment_values = sorted({item["target_payment_type_value"] for item in payment_mappings})
            payment_rows = conn.execute(
                "SELECT id,value,code_name,is_cash_payment FROM m_payment_type "
                "WHERE code_name=ANY(%s) OR value=ANY(%s) ORDER BY id",
                (payment_codes, payment_values),
            ).fetchall()
            payment_gl_codes = sorted({item["gl_code"] for item in payment_mappings})
            payment_gl_rows = conn.execute(
                "SELECT id,gl_code,name,classification_enum,disabled FROM acc_gl_account WHERE gl_code=ANY(%s)",
                (payment_gl_codes,),
            ).fetchall()
            payment_gl_by_code = {str(row[1]): row for row in payment_gl_rows}
            payment_report = []
            payment_resolution: dict[int, bool] = {}
            for mapping in payment_mappings:
                expected_code = mapping.get("target_payment_type_code")
                matches = [row for row in payment_rows if (
                    (expected_code and str(row[2] or "") == expected_code)
                    or (not expected_code and str(row[1]) == mapping["target_payment_type_value"])
                )]
                gl_row = payment_gl_by_code.get(mapping["gl_code"])
                resolved = len(matches) == 1 and bool(
                    gl_row and not gl_row[4] and int(gl_row[3]) == 1
                )
                source_payment_type_id = int(mapping["source_payment_type_id"])
                payment_resolution[source_payment_type_id] = resolved
                payment_report.append({
                    **mapping,
                    "target_payment_type_id": matches[0][0] if len(matches) == 1 else None,
                    "resolved": resolved,
                })
                if not resolved:
                    blockers.append(f"share_payment_channel_unresolved:{source_payment_type_id}")
            gl_mapping_ready = accounting_configuration_approved(
                contract.raw.get("accounting_candidates", {}), candidate_resolution, payment_resolution,
            )
            counts = conn.execute(
                "SELECT (SELECT COUNT(*) FROM m_share_account),"
                "(SELECT COUNT(*) FROM m_share_account_transactions),"
                "(SELECT COUNT(*) FROM credesal_share_native_event_map),"
                "(SELECT COUNT(*) FROM credesal_share_certificate)",
            ).fetchone()
            proof_rows = conn.execute(
                "SELECT sp.external_id,COUNT(DISTINCT em.share_account_id) "
                "FROM credesal_share_native_event_map em "
                "JOIN m_share_product sp ON sp.id=em.share_product_id "
                "WHERE em.event_status='RECONCILED' AND sp.external_id=ANY(%s) "
                "GROUP BY sp.external_id",
                (external_ids,),
            ).fetchall()
            proof_accounts = {str(row[0]): int(row[1]) for row in proof_rows}
            lifecycle_proof_ready = all(proof_accounts.get(external_id, 0) > 0 for external_id in external_ids)
            target_report = {
                "postgres_inspection": "ok",
                "products": [dict(zip(("id", "external_id", "currency_code", "total_shares", "unit_price",
                                       "minimum_client_shares", "nominal_client_shares", "maximum_client_shares",
                                       "accounting_type"), row)) for row in products],
                "eligible_reconciled_vista_clients": int(savings[0]),
                "eligible_reconciled_vista_accounts": int(savings[1]),
                "permission_count": len(permissions),
                "required_permission_count": len(contract.raw["required_permissions"]),
                "accounting_candidates": candidate_report,
                "payment_channel_mappings": payment_report,
                "approved_gl_mapping_ready": gl_mapping_ready,
                "controlled_lifecycle_proof_ready": lifecycle_proof_ready,
                "controlled_lifecycle_proof_accounts": proof_accounts,
                "counts": {"share_accounts": counts[0], "share_transactions": counts[1],
                           "native_event_maps": counts[2], "projected_certificates": counts[3]},
            }
            if len(products) != 2:
                blockers.append("native_share_products_not_provisioned")
            if int(savings[0]) < 34:
                blockers.append("reconciled_native_savings_prerequisite")
            if len(permissions) != len(contract.raw["required_permissions"]):
                blockers.append("native_share_permissions_missing")

    for gate in contract.raw["release_gates"]:
        if gate == "approved_share_product_limits":
            limit_issues = validate_approved_limits(contract.raw["share_classes"], projection["class_totals"])
            if limit_issues:
                blockers.append(gate)
                blockers.extend(f"share_product_limit:{issue}" for issue in limit_issues)
        elif gate == "approved_share_product_gl_mappings":
            if not gl_mapping_ready:
                blockers.append(gate)
        elif gate == "reconciled_native_savings_prerequisite":
            if int(target_report.get("eligible_reconciled_vista_clients", 0)) < 34:
                blockers.append(gate)
        elif gate == "controlled_native_share_lifecycle_proof":
            if not lifecycle_proof_ready:
                blockers.append(gate)
        else:
            blockers.append(gate)
    blockers = sorted(set(blockers))
    signature = hashlib.sha256(json.dumps({"source": source_schema, "target": target_schema},
                                          sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "block": BLOCK,
        "contract_hash": contract.contract_hash,
        "schema_signature": signature,
        "source_fingerprint": source_fingerprint(settings.source),
        "read_ready": not any(item.startswith(("missing_source", "source_baseline", "movement_", "position_",
                                               "invalid_", "reversed_")) for item in blockers),
        "ready": not blockers,
        "blockers": blockers,
        "source": {"schema": source_schema, "totals": totals, "class_totals": projection["class_totals"],
                   "account_count": len(projection["accounts"])},
        "target": target_report,
    }
