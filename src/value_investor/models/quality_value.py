"""Quality-at-a-reasonable-price style screen."""

from __future__ import annotations

from typing import Any

from value_investor.models.base import ModelResult, ValueModel


class QualityValueModel(ValueModel):
    """
    Combines profitability and balance-sheet quality with moderate valuation.

    Inspired by Buffett/Munger quality-value: durable returns on capital,
    manageable leverage, and not paying extreme multiples.
    """

    id = "quality_value"
    name = "Quality Value"

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        checks: list[tuple[str, bool, str]] = []
        failed: list[str] = []

        roe = row.get("return_on_equity")
        margins = row.get("profit_margins")
        de = row.get("debt_to_equity")
        pe = row.get("trailing_pe")
        fcf = row.get("free_cashflow")
        market_cap = row.get("market_cap")

        if roe is not None:
            ok = roe >= 0.12
            checks.append(("ROE >= 12%", ok, f"ROE={roe:.1%}"))
            if not ok:
                failed.append("ROE below 12%")
        else:
            checks.append(("ROE", False, "missing"))
            failed.append("missing ROE")

        if margins is not None:
            ok = margins >= 0.05
            checks.append(("Profit margin >= 5%", ok, f"margin={margins:.1%}"))
            if not ok:
                failed.append("thin margins")
        else:
            checks.append(("Profit margin", False, "missing"))
            failed.append("missing margins")

        if de is not None:
            ok = de < 80
            checks.append(("Debt/equity < 80%", ok, f"D/E={de:.0f}%"))
            if not ok:
                failed.append("high leverage")
        else:
            checks.append(("Debt/equity", True, "not reported — skipped"))

        if pe is not None and pe > 0:
            ok = pe < 20
            checks.append(("P/E < 20", ok, f"P/E={pe:.1f}"))
            if not ok:
                failed.append("P/E >= 20")
        else:
            checks.append(("P/E", False, "missing"))
            failed.append("missing P/E")

        if fcf is not None and market_cap is not None and market_cap > 0:
            fcf_yield = fcf / market_cap
            ok = fcf_yield >= 0.03
            checks.append(("FCF yield >= 3%", ok, f"FCF yield={fcf_yield:.1%}"))
            if not ok:
                failed.append("FCF yield below 3%")
        else:
            checks.append(("FCF yield", False, "missing FCF or market cap"))
            failed.append("cannot compute FCF yield")

        passed_count = sum(1 for _, ok, _ in checks if ok)
        score = passed_count / len(checks) if checks else 0.0
        passed = score >= 0.8 and (roe is None or roe >= 0.12)
        reasons = [f"{label}: {detail}" for label, ok, detail in checks if ok]

        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)
