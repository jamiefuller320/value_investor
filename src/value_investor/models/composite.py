"""Cross-sectional composite value score."""

from __future__ import annotations

from typing import Any, Self

import pandas as pd

from value_investor.models.base import ModelResult
from value_investor.models.fitted import UniverseFittedModel
from value_investor.models.ranking import percentile_rank


class CompositeValueModel(UniverseFittedModel):
    """
    Ranks companies on a weighted blend of cheapness and shareholder yield.

    Must be calibrated with `fit(universe_df)` before `evaluate` for percentile ranks.
    """

    id = "composite_value"
    name = "Composite Value"

    WEIGHTS = {
        "trailing_pe": 0.25,
        "price_to_book": 0.20,
        "dividend_yield": 0.20,
        "fcf_yield": 0.20,
        "ev_ebitda": 0.15,
    }

    def fit(self, universe: pd.DataFrame) -> Self:
        self._fit_base(universe)
        return self

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        if self._universe is None or self._universe.empty:
            return self._result(
                passed=False,
                score=0.0,
                failed_criteria=["composite model not fitted — run fit() on universe first"],
            )

        scores: list[float] = []
        reasons: list[str] = []
        failed: list[str] = []

        pe_rank = percentile_rank(
            self._universe["trailing_pe"], row.get("trailing_pe"), higher_is_better=False
        )
        pb_rank = percentile_rank(
            self._universe["price_to_book"], row.get("price_to_book"), higher_is_better=False
        )
        div_rank = percentile_rank(
            self._universe["dividend_yield"], row.get("dividend_yield"), higher_is_better=True
        )

        fcf_yield = None
        if row.get("free_cashflow") is not None and row.get("market_cap"):
            fcf_yield = row["free_cashflow"] / row["market_cap"]
        fcf_rank = percentile_rank(
            self._universe.get("fcf_yield", pd.Series(dtype=float)),
            fcf_yield,
            higher_is_better=True,
        )

        ev_ebitda = None
        if row.get("enterprise_value") and row.get("ebitda"):
            ev_ebitda = row["enterprise_value"] / row["ebitda"]
        ev_rank = percentile_rank(
            self._universe.get("ev_ebitda", pd.Series(dtype=float)),
            ev_ebitda,
            higher_is_better=False,
        )

        components = [
            ("trailing_pe", pe_rank, self.WEIGHTS["trailing_pe"]),
            ("price_to_book", pb_rank, self.WEIGHTS["price_to_book"]),
            ("dividend_yield", div_rank, self.WEIGHTS["dividend_yield"]),
            ("fcf_yield", fcf_rank, self.WEIGHTS["fcf_yield"]),
            ("ev_ebitda", ev_rank, self.WEIGHTS["ev_ebitda"]),
        ]

        for metric, rank, weight in components:
            if rank is None:
                failed.append(f"missing {metric}")
                continue
            scores.append(rank * weight)
            if rank >= 0.7:
                reasons.append(f"top-tier on {metric} (percentile {rank:.0%})")

        total_weight = sum(w for _, r, w in components if r is not None)
        score = sum(scores) / total_weight if total_weight else 0.0
        passed = score >= 0.65 and len(failed) <= 2

        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)
