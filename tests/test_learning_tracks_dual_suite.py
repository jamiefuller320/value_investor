"""Dual-suite learning-track scoreboard (presentation / publish only)."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.learning_tracks_dual_suite import (
    SUCCESS_DEFINITION_FAIR_ADOPTION,
    build_learning_tracks_dual_suite,
    classify_suite,
)
from value_investor.paper_automation import FUND_FILENAME


def test_classify_suite_fair_and_cohort() -> None:
    assert classify_suite("ai_judgment") == "A"
    assert classify_suite("ai_judgment_fair") == "B"
    assert classify_suite("rules_fair") == "B"
    assert classify_suite("buy_tier_level") == "B"
    assert classify_suite("ai_judgment", track_configs={"ai_judgment": {"is_suite_b": True}}) == "B"


def test_build_dual_suite_scoreboard_fair_adoption(tmp_path: Path) -> None:
    review = {
        "primary_learning_track": "ai_judgment",
        "primary_excess_after_costs": -0.35,
        "beat_market": False,
        "beat_control": True,
        "verdict": "underperforming",
        "reviews": {
            "ai_judgment": {
                "is_primary_learning_track": True,
                "metrics": {
                    "excess_after_costs": -0.35,
                    "cost_drag": 0.39,
                    "trade_count": 10,
                    "epoch": {"excess_after_costs": -0.1},
                },
            },
            "rules": {
                "is_primary_learning_track": False,
                "metrics": {"excess_after_costs": -0.4, "cost_drag": 0.45, "trade_count": 12},
            },
            "ai_judgment_fair": {
                "is_primary_learning_track": False,
                "metrics": {"excess_after_costs": -0.12, "cost_drag": 0.08, "trade_count": 5},
            },
            "rules_fair": {
                "is_primary_learning_track": False,
                "metrics": {"excess_after_costs": -0.08, "cost_drag": 0.05, "trade_count": 4},
            },
            "buy_tier_level": {
                "is_primary_learning_track": False,
                "metrics": {"excess_after_costs": 0.01, "cost_drag": 0.006, "trade_count": 20},
            },
        },
    }
    # Minimal fund for fair-assess path (optional).
    # learning_track_dirs: rules → paper root; ai_judgment → paper_root/ai_judgment.
    (tmp_path / FUND_FILENAME).write_text(
        json.dumps(
            {
                "contributed_capital": 10000,
                "config": {"trade_cost_pct": 0.03, "initial_cash": 10000},
                "trades": [
                    {"id": "1", "ticker": "AAA.L", "side": "buy", "gross": 1000, "cost": 30},
                    {"id": "2", "ticker": "AAA.L", "side": "sell", "gross": 1100, "cost": 33},
                ],
            }
        ),
        encoding="utf-8",
    )
    ai_dir = tmp_path / "ai_judgment"
    ai_dir.mkdir()
    (ai_dir / FUND_FILENAME).write_text(
        (tmp_path / FUND_FILENAME).read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    payload = build_learning_tracks_dual_suite(
        review,
        paper_root=tmp_path,
        include_fair_assess=True,
    )
    assert payload is not None
    assert payload["success_definition"] == SUCCESS_DEFINITION_FAIR_ADOPTION
    assert payload["adoption_suite"] == "B"
    assert payload["primary_learning_track_unchanged"] is True
    assert payload["primary_learning_track"] == "ai_judgment"
    assert payload["suite_a"]["headline_not_adoption_truth"] is True
    assert "ai_judgment" in payload["suite_a"]["track_ids"]
    assert "ai_judgment_fair" not in payload["suite_a"]["track_ids"]
    assert "ai_judgment_fair" in payload["suite_b"]["track_ids"]
    assert "buy_tier_level" in payload["suite_b"]["track_ids"]
    assert payload["suite_b"]["ai_excess_after_costs"] == -0.12
    assert payload["suite_b"]["control_excess_after_costs"] == -0.08
    assert payload["suite_b"]["beat_market"] is False
    assert payload["suite_b"]["beat_control"] is False  # -0.12 < -0.08
    assert payload["promotion_gate"]["do_not_flip_primary_on_stress_excess"] is True
    assess = payload["fair_assess_suite_a"]
    assert assess is not None
    assert "ai_judgment" in assess["tracks"]
    assert assess["tracks"]["ai_judgment"]["cost_drag_relief"] is not None


def test_build_dual_suite_without_fair_twins() -> None:
    review = {
        "primary_learning_track": "ai_judgment",
        "reviews": {
            "ai_judgment": {
                "is_primary_learning_track": True,
                "metrics": {"excess_after_costs": -0.2},
            },
            "rules": {"metrics": {"excess_after_costs": -0.25}},
        },
    }
    payload = build_learning_tracks_dual_suite(review, include_fair_assess=False)
    assert payload is not None
    assert payload["suite_b"]["available"] is False
    assert payload["suite_b"]["ai_excess_after_costs"] is None
    assert payload["fair_assess_suite_a"] is None
