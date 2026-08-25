"""Tests for hypothesis-first underwater review and loser feedback."""

from __future__ import annotations

from types import SimpleNamespace

from value_investor.capital_allocation import exit_urgency
from value_investor.hypothesis_integrity import (
    THESIS_BROKEN,
    THESIS_INTACT,
    THESIS_WEAKENING,
    assess_holding_hypothesis,
    portfolio_loser_feedback,
    run_hypothesis_integrity_pass,
    urgency_adjustment_for_hypothesis,
)
from value_investor.paper_automation import surveil_position


def test_intact_despite_drawdown_when_buy_and_cheap():
    card = assess_holding_hypothesis(
        ticker="AAA.L",
        mark=85.0,
        avg_cost=100.0,
        row={
            "signal": "buy",
            "passed_families": "cheapness,quality,risk",
            "conviction_score": 0.6,
            "data_quality_score": 0.9,
            "research_verdict": "accumulate",
            "timing_signal": "neutral",
        },
    )
    assert card["underwater"] is True
    assert card["thesis_status"] == THESIS_INTACT
    assert card["recommended_action"] in {"hold_tolerate", "watch_review"}


def test_broken_when_avoid_and_cheapness_gone():
    card = assess_holding_hypothesis(
        ticker="BBB.L",
        mark=70.0,
        avg_cost=100.0,
        row={
            "signal": "avoid",
            "passed_families": "quality",
            "conviction_score": 0.2,
            "research_verdict": "sell",
        },
    )
    assert card["thesis_status"] == THESIS_BROKEN
    assert card["recommended_action"] == "exit_candidate"


def test_weakening_when_left_buy_tier():
    card = assess_holding_hypothesis(
        ticker="CCC.L",
        mark=90.0,
        avg_cost=100.0,
        row={
            "signal": "hold",
            "passed_families": "cheapness,quality",
            "conviction_score": 0.5,
            "timing_signal": "wait",
        },
    )
    assert card["thesis_status"] == THESIS_WEAKENING


def test_portfolio_tolerance_and_selection_feedback():
    assessments = [
        assess_holding_hypothesis(
            ticker="W1",
            mark=110.0,
            avg_cost=100.0,
            row={"signal": "buy", "passed_families": "cheapness,quality,risk"},
        ),
        assess_holding_hypothesis(
            ticker="L1",
            mark=80.0,
            avg_cost=100.0,
            row={"signal": "buy", "passed_families": "quality"},
        ),
        assess_holding_hypothesis(
            ticker="L2",
            mark=75.0,
            avg_cost=100.0,
            row={"signal": "hold", "passed_families": "quality"},
        ),
    ]
    feedback = portfolio_loser_feedback(
        assessments,
        position_values={"W1": 100.0, "L1": 80.0, "L2": 75.0},
    )
    assert feedback["loser_count"] == 2
    assert feedback["loser_share"] > 0.5
    assert feedback["within_tolerance"] is False
    assert any("cheapness" in flag for flag in feedback["selection_feedback_flags"])


def test_exit_urgency_dampened_when_thesis_intact():
    row = {"signal": "buy", "timing_signal": "accumulate"}
    calm = exit_urgency(
        row=row,
        mark=85.0,
        avg_cost=100.0,
        in_target_set=True,
        hypothesis_status=THESIS_INTACT,
    )
    raw = exit_urgency(
        row=row,
        mark=85.0,
        avg_cost=100.0,
        in_target_set=True,
        hypothesis_status=None,
    )
    assert calm < raw
    assert urgency_adjustment_for_hypothesis(THESIS_INTACT) < 0


def test_surveillance_stop_intact_is_watch_not_action():
    alerts = surveil_position(
        ticker="AAA.L",
        name="Aaa",
        source="paper",
        mark=80.0,
        stop_loss=85.0,
        avg_cost=100.0,
        screen_row={
            "signal": "buy",
            "passed_families": "cheapness,quality",
            "conviction_score": 0.55,
            "data_quality_score": 0.9,
            "research_verdict": "hold",
        },
    )
    stop_alerts = [a for a in alerts if "stop" in a.message.lower()]
    assert stop_alerts
    assert all(a.severity == "watch" for a in stop_alerts)


def test_run_hypothesis_integrity_pass_writes(tmp_path):
    fund = SimpleNamespace(
        holdings={
            "AAA.L": SimpleNamespace(shares=10.0, avg_cost=100.0, name="Aaa"),
            "BBB.L": SimpleNamespace(shares=5.0, avg_cost=50.0, name="Bbb"),
        }
    )
    candidates = [
        {
            "ticker": "AAA.L",
            "name": "Aaa",
            "signal": "buy",
            "passed_families": "cheapness,quality",
            "conviction_score": 0.6,
            "data_quality_score": 0.9,
            "price": 80.0,
        },
        {
            "ticker": "BBB.L",
            "name": "Bbb",
            "signal": "avoid",
            "passed_families": "quality",
            "conviction_score": 0.2,
            "research_verdict": "sell",
            "price": 40.0,
        },
    ]
    payload = run_hypothesis_integrity_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=candidates,
        prices_by_ticker={"AAA.L": 80.0, "BBB.L": 40.0},
    )
    assert (tmp_path / "hypothesis_integrity.json").exists()
    assert (tmp_path / "hypothesis_integrity.md").exists()
    assert payload["underwater_count"] == 2
    assert payload["portfolio_feedback"]["broken_loser_count"] >= 1
    assert payload["portfolio_feedback"]["balancing_hint"] == "rotate_broken_first"
