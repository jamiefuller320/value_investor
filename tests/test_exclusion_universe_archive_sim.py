"""Tests for observe-only exclusion-universe archive simulation."""

import json
from pathlib import Path

from value_investor.backtest import HISTORY_DIR, RunSnapshot
from value_investor.exclusion_universe_archive_sim import (
    COHORTS_FILENAME,
    REVIEW_FILENAME,
    UNIVERSE_BUY_TIER_ONLY,
    ExclusionStep,
    ExclusionUniverseArchiveConfig,
    _equal_weight_forward_return,
    _passes_exclusion_step,
    default_exclusion_ladder,
    run_exclusion_universe_archive_sim,
)


def _write_history_snapshot(
    output_dir: Path,
    filename: str,
    run_at: str,
    prices: dict[str, float],
    signals: list[dict],
) -> None:
    history = output_dir / HISTORY_DIR
    history.mkdir(parents=True, exist_ok=True)
    payload = {"run_at": run_at, "prices": prices, "signals": signals}
    (history / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_passes_exclusion_step_conviction_floor():
    step = ExclusionStep("t", "test", min_conviction=0.35)
    row = {
        "ticker": "A.L",
        "screen_signal": "buy",
        "effective_signal": "buy",
        "conviction_score": 0.4,
    }
    assert _passes_exclusion_step(row, step)
    row_low = {**row, "conviction_score": 0.2}
    assert not _passes_exclusion_step(row_low, step)


def test_passes_exclusion_step_timing_wait():
    step = ExclusionStep("t", "test", exclude_timing_wait=True)
    assert _passes_exclusion_step(
        {
            "ticker": "A.L",
            "screen_signal": "buy",
            "effective_signal": "buy",
            "timing_signal": "neutral",
            "conviction_score": 0.5,
        },
        step,
    )
    assert not _passes_exclusion_step(
        {
            "ticker": "A.L",
            "screen_signal": "buy",
            "effective_signal": "buy",
            "timing_signal": "wait",
            "conviction_score": 0.5,
        },
        step,
    )


def test_equal_weight_forward_return():
    entry = RunSnapshot(
        run_at="2026-01-01T10:00:00+00:00",
        prices={"A.L": 100.0, "B.L": 50.0},
        signals=[],
    )
    exit_snap = RunSnapshot(
        run_at="2026-01-29T10:00:00+00:00",
        prices={"A.L": 110.0, "B.L": 45.0},
        signals=[],
    )
    ret, count = _equal_weight_forward_return(["A.L", "B.L"], entry, exit_snap)
    assert count == 2
    assert ret is not None
    assert abs(ret - 0.0) < 1e-9


def test_run_exclusion_universe_archive_sim_positive_exclusion_alpha(tmp_path: Path):
    """Low-conviction loser excluded by conviction ladder should lift filtered EW return."""
    good = {
        "ticker": "GOOD.L",
        "signal": "buy",
        "conviction_score": 0.8,
        "timing_signal": "neutral",
    }
    bad = {
        "ticker": "BAD.L",
        "signal": "buy",
        "conviction_score": 0.2,
        "timing_signal": "neutral",
    }
    rows = [good, bad]
    _write_history_snapshot(
        tmp_path,
        "run_20260101_100000.json",
        "2026-01-01T10:00:00+00:00",
        {"GOOD.L": 100.0, "BAD.L": 100.0, "^FTSE": 8000.0},
        rows,
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260129_100000.json",
        "2026-01-29T10:00:00+00:00",
        {"GOOD.L": 110.0, "BAD.L": 90.0, "^FTSE": 8100.0},
        rows,
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260326_100000.json",
        "2026-03-26T10:00:00+00:00",
        {"GOOD.L": 115.0, "BAD.L": 85.0, "^FTSE": 8200.0},
        rows,
    )

    ladder = (
        ExclusionStep("u0", "Baseline"),
        ExclusionStep("u1", "Conviction >= 0.35", min_conviction=0.35),
    )
    review = run_exclusion_universe_archive_sim(
        tmp_path,
        config=ExclusionUniverseArchiveConfig(
            universe_mode=UNIVERSE_BUY_TIER_ONLY,
            ladder=ladder,
            min_week_pairs=1,
            min_filtered_pool=1,
            max_positions=1,
        ),
    )

    assert review["scope"] == "exclusion_universe_archive"
    assert (tmp_path / COHORTS_FILENAME).exists()
    assert (tmp_path / REVIEW_FILENAME).exists()
    assert review["readiness"]["week_pairs"] >= 2

    u0 = next(row for row in review["ladder_results"] if row["step_id"] == "u0")
    u1 = next(row for row in review["ladder_results"] if row["step_id"] == "u1")
    assert (u0["summary"]["cumulative_exclusion_alpha"] or 0) <= (
        u1["summary"]["cumulative_exclusion_alpha"] or 0
    )
    assert (u1["summary"]["cumulative_exclusion_alpha"] or 0) > 0
    assert (u1["hindsight_summary"]["mean_bottom_quartile_exclude_rate"] or 0) >= 0.5


def test_default_ladder_includes_ai_overlay_steps():
    ladder = default_exclusion_ladder(include_ai_overlay_steps=True)
    ids = [step.step_id for step in ladder]
    assert "u6" in ids
    assert "u7" in ids
