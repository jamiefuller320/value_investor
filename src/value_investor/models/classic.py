"""Classic absolute-threshold value screens."""

from __future__ import annotations

from typing import Any

from value_investor.models.base import ModelResult, ValueModel


class LynchPEGModel(ValueModel):
    """Peter Lynch: PEG < 1 — growth at a reasonable price."""

    id = "lynch_peg"
    name = "Lynch PEG"

    MAX_PEG = 1.0
    MIN_GROWTH = 0.05

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        pe = row.get("trailing_pe")
        growth = row.get("earnings_growth")
        failed: list[str] = []

        if pe is None or pe <= 0:
            return self._result(passed=False, score=0.0, failed_criteria=["missing positive P/E"])

        if growth is None or growth <= 0:
            return self._result(passed=False, score=0.2, failed_criteria=["missing or negative earnings growth"])

        if growth < self.MIN_GROWTH:
            failed.append(f"growth {growth:.1%} below {self.MIN_GROWTH:.0%} floor")

        peg = pe / (growth * 100)
        passed = peg < self.MAX_PEG and growth >= self.MIN_GROWTH
        score = max(0.0, 1.0 - peg) if peg < 2 else 0.0

        if not passed and peg >= self.MAX_PEG:
            failed.append(f"PEG {peg:.2f} >= {self.MAX_PEG}")

        reasons = [f"PEG={peg:.2f}", f"growth={growth:.1%}"]
        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)


class SchlossModel(ValueModel):
    """Walter Schloss: low P/B with conservative leverage."""

    id = "schloss"
    name = "Schloss Low P/B"

    MAX_PB = 1.2
    MAX_DE = 50.0

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        pb = row.get("price_to_book")
        de = row.get("debt_to_equity")
        failed: list[str] = []
        checks: list[tuple[str, bool, str]] = []

        if pb is not None:
            ok = pb < self.MAX_PB
            checks.append((f"P/B < {self.MAX_PB}", ok, f"P/B={pb:.2f}"))
            if not ok:
                failed.append("P/B too high")
        else:
            checks.append(("P/B", False, "missing"))
            failed.append("missing P/B")

        if de is not None:
            ok = de < self.MAX_DE
            checks.append((f"D/E < {self.MAX_DE}%", ok, f"D/E={de:.0f}%"))
            if not ok:
                failed.append("too much leverage")
        else:
            checks.append(("D/E", True, "not reported — skipped"))

        passed_count = sum(1 for _, ok, _ in checks if ok)
        score = passed_count / len(checks)
        passed = pb is not None and pb < self.MAX_PB and (de is None or de < self.MAX_DE)
        reasons = [f"{label}: {detail}" for label, ok, detail in checks if ok]

        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)


class DeepValueModel(ValueModel):
    """Deep value: simultaneously cheap on P/B and EV/EBITDA."""

    id = "deep_value"
    name = "Deep Value"

    MAX_PB = 1.0
    MAX_EV_EBITDA = 8.0

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        pb = row.get("price_to_book")
        ev = row.get("enterprise_value")
        ebitda = row.get("ebitda")
        failed: list[str] = []
        reasons: list[str] = []

        pb_ok = pb is not None and pb < self.MAX_PB
        ev_ebitda = (ev / ebitda) if ev and ebitda else None
        ev_ok = ev_ebitda is not None and ev_ebitda < self.MAX_EV_EBITDA

        if pb_ok:
            reasons.append(f"P/B={pb:.2f}")
        else:
            failed.append("P/B not below 1.0")

        if ev_ok:
            reasons.append(f"EV/EBITDA={ev_ebitda:.1f}")
        else:
            failed.append("EV/EBITDA not below 8")

        score = (int(pb_ok) + int(ev_ok)) / 2
        passed = pb_ok and ev_ok
        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)


class FCFYieldModel(ValueModel):
    """Absolute FCF yield screen — cash return to equity holders."""

    id = "fcf_yield"
    name = "FCF Yield"

    MIN_YIELD = 0.05

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        fcf = row.get("free_cashflow")
        mcap = row.get("market_cap")
        failed: list[str] = []

        if fcf is None or mcap is None or mcap <= 0:
            return self._result(passed=False, score=0.0, failed_criteria=["missing FCF or market cap"])

        yld = fcf / mcap
        passed = yld >= self.MIN_YIELD
        score = min(1.0, yld / (self.MIN_YIELD * 2))

        if not passed:
            failed.append(f"FCF yield {yld:.1%} below {self.MIN_YIELD:.0%}")

        return self._result(
            passed=passed,
            score=score,
            reasons=[f"FCF yield={yld:.1%}"],
            failed_criteria=failed,
        )


class EarningsYieldModel(ValueModel):
    """Earnings yield (E/P) — inverse P/E above hurdle."""

    id = "earnings_yield"
    name = "Earnings Yield"

    MIN_YIELD = 0.08

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        pe = row.get("trailing_pe")
        failed: list[str] = []

        if pe is None or pe <= 0:
            return self._result(passed=False, score=0.0, failed_criteria=["missing positive P/E"])

        yld = 1.0 / pe
        passed = yld >= self.MIN_YIELD
        score = min(1.0, yld / (self.MIN_YIELD * 1.5))

        if not passed:
            failed.append(f"earnings yield {yld:.1%} below {self.MIN_YIELD:.0%}")

        return self._result(
            passed=passed,
            score=score,
            reasons=[f"E/P={yld:.1%} (P/E={pe:.1f})"],
            failed_criteria=failed,
        )
