from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "migration-services" / "registry.json"
VALID_STATUSES = {"available", "export-ready", "planned", "blocked", "retired"}


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("version") != 1 or not isinstance(value.get("services"), list):
        raise ValueError("Invalid migration service registry")

    identifiers: set[str] = set()
    for service in value["services"]:
        identifier = service.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("Migration service IDs must be non-empty and unique")
        identifiers.add(identifier)
        if service.get("status") not in VALID_STATUSES:
            raise ValueError(f"Invalid migration service status: {service.get('status')!r}")
        if not isinstance(service.get("executable"), bool):
            raise ValueError(f"Migration service {identifier!r} needs executable true/false")
        if service["executable"] and not service.get("cli_block"):
            raise ValueError(f"Executable migration service {identifier!r} needs a cli_block")

    dependencies: dict[str, list[str]] = {}
    for service in value["services"]:
        identifier = service["id"]
        depends_on = service.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
            raise ValueError(f"Migration service {identifier!r} dependencies must be a list of service IDs")
        unknown = set(depends_on) - identifiers
        if unknown:
            raise ValueError(f"Migration service {identifier!r} has unknown dependencies: {sorted(unknown)}")
        if identifier in depends_on:
            raise ValueError(f"Migration service {identifier!r} cannot depend on itself")
        dependencies[identifier] = depends_on

    for service in value["services"]:
        identifier = service["id"]
        post_sync = service.get("post_sync_services", [])
        if not isinstance(post_sync, list) or not all(isinstance(item, str) for item in post_sync):
            raise ValueError(f"Migration service {identifier!r} post-sync services must be a list of service IDs")
        unknown_post_sync = set(post_sync) - identifiers
        if unknown_post_sync:
            raise ValueError(f"Migration service {identifier!r} has unknown post-sync services: {sorted(unknown_post_sync)}")
        if any(identifier not in dependencies[item] for item in post_sync):
            raise ValueError(f"Migration service {identifier!r} post-sync services must depend on it")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise ValueError("Migration service dependency cycle detected")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in dependencies[identifier]:
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in identifiers:
        visit(identifier)

    return value


def service_report(identifier: str | None = None) -> dict[str, Any]:
    registry = load_registry()
    if identifier is None:
        return registry
    matches = [service for service in registry["services"] if service["id"] == identifier]
    if not matches:
        raise ValueError(f"Unknown migration service: {identifier}")
    return {"version": registry["version"], "service": matches[0]}
