"""Observe-only Start → … → live-ready tile stepper."""

from __future__ import annotations

from pathlib import Path

from test_market_status import _by_id, _seed_library, _status_roots

from value_investor.market_status import (
    GATE_ADMIT,
    GATE_BODIES,
    GATE_EPOCH0,
    GATE_FTSE_PARITY,
    GATE_LIVE_READY,
    GATE_SPRINT,
    GATE_START,
    LIVE_MARKET_ID,
    build_learning_gate_indicator,
    build_market_status,
)
from value_investor.storage import write_json


def _statuses(gate: dict) -> dict[str, str]:
    return {step["id"]: step["status"] for step in gate["steps"]}


def test_live_tile_is_live_path_not_self_catchup():
    gate = build_learning_gate_indicator(is_live=True)
    assert gate["observe_only"] is True
    assert gate["current_id"] == GATE_LIVE_READY
    assert gate["live_ready"] is True
    assert _statuses(gate) == {
        GATE_START: "done",
        GATE_BODIES: "done",
        GATE_SPRINT: "done",
        GATE_ADMIT: "done",
        GATE_EPOCH0: "done",
        GATE_FTSE_PARITY: "done",
        GATE_LIVE_READY: "done",
    }
    assert gate["next_gate"]["id"] == "live_path"
    assert "catching this tile up to itself" in gate["annotation"]
    assert "FTSE 350" in gate["next_gate"]["criteria"]
    assert "NAV" not in gate["annotation"]


def test_zero_body_next_gate_is_bodies_clear():
    gate = build_learning_gate_indicator(
        is_live=False,
        is_admitted=False,
        ingest="sprint",
        ingest_parity_met=False,
        ingest_exhausted=False,
        remaining_gaps={"unmeasured": 0, "zero_body": 1, "thin": 24, "indexed_without_body": 2},
    )
    assert gate["current_id"] == GATE_BODIES
    assert _statuses(gate)[GATE_START] == "done"
    assert _statuses(gate)[GATE_BODIES] == "current"
    assert _statuses(gate)[GATE_SPRINT] == "pending"
    assert gate["next_gate"]["gate"] == "unmeasured_zero_clear"
    assert "zero 1" in gate["next_gate"]["criteria"]
    assert "cannot park" in gate["next_gate"]["criteria"]


def test_bodies_clear_leftover_next_is_sprint_complete():
    gate = build_learning_gate_indicator(
        is_live=False,
        ingest="sprint",
        remaining_gaps={"unmeasured": 0, "zero_body": 0, "thin": 3, "indexed_without_body": 1},
    )
    assert gate["bodies_complete"] is True
    assert gate["sprint_complete"] is False
    assert gate["current_id"] == GATE_SPRINT
    assert gate["next_gate"]["gate"] == "sprint_ingest_complete"
    assert "thin 3" in gate["next_gate"]["criteria"]
    assert "Sprint until exhaustion" in gate["next_gate"]["timeframe"]


def test_sprint_complete_not_admitted_next_is_l322():
    gate = build_learning_gate_indicator(
        is_live=False,
        is_admitted=False,
        ingest="maintenance",
        ingest_exhausted=True,
        learning_depth={"filing_ready": True, "learning_ready": False},
    )
    assert gate["sprint_complete"] is True
    assert gate["current_id"] == GATE_ADMIT
    assert gate["next_gate"]["gate"] == "l322_admit"


def test_admitted_without_epoch0_next_is_marks():
    gate = build_learning_gate_indicator(
        is_live=False,
        is_admitted=True,
        ingest_exhausted=True,
        learning_depth={
            "filing_ready": True,
            "trajectory_ready": False,
            "learning_ready": False,
            "span_weeks": 10.57,
            "unique_days": 28,
        },
    )
    assert gate["admit_complete"] is True
    assert gate["epoch0_complete"] is False
    assert gate["current_id"] == GATE_EPOCH0
    assert gate["next_gate"]["gate"] == "epoch0_marks"
    assert "NAV" not in gate["annotation"]


def test_admitted_epoch0_short_span_next_is_learning_ready():
    gate = build_learning_gate_indicator(
        is_live=False,
        is_admitted=True,
        ingest_exhausted=True,
        epoch0={"present": True, "holdings": 120, "epoch0_batch_count": 21},
        learning_depth={
            "filing_ready": True,
            "trajectory_ready": False,
            "learning_ready": False,
            "span_weeks": 10.57,
            "unique_days": 28,
        },
    )
    assert gate["epoch0_complete"] is True
    assert gate["learning_ready"] is False
    assert gate["current_id"] == GATE_FTSE_PARITY
    assert _statuses(gate)[GATE_EPOCH0] == "done"
    assert _statuses(gate)[GATE_FTSE_PARITY] == "current"
    assert gate["next_gate"]["gate"] == "learning_ready"
    assert "10.57w" in gate["next_gate"]["criteria"]
    assert "1.43w" in gate["next_gate"]["timeframe"]


def test_parity_reached_next_gate_is_stage_4():
    gate = build_learning_gate_indicator(
        is_live=False,
        is_admitted=True,
        ingest_parity_met=True,
        epoch0={"present": True, "holdings": 80, "epoch0_batch_count": 12},
        learning_depth={
            "filing_ready": True,
            "trajectory_ready": True,
            "learning_ready": True,
            "span_weeks": 12.5,
            "unique_days": 14,
        },
    )
    assert gate["learning_ready"] is True
    assert gate["live_ready"] is False
    assert gate["current_id"] == GATE_LIVE_READY
    assert _statuses(gate)[GATE_FTSE_PARITY] == "done"
    assert _statuses(gate)[GATE_LIVE_READY] == "current"
    assert gate["next_gate"]["gate"] == "phase_4_live_screen"
    assert "Live screen stays FTSE 350" in gate["next_gate"]["timeframe"]
    assert "Do not fork shard AI" in gate["next_gate"]["criteria"]


def test_market_status_attaches_learning_gate(tmp_path: Path):
    library = _seed_library(tmp_path / "library")
    write_json(
        library / "markets" / "sp500" / "learning_depth.json",
        {
            "filing_ready": True,
            "trajectory_ready": False,
            "learning_ready": False,
            "screen": {"span_weeks": 10.57, "unique_days": 28},
        },
        compact=False,
    )
    payload = build_market_status(
        library_root=library,
        policy_path=library / "policy.json",
        dispatch_path=library / "euro_ingest_dispatch.json",
        **_status_roots(tmp_path),
        live_meta={"company_count": 249, "signal_counts": {"buy": 10}},
        live_signal_counts={"buy": 10},
        live_run_at="2026-09-03T09:00:00+00:00",
    )
    live = _by_id(payload, LIVE_MARKET_ID)
    assert live["learning_gate"]["live_ready"] is True
    assert live["learning_gate"]["next_gate"]["id"] == "live_path"
    assert live.get("learning_depth") is None
    assert len(live["learning_gate"]["steps"]) == 7

    euro = _by_id(payload, "euro_depth")
    assert euro["learning_gate"]["current_id"] == GATE_BODIES
    assert euro["learning_gate"]["next_gate"]["gate"] == "unmeasured_zero_clear"

    sp500 = _by_id(payload, "sp500")
    assert sp500["learning_depth"]["span_weeks"] == 10.57
    assert sp500["learning_gate"]["filing_ready"] is True
    assert sp500["learning_gate"]["sprint_complete"] is True
    assert sp500["learning_gate"]["next_gate"]["gate"] == "l322_admit"
