"""Opening insurance cannot mix a current header with dated final metric targets."""
import unittest
from arissto_sync.loans import _build_loan_lifecycle_action
from tests import test_loans as fixtures


class InsuranceSnapshotBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LoanInspectionTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def build(self, current, dated, current_state='1', dated_state='1'):
        loan, source, target, payload = self.fixture.lifecycle_fixture()
        loan['SALDO_SEGURO'] = current; loan['source_state'] = current_state
        loan['_mora_cutover_snapshot'] = {
            'source_day':'2026-08-30','ID_ESTADO_CARTERA':dated_state,
            'SALDO_PAGADO_CAPITAL':'8.00','SALDO_PAGADO_INTERES':'1.90','SALDO_PAGADO_SEGURO':'0.10',
            'SALDO_VENCIDO_CAPITAL':'0','SALDO_MORA':'0','SALDO_RECARGOS':'0',
            'MONTO_DESEMBOLSADO':'350','SALDO_INTERES':'1.90','SALDO_SEGURO':dated,'SALDO_TOTAL':'344.00'}
        return _build_loan_lifecycle_action(self.fixture.contract, loan, source, target, payload, '2026-08-31')['lifecycle']

    def test_opening_charge_and_metric_target_use_the_same_dated_balance(self):
        for current, dated in [('0.10','0.25'), ('0','0.25')]:
            with self.subTest(current=current, dated=dated):
                lifecycle = self.build(current, dated)
                self.assertEqual(lifecycle['cutover_insurance_charge']['amount'], dated)
                self.assertEqual(lifecycle['final_metric_alignment']['targets']['insuranceOutstanding'], dated)
                self.assertIsNotNone(lifecycle['recurring_insurance_charge'])

    def test_later_header_insurance_is_not_imported_when_dated_balance_is_zero(self):
        lifecycle = self.build('0.25', '0.00')
        self.assertIsNone(lifecycle['cutover_insurance_charge'])
        self.assertEqual(lifecycle['final_metric_alignment']['targets']['insuranceOutstanding'], '0.00')

    def test_dated_status_owns_eligibility_despite_a_later_header_status(self):
        active = self.build('0.10', '0.25', current_state='3')
        self.assertEqual(active['cutover_insurance_charge']['amount'], '0.25')
        closed = self.build('0.25', '0.00', dated_state='3')
        self.assertIsNone(closed['cutover_insurance_charge'])
        self.assertIsNone(closed['final_metric_alignment'])
