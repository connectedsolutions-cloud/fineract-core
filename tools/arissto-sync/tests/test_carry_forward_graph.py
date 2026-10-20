import unittest

from arissto_sync.carry_forward_graph import audit_direct_graph, nonretained_loan_edges


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class _GraphConnection:
    def __init__(self, edges, counts):
        self.edges = edges
        self.counts = counts

    def execute(self, query, params=None):
        if params is None:
            return _Rows(self.edges)
        table = query.as_string().split('FROM "')[1].split('"')[0]
        return _Rows([(self.counts.get(table, 0),)])


class CarryForwardGraphTests(unittest.TestCase):
    def test_populated_unproved_edge_blocks_seed(self):
        edges = [('m_loan_transaction', 'fk_txn', 'loan_id', 1),
                 ('credesal_mobile_collection_item', 'fk_collection', 'loan_id', 1)]
        report = audit_direct_graph(_GraphConnection(edges, {
            'm_loan_transaction': 2, 'credesal_mobile_collection_item': 1,
        }), [12])
        self.assertEqual(report['target_eligible_loan_count'], 1)
        self.assertIn('unproved_loan_edge:credesal_mobile_collection_item.loan_id',
                      report['blockers'])
        self.assertFalse(report['ready_for_seed'])

    def test_unknown_populated_edge_and_bad_ids_fail_closed(self):
        report = audit_direct_graph(_GraphConnection(
            [('new_table', 'fk_new', 'loan_id', 1)], {'new_table': 1}), [12])
        self.assertIn('unproved_loan_edge:new_table.loan_id', report['blockers'])
        with self.assertRaisesRegex(ValueError, 'unique positive'):
            audit_direct_graph(_GraphConnection([], {}), [12, 12])

    def test_mobile_metadata_can_be_rebuilt_without_excluding_loan(self):
        edges = [('credesal_mobile_collection_item', 'fk_collection', 'loan_id', 1)]
        connection = _GraphConnection(edges, {'credesal_mobile_collection_item': 12})
        self.assertEqual(nonretained_loan_edges(connection, [12]),
                         {12: {'review_edge:credesal_mobile_collection_item'}})
        self.assertEqual(nonretained_loan_edges(
            connection, [12], rebuild_mobile_metadata=True), {})


if __name__ == '__main__':
    unittest.main()
