import json
from pathlib import Path

from value_investor.hold_period_counterfactual import (
    FINDING_TITLE,
    MIN_FAITHFUL_PASSES,
    STORE_FAILED_TITLE,
    faithful_window,
    ops_finding_from_hold_period_counterfactual,
    realised_holding_stats,
    score_track,
)
from value_investor.rebalance_log import append_rebalance_log


def _no_ratio(ticker, from_day, to_day):
    return None


def _pass(day: int, shares: float) -> dict:
    holdings = [{"ticker": "AAA.L", "shares": shares, "avg_cost": 300.0, "sector": "Banks"}]
    return {
        "acted": True,
        "logged_at": f"2026-09-{day:02d}T08:00:00+00:00",
        "strategy_mode": "automated",
        "max_positions": 1,
        "trade_cost_pct": 0.0,
        "nav_before": 300.0 * shares,
        "nav_after": 600.0,
        "cash_before": 0.0,
        "contributed_capital_before": 1000.0,
        "holdings_before": holdings,
        "holdings_after": holdings,
        "candidates": [
            {
                "ticker": "AAA.L",
                "price": 300.0,
                "signal": "buy",
                "conviction_score": 0.9,
                "sector": "Banks",
            }
        ],
        "selection": {"skip_timing_wait": True, "exit_confirm_screens": 2},
        "trades": [],
    }


def test_realised_holding_stats_fifo_and_turnover():
    fund = {
        "trades": [
            {
                "acted_at": "2026-09-01T08:00:00+00:00",
                "ticker": "AAA.L",
                "side": "buy",
                "shares": 2.0,
                "gross": 200.0,
            },
            {
                "acted_at": "2026-09-05T08:00:00+00:00",
                "ticker": "AAA.L",
                "side": "sell",
                "shares": 1.0,
                "gross": 100.0,
            },
            {
                "acted_at": "2026-09-11T08:00:00+00:00",
                "ticker": "AAA.L",
                "side": "sell",
                "shares": 1.0,
                "gross": 100.0,
            },
            {
                "acted_at": "2026-09-02T08:00:00+00:00",
                "ticker": "BBB.L",
                "side": "buy",
                "shares": 1.0,
                "gross": 100.0,
            },
        ],
        "equity_curve": [
            {"at": "2026-09-01T09:00:00+00:00", "portfolio_value": 1000.0},
            {"at": "2026-09-15T09:00:00+00:00", "portfolio_value": 1000.0},
        ],
    }
    stats = realised_holding_stats(fund)
    assert stats["closed_lots"] == 1
    assert stats["median_hold_days"] == 10.0
    assert stats["window_days"] == 14.0
    assert stats["annualised_sell_turnover"] == 5.2


def test_faithful_window_skips_log_hole_at_start():
    acted = [_pass(1, 3.0)] + [_pass(day, 2.0) for day in range(2, 2 + MIN_FAITHFUL_PASSES + 1)]
    window = faithful_window(acted, _no_ratio)
    assert window is not None
    start, replay, gap = window
    assert start == 1
    assert gap == 0.0
    assert replay["simulated_nav"] == 600.0


def test_faithful_window_none_when_too_few_passes():
    acted = [_pass(day, 2.0) for day in range(1, MIN_FAITHFUL_PASSES)]
    assert faithful_window(acted, _no_ratio) is None


def test_score_track_reports_unreliable_and_ok(tmp_path: Path):
    short = tmp_path / "short"
    short.mkdir()
    (short / "automated_fund.json").write_text(json.dumps({"trades": []}), encoding="utf-8")
    append_rebalance_log(short, _pass(1, 2.0))
    row = score_track("rules", short, _no_ratio)
    assert row["status"] == "unreliable"

    full = tmp_path / "full"
    full.mkdir()
    (full / "automated_fund.json").write_text(json.dumps({"trades": []}), encoding="utf-8")
    for day in range(1, MIN_FAITHFUL_PASSES + 2):
        append_rebalance_log(full, _pass(day, 2.0))
    row = score_track("rules", full, _no_ratio)
    assert row["status"] == "ok"
    assert row["live_exit_confirm_screens"] == 2
    assert row["window"]["skipped_passes"] == 0
    assert [v["exit_confirm_screens"] for v in row["variants"]] == [5, 10, 20]
    assert all(v["delta_vs_baseline"] == 0.0 for v in row["variants"])


def _payload(delta: float, status: str = "ok") -> dict:
    best = {"exit_confirm_screens": 5, "delta_vs_baseline": delta, "trade_count": 10}
    return {
        "tracks": {
            "rules_fair": {
                "status": status,
                "live_exit_confirm_screens": 2,
                "window": {"passes": 19},
                "baseline": {"trade_count": 24},
                "realised": {"median_hold_days": 4.0},
                "best_variant": best,
            }
        }
    }


def test_ops_finding_only_for_faithful_edge():
    finding = ops_finding_from_hold_period_counterfactual(_payload(0.05))
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False
    assert "rules_fair" in finding["summary"]
    assert ops_finding_from_hold_period_counterfactual(_payload(0.005)) is None
    assert ops_finding_from_hold_period_counterfactual(_payload(0.05, "unreliable")) is None


def test_ops_finding_skips_book_with_running_exit_buffer_twin():
    payload = {**_payload(0.05), "exit_buffer_twins": {"rules_fair": "rules_hold5_fair"}}
    assert ops_finding_from_hold_period_counterfactual(payload) is None


def test_build_scores_primary_and_control_only(tmp_path: Path, monkeypatch):
    from value_investor import hold_period_counterfactual as module

    root = tmp_path / "paper"
    for track_id in ("", "ai_judgment", "ai_judgment_fair", "buy_tier_level"):
        path = root / track_id if track_id else root
        path.mkdir(parents=True, exist_ok=True)
        (path / "automated_fund.json").write_text("{}", encoding="utf-8")
    for track_id, flag in (
        ("ai_judgment_fair", "is_fair_cost_lab"),
        ("buy_tier_level", "is_cohort_lab"),
    ):
        (root / track_id / "config.json").write_text(
            json.dumps({"track_id": track_id, flag: True}), encoding="utf-8"
        )
    (root / "assessment_model.json").write_text(
        json.dumps(
            {
                "primary_track": "ai_judgment_fair",
                "control_track": "buy_tier_level",
                "frozen_tracks": {"rules": {}, "ai_judgment": {}},
                "twins": {
                    "ai_judgment_hold5_fair": {
                        "parent_track": "ai_judgment_fair",
                        "varied": {"exit_confirm_screens": {"parent": 2, "twin": 5}},
                    },
                    "ai_judgment_graduated_fair": {
                        "parent_track": "ai_judgment_fair",
                        "varied": {"use_graduated_allocation": {"parent": False, "twin": True}},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    scored: list[str] = []
    monkeypatch.setattr(
        module, "score_track", lambda track_id, *_a: scored.append(track_id) or {"status": "ok"}
    )

    payload = module.build_hold_period_counterfactual(root, history_fetcher=_no_ratio)

    assert scored == ["ai_judgment_fair", "buy_tier_level"]
    assert payload["exit_buffer_twins"] == {"ai_judgment_fair": "ai_judgment_hold5_fair"}


def test_check_hold_period_counterfactual_persists_and_reports(tmp_path: Path, monkeypatch):
    from value_investor import hold_period_counterfactual as module
    from value_investor.ops_monitor import check_hold_period_counterfactual

    root = tmp_path / "paper_automation"
    root.mkdir()
    store = tmp_path / "hold_period_counterfactual.json"
    monkeypatch.setattr(module, "build_hold_period_counterfactual", lambda *a, **k: _payload(0.05))
    findings = check_hold_period_counterfactual(paper_root=root, store_path=store)
    assert [f.title for f in findings] == [FINDING_TITLE]
    assert findings[0].auto_fixable is False
    assert json.loads(store.read_text())["tracks"]["rules_fair"]["status"] == "ok"

    def boom(*a, **k):
        raise ValueError("bad log")

    monkeypatch.setattr(module, "build_hold_period_counterfactual", boom)
    failed = check_hold_period_counterfactual(paper_root=root, store_path=store)
    assert [f.title for f in failed] == [STORE_FAILED_TITLE]
