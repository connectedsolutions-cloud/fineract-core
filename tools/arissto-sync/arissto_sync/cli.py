from __future__ import annotations

import argparse
import json

from .aml_alerts import (
    BLOCK as AML_ALERT_BLOCK,
    AmlAlertContract,
    apply_aml_alert_plan,
    build_aml_alert_plan,
    inspect_aml_alerts,
    reconcile_aml_alerts,
)
from .clients import ClientContract
from .arissto import check_source
from .config import load_settings, load_source_config
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
from .service_registry import service_report
from .state import State
from .workflows import apply_clients_with_family_references, apply_clients_with_pep


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="arissto-sync", description="Local Arissto to Fineract synchronization CLI")
    root.add_argument("--env-file")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("source-check", help="test only the read-only Arissto connection")
    services = commands.add_parser("services", help="list registered migration services")
    services.add_argument("--service", help="show one migration service by stable ID")
    for name in ("preflight", "inspect", "plan", "status"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--target", choices=("local", "prod"), required=True)
        if name in {"inspect", "plan"}:
            cmd.add_argument(
                "--block",
                choices=("clients", PEP_BLOCK, FAMILY_REFERENCES_BLOCK, EMPLOYEE_BLOCK, MEMBERSHIP_BLOCK,
                         AML_ALERT_BLOCK),
                required=True,
            )
        if name == "plan":
            cmd.add_argument("--source-key", action="append",
                             help="scope the plan to an exact source key for the selected block; repeat as needed")
        if name == "status":
            cmd.add_argument(
                "--block",
                choices=("clients", PEP_BLOCK, FAMILY_REFERENCES_BLOCK, EMPLOYEE_BLOCK, MEMBERSHIP_BLOCK,
                         AML_ALERT_BLOCK),
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
        settings = load_settings(args.target, args.env_file)
        state = State(settings.state_path)
        client_contract = ClientContract.load(settings.mapping_path)
        family_contract = FamilyReferenceContract.load(settings.family_reference_mapping_path)
        pep_contract = PepContract.load(settings.pep_mapping_path)
        employee_contract = EmployeeContract.load(settings.employee_mapping_path)
        membership_contract = MembershipContract.load(settings.membership_mapping_path)
        aml_alert_contract = AmlAlertContract.load(settings.aml_alert_mapping_path)
        if args.command == "preflight": emit(preflight(settings))
        elif args.command == "inspect":
            contract = (aml_alert_contract if args.block == AML_ALERT_BLOCK
                        else membership_contract if args.block == MEMBERSHIP_BLOCK
                        else employee_contract if args.block == EMPLOYEE_BLOCK
                        else family_contract if args.block == FAMILY_REFERENCES_BLOCK
                        else pep_contract if args.block == PEP_BLOCK else client_contract)
            report = (inspect_aml_alerts(settings, contract) if args.block == AML_ALERT_BLOCK
                      else inspect_membership(settings, contract) if args.block == MEMBERSHIP_BLOCK
                      else inspect_employees(settings, contract) if args.block == EMPLOYEE_BLOCK
                      else inspect_family_references(settings, contract) if args.block == FAMILY_REFERENCES_BLOCK
                      else inspect_pep(settings, contract) if args.block == PEP_BLOCK
                      else inspect_clients(settings, contract))
            state.save_inspection(settings.target.name, settings.target.fingerprint, args.block,
                                  report["contract_hash"], report["schema_signature"], report["ready"])
            emit(report)
        elif args.command == "plan":
            if args.block == AML_ALERT_BLOCK:
                plan_id, document = build_aml_alert_plan(settings, state, aml_alert_contract, args.source_key)
            elif args.block == MEMBERSHIP_BLOCK:
                plan_id, document = build_membership_plan(settings, state, membership_contract, args.source_key)
            elif args.block == EMPLOYEE_BLOCK:
                plan_id, document = build_employee_plan(settings, state, employee_contract, args.source_key)
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
            elif plan["block"] == MEMBERSHIP_BLOCK:
                run_id, counts = apply_membership_plan(
                    settings, state, membership_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == EMPLOYEE_BLOCK:
                run_id, counts = apply_employee_plan(
                    settings, state, employee_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == FAMILY_REFERENCES_BLOCK:
                run_id, counts = apply_family_reference_plan(
                    settings, state, family_contract, args.plan, args.confirm_production
                )
            elif plan["block"] == PEP_BLOCK:
                run_id, counts = apply_pep_plan(
                    settings, state, pep_contract, args.plan, args.confirm_production
                )
            else:
                run_id, counts = apply_plan(settings, state, client_contract, args.plan, args.confirm_production)
            emit({"run_id": run_id, "counts": counts})
        elif args.command == "reconcile":
            run = state.run(args.run)
            if run["block"] == AML_ALERT_BLOCK:
                emit(reconcile_aml_alerts(settings, state, aml_alert_contract, args.run))
            elif run["block"] == MEMBERSHIP_BLOCK:
                emit(reconcile_membership(settings, state, membership_contract, args.run))
            elif run["block"] == EMPLOYEE_BLOCK:
                emit(reconcile_employees(settings, state, employee_contract, args.run))
            elif run["block"] == FAMILY_REFERENCES_BLOCK:
                emit(reconcile_family_references(settings, state, family_contract, args.run))
            elif run["block"] == PEP_BLOCK:
                emit(reconcile_pep(settings, state, pep_contract, args.run))
            else:
                emit(reconcile(settings, state, client_contract, args.run))
        elif args.command == "retry":
            previous = state.run(args.run)
            keys = {item["source_key"] for item in state.run_items(args.run, failed_only=True)}
            if previous["block"] == AML_ALERT_BLOCK:
                run_id, counts = apply_aml_alert_plan(
                    settings, state, aml_alert_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == MEMBERSHIP_BLOCK:
                run_id, counts = apply_membership_plan(
                    settings, state, membership_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == EMPLOYEE_BLOCK:
                run_id, counts = apply_employee_plan(
                    settings, state, employee_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == FAMILY_REFERENCES_BLOCK:
                run_id, counts = apply_family_reference_plan(
                    settings, state, family_contract, previous["plan_id"], args.confirm_production, keys
                )
            elif previous["block"] == PEP_BLOCK:
                run_id, counts = apply_pep_plan(
                    settings, state, pep_contract, previous["plan_id"], args.confirm_production, keys
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
