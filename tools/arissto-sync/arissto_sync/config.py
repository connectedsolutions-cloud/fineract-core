from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class SourceConfig:
    server: str
    port: int
    database: str
    user: str
    password: str
    driver: str
    extra: str
    connect_timeout: int
    query_timeout: int


@dataclass(frozen=True)
class TargetConfig:
    name: str
    api_url: str
    api_user: str
    api_password: str
    tenant: str
    pg_url: str | None
    expected_host: str
    tls_verify: bool

    @property
    def fingerprint(self) -> str:
        pg_host = urlparse(self.pg_url).hostname if self.pg_url else "api-only"
        material = f"{self.name}|{self.api_url.rstrip('/')}|{self.tenant}|{pg_host}"
        return hashlib.sha256(material.encode()).hexdigest()[:16]

    def assert_expected_host(self) -> None:
        api_host = urlparse(self.api_url).hostname or ""
        if not self.expected_host:
            raise ValueError(f"FINERACT_{self.name.upper()}_EXPECTED_HOST is required")
        if api_host.lower() != self.expected_host.lower():
            raise ValueError(
                f"Target host guard failed: API host {api_host!r} does not equal expected host {self.expected_host!r}"
            )


@dataclass(frozen=True)
class Settings:
    source: SourceConfig
    target: TargetConfig
    state_path: Path
    mapping_path: Path
    family_reference_mapping_path: Path
    pep_mapping_path: Path
    employee_mapping_path: Path
    membership_mapping_path: Path
    aml_alert_mapping_path: Path


def load_source_config(env_file: str | None = None) -> SourceConfig:
    """Load only Arissto settings, without requiring a Fineract profile."""
    load_env(Path(env_file) if env_file else ROOT / ".env")
    return SourceConfig(
        server=required("ARISSTO_SERVER"), port=int(os.getenv("ARISSTO_PORT", "1433")),
        database=required("ARISSTO_DATABASE"), user=required("ARISSTO_USER"),
        password=required("ARISSTO_PASSWORD"), driver=os.getenv("ARISSTO_ODBC_DRIVER", "ODBC Driver 18 for SQL Server"),
        extra=os.getenv("ARISSTO_ODBC_EXTRA", "Encrypt=yes;TrustServerCertificate=yes;ApplicationIntent=ReadOnly"),
        connect_timeout=int(os.getenv("ARISSTO_CONNECT_TIMEOUT", "15")),
        query_timeout=int(os.getenv("ARISSTO_QUERY_TIMEOUT", "30")),
    )


def load_settings(target: str, env_file: str | None = None) -> Settings:
    if target not in {"local", "prod"}:
        raise ValueError("target must be local or prod")
    source = load_source_config(env_file)
    prefix = f"FINERACT_{target.upper()}_"
    tls_verify_name = prefix + "TLS_VERIFY"
    tls_verify = os.getenv(tls_verify_name, os.getenv("ARISSTO_SYNC_TLS_VERIFY", "true")).lower() not in {
        "0", "false", "no"
    }
    target_config = TargetConfig(
        name=target, api_url=required(prefix + "API_URL").rstrip("/"), api_user=required(prefix + "API_USER"),
        api_password=required(prefix + "API_PASSWORD"), tenant=os.getenv(prefix + "TENANT", "default"),
        pg_url=os.getenv(prefix + "PG_URL", "").strip() or None,
        expected_host=required(prefix + "EXPECTED_HOST"), tls_verify=tls_verify,
    )
    target_config.assert_expected_host()
    state = Path(os.getenv("ARISSTO_SYNC_STATE", ".arissto-sync/state.sqlite3"))
    mapping = Path(os.getenv("ARISSTO_SYNC_CLIENT_MAPPING", "config/clients.json"))
    family_mapping = Path(os.getenv("ARISSTO_SYNC_FAMILY_REFERENCE_MAPPING", "config/client_family_references.json"))
    pep_mapping = Path(os.getenv("ARISSTO_SYNC_CLIENT_PEP_MAPPING", "config/client_pep.json"))
    employee_mapping = Path(os.getenv("ARISSTO_SYNC_EMPLOYEE_MAPPING", "config/employees.json"))
    membership_mapping = Path(os.getenv(
        "ARISSTO_SYNC_MEMBERSHIP_MAPPING", "config/membership_share_capital.json"
    ))
    aml_alert_mapping = Path(os.getenv("ARISSTO_SYNC_AML_ALERT_MAPPING", "config/aml_alerts.json"))
    return Settings(source, target_config, state if state.is_absolute() else ROOT / state,
                    mapping if mapping.is_absolute() else ROOT / mapping,
                    family_mapping if family_mapping.is_absolute() else ROOT / family_mapping,
                    pep_mapping if pep_mapping.is_absolute() else ROOT / pep_mapping,
                    employee_mapping if employee_mapping.is_absolute() else ROOT / employee_mapping,
                    membership_mapping if membership_mapping.is_absolute() else ROOT / membership_mapping,
                    aml_alert_mapping if aml_alert_mapping.is_absolute() else ROOT / aml_alert_mapping)
