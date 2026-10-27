"""Conservatively reconstruct active source-day state before later ordinary payments.

This is not a general temporal reconstruction of revised or reversed loans.
Unsupported after-boundary history keeps the existing quarantine.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _day(value: Any) -> str:
    return str(value or "")[:10]


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def bound_active_loan_histories(loans: list[dict], lifecycles: dict[int, dict], cutoff: str,
                                supported_transactions: dict[str, str]) -> None:
    source_day = (date.fromisoformat(cutoff) - timedelta(days=1)).isoformat()
    for loan in loans:
        counts = loan.get("_post_cutover_source_events") or {}
        history = lifecycles.get(int(loan["ID_CREDITO"])) or {}
        snapshot = loan.get("_mora_cutover_snapshot") or {}
        if (not counts or set(counts) != {"movements"} or loan.get("_mora_cutover_snapshot_missing")
                or _text(loan.get("source_state")) != "1" or _text(snapshot.get("ID_ESTADO_CARTERA")) != "1"
                or _day(snapshot.get("source_day")) != source_day
                or history.get("refinance_incoming") or history.get("refinance_outgoing")
                or (history.get("schedule_adjustment_summary") or {}).get("adjustment_count")):
            continue
        movements = history.get("movements") or []
        later = [row for row in movements if _day(row.get("FECHA_OPERACION")) >= cutoff]
        prior = [row for row in movements if _day(row.get("FECHA_OPERACION")) < cutoff]
        def role(row: dict) -> str:
            return supported_transactions.get(f'{row.get("CODIGO_SISTEMA")}:{_text(row.get("ID_TRANSACCION"))}', "")
        payment_roles = {"repayment", "mobile-collection-repayment"}
        if (not later or len(later) != counts["movements"]
                or any(role(row) not in payment_roles for row in later)
                or any(_text(row.get("REVERSION")) not in {"", "0"} or "reversal" in role(row) for row in movements)
                or any(not _day(row.get("FECHA_OPERACION")) for row in movements)):
            continue
        payments = [row for row in prior if role(row) in payment_roles | {"adjusted-repayment"}]
        # A dated close plus exact paid counters corroborates completeness of
        # retained principal/interest cash history; never just discard a guard.
        if any(snapshot.get(counter) is None or sum((_money(row.get(component)) for row in payments), Decimal(0))
               != _money(snapshot[counter]) for component, counter in
               (("MONTO_CAPITAL", "SALDO_PAGADO_CAPITAL"), ("MONTO_INTERES", "SALDO_PAGADO_INTERES"))):
            continue
        if snapshot.get("MONTO_DESEMBOLSADO") is None:
            continue
        later_ids = {_text(row["ID_MOVIMIENTO_CARTERA"]) for row in later}
        history["movements"] = prior
        history["charge_details"] = [row for row in history.get("charge_details") or []
                                     if _text(row.get("ID_MOVIMIENTO_CARTERA")) not in later_ids]
        for field in ("SALDO_INTERES", "SALDO_MORA", "SALDO_RECARGOS", "SALDO_SEGURO", "SALDO_TOTAL", "MONTO_DESEMBOLSADO"):
            if snapshot.get(field) is not None:
                loan[field] = snapshot[field]
        loan["ULTIMO_SALDO"] = _money(snapshot["MONTO_DESEMBOLSADO"]) - _money(snapshot["SALDO_PAGADO_CAPITAL"])
        loan["SALDO_CAPITAL"] = snapshot["SALDO_PAGADO_CAPITAL"]
        loan["_bounded_source_window"] = {
            "policy": "active-close-before-later-payments-v1", "source_through_date": source_day,
            "fineract_starts": cutoff, "excluded_movement_count": len(later),
            "excluded_movement_ids": sorted(later_ids), "paid_counters_corroborated": True,
        }
        del loan["_post_cutover_source_events"]
