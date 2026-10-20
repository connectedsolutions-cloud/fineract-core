"""Read-only Arissto client office chronology for native Fineract replay."""
from __future__ import annotations

from datetime import date
from typing import Any

from .arissto import select_rows


def _day(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def extract_client_office_observations(conn: Any) -> list[dict[str, Any]]:
    """Return source changes, retaining each raw first-observed day."""
    duplicates = select_rows(conn, """
        SELECT TOP (1) h.ID_ASOCIADO, CAST(c.FECHA_OPERACION AS date) AS business_date
        FROM dbo.AFI_HISTORICO_DIARIO h
        JOIN dbo.CIERRE_DIARIO c ON c.ID_CIERRE_DIARIO=h.ID_CIERRE_DIARIO
        GROUP BY h.ID_ASOCIADO, CAST(c.FECHA_OPERACION AS date)
        HAVING COUNT_BIG(*) > 1
    """)
    if duplicates:
        raise RuntimeError("duplicate_client_office_snapshot_day")
    rows = select_rows(conn, """
        WITH daily AS (
            SELECT h.ID_ASOCIADO,
                   CAST(c.FECHA_OPERACION AS date) AS business_date,
                   RTRIM(h.ID_SUCURSAL_ACTIVA) AS active_branch
            FROM dbo.AFI_HISTORICO_DIARIO h
            JOIN dbo.CIERRE_DIARIO c ON c.ID_CIERRE_DIARIO=h.ID_CIERRE_DIARIO
        ), sequenced AS (
            SELECT ID_ASOCIADO, business_date, active_branch,
                   LAG(business_date) OVER (
                       PARTITION BY ID_ASOCIADO ORDER BY business_date
                   ) AS previous_date,
                   LAG(active_branch) OVER (
                       PARTITION BY ID_ASOCIADO ORDER BY business_date
                   ) AS previous_branch
            FROM daily
        )
        SELECT s.ID_ASOCIADO AS source_client_id,
               RTRIM(s.NUMERO_AFILIACION) AS client_external_id,
               RTRIM(s.ID_SUCURSAL) AS original_branch,
               RTRIM(s.ID_SUCURSAL_ACTIVA) AS current_branch,
               q.previous_date, q.previous_branch,
               q.business_date AS observed_date, q.active_branch AS destination_branch
        FROM sequenced q
        JOIN dbo.AFI_SOCIO s ON s.ID_ASOCIADO=q.ID_ASOCIADO
        WHERE q.previous_branch IS NOT NULL
          AND q.previous_branch<>q.active_branch
        ORDER BY q.ID_ASOCIADO,q.business_date
    """)
    changed_client_ids = {int(row["source_client_id"]) for row in rows}
    current_differences = select_rows(conn, """
        SELECT ID_ASOCIADO AS source_client_id
        FROM dbo.AFI_SOCIO
        WHERE RTRIM(ID_SUCURSAL)<>RTRIM(ID_SUCURSAL_ACTIVA)
    """)
    if any(int(row["source_client_id"]) not in changed_client_ids for row in current_differences):
        raise RuntimeError("client_office_transition_missing_daily_history")
    return [dict(row) for row in rows]


def normalize_client_office_observations(
    rows: list[dict[str, Any]], office_mapping: dict[str, int],
    opening_dates: dict[int, date],
) -> list[dict[str, Any]]:
    """Floor only the target date; keep the source day for audit."""
    events: list[dict[str, Any]] = []
    by_client: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        client_key = str(row["client_external_id"]).strip()
        previous_branch = str(row["previous_branch"]).strip()
        destination_branch = str(row["destination_branch"]).strip()
        original_branch = str(row["original_branch"]).strip()
        current_branch = str(row["current_branch"]).strip()
        if not client_key or not previous_branch or not destination_branch:
            raise RuntimeError("incomplete_client_office_transition")
        if previous_branch not in office_mapping or destination_branch not in office_mapping:
            raise RuntimeError("unmapped_client_office_transition")
        observed_date = _day(row["observed_date"])
        previous_date = _day(row["previous_date"])
        if (observed_date - previous_date).days != 1:
            raise RuntimeError("client_office_transition_has_snapshot_gap")
        office_id = int(office_mapping[destination_branch])
        opening_date = opening_dates.get(office_id)
        if opening_date is None:
            raise RuntimeError("destination_office_has_no_opening_date")
        opening_date = _day(opening_date)
        effective_date = max(observed_date, opening_date)
        event = {
            "source_client_id": int(row["source_client_id"]),
            "client_external_id": client_key,
            "original_branch": original_branch,
            "current_branch": current_branch,
            "from_branch": previous_branch,
            "to_branch": destination_branch,
            "from_office_id": int(office_mapping[previous_branch]),
            "to_office_id": office_id,
            "observed_date": observed_date.isoformat(),
            "previous_observed_date": previous_date.isoformat(),
            "office_opening_date": opening_date.isoformat(),
            "effective_date": effective_date.isoformat(),
            "date_adjustment": "office-opening-floor" if effective_date > observed_date else None,
        }
        events.append(event)
        by_client.setdefault(client_key, []).append(event)
    for client_key, timeline in by_client.items():
        timeline.sort(key=lambda item: item["observed_date"])
        if timeline[0]["from_branch"] != timeline[0]["original_branch"]:
            raise RuntimeError("client_office_initial_branch_mismatch")
        for prior, later in zip(timeline, timeline[1:]):
            if prior["to_branch"] != later["from_branch"]:
                raise RuntimeError("client_office_timeline_disconnected")
            if prior["effective_date"] >= later["effective_date"]:
                raise RuntimeError("client_office_effective_dates_not_increasing")
        if timeline[-1]["to_branch"] != timeline[-1]["current_branch"]:
            raise RuntimeError("client_office_final_branch_mismatch")
    return sorted(events, key=lambda item: (item["effective_date"], item["source_client_id"]))


def plan_client_office_transfers(settings: Any, target_clients: dict[str, dict[str, Any]],
                                 included_client_keys: set[str],
                                 *, require_all: bool = False) -> list[dict[str, Any]]:
    """Freeze transfer candidates against the selected target's office openings."""
    import json

    from .arissto import source_connection
    from .connections import postgres_connection

    office_mapping = {
        str(key): int(value)
        for key, value in json.loads(settings.mapping_path.read_text())["office_mapping"].items()
    }
    with source_connection(settings.source) as conn:
        observations = extract_client_office_observations(conn)
    if not settings.target.pg_url:
        raise RuntimeError("client_office_transfers_require_target_postgres")
    with postgres_connection(settings.target.pg_url) as conn:
        openings = conn.execute(
            "SELECT id,opening_date FROM m_office WHERE id=ANY(%s)",
            (list(office_mapping.values()),),
        ).fetchall()
    opening_dates = {int(office_id): opening for office_id, opening in openings}
    events = normalize_client_office_observations(observations, office_mapping, opening_dates)
    selected: list[dict[str, Any]] = []
    for event in events:
        client_key = event["client_external_id"]
        if client_key not in included_client_keys:
            if require_all:
                raise RuntimeError("client_office_transfer_without_loan_action")
            continue
        client = target_clients.get(client_key)
        if client is None:
            raise RuntimeError("client_office_transfer_target_client_missing")
        selected.append({**event, "client_id": int(client["id"])})
    return selected


def target_client_office_transfer_blockers(settings: Any, events: list[dict[str, Any]]) -> list[str]:
    """Refuse retroactive transfer over already replayed future loan activity."""
    from .connections import postgres_connection

    if not events:
        return []
    if not settings.target.pg_url:
        return ["client_office_transfer_target_postgres_unavailable"]
    blockers: set[str] = set()
    with postgres_connection(settings.target.pg_url) as conn:
        for event in events:
            client_id = int(event["client_id"])
            accepted = conn.execute(
                "SELECT COUNT(*) FROM m_client_transfer_details WHERE client_id=%s "
                "AND from_office_id=%s AND to_office_id=%s "
                "AND proposed_transfer_date=%s AND transfer_type=2",
                (client_id, int(event["from_office_id"]), int(event["to_office_id"]),
                 event["effective_date"]),
            ).fetchone()[0]
            if int(accepted) == 1:
                continue
            if int(accepted) > 1:
                blockers.add("duplicate_native_client_office_transfer_history")
                continue
            savings_rows = conn.execute(
                "SELECT COUNT(*) FROM m_savings_account WHERE client_id=%s",
                (client_id,),
            ).fetchone()[0]
            if int(savings_rows):
                blockers.add("client_office_transfer_requires_savings_after_loans")
            later_loan_rows = conn.execute(
                "SELECT COUNT(*) FROM m_loan l WHERE l.client_id=%s AND ("
                "l.submittedon_date>=%s OR EXISTS ("
                "SELECT 1 FROM m_loan_transaction t WHERE t.loan_id=l.id "
                "AND t.transaction_date>=%s AND t.is_reversed=false))",
                (client_id, event["effective_date"], event["effective_date"]),
            ).fetchone()[0]
            if int(later_loan_rows):
                blockers.add("historical_office_transfer_requires_fresh_or_prefixed_loan_target")
    return sorted(blockers)


def attach_pretransfer_loan_balances(settings: Any, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Freeze positive source balances from the last day before each move."""
    from decimal import Decimal

    from .arissto import source_connection

    if not events:
        return []
    enriched: list[dict[str, Any]] = []
    with source_connection(settings.source) as conn:
        for event in events:
            rows = select_rows(conn, """
                SELECT l.ID_CREDITO AS source_loan_id,
                       x.business_date AS snapshot_date,
                       x.total_balance, x.interest_balance,
                       x.other_balance, x.penalty_balance
                FROM dbo.AFI_SOCIO s
                JOIN dbo.CRD_CARTERA l
                  ON l.ID_EMPRESA=s.ID_EMPRESA
                 AND l.ID_SUCURSAL_SOCIO=s.ID_SUCURSAL
                 AND l.ID_SOCIO=s.ID_SOCIO
                OUTER APPLY (
                    SELECT TOP (1) CAST(c.FECHA_OPERACION AS date) AS business_date,
                                   h.SALDO_TOTAL AS total_balance,
                                   h.SALDO_INTERES AS interest_balance,
                                   h.SALDO_OTROS AS other_balance,
                                   h.SALDO_MORA AS penalty_balance
                    FROM dbo.CRD_HISTORICO_DIARIO h
                    JOIN dbo.CIERRE_DIARIO c ON c.ID_CIERRE_DIARIO=h.ID_CIERRE_DIARIO
                    WHERE h.ID_CREDITO=l.ID_CREDITO
                      AND CAST(c.FECHA_OPERACION AS date)<CAST(? AS date)
                    ORDER BY c.FECHA_OPERACION DESC,h.ID_CRD_HISTORICO_DIARIO DESC
                ) x
                WHERE s.ID_ASOCIADO=?
                ORDER BY l.ID_CREDITO
            """, (event["effective_date"], int(event["source_client_id"])))
            active = []
            for row in rows:
                amount = Decimal(str(row["total_balance"] or 0))
                if amount > Decimal("0.00"):
                    if row["snapshot_date"] is None:
                        raise RuntimeError("active_transfer_loan_missing_source_snapshot")
                    components = {name: Decimal(str(row[name] or 0)) for name in (
                        "interest_balance", "other_balance", "penalty_balance"
                    )}
                    components["principal_balance"] = amount - sum(components.values())
                    if any(value < 0 for value in components.values()):
                        raise RuntimeError("client_office_transfer_source_balance_components_mismatch")
                    active.append({
                        "source_loan_id": int(row["source_loan_id"]),
                        "snapshot_date": _day(row["snapshot_date"]).isoformat(),
                        "total_balance": format(amount, "f"),
                        **{name: format(value, "f") for name, value in components.items()},
                    })
            enriched.append({**event, "active_source_loans": active})
    return enriched
