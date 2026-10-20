import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from arissto_sync.carry_forward_seed_refs import _dependency_closure, _selection, isolated_url
from arissto_sync.carry_forward_seed_stage import _copy_order
from arissto_sync.carry_forward_seed_verify import _verify_retained_product_delinquency_buckets
from arissto_sync.loans import _mark_retained_seeded_loans
from arissto_sync.state import State


class CarryForwardSeedTests(unittest.TestCase):
    def test_application_level_guarantor_clients_join_seed_closure(self):
        class Source:
            def execute(self, query, params):
                self_query = str(query)
                assert "m_guarantor" in self_query
                return type("Rows", (), {"fetchall": lambda self: [(17,), (18,)]})()

        with (patch("arissto_sync.carry_forward_seed_refs._foreign_keys", return_value=[]),
              patch("arissto_sync.carry_forward_seed_refs._stage_and_source_values",
                    return_value=({"17", "18"}, {"17"}))):
            parents, blockers, references = _dependency_closure(
                Source(), object(), {"m_guarantor"}, [1], [2], {},
            )
        self.assertEqual(parents["m_client"], {18})
        self.assertEqual(blockers, [])
        self.assertEqual(references[0]["application_level"], True)

    def test_retained_loan_requires_exact_mapping_and_whole_refinance_component(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "cycle.sqlite3")
            try:
                state.initialize_cycle("carry", "local", "fingerprint", "seed-dump", "now")
                state.conn.executemany("INSERT INTO state_metadata(key,value) VALUES(?,?)", [
                    ("carry_forward_mapping_hash", "mapping-proof"),
                    ("carry_forward_retained_proof_hash", "loan-proof"),
                    ("carry_forward_stage_dump_sha256", "seed-dump"),
                    ("carry_forward_classification_hash", "classification-proof"),
                    ("carry_forward_fineract_starts", "2026-10-07"),
                    ("carry_forward_old_fineract_starts", "2026-10-06"),
                ])
                state.conn.commit()
                state.save_mapping("fingerprint", "loans", "loan:1", "101", "source-hash")
                state.save_mapping("fingerprint", "loans", "product:a", "11", "product-hash")
                product = {"entity_type": "product", "source_key": "product:a",
                           "action": "unchanged-product", "source_hash": "product-hash",
                           "target_id": 11}
                retained = {"entity_type": "loan", "source_key": "loan:1", "action": "recover-loan",
                            "source_hash": "source-hash", "target_id": 101, "depends_on": []}
                old_document = {"actions": [product, dict(retained)]}
                document = {"migration_cutover_date": "2026-10-07", "actions": [
                    product, {**retained, "source_hash": "new-boundary-hash"},
                ]}
                _mark_retained_seeded_loans(document, old_document, state, "fingerprint")
                self.assertEqual(document["actions"][1]["action"], "retained-loan")
                self.assertEqual(document["actions"][1]["seed_source_hash"], "source-hash")
                self.assertEqual(document["carry_forward_retention"]["loan_count"], 1)
                changed = {"migration_cutover_date": "2026-10-07", "actions": [
                    product, {**retained, "source_hash": "new-boundary-hash"},
                ]}
                changed_old = {"actions": [product, {**retained, "source_hash": "changed"}]}
                with self.assertRaisesRegex(ValueError, "changed after seed proof"):
                    _mark_retained_seeded_loans(changed, changed_old, state, "fingerprint")
                mixed = {"migration_cutover_date": "2026-10-07", "actions": [
                    product, {**retained, "depends_on": ["loan:2"]},
                    {**retained, "source_key": "loan:2", "target_id": 102,
                     "depends_on": ["loan:1"]},
                ]}
                with self.assertRaisesRegex(ValueError, "mixes retained and replayed"):
                    _mark_retained_seeded_loans(mixed, old_document, state, "fingerprint")
            finally:
                state.conn.close()

    def test_isolated_database_guard_rejects_registered_and_remote_targets(self):
        sandbox = "postgresql://local:secret@127.0.0.1:5432/fineract_sandbox"
        self.assertTrue(isolated_url(
            sandbox, "fineract_carry_input_20261006", "input",
        ).endswith("/fineract_carry_input_20261006"))
        with self.assertRaisesRegex(ValueError, "isolated local"):
            isolated_url(sandbox, "fineract_sandbox", "stage")
        with self.assertRaisesRegex(ValueError, "isolated local"):
            isolated_url(sandbox.replace("127.0.0.1", "db.example.com"),
                         "fineract_carry_seed_stage_20261006", "stage")
        with self.assertRaisesRegex(ValueError, "isolated local"):
            isolated_url(sandbox.replace("fineract_sandbox", "default"),
                         "fineract_carry_seed_stage_20261006", "stage")

    def test_product_and_transaction_child_selectors_bind_expected_ids(self):
        product_predicate, product_params = _selection(
            "m_product_loan_charge", [10], [4], {},
        )
        self.assertIn("product_loan_id", product_predicate.as_string())
        self.assertEqual(product_params, ([4],))
        bucket_predicate, bucket_params = _selection(
            "m_delinquency_bucket_mappings", [10], [4], {},
        )
        self.assertIn("delinquency_bucket_id", bucket_predicate.as_string())
        self.assertIn("m_product_loan", bucket_predicate.as_string())
        self.assertEqual(bucket_params, ([4],))
        transfer_predicate, transfer_params = _selection(
            "m_account_transfer_transaction", [10], [4], {},
        )
        self.assertIn("from_loan_transaction_id", transfer_predicate.as_string())
        self.assertIn("to_loan_transaction_id", transfer_predicate.as_string())
        self.assertEqual(transfer_params, ([10], [10]))

    def test_restored_seed_rejects_product_bucket_without_mappings(self):
        class Connection:
            def __init__(self, rows):
                self.rows = rows
                self.params = None

            def execute(self, query, params):
                self.params = params
                return self

            def fetchall(self):
                return self.rows

        valid = Connection([])
        _verify_retained_product_delinquency_buckets(valid, [101, 102])
        self.assertEqual(valid.params, ([101, 102],))
        missing = Connection([(4,), (7,)])
        with self.assertRaisesRegex(ValueError, "retained loan products: 4,7"):
            _verify_retained_product_delinquency_buckets(missing, [101])

    def test_copy_order_places_referenced_rows_first_and_rejects_cycle(self):
        edges = [
            ("m_loan_transaction", "loan_id", "m_loan", "id", 1),
            ("m_loan_charge_paid_by", "loan_transaction_id", "m_loan_transaction", "id", 1),
        ]
        with patch("arissto_sync.carry_forward_seed_stage._foreign_keys", return_value=edges):
            self.assertEqual(_copy_order(None, {
                "m_loan", "m_loan_transaction", "m_loan_charge_paid_by",
            }), ["m_loan", "m_loan_transaction", "m_loan_charge_paid_by"])
        cycle = [
            ("a", "x", "b", "id", 1),
            ("b", "x", "a", "id", 1),
        ]
        with patch("arissto_sync.carry_forward_seed_stage._foreign_keys", return_value=cycle):
            with self.assertRaisesRegex(ValueError, "cycle"):
                _copy_order(None, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
