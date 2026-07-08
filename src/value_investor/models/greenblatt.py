"""Joel Greenblatt Magic Formula — high earnings yield + high return on capital."""

from __future__ import annotations

from typing import Any, Self

import pandas as pd

from value_investor.models.base import ModelResult
from value_investor.models.fitted import UniverseFittedModel
from value_investor.models.ranking import percentile_rank


class MagicFormulaModel(UniverseFittedModel):
    """
    Ranks on EBIT/EV (earnings yield) and ROIC proxy.

    Passes names in the top half of the universe on the combined rank.
    """

    id = "magic_formula"
    name = "Magic Formula"

    def fit(self, universe: pd.DataFrame) -> Self:
        self._fit_base(universe)
        df = self._require_universe()

        ey_rank = df["earnings_yield_ebit"].rank(ascending=False, na_option="bottom", pct=True)
        roic_rank = df["roic_proxy"].rank(ascending=False, na_option="bottom", pct=True)
        df = df.copy()
        df["magic_combined_rank"] = (ey_rank + roic_rank) / 2
        self._universe = df
        return self

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        if self._universe is None:
            return self._result(passed=False, score=0.0, failed_criteria=["model not fitted"])

        ev = row.get("enterprise_value")
        ebit = row.get("ebit")
        earnings_yield = (ebit / ev) if ebit and ev else None

        ey_rank = percentile_rank(
            self._universe["earnings_yield_ebit"], earnings_yield, higher_is_better=True
        )

        invested = None
        if row.get("total_assets") and row.get("total_current_liabilities") is not None:
            invested = row["total_assets"] - row["total_current_liabilities"]
        roic = (ebit / invested) if ebit and invested else None
        roic_rank = percentile_rank(self._universe["roic_proxy"], roic, higher_is_better=True)

        if ey_rank is None or roic_rank is None:
            return self._result(
                passed=False,
                score=0.0,
                failed_criteria=["missing EBIT/EV or ROIC inputs"],
            )

        combined = (ey_rank + roic_rank) / 2
        passed = combined >= 0.5
        reasons = []
        if ey_rank >= 0.5:
            reasons.append(f"earnings yield rank {ey_rank:.0%}")
        if roic_rank >= 0.5:
            reasons.append(f"ROIC rank {roic_rank:.0%}")

        failed = [] if passed else ["below top half on combined Magic Formula rank"]
        return self._result(passed=passed, score=combined, reasons=reasons, failed_criteria=failed)
