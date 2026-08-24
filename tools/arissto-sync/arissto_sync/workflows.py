from __future__ import annotations

from typing import Any

from .clients import ClientContract
from .config import Settings
from .engine import apply_plan, reconcile
from .family_references import (
    FamilyReferenceContract,
    apply_family_reference_plan,
    build_family_reference_plan,
    reconcile_family_references,
)
from .pep import PepContract, apply_pep_plan, build_pep_plan, reconcile_pep
from .state import State


def successful_client_source_keys(state: State, run_id: str) -> set[str]:
    return {
        item["source_key"]
        for item in state.run_items(run_id)
        if item["status"] in {"succeeded", "unchanged"}
    }


def apply_clients_with_pep(
    settings: Settings,
    state: State,
    client_contract: ClientContract,
    pep_contract: PepContract,
    client_plan_id: str,
    production_confirmation: str | None = None,
) -> dict[str, Any]:
    plan = state.plan(client_plan_id)
    if plan["block"] != "clients":
        raise ValueError("--with-pep requires a clients plan")

    client_run_id, client_counts = apply_plan(
        settings, state, client_contract, client_plan_id, production_confirmation
    )
    client_reconciliation = reconcile(settings, state, client_contract, client_run_id)
    result: dict[str, Any] = {
        "ok": False,
        "workflow": "clients-with-pep",
        "client": {
            "plan_id": client_plan_id,
            "run_id": client_run_id,
            "counts": client_counts,
            "reconciliation": client_reconciliation,
        },
        "client_pep": {"status": "not-started"},
    }
    if not client_reconciliation["ok"]:
        result["stopped_after"] = "client-reconciliation"
        return result

    owner_keys = successful_client_source_keys(state, client_run_id)
    if not owner_keys:
        result["ok"] = True
        result["client_pep"] = {"status": "skipped", "reason": "no-successful-client-source-keys"}
        return result

    pep_plan_id, pep_plan = build_pep_plan(settings, state, pep_contract, owner_keys=owner_keys)
    if not pep_plan["applicable"]:
        result["client_pep"] = {
            "status": "blocked",
            "plan_id": pep_plan_id,
            "scope": pep_plan["scope"],
            "counts": pep_plan["counts"],
            "readiness_blocker_count": pep_plan["readiness_blocker_count"],
        }
        result["stopped_after"] = "client-pep-plan"
        return result
    pep_run_id, pep_counts = apply_pep_plan(
        settings, state, pep_contract, pep_plan_id, production_confirmation
    )
    pep_reconciliation = reconcile_pep(settings, state, pep_contract, pep_run_id)
    result["client_pep"] = {
        "status": "completed" if pep_reconciliation["ok"] else "completed-with-errors",
        "plan_id": pep_plan_id,
        "run_id": pep_run_id,
        "scope": pep_plan["scope"],
        "counts": pep_counts,
        "reconciliation": pep_reconciliation,
    }
    result["ok"] = pep_reconciliation["ok"]
    if not result["ok"]:
        result["stopped_after"] = "client-pep-reconciliation"
    return result


def apply_clients_with_family_references(
    settings: Settings,
    state: State,
    client_contract: ClientContract,
    family_contract: FamilyReferenceContract,
    client_plan_id: str,
    production_confirmation: str | None = None,
) -> dict[str, Any]:
    plan = state.plan(client_plan_id)
    if plan["block"] != "clients":
        raise ValueError("--with-family-references requires a clients plan")

    client_run_id, client_counts = apply_plan(
        settings, state, client_contract, client_plan_id, production_confirmation
    )
    client_reconciliation = reconcile(settings, state, client_contract, client_run_id)
    result: dict[str, Any] = {
        "ok": False,
        "workflow": "clients-with-family-references",
        "client": {
            "plan_id": client_plan_id,
            "run_id": client_run_id,
            "counts": client_counts,
            "reconciliation": client_reconciliation,
        },
        "family_references": {"status": "not-started"},
    }
    if not client_reconciliation["ok"]:
        result["stopped_after"] = "client-reconciliation"
        return result

    owner_keys = successful_client_source_keys(state, client_run_id)
    if not owner_keys:
        result["ok"] = True
        result["family_references"] = {"status": "skipped", "reason": "no-successful-client-source-keys"}
        return result

    family_plan_id, family_plan = build_family_reference_plan(
        settings, state, family_contract, owner_keys=owner_keys
    )
    family_run_id, family_counts = apply_family_reference_plan(
        settings, state, family_contract, family_plan_id, production_confirmation
    )
    family_reconciliation = reconcile_family_references(
        settings, state, family_contract, family_run_id
    )
    result["family_references"] = {
        "status": "completed" if family_reconciliation["ok"] else "completed-with-errors",
        "plan_id": family_plan_id,
        "run_id": family_run_id,
        "scope": family_plan["scope"],
        "counts": family_counts,
        "reconciliation": family_reconciliation,
    }
    result["ok"] = family_reconciliation["ok"]
    if not result["ok"]:
        result["stopped_after"] = "family-reference-reconciliation"
    return result
