"""Turn stored Arissto daily classifications into native Fineract tag intervals.

The source classification is authoritative for historical dates. Days past due
is retained as evidence, never used to select or reject a historical category.
Intervals use Fineract's added-on inclusive / lifted-on exclusive dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Iterator


CLASSIFICATIONS = {
    "1": "A1", "2": "A2", "3": "B", "4": "C1",
    "5": "C2", "6": "D1", "7": "D2", "8": "E",
}


@dataclass(frozen=True)
class DailyClassification:
    source_loan_id: str
    close_date: date
    classification_id: str
    days_past_due: int | None


@dataclass(frozen=True)
class TagInterval:
    source_loan_id: str
    classification: str
    added_on_date: date
    lifted_on_date: date


def compress_classifications(
    rows: Iterable[DailyClassification], *, source_through_date: date,
) -> list[TagInterval]:
    """Compress consecutive observed days; leave missing closes uncovered.

    The final interval ends after the inclusive Arissto-owned date. A future
    native Fineract tag may begin on that following day without overlap.
    """
    ordered = sorted(rows, key=lambda row: (row.source_loan_id, row.close_date))
    return list(compress_sorted_classifications(ordered, source_through_date=source_through_date))


def compress_sorted_classifications(
    rows: Iterable[DailyClassification], *, source_through_date: date,
) -> Iterator[TagInterval]:
    """Stream intervals from rows ordered by source loan ID and close date."""
    previous: DailyClassification | None = None
    start: date | None = None
    completed_loans: set[str] = set()
    for row in rows:
        if not row.source_loan_id.strip():
            raise ValueError("Historical classification has no source loan ID")
        if row.classification_id not in CLASSIFICATIONS:
            raise ValueError(f"Unknown Arissto classification: {row.classification_id}")
        if row.days_past_due is not None and row.days_past_due < 0:
            raise ValueError("Historical days past due cannot be negative")
        if row.close_date > source_through_date:
            raise ValueError("Historical close exceeds Arissto source-through date")
        if row.source_loan_id in completed_loans:
            raise ValueError("Historical classifications revisit a completed loan")
        if previous is not None and previous.source_loan_id == row.source_loan_id:
            if row.close_date < previous.close_date:
                raise ValueError("Historical close dates are not ordered")
            if previous.close_date == row.close_date:
                raise ValueError(f"Duplicate historical close for loan {row.source_loan_id}")
            consecutive = row.close_date == previous.close_date + timedelta(days=1)
            if not consecutive or row.classification_id != previous.classification_id:
                assert start is not None
                yield TagInterval(previous.source_loan_id,
                                  CLASSIFICATIONS[previous.classification_id],
                                  start, previous.close_date + timedelta(days=1))
                start = row.close_date
        else:
            if previous is not None:
                assert start is not None
                yield TagInterval(previous.source_loan_id,
                                  CLASSIFICATIONS[previous.classification_id],
                                  start, previous.close_date + timedelta(days=1))
                completed_loans.add(previous.source_loan_id)
            start = row.close_date
        previous = row
    if previous is not None:
        assert start is not None
        yield TagInterval(previous.source_loan_id,
                          CLASSIFICATIONS[previous.classification_id],
                          start, previous.close_date + timedelta(days=1))
