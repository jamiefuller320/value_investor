"""Portfolio simulator for screening strategy effectiveness."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from value_investor.backtest import BENCHMARK_TICKER, RunSnapshot, load_run_snapshots

DEFAULT_INITIAL_CAPITAL = 1000.0
DEFAULT_TRADE_COST_PCT = 0.03
DEFAULT_MAX_POSITIONS = 5
BUY_SIGNALS = frozenset({"strong_buy", "buy"})


@dataclass
class SimulatorConfig:
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    trade_cost_pct: float = DEFAULT_TRADE_COST_PCT
    max_positions: int = DEFAULT_MAX_POSITIONS
    buy_signals: frozenset[str] = BUY_SIGNALS
    skip_timing_wait: bool = True
    use_adjusted_signal: bool = False
    require_research_accumulate: bool = False
    monthly_deposit: float = 0.0
    # When True, honour core_limit entry gates and tactical stop/target exits (L3).
    use_trade_plan_levels: bool = False
    # With use_trade_plan_levels: trail stop up from refreshed plans, never below entry stop (L44).
    trailing_stop: bool = False


@dataclass
class Trade:
    run_at: str
    ticker: str
    side: str
    shares: float
    price: float
    gross: float
    cost: float
    net: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_at": self.run_at,
            "ticker": self.ticker,
            "side": self.side,
            "shares": round(self.shares, 6),
            "price": round(self.price, 4),
            "gross": round(self.gross, 2),
            "cost": round(self.cost, 2),
            "net": round(self.net, 2),
        }


@dataclass
class SimulationSummary:
    initial_capital: float
    final_value: float
    total_return: float
    benchmark_return: float
    excess_return: float
    trade_count: int
    total_costs: float
    periods: int
    holdings: dict[str, float]
    trade_cost_pct: float = DEFAULT_TRADE_COST_PCT
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_capital": round(self.initial_capital, 2),
            "final_value": round(self.final_value, 2),
            "total_return": round(self.total_return, 4),
            "benchmark_return": round(self.benchmark_return, 4),
            "excess_return": round(self.excess_return, 4),
            "trade_count": self.trade_count,
            "total_costs": round(self.total_costs, 2),
            "periods": self.periods,
            "trade_cost_pct": self.trade_cost_pct,
            "holdings": {k: round(v, 6) for k, v in self.holdings.items()},
            "trades": [t.to_dict() for t in self.trades[-20:]],
            "equity_curve": self.equity_curve,
            "note": self.note,
        }

    def has_results(self) -> bool:
        return self.periods >= 2 and bool(self.equity_curve)


@dataclass
class SimulationComparison:
    screen: SimulationSummary
    overlay: SimulationSummary
    static_levels: SimulationSummary | None = None
    trailing_levels: SimulationSummary | None = None
    comparison_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = self.screen.to_dict()
        payload["research_overlay"] = self.overlay.to_dict()
        if self.static_levels is not None:
            payload["static_levels"] = self.static_levels.to_dict()
        if self.trailing_levels is not None:
            payload["trailing_levels"] = self.trailing_levels.to_dict()
        if self.comparison_note:
            payload["comparison_note"] = self.comparison_note
        return payload

    def has_results(self) -> bool:
        tracks = [self.screen, self.overlay, self.static_levels, self.trailing_levels]
        return any(t is not None and t.has_results() for t in tracks)


def simulation_summary_from_dict(data: dict[str, Any]) -> SimulationSummary:
    trades = [Trade(**t) for t in data.get("trades", [])]
    return SimulationSummary(
        initial_capital=float(data["initial_capital"]),
        final_value=float(data["final_value"]),
        total_return=float(data["total_return"]),
        benchmark_return=float(data["benchmark_return"]),
        excess_return=float(data["excess_return"]),
        trade_count=int(data["trade_count"]),
        total_costs=float(data["total_costs"]),
        periods=int(data["periods"]),
        holdings=dict(data.get("holdings") or {}),
        trade_cost_pct=float(data.get("trade_cost_pct", DEFAULT_TRADE_COST_PCT)),
        trades=trades,
        equity_curve=list(data.get("equity_curve") or []),
        note=str(data.get("note", "")),
    )


def simulation_comparison_from_dict(data: dict[str, Any]) -> SimulationComparison:
    overlay_data = data.get("research_overlay")
    static_data = data.get("static_levels")
    trailing_data = data.get("trailing_levels")
    return SimulationComparison(
        screen=simulation_summary_from_dict(data),
        overlay=(
            simulation_summary_from_dict(overlay_data)
            if overlay_data
            else simulation_summary_from_dict(data)
        ),
        static_levels=(
            simulation_summary_from_dict(static_data) if isinstance(static_data, dict) else None
        ),
        trailing_levels=(
            simulation_summary_from_dict(trailing_data)
            if isinstance(trailing_data, dict)
            else None
        ),
        comparison_note=str(data.get("comparison_note", "")),
    )


def _snapshots_have_research_overlay(snapshots: list[RunSnapshot]) -> bool:
    for snapshot in snapshots:
        for row in snapshot.signals:
            verdict = row.get("research_verdict")
            if verdict is not None and str(verdict).strip():
                return True
            adjusted = row.get("adjusted_signal")
            signal = row.get("signal")
            if (
                adjusted is not None
                and signal is not None
                and str(adjusted).strip()
                and str(adjusted) != str(signal)
            ):
                return True
    return False


def _comparison_note(
    screen: SimulationSummary,
    overlay: SimulationSummary,
    *,
    has_overlay_data: bool,
) -> str:
    if not screen.has_results():
        return screen.note or overlay.note
    if not has_overlay_data:
        return "No research verdicts in archived runs; overlay track matches screen-only."
    delta = overlay.total_return - screen.total_return
    if abs(delta) < 0.0001:
        return "Research overlay produced identical returns to screen-only over this window."
    direction = "outperformed" if delta > 0 else "underperformed"
    return f"Research overlay {direction} screen-only by {delta:+.1%} total return."


def run_simulation_comparison(
    snapshots: list[RunSnapshot],
    config: SimulatorConfig | None = None,
) -> SimulationComparison:
    """Run screen, research-overlay, and technical level tracks on the same snapshots."""
    base = config or SimulatorConfig()
    # Force level flags off on the baseline tracks so comparison stays clean.
    screen = run_simulation(
        snapshots,
        replace(base, use_trade_plan_levels=False, trailing_stop=False),
    )
    overlay = run_simulation(
        snapshots,
        replace(
            base,
            use_adjusted_signal=True,
            use_trade_plan_levels=False,
            trailing_stop=False,
        ),
    )
    static_levels = run_simulation(
        snapshots,
        replace(base, use_trade_plan_levels=True, trailing_stop=False),
    )
    trailing_levels = run_simulation(
        snapshots,
        replace(base, use_trade_plan_levels=True, trailing_stop=True),
    )
    has_overlay_data = _snapshots_have_research_overlay(snapshots)
    return SimulationComparison(
        screen=screen,
        overlay=overlay,
        static_levels=static_levels,
        trailing_levels=trailing_levels,
        comparison_note=_comparison_note(screen, overlay, has_overlay_data=has_overlay_data),
    )


def _select_targets(snapshot: RunSnapshot, config: SimulatorConfig) -> list[str]:
    ranked: list[tuple[str, float]] = []
    for row in snapshot.signals:
        signal = str(row.get("signal", ""))
        if config.use_adjusted_signal:
            adjusted = row.get("adjusted_signal")
            if adjusted is not None and str(adjusted).strip():
                signal = str(adjusted)
        if signal not in config.buy_signals:
            continue
        if config.require_research_accumulate:
            verdict = row.get("research_verdict")
            if verdict is None or str(verdict).strip().lower() != "accumulate":
                continue
        timing = row.get("timing_signal")
        if config.skip_timing_wait and timing == "wait":
            continue
        conviction = float(row.get("conviction_score") or 0)
        ranked.append((str(row["ticker"]), conviction))

    ranked.sort(key=lambda item: item[1], reverse=True)
    return [ticker for ticker, _ in ranked[: config.max_positions]]


def _portfolio_value(
    cash: float,
    holdings: dict[str, float],
    prices: dict[str, float],
) -> float:
    equity = sum(
        shares * prices[ticker]
        for ticker, shares in holdings.items()
        if ticker in prices and prices[ticker] > 0
    )
    return cash + equity


def _execute_sell(
    *,
    run_at: str,
    ticker: str,
    shares: float,
    price: float,
    trade_cost_pct: float,
) -> tuple[float, Trade]:
    gross = shares * price
    cost = gross * trade_cost_pct
    net = gross - cost
    trade = Trade(
        run_at=run_at,
        ticker=ticker,
        side="sell",
        shares=shares,
        price=price,
        gross=gross,
        cost=cost,
        net=net,
    )
    return net, trade


def _execute_buy(
    *,
    run_at: str,
    ticker: str,
    budget: float,
    price: float,
    trade_cost_pct: float,
) -> tuple[float, float, Trade | None]:
    if budget <= 0 or price <= 0:
        return 0.0, 0.0, None
    # Total cash out includes 3% fee on gross notional
    gross = budget / (1 + trade_cost_pct)
    cost = gross * trade_cost_pct
    shares = gross / price
    trade = Trade(
        run_at=run_at,
        ticker=ticker,
        side="buy",
        shares=shares,
        price=price,
        gross=gross,
        cost=cost,
        net=-(gross + cost),
    )
    return shares, gross + cost, trade


def _signal_rows_by_ticker(snapshot: RunSnapshot) -> dict[str, dict[str, Any]]:
    return {str(row.get("ticker")): row for row in snapshot.signals if row.get("ticker")}


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _effective_stop(
    *,
    period_stop: float | None,
    entry_stop: float | None,
    trailing: bool,
) -> float | None:
    """Static = period stop; trailing = max(entry floor, period) so stops only rise."""
    if not trailing:
        return period_stop
    if entry_stop is None:
        return period_stop
    if period_stop is None:
        return entry_stop
    return max(entry_stop, period_stop)


def _rebalance(
    *,
    snapshot: RunSnapshot,
    cash: float,
    holdings: dict[str, float],
    config: SimulatorConfig,
    entry_stops: dict[str, float] | None = None,
) -> tuple[float, dict[str, float], list[Trade], dict[str, float]]:
    prices = snapshot.prices
    run_at = snapshot.run_at
    trades: list[Trade] = []
    targets = _select_targets(snapshot, config)
    target_set = set(targets)
    by_ticker = _signal_rows_by_ticker(snapshot)
    exited_for_levels: set[str] = set()
    stops = dict(entry_stops or {})

    def _clear_stop(ticker: str) -> None:
        stops.pop(ticker, None)

    # Sell positions no longer in target universe
    for ticker in list(holdings.keys()):
        if ticker in target_set:
            continue
        price = prices.get(ticker)
        if price is None or price <= 0:
            del holdings[ticker]
            _clear_stop(ticker)
            continue
        shares = holdings.pop(ticker)
        _clear_stop(ticker)
        proceeds, trade = _execute_sell(
            run_at=run_at,
            ticker=ticker,
            shares=shares,
            price=price,
            trade_cost_pct=config.trade_cost_pct,
        )
        cash += proceeds
        trades.append(trade)

    # Optional trade-plan stop / take-profit exits (whole position; L3 / L44).
    if config.use_trade_plan_levels:
        for ticker in list(holdings.keys()):
            price = prices.get(ticker)
            if price is None or price <= 0:
                continue
            row = by_ticker.get(ticker) or {}
            period_stop = _optional_float(row.get("tactical_stop_loss"))
            target = _optional_float(row.get("tactical_take_profit"))
            stop = _effective_stop(
                period_stop=period_stop,
                entry_stop=stops.get(ticker),
                trailing=bool(config.trailing_stop),
            )
            hit_stop = stop is not None and price <= stop
            hit_target = target is not None and price >= target
            if not (hit_stop or hit_target):
                continue
            shares = holdings.pop(ticker)
            _clear_stop(ticker)
            proceeds, trade = _execute_sell(
                run_at=run_at,
                ticker=ticker,
                shares=shares,
                price=price,
                trade_cost_pct=config.trade_cost_pct,
            )
            cash += proceeds
            trades.append(trade)
            exited_for_levels.add(ticker)

    if not targets:
        return cash, holdings, trades, stops

    total_value = _portfolio_value(cash, holdings, prices)
    target_each = total_value / len(targets)

    # Trim overweight positions
    for ticker in targets:
        if ticker in exited_for_levels:
            continue
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        current_shares = holdings.get(ticker, 0.0)
        current_value = current_shares * price
        if current_value <= target_each * 1.02:
            continue
        excess_value = current_value - target_each
        shares_to_sell = excess_value / price
        if shares_to_sell <= 0:
            continue
        shares_to_sell = min(shares_to_sell, current_shares)
        proceeds, trade = _execute_sell(
            run_at=run_at,
            ticker=ticker,
            shares=shares_to_sell,
            price=price,
            trade_cost_pct=config.trade_cost_pct,
        )
        cash += proceeds
        holdings[ticker] = current_shares - shares_to_sell
        if holdings[ticker] <= 1e-9:
            del holdings[ticker]
            _clear_stop(ticker)
        trades.append(trade)

    # Buy underweight positions
    for ticker in targets:
        if ticker in exited_for_levels:
            continue
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        row = by_ticker.get(ticker) or {}
        if config.use_trade_plan_levels:
            core_order = str(row.get("core_order") or "market")
            core_limit = _optional_float(row.get("core_limit"))
            if core_order == "limit" and core_limit is not None and price > core_limit:
                # Limit not reached this period — leave cash unallocated for this sleeve.
                continue
        current_shares = holdings.get(ticker, 0.0)
        current_value = current_shares * price
        shortfall = target_each - current_value
        if shortfall <= 0.01:
            continue
        budget = min(shortfall, cash)
        shares_bought, spent, trade = _execute_buy(
            run_at=run_at,
            ticker=ticker,
            budget=budget,
            price=price,
            trade_cost_pct=config.trade_cost_pct,
        )
        if trade is None:
            continue
        cash -= spent
        was_flat = current_shares <= 1e-9
        holdings[ticker] = current_shares + shares_bought
        # Sticky entry-stop floor: set only on first open (trailing track uses this).
        if was_flat and ticker not in stops:
            period_stop = _optional_float(row.get("tactical_stop_loss"))
            if period_stop is not None:
                stops[ticker] = period_stop
        trades.append(trade)

    return cash, holdings, trades, stops


def run_simulation(
    snapshots: list[RunSnapshot],
    config: SimulatorConfig | None = None,
) -> SimulationSummary:
    """
    Simulate a £1,000 pot rebalanced on each archived screening run.

    Applies config.trade_cost_pct (default 3%) on every buy and sell.
    """
    config = config or SimulatorConfig()
    if len(snapshots) < 2:
        return SimulationSummary(
            initial_capital=config.initial_capital,
            final_value=config.initial_capital,
            total_return=0.0,
            benchmark_return=0.0,
            excess_return=0.0,
            trade_count=0,
            total_costs=0.0,
            periods=len(snapshots),
            holdings={},
            note="Need at least 2 archived runs to simulate portfolio performance.",
        )

    cash = config.initial_capital
    contributed = config.initial_capital
    holdings: dict[str, float] = {}
    entry_stops: dict[str, float] = {}
    all_trades: list[Trade] = []
    equity_curve: list[dict[str, Any]] = []
    deposits_applied = 0

    first = snapshots[0]
    bench_start = first.prices.get(BENCHMARK_TICKER)

    def _month_index(iso: str) -> int:
        text = iso.replace("Z", "+00:00")
        # Accept full ISO timestamps or YYYY-MM-DD.
        stamp = text[:10]
        year = int(stamp[0:4])
        month = int(stamp[5:7])
        return year * 12 + month

    start_month = _month_index(first.run_at)

    for snapshot in snapshots:
        if config.monthly_deposit > 0:
            expected = max(0, _month_index(snapshot.run_at) - start_month)
            missing = expected - deposits_applied
            if missing > 0:
                injected = missing * config.monthly_deposit
                cash += injected
                contributed += injected
                deposits_applied += missing

        cash, holdings, trades, entry_stops = _rebalance(
            snapshot=snapshot,
            cash=cash,
            holdings=holdings,
            config=config,
            entry_stops=entry_stops,
        )
        all_trades.extend(trades)
        value = _portfolio_value(cash, holdings, snapshot.prices)
        equity_curve.append(
            {
                "run_at": snapshot.run_at,
                "portfolio_value": round(value, 2),
                "cash": round(cash, 2),
                "contributed_capital": round(contributed, 2),
                "positions": len(holdings),
            }
        )

    last = snapshots[-1]
    final_value = _portfolio_value(cash, holdings, last.prices)
    bench_end = last.prices.get(BENCHMARK_TICKER)

    # Return vs capital contributed (initial + deposits), not initial alone.
    capital_base = contributed if contributed > 0 else config.initial_capital
    total_return = (final_value - capital_base) / capital_base
    benchmark_return = 0.0
    if bench_start and bench_end and bench_start > 0:
        benchmark_return = (bench_end - bench_start) / bench_start

    total_costs = sum(t.cost for t in all_trades)

    return SimulationSummary(
        initial_capital=config.initial_capital,
        final_value=final_value,
        total_return=total_return,
        benchmark_return=benchmark_return,
        excess_return=total_return - benchmark_return,
        trade_count=len(all_trades),
        total_costs=total_costs,
        periods=len(snapshots),
        holdings=holdings,
        trade_cost_pct=config.trade_cost_pct,
        trades=all_trades,
        equity_curve=equity_curve,
    )


def run_simulation_from_dir(output_dir, config: SimulatorConfig | None = None) -> SimulationComparison:
    from pathlib import Path

    path = Path(output_dir)
    snapshots = load_run_snapshots(path)
    return run_simulation_comparison(snapshots, config=config)


def _format_single_simulation_text(summary: SimulationSummary, *, heading: str | None = None) -> list[str]:
    if not summary.has_results() and summary.note:
        return [summary.note]

    cost_pct = summary.trade_cost_pct * 100
    lines: list[str] = []
    if heading:
        lines.append(f"{heading}:")
    lines.extend([
        f"  Final value: £{summary.final_value:,.2f} ({summary.total_return:+.1%})",
        f"  FTSE 100 buy-and-hold: {summary.benchmark_return:+.1%}",
        f"  Excess return: {summary.excess_return:+.1%}",
        f"  Trades: {summary.trade_count}, total costs: £{summary.total_costs:,.2f}",
    ])
    if summary.holdings:
        holding_bits = ", ".join(
            f"{ticker} ({shares:.2f} sh)" for ticker, shares in summary.holdings.items()
        )
        lines.append(f"  Current holdings: {holding_bits}")
    if not heading:
        lines.insert(0, f"Portfolio simulation (£{summary.initial_capital:,.0f} start, {cost_pct:.0f}% per trade):")
    return lines


def format_simulation_text(summary: SimulationSummary) -> str:
    return "\n".join(_format_single_simulation_text(summary))


def format_simulation_comparison_text(comparison: SimulationComparison) -> str:
    if not comparison.screen.has_results() and comparison.screen.note:
        return comparison.screen.note

    cost_pct = comparison.screen.trade_cost_pct * 100
    lines = [
        f"Portfolio simulation comparison (£{comparison.screen.initial_capital:,.0f} start, {cost_pct:.0f}% per trade):",
        f"Periods simulated: {comparison.screen.periods}",
        "",
    ]
    lines.extend(_format_single_simulation_text(comparison.screen, heading="Screen only"))
    lines.append("")
    lines.extend(
        _format_single_simulation_text(
            comparison.overlay,
            heading="With research overlay (adjusted_signal)",
        )
    )
    if comparison.static_levels is not None:
        lines.append("")
        lines.extend(
            _format_single_simulation_text(
                comparison.static_levels,
                heading="Technical levels (static period stops)",
            )
        )
    if comparison.trailing_levels is not None:
        lines.append("")
        lines.extend(
            _format_single_simulation_text(
                comparison.trailing_levels,
                heading="Technical levels (trailing stop, entry floor)",
            )
        )
    if comparison.comparison_note:
        lines.extend(["", comparison.comparison_note])
    return "\n".join(lines)
