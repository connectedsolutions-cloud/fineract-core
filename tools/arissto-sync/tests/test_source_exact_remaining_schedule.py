import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from arissto_sync.loans import (
    _apply_loan_lifecycle,
    _build_loan_lifecycle_action,
    _ensure_source_exact_initial_manual_schedule,
    _loan_schedule_differences,
    _source_exact_expected_schedule,
    _source_exact_installments,
    _validate_existing_loan,
)
from tests import test_loans as fixtures


class SourceExactRemainingScheduleTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.LoanInspectionTests()
        fixture.setUp()
        self.fixture = fixture

    def test_recovered_loan_rejects_old_expected_disbursement_date(self):
        action = {"lifecycle": {"application_payload": {
            "clientId": 900, "principal": "350.00",
            "expectedDisbursementDate": "2023-04-29",
        }}}
        existing = {
            "loanProductId": 90, "clientId": 900, "principal": "350.00",
            "timeline": {"expectedDisbursementDate": [2023, 4, 28]},
        }
        with self.assertRaisesRegex(RuntimeError, "expected_disbursement_date"):
            _validate_existing_loan(existing, action, 90, check_expected_date=True)
        existing["timeline"]["expectedDisbursementDate"] = [2023, 4, 29]
        _validate_existing_loan(existing, action, 90, check_expected_date=True)

    def planned(self, loan_id, original, remaining, paid, source_state="1",
                first_due="2026-09-29", later=(), adjustment_count=2,
                interim_interest="0.00", archived_mismatch=False,
                archive_terminal_revision=False):
        loan, source, target, product = self.fixture.lifecycle_fixture()
        loan.update({
            "ID_CREDITO": loan_id, "MONTO_APROBADO": original,
            "MONTO_DESEMBOLSADO": original,
            "ULTIMO_SALDO": remaining if source_state == "1" else "0.00",
            "SALDO_INTERES": "0.00", "SALDO_INTERES_PENDIENTE": "0.00",
            "SALDO_SEGURO": "0.00", "SALDO_TOTAL": remaining if source_state == "1" else "0.00",
            "source_state": source_state, "FECHA_OTORGAMIENTO": "2026-09-28",
        })
        source["application"].update({"FECHA_DESEMBOLSO": "2026-08-28"})
        adjustment_at = {
            2427: datetime(2026, 9, 29, 21, 14),
            2494: datetime(2026, 10, 8, 0, 3),
            2561: datetime(2026, 10, 8, 20, 47),
        }.get(loan_id, datetime(2026, 9, 28, 15, 1))
        source["schedule_adjustment_summary"] = {
            "adjustment_count": adjustment_count,
            "last_adjustment_created_at": adjustment_at,
            "adjustments": [
                {"ID_REESTRUCTURACION": 1000 + index,
                 "DT_CREO": adjustment_at - timedelta(days=adjustment_count - index - 1),
                 "MONTO_REESTRUCTURADO": remaining}
                for index in range(adjustment_count)
            ],
        }
        left = Decimal(remaining) - Decimal("1.00")
        source["schedule"] = [
            {"NO_CUOTA": 1, "FECHA_PAGO": first_due, "MONTO_CAPITAL": "1.00",
             "MONTO_INTERES": "0.81", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
            {"NO_CUOTA": 2, "FECHA_PAGO": max(
                "2026-10-01", (datetime.fromisoformat(first_due) + timedelta(days=1)).date().isoformat(),
            ), "MONTO_CAPITAL": str(left),
             "MONTO_INTERES": "0.79", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
        ]
        archived = [dict(row) for row in source["schedule"]]
        if archived_mismatch:
            archived[0]["MONTO_INTERES"] = "99.00"
        if archive_terminal_revision:
            archived[-1]["FECHA_PAGO"] = "2026-10-31"
            archived[-1]["MONTO_INTERES"] = "1.79"
        source["schedule_adjustment_summary"]["archived_schedules"] = {
            str(1000 + adjustment_count - 1): archived,
        }
        disb = dict(source["movements"][0])
        disb.update({"ID_CREDITO": loan_id, "FECHA_OPERACION": "2026-08-28",
                     "MONTO": original, "MONTO_CAPITAL": original})
        repay = dict(source["movements"][1])
        repay.update({"ID_CREDITO": loan_id, "FECHA_OPERACION": "2026-09-26",
                      "MONTO": paid, "MONTO_CAPITAL": paid, "MONTO_INTERES": "0.00",
                      "MONTO_SEGURO": "0.00", "DT_CREO": datetime(2026, 9, 26, 17, 0)})
        source["movements"] = [disb, repay]
        if Decimal(interim_interest):
            interim = dict(repay)
            interim.update({
                "ID_MOVIMIENTO_CARTERA": "102", "FECHA_OPERACION": "2026-09-28",
                "DT_CREO": datetime(2026, 9, 28, 22, 44),
                "MONTO": interim_interest, "MONTO_CAPITAL": "0.00",
                "MONTO_INTERES": interim_interest,
            })
            source["movements"].append(interim)
        for index, (payment_date, payment_principal, payment_interest) in enumerate(
            later, 103 if Decimal(interim_interest) else 102,
        ):
            movement = dict(repay)
            movement.update({
                "ID_MOVIMIENTO_CARTERA": str(index), "FECHA_OPERACION": payment_date,
                "MONTO": str(Decimal(payment_principal) + Decimal(payment_interest)),
                "MONTO_CAPITAL": payment_principal, "MONTO_INTERES": payment_interest,
                "DT_CREO": datetime.fromisoformat(payment_date + "T22:20:00"),
            })
            source["movements"].append(movement)
        if later and source_state == "1":
            current = Decimal(remaining) - sum(Decimal(row[1]) for row in later)
            loan["ULTIMO_SALDO"] = str(current)
            loan["SALDO_TOTAL"] = str(current)
        source["charge_details"] = []
        if source_state == "3" and not later and Decimal(paid) < Decimal(original):
            final = dict(repay)
            final.update({"ID_MOVIMIENTO_CARTERA": "102", "FECHA_OPERACION": "2026-09-28",
                          "MONTO": str(Decimal(original) - Decimal(paid)),
                          "MONTO_CAPITAL": str(Decimal(original) - Decimal(paid))})
            source["movements"].append(final)
        return _build_loan_lifecycle_action(self.fixture.contract, loan, source, target, product)

    def test_selector_recognizes_remaining_principal_for_active_and_closed_loans(self):
        for loan_id, original, remaining, paid, state in (
            (2357, "433.00", "175.28", "257.72", "1"),
            (2498, "165.00", "89.90", "75.10", "3"),
            (2499, "172.00", "118.69", "53.31", "1"),
        ):
            with self.subTest(loan_id=loan_id):
                result = self.planned(loan_id, original, remaining, paid, state)
                lifecycle = result["lifecycle"]
                policy = lifecycle["source_exact_remaining_schedule_policy"]
                self.assertIsNotNone(policy)
                self.assertEqual(lifecycle["schedule_writer"], "fineract-source-exact-remaining-schedule-v1")
                self.assertEqual(policy["bridge_principal"], str(Decimal(original) - Decimal(remaining)))
                installments = _source_exact_installments({"lifecycle": lifecycle})
                self.assertEqual(sum(Decimal(row["principal"]) for row in installments), Decimal(original))
                self.assertEqual(installments[1]["principal"], "1.00")
                self.assertEqual(installments[1]["dueDate"], "2026-09-29")

    def test_selector_rejects_inconsistent_adjusted_payment_history(self):
        result = self.planned(2357, "433.00", "175.28", "250.00")
        self.assertIn(
            "source_exact_remaining_schedule_signature_mismatch",
            result["quarantine_reasons"],
        )
        self.assertIsNone(result["lifecycle"]["source_exact_remaining_schedule_policy"])

    def test_reviewed_regenerated_plans_keep_later_payments_out_of_bridge(self):
        for loan_id, original, schedule_total, historical_paid, state, first_due, later, count, interim in (
            (2357, "433.00", "175.28", "257.72", "3", "2026-09-29",
             (("2026-09-29", "175.28", "1.20"),), 2, "0.00"),
            (2427, "493.00", "438.80", "54.20", "1", "2026-09-30",
             (("2026-09-29", "10.25", "0.00"),
              ("2026-09-30", "7.31", "2.94")), 1, "25.46"),
            (2499, "172.00", "118.69", "53.31", "1", "2026-09-29",
             (("2026-09-30", "3.37", "1.63"),), 2, "0.00"),
            (2494, "272.00", "158.67", "113.33", "1", "2026-10-08",
             (("2026-10-08", "10.00", "0.00"),), 2, "0.00"),
            (2561, "325.00", "317.62", "7.38", "1", "2026-10-09",
             (("2026-10-08", "5.00", "0.00"),), 1, "0.00"),
        ):
            with self.subTest(loan_id=loan_id):
                result = self.planned(
                    loan_id, original, schedule_total, historical_paid, state,
                    first_due=first_due, later=later, adjustment_count=count,
                    interim_interest=interim,
                )
                policy = result["lifecycle"]["source_exact_remaining_schedule_policy"]
                self.assertIsNotNone(policy)
                self.assertEqual(policy["bridge_principal"], historical_paid)
                self.assertEqual(Decimal(policy["bridge_interest"]), Decimal(interim))
                self.assertNotIn("source_exact_remaining_schedule_signature_mismatch",
                                 result["quarantine_reasons"])

    def test_post_adjustment_pattern_accepts_another_loan_with_source_proof(self):
        result = self.planned(
            9999, "172.00", "118.69", "53.31", later=(("2026-09-30", "3.37", "1.63"),),
        )
        policy = result["lifecycle"]["source_exact_remaining_schedule_policy"]
        self.assertIsNotNone(policy)
        self.assertEqual(policy["adjustment_proof"]["classification"],
                         "source-adjustment-remaining-schedule")
        self.assertNotIn("source_exact_remaining_schedule_signature_mismatch",
                         result["quarantine_reasons"])

    def test_post_adjustment_pattern_rejects_changed_archived_schedule(self):
        result = self.planned(
            9999, "172.00", "118.69", "53.31",
            later=(("2026-09-30", "3.37", "1.63"),), archived_mismatch=True,
        )
        self.assertIn("source_exact_remaining_schedule_signature_mismatch",
                      result["quarantine_reasons"])

    def test_superseded_full_principal_archive_uses_dated_payment_split(self):
        loan, source, target, product = self.fixture.lifecycle_fixture()
        loan.update({
            "ID_CREDITO": 9999, "MONTO_APROBADO": "172.00",
            "MONTO_DESEMBOLSADO": "172.00", "ULTIMO_SALDO": "115.32",
            "SALDO_TOTAL": "115.32", "FECHA_OTORGAMIENTO": "2026-09-28",
        })
        source["application"]["FECHA_DESEMBOLSO"] = "2026-08-28"
        source["schedule"] = [
            {"NO_CUOTA": 1, "FECHA_PAGO": "2026-09-29", "MONTO_CAPITAL": "1.00",
             "MONTO_INTERES": "0.81", "MONTO_OTROS": 0, "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
            {"NO_CUOTA": 2, "FECHA_PAGO": "2026-10-01", "MONTO_CAPITAL": "117.69",
             "MONTO_INTERES": "0.79", "MONTO_OTROS": 0, "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
        ]
        archived = [dict(row) for row in source["schedule"]]
        archived[0].update({"FECHA_PAGO": "2026-09-01", "MONTO_CAPITAL": "54.31"})
        archived[1].update({"FECHA_PAGO": "2026-09-08"})
        source["schedule_adjustment_summary"] = {
            "adjustment_count": 1,
            "adjustments": [{"ID_REESTRUCTURACION": 77,
                             "DT_CREO": datetime(2026, 9, 28, 15),
                             "MONTO_REESTRUCTURADO": None}],
            "archived_schedules": {"77": archived},
        }
        disb, repay = (dict(row) for row in source["movements"])
        disb.update({"FECHA_OPERACION": "2026-08-28", "MONTO": "172.00",
                     "MONTO_CAPITAL": "172.00"})
        repay.update({"FECHA_OPERACION": "2026-09-26", "MONTO": "53.31",
                      "MONTO_CAPITAL": "53.31", "MONTO_INTERES": "0.00",
                      "MONTO_SEGURO": "0.00", "DT_CREO": datetime(2026, 9, 26, 17)})
        later = dict(repay)
        later.update({"ID_MOVIMIENTO_CARTERA": "102", "FECHA_OPERACION": "2026-09-30",
                      "MONTO": "3.37", "MONTO_CAPITAL": "3.37",
                      "DT_CREO": datetime(2026, 9, 30, 17)})
        source["movements"] = [disb, repay, later]
        source["charge_details"] = []
        accepted = _build_loan_lifecycle_action(
            self.fixture.contract, loan, source, target, product,
        )
        policy = accepted["lifecycle"]["source_exact_remaining_schedule_policy"]
        self.assertEqual(policy["bridge_principal"], "53.31")
        self.assertEqual(policy["adjustment_proof"]["archive_provenance"],
                         "superseded-full-principal")
        source["movements"][1]["MONTO_CAPITAL"] = "52.31"
        source["movements"][1]["MONTO"] = "52.31"
        rejected = _build_loan_lifecycle_action(
            self.fixture.contract, loan, source, target, product,
        )
        self.assertIn("source_exact_remaining_schedule_signature_mismatch",
                      rejected["quarantine_reasons"])

    def test_terminal_archive_revision_accepts_only_terminal_date_and_interest(self):
        result = self.planned(
            9999, "172.00", "118.69", "53.31",
            later=(("2026-09-30", "3.37", "1.63"),),
            archive_terminal_revision=True,
        )
        policy = result["lifecycle"]["source_exact_remaining_schedule_policy"]
        self.assertEqual(policy["adjustment_proof"]["archive_provenance"],
                         "terminal-date-interest-revision")
        changed_earlier = self.planned(
            9999, "172.00", "118.69", "53.31",
            later=(("2026-09-30", "3.37", "1.63"),), archived_mismatch=True,
            archive_terminal_revision=True,
        )
        self.assertIn("source_exact_remaining_schedule_signature_mismatch",
                      changed_earlier["quarantine_reasons"])

    def test_post_adjustment_pattern_rejects_unproven_payment_split(self):
        # The planner must never infer this split from the current balance alone.
        result = self.planned(
            9999, "172.00", "118.69", "50.00", later=(("2026-09-30", "3.37", "1.63"),),
        )
        self.assertIn("source_exact_remaining_schedule_signature_mismatch",
                      result["quarantine_reasons"])

    def test_post_adjustment_exception_requires_source_timestamps(self):
        loan, source, target, product = self.fixture.lifecycle_fixture()
        loan.update({
            "ID_CREDITO": 2499, "MONTO_APROBADO": "172.00",
            "MONTO_DESEMBOLSADO": "172.00", "ULTIMO_SALDO": "115.32",
            "SALDO_INTERES": "0.00", "SALDO_INTERES_PENDIENTE": "0.00",
            "SALDO_SEGURO": "0.00", "SALDO_TOTAL": "115.32",
            "FECHA_OTORGAMIENTO": "2026-09-28",
        })
        source["application"]["FECHA_DESEMBOLSO"] = "2026-08-28"
        source["schedule_adjustment_summary"] = {"adjustment_count": 2}
        source["schedule"] = [
            {"NO_CUOTA": 1, "FECHA_PAGO": "2026-09-29", "MONTO_CAPITAL": "1.00",
             "MONTO_INTERES": "0.81", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
            {"NO_CUOTA": 2, "FECHA_PAGO": "2026-09-30", "MONTO_CAPITAL": "117.69",
             "MONTO_INTERES": "0.79", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
        ]
        disb, repay = source["movements"]
        disb.update({"ID_CREDITO": 2499, "FECHA_OPERACION": "2026-08-28",
                     "MONTO": "172.00", "MONTO_CAPITAL": "172.00"})
        repay.update({"ID_CREDITO": 2499, "FECHA_OPERACION": "2026-09-26",
                      "MONTO": "53.31", "MONTO_CAPITAL": "53.31",
                      "MONTO_INTERES": "0.00", "MONTO_SEGURO": "0.00"})
        later = dict(repay)
        later.update({"ID_MOVIMIENTO_CARTERA": "102", "FECHA_OPERACION": "2026-09-30",
                      "MONTO": "3.37", "MONTO_CAPITAL": "3.37"})
        source["movements"] = [disb, repay, later]
        source["charge_details"] = []
        result = _build_loan_lifecycle_action(self.fixture.contract, loan, source, target, product)
        self.assertIn("source_exact_remaining_schedule_signature_mismatch",
                      result["quarantine_reasons"])

    def test_repeated_adjustment_uses_proven_earlier_payment_split(self):
        loan, source, target, product = self.fixture.lifecycle_fixture()
        loan.update({
            "ID_CREDITO": 1728, "MONTO_APROBADO": "1100.00",
            "MONTO_DESEMBOLSADO": "1100.00", "ULTIMO_SALDO": "705.55",
            "SALDO_INTERES": "0.00", "SALDO_INTERES_PENDIENTE": "0.00",
            "SALDO_SEGURO": "0.00", "SALDO_TOTAL": "705.55",
            "FECHA_OTORGAMIENTO": "2026-09-21",
        })
        source["application"]["FECHA_DESEMBOLSO"] = "2026-08-28"
        source["schedule"] = [
            {"NO_CUOTA": 1, "FECHA_PAGO": "2026-09-28", "MONTO_CAPITAL": "300.00",
             "MONTO_INTERES": "10.00", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
            {"NO_CUOTA": 2, "FECHA_PAGO": "2026-10-05", "MONTO_CAPITAL": "456.75",
             "MONTO_INTERES": "5.00", "MONTO_OTROS": "0", "MONTO_APORTACION": 0,
             "ID_REESTRUCTURACION": None, "CUOTA_DIFERIDA": 0},
        ]
        historical, later = (dict(row) for row in source["movements"])
        historical.update({
            "ID_CREDITO": 1728, "FECHA_OPERACION": "2026-08-28",
            "MONTO": "1100.00", "MONTO_CAPITAL": "1100.00",
        })
        later.update({
            "ID_CREDITO": 1728, "FECHA_OPERACION": "2026-09-18",
            "DT_CREO": datetime(2026, 9, 18, 12),
            "MONTO": "343.25", "MONTO_CAPITAL": "343.25",
            "MONTO_INTERES": "0.00", "MONTO_SEGURO": "0.00",
        })
        source["movements"] = [historical, later]
        for movement_id, when, principal, interest in (
            (102, "2026-09-28", "30.00", "0.00"),
            (103, "2026-10-03", "21.20", "8.36"),
        ):
            payment = dict(later)
            payment.update({
                "ID_MOVIMIENTO_CARTERA": str(movement_id),
                "FECHA_OPERACION": when,
                "DT_CREO": datetime.fromisoformat(when + "T12:00:00"),
                "MONTO": str(Decimal(principal) + Decimal(interest)),
                "MONTO_CAPITAL": principal, "MONTO_INTERES": interest,
            })
            source["movements"].append(payment)
        source["charge_details"] = []
        adjustments = [
            {"ID_REESTRUCTURACION": 202, "DT_CREO": datetime(2026, 9, 21, 20, 46),
             "MONTO_REESTRUCTURADO": "756.75"},
            {"ID_REESTRUCTURACION": 223, "DT_CREO": datetime(2026, 10, 6, 17, 20),
             "MONTO_REESTRUCTURADO": "756.75"},
        ]
        archived = {
            str(item["ID_REESTRUCTURACION"]): [dict(row) for row in source["schedule"]]
            for item in adjustments
        }
        source["schedule_adjustment_summary"] = {
            "adjustment_count": 2,
            "last_adjustment_created_at": adjustments[-1]["DT_CREO"],
            "adjustments": adjustments,
            "archived_schedules": archived,
        }
        accepted = _build_loan_lifecycle_action(
            self.fixture.contract, loan, source, target, product,
        )
        policy = accepted["lifecycle"]["source_exact_remaining_schedule_policy"]
        self.assertIsNotNone(policy)
        self.assertEqual(policy["bridge_principal"], "343.25")
        self.assertEqual(policy["adjustment_proof"]["anchor_adjustment_id"], 202)
        self.assertEqual(policy["adjustment_proof"]["latest_adjustment_id"], 223)
        self.assertNotIn("source_exact_remaining_schedule_signature_mismatch",
                         accepted["quarantine_reasons"])

        source["schedule_adjustment_summary"]["archived_schedules"]["223"][0]["MONTO_INTERES"] = "11.00"
        rejected = _build_loan_lifecycle_action(
            self.fixture.contract, loan, source, target, product,
        )
        self.assertIn("source_exact_remaining_schedule_signature_mismatch",
                      rejected["quarantine_reasons"])

    def test_regular_plan_freezes_manual_fallback_capability(self):
        loan, source, target, product = self.fixture.lifecycle_fixture()
        result = _build_loan_lifecycle_action(
            self.fixture.contract, loan, source, target, product,
        )
        self.assertEqual(
            result["lifecycle"]["source_exact_manual_fallback"],
            "initial-zero-servicing-v1",
        )

    def test_initial_manual_writer_copies_components_and_rejects_started_servicing(self):
        result = self.planned(2357, "433.00", "175.28", "257.72")
        action = {"external_id": "ARISSTO:CRD:2357", "lifecycle": result["lifecycle"]}
        expected = _source_exact_expected_schedule(result["lifecycle"])
        periods = [
            {"period": row["number"], "fromDate": "2026-08-28" if index == 0 else expected[index-1]["due_date"],
             "dueDate": row["due_date"], "principalOriginalDue": row["principal"],
             "interestOriginalDue": row["interest"]}
            for index, row in enumerate(expected)
        ]
        current = {"periods": [{"period": 1, "fromDate": "2026-08-28",
                                "dueDate": "2026-09-29", "principalOriginalDue": "433.00",
                                "interestOriginalDue": "2.00"}]}
        loan = {"id": 77, "status": {"id": 300}, "repaymentSchedule": current,
                "transactions": [{"type": {"id": 1}}]}
        refreshed = {**loan, "repaymentSchedule": {"periods": periods}}
        self.assertEqual(_loan_schedule_differences(expected, refreshed["repaymentSchedule"]), [])
        api = MagicMock()
        with patch("arissto_sync.loans._find_loan", return_value=refreshed):
            _ensure_source_exact_initial_manual_schedule(api, loan, action, "attempt")
        payload = api.request.call_args.args[2]
        self.assertEqual(api.request.call_args.kwargs["query"], {"command": "sourceExactResyncSchedule"})
        self.assertEqual(payload["expectedNonDisbursementTransactionCount"], 0)
        self.assertEqual(payload["installments"][0]["principal"], "257.72")
        self.assertEqual(payload["installments"][1]["principal"], "1.00")
        self.assertEqual(payload["installments"][1]["interest"], "0.81")
        with self.assertRaisesRegex(RuntimeError, "servicing_already_started"):
            _ensure_source_exact_initial_manual_schedule(
                api, {**loan, "transactions": [{"type": {"id": 1}}, {"type": {"id": 2}}]},
                action, "attempt",
            )

    def test_preview_component_mismatch_uses_frozen_manual_fallback(self):
        loan, source, target, product = self.fixture.lifecycle_fixture()
        lifecycle = _build_loan_lifecycle_action(
            self.fixture.contract, loan, source, target, product,
        )["lifecycle"]
        lifecycle["events"] = lifecycle["events"][:1]
        lifecycle["cutover_insurance_charge"] = None
        lifecycle["recurring_insurance_charge"] = None
        lifecycle["mora_terms"]["fineract_starts_on"] = "2026-06-21"
        pending = {
            "id": 55, "loanProductId": 90, "isInterestRecalculationEnabled": True, "clientId": 900, "principal": 350,
            "status": {"id": 100}, "transactions": [],
            "repaymentSchedule": self.fixture.calculated_schedule(lifecycle),
        }
        approved = {**pending, "status": {"id": 200}}
        active = {**pending, "status": {"id": 300},
                  "transactions": [{"type": {"id": 1}}]}
        api = MagicMock()
        api.calculate_loan_schedule.return_value = self.fixture.calculated_schedule(lifecycle)
        api.request.side_effect = [{"resourceId": 55}, {}, approved, {}, active, active]
        action = {"external_id": "ARISSTO:CRD:2068", "lifecycle": lifecycle}
        with (
            patch("arissto_sync.loans._find_loan", side_effect=[None, pending]),
            patch("arissto_sync.loans._ensure_source_exact_pending_schedule",
                  side_effect=RuntimeError("loan_source_exact_schedule_preview_mismatch:{}")),
            patch("arissto_sync.loans._ensure_source_exact_initial_manual_schedule",
                  return_value=active) as manual,
        ):
            self.assertEqual(
                _apply_loan_lifecycle(api, action, 90, finalize=False), (55, False),
            )
        manual.assert_called_once()
        self.assertEqual(api.request.call_args_list[3].kwargs["query"],
                         {"command": "sourceExactDisburse"})

    def test_disbursement_date_drift_restores_exact_schedule_before_servicing(self):
        loan, source, target, product = self.fixture.lifecycle_fixture()
        lifecycle = _build_loan_lifecycle_action(
            self.fixture.contract, loan, source, target, product,
        )["lifecycle"]
        lifecycle["schedule_writer"] = "fineract-variable-installments-v1"
        lifecycle["schedule_reconciliation_policy"] = "exact-source-schedule"
        lifecycle["events"] = lifecycle["events"][:1]
        lifecycle["cutover_insurance_charge"] = None
        lifecycle["recurring_insurance_charge"] = None
        lifecycle["mora_terms"]["fineract_starts_on"] = "2026-06-21"
        disbursement_date = lifecycle["events"][0]["date"]
        contractual_date = (datetime.fromisoformat(disbursement_date).date()
                            + timedelta(days=2)).isoformat()
        lifecycle["application_payload"]["expectedDisbursementDate"] = contractual_date
        lifecycle["approval_payload"]["expectedDisbursementDate"] = contractual_date
        pending = {
            "id": 55, "loanProductId": 90, "isInterestRecalculationEnabled": True, "clientId": 900, "principal": 350,
            "status": {"id": 100}, "transactions": [],
            "repaymentSchedule": self.fixture.calculated_schedule(lifecycle),
        }
        approved = {**pending, "status": {"id": 200}}
        active = {**pending, "status": {"id": 300},
                  "transactions": [{"type": {"id": 1}}]}
        api = MagicMock()
        api.calculate_loan_schedule.return_value = self.fixture.calculated_schedule(lifecycle)
        api.request.side_effect = [{"resourceId": 55}, {}, approved, {}, active, active]
        action = {"external_id": "ARISSTO:CRD:date-drift", "lifecycle": lifecycle}
        with (
            patch("arissto_sync.loans._find_loan", side_effect=[None, pending]),
            patch("arissto_sync.loans._ensure_source_exact_pending_schedule", return_value=pending),
            patch("arissto_sync.loans._ensure_source_exact_initial_manual_schedule",
                  return_value=active) as restore,
        ):
            self.assertEqual(_apply_loan_lifecycle(api, action, 90, finalize=False), (55, False))
        restore.assert_called_once()
