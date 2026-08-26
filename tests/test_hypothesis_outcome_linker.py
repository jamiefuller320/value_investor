"""Tests for hypothesis outcome linker."""

from __future__ import annotations

from value_investor.exit_timing_cohorts import (
    ingest_hold_episodes,
)
from value_investor.hypothesis_integrity import THESIS_BROKEN, THESIS_INTACT
from value_investor.hypothesis_outcome_linker import (
    aggregate_hold_outcomes_by_thesis,
    assess_outcome_linker_readiness,
    enrich_cohorts_with_thesis,
    run_hypothesis_outcome_link_pass,
)
from value_investor.paper_fund import PaperFund, PaperFundConfig, Position


def _fund_with_holding() -> PaperFund:
    fund = PaperFund.create(
        PaperFundConfig(
            name="Linker test",
            mode="automated",
            initial_cash=0,
            trade_cost_pct=0.0,
            max_positions=5,
        )
    )
    fund.holdings["GOOD.L"] = Position(
        ticker="GOOD.L", shares=10, avg_cost=100, name="Good", momentum_grace=False
    )
    fund.rebalance_state.exit_streak = {"GOOD.L": 1}
    return fund


def test_hold_episode_stamps_thesis_at_ingest():
    fund = _fund_with_holding()
    store: dict = {"hold_episodes": []}
    candidates = [
        {
            "ticker": "GOOD.L",
            "signal": "buy",
            "passed_families": "cheapness,quality",
            "conviction_score": 0.6,
            "data_quality_score": 0.9,
            "research_verdict": "accumulate",
        }
    ]
    ingest_hold_episodes(
        fund,
        store,
        track_id="rules",
        candidates=candidates,
        prices_by_ticker={"GOOD.L": 92.0},
        as_of="2026-08-01T10:00:00+01:00",
    )
    episode = store["hold_episodes"][0]
    assert episode.get("thesis_status_at_start") == THESIS_INTACT
    assert episode.get("recommended_action_at_start")


def test_aggregate_hold_outcomes_by_thesis():
    episodes = [
        {
            "status": "closed",
            "thesis_status_at_start": THESIS_INTACT,
            "recovered_to_breakeven": True,
            "close_reason": "recovered_max_window",
            "peak_unrealized_pct": 0.02,
            "trough_unrealized_pct": -0.08,
        },
        {
            "status": "closed",
            "thesis_status_at_start": THESIS_BROKEN,
            "recovered_to_breakeven": False,
            "close_reason": "sold_while_underwater",
            "peak_unrealized_pct": -0.02,
            "trough_unrealized_pct": -0.2,
        },
    ]
    summary = aggregate_hold_outcomes_by_thesis(episodes)
    assert summary["closed_total"] == 2
    intact = summary["by_thesis_status"][THESIS_INTACT]
    broken = summary["by_thesis_status"][THESIS_BROKEN]
    assert intact["recovery_rate"] == 1.0
    assert broken["recovery_rate"] == 0.0
    assert broken["sold_underwater_rate"] == 1.0


def test_readiness_not_ready_until_enough_closed():
    hold_summary = {"closed_total": 2, "by_thesis_status": {}}
    swap_summary = {"sell_legs_total": 0}
    readiness = assess_outcome_linker_readiness(hold_summary, swap_summary)
    assert readiness["ready_for_thesis_outcome_analysis"] is False
    assert readiness["gaps"]


def test_run_hypothesis_outcome_link_pass(tmp_path):
    fund = _fund_with_holding()
    cohorts_path = tmp_path / "exit_timing_cohorts.json"
    store = {"schema_version": 1, "hold_episodes": [], "swap_rotations": []}
    candidates = [
        {
            "ticker": "GOOD.L",
            "signal": "buy",
            "passed_families": "cheapness,quality",
            "conviction_score": 0.55,
            "data_quality_score": 0.85,
        }
    ]
    ingest_hold_episodes(
        fund,
        store,
        track_id="rules",
        candidates=candidates,
        prices_by_ticker={"GOOD.L": 90.0},
        as_of="2026-08-01T10:00:00+01:00",
    )
    cohorts_path.write_text(__import__("json").dumps(store), encoding="utf-8")

    review = run_hypothesis_outcome_link_pass(
        output_dir=tmp_path,
        track_id="rules",
        candidates=candidates,
    )
    assert (tmp_path / "hypothesis_outcome_link_review.json").exists()
    assert review["hold_recovery_by_thesis"]["open_with_thesis"] >= 1

    # Backfill path: strip thesis and re-enrich
    store2 = __import__("json").loads(cohorts_path.read_text())
    store2["hold_episodes"][0].pop("thesis_status_at_start", None)
    cohorts_path.write_text(__import__("json").dumps(store2), encoding="utf-8")
    stamped = enrich_cohorts_with_thesis(store2, candidates=candidates)
    assert stamped["hold_episodes"] >= 1
    assert store2["hold_episodes"][0].get("thesis_status_at_start") == THESIS_INTACT
