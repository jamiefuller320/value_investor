"""Tests for decision-review learning knobs and proposals."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from value_investor.decision_review import (
    MIN_EPOCH_DAYS,
    BookMetrics,
    LearningKnobs,
    compute_book_metrics,
    detect_saturated_knobs,
    ensure_knob_epoch,
    estimate_counterfactual_preview,
    max_positions_bounds_for,
    metrics_for_review,
    propose_knob_updates,
    run_decision_review,
    start_knob_epoch,
)
from value_investor.paper_automation import (
    GRADUATED_ALLOCATION_MIN_POSITIONS,
    AutomationConfig,
    default_graduated_allocation_config,
)
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


def test_select_automated_targets_ai_judgment_gates():
    candidates = [
        {
            "ticker": "GOOD.L",
            "signal": "buy",
            "adjusted_signal": "strong_buy",
            "research_verdict": "accumulate",
            "conviction_score": 0.9,
            "price": 10,
        },
        {
            "ticker": "NOMEMO.L",
            "signal": "strong_buy",
            "adjusted_signal": "strong_buy",
            "research_verdict": None,
            "conviction_score": 0.95,
            "price": 10,
        },
        {
            "ticker": "AVOID.L",
            "signal": "strong_buy",
            "adjusted_signal": "avoid",
            "research_verdict": "pass",
            "conviction_score": 0.99,
            "price": 10,
        },
    ]
    rules = select_automated_targets(candidates, max_positions=5)
    assert [r["ticker"] for r in rules] == ["AVOID.L", "NOMEMO.L", "GOOD.L"]

    ai = select_automated_targets(
        candidates,
        max_positions=5,
        use_adjusted_signal=True,
        require_research_accumulate=True,
    )
    assert [r["ticker"] for r in ai] == ["GOOD.L"]

    rendered = select_automated_targets(
        [
            {
                "ticker": "RENDER.L",
                "signal": "strong_buy",
                "adjusted_signal": "strong_buy",
                "research_verdict": "Verdict: accumulate\nRisk: medium\nConfidence: 0.70",
                "conviction_score": 0.88,
                "price": 10,
            }
        ],
        max_positions=5,
        use_adjusted_signal=True,
        require_research_accumulate=True,
    )
    assert [r["ticker"] for r in rendered] == ["RENDER.L"]


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
            acted_at=f"2026-01-0{i + 1}T12:00:00+00:00",
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
            acted_at=f"2026-03-0{i + 1}T12:00:00+00:00",
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
        assert cfg["min_conviction"] > 0 or cfg["max_positions"] < 5 or cfg["sector_cap"] < 0.5
    assert (out / "decision_review_history.json").exists()


def test_knob_epoch_metrics_since_last_apply(tmp_path: Path):
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
        acted_at="2026-01-01T12:00:00+00:00",
    )
    fund.record_mark({"AAA.L": 11}, note="m1", acted_at="2026-01-02T12:00:00+00:00")
    fund.record_mark({"AAA.L": 11}, note="m2", acted_at="2026-01-03T12:00:00+00:00")

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

    epoch = start_knob_epoch(
        out,
        fund,
        LearningKnobs(max_positions=4),
        reviewed_at="2026-01-03T12:00:00+00:00",
    )
    assert epoch.baseline_nav > 0

    fund.buy(
        ticker="BBB.L",
        price=10,
        sizing_mode="cash",
        amount=200,
        sector="Mining",
        name="B",
        acted_at="2026-01-04T12:00:00+00:00",
    )
    fund.record_mark(
        {"AAA.L": 11, "BBB.L": 10},
        note="m3",
        acted_at="2026-01-05T12:00:00+00:00",
    )
    fund.record_mark(
        {"AAA.L": 11, "BBB.L": 10.5},
        note="m4",
        acted_at="2026-01-06T12:00:00+00:00",
    )
    (out / "automated_fund.json").write_text(
        __import__("json").dumps(fund.to_dict()),
        encoding="utf-8",
    )

    metrics = compute_book_metrics(
        fund,
        benchmark_return=0.01,
        fetch_benchmark=False,
        knob_epoch=ensure_knob_epoch(out),
    )
    assert metrics.epoch is not None
    assert metrics.epoch["trade_count"] == 1
    assert metrics.epoch["equity_marks"] >= 2
    assert metrics.epoch["total_return"] != metrics.total_return

    review_slice = metrics_for_review(metrics)
    assert review_slice.trade_count == 1
    assert review_slice.equity_marks >= 2


def test_counterfactual_preview_blocks_excess_buys():
    fund = PaperFund.create(
        PaperFundConfig(
            name="Auto",
            mode="automated",
            initial_cash=1000,
            trade_cost_pct=0.03,
            max_positions=10,
        )
    )
    for i, ticker in enumerate(["AAA.L", "BBB.L", "CCC.L", "DDD.L", "EEE.L", "FFF.L"]):
        fund.buy(
            ticker=ticker,
            price=10,
            sizing_mode="cash",
            amount=150,
            sector=f"Sector{i % 2}",
            name=ticker,
            acted_at=f"2026-01-0{i + 1}T12:00:00+00:00",
        )
    preview = estimate_counterfactual_preview(
        fund,
        knobs=LearningKnobs(max_positions=3, sector_cap=0.5),
    )
    assert preview["blocked_buys"] >= 3
    assert preview["estimated_cost_savings_gbp"] > 0
    assert preview["cost_drag_delta"] > 0


def test_run_decision_review_starts_epoch_on_apply(tmp_path: Path):
    fund = PaperFund.create(
        PaperFundConfig(
            name="Auto",
            mode="automated",
            initial_cash=1000,
            trade_cost_pct=0.03,
            max_positions=5,
        )
    )
    for i, ticker in enumerate(["AAA.L", "BBB.L", "CCC.L", "DDD.L"]):
        fund.buy(
            ticker=ticker,
            price=10,
            sizing_mode="cash",
            amount=200,
            sector="Banks",
            name=ticker,
            acted_at=f"2026-01-0{i + 1}T12:00:00+00:00",
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
            acted_at=f"2026-03-0{i + 1}T12:00:00+00:00",
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

    result = run_decision_review(
        output_dir=out,
        apply=True,
        fetch_benchmark=False,
        benchmark_return=0.05,
    )
    if result.applied:
        assert (out / "knob_epoch.json").exists()
        epoch = __import__("json").loads((out / "knob_epoch.json").read_text(encoding="utf-8"))
        assert epoch["knobs"]["max_positions"] <= 5


def test_benchmark_ticker_for_shard_meta(tmp_path: Path):
    from value_investor.decision_review import benchmark_ticker_for_dir, compare_learning_tracks

    shard_root = tmp_path / "markets" / "sp500"
    shard_root.mkdir(parents=True)
    (shard_root / "shard_meta.json").write_text(
        '{"benchmark_ticker":"^GSPC"}',
        encoding="utf-8",
    )
    assert benchmark_ticker_for_dir(shard_root) == "^GSPC"

    (shard_root / "config.json").write_text("{}", encoding="utf-8")
    (shard_root / "automated_fund.json").write_text(
        __import__("json").dumps(
            __import__("value_investor.paper_fund", fromlist=["PaperFund"])
            .PaperFund.create(
                __import__(
                    "value_investor.paper_fund", fromlist=["PaperFundConfig"]
                ).PaperFundConfig(
                    name="rules",
                    mode="automated",
                    initial_cash=1000,
                    trade_cost_pct=0.03,
                    max_positions=5,
                )
            )
            .to_dict()
        ),
        encoding="utf-8",
    )
    ai_dir = shard_root / "ai_judgment"
    ai_dir.mkdir()
    (ai_dir / "config.json").write_text(
        '{"track_id":"ai_judgment","is_primary_learning_track":true}', encoding="utf-8"
    )
    (ai_dir / "automated_fund.json").write_text(
        (shard_root / "automated_fund.json").read_text(), encoding="utf-8"
    )

    with (
        patch("value_investor.churn_health.write_churn_health", return_value={}),
        patch("value_investor.rebalance_log.write_buffered_hold_counterfactual", return_value=None),
    ):
        summary = compare_learning_tracks(base_dir=shard_root, force=True, fetch_benchmark=False)
    assert summary["benchmark_ticker"] == "^GSPC"
    assert "^GSPC" in summary["success_criterion"]


def test_cohort_lab_is_frozen_against_apply(tmp_path: Path):
    fund = PaperFund.create(
        PaperFundConfig(
            name="Cohort",
            mode="automated",
            initial_cash=1000,
            trade_cost_pct=0.00275,
            max_positions=120,
        )
    )
    out = tmp_path / "buy_tier_level"
    out.mkdir()
    config = AutomationConfig(
        max_positions=120,
        min_conviction=0.0,
        sector_cap=1.0,
        is_cohort_lab=True,
        track_id="buy_tier_level",
    )
    (out / "config.json").write_text(__import__("json").dumps(config.to_dict()), encoding="utf-8")
    (out / "automated_fund.json").write_text(
        __import__("json").dumps(fund.to_dict()), encoding="utf-8"
    )
    result = run_decision_review(
        output_dir=out,
        apply=True,
        force=True,
        fetch_benchmark=False,
        benchmark_return=0.0,
    )
    assert result.applied is False
    assert "Frozen" in result.note
    cfg = __import__("json").loads((out / "config.json").read_text(encoding="utf-8"))
    assert cfg["min_conviction"] == 0.0
    assert cfg["max_positions"] == 120


def _write_churny_track(
    out: Path,
    *,
    config: AutomationConfig,
    trade_day: str = "2026-01-0",
) -> PaperFund:
    fund = PaperFund.create(
        PaperFundConfig(
            name="Auto",
            mode="automated",
            initial_cash=1000,
            trade_cost_pct=0.03,
            max_positions=8,
        )
    )
    for i, ticker in enumerate(["AAA.L", "BBB.L", "CCC.L", "DDD.L"]):
        fund.buy(
            ticker=ticker,
            price=10,
            sizing_mode="cash",
            amount=200,
            sector="Banks",
            name=ticker,
            acted_at=f"{trade_day}{i + 1}T12:00:00+00:00",
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
            acted_at=f"2026-03-0{i + 1}T12:00:00+00:00",
        )
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(__import__("json").dumps(config.to_dict()), encoding="utf-8")
    (out / "automated_fund.json").write_text(
        __import__("json").dumps(fund.to_dict()), encoding="utf-8"
    )
    return fund


def _read_config(out: Path) -> dict:
    return __import__("json").loads((out / "config.json").read_text(encoding="utf-8"))


def test_second_review_does_not_reapply_on_lifetime_metrics(tmp_path: Path):
    """Regression: the day after an apply, a thin new epoch must not fall back to lifetime."""
    out = tmp_path / "paper"
    _write_churny_track(
        out,
        config=AutomationConfig(
            max_positions=5, skip_timing_wait=True, min_conviction=0.0, sector_cap=0.5
        ),
    )
    first = run_decision_review(
        output_dir=out, apply=True, fetch_benchmark=False, benchmark_return=0.05
    )
    assert first.applied is True
    after_first = _read_config(out)

    second = run_decision_review(
        output_dir=out, apply=True, fetch_benchmark=False, benchmark_return=0.05
    )
    assert second.applied is False
    assert second.enough_history is False
    assert _read_config(out) == after_first
    assert any("days since last knob apply" in r for r in second.reasons)


def _seed_epoch(out: Path, *, started_at: str, knobs: LearningKnobs) -> None:
    from value_investor.decision_review import KnobEpoch, save_knob_epoch

    save_knob_epoch(
        out,
        KnobEpoch(
            started_at=started_at,
            baseline_nav=400.0,
            baseline_contributed_capital=1000.0,
            knobs=knobs.to_dict(),
        ),
    )


def _add_epoch_activity(out: Path, since: datetime) -> None:
    import json

    fund = PaperFund.from_dict(json.loads((out / "automated_fund.json").read_text()))
    stamp = since + timedelta(days=1)
    for ticker in ["EEE.L", "FFF.L"]:
        fund.buy(
            ticker=ticker,
            price=10,
            sizing_mode="cash",
            amount=200,
            sector="Mining",
            name=ticker,
            acted_at=stamp.isoformat(),
        )
        fund.sell(
            ticker=ticker,
            price=9,
            sizing_mode="shares",
            amount=fund.holdings[ticker].shares,
            acted_at=(stamp + timedelta(minutes=5)).isoformat(),
        )
    for i in range(3):
        fund.record_mark(
            {t: 9.0 for t in fund.holdings},
            note=f"e{i}",
            acted_at=(stamp + timedelta(hours=i + 1)).isoformat(),
        )
    (out / "automated_fund.json").write_text(json.dumps(fund.to_dict()), encoding="utf-8")


def test_epoch_cooldown_blocks_apply_until_aged(tmp_path: Path):
    knobs = LearningKnobs(max_positions=5, skip_timing_wait=True, min_conviction=0.0)
    cfg = AutomationConfig(max_positions=5, skip_timing_wait=True, min_conviction=0.0)

    young = tmp_path / "young"
    _write_churny_track(young, config=cfg)
    start = datetime.now(tz=UTC) - timedelta(days=5)
    _seed_epoch(young, started_at=start.isoformat(), knobs=knobs)
    _add_epoch_activity(young, start)
    result = run_decision_review(
        output_dir=young, apply=True, fetch_benchmark=False, benchmark_return=0.05
    )
    assert result.metrics["epoch"]["equity_marks"] >= 2
    assert result.metrics["epoch"]["trade_count"] >= 1
    assert 4.5 < result.metrics["epoch"]["age_days"] < 5.5
    assert result.applied is False
    assert "cooldown" in result.note
    assert _read_config(young)["min_conviction"] == 0.0

    aged = tmp_path / "aged"
    _write_churny_track(aged, config=cfg)
    start = datetime.now(tz=UTC) - timedelta(days=MIN_EPOCH_DAYS + 2)
    _seed_epoch(aged, started_at=start.isoformat(), knobs=knobs)
    _add_epoch_activity(aged, start)
    result = run_decision_review(
        output_dir=aged, apply=True, fetch_benchmark=False, benchmark_return=0.05
    )
    assert result.enough_history is True
    assert result.proposed_changes
    assert result.applied is True


def _pressured_metrics() -> BookMetrics:
    return BookMetrics(
        portfolio_value=640,
        contributed_capital=1000,
        total_return=-0.36,
        total_costs=400,
        cost_drag=0.40,
        trade_count=60,
        buy_count=35,
        sell_count=25,
        positions=3,
        cash_fraction=0.01,
        equity_marks=40,
        max_sector_weight=0.34,
        dominant_sector="Banks",
        benchmark_return=-0.02,
        excess_after_costs=-0.34,
    )


def test_detect_saturated_knobs_at_bounds():
    at_bounds = LearningKnobs(
        max_positions=3, skip_timing_wait=True, min_conviction=0.6, sector_cap=0.2
    )
    saturated = detect_saturated_knobs(_pressured_metrics(), at_bounds)
    by_knob = {row["knob"]: row for row in saturated}
    assert set(by_knob) == {"min_conviction", "max_positions", "sector_cap"}
    assert by_knob["min_conviction"]["pressure"] == "raise"
    assert by_knob["max_positions"]["pressure"] == "lower"

    _proposed, changes, _reasons = propose_knob_updates(_pressured_metrics(), at_bounds)
    assert changes == {}


def test_detect_saturated_knobs_empty_when_room_left():
    knobs = LearningKnobs(max_positions=5, skip_timing_wait=True, min_conviction=0.2)
    assert detect_saturated_knobs(_pressured_metrics(), knobs) == []


def test_run_decision_review_reports_saturation(tmp_path: Path):
    out = tmp_path / "paper"
    _write_churny_track(
        out,
        config=AutomationConfig(
            max_positions=3, skip_timing_wait=True, min_conviction=0.6, sector_cap=0.2
        ),
    )
    result = run_decision_review(
        output_dir=out, apply=True, fetch_benchmark=False, benchmark_return=0.05
    )
    assert result.applied is False
    knobs = {row["knob"] for row in result.saturated_knobs}
    assert {"max_positions", "sector_cap"} <= knobs
    assert any("Saturated at bound" in r for r in result.reasons)
    payload = __import__("json").loads((out / "decision_review.json").read_text())
    assert payload["saturated_knobs"]


def test_max_positions_floor_matches_graduated_allocation_sync():
    assert max_positions_bounds_for(AutomationConfig())[0] == 3
    ga = default_graduated_allocation_config(AutomationConfig(max_positions=3))
    assert ga.max_positions == GRADUATED_ALLOCATION_MIN_POSITIONS
    assert max_positions_bounds_for(ga)[0] == GRADUATED_ALLOCATION_MIN_POSITIONS


def test_graduated_allocation_review_does_not_fight_track_sync(tmp_path: Path):
    """Regression: review proposed max_positions 3, sync reset it to 4, every weekday."""
    out = tmp_path / "graduated_allocation"
    _write_churny_track(
        out,
        config=AutomationConfig(
            max_positions=GRADUATED_ALLOCATION_MIN_POSITIONS,
            skip_timing_wait=True,
            min_conviction=0.6,
            sector_cap=0.2,
            use_graduated_allocation=True,
        ),
    )
    result = run_decision_review(
        output_dir=out, apply=True, fetch_benchmark=False, benchmark_return=0.05
    )
    assert "max_positions" not in result.proposed_changes
    assert _read_config(out)["max_positions"] == GRADUATED_ALLOCATION_MIN_POSITIONS
    by_knob = {row["knob"]: row for row in result.saturated_knobs}
    assert by_knob["max_positions"]["bound"] == GRADUATED_ALLOCATION_MIN_POSITIONS


def test_review_publishes_metrics_since_frozen_zero_datum(tmp_path: Path):
    """L533: fair labs score forward from the warm-start datum, which knob applies never move."""
    import json

    from value_investor.decision_review import KnobEpoch, load_forward_zero_datum, save_knob_epoch

    out = tmp_path / "ai_judgment_fair"
    _write_churny_track(
        out,
        config=AutomationConfig(max_positions=5, skip_timing_wait=True, min_conviction=0.0),
    )
    zero_at = "2026-02-15T12:00:00+00:00"
    (out / "fair_cost_lab_provenance.json").write_text(
        json.dumps(
            {
                "suite": "B",
                "endurance_zero_datum": {
                    "started_at": zero_at,
                    "baseline_nav": 400.0,
                    "baseline_contributed_capital": 1000.0,
                },
            }
        ),
        encoding="utf-8",
    )
    later_epoch = "2026-03-02T00:00:00+00:00"
    save_knob_epoch(
        out,
        KnobEpoch(
            started_at=later_epoch,
            baseline_nav=380.0,
            baseline_contributed_capital=1000.0,
            knobs={},
        ),
    )
    assert load_forward_zero_datum(out)["started_at"] == zero_at

    result = run_decision_review(
        output_dir=out, apply=False, fetch_benchmark=False, benchmark_return=0.05
    )
    since = result.metrics["since_zero_datum"]
    assert since["started_at"] == zero_at
    assert since["source"] == "fair_cost_lab_provenance.json"
    assert since["baseline_nav"] == 400.0
    assert since["equity_marks"] > result.metrics["epoch"]["equity_marks"]
    assert result.metrics["epoch"]["started_at"] == later_epoch
    assert since["excess_after_costs"] == round(since["total_return"] - 0.05, 4)


def test_review_omits_since_zero_datum_without_provenance(tmp_path: Path):
    out = tmp_path / "rules"
    _write_churny_track(out, config=AutomationConfig(max_positions=5))
    result = run_decision_review(
        output_dir=out, apply=False, fetch_benchmark=False, benchmark_return=0.05
    )
    assert "since_zero_datum" not in result.metrics
