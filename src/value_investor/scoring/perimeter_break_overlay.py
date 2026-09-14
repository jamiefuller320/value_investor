"""Perimeter-break overlay — cap group-yield strong buys after announced carve-outs."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from value_investor.scoring.cash_conversion_overlay import dividend_screen_passed
from value_investor.scoring.fcf import load_filing_bodies_for_ticker

PERIMETER_ACTION_FRAGMENTS = (
    "agreed to sell",
    "agreement to sell",
    "sale of the",
    "sale of its",
    "disposal of",
    "carve-out",
    "carve out",
    "demerger",
    "held for sale",
    "discontinued operation",
)

PERIMETER_SCOPE_FRAGMENTS = (
    "media & entertainment",
    "media and entertainment",
    "business unit",
    "division",
    "segment",
    "major business",
)

_PERIMETER_ACTION_RES = tuple(
    re.compile(re.escape(fragment), re.IGNORECASE) for fragment in PERIMETER_ACTION_FRAGMENTS
)
_PERIMETER_SCOPE_RES = tuple(
    re.compile(re.escape(fragment), re.IGNORECASE) for fragment in PERIMETER_SCOPE_FRAGMENTS
)

_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def perimeter_break_language_detected(text: str) -> bool:
    """True when prose announces a material disposal or carve-out of a business unit."""
    if not text:
        return False
    has_action = any(pattern.search(text) for pattern in _PERIMETER_ACTION_RES)
    if not has_action:
        return False
    return any(pattern.search(text) for pattern in _PERIMETER_SCOPE_RES)


def perimeter_break_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> bool:
    """Scan cached filing bodies for announced perimeter breaks."""
    bodies = load_filing_bodies_for_ticker(ticker, output_dir=output_dir)
    return any(perimeter_break_language_detected(body) for body in bodies)


def perimeter_break_overlay_triggered(
    *,
    perimeter_break_detected_flag: bool,
    signal: str,
    ticker_models: pd.DataFrame,
) -> bool:
    """Group-yield strong_buy blocked until continuing-group figures exist post carve-out."""
    if not perimeter_break_detected_flag:
        return False
    if str(signal or "").strip().lower() != "strong_buy":
        return False
    return dividend_screen_passed(ticker_models)


def cap_signal_for_perimeter_break_overlay(signal: str) -> str:
    """Cap at buy — do not leave strong_buy on pre-deal consolidated group yield."""
    if signal == "strong_buy":
        return "buy"
    return signal


def _more_conservative_signal(current: str, candidate: str) -> str:
    current_rank = _SIGNAL_RANK.get(current, 0)
    candidate_rank = _SIGNAL_RANK.get(candidate, 0)
    return current if current_rank <= candidate_rank else candidate


def apply_perimeter_break_overlay_to_signal(
    signal: str,
    *,
    perimeter_break_detected_flag: bool,
    ticker_models: pd.DataFrame,
    adjusted_signal: str | None = None,
) -> tuple[bool, bool, str]:
    """Return overlay flag, detected flag, and conservative adjusted signal."""
    base_adjusted = adjusted_signal or signal
    if not perimeter_break_overlay_triggered(
        perimeter_break_detected_flag=perimeter_break_detected_flag,
        signal=signal,
        ticker_models=ticker_models,
    ):
        return False, perimeter_break_detected_flag, base_adjusted
    capped = cap_signal_for_perimeter_break_overlay(signal)
    return True, perimeter_break_detected_flag, _more_conservative_signal(base_adjusted, capped)


def enrich_signals_with_perimeter_break_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Add perimeter-break flags and cap ``adjusted_signal`` when triggered."""
    if signals.empty:
        return signals

    out = signals.copy()
    overlay_flags: list[bool] = []
    detected_flags: list[bool] = []
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

        detected_flag = row.get("perimeter_break_detected")
        if detected_flag is not None and not (
            isinstance(detected_flag, float) and pd.isna(detected_flag)
        ):
            detected = bool(detected_flag)
        else:
            detected = perimeter_break_for_ticker(ticker, output_dir=output_dir)

        triggered, _, new_adjusted = apply_perimeter_break_overlay_to_signal(
            str(row.get("signal") or "hold"),
            perimeter_break_detected_flag=detected,
            ticker_models=ticker_models,
            adjusted_signal=existing_adjusted,
        )
        overlay_flags.append(triggered)
        detected_flags.append(detected)
        adjusted.append(new_adjusted)

    out["perimeter_break_detected"] = detected_flags
    out["perimeter_break_overlay"] = overlay_flags
    out["adjusted_signal"] = adjusted
    return out
