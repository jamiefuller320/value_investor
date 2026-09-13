"""Tests for deliberate automated Phase C readiness assessment."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.phase_c_readiness import (
    assess_phase_c_readiness,
    check_phase_b_slim,
    check_rebalance_log_span,
)


def test_phase_b_check_passes_with_structured_docs(tmp_path: Path):
    for i, mode in enumerate(
        ["structured_verdict", "structured_verdict_update", "structured_verdict_gap_fill"]
    ):
        ticker_dir = tmp_path / f"T{i}.L"
        ticker_dir.mkdir()
        (ticker_dir / "research.json").write_text(
            json.dumps({"mode": mode, "research_verdict": "accumulate"}),
            encoding="utf-8",
        )
    check = check_phase_b_slim(tmp_path)
    assert check.status == "pass"


def test_phase_b_check_fails_without_structured_docs(tmp_path: Path):
    ticker_dir = tmp_path / "AAA.L"
    ticker_dir.mkdir()
    (ticker_dir / "research.json").write_text(
        json.dumps({"mode": "initial", "research_verdict": "accumulate"}),
        encoding="utf-8",
    )
    check = check_phase_b_slim(tmp_path)
    assert check.status == "fail"


def test_rebalance_span_check(tmp_path: Path):
    start = datetime(2026, 7, 1, tzinfo=UTC)
    entries = []
    for day in range(0, 70, 7):
        entries.append(
            {
                "logged_at": (start + timedelta(days=day)).isoformat(),
                "screen_buy_tier": [{"ticker": "AAA.L"}],
                "candidates": [{"ticker": "AAA.L"}],
                "acted": True,
            }
        )
    (tmp_path / "rebalance_log.json").write_text(json.dumps(entries), encoding="utf-8")
    check = check_rebalance_log_span(tmp_path)
    assert check.status == "pass"
    assert check.evidence["span_days"] >= 56


def test_assess_not_ready_without_prereqs(tmp_path: Path):
    report = assess_phase_c_readiness(
        ai_judgment_dir=tmp_path / "missing_ai",
        research_root=tmp_path / "missing_research",
        latest_path=tmp_path / "missing_latest.json",
    )
    assert report.ready is False
    assert any(c.status != "pass" for c in report.checks)


def test_force_phase_b_override(tmp_path: Path):
    check = check_phase_b_slim(tmp_path, force_phase_b_done=True)
    assert check.status == "pass"
    assert check.evidence.get("forced") is True
