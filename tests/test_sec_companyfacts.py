"""Tests for SEC companyfacts memo source and coverage instrument (L544)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.research.sec_companyfacts import (
    SOURCE_FILENAME,
    backfill_candidates,
    backfill_market_sec_companyfacts,
    backfill_us_markets_sec_companyfacts,
    build_companyfacts_source,
    extract_annual_cashflow_facts,
    refresh_sec_companyfacts_source,
)
from value_investor.sec_companyfacts_coverage import (
    COVERAGE_FINDING_TITLE,
    DIVERGENCE_FINDING_TITLE,
    build_sec_companyfacts_coverage,
    ops_findings_from_sec_companyfacts_coverage,
)


def _fact(start, end, val, *, form="10-K", fp="FY", filed="2025-11-01", accn="a1"):
    return {
        "start": start,
        "end": end,
        "val": val,
        "form": form,
        "fp": fp,
        "filed": filed,
        "accn": accn,
    }


def _payload(ocf_facts, capex_facts=None, *, taxonomy="us-gaap", unit="USD"):
    ocf_concept = (
        "NetCashProvidedByUsedInOperatingActivities"
        if taxonomy == "us-gaap"
        else "CashFlowsFromUsedInOperatingActivities"
    )
    capex_concept = (
        "PaymentsToAcquirePropertyPlantAndEquipment"
        if taxonomy == "us-gaap"
        else "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
    )
    facts = {ocf_concept: {"units": {unit: ocf_facts}}}
    if capex_facts is not None:
        facts[capex_concept] = {"units": {unit: capex_facts}}
    return {"cik": 1, "entityName": "Example Corp", "facts": {taxonomy: facts}}


def test_extract_keeps_annual_durations_and_latest_filed_value():
    payload = _payload(
        [
            _fact("2024-10-01", "2025-09-30", 100.0, filed="2025-11-01", accn="orig"),
            _fact("2024-10-01", "2025-09-30", 105.0, filed="2026-11-01", accn="restated"),
            _fact("2025-07-01", "2025-09-30", 30.0),
            _fact("2024-10-01", "2025-06-30", 70.0, form="10-Q", fp="Q3"),
            _fact("2023-10-01", "2024-09-30", 90.0, filed="2024-11-01"),
        ],
        [
            _fact("2024-10-01", "2025-09-30", 20.0),
            _fact("2023-10-01", "2024-09-30", 15.0, filed="2024-11-01"),
        ],
    )
    periods = extract_annual_cashflow_facts(payload)
    assert [p["period_end"] for p in periods] == ["2025-09-30", "2024-09-30"]
    latest = periods[0]
    assert latest["operating_cashflow"]["value"] == 105.0
    assert latest["operating_cashflow"]["accn"] == "restated"
    assert latest["operating_cashflow"]["first_filed"] == "2025-11-01"
    assert latest["free_cashflow"] == 85.0
    assert latest["fiscal_year_label"] == "2025"
    assert latest["currency"] == "USD"


def test_extract_ifrs_non_usd_and_missing_capex():
    payload = _payload(
        [_fact("2025-01-01", "2025-12-31", 500.0, form="20-F")],
        taxonomy="ifrs-full",
        unit="EUR",
    )
    periods = extract_annual_cashflow_facts(payload)
    assert periods[0]["currency"] == "EUR"
    assert periods[0]["operating_cashflow"]["concept"].startswith("ifrs-full:")
    assert periods[0]["free_cashflow"] is None


def test_build_source_records_provenance():
    source = build_companyfacts_source(
        _payload([_fact("2025-01-01", "2025-12-31", 10.0)]),
        ticker="exm",
        cik=42,
    )
    assert source["ticker"] == "EXM"
    assert source["url"].endswith("CIK0000000042.json")
    assert source["latest"]["period_end"] == "2025-12-31"


def test_refresh_writes_source_and_handles_unresolved(tmp_path: Path):
    payload = _payload(
        [_fact("2025-01-01", "2025-12-31", 10.0)],
        [_fact("2025-01-01", "2025-12-31", 4.0)],
    )
    meta = refresh_sec_companyfacts_source(
        ticker="EXM",
        sources_dir=tmp_path,
        fetcher=lambda cik: payload,
        cik_resolver=lambda ticker: 42,
    )
    assert meta["written"] is True
    assert meta["latest_free_cashflow"] == 6.0
    written = json.loads((tmp_path / SOURCE_FILENAME).read_text(encoding="utf-8"))
    assert written["cik"] == 42

    missing = refresh_sec_companyfacts_source(
        ticker="NOPE",
        sources_dir=tmp_path / "other",
        fetcher=lambda cik: payload,
        cik_resolver=lambda ticker: None,
    )
    assert missing == {"written": False, "ticker": "NOPE", "note": "cik_unresolved"}

    empty = refresh_sec_companyfacts_source(
        ticker="EMPTY",
        sources_dir=tmp_path / "empty",
        fetcher=lambda cik: {"facts": {}},
        cik_resolver=lambda ticker: 7,
    )
    assert empty["note"] == "no_annual_cashflow_facts"
    assert not (tmp_path / "empty" / SOURCE_FILENAME).exists()


def _memo(root: Path, ticker: str, *, signal: str = "buy") -> Path:
    ticker_dir = root / ticker
    (ticker_dir / "sources").mkdir(parents=True)
    (ticker_dir / "research.json").write_text(json.dumps({"signal": signal}), encoding="utf-8")
    return ticker_dir / "sources"


def _write_source(sources_dir: Path, *, fetched_at: datetime, fcf: float, year: str = "2025"):
    source = {
        "fetched_at": fetched_at.isoformat(),
        "latest": {
            "period_end": f"{year}-12-31",
            "fiscal_year_label": year,
            "currency": "USD",
            "free_cashflow": fcf,
            "operating_cashflow": {"filed": f"{int(year) + 1}-02-01"},
        },
        "annual": [],
    }
    (sources_dir / SOURCE_FILENAME).write_text(json.dumps(source), encoding="utf-8")


def _write_yahoo(sources_dir: Path, *, ocf: float, capex: float, year: str = "2025"):
    financials = {
        "cash_flow": {year: {"Operating Cash Flow": ocf, "Capital Expenditure": capex}},
    }
    (sources_dir / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")


def test_backfill_candidates_missing_first_then_stale(tmp_path: Path):
    now = datetime(2026, 10, 6, tzinfo=UTC)
    _memo(tmp_path, "BBB", signal="buy")
    _memo(tmp_path, "AAA", signal="strong_buy")
    stale = _memo(tmp_path, "CCC")
    _write_source(stale, fetched_at=now - timedelta(days=45), fcf=1.0)
    fresh = _memo(tmp_path, "DDD")
    _write_source(fresh, fetched_at=now - timedelta(days=2), fcf=1.0)

    ordered = [ticker for ticker, _ in backfill_candidates(tmp_path, now=now)]
    assert ordered == ["AAA", "BBB", "CCC"]


def test_backfill_market_respects_cap_and_skips_non_us(tmp_path: Path):
    research = tmp_path / "markets" / "sp500" / "screen" / "research"
    for ticker in ("AAA", "BBB", "CCC"):
        _memo(research, ticker)
    payload = _payload([_fact("2025-01-01", "2025-12-31", 10.0)])

    result = backfill_market_sec_companyfacts(
        "sp500",
        library_root=tmp_path,
        max_tickers=2,
        fetcher=lambda cik: payload,
        cik_resolver=lambda ticker: None if ticker == "BBB" else 1,
        sleep_s=0,
    )
    assert result.candidates == 3
    assert result.written == ["AAA"]
    assert result.failed == {"BBB": "cik_unresolved"}
    assert (research / "AAA" / "sources" / SOURCE_FILENAME).exists()

    assert backfill_us_markets_sec_companyfacts(["euro_depth"], library_root=tmp_path) == []


def test_coverage_compares_sec_with_yahoo_basis(tmp_path: Path):
    now = datetime(2026, 10, 6, tzinfo=UTC)
    research = tmp_path / "markets" / "sp500" / "screen" / "research"
    agrees = _memo(research, "AGR", signal="strong_buy")
    _write_source(agrees, fetched_at=now, fcf=100.0)
    _write_yahoo(agrees, ocf=130.0, capex=-32.0)
    diverged = _memo(research, "DIV", signal="buy")
    _write_source(diverged, fetched_at=now, fcf=100.0)
    _write_yahoo(diverged, ocf=200.0, capex=-40.0)
    no_year = _memo(research, "NOY")
    _write_source(no_year, fetched_at=now, fcf=50.0)
    _write_yahoo(no_year, ocf=1.0, capex=0.0, year="2024")
    _memo(research, "MIS")

    payload = build_sec_companyfacts_coverage(tmp_path, markets=("sp500",), now=now)
    summary = payload["summary"]
    assert summary["memos"] == 4
    assert summary["with_companyfacts"] == 3
    assert summary["compared"] == 2
    assert summary["diverged"] == 1
    assert summary["diverged_buy_tier"] == 1
    assert payload["diverged"][0]["ticker"] == "DIV"
    assert payload["diverged"][0]["divergence"] == 0.375

    findings = {f["title"]: f for f in ops_findings_from_sec_companyfacts_coverage(payload)}
    assert findings[DIVERGENCE_FINDING_TITLE]["severity"] == "info"
    assert "DIV (sp500)" in findings[DIVERGENCE_FINDING_TITLE]["summary"]
    assert findings[COVERAGE_FINDING_TITLE]["severity"] == "info"
    assert all(f["auto_fixable"] is False for f in findings.values())


def test_divergence_finding_warns_at_three_buy_tier_names():
    rows = [
        {
            "ticker": f"T{i}",
            "market_id": "sp500",
            "signal": "buy",
            "period_end": "2025-12-31",
            "sec_fcf": 1e8,
            "yahoo_filing_aligned": 2e8,
            "divergence": 0.5,
        }
        for i in range(3)
    ]
    payload = {
        "summary": {"coverage": 0.9, "diverged": 3, "compared": 10, "diverged_buy_tier": 3},
        "diverged": rows,
    }
    findings = ops_findings_from_sec_companyfacts_coverage(payload)
    assert [f["title"] for f in findings] == [DIVERGENCE_FINDING_TITLE]
    assert findings[0]["severity"] == "warn"


def test_check_sec_companyfacts_coverage_persists_store(tmp_path: Path):
    from value_investor.ops_monitor import check_sec_companyfacts_coverage

    research = tmp_path / "markets" / "nasdaq100" / "screen" / "research"
    _memo(research, "MIS")
    store = tmp_path / "store.json"
    findings = check_sec_companyfacts_coverage(library_root=tmp_path, store_path=store)
    assert [f.title for f in findings] == [COVERAGE_FINDING_TITLE]
    assert json.loads(store.read_text(encoding="utf-8"))["markets"]["nasdaq100"]["memos"] == 1
    assert check_sec_companyfacts_coverage(library_root=tmp_path / "absent") == []


def test_prompt_lists_companyfacts_only_when_present(tmp_path: Path):
    from value_investor.research.agent import _initial_prompt, _weekly_update_prompt

    prompt = _initial_prompt(ticker="ITV.L", company_name="ITV plc", sources_dir=tmp_path)
    assert SOURCE_FILENAME not in prompt

    (tmp_path / SOURCE_FILENAME).write_text("{}", encoding="utf-8")
    prompt = _initial_prompt(ticker="AOS", company_name="A. O. Smith", sources_dir=tmp_path)
    assert SOURCE_FILENAME in prompt
    weekly = _weekly_update_prompt(
        ticker="AOS",
        company_name="A. O. Smith",
        sources_dir=tmp_path,
        news_batch_path=tmp_path / "batch.json",
        existing_markdown_path=tmp_path / "research.md",
    )
    assert "SEC filed cash-flow facts" in weekly


def test_gap_fill_inventory_and_us_catalog(tmp_path: Path):
    from value_investor.research.gap_fill_sources import (
        ALTERNATE_SOURCE_CATALOG,
        inspect_local_sources,
        suggest_alternate_sources,
    )

    inventory = inspect_local_sources(tmp_path)
    assert "sec_companyfacts" not in inventory["available"]
    assert "sec_companyfacts" not in inventory["thin"]

    (tmp_path / SOURCE_FILENAME).write_text("{}", encoding="utf-8")
    assert inspect_local_sources(tmp_path)["available"]["sec_companyfacts"] is True

    assert ALTERNATE_SOURCE_CATALOG["us"][0]["id"] == "sec_companyfacts"
    ranked = suggest_alternate_sources(
        ticker="AOS",
        market="sp500",
        inventory={"thin": []},
        open_questions=["Does free cash flow cover the dividend?"],
    )
    assert ranked[0]["id"] == "sec_companyfacts"
