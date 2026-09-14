import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from arissto_sync.cli import parser
from arissto_sync.connections import FineractError
from arissto_sync.cycles import CycleCatalog, workflow_history_across_cycles
from arissto_sync.dte_history import DteApplyControls
from arissto_sync.loans import LoanApplyControls
from arissto_sync.orchestration import (
    FineractResetControls,
    FineractRestartControls,
    _restart_local_fineract,
    _record_child_item_failures,
    assert_zero_pre_cutoff_native_gl,
    assert_scheduler_paused,
    bind_active_accounting_cutoff,
    build_workflow_plan,
    ensure_financial_activity_mappings,
    ensure_arissto_offices,
    ensure_active_accounting_cutoff,
    execute_workflow,
    failure_fingerprint,
    refresh_workflow_run,
    reset_local_fineract,
    verify_active_accounting_cutoff,
)
from arissto_sync.service_runtime import ServiceRuntime
from arissto_sync.state import State, accounting_cutoff_snapshot, now, sync_run_cutoff_date
from arissto_sync.workflow_definitions import inspect_workflow, list_workflows, load_workflow


class FakeRuntime:
    def __init__(
        self, state, target_fingerprint, fail_clients=False, fineract_outages=0,
        wrapped_fineract_outages=0, contract_suffix="",
    ):
        self.state = state
        self.target_fingerprint = target_fingerprint
        self.fail_clients = fail_clients
        self.fineract_outages = fineract_outages
        self.wrapped_fineract_outages = wrapped_fineract_outages
        self.contract_suffix = contract_suffix
        self.prepared = []
        self.planned = []
        self.retried = []

    def contract_hash(self, block):
        return f"contract-{block}{self.contract_suffix}"

    def prepare(self, block):
        self.prepared.append(block)
        return {"performed": False}

    def inspect(self, block):
        if self.fineract_outages:
            self.fineract_outages -= 1
            raise requests.ConnectionError("Fineract is offline")
        return {
            "ready": True,
            "contract_hash": self.contract_hash(block),
            "schema_signature": f"schema-{block}",
        }

    def plan(self, block):
        self.planned.append(block)
        document = {"applicable": True, "actions": []}
        plan_id = self.state.save_plan(
            self.target_fingerprint, block, "source", self.contract_hash(block), document
        )
        return plan_id, document

    def apply(self, block, plan_id, production_confirmation=None):
        plan = self.state.plan(plan_id)
        run_id = self.state.start_run(plan)
        failed = block == "clients" and self.fail_clients
        self.state.record_item(
            run_id, "123", "update", "hash", "failed" if failed else "succeeded",
            error_code="forced-client-failure" if failed else None,
        )
        self.state.finish_run(
            run_id, "completed-with-errors" if failed else "completed",
            {"failed": int(failed), "succeeded": int(not failed)},
        )
        return run_id, {"failed": int(failed), "succeeded": int(not failed)}

    def retry(self, block, previous_run_id, production_confirmation=None):
        self.retried.append(block)
        previous = self.state.run(previous_run_id)
        return self.apply(block, previous["plan_id"], production_confirmation)

    def reconcile(self, block, run_id):
        if self.wrapped_fineract_outages:
            self.wrapped_fineract_outages -= 1
            raise RuntimeError("Service reconciliation could not load its failed run")
        failed = block == "clients" and self.fail_clients
        return {"ok": not failed, "counts": {"mismatched": int(failed)}}


class WorkflowDefinitionTests(unittest.TestCase):
    def test_local_process_control_defaults_use_guarded_gradle_lifecycle(self):
        with patch.dict(os.environ, {
            "ARISSTO_SYNC_FINERACT_STOP_COMMAND": "",
            "ARISSTO_SYNC_FINERACT_RESTART_COMMAND": "",
        }):
            self.assertEqual(
                FineractResetControls.configured().stop_command,
                ("./scripts/local-fineract.sh", "stop"),
            )
            self.assertEqual(
                FineractRestartControls.configured().command,
                ("./scripts/local-fineract.sh", "restart"),
            )

    def test_workflow_cli_carries_explicit_cycle_identity(self):
        created = parser().parse_args([
            "workflow", "cycle", "create", "--cycle", "cycle-a",
            "--baseline-ref", "sandbox@baseline-a", "--target", "local",
        ])
        self.assertEqual(created.cycle, "cycle-a")
        resumed = parser().parse_args([
            "workflow", "plan", "--workflow", "local-full-sync",
            "--include-service", "accounting-journal-entries",
            "--cycle", "cycle-a", "--target", "local",
            "--resume-from-workflow-run", "parent-run",
        ])
        self.assertEqual(resumed.resume_from_workflow_run, "parent-run")
        reset_created = parser().parse_args([
            "workflow", "cycle", "create", "--cycle", "cycle-b",
            "--baseline-ref", "sandbox@baseline-b", "--target", "local",
            "--reset-tenant", "sandbox", "--reset-confirm", "sandbox:fineract_sandbox",
        ])
        self.assertEqual(reset_created.reset_tenant, "sandbox")
        planned = parser().parse_args([
            "workflow", "plan", "--workflow", "local-party-profile",
            "--cycle", "cycle-a", "--target", "local",
        ])
        self.assertEqual(planned.cycle, "cycle-a")

    def test_workflow_cli_accepts_explicit_cutoff_override(self):
        planned = parser().parse_args([
            "workflow", "plan", "--workflow", "local-party-profile",
            "--cycle", "cycle-a", "--target", "local", "--cutoff-date", "2026-09-02",
        ])
        self.assertEqual(planned.cutoff_date, "2026-09-02")

    def test_standalone_plan_cli_accepts_explicit_cutoff_override(self):
        planned = parser().parse_args([
            "plan", "--block", "loans", "--target", "local", "--cutoff-date", "2026-09-02",
        ])
        self.assertEqual(planned.cutoff_date, "2026-09-02")

    def test_sync_run_cutoff_uses_el_salvador_calendar_date(self):
        instant = datetime(2026, 9, 3, 4, 30, tzinfo=timezone.utc)
        self.assertEqual(sync_run_cutoff_date(instant), "2026-09-02")

    def test_cutoff_override_requires_extended_iso_date(self):
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            accounting_cutoff_snapshot("20260902")

    def test_service_runtime_passes_loan_controls_to_engine(self):
        controls = LoanApplyControls(workers=4, pause_seconds=45, recovery_attempts=5)
        runtime = object.__new__(ServiceRuntime)
        runtime.settings = SimpleNamespace()
        runtime.state = SimpleNamespace()
        runtime.loan_controls = controls
        contract = object()
        runtime.contracts = {"loans": contract}

        with patch("arissto_sync.service_runtime.apply_loan_plan", return_value=("run", {})) as apply:
            runtime.apply("loans", "plan")

        apply.assert_called_once_with(
            runtime.settings, runtime.state, contract, "plan", None, controls=controls
        )

    def test_service_runtime_passes_dte_controls_to_engine(self):
        controls = DteApplyControls(workers=4, batch_size=1000)
        runtime = object.__new__(ServiceRuntime)
        runtime.settings = SimpleNamespace()
        runtime.state = SimpleNamespace()
        runtime.loan_controls = None
        runtime.dte_controls = controls
        contract = object()
        runtime.contracts = {"dte-history": contract}

        with patch("arissto_sync.service_runtime.apply_dte_history_plan", return_value=("run", {})) as apply:
            runtime.apply("dte-history", "plan")

        apply.assert_called_once_with(
            runtime.settings, runtime.state, contract, "plan", None, controls=controls
        )

    def test_service_runtime_scopes_accounting_plan_to_frozen_periods(self):
        runtime = object.__new__(ServiceRuntime)
        runtime.settings = SimpleNamespace()
        runtime.state = SimpleNamespace()
        runtime.loan_controls = None
        runtime.dte_controls = None
        runtime.accounting_periods = ("00028",)
        contract = object()
        runtime.contracts = {"accounting-journal-entries": contract}

        with patch(
            "arissto_sync.service_runtime.build_accounting_plan",
            return_value=("plan", {}),
        ) as plan:
            runtime.plan("accounting-journal-entries")

        plan.assert_called_once_with(
            runtime.settings, runtime.state, contract, None,
            source_periods=["00028"], full_scope=False,
        )

        runtime.accounting_periods = ()
        with patch(
            "arissto_sync.service_runtime.build_accounting_plan",
            return_value=("full-plan", {}),
        ) as full_plan:
            runtime.plan("accounting-journal-entries")
        full_plan.assert_called_once_with(
            runtime.settings, runtime.state, contract, None,
            source_periods=[], full_scope=True,
        )

    def test_service_runtime_accounting_retry_accepts_engine_block_identity(self):
        runtime = object.__new__(ServiceRuntime)
        runtime.settings = SimpleNamespace()
        runtime.loan_controls = None
        runtime.dte_controls = None
        runtime.accounting_periods = ("00028",)
        contract = object()
        runtime.contracts = {"accounting-journal-entries": contract}
        runtime.state = SimpleNamespace(
            run=lambda _run_id: {"block": "accounting", "plan_id": "plan-1"},
        )

        with (
            patch("arissto_sync.service_runtime.accounting_retry_keys", return_value={"journal-1"}),
            patch(
                "arissto_sync.service_runtime.apply_accounting_plan",
                return_value=("run-2", {}),
            ) as apply,
        ):
            runtime.retry("accounting-journal-entries", "run-1")

        apply.assert_called_once_with(
            runtime.settings, runtime.state, contract, "plan-1", None,
            {"journal-1"}, retry_from_run="run-1",
        )

    def test_cli_accepts_dte_apply_controls(self):
        args = parser().parse_args([
            "apply", "--target", "local", "--plan", "plan-1",
            "--dte-workers", "4", "--dte-batch-size", "1000",
        ])
        self.assertEqual((args.dte_workers, args.dte_batch_size), (4, 1000))

    def test_service_runtime_reuses_completed_child_for_reconciliation_only_retry(self):
        runtime = object.__new__(ServiceRuntime)
        runtime.settings = SimpleNamespace()
        runtime.contracts = {"clients": object()}
        runtime.state = SimpleNamespace(
            run=lambda _run_id: {
                "block": "clients", "plan_id": "plan-1",
                "summary": {"create": 3},
            },
            run_items=lambda _run_id, failed_only=False: [],
        )

        with patch("arissto_sync.service_runtime.apply_plan") as apply:
            run_id, counts = runtime.retry("clients", "run-1")

        self.assertEqual(run_id, "run-1")
        self.assertEqual(counts, {"create": 3})
        apply.assert_not_called()

    def test_service_runtime_reuses_completed_accounting_child_for_reconciliation_only_retry(self):
        runtime = object.__new__(ServiceRuntime)
        runtime.settings = SimpleNamespace()
        runtime.contracts = {"accounting-journal-entries": object()}
        runtime.state = SimpleNamespace(
            run=lambda _run_id: {
                "block": "accounting", "plan_id": "plan-1",
                "summary": {"reconciled": 13973, "quarantined": 51},
            },
        )

        with (
            patch("arissto_sync.service_runtime.accounting_retry_keys", return_value=set()),
            patch("arissto_sync.service_runtime.apply_accounting_plan") as apply,
        ):
            run_id, counts = runtime.retry("accounting-journal-entries", "run-1")

        self.assertEqual(run_id, "run-1")
        self.assertEqual(counts, {"reconciled": 13973, "quarantined": 51})
        apply.assert_not_called()

    def test_service_runtime_reuses_recovered_loans_child_for_reconciliation_only_retry(self):
        runtime = object.__new__(ServiceRuntime)
        runtime.settings = SimpleNamespace()
        runtime.loan_controls = None
        runtime.contracts = {"loans": object()}
        runtime.state = SimpleNamespace(
            run=lambda _run_id: {
                "block": "loans", "plan_id": "plan-1",
                "summary": {"loans_recovered": 2},
            },
            plan=lambda _plan_id: {"document": {"actions": [{"source_key": "loan:1"}]}},
            plan_run_items=lambda _plan_id: [{"source_key": "loan:1", "status": "recovered"}],
        )

        with patch("arissto_sync.service_runtime.apply_loan_plan") as apply:
            run_id, counts = runtime.retry("loans", "run-1")

        self.assertEqual(run_id, "run-1")
        self.assertEqual(counts, {"loans_recovered": 2})
        apply.assert_not_called()

    def test_ready_workflow_uses_registry_dependencies_and_stable_tie_order(self):
        report = inspect_workflow(load_workflow("local-party-profile"))
        self.assertTrue(report["ready"])
        self.assertEqual(
            report["ordered_services"],
            [
                "clients", "employees", "client-staff-assignments",
                "client-pep", "client-family-references",
            ],
        )
        self.assertEqual(report["warnings"], [])

    def test_credit_workflow_allows_blocked_but_executable_loan_acceptance(self):
        definition = load_workflow("local-credit-collections")
        report = inspect_workflow(definition)
        self.assertTrue(report["ready"])
        self.assertEqual(definition.accounting_cutoff_policy, "activate-frozen-plan")
        self.assertEqual(report["blockers"], [])
        self.assertIn(
            {
                "service_id": "loans",
                "code": "service-unavailable",
                "status": "blocked",
                "allowed_by": "allow-executable",
            },
            report["warnings"],
        )

    def test_accounting_cutoff_is_created_and_activated_idempotently(self):
        api = SimpleNamespace()
        api.request = unittest.mock.MagicMock(side_effect=[
            FineractError(
                "failed (403): error.msg.accounting.cutoff.not.configured", 403
            ),
            {"cutoffDate": "2026-09-02", "timezoneId": "America/El_Salvador",
             "lifecycleState": "DRAFT"},
            {"cutoffDate": "2026-09-02", "timezoneId": "America/El_Salvador",
             "lifecycleState": "ACTIVE", "configurationRevision": 2},
        ])
        active = ensure_active_accounting_cutoff(api, accounting_cutoff_snapshot("2026-09-02"))
        self.assertEqual(active["lifecycleState"], "ACTIVE")
        self.assertEqual(api.request.call_count, 3)

        api.request.reset_mock()
        api.request.side_effect = None
        api.request.return_value = active
        self.assertEqual(
            ensure_active_accounting_cutoff(api, accounting_cutoff_snapshot("2026-09-02")),
            active,
        )
        api.request.assert_called_once_with("GET", "accountingcutoff")

    def test_accounting_cutoff_rejects_mismatched_active_configuration(self):
        api = SimpleNamespace(request=unittest.mock.MagicMock(return_value={
            "cutoffDate": "2026-09-01", "timezoneId": "America/El_Salvador",
            "lifecycleState": "ACTIVE",
        }))
        with self.assertRaisesRegex(RuntimeError, "does not match workflow plan"):
            ensure_active_accounting_cutoff(api, accounting_cutoff_snapshot("2026-09-02"))

    def test_scheduler_pause_is_a_fail_closed_migration_prerequisite(self):
        api = Mock()
        api.request.return_value = {"active": False}
        self.assertEqual(assert_scheduler_paused(api), {"active": False})
        api.request.assert_called_once_with("GET", "scheduler")

        api.request.return_value = {"active": True}
        with self.assertRaisesRegex(RuntimeError, "must be paused"):
            assert_scheduler_paused(api)

    @staticmethod
    def active_cutoff(configuration_hash="cutoff-hash", revision=2):
        return {
            "cutoffDate": "2026-09-02",
            "timezoneId": "America/El_Salvador",
            "lifecycleState": "ACTIVE",
            "configurationRevision": revision,
            "configurationHash": configuration_hash,
        }

    def test_child_cutoff_binding_freezes_active_revision_and_hash(self):
        bound = bind_active_accounting_cutoff(
            accounting_cutoff_snapshot("2026-09-02"), self.active_cutoff()
        )

        self.assertEqual(bound["configuration_revision"], 2)
        self.assertEqual(bound["configuration_hash"], "cutoff-hash")
        self.assertEqual(bound["lifecycle_state"], "ACTIVE")

    def test_bound_child_cutoff_rejects_tenant_configuration_drift(self):
        snapshot = bind_active_accounting_cutoff(
            accounting_cutoff_snapshot("2026-09-02"), self.active_cutoff()
        )
        api = SimpleNamespace(request=unittest.mock.MagicMock(
            return_value=self.active_cutoff("changed-hash", 3)
        ))

        with self.assertRaisesRegex(RuntimeError, "configuration_revision changed"):
            verify_active_accounting_cutoff(api, snapshot)

    def test_shared_pre_cutoff_native_gl_check_is_aggregate_and_fail_closed(self):
        cursor = SimpleNamespace(fetchone=unittest.mock.MagicMock(return_value=(4, 2, date(2026, 8, 1), date(2026, 8, 2))))
        connection = SimpleNamespace(execute=unittest.mock.MagicMock(return_value=cursor))
        manager = unittest.mock.MagicMock()
        manager.__enter__.return_value = connection
        manager.__exit__.return_value = False
        settings = SimpleNamespace(target=SimpleNamespace(pg_url="postgresql://target"))

        with patch("arissto_sync.orchestration.postgres_connection", return_value=manager):
            with self.assertRaisesRegex(RuntimeError, "found 4 native GL entries"):
                assert_zero_pre_cutoff_native_gl(
                    settings, accounting_cutoff_snapshot("2026-09-02")
                )

        sql, params = connection.execute.call_args.args
        self.assertIn("manual_entry=FALSE", sql)
        self.assertNotIn("description", sql.lower())
        self.assertEqual(params, ("2026-09-02",))

    def test_office_bootstrap_creates_missing_branch_and_corrects_root(self):
        api = SimpleNamespace()
        api.offices = unittest.mock.MagicMock(side_effect=[
            [{"id": 1, "name": "Head Office", "externalId": None,
              "openingDate": [2009, 1, 1], "parentId": None}],
            [{"id": 1, "name": "Santiago de María", "externalId": "1",
              "openingDate": [2022, 12, 10], "parentId": None},
             {"id": 2, "name": "Usulutan", "externalId": "2",
              "openingDate": [2024, 11, 27], "parentId": 1}],
        ])
        api.request = unittest.mock.MagicMock(side_effect=[{}, {"officeId": 2}])

        report = ensure_arissto_offices(api)

        self.assertEqual([item["action"] for item in report["actions"]], ["updated", "created"])
        self.assertEqual(api.request.call_args_list[0].args[:2], ("PUT", "offices/1"))
        self.assertEqual(api.request.call_args_list[1].args[:2], ("POST", "offices"))
        self.assertEqual(api.request.call_args_list[0].args[2]["openingDate"], "2022-12-10")
        self.assertEqual(api.request.call_args_list[1].args[2]["openingDate"], "2024-11-27")

    def test_office_bootstrap_is_idempotent_when_offices_are_correct(self):
        offices = [
            {"id": 1, "name": "Santiago de María", "externalId": "1",
             "openingDate": "2022-12-10", "parentId": None},
            {"id": 2, "name": "Usulutan", "externalId": "2",
             "openingDate": "2024-11-27", "parentId": 1},
        ]
        api = SimpleNamespace(
            offices=unittest.mock.MagicMock(side_effect=[offices, offices]),
            request=unittest.mock.MagicMock(),
        )

        report = ensure_arissto_offices(api)

        self.assertEqual([item["action"] for item in report["actions"]], ["unchanged", "unchanged"])
        api.request.assert_not_called()

    def test_office_bootstrap_fails_closed_if_created_id_breaks_contract(self):
        api = SimpleNamespace(
            offices=unittest.mock.MagicMock(return_value=[
                {"id": 1, "name": "Santiago de María", "externalId": "1",
                 "openingDate": "2022-12-10", "parentId": None},
            ]),
            request=unittest.mock.MagicMock(return_value={"officeId": 3}),
        )
        with self.assertRaisesRegex(RuntimeError, "requires office 2"):
            ensure_arissto_offices(api)

    @staticmethod
    def financial_activity_prerequisites():
        return {"financial_activity_mappings": [{
            "required_by_services": ["loans"],
            "financial_activity_id": 100,
            "gl_code": "1510",
            "gl_classification": 1,
            "gl_usage": 1,
        }]}

    @staticmethod
    def transfer_account():
        return {
            "id": 69, "glCode": "1510", "disabled": False,
            "type": {"id": 1}, "usage": {"id": 1},
        }

    def test_financial_activity_prerequisite_creates_and_verifies_missing_mapping(self):
        created = {
            "id": 1,
            "financialActivityData": {"id": 100},
            "glAccountData": {"id": 69, "glCode": "1510"},
        }
        api = SimpleNamespace(request=unittest.mock.MagicMock(side_effect=[
            [self.transfer_account()], [], {"resourceId": 1}, [created],
        ]))

        report = ensure_financial_activity_mappings(
            api, self.financial_activity_prerequisites(), ["clients", "loans"]
        )

        self.assertEqual(report["actions"], [{
            "financial_activity_id": 100, "gl_code": "1510", "action": "created",
        }])
        self.assertEqual(api.request.call_args_list[2].args, (
            "POST", "financialactivityaccounts",
            {"financialActivityId": 100, "glAccountId": 69},
        ))

    def test_financial_activity_prerequisite_is_idempotent(self):
        existing = {
            "id": 1,
            "financialActivityData": {"id": 100},
            "glAccountData": {"id": 69, "glCode": "1510"},
        }
        api = SimpleNamespace(request=unittest.mock.MagicMock(side_effect=[
            [self.transfer_account()], [existing],
        ]))

        report = ensure_financial_activity_mappings(
            api, self.financial_activity_prerequisites(), ["loans"]
        )

        self.assertEqual(report["actions"][0]["action"], "unchanged")
        self.assertEqual(api.request.call_count, 2)

    def test_savings_selection_bootstraps_only_liability_transfer_mapping(self):
        prerequisites = {"financial_activity_mappings": [
            self.financial_activity_prerequisites()["financial_activity_mappings"][0],
            {
                "required_by_services": ["savings-deposits"],
                "financial_activity_id": 200,
                "gl_code": "2130050101",
                "gl_classification": 2,
                "gl_usage": 1,
            },
        ]}
        liability_account = {
            "id": 70, "glCode": "2130050101", "disabled": False,
            "type": {"id": 2}, "usage": {"id": 1},
        }
        created = {
            "id": 2,
            "financialActivityData": {"id": 200},
            "glAccountData": {"id": 70, "glCode": "2130050101"},
        }
        api = SimpleNamespace(request=unittest.mock.MagicMock(side_effect=[
            [self.transfer_account(), liability_account], [], {"resourceId": 2}, [created],
        ]))

        report = ensure_financial_activity_mappings(
            api, prerequisites, ["clients", "savings-deposits"]
        )

        self.assertEqual(report["actions"], [{
            "financial_activity_id": 200, "gl_code": "2130050101", "action": "created",
        }])
        self.assertEqual(api.request.call_args_list[2].args, (
            "POST", "financialactivityaccounts",
            {"financialActivityId": 200, "glAccountId": 70},
        ))

    def test_financial_activity_prerequisite_fails_closed_without_coa(self):
        api = SimpleNamespace(request=unittest.mock.MagicMock(side_effect=[[], []]))
        with self.assertRaisesRegex(RuntimeError, "requires exactly one GL account 1510"):
            ensure_financial_activity_mappings(
                api, self.financial_activity_prerequisites(), ["loans"]
            )

    def test_financial_activity_prerequisite_rejects_conflicting_mapping(self):
        existing = {
            "id": 1,
            "financialActivityData": {"id": 100},
            "glAccountData": {"id": 5, "glCode": "111001"},
        }
        api = SimpleNamespace(request=unittest.mock.MagicMock(side_effect=[
            [self.transfer_account()], [existing],
        ]))
        with self.assertRaisesRegex(RuntimeError, "already mapped to a different GL account"):
            ensure_financial_activity_mappings(
                api, self.financial_activity_prerequisites(), ["loans"]
            )

    def test_financial_activity_prerequisite_is_skipped_without_loans(self):
        api = SimpleNamespace(request=unittest.mock.MagicMock())

        report = ensure_financial_activity_mappings(
            api, self.financial_activity_prerequisites(), ["clients", "employees"]
        )

        self.assertEqual(report, {"performed": False, "actions": []})
        api.request.assert_not_called()

    def test_workflow_catalog_surfaces_ready_and_blocked_definitions(self):
        catalog = {item["id"]: item for item in list_workflows()["workflows"]}
        self.assertTrue(catalog["local-party-profile"]["ready"])
        self.assertTrue(catalog["local-membership-financial"]["ready"])
        self.assertTrue(catalog["local-credit-collections"]["ready"])
        self.assertTrue(catalog["local-full-sync"]["ready"])
        credit_warnings = {
            warning["service_id"] for warning in catalog["local-credit-collections"]["warnings"]
        }
        self.assertEqual(credit_warnings, {"loans", "dte-history"})
        full_warnings = {
            warning["service_id"] for warning in catalog["local-full-sync"]["warnings"]
        }
        self.assertEqual(full_warnings, {"loans", "dte-history", "accounting-journal-entries"})

    def test_allow_executable_policy_never_allows_non_executable_service(self):
        definition = load_workflow("local-credit-collections")
        registry = {
            "services": [
                {
                    "id": service_id,
                    "status": "planned" if service_id == "loans" else "available",
                    "executable": service_id != "loans",
                    "depends_on": [],
                }
                for service_id in definition.services
            ]
        }

        report = inspect_workflow(definition, registry)

        self.assertFalse(report["ready"])
        self.assertIn({"service_id": "loans", "code": "not-executable"}, report["blockers"])

    def test_local_restart_runs_frozen_command_and_waits_for_authenticated_api(self):
        settings = SimpleNamespace(target=SimpleNamespace(name="local"))
        controls = FineractRestartControls(1, 10, 1, ("restart-fineract", "--local"))
        with (
            patch("arissto_sync.orchestration._fineract_api_ready", side_effect=[False, False, True]),
            patch("arissto_sync.orchestration.subprocess.run") as run,
            patch("arissto_sync.orchestration.time.sleep") as sleep,
        ):
            _restart_local_fineract(settings, controls)

        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["restart-fineract", "--local"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        sleep.assert_called_once_with(1)

    def test_guarded_local_reset_stops_restores_and_restarts(self):
        settings = SimpleNamespace(target=SimpleNamespace(
            name="local", tenant="sandbox",
            pg_url="postgresql://postgres@localhost:5432/fineract_sandbox",
        ))
        reset_controls = FineractResetControls(60, ("stop-fineract", "--local"))
        restart_controls = FineractRestartControls(1, 10, 1, ("restart-fineract", "--local"))
        with (
            patch("arissto_sync.orchestration.subprocess.run") as run,
            patch("arissto_sync.orchestration._restart_local_fineract") as restart,
        ):
            report = reset_local_fineract(
                settings, "sandbox", "sandbox:fineract_sandbox",
                reset_controls, restart_controls,
            )

        self.assertEqual(report, {"performed": True, "tenant": "sandbox", "target": "local"})
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], ["stop-fineract", "--local"])
        self.assertEqual(run.call_args_list[1].args[0][1:3], ["reset", "sandbox"])
        restart.assert_called_once_with(settings, restart_controls)

    def test_guarded_local_reset_rejects_default_tenant(self):
        settings = SimpleNamespace(target=SimpleNamespace(
            name="local", tenant="default",
            pg_url="postgresql://postgres@localhost:5432/fineract_default",
        ))
        with self.assertRaisesRegex(ValueError, "non-default"):
            reset_local_fineract(settings, "default", "default:fineract_default")

    def test_guarded_local_reset_rejects_api_and_database_target_mismatch(self):
        settings = SimpleNamespace(target=SimpleNamespace(
            name="local", tenant="default",
            pg_url="postgresql://postgres@localhost:5432/fineract_default",
        ))
        with self.assertRaisesRegex(ValueError, "does not match configured local API tenant"):
            reset_local_fineract(settings, "sandbox", "sandbox:fineract_sandbox")

        settings.target.tenant = "sandbox"
        with self.assertRaisesRegex(ValueError, "must be exactly sandbox:fineract_default"):
            reset_local_fineract(settings, "sandbox", "sandbox:fineract_sandbox")


class WorkflowStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.directory.name) / "state.sqlite3"
        self.state = State(self.state_path)
        self.cycle_id = "cycle-a"
        self.definition = load_workflow("local-party-profile")
        self.settings = SimpleNamespace(
            state_path=self.state_path,
            target=SimpleNamespace(name="local", fingerprint="local-fingerprint"),
        )
        self.state.initialize_cycle(
            self.cycle_id, "local", self.settings.target.fingerprint, "sandbox-baseline-a", now()
        )
        self.office_bootstrap = patch(
            "arissto_sync.orchestration.ensure_arissto_offices",
            return_value={"performed": True, "actions": []},
        )
        self.office_bootstrap.start()

    def tearDown(self):
        self.office_bootstrap.stop()
        self.state.conn.close()
        self.directory.cleanup()

    def create_run(self, runtime_controls=None):
        document = {
            "workflow_id": self.definition.identifier,
            "workflow_version": self.definition.version,
            "definition_hash": self.definition.definition_hash,
            "ordered_services": list(self.definition.services),
            "definition": self.definition.document,
            "target_fingerprint": self.settings.target.fingerprint,
        }
        if runtime_controls is not None:
            document["runtime_controls"] = runtime_controls
        plan_id = self.state.save_workflow_plan(
            self.definition.identifier, self.definition.version,
            self.definition.definition_hash, "local", self.settings.target.fingerprint,
            document,
        )
        return self.state.create_workflow_run(self.state.workflow_plan(plan_id))

    def test_failure_fingerprint_is_stable_and_identity_specific(self):
        first = failure_fingerprint("clients", "apply", "123", "invalid")
        self.assertEqual(first, failure_fingerprint("clients", "apply", "123", "invalid"))
        self.assertNotEqual(first, failure_fingerprint("clients", "apply", "124", "invalid"))

    def test_workflow_uses_frozen_loan_runtime_controls(self):
        controls = {"loans": {"workers": 4, "pause_seconds": 45, "recovery_attempts": 5}}
        run_id = self.create_run({"loans": controls["loans"]})
        runtime = FakeRuntime(self.state, self.settings.target.fingerprint)
        with patch("arissto_sync.orchestration.ServiceRuntime", return_value=runtime) as runtime_type:
            report = execute_workflow(self.settings, self.state, run_id, self.cycle_id)

        self.assertEqual(report["workflow_run"]["status"], "completed")
        event_types = [event["event_type"] for event in report["events"]]
        self.assertEqual(
            [event["sequence"] for event in report["events"]],
            sorted(event["sequence"] for event in report["events"]),
        )
        self.assertIn("workflow-run-created", event_types)
        self.assertIn("workflow-run-started", event_types)
        self.assertIn("workflow-step-phase-changed", event_types)
        self.assertIn("workflow-step-completed", event_types)
        self.assertEqual(event_types[-1], "workflow-run-finished")
        self.assertEqual(runtime.prepared, list(self.definition.services))
        runtime_type.assert_called_once_with(
            self.settings, self.state, LoanApplyControls(workers=4, pause_seconds=45, recovery_attempts=5),
            DteApplyControls(workers=2, batch_size=500), (),
        )

    def test_workflow_plan_freezes_loan_runtime_controls(self):
        controls = LoanApplyControls(workers=4, pause_seconds=45, recovery_attempts=5)
        with patch("arissto_sync.orchestration.preflight", return_value={"ok": True}):
            _plan_id, document = build_workflow_plan(
                self.settings, self.state, self.definition.identifier, self.cycle_id, controls
            )

        self.assertEqual(document["runtime_controls"], {
            "loans": {"workers": 4, "pause_seconds": 45, "recovery_attempts": 5},
            "dte-history": {"workers": 2, "batch_size": 500},
            "fineract_restart": {
                "attempts": 1, "timeout_seconds": 180.0, "poll_seconds": 5.0,
                "command": ["./scripts/local-fineract.sh", "restart"],
            },
        })

    def test_credit_workflow_plan_freezes_allowed_blocked_service_warning(self):
        with patch("arissto_sync.orchestration.preflight", return_value={"ok": True}):
            _plan_id, document = build_workflow_plan(
                self.settings, self.state, "local-credit-collections", self.cycle_id
            )

        self.assertEqual(document["readiness"]["blockers"], [])
        self.assertEqual(
            {warning["service_id"] for warning in document["readiness"]["warnings"]},
            {"loans", "dte-history"},
        )

    def test_full_sync_defaults_to_full_ledger_and_can_freeze_a_period(self):
        with patch("arissto_sync.orchestration.preflight", return_value={"ok": True}):
            _full_plan_id, full_document = build_workflow_plan(
                self.settings, self.state, "local-full-sync", self.cycle_id
            )
            _plan_id, document = build_workflow_plan(
                self.settings, self.state, "local-full-sync", self.cycle_id,
                accounting_periods=["00028"],
            )

        self.assertEqual(
            full_document["runtime_controls"]["accounting-journal-entries"],
            {"scope": "full-company", "source_periods": []},
        )
        self.assertEqual(
            document["runtime_controls"]["accounting-journal-entries"],
            {"scope": "source-periods", "source_periods": ["00028"]},
        )

    def test_selected_workflow_plan_executes_its_frozen_dependency_closure(self):
        with patch("arissto_sync.orchestration.preflight", return_value={"ok": True}):
            plan_id, document = build_workflow_plan(
                self.settings, self.state, "local-credit-collections", self.cycle_id,
                selected_services=["loans"],
            )
        run_id = self.state.create_workflow_run(self.state.workflow_plan(plan_id))
        runtime = FakeRuntime(self.state, self.settings.target.fingerprint)
        with (
            patch("arissto_sync.orchestration.ServiceRuntime", return_value=runtime),
            patch(
                "arissto_sync.orchestration.ensure_financial_activity_mappings",
                return_value={"performed": True, "actions": [{
                    "financial_activity_id": 100, "gl_code": "1510", "action": "unchanged",
                }]},
            ),
            patch("arissto_sync.orchestration.ensure_active_accounting_cutoff", return_value={
                "cutoffDate": document["accounting_cutoff"]["date"],
                "timezoneId": document["accounting_cutoff"]["timezone"],
                "lifecycleState": "ACTIVE",
                "configurationRevision": 2,
                "configurationHash": "cutoff-hash",
            }),
            patch(
                "arissto_sync.orchestration.assert_scheduler_paused",
                return_value={"active": False},
            ),
            patch(
                "arissto_sync.orchestration.verify_active_accounting_cutoff",
                return_value={},
            ) as verify_cutoff,
            patch(
                "arissto_sync.orchestration.assert_zero_pre_cutoff_native_gl",
                return_value={"ok": True, "native_entry_count": 0},
            ) as verify_gl,
        ):
            report = execute_workflow(self.settings, self.state, run_id, self.cycle_id)

        self.assertEqual(report["workflow_run"]["status"], "completed")
        self.assertEqual(
            [step["service_id"] for step in report["steps"]],
            ["clients", "employees", "loans"],
        )
        self.assertTrue(all(step["status"] == "completed" for step in report["steps"]))
        self.assertTrue(any(
            event["event_type"] == "target-prerequisites-ready"
            and event["status"] == "ready"
            for event in report["events"]
        ))
        self.assertEqual(verify_cutoff.call_count, 6)
        self.assertEqual(verify_gl.call_count, 4)
        for step in self.state.workflow_steps(run_id):
            child_cutoff = self.state.plan(step["plan_id"])["document"]["accounting_cutoff"]
            self.assertEqual(child_cutoff["configuration_revision"], 2)
            self.assertEqual(child_cutoff["configuration_hash"], "cutoff-hash")

    def test_resumed_plan_validates_and_skips_reconciled_parent_service(self):
        with patch("arissto_sync.orchestration.preflight", return_value={"ok": True}):
            parent_plan_id, _document = build_workflow_plan(
                self.settings, self.state, "local-party-profile", self.cycle_id,
            )
        parent_run_id = self.state.create_workflow_run(
            self.state.workflow_plan(parent_plan_id)
        )
        client_plan_id = self.state.save_plan(
            self.settings.target.fingerprint, "clients", "source", "contract-clients",
            {"applicable": True, "actions": []},
        )
        child_run_id = self.state.start_run(self.state.plan(client_plan_id))
        self.state.finish_run(child_run_id, "completed", {"succeeded": 1})
        client_step = self.state.workflow_steps(parent_run_id)[0]
        self.state.update_workflow_step(
            client_step["id"], status="completed", phase="completed",
            plan_id=client_plan_id, child_run_id=child_run_id,
            summary={"reconciliation_ok": True}, finish=True,
        )
        self.state.finish_workflow_run(parent_run_id, "failed", {})

        with patch("arissto_sync.orchestration.preflight", return_value={"ok": True}):
            plan_id, document = build_workflow_plan(
                self.settings, self.state, "local-party-profile", self.cycle_id,
                selected_services=["client-pep"], resume_from_run_id=parent_run_id,
            )

        self.assertEqual(document["run_mode"], "resumed")
        self.assertEqual(document["service_actions"], {
            "clients": "validate-and-skip", "client-pep": "continue",
        })
        run_id = self.state.create_workflow_run(self.state.workflow_plan(plan_id))
        runtime = FakeRuntime(self.state, self.settings.target.fingerprint)
        with patch("arissto_sync.orchestration.ServiceRuntime", return_value=runtime):
            report = execute_workflow(self.settings, self.state, run_id, self.cycle_id)

        self.assertEqual(report["workflow_run"]["status"], "completed")
        self.assertEqual(runtime.prepared, ["client-pep"])
        self.assertEqual(runtime.planned, ["client-pep"])
        client_summary = report["steps"][0]["summary"]
        self.assertEqual(client_summary["execution_action"], "validated-and-skipped")

    def test_transient_fineract_outage_restarts_and_retries_service_step(self):
        run_id = self.create_run({
            "fineract_restart": {
                "attempts": 1, "timeout_seconds": 10, "poll_seconds": 1,
                "command": ["test-restart"],
            },
        })
        runtime = FakeRuntime(self.state, self.settings.target.fingerprint, fineract_outages=1)
        with (
            patch("arissto_sync.orchestration.ServiceRuntime", return_value=runtime),
            patch("arissto_sync.orchestration._restart_local_fineract") as restart,
        ):
            report = execute_workflow(self.settings, self.state, run_id, self.cycle_id)

        self.assertEqual(report["workflow_run"]["status"], "completed")
        restart.assert_called_once_with(
            self.settings, FineractRestartControls(1, 10, 1, ("test-restart",))
        )
        client_steps = [step for step in report["steps"] if step["service_id"] == "clients"]
        self.assertEqual([step["status"] for step in client_steps], ["failed", "completed"])
        self.assertEqual(client_steps[-1]["attempt"], 2)
        retry_event = next(
            event for event in report["events"]
            if event["event_type"] == "workflow-step-retry-created"
            and event["service_id"] == "clients"
        )
        self.assertEqual(retry_event["attempt"], 2)
        self.assertTrue(any(
            link["event_id"] == retry_event["id"] and link["relationship"] == "retry-of"
            for link in report["event_links"]
        ))

    def test_legacy_plan_does_not_gain_automatic_restart(self):
        run_id = self.create_run()
        runtime = FakeRuntime(self.state, self.settings.target.fingerprint, fineract_outages=1)
        with (
            patch("arissto_sync.orchestration.ServiceRuntime", return_value=runtime),
            patch("arissto_sync.orchestration._restart_local_fineract") as restart,
        ):
            report = execute_workflow(self.settings, self.state, run_id, self.cycle_id)

        self.assertEqual(report["workflow_run"]["status"], "failed")
        restart.assert_not_called()

    def test_non_connectivity_failure_does_not_restart_fineract(self):
        run_id = self.create_run()
        runtime = FakeRuntime(self.state, self.settings.target.fingerprint, fail_clients=True)
        with (
            patch("arissto_sync.orchestration.ServiceRuntime", return_value=runtime),
            patch("arissto_sync.orchestration._restart_local_fineract") as restart,
        ):
            report = execute_workflow(self.settings, self.state, run_id, self.cycle_id)

        self.assertEqual(report["workflow_run"]["status"], "failed")
        restart.assert_not_called()

    def test_health_probe_recovers_outage_hidden_by_service_summary(self):
        run_id = self.create_run({
            "fineract_restart": {
                "attempts": 1, "timeout_seconds": 10, "poll_seconds": 1,
                "command": ["test-restart"],
            },
        })
        runtime = FakeRuntime(
            self.state, self.settings.target.fingerprint, wrapped_fineract_outages=1,
        )
        with (
            patch("arissto_sync.orchestration.ServiceRuntime", return_value=runtime),
            patch("arissto_sync.orchestration._fineract_api_ready", return_value=False),
            patch("arissto_sync.orchestration._restart_local_fineract") as restart,
        ):
            report = execute_workflow(self.settings, self.state, run_id, self.cycle_id)

        self.assertEqual(report["workflow_run"]["status"], "completed")
        restart.assert_called_once()

    def test_workflow_plan_freezes_explicit_accounting_cutoff(self):
        self.state.set_accounting_cutoff("2026-09-02")
        with patch("arissto_sync.orchestration.preflight", return_value={"ok": True}):
            plan_id, document = build_workflow_plan(
                self.settings, self.state, self.definition.identifier, self.cycle_id
            )

        expected = {
            "date": "2026-09-02", "timezone": "America/El_Salvador", "source": "explicit",
        }
        self.assertEqual(document["accounting_cutoff"], expected)
        self.assertEqual(self.state.workflow_plan(plan_id)["document"]["accounting_cutoff"], expected)

    def test_workflow_children_inherit_frozen_cutoff(self):
        self.state.set_accounting_cutoff("2026-09-02")
        run_id = self.create_run()
        self.state.set_accounting_cutoff("2026-09-03")
        runtime = FakeRuntime(self.state, self.settings.target.fingerprint)

        with patch("arissto_sync.orchestration.ServiceRuntime", return_value=runtime):
            report = execute_workflow(self.settings, self.state, run_id, self.cycle_id)

        self.assertEqual(report["workflow_run"]["status"], "completed")
        for step in self.state.workflow_steps(run_id):
            child_plan = self.state.plan(step["plan_id"])
            self.assertEqual(child_plan["document"]["accounting_cutoff"]["date"], "2026-09-02")

    def test_standalone_plan_freezes_cutoff_in_document(self):
        self.state.set_accounting_cutoff("2026-09-02")
        document = {"applicable": True, "actions": []}
        plan_id = self.state.save_plan(
            self.settings.target.fingerprint, "loans", "source", "contract", document
        )

        self.assertEqual(document["accounting_cutoff"]["date"], "2026-09-02")
        self.assertEqual(self.state.plan(plan_id)["document"]["accounting_cutoff"], document["accounting_cutoff"])

    def test_child_dependency_failures_keep_blocked_loan_lineage(self):
        workflow_run_id = self.create_run()
        step = self.state.workflow_steps(workflow_run_id)[0]
        document = {
            "actions": [
                {"source_key": "loan:1", "depends_on": []},
                {"source_key": "loan:2", "depends_on": ["loan:1"]},
            ],
        }
        child_plan_id = self.state.save_plan(
            self.settings.target.fingerprint, "loans", "source", "contract", document
        )
        child_plan = self.state.plan(child_plan_id)
        child_run_id = self.state.start_run(child_plan)
        self.state.record_item(
            child_run_id, "loan:1", "create-loan", "hash-1", "failed",
            error_code="worker-failure",
        )
        self.state.record_item(
            child_run_id, "loan:2", "create-loan", "hash-2", "blocked",
            error_code="loan_dependency_failed",
        )

        _record_child_item_failures(
            self.state, workflow_run_id, step, child_run_id, document
        )

        failures = {row["source_key"]: row for row in self.state.workflow_failures(workflow_run_id)}
        self.assertEqual(failures["loan:2"]["item_status"], "blocked")
        self.assertIn(
            {
                "failure_id": failures["loan:2"]["id"],
                "related_failure_id": failures["loan:1"]["id"],
                "relationship": "blocked-by",
            },
            self.state.workflow_failure_links(workflow_run_id),
        )

    def test_failed_root_blocks_dependents_but_independent_sibling_completes_and_resume_recovers(self):
        run_id = self.create_run()
        failing_runtime = FakeRuntime(self.state, self.settings.target.fingerprint, fail_clients=True)
        with patch("arissto_sync.orchestration.ServiceRuntime", return_value=failing_runtime):
            report = execute_workflow(self.settings, self.state, run_id, self.cycle_id)

        self.assertEqual(report["workflow_run"]["status"], "failed")
        latest = {step["service_id"]: step for step in report["steps"]}
        self.assertEqual(latest["clients"]["status"], "failed")
        self.assertEqual(latest["client-pep"]["status"], "blocked")
        self.assertEqual(latest["client-family-references"]["status"], "blocked")
        self.assertEqual(latest["employees"]["status"], "completed")
        self.assertTrue(any(failure["source_key"] == "123" for failure in report["failures"]))
        self.assertTrue(any(link["relationship"] == "blocked-by" for link in report["failure_links"]))
        failure_events = {
            event["workflow_failure_id"]: event for event in report["events"]
            if event["workflow_failure_id"]
        }
        blocked_link = next(
            link for link in report["failure_links"] if link["relationship"] == "blocked-by"
        )
        self.assertIn(blocked_link["failure_id"], failure_events)
        self.assertIn(blocked_link["related_failure_id"], failure_events)
        self.assertIn(
            {
                "event_id": failure_events[blocked_link["failure_id"]]["id"],
                "related_event_id": failure_events[blocked_link["related_failure_id"]]["id"],
                "relationship": "blocked-by",
            },
            report["event_links"],
        )

        successful_runtime = FakeRuntime(self.state, self.settings.target.fingerprint)
        with patch("arissto_sync.orchestration.ServiceRuntime", return_value=successful_runtime):
            resumed = execute_workflow(self.settings, self.state, run_id, self.cycle_id)

        self.assertEqual(resumed["workflow_run"]["status"], "completed")
        latest = {}
        for step in resumed["steps"]:
            latest[step["service_id"]] = step
        self.assertTrue(all(step["status"] == "completed" for step in latest.values()))
        self.assertEqual(latest["employees"]["attempt"], 1)
        self.assertEqual(latest["clients"]["attempt"], 2)
        self.assertTrue(any(
            event["event_type"] == "workflow-step-skipped"
            and event["service_id"] == "employees"
            and event["details"]["reason"] == "already-completed"
            for event in resumed["events"]
        ))

        trends = self.state.workflow_failure_trends(self.definition.identifier)
        self.assertTrue(any(
            row["source_key"] == "123" and row["run_count"] == 1 and row["trend"] == "new"
            for row in trends
        ))

    def test_resume_replans_when_service_contract_changed(self):
        run_id = self.create_run()
        failing_runtime = FakeRuntime(self.state, self.settings.target.fingerprint, fail_clients=True)
        with patch("arissto_sync.orchestration.ServiceRuntime", return_value=failing_runtime):
            report = execute_workflow(self.settings, self.state, run_id, self.cycle_id)
        self.assertEqual(report["workflow_run"]["status"], "failed")

        changed_runtime = FakeRuntime(
            self.state, self.settings.target.fingerprint, contract_suffix="-v2"
        )
        with patch("arissto_sync.orchestration.ServiceRuntime", return_value=changed_runtime):
            resumed = execute_workflow(self.settings, self.state, run_id, self.cycle_id)

        self.assertEqual(resumed["workflow_run"]["status"], "completed")
        self.assertIn("clients", changed_runtime.planned)
        self.assertNotIn("clients", changed_runtime.retried)
        self.assertTrue(any(
            event["event_type"] == "workflow-stale-child-plan-discarded"
            and event["service_id"] == "clients"
            for event in resumed["events"]
        ))

    def test_dead_runner_is_marked_interrupted(self):
        run_id = self.create_run()
        self.state.claim_workflow_run(run_id, 99999999)
        run = refresh_workflow_run(self.state, run_id)
        self.assertEqual(run["status"], "interrupted")
        self.assertEqual(run["error_code"], "runner-process-exited")


class SyncCycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base_state = Path(self.directory.name) / "state.sqlite3"
        self.catalog = CycleCatalog(self.base_state)

    def tearDown(self):
        self.catalog.conn.close()
        self.directory.cleanup()

    def test_cycles_get_independent_state_files_and_preserve_baseline_identity(self):
        first = self.catalog.create("first-cycle", "local", "target-a", "sandbox@baseline-1")
        second = self.catalog.create("second-cycle", "local", "target-a", "sandbox@baseline-2")
        self.assertNotEqual(first["state_path"], second["state_path"])
        first_state = State(Path(first["state_path"]))
        second_state = State(Path(second["state_path"]))
        try:
            self.assertEqual(first_state.require_cycle("first-cycle", "target-a")["baseline_ref"],
                             "sandbox@baseline-1")
            self.assertEqual(second_state.require_cycle("second-cycle", "target-a")["baseline_ref"],
                             "sandbox@baseline-2")
            first_state.add_link("target-a", "clients", "123", "55")
            self.assertIsNone(second_state.link("target-a", "clients", "123"))
        finally:
            first_state.conn.close()
            second_state.conn.close()

    def test_duplicate_cycle_is_rejected_and_closed_cycle_cannot_reopen(self):
        self.catalog.create("cycle-a", "local", "target-a", "baseline-a")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.catalog.create("cycle-a", "local", "target-a", "baseline-a")
        closed = self.catalog.close("cycle-a")
        self.assertEqual(closed["status"], "closed")
        with self.assertRaisesRegex(ValueError, "is closed"):
            self.catalog.require_open("cycle-a", "target-a")

    def test_active_workflow_runs_are_found_across_cycles(self):
        cycle = self.catalog.create("cycle-active", "local", "target-a", "baseline-a")
        state = State(Path(cycle["state_path"]))
        try:
            plan_id = state.save_workflow_plan(
                "test-workflow", 1, "definition", "local", "target-a",
                {"ordered_services": []},
            )
            run_id = state.create_workflow_run(state.workflow_plan(plan_id))
        finally:
            state.conn.close()
        self.assertEqual(self.catalog.active_workflow_runs(), [{
            "id": run_id, "workflow_id": "test-workflow", "status": "queued",
            "created_at": self.catalog.active_workflow_runs()[0]["created_at"],
            "cycle_id": "cycle-active",
        }])

    def test_history_compares_same_failure_across_isolated_cycles(self):
        for cycle_id in ("cycle-a", "cycle-b"):
            cycle = self.catalog.create(cycle_id, "local", "target-a", f"baseline-{cycle_id}")
            state = State(Path(cycle["state_path"]))
            try:
                document = {"ordered_services": []}
                plan_id = state.save_workflow_plan(
                    "test-workflow", 1, "definition", "local", "target-a", document
                )
                run_id = state.create_workflow_run(state.workflow_plan(plan_id))
                state.record_workflow_failure(
                    run_id, None, "clients", "apply", "123", "failed", "invalid-client", None,
                    failure_fingerprint("clients", "apply", "123", "invalid-client"),
                )
                state.finish_workflow_run(run_id, "failed", {"failure_count": 1})
            finally:
                state.conn.close()

        report = workflow_history_across_cycles(self.catalog, "test-workflow")
        self.assertEqual(len(report["cycles"]), 2)
        self.assertEqual(report["failure_trends"][0]["cycle_count"], 2)
        self.assertEqual(report["failure_trends"][0]["run_count"], 2)
        self.assertEqual(report["failure_trends"][0]["trend"], "recurring")


if __name__ == "__main__":
    unittest.main()
