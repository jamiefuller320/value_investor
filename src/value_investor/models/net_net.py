"""Benjamin Graham net-net (NCAV) screen."""

from __future__ import annotations

from typing import Any

from value_investor.models.base import ModelResult, ValueModel


class NetNetModel(ValueModel):
    """
    Graham net-net: NCAV = current assets − total liabilities.

    Classic threshold: NCAV > market cap (trading below liquidation value).
    Practical FTSE threshold: NCAV/Market Cap > 0.67 (two-thirds).
    """

    id = "graham_net_net"
    name = "Graham Net-Net"

    MIN_NCAV_RATIO = 0.67

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        ncav = row.get("ncav")
        mcap = row.get("market_cap")
        failed: list[str] = []

        if ncav is None:
            return self._result(passed=False, score=0.0, failed_criteria=["missing NCAV (balance sheet data)"])

        if mcap is None or mcap <= 0:
            return self._result(passed=False, score=0.0, failed_criteria=["missing market cap"])

        ratio = ncav / mcap
        strict_pass = ratio >= 1.0
        passed = ratio >= self.MIN_NCAV_RATIO
        score = min(1.0, ratio)

        if not passed:
            failed.append(f"NCAV/market cap {ratio:.2f} below {self.MIN_NCAV_RATIO}")

        reasons = [f"NCAV/market cap={ratio:.2f}"]
        if strict_pass:
            reasons.append("trading below net current asset value")

        return self._result(passed=passed, score=score, reasons=reasons, failed_criteria=failed)
