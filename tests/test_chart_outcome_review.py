"""Tests for buy-tier chart outcome review."""

from __future__ import annotations

from pathlib import Path

from value_investor.chart_outcome_review import (
    REVIEW_FILENAME,
    REVIEW_MD_FILENAME,
    VERDICT_HAS_TERRIBLE,
    VERDICT_MIXED_NO_TERRIBLE,
    build_chart_outcome_review,
    classify_chart_outcome,
    run_chart_outcome_review,
    score_chart_payload,
    slim_chart_outcome_review,
    verdict_from_counts,
)
from value_investor.storage import write_json


def _chart(
    *,
    ticker: str = "AAA.L",
    signal: str = "strong_buy",
    since: str = "2026-08-02",
    entry: float = 100.0,
    dates: list[str] | None = None,
    closes: list[float] | None = None,
    stop: float = 85.0,
    target: float = 110.0,
    stop_date: str | None = None,
    target_date: str | None = None,
    stop_direction: str | None = None,
    target_direction: str | None = None,
) -> dict:
    return {
        "ticker": ticker,
        "name": ticker,
        "signal": signal,
        "signal_since": since,
        "initial_levels_as_of": since,
        "dates": dates or ["2026-08-03", "2026-08-10", "2026-09-02"],
        "closes": closes or [101.0, 108.0, 106.0],
        "initial_levels": {"last": entry, "stop_loss": stop, "take_profit": target},
        "level_crossings": [
            {
                "key": "stop_loss",
                "label": "Stop",
                "price": stop,
                "date": stop_date,
                "direction": stop_direction,
            },
            {
                "key": "take_profit",
                "label": "Target",
                "price": target,
                "date": target_date,
                "direction": target_direction,
            },
        ],
    }


def test_classify_well_timed_target_hold():
    assert (
        classify_chart_outcome(
            return_since=0.03,
            max_drawdown=-0.02,
            stop_hit=False,
            target_hit=True,
            has_entry=True,
        )
        == "well_timed"
    )


def test_classify_giveback_and_terrible():
    assert (
        classify_chart_outcome(
            return_since=-0.04,
            max_drawdown=-0.06,
            stop_hit=False,
            target_hit=True,
            has_entry=True,
        )
        == "giveback"
    )
    assert (
        classify_chart_outcome(
            return_since=-0.16,
            max_drawdown=-0.18,
            stop_hit=False,
            target_hit=False,
            has_entry=True,
        )
        == "terrible"
    )
    assert (
        classify_chart_outcome(
            return_since=-0.11,
            max_drawdown=-0.12,
            stop_hit=True,
            target_hit=False,
            has_entry=True,
        )
        == "terrible"
    )


def test_score_uses_frozen_initial_last_not_gap_open():
    payload = _chart(
        entry=100.0,
        dates=["2026-08-03", "2026-08-10", "2026-09-02"],
        closes=[115.0, 98.0, 102.0],
        target_date="2026-08-03",
        target_direction="up",
    )
    row = score_chart_payload(payload)
    assert row["entry"] == 100.0
    assert row["return_since"] == 0.02
    assert row["runup"] == 0.15
    assert row["max_drawdown"] == -0.02
    assert row["outcome"] == "well_timed"
    assert row["days_to_target"] == 1


def test_verdict_mixed_no_terrible():
    verdict = verdict_from_counts(
        {
            "chart_count": 10,
            "well_timed": 3,
            "giveback": 2,
            "underwater": 4,
            "terrible": 0,
        }
    )
    assert verdict == VERDICT_MIXED_NO_TERRIBLE
    assert (
        verdict_from_counts({"chart_count": 4, "well_timed": 1, "terrible": 1, "giveback": 0})
        == VERDICT_HAS_TERRIBLE
    )


def test_run_writes_artifacts_and_slim_omits_rows(tmp_path: Path):
    chart_dir = tmp_path / "charts"
    chart_dir.mkdir()
    write_json(
        chart_dir / "AAA.L.json",
        _chart(
            ticker="AAA.L",
            closes=[101.0, 112.0, 111.0],
            target_date="2026-08-10",
            target_direction="up",
        ),
    )
    write_json(
        chart_dir / "BBB.L.json",
        _chart(
            ticker="BBB.L",
            signal="buy",
            closes=[99.0, 96.0, 94.0],
            target_date="2026-08-03",
            target_direction="up",
        ),
    )
    payload = run_chart_outcome_review(data_dir=tmp_path, chart_dir=chart_dir)
    assert (tmp_path / REVIEW_FILENAME).exists()
    assert (tmp_path / REVIEW_MD_FILENAME).exists()
    assert payload["verdict"] == VERDICT_MIXED_NO_TERRIBLE
    assert payload["counts"]["stop_hit"] == 0
    assert payload["counts"]["terrible"] == 0
    assert payload["counts"]["well_timed"] == 1
    assert payload["counts"]["giveback"] == 1
    slim = slim_chart_outcome_review(payload)
    assert slim is not None
    assert "rows" not in slim
    assert slim["observe_only"] is True
    assert slim["verdict"] == VERDICT_MIXED_NO_TERRIBLE
    assert slim["well_timed"][0]["ticker"] == "AAA.L"


def test_empty_chart_dir(tmp_path: Path):
    payload = build_chart_outcome_review(chart_dir=tmp_path / "missing")
    assert payload["verdict"] == "empty"
    assert payload["counts"]["chart_count"] == 0
