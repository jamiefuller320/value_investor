from __future__ import annotations

import json
import urllib.error
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from value_investor.cision_direct_coverage import (
    COVERAGE_FINDING_TITLE,
    SILENT_FINDING_TITLE,
    build_cision_direct_coverage,
    ops_findings_from_cision_direct_coverage,
)
from value_investor.library_ingest_exhaustion import load_ingest_exhaustion
from value_investor.research.cision_direct import (
    CISION_KIND_QUOTAS,
    CISION_MAX_ITEMS,
    cision_eligible,
    cision_feed_url,
    cision_item_to_filing,
    cision_newsroom,
    classify_cision_release,
    fetch_filings_cision_direct,
    parse_cision_rss,
    report_attachment_url,
    select_rows_by_kind_quota,
)
from value_investor.research.filings import (
    UNEXTRACTABLE_BODY_SOURCES,
    _apply_headline_period,
    _source_bonus,
    filing_source_surface,
    ingest_filings,
)
from value_investor.storage import write_json

NOW = datetime.now(UTC).replace(microsecond=0)


def _item(title: str, when: datetime, *, newsroom: str = "sandvik", rid: int = 1) -> str:
    slug = "-".join(title.lower().split())[:40]
    return (
        f"<item><title>{title}</title>"
        f"<link>https://news.cision.com/{newsroom}/r/{slug},c{rid}</link>"
        f'<guid isPermaLink="false">cision{rid}</guid>'
        f"<description><![CDATA[{title} summary &amp; outlook.]]></description>"
        f"<pubDate>{format_datetime(when)}</pubDate></item>"
    )


def _rss(*items: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
        "<title>Cision News</title>" + "".join(items) + "</channel></rss>"
    ).encode("utf-8")


def _release_page(rid: int, *, attachment: bool = True) -> bytes:
    links = (
        f'<a href="https://mb.cision.com/Public/208/{rid}/abc.xlsx">Data</a>'
        f'<a href="https://mb.cision.com/Main/208/{rid}/{rid}9.pdf">Interim report</a>'
        f'<a href="https://mb.cision.com/Public/208/{rid}/press.pdf">Press release</a>'
        if attachment
        else ""
    )
    return f"<html><body><p>Report text</p>{links}</body></html>".encode()


def _fake_get(feed: bytes, *, pages: dict[int, bytes] | None = None, fail_pages: bool = False):
    calls: list[str] = []

    def _get(url: str, *, timeout: int = 30) -> bytes:
        calls.append(url)
        if "ListItems" in url:
            return feed
        if fail_pages:
            raise urllib.error.URLError("down")
        rid = int(url.rsplit(",c", 1)[1])
        return (pages or {}).get(rid, _release_page(rid))

    return _get, calls


def test_newsroom_map_is_explicit():
    assert cision_newsroom("VOLV-B.ST") == "ab-volvo"
    assert cision_newsroom("tel2-b.st") == "tele2-ab"
    assert cision_eligible("SAND.ST")
    for ticker in ("HM-B.ST", "NIBE-B.ST", "ABB.ST", "LIFCO-B.ST", "INDU-C.ST", "SAP.DE"):
        assert not cision_eligible(ticker)
    assert cision_feed_url("sandvik").endswith("/sandvik/ListItems?format=rss&pageSize=400")


def test_parse_cision_rss_reads_cdata_entities_and_dates():
    when = datetime(2026, 7, 17, 5, 20, tzinfo=UTC)
    items = parse_cision_rss(_rss(_item("Interim report second quarter 2026", when, rid=42)))
    assert len(items) == 1
    assert items[0]["title"] == "Interim report second quarter 2026"
    assert items[0]["published"] == when
    assert items[0]["link"].endswith(",c42")
    assert items[0]["description"] == "Interim report second quarter 2026 summary & outlook."
    assert parse_cision_rss(b"not xml") == []


@pytest.mark.parametrize(
    ("title", "month", "kind", "period"),
    [
        ("Volvo Group – the second quarter 2026", 7, "interim_results", "interim"),
        ("Volvo Group – the fourth quarter and full year 2025", 1, "final_results", "annual"),
        ("Interim report 1 January - 31 March 2026", 4, "quarterly_update", "trading_update"),
        ("Hexagon Interim Report 1 January - 30 June 2026", 7, "interim_results", "interim"),
        ("Telia Company Year-end Report January – December 2025", 1, "final_results", "annual"),
        (
            "Interim Management Statement January-September 2025",
            10,
            "quarterly_update",
            "trading_update",
        ),
        ("Quarterly Report Q4 2025", 2, "final_results", "annual"),
        ("SKF Q2 2026: Continued margin improvement", 7, "interim_results", "interim"),
        (
            "Tele2 reports Q4 and full‑year 2025 results, proposing 65% dividend increase.",
            1,
            "final_results",
            "annual",
        ),
        (
            "Boliden Q4 2024: Future-proofing Boliden – Announced acquisition",
            2,
            "final_results",
            "annual",
        ),
        (
            "Highlights of Handelsbanken’s Annual Report January – December 2025",
            2,
            "final_results",
            "annual",
        ),
        (
            "Alfa Laval’s annual and sustainability report for 2025 published",
            3,
            "annual_report",
            "annual",
        ),
        ("Volvo Group publishes Annual Report 2025", 2, "annual_report", "annual"),
        ("Interim report Q1 1 April - 30 June 2026", 7, "quarterly_update", "trading_update"),
        ("Interim Report", 8, "interim_results", "interim"),
    ],
)
def test_classify_cision_release(title, month, kind, period):
    classified = classify_cision_release(title, datetime(2026, month, 15, tzinfo=UTC))
    assert classified is not None
    assert classified[:2] == (kind, period)


@pytest.mark.parametrize(
    "title",
    [
        "Invitation to the Volvo Group report on the second quarter 2026",
        "Invitation to Investor’s Q3 2026 webcast",
        "President and CEO comments on Q2 report",
        "Handelsbanken’s interim report for January – June 2026 will be presented Wednesday",
        "Filing of Form 20-F with SEC",
        "Ericsson Annual Report on Form 20-F filed with the SEC",
        "Correction to ESEF file attachment in Nordea’s annual reporting package 2024",
        "EVOLUTION AND GALAXY GAMING EXTEND MERGER AGREEMENT; APPROVALS ANTICIPATED IN Q1 2026",
        "Notice of Annual General Meeting of AB Volvo",
        "Share buybacks in Ericsson during the period September 2026",
        "Volvo and Waabi kick off customer operations in Texas",
        "",
    ],
)
def test_classify_cision_release_drops_noise(title):
    assert classify_cision_release(title, datetime(2026, 7, 15, tzinfo=UTC)) is None


def test_item_to_filing_rejects_other_newsrooms_and_old_items():
    when = NOW - timedelta(days=5)
    item = parse_cision_rss(_rss(_item("Interim report second quarter 2026", when, rid=7)))[0]
    row = cision_item_to_filing(item, newsroom="sandvik")
    assert row is not None
    assert row["source"] == "cision_direct"
    assert row["cision_release_id"] == "7"
    assert row["cision_period"] == row["period"] == "interim"
    assert row["has_body"] is False
    assert cision_item_to_filing(item, newsroom="skf") is None
    assert cision_item_to_filing(item, newsroom="sandvik", cutoff=NOW) is None


def test_fetch_resolves_report_pdf_and_applies_quota_and_refiling():
    items = [
        _item("Interim report second quarter 2026", NOW - timedelta(days=80), rid=10),
        _item("Interim report second quarter 2026", NOW - timedelta(days=79), rid=11),
        _item("Interim report first quarter 2026", NOW - timedelta(days=170), rid=12),
        _item("Sandvik AB Annual Report 2025", NOW - timedelta(days=210), rid=13),
        _item("Interim report fourth quarter 2025", NOW - timedelta(days=250), rid=14),
        _item("Interim report third quarter 2025", NOW - timedelta(days=350), rid=15),
        _item("Interim report second quarter 2025", NOW - timedelta(days=445), rid=16),
        _item("Interim report first quarter 2025", NOW - timedelta(days=535), rid=17),
        _item("Interim report fourth quarter 2024", NOW - timedelta(days=620), rid=18),
        _item("Interim report third quarter 2024", NOW - timedelta(days=715), rid=19),
        _item("Interim report second quarter 2023", NOW - timedelta(days=1180), rid=20),
        _item("Invitation: Presentation of Sandvik’s report", NOW - timedelta(days=90), rid=21),
    ]
    getter, calls = _fake_get(_rss(*items), pages={12: _release_page(12, attachment=False)})
    rows = fetch_filings_cision_direct(ticker="SAND.ST", http_get=getter)
    ids = [r["cision_release_id"] for r in rows]
    assert "10" not in ids  # superseded by the re-issue a day later
    assert "19" not in ids  # third quarterly beyond the quota
    assert "20" not in ids  # outside the lookback
    assert ids == ["11", "12", "13", "14", "15", "16", "18"]
    assert len(rows) <= CISION_MAX_ITEMS
    by_id = {r["cision_release_id"]: r for r in rows}
    assert by_id["11"]["url"] == "https://mb.cision.com/Main/208/11/119.pdf"
    assert by_id["11"]["release_url"].endswith(",c11")
    assert by_id["12"]["url"] == by_id["12"]["release_url"]
    assert sum("ListItems" in c for c in calls) == 1
    assert len(calls) == 1 + len(rows)


def test_fetch_listing_only_skips_release_pages_and_survives_errors():
    feed = _rss(_item("Interim report second quarter 2026", NOW - timedelta(days=80), rid=10))
    getter, calls = _fake_get(feed)
    rows = fetch_filings_cision_direct(ticker="SAND.ST", http_get=getter, resolve_attachments=False)
    assert [r["url"] for r in rows] == [rows[0]["release_url"]]
    assert len(calls) == 1

    getter, _ = _fake_get(feed, fail_pages=True)
    rows = fetch_filings_cision_direct(ticker="SAND.ST", http_get=getter)
    assert rows[0]["url"] == rows[0]["release_url"]

    def _down(url: str, *, timeout: int = 30) -> bytes:
        raise urllib.error.URLError("down")

    assert fetch_filings_cision_direct(ticker="SAND.ST", http_get=_down) == []
    assert fetch_filings_cision_direct(ticker="HM-B.ST", http_get=_down) == []


def test_report_attachment_url_takes_first_main_pdf():
    assert report_attachment_url(_release_page(5)) == "https://mb.cision.com/Main/208/5/59.pdf"
    assert report_attachment_url(_release_page(5, attachment=False)) is None


def test_kind_quota_keeps_newest_per_kind():
    rows = [{"cision_kind": "quarterly_update", "published_at": f"2026-0{m}-01"} for m in (1, 2, 3)]
    kept = select_rows_by_kind_quota(rows)
    assert [r["published_at"] for r in kept] == ["2026-03-01", "2026-02-01"]
    assert CISION_MAX_ITEMS == sum(CISION_KIND_QUOTAS.values()) <= 12


def test_period_bonus_surface_and_unextractable_wiring():
    row = {
        "source": "cision_direct",
        "headline": "Volvo Group – the second quarter 2026",
        "cision_period": "interim",
        "period": "interim",
        "url": "https://mb.cision.com/Main/39/4375280/4197349.pdf",
    }
    assert _apply_headline_period(row)["period"] == "interim"
    assert _source_bonus("cision_direct") == _source_bonus("amf_direct")
    assert filing_source_surface("omxs30", "VOLV-B.ST") == "euro_filings+cision_direct"
    assert filing_source_surface("euro_depth", "SKF-B.ST") == "euro_filings+cision_direct"
    assert filing_source_surface("omxs30", "HM-B.ST") == "euro_filings"
    assert "cision_direct" in UNEXTRACTABLE_BODY_SOURCES


def _cision_row(period: str, url: str, headline: str) -> dict:
    return {
        "id": f"cision-{period}",
        "source": "cision_direct",
        "headline": headline,
        "published_at": "2026-07-17T05:20:00+00:00",
        "url": url,
        "release_url": "https://news.cision.com/ab-volvo/r/volvo-group---the-second-quarter-2026,c4375280",
        "period": period,
        "cision_period": period,
        "cision_kind": "interim_results",
        "category": "Regulatory report",
        "has_body": False,
        "body_path": None,
        "priority": 100,
    }


def _euro_patches(cision_rows: list[dict] | None = None):
    return [
        patch("value_investor.research.filings.fetch_filings_esef_direct", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_belgium_official", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_euro_news", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_investegate_company", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_ir_allowlist", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_sec_edgar", return_value=[]),
        patch(
            "value_investor.research.filings.refresh_sources_yahoo_cashflow_metrics",
            return_value=None,
        ),
    ]


def test_ingest_filings_st_uses_cision_direct(tmp_path: Path):
    url = "https://mb.cision.com/Main/39/4375280/4197349.pdf"
    body = "Volvo Group report on the second quarter 2026. Net sales SEK 126.3 billion. " * 20
    patches = _euro_patches()
    for p in patches:
        p.start()
    try:
        with (
            patch(
                "value_investor.research.filings.fetch_filings_cision_direct",
                return_value=[_cision_row("interim", url, "Volvo Group – the second quarter 2026")],
            ) as cision,
            patch("value_investor.research.filings.fetch_filings_amf_direct") as amf,
            patch("value_investor.research.filings.fetch_filing_body", return_value=body),
        ):
            meta = ingest_filings(
                ticker="VOLV-B.ST",
                company_name="AB Volvo (publ)",
                sources_dir=tmp_path,
                market="omxs30",
            )
    finally:
        for p in patches:
            p.stop()
    cision.assert_called_once()
    amf.assert_not_called()
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert "Cision newsroom RSS" in index["note"]
    rows = [r for r in index["filings"] if r["source"] == "cision_direct"]
    assert len(rows) == 1
    assert rows[0]["has_body"] is True
    assert rows[0]["period"] == "interim"


def test_ingest_filings_unmapped_st_skips_cision(tmp_path: Path):
    patches = _euro_patches()
    for p in patches:
        p.start()
    try:
        with patch("value_investor.research.filings.fetch_filings_cision_direct") as cision:
            ingest_filings(
                ticker="HM-B.ST",
                company_name="H & M Hennes & Mauritz AB (publ)",
                sources_dir=tmp_path,
                market="omxs30",
            )
    finally:
        for p in patches:
            p.stop()
    cision.assert_not_called()


def test_load_exhaustion_releases_parked_mapped_swedish_names_only(tmp_path: Path):
    write_json(
        tmp_path / "markets" / "omxs30" / "ingest_exhaustion.json",
        {
            "market_id": "omxs30",
            "exhausted": True,
            "parked": [
                {"ticker": "SAND.ST", "reason": "awaiting_periodic_report"},
                {"ticker": "HM-B.ST", "reason": "awaiting_periodic_report"},
                {"ticker": "SKF-B.ST", "source_surface": "euro_filings+cision_direct"},
            ],
        },
        compact=False,
    )
    payload = load_ingest_exhaustion("omxs30", library_root=tmp_path)
    assert payload["surface_released"] == ["SAND.ST"]
    assert sorted(r["ticker"] for r in payload["parked"]) == ["HM-B.ST", "SKF-B.ST"]


def test_library_discovery_listing_includes_cision_without_page_fetches():
    from value_investor.library_discovery_scan import list_regime_filings_index_only

    row = _cision_row("interim", "https://news.cision.com/ab-volvo/r/x,c1", "Q2 2026")
    with (
        patch(
            "value_investor.library_discovery_scan.fetch_filings_cision_direct",
            return_value=[row],
        ) as cision,
        patch("value_investor.library_discovery_scan.fetch_filings_esef_direct", return_value=[]),
        patch(
            "value_investor.library_discovery_scan.fetch_filings_belgium_official",
            return_value=[],
        ),
        patch("value_investor.library_discovery_scan.fetch_filings_euro_news", return_value=[]),
        patch(
            "value_investor.library_discovery_scan.fetch_filings_investegate_company",
            return_value=[],
        ),
        patch("value_investor.library_discovery_scan.fetch_filings_ir_allowlist", return_value=[]),
        patch("value_investor.library_discovery_scan.fetch_filings_sec_edgar", return_value=[]),
    ):
        rows = list_regime_filings_index_only(
            ticker="VOLV-B.ST", company_name="AB Volvo (publ)", market="omxs30"
        )
    assert cision.call_args.kwargs["resolve_attachments"] is False
    assert [r["source"] for r in rows] == ["cision_direct"]


def _memo(root: Path, market: str, ticker: str, index: dict | None) -> None:
    ticker_dir = root / "markets" / market / "screen" / "research" / ticker
    filings_dir = ticker_dir / "sources" / "filings"
    filings_dir.mkdir(parents=True, exist_ok=True)
    (ticker_dir / "research.json").write_text(json.dumps({"signal": "buy"}), encoding="utf-8")
    if index is not None:
        (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")


def test_cision_direct_coverage_statuses_and_findings(tmp_path: Path):
    now = datetime(2026, 10, 6, tzinfo=UTC)
    fresh = (now - timedelta(days=1)).isoformat()
    note = "Euro-listed results discovery via ESEF, Cision newsroom RSS (news.cision.com)"
    body = {"source": "cision_direct", "has_body": True, "published_at": "2026-07-17"}
    covered = {
        "fetched_at": fresh,
        "note": note,
        "filings": [{**body, "period": "annual"}, {**body, "period": "interim"}],
    }
    _memo(tmp_path, "omxs30", "VOLV-B.ST", covered)
    _memo(tmp_path, "euro_depth", "VOLV-B.ST", covered)
    _memo(
        tmp_path,
        "omxs30",
        "SAND.ST",
        {"fetched_at": fresh, "note": note, "filings": [{**body, "period": "interim"}]},
    )
    for ticker in ("SKF-B.ST", "TELIA.ST"):
        _memo(
            tmp_path,
            "omxs30",
            ticker,
            {"fetched_at": fresh, "note": note, "filings": [{"source": "esef_direct"}]},
        )
    _memo(
        tmp_path,
        "omxs30",
        "BOL.ST",
        {
            "fetched_at": (now - timedelta(days=30)).isoformat(),
            "note": "Euro-listed results discovery via ESEF",
            "filings": [],
        },
    )
    _memo(tmp_path, "omxs30", "HM-B.ST", covered)

    with patch(
        "value_investor.cision_direct_coverage._screen_buy_tier",
        return_value={"VOLV-B.ST", "SAND.ST", "SKF-B.ST", "BOL.ST", "HM-B.ST"},
    ):
        payload = build_cision_direct_coverage(tmp_path, now=now)

    status = {r["ticker"]: r["status"] for r in payload["not_covered"]}
    assert status == {
        "SAND.ST": "partial",
        "SKF-B.ST": "silent",
        "TELIA.ST": "silent",
        "BOL.ST": "not_reingested",
    }
    summary = payload["summary"]
    assert summary["buy_tier"] == 4
    assert summary["buy_tier_covered"] == 1
    assert summary["silent"] == 2
    assert payload["markets"]["euro_depth"]["buy_tier_covered"] == 1

    findings = {f["title"]: f for f in ops_findings_from_cision_direct_coverage(payload)}
    assert findings[SILENT_FINDING_TITLE]["severity"] == "warn"
    assert "SKF-B.ST" in findings[SILENT_FINDING_TITLE]["summary"]
    assert "cision-direct-filings.md" in findings[COVERAGE_FINDING_TITLE]["summary"]
    assert "SAND.ST" in findings[COVERAGE_FINDING_TITLE]["summary"]
    assert all(f["auto_fixable"] is False for f in findings.values())


def test_check_cision_direct_coverage_persists_store(tmp_path: Path):
    from value_investor.ops_monitor import check_cision_direct_coverage

    _memo(
        tmp_path, "omxs30", "SAND.ST", {"fetched_at": datetime.now(UTC).isoformat(), "filings": []}
    )
    store = tmp_path / "cision_direct_coverage.json"
    with patch("value_investor.cision_direct_coverage._screen_buy_tier", return_value={"SAND.ST"}):
        findings = check_cision_direct_coverage(library_root=tmp_path, store_path=store)
    assert store.exists()
    assert json.loads(store.read_text(encoding="utf-8"))["observe_only"] is True
    assert [f.title for f in findings] == [COVERAGE_FINDING_TITLE]
    assert all(f.auto_fixable is False for f in findings)
