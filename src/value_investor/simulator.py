"""Portfolio simulator for screening strategy effectiveness."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    holdings: dict[str, float] = {}
    all_trades: list[Trade] = []
    equity_curve: list[dict[str, Any]] = []

    first = snapshots[0]
    bench_start = first.prices.get(BENCHMARK_TICKER)

    for snapshot in snapshots:
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
                "positions": len(holdings),
            }
        )

    last = snapshots[-1]
    final_value = _portfolio_value(cash, holdings, last.prices)
    bench_end = last.prices.get(BENCHMARK_TICKER)

    total_return = (final_value - config.initial_capital) / config.initial_capital
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


def run_simulation_from_dir(output_dir, config: SimulatorConfig | None = None) -> SimulationSummary:
    from pathlib import Path

    path = Path(output_dir)
    snapshots = load_run_snapshots(path)
    return run_simulation(snapshots, config=config)


def format_simulation_text(summary: SimulationSummary) -> str:
    if not summary.has_results() and summary.note:
        return summary.note

    cost_pct = summary.trade_cost_pct * 100
    lines = [
        f"Portfolio simulation (£{summary.initial_capital:,.0f} start, {cost_pct:.0f}% per trade):",
        f"  Final value: £{summary.final_value:,.2f} ({summary.total_return:+.1%})",
        f"  FTSE 100 buy-and-hold: {summary.benchmark_return:+.1%}",
        f"  Excess return: {summary.excess_return:+.1%}",
        f"  Trades: {summary.trade_count}, total costs: £{summary.total_costs:,.2f}",
        f"  Periods simulated: {summary.periods}",
    ]
    if summary.holdings:
        holding_bits = ", ".join(f"{ticker} ({shares:.2f} sh)" for ticker, shares in summary.holdings.items())
        lines.append(f"  Current holdings: {holding_bits}")
    return "\n".join(lines)
