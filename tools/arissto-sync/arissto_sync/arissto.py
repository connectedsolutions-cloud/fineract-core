"""Self-contained, read-only Arissto SQL Server connection helper."""

from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from typing import Any

from .config import SourceConfig


READ_ONLY_SQL = re.compile(r"^\s*(SELECT|WITH)\b", re.I)
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESERVED_EXTRA_KEYS = {"driver", "server", "database", "uid", "user", "pwd", "password", "trusted_connection"}
# pyodbc does not expose SQL_MODE_READ_ONLY on every supported release.
# The ODBC specification defines the value as 1.
ODBC_MODE_READ_ONLY = 1


def source_fingerprint(config: SourceConfig) -> str:
    material = f"{config.server.lower()}:{config.port}/{config.database.lower()}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _validate_extra(extra: str) -> None:
    for item in extra.split(";"):
        if not item.strip() or "=" not in item:
            continue
        key = item.split("=", 1)[0].strip().lower()
        if key in RESERVED_EXTRA_KEYS:
            raise ValueError(f"ARISSTO_ODBC_EXTRA cannot override {key}")


def connection_string(config: SourceConfig) -> str:
    """Build the ODBC string. Callers must never log the returned value."""
    _validate_extra(config.extra)
    parts = [
        f"DRIVER={{{config.driver}}}",
        f"SERVER={config.server},{config.port}",
        f"DATABASE={config.database}",
        f"UID={config.user}",
        f"PWD={config.password}",
        config.extra,
    ]
    return ";".join(part.rstrip(";") for part in parts if part) + ";"


@contextmanager
def source_connection(config: SourceConfig):
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError("pyodbc is required; install requirements.txt") from exc

    conn = pyodbc.connect(
        connection_string(config),
        timeout=config.connect_timeout,
        autocommit=False,
    )
    try:
        conn.set_attr(pyodbc.SQL_ATTR_ACCESS_MODE, ODBC_MODE_READ_ONLY)
        conn.timeout = config.query_timeout
        yield conn
    finally:
        conn.rollback()
        conn.close()


def select_rows(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    stripped = sql.rstrip()
    if not READ_ONLY_SQL.match(sql) or ";" in stripped.rstrip(";"):
        raise ValueError("Arissto queries must be a single SELECT or WITH statement")
    cursor = conn.cursor()
    cursor.execute(sql, params)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def check_source(config: SourceConfig) -> dict[str, Any]:
    """Connect and return non-sensitive identity and permission diagnostics."""
    sql = """
        SELECT
            DB_NAME() AS database_name,
            CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128)) AS product_version,
            CAST(SERVERPROPERTY('Edition') AS nvarchar(128)) AS edition,
            IS_MEMBER('db_datareader') AS is_datareader,
            IS_MEMBER('db_datawriter') AS is_datawriter,
            IS_MEMBER('db_owner') AS is_db_owner,
            IS_SRVROLEMEMBER('sysadmin') AS is_sysadmin
    """
    with source_connection(config) as conn:
        cursor = conn.cursor()
        cursor.execute(sql)
        row = cursor.fetchone()

    is_datawriter = bool(row[4])
    is_db_owner = bool(row[5])
    is_sysadmin = bool(row[6])
    return {
        "ok": True,
        "source": {
            "fingerprint": source_fingerprint(config),
            "database": row[0],
            "product_version": row[1],
            "edition": row[2],
            "driver": config.driver,
        },
        "permissions": {
            "db_datareader": bool(row[3]),
            "db_datawriter": is_datawriter,
            "db_owner": is_db_owner,
            "sysadmin": is_sysadmin,
            "read_only_login_verified": not (is_datawriter or is_db_owner or is_sysadmin),
        },
        "note": "Application read-only guards are active; database login permissions remain the authoritative boundary.",
    }
