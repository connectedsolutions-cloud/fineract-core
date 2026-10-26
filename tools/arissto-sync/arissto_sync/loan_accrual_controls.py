"""Source-owned accrual controls, separate from the eight monetary targets."""
from __future__ import annotations
from datetime import date, timedelta
from typing import Any


def freeze(loan: dict[str, Any], cutoff: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    source_day = date.fromisoformat(cutoff) - timedelta(days=1)
    paused = False
    previous_date = None
    previous_id = None
    for event in events:
        day = date.fromisoformat(event["effective_date"])
        source_id = int(event["source_event_id"])
        if (day > source_day or source_id <= 0 or not isinstance(event.get("blocked"), bool)
                or event["blocked"] == paused or previous_date is not None and
                (day < previous_date or day == previous_date and source_id <= previous_id)):
            raise ValueError("invalid_source_accrual_control_history")
        paused = event["blocked"]
        previous_date, previous_id = day, source_id
    snapshot = loan.get("_mora_cutover_snapshot") or {}
    flag = snapshot.get("CRD_CONGELADO")
    if flag is not None:
        flag = str(flag).strip()
        if flag not in {"0", "1"} or (flag == "1") != paused:
            raise ValueError("source_accrual_control_snapshot_history_conflict")
    if paused and not events:
        raise ValueError("source_accrual_control_missing_history")
    # Null is the observed never-frozen source representation; the complete
    # type-4 feed, rather than a zero interest balance, establishes no restriction.
    return {"revision": 1, "sourceDay": source_day.isoformat(), "fineractStarts": cutoff,
            "ordinaryInterestPaused": paused, "moraPaused": paused,
            "sourceScope": "arissto-type-4-whole-loan", "sourceEventIds": [int(e["source_event_id"]) for e in events]}


def _day(value: Any) -> date:
    return date(*value) if isinstance(value, list) else date.fromisoformat(str(value)[:10])


def verify(api: Any, loan: dict[str, Any], controls: dict[str, Any]) -> None:
    """Read actual calculator controls at handoff, including independent controls."""
    handoff = date.fromisoformat(controls["fineractStarts"])
    loan_id = int(loan["id"])
    history = api.request("GET", f"loans/{loan_id}/freezehistory")
    if not isinstance(history, list):
        raise RuntimeError("accrual_control_history_unreadable")
    whole = False
    mora_only = False
    for event in history:
        if _day(event["effectiveDate"]) > handoff:
            continue
        action = event.get("action")
        if action in {"FREEZE", "UNFREEZE"}:
            whole = action == "FREEZE"
        elif action in {"MORA_FREEZE", "MORA_UNFREEZE"}:
            mora_only = action == "MORA_FREEZE"
    pauses = api.request("GET", f"loans/{loan_id}/interest-pauses")
    if not isinstance(pauses, list):
        raise RuntimeError("accrual_control_interest_pauses_unreadable")
    interest_only = any(_day(p["startDate"]) <= handoff <= _day(p["endDate"]) for p in pauses)
    actual = {"ordinaryInterestPaused": whole or interest_only, "moraPaused": whole or mora_only}
    if any(actual[k] != controls[k] for k in actual):
        raise RuntimeError("accrual_control_native_state_mismatch")
    if bool(loan.get("isFrozen")) != whole:
        raise RuntimeError("accrual_control_loan_flag_history_mismatch")
