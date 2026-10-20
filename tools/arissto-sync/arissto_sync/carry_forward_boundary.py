"""Per-run accounting boundary for a local carry-forward rebuild.

Arissto COB status is deliberately absent: it is observational, not a gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class CarryForwardBoundary:
    old_arissto_through: str
    old_fineract_starts: str
    arissto_through: str
    fineract_starts: str

    @classmethod
    def select(cls, old_fineract_starts: str, arissto_through: str) -> "CarryForwardBoundary":
        """Derive a fresh boundary from the date selected for this run."""
        old_t = date.fromisoformat(old_fineract_starts)
        selected_s = date.fromisoformat(arissto_through)
        if old_t.isoformat() != old_fineract_starts or selected_s.isoformat() != arissto_through:
            raise ValueError("Accounting dates must use YYYY-MM-DD")
        new_t = selected_s + timedelta(days=1)
        if new_t <= old_t:
            raise ValueError("Carry-forward requires a later Fineract start date")
        return cls(
            old_arissto_through=(old_t - timedelta(days=1)).isoformat(),
            old_fineract_starts=old_t.isoformat(),
            arissto_through=selected_s.isoformat(),
            fineract_starts=new_t.isoformat(),
        )
