"""Observe-only conviction-timing overlay for weak trajectory transition keys.

Scores counterfactual conviction/timing adjustments for hold->buy and
signal_unchanged cohorts flagged by trajectory evidence (1w positive_rate
below baseline). Does not mutate live ``assign_signal()`` thresholds or
``adjusted_signal`` — exports parallel observe-only fields only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

# Archive priors from trajectory_evidence (ana-20260903-01 / ldr-20260901-02).
HOLD_TO_BUY_KEY = "hold->buy"
SIGNAL_UNCHANGED_KEY = "signal_unchanged"
WEAK_TRANSITION_KEYS = frozenset({HOLD_TO_BUY_KEY, SIGNAL_UNCHANGED_KEY})

ARCHIVE_1W_POSITIVE_RATES: dict[str, float] = {
    HOLD_TO_BUY_KEY: 0.25,
    SIGNAL_UNCHANGED_KEY: 0.3431,
}
BASELINE_1W_HIT_RATE = 0.4205

HOLD_TO_BUY_CONVICTION_MULTIPLIER = 0.75
SIGNAL_UNCHANGED_CONVICTION_MULTIPLIER = 0.90

BUY_TIER_SIGNALS = frozenset({"buy", "strong_buy"})
TIMING_ACCUMULATE = "accumulate"
TIMING_WAIT = "wait"


def resolve_prior_signal(
    history: pd.DataFrame,
    *,
    ticker: str,
    run_at: datetime,
) -> str | None:
    """Most recent signal for ``ticker`` strictly before ``run_at``."""
    if history.empty or "ticker" not in history.columns:
        return None

    ticker_history = history[history["ticker"] == ticker].copy()
    if ticker_history.empty:
        return None

    ticker_history["run_at_dt"] = pd.to_datetime(ticker_history["run_at"], utc=True)
    current_ts = pd.Timestamp(run_at)
    if current_ts.tzinfo is None:
        current_ts = current_ts.tz_localize("UTC")

    prior = ticker_history[ticker_history["run_at_dt"] < current_ts]
    if prior.empty:
        return None
    return str(prior.iloc[-1]["signal"])


def resolve_transition_key(prior_signal: str | None, current_signal: str) -> str:
    """Trajectory ledger key: ``hold->buy``, ``signal_unchanged``, or ``new``."""
    current = str(current_signal or "hold").strip().lower()
    if prior_signal is None:
        return "new"
    prior = str(prior_signal).strip().lower()
    if prior == current:
        return SIGNAL_UNCHANGED_KEY
    return f"{prior}->{current}"


def _float_or_none(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return float(value)


def _observe_timing_signal(
    *,
    transition_key: str,
    signal: str,
    timing_signal: str,
) -> str | None:
    """Delay accumulate flips on weak cohorts; leave live timing untouched."""
    timing = str(timing_signal or "").strip().lower()
    if timing != TIMING_ACCUMULATE:
        return None
    if transition_key == HOLD_TO_BUY_KEY and signal in BUY_TIER_SIGNALS:
        return TIMING_WAIT
    if (
        transition_key == SIGNAL_UNCHANGED_KEY
        and signal in BUY_TIER_SIGNALS
        and timing == TIMING_ACCUMULATE
    ):
        return TIMING_WAIT
    return None


def build_conviction_timing_overlay(
    row: pd.Series | dict[str, Any],
    *,
    prior_signal: str | None,
) -> dict[str, Any]:
    """Build observe-only conviction/timing overlay payload for one ticker."""
    if isinstance(row, dict):
        series = pd.Series(row)
    else:
        series = row

    signal = str(series.get("signal") or "hold").strip().lower()
    timing_signal = str(series.get("timing_signal") or "neutral").strip().lower()
    conviction = _float_or_none(series.get("conviction_score")) or 0.0
    transition_key = resolve_transition_key(prior_signal, signal)

    overlay: dict[str, Any] = {
        "observe_only": True,
        "transition_key": transition_key,
        "prior_signal": prior_signal,
        "conviction_timing_overlay": False,
        "conviction_timing_overlay_score": None,
        "conviction_timing_overlay_timing": None,
        "conviction_timing_overlay_action": None,
        "archive_1w_positive_rate": ARCHIVE_1W_POSITIVE_RATES.get(transition_key),
        "baseline_1w_hit_rate": BASELINE_1W_HIT_RATE,
    }

    if transition_key not in WEAK_TRANSITION_KEYS:
        return overlay

    observe_score: float | None = None
    action: str | None = None

    if transition_key == HOLD_TO_BUY_KEY:
        observe_score = round(conviction * HOLD_TO_BUY_CONVICTION_MULTIPLIER, 4)
        action = "downweight_conviction"
    elif transition_key == SIGNAL_UNCHANGED_KEY and signal in BUY_TIER_SIGNALS:
        observe_score = round(conviction * SIGNAL_UNCHANGED_CONVICTION_MULTIPLIER, 4)
        action = "downweight_conviction"

    observe_timing = _observe_timing_signal(
        transition_key=transition_key,
        signal=signal,
        timing_signal=timing_signal,
    )
    if observe_timing is not None:
        action = "delay_timing_flip" if action is None else f"{action}+delay_timing_flip"

    if observe_score is None and observe_timing is None:
        return overlay

    overlay["conviction_timing_overlay"] = True
    overlay["conviction_timing_overlay_score"] = observe_score
    overlay["conviction_timing_overlay_timing"] = observe_timing
    overlay["conviction_timing_overlay_action"] = action
    return overlay


def format_conviction_timing_overlay_note(overlay: dict[str, Any]) -> str | None:
    """Compact summary fragment when the observe-only overlay fires."""
    if not overlay.get("conviction_timing_overlay"):
        return None

    transition_key = str(overlay.get("transition_key") or "")
    positive_rate = overlay.get("archive_1w_positive_rate")
    rate_text = f"{positive_rate:.0%}" if positive_rate is not None else "below baseline"
    parts = [
        f"Conviction-timing overlay (observe-only): {transition_key} 1w hit {rate_text}",
    ]

    observe_score = overlay.get("conviction_timing_overlay_score")
    if observe_score is not None:
        parts.append(f"scored conviction {float(observe_score):.0%}")

    observe_timing = overlay.get("conviction_timing_overlay_timing")
    if observe_timing:
        parts.append(f"observe timing {observe_timing}")

    return " — ".join(parts) + "."


def enrich_signals_with_conviction_timing_overlay(
    signals: pd.DataFrame,
    history: pd.DataFrame,
    *,
    run_at: datetime,
) -> pd.DataFrame:
    """Attach observe-only conviction-timing overlay columns."""
    if signals.empty:
        return signals

    out = signals.copy()
    overlays: list[dict[str, Any]] = []
    for _, row in out.iterrows():
        prior = resolve_prior_signal(
            history,
            ticker=str(row["ticker"]),
            run_at=run_at,
        )
        overlays.append(build_conviction_timing_overlay(row, prior_signal=prior))

    out["transition_key"] = [item["transition_key"] for item in overlays]
    out["prior_signal"] = [item.get("prior_signal") for item in overlays]
    out["conviction_timing_overlay"] = [
        bool(item["conviction_timing_overlay"]) for item in overlays
    ]
    out["conviction_timing_overlay_score"] = [
        item.get("conviction_timing_overlay_score") for item in overlays
    ]
    out["conviction_timing_overlay_timing"] = [
        item.get("conviction_timing_overlay_timing") for item in overlays
    ]
    out["conviction_timing_overlay_action"] = [
        item.get("conviction_timing_overlay_action") for item in overlays
    ]
    return out
