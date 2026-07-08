"""Graham enterprising investor screen."""

from __future__ import annotations

from typing import Any

from value_investor.models.base import ModelResult, ValueModel


class GrahamEnterprisingModel(ValueModel):
    """
    Enterprising investor screen — tolerates higher growth valuations but
    demands financial strength and earnings quality.
    """

    id = "graham_enterprising"
    name = "Graham Enterprising"

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        checks: list[tuple[str, bool, str]] = []
        failed: list[str] = []

        pe = row.get("trailing_pe")
        pb = row.get("price_to_book")
        de = row.get("debt_to_equity")
        roe = row.get("return_on_equity")
        earnings_growth = row.get("earnings_growth")

        if pe is not None and pe > 0:
            ok = pe < 25
            checks.append(("P/E < 25", ok, f"P/E={pe:.1f}"))
            if not ok:
                failed.append("P/E >= 25")
        else:
            checks.append(("Positive P/E", False, "missing"))
            failed.append("missing P/E")

        if pb is not None:
            ok = pb < 3.0
            checks.append(("P/B < 3", ok, f"P/B={pb:.2f}"))
            if not ok:
                failed.append("P/B >= 3")
        else:
            checks.append(("P/B", False, "missing"))
            failed.append("missing P/B")

        if de is not None:
            ok = de < 100  # yfinance reports as percentage
            checks.append(("Debt/equity < 100%", ok, f"D/E={de:.0f}%"))
            if not ok:
                failed.append("excessive leverage")
        else:
            checks.append(("Debt/equity", True, "not reported — skipped"))
            # don't penalize missing D/E heavily

        if roe is not None:
            ok = roe > 0.08
            checks.append(("ROE > 8%", ok, f"ROE={roe:.1%}"))
            if not ok:
                failed.append("ROE <= 8%")
        else:
            checks.append(("ROE", False, "missing"))
            failed.append("missing ROE")

        if earnings_growth is not None:
            ok = earnings_growth > 0
            checks.append(("Positive earnings growth", ok, f"growth={earnings_growth:.1%}"))
            if not ok:
                failed.append("negative earnings growth")
        else:
            checks.append(("Earnings growth", True, "not reported — skipped"))

        passed_count = sum(1 for _, ok, _ in checks if ok)
        score = passed_count / len(checks) if checks else 0.0
        # Require core valuation + quality checks
        core_ok = all(
            ok for label, ok, _ in checks if label in ("P/E < 25", "P/B < 3", "ROE > 8%")
        )
        passed = core_ok and score >= 0.75
        reasons = [f"{label}: {detail}" for label, ok, detail in checks if ok]

        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)
