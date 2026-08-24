from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .connections import IDENTIFIER, FineractApi, select_rows


KYC_TABLES = [
    "credesal_client_datos_personales", "credesal_client_pep", "credesal_client_trabajo",
    "credesal_client_informacion_laboral", "credesal_client_ingresos_egresos_mensuales",
    "credesal_client_remesas", "credesal_client_informacion_complementaria",
    "credesal_client_actividad_mensual",
]
CATALOG_TABLES = [
    "credesal_catalog_code_value_map", "credesal_geo_country", "credesal_geo_department",
    "credesal_geo_municipality", "credesal_economic_activity",
]
CORE_COLUMNS = {
    "externalId": "external_id", "firstname": "firstname", "middlename": "middlename",
    "lastname": "lastname", "secondlastname": "secondlastname", "marriedlastname": "marriedlastname",
    "mobileNo": "mobile_no", "dateOfBirth": "date_of_birth", "emailAddress": "email_address",
    "activationDate": "activation_date", "submittedOnDate": "submittedon_date",
    "genderId": "gender_cv_id",
}
ADDRESS_COLUMNS = {
    "addressLine1": "address_line_1", "addressLine2": "address_line_2", "addressLine3": "address_line_3",
    "townVillage": "town_village", "countyDistrict": "county_district", "stateProvinceId": "state_province_id",
    "countryId": "country_id", "postalCode": "postal_code", "isActive": "is_active", "city": "city",
}
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ClientDataIssue(RuntimeError):
    """A non-PII reason why one source client cannot be migrated safely."""


def _fold(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


@dataclass(frozen=True)
class TargetCatalogs:
    code_values: dict[tuple[str, str], tuple[int, str]]
    named_values: dict[tuple[str, str], int]
    countries: dict[str, dict[str, Any]]
    departments: dict[str, dict[str, Any]]
    municipalities: dict[str, dict[str, Any]]
    activities: dict[str, str]
    address_enabled: bool
    signature: str
    client_tags: dict[tuple[str, str], int] = field(default_factory=dict)

    @classmethod
    def from_postgres(cls, conn: Any) -> "TargetCatalogs":
        code_values = {
            (str(catalog), str(key).strip()): (int(code_id), str(label))
            for catalog, key, code_id, label in conn.execute(
                "SELECT catalog_name, source_key, code_value_id, source_label "
                "FROM credesal_catalog_code_value_map WHERE source_system = 'ARISSTO'"
            ).fetchall()
        }
        named_values = {
            (_fold(code), _fold(label)): int(identifier)
            for code, identifier, label in conn.execute(
                "SELECT c.code_name, cv.id, cv.code_value FROM m_code c "
                "JOIN m_code_value cv ON cv.code_id=c.id WHERE cv.is_active=true"
            ).fetchall()
        }
        countries = {
            str(row[0]).strip(): {"name": row[1], "iso2": row[2], "iso3": row[3], "demonym": row[4], "code_value_id": row[5]}
            for row in conn.execute(
                "SELECT arissto_country_id,name,iso2,iso3,demonym,country_cv_id FROM credesal_geo_country"
            ).fetchall()
        }
        departments = {
            str(row[0]).strip(): {"country_key": row[1], "name": row[2], "zone_code": row[3], "code_value_id": row[4]}
            for row in conn.execute(
                "SELECT arissto_department_id,arissto_country_id,name,zone_code,state_cv_id FROM credesal_geo_department"
            ).fetchall()
        }
        municipalities = {
            str(row[0]).strip(): {"department_key": row[1], "code": row[2], "name": row[3], "district": row[4],
                                  "settlement_type": row[5], "postal_code": row[6], "region_code": row[7]}
            for row in conn.execute(
                "SELECT arissto_municipality_id,arissto_department_id,municipality_code,name,district,"
                "settlement_type,postal_code,region_code FROM credesal_geo_municipality"
            ).fetchall()
        }
        activities = {
            str(identifier).strip(): str(description)
            for identifier, description in conn.execute(
                "SELECT arissto_activity_id,description FROM credesal_economic_activity WHERE active=true"
            ).fetchall()
        }
        client_tags: dict[tuple[str, str], int] = {}
        for identifier, name, tag_group in conn.execute(
            "SELECT id,name,tag_group FROM m_client_tag WHERE is_active=true"
        ).fetchall():
            key = (_fold(tag_group), _fold(name))
            if key in client_tags:
                raise RuntimeError(f"duplicate_active_client_tag:{key[0]}:{key[1]}")
            client_tags[key] = int(identifier)
        config = conn.execute("SELECT enabled FROM c_configuration WHERE name='enable-address'").fetchone()
        material = {
            "code_values": sorted((a, b, c, d) for (a, b), (c, d) in code_values.items()),
            "named_values": sorted((a, b, c) for (a, b), c in named_values.items()),
            "countries": sorted(countries.items()), "departments": sorted(departments.items()),
            "municipalities": sorted(municipalities.items()), "activities": sorted(activities.items()),
            "client_tags": sorted((group, name, identifier) for (group, name), identifier in client_tags.items()),
            "address_enabled": bool(config and config[0]),
        }
        signature = hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()
        return cls(code_values, named_values, countries, departments, municipalities, activities,
                   bool(config and config[0]), signature, client_tags)

    def named_id(self, code: str, label: str) -> int:
        value = self.named_values.get((_fold(code), _fold(label)))
        if value is None:
            raise ClientDataIssue(f"missing_target_code_value:{code}")
        return value

    def client_tag_id(self, group: str, name: str) -> int:
        value = self.client_tags.get((_fold(group), _fold(name)))
        if value is None:
            raise ClientDataIssue(f"missing_target_client_tag:{group}:{name}")
        return value

    def catalog_value(self, catalog: str, source_key: Any) -> tuple[int, str] | None:
        key = normalize(source_key, "text")
        if key is None:
            return None
        value = self.code_values.get((catalog, str(key)))
        if value is None:
            raise ClientDataIssue(f"unresolved_catalog:{catalog}")
        return value

    def reference(self, kind: str, source_key: Any) -> dict[str, Any] | None:
        key = normalize(source_key, "text")
        if key is None:
            return None
        rows = {"country": self.countries, "department": self.departments,
                "municipality": self.municipalities}.get(kind)
        if rows is None or str(key) not in rows:
            raise ClientDataIssue(f"unresolved_catalog:{kind}")
        return rows[str(key)]

    def activity(self, source_key: Any) -> str | None:
        key = normalize(source_key, "text")
        if key is None or str(key) == "0":
            return None
        value = self.activities.get(str(key))
        if value is None:
            raise ClientDataIssue("unresolved_catalog:economic_activity")
        return value


@dataclass(frozen=True)
class ClientContract:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "ClientContract":
        value = json.loads(path.read_text(encoding="utf-8"))
        for key in ("source", "core", "datatables", "status"):
            if key not in value:
                raise ValueError(f"Client mapping is missing {key!r}")
        source = value["source"]
        identifiers = [source[name] for name in ("table", "company_key", "branch_key", "party_key", "status_key")]
        identifiers.append(source.get("external_key", source["party_key"]))
        client_type = value.get("client_type_tag") or {}
        related = ((client_type.get("combined") or {}).get("when_exists") or {})
        if related:
            identifiers.append(related.get("table", ""))
            identifiers.extend((related.get("join") or {}).keys())
            identifiers.extend((related.get("join") or {}).values())
        for mapping in cls._mapping_items(value):
            identifiers.extend(cls._mapping_sources(mapping))
        if not all(IDENTIFIER.fullmatch(name) for name in identifiers):
            raise ValueError("Unsafe SQL identifier in client mapping")
        if client_type:
            if not client_type.get("group") or not client_type.get("status_map"):
                raise ValueError("client_type_tag requires group and status_map")
            combined = client_type.get("combined") or {}
            if combined and (not combined.get("base_status") or not combined.get("tag") or not related.get("join")):
                raise ValueError("client_type_tag combined rule is incomplete")
        destination_identifiers = list(value.get("datatables", {}))
        destination_identifiers += [column for columns in value.get("datatables", {}).values() for column in columns]
        destination_identifiers += list(value.get("reconcile_absent_datatables", []))
        destination_identifiers += list(value.get("identifiers", {}))
        if not all(IDENTIFIER.fullmatch(name) for name in destination_identifiers):
            raise ValueError("Unsafe destination identifier in client mapping")
        unknown_absence_tables = set(value.get("reconcile_absent_datatables", [])) - set(value.get("datatables", {}))
        if unknown_absence_tables:
            raise ValueError("Absence reconciliation references an undeclared datatable")
        valid_dispositions = {"migrate", "derived", "excluded"}
        valid_ownership = {"legacy-owned", "new-system-owned", "calculated"}
        for field in cls._mapping_items(value):
            if field.get("disposition") not in valid_dispositions:
                raise ValueError("Every client field needs a valid disposition")
            if field.get("ownership") not in valid_ownership:
                raise ValueError("Every client field needs valid ownership")
        return cls(value)

    @staticmethod
    def _mapping_items(value: dict[str, Any]) -> list[dict[str, Any]]:
        result = list(value.get("core", {}).values())
        if value.get("activation"):
            result.append(value["activation"])
        result += [field for table in value.get("datatables", {}).values() for field in table.values()]
        result += list(value.get("identifiers", {}).values())
        result += [field for address in value.get("addresses", {}).values() for field in address.get("fields", {}).values()]
        return result

    @staticmethod
    def _mapping_sources(mapping: dict[str, Any]) -> list[str]:
        values = mapping.get("sources") or ([mapping["source"]] if mapping.get("source") else [])
        return [str(value) for value in values]

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True).encode()).hexdigest()

    def fields(self) -> list[dict[str, Any]]:
        result = []
        for destination, item in self.raw["core"].items():
            result.append({**item, "destination": f"m_client.{CORE_COLUMNS.get(destination, destination)}", "kind": "core-field"})
        if self.raw.get("activation"):
            result.append({**self.raw["activation"], "destination": "m_client.activation_date", "kind": "core-field"})
        for table, columns in self.raw["datatables"].items():
            for destination, item in columns.items():
                result.append({**item, "destination": f"{table}.{destination}", "kind": "datatable-field"})
        for name, item in self.raw.get("identifiers", {}).items():
            result.append({**item, "destination": f"m_client_identifier.{name}", "kind": "identifier"})
        for name, address in self.raw.get("addresses", {}).items():
            for destination, item in address.get("fields", {}).items():
                table = "m_client_address" if destination == "isActive" else "m_address"
                result.append({**item, "destination": f"{table}.{ADDRESS_COLUMNS.get(destination, destination)}",
                               "address": name, "kind": "address-field"})
        return result

    def source_columns(self) -> list[str]:
        source = self.raw["source"]
        columns = [source[name] for name in ("company_key", "branch_key", "party_key", "status_key")]
        columns.append(source.get("external_key", source["party_key"]))
        for item in self._mapping_items(self.raw):
            if item.get("disposition") in {"migrate", "derived"}:
                columns.extend(self._mapping_sources(item))
        return list(dict.fromkeys(columns))

    def query(self, key: str | None = None) -> tuple[str, tuple[Any, ...]]:
        source = self.raw["source"]
        cols = [f"[src].[{name}]" for name in self.source_columns()]
        client_type = self.raw.get("client_type_tag") or {}
        related = ((client_type.get("combined") or {}).get("when_exists") or {})
        if related:
            joins = " AND ".join(
                f"[related].[{related_column}] = [src].[{source_column}]"
                for related_column, source_column in related["join"].items()
            )
            cols.append(
                f"CASE WHEN EXISTS (SELECT 1 FROM [dbo].[{related['table']}] AS [related] "
                f"WHERE {joins}) THEN 1 ELSE 0 END AS [__client_type_related_exists]"
            )
        for name, item in self.raw.get("identifiers", {}).items():
            if item.get("source_unique") and item.get("source"):
                column = item["source"]
                cols.append(
                    f"(SELECT COUNT(*) FROM [dbo].[{source['table']}] AS [dup] "
                    f"WHERE NULLIF(LTRIM(RTRIM([dup].[{column}])), '') = "
                    f"NULLIF(LTRIM(RTRIM([src].[{column}])), '')) AS [__duplicate_{name}]"
                )
        sql = f"SELECT {', '.join(cols)} FROM [dbo].[{source['table']}] AS [src]"
        if key is None:
            return sql, ()
        source_key = str(key).strip()
        if not source_key or ":" in source_key:
            raise ValueError("Invalid source key; use the exact affiliation number")
        sql += f" WHERE [src].[{source.get('external_key', source['party_key'])}] = ?"
        return sql, (source_key,)

    def source_key(self, row: dict[str, Any]) -> str:
        source = self.raw["source"]
        key = normalize(row.get(source.get("external_key", source["party_key"])), "text")
        if key is None:
            raise ClientDataIssue("missing_required:externalId")
        return str(key)

    def legacy_source_key(self, row: dict[str, Any]) -> str:
        source = self.raw["source"]
        return ":".join(str(row[source[name]]).strip() for name in ("company_key", "branch_key", "party_key"))

    def external_id(self, row: dict[str, Any]) -> str:
        return self.source_key(row)

    def legacy_external_id(self, row: dict[str, Any]) -> str:
        return "arissto:afi_socio:" + self.legacy_source_key(row)

    def payload(self, row: dict[str, Any], catalogs: TargetCatalogs | None = None) -> dict[str, Any]:
        core: dict[str, Any] = {"externalId": self.external_id(row), "locale": "es", "dateFormat": "yyyy-MM-dd"}
        for destination, item in self.raw["core"].items():
            if item.get("disposition") in {"migrate", "derived"} and item.get("ownership") == "legacy-owned":
                value = resolve_value(item, row, catalogs)
                if item.get("required") and value is None:
                    raise ClientDataIssue(f"missing_required:{destination}")
                core[destination] = value

        if self.import_active:
            activation = self.raw.get("activation") or {}
            activation_date = normalize(row.get(activation.get("source")), "date")
            if activation_date is None:
                raise ClientDataIssue("missing_required:activationDate")
            source = self.raw["source"]
            branch = str(row[source["branch_key"]]).strip()
            activation_floor = (self.raw.get("activation_floor_by_branch") or {}).get(branch)
            if activation_floor and activation_date < activation_floor:
                activation_date = activation_floor
            core["activationDate"] = activation_date
            # Fineract requires submittedOnDate <= activationDate. Use the same
            # approved record-creation date for a deterministic import timeline.
            core["submittedOnDate"] = activation_date

        client_type_tag = None
        if self.raw.get("client_type_tag"):
            if catalogs is None:
                raise ClientDataIssue("target_catalogs_not_loaded")
            tag_name = self.client_type_tag_name(row)
            tag_group = self.raw["client_type_tag"]["group"]
            tag_id = catalogs.client_tag_id(tag_group, tag_name)
            core["tagIds"] = [tag_id]
            client_type_tag = {"group": tag_group, "name": tag_name, "id": tag_id}

        datatables: dict[str, dict[str, Any]] = {}
        for table, columns in self.raw["datatables"].items():
            values = {destination: resolve_value(item, row, catalogs) for destination, item in columns.items()
                      if item.get("disposition") in {"migrate", "derived"} and item.get("ownership") == "legacy-owned"}
            if any(value is not None for value in values.values()):
                datatables[table] = values
        absent_datatables = [table for table in self.raw.get("reconcile_absent_datatables", [])
                             if table not in datatables]

        identifiers = []
        for name, item in self.raw.get("identifiers", {}).items():
            if item.get("disposition") not in {"migrate", "derived"}:
                continue
            document_key = resolve_value(item, row, catalogs)
            if document_key is None:
                continue
            if item.get("source_unique") and int(row.get(f"__duplicate_{name}") or 0) > 1:
                raise ClientDataIssue(f"duplicate_source_identifier:{name}")
            if catalogs is None:
                raise ClientDataIssue("target_catalogs_not_loaded")
            identifiers.append({"name": name, "documentTypeId": catalogs.named_id("Customer Identifier", item["document_type"]),
                                "documentKey": document_key, "description": "Migrated from Arissto", "status": "Active"})

        addresses = []
        for name, address in self.raw.get("addresses", {}).items():
            values = {destination: resolve_value(item, row, catalogs) for destination, item in address.get("fields", {}).items()
                      if item.get("disposition") in {"migrate", "derived"}}
            if not any(value is not None for key, value in values.items() if key != "isActive"):
                continue
            if catalogs is None:
                raise ClientDataIssue("target_catalogs_not_loaded")
            values.update({"name": name, "addressTypeId": catalogs.named_id("ADDRESS_TYPE", address["address_type"])})
            addresses.append(values)
        return {"core": core, "datatables": datatables, "absent_datatables": absent_datatables,
                "identifiers": identifiers, "addresses": addresses, "client_type_tag": client_type_tag}

    def client_type_tag_name(self, row: dict[str, Any]) -> str:
        config = self.raw.get("client_type_tag") or {}
        source_status = str(row[self.raw["source"]["status_key"]]).strip()
        name = (config.get("status_map") or {}).get(source_status)
        if not name:
            raise ClientDataIssue(f"unmapped_client_type_status:{source_status}")
        combined = config.get("combined") or {}
        if source_status == str(combined.get("base_status")) and bool(row.get("__client_type_related_exists")):
            name = combined["tag"]
        return str(name)

    def required_client_tags(self) -> list[tuple[str, str]]:
        config = self.raw.get("client_type_tag") or {}
        if not config:
            return []
        names = list((config.get("status_map") or {}).values())
        combined = config.get("combined") or {}
        if combined.get("tag"):
            names.append(combined["tag"])
        return [(str(config["group"]), str(name)) for name in dict.fromkeys(names)]

    def related_source_requirements(self) -> dict[str, list[str]]:
        related = (((self.raw.get("client_type_tag") or {}).get("combined") or {}).get("when_exists") or {})
        if not related:
            return {}
        return {str(related["table"]): [str(column) for column in related["join"].keys()]}

    def client_type_tag_matches(self, row: dict[str, Any], current: dict[str, Any], catalogs: TargetCatalogs) -> bool:
        config = self.raw.get("client_type_tag") or {}
        if not config:
            return True
        desired_id = catalogs.client_tag_id(config["group"], self.client_type_tag_name(row))
        current_ids = {
            int(tag["id"]) for tag in (current.get("tags") or [])
            if _fold(tag.get("tagGroup", "")) == _fold(config["group"])
        }
        return current_ids == {desired_id}

    def hash_row(self, row: dict[str, Any], catalogs: TargetCatalogs | None = None) -> str:
        return hashlib.sha256(json.dumps(self.payload(row, catalogs), sort_keys=True, default=str).encode()).hexdigest()

    def status_action(self, row: dict[str, Any]) -> str | None:
        value = str(row[self.raw["source"]["status_key"]]).strip()
        return self.raw["status"].get(value)

    def create_values(self, row: dict[str, Any]) -> dict[str, Any]:
        values = dict(self.raw.get("create_defaults") or {})
        source = self.raw["source"]
        branch = str(row[source["branch_key"]]).strip()
        office_id = self.raw.get("office_mapping", {}).get(branch)
        if not office_id:
            raise RuntimeError("source_branch_not_mapped")
        values["officeId"] = int(office_id)
        if values.get("active"):
            values.update({"dateFormat": "yyyy-MM-dd", "locale": "en"})
        return values

    @property
    def import_active(self) -> bool:
        return bool((self.raw.get("create_defaults") or {}).get("active"))

    def catalog_sources(self) -> list[tuple[str, str, str]]:
        result = []
        for item in self._mapping_items(self.raw):
            kind = item.get("type")
            source = item.get("source")
            if not source:
                continue
            if kind == "catalog-label": result.append((source, "code", item["catalog"]))
            elif kind in {"country-name", "country-demonym"}: result.append((source, "country", "country"))
            elif kind == "department-name": result.append((source, "department", "department"))
            elif kind in {"municipality-name", "municipality-field"}: result.append((source, "municipality", "municipality"))
            elif kind == "economic-activity": result.append((source, "activity", "economic_activity"))
        return list(dict.fromkeys(result))

    def required_named_codes(self) -> list[tuple[str, str]]:
        result = []
        for item in self.raw.get("core", {}).values():
            if item.get("type") == "gender-code":
                result.extend((item.get("catalog", "Gender"), label) for label in item.get("value_map", {}).values())
        result.extend(("Customer Identifier", item["document_type"])
                      for item in self.raw.get("identifiers", {}).values()
                      if item.get("disposition") in {"migrate", "derived"})
        result.extend(("ADDRESS_TYPE", item["address_type"]) for item in self.raw.get("addresses", {}).values())
        return list(dict.fromkeys(result))


def resolve_value(item: dict[str, Any], row: dict[str, Any], catalogs: TargetCatalogs | None) -> Any:
    kind = item.get("type", "text")
    sources = ClientContract._mapping_sources(item)
    value = row.get(sources[0]) if sources else item.get("value")
    if kind == "boolean" and item.get("value_map") is not None:
        raw = normalize(value, "text")
        if raw is None:
            return None
        value_map = {str(key).casefold(): mapped for key, mapped in item["value_map"].items()}
        key = str(raw).casefold()
        if key not in value_map or not isinstance(value_map[key], bool):
            raise ClientDataIssue("invalid_boolean")
        return value_map[key]
    if kind == "gender-code":
        raw = normalize(value, "text")
        if raw is None: return None
        label = item.get("value_map", {}).get(str(raw))
        if label is None: raise ClientDataIssue("invalid_gender")
        if catalogs is None: raise ClientDataIssue("target_catalogs_not_loaded")
        return catalogs.named_id(item.get("catalog", "Gender"), label)
    if kind == "email":
        value = normalize(value, "text")
        if value is not None and not EMAIL.fullmatch(value): return None
        return value
    if kind == "coalesce":
        for source in sources:
            candidate = normalize(row.get(source), item.get("value_type", "text"))
            if candidate is not None: return candidate
        return None
    if kind == "selected-document-type":
        for source, label in zip(sources, item["labels"]):
            if normalize(row.get(source), "text") is not None: return label
        return None
    if kind == "selected-document-number":
        for source in sources:
            candidate = normalize(row.get(source), "text")
            if candidate is not None: return candidate
        return None
    if kind == "dui-expiration":
        return normalize(value, "date") if normalize(row.get(item["dui_source"]), "text") is not None else None
    if catalogs is None and kind in {"catalog-label", "country-name", "country-demonym", "department-name",
                                     "municipality-name", "municipality-field", "economic-activity", "code-value-id"}:
        raise ClientDataIssue("target_catalogs_not_loaded")
    if kind == "catalog-label":
        resolved = catalogs.catalog_value(item["catalog"], value)
        return resolved[1] if resolved else None
    if kind == "code-value-id":
        resolved = catalogs.catalog_value(item["catalog"], value)
        return resolved[0] if resolved else None
    if kind in {"country-name", "country-demonym"}:
        resolved = catalogs.reference("country", value)
        if not resolved: return None
        return resolved.get("demonym") or resolved["name"] if kind == "country-demonym" else resolved["name"]
    if kind == "department-name":
        resolved = catalogs.reference("department", value)
        return resolved["name"] if resolved else None
    if kind == "municipality-name":
        resolved = catalogs.reference("municipality", value)
        return resolved["name"] if resolved else None
    if kind == "municipality-field":
        resolved = catalogs.reference("municipality", value)
        return resolved.get(item["field"]) if resolved else None
    if kind == "economic-activity": return catalogs.activity(value)
    if kind == "profession":
        direct = normalize(row.get(sources[0]), "text") if sources else None
        if direct is not None: return direct
        resolved = catalogs.catalog_value("PROFESSION", row.get(sources[1])) if catalogs and len(sources) > 1 else None
        return resolved[1] if resolved else None
    if kind == "nationality":
        direct = normalize(row.get(sources[0]), "text") if sources else None
        if direct is not None: return direct
        resolved = catalogs.reference("country", row.get(sources[1])) if catalogs and len(sources) > 1 else None
        return (resolved.get("demonym") or resolved["name"]) if resolved else None
    return normalize(value, kind)


def normalize(value: Any, kind: str) -> Any:
    if value is None: return None
    if isinstance(value, str): value = re.sub(r"\s+", " ", value.strip()) or None
    if value is None: return None
    if kind == "date" and isinstance(value, (date, datetime)): return value.strftime("%Y-%m-%d")
    if kind == "date": return str(value)
    if kind == "boolean":
        if isinstance(value, bool): return value
        folded = str(value).strip().casefold()
        if folded in {"1", "true", "si", "sí", "s", "yes"}: return True
        if folded in {"0", "false", "no", "n"}: return False
        raise ClientDataIssue("invalid_boolean")
    if kind == "integer": return int(value)
    if kind in {"decimal", "number"}:
        return float(value) if isinstance(value, Decimal) else value
    return value


def extract_clients(conn: Any, contract: ClientContract, key: str | None = None) -> list[dict[str, Any]]:
    sql, params = contract.query(key)
    return select_rows(conn, sql, params)


def classify(api: FineractApi, contract: ClientContract, row: dict[str, Any]) -> tuple[str, str | None]:
    current = api.find_client(contract.external_id(row))
    if current is None: return "create", None
    return "update", str(current["id"])
