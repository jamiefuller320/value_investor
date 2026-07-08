"""Warren Buffett-inspired quality and economic-moat proxies."""

from __future__ import annotations

from typing import Any

from value_investor.models.base import ModelResult, ValueModel


class BuffettQualityModel(ValueModel):
    """
    Quality compounder screen: high ROE, manageable debt, consistent margins,
    and not paying an extreme multiple.
    """

    id = "buffett_quality"
    name = "Buffett Quality"

    MIN_ROE = 0.15
    MAX_DE = 60.0
    MIN_MARGIN = 0.08
    MAX_PE = 25.0

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        roe = row.get("return_on_equity")
        de = row.get("debt_to_equity")
        margin = row.get("profit_margins")
        pe = row.get("trailing_pe")
        failed: list[str] = []
        checks: list[tuple[str, bool, str]] = []

        if roe is not None:
            ok = roe >= self.MIN_ROE
            checks.append((f"ROE >= {self.MIN_ROE:.0%}", ok, f"ROE={roe:.1%}"))
            if not ok:
                failed.append("ROE too low")
        else:
            checks.append(("ROE", False, "missing"))
            failed.append("missing ROE")

        if de is not None:
            ok = de < self.MAX_DE
            checks.append((f"D/E < {self.MAX_DE}%", ok, f"D/E={de:.0f}%"))
            if not ok:
                failed.append("too much debt")
        else:
            checks.append(("D/E", True, "not reported — skipped"))

        if margin is not None:
            ok = margin >= self.MIN_MARGIN
            checks.append((f"margin >= {self.MIN_MARGIN:.0%}", ok, f"margin={margin:.1%}"))
            if not ok:
                failed.append("thin margins")
        else:
            checks.append(("margin", False, "missing"))
            failed.append("missing margins")

        if pe is not None and pe > 0:
            ok = pe < self.MAX_PE
            checks.append((f"P/E < {self.MAX_PE}", ok, f"P/E={pe:.1f}"))
            if not ok:
                failed.append("P/E too high")
        else:
            checks.append(("P/E", False, "missing"))
            failed.append("missing P/E")

        passed_count = sum(1 for _, ok, _ in checks if ok)
        score = passed_count / len(checks)
        core = roe is not None and roe >= self.MIN_ROE and pe is not None and 0 < pe < self.MAX_PE
        passed = core and score >= 0.75
        reasons = [f"{label}: {detail}" for label, ok, detail in checks if ok]

        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)


class EconomicMoatModel(ValueModel):
    """Moat proxy: sustained high ROE with above-average margins and low leverage."""

    id = "economic_moat"
    name = "Economic Moat"

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        roe = row.get("return_on_equity")
        roa = row.get("return_on_assets")
        margin = row.get("profit_margins")
        de = row.get("debt_to_equity")
        failed: list[str] = []
        points = 0
        max_points = 4
        reasons: list[str] = []

        if roe is not None and roe >= 0.18:
            points += 1
            reasons.append(f"high ROE={roe:.1%}")
        elif roe is not None:
            failed.append("ROE below 18%")

        if roa is not None and roa >= 0.08:
            points += 1
            reasons.append(f"solid ROA={roa:.1%}")
        elif roa is not None:
            failed.append("ROA below 8%")

        if margin is not None and margin >= 0.12:
            points += 1
            reasons.append(f"wide margin={margin:.1%}")
        elif margin is not None:
            failed.append("margins below 12%")

        if de is not None and de < 50:
            points += 1
            reasons.append(f"low leverage D/E={de:.0f}%")
        elif de is not None:
            failed.append("leverage too high")
        else:
            max_points -= 1

        score = points / max_points if max_points else 0
        passed = points >= 3
        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)
