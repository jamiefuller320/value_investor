"""Joseph Piotroski F-Score — financial strength checklist."""

from __future__ import annotations

from typing import Any

from value_investor.models.base import ModelResult, ValueModel


class PiotroskiFScoreModel(ValueModel):
    """
    Nine-point F-Score adapted to available yfinance data.

    Scoring (1 point each):
    1. Positive net income
    2. Positive operating cash flow
    3. ROA improving YoY
    4. Quality of earnings (OCF > NI)
    5. Leverage declining
    6. Current ratio improving
    7. No dilution (shares stable or falling)
    8. Gross margin improving
    9. Asset turnover improving
    """

    id = "piotroski_f"
    name = "Piotroski F-Score"

    PASS_SCORE = 7

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        points = 0
        reasons: list[str] = []
        failed: list[str] = []

        ni = row.get("net_income")
        ocf = row.get("operating_cashflow")
        roa = row.get("return_on_assets")
        roa_prev = row.get("return_on_assets_prev")
        leverage = row.get("leverage")
        leverage_prev = row.get("leverage_prev")
        cr = row.get("current_ratio_bs") or row.get("current_ratio")
        cr_prev = row.get("current_ratio_bs_prev")
        shares = row.get("shares_outstanding")
        shares_prev = row.get("shares_outstanding_prev")
        gm = row.get("gross_margin")
        gm_prev = row.get("gross_margin_prev")
        at = row.get("asset_turnover")
        at_prev = row.get("asset_turnover_prev")

        checks: list[tuple[str, bool | None]] = [
            ("positive net income", ni is not None and ni > 0),
            ("positive operating cash flow", ocf is not None and ocf > 0),
            ("ROA improving", roa is not None and roa_prev is not None and roa > roa_prev),
            ("OCF > net income", ocf is not None and ni is not None and ocf > ni),
            ("leverage declining", leverage is not None and leverage_prev is not None and leverage < leverage_prev),
            ("current ratio improving", cr is not None and cr_prev is not None and cr > cr_prev),
            (
                "no share dilution",
                shares is not None and shares_prev is not None and shares <= shares_prev * 1.01,
            ),
            ("gross margin improving", gm is not None and gm_prev is not None and gm > gm_prev),
            ("asset turnover improving", at is not None and at_prev is not None and at > at_prev),
        ]

        available = 0
        for label, ok in checks:
            if ok is None:
                continue
            available += 1
            if ok:
                points += 1
                reasons.append(label)
            else:
                failed.append(label)

        if available < 5:
            return self._result(
                passed=False,
                score=points / 9,
                failed_criteria=["insufficient financial statement history"],
            )

        score = points / 9
        passed = points >= self.PASS_SCORE
        if not passed:
            failed.insert(0, f"F-Score {points}/9 below {self.PASS_SCORE}")

        reasons.insert(0, f"F-Score={points}/9")
        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)
