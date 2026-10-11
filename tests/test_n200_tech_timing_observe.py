"""Tests for sealed N200 observe-only tech-timing brackets."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.backtest import RunSnapshot
from value_investor.market_trading_costs import (
    LEGACY_STRESS_TRADE_COST_PCT,
    costs_for_market,
)
from value_investor.n200_tech_timing_observe import (
    FAIR_COST_MARKER_ID,
    FINDING_TITLE,
    PER_LEVER_MARKER_ID,
    PIPELINE_HEALTH_DISCLAIMER,
    REGISTRATION_ID,
    STRESS_TRADE_COST_PCT,
    VOLUME_GATE_TITLE,
    N200Config,
    build_lever_scoreboard,
    build_n200_observe,
    build_n200_pipeline_health_projection,
    build_registration_payload,
    episode_return,
    ops_findings_from_n200_observe,
    refresh_n200_tech_timing_observe,
    row_f9_eligible,
)


def _snap(
    day: int,
    rows: list[tuple[str, str, float]],
    *,
    month: int = 1,
) -> RunSnapshot:
    signals = [
        {"ticker": t, "signal": sig, "conviction_score": 0.5, "data_quality_score": 0.8}
        for t, sig, _ in rows
    ]
    prices = {t: p for t, _, p in rows}
    return RunSnapshot(
        run_at=f"2026-{month:02d}-{day:02d}T12:00:00+00:00",
        prices=prices,
        signals=signals,
    )


def test_episode_return_applies_round_trip_cost():
    assert abs(episode_return(100.0, 110.0, trade_cost_pct=0.03) - 0.04) < 1e-12


def test_episode_return_asymmetric_fair_costs():
    # buy 0.5% + sell 0.1% = 0.6% RT drag on +10% gross → 0.094
    got = episode_return(100.0, 110.0, buy_cost_pct=0.005, sell_cost_pct=0.001)
    assert abs(got - 0.094) < 1e-12


def test_row_f9_eligible_pass_and_fail():
    ok, note = row_f9_eligible({"ticker": "AAA.L"})
    assert ok and "or_pass" in note
    bad, reason = row_f9_eligible({"key_filing_bodies": False})
    assert not bad and "key_filing_bodies" in reason
    good, _ = row_f9_eligible(
        {
            "key_filing_bodies": True,
            "fcf_basis_bound": True,
            "overlay_bound": True,
            "memo_recent": True,
        }
    )
    assert good


def test_build_n200_observe_scores_brackets_fair_primary():
    # AAA enters buy on day 1 @100, leaves on day 29 @120 (~4 weeks)
    snaps = [
        _snap(1, [("AAA.L", "buy", 100.0), ("BBB.L", "hold", 50.0)]),
        _snap(8, [("AAA.L", "buy", 105.0)]),
        _snap(15, [("AAA.L", "buy", 110.0)]),
        _snap(22, [("AAA.L", "buy", 115.0)]),
        _snap(29, [("AAA.L", "hold", 120.0)]),  # left buy-tier
    ]
    payload = build_n200_observe(snaps, generated_at="2026-10-11T00:00:00+00:00")
    assert payload["registration_id"] == REGISTRATION_ID
    assert payload["identity_id"] == "raw_buy_tier"
    assert payload["completed_entry_episodes"] == 1
    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    fair = costs_for_market("ftse350")
    control = payload["path_scoreboard"]["control_smooth_ret_cohort_median"]
    assert control is not None
    # 120/100 - 1 - (buy+sell) fair RT
    expected_fair = 0.20 - fair.round_trip_pct
    assert abs(control - expected_fair) < 1e-6
    stress = payload["path_scoreboard"]["control_smooth_ret_cohort_median_stress_report_only"]
    expected_stress = 0.20 - 2.0 * STRESS_TRADE_COST_PCT
    assert abs(stress - expected_stress) < 1e-6
    # Fair primary is materially above stress (less drag).
    assert control > stress + 0.04
    assert payload["cost_basis"]["primary"] == "fair_market_table"
    assert payload["cost_basis"]["stress_role"] == "report_only"
    assert payload["stress_scoreboard_report_only"]["role"] == "report_only"
    assert "entry_+0__exit_+0" in payload["cells"]
    marker_ids = [m["marker_id"] for m in payload["change_markers"]]
    assert "n200-seal-v0" in marker_ids
    assert FAIR_COST_MARKER_ID in marker_ids
    assert "entry_lever_scoreboard" in payload
    assert "exit_lever_scoreboard" in payload
    assert payload["entry_lever_scoreboard"]["cost_basis"] == "fair_market_table"
    assert payload["entry_lever_scoreboard"]["independent_of_path_pnl"] is True
    assert payload["per_lever_scoreboards"]["independent_of_path_pnl"] is True
    assert payload["per_lever_scoreboards"]["not_capital_ready"] is True
    assert PER_LEVER_MARKER_ID in marker_ids


def test_fair_vs_stress_cfg_override_separates_scoreboards():
    snaps = [
        _snap(1, [("AAA.L", "buy", 100.0)]),
        _snap(15, [("AAA.L", "hold", 110.0)]),
    ]
    # Explicit tiny fair costs vs high stress — proves separation.
    cfg = N200Config(buy_cost_pct=0.001, sell_cost_pct=0.001, stress_trade_cost_pct=0.03)
    payload = build_n200_observe(snaps, cfg=cfg)
    fair_med = payload["path_scoreboard"]["control_smooth_ret_cohort_median"]
    stress_med = payload["path_scoreboard"]["control_smooth_ret_cohort_median_stress_report_only"]
    assert abs(fair_med - (0.10 - 0.002)) < 1e-6
    assert abs(stress_med - (0.10 - 0.06)) < 1e-6
    assert fair_med != stress_med
    assert payload["cells"]["entry_+0__exit_+0"]["smooth_ret_cohort_median"] == fair_med


def test_skips_f9_fail_rows():
    snaps = [
        RunSnapshot(
            run_at="2026-01-01T12:00:00+00:00",
            prices={"BAD.L": 10.0, "OK.L": 20.0},
            signals=[
                {
                    "ticker": "BAD.L",
                    "signal": "buy",
                    "key_filing_bodies": False,
                    "conviction_score": 0.9,
                },
                {
                    "ticker": "OK.L",
                    "signal": "buy",
                    "conviction_score": 0.9,
                },
            ],
        ),
        RunSnapshot(
            run_at="2026-01-15T12:00:00+00:00",
            prices={"BAD.L": 11.0, "OK.L": 22.0},
            signals=[
                {"ticker": "BAD.L", "signal": "hold"},
                {"ticker": "OK.L", "signal": "hold"},
            ],
        ),
    ]
    payload = build_n200_observe(snaps)
    assert payload["skipped_ineligible"] == 1
    assert payload["completed_entry_episodes"] == 1
    assert payload["episodes_sample"][0]["ticker"] == "OK.L"


def test_refresh_persists_registration_and_store(tmp_path: Path):
    hist = tmp_path / "history"
    hist.mkdir()
    snap = {
        "run_at": "2026-01-01T12:00:00+00:00",
        "prices": {"AAA.L": 100.0},
        "signals": [{"ticker": "AAA.L", "signal": "buy", "conviction_score": 0.5}],
    }
    (hist / "run_20260101.json").write_text(json.dumps(snap), encoding="utf-8")
    snap2 = {
        "run_at": "2026-01-15T12:00:00+00:00",
        "prices": {"AAA.L": 110.0},
        "signals": [{"ticker": "AAA.L", "signal": "hold", "conviction_score": 0.2}],
    }
    (hist / "run_20260115.json").write_text(json.dumps(snap2), encoding="utf-8")

    store = tmp_path / "n200_tech_timing_observe.json"
    reg = tmp_path / "n200_tech_timing_registration.json"
    payload = refresh_n200_tech_timing_observe(
        output_dir=tmp_path,
        store_path=store,
        registration_path=reg,
        persist=True,
    )
    assert store.is_file()
    assert reg.is_file()
    saved_reg = json.loads(reg.read_text(encoding="utf-8"))
    assert saved_reg["registration_id"] == REGISTRATION_ID
    assert saved_reg["o2_identity"] == "raw_buy_tier"
    assert saved_reg["n201_sealed"] is False
    assert saved_reg["cost_basis"]["primary"] == "fair_market_table"
    assert saved_reg["stress_trade_cost_pct"] == LEGACY_STRESS_TRADE_COST_PCT
    assert saved_reg["cost_amendment"]["marker_id"] == FAIR_COST_MARKER_ID
    assert saved_reg["cost_amendment"]["kept_registration_id"] is True
    assert payload["completed_entry_episodes"] == 1
    marker_ids = [m["marker_id"] for m in payload["change_markers"]]
    assert FAIR_COST_MARKER_ID in marker_ids


def test_ops_findings_volume_gate():
    base = build_n200_observe([])
    base["completed_entry_episodes"] = 30
    base["calendar_weeks_spanned"] = 10
    base["volume_gate"] = {"met": True, "min_episodes": 24, "min_weeks": 8}
    base["phase"] = {"entries_per_week": 3.0, "floor": 5.0, "floor_met": False}
    base["path_scoreboard"] = {
        "control_smooth_ret_cohort_median": 0.01,
        "control_smooth_ret_cohort_median_stress_report_only": -0.05,
    }
    base["per_lever_scoreboards"] = {
        "entry_verdict": "win",
        "exit_verdict": "lose",
        "independent_of_path_pnl": True,
    }
    findings = ops_findings_from_n200_observe(base)
    titles = {f["title"] for f in findings}
    assert FINDING_TITLE in titles
    assert VOLUME_GATE_TITLE in titles
    assert all(f["auto_fixable"] is False for f in findings)
    refresh = next(f for f in findings if f["title"] == FINDING_TITLE)
    assert "fair costs primary" in refresh["summary"]
    assert "stress_3pct_report_only" in refresh["summary"]
    assert "entry_lever=win" in refresh["summary"]
    assert "exit_lever=lose" in refresh["summary"]
    assert "independent of path P&L" in refresh["summary"]


def test_registration_payload_seal_fields():
    reg = build_registration_payload(sealed_at="2026-10-11")
    assert reg["status"] == "sealed_observe_only"
    assert reg["o5_primacy"]["control_excess"] == "report_only"
    assert reg["o5_primacy"]["stress_cost"] == "report_only"
    assert reg["o5_primacy"]["primary"] == "absolute_smoothed_return_fair_costs"
    assert reg["o3_volume_gate"]["rule"] == "both_required"
    assert reg["cost_basis"]["primary"] == "fair_market_table"
    assert reg["trade_cost_pct"] == reg["cost_basis"]["trade_cost_pct_symmetric_proxy"]
    assert reg["stress_trade_cost_pct"] == 0.03


def test_pipeline_health_projection_phase_volume_fresh():
    store = {
        "registration_id": REGISTRATION_ID,
        "deferred_id": "N200",
        "generated_at": "2026-10-11T12:00:00+00:00",
        "completed_entry_episodes": 101,
        "calendar_weeks_spanned": 9,
        "phase": {"entries_per_week": 11.0, "floor": 5.0, "floor_met": True},
        "volume_gate": {"met": True, "min_episodes": 24, "min_weeks": 8},
        "per_lever_scoreboards": {
            "entry_verdict": "lose",
            "exit_verdict": "win",
            "entry_margin_vs_best_alt": -0.01,
            "exit_margin_vs_best_alt": 0.005,
            "independent_of_path_pnl": True,
            "cost_basis": "fair_market_table",
            "path_control_smooth_ret_cohort_median": -0.0055,
        },
        "observe_only": True,
    }
    ops = {
        "run_at": "2026-10-11T12:30:00+00:00",
        "findings": [{"title": FINDING_TITLE, "severity": "info"}],
    }
    proj = build_n200_pipeline_health_projection(
        store,
        ops_status=ops,
        now=datetime(2026, 10, 11, 13, 0, tzinfo=UTC),
    )
    assert proj["observe_only"] is True
    assert proj["not_alpha_signal"] is True
    assert proj["not_capital_ready"] is True
    assert proj["disclaimer"] == PIPELINE_HEALTH_DISCLAIMER
    assert proj["phase"]["floor_met"] is True
    assert proj["phase"]["entries_per_week"] == 11.0
    assert proj["volume_gate"]["met"] is True
    assert proj["volume_gate"]["episodes"] == 101
    assert proj["volume_gate"]["weeks"] == 9
    assert proj["freshness"]["state"] == "fresh"
    assert proj["pipeline"]["functioning"] is True
    assert proj["pipeline"]["ops_check_ok"] is True
    assert proj["per_lever"]["present"] is True
    assert proj["per_lever"]["entry_verdict"] == "lose"
    assert proj["per_lever"]["exit_verdict"] == "win"
    assert proj["per_lever"]["independent_of_path_pnl"] is True
    assert proj["per_lever"]["cost_basis"] == "fair_market_table"
    assert "entry lever lose" in proj["headline"]
    assert "exit lever win" in proj["headline"]


def test_pipeline_health_projection_missing_store():
    proj = build_n200_pipeline_health_projection(
        None,
        store_path=Path("/nonexistent/n200_tech_timing_observe.json"),
        ops_status={"run_at": "2026-10-11T12:00:00+00:00", "findings": []},
        now=datetime(2026, 10, 11, 13, 0, tzinfo=UTC),
    )
    assert proj["store_present"] is False
    assert proj["pipeline"]["functioning"] is False
    assert proj["freshness"]["state"] == "missing"
    assert proj["not_capital_ready"] is True


def test_pipeline_health_projection_stale_not_functioning():
    store = {
        "generated_at": "2026-10-01T00:00:00+00:00",
        "completed_entry_episodes": 10,
        "calendar_weeks_spanned": 2,
        "phase": {"entries_per_week": 2.0, "floor": 5.0, "floor_met": False},
        "volume_gate": {"met": False, "min_episodes": 24, "min_weeks": 8},
    }
    proj = build_n200_pipeline_health_projection(
        store,
        ops_status={"run_at": "2026-10-11T12:00:00+00:00", "findings": []},
        now=datetime(2026, 10, 11, 13, 0, tzinfo=UTC),
    )
    assert proj["freshness"]["state"] == "stale"
    assert proj["pipeline"]["functioning"] is False
    assert proj["phase"]["floor_met"] is False


def test_build_lever_scoreboard_fair_cost_primary_and_verdicts():
    # Control best → win; alternative better → lose. Fair-cost medians only.
    win_board = build_lever_scoreboard(
        {-14: [-0.04], 0: [-0.01], 14: [-0.03]},
        lever="entry",
    )
    assert win_board["cost_basis"] == "fair_market_table"
    assert win_board["independent_of_path_pnl"] is True
    assert win_board["verdict"] == "win"
    assert win_board["control_is_best_feasible"] is True
    assert win_board["margin_vs_best_alt"] == 0.02
    assert win_board["best_alt_offset_days"] == 14

    lose_board = build_lever_scoreboard(
        {-14: [0.05], 0: [0.01], 14: [0.02]},
        lever="exit",
    )
    assert lose_board["verdict"] == "lose"
    assert lose_board["control_is_best_feasible"] is False
    assert lose_board["best_alt_offset_days"] == -14
    assert lose_board["margin_vs_best_alt"] == -0.04


def test_entry_lever_wins_while_path_loses():
    """Learning independence: best-feasible entry can win on a net-loss path.

    Prices (fair costs tiny so sign matches gross):
    - Control entry Jan15 @100 → exit Feb12 @95 → path loss
    - Early entry Jan1 @120 would be worse (bought higher)
    - Late entry Jan29 @110 would be worse
    """
    snaps = [
        _snap(1, [("AAA.L", "hold", 120.0)]),
        _snap(8, [("AAA.L", "hold", 115.0)]),
        _snap(15, [("AAA.L", "buy", 100.0)]),  # enter buy-tier (control)
        _snap(22, [("AAA.L", "buy", 102.0)]),
        _snap(29, [("AAA.L", "buy", 110.0)]),  # +14d entry worse
        _snap(5, [("AAA.L", "buy", 98.0)], month=2),
        _snap(12, [("AAA.L", "hold", 95.0)], month=2),  # leave buy-tier
    ]
    cfg = N200Config(buy_cost_pct=0.001, sell_cost_pct=0.001)
    payload = build_n200_observe(snaps, cfg=cfg)
    assert payload["completed_entry_episodes"] == 1
    path = payload["path_scoreboard"]["control_smooth_ret_cohort_median"]
    assert path is not None and path < 0
    entry = payload["entry_lever_scoreboard"]
    assert entry["cost_basis"] == "fair_market_table"
    assert entry["verdict"] == "win"
    assert entry["control_is_best_feasible"] is True
    assert entry["independent_of_path_pnl"] is True
    # Episode-level: path loss + entry win coexist.
    ep = payload["episodes_sample"][0]
    assert ep["control_return"] < 0
    assert ep["entry_lever"]["verdict"] == "win"
    assert payload["per_lever_scoreboards"]["entry_verdict"] == "win"
    assert payload["per_lever_scoreboards"]["path_control_smooth_ret_cohort_median"] == path


def test_entry_lever_fails_while_path_profits():
    """Learning independence: path can be green while entry was not best-feasible.

    Control entry Jan15 @100 → exit Feb12 @120 → path profit, but Jan1 @80
    would have been a better entry (bought cheaper).
    """
    snaps = [
        _snap(1, [("AAA.L", "hold", 80.0)]),  # -14d better entry
        _snap(8, [("AAA.L", "hold", 90.0)]),
        _snap(15, [("AAA.L", "buy", 100.0)]),
        _snap(22, [("AAA.L", "buy", 105.0)]),
        _snap(29, [("AAA.L", "buy", 110.0)]),
        _snap(5, [("AAA.L", "buy", 115.0)], month=2),
        _snap(12, [("AAA.L", "hold", 120.0)], month=2),
    ]
    cfg = N200Config(buy_cost_pct=0.001, sell_cost_pct=0.001)
    payload = build_n200_observe(snaps, cfg=cfg)
    path = payload["path_scoreboard"]["control_smooth_ret_cohort_median"]
    assert path is not None and path > 0
    entry = payload["entry_lever_scoreboard"]
    assert entry["verdict"] == "lose"
    assert entry["control_is_best_feasible"] is False
    assert entry["best_alt_offset_days"] == -14
    assert entry["cost_basis"] == "fair_market_table"
    ep = payload["episodes_sample"][0]
    assert ep["control_return"] > 0
    assert ep["entry_lever"]["verdict"] == "lose"
    assert payload["per_lever_scoreboards"]["entry_verdict"] == "lose"
    # Path profit must not flip lever verdict.
    assert payload["per_lever_scoreboards"]["path_control_smooth_ret_cohort_median"] == path


def test_exit_lever_independent_of_path_pnl():
    """Exit lever scored with control entry; can disagree with path sign."""
    # Rising then falling: early exit (-14d) better; control exit still +ve path.
    snaps = [
        _snap(1, [("AAA.L", "hold", 100.0)]),
        _snap(8, [("AAA.L", "hold", 100.0)]),
        _snap(15, [("AAA.L", "buy", 100.0)]),
        _snap(22, [("AAA.L", "buy", 130.0)]),
        _snap(29, [("AAA.L", "buy", 125.0)]),  # peak-ish — -14d from leave
        _snap(5, [("AAA.L", "buy", 118.0)], month=2),
        _snap(12, [("AAA.L", "hold", 110.0)], month=2),  # control exit still profit
    ]
    cfg = N200Config(buy_cost_pct=0.001, sell_cost_pct=0.001)
    payload = build_n200_observe(snaps, cfg=cfg)
    path = payload["path_scoreboard"]["control_smooth_ret_cohort_median"]
    assert path is not None and path > 0
    exit_sb = payload["exit_lever_scoreboard"]
    assert exit_sb["verdict"] == "lose"
    assert exit_sb["best_alt_offset_days"] == -14
    assert exit_sb["independent_of_path_pnl"] is True
    assert exit_sb["cost_basis"] == "fair_market_table"
