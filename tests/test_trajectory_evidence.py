"""Tests for trajectory evidence package."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.backtest import RunSnapshot
from value_investor.trajectory_evidence import (
    build_boundary_watch_panel,
    build_model_focus_candidates,
    build_transition_events,
    run_trajectory_evidence,
    slim_trajectory_evidence_for_review,
    summarize_transition_outcomes,
)


def _snap(run_at: str, rows: list[dict], prices: dict[str, float] | None = None) -> RunSnapshot:
    tickers = [row["ticker"] for row in rows]
    default_prices = {ticker: 100.0 for ticker in tickers}
    if prices:
        default_prices.update(prices)
    return RunSnapshot(run_at=run_at, prices=default_prices, signals=rows)


def test_build_transition_events_detects_signal_upgrade():
    snaps = [
        _snap(
            "2026-08-09T00:00:00+00:00",
            [{"ticker": "A.L", "signal": "hold", "conviction_score": 0.2, "timing_signal": "wait"}],
        ),
        _snap(
            "2026-08-16T00:00:00+00:00",
            [
                {
                    "ticker": "A.L",
                    "signal": "buy",
                    "conviction_score": 0.4,
                    "timing_signal": "neutral",
                }
            ],
            prices={"A.L": 100.0},
        ),
        _snap(
            "2026-08-23T00:00:00+00:00",
            [
                {
                    "ticker": "A.L",
                    "signal": "buy",
                    "conviction_score": 0.41,
                    "timing_signal": "neutral",
                }
            ],
            prices={"A.L": 110.0},
        ),
    ]
    events = build_transition_events(snaps)
    assert len(events) == 1
    assert events[0]["transition_key"] == "hold->buy"
    assert events[0]["direction"] == "upgrade"
    outcomes = events[0]["outcomes"]
    assert outcomes["forward_return_1w"] == 0.1
    assert outcomes["prediction_success_1w"] is True
    assert outcomes["weeks_to_realization"] == 1
    assert outcomes["expected_return_sign"] == 1


def test_build_transition_events_multi_horizon_returns():
    rows_hold = [
        {"ticker": "A.L", "signal": "hold", "conviction_score": 0.2, "timing_signal": "wait"}
    ]
    rows_buy = [
        {
            "ticker": "A.L",
            "signal": "buy",
            "conviction_score": 0.4,
            "timing_signal": "neutral",
        }
    ]
    price_path = [100.0, 100.0, 110.0, 115.0, 120.0, 130.0]
    snaps = [
        _snap(
            f"2026-08-{9 + index:02d}T00:00:00+00:00",
            rows_hold if index == 0 else rows_buy,
            prices={"A.L": price_path[index]},
        )
        for index in range(6)
    ]
    events = build_transition_events(snaps)
    assert len(events) == 1
    outcomes = events[0]["outcomes"]
    assert outcomes["forward_return_1w"] == 0.1
    assert outcomes["forward_return_4w"] == 0.3
    assert outcomes["prediction_success_4w"] is True
    assert outcomes["weeks_to_realization"] == 1


def test_build_boundary_watch_panel_tags_pre_buy():
    panel = build_boundary_watch_panel(
        [
            {
                "ticker": "A.L",
                "name": "A",
                "signal": "hold",
                "conviction_score": 0.30,
                "signal_trend": "improving",
                "timing_signal": "neutral",
            }
        ]
    )
    assert panel[0]["boundary_tags"] == ["pre_buy"]


def test_summarize_transition_outcomes_groups_direction():
    events = [
        {
            "transition_key": "hold->buy",
            "direction": "upgrade",
            "outcomes": {
                "forward_return_1w": 0.05,
                "expected_return_sign": 1,
                "prediction_success_1w": True,
            },
        },
        {
            "transition_key": "buy->hold",
            "direction": "downgrade",
            "outcomes": {
                "forward_return_1w": -0.02,
                "expected_return_sign": -1,
                "prediction_success_1w": True,
            },
        },
    ]
    summary = summarize_transition_outcomes(events)
    assert summary["labeled_event_count"] == 2
    assert summary["upgrade_events"]["count"] == 1
    assert summary["downgrade_events"]["mean_forward_return"] == -0.02
    assert summary["prediction_hit_rate_by_horizon"]["1w"]["prediction_hit_rate"] == 1.0


def test_summarize_transition_outcomes_weeks_to_realization():
    events = [
        {
            "direction": "upgrade",
            "outcomes": {
                "expected_return_sign": 1,
                "weeks_to_realization": 2,
                "realization_within_12w": True,
                "forward_return_1w": 0.01,
                "prediction_success_1w": True,
            },
        },
        {
            "direction": "upgrade",
            "outcomes": {
                "expected_return_sign": 1,
                "weeks_to_realization": 4,
                "realization_within_12w": True,
                "forward_return_1w": 0.01,
                "prediction_success_1w": True,
            },
        },
    ]
    summary = summarize_transition_outcomes(events)
    real = summary["weeks_to_realization"]
    assert real["realized_event_count"] == 2
    assert real["median_weeks"] == 3.0
    assert real["within_4w_rate"] == 1.0


def test_build_model_focus_candidates_ranks_weak_transitions():
    summary = {
        "labeled_event_count": 40,
        "by_transition_key": {
            "hold->buy": {"count": 20, "mean_forward_return": -0.008, "positive_rate": 0.25},
            "buy->hold": {"count": 16, "mean_forward_return": 0.014, "positive_rate": 0.56},
            "tiny": {"count": 3, "mean_forward_return": -0.2, "positive_rate": 0.0},
        },
        "prediction_hit_rate_by_horizon": {
            "1w": {"scored_event_count": 30, "prediction_hit_rate": 0.40},
            "4w": {"scored_event_count": 20, "prediction_hit_rate": 0.52},
        },
        "weeks_to_realization": {
            "realized_event_count": 18,
            "median_weeks": 1,
            "within_4w_rate": 0.94,
        },
    }
    candidates = build_model_focus_candidates(summary)
    kinds = {row["kind"] for row in candidates}
    keys = {row["key"] for row in candidates}
    assert "hold->buy" in keys
    assert "tiny" not in keys
    assert "horizon_hit_rate" in kinds
    assert "realization_lag" in kinds


def test_slim_trajectory_evidence_for_review_omits_event_dump():
    slim = slim_trajectory_evidence_for_review(
        {
            "snapshot_count": 10,
            "transition_event_count": 383,
            "outcome_summary": {
                "labeled_event_count": 40,
                "by_transition_key": {
                    "hold->buy": {"count": 20, "mean_forward_return": -0.01, "positive_rate": 0.25}
                },
                "prediction_hit_rate_by_horizon": {
                    "1w": {"scored_event_count": 30, "prediction_hit_rate": 0.4}
                },
                "weeks_to_realization": {"median_weeks": 1},
            },
            "events": [{"ticker": "A.L"}],
        }
    )
    assert slim is not None
    assert "events" not in slim
    assert slim["labeled_event_count"] == 40
    assert slim["model_focus_candidates"]
    assert "assessment-model" in slim["purpose"]


def test_run_trajectory_evidence_writes_artifacts(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    history = data_dir / "history"
    history.mkdir(parents=True)
    rows = [{"ticker": "A.L", "signal": "hold", "conviction_score": 0.2, "timing_signal": "wait"}]
    (history / "run_20260809.json").write_text(
        json.dumps(_snap("2026-08-09T00:00:00+00:00", rows).to_dict()),
        encoding="utf-8",
    )
    (history / "run_20260816.json").write_text(
        json.dumps(
            _snap(
                "2026-08-16T00:00:00+00:00",
                [
                    {
                        "ticker": "A.L",
                        "signal": "buy",
                        "conviction_score": 0.4,
                        "timing_signal": "neutral",
                    }
                ],
            ).to_dict()
        ),
        encoding="utf-8",
    )
    (data_dir / "latest.json").write_text(
        json.dumps(
            {
                "run_at": "2026-08-16T00:00:00+00:00",
                "reports": [
                    {
                        "ticker": "A.L",
                        "name": "A",
                        "signal": "buy",
                        "conviction_score": 0.4,
                        "signal_trend": "new",
                        "timing_signal": "neutral",
                        "weeks_at_signal": 1,
                        "passed_families": "cheapness",
                        "action_note": "Buy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = run_trajectory_evidence(data_dir=data_dir, include_loser_cards=False)
    assert payload["transition_event_count"] == 1
    assert "model_focus_candidates" in payload
    assert (data_dir / "trajectory_transitions.json").exists()
    assert (data_dir / "trajectory_boundary_watch.json").exists()
    assert (data_dir / "trajectory_evidence_review.json").exists()
