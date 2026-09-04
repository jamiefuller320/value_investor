"""Tests for deterministic learning-path system-gap snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.system_gap_analysis import (
    build_system_gap_snapshot,
    slim_system_gaps_for_review,
    write_system_gap_snapshot,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _memo(
    root: Path,
    ticker: str,
    *,
    verdict: str | None = "accumulate",
    grade: str = "strong",
    bodies: int = 20,
    mode: str = "refresh",
) -> None:
    _write_json(
        root / ticker / "research.json",
        {
            "ticker": ticker,
            "name": ticker,
            "research_verdict": verdict,
            "mode": mode,
            "memo_quality": {"grade": grade, "filings_with_body": bodies},
        },
    )


def test_snapshot_flags_unwired_committed_verdicts(tmp_path: Path):
    data = tmp_path / "data"
    committed = data / "research"
    _memo(committed, "JSG.L")
    _memo(committed, "MONY.L")
    _memo(committed, "VTY.L")
    _memo(committed, "BREE.L")
    _write_json(
        data / "latest.json",
        {
            "research": [{"ticker": "AZN.L", "research_verdict": "accumulate"}],
            "reports": [
                {"ticker": "JSG.L", "signal": "strong_buy"},
                {"ticker": "MONY.L", "signal": "strong_buy"},
                {"ticker": "VTY.L", "signal": "buy"},
                {"ticker": "BREE.L", "signal": "buy"},
                {"ticker": "AZN.L", "signal": "buy", "research_verdict": "accumulate"},
            ],
        },
    )
    snapshot = build_system_gap_snapshot(
        data_dir=data,
        output_dir=tmp_path / "output",
        library_root=tmp_path / "library",
        committed_research=committed,
        paper_root=data / "paper_automation",
        policy_path=tmp_path / "missing-policy.json",
    )
    ids = {row["id"] for row in snapshot["flags"]}
    assert "buy_tier_unwired_verdict" in ids
    assert "overlay_lagging_committed" in ids
    assert "research_index_shrunk" in ids
    apply_layer = snapshot["layers"]["apply"]
    assert apply_layer["buy_tier_count"] == 5
    assert apply_layer["buy_tier_wired_count"] == 1
    assert "JSG.L" in apply_layer["buy_tier_unwired_with_committed_verdict"]


def test_snapshot_flags_thin_memos_and_unused_budget(tmp_path: Path):
    data = tmp_path / "data"
    library = tmp_path / "library"
    focus_research = library / "markets" / "euro_depth" / "screen" / "research"
    for ticker in ("ABI.BR", "AZE.BR", "NOVN.SW", "SHELL.AS", "TTE.PA", "ASML.AS"):
        _memo(focus_research, ticker, verdict=None, grade="thin", bodies=0, mode="initial")
        (focus_research / ticker / "research.md").write_text("memo", encoding="utf-8")
    _write_json(
        library / "last_ladder.json",
        {
            "run_at": "2026-09-02T12:00:00+00:00",
            "focus_market": "euro_depth",
            "plan": {"allow_research": True},
            "layers": {
                "selective_research": {
                    "executed": 0,
                    "allow_research": True,
                    "constraining": False,
                    "budget_flag": "enforced",
                    "remaining_usd_before": 72.8,
                    "dedupe": {
                        "already_researched_count": 44,
                        "skipped_count": 44,
                        "skipped_sample": [{"reason": "already_researched", "ticker": "ABI.BR"}],
                    },
                }
            },
        },
    )
    _write_json(
        library / "policy.json",
        {
            "focus_market": "euro_depth",
            "budget": {
                "weekly_ops_cap_usd": 80,
                "estimated_spend_weekly_ops_usd_this_week": 17.2,
                "enforce_weekly_ops_cap": True,
            },
            "ladder": {"estimated_memo_usd": 0.4},
        },
    )
    snapshot = build_system_gap_snapshot(
        data_dir=data,
        output_dir=tmp_path / "output",
        library_root=library,
        policy_path=library / "policy.json",
        paper_root=data / "paper_automation",
    )
    ids = {row["id"] for row in snapshot["flags"]}
    assert "thin_memo_counted_as_coverage" in ids
    assert "research_skipped_already_done" in ids
    assert "unused_budget_zero_research" in ids


def test_snapshot_flags_persist_hole_and_stale_learning_clock(tmp_path: Path):
    data = tmp_path / "data"
    paper = data / "paper_automation"
    paper.mkdir(parents=True)
    (paper / "ai_judgment").mkdir()
    output = tmp_path / "output"
    _write_json(
        output / "paper_automation" / "learning_tracks_entry_dca.json",
        {"episodes": 3},
    )
    library = tmp_path / "library"
    _write_json(
        library / "markets" / "sp500" / "learning_depth.json",
        {
            "filing_ready": True,
            "learning_ready": False,
            "trajectory_ready": False,
            "screen": {
                "stale": True,
                "unique_days": 7,
                "last_screen": "2026-08-16",
                "archive_files": 12,
            },
        },
    )
    _write_json(
        library / "policy.json",
        {"focus_market": "euro_depth", "ladder": {"observe_sim_markets": ["sp500"]}},
    )
    snapshot = build_system_gap_snapshot(
        data_dir=data,
        output_dir=output,
        library_root=library,
        policy_path=library / "policy.json",
        paper_root=paper,
    )
    ids = {row["id"] for row in snapshot["flags"]}
    assert "overlay_persist_hole" in ids
    assert "filing_ready_learning_stale" in ids
    assert "observe_clock_stale" in ids
    persist = snapshot["layers"]["persist"]
    assert persist["persist_hole"] is True
    assert "learning_tracks_entry_dca.json" in persist["in_output_not_committed"]


def test_slim_and_write_round_trip(tmp_path: Path):
    data = tmp_path / "data"
    _write_json(data / "latest.json", {"reports": [], "research": []})
    snapshot = build_system_gap_snapshot(
        data_dir=data,
        output_dir=tmp_path / "output",
        library_root=tmp_path / "library",
        paper_root=data / "paper_automation",
        policy_path=tmp_path / "missing.json",
    )
    slim = slim_system_gaps_for_review(snapshot)
    assert slim is not None
    assert slim["probe_questions"]
    assert "healthy_counter_distrust" in slim
    path = write_system_gap_snapshot(snapshot, path=data / "system_gaps.json")
    assert path.exists()
    assert '"schema_version"' in path.read_text(encoding="utf-8")
