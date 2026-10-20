import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arissto_sync.carry_forward_classify import (
    bind_retained_proofs, classify_rows, summarize_refinance_review,
    write_private_classification,
)


def loan(key, *, predecessor=None, quarantine=False):
    return {
        'entity_type': 'loan', 'source_key': f'loan:{key}',
        'external_id': f'ARISSTO:CRD:{key}',
        'source_hash': f'source-{key}', 'lifecycle_hash': f'lifecycle-{key}',
        'quarantine_reasons': ['source_issue'] if quarantine else [],
        'lifecycle': {'refinance': {
            'settlements': [{'predecessor_source_key': predecessor}]
        } if predecessor else None},
    }


class CarryForwardClassifyTests(unittest.TestCase):
    def test_only_unchanged_closed_loan_without_unproved_edges_is_retained(self):
        accepted = {'actions': [loan(1), loan(2), loan(3), loan(4)]}
        fresh = {'actions': [loan(1), loan(2), loan(3), loan(4, quarantine=True)]}
        rows = classify_rows(accepted, fresh, ['loan:1', 'loan:2', 'loan:3', 'loan:4'],
                             {'loan:2': 'source_lifecycle_changed'},
                             {'loan:1': 101, 'loan:2': 102, 'loan:3': 103},
                             {}, {103: {'review_edge:m_loan_topup'}})
        self.assertEqual(rows['loan:1']['disposition'], 'retain-candidate')
        self.assertEqual(rows['loan:2']['disposition'], 'replay')
        self.assertEqual(rows['loan:3']['disposition'], 'retain-review')
        self.assertEqual(rows['loan:4']['disposition'], 'block')

    def test_repeated_carry_forward_preserves_mapping_proof_hash(self):
        previous = loan(1)
        previous.update(action='retained-loan', seed_source_hash='original-seed-hash')
        rows = classify_rows({'actions': [previous]}, {'actions': [loan(1)]},
                             ['loan:1'], {}, {'loan:1': 101}, {}, {})
        self.assertEqual(rows['loan:1']['source_hash'], 'source-1')
        self.assertEqual(rows['loan:1']['mapping_source_hash'], 'original-seed-hash')

    def test_refinance_component_excluded_together(self):
        accepted = {'actions': [loan(1), loan(2, predecessor=1)]}
        fresh = {'actions': [loan(1), loan(2, predecessor=1)]}
        rows = classify_rows(accepted, fresh, ['loan:1', 'loan:2'], {},
                             {'loan:1': 101, 'loan:2': 102}, {},
                             {102: {'review_edge:m_account_transfer_details'}})
        self.assertEqual(rows['loan:1']['disposition'], 'retain-review')
        self.assertIn('refinance_component_requires_review', rows['loan:1']['reasons'])

    def test_source_change_excludes_entire_refinance_component(self):
        accepted = {'actions': [loan(1), loan(2, predecessor=1)]}
        rows = classify_rows(
            accepted, accepted, ['loan:1', 'loan:2'],
            {'loan:2': 'source_lifecycle_changed'},
            {'loan:1': 101, 'loan:2': 102}, {},
            {101: {'review_edge:m_loan_topup'}},
        )
        self.assertEqual(rows['loan:1']['disposition'], 'replay')
        self.assertIn('refinance_component_excluded', rows['loan:1']['reasons'])

    def test_refinance_review_separates_transfer_links_from_mobile_links(self):
        accepted = {'actions': [loan(1), loan(2, predecessor=1),
                                loan(3), loan(4, predecessor=3)]}
        rows = classify_rows(
            accepted, accepted, ['loan:1', 'loan:2', 'loan:3', 'loan:4'], {},
            {'loan:1': 101, 'loan:2': 102, 'loan:3': 103, 'loan:4': 104}, {},
            {101: {'review_edge:m_loan_topup'},
             102: {'review_edge:m_loan_refinancing_settlement'},
             103: {'review_edge:m_loan_topup'},
             104: {'review_edge:credesal_mobile_collection_item'}},
        )
        review = summarize_refinance_review(
            accepted, accepted, ['loan:1', 'loan:2', 'loan:3', 'loan:4'], rows,
        )
        self.assertEqual(review['loans_with_only_refinance_direct_edges'], 2)
        self.assertEqual(review['loans_with_other_direct_edges'], 2)
        self.assertEqual(review['frozen_candidate_loans_in_refinance_groups'], 4)

    def test_blocked_refinance_member_blocks_entire_component(self):
        accepted = {'actions': [loan(1), loan(2, predecessor=1)]}
        fresh = {'actions': [loan(1), loan(2, predecessor=1, quarantine=True)]}
        rows = classify_rows(accepted, fresh, ['loan:1', 'loan:2'], {},
                             {'loan:1': 101}, {}, {})
        self.assertEqual(rows['loan:1']['disposition'], 'block')
        self.assertEqual(rows['loan:2']['disposition'], 'block')
        self.assertIn('refinance_component_excluded', rows['loan:1']['reasons'])

    def test_unknown_target_edge_blocks_retention(self):
        accepted = {'actions': [loan(1)]}
        rows = classify_rows(accepted, accepted, ['loan:1'], {}, {'loan:1': 101}, {},
                             {101: {'unproved_edge:unknown_table'}})
        self.assertEqual(rows['loan:1']['disposition'], 'block')

    def test_retention_proof_binds_accepted_reconciliation_and_cutoff(self):
        accepted = {'actions': [loan(1)]}
        rows = classify_rows(accepted, accepted, ['loan:1'], {}, {'loan:1': 101}, {}, {})
        binding = {
            'accepted_run_id': 'run-1', 'accepted_plan_id': 'plan-1',
            'accepted_reconciliation_hash': 'hash-1',
        }
        cutoff = {'date': '2026-10-06', 'configuration_hash': 'cutoff-1'}
        bind_retained_proofs(rows, binding, cutoff)
        first = rows['loan:1']['retention_proof_hash']
        self.assertEqual(len(first), 64)
        bind_retained_proofs(rows, {**binding, 'accepted_reconciliation_hash': 'hash-2'}, cutoff)
        self.assertNotEqual(rows['loan:1']['retention_proof_hash'], first)

    def test_private_classification_is_atomic_and_owner_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '.arissto-sync'
            root.mkdir()
            output = root / 'carry-forward' / 'classifications' / 'date.json'
            with patch('arissto_sync.carry_forward_classify.load_settings',
                       return_value=SimpleNamespace(state_path=root / 'state.sqlite3')):
                write_private_classification({'counts': {'retain-candidate': 1}}, output)
                self.assertEqual(json.loads(output.read_text())['counts']['retain-candidate'], 1)
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                self.assertEqual(output.parent.stat().st_mode & 0o777, 0o700)
                with self.assertRaisesRegex(ValueError, 'private carry-forward'):
                    write_private_classification({}, Path(directory) / 'outside.json')


if __name__ == '__main__':
    unittest.main()
