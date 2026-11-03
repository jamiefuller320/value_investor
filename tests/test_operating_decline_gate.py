"""Tests for the observe-only operating-decline gate (N250)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from value_investor.operating_decline_gate import (
    COVERAGE_GAP_TITLE,
    FINDING_TITLE,
    assess_operating_decline,
    format_operating_decline_text,
    ops_findings_from_operating_decline_gate,
    refresh_operating_decline_gate,
)

AS_OF = "2026-11-03"


def _financials(
    revenue: dict[str, float],
    operating: dict[str, float] | None = None,
    eps: dict[str, float] | None = None,
    fcf: dict[str, float] | None = None,
    *,
    fetched_at: str = "2026-10-20T00:00:00+00:00",
) -> dict:
    years = sorted(revenue, reverse=True)
    income = {y: {"Total Revenue": revenue[y]} for y in years}
    for y, v in (operating or {}).items():
        income[y]["Operating Income"] = v
    for y, v in (eps or {}).items():
        income.setdefault(y, {})["Diluted EPS"] = v
    cash_flow = {y: {"Free Cash Flow": v} for y, v in (fcf or {}).items()}
    return {"fetched_at": fetched_at, "income_statement": income, "cash_flow": cash_flow}


def _healthy() -> dict:
    return _financials(
        {"2025": 1100.0, "2024": 1000.0, "2023": 950.0},
        operating={"2025": 165.0, "2024": 150.0, "2023": 140.0},
        eps={"2025": 1.2, "2024": 1.0},
        fcf={"2025": 120.0, "2024": 100.0},
    )


def _filing(headline: str, published_at: str, fid: str = "f1") -> dict:
    return {"id": fid, "headline": headline, "summary": headline, "published_at": published_at}


def _raw(income: dict, cash_flow: dict | None = None) -> dict:
    return {
        "fetched_at": "2026-10-20T00:00:00+00:00",
        "income_statement": income,
        "cash_flow": cash_flow or {},
    }


def _codes(result: dict) -> list[str]:
    return [r["code"] for r in result["reasons"]]


def _assess(row=None, financials=None, filings=None, as_of=AS_OF):
    return assess_operating_decline(
        row if row is not None else {},
        financials if financials is not None else _healthy(),
        filings,
        as_of=as_of,
    )


def test_clear_when_all_trends_healthy():
    result = _assess(
        row={"interim_dividend_cut_flagged": False},
        filings=[_filing("Full year results", "2026-09-01")],
    )
    assert result["verdict"] == "clear"
    assert result["reasons"] == []
    assert set(result["checks"]) == {
        "revenue",
        "operating_margin",
        "eps_annual",
        "eps_interim",
        "fcf",
        "dividend",
        "profit_warning",
    }
    assert result["checks"]["revenue"]["evaluable"] is True
    assert result["checks"]["eps_interim"]["evaluable"] is False


def test_revenue_drop_beyond_threshold_is_declining():
    fin = _financials(
        {"2025": 900.0, "2024": 1000.0, "2023": 950.0},
        operating={"2025": 135.0, "2024": 150.0},
    )
    result = _assess(financials=fin)
    assert result["verdict"] == "declining"
    assert "revenue_decline" in _codes(result)
    assert "revenue_two_year_decline" not in _codes(result)


def test_two_consecutive_small_revenue_declines_are_declining():
    fin = _financials(
        {"2025": 970.0, "2024": 990.0, "2023": 1010.0},
        operating={"2025": 145.0, "2024": 149.0},
    )
    result = _assess(financials=fin)
    assert result["verdict"] == "declining"
    assert _codes(result) == ["revenue_two_year_decline"]


def test_flat_revenue_noise_is_not_a_decline():
    fin = _financials(
        {"2025": 998.0, "2024": 1000.0, "2023": 1001.0},
        operating={"2025": 150.0, "2024": 150.0},
    )
    assert _assess(financials=fin)["verdict"] == "clear"


def test_operating_margin_drop_is_declining():
    fin = _financials(
        {"2025": 1000.0, "2024": 1000.0},
        operating={"2025": 100.0, "2024": 150.0},
    )
    result = _assess(financials=fin)
    assert result["verdict"] == "declining"
    assert _codes(result) == ["operating_margin_drop"]
    assert result["checks"]["operating_margin"]["change_pp"] == pytest.approx(-0.05)


def test_fcf_turning_negative_is_declining():
    fin = _financials(
        {"2025": 1100.0, "2024": 1000.0},
        operating={"2025": 165.0, "2024": 150.0},
        fcf={"2025": -20.0, "2024": 80.0},
    )
    result = _assess(financials=fin)
    assert result["verdict"] == "declining"
    assert _codes(result) == ["fcf_turned_negative"]


def test_single_soft_signal_stays_clear_but_is_cited():
    fin = _financials(
        {"2025": 1100.0, "2024": 1000.0},
        operating={"2025": 165.0, "2024": 150.0},
        eps={"2025": 0.5, "2024": 1.0},
    )
    result = _assess(financials=fin)
    assert result["verdict"] == "clear"
    assert _codes(result) == ["eps_decline_annual"]


def test_two_soft_signals_are_declining():
    fin = _financials(
        {"2025": 1100.0, "2024": 1000.0},
        operating={"2025": 165.0, "2024": 150.0},
        eps={"2025": 0.5, "2024": 1.0},
    )
    result = _assess(row={"interim_dividend_cut_flagged": True}, financials=fin)
    assert result["verdict"] == "declining"
    assert set(_codes(result)) == {"eps_decline_annual", "dividend_cut"}


def test_interim_eps_decline_counts_as_soft_signal():
    row = {"interim_eps_decline_pct": 0.31}
    result = _assess(row=row)
    assert result["verdict"] == "clear"
    assert _codes(result) == ["eps_decline_interim"]
    result = _assess(row={"interim_eps_decline_pct": 0.31, "interim_dividend_cut_flagged": True})
    assert result["verdict"] == "declining"
    assert _assess(row={"interim_eps_decline_pct": 0.04})["reasons"] == []


def test_sharp_fcf_fall_is_soft():
    fin = _financials(
        {"2025": 1100.0, "2024": 1000.0},
        operating={"2025": 165.0, "2024": 150.0},
        fcf={"2025": 30.0, "2024": 100.0},
    )
    result = _assess(financials=fin)
    assert result["verdict"] == "clear"
    assert _codes(result) == ["fcf_sharp_fall"]


@pytest.mark.parametrize(
    "headline",
    [
        "Profit warning",
        "Board cuts guidance for FY26",
        "Trading update: full year profit below expectations",
    ],
)
def test_profit_warning_headline_is_declining(headline):
    result = _assess(filings=[_filing(headline, "2026-09-15", "w1")])
    assert result["verdict"] == "declining"
    assert _codes(result) == ["profit_warning"]
    assert result["reasons"][0]["source"] == "filings_index.json:w1"


def test_plain_trading_update_is_not_a_warning():
    result = _assess(filings=[_filing("Q3 Trading Update", "2026-10-20")])
    assert result["verdict"] == "clear"
    assert result["checks"]["profit_warning"]["scanned_items"] == 1


def test_impairment_headline_alone_is_soft():
    result = _assess(filings=[_filing("Impairment of goodwill", "2026-10-01")])
    assert result["verdict"] == "clear"
    assert _codes(result) == ["impairment_or_downgrade"]


def test_profit_warning_dated_after_as_of_is_ignored():
    filings = [_filing("Profit warning", "2026-11-10", "late")]
    result = _assess(filings=filings, as_of="2026-11-03")
    assert result["verdict"] == "clear"
    assert result["checks"]["profit_warning"]["scanned_items"] == 0
    later = _assess(filings=filings, as_of="2026-11-12")
    assert later["verdict"] == "declining"


def test_profit_warning_outside_lookback_window_is_ignored():
    result = _assess(filings=[_filing("Profit warning", "2026-03-01")])
    assert result["verdict"] == "clear"


def test_third_party_news_headlines_are_not_company_warnings():
    item = _filing(
        "Evening Wrap: ASX 200 slides as NCK profit warning flags slowdown", "2026-10-22"
    )
    item["source"] = "google_news_asx_resolved"
    result = _assess(filings=[item])
    assert result["verdict"] == "clear"
    assert result["checks"]["profit_warning"]["scanned_items"] == 0


def test_undated_filings_are_ignored():
    item = {"id": "x", "headline": "Profit warning", "summary": "Profit warning"}
    assert _assess(filings=[item])["verdict"] == "clear"


def test_financials_fetched_after_as_of_fail_closed():
    fin = _healthy()
    fin["fetched_at"] = "2026-11-20T00:00:00+00:00"
    result = _assess(financials=fin)
    assert result["verdict"] == "insufficient_data"
    assert result["checks"]["revenue"]["why"] == "financials_fetched_after_as_of"


def test_fiscal_years_after_as_of_year_are_ignored():
    fin = _financials(
        {"2026": 500.0, "2025": 1100.0, "2024": 1000.0},
        operating={"2025": 165.0, "2024": 150.0},
        fetched_at="2025-11-01T00:00:00+00:00",
    )
    assert _assess(financials=fin, as_of="2025-12-31")["verdict"] == "clear"
    assert _assess(financials=fin, as_of="2026-11-03")["verdict"] == "declining"


def test_missing_financials_is_insufficient_data():
    result = assess_operating_decline({}, None, None, as_of=AS_OF)
    assert result["verdict"] == "insufficient_data"
    assert "revenue_not_evaluable" in _codes(result)


def test_revenue_without_margin_or_eps_is_insufficient_data():
    fin = _financials({"2025": 1100.0, "2024": 1000.0})
    result = _assess(financials=fin)
    assert result["verdict"] == "insufficient_data"
    assert "operating_margin_not_evaluable" in _codes(result)
    assert "eps_not_evaluable" in _codes(result)


def test_stale_financials_are_insufficient_data():
    fin = _financials(
        {"2022": 1100.0, "2021": 1000.0},
        operating={"2022": 165.0, "2021": 150.0},
    )
    assert _assess(financials=fin)["verdict"] == "insufficient_data"


def test_adverse_evidence_wins_over_missing_data():
    result = _assess(
        financials=None,
        filings=[_filing("Profit warning", "2026-10-01")],
    )
    assert result["verdict"] == "declining"


def test_nan_and_non_numeric_values_are_not_evaluable():
    fin = _financials({"2025": float("nan"), "2024": 1000.0})
    assert _assess(financials=fin)["verdict"] == "insufficient_data"


def test_bad_as_of_raises():
    with pytest.raises(ValueError):
        assess_operating_decline({}, None, None, as_of="not-a-date")


def _write_name(
    research_root: Path,
    ticker: str,
    financials: dict | None,
    filings: list | None = None,
) -> None:
    sources = research_root / ticker / "sources"
    sources.mkdir(parents=True)
    if financials is not None:
        (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")
    if filings is not None:
        (sources / "filings").mkdir()
        (sources / "filings" / "filings_index.json").write_text(
            json.dumps({"filings": filings}), encoding="utf-8"
        )


def _declining_financials() -> dict:
    return _financials(
        {"2025": 800.0, "2024": 1000.0},
        operating={"2025": 80.0, "2024": 150.0},
    )


def _build_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    research = tmp_path / "research"
    latest = tmp_path / "latest.json"
    rows = [
        {"ticker": "OKAY.L", "signal": "strong_buy", "sector": "Industrials"},
        {"ticker": "BAD.L", "signal": "buy", "sector": "Energy"},
        {"ticker": "NODATA.L", "signal": "buy", "sector": "Utilities"},
        {"ticker": "HOLD.L", "signal": "hold", "sector": "Utilities"},
    ]
    latest.write_text(
        json.dumps({"run_at": "2026-11-01T07:00:00+00:00", "reports": rows}),
        encoding="utf-8",
    )
    _write_name(research, "OKAY.L", _healthy(), [_filing("Results", "2026-09-01")])
    _write_name(research, "BAD.L", _declining_financials())
    _write_name(research, "NODATA.L", None)
    _write_name(research, "HOLD.L", _healthy())
    return latest, research, tmp_path / "store.json"


def test_refresh_writes_store_with_contract_shape(tmp_path):
    latest, research, store = _build_fixture(tmp_path)
    payload = refresh_operating_decline_gate(
        latest_path=latest,
        research_root=research,
        store_path=store,
        library_root=None,
        as_of=AS_OF,
    )
    on_disk = json.loads(store.read_text(encoding="utf-8"))
    assert on_disk == payload
    assert payload["schema_version"] == 1
    assert payload["as_of"] == AS_OF
    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    assert payload["summary"] == {
        "names": 4,
        "clear": 2,
        "declining": 1,
        "insufficient_data": 1,
        "buy_tier_names": 3,
        "buy_tier_covered": 2,
        "names_with_interim_eps": 0,
        "latest_fiscal_year_counts": {"2025": 3},
    }
    bad = payload["names"]["BAD.L"]
    assert set(bad) >= {"market", "sector", "signal", "verdict", "reasons", "checks"}
    assert bad["market"] == "ftse350"
    assert bad["sector"] == "Energy"
    assert bad["verdict"] == "declining"
    assert all(set(r) == {"code", "detail", "source"} for r in bad["reasons"])
    assert payload["names"]["NODATA.L"]["verdict"] == "insufficient_data"


def test_refresh_no_persist_does_not_write(tmp_path):
    latest, research, store = _build_fixture(tmp_path)
    refresh_operating_decline_gate(
        latest_path=latest,
        research_root=research,
        store_path=store,
        library_root=None,
        persist=False,
        as_of=AS_OF,
    )
    assert not store.exists()


def test_refresh_ignores_row_flags_when_screen_run_is_after_as_of(tmp_path):
    latest, research, store = _build_fixture(tmp_path)
    data = json.loads(latest.read_text(encoding="utf-8"))
    data["reports"][0]["interim_dividend_cut_flagged"] = True
    data["reports"][0]["interim_eps_decline_pct"] = 0.4
    latest.write_text(json.dumps(data), encoding="utf-8")
    current = refresh_operating_decline_gate(
        latest_path=latest,
        research_root=research,
        store_path=store,
        library_root=None,
        persist=False,
        as_of="2026-11-03",
    )
    assert current["names"]["OKAY.L"]["verdict"] == "declining"
    earlier = refresh_operating_decline_gate(
        latest_path=latest,
        research_root=research,
        store_path=store,
        library_root=None,
        persist=False,
        as_of="2026-10-25",
    )
    assert earlier["names"]["OKAY.L"]["checks"]["dividend"]["evaluable"] is False
    assert earlier["names"]["OKAY.L"]["verdict"] == "clear"
    assert earlier["names"]["OKAY.L"]["reasons"] == []


def test_refresh_includes_library_names_without_overriding_ftse(tmp_path):
    latest, research, store = _build_fixture(tmp_path)
    library = tmp_path / "library"
    screen = library / "markets" / "sp500" / "screen"
    screen.mkdir(parents=True)
    (screen / "latest_signals.csv").write_text(
        "ticker,name,sector,signal\nUSA,US Co,Tech,buy\nBAD.L,Dup,Energy,buy\nMISSING,No,Tech,buy\n",
        encoding="utf-8",
    )
    _write_name(screen / "research", "USA", _declining_financials())
    _write_name(screen / "research", "BAD.L", _healthy())
    payload = refresh_operating_decline_gate(
        latest_path=latest,
        research_root=research,
        store_path=store,
        library_root=library,
        persist=False,
        as_of=AS_OF,
    )
    assert payload["names"]["USA"]["market"] == "sp500"
    assert payload["names"]["USA"]["verdict"] == "declining"
    assert payload["names"]["BAD.L"]["market"] == "ftse350"
    assert "MISSING" not in payload["names"]
    assert payload["summary"]["buy_tier_names"] == 3


def test_refresh_with_missing_latest_is_empty_not_a_crash(tmp_path):
    payload = refresh_operating_decline_gate(
        latest_path=tmp_path / "nope.json",
        research_root=tmp_path / "research",
        store_path=tmp_path / "store.json",
        library_root=None,
        as_of=AS_OF,
    )
    assert payload["summary"]["names"] == 0
    titles = [f["title"] for f in ops_findings_from_operating_decline_gate(payload)]
    assert COVERAGE_GAP_TITLE in titles


def test_findings_summarise_and_flag_buy_tier_declines(tmp_path):
    latest, research, store = _build_fixture(tmp_path)
    payload = refresh_operating_decline_gate(
        latest_path=latest,
        research_root=research,
        store_path=store,
        library_root=None,
        as_of=AS_OF,
    )
    findings = ops_findings_from_operating_decline_gate(payload)
    refreshed = next(f for f in findings if f["title"] == FINDING_TITLE)
    assert refreshed["severity"] == "info"
    assert "BAD.L" in refreshed["summary"]
    assert "revenue_decline" in refreshed["summary"]
    assert "covered 2/3" in refreshed["summary"]
    assert all(f["auto_fixable"] is False for f in findings)
    assert any(f["title"] == COVERAGE_GAP_TITLE and f["severity"] == "warn" for f in findings)


def test_no_coverage_warning_when_buy_tier_is_covered(tmp_path):
    latest, research, store = _build_fixture(tmp_path)
    (research / "NODATA.L" / "sources" / "financials_annual.json").write_text(
        json.dumps(_healthy()), encoding="utf-8"
    )
    payload = refresh_operating_decline_gate(
        latest_path=latest,
        research_root=research,
        store_path=store,
        library_root=None,
        as_of=AS_OF,
    )
    titles = [f["title"] for f in ops_findings_from_operating_decline_gate(payload)]
    assert titles == [FINDING_TITLE]


def test_text_drill_down_lists_reasons(tmp_path):
    latest, research, store = _build_fixture(tmp_path)
    payload = refresh_operating_decline_gate(
        latest_path=latest,
        research_root=research,
        store_path=store,
        library_root=None,
        as_of=AS_OF,
    )
    text = format_operating_decline_text(payload, ticker="bad.l")
    assert "declining" in text
    assert "revenue_decline" in text
    assert "not in the gate store" in format_operating_decline_text(payload, ticker="ZZZ")
    assert "FTSE buy-tier covered 2/3" in format_operating_decline_text(payload)


def test_ops_monitor_check_wraps_findings(tmp_path):
    from value_investor.ops_monitor import check_operating_decline_gate

    latest, research, store = _build_fixture(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "latest.json").write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")
    (data_dir / "research").symlink_to(research)
    findings = check_operating_decline_gate(
        output_dir=data_dir, store_path=store, as_of=AS_OF, persist=True
    )
    assert findings[0].title == FINDING_TITLE
    assert findings[0].auto_fixable is False
    assert store.exists()


def test_margin_uses_one_operating_income_label_across_years():
    fin = _raw(
        {
            "2025": {"Total Revenue": 1000.0, "Operating Income": 100.0, "EBIT": 300.0},
            "2024": {"Total Revenue": 1000.0, "EBIT": 150.0},
        }
    )
    margin = _assess(financials=fin)["checks"]["operating_margin"]
    assert margin["label"] == "EBIT / Total Revenue"
    assert margin["fired"] is False
    assert margin["change_pp"] == pytest.approx(0.15)


def test_margin_not_evaluable_when_no_single_label_spans_both_years():
    fin = _raw(
        {
            "2025": {"Total Revenue": 1000.0, "Operating Income": 100.0},
            "2024": {"Total Revenue": 1000.0, "EBIT": 150.0},
        }
    )
    result = _assess(financials=fin)
    assert result["checks"]["operating_margin"]["evaluable"] is False
    assert result["verdict"] == "insufficient_data"


def test_margin_label_that_reaches_newest_year_beats_stale_preferred_label():
    fin = _raw(
        {
            "2025": {"Total Revenue": 1000.0, "EBIT": 160.0},
            "2024": {"Total Revenue": 1000.0, "Operating Income": 150.0, "EBIT": 150.0},
            "2023": {"Total Revenue": 1000.0, "Operating Income": 150.0},
        }
    )
    margin = _assess(financials=fin)["checks"]["operating_margin"]
    assert margin["label"] == "EBIT / Total Revenue"
    assert margin["latest_year"] == 2025


def test_revenue_does_not_mix_labels_across_years():
    fin = _raw(
        {
            "2025": {"Total Revenue": 800.0, "Operating Income": 120.0},
            "2024": {"Operating Revenue": 1000.0, "Operating Income": 150.0},
        }
    )
    result = _assess(financials=fin)
    assert result["checks"]["revenue"]["evaluable"] is False
    assert "revenue_decline" not in _codes(result)


def test_revenue_two_year_rule_stays_on_one_label():
    fin = _raw(
        {
            "2025": {"Total Revenue": 990.0, "Operating Revenue": 990.0, "Operating Income": 150.0},
            "2024": {
                "Total Revenue": 995.0,
                "Operating Revenue": 1000.0,
                "Operating Income": 150.0,
            },
            "2023": {"Operating Revenue": 1020.0},
        }
    )
    revenue = _assess(financials=fin)["checks"]["revenue"]
    assert revenue["label"] == "Total Revenue"
    assert revenue["prior_change_pct"] is None
    assert revenue["fired"] is False


def test_eps_does_not_mix_diluted_and_basic():
    fin = _raw(
        {
            "2025": {"Total Revenue": 1000.0, "Operating Income": 150.0, "Diluted EPS": 0.4},
            "2024": {"Total Revenue": 1000.0, "Operating Income": 150.0, "Basic EPS": 1.0},
        }
    )
    result = _assess(financials=fin)
    assert result["checks"]["eps_annual"]["evaluable"] is False
    assert "eps_decline_annual" not in _codes(result)


def test_eps_prefers_diluted_when_both_years_have_it():
    fin = _raw(
        {
            "2025": {"Diluted EPS": 1.0, "Basic EPS": 0.4},
            "2024": {"Diluted EPS": 1.0, "Basic EPS": 1.0},
        }
    )
    eps = _assess(financials=fin)["checks"]["eps_annual"]
    assert eps["label"] == "Diluted EPS"
    assert eps["fired"] is False


def test_fcf_does_not_mix_direct_and_derived_across_years():
    cash = {
        "2025": {
            "Free Cash Flow": -20.0,
            "Operating Cash Flow": 100.0,
            "Capital Expenditure": -90.0,
        },
        "2024": {"Operating Cash Flow": 200.0, "Capital Expenditure": -100.0},
    }
    fin = _raw({"2025": {"Total Revenue": 1.0}}, cash)
    fcf = _assess(financials=fin)["checks"]["fcf"]
    assert fcf["label"] == "Operating Cash Flow + Capital Expenditure"
    assert fcf["latest"] == pytest.approx(10.0)
    assert fcf["prior"] == pytest.approx(100.0)
    assert fcf["fired"] is True
    assert fcf["strength"] == "soft"


def test_fcf_not_evaluable_when_labels_do_not_overlap():
    cash = {
        "2025": {"Free Cash Flow": 50.0},
        "2024": {"Operating Cash Flow": 200.0, "Capital Expenditure": -100.0},
    }
    fin = _raw({"2025": {"Total Revenue": 1.0}}, cash)
    assert _assess(financials=fin)["checks"]["fcf"]["evaluable"] is False


def test_summary_reports_interim_and_fiscal_year_coverage(tmp_path):
    latest, research, store = _build_fixture(tmp_path)
    data = json.loads(latest.read_text(encoding="utf-8"))
    data["reports"][3]["interim_eps_decline_pct"] = 0.02
    latest.write_text(json.dumps(data), encoding="utf-8")
    payload = refresh_operating_decline_gate(
        latest_path=latest,
        research_root=research,
        store_path=store,
        library_root=None,
        as_of=AS_OF,
    )
    assert payload["summary"]["names_with_interim_eps"] == 1
    assert payload["summary"]["latest_fiscal_year_counts"] == {"2025": 3}
    summary = next(
        f["summary"]
        for f in ops_findings_from_operating_decline_gate(payload)
        if f["title"] == FINDING_TITLE
    )
    assert "interim EPS on 1 names" in summary
    assert "2025:3" in summary
