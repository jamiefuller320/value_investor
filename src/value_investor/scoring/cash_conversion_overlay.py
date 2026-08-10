"""Cash-conversion overlay — cap adjusted signals when capital returns mask weak FCF."""

from __future__ import annotations

import ast
from typing import Any

import pandas as pd

from value_investor.scoring.fcf import resolve_free_cashflow

DIVIDEND_MODEL_IDS = ("high_dividend", "dividend_growth")
SHARE_COUNT_STABLE_TOLERANCE = 1.01


def _parse_list_field(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "[]":
            return []
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (SyntaxError, ValueError):
            return [text]
    return []


def dividend_screen_passed(ticker_models: pd.DataFrame) -> bool:
    """True when at least one dividend-family screen passes."""
    if ticker_models.empty or "model_id" not in ticker_models.columns:
        return False
    dividend = ticker_models[ticker_models["model_id"].isin(DIVIDEND_MODEL_IDS)]
    if dividend.empty:
        return False
    return bool(dividend["passed"].any())


def active_buyback_detected(
    *,
    shares_outstanding: float | None,
    shares_outstanding_prev: float | None,
    ticker_models: pd.DataFrame,
) -> bool:
    """Detect repurchases via declining share count or Piotroski non-dilution."""
    if shares_outstanding is not None and shares_outstanding_prev is not None:
        if (
            float(shares_outstanding)
            <= float(shares_outstanding_prev) * SHARE_COUNT_STABLE_TOLERANCE
        ):
            return True

    if ticker_models.empty or "model_id" not in ticker_models.columns:
        return False
    piotroski = ticker_models[ticker_models["model_id"] == "piotroski_f"]
    if piotroski.empty:
        return False
    reasons = _parse_list_field(piotroski.iloc[0].get("reasons"))
    return "no share dilution" in reasons


def cash_conversion_overlay_triggered(
    *,
    free_cashflow: float | None,
    dividend_screen_passed_flag: bool,
    active_buyback: bool,
) -> bool:
    """Negative trailing FCF plus dividend pass and active buyback."""
    if free_cashflow is None or (isinstance(free_cashflow, float) and pd.isna(free_cashflow)):
        return False
    if float(free_cashflow) >= 0:
        return False
    return dividend_screen_passed_flag and active_buyback


def cap_signal_for_cash_conversion_overlay(signal: str) -> str:
    """Cap at research-equivalent caution: strong_buy -> buy, buy -> hold."""
    if signal == "strong_buy":
        return "buy"
    if signal == "buy":
        return "hold"
    return signal


_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def _more_conservative_signal(current: str, candidate: str) -> str:
    current_rank = _SIGNAL_RANK.get(current, 0)
    candidate_rank = _SIGNAL_RANK.get(candidate, 0)
    return current if current_rank <= candidate_rank else candidate


def apply_cash_conversion_overlay_to_signal(
    signal: str,
    *,
    free_cashflow: float | None,
    shares_outstanding: float | None,
    shares_outstanding_prev: float | None,
    ticker_models: pd.DataFrame,
    adjusted_signal: str | None = None,
) -> tuple[bool, str]:
    """Return overlay flag and conservative adjusted signal."""
    base_adjusted = adjusted_signal or signal
    if not cash_conversion_overlay_triggered(
        free_cashflow=free_cashflow,
        dividend_screen_passed_flag=dividend_screen_passed(ticker_models),
        active_buyback=active_buyback_detected(
            shares_outstanding=shares_outstanding,
            shares_outstanding_prev=shares_outstanding_prev,
            ticker_models=ticker_models,
        ),
    ):
        return False, base_adjusted
    capped = cap_signal_for_cash_conversion_overlay(signal)
    return True, _more_conservative_signal(base_adjusted, capped)


def enrich_signals_with_cash_conversion_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
) -> pd.DataFrame:
    """Add cash-conversion overlay flag and cap ``adjusted_signal`` when triggered."""
    out = signals.copy()
    flags: list[bool] = []
    adjusted: list[str] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        ticker_models = model_results[model_results["ticker"] == ticker]

        canonical_fcf = resolve_free_cashflow(row)

        shares = row.get("shares_outstanding")
        shares_outstanding = (
            float(shares)
            if shares is not None and not (isinstance(shares, float) and pd.isna(shares))
            else None
        )
        shares_prev = row.get("shares_outstanding_prev")
        shares_outstanding_prev = (
            float(shares_prev)
            if shares_prev is not None
            and not (isinstance(shares_prev, float) and pd.isna(shares_prev))
            else None
        )

        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        triggered, new_adjusted = apply_cash_conversion_overlay_to_signal(
            str(row.get("signal") or "hold"),
            free_cashflow=canonical_fcf,
            shares_outstanding=shares_outstanding,
            shares_outstanding_prev=shares_outstanding_prev,
            ticker_models=ticker_models,
            adjusted_signal=existing_adjusted,
        )
        flags.append(triggered)
        adjusted.append(new_adjusted)

    out["cash_conversion_overlay"] = flags
    out["adjusted_signal"] = adjusted
    return out
