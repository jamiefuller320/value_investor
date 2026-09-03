"""Tests for modelling/analysis review synthesis."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.analysis_review import (
    build_analysis_payload,
    compile_analysis_tasks,
    has_enough_analysis_inputs,
    parse_analysis_review,
    promote_analysis_tasks,
)


def test_parse_analysis_review_splits_sections():
    text = """EXECUTIVE SUMMARY
Paper primary beats control but not market.

PERFORMANCE DIAGNOSIS
- Cost drag elevated on rules track

SIGNAL & BACKTEST FINDINGS
28d buy-tier excess positive with run_count=3.

PAPER TRACK COMPARISON
AI judgment has lower cost drag than rules.

PROPOSED EXPERIMENTS
1. [offline_sim] Replay grace params on archived runs — counterfactual prior
2. [scoring] Sector healthcare overlay — attribution gap

DEFER
- Evolutionary genomes until 12 months history
"""
    review = parse_analysis_review(text)
    assert "beats control" in review.executive_summary
    assert "Cost drag" in review.performance_diagnosis
    assert "run_count=3" in review.signal_backtest_findings
    assert "AI judgment" in review.paper_track_comparison
    assert "[offline_sim]" in review.proposed_experiments
    assert "Evolutionary" in review.defer


def test_build_analysis_payload_reads_learning_tracks(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    paper = data_dir / "paper_automation"
    paper.mkdir(parents=True)
    (paper / "learning_tracks_review.json").write_text(
        json.dumps({"primary_excess_after_costs": -0.03, "beat_control": True}),
        encoding="utf-8",
    )
    (paper / "learning_tracks_churn_health.json").write_text(
        json.dumps({"tracks": {"rules": {"decision_review": {"cost_drag": 0.05}}}}),
        encoding="utf-8",
    )
    (data_dir / "latest.json").write_text(
        json.dumps({"meta": {"company_count": 248}, "backtest": {"run_count": 1}}),
        encoding="utf-8",
    )
    payload = build_analysis_payload(data_dir=data_dir, output_dir=tmp_path / "output")
    assert payload["learning_tracks_review"]["beat_control"] is True
    assert payload["churn_health"]["tracks"]["rules"]["decision_review"]["cost_drag"] == 0.05
    ok, _ = has_enough_analysis_inputs(payload)
    assert ok is True


def test_build_analysis_payload_includes_ingest_trials_for_analysis_trigger(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    paper = data_dir / "paper_automation"
    paper.mkdir(parents=True)
    (paper / "learning_tracks_review.json").write_text(
        json.dumps({"primary_excess_after_costs": -0.03}),
        encoding="utf-8",
    )
    (data_dir / "ingest_trials.json").write_text(
        json.dumps(
            {
                "trials": [
                    {
                        "id": "trial-20260812-99",
                        "status": "pending_review",
                        "review_trigger": "analysis_review",
                        "completed_at": "2026-08-12T00:00:00+00:00",
                        "title": "Weekly ingest trial",
                    },
                    {
                        "id": "trial-20260812-01",
                        "status": "pending_review",
                        "review_trigger": "horizon_scan",
                        "completed_at": "2026-08-12T00:00:00+00:00",
                        "title": "Horizon-only trial",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = build_analysis_payload(data_dir=data_dir, output_dir=tmp_path / "output")
    pending = payload["ingest_trials_pending_review"]
    assert len(pending) == 1
    assert pending[0]["id"] == "trial-20260812-99"


def test_build_analysis_payload_includes_trajectory_focus(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    paper = data_dir / "paper_automation"
    paper.mkdir(parents=True)
    (paper / "learning_tracks_review.json").write_text(
        json.dumps({"primary_excess_after_costs": -0.03}),
        encoding="utf-8",
    )
    (data_dir / "trajectory_evidence_review.json").write_text(
        json.dumps(
            {
                "snapshot_count": 10,
                "transition_event_count": 40,
                "outcome_summary": {
                    "labeled_event_count": 40,
                    "by_transition_key": {
                        "hold->buy": {
                            "count": 20,
                            "mean_forward_return": -0.008,
                            "positive_rate": 0.25,
                        }
                    },
                    "prediction_hit_rate_by_horizon": {
                        "1w": {"scored_event_count": 30, "prediction_hit_rate": 0.40}
                    },
                    "weeks_to_realization": {"median_weeks": 1, "within_4w_rate": 0.9},
                },
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "chart_outcome_review.json").write_text(
        json.dumps(
            {
                "verdict": "mixed_no_terrible",
                "verdict_label": "Mixed story — no terrible outcomes",
                "headline": "Mixed story. 2 well timed; 0 stop hits.",
                "counts": {
                    "chart_count": 4,
                    "well_timed": 2,
                    "giveback": 1,
                    "underwater": 1,
                    "terrible": 0,
                    "stop_hit": 0,
                },
                "stats": {"median_return": -0.003},
                "well_timed": [{"ticker": "AEP.L", "return_since": 0.08, "outcome": "well_timed"}],
                "weakest": [{"ticker": "JD.L", "return_since": -0.09, "outcome": "giveback"}],
                "rows": [{"ticker": "AEP.L"}, {"ticker": "JD.L"}],
                "note": "observe-only",
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "loser_snapshot_cards.json").write_text(
        json.dumps(
            {
                "card_count": 2,
                "cohort_counts": {"avoid": 1, "failed_buy_alumni": 1},
                "scope_note": "test",
                "cards": [
                    {
                        "ticker": "A.L",
                        "cohorts": ["avoid"],
                        "screen": {
                            "signal": "avoid",
                            "failed_families": ["quality", "cheapness"],
                        },
                        "opinion_flip_triggers": ["conviction_drop"],
                        "summary_lines": ["Avoid on quality fail"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "exclusion_universe_review.json").write_text(
        json.dumps(
            {
                "recommended_step": {"step_id": "u4"},
                "readiness": {"ready_for_priors": True, "week_pairs": 6},
                "ladder_results": [
                    {
                        "step_id": "u4",
                        "label": "conviction >= 0.35",
                        "summary": {
                            "cumulative_exclusion_alpha": 0.01,
                            "week_pairs": 6,
                            "mean_filtered_pool": 40,
                        },
                        "hindsight_summary": {"mean_bottom_quartile_exclude_rate": 0.4},
                    }
                ],
                "note": "observe-only",
            }
        ),
        encoding="utf-8",
    )
    (paper / "exclusion_ladder_replay_review.json").write_text(
        json.dumps(
            {
                "recommended_step_id": "u4",
                "readiness": {
                    "ready_for_shadow_spawn": True,
                    "primary_return_delta_vs_actual": 0.02,
                },
                "tracks": {
                    "ai_judgment": {
                        "best_replay_step_id": "u4",
                        "ladder_steps": [
                            {
                                "step_id": "u4",
                                "replay": {
                                    "return_delta_vs_actual": 0.02,
                                    "log_entries_replayed": 4,
                                },
                            }
                        ],
                    }
                },
                "note": "replay",
            }
        ),
        encoding="utf-8",
    )
    (paper / "learning_tracks_exit_timing.json").write_text(
        json.dumps(
            {
                "readiness": {
                    "ready_for_probability_analysis": False,
                    "hold_closed_count": 5,
                    "swap_closed_count": 2,
                },
                "hold_recovery": {"closed": {"count": 5}},
                "swap_rotation": {"closed": {"count": 2}},
                "note": "thin",
            }
        ),
        encoding="utf-8",
    )
    payload = build_analysis_payload(data_dir=data_dir, output_dir=tmp_path / "output")
    traj = payload["trajectory_evidence"]
    assert traj is not None
    assert traj["labeled_event_count"] == 40
    assert traj["model_focus_candidates"]
    assert traj["model_focus_candidates"][0]["key"] == "hold->buy"
    charts = payload["chart_outcome_review"]
    assert charts["verdict"] == "mixed_no_terrible"
    assert charts["observe_only"] is True
    assert "rows" not in charts
    losers = payload["loser_snapshot_cards"]
    assert losers["card_count"] == 2
    assert losers["top_failed_families"][0][0] == "quality"
    assert "cards" not in losers
    excl = payload["exclusion_universe"]
    assert excl["readiness"]["ready_for_priors"] is True
    assert excl["ladder_results_slim"][0]["step_id"] == "u4"
    assert "ladder_results" not in excl
    replay = payload["exclusion_ladder_replay"]
    assert replay["readiness"]["ready_for_shadow_spawn"] is True
    assert replay["tracks_slim"]["ai_judgment"]["log_entries_replayed"] == 4
    timing = payload["exit_timing_cohorts"]
    assert timing["readiness"]["hold_closed_count"] == 5
    assert timing["hold_recovery_closed"]["count"] == 5
    assert "purpose" in timing


def test_compile_and_promote_analysis_tasks(tmp_path: Path):
    review = parse_analysis_review(
        "PROPOSED EXPERIMENTS\n1. [scoring] Add sector overlay — test attribution\n"
    )
    tasks_path = tmp_path / "analysis_tasks.json"
    eng_path = tmp_path / "engineering_tasks.json"
    eng_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")

    compiled = compile_analysis_tasks(review, run_stamp="20260728", tasks_path=tasks_path)
    assert compiled["task_count"] == 1
    task_id = compiled["tasks"][0]["id"]
    assert task_id.startswith("ana-20260728-")

    result = promote_analysis_tasks(
        [task_id],
        analysis_tasks_path=tasks_path,
        engineering_tasks_path=eng_path,
    )
    assert result["promoted"] == [task_id]
    eng_payload = json.loads(eng_path.read_text(encoding="utf-8"))
    assert eng_payload["tasks"][0]["id"] == "eng-20260728-01"
    assert eng_payload["tasks"][0]["source"] == "analysis_review"

    analysis_payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert analysis_payload["tasks"][0]["status"] == "promoted"


def test_promote_skips_non_engineering_areas(tmp_path: Path):
    review = parse_analysis_review(
        "PROPOSED EXPERIMENTS\n1. [offline_sim] Replay grace — offline only\n"
    )
    tasks_path = tmp_path / "analysis_tasks.json"
    eng_path = tmp_path / "engineering_tasks.json"
    eng_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    compiled = compile_analysis_tasks(review, run_stamp="20260728", tasks_path=tasks_path)
    task_id = compiled["tasks"][0]["id"]

    result = promote_analysis_tasks(
        [task_id],
        analysis_tasks_path=tasks_path,
        engineering_tasks_path=eng_path,
    )
    assert result["promoted"] == []
    assert result["skipped"][0]["reason"].startswith("not promotable")
