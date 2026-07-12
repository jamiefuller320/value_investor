"""Risk-family screens: earnings quality and financial health."""

from __future__ import annotations

from typing import Any

from value_investor.models.base import ModelResult, ValueModel


class EarningsQualityModel(ValueModel):
    """
    Detect weak cash conversion and high accruals.

    Passes when reported earnings are backed by cash and accruals are modest.
    """

    id = "earnings_quality"
    name = "Earnings Quality"

    MIN_FCF_TO_NI = 0.6
    MIN_OCF_TO_NI = 0.8
    MAX_ACCRUALS_TO_ASSETS = 0.08

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        ni = row.get("net_income")
        fcf = row.get("free_cashflow")
        ocf = row.get("operating_cashflow")
        assets = row.get("total_assets")

        checks: list[tuple[str, bool, str]] = []
        failed: list[str] = []

        if ni is not None and ni > 0:
            if fcf is not None:
                ratio = fcf / ni
                ok = ratio >= self.MIN_FCF_TO_NI
                checks.append((f"FCF/NI >= {self.MIN_FCF_TO_NI:.0%}", ok, f"FCF/NI={ratio:.2f}"))
                if not ok:
                    failed.append("weak free-cash conversion")
            else:
                checks.append(("FCF/NI", False, "missing FCF"))
                failed.append("missing FCF")

            if ocf is not None:
                ratio = ocf / ni
                ok = ratio >= self.MIN_OCF_TO_NI
                checks.append((f"OCF/NI >= {self.MIN_OCF_TO_NI:.0%}", ok, f"OCF/NI={ratio:.2f}"))
                if not ok:
                    failed.append("operating cash below earnings")
            else:
                checks.append(("OCF/NI", False, "missing OCF"))
                failed.append("missing OCF")
        elif ni is not None and ni <= 0:
            checks.append(("positive net income", False, f"NI={ni:.0f}"))
            failed.append("negative net income")
        else:
            checks.append(("net income", False, "missing"))
            failed.append("missing net income")

        if ni is not None and ocf is not None and assets is not None and assets > 0:
            accruals = (ni - ocf) / assets
            ok = accruals <= self.MAX_ACCRUALS_TO_ASSETS
            checks.append(
                (f"accruals/assets <= {self.MAX_ACCRUALS_TO_ASSETS:.0%}", ok, f"ratio={accruals:.2%}")
            )
            if not ok:
                failed.append("high accruals vs assets")
        else:
            checks.append(("accruals", True, "insufficient data — skipped"))

        available = sum(1 for _, ok, _ in checks if ok is not False or "skipped" not in _)
        passed_checks = sum(1 for _, ok, _ in checks if ok)
        score = passed_checks / len(checks) if checks else 0.0
        passed = score >= 0.75 and "negative net income" not in failed

        reasons = [detail for _, ok, detail in checks if ok]
        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)


class FinancialHealthModel(ValueModel):
    """
    Low-distress screen: manageable leverage, liquidity, and coverage.

    Passes when balance-sheet stress indicators are within conservative bounds.
    """

    id = "financial_health"
    name = "Financial Health"

    MAX_DEBT_TO_EQUITY = 80.0
    MAX_LEVERAGE = 0.55
    MAX_NET_DEBT_TO_EBITDA = 4.0
    MIN_CURRENT_RATIO = 1.1
    MIN_INTEREST_COVERAGE = 2.5

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        checks: list[tuple[str, bool, str]] = []
        failed: list[str] = []

        de = row.get("debt_to_equity")
        if de is not None:
            ok = de <= self.MAX_DEBT_TO_EQUITY
            checks.append((f"D/E <= {self.MAX_DEBT_TO_EQUITY:.0f}%", ok, f"D/E={de:.0f}%"))
            if not ok:
                failed.append("high debt to equity")
        else:
            checks.append(("D/E", True, "not reported — skipped"))

        leverage = row.get("leverage")
        if leverage is not None:
            ok = leverage <= self.MAX_LEVERAGE
            checks.append((f"leverage <= {self.MAX_LEVERAGE:.0%}", ok, f"leverage={leverage:.1%}"))
            if not ok:
                failed.append("high leverage")
        else:
            checks.append(("leverage", True, "not reported — skipped"))

        cr = row.get("current_ratio_bs") or row.get("current_ratio")
        if cr is not None:
            ok = cr >= self.MIN_CURRENT_RATIO
            checks.append((f"current ratio >= {self.MIN_CURRENT_RATIO:.1f}", ok, f"CR={cr:.2f}"))
            if not ok:
                failed.append("weak liquidity")
        else:
            checks.append(("current ratio", False, "missing"))
            failed.append("missing current ratio")

        debt = row.get("total_debt") or row.get("total_debt_bs")
        cash = row.get("total_cash") or 0.0
        ebitda = row.get("ebitda")
        if debt is not None and ebitda is not None and ebitda > 0:
            net_debt = debt - (cash or 0.0)
            ratio = net_debt / ebitda
            ok = ratio <= self.MAX_NET_DEBT_TO_EBITDA
            checks.append(
                (f"net debt/EBITDA <= {self.MAX_NET_DEBT_TO_EBITDA:.1f}", ok, f"ratio={ratio:.1f}")
            )
            if not ok:
                failed.append("high net debt/EBITDA")
        else:
            checks.append(("net debt/EBITDA", True, "insufficient data — skipped"))

        ebit = row.get("ebit")
        interest = row.get("interest_expense")
        if ebit is not None and interest is not None and interest > 0:
            coverage = ebit / interest
            ok = coverage >= self.MIN_INTEREST_COVERAGE
            checks.append(
                (f"interest coverage >= {self.MIN_INTEREST_COVERAGE:.1f}", ok, f"coverage={coverage:.1f}x")
            )
            if not ok:
                failed.append("weak interest coverage")
        else:
            checks.append(("interest coverage", True, "insufficient data — skipped"))

        passed_checks = sum(1 for _, ok, _ in checks if ok)
        score = passed_checks / len(checks) if checks else 0.0
        hard_fails = {"high debt to equity", "high leverage", "weak liquidity", "high net debt/EBITDA"}
        passed = score >= 0.7 and not (hard_fails & set(failed))

        reasons = [detail for _, ok, detail in checks if ok]
        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)
