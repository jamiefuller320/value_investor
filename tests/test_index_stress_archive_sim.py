"""Tests for index stress detection and archive simulation."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from value_investor.backtest import HISTORY_DIR
from value_investor.index_stress import (
    IndexStressDecision,
    IndexStressThresholds,
    enrich_daily_bars,
    evaluate_index_stress_row,
    label_daily_stress,
    weekly_proxy_stress,
)
from value_investor.index_stress_archive_sim import (
    COHORTS_FILENAME,
    REVIEW_FILENAME,
    IndexStressArchiveConfig,
    replay_stop_counterfactual,
    run_index_stress_archive_sim,
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


def _synthetic_crash_bars(start: date, days: int = 30) -> list[dict]:
    bars: list[dict] = []
    close = 8000.0
    for offset in range(days):
        day = start + timedelta(days=offset)
        if offset == 15:
            close *= 0.94
        elif offset > 15:
            close *= 1.002
        else:
            close *= 1.0005
        bars.append({"date": day.isoformat(), "close": round(close, 2)})
    return bars


def test_evaluate_index_stress_row_flags_large_1d_move():
    thresholds = IndexStressThresholds(abs_1d=-0.03)
    enriched = enrich_daily_bars(
        [
            {"date": "2026-01-01", "close": 8000.0},
            {"date": "2026-01-02", "close": 7720.0},
        ],
        thresholds=thresholds,
    )
    decision = evaluate_index_stress_row(enriched[-1], thresholds=thresholds)
    assert decision.stressed is True
    assert any("abs_1d" in trigger for trigger in decision.triggers)


def test_weekly_proxy_stress_fallback():
    decision = weekly_proxy_stress(index_return=-0.06)
    assert decision.stressed is True


def test_label_daily_stress_marks_crash_day():
    bars = _synthetic_crash_bars(date(2026, 1, 1), days=25)
    decisions = label_daily_stress(bars)
    assert any(row.stressed for row in decisions)


def test_replay_stop_counterfactual_counts_stress_window_hits():
    buy_row = {
        "ticker": "AAA.L",
        "signal": "strong_buy",
        "conviction_score": 0.8,
        "tactical_stop_loss": 95.0,
    }
    snap_a = {
        "run_at": "2026-01-01T10:00:00+00:00",
        "prices": {"AAA.L": 100.0, "^FTSE": 8000.0},
        "signals": [buy_row],
    }
    snap_b = {
        "run_at": "2026-01-08T10:00:00+00:00",
        "prices": {"AAA.L": 90.0, "^FTSE": 7600.0},
        "signals": [buy_row],
    }
    from value_investor.backtest import RunSnapshot

    snapshots = [RunSnapshot.from_dict(snap_a), RunSnapshot.from_dict(snap_b)]
    stress_map = {
        "2026-01-05": IndexStressDecision(
            date="2026-01-05",
            stressed=True,
            triggers=["abs_1d<=-3.0%"],
        )
    }
    replay = replay_stop_counterfactual(
        snapshots,
        stress_decisions_by_date=stress_map,
        thresholds=IndexStressThresholds(),
        use_daily_stress=True,
    )
    assert replay["stop_hits_total"] == 1
    assert replay["counterfactual_sells_avoided"] == 1


def test_run_index_stress_archive_sim_writes_artifacts(tmp_path: Path):
    buy_row = {
        "ticker": "AAA.L",
        "signal": "buy",
        "conviction_score": 0.7,
        "tactical_stop_loss": 95.0,
    }
    _write_history_snapshot(
        tmp_path,
        "run_20260101_100000.json",
        "2026-01-01T10:00:00+00:00",
        {"AAA.L": 100.0, "^FTSE": 8000.0},
        [buy_row],
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260108_100000.json",
        "2026-01-08T10:00:00+00:00",
        {"AAA.L": 94.0, "^FTSE": 7700.0},
        [buy_row],
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260115_100000.json",
        "2026-01-15T10:00:00+00:00",
        {"AAA.L": 98.0, "^FTSE": 7800.0},
        [buy_row],
    )

    def fake_fetch(symbol: str, start: date, end: date) -> list[dict]:
        return _synthetic_crash_bars(start, days=max(10, (end - start).days + 5))

    review = run_index_stress_archive_sim(
        tmp_path,
        config=IndexStressArchiveConfig(),
        fetch_daily_bars=fake_fetch,
    )
    assert (tmp_path / COHORTS_FILENAME).exists()
    assert (tmp_path / REVIEW_FILENAME).exists()
    assert review.get("snapshot_count") == 3
    assert (review.get("primary_replay") or {}).get("windows") == 2
    assert review.get("threshold_sweep")
