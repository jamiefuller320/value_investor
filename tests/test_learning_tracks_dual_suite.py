"""Dual-suite learning-track scoreboard (presentation / publish only)."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.learning_tracks_dual_suite import (
    SUCCESS_DEFINITION_FAIR_ADOPTION,
    build_learning_tracks_dual_suite,
    build_paper_track_analysis_buckets,
    classify_suite,
    slim_dual_suite_for_analysis,
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


def test_paper_track_analysis_buckets_split_identity_from_adoption() -> None:
    review = {
        "primary_learning_track": "ai_judgment",
        "primary_excess_after_costs": -0.35,
        "beat_market": False,
        "beat_control": True,
        "verdict": "underperforming",
        "reviews": {
            "ai_judgment": {
                "metrics": {"excess_after_costs": -0.35, "cost_drag": 0.40, "trade_count": 62}
            },
            "rules": {
                "metrics": {"excess_after_costs": -0.42, "cost_drag": 0.47, "trade_count": 80}
            },
            "ai_judgment_fair": {
                "metrics": {"excess_after_costs": -0.13, "cost_drag": 0.14, "trade_count": 34}
            },
            "rules_fair": {
                "metrics": {"excess_after_costs": -0.10, "cost_drag": 0.08, "trade_count": 34}
            },
            "buy_tier_level": {
                "metrics": {
                    "excess_after_costs": 0.032,
                    "cost_drag": 0.007,
                    "trade_count": 93,
                    "equity_marks": 19,
                }
            },
            "buy_tier_level_dca": {"metrics": {"excess_after_costs": 0.02, "equity_marks": 8}},
        },
    }
    dual = build_learning_tracks_dual_suite(review, include_fair_assess=False)
    buckets = build_paper_track_analysis_buckets(dual)
    assert buckets is not None
    assert buckets["suite_a_stress"]["is_adoption_truth"] is False
    assert buckets["suite_b_adoption"]["is_adoption_truth"] is True
    assert buckets["suite_b_adoption"]["beat_market"] is False
    assert buckets["suite_b_adoption"]["beat_control"] is False
    identity = buckets["suite_b_identity"]
    assert identity["is_adoption_truth"] is False
    assert identity["tracks"]["buy_tier_level"]["excess_after_costs"] == 0.032
    assert identity["tracks"]["buy_tier_level"]["equity_marks"] == 19
    slim = slim_dual_suite_for_analysis(dual)
    assert slim is not None
    assert "fair_assess_suite_a" not in slim


def test_paper_track_analysis_buckets_none_without_dual() -> None:
    assert build_paper_track_analysis_buckets(None) is None
    assert slim_dual_suite_for_analysis(None) is None


def test_suite_b_adoption_scores_forward_from_zero_datum() -> None:
    """L533: warm-start seed (replayed at 3% stress) must not drive Suite B adoption."""
    review = {
        "primary_learning_track": "ai_judgment",
        "reviews": {
            "ai_judgment": {"metrics": {"excess_after_costs": -0.35}},
            "rules": {"metrics": {"excess_after_costs": -0.42}},
            "ai_judgment_fair": {
                "metrics": {
                    "excess_after_costs": -0.135,
                    "since_zero_datum": {
                        "started_at": "2026-09-01T09:27:42+01:00",
                        "excess_after_costs": 0.012,
                        "equity_marks": 20,
                    },
                }
            },
            "rules_fair": {
                "metrics": {
                    "excess_after_costs": -0.108,
                    "since_zero_datum": {
                        "started_at": "2026-09-01T09:27:27+01:00",
                        "excess_after_costs": 0.02,
                    },
                }
            },
        },
    }
    out = build_learning_tracks_dual_suite(review, include_fair_assess=False)
    assert out is not None
    suite_b = out["suite_b"]
    assert suite_b["ai_excess_after_costs"] == 0.012
    assert suite_b["control_excess_after_costs"] == 0.02
    assert suite_b["excess_basis"] == {"ai": "since_zero_datum", "control": "since_zero_datum"}
    assert suite_b["beat_market"] is True
    assert suite_b["beat_control"] is False
    assert suite_b["lifetime_excess_diagnostic"]["ai"] == -0.135
    row = suite_b["tracks"]["ai_judgment_fair"]
    assert row["since_zero_datum_excess_after_costs"] == 0.012
    assert row["excess_after_costs"] == -0.135


def test_suite_b_falls_back_to_lifetime_without_zero_datum() -> None:
    review = {
        "reviews": {
            "ai_judgment_fair": {"metrics": {"excess_after_costs": -0.05}},
            "rules_fair": {"metrics": {"excess_after_costs": -0.07}},
        },
    }
    out = build_learning_tracks_dual_suite(review, include_fair_assess=False)
    assert out is not None
    assert out["suite_b"]["ai_excess_after_costs"] == -0.05
    assert out["suite_b"]["excess_basis"] == {"ai": "lifetime", "control": "lifetime"}
