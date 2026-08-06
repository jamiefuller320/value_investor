"""Tests for deterministic paper churn health rollup."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.churn_health import (
    build_churn_health,
    summarize_track_churn_health,
    write_churn_health,
)


def _write_track(
    track_dir: Path,
    *,
    trades: list[dict],
    cost_drag: float = 0.05,
    exit_streak: dict | None = None,
) -> None:
    track_dir.mkdir(parents=True, exist_ok=True)
    (track_dir / "config.json").write_text(
        json.dumps(
            {
                "track_id": "rules",
                "exit_confirm_screens": 2,
                "reentry_cooldown_screens": 1,
                "min_rebalance_notional_gbp": 10.0,
            }
        ),
        encoding="utf-8",
    )
    (track_dir / "decision_review.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "cost_drag": cost_drag,
                    "trade_count": len(trades),
                    "total_costs": 50.0,
                    "excess_after_costs": -0.02,
                },
                "knobs_after": {"max_positions": 3},
            }
        ),
        encoding="utf-8",
    )
    (track_dir / "automated_fund.json").write_text(
        json.dumps(
            {
                "trades": trades,
                "rebalance_state": {
                    "exit_streak": exit_streak or {"OLD.L": 1},
                    "reentry_cooldown": {},
                },
            }
        ),
        encoding="utf-8",
    )
    (track_dir / "last_run.json").write_text(
        json.dumps(
            {
                "acted": True,
                "note": "Rebalanced",
                "gate": {"local_time": "2026-07-30T09:20:00+01:00"},
                "trades": trades[-1:],
                "plan": {
                    "anticipated_holds": [
                        {
                            "action": "hold",
                            "ticker": "OLD.L",
                            "reason": "Hold buffer — outside target set (1/2 screen(s) before exit)",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def test_summarize_track_churn_health_counts_flips_and_buffer(tmp_path: Path):
    trades = [
        {
            "acted_at": "2026-07-29T09:15:00+01:00",
            "ticker": "AAA.L",
            "side": "sell",
            "note": "Automated trim",
        },
        {
            "acted_at": "2026-07-29T09:15:01+01:00",
            "ticker": "AAA.L",
            "side": "buy",
            "note": "Automated buy",
        },
    ]
    track_dir = tmp_path / "rules"
    _write_track(track_dir, trades=trades, cost_drag=0.11)

    summary = summarize_track_churn_health(
        track_dir,
        track_id="rules",
        as_of=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        lookback_days=7,
    )
    assert summary["decision_review"]["cost_drag"] == 0.11
    assert summary["rebalance_state"]["buffered_holdings"] == 1
    window = next(v for k, v in summary.items() if str(k).startswith("trades_last_"))
    assert window["adjacent_flip_count"] == 1


def test_write_churn_health_for_learning_tracks(tmp_path: Path):
    paper = tmp_path / "paper_automation"
    _write_track(paper, trades=[], cost_drag=0.08)
    (paper / "ai_judgment").mkdir()
    _write_track(paper / "ai_judgment", trades=[], cost_drag=0.03)
    (paper / "momentum_grace").mkdir()
    _write_track(paper / "momentum_grace", trades=[], cost_drag=0.01)
    (paper / "technical").mkdir()
    _write_track(paper / "technical", trades=[], cost_drag=0.02)

    payload = write_churn_health(paper)
    assert (paper / "learning_tracks_churn_health.json").exists()
    assert set(payload["tracks"]) == {"rules", "ai_judgment", "momentum_grace", "technical"}
    assert any("cost drag" in alert["title"].lower() for alert in payload["alerts"])
