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
    has_errors: bool,
) -> Signal:
    """Map aggregated model output to an actionable signal."""
    if has_errors or model_count == 0:
        return Signal.INSUFFICIENT_DATA

    pass_rate = models_passed / model_count
    composite = composite_score if composite_score is not None else mean_model_score

    strong_threshold = _min_passes(model_count, 0.35, 5)
    buy_threshold = _min_passes(model_count, 0.22, 3)

    if models_passed >= strong_threshold and composite >= 0.7:
        return Signal.STRONG_BUY
    if models_passed >= buy_threshold and composite >= 0.55:
        return Signal.BUY
    if pass_rate >= 0.15 or composite >= 0.45:
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
        signals.append(
            assign_signal(
                models_passed=int(row.get("models_passed") or 0),
                model_count=int(row.get("model_count") or 0),
                mean_model_score=float(row.get("mean_model_score") or 0),
                composite_score=row.get("composite_score"),
                has_errors=bool(row.get("errors")),
            )
        )

    out["signal"] = [s.value for s in signals]
    out["signal_rank"] = [SIGNAL_ORDER[s] for s in signals]

    sort_cols = ["signal_rank", "composite_score", "mean_model_score", "models_passed"]
    out = out.sort_values(sort_cols, ascending=[False, False, False, False])
    return out.reset_index(drop=True)
