"""Tests for loser snapshot cards."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.loser_snapshot_cards import (
    build_loser_snapshot_card,
    run_loser_snapshot_cards,
    select_loser_cohort_members,
)


def _sample_report(**overrides):
    base = {
        "ticker": "BAD.L",
        "name": "Bad Co",
        "sector": "Industrials",
        "signal": "avoid",
        "conviction_score": 0.15,
        "timing_signal": "wait",
        "weeks_at_signal": 3,
        "signal_trend": "deteriorating",
        "stability_label": "unstable",
        "data_quality_score": 0.9,
        "composite_score": 0.2,
        "models_passed": 2,
        "model_count": 22,
        "passed_families": "cheapness",
        "failed_models": ["Quality Value"],
        "model_failures": {"Quality Value": ["ROE below 12%"]},
        "action_note": "Pass — weak fundamentals",
        "research_verdict": "avoid",
    }
    base.update(overrides)
    return base


def test_select_loser_cohort_members_scoped():
    reports = [
        _sample_report(ticker="BAD.L", signal="avoid"),
        _sample_report(ticker="HOLD.L", signal="hold"),
        _sample_report(ticker="BUY.L", signal="buy"),
        _sample_report(ticker="ALUM.L", signal="hold"),
    ]
    members = select_loser_cohort_members(
        reports,
        memo_tickers={"ALUM.L", "BUY.L"},
    )
    assert set(members) == {"BAD.L", "ALUM.L"}
    assert members["BAD.L"] == ["avoid"]
    assert members["ALUM.L"] == ["failed_buy_alumni"]


def test_build_loser_snapshot_card_includes_triggers():
    card = build_loser_snapshot_card(
        _sample_report(),
        cohorts=["avoid"],
        has_research_memo=False,
        reports=[_sample_report()],
    )
    assert card["screen"]["failed_families"] == ["quality", "dividend", "garp", "risk"]
    assert "conviction >= 0.35" in card["opinion_flip_triggers"]
    assert any("AVOID" in line for line in card["summary_lines"])


def test_run_loser_snapshot_cards_writes_artifacts(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "latest.json").write_text(
        json.dumps(
            {
                "run_at": "2026-08-23T00:00:00+00:00",
                "reports": [
                    _sample_report(),
                    _sample_report(ticker="ALUM.L", signal="hold"),
                ],
            }
        ),
        encoding="utf-8",
    )
    research = data_dir / "research" / "ALUM.L"
    research.mkdir(parents=True)
    (research / "research.json").write_text(
        json.dumps({"ticker": "ALUM.L", "signal": "buy", "version": 1}),
        encoding="utf-8",
    )

    payload = run_loser_snapshot_cards(data_dir=data_dir)
    assert payload["card_count"] == 2
    assert (data_dir / "loser_snapshot_cards.json").exists()
    assert (data_dir / "loser_snapshot_cards.md").exists()
    assert payload["cohort_counts"]["avoid"] == 1
    assert payload["cohort_counts"]["failed_buy_alumni"] == 1
