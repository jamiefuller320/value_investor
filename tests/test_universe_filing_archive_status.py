"""Tests for thin cold-store archive pack status panel (L521)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.universe_filing_archive_status import (
    PILOT_CAPS,
    WIDEN_CRITERIA,
    build_universe_filing_archive_status,
    write_universe_filing_archive_status,
)


def test_status_missing_pack_run() -> None:
    payload = build_universe_filing_archive_status(
        pack_run={},
        bottleneck={},
        now=datetime(2026, 10, 2, 18, 0, tzinfo=UTC),
    )
    assert payload["present"] is False
    assert payload["last_run"]["badge"] == "missing"
    assert payload["observe_only"] is True
    assert payload["auto_fixable"] is False


def test_status_dry_complete_next_widen_need_apply() -> None:
    pack_run = {
        "generated_at": "2026-10-02T01:17:18+00:00",
        "run_id": "uap-test",
        "outcome": "dry_complete",
        "dry_run": True,
        "pack_order": "week_first_then_backward",
        "gate": {"decision": "allow", "allowed": True, "in_quiet_window": True},
        "plan_unit_count": 192,
        "units_attempted": 0,
        "units_completed": 0,
        "objects_written": 0,
        "fourth_equal_sprint_stream": False,
        "preemptible": True,
        "capacity_isolation": {
            "isolation_ok": True,
            "shared_critical_path": False,
            "fourth_equal_sprint_stream": False,
            "http_fetches": 0,
        },
        "max_units": 2,
    }
    payload = build_universe_filing_archive_status(
        pack_run=pack_run,
        bottleneck={"errors": [], "throughput": {}, "bottlenecks": []},
        now=datetime(2026, 10, 2, 18, 0, tzinfo=UTC),
    )
    assert payload["present"] is True
    assert payload["last_run"]["outcome"] == "dry_complete"
    assert payload["last_run"]["mode"] == "dry"
    assert payload["last_run"]["badge"] == "ok"
    assert payload["last_run"]["hours_since"] == 16.71
    assert payload["clash_flags"]["isolation_ok"] is True
    assert payload["clash_flags"]["fourth_equal_sprint_stream"] is False
    assert payload["next_widen_step"]["id"] == "need_apply_nights"
    assert payload["current_caps"]["max_units"] == PILOT_CAPS["max_units"]
    assert WIDEN_CRITERIA in payload["next_widen_step"]["widen_criteria"]


def test_status_apply_isolation_ok_accumulate() -> None:
    pack_run = {
        "generated_at": "2026-10-02T22:05:00+00:00",
        "run_id": "uap-apply",
        "outcome": "apply_complete",
        "dry_run": False,
        "gate": {"decision": "allow", "allowed": True, "focus_pressure_reasons": []},
        "max_units": 2,
        "units_attempted": 2,
        "units_completed": 2,
        "objects_written": 3,
        "fourth_equal_sprint_stream": False,
        "capacity_isolation": {
            "isolation_ok": True,
            "shared_critical_path": False,
            "http_fetches": 4,
            "fourth_equal_sprint_stream": False,
        },
        "assemble_caps": {"max_http_fetches": 8, "max_tickers_per_unit": 2},
    }
    payload = build_universe_filing_archive_status(
        pack_run=pack_run,
        bottleneck={"errors": []},
        now=datetime(2026, 10, 3, 8, 0, tzinfo=UTC),
    )
    assert payload["last_run"]["mode"] == "apply"
    assert payload["next_widen_step"]["id"] == "accumulate_quiet_nights"
    assert "max_units=2" in payload["next_widen_step"]["detail"]


def test_status_failures_hold_widen() -> None:
    payload = build_universe_filing_archive_status(
        pack_run={
            "generated_at": "2026-10-02T22:05:00+00:00",
            "outcome": "apply_complete",
            "dry_run": False,
            "gate": {"decision": "allow", "allowed": True},
            "capacity_isolation": {"isolation_ok": True, "shared_critical_path": False},
        },
        bottleneck={"errors": ["sec: 429 rate limited"]},
        now=datetime(2026, 10, 3, 8, 0, tzinfo=UTC),
    )
    assert payload["last_run"]["badge"] == "fail"
    assert payload["last_run"]["error_count"] == 1
    assert payload["next_widen_step"]["id"] == "fix_failures"


def test_status_isolation_fail_holds() -> None:
    payload = build_universe_filing_archive_status(
        pack_run={
            "generated_at": "2026-10-02T22:05:00+00:00",
            "outcome": "apply_complete",
            "dry_run": False,
            "gate": {"decision": "allow", "allowed": True},
            "capacity_isolation": {
                "isolation_ok": False,
                "shared_critical_path": True,
                "fourth_equal_sprint_stream": False,
            },
        },
        bottleneck={"errors": []},
        now=datetime(2026, 10, 3, 8, 0, tzinfo=UTC),
    )
    assert payload["next_widen_step"]["id"] == "hold_isolation"
    assert payload["clash_flags"]["shared_critical_path"] is True


def test_status_suspend_waits_gate() -> None:
    payload = build_universe_filing_archive_status(
        pack_run={
            "generated_at": "2026-10-02T22:05:00+00:00",
            "outcome": "suspend",
            "dry_run": True,
            "gate": {
                "decision": "suspend",
                "allowed": False,
                "focus_pressure_reasons": ["focus_fat_slot_sprint_active"],
            },
        },
        bottleneck={"errors": []},
        now=datetime(2026, 10, 3, 8, 0, tzinfo=UTC),
    )
    assert payload["last_run"]["badge"] == "warn"
    assert payload["next_widen_step"]["id"] == "wait_gate"
    assert payload["clash_flags"]["focus_pressure"] is True


def test_write_status_persists(tmp_path: Path) -> None:
    pack_path = tmp_path / "pack_run.json"
    bn_path = tmp_path / "bn.json"
    status_path = tmp_path / "status.json"
    pack_path.write_text(
        '{"generated_at":"2026-10-02T01:00:00+00:00","outcome":"dry_complete","dry_run":true,"gate":{"decision":"allow","allowed":true},"capacity_isolation":{"isolation_ok":true,"shared_critical_path":false}}',
        encoding="utf-8",
    )
    bn_path.write_text('{"errors":[],"bottlenecks":[]}', encoding="utf-8")
    payload = write_universe_filing_archive_status(
        pack_run_path=pack_path,
        bottleneck_path=bn_path,
        status_path=status_path,
        now=datetime(2026, 10, 2, 12, 0, tzinfo=UTC),
    )
    assert status_path.exists()
    assert payload["last_run"]["outcome"] == "dry_complete"
