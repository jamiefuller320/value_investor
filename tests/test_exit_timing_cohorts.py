"""Tests for observe-only hold-recovery and swap-rotation cohorts."""

from value_investor.exit_timing_cohorts import (
    ExitTimingCohortConfig,
    assess_framework_readiness,
    build_exit_timing_review,
    ingest_hold_episodes,
    ingest_swap_rotations,
    run_exit_timing_cohort_pass,
    update_hold_episodes,
    update_swap_rotations,
)
from value_investor.paper_fund import PaperFund, PaperFundConfig, Position


def _stressed_fund() -> PaperFund:
    fund = PaperFund.create(
        PaperFundConfig(
            name="Cohort test",
            mode="automated",
            initial_cash=0,
            trade_cost_pct=0.0,
            max_positions=5,
        )
    )
    fund.holdings["STRESS.L"] = Position(
        ticker="STRESS.L",
        shares=10,
        avg_cost=100,
        name="Stressed",
        momentum_grace=False,
    )
    fund.rebalance_state.exit_streak = {"STRESS.L": 1}
    return fund


def test_ingest_hold_episode_on_exit_streak():
    fund = _stressed_fund()
    store: dict = {"hold_episodes": []}
    candidates = [
        {
            "ticker": "STRESS.L",
            "signal": "hold",
            "adjusted_signal": "hold",
            "data_quality_score": 0.85,
            "conviction_score": 0.6,
        }
    ]
    added = ingest_hold_episodes(
        fund,
        store,
        track_id="rules",
        candidates=candidates,
        prices_by_ticker={"STRESS.L": 98.0},
        as_of="2026-07-10T09:15:00+01:00",
    )
    assert added == 1
    episode = store["hold_episodes"][0]
    assert episode["ticker"] == "STRESS.L"
    assert "exit_streak" in episode["stress_triggers"]
    assert episode["data_quality_score"] == 0.85
    assert episode["status"] == "open"


def test_update_hold_episode_closes_on_sell():
    fund = _stressed_fund()
    store: dict = {"hold_episodes": []}
    ingest_hold_episodes(
        fund,
        store,
        track_id="rules",
        candidates=[{"ticker": "STRESS.L", "signal": "hold"}],
        prices_by_ticker={"STRESS.L": 95.0},
        as_of="2026-07-10T09:15:00+01:00",
    )
    fund.sell(
        ticker="STRESS.L",
        price=94,
        sizing_mode="shares",
        amount=10,
        note="Automated exit",
        acted_at="2026-07-20T09:15:00+01:00",
    )
    updated = update_hold_episodes(
        fund,
        store,
        prices_by_ticker={"STRESS.L": 94.0},
        as_of="2026-07-20T09:15:00+01:00",
    )
    assert updated >= 0
    episode = store["hold_episodes"][0]
    assert episode["status"] == "closed"
    assert episode["close_reason"] == "sold_while_underwater"


def test_ingest_swap_rotation_same_pass():
    store: dict = {"swap_rotations": []}
    trades = [
        {
            "side": "sell",
            "ticker": "OLD.L",
            "price": 120,
            "shares": 10,
            "gross": 1200,
            "cost": 0,
            "avg_cost_at_exit": 100,
        },
        {
            "side": "buy",
            "ticker": "NEW.L",
            "price": 50,
            "shares": 20,
            "gross": 1000,
            "cost": 0,
        },
    ]
    added = ingest_swap_rotations(
        store,
        track_id="rules",
        trades=trades,
        as_of="2026-07-10T09:15:00+01:00",
        trade_cost_pct=0.001,
    )
    assert added == 1
    rotation = store["swap_rotations"][0]
    assert rotation["status"] == "open"
    assert rotation["sells"][0]["realized_pct"] == 0.2


def test_update_swap_rotation_verdict():
    store = {
        "swap_rotations": [
            {
                "rotation_id": "rules:2026-07-10",
                "track_id": "rules",
                "logged_at": "2026-06-01T09:15:00+01:00",
                "status": "open",
                "sells": [{"ticker": "OLD.L", "price": 100}],
                "buys": [{"ticker": "NEW.L", "price": 50}],
                "checkpoints": [],
                "sell_returns_since_rotation": {},
                "buy_returns_since_rotation": {},
            }
        ]
    }
    cfg = ExitTimingCohortConfig(shadow_windows_days=(7, 28, 56, 84))
    as_of = "2026-09-15T09:15:00+01:00"
    updated = update_swap_rotations(
        store,
        prices_by_ticker={"OLD.L": 95.0, "NEW.L": 60.0},
        as_of=as_of,
        cfg=cfg,
    )
    assert updated >= 4
    rotation = store["swap_rotations"][0]
    assert rotation["status"] == "closed"
    assert rotation["verdict"] == "replacement_outperformed"


def test_assess_framework_readiness_reports_gaps():
    store = {"hold_episodes": [], "swap_rotations": []}
    readiness = assess_framework_readiness(store)
    assert readiness["ready_for_probability_analysis"] is False
    assert len(readiness["gaps"]) >= 2


def test_run_exit_timing_cohort_pass_writes_artifacts(tmp_path):
    fund = _stressed_fund()
    review = run_exit_timing_cohort_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=[
            {
                "ticker": "STRESS.L",
                "signal": "hold",
                "data_quality_score": 0.9,
            }
        ],
        trades=[],
        prices_by_ticker={"STRESS.L": 97.0},
        trade_cost_pct=0.001,
        as_of="2026-07-10T09:15:00+01:00",
    )
    assert review["track_id"] == "rules"
    assert (tmp_path / "exit_timing_cohorts.json").exists()
    assert (tmp_path / "exit_timing_cohorts_review.json").exists()
    assert review["readiness"]["ready_for_probability_analysis"] is False


def test_build_exit_timing_review_includes_framework():
    review = build_exit_timing_review({"hold_episodes": [], "swap_rotations": []}, track_id="rules")
    assert review["framework"]["hold_recovery"]["question"]
    assert review["framework"]["swap_rotation"]["question"]
