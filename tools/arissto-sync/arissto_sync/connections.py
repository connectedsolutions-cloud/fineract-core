from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

import requests

from .arissto import IDENTIFIER, select_rows, source_connection
from .config import TargetConfig


class FineractError(RuntimeError):
    pass


class FineractApi:
    def __init__(self, config: TargetConfig, session: requests.Session | None = None):
        self.config = config
        # One session per workflow reuses TLS handshakes and TCP connections.
        self.session = session or requests.Session()

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None,
                query: dict[str, Any] | None = None, idempotency_key: str | None = None) -> Any:
        url = f"{self.config.api_url}/{path.lstrip('/')}"
        headers = {
            "Fineract-Platform-TenantId": self.config.tenant,
            "Content-Type": "application/json", "Accept": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self.session.request(
                method, url, params=query, json=payload, headers=headers,
                auth=(self.config.api_user, self.config.api_password), timeout=30,
                verify=self.config.tls_verify,
            )
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.HTTPError as exc:
            response = exc.response
            status = response.status_code if response is not None else "unknown"
            detail = response.text[:1000] if response is not None else ""
            raise FineractError(f"Fineract API {method} {path} failed ({status}): {detail}") from exc

    def ping(self) -> dict[str, Any]:
        return self.request("GET", "offices", query={"limit": 1})

    def offices(self) -> list[dict[str, Any]]:
        value = self.request("GET", "offices")
        return value if isinstance(value, list) else value.get("pageItems", [])

    def staff(self, status: str = "ALL") -> list[dict[str, Any]]:
        value = self.request("GET", "staff", query={"status": status})
        return value if isinstance(value, list) else value.get("pageItems", [])

    def find_staff(self, external_id: str) -> dict[str, Any] | None:
        exact = [item for item in self.staff("ALL") if item.get("externalId") == external_id]
        if len(exact) > 1:
            raise FineractError(f"Duplicate Fineract staff external ID: {external_id}")
        return exact[0] if exact else None

    def create_staff(self, payload: dict[str, Any]) -> str:
        result = self.request("POST", "staff", payload)
        identifier = result.get("resourceId") or result.get("entityId") or result.get("staffId")
        if identifier is not None:
            return str(identifier)
        recovered = self.find_staff(str(payload["externalId"]))
        if not recovered:
            raise FineractError("Unable to recover created staff by external ID")
        return str(recovered["id"])

    def update_staff(self, staff_id: str, payload: dict[str, Any]) -> None:
        self.request("PUT", f"staff/{staff_id}", payload)

    def datatables(self) -> list[dict[str, Any]]:
        value = self.request("GET", "datatables", query={"apptable": "m_client"})
        return value if isinstance(value, list) else value.get("pageItems", [])

    def datatable_data(self, table: str, client_id: str) -> Any:
        try:
            result = self.request("GET", f"datatables/{table}/{client_id}", query={"genericResultSet": "true"})
            # For a missing one-to-one row, Fineract may return HTTP 200 with a
            # generic-result wrapper whose data array is empty instead of 404.
            if isinstance(result, dict) and isinstance(result.get("data"), list) and not result["data"]:
                return None
            return result
        except FineractError as exc:
            if "(404)" in str(exc):
                return None
            raise

    def create_client(self, payload: dict[str, Any]) -> str:
        result = self.request("POST", "clients", payload)
        return str(result["clientId"])

    def update_client(self, client_id: str, payload: dict[str, Any]) -> None:
        self.request("PUT", f"clients/{client_id}", payload)

    def upsert_datatable(self, table: str, client_id: str, payload: dict[str, Any]) -> None:
        existing = self.datatable_data(table, client_id)
        self.request("PUT" if existing else "POST", f"datatables/{table}/{client_id}", payload)

    def create_datatable(self, table: str, client_id: str, payload: dict[str, Any]) -> None:
        self.request("POST", f"datatables/{table}/{client_id}", payload)

    def client_identifiers(self, client_id: str) -> list[dict[str, Any]]:
        value = self.request("GET", f"clients/{client_id}/identifiers")
        return value if isinstance(value, list) else value.get("pageItems", [])

    def upsert_client_identifier(self, client_id: str, payload: dict[str, Any]) -> None:
        body = dict(payload)
        if isinstance(body.get("status"), str):
            # Fineract's update path parses this value with Enum.valueOf and
            # therefore requires the enum token even though API reads/docs use
            # the display label "Active".
            body["status"] = body["status"].upper()
        document_type_id = int(body["documentTypeId"])
        existing = [item for item in self.client_identifiers(client_id)
                    if int((item.get("documentType") or {}).get("id", -1)) == document_type_id]
        if len(existing) > 1:
            raise FineractError("Multiple active client identifiers have the same document type")
        if existing:
            self.request("PUT", f"clients/{client_id}/identifiers/{existing[0]['id']}", body)
        else:
            self.request("POST", f"clients/{client_id}/identifiers", body)

    def create_client_identifier(self, client_id: str, payload: dict[str, Any]) -> None:
        body = dict(payload)
        if isinstance(body.get("status"), str):
            body["status"] = body["status"].upper()
        self.request("POST", f"clients/{client_id}/identifiers", body)

    def client_addresses(self, client_id: str) -> list[dict[str, Any]]:
        value = self.request("GET", f"client/{client_id}/addresses")
        return value if isinstance(value, list) else value.get("pageItems", [])

    def upsert_client_address(self, client_id: str, payload: dict[str, Any]) -> None:
        address_type_id = int(payload["addressTypeId"])
        body = {key: value for key, value in payload.items() if key != "name"}
        existing = [item for item in self.client_addresses(client_id)
                    if int(item.get("addressTypeId", -1)) == address_type_id]
        if len(existing) > 1:
            raise FineractError("Multiple client addresses have the same address type")
        if existing:
            body["addressId"] = existing[0]["addressId"]
            self.request("PUT", f"client/{client_id}/addresses", body)
        else:
            self.request("POST", f"client/{client_id}/addresses", body, query={"type": address_type_id})

    def create_client_address(self, client_id: str, payload: dict[str, Any]) -> None:
        address_type_id = int(payload["addressTypeId"])
        body = {key: value for key, value in payload.items() if key != "name"}
        self.request("POST", f"client/{client_id}/addresses", body, query={"type": address_type_id})

    def deactivate_client(self, client_id: str, closure_reason_id: int, date_value: str) -> None:
        self.request("POST", f"clients/{client_id}", {
            "closureReasonId": closure_reason_id, "closureDate": date_value,
            "dateFormat": "yyyy-MM-dd", "locale": "es",
        }, query={"command": "close"})

    def activate_client(self, client_id: str, date_value: str) -> None:
        self.request("POST", f"clients/{client_id}", {
            "activationDate": date_value, "dateFormat": "yyyy-MM-dd", "locale": "en",
        }, query={"command": "activate"})

    def find_client(self, external_id: str) -> dict[str, Any] | None:
        result = self.request("GET", "clients", query={"externalId": external_id, "limit": 2})
        rows = result.get("pageItems", result if isinstance(result, list) else [])
        exact = [row for row in rows if row.get("externalId") == external_id]
        if len(exact) > 1:
            raise FineractError(f"Duplicate Fineract external ID: {external_id}")
        return exact[0] if exact else None

    def get_client(self, client_id: str) -> dict[str, Any]:
        return self.request("GET", f"clients/{client_id}")

    def calculate_loan_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calculate a native schedule without creating a loan application."""
        return self.request("POST", "loans", payload, query={"command": "calculateLoanSchedule"})

    def calculate_variable_loan_schedule(
        self, loan_id: int, payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Preview term variations on a pending application without persisting them."""
        return self.request(
            "POST", f"loans/{loan_id}/schedule", payload,
            query={"command": "calculateLoanSchedule"},
        )

    def add_loan_schedule_variations(
        self, loan_id: int, payload: dict[str, Any], idempotency_key: str,
    ) -> dict[str, Any]:
        """Persist previously validated term variations on a pending application."""
        return self.request(
            "POST", f"loans/{loan_id}/schedule", payload,
            query={"command": "addVariations"}, idempotency_key=idempotency_key,
        )

    def family_members(self, client_id: str) -> list[dict[str, Any]]:
        value = self.request("GET", f"clients/{client_id}/familymembers")
        return value if isinstance(value, list) else value.get("pageItems", [])

    def get_family_member(self, client_id: str, family_member_id: str) -> dict[str, Any]:
        return self.request("GET", f"clients/{client_id}/familymembers/{family_member_id}")

    def create_family_member(self, client_id: str, payload: dict[str, Any]) -> str:
        result = self.request("POST", f"clients/{client_id}/familymembers", payload)
        identifier = result.get("resourceId") or result.get("entityId") or result.get("subResourceId")
        if identifier is not None:
            return str(identifier)
        external_id = payload.get("externalId")
        matches = [item for item in self.family_members(client_id) if item.get("externalId") == external_id]
        if len(matches) != 1:
            raise FineractError("Unable to recover created family member by external ID")
        return str(matches[0]["id"])

    def update_family_member(self, client_id: str, family_member_id: str, payload: dict[str, Any]) -> None:
        self.request("PUT", f"clients/{client_id}/familymembers/{family_member_id}", payload)


@contextmanager
def postgres_connection(url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for PostgreSQL inspection") from exc
    with psycopg.connect(url, autocommit=False) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        yield conn
        conn.rollback()


def postgres_schema(conn: Any, tables: list[str]) -> dict[str, dict[str, str]]:
    rows = conn.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY(%s)", (tables,),
    ).fetchall()
    result: dict[str, dict[str, str]] = {table: {} for table in tables}
    for table, column, data_type in rows:
        result[table][column] = data_type
    return result
