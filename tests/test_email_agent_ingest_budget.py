"""Email-agent CLI wiring for Sunday ingest runtime budget (L429)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from value_investor.email_agent import main
from value_investor.research.ingest_improvement import (
    DEFAULT_EMAIL_INGEST_MAX_RUNTIME_SECONDS,
)


def test_ingest_max_runtime_default_matches_constant() -> None:
    assert DEFAULT_EMAIL_INGEST_MAX_RUNTIME_SECONDS == 5400


def _fake_screen_result() -> MagicMock:
    result = MagicMock()
    result.signals = pd.DataFrame(
        [
            {
                "ticker": "AAA.L",
                "name": "Alpha PLC",
                "sector": "Financials",
                "signal": "buy",
                "models_passed": 8,
                "model_count": 18,
                "composite_score": 0.7,
            }
        ]
    )
    result.model_results = pd.DataFrame()
    result.trust_signals = None
    result.trust_model_results = None
    result.run_at = datetime.now(UTC)
    result.universe_name = "ftse350"
    result.excluded_investment_vehicles = 0
    result.run_diff = None
    result.backtest = None
    result.simulation = None
    return result


def _report_mock() -> MagicMock:
    report = MagicMock()
    report.ticker = "AAA.L"
    report.signal = "buy"
    report.to_dict.return_value = {"ticker": "AAA.L", "signal": "buy"}
    return report


@patch("value_investor.email_agent.load_historical_analysis_summary", return_value=None)
@patch("value_investor.email_agent.run_screen")
@patch("value_investor.email_agent.write_outputs")
@patch("value_investor.email_agent.build_company_reports")
@patch("value_investor.email_agent.build_trust_reports", return_value=[])
@patch("value_investor.email_agent.format_text_report", return_value="text")
@patch("value_investor.email_agent.format_html_report", return_value="<html/>")
@patch("value_investor.email_agent.research_documents_for_reports", return_value={})
@patch("value_investor.email_agent.publish_dashboard")
def test_email_agent_passes_ingest_max_runtime_seconds(
    _mock_publish,
    _mock_docs,
    _mock_html,
    _mock_text,
    _mock_trust,
    mock_reports,
    _mock_write,
    mock_screen,
    _mock_hist,
    tmp_path,
):
    mock_screen.return_value = _fake_screen_result()
    mock_reports.return_value = [_report_mock()]

    with patch(
        "value_investor.research.ingest_improvement.run_ingest_improvement_pass"
    ) as mock_ingest:
        mock_ingest.return_value = MagicMock()
        out = tmp_path / "output"
        out.mkdir()
        code = main(
            [
                "--dry-run",
                "--output-dir",
                str(out),
                "--ingest-improvement-pass",
                "--ingest-improvement-cap",
                "3",
                "--ingest-max-runtime-seconds",
                "120",
                "--no-record-spend",
            ]
        )
        assert code == 0
        assert mock_ingest.called
        kwargs = mock_ingest.call_args.kwargs
        assert kwargs["max_runtime_seconds"] == 120.0
        assert kwargs["max_targets"] == 3


@patch("value_investor.email_agent.load_historical_analysis_summary", return_value=None)
@patch("value_investor.email_agent.run_screen")
@patch("value_investor.email_agent.write_outputs")
@patch("value_investor.email_agent.build_company_reports")
@patch("value_investor.email_agent.build_trust_reports", return_value=[])
@patch("value_investor.email_agent.format_text_report", return_value="text")
@patch("value_investor.email_agent.format_html_report", return_value="<html/>")
@patch("value_investor.email_agent.research_documents_for_reports", return_value={})
def test_email_agent_zero_ingest_runtime_means_unlimited(
    _mock_docs,
    _mock_html,
    _mock_text,
    _mock_trust,
    mock_reports,
    _mock_write,
    mock_screen,
    _mock_hist,
    tmp_path,
):
    mock_screen.return_value = _fake_screen_result()
    mock_reports.return_value = [_report_mock()]
    with patch(
        "value_investor.research.ingest_improvement.run_ingest_improvement_pass"
    ) as mock_ingest:
        mock_ingest.return_value = MagicMock()
        out = tmp_path / "output"
        out.mkdir()
        code = main(
            [
                "--dry-run",
                "--output-dir",
                str(out),
                "--ingest-improvement-pass",
                "--ingest-max-runtime-seconds",
                "0",
                "--no-record-spend",
            ]
        )
        assert code == 0
        assert mock_ingest.call_args.kwargs["max_runtime_seconds"] is None
