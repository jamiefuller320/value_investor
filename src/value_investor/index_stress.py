"""Index stress detection from daily rate-of-change and drawdown features.

Observe-only helpers for archive simulation and future portfolio circuit breakers.
Uses ^FTSE (or configured benchmark) daily bars — weekly screen snapshots alone
miss intraweek gap risk.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from value_investor.backtest import BENCHMARK_TICKER

logger = logging.getLogger(__name__)

FetchDailyBars = Callable[[str, date, date], list[dict[str, Any]]]


@dataclass(frozen=True)
class IndexStressThresholds:
    """Rule-based stress triggers — calibrate via archive sim, not hand-tuned live."""

    abs_1d: float = -0.03
    abs_5d: float = -0.05
    vol_window: int = 20
    vol_z: float = 2.5
    drawdown_window: int = 20
    drawdown_from_peak: float = -0.06
    weekly_abs_fallback: float = -0.05

    def to_dict(self) -> dict[str, Any]:
        return {
            "abs_1d": self.abs_1d,
            "abs_5d": self.abs_5d,
            "vol_window": self.vol_window,
            "vol_z": self.vol_z,
            "drawdown_window": self.drawdown_window,
            "drawdown_from_peak": self.drawdown_from_peak,
            "weekly_abs_fallback": self.weekly_abs_fallback,
        }


@dataclass
class IndexStressDecision:
    date: str
    stressed: bool
    triggers: list[str] = field(default_factory=list)
    return_1d: float | None = None
    return_5d: float | None = None
    vol_z_1d: float | None = None
    drawdown: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "stressed": self.stressed,
            "triggers": list(self.triggers),
            "return_1d": self.return_1d,
            "return_5d": self.return_5d,
            "vol_z_1d": self.vol_z_1d,
            "drawdown": self.drawdown,
        }


def _parse_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text[:10])


def _safe_return(current: float, prior: float) -> float | None:
    if prior <= 0 or current <= 0:
        return None
    return (current - prior) / prior


def _rolling_std(values: Sequence[float], window: int) -> float | None:
    if len(values) < window or window < 2:
        return None
    sample = list(values[-window:])
    mean = sum(sample) / len(sample)
    var = sum((x - mean) ** 2 for x in sample) / (len(sample) - 1)
    if var <= 0:
        return None
    return math.sqrt(var)


def enrich_daily_bars(bars: list[dict[str, Any]], *, thresholds: IndexStressThresholds) -> list[dict[str, Any]]:
    """Add return, vol-z, and drawdown features to sorted daily bars."""
    if not bars:
        return []

    sorted_bars = sorted(bars, key=lambda row: str(row.get("date") or ""))
    enriched: list[dict[str, Any]] = []
    closes: list[float] = []
    returns_1d: list[float] = []

    for row in sorted_bars:
        close = float(row.get("close") or 0)
        if close <= 0:
            continue
        item = dict(row)
        item["close"] = close
        ret_1d = _safe_return(close, closes[-1]) if closes else None
        item["return_1d"] = ret_1d
        if ret_1d is not None:
            returns_1d.append(ret_1d)

        idx = len(closes)
        ret_5d = None
        if idx >= 5:
            ret_5d = _safe_return(close, closes[idx - 5])
        item["return_5d"] = ret_5d

        vol_std = _rolling_std(returns_1d, thresholds.vol_window)
        if ret_1d is not None and vol_std and vol_std > 0:
            item["vol_z_1d"] = ret_1d / vol_std
        else:
            item["vol_z_1d"] = None

        window = thresholds.drawdown_window
        if len(closes) >= window:
            peak = max(closes[-window:])
            item["drawdown"] = _safe_return(close, peak)
        elif closes:
            peak = max(closes)
            item["drawdown"] = _safe_return(close, peak)
        else:
            item["drawdown"] = None

        closes.append(close)
        enriched.append(item)
    return enriched


def evaluate_index_stress_row(
    row: dict[str, Any],
    *,
    thresholds: IndexStressThresholds,
) -> IndexStressDecision:
    """Evaluate whether one day's index features constitute a stress trigger."""
    triggers: list[str] = []
    ret_1d = row.get("return_1d")
    ret_5d = row.get("return_5d")
    vol_z = row.get("vol_z_1d")
    drawdown = row.get("drawdown")

    if ret_1d is not None and ret_1d <= thresholds.abs_1d:
        triggers.append(f"abs_1d<={thresholds.abs_1d:.1%}")
    if ret_5d is not None and ret_5d <= thresholds.abs_5d:
        triggers.append(f"abs_5d<={thresholds.abs_5d:.1%}")
    if vol_z is not None and vol_z <= -thresholds.vol_z:
        triggers.append(f"vol_z_1d<=-{thresholds.vol_z}")
    if drawdown is not None and drawdown <= thresholds.drawdown_from_peak:
        triggers.append(f"drawdown<={thresholds.drawdown_from_peak:.1%}")

    return IndexStressDecision(
        date=str(row.get("date") or ""),
        stressed=bool(triggers),
        triggers=triggers,
        return_1d=ret_1d,
        return_5d=ret_5d,
        vol_z_1d=vol_z,
        drawdown=drawdown,
    )


def label_daily_stress(
    bars: list[dict[str, Any]],
    *,
    thresholds: IndexStressThresholds | None = None,
) -> list[IndexStressDecision]:
    thresholds = thresholds or IndexStressThresholds()
    enriched = enrich_daily_bars(bars, thresholds=thresholds)
    return [evaluate_index_stress_row(row, thresholds=thresholds) for row in enriched]


def default_fetch_daily_bars(symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    """Fetch daily OHLC closes from Yahoo Finance."""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance unavailable for index stress fetch")
        return []

    try:
        frame = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat(), auto_adjust=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Index history fetch failed for %s: %s", symbol, exc)
        return []

    if frame is None or frame.empty:
        return []

    bars: list[dict[str, Any]] = []
    for idx, close in frame["Close"].dropna().items():
        day = idx.date() if hasattr(idx, "date") else _parse_date(str(idx))
        bars.append({"date": day.isoformat(), "close": float(close), "symbol": symbol})
    return bars


def weekly_proxy_stress(
    *,
    index_return: float,
    thresholds: IndexStressThresholds | None = None,
) -> IndexStressDecision:
    """Fallback when only weekly snapshot index marks exist."""
    thresholds = thresholds or IndexStressThresholds()
    stressed = index_return <= thresholds.weekly_abs_fallback
    triggers = [f"weekly_abs<={thresholds.weekly_abs_fallback:.1%}"] if stressed else []
    return IndexStressDecision(
        date="",
        stressed=stressed,
        triggers=triggers,
        return_1d=index_return,
    )


def stress_by_date(decisions: Sequence[IndexStressDecision]) -> dict[str, IndexStressDecision]:
    return {row.date: row for row in decisions if row.date}


def any_stress_between(
    decisions_by_date: dict[str, IndexStressDecision],
    *,
    start: date,
    end: date,
) -> tuple[bool, list[str]]:
    """True if any stress trigger fired on (start, end] calendar days."""
    triggers: list[str] = []
    for day_str, decision in decisions_by_date.items():
        day = _parse_date(day_str)
        if day <= start or day > end:
            continue
        if decision.stressed:
            triggers.extend(decision.triggers)
    return bool(triggers), sorted(set(triggers))


__all__ = [
    "BENCHMARK_TICKER",
    "FetchDailyBars",
    "IndexStressDecision",
    "IndexStressThresholds",
    "any_stress_between",
    "default_fetch_daily_bars",
    "enrich_daily_bars",
    "evaluate_index_stress_row",
    "label_daily_stress",
    "stress_by_date",
    "weekly_proxy_stress",
]
