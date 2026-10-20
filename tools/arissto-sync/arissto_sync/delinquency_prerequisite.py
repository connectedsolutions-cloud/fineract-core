"""Idempotent tenant setup for the reviewed Credesal delinquency buckets."""

from __future__ import annotations

from typing import Any

from .connections import FineractApi


# Reviewed from the local default tenant on 2026-10-07. The unassigned
# diaria-8 range is deliberately excluded: it belongs to neither bucket.
BUCKETS = (
    ("Mora Estandar", (
        ("A1", 0, 7), ("A2", 8, 30), ("B", 31, 60),
        ("C1", 61, 90), ("C2", 91, 120), ("D1", 121, 150),
        ("D2", 151, 180), ("E", 181, None),
    )),
    ("mora-diaria", (
        ("diaria-1", 1, 2), ("diaria-2", 3, 4),
        ("diaria-3", 5, 6), ("diaria-4", 7, 8),
        ("diaria-5", 9, 10), ("diaria-6", 11, 12),
        ("diaria-7", 13, 14),
    )),
)

# Only these two Arissto lines have reviewed native loan products. Housing lines
# use different source ranges above 30 days and must not inherit this bucket.
STANDARD_PRODUCT_EXTERNAL_IDS = frozenset({
    "ARISSTO:CRD-LINE:00001", "ARISSTO:CRD-LINE:00010",
})
LEGACY_A1 = ("A1", 1, 7)


def _rows(api: FineractApi, path: str) -> list[dict[str, Any]]:
    result = api.request("GET", path)
    if not isinstance(result, list):
        raise ValueError(f"Unexpected Fineract {path} response")
    return result


def _range_key(row: dict[str, Any]) -> tuple[str, int, int | None]:
    return row["classification"], row["minimumAgeDays"], row.get("maximumAgeDays")


def ensure_standard_loan_product_bucket(
    api: FineractApi, product_id: int, external_id: str, *, bucket_id: int | None = None,
) -> bool:
    """Link one reviewed Arissto product to Mora Estandar and read it back."""
    if external_id not in STANDARD_PRODUCT_EXTERNAL_IDS:
        raise ValueError(f"Unreviewed product for Mora Estandar: {external_id}")
    if bucket_id is None:
        buckets = _rows(api, "delinquency/buckets")
        matching = [row for row in buckets if row.get("name") == "Mora Estandar"]
        if len(matching) != 1 or {
            _range_key(row) for row in matching[0].get("ranges", [])
        } != set(BUCKETS[0][1]):
            ensure_delinquency_buckets(api)
            buckets = _rows(api, "delinquency/buckets")
            matching = [row for row in buckets if row.get("name") == "Mora Estandar"]
        if len(matching) != 1 or {
            _range_key(row) for row in matching[0].get("ranges", [])
        } != set(BUCKETS[0][1]):
            raise ValueError("Reviewed Mora Estandar bucket is missing or conflicting")
        bucket_id = int(matching[0]["id"])
    current = api.request("GET", f"loanproducts/{product_id}")
    if current.get("externalId") != external_id:
        raise ValueError(f"Loan product identity changed: {external_id}")
    linked_id = (current.get("delinquencyBucket") or {}).get("id")
    if linked_id == bucket_id:
        return False
    api.request("PUT", f"loanproducts/{product_id}", {"delinquencyBucketId": bucket_id})
    verified = api.request("GET", f"loanproducts/{product_id}")
    if verified.get("externalId") != external_id or (
        verified.get("delinquencyBucket") or {}
    ).get("id") != bucket_id:
        raise ValueError(f"Mora Estandar product link did not verify: {external_id}")
    return True


def ensure_delinquency_buckets(api: FineractApi, *, link_products: bool = False) -> dict[str, Any]:
    """Create reviewed buckets and upgrade the previously reviewed A1 range."""
    ranges = _rows(api, "delinquency/ranges")
    buckets = _rows(api, "delinquency/buckets")
    by_classification = {row["classification"]: row for row in ranges}
    by_name = {row["name"]: row for row in buckets}
    if len(by_classification) != len(ranges) or len(by_name) != len(buckets):
        raise ValueError("Duplicate delinquency range classification or bucket name")
    legacy_a1 = _range_key(by_classification["A1"]) == LEGACY_A1 if "A1" in by_classification else False
    # Validate all existing reviewed definitions before creating anything.
    for name, definitions in BUCKETS:
        for definition in definitions:
            existing = by_classification.get(definition[0])
            if existing and _range_key(existing) != definition and not (
                legacy_a1 and definition[0] == "A1"
            ):
                raise ValueError(f"Conflicting delinquency range: {definition[0]}")
        existing_bucket = by_name.get(name)
        if existing_bucket:
            actual = {_range_key(row) for row in existing_bucket["ranges"]}
            legacy_definitions = {LEGACY_A1 if item[0] == "A1" else item for item in definitions}
            if actual != set(definitions) and not (legacy_a1 and name == "Mora Estandar"
                                                   and actual == legacy_definitions):
                raise ValueError(f"Conflicting delinquency bucket: {name}")
    if legacy_a1 and any(
        bucket["name"] != "Mora Estandar" and any(row["classification"] == "A1" for row in bucket["ranges"])
        for bucket in buckets
    ):
        raise ValueError("Legacy A1 range is shared with an unreviewed bucket")

    actions: list[dict[str, str]] = []
    if legacy_a1:
        api.request("PUT", f"delinquency/ranges/{by_classification['A1']['id']}", {
            "classification": "A1", "minimumAgeDays": 0, "maximumAgeDays": 7, "locale": "en",
        })
        updated = [row for row in _rows(api, "delinquency/ranges") if row["classification"] == "A1"]
        if len(updated) != 1 or _range_key(updated[0]) != ("A1", 0, 7):
            raise ValueError("A1 zero-day range update did not verify")
        by_classification["A1"] = updated[0]
        actions.append({"updated_range": "A1:0-7"})
    for name, definitions in BUCKETS:
        for classification, minimum, maximum in definitions:
            if classification in by_classification:
                continue
            payload = {"classification": classification, "minimumAgeDays": minimum,
                       "locale": "en"}
            if maximum is not None:
                payload["maximumAgeDays"] = maximum
            api.request("POST", "delinquency/ranges", payload)
            current = [row for row in _rows(api, "delinquency/ranges")
                       if row["classification"] == classification]
            if len(current) != 1 or _range_key(current[0]) != (classification, minimum, maximum):
                raise ValueError(f"Delinquency range creation did not verify: {classification}")
            by_classification[classification] = current[0]
            actions.append({"created_range": classification})
        if name in by_name:
            continue
        api.request("POST", "delinquency/buckets", {
            "name": name,
            "ranges": [by_classification[item[0]]["id"] for item in definitions],
        })
        current = [row for row in _rows(api, "delinquency/buckets") if row["name"] == name]
        if len(current) != 1 or {_range_key(row) for row in current[0]["ranges"]} != set(definitions):
            raise ValueError(f"Delinquency bucket creation did not verify: {name}")
        by_name[name] = current[0]
        actions.append({"created_bucket": name})
    if link_products:
        products = _rows(api, "loanproducts")
        managed = [row for row in products if row.get("externalId") in STANDARD_PRODUCT_EXTERNAL_IDS]
        if len({row["externalId"] for row in managed}) != len(managed):
            raise ValueError("Duplicate reviewed Arissto loan product external ID")
        standard_id = int(by_name["Mora Estandar"]["id"])
        for product in managed:
            if ensure_standard_loan_product_bucket(
                api, int(product["id"]), product["externalId"], bucket_id=standard_id,
            ):
                actions.append({"linked_product": product["externalId"]})
    return {"performed": bool(actions), "actions": actions,
            "buckets": [name for name, _ in BUCKETS]}
