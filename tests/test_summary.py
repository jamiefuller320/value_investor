"""Tests for company report / screening snapshot export fields."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from value_investor.models.piotroski import PiotroskiFScoreModel, piotroski_snapshot_from_result
from value_investor.models.risk import EarningsQualityModel
from value_investor.scoring import evaluate_universe
from value_investor.scoring.fcf import (
    append_fcf_divergence_to_action_note,
    build_labelled_fcf_dividend_coverage,
    earnings_growth_signs_diverge,
    enrich_universe_with_filing_metrics,
    extract_company_adjusted_fcf_from_reconciliation_bridges,
    fcf_action_note_mismatch,
    fcf_basis_divergence_flagged,
    fcf_filing_screen_mismatch,
    fcf_universe_divergence_flagged,
    fcf_values_diverge,
    ocf_definition_diverges,
    overlay_free_cashflow_from_bundle,
    parse_adjusted_eps_growth_pct,
    parse_company_adjusted_fcf,
    reconcile_fcf,
)
from value_investor.scoring.sector_overrides import AGRICULTURE_COMMODITIES_SECTOR
from value_investor.signals import Signal, assign_signal
from value_investor.summary import build_company_reports


def _signal_row(**overrides) -> dict:
    base = {
        "ticker": "HIK.L",
        "name": "Hikma Pharmaceuticals PLC",
        "sector": "Health Care",
        "signal": "strong_buy",
        "models_passed": 13,
        "model_count": 22,
        "composite_score": 0.75,
        "sector_composite_score": 0.91,
        "families_passed": 4,
        "passed_families": "cheapness,quality,garp,risk",
        "data_quality_score": 0.95,
        "metrics_present": 19,
        "metrics_total": 20,
        "weeks_at_signal": 2,
        "signal_trend": "stable",
        "conviction_score": 0.55,
        "stability_label": "building",
        "timing_signal": "neutral",
        "timing_score": 0.5,
        "rsi_14": 55.0,
        "price_vs_sma200_pct": 0.02,
        "timing_reasons": "[]",
        "action_note": "",
    }
    base.update(overrides)
    return base


def _model_results_for_hik() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "model_id": "graham_enterprising",
                "model_name": "Graham Enterprising",
                "passed": True,
                "score": 0.9,
                "reasons": "['P/E=11.6']",
                "failed_criteria": "[]",
            },
            {
                "ticker": "HIK.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": False,
                "score": 0.0,
                "reasons": "[]",
                "failed_criteria": "['negative free cash flow']",
            },
            {
                "ticker": "HIK.L",
                "model_id": "piotroski_f",
                "model_name": "Piotroski F-Score",
                "passed": False,
                "score": 6 / 9,
                "reasons": "['F-Score=6/9', 'positive net income', 'positive operating cash flow']",
                "failed_criteria": "['F-Score 6/9 below 7', 'ROA improving', 'OCF > net income']",
            },
        ]
    )


def _model_results_for_hik_cash_conversion_cap(*, ticker: str = "HIKX.L") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "model_id": "dividend_growth",
                "model_name": "Dividend Growth",
                "passed": True,
                "score": 0.8,
                "reasons": "['dividend payer: yield=3.9%']",
                "failed_criteria": "[]",
            },
            {
                "ticker": ticker,
                "model_id": "piotroski_f",
                "model_name": "Piotroski F-Score",
                "passed": True,
                "score": 7 / 9,
                "reasons": "['F-Score=7/9', 'positive net income', 'no share dilution']",
                "failed_criteria": "['OCF > net income']",
            },
        ]
    )


def test_build_company_reports_exports_failed_models():
    signals = pd.DataFrame([_signal_row()])
    model_results = _model_results_for_hik()

    report = build_company_reports(signals, model_results)[0]

    assert report.failed_models == ["FCF Yield", "Piotroski F-Score"]
    assert "Graham Enterprising" in report.passed_models
    assert report.signal == "strong_buy"


def test_build_company_reports_exports_model_failures_and_screening_inputs():
    signals = pd.DataFrame(
        [
            _signal_row(
                debt_to_equity=140.0,
                current_ratio=0.73,
                earnings_growth=-0.072,
                dividend_yield=0.04,
                ncav=None,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "model_id": "graham_enterprising",
                "model_name": "Graham Enterprising",
                "passed": False,
                "score": 0.5,
                "reasons": "[]",
                "failed_criteria": "['negative earnings growth', 'excessive leverage']",
            },
            {
                "ticker": "HIK.L",
                "model_id": "graham_net_net",
                "model_name": "Graham Net-Net",
                "passed": False,
                "score": 0.0,
                "reasons": "[]",
                "failed_criteria": "['missing NCAV (balance sheet data)']",
            },
            {
                "ticker": "HIK.L",
                "model_id": "financial_health",
                "model_name": "Financial Health",
                "passed": False,
                "score": 0.4,
                "reasons": "[]",
                "failed_criteria": "['high debt to equity', 'weak liquidity']",
            },
        ]
    )

    snapshot = build_company_reports(signals, model_results)[0].to_dict()

    assert snapshot["model_failures"]["Graham Enterprising"] == [
        "negative earnings growth",
        "excessive leverage",
    ]
    assert snapshot["model_failures"]["Graham Net-Net"] == ["missing NCAV (balance sheet data)"]
    assert snapshot["screening_inputs"]["debt_to_equity"] == 140.0
    assert snapshot["screening_inputs"]["current_ratio"] == 0.73
    assert snapshot["screening_inputs"]["earnings_growth_pct"] == -0.072
    assert snapshot["screening_inputs"]["ncav_available"] is False
    assert snapshot["screening_inputs"]["dividend_yield_raw"] == 0.04


def test_build_company_reports_exports_piotroski_component_scores():
    signals = pd.DataFrame([_signal_row()])
    model_results = _model_results_for_hik()

    snapshot = build_company_reports(signals, model_results)[0].to_dict()

    assert snapshot["piotroski_f_score"]["score"] == 6
    assert snapshot["piotroski_f_score"]["max_score"] == 9
    assert snapshot["piotroski_f_score"]["passed"] is False
    components = {
        item["name"]: item["passed"] for item in snapshot["piotroski_f_score"]["components"]
    }
    assert components["positive net income"] is True
    assert components["ROA improving"] is False


def test_company_report_to_dict_keeps_existing_fields():
    signals = pd.DataFrame([_signal_row()])
    model_results = _model_results_for_hik()

    snapshot = build_company_reports(signals, model_results)[0].to_dict()

    assert snapshot["ticker"] == "HIK.L"
    assert snapshot["passed_models"] == ["Graham Enterprising"]
    assert "failed_models" in snapshot
    assert "model_failures" in snapshot
    assert "screening_inputs" in snapshot
    assert "piotroski_f_score" in snapshot


def test_piotroski_snapshot_from_evaluated_universe():
    universe = pd.DataFrame(
        [
            {
                "ticker": "AAA.L",
                "name": "Alpha",
                "net_income": 100,
                "operating_cashflow": 150,
                "return_on_assets": 0.1,
                "return_on_assets_prev": 0.08,
                "leverage": 0.3,
                "leverage_prev": 0.35,
                "current_ratio_bs": 2.0,
                "current_ratio_bs_prev": 1.8,
                "shares_outstanding": 100,
                "shares_outstanding_prev": 102,
                "gross_margin": 0.4,
                "gross_margin_prev": 0.38,
                "asset_turnover": 1.2,
                "asset_turnover_prev": 1.1,
            }
        ]
    )
    model_results = evaluate_universe(universe, models=[PiotroskiFScoreModel()])
    signals = pd.DataFrame(
        [
            {
                "ticker": "AAA.L",
                "name": "Alpha",
                "signal": "buy",
                "models_passed": 1,
                "model_count": 1,
            }
        ]
    )

    snapshot = build_company_reports(signals, model_results)[0].to_dict()

    assert snapshot["piotroski_f_score"]["passed"] is True
    assert snapshot["piotroski_f_score"]["score"] >= 7
    assert len(snapshot["piotroski_f_score"]["components"]) == 9


def test_piotroski_snapshot_from_result_uses_details_when_present():
    payload = piotroski_snapshot_from_result(
        passed=True,
        score=8 / 9,
        reasons=["F-Score=8/9"],
        failed_criteria=[],
        details={
            "f_score": 8,
            "max_score": 9,
            "components": [{"name": "positive net income", "passed": True}],
        },
    )
    assert payload["score"] == 8
    assert payload["components"] == [{"name": "positive net income", "passed": True}]


def test_strong_buy_confirmation_unchanged_by_snapshot_export():
    signal = assign_signal(
        models_passed=13,
        model_count=22,
        mean_model_score=0.75,
        weighted_model_score=0.75,
        composite_score=0.75,
        sector_composite_score=0.91,
        families_passed=4,
        family_count=5,
        data_quality_score=0.95,
        risk_family_passed=True,
        risk_mean_score=0.8,
        has_errors=False,
    )
    assert signal == Signal.STRONG_BUY


def test_build_company_reports_exports_overridden_plantation_sector():
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="AEP.L",
                name="AEP Plantations Plc",
                sector=AGRICULTURE_COMMODITIES_SECTOR,
                sector_composite_score=0.55,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "AEP.L",
                "model_id": "composite_value",
                "model_name": "Composite Value",
                "passed": True,
                "score": 0.7,
                "reasons": "[]",
                "failed_criteria": "[]",
            },
        ]
    )

    report = build_company_reports(signals, model_results)[0]

    assert report.sector == AGRICULTURE_COMMODITIES_SECTOR
    assert report.sector_composite_score == 0.55
    assert "sector-relative 55%" in report.summary


def _healthcare_overlay_models(*, f_score: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "PHAR.L",
                "model_id": "piotroski_f",
                "model_name": "Piotroski F-Score",
                "passed": False,
                "score": f_score / 9,
                "reasons": f"['F-Score={f_score}/9']",
                "failed_criteria": f"['F-Score {f_score}/9 below 7']",
            },
        ]
    )


def test_healthcare_overlay_caps_strong_buy_when_negative_fcf_and_weak_piotroski():
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="PHAR.L",
                name="Pharma Weak Ltd",
                sector="Healthcare",
                signal="strong_buy",
                free_cashflow=-50.0,
            )
        ]
    )
    model_results = _healthcare_overlay_models(f_score=3)

    report = build_company_reports(signals, model_results)[0]
    snapshot = report.to_dict()

    assert report.signal == "strong_buy"
    assert snapshot["healthcare_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert "Healthcare overlay" in report.summary


def test_healthcare_overlay_not_triggered_for_hik_like_profile():
    signals = pd.DataFrame(
        [
            _signal_row(free_cashflow=-100.0),
        ]
    )
    model_results = _model_results_for_hik()

    report = build_company_reports(signals, model_results)[0]

    assert report.signal == "strong_buy"
    snapshot = report.to_dict()
    assert snapshot["healthcare_overlay"] is False
    assert snapshot["cash_conversion_overlay"] is False
    # Committed HIK.L FCF bridge marks filing/screen mismatch → basis overlay caps Strong Buy.
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"


def _model_results_for_megp_dividend_overlay(*, ticker: str = "MEGP.L") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "model_id": "high_dividend",
                "model_name": "High Dividend Yield",
                "passed": True,
                "score": 0.9,
                "reasons": "['yield=7.6%']",
                "failed_criteria": "[]",
            },
            {
                "ticker": ticker,
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": False,
                "score": 0.3,
                "reasons": "[]",
                "failed_criteria": "['FCF yield 3.7% below 5%']",
            },
            {
                "ticker": ticker,
                "model_id": "earnings_quality",
                "model_name": "Earnings Quality",
                "passed": False,
                "score": 0.5,
                "reasons": "[]",
                "failed_criteria": "['weak free-cash conversion']",
            },
        ]
    )


def test_dividend_yield_overlay_caps_megp_like_profile():
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="MEGP.L",
                name="ME Group International plc",
                sector="Industrials",
                signal="strong_buy",
                dividend_yield=0.0757,
            ),
        ]
    )
    model_results = _model_results_for_megp_dividend_overlay()

    report = build_company_reports(signals, model_results)[0]
    snapshot = report.to_dict()

    assert report.signal == "strong_buy"
    assert snapshot["dividend_yield_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert "Dividend-yield overlay" in report.summary


def test_dividend_yield_overlay_not_triggered_when_fcf_yield_passes():
    signals = pd.DataFrame([_signal_row(ticker="MEGP.L", signal="strong_buy")])
    model_results = pd.DataFrame(
        [
            {
                "ticker": "MEGP.L",
                "model_id": "high_dividend",
                "model_name": "High Dividend Yield",
                "passed": True,
                "score": 0.9,
                "reasons": "[]",
                "failed_criteria": "[]",
            },
            {
                "ticker": "MEGP.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
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

    report = build_company_reports(signals, model_results)[0]

    assert report.to_dict()["dividend_yield_overlay"] is False
    assert report.to_dict()["adjusted_signal"] == "strong_buy"


def test_interim_quality_overlay_caps_megp_like_profile():
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="MEGP.L",
                name="ME Group International plc",
                sector="Industrials",
                signal="strong_buy",
                passed_families="cheapness,quality,dividend,garp,risk",
                free_cashflow=25_153_000.0,
                interim_eps_decline_pct=0.039,
                dividends_paid=29_769_000.0,
            ),
        ]
    )
    model_results = pd.DataFrame(
        columns=[
            "ticker",
            "model_id",
            "model_name",
            "passed",
            "score",
            "reasons",
            "failed_criteria",
        ]
    )

    report = build_company_reports(signals, model_results)[0]
    snapshot = report.to_dict()

    assert report.signal == "strong_buy"
    assert snapshot["interim_quality_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert "Interim-quality overlay" in report.summary


def test_interim_quality_overlay_not_triggered_when_fcf_covers_dividends():
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="TEST.L",
                signal="strong_buy",
                passed_families="cheapness,quality,dividend,garp,risk",
                free_cashflow=40_000_000.0,
                interim_eps_decline_pct=0.039,
                dividends_paid=29_769_000.0,
            ),
        ]
    )

    report = build_company_reports(
        signals,
        pd.DataFrame(
            columns=[
                "ticker",
                "model_id",
                "model_name",
                "passed",
                "score",
                "reasons",
                "failed_criteria",
            ]
        ),
    )[0]

    assert report.to_dict()["interim_quality_overlay"] is False
    assert report.to_dict()["adjusted_signal"] == "strong_buy"


def test_cash_conversion_overlay_caps_hik_like_profile():
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="HIKX.L",
                name="Hikma-like Test plc",
                free_cashflow=-66.1,
                shares_outstanding=240_000_000,
                shares_outstanding_prev=245_000_000,
            ),
        ]
    )
    model_results = _model_results_for_hik_cash_conversion_cap()

    report = build_company_reports(signals, model_results)[0]
    snapshot = report.to_dict()

    assert report.signal == "strong_buy"
    assert snapshot["healthcare_overlay"] is False
    assert snapshot["cash_conversion_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert "Cash-conversion overlay" in report.summary


def test_cash_conversion_overlay_not_triggered_without_dividend_screen():
    signals = pd.DataFrame(
        [
            _signal_row(
                free_cashflow=-66.1,
                shares_outstanding=240_000_000,
                shares_outstanding_prev=245_000_000,
            ),
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "HIK.L",
                "model_id": "piotroski_f",
                "model_name": "Piotroski F-Score",
                "passed": True,
                "score": 7 / 9,
                "reasons": "['F-Score=7/9', 'no share dilution']",
                "failed_criteria": "[]",
            },
        ]
    )

    report = build_company_reports(signals, model_results)[0]

    snapshot = report.to_dict()
    assert snapshot["cash_conversion_overlay"] is False
    # Committed HIK.L FCF bridge marks filing/screen mismatch → basis overlay caps Strong Buy.
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"


def test_cash_conversion_overlay_respects_existing_research_adjusted_signal():
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="HIKX.L",
                name="Hikma-like Test plc",
                free_cashflow=-66.1,
                shares_outstanding=240_000_000,
                shares_outstanding_prev=245_000_000,
                adjusted_signal="hold",
                research_verdict="pass",
            ),
        ]
    )
    model_results = _model_results_for_hik_cash_conversion_cap()

    report = build_company_reports(signals, model_results)[0]

    assert report.to_dict()["cash_conversion_overlay"] is True
    assert report.adjusted_signal == "hold"


def test_healthcare_overlay_respects_existing_research_adjusted_signal():
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="PHAR.L",
                name="Pharma Weak Ltd",
                sector="Health Care",
                signal="strong_buy",
                free_cashflow=-25.0,
                adjusted_signal="hold",
                research_verdict="pass",
            )
        ]
    )
    model_results = _healthcare_overlay_models(f_score=4)

    report = build_company_reports(signals, model_results)[0]

    assert report.to_dict()["healthcare_overlay"] is True
    assert report.adjusted_signal == "hold"


def _hik_financials() -> dict:
    return {
        "ticker": "HIK.L",
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 436_000_000.0,
                "Capital Expenditure": -317_000_000.0,
                "Free Cash Flow": 119_000_000.0,
            }
        },
    }


def test_earnings_quality_prefers_adjusted_net_income():
    model = EarningsQualityModel()
    statutory_only = model.evaluate(
        {
            "net_income": 100.0,
            "free_cashflow": 40.0,
            "operating_cashflow": 80.0,
            "total_assets": 1000.0,
        }
    )
    assert statutory_only.passed is False

    with_adjusted = model.evaluate(
        {
            "net_income": 100.0,
            "net_income_adjusted": 50.0,
            "free_cashflow": 40.0,
            "operating_cashflow": 80.0,
            "total_assets": 1000.0,
        }
    )
    assert with_adjusted.passed is True


def test_reconcile_fcf_prefers_filing_aligned_ocf_capex():
    bundle = reconcile_fcf(screen_ttm=-66_125_000.0, financials=_hik_financials())
    assert bundle["canonical"] == 119_000_000.0
    assert bundle["source"] == "filing_aligned_ocf_capex"
    assert bundle["source"] == "filing_aligned_ocf_capex"
    assert bundle["screen_ttm"] == -66_125_000.0
    assert bundle["cashflow_metrics_free_cashflow"] == 119_000_000.0


def test_fcf_values_diverge_on_sign_or_magnitude():
    assert fcf_values_diverge(119_000_000.0, -66_125_000.0) is True
    assert fcf_values_diverge(1_000_000.0, -1_000_000.0) is False
    assert fcf_values_diverge(60_000_000.0, -1_000_000.0) is True
    assert fcf_values_diverge(100.0, 80.0) is False
    assert fcf_values_diverge(100.0, 70.0, threshold=0.50) is False
    assert fcf_values_diverge(100.0, 40.0, threshold=0.50) is True
    assert fcf_values_diverge(100.0, 100.0) is False
    assert fcf_values_diverge(None, -66_125_000.0) is False


def test_fcf_filing_screen_mismatch_uses_25_pct_threshold():
    assert fcf_filing_screen_mismatch(
        filing_aligned=100_000_000.0,
        screen_ttm=70_000_000.0,
        divergence_flagged=False,
    )
    assert not fcf_filing_screen_mismatch(
        filing_aligned=100_000_000.0,
        screen_ttm=92_000_000.0,
        divergence_flagged=False,
    )
    assert fcf_filing_screen_mismatch(
        filing_aligned=100_000_000.0,
        screen_ttm=92_000_000.0,
        divergence_flagged=True,
    )


def test_fcf_filing_screen_mismatch_measures_gap_against_filing_fcf():
    """Gap vs filing FCF, not max(filing, screen), when screen TTM exceeds filing."""
    assert fcf_filing_screen_mismatch(
        filing_aligned=100_000_000.0,
        screen_ttm=126_000_000.0,
        divergence_flagged=False,
    )
    assert not fcf_filing_screen_mismatch(
        filing_aligned=100_000_000.0,
        screen_ttm=124_000_000.0,
        divergence_flagged=False,
    )


def test_reconcile_fcf_prefers_company_adjusted_when_present():
    bundle = reconcile_fcf(
        screen_ttm=362_600_000.0,
        financials=_fgp_financials(),
        company_adjusted=113_500_000.0,
        company_adjusted_currency="GBP",
    )
    assert bundle["canonical"] == 113_500_000.0
    assert bundle["source"] == "company_adjusted"
    assert bundle["divergence_flagged"] is True


def test_overlay_free_cashflow_from_bundle_uses_company_adjusted():
    row = pd.Series({"ticker": "FGP.L", "free_cashflow": 362_600_000.0})
    bundle = {
        "company_adjusted": 113_500_000.0,
        "filing_aligned": 362_600_000.0,
        "canonical": 113_500_000.0,
        "divergence_flagged": True,
    }
    assert overlay_free_cashflow_from_bundle(row, bundle) == 113_500_000.0


def test_overlay_free_cashflow_from_bundle_suppresses_screen_ttm_on_mismatch():
    row = pd.Series(
        {
            "free_cashflow": 70_000_000.0,
            "free_cashflow_screen_ttm": 70_000_000.0,
        }
    )
    bundle = {
        "canonical": 100_000_000.0,
        "filing_aligned": 100_000_000.0,
        "divergence_flagged": False,
    }
    assert overlay_free_cashflow_from_bundle(row, bundle) == 100_000_000.0

    close_row = pd.Series(
        {
            "free_cashflow": 92_000_000.0,
            "free_cashflow_screen_ttm": 92_000_000.0,
        }
    )
    assert overlay_free_cashflow_from_bundle(close_row, bundle) == 92_000_000.0


def test_append_fcf_divergence_note_when_filing_screen_gap_exceeds_25_pct():
    note = append_fcf_divergence_to_action_note(
        "",
        canonical=100_000_000.0,
        screen_ttm=70_000_000.0,
        fcf_bundle={"filing_aligned": 100_000_000.0, "divergence_flagged": False},
    )
    assert "FCF basis mismatch" in note
    assert "filing $100M" in note
    assert "screen TTM $70M" in note


def test_fcf_basis_divergence_flags_fgp_style_mismatch():
    flagged = fcf_basis_divergence_flagged(
        filing_aligned=362_600_000.0,
        screen_ttm=302_812_512.0,
        company_adjusted=113_500_000.0,
        company_adjusted_currency="GBP",
    )
    assert flagged is True


def test_parse_company_adjusted_fcf_from_ir_prose():
    amount, currency = parse_company_adjusted_fcf("Free Cash Flow of £113.5m before acquisitions")
    assert amount == 113_500_000.0
    assert currency == "GBP"


def test_extract_company_adjusted_fcf_from_reconciliation_bridges(tmp_path: Path):
    sources = tmp_path / "research" / "FGP.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "ir_presentation_metrics.json").write_text(
        json.dumps(
            {
                "bridges": [
                    {
                        "period": "interim",
                        "bridge_type": "fcf_by_division",
                        "currency": "GBP",
                        "derived": {"total_fcf_millions": -35.6},
                    },
                    {
                        "period": "annual",
                        "bridge_type": "fcf_by_division",
                        "currency": "GBP",
                        "derived": {"total_fcf_millions": 113.5},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    amount, currency = extract_company_adjusted_fcf_from_reconciliation_bridges(
        "FGP.L",
        output_dir=tmp_path,
    )

    assert amount == 113_500_000.0
    assert currency == "GBP"


def test_append_fcf_divergence_to_action_note():
    bundle = reconcile_fcf(
        screen_ttm=-66_125_000.0,
        financials=_hik_financials(),
    )
    note = append_fcf_divergence_to_action_note(
        "Strong Buy — neutral timing",
        canonical=119_000_000.0,
        screen_ttm=-66_125_000.0,
        fcf_bundle=bundle,
    )
    assert "Strong Buy — neutral timing" in note
    assert "FCF basis mismatch" in note
    assert "filing $119M" in note
    assert "screen TTM −$66.1M" in note

    unchanged = append_fcf_divergence_to_action_note(
        "Buy — neutral timing",
        canonical=100.0,
        screen_ttm=90.0,
    )
    assert unchanged == "Buy — neutral timing"


def test_build_company_reports_exports_reconciled_fcf(tmp_path: Path):
    sources = tmp_path / "research" / "HIK.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(json.dumps(_hik_financials()), encoding="utf-8")

    signals = pd.DataFrame(
        [
            _signal_row(
                free_cashflow=-66_125_000.0,
                free_cashflow_screen_ttm=-66_125_000.0,
                shares_outstanding=240_000_000,
                shares_outstanding_prev=245_000_000,
            )
        ]
    )
    model_results = _model_results_for_hik_cash_conversion_cap(ticker="HIK.L")

    snapshot = build_company_reports(signals, model_results, output_dir=tmp_path)[0].to_dict()

    assert snapshot["key_metrics"]["FCF"] == "119000000.0"
    assert snapshot["cashflow_metrics"]["free_cashflow"] == 119_000_000.0
    assert snapshot["fcf"]["canonical"] == 119_000_000.0
    assert snapshot["fcf"]["source"] == "policy_filing_aligned"
    assert snapshot["fcf"]["bridge_resolved"] is True
    assert snapshot["fcf"]["screen_ttm"] == -66_125_000.0
    assert snapshot["fcf"]["divergence_flagged"] is True
    assert snapshot["fcf"]["filing_screen_mismatch"] is True
    assert snapshot["cash_conversion_overlay"] is False
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert "FCF basis mismatch" in snapshot["action_note"]
    assert "filing $119M" in snapshot["action_note"]
    assert "screen TTM −$66.1M" in snapshot["action_note"]


def test_build_company_reports_surfaces_fcf_bridge_when_timing_insufficient(tmp_path: Path):
    sources = tmp_path / "research" / "HIK.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(json.dumps(_hik_financials()), encoding="utf-8")

    signals = pd.DataFrame(
        [
            _signal_row(
                free_cashflow=-66_125_000.0,
                free_cashflow_screen_ttm=-66_125_000.0,
                timing_signal="insufficient_data",
                timing_score=0.0,
                rsi_14=None,
            )
        ]
    )
    model_results = _model_results_for_hik_cash_conversion_cap(ticker="HIK.L")

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]

    assert "FCF basis mismatch" in report.action_note
    assert "FCF basis mismatch" in report.summary


def _fgp_financials() -> dict:
    return {
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


def _model_results_for_fgp_fcf_basis_cap(*, ticker: str = "FGP.L") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.9,
                "reasons": "['FCF yield=37.3%']",
                "failed_criteria": "[]",
            },
            {
                "ticker": ticker,
                "model_id": "composite_value",
                "model_name": "Composite Value",
                "passed": True,
                "score": 0.85,
                "reasons": "['composite rank strong']",
                "failed_criteria": "[]",
            },
        ]
    )


def test_build_company_reports_exports_fcf_basis_overlay_for_fgp(tmp_path: Path):
    sources = tmp_path / "research" / "FGP.L" / "sources"
    filings = sources / "filings" / "bodies"
    filings.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(json.dumps(_fgp_financials()), encoding="utf-8")
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
            _signal_row(
                ticker="FGP.L",
                name="FirstGroup plc",
                sector="Industrials",
                signal="strong_buy",
                conviction_score=0.6,
                free_cashflow=362_600_000.0,
                free_cashflow_screen_ttm=302_812_512.0,
            )
        ]
    )
    model_results = _model_results_for_fgp_fcf_basis_cap()

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    snapshot = report.to_dict()

    assert snapshot["fcf"]["company_adjusted"] == 113_500_000.0
    assert snapshot["fcf"]["company_adjusted_currency"] == "GBP"
    assert snapshot["fcf"]["divergence_flagged"] is True
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert snapshot["conviction_score"] == pytest.approx(0.51)
    assert snapshot["cashflow_metrics"]["free_cashflow"] == 113_500_000.0
    assert snapshot["key_metrics"]["FCF"] == "113500000.0"
    assert "company-adj £113.5M" in snapshot["action_note"]


def test_earnings_growth_signs_diverge_detects_fgp_style_mismatch():
    assert earnings_growth_signs_diverge(-0.059, 0.16) is True
    assert earnings_growth_signs_diverge(0.05, 0.10) is False
    assert earnings_growth_signs_diverge(-0.05, -0.10) is False


def test_parse_adjusted_eps_growth_pct_from_filing_prose():
    assert parse_adjusted_eps_growth_pct("Adjusted EPS +16% to 19.4p") == pytest.approx(0.16)
    assert parse_adjusted_eps_growth_pct("16% growth in Adjusted EPS") == pytest.approx(0.16)


def _model_results_for_fgp_earnings_basis_cap(*, ticker: str = "FGP.L") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "model_id": "neff_pegy",
                "model_name": "Neff PEGY",
                "passed": True,
                "score": 0.85,
                "reasons": "['PEGY=0.72']",
                "failed_criteria": "[]",
            },
            {
                "ticker": ticker,
                "model_id": "lynch_peg",
                "model_name": "Lynch PEG",
                "passed": False,
                "score": 0.2,
                "reasons": "[]",
                "failed_criteria": "['missing or negative earnings growth']",
            },
        ]
    )


def test_build_company_reports_exports_earnings_basis_overlay_for_fgp(tmp_path: Path):
    sources = tmp_path / "research" / "FGP.L" / "sources"
    filings = sources / "filings" / "bodies"
    filings.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(json.dumps(_fgp_financials()), encoding="utf-8")
    (filings / "ir_results.txt").write_text(
        "Strong financial performance - 16% growth in Adjusted EPS\nAdjusted EPS +16% to 19.4p",
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
            _signal_row(
                ticker="FGP.L",
                name="FirstGroup plc",
                sector="Industrials",
                signal="strong_buy",
                conviction_score=0.6,
                earnings_growth=-0.059,
                basic_eps_growth_pct=0.214 / 0.213 - 1.0,
                adjusted_eps_growth_pct=0.16,
            )
        ]
    )
    model_results = _model_results_for_fgp_earnings_basis_cap()

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    snapshot = report.to_dict()

    assert snapshot["screening_inputs"]["earnings_growth_pct"] == pytest.approx(-0.059)
    assert snapshot["screening_inputs"]["basic_eps_growth_pct"] == pytest.approx(
        0.214 / 0.213 - 1.0
    )
    assert snapshot["screening_inputs"]["statutory_earnings_growth_pct"] == pytest.approx(
        0.214 / 0.213 - 1.0
    )
    assert snapshot["screening_inputs"]["adjusted_eps_growth_pct"] == pytest.approx(0.16)
    assert snapshot["earnings_basis_overlay"] is False
    # Committed FGP.L FCF bridge marks basis mismatch → FCF overlay caps Strong Buy.
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert snapshot["conviction_score"] == pytest.approx(0.51)


def test_build_company_reports_interim_quality_uses_filing_fcf_for_megp():
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="MEGP.L",
                name="ME Group International plc",
                sector="Industrials",
                signal="strong_buy",
                passed_families="cheapness,quality,dividend,garp,risk",
                free_cashflow=25_153_000.0,
                interim_eps_decline_pct=0.039,
                dividends_paid=29_769_000.0,
            ),
        ]
    )
    model_results = pd.DataFrame(
        columns=[
            "ticker",
            "model_id",
            "model_name",
            "passed",
            "score",
            "reasons",
            "failed_criteria",
        ]
    )

    report = build_company_reports(signals, model_results)[0]
    snapshot = report.to_dict()

    assert snapshot["interim_quality_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert "Interim-quality overlay" in report.summary


def test_build_company_reports_exports_operating_cashflow_and_dual_coverage(tmp_path: Path):
    sources = tmp_path / "research" / "MEGP.L" / "sources"
    sources.mkdir(parents=True)
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

    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="MEGP.L",
                name="ME Group International plc",
                sector="Industrials",
                signal="strong_buy",
                operating_cashflow=90_762_000.0,
                free_cashflow=25_153_000.0,
                dividends_paid=29_769_000.0,
                fcf_dividend_coverage_net=25_153_000.0 / 29_769_000.0,
                fcf_dividend_coverage_gross=49_891_000.0 / 29_769_000.0,
            ),
        ]
    )
    model_results = pd.DataFrame(
        columns=[
            "ticker",
            "model_id",
            "model_name",
            "passed",
            "score",
            "reasons",
            "failed_criteria",
        ]
    )

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    snapshot = report.to_dict()

    assert snapshot["operating_cashflow"] == pytest.approx(90_762_000.0)
    assert snapshot["fcf_dividend_coverage_net"] == pytest.approx(25_153_000.0 / 29_769_000.0)
    assert snapshot["fcf_dividend_coverage_gross"] == pytest.approx(49_891_000.0 / 29_769_000.0)
    assert snapshot["cashflow_metrics"]["operating_cashflow"] == pytest.approx(90_762_000.0)


def test_build_company_reports_exports_annual_aligned_gross_coverage(tmp_path: Path):
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
        "activities was £38.7m. Diluted earnings per share of 6.48 pence, a decline of 3.9%.",
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

    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="MEGP.L",
                name="ME Group International plc",
                sector="Industrials",
                signal="strong_buy",
                passed_families="cheapness,quality,dividend,garp,risk",
                free_cashflow=25_153_000.0,
            ),
        ]
    )
    signals = enrich_universe_with_filing_metrics(signals, tmp_path)
    model_results = pd.DataFrame(
        columns=[
            "ticker",
            "model_id",
            "model_name",
            "passed",
            "score",
            "reasons",
            "failed_criteria",
        ]
    )

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    snapshot = report.to_dict()

    assert snapshot["fcf_dividend_coverage_gross"] == pytest.approx(49_891_000.0 / 29_769_000.0)
    assert snapshot["fcf_dividend_coverage_gross"] > 1.0
    assert snapshot["interim_quality_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"


def test_ocf_definition_diverges_when_management_ocf_exceeds_statutory_by_15_pct():
    assert ocf_definition_diverges(90_762_000.0, 115_500_000.0) is True
    assert ocf_definition_diverges(90_762_000.0, 100_000_000.0) is False


def test_build_labelled_fcf_dividend_coverage_uses_statutory_and_management_labels():
    labelled = build_labelled_fcf_dividend_coverage(
        fcf_dividend_coverage_net=0.84,
        fcf_dividend_coverage_gross=1.68,
    )
    assert labelled["statutory_ocf_minus_capex"]["label"] == "Statutory OCF−CapEx"
    assert labelled["statutory_ocf_minus_capex"]["ratio"] == pytest.approx(0.84)
    assert labelled["management_cash_generated_minus_capex"]["label"] == (
        "Management cash-generated−CapEx"
    )
    assert labelled["management_cash_generated_minus_capex"]["ratio"] == pytest.approx(1.68)


def test_fcf_universe_divergence_flagged_at_15_pct_without_50_pct_overlay():
    assert fcf_universe_divergence_flagged(
        filing_aligned=100_000_000.0,
        screen_ttm=84_000_000.0,
        company_adjusted=None,
    )
    assert not fcf_basis_divergence_flagged(
        filing_aligned=100_000_000.0,
        screen_ttm=84_000_000.0,
        company_adjusted=None,
    )


def test_fcf_action_note_mismatch_triggers_at_15_pct_universe_gap():
    assert fcf_action_note_mismatch(
        filing_aligned=100_000_000.0,
        screen_ttm=84_000_000.0,
        company_adjusted=None,
    )
    assert not fcf_filing_screen_mismatch(
        filing_aligned=100_000_000.0,
        screen_ttm=84_000_000.0,
        divergence_flagged=False,
    )


def test_append_fcf_divergence_note_includes_definition_divergence_coverage():
    note = append_fcf_divergence_to_action_note(
        "Strong Buy — neutral timing",
        canonical=25_153_000.0,
        screen_ttm=25_153_000.0,
        fcf_definition_divergence=True,
        fcf_dividend_coverage_net=0.84,
        fcf_dividend_coverage_gross=1.68,
    )
    assert "FCF definition divergence" in note
    assert "statutory 0.84×" in note
    assert "management 1.68×" in note


def test_build_company_reports_exports_labelled_dual_coverage_and_flags(tmp_path: Path):
    sources = tmp_path / "research" / "MEGP.L" / "sources"
    filings_dir = sources / "filings" / "bodies"
    filings_dir.mkdir(parents=True)
    annual_body = filings_dir / "annual.txt"
    annual_body.write_text(
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
                        "body_path": str(annual_body),
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

    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="MEGP.L",
                name="ME Group International plc",
                sector="Industrials",
                signal="strong_buy",
                free_cashflow=25_153_000.0,
                free_cashflow_screen_ttm=15_565_750.0,
            ),
        ]
    )
    signals = enrich_universe_with_filing_metrics(signals, tmp_path)
    model_results = pd.DataFrame(
        columns=[
            "ticker",
            "model_id",
            "model_name",
            "passed",
            "score",
            "reasons",
            "failed_criteria",
        ]
    )

    snapshot = build_company_reports(signals, model_results, output_dir=tmp_path)[0].to_dict()

    assert snapshot["fcf_definition_divergence"] is True
    assert snapshot["fcf_divergence_flagged"] is True
    assert snapshot["fcf_dividend_coverage"]["statutory_ocf_minus_capex"]["ratio"] == pytest.approx(
        25_153_000.0 / 29_769_000.0
    )
    assert snapshot["fcf_dividend_coverage"]["management_cash_generated_minus_capex"][
        "ratio"
    ] == pytest.approx(49_891_000.0 / 29_769_000.0)
    assert "FCF definition divergence" in snapshot["action_note"]


def test_build_company_reports_exports_dual_leverage_display():
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="FGP.L",
                name="FirstGroup plc",
                debt_to_equity=19.4,
                debt_to_equity_yahoo=161.0,
                filing_adjusted_net_debt_gbp=137_700_000.0,
                leverage_override=True,
                dual_leverage_display=True,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "FGP.L",
                "model_id": "graham_enterprising",
                "model_name": "Graham Enterprising",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    snapshot = build_company_reports(signals, model_results)[0].to_dict()

    assert snapshot["leverage_override"] is True
    assert snapshot["dual_leverage_display"] is True
    assert snapshot["screening_inputs"]["debt_to_equity_yahoo"] == pytest.approx(161.0)
    assert snapshot["screening_inputs"]["filing_adjusted_net_debt_gbp"] == pytest.approx(
        137_700_000.0
    )
    assert snapshot["screening_inputs"]["debt_to_equity"] == pytest.approx(19.4)
    assert snapshot["key_metrics"]["D/E (Yahoo)"] == "161%"
    assert snapshot["key_metrics"]["Leverage (filing)"] == "£137.7m adj. net debt"
    assert "Leverage override" in snapshot["summary"]
