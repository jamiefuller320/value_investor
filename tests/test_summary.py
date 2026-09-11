"""Tests for company report / screening snapshot export fields."""

from __future__ import annotations

import json
from dataclasses import replace
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
    fcf_bundle_from_persisted_report,
    fcf_filing_screen_mismatch,
    fcf_universe_divergence_flagged,
    fcf_values_diverge,
    ocf_definition_diverges,
    overlay_free_cashflow_from_bundle,
    parse_adjusted_eps_growth_pct,
    parse_company_adjusted_fcf,
    parse_filing_aligned_from_action_note,
    parse_screen_ttm_from_action_note,
    reconcile_fcf,
)
from value_investor.scoring.sector_overrides import AGRICULTURE_COMMODITIES_SECTOR
from value_investor.signals import Signal, assign_signal
from value_investor.summary import (
    CompanyReport,
    apply_research_overlay_with_fcf_enforcement,
    build_company_reports,
    honour_fcf_action_note_enforcement,
)


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
        "family_count": 5,
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
    assert bundle["source"] == "auto_fallback_filing_aligned"
    assert bundle["policy_basis"] == "filing_aligned"
    assert bundle["auto_policy_resolved"] is True
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


def test_reconcile_fcf_discards_company_adjusted_outlier():
    # FGP-like: filing OCF−CapEx ≈ screen TTM; company-adjusted is the outlier.
    bundle = reconcile_fcf(
        screen_ttm=362_600_000.0,
        financials=_fgp_financials(),
        company_adjusted=113_500_000.0,
        company_adjusted_currency="GBP",
    )
    assert bundle["canonical"] == 362_600_000.0
    assert bundle["source"] == "auto_majority_filing_aligned"
    assert bundle["policy_basis"] == "filing_aligned"
    assert "company_adjusted" in (bundle.get("auto_policy_discarded") or [])
    assert bundle["divergence_flagged"] is True


def test_reconcile_fcf_majority_prefers_company_when_paired_with_filing():
    # ITV-like: company-adjusted agrees with filing; discard divergent Yahoo TTM.
    financials = {
        "ticker": "ITV.L",
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 202_000_000.0,
                "Capital Expenditure": -54_000_000.0,
                "Free Cash Flow": 148_000_000.0,
            }
        },
    }
    bundle = reconcile_fcf(
        screen_ttm=211_900_000.0,
        financials=financials,
        company_adjusted=187_000_000.0,
        company_adjusted_currency="GBP",
        filing_currency="GBP",
    )
    assert bundle["canonical"] == 187_000_000.0
    assert bundle["source"] == "auto_majority_company_adjusted"
    assert bundle["policy_basis"] == "company_adjusted"
    assert "screen_ttm" in (bundle.get("auto_policy_discarded") or [])


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


def _bree_financials() -> dict:
    return {
        "ticker": "BREE.L",
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 150_000_000.0,
                "Capital Expenditure": -44_200_000.0,
                "Free Cash Flow": 105_800_000.0,
            }
        },
    }


def _bree_research_sources(tmp_path: Path) -> None:
    sources = tmp_path / "research" / "BREE.L" / "sources"
    filings = sources / "filings" / "bodies"
    filings.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(_bree_financials()), encoding="utf-8"
    )
    (filings / "ir_results.txt").write_text(
        "Free Cash Flow of £133.2m before lease and acquisition adjustments",
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


def test_build_company_reports_fcf_basis_overlay_when_company_adj_diverges_bree_style(
    tmp_path: Path,
):
    _bree_research_sources(tmp_path)
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="BREE.L",
                name="Breedon Group plc",
                sector="Basic Materials",
                signal="strong_buy",
                conviction_score=0.7,
                free_cashflow=107_800_000.0,
                free_cashflow_screen_ttm=107_800_000.0,
                fcf_basis_overlay=False,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "BREE.L",
                "model_id": "graham_enterprising",
                "model_name": "Graham Enterprising",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    snapshot = build_company_reports(signals, model_results, output_dir=tmp_path)[0].to_dict()

    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert "FCF basis mismatch" in snapshot["action_note"]
    assert "filing £105.8M" in snapshot["action_note"]
    assert "screen TTM £107.8M" in snapshot["action_note"]
    assert "company-adj £133.2M" in snapshot["action_note"]


def _bowl_financials() -> dict:
    return {
        "ticker": "BOWL.L",
        "cash_flow": {
            "2026": {
                "Operating Cash Flow": 55_000_000.0,
                "Capital Expenditure": -18_000_000.0,
                "Free Cash Flow": 37_000_000.0,
            }
        },
    }


def test_fcf_basis_overlay_honours_action_note_predicate_below_25pct_filing_gap():
    """BOWL.L-style gap: universe note at 15% but filing/screen ratio below 25%."""
    filing = 37_000_000.0
    screen = 43_800_000.0
    assert fcf_universe_divergence_flagged(
        filing_aligned=filing,
        screen_ttm=screen,
        company_adjusted=None,
        filing_currency="GBP",
    )
    assert not fcf_filing_screen_mismatch(
        filing_aligned=filing,
        screen_ttm=screen,
        divergence_flagged=False,
    )
    note = append_fcf_divergence_to_action_note(
        "Buy — neutral timing",
        canonical=filing,
        screen_ttm=screen,
        fcf_bundle={
            "filing_aligned": filing,
            "currency": "GBP",
            "divergence_flagged": False,
            "fcf_divergence_flagged": True,
        },
    )
    assert "FCF basis mismatch" in note


def test_build_company_reports_exports_fcf_basis_overlay_for_bowl(tmp_path: Path):
    sources = tmp_path / "research" / "BOWL.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(_bowl_financials()), encoding="utf-8"
    )

    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="BOWL.L",
                name="Hollywood Bowl Group plc",
                sector="Consumer Cyclical",
                signal="buy",
                conviction_score=0.7284,
                free_cashflow=37_000_000.0,
                free_cashflow_screen_ttm=43_800_000.0,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "BOWL.L",
                "model_id": "graham_net_net",
                "model_name": "Graham",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    snapshot = build_company_reports(signals, model_results, output_dir=tmp_path)[0].to_dict()

    assert snapshot["fcf"]["fcf_divergence_flagged"] is True
    assert snapshot["fcf"]["filing_screen_mismatch"] is False
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"
    assert snapshot["conviction_score"] == pytest.approx(0.7284 * 0.85)
    assert "FCF basis mismatch" in snapshot["action_note"]
    assert "filing £37M" in snapshot["action_note"]
    assert "screen TTM £43.8M" in snapshot["action_note"]


def _dnlm_research_sources(tmp_path: Path) -> None:
    sources = tmp_path / "research" / "DNLM.L" / "sources"
    filings = sources / "filings" / "bodies"
    filings.mkdir(parents=True)
    financials = {
        "ticker": "DNLM.L",
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 255_900_000.0,
                "Capital Expenditure": -44_500_000.0,
                "Free Cash Flow": 211_400_000.0,
            }
        },
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")
    (filings / "annual_results.txt").write_text(
        "Company-adjusted free cash flow of £171.0m after working-capital normalisation",
        encoding="utf-8",
    )
    (sources / "filings" / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "period": "annual",
                        "has_body": True,
                        "body_path": str(filings / "annual_results.txt"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _tpk_financials() -> dict:
    return {
        "ticker": "TPK.L",
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 350_000_000.0,
                "Capital Expenditure": -52_000_000.0,
                "Free Cash Flow": 298_000_000.0,
            }
        },
    }


def test_build_company_reports_fcf_basis_overlay_caps_tpk_style_buy(tmp_path: Path):
    """TPK.L: 24% filing/screen gap (below 25%) still caps buy via universe divergence."""
    sources = tmp_path / "research" / "TPK.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(json.dumps(_tpk_financials()), encoding="utf-8")

    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="TPK.L",
                name="Travis Perkins plc",
                sector="Industrials",
                signal="buy",
                conviction_score=0.4026,
                free_cashflow=298_000_000.0,
                free_cashflow_screen_ttm=226_100_000.0,
                fcf_basis_overlay=False,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "TPK.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    snapshot = build_company_reports(signals, model_results, output_dir=tmp_path)[0].to_dict()

    assert snapshot["fcf"]["filing_screen_mismatch"] is False
    assert snapshot["fcf"]["fcf_divergence_flagged"] is True
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"
    assert "FCF basis mismatch" in snapshot["action_note"]
    assert "filing £298M" in snapshot["action_note"]
    assert "screen TTM £226.1M" in snapshot["action_note"]


def test_company_report_from_dict_honours_tpk_style_stale_fcf_note():
    """Deserialised rows must not ship buy beside an FCF mismatch action note."""
    stale = {
        "ticker": "TPK.L",
        "name": "Travis Perkins plc",
        "signal": "buy",
        "adjusted_signal": "buy",
        "fcf_basis_overlay": False,
        "conviction_score": 0.4026,
        "action_note": (
            "Buy — neutral timing | FCF basis mismatch: filing £298M | screen TTM £226.1M | "
            "Earnings growth basis divergence >300 bps: statutory -127.6% vs filing core -97.2%"
        ),
        "models_passed": 4,
        "model_count": 22,
        "composite_score": 0.75,
        "families_passed": 2,
        "data_quality_score": 0.95,
        "metrics_present": 19,
        "metrics_total": 20,
        "weeks_at_signal": 9,
        "signal_trend": "stable",
        "stability_label": "persistent",
        "timing_signal": "neutral",
        "timing_score": 0.375,
        "summary": "Buy (4/22 models).",
        "passed_models": [],
        "key_metrics": {},
    }
    snapshot = CompanyReport.from_dict(stale).to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"
    assert snapshot["conviction_score"] == pytest.approx(0.4026 * 0.85)


def test_build_company_reports_fcf_basis_overlay_caps_buy_when_note_mismatch_dnlm_style(
    tmp_path: Path,
):
    """Buy-tier names must downgrade to hold when FCF basis mismatch note would fire."""
    _dnlm_research_sources(tmp_path)
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="DNLM.L",
                name="Dunelm Group plc",
                sector="Consumer Cyclical",
                signal="buy",
                conviction_score=0.75,
                free_cashflow=171_000_000.0,
                free_cashflow_screen_ttm=163_900_000.0,
                fcf_basis_overlay=False,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "DNLM.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    snapshot = build_company_reports(signals, model_results, output_dir=tmp_path)[0].to_dict()

    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"
    assert "FCF basis mismatch" in snapshot["action_note"]
    assert "filing £211.4M" in snapshot["action_note"]
    assert "screen TTM £163.9M" in snapshot["action_note"]
    assert "company-adj £171M" in snapshot["action_note"]


def test_honour_fcf_action_note_enforcement_caps_hln_style_buy(tmp_path: Path):
    """Export helper must fire overlay when note mentions mismatch but flag is false."""
    sources = tmp_path / "research" / "HLN.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(
            {
                "cash_flow": {
                    "2025": {
                        "Operating Cash Flow": 2_634_000_000.0,
                        "Capital Expenditure": -413_000_000.0,
                        "Free Cash Flow": 2_221_000_000.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="HLN.L",
                name="Haleon plc",
                sector="Healthcare",
                signal="buy",
                conviction_score=0.8022,
                free_cashflow=2_221_000_000.0,
                free_cashflow_screen_ttm=1_801_800_000.0,
                fcf_basis_overlay=False,
                action_note=(
                    "Buy — neutral timing | FCF basis mismatch: filing £2221M | screen TTM £1801.8M"
                ),
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "HLN.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    assert report.fcf_basis_overlay is True
    assert report.adjusted_signal == "hold"

    stale = honour_fcf_action_note_enforcement(
        replace(
            report,
            fcf_basis_overlay=False,
            adjusted_signal="buy",
            conviction_score=0.8022,
        )
    )
    assert stale.fcf_basis_overlay is True
    assert stale.adjusted_signal == "hold"
    assert stale.conviction_score == pytest.approx(0.8022 * 0.85)


def test_honour_fcf_action_note_enforcement_caps_sbry_style_buy():
    """SBRY.L: buy with company-adj divergence note must cap even when overlay flag is stale."""
    note = (
        "Buy — neutral timing | FCF basis mismatch: filing £923M | screen TTM £821.9M | "
        "company-adj £574M | Research: Accumulate, Medium risk — margin compression overhang"
    )
    report = CompanyReport.from_dict(
        {
            "ticker": "SBRY.L",
            "name": "J Sainsbury plc",
            "sector": "Consumer Defensive",
            "signal": "buy",
            "adjusted_signal": "buy",
            "models_passed": 7,
            "model_count": 22,
            "composite_score": 0.5,
            "families_passed": 4,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 1,
            "signal_trend": "stable",
            "conviction_score": 0.5231,
            "stability_label": "building",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": {
                "filing_aligned": 923_000_000.0,
                "screen_ttm": 821_900_000.0,
                "company_adjusted": 574_000_000.0,
            },
            "summary": "Buy (7/22 models).",
            "passed_models": [],
            "key_metrics": {
                "free_cashflow": 821_900_000.0,
                "free_cashflow_screen_ttm": 821_900_000.0,
            },
        }
    )

    enforced = honour_fcf_action_note_enforcement(report)
    assert enforced.fcf_basis_overlay is True
    assert enforced.adjusted_signal == "hold"
    assert enforced.conviction_score == pytest.approx(0.5231 * 0.85)

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"
    assert snapshot["conviction_score"] == pytest.approx(0.5231 * 0.85)


def test_build_company_reports_fcf_basis_overlay_caps_sbry_style_buy(tmp_path: Path):
    """SBRY.L: filing/screen gap below 25% but company-adj universe divergence must cap buy."""
    filing = 923_000_000.0
    screen = 821_900_000.0
    sources = tmp_path / "research" / "SBRY.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(
            {
                "ticker": "SBRY.L",
                "cash_flow": {
                    "2026": {
                        "Operating Cash Flow": 1_100_000_000.0,
                        "Capital Expenditure": -177_000_000.0,
                        "Free Cash Flow": filing,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    filings = sources / "filings" / "bodies"
    filings.mkdir(parents=True)
    body_path = filings / "annual.txt"
    body_path.write_text("Retail free cash flow of £574m in the year", encoding="utf-8")
    (sources / "filings" / "filings_index.json").write_text(
        json.dumps({"filings": [{"body_path": str(body_path), "period": "annual"}]}),
        encoding="utf-8",
    )

    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="SBRY.L",
                name="J Sainsbury plc",
                sector="Consumer Defensive",
                signal="buy",
                conviction_score=0.5231,
                free_cashflow=screen,
                free_cashflow_screen_ttm=screen,
                fcf_basis_overlay=False,
                adjusted_signal="buy",
                action_note="Buy — neutral timing",
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "SBRY.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    snapshot = build_company_reports(signals, model_results, output_dir=tmp_path)[0].to_dict()

    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"
    assert "FCF basis mismatch" in snapshot["action_note"]
    assert "filing £923M" in snapshot["action_note"]
    assert "screen TTM £821.9M" in snapshot["action_note"]
    assert "company-adj £" in snapshot["action_note"]


def _srp_research_sources(tmp_path: Path) -> None:
    """SRP.L: filing/screen gap below 25% but company-adj universe divergence triggers overlay."""
    sources = tmp_path / "research" / "SRP.L" / "sources"
    filings = sources / "filings" / "bodies"
    filings.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(
            {
                "ticker": "SRP.L",
                "cash_flow": {
                    "2025": {
                        "Operating Cash Flow": 500_000_000.0,
                        "Capital Expenditure": -86_500_000.0,
                        "Free Cash Flow": 413_500_000.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (filings / "annual_results.txt").write_text(
        "Company-adjusted free cash flow of £219.0m after lease and working-capital adjustments",
        encoding="utf-8",
    )
    (sources / "filings" / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "period": "annual",
                        "has_body": True,
                        "body_path": str(filings / "annual_results.txt"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_build_company_reports_fcf_basis_overlay_caps_srp_style_buy(tmp_path: Path):
    """SRP.L: buy must downgrade to hold when company-adj FCF diverges below 25% filing gap."""
    _srp_research_sources(tmp_path)
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="SRP.L",
                name="Serco Group plc",
                sector="Industrials",
                signal="buy",
                conviction_score=0.557915,
                free_cashflow=413_500_000.0,
                free_cashflow_screen_ttm=361_200_000.0,
                fcf_basis_overlay=False,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "SRP.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    snapshot = build_company_reports(signals, model_results, output_dir=tmp_path)[0].to_dict()

    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"
    assert snapshot["conviction_score"] == pytest.approx(0.557915 * 0.85)
    assert "FCF basis mismatch" in snapshot["action_note"]
    assert "filing £413.5M" in snapshot["action_note"]
    assert "screen TTM £361.2M" in snapshot["action_note"]
    assert "company-adj £219M" in snapshot["action_note"]


def test_honour_fcf_action_note_enforcement_caps_srp_style_buy():
    """SRP.L: stale buy rows with FCF mismatch note must cap even when fcf=None."""
    note = (
        "Buy — neutral timing | FCF basis mismatch: filing £413.5M | screen TTM £361.2M | "
        "company-adj £219M | Earnings growth basis divergence >300 bps: statutory 244.8% vs "
        "filing core -41.8%"
    )
    report = CompanyReport.from_dict(
        {
            "ticker": "SRP.L",
            "name": "Serco Group plc",
            "sector": "Industrials",
            "signal": "buy",
            "adjusted_signal": "buy",
            "models_passed": 4,
            "model_count": 22,
            "composite_score": 0.6179,
            "families_passed": 4,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 9,
            "signal_trend": "stable",
            "conviction_score": 0.557915,
            "stability_label": "persistent",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Buy (4/22 models).",
            "passed_models": [],
            "key_metrics": {
                "free_cashflow": 361_200_000.0,
                "free_cashflow_screen_ttm": 361_200_000.0,
            },
        }
    )

    enforced = honour_fcf_action_note_enforcement(report)
    assert enforced.fcf_basis_overlay is True
    assert enforced.adjusted_signal == "hold"
    assert enforced.conviction_score == pytest.approx(0.557915 * 0.85)

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"


def test_export_enforced_report_dicts_honours_srp_style_stale_row():
    """SRP.L cached email_reports rows must not ship buy beside an FCF mismatch note."""
    from value_investor.summary import export_enforced_report_dicts

    stale = {
        "ticker": "SRP.L",
        "name": "Serco Group plc",
        "signal": "buy",
        "adjusted_signal": "buy",
        "fcf_basis_overlay": False,
        "conviction_score": 0.557915,
        "action_note": (
            "Buy — neutral timing | FCF basis mismatch: filing £413.5M | screen TTM £361.2M | "
            "company-adj £219M"
        ),
        "models_passed": 4,
        "model_count": 22,
        "composite_score": 0.6179,
        "families_passed": 4,
        "data_quality_score": 1.0,
        "metrics_present": 20,
        "metrics_total": 20,
        "weeks_at_signal": 9,
        "signal_trend": "stable",
        "stability_label": "persistent",
        "timing_signal": "neutral",
        "timing_score": 0.5,
        "summary": "Buy (4/22 models).",
        "passed_models": [],
        "key_metrics": {},
    }
    exported = export_enforced_report_dicts([stale])[0]
    assert exported["fcf_basis_overlay"] is True
    assert exported["adjusted_signal"] == "hold"
    assert exported["conviction_score"] == pytest.approx(0.557915 * 0.85)


def test_apply_research_overlay_with_fcf_enforcement_caps_mgns_style_strong_buy(
    tmp_path: Path,
):
    """Strong-buy names with stale overlay=false must cap when action note flags FCF mismatch."""
    from value_investor.research.document import ResearchDocument

    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="MGNS.L",
                name="Morgan Sindall Group plc",
                sector="Industrials",
                signal="strong_buy",
                conviction_score=0.811,
                free_cashflow=170_700_000.0,
                free_cashflow_screen_ttm=141_500_000.0,
                fcf_basis_overlay=False,
                adjusted_signal="strong_buy",
                action_note=(
                    "Strong Buy — neutral timing | FCF basis mismatch: filing £170.7M | "
                    "screen TTM £141.5M"
                ),
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "MGNS.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    assert report.fcf_basis_overlay is True
    assert report.adjusted_signal == "buy"

    stale = replace(
        report,
        fcf_basis_overlay=False,
        adjusted_signal="strong_buy",
        conviction_score=0.811,
    )
    doc = ResearchDocument(
        ticker="MGNS.L",
        name="Morgan Sindall Group plc",
        signal="strong_buy",
        version=1,
        created_at="2026-09-06T00:00:00+00:00",
        updated_at="2026-09-06T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="accumulate",
        research_risk_level="medium",
        research_confidence=0.7,
        research_path=str(tmp_path / "research" / "MGNS.L" / "research.md"),
    )

    overlaid = apply_research_overlay_with_fcf_enforcement([stale], [doc])[0]
    assert overlaid.fcf_basis_overlay is True
    assert overlaid.adjusted_signal == "buy"

    honoured = honour_fcf_action_note_enforcement(stale)
    assert honoured.fcf_basis_overlay is True
    assert honoured.adjusted_signal == "buy"
    assert honoured.conviction_score == pytest.approx(0.811 * 0.85)


def test_honour_fcf_action_note_enforcement_caps_imb_style_strong_buy():
    """IMB.L: strong_buy with FCF mismatch note but fcf=None must cap on export."""
    note = (
        "Strong Buy — neutral timing | FCF basis mismatch: filing £3166M | "
        "screen TTM £2502.4M | Earnings growth basis divergence >300 bps"
    )
    report = CompanyReport.from_dict(
        {
            "ticker": "IMB.L",
            "name": "Imperial Brands PLC",
            "sector": "Consumer Defensive",
            "signal": "strong_buy",
            "adjusted_signal": "strong_buy",
            "models_passed": 13,
            "model_count": 22,
            "composite_score": 0.75,
            "sector_composite_score": 0.7,
            "families_passed": 5,
            "passed_families": "cheapness,quality,garp,dividend,risk",
            "family_count": 5,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 9,
            "signal_trend": "stable",
            "conviction_score": 0.85,
            "stability_label": "persistent",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "rsi_14": 50.0,
            "price_vs_sma200_pct": 0.0,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Strong Buy (13/22 models).",
            "passed_models": [],
            "key_metrics": {
                "free_cashflow": 2_502_400_000.0,
                "free_cashflow_screen_ttm": 2_502_400_000.0,
            },
        }
    )

    enforced = honour_fcf_action_note_enforcement(report)
    assert enforced.fcf_basis_overlay is True
    assert enforced.adjusted_signal == "buy"
    assert enforced.conviction_score == pytest.approx(0.85 * 0.85)

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert snapshot["conviction_score"] == pytest.approx(0.85 * 0.85)


def test_honour_fcf_action_note_enforcement_caps_mony_style_strong_buy():
    """MONY.L: below-25% filing gap but FCF mismatch note must cap strong_buy on export."""
    note = (
        "Strong Buy — neutral timing | FCF basis mismatch: filing £98.1M | "
        "screen TTM £80M | Research: Accumulate, Medium risk"
    )
    report = CompanyReport.from_dict(
        {
            "ticker": "MONY.L",
            "name": "MONY Group plc",
            "sector": "Communication Services",
            "signal": "strong_buy",
            "adjusted_signal": "strong_buy",
            "models_passed": 15,
            "model_count": 22,
            "composite_score": 0.7072,
            "families_passed": 5,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 2,
            "signal_trend": "stable",
            "conviction_score": 0.5388,
            "stability_label": "building",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Strong Buy (15/22 models).",
            "passed_models": [],
            "key_metrics": {
                "free_cashflow": 80_000_000.0,
                "free_cashflow_screen_ttm": 80_000_000.0,
            },
        }
    )

    enforced = honour_fcf_action_note_enforcement(report)
    assert enforced.fcf_basis_overlay is True
    assert enforced.adjusted_signal == "buy"
    assert enforced.conviction_score == pytest.approx(0.5388 * 0.85)

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert snapshot["conviction_score"] == pytest.approx(0.5388 * 0.85)


def test_honour_fcf_action_note_enforcement_caps_rs1_style_buy():
    """RS1.L: buy-tier note below 25% filing gap must cap to hold when fcf is absent."""
    note = (
        "Buy — wait for pullback | FCF basis mismatch: filing £210.9M | screen TTM £168M | "
        "FCF definition divergence: statutory 1.99× vs management 2.81× dividend coverage | "
        "Earnings growth basis divergence >300 bps: statutory 6.5% vs filing core -3.2%"
    )
    report = CompanyReport.from_dict(
        {
            "ticker": "RS1.L",
            "name": "RS Group plc",
            "sector": "Industrials",
            "signal": "buy",
            "adjusted_signal": "buy",
            "models_passed": 11,
            "model_count": 22,
            "composite_score": 0.5,
            "families_passed": 5,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 1,
            "signal_trend": "stable",
            "conviction_score": 0.51238,
            "stability_label": "building",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Buy (11/22 models).",
            "passed_models": [],
            "key_metrics": {},
        }
    )

    enforced = honour_fcf_action_note_enforcement(report)
    assert enforced.fcf_basis_overlay is True
    assert enforced.adjusted_signal == "hold"
    assert enforced.conviction_score == pytest.approx(0.51238 * 0.85)

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"


def test_apply_research_overlay_with_fcf_enforcement_caps_rs1_style_buy():
    """Research overlay must not restore buy when FCF mismatch note is present."""
    from value_investor.research.document import ResearchDocument

    note = (
        "Buy — wait for pullback | FCF basis mismatch: filing £210.9M | screen TTM £168M | "
        "FCF definition divergence: statutory 1.99× vs management 2.81× dividend coverage"
    )
    stale = CompanyReport.from_dict(
        {
            "ticker": "RS1.L",
            "name": "RS Group plc",
            "sector": "Industrials",
            "signal": "buy",
            "adjusted_signal": "buy",
            "models_passed": 11,
            "model_count": 22,
            "composite_score": 0.5,
            "families_passed": 5,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 1,
            "signal_trend": "stable",
            "conviction_score": 0.51238,
            "stability_label": "building",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Buy (11/22 models).",
            "passed_models": [],
            "key_metrics": {},
        }
    )
    doc = ResearchDocument(
        ticker="RS1.L",
        name="RS Group plc",
        signal="buy",
        version=2,
        created_at="2026-09-06T00:00:00+00:00",
        updated_at="2026-09-06T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="accumulate",
        research_risk_level="medium",
        research_confidence=0.7,
        research_rationale="Measured accumulation.",
        research_path="docs/research/RS1.L.md",
    )

    overlaid = apply_research_overlay_with_fcf_enforcement([stale], [doc])[0]
    assert overlaid.fcf_basis_overlay is True
    assert overlaid.adjusted_signal == "hold"
    # Research overlay adjusts conviction first; FCF cap applies to that post-research score.
    assert overlaid.conviction_score == pytest.approx(0.56238 * 0.85)


def test_export_enforced_report_dicts_honours_mony_style_stale_row():
    """Cached email_reports rows must not ship strong_buy beside an FCF mismatch note."""
    from value_investor.summary import export_enforced_report_dicts

    stale = {
        "ticker": "MONY.L",
        "name": "MONY Group plc",
        "signal": "strong_buy",
        "adjusted_signal": "strong_buy",
        "fcf_basis_overlay": False,
        "conviction_score": 0.5388,
        "action_note": (
            "Strong Buy — neutral timing | FCF basis mismatch: filing £98.1M | screen TTM £80M"
        ),
        "models_passed": 15,
        "model_count": 22,
        "composite_score": 0.7072,
        "families_passed": 5,
        "data_quality_score": 1.0,
        "metrics_present": 20,
        "metrics_total": 20,
        "weeks_at_signal": 2,
        "signal_trend": "stable",
        "stability_label": "building",
        "timing_signal": "neutral",
        "timing_score": 0.5,
        "summary": "Strong Buy (15/22 models).",
        "passed_models": [],
        "key_metrics": {},
    }
    exported = export_enforced_report_dicts([stale])[0]
    assert exported["fcf_basis_overlay"] is True
    assert exported["adjusted_signal"] == "buy"
    assert exported["conviction_score"] == pytest.approx(0.5388 * 0.85)


def test_export_enforced_report_dicts_honours_rs1_style_stale_row():
    """RS1.L-style cached rows must not ship buy beside an FCF mismatch note."""
    from value_investor.summary import export_enforced_report_dicts

    stale = {
        "ticker": "RS1.L",
        "name": "RS Group plc",
        "signal": "buy",
        "adjusted_signal": "buy",
        "fcf_basis_overlay": False,
        "conviction_score": 0.51238,
        "action_note": (
            "Buy — wait for pullback | FCF basis mismatch: filing £210.9M | "
            "screen TTM £168M | FCF definition divergence: statutory 1.99× vs "
            "management 2.81× dividend coverage"
        ),
        "models_passed": 11,
        "model_count": 22,
        "composite_score": 0.5,
        "families_passed": 5,
        "data_quality_score": 1.0,
        "metrics_present": 20,
        "metrics_total": 20,
        "weeks_at_signal": 1,
        "signal_trend": "stable",
        "stability_label": "building",
        "timing_signal": "neutral",
        "timing_score": 0.5,
        "summary": "Buy (11/22 models).",
        "passed_models": [],
        "key_metrics": {},
    }
    exported = export_enforced_report_dicts([stale])[0]
    assert exported["fcf_basis_overlay"] is True
    assert exported["adjusted_signal"] == "hold"
    assert exported["conviction_score"] == pytest.approx(0.51238 * 0.85)


def _wix_style_action_note() -> str:
    return (
        "Buy — neutral timing | FCF basis mismatch: filing £168.7M | screen TTM £133.9M | "
        "Earnings growth basis divergence >300 bps: statutory 118.2% vs filing core 99.8%"
    )


def test_honour_fcf_action_note_enforcement_caps_wix_style_buy():
    """WIX.L: buy-tier note below 25% filing gap must cap to hold when fcf is absent."""
    report = CompanyReport.from_dict(
        {
            "ticker": "WIX.L",
            "name": "Wickes Group plc",
            "sector": "Consumer Cyclical",
            "signal": "buy",
            "adjusted_signal": "buy",
            "models_passed": 11,
            "model_count": 22,
            "composite_score": 0.6802,
            "families_passed": 5,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 13,
            "signal_trend": "stable",
            "conviction_score": 0.8304,
            "stability_label": "persistent",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": _wix_style_action_note(),
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Buy (11/22 models).",
            "passed_models": [],
            "key_metrics": {},
        }
    )

    enforced = honour_fcf_action_note_enforcement(report)
    assert enforced.fcf_basis_overlay is True
    assert enforced.adjusted_signal == "hold"
    assert enforced.conviction_score == pytest.approx(0.8304 * 0.85)


def test_apply_research_overlay_with_fcf_enforcement_caps_wix_style_buy():
    """Research accumulate must not restore buy when WIX-style FCF mismatch note is present."""
    from value_investor.research.document import ResearchDocument

    stale = CompanyReport.from_dict(
        {
            "ticker": "WIX.L",
            "name": "Wickes Group plc",
            "sector": "Consumer Cyclical",
            "signal": "buy",
            "adjusted_signal": "buy",
            "models_passed": 11,
            "model_count": 22,
            "composite_score": 0.6802,
            "families_passed": 5,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 13,
            "signal_trend": "stable",
            "conviction_score": 0.8304,
            "stability_label": "persistent",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": _wix_style_action_note(),
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Buy (11/22 models).",
            "passed_models": [],
            "key_metrics": {},
        }
    )
    doc = ResearchDocument(
        ticker="WIX.L",
        name="Wickes Group plc",
        signal="buy",
        version=2,
        created_at="2026-09-06T00:00:00+00:00",
        updated_at="2026-09-06T00:00:00+00:00",
        mode="initial",
        research_verdict="accumulate",
        research_risk_level="medium",
        research_confidence=0.7,
        research_rationale="Measured sizing rather than full conviction.",
        research_path="docs/research/WIX.L.md",
    )

    overlaid = apply_research_overlay_with_fcf_enforcement([stale], [doc])[0]
    assert overlaid.fcf_basis_overlay is True
    assert overlaid.adjusted_signal == "hold"


def test_export_enforced_report_dicts_honours_wix_style_stale_row():
    """WIX.L-style cached rows must not ship buy beside an FCF mismatch note."""
    from value_investor.summary import export_enforced_report_dicts

    stale = {
        "ticker": "WIX.L",
        "name": "Wickes Group plc",
        "signal": "buy",
        "adjusted_signal": "buy",
        "fcf_basis_overlay": False,
        "conviction_score": 0.8304,
        "action_note": _wix_style_action_note(),
        "models_passed": 11,
        "model_count": 22,
        "composite_score": 0.6802,
        "families_passed": 5,
        "data_quality_score": 1.0,
        "metrics_present": 20,
        "metrics_total": 20,
        "weeks_at_signal": 13,
        "signal_trend": "stable",
        "stability_label": "persistent",
        "timing_signal": "neutral",
        "timing_score": 0.5,
        "summary": "Buy (11/22 models).",
        "passed_models": [],
        "key_metrics": {},
    }
    exported = export_enforced_report_dicts([stale])[0]
    assert exported["fcf_basis_overlay"] is True
    assert exported["adjusted_signal"] == "hold"
    assert exported["conviction_score"] == pytest.approx(0.8304 * 0.85)


def test_build_company_reports_fcf_basis_overlay_caps_wix_style_buy(tmp_path: Path):
    """WIX.L-style 21% universe gap must cap buy-tier signals when FCF note would fire."""
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="WIX.L",
                name="Wickes Group plc",
                sector="Consumer Cyclical",
                signal="buy",
                conviction_score=0.8304,
                free_cashflow=168_700_000.0,
                free_cashflow_screen_ttm=133_900_000.0,
                fcf_basis_overlay=False,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "WIX.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    snapshot = build_company_reports(signals, model_results, output_dir=tmp_path)[0].to_dict()

    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"
    assert snapshot["conviction_score"] == pytest.approx(0.8304 * 0.85)
    assert "FCF basis mismatch" in snapshot["action_note"]
    assert "filing £168.7M" in snapshot["action_note"]
    assert "screen TTM £133.9M" in snapshot["action_note"]


def test_build_company_reports_exports_fcf_basis_overlay_for_mony_style_note(
    tmp_path: Path,
):
    """Universe-level 15% gap must cap buy-tier signals when FCF note would fire."""
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="MONY.L",
                name="MONY Group plc",
                sector="Communication Services",
                signal="strong_buy",
                conviction_score=0.5388,
                free_cashflow=80_000_000.0,
                free_cashflow_screen_ttm=80_000_000.0,
                fcf_basis_overlay=False,
                adjusted_signal="strong_buy",
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "MONY.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )
    sources = tmp_path / "research" / "MONY.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(
            {
                "ticker": "MONY.L",
                "cash_flow": {
                    "2026": {
                        "Operating Cash Flow": 110_000_000.0,
                        "Capital Expenditure": -11_900_000.0,
                        "Free Cash Flow": 98_100_000.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    snapshot = report.to_dict()

    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert snapshot["conviction_score"] == pytest.approx(0.5388 * 0.85)
    assert "FCF basis mismatch" in snapshot["action_note"]
    assert "filing £98.1M" in snapshot["action_note"]
    assert "screen TTM £80M" in snapshot["action_note"]


def test_company_report_to_dict_honours_fcf_note_after_research_overlay():
    """Publish/email JSON export must not leave strong_buy beside an FCF mismatch note."""
    note = "Strong Buy — neutral timing | FCF basis mismatch: filing £3166M | screen TTM £2502.4M"
    report = CompanyReport.from_dict(
        {
            "ticker": "IMB.L",
            "name": "Imperial Brands PLC",
            "sector": "Consumer Defensive",
            "signal": "strong_buy",
            "adjusted_signal": "strong_buy",
            "models_passed": 13,
            "model_count": 22,
            "composite_score": 0.75,
            "families_passed": 5,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 9,
            "signal_trend": "stable",
            "conviction_score": 0.85,
            "stability_label": "persistent",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Strong Buy (13/22 models).",
            "passed_models": [],
            "key_metrics": {},
        }
    )
    stale = replace(
        report,
        fcf_basis_overlay=False,
        adjusted_signal="strong_buy",
        conviction_score=0.85,
        action_note=f"{note} | Research: Accumulate, Medium risk",
    )

    snapshot = stale.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert snapshot["conviction_score"] == pytest.approx(0.85 * 0.85)


def _rio_fcf_mismatch_note() -> str:
    return (
        "Strong Buy — neutral timing | FCF basis mismatch: filing £4497M | "
        "screen TTM £3595.5M | Earnings growth basis divergence >300 bps: "
        "statutory -13.8% vs filing core -8.2%"
    )


def test_fcf_basis_overlay_honours_action_note_predicate_rio_style_gap():
    """RIO.L-style gap: ~20% filing/screen divergence below 25% but above 15%."""
    filing = 4_497_000_000.0
    screen = 3_595_500_000.0
    assert fcf_universe_divergence_flagged(
        filing_aligned=filing,
        screen_ttm=screen,
        company_adjusted=None,
        filing_currency="GBP",
    )
    assert not fcf_filing_screen_mismatch(
        filing_aligned=filing,
        screen_ttm=screen,
        divergence_flagged=False,
    )
    assert fcf_action_note_mismatch(
        filing_aligned=filing,
        screen_ttm=screen,
        filing_currency="GBP",
    )


def test_honour_fcf_action_note_enforcement_caps_rio_style_strong_buy():
    """RIO.L: strong_buy with FCF mismatch note but fcf=None must cap on export."""
    note = _rio_fcf_mismatch_note()
    report = CompanyReport.from_dict(
        {
            "ticker": "RIO.L",
            "name": "Rio Tinto Group",
            "sector": "Basic Materials",
            "signal": "strong_buy",
            "adjusted_signal": "strong_buy",
            "models_passed": 11,
            "model_count": 22,
            "composite_score": 0.6792,
            "sector_composite_score": 0.7247,
            "families_passed": 5,
            "passed_families": "cheapness,quality,dividend,garp,risk",
            "family_count": 5,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 2,
            "signal_trend": "stable",
            "conviction_score": 0.6765,
            "stability_label": "building",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "rsi_14": 60.4,
            "price_vs_sma200_pct": 0.1,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Strong Buy (11/22 models).",
            "passed_models": [],
            "key_metrics": {
                "P/E": "14.0",
                "P/B": "2.6",
                "Yield": "4.6%",
                "ROE": "19.3%",
                "FCF": "4497000000.0",
            },
        }
    )

    enforced = honour_fcf_action_note_enforcement(report)
    assert enforced.fcf_basis_overlay is True
    assert enforced.adjusted_signal == "buy"
    assert enforced.conviction_score == pytest.approx(0.6765 * 0.85)

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert snapshot["conviction_score"] == pytest.approx(0.6765 * 0.85)


def test_build_company_reports_exports_fcf_basis_overlay_for_rio(tmp_path: Path):
    """RIO.L-style: universe divergence at 20% caps strong_buy despite sub-25% filing gap."""
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="RIO.L",
                name="Rio Tinto Group",
                sector="Basic Materials",
                signal="strong_buy",
                conviction_score=0.6765,
                free_cashflow=4_497_000_000.0,
                free_cashflow_screen_ttm=3_595_500_000.0,
                fcf_basis_overlay=False,
                adjusted_signal="strong_buy",
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "RIO.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    assert report.fcf_basis_overlay is True
    assert report.adjusted_signal == "buy"
    assert "FCF basis mismatch" in report.action_note

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"


def _sn_fcf_mismatch_note() -> str:
    return (
        "Strong Buy — neutral timing | FCF basis mismatch: filing £852M | "
        "screen TTM £1059M | Earnings growth basis divergence >300 bps: "
        "statutory 52.8% vs filing core 16.5%"
    )


def test_fcf_basis_overlay_honours_action_note_predicate_sn_style_gap():
    """SN.L-style gap: ~24% filing/screen divergence below 25% but above 15%."""
    filing = 852_000_000.0
    screen = 1_059_000_000.0
    assert fcf_universe_divergence_flagged(
        filing_aligned=filing,
        screen_ttm=screen,
        company_adjusted=None,
        filing_currency="GBP",
    )
    assert not fcf_filing_screen_mismatch(
        filing_aligned=filing,
        screen_ttm=screen,
        divergence_flagged=False,
    )
    note = _sn_fcf_mismatch_note()
    assert parse_filing_aligned_from_action_note(note) == pytest.approx(filing)
    assert parse_screen_ttm_from_action_note(note) == pytest.approx(screen)


def test_honour_fcf_action_note_enforcement_caps_sn_style_strong_buy():
    """SN.L: strong_buy with FCF mismatch note but fcf=None must cap on export."""
    note = _sn_fcf_mismatch_note()
    report = CompanyReport.from_dict(
        {
            "ticker": "SN.L",
            "name": "Smith & Nephew plc",
            "sector": "Healthcare",
            "signal": "strong_buy",
            "adjusted_signal": "strong_buy",
            "models_passed": 8,
            "model_count": 22,
            "composite_score": 0.65,
            "families_passed": 4,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 3,
            "signal_trend": "stable",
            "conviction_score": 0.7012,
            "stability_label": "building",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Strong Buy (8/22 models).",
            "passed_models": [],
            "key_metrics": {"FCF": "852000000.0"},
        }
    )

    enforced = honour_fcf_action_note_enforcement(report)
    assert enforced.fcf_basis_overlay is True
    assert enforced.adjusted_signal == "buy"
    assert enforced.conviction_score == pytest.approx(0.7012 * 0.85)

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert snapshot["conviction_score"] == pytest.approx(0.7012 * 0.85)


def test_build_company_reports_exports_fcf_basis_overlay_for_sn(tmp_path: Path):
    """SN.L-style: universe divergence at ~24% caps strong_buy despite sub-25% filing gap."""
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="SN.L",
                name="Smith & Nephew plc",
                sector="Healthcare",
                signal="strong_buy",
                conviction_score=0.7012,
                free_cashflow=852_000_000.0,
                free_cashflow_screen_ttm=1_059_000_000.0,
                fcf_basis_overlay=False,
                adjusted_signal="strong_buy",
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "SN.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    assert report.fcf_basis_overlay is True
    assert report.adjusted_signal == "buy"
    assert "FCF basis mismatch" in report.action_note

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"


def _trn_fcf_mismatch_note() -> str:
    return (
        "Buy — favourable entry timing | FCF basis mismatch: filing £79.5M | "
        "screen TTM £62.5M | Earnings growth basis divergence >300 bps: "
        "statutory 48.4% vs filing core 36.8%"
    )


def test_fcf_basis_overlay_honours_action_note_predicate_trn_style_gap():
    """TRN.L-style gap: ~21% filing/screen divergence below 25% but above 15%."""
    filing = 79_500_000.0
    screen = 62_500_000.0
    assert fcf_universe_divergence_flagged(
        filing_aligned=filing,
        screen_ttm=screen,
        company_adjusted=None,
        filing_currency="GBP",
    )
    assert not fcf_filing_screen_mismatch(
        filing_aligned=filing,
        screen_ttm=screen,
        divergence_flagged=False,
    )
    note = _trn_fcf_mismatch_note()
    assert parse_filing_aligned_from_action_note(note) == pytest.approx(filing)
    assert parse_screen_ttm_from_action_note(note) == pytest.approx(screen)


def test_honour_fcf_action_note_enforcement_caps_trn_style_buy():
    """TRN.L: buy with FCF mismatch note but fcf=None must cap on export."""
    note = _trn_fcf_mismatch_note()
    report = CompanyReport.from_dict(
        {
            "ticker": "TRN.L",
            "name": "Trainline plc",
            "sector": "Technology",
            "signal": "buy",
            "adjusted_signal": "buy",
            "models_passed": 5,
            "model_count": 22,
            "composite_score": 0.5,
            "families_passed": 3,
            "data_quality_score": 0.95,
            "metrics_present": 18,
            "metrics_total": 20,
            "weeks_at_signal": 1,
            "signal_trend": "stable",
            "conviction_score": 0.5005,
            "stability_label": "building",
            "timing_signal": "favourable",
            "timing_score": 0.7,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Buy (5/22 models).",
            "passed_models": [],
            "key_metrics": {},
        }
    )

    enforced = honour_fcf_action_note_enforcement(report)
    assert enforced.fcf_basis_overlay is True
    assert enforced.adjusted_signal == "hold"
    assert enforced.conviction_score == pytest.approx(0.5005 * 0.85)

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"
    assert snapshot["conviction_score"] == pytest.approx(0.5005 * 0.85)


def test_build_company_reports_exports_fcf_basis_overlay_for_trn(tmp_path: Path):
    """TRN.L-style: universe divergence at ~21% caps buy despite sub-25% filing gap."""
    sources = tmp_path / "research" / "TRN.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(
            {
                "ticker": "TRN.L",
                "cash_flow": {
                    "2026": {
                        "Operating Cash Flow": 133_000_000.0,
                        "Capital Expenditure": -53_500_000.0,
                        "Free Cash Flow": 79_500_000.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="TRN.L",
                name="Trainline plc",
                sector="Technology",
                signal="buy",
                conviction_score=0.5005,
                timing_signal="favourable",
                action_note="Buy — favourable entry timing",
                free_cashflow=79_500_000.0,
                free_cashflow_screen_ttm=62_500_000.0,
                fcf_basis_overlay=False,
                adjusted_eps_growth_pct=36.8,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "TRN.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    snapshot = report.to_dict()

    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"
    assert snapshot["conviction_score"] == pytest.approx(0.5005 * 0.85)
    assert "FCF basis mismatch" in snapshot["action_note"]
    assert "filing £79.5M" in snapshot["action_note"]
    assert "screen TTM £62.5M" in snapshot["action_note"]


def test_export_enforced_report_dicts_honours_trn_style_stale_row():
    """TRN.L cached email_reports rows must not ship buy beside an FCF mismatch note."""
    from value_investor.summary import export_enforced_report_dicts

    stale = {
        "ticker": "TRN.L",
        "name": "Trainline plc",
        "signal": "buy",
        "adjusted_signal": "buy",
        "fcf_basis_overlay": False,
        "conviction_score": 0.5005,
        "action_note": _trn_fcf_mismatch_note(),
        "models_passed": 5,
        "model_count": 22,
        "composite_score": 0.5,
        "families_passed": 3,
        "data_quality_score": 0.95,
        "metrics_present": 18,
        "metrics_total": 20,
        "weeks_at_signal": 1,
        "signal_trend": "stable",
        "stability_label": "building",
        "timing_signal": "favourable",
        "timing_score": 0.7,
        "summary": "Buy (5/22 models).",
        "passed_models": [],
        "key_metrics": {},
    }
    exported = export_enforced_report_dicts([stale])[0]
    assert exported["fcf_basis_overlay"] is True
    assert exported["adjusted_signal"] == "hold"
    assert exported["conviction_score"] == pytest.approx(0.5005 * 0.85)


def test_apply_research_overlay_with_fcf_enforcement_caps_trn_style_buy():
    """TRN.L: stale overlay=false must not leave buy beside FCF mismatch note."""
    from value_investor.research.document import ResearchDocument

    note = _trn_fcf_mismatch_note()
    stale = CompanyReport.from_dict(
        {
            "ticker": "TRN.L",
            "name": "Trainline plc",
            "sector": "Technology",
            "signal": "buy",
            "adjusted_signal": "buy",
            "models_passed": 5,
            "model_count": 22,
            "composite_score": 0.5,
            "families_passed": 3,
            "data_quality_score": 0.95,
            "metrics_present": 18,
            "metrics_total": 20,
            "weeks_at_signal": 1,
            "signal_trend": "stable",
            "conviction_score": 0.5005,
            "stability_label": "building",
            "timing_signal": "favourable",
            "timing_score": 0.7,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Buy (5/22 models).",
            "passed_models": [],
            "key_metrics": {},
        }
    )
    doc = ResearchDocument(
        ticker="TRN.L",
        name="Trainline plc",
        signal="buy",
        version=1,
        created_at="2026-09-06T00:00:00+00:00",
        updated_at="2026-09-06T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="accumulate",
        research_risk_level="medium",
        research_confidence=0.7,
        research_rationale="Regulatory clarity still pending.",
    )

    overlaid = apply_research_overlay_with_fcf_enforcement([stale], [doc])[0]
    assert overlaid.fcf_basis_overlay is True
    assert overlaid.adjusted_signal == "hold"


def _vty_fcf_mismatch_note() -> str:
    return (
        "Strong Buy — neutral timing | FCF basis mismatch: filing £174.6M | "
        "screen TTM £147.4M | Earnings growth basis divergence >300 bps: "
        "statutory 91.8% vs filing core 85.2%"
    )


def test_fcf_basis_overlay_honours_action_note_predicate_vty_style_gap():
    """VTY.L-style gap: ~16% filing/screen divergence below 25% but above 15%."""
    filing = 174_600_000.0
    screen = 147_400_000.0
    assert fcf_universe_divergence_flagged(
        filing_aligned=filing,
        screen_ttm=screen,
        company_adjusted=None,
        filing_currency="GBP",
    )
    assert not fcf_filing_screen_mismatch(
        filing_aligned=filing,
        screen_ttm=screen,
        divergence_flagged=False,
    )
    note = _vty_fcf_mismatch_note()
    assert parse_filing_aligned_from_action_note(note) == pytest.approx(filing)
    assert parse_screen_ttm_from_action_note(note) == pytest.approx(screen)
    assert fcf_action_note_mismatch(
        filing_aligned=filing,
        screen_ttm=screen,
        filing_currency="GBP",
    )


def test_honour_fcf_action_note_enforcement_caps_vty_style_strong_buy():
    """VTY.L: strong_buy with FCF mismatch note but fcf=None must cap on export."""
    note = _vty_fcf_mismatch_note()
    report = CompanyReport.from_dict(
        {
            "ticker": "VTY.L",
            "name": "Vistry Group PLC",
            "sector": "Consumer Cyclical",
            "signal": "strong_buy",
            "adjusted_signal": "strong_buy",
            "models_passed": 11,
            "model_count": 22,
            "composite_score": 0.6598,
            "sector_composite_score": 0.7247,
            "families_passed": 4,
            "passed_families": "cheapness,quality,dividend,risk",
            "family_count": 5,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 2,
            "signal_trend": "stable",
            "conviction_score": 0.6598,
            "stability_label": "building",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "rsi_14": 50.0,
            "price_vs_sma200_pct": 0.0,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Strong Buy (11/22 models).",
            "passed_models": [],
            "key_metrics": {},
        }
    )

    enforced = honour_fcf_action_note_enforcement(report)
    assert enforced.fcf_basis_overlay is True
    assert enforced.adjusted_signal == "buy"
    assert enforced.conviction_score == pytest.approx(0.6598 * 0.85)

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert snapshot["conviction_score"] == pytest.approx(0.6598 * 0.85)


def test_build_company_reports_exports_fcf_basis_overlay_for_vty(tmp_path: Path):
    """VTY.L-style: universe divergence at 16% caps strong_buy despite sub-25% filing gap."""
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="VTY.L",
                name="Vistry Group PLC",
                sector="Consumer Cyclical",
                signal="strong_buy",
                conviction_score=0.6598,
                free_cashflow=174_600_000.0,
                free_cashflow_screen_ttm=147_400_000.0,
                fcf_basis_overlay=False,
                adjusted_signal="strong_buy",
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "VTY.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    assert report.fcf_basis_overlay is True
    assert report.adjusted_signal == "buy"
    assert "FCF basis mismatch" in report.action_note

    snapshot = report.to_dict()
    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"


def test_export_enforced_report_dicts_honours_vty_style_stale_row():
    """VTY.L cached email_reports rows must not ship strong_buy beside an FCF mismatch note."""
    from value_investor.summary import export_enforced_report_dicts

    stale = {
        "ticker": "VTY.L",
        "name": "Vistry Group PLC",
        "signal": "strong_buy",
        "adjusted_signal": "strong_buy",
        "fcf_basis_overlay": False,
        "conviction_score": 0.6598,
        "action_note": _vty_fcf_mismatch_note(),
        "models_passed": 11,
        "model_count": 22,
        "composite_score": 0.6598,
        "families_passed": 4,
        "data_quality_score": 1.0,
        "metrics_present": 20,
        "metrics_total": 20,
        "weeks_at_signal": 2,
        "signal_trend": "stable",
        "stability_label": "building",
        "timing_signal": "neutral",
        "timing_score": 0.5,
        "summary": "Strong Buy (11/22 models).",
        "passed_models": [],
        "key_metrics": {},
    }
    exported = export_enforced_report_dicts([stale])[0]
    assert exported["fcf_basis_overlay"] is True
    assert exported["adjusted_signal"] == "buy"
    assert exported["conviction_score"] == pytest.approx(0.6598 * 0.85)


def test_apply_research_overlay_with_fcf_enforcement_caps_vty_style_strong_buy():
    """VTY.L: stale overlay=false must not leave strong_buy beside FCF mismatch note."""
    from value_investor.research.document import ResearchDocument

    note = _vty_fcf_mismatch_note()
    stale = CompanyReport.from_dict(
        {
            "ticker": "VTY.L",
            "name": "Vistry Group PLC",
            "sector": "Consumer Cyclical",
            "signal": "strong_buy",
            "adjusted_signal": "strong_buy",
            "models_passed": 11,
            "model_count": 22,
            "composite_score": 0.6598,
            "families_passed": 4,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 2,
            "signal_trend": "stable",
            "conviction_score": 0.6598,
            "stability_label": "building",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Strong Buy (11/22 models).",
            "passed_models": [],
            "key_metrics": {},
        }
    )
    doc = ResearchDocument(
        ticker="VTY.L",
        name="Vistry Group PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-09-06T00:00:00+00:00",
        updated_at="2026-09-06T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="accumulate",
        research_risk_level="high",
        research_confidence=0.7,
        research_rationale="Deep research moderates the Strong Buy on near-term earnings quality.",
    )

    overlaid = apply_research_overlay_with_fcf_enforcement([stale], [doc])[0]
    assert overlaid.fcf_basis_overlay is True
    assert overlaid.adjusted_signal == "buy"


def test_apply_research_overlay_with_fcf_enforcement_caps_sn_style_strong_buy(
    tmp_path: Path,
):
    """SN.L: stale overlay=false must not leave strong_buy beside FCF mismatch note."""
    from value_investor.research.document import ResearchDocument

    note = _sn_fcf_mismatch_note()
    stale = CompanyReport.from_dict(
        {
            "ticker": "SN.L",
            "name": "Smith & Nephew plc",
            "sector": "Healthcare",
            "signal": "strong_buy",
            "adjusted_signal": "strong_buy",
            "models_passed": 8,
            "model_count": 22,
            "composite_score": 0.65,
            "families_passed": 4,
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 3,
            "signal_trend": "stable",
            "conviction_score": 0.7012,
            "stability_label": "building",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": note,
            "fcf_basis_overlay": False,
            "fcf": None,
            "summary": "Strong Buy (8/22 models).",
            "passed_models": [],
            "key_metrics": {"FCF": "852000000.0"},
        }
    )
    doc = ResearchDocument(
        ticker="SN.L",
        name="Smith & Nephew plc",
        signal="strong_buy",
        version=2,
        created_at="2026-09-06T00:00:00+00:00",
        updated_at="2026-09-06T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="accumulate",
        research_risk_level="medium",
        research_confidence=0.7,
        research_rationale="Phased conviction warranted.",
    )

    overlaid = apply_research_overlay_with_fcf_enforcement([stale], [doc])[0]
    assert overlaid.fcf_basis_overlay is True
    assert overlaid.adjusted_signal == "buy"


def test_apply_research_overlay_with_fcf_enforcement_caps_rio_style_strong_buy(
    tmp_path: Path,
):
    """RIO.L: stale overlay=false must not leave strong_buy beside FCF mismatch note."""
    from value_investor.research.document import ResearchDocument

    note = _rio_fcf_mismatch_note()
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="RIO.L",
                name="Rio Tinto Group",
                sector="Basic Materials",
                signal="strong_buy",
                conviction_score=0.6765,
                free_cashflow=4_497_000_000.0,
                free_cashflow_screen_ttm=3_595_500_000.0,
                fcf_basis_overlay=False,
                adjusted_signal="strong_buy",
                action_note=note,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "RIO.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    report = build_company_reports(signals, model_results, output_dir=tmp_path)[0]
    stale = replace(
        report,
        fcf_basis_overlay=False,
        adjusted_signal="strong_buy",
        conviction_score=0.6765,
    )
    doc = ResearchDocument(
        ticker="RIO.L",
        name="Rio Tinto Group",
        signal="strong_buy",
        version=1,
        created_at="2026-09-06T00:00:00+00:00",
        updated_at="2026-09-06T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="accumulate",
        research_risk_level="medium",
        research_confidence=0.7,
        research_path=str(tmp_path / "research" / "RIO.L" / "research.md"),
    )

    overlaid = apply_research_overlay_with_fcf_enforcement([stale], [doc])[0]
    assert overlaid.fcf_basis_overlay is True
    assert overlaid.adjusted_signal == "buy"
    assert overlaid.to_dict()["adjusted_signal"] == "buy"


def _gfrd_financials() -> dict:
    return {
        "ticker": "GFRD.L",
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 65_700_000.0,
                "Capital Expenditure": -2_400_000.0,
                "Free Cash Flow": 63_300_000.0,
            }
        },
    }


def test_build_company_reports_exports_fcf_basis_overlay_for_gfrd_stale_note(
    tmp_path: Path,
):
    """GFRD.L-style: mismatch note persists after free_cashflow_screen_ttm is lost."""
    sources = tmp_path / "research" / "GFRD.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(_gfrd_financials()), encoding="utf-8"
    )

    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="GFRD.L",
                name="Galliford Try Holdings plc",
                sector="Industrials",
                signal="buy",
                conviction_score=0.7912,
                free_cashflow=63_300_000.0,
                fcf_basis_overlay=False,
                adjusted_signal="buy",
                fcf_divergence_flagged=False,
                action_note=(
                    "Buy — neutral timing | FCF basis mismatch: filing £63.3M | screen TTM £50.0M"
                ),
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "GFRD.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    reports = build_company_reports(signals, model_results, output_dir=tmp_path)
    snapshot = reports[0].to_dict()

    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"
    assert snapshot["conviction_score"] == pytest.approx(0.7912 * 0.85)
    assert "FCF basis mismatch" in snapshot["action_note"]
    assert "screen TTM £50" in snapshot["action_note"]


def test_build_company_reports_reapplies_fcf_overlay_when_flag_true_but_buy_remains(
    tmp_path: Path,
):
    """Persisted overlay=true must not skip capping when adjusted_signal stayed buy."""
    _dnlm_research_sources(tmp_path)
    note = (
        "Buy — neutral timing | FCF basis mismatch: filing £211.4M | "
        "screen TTM £163.9M | company-adj £171M"
    )
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="DNLM.L",
                name="Dunelm Group plc",
                sector="Consumer Cyclical",
                signal="buy",
                conviction_score=0.75,
                free_cashflow=171_000_000.0,
                free_cashflow_screen_ttm=163_900_000.0,
                fcf_basis_overlay=True,
                action_note=note,
            )
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "DNLM.L",
                "model_id": "fcf_yield",
                "model_name": "FCF Yield",
                "passed": True,
                "score": 0.8,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )

    snapshot = build_company_reports(signals, model_results, output_dir=tmp_path)[0].to_dict()

    assert snapshot["fcf_basis_overlay"] is True
    assert snapshot["adjusted_signal"] == "hold"


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
    assert snapshot["interim_eps_decline_pct"] == pytest.approx(0.039)
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


def test_earnings_growth_bps_diverge_flags_hik_style_gap():
    from value_investor.scoring.fcf import earnings_growth_bps_diverge

    assert earnings_growth_bps_diverge(0.017, 0.05) is True
    assert earnings_growth_bps_diverge(0.017, 0.03) is False
    assert earnings_growth_bps_diverge(0.05, 0.08) is False


def test_build_company_reports_exports_lynch_peg_and_bps_warning(tmp_path: Path):
    from value_investor.storage import write_json

    run_at = "2026-09-02T10:22:48.084715+00:00"
    for ticker, moat_pass in (("MEGP.L", True), ("FGP.L", False)):
        sources = tmp_path / "research" / ticker / "sources"
        sources.mkdir(parents=True)
        write_json(
            sources / "screen_run_manifest.json",
            {
                "ticker": ticker,
                "run_at": run_at,
                "ticker_signal": {
                    "ticker": ticker,
                    "signal": "strong_buy",
                    "sector": "Industrials",
                    "models_passed": 15,
                },
                "ticker_models": [
                    {"ticker": ticker, "model_id": "economic_moat", "passed": moat_pass},
                    {"ticker": ticker, "model_id": "lynch_peg", "passed": False},
                ],
                "models_passed": 15,
            },
            compact=False,
            compress=False,
        )

    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="MEGP.L",
                name="ME Group International plc",
                sector="Industrials",
                signal="strong_buy",
                trailing_pe=12.0,
                earnings_growth=0.045,
                basic_eps_growth_pct=0.004,
                adjusted_eps_growth_pct=0.045,
            )
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

    assert snapshot["earnings_growth_bps_divergence_warning"] is True
    assert snapshot["screening_inputs"]["lynch_peg_model"] == pytest.approx(12.0 / (0.045 * 100))
    assert snapshot["screening_inputs"]["lynch_peg_statutory"] == pytest.approx(
        12.0 / (0.004 * 100)
    )
    assert snapshot["peer_model_pass_table"]["peer_count"] == 2
    moat_row = next(
        row
        for row in snapshot["peer_model_pass_table"]["model_rows"]
        if row["model_id"] == "economic_moat"
    )
    assert moat_row["peer_passes"]["MEGP.L"] is True
    assert moat_row["peer_passes"]["FGP.L"] is False
    assert (tmp_path / "research" / "MEGP.L" / "sources" / "peer_model_pass_table.json").exists()
    assert "Earnings growth basis divergence >300 bps" in snapshot["action_note"]


def test_build_company_reports_lynch_peg_uses_filing_growth_without_bps_warning():
    signals = pd.DataFrame(
        [
            _signal_row(
                ticker="HIK.L",
                name="Hikma Pharmaceuticals PLC",
                sector="Health Care",
                signal="strong_buy",
                trailing_pe=11.6,
                earnings_growth=0.05,
                basic_eps_growth_pct=0.05,
                adjusted_eps_growth_pct=0.05,
            )
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

    snapshot = build_company_reports(signals, model_results)[0].to_dict()

    assert snapshot["earnings_growth_bps_divergence_warning"] is False
    assert snapshot["screening_inputs"]["model_earnings_growth_pct"] == pytest.approx(0.05)
    assert snapshot["screening_inputs"]["lynch_peg_model"] == pytest.approx(11.6 / (0.05 * 100))


def test_build_company_reports_exports_conviction_timing_overlay_for_hold_to_buy():
    from datetime import UTC, datetime

    from value_investor.scoring.conviction_timing_overlay import HOLD_TO_BUY_KEY

    run_at = datetime(2026, 9, 3, 10, 0, 0, tzinfo=UTC)
    history = pd.DataFrame(
        [
            {
                "run_at": "2026-08-27T10:00:00+00:00",
                "ticker": "ABC.L",
                "signal": "hold",
                "signal_rank": 2,
                "conviction_score": 0.2,
                "data_quality_score": 1.0,
            }
        ]
    )
    signals = pd.DataFrame(
        [
            {
                "ticker": "ABC.L",
                "name": "ABC plc",
                "signal": "buy",
                "signal_rank": 3,
                "models_passed": 8,
                "model_count": 22,
                "composite_score": 0.55,
                "sector_composite_score": 0.52,
                "families_passed": 3,
                "passed_families": "cheapness,quality,dividend",
                "family_count": 5,
                "data_quality_score": 1.0,
                "metrics_present": 20,
                "metrics_total": 20,
                "weeks_at_signal": 1,
                "signal_trend": "improving",
                "conviction_score": 0.4,
                "stability_label": "new",
                "timing_signal": "accumulate",
                "timing_score": 0.7,
                "rsi_14": 45.0,
                "price_vs_sma200_pct": -0.05,
            }
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

    report = build_company_reports(
        signals,
        model_results,
        signal_history=history,
        run_at=run_at,
    )[0]
    snapshot = report.to_dict()

    assert snapshot["transition_key"] == HOLD_TO_BUY_KEY
    assert snapshot["conviction_timing_overlay"] is True
    assert snapshot["conviction_timing_overlay_detail"][
        "conviction_timing_overlay_score"
    ] == pytest.approx(0.3)
    assert (
        snapshot["conviction_timing_overlay_detail"]["conviction_timing_overlay_timing"] == "wait"
    )
    assert snapshot["signal"] == "buy"
    assert snapshot["conviction_score"] == pytest.approx(0.4)
    assert "Conviction-timing overlay (observe-only)" in report.summary


def test_build_company_reports_exports_quality_family_avoid_gate_for_aal_pattern():
    signals = pd.DataFrame(
        [
            {
                "ticker": "AAL.L",
                "name": "Anglo American plc",
                "signal": "avoid",
                "signal_rank": 1,
                "models_passed": 2,
                "model_count": 22,
                "composite_score": 0.325,
                "sector_composite_score": 0.31,
                "families_passed": 2,
                "passed_families": "cheapness,risk",
                "family_count": 5,
                "data_quality_score": 0.95,
                "metrics_present": 19,
                "metrics_total": 20,
                "weeks_at_signal": 1,
                "signal_trend": "new",
                "conviction_score": 0.0633,
                "stability_label": "new",
                "timing_signal": "neutral",
                "timing_score": 0.5,
                "rsi_14": 40.0,
                "price_vs_sma200_pct": -0.1,
            }
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "AAL.L",
                "model_id": model_id,
                "model_name": model_id,
                "passed": False,
                "score": score,
                "reasons": [],
                "failed_criteria": [],
            }
            for model_id, score in {
                "quality_value": 0.2,
                "buffett_quality": 0.15,
                "economic_moat": 0.1,
                "piotroski_f": 0.25,
            }.items()
        ]
    )

    report = build_company_reports(signals, model_results)[0]
    snapshot = report.to_dict()

    assert snapshot["quality_family_avoid_gate"] is True
    assert snapshot["quality_family_avoid_gate_detail"]["quality_family_avoid_gate_action"] == (
        "cohort_watch"
    )
    assert snapshot["quality_family_avoid_gate_detail"]["quality_family_composite_score"] == (
        pytest.approx(0.175)
    )
    assert snapshot["signal"] == "avoid"
    assert "Quality-family avoid gate (observe-only)" in report.summary


def test_fcf_bundle_from_persisted_report_prefers_note_filing_over_metrics():
    note = "Buy | FCF basis mismatch: filing £148M | screen TTM £211.9M"
    bundle = fcf_bundle_from_persisted_report(
        None,
        action_note=note,
        key_metrics={"FCF": 187_000_000.0, "free_cashflow": 187_000_000.0},
    )
    assert bundle["filing_aligned"] == pytest.approx(148_000_000.0)
    assert bundle["screen_ttm"] == pytest.approx(211_900_000.0)


def test_honour_and_to_dict_backfill_structured_fcf_from_note():
    note = "Buy — neutral timing | FCF basis mismatch: filing £192.1M | screen TTM £353.2M"
    report = CompanyReport.from_dict(
        {
            "ticker": "BKG.L",
            "name": "The Berkeley Group Holdings plc",
            "sector": "Consumer Cyclical",
            "signal": "buy",
            "adjusted_signal": "hold",
            "models_passed": 10,
            "model_count": 22,
            "composite_score": 0.6,
            "families_passed": 4,
            "data_quality_score": 1.0,
            "metrics_present": 18,
            "metrics_total": 20,
            "weeks_at_signal": 2,
            "signal_trend": "stable",
            "conviction_score": 0.7,
            "stability_label": "new",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "action_note": note,
            "fcf_basis_overlay": True,
            "fcf": None,
            "summary": "Buy.",
            "passed_models": [],
            "key_metrics": {},
        }
    )
    enforced = honour_fcf_action_note_enforcement(report)
    assert enforced.fcf is not None
    assert enforced.fcf["filing_aligned"] == pytest.approx(192_100_000.0)
    assert enforced.fcf["screen_ttm"] == pytest.approx(353_200_000.0)
    snapshot = report.to_dict()
    assert snapshot["fcf"]["filing_aligned"] == pytest.approx(192_100_000.0)
    assert snapshot["fcf"]["screen_ttm"] == pytest.approx(353_200_000.0)
