"""David Dreman contrarian dividend-value screen."""

from __future__ import annotations

from typing import Any, Self

import pandas as pd

from value_investor.models.base import ModelResult
from value_investor.models.fitted import UniverseFittedModel
from value_investor.models.ranking import percentile_rank


class DremanContrarianModel(UniverseFittedModel):
    """
    Contrarian value: bottom quintile P/E, above-median dividend yield,
    and below-median P/B within the universe.
    """

    id = "dreman_contrarian"
    name = "Dreman Contrarian"

    def fit(self, universe: pd.DataFrame) -> Self:
        self._fit_base(universe)
        return self

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        if self._universe is None:
            return self._result(passed=False, score=0.0, failed_criteria=["model not fitted"])

        pe_rank = percentile_rank(
            self._universe["trailing_pe"], row.get("trailing_pe"), higher_is_better=False
        )
        pb_rank = percentile_rank(
            self._universe["price_to_book"], row.get("price_to_book"), higher_is_better=False
        )
        div_rank = percentile_rank(
            self._universe["dividend_yield"], row.get("dividend_yield"), higher_is_better=True
        )

        ranks = [r for r in (pe_rank, pb_rank, div_rank) if r is not None]
        if len(ranks) < 2:
            return self._result(passed=False, score=0.0, failed_criteria=["missing valuation data"])

        failed: list[str] = []
        reasons: list[str] = []
        checks_passed = 0

        if pe_rank is not None and pe_rank >= 0.75:
            checks_passed += 1
            reasons.append(f"low P/E rank {pe_rank:.0%}")
        elif pe_rank is not None:
            failed.append("P/E not in bottom quartile")

        if pb_rank is not None and pb_rank >= 0.6:
            checks_passed += 1
            reasons.append(f"low P/B rank {pb_rank:.0%}")
        elif pb_rank is not None:
            failed.append("P/B not cheap vs universe")

        if div_rank is not None and div_rank >= 0.5:
            checks_passed += 1
            reasons.append(f"dividend rank {div_rank:.0%}")
        elif div_rank is not None:
            failed.append("dividend yield below median")

        score = sum(ranks) / len(ranks)
        passed = checks_passed >= 2 and (pe_rank or 0) >= 0.6
        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)
