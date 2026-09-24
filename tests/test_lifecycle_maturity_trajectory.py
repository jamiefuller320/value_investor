"""Tests for lifecycle maturity mix trajectory (L463)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.lifecycle_maturity_trajectory import (
    FINDING_TITLE,
    build_lifecycle_maturity_snapshot,
    ops_finding_from_maturity,
    refresh_lifecycle_maturity_trajectory,
)
from value_investor.storage import write_json


def _write(path: Path, payload: dict) -> None:
    write_json(path, payload, compact=False)


def _board_payload() -> dict:
    """Minimal board: young focus book + harvest-heavy live FTSE."""
    return {
        "schema_version": 1,
        "generated_at": "2026-09-24T10:00:00+00:00",
        "observe_only": True,
        "markets": [
            {
                "market_id": "ftse350",
                "label": "FTSE 350",
                "is_live": True,
                "is_focus": False,
                "is_admitted": True,
                "default_track_id": "buy_tier_level",
                "tracks": [
                    {
                        "track_id": "buy_tier_level",
                        "track_label": "Buy-tier level",
                        "is_primary": False,
                        "is_default": True,
                        "holdings_count": 59,
                        "position_columns": {
                            "just_bought": {
                                "count": 2,
                                "truncated": 0,
                                "shown": [
                                    {
                                        "ticker": "A.L",
                                        "days_in_column": 1,
                                        "unrealized_pnl_pct": 0.01,
                                    },
                                    {
                                        "ticker": "B.L",
                                        "days_in_column": 3,
                                        "unrealized_pnl_pct": -0.02,
                                    },
                                ],
                            },
                            "growth": {
                                "count": 20,
                                "truncated": 0,
                                "shown": [
                                    {
                                        "ticker": "C.L",
                                        "days_in_column": 16,
                                        "unrealized_pnl_pct": 0.05,
                                    }
                                ]
                                + [
                                    {
                                        "ticker": f"G{i}.L",
                                        "days_in_column": 20,
                                        "unrealized_pnl_pct": -0.01 if i % 2 else 0.02,
                                    }
                                    for i in range(19)
                                ],
                            },
                            "near_sell": {
                                "count": 37,
                                "truncated": 0,
                                "shown": [
                                    {
                                        "ticker": "N.L",
                                        "days_in_column": 40,
                                        "unrealized_pnl_pct": -0.03,
                                    }
                                ]
                                + [
                                    {
                                        "ticker": f"NS{i}.L",
                                        "days_in_column": 30,
                                        "unrealized_pnl_pct": 0.01,
                                    }
                                    for i in range(36)
                                ],
                            },
                            "just_sold": {"count": 0, "truncated": 0, "shown": []},
                            "post_sale": {"count": 0, "truncated": 0, "shown": []},
                        },
                    }
                ],
            },
            {
                "market_id": "euro_depth",
                "label": "Euro depth",
                "is_live": False,
                "is_focus": True,
                "is_admitted": True,
                "default_track_id": "buy_tier_level",
                "tracks": [
                    {
                        "track_id": "buy_tier_level",
                        "track_label": "Buy-tier level",
                        "is_primary": False,
                        "is_default": True,
                        "holdings_count": 36,
                        "position_columns": {
                            "just_bought": {
                                "count": 17,
                                "truncated": 0,
                                "shown": [
                                    {
                                        "ticker": f"E{i}.PA",
                                        "days_in_column": 5,
                                        "unrealized_pnl_pct": -0.01 if i < 5 else 0.02,
                                    }
                                    for i in range(17)
                                ],
                            },
                            "growth": {
                                "count": 16,
                                "truncated": 0,
                                "shown": [
                                    {
                                        "ticker": f"EG{i}.PA",
                                        "days_in_column": 14,
                                        "unrealized_pnl_pct": -0.02 if i < 9 else 0.03,
                                    }
                                    for i in range(16)
                                ],
                            },
                            "near_sell": {
                                "count": 3,
                                "truncated": 0,
                                "shown": [
                                    {
                                        "ticker": f"EN{i}.PA",
                                        "days_in_column": 10,
                                        "unrealized_pnl_pct": -0.01,
                                    }
                                    for i in range(3)
                                ],
                            },
                            "just_sold": {"count": 4, "truncated": 0, "shown": []},
                            "post_sale": {"count": 0, "truncated": 0, "shown": []},
                        },
                    }
                ],
            },
        ],
    }


def test_maturity_per_market_shares_and_trajectory(tmp_path: Path):
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    board_path = tmp_path / "lifecycle_board.json"
    ops_path = tmp_path / "ops_status.json"
    store_path = tmp_path / "lifecycle_maturity_trajectory.json"
    _write(board_path, _board_payload())
    _write(ops_path, {"run_at": (now - timedelta(minutes=30)).isoformat(), "overall": "ok"})
    # Prior: euro more early-heavy → improving when early_share falls.
    _write(
        store_path,
        {
            "schema_version": 1,
            "generated_at": (now - timedelta(hours=12)).isoformat(),
            "history": [
                {
                    "at": (now - timedelta(hours=12)).isoformat(),
                    "ftse350": {
                        "primary_value": 40.0,
                        "early_share": 0.4,
                        "uw_rate_growth": 0.5,
                        "held_count": 59,
                        "freshness_state": "fresh",
                    },
                    "euro_depth": {
                        "primary_value": 95.0,
                        "early_share": 0.95,
                        "uw_rate_growth": 0.7,
                        "held_count": 36,
                        "freshness_state": "fresh",
                    },
                }
            ],
        },
    )

    snap = refresh_lifecycle_maturity_trajectory(
        store_path=store_path,
        board_path=board_path,
        ops_status_path=ops_path,
        now=now,
    )
    assert snap["observe_only"] is True
    assert snap["surface_freshness"] == "fresh"
    assert "beat_market" in snap["separation"]["excludes"]
    assert "exit_shadow" in snap["separation"]["excludes"]
    assert "decision_review_knob_apply" in snap["separation"]["excludes"]

    by_id = {row["id"]: row for row in snap["markets"]}
    euro = by_id["euro_depth"]
    ftse = by_id["ftse350"]
    assert euro["is_focus"] is True
    assert euro["metrics"]["just_bought_count"] == 17
    assert euro["metrics"]["growth_count"] == 16
    assert euro["metrics"]["held_count"] == 36
    assert euro["metrics"]["early_share"] == round((17 + 16) / 36, 4)
    assert euro["primary_value"] == round(((17 + 16) / 36) * 100, 2)
    assert euro["metrics"]["uw_rate_by_column"]["just_bought"] == round(5 / 17, 4)
    assert euro["metrics"]["uw_rate_by_column"]["growth"] == round(9 / 16, 4)
    assert euro["metrics"]["uw_rate_by_column"]["near_sell"] == 1.0
    assert euro["trajectory"]["direction"] == "improving"
    assert "Better" in euro["trajectory"]["label"]

    # FTSE harvest-heavy: early = 22/59 ≈ 37.29%; prior was 40 → improving.
    assert ftse["metrics"]["near_sell_count"] == 37
    assert ftse["primary_value"] == round((22 / 59) * 100, 2)
    assert ftse["trajectory"]["direction"] == "improving"

    saved = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(saved["history"]) == 2
    assert ops_finding_from_maturity(snap) is None


def test_maturity_missing_board_emits_finding(tmp_path: Path):
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    snap = build_lifecycle_maturity_snapshot(
        board_path=tmp_path / "missing_board.json",
        ops_status_path=tmp_path / "missing_ops.json",
        prior_path=tmp_path / "missing_store.json",
        now=now,
    )
    assert snap["surface_freshness"] == "missing"
    finding = ops_finding_from_maturity(snap)
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False


def test_maturity_stale_board(tmp_path: Path):
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    board = _board_payload()
    board["generated_at"] = (now - timedelta(hours=48)).isoformat()
    board_path = tmp_path / "lifecycle_board.json"
    _write(board_path, board)
    _write(tmp_path / "ops_status.json", {"run_at": now.isoformat(), "overall": "ok"})
    snap = build_lifecycle_maturity_snapshot(
        board_path=board_path,
        ops_status_path=tmp_path / "ops_status.json",
        prior_path=tmp_path / "none.json",
        now=now,
    )
    assert snap["surface_freshness"] == "stale"
    finding = ops_finding_from_maturity(snap)
    assert finding is not None
    assert finding["auto_fixable"] is False


def test_maturity_separation_block_lists_excluded_layers():
    """L463 store documents hard separation from other analysis measures."""
    text = Path("src/value_investor/lifecycle_maturity_trajectory.py").read_text(encoding="utf-8")
    for needle in (
        "beat_market",
        "excess_after_costs",
        "exit_shadow",
        "l462_wow_nav",
        "n153_fx",
        "decision_review_knob_apply",
    ):
        assert needle in text
    # No imports that would couple into those lanes.
    assert "from value_investor.exit_shadow" not in text
    assert "from value_investor.decision_review" not in text
    assert "paper_fund" not in text or "BUY_TIER" in text  # track id only via paper_automation
