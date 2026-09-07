"""Tests for research source ingestion helpers."""

from pathlib import Path
from unittest.mock import patch

from value_investor.research.ingest import _strip_html, ingest_research_sources, merge_news_articles


def test_strip_html_removes_tags():
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_merge_news_articles_deduplicates_by_id():
    first = [{"id": "a", "title": "One", "published_at": "2026-07-01"}]
    second = [
        {"id": "a", "title": "One duplicate", "published_at": "2026-07-02"},
        {"id": "b", "title": "Two"},
    ]
    merged = merge_news_articles(first, second)
    assert len(merged) == 2
    assert {item["id"] for item in merged} == {"a", "b"}
    assert merged[0]["id"] == "a"
    assert merged[0]["title"] == "One duplicate"


@patch("value_investor.research.ingest.fetch_google_news_rss", return_value=[])
@patch("value_investor.research.ingest.fetch_yfinance_news", return_value=[])
@patch(
    "value_investor.research.ingest.fetch_annual_financials", return_value={"income_statement": {}}
)
@patch("value_investor.research.filings.ingest_filings")
@patch("value_investor.research.filings.refetch_ir_allowlist_filing_bodies")
@patch(
    "value_investor.research.filings.refetch_residual_filing_bodies", return_value={"fetched": 0}
)
def test_ingest_euro_updates_summary_when_ir_merge_adds_indexes(
    _mock_residual,
    mock_ir_refetch,
    mock_ingest_filings,
    _mock_financials,
    _mock_yf_news,
    _mock_google_news,
    tmp_path: Path,
):
    """Euro ingest must reflect IR allowlist merge even when body fetch returns 0."""
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir(parents=True)
    index_path = filings_dir / "filings_index.json"
    index_path.write_text(
        '{"summary": {"total": 2, "with_body": 0, "annual": 2}, '
        '"sources_used": ["ir_allowlist"], "filings": []}',
        encoding="utf-8",
    )
    mock_ingest_filings.return_value = {
        "filings_index_path": str(index_path),
        "filings_summary": {"total": 0, "with_body": 0, "annual": 0},
        "filings_sources": [],
    }
    mock_ir_refetch.return_value = {
        "fetched": 0,
        "merge": {"added": 2, "total_allowlist": 2},
    }

    meta = ingest_research_sources(
        ticker="AED.BR",
        company_name="Aedifica NV/SA",
        screening_snapshot={"ticker": "AED.BR", "name": "Aedifica NV/SA", "signal": "buy"},
        sources_dir=tmp_path,
        market="euro_depth",
        deepen_history=False,
    )

    assert int(meta["filings_summary"]["total"]) == 2
    assert meta["filings_sources"] == ["ir_allowlist"]
