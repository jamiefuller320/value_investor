"""Tests for N215 soft-band technical veto observe (labels only)."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.n215_technical_veto_observe import (
    BAND_HARD_LO,
    BAND_SOFT_LO,
    BAND_WARN_LO,
    FINDING_TITLE,
    GRIND_MID60_RULE_ID,
    GRIND_MID60_THR,
    RECIPE_ID,
    REGISTRATION_ID,
    band_for_score,
    build_n215_observe,
    build_registration_payload,
    extract_features,
    ops_findings_from_n215_observe,
    refresh_n215_technical_veto_observe,
    score_episode,
    score_features,
)


def _write_chart(path: Path, *, closes: list[float], start: str = "2026-01-02") -> None:
    """Write a minimal chart JSON with daily dates from ``start``."""
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


def test_band_for_score_cuts_frozen():
    assert band_for_score(0.0) == "PASS"
    assert band_for_score(BAND_WARN_LO - 1e-9) == "PASS"
    assert band_for_score(BAND_WARN_LO) == "WARN"
    assert band_for_score(BAND_SOFT_LO) == "SOFT_VETO"
    assert band_for_score(BAND_HARD_LO) == "HARD_CANDIDATE"


def test_missing_chart_fail_closed_pass(tmp_path: Path):
    row = score_episode(
        ticker="MISSING.L",
        book="N200",
        buy_ts="2026-08-02T12:00:00+00:00",
        fair_cost=-0.12,
        charts_dir=tmp_path,
    )
    assert row["band"] == "PASS"
    assert row["fail_closed"] is True
    assert row["risk_score"] == 0.0
    assert row["influences_live"] is False
    assert row["bucket"] == "deep_loser"


def test_score_features_weighted_sum_and_trail():
    feats = {
        "f_elev_abs": 0.0,
        "f_elev_range": 0.0,
        "f_near_high": 0.0,
        "f_r20": 0.0,
        "f_failed_bo": 1.0,
        "f_rsi_fail": 1.0,
        "f_rsi_level": 0.0,
        "f_death_cross": 0.0,
        "f_lost_200": 0.0,
    }
    score, contribs = score_features(feats)
    assert abs(score - (0.18 + 0.15)) < 1e-9
    assert contribs[0]["feature"] in {"f_failed_bo", "f_rsi_fail"}
    # 0.33 < WARN cut 0.35 → still PASS; need more mass for WARN+
    assert band_for_score(score) == "PASS"
    assert band_for_score(score + 0.05) == "WARN"


def test_extract_features_near_high_rally():
    # Flat then rally into highs
    closes = [100.0] * 80 + [100.0 + i for i in range(1, 47)]
    extracted = extract_features(closes)
    assert extracted["features"]["f_near_high"] > 0.5
    assert extracted["features"]["f_r20"] > 0.0
    assert extracted["raw"]["bars"] == len(closes)
    assert extracted["raw"]["mid_range_60"] is not None
    assert extracted["raw"]["mid_range_60"] >= GRIND_MID60_THR


def test_grind_mid60_fires_only_on_pass_above_mid():
    # Mid-range high but soft features near zero → PASS + grind fire.
    # Quiet series ending in upper half of last 60d range.
    closes = [100.0] * 40 + [90.0 + i * 0.4 for i in range(60)]  # ends ~114, range 90–114
    extracted = extract_features(closes)
    mid = extracted["raw"]["mid_range_60"]
    assert mid is not None and mid >= GRIND_MID60_THR
    score, _ = score_features(extracted["features"])
    assert band_for_score(score) == "PASS"
    # score_episode wires the companion flag
    # (full path tested via synthetic chart below)


def test_score_episode_grind_mid60_companion(tmp_path: Path):
    charts = tmp_path / "charts"
    charts.mkdir()
    # Mild grind: 60d range ~95–105, close at 103 (mid≥0.5) without climax soft mass.
    closes = [100.0] * 70
    for i in range(60):
        closes.append(95.0 + (i % 10) * 1.0)  # oscillate 95–104
    closes[-1] = 103.0
    _write_chart(charts / "GRD.L.json", closes=closes, start="2026-01-02")
    row = score_episode(
        ticker="GRD.L",
        book="N200",
        buy_ts="2026-05-15T12:00:00+00:00",
        fair_cost=-0.15,
        charts_dir=charts,
    )
    assert row["coverage"] is True
    assert row["band"] == "PASS"
    assert row["mid_range_60"] is not None and row["mid_range_60"] >= GRIND_MID60_THR
    assert row["grind_mid60_fire"] is True
    assert any(GRIND_MID60_RULE_ID in r for r in row["reasons"])


def test_build_and_refresh_persist(tmp_path: Path):
    charts = tmp_path / "charts"
    charts.mkdir()
    # Rising series ending near high with enough bars
    closes = [50.0 + 0.2 * i for i in range(120)]
    _write_chart(charts / "AAA.L.json", closes=closes, start="2026-01-02")
    # Remap ticker field is ignored; filename drives load via chart_filename
    # chart_filename("AAA.L") -> AAA.L.json
    n200 = {
        "lifecycle_episodes": [
            {
                "ticker": "AAA.L",
                "entry_run_at": "2026-05-01T12:00:00+00:00",
                "exit_run_at": "2026-05-20T12:00:00+00:00",
                "status": "closed",
                "fair_cost_return": -0.15,
            },
            {
                "ticker": "BBB.L",
                "entry_run_at": "2026-05-01T12:00:00+00:00",
                "exit_run_at": "2026-05-20T12:00:00+00:00",
                "status": "closed",
                "fair_cost_return": 0.20,
            },
        ]
    }
    n206 = {"lifecycle_episodes": []}
    n210 = {"lifecycle_episodes": []}
    (tmp_path / "n200_tech_timing_observe.json").write_text(json.dumps(n200), encoding="utf-8")
    (tmp_path / "n206_plain_ey_observe.json").write_text(json.dumps(n206), encoding="utf-8")
    (tmp_path / "n210_ai_judgment_observe.json").write_text(json.dumps(n210), encoding="utf-8")
    # BBB missing chart → fail-closed PASS large winner
    store = tmp_path / "n215_technical_veto_observe.json"
    reg = tmp_path / "n215_technical_veto_registration.json"
    payload = refresh_n215_technical_veto_observe(
        output_dir=tmp_path,
        store_path=store,
        registration_path=reg,
        charts_dir=charts,
        persist=True,
        generated_at="2026-10-21T00:00:00+00:00",
    )
    assert payload["registration_id"] == REGISTRATION_ID
    assert payload["recipe_id"] == RECIPE_ID
    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    assert payload["admit_recommendation"]["live_veto"] is False
    assert payload["admit_recommendation"]["any_band_admit_worthy"] is False
    assert "companion_grind_mid60" in payload["rollup"]
    assert payload["rollup"]["companion_grind_mid60"]["rule_id"] == GRIND_MID60_RULE_ID
    assert payload["rollup"]["companion_grind_mid60"]["influences_live"] is False
    assert store.is_file() and reg.is_file()
    assert len(payload["episodes"]) == 2
    findings = ops_findings_from_n215_observe(payload)
    assert findings and findings[0]["title"] == FINDING_TITLE
    assert findings[0]["auto_fixable"] is False
    assert GRIND_MID60_RULE_ID in findings[0]["summary"]


def test_registration_seal_fields():
    reg = build_registration_payload(generated_at="2026-10-21T00:00:00+00:00")
    assert reg["influences_live"] is False
    assert reg["observe_only"] is True
    assert reg["recipe"]["recipe_id"] == RECIPE_ID
    assert abs(sum(reg["recipe"]["weights"].values()) - 1.0) < 1e-9
    assert GRIND_MID60_RULE_ID in reg["companion_rules"]
    assert reg["companion_rules"][GRIND_MID60_RULE_ID]["influences_live"] is False


def test_build_n215_observe_rollup_shape():
    # Direct build with empty episodes
    payload = build_n215_observe([], generated_at="2026-10-21T00:00:00+00:00")
    assert payload["cohort"]["N200_closed"] == 0
    assert "exclusive_bands" in payload["rollup"]
    assert "cumulative_bands" in payload["rollup"]
    assert "hard_rule_companion" in payload["rollup"]
    assert "companion_grind_mid60" in payload["rollup"]
    assert payload["rollup"]["companion_grind_mid60"]["alone_benefit_primary"] == "N200"
