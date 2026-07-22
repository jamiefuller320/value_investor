"""Tests for independent paper automation and session settle gating."""

from datetime import datetime
from zoneinfo import ZoneInfo

from value_investor.paper_automation import (
    AutomationConfig,
    is_after_open_settle,
    run_daily_automation,
    session_gate_status,
    surveil_position,
)
from value_investor.paper_fund import PaperFund


LONDON = ZoneInfo("Europe/London")


def test_settle_gate_waits_until_after_open_volatility_window():
    config = AutomationConfig(settle_minutes_after_open=75, market_open="08:00")
    before = datetime(2026, 7, 15, 8, 30, tzinfo=LONDON)  # Wednesday
    after = datetime(2026, 7, 15, 9, 20, tzinfo=LONDON)
    weekend = datetime(2026, 7, 18, 10, 0, tzinfo=LONDON)  # Saturday

    assert not is_after_open_settle(config, before)
    assert is_after_open_settle(config, after)
    assert not is_after_open_settle(config, weekend)

    early = session_gate_status(config, before)
    assert early["can_act"] is False
    assert "settle" in early["reason"]

    ready = session_gate_status(config, after)
    assert ready["can_act"] is True


def test_surveil_position_flags_stop_and_wait():
    alerts = surveil_position(
        ticker="AAA.L",
        name="Alpha",
        source="live",
        mark=90,
        stop_loss=95,
        take_profit=120,
        timing_signal="wait",
        signal="buy",
    )
    severities = {a.severity for a in alerts}
    messages = " ".join(a.message for a in alerts)
    assert "action" in severities
    assert "watch" in severities
    assert "stop" in messages.lower()
    assert "wait" in messages.lower()


def test_run_daily_automation_force_rebalances_without_network(tmp_path, monkeypatch):
    reports = {
        "reports": [
            {
                "ticker": "AAA.L",
                "name": "Alpha",
                "signal": "strong_buy",
                "conviction_score": 0.9,
                "price": 10,
                "timing_signal": "accumulate",
            },
            {
                "ticker": "BBB.L",
                "name": "Beta",
                "signal": "buy",
                "conviction_score": 0.8,
                "price": 20,
                "timing_signal": "neutral",
            },
        ]
    }
    reports_path = tmp_path / "latest.json"
    reports_path.write_text(__import__("json").dumps(reports), encoding="utf-8")

    monkeypatch.setattr(
        "value_investor.paper_automation.refresh_candidate_marks",
        lambda candidates, extra_tickers=None: candidates,
    )

    config = AutomationConfig(
        initial_cash=1000,
        trade_cost_pct=0.0,
        max_positions=2,
        settle_minutes_after_open=75,
    )
    result = run_daily_automation(
        output_dir=tmp_path / "auto",
        config=config,
        reports_path=reports_path,
        now=datetime(2026, 7, 15, 8, 10, tzinfo=LONDON),  # before settle
        force=True,
    )
    assert result.acted is True
    assert len(result.trades) >= 1
    assert (tmp_path / "auto" / "automated_fund.json").exists()
    assert (tmp_path / "auto" / "last_run.json").exists()

    fund = PaperFund.from_dict(
        __import__("json").loads((tmp_path / "auto" / "automated_fund.json").read_text())
    )
    assert fund.config.mode == "automated"
    assert len(fund.holdings) == 2


def test_run_daily_automation_skips_before_settle(tmp_path, monkeypatch):
    reports_path = tmp_path / "latest.json"
    reports_path.write_text(
        __import__("json").dumps({"reports": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "value_investor.paper_automation.refresh_candidate_marks",
        lambda candidates, extra_tickers=None: candidates,
    )
    result = run_daily_automation(
        output_dir=tmp_path / "auto",
        config=AutomationConfig(),
        reports_path=reports_path,
        now=datetime(2026, 7, 15, 8, 10, tzinfo=LONDON),
        force=False,
    )
    assert result.acted is False
    assert result.gate["can_act"] is False


def test_run_learning_tracks_primary_ai_and_rules_control(tmp_path, monkeypatch):
    from value_investor.paper_automation import run_learning_tracks

    reports = {
        "reports": [
            {
                "ticker": "GOOD.L",
                "name": "Good",
                "signal": "strong_buy",
                "adjusted_signal": "strong_buy",
                "research_verdict": "accumulate",
                "conviction_score": 0.9,
                "price": 10,
                "timing_signal": "accumulate",
            },
            {
                "ticker": "SCREEN.L",
                "name": "ScreenOnly",
                "signal": "buy",
                "adjusted_signal": "buy",
                "research_verdict": None,
                "conviction_score": 0.85,
                "price": 12,
                "timing_signal": "neutral",
            },
        ]
    }
    reports_path = tmp_path / "latest.json"
    reports_path.write_text(__import__("json").dumps(reports), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.paper_automation.refresh_candidate_marks",
        lambda candidates, extra_tickers=None: candidates,
    )

    summary = run_learning_tracks(
        base_dir=tmp_path / "auto",
        reports_path=reports_path,
        now=datetime(2026, 7, 15, 10, 0, tzinfo=LONDON),
        force=True,
    )
    assert summary["primary_learning_track"] == "ai_judgment"
    assert "rules" in summary["tracks"]
    assert "ai_judgment" in summary["tracks"]
    assert summary["tracks"]["ai_judgment"]["is_primary_learning_track"] is True
    assert (tmp_path / "auto" / "learning_tracks_summary.json").exists()
    assert (tmp_path / "auto" / "ai_judgment" / "config.json").exists()

    rules_fund = PaperFund.from_dict(
        __import__("json").loads(
            (tmp_path / "auto" / "automated_fund.json").read_text(encoding="utf-8")
        )
    )
    ai_fund = PaperFund.from_dict(
        __import__("json").loads(
            (tmp_path / "auto" / "ai_judgment" / "automated_fund.json").read_text(
                encoding="utf-8"
            )
        )
    )
    # Rules may hold both buy-tier names; AI judgment requires research accumulate.
    assert "GOOD.L" in ai_fund.holdings
    assert "SCREEN.L" not in ai_fund.holdings
    assert "GOOD.L" in rules_fund.holdings
    assert "SCREEN.L" in rules_fund.holdings
