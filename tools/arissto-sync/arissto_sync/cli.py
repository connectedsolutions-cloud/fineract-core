from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .aml_alerts import (
    BLOCK as AML_ALERT_BLOCK,
    AmlAlertContract,
    apply_aml_alert_plan,
    build_aml_alert_plan,
    inspect_aml_alerts,
    reconcile_aml_alerts,
)
from .accounting import (
    BLOCK as ACCOUNTING_BLOCK,
    AccountingContract,
    accounting_retry_keys,
    accounting_status,
    apply_accounting_plan,
    build_accounting_plan,
    inspect_accounting,
    reconcile_accounting,
)
from .accounting_report_proof import prove_accounting_reports
from .accounting_g10_acceptance import prove_g10
from .clients import ClientContract
from .client_staff_assignments import (
    BLOCK as CLIENT_STAFF_ASSIGNMENT_BLOCK,
    ClientStaffAssignmentContract,
    apply_client_staff_assignment_plan,
    build_client_staff_assignment_plan,
    inspect_client_staff_assignments,
    reconcile_client_staff_assignments,
)
from .arissto import check_source
from .config import ROOT, configured_state_path, load_settings, load_source_config
from .connections import FineractApi
from .cycles import CycleCatalog, settings_for_cycle, workflow_history_across_cycles
from .engine import apply_plan, build_plan, inspect_clients, preflight, reconcile
from .employees import (
    BLOCK as EMPLOYEE_BLOCK,
    EmployeeContract,
    apply_employee_plan,
    build_employee_plan,
    inspect_employees,
    reconcile_employees,
)
from .dte_history import (
    BLOCK as DTE_HISTORY_BLOCK,
    DEFAULT_DTE_BATCH_SIZE,
    DEFAULT_DTE_WORKERS,
    MAX_DTE_BATCH_SIZE,
    MAX_DTE_WORKERS,
    DteApplyControls,
    DteHistoryContract,
    apply_dte_history_plan,
    build_dte_history_plan,
    inspect_dte_history,
    reconcile_dte_history,
)
from .family_references import (
    BLOCK as FAMILY_REFERENCES_BLOCK,
    FamilyReferenceContract,
    apply_family_reference_plan,
    build_family_reference_plan,
    inspect_family_references,
    reconcile_family_references,
)
from .pep import BLOCK as PEP_BLOCK, PepContract, apply_pep_plan, build_pep_plan, inspect_pep, reconcile_pep
from .membership import (
    BLOCK as MEMBERSHIP_BLOCK,
    MembershipContract,
    apply_membership_plan,
    build_membership_plan,
    inspect_membership,
    reconcile_membership,
)
from .mobile_collections import (
    BLOCK as MOBILE_COLLECTION_BLOCK,
    MobileCollectionContract,
    apply_mobile_collection_plan,
    build_mobile_collection_plan,
    inspect_mobile_collections,
    reconcile_mobile_collections,
)
from .native_shares import BLOCK as NATIVE_SHARES_BLOCK, NativeShareContract, inspect_native_shares
from .native_share_engine import apply_native_share_plan, build_native_share_plan, reconcile_native_shares
from .loans import (
    BLOCK as LOANS_BLOCK,
    CLOSED_REFINANCE_HISTORICAL_SCHEDULE_LOANS,
    DEFAULT_FINERACT_PAUSE_SECONDS,
    DEFAULT_FINERACT_RECOVERY_ATTEMPTS,
    DEFAULT_LOAN_WORKERS,
    MAX_LOAN_WORKERS,
    LoanApplyControls,
    LoanContract,
    apply_loan_plan,
    build_loan_plan,
    inspect_loans,
    loan_retry_keys,
    compact_loan_reconciliation_report,
    reconcile_loans,
)
from .loan_schedule_proof import prove_schedule
from .loan_debug import debug_loan_run
from .loan_reference_canary import (
    verify_adjusted_schedule_cohort,
    verify_closed_refinance_historical_canary,
    verify_contractual_anchor_cohort,
)
from .orchestration import (
    FineractRestartControls,
    build_workflow_plan,
    execute_workflow,
    inspect_local_workflow,
    resume_workflow,
    reset_local_fineract,
    start_workflow,
    stop_workflow,
    workflow_report,
    bind_active_accounting_cutoff,
)
from .service_registry import service_report
from .retention import APPLY_CONFIRMATION, apply_retention, retention_plan
from .savings import BLOCK as SAVINGS_BLOCK, SavingsContract, inspect_savings
from .savings_engine import apply_savings_plan, build_savings_plan, reconcile_savings
from .savings_lifecycle_proof import prove_vista_lifecycle
from .fixed_deposit_lifecycle_proof import prove_dpf_lifecycle
from .state import State
from .storage_health import storage_health
from .workflows import apply_clients_with_family_references, apply_clients_with_pep
from .workflow_definitions import list_workflows


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="arissto-sync", description="Local Arissto to Fineract synchronization CLI")
    root.add_argument("--env-file")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("source-check", help="test only the read-only Arissto connection")
    health = commands.add_parser("health", help="inspect local sync-state and workflow-log storage")
    health.add_argument("--max-total-mb", type=int, default=1024)
    health.add_argument("--max-run-log-mb", type=int, default=50)
    health.add_argument("--stale-open-days", type=int, default=2)
    retention = commands.add_parser("retention", help="plan or apply guarded sync-state retention")
    retention_commands = retention.add_subparsers(dest="retention_command", required=True)
    retention_plan_command = retention_commands.add_parser("plan", help="preview retention actions")
    retention_apply_command = retention_commands.add_parser("apply", help="apply the current retention plan")
    for retention_command in (retention_plan_command, retention_apply_command):
        retention_command.add_argument("--scope", choices=("all", "local", "prod"), default="all")
        retention_command.add_argument(
            "--prod-fingerprint", action="append", dest="production_fingerprints",
            help="include an explicit production target fingerprint; repeat as needed",
        )
    retention_apply_command.add_argument(
        "--confirm", required=True, help=f"must be exactly {APPLY_CONFIRMATION}",
    )
    schedule_proof = commands.add_parser(
        "prove-loan-schedule", help="compare one Arissto schedule with Fineract's non-posting calculator"
    )
    schedule_proof.add_argument("--target", choices=("local",), required=True)
    schedule_proof.add_argument("--source-key", type=int, required=True)
    schedule_proof.add_argument("--product-id", type=int, required=True)
    schedule_proof.add_argument("--client-id", type=int, required=True)
    accounting_report_proof = commands.add_parser(
        "prove-accounting-reports",
        help="compare native dimension-aware reports with independent Arissto journal rollups",
    )
    accounting_report_proof.add_argument("--target", choices=("local",), required=True)
    accounting_report_proof.add_argument("--from-date", required=True)
    accounting_report_proof.add_argument("--to-date", required=True)
    accounting_g10_proof = commands.add_parser(
        "prove-accounting-g10", help="verify the scoped Gate 10 canary matrix against the local sandbox",
    )
    accounting_g10_proof.add_argument("--target", choices=("local",), required=True)
    accounting_g10_proof.add_argument("--cutoff-date", required=True)
    accounting_g10_proof.add_argument("--native-reference", default="G10-CUTOFF-20260910")
    vista_proof = commands.add_parser(
        "prove-vista-lifecycle", help="prove one isolated Arissto VISTA lifecycle using native Fineract commands"
    )
    vista_proof.add_argument("--target", choices=("local",), required=True)
    vista_proof.add_argument("--source-key", required=True, help="COMPANY:BRANCH:ACCOUNT, for example 001:001:0000000100")
    vista_proof.add_argument("--execute", action="store_true", help="create and replay the proof on the local target")
    vista_proof.add_argument("--reconcile-existing", action="store_true",
                             help="read and reconcile an existing proof account without replaying events")
    dpf_proof = commands.add_parser(
        "prove-dpf-lifecycle", help="prove one Arissto fixed-deposit lifecycle using native Fineract commands"
    )
    dpf_proof.add_argument("--target", choices=("local",), required=True)
    dpf_proof.add_argument("--source-key", required=True, help="COMPANY:BRANCH:ACCOUNT")
    dpf_proof.add_argument("--execute", action="store_true")
    services = commands.add_parser("services", help="list registered migration services")
    services.add_argument("--service", help="show one migration service by stable ID")
    workflow = commands.add_parser("workflow", help="run dependency-driven local sync workflows")
    workflow_commands = workflow.add_subparsers(dest="workflow_command", required=True)
    workflow_commands.add_parser("list", help="list local workflow definitions and readiness")
    workflow_cycle = workflow_commands.add_parser("cycle", help="manage isolated local SQLite sync cycles")
    cycle_commands = workflow_cycle.add_subparsers(dest="cycle_command", required=True)
    cycle_commands.add_parser("list", help="list preserved local sync cycles")
    cycle_create = cycle_commands.add_parser("create", help="create a fresh isolated SQLite state cycle")
    cycle_create.add_argument("--cycle", required=True)
    cycle_create.add_argument("--baseline-ref", required=True)
    cycle_create.add_argument("--note")
    cycle_create.add_argument("--target", choices=("local",), required=True)
    cycle_create.add_argument(
        "--reset-tenant",
        help="restore this disposable local tenant baseline before creating the cycle",
    )
    cycle_create.add_argument(
        "--reset-confirm",
        help="exact TENANT:DATABASE confirmation required by the local reset tool",
    )
    cycle_show = cycle_commands.add_parser("show", help="show one sync cycle and its state location")
    cycle_show.add_argument("--cycle", required=True)
    cycle_close = cycle_commands.add_parser("close", help="close a cycle against new workflow plans")
    cycle_close.add_argument("--cycle", required=True)
    workflow_inspect = workflow_commands.add_parser("inspect", help="validate a workflow definition and registry graph")
    workflow_inspect.add_argument("--workflow", required=True)
    workflow_plan = workflow_commands.add_parser("plan", help="preflight and save an immutable local workflow plan")
    workflow_plan.add_argument("--workflow", required=True)
    workflow_plan.add_argument(
        "--include-service", action="append", dest="included_services",
        help="include one service and its prerequisites; repeat to select more services",
    )
    workflow_plan.add_argument("--cycle", required=True)
    workflow_plan.add_argument("--target", choices=("local",), required=True)
    workflow_plan.add_argument("--cutoff-date", help="accounting cutoff in YYYY-MM-DD; defaults to the sync-run date")
    workflow_plan.add_argument(
        "--accounting-period", action="append", dest="accounting_periods",
        help="reviewed accounting source period; repeat to include more than one",
    )
    workflow_plan.add_argument(
        "--resume-from-workflow-run",
        help=("continue in the same cycle while validating and skipping services "
              "already reconciled by this completed or incomplete workflow run"),
    )
    workflow_start = workflow_commands.add_parser("start", help="start a planned workflow in a detached local process")
    workflow_start.add_argument("--workflow-plan", required=True)
    workflow_start.add_argument("--cycle", required=True)
    workflow_start.add_argument("--target", choices=("local",), required=True)
    workflow_execute = workflow_commands.add_parser("execute", help="internal detached workflow executor")
    workflow_execute.add_argument("--workflow-run", "--run", dest="workflow_run", required=True)
    workflow_execute.add_argument("--cycle", required=True)
    workflow_execute.add_argument("--target", choices=("local",), required=True)
    workflow_status = workflow_commands.add_parser("status", help="show durable workflow, step, and failure state")
    workflow_status.add_argument("--workflow-run", required=True)
    workflow_status.add_argument("--cycle", required=True)
    workflow_status.add_argument("--target", choices=("local",), required=True)
    workflow_resume = workflow_commands.add_parser("resume", help="resume failed or interrupted steps")
    workflow_resume.add_argument("--workflow-run", required=True)
    workflow_resume.add_argument("--cycle", required=True)
    workflow_resume.add_argument("--target", choices=("local",), required=True)
    workflow_stop = workflow_commands.add_parser("stop", help="request termination of a running local workflow")
    workflow_stop.add_argument("--workflow-run", required=True)
    workflow_stop.add_argument("--cycle", required=True)
    workflow_stop.add_argument("--target", choices=("local",), required=True)
    workflow_history = workflow_commands.add_parser("history", help="compare workflow runs and recurring failures")
    workflow_history.add_argument("--workflow", required=True)
    workflow_history.add_argument("--cycle", help="limit history to one cycle; omit to compare all cycles")
    workflow_history.add_argument("--target", choices=("local",), required=True)
    for name in ("preflight", "inspect", "plan", "status"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--target", choices=("local", "prod"), required=name != "inspect")
        if name in {"inspect", "plan"}:
            block_choices = (
                "clients", PEP_BLOCK, FAMILY_REFERENCES_BLOCK, EMPLOYEE_BLOCK, CLIENT_STAFF_ASSIGNMENT_BLOCK,
                MEMBERSHIP_BLOCK, AML_ALERT_BLOCK, SAVINGS_BLOCK, LOANS_BLOCK, MOBILE_COLLECTION_BLOCK,
                NATIVE_SHARES_BLOCK, DTE_HISTORY_BLOCK,
            )
            if name in {"inspect", "plan"}:
                block_choices = (*block_choices, ACCOUNTING_BLOCK)
            cmd.add_argument(
                "--block",
                choices=block_choices,
                required=True,
            )
        if name == "inspect":
            cmd.add_argument("--source-key", help="inspect one exact source key when the selected block supports it")
            cmd.add_argument("--cutoff-date", help="accounting cutoff in YYYY-MM-DD (required for accounting)")
        if name == "plan":
            cmd.add_argument("--cutoff-date", help="accounting cutoff in YYYY-MM-DD; defaults to the sync-run date")
            cmd.add_argument("--source-key", action="append",
                             help="scope the plan to an exact source key for the selected block; repeat as needed")
            cmd.add_argument(
                "--period", action="append",
                help="accounting only: scope to every journal header in one source period; repeat as needed",
            )
            cmd.add_argument(
                "--proof-namespace",
                help="local loans only: create fresh namespaced loan/transaction identities for a controlled proof",
            )
            cmd.add_argument(
                "--repair-existing-drift", action="store_true",
                help="local savings only: explicitly plan repair of known mapped/native drift",
            )
        if name == "status":
            cmd.add_argument(
                "--block",
                choices=("clients", PEP_BLOCK, FAMILY_REFERENCES_BLOCK, EMPLOYEE_BLOCK, CLIENT_STAFF_ASSIGNMENT_BLOCK,
                         MEMBERSHIP_BLOCK, SAVINGS_BLOCK, AML_ALERT_BLOCK, LOANS_BLOCK, MOBILE_COLLECTION_BLOCK,
                         NATIVE_SHARES_BLOCK, DTE_HISTORY_BLOCK, ACCOUNTING_BLOCK),
            )
    apply = commands.add_parser("apply")
    apply.add_argument("--target", choices=("local", "prod"), required=True)
    apply.add_argument("--plan", required=True)
    apply.add_argument("--confirm-production")
    chained = apply.add_mutually_exclusive_group()
    chained.add_argument("--with-pep", action="store_true",
                         help="after successful client reconciliation, sync PEP for those client source keys")
    chained.add_argument("--with-family-references", action="store_true",
                         help="after successful client reconciliation, sync references for those client source keys")
    rec = commands.add_parser("reconcile")
    rec.add_argument("--target", choices=("local", "prod"), required=True)
    rec.add_argument("--run", required=True)
    rec.add_argument("--report", help="write a compact grouped loan reconciliation JSON artifact")
    rec.add_argument("--sample-limit", type=int, default=3,
                     help="representative findings retained per report group (default: 3)")
    retry = commands.add_parser("retry")
    retry.add_argument("--target", choices=("local", "prod"), required=True)
    retry.add_argument("--run", required=True)
    retry.add_argument("--failed-only", action="store_true", required=True)
    retry.add_argument("--confirm-production")
    for command in (apply, retry, workflow_plan):
        command.add_argument(
            "--loan-workers", type=int,
            help=(f"parallel loan lifecycles (default: {DEFAULT_LOAN_WORKERS}; "
                  f"maximum: {MAX_LOAN_WORKERS})"),
        )
        command.add_argument(
            "--fineract-pause-seconds", type=float,
            help=("shared worker pause after a transient Fineract failure "
                  f"(default: {DEFAULT_FINERACT_PAUSE_SECONDS:g})"),
        )
        command.add_argument(
            "--fineract-recovery-attempts", type=int,
            help=("whole-loan attempts after transient Fineract failures "
                  f"(default: {DEFAULT_FINERACT_RECOVERY_ATTEMPTS})"),
        )
        command.add_argument(
            "--dte-workers", type=int,
            help=(f"parallel DTE batches (default: {DEFAULT_DTE_WORKERS}; "
                  f"maximum: {MAX_DTE_WORKERS})"),
        )
        command.add_argument(
            "--dte-batch-size", type=int,
            help=(f"DTE aggregates committed per batch (default: {DEFAULT_DTE_BATCH_SIZE}; "
                  f"maximum: {MAX_DTE_BATCH_SIZE})"),
        )
    workflow_plan.add_argument(
        "--fineract-restart-attempts", type=int,
        help="automatic local Fineract restarts per workflow (default: 1; 0 disables)",
    )
    workflow_plan.add_argument(
        "--fineract-restart-timeout-seconds", type=float,
        help="seconds allowed for the restart command and subsequent API readiness (default: 180)",
    )
    workflow_plan.add_argument(
        "--fineract-restart-poll-seconds", type=float,
        help="API readiness polling interval after a local Fineract restart (default: 5)",
    )
    debug_loans = commands.add_parser(
        "debug-loans",
        help="build a read-only event-level report for a completed local loans run",
    )
    debug_loans.add_argument("--target", choices=("local",), required=True)
    debug_loans.add_argument("--run", required=True)
    debug_loans.add_argument(
        "--source-key", action="append",
        help="limit the report to one loan source key; repeat as needed (accepts 123 or loan:123)",
    )
    debug_loans.add_argument("--include-clean", action="store_true")
    debug_loans.add_argument("--report", help="write the full JSON report to this path")
    reference_canary = commands.add_parser(
        "check-loan-reference-canary",
        help="verify the reviewed 20 historical-reference roots and their 57 descendants",
    )
    reference_canary.add_argument("--target", choices=("local",), required=True)
    reference_canary.add_argument("--plan", required=True)
    reference_canary.add_argument(
        "--run", help="also reconcile and verify the completed canary run",
    )
    reference_canary_plan = commands.add_parser(
        "plan-loan-reference-canary",
        help="build the dependency-expanded 20-root/57-descendant loans canary plan",
    )
    reference_canary_plan.add_argument("--target", choices=("local",), required=True)
    reference_canary_plan.add_argument("--proof-namespace", required=True)
    contractual_anchor = commands.add_parser(
        "check-loan-contractual-anchor-cohort",
        help="verify G5-SCH-008 from the contractual-anchor classifier in a full loans plan",
    )
    contractual_anchor.add_argument("--target", choices=("local",), required=True)
    contractual_anchor.add_argument("--cycle", help="read the plan and runs from this sync cycle")
    contractual_anchor.add_argument("--plan", required=True)
    contractual_anchor.add_argument("--run")
    contractual_anchor.add_argument("--replay-run")
    adjusted_schedule = commands.add_parser(
        "check-loan-adjusted-schedule-cohort",
        help="verify the nine G5-SCH-009 manually adjusted schedules",
    )
    adjusted_schedule.add_argument("--target", choices=("local",), required=True)
    adjusted_schedule.add_argument("--cycle", help="read the plan and runs from this sync cycle")
    adjusted_schedule.add_argument("--plan", required=True)
    adjusted_schedule.add_argument("--run")
    adjusted_schedule.add_argument("--replay-run")
    link = commands.add_parser("link")
    link.add_argument("--target", choices=("local", "prod"), required=True)
    link.add_argument("--block", choices=("clients",), required=True)
    link.add_argument("--source-key", required=True)
    link.add_argument("--target-id", required=True)
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "source-check":
            emit(check_source(load_source_config(args.env_file)))
            return 0
        if args.command == "health":
            report = storage_health(
                configured_state_path(args.env_file),
                max_total_bytes=args.max_total_mb * 1024 * 1024,
                max_run_log_bytes=args.max_run_log_mb * 1024 * 1024,
                stale_open_days=args.stale_open_days,
            )
            emit(report)
            return 0 if report["ok"] else 2
        if args.command == "retention":
            state_path = configured_state_path(args.env_file)
            if args.retention_command == "plan":
                emit(retention_plan(
                    state_path, scope=args.scope,
                    production_fingerprints=args.production_fingerprints,
                ))
            else:
                emit(apply_retention(
                    state_path, confirmation=args.confirm, scope=args.scope,
                    production_fingerprints=args.production_fingerprints,
                ))
            return 0
        if args.command == "services":
            emit(service_report(args.service))
            return 0
        if args.command == "workflow" and args.workflow_command == "inspect":
            report = inspect_local_workflow(args.workflow)
            emit(report)
            return 0 if report["ready"] else 2
        if args.command == "workflow" and args.workflow_command == "list":
            emit(list_workflows())
            return 0
        if args.command == "workflow" and args.workflow_command == "cycle" and args.cycle_command != "create":
            catalog = CycleCatalog(configured_state_path(args.env_file))
            if args.cycle_command == "list":
                emit({"cycles": catalog.list()})
            elif args.cycle_command == "show":
                emit(catalog.get(args.cycle))
            elif args.cycle_command == "close":
                emit(catalog.close(args.cycle))
            return 0
        if args.command == "prove-loan-schedule":
            report = prove_schedule(
                load_settings(args.target, args.env_file), args.source_key, args.product_id, args.client_id
            )
            emit(report)
            return 0 if report["accepted"] else 2
        if args.command == "prove-accounting-reports":
            settings = load_settings(args.target, args.env_file)
            contract = AccountingContract.load(ROOT / "config/accounting.json")
            report = prove_accounting_reports(
                settings, contract, date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)
            )
            emit(report)
            return 0 if report["accepted"] else 2
        if args.command == "prove-accounting-g10":
            settings = load_settings(args.target, args.env_file)
            report = prove_g10(
                settings, AccountingContract.load(ROOT / "config/accounting.json"), State(settings.state_path),
                args.cutoff_date, args.native_reference,
            )
            emit(report)
            return 0 if report["accepted"] else 2
        if args.command == "prove-vista-lifecycle":
            settings = load_settings(args.target, args.env_file)
            contract = SavingsContract.load(settings.savings_mapping_path)
            if args.execute and args.reconcile_existing:
                raise ValueError("Choose either --execute or --reconcile-existing")
            report = prove_vista_lifecycle(settings, contract, args.source_key, args.execute, args.reconcile_existing)
            emit(report)
            return 0 if (report["accepted"] if args.execute or args.reconcile_existing else report["ready_to_execute"]) else 2
        if args.command == "prove-dpf-lifecycle":
            settings = load_settings(args.target, args.env_file)
            contract = SavingsContract.load(settings.savings_mapping_path)
            report = prove_dpf_lifecycle(settings, contract, args.source_key, args.execute)
            emit(report)
            return 0 if (report["accepted"] if args.execute else report["ready_to_execute"]) else 2
        if args.command == "inspect" and args.block == LOANS_BLOCK:
            contract = LoanContract.load(ROOT / "config/loans.json")
            if args.target:
                loan_settings = load_settings(args.target, args.env_file)
                emit(inspect_loans(
                    loan_settings.source, contract, args.source_key, loan_settings.target.pg_url
                ))
            else:
                emit(inspect_loans(load_source_config(args.env_file), contract, args.source_key))
            return 0
        if args.command == "inspect" and args.block == ACCOUNTING_BLOCK:
            if not args.cutoff_date:
                raise ValueError("--cutoff-date is required for inspect --block accounting")
            contract = AccountingContract.load(ROOT / "config/accounting.json")
            if args.target:
                accounting_settings = load_settings(args.target, args.env_file)
                report = inspect_accounting(
                    accounting_settings.source, contract, args.cutoff_date, args.source_key,
                    accounting_settings.target.pg_url,
                )
                state = State(accounting_settings.state_path)
                state.save_inspection(
                    accounting_settings.target.name, accounting_settings.target.fingerprint, ACCOUNTING_BLOCK,
                    report["contract_hash"], report["schema_signature"], report["ready"],
                )
            else:
                report = inspect_accounting(
                    load_source_config(args.env_file), contract, args.cutoff_date, args.source_key,
                )
            emit(report)
            return 0 if report["ready"] else 2
        if not args.target:
            raise ValueError(f"--target is required for {args.command} --block {getattr(args, 'block', '')}".strip())
        settings = load_settings(args.target, args.env_file)
        if args.command in {
            "check-loan-contractual-anchor-cohort",
            "check-loan-adjusted-schedule-cohort",
        } and args.cycle:
            catalog = CycleCatalog(settings.state_path)
            cycle = catalog.get(args.cycle)
            settings = settings_for_cycle(settings, cycle)
        if args.command == "workflow":
            catalog = CycleCatalog(settings.state_path)
            if args.workflow_command == "cycle" and args.cycle_command == "create":
                if bool(args.reset_tenant) != bool(args.reset_confirm):
                    raise ValueError("--reset-tenant and --reset-confirm must be supplied together")
                active = catalog.active_workflow_runs()
                if active:
                    raise ValueError("Cannot replace the local cycle while a workflow is queued or running")
                reset = None
                if args.reset_tenant:
                    reset = reset_local_fineract(
                        settings, args.reset_tenant, args.reset_confirm,
                    )
                cycle = catalog.create(
                    args.cycle, settings.target.name, settings.target.fingerprint,
                    args.baseline_ref, args.note,
                )
                catalog.conn.close()
                retention = apply_retention(
                    settings.state_path, confirmation=APPLY_CONFIRMATION, scope="local",
                )
                emit({**cycle, "target_reset": reset, "retention": retention})
                return 0
            if args.workflow_command == "history" and not args.cycle:
                emit(workflow_history_across_cycles(catalog, args.workflow))
                return 0
            cycle = (
                catalog.require_open(args.cycle, settings.target.fingerprint)
                if args.workflow_command in {"plan", "start", "execute", "resume", "stop"}
                else catalog.get(args.cycle)
            )
            settings = settings_for_cycle(settings, cycle)
            state = State(settings.state_path)
            if args.workflow_command == "plan" and args.cutoff_date:
                state.set_accounting_cutoff(args.cutoff_date)
            state.require_cycle(args.cycle, cycle["target_fingerprint"])
            if args.workflow_command == "plan":
                plan_id, document = build_workflow_plan(
                    settings, state, args.workflow, args.cycle,
                    LoanApplyControls.configured(
                        args.loan_workers, args.fineract_pause_seconds, args.fineract_recovery_attempts
                    ),
                    FineractRestartControls.configured(
                        args.fineract_restart_attempts, args.fineract_restart_timeout_seconds,
                        args.fineract_restart_poll_seconds,
                    ),
                    selected_services=args.included_services,
                    dte_controls=DteApplyControls.configured(args.dte_workers, args.dte_batch_size),
                    accounting_periods=args.accounting_periods,
                    resume_from_run_id=args.resume_from_workflow_run,
                )
                emit({"workflow_plan_id": plan_id, **document})
            elif args.workflow_command == "start":
                emit(start_workflow(settings, state, args.workflow_plan, args.cycle, args.env_file))
            elif args.workflow_command == "execute":
                report = execute_workflow(settings, state, args.workflow_run, args.cycle)
                emit(report)
                return 0 if report["workflow_run"]["status"] == "completed" else 2
            elif args.workflow_command == "status":
                emit(workflow_report(state, args.workflow_run))
            elif args.workflow_command == "resume":
                emit(resume_workflow(settings, state, args.workflow_run, args.cycle, args.env_file))
            elif args.workflow_command == "stop":
                emit(stop_workflow(state, args.workflow_run))
            elif args.workflow_command == "history":
                emit({
                    "workflow_id": args.workflow,
                    "runs": state.workflow_history(args.workflow),
                    "failure_trends": state.workflow_failure_trends(args.workflow),
                })
            return 0
        state = State(settings.state_path)
        if args.command == "plan" and args.cutoff_date:
            state.set_accounting_cutoff(args.cutoff_date)
        client_contract = ClientContract.load(settings.mapping_path)
        family_contract = FamilyReferenceContract.load(settings.family_reference_mapping_path)
        pep_contract = PepContract.load(settings.pep_mapping_path)
        employee_contract = EmployeeContract.load(settings.employee_mapping_path)
        client_staff_assignment_contract = ClientStaffAssignmentContract.load(
            settings.client_staff_assignment_mapping_path
        )
        membership_contract = MembershipContract.load(settings.membership_mapping_path)
        native_share_contract = NativeShareContract.load(settings.native_share_mapping_path)
        aml_alert_contract = AmlAlertContract.load(settings.aml_alert_mapping_path)
        savings_contract = SavingsContract.load(settings.savings_mapping_path)
        loan_contract = LoanContract.load(ROOT / "config/loans.json")
        mobile_collection_contract = MobileCollectionContract.load(settings.mobile_collection_mapping_path)
        dte_history_contract = DteHistoryContract.load(settings.dte_history_mapping_path)
        if args.command == "debug-loans":
            source_keys = {
                value if value.startswith("loan:") else f"loan:{value}"
                for value in (args.source_key or [])
            }
            report = debug_loan_run(
                settings, state, loan_contract, args.run, source_keys or None, args.include_clean,
            )
            if args.report:
                report_path = Path(args.report).expanduser().resolve()
                if not report_path.parent.is_dir():
                    raise ValueError(f"Report parent directory does not exist: {report_path.parent}")
                report_path.write_text(
                    json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8",
                )
                emit({
                    "report": str(report_path),
                    "affected_loan_count": report["affected_loan_count"],
                    "mismatch_counts": report["mismatch_counts"],
                    "suggested_disposition_counts": report["suggested_disposition_counts"],
                })
            else:
                emit(report)
        elif args.command == "plan-loan-reference-canary":
            plan_id, document = build_loan_plan(
                settings,
                state,
                loan_contract,
                [str(loan_id) for loan_id in CLOSED_REFINANCE_HISTORICAL_SCHEDULE_LOANS],
                args.proof_namespace,
            )
            report = verify_closed_refinance_historical_canary(state.plan(plan_id))
            emit({"plan_id": plan_id, "canary": report, **document})
            return 0 if report["accepted"] else 2
        elif args.command == "check-loan-reference-canary":
            plan = state.plan(args.plan)
            if plan["block"] != LOANS_BLOCK:
                raise ValueError("The historical-reference canary requires a loans plan")
            run_items = None
            reconciliation = None
            if args.run:
                run = state.run(args.run)
                if run["plan_id"] != args.plan:
                    raise ValueError("Canary run does not belong to the selected plan")
                run_items = state.plan_run_items(args.plan)
                reconciliation = reconcile_loans(
                    settings, state, loan_contract, args.run,
                )
            report = verify_closed_refinance_historical_canary(
                plan, run_items=run_items, reconciliation=reconciliation,
            )
            emit(report)
            return 0 if report["accepted"] else 2
        elif args.command == "check-loan-contractual-anchor-cohort":
            plan = state.plan(args.plan)
            if plan["block"] != LOANS_BLOCK:
                raise ValueError("The contractual-anchor check requires a loans plan")

            def evidence(run_id):
                if not run_id:
                    return None, None
                run = state.run(run_id)
                if run["plan_id"] != args.plan:
                    raise ValueError("Cohort run does not belong to the selected plan")
                reconciliation = state.run_reconciliation(run_id)
                return state.run_items(run_id), (
                    None if reconciliation is None else reconciliation["summary"]
                )

            run_items, reconciliation = evidence(args.run)
            replay_items, replay_reconciliation = evidence(args.replay_run)
            report = verify_contractual_anchor_cohort(
                plan,
                run_items=run_items,
                reconciliation=reconciliation,
                replay_items=replay_items,
                replay_reconciliation=replay_reconciliation,
            )
            emit(report)
            return 0 if report["accepted"] else 2
        elif args.command == "check-loan-adjusted-schedule-cohort":
            plan = state.plan(args.plan)
            if plan["block"] != LOANS_BLOCK:
                raise ValueError("The adjusted-schedule check requires a loans plan")

            def adjusted_evidence(run_id):
                if not run_id:
                    return None, None
                run = state.run(run_id)
                if run["plan_id"] != args.plan:
                    raise ValueError("Cohort run does not belong to the selected plan")
                reconciliation = state.run_reconciliation(run_id)
                return state.run_items(run_id), (
                    None if reconciliation is None else reconciliation["summary"]
                )

            run_items, reconciliation = adjusted_evidence(args.run)
            replay_items, replay_reconciliation = adjusted_evidence(args.replay_run)
            report = verify_adjusted_schedule_cohort(
                plan,
                run_items=run_items,
                reconciliation=reconciliation,
                replay_items=replay_items,
                replay_reconciliation=replay_reconciliation,
            )
            emit(report)
            return 0 if report["accepted"] else 2
        elif args.command == "preflight": emit(preflight(settings))
        elif args.command == "inspect":
            contract = (mobile_collection_contract if args.block == MOBILE_COLLECTION_BLOCK
                        else dte_history_contract if args.block == DTE_HISTORY_BLOCK
                        else native_share_contract if args.block == NATIVE_SHARES_BLOCK
                        else savings_contract if args.block == SAVINGS_BLOCK
                        else aml_alert_contract if args.block == AML_ALERT_BLOCK
                        else membership_contract if args.block == MEMBERSHIP_BLOCK
                        else client_staff_assignment_contract if args.block == CLIENT_STAFF_ASSIGNMENT_BLOCK
                        else employee_contract if args.block == EMPLOYEE_BLOCK
                        else family_contract if args.block == FAMILY_REFERENCES_BLOCK
                        else pep_contract if args.block == PEP_BLOCK else client_contract)
            report = (inspect_mobile_collections(settings, contract)
                      if args.block == MOBILE_COLLECTION_BLOCK
                      else inspect_dte_history(settings, contract) if args.block == DTE_HISTORY_BLOCK
                      else inspect_native_shares(settings, contract, args.source_key)
                      if args.block == NATIVE_SHARES_BLOCK
                      else inspect_savings(settings, contract) if args.block == SAVINGS_BLOCK
                      else inspect_aml_alerts(settings, contract) if args.block == AML_ALERT_BLOCK
                      else inspect_membership(settings, contract) if args.block == MEMBERSHIP_BLOCK
                      else inspect_client_staff_assignments(settings, contract)
                      if args.block == CLIENT_STAFF_ASSIGNMENT_BLOCK
                      else inspect_employees(settings, contract) if args.block == EMPLOYEE_BLOCK
                      else inspect_family_references(settings, contract) if args.block == FAMILY_REFERENCES_BLOCK
                      else inspect_pep(settings, contract) if args.block == PEP_BLOCK
                      else inspect_clients(settings, contract))
            state.save_inspection(settings.target.name, settings.target.fingerprint, args.block,
                                  report["contract_hash"], report["schema_signature"], report["ready"])
            emit(report)
        elif args.command == "plan":
            if args.block == LOANS_BLOCK:
                plan_id, document = build_loan_plan(
                    settings, state, loan_contract, args.source_key, args.proof_namespace,
                    args.cutoff_date,
                )
            elif args.block == ACCOUNTING_BLOCK:
                if args.proof_namespace or args.repair_existing_drift:
                    raise ValueError(
                        "Accounting planning supports only explicit source keys and an optional cutoff date"
                    )
                state.adopt_accounting_cutoff(bind_active_accounting_cutoff(
                    state.accounting_cutoff, FineractApi(settings.target).request("GET", "accountingcutoff")
                ))
                plan_id, document = build_accounting_plan(
                    settings, state, AccountingContract.load(ROOT / "config/accounting.json"), args.source_key,
                    source_periods=args.period,
                )
            elif args.proof_namespace or args.period:
                raise ValueError("--proof-namespace is supported only for loans; --period only for accounting")
            elif args.block == NATIVE_SHARES_BLOCK:
                plan_id, document = build_native_share_plan(
                    settings, state, native_share_contract, args.source_key
                )
            elif args.block == MOBILE_COLLECTION_BLOCK:
                plan_id, document = build_mobile_collection_plan(
                    settings, state, mobile_collection_contract, args.source_key
                )
            elif args.block == DTE_HISTORY_BLOCK:
                plan_id, document = build_dte_history_plan(
                    settings, state, dte_history_contract, args.source_key
                )
            elif args.block == SAVINGS_BLOCK:
                plan_id, document = build_savings_plan(
                    settings, state, savings_contract, args.source_key, args.repair_existing_drift
                )
            elif args.repair_existing_drift:
                raise ValueError("--repair-existing-drift is supported only for savings-deposits")
            elif args.block == AML_ALERT_BLOCK:
                plan_id, document = build_aml_alert_plan(settings, state, aml_alert_contract, args.source_key)
            elif args.block == MEMBERSHIP_BLOCK:
                plan_id, document = build_membership_plan(settings, state, membership_contract, args.source_key)
            elif args.block == EMPLOYEE_BLOCK:
                plan_id, document = build_employee_plan(settings, state, employee_contract, args.source_key)
            elif args.block == CLIENT_STAFF_ASSIGNMENT_BLOCK:
                plan_id, document = build_client_staff_assignment_plan(
                    settings, state, client_staff_assignment_contract, args.source_key
                )
            elif args.block == FAMILY_REFERENCES_BLOCK:
                plan_id, document = build_family_reference_plan(settings, state, family_contract, args.source_key)
            elif args.block == PEP_BLOCK:
                plan_id, document = build_pep_plan(settings, state, pep_contract, args.source_key)
            else:
                plan_id, document = build_plan(settings, state, client_contract, args.source_key)
            emit({"plan_id": plan_id, **document})
        elif args.command == "apply":
            plan = state.plan(args.plan)
            if args.with_pep:
                result = apply_clients_with_pep(
                    settings, state, client_contract, pep_contract, args.plan, args.confirm_production
                )
                if settings.target.name == "prod":
                    state.conn.close()
                    result["retention"] = apply_retention(
                        settings.state_path, confirmation=APPLY_CONFIRMATION, scope="prod",
                        production_fingerprints=[settings.target.fingerprint],
                    )
                emit(result)
                return 0 if result["ok"] else 2
            elif args.with_family_references:
                result = apply_clients_with_family_references(
                    settings, state, client_contract, family_contract, args.plan, args.confirm_production
                )
                if settings.target.name == "prod":
                    state.conn.close()
                    result["retention"] = apply_retention(
                        settings.state_path, confirmation=APPLY_CONFIRMATION, scope="prod",
                        production_fingerprints=[settings.target.fingerprint],
                    )
                emit(result)
                return 0 if result["ok"] else 2
            elif plan["block"] == AML_ALERT_BLOCK:
                run_id, counts = apply_aml_alert_plan(
                    settings, state, aml_alert_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == SAVINGS_BLOCK:
                run_id, counts = apply_savings_plan(
                    settings, state, savings_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == NATIVE_SHARES_BLOCK:
                run_id, counts = apply_native_share_plan(
                    settings, state, native_share_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == MEMBERSHIP_BLOCK:
                run_id, counts = apply_membership_plan(
                    settings, state, membership_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == EMPLOYEE_BLOCK:
                run_id, counts = apply_employee_plan(
                    settings, state, employee_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == CLIENT_STAFF_ASSIGNMENT_BLOCK:
                run_id, counts = apply_client_staff_assignment_plan(
                    settings, state, client_staff_assignment_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == FAMILY_REFERENCES_BLOCK:
                run_id, counts = apply_family_reference_plan(
                    settings, state, family_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == PEP_BLOCK:
                run_id, counts = apply_pep_plan(
                    settings, state, pep_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == LOANS_BLOCK:
                run_id, counts = apply_loan_plan(
                    settings, state, loan_contract, args.plan, args.confirm_production,
                    controls=LoanApplyControls.configured(
                        args.loan_workers, args.fineract_pause_seconds, args.fineract_recovery_attempts
                    ),
                )
            elif plan["block"] == MOBILE_COLLECTION_BLOCK:
                run_id, counts = apply_mobile_collection_plan(
                    settings, state, mobile_collection_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == DTE_HISTORY_BLOCK:
                run_id, counts = apply_dte_history_plan(
                    settings, state, dte_history_contract, args.plan, args.confirm_production,
                    controls=DteApplyControls.configured(args.dte_workers, args.dte_batch_size),
                )
            elif plan["block"] == ACCOUNTING_BLOCK:
                run_id, counts = apply_accounting_plan(
                    settings, state, AccountingContract.load(ROOT / "config/accounting.json"),
                    args.plan, args.confirm_production,
                )
            else:
                run_id, counts = apply_plan(settings, state, client_contract, args.plan, args.confirm_production)
            result = {"run_id": run_id, "counts": counts}
            if settings.target.name == "prod":
                state.conn.close()
                result["retention"] = apply_retention(
                    settings.state_path, confirmation=APPLY_CONFIRMATION, scope="prod",
                    production_fingerprints=[settings.target.fingerprint],
                )
            emit(result)
        elif args.command == "reconcile":
            run = state.run(args.run)
            if run["block"] == AML_ALERT_BLOCK:
                emit(reconcile_aml_alerts(settings, state, aml_alert_contract, args.run))
            elif run["block"] == SAVINGS_BLOCK:
                result = reconcile_savings(settings, state, savings_contract, args.run)
                state.record_reconciliation(args.run, result)
                emit(result)
            elif run["block"] == NATIVE_SHARES_BLOCK:
                result = reconcile_native_shares(settings, state, native_share_contract, args.run)
                state.record_reconciliation(args.run, result)
                emit(result)
            elif run["block"] == MEMBERSHIP_BLOCK:
                emit(reconcile_membership(settings, state, membership_contract, args.run))
            elif run["block"] == EMPLOYEE_BLOCK:
                emit(reconcile_employees(settings, state, employee_contract, args.run))
            elif run["block"] == CLIENT_STAFF_ASSIGNMENT_BLOCK:
                emit(reconcile_client_staff_assignments(
                    settings, state, client_staff_assignment_contract, args.run
                ))
            elif run["block"] == FAMILY_REFERENCES_BLOCK:
                emit(reconcile_family_references(settings, state, family_contract, args.run))
            elif run["block"] == PEP_BLOCK:
                emit(reconcile_pep(settings, state, pep_contract, args.run))
            elif run["block"] == LOANS_BLOCK:
                result = reconcile_loans(settings, state, loan_contract, args.run)
                state.record_reconciliation(args.run, result)
                if args.report:
                    report = compact_loan_reconciliation_report(result, args.sample_limit)
                    report_path = Path(args.report).expanduser().resolve()
                    if not report_path.parent.is_dir():
                        raise ValueError(f"Report parent directory does not exist: {report_path.parent}")
                    report_path.write_text(
                        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
                        encoding="utf-8",
                    )
                    emit({
                        "ok": result["ok"],
                        "run_id": result["run_id"],
                        "report": str(report_path),
                        "blocking_mismatch_count": report["blocking_mismatch_count"],
                        "blocking_affected_source_key_count": report["blocking_affected_source_key_count"],
                    })
                else:
                    emit(result)
            elif run["block"] == MOBILE_COLLECTION_BLOCK:
                result = reconcile_mobile_collections(settings, state, mobile_collection_contract, args.run)
                state.record_reconciliation(args.run, result)
                emit(result)
            elif run["block"] == DTE_HISTORY_BLOCK:
                emit(reconcile_dte_history(settings, state, dte_history_contract, args.run))
            elif run["block"] == ACCOUNTING_BLOCK:
                emit(reconcile_accounting(
                    settings, state, AccountingContract.load(ROOT / "config/accounting.json"), args.run
                ))
            else:
                emit(reconcile(settings, state, client_contract, args.run))
        elif args.command == "retry":
            previous = state.run(args.run)
            keys = {item["source_key"] for item in state.run_items(args.run, failed_only=True)}
            if previous["block"] == AML_ALERT_BLOCK:
                run_id, counts = apply_aml_alert_plan(
                    settings, state, aml_alert_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == SAVINGS_BLOCK:
                run_id, counts = apply_savings_plan(
                    settings, state, savings_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == NATIVE_SHARES_BLOCK:
                run_id, counts = apply_native_share_plan(
                    settings, state, native_share_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == MEMBERSHIP_BLOCK:
                run_id, counts = apply_membership_plan(
                    settings, state, membership_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == EMPLOYEE_BLOCK:
                run_id, counts = apply_employee_plan(
                    settings, state, employee_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == CLIENT_STAFF_ASSIGNMENT_BLOCK:
                run_id, counts = apply_client_staff_assignment_plan(
                    settings, state, client_staff_assignment_contract, previous["plan_id"],
                    args.confirm_production, keys
                )
            elif previous["block"] == FAMILY_REFERENCES_BLOCK:
                run_id, counts = apply_family_reference_plan(
                    settings, state, family_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == PEP_BLOCK:
                run_id, counts = apply_pep_plan(
                    settings, state, pep_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == LOANS_BLOCK:
                loan_plan = state.plan(previous["plan_id"])
                keys = loan_retry_keys(
                    loan_plan["document"]["actions"], state.plan_run_items(previous["plan_id"])
                )
                run_id, counts = apply_loan_plan(
                    settings, state, loan_contract, previous["plan_id"], args.confirm_production, keys,
                    LoanApplyControls.configured(
                        args.loan_workers, args.fineract_pause_seconds, args.fineract_recovery_attempts
                    ),
                )
            elif previous["block"] == MOBILE_COLLECTION_BLOCK:
                run_id, counts = apply_mobile_collection_plan(
                    settings, state, mobile_collection_contract, previous["plan_id"],
                    args.confirm_production, keys
                )
            elif previous["block"] == DTE_HISTORY_BLOCK:
                run_id, counts = apply_dte_history_plan(
                    settings, state, dte_history_contract, previous["plan_id"],
                    args.confirm_production, keys,
                    DteApplyControls.configured(args.dte_workers, args.dte_batch_size),
                )
            elif previous["block"] == ACCOUNTING_BLOCK:
                keys = accounting_retry_keys(state, args.run)
                run_id, counts = apply_accounting_plan(
                    settings, state, AccountingContract.load(ROOT / "config/accounting.json"),
                    previous["plan_id"], args.confirm_production, keys, retry_from_run=args.run,
                )
            else:
                run_id, counts = apply_plan(
                    settings, state, client_contract, previous["plan_id"], args.confirm_production, keys
                )
            emit({"run_id": run_id, "counts": counts})
        elif args.command == "link":
            source_key = args.source_key.strip()
            client_contract.query(source_key)  # Validate the canonical affiliation-number key shape.
            state.add_link(settings.target.fingerprint, args.block, source_key, args.target_id)
            emit({"linked": True, "source_key": source_key, "target_id": args.target_id,
                  "target_fingerprint": settings.target.fingerprint})
        elif args.command == "status":
            emit(accounting_status(state, settings.target.fingerprint) if args.block == ACCOUNTING_BLOCK
                 else state.recent(args.block, settings.target.fingerprint))
        return 0
    except Exception as exc:
        emit({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
