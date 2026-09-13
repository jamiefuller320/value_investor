"""Stamp market-aware timing_signal onto library screen-lite frames."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from value_investor.technical_analysis import compute_indicators, fetch_price_history

BUY_TIER = frozenset({"buy", "strong_buy"})
RESOLVED_TIMING = frozenset({"wait", "accumulate", "neutral"})


def _as_of_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def slice_price_history(frame: pd.DataFrame, as_of: datetime | None) -> pd.DataFrame:
    """Keep bars at or before ``as_of`` so archive timing stays point-in-time."""
    if frame is None or frame.empty or as_of is None:
        return frame
    work = frame.copy()
    idx = work.index
    if getattr(idx, "tz", None) is None:
        work.index = work.index.tz_localize("UTC")
    else:
        work.index = work.index.tz_convert("UTC")
    cutoff = _as_of_utc(as_of)
    return work.loc[work.index <= cutoff]


def timing_fields_from_history(
    frame: pd.DataFrame | None,
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"timing_signal": "insufficient_data", "timing_score": 0.0}
    sliced = slice_price_history(frame, as_of)
    tech = compute_indicators(sliced)
    return {
        "timing_signal": tech.timing_signal.value,
        "timing_score": tech.timing_score,
        "rsi_14": tech.rsi_14,
    }


def buy_tier_needs_timing_stamp(signals: pd.DataFrame) -> bool:
    """True when buy-tier rows have no resolved timing yet (wait / accumulate / neutral).

    Screen-lite writes ``insufficient_data`` until equal-support (or epoch-0)
    stamps Yahoo timing. Epoch-0 must not rebalance in that state or
    ``skip_timing_wait`` cannot drop wait names from new buys.
    """
    if signals is None or signals.empty or "ticker" not in signals.columns:
        return False
    signal_col = "signal" if "signal" in signals.columns else None
    if signal_col is None:
        return False
    buy = signals.loc[signals[signal_col].astype(str).str.strip().str.lower().isin(BUY_TIER)]
    if buy.empty:
        return False
    if "timing_signal" not in buy.columns:
        return True
    values = buy["timing_signal"].astype(str).str.strip().str.lower()
    return not values.isin(RESOLVED_TIMING).any()


def timing_candidate_tickers(signals: pd.DataFrame) -> list[str]:
    """Buy-tier plus hold names — enough for buy-not-now and below-tier timing."""
    if signals.empty or "ticker" not in signals.columns:
        return []
    signal_col = "signal" if "signal" in signals.columns else None
    out: list[str] = []
    for row in signals.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        signal = str(row.get(signal_col) or "").strip().lower() if signal_col else ""
        if signal in BUY_TIER or signal == "hold":
            out.append(ticker)
    return list(dict.fromkeys(out))


def stamp_timing_on_signals(
    signals: pd.DataFrame,
    *,
    market: str,
    as_of: datetime | None = None,
    history: dict[str, pd.DataFrame] | None = None,
    tickers: list[str] | None = None,
) -> pd.DataFrame:
    """Add timing_signal using market Yahoo symbols (not LSE .L)."""
    out = signals.copy()
    if out.empty or "ticker" not in out.columns:
        return out
    wanted = tickers or timing_candidate_tickers(out)
    frames = history if history is not None else fetch_price_history(wanted, market=market)
    if "timing_signal" not in out.columns:
        out["timing_signal"] = "insufficient_data"
    if "timing_score" not in out.columns:
        out["timing_score"] = 0.0
    for idx, row in out.iterrows():
        ticker = str(row.get("ticker") or "").strip()
        if not ticker or ticker not in frames:
            continue
        fields = timing_fields_from_history(frames.get(ticker), as_of=as_of)
        out.at[idx, "timing_signal"] = fields["timing_signal"]
        out.at[idx, "timing_score"] = fields["timing_score"]
        if fields.get("rsi_14") is not None:
            out.at[idx, "rsi_14"] = fields["rsi_14"]
    return out


__all__ = [
    "buy_tier_needs_timing_stamp",
    "slice_price_history",
    "stamp_timing_on_signals",
    "timing_candidate_tickers",
    "timing_fields_from_history",
]
