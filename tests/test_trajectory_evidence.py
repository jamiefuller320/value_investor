"""Tests for trajectory evidence package."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.backtest import RunSnapshot
from value_investor.trajectory_evidence import (
    build_boundary_watch_panel,
    build_transition_events,
    run_trajectory_evidence,
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
    assert events[0]["outcomes"]["forward_return_1w"] == 0.1


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
            "outcomes": {"forward_return_1w": 0.05},
        },
        {
            "transition_key": "buy->hold",
            "direction": "downgrade",
            "outcomes": {"forward_return_1w": -0.02},
        },
    ]
    summary = summarize_transition_outcomes(events)
    assert summary["labeled_event_count"] == 2
    assert summary["upgrade_events"]["count"] == 1
    assert summary["downgrade_events"]["mean_forward_return_1w"] == -0.02


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
    assert (data_dir / "trajectory_transitions.json").exists()
    assert (data_dir / "trajectory_boundary_watch.json").exists()
    assert (data_dir / "trajectory_evidence_review.json").exists()
