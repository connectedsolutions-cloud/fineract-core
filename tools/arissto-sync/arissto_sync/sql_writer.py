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
        "loans": frozenset({"upsert_loan_product_crosswalk"}),
        "delinquency-history": frozenset({"replace_historical_delinquency_tags"}),
        "membership-share-capital": frozenset({"upsert_membership_archive"}),
        "aml-alerts": frozenset({"upsert_aml_alerts"}),
        "mobile-collections": frozenset({"upsert_mobile_collection_metadata"}),
        "dte-history": frozenset({"create_historical_dte", "update_historical_mh_timestamps"}),
        "cheque-history": frozenset({"insert_historical_cheque_metadata"}),
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

    def reconcile_october_8_sandbox_delinquency_tags(
        self, *, run_id: str, cycle_id: str, target_fingerprint: str,
        source_through_date: str, fineract_starts: str,
        adopt_rows: list[tuple[Any, ...]], shift_ids: list[int],
        source_row_count: int, source_hash: str, source_interval_count: int,
        mapped_interval_count: int, unmapped_count: int, observed_at: Any,
        user_id: int,
    ) -> tuple[int, int]:
        """One reviewed sandbox repair; fixed SQL and exact candidate counts."""
        if (
            self.block != "delinquency-history"
            or run_id != "494db0368e3f4b538b898a7ba592b5e8"
            or cycle_id != "sandbox-2026-10-08-carry-forward-a"
            or target_fingerprint != "b9f6834b66790744"
            or source_through_date != "2026-10-08"
            or fineract_starts != "2026-10-09"
            or len(adopt_rows) != 2477
            or len(shift_ids) != 456
            or len(set(shift_ids)) != 456
            or mapped_interval_count != 5746
            or unmapped_count != 0
        ):
            raise PermissionError("Sandbox delinquency repair differs from the reviewed run and counts")
        shifted = self.connection.execute("""
            UPDATE m_loan_delinquency_tag_history h
               SET addedon_date=%s,last_modified_by=%s,last_modified_on_utc=%s,
                   version=h.version+1
              FROM m_loan l
             WHERE h.loan_id=l.id AND h.id=ANY(%s)
               AND l.external_id LIKE 'ARISSTO:CRD:%%'
               AND h.addedon_date=%s AND h.liftedon_date IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM credesal_loan_delinquency_tag_source p
                    WHERE p.tag_history_id=h.id
               )
        """, (fineract_starts, user_id, observed_at, shift_ids, source_through_date)).rowcount
        if shifted != 456:
            raise RuntimeError("Reviewed handoff native tag shift count changed")
        adopted = 0
        for (tag_id, loan_id, range_id, added, lifted, source_loan_id,
             classification, interval_hash) in adopt_rows:
            result = self.connection.execute("""
                INSERT INTO credesal_loan_delinquency_tag_source (
                    tag_history_id,source_system,source_loan_id,added_on_date,
                    lifted_on_date,classification,interval_hash,observed_at
                )
                SELECT h.id,'ARISSTO_CLOSE',%s,h.addedon_date,h.liftedon_date,%s,%s,%s
                  FROM m_loan_delinquency_tag_history h
                  JOIN m_loan l ON l.id=h.loan_id
                 WHERE h.id=%s AND h.loan_id=%s AND h.delinquency_range_id=%s
                   AND h.addedon_date=%s AND h.liftedon_date=%s
                   AND l.external_id=%s
                   AND NOT EXISTS (
                       SELECT 1 FROM credesal_loan_delinquency_tag_source p
                        WHERE p.tag_history_id=h.id
                   )
            """, (source_loan_id, classification, interval_hash, observed_at,
                  tag_id, loan_id, range_id, added, lifted,
                  f"ARISSTO:CRD:{source_loan_id}"))
            if result.rowcount != 1:
                raise RuntimeError("Reviewed native tag provenance candidate changed")
            adopted += 1
        self.connection.execute("""
            INSERT INTO credesal_loan_delinquency_history_manifest (
                source_system,source_through_date,source_row_count,source_hash,
                source_interval_count,imported_interval_count,
                unmapped_source_loan_count,accepted_at
            ) VALUES ('ARISSTO_CLOSE',%s,%s,%s,%s,%s,%s,%s)
        """, (source_through_date,source_row_count,source_hash,
              source_interval_count,adopted,unmapped_count,observed_at))
        return adopted, shifted
