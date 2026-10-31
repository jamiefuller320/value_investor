"""Tests for sealed N206 patient plain earnings-yield observe."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.backtest import RunSnapshot
from value_investor.market_trading_costs import LEGACY_STRESS_TRADE_COST_PCT
from value_investor.n201_value_mom_observe import N201Config
from value_investor.n206_plain_ey_observe import (
    FINDING_TITLE,
    FIXED_STAKE_UNITS,
    REGISTRATION_ID,
    INTERESTINGNESS_TITLE,
    VOLUME_GATE_TITLE,
    build_n206_pipeline_health_projection,
    build_registration_payload,
    ops_findings_from_n206_observe,
    refresh_n206_plain_ey_observe,
    score_plain_ey_hold,
)


def _row(
    ticker: str,
    *,
    ey: float | None,
    mom: float | None,
    fh: bool | None,
    price: float,
) -> tuple[dict, float]:
    sig: dict = {"ticker": ticker, "signal": "hold", "market_id": "ftse350"}
    if ey is not None:
        sig["earnings_yield"] = ey
    if mom is not None:
        sig["momentum_12_1"] = mom
    if fh is not None:
        sig["financial_health_pass"] = fh
    return sig, price


def _snap(day: int, rows: list[tuple[dict, float]]) -> RunSnapshot:
    signals = [r for r, _ in rows]
    prices = {str(r["ticker"]): p for r, p in rows}
    return RunSnapshot(
        run_at=f"2026-01-{day:02d}T12:00:00+00:00",
        prices=prices,
        signals=signals,
    )


def test_registration_is_observe_only_plain_ey():
    reg = build_registration_payload(sealed_at="2026-10-16")
    assert reg["registration_id"] == REGISTRATION_ID
    assert reg["deferred_id"] == "N206"
    assert reg["observe_only"] is True
    assert reg["influences_live"] is False
    assert reg["alone_first"] is True
    assert reg["entry_filters"]["momentum_filter"] is False
    assert reg["entry_filters"]["financial_health"] == "pass"
    assert reg["sizing"]["mode"] == "fixed_stake"
    assert reg["sizing"]["stake_units"] == FIXED_STAKE_UNITS
    assert reg["sizing"]["cash_fund_nav"] == "parked"
    assert reg["filing_ingest_sprint"] is False
    assert reg["momentum_price_fetch"] is False
    assert reg["launch_queue"]["data_deepen_requested"] is False
    assert reg["o5_primacy"]["primary"] == "absolute_smoothed_return_fair_costs"
    assert reg["o5_primacy"]["cash_excess"] == "report_only"
    assert reg["o5_primacy"]["stress_cost"] == "report_only"
    assert "promote_n200" in reg["does_not"]
    assert "promote_n201" in reg["does_not"]
    assert "promote_n210" in reg["does_not"]
    assert "crown_assessment_primary" in reg["does_not"]
    assert "widen_max_positions" in reg["does_not"]
    assert "widen_sector_cap" in reg["does_not"]
    assert reg["stress_trade_cost_pct"] == LEGACY_STRESS_TRADE_COST_PCT
    assert reg["baseline_promoted_from"] == "patient_plain_ey_hold_v0"


def test_negative_momentum_still_enters_when_ey_and_health_pass():
    cheap = _row("AAA.L", ey=0.20, mom=-0.4, fh=True, price=100.0)
    rich = _row("BBB.L", ey=0.01, mom=0.5, fh=True, price=50.0)
    snaps = [
        _snap(2, [cheap, rich]),
        _snap(5, [cheap, rich]),
    ]
    # Force a short hold so the second snapshot exits.
    payload = score_plain_ey_hold(
        snaps,
        cfg=N201Config(fetch_momentum_prices=False, hold_trading_days=1, max_episodes=10),
    )
    tickers = {ep["ticker"] for ep in payload["episodes_sample"]}
    assert "AAA.L" in tickers
    assert "BBB.L" not in tickers
    assert payload["momentum_filter"] is False
    assert payload["momentum_price_fetch"] is False
    assert payload["influences_live"] is False
    assert payload["path_scoreboard"]["smooth_ret_cohort_median"] is not None
    assert payload["_return_pcts"]


def test_missing_financial_health_does_not_enter():
    row = _row("CCC.L", ey=0.3, mom=None, fh=None, price=10.0)
    snaps = [_snap(2, [row]), _snap(6, [row])]
    payload = score_plain_ey_hold(
        snaps,
        cfg=N201Config(fetch_momentum_prices=False, hold_trading_days=1),
    )
    assert payload["completed_entry_episodes"] == 0
    assert payload["skipped_missing_entry_fields"] > 0


def test_findings_are_observe_only_and_volume_gate_does_not_promote():
    scored = score_plain_ey_hold([], cfg=N201Config(fetch_momentum_prices=False))
    scored["completed_entry_episodes"] = 48
    scored["calendar_weeks_spanned"] = 8
    scored["volume_gate"] = {"met": True, "min_episodes": 48, "min_weeks": 8}
    scored["path_scoreboard"] = {
        **(scored.get("path_scoreboard") or {}),
        "smooth_ret_cohort_median": 0.02,
    }
    findings = ops_findings_from_n206_observe(scored)
    titles = [row["title"] for row in findings]
    assert FINDING_TITLE in titles
    assert VOLUME_GATE_TITLE in titles
    assert INTERESTINGNESS_TITLE in titles
    assert all(row["auto_fixable"] is False for row in findings)
    assert all(
        "no auto-promote" in row["summary"].lower()
        or "no live writes" in row["summary"]
        or "pipeline badge" in row["summary"]
        for row in findings
    )


def test_refresh_persists_registration_without_admitted_panels(tmp_path: Path):
    store = tmp_path / "n206_plain_ey_observe.json"
    reg = tmp_path / "n206_plain_ey_registration.json"
    payload = refresh_n206_plain_ey_observe(
        output_dir=tmp_path,
        store_path=store,
        registration_path=reg,
        include_admitted_markets=False,
        generated_at="2026-10-16T12:00:00+00:00",
    )
    assert store.is_file()
    written = json.loads(reg.read_text(encoding="utf-8"))
    assert written["registration_id"] == REGISTRATION_ID
    assert written["influences_live"] is False
    assert payload["panel_coverage"]["filing_ingest_sprint"] is False
    assert payload["panel_coverage"]["momentum_price_fetch"] is False
    assert "_return_pcts" not in payload


def test_pipeline_health_reads_store(tmp_path: Path):
    store = tmp_path / "n206_plain_ey_observe.json"
    store.write_text(
        json.dumps(
            {
                "registration_id": REGISTRATION_ID,
                "generated_at": "2026-10-16T12:00:00+00:00",
                "completed_entry_episodes": 3,
                "calendar_weeks_spanned": 2,
                "phase": {"entries_per_week": 1.5, "floor": 8.0, "floor_met": False},
                "volume_gate": {"met": False, "min_episodes": 48, "min_weeks": 8},
                "path_scoreboard": {"smooth_ret_cohort_median": 0.01},
            }
        ),
        encoding="utf-8",
    )
    ops = tmp_path / "ops_status.json"
    ops.write_text(
        json.dumps(
            {
                "run_at": "2026-10-16T12:05:00+00:00",
                "findings": [{"title": FINDING_TITLE}],
            }
        ),
        encoding="utf-8",
    )
    proj = build_n206_pipeline_health_projection(
        store_path=store,
        ops_status_path=ops,
        now=datetime(2026, 10, 16, 12, 10, tzinfo=UTC),
    )
    assert proj["influences_live"] is False
    assert proj["not_assessment_primary"] is True
    assert proj["data_deepen_requested"] is False
    assert proj["volume_gate"]["episodes"] == 3
    assert proj["pipeline"]["ops_check_ok"] is True
