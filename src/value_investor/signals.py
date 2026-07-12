"""Investment signal generation from model scores."""

from __future__ import annotations

from enum import Enum

import pandas as pd

from value_investor.data_quality import (
    MIN_QUALITY_FOR_ANALYSIS,
    MIN_QUALITY_FOR_BUY,
    MIN_QUALITY_FOR_STRONG_BUY,
)


class Signal(str, Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    AVOID = "avoid"
    INSUFFICIENT_DATA = "insufficient_data"


SIGNAL_ORDER = {
    Signal.STRONG_BUY: 4,
    Signal.BUY: 3,
    Signal.HOLD: 2,
    Signal.AVOID: 1,
    Signal.INSUFFICIENT_DATA: 0,
}


def _min_passes(model_count: int, fraction: float, floor: int) -> int:
    return max(floor, int(model_count * fraction))


def assign_signal(
    *,
    models_passed: int,
    model_count: int,
    mean_model_score: float,
    weighted_model_score: float | None,
    composite_score: float | None,
    sector_composite_score: float | None,
    families_passed: int,
    family_count: int,
    data_quality_score: float,
    risk_family_passed: bool,
    risk_mean_score: float,
    has_errors: bool,
) -> Signal:
    """Map aggregated model output to an actionable signal."""
    if has_errors or model_count == 0:
        return Signal.INSUFFICIENT_DATA

    if data_quality_score < MIN_QUALITY_FOR_ANALYSIS:
        return Signal.INSUFFICIENT_DATA

    pass_rate = models_passed / model_count
    score_for_blend = (
        weighted_model_score if weighted_model_score is not None else mean_model_score
    )
    composite = composite_score if composite_score is not None else score_for_blend
    sector_composite = sector_composite_score if sector_composite_score is not None else composite
    blended_composite = (composite + sector_composite) / 2

    strong_threshold = _min_passes(model_count, 0.35, 5)
    buy_threshold = _min_passes(model_count, 0.22, 3)
    min_families_strong = max(2, min(3, family_count))
    min_families_buy = max(1, min(2, family_count))

    signal = Signal.AVOID
    if (
        models_passed >= strong_threshold
        and blended_composite >= 0.7
        and families_passed >= min_families_strong
    ):
        signal = Signal.STRONG_BUY
    elif (
        models_passed >= buy_threshold
        and blended_composite >= 0.55
        and families_passed >= min_families_buy
    ):
        signal = Signal.BUY
    elif pass_rate >= 0.15 or blended_composite >= 0.45:
        signal = Signal.HOLD

    # Downgrade when fundamentals coverage is thin
    if signal == Signal.STRONG_BUY and data_quality_score < MIN_QUALITY_FOR_STRONG_BUY:
        signal = Signal.BUY
    if signal == Signal.BUY and data_quality_score < MIN_QUALITY_FOR_BUY:
        signal = Signal.HOLD

    # Risk family veto: cheap screens can pass while balance sheet / earnings quality fail
    if signal == Signal.STRONG_BUY and (not risk_family_passed or risk_mean_score < 0.55):
        signal = Signal.BUY
    if signal == Signal.BUY and (risk_mean_score < 0.35 or not risk_family_passed):
        signal = Signal.HOLD

    return signal


def build_signals(
    universe: pd.DataFrame,
    model_results: pd.DataFrame,
    summary: pd.DataFrame,
) -> pd.DataFrame:
    """Merge universe metrics with model summary and assign final signals."""
    composite = model_results[model_results["model_id"] == "composite_value"][
        ["ticker", "score"]
    ].rename(columns={"score": "composite_score"})

    out = universe.merge(summary, on="ticker", how="left")
    out = out.merge(composite, on="ticker", how="left")

    signals: list[Signal] = []
    for _, row in out.iterrows():
        sector_score = row.get("sector_composite_score")
        sector_composite_score = (
            float(sector_score) if sector_score is not None and not pd.isna(sector_score) else None
        )
        composite = row.get("composite_score")
        composite_score = float(composite) if composite is not None and not pd.isna(composite) else None

        weighted_score = row.get("weighted_model_score")
        weighted_model_score = (
            float(weighted_score)
            if weighted_score is not None and not pd.isna(weighted_score)
            else None
        )
        risk_passed = row.get("risk_family_passed")
        risk_family_passed = bool(risk_passed) if risk_passed is not None and not pd.isna(risk_passed) else False
        risk_score = row.get("risk_mean_score")
        risk_mean_score = float(risk_score) if risk_score is not None and not pd.isna(risk_score) else 0.0

        signals.append(
            assign_signal(
                models_passed=int(row.get("models_passed") or 0),
                model_count=int(row.get("model_count") or 0),
                mean_model_score=float(row.get("mean_model_score") or 0),
                weighted_model_score=weighted_model_score,
                composite_score=composite_score,
                sector_composite_score=sector_composite_score,
                families_passed=int(row.get("families_passed") or 0),
                family_count=int(row.get("family_count") or 5),
                data_quality_score=float(row.get("data_quality_score") or 0),
                risk_family_passed=risk_family_passed,
                risk_mean_score=risk_mean_score,
                has_errors=bool(row.get("errors")),
            )
        )

    out["signal"] = [s.value for s in signals]
    out["signal_rank"] = [SIGNAL_ORDER[s] for s in signals]

    sort_cols = [
        "signal_rank",
        "composite_score",
        "sector_composite_score",
        "weighted_model_score",
        "mean_model_score",
        "models_passed",
    ]
    present = [c for c in sort_cols if c in out.columns]
    out = out.sort_values(present, ascending=[False] * len(present))
    return out.reset_index(drop=True)
