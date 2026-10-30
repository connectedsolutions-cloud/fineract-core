"""Sanitized financial regression for the October 2499 revision chain.

Only technical IDs, dates and monetary components from the reviewed evidence;
no borrower data. These are offline planner/writer tests, not a target sync.
"""
import copy
import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from arissto_sync.loans import (
    _build_loan_lifecycle_action, _source_exact_installments,
    _source_exact_expected_schedule, _ensure_source_exact_initial_manual_schedule,
    _validate_compatibility_projection, _apply_loan_lifecycle,
)
from tests import test_loans as fixtures

ARCHIVES = {212: [('1', '2026-08-29', '5.18', '1.18'),
       ('2', '2026-08-30', '5.22', '1.14'),
       ('3', '2026-08-31', '5.25', '1.11'),
       ('4', '2026-09-01', '5.29', '1.07'),
       ('5', '2026-09-02', '5.33', '1.03'),
       ('6', '2026-09-03', '5.36', '1.00'),
       ('7', '2026-09-04', '5.40', '0.96'),
       ('8', '2026-09-05', '5.44', '0.92'),
       ('9', '2026-09-06', '5.47', '0.89'),
       ('10', '2026-09-07', '5.51', '0.85'),
       ('11', '2026-09-08', '5.55', '0.81'),
       ('12', '2026-09-09', '5.59', '0.77'),
       ('13', '2026-09-10', '5.62', '0.74'),
       ('14', '2026-09-11', '5.66', '0.70'),
       ('15', '2026-09-12', '5.70', '0.66'),
       ('16', '2026-09-13', '5.74', '0.62'),
       ('17', '2026-09-14', '5.78', '0.58'),
       ('18', '2026-09-15', '5.82', '0.54'),
       ('19', '2026-09-16', '5.86', '0.50'),
       ('20', '2026-09-17', '5.90', '0.46'),
       ('21', '2026-09-18', '5.94', '0.42'),
       ('22', '2026-09-19', '5.98', '0.38'),
       ('23', '2026-09-20', '6.02', '0.34'),
       ('24', '2026-09-21', '6.06', '0.30'),
       ('25', '2026-09-22', '6.10', '0.26'),
       ('26', '2026-09-23', '6.15', '0.21'),
       ('27', '2026-09-24', '6.19', '0.17'),
       ('28', '2026-09-25', '6.23', '0.13'),
       ('29', '2026-09-26', '6.27', '0.09'),
       ('30', '2026-09-27', '6.39', '0.04')],
 213: [('1', '2026-09-29', '3.58', '0.81'),
       ('2', '2026-09-30', '3.60', '0.79'),
       ('3', '2026-10-01', '3.63', '0.76'),
       ('4', '2026-10-02', '3.65', '0.74'),
       ('5', '2026-10-03', '3.68', '0.71'),
       ('6', '2026-10-04', '3.70', '0.69'),
       ('7', '2026-10-05', '3.73', '0.66'),
       ('8', '2026-10-06', '3.75', '0.64'),
       ('9', '2026-10-07', '3.78', '0.61'),
       ('10', '2026-10-08', '3.80', '0.59'),
       ('11', '2026-10-09', '3.83', '0.56'),
       ('12', '2026-10-10', '3.86', '0.53'),
       ('13', '2026-10-11', '3.88', '0.51'),
       ('14', '2026-10-12', '3.91', '0.48'),
       ('15', '2026-10-13', '3.94', '0.45'),
       ('16', '2026-10-14', '3.96', '0.43'),
       ('17', '2026-10-15', '3.99', '0.40'),
       ('18', '2026-10-16', '4.02', '0.37'),
       ('19', '2026-10-17', '4.04', '0.35'),
       ('20', '2026-10-18', '4.07', '0.32'),
       ('21', '2026-10-19', '4.10', '0.29'),
       ('22', '2026-10-20', '4.13', '0.26'),
       ('23', '2026-10-21', '4.16', '0.23'),
       ('24', '2026-10-22', '4.19', '0.20'),
       ('25', '2026-10-23', '4.21', '0.18'),
       ('26', '2026-10-24', '4.24', '0.15'),
       ('27', '2026-10-25', '4.27', '0.12'),
       ('28', '2026-10-26', '4.30', '0.09'),
       ('29', '2026-10-27', '4.33', '0.06'),
       ('30', '2026-09-27', '4.36', '-0.90')],
 276: [('1', '2026-09-29', '3.58', '0.81'),
       ('2', '2026-09-30', '3.60', '0.79'),
       ('3', '2026-10-01', '3.63', '0.76'),
       ('4', '2026-10-02', '3.65', '0.74'),
       ('5', '2026-10-03', '3.68', '0.71'),
       ('6', '2026-10-04', '3.70', '0.69'),
       ('7', '2026-10-05', '3.73', '0.66'),
       ('8', '2026-10-06', '3.75', '0.64'),
       ('9', '2026-10-07', '3.78', '0.61'),
       ('10', '2026-10-08', '3.80', '0.59'),
       ('11', '2026-10-09', '3.83', '0.56'),
       ('12', '2026-10-10', '3.86', '0.53'),
       ('13', '2026-10-11', '3.88', '0.51'),
       ('14', '2026-10-12', '3.91', '0.48'),
       ('15', '2026-10-13', '3.94', '0.45'),
       ('16', '2026-10-14', '3.96', '0.43'),
       ('17', '2026-10-15', '3.99', '0.40'),
       ('18', '2026-10-16', '4.02', '0.37'),
       ('19', '2026-10-17', '4.04', '0.35'),
       ('20', '2026-10-18', '4.07', '0.32'),
       ('21', '2026-10-19', '4.10', '0.29'),
       ('22', '2026-10-20', '4.13', '0.26'),
       ('23', '2026-10-21', '4.16', '0.23'),
       ('24', '2026-10-22', '4.19', '0.20'),
       ('25', '2026-10-23', '4.21', '0.18'),
       ('26', '2026-10-24', '4.24', '0.15'),
       ('27', '2026-10-25', '4.27', '0.12'),
       ('28', '2026-10-26', '4.30', '0.09'),
       ('29', '2026-10-27', '4.33', '0.06'),
       ('30', '2026-10-28', '4.36', '0.03')]}
CURRENT = [('1', '2026-10-29', '6.23', '0.67'),
 ('2', '2026-10-30', '6.27', '0.63'),
 ('3', '2026-10-31', '6.31', '0.59'),
 ('4', '2026-11-01', '6.36', '0.54'),
 ('5', '2026-11-02', '6.40', '0.50'),
 ('6', '2026-11-03', '6.44', '0.46'),
 ('7', '2026-11-04', '6.49', '0.41'),
 ('8', '2026-11-05', '6.53', '0.37'),
 ('9', '2026-11-06', '6.58', '0.32'),
 ('10', '2026-11-07', '6.62', '0.28'),
 ('11', '2026-11-08', '6.67', '0.23'),
 ('12', '2026-11-09', '6.71', '0.19'),
 ('13', '2026-11-10', '6.76', '0.14'),
 ('14', '2026-11-11', '6.81', '0.09'),
 ('15', '2026-11-12', '6.91', '0.05')]
PAYMENTS = [('2026-08-28', '28933', '0.29', '0.29', '0.00', '0.00'),
 ('2026-08-29', '29077', '7.00', '5.82', '1.18', '0.00'),
 ('2026-08-31', '29283', '7.00', '4.73', '2.27', '0.00'),
 ('2026-09-02', '29492', '7.00', '4.79', '2.21', '0.00'),
 ('2026-09-05', '29802', '7.00', '3.79', '3.21', '0.00'),
 ('2026-09-07', '29925', '7.00', '4.91', '2.09', '0.00'),
 ('2026-09-10', '30192', '7.00', '3.97', '3.03', '0.00'),
 ('2026-09-12', '30450', '7.00', '5.03', '1.97', '0.00'),
 ('2026-09-16', '30686', '5.00', '1.14', '3.80', '0.06'),
 ('2026-09-19', '30952', '7.00', '4.17', '2.83', '0.00'),
 ('2026-09-22', '31167', '7.00', '4.26', '2.74', '0.00'),
 ('2026-09-24', '31446', '7.00', '5.11', '1.77', '0.12'),
 ('2026-09-26', '31604', '7.00', '5.30', '1.70', '0.00'),
 ('2026-09-30', '32019', '5.00', '3.37', '1.63', '0.00'),
 ('2026-10-03', '32281', '7.00', '4.63', '2.37', '0.00'),
 ('2026-10-08', '32761', '5.00', '1.21', '3.79', '0.00'),
 ('2026-10-10', '32944', '5.00', '3.50', '1.50', '0.00'),
 ('2026-10-13', '33180', '5.00', '2.81', '2.18', '0.01'),
 ('2026-10-20', '33757', '5.00', '0.05', '4.95', '0.00'),
 ('2026-10-22', '33944', '5.00', '3.59', '1.41', '0.00'),
 ('2026-10-27', '34364', '5.00', '1.44', '3.41', '0.15'),
 ('2026-10-29', '34586', '5.00', '4.33', '0.67', '0.00')]

def schedule(rows):
    return [dict(NO_CUOTA=int(number), FECHA_PAGO=due, MONTO_CAPITAL=principal,
                 MONTO_INTERES=interest, MONTO_OTROS="0.00", MONTO_APORTACION=0,
                 ID_REESTRUCTURACION=None, CUOTA_DIFERIDA=0)
            for number, due, principal, interest in rows]


class RevisionChainTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.LoanInspectionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.contract = fixture.contract
        self.loan, self.source, self.target, self.product = fixture.lifecycle_fixture()
        self.loan.update(ID_CREDITO=2499, MONTO_APROBADO="172.00", MONTO_DESEMBOLSADO="172.00",
                         NO_CUOTAS_APROBADO=30, ID_FRECUENCIA=1,
                         FECHA_OTORGAMIENTO="2026-10-28", FECHA_VENCIMIENTO="2026-11-12",
                         ULTIMO_SALDO="93.76", SALDO_INTERES="0.64", SALDO_INTERES_PENDIENTE="0.00",
                         SALDO_MORA="0.00", SALDO_SEGURO="0.00", SALDO_TOTAL="94.40")
        self.loan["_mora_cutover_snapshot"] = dict(
            source_day="2026-10-29", ID_CRD_HISTORICO_DIARIO=1, MONTO_DESEMBOLSADO="172.00",
            SALDO_PAGADO_CAPITAL="78.24", SALDO_PAGADO_INTERES="50.71", SALDO_PAGADO_SEGURO="0.00", SALDO_VENCIDO_CAPITAL="1.90",
            SALDO_INTERES="0.64", SALDO_MORA="0.00", SALDO_RECARGOS="0.00", SALDO_SEGURO="0.00")
        self.source["application"].update(FECHA_SOLICITUD="2026-08-28", FECHA_APROBADO="2026-08-28",
                                          FECHA_DESEMBOLSO="2026-08-28", NO_CUOTAS_APROBADO=30)
        disb, repay = self.source["movements"]
        disb.update(ID_CREDITO=2499, ID_MOVIMIENTO_CARTERA="28932", FECHA_OPERACION="2026-08-28",
                    MONTO="172.00", MONTO_CAPITAL="172.00", DT_CREO=datetime(2026,8,28,22,18,35,927000))
        self.source["movements"] = [disb]
        for day, mid, amount, principal, interest, mora in PAYMENTS:
            row = {**repay, "ID_CREDITO":2499, "ID_MOVIMIENTO_CARTERA":mid,
                   "FECHA_OPERACION":day, "DT_CREO":datetime.fromisoformat(day+"T22:00:00"),
                   "MONTO":amount, "MONTO_CAPITAL":principal, "MONTO_INTERES":interest,
                   "MONTO_MORA":mora, "MONTO_SEGURO":"0.00"}
            if mid == "28933": row["DT_CREO"] = datetime(2026,8,28,22,26,1,700000)
            self.source["movements"].append(row)
        self.source["charge_details"] = []
        self.source["schedule"] = schedule(CURRENT)
        self.source["schedule_adjustment_summary"] = dict(adjustment_count=3, adjustments=[
            dict(ID_REESTRUCTURACION=212, DT_CREO=datetime(2026,9,28,15,0,9,447000), MONTO_REESTRUCTURADO=None),
            dict(ID_REESTRUCTURACION=213, DT_CREO=datetime(2026,9,28,15,1,37,930000), MONTO_REESTRUCTURADO="118.69"),
            dict(ID_REESTRUCTURACION=276, DT_CREO=datetime(2026,10,28,22,28,40,760000), MONTO_REESTRUCTURADO="118.69")],
            archived_schedules={str(rid):schedule(rows) for rid, rows in ARCHIVES.items()})
        self.source["refinance_incoming"] = [dict(
            old_credit_id=2354, new_credit_id=2499, payoff_movement_id="28931", payoff_amount="171.71",
            payoff_principal="171.71", payoff_interest="0.00", payoff_fee="0.00", payoff_penalty="0.00",
            payoff_date="2026-08-28", disbursement_movement_id="28932")]

    def build(self):
        return _build_loan_lifecycle_action(self.contract, self.loan, self.source, self.target,
                                            self.product, "2026-10-30")

    def action(self):
        return dict(external_id="ARISSTO:CRD:2499", entity_source_key="2499", lifecycle=self.build()["lifecycle"])

    def assert_rejected(self):
        result = self.build()
        self.assertIn("source_exact_remaining_schedule_signature_mismatch", result["quarantine_reasons"])
        self.assertNotIn("compatibility_projection", result["lifecycle"])

    def test_full_october_chain_has_exact_projection_cash_and_metrics(self):
        result = self.build()
        self.assertEqual(result["quarantine_reasons"], [])
        lifecycle = result["lifecycle"]
        policy = lifecycle["source_exact_remaining_schedule_policy"]
        self.assertEqual((policy["bridge_principal"],policy["bridge_interest"]), ("73.91","50.04"))
        projection = lifecycle["compatibility_projection"]
        self.assertEqual((projection["approved_installment_count"],projection["current_source_installment_count"],
                          projection["native_installment_count"]),(30,15,16))
        self.assertEqual(projection["actual_refinance_date"], "2026-08-28")
        self.assertEqual(projection["current_contractual_origin_date"], "2026-10-28")
        self.assertEqual((projection["arissto_through"],projection["fineract_starts"]),("2026-10-29","2026-10-30"))
        self.assertEqual(lifecycle["application_payload"]["numberOfRepayments"],16)
        rows = _source_exact_installments(dict(lifecycle=lifecycle))
        self.assertEqual(len(rows),16)
        self.assertEqual(sum(Decimal(row["principal"]) for row in rows),Decimal("172.00"))
        self.assertEqual(rows[0]["fromDate"],"2026-08-28")
        self.assertEqual(rows[0]["dueDate"],"2026-10-28")
        self.assertEqual(rows[-1]["dueDate"],"2026-11-12")
        _validate_compatibility_projection(dict(lifecycle=lifecycle))
        proof = policy["adjustment_proof"]
        self.assertEqual([stage["remaining_principal"] for stage in proof["stages"]],["118.69","118.69","98.09"])
        self.assertEqual({warning["code"] for warning in proof["warnings"]},
                         {"stale_revision_header_amount","archived_schedule_anomaly"})
        archive = proof["source_evidence"]["summary"]["archived_schedules"]["213"][-1]
        self.assertEqual((archive["FECHA_PAGO"],archive["MONTO_INTERES"]),("2026-09-27","-0.90"))
        repayments = [event for event in lifecycle["events"] if event["role"] in {"repayment", "mobile-collection-repayment"}]
        self.assertEqual(len(repayments),22)
        self.assertEqual(len({event["external_id"] for event in repayments}),22)
        self.assertEqual(sum(Decimal(event["amount"]) for event in repayments),Decimal("129.29"))
        self.assertEqual(sum(Decimal(event["allocation"]["penalty"]) for event in repayments),Decimal("0.34"))
        self.assertEqual(lifecycle["final_metric_alignment"]["targets"],dict(
            paidPrincipal="78.24",outstandingPrincipal="93.76",paidInterest="50.71",accruedInterest="0.64",
            duePrincipal="1.90",mora="0.00",insurancePaid="0.00",insuranceOutstanding="0.00"))

    def test_missing_tied_or_mixed_clock_payment_timestamp_is_rejected(self):
        row = self.source["movements"][-1]
        for timestamp in (None, datetime(2026,10,28,22,28,40,760000),
                          datetime.fromisoformat("2026-10-29T22:00:00+00:00")):
            with self.subTest(timestamp=timestamp):
                row["DT_CREO"] = timestamp
                self.assert_rejected()

    def test_unexplained_intermediate_principal_or_missing_archive_is_rejected(self):
        archives = self.source["schedule_adjustment_summary"]["archived_schedules"]
        archives["213"][0]["MONTO_CAPITAL"] = "3.59"
        self.assert_rejected()
        archives["213"] = schedule(ARCHIVES[213])
        del archives["276"]
        self.assert_rejected()

    def test_wrong_refinance_identity_or_amount_remains_quarantined(self):
        link = self.source["refinance_incoming"][0]
        for key,value in (("old_credit_id",2353),("payoff_amount","171.70"),("payoff_date","2026-08-29")):
            original = link[key]
            with self.subTest(key=key):
                link[key] = value
                self.assertIn("reviewed_refinance_application_date_signature_changed",self.build()["quarantine_reasons"])
                link[key] = original

    def test_original_reviewed_date_is_not_required_but_unproven_date_is(self):
        self.loan["FECHA_OTORGAMIENTO"] = "2026-10-27"
        self.assertIn("reviewed_refinance_application_date_signature_changed",self.build()["quarantine_reasons"])

    def test_evidence_drift_changes_frozen_hash_including_old_archive_interest(self):
        before = self.build()["lifecycle_hash"]
        self.source["schedule_adjustment_summary"]["archived_schedules"]["213"][-1]["MONTO_INTERES"] = "-0.89"
        self.assertNotEqual(before,self.build()["lifecycle_hash"])
        before = self.build()["lifecycle_hash"]
        self.source["movements"][-1]["DT_CREO"] = datetime(2026,10,29,22,0,0,1000)
        self.assertNotEqual(before,self.build()["lifecycle_hash"])

    def test_later_payment_is_not_subtracted_twice_and_bad_balance_is_rejected(self):
        self.source["schedule"][0]["MONTO_CAPITAL"] = "1.90"
        self.assert_rejected()
        self.source["schedule"] = schedule(CURRENT)
        self.loan["ULTIMO_SALDO"] = "93.75"
        self.assert_rejected()

    def test_projection_drift_is_rejected_before_any_target_access(self):
        action = self.action()
        action["lifecycle"]["schedule"][0]["principal"] = "6.22"
        api = MagicMock()
        with self.assertRaisesRegex(RuntimeError,"projection_contract_changed"):
            _apply_loan_lifecycle(api,action,90)
        self.assertEqual(api.mock_calls,[])

    def test_writer_installs_16_rows_then_retries_without_replacing_progressed_schedule(self):
        action = self.action()
        expected = _source_exact_expected_schedule(action["lifecycle"])
        rows = _source_exact_installments(action)
        periods = [dict(period=row["installmentNumber"],fromDate=row["fromDate"],dueDate=row["dueDate"],
                        principalOriginalDue=row["principal"],interestOriginalDue=row["interest"]) for row in rows]
        current = dict(id=77,status=dict(id=300),transactions=[dict(type=dict(id=1))],
                       repaymentSchedule=dict(periods=[dict(period=1,fromDate="2026-08-28",dueDate="2026-11-12",principalDue="172.00",interestDue="0.00")]))
        installed = {**current,"repaymentSchedule":dict(periods=periods)}
        api = MagicMock()
        with patch("arissto_sync.loans._find_loan",return_value=installed):
            self.assertEqual(_ensure_source_exact_initial_manual_schedule(api,current,action,None),installed)
        self.assertEqual(api.request.call_args.kwargs["query"],dict(command="sourceExactResyncSchedule"))
        self.assertEqual(len(api.request.call_args.args[2]["installments"]),16)
        self.assertEqual(api.request.call_args.args[2]["expectedNonDisbursementTransactionCount"],0)
        api.reset_mock()
        for paid_count in (0,1,11,22):
            progressed = {**installed,"transactions":current["transactions"]+[dict(type=dict(id=2))]*paid_count}
            self.assertEqual(_ensure_source_exact_initial_manual_schedule(api,progressed,action,None),progressed)
        api.request.assert_not_called()
        with self.assertRaisesRegex(RuntimeError,"servicing_already_started"):
            _ensure_source_exact_initial_manual_schedule(api,{**current,"transactions":[dict(type=dict(id=1)),dict(type=dict(id=2))]},action,None)
        api.request.assert_not_called()

    def test_current_negative_or_retrograde_schedule_is_not_projected(self):
        self.source["schedule"][-1]["MONTO_INTERES"] = "-0.01"
        self.assertNotIn("compatibility_projection",self.build()["lifecycle"])
        self.source["schedule"] = schedule(CURRENT)
        self.source["schedule"][-1]["FECHA_PAGO"] = "2026-10-29"
        self.assertNotIn("compatibility_projection",self.build()["lifecycle"])

    def test_changed_refinance_disbursement_link_is_rejected(self):
        link = self.source["refinance_incoming"][0]
        for key,value in (("new_credit_id",2498),("disbursement_movement_id","wrong"),("later_posted_payment_count",1)):
            original = link.get(key)
            with self.subTest(key=key):
                link[key] = value
                self.assertIn("reviewed_refinance_application_date_signature_changed",self.build()["quarantine_reasons"])
                if original is None: del link[key]
                else: link[key] = original

    def test_completed_aligned_2499_recovers_read_only_and_checks_all_payments(self):
        action = self.action()
        lifecycle = action["lifecycle"]
        def transaction(event, amount=None):
            allocation = event.get("allocation") or {}
            return dict(id=int(event.get("source_movement_id") or 1),externalId=event["external_id"],
                        date=event["date"],amount=amount or event["amount"],reversed=False,
                        type=dict(id=1 if event["role"] == "disbursement" else 2),
                        principalPortion=allocation.get("principal","0.00"),interestPortion=allocation.get("interest","0.00"),
                        feeChargesPortion=allocation.get("fee","0.00"),penaltyChargesPortion=allocation.get("penalty","0.00"))
        settlement = lifecycle["refinance"]["settlements"][0]
        transactions = [transaction(event,"0.29" if event["role"] == "disbursement" else None)
                        for event in lifecycle["events"]]
        transfer_id = settlement.get("transfer_external_id") or settlement["topup_transfer_external_id"]
        transactions.append(dict(id=30000,externalId=transfer_id,date="2026-08-28",amount="171.71",reversed=False,type=dict(id=1)))
        target = dict(id=77,externalId=action["external_id"],loanProductId=90,clientId=900,principal="172.00",
                      status=dict(id=300),timeline=dict(expectedDisbursementDate="2026-10-28"),
                      isInterestRecalculationEnabled=False,transactions=transactions,
                      repaymentSchedule=dict(periods=[dict(period=1,migrationBaseline=True,principalDue="93.76")]))
        predecessor = dict(id=76,externalId=settlement["predecessor_external_id"],transactions=[transaction(dict(
            role="repayment", external_id=settlement["payoff_external_id"],date="2026-08-28",amount="171.71",
            allocation=settlement["payoff_allocation"]))])
        metrics = dict(loanId=77,cutoffDate="2026-10-30",alignmentVersion=1,continuationReady=True,
                       metrics=lifecycle["final_metric_alignment"]["targets"])
        api = MagicMock()
        def request(method,path,*args,**kwargs):
            self.assertEqual(method,"GET")
            if path.endswith("/migration-metrics"): return metrics
            if "/transactions/external-id/" in path: return None
            raise AssertionError(path)
        api.request.side_effect = request
        def find(api,external_id):
            return predecessor if external_id == predecessor["externalId"] else target
        before = copy.deepcopy(target)
        with patch("arissto_sync.loans._find_loan",side_effect=find), patch("arissto_sync.loans._verify_loan_term_account_contract"):
            self.assertEqual(_apply_loan_lifecycle(api,action,90),(77,True))
            self.assertEqual(target,before)
            last_payment = next(tx for tx in transactions if tx["externalId"] == "ARISSTO:CRD-MOV:34586")
            last_payment["principalPortion"] = "4.32"
            with self.assertRaisesRegex(RuntimeError,"allocation_mismatch"):
                _apply_loan_lifecycle(api,action,90)
        self.assertTrue(all(call.args[0] == "GET" for call in api.request.call_args_list))

    def test_same_proven_chain_is_reason_based_without_a_loan_id_exception(self):
        self.loan["ID_CREDITO"] = 9001
        for movement in self.source["movements"]:
            movement["ID_CREDITO"] = 9001
        self.source["refinance_incoming"][0]["new_credit_id"] = 9001
        result = self.build()
        self.assertEqual(result["quarantine_reasons"],[])
        self.assertEqual(result["lifecycle"]["compatibility_projection"]["native_installment_count"],16)
        self.assertIsNone(result["lifecycle"]["native_creation_override"])
