import unittest

from arissto_sync.delinquency_prerequisite import (
    BUCKETS, ensure_delinquency_buckets, ensure_standard_loan_product_bucket,
)


class FakeApi:
    def __init__(self):
        self.ranges = []
        self.buckets = []
        self.products = {}
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path))
        if method == "GET":
            if path == "loanproducts":
                return list(self.products.values())
            if path.startswith("loanproducts/"):
                return self.products[int(path.rsplit("/", 1)[1])]
            return self.ranges if path.endswith("ranges") else self.buckets
        if path.startswith("loanproducts/"):
            product = self.products[int(path.rsplit("/", 1)[1])]
            product["delinquencyBucket"] = next(
                bucket for bucket in self.buckets if bucket["id"] == payload["delinquencyBucketId"]
            )
            return {"resourceId": product["id"]}
        if method == "PUT" and path.startswith("delinquency/ranges/"):
            row = next(r for r in self.ranges if r["id"] == int(path.rsplit("/", 1)[1]))
            row.update({key: value for key, value in payload.items() if key != "locale"})
            return {"resourceId": row["id"]}
        if path.endswith("ranges"):
            if "locale" not in payload:
                raise ValueError("Fineract requires a locale for age days")
            row = {"id": len(self.ranges) + 1, **payload}
            row.pop("locale")
            self.ranges.append(row)
            return {"resourceId": row["id"]}
        row = {"id": len(self.buckets) + 1, "name": payload["name"],
               "ranges": [r for r in self.ranges if r["id"] in payload["ranges"]]}
        self.buckets.append(row)
        return {"resourceId": row["id"]}


class DelinquencyPrerequisiteTests(unittest.TestCase):
    def test_creates_reviewed_buckets_and_is_idempotent(self):
        api = FakeApi()
        result = ensure_delinquency_buckets(api)
        self.assertTrue(result["performed"])
        self.assertEqual(len(api.ranges), 15)
        self.assertEqual([b["name"] for b in api.buckets], [b[0] for b in BUCKETS])
        self.assertEqual(len(api.buckets[0]["ranges"]), 8)
        self.assertEqual(len(api.buckets[1]["ranges"]), 7)
        self.assertFalse(ensure_delinquency_buckets(api)["performed"])
        self.assertEqual(len([call for call in api.calls if call[0] == "POST"]), 17)

    def test_rejects_conflicting_range_before_writing(self):
        api = FakeApi()
        api.ranges.append({"id": 1, "classification": "A1",
                           "minimumAgeDays": 1, "maximumAgeDays": 8})
        with self.assertRaisesRegex(ValueError, "Conflicting delinquency range"):
            ensure_delinquency_buckets(api)
        self.assertFalse(any(call[0] == "POST" for call in api.calls))

    def test_upgrades_existing_reviewed_a1_to_zero_days(self):
        api = FakeApi()
        ensure_delinquency_buckets(api)
        api.ranges[0]["minimumAgeDays"] = 1
        result = ensure_delinquency_buckets(api)
        self.assertEqual(result["actions"], [{"updated_range": "A1:0-7"}])
        self.assertEqual(api.ranges[0]["minimumAgeDays"], 0)
        self.assertFalse(ensure_delinquency_buckets(api)["performed"])

    def test_rejects_legacy_a1_shared_with_unreviewed_bucket(self):
        api = FakeApi()
        ensure_delinquency_buckets(api)
        api.ranges[0]["minimumAgeDays"] = 1
        api.buckets.append({"id": 99, "name": "Other", "ranges": [api.ranges[0]]})
        with self.assertRaisesRegex(ValueError, "shared with an unreviewed bucket"):
            ensure_delinquency_buckets(api)
        self.assertFalse(any(call[0] == "PUT" for call in api.calls))

    def test_rejects_conflicting_bucket_before_writing(self):
        api = FakeApi()
        api.buckets.append({"id": 1, "name": "Mora Estandar", "ranges": []})
        with self.assertRaisesRegex(ValueError, "Conflicting delinquency bucket"):
            ensure_delinquency_buckets(api)
        self.assertFalse(any(call[0] == "POST" for call in api.calls))

    def test_links_only_reviewed_existing_products_and_rechecks_idempotently(self):
        api = FakeApi()
        ensure_delinquency_buckets(api)
        api.products = {
            10: {"id": 10, "externalId": "ARISSTO:CRD-LINE:00001", "delinquencyBucket": {"id": 99}},
            11: {"id": 11, "externalId": "ARISSTO:CRD-LINE:00010", "delinquencyBucket": {"ranges": []}},
            12: {"id": 12, "externalId": "UNRELATED", "delinquencyBucket": {"id": 99}},
        }
        result = ensure_delinquency_buckets(api, link_products=True)
        self.assertEqual(
            result["actions"],
            [{"linked_product": "ARISSTO:CRD-LINE:00001"},
             {"linked_product": "ARISSTO:CRD-LINE:00010"}],
        )
        self.assertEqual(api.products[10]["delinquencyBucket"]["name"], "Mora Estandar")
        self.assertEqual(api.products[11]["delinquencyBucket"]["name"], "Mora Estandar")
        self.assertEqual(api.products[12]["delinquencyBucket"], {"id": 99})
        self.assertFalse(ensure_delinquency_buckets(api, link_products=True)["performed"])
        self.assertEqual(len([call for call in api.calls if call[0] == "PUT"]), 2)

    def test_links_product_after_creation_even_when_bucket_is_missing(self):
        api = FakeApi()
        api.products[10] = {"id": 10, "externalId": "ARISSTO:CRD-LINE:00001"}
        self.assertTrue(ensure_standard_loan_product_bucket(api, 10, "ARISSTO:CRD-LINE:00001"))
        self.assertEqual(api.products[10]["delinquencyBucket"]["name"], "Mora Estandar")
        self.assertFalse(ensure_standard_loan_product_bucket(api, 10, "ARISSTO:CRD-LINE:00001"))

    def test_rejects_changed_product_identity_before_linking(self):
        api = FakeApi()
        ensure_delinquency_buckets(api)
        api.products[10] = {"id": 10, "externalId": "UNRELATED"}
        with self.assertRaisesRegex(ValueError, "identity changed"):
            ensure_standard_loan_product_bucket(api, 10, "ARISSTO:CRD-LINE:00001")
        self.assertFalse(any(call[0] == "PUT" for call in api.calls))


if __name__ == "__main__":
    unittest.main()
