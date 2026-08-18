"""Tests for screening pipeline snapshot export behaviour."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import value_investor.pipeline  # noqa: F401 — installs research snapshot hooks
from value_investor.models.classic import FCFYieldModel
from value_investor.research.document import ResearchDocument
from value_investor.research.overlay import apply_research_overlay
from value_investor.research.store import ResearchStore
from value_investor.scoring import evaluate_universe
from value_investor.scoring.cash_conversion_overlay import (
    enrich_signals_with_cash_conversion_overlay,
)
from value_investor.scoring.dividend_yield_overlay import enrich_signals_with_dividend_yield_overlay
from value_investor.scoring.earnings_basis_overlay import enrich_signals_with_earnings_basis_overlay
from value_investor.scoring.fcf import (
    enrich_universe_with_canonical_fcf,
    enrich_universe_with_filing_metrics,
    extract_cashflow_metrics_from_annual_financials,
    fcf_filing_screen_mismatch,
    fcf_within_company_tolerance,
    fcf_yield_pass_suppressed,
    parse_adjusted_eps_growth_pct,
    parse_interim_eps_decline_pct,
    suppress_fcf_yield_passes,
)
from value_investor.scoring.fcf_basis_overlay import enrich_signals_with_fcf_basis_overlay
from value_investor.scoring.healthcare_overlay import enrich_signals_with_healthcare_overlay
from value_investor.scoring.interim_quality_overlay import (
    enrich_signals_with_interim_quality_overlay,
)
from value_investor.scoring.sector_overrides import (
    AGRICULTURE_COMMODITIES_SECTOR,
    apply_sector_overrides,
    resolve_scoring_sector,
)
from value_investor.scoring.snapshot import (
    refresh_snapshot_from_document,
    sync_research_verdict_snapshots,
)
from value_investor.sector_scoring import add_sector_scores
from value_investor.storage import write_json
from value_investor.summary import CompanyReport, build_company_reports


def _minimal_report(**overrides) -> CompanyReport:
    base = dict(
        ticker="FGP.L",
        name="FirstGroup plc",
        sector="Industrials",
        signal="strong_buy",
        models_passed=11,
        model_count=22,
        composite_score=0.9,
        sector_composite_score=0.85,
        families_passed=5,
        passed_families="cheapness,quality,dividend,garp,risk",
        data_quality_score=1.0,
        metrics_present=20,
        metrics_total=20,
        weeks_at_signal=1,
        signal_trend="new",
        conviction_score=0.5,
        stability_label="new",
        timing_signal="neutral",
        timing_score=0.5,
        rsi_14=50.0,
        price_vs_sma200_pct=0.0,
        action_note="",
        trade_plan=None,
        summary="test",
        passed_models=["FCF Yield"],
        key_metrics={"P/E": "9.1"},
        failed_models=["Financial Health"],
        model_failures={"Financial Health": ["weak liquidity"]},
        screening_inputs={
            "debt_to_equity": 140.0,
            "current_ratio": 0.73,
            "earnings_growth_pct": -0.072,
            "ncav_available": False,
            "dividend_yield_raw": 0.04,
        },
    )
    base.update(overrides)
    return CompanyReport(**base)


def test_screening_snapshot_written_with_failed_models_and_piotroski(tmp_path: Path):
    signals = pd.DataFrame(
        [
            {
                "ticker": "GFTU.L",
                "name": "Grafton Group plc",
                "sector": "Industrials",
                "signal": "strong_buy",
                "models_passed": 11,
                "model_count": 22,
                "composite_score": 0.84,
                "sector_composite_score": 0.8,
                "families_passed": 5,
                "passed_families": "cheapness,quality,dividend,garp,risk",
                "data_quality_score": 1.0,
                "metrics_present": 20,
                "metrics_total": 20,
                "weeks_at_signal": 1,
                "signal_trend": "new",
                "conviction_score": 0.51,
                "stability_label": "new",
                "timing_signal": "neutral",
                "timing_score": 0.5,
                "rsi_14": 63.0,
                "price_vs_sma200_pct": 0.0,
                "timing_reasons": "[]",
                "action_note": "",
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "GFTU.L",
                "model_id": "buffett_quality",
                "model_name": "Buffett Quality",
                "passed": False,
                "score": 0.2,
                "reasons": "[]",
                "failed_criteria": "['ROE below threshold']",
            },
            {
                "ticker": "GFTU.L",
                "model_id": "piotroski_f",
                "model_name": "Piotroski F-Score",
                "passed": True,
                "score": 8 / 9,
                "reasons": "['F-Score=8/9', 'positive net income', 'positive operating cash flow']",
                "failed_criteria": "['asset turnover improving']",
            },
        ]
    )

    snapshot = build_company_reports(signals, model_results)[0].to_dict()
    snapshot_path = tmp_path / "screening_snapshot.json"
    write_json(snapshot_path, snapshot, compact=True, compress=False)

    written = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert "Buffett Quality" in written["failed_models"]
    assert written["model_failures"]["Buffett Quality"] == ["ROE below threshold"]
    assert written["piotroski_f_score"]["score"] == 8
    assert written["piotroski_f_score"]["passed"] is True
    assert written["signal"] == "strong_buy"


def test_refresh_snapshot_from_document_merges_research_verdict(tmp_path: Path):
    sources_dir = tmp_path / "research" / "FGP.L" / "sources"
    sources_dir.mkdir(parents=True)
    write_json(
        sources_dir / "screening_snapshot.json",
        {"ticker": "FGP.L", "signal": "strong_buy", "research_verdict": None},
        compact=True,
    )
    doc = ResearchDocument(
        ticker="FGP.L",
        name="FirstGroup plc",
        signal="strong_buy",
        version=2,
        created_at="2026-07-26T00:00:00+00:00",
        updated_at="2026-07-26T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="caution",
        research_risk_level="medium",
        research_confidence=0.62,
        research_rationale="Leverage flags confirmed.",
        research_path=str(tmp_path / "research" / "FGP.L" / "research.md"),
    )

    assert refresh_snapshot_from_document(tmp_path, doc) is True
    written = json.loads((sources_dir / "screening_snapshot.json").read_text(encoding="utf-8"))
    assert written["research_verdict"] == "caution"
    assert written["research_risk_level"] == "medium"
    assert written["research_confidence"] == 0.62
    assert written["adjusted_signal"] == "buy"


def test_sync_research_verdict_snapshots_writes_full_report(tmp_path: Path):
    report = _minimal_report()
    doc = ResearchDocument(
        ticker="FGP.L",
        name="FirstGroup plc",
        signal="strong_buy",
        version=2,
        created_at="2026-07-26T00:00:00+00:00",
        updated_at="2026-07-26T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="accumulate",
        research_risk_level="low",
        research_confidence=0.7,
        research_path=str(tmp_path / "research" / "FGP.L" / "research.md"),
    )

    updated = sync_research_verdict_snapshots(tmp_path, [report], [doc])
    assert updated == 1

    snapshot_path = tmp_path / "research" / "FGP.L" / "sources" / "screening_snapshot.json"
    written = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert written["screening_inputs"]["debt_to_equity"] == 140.0
    assert written["model_failures"]["Financial Health"] == ["weak liquidity"]
    assert written["research_verdict"] == "accumulate"
    assert written["adjusted_signal"] == "strong_buy"


def test_apply_research_overlay_syncs_screening_snapshot(tmp_path: Path):
    report = _minimal_report()
    doc = ResearchDocument(
        ticker="FGP.L",
        name="FirstGroup plc",
        signal="strong_buy",
        version=2,
        created_at="2026-07-26T00:00:00+00:00",
        updated_at="2026-07-26T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="caution",
        research_risk_level="medium",
        research_confidence=0.62,
        research_path=str(tmp_path / "research" / "FGP.L" / "research.md"),
    )

    updated = apply_research_overlay([report], [doc])
    assert updated[0].research_verdict == "caution"

    snapshot_path = tmp_path / "research" / "FGP.L" / "sources" / "screening_snapshot.json"
    written = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert written["research_verdict"] == "caution"
    assert written["screening_inputs"]["current_ratio"] == 0.73


def test_research_store_save_refreshes_screening_snapshot(tmp_path: Path):
    sources_dir = tmp_path / "research" / "FGP.L" / "sources"
    sources_dir.mkdir(parents=True)
    write_json(
        sources_dir / "screening_snapshot.json",
        {"ticker": "FGP.L", "signal": "strong_buy"},
        compact=True,
    )
    store = ResearchStore(tmp_path)
    doc = ResearchDocument(
        ticker="FGP.L",
        name="FirstGroup plc",
        signal="strong_buy",
        version=1,
        created_at="2026-07-26T00:00:00+00:00",
        updated_at="2026-07-26T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="pass",
        research_confidence=0.5,
    )
    store.save(doc)

    written = json.loads((sources_dir / "screening_snapshot.json").read_text(encoding="utf-8"))
    assert written["research_verdict"] == "pass"
    assert written["adjusted_signal"] == "hold"


def _consumer_defensive_universe_with_plantation() -> pd.DataFrame:
    """Plantation misclassified as Consumer Defensive: cheap vs FMCG, not vs full universe."""
    return pd.DataFrame(
        [
            {
                "ticker": "AEP.L",
                "name": "AEP Plantations Plc",
                "sector": "Consumer Defensive",
                "trailing_pe": 10.0,
                "price_to_book": 1.5,
                "dividend_yield": 0.056,
                "free_cashflow": 80,
                "market_cap": 1000,
                "enterprise_value": 950,
                "ebitda": 120,
                "return_on_equity": 0.15,
            },
            {
                "ticker": "ULVR.L",
                "name": "Unilever PLC",
                "sector": "Consumer Defensive",
                "trailing_pe": 22.0,
                "price_to_book": 5.0,
                "dividend_yield": 0.03,
                "free_cashflow": 40,
                "market_cap": 1000,
                "enterprise_value": 1100,
                "ebitda": 80,
                "return_on_equity": 0.12,
            },
            {
                "ticker": "DGE.L",
                "name": "Diageo plc",
                "sector": "Consumer Defensive",
                "trailing_pe": 25.0,
                "price_to_book": 6.0,
                "dividend_yield": 0.025,
                "free_cashflow": 30,
                "market_cap": 1000,
                "enterprise_value": 1150,
                "ebitda": 70,
                "return_on_equity": 0.10,
            },
            {
                "ticker": "ABF.L",
                "name": "Associated British Foods",
                "sector": "Consumer Defensive",
                "trailing_pe": 28.0,
                "price_to_book": 4.5,
                "dividend_yield": 0.02,
                "free_cashflow": 25,
                "market_cap": 1000,
                "enterprise_value": 1200,
                "ebitda": 65,
                "return_on_equity": 0.09,
            },
            {
                "ticker": "SHEL.L",
                "name": "Shell plc",
                "sector": "Energy",
                "trailing_pe": 6.0,
                "price_to_book": 1.0,
                "dividend_yield": 0.07,
                "free_cashflow": 120,
                "market_cap": 1000,
                "enterprise_value": 900,
                "ebitda": 180,
                "return_on_equity": 0.18,
            },
        ]
    )


def test_resolve_scoring_sector_remaps_aep_and_plantation_names():
    assert resolve_scoring_sector("AEP.L", "Consumer Defensive", "AEP Plantations Plc") == (
        AGRICULTURE_COMMODITIES_SECTOR
    )
    assert resolve_scoring_sector("XYZ.L", "Consumer Defensive", "Palm Oil Holdings Ltd") == (
        AGRICULTURE_COMMODITIES_SECTOR
    )
    assert (
        resolve_scoring_sector("XYZ.L", "Consumer Defensive", "Unilever PLC")
        == "Consumer Defensive"
    )
    assert resolve_scoring_sector("XYZ.L", "Energy", "Palm Oil Holdings Ltd") == "Energy"


def test_apply_sector_overrides_changes_sector_composite_score():
    universe = _consumer_defensive_universe_with_plantation()
    before = add_sector_scores(universe)
    aep_before = float(before.loc[before["ticker"] == "AEP.L", "sector_composite_score"].iloc[0])

    overridden = apply_sector_overrides(universe)
    assert (
        overridden.loc[overridden["ticker"] == "AEP.L", "sector"].iloc[0]
        == AGRICULTURE_COMMODITIES_SECTOR
    )

    after = add_sector_scores(overridden)
    aep_after = float(after.loc[after["ticker"] == "AEP.L", "sector_composite_score"].iloc[0])

    assert aep_before > 0.7
    assert aep_after < aep_before


def test_enrich_signals_with_healthcare_overlay_caps_adjusted_signal():
    signals = pd.DataFrame(
        [
            {
                "ticker": "PHAR.L",
                "name": "Pharma Weak Ltd",
                "sector": "Healthcare",
                "signal": "strong_buy",
                "free_cashflow": -80.0,
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "PHAR.L",
                "model_id": "piotroski_f",
                "model_name": "Piotroski F-Score",
                "passed": False,
                "score": 4 / 9,
                "reasons": "['F-Score=4/9']",
                "failed_criteria": "['F-Score 4/9 below 7']",
            },
        ]
    )

    enriched = enrich_signals_with_healthcare_overlay(signals, model_results)

    assert enriched.iloc[0]["signal"] == "strong_buy"
    assert bool(enriched.iloc[0]["healthcare_overlay"]) is True
    assert enriched.iloc[0]["adjusted_signal"] == "buy"


def test_enrich_signals_with_healthcare_overlay_after_research():
    signals = pd.DataFrame(
        [
            {
                "ticker": "PHAR.L",
                "name": "Pharma Weak Ltd",
                "sector": "Healthcare",
                "signal": "strong_buy",
                "free_cashflow": -80.0,
                "adjusted_signal": "strong_buy",
                "research_verdict": "accumulate",
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "PHAR.L",
                "model_id": "piotroski_f",
                "model_name": "Piotroski F-Score",
                "passed": False,
                "score": 2 / 9,
                "reasons": "['F-Score=2/9']",
                "failed_criteria": "['F-Score 2/9 below 7']",
            },
        ]
    )

    enriched = enrich_signals_with_healthcare_overlay(signals, model_results)

    assert bool(enriched.iloc[0]["healthcare_overlay"]) is True
    assert enriched.iloc[0]["adjusted_signal"] == "buy"


def test_enrich_signals_with_cash_conversion_overlay_caps_adjusted_signal():
    signals = pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "name": "Hikma Pharmaceuticals PLC",
                "sector": "Health Care",
                "signal": "strong_buy",
                "free_cashflow": -66.1,
                "shares_outstanding": 240_000_000,
                "shares_outstanding_prev": 245_000_000,
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "model_id": "dividend_growth",
                "model_name": "Dividend Growth",
                "passed": True,
                "score": 0.8,
                "reasons": "['dividend payer: yield=3.9%']",
                "failed_criteria": "[]",
            },
        ]
    )

    enriched = enrich_signals_with_cash_conversion_overlay(signals, model_results)

    assert enriched.iloc[0]["signal"] == "strong_buy"
    assert bool(enriched.iloc[0]["cash_conversion_overlay"]) is True
    assert enriched.iloc[0]["adjusted_signal"] == "buy"


def test_enrich_signals_with_cash_conversion_overlay_after_healthcare():
    signals = pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "name": "Hikma Pharmaceuticals PLC",
                "sector": "Health Care",
                "signal": "strong_buy",
                "free_cashflow": -66.1,
                "shares_outstanding": 240_000_000,
                "shares_outstanding_prev": 245_000_000,
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "model_id": "dividend_growth",
                "model_name": "Dividend Growth",
                "passed": True,
                "score": 0.8,
                "reasons": "['dividend payer: yield=3.9%']",
                "failed_criteria": "[]",
            },
            {
                "ticker": "HIK.L",
                "model_id": "piotroski_f",
                "model_name": "Piotroski F-Score",
                "passed": False,
                "score": 6 / 9,
                "reasons": "['F-Score=6/9']",
                "failed_criteria": "['F-Score 6/9 below 7']",
            },
        ]
    )

    enriched = enrich_signals_with_healthcare_overlay(signals, model_results)
    enriched = enrich_signals_with_cash_conversion_overlay(enriched, model_results)

    assert bool(enriched.iloc[0]["healthcare_overlay"]) is False
    assert bool(enriched.iloc[0]["cash_conversion_overlay"]) is True
    assert enriched.iloc[0]["adjusted_signal"] == "buy"


def test_enrich_signals_with_cash_conversion_overlay_uses_canonical_fcf():
    """Do not cap when canonical FCF is positive even if preserved screen TTM is negative."""
    signals = pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "name": "Hikma Pharmaceuticals PLC",
                "sector": "Health Care",
                "signal": "strong_buy",
                "free_cashflow": 119_000_000.0,
                "free_cashflow_screen_ttm": -66_125_000.0,
                "shares_outstanding": 240_000_000,
                "shares_outstanding_prev": 245_000_000,
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "model_id": "dividend_growth",
                "model_name": "Dividend Growth",
                "passed": True,
                "score": 0.8,
                "reasons": "['dividend payer: yield=3.9%']",
                "failed_criteria": "[]",
            },
        ]
    )

    enriched = enrich_signals_with_cash_conversion_overlay(signals, model_results)

    assert enriched.iloc[0]["signal"] == "strong_buy"
    assert bool(enriched.iloc[0]["cash_conversion_overlay"]) is False
    assert enriched.iloc[0]["adjusted_signal"] == "strong_buy"


def test_enrich_universe_with_canonical_fcf_uses_cached_financials(tmp_path: Path):
    sources = tmp_path / "research" / "HIK.L" / "sources"
    sources.mkdir(parents=True)
    financials = {
        "ticker": "HIK.L",
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 436_000_000.0,
                "Capital Expenditure": -317_000_000.0,
                "Free Cash Flow": 119_000_000.0,
            }
        },
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")

    universe = pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "name": "Hikma Pharmaceuticals PLC",
                "free_cashflow": -66_125_000.0,
            },
            {"ticker": "OTHER.L", "name": "Other plc", "free_cashflow": 10_000_000.0},
        ]
    )

    enriched = enrich_universe_with_canonical_fcf(universe, tmp_path)
    hik = enriched[enriched["ticker"] == "HIK.L"].iloc[0]
    other = enriched[enriched["ticker"] == "OTHER.L"].iloc[0]

    assert hik["free_cashflow_screen_ttm"] == -66_125_000.0
    assert hik["free_cashflow"] == 119_000_000.0
    assert other["free_cashflow"] == 10_000_000.0


def test_enrich_universe_keeps_screen_ttm_when_filing_within_25_pct(tmp_path: Path):
    sources = tmp_path / "research" / "CLOSE.L" / "sources"
    sources.mkdir(parents=True)
    financials = {
        "ticker": "CLOSE.L",
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 200_000_000.0,
                "Capital Expenditure": -100_000_000.0,
                "Free Cash Flow": 100_000_000.0,
            }
        },
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")

    universe = pd.DataFrame(
        [{"ticker": "CLOSE.L", "name": "Close Match plc", "free_cashflow": 92_000_000.0}]
    )
    enriched = enrich_universe_with_canonical_fcf(universe, tmp_path)
    row = enriched.iloc[0]

    assert row["free_cashflow_screen_ttm"] == 92_000_000.0
    assert row["free_cashflow"] == 92_000_000.0


def test_enrich_universe_uses_filing_when_gap_exceeds_25_pct_without_divergence_flag(
    tmp_path: Path,
):
    sources = tmp_path / "research" / "GAP.L" / "sources"
    sources.mkdir(parents=True)
    financials = {
        "ticker": "GAP.L",
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 200_000_000.0,
                "Capital Expenditure": -100_000_000.0,
                "Free Cash Flow": 100_000_000.0,
            }
        },
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")

    universe = pd.DataFrame(
        [{"ticker": "GAP.L", "name": "Gap Match plc", "free_cashflow": 70_000_000.0}]
    )
    enriched = enrich_universe_with_canonical_fcf(universe, tmp_path)
    row = enriched.iloc[0]

    assert fcf_filing_screen_mismatch(
        filing_aligned=100_000_000.0,
        screen_ttm=70_000_000.0,
        divergence_flagged=False,
    )
    assert row["free_cashflow_screen_ttm"] == 70_000_000.0
    assert row["free_cashflow"] == 100_000_000.0


def test_enrich_universe_with_filing_metrics_fills_ocf_and_adjusted_earnings(tmp_path: Path):
    sources = tmp_path / "research" / "MEGP.L" / "sources"
    sources.mkdir(parents=True)
    financials = {
        "ticker": "MEGP.L",
        "cash_flow": {
            "2025": {"Operating Cash Flow": 90_800_000.0, "Free Cash Flow": 55_000_000.0},
            "2024": {"Operating Cash Flow": 70_000_000.0},
        },
        "income_statement": {
            "2025": {"Normalized Income": 55_047_230.0, "Net Income": 56_572_000.0},
            "2024": {"Normalized Income": 50_000_000.0},
        },
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")

    universe = pd.DataFrame(
        [
            {
                "ticker": "MEGP.L",
                "name": "ME Group International plc",
                "operating_cashflow": None,
                "free_cashflow": 15_565_750.0,
                "net_income": 56_572_000.0,
            }
        ]
    )

    enriched = enrich_universe_with_filing_metrics(universe, tmp_path)
    row = enriched.iloc[0]

    assert row["operating_cashflow"] == 90_800_000.0
    assert row["operating_cashflow_prev"] == 70_000_000.0
    assert row["net_income_adjusted"] == 55_047_230.0
    assert row["net_income_adjusted_prev"] == 50_000_000.0
    assert row["free_cashflow"] == 15_565_750.0


def test_enrich_signals_with_dividend_yield_overlay_caps_megp_like_profile():
    signals = pd.DataFrame(
        [
            {
                "ticker": "MEGP.L",
                "name": "ME Group International plc",
                "sector": "Industrials",
                "signal": "strong_buy",
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "MEGP.L",
                "model_id": "high_dividend",
                "model_name": "High Dividend Yield",
                "passed": True,
                "score": 0.9,
                "reasons": "['yield=7.6%']",
                "failed_criteria": "[]",
            },
            {
                "ticker": "MEGP.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": False,
                "score": 0.3,
                "reasons": "[]",
                "failed_criteria": "['FCF yield 3.7% below 5%']",
            },
            {
                "ticker": "MEGP.L",
                "model_id": "earnings_quality",
                "model_name": "Earnings Quality",
                "passed": False,
                "score": 0.5,
                "reasons": "[]",
                "failed_criteria": "['weak free-cash conversion']",
            },
        ]
    )

    enriched = enrich_signals_with_dividend_yield_overlay(signals, model_results)

    assert enriched.iloc[0]["signal"] == "strong_buy"
    assert bool(enriched.iloc[0]["dividend_yield_overlay"]) is True
    assert enriched.iloc[0]["adjusted_signal"] == "buy"


def test_parse_interim_eps_decline_pct_from_filing_prose():
    text = (
        "Diluted earnings per share of 6.48 pence, a decline of 3.9% "
        "(H1 2025: 6.74 pence per share)."
    )
    assert parse_interim_eps_decline_pct(text) == pytest.approx(0.039)


def test_enrich_universe_with_filing_metrics_extracts_interim_eps_decline(tmp_path: Path):
    sources = tmp_path / "research" / "MEGP.L" / "sources"
    filings_dir = sources / "filings" / "bodies"
    filings_dir.mkdir(parents=True)
    body_path = filings_dir / "interim.txt"
    body_path.write_text(
        "Diluted earnings per share of 6.48 pence, a decline of 3.9% "
        "(H1 2025: 6.74 pence per share).",
        encoding="utf-8",
    )
    (sources / "filings").mkdir(parents=True, exist_ok=True)
    (sources / "filings" / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": "interim",
                        "period": "interim",
                        "has_body": True,
                        "body_path": str(body_path),
                        "published_at": "2026-07-13",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    financials = {
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 90_762_000.0,
                "Free Cash Flow": 25_153_000.0,
                "Cash Dividends Paid": -29_769_000.0,
            }
        },
        "income_statement": {"2025": {"Normalized Income": 55_047_230.0}},
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")

    universe = pd.DataFrame([{"ticker": "MEGP.L", "name": "ME Group International plc"}])
    enriched = enrich_universe_with_filing_metrics(universe, tmp_path)
    row = enriched.iloc[0]

    assert row["dividends_paid"] == pytest.approx(29_769_000.0)
    assert row["interim_eps_decline_pct"] == pytest.approx(0.039)


def test_enrich_signals_with_interim_quality_overlay_caps_megp_like_profile():
    signals = pd.DataFrame(
        [
            {
                "ticker": "MEGP.L",
                "name": "ME Group International plc",
                "sector": "Industrials",
                "signal": "strong_buy",
                "passed_families": "cheapness,quality,dividend,garp,risk",
                "free_cashflow": 25_153_000.0,
                "interim_eps_decline_pct": 0.039,
                "dividends_paid": 29_769_000.0,
            }
        ]
    )
    model_results = pd.DataFrame([])

    enriched = enrich_signals_with_interim_quality_overlay(signals, model_results)

    assert enriched.iloc[0]["signal"] == "strong_buy"
    assert bool(enriched.iloc[0]["interim_quality_overlay"]) is True
    assert enriched.iloc[0]["adjusted_signal"] == "buy"


def test_enrich_signals_with_interim_quality_overlay_not_triggered_without_interim_decline():
    signals = pd.DataFrame(
        [
            {
                "ticker": "MEGP.L",
                "signal": "strong_buy",
                "passed_families": "cheapness,quality,dividend,garp,risk",
                "free_cashflow": 25_153_000.0,
                "dividends_paid": 29_769_000.0,
            }
        ]
    )

    enriched = enrich_signals_with_interim_quality_overlay(signals, pd.DataFrame())

    assert bool(enriched.iloc[0]["interim_quality_overlay"]) is False
    assert enriched.iloc[0]["adjusted_signal"] == "strong_buy"


def test_enrich_signals_with_fcf_basis_overlay_caps_yield_inflated_strong_buy(tmp_path: Path):
    sources = tmp_path / "research" / "FGP.L" / "sources"
    filings = sources / "filings" / "bodies"
    filings.mkdir(parents=True)
    financials = {
        "ticker": "FGP.L",
        "cash_flow": {
            "2026": {
                "Operating Cash Flow": 615_600_000.0,
                "Capital Expenditure": -253_000_000.0,
                "Free Cash Flow": 362_600_000.0,
            }
        },
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")
    (filings / "ir_results.txt").write_text(
        "Free Cash Flow of £113.5m before acquisitions and returns",
        encoding="utf-8",
    )
    (sources / "filings" / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "period": "annual",
                        "has_body": True,
                        "body_path": str(filings / "ir_results.txt"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    signals = pd.DataFrame(
        [
            {
                "ticker": "FGP.L",
                "signal": "strong_buy",
                "conviction_score": 0.6,
                "free_cashflow": 362_600_000.0,
                "free_cashflow_screen_ttm": 302_812_512.0,
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "FGP.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.9,
                "reasons": "['FCF yield=37.3%']",
                "failed_criteria": "[]",
            }
        ]
    )

    enriched = enrich_signals_with_fcf_basis_overlay(signals, model_results, output_dir=tmp_path)

    assert bool(enriched.iloc[0]["fcf_basis_overlay"]) is True
    assert enriched.iloc[0]["adjusted_signal"] == "buy"
    assert enriched.iloc[0]["conviction_score"] == pytest.approx(0.51)


def test_parse_adjusted_eps_growth_pct_from_ir_prose():
    assert parse_adjusted_eps_growth_pct("Adjusted EPS increased by 16% to 9.9p") == pytest.approx(
        0.16
    )


def test_enrich_universe_with_filing_metrics_extracts_adjusted_eps_growth(tmp_path: Path):
    sources = tmp_path / "research" / "FGP.L" / "sources"
    filings = sources / "filings" / "bodies"
    filings.mkdir(parents=True)
    body_path = filings / "annual.txt"
    body_path.write_text("Adjusted EPS +16% to 19.4p", encoding="utf-8")
    (sources / "filings" / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": "annual",
                        "period": "annual",
                        "has_body": True,
                        "body_path": str(body_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    universe = pd.DataFrame([{"ticker": "FGP.L", "name": "FirstGroup plc"}])
    enriched = enrich_universe_with_filing_metrics(universe, tmp_path)
    row = enriched.iloc[0]

    assert row["adjusted_eps_growth_pct"] == pytest.approx(0.16)


def test_enrich_signals_with_earnings_basis_overlay_caps_fgp_like_profile():
    signals = pd.DataFrame(
        [
            {
                "ticker": "FGP.L",
                "name": "FirstGroup plc",
                "sector": "Industrials",
                "signal": "strong_buy",
                "conviction_score": 0.6,
                "earnings_growth": -0.059,
                "basic_eps_growth_pct": 0.005,
                "adjusted_eps_growth_pct": 0.16,
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "FGP.L",
                "model_id": "neff_pegy",
                "model_name": "Neff PEGY",
                "passed": True,
                "score": 0.85,
                "reasons": "['PEGY=0.72']",
                "failed_criteria": "[]",
            }
        ]
    )

    enriched = enrich_signals_with_earnings_basis_overlay(signals, model_results)

    assert enriched.iloc[0]["signal"] == "strong_buy"
    assert bool(enriched.iloc[0]["earnings_basis_overlay"]) is False
    assert enriched.iloc[0]["adjusted_signal"] == "strong_buy"
    assert enriched.iloc[0]["conviction_score"] == pytest.approx(0.6)


def test_enrich_signals_with_earnings_basis_overlay_falls_back_to_yahoo_without_basic_eps():
    signals = pd.DataFrame(
        [
            {
                "ticker": "FGP.L",
                "signal": "strong_buy",
                "conviction_score": 0.6,
                "earnings_growth": -0.059,
                "adjusted_eps_growth_pct": 0.16,
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "FGP.L",
                "model_id": "neff_pegy",
                "model_name": "Neff PEGY",
                "passed": True,
                "score": 0.85,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    enriched = enrich_signals_with_earnings_basis_overlay(signals, model_results)

    assert bool(enriched.iloc[0]["earnings_basis_overlay"]) is True
    assert enriched.iloc[0]["adjusted_signal"] == "buy"
    assert enriched.iloc[0]["conviction_score"] == pytest.approx(0.51)


def _fgp_style_research_tree(tmp_path: Path) -> None:
    sources = tmp_path / "research" / "FGP.L" / "sources"
    filings = sources / "filings" / "bodies"
    filings.mkdir(parents=True)
    financials = {
        "ticker": "FGP.L",
        "cash_flow": {
            "2026": {
                "Operating Cash Flow": 615_600_000.0,
                "Capital Expenditure": -253_000_000.0,
                "Free Cash Flow": 362_600_000.0,
            }
        },
        "income_statement": {
            "2026": {"Basic EPS": 0.214},
            "2025": {"Basic EPS": 0.213},
        },
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")
    (filings / "ir_results.txt").write_text(
        "Free Cash Flow of £113.5m before acquisitions and returns",
        encoding="utf-8",
    )
    (sources / "filings" / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "period": "annual",
                        "has_body": True,
                        "body_path": str(filings / "ir_results.txt"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_fcf_yield_pass_suppressed_when_divergence_exceeds_company_tolerance():
    assert (
        fcf_within_company_tolerance(
            362_600_000.0,
            113_500_000.0,
            company_adjusted_currency="GBP",
        )
        is False
    )
    assert (
        fcf_yield_pass_suppressed(
            divergence_flagged=True,
            canonical=362_600_000.0,
            company_adjusted=113_500_000.0,
            company_adjusted_currency="GBP",
        )
        is True
    )
    assert (
        fcf_yield_pass_suppressed(
            divergence_flagged=True,
            canonical=120_000_000.0,
            company_adjusted=113_500_000.0,
            company_adjusted_currency="GBP",
        )
        is False
    )


def test_extract_cashflow_metrics_use_ocf_capex_for_prior_year():
    financials = {
        "cash_flow": {
            "2026": {
                "Operating Cash Flow": 615_600_000.0,
                "Capital Expenditure": -253_000_000.0,
                "Free Cash Flow": 999_000_000.0,
            },
            "2025": {
                "Operating Cash Flow": 754_200_000.0,
                "Capital Expenditure": -156_400_000.0,
                "Free Cash Flow": 999_000_000.0,
            },
        }
    }
    metrics = extract_cashflow_metrics_from_annual_financials(financials)
    assert metrics["free_cashflow"] == pytest.approx(362_600_000.0)
    assert metrics["free_cashflow_prev"] == pytest.approx(597_800_000.0)


def test_enrich_universe_with_filing_metrics_extracts_basic_eps_growth(tmp_path: Path):
    _fgp_style_research_tree(tmp_path)
    universe = pd.DataFrame([{"ticker": "FGP.L", "name": "FirstGroup plc"}])
    enriched = enrich_universe_with_filing_metrics(universe, tmp_path)
    row = enriched.iloc[0]
    assert row["basic_eps"] == pytest.approx(0.214)
    assert row["basic_eps_prev"] == pytest.approx(0.213)
    assert row["basic_eps_growth_pct"] == pytest.approx(0.00469483568, rel=1e-4)


def test_suppress_fcf_yield_passes_for_fgp_style_mismatch(tmp_path: Path):
    _fgp_style_research_tree(tmp_path)
    universe = pd.DataFrame(
        [
            {
                "ticker": "FGP.L",
                "free_cashflow": 362_600_000.0,
                "market_cap": 973_000_000.0,
            }
        ]
    )
    universe = enrich_universe_with_canonical_fcf(universe, tmp_path)
    universe = enrich_universe_with_filing_metrics(universe, tmp_path)
    model_results = evaluate_universe(universe, models=[FCFYieldModel()])
    fcf_yield_before = model_results.loc[model_results["model_id"] == "fcf_yield", "passed"].iloc[0]
    assert bool(fcf_yield_before) is True

    model_results = suppress_fcf_yield_passes(model_results, universe, output_dir=tmp_path)
    fcf_yield = model_results.loc[model_results["model_id"] == "fcf_yield"].iloc[0]
    assert bool(fcf_yield["passed"]) is False
    assert "FCF yield suppressed" in str(fcf_yield["failed_criteria"])


def test_enrich_universe_with_filing_metrics_computes_dual_dividend_coverage(tmp_path: Path):
    sources = tmp_path / "research" / "MEGP.L" / "sources"
    filings_dir = sources / "filings" / "bodies"
    filings_dir.mkdir(parents=True)
    body_path = filings_dir / "annual.txt"
    body_path.write_text(
        "Cash generated from operations £115.5m while net cash generated from operating "
        "activities was £90.8m.",
        encoding="utf-8",
    )
    (sources / "filings" / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": "annual",
                        "period": "annual",
                        "has_body": True,
                        "body_path": str(body_path),
                        "published_at": "2026-03-23",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    financials = {
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 90_762_000.0,
                "Capital Expenditure": -65_609_000.0,
                "Free Cash Flow": 25_153_000.0,
                "Cash Dividends Paid": -29_769_000.0,
            }
        }
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")

    enriched = enrich_universe_with_filing_metrics(
        pd.DataFrame([{"ticker": "MEGP.L", "name": "ME Group International plc"}]),
        tmp_path,
    )
    row = enriched.iloc[0]

    assert row["operating_cashflow"] == pytest.approx(90_762_000.0)
    assert row["operating_cashflow_gross"] == pytest.approx(115_500_000.0)
    assert row["fcf_dividend_coverage_net"] == pytest.approx(25_153_000.0 / 29_769_000.0)
    assert row["fcf_dividend_coverage_gross"] == pytest.approx(49_891_000.0 / 29_769_000.0)


def test_enrich_universe_dual_coverage_ignores_interim_gross_ocf(tmp_path: Path):
    """Annual gross OCF must not be replaced by a newer interim filing body (MEGP −0.90× artefact)."""
    sources = tmp_path / "research" / "MEGP.L" / "sources"
    filings_dir = sources / "filings" / "bodies"
    filings_dir.mkdir(parents=True)
    annual_body = filings_dir / "annual.txt"
    annual_body.write_text(
        "Cash generated from operations £115.5m while net cash generated from operating "
        "activities was £90.8m.",
        encoding="utf-8",
    )
    interim_body = filings_dir / "interim.txt"
    interim_body.write_text(
        "Cash generated from operations £38.7m while net cash generated from operating "
        "activities was £38.7m.",
        encoding="utf-8",
    )
    (sources / "filings" / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": "interim",
                        "period": "interim",
                        "has_body": True,
                        "body_path": str(interim_body),
                        "published_at": "2026-07-13",
                    },
                    {
                        "id": "annual",
                        "period": "annual",
                        "has_body": True,
                        "body_path": str(annual_body),
                        "published_at": "2026-03-23",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    financials = {
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 90_762_000.0,
                "Capital Expenditure": -65_609_000.0,
                "Free Cash Flow": 25_153_000.0,
                "Cash Dividends Paid": -29_769_000.0,
            }
        }
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")

    enriched = enrich_universe_with_filing_metrics(
        pd.DataFrame([{"ticker": "MEGP.L", "name": "ME Group International plc"}]),
        tmp_path,
    )
    row = enriched.iloc[0]

    assert row["operating_cashflow_gross"] == pytest.approx(115_500_000.0)
    assert row["fcf_dividend_coverage_gross"] == pytest.approx(49_891_000.0 / 29_769_000.0)
    assert row["fcf_dividend_coverage_gross"] > 1.0
    assert row["fcf_dividend_coverage_net"] == pytest.approx(25_153_000.0 / 29_769_000.0)


def test_enrich_signals_with_interim_quality_overlay_uses_annual_gross_coverage(tmp_path: Path):
    sources = tmp_path / "research" / "MEGP.L" / "sources"
    filings_dir = sources / "filings" / "bodies"
    filings_dir.mkdir(parents=True)
    annual_body = filings_dir / "annual.txt"
    annual_body.write_text(
        "Cash generated from operations £115.5m while net cash generated from operating "
        "activities was £90.8m.",
        encoding="utf-8",
    )
    interim_body = filings_dir / "interim.txt"
    interim_body.write_text(
        "Cash generated from operations £38.7m. "
        "Diluted earnings per share of 6.48 pence, a decline of 3.9%.",
        encoding="utf-8",
    )
    (sources / "filings" / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": "interim",
                        "period": "interim",
                        "has_body": True,
                        "body_path": str(interim_body),
                        "published_at": "2026-07-13",
                    },
                    {
                        "id": "annual",
                        "period": "annual",
                        "has_body": True,
                        "body_path": str(annual_body),
                        "published_at": "2026-03-23",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    financials = {
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 90_762_000.0,
                "Capital Expenditure": -65_609_000.0,
                "Free Cash Flow": 25_153_000.0,
                "Cash Dividends Paid": -29_769_000.0,
            }
        }
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")

    universe = pd.DataFrame(
        [{"ticker": "MEGP.L", "name": "ME Group International plc", "signal": "strong_buy"}]
    )
    enriched = enrich_universe_with_filing_metrics(universe, tmp_path)
    enriched["passed_families"] = "cheapness,quality,dividend,garp,risk"

    overlayed = enrich_signals_with_interim_quality_overlay(enriched, pd.DataFrame())
    row = overlayed.iloc[0]

    assert row["fcf_dividend_coverage_gross"] == pytest.approx(49_891_000.0 / 29_769_000.0)
    assert bool(row["interim_quality_overlay"]) is True
    assert row["adjusted_signal"] == "buy"


def test_enrich_signals_with_interim_quality_overlay_not_triggered_on_annual_gross_cover():
    signals = pd.DataFrame(
        [
            {
                "ticker": "TEST.L",
                "signal": "strong_buy",
                "passed_families": "cheapness,quality,dividend,garp,risk",
                "interim_eps_decline_pct": 0.039,
                "fcf_dividend_coverage_gross": 1.68,
            }
        ]
    )

    enriched = enrich_signals_with_interim_quality_overlay(signals, pd.DataFrame())

    assert bool(enriched.iloc[0]["interim_quality_overlay"]) is False
    assert enriched.iloc[0]["adjusted_signal"] == "strong_buy"


def test_enrich_signals_with_cyclical_exposure_overlay_flags_megp_like_profile():
    from value_investor.scoring.cyclical_exposure_overlay import (
        enrich_signals_with_cyclical_exposure_overlay,
    )

    signals = pd.DataFrame(
        [
            {
                "ticker": "MEGP.L",
                "signal": "strong_buy",
                "passed_families": "cheapness,quality,dividend,garp,risk",
                "interim_eps_decline_pct": 0.039,
                "dividends_paid": 29_769_000.0,
                "fcf_dividend_coverage_net": 0.85,
                "cyclical_exposure_detected": True,
            }
        ]
    )

    enriched = enrich_signals_with_cyclical_exposure_overlay(signals, pd.DataFrame())

    assert bool(enriched.iloc[0]["cyclical_exposure_overlay"]) is True
    assert enriched.iloc[0]["adjusted_signal"] == "buy"


def test_enrich_signals_with_healthcare_price_erosion_overlay_caps_hik_like_profile():
    from value_investor.scoring.healthcare_price_erosion_overlay import (
        enrich_signals_with_healthcare_price_erosion_overlay,
    )

    signals = pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "sector": "Health Care",
                "signal": "strong_buy",
                "passed_families": "quality,dividend,garp,risk",
                "healthcare_price_erosion_detected": True,
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "model_id": model_id,
                "passed": False,
                "score": 0.2,
            }
            for model_id in ("high_dividend", "fcf_yield", "earnings_yield", "low_pe_high_yield")
        ]
        + [
            {
                "ticker": "HIK.L",
                "model_id": "buffett_quality",
                "passed": True,
                "score": 0.8,
            }
        ]
    )

    enriched = enrich_signals_with_healthcare_price_erosion_overlay(signals, model_results)

    assert bool(enriched.iloc[0]["healthcare_price_erosion_overlay"]) is True
    assert enriched.iloc[0]["adjusted_signal"] == "buy"
