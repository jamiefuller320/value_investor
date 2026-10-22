"""Tests for N215 soft-veto → MONITOR reentry observe (labels only)."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.n215_reentry_observe import (
    BREAKOUT_PCT,
    FINDING_TITLE,
    PAIR_ID,
    R5_TIMEOUT_SESSIONS,
    R6_WORSEN_DD,
    REGISTRATION_ID,
    SCHEMA_VERSION,
    build_n215_reentry_observe,
    build_registration_payload,
    meets_band_gate,
    ops_findings_from_n215_reentry,
    pre_t0_swing_high,
    refresh_n215_reentry_observe,
    walk_r1_monitor,
)


def _write_chart(path: Path, *, closes: list[float], start: str = "2026-01-02") -> None:
    from datetime import date, timedelta

    d0 = date.fromisoformat(start)
    dates = [(d0 + timedelta(days=i)).isoformat() for i in range(len(closes))]
    payload = {
        "ticker": "TEST.L",
        "dates": dates,
        "closes": closes,
        "sma50_series": [None] * len(closes),
        "sma200_series": [None] * len(closes),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_meets_band_gate():
    assert meets_band_gate("WARN", gate="WARN+")
    assert meets_band_gate("SOFT_VETO", gate="WARN+")
    assert not meets_band_gate("PASS", gate="WARN+")
    assert meets_band_gate("SOFT_VETO", gate="SOFT_VETO+")
    assert not meets_band_gate("WARN", gate="SOFT_VETO+")


def test_pre_t0_swing_high_lookback_max():
    closes = [10.0] * 50 + [20.0, 18.0, 19.0]
    assert pre_t0_swing_high(closes, len(closes) - 1) == 20.0


def test_walk_r1_reenters_on_breakout():
    # Flat then breakout above prior high
    pre = [100.0] * 30 + [110.0] + [105.0] * 10  # swing high 110 at buy
    # buy at end of pre; then climb past 110*1.01; keep bars after reentry for path
    post = [105.0, 106.0, 112.0, 114.0, 116.0]  # day 3 breaks
    closes = pre + post
    from datetime import date, timedelta

    d0 = date(2026, 1, 1)
    dates = [(d0 + timedelta(days=i)).isoformat() for i in range(len(closes))]
    buy_day = dates[len(pre) - 1]
    exit_day = dates[len(pre) + 4]  # after reentry
    walk = walk_r1_monitor(dates=dates, closes=closes, buy_day=buy_day, exit_day=exit_day)
    assert walk["evaluable"] is True
    assert walk["label"] == "reentered"
    assert walk["sessions_walked"] == 3
    assert walk["breakout_level"] == 110.0 * (1.0 + BREAKOUT_PCT)
    assert walk["alt_path_return"] is not None
    assert walk["alt_path_return"] > 0


def test_walk_r1_worsen_abandon():
    pre = [100.0] * 40
    post = [95.0, 90.0, 84.0]  # −16% from t0
    closes = pre + post
    from datetime import date, timedelta

    d0 = date(2026, 1, 1)
    dates = [(d0 + timedelta(days=i)).isoformat() for i in range(len(closes))]
    buy_day = dates[len(pre) - 1]
    walk = walk_r1_monitor(dates=dates, closes=closes, buy_day=buy_day, exit_day=None)
    assert walk["label"] == "abandoned_worsen"
    assert walk["drawdown_at_abandon"] <= R6_WORSEN_DD


def test_walk_r1_timeout():
    pre = [100.0] * 40
    post = [100.0 + (i % 3) * 0.1 for i in range(R5_TIMEOUT_SESSIONS)]
    closes = pre + post
    from datetime import date, timedelta

    d0 = date(2026, 1, 1)
    dates = [(d0 + timedelta(days=i)).isoformat() for i in range(len(closes))]
    buy_day = dates[len(pre) - 1]
    walk = walk_r1_monitor(dates=dates, closes=closes, buy_day=buy_day, exit_day=None)
    assert walk["label"] == "abandoned_timeout"
    assert walk["sessions_walked"] == R5_TIMEOUT_SESSIONS


def test_walk_unevaluable_no_forward():
    closes = [100.0] * 20
    from datetime import date, timedelta

    d0 = date(2026, 1, 1)
    dates = [(d0 + timedelta(days=i)).isoformat() for i in range(len(closes))]
    buy_day = dates[-1]
    walk = walk_r1_monitor(dates=dates, closes=closes, buy_day=buy_day, exit_day=None)
    assert walk["evaluable"] is False
    assert walk["label"] == "unevaluable"


def test_refresh_persist_and_findings(tmp_path: Path):
    charts = tmp_path / "charts"
    charts.mkdir()
    # Rising into highs so soft score can WARN; then breakout after buy
    # Build a long series that ends near highs then breaks out
    closes = [50.0 + 0.3 * i for i in range(120)] + [90.0, 91.0, 95.0]
    _write_chart(charts / "WIN.L.json", closes=closes, start="2026-01-02")
    # Deep loser that worsens without breakout
    loser = [80.0] * 100 + [80.0, 70.0, 65.0]
    _write_chart(charts / "LOSE.L.json", closes=loser, start="2026-01-02")

    from datetime import date, timedelta

    d0 = date(2026, 1, 2)
    win_buy = (d0 + timedelta(days=119)).isoformat()
    win_exit = (d0 + timedelta(days=122)).isoformat()
    lose_buy = (d0 + timedelta(days=99)).isoformat()
    lose_exit = (d0 + timedelta(days=102)).isoformat()

    n200 = {
        "lifecycle_episodes": [
            {
                "ticker": "WIN.L",
                "entry_run_at": f"{win_buy}T12:00:00+00:00",
                "exit_run_at": f"{win_exit}T12:00:00+00:00",
                "status": "closed",
                "fair_cost_return": 0.20,
            },
            {
                "ticker": "LOSE.L",
                "entry_run_at": f"{lose_buy}T12:00:00+00:00",
                "exit_run_at": f"{lose_exit}T12:00:00+00:00",
                "status": "closed",
                "fair_cost_return": -0.15,
            },
            {
                "ticker": "PASS.L",
                "entry_run_at": "2026-05-01T12:00:00+00:00",
                "exit_run_at": "2026-05-20T12:00:00+00:00",
                "status": "closed",
                "fair_cost_return": 0.05,
            },
        ]
    }
    (tmp_path / "n200_tech_timing_observe.json").write_text(json.dumps(n200), encoding="utf-8")
    # Soft store: force WIN/LOSE into WARN+; PASS stays out
    soft = {
        "episodes": [
            {
                "ticker": "WIN.L",
                "book": "N200",
                "buy_day": win_buy,
                "buy_ts": f"{win_buy}T12:00:00+00:00",
                "band": "WARN",
                "risk_score": 0.40,
                "coverage": True,
                "fail_closed": False,
            },
            {
                "ticker": "LOSE.L",
                "book": "N200",
                "buy_day": lose_buy,
                "buy_ts": f"{lose_buy}T12:00:00+00:00",
                "band": "SOFT_VETO",
                "risk_score": 0.60,
                "coverage": True,
                "fail_closed": False,
            },
            {
                "ticker": "PASS.L",
                "book": "N200",
                "buy_day": "2026-05-01",
                "buy_ts": "2026-05-01T12:00:00+00:00",
                "band": "PASS",
                "risk_score": 0.10,
                "coverage": True,
                "fail_closed": False,
            },
        ]
    }
    (tmp_path / "n215_technical_veto_observe.json").write_text(json.dumps(soft), encoding="utf-8")
    # N206 holdout: one WARN+ mild winner that reenters (on-the-fly soft score)
    n206 = {
        "lifecycle_episodes": [
            {
                "ticker": "WIN.L",
                "entry_run_at": f"{win_buy}T12:00:00+00:00",
                "exit_run_at": f"{win_exit}T12:00:00+00:00",
                "status": "closed",
                "fair_cost_return": 0.08,
            },
        ]
    }
    (tmp_path / "n206_plain_ey_observe.json").write_text(json.dumps(n206), encoding="utf-8")

    store = tmp_path / "n215_reentry_observe.json"
    reg = tmp_path / "n215_reentry_registration.json"
    payload = refresh_n215_reentry_observe(
        output_dir=tmp_path,
        store_path=store,
        registration_path=reg,
        charts_dir=charts,
        persist=True,
        generated_at="2026-10-21T00:00:00+00:00",
    )
    assert payload["registration_id"] == REGISTRATION_ID
    assert payload["pair_id"] == PAIR_ID
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["thickened"] is True
    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    assert payload["admit_recommendation"]["live_reentry"] is False
    assert payload["admit_recommendation"]["layer_b_closer_to_admit"] is False
    assert store.is_file() and reg.is_file()
    assert len(payload["episodes"]) == 3
    primary = payload["rollup"]["primary_WARN+_R1"]
    assert primary["gated_n"] == 2
    assert "full_gate_reentered_rate" in primary
    assert "positive_fc_re_admit_rate" in primary
    win_row = next(r for r in payload["episodes"] if r["ticker"] == "WIN.L")
    assert win_row["label"] == "reentered"
    lose_row = next(r for r in payload["episodes"] if r["ticker"] == "LOSE.L")
    assert lose_row["label"] == "abandoned_worsen"
    holdout = payload.get("holdout_N206")
    assert isinstance(holdout, dict)
    assert holdout["never_tune"] is True
    assert holdout["closed_n"] == 1
    findings = ops_findings_from_n215_reentry(payload)
    assert findings and findings[0]["title"] == FINDING_TITLE
    assert findings[0]["auto_fixable"] is False
    assert "thickened" in findings[0]["summary"]


def test_registration_seal_fields():
    reg = build_registration_payload(generated_at="2026-10-21T00:00:00+00:00")
    assert reg["influences_live"] is False
    assert reg["observe_only"] is True
    assert reg["pair"]["reentry_rule"] == "R1"
    assert reg["pair"]["r5_timeout_sessions"] == R5_TIMEOUT_SESSIONS
    assert reg["pair"]["r6_worsen_dd"] == R6_WORSEN_DD
    assert reg["pair"]["thickened"] is True


def test_build_empty_shape():
    payload = build_n215_reentry_observe([], generated_at="2026-10-21T00:00:00+00:00")
    assert payload["cohort"]["N200_closed"] == 0
    assert "primary_WARN+_R1" in payload["rollup"]
    assert payload["admit_recommendation"]["pair_admit_worthy"] is False
    assert payload["holdout_N206"] is None


def test_build_with_empty_holdout():
    payload = build_n215_reentry_observe(
        [],
        holdout_episodes=[],
        generated_at="2026-10-21T00:00:00+00:00",
    )
    assert payload["holdout_N206"] is not None
    assert payload["holdout_N206"]["closed_n"] == 0
    assert payload["holdout_N206"]["never_tune"] is True
