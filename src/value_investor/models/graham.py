"""Benjamin Graham defensive investor screen (adapted for available data)."""

from __future__ import annotations

from typing import Any

from value_investor.models.base import ModelResult, ValueModel


class GrahamDefensiveModel(ValueModel):
    """
    Graham's defensive criteria, simplified for yfinance fundamentals.

    Classic rules adapted:
    - Adequate size (FTSE 100 membership assumed)
    - P/E below 15
    - P/B below 1.5 (or P/E × P/B < 22.5)
    - Current ratio >= 2
    - Positive earnings (proxy: trailing P/E exists and > 0)
    - Dividend payer (yield > 0)
    """

    id = "graham_defensive"
    name = "Graham Defensive"

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        checks: list[tuple[str, bool, str]] = []
        failed: list[str] = []

        pe = row.get("trailing_pe")
        pb = row.get("price_to_book")
        current_ratio = row.get("current_ratio")
        div_yield = row.get("dividend_yield")

        if pe is not None and pe > 0:
            ok = pe < 15
            checks.append(("P/E < 15", ok, f"P/E={pe:.1f}"))
            if not ok:
                failed.append("P/E >= 15")
        else:
            checks.append(("Positive earnings (P/E)", False, "missing or negative P/E"))
            failed.append("no positive trailing P/E")

        if pb is not None:
            pe_pb = (pe or 0) * pb
            ok = pb < 1.5 or (pe is not None and pe_pb < 22.5)
            checks.append(("P/B < 1.5 or P/E×P/B < 22.5", ok, f"P/B={pb:.2f}"))
            if not ok:
                failed.append("valuation too rich on P/B or P/E×P/B")
        else:
            checks.append(("P/B available", False, "missing P/B"))
            failed.append("missing P/B")

        if current_ratio is not None:
            ok = current_ratio >= 2.0
            checks.append(("Current ratio >= 2", ok, f"CR={current_ratio:.2f}"))
            if not ok:
                failed.append("current ratio < 2")
        else:
            checks.append(("Current ratio", False, "missing"))
            failed.append("missing current ratio")

        if div_yield is not None:
            ok = div_yield > 0
            checks.append(("Dividend payer", ok, f"yield={div_yield:.2%}"))
            if not ok:
                failed.append("no dividend")
        else:
            checks.append(("Dividend payer", False, "missing yield"))
            failed.append("missing dividend yield")

        passed_count = sum(1 for _, ok, _ in checks if ok)
        score = passed_count / len(checks) if checks else 0.0
        passed = passed_count == len(checks) and len(checks) >= 4
        reasons = [f"{label}: {detail}" for label, ok, detail in checks if ok]

        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)
