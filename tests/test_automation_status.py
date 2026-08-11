"""Tests for dashboard automation settings / achievements assembly."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.automation_status import (
    build_automation_status,
    build_learning_track_epoch_datum,
    write_automation_status,
)
from value_investor.storage import write_json


def test_build_automation_status_timeline(tmp_path: Path):
    library = tmp_path / "library"
    paper = tmp_path / "paper"
    library.mkdir()
    paper.mkdir()

    write_json(
        library / "policy.json",
        {
            "schema_version": 1,
            "focus_market": "aim",
            "market_queue": ["sp500", "aim"],
            "updated_at": "2026-07-18T12:00:00+00:00",
            "graduated_markets": [
                {
                    "market": "sp500",
                    "graduated_at": "2026-07-17T04:00:00+00:00",
                    "coverage_pct": 1.0,
                    "stale_pct": 0.0,
                }
            ],
            "focus_graduation": {
                "auto_advance": True,
                "min_coverage_pct": 0.95,
                "max_stale_pct": 0.15,
                "maintenance_enabled": True,
                "history": [
                    {
                        "at": "2026-07-17T04:00:00+00:00",
                        "from_market": "sp500",
                        "to_market": "aim",
                        "reason": "advanced",
                        "coverage_pct": 1.0,
                        "stale_pct": 0.0,
                    }
                ],
            },
            "budget": {
                "plan_name": "Pro",
                "plan_monthly_usd": 20,
                "weekly_ops_cap_usd": 50.0,
                "enforce_weekly_ops_cap": True,
                "plan_refresh_day_of_month": 8,
            },
            "ladder": {
                "enabled": True,
                "research_hard_cap": 50,
                "research_all_graduated": True,
                "spend_checkpoint_usd": 60.0,
                "spend_since_checkpoint_usd": 0.0,
            },
            "research_model": {"model_id": "composer-2.5", "pool": "auto"},
            "model_review": {"last_reviewed_at": None, "review_interval_days": 14, "history": []},
            "macro_context": {"enabled": True, "refresh_on_ladder": True},
        },
        compact=False,
    )
    write_json(
        library / "last_ladder.json",
        {
            "run_at": "2026-07-18T12:36:32+00:00",
            "focus_market": "aim",
            "graduated_markets": ["sp500"],
            "plan": {"max_tickers": 40, "surplus_day": False, "research_model": "composer-2.5"},
            "layers": {
                "fundamentals": {"skipped": True},
                "maintenance": {"skipped": True},
                "screen_lite": {"shortlist_count": 3, "strong_buy": 1, "buy": 2},
                "selective_research": {
                    "executed": 3,
                    "created": 3,
                    "updated": 0,
                    "estimated_spend_usd": 1.2,
                },
                "graduation": {"skipped": True},
            },
        },
        compact=False,
    )
    write_json(
        library / "l34_slices_complete_summary.json",
        {
            "completed_at": "2026-07-18T18:33:55+00:00",
            "new_markets": ["aim"],
            "research_memos_created": 11,
            "note": "test milestone",
        },
        compact=False,
    )
    write_json(
        paper / "config.json",
        {
            "enabled": True,
            "timezone": "Europe/London",
            "auto_rebalance": True,
            "max_positions": 5,
        },
        compact=False,
    )
    write_json(
        paper / "last_run.json",
        {
            "generated_at": "2026-07-17T12:44:32+00:00",
            "acted": True,
            "note": "Rebalanced",
            "trades": [{"ticker": "AAA.L", "side": "buy", "acted_at": "2026-07-17T12:44:32+00:00"}],
            "fund": {"cash": 100, "holdings": {"AAA.L": {}}},
            "gate": {"can_act": True, "reason": "ok"},
        },
        compact=False,
    )

    payload = build_automation_status(library_root=library, paper_root=paper)
    assert payload["settings"]["library"]["focus_market"] == "aim"
    assert payload["settings"]["paper"]["enabled"] is True
    assert "paper_auto" in payload["settings"]["workflows"]
    titles = [e["title"] for e in payload["achievements"]["timeline"]]
    assert any("Library ladder run" in t for t in titles)
    assert any("Paper automation acted" in t for t in titles)
    assert any("L34 next-slice" in t for t in titles)
    assert payload["achievements"]["last_ladder"]["layers"]["research_created"] == 3

    assert payload["engineering_queue"]["status"]["open_count"] >= 0
    assert "queued_tasks" in payload["engineering_queue"]

    out = write_automation_status(
        library_root=library,
        paper_root=paper,
        path=tmp_path / "automation.json",
    )
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 1
    assert len(saved["achievements"]["timeline"]) >= 3


def test_build_learning_track_epoch_datum_from_review(tmp_path: Path):
    paper = tmp_path / "paper"
    paper.mkdir()

    write_json(
        paper / "learning_tracks_review.json",
        {
            "schema_version": 1,
            "primary_learning_track": "ai_judgment",
            "reviews": {
                "rules": {
                    "track_id": "rules",
                    "track_label": "Screen rules (control)",
                    "is_primary_learning_track": False,
                    "applied": True,
                    "metrics": {
                        "epoch": {
                            "started_at": "2026-08-11T08:28:00+00:00",
                            "baseline_nav": 914.78,
                            "portfolio_value": 914.78,
                            "total_return": 0.0,
                            "trade_count": 0,
                            "equity_marks": 0,
                            "benchmark_return": None,
                            "excess_after_costs": None,
                            "note": "Insufficient epoch marks for benchmark span.",
                            "knobs": {"min_conviction": 0.55},
                        }
                    },
                },
                "ai_judgment": {
                    "track_id": "ai_judgment",
                    "track_label": "AI judgment (primary)",
                    "is_primary_learning_track": True,
                    "applied": True,
                    "metrics": {
                        "epoch": {
                            "started_at": "2026-08-11T08:28:00+00:00",
                            "baseline_nav": 997.72,
                            "portfolio_value": 1005.0,
                            "total_return": 0.0073,
                            "trade_count": 1,
                            "equity_marks": 2,
                            "benchmark_return": 0.012,
                            "excess_after_costs": -0.0047,
                            "note": "",
                            "knobs": {"max_positions": 3},
                        }
                    },
                },
            },
        },
        compact=False,
    )

    payload = build_learning_track_epoch_datum(paper_root=paper)
    assert payload["observe_only"] is True
    assert payload["primary_learning_track"] == "ai_judgment"
    assert payload["summary"]["track_count"] == 2
    assert payload["summary"]["tracks_benchmark_span_ready"] == 1
    assert payload["summary"]["tracks_with_post_apply_trades"] == 1
    assert payload["summary"]["all_benchmark_spans_insufficient"] is False

    rules = payload["tracks"]["rules"]
    assert rules["epoch_nav"] == 914.78
    assert rules["post_apply_trade_count"] == 0
    assert rules["benchmark_span_available"] is False
    assert "Insufficient epoch marks" in rules["note"]

    primary = payload["tracks"]["ai_judgment"]
    assert primary["epoch_nav"] == 1005.0
    assert primary["post_apply_trade_count"] == 1
    assert primary["benchmark_span_available"] is True
    assert primary["enough_epoch_history"] is True


def test_build_automation_status_includes_epoch_datum(tmp_path: Path):
    library = tmp_path / "library"
    paper = tmp_path / "paper"
    library.mkdir()
    paper.mkdir()

    write_json(library / "policy.json", {"focus_market": "aim"}, compact=False)
    write_json(
        paper / "learning_tracks_review.json",
        {
            "primary_learning_track": "ai_judgment",
            "reviews": {
                "ai_judgment": {
                    "track_label": "AI judgment (primary)",
                    "is_primary_learning_track": True,
                    "applied": True,
                    "metrics": {
                        "epoch": {
                            "started_at": "2026-08-11T08:28:00+00:00",
                            "baseline_nav": 1000.0,
                            "portfolio_value": 1000.0,
                            "trade_count": 0,
                            "equity_marks": 0,
                            "note": "Insufficient epoch marks for benchmark span.",
                        }
                    },
                }
            },
        },
        compact=False,
    )

    payload = build_automation_status(library_root=library, paper_root=paper)
    epoch = payload["learning_track_epoch_datum"]
    assert epoch["observe_only"] is True
    assert epoch["summary"]["all_benchmark_spans_insufficient"] is True
    assert epoch["tracks"]["ai_judgment"]["epoch_nav"] == 1000.0
