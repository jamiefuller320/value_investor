"""Tests for signal stability and conviction."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.signal_stability import (
    compute_stability,
    conviction_score,
    enrich_signals_with_stability,
    ensure_signal_history,
    publish_committed_signal_history,
    refresh_dashboard_report_stability,
    signal_history_from_run_snapshots,
)
from value_investor.storage import write_json


def test_conviction_increases_with_persistence():
    low = conviction_score(
        blended_composite=0.8,
        families_passed=3,
        family_count=5,
        data_quality_score=0.9,
        weeks_at_signal=1,
    )
    high = conviction_score(
        blended_composite=0.8,
        families_passed=3,
        family_count=5,
        data_quality_score=0.9,
        weeks_at_signal=4,
    )
    assert high > low


def test_compute_stability_detects_persistent_signal():
    history = pd.DataFrame(
        [
            {
                "run_at": "2026-06-10T07:00:00+00:00",
                "ticker": "AAA.L",
                "signal": "strong_buy",
                "signal_rank": 4,
                "conviction_score": 0.7,
                "data_quality_score": 0.8,
            },
            {
                "run_at": "2026-06-17T07:00:00+00:00",
                "ticker": "AAA.L",
                "signal": "strong_buy",
                "signal_rank": 4,
                "conviction_score": 0.72,
                "data_quality_score": 0.8,
            },
        ]
    )
    info = compute_stability(
        history,
        ticker="AAA.L",
        current_signal="strong_buy",
        current_rank=4,
        blended_composite=0.8,
        families_passed=3,
        family_count=5,
        data_quality_score=0.85,
        current_run_at=datetime(2026, 6, 24, 7, 0, tzinfo=UTC),
    )
    assert info.weeks_at_signal >= 2
    assert info.signal_trend == "stable"
    assert info.stability_label in ("building", "persistent")
    assert info.signal_since == "2026-06-10"


def test_enrich_signals_adds_conviction_columns():
    signals = pd.DataFrame(
        [
            {
                "ticker": "AAA.L",
                "signal": "buy",
                "signal_rank": 3,
                "composite_score": 0.7,
                "sector_composite_score": 0.75,
                "families_passed": 2,
                "family_count": 5,
                "data_quality_score": 0.8,
            }
        ]
    )
    history = pd.DataFrame(
        columns=[
            "run_at",
            "ticker",
            "signal",
            "signal_rank",
            "conviction_score",
            "data_quality_score",
        ]
    )
    out = enrich_signals_with_stability(
        signals,
        history,
        run_at=datetime(2026, 7, 8, 7, 0, tzinfo=UTC),
    )
    assert "conviction_score" in out.columns
    assert "stability_label" in out.columns
    assert "signal_since" in out.columns
    assert out.iloc[0]["stability_label"] == "new"


def test_ensure_signal_history_backfills_from_snapshots(tmp_path: Path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    write_json(
        history_dir / "run_20260610_070000.json",
        {
            "run_at": "2026-06-10T07:00:00+00:00",
            "prices": {},
            "signals": [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "conviction_score": 0.5,
                    "data_quality_score": 0.9,
                }
            ],
        },
        compact=True,
    )
    write_json(
        history_dir / "run_20260617_070000.json",
        {
            "run_at": "2026-06-17T07:00:00+00:00",
            "prices": {},
            "signals": [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "conviction_score": 0.55,
                    "data_quality_score": 0.9,
                }
            ],
        },
        compact=True,
    )

    output_dir = tmp_path / "output"
    stats = ensure_signal_history(
        output_dir,
        committed_path=tmp_path / "missing.csv",
        history_dir=history_dir,
        committed_history_dir=tmp_path / "missing_hist",
    )
    assert stats["source"] == "snapshots"
    assert stats["rows"] == 2
    frame = signal_history_from_run_snapshots(history_dir)
    assert len(frame) == 2
    assert set(frame["ticker"]) == {"AAA.L"}

    publish_committed_signal_history(output_dir, committed_path=tmp_path / "docs_signal.csv")
    assert (tmp_path / "docs_signal.csv").exists()


def test_refresh_dashboard_report_stability_fixes_new_labels():
    history = pd.DataFrame(
        [
            {
                "run_at": "2026-06-10T07:00:00+00:00",
                "ticker": "AAA.L",
                "signal": "strong_buy",
                "signal_rank": 4,
                "conviction_score": 0.4,
                "data_quality_score": 1.0,
            },
            {
                "run_at": "2026-06-17T07:00:00+00:00",
                "ticker": "AAA.L",
                "signal": "strong_buy",
                "signal_rank": 4,
                "conviction_score": 0.4,
                "data_quality_score": 1.0,
            },
            {
                "run_at": "2026-06-24T07:00:00+00:00",
                "ticker": "AAA.L",
                "signal": "strong_buy",
                "signal_rank": 4,
                "conviction_score": 0.4,
                "data_quality_score": 1.0,
            },
        ]
    )
    reports = [
        {
            "ticker": "AAA.L",
            "signal": "strong_buy",
            "families_passed": 5,
            "family_count": None,
            "composite_score": 0.8,
            "sector_composite_score": 0.8,
            "data_quality_score": 1.0,
            "weeks_at_signal": 1,
            "stability_label": "new",
            "summary": (
                "Strong Buy (15/22 models). Families: 5/4 (cheapness, quality, "
                "dividend, GARP, risk). Conviction 40% (new, 1w at signal, new)."
            ),
        }
    ]
    out = refresh_dashboard_report_stability(
        reports,
        history,
        run_at=datetime(2026, 7, 1, 7, 0, tzinfo=UTC),
    )
    assert out[0]["stability_label"] == "persistent"
    assert out[0]["weeks_at_signal"] >= 4
    assert out[0]["family_count"] == 5
    assert "Families: 5/5 (" in out[0]["summary"]
    assert "persistent" in out[0]["summary"]
