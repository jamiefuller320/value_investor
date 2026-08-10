"""Tests for canonical buy-tier ingest bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.research.filings import sanitize_filings_index
from value_investor.research.ingest_bootstrap import (
    bootstrap_buy_tier_research,
    canonical_filings_dir,
    ensure_canonical_research_store,
)
from value_investor.summary import CompanyReport


def _report(ticker: str, name: str, signal: str = "strong_buy") -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=name,
        sector="Industrials",
        signal=signal,
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


def test_ensure_canonical_migrates_library_index(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    library_index = (
        tmp_path
        / "docs/data/library/markets/aim/screen/research/BREE.L/sources/filings/filings_index.json"
    )
    library_index.parent.mkdir(parents=True)
    library_index.write_text(
        json.dumps(
            {
                "summary": {"total": 2, "annual": 0, "interim": 0, "with_body": 0},
                "filings": [
                    {"headline": "Beazley plc results", "has_body": False, "source": "google_news"},
                    {
                        "headline": "Breedon Group plc FY results",
                        "has_body": False,
                        "source": "ticker_rns_api",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    data_dir = tmp_path / "docs/data"
    row = ensure_canonical_research_store(
        "BREE.L",
        "Breedon Group plc",
        output_dir=data_dir,
        seed_if_missing=False,
    )
    assert row["action"] == "migrated"
    canonical = canonical_filings_dir(data_dir, "BREE.L") / "filings_index.json"
    assert canonical.exists()


def test_sanitize_filings_index_prunes_misattributed_rows(tmp_path: Path):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "headline": "Beazley plc FY results",
                        "has_body": False,
                        "source": "google_news",
                    },
                    {
                        "headline": "Breedon Group plc Full Year Results",
                        "has_body": False,
                        "source": "ticker_rns_api",
                        "period": "other",
                    },
                ],
                "summary": {"total": 2, "with_body": 0, "annual": 0, "interim": 0},
            }
        ),
        encoding="utf-8",
    )
    result = sanitize_filings_index(
        filings_dir,
        company_name="Breedon Group plc",
        ticker="BREE.L",
    )
    assert result["pruned"] == 1
    payload = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert len(payload["filings"]) == 1
    assert payload["filings"][0]["period"] == "annual"


def test_bootstrap_buy_tier_research_migrates_strong_buy(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    library_index = (
        tmp_path
        / "docs/data/library/markets/aim/screen/research/BREE.L/sources/filings/filings_index.json"
    )
    library_index.parent.mkdir(parents=True)
    library_index.write_text(
        json.dumps({"summary": {"total": 1, "with_body": 0}, "filings": [{"has_body": False}]}),
        encoding="utf-8",
    )
    data_dir = tmp_path / "docs/data"
    summary = bootstrap_buy_tier_research(
        [_report("BREE.L", "Breedon Group plc")],
        output_dir=data_dir,
        seed_cap=0,
    )
    assert summary["migrated"] == 1
    assert (canonical_filings_dir(data_dir, "BREE.L") / "filings_index.json").exists()


@patch("value_investor.research.ingest.ingest_research_sources")
def test_bootstrap_buy_tier_research_seeds_buy_tier_up_to_cap(
    mock_ingest: object,
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "docs/data"
    reports = [
        _report("AAA.L", "Alpha plc", signal="strong_buy"),
        _report("BBB.L", "Beta plc", signal="buy"),
        _report("CCC.L", "Gamma plc", signal="buy"),
    ]

    def _fake_ingest(**kwargs):
        sources_dir = kwargs["sources_dir"]
        filings_dir = sources_dir / "filings"
        filings_dir.mkdir(parents=True, exist_ok=True)
        (filings_dir / "filings_index.json").write_text(
            json.dumps({"summary": {"total": 0, "with_body": 0}, "filings": []}),
            encoding="utf-8",
        )
        return {"filings_summary": {"total": 0, "with_body": 0}}

    mock_ingest.side_effect = _fake_ingest

    summary = bootstrap_buy_tier_research(reports, output_dir=data_dir, seed_cap=2)

    assert summary["seeded"] == 2
    assert summary["pending"] == 1
    assert mock_ingest.call_count == 2
    assert (canonical_filings_dir(data_dir, "AAA.L") / "filings_index.json").exists()
    assert (canonical_filings_dir(data_dir, "BBB.L") / "filings_index.json").exists()
    assert not (canonical_filings_dir(data_dir, "CCC.L") / "filings_index.json").exists()
