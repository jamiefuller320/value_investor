"""Tests for buy-tier price chart payloads."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.price_charts import (
    build_price_chart_payload,
    chart_filename,
    copy_charts_to_dashboard,
    ensure_buy_tier_charts,
    first_level_crossings,
    levels_from_trade_plan,
    write_buy_tier_charts_from_history,
)
from value_investor.storage import write_json


def _series(start: float = 100.0, days: int = 220) -> pd.Series:
    index = pd.date_range("2025-01-01", periods=days, freq="B")
    values = [start + (i % 17) - 8 for i in range(days)]
    return pd.Series(values, index=index)


def test_build_price_chart_payload_includes_levels():
    series = _series()
    payload = build_price_chart_payload(
        ticker="AAA.L",
        name="Alpha",
        series=series,
        signal="strong_buy",
        signal_since="2025-06-15",
        as_of=datetime(2025, 6, 15, tzinfo=UTC),
        snapshot_dirs=[],
        trade_plan={
            "core_limit": 98.0,
            "tactical_limit": 95.0,
            "tactical_stop_loss": 90.0,
            "tactical_take_profit": 110.0,
        },
    )
    assert payload is not None
    assert payload["ticker"] == "AAA.L"
    assert len(payload["dates"]) == len(payload["closes"])
    assert payload["levels"]["tactical_limit"] == 95.0
    assert payload["levels"]["stop_loss"] == 90.0
    assert payload["levels"]["take_profit"] == 110.0
    assert payload["levels"]["last"] == payload["closes"][-1]
    assert payload["signal_since"] == "2025-06-15"
    assert payload["levels_as_of"]
    assert payload["initial_levels"] is not None
    assert payload["initial_levels_as_of"] == "2025-06-15"
    assert isinstance(payload["level_crossings"], list)


def test_write_buy_tier_charts_from_history(tmp_path: Path):
    signals = pd.DataFrame(
        [
            {
                "ticker": "AAA.L",
                "name": "Alpha",
                "signal": "strong_buy",
                "core_limit": 98.0,
                "tactical_limit": 95.0,
                "tactical_stop_loss": 90.0,
                "tactical_take_profit": 110.0,
            },
            {
                "ticker": "BBB.L",
                "name": "Beta",
                "signal": "hold",
            },
        ]
    )
    history = {"AAA.L": _series(), "BBB.L": _series(80)}
    written = write_buy_tier_charts_from_history(
        signals=signals,
        history=history,
        chart_dir=tmp_path / "charts",
    )
    assert len(written) == 1
    assert written[0].name == "AAA.L.json"
    assert written[0].exists()


def test_copy_charts_to_dashboard_filters_tickers(tmp_path: Path):
    source = tmp_path / "output_charts"
    dest = tmp_path / "docs" / "data" / "charts"
    source.mkdir(parents=True)
    (source / "AAA.L.json").write_text('{"ticker":"AAA.L"}', encoding="utf-8")
    (source / "BBB.L.json").write_text('{"ticker":"BBB.L"}', encoding="utf-8")
    paths = copy_charts_to_dashboard(source_dir=source, dest_dir=dest, tickers=["AAA.L"])
    assert paths == ["data/charts/AAA.L.json"]
    assert (dest / "AAA.L.json").exists()
    assert not (dest / "BBB.L.json").exists()


def test_ensure_buy_tier_charts_skips_fetch_when_present(tmp_path: Path):
    chart_dir = tmp_path / "charts"
    chart_dir.mkdir()
    path = chart_dir / chart_filename("AAA.L")
    path.write_text('{"ticker":"AAA.L"}', encoding="utf-8")
    written = ensure_buy_tier_charts(
        reports=[{"ticker": "AAA.L", "signal": "strong_buy", "name": "Alpha"}],
        chart_dir=chart_dir,
        fetch=False,
    )
    assert written == [path]


def test_levels_from_trade_plan_reads_legacy_keys():
    levels = levels_from_trade_plan({"stop_loss": 90.0, "take_profit": 110.0}, last=100.0)
    assert levels["stop_loss"] == 90.0
    assert levels["take_profit"] == 110.0
    assert levels["last"] == 100.0


def test_first_level_crossings_records_first_touch_after_since():
    dates = ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]
    closes = [100.0, 99.0, 94.0, 111.0]
    rows = first_level_crossings(
        dates,
        closes,
        {"stop_loss": 95.0, "take_profit": 110.0, "core_limit": 98.0},
        since="2026-08-02",
    )
    by_key = {row["key"]: row for row in rows}
    assert by_key["stop_loss"]["date"] == "2026-08-03"
    assert by_key["stop_loss"]["direction"] == "down"
    assert by_key["take_profit"]["date"] == "2026-08-04"
    assert by_key["take_profit"]["direction"] == "up"
    assert by_key["core_limit"]["date"] == "2026-08-03"


def test_build_payload_uses_archived_initial_levels(tmp_path: Path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    write_json(
        history_dir / "run_20250616_070000.json",
        {
            "run_at": "2025-06-16T07:00:00+00:00",
            "prices": {},
            "signals": [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "core_limit": 91.0,
                    "tactical_limit": 88.0,
                    "tactical_stop_loss": 80.0,
                    "tactical_take_profit": 120.0,
                }
            ],
        },
        compact=True,
    )
    payload = build_price_chart_payload(
        ticker="AAA.L",
        name="Alpha",
        series=_series(),
        signal="strong_buy",
        signal_since="2025-06-15",
        trade_plan={
            "core_limit": 98.0,
            "tactical_limit": 95.0,
            "tactical_stop_loss": 90.0,
            "tactical_take_profit": 110.0,
        },
        snapshot_dirs=[history_dir],
    )
    assert payload is not None
    assert payload["levels"]["core_limit"] == 98.0
    assert payload["initial_levels"]["core_limit"] == 91.0
    assert payload["initial_levels"]["stop_loss"] == 80.0
    assert payload["initial_levels_as_of"] == "2025-06-16"
    assert payload["initial_levels"]["sma50"] is not None
