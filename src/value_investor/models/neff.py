"""Nancy Tengler / John Neff style value screens."""

from __future__ import annotations

from typing import Any

from value_investor.models.base import ModelResult, ValueModel


class NeffPEGYModel(ValueModel):
    """
    John Neff PEGY: (P/E) / (earnings growth + dividend yield).

    Lower is better; pass below 1.0.
    """

    id = "neff_pegy"
    name = "Neff PEGY"

    MAX_PEGY = 1.0

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        pe = row.get("trailing_pe")
        growth = row.get("earnings_growth")
        yld = row.get("dividend_yield") or 0.0
        failed: list[str] = []

        if pe is None or pe <= 0:
            return self._result(passed=False, score=0.0, failed_criteria=["missing positive P/E"])

        denominator = (growth or 0) + yld
        if denominator <= 0:
            return self._result(passed=False, score=0.0, failed_criteria=["no growth or dividend yield"])

        pegy = pe / (denominator * 100)
        passed = pegy < self.MAX_PEGY
        score = max(0.0, 1.0 - pegy) if pegy < 2 else 0.0

        if not passed:
            failed.append(f"PEGY {pegy:.2f} >= {self.MAX_PEGY}")

        return self._result(
            passed=passed,
            score=score,
            reasons=[f"PEGY={pegy:.2f}", f"growth={growth or 0:.1%}", f"yield={yld:.1%}"],
            failed_criteria=failed,
        )


class LowPEHighYieldModel(ValueModel):
    """Simple combined income-value: low P/E plus meaningful dividend."""

    id = "low_pe_high_yield"
    name = "Low P/E + High Yield"

    MAX_PE = 12.0
    MIN_YIELD = 0.04

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        pe = row.get("trailing_pe")
        yld = row.get("dividend_yield")
        failed: list[str] = []

        pe_ok = pe is not None and 0 < pe < self.MAX_PE
        yld_ok = yld is not None and yld >= self.MIN_YIELD

        if not pe_ok:
            failed.append(f"P/E not below {self.MAX_PE}")
        if not yld_ok:
            failed.append(f"yield below {self.MIN_YIELD:.0%}")

        score = (int(pe_ok) + int(yld_ok)) / 2
        passed = pe_ok and yld_ok
        reasons = []
        if pe_ok:
            reasons.append(f"P/E={pe:.1f}")
        if yld_ok:
            reasons.append(f"yield={yld:.1%}")

        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)
