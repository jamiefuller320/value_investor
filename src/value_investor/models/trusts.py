"""Investment-trust / closed-end fund screens (NAV discount, income, premium risk)."""

from __future__ import annotations

from typing import Any, Self

import pandas as pd

from value_investor.models.base import ModelResult, ValueModel
from value_investor.models.fitted import UniverseFittedModel
from value_investor.models.ranking import percentile_rank


class DeepDiscountTrustModel(UniverseFittedModel):
    """Wide discount to book/NAV proxy versus the trust universe."""

    id = "trust_deep_discount"
    name = "Trust Deep Discount"

    MIN_DISCOUNT = 0.10  # at least 10% below book

    def fit(self, universe: pd.DataFrame) -> Self:
        self._fit_base(universe)
        return self

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        if self._universe is None:
            return self._result(passed=False, score=0.0, failed_criteria=["model not fitted"])

        discount = row.get("discount_to_nav")
        if discount is None or pd.isna(discount):
            return self._result(passed=False, score=0.0, failed_criteria=["missing discount/NAV proxy"])

        rank = percentile_rank(
            self._universe["discount_to_nav"], float(discount), higher_is_better=True
        )
        if rank is None:
            return self._result(passed=False, score=0.0, failed_criteria=["could not rank discount"])

        passed = float(discount) >= self.MIN_DISCOUNT and rank >= 0.70
        failed: list[str] = []
        if float(discount) < self.MIN_DISCOUNT:
            failed.append(f"discount {float(discount):.0%} below {self.MIN_DISCOUNT:.0%} floor")
        if rank < 0.70:
            failed.append("not in top 30% of discounts")

        return self._result(
            passed=passed,
            score=rank,
            reasons=[f"discount={float(discount):.0%} to book/NAV proxy", f"universe rank {rank:.0%}"],
            failed_criteria=failed,
        )


class TrustIncomeModel(UniverseFittedModel):
    """High distribution yield among trusts (income / infrastructure sleeves)."""

    id = "trust_income"
    name = "Trust Income"

    MIN_YIELD = 0.03

    def fit(self, universe: pd.DataFrame) -> Self:
        self._fit_base(universe)
        return self

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        if self._universe is None:
            return self._result(passed=False, score=0.0, failed_criteria=["model not fitted"])

        yld = row.get("dividend_yield")
        if yld is None or pd.isna(yld):
            return self._result(passed=False, score=0.0, failed_criteria=["missing dividend yield"])

        rank = percentile_rank(
            self._universe["dividend_yield"], float(yld), higher_is_better=True
        )
        if rank is None:
            return self._result(passed=False, score=0.0, failed_criteria=["could not rank yield"])

        # Prefer not buying a rich premium solely for yield.
        discount = row.get("discount_to_nav")
        premium_ok = discount is None or pd.isna(discount) or float(discount) >= -0.05

        passed = float(yld) >= self.MIN_YIELD and rank >= 0.70 and premium_ok
        failed: list[str] = []
        if float(yld) < self.MIN_YIELD:
            failed.append(f"yield {float(yld):.1%} below {self.MIN_YIELD:.0%} floor")
        if rank < 0.70:
            failed.append("not in top 30% for yield")
        if not premium_ok:
            failed.append("trading at a rich premium to book/NAV proxy")

        return self._result(
            passed=passed,
            score=rank,
            reasons=[f"yield={float(yld):.1%}", f"universe rank {rank:.0%}"],
            failed_criteria=failed,
        )


class DiscountIncomeTrustModel(ValueModel):
    """Combined discount + income — classic closed-end value setup."""

    id = "trust_discount_income"
    name = "Trust Discount + Income"

    MIN_DISCOUNT = 0.05
    MIN_YIELD = 0.025

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        discount = row.get("discount_to_nav")
        yld = row.get("dividend_yield")
        failed: list[str] = []
        checks = 0
        score_bits: list[float] = []

        if discount is not None and not pd.isna(discount):
            ok = float(discount) >= self.MIN_DISCOUNT
            checks += 1
            # Map 5%→0.4, 20%+→1.0
            score_bits.append(max(0.0, min(1.0, (float(discount) - 0.0) / 0.25)))
            if not ok:
                failed.append(f"discount {float(discount):.0%} below {self.MIN_DISCOUNT:.0%}")
        else:
            failed.append("missing discount/NAV proxy")

        if yld is not None and not pd.isna(yld):
            ok = float(yld) >= self.MIN_YIELD
            checks += 1
            score_bits.append(max(0.0, min(1.0, float(yld) / 0.08)))
            if not ok:
                failed.append(f"yield {float(yld):.1%} below {self.MIN_YIELD:.0%}")
        else:
            failed.append("missing dividend yield")

        passed = (
            discount is not None
            and yld is not None
            and not pd.isna(discount)
            and not pd.isna(yld)
            and float(discount) >= self.MIN_DISCOUNT
            and float(yld) >= self.MIN_YIELD
        )
        score = sum(score_bits) / len(score_bits) if score_bits else 0.0
        reasons = []
        if discount is not None and not pd.isna(discount):
            reasons.append(f"discount={float(discount):.0%}")
        if yld is not None and not pd.isna(yld):
            reasons.append(f"yield={float(yld):.1%}")

        return self._result(
            passed=passed,
            score=score,
            reasons=reasons,
            failed_criteria=failed if not passed else [],
        )


class TrustRelativeValueModel(UniverseFittedModel):
    """Cheap on earnings yield among trusts that report a positive P/E."""

    id = "trust_relative_value"
    name = "Trust Relative Value"

    def fit(self, universe: pd.DataFrame) -> Self:
        self._fit_base(universe)
        return self

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        if self._universe is None:
            return self._result(passed=False, score=0.0, failed_criteria=["model not fitted"])

        pe = row.get("trailing_pe")
        if pe is None or pd.isna(pe) or float(pe) <= 0:
            return self._result(
                passed=False,
                score=0.0,
                failed_criteria=["no positive trailing P/E"],
            )

        rank = percentile_rank(
            self._universe["trailing_pe"], float(pe), higher_is_better=False
        )
        if rank is None:
            return self._result(passed=False, score=0.0, failed_criteria=["could not rank P/E"])

        discount = row.get("discount_to_nav")
        discount_ok = discount is not None and not pd.isna(discount) and float(discount) >= 0.0
        passed = rank >= 0.70 and discount_ok
        failed: list[str] = []
        if rank < 0.70:
            failed.append("not in cheapest 30% on P/E")
        if not discount_ok:
            failed.append("not at a discount to book/NAV proxy")

        return self._result(
            passed=passed,
            score=rank,
            reasons=[f"P/E={float(pe):.1f}", f"cheapness rank {rank:.0%}"],
            failed_criteria=failed,
        )


class TrustPremiumRiskModel(ValueModel):
    """Risk sleeve: fail names trading at a rich premium to book/NAV proxy."""

    id = "trust_premium_risk"
    name = "Trust Premium Risk"

    # Pass when not at a large premium (discount or modest premium OK).
    MAX_PREMIUM = 0.08  # fail if premium > 8% (discount < -8%)

    def evaluate(self, row: dict[str, Any]) -> ModelResult:
        discount = row.get("discount_to_nav")
        if discount is None or pd.isna(discount):
            # Unknown premium — soft pass with low score so risk family does not veto hard.
            return self._result(
                passed=True,
                score=0.45,
                reasons=["discount/NAV proxy unavailable — neutral risk"],
            )

        premium = -float(discount)
        passed = premium <= self.MAX_PREMIUM
        if passed:
            # Higher score for deeper discounts
            score = max(0.4, min(1.0, 0.55 + float(discount)))
            return self._result(
                passed=True,
                score=score,
                reasons=[f"premium/discount={float(discount):+.0%} vs book/NAV proxy"],
            )

        return self._result(
            passed=False,
            score=max(0.0, 0.35 - premium),
            reasons=[f"premium={premium:.0%} vs book/NAV proxy"],
            failed_criteria=[f"rich premium above {self.MAX_PREMIUM:.0%}"],
        )


ALL_TRUST_MODELS: list[ValueModel] = [
    DeepDiscountTrustModel(),
    TrustIncomeModel(),
    DiscountIncomeTrustModel(),
    TrustRelativeValueModel(),
    TrustPremiumRiskModel(),
]

TRUST_MODEL_FAMILIES: dict[str, list[str]] = {
    "discount": ["trust_deep_discount", "trust_discount_income", "trust_relative_value"],
    "income": ["trust_income", "trust_discount_income"],
    "risk": ["trust_premium_risk"],
}

TRUST_MODEL_TO_FAMILY = {
    model_id: family
    for family, model_ids in TRUST_MODEL_FAMILIES.items()
    for model_id in model_ids
}
