from __future__ import annotations

import json
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

from .arissto import select_rows, source_connection, source_fingerprint
from .config import Settings
from .connections import FineractApi, postgres_connection
from .native_shares import BLOCK, NativeShareContract, inspect_native_shares
from .state import State


SOURCE_SYSTEM = "arissto"
ACCOUNT_EXTERNAL_PREFIX = "arissto:share:"
PRODUCT_NAME_PREFIX = "Arissto Credesal"
PLANNING_PROVISIONING_BLOCKERS = {
    "native_share_products_not_provisioned",
    "controlled_native_share_lifecycle_proof",
}


@contextmanager
def _postgres_write_connection(url: str):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise RuntimeError("psycopg is required for native share provenance writes") from exc
    with psycopg.connect(url, autocommit=False) as conn:
        yield conn


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(type(value).__name__)


def _stable_hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode()).hexdigest()


def _idempotency_key(operation: str, identity: str) -> str:
    """Return a stable key that fits Fineract's varchar(50) command column."""
    digest = sha256(f"{operation}|{identity}".encode("utf-8")).hexdigest()[:24]
    return f"sh2:{operation}:{digest}"


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def account_external_id(source_key: str) -> str:
    parts = source_key.split("|")
    if len(parts) != 2 or parts[0] != "AFI_ACCION" or not parts[1]:
        raise ValueError(f"Invalid native share account source key: {source_key}")
    return f"{ACCOUNT_EXTERNAL_PREFIX}{parts[1]}"


def movement_source_key(row: dict[str, Any]) -> str:
    return "MOV_APORTACIONES|{}|{}|{}".format(
        str(row["ID_EMPRESA"]).strip(), str(row["ID_SUCURSAL"]).strip(),
        str(row["ID_MOV_APORTACION"]).strip(),
    )


def certificate_source_key(row: dict[str, Any]) -> str:
    return "AFI_CERTIFICADO|{}|{}|{}".format(
        int(row["ID_CERTIFICADO"]), int(row["ID_ASOCIADO"]), int(row["ID_TIPO_ACCION"]),
    )


def _date_string(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _truthy(value: Any) -> bool:
    return str(value or "").strip().upper() in {"1", "S", "Y", "TRUE"}


def extract_native_share_records(settings: Settings, contract: NativeShareContract,
                                 source_keys: list[str] | None = None) -> list[dict[str, Any]]:
    source = contract.raw["source"]
    wanted = set(source_keys or [])
    with source_connection(settings.source) as conn:
        positions = select_rows(conn, f"""
            SELECT a.*,RTRIM(s.NUMERO_AFILIACION) NUMERO_AFILIACION
            FROM dbo.{source['position_table']} a
            JOIN dbo.{source['party_table']} s ON s.ID_ASOCIADO=a.ID_ASOCIADO
            ORDER BY a.ID_ACCION
        """)
        certificates = select_rows(conn, f"SELECT * FROM dbo.{source['certificate_table']} ORDER BY ID_CERTIFICADO")
        movements = select_rows(conn, f"""
            SELECT * FROM dbo.{source['movement_table']}
            ORDER BY FECHA,ID_EMPRESA,ID_SUCURSAL,ID_MOV_APORTACION
        """)

    certs_by_position: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    events_by_position: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in certificates:
        certs_by_position[(int(row["ID_ASOCIADO"]), int(row["ID_TIPO_ACCION"]))].append(row)
    for row in movements:
        events_by_position[(int(row["ID_ASOCIADO"]), int(row["ID_TIPO_ACCION"]))].append(row)

    unit_price = _decimal(contract.raw["expected"]["unit_price"])
    records: list[dict[str, Any]] = []
    for position in positions:
        source_key = f"AFI_ACCION|{position['ID_ACCION']}"
        if wanted and source_key not in wanted:
            continue
        share_type = str(int(position["ID_TIPO_ACCION"]))
        if share_type not in contract.raw["share_classes"]:
            continue
        identity = (int(position["ID_ASOCIADO"]), int(position["ID_TIPO_ACCION"]))
        record_certificates = []
        for row in certs_by_position.get(identity, []):
            certificate = {
                "source_key": certificate_source_key(row),
                "certificate_id": int(row["ID_CERTIFICADO"]),
                "associate_id": int(row["ID_ASOCIADO"]),
                "share_type": int(row["ID_TIPO_ACCION"]),
                "status_id": int(row["ID_ESTADO_CERTIFICADO"]),
                "branch_id": str(row.get("ID_SUCURSAL") or "").strip() or None,
                "book_id": row.get("ID_LIBRO_ACCIONES"),
                "certificate_number": row.get("NUMERO_CERTIFICADO"),
                "certificate_date": _date_string(row["FECHA_CERTIFICADO"]) if row.get("FECHA_CERTIFICADO") else None,
                "unit_price": format(_decimal(row.get("VALOR_ACCION")), "f"),
                "represented_shares": format(_decimal(row.get("NUMERO_ACCIONES")), "f"),
                "subscribed_shares": format(_decimal(row.get("ACCIONES_SUSCRITAS")), "f"),
                "paid_shares": format(_decimal(row.get("ACCIONES_PAGADAS")), "f"),
                "subscribed_balance": format(_decimal(row.get("SALDO_SUSCRITO")), "f"),
                "paid_balance": format(_decimal(row.get("SALDO_PAGADO")), "f"),
                "current_balance": format(_decimal(row.get("SALDO_ACCIONES")), "f"),
                "blocked_balance": format(_decimal(row.get("SALDO_BLOQUEADO")), "f"),
                "available_balance": format(_decimal(row.get("SALDO_DISPONIBLE")), "f"),
                "certificate_number_start": row.get("ACCION_INI"),
                "certificate_number_end": row.get("ACCION_FIN"),
                "folio": row.get("FOLIO"), "line_number": row.get("LINEA"), "series": row.get("SERIE"),
                "printed": bool(row.get("IMPRESO")), "blocked": _truthy(row.get("BLOQUEO")),
                "restricted": _truthy(row.get("RESTRINGIDO")),
                "reference": row.get("REFERENCIA"), "certification": row.get("CERTIFICACION"),
                "capital_account_source_id": str(row.get("ID_CUENTA_CAPITAL") or "").strip() or None,
                "interest_account_source_id": str(row.get("ID_CUENTA_INTERES") or "").strip() or None,
            }
            certificate["source_hash"] = _stable_hash(certificate)
            record_certificates.append(certificate)

        record_events = []
        for row in sorted(events_by_position.get(identity, []), key=lambda item: (
            _date_string(item["FECHA"]), movement_source_key(item),
        )):
            amount = _decimal(row["MONTO"])
            event = {
                "source_key": movement_source_key(row), "event_date": _date_string(row["FECHA"]),
                "shares": int(amount / unit_price), "unit_price": format(unit_price, "f"),
                "amount": format(amount, "f"), "source_payment_type_id": int(row["ID_TIPO_PAGO"]),
            }
            event["source_hash"] = _stable_hash(event)
            record_events.append(event)

        paid_shares = sum(int(_decimal(item["paid_shares"])) for item in record_certificates)
        subscribed_shares = sum(int(_decimal(item["subscribed_shares"])) for item in record_certificates)
        record = {
            "source_key": source_key, "share_type": share_type,
            "class_code": contract.raw["share_classes"][share_type]["code"],
            "client_external_id": str(position["NUMERO_AFILIACION"]).strip(),
            "account_external_id": account_external_id(source_key),
            "paid_shares": paid_shares, "subscribed_shares": subscribed_shares,
            "paid_capital": format(sum((_decimal(item["amount"]) for item in record_events), Decimal("0")), "f"),
            "events": record_events, "certificates": record_certificates,
        }
        record["source_hash"] = _stable_hash(record)
        records.append(record)
    return records


def _target_context(settings: Settings, contract: NativeShareContract,
                    records: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.target.pg_url:
        raise RuntimeError("Native share planning requires target PostgreSQL inspection")
    external_ids = sorted({record["client_external_id"] for record in records})
    account_external_ids = sorted({record["account_external_id"] for record in records})
    product_external_ids = sorted(item["product_external_id"] for item in contract.raw["share_classes"].values())
    with postgres_connection(settings.target.pg_url) as conn:
        clients = conn.execute(
            "SELECT external_id,id,status_enum FROM m_client WHERE external_id=ANY(%s)", (external_ids,),
        ).fetchall()
        savings = conn.execute("""
            SELECT sma.client_id,sma.savings_account_id,sma.source_key,sma.source_opened_on
            FROM credesal_savings_migration_account sma
            JOIN credesal_savings_migration_owner smo ON smo.migration_account_id=sma.id
              AND smo.client_id=sma.client_id AND smo.is_native_owner=true
            JOIN m_savings_account sa ON sa.id=sma.savings_account_id AND sa.client_id=sma.client_id
            WHERE sma.deposit_type='VISTA' AND sma.migration_status='RECONCILED'
              AND sa.deposit_type_enum=100 AND sa.status_enum=300 AND sa.currency_code=%s
            ORDER BY sma.client_id,sma.source_opened_on,sma.source_key
        """, (contract.raw["target"]["currency"],)).fetchall()
        products = conn.execute(
            "SELECT id,external_id,currency_code,total_shares,unit_price,minimum_client_shares,"
            "nominal_client_shares,maximum_client_shares,accounting_type FROM m_share_product "
            "WHERE external_id=ANY(%s)", (product_external_ids,),
        ).fetchall()
        accounts = conn.execute(
            "SELECT id,external_id,client_id,product_id,savings_account_id,status_enum,total_approved_shares,currency_code "
            "FROM m_share_account WHERE external_id=ANY(%s)", (account_external_ids,),
        ).fetchall()
        event_maps = conn.execute(
            "SELECT source_key,source_hash,contract_hash,share_account_id,share_transaction_id,event_status "
            "FROM credesal_share_native_event_map WHERE source_system=%s",
            (SOURCE_SYSTEM,),
        ).fetchall()

    savings_by_client: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for client_id, savings_id, source_key, opened_on in savings:
        savings_by_client[int(client_id)].append({
            "id": int(savings_id), "source_key": str(source_key),
            "opened_on": _date_string(opened_on) if opened_on else None,
        })
    return {
        "clients": {str(row[0]): {"id": int(row[1]), "status": int(row[2])} for row in clients},
        "savings": dict(savings_by_client),
        "products": {str(row[1]): {
            "id": int(row[0]), "currency": str(row[2]), "total": int(row[3]),
            "unit_price": format(_decimal(row[4]), "f"), "minimum": int(row[5]),
            "nominal": int(row[6]), "maximum": int(row[7]), "accounting_type": int(row[8]),
        } for row in products},
        "accounts": {str(row[1]): {
            "id": int(row[0]), "client_id": int(row[2]), "product_id": int(row[3]),
            "savings_account_id": int(row[4]), "status": int(row[5]),
            "approved_shares": int(row[6] or 0), "currency": str(row[7]),
        } for row in accounts},
        "event_maps": {str(row[0]): {
            "source_hash": str(row[1]), "contract_hash": str(row[2]), "account_id": int(row[3]),
            "transaction_id": int(row[4]) if row[4] is not None else None, "status": str(row[5]),
        } for row in event_maps},
    }


def _product_contracts(contract: NativeShareContract) -> dict[str, dict[str, Any]]:
    return {
        share_type: {
            "share_type": share_type, "code": item["code"], "external_id": item["product_external_id"],
            "numbering_code": item["numbering_code"],
            "total_shares": int(item["approved_total_shares"]),
            "minimum_shares": int(item["approved_minimum_client_shares"]),
            "nominal_shares": int(item["approved_nominal_client_shares"]),
            "maximum_shares": int(item["approved_maximum_client_shares"]),
            "unit_price": str(contract.raw["expected"]["unit_price"]),
            "currency": contract.raw["target"]["currency"],
        }
        for share_type, item in contract.raw["share_classes"].items()
    }


def build_native_share_plan(settings: Settings, state: State, contract: NativeShareContract,
                            source_keys: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    inspection = inspect_native_shares(settings, contract)
    ignored = set(PLANNING_PROVISIONING_BLOCKERS)
    if int(inspection["target"].get("eligible_reconciled_vista_clients", 0)) >= 34:
        ignored.add("reconciled_native_savings_prerequisite")
    blockers = [item for item in inspection["blockers"] if item not in ignored]
    records = extract_native_share_records(settings, contract, source_keys)
    target = _target_context(settings, contract, records)
    products = _product_contracts(contract)
    actions: list[dict[str, Any]] = []
    counts = Counter()
    for record in records:
        client = target["clients"].get(record["client_external_id"])
        savings_options = target["savings"].get(client["id"], []) if client else []
        existing = target["accounts"].get(record["account_external_id"])
        mapped_events = [target["event_maps"].get(event["source_key"]) for event in record["events"]]
        reason = None
        action = "create"
        if client is None:
            action, reason = "quarantine", "client_dependency_missing"
        elif client["status"] != 300:
            action, reason = "quarantine", "client_dependency_inactive"
        elif not savings_options:
            action, reason = "quarantine", "eligible_same_client_vista_missing"
        elif existing:
            exact_maps = all(item and item["source_hash"] == event["source_hash"]
                             and item["contract_hash"] == contract.contract_hash
                             and item["account_id"] == existing["id"] and item["status"] == "RECONCILED"
                             for item, event in zip(mapped_events, record["events"], strict=True))
            if (exact_maps and existing["status"] == 300
                    and existing["approved_shares"] == record["paid_shares"]):
                action = "unchanged"
            else:
                action = "resume"
        counts[action] += 1
        product = products[record["share_type"]]
        selected_savings = savings_options[0] if savings_options else None
        prerequisite = {
            "client_id": client["id"] if client else None,
            "savings_account_id": selected_savings["id"] if selected_savings else None,
            "savings_source_key": selected_savings["source_key"] if selected_savings else None,
            "product_external_id": product["external_id"], "product_contract": product,
        }
        actions.append({
            "source_key": record["source_key"], "source_hash": record["source_hash"],
            "action": action, "reason": reason, "target_id": existing["id"] if existing else None,
            "account_external_id": record["account_external_id"], "share_type": record["share_type"],
            "paid_shares": record["paid_shares"], "subscribed_shares": record["subscribed_shares"],
            "event_count": len(record["events"]), "certificate_count": len(record["certificates"]),
            **prerequisite, "prerequisite_hash": _stable_hash(prerequisite),
        })
    actions.sort(key=lambda item: item["source_key"])
    document = {
        "block": BLOCK, "applicable": not blockers, "contract_hash": contract.contract_hash,
        "schema_signature": inspection["schema_signature"], "source_fingerprint": source_fingerprint(settings.source),
        "scope": source_keys or "all", "counts": dict(counts), "actions": actions,
        "product_contracts": products, "readiness_blockers": blockers,
        "quarantine_count": counts["quarantine"],
    }
    plan_id = state.save_plan(
        settings.target.fingerprint, BLOCK, source_fingerprint(settings.source), contract.contract_hash, document,
    )
    return plan_id, document


def _resource_id(result: dict[str, Any]) -> int:
    for field in ("resourceId", "entityId", "subResourceId"):
        if result.get(field) is not None:
            return int(result[field])
    raise RuntimeError(f"Fineract response is missing a resource identifier: {result}")


def _product_resources(settings: Settings, contract: NativeShareContract) -> dict[str, Any]:
    if not settings.target.pg_url:
        raise RuntimeError("Native share product provisioning requires target PostgreSQL inspection")
    accounting = contract.raw["accounting_candidates"]
    gl_codes = {
        definition["gl_code"]
        for mappings in accounting.values()
        for definition in mappings.values()
    }
    payment_mappings = contract.raw["accounting_strategy"]["payment_channel_mappings"]
    gl_codes.update(item["gl_code"] for item in payment_mappings)
    with postgres_connection(settings.target.pg_url) as conn:
        gl_rows = conn.execute(
            "SELECT id,gl_code,classification_enum,disabled FROM acc_gl_account WHERE gl_code=ANY(%s)",
            (sorted(gl_codes),),
        ).fetchall()
        payment_rows = conn.execute(
            "SELECT id,value,code_name FROM m_payment_type", ()
        ).fetchall()
    gl = {str(row[1]): {"id": int(row[0]), "classification": int(row[2]), "disabled": bool(row[3])}
          for row in gl_rows}
    if set(gl) != gl_codes or any(item["disabled"] for item in gl.values()):
        raise RuntimeError("Native share GL resources are missing or disabled")
    payments: dict[int, int] = {}
    payment_report: list[dict[str, int]] = []
    for mapping in payment_mappings:
        code = mapping.get("target_payment_type_code")
        matches = [row for row in payment_rows if (
            (code and str(row[2] or "") == code)
            or (not code and str(row[1]) == mapping["target_payment_type_value"])
        )]
        if len(matches) != 1:
            raise RuntimeError(f"Native share payment type is not unique: {mapping['source_payment_type_id']}")
        source_id = int(mapping["source_payment_type_id"])
        payments[source_id] = int(matches[0][0])
        payment_report.append({"paymentTypeId": int(matches[0][0]), "fundSourceAccountId": gl[mapping["gl_code"]]["id"]})
    shared = accounting["shared"]
    class_gl = {
        share_type: gl[accounting[item["code"]]["shareEquityId"]["gl_code"]]["id"]
        for share_type, item in contract.raw["share_classes"].items()
    }
    return {
        "shareReferenceId": gl[shared["shareReferenceId"]["gl_code"]]["id"],
        "shareSuspenseId": gl[shared["shareSuspenseId"]["gl_code"]]["id"],
        "incomeFromFeeAccountId": gl[shared["incomeFromFeeAccountId"]["gl_code"]]["id"],
        "shareEquityIds": class_gl, "paymentTypeIds": payments,
        "paymentChannelToFundSourceMappings": payment_report,
    }


def _product_payload(item: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    code = item["code"]
    return {
        "name": f"{PRODUCT_NAME_PREFIX} shares {code.title()}",
        "shortName": "ACOM" if code == "COMMON" else "APRF",
        "numberingCode": item["numbering_code"],
        "description": f"Native {code.lower()} paid share capital migrated from Arissto",
        "externalId": item["external_id"], "currencyCode": item["currency"],
        "digitsAfterDecimal": 2, "inMultiplesOf": 1, "totalShares": item["total_shares"],
        "sharesIssued": item["total_shares"], "unitPrice": item["unit_price"],
        "minimumShares": item["minimum_shares"], "nominalShares": item["nominal_shares"],
        "maximumShares": item["maximum_shares"], "allowDividendCalculationForInactiveClients": False,
        "lockinPeriodFrequency": 0, "lockinPeriodFrequencyType": 0,
        "minimumActivePeriodForDividends": 0, "minimumactiveperiodFrequencyType": 0,
        "marketPricePeriods": [{
            "fromDate": "2023-02-01", "shareValue": item["unit_price"],
            "dateFormat": "yyyy-MM-dd", "locale": "en",
        }],
        "accountingRule": 2, "shareReferenceId": resources["shareReferenceId"],
        "shareSuspenseId": resources["shareSuspenseId"],
        "shareEquityId": resources["shareEquityIds"][item["share_type"]],
        "incomeFromFeeAccountId": resources["incomeFromFeeAccountId"],
        "paymentChannelToFundSourceMappings": resources["paymentChannelToFundSourceMappings"],
        "chargesSelected": [], "locale": "en", "dateFormat": "yyyy-MM-dd",
    }


def _ensure_products(settings: Settings, contract: NativeShareContract,
                     planned: dict[str, dict[str, Any]]) -> tuple[dict[str, int], dict[str, Any]]:
    resources = _product_resources(settings, contract)
    api = FineractApi(settings.target)
    product_ids: dict[str, int] = {}
    for share_type, item in sorted(planned.items()):
        if item != _product_contracts(contract)[share_type]:
            raise RuntimeError(f"Native share product contract changed after planning: {share_type}")
        with postgres_connection(settings.target.pg_url or "") as conn:
            rows = conn.execute(
                "SELECT id,currency_code,total_shares,unit_price,minimum_client_shares,nominal_client_shares,"
                "maximum_client_shares,accounting_type,numbering_code FROM m_share_product WHERE external_id=%s",
                (item["external_id"],),
            ).fetchall()
        if len(rows) > 1:
            raise RuntimeError(f"Duplicate native share product external ID: {item['external_id']}")
        if rows:
            row = rows[0]
            observed = {
                "currency": str(row[1]), "total": int(row[2]), "unit_price": format(_decimal(row[3]), "f"),
                "minimum": int(row[4]), "nominal": int(row[5]), "maximum": int(row[6]),
                "accounting_type": int(row[7]),
            }
            expected = {
                "currency": item["currency"], "total": item["total_shares"],
                "unit_price": format(_decimal(item["unit_price"]), "f"), "minimum": item["minimum_shares"],
                "nominal": item["nominal_shares"], "maximum": item["maximum_shares"], "accounting_type": 2,
            }
            if observed != expected:
                raise RuntimeError(f"Native share product drift: {item['external_id']}")
            product_id = int(row[0])
            observed_numbering_code = row[8]
            if observed_numbering_code not in (None, "", item["numbering_code"]):
                raise RuntimeError(f"Native share product numbering code drift: {item['external_id']}")
            expected_payment_mappings = {
                (mapping["paymentTypeId"], mapping["fundSourceAccountId"])
                for mapping in resources["paymentChannelToFundSourceMappings"]
            }
            with postgres_connection(settings.target.pg_url or "") as conn:
                mapping_rows = conn.execute(
                    "SELECT payment_type,gl_account_id FROM acc_product_mapping "
                    "WHERE product_id=%s AND product_type=4 AND payment_type IS NOT NULL",
                    (product_id,),
                ).fetchall()
            observed_payment_mappings = {(int(mapping[0]), int(mapping[1])) for mapping in mapping_rows}
            payload = {"locale": "en"}
            if observed_numbering_code in (None, ""):
                payload["numberingCode"] = item["numbering_code"]
            if observed_payment_mappings != expected_payment_mappings:
                payload["paymentChannelToFundSourceMappings"] = resources["paymentChannelToFundSourceMappings"]
            if len(payload) > 1:
                api.request("PUT", f"products/share/{product_id}", payload,
                            idempotency_key=_idempotency_key("product-map", f"{product_id}|{_stable_hash(payload)}"))
            product_ids[share_type] = product_id
            continue
        payload = _product_payload(item, resources)
        result = api.request("POST", "products/share", payload,
                             idempotency_key=_idempotency_key("product", _stable_hash(payload)))
        product_ids[share_type] = _resource_id(result)
    return product_ids, resources


def _account_row(settings: Settings, external_id: str) -> dict[str, Any] | None:
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute(
            "SELECT id,client_id,product_id,savings_account_id,status_enum,total_approved_shares,currency_code "
            "FROM m_share_account WHERE external_id=%s", (external_id,),
        ).fetchall()
    if len(rows) > 1:
        raise RuntimeError(f"Duplicate native share account external ID: {external_id}")
    if not rows:
        return None
    row = rows[0]
    return {"id": int(row[0]), "client_id": int(row[1]), "product_id": int(row[2]),
            "savings_account_id": int(row[3]), "status": int(row[4]),
            "approved_shares": int(row[5] or 0), "currency": str(row[6])}


def _transaction_rows(settings: Settings, account_id: int) -> list[dict[str, Any]]:
    with postgres_connection(settings.target.pg_url or "") as conn:
        rows = conn.execute("""
            SELECT id,transaction_date,total_shares,unit_price,amount,status_enum,type_enum,payment_type_id
            FROM m_share_account_transactions
            WHERE account_id=%s AND is_active=true AND type_enum=500
            ORDER BY transaction_date,id
        """, (account_id,)).fetchall()
    return [{
        "id": int(row[0]), "date": _date_string(row[1]), "shares": int(row[2]),
        "unit_price": format(_decimal(row[3]), "f"), "amount": format(_decimal(row[4]), "f"),
        "status": int(row[5]), "type": int(row[6]),
        "payment_type_id": int(row[7]) if row[7] is not None else None,
    } for row in rows]


def _matching_transaction(rows: list[dict[str, Any]], event: dict[str, Any], payment_type_id: int) -> dict[str, Any] | None:
    matches = [row for row in rows if (
        row["date"] == event["event_date"] and row["shares"] == event["shares"]
        and _decimal(row["unit_price"]) == _decimal(event["unit_price"])
        and _decimal(row["amount"]) == _decimal(event["amount"])
        and row["payment_type_id"] == payment_type_id
    )]
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous native share transaction read-back: {event['source_key']}")
    return matches[0] if matches else None


def _ensure_account_and_events(settings: Settings, contract: NativeShareContract, api: FineractApi,
                               action: dict[str, Any], record: dict[str, Any], product_id: int,
                               payment_type_ids: dict[int, int]) -> tuple[int, dict[str, int]]:
    events = record["events"]
    if not events:
        raise RuntimeError(f"Native share position has no purchase events: {record['source_key']}")
    account = _account_row(settings, action["account_external_id"])
    first = events[0]
    first_payment_type = payment_type_ids[first["source_payment_type_id"]]
    if account is None:
        result = api.request("POST", "accounts/share", {
            "clientId": action["client_id"], "productId": product_id,
            "savingsAccountId": action["savings_account_id"], "externalId": action["account_external_id"],
            "submittedDate": first["event_date"], "applicationDate": first["event_date"],
            "requestedShares": first["shares"], "paymentTypeId": first_payment_type,
            "allowDividendCalculationForInactiveClients": False,
            "dateFormat": "yyyy-MM-dd", "locale": "en",
        }, idempotency_key=_idempotency_key("account", record["source_hash"]))
        account_id = _resource_id(result)
        account = _account_row(settings, action["account_external_id"])
        if account is None or account["id"] != account_id:
            raise RuntimeError(f"Unable to recover created native share account: {record['source_key']}")
    account_id = account["id"]
    expected_identity = (action["client_id"], product_id, action["savings_account_id"])
    if (account["client_id"], account["product_id"], account["savings_account_id"]) != expected_identity:
        raise RuntimeError(f"Native share account identity collision: {record['source_key']}")

    transaction_ids: dict[str, int] = {}
    rows = _transaction_rows(settings, account_id)
    initial = _matching_transaction(rows, first, first_payment_type)
    if initial is None and account["status"] == 100:
        recoverable = [row for row in rows if (
            row["date"] == first["event_date"] and row["shares"] == first["shares"]
            and _decimal(row["unit_price"]) == _decimal(first["unit_price"])
            and _decimal(row["amount"]) == _decimal(first["amount"])
            and row["payment_type_id"] is None and row["status"] == 100
        )]
        if len(recoverable) == 1:
            payload = {
                "requestedShares": first["shares"], "applicationDate": first["event_date"],
                "paymentTypeId": first_payment_type, "dateFormat": "yyyy-MM-dd", "locale": "en",
            }
            api.request("PUT", f"accounts/share/{account_id}", payload,
                        idempotency_key=_idempotency_key("account-update", _stable_hash(payload)))
            rows = _transaction_rows(settings, account_id)
            initial = _matching_transaction(rows, first, first_payment_type)
    if initial is None:
        raise RuntimeError(f"Initial native share purchase is missing after account creation: {first['source_key']}")
    if initial["status"] == 100:
        api.request("POST", f"accounts/share/{account_id}", {
            "approvedDate": first["event_date"], "dateFormat": "yyyy-MM-dd", "locale": "en",
            "note": f"Arissto {first['source_key']}",
        }, query={"command": "approve"}, idempotency_key=_idempotency_key("approve", first["source_hash"]))
    account = _account_row(settings, action["account_external_id"])
    if account and account["status"] == 200:
        api.request("POST", f"accounts/share/{account_id}", {
            "activatedDate": first["event_date"], "dateFormat": "yyyy-MM-dd", "locale": "en",
        }, query={"command": "activate"}, idempotency_key=_idempotency_key("activate", record["source_hash"]))
    rows = _transaction_rows(settings, account_id)
    initial = _matching_transaction(rows, first, first_payment_type)
    if initial is None or initial["status"] != 300:
        raise RuntimeError(f"Initial native share purchase did not approve: {first['source_key']}")
    transaction_ids[first["source_key"]] = initial["id"]

    for event in events[1:]:
        payment_type_id = payment_type_ids[event["source_payment_type_id"]]
        rows = _transaction_rows(settings, account_id)
        transaction = _matching_transaction(rows, event, payment_type_id)
        if transaction is None:
            api.request("POST", f"accounts/share/{account_id}", {
                "requestedDate": event["event_date"], "requestedShares": event["shares"],
                "paymentTypeId": payment_type_id, "dateFormat": "yyyy-MM-dd", "locale": "en",
            }, query={"command": "applyadditionalshares"},
                idempotency_key=_idempotency_key("apply-additional", event["source_hash"]))
            transaction = _matching_transaction(_transaction_rows(settings, account_id), event, payment_type_id)
        if transaction is None:
            raise RuntimeError(f"Unable to recover additional native share purchase: {event['source_key']}")
        if transaction["status"] == 100:
            api.request("POST", f"accounts/share/{account_id}", {
                "requestedShares": [{"id": transaction["id"]}],
            }, query={"command": "approveadditionalshares"},
                idempotency_key=_idempotency_key("approve-additional", event["source_hash"]))
            transaction = _matching_transaction(_transaction_rows(settings, account_id), event, payment_type_id)
        if transaction is None or transaction["status"] != 300:
            raise RuntimeError(f"Additional native share purchase did not approve: {event['source_key']}")
        transaction_ids[event["source_key"]] = transaction["id"]
    return account_id, transaction_ids


def _persist_projection(settings: Settings, contract: NativeShareContract, plan_id: str, run_id: str,
                        action: dict[str, Any], record: dict[str, Any], account_id: int,
                        product_id: int, transaction_ids: dict[str, int]) -> None:
    class_name = contract.raw["share_classes"][record["share_type"]]["code"]
    with _postgres_write_connection(settings.target.pg_url or "") as conn:
        for event in record["events"]:
            conn.execute("""
                INSERT INTO credesal_share_native_event_map
                  (source_system,source_table,source_key,source_hash,contract_hash,plan_id,run_id,client_id,
                   share_product_id,share_account_id,share_transaction_id,event_kind,event_status,event_date,
                   total_shares,unit_price,amount,applied_at,updated_at)
                VALUES (%s,'MOV_APORTACIONES',%s,%s,%s,%s,%s,%s,%s,%s,%s,'PURCHASE','APPLIED',%s,%s,%s,%s,
                        CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                ON CONFLICT (source_system,source_table,source_key) DO UPDATE SET
                  source_hash=EXCLUDED.source_hash,contract_hash=EXCLUDED.contract_hash,plan_id=EXCLUDED.plan_id,
                  run_id=EXCLUDED.run_id,client_id=EXCLUDED.client_id,share_product_id=EXCLUDED.share_product_id,
                  share_account_id=EXCLUDED.share_account_id,share_transaction_id=EXCLUDED.share_transaction_id,
                  event_kind=EXCLUDED.event_kind,event_status='APPLIED',event_date=EXCLUDED.event_date,
                  total_shares=EXCLUDED.total_shares,unit_price=EXCLUDED.unit_price,amount=EXCLUDED.amount,
                  error_code=NULL,applied_at=CURRENT_TIMESTAMP,reconciled_at=NULL,updated_at=CURRENT_TIMESTAMP
            """, (SOURCE_SYSTEM, event["source_key"], event["source_hash"], contract.contract_hash,
                    plan_id, run_id, action["client_id"], product_id, account_id,
                    transaction_ids[event["source_key"]], event["event_date"], event["shares"],
                    event["unit_price"], event["amount"]))
        for certificate in record["certificates"]:
            conn.execute("""
                INSERT INTO credesal_share_certificate
                  (source_system,source_key,source_hash,client_id,share_account_id,arissto_certificate_id,
                   arissto_associate_id,arissto_share_type_id,share_type_name,arissto_status_id,branch_id,book_id,
                   certificate_number,certificate_date,unit_price,represented_shares,initial_share_number,final_share_number,
                   current_balance,subscribed_shares,subscribed_balance,paid_shares,paid_balance,blocked_balance,
                   available_balance,folio,line_number,series,printed,blocked,restricted,reference,certification,
                   capital_account_source_id,interest_account_source_id,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
                ON CONFLICT (source_system,source_key) DO UPDATE SET
                  source_hash=EXCLUDED.source_hash,client_id=EXCLUDED.client_id,share_account_id=EXCLUDED.share_account_id,
                  share_type_name=EXCLUDED.share_type_name,arissto_status_id=EXCLUDED.arissto_status_id,
                  subscribed_shares=EXCLUDED.subscribed_shares,subscribed_balance=EXCLUDED.subscribed_balance,
                  paid_shares=EXCLUDED.paid_shares,paid_balance=EXCLUDED.paid_balance,current_balance=EXCLUDED.current_balance,
                  blocked_balance=EXCLUDED.blocked_balance,available_balance=EXCLUDED.available_balance,
                  updated_at=CURRENT_TIMESTAMP
            """, (SOURCE_SYSTEM, certificate["source_key"], certificate["source_hash"], action["client_id"], account_id,
                    certificate["certificate_id"], certificate["associate_id"], certificate["share_type"], class_name,
                    certificate["status_id"], certificate["branch_id"], certificate["book_id"],
                    certificate["certificate_number"], certificate["certificate_date"], certificate["unit_price"],
                    certificate["represented_shares"], certificate["certificate_number_start"],
                    certificate["certificate_number_end"], certificate["current_balance"],
                    certificate["subscribed_shares"], certificate["subscribed_balance"], certificate["paid_shares"],
                    certificate["paid_balance"], certificate["blocked_balance"], certificate["available_balance"],
                    certificate["folio"], certificate["line_number"], certificate["series"], certificate["printed"],
                    certificate["blocked"], certificate["restricted"], certificate["reference"],
                    certificate["certification"], certificate["capital_account_source_id"],
                    certificate["interest_account_source_id"]))
        conn.commit()


def _apply_guard(settings: Settings, state: State, contract: NativeShareContract, plan_id: str,
                 production_confirmation: str | None) -> dict[str, Any]:
    plan = state.plan(plan_id)
    if plan["block"] != BLOCK:
        raise RuntimeError("Plan is not a native-share-capital plan")
    if plan["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Native share plan belongs to a different target")
    if plan["source_fingerprint"] != source_fingerprint(settings.source):
        raise RuntimeError("Native share plan source fingerprint changed")
    if plan["contract_hash"] != contract.contract_hash:
        raise RuntimeError("Native share contract changed after planning")
    if settings.target.name == "prod" and production_confirmation != settings.target.fingerprint:
        raise RuntimeError(f"Production apply requires --confirm-production {settings.target.fingerprint}")
    inspection = inspect_native_shares(settings, contract)
    ignored = set(PLANNING_PROVISIONING_BLOCKERS)
    if int(inspection["target"].get("eligible_reconciled_vista_clients", 0)) >= 34:
        ignored.add("reconciled_native_savings_prerequisite")
    blockers = [item for item in inspection["blockers"] if item not in ignored]
    if blockers:
        raise RuntimeError(f"Native share readiness changed: {blockers}")
    if inspection["schema_signature"] != plan["document"]["schema_signature"]:
        raise RuntimeError("Native share destination schema changed after planning")
    if not plan["document"].get("applicable"):
        raise RuntimeError("Native share plan is not applicable")
    return plan


def apply_native_share_plan(settings: Settings, state: State, contract: NativeShareContract, plan_id: str,
                            production_confirmation: str | None = None,
                            source_keys: set[str] | None = None) -> tuple[str, dict[str, int]]:
    plan = _apply_guard(settings, state, contract, plan_id, production_confirmation)
    actions = [action for action in plan["document"]["actions"]
               if source_keys is None or action["source_key"] in source_keys]
    records = {record["source_key"]: record for record in extract_native_share_records(
        settings, contract, [action["source_key"] for action in actions],
    )}
    for action in actions:
        record = records.get(action["source_key"])
        if record is None or record["source_hash"] != action["source_hash"]:
            raise RuntimeError(f"Native share source changed after planning: {action['source_key']}")
    product_ids, resources = _ensure_products(settings, contract, plan["document"]["product_contracts"])
    api = FineractApi(settings.target)
    run_id = state.start_run(plan)
    counts = Counter()
    for action in actions:
        key = action["source_key"]
        if action["action"] == "quarantine":
            state.record_item(run_id, key, "quarantine", action["source_hash"], "quarantined",
                              action.get("target_id"), action.get("reason"))
            counts["quarantined"] += 1
            continue
        if action["action"] == "unchanged":
            state.record_item(run_id, key, "unchanged", action["source_hash"], "unchanged",
                              action.get("target_id"))
            counts["unchanged"] += 1
            continue
        try:
            record = records[key]
            product_id = product_ids[action["share_type"]]
            account_id, transaction_ids = _ensure_account_and_events(
                settings, contract, api, action, record, product_id, resources["paymentTypeIds"],
            )
            _persist_projection(settings, contract, plan_id, run_id, action, record, account_id,
                                product_id, transaction_ids)
            state.save_mapping(settings.target.fingerprint, BLOCK, key, str(account_id), action["source_hash"])
            state.record_item(run_id, key, action["action"], action["source_hash"], "succeeded", str(account_id))
            counts["succeeded"] += 1
        except Exception as exc:
            message = " ".join(str(exc).splitlines())[:1000]
            state.record_item(run_id, key, action["action"], action["source_hash"], "failed",
                              action.get("target_id"), f"{type(exc).__name__}:{message}"[:1100])
            counts["failed"] += 1
    state.finish_run(run_id, "completed" if counts["failed"] == 0 else "completed-with-errors", dict(counts))
    return run_id, dict(counts)


def reconcile_native_shares(settings: Settings, state: State, contract: NativeShareContract,
                            run_id: str) -> dict[str, Any]:
    run = state.run(run_id)
    if run["block"] != BLOCK or run["target_fingerprint"] != settings.target.fingerprint:
        raise RuntimeError("Native share run does not belong to the selected target")
    items = state.run_items(run_id)
    eligible_items = [item for item in items if item["status"] in {"succeeded", "unchanged"}]
    keys = sorted(item["source_key"] for item in eligible_items)
    records = {record["source_key"]: record for record in extract_native_share_records(settings, contract, keys)}
    plan = state.plan(run["plan_id"])
    actions = {action["source_key"]: action for action in plan["document"]["actions"] if action["source_key"] in keys}
    event_keys = sorted(event["source_key"] for record in records.values() for event in record["events"])
    certificate_keys = sorted(item["source_key"] for record in records.values() for item in record["certificates"])
    with postgres_connection(settings.target.pg_url or "") as conn:
        account_rows = conn.execute("""
            SELECT sa.id,sa.external_id,sa.client_id,sa.product_id,sp.external_id,sa.savings_account_id,
                   sa.status_enum,sa.total_approved_shares,sa.currency_code
            FROM m_share_account sa JOIN m_share_product sp ON sp.id=sa.product_id
            WHERE sa.external_id=ANY(%s)
        """, (sorted(record["account_external_id"] for record in records.values()),)).fetchall() if records else []
        event_rows = conn.execute("""
            SELECT em.source_key,em.source_hash,em.contract_hash,em.client_id,em.share_product_id,
                   em.share_account_id,em.share_transaction_id,em.event_status,em.event_date,
                   em.total_shares,em.unit_price,em.amount,
                   tx.transaction_date,tx.total_shares,tx.unit_price,tx.amount,tx.status_enum,tx.type_enum,tx.payment_type_id
            FROM credesal_share_native_event_map em
            LEFT JOIN m_share_account_transactions tx ON tx.id=em.share_transaction_id
            WHERE em.source_system=%s AND em.source_key=ANY(%s)
        """, (SOURCE_SYSTEM, event_keys)).fetchall() if event_keys else []
        certificate_rows = conn.execute("""
            SELECT source_key,source_hash,client_id,share_account_id,paid_shares,subscribed_shares
            FROM credesal_share_certificate WHERE source_system=%s AND source_key=ANY(%s)
        """, (SOURCE_SYSTEM, certificate_keys)).fetchall() if certificate_keys else []
        journal_rows = conn.execute("""
            SELECT em.source_key,ga.gl_code,je.type_enum,je.amount
            FROM credesal_share_native_event_map em
            JOIN acc_gl_journal_entry je ON je.share_transaction_id=em.share_transaction_id AND je.reversed=false
            JOIN acc_gl_account ga ON ga.id=je.account_id
            WHERE em.source_system=%s AND em.source_key=ANY(%s)
            ORDER BY em.source_key,je.id
        """, (SOURCE_SYSTEM, event_keys)).fetchall() if event_keys else []

    accounts = {str(row[1]): {
        "id": int(row[0]), "client_id": int(row[2]), "product_id": int(row[3]),
        "product_external_id": str(row[4]), "savings_account_id": int(row[5]),
        "status": int(row[6]), "approved_shares": int(row[7] or 0), "currency": str(row[8]),
    } for row in account_rows}
    event_maps = {str(row[0]): {
        "source_hash": str(row[1]), "contract_hash": str(row[2]), "client_id": int(row[3]),
        "product_id": int(row[4]), "account_id": int(row[5]),
        "transaction_id": int(row[6]) if row[6] is not None else None, "event_status": str(row[7]),
        "event_date": _date_string(row[8]), "shares": int(row[9]), "unit_price": format(_decimal(row[10]), "f"),
        "amount": format(_decimal(row[11]), "f"), "tx_date": _date_string(row[12]) if row[12] else None,
        "tx_shares": int(row[13]) if row[13] is not None else None,
        "tx_unit_price": format(_decimal(row[14]), "f") if row[14] is not None else None,
        "tx_amount": format(_decimal(row[15]), "f") if row[15] is not None else None,
        "tx_status": int(row[16]) if row[16] is not None else None,
        "tx_type": int(row[17]) if row[17] is not None else None,
        "payment_type_id": int(row[18]) if row[18] is not None else None,
    } for row in event_rows}
    certificates = {str(row[0]): {
        "source_hash": str(row[1]), "client_id": int(row[2]), "account_id": int(row[3]),
        "paid_shares": int(_decimal(row[4])), "subscribed_shares": int(_decimal(row[5])),
    } for row in certificate_rows}
    journals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source_key, gl_code, type_enum, amount in journal_rows:
        journals[str(source_key)].append({
            "gl_code": str(gl_code), "type": int(type_enum), "amount": _decimal(amount),
        })

    resources = _product_resources(settings, contract)
    payment_gl = {
        int(item["source_payment_type_id"]): item["gl_code"]
        for item in contract.raw["accounting_strategy"]["payment_channel_mappings"]
    }
    equity_gl = {
        share_type: contract.raw["accounting_candidates"][item["code"]]["shareEquityId"]["gl_code"]
        for share_type, item in contract.raw["share_classes"].items()
    }
    reference_gl = contract.raw["accounting_candidates"]["shared"]["shareReferenceId"]["gl_code"]
    suspense_gl = contract.raw["accounting_candidates"]["shared"]["shareSuspenseId"]["gl_code"]
    mismatches: list[dict[str, Any]] = []
    matched_keys: list[str] = []
    counts = Counter()
    for key in keys:
        record = records.get(key)
        action = actions.get(key)
        reasons: list[str] = []
        if record is None or action is None:
            reasons.append("source_or_plan_missing")
        else:
            account = accounts.get(record["account_external_id"])
            if account is None:
                reasons.append("share_account_missing")
            else:
                if account["client_id"] != action["client_id"]:
                    reasons.append("client_mismatch")
                if account["product_external_id"] != action["product_external_id"]:
                    reasons.append("product_mismatch")
                if account["savings_account_id"] != action["savings_account_id"]:
                    reasons.append("savings_account_mismatch")
                if account["status"] != 300:
                    reasons.append("share_account_not_active")
                if account["approved_shares"] != record["paid_shares"]:
                    reasons.append("approved_share_total_mismatch")
                if account["currency"] != contract.raw["target"]["currency"]:
                    reasons.append("currency_mismatch")
                for event in record["events"]:
                    mapped = event_maps.get(event["source_key"])
                    if mapped is None:
                        reasons.append(f"event_map_missing:{event['source_key']}")
                        continue
                    expected_payment = resources["paymentTypeIds"][event["source_payment_type_id"]]
                    if mapped["source_hash"] != event["source_hash"] or mapped["contract_hash"] != contract.contract_hash:
                        reasons.append(f"event_hash_mismatch:{event['source_key']}")
                    if mapped["account_id"] != account["id"] or mapped["event_status"] not in {"APPLIED", "RECONCILED"}:
                        reasons.append(f"event_identity_mismatch:{event['source_key']}")
                    if (mapped["event_date"] != event["event_date"] or mapped["shares"] != event["shares"]
                            or _decimal(mapped["unit_price"]) != _decimal(event["unit_price"])
                            or _decimal(mapped["amount"]) != _decimal(event["amount"])):
                        reasons.append(f"event_value_mismatch:{event['source_key']}")
                    if (mapped["tx_date"] != event["event_date"] or mapped["tx_shares"] != event["shares"]
                            or _decimal(mapped["tx_unit_price"]) != _decimal(event["unit_price"])
                            or _decimal(mapped["tx_amount"]) != _decimal(event["amount"])
                            or mapped["tx_status"] != 300 or mapped["tx_type"] != 500
                            or mapped["payment_type_id"] != expected_payment):
                        reasons.append(f"native_transaction_mismatch:{event['source_key']}")
                    entries = journals.get(event["source_key"], [])
                    signed = sum((entry["amount"] if entry["type"] == 2 else -entry["amount"] for entry in entries), Decimal("0"))
                    debits = Counter()
                    credits = Counter()
                    for entry in entries:
                        (debits if entry["type"] == 2 else credits)[entry["gl_code"]] += entry["amount"]
                    expected_amount = _decimal(event["amount"])
                    if signed != 0 or debits[payment_gl[event["source_payment_type_id"]]] != expected_amount:
                        reasons.append(f"journal_debit_or_balance_mismatch:{event['source_key']}")
                    if credits[equity_gl[record["share_type"]]] != expected_amount:
                        reasons.append(f"journal_equity_mismatch:{event['source_key']}")
                    if debits[suspense_gl] != credits[suspense_gl] or debits[reference_gl] != credits[reference_gl]:
                        reasons.append(f"journal_control_balance_mismatch:{event['source_key']}")
                for certificate in record["certificates"]:
                    projected = certificates.get(certificate["source_key"])
                    if projected is None:
                        reasons.append(f"certificate_missing:{certificate['source_key']}")
                    elif (projected["source_hash"] != certificate["source_hash"]
                          or projected["account_id"] != account["id"]
                          or projected["paid_shares"] != int(_decimal(certificate["paid_shares"]))
                          or projected["subscribed_shares"] != int(_decimal(certificate["subscribed_shares"]))):
                        reasons.append(f"certificate_mismatch:{certificate['source_key']}")
        if reasons:
            counts["mismatch"] += 1
            mismatches.append({"source_key": key, "reasons": reasons[:30]})
        else:
            counts["matched"] += 1
            matched_keys.append(key)

    if matched_keys:
        matched_event_keys = [event["source_key"] for key in matched_keys for event in records[key]["events"]]
        with _postgres_write_connection(settings.target.pg_url or "") as conn:
            conn.execute("""
                UPDATE credesal_share_native_event_map
                SET event_status='RECONCILED',reconciled_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                WHERE source_system=%s AND source_key=ANY(%s)
            """, (SOURCE_SYSTEM, matched_event_keys))
            conn.commit()
    failed = sum(item["status"] == "failed" for item in items)
    quarantined = sum(item["status"] == "quarantined" for item in items)
    return {
        "run_id": run_id, "ok": not mismatches and failed == 0, "counts": dict(counts),
        "failed": failed, "quarantined": quarantined, "failed_or_quarantined": failed + quarantined,
        "mismatches": mismatches[:100],
    }
