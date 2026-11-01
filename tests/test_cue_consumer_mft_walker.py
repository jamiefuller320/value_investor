"""Tests for cue_consumer_mft lab paper episode walker (thin v0)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from value_investor.backtest import RunSnapshot
from value_investor.cue_consumer_mft import (
    FIXED_STAKE_UNITS,
    PIPELINE_STATUS_ARMED,
    PIPELINE_STATUS_WALKER,
    TUNE_SPEC_ID,
    TUNE_SPEC_ID_EPOCH0,
    WALKER_FINDING_TITLE,
    ops_findings_from_cue_consumer_mft,
    refresh_cue_consumer_mft,
    resolve_lab_knob_epoch,
)
from value_investor.cue_consumer_mft_walker import (
    MAX_OPEN_POSITIONS,
    WALKER_MARKER_ID,
    WalkerConfig,
    gated_walker_payload,
    walk_lab_paper_episodes,
)


def _snap(run_at: str, signals: list[dict], prices: dict[str, float]) -> RunSnapshot:
    return RunSnapshot(run_at=run_at, prices=prices, signals=signals)


def _ai_row(ticker: str, *, signal: str = "buy") -> dict:
    return {
        "ticker": ticker,
        "signal": signal,
        "adjusted_signal": signal,
        "conviction_score": 0.7,
        "research_verdict": "accumulate" if signal in {"buy", "strong_buy"} else "reduce",
    }


def test_walker_opens_and_closes_lab_paper_with_durable_evidence():
    snaps = [
        _snap(
            "2026-08-01T12:00:00+00:00",
            [_ai_row("AAA.L"), {"ticker": "BBB.L", "signal": "hold"}],
            {"AAA.L": 10.0, "BBB.L": 5.0},
        ),
        _snap(
            "2026-08-08T12:00:00+00:00",
            [_ai_row("AAA.L"), {"ticker": "BBB.L", "signal": "buy"}],
            {"AAA.L": 11.0, "BBB.L": 5.5},
        ),
        _snap(
            "2026-09-15T12:00:00+00:00",
            [_ai_row("AAA.L", signal="sell"), {"ticker": "BBB.L", "signal": "hold"}],
            {"AAA.L": 9.0, "BBB.L": 6.0},
        ),
    ]
    out = walk_lab_paper_episodes(snaps, cfg=WalkerConfig(max_open_positions=10))
    assert out["status"] == "active"
    assert out["walker_marker_id"] == WALKER_MARKER_ID
    assert out["influences_live"] is False
    assert out["evolutionary_spawn"] is False
    assert out["closed_lab_episodes"] == 2
    assert out["open_lab_episodes"] == 0

    by_ticker = {e["ticker"]: e for e in out["closed_episodes"]}
    aaa = by_ticker["AAA.L"]
    assert aaa["cue_source_id"] == "n210_ai_filter"  # priority over raw
    assert aaa["fixed_stake_units"] == FIXED_STAKE_UNITS
    assert aaa["book_kind"] == "lab_paper"
    assert aaa["influences_live"] is False
    assert aaa["evidence"]["pit_ok"] is True
    judgment = aaa["evidence"]["judgment_in_the_round"]
    assert judgment["influences_live"] is False
    assert judgment["fill_status"] == "filled"
    assert judgment["buy"]["B4"]["unknown"] is False
    assert "cue_source_id=n210_ai_filter" in judgment["buy"]["B4"]["cites"]
    assert judgment["buy"]["B5"]["unknown"] is False  # conviction + verdict cites
    assert judgment["sell"]["S4"]["unknown"] is False  # exit rule cite on close
    assert judgment["sell"]["S1"]["unknown"] is False
    assert aaa["exit_reason"].startswith("identity_break_")
    assert aaa["same_day_assessment"]["hard_ban"] is False

    bbb = by_ticker["BBB.L"]
    assert bbb["cue_source_id"] == "n200_raw_buy_tier"


def test_walker_respects_open_cap_and_no_double_stake():
    snaps = [
        _snap(
            "2026-08-01T12:00:00+00:00",
            [
                {"ticker": "A.L", "signal": "buy"},
                {"ticker": "B.L", "signal": "buy"},
                {"ticker": "C.L", "signal": "buy"},
            ],
            {"A.L": 1.0, "B.L": 1.0, "C.L": 1.0},
        ),
        _snap(
            "2026-08-08T12:00:00+00:00",
            [
                {"ticker": "A.L", "signal": "buy"},
                {"ticker": "B.L", "signal": "buy"},
                {"ticker": "C.L", "signal": "buy"},
            ],
            {"A.L": 1.1, "B.L": 1.1, "C.L": 1.1},
        ),
    ]
    out = walk_lab_paper_episodes(snaps, cfg=WalkerConfig(max_open_positions=2))
    assert out["open_lab_episodes"] == 2
    assert out["skipped_at_open_cap"] >= 1
    tickers = {e["ticker"] for e in out["open_episodes"]}
    assert len(tickers) == 2


def test_gated_walker_when_start_gate_blocks(tmp_path: Path):
    gated = gated_walker_payload(reason="start_gate_not_eligible")
    assert gated["status"] == "gated"
    assert gated["closed_lab_episodes"] == 0
    assert gated["influences_live"] is False

    queue_path = tmp_path / "post_sale_review_queue.json"
    queue_path.write_text(json.dumps({"active": []}), encoding="utf-8")
    # No frozen cohort + before calendar → not eligible → walker gated.
    payload = refresh_cue_consumer_mft(
        output_dir=tmp_path,
        store_path=tmp_path / "cue_consumer_mft_observe.json",
        registration_path=tmp_path / "cue_consumer_mft_registration.json",
        start_gate_path=tmp_path / "cue_consumer_mft_start_gate.json",
        queue_path=queue_path,
        labels_path=tmp_path / "labels.json",
        persist=True,
        today=date(2026, 10, 25),
    )
    assert payload["pipeline_status"] == PIPELINE_STATUS_ARMED
    assert payload["episode_walker"]["status"] == "gated"
    assert payload["open_lab_episodes"] == 0
    assert payload["observe_shadow_pass"]["fills"] is False
    findings = ops_findings_from_cue_consumer_mft(payload)
    assert not any(f["title"] == WALKER_FINDING_TITLE for f in findings)


def test_refresh_runs_walker_when_eligible(tmp_path: Path):
    history = tmp_path / "history"
    history.mkdir()
    # Minimal archive the walker can load via load_run_snapshots.
    from value_investor.storage import write_json

    write_json(
        history / "run_20260801_120000.json",
        {
            "run_at": "2026-08-01T12:00:00+00:00",
            "prices": {"ZZZ.L": 10.0},
            "signals": [
                {
                    "ticker": "ZZZ.L",
                    "signal": "buy",
                    "adjusted_signal": "buy",
                    "conviction_score": 0.8,
                    "research_verdict": "accumulate",
                }
            ],
        },
        compact=True,
    )
    write_json(
        history / "run_20260808_120000.json",
        {
            "run_at": "2026-08-08T12:00:00+00:00",
            "prices": {"ZZZ.L": 10.5},
            "signals": [
                {
                    "ticker": "ZZZ.L",
                    "signal": "buy",
                    "adjusted_signal": "buy",
                    "conviction_score": 0.8,
                    "research_verdict": "accumulate",
                }
            ],
        },
        compact=True,
    )

    gate = {
        "schema_version": 1,
        "checkpoint_id": "open_autopsy_cohort_2026_q4",
        "cohort_review_ids": ["rev-a"],
        "proposed_cohort_review_ids": ["rev-a"],
        "checkpoint_status": "open",
    }
    (tmp_path / "cue_consumer_mft_start_gate.json").write_text(json.dumps(gate), encoding="utf-8")
    labels = {
        "actioned_review_ids": ["rev-a"],
        "events": [{"review_id": "rev-a", "kind": "accept"}],
    }
    (tmp_path / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    (tmp_path / "post_sale_review_queue.json").write_text(
        json.dumps({"active": []}), encoding="utf-8"
    )

    payload = refresh_cue_consumer_mft(
        output_dir=tmp_path,
        store_path=tmp_path / "cue_consumer_mft_observe.json",
        registration_path=tmp_path / "cue_consumer_mft_registration.json",
        start_gate_path=tmp_path / "cue_consumer_mft_start_gate.json",
        queue_path=tmp_path / "post_sale_review_queue.json",
        labels_path=tmp_path / "labels.json",
        persist=True,
        today=date(2026, 10, 28),
    )
    assert payload["evolutionary_shadows_eligible"] is True
    assert payload["pipeline_status"] == PIPELINE_STATUS_WALKER
    assert payload["episode_walker"]["status"] == "active"
    assert payload["observe_shadow_pass"]["fills"] is True
    assert payload["open_lab_episodes"] >= 1
    assert payload["influences_live"] is False
    assert payload["spend_guard"]["steals_data_p1_fat_slot"] is False

    store = json.loads((tmp_path / "cue_consumer_mft_observe.json").read_text())
    assert store["pipeline_status"] == PIPELINE_STATUS_WALKER
    assert store["open_episodes_sample"]
    assert store["open_episodes_sample"][0]["evidence"]["pit_ok"] is True

    findings = ops_findings_from_cue_consumer_mft(payload)
    assert any(f["title"] == WALKER_FINDING_TITLE for f in findings)
    assert all(f["auto_fixable"] is False for f in findings)

    reg = json.loads((tmp_path / "cue_consumer_mft_registration.json").read_text())
    assert reg["pipeline_status"] == PIPELINE_STATUS_WALKER
    assert reg["influences_live"] is False


def test_default_max_open_positions_is_50():
    assert MAX_OPEN_POSITIONS == 50
    assert WalkerConfig().max_open_positions == 50
    snaps = [
        _snap(
            "2026-08-01T12:00:00+00:00",
            [{"ticker": f"T{i}.L", "signal": "buy"} for i in range(60)],
            {f"T{i}.L": 1.0 for i in range(60)},
        ),
        _snap(
            "2026-08-08T12:00:00+00:00",
            [{"ticker": f"T{i}.L", "signal": "buy"} for i in range(60)],
            {f"T{i}.L": 1.1 for i in range(60)},
        ),
    ]
    out = walk_lab_paper_episodes(snaps)
    assert out["max_open_positions"] == 50
    assert out["open_lab_episodes"] == 50
    assert out["skipped_at_open_cap"] == 10


def test_resolve_lab_knob_epoch_bumps_on_cap_raise_and_persists():
    when0 = "2026-10-28T12:00:00+00:00"
    when1 = "2026-11-01T22:00:00+00:00"
    when2 = "2026-11-02T08:00:00+00:00"
    first = resolve_lab_knob_epoch(None, when=when0)
    assert first["epoch_bumped"] is False
    assert first["knob_epoch_started_at"] == when0
    assert first["max_open_positions"] == 50

    prior_epoch0 = {
        "mid_flight_tune": {
            "knob_epoch_started_at": when0,
            "tune_spec_id": TUNE_SPEC_ID_EPOCH0,
            "max_open_positions": 30,
            "epoch_history": [],
        },
        "episode_walker": {"max_open_positions": 30},
    }
    bumped = resolve_lab_knob_epoch(prior_epoch0, when=when1)
    assert bumped["epoch_bumped"] is True
    assert bumped["knob_epoch_started_at"] == when1
    assert bumped["max_open_positions"] == 50
    assert bumped["end_reason"] == "open_cap_raise_30_to_50"
    assert len(bumped["epoch_history"]) == 1
    assert bumped["epoch_history"][0]["knob_epoch_started_at"] == when0
    assert bumped["epoch_history"][0]["max_open_positions"] == 30

    prior_epoch1 = {
        "mid_flight_tune": {
            "knob_epoch_started_at": when1,
            "tune_spec_id": TUNE_SPEC_ID,
            "max_open_positions": 50,
            "epoch_history": bumped["epoch_history"],
        },
        "episode_walker": {"max_open_positions": 50},
    }
    persisted = resolve_lab_knob_epoch(prior_epoch1, when=when2)
    assert persisted["epoch_bumped"] is False
    assert persisted["knob_epoch_started_at"] == when1
    assert persisted["max_open_positions"] == 50
    assert len(persisted["epoch_history"]) == 1


def test_refresh_stamps_cap50_epoch_and_persists_across_refresh(tmp_path: Path):
    history = tmp_path / "history"
    history.mkdir()
    from value_investor.storage import write_json

    write_json(
        history / "run_20260801_120000.json",
        {
            "run_at": "2026-08-01T12:00:00+00:00",
            "prices": {"ZZZ.L": 10.0},
            "signals": [
                {
                    "ticker": "ZZZ.L",
                    "signal": "buy",
                    "adjusted_signal": "buy",
                    "conviction_score": 0.8,
                    "research_verdict": "accumulate",
                }
            ],
        },
        compact=True,
    )
    write_json(
        history / "run_20260808_120000.json",
        {
            "run_at": "2026-08-08T12:00:00+00:00",
            "prices": {"ZZZ.L": 10.5},
            "signals": [
                {
                    "ticker": "ZZZ.L",
                    "signal": "buy",
                    "adjusted_signal": "buy",
                    "conviction_score": 0.8,
                    "research_verdict": "accumulate",
                }
            ],
        },
        compact=True,
    )

    store_path = tmp_path / "cue_consumer_mft_observe.json"
    # Seed epoch-0 store (cap 30) so refresh must bump to epoch-1 / cap 50.
    store_path.write_text(
        json.dumps(
            {
                "lab_armed_at": "2026-10-28T12:00:00+00:00",
                "mid_flight_tune": {
                    "knob_epoch_started_at": "2026-10-28T12:00:00+00:00",
                    "tune_spec_id": TUNE_SPEC_ID_EPOCH0,
                    "max_open_positions": 30,
                    "epoch_history": [],
                },
                "episode_walker": {"max_open_positions": 30},
            }
        ),
        encoding="utf-8",
    )
    gate = {
        "schema_version": 1,
        "checkpoint_id": "open_autopsy_cohort_2026_q4",
        "cohort_review_ids": ["rev-a"],
        "proposed_cohort_review_ids": ["rev-a"],
        "checkpoint_status": "open",
    }
    (tmp_path / "cue_consumer_mft_start_gate.json").write_text(json.dumps(gate), encoding="utf-8")
    labels = {
        "actioned_review_ids": ["rev-a"],
        "events": [{"review_id": "rev-a", "kind": "accept"}],
    }
    (tmp_path / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    (tmp_path / "post_sale_review_queue.json").write_text(
        json.dumps({"active": []}), encoding="utf-8"
    )

    first = refresh_cue_consumer_mft(
        output_dir=tmp_path,
        store_path=store_path,
        registration_path=tmp_path / "cue_consumer_mft_registration.json",
        start_gate_path=tmp_path / "cue_consumer_mft_start_gate.json",
        queue_path=tmp_path / "post_sale_review_queue.json",
        labels_path=tmp_path / "labels.json",
        persist=True,
        generated_at="2026-11-01T22:10:00+00:00",
        today=date(2026, 11, 1),
    )
    mid = first["mid_flight_tune"]
    assert mid["max_open_positions"] == 50
    assert mid["tune_spec_id"] == TUNE_SPEC_ID
    assert mid["knob_epoch_started_at"] == "2026-11-01T22:10:00+00:00"
    assert mid["stratify_field"] == "knob_epoch_started_at"
    assert first["influences_live"] is False
    assert len(mid["epoch_history"]) == 1
    assert mid["epoch_history"][0]["end_reason"] == "open_cap_raise_30_to_50"
    assert first["episode_walker"]["max_open_positions"] == 50

    second = refresh_cue_consumer_mft(
        output_dir=tmp_path,
        store_path=store_path,
        registration_path=tmp_path / "cue_consumer_mft_registration.json",
        start_gate_path=tmp_path / "cue_consumer_mft_start_gate.json",
        queue_path=tmp_path / "post_sale_review_queue.json",
        labels_path=tmp_path / "labels.json",
        persist=True,
        generated_at="2026-11-02T08:00:00+00:00",
        today=date(2026, 11, 2),
    )
    mid2 = second["mid_flight_tune"]
    assert mid2["knob_epoch_started_at"] == "2026-11-01T22:10:00+00:00"
    assert mid2["max_open_positions"] == 50
    assert mid2["tune_spec_id"] == TUNE_SPEC_ID
    assert len(mid2["epoch_history"]) == 1
    assert second["influences_live"] is False
