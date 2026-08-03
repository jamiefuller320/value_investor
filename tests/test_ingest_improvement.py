"""Tests for ingest-only improvement executor."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.research.format import format_ingest_improvement_text
from value_investor.research.ingest_improvement import (
    IngestImprovementSummary,
    IngestImprovementTarget,
    _planned_sources_for_ticker,
    map_suggestion_to_source_ids,
    select_ingest_improvement_targets,
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


def test_map_suggestion_to_source_ids():
    assert "companies_house_accounts" in map_suggestion_to_source_ids(
        "Add Companies House filed-accounts PDF fetch"
    )
    assert "investegate_rns_full" in map_suggestion_to_source_ids(
        "Add Investegate/LSE RNS direct HTML fetch"
    )
    assert "company_ir_presentation" in map_suggestion_to_source_ids(
        "Fetch company IR results presentation PDF"
    )
    assert "sec_exhibits" in map_suggestion_to_source_ids(
        "dual-list SEDAR+ 20-F/AIF for annual accounts"
    )
    assert "company_ir_presentation" in map_suggestion_to_source_ids(
        "Fetch ITV investor-relations results presentation PDFs (segment revenue, Studios margin range, dividend policy, pro-forma cash flow) from allowlisted IR URLs post-results."
    )
    assert "company_ir_presentation" in map_suggestion_to_source_ids(
        "Extract consolidated cash-flow statement and related party transactions from annual report PDF"
    )


def test_planned_sources_includes_ir_presentation_for_itv_l():
    from value_investor.research.filings import fetch_filings_ir_allowlist

    inventory = {
        "thin": ["filings_bodies"],
        "filings_summary": {"with_body": 0, "total": 5},
    }
    planned = _planned_sources_for_ticker(
        ticker="ITV.L",
        market="ftse350",
        inventory=inventory,
        ingest_suggestions=[
            {
                "suggestion": (
                    "Fetch ITV investor-relations results presentation PDFs "
                    "(segment revenue, Studios margin range, dividend policy, pro-forma cash flow)"
                )
            }
        ],
        filings_with_body=0,
    )
    planned_ids = {row["id"] for row in planned}
    assert "company_ir_presentation" in planned_ids
    assert fetch_filings_ir_allowlist("ITV.L")


def test_select_ingest_improvement_targets_prioritises_missing_annual_bodies(tmp_path: Path):
    output_dir = tmp_path / "output"
    sources = output_dir / "research" / "MEGP.L" / "sources" / "filings"
    sources.mkdir(parents=True)
    (sources / "filings_index.json").write_text(
        json.dumps(
            {
                "summary": {
                    "total": 3,
                    "annual": 1,
                    "interim": 1,
                    "trading_update": 1,
                    "with_body": 1,
                },
                "filings": [
                    {"period": "annual", "has_body": False},
                    {"period": "interim", "has_body": True},
                    {"period": "trading_update", "has_body": False},
                ],
            }
        ),
        encoding="utf-8",
    )

    targets = select_ingest_improvement_targets(
        [_report("MEGP.L", "ME Group International plc")],
        output_dir=output_dir,
        suggestions_path=tmp_path / "missing.json",
        max_targets=3,
    )

    assert len(targets) == 1
    assert targets[0].ticker == "MEGP.L"
    assert targets[0].priority_score >= 4.0


def test_inspect_local_sources_includes_period_coverage(tmp_path: Path):
    from value_investor.research.gap_fill_sources import inspect_local_sources

    sources_dir = tmp_path / "sources"
    filings_dir = sources_dir / "filings"
    filings_dir.mkdir(parents=True)
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "summary": {
                    "total": 2,
                    "annual": 1,
                    "trading_update": 1,
                    "with_body": 0,
                },
                "filings": [
                    {"period": "annual", "has_body": False},
                    {"period": "trading_update", "has_body": False},
                ],
            }
        ),
        encoding="utf-8",
    )

    inventory = inspect_local_sources(sources_dir)
    assert inventory["period_coverage"]["annual"]["total"] == 1
    assert inventory["period_coverage"]["trading_update"]["total"] == 1
    assert inventory["filings_summary"]["period_coverage"]["annual"]["with_body"] == 0


def test_select_ingest_improvement_targets_prioritises_thin_filings(tmp_path: Path):
    output_dir = tmp_path / "output"
    suggestions_path = tmp_path / "suggestions.json"
    suggestions_path.write_text(
        json.dumps(
            {
                "suggestions": [
                    {
                        "ticker": "BT-A.L",
                        "area": "ingest",
                        "priority": "high",
                        "suggestion": "Fetch Investegate/LSE RNS direct HTML",
                    },
                    {
                        "ticker": "RIO.L",
                        "area": "scoring",
                        "priority": "medium",
                        "suggestion": "Ignore me",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    bt_sources = output_dir / "research" / "BT-A.L" / "sources" / "filings"
    bt_sources.mkdir(parents=True)
    (bt_sources / "filings_index.json").write_text(
        json.dumps(
            {
                "summary": {"total": 5, "annual": 5, "interim": 0, "with_body": 0},
                "filings": [{"has_body": False}] * 5,
            }
        ),
        encoding="utf-8",
    )

    targets = select_ingest_improvement_targets(
        [_report("BT-A.L", "BT Group")],
        output_dir=output_dir,
        suggestions_path=suggestions_path,
        max_targets=2,
    )

    assert len(targets) == 1
    assert targets[0].ticker == "BT-A.L"
    assert targets[0].indexed_without_body == 5
    assert targets[0].ingest_suggestion_count == 1


def test_select_ingest_improvement_targets_uses_library_research_path(tmp_path: Path, monkeypatch):
    output_dir = tmp_path / "output"
    library_index = (
        tmp_path
        / "docs/data/library/markets/aim/screen/research/BREE.L/sources/filings/filings_index.json"
    )
    library_index.parent.mkdir(parents=True)
    library_index.write_text(
        json.dumps(
            {
                "summary": {"total": 20, "annual": 0, "interim": 0, "with_body": 0},
                "filings": [{"has_body": False}] * 20,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    targets = select_ingest_improvement_targets(
        [_report("BREE.L", "Breedon Group")],
        output_dir=output_dir,
        suggestions_path=tmp_path / "missing.json",
        max_targets=3,
    )

    assert len(targets) == 1
    assert targets[0].ticker == "BREE.L"
    assert targets[0].filings_total == 20
    assert targets[0].indexed_without_body == 20


def test_planned_sources_prioritises_companies_house_for_uk_zero_bodies():
    inventory = {
        "thin": ["filings_bodies"],
        "filings_summary": {"with_body": 0, "total": 5},
    }
    planned = _planned_sources_for_ticker(
        ticker="BT-A.L",
        market="ftse350",
        inventory=inventory,
        ingest_suggestions=[],
        filings_with_body=0,
    )
    assert planned
    assert planned[0]["id"] == "companies_house_accounts"


def test_format_ingest_improvement_text():
    summary = IngestImprovementSummary(
        targets=[
            IngestImprovementTarget(
                ticker="BT-A.L",
                name="BT Group",
                signal="strong_buy",
                filings_total=5,
                filings_with_body=0,
                indexed_without_body=5,
                ingest_suggestion_count=1,
            )
        ],
        results=[
            {
                "ticker": "BT-A.L",
                "with_body_before": 0,
                "with_body_after": 2,
                "improved": True,
                "planned_sources": ["investegate_rns_full"],
            }
        ],
        improved=1,
    )
    text = format_ingest_improvement_text(summary)
    assert text is not None
    assert "BT-A.L" in text
    assert "0 → 2" in text


def test_ingest_improvement_installs_fetch_cashflow_fallback():
    from value_investor import fetch as fetch_mod

    assert getattr(fetch_mod.fetch_company_metrics, "_cashflow_fallback_installed", False)
