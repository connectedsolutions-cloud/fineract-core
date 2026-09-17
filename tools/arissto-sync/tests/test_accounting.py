import unittest
import tempfile
from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from arissto_sync.accounting import (
    BLOCK, RECONCILIATION_VERSION, AccountingContract, HEADER_PERIOD_QUERY, HEADER_QUERY, LINE_PERIOD_QUERY, LINE_QUERY,
    SOURCE_LEDGER_CONTROL_QUERY, SOURCE_LEDGER_CONTROL_SUMMARY_QUERY, SOURCE_LEDGER_MAYOR_QUERY,
    SOURCE_SCHEMA_QUERY,
    _classify_apply_error, _hash, _load_accounting_plan_inputs, _missing_api_user_office_ids,
    _source_control_period_readiness,
    _source_ledger_control,
    _verify_scheduler_paused, accounting_retry_keys,
    apply_accounting_plan,
    assert_accounting_plan_current,
    build_historical_journal_request, classify_accounting, parse_source_key, plan_accounting_rows,
    reconcile_accounting,
)
from arissto_sync.arissto import READ_ONLY_SQL, source_fingerprint
from arissto_sync.config import SourceConfig, TargetConfig
from arissto_sync.state import State


CONFIG = Path(__file__).resolve().parents[1] / "config/accounting.json"


def header(**changes):
    value = {
        "company_id": "001", "header_branch_id": "001", "period_id": "00065",
        "journal_id": "10", "journal_number": "2025120010",
        "journal_date": date(2025, 12, 15), "journal_status": "3",
        "journal_type": "001", "liquidation_flag": "0", "opening_flag": "0",
        "source_system": 1, "daily_close_id": "9", "mayorization_close_id": "9",
        "period_year": "2025", "period_month": "12",
        "header_concept": "private header text", "header_description": "private description",
    }
    value.update(changes)
    return value


def line(line_id, debit="0.00", credit="0.00", **changes):
    value = {
        "company_id": "001", "header_branch_id": "001", "period_id": "00065",
        "journal_id": "10", "line_id": str(line_id), "account_id": str(line_id),
        "account_code": "1110010101", "destination_branch_id": "001",
        "debit": Decimal(debit), "credit": Decimal(credit),
        "line_concept": "private line text", "line_aux_concept": "private auxiliary text",
    }
    value.update(changes)
    return value


def target(**changes):
    value = {
        "accounts": {
            "1110010199": [{"id": 7, "disabled": False, "manual_allowed": True}],
        },
        "offices": {
            1: {"external_id": "1"},
            2: {"external_id": "2"},
        },
        "closure_by_office": {},
        "currencies": {"USD": [{"id": 1, "decimal_places": 2}]},
        "imported": {},
    }
    value.update(changes)
    return value


class AccountingInspectorTests(unittest.TestCase):

    def test_gate7_scheduler_guard_and_error_classification_fail_closed(self):
        api = SimpleNamespace(request=lambda method, path: {"active": True})
        with self.assertRaisesRegex(RuntimeError, "scheduler must be paused"):
            _verify_scheduler_paused(api)
        self.assertEqual(_classify_apply_error(requests.ConnectionError("lost"))[1:], ("retryable", True))
        self.assertEqual(_classify_apply_error(ValueError("bad response"))[1:], ("quarantined", False))
        office_error = RuntimeError("error.msg.arissto.historical.gl.office.unauthorized")
        self.assertEqual(_classify_apply_error(office_error)[1:], ("fatal", False))
    def setUp(self):
        self.contract = AccountingContract.load(CONFIG)

    def test_accounting_is_inspect_only_and_uses_complete_source_keys(self):
        self.assertEqual(BLOCK, "accounting")
        self.assertEqual(parse_source_key("001:001:00065:10"), ("001", "001", "00065", "10"))
        with self.assertRaisesRegex(ValueError, "COMPANY:BRANCH:PERIOD:JOURNAL"):
            parse_source_key("10")
        for query in (
            HEADER_QUERY, LINE_QUERY, HEADER_PERIOD_QUERY, LINE_PERIOD_QUERY,
            SOURCE_SCHEMA_QUERY, SOURCE_LEDGER_CONTROL_SUMMARY_QUERY,
            SOURCE_LEDGER_CONTROL_QUERY, SOURCE_LEDGER_MAYOR_QUERY,
        ):
            self.assertRegex(query, READ_ONLY_SQL)
        self.assertIn("p.ID_PERIODO=?", HEADER_PERIOD_QUERY)
        self.assertIn("d.ID_PERIODO=?", LINE_PERIOD_QUERY)
        self.assertIn("non_annual_liquidation_line_count", SOURCE_LEDGER_CONTROL_QUERY)

    def test_source_ledger_control_accepts_only_reproducible_annual_hybrid_rollup(self):
        document, _, _, _ = self.reconciliation_fixture()
        summary = [{
            "control_period_id": "00065", "closed_before_cutoff": 1,
            "eligible_journal_count": 1,
        }]
        comparisons = [{
            "destination_branch_id": "001",
            "account_id": "parent", "journal_closing": Decimal("0.00"),
            "direct_line_count": 4,
            "non_annual_liquidation_line_count": 0,
        }]
        mayor = [{
            "destination_branch_id": "001", "account_id": "parent",
            "ledger_closing": Decimal("-10.00"),
        }]
        rollups = [{
            "destination_branch_id": "001", "account_id": "parent",
            "child_account_count": 2, "child_ledger_row_count": 2,
            "child_ledger_closing": Decimal("-10.00"),
        }]
        with (
            patch("arissto_sync.accounting.source_connection", return_value=nullcontext(object())),
            patch("arissto_sync.accounting.select_rows", side_effect=[summary, comparisons, mayor, rollups]),
        ):
            result = _source_ledger_control(SimpleNamespace(source=object()), self.contract, document)

        self.assertEqual(result["raw_closing_mismatch_count"], 1)
        self.assertEqual(result["accepted_hybrid_rollup_count"], 1)
        self.assertEqual(result["accepted_hybrid_rollup_variance"], Decimal("10.00"))
        self.assertEqual(result["unsafe_hybrid_account_count"], 0)
        self.assertEqual(result["closing_mismatch_count"], 0)

    def test_accounting_api_user_must_cover_all_mapped_offices(self):
        self.assertEqual(
            _missing_api_user_office_ids(
                {"api_user_selected": True, "api_user_office_ids": [1]}, self.contract,
            ),
            [2],
        )
        self.assertEqual(
            _missing_api_user_office_ids(
                {"api_user_selected": True, "api_user_office_ids": [1, 2]}, self.contract,
            ),
            [],
        )

    def test_source_control_period_must_end_before_cutoff(self):
        header = {
            "company_id": "001", "header_branch_id": "001", "period_id": "00074", "journal_id": "1",
            "journal_date": date(2026, 9, 10), "period_year": 2026, "period_month": 9,
        }
        self.assertEqual(
            _source_control_period_readiness([header], {"findings": []}, self.contract, date(2026, 9, 17)),
            {
                "resolved": True, "source_key": "001:001:00074:1", "period_id": "00074",
                "period_end": "2026-09-30", "closed_before_cutoff": False,
            },
        )
    def test_period_plan_apply_revalidation_uses_bounded_period_queries(self):
        calls = []

        def fake_select_rows(_connection, query, params=()):
            calls.append((query, params))
            return []

        with patch("arissto_sync.accounting.select_rows", side_effect=fake_select_rows):
            _load_accounting_plan_inputs(
                SimpleNamespace(), self.contract, ["001:001:00053:10"],
                source_conn=object(), source_periods=["00053", "00052", "00053"],
            )

        self.assertEqual(
            calls[:4],
            [
                (HEADER_PERIOD_QUERY, ("001", "00052")),
                (LINE_PERIOD_QUERY, ("001", "00052")),
                (HEADER_PERIOD_QUERY, ("001", "00053")),
                (LINE_PERIOD_QUERY, ("001", "00053")),
            ],
        )
        self.assertEqual(calls[4][0], SOURCE_SCHEMA_QUERY)

    def test_clean_journal_is_counted_without_exposing_free_text_or_amounts(self):
        report = classify_accounting(
            [header()], [line(1, debit="10.00"), line(2, credit="10.00")],
            self.contract, date(2026, 1, 1),
        )
        self.assertEqual(report["boundary_counts"]["before_cutoff"], 1)
        self.assertEqual(report["boundary_counts"]["on_cutoff"], 0)
        self.assertEqual(report["classification_counts"]["balanced"], 1)
        self.assertEqual(report["classification_counts"]["populated"], 1)
        self.assertEqual(report["classification_counts"]["SOURCE_JOURNAL_UNBALANCED"], 0)
        self.assertEqual(report["findings"], [])
        rendered = str(report)
        self.assertNotIn("private", rendered)
        self.assertNotIn("10.00", rendered)

    def test_journal_before_approved_inception_is_quarantined(self):
        old_header = header(
            period_id="00027", journal_id="9", journal_number="2022100009",
            journal_date=date(2022, 10, 31), period_year="2022", period_month="10",
        )
        old_lines = [
            line(1, period_id="00027", journal_id="9", debit="10.00"),
            line(2, period_id="00027", journal_id="9", credit="10.00"),
        ]
        report = classify_accounting([old_header], old_lines, self.contract, date(2026, 1, 1))
        self.assertIn(
            "SOURCE_JOURNAL_BEFORE_HISTORICAL_ORIGIN",
            report["findings"][0]["reason_codes"],
        )

    def test_stable_reason_codes_cover_status_shape_period_account_agency_and_closure(self):
        target = {
            "accounts": {"1110010199": [{"id": 7, "disabled": False, "manual_allowed": True}]},
            "closure_by_office": {1: date(2026, 1, 31)},
        }
        bad_header = header(
            journal_date=date(2026, 1, 15), journal_status="2", period_month="12",
            journal_number="bad", opening_flag="1",
        )
        bad_lines = [
            line(1, debit="1.001", credit="2.00"),
            line(1, debit="0.00", credit="0.00", account_code=None, destination_branch_id="999"),
        ]
        report = classify_accounting([bad_header], bad_lines, self.contract, date(2026, 1, 15), target)
        reasons = set(report["findings"][0]["reason_codes"])
        self.assertTrue({
            "SOURCE_JOURNAL_EXCLUDED_FROM_LEDGER", "SOURCE_JOURNAL_UNBALANCED",
            "SOURCE_JOURNAL_REFERENCE_INVALID",
            "SOURCE_OPENING_JOURNAL_REQUIRES_REVIEW", "SOURCE_JOURNAL_LINE_KEY_DUPLICATE",
            "SOURCE_JOURNAL_LINE_ZERO", "SOURCE_AMOUNT_SCALE_UNSUPPORTED",
            "SOURCE_ACCOUNT_UNRESOLVED", "SOURCE_DESTINATION_BRANCH_UNMAPPED",
            "TARGET_OFFICE_CLOSURE_CONFLICT",
        } <= reasons)
        self.assertEqual(report["classification_counts"]["SOURCE_JOURNAL_BACK_PERIOD"], 1)
        self.assertEqual(
            report["date_policy_observations"][0]["effective_entry_date"], "2025-12-31",
        )

    def test_classification_and_hashes_are_deterministic(self):
        headers = [header()]
        lines = [line(2, credit="3.00"), line(1, debit="3.00")]
        first = classify_accounting(headers, lines, self.contract, date(2026, 1, 1))
        second = classify_accounting(headers, list(reversed(lines)), self.contract, date(2026, 1, 1))
        self.assertEqual(first, second)

    def plan(self, headers=None, lines=None, target_snapshot=None, keys=None, cutoff="2026-01-01"):
        return plan_accounting_rows(
            headers if headers is not None else [header()],
            lines if lines is not None else [line("02", credit="3.00"), line("01", debit="3.00")],
            self.contract,
            {"date": cutoff, "timezone": "America/El_Salvador", "source": "explicit"},
            "source-fingerprint", "target-fingerprint", target_snapshot or target(),
            keys or ["001:001:00065:10"], "source-schema-signature",
        )

    def test_explicit_key_plan_is_canonical_and_freezes_resolved_mappings(self):
        first = self.plan()
        second = self.plan(lines=list(reversed([
            line("02", credit="3.00"), line("01", debit="3.00")
        ])))
        self.assertEqual(first, second)
        self.assertEqual(first["counts"], {"APPLICABLE": 1})
        action = first["actions"][0]
        self.assertEqual(action["disposition"], "APPLICABLE")
        self.assertEqual([item["source_line_id"] for item in action["payload"]["lines"]], ["01", "02"])
        self.assertEqual(action["payload"]["debit_total"], "3.00")
        self.assertEqual(action["payload"]["credit_total"], "3.00")
        planned_line = action["payload"]["lines"][0]
        self.assertEqual(planned_line["target_account_code"], "1110010199")
        self.assertEqual(planned_line["target_gl_account_id"], 7)
        self.assertEqual(planned_line["office_id"], 1)
        self.assertEqual(planned_line["dimensions"], {"office": "1"})
        self.assertEqual(planned_line["debit"], "3.00")
        self.assertEqual(first["bindings"]["policy"]["planner_version"], "accounting-explicit-key-plan-v2")
        self.assertEqual(len(first["plan_hash"]), 64)
        self.assertEqual(len(action["planned_hash"]), 64)

    def test_malformed_reference_month_is_preserved_without_quarantine(self):
        source_header = header(
            period_id="00054", journal_id="0000006008", journal_number="2025020061",
            journal_date=date(2025, 1, 24), period_year="2025", period_month="1",
        )
        source_lines = [
            line("01", period_id="00054", journal_id="0000006008", debit="3.00"),
            line("02", period_id="00054", journal_id="0000006008", credit="3.00"),
        ]
        document = self.plan(
            headers=[source_header], lines=source_lines,
            keys=["001:001:00054:0000006008"],
        )

        action = document["actions"][0]
        self.assertEqual(action["disposition"], "APPLICABLE")
        self.assertEqual(action["payload"]["ref_num"], "2025020061")
        self.assertEqual(action["payload"]["entry_date"], "2025-01-24")
        self.assertEqual(action["payload"]["provenance"]["source_journal_date"], "2025-01-24")
        self.assertEqual(
            action["payload"]["provenance"]["date_anomaly_codes"],
            ["SOURCE_JOURNAL_REFERENCE_DATE_MISMATCH"],
        )

    def test_back_period_journal_uses_period_end_and_preserves_source_date(self):
        source_header = header(
            header_branch_id="002", period_id="00058", journal_id="0000007509",
            journal_number="2025050365", journal_date=date(2025, 6, 4),
            period_year="2025", period_month="5",
        )
        source_lines = [
            line("01", header_branch_id="002", period_id="00058", journal_id="0000007509", debit="3.00"),
            line("02", header_branch_id="002", period_id="00058", journal_id="0000007509", credit="3.00"),
        ]
        document = self.plan(
            headers=[source_header], lines=source_lines,
            keys=["001:002:00058:0000007509"],
        )

        action = document["actions"][0]
        self.assertEqual(action["disposition"], "APPLICABLE")
        self.assertEqual(action["payload"]["entry_date"], "2025-05-31")
        self.assertEqual(action["payload"]["provenance"]["source_journal_date"], "2025-06-04")
        self.assertEqual(
            action["payload"]["provenance"]["date_anomaly_codes"],
            ["SOURCE_JOURNAL_BACK_PERIOD", "SOURCE_JOURNAL_REFERENCE_DATE_MISMATCH"],
        )
        request = build_historical_journal_request(
            "plan-1", "run-1", {**document, "accounting_cutoff": {
                **document["accounting_cutoff"], "configuration_revision": 2,
                "configuration_hash": "a" * 64, "lifecycle_state": "ACTIVE",
            }}, action, source_header, source_lines, self.contract,
        )
        self.assertEqual(request["sourceJournalDate"], "2025-06-04")
        self.assertEqual(request["entryDate"], "2025-05-31")
        self.assertEqual(
            request["knownAnomalyCodes"],
            "SOURCE_JOURNAL_BACK_PERIOD,SOURCE_JOURNAL_REFERENCE_DATE_MISMATCH",
        )
        boundary_document = self.plan(
            headers=[source_header], lines=source_lines,
            keys=["001:002:00058:0000007509"], cutoff="2025-06-01",
        )
        self.assertEqual(boundary_document["actions"][0]["disposition"], "APPLICABLE")

    def test_display_projection_is_normalized_bounded_and_raw_auxiliary_text_is_not_planned(self):
        long_text = "  A\nB  " + "x" * 600
        plan = self.plan(lines=[
            line("01", debit="1.00", line_concept=long_text, line_aux_concept="restricted secret"),
            line("02", credit="1.00", line_concept="   ", line_aux_concept="another secret"),
        ])
        planned = plan["actions"][0]["payload"]["lines"]
        self.assertEqual(len(planned[0]["description"]), 500)
        self.assertTrue(planned[0]["description"].startswith("A B "))
        self.assertTrue(planned[0]["description_truncated"])
        self.assertEqual(planned[1]["description"], "private description")
        rendered = str(plan)
        self.assertNotIn("restricted secret", rendered)
        self.assertNotIn("another secret", rendered)

    def test_plan_never_silently_omits_missing_invalid_or_post_cutoff_keys(self):
        invalid = header(
            journal_id="11", journal_date=date(2026, 1, 1),
            period_year="2026", period_month="1",
        )
        invalid_lines = [
            line("1", journal_id="11", debit="1.00"),
            line("2", journal_id="11", credit="1.00"),
        ]
        plan = self.plan(
            headers=[invalid], lines=invalid_lines,
            keys=["001:001:00065:11", "001:001:00065:99"],
        )
        self.assertEqual([action["source_key"] for action in plan["actions"]], [
            "001:001:00065:11", "001:001:00065:99",
        ])
        self.assertEqual(plan["counts"], {"QUARANTINED": 2})
        self.assertIn("SOURCE_JOURNAL_ON_OR_AFTER_CUTOFF", plan["actions"][0]["reason_codes"])
        self.assertEqual(plan["actions"][1]["reason_codes"], ["SOURCE_JOURNAL_HEADER_MISSING"])

    def test_duplicate_source_rows_quarantine_deterministically_across_input_order(self):
        first_header = header(header_description="first")
        second_header = header(header_description="second")
        source_lines = [
            line("01", debit="1.00", line_concept="first line"),
            line("01", debit="1.00", line_concept="duplicate line"),
            line("02", credit="2.00"),
        ]
        first = self.plan(headers=[first_header, second_header], lines=source_lines)
        second = self.plan(
            headers=[second_header, first_header], lines=list(reversed(source_lines)),
        )
        self.assertEqual(first, second)
        self.assertEqual(first["actions"][0]["disposition"], "QUARANTINED")
        self.assertEqual(
            set(first["actions"][0]["reason_codes"]),
            {"SOURCE_JOURNAL_HEADER_KEY_DUPLICATE", "SOURCE_JOURNAL_LINE_KEY_DUPLICATE"},
        )

    def test_target_provenance_selects_unchanged_and_rejects_hash_drift(self):
        applicable = self.plan()
        source_hash = applicable["actions"][0]["source_hash"]
        unchanged = self.plan(target_snapshot=target(imported={"001:001:00065:10": source_hash}))
        self.assertEqual(unchanged["actions"][0]["disposition"], "UNCHANGED")
        drifted = self.plan(target_snapshot=target(imported={"001:001:00065:10": "old-hash"}))
        self.assertEqual(drifted["actions"][0]["disposition"], "QUARANTINED")
        self.assertEqual(drifted["actions"][0]["reason_codes"], ["TARGET_PROVENANCE_HASH_DRIFT"])

    def test_plan_reuse_rejects_cutoff_mapping_target_and_source_drift(self):
        frozen = self.plan()
        assert_accounting_plan_current(frozen, self.plan())
        with self.assertRaisesRegex(RuntimeError, "ACCOUNTING_CUTOFF_DRIFT"):
            assert_accounting_plan_current(frozen, self.plan(cutoff="2026-02-01"))
        changed_target = target()
        changed_target["accounts"]["1110010199"][0]["id"] = 8
        with self.assertRaisesRegex(RuntimeError, "ACCOUNTING_PLAN_BINDING_DRIFT"):
            assert_accounting_plan_current(frozen, self.plan(target_snapshot=changed_target))
        with self.assertRaisesRegex(RuntimeError, "ACCOUNTING_SOURCE_OR_PAYLOAD_DRIFT"):
            assert_accounting_plan_current(
                frozen,
                self.plan(lines=[line("01", debit="4.00"), line("02", credit="4.00")]),
            )

    def test_gate7_request_matches_atomic_api_without_leaking_text_into_plan(self):
        cutoff = {
            "date": "2026-01-01", "timezone": "America/El_Salvador", "source": "explicit",
            "configuration_revision": 2, "configuration_hash": "a" * 64, "lifecycle_state": "ACTIVE",
        }
        document = plan_accounting_rows(
            [header()], [line("01", debit="3.00"), line("02", credit="3.00")], self.contract,
            cutoff, "source-fingerprint", "target-fingerprint", target(),
            ["001:001:00065:10"], "b" * 64,
        )
        action = document["actions"][0]
        request = build_historical_journal_request(
            "plan-1", "run-1", document, action, header(),
            [line("01", debit="3.00"), line("02", credit="3.00")], self.contract,
        )
        self.assertEqual(request["provenanceSchemaVersion"], "arissto-gl-v1")
        self.assertEqual(request["sourceJournalNumber"], request["refNum"])
        self.assertEqual(request["sourceJournalDate"], request["entryDate"])
        self.assertEqual(request["cutoffConfigurationRevision"], 2)
        self.assertEqual(request["lines"][0]["officeExternalId"], "1")
        self.assertEqual(request["lines"][0]["sourceLineConcept"], "private line text")
        self.assertNotIn("private auxiliary text", str(document))

    def test_gate7_state_retains_recovery_identity_and_retryability(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            plan_document = self.plan()
            state.adopt_accounting_cutoff(plan_document["accounting_cutoff"])
            plan_id = state.save_plan("target", BLOCK, "source", self.contract.hash, plan_document)
            run_id = state.start_run(state.plan(plan_id))
            state.record_accounting_item(
                run_id, "001:001:00065:10", "import", "a" * 64, "pending",
                plan_document["plan_hash"], "b" * 64, "acct:key", run_id,
            )
            pending = state.accounting_retry_items(run_id)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["request_idempotency_key"], "acct:key")
            state.record_accounting_item(
                run_id, "001:001:00065:10", "import", "a" * 64, "failed",
                plan_document["plan_hash"], "b" * 64, "acct:key", run_id,
                error_code="ACCOUNTING_IMPORT_CONNECTIONERROR", error_class="retryable", retryable=True,
            )
            attempt = state.accounting_attempt(run_id, "001:001:00065:10")
            self.assertTrue(attempt["retryable"])
            self.assertEqual(attempt["request_run_id"], run_id)

    def reconciliation_fixture(self):
        document = self.plan()
        document["accounting_cutoff"].update({
            "configuration_revision": 2,
            "configuration_hash": "a" * 64,
            "lifecycle_state": "ACTIVE",
        })
        action = document["actions"][0]
        transaction_id = "AI-target-transaction"
        rows = []
        for sequence, expected in enumerate(action["payload"]["lines"], 1):
            is_debit = Decimal(expected["debit"]) > 0
            side = "DEBIT" if is_debit else "CREDIT"
            type_enum = 2 if is_debit else 1
            amount = expected["debit"] if is_debit else expected["credit"]
            rows.append({
                "source_key": action["source_key"],
                "target_transaction_id": transaction_id,
                "target_ref_num": action["payload"]["ref_num"],
                "source_journal_date": action["payload"]["entry_date"],
                "source_hash": action["source_hash"],
                "planned_hash": action["planned_hash"],
                "contract_hash": document["bindings"]["contract_hash"],
                "source_schema_signature": document["bindings"]["source_schema_signature"],
                "coa_mapping_hash": document["bindings"]["coa_mapping"]["hash"],
                "office_mapping_hash": document["bindings"]["agency_mapping"]["hash"],
                "policy_hash": document["bindings"]["policy"]["hash"],
                "cutoff_date": document["accounting_cutoff"]["date"],
                "cutoff_timezone_id": document["accounting_cutoff"]["timezone"],
                "cutoff_configuration_revision": 2,
                "cutoff_configuration_hash": "a" * 64,
                "provenance_result": "IMPORTED",
                "source_line_id": expected["source_line_id"],
                "source_line_sequence": sequence,
                "source_line_hash": "b" * 64,
                "source_account_id": expected["source_account_id"],
                "source_account_code": expected["source_account_code"],
                "target_gl_account_id": expected["target_gl_account_id"],
                "source_debit_amount": expected["debit"],
                "source_credit_amount": expected["credit"],
                "source_side": side,
                "source_amount": amount,
                "target_side": side,
                "target_type_enum": type_enum,
                "target_amount": amount,
                "target_entry_date": action["payload"]["entry_date"],
                "source_destination_branch_id": expected["source_destination_branch_id"],
                "target_office_id": expected["office_id"],
                "target_office_external_id": expected["dimensions"]["office"],
                "target_dimensions": expected["dimensions"],
                "target_description_sha256": expected["description_sha256"],
                "target_journal_entry_id": 100 + sequence,
                "line_result": "IMPORTED",
                "journal_entry_id": 100 + sequence,
                "journal_account_id": expected["target_gl_account_id"],
                "journal_account_code": expected["target_account_code"],
                "journal_office_id": expected["office_id"],
                "journal_office_external_id": expected["dimensions"]["office"],
                "currency_code": action["payload"]["currency"],
                "journal_transaction_id": transaction_id,
                "reversed": False,
                "reversal_id": None,
                "journal_ref_num": action["payload"]["ref_num"],
                "manual_entry": True,
                "journal_entry_date": action["payload"]["entry_date"],
                "journal_type_enum": type_enum,
                "journal_amount": amount,
                "journal_description": expected["description"],
                "journal_dimensions": expected["dimensions"],
                "loan_transaction_id": None,
                "savings_transaction_id": None,
                "client_transaction_id": None,
                "share_transaction_id": None,
                "entity_type_enum": None,
                "entity_id": None,
            })
        return document, action, transaction_id, rows

    def test_gate8_direct_journal_reconciliation_marks_exact_run_reconciled(self):
        document, action, transaction_id, rows = self.reconciliation_fixture()
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target-fingerprint", pg_url=None))
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            state.adopt_accounting_cutoff(document["accounting_cutoff"])
            plan_id = state.save_plan(
                settings.target.fingerprint, BLOCK, "source-fingerprint", self.contract.hash, document,
            )
            run_id = state.start_run(state.plan(plan_id))
            state.record_accounting_item(
                run_id, action["source_key"], "import", action["source_hash"], "succeeded",
                document["plan_hash"], action["planned_hash"], "acct:key", run_id,
                target_transaction_id=transaction_id, target_line_ids=[101, 102], disposition="IMPORTED",
            )
            state.finish_run(run_id, "completed", {"imported": 1})
            result = reconcile_accounting(
                settings, state, self.contract, run_id,
                {"rows": rows, "boundary": {
                    "native_non_manual_pre_cutoff": 0, "imported_on_or_after_cutoff": 0,
                }},
                {
                    "control_period_id": "00065", "closed_before_cutoff": 1,
                    "eligible_journal_count": 1, "compared_account_branch_count": 2,
                    "closing_mismatch_count": 0, "absolute_closing_variance": "0.00",
                },
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["reconciliation_version"], RECONCILIATION_VERSION)
            self.assertEqual(result["counts"]["reconciled"], 1)
            self.assertEqual(result["direct_balance_control"]["agency_variance_count"], 0)
            self.assertEqual(result["direct_balance_control"]["consolidated_variance_count"], 0)
            self.assertTrue(result["gate8_acceptance_ok"])
            self.assertEqual(result["source_ledger_findings"], [])
            self.assertNotIn("product_subledgers", result)
            self.assertEqual(state.run(run_id)["status"], "reconciled")
            self.assertEqual(state.run_items(run_id)[0]["status"], "reconciled")

    def test_gate8_reconciliation_uses_terminal_items_across_plan_retry_chain(self):
        document, action, transaction_id, rows = self.reconciliation_fixture()
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target-fingerprint", pg_url=None))
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            state.adopt_accounting_cutoff(document["accounting_cutoff"])
            plan_id = state.save_plan(
                settings.target.fingerprint, BLOCK, "source-fingerprint", self.contract.hash, document,
            )
            apply_run_id = state.start_run(state.plan(plan_id))
            state.record_accounting_item(
                apply_run_id, action["source_key"], "import", action["source_hash"], "succeeded",
                document["plan_hash"], action["planned_hash"], "acct:key", apply_run_id,
                target_transaction_id=transaction_id, target_line_ids=[101, 102], disposition="IMPORTED",
            )
            state.finish_run(apply_run_id, "completed", {"imported": 1})
            reconciliation_run_id = state.start_run(state.plan(plan_id))
            state.finish_run(reconciliation_run_id, "completed", {})

            result = reconcile_accounting(
                settings, state, self.contract, reconciliation_run_id,
                {"rows": rows, "boundary": {
                    "native_non_manual_pre_cutoff": 0, "imported_on_or_after_cutoff": 0,
                }},
                {
                    "control_period_id": "00065", "closed_before_cutoff": 1,
                    "eligible_journal_count": 1, "compared_account_branch_count": 2,
                    "closing_mismatch_count": 0, "absolute_closing_variance": "0.00",
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["counts"]["reconciled"], 1)
            self.assertEqual(state.run_items(apply_run_id)[0]["status"], "reconciled")

    def test_gate8_reconciliation_fails_closed_on_line_or_boundary_drift(self):
        document, action, transaction_id, rows = self.reconciliation_fixture()
        rows[0]["journal_amount"] = "4.00"
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target-fingerprint", pg_url=None))
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            state.adopt_accounting_cutoff(document["accounting_cutoff"])
            plan_id = state.save_plan(
                settings.target.fingerprint, BLOCK, "source-fingerprint", self.contract.hash, document,
            )
            run_id = state.start_run(state.plan(plan_id))
            state.record_accounting_item(
                run_id, action["source_key"], "import", action["source_hash"], "succeeded",
                document["plan_hash"], action["planned_hash"], "acct:key", run_id,
                target_transaction_id=transaction_id, target_line_ids=[101, 102], disposition="IMPORTED",
            )
            result = reconcile_accounting(
                settings, state, self.contract, run_id,
                {"rows": rows, "boundary": {
                    "native_non_manual_pre_cutoff": 1, "imported_on_or_after_cutoff": 0,
                }},
                {
                    "control_period_id": "00065", "closed_before_cutoff": 1,
                    "eligible_journal_count": 1, "compared_account_branch_count": 2,
                    "closing_mismatch_count": 0, "absolute_closing_variance": "0.00",
                },
            )
            self.assertFalse(result["ok"])
            self.assertIn("TARGET_JOURNAL_LINE_DRIFT", result["findings"][0]["reason_codes"])
            self.assertIn("TARGET_JOURNAL_TOTAL_DRIFT", result["findings"][0]["reason_codes"])
            self.assertEqual(result["boundary_findings"], ["TARGET_NATIVE_NON_MANUAL_PRE_CUTOFF_GL"])
            self.assertIn("TARGET_AGENCY_BALANCE_DRIFT", result["balance_findings"])
            self.assertEqual(state.run(run_id)["status"], "reconciliation-failed")

    def test_gate8_fails_when_final_source_ledger_control_is_incomplete_or_drifted(self):
        document, action, transaction_id, rows = self.reconciliation_fixture()
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target-fingerprint", pg_url=None))
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            state.adopt_accounting_cutoff(document["accounting_cutoff"])
            plan_id = state.save_plan(
                settings.target.fingerprint, BLOCK, "source-fingerprint", self.contract.hash, document,
            )
            run_id = state.start_run(state.plan(plan_id))
            state.record_accounting_item(
                run_id, action["source_key"], "import", action["source_hash"], "succeeded",
                document["plan_hash"], action["planned_hash"], "acct:key", run_id,
                target_transaction_id=transaction_id, target_line_ids=[101, 102], disposition="IMPORTED",
            )
            result = reconcile_accounting(
                settings, state, self.contract, run_id,
                {"rows": rows, "boundary": {
                    "native_non_manual_pre_cutoff": 0, "imported_on_or_after_cutoff": 0,
                }},
                {
                    "control_period_id": "00065", "closed_before_cutoff": 1,
                    "eligible_journal_count": 2, "compared_account_branch_count": 2,
                    "closing_mismatch_count": 1, "absolute_closing_variance": "1.00",
                },
            )
            self.assertFalse(result["ok"])
            self.assertFalse(result["gate8_acceptance_ok"])
            self.assertEqual(result["source_ledger_findings"], [
                "SOURCE_LEDGER_CONTROL_SCOPE_INCOMPLETE",
                "SOURCE_JOURNAL_TO_CNT_MAYOR_CLOSING_DRIFT",
            ])

    def test_gate8_accepts_proven_safe_hybrid_parent_rollups(self):
        document, action, transaction_id, rows = self.reconciliation_fixture()
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target-fingerprint", pg_url=None))
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            state.adopt_accounting_cutoff(document["accounting_cutoff"])
            plan_id = state.save_plan(
                settings.target.fingerprint, BLOCK, "source-fingerprint", self.contract.hash, document,
            )
            run_id = state.start_run(state.plan(plan_id))
            state.record_accounting_item(
                run_id, action["source_key"], "import", action["source_hash"], "succeeded",
                document["plan_hash"], action["planned_hash"], "acct:key", run_id,
                target_transaction_id=transaction_id, target_line_ids=[101, 102], disposition="IMPORTED",
            )
            result = reconcile_accounting(
                settings, state, self.contract, run_id,
                {"rows": rows, "boundary": {
                    "native_non_manual_pre_cutoff": 0, "imported_on_or_after_cutoff": 0,
                }},
                {
                    "control_period_id": "00065", "closed_before_cutoff": 1,
                    "eligible_journal_count": 1, "compared_account_branch_count": 2,
                    "raw_closing_mismatch_count": 2,
                    "accepted_hybrid_rollup_count": 2,
                    "accepted_hybrid_rollup_variance": "37880.08",
                    "unsafe_hybrid_account_count": 0,
                    "closing_mismatch_count": 0, "absolute_closing_variance": "0.00",
                },
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["source_ledger_findings"], [])
            self.assertEqual(result["source_ledger_control"]["accepted_hybrid_rollup_count"], 2)

    def test_gate8_fails_closed_for_unproven_hybrid_parent_rollup(self):
        document, action, transaction_id, rows = self.reconciliation_fixture()
        settings = SimpleNamespace(target=SimpleNamespace(fingerprint="target-fingerprint", pg_url=None))
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            state.adopt_accounting_cutoff(document["accounting_cutoff"])
            plan_id = state.save_plan(
                settings.target.fingerprint, BLOCK, "source-fingerprint", self.contract.hash, document,
            )
            run_id = state.start_run(state.plan(plan_id))
            state.record_accounting_item(
                run_id, action["source_key"], "import", action["source_hash"], "succeeded",
                document["plan_hash"], action["planned_hash"], "acct:key", run_id,
                target_transaction_id=transaction_id, target_line_ids=[101, 102], disposition="IMPORTED",
            )
            result = reconcile_accounting(
                settings, state, self.contract, run_id,
                {"rows": rows, "boundary": {
                    "native_non_manual_pre_cutoff": 0, "imported_on_or_after_cutoff": 0,
                }},
                {
                    "control_period_id": "00065", "closed_before_cutoff": 1,
                    "eligible_journal_count": 1, "compared_account_branch_count": 1,
                    "accepted_hybrid_rollup_count": 0,
                    "unsafe_hybrid_account_count": 1,
                    "closing_mismatch_count": 1, "absolute_closing_variance": "1.00",
                },
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["source_ledger_findings"], [
                "SOURCE_HYBRID_ACCOUNT_ROLLUP_UNSAFE",
                "SOURCE_JOURNAL_TO_CNT_MAYOR_CLOSING_DRIFT",
            ])

    def test_gate7_lost_response_retry_reuses_request_identity_and_converges(self):
        source = SourceConfig("source", 1433, "arissto", "reader", "secret", "driver", "", 1, 1)
        target_config = TargetConfig("local", "https://local.test", "user", "secret", "default", None,
                                     "local.test", True)
        settings = SimpleNamespace(source=source, target=target_config)
        cutoff = {
            "date": "2026-01-01", "timezone": "America/El_Salvador", "source": "explicit",
            "configuration_revision": 2, "configuration_hash": "a" * 64, "lifecycle_state": "ACTIVE",
        }
        source_rows = (
            [header()], [line("01", debit="3.00"), line("02", credit="3.00")], [],
            [{"currency_type": "1", "iso_code": "USD", "active_flag": "1", "multicurrency_flag": "0"}],
        )
        target_snapshot = target(tables=[])
        document = plan_accounting_rows(
            source_rows[0], source_rows[1], self.contract, cutoff, source_fingerprint(source),
            target_config.fingerprint, target_snapshot, ["001:001:00065:10"], _hash([]),
        )

        class Api:
            def __init__(self, fail=False):
                self.fail = fail
                self.posts = []

            def request(self, method, path, payload=None, query=None, idempotency_key=None):
                if method == "GET":
                    if path == "scheduler":
                        return {"active": False}
                    return {"cutoffDate": "2026-01-01", "timezoneId": "America/El_Salvador",
                            "configurationRevision": 2, "configurationHash": "a" * 64,
                            "lifecycleState": "ACTIVE"}
                self.posts.append((payload, idempotency_key))
                if self.fail:
                    raise requests.ConnectionError("response lost")
                return {"transactionId": "AI123", "journalEntryIds": [11, 12], "unchanged": True}

        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.sqlite3")
            state.adopt_accounting_cutoff(cutoff)
            plan_id = state.save_plan(target_config.fingerprint, BLOCK, source_fingerprint(source),
                                      self.contract.hash, document)
            first_api = Api(fail=True)
            first_run, first_counts = apply_accounting_plan(
                settings, state, self.contract, plan_id, api=first_api,
                source_rows=source_rows, target_snapshot=target_snapshot,
            )
            self.assertEqual(first_counts["retryable_failures"], 1)
            self.assertEqual(accounting_retry_keys(state, first_run), {"001:001:00065:10"})
            second_api = Api()
            second_run, second_counts = apply_accounting_plan(
                settings, state, self.contract, plan_id, only_keys=accounting_retry_keys(state, first_run),
                retry_from_run=first_run, api=second_api, source_rows=source_rows,
                target_snapshot=target_snapshot,
            )
            self.assertEqual(second_counts["recovered"], 1)
            self.assertEqual(first_api.posts[0][1], second_api.posts[0][1])
            self.assertEqual(first_api.posts[0][0]["runId"], second_api.posts[0][0]["runId"])
            self.assertEqual(state.accounting_attempt(second_run, "001:001:00065:10")["target_line_ids"], [11, 12])


if __name__ == "__main__":
    unittest.main()
