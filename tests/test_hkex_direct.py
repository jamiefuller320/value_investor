"""HKEX direct announcement feed for .HK memos (L543)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from value_investor.hkex_direct_coverage import (
    COVERAGE_FINDING_TITLE,
    SILENT_FINDING_TITLE,
    build_hkex_direct_coverage,
    ops_findings_from_hkex_direct_coverage,
)
from value_investor.ingest_discovery_scan import merge_discovery_into_index
from value_investor.library_ingest_exhaustion import (
    load_ingest_exhaustion,
    refresh_library_ingest_exhaustion,
)
from value_investor.research import hkex_direct
from value_investor.research.filings import (
    _apply_headline_period,
    filing_source_surface,
    ingest_filings,
    merge_filings,
)
from value_investor.research.hkex_direct import (
    classify_hkex_category,
    drop_allowlist_rows_covered_by_hkex,
    fetch_filings_hkex_direct,
    hk_stock_code,
    parse_prefix_response,
    select_rows_by_kind_quota,
)
from value_investor.storage import write_json

PREFIX_PAYLOAD = (
    'callback({"more":"0","stockInfo":['
    '{"stockId":1000123,"code":"02382","name":"SUNNY OPTICAL"},'
    '{"stockId":1000999,"code":"23820","name":"SUNNYOPT WARRANT"}]});\r\n'
)


def _hkex_raw(title: str, category: str, when: datetime, link: str, news_id: str) -> dict:
    return {
        "TITLE": title,
        "LONG_TEXT": category,
        "DATE_TIME": (when + timedelta(hours=8)).strftime("%d/%m/%Y %H:%M"),
        "FILE_LINK": link,
        "FILE_TYPE": "PDF",
        "FILE_INFO": "180KB",
        "NEWS_ID": news_id,
        "STOCK_CODE": "02382",
    }


def _title_payload(rows: list[dict]) -> bytes:
    return json.dumps({"result": json.dumps(rows)}).encode("utf-8")


@pytest.fixture(autouse=True)
def _clear_stock_id_cache():
    hkex_direct._stock_id_cache.clear()
    yield
    hkex_direct._stock_id_cache.clear()


def _fake_hkex_get(results_rows: list[dict], report_rows: list[dict]):
    calls: list[str] = []

    def _get(url: str, *, timeout: int = 30) -> bytes:
        calls.append(url)
        if "prefix.do" in url:
            return PREFIX_PAYLOAD.encode("utf-8")
        if "t1code=10000" in url:
            return _title_payload(results_rows)
        if "t1code=40000" in url:
            return _title_payload(report_rows)
        raise AssertionError(url)

    return _get, calls


def test_hk_stock_code_pads_to_five_digits():
    assert hk_stock_code("2382.HK") == "02382"
    assert hk_stock_code("0700.hk") == "00700"
    assert hk_stock_code("D05.SI") is None
    assert hk_stock_code("BHP.AX") is None


def test_parse_prefix_response_matches_exact_code_not_warrant():
    assert parse_prefix_response(PREFIX_PAYLOAD, "02382") == 1000123
    assert parse_prefix_response(PREFIX_PAYLOAD, "00700") is None
    assert parse_prefix_response("not json", "02382") is None


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Announcements and Notices - [Final Results &#x2f; Dividend or Distribution]", "annual"),
        ("Announcements and Notices - [Interim Results]", "interim"),
        ("Announcements and Notices - [Quarterly Results]", "interim"),
        ("Financial Statements&#x2f;ESG Information - [Annual Report]", "annual"),
        ("Financial Statements&#x2f;ESG Information - [Interim&#x2f;Half-Year Report]", "interim"),
        (
            "Announcements and Notices - [Profit Warning &#x2f; Inside Information]",
            "trading_update",
        ),
    ],
)
def test_classify_hkex_category_periods(label: str, expected: str):
    classified = classify_hkex_category(label)
    assert classified is not None
    assert classified[1] == expected


@pytest.mark.parametrize(
    "label",
    [
        "Financial Statements&#x2f;ESG Information - [Environmental, Social and Governance Information&#x2f;Report]",
        "Announcements and Notices - [Date of Board Meeting]",
        "Announcements and Notices - [Dividend or Distribution (Announcement Form)]",
        "",
    ],
)
def test_classify_hkex_category_drops_noise(label: str):
    assert classify_hkex_category(label) is None


def test_fetch_filings_hkex_direct_parses_both_queries():
    now = datetime.now(UTC)
    results = [
        _hkex_raw(
            "INTERIM RESULTS ANNOUNCEMENT FOR THE SIX MONTHS ENDED 30 JUNE 2026",
            "Announcements and Notices - [Interim Results]",
            now - timedelta(days=40),
            "/listedco/listconews/sehk/2026/0826/2026082600001.pdf",
            "1",
        ),
        _hkex_raw(
            "NOTICE OF BOARD MEETING",
            "Announcements and Notices - [Date of Board Meeting]",
            now - timedelta(days=60),
            "/listedco/listconews/sehk/2026/0804/2026080400002.pdf",
            "2",
        ),
        _hkex_raw(
            "ANNOUNCEMENT OF THE RESULTS FOR THE THREE MONTHS ENDED 31 MARCH 2026",
            "Announcements and Notices - [Quarterly Results]",
            now - timedelta(days=140),
            "/listedco/listconews/sehk/2026/0513/2026051300003.pdf",
            "3",
        ),
        _hkex_raw(
            "ANNUAL RESULTS ANNOUNCEMENT FOR THE YEAR ENDED 31 DECEMBER 2021",
            "Announcements and Notices - [Final Results]",
            now - timedelta(days=1500),
            "/listedco/listconews/sehk/2022/0330/2022033000004.pdf",
            "4",
        ),
    ]
    reports = [
        _hkex_raw(
            "ANNUAL REPORT 2025",
            "Financial Statements&#x2f;ESG Information - [Annual Report]",
            now - timedelta(days=160),
            "/listedco/listconews/sehk/2026/0424/2026042401983.pdf",
            "5",
        ),
        _hkex_raw(
            "ENVIRONMENTAL, SOCIAL AND GOVERNANCE REPORT 2025",
            "Financial Statements&#x2f;ESG Information - [Environmental, Social and Governance]",
            now - timedelta(days=160),
            "/listedco/listconews/sehk/2026/0424/2026042401984.pdf",
            "6",
        ),
    ]
    getter, calls = _fake_hkex_get(results, reports)
    rows = fetch_filings_hkex_direct(ticker="2382.HK", http_get=getter)

    assert [r["headline"] for r in rows] == [
        "INTERIM RESULTS ANNOUNCEMENT FOR THE SIX MONTHS ENDED 30 JUNE 2026",
        "ANNOUNCEMENT OF THE RESULTS FOR THE THREE MONTHS ENDED 31 MARCH 2026",
        "ANNUAL REPORT 2025",
    ]
    assert [r["period"] for r in rows] == ["interim", "interim", "annual"]
    assert all(r["source"] == "hkex_direct" for r in rows)
    assert rows[2]["url"] == (
        "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0424/2026042401983.pdf"
    )
    assert rows[2]["category"].endswith("[Annual Report]")
    assert "stockId=1000123" in calls[1]
    assert sum("prefix.do" in c for c in calls) == 1


def test_fetch_filings_hkex_direct_skips_non_hk_and_unknown_codes():
    getter, calls = _fake_hkex_get([], [])
    assert fetch_filings_hkex_direct(ticker="D05.SI", http_get=getter) == []
    assert calls == []
    assert fetch_filings_hkex_direct(ticker="0700.HK", http_get=getter) == []
    assert all("titleSearchServlet" not in c for c in calls)


def test_fetch_filings_hkex_direct_survives_network_errors():
    def _boom(url: str, *, timeout: int = 30) -> bytes:
        raise OSError("down")

    assert fetch_filings_hkex_direct(ticker="2382.HK", http_get=_boom) == []


def test_kind_quota_keeps_newest_per_kind_within_body_budget():
    from value_investor.research.hkex_direct import HKEX_KIND_QUOTAS, HKEX_MAX_ITEMS

    rows = [
        {"hkex_kind": kind, "published_at": f"20{year}-0{month}-01"}
        for kind in HKEX_KIND_QUOTAS
        for year in (24, 25, 26)
        for month in (3, 8)
    ]
    rows.append({"hkex_kind": "unknown", "published_at": "2026-09-30"})
    kept = select_rows_by_kind_quota(rows)
    assert len(kept) == HKEX_MAX_ITEMS == 10
    assert HKEX_MAX_ITEMS < 12  # ingest body cap; feed rows never left without bodies
    by_kind: dict[str, list[str]] = {}
    for row in kept:
        by_kind.setdefault(row["hkex_kind"], []).append(row["published_at"])
    assert by_kind["profit_warning"] == ["2026-08-01"]
    assert by_kind["interim_results"] == ["2026-08-01", "2026-03-01", "2025-08-01"]
    assert "unknown" not in by_kind
    assert [r["published_at"] for r in kept] == sorted(
        (r["published_at"] for r in kept), reverse=True
    )


def test_allowlist_rows_covered_by_hkex_are_dropped_host_insensitive():
    hkex_rows = [
        {"url": "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0424/2026042401983.pdf"}
    ]
    allowlist = [
        {"url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0424/2026042401983.pdf"},
        {"url": "https://www.chinaunicom.com.hk/en/ir/reports/ar2025.pdf"},
    ]
    kept = drop_allowlist_rows_covered_by_hkex(allowlist, hkex_rows)
    assert [r["url"] for r in kept] == ["https://www.chinaunicom.com.hk/en/ir/reports/ar2025.pdf"]
    assert drop_allowlist_rows_covered_by_hkex(allowlist, []) == allowlist


def test_apply_headline_period_keeps_hkex_category_period():
    row = {
        "id": "x",
        "source": "hkex_direct",
        "headline": "ANNOUNCEMENT OF THE RESULTS FOR THE THREE MONTHS ENDED 31 MARCH 2026",
        "category": "Announcements and Notices - [Quarterly Results]",
        "period": "interim",
        "hkex_period": "interim",
    }
    assert _apply_headline_period(row)["period"] == "interim"
    profit = {**row, "headline": "POSITIVE PROFIT ALERT", "hkex_period": "trading_update"}
    assert _apply_headline_period(profit)["period"] == "trading_update"


def test_merge_prefers_hkex_direct_over_google_news_same_headline():
    gnews = {
        "id": "g",
        "source": "google_news_asia",
        "headline": "ANNUAL REPORT 2025",
        "published_at": "2026-04-24T09:00:00+00:00",
        "priority": 100,
    }
    hkex = {**gnews, "id": "h", "source": "hkex_direct", "url": "https://www.hkexnews.hk/a.pdf"}
    merged = merge_filings([gnews], [hkex])
    assert [r["source"] for r in merged] == ["hkex_direct"]


def _hkex_row(period: str, url: str, headline: str) -> dict:
    return {
        "id": url[-12:],
        "source": "hkex_direct",
        "headline": headline,
        "published_at": "2026-08-26T11:00:00+00:00",
        "url": url,
        "period": period,
        "hkex_period": period,
        "category": "Announcements and Notices - [Interim Results]",
        "summary": headline,
        "has_body": False,
        "body_path": None,
        "priority": 100,
    }


def test_ingest_filings_asia_hk_uses_hkex_direct_and_dedupes_allowlist(tmp_path: Path):
    url = "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0424/2026042401983.pdf"
    hkex_rows = [_hkex_row("annual", url, "ANNUAL REPORT 2025")]
    allowlist_rows = [
        {
            "id": "allow1",
            "source": "ir_allowlist",
            "headline": "IR allowlist document",
            "published_at": None,
            "url": url.replace("www.", "www1."),
            "period": "annual",
            "category": "ir_allowlist",
            "has_body": False,
            "body_path": None,
            "priority": 100,
        }
    ]
    body = "Sunny Optical annual report 2025. " * 20
    with (
        patch(
            "value_investor.research.filings.fetch_filings_hkex_direct", return_value=hkex_rows
        ) as hkex,
        patch("value_investor.research.filings.fetch_filings_asia_news", return_value=[]),
        patch(
            "value_investor.research.filings.fetch_filings_ir_allowlist",
            return_value=allowlist_rows,
        ),
        patch("value_investor.research.filings.fetch_filing_body", return_value=body),
        patch("value_investor.research.filings.fetch_filings_sec_edgar") as sec,
    ):
        meta = ingest_filings(
            ticker="2382.HK",
            company_name="Sunny Optical Technology (Group) Company Limited",
            sources_dir=tmp_path,
            market="hang_seng",
        )
    hkex.assert_called_once()
    sec.assert_not_called()
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert index["regime"] == "asia_filings"
    assert "HKEXnews" in index["note"]
    assert [r["source"] for r in index["filings"]] == ["hkex_direct"]
    assert index["filings"][0]["has_body"] is True
    assert index["filings"][0]["period"] == "annual"


def test_ingest_filings_asia_si_skips_hkex(tmp_path: Path):
    with (
        patch("value_investor.research.filings.fetch_filings_hkex_direct") as hkex,
        patch("value_investor.research.filings.fetch_filings_asia_news", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_ir_allowlist", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_sec_edgar", return_value=[]),
    ):
        ingest_filings(
            ticker="D05.SI",
            company_name="DBS Group Holdings Ltd",
            sources_dir=tmp_path,
            market="sti",
        )
    hkex.assert_not_called()


def test_filing_source_surface_marks_hkex_adapter():
    assert filing_source_surface("hang_seng", "2382.HK") == "asia_filings+hkex_direct"
    assert filing_source_surface("sti", "D05.SI") == "asia_filings"
    assert filing_source_surface("sp500", "AAPL") == "sec_edgar"


def _write_exhaustion(root: Path, market: str, parked: list[dict]) -> None:
    write_json(
        root / "markets" / market / "ingest_exhaustion.json",
        {"market_id": market, "exhausted": True, "parked": parked},
        compact=False,
    )


def test_load_exhaustion_releases_parked_names_on_new_fetch_surface(tmp_path: Path):
    _write_exhaustion(
        tmp_path,
        "hang_seng",
        [
            {"ticker": "2382.HK", "reason": "awaiting_periodic_report"},
            {"ticker": "0941.HK", "source_surface": "asia_filings+hkex_direct"},
        ],
    )
    _write_exhaustion(tmp_path, "sti", [{"ticker": "BUOU.SI"}])

    hk = load_ingest_exhaustion("hang_seng", library_root=tmp_path)
    assert hk["surface_released"] == ["2382.HK"]
    assert [r["ticker"] for r in hk["parked"]] == ["0941.HK"]
    assert hk["exhausted"] is False

    sti = load_ingest_exhaustion("sti", library_root=tmp_path)
    assert sti["surface_released"] == []
    assert [r["ticker"] for r in sti["parked"]] == ["BUOU.SI"]
    assert sti["exhausted"] is True


def test_refresh_does_not_repark_surface_released_name_same_pass(tmp_path: Path):
    _write_exhaustion(tmp_path, "hang_seng", [{"ticker": "2382.HK"}, {"ticker": "0941.HK"}])
    health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_tickers": ["2382.HK", "0941.HK"],
        "indexed_without_body_tickers": [],
    }
    log_path = tmp_path / "health_log.json"
    write_json(
        log_path,
        {
            "entries": [
                {"market_id": "hang_seng", "improved": 0, "targets": 5, "health_after": health}
                for _ in range(3)
            ]
        },
        compact=False,
    )
    payload = refresh_library_ingest_exhaustion(
        "hang_seng",
        library_root=tmp_path,
        health=health,
        health_log_path=log_path,
    )
    assert payload["surface_released"] == ["0941.HK", "2382.HK"]
    assert payload["parked"] == []
    assert payload["unparked_leftover"] == ["0941.HK", "2382.HK"]

    # Next pass: released grace is spent; zero-improve streak parks with the new stamp.
    again = refresh_library_ingest_exhaustion(
        "hang_seng",
        library_root=tmp_path,
        health=health,
        health_log_path=log_path,
    )
    assert again["surface_released"] == []
    assert {r["ticker"] for r in again["parked"]} == {"2382.HK", "0941.HK"}
    assert {r["source_surface"] for r in again["parked"]} == {"asia_filings+hkex_direct"}
    reloaded = load_ingest_exhaustion("hang_seng", library_root=tmp_path)
    assert reloaded["surface_released"] == []
    assert len(reloaded["parked"]) == 2


def test_library_discovery_listing_includes_hkex_for_hk(tmp_path: Path):
    from value_investor.library_discovery_scan import list_regime_filings_index_only

    url = "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0826/2026082600001.pdf"
    with (
        patch(
            "value_investor.library_discovery_scan.fetch_filings_hkex_direct",
            return_value=[_hkex_row("interim", url, "INTERIM RESULTS 2026")],
        ) as hkex,
        patch("value_investor.library_discovery_scan.fetch_filings_asia_news", return_value=[]),
        patch(
            "value_investor.library_discovery_scan.fetch_filings_ir_allowlist",
            return_value=[{"id": "a", "source": "ir_allowlist", "headline": "x", "url": url}],
        ),
    ):
        rows = list_regime_filings_index_only(
            ticker="2382.HK", company_name="Sunny Optical", market="hang_seng"
        )
    hkex.assert_called_once()
    assert [r["source"] for r in rows] == ["hkex_direct"]


def test_merge_discovery_into_index_stamps_resolved_regime(tmp_path: Path):
    merge_discovery_into_index(
        filings_dir=tmp_path / "hk",
        ticker="2382.HK",
        company_name="Sunny Optical",
        discovered=[],
        market="hang_seng",
    )
    payload = json.loads((tmp_path / "hk" / "filings_index.json").read_text(encoding="utf-8"))
    assert payload["regime"] == "asia_filings"
    merge_discovery_into_index(
        filings_dir=tmp_path / "uk", ticker="AAA.L", company_name="AAA", discovered=[]
    )
    payload = json.loads((tmp_path / "uk" / "filings_index.json").read_text(encoding="utf-8"))
    assert payload["regime"] == "uk_rns"


def _memo(root: Path, ticker: str, index: dict | None) -> None:
    ticker_dir = root / "markets" / "hang_seng" / "screen" / "research" / ticker
    filings_dir = ticker_dir / "sources" / "filings"
    filings_dir.mkdir(parents=True, exist_ok=True)
    (ticker_dir / "research.json").write_text(json.dumps({"signal": "buy"}), encoding="utf-8")
    if index is not None:
        (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")


def test_hkex_direct_coverage_statuses_and_findings(tmp_path: Path):
    now = datetime(2026, 10, 6, tzinfo=UTC)
    fresh = (now - timedelta(days=1)).isoformat()
    body = {"source": "hkex_direct", "has_body": True, "published_at": "2026-08-26"}
    _memo(
        tmp_path,
        "2382.HK",
        {
            "fetched_at": fresh,
            "note": "Hong Kong results via the HKEXnews title-search feed",
            "filings": [{**body, "period": "annual"}, {**body, "period": "interim"}],
        },
    )
    _memo(
        tmp_path,
        "0941.HK",
        {"fetched_at": fresh, "note": "HKEXnews", "filings": [{**body, "period": "annual"}]},
    )
    for ticker in ("0700.HK", "0005.HK"):
        _memo(
            tmp_path,
            ticker,
            {
                "fetched_at": fresh,
                "note": "HKEXnews",
                "filings": [{"source": "google_news_asia", "period": "annual"}],
            },
        )
    _memo(
        tmp_path,
        "1378.HK",
        {
            "fetched_at": (now - timedelta(days=30)).isoformat(),
            "note": "Hong Kong / Singapore results discovery via Google News",
            "filings": [],
        },
    )

    with patch(
        "value_investor.hkex_direct_coverage._screen_buy_tier",
        return_value={"2382.HK", "0941.HK", "0700.HK", "1378.HK"},
    ):
        payload = build_hkex_direct_coverage(tmp_path, now=now)

    status = {r["ticker"]: r["status"] for r in payload["not_covered"]}
    assert status == {
        "0941.HK": "partial",
        "0700.HK": "silent",
        "0005.HK": "silent",
        "1378.HK": "not_reingested",
    }
    summary = payload["summary"]
    assert summary["buy_tier"] == 4
    assert summary["buy_tier_covered"] == 1
    assert summary["silent"] == 2

    findings = {f["title"]: f for f in ops_findings_from_hkex_direct_coverage(payload)}
    assert findings[SILENT_FINDING_TITLE]["severity"] == "warn"
    assert "0700.HK" in findings[SILENT_FINDING_TITLE]["summary"]
    assert findings[COVERAGE_FINDING_TITLE]["severity"] == "info"
    assert "0941.HK" in findings[COVERAGE_FINDING_TITLE]["summary"]
    assert all(f["auto_fixable"] is False for f in findings.values())


def test_hkex_direct_coverage_quiet_when_covered(tmp_path: Path):
    body = {"source": "hkex_direct", "has_body": True}
    _memo(
        tmp_path,
        "2382.HK",
        {
            "fetched_at": datetime.now(UTC).isoformat(),
            "filings": [{**body, "period": "annual"}, {**body, "period": "interim"}],
        },
    )
    with patch("value_investor.hkex_direct_coverage._screen_buy_tier", return_value={"2382.HK"}):
        payload = build_hkex_direct_coverage(tmp_path)
    assert payload["summary"]["buy_tier_coverage"] == 1.0
    assert ops_findings_from_hkex_direct_coverage(payload) == []
