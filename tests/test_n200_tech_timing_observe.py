"""Tests for sealed N200 observe-only tech-timing brackets."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.backtest import RunSnapshot
from value_investor.n200_tech_timing_observe import (
    FINDING_TITLE,
    REGISTRATION_ID,
    VOLUME_GATE_TITLE,
    build_n200_observe,
    build_registration_payload,
    episode_return,
    ops_findings_from_n200_observe,
    refresh_n200_tech_timing_observe,
    row_f9_eligible,
)


def _snap(day: int, rows: list[tuple[str, str, float]]) -> RunSnapshot:
    signals = [
        {"ticker": t, "signal": sig, "conviction_score": 0.5, "data_quality_score": 0.8}
        for t, sig, _ in rows
    ]
    prices = {t: p for t, _, p in rows}
    return RunSnapshot(
        run_at=f"2026-01-{day:02d}T12:00:00+00:00",
        prices=prices,
        signals=signals,
    )


def test_episode_return_applies_round_trip_cost():
    assert abs(episode_return(100.0, 110.0, trade_cost_pct=0.03) - 0.04) < 1e-12


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


def test_build_n200_observe_scores_brackets():
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
    control = payload["path_scoreboard"]["control_smooth_ret_cohort_median"]
    assert control is not None
    # 120/100 - 1 - 0.06 = 0.14
    assert abs(control - 0.14) < 1e-6
    assert "entry_+0__exit_+0" in payload["cells"]
    assert payload["change_markers"][0]["marker_id"] == "n200-seal-v0"
    assert "entry_lever_scoreboard" in payload
    assert "exit_lever_scoreboard" in payload


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
    assert payload["completed_entry_episodes"] == 1


def test_ops_findings_volume_gate():
    base = build_n200_observe([])
    base["completed_entry_episodes"] = 30
    base["calendar_weeks_spanned"] = 10
    base["volume_gate"] = {"met": True, "min_episodes": 24, "min_weeks": 8}
    base["phase"] = {"entries_per_week": 3.0, "floor": 5.0, "floor_met": False}
    base["path_scoreboard"] = {"control_smooth_ret_cohort_median": 0.01}
    findings = ops_findings_from_n200_observe(base)
    titles = {f["title"] for f in findings}
    assert FINDING_TITLE in titles
    assert VOLUME_GATE_TITLE in titles
    assert all(f["auto_fixable"] is False for f in findings)


def test_registration_payload_seal_fields():
    reg = build_registration_payload(sealed_at="2026-10-11")
    assert reg["status"] == "sealed_observe_only"
    assert reg["o5_primacy"]["control_excess"] == "report_only"
    assert reg["o3_volume_gate"]["rule"] == "both_required"
