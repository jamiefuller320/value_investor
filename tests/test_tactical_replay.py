"""Tactical-slice replay: live trade-plan parity and slice fills (synthetic prices)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from value_investor import tactical_replay as tr
from value_investor.technical_analysis import (
    TradePlanConfig,
    compute_indicators,
    compute_trade_plan,
)


def _walk(n: int = 700, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.018, n)))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.008, n)))
    dates = pd.bdate_range("2004-01-01", periods=n)
    return pd.DataFrame(
        {"ticker": "AAA", "date": dates, "open": open_, "high": high, "low": low, "close": close}
    )


def test_plan_matches_live_trade_plan_on_one_year_window():
    daily = _walk()
    series = tr.price_series_from_daily(daily)["AAA"]
    ind = tr.indicator_frame(series)
    cfg = TradePlanConfig()
    checked = 0
    for i in tr.weekly_plan_indices(series):
        if i < 450:
            continue
        window = daily.iloc[i - 251 : i + 1]
        ohlc = window.rename(columns={"close": "Close", "high": "High", "low": "Low"})
        tech = compute_indicators(ohlc[["Close", "High", "Low"]].reset_index(drop=True))
        live = compute_trade_plan(
            window["close"].reset_index(drop=True), tech, value_signal="buy", config=cfg
        )
        replay = tr.plan_on(ind, int(i), cfg)
        assert (live is None) == (replay is None)
        if live is None:
            continue
        assert replay["core_pct"] == pytest.approx(live.core_allocation_pct)
        assert replay["limit"] == pytest.approx(live.tactical_limit, abs=0.011)
        assert replay["stop"] == pytest.approx(live.tactical_stop_loss, abs=0.011)
        assert replay["target"] == pytest.approx(live.tactical_take_profit, abs=0.011)
        checked += 1
    assert checked >= 40


def test_plans_only_while_screen_is_buy_tier():
    daily = _walk()
    series = tr.price_series_from_daily(daily)["AAA"]
    ind = tr.indicator_frame(series)
    d = series.dates
    tiers = [(d[0], True), (d[400], False), (d[550], True)]
    plans = tr.build_ticker_plans(series, ind, tiers, TradePlanConfig())
    assert plans.bar
    assert all(b >= tr.MIN_BARS - 1 for b in plans.bar)
    assert not any(400 <= b < 550 for b in plans.bar)
    assert all(v >= b for b, v in zip(plans.bar, plans.valid_to, strict=True))


def _series(lows: list[float], highs: list[float], opens: list[float] | None = None):
    n = len(lows)
    close = np.full(n, 100.0)
    return tr.PriceSeries(
        dates=pd.bdate_range("2010-01-04", periods=n).to_numpy(dtype="datetime64[ns]"),
        open=np.array(opens if opens else [100.0] * n, dtype=float),
        high=np.array(highs, dtype=float),
        low=np.array(lows, dtype=float),
        close=close,
    )


def _plans(*rows: tuple[int, int]) -> tr.TickerPlans:
    plans = tr.TickerPlans()
    for bar, valid_to in rows:
        plans.bar.append(bar)
        plans.core_pct.append(0.6)
        plans.limit.append(95.0)
        plans.stop.append(90.0)
        plans.target.append(105.0)
        plans.valid_to.append(valid_to)
    return plans


FLAT_LOW = [99.0] * 12
FLAT_HIGH = [101.0] * 12


def _with(values: list[float], **at: float) -> list[float]:
    out = list(values)
    for key, value in at.items():
        out[int(key[1:])] = value
    return out


def test_fill_at_limit_then_target():
    s = _series(_with(FLAT_LOW, b2=94.0), _with(FLAT_HIGH, b4=106.0))
    res = tr.simulate_slice(
        s, _plans((0, 11)), start_bar=0, end_bar=11, eval_bars=[1, 3, 11], cost_per_side=0.0
    )
    (trade,) = res.trades
    assert (trade.entry_bar, trade.entry_price) == (2, 95.0)
    assert (trade.exit_bar, trade.exit_price, trade.exit_kind) == (4, 105.0, "target")
    assert res.values[1] == 1.0 and not res.in_position[1]
    assert res.values[3] == pytest.approx(100 / 95) and res.in_position[3]
    assert res.values[11] == pytest.approx(105 / 95)


def test_gaps_fill_at_the_open():
    s = _series(
        _with(FLAT_LOW, b2=92.0, b5=85.0),
        FLAT_HIGH,
        opens=_with([100.0] * 12, b2=93.0, b5=88.0),
    )
    res = tr.simulate_slice(
        s, _plans((0, 11)), start_bar=0, end_bar=11, eval_bars=[11], cost_per_side=0.0
    )
    (trade,) = res.trades
    assert trade.entry_price == 93.0
    assert (trade.exit_price, trade.exit_kind) == (88.0, "stop")


def test_stop_checked_before_target_on_the_same_day():
    s = _series(_with(FLAT_LOW, b2=94.0, b3=89.0), _with(FLAT_HIGH, b3=106.0))
    res = tr.simulate_slice(
        s, _plans((0, 11)), start_bar=0, end_bar=11, eval_bars=[11], cost_per_side=0.0
    )
    assert res.trades[0].exit_kind == "stop"
    assert res.trades[0].exit_price == 90.0


def test_rearms_only_on_a_newer_plan_so_one_holding_can_cycle():
    lows = _with(FLAT_LOW, b2=94.0, b4=94.0, b7=94.0)
    highs = _with(FLAT_HIGH, b3=106.0, b8=106.0)
    s = _series(lows, highs)
    res = tr.simulate_slice(
        s, _plans((0, 5), (5, 11)), start_bar=0, end_bar=11, eval_bars=[11], cost_per_side=0.0
    )
    assert [(t.entry_bar, t.exit_bar) for t in res.trades] == [(2, 3), (7, 8)]
    assert res.values[11] == pytest.approx((105 / 95) ** 2)


def test_expired_plan_does_not_fill():
    s = _series(_with(FLAT_LOW, b4=94.0), FLAT_HIGH)
    res = tr.simulate_slice(
        s, _plans((0, 3)), start_bar=0, end_bar=11, eval_bars=[11], cost_per_side=0.0
    )
    assert res.trades == []
    assert res.values[11] == 1.0


def test_no_fill_on_core_exit_day_and_open_slice_closes_with_core():
    s = _series(_with(FLAT_LOW, b11=90.5), FLAT_HIGH)
    res = tr.simulate_slice(
        s, _plans((0, 11)), start_bar=0, end_bar=11, eval_bars=[11], cost_per_side=0.0
    )
    assert res.trades == []

    s = _series(_with(FLAT_LOW, b2=94.0), FLAT_HIGH)
    res = tr.simulate_slice(
        s, _plans((0, 11)), start_bar=0, end_bar=11, eval_bars=[11], cost_per_side=0.0
    )
    assert res.trades[0].exit_kind == "core_exit"
    assert res.values[11] == pytest.approx(100 / 95)


def test_delisting_haircut_and_costs():
    s = _series(_with(FLAT_LOW, b2=94.0), FLAT_HIGH)
    res = tr.simulate_slice(
        s,
        _plans((0, 11)),
        start_bar=0,
        end_bar=11,
        eval_bars=[11],
        cost_per_side=0.01,
        terminal_haircut=-0.5,
    )
    assert res.trades[0].exit_kind == "delisted"
    assert res.values[11] == pytest.approx(0.99 / 95 * 50 * 0.99)
