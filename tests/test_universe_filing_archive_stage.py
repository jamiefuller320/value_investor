"""Tests for cold-store archive pack stage ladder + quiet-night auto-widen."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.ops_monitor import check_universe_filing_archive_auto_widen
from value_investor.storage import write_json
from value_investor.universe_filing_archive_stage import (
    FINDING_TITLE_AUTO_WIDEN,
    MAX_DOCUMENTED_STAGE,
    QUIET_NIGHTS_REQUIRED,
    advance_stage_ladder,
    caps_for_stage,
    classify_quiet_night,
    ops_finding_from_stage_ladder,
    resolve_apply_caps,
)
from value_investor.universe_filing_archive_status import (
    build_universe_filing_archive_status,
)


def _clean_iso(**extra: object) -> dict:
    isolation = {
        "isolation_ok": True,
        "shared_critical_path": False,
        "fourth_equal_sprint_stream": False,
    }
    isolation.update({k: v for k, v in extra.items() if k in isolation})
    return isolation


def test_classify_clean_and_reset() -> None:
    assert classify_quiet_night(
        outcome="apply_complete",
        dry_run=False,
        isolation=_clean_iso(),
    )[0] == "clean"
    assert classify_quiet_night(
        outcome="suspend",
        dry_run=False,
        isolation=_clean_iso(),
    )[0] == "reset"
    assert classify_quiet_night(
        outcome="apply_complete",
        dry_run=False,
        isolation=_clean_iso(isolation_ok=False),
    )[0] == "reset"
    assert classify_quiet_night(
        outcome="apply_complete",
        dry_run=False,
        isolation=_clean_iso(shared_critical_path=True),
    )[0] == "reset"
    assert classify_quiet_night(
        outcome="dry_complete",
        dry_run=True,
        isolation=_clean_iso(),
    )[0] == "ignore"


def test_advance_promotes_after_required_streak() -> None:
    state: dict = {"stage_ladder": {"current_stage": 2, "quiet_isolation_ok_streak": 0}}
    now = datetime(2026, 11, 10, 22, 0, tzinfo=UTC)
    for i in range(QUIET_NIGHTS_REQUIRED - 1):
        state = advance_stage_ladder(
            state,
            outcome="apply_complete",
            dry_run=False,
            isolation=_clean_iso(),
            run_id=f"run-{i}",
            now=now,
        )
        assert state["promoted"] is False
        assert state["current_stage"] == 2
        assert state["quiet_isolation_ok_streak"] == i + 1

    state = advance_stage_ladder(
        state,
        outcome="apply_complete",
        dry_run=False,
        isolation=_clean_iso(),
        run_id="run-promote",
        now=now,
    )
    assert state["promoted"] is True
    assert state["current_stage"] == 3
    assert state["quiet_isolation_ok_streak"] == 0
    assert state["current_caps"] == caps_for_stage(3)
    assert state["last_auto_widen"]["from_stage"] == 2
    assert state["last_auto_widen"]["to_stage"] == 3


def test_advance_resets_on_suspend_mid_streak() -> None:
    state = advance_stage_ladder(
        {"stage_ladder": {"current_stage": 2, "quiet_isolation_ok_streak": 3}},
        outcome="suspend",
        dry_run=False,
        isolation=_clean_iso(),
        run_id="suspend-1",
    )
    assert state["quiet_isolation_ok_streak"] == 0
    assert state["current_stage"] == 2
    assert state["promoted"] is False
    assert state["last_reset_reason"] == "outcome=suspend"


def test_advance_does_not_pass_ceiling() -> None:
    state = {"stage_ladder": {"current_stage": MAX_DOCUMENTED_STAGE, "quiet_isolation_ok_streak": 0}}
    for i in range(QUIET_NIGHTS_REQUIRED + 2):
        state = advance_stage_ladder(
            state,
            outcome="apply_complete",
            dry_run=False,
            isolation=_clean_iso(),
            run_id=f"ceil-{i}",
        )
    assert state["current_stage"] == MAX_DOCUMENTED_STAGE
    assert state["at_ceiling"] is True
    assert state["promoted"] is False
    assert state["quiet_isolation_ok_streak"] == QUIET_NIGHTS_REQUIRED + 2


def test_advance_idempotent_same_run_id() -> None:
    prior = {"stage_ladder": {"current_stage": 2, "quiet_isolation_ok_streak": 1}}
    first = advance_stage_ladder(
        prior,
        outcome="apply_complete",
        dry_run=False,
        isolation=_clean_iso(),
        run_id="same",
    )
    second = advance_stage_ladder(
        first,
        outcome="apply_complete",
        dry_run=False,
        isolation=_clean_iso(),
        run_id="same",
    )
    assert first["quiet_isolation_ok_streak"] == 2
    assert second["quiet_isolation_ok_streak"] == 2


def test_resolve_caps_prefer_stage_ladder(tmp_path: Path) -> None:
    status_path = tmp_path / "status.json"
    write_json(
        status_path,
        {
            "stage_ladder": {
                "current_stage": 3,
                "quiet_isolation_ok_streak": 0,
                "current_caps": caps_for_stage(3),
            }
        },
    )
    resolved = resolve_apply_caps(status_path=status_path)
    assert resolved["max_units"] == 16
    assert resolved["max_http_fetches"] == 64
    assert resolved["from_stage_ladder"] is True

    overridden = resolve_apply_caps(
        max_units=4,
        max_http_fetches=16,
        status_path=status_path,
    )
    assert overridden["max_units"] == 4
    assert overridden["max_http_fetches"] == 16
    assert overridden["from_stage_ladder"] is False


def test_ops_finding_recent_auto_widen() -> None:
    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    finding = ops_finding_from_stage_ladder(
        {
            "last_auto_widen": {
                "at": "2026-11-10T04:00:00+00:00",
                "from_stage": 2,
                "to_stage": 3,
                "to_caps": caps_for_stage(3),
                "required_streak": 5,
                "run_id": "uap-x",
            }
        },
        now=now,
    )
    assert finding is not None
    assert finding["title"] == FINDING_TITLE_AUTO_WIDEN
    assert finding["auto_fixable"] is False
    assert finding["severity"] == "info"

    stale = ops_finding_from_stage_ladder(
        {
            "last_auto_widen": {
                "at": "2026-11-01T04:00:00+00:00",
                "from_stage": 2,
                "to_stage": 3,
                "to_caps": caps_for_stage(3),
            }
        },
        now=now,
    )
    assert stale is None


def test_ops_monitor_check_reads_status(tmp_path: Path) -> None:
    status_path = tmp_path / "status.json"
    write_json(
        status_path,
        {
            "stage_ladder": {
                "current_stage": 3,
                "last_auto_widen": {
                    "at": "2026-11-10T04:00:00+00:00",
                    "from_stage": 2,
                    "to_stage": 3,
                    "to_caps": caps_for_stage(3),
                    "required_streak": 5,
                },
            }
        },
    )
    findings = check_universe_filing_archive_auto_widen(
        status_path=status_path,
        now=datetime(2026, 11, 10, 12, 0, tzinfo=UTC),
    )
    assert len(findings) == 1
    assert findings[0].title == FINDING_TITLE_AUTO_WIDEN
    assert findings[0].auto_fixable is False


def test_status_panel_shows_streak_progress() -> None:
    payload = build_universe_filing_archive_status(
        pack_run={
            "generated_at": "2026-11-10T22:05:00+00:00",
            "run_id": "uap-1",
            "outcome": "apply_complete",
            "dry_run": False,
            "gate": {"decision": "allow", "allowed": True},
            "max_units": 8,
            "capacity_isolation": _clean_iso(),
            "assemble_caps": {"max_http_fetches": 32},
            "fourth_equal_sprint_stream": False,
        },
        bottleneck={"errors": []},
        prior_status={
            "stage_ladder": {
                "current_stage": 2,
                "quiet_isolation_ok_streak": 2,
                "current_caps": caps_for_stage(2),
            }
        },
        now=datetime(2026, 11, 11, 8, 0, tzinfo=UTC),
    )
    assert payload["stage_ladder"]["quiet_isolation_ok_streak"] == 3
    assert payload["stage_ladder"]["current_stage"] == 2
    assert payload["next_widen_step"]["id"] == "accumulate_quiet_nights"
    assert "3/5" in payload["next_widen_step"]["label"]


def test_status_panel_auto_widen_event() -> None:
    payload = build_universe_filing_archive_status(
        pack_run={
            "generated_at": "2026-11-10T22:05:00+00:00",
            "run_id": "uap-promote",
            "outcome": "apply_complete",
            "dry_run": False,
            "gate": {"decision": "allow", "allowed": True},
            "max_units": 8,
            "capacity_isolation": _clean_iso(),
            "assemble_caps": {"max_http_fetches": 32},
        },
        bottleneck={"errors": []},
        prior_status={
            "stage_ladder": {
                "current_stage": 2,
                "quiet_isolation_ok_streak": QUIET_NIGHTS_REQUIRED - 1,
                "current_caps": caps_for_stage(2),
            }
        },
        now=datetime(2026, 11, 10, 22, 5, tzinfo=UTC),
    )
    assert payload["stage_ladder"]["promoted"] is True
    assert payload["stage_ladder"]["current_stage"] == 3
    assert payload["current_caps"]["max_units"] == 16
    assert payload["next_widen_step"]["id"] == "auto_widened"
