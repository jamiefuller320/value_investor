"""Investment signal generation from model scores."""

from __future__ import annotations

from enum import Enum

import pandas as pd


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
    composite_score: float | None,
    sector_composite_score: float | None,
    families_passed: int,
    family_count: int,
    has_errors: bool,
) -> Signal:
    """Map aggregated model output to an actionable signal."""
    if has_errors or model_count == 0:
        return Signal.INSUFFICIENT_DATA

    pass_rate = models_passed / model_count
    composite = composite_score if composite_score is not None else mean_model_score
    sector_composite = sector_composite_score if sector_composite_score is not None else composite
    blended_composite = (composite + sector_composite) / 2

    strong_threshold = _min_passes(model_count, 0.35, 5)
    buy_threshold = _min_passes(model_count, 0.22, 3)
    min_families_strong = max(2, min(3, family_count))
    min_families_buy = max(1, min(2, family_count))

    if (
        models_passed >= strong_threshold
        and blended_composite >= 0.7
        and families_passed >= min_families_strong
    ):
        return Signal.STRONG_BUY
    if (
        models_passed >= buy_threshold
        and blended_composite >= 0.55
        and families_passed >= min_families_buy
    ):
        return Signal.BUY
    if pass_rate >= 0.15 or blended_composite >= 0.45:
        return Signal.HOLD
    return Signal.AVOID


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

        signals.append(
            assign_signal(
                models_passed=int(row.get("models_passed") or 0),
                model_count=int(row.get("model_count") or 0),
                mean_model_score=float(row.get("mean_model_score") or 0),
                composite_score=composite_score,
                sector_composite_score=sector_composite_score,
                families_passed=int(row.get("families_passed") or 0),
                family_count=int(row.get("family_count") or 4),
                has_errors=bool(row.get("errors")),
            )
        )

    out["signal"] = [s.value for s in signals]
    out["signal_rank"] = [SIGNAL_ORDER[s] for s in signals]

    sort_cols = [
        "signal_rank",
        "composite_score",
        "sector_composite_score",
        "mean_model_score",
        "models_passed",
    ]
    out = out.sort_values(sort_cols, ascending=[False, False, False, False])
    return out.reset_index(drop=True)
