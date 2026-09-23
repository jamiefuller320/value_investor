"""Tests for library ingest stall task triage."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_tasks import load_engineering_tasks
from value_investor.library_stall_task_triage import (
    analyze_library_stall_task,
    find_superseded_library_stall_canonical,
    investigate_reburn_loop_library_stall,
    reburn_unpark_dispatch_gates,
    summarize_library_stall_parks,
    triage_library_stall_tasks,
)


def _stall_row(
    task_id: str,
    *,
    status: str = "parked",
    market_id: str = "dax",
    parked_policy: str = "",
    parked_reason: str = "",
) -> dict:
    return {
        "id": task_id,
        "area": "ingest",
        "status": status,
        "source": "library_ingest_stall",
        "title": f"Close library ingest filing gaps for {market_id}",
        "summary": "Broad market stall",
        "evidence": {
            "market_id": market_id,
            "filing_health": {
                "unmeasured_buy_tier": 2,
                "zero_body_buy_tier": 0,
                "indexed_without_body": 30,
                "thin_body_buy_tier": 1,
                "unmeasured_tickers": ["AAA.DE", "BBB.DE"],
                "indexed_without_body_tickers": ["FME.DE"],
                "indexed_without_body_by_ticker": {"FME.DE": 30},
            },
        },
        "parked_policy": parked_policy,
        "parked_reason": parked_reason,
    }


def test_find_superseded_library_stall_canonical():
    tasks = [
        _stall_row("eng-20260920-16"),
        _stall_row("eng-20260922-05"),
    ]
    older = tasks[0]
    assert find_superseded_library_stall_canonical(older, tasks) == "eng-20260922-05"
    assert find_superseded_library_stall_canonical(tasks[1], tasks) is None


def test_triage_cancels_superseded_stall(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _stall_row("eng-20260920-16"),
            _stall_row("eng-20260922-05", parked_policy="reburn_loop", parked_reason="reburn"),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    result = triage_library_stall_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_cancel_superseded=True,
        auto_cancel_resolved=False,
        auto_annotate=False,
    )
    assert any(row.action == "cancel_superseded_library_stall" for row in result.cancelled)
    rows = {row["id"]: row for row in load_engineering_tasks(tasks_path)["tasks"]}
    assert rows["eng-20260920-16"]["status"] == "cancelled"
    assert rows["eng-20260920-16"].get("duplicate_of") == "eng-20260922-05"
    assert rows["eng-20260922-05"]["status"] == "parked"


def test_analyze_library_stall_task_bundled_and_focus(monkeypatch):
    row = _stall_row("eng-20260922-05")
    triage = analyze_library_stall_task(row, refresh_health=False)
    assert triage["bundled"] is True
    assert triage["focus_ticker"] == "AAA.DE"
    assert triage["focus_lane"] == "unmeasured"
    assert "split_by_ticker_not_broad_market_task" in triage["recommendations"]


def test_reframe_skips_reburn_loop(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    row = _stall_row(
        "eng-20260922-05",
        parked_policy="reburn_loop",
        parked_reason="automation waste reburn",
    )
    tasks_path.write_text(json.dumps({"tasks": [row]}), encoding="utf-8")

    result = triage_library_stall_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_cancel_superseded=False,
        auto_annotate=True,
        auto_reframe_bundled=True,
    )
    assert not result.reframed
    kept = load_engineering_tasks(tasks_path)["tasks"][0]
    assert kept.get("evidence", {}).get("stall_triage", {}).get("reburn_loop") is True


def test_reframe_bundled_parked_task(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    row = _stall_row("eng-20260922-05", parked_policy="preflight_clash")
    tasks_path.write_text(json.dumps({"tasks": [row]}), encoding="utf-8")
    health = row["evidence"]["filing_health"]
    monkeypatch.setattr(
        "value_investor.library_stall_task_triage.snapshot_library_buy_tier_filing_health",
        lambda market_id, **kwargs: {**health, "snapshot_at": "2026-09-22T00:00:00+00:00"},
    )

    result = triage_library_stall_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_cancel_superseded=False,
        auto_annotate=False,
        auto_reframe_bundled=True,
    )
    assert any(row.action == "reframe_narrow" for row in result.reframed)
    updated = load_engineering_tasks(tasks_path)["tasks"][0]
    assert "AAA.DE" in updated["title"]
    assert updated["evidence"].get("focus_ticker") == "AAA.DE"
    assert updated["evidence"].get("narrow_reframe_at")


def test_reburn_investigation_blocks_reframe_when_waste_active(tmp_path: Path, monkeypatch):
    row = _stall_row(
        "eng-20260922-05",
        parked_policy="reburn_loop",
        parked_reason="automation waste reburn",
    )
    monkeypatch.setattr(
        "value_investor.project_traffic.get_traffic_control_state",
        lambda **kwargs: {
            "automation_waste_active": True,
            "automation_waste_parked_task_ids": ["eng-20260922-05"],
        },
    )
    monkeypatch.setattr(
        "value_investor.automation_waste.detect_engineering_agent_reburn",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery.preflight_park_is_healed",
        lambda row, **kwargs: True,
    )
    inv = investigate_reburn_loop_library_stall(
        row, tasks_path=tmp_path / "missing.json", bundled=True, focus_ticker="AAA.DE"
    )
    assert inv["primary_hypothesis"] == "eng_agent_reburn_active"
    assert inv["allow_narrow_reframe"] is False
    assert "automation_waste" in inv["blockers"]

    triage = analyze_library_stall_task(row, refresh_health=False)
    triage["reburn_investigation"] = inv
    from value_investor.library_stall_task_triage import reframe_bundled_library_stall_task

    assert (
        reframe_bundled_library_stall_task(row, triage, tasks_path=tmp_path / "t.json", apply=False)
        is None
    )


def test_reburn_investigation_allows_reframe_when_cleared(tmp_path: Path, monkeypatch):
    row = _stall_row(
        "eng-20260922-05",
        parked_policy="reburn_loop",
        parked_reason="automation waste reburn",
    )
    monkeypatch.setattr(
        "value_investor.project_traffic.get_traffic_control_state",
        lambda **kwargs: {"automation_waste_active": False},
    )
    monkeypatch.setattr(
        "value_investor.automation_waste.detect_engineering_agent_reburn",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery.preflight_park_is_healed",
        lambda row, **kwargs: True,
    )
    inv = investigate_reburn_loop_library_stall(
        row, tasks_path=tmp_path / "missing.json", bundled=True, focus_ticker="AAA.DE"
    )
    assert inv["allow_narrow_reframe"] is True


def test_allow_unpark_without_bundled_narrow_reframe(tmp_path: Path, monkeypatch):
    row = _stall_row(
        "eng-20260922-05",
        parked_policy="reburn_loop",
        parked_reason="automation waste reburn",
    )
    row["evidence"]["filing_health"] = {
        **row["evidence"]["filing_health"],
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 1,
        "unmeasured_tickers": [],
        "zero_body_tickers": ["ZZZ.DE"],
    }
    monkeypatch.setattr(
        "value_investor.project_traffic.get_traffic_control_state",
        lambda **kwargs: {"automation_waste_active": False},
    )
    monkeypatch.setattr(
        "value_investor.automation_waste.detect_engineering_agent_reburn",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery.preflight_park_is_healed",
        lambda row, **kwargs: True,
    )
    inv = investigate_reburn_loop_library_stall(
        row,
        tasks_path=tmp_path / "missing.json",
        bundled=False,
        focus_ticker="ZZZ.DE",
    )
    assert inv["allow_unpark"] is True
    assert inv["allow_narrow_reframe"] is False


def test_reburn_unpark_dispatch_gates_imports_resolve(tmp_path: Path, monkeypatch):
    """Regression: eng-queue recover-queue ImportError (runs 35853220275 / 35853482034).

    ``is_queue_clearing_pause_active`` lives in engineering_recovery and
    ``is_traffic_pause_active`` in project_traffic — not engineering_queue.
    """
    monkeypatch.setattr(
        "value_investor.project_traffic.get_traffic_control_state",
        lambda **kwargs: {"automation_waste_active": False, "pause_reasons": []},
    )
    monkeypatch.setattr(
        "value_investor.project_traffic.is_traffic_pause_active",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery.is_queue_clearing_pause_active",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        "value_investor.automation_waste.detect_engineering_agent_reburn",
        lambda **kwargs: None,
    )
    ok, detail = reburn_unpark_dispatch_gates(tasks_path=tmp_path / "missing.json")
    assert ok is True
    assert detail == "dispatch gates clear"


def test_auto_unpark_reburn_when_gates_clear(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    row = _stall_row(
        "eng-20260922-05",
        parked_policy="reburn_loop",
        parked_reason="automation waste reburn",
    )
    tasks_path.write_text(json.dumps({"tasks": [row]}), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.project_traffic.get_traffic_control_state",
        lambda **kwargs: {"automation_waste_active": False},
    )
    monkeypatch.setattr(
        "value_investor.automation_waste.detect_engineering_agent_reburn",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery.preflight_park_is_healed",
        lambda row, **kwargs: True,
    )
    monkeypatch.setattr(
        "value_investor.library_stall_task_triage.reburn_unpark_dispatch_gates",
        lambda **kwargs: (True, "dispatch gates clear"),
    )

    result = triage_library_stall_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_cancel_superseded=False,
        auto_annotate=False,
        auto_unpark_cleared_reburn=True,
    )
    assert any(a.action == "unpark_reburn_library_stall" for a in result.unparked)
    assert load_engineering_tasks(tasks_path)["tasks"][0]["status"] == "open"


def test_summarize_library_stall_parks_from_evidence():
    row = _stall_row("eng-20260922-05", parked_policy="reburn_loop")
    row["evidence"]["stall_triage"] = {
        "focus_ticker": "HEI.DE",
        "filing_gaps": 6,
        "reburn_loop": True,
        "reburn_investigation": {
            "allow_unpark": True,
            "blockers": [],
            "primary_hypothesis": "scope_too_broad_secondary",
        },
    }
    summary = summarize_library_stall_parks([row])
    assert len(summary) == 1
    assert summary[0]["focus_ticker"] == "HEI.DE"
    assert summary[0]["allow_unpark"] is True


def test_triage_cancels_resolved_stall(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(json.dumps({"tasks": [_stall_row("eng-20260922-05")]}), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.library_stall_task_triage.snapshot_library_buy_tier_filing_health",
        lambda market_id, **kwargs: {
            "unmeasured_buy_tier": 0,
            "zero_body_buy_tier": 0,
            "snapshot_at": "2026-09-22T00:00:00+00:00",
        },
    )

    result = triage_library_stall_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_cancel_superseded=False,
        auto_cancel_resolved=True,
        auto_annotate=False,
    )
    assert any(row.action == "cancel_resolved_library_stall" for row in result.cancelled)
