"""Tests for exclusion-ladder rebalance_log replay."""

import json
from pathlib import Path

from value_investor.exclusion_ladder_replay import (
    REPLAY_FILENAME,
    REVIEW_FILENAME,
    ExclusionStep,
    replay_knobs_for_step,
    run_exclusion_ladder_replay,
    spawn_exclusion_shadow,
)
from value_investor.exclusion_universe_archive_sim import REVIEW_FILENAME as ARCHIVE_REVIEW
from value_investor.paper_automation import CONFIG_FILENAME, AutomationConfig
from value_investor.rebalance_log import append_rebalance_log


def _sample_log_entry(when: str, conviction_a: float = 0.9, conviction_b: float = 0.2) -> dict:
    return {
        "schema_version": 2,
        "strategy_mode": "automated",
        "trade_cost_pct": 0.0,
        "max_positions": 2,
        "acted": True,
        "gate": {"local_time": when},
        "selection": {
            "skip_timing_wait": False,
            "min_conviction": 0.0,
            "sector_cap": 1.0,
            "use_adjusted_signal": True,
            "require_research_accumulate": True,
            "exit_confirm_screens": 0,
        },
        "nav_before": 1000.0,
        "cash_before": 1000.0,
        "contributed_capital_before": 1000.0,
        "holdings_before": [],
        "rebalance_state_before": {},
        "screen_buy_tier": [
            {"ticker": "GOOD.L", "signal": "buy", "conviction_score": conviction_a, "price": 10},
            {"ticker": "LOW.L", "signal": "buy", "conviction_score": conviction_b, "price": 10},
        ],
        "candidates": [
            {
                "ticker": "GOOD.L",
                "signal": "buy",
                "adjusted_signal": "buy",
                "research_verdict": "accumulate",
                "conviction_score": conviction_a,
                "price": 10,
                "sector": "Banks",
                "timing_signal": "neutral",
            },
            {
                "ticker": "LOW.L",
                "signal": "buy",
                "adjusted_signal": "buy",
                "research_verdict": "accumulate",
                "conviction_score": conviction_b,
                "price": 10,
                "sector": "Mining",
                "timing_signal": "neutral",
            },
        ],
        "holdings_after": [],
        "rebalance_state_after": {},
    }


def test_replay_knobs_for_step_maps_conviction_floor():
    cfg = AutomationConfig(min_conviction=0.0, skip_timing_wait=False, use_adjusted_signal=True)
    step = ExclusionStep("u4", "test", exclude_timing_wait=True, min_conviction=0.35)
    knobs = replay_knobs_for_step(step, cfg)
    assert knobs["min_conviction"] == 0.35
    assert knobs["skip_timing_wait"] is True


def test_run_exclusion_ladder_replay_writes_artifacts(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    paper_root = data_dir / "paper_automation" / "ai_judgment"
    paper_root.mkdir(parents=True)
    (data_dir / ARCHIVE_REVIEW).write_text(
        json.dumps(
            {
                "ladder": [
                    {"step_id": "u0", "label": "baseline"},
                    {
                        "step_id": "u4",
                        "label": "tight",
                        "exclude_timing_wait": True,
                        "min_conviction": 0.35,
                    },
                ],
                "recommended_step": {"step_id": "u4"},
            }
        ),
        encoding="utf-8",
    )
    (paper_root / CONFIG_FILENAME).write_text(
        json.dumps(
            AutomationConfig(
                track_id="ai_judgment",
                use_adjusted_signal=True,
                require_research_accumulate=True,
                max_positions=2,
            ).to_dict()
        ),
        encoding="utf-8",
    )
    append_rebalance_log(paper_root, _sample_log_entry("2026-01-01T12:00:00+00:00"))
    append_rebalance_log(
        paper_root,
        {
            **_sample_log_entry("2026-01-08T12:00:00+00:00"),
            "nav_before": 1000.0,
            "cash_before": 500.0,
            "holdings_before": [
                {"ticker": "GOOD.L", "shares": 50, "avg_cost": 10, "sector": "Banks", "name": "Good"}
            ],
        },
    )

    review = run_exclusion_ladder_replay(
        data_dir / "paper_automation",
        data_dir=data_dir,
        tracks=("ai_judgment",),
    )
    assert review["recommended_step_id"] == "u4"
    assert (data_dir / "paper_automation" / REPLAY_FILENAME).exists()
    assert (data_dir / "paper_automation" / REVIEW_FILENAME).exists()
    assert "ai_judgment" in review["tracks"]


def test_spawn_exclusion_shadow_creates_config(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    paper_root = data_dir / "paper_automation"
    ai_dir = paper_root / "ai_judgment"
    ai_dir.mkdir(parents=True)
    (data_dir / ARCHIVE_REVIEW).write_text(
        json.dumps(
            {
                "ladder": [
                    {
                        "step_id": "u4",
                        "label": "tight",
                        "exclude_timing_wait": True,
                        "min_conviction": 0.35,
                    }
                ],
                "recommended_step": {"step_id": "u4"},
            }
        ),
        encoding="utf-8",
    )
    (ai_dir / CONFIG_FILENAME).write_text(
        json.dumps(
            AutomationConfig(
                track_id="ai_judgment",
                use_adjusted_signal=True,
                require_research_accumulate=True,
                min_conviction=0.45,
            ).to_dict()
        ),
        encoding="utf-8",
    )
    append_rebalance_log(ai_dir, _sample_log_entry("2026-01-01T12:00:00+00:00"))

    result = spawn_exclusion_shadow(paper_root, data_dir=data_dir, warm_start=True)
    assert result["spawned"] is True
    shadow_dir = paper_root / "ai_judgment_exclusion_u4"
    assert (shadow_dir / CONFIG_FILENAME).exists()
    shadow = AutomationConfig.from_dict(json.loads((shadow_dir / CONFIG_FILENAME).read_text()))
    assert shadow.is_exclusion_shadow is True
    assert shadow.min_conviction == 0.35
    assert shadow.skip_timing_wait is True
