"""Tests for sealed N210 B3 fixed-stake AI/filter judgment episode walker."""

from __future__ import annotations

from pathlib import Path

from value_investor.backtest import RunSnapshot
from value_investor.market_trading_costs import (
    LEGACY_STRESS_TRADE_COST_PCT,
    costs_for_market,
)
from value_investor.n210_ai_judgment_observe import (
    DEFERRED_ID,
    FINDING_TITLE,
    FIXED_STAKE_UNITS,
    HOLD_TRADING_DAYS,
    MIN_CONVICTION,
    PIPELINE_STATUS,
    REGISTRATION_ID,
    STUB_PIPELINE_STATUS,
    STUB_TITLE,
    VOLUME_MIN_EPISODES,
    VOLUME_MIN_WEEKS,
    WALKER_MARKER_ID,
    N210Config,
    _entry_filter_state,
    build_n210_observe,
    build_n210_pipeline_health_projection,
    build_registration_payload,
    episode_return,
    fixed_stake_pnl,
    ops_findings_from_n210_observe,
    refresh_n210_ai_judgment_observe,
    row_f9_eligible,
)


def _row(
    ticker: str,
    *,
    price: float,
    signal: str = "buy",
    adjusted_signal: str | None = "buy",
    research_verdict: str | None = "accumulate",
    conviction: float | None = 0.8,
    timing: str | None = None,
) -> tuple[dict, float]:
    sig: dict = {
        "ticker": ticker,
        "signal": signal,
        "market_id": "ftse350",
    }
    if adjusted_signal is not None:
        sig["adjusted_signal"] = adjusted_signal
    if research_verdict is not None:
        sig["research_verdict"] = research_verdict
    if conviction is not None:
        sig["conviction_score"] = conviction
    if timing is not None:
        sig["timing_signal"] = timing
    return sig, price


def _snap(day: int, rows: list[tuple[dict, float]], *, month: int = 1) -> RunSnapshot:
    signals = [r for r, _ in rows]
    prices = {str(r["ticker"]): p for r, p in rows}
    return RunSnapshot(
        run_at=f"2026-{month:02d}-{day:02d}T12:00:00+00:00",
        prices=prices,
        signals=signals,
    )


def test_registration_payload_fixed_stake_and_gates():
    reg = build_registration_payload()
    assert reg["registration_id"] == REGISTRATION_ID
    assert reg["deferred_id"] == DEFERRED_ID
    assert reg["observe_only"] is True
    assert reg["influences_live"] is False
    assert reg["pipeline_status"] == PIPELINE_STATUS
    assert reg["pipeline_status"] != STUB_PIPELINE_STATUS
    assert reg["sizing"]["mode"] == "fixed_stake"
    assert reg["sizing"]["stake_units"] == 100.0
    assert reg["sizing"]["scoreboard_unit"] == "fair_cost_episode_pct"
    assert reg["sizing"]["cash_fund_nav"] == "parked"
    assert reg["entry_filters"]["min_conviction"] == MIN_CONVICTION
    assert reg["entry_filters"]["use_adjusted_signal"] is True
    assert reg["entry_filters"]["require_research_accumulate"] is True
    assert reg["exit"]["hold_trading_days"] == HOLD_TRADING_DAYS
    assert reg["o3_volume_gate"]["completed_entry_episodes_min"] == VOLUME_MIN_EPISODES
    assert reg["o3_volume_gate"]["calendar_weeks_spanned_min"] == VOLUME_MIN_WEEKS
    assert "f8_fail_closed" in reg["constraints"]
    assert "o3_alone_first" in reg["constraints"]
    assert "no_matched30_touch" in reg["constraints"]
    assert "fixed_stake_not_fund_nav" in reg["constraints"]
    assert reg["stress_trade_cost_pct"] == LEGACY_STRESS_TRADE_COST_PCT


def test_entry_filter_admission_and_rejects():
    ok, note, detail = _entry_filter_state(
        {
            "signal": "hold",
            "adjusted_signal": "buy",
            "research_verdict": "accumulate",
            "conviction_score": 0.7,
        },
        use_adjusted_signal=True,
        require_research_accumulate=True,
        min_conviction=0.6,
    )
    assert ok and note == "entry_filters_clear"
    assert detail["signal"] == "buy"

    bad_conv, note_conv, _ = _entry_filter_state(
        {
            "signal": "buy",
            "adjusted_signal": "buy",
            "research_verdict": "accumulate",
            "conviction_score": 0.4,
        },
        use_adjusted_signal=True,
        require_research_accumulate=True,
        min_conviction=0.6,
    )
    assert not bad_conv and note_conv == "conviction_below_floor"

    bad_verdict, note_v, _ = _entry_filter_state(
        {
            "signal": "buy",
            "adjusted_signal": "buy",
            "research_verdict": "caution",
            "conviction_score": 0.9,
        },
        use_adjusted_signal=True,
        require_research_accumulate=True,
        min_conviction=0.6,
    )
    assert not bad_verdict and note_v == "research_not_accumulate"

    soft, note_s, _ = _entry_filter_state(
        {
            "signal": "buy",
            "adjusted_signal": "buy",
            "research_verdict": "accumulate",
        },
        use_adjusted_signal=True,
        require_research_accumulate=True,
        min_conviction=0.6,
    )
    assert not soft and note_s == "soft_gap_missing_conviction"


def test_fixed_stake_return_independent_of_stake_size():
    fair = costs_for_market("ftse350")
    ret = episode_return(100.0, 110.0, buy_cost_pct=fair.buy_pct, sell_cost_pct=fair.sell_pct)
    a = fixed_stake_pnl(
        100.0, 110.0, stake_units=100.0, buy_cost_pct=fair.buy_pct, sell_cost_pct=fair.sell_pct
    )
    b = fixed_stake_pnl(
        100.0, 110.0, stake_units=10_000.0, buy_cost_pct=fair.buy_pct, sell_cost_pct=fair.sell_pct
    )
    assert abs(a["return_pct"] - ret) < 1e-12
    assert a["return_pct"] == b["return_pct"]
    assert a["pnl_local"] != b["pnl_local"]


def test_row_f9_eligible_pass_and_fail():
    ok, note = row_f9_eligible({"ticker": "AAA.L"})
    assert ok and "or_pass" in note
    bad, reason = row_f9_eligible({"key_filing_bodies": False})
    assert not bad and "key_filing_bodies" in reason


def test_build_n210_observe_progressive_fixed_stake_no_live_influence():
    def cohort(aaa_price: float, *, aaa_clear: bool = True):
        rows = [
            _row(
                "AAA.L",
                price=aaa_price,
                adjusted_signal="buy" if aaa_clear else "hold",
                research_verdict="accumulate" if aaa_clear else "caution",
                conviction=0.85 if aaa_clear else 0.2,
            ),
            _row(
                "BBB.L",
                price=50.0,
                signal="buy",
                adjusted_signal="hold",
                research_verdict="neutral",
                conviction=0.3,
            ),
            _row(
                "CCC.L",
                price=40.0,
                signal="buy",
                adjusted_signal=None,
                research_verdict=None,
                conviction=None,
            ),
        ]
        return rows

    # Progressive: AAA clears on week 1, holds through ~14 calendar weeks.
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
        _snap(15, cohort(120.0), month=3),
        _snap(22, cohort(122.0), month=3),
        _snap(29, cohort(124.0), month=3),
        _snap(5, cohort(126.0), month=4),
    ]
    payload = build_n210_observe(
        snaps,
        cfg=N210Config(),
        generated_at="2026-10-15T12:00:00+00:00",
    )
    assert payload["registration_id"] == REGISTRATION_ID
    assert payload["pipeline_status"] == PIPELINE_STATUS
    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    assert payload["independent_of_fund_nav"] is True
    assert payload["sizing"]["mode"] == "fixed_stake"
    assert payload["sizing"]["stake_units"] == FIXED_STAKE_UNITS
    assert payload["completed_entry_episodes"] >= 1
    assert payload["open_entry_episodes"] == 0 or isinstance(payload["open_entry_episodes"], int)
    med = payload["path_scoreboard"]["smooth_ret_cohort_median"]
    assert med is not None
    ep = payload["episodes_sample"][0]
    assert ep["ticker"] == "AAA.L"
    assert ep["fixed_stake_units"] == FIXED_STAKE_UNITS
    assert ep["influences_live"] is False
    assert ep["independent_of_fund_nav"] is True
    assert ep["scoreboard_unit"] == "fair_cost_episode_pct"
    assert ep["exit_reason"] in {
        "hold_trading_days",
        "identity_break_not_buy_tier",
        "identity_break_research_not_accumulate",
        "identity_break_conviction_below_floor",
        "identity_break_missing_row",
    }
    marker_ids = {m.get("id") or m.get("marker_id") for m in payload["change_markers"]}
    assert WALKER_MARKER_ID in marker_ids
    # Control cohort should score raw buy-tier names (BBB/CCC) report-only.
    assert payload["control_completed_entry_episodes_report_only"] >= 1
    assert (
        payload["path_scoreboard"]["unfiltered_buy_tier_smooth_ret_cohort_median_report_only"]
        is not None
    )


def test_progressive_entries_not_fund_sleeve_rebuy():
    """First sighting clears are entries; still-clear names do not re-enter.

    Anti day-0 fund sleeve: each entry is a fixed 100 stake episode, not an
    equal-weight NAV fill of the whole clear set.
    """
    clear = [
        _row("AAA.L", price=100.0),
        _row(
            "ZZZ.L",
            price=10.0,
            signal="hold",
            adjusted_signal="hold",
            research_verdict="pass",
            conviction=0.1,
        ),
    ]
    still_clear = [
        _row("AAA.L", price=105.0),
        _row(
            "ZZZ.L",
            price=10.0,
            signal="hold",
            adjusted_signal="hold",
            research_verdict="pass",
            conviction=0.1,
        ),
    ]
    newly = [
        _row("BBB.L", price=50.0),
        _row("AAA.L", price=110.0),
        _row(
            "ZZZ.L",
            price=10.0,
            signal="hold",
            adjusted_signal="hold",
            research_verdict="pass",
            conviction=0.1,
        ),
    ]
    snaps = [
        _snap(1, clear, month=1),
        _snap(8, still_clear, month=1),
        _snap(15, newly, month=1),  # BBB newly clears; AAA still clear → no rebuy
        _snap(22, newly, month=1),
        _snap(1, newly, month=2),
        _snap(8, newly, month=2),
        _snap(15, newly, month=2),
        _snap(22, newly, month=2),
        _snap(1, newly, month=3),
        _snap(8, newly, month=3),
        _snap(15, newly, month=3),
        _snap(22, newly, month=3),
        _snap(29, newly, month=3),
        _snap(5, newly, month=4),
        _snap(12, newly, month=4),
        _snap(19, newly, month=4),
    ]
    payload = build_n210_observe(snaps, cfg=N210Config())
    tickers = [e["ticker"] for e in payload["episodes_sample"]]
    assert "AAA.L" in tickers  # first-sighting progressive entry
    assert "BBB.L" in tickers  # newly clears later
    assert tickers.count("AAA.L") == 1  # no rebuy while still clear
    for ep in payload["episodes_sample"]:
        assert ep["fixed_stake_units"] == FIXED_STAKE_UNITS
        assert ep["influences_live"] is False
    assert payload["sizing"]["cash_fund_nav"] == "parked"


def test_open_episodes_tracked_before_hold_completes():
    snaps = [
        _snap(1, [_row("AAA.L", price=100.0)], month=1),
        _snap(8, [_row("AAA.L", price=101.0)], month=1),
    ]
    payload = build_n210_observe(snaps, cfg=N210Config())
    assert payload["completed_entry_episodes"] == 0
    assert payload["open_entry_episodes"] == 1
    assert payload["open_episodes_sample"][0]["ticker"] == "AAA.L"
    assert payload["influences_live"] is False


def test_scoring_independent_of_fund_nav_cfg_stake():
    rows_entry = [
        _row("AAA.L", price=100.0),
        _row(
            "BBB.L",
            price=50.0,
            signal="hold",
            adjusted_signal="hold",
            research_verdict="pass",
            conviction=0.1,
        ),
    ]
    rows_exit = [
        _row("AAA.L", price=110.0),
        _row(
            "BBB.L",
            price=50.0,
            signal="hold",
            adjusted_signal="hold",
            research_verdict="pass",
            conviction=0.1,
        ),
    ]
    snaps = [
        _snap(1, rows_entry, month=1),
        _snap(1, rows_exit, month=4),
    ]
    a = build_n210_observe(snaps, cfg=N210Config(fixed_stake_units=100.0))
    b = build_n210_observe(snaps, cfg=N210Config(fixed_stake_units=10_000.0))
    assert (
        a["path_scoreboard"]["smooth_ret_cohort_median"]
        == b["path_scoreboard"]["smooth_ret_cohort_median"]
    )


def test_refresh_persists_walker_store(tmp_path: Path):
    store = tmp_path / "n210_ai_judgment_observe.json"
    reg_path = tmp_path / "n210_ai_judgment_registration.json"
    # Empty history still produces walker-active payload (0 episodes).
    payload = refresh_n210_ai_judgment_observe(
        output_dir=tmp_path,
        store_path=store,
        registration_path=reg_path,
        persist=True,
    )
    assert store.exists()
    assert reg_path.exists()
    assert payload["pipeline_status"] == PIPELINE_STATUS
    assert payload["influences_live"] is False
    assert payload["volume_gate"]["met"] is False
    assert payload["path_scoreboard"]["scoreboard_unit"] == "fair_cost_episode_pct"
    # Stub finding must not fire on active walker.
    titles = {f["title"] for f in ops_findings_from_n210_observe(payload)}
    assert FINDING_TITLE in titles
    assert STUB_TITLE not in titles
    assert all(f["auto_fixable"] is False for f in ops_findings_from_n210_observe(payload))


def test_ops_findings_stub_only_when_legacy_pipeline():
    payload = {
        "pipeline_status": STUB_PIPELINE_STATUS,
        "completed_entry_episodes": 0,
        "calendar_weeks_spanned": 0,
        "volume_gate": {"met": False},
    }
    titles = {f["title"] for f in ops_findings_from_n210_observe(payload)}
    assert STUB_TITLE in titles
    assert FINDING_TITLE in titles


def test_ops_volume_gate_finding_when_met():
    payload = {
        "pipeline_status": PIPELINE_STATUS,
        "completed_entry_episodes": VOLUME_MIN_EPISODES,
        "calendar_weeks_spanned": VOLUME_MIN_WEEKS,
        "volume_gate": {"met": True},
    }
    findings = ops_findings_from_n210_observe(payload)
    assert any(f["title"] == "N210 volume gate ready for review" for f in findings)
    assert all(f["auto_fixable"] is False for f in findings)


def test_pipeline_health_projection_thin_marks_walker_alive():
    """0 completed + open > 0 is honest functioning — not assessment primary."""
    from datetime import UTC, datetime

    store = {
        "registration_id": REGISTRATION_ID,
        "deferred_id": DEFERRED_ID,
        "generated_at": "2026-10-15T12:00:00+00:00",
        "pipeline_status": PIPELINE_STATUS,
        "completed_entry_episodes": 0,
        "open_entry_episodes": 3,
        "calendar_weeks_spanned": 9,
        "phase": {"entries_per_week": 0.0, "floor": 8.0, "floor_met": False},
        "volume_gate": {"met": False, "min_episodes": 48, "min_weeks": 8},
        "path_scoreboard": {
            "smooth_ret_cohort_median": None,
            "open_entry_episodes": 3,
            "completed_entry_episodes": 0,
            "companions": {"volume_toward_gate": "0/48", "open_episodes": 3},
        },
    }
    proj = build_n210_pipeline_health_projection(
        store,
        ops_status={
            "run_at": "2026-10-15T12:30:00+00:00",
            "findings": [{"title": FINDING_TITLE}],
        },
        now=datetime(2026, 10, 15, 13, 0, tzinfo=UTC),
    )
    assert proj["observe_only"] is True
    assert proj["influences_live"] is False
    assert proj["not_assessment_primary"] is True
    assert proj["not_capital_ready"] is True
    assert proj["launch_queue_waiter"] is True
    assert proj["independent_of_fund_nav"] is True
    assert proj["walker_active"] is True
    assert proj["stub_gone"] is True
    assert proj["pipeline_status"] == PIPELINE_STATUS
    assert proj["volume_gate"]["episodes"] == 0
    assert proj["volume_gate"]["open_episodes"] == 3
    assert proj["volume_gate"]["min_episodes"] == 48
    assert proj["pipeline"]["functioning"] is True
    assert "thin marks" in proj["headline"].lower() or "0 completed" in proj["headline"]
    assert proj["path_scoreboard"]["smooth_ret_cohort_median"] is None


def test_pipeline_health_projection_missing_store():
    from datetime import UTC, datetime

    proj = build_n210_pipeline_health_projection(
        None,
        store_path=Path("/nonexistent/n210_ai_judgment_observe.json"),
        ops_status={"run_at": "2026-10-15T12:00:00+00:00", "findings": []},
        now=datetime(2026, 10, 15, 13, 0, tzinfo=UTC),
    )
    assert proj["store_present"] is False
    assert proj["pipeline"]["functioning"] is False
    assert proj["not_assessment_primary"] is True
    assert "missing" in proj["headline"].lower()
