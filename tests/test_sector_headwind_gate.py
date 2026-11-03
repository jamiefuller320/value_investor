"""Tests for the observe-only sector headwind gate."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from value_investor.ops_monitor import check_sector_headwind_gate
from value_investor.sector_headwind_gate import (
    COVERAGE_GAP_TITLE,
    FINDING_TITLE,
    PRICE_BREADTH_HEADWIND,
    assess_sector,
    ops_findings_from_sector_headwind_gate,
    refresh_sector_headwind_gate,
)


def _members(count: int = 4, *, sector: str = "Industrials") -> list[dict]:
    return [
        {
            "ticker": f"T{index}.L",
            "sector": sector,
            "signal": "buy" if index == 0 else "hold",
            "yahoo_normalized_income_growth_pct": 0.10,
        }
        for index in range(count)
    ]


def _chart(
    *,
    start: float = 80.0,
    end: float = 120.0,
    points: int = 260,
    sma: float = 100.0,
    start_day: date = date(2025, 1, 1),
) -> dict:
    step = (end - start) / (points - 1)
    return {
        "dates": [(start_day + timedelta(days=index)).isoformat() for index in range(points)],
        "closes": [start + step * index for index in range(points)],
        "sma200_series": [sma] * points,
    }


def _charts(members: list[dict], **kwargs) -> dict[str, dict]:
    return {row["ticker"]: _chart(**kwargs) for row in members}


def test_sound_sector_has_complete_price_and_earnings_coverage():
    members = _members()
    result = assess_sector(
        members,
        charts=_charts(members),
        decline_verdicts=None,
        as_of="2025-09-30",
    )

    assert result["verdict"] == "sound"
    assert result["metrics"]["price_below_sma200_share"] == 0.0
    assert result["metrics"]["sector_return_126d"] > 0
    assert result["metrics"]["earnings_declining_share"] == 0.0
    assert result["metrics"]["operating_decline_component_available"] is False
    assert {row["code"] for row in result["reasons"]} == {
        "NO_BROAD_HEADWIND",
        "OPERATING_DECLINE_STORE_UNAVAILABLE",
    }


def test_price_breadth_and_negative_126d_trend_create_headwind():
    members = _members()
    charts = _charts(members, start=130.0, end=75.0, sma=100.0)
    charts[members[-1]["ticker"]] = _chart(start=80.0, end=120.0, sma=100.0)

    result = assess_sector(
        members,
        charts=charts,
        decline_verdicts=None,
        as_of="2025-09-30",
    )

    assert result["verdict"] == "headwind"
    assert result["metrics"]["price_below_sma200_share"] >= PRICE_BREADTH_HEADWIND
    assert result["metrics"]["sector_return_126d"] < -0.10
    assert "PRICE_BREADTH_AND_TREND_HEADWIND" in {row["code"] for row in result["reasons"]}


def test_earnings_breadth_creates_headwind():
    members = _members()
    members[0]["interim_eps_decline_pct"] = 0.04
    members[1]["adjusted_eps_growth_pct"] = -0.02

    result = assess_sector(
        members,
        charts=_charts(members),
        decline_verdicts=None,
        as_of="2025-09-30",
    )

    assert result["verdict"] == "headwind"
    assert result["metrics"]["earnings_declining_share"] == 0.5
    assert "EARNINGS_BREADTH_HEADWIND" in {row["code"] for row in result["reasons"]}


def test_operating_decline_store_breadth_creates_headwind():
    members = _members()
    names = {
        row["ticker"]: {"verdict": "declining" if index < 2 else "clear"}
        for index, row in enumerate(members)
    }

    result = assess_sector(
        members,
        charts=_charts(members),
        decline_verdicts={"names": names},
        as_of="2025-09-30",
    )

    assert result["verdict"] == "headwind"
    assert result["metrics"]["operating_declining_share"] == 0.5
    assert "OPERATING_DECLINE_BREADTH_HEADWIND" in {row["code"] for row in result["reasons"]}


@pytest.mark.parametrize(
    ("members", "charts", "expected_code"),
    [
        (_members(3), {}, "TOO_FEW_SECTOR_MEMBERS"),
        (_members(), {}, "INSUFFICIENT_CORE_COVERAGE"),
    ],
)
def test_insufficient_data_for_too_few_members_or_missing_charts(
    members: list[dict],
    charts: dict[str, dict],
    expected_code: str,
):
    result = assess_sector(
        members,
        charts=charts,
        decline_verdicts=None,
        as_of="2025-09-30",
    )

    assert result["verdict"] == "insufficient_data"
    assert expected_code in {row["code"] for row in result["reasons"]}


def test_chart_points_after_as_of_are_ignored():
    members = _members()
    charts: dict[str, dict] = {}
    for member in members:
        chart = _chart(start=80.0, end=120.0, points=200, sma=100.0)
        chart["dates"].append("2026-01-02")
        chart["closes"].append(10.0)
        chart["sma200_series"].append(100.0)
        charts[member["ticker"]] = chart
    cutoff = _chart(points=200)["dates"][-1]

    result = assess_sector(
        members,
        charts=charts,
        decline_verdicts=None,
        as_of=cutoff,
    )

    assert result["verdict"] == "sound"
    assert result["metrics"]["price_below_sma200_share"] == 0.0
    assert result["metrics"]["sector_return_126d"] > 0


def test_absent_decline_store_is_cited_but_does_not_prevent_sound():
    members = _members()
    result = assess_sector(
        members,
        charts=_charts(members),
        decline_verdicts=None,
        as_of="2025-09-30",
    )

    assert result["verdict"] == "sound"
    assert "OPERATING_DECLINE_STORE_UNAVAILABLE" in {row["code"] for row in result["reasons"]}


def test_refresh_persists_store_shape_from_tmp_inputs(tmp_path: Path):
    members = _members()
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "run_at": "2025-09-30T12:00:00+00:00",
                "reports": members,
            }
        ),
        encoding="utf-8",
    )
    chart_dir = tmp_path / "charts"
    chart_dir.mkdir()
    for ticker, chart in _charts(members).items():
        (chart_dir / f"{ticker}.json").write_text(json.dumps(chart), encoding="utf-8")
    store = tmp_path / "sector_headwind_gate.json"

    payload = refresh_sector_headwind_gate(
        latest_path=latest,
        charts_dir=chart_dir,
        decline_store=tmp_path / "absent_decline.json",
        store_path=store,
    )
    written = json.loads(store.read_text(encoding="utf-8"))

    assert payload == written
    assert payload["schema_version"] == 1
    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    assert payload["summary"]["sectors"] == 1
    assert payload["summary"]["chart_file_coverage_share"] == 1.0
    assert payload["summary"]["buy_tier_names"] == 1
    assert payload["sectors"]["ftse350:Industrials"]["verdict"] == "sound"
    assert payload["sectors"]["ftse350:Industrials"]["members"] == [
        "T0.L",
        "T1.L",
        "T2.L",
        "T3.L",
    ]
    assert payload["names"]["T0.L"] == {
        "market": "ftse350",
        "sector": "Industrials",
        "sector_verdict": "sound",
    }


def test_findings_report_headwinds_and_buy_tier_coverage_gaps():
    payload = {
        "summary": {
            "sectors": 2,
            "sound": 0,
            "headwind": 1,
            "insufficient_data": 1,
            "buy_tier_in_headwind_sector": 2,
        },
        "sectors": {
            "ftse350:Energy": {
                "sector": "Energy",
                "verdict": "headwind",
                "buy_tier_members": ["A.L", "B.L"],
            },
            "ftse350:Utilities": {
                "sector": "Utilities",
                "verdict": "insufficient_data",
                "buy_tier_members": ["C.L"],
            },
        },
    }

    findings = ops_findings_from_sector_headwind_gate(payload)

    assert [row["title"] for row in findings] == [FINDING_TITLE, COVERAGE_GAP_TITLE]
    assert "Energy" in findings[0]["summary"]
    assert "2" in findings[0]["summary"]
    assert "Utilities" in findings[1]["summary"]
    assert all(row["auto_fixable"] is False for row in findings)


def test_ops_monitor_check_refreshes_tmp_store(tmp_path: Path):
    members = _members()
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps({"run_at": "2025-09-30", "reports": members}),
        encoding="utf-8",
    )
    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    for ticker, chart in _charts(members).items():
        (charts_dir / f"{ticker}.json").write_text(json.dumps(chart), encoding="utf-8")
    store = tmp_path / "gate.json"

    findings = check_sector_headwind_gate(
        latest_path=latest,
        charts_dir=charts_dir,
        decline_store=tmp_path / "missing.json",
        store_path=store,
    )

    assert store.is_file()
    assert findings[0].title == FINDING_TITLE
    assert findings[0].auto_fixable is False
