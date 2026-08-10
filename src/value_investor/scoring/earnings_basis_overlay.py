"""Earnings-basis overlay — flag statutory vs adjusted EPS growth sign divergence."""

from __future__ import annotations

import pandas as pd

from value_investor.scoring.fcf import (
    earnings_growth_signs_diverge,
    resolve_statutory_earnings_growth,
)

GROWTH_DEPENDENT_MODEL_IDS = ("lynch_peg", "graham_enterprising", "neff_pegy")
EARNINGS_BASIS_CONVICTION_MULTIPLIER = 0.85

_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def growth_dependent_model_passed(ticker_models: pd.DataFrame) -> bool:
    """True when a Lynch/Graham/Neff growth-dependent screen passes for the ticker."""
    if ticker_models.empty or "model_id" not in ticker_models.columns:
        return False
    dependent = ticker_models[ticker_models["model_id"].isin(GROWTH_DEPENDENT_MODEL_IDS)]
    if dependent.empty:
        return False
    return bool(dependent["passed"].any())


def earnings_basis_overlay_triggered(
    *,
    statutory_growth: float | None,
    adjusted_growth: float | None,
    ticker_models: pd.DataFrame,
) -> bool:
    """Flag when growth signs diverge and a growth-dependent model still passes."""
    if not earnings_growth_signs_diverge(statutory_growth, adjusted_growth):
        return False
    return growth_dependent_model_passed(ticker_models)


def cap_signal_for_earnings_basis_overlay(signal: str) -> str:
    """Cap at research-equivalent caution: strong_buy -> buy, buy -> hold."""
    if signal == "strong_buy":
        return "buy"
    if signal == "buy":
        return "hold"
    return signal


def cap_conviction_for_earnings_basis_overlay(conviction_score: float) -> float:
    """Reduce conviction when statutory/adjusted growth signs diverge."""
    return max(0.0, float(conviction_score) * EARNINGS_BASIS_CONVICTION_MULTIPLIER)


def _more_conservative_signal(current: str, candidate: str) -> str:
    current_rank = _SIGNAL_RANK.get(current, 0)
    candidate_rank = _SIGNAL_RANK.get(candidate, 0)
    return current if current_rank <= candidate_rank else candidate


def apply_earnings_basis_overlay_to_signal(
    signal: str,
    *,
    statutory_growth: float | None,
    adjusted_growth: float | None,
    ticker_models: pd.DataFrame,
    conviction_score: float,
    adjusted_signal: str | None = None,
) -> tuple[bool, str, float]:
    """Return overlay flag, conservative adjusted signal, and capped conviction."""
    base_adjusted = adjusted_signal or signal
    base_conviction = float(conviction_score or 0.0)
    if not earnings_basis_overlay_triggered(
        statutory_growth=statutory_growth,
        adjusted_growth=adjusted_growth,
        ticker_models=ticker_models,
    ):
        return False, base_adjusted, base_conviction
    capped_signal = cap_signal_for_earnings_basis_overlay(signal)
    return (
        True,
        _more_conservative_signal(base_adjusted, capped_signal),
        cap_conviction_for_earnings_basis_overlay(base_conviction),
    )


def enrich_signals_with_earnings_basis_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
) -> pd.DataFrame:
    """Add earnings-basis overlay flag and cap growth-inflated conviction when triggered."""
    out = signals.copy()
    flags: list[bool] = []
    adjusted: list[str] = []
    convictions: list[float] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        ticker_models = model_results[model_results["ticker"] == ticker]

        statutory_growth = resolve_statutory_earnings_growth(row)

        adjusted_metric = row.get("adjusted_eps_growth_pct")
        adjusted_growth = (
            float(adjusted_metric)
            if adjusted_metric is not None
            and not (isinstance(adjusted_metric, float) and pd.isna(adjusted_metric))
            else None
        )

        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        triggered, new_adjusted, new_conviction = apply_earnings_basis_overlay_to_signal(
            str(row.get("signal") or "hold"),
            statutory_growth=statutory_growth,
            adjusted_growth=adjusted_growth,
            ticker_models=ticker_models,
            conviction_score=float(row.get("conviction_score") or 0.0),
            adjusted_signal=existing_adjusted,
        )
        flags.append(triggered)
        adjusted.append(new_adjusted)
        convictions.append(new_conviction)

    out["earnings_basis_overlay"] = flags
    out["adjusted_signal"] = adjusted
    out["conviction_score"] = convictions
    return out
