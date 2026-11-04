"""Report-only price channel columns at a signal close (N254).

Channels other traders draw, computed from one chart payload (``dates``,
``closes``, ``highs``, ``lows``) using only bars up to and including the
signal session:

- log-price regression channel, 6 months (126 sessions, primary) and
  12 months (252 sessions, context): slope, fit, position in residual
  standard deviations, band bucket;
- Bollinger(20, 2) on closes;
- Donchian 20 and 55 on highs and lows (the prior sessions, not today);
- trendlines through the last two swing lows (support) and swing highs
  (resistance) inside the 6-month window; a swing point needs
  ``PIVOT_SPAN`` sessions on each side, so none is confirmed by later bars;
- distance from the 50- and 200-session averages and the 52-week high/low.

Definitions are frozen by the strategy-book registration (section 8). The
columns label episodes for the board; they never enter, exit or size one.
Charts written before highs/lows were stored fall back to closes and say so
in ``hl_basis``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

CHANNEL_DIAGNOSTICS_VERSION = "channel_v0"
PRIMARY_WINDOW = 126
CONTEXT_WINDOW = 252
REGRESSION_BAND_SD = 2.0
TREND_R2_MIN = 0.25
BOLLINGER_WINDOW = 20
BOLLINGER_SD = 2.0
DONCHIAN_WINDOWS = (20, 55)
PIVOT_SPAN = 5
SESSIONS_PER_YEAR = 252


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number <= 0:
        return None
    return number


def _pct(value: float, reference: float) -> float:
    return round((value / reference - 1.0) * 100.0, 2)


def _signal_index(dates: Sequence[str], as_of: str) -> int | None:
    """Index of the last session on or before ``as_of``."""
    cutoff = str(as_of)[:10]
    found = None
    for i, raw in enumerate(dates):
        if str(raw)[:10] <= cutoff:
            found = i
        else:
            break
    return found


def regression_channel(closes: np.ndarray, window: int) -> dict[str, Any]:
    """Log-price OLS channel over the last ``window`` closes."""
    prefix = f"ch{window}"
    if len(closes) < window:
        return {f"{prefix}_status": "insufficient_history"}
    y = np.log(closes[-window:])
    x = np.arange(window, dtype="float64")
    slope, intercept = np.polyfit(x, y, 1)
    fitted = intercept + slope * x
    resid = y - fitted
    sd = float(np.std(resid, ddof=2))
    total = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid**2)) / total if total > 0 else 0.0
    z = float(resid[-1] / sd) if sd > 0 else 0.0
    if z <= -REGRESSION_BAND_SD:
        bucket = "below_lower"
    elif z < 0:
        bucket = "lower_half"
    elif z < REGRESSION_BAND_SD:
        bucket = "upper_half"
    else:
        bucket = "above_upper"
    if r2 >= TREND_R2_MIN:
        direction = "rising" if slope > 0 else "falling"
    else:
        direction = "sideways"
    return {
        f"{prefix}_status": "ok",
        f"{prefix}_slope_pct_yr": round((math.exp(slope * SESSIONS_PER_YEAR) - 1.0) * 100.0, 2),
        f"{prefix}_r2": round(r2, 3),
        f"{prefix}_z": round(z, 2),
        f"{prefix}_bucket": bucket,
        f"{prefix}_direction": direction,
        f"{prefix}_lower": round(math.exp(fitted[-1] - REGRESSION_BAND_SD * sd), 4),
        f"{prefix}_upper": round(math.exp(fitted[-1] + REGRESSION_BAND_SD * sd), 4),
    }


def bollinger(closes: np.ndarray) -> dict[str, Any]:
    if len(closes) < BOLLINGER_WINDOW:
        return {"bb20_pct_b": None, "bb20_width_pct": None}
    window = closes[-BOLLINGER_WINDOW:]
    mid = float(window.mean())
    sd = float(window.std(ddof=0))
    if sd <= 0:
        return {"bb20_pct_b": None, "bb20_width_pct": 0.0}
    lower = mid - BOLLINGER_SD * sd
    upper = mid + BOLLINGER_SD * sd
    return {
        "bb20_pct_b": round((float(closes[-1]) - lower) / (upper - lower), 3),
        "bb20_width_pct": round((upper - lower) / mid * 100.0, 2),
    }


def donchian(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> dict[str, Any]:
    out: dict[str, Any] = {}
    close = float(closes[-1])
    for window in DONCHIAN_WINDOWS:
        prefix = f"dc{window}"
        if len(closes) < window + 1:
            out.update(
                {f"{prefix}_pos": None, f"{prefix}_new_low": None, f"{prefix}_new_high": None}
            )
            continue
        top = float(highs[-window - 1 : -1].max())
        bottom = float(lows[-window - 1 : -1].min())
        span = top - bottom
        out[f"{prefix}_pos"] = round((close - bottom) / span, 3) if span > 0 else None
        out[f"{prefix}_new_low"] = bool(lows[-1] < bottom)
        out[f"{prefix}_new_high"] = bool(highs[-1] > top)
    return out


def _pivots(values: np.ndarray, *, low: bool, start: int) -> list[int]:
    """Confirmed swing points at or after ``start``.

    A swing low is strictly below every other bar within ``PIVOT_SPAN``
    sessions on each side (a swing high strictly above), so a flat stretch
    has none.
    """
    found: list[int] = []
    last = len(values) - 1 - PIVOT_SPAN
    for j in range(max(start, PIVOT_SPAN), last + 1):
        others = np.concatenate((values[j - PIVOT_SPAN : j], values[j + 1 : j + PIVOT_SPAN + 1]))
        if (values[j] < others.min()) if low else (values[j] > others.max()):
            found.append(j)
    return found


def trendline(closes: np.ndarray, values: np.ndarray, *, low: bool) -> dict[str, Any]:
    prefix = "support" if low else "resistance"
    empty = {f"{prefix}_dist_pct": None, f"{prefix}_slope": None, f"{prefix}_broken": None}
    if len(closes) < PRIMARY_WINDOW:
        return empty
    start = len(closes) - PRIMARY_WINDOW
    points = _pivots(values, low=low, start=start)
    if len(points) < 2:
        return empty
    j1, j2 = points[-2], points[-1]
    v1, v2 = float(values[j1]), float(values[j2])
    i = len(closes) - 1
    projected = v2 + (v2 - v1) / (j2 - j1) * (i - j2)
    if projected <= 0:
        return empty
    close = float(closes[-1])
    return {
        f"{prefix}_dist_pct": _pct(close, projected),
        f"{prefix}_slope": "rising" if v2 > v1 else ("falling" if v2 < v1 else "flat"),
        f"{prefix}_broken": bool(close < projected) if low else bool(close > projected),
    }


def averages(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> dict[str, Any]:
    close = float(closes[-1])
    out: dict[str, Any] = {}
    sma50 = float(closes[-50:].mean()) if len(closes) >= 50 else None
    sma200 = float(closes[-200:].mean()) if len(closes) >= 200 else None
    out["sma50_dist_pct"] = _pct(close, sma50) if sma50 else None
    out["sma200_dist_pct"] = _pct(close, sma200) if sma200 else None
    out["sma50_above_sma200"] = bool(sma50 > sma200) if sma50 and sma200 else None
    if len(closes) >= SESSIONS_PER_YEAR:
        out["hi252_dist_pct"] = _pct(close, float(highs[-SESSIONS_PER_YEAR:].max()))
        out["lo252_dist_pct"] = _pct(close, float(lows[-SESSIONS_PER_YEAR:].min()))
    else:
        out["hi252_dist_pct"] = None
        out["lo252_dist_pct"] = None
    return out


def channel_columns(
    dates: Sequence[str],
    closes: Sequence[Any],
    highs: Sequence[Any] | None = None,
    lows: Sequence[Any] | None = None,
    *,
    as_of: str,
) -> dict[str, Any]:
    """All channel columns at the last session on or before ``as_of``."""
    out: dict[str, Any] = {"channel_version": CHANNEL_DIAGNOSTICS_VERSION}
    i = _signal_index(dates, as_of)
    if i is None:
        out["channel_status"] = "no_bar_on_or_before_as_of"
        return out

    rows: list[tuple[float, float, float, bool]] = []
    for k in range(i + 1):
        close = _as_float(closes[k])
        if close is None:
            continue
        high = _as_float(highs[k]) if highs is not None and k < len(highs) else None
        low = _as_float(lows[k]) if lows is not None and k < len(lows) else None
        filled = high is None or low is None
        rows.append(
            (close, max(high or close, close), min(low or close, close), filled),
        )
    if not rows:
        out["channel_status"] = "no_closes"
        return out

    c = np.array([r[0] for r in rows], dtype="float64")
    h = np.array([r[1] for r in rows], dtype="float64")
    lo = np.array([r[2] for r in rows], dtype="float64")
    recent = [r[3] for r in rows[-CONTEXT_WINDOW:]]
    if not any(recent):
        basis = "high_low"
    elif all(recent):
        basis = "closes"
    else:
        basis = "partial"

    out["channel_status"] = "ok"
    out["channel_as_of"] = str(dates[i])[:10]
    out["hl_basis"] = basis
    out["bars"] = len(c)
    out.update(regression_channel(c, PRIMARY_WINDOW))
    out.update(regression_channel(c, CONTEXT_WINDOW))
    out.update(bollinger(c))
    out.update(donchian(c, h, lo))
    out.update(trendline(c, lo, low=True))
    out.update(trendline(c, h, low=False))
    out.update(averages(c, h, lo))
    return out


def channel_columns_from_chart(payload: dict[str, Any], *, as_of: str) -> dict[str, Any]:
    """``channel_columns`` on a ``docs/data/charts/<TICKER>.json`` payload."""
    return channel_columns(
        payload.get("dates") or [],
        payload.get("closes") or [],
        payload.get("highs"),
        payload.get("lows"),
        as_of=as_of,
    )


DEFAULT_CHARTS_DIR = "docs/data/charts"
CHART_HL_COMPLETE_TITLE = "Chart highs and lows complete"
CHART_HL_INCOMPLETE_TITLE = "Chart highs and lows incomplete"
CHART_HL_MIN_SHARE = 0.95


def ops_findings_from_chart_high_low_coverage(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    """Observe-only finding: share of charts carrying highs and lows."""
    total = int(coverage.get("charts") or 0)
    if total == 0:
        return []
    done = int(coverage.get("with_high_low") or 0)
    share = done / total
    complete = share >= CHART_HL_MIN_SHARE
    return [
        {
            "severity": "info" if complete else "warn",
            "category": "research",
            "title": CHART_HL_COMPLETE_TITLE if complete else CHART_HL_INCOMPLETE_TITLE,
            "summary": (
                f"{done} of {total} charts ({share:.0%}) store daily highs and lows. "
                "Channel columns (N254) use closes in place of missing highs/lows and "
                "label them hl_basis=closes. Charts gain highs/lows on their next rebuild "
                "(publish schema refresh or the strategy-book close refresh)."
            ),
        }
    ]


def chart_high_low_coverage(chart_dir: Any) -> dict[str, Any]:
    """Counts of chart files with a full ``highs``/``lows`` record."""
    from pathlib import Path

    from value_investor.storage import read_json

    total = with_hl = 0
    for path in sorted(Path(chart_dir).glob("*.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict) or not payload.get("dates"):
            continue
        total += 1
        highs = payload.get("highs") or []
        lows = payload.get("lows") or []
        if (
            len(highs) == len(payload["dates"])
            and len(lows) == len(highs)
            and any(v is not None for v in highs)
        ):
            with_hl += 1
    return {"charts": total, "with_high_low": with_hl}
