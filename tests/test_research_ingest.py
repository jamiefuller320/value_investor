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
def test_ingest_tsx60_runs_ir_allowlist_refetch_like_euro(
    _mock_residual,
    mock_ir_refetch,
    mock_ingest_filings,
    _mock_financials,
    _mock_yf_news,
    _mock_google_news,
    tmp_path: Path,
):
    """eng-20260912-21: TSX ingest must merge/fetch builtin IR allowlist (SU.TO SEC exhibits)."""
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir(parents=True)
    index_path = filings_dir / "filings_index.json"
    index_path.write_text(
        '{"summary": {"total": 43, "with_body": 26, "annual": 5}, '
        '"sources_used": ["sec_edgar"], "filings": []}',
        encoding="utf-8",
    )
    mock_ingest_filings.return_value = {
        "filings_index_path": str(index_path),
        "filings_summary": {"total": 43, "with_body": 26, "annual": 5},
        "filings_sources": ["sec_edgar"],
    }

    def _ir_refetch_side_effect(filings_dir, ticker, **kwargs):
        index_path.write_text(
            '{"summary": {"total": 48, "with_body": 31, "annual": 5}, '
            '"sources_used": ["sec_edgar", "ir_allowlist"], "filings": []}',
            encoding="utf-8",
        )
        return {
            "fetched": 5,
            "merge": {"added": 5, "total_allowlist": 5},
        }

    mock_ir_refetch.side_effect = _ir_refetch_side_effect

    meta = ingest_research_sources(
        ticker="SU.TO",
        company_name="Suncor Energy Inc.",
        screening_snapshot={"ticker": "SU.TO", "name": "Suncor Energy Inc.", "signal": "buy"},
        sources_dir=tmp_path,
        market="tsx60",
        deepen_history=False,
    )

    mock_ir_refetch.assert_called_once()
    assert mock_ir_refetch.call_args.kwargs["ticker"] == "SU.TO"
    assert int(meta["filings_summary"]["with_body"]) == 31
    assert "ir_allowlist" in meta["filings_sources"]


@patch("value_investor.research.ingest.fetch_google_news_rss", return_value=[])
@patch("value_investor.research.ingest.fetch_yfinance_news", return_value=[])
@patch(
    "value_investor.research.ingest.fetch_annual_financials", return_value={"income_statement": {}}
)
@patch("value_investor.research.filings.ingest_filings")
@patch("value_investor.research.filings.extract_ir_presentation_metrics")
@patch("value_investor.research.filings.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.filings.fetch_filings_ir_allowlist")
def test_eng_20260921_02_uk_ingest_runs_ir_results_presentation_pipeline(
    mock_ir_rows,
    mock_ir_refetch,
    mock_extract_metrics,
    mock_ingest_filings,
    _mock_financials,
    _mock_yf_news,
    _mock_google_news,
    tmp_path: Path,
):
    """eng-20260921-02: FTSE IR allowlist tickers refetch decks and write ir_presentation_metrics."""
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir(parents=True)
    index_path = filings_dir / "filings_index.json"
    index_path.write_text(
        '{"summary": {"total": 5, "with_body": 2, "annual": 2}, '
        '"sources_used": ["investegate_direct"], "filings": []}',
        encoding="utf-8",
    )
    mock_ingest_filings.return_value = {
        "filings_index_path": str(index_path),
        "filings_summary": {"total": 5, "with_body": 2, "annual": 2},
        "filings_sources": ["investegate_direct"],
    }
    mock_ir_rows.return_value = [{"id": "ir_f5cc65dca4e5855a", "source": "ir_allowlist"}]
    mock_ir_refetch.return_value = {
        "fetched": 1,
        "merge": {"added": 1, "total_allowlist": 4},
        "with_body_after": 3,
    }
    mock_extract_metrics.return_value = {
        "bridge_count": 2,
        "segment_split_count": 0,
        "lease_maturity_count": 0,
        "mandatory": True,
    }

    meta = ingest_research_sources(
        ticker="FGP.L",
        company_name="FirstGroup plc",
        screening_snapshot={"ticker": "FGP.L", "name": "FirstGroup plc", "signal": "strong_buy"},
        sources_dir=tmp_path,
        market="ftse350",
        deepen_history=False,
    )

    mock_ir_refetch.assert_called_once()
    assert mock_ir_refetch.call_args.kwargs["ticker"] == "FGP.L"
    mock_extract_metrics.assert_called_once()
    metrics = meta["ir_presentation_metrics"]
    assert metrics["bridge_count"] == 2
    assert metrics["mandatory"] is True


def test_attach_filing_interim_financials_when_yahoo_quarterlies_empty(tmp_path: Path):
    """eng-20260918-15: ITV-like empty Yahoo quarterlies get filing_interim_financials attachment."""
    import json

    from value_investor.research.ingest import attach_filing_interim_financials

    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    body_path = bodies_dir / "h1.txt"
    body_path.write_text(
        "ITV plc Interim results for the six months ended 30 June 2026\n"
        "Adjusted EPS for the period was 2.2p (2025: 1.8p). "
        "with free cash flow of £40 million (30 June 2025: £43 million).",
        encoding="utf-8",
    )
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": "h1",
                        "headline": "ITV plc Interim Results to 30 June 2026",
                        "url": "https://example.com/half-year-report.pdf",
                        "period": "interim",
                        "has_body": True,
                        "body_path": str(body_path),
                        "published_at": "2026-07-31T00:00:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    financials = {
        "quarterly_income": {},
        "quarterly_cashflow": {},
    }
    merged = attach_filing_interim_financials(
        financials,
        filings_dir=filings_dir,
        ticker="ITV.L",
        sources_dir=tmp_path,
    )
    interim = merged.get("filing_interim_financials") or {}
    assert interim.get("interim_highlights", {}).get("free_cash_flow_millions") == 40.0
    assert (tmp_path / "filing_interim_financials.json").is_file()


def test_research_index_cohesion_matches_committed_verdict_count_in_repo():
    """CI: committed verdict memos must appear in latest.json research[] (eng-20261004-05)."""
    from pathlib import Path

    from value_investor.research.ingest import research_index_cohesion_metrics

    metrics = research_index_cohesion_metrics(data_dir=Path("docs/data"))
    assert metrics["index_missing_committed_verdicts"] == 0
    assert metrics["counts_match"] is True
    assert metrics["committed_with_verdict"] == metrics["indexed_verdict_count"]
    assert metrics["committed_with_verdict"] > 0


def test_reconcile_committed_research_index_merges_missing_tickers(tmp_path: Path):
    from value_investor.research.ingest import (
        reconcile_committed_research_index,
        research_index_cohesion_metrics,
    )
    from value_investor.storage import write_json

    data_dir = tmp_path / "data"
    committed = data_dir / "research" / "AO.L"
    committed.mkdir(parents=True)
    write_json(
        committed / "research.json",
        {
            "ticker": "AO.L",
            "name": "AO World plc",
            "research_verdict": "accumulate",
            "executive_summary": "Profit pivot with net funds.",
            "version": 1,
        },
        compact=True,
    )
    (committed / "research.md").write_text("# AO World memo\n", encoding="utf-8")
    latest_path = data_dir / "latest.json"
    write_json(latest_path, {"research": [], "reports": []}, compact=True)

    result = reconcile_committed_research_index(
        data_dir=data_dir,
        dest_dir=tmp_path / "docs",
        latest_path=latest_path,
        committed_root=committed.parent,
    )
    assert result["reconciled"] == ["AO.L"]
    after = research_index_cohesion_metrics(
        data_dir=data_dir,
        latest_path=latest_path,
        committed_root=committed.parent,
    )
    assert after["index_missing_committed_verdicts"] == 0
    assert (tmp_path / "docs" / "research" / "AO.L.md").is_file()


@patch("value_investor.research.ingest.fetch_google_news_rss", return_value=[])
@patch("value_investor.research.ingest.fetch_yfinance_news", return_value=[])
@patch(
    "value_investor.research.ingest.fetch_annual_financials", return_value={"income_statement": {}}
)
@patch(
    "value_investor.research.gap_fill_sources.deepen_thin_filings_if_needed",
    return_value={"skipped": True},
)
@patch("value_investor.research.filings.refetch_uk_primary_filing_bodies")
@patch("value_investor.research.filings.refresh_uk_filing_listings_into_index")
@patch("value_investor.research.filings.ingest_filings")
def test_uk_deepen_ingest_refreshes_listings_before_body_refetch(
    mock_ingest_filings,
    mock_refresh,
    mock_uk_refetch,
    _mock_deepen,
    _mock_financials,
    _mock_yf_news,
    _mock_google_news,
    tmp_path: Path,
):
    """AO.L-style UK memo ingest should merge fresh listings then refetch bodies."""
    mock_ingest_filings.return_value = {
        "filings_index_path": str(tmp_path / "filings" / "filings_index.json"),
        "filings_summary": {"total": 3, "with_body": 0, "annual": 2, "interim": 1},
        "filings_sources": ["companies_house"],
        "filings_regime": "uk_rns",
    }
    mock_refresh.return_value = {"added": 2, "added_interim": 1}
    mock_uk_refetch.return_value = {"fetched": 2, "with_body_after": 2}

    meta = ingest_research_sources(
        ticker="AO.L",
        company_name="AO World plc",
        screening_snapshot={"ticker": "AO.L", "signal": "buy"},
        sources_dir=tmp_path,
        market="ftse350",
        deepen_history=True,
    )

    assert mock_refresh.call_count >= 1
    assert mock_refresh.call_args.kwargs.get("max_ch_accounts") == 5
    mock_uk_refetch.assert_called_once()
    assert meta["filings_summary"]["total"] == 3
