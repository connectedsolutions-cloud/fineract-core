from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ROOT
from .service_registry import load_registry


WORKFLOWS_PATH = ROOT / "workflows"
WORKFLOW_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class WorkflowDefinition:
    identifier: str
    version: int
    description: str
    services: tuple[str, ...]
    scope_mode: str
    stop_policy: str
    retry_policy: str
    unavailable_services: str
    accounting_cutoff_policy: str
    document: dict[str, Any]
    definition_hash: str


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def workflow_path(identifier: str, root: Path = WORKFLOWS_PATH) -> Path:
    if not WORKFLOW_ID.fullmatch(identifier):
        raise ValueError(f"Invalid workflow ID: {identifier!r}")
    return root / f"{identifier}.json"


def load_workflow(identifier: str, root: Path = WORKFLOWS_PATH) -> WorkflowDefinition:
    path = workflow_path(identifier, root)
    if not path.is_file():
        raise ValueError(f"Unknown workflow: {identifier}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("id") != identifier:
        raise ValueError(f"Workflow file ID does not match {identifier!r}")
    if value.get("version") != 1:
        raise ValueError(f"Unsupported workflow version: {value.get('version')!r}")
    services = value.get("services")
    if not isinstance(services, list) or not services or not all(isinstance(item, str) for item in services):
        raise ValueError("Workflow services must be a non-empty list of service IDs")
    if len(services) != len(set(services)):
        raise ValueError("Workflow services must be unique")
    scope_mode = value.get("scope", {}).get("mode")
    if scope_mode != "full-block":
        raise ValueError("Local workflow version 1 supports only full-block scope")
    if value.get("ordering") != "registry-topological":
        raise ValueError("Workflow ordering must be registry-topological")
    if value.get("stop_policy") != "dependency-gated":
        raise ValueError("Workflow stop_policy must be dependency-gated")
    if value.get("retry_policy") != "resume-failed-step":
        raise ValueError("Workflow retry_policy must be resume-failed-step")
    if value.get("unavailable_services") not in {"reject", "allow-executable"}:
        raise ValueError("Workflow unavailable_services must be reject or allow-executable")
    if value.get("accounting_cutoff_policy", "snapshot-only") not in {
        "snapshot-only", "activate-frozen-plan",
    }:
        raise ValueError(
            "Workflow accounting_cutoff_policy must be snapshot-only or activate-frozen-plan"
        )
    prerequisites = value.get("target_prerequisites", {})
    if not isinstance(prerequisites, dict):
        raise ValueError("Workflow target_prerequisites must be an object")
    mappings = prerequisites.get("financial_activity_mappings", [])
    if not isinstance(mappings, list):
        raise ValueError("Workflow financial_activity_mappings must be a list")
    seen_activity_ids: set[int] = set()
    for mapping in mappings:
        if not isinstance(mapping, dict):
            raise ValueError("Workflow financial activity mapping must be an object")
        activity_id = mapping.get("financial_activity_id")
        gl_code = mapping.get("gl_code")
        required_by = mapping.get("required_by_services")
        if not isinstance(activity_id, int) or activity_id <= 0:
            raise ValueError("Workflow financial_activity_id must be a positive integer")
        if activity_id in seen_activity_ids:
            raise ValueError("Workflow financial activity IDs must be unique")
        seen_activity_ids.add(activity_id)
        if not isinstance(gl_code, str) or not gl_code.strip():
            raise ValueError("Workflow financial activity gl_code must be nonblank")
        if (
            not isinstance(required_by, list) or not required_by
            or not all(isinstance(service_id, str) and service_id in services for service_id in required_by)
        ):
            raise ValueError(
                "Workflow financial activity required_by_services must name selected services"
            )
        for field in ("gl_classification", "gl_usage"):
            if not isinstance(mapping.get(field), int) or mapping[field] <= 0:
                raise ValueError(f"Workflow financial activity {field} must be a positive integer")
    return WorkflowDefinition(
        identifier=identifier,
        version=value["version"],
        description=str(value.get("description", "")),
        services=tuple(services),
        scope_mode=scope_mode,
        stop_policy=value["stop_policy"],
        retry_policy=value["retry_policy"],
        unavailable_services=value["unavailable_services"],
        accounting_cutoff_policy=value.get("accounting_cutoff_policy", "snapshot-only"),
        document=value,
        definition_hash=_canonical_hash(value),
    )


def inspect_workflow(definition: WorkflowDefinition, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or load_registry()
    catalog = {service["id"]: service for service in registry["services"]}
    selected = set(definition.services)
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for service_id in definition.services:
        service = catalog.get(service_id)
        if service is None:
            blockers.append({"service_id": service_id, "code": "unknown-service"})
            continue
        if not service["executable"]:
            blockers.append({"service_id": service_id, "code": "not-executable"})
        if service["status"] != "available":
            issue = {"service_id": service_id, "code": "service-unavailable", "status": service["status"]}
            if definition.unavailable_services == "allow-executable" and service["executable"]:
                warnings.append({**issue, "allowed_by": "allow-executable"})
            else:
                blockers.append(issue)
        missing = [dependency for dependency in service.get("depends_on", []) if dependency not in selected]
        if missing:
            blockers.append({
                "service_id": service_id, "code": "missing-selected-dependencies", "dependencies": missing
            })

    ordered: list[str] = []
    if not any(item["code"] in {"unknown-service", "missing-selected-dependencies"} for item in blockers):
        remaining = list(definition.services)
        while remaining:
            ready = [
                service_id for service_id in remaining
                if all(dependency in ordered for dependency in catalog[service_id].get("depends_on", []))
            ]
            if not ready:
                blockers.append({"service_id": None, "code": "dependency-cycle"})
                break
            service_id = ready[0]
            ordered.append(service_id)
            remaining.remove(service_id)

    return {
        "workflow_id": definition.identifier,
        "workflow_version": definition.version,
        "definition_hash": definition.definition_hash,
        "services": list(definition.services),
        "ordered_services": ordered,
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
    }


def require_workflow_ready(definition: WorkflowDefinition) -> dict[str, Any]:
    report = inspect_workflow(definition)
    if not report["ready"]:
        codes = ", ".join(
            f"{item.get('service_id') or 'workflow'}:{item['code']}" for item in report["blockers"]
        )
        raise ValueError(f"Workflow {definition.identifier!r} is not ready: {codes}")
    return report


def select_workflow_services(
    definition: WorkflowDefinition, requested_services: list[str] | tuple[str, ...],
    registry: dict[str, Any] | None = None,
) -> WorkflowDefinition:
    """Return a frozen workflow subset containing every requested service dependency."""
    requested = tuple(dict.fromkeys(requested_services))
    if not requested:
        raise ValueError("Select at least one workflow service")
    unknown = set(requested) - set(definition.services)
    if unknown:
        raise ValueError(
            f"Services are not part of workflow {definition.identifier!r}: {sorted(unknown)}"
        )

    registry = registry or load_registry()
    catalog = {service["id"]: service for service in registry["services"]}
    selected: set[str] = set()

    def include(service_id: str) -> None:
        if service_id in selected:
            return
        if service_id not in definition.services:
            raise ValueError(
                f"Workflow {definition.identifier!r} does not contain dependency {service_id!r}"
            )
        for dependency in catalog[service_id].get("depends_on", []):
            include(dependency)
        selected.add(service_id)

    for service_id in requested:
        include(service_id)

    included = [service_id for service_id in definition.services if service_id in selected]
    document = json.loads(json.dumps(definition.document))
    document["services"] = included
    document["selection"] = {
        "mode": "dependency-closure",
        "requested_services": list(requested),
        "included_services": included,
    }
    return WorkflowDefinition(
        identifier=definition.identifier,
        version=definition.version,
        description=definition.description,
        services=tuple(included),
        scope_mode=definition.scope_mode,
        stop_policy=definition.stop_policy,
        retry_policy=definition.retry_policy,
        unavailable_services=definition.unavailable_services,
        accounting_cutoff_policy=definition.accounting_cutoff_policy,
        document=document,
        definition_hash=_canonical_hash(document),
    )


def list_workflows(root: Path = WORKFLOWS_PATH) -> dict[str, Any]:
    workflows = []
    for path in sorted(root.glob("*.json")):
        definition = load_workflow(path.stem, root)
        report = inspect_workflow(definition)
        workflows.append({
            "id": definition.identifier,
            "description": definition.description,
            "ready": report["ready"],
            "ordered_services": report["ordered_services"],
            "blockers": report["blockers"],
            "warnings": report["warnings"],
        })
    return {"version": 1, "target": "local", "workflows": workflows}
