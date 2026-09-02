from __future__ import annotations

import argparse
import json
from pathlib import Path

from .aml_alerts import (
    BLOCK as AML_ALERT_BLOCK,
    AmlAlertContract,
    apply_aml_alert_plan,
    build_aml_alert_plan,
    inspect_aml_alerts,
    reconcile_aml_alerts,
)
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
from .config import ROOT, load_settings, load_source_config
from .engine import apply_plan, build_plan, inspect_clients, preflight, reconcile
from .employees import (
    BLOCK as EMPLOYEE_BLOCK,
    EmployeeContract,
    apply_employee_plan,
    build_employee_plan,
    inspect_employees,
    reconcile_employees,
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
    LoanContract,
    apply_loan_plan,
    build_loan_plan,
    inspect_loans,
    loan_retry_keys,
    compact_loan_reconciliation_report,
    reconcile_loans,
)
from .loan_schedule_proof import prove_schedule
from .service_registry import service_report
from .savings import BLOCK as SAVINGS_BLOCK, SavingsContract, inspect_savings
from .savings_engine import apply_savings_plan, build_savings_plan, reconcile_savings
from .savings_lifecycle_proof import prove_vista_lifecycle
from .fixed_deposit_lifecycle_proof import prove_dpf_lifecycle
from .state import State
from .workflows import apply_clients_with_family_references, apply_clients_with_pep


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="arissto-sync", description="Local Arissto to Fineract synchronization CLI")
    root.add_argument("--env-file")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("source-check", help="test only the read-only Arissto connection")
    schedule_proof = commands.add_parser(
        "prove-loan-schedule", help="compare one Arissto schedule with Fineract's non-posting calculator"
    )
    schedule_proof.add_argument("--target", choices=("local",), required=True)
    schedule_proof.add_argument("--source-key", type=int, required=True)
    schedule_proof.add_argument("--product-id", type=int, required=True)
    schedule_proof.add_argument("--client-id", type=int, required=True)
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
    for name in ("preflight", "inspect", "plan", "status"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--target", choices=("local", "prod"), required=name != "inspect")
        if name in {"inspect", "plan"}:
            block_choices = (
                "clients", PEP_BLOCK, FAMILY_REFERENCES_BLOCK, EMPLOYEE_BLOCK, CLIENT_STAFF_ASSIGNMENT_BLOCK,
                MEMBERSHIP_BLOCK, AML_ALERT_BLOCK, SAVINGS_BLOCK, LOANS_BLOCK, MOBILE_COLLECTION_BLOCK,
                NATIVE_SHARES_BLOCK,
            )
            if name == "inspect":
                block_choices = (*block_choices, SAVINGS_BLOCK, LOANS_BLOCK)
            cmd.add_argument(
                "--block",
                choices=block_choices,
                required=True,
            )
        if name == "inspect":
            cmd.add_argument("--source-key", help="inspect one exact source key when the selected block supports it")
        if name == "plan":
            cmd.add_argument("--source-key", action="append",
                             help="scope the plan to an exact source key for the selected block; repeat as needed")
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
                         NATIVE_SHARES_BLOCK),
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
        if args.command == "services":
            emit(service_report(args.service))
            return 0
        if args.command == "prove-loan-schedule":
            report = prove_schedule(
                load_settings(args.target, args.env_file), args.source_key, args.product_id, args.client_id
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
        if not args.target:
            raise ValueError(f"--target is required for {args.command} --block {getattr(args, 'block', '')}".strip())
        settings = load_settings(args.target, args.env_file)
        state = State(settings.state_path)
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
        if args.command == "preflight": emit(preflight(settings))
        elif args.command == "inspect":
            contract = (mobile_collection_contract if args.block == MOBILE_COLLECTION_BLOCK
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
                    settings, state, loan_contract, args.source_key, args.proof_namespace
                )
            elif args.proof_namespace:
                raise ValueError("--proof-namespace is supported only for loans")
            elif args.block == NATIVE_SHARES_BLOCK:
                plan_id, document = build_native_share_plan(
                    settings, state, native_share_contract, args.source_key
                )
            elif args.block == MOBILE_COLLECTION_BLOCK:
                plan_id, document = build_mobile_collection_plan(
                    settings, state, mobile_collection_contract, args.source_key
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
                emit(result)
                return 0 if result["ok"] else 2
            elif args.with_family_references:
                result = apply_clients_with_family_references(
                    settings, state, client_contract, family_contract, args.plan, args.confirm_production
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
                    settings, state, loan_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == MOBILE_COLLECTION_BLOCK:
                run_id, counts = apply_mobile_collection_plan(
                    settings, state, mobile_collection_contract, args.plan, args.confirm_production
                )
            else:
                run_id, counts = apply_plan(settings, state, client_contract, args.plan, args.confirm_production)
            emit({"run_id": run_id, "counts": counts})
        elif args.command == "reconcile":
            run = state.run(args.run)
            if run["block"] == AML_ALERT_BLOCK:
                emit(reconcile_aml_alerts(settings, state, aml_alert_contract, args.run))
            elif run["block"] == SAVINGS_BLOCK:
                emit(reconcile_savings(settings, state, savings_contract, args.run))
            elif run["block"] == NATIVE_SHARES_BLOCK:
                emit(reconcile_native_shares(settings, state, native_share_contract, args.run))
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
                emit(reconcile_mobile_collections(settings, state, mobile_collection_contract, args.run))
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
                keys = loan_retry_keys(loan_plan["document"]["actions"], state.run_items(args.run))
                run_id, counts = apply_loan_plan(
                    settings, state, loan_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == MOBILE_COLLECTION_BLOCK:
                run_id, counts = apply_mobile_collection_plan(
                    settings, state, mobile_collection_contract, previous["plan_id"],
                    args.confirm_production, keys
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
        elif args.command == "status": emit(state.recent(args.block, settings.target.fingerprint))
        return 0
    except Exception as exc:
        emit({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
