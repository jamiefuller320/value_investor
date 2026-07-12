"""Tests for risk-family screening models."""

from value_investor.models.risk import EarningsQualityModel, FinancialHealthModel
from value_investor.signals import Signal, assign_signal


def test_earnings_quality_passes_strong_cash_conversion():
    model = EarningsQualityModel()
    row = {
        "net_income": 100,
        "free_cashflow": 90,
        "operating_cashflow": 110,
        "total_assets": 2000,
    }
    result = model.evaluate(row)
    assert result.passed is True
    assert result.score >= 0.75


def test_earnings_quality_fails_high_accruals():
    model = EarningsQualityModel()
    row = {
        "net_income": 100,
        "free_cashflow": 20,
        "operating_cashflow": 30,
        "total_assets": 1000,
    }
    result = model.evaluate(row)
    assert result.passed is False


def test_financial_health_passes_conservative_balance_sheet():
    model = FinancialHealthModel()
    row = {
        "debt_to_equity": 40,
        "leverage": 0.3,
        "current_ratio_bs": 1.8,
        "total_debt": 200,
        "total_cash": 50,
        "ebitda": 150,
        "ebit": 120,
        "interest_expense": 10,
    }
    result = model.evaluate(row)
    assert result.passed is True


def test_assign_signal_downgrades_on_risk_family_failure():
    signal = assign_signal(
        models_passed=8,
        model_count=20,
        mean_model_score=0.8,
        weighted_model_score=0.82,
        composite_score=0.85,
        sector_composite_score=0.85,
        families_passed=3,
        family_count=5,
        data_quality_score=0.85,
        risk_family_passed=False,
        risk_mean_score=0.3,
        has_errors=False,
    )
    assert signal != Signal.STRONG_BUY
