"""Dividend-focused value screens."""

from __future__ import annotations

from typing import Any, Self

import pandas as pd

from value_investor.models.base import ModelResult, ValueModel
from value_investor.models.fitted import UniverseFittedModel
from value_investor.models.ranking import percentile_rank


class HighDividendYieldModel(UniverseFittedModel):
    """Top-quartile dividend yield with positive earnings."""

    id = "high_dividend"
    name = "High Dividend Yield"

    MIN_YIELD = 0.03

    def fit(self, universe: pd.DataFrame) -> Self:
        self._fit_base(universe)
        return self

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        if self._universe is None:
            return self._result(passed=False, score=0.0, failed_criteria=["model not fitted"])

        yld = row.get("dividend_yield")
        pe = row.get("trailing_pe")
        failed: list[str] = []

        if yld is None:
            return self._result(passed=False, score=0.0, failed_criteria=["missing dividend yield"])

        rank = percentile_rank(self._universe["dividend_yield"], yld, higher_is_better=True)
        if rank is None:
            return self._result(passed=False, score=0.0, failed_criteria=["could not rank yield"])

        earnings_ok = pe is not None and pe > 0
        passed = rank >= 0.75 and yld >= self.MIN_YIELD and earnings_ok

        if yld < self.MIN_YIELD:
            failed.append(f"yield {yld:.1%} below {self.MIN_YIELD:.0%} floor")
        if rank < 0.75:
            failed.append("not in top quartile for yield")
        if not earnings_ok:
            failed.append("no positive earnings")

        return self._result(
            passed=passed,
            score=rank,
            reasons=[f"yield={yld:.1%}", f"universe rank {rank:.0%}"],
            failed_criteria=failed,
        )


class DividendGrowthModel(ValueModel):
    """Dividend payer with earnings growth — sustainable income compounder."""

    id = "dividend_growth"
    name = "Dividend Growth"

    MIN_YIELD = 0.02
    MIN_EARNINGS_GROWTH = 0.03

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        yld = row.get("dividend_yield")
        growth = row.get("earnings_growth")
        pe = row.get("trailing_pe")
        failed: list[str] = []
        checks: list[tuple[str, bool, str]] = []

        if yld is not None:
            ok = yld >= self.MIN_YIELD
            checks.append(("dividend payer", ok, f"yield={yld:.1%}"))
            if not ok:
                failed.append("yield too low")
        else:
            checks.append(("dividend", False, "missing"))
            failed.append("no dividend data")

        if growth is not None:
            ok = growth >= self.MIN_EARNINGS_GROWTH
            checks.append(("earnings growth", ok, f"growth={growth:.1%}"))
            if not ok:
                failed.append("earnings not growing")
        else:
            checks.append(("growth", False, "missing"))
            failed.append("missing earnings growth")

        if pe is not None:
            ok = 0 < pe < 25
            checks.append(("reasonable P/E", ok, f"P/E={pe:.1f}"))
            if not ok:
                failed.append("P/E out of range")
        else:
            checks.append(("P/E", False, "missing"))
            failed.append("missing P/E")

        passed_count = sum(1 for _, ok, _ in checks if ok)
        score = passed_count / len(checks)
        passed = passed_count >= 2 and yld is not None and yld >= self.MIN_YIELD
        reasons = [f"{label}: {detail}" for label, ok, detail in checks if ok]

        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)
