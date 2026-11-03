"""Tests for L546 SEC filing_aligned observe twin."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.scoring.fcf import reconcile_fcf
from value_investor.sec_filing_aligned_twin import (
    EPOCH_ID,
    TWIN_FINDING_TITLE,
    build_sec_filing_aligned_twin,
    ops_findings_from_sec_filing_aligned_twin,
    twin_row,
)


def _write_us_memo(
    library_root: Path,
    *,
    market_id: str,
    ticker: str,
    signal: str,
    yahoo_ocf: float,
    yahoo_capex: float,
    sec_ocf: float,
    sec_capex: float,
    year: str = "2025",
) -> Path:
    ticker_dir = library_root / "markets" / market_id / "screen" / "research" / ticker
    sources = ticker_dir / "sources"
    sources.mkdir(parents=True)
    (ticker_dir / "research.json").write_text(
        json.dumps({"ticker": ticker, "signal": signal}),
        encoding="utf-8",
    )
    (sources / "financials_annual.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "cash_flow": {
                    year: {
                        "Operating Cash Flow": yahoo_ocf,
                        "Capital Expenditure": yahoo_capex,
                        "Free Cash Flow": yahoo_ocf + yahoo_capex,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (sources / "sec_companyfacts.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "fetched_at": "2026-11-01T00:00:00+00:00",
                "latest": {
                    "period_end": f"{year}-12-31",
                    "fiscal_year_label": year,
                    "currency": "USD",
                    "operating_cashflow": {"value": sec_ocf, "filed": "2026-02-01"},
                    "capital_expenditure": {"value": sec_capex, "filed": "2026-02-01"},
                    "free_cashflow": sec_ocf - sec_capex,
                },
                "annual": [],
            }
        ),
        encoding="utf-8",
    )
    return ticker_dir


def test_reconcile_fcf_accepts_sec_filing_aligned_override():
    financials = {
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 100.0,
                "Capital Expenditure": -40.0,
                "Free Cash Flow": 60.0,
            }
        }
    }
    yahoo = reconcile_fcf(screen_ttm=60.0, financials=financials, filing_currency="USD")
    assert yahoo["filing_aligned"] == 60.0
    assert yahoo["filing_aligned_source"] == "yahoo_annual"

    sec = reconcile_fcf(
        screen_ttm=60.0,
        financials=financials,
        filing_currency="USD",
        filing_aligned_override=200.0,
        filing_aligned_source="sec_companyfacts",
        fiscal_year_override="2025",
    )
    assert sec["filing_aligned"] == 200.0
    assert sec["filing_aligned_source"] == "sec_companyfacts"
    assert sec["fiscal_year"] == "2025"
    # Live default path unchanged when override omitted.
    again = reconcile_fcf(screen_ttm=60.0, financials=financials, filing_currency="USD")
    assert again["filing_aligned"] == 60.0
    assert again["filing_aligned_source"] == "yahoo_annual"


def test_twin_row_flags_policy_change_when_sec_diverges(tmp_path: Path):
    ticker_dir = _write_us_memo(
        tmp_path,
        market_id="sp500",
        ticker="EXM",
        signal="strong_buy",
        yahoo_ocf=100_000_000.0,
        yahoo_capex=-40_000_000.0,  # Yahoo filing_aligned = 60M
        sec_ocf=100_000_000.0,
        sec_capex=10_000_000.0,  # SEC FCF = 90M — can change majority vs screen
    )
    # Make screen disagree with Yahoo filing so SEC override can flip policy.
    # Yahoo Free Cash Flow stand-in is 60M; with company_adjusted absent,
    # Yahoo path falls back to filing_aligned=60M. SEC override=90M still
    # filing_aligned path — set screen far away so both stay filing-aligned
    # but filing_aligned value itself changes (policy_fcf changes).
    row = twin_row(ticker_dir)
    assert row is not None
    assert row["influences_live"] is False
    assert row["buy_tier"] is True
    assert row["yahoo"]["filing_aligned_source"] == "yahoo_annual"
    assert row["sec_twin"]["filing_aligned_source"] == "sec_companyfacts"
    assert row["sec_twin"]["filing_aligned"] == 90_000_000.0
    assert row["yahoo"]["filing_aligned"] == 60_000_000.0
    assert row["policy_changed"] is True


def test_build_twin_store_and_ops_finding(tmp_path: Path):
    _write_us_memo(
        tmp_path,
        market_id="sp500",
        ticker="AAA",
        signal="buy",
        yahoo_ocf=50_000_000.0,
        yahoo_capex=-10_000_000.0,
        sec_ocf=50_000_000.0,
        sec_capex=5_000_000.0,
    )
    _write_us_memo(
        tmp_path,
        market_id="nasdaq100",
        ticker="BBB",
        signal="strong_buy",
        yahoo_ocf=80_000_000.0,
        yahoo_capex=-20_000_000.0,
        sec_ocf=80_000_000.0,
        sec_capex=5_000_000.0,
    )
    _write_us_memo(
        tmp_path,
        market_id="sp500",
        ticker="CCC",
        signal="buy",
        yahoo_ocf=40_000_000.0,
        yahoo_capex=-5_000_000.0,
        sec_ocf=40_000_000.0,
        sec_capex=2_000_000.0,
    )
    # Agreeing name should not count as policy change when values match.
    _write_us_memo(
        tmp_path,
        market_id="sp500",
        ticker="DDD",
        signal="hold",
        yahoo_ocf=30_000_000.0,
        yahoo_capex=-10_000_000.0,
        sec_ocf=30_000_000.0,
        sec_capex=10_000_000.0,  # SEC FCF = Yahoo OCF+CapEx = 20M
    )

    payload = build_sec_filing_aligned_twin(tmp_path)
    assert payload["influences_live"] is False
    assert payload["observe_only"] is True
    assert payload["epoch_id"] == EPOCH_ID
    assert payload["summary"]["compared"] >= 3
    assert payload["summary"]["policy_changed_buy_tier"] >= 3

    findings = ops_findings_from_sec_filing_aligned_twin(payload)
    assert len(findings) == 1
    assert findings[0]["title"] == TWIN_FINDING_TITLE
    assert findings[0]["severity"] == "warn"
    assert findings[0]["auto_fixable"] is False
    assert "influences_live=false" in findings[0]["summary"]
