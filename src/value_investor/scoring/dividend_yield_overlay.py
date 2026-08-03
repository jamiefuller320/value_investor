"""Dividend-yield overlay — cap signals when yield passes but FCF and earnings quality fail."""

from __future__ import annotations

import pandas as pd

HIGH_DIVIDEND_MODEL_ID = "high_dividend"
FCF_YIELD_MODEL_ID = "fcf_yield"
EARNINGS_QUALITY_MODEL_ID = "earnings_quality"

_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def _model_passed(ticker_models: pd.DataFrame, model_id: str) -> bool | None:
    """Return pass/fail for ``model_id``, or None when the model row is absent."""
    if ticker_models.empty or "model_id" not in ticker_models.columns:
        return None
    rows = ticker_models[ticker_models["model_id"] == model_id]
    if rows.empty:
        return None
    return bool(rows.iloc[0]["passed"])


def dividend_yield_overlay_triggered(ticker_models: pd.DataFrame) -> bool:
    """High Dividend Yield passes while FCF Yield and Earnings Quality both fail."""
    high_dividend = _model_passed(ticker_models, HIGH_DIVIDEND_MODEL_ID)
    fcf_yield = _model_passed(ticker_models, FCF_YIELD_MODEL_ID)
    earnings_quality = _model_passed(ticker_models, EARNINGS_QUALITY_MODEL_ID)
    if high_dividend is not True:
        return False
    if fcf_yield is not False:
        return False
    return earnings_quality is False


def cap_signal_for_dividend_yield_overlay(signal: str) -> str:
    """Cap at research-equivalent caution: strong_buy -> buy, buy -> hold."""
    if signal == "strong_buy":
        return "buy"
    if signal == "buy":
        return "hold"
    return signal


def _more_conservative_signal(current: str, candidate: str) -> str:
    current_rank = _SIGNAL_RANK.get(current, 0)
    candidate_rank = _SIGNAL_RANK.get(candidate, 0)
    return current if current_rank <= candidate_rank else candidate


def apply_dividend_yield_overlay_to_signal(
    signal: str,
    *,
    ticker_models: pd.DataFrame,
    adjusted_signal: str | None = None,
) -> tuple[bool, str]:
    """Return overlay flag and conservative adjusted signal."""
    base_adjusted = adjusted_signal or signal
    if not dividend_yield_overlay_triggered(ticker_models):
        return False, base_adjusted
    capped = cap_signal_for_dividend_yield_overlay(signal)
    return True, _more_conservative_signal(base_adjusted, capped)


def enrich_signals_with_dividend_yield_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
) -> pd.DataFrame:
    """Add dividend-yield overlay flag and cap ``adjusted_signal`` when triggered."""
    out = signals.copy()
    flags: list[bool] = []
    adjusted: list[str] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        ticker_models = model_results[model_results["ticker"] == ticker]

        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        triggered, new_adjusted = apply_dividend_yield_overlay_to_signal(
            str(row.get("signal") or "hold"),
            ticker_models=ticker_models,
            adjusted_signal=existing_adjusted,
        )
        flags.append(triggered)
        adjusted.append(new_adjusted)

    out["dividend_yield_overlay"] = flags
    out["adjusted_signal"] = adjusted
    return out
