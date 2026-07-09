"""Tests for email report generation."""

from unittest.mock import MagicMock, patch

import pandas as pd

from value_investor.backtest import BacktestSummary, HorizonResult
from value_investor.deep_analysis import DeepAnalysis
from value_investor.emailer import EmailConfig, format_html_report, format_text_report, send_report_email
from value_investor.run_diff import RunDiff
from value_investor.summary import build_company_reports


def _sample_frames():
    signals = pd.DataFrame([
        {
            "ticker": "AAA.L",
            "name": "Alpha PLC",
            "sector": "Financials",
            "signal": "strong_buy",
            "models_passed": 10,
            "model_count": 18,
            "composite_score": 0.8,
            "sector_composite_score": 0.82,
            "families_passed": 3,
            "passed_families": "cheapness,quality,dividend",
            "data_quality_score": 0.85,
            "metrics_present": 18,
            "metrics_total": 20,
            "weeks_at_signal": 3,
            "signal_trend": "stable",
            "conviction_score": 0.72,
            "stability_label": "building",
            "timing_signal": "accumulate",
            "timing_score": 0.75,
            "rsi_14": 34.0,
            "price_vs_sma200_pct": -0.08,
            "timing_reasons": ["RSI below neutral (34)", "below 200-day MA"],
            "action_note": "Strong Buy — favourable entry timing",
            "core_order": "limit",
            "core_limit": 98.5,
            "core_allocation_pct": 0.65,
            "tactical_order": "limit",
            "tactical_limit": 95.0,
            "tactical_allocation_pct": 0.35,
            "stop_loss": 92.0,
            "take_profit": 105.0,
            "trade_plan_summary": (
                "Trade plan: core 65% limit £98.50; tactical 35% limit £95.00; "
                "stop £92.00, target £105.00."
            ),
            "trailing_pe": 8.0,
            "price_to_book": 0.9,
            "dividend_yield": 0.04,
            "return_on_equity": 0.15,
        },
        {
            "ticker": "BBB.L",
            "name": "Beta PLC",
            "sector": "Energy",
            "signal": "avoid",
            "models_passed": 2,
            "model_count": 18,
            "composite_score": 0.3,
            "sector_composite_score": 0.25,
            "families_passed": 1,
            "passed_families": "cheapness",
            "data_quality_score": 0.45,
            "metrics_present": 9,
            "metrics_total": 20,
            "weeks_at_signal": 1,
            "signal_trend": "deteriorating",
            "conviction_score": 0.15,
            "stability_label": "new",
            "timing_signal": "wait",
            "timing_score": 0.25,
            "rsi_14": 72.0,
            "price_vs_sma200_pct": 0.12,
            "timing_reasons": ["RSI overbought (72)"],
            "action_note": "Pass — weak fundamentals",
            "trailing_pe": 25.0,
            "price_to_book": 3.0,
            "dividend_yield": 0.01,
            "return_on_equity": 0.05,
        },
    ])
    model_results = pd.DataFrame([
        {
            "ticker": "AAA.L",
            "model_name": "Graham Defensive",
            "passed": True,
            "score": 1.0,
            "reasons": "['P/E < 15: P/E=8.0', 'Dividend payer: yield=4.00%']",
            "failed_criteria": "[]",
        },
        {
            "ticker": "AAA.L",
            "model_name": "Deep Value",
            "passed": True,
            "score": 0.9,
            "reasons": "['P/E=8.0', 'EV/EBITDA=6.0']",
            "failed_criteria": "[]",
        },
        {
            "ticker": "BBB.L",
            "model_name": "Graham Defensive",
            "passed": False,
            "score": 0.2,
            "reasons": "[]",
            "failed_criteria": "['P/E >= 15']",
        },
    ])
    return signals, model_results


def test_build_company_reports_includes_summary():
    signals, model_results = _sample_frames()
    reports = build_company_reports(signals, model_results)

    assert len(reports) == 2
    alpha = reports[0]
    assert alpha.ticker == "AAA.L"
    assert alpha.signal == "strong_buy"
    assert "Strong Buy" in alpha.summary
    assert "Graham Defensive" in alpha.summary


def test_format_reports_contain_all_companies():
    signals, model_results = _sample_frames()
    reports = build_company_reports(signals, model_results)

    text = format_text_report(run_at="2026-07-08", reports=reports)
    html = format_html_report(run_at="2026-07-08", reports=reports)

    assert "Alpha PLC" in text
    assert "Beta PLC" in text
    assert "Families:" in text
    assert "Conviction" in text
    assert "Timing" in text
    assert "Market timing" in html or "Accumulate" in html
    assert "strong_buy" not in html
    assert "Strong Buy" in html


def test_format_reports_include_diff_and_deep_analysis_sections():
    signals, model_results = _sample_frames()
    reports = build_company_reports(signals, model_results)
    run_diff = RunDiff(
        previous_run_at="2026-07-01",
        new_strong_buys=["Alpha (AAA.L): buy → strong_buy"],
        persistent_strong_buys=[],
        lost_strong_buys=[],
        upgrades=["Alpha (AAA.L): buy → strong_buy"],
        downgrades=[],
        unchanged_top_signals=1,
    )
    deep_analysis = DeepAnalysis(
        executive_intro="Markets look selective.",
        top_picks_analysis="Alpha stands out on cheapness and quality.",
        red_flags="Energy names remain cyclical.",
    )

    text = format_text_report(
        run_at="2026-07-08",
        reports=reports,
        run_diff=run_diff,
        deep_analysis=deep_analysis,
    )
    html = format_html_report(
        run_at="2026-07-08",
        reports=reports,
        run_diff=run_diff,
        deep_analysis=deep_analysis,
    )

    assert "WEEK-OVER-WEEK CHANGES" in text
    assert "DEEP ANALYSIS" in text
    assert "Red flags" in html
    assert "Week-over-week changes" in html


def test_format_reports_include_backtest_section():
    signals, model_results = _sample_frames()
    reports = build_company_reports(signals, model_results)
    backtest = BacktestSummary(
        run_count=3,
        horizons=[
            HorizonResult(
                horizon_days=7,
                signal="strong_buy",
                avg_return=0.05,
                count=4,
                benchmark_return=0.01,
                excess_return=0.04,
            )
        ],
    )
    text = format_text_report(run_at="2026-07-08", reports=reports, backtest=backtest)
    assert "SIGNAL BACKTEST" in text
    assert "strong_buy" in text


def test_format_reports_highlight_favorable_timing():
    signals, model_results = _sample_frames()
    reports = build_company_reports(signals, model_results)
    text = format_text_report(run_at="2026-07-08", reports=reports)
    assert "MARKET TIMING" in text
    assert "Alpha PLC" in text
    assert "favourable" in text.lower()


def test_format_reports_include_strong_buy_trade_plans():
    signals, model_results = _sample_frames()
    reports = build_company_reports(signals, model_results)
    text = format_text_report(run_at="2026-07-08", reports=reports)
    html = format_html_report(run_at="2026-07-08", reports=reports)

    assert "STRONG BUY TRADE PLANS" in text
    assert "Trade plan:" in text
    assert "stop £92.00" in text
    assert "Strong buy trade plans" in html
    assert "Tactical:" in html
    alpha = reports[0]
    assert "Trade plan:" in alpha.summary


@patch("value_investor.emailer.smtplib.SMTP")
def test_send_report_email(mock_smtp):
    server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = server

    config = EmailConfig(
        smtp_host="smtp.test",
        smtp_port=587,
        smtp_user="from@test.com",
        smtp_password="secret",
        email_to="to@test.com",
    )
    send_report_email(
        subject="Test",
        text_body="hello",
        html_body="<p>hello</p>",
        config=config,
    )

    server.starttls.assert_called_once()
    server.login.assert_called_once_with("from@test.com", "secret")
    server.sendmail.assert_called_once()
