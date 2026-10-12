"""Tests for sealed N201 observe-only short-horizon value+momentum."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from value_investor.backtest import RunSnapshot
from value_investor.market_trading_costs import (
    LEGACY_STRESS_TRADE_COST_PCT,
    costs_for_market,
)
from value_investor.n201_value_mom_observe import (
    ELIGIBILITY_MODE,
    FINDING_TITLE,
    FIXED_STAKE_UNITS,
    HOLD_TRADING_DAYS,
    PATIENT_HOLD_BASELINE,
    REGISTRATION_ID,
    SEAL_MARKER_ID,
    VOLUME_GATE_TITLE,
    VOLUME_MIN_EPISODES,
    VOLUME_MIN_WEEKS,
    N201Config,
    _earnings_yield,
    _financial_health_pass,
    build_n201_observe,
    build_n201_pipeline_health_projection,
    build_registration_payload,
    episode_return,
    fixed_stake_pnl,
    load_library_market_snapshots,
    ops_findings_from_n201_observe,
    refresh_n201_value_mom_observe,
    row_f9_eligible,
    trading_days_between,
)


def _row(
    ticker: str,
    *,
    ey: float | None,
    mom: float | None,
    fh: bool | None,
    price: float,
    market_id: str = "ftse350",
) -> tuple[dict, float]:
    sig: dict = {"ticker": ticker, "signal": "hold", "market_id": market_id}
    if ey is not None:
        sig["earnings_yield"] = ey
    if mom is not None:
        sig["momentum_12_1"] = mom
    if fh is not None:
        sig["financial_health_pass"] = fh
    return sig, price


def _snap(day: int, rows: list[tuple[dict, float]], *, month: int = 1) -> RunSnapshot:
    signals = [r for r, _ in rows]
    prices = {str(r["ticker"]): p for r, p in rows}
    return RunSnapshot(
        run_at=f"2026-{month:02d}-{day:02d}T12:00:00+00:00",
        prices=prices,
        signals=signals,
    )


def test_episode_return_and_fixed_stake_pnl_independent_of_nav():
    fair = costs_for_market("ftse350")
    ret = episode_return(100.0, 110.0, buy_cost_pct=fair.buy_pct, sell_cost_pct=fair.sell_pct)
    stake_a = fixed_stake_pnl(
        100.0, 110.0, stake_units=100.0, buy_cost_pct=fair.buy_pct, sell_cost_pct=fair.sell_pct
    )
    stake_b = fixed_stake_pnl(
        100.0, 110.0, stake_units=10_000.0, buy_cost_pct=fair.buy_pct, sell_cost_pct=fair.sell_pct
    )
    # Scoreboard unit is % — stake size must not change return_pct.
    assert abs(stake_a["return_pct"] - ret) < 1e-12
    assert abs(stake_b["return_pct"] - ret) < 1e-12
    assert stake_a["return_pct"] == stake_b["return_pct"]
    assert stake_a["pnl_local"] != stake_b["pnl_local"]


def test_registration_invariants_seal_fields():
    reg = build_registration_payload(sealed_at="2026-10-12")
    assert reg["registration_id"] == REGISTRATION_ID
    assert reg["deferred_id"] == "N201"
    assert reg["status"] == "sealed_observe_only"
    assert reg["observe_only"] is True
    assert reg["influences_live"] is False
    assert reg["independent_of_n200"] is True
    assert reg["sizing"]["mode"] == "fixed_stake"
    assert reg["sizing"]["stake_units"] == FIXED_STAKE_UNITS
    assert reg["sizing"]["cash_fund_nav"] == "parked"
    assert reg["sizing"]["scoreboard_unit"] == "fair_cost_episode_pct"
    assert reg["exit"]["hold_trading_days"] == HOLD_TRADING_DAYS
    assert reg["o3_volume_gate"]["completed_entry_episodes_min"] == VOLUME_MIN_EPISODES
    assert reg["o3_volume_gate"]["calendar_weeks_spanned_min"] == VOLUME_MIN_WEEKS
    assert reg["o3_volume_gate"]["rule"] == "both_required"
    assert reg["o5_primacy"]["primary"] == "absolute_smoothed_return_fair_costs"
    assert reg["o5_primacy"]["patient_hold_excess"] == "report_only"
    assert reg["o5_primacy"]["stress_cost"] == "report_only"
    assert reg["o6_phase_floor"]["entries_per_week_target"] == 8.0
    assert reg["eligibility_mode"] == ELIGIBILITY_MODE
    assert reg["patient_hold_baseline"]["id"] == PATIENT_HOLD_BASELINE["id"]
    assert reg["patient_hold_baseline"]["momentum_filter"] is False
    assert reg["universe"]["fx_conversion"] is False
    assert reg["launch_queue"]["enqueued"] is True
    assert "fixed_stake_not_fund_nav" in reg["constraints"]
    assert "independent_of_n200" in reg["constraints"]
    assert reg["cost_basis"]["primary"] == "fair_market_table"
    assert reg["stress_trade_cost_pct"] == LEGACY_STRESS_TRADE_COST_PCT
    assert reg["exit"]["archive_trading_day_proxy"] == "session_calendar_or_busday_holidays"


def test_earnings_yield_from_key_metrics_pe():
    assert _earnings_yield({"key_metrics": {"P/E": "12.5"}}) == pytest.approx(1.0 / 12.5)
    assert _earnings_yield({"trailing_pe": 10.0}) == pytest.approx(0.1)
    assert _earnings_yield({"earnings_yield_pe": 0.08}) == pytest.approx(0.08)


def test_financial_health_from_passed_models_display_name():
    assert _financial_health_pass({"passed_models": ["Financial Health", "Magic Formula"]}) is True
    assert _financial_health_pass({"failed_models": ["Financial Health"]}) is False
    # Enumerated passed_models without FH → fail (enriched archive row).
    assert (
        _financial_health_pass(
            {"passed_models": ["Earnings Yield"], "failed_models": ["Financial Health"]}
        )
        is False
    )
    assert _financial_health_pass({"ticker": "AAA.L"}) is None


def test_trading_days_between_skips_weekend_and_uk_holiday():
    # 2026-04-02 (Thu) → 2026-04-07 (Tue) includes Good Friday 2026-04-03 + Easter Monday 2026-04-06.
    days = trading_days_between(
        "2026-04-02T12:00:00+00:00",
        "2026-04-07T12:00:00+00:00",
        market_id="ftse350",
    )
    # Fri+Mon holidays, Sat+Sun weekend → only Tue 2026-04-07 counts in (start, end].
    assert days == 1


def test_trading_days_between_prefers_session_calendar():
    from datetime import date

    sessions = {date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)}
    days = trading_days_between(
        "2026-01-01T00:00:00+00:00",
        "2026-01-06T00:00:00+00:00",
        sessions=sessions,
    )
    assert days == 3


def test_row_f9_eligible_pass_and_fail():
    ok, note = row_f9_eligible({"ticker": "AAA.L"})
    assert ok and "or_pass" in note
    bad, reason = row_f9_eligible({"key_filing_bodies": False})
    assert not bad and "key_filing_bodies" in reason


def test_build_n201_observe_scores_fixed_stake_fair_primary():
    # 10 names with EY so top-30% is well-defined; AAA clears EY+mom+FH.
    def cohort(aaa_price: float, aaa_ey: float = 0.12, aaa_mom: float = 0.05, aaa_fh: bool = True):
        rows = [_row("AAA.L", ey=aaa_ey, mom=aaa_mom, fh=aaa_fh, price=aaa_price)]
        # Fill 9 others below AAA on EY (AAA in top 30% of 10 → top 3).
        for i in range(9):
            rows.append(
                _row(
                    f"Z{i}.L",
                    ey=0.01 + i * 0.001,
                    mom=0.02,
                    fh=True,
                    price=50.0 + i,
                )
            )
        return rows

    # Entry week 1; hold ~13 calendar weeks (~65 trading weekdays) to clear 63d.
    snaps = [
        _snap(1, cohort(100.0), month=1),
        _snap(8, cohort(102.0), month=1),
        _snap(15, cohort(104.0), month=1),
        _snap(22, cohort(106.0), month=1),
        _snap(1, cohort(108.0), month=2),
        _snap(8, cohort(110.0), month=2),
        _snap(15, cohort(112.0), month=2),
        _snap(22, cohort(114.0), month=2),
        _snap(1, cohort(116.0), month=3),
        _snap(8, cohort(118.0), month=3),
        _snap(15, cohort(120.0), month=3),  # ~73 calendar days / ~52+ weekdays
        _snap(22, cohort(122.0), month=3),
        _snap(29, cohort(124.0), month=3),
        _snap(5, cohort(126.0), month=4),
    ]
    payload = build_n201_observe(
        snaps,
        cfg=N201Config(fetch_momentum_prices=False),
        generated_at="2026-10-12T00:00:00+00:00",
    )
    assert payload["registration_id"] == REGISTRATION_ID
    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    assert payload["independent_of_n200"] is True
    assert payload["sizing"]["independent_of_fund_nav"] is True
    assert payload["completed_entry_episodes"] >= 1
    med = payload["path_scoreboard"]["smooth_ret_cohort_median"]
    assert med is not None
    ep = payload["episodes_sample"][0]
    assert ep["ticker"] == "AAA.L"
    assert ep["fixed_stake_units"] == FIXED_STAKE_UNITS
    assert ep["independent_of_fund_nav"] is True
    assert ep["scoreboard_unit"] == "fair_cost_episode_pct"
    assert ep["exit_reason"] in {
        "hold_trading_days",
        "identity_break_ey_band",
        "quality_break_financial_health",
    }
    assert ep["hold_trading_days"] >= HOLD_TRADING_DAYS or ep["exit_reason"] != "hold_trading_days"
    assert payload["cost_basis"]["primary"] == "fair_market_table"
    assert payload["path_scoreboard"]["independent_of_fund_nav"] is True
    marker_ids = [m["marker_id"] for m in payload["change_markers"]]
    assert SEAL_MARKER_ID in marker_ids
    assert payload["patient_hold_baseline"]["momentum_filter"] is False


def test_scoring_independent_of_fund_nav_cfg_stake():
    """Changing stake units must not change cohort median %."""
    rows_entry = [
        _row("AAA.L", ey=0.20, mom=0.10, fh=True, price=100.0),
        _row("BBB.L", ey=0.01, mom=0.10, fh=True, price=50.0),
        _row("CCC.L", ey=0.02, mom=0.10, fh=True, price=50.0),
    ]
    rows_exit = [
        _row("AAA.L", ey=0.20, mom=0.10, fh=True, price=110.0),
        _row("BBB.L", ey=0.01, mom=0.10, fh=True, price=50.0),
        _row("CCC.L", ey=0.02, mom=0.10, fh=True, price=50.0),
    ]
    # Spaced ~14 weeks apart so weekday hold clears 63.
    snaps = [
        _snap(1, rows_entry, month=1),
        _snap(1, rows_exit, month=4),
    ]
    a = build_n201_observe(
        snaps, cfg=N201Config(fixed_stake_units=100.0, fetch_momentum_prices=False)
    )
    b = build_n201_observe(
        snaps, cfg=N201Config(fixed_stake_units=9999.0, fetch_momentum_prices=False)
    )
    assert a["completed_entry_episodes"] == b["completed_entry_episodes"] == 1
    assert (
        a["path_scoreboard"]["smooth_ret_cohort_median"]
        == b["path_scoreboard"]["smooth_ret_cohort_median"]
    )
    assert a["episodes_sample"][0]["return_pct"] == b["episodes_sample"][0]["return_pct"]
    assert (
        a["episodes_sample"][0]["pnl_local_report_only"]
        != b["episodes_sample"][0]["pnl_local_report_only"]
    )


def test_skips_missing_entry_fields_soft_gap():
    # AAA has no EY/mom/FH — cannot enter; BBB has full fields but weak EY.
    snaps = [
        _snap(
            1,
            [
                ({"ticker": "AAA.L", "signal": "hold"}, 100.0),
                _row("BBB.L", ey=0.01, mom=0.05, fh=True, price=50.0),
            ],
        ),
        _snap(
            1,
            [
                ({"ticker": "AAA.L", "signal": "hold"}, 110.0),
                _row("BBB.L", ey=0.01, mom=0.05, fh=True, price=55.0),
            ],
            month=4,
        ),
    ]
    payload = build_n201_observe(snaps, cfg=N201Config(fetch_momentum_prices=False))
    # Single-name EY universe: BBB is top 30% of itself, but AAA never enters.
    assert all(ep["ticker"] != "AAA.L" for ep in payload["episodes_sample"])


def test_refresh_persists_registration_and_store(tmp_path: Path):
    hist = tmp_path / "history"
    hist.mkdir()
    snap = {
        "run_at": "2026-01-01T12:00:00+00:00",
        "prices": {"AAA.L": 100.0, "BBB.L": 50.0, "CCC.L": 50.0},
        "signals": [
            {
                "ticker": "AAA.L",
                "earnings_yield": 0.2,
                "momentum_12_1": 0.1,
                "financial_health_pass": True,
                "market_id": "ftse350",
            },
            {
                "ticker": "BBB.L",
                "earnings_yield": 0.01,
                "momentum_12_1": 0.1,
                "financial_health_pass": True,
            },
            {
                "ticker": "CCC.L",
                "earnings_yield": 0.02,
                "momentum_12_1": 0.1,
                "financial_health_pass": True,
            },
        ],
    }
    (hist / "run_20260101.json").write_text(json.dumps(snap), encoding="utf-8")
    snap2 = {
        "run_at": "2026-04-01T12:00:00+00:00",
        "prices": {"AAA.L": 110.0, "BBB.L": 50.0, "CCC.L": 50.0},
        "signals": snap["signals"],
    }
    (hist / "run_20260401.json").write_text(json.dumps(snap2), encoding="utf-8")

    store = tmp_path / "n201_value_mom_observe.json"
    reg = tmp_path / "n201_value_mom_registration.json"
    payload = refresh_n201_value_mom_observe(
        output_dir=tmp_path,
        store_path=store,
        registration_path=reg,
        persist=True,
        include_admitted_markets=False,
        cfg=N201Config(fetch_momentum_prices=False),
    )
    assert store.is_file()
    assert reg.is_file()
    saved_reg = json.loads(reg.read_text(encoding="utf-8"))
    assert saved_reg["registration_id"] == REGISTRATION_ID
    assert saved_reg["status"] == "sealed_observe_only"
    assert saved_reg["independent_of_n200"] is True
    assert saved_reg["sizing"]["stake_units"] == 100.0
    assert payload["completed_entry_episodes"] == 1
    assert SEAL_MARKER_ID in [m["marker_id"] for m in payload["change_markers"]]
    assert saved_reg["exit"]["archive_trading_day_proxy"] == ("session_calendar_or_busday_holidays")


def test_load_library_market_snapshots_enriches_ey_and_fh(tmp_path: Path):
    import gzip

    screen = tmp_path / "markets" / "sp500" / "screen"
    history = screen / "history"
    history.mkdir(parents=True)
    (screen / "signals_20261001_120000.csv").write_text(
        "ticker,signal,earnings_yield_pe,last_price\nAAA,hold,0.12,100.0\nBBB,hold,0.02,50.0\n",
        encoding="utf-8",
    )
    models = {
        "run_at": "2026-10-01T12:00:00+00:00",
        "models": [
            {"ticker": "AAA", "model_id": "financial_health", "passed": True, "score": 1.0},
            {"ticker": "BBB", "model_id": "financial_health", "passed": False, "score": 0.0},
        ],
    }
    with gzip.open(history / "models_20261001_120000.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(models, fh)

    snaps = load_library_market_snapshots(tmp_path, "sp500")
    assert len(snaps) == 1
    by_ticker = {r["ticker"]: r for r in snaps[0].signals}
    assert by_ticker["AAA"]["earnings_yield_pe"] == pytest.approx(0.12)
    assert by_ticker["AAA"]["financial_health_pass"] is True
    assert by_ticker["BBB"]["financial_health_pass"] is False
    assert by_ticker["AAA"]["market_id"] == "sp500"


def test_ops_findings_volume_gate():
    base = build_n201_observe([])
    base["completed_entry_episodes"] = 50
    base["calendar_weeks_spanned"] = 10
    base["volume_gate"] = {"met": True, "min_episodes": 48, "min_weeks": 8}
    base["phase"] = {"entries_per_week": 9.0, "floor": 8.0, "floor_met": True}
    base["path_scoreboard"] = {
        "smooth_ret_cohort_median": 0.01,
        "smooth_ret_cohort_median_stress_report_only": -0.05,
        "patient_hold_excess_report_only": 0.002,
    }
    findings = ops_findings_from_n201_observe(base)
    titles = {f["title"] for f in findings}
    assert FINDING_TITLE in titles
    assert VOLUME_GATE_TITLE in titles
    assert all(f["auto_fixable"] is False for f in findings)
    refresh = next(f for f in findings if f["title"] == FINDING_TITLE)
    assert "independent of fund NAV" in refresh["summary"]
    assert "fair costs primary" in refresh["summary"]


def test_pipeline_health_projection():
    store = {
        "registration_id": REGISTRATION_ID,
        "deferred_id": "N201",
        "generated_at": "2026-10-12T12:00:00+00:00",
        "completed_entry_episodes": 10,
        "calendar_weeks_spanned": 4,
        "phase": {"entries_per_week": 2.5, "floor": 8.0, "floor_met": False},
        "volume_gate": {"met": False, "min_episodes": 48, "min_weeks": 8},
        "path_scoreboard": {"smooth_ret_cohort_median": 0.01},
    }
    proj = build_n201_pipeline_health_projection(
        store,
        ops_status={"run_at": "2026-10-12T12:30:00+00:00", "findings": [{"title": FINDING_TITLE}]},
        now=__import__("datetime").datetime(2026, 10, 12, 13, 0, tzinfo=__import__("datetime").UTC),
    )
    assert proj["observe_only"] is True
    assert proj["launch_queue_waiter"] is True
    assert proj["independent_of_fund_nav"] is True
    assert proj["not_capital_ready"] is True
    assert proj["volume_gate"]["min_episodes"] == 48
