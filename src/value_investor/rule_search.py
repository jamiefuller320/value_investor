"""Pre-registered search over selection and tactical rules (registration ``hrs-v1``).

Runs on the licensed replay inputs built by ``ftse-historical-replay build-panel``
(outside the repository) and the screen signals cached by the replay. Each rule
set is a combination of:

* **selection** applied to the frozen screen's output: which tier, optionally
  only the top N by conviction, and the registered **exit rule** that sells the
  core (leaving the selection, a confirmed thesis break, or a confirmed
  re-rating to no longer cheap);
* **tactical**: off (core only), or a trade-plan variant whose dip slice is
  replayed on daily prices by ``tactical_replay``.

The search scores every registered combination on the development window only,
by the lower confidence bound of the probability that the book beats a plain
value book (the hsr-v1 earnings-yield sort, equal weight, same costs) over the
registered horizon. Both face the same value regime, so a decade when growth
led the market does not decide the answer; the excess over the cap-weighted
universe is reported as market context. It picks from a plateau
(median over one-step neighbours), reports the probability of backtest
overfitting and the deflated Sharpe ratio, and commits only config-level
aggregates. The holdout is evaluated once, for the frozen rules and the chosen
rules, each with and without the tactical slice.

The screen code is never edited: thresholds that live in fingerprinted code are
not part of the grid.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from value_investor import historical_screen_replay as hsr
from value_investor.tactical_replay import (
    BUY_TIER,
    PriceSeries,
    TickerPlans,
    build_ticker_plans,
    indicator_frame,
    price_series_from_daily,
    simulate_slice,
)
from value_investor.technical_analysis import trade_plan_config_for_market

DEFAULT_REGISTRATION_PATH = hsr.REPO_ROOT / "docs/data/historical_rule_search_registration.json"
DEFAULT_STORE_PATH = Path("docs/data/historical_rule_search.json")
RULE_CODE_PATHS = ("technical_analysis.py", "tactical_replay.py", "rule_search.py")
PRICE_STALE_DAYS = 7
NORMAL = NormalDist()

STALE_REGISTRATION_TITLE = "Historical rule search registration predates rule code"
STALE_VERDICT_TITLE = "Historical rule search verdict no longer describes the live rules"
HOLDOUT_REUSED_TITLE = "Historical rule search holdout revealed more than once"


def rule_code_fingerprint(package_dir: Path = hsr.PACKAGE_DIR) -> str:
    digest = hashlib.sha256()
    for rel in RULE_CODE_PATHS:
        path = Path(package_dir) / rel
        digest.update(rel.encode())
        digest.update(hsr.fingerprint_file_bytes(path) if path.exists() else b"<missing>")
    return digest.hexdigest()


def load_registration(path: Path = DEFAULT_REGISTRATION_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --- Rule sets -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleConfig:
    tier: str
    top_n: int | None
    exit_rule: str  # key into the registered exit_rules
    tactical: str | None  # key into the registered tactical variants; None = core only

    @property
    def id(self) -> str:
        top = "all" if self.top_n is None else str(self.top_n)
        return f"{self.tier}|top={top}|exit={self.exit_rule}|tac={self.tactical or 'off'}"

    def core_only(self) -> RuleConfig:
        return replace(self, tactical=None)

    def params(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "top_n": self.top_n,
            "exit_rule": self.exit_rule,
            "tactical": self.tactical,
        }


def tactical_keys(grid: Mapping[str, Any]) -> list[str]:
    tac = grid["tactical"]
    return [
        f"limit={a}|stop={b}|target={c}"
        for a, b, c in itertools.product(tac["limit"], tac["stop"], tac["target"])
    ]


def grid_configs(registration: Mapping[str, Any]) -> list[RuleConfig]:
    grid = registration["grid"]
    sel = grid["selection"]
    tacticals: list[str | None] = [None, *tactical_keys(grid)]
    return [
        RuleConfig(tier, top_n, exit_rule, tac)
        for tier in sel["tier"]
        for top_n in sel["top_n"]
        for exit_rule in sel["exit_rule"]
        for tac in tacticals
    ]


def frozen_config(registration: Mapping[str, Any]) -> RuleConfig:
    f = registration["frozen_config"]
    return RuleConfig(f["tier"], f["top_n"], f["exit_rule"], f["tactical"])


def trade_plan_config(registration: Mapping[str, Any], key: str):
    """Market-cost trade-plan config with the variant's registered overrides."""
    tac = registration["grid"]["tactical"]
    parts = dict(part.split("=", 1) for part in key.split("|"))
    overrides: dict[str, Any] = {}
    for dim in ("limit", "stop", "target"):
        overrides.update(tac["variants"][dim][parts[dim]])
    base = trade_plan_config_for_market(registration["market_id"])
    return replace(base, **overrides)


def neighbours(config: RuleConfig, registration: Mapping[str, Any]) -> list[RuleConfig]:
    """Configs one registered step away in a single dimension."""
    grid = registration["grid"]
    sel = grid["selection"]
    out: list[RuleConfig] = []

    def step(values: Sequence[Any], current: Any) -> list[Any]:
        i = list(values).index(current)
        return [values[j] for j in (i - 1, i + 1) if 0 <= j < len(values)]

    for tier in step(sel["tier"], config.tier):
        out.append(replace(config, tier=tier))
    for top_n in step(sel["top_n"], config.top_n):
        out.append(replace(config, top_n=top_n))
    for exit_rule in step(sel["exit_rule"], config.exit_rule):
        out.append(replace(config, exit_rule=exit_rule))
    if config.tactical is not None:
        parts = dict(part.split("=", 1) for part in config.tactical.split("|"))
        tac = grid["tactical"]
        for dim in ("limit", "stop", "target"):
            for value in step(tac[dim], parts[dim]):
                moved = {**parts, dim: value}
                out.append(
                    replace(
                        config,
                        tactical=f"limit={moved['limit']}|stop={moved['stop']}"
                        f"|target={moved['target']}",
                    )
                )
    return out


# --- Data ----------------------------------------------------------------------------------


def _naive(ts: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(UTC).tz_localize(None)
    return stamp.normalize()


@dataclass
class ScreenDate:
    date: pd.Timestamp
    signal: dict[str, str]
    conviction: dict[str, float]
    market_cap: dict[str, float]
    # Earnings-yield percentile among names screened that date (0 = dearest).
    ey_pct: dict[str, float] = field(default_factory=dict)
    # The hsr-v1 plain value sort: top 30% by positive earnings yield.
    plain_value: frozenset[str] = frozenset()


class SearchData:
    """Signals, prices, and memoised trade plans for one replay build."""

    def __init__(
        self,
        signals: pd.DataFrame,
        panel: pd.DataFrame,
        daily: pd.DataFrame,
        terminal_haircuts: Mapping[str, float],
        registration: Mapping[str, Any],
    ) -> None:
        self.registration = registration
        self.series: dict[str, PriceSeries] = price_series_from_daily(daily)
        self.haircuts = dict(terminal_haircuts)
        caps = panel.assign(as_of=panel["as_of"].map(_naive))
        cap_by_date = {
            d: dict(zip(g["ticker"].astype(str), g["market_cap"].astype(float), strict=True))
            for d, g in caps.groupby("as_of")
        }
        sig = signals.assign(as_of=signals["as_of"].map(_naive))
        self.screens: list[ScreenDate] = []
        for d, g in sorted(sig.groupby("as_of"), key=lambda item: item[0]):
            tickers = g["ticker"].astype(str)
            ey = (
                pd.to_numeric(g["earnings_yield"], errors="coerce")
                if "earnings_yield" in g
                else None
            )
            ey_pct: dict[str, float] = {}
            if ey is not None and ey.notna().any():
                pct = ey.rank(pct=True, method="average")
                ey_pct = {t: float(v) for t, v in zip(tickers, pct, strict=True) if not pd.isna(v)}
            self.screens.append(
                ScreenDate(
                    date=d,
                    signal=dict(zip(tickers, g["signal"].astype(str), strict=True)),
                    conviction=dict(
                        zip(tickers, g["conviction_score"].fillna(0.0).astype(float), strict=True)
                    ),
                    market_cap=cap_by_date.get(d, {}),
                    ey_pct=ey_pct,
                    plain_value=frozenset(hsr.plain_value_tickers(g))
                    if "earnings_yield" in g
                    else frozenset(),
                )
            )
        tier_rows: dict[str, list[tuple[np.datetime64, bool]]] = {}
        for screen in self.screens:
            stamp = np.datetime64(screen.date.to_datetime64(), "ns")
            for ticker, signal in screen.signal.items():
                tier_rows.setdefault(ticker, []).append((stamp, signal in BUY_TIER))
        self.tier_history = tier_rows
        calendar = np.unique(np.concatenate([s.dates for s in self.series.values()]))
        self.month_ends = (
            pd.Series(pd.DatetimeIndex(calendar))
            .groupby(pd.DatetimeIndex(calendar).to_period("M"))
            .max()
            .tolist()
        )
        self._indicators: dict[str, pd.DataFrame] = {}
        self._plans: dict[tuple[str, str], TickerPlans] = {}
        self.benchmarks: dict[tuple[pd.Timestamp, ...], tuple[np.ndarray, np.ndarray]] = {}
        self.plain_books: dict[tuple[tuple[pd.Timestamp, ...], float], PlainBook] = {}

    def plans(self, ticker: str, key: str) -> TickerPlans:
        memo = (ticker, key)
        if memo not in self._plans:
            series = self.series.get(ticker)
            if series is None:
                self._plans[memo] = TickerPlans()
            else:
                if ticker not in self._indicators:
                    self._indicators[ticker] = indicator_frame(series)
                self._plans[memo] = build_ticker_plans(
                    series,
                    self._indicators[ticker],
                    self.tier_history.get(ticker, []),
                    trade_plan_config(self.registration, key),
                )
        return self._plans[memo]

    def bar_at(self, ticker: str, day: pd.Timestamp) -> int | None:
        """Bar on or just before ``day``; None when the series has no fresh bar."""
        series = self.series.get(ticker)
        if series is None:
            return None
        i = series.index_on_or_before(np.datetime64(day.to_datetime64(), "ns"))
        if i < 0:
            return None
        age = (day - pd.Timestamp(series.dates[i])).days
        return i if age <= PRICE_STALE_DAYS else None

    def window_dates(self, window: Mapping[str, str]) -> list[pd.Timestamp]:
        """Rebalance dates in the window plus the next month-end for the last return."""
        first, last = pd.Timestamp(window["first_entry"]), pd.Timestamp(window["last_entry"])
        dates = [s.date for s in self.screens if first <= s.date <= last]
        if not dates:
            return []
        after = [d for d in self.month_ends if d > dates[-1]]
        return [*dates, after[0]] if after else dates


# --- Simulation ----------------------------------------------------------------------------


def select(screen: ScreenDate, config: RuleConfig) -> list[str]:
    tier = BUY_TIER if config.tier == "buy_tier" else frozenset({"strong_buy"})
    names = [t for t, s in screen.signal.items() if s in tier]
    names.sort(key=lambda t: (-screen.conviction.get(t, 0.0), t))
    return names if config.top_n is None else names[: config.top_n]


@dataclass
class _Streaks:
    outside: int = 0
    avoid: int = 0
    rerated: int = 0


def exit_reason(
    rule: Mapping[str, Any], streaks: _Streaks, screen: ScreenDate, ticker: str, chosen: bool
) -> str | None:
    """Advance one held name's streaks on a screen; the sell reason, or None to keep.

    ``tier``: sell after ``screens_outside`` screens outside the selection; a
    single ``avoid`` sells at once.

    ``thesis`` (the core sell trigger): leaving the selection is not a sell. Sell
    after ``avoid_confirm`` consecutive ``avoid`` screens, or, when
    ``rerate_below_pct`` is set, after ``rerate_confirm`` consecutive screens
    outside the selection with the earnings yield below that percentile of the
    screened names (re-rated: no longer cheap). A missing earnings yield leaves
    the re-rating streak where it was.
    """
    signal = screen.signal.get(ticker)
    if rule["kind"] == "tier":
        if signal == "avoid":
            return "avoid"
        streaks.outside = 0 if chosen else streaks.outside + 1
        return "left_selection" if streaks.outside >= int(rule["screens_outside"]) else None
    streaks.avoid = streaks.avoid + 1 if signal == "avoid" else 0
    if streaks.avoid >= int(rule["avoid_confirm"]):
        return "thesis_break"
    threshold = rule.get("rerate_below_pct")
    if threshold is None or chosen:
        streaks.rerated = 0
        return None
    pct = screen.ey_pct.get(ticker)
    if pct is not None:
        streaks.rerated = streaks.rerated + 1 if pct < float(threshold) else 0
    return "rerated" if streaks.rerated >= int(rule["rerate_confirm"]) else None


def holdings_by_month(
    data: SearchData, config: RuleConfig, dates: Sequence[pd.Timestamp]
) -> tuple[list[list[str]], dict[str, int]]:
    """Names held over each month (rebalance date k to k+1), and sells by reason.

    Every rule sells a name that leaves the screened universe (left the index,
    or no fresh price): no later screen could ever confirm a sell, so holding it
    would be open-ended.
    """
    rule = data.registration["exit_rules"][config.exit_rule]
    screens = {s.date: s for s in data.screens}
    held: dict[str, _Streaks] = {}
    exits: dict[str, int] = {}
    out: list[list[str]] = []
    for day in dates[:-1]:
        screen = screens[day]
        chosen = set(select(screen, config))
        for ticker in list(held):
            if screen.signal.get(ticker) is None or data.bar_at(ticker, day) is None:
                reason: str | None = "left_universe"
            else:
                reason = exit_reason(rule, held[ticker], screen, ticker, ticker in chosen)
            if reason:
                del held[ticker]
                exits[reason] = exits.get(reason, 0) + 1
        for ticker in sorted(chosen):
            if ticker not in held and data.bar_at(ticker, day) is not None:
                held[ticker] = _Streaks()
        out.append(sorted(held))
    return out, exits


def _month_return(
    data: SearchData, ticker: str, start: pd.Timestamp, end: pd.Timestamp
) -> tuple[float, int, bool]:
    """Total return start→end, the bar it ends on, and whether the name delisted."""
    series = data.series[ticker]
    b0 = data.bar_at(ticker, start)
    assert b0 is not None
    b1 = data.bar_at(ticker, end)
    p0 = float(series.close[b0])
    if b1 is not None:
        return float(series.close[b1]) / p0 - 1.0, b1, False
    last = series.index_on_or_before(np.datetime64(end.to_datetime64(), "ns"))
    if last == len(series.close) - 1:
        haircut = data.haircuts.get(ticker, 0.0)
        return float(series.close[last]) * (1.0 + haircut) / p0 - 1.0, last, True
    return float(series.close[last]) / p0 - 1.0, last, False


@dataclass
class PlainBook:
    returns: np.ndarray
    # Months with no plain value names; the equal-weight universe stands in.
    fallback_months: int = 0


@dataclass
class WindowRun:
    dates: list[pd.Timestamp]
    portfolio: np.ndarray
    cap_weighted: np.ndarray
    equal_weighted: np.ndarray
    plain_value: np.ndarray
    plain_value_fallback_months: int
    names_held: list[int]
    tactical_trades: list[dict[str, Any]]
    holding_months: int
    episode_months: list[int] = field(default_factory=list)
    open_at_end: int = 0
    exits: dict[str, int] = field(default_factory=dict)


def simulate(
    data: SearchData,
    config: RuleConfig,
    window: Mapping[str, str],
    *,
    cost_per_side: float,
) -> WindowRun:
    """Monthly book: equal weight per held name, each split core : tactical slice."""
    dates = data.window_dates(window)
    holdings, exits = holdings_by_month(data, config, dates)
    months = len(holdings)

    # Episodes: contiguous months held.
    episodes: list[tuple[str, int, int]] = []
    open_at: dict[str, int] = {}
    for k in range(months + 1):
        now = set(holdings[k]) if k < months else set()
        for ticker in list(open_at):
            if ticker not in now:
                episodes.append((ticker, open_at.pop(ticker), k))
        for ticker in now:
            open_at.setdefault(ticker, k)

    core_ret: dict[tuple[str, int], float] = {}
    slice_ret: dict[tuple[str, int], float] = {}
    slice_open: dict[tuple[str, int], bool] = {}
    core_pct: dict[tuple[str, int], float] = {}
    trades: list[dict[str, Any]] = []
    for ticker, k0, k1 in episodes:
        end_bar = None
        delisted = False
        bars = []
        for k in range(k0, k1):
            r, b1, gone = _month_return(data, ticker, dates[k], dates[k + 1])
            core_ret[(ticker, k)] = r
            bars.append(data.bar_at(ticker, dates[k]))
            end_bar = b1
            if gone:
                delisted = True
                k1 = k + 1
                break
        c = 1.0
        plans = None
        if config.tactical is not None:
            plans = data.plans(ticker, config.tactical)
            j = plans.latest_on_or_before(bars[0])
            if j >= 0 and plans.valid_to[j] >= bars[0]:
                c = plans.core_pct[j]
        for k in range(k0, k1):
            core_pct[(ticker, k)] = c
        if plans is None or c >= 1.0:
            continue
        eval_bars = [*bars, end_bar]
        result = simulate_slice(
            data.series[ticker],
            plans,
            start_bar=bars[0],
            end_bar=end_bar,
            eval_bars=eval_bars,
            cost_per_side=cost_per_side,
            terminal_haircut=data.haircuts.get(ticker, 0.0) if delisted else None,
        )
        for i, k in enumerate(range(k0, k1)):
            v0, v1 = result.values[eval_bars[i]], result.values[eval_bars[i + 1]]
            slice_ret[(ticker, k)] = v1 / v0 - 1.0 if v0 > 0 else 0.0
            slice_open[(ticker, k)] = result.in_position[eval_bars[i]]
        trades.extend({"kind": t.exit_kind, "gross_return": t.gross_return} for t in result.trades)

    portfolio = np.zeros(months)
    prev_core: dict[str, float] = {}
    prev_slice: dict[str, float] = {}
    for k in range(months):
        names = holdings[k]
        n = len(names)
        core_t = {t: core_pct[(t, k)] / n for t in names} if n else {}
        slice_t = {t: (1.0 - core_pct[(t, k)]) / n for t in names} if n else {}
        turnover = sum(
            abs(core_t.get(t, 0.0) - prev_core.get(t, 0.0)) for t in set(core_t) | set(prev_core)
        )
        turnover += sum(
            abs(slice_t[t] - prev_slice.get(t, 0.0))
            for t in names
            if slice_open.get((t, k)) and t in prev_slice
        )
        gross = sum(
            core_t[t] * core_ret[(t, k)] + slice_t[t] * slice_ret.get((t, k), core_ret[(t, k)])
            for t in names
        )
        portfolio[k] = gross - cost_per_side * turnover
        growth = 1.0 + gross
        prev_core = (
            {t: core_t[t] * (1.0 + core_ret[(t, k)]) / growth for t in names} if growth > 0 else {}
        )
        prev_slice = (
            {t: slice_t[t] * (1.0 + slice_ret.get((t, k), 0.0)) / growth for t in names}
            if growth > 0
            else {}
        )

    cap_w, eq_w = benchmark_returns(data, dates)
    plain = plain_value_book(data, dates, cost_per_side=cost_per_side)
    return WindowRun(
        dates=dates,
        portfolio=portfolio,
        cap_weighted=cap_w,
        equal_weighted=eq_w,
        plain_value=plain.returns,
        plain_value_fallback_months=plain.fallback_months,
        names_held=[len(h) for h in holdings],
        tactical_trades=trades,
        holding_months=sum(len(h) for h in holdings),
        episode_months=[k1 - k0 for _, k0, k1 in episodes],
        open_at_end=sum(1 for _, _, k1 in episodes if k1 == months),
        exits=exits,
    )


def benchmark_returns(
    data: SearchData, dates: Sequence[pd.Timestamp]
) -> tuple[np.ndarray, np.ndarray]:
    """Cap-weighted and equal-weighted monthly returns of the screened universe."""
    memo = tuple(dates)
    if memo in data.benchmarks:
        return data.benchmarks[memo]
    screens = {s.date: s for s in data.screens}
    cap_w = np.zeros(len(dates) - 1)
    eq_w = np.zeros(len(dates) - 1)
    for k, day in enumerate(dates[:-1]):
        caps = screens[day].market_cap
        rets, weights = [], []
        for ticker, cap in caps.items():
            if ticker not in data.series or data.bar_at(ticker, day) is None or not cap > 0:
                continue
            r, _, _ = _month_return(data, ticker, day, dates[k + 1])
            rets.append(r)
            weights.append(cap)
        if rets:
            w = np.asarray(weights) / float(np.sum(weights))
            cap_w[k] = float(np.dot(w, rets))
            eq_w[k] = float(np.mean(rets))
    data.benchmarks[memo] = (cap_w, eq_w)
    return cap_w, eq_w


def plain_value_book(
    data: SearchData, dates: Sequence[pd.Timestamp], *, cost_per_side: float
) -> PlainBook:
    """Equal-weight plain value sort, rebalanced monthly and costed like the rule books."""
    memo = (tuple(dates), cost_per_side)
    if memo in data.plain_books:
        return data.plain_books[memo]
    screens = {s.date: s for s in data.screens}
    _, eq_w = benchmark_returns(data, dates)
    out = np.zeros(len(dates) - 1)
    fallback = 0
    prev: dict[str, float] = {}
    for k, day in enumerate(dates[:-1]):
        names = sorted(
            t
            for t in screens[day].plain_value
            if t in data.series and data.bar_at(t, day) is not None
        )
        if not names:
            out[k] = eq_w[k]
            fallback += 1
            prev = {}
            continue
        rets = {t: _month_return(data, t, day, dates[k + 1])[0] for t in names}
        w = 1.0 / len(names)
        turnover = sum(abs(w - prev.get(t, 0.0)) for t in names)
        turnover += sum(v for t, v in prev.items() if t not in rets)
        gross = float(np.mean(list(rets.values())))
        out[k] = gross - cost_per_side * turnover
        growth = 1.0 + gross
        prev = {t: w * (1.0 + r) / growth for t, r in rets.items()} if growth > 0 else {}
    book = PlainBook(returns=out, fallback_months=fallback)
    data.plain_books[memo] = book
    return book


# --- Statistics ----------------------------------------------------------------------------


def long_run_sd(x: np.ndarray, lag: int) -> float:
    """Newey–West (Bartlett) long-run standard deviation."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 2:
        return float("nan")
    d = x - x.mean()
    var = float(np.dot(d, d)) / n
    for lag_i in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - lag_i / (lag + 1.0)
        var += 2.0 * weight * float(np.dot(d[lag_i:], d[:-lag_i])) / n
    return math.sqrt(var) if var > 0 else float("nan")


def horizon_probability(
    log_excess: np.ndarray, horizon_months: int, *, lag: int, z: float
) -> dict[str, float | None]:
    """P(cumulative log excess over ``horizon_months`` > 0) and its lower bound.

    Normal approximation with the long-run variance: P = Φ(μ√H / σ_LR). The
    lower bound replaces μ with μ − z·σ_LR/√T (uncertainty in the mean).
    """
    x = np.asarray(log_excess, dtype=float)
    n = len(x)
    sd = long_run_sd(x, lag)
    if n < 2 or not sd == sd:
        return {"p": None, "p_lower": None, "empirical_hit_rate": None}
    mu = float(x.mean())
    root_h = math.sqrt(horizon_months)
    p = NORMAL.cdf(mu * root_h / sd)
    p_lower = NORMAL.cdf((mu - z * sd / math.sqrt(n)) * root_h / sd)
    hits = None
    if n >= horizon_months:
        sums = np.convolve(x, np.ones(horizon_months), mode="valid")
        hits = float(np.mean(sums > 0))
    return {"p": round(p, 4), "p_lower": round(p_lower, 4), "empirical_hit_rate": hits}


def mean_ci(x: np.ndarray, *, lag: int, z: float) -> dict[str, float | None]:
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return {"mean": None, "low": None, "high": None}
    sd = long_run_sd(x, lag)
    mu = float(x.mean())
    half = z * sd / math.sqrt(len(x)) if sd == sd else float("nan")
    return {"mean": round(mu, 6), "low": round(mu - half, 6), "high": round(mu + half, 6)}


def excess_vs_plain_value(run: WindowRun) -> np.ndarray:
    """Monthly log excess over the plain value book: the search objective's series."""
    return np.log1p(run.portfolio) - np.log1p(run.plain_value)


def window_metrics(
    run: WindowRun, *, horizons: Sequence[int], lag: int, z: float
) -> dict[str, Any]:
    if len(run.portfolio) == 0:
        return {
            "months": 0,
            "horizons": {
                str(h): horizon_probability(np.array([]), h, lag=lag, z=z) for h in horizons
            },
        }
    log_ex = excess_vs_plain_value(run)
    log_ex_cap = np.log1p(run.portfolio) - np.log1p(run.cap_weighted)
    log_ex_eq = np.log1p(run.portfolio) - np.log1p(run.equal_weighted)
    plain_vs_cap = np.log1p(run.plain_value) - np.log1p(run.cap_weighted)
    sd = float(np.std(log_ex, ddof=1)) if len(log_ex) > 1 else float("nan")
    trades = run.tactical_trades
    years = run.holding_months / 12.0

    def annualised(x: np.ndarray) -> float:
        return round(float(np.expm1(12 * np.mean(x))), 4)

    return {
        "months": len(run.portfolio),
        "first": run.dates[0].date().isoformat() if run.dates else None,
        "last": run.dates[-1].date().isoformat() if run.dates else None,
        "annualised_return": annualised(np.log1p(run.portfolio)),
        "annualised_excess_plain_value": annualised(log_ex),
        "information_ratio": round(float(np.mean(log_ex) / sd * math.sqrt(12)), 4)
        if sd > 0
        else None,
        "horizons": {str(h): horizon_probability(log_ex, h, lag=lag, z=z) for h in horizons},
        "plain_value_fallback_months": run.plain_value_fallback_months,
        "market_context": {
            "annualised_excess_cap": annualised(log_ex_cap),
            "annualised_excess_equal": annualised(log_ex_eq),
            "plain_value_annualised_excess_cap": annualised(plain_vs_cap),
            "horizons_vs_cap_weighted": {
                str(h): horizon_probability(log_ex_cap, h, lag=lag, z=z) for h in horizons
            },
        },
        "median_names_held": float(np.median(run.names_held)) if run.names_held else 0.0,
        "holding": _holding_summary(run),
        "tactical": {
            "round_trips": len(trades),
            "round_trips_per_holding_year": round(len(trades) / years, 3) if years else None,
            "win_rate": round(float(np.mean([t["gross_return"] > 0 for t in trades])), 4)
            if trades
            else None,
            "exits": {
                kind: sum(1 for t in trades if t["kind"] == kind)
                for kind in ("target", "stop", "core_exit", "delisted")
            },
        },
    }


def monthly_series(run: WindowRun) -> dict[str, Any]:
    """Book-level monthly returns (no per-name rows), kept for analysis after deletion."""

    def rounded(x: np.ndarray) -> list[float]:
        return [round(float(v), 6) for v in x]

    return {
        "month_starts": [d.date().isoformat() for d in run.dates[:-1]],
        "portfolio": rounded(run.portfolio),
        "plain_value": rounded(run.plain_value),
        "cap_weighted": rounded(run.cap_weighted),
        "equal_weighted": rounded(run.equal_weighted),
        "names_held": [int(n) for n in run.names_held],
    }


def _holding_summary(run: WindowRun) -> dict[str, Any]:
    """Holding periods in months; episodes still open at the window end are censored."""
    lengths = np.asarray(run.episode_months, dtype=float)
    if not len(lengths):
        return {"episodes": 0}
    return {
        "episodes": len(lengths),
        "median_months": float(np.median(lengths)),
        "p90_months": float(np.percentile(lengths, 90)),
        "max_months": int(lengths.max()),
        "open_at_window_end": run.open_at_end,
        "exits": dict(sorted(run.exits.items())),
    }


def pbo_cscv(matrix: np.ndarray, *, blocks: int = 16) -> float | None:
    """Probability of backtest overfitting by combinatorially symmetric cross-validation.

    ``matrix`` is T months × K configs of excess returns. For every split of the
    blocks into equal in-sample and out-of-sample halves, the in-sample Sharpe
    winner's out-of-sample rank is logit-transformed; PBO is the share at or
    below the median.
    """
    t, k = matrix.shape
    if k < 2 or t < blocks * 2:
        return None
    edges = np.linspace(0, t, blocks + 1).astype(int)
    sums = np.stack([matrix[a:b].sum(axis=0) for a, b in zip(edges[:-1], edges[1:], strict=True)])
    sq = np.stack(
        [(matrix[a:b] ** 2).sum(axis=0) for a, b in zip(edges[:-1], edges[1:], strict=True)]
    )
    counts = np.diff(edges).astype(float)
    below = 0
    total = 0
    for chosen in itertools.combinations(range(blocks), blocks // 2):
        mask = np.zeros(blocks, dtype=bool)
        mask[list(chosen)] = True

        def sharpe(m: np.ndarray) -> np.ndarray:
            n = counts[m].sum()
            mean = sums[m].sum(axis=0) / n
            var = sq[m].sum(axis=0) / n - mean**2
            return mean / np.sqrt(np.where(var > 0, var, np.nan))

        is_sr, oos_sr = sharpe(mask), sharpe(~mask)
        if np.all(np.isnan(is_sr)):
            continue
        best = int(np.nanargmax(is_sr))
        if np.isnan(oos_sr[best]):
            continue
        rank = float(np.sum(oos_sr <= oos_sr[best]))  # 1..K
        omega = rank / (k + 1.0)
        below += int(math.log(omega / (1.0 - omega)) <= 0)
        total += 1
    return round(below / total, 4) if total else None


def deflated_sharpe(returns: np.ndarray, trial_sharpes: Sequence[float]) -> float | None:
    """Bailey & López de Prado deflated Sharpe ratio (per-period Sharpe units)."""
    x = np.asarray(returns, dtype=float)
    n = len(x)
    trials = [s for s in trial_sharpes if s == s]
    if n < 3 or len(trials) < 2:
        return None
    sd = float(np.std(x, ddof=1))
    if sd <= 0:
        return None
    sr = float(np.mean(x)) / sd
    skew = float(np.mean(((x - x.mean()) / sd) ** 3))
    kurt = float(np.mean(((x - x.mean()) / sd) ** 4))
    var_trials = float(np.var(trials, ddof=1))
    k = len(trials)
    gamma = 0.5772156649
    sr0 = math.sqrt(var_trials) * (
        (1 - gamma) * NORMAL.inv_cdf(1 - 1 / k) + gamma * NORMAL.inv_cdf(1 - 1 / (k * math.e))
    )
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if denom <= 0:
        return None
    return round(NORMAL.cdf((sr - sr0) * math.sqrt(n - 1) / math.sqrt(denom)), 4)


# --- Search, reveal, store --------------------------------------------------------------------


def _objective(metrics: Mapping[str, Any], registration: Mapping[str, Any]) -> float:
    obj = registration["objective"]
    value = metrics["horizons"][str(obj["horizon_months"])][obj["metric"]]
    return float(value) if value is not None else float("-inf")


def choose(
    scores: Mapping[str, float], configs: Sequence[RuleConfig], registration: Mapping[str, Any]
) -> tuple[RuleConfig, float]:
    """Highest plateau score (median over self and one-step neighbours).

    Ties go to core only, then to the fewest departures from the frozen rules.
    """
    frozen = frozen_config(registration)
    by_id = {c.id: c for c in configs}

    def plateau(c: RuleConfig) -> float:
        vals = [scores[c.id]] + [scores[n.id] for n in neighbours(c, registration) if n.id in by_id]
        return float(np.median(vals))

    def departures(c: RuleConfig) -> int:
        return sum(
            a != b for a, b in zip(c.params().values(), frozen.params().values(), strict=True)
        )

    ranked = sorted(
        configs,
        key=lambda c: (-round(plateau(c), 4), c.tactical is not None, departures(c), c.id),
    )
    best = ranked[0]
    return best, round(plateau(best), 4)


def _settings(registration: Mapping[str, Any]) -> dict[str, Any]:
    obj = registration["objective"]
    return {
        "horizons": [int(h) for h in obj["report_horizons_months"]],
        "lag": int(obj["long_run_lag_months"]),
        "z_search": float(obj["z_search"]),
        "z_holdout": float(obj["z_holdout"]),
        "cost": float(registration["costs"]["base_per_side"]),
        "stress_cost": float(registration["costs"]["stress_per_side"]),
    }


def run_search(data: SearchData, registration: Mapping[str, Any]) -> dict[str, Any]:
    """Score every registered rule set on the development window and pick one."""
    s = _settings(registration)
    window = registration["windows"]["development"]
    configs = grid_configs(registration)
    runs: dict[str, WindowRun] = {}
    rows: list[dict[str, Any]] = []
    for config in configs:
        run = simulate(data, config, window, cost_per_side=s["cost"])
        runs[config.id] = run
        metrics = window_metrics(run, horizons=s["horizons"], lag=s["lag"], z=s["z_search"])
        rows.append({"id": config.id, "params": config.params(), "development": metrics})
    for row in rows:
        config = RuleConfig(**row["params"])
        if config.tactical is None:
            continue
        diff = runs[config.id].portfolio - runs[config.core_only().id].portfolio
        row["development"]["tactical_increment_monthly"] = mean_ci(
            diff, lag=s["lag"], z=s["z_search"]
        )
    scores = {row["id"]: _objective(row["development"], registration) for row in rows}
    chosen, plateau_score = choose(scores, configs, registration)
    excess = np.column_stack([excess_vs_plain_value(runs[c.id]) for c in configs])
    trial_sharpes = [
        float(np.mean(col) / np.std(col, ddof=1)) if np.std(col, ddof=1) > 0 else float("nan")
        for col in excess.T
    ]
    chosen_col = excess[:, [c.id for c in configs].index(chosen.id)]
    frozen = frozen_config(registration)
    return {
        "run_at": datetime.now(UTC).isoformat(),
        "window": dict(window),
        "configs_tested": len(configs),
        "configs": rows,
        "selection": {
            "config_id": chosen.id,
            "params": chosen.params(),
            "objective": scores[chosen.id],
            "plateau_objective": plateau_score,
            "frozen_config_id": frozen_config(registration).id,
            "frozen_objective": scores.get(frozen_config(registration).id),
        },
        "overfitting": {
            "pbo_cscv": pbo_cscv(excess, blocks=int(registration["overfitting"]["cscv_blocks"])),
            "deflated_sharpe_chosen": deflated_sharpe(chosen_col, trial_sharpes),
        },
        "series": {
            "frozen": monthly_series(runs[frozen.id]) if frozen.id in runs else None,
            "chosen": monthly_series(runs[chosen.id]),
        },
    }


def _verdict_p_lower(horizons: Mapping[str, Any], registration: Mapping[str, Any]) -> str:
    h = horizons[str(registration["objective"]["horizon_months"])]
    if h["p_lower"] is None:
        return "too_thin"
    if h["p_lower"] >= float(registration["pass_bars"]["holdout_p_lower_min"]):
        return "pass"
    if h["p"] < 0.5:
        return "fail"
    return "inconclusive"


def _verdict_increment(ci: Mapping[str, Any]) -> str:
    if ci["low"] is None:
        return "too_thin"
    if ci["low"] > 0:
        return "adds"
    if ci["high"] < 0:
        return "costs"
    return "inconclusive"


def run_reveal(
    data: SearchData, registration: Mapping[str, Any], selection: Mapping[str, Any]
) -> dict[str, Any]:
    """Holdout for the frozen and chosen rules, with and without the tactical slice."""
    s = _settings(registration)
    window = registration["windows"]["holdout"]
    chosen = RuleConfig(**selection["params"])
    frozen = frozen_config(registration)
    out: dict[str, Any] = {"run_at": datetime.now(UTC).isoformat(), "window": dict(window)}
    portfolios: dict[tuple[str, str], np.ndarray] = {}
    for label, config in (("frozen", frozen), ("chosen", chosen)):
        entry: dict[str, Any] = {"config_id": config.id}
        for cost_label, cost in (("base", s["cost"]), ("stress", s["stress_cost"])):
            run = simulate(data, config, window, cost_per_side=cost)
            portfolios[(label, cost_label)] = run.portfolio
            metrics = window_metrics(run, horizons=s["horizons"], lag=s["lag"], z=s["z_holdout"])
            block: dict[str, Any] = {"metrics": metrics, "series": monthly_series(run)}
            if config.tactical is not None:
                core = simulate(data, config.core_only(), window, cost_per_side=cost)
                block["core_only_metrics"] = window_metrics(
                    core, horizons=s["horizons"], lag=s["lag"], z=s["z_holdout"]
                )
                block["core_only_portfolio"] = monthly_series(core)["portfolio"]
                ci = mean_ci(run.portfolio - core.portfolio, lag=s["lag"], z=s["z_holdout"])
                block["tactical_increment_monthly"] = ci
                block["tactical_verdict"] = _verdict_increment(ci)
            block["verdict_vs_plain_value"] = _verdict_p_lower(metrics["horizons"], registration)
            block["market_context_vs_cap_weighted"] = _verdict_p_lower(
                metrics["market_context"]["horizons_vs_cap_weighted"], registration
            )
            entry[cost_label] = block
        out[label] = entry
    # Did the search add anything over the live rules? Same months, so a paired difference.
    out["chosen_minus_frozen"] = {}
    for cost_label in ("base", "stress"):
        diff = portfolios[("chosen", cost_label)] - portfolios[("frozen", cost_label)]
        ci = mean_ci(diff, lag=s["lag"], z=s["z_holdout"])
        out["chosen_minus_frozen"][cost_label] = {
            "monthly": ci,
            "verdict": "same_rules" if chosen.id == frozen.id else _verdict_increment(ci),
        }
    return out


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def selection_committed(store_path: Path = DEFAULT_STORE_PATH) -> bool:
    store = _read_json(store_path) or {}
    return bool((store.get("search") or {}).get("selection"))


def _check_fingerprints(registration: Mapping[str, Any]) -> None:
    if registration.get("screen_code_fingerprint") != hsr.screen_code_fingerprint():
        raise ValueError("Screen code changed since registration; run `register` first.")
    if registration.get("rule_code_fingerprint") != rule_code_fingerprint():
        raise ValueError("Rule code changed since registration; run `register` first.")


def load_search_data(
    build_dir: Path, registration: Mapping[str, Any], *, terminal: str = "terminal_baseline.csv"
) -> SearchData:
    build_dir = Path(build_dir)
    if hsr._inside_repo(build_dir):
        raise ValueError(
            f"{build_dir} is inside the repository. Licensed data must stay outside this public repo."
        )
    panel = pd.read_csv(build_dir / "panel.csv.gz")
    signals = hsr.cached_replay_signals(
        panel,
        market_id=registration["market_id"],
        cache_path=build_dir / hsr.SIGNAL_CACHE_NAME,
    )
    daily = pd.read_csv(build_dir / "daily.csv.gz")
    term = pd.read_csv(build_dir / terminal)
    haircuts = dict(zip(term["ticker"].astype(str), term["haircut"].astype(float), strict=True))
    return SearchData(signals, panel, daily, haircuts, registration)


def search(
    build_dir: Path,
    *,
    registration_path: Path = DEFAULT_REGISTRATION_PATH,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    registration = load_registration(registration_path)
    _check_fingerprints(registration)
    store = _read_json(store_path) or {}
    if store.get("holdout_reveals"):
        raise ValueError("Holdout already revealed; a new search needs a new registration_id.")
    data = load_search_data(build_dir, registration)
    result = run_search(data, registration)
    payload = {
        **store,
        "registration_id": registration.get("registration_id"),
        "search": result,
        "holdout_reveals": [],
    }
    _write_json(store_path, payload)
    return payload


def reveal(
    build_dir: Path,
    *,
    registration_path: Path = DEFAULT_REGISTRATION_PATH,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    registration = load_registration(registration_path)
    _check_fingerprints(registration)
    store = _read_json(store_path) or {}
    selection = (store.get("search") or {}).get("selection")
    if not selection:
        raise ValueError("No committed search selection; run `search` and commit the store first.")
    reveals = list(store.get("holdout_reveals") or [])
    if reveals:
        print("Holdout already revealed; this reveal is recorded as exploratory.")
    data = load_search_data(build_dir, registration)
    result = run_reveal(data, registration, selection)
    reveals.append({"at": result["run_at"], "evidence": not reveals})
    payload = {**store, "holdout": result, "holdout_reveals": reveals}
    _write_json(store_path, payload)
    return payload


def register(
    registration_path: Path = DEFAULT_REGISTRATION_PATH, store_path: Path = DEFAULT_STORE_PATH
) -> dict[str, str]:
    store = _read_json(store_path) or {}
    if store.get("holdout_reveals"):
        raise ValueError("Holdout already revealed; open a new registration_id instead.")
    registration = load_registration(registration_path)
    registration["screen_code_fingerprint"] = hsr.screen_code_fingerprint()
    registration["rule_code_fingerprint"] = rule_code_fingerprint()
    registration["registered_at"] = datetime.now(UTC).isoformat()
    _write_json(registration_path, registration)
    return {
        "screen_code_fingerprint": registration["screen_code_fingerprint"],
        "rule_code_fingerprint": registration["rule_code_fingerprint"],
    }


def status_block(
    registration_path: Path = DEFAULT_REGISTRATION_PATH, store_path: Path = DEFAULT_STORE_PATH
) -> dict[str, Any] | None:
    """Daily ops-monitor view (embedded in ``historical_screen_replay.json``)."""
    if not Path(registration_path).exists():
        return None
    registration = load_registration(registration_path)
    store = _read_json(store_path) or {}
    search_block = store.get("search") or {}
    return {
        "registration_id": registration.get("registration_id"),
        "matches_screen_code": registration.get("screen_code_fingerprint")
        == hsr.screen_code_fingerprint(),
        "matches_rule_code": registration.get("rule_code_fingerprint") == rule_code_fingerprint(),
        "selection": (search_block.get("selection") or {}).get("config_id"),
        "holdout_reveals": list(store.get("holdout_reveals") or []),
    }


def findings_from_block(block: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not block:
        return []
    findings: list[dict[str, Any]] = []
    reveals = block.get("holdout_reveals") or []
    current = block.get("matches_screen_code") and block.get("matches_rule_code")
    if current is False:
        if reveals:
            findings.append(
                {
                    "severity": "warn",
                    "category": "backtest",
                    "title": STALE_VERDICT_TITLE,
                    "summary": (
                        "Screen or trade-plan code changed after the rule-search holdout was "
                        "revealed. Its verdicts describe the registered rules only. See "
                        "docs/ops/historical-rule-search.md."
                    ),
                    "auto_fixable": False,
                }
            )
        else:
            findings.append(
                {
                    "severity": "info",
                    "category": "backtest",
                    "title": STALE_REGISTRATION_TITLE,
                    "summary": (
                        "Screen or trade-plan code changed since the rule search was registered. "
                        "Run `ftse-rule-search register` before the licensed run; the holdout "
                        "is still sealed."
                    ),
                    "auto_fixable": False,
                }
            )
    if len(reveals) > 1:
        findings.append(
            {
                "severity": "warn",
                "category": "backtest",
                "title": HOLDOUT_REUSED_TITLE,
                "summary": (
                    f"The rule-search holdout was revealed {len(reveals)} times. Only the first "
                    "reveal is evidence."
                ),
                "auto_fixable": False,
            }
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ftse-rule-search", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Fingerprints, selection, and reveals")
    sub.add_parser("register", help="Re-freeze fingerprints while the holdout is sealed")
    for name, text in (
        ("search", "Score the registered grid on the development window and pick a rule set"),
        ("reveal", "Evaluate frozen and chosen rules on the holdout (once)"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--build", type=Path, required=True, help="build-panel output directory")
    args = parser.parse_args(argv)
    if args.command == "status":
        print(json.dumps(status_block(), indent=2))
    elif args.command == "register":
        print(json.dumps(register(), indent=2))
    elif args.command == "search":
        payload = search(args.build)
        print(
            json.dumps(
                {
                    "selection": payload["search"]["selection"],
                    "overfitting": payload["search"]["overfitting"],
                },
                indent=2,
            )
        )
    else:
        payload = reveal(args.build)
        print(json.dumps(payload["holdout"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
