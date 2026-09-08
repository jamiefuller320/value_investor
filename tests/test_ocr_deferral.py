"""Wide-pass OCR deferral and pin/drain resume."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.research.companies_house import MIME_PDF
from value_investor.research.filings import (
    _extract_filing_document_result,
    refetch_companies_house_filing_bodies,
)
from value_investor.research.ingest_improvement import run_ingest_improvement_pass
from value_investor.summary import CompanyReport


def _report(ticker: str = "ITV.L", name: str = "ITV plc") -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=name,
        sector="Communication Services",
        signal="strong_buy",
        models_passed=5,
        model_count=10,
        composite_score=0.7,
        sector_composite_score=0.8,
        families_passed=4,
        passed_families="cheapness,quality",
        data_quality_score=0.9,
        metrics_present=18,
        metrics_total=20,
        weeks_at_signal=1,
        signal_trend="new",
        conviction_score=0.5,
        stability_label="new",
        timing_signal="neutral",
        timing_score=0.0,
        rsi_14=50.0,
        price_vs_sma200_pct=0.0,
        action_note="",
        trade_plan=None,
        summary="test",
        passed_models=[],
        key_metrics={},
    )


def test_extract_defers_ocr_when_disallowed(monkeypatch):
    monkeypatch.setattr(
        "value_investor.research.filings._extract_pdf_text",
        lambda raw: None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._extract_pdf_text_fitz",
        lambda raw: None,
    )

    def _boom(_raw, *, max_pages=None):
        raise AssertionError("wide pass must not OCR")

    monkeypatch.setattr("value_investor.research.filings._ocr_pdf_text", _boom)
    extract = _extract_filing_document_result(b"%PDF-1.4", MIME_PDF, allow_ocr=False)
    assert extract.text is None
    assert extract.ocr_pending is True


def test_extract_still_ocrs_when_allowed(monkeypatch):
    monkeypatch.setattr(
        "value_investor.research.filings._extract_pdf_text",
        lambda raw: None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._extract_pdf_text_fitz",
        lambda raw: None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._ocr_pdf_text",
        lambda raw, *, max_pages=None: "A" * 220 + " going concern pension covenant",
    )
    extract = _extract_filing_document_result(b"%PDF-1.4", MIME_PDF, allow_ocr=True)
    assert extract.text is not None
    assert "going concern" in extract.text
    assert extract.ocr_pending is False


def _ch_index(filings_dir: Path, *, ocr_pending: bool = False) -> None:
    filings_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "id": "ch1",
        "source": "companies_house",
        "headline": "Companies House accounts",
        "url": "https://document-api.company-information.service.gov.uk/document/ch1",
        "document_metadata_url": (
            "https://document-api.company-information.service.gov.uk/document/ch1"
        ),
        "period": "annual",
        "has_body": False,
        "body_path": None,
    }
    if ocr_pending:
        row["ocr_pending"] = True
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"filings": [row], "summary": {"total": 1, "with_body": 0}}),
        encoding="utf-8",
    )


def test_refetch_ch_stops_at_deadline(tmp_path: Path, monkeypatch):
    filings_dir = tmp_path / "filings"
    _ch_index(filings_dir)

    def _boom(row, *, allow_ocr=True):
        raise AssertionError("deadline should skip CH fetch")

    monkeypatch.setattr("value_investor.research.filings._fetch_companies_house_body", _boom)
    result = refetch_companies_house_filing_bodies(
        filings_dir, max_bodies=3, deadline_monotonic=0.0, allow_ocr=False
    )
    assert result["deadline_hit"] is True
    assert result["attempted"] == 1
    assert result["fetched"] == 0


def test_refetch_ch_skips_ocr_pending_on_wide_pass(tmp_path: Path, monkeypatch):
    filings_dir = tmp_path / "filings"
    _ch_index(filings_dir, ocr_pending=True)

    def _boom(row, *, allow_ocr=True):
        raise AssertionError("ocr_pending row must wait for pin")

    monkeypatch.setattr("value_investor.research.filings._fetch_companies_house_body", _boom)
    result = refetch_companies_house_filing_bodies(
        filings_dir, max_bodies=3, allow_ocr=False
    )
    assert result["ocr_deferred"] == 1
    assert result["fetched"] == 0
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["ocr_pending"] is True
    assert saved["filings"][0]["has_body"] is False


def test_refetch_ch_resumes_ocr_when_allowed(tmp_path: Path, monkeypatch):
    filings_dir = tmp_path / "filings"
    _ch_index(filings_dir, ocr_pending=True)
    deep = "Defined benefit pension scheme borrowings covenant going concern cash flow " + (
        "x" * 220
    )

    def _fetch(row, *, allow_ocr=True):
        assert allow_ocr is True
        row.pop("ocr_pending", None)
        return deep

    monkeypatch.setattr("value_investor.research.filings._fetch_companies_house_body", _fetch)
    result = refetch_companies_house_filing_bodies(
        filings_dir, max_bodies=3, allow_ocr=True
    )
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    assert not saved["filings"][0].get("ocr_pending")


@patch("value_investor.research.ingest_improvement.deepen_thin_filings_if_needed")
@patch("value_investor.research.ingest_improvement.execute_planned_alternate_sources")
@patch("value_investor.research.ingest_improvement.ingest_research_sources")
@patch("value_investor.research.ingest_improvement.sanitize_filings_index")
@patch("value_investor.research.ingest_improvement.bootstrap_buy_tier_research")
@patch("value_investor.research.ingest_improvement.refetch_uk_primary_filing_bodies")
def test_wide_ingest_pass_disables_ocr(
    mock_primary,
    mock_bootstrap,
    mock_sanitize,
    mock_ingest,
    mock_alternate,
    mock_deepen,
    tmp_path: Path,
):
    output_dir = tmp_path / "output"
    sources = output_dir / "research" / "ITV.L" / "sources" / "filings"
    sources.mkdir(parents=True)
    (sources / "filings_index.json").write_text(
        json.dumps(
            {
                "summary": {"total": 2, "with_body": 1},
                "filings": [{"has_body": True}, {"has_body": False}],
            }
        ),
        encoding="utf-8",
    )
    mock_ingest.return_value = {"filings_summary": {"with_body": 1}}
    mock_alternate.return_value = {"fetched": 0}
    mock_deepen.return_value = {"skipped": True, "reason": "sufficient_bodies"}
    mock_primary.return_value = {
        "companies_house": {"fetched": 0, "ocr_deferred": 1},
        "rns": {"fetched": 0},
        "fetched": 0,
        "ocr_deferred": 1,
    }
    run_ingest_improvement_pass(
        reports=[_report()],
        output_dir=output_dir,
        market="ftse350",
        max_targets=1,
        max_runtime_seconds=3600,
        discovery_scan=False,
        suggestions_path=tmp_path / "missing.json",
    )
    assert mock_primary.call_args.kwargs["allow_ocr"] is False
    assert mock_primary.call_args.kwargs["deadline_monotonic"] is not None
    assert mock_ingest.call_args.kwargs["allow_ocr"] is False
    assert mock_alternate.call_args.kwargs["allow_ocr"] is False
    assert mock_deepen.call_args.kwargs["allow_ocr"] is False


@patch("value_investor.research.ingest_improvement.deepen_thin_filings_if_needed")
@patch("value_investor.research.ingest_improvement.execute_planned_alternate_sources")
@patch("value_investor.research.ingest_improvement.ingest_research_sources")
@patch("value_investor.research.ingest_improvement.sanitize_filings_index")
@patch("value_investor.research.ingest_improvement.bootstrap_buy_tier_research")
@patch("value_investor.research.ingest_improvement.refetch_uk_primary_filing_bodies")
def test_pin_ingest_pass_enables_ocr(
    mock_primary,
    mock_bootstrap,
    mock_sanitize,
    mock_ingest,
    mock_alternate,
    mock_deepen,
    tmp_path: Path,
):
    output_dir = tmp_path / "output"
    sources = output_dir / "research" / "ITV.L" / "sources" / "filings"
    sources.mkdir(parents=True)
    (sources / "filings_index.json").write_text(
        json.dumps(
            {
                "summary": {"total": 2, "with_body": 1},
                "filings": [{"has_body": True}, {"has_body": False}],
            }
        ),
        encoding="utf-8",
    )
    mock_ingest.return_value = {"filings_summary": {"with_body": 1}}
    mock_alternate.return_value = {"fetched": 0}
    mock_deepen.return_value = {"skipped": True, "reason": "sufficient_bodies"}
    mock_primary.return_value = {
        "companies_house": {"fetched": 1, "ocr_deferred": 0},
        "rns": {"fetched": 0},
        "fetched": 1,
    }
    run_ingest_improvement_pass(
        reports=[_report()],
        output_dir=output_dir,
        market="ftse350",
        max_targets=1,
        pin_tickers=["ITV.L"],
        discovery_scan=False,
        suggestions_path=tmp_path / "missing.json",
    )
    assert mock_primary.call_args.kwargs["allow_ocr"] is True
    assert mock_ingest.call_args.kwargs["allow_ocr"] is True
