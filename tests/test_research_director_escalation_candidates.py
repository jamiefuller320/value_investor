"""Tests for director escalation candidate aggregation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.research.director_escalation_candidates import (
    aggregate_escalation_candidates,
    write_escalation_candidates,
)
from value_investor.research.director_shadow import (
    RECOMMEND_ESCALATE,
    RECOMMEND_MONITOR,
    RECOMMEND_RE_ESCALATE,
    append_shadow_log_entry,
)


def _candidate_entry(
    ticker: str,
    *,
    action: str = RECOMMEND_ESCALATE,
    recorded_at: str,
) -> dict:
    return {
        "ticker": ticker,
        "research_action": "updated",
        "recommended_action": action,
        "recorded_at": recorded_at,
        "escalation": {
            "should_escalate": True,
            "triggers": ["thin_sources"],
            "reasons": ["Source quality grade is thin"],
        },
        "material_change": None,
    }


def test_aggregate_prefers_newer_run_entry_over_log(tmp_path: Path):
    log_path = tmp_path / "shadow_log.json"
    week_time = datetime(2026, 8, 13, 12, 0, tzinfo=UTC).isoformat()
    append_shadow_log_entry(
        _candidate_entry("VTY.L", recorded_at=week_time),
        path=log_path,
    )
    run_entries = [
        _candidate_entry(
            "VTY.L",
            action=RECOMMEND_RE_ESCALATE,
            recorded_at=datetime(2026, 8, 13, 18, 0, tzinfo=UTC).isoformat(),
        )
    ]
    summary = aggregate_escalation_candidates(
        run_entries=run_entries,
        shadow_log_path=log_path,
        when=datetime(2026, 8, 13, 20, 0, tzinfo=UTC),
    )
    assert len(summary.candidates) == 1
    assert summary.candidates[0]["recommended_action"] == RECOMMEND_RE_ESCALATE


def test_aggregate_filters_non_candidate_actions(tmp_path: Path):
    log_path = tmp_path / "shadow_log.json"
    week_time = datetime(2026, 8, 13, 12, 0, tzinfo=UTC).isoformat()
    append_shadow_log_entry(
        {
            **_candidate_entry("AAA.L", recorded_at=week_time),
            "recommended_action": RECOMMEND_MONITOR,
        },
        path=log_path,
    )
    append_shadow_log_entry(
        _candidate_entry("BBB.L", recorded_at=week_time),
        path=log_path,
    )
    summary = aggregate_escalation_candidates(
        shadow_log_path=log_path,
        when=datetime(2026, 8, 13, 20, 0, tzinfo=UTC),
    )
    assert [row["ticker"] for row in summary.candidates] == ["BBB.L"]


def test_write_escalation_candidates_round_trip(tmp_path: Path):
    summary = aggregate_escalation_candidates(
        run_entries=[
            _candidate_entry(
                "MEGP.L",
                recorded_at=datetime(2026, 8, 13, 12, 0, tzinfo=UTC).isoformat(),
            )
        ],
        shadow_log_path=tmp_path / "shadow_log.json",
        when=datetime(2026, 8, 13, 20, 0, tzinfo=UTC),
    )
    path = write_escalation_candidates(summary, path=tmp_path / "candidates.json")
    payload = path.read_text(encoding="utf-8")
    assert "MEGP.L" in payload
    assert summary.auto_escalate_enabled is False
