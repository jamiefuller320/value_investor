"""FCF basis overlay — cap conviction when FCF bases diverge and yield screens pass."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from value_investor.scoring.fcf import reconcile_fcf_for_ticker, screen_ttm_from_row

FCF_YIELD_DEPENDENT_MODEL_IDS = ("fcf_yield", "composite_value", "quality_value")
FCF_BASIS_CONVICTION_MULTIPLIER = 0.85

_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def fcf_yield_dependent_model_passed(ticker_models: pd.DataFrame) -> bool:
    """True when an FCF-yield-dependent screen passes for the ticker."""
    if ticker_models.empty or "model_id" not in ticker_models.columns:
        return False
    dependent = ticker_models[ticker_models["model_id"].isin(FCF_YIELD_DEPENDENT_MODEL_IDS)]
    if dependent.empty:
        return False
    return bool(dependent["passed"].any())


def fcf_basis_overlay_triggered(
    *,
    divergence_flagged: bool,
    ticker_models: pd.DataFrame,
) -> bool:
    """Flag when FCF bases diverge and a yield-dependent model still passes."""
    if not divergence_flagged:
        return False
    return fcf_yield_dependent_model_passed(ticker_models)


def cap_signal_for_fcf_basis_overlay(signal: str) -> str:
    """Cap at research-equivalent caution: strong_buy -> buy, buy -> hold."""
    if signal == "strong_buy":
        return "buy"
    if signal == "buy":
        return "hold"
    return signal


def cap_conviction_for_fcf_basis_overlay(conviction_score: float) -> float:
    """Reduce conviction when FCF basis mismatch inflates yield-dependent screens."""
    return max(0.0, float(conviction_score) * FCF_BASIS_CONVICTION_MULTIPLIER)


def _more_conservative_signal(current: str, candidate: str) -> str:
    current_rank = _SIGNAL_RANK.get(current, 0)
    candidate_rank = _SIGNAL_RANK.get(candidate, 0)
    return current if current_rank <= candidate_rank else candidate


def apply_fcf_basis_overlay_to_signal(
    signal: str,
    *,
    divergence_flagged: bool,
    ticker_models: pd.DataFrame,
    conviction_score: float,
    adjusted_signal: str | None = None,
) -> tuple[bool, str, float]:
    """Return overlay flag, conservative adjusted signal, and capped conviction."""
    base_adjusted = adjusted_signal or signal
    base_conviction = float(conviction_score or 0.0)
    if not fcf_basis_overlay_triggered(
        divergence_flagged=divergence_flagged,
        ticker_models=ticker_models,
    ):
        return False, base_adjusted, base_conviction
    capped_signal = cap_signal_for_fcf_basis_overlay(signal)
    return (
        True,
        _more_conservative_signal(base_adjusted, capped_signal),
        cap_conviction_for_fcf_basis_overlay(base_conviction),
    )


def enrich_signals_with_fcf_basis_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Add FCF basis overlay flag and cap yield-inflated conviction when triggered."""
    out = signals.copy()
    flags: list[bool] = []
    adjusted: list[str] = []
    convictions: list[float] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        ticker_models = model_results[model_results["ticker"] == ticker]
        screen_ttm = screen_ttm_from_row(row)
        fcf_bundle = reconcile_fcf_for_ticker(
            ticker,
            screen_ttm=screen_ttm,
            output_dir=output_dir,
        )

        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        triggered, new_adjusted, new_conviction = apply_fcf_basis_overlay_to_signal(
            str(row.get("signal") or "hold"),
            divergence_flagged=bool(fcf_bundle.get("divergence_flagged")),
            ticker_models=ticker_models,
            conviction_score=float(row.get("conviction_score") or 0.0),
            adjusted_signal=existing_adjusted,
        )
        flags.append(triggered)
        adjusted.append(new_adjusted)
        convictions.append(new_conviction)

    out["fcf_basis_overlay"] = flags
    out["adjusted_signal"] = adjusted
    out["conviction_score"] = convictions
    return out
