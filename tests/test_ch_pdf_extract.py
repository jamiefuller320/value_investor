"""Tests for Companies House PDF/iXBRL extraction and OCR fallback."""

from __future__ import annotations

from unittest.mock import patch

from value_investor.research.companies_house import (
    MIME_PDF,
    MIME_XHTML,
    _document_mime_candidates,
    fetch_document_bytes,
    iter_ch_document_downloads,
)
from value_investor.research.filings import (
    _extract_filing_document_text,
    _fetch_companies_house_body,
    _ocr_pdf_text,
)


def test_document_mime_candidates_prefers_pdf_then_xhtml():
    resources = {
        MIME_PDF: {"content_length": 1000},
        MIME_XHTML: {"content_length": 500},
    }
    assert _document_mime_candidates(resources) == [MIME_PDF, MIME_XHTML]
    assert _document_mime_candidates(resources, prefer=MIME_XHTML) == [
        MIME_XHTML,
        MIME_PDF,
    ]


def test_fetch_document_bytes_uses_prefer_mime(monkeypatch):
    meta = {
        "links": {"document": "/document/abc/content"},
        "resources": {
            MIME_PDF: {"content_length": 100},
            MIME_XHTML: {"content_length": 200},
        },
    }
    calls: list[str] = []

    def fake_get(url, *, api_key, accept="application/json", timeout=60.0, retries=2):
        if url.endswith("/document/abc"):
            import json

            return json.dumps(meta).encode("utf-8")
        calls.append(accept)
        return b"<html>ixbrl accounts</html>"

    monkeypatch.setattr("value_investor.research.companies_house._ch_get", fake_get)
    monkeypatch.setattr("value_investor.research.companies_house.time.sleep", lambda *_a, **_k: None)
    fetched = fetch_document_bytes(
        "https://document-api.company-information.service.gov.uk/document/abc",
        api_key="test-key",
        prefer=MIME_XHTML,
        metadata=meta,
    )
    assert fetched == (b"<html>ixbrl accounts</html>", MIME_XHTML)
    assert MIME_XHTML in calls


def test_extract_filing_document_text_falls_back_to_ocr(monkeypatch):
    monkeypatch.setattr(
        "value_investor.research.filings._extract_pdf_text",
        lambda raw: None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._ocr_pdf_text",
        lambda raw: "A" * 220 + " going concern pension covenant",
    )
    text = _extract_filing_document_text(b"%PDF-1.4", MIME_PDF)
    assert text is not None
    assert "going concern" in text


def test_fetch_companies_house_body_uses_ixbrl_when_pdf_empty(monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")
    row = {
        "id": "ch_test",
        "document_metadata_url": "https://document-api.example/doc/1",
        "url": "https://document-api.example/doc/1",
    }
    downloads = [
        (b"%PDF-empty", MIME_PDF),
        (b"<html><body>Statutory accounts going concern note</body></html>", MIME_XHTML),
    ]

    monkeypatch.setattr(
        "value_investor.research.companies_house.iter_ch_document_downloads",
        lambda *args, **kwargs: downloads,
    )
    with patch(
        "value_investor.research.filings._extract_filing_document_text",
        side_effect=[None, "A" * 220 + " going concern"],
    ):
        body = _fetch_companies_house_body(row)
    assert body is not None
    assert "going concern" in body


def test_ocr_pdf_text_disabled_by_env(monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_OCR", "0")
    assert _ocr_pdf_text(b"%PDF-1.4") is None


def test_iter_ch_document_downloads_skips_duplicate_payloads(monkeypatch):
    meta = {
        "links": {"document": "/document/abc/content"},
        "resources": {MIME_PDF: {"content_length": 100}},
    }
    monkeypatch.setattr(
        "value_investor.research.companies_house.fetch_document_metadata",
        lambda *args, **kwargs: meta,
    )
    monkeypatch.setattr(
        "value_investor.research.companies_house.fetch_document_bytes",
        lambda *args, **kwargs: (b"same-payload", MIME_PDF),
    )
    downloads = iter_ch_document_downloads("https://document-api.example/doc/1", api_key="k")
    assert len(downloads) == 1
