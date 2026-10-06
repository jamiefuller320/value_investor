"""AMF open-data feed for French issuers (L545)."""

from __future__ import annotations

import json
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from value_investor.amf_direct_coverage import (
    COVERAGE_FINDING_TITLE,
    SILENT_FINDING_TITLE,
    build_amf_direct_coverage,
    ops_findings_from_amf_direct_coverage,
)
from value_investor.library_ingest_exhaustion import load_ingest_exhaustion
from value_investor.research.amf_direct import (
    AMF_KIND_QUOTAS,
    AMF_MAX_ITEMS,
    amf_issuer_filter,
    amf_ticker,
    classify_amf_record,
    fetch_filings_amf_direct,
    prefer_english_rows,
    record_subtype_code,
    select_rows_by_kind_quota,
)
from value_investor.research.filings import (
    _apply_headline_period,
    _source_bonus,
    filing_source_surface,
    ingest_filings,
)
from value_investor.storage import write_json

FR_IDENTITY = {"lei": "96950077L0TN7BAROX36", "lei_country": "FR"}


def _raw(
    code: str,
    title: str,
    when: datetime,
    *,
    lang: str = "Anglais",
    url: str | None = None,
    uin: str | None = None,
    lei: str = "96950077L0TN7BAROX36",
) -> dict:
    stamp = when.strftime("%Y%m%d%H%M%S")
    return {
        "informationdeposee_inf_stp_inf": code,
        "informationdeposee_inf_tit_inf": title,
        "informationdeposee_inf_dat_emt": when.isoformat(),
        "informationdeposee_inf_lng_inf": lang,
        "url_de_recuperation": url
        or f"https://fr.ftp.opendatasoft.com/datadila/INFOFI/MKW/FC{code}{stamp}{lang[:2]}.pdf",
        "uin_idt_uin": uin or f"{code}-{stamp}-{lang}",
        "identificationsociete_iso_cd_lei": lei,
        "subtype_of_information": "Inside Information",
    }


def _payload(rows: list[dict]) -> bytes:
    return json.dumps({"total_count": len(rows), "results": rows}).encode("utf-8")


def _fake_amf_get(periodic: list[dict], inside: list[dict]):
    calls: list[str] = []

    def _get(url: str, *, timeout: int = 30) -> bytes:
        calls.append(url)
        where = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["where"][0]
        return _payload(inside if "search(" in where else periodic)

    return _get, calls


def _days_ago(days: int) -> datetime:
    return datetime.now(UTC).replace(microsecond=0) - timedelta(days=days)


def test_amf_ticker_only_for_paris():
    assert amf_ticker("CAP.PA") == "CAP"
    assert amf_ticker("ai.pa") == "AI"
    assert amf_ticker("ASML.AS") is None
    assert amf_ticker("SAP.DE") is None


def test_issuer_filter_prefers_ticker_then_french_lei():
    assert amf_issuer_filter("CAP.PA", {"lei": "X" * 20, "lei_country": "DE"}) == (
        'identificationsociete_iso_code_tkr_iso_cd_tkr="CAP"'
    )
    fr_elsewhere = {"lei": "549300M3VH1A3ER1TB49", "lei_country": "FR"}
    assert amf_issuer_filter("EL.AS", fr_elsewhere) == (
        'identificationsociete_iso_cd_lei="549300M3VH1A3ER1TB49"'
    )
    assert amf_issuer_filter("SAP.DE", {"lei": "529900D6BF99LW9R2E68", "lei_country": "DE"}) is None
    assert amf_issuer_filter("BAD.AS", {"lei": "short", "lei_country": "FR"}) is None


@pytest.mark.parametrize(
    ("code", "title", "month", "kind", "period"),
    [
        ("001007", "Full-year 2025 results", 2, "final_results", "annual"),
        ("001007", "Résultats de l'année 2025", 2, "final_results", "annual"),
        ("001007", "VINCI - 2024 Annual Results", 2, "final_results", "annual"),
        (
            "001007",
            "EssilorLuxottica: Q4/FY 2025 Results - Revenue growing",
            2,
            "final_results",
            "annual",
        ),
        ("001007", "Résultats du 1er semestre 2025", 7, "interim_results", "interim"),
        (
            "001007",
            "UNIBAIL-RODAMCO-WESTFIELD REPORTS H1-2026 EARNINGS",
            7,
            "interim_results",
            "interim",
        ),
        (
            "001007",
            "Bouygues: Very strong Group performance in first-half 2026, Outlook for the full-year",
            7,
            "interim_results",
            "interim",
        ),
        (
            "001007",
            "Bouygues: Strong first-quarter 2026 Group results, outlook for the full-year confirmed",
            5,
            "quarterly_update",
            "trading_update",
        ),
        (
            "001007",
            "Chiffre d'affaires du 1er trimestre 2026",
            4,
            "quarterly_update",
            "trading_update",
        ),
        ("001007", "Capgemini Q3 2025 revenues", 10, "quarterly_update", "trading_update"),
        # Generic titles fall back to the filing month.
        (
            "001007",
            "Inside Information / News release on accounts, results",
            2,
            "final_results",
            "annual",
        ),
        (
            "001007",
            "Inside Information / News release on accounts, results",
            7,
            "interim_results",
            "interim",
        ),
        (
            "001007",
            "Inside Information / News release on accounts, results",
            4,
            "quarterly_update",
            "trading_update",
        ),
        (
            "001006",
            "Press release: 2025: strong sales and EPS growth",
            1,
            "final_results",
            "annual",
        ),
        (
            "001006",
            "Press Release: Q1 2026: double-digit sales and business EPS growth",
            4,
            "quarterly_update",
            "trading_update",
        ),
        ("004000", "2026 INTERIM FINANCIAL REPORT", 8, "half_year_report", "interim"),
        ("004000", "Rapport financier semestriel 2026", 7, "half_year_report", "interim"),
        ("004000", "LVMH 2025 Consolidated Financial Statements", 2, "annual_report", "annual"),
        ("004000", "LVMH 2024 Consolidated FInancial Staement", 2, "annual_report", "annual"),
        ("002002", "RAPPORT FINANCIER ANNUEL 2024", 4, "annual_report", "annual"),
        ("005001", "First-quarter 2026 Sales", 5, "quarterly_update", "trading_update"),
    ],
)
def test_classify_amf_record_periods(code, title, month, kind, period):
    published = datetime(2026, month, 15, tzinfo=UTC)
    classified = classify_amf_record(code, title, published)
    assert classified is not None
    assert classified[:2] == (kind, period)


@pytest.mark.parametrize(
    ("code", "title"),
    [
        ("002009", "Notice of publication of the 2025 Universal Registration Document"),
        ("002002", "Orange: Publication of the 2025 Universal Registration Document"),
        ("001006", "Press release: Filing of the 2025 U.S. Form 20-F and French DEU"),
        ("001006", "Communiqué de presse : Dépôt du Document d'Enregistrement Universel 2025"),
        ("001007", "VINCI : Publication des comptes consolidés certifiés au 31 décembre 2025"),
        ("002003", "Half yearly financial reports / Terms of availability of the report"),
        ("001006", "Press Release : Availability of the aide-mémoire for Q3 2026 results"),
        ("001006", "Press Release: Sanofi's brivekimig phase 2 study results in HS"),
        ("001006", "Orange announces the results of its tender offer on outstanding hybrids"),
        ("001007", "Assemblée Générale du 19 mai 2026 : résultats des votes"),
        ("001006", "LVMH 2025 Dividend"),
        ("001006", "Capgemini and Google Cloud expand strategic partnership"),
        ("001002", "Capgemini to acquire WNS to create a global leader"),
        ("013007", "Disclosure of trading in own shares"),
        ("006000", "Total number of voting rights"),
    ],
)
def test_classify_amf_record_drops_noise(code, title):
    assert classify_amf_record(code, title, datetime(2026, 2, 10, tzinfo=UTC)) is None


def test_record_subtype_code_handles_multi_tagged_records():
    assert record_subtype_code("001007") == "001007"
    assert record_subtype_code('["006000", "001008"]') == "001008"
    assert record_subtype_code(["001006", "013006"]) == "001006"
    assert record_subtype_code(None) == ""


def test_fetch_filings_amf_direct_parses_both_queries_and_prefers_english():
    fy = _days_ago(230)
    h1 = _days_ago(60)
    periodic = [
        _raw("004000", "2026 INTERIM FINANCIAL REPORT", h1 + timedelta(days=4)),
        _raw(
            "004000", "RAPPORT FINANCIER SEMESTRIEL 2026", h1 + timedelta(days=4), lang="Français"
        ),
        _raw("001007", "Full-year 2025 results", fy),
        _raw("001007", "Résultats de l'année 2025", fy, lang="Français"),
        _raw("001007", "Résultats du 1er semestre 2026", h1, lang="Français"),
        _raw("004000", "Annual report", fy, url="https://fr.ftp.opendatasoft.com/x/FC1.zip"),
    ]
    inside = [
        _raw("001006", "Press release: Q1 2026: double-digit sales growth", _days_ago(150)),
        _raw("001006", "Press release: Availability of the Q1 2026 aide-mémoire", _days_ago(170)),
    ]
    getter, calls = _fake_amf_get(periodic, inside)
    rows = fetch_filings_amf_direct(ticker="CAP.PA", identity={}, http_get=getter)

    assert len(calls) == 2
    assert all("identificationsociete_iso_code_tkr_iso_cd_tkr" in c for c in calls)
    by_headline = {r["headline"]: r for r in rows}
    assert set(by_headline) == {
        "2026 INTERIM FINANCIAL REPORT",
        "Full-year 2025 results",
        "Résultats du 1er semestre 2026",
        "Press release: Q1 2026: double-digit sales growth",
    }
    interim = by_headline["2026 INTERIM FINANCIAL REPORT"]
    assert interim["source"] == "amf_direct"
    assert interim["period"] == interim["amf_period"] == "interim"
    assert interim["amf_language"] == "en"
    assert interim["url"].endswith(".pdf")
    assert interim["has_body"] is False
    # French-only filing is kept when no English twin exists.
    assert by_headline["Résultats du 1er semestre 2026"]["amf_language"] == "fr"
    assert by_headline["Full-year 2025 results"]["period"] == "annual"


def test_fetch_filings_amf_direct_drops_refilings_but_keeps_generic_quarterly_titles():
    generic = "Inside Information / News release on accounts, results"
    periodic = [
        _raw("004000", "VINCI: Half-year financial report at 30 June 2026", _days_ago(60)),
        _raw("004000", "VINCI: Half-year financial report at 30 June 2026", _days_ago(64)),
        _raw("001007", generic, datetime(2026, 7, 30, tzinfo=UTC)),
        _raw("001007", generic, datetime(2025, 7, 31, tzinfo=UTC)),
    ]
    getter, _ = _fake_amf_get(periodic, [])
    rows = fetch_filings_amf_direct(
        ticker="DG.PA", identity={}, http_get=getter, lookback_days=5000
    )
    half_year = [r for r in rows if r["amf_kind"] == "half_year_report"]
    results = [r for r in rows if r["amf_kind"] == "interim_results"]
    assert len(half_year) == 1
    assert len(results) == 2


def test_fetch_filings_amf_direct_keeps_dominant_issuer_on_reused_ticker():
    periodic = [_raw("001007", f"Q{q} revenues", _days_ago(30 * q)) for q in (1, 3)]
    periodic.append(_raw("001007", "Full-year results", _days_ago(200), lei="OTHERISSUERLEI000000"))
    getter, _ = _fake_amf_get(periodic, [])
    rows = fetch_filings_amf_direct(ticker="CAP.PA", identity={}, http_get=getter)
    assert {r["amf_issuer_lei"] for r in rows} == {"96950077L0TN7BAROX36"}


def test_fetch_filings_amf_direct_skips_ineligible_and_survives_errors():
    def _boom(url, *, timeout=30):
        raise OSError("down")

    assert fetch_filings_amf_direct(ticker="SAP.DE", identity={}, http_get=_boom) == []
    assert fetch_filings_amf_direct(ticker="CAP.PA", identity={}, http_get=_boom) == []


def test_kind_quota_keeps_newest_per_kind_within_body_budget():
    assert AMF_MAX_ITEMS == sum(AMF_KIND_QUOTAS.values()) <= 12
    rows = [
        {"amf_kind": "quarterly_update", "published_at": f"2026-0{m}-01", "id": str(m)}
        for m in range(1, 6)
    ]
    kept = select_rows_by_kind_quota(rows)
    assert [r["id"] for r in kept] == ["5", "4"]


def test_prefer_english_rows_keys_on_day_and_subtype_not_kind():
    rows = [
        {
            "published_at": "2025-02-12T10:00",
            "amf_subtype": "004000",
            "amf_language": "en",
            "amf_kind": "half_year_report",
        },
        {
            "published_at": "2025-02-12T10:00",
            "amf_subtype": "004000",
            "amf_language": "fr",
            "amf_kind": "annual_report",
        },
        {
            "published_at": "2025-07-30T10:00",
            "amf_subtype": "001007",
            "amf_language": "fr",
            "amf_kind": "interim_results",
        },
    ]
    kept = prefer_english_rows(rows)
    assert [(r["amf_language"], r["amf_subtype"]) for r in kept] == [
        ("en", "004000"),
        ("fr", "001007"),
    ]


def test_apply_headline_period_keeps_amf_period_for_french_titles():
    row = {
        "id": "x",
        "source": "amf_direct",
        "headline": "Résultats du 1er semestre 2025",
        "period": "interim",
        "amf_period": "interim",
        "published_at": "2025-07-30T06:00:00+00:00",
    }
    assert _apply_headline_period(row)["period"] == "interim"
    quarterly = {**row, "headline": "Chiffre d'affaires T3 2025", "amf_period": "trading_update"}
    assert _apply_headline_period(quarterly)["period"] == "trading_update"


def test_source_bonus_matches_other_direct_exchange_feeds():
    assert _source_bonus("amf_direct") == _source_bonus("hkex_direct") == 27
    assert _source_bonus("amf_direct") > _source_bonus("esef_direct")


def _amf_row(period: str, url: str, headline: str) -> dict:
    return {
        "id": f"amf-{period}",
        "source": "amf_direct",
        "headline": headline,
        "published_at": "2026-07-30T06:00:00+00:00",
        "url": url,
        "period": period,
        "amf_period": period,
        "amf_kind": "interim_results" if period == "interim" else "final_results",
        "category": "Inside Information",
        "has_body": False,
        "body_path": None,
        "priority": 100,
    }


def test_ingest_filings_euro_pa_uses_amf_direct(tmp_path: Path):
    url = "https://fr.ftp.opendatasoft.com/datadila/INFOFI/MKW/2026/07/FCMKW135092_20260730.pdf"
    body = "Capgemini first-half 2026 results. Revenues and operating margin. " * 20
    with (
        patch(
            "value_investor.research.filings.fetch_filings_amf_direct",
            return_value=[_amf_row("interim", url, "Résultats du 1er semestre 2026")],
        ) as amf,
        patch("value_investor.research.filings.fetch_filings_esef_direct", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_belgium_official", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_euro_news", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_investegate_company", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_ir_allowlist", return_value=[]),
        patch("value_investor.research.filings.fetch_filing_body", return_value=body),
        patch("value_investor.research.filings.fetch_filings_sec_edgar", return_value=[]),
        patch(
            "value_investor.research.filings.refresh_sources_yahoo_cashflow_metrics",
            return_value=None,
        ),
    ):
        meta = ingest_filings(
            ticker="CAP.PA",
            company_name="Capgemini SE",
            sources_dir=tmp_path,
            market="cac40",
        )
    amf.assert_called_once()
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert index["regime"] == "euro_filings"
    assert "AMF open data" in index["note"]
    rows = [r for r in index["filings"] if r["source"] == "amf_direct"]
    assert len(rows) == 1
    assert rows[0]["has_body"] is True
    assert rows[0]["period"] == "interim"


def test_ingest_filings_euro_non_french_skips_amf(tmp_path: Path):
    with (
        patch("value_investor.research.filings.fetch_filings_amf_direct") as amf,
        patch("value_investor.research.filings.amf_eligible", return_value=False),
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
    ):
        ingest_filings(
            ticker="SAP.DE",
            company_name="SAP SE",
            sources_dir=tmp_path,
            market="dax",
        )
    amf.assert_not_called()


def test_filing_source_surface_marks_amf_adapter():
    assert filing_source_surface("cac40", "CAP.PA") == "euro_filings+amf_direct"
    assert filing_source_surface("euro_stoxx50", "MC.PA") == "euro_filings+amf_direct"
    with patch("value_investor.research.amf_direct._cached_identity", return_value={}):
        assert filing_source_surface("dax", "SAP.DE") == "euro_filings"
    with patch("value_investor.research.amf_direct._cached_identity", return_value=FR_IDENTITY):
        assert filing_source_surface("aex", "XYZ.AS") == "euro_filings+amf_direct"


def test_load_exhaustion_releases_parked_french_names_only(tmp_path: Path):
    write_json(
        tmp_path / "markets" / "cac40" / "ingest_exhaustion.json",
        {
            "market_id": "cac40",
            "exhausted": True,
            "parked": [
                {"ticker": "CAP.PA", "reason": "awaiting_periodic_report"},
                {"ticker": "SAN.PA", "source_surface": "euro_filings+amf_direct"},
            ],
        },
        compact=False,
    )
    write_json(
        tmp_path / "markets" / "dax" / "ingest_exhaustion.json",
        {"market_id": "dax", "exhausted": True, "parked": [{"ticker": "SAP.DE"}]},
        compact=False,
    )
    cac = load_ingest_exhaustion("cac40", library_root=tmp_path)
    assert cac["surface_released"] == ["CAP.PA"]
    assert [r["ticker"] for r in cac["parked"]] == ["SAN.PA"]
    with patch("value_investor.research.amf_direct._cached_identity", return_value={}):
        dax = load_ingest_exhaustion("dax", library_root=tmp_path)
    assert dax["surface_released"] == []
    assert [r["ticker"] for r in dax["parked"]] == ["SAP.DE"]


def test_library_discovery_listing_includes_amf_for_pa():
    from value_investor.library_discovery_scan import list_regime_filings_index_only

    url = "https://fr.ftp.opendatasoft.com/datadila/INFOFI/MKW/2026/07/FCMKW1.pdf"
    with (
        patch(
            "value_investor.library_discovery_scan.fetch_filings_amf_direct",
            return_value=[_amf_row("interim", url, "First-half 2026 results")],
        ) as amf,
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
            ticker="CAP.PA", company_name="Capgemini SE", market="cac40"
        )
    amf.assert_called_once()
    assert [r["source"] for r in rows] == ["amf_direct"]


def _memo(root: Path, market: str, ticker: str, index: dict | None) -> None:
    ticker_dir = root / "markets" / market / "screen" / "research" / ticker
    filings_dir = ticker_dir / "sources" / "filings"
    filings_dir.mkdir(parents=True, exist_ok=True)
    (ticker_dir / "research.json").write_text(json.dumps({"signal": "buy"}), encoding="utf-8")
    if index is not None:
        (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")


def test_amf_direct_coverage_statuses_and_findings(tmp_path: Path):
    now = datetime(2026, 10, 6, tzinfo=UTC)
    fresh = (now - timedelta(days=1)).isoformat()
    note = "Euro-listed results discovery via ESEF, AMF open data (info-financiere.gouv.fr)"
    body = {"source": "amf_direct", "has_body": True, "published_at": "2026-07-30"}
    covered = {
        "fetched_at": fresh,
        "note": note,
        "filings": [{**body, "period": "annual"}, {**body, "period": "interim"}],
    }
    # Same name in two markets counts once in the summary.
    _memo(tmp_path, "cac40", "CAP.PA", covered)
    _memo(tmp_path, "euro_stoxx50", "CAP.PA", covered)
    _memo(
        tmp_path,
        "cac40",
        "SAN.PA",
        {"fetched_at": fresh, "note": note, "filings": [{**body, "period": "interim"}]},
    )
    for ticker in ("DG.PA", "EN.PA"):
        _memo(
            tmp_path,
            "cac40",
            ticker,
            {
                "fetched_at": fresh,
                "note": note,
                "filings": [{"source": "google_news_euro", "period": "annual"}],
            },
        )
    _memo(
        tmp_path,
        "cac40",
        "RI.PA",
        {
            "fetched_at": (now - timedelta(days=30)).isoformat(),
            "note": "Euro-listed results discovery via ESEF",
            "filings": [],
        },
    )
    _memo(tmp_path, "cac40", "SAP.DE", covered)

    with (
        patch(
            "value_investor.amf_direct_coverage._screen_buy_tier",
            return_value={"CAP.PA", "SAN.PA", "DG.PA", "RI.PA", "SAP.DE"},
        ),
        patch("value_investor.research.amf_direct._cached_identity", return_value={}),
    ):
        payload = build_amf_direct_coverage(tmp_path, markets=("cac40", "euro_stoxx50"), now=now)

    status = {r["ticker"]: r["status"] for r in payload["not_covered"]}
    assert status == {
        "SAN.PA": "partial",
        "DG.PA": "silent",
        "EN.PA": "silent",
        "RI.PA": "not_reingested",
    }
    summary = payload["summary"]
    assert summary["buy_tier"] == 4
    assert summary["buy_tier_covered"] == 1
    assert summary["silent"] == 2
    assert payload["markets"]["euro_stoxx50"]["buy_tier_covered"] == 1
    assert payload["markets"]["cac40"]["buy_tier_covered"] == 1

    findings = {f["title"]: f for f in ops_findings_from_amf_direct_coverage(payload)}
    assert findings[SILENT_FINDING_TITLE]["severity"] == "warn"
    assert "DG.PA" in findings[SILENT_FINDING_TITLE]["summary"]
    assert findings[COVERAGE_FINDING_TITLE]["severity"] == "info"
    assert "SAN.PA" in findings[COVERAGE_FINDING_TITLE]["summary"]
    assert all(f["auto_fixable"] is False for f in findings.values())


def test_amf_direct_coverage_quiet_when_covered(tmp_path: Path):
    body = {"source": "amf_direct", "has_body": True}
    _memo(
        tmp_path,
        "cac40",
        "CAP.PA",
        {
            "fetched_at": datetime.now(UTC).isoformat(),
            "filings": [{**body, "period": "annual"}, {**body, "period": "interim"}],
        },
    )
    with patch("value_investor.amf_direct_coverage._screen_buy_tier", return_value={"CAP.PA"}):
        payload = build_amf_direct_coverage(tmp_path, markets=("cac40",))
    assert payload["summary"]["buy_tier_coverage"] == 1.0
    assert ops_findings_from_amf_direct_coverage(payload) == []


def test_check_amf_direct_coverage_persists_store(tmp_path: Path):
    from value_investor.ops_monitor import check_amf_direct_coverage

    _memo(tmp_path, "cac40", "CAP.PA", {"fetched_at": datetime.now(UTC).isoformat(), "filings": []})
    store = tmp_path / "amf_direct_coverage.json"
    with patch("value_investor.amf_direct_coverage._screen_buy_tier", return_value={"CAP.PA"}):
        findings = check_amf_direct_coverage(library_root=tmp_path, store_path=store)
    assert store.exists()
    assert json.loads(store.read_text(encoding="utf-8"))["observe_only"] is True
    assert [f.title for f in findings] == [COVERAGE_FINDING_TITLE]
    assert all(f.auto_fixable is False for f in findings)
