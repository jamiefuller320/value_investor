"""Tests for L632 lifecycle exit_reason / entry trail backfill helpers."""

from __future__ import annotations

from value_investor.lifecycle_exit_reason_backfill import lifecycle_reason_coverage
from value_investor.sealed_lifecycle import slim_lifecycle_episodes


def test_coverage_counts_closed_blank_vs_open():
    payload = {
        "lifecycle_episodes": [
            {
                "ticker": "AAA.L",
                "status": "closed",
                "exit_reason": "leave_buy_tier",
                "entry_reason": "enter_buy_tier",
            },
            {"ticker": "BBB.L", "status": "closed"},
            {"ticker": "CCC.L", "status": "open", "entry_detail": {"earnings_yield": 0.1}},
            {"ticker": "DDD.L", "status": "open"},
        ]
    }
    cov = lifecycle_reason_coverage(payload)
    assert cov["closed_n"] == 2
    assert cov["closed_blank_exit_reason"] == 1
    assert cov["open_n"] == 2
    assert cov["open_blank_exit_reason"] == 2
    assert cov["open_missing_entry_trail"] == 1


def test_slim_preserves_open_entry_detail_and_closed_exit_reason():
    rows = slim_lifecycle_episodes(
        [
            {
                "ticker": "OPEN.L",
                "status": "open",
                "entry_run_at": "2026-10-01T00:00:00+00:00",
                "entry_detail": {
                    "earnings_yield": 0.12,
                    "in_ey_top30_local": True,
                    "financial_health_pass": True,
                },
                "open_mark_return": 0.01,
            },
            {
                "ticker": "CLOSED.L",
                "status": "closed",
                "entry_run_at": "2026-09-01T00:00:00+00:00",
                "exit_run_at": "2026-10-01T00:00:00+00:00",
                "exit_reason": "identity_break_ey_band",
                "entry_detail": {"earnings_yield": 0.11},
                "fair_cost_return": 0.02,
            },
        ]
    )
    by = {r["ticker"]: r for r in rows}
    assert "exit_reason" not in by["OPEN.L"]
    assert by["OPEN.L"]["entry_detail"]["earnings_yield"] == 0.12
    assert by["CLOSED.L"]["exit_reason"] == "identity_break_ey_band"
    assert by["CLOSED.L"]["entry_detail"]["earnings_yield"] == 0.11
