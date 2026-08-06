"""Tests for per-rebalance decision logging and log-based replay."""

from pathlib import Path

from value_investor.decision_review import LearningKnobs, estimate_counterfactual_with_log
from value_investor.paper_automation import AutomationConfig, run_daily_automation
from value_investor.paper_fund import PaperFund, PaperFundConfig
from value_investor.rebalance_log import (
    REBALANCE_LOG_FILENAME,
    append_rebalance_log,
    build_rebalance_log_entry,
    collect_decision_candidates,
    collect_screen_buy_tier,
    gate_excluded_tickers,
    load_rebalance_log,
    replay_counterfactual_from_log,
    resolve_replay_candidates,
    slim_candidate,
)


def test_slim_candidate_keeps_replay_fields():
    row = {
        "ticker": "AAA.L",
        "name": "Alpha",
        "signal": "buy",
        "adjusted_signal": "strong_buy",
        "conviction_score": 0.8,
        "timing_signal": "neutral",
        "sector": "Banks",
        "price": 10.5,
        "research_verdict": "accumulate",
        "trade_plan": {"tactical_stop_loss": 9.0, "noise": "drop"},
    }
    slim = slim_candidate(row)
    assert slim["ticker"] == "AAA.L"
    assert slim["adjusted_signal"] == "strong_buy"
    assert slim["trade_plan"]["tactical_stop_loss"] == 9.0
    assert "noise" not in slim.get("trade_plan", {})


def test_collect_decision_candidates_includes_holdings():
    fund = PaperFund.create(
        PaperFundConfig(name="Auto", mode="automated", initial_cash=1000)
    )
    fund.buy(
        ticker="HOLD.L",
        price=10,
        sizing_mode="cash",
        amount=200,
        sector="Mining",
        name="Held",
    )
    marked = [
        {
            "ticker": "BUY.L",
            "signal": "buy",
            "conviction_score": 0.9,
            "price": 12,
        },
        {
            "ticker": "AI.L",
            "signal": "strong_buy",
            "adjusted_signal": "hold",
            "conviction_score": 0.85,
            "price": 8,
        },
        {
            "ticker": "HOLD.L",
            "signal": "hold",
            "price": 10,
        },
        {
            "ticker": "SKIP.L",
            "signal": "hold",
            "price": 5,
        },
    ]
    screen = collect_screen_buy_tier(marked, fund)
    screen_tickers = {row["ticker"] for row in screen}
    assert screen_tickers == {"BUY.L", "AI.L", "HOLD.L"}

    picked = collect_decision_candidates(marked, fund, use_adjusted_signal=False)
    assert {row["ticker"] for row in picked} == {"BUY.L", "AI.L", "HOLD.L"}

    gated = collect_decision_candidates(marked, fund, use_adjusted_signal=True)
    assert {row["ticker"] for row in gated} == {"BUY.L", "HOLD.L"}
    assert gate_excluded_tickers(screen, gated) == ["AI.L"]


def test_resolve_replay_candidates_widens_on_ai_gate_change():
    entry = {
        "selection": {
            "use_adjusted_signal": True,
            "require_research_accumulate": True,
        },
        "screen_buy_tier": [{"ticker": "AI.L"}, {"ticker": "BUY.L"}],
        "candidates": [{"ticker": "BUY.L"}],
    }
    assert resolve_replay_candidates(entry) == entry["candidates"]
    assert resolve_replay_candidates(entry, use_adjusted_signal=False) == entry[
        "screen_buy_tier"
    ]
    assert (
        resolve_replay_candidates(entry, candidate_source="screen_buy_tier")
        == entry["screen_buy_tier"]
    )


def test_replay_counterfactual_uses_screen_pool_for_raw_signal(tmp_path: Path):
    out = tmp_path / "track"
    out.mkdir()
    base_entry = {
        "schema_version": 2,
        "strategy_mode": "automated",
        "trade_cost_pct": 0.0,
        "max_positions": 5,
        "acted": True,
        "selection": {
            "skip_timing_wait": True,
            "min_conviction": 0.0,
            "sector_cap": 1.0,
            "use_adjusted_signal": True,
            "require_research_accumulate": False,
            "use_momentum_grace": False,
            "exit_confirm_screens": 0,
            "reentry_cooldown_screens": 0,
            "min_rebalance_notional_gbp": 0.0,
        },
        "nav_before": 1000.0,
        "cash_before": 1000.0,
        "contributed_capital_before": 1000.0,
        "holdings_before": [],
        "rebalance_state_before": {},
        "screen_buy_tier": [
            {
                "ticker": "RAW.L",
                "signal": "strong_buy",
                "adjusted_signal": "hold",
                "conviction_score": 0.95,
                "price": 10,
                "sector": "Tech",
            },
            {
                "ticker": "BUY.L",
                "signal": "buy",
                "adjusted_signal": "buy",
                "conviction_score": 0.7,
                "price": 10,
                "sector": "Banks",
            },
        ],
        "candidates": [
            {
                "ticker": "BUY.L",
                "signal": "buy",
                "adjusted_signal": "buy",
                "conviction_score": 0.7,
                "price": 10,
                "sector": "Banks",
            }
        ],
        "gate_excluded": ["RAW.L"],
        "holdings_after": [],
        "rebalance_state_after": {},
    }
    entries = [
        {**base_entry, "gate": {"local_time": "2026-01-01T12:00:00+00:00"}},
        {**base_entry, "gate": {"local_time": "2026-01-02T12:00:00+00:00"}},
    ]
    for entry in entries:
        append_rebalance_log(out, entry)

    gated = replay_counterfactual_from_log(
        load_rebalance_log(out),
        max_positions=2,
        use_adjusted_signal=True,
    )
    raw = replay_counterfactual_from_log(
        load_rebalance_log(out),
        max_positions=2,
        use_adjusted_signal=False,
    )
    assert gated is not None and raw is not None
    assert gated["used_screen_buy_tier_pool"] is False
    assert raw["used_screen_buy_tier_pool"] is True
    assert raw["simulated_trade_count"] > gated["simulated_trade_count"]


def test_run_daily_automation_appends_rebalance_log(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    reports_path = tmp_path / "latest.json"
    reports_path.write_text(
        __import__("json").dumps(
            {
                "run_at": "2026-07-15T08:00:00+00:00",
                "reports": [
                    {
                        "ticker": "AAA.L",
                        "name": "Alpha",
                        "signal": "strong_buy",
                        "conviction_score": 0.9,
                        "price": 10,
                        "timing_signal": "neutral",
                        "sector": "Banks",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "value_investor.paper_automation.refresh_candidate_marks",
        lambda candidates, extra_tickers=None: candidates,
    )
    out = tmp_path / "auto"
    run_daily_automation(
        output_dir=out,
        config=AutomationConfig(initial_cash=1000, trade_cost_pct=0.0, max_positions=1),
        reports_path=reports_path,
        now=datetime(2026, 7, 15, 10, 0, tzinfo=ZoneInfo("Europe/London")),
        force=True,
    )
    log_path = out / REBALANCE_LOG_FILENAME
    assert log_path.exists()
    entries = load_rebalance_log(out)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["acted"] is True
    assert entry["schema_version"] == 2
    assert entry["screen_source"]["run_at"] == "2026-07-15T08:00:00+00:00"
    assert any(row["ticker"] == "AAA.L" for row in entry["candidates"])
    assert any(row["ticker"] == "AAA.L" for row in entry["screen_buy_tier"])
    assert entry["gate_excluded"] == []
def test_replay_counterfactual_from_log_changes_trade_count(tmp_path: Path):
    out = tmp_path / "track"
    out.mkdir()
    entries = [
        {
            "schema_version": 1,
            "strategy_mode": "automated",
            "trade_cost_pct": 0.0,
            "max_positions": 5,
            "acted": True,
            "gate": {"local_time": "2026-01-01T12:00:00+00:00"},
            "selection": {
                "skip_timing_wait": True,
                "min_conviction": 0.0,
                "sector_cap": 1.0,
                "use_adjusted_signal": False,
                "require_research_accumulate": False,
                "use_momentum_grace": False,
                "exit_confirm_screens": 0,
                "reentry_cooldown_screens": 0,
                "min_rebalance_notional_gbp": 0.0,
            },
            "nav_before": 1000.0,
            "cash_before": 1000.0,
            "contributed_capital_before": 1000.0,
            "holdings_before": [],
            "rebalance_state_before": {},
            "candidates": [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "conviction_score": 0.9,
                    "price": 10,
                    "sector": "Banks",
                },
                {
                    "ticker": "BBB.L",
                    "signal": "buy",
                    "conviction_score": 0.8,
                    "price": 10,
                    "sector": "Mining",
                },
            ],
            "holdings_after": [],
            "rebalance_state_after": {},
        },
        {
            "schema_version": 1,
            "strategy_mode": "automated",
            "trade_cost_pct": 0.0,
            "max_positions": 5,
            "acted": True,
            "gate": {"local_time": "2026-01-02T12:00:00+00:00"},
            "selection": {
                "skip_timing_wait": True,
                "min_conviction": 0.0,
                "sector_cap": 1.0,
                "use_adjusted_signal": False,
                "require_research_accumulate": False,
                "use_momentum_grace": False,
                "exit_confirm_screens": 0,
                "reentry_cooldown_screens": 0,
                "min_rebalance_notional_gbp": 0.0,
            },
            "nav_before": 1000.0,
            "cash_before": 500.0,
            "contributed_capital_before": 1000.0,
            "holdings_before": [
                {
                    "ticker": "AAA.L",
                    "shares": 50,
                    "avg_cost": 10,
                    "sector": "Banks",
                    "name": "AAA",
                }
            ],
            "rebalance_state_before": {},
            "candidates": [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "conviction_score": 0.9,
                    "price": 10,
                    "sector": "Banks",
                },
                {
                    "ticker": "BBB.L",
                    "signal": "buy",
                    "conviction_score": 0.8,
                    "price": 10,
                    "sector": "Mining",
                },
            ],
            "holdings_after": [],
            "rebalance_state_after": {},
        },
    ]
    for entry in entries:
        append_rebalance_log(out, entry)

    wide = replay_counterfactual_from_log(
        load_rebalance_log(out),
        max_positions=2,
        min_conviction=0.0,
        sector_cap=1.0,
    )
    narrow = replay_counterfactual_from_log(
        load_rebalance_log(out),
        max_positions=1,
        min_conviction=0.0,
        sector_cap=1.0,
    )
    assert wide is not None and narrow is not None
    assert wide["simulated_trade_count"] >= narrow["simulated_trade_count"]


def test_estimate_counterfactual_with_log_uses_preview_when_log_thin(tmp_path: Path):
    fund = PaperFund.create(
        PaperFundConfig(name="Auto", mode="automated", initial_cash=1000, trade_cost_pct=0.03)
    )
    fund.buy(
        ticker="AAA.L",
        price=10,
        sizing_mode="cash",
        amount=400,
        sector="Banks",
        name="A",
    )
    preview = estimate_counterfactual_with_log(
        tmp_path,
        fund,
        knobs=LearningKnobs(max_positions=1, sector_cap=0.5),
    )
    assert preview["scope"] == "lifetime_trade_replay"
    assert preview["graduates_at_acted_entries"] == 2
