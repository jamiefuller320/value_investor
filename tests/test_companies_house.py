"""Tests for Companies House client + historical deepen (mocked HTTP)."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from unittest.mock import patch

from value_investor.research.companies_house import (
    DEEPEN_MAX_ACCOUNTS,
    DEFAULT_MAX_ACCOUNTS,
    _StripAuthOnRedirect,
    fetch_accounts_filing_rows,
    fetch_filings_companies_house,
    load_company_number_map,
    resolve_company_number,
    save_company_number_map,
    search_company_number,
)
from value_investor.research.deepen_sources import deepen_sources_for_memo_tickers
from value_investor.research.document import ResearchDocument
from value_investor.research.filings import (
    fetch_filings_ir_allowlist,
    ingest_filings,
    load_ir_url_allowlist,
)
from value_investor.research.store import ResearchStore


def test_strip_auth_on_redirect_drops_authorization():
    handler = _StripAuthOnRedirect()
    req = urllib.request.Request(
        "https://document-api.company-information.service.gov.uk/document/x/content",
        headers={
            "Authorization": "Basic dGVzdDo=",
            "Accept": "application/pdf",
            "User-Agent": "test",
        },
        method="GET",
    )
    # Minimal fake redirect response headers
    class _Hdrs(dict):
        def get_all(self, name, default=None):  # noqa: ANN001
            return [self[name]] if name in self else default

    headers = _Hdrs({"Location": "https://s3.eu-west-2.amazonaws.com/bucket/doc?X-Amz-Algorithm=AWS4"})
    new_req = handler.redirect_request(
        req,
        fp=None,
        code=302,
        msg="Found",
        headers=headers,
        newurl=headers["Location"],
    )
    assert new_req is not None
    assert "Authorization" not in new_req.headers
    assert "authorization" not in {k.lower() for k in new_req.headers}
    assert new_req.get_header("Accept") == "application/pdf"


def test_load_and_save_company_number_map(tmp_path: Path):
    path = tmp_path / "ch.json"
    save_company_number_map({"SHEL.L": "00006400"}, path)
    mapping = load_company_number_map(path)
    assert mapping["SHEL.L"] == "00006400"
    save_company_number_map({"BP.L": "00102498"}, path)
    mapping = load_company_number_map(path)
    assert mapping["SHEL.L"] == "00006400"
    assert mapping["BP.L"] == "00102498"


def test_fetch_filings_companies_house_noop_without_api_key(monkeypatch):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    rows = fetch_filings_companies_house(
        ticker="SHEL.L",
        company_name="Shell plc",
    )
    assert rows == []


def test_search_company_number_prefers_active_name_overlap(monkeypatch):
    payload = {
        "items": [
            {
                "company_number": "99999999",
                "title": "SHELLAC COATINGS LTD",
                "company_status": "dissolved",
            },
            {
                "company_number": "00006400",
                "title": "SHELL PLC",
                "company_status": "active",
            },
        ]
    }

    def fake_get(url, *, api_key, accept="application/json", timeout=60.0, retries=2):
        return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(
        "value_investor.research.companies_house._ch_get",
        fake_get,
    )
    number = search_company_number(
        company_name="Shell plc",
        ticker="SHEL.L",
        api_key="test-key",
    )
    assert number == "00006400"


def test_resolve_company_number_uses_cache_before_search(tmp_path: Path, monkeypatch):
    path = tmp_path / "ch.json"
    save_company_number_map({"SHEL.L": "00006400"}, path)
    called = {"search": 0}

    def boom(*args, **kwargs):
        called["search"] += 1
        raise AssertionError("should not search when cached")

    monkeypatch.setattr(
        "value_investor.research.companies_house.search_company_number",
        boom,
    )
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")
    number = resolve_company_number(
        ticker="SHEL.L",
        company_name="Shell plc",
        map_path=path,
    )
    assert number == "00006400"
    assert called["search"] == 0


def test_fetch_accounts_filing_rows_limits_and_shapes(monkeypatch):
    items = []
    for i in range(8):
        items.append(
            {
                "transaction_id": f"tx{i}",
                "description": f"accounts-with-accounts-type-full-{i}",
                "date": f"202{i % 5}-03-15",
                "links": {
                    "document_metadata": (
                        f"https://document-api.company-information.service.gov.uk/"
                        f"document/{i}"
                    )
                },
            }
        )
    payload = {"items": items}

    monkeypatch.setattr(
        "value_investor.research.companies_house._ch_get",
        lambda *a, **k: json.dumps(payload).encode("utf-8"),
    )
    monkeypatch.setattr(
        "value_investor.research.companies_house.time.sleep",
        lambda *_a, **_k: None,
    )
    rows = fetch_accounts_filing_rows(
        company_number="00006400",
        api_key="test-key",
        max_accounts=3,
    )
    assert len(rows) == 3
    assert rows[0]["source"] == "companies_house"
    assert rows[0]["period"] == "annual"
    assert rows[0]["document_metadata_url"].startswith("https://")


def test_ingest_filings_merges_companies_house_and_deepens(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")
    ch_rows = [
        {
            "id": "ch_00006400_tx1",
            "source": "companies_house",
            "headline": "Companies House accounts — full",
            "published_at": "2025-03-15T00:00:00+00:00",
            "url": "https://document-api.example/doc/1",
            "period": "annual",
            "category": "accounts",
            "summary": "full",
            "has_body": False,
            "body_path": None,
            "priority": 140,
            "document_metadata_url": "https://document-api.example/doc/1",
        }
    ]
    with (
        patch("value_investor.research.filings.fetch_filings_ticker_api", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_google_news", return_value=[]),
        patch(
            "value_investor.research.companies_house.fetch_filings_companies_house",
            return_value=ch_rows,
        ) as ch_mock,
        patch(
            "value_investor.research.filings._fetch_companies_house_body",
            return_value="A" * 250 + " pension deficit going concern",
        ),
        patch("value_investor.research.filings.fetch_filings_ir_allowlist", return_value=[]),
    ):
        meta = ingest_filings(
            ticker="SHEL.L",
            company_name="Shell plc",
            sources_dir=tmp_path,
            market="ftse350",
            deepen_history=True,
        )

    assert ch_mock.call_args.kwargs["max_accounts"] == DEEPEN_MAX_ACCOUNTS
    assert meta["filings_summary"]["annual"] == 1
    assert meta["filings_summary"]["with_body"] == 1
    assert "companies_house" in meta["filings_sources"]


def test_ingest_filings_default_ch_accounts_not_deepen(tmp_path: Path):
    with (
        patch("value_investor.research.filings.fetch_filings_ticker_api", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_google_news", return_value=[]),
        patch(
            "value_investor.research.companies_house.fetch_filings_companies_house",
            return_value=[],
        ) as ch_mock,
        patch("value_investor.research.filings.fetch_filings_ir_allowlist", return_value=[]),
    ):
        ingest_filings(
            ticker="SHEL.L",
            company_name="Shell plc",
            sources_dir=tmp_path,
            market="ftse350",
            deepen_history=False,
        )
    assert ch_mock.call_args.kwargs["max_accounts"] == DEFAULT_MAX_ACCOUNTS


def test_ir_allowlist_load_and_fetch(tmp_path: Path):
    path = tmp_path / "ir.json"
    path.write_text(
        json.dumps(
            {
                "urls": {
                    "HIK.L": [
                        "https://www.hikma.com/investors/annual-report-2024.pdf",
                        "https://www.hikma.com/investors/interim-results.pdf",
                    ],
                    "SHEL.L": [
                        "https://www.sec.gov/Archives/edgar/data/1306965/000162828026017024/shel-20251231.htm",
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    mapping = load_ir_url_allowlist(path)
    assert len(mapping["HIK.L"]) == 2
    rows = fetch_filings_ir_allowlist("HIK.L", path=path)
    assert len(rows) == 2
    assert rows[0]["source"] == "ir_allowlist"
    assert rows[0]["period"] == "annual"
    assert rows[1]["period"] == "interim"
    shel = fetch_filings_ir_allowlist("SHEL.L", path=path)
    assert len(shel) == 1
    assert shel[0]["period"] == "annual"


def test_deepen_sources_for_memo_tickers(tmp_path: Path):
    store = ResearchStore(tmp_path)
    doc = ResearchDocument(
        ticker="EXAM.L",
        name="Example PLC",
        signal="buy",
        version=1,
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-01T00:00:00+00:00",
        mode="initial",
        executive_summary="Summary",
    )
    store.save(doc)

    with patch(
        "value_investor.research.deepen_sources.ingest_research_sources",
        return_value={
            "filings_summary": {"total": 5, "with_body": 3, "annual": 2},
        },
    ) as ingest_mock:
        result = deepen_sources_for_memo_tickers(
            output_dir=tmp_path,
            tickers=["EXAM.L"],
            market="ftse350",
        )

    assert len(result.deepened) == 1
    assert result.deepened[0]["ticker"] == "EXAM.L"
    assert result.deepened[0]["filings_with_body"] == 3
    assert ingest_mock.call_args.kwargs["deepen_history"] is True
    summary_path = tmp_path / "deepen_sources_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert "not backdated" in payload["note"]


def test_deepen_sources_skips_missing_memo(tmp_path: Path):
    result = deepen_sources_for_memo_tickers(
        output_dir=tmp_path,
        tickers=["MISSING.L"],
        market="ftse350",
    )
    assert result.skipped == ["MISSING.L"]
    assert result.deepened == []
