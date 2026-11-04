"""Tests for report-only channel columns (N254)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from value_investor.channel_diagnostics import (
    CHANNEL_DIAGNOSTICS_VERSION,
    CHART_HL_COMPLETE_TITLE,
    CHART_HL_INCOMPLETE_TITLE,
    channel_columns,
    channel_columns_from_chart,
    chart_high_low_coverage,
    ops_findings_from_chart_high_low_coverage,
)
from value_investor.storage import write_json


def _dates(n: int) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-11-01", periods=n)]


def _rising(n: int, *, drift: float = 0.0008, wiggle: float = 0.01) -> list[float]:
    return [100.0 * math.exp(drift * i + wiggle * math.sin(i / 3.0)) for i in range(n)]


def test_rising_channel_reads_rising_and_context_needs_a_year():
    closes = _rising(200)
    out = channel_columns(_dates(200), closes, as_of="2030-01-01")
    assert out["channel_version"] == CHANNEL_DIAGNOSTICS_VERSION
    assert out["channel_status"] == "ok"
    assert out["ch126_status"] == "ok"
    assert out["ch126_direction"] == "rising"
    assert 15 < out["ch126_slope_pct_yr"] < 30
    assert out["ch252_status"] == "insufficient_history"
    assert out["hl_basis"] == "closes"


def test_drop_below_the_lower_band_is_bucketed():
    closes = _rising(300)
    closes[-1] = closes[-2] * 0.85
    out = channel_columns(_dates(300), closes, as_of="2030-01-01")
    assert out["ch126_bucket"] == "below_lower"
    assert out["ch126_z"] <= -2
    assert out["ch252_status"] == "ok"
    assert out["bb20_pct_b"] < 0


def test_later_bars_do_not_change_the_columns():
    dates = _dates(320)
    closes = _rising(320)
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    as_of = dates[280]
    before = channel_columns(dates, closes, highs, lows, as_of=as_of)
    for k in range(281, 320):
        closes[k] *= 0.5
        highs[k] *= 0.5
        lows[k] *= 0.5
    after = channel_columns(dates, closes, highs, lows, as_of=as_of)
    assert before == after
    assert before["channel_as_of"] == as_of
    assert before["bars"] == 281


def test_donchian_uses_prior_sessions_and_highs_lows():
    n = 60
    closes = [100.0] * n
    highs = [101.0] * n
    lows = [99.0] * n
    lows[-1] = 97.0
    closes[-1] = 98.0
    out = channel_columns(_dates(n), closes, highs, lows, as_of="2030-01-01")
    assert out["hl_basis"] == "high_low"
    assert out["dc20_new_low"] is True
    assert out["dc20_new_high"] is False
    assert out["dc20_pos"] < 0
    assert out["dc55_new_low"] is True


def test_support_line_through_rising_swing_lows_breaks_on_a_close_below():
    n = 130
    base = np.full(n, 110.0)
    base[40] = 100.0
    base[90] = 104.0
    closes = list(base)
    lows = list(base)
    highs = [v + 1 for v in base]
    # Support through (40, 100) and (90, 104) projects to about 107.1 at bar 129.
    closes[-1] = lows[-1] = 106.0
    out = channel_columns(_dates(n), closes, highs, lows, as_of="2030-01-01")
    assert out["support_slope"] == "rising"
    assert out["support_broken"] is True
    assert out["support_dist_pct"] < 0


def test_missing_highs_lows_fall_back_to_closes_and_say_so():
    closes = _rising(60)
    highs = [None] * 30 + [c * 1.01 for c in closes[30:]]
    lows = [None] * 30 + [c * 0.99 for c in closes[30:]]
    out = channel_columns(_dates(60), closes, highs, lows, as_of="2030-01-01")
    assert out["hl_basis"] == "partial"
    assert channel_columns(_dates(5), [1, 2, 3, 4, 5], as_of="2000-01-01") == {
        "channel_version": CHANNEL_DIAGNOSTICS_VERSION,
        "channel_status": "no_bar_on_or_before_as_of",
    }


def test_chart_payload_entry_point():
    payload = {"dates": _dates(140), "closes": _rising(140)}
    out = channel_columns_from_chart(payload, as_of="2030-01-01")
    assert out["ch126_status"] == "ok"
    assert out["hl_basis"] == "closes"


def test_high_low_coverage_finding(tmp_path: Path):
    write_json(
        tmp_path / "A.json",
        {"dates": ["d1", "d2"], "closes": [1, 2], "highs": [1, 2], "lows": [1, 2]},
        compact=True,
    )
    write_json(tmp_path / "B.json", {"dates": ["d1", "d2"], "closes": [1, 2]}, compact=True)
    coverage = chart_high_low_coverage(tmp_path)
    assert coverage == {"charts": 2, "with_high_low": 1}
    (finding,) = ops_findings_from_chart_high_low_coverage(coverage)
    assert finding["title"] == CHART_HL_INCOMPLETE_TITLE
    assert finding["severity"] == "warn"
    (done,) = ops_findings_from_chart_high_low_coverage({"charts": 20, "with_high_low": 19})
    assert done["title"] == CHART_HL_COMPLETE_TITLE
    assert ops_findings_from_chart_high_low_coverage({"charts": 0}) == []


def test_ops_monitor_check_is_observe_only(tmp_path: Path):
    from value_investor.ops_monitor import check_chart_high_low_coverage

    write_json(tmp_path / "B.json", {"dates": ["d1"], "closes": [1]}, compact=True)
    (finding,) = check_chart_high_low_coverage(chart_dir=tmp_path)
    assert finding.auto_fixable is False
    assert finding.title == CHART_HL_INCOMPLETE_TITLE
    assert check_chart_high_low_coverage(chart_dir=tmp_path / "missing") == []
