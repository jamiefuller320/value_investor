"""Tests for hourly index stress features."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from value_investor.index_stress import label_daily_stress
from value_investor.index_stress_intraday import (
    aggregate_hourly_daily_features,
    intraday_stress_triggers,
    merge_intraday_into_daily_decisions,
    persist_intraday_bars,
)


def _hourly_day(day: date, *, crash_hour: int = 10, crash_pct: float = -0.02) -> list[dict]:
    bars: list[dict] = []
    price = 8000.0
    for hour in range(9, 17):
        ts = datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)
        if hour == crash_hour:
            price *= 1 + crash_pct
        else:
            price *= 1.0002
        bars.append(
            {
                "ts": ts.isoformat(),
                "date": day.isoformat(),
                "open": price,
                "close": price,
                "symbol": "^FTSE",
            }
        )
    return bars


def test_intraday_stress_triggers_on_hourly_drop():
    day = date(2026, 1, 15)
    features = aggregate_hourly_daily_features(_hourly_day(day, crash_pct=-0.02))
    triggers = intraday_stress_triggers(features[day.isoformat()], abs_1h=-0.015)
    assert triggers


def test_merge_intraday_flags_day_not_stressed_on_daily_close():
    daily = label_daily_stress(
        [
            {"date": "2026-01-14", "close": 8000.0},
            {"date": "2026-01-15", "close": 7980.0},
        ]
    )
    hourly_features = aggregate_hourly_daily_features(_hourly_day(date(2026, 1, 15), crash_pct=-0.02))
    merged = merge_intraday_into_daily_decisions(
        daily,
        hourly_features,
        abs_1h=-0.015,
        abs_session=None,
    )
    day15 = next(row for row in merged if row.date == "2026-01-15")
    assert day15.stressed is True


def test_persist_intraday_bars_round_trip(tmp_path: Path):
    bars = _hourly_day(date(2026, 1, 15))
    path = persist_intraday_bars(symbol="^FTSE", hourly_bars=bars, root=tmp_path)
    payload = path.read_text(encoding="utf-8")
    assert "ftse_1h.json" in str(path)
    assert "2026-01-15" in payload
