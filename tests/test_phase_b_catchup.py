"""Tests for Phase B structured-mode catch-up batches."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.research.phase_b_catchup import (
    list_phase_b_backlog,
    run_phase_b_catchup_pass,
    write_phase_b_backlog_status,
)


def _write_research(path: Path, *, mode: str = "initial", verdict: str = "accumulate") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ticker": path.parent.name,
                "name": path.parent.name,
                "signal": "buy",
                "mode": mode,
                "research_verdict": verdict,
                "version": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )


def test_list_phase_b_backlog_essay_modes_only(tmp_path: Path):
    root = tmp_path / "research"
    _write_research(root / "AAA.L" / "research.json", mode="initial")
    _write_research(
        root / "BBB.L" / "research.json",
        mode="structured_verdict_update",
    )
    assert list_phase_b_backlog(committed_dir=root) == ["AAA.L"]


def test_write_phase_b_backlog_status(tmp_path: Path):
    root = tmp_path / "research"
    _write_research(root / "ZZZ.L" / "research.json")
    state = tmp_path / "phase_b_catchup_state.json"
    payload = write_phase_b_backlog_status(
        committed_dir=root,
        latest_path=tmp_path / "missing_latest.json",
        state_path=state,
        recommended_batch=2,
    )
    assert payload["backlog_count"] == 1
    assert state.exists()


@patch("value_investor.research.phase_b_catchup.weekly_ops_budget_status")
def test_run_phase_b_catchup_dry_run(mock_budget, tmp_path: Path):
    mock_budget.return_value = {
        "remaining_weekly_ops_usd": 100.0,
        "constraining": False,
    }
    root = tmp_path / "research"
    _write_research(root / "AAA.L" / "research.json")
    _write_research(root / "BBB.L" / "research.json")
    summary = run_phase_b_catchup_pass(
        api_key=None,
        batch_size=1,
        committed_dir=root,
        latest_path=tmp_path / "latest.json",
        output_dir=tmp_path / "output",
        dry_run=True,
        state_path=tmp_path / "state.json",
        summary_path=tmp_path / "summary.json",
    )
    assert summary.dry_run is True
    assert summary.selected == ["AAA.L"]
    assert summary.updated == []
