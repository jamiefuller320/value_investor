"""Tests for company report / screening snapshot export fields."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from value_investor.models.piotroski import PiotroskiFScoreModel, piotroski_snapshot_from_result
from value_investor.scoring import evaluate_universe
from value_investor.models.risk import EarningsQualityModel
from value_investor.scoring.fcf import reconcile_fcf
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
    return pd.DataFrame([
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
    ])


def _model_results_for_hik_cash_conversion_cap(*, ticker: str = "HIKX.L") -> pd.DataFrame:
    return pd.DataFrame([
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
    ])


def test_build_company_reports_exports_failed_models():
    signals = pd.DataFrame([_signal_row()])
    model_results = _model_results_for_hik()

    report = build_company_reports(signals, model_results)[0]

    assert report.failed_models == ["FCF Yield", "Piotroski F-Score"]
    assert "Graham Enterprising" in report.passed_models
    assert report.signal == "strong_buy"


def test_build_company_reports_exports_model_failures_and_screening_inputs():
    signals = pd.DataFrame([
        _signal_row(
            debt_to_equity=140.0,
            current_ratio=0.73,
            earnings_growth=-0.072,
            dividend_yield=0.04,
            ncav=None,
        )
    ])
    model_results = pd.DataFrame([
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
    ])

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
    components = {item["name"]: item["passed"] for item in snapshot["piotroski_f_score"]["components"]}
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
    universe = pd.DataFrame([
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
    ])
    model_results = evaluate_universe(universe, models=[PiotroskiFScoreModel()])
    signals = pd.DataFrame([{"ticker": "AAA.L", "name": "Alpha", "signal": "buy", "models_passed": 1, "model_count": 1}])

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
    signals = pd.DataFrame([
        _signal_row(
            ticker="AEP.L",
            name="AEP Plantations Plc",
            sector=AGRICULTURE_COMMODITIES_SECTOR,
            sector_composite_score=0.55,
        )
    ])
    model_results = pd.DataFrame([
        {
            "ticker": "AEP.L",
            "model_id": "composite_value",
            "model_name": "Composite Value",
            "passed": True,
            "score": 0.7,
            "reasons": "[]",
            "failed_criteria": "[]",
        },
    ])

    report = build_company_reports(signals, model_results)[0]

    assert report.sector == AGRICULTURE_COMMODITIES_SECTOR
    assert report.sector_composite_score == 0.55
    assert "sector-relative 55%" in report.summary


def _healthcare_overlay_models(*, f_score: int = 3) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "ticker": "PHAR.L",
            "model_id": "piotroski_f",
            "model_name": "Piotroski F-Score",
            "passed": False,
            "score": f_score / 9,
            "reasons": f"['F-Score={f_score}/9']",
            "failed_criteria": f"['F-Score {f_score}/9 below 7']",
        },
    ])


def test_healthcare_overlay_caps_strong_buy_when_negative_fcf_and_weak_piotroski():
    signals = pd.DataFrame([
        _signal_row(
            ticker="PHAR.L",
            name="Pharma Weak Ltd",
            sector="Healthcare",
            signal="strong_buy",
            free_cashflow=-50.0,
        )
    ])
    model_results = _healthcare_overlay_models(f_score=3)

    report = build_company_reports(signals, model_results)[0]
    snapshot = report.to_dict()

    assert report.signal == "strong_buy"
    assert snapshot["healthcare_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert "Healthcare overlay" in report.summary


def test_healthcare_overlay_not_triggered_for_hik_like_profile():
    signals = pd.DataFrame([
        _signal_row(free_cashflow=-100.0),
    ])
    model_results = _model_results_for_hik()

    report = build_company_reports(signals, model_results)[0]

    assert report.signal == "strong_buy"
    assert report.to_dict()["healthcare_overlay"] is False
    assert report.to_dict()["cash_conversion_overlay"] is False
    assert report.to_dict()["adjusted_signal"] == "strong_buy"


def _model_results_for_megp_dividend_overlay(*, ticker: str = "MEGP.L") -> pd.DataFrame:
    return pd.DataFrame([
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
    ])


def test_dividend_yield_overlay_caps_megp_like_profile():
    signals = pd.DataFrame([
        _signal_row(
            ticker="MEGP.L",
            name="ME Group International plc",
            sector="Industrials",
            signal="strong_buy",
            dividend_yield=0.0757,
        ),
    ])
    model_results = _model_results_for_megp_dividend_overlay()

    report = build_company_reports(signals, model_results)[0]
    snapshot = report.to_dict()

    assert report.signal == "strong_buy"
    assert snapshot["dividend_yield_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert "Dividend-yield overlay" in report.summary


def test_dividend_yield_overlay_not_triggered_when_fcf_yield_passes():
    signals = pd.DataFrame([_signal_row(ticker="MEGP.L", signal="strong_buy")])
    model_results = pd.DataFrame([
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
    ])

    report = build_company_reports(signals, model_results)[0]

    assert report.to_dict()["dividend_yield_overlay"] is False
    assert report.to_dict()["adjusted_signal"] == "strong_buy"


def test_cash_conversion_overlay_caps_hik_like_profile():
    signals = pd.DataFrame([
        _signal_row(
            ticker="HIKX.L",
            name="Hikma-like Test plc",
            free_cashflow=-66.1,
            shares_outstanding=240_000_000,
            shares_outstanding_prev=245_000_000,
        ),
    ])
    model_results = _model_results_for_hik_cash_conversion_cap()

    report = build_company_reports(signals, model_results)[0]
    snapshot = report.to_dict()

    assert report.signal == "strong_buy"
    assert snapshot["healthcare_overlay"] is False
    assert snapshot["cash_conversion_overlay"] is True
    assert snapshot["adjusted_signal"] == "buy"
    assert "Cash-conversion overlay" in report.summary


def test_cash_conversion_overlay_not_triggered_without_dividend_screen():
    signals = pd.DataFrame([
        _signal_row(
            free_cashflow=-66.1,
            shares_outstanding=240_000_000,
            shares_outstanding_prev=245_000_000,
        ),
    ])
    model_results = pd.DataFrame([
        {
            "ticker": "HIK.L",
            "model_id": "piotroski_f",
            "model_name": "Piotroski F-Score",
            "passed": True,
            "score": 7 / 9,
            "reasons": "['F-Score=7/9', 'no share dilution']",
            "failed_criteria": "[]",
        },
    ])

    report = build_company_reports(signals, model_results)[0]

    assert report.to_dict()["cash_conversion_overlay"] is False
    assert report.to_dict()["adjusted_signal"] == "strong_buy"


def test_cash_conversion_overlay_respects_existing_research_adjusted_signal():
    signals = pd.DataFrame([
        _signal_row(
            ticker="HIKX.L",
            name="Hikma-like Test plc",
            free_cashflow=-66.1,
            shares_outstanding=240_000_000,
            shares_outstanding_prev=245_000_000,
            adjusted_signal="hold",
            research_verdict="pass",
        ),
    ])
    model_results = _model_results_for_hik_cash_conversion_cap()

    report = build_company_reports(signals, model_results)[0]

    assert report.to_dict()["cash_conversion_overlay"] is True
    assert report.adjusted_signal == "hold"


def test_healthcare_overlay_respects_existing_research_adjusted_signal():
    signals = pd.DataFrame([
        _signal_row(
            ticker="PHAR.L",
            name="Pharma Weak Ltd",
            sector="Health Care",
            signal="strong_buy",
            free_cashflow=-25.0,
            adjusted_signal="hold",
            research_verdict="pass",
        )
    ])
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
    assert bundle["screen_ttm"] == -66_125_000.0
    assert bundle["cashflow_metrics_free_cashflow"] == 119_000_000.0


def test_build_company_reports_exports_reconciled_fcf(tmp_path: Path):
    sources = tmp_path / "research" / "HIK.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(json.dumps(_hik_financials()), encoding="utf-8")

    signals = pd.DataFrame([
        _signal_row(
            free_cashflow=-66_125_000.0,
            free_cashflow_screen_ttm=-66_125_000.0,
            shares_outstanding=240_000_000,
            shares_outstanding_prev=245_000_000,
        )
    ])
    model_results = _model_results_for_hik_cash_conversion_cap(ticker="HIK.L")

    snapshot = build_company_reports(signals, model_results, output_dir=tmp_path)[0].to_dict()

    assert snapshot["key_metrics"]["FCF"] == "119000000.0"
    assert snapshot["cashflow_metrics"]["free_cashflow"] == 119_000_000.0
    assert snapshot["fcf"]["canonical"] == 119_000_000.0
    assert snapshot["fcf"]["source"] == "filing_aligned_ocf_capex"
    assert snapshot["fcf"]["screen_ttm"] == -66_125_000.0
    assert snapshot["cash_conversion_overlay"] is False
    assert snapshot["adjusted_signal"] == "strong_buy"
