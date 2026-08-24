"""Tests for Sunday review dashboard payload and history persistence."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.sunday_review_dashboard import (
    REVIEW_HISTORY_FILENAME,
    backfill_history_from_archives,
    build_sunday_review_dashboard,
    build_week_snapshot,
    load_review_history,
    slim_exclusion_weekly_rows,
    upsert_review_history,
)


def _sample_exclusion_archive() -> dict:
    return {
        "recommended_step": {"step_id": "u4"},
        "ladder_results": [
            {
                "step_id": "u4",
                "summary": {
                    "cumulative_exclusion_alpha": 0.005,
                    "positive_alpha_rate": 0.375,
                    "week_pairs": 2,
                    "avg_filtered_pool_size": 38.0,
                },
                "weekly": [
                    {
                        "run_at": "2026-08-09T07:00:00+00:00",
                        "exit_run_at": "2026-08-16T07:00:00+00:00",
                        "baseline_ew_return": 0.01,
                        "filtered_ew_return": 0.012,
                        "benchmark_return": 0.008,
                        "exclusion_alpha": 0.002,
                        "baseline_pool_size": 60,
                        "filtered_pool_size": 40,
                        "excluded_count": 20,
                        "hindsight": {
                            "bottom_quartile_exclude_rate": 0.45,
                            "top_quartile_retain_rate": 0.65,
                        },
                    }
                ],
            }
        ],
    }


def _sample_learning_review() -> dict:
    return {
        "primary_learning_track": "ai_judgment",
        "reviews": {
            "ai_judgment": {
                "track_id": "ai_judgment",
                "track_label": "AI judgment (primary)",
                "is_primary_learning_track": True,
                "knobs_after": {"min_conviction": 0.45},
                "metrics": {
                    "excess_after_costs": -0.17,
                    "benchmark_return": 0.01,
                    "cost_drag": 0.21,
                    "trade_count": 29,
                    "equity_marks": 15,
                    "positions": 3,
                    "epoch": {"excess_after_costs": -0.02, "equity_marks": 1},
                },
            },
            "ai_judgment_exclusion_u4": {
                "track_id": "ai_judgment_exclusion_u4",
                "track_label": "Exclusion u4 shadow",
                "metrics": {
                    "excess_after_costs": -0.12,
                    "benchmark_return": 0.01,
                    "cost_drag": 0.05,
                    "trade_count": 14,
                    "equity_marks": 9,
                    "positions": 3,
                },
            },
        },
    }


def test_slim_exclusion_weekly_rows_includes_vs_benchmark():
    rows = slim_exclusion_weekly_rows(_sample_exclusion_archive())
    assert len(rows) == 1
    assert rows[0]["exclusion_alpha"] == 0.002
    assert rows[0]["filtered_vs_benchmark"] == round(0.012 - 0.008, 6)


def test_upsert_review_history_replaces_same_week():
    history = load_review_history(Path("/nonexistent/review_history.json"))
    snap_a = build_week_snapshot(
        week_ending="2026-08-23",
        exclusion_archive=_sample_exclusion_archive(),
        learning_tracks_review=_sample_learning_review(),
    )
    snap_b = dict(snap_a)
    snap_b["analysis_headline"] = "Updated headline"
    history = upsert_review_history(history, snap_a)
    history = upsert_review_history(history, snap_b)
    assert len(history["weeks"]) == 1
    assert history["weeks"][0]["analysis_headline"] == "Updated headline"


def test_backfill_history_from_archives(tmp_path: Path):
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    bundle = {
        "generated_at": "2026-08-16T12:00:00+00:00",
        "learning_tracks_review": _sample_learning_review(),
    }
    (archive_dir / "2026-08-16.json").write_text(json.dumps(bundle), encoding="utf-8")
    rows = backfill_history_from_archives(archive_dir)
    assert len(rows) == 1
    assert rows[0]["week_ending"] == "2026-08-16"
    assert len(rows[0]["paper_tracks"]) == 2


def test_build_sunday_review_dashboard_persists_history(tmp_path: Path):
    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    paper_root.mkdir(parents=True)
    archive_dir = data_dir / "archive"
    archive_dir.mkdir()

    (data_dir / "exclusion_universe_archive.json").write_text(
        json.dumps(_sample_exclusion_archive()),
        encoding="utf-8",
    )
    (data_dir / "exclusion_universe_review.json").write_text(
        json.dumps(
            {
                "recommended_step": {"step_id": "u4"},
                "readiness": {"ready_for_priors": True, "week_pairs": 2},
                "ladder_results": _sample_exclusion_archive()["ladder_results"],
            }
        ),
        encoding="utf-8",
    )
    (paper_root / "learning_tracks_review.json").write_text(
        json.dumps(_sample_learning_review()),
        encoding="utf-8",
    )
    (data_dir / "experiment_assessment.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "summary": {"total": 1},
                "experiments": [
                    {
                        "experiment_id": "ai_judgment_exclusion_u4",
                        "kind": "exclusion_shadow",
                        "title": "Exclusion ladder shadow u4",
                        "status": "observing",
                        "pipeline": "exclusion_ladder",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = build_sunday_review_dashboard(
        data_dir,
        paper_root=paper_root,
        archive_dir=archive_dir,
        run_at="2026-08-23T08:00:00+00:00",
        persist_history=True,
        refresh_experiments=False,
    )

    assert payload["week_ending"] == "2026-08-23"
    assert payload["current"]["exclusion"]["weekly"]
    assert payload["current"]["paper_tracks"]
    history_path = data_dir / REVIEW_HISTORY_FILENAME
    assert history_path.exists()
    stored = json.loads(history_path.read_text(encoding="utf-8"))
    assert any(row.get("week_ending") == "2026-08-23" for row in stored["weeks"])
