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
    comparison_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = self.screen.to_dict()
        payload["research_overlay"] = self.overlay.to_dict()
        if self.comparison_note:
            payload["comparison_note"] = self.comparison_note
        return payload

    def has_results(self) -> bool:
        return self.screen.has_results() or self.overlay.has_results()


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
    return SimulationComparison(
        screen=simulation_summary_from_dict(data),
        overlay=simulation_summary_from_dict(overlay_data) if overlay_data else simulation_summary_from_dict(data),
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
    """Run screen-only and research-overlay simulations on the same snapshots."""
    base = config or SimulatorConfig()
    screen = run_simulation(snapshots, base)
    overlay = run_simulation(
        snapshots,
        replace(base, use_adjusted_signal=True),
    )
    has_overlay_data = _snapshots_have_research_overlay(snapshots)
    return SimulationComparison(
        screen=screen,
        overlay=overlay,
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


def _rebalance(
    *,
    snapshot: RunSnapshot,
    cash: float,
    holdings: dict[str, float],
    config: SimulatorConfig,
) -> tuple[float, dict[str, float], list[Trade]]:
    prices = snapshot.prices
    run_at = snapshot.run_at
    trades: list[Trade] = []
    targets = _select_targets(snapshot, config)
    target_set = set(targets)

    # Sell positions no longer in target universe
    for ticker in list(holdings.keys()):
        if ticker in target_set:
            continue
        price = prices.get(ticker)
        if price is None or price <= 0:
            del holdings[ticker]
            continue
        shares = holdings.pop(ticker)
        proceeds, trade = _execute_sell(
            run_at=run_at,
            ticker=ticker,
            shares=shares,
            price=price,
            trade_cost_pct=config.trade_cost_pct,
        )
        cash += proceeds
        trades.append(trade)

    if not targets:
        return cash, holdings, trades

    total_value = _portfolio_value(cash, holdings, prices)
    target_each = total_value / len(targets)

    # Trim overweight positions
    for ticker in targets:
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
        trades.append(trade)

    # Buy underweight positions
    for ticker in targets:
        price = prices.get(ticker)
        if price is None or price <= 0:
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
        holdings[ticker] = current_shares + shares_bought
        trades.append(trade)

    return cash, holdings, trades


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

        cash, holdings, trades = _rebalance(
            snapshot=snapshot,
            cash=cash,
            holdings=holdings,
            config=config,
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
    if comparison.comparison_note:
        lines.extend(["", comparison.comparison_note])
    return "\n".join(lines)
