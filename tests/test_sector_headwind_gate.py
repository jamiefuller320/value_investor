"""Tests for the observe-only sector headwind gate."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from value_investor.operating_decline_gate import EPS_INTERIM_DROP_PCT
from value_investor.ops_monitor import check_sector_headwind_gate
from value_investor.sector_headwind_gate import (
    COVERAGE_GAP_TITLE,
    FINDING_TITLE,
    PRICE_BREADTH_HEADWIND,
    SCREEN_EARNINGS_GROWTH_DECLINE_PCT,
    assess_sector,
    ops_findings_from_sector_headwind_gate,
    refresh_sector_headwind_gate,
    sector_label_as_of,
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
    assert result["metrics"]["earnings_component"] == "screen_fields_fallback"
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


def test_material_screen_field_fallback_creates_headwind_at_thresholds():
    members = _members()
    members[0]["interim_eps_decline_pct"] = EPS_INTERIM_DROP_PCT
    members[1]["adjusted_eps_growth_pct"] = SCREEN_EARNINGS_GROWTH_DECLINE_PCT

    result = assess_sector(
        members,
        charts=_charts(members),
        decline_verdicts=None,
        as_of="2025-09-30",
    )

    assert result["verdict"] == "headwind"
    assert result["metrics"]["earnings_component"] == "screen_fields_fallback"
    assert result["metrics"]["earnings_declining_share"] == 0.5
    assert "EARNINGS_BREADTH_HEADWIND" in {row["code"] for row in result["reasons"]}


def test_screen_field_fallback_ignores_immaterial_changes():
    members = _members()
    members[0]["interim_eps_decline_pct"] = EPS_INTERIM_DROP_PCT - 0.001
    members[1]["yahoo_normalized_income_growth_pct"] = SCREEN_EARNINGS_GROWTH_DECLINE_PCT + 0.001
    members[2]["adjusted_eps_growth_pct"] = SCREEN_EARNINGS_GROWTH_DECLINE_PCT + 0.001

    result = assess_sector(
        members,
        charts=_charts(members),
        decline_verdicts=None,
        as_of="2025-09-30",
    )

    assert result["verdict"] == "sound"
    assert result["metrics"]["earnings_component"] == "screen_fields_fallback"
    assert result["metrics"]["earnings_declining_share"] == 0.0


def test_operating_decline_store_is_primary_earnings_component():
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
    assert result["metrics"]["earnings_component"] == "operating_decline_store"
    assert result["metrics"]["earnings_declining_share"] == 0.5
    assert result["metrics"]["operating_declining_share"] == 0.5
    assert "OPERATING_DECLINE_BREADTH_HEADWIND" in {row["code"] for row in result["reasons"]}
    assert "OPERATING_DECLINE_STORE_UNAVAILABLE" not in {row["code"] for row in result["reasons"]}


def test_store_primary_does_not_apply_raw_screen_proxy():
    members = _members()
    for member in members:
        member["interim_eps_decline_pct"] = 0.50
        member["yahoo_normalized_income_growth_pct"] = -0.50
    names = {row["ticker"]: {"verdict": "clear"} for row in members}

    result = assess_sector(
        members,
        charts=_charts(members),
        decline_verdicts={"names": names},
        as_of="2025-09-30",
    )

    assert result["verdict"] == "sound"
    assert result["metrics"]["earnings_component"] == "operating_decline_store"
    assert result["metrics"]["earnings_declining_share"] == 0.0
    assert result["metrics"]["earnings_fields_used"] == []
    assert "EARNINGS_BREADTH_HEADWIND" not in {row["code"] for row in result["reasons"]}


def test_thin_store_uses_screen_field_fallback_without_unavailable_reason():
    members = _members()
    members[0]["interim_eps_decline_pct"] = EPS_INTERIM_DROP_PCT
    members[1]["yahoo_normalized_income_growth_pct"] = SCREEN_EARNINGS_GROWTH_DECLINE_PCT
    names = {members[0]["ticker"]: {"verdict": "clear"}}

    result = assess_sector(
        members,
        charts=_charts(members),
        decline_verdicts={"names": names},
        as_of="2025-09-30",
    )

    codes = {row["code"] for row in result["reasons"]}
    assert result["verdict"] == "headwind"
    assert result["metrics"]["earnings_component"] == "screen_fields_fallback"
    assert "OPERATING_DECLINE_STORE_THIN_FALLBACK" in codes
    assert "OPERATING_DECLINE_STORE_UNAVAILABLE" not in codes


def test_insufficient_decline_verdicts_are_excluded_from_store_coverage():
    members = _members(5)
    names = {
        members[0]["ticker"]: {"verdict": "declining"},
        members[1]["ticker"]: {"verdict": "declining"},
        members[2]["ticker"]: {"verdict": "clear"},
        members[3]["ticker"]: {"verdict": "clear"},
        members[4]["ticker"]: {"verdict": "insufficient_data"},
    }

    result = assess_sector(
        members,
        charts=_charts(members),
        decline_verdicts={"names": names},
        as_of="2025-09-30",
    )

    assert result["verdict"] == "headwind"
    assert result["metrics"]["earnings_component"] == "operating_decline_store"
    assert result["metrics"]["operating_decline_member_count"] == 4
    assert result["metrics"]["operating_decline_coverage_share"] == 0.8
    assert result["metrics"]["earnings_declining_share"] == 0.5


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
    assert result["metrics"]["earnings_component"] == "screen_fields_fallback"
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
        market_status_path=tmp_path / "absent_status.json",
        library_root=tmp_path / "library",
        label_history_path=tmp_path / "labels.jsonl",
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
    assert (
        payload["sectors"]["ftse350:Industrials"]["metrics"]["earnings_component"]
        == "screen_fields_fallback"
    )
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
        "screen_date": "2025-09-30",
    }
    assert payload["universe"]["included"] == ["ftse350"]
    assert payload["universe"]["admitted_library_markets"] == []
    assert payload["names_by_market"]["ftse350"]["T0.L"]["sector_verdict"] == "sound"


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
        market_status_path=tmp_path / "absent_status.json",
        library_root=tmp_path / "library",
        label_history_path=tmp_path / "labels.jsonl",
    )

    assert store.is_file()
    assert findings[0].title == FINDING_TITLE
    assert findings[0].auto_fixable is False


def _write_signals(root: Path, market: str, rows: list[dict], *, run_at: str) -> None:
    screen = root / "markets" / market / "screen"
    screen.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (screen / "latest_signals.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (screen / "latest_summary.json").write_text(
        json.dumps({"market": market, "run_at": run_at}),
        encoding="utf-8",
    )


def _write_charts(chart_dir: Path, rows: list[dict], **kwargs) -> None:
    chart_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        ticker = row["ticker"]
        if not (chart_dir / f"{ticker}.json").is_file():
            (chart_dir / f"{ticker}.json").write_text(
                json.dumps(_chart(**kwargs)),
                encoding="utf-8",
            )


def _library_refresh(
    tmp_path: Path,
    *,
    markets: dict[str, list[dict]],
    graduated: list[str],
    charts: dict[str, dict] | None = None,
    decline: dict | None = None,
    skipped: list[str] | None = None,
    as_of: str | None = None,
    run_at: str = "2025-09-30T12:00:00+00:00",
    chart_kwargs: dict | None = None,
):
    library = tmp_path / "library"
    chart_dir = tmp_path / "charts"
    chart_dir.mkdir(exist_ok=True)
    for market, rows in markets.items():
        _write_signals(library, market, rows, run_at=run_at)
        if chart_kwargs is not None:
            _write_charts(chart_dir, rows, **chart_kwargs)
    if charts:
        for ticker, chart in charts.items():
            (chart_dir / f"{ticker}.json").write_text(json.dumps(chart), encoding="utf-8")
    status = {
        "markets": [
            *[{"market_id": market, "is_graduated": True} for market in graduated],
            *[{"market_id": market, "is_graduated": False} for market in skipped or []],
        ]
    }
    status_path = tmp_path / "market_status.json"
    status_path.write_text(json.dumps(status), encoding="utf-8")
    decline_path = tmp_path / "decline.json"
    if decline is not None:
        decline_path.write_text(json.dumps(decline), encoding="utf-8")
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps({"run_at": run_at, "reports": _members(sector="FTSE Only")}),
        encoding="utf-8",
    )
    for ticker, chart in _charts(_members(sector="FTSE Only")).items():
        (chart_dir / f"{ticker}.json").write_text(json.dumps(chart), encoding="utf-8")
    store = tmp_path / "gate.json"
    labels = tmp_path / "labels.jsonl"
    payload = refresh_sector_headwind_gate(
        latest_path=latest,
        charts_dir=chart_dir,
        decline_store=decline_path,
        store_path=store,
        market_status_path=status_path,
        library_root=library,
        label_history_path=labels,
        as_of=as_of,
    )
    return payload, labels


def test_library_sector_sound_uses_decline_store_inside_decision_date(tmp_path: Path):
    rows = _members(sector="Industrials")
    for row in rows:
        row["ticker"] = row["ticker"].replace(".L", ".AX")
    names = {row["ticker"]: {"verdict": "clear"} for row in rows}
    payload, _labels = _library_refresh(
        tmp_path,
        markets={"asx200": rows},
        graduated=["asx200"],
        decline={"as_of": "2025-10-05", "names": names},
        chart_kwargs={"start": 80.0, "end": 120.0, "sma": 100.0},
    )

    sector = payload["sectors"]["asx200:Industrials"]
    assert sector["verdict"] == "sound"
    assert sector["metrics"]["earnings_component"] == "operating_decline_store"
    assert sector["metrics"]["as_of"] == "2025-10-05"
    assert sector["screen_date"] == "2025-09-30"
    assert payload["summary"]["by_market"]["asx200"]["buy_tier_by_verdict"]["sound"] == 1
    assert "asx200" in payload["universe"]["admitted_library_markets"]
    assert payload["names_by_market"]["asx200"]["T0.AX"]["sector_verdict"] == "sound"
    assert "T0.AX" not in payload["names"]


def test_library_price_breadth_headwind(tmp_path: Path):
    rows = _members(sector="Energy")
    for row in rows:
        row["ticker"] = row["ticker"].replace(".L", ".DE")
    charts = _charts(rows, start=130.0, end=75.0, sma=100.0)
    charts[rows[-1]["ticker"]] = _chart(start=80.0, end=120.0, sma=100.0)
    names = {row["ticker"]: {"verdict": "clear"} for row in rows}
    payload, _labels = _library_refresh(
        tmp_path,
        markets={"dax": rows},
        graduated=["dax"],
        charts=charts,
        decline={"as_of": "2025-09-30", "names": names},
        as_of="2025-09-30",
    )

    sector = payload["sectors"]["dax:Energy"]
    assert sector["verdict"] == "headwind"
    assert sector["metrics"]["price_below_sma200_share"] >= PRICE_BREADTH_HEADWIND
    assert sector["metrics"]["sector_return_126d"] < -0.10
    assert "PRICE_BREADTH_AND_TREND_HEADWIND" in {row["code"] for row in sector["reasons"]}


def test_library_decline_breadth_headwind(tmp_path: Path):
    rows = _members(sector="Financials")
    for row in rows:
        row["ticker"] = row["ticker"].replace(".L", ".PA")
    names = {
        row["ticker"]: {"verdict": "declining" if index < 2 else "clear"}
        for index, row in enumerate(rows)
    }
    payload, _labels = _library_refresh(
        tmp_path,
        markets={"cac40": rows},
        graduated=["cac40"],
        decline={"as_of": "2025-09-30", "names": names},
        as_of="2025-09-30",
        chart_kwargs={"start": 80.0, "end": 120.0, "sma": 100.0},
    )

    sector = payload["sectors"]["cac40:Financials"]
    assert sector["verdict"] == "headwind"
    assert sector["metrics"]["earnings_component"] == "operating_decline_store"
    assert sector["metrics"]["earnings_declining_share"] == 0.5
    assert "OPERATING_DECLINE_BREADTH_HEADWIND" in {row["code"] for row in sector["reasons"]}


def test_library_insufficient_data_for_too_few_members_and_chart_coverage(tmp_path: Path):
    small = _members(3, sector="Utilities")
    for row in small:
        row["ticker"] = f"S{row['ticker']}"
    wide = _members(10, sector="Real Estate")
    for row in wide:
        row["ticker"] = f"W{row['ticker']}"
    wide_charts = {row["ticker"]: _chart() for row in wide[:5]}
    names = {row["ticker"]: {"verdict": "clear"} for row in [*small, *wide]}
    payload, _labels = _library_refresh(
        tmp_path,
        markets={"psi20": [*small, *wide]},
        graduated=["psi20"],
        charts={**_charts(small), **wide_charts},
        decline={"as_of": "2025-09-30", "names": names},
        as_of="2025-09-30",
    )

    assert payload["sectors"]["psi20:Utilities"]["verdict"] == "insufficient_data"
    assert payload["sectors"]["psi20:Real Estate"]["verdict"] == "insufficient_data"
    gaps = {
        row["sector"]: row["reasons"]
        for row in payload["summary"]["by_market"]["psi20"]["buy_tier_insufficient_data"]
    }
    assert "too few members" in gaps["Utilities"]
    assert "chart coverage" in gaps["Real Estate"]
    assert "chart history" in gaps["Real Estate"]


def test_non_graduated_market_is_not_scored(tmp_path: Path):
    rows = _members(sector="Industrials")
    payload, labels = _library_refresh(
        tmp_path,
        markets={"sp400": rows, "asx200": rows},
        graduated=["asx200"],
        skipped=["sp400"],
        decline={
            "as_of": "2025-09-30",
            "names": {row["ticker"]: {"verdict": "clear"} for row in rows},
        },
        as_of="2025-09-30",
        chart_kwargs={"start": 80.0, "end": 120.0},
    )

    assert "sp400:Industrials" not in payload["sectors"]
    assert "asx200:Industrials" in payload["sectors"]
    assert {"market": "sp400", "reason": "not_graduated"} in payload["universe"]["not_scored"]
    text = labels.read_text(encoding="utf-8")
    assert '"market":"sp400"' not in text
    assert '"market":"asx200"' in text


def test_ticker_in_two_markets_gets_two_verdicts(tmp_path: Path):
    shared = "SAP.DE"
    alpha = _members(sector="Industrials")
    beta = _members(sector="Energy")
    alpha[0]["ticker"] = shared
    beta[0]["ticker"] = shared
    for row in alpha[1:]:
        row["ticker"] = row["ticker"].replace(".L", ".DE")
    for row in beta[1:]:
        row["ticker"] = row["ticker"].replace(".L", ".PA")
    charts = _charts(alpha, start=80.0, end=120.0, sma=100.0)
    falling = _charts(beta, start=130.0, end=75.0, sma=100.0)
    falling[beta[-1]["ticker"]] = _chart(start=80.0, end=120.0, sma=100.0)
    charts.update(falling)
    names = {row["ticker"]: {"verdict": "clear"} for row in [*alpha, *beta]}
    payload, _labels = _library_refresh(
        tmp_path,
        markets={"dax": alpha, "euro_stoxx50": beta},
        graduated=["dax", "euro_stoxx50"],
        charts=charts,
        decline={"as_of": "2025-09-30", "names": names},
        as_of="2025-09-30",
    )

    assert payload["names_by_market"]["dax"][shared]["sector_verdict"] == "sound"
    assert payload["names_by_market"]["euro_stoxx50"][shared]["sector_verdict"] == "headwind"
    assert payload["names_by_market"]["dax"][shared]["sector"] == "Industrials"
    assert payload["names_by_market"]["euro_stoxx50"][shared]["sector"] == "Energy"


def test_library_point_in_time_ignores_later_chart_bars_and_decline_snapshot(tmp_path: Path):
    rows = _members(sector="Technology")
    for row in rows:
        row["ticker"] = row["ticker"].replace(".L", ".HK")
        row["yahoo_normalized_income_growth_pct"] = 0.10
    charts = {}
    for row in rows:
        chart = _chart(start=80.0, end=120.0, points=200, sma=100.0)
        chart["dates"].append("2026-01-02")
        chart["closes"].append(10.0)
        chart["sma200_series"].append(100.0)
        charts[row["ticker"]] = chart
    cutoff = _chart(points=200)["dates"][-1]
    payload, _labels = _library_refresh(
        tmp_path,
        markets={"hang_seng": rows},
        graduated=["hang_seng"],
        charts=charts,
        decline={
            "as_of": "2026-02-01",
            "names": {row["ticker"]: {"verdict": "declining"} for row in rows},
        },
        as_of=cutoff,
        run_at=f"{cutoff}T12:00:00+00:00",
    )

    sector = payload["sectors"]["hang_seng:Technology"]
    assert sector["verdict"] == "sound"
    assert sector["metrics"]["price_below_sma200_share"] == 0.0
    assert sector["metrics"]["sector_return_126d"] > 0
    assert sector["metrics"]["earnings_component"] == "screen_fields_fallback"
    assert "OPERATING_DECLINE_STORE_UNAVAILABLE" in {row["code"] for row in sector["reasons"]}


def test_sector_label_history_appends_only_changes_and_reads_as_of(tmp_path: Path):
    rows = _members(sector="Industrials")
    for row in rows:
        row["ticker"] = row["ticker"].replace(".L", ".SW")
    common = dict(
        markets={"smi": rows},
        graduated=["smi"],
        decline={
            "as_of": "2025-09-01",
            "names": {row["ticker"]: {"verdict": "clear"} for row in rows},
        },
        chart_kwargs={"start": 80.0, "end": 120.0},
    )
    payload, labels = _library_refresh(
        tmp_path, as_of="2025-09-01", run_at="2025-09-01T00:00:00+00:00", **common
    )
    first_lines = [line for line in labels.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(first_lines) == 4 + 4  # library names plus the FTSE fixture names
    assert payload["names_by_market"]["smi"]["T0.SW"]["sector"] == "Industrials"

    _library_refresh(tmp_path, as_of="2025-09-01", run_at="2025-09-01T00:00:00+00:00", **common)
    second_lines = [
        line for line in labels.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert second_lines == first_lines

    changed = [dict(row) for row in rows]
    changed[0]["sector"] = "Healthcare"
    _library_refresh(
        tmp_path,
        markets={"smi": changed},
        graduated=["smi"],
        decline=common["decline"],
        chart_kwargs=common["chart_kwargs"],
        as_of="2025-10-01",
        run_at="2025-10-01T00:00:00+00:00",
    )
    third_lines = [line for line in labels.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(third_lines) == len(first_lines) + 1
    latest = json.loads(third_lines[-1])
    assert latest["market"] == "smi"
    assert latest["ticker"] == "T0.SW"
    assert latest["sector"] == "Healthcare"
    assert latest["as_of"] == "2025-10-01"
    assert latest["screen_date"] == "2025-10-01"

    assert sector_label_as_of("smi", "T0.SW", "2025-08-01", path=labels) is None
    assert sector_label_as_of("smi", "T0.SW", "2025-09-15", path=labels) == "Industrials"
    assert sector_label_as_of("smi", "T0.SW", "2025-10-01", path=labels) == "Healthcare"
    assert sector_label_as_of("smi", "T1.SW", "2025-10-01", path=labels) == "Industrials"


def test_coverage_finding_names_library_markets_mostly_insufficient():
    payload = {
        "summary": {
            "markets": 2,
            "sectors": 4,
            "sound": 1,
            "headwind": 1,
            "insufficient_data": 2,
            "buy_tier_in_headwind_sector": 2,
        },
        "sectors": {
            "ftse350:Energy": {
                "market": "ftse350",
                "sector": "Energy",
                "verdict": "headwind",
                "buy_tier_members": ["A.L"],
            },
            "ftse350:Utilities": {
                "market": "ftse350",
                "sector": "Utilities",
                "verdict": "insufficient_data",
                "buy_tier_members": ["C.L"],
            },
            "aim:Mining": {
                "market": "aim",
                "sector": "Mining",
                "verdict": "insufficient_data",
                "buy_tier_members": ["M1"],
            },
            "aim:Software": {
                "market": "aim",
                "sector": "Software",
                "verdict": "insufficient_data",
                "buy_tier_members": ["M2"],
            },
            "aim:Banks": {
                "market": "aim",
                "sector": "Banks",
                "verdict": "sound",
                "buy_tier_members": ["M3"],
            },
        },
    }

    findings = ops_findings_from_sector_headwind_gate(payload)

    assert findings[1]["title"] == COVERAGE_GAP_TITLE
    assert "Utilities" in findings[1]["summary"]
    assert "aim (2/3)" in findings[1]["summary"]
    assert "Mining" not in findings[1]["summary"]
    assert findings[1]["auto_fixable"] is False
