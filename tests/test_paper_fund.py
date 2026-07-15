"""Tests for cash-backed paper funds and parallel strategy books."""

from value_investor.paper_fund import (
    PaperFund,
    PaperFundConfig,
    compare_funds,
    create_parallel_book,
    resolve_order_shares,
    run_automated_rebalance,
    run_technical_pass,
)
from value_investor.simulator import SimulatorConfig, run_simulation
from value_investor.backtest import BENCHMARK_TICKER, RunSnapshot


def test_resolve_order_shares_modes_respect_cash():
    # £100 cash, 3% costs, £10 price → max gross ≈ 97.087, max shares ≈ 9.7087
    shares = resolve_order_shares(
        sizing_mode="cash",
        amount=100,
        price=10,
        nav=100,
        cash=100,
        trade_cost_pct=0.03,
        side="buy",
    )
    assert 9.7 < shares < 9.71

    pct_shares = resolve_order_shares(
        sizing_mode="pct_nav",
        amount=0.5,
        price=10,
        nav=200,
        cash=200,
        trade_cost_pct=0.0,
        side="buy",
    )
    assert abs(pct_shares - 10.0) < 1e-9

    capped = resolve_order_shares(
        sizing_mode="shares",
        amount=100,
        price=10,
        nav=50,
        cash=50,
        trade_cost_pct=0.0,
        side="buy",
    )
    assert abs(capped - 5.0) < 1e-9


def test_monthly_deposits_and_mtm_performance():
    fund = PaperFund.create(
        PaperFundConfig(
            name="Test",
            mode="manual",
            initial_cash=1000,
            monthly_deposit=100,
            trade_cost_pct=0.0,
            created_at="2026-01-15T00:00:00+00:00",
        )
    )
    deposited = fund.apply_deposits_to("2026-03-10")
    assert deposited == 200
    assert fund.cash == 1200
    assert fund.contributed_capital == 1200
    assert fund.deposits_applied == 2

    trade = fund.buy(
        ticker="AAA.L",
        price=10,
        sizing_mode="cash",
        amount=600,
        name="Alpha",
        acted_at="2026-03-10T12:00:00+00:00",
    )
    assert trade.shares == 60
    assert fund.cash == 600

    perf = fund.performance({"AAA.L": 12})
    assert perf["portfolio_value"] == 1320  # 600 cash + 720 equity
    assert perf["contributed_capital"] == 1200
    assert abs(perf["total_return"] - (120 / 1200)) < 1e-6


def test_parallel_book_three_modes():
    book = create_parallel_book(initial_cash=5000, monthly_deposit=250)
    assert len(book.funds) == 3
    modes = {f.config.mode for f in book.funds}
    assert modes == {"manual", "technical", "automated"}
    for fund in book.funds:
        assert fund.cash == 5000
        assert fund.config.monthly_deposit == 250

    round_trip = type(book).from_dict(book.to_dict())
    assert len(round_trip.funds) == 3
    assert round_trip.active_fund_id == book.active_fund_id


def test_automated_rebalance_constrained_by_cash_and_max_positions():
    fund = PaperFund.create(
        PaperFundConfig(
            name="Auto",
            mode="automated",
            initial_cash=1000,
            trade_cost_pct=0.0,
            max_positions=2,
        )
    )
    candidates = [
        {"ticker": "AAA.L", "name": "A", "signal": "strong_buy", "conviction_score": 0.9, "price": 10},
        {"ticker": "BBB.L", "name": "B", "signal": "buy", "conviction_score": 0.8, "price": 20},
        {"ticker": "CCC.L", "name": "C", "signal": "buy", "conviction_score": 0.7, "price": 5},
        {"ticker": "DDD.L", "name": "D", "signal": "hold", "conviction_score": 0.99, "price": 1},
    ]
    trades = run_automated_rebalance(fund, candidates)
    assert trades
    assert len(fund.holdings) == 2
    assert set(fund.holdings) == {"AAA.L", "BBB.L"}
    assert fund.cash < 1000
    # Equal weight ~£500 each at zero costs
    assert abs(fund.holdings["AAA.L"].shares * 10 - 500) < 1.0
    assert abs(fund.holdings["BBB.L"].shares * 20 - 500) < 1.0


def test_technical_pass_stop_and_entry():
    fund = PaperFund.create(
        PaperFundConfig(
            name="Tech",
            mode="technical",
            initial_cash=1000,
            trade_cost_pct=0.0,
            max_positions=3,
        )
    )
    fund.buy(
        ticker="OLD.L",
        price=100,
        sizing_mode="shares",
        amount=2,
        stop_loss=90,
        take_profit=120,
        note="seed",
    )
    candidates = [
        {
            "ticker": "OLD.L",
            "signal": "buy",
            "conviction_score": 0.5,
            "price": 85,
            "timing_signal": "neutral",
            "trade_plan": {"tactical_stop_loss": 90, "tactical_take_profit": 120},
        },
        {
            "ticker": "NEW.L",
            "name": "NewCo",
            "signal": "strong_buy",
            "conviction_score": 0.9,
            "price": 50,
            "timing_signal": "accumulate",
            "trade_plan": {
                "core_limit": 48,
                "tactical_stop_loss": 40,
                "tactical_take_profit": 60,
            },
        },
    ]
    trades = run_technical_pass(fund, candidates, buy_pct_nav=0.2)
    sides = {(t.ticker, t.side) for t in trades}
    assert ("OLD.L", "sell") in sides
    assert ("NEW.L", "buy") in sides
    assert "OLD.L" not in fund.holdings
    assert "NEW.L" in fund.holdings
    assert fund.holdings["NEW.L"].stop_loss == 40


def test_preview_automated_plan_explains_next_moves():
    fund = PaperFund.create(
        PaperFundConfig(
            name="Auto",
            mode="automated",
            initial_cash=1000,
            trade_cost_pct=0.0,
            max_positions=2,
        )
    )
    fund.buy(ticker="OLD.L", price=10, sizing_mode="cash", amount=400, name="Old")
    candidates = [
        {"ticker": "AAA.L", "name": "A", "signal": "strong_buy", "conviction_score": 0.95, "price": 20},
        {"ticker": "BBB.L", "name": "B", "signal": "buy", "conviction_score": 0.9, "price": 25},
        {
            "ticker": "WAIT.L",
            "name": "Waiter",
            "signal": "strong_buy",
            "conviction_score": 0.99,
            "price": 15,
            "timing_signal": "wait",
        },
        {"ticker": "OLD.L", "name": "Old", "signal": "hold", "conviction_score": 0.1, "price": 10},
    ]
    from value_investor.paper_fund import preview_automated_plan

    plan = preview_automated_plan(fund, candidates)
    assert "equal-weight" in plan["summary"].lower() or "sleeve" in plan["summary"].lower()
    assert any(x["ticker"] == "OLD.L" for x in plan["anticipated_exits"])
    assert {t["ticker"] for t in plan["targets"]} == {"AAA.L", "BBB.L"}
    assert any(w["ticker"] == "WAIT.L" for w in plan["waitlisted"])
    assert len(plan["rules"]) >= 4
    # Dry-run must not mutate fund
    assert "OLD.L" in fund.holdings
    assert fund.cash == 600


def test_compare_funds_ranks_by_return():
    a = PaperFund.create(PaperFundConfig(name="A", mode="manual", initial_cash=1000, trade_cost_pct=0))
    b = PaperFund.create(PaperFundConfig(name="B", mode="manual", initial_cash=1000, trade_cost_pct=0))
    a.buy(ticker="AAA.L", price=10, sizing_mode="cash", amount=500)
    b.buy(ticker="AAA.L", price=10, sizing_mode="cash", amount=500)
    rows = compare_funds([a, b], {"AAA.L": 12})
    assert rows[0]["portfolio_value"] == rows[1]["portfolio_value"]


def test_simulator_monthly_deposit_increases_contributed_capital():
    snapshots = [
        RunSnapshot(
            run_at="2026-01-05T07:00:00+00:00",
            prices={"AAA.L": 100.0, BENCHMARK_TICKER: 8000.0},
            signals=[
                {"ticker": "AAA.L", "signal": "strong_buy", "conviction_score": 0.9},
            ],
        ),
        RunSnapshot(
            run_at="2026-02-05T07:00:00+00:00",
            prices={"AAA.L": 100.0, BENCHMARK_TICKER: 8000.0},
            signals=[
                {"ticker": "AAA.L", "signal": "strong_buy", "conviction_score": 0.9},
            ],
        ),
        RunSnapshot(
            run_at="2026-03-05T07:00:00+00:00",
            prices={"AAA.L": 100.0, BENCHMARK_TICKER: 8000.0},
            signals=[
                {"ticker": "AAA.L", "signal": "strong_buy", "conviction_score": 0.9},
            ],
        ),
    ]
    summary = run_simulation(
        snapshots,
        SimulatorConfig(initial_capital=1000, trade_cost_pct=0.0, monthly_deposit=100, max_positions=1),
    )
    assert summary.equity_curve[-1]["contributed_capital"] == 1200
    # Flat prices → final ≈ contributed after fees=0
    assert abs(summary.final_value - 1200) < 0.01
    assert abs(summary.total_return) < 0.001
