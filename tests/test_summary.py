"""Tests for company report / screening snapshot export fields."""

from __future__ import annotations

import pandas as pd

from value_investor.models.piotroski import PiotroskiFScoreModel, piotroski_snapshot_from_result
from value_investor.scoring import evaluate_universe
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


def test_build_company_reports_exports_failed_models():
    signals = pd.DataFrame([_signal_row()])
    model_results = _model_results_for_hik()

    report = build_company_reports(signals, model_results)[0]

    assert report.failed_models == ["FCF Yield", "Piotroski F-Score"]
    assert "Graham Enterprising" in report.passed_models
    assert report.signal == "strong_buy"


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
