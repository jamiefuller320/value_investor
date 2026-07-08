"""Tests for email report generation."""

from unittest.mock import MagicMock, patch

import pandas as pd

from value_investor.emailer import EmailConfig, format_html_report, format_text_report, send_report_email
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
    assert "strong_buy" not in html
    assert "Strong Buy" in html


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
