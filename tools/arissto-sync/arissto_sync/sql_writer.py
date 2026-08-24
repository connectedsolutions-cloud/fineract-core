from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


class SqlWritePolicy:
    """Per-block allowlist for exceptional direct PostgreSQL writes.

    The client block intentionally has no entries. Adding an entry requires a reviewed
    block plan, a parameterized statement, and a post-write verifier.
    """

    ALLOWED: dict[str, frozenset[str]] = {
        "clients": frozenset(),
        "membership-share-capital": frozenset({"upsert_membership_archive"}),
        "aml-alerts": frozenset({"upsert_aml_alerts"}),
    }

    @classmethod
    def assert_allowed(cls, block: str, operation: str) -> None:
        if operation not in cls.ALLOWED.get(block, frozenset()):
            raise PermissionError(f"Direct SQL operation {block}.{operation} is not allowlisted")


class ControlledSqlWriter:
    def __init__(self, connection: Any, block: str):
        self.connection = connection
        self.block = block

    @contextmanager
    def entity_transaction(self, operation: str) -> Iterator[Any]:
        SqlWritePolicy.assert_allowed(self.block, operation)
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
