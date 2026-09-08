"""Tests for offline macro context (not wired into scoring)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.macro_context import (
    DOMAIN_SERIES,
    EQUITY_INDEX_MARKERS,
    backfill_equity_index_snapshots,
    domain_for_market,
    load_macro_snapshot,
    macro_context_for_market,
    macro_regime_note,
    save_macro_snapshot,
)
from value_investor.research.ingest import ingest_research_sources


def test_domain_for_market_mapping():
    assert domain_for_market("sp500") == "us"
    assert domain_for_market("nasdaq100") == "us"
    assert domain_for_market("ftse350") == "uk"
    assert domain_for_market("ftse_smallcap") == "uk"
    assert domain_for_market("euro_stoxx50") == "euro"
    assert domain_for_market("dax") == "euro"
    assert domain_for_market("asx200") == "au"
    assert domain_for_market("tsx60") == "ca"


def test_macro_context_is_secondary_only(tmp_path: Path):
    snapshot = {
        "fetched_at": "2026-07-17T00:00:00+00:00",
        "note": "Offline macro / regime context only.",
        "domains": {
            "au": {
                "domain": "au",
                "markers": {
                    "aud_usd": {"symbol": "AUDUSD=X", "value": 0.66, "as_of": "2026-07-16"},
                    "asx_200": {"symbol": "^AXJO", "value": 8000.0, "as_of": "2026-07-16"},
                },
            }
        },
    }
    save_macro_snapshot(snapshot, root=tmp_path)
    loaded = load_macro_snapshot(tmp_path)
    assert loaded is not None
    ctx = macro_context_for_market("asx200", root=tmp_path, refresh_if_missing=False)
    assert ctx["domain"] == "au"
    assert "scoring" in (ctx.get("note") or "").lower()
    note = macro_regime_note("asx200", root=tmp_path)
    assert "macro[au]" in note
    assert "aud_usd=0.66" in note


def test_us_domain_includes_sp500_index():
    assert DOMAIN_SERIES["us"]["sp500"] == "^GSPC"
    assert EQUITY_INDEX_MARKERS["us"] == ("sp500", "^GSPC")


def test_backfill_writes_sp500_into_dated_snapshots(tmp_path: Path):
    from value_investor.storage import read_json, write_json

    write_json(
        tmp_path / "2026-09-04.json",
        {
            "fetched_at": "2026-09-04T12:00:00+00:00",
            "domains": {
                "us": {
                    "domain": "us",
                    "markers": {
                        "usd_index": {"symbol": "DX-Y.NYB", "value": 99.1, "as_of": "2026-09-04"},
                    },
                }
            },
        },
        compact=False,
        compress=False,
    )
    write_json(
        tmp_path / "latest.json",
        {
            "fetched_at": "2026-09-07T12:00:00+00:00",
            "domains": {
                "us": {
                    "domain": "us",
                    "markers": {
                        "usd_index": {"symbol": "DX-Y.NYB", "value": 99.2, "as_of": "2026-09-07"},
                    },
                }
            },
        },
        compact=False,
        compress=False,
    )
    result = backfill_equity_index_snapshots(
        tmp_path,
        closes_by_symbol={"^GSPC": {"2026-09-03": 6500.0, "2026-09-05": 6520.5}},
        fetch_missing=False,
    )
    assert result["patched"] == 2
    dated = read_json(tmp_path / "2026-09-04.json")
    marker = dated["domains"]["us"]["markers"]["sp500"]
    assert marker["symbol"] == "^GSPC"
    assert marker["value"] == 6500.0
    assert marker["as_of"] == "2026-09-03"
    latest = read_json(tmp_path / "latest.json")
    assert latest["domains"]["us"]["markers"]["sp500"]["value"] == 6520.5
    assert latest["domains"]["us"]["markers"]["usd_index"]["value"] == 99.2


def test_ingest_writes_macro_context_when_market_set(tmp_path: Path):
    sources = tmp_path / "sources"
    fake_macro = {
        "market": "asx200",
        "domain": "au",
        "fetched_at": "2026-07-17T00:00:00+00:00",
        "note": "Secondary regime context only — do not treat as a scoring input.",
        "markers": {},
    }
    with (
        patch(
            "value_investor.research.ingest.fetch_annual_financials",
            return_value={
                "ticker": "BHP.AX",
                "income_statement": {},
                "balance_sheet": {},
                "cash_flow": {},
                "quarterly_income": {},
            },
        ),
        patch("value_investor.research.ingest.fetch_yfinance_news", return_value=[]),
        patch("value_investor.research.ingest.fetch_google_news_rss", return_value=[]),
        patch(
            "value_investor.research.filings.ingest_filings",
            return_value={
                "filings_index_path": str(sources / "filings" / "filings_index.json"),
                "filings_summary": {
                    "total": 0,
                    "annual": 0,
                    "interim": 0,
                    "other": 0,
                    "with_body": 0,
                },
                "filings_sources": [],
                "filings_regime": "asx_announcements",
            },
        ),
        patch(
            "value_investor.macro_context.macro_context_for_market",
            return_value=fake_macro,
        ),
    ):
        meta = ingest_research_sources(
            ticker="BHP.AX",
            company_name="BHP",
            screening_snapshot={"ticker": "BHP.AX"},
            sources_dir=sources,
            market="asx200",
            include_filings=True,
        )
    assert (sources / "macro_context.json").exists()
    assert meta["macro_context"]["domain"] == "au"
    assert meta["market"] == "asx200"
