"""Tests for per-rebalance decision logging and log-based replay."""

from pathlib import Path

from value_investor.decision_review import LearningKnobs, estimate_counterfactual_with_log
from value_investor.paper_automation import AutomationConfig, run_daily_automation
from value_investor.paper_fund import PaperFund, PaperFundConfig
from value_investor.rebalance_log import (
    REBALANCE_LOG_FILENAME,
    append_rebalance_log,
    collect_buy_tier_history_tickers,
    collect_decision_candidates,
    collect_screen_buy_tier,
    compare_buffered_hold_across_tracks,
    compare_buffered_hold_counterfactual,
    compare_rebalance_counterfactual_previews,
    extract_held_stress_episode_seeds,
    extract_log_swap_rotation_seeds,
    filter_acted_log_entries_since,
    gate_excluded_tickers,
    load_rebalance_log,
    replay_counterfactual_from_archive,
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
        "data_quality_score": 0.92,
        "timing_signal": "neutral",
        "sector": "Banks",
        "price": 10.5,
        "research_verdict": "accumulate",
        "trade_plan": {"tactical_stop_loss": 9.0, "noise": "drop"},
    }
    slim = slim_candidate(row)
    assert slim["ticker"] == "AAA.L"
    assert slim["adjusted_signal"] == "strong_buy"
    assert slim["data_quality_score"] == 0.92
    assert slim["trade_plan"]["tactical_stop_loss"] == 9.0
    assert "noise" not in slim.get("trade_plan", {})


def test_collect_decision_candidates_includes_holdings():
    fund = PaperFund.create(PaperFundConfig(name="Auto", mode="automated", initial_cash=1000))
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
    assert resolve_replay_candidates(entry, use_adjusted_signal=False) == entry["screen_buy_tier"]
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


def _write_archive(
    archive_dir: Path,
    stamp: str,
    run_at: str,
    reports: list[dict],
) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / f"{stamp}.json").write_text(
        __import__("json").dumps({"run_at": run_at, "reports": reports}),
        encoding="utf-8",
    )


def test_archive_rebalance_replay_walks_more_passes_than_log(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "value_investor.archive_history.snapshot_prices",
        lambda tickers: {t: 10.0 for t in tickers},
    )
    track = tmp_path / "rules"
    track.mkdir()
    archive = tmp_path / "archive"
    reports = [
        {
            "ticker": "AAA.L",
            "signal": "strong_buy",
            "conviction_score": 0.9,
            "timing_signal": "neutral",
            "sector": "Banks",
            "price": 10,
        },
        {
            "ticker": "BBB.L",
            "signal": "buy",
            "conviction_score": 0.8,
            "timing_signal": "neutral",
            "sector": "Mining",
            "price": 10,
        },
    ]
    _write_archive(archive, "2026-01-01", "2026-01-01T12:00:00+00:00", reports)
    _write_archive(archive, "2026-01-08", "2026-01-08T12:00:00+00:00", reports)
    _write_archive(archive, "2026-01-15", "2026-01-15T12:00:00+00:00", reports)

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
        "candidates": reports,
        "holdings_after": [],
        "rebalance_state_after": {},
    }
    append_rebalance_log(
        track,
        {**base_entry, "gate": {"local_time": "2026-01-01T13:00:00+00:00"}},
    )
    append_rebalance_log(
        track,
        {**base_entry, "gate": {"local_time": "2026-01-08T13:00:00+00:00"}},
    )

    archive_preview = replay_counterfactual_from_archive(
        track,
        max_positions=2,
        min_conviction=0.55,
        sector_cap=0.2,
        archive_dir=archive,
    )
    log_preview = replay_counterfactual_from_log(
        load_rebalance_log(track),
        max_positions=2,
        min_conviction=0.55,
        sector_cap=0.2,
    )
    assert archive_preview is not None and log_preview is not None
    assert archive_preview["scope"] == "archive_rebalance_replay"
    assert archive_preview["archive_passes_replayed"] >= log_preview["log_entries_replayed"]
    assert archive_preview["archive_passes_replayed"] == 3


def test_compare_rebalance_counterfactual_previews_structure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "value_investor.archive_history.snapshot_prices",
        lambda tickers: {t: 10.0 for t in tickers},
    )
    track = tmp_path / "rules"
    track.mkdir()
    archive = tmp_path / "archive"
    reports = [
        {
            "ticker": "AAA.L",
            "signal": "strong_buy",
            "conviction_score": 0.9,
            "timing_signal": "neutral",
            "sector": "Banks",
            "price": 10,
        }
    ]
    _write_archive(archive, "2026-01-01", "2026-01-01T12:00:00+00:00", reports)
    _write_archive(archive, "2026-01-08", "2026-01-08T12:00:00+00:00", reports)

    entry = {
        "schema_version": 2,
        "strategy_mode": "automated",
        "trade_cost_pct": 0.0,
        "max_positions": 5,
        "acted": True,
        "gate": {"local_time": "2026-01-01T13:00:00+00:00"},
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
        "candidates": reports,
        "holdings_after": [],
        "rebalance_state_after": {},
    }
    append_rebalance_log(track, entry)
    append_rebalance_log(track, {**entry, "gate": {"local_time": "2026-01-08T13:00:00+00:00"}})

    comparison = compare_rebalance_counterfactual_previews(
        track,
        max_positions=1,
        min_conviction=0.55,
        sector_cap=0.2,
        archive_dir=archive,
    )
    assert comparison is not None
    assert comparison["scope"] == "rebalance_counterfactual_comparison"
    assert comparison["observe_only"] is True
    assert comparison["log_preview"] is not None
    assert comparison["archive_preview"] is not None
    cmp = comparison["comparison"]
    assert cmp["archive_passes_replayed"] >= cmp["log_entries_replayed"]
    assert "return_delta_gap_archive_minus_log" in cmp


def _buffered_hold_base_entry(**overrides):
    base = {
        "schema_version": 2,
        "track_id": "rules",
        "strategy_mode": "automated",
        "trade_cost_pct": 0.03,
        "max_positions": 3,
        "acted": True,
        "selection": {
            "skip_timing_wait": True,
            "min_conviction": 0.0,
            "sector_cap": 1.0,
            "use_adjusted_signal": False,
            "require_research_accumulate": False,
            "use_momentum_grace": False,
            "exit_confirm_screens": 2,
            "reentry_cooldown_screens": 1,
            "min_rebalance_notional_gbp": 0.0,
        },
        "nav_before": 1000.0,
        "cash_before": 400.0,
        "contributed_capital_before": 1000.0,
        "holdings_before": [
            {
                "ticker": "HIK.L",
                "shares": 10,
                "avg_cost": 10,
                "sector": "Healthcare",
                "name": "Hikma",
            },
            {
                "ticker": "ITV.L",
                "shares": 10,
                "avg_cost": 10,
                "sector": "Communication Services",
                "name": "ITV",
            },
            {
                "ticker": "FGP.L",
                "shares": 10,
                "avg_cost": 10,
                "sector": "Industrials",
                "name": "FirstGroup",
            },
        ],
        "rebalance_state_before": {
            "exit_streak": {"HIK.L": 0, "ITV.L": 0, "FGP.L": 0},
            "reentry_cooldown": {},
        },
        "candidates": [
            {
                "ticker": "AAA.L",
                "signal": "strong_buy",
                "conviction_score": 0.95,
                "price": 10,
                "sector": "Banks",
            },
            {
                "ticker": "BBB.L",
                "signal": "buy",
                "conviction_score": 0.9,
                "price": 10,
                "sector": "Mining",
            },
            {
                "ticker": "CCC.L",
                "signal": "buy",
                "conviction_score": 0.85,
                "price": 10,
                "sector": "Tech",
            },
            {
                "ticker": "HIK.L",
                "signal": "hold",
                "conviction_score": 0.4,
                "price": 10,
                "sector": "Healthcare",
            },
            {
                "ticker": "ITV.L",
                "signal": "hold",
                "conviction_score": 0.4,
                "price": 10,
                "sector": "Communication Services",
            },
            {
                "ticker": "FGP.L",
                "signal": "hold",
                "conviction_score": 0.4,
                "price": 10,
                "sector": "Industrials",
            },
        ],
        "holdings_after": [
            {
                "ticker": "HIK.L",
                "shares": 10,
                "avg_cost": 10,
                "sector": "Healthcare",
                "name": "Hikma",
            },
            {
                "ticker": "ITV.L",
                "shares": 10,
                "avg_cost": 10,
                "sector": "Communication Services",
                "name": "ITV",
            },
            {
                "ticker": "FGP.L",
                "shares": 10,
                "avg_cost": 10,
                "sector": "Industrials",
                "name": "FirstGroup",
            },
        ],
        "rebalance_state_after": {
            "exit_streak": {"HIK.L": 1, "ITV.L": 1, "FGP.L": 1},
            "reentry_cooldown": {},
        },
        "trades": [],
    }
    base.update(overrides)
    return base


def test_filter_acted_log_entries_since_respects_lookback():
    from datetime import UTC, datetime

    entries = [
        {"acted": True, "gate": {"local_time": "2026-08-01T12:00:00+00:00"}},
        {"acted": True, "gate": {"local_time": "2026-08-08T12:00:00+00:00"}},
        {"acted": True, "gate": {"local_time": "2026-08-10T12:00:00+00:00"}},
        {"acted": False, "gate": {"local_time": "2026-08-10T13:00:00+00:00"}},
    ]
    filtered = filter_acted_log_entries_since(
        entries,
        lookback_days=7,
        as_of=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
    )
    assert [e["gate"]["local_time"] for e in filtered] == [
        "2026-08-08T12:00:00+00:00",
        "2026-08-10T12:00:00+00:00",
    ]


def test_exit_confirm_screens_counterfactual_changes_trade_count(tmp_path: Path):
    from datetime import UTC, datetime

    out = tmp_path / "rules"
    out.mkdir()
    entry = _buffered_hold_base_entry(gate={"local_time": "2026-08-10T12:00:00+00:00"})
    append_rebalance_log(out, entry)

    as_of = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    buffered = replay_counterfactual_from_log(
        load_rebalance_log(out),
        max_positions=3,
        exit_confirm_screens=2,
        lookback_days=7,
        as_of=as_of,
    )
    immediate = replay_counterfactual_from_log(
        load_rebalance_log(out),
        max_positions=3,
        exit_confirm_screens=1,
        lookback_days=7,
        as_of=as_of,
    )
    assert buffered is not None and immediate is not None
    assert buffered["knobs"]["exit_confirm_screens"] == 2
    assert immediate["knobs"]["exit_confirm_screens"] == 1
    assert immediate["simulated_trade_count"] > buffered["simulated_trade_count"]


def test_compare_buffered_hold_counterfactual_structure(tmp_path: Path):
    from datetime import UTC, datetime

    out = tmp_path / "rules"
    out.mkdir()
    append_rebalance_log(
        out,
        _buffered_hold_base_entry(gate={"local_time": "2026-08-10T12:00:00+00:00"}),
    )
    comparison = compare_buffered_hold_counterfactual(
        out,
        lookback_days=7,
        as_of=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
    )
    assert comparison is not None
    assert comparison["scope"] == "buffered_hold_counterfactual"
    assert comparison["observe_only"] is True
    assert comparison["churn_context"]["buffered_holdings"] == 3
    assert set(comparison["churn_context"]["exit_streak"]) == {"HIK.L", "ITV.L", "FGP.L"}
    assert "1" in comparison["variants"]
    assert "2" in comparison["variants"]
    assert comparison["comparison"]["trade_count_delta_lower_minus_higher"] >= 0


def test_compare_buffered_hold_across_tracks(tmp_path: Path):
    from datetime import UTC, datetime

    paper = tmp_path / "paper_automation"
    rules = paper
    ai = paper / "ai_judgment"
    ai.mkdir(parents=True)
    as_of = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    for track_dir, track_id in ((rules, "rules"), (ai, "ai_judgment")):
        append_rebalance_log(
            track_dir,
            _buffered_hold_base_entry(
                track_id=track_id,
                gate={"local_time": "2026-08-10T12:00:00+00:00"},
            ),
        )
    comparison = compare_buffered_hold_across_tracks(
        paper,
        lookback_days=7,
        as_of=as_of,
    )
    assert comparison is not None
    assert comparison["scope"] == "buffered_hold_counterfactual_multi"
    assert set(comparison["tracks"]) == {"rules", "ai_judgment"}


def test_write_buffered_hold_counterfactual(tmp_path: Path):
    from datetime import UTC, datetime

    from value_investor.rebalance_log import (
        BUFFERED_HOLD_COUNTERFACTUAL_FILENAME,
        append_rebalance_log,
        write_buffered_hold_counterfactual,
    )

    paper = tmp_path / "paper_automation"
    rules = paper
    ai = paper / "ai_judgment"
    ai.mkdir(parents=True)
    as_of = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    for track_dir, track_id in ((rules, "rules"), (ai, "ai_judgment")):
        append_rebalance_log(
            track_dir,
            _buffered_hold_base_entry(
                track_id=track_id,
                gate={"local_time": "2026-08-10T12:00:00+00:00"},
            ),
        )
    payload = write_buffered_hold_counterfactual(paper, lookback_days=7, as_of=as_of)
    assert payload is not None
    assert (paper / BUFFERED_HOLD_COUNTERFACTUAL_FILENAME).exists()


def test_collect_buy_tier_history_tickers_from_log():
    entries = [
        {
            "acted": True,
            "gate": {"local_time": "2026-01-01T12:00:00+00:00"},
            "screen_buy_tier": [{"ticker": "AAA.L", "signal": "buy"}],
            "candidates": [{"ticker": "BBB.L", "signal": "strong_buy"}],
            "trades": [{"ticker": "CCC.L", "side": "buy"}],
        }
    ]
    history = collect_buy_tier_history_tickers(entries)
    assert history == frozenset({"AAA.L", "BBB.L", "CCC.L"})


def test_extract_held_stress_and_log_swap_seeds():
    entries = [
        {
            "acted": True,
            "track_id": "rules",
            "trade_cost_pct": 0.03,
            "gate": {"local_time": "2026-01-08T13:00:00+00:00"},
            "holdings_before": [
                {"ticker": "HELD.L", "avg_cost": 100.0, "name": "Held", "momentum_grace": True}
            ],
            "rebalance_state_before": {"exit_streak": {"HELD.L": 2}},
            "candidates": [
                {
                    "ticker": "HELD.L",
                    "signal": "strong_buy",
                    "adjusted_signal": "hold",
                    "conviction_score": 0.4,
                    "price": 92.0,
                }
            ],
            "screen_buy_tier": [{"ticker": "HELD.L", "signal": "strong_buy"}],
            "trades": [
                {"ticker": "HELD.L", "side": "sell", "price": 92.0, "note": "Automated exit"},
                {"ticker": "NEW.L", "side": "buy", "price": 50.0, "note": "Automated buy"},
            ],
        }
    ]
    history = collect_buy_tier_history_tickers(entries)
    held = extract_held_stress_episode_seeds(entries, buy_tier_history=history)
    assert len(held) == 1
    assert held[0]["ticker"] == "HELD.L"
    assert "signal_downgrade" in held[0]["stress_triggers"]
    assert "exit_streak" in held[0]["stress_triggers"]

    swaps = extract_log_swap_rotation_seeds(entries)
    assert len(swaps) == 1
    assert swaps[0]["rotation_id"] == "rules:2026-01-08T13:00:00+00:00"
    assert swaps[0]["sells"][0]["ticker"] == "HELD.L"
    assert swaps[0]["buys"][0]["ticker"] == "NEW.L"
