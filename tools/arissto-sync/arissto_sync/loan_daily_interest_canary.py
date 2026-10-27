"""Read-only, date-matched Arissto/Fineract interest canary.

Run from the sync-engine directory with ``python -m
arissto_sync.loan_daily_interest_canary``. This intentionally accepts only
namespaced loans in the disposable local sandbox.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from .arissto import select_rows, source_connection
from .config import load_settings
from .connections import FineractApi
from .loans import _find_loan


NAMESPACE = re.compile(r"[a-z0-9][a-z0-9-]{0,23}\Z")
CENT = Decimal("0.01")


def _day(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return date(*(int(part) for part in value))
    return date.fromisoformat(str(value)[:10])


def _amount(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def native_interest_as_of(loan: dict[str, Any], business_date: date) -> Decimal:
    """Mirror the cumulative summary's due/current-period interest formula."""
    periods = (loan.get("repaymentSchedule") or {}).get("periods") or []
    due = Decimal("0.00")
    current = Decimal("0.00")
    for period in periods:
        if period.get("period") in (None, 0):
            continue
        start, end = _day(period["fromDate"]), _day(period["dueDate"])
        if end <= business_date:
            due += _amount(period.get("interestOutstanding"))
        elif start <= business_date < end:
            length = (end - start).days
            if length <= 0:
                raise ValueError("Invalid target installment dates")
            elapsed = (business_date - start).days
            accrued = _amount(period.get("interestDue")) * Decimal(elapsed) / Decimal(length)
            accrued -= _amount(period.get("interestPaid")) + _amount(period.get("interestWaived"))
            current = max(accrued, Decimal("0.00")).quantize(CENT, rounding=ROUND_HALF_EVEN)
    return due + current


def compare(settings: Any, namespace: str, source_keys: list[int], first: date, last: date) -> dict[str, Any]:
    if settings.target.name != "local" or settings.target.tenant != "sandbox":
        raise ValueError("Daily interest canaries require the disposable local sandbox")
    if not NAMESPACE.fullmatch(namespace):
        raise ValueError("Invalid proof namespace")
    keys = sorted(set(source_keys))
    if not keys or len(keys) > 10 or any(key <= 0 for key in keys):
        raise ValueError("Supply one to ten positive source loan IDs")
    if last < first or (last - first).days > 30:
        raise ValueError("Use an ordered source-close window of at most 31 days")

    placeholders = ",".join("?" for _ in keys)
    sql = f"""
        SELECT h.ID_CREDITO, CAST(c.FECHA_OPERACION AS date) AS close_date,
               h.SALDO_INTERES, h.SALDO_PAGADO_CAPITAL, h.SALDO_PAGADO_INTERES,
               h.CRD_CONGELADO
        FROM dbo.CRD_HISTORICO_DIARIO h
        JOIN dbo.CIERRE_DIARIO c ON c.ID_CIERRE_DIARIO=h.ID_CIERRE_DIARIO
        WHERE c.CIERRE='1' AND CAST(c.FECHA_OPERACION AS date)>=?
          AND CAST(c.FECHA_OPERACION AS date)<=?
          AND h.ID_CREDITO IN ({placeholders})
        ORDER BY h.ID_CREDITO,c.FECHA_OPERACION,h.ID_CRD_HISTORICO_DIARIO
    """
    with source_connection(settings.source) as conn:
        source_rows = select_rows(conn, sql, (first, last, *keys))
    by_key: dict[int, dict[date, dict[str, Any]]] = {key: {} for key in keys}
    for row in source_rows:
        by_key[int(row["ID_CREDITO"])][_day(row["close_date"])] = row

    api = FineractApi(settings.target)
    results = []
    for key in keys:
        external_id = f"PROOF:{namespace}:ARISSTO:CRD:{key}"
        loan = _find_loan(api, external_id)
        if loan is None or loan.get("externalId") != external_id:
            raise ValueError(f"Missing proof loan for source key {key}")
        rows = []
        day = first
        while day <= last:
            source = by_key[key].get(day)
            if source is None:
                rows.append({"source_close": day.isoformat(), "missing_completed_close": True})
            else:
                # Arissto's completed close on S includes S's accrual. The
                # cumulative Fineract summary at S+1 includes the same day.
                native_date = day + timedelta(days=1)
                native = native_interest_as_of(loan, native_date)
                source_interest = _amount(source["SALDO_INTERES"])
                rows.append({
                    "source_close": day.isoformat(),
                    "native_business_date": native_date.isoformat(),
                    "source_interest": format(source_interest, ".2f"),
                    "native_interest": format(native, ".2f"),
                    "difference": format(native - source_interest, ".2f"),
                    "source_frozen": str(source.get("CRD_CONGELADO") or "0").strip() == "1",
                    "source_paid_principal": format(_amount(source["SALDO_PAGADO_CAPITAL"]), ".2f"),
                    "source_paid_interest": format(_amount(source["SALDO_PAGADO_INTERES"]), ".2f"),
                })
            day += timedelta(days=1)
        results.append({"source_key": key, "proof_loan_id": loan["id"], "days": rows})
    return {"target_fingerprint": settings.target.fingerprint,
            "proof_namespace": namespace, "comparison": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof-namespace", required=True)
    parser.add_argument("--source-key", type=int, action="append", required=True)
    parser.add_argument("--from-date", type=date.fromisoformat, required=True)
    parser.add_argument("--through-date", type=date.fromisoformat, required=True)
    parser.add_argument("--env-file")
    args = parser.parse_args()
    result = compare(load_settings("local", args.env_file), args.proof_namespace,
                     args.source_key, args.from_date, args.through_date)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
