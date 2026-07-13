"""Tests for buy-tier price chart payloads."""

from pathlib import Path

import pandas as pd

from value_investor.price_charts import (
    build_price_chart_payload,
    chart_filename,
    copy_charts_to_dashboard,
    ensure_buy_tier_charts,
    levels_from_trade_plan,
    write_buy_tier_charts_from_history,
)


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
