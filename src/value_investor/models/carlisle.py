"""Tobias Carlisle Acquirer's Multiple — low EV/EBIT."""

from __future__ import annotations

from typing import Any, Self

import pandas as pd

from value_investor.models.base import ModelResult
from value_investor.models.fitted import UniverseFittedModel
from value_investor.models.ranking import percentile_rank


class AcquirersMultipleModel(UniverseFittedModel):
    """Low enterprise value to EBIT — what a private acquirer would pay."""

    id = "acquirers_multiple"
    name = "Acquirer's Multiple"

    ABSOLUTE_MAX = 12.0

    def fit(self, universe: pd.DataFrame) -> Self:
        self._fit_base(universe)
        return self

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        if self._universe is None:
            return self._result(passed=False, score=0.0, failed_criteria=["model not fitted"])

        ev = row.get("enterprise_value")
        ebit = row.get("ebit")
        if not ev or not ebit or ebit <= 0:
            return self._result(passed=False, score=0.0, failed_criteria=["missing EV or EBIT"])

        multiple = ev / ebit
        rank = percentile_rank(self._universe["ev_ebit"], multiple, higher_is_better=False)
        if rank is None:
            return self._result(passed=False, score=0.0, failed_criteria=["could not rank EV/EBIT"])

        passed = rank >= 0.6 and multiple < self.ABSOLUTE_MAX
        failed = []
        if multiple >= self.ABSOLUTE_MAX:
            failed.append(f"EV/EBIT {multiple:.1f} above {self.ABSOLUTE_MAX}")
        if rank < 0.6:
            failed.append("not in top 40% cheapest on EV/EBIT")

        return self._result(
            passed=passed,
            score=rank,
            reasons=[f"EV/EBIT={multiple:.1f}", f"universe rank {rank:.0%}"],
            failed_criteria=failed,
        )
