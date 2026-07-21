"""Tests for decision-review learning knobs and proposals."""

from pathlib import Path

from value_investor.decision_review import (
    BookMetrics,
    LearningKnobs,
    compute_book_metrics,
    propose_knob_updates,
    run_decision_review,
)
from value_investor.paper_automation import AutomationConfig
from value_investor.paper_fund import (
    PaperFund,
    PaperFundConfig,
    select_automated_targets,
)


def test_select_automated_targets_respects_conviction_and_sector_cap():
    candidates = [
        {
            "ticker": "AAA.L",
            "signal": "strong_buy",
            "conviction_score": 0.9,
            "price": 10,
            "sector": "Banks",
        },
        {
            "ticker": "BBB.L",
            "signal": "buy",
            "conviction_score": 0.85,
            "price": 10,
            "sector": "Banks",
        },
        {
            "ticker": "CCC.L",
            "signal": "buy",
            "conviction_score": 0.8,
            "price": 10,
            "sector": "Mining",
        },
        {
            "ticker": "DDD.L",
            "signal": "buy",
            "conviction_score": 0.2,
            "price": 10,
            "sector": "Retail",
        },
    ]
    # floor drops DDD; sector_cap 0.3 with max 5 → 1 per sector → AAA + CCC
    picked = select_automated_targets(
        candidates,
        max_positions=5,
        min_conviction=0.5,
        sector_cap=0.3,
    )
    tickers = [row["ticker"] for row in picked]
    assert tickers == ["AAA.L", "CCC.L"]


def test_propose_knobs_raises_conviction_on_high_cost_drag():
    metrics = BookMetrics(
        portfolio_value=950,
        contributed_capital=1000,
        total_return=-0.05,
        total_costs=60,
        cost_drag=0.06,
        trade_count=6,
        buy_count=4,
        sell_count=2,
        positions=5,
        cash_fraction=0.1,
        equity_marks=5,
        max_sector_weight=0.25,
        dominant_sector="Banks",
        benchmark_return=0.0,
        excess_after_costs=-0.05,
    )
    knobs = LearningKnobs(
        max_positions=5,
        skip_timing_wait=True,
        min_conviction=0.0,
        sector_cap=0.3,
    )
    proposed, changes, reasons = propose_knob_updates(metrics, knobs)
    assert changes.get("min_conviction") == 0.05
    assert proposed.min_conviction == 0.05
    assert proposed.max_positions == 4  # weak excess also shrinks book
    assert any("min_conviction" in r for r in reasons)


def test_propose_knobs_tightens_sector_cap_when_concentrated():
    metrics = BookMetrics(
        portfolio_value=1000,
        contributed_capital=1000,
        total_return=0.01,
        total_costs=10,
        cost_drag=0.01,
        trade_count=3,
        buy_count=3,
        sell_count=0,
        positions=3,
        cash_fraction=0.05,
        equity_marks=4,
        max_sector_weight=0.55,
        dominant_sector="Banks",
        benchmark_return=0.0,
        excess_after_costs=0.01,
    )
    knobs = LearningKnobs(sector_cap=0.30)
    proposed, changes, _reasons = propose_knob_updates(metrics, knobs)
    assert changes["sector_cap"] == 0.25
    assert proposed.sector_cap == 0.25


def test_run_decision_review_report_only_until_history_thick(tmp_path: Path):
    fund = PaperFund.create(
        PaperFundConfig(
            name="Auto",
            mode="automated",
            initial_cash=1000,
            trade_cost_pct=0.03,
            max_positions=5,
        )
    )
    fund.buy(
        ticker="AAA.L",
        price=10,
        sizing_mode="cash",
        amount=400,
        sector="Banks",
        name="A",
    )
    fund.record_mark({"AAA.L": 11}, note="mark1")

    out = tmp_path / "paper"
    out.mkdir()
    (out / "config.json").write_text(
        __import__("json").dumps(AutomationConfig(max_positions=5).to_dict()),
        encoding="utf-8",
    )
    (out / "automated_fund.json").write_text(
        __import__("json").dumps(fund.to_dict()),
        encoding="utf-8",
    )

    result = run_decision_review(
        output_dir=out,
        apply=True,
        fetch_benchmark=False,
        benchmark_return=0.0,
    )
    assert result.enough_history is False
    assert result.applied is False
    assert (out / "decision_review.json").exists()
    # Config unchanged
    cfg = __import__("json").loads((out / "config.json").read_text(encoding="utf-8"))
    assert cfg["max_positions"] == 5


def test_run_decision_review_applies_when_forced(tmp_path: Path):
    fund = PaperFund.create(
        PaperFundConfig(
            name="Auto",
            mode="automated",
            initial_cash=1000,
            trade_cost_pct=0.03,
            max_positions=5,
        )
    )
    # Create costly churn
    for i, ticker in enumerate(["AAA.L", "BBB.L", "CCC.L", "DDD.L"]):
        fund.buy(
            ticker=ticker,
            price=10,
            sizing_mode="cash",
            amount=200,
            sector="Banks",
            name=ticker,
            acted_at=f"2026-01-0{i+1}T12:00:00+00:00",
        )
    for ticker in ["AAA.L", "BBB.L"]:
        fund.sell(
            ticker=ticker,
            price=9,
            sizing_mode="shares",
            amount=fund.holdings[ticker].shares,
            acted_at="2026-02-01T12:00:00+00:00",
        )
    for i in range(4):
        fund.record_mark(
            {t: 9.5 for t in fund.holdings},
            note=f"m{i}",
            acted_at=f"2026-03-0{i+1}T12:00:00+00:00",
        )

    out = tmp_path / "paper"
    out.mkdir()
    config = AutomationConfig(
        max_positions=5,
        skip_timing_wait=True,
        min_conviction=0.0,
        sector_cap=0.5,
    )
    (out / "config.json").write_text(
        __import__("json").dumps(config.to_dict()),
        encoding="utf-8",
    )
    (out / "automated_fund.json").write_text(
        __import__("json").dumps(fund.to_dict()),
        encoding="utf-8",
    )

    metrics = compute_book_metrics(fund, benchmark_return=0.05, fetch_benchmark=False)
    assert metrics.cost_drag > 0
    assert metrics.equity_marks >= 4

    result = run_decision_review(
        output_dir=out,
        apply=True,
        fetch_benchmark=False,
        benchmark_return=0.05,
    )
    assert result.enough_history is True
    cfg = __import__("json").loads((out / "config.json").read_text(encoding="utf-8"))
    assert result.proposed_changes or result.applied is False
    if result.proposed_changes:
        assert result.applied is True
        assert (
            cfg["min_conviction"] > 0
            or cfg["max_positions"] < 5
            or cfg["sector_cap"] < 0.5
        )
    assert (out / "decision_review_history.json").exists()
