"""Replay the trade plan's tactical slice on daily prices.

The live trade plan (``technical_analysis.compute_trade_plan``) is stateless:
every screen run recomputes, for buy-tier names, a core fraction plus a
tactical dip limit, stop, and take-profit from about a year of adjusted daily
prices. This module rebuilds those plans on each weekly plan date from the
same price-only inputs, then simulates the tactical slice of a core holding:

* While the core is held, the slice waits in cash for the active plan's limit.
* A fill fixes that plan's stop and target. The stop is checked first each day
  (conservative when both trade); gaps fill at the open.
* After an exit the slice re-arms only on a newer plan, so one holding can run
  several buy/sell cycles.
* When the core exits (or the name delists) an open slice is closed with it.

Indicators come from the module's own helpers over the full history. Their
exponential smoothing forgets the start within a few dozen bars, so values match
``compute_indicators`` on the live one-year window (tested).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from value_investor.technical_analysis import (
    MIN_BARS,
    TechnicalIndicators,
    TimingSignal,
    TradePlanConfig,
    _atr,
    _macd_histogram,
    _rsi,
    assign_timing_signal,
    compute_trade_plan,
)

BUY_TIER = frozenset({"buy", "strong_buy"})


@dataclass
class PriceSeries:
    """One ticker's adjusted daily bars on its own trading days."""

    dates: np.ndarray  # datetime64[ns], ascending
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    def index_on_or_before(self, day: np.datetime64) -> int:
        return int(np.searchsorted(self.dates, day, side="right")) - 1


def price_series_from_daily(daily: pd.DataFrame) -> dict[str, PriceSeries]:
    frame = daily.assign(date=pd.to_datetime(daily["date"])).sort_values(["ticker", "date"])
    out: dict[str, PriceSeries] = {}
    for ticker, rows in frame.groupby("ticker", sort=False):
        close = rows["close"].to_numpy(dtype=float)
        out[str(ticker)] = PriceSeries(
            dates=rows["date"].to_numpy(dtype="datetime64[ns]"),
            open=rows["open"].fillna(rows["close"]).to_numpy(dtype=float),
            high=rows["high"].fillna(rows["close"]).to_numpy(dtype=float),
            low=rows["low"].fillna(rows["close"]).to_numpy(dtype=float),
            close=close,
        )
    return out


def indicator_frame(series: PriceSeries, *, recent_low_days: int = 20) -> pd.DataFrame:
    """Per-day indicators matching ``compute_indicators`` on the trailing window."""
    close = pd.Series(series.close)
    hist, _ = _macd_histogram(close)
    atr = _atr(pd.Series(series.high), pd.Series(series.low), close)
    frame = pd.DataFrame(
        {
            "close": close,
            "rsi_14": _rsi(close).astype(float),
            "sma_50": close.rolling(50).mean(),
            "sma_200": close.rolling(200).mean(),
            "macd_hist": hist,
            "macd_hist_prev": hist.shift(1),
            "atr_14": atr,
            "recent_low": close.rolling(recent_low_days).min(),
        }
    )
    frame["enough_bars"] = np.arange(len(frame)) + 1 >= MIN_BARS
    return frame


def _opt(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def plan_on(
    ind: pd.DataFrame, i: int, config: TradePlanConfig, *, value_signal: str = "buy"
) -> dict[str, float] | None:
    """The live trade plan for bar ``i`` (None when the live screen would have none)."""
    row = ind.iloc[i]
    if not row["enough_bars"] or pd.isna(row["rsi_14"]):
        return None
    close = float(row["close"])
    sma50, sma200 = _opt(row["sma_50"]), _opt(row["sma_200"])
    rsi = _opt(row["rsi_14"])
    timing, score, reasons = assign_timing_signal(
        rsi=rsi,
        close=close,
        sma_50=sma50,
        sma_200=sma200,
        macd_histogram=_opt(row["macd_hist"]),
        macd_histogram_prev=_opt(row["macd_hist_prev"]),
    )
    if timing == TimingSignal.INSUFFICIENT_DATA:
        return None
    tech = TechnicalIndicators(
        close=close,
        rsi_14=rsi,
        sma_50=sma50,
        sma_200=sma200,
        atr_14=_opt(row["atr_14"]),
        timing_signal=timing,
        timing_score=score,
    )
    days = int(config.recent_low_days)
    window = ind["close"].iloc[max(0, i - days + 1) : i + 1]
    plan = compute_trade_plan(window, tech, value_signal=value_signal, config=config)
    if plan is None or plan.tactical_limit is None:
        return None
    return {
        "core_pct": float(plan.core_allocation_pct),
        "limit": float(plan.tactical_limit),
        "stop": float(plan.tactical_stop_loss),
        "target": float(plan.tactical_take_profit),
    }


def weekly_plan_indices(series: PriceSeries) -> np.ndarray:
    """Bar index of the last trading day of each ISO week."""
    weeks = pd.DatetimeIndex(series.dates).to_period("W")
    last = pd.Series(np.arange(len(weeks))).groupby(np.asarray(weeks)).max()
    return last.to_numpy(dtype=int)


@dataclass
class TickerPlans:
    """Weekly plans for one ticker under one ``TradePlanConfig``."""

    bar: list[int] = field(default_factory=list)
    core_pct: list[float] = field(default_factory=list)
    limit: list[float] = field(default_factory=list)
    stop: list[float] = field(default_factory=list)
    target: list[float] = field(default_factory=list)
    # Last bar the plan is live: the next weekly plan date, when the live screen
    # would have replaced it (or dropped it if the name left the buy tier).
    valid_to: list[int] = field(default_factory=list)

    def latest_before(self, bar: int) -> int:
        """Index of the newest plan computed at a close strictly before ``bar``."""
        return bisect.bisect_left(self.bar, bar) - 1

    def latest_on_or_before(self, bar: int) -> int:
        return bisect.bisect_right(self.bar, bar) - 1


def build_ticker_plans(
    series: PriceSeries,
    ind: pd.DataFrame,
    buy_tier_from: list[tuple[np.datetime64, bool]],
    config: TradePlanConfig,
) -> TickerPlans:
    """Plans on weekly dates where the latest monthly screen signal is buy tier.

    ``buy_tier_from`` lists (screen date, in buy tier) in date order; a plan
    date uses the newest screen dated on or before it.
    """
    plans = TickerPlans()
    if not buy_tier_from:
        return plans
    screen_dates = np.array([d for d, _ in buy_tier_from], dtype="datetime64[ns]")
    in_tier = [flag for _, flag in buy_tier_from]
    weekly = weekly_plan_indices(series)
    for pos, i in enumerate(weekly):
        k = int(np.searchsorted(screen_dates, series.dates[i], side="right")) - 1
        if k < 0 or not in_tier[k]:
            continue
        plan = plan_on(ind, int(i), config)
        if plan is None:
            continue
        plans.bar.append(int(i))
        plans.core_pct.append(plan["core_pct"])
        plans.limit.append(plan["limit"])
        plans.stop.append(plan["stop"])
        plans.target.append(plan["target"])
        plans.valid_to.append(
            int(weekly[pos + 1]) if pos + 1 < len(weekly) else len(series.close) - 1
        )
    return plans


@dataclass
class SliceTrade:
    entry_bar: int
    entry_price: float
    exit_bar: int
    exit_price: float
    exit_kind: str  # stop | target | core_exit | delisted

    @property
    def gross_return(self) -> float:
        return self.exit_price / self.entry_price - 1.0


@dataclass
class SliceResult:
    """Slice value (start = 1.0) on requested bars, plus the trades it made."""

    values: dict[int, float]
    in_position: dict[int, bool]
    trades: list[SliceTrade]


def simulate_slice(
    series: PriceSeries,
    plans: TickerPlans,
    *,
    start_bar: int,
    end_bar: int,
    eval_bars: list[int],
    cost_per_side: float,
    terminal_haircut: float | None = None,
) -> SliceResult:
    """Tactical slice from the close of ``start_bar`` to the close of ``end_bar``.

    ``terminal_haircut`` set means the series ends at ``end_bar`` (delisting):
    an open position exits at that close times ``1 + haircut``.
    """
    o, h, low, c = series.open, series.high, series.low, series.close
    cash = 1.0
    segments: list[tuple[int, int, float]] = []  # (from_bar, to_bar_exclusive, shares)
    cash_after: list[tuple[int, float]] = [(start_bar, 1.0)]
    trades: list[SliceTrade] = []
    used_plan = -1
    d = start_bar + 1
    last_fill_bar = end_bar - 1
    while d <= last_fill_bar:
        j = plans.latest_before(d)
        if j <= used_plan or j < 0 or plans.valid_to[j] < d:
            nxt = max(j, used_plan) + 1
            if nxt >= len(plans.bar):
                break
            d = max(d, plans.bar[nxt] + 1)
            continue
        active_to = min(plans.valid_to[j], last_fill_bar)
        limit = plans.limit[j]
        hits = np.nonzero(low[d : active_to + 1] <= limit)[0]
        if not len(hits):
            d = active_to + 1
            continue
        fill = d + int(hits[0])
        entry = min(float(o[fill]), limit)
        shares = cash * (1.0 - cost_per_side) / entry
        used_plan = j
        stop, target = plans.stop[j], plans.target[j]
        after = fill + 1
        stop_hit = low[after : end_bar + 1] <= stop
        tgt_hit = h[after : end_bar + 1] >= target
        either = np.nonzero(stop_hit | tgt_hit)[0]
        if len(either):
            x = after + int(either[0])
            if low[x] <= stop:
                px, kind = min(float(o[x]), stop), "stop"
            else:
                px, kind = max(float(o[x]), target), "target"
        else:
            x = end_bar
            if terminal_haircut is not None:
                px, kind = float(c[x]) * (1.0 + terminal_haircut), "delisted"
            else:
                px, kind = float(c[x]), "core_exit"
        cash = shares * px * (1.0 - cost_per_side)
        segments.append((fill, x, shares))
        cash_after.append((x, cash))
        trades.append(SliceTrade(fill, entry, x, px, kind))
        d = x + 1

    values: dict[int, float] = {}
    in_position: dict[int, bool] = {}
    for bar in eval_bars:
        seg = next((s for s in segments if s[0] <= bar < s[1]), None)
        if seg is not None:
            values[bar] = seg[2] * float(c[bar])
            in_position[bar] = True
        else:
            k = bisect.bisect_right([b for b, _ in cash_after], bar) - 1
            values[bar] = cash_after[max(k, 0)][1]
            in_position[bar] = False
    return SliceResult(values=values, in_position=in_position, trades=trades)
