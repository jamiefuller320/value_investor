"""Tests for L389 claimed-vs-landed indicator integrity."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.indicator_integrity import (
    build_research_docs_receipt,
    count_research_store_modes,
    evaluate_indicator_integrity,
    evaluate_research_docs_receipt,
    write_research_docs_receipt,
)
from value_investor.ops_monitor import check_indicator_integrity


def _write_memo(root: Path, ticker: str, *, mode: str, verdict: str | None) -> None:
    path = root / ticker
    path.mkdir(parents=True, exist_ok=True)
    payload: dict = {"ticker": ticker, "mode": mode}
    if verdict is not None:
        payload["research_verdict"] = verdict
    (path / "research.json").write_text(json.dumps(payload), encoding="utf-8")


def test_count_research_store_modes_tracks_verdict_without_structured(tmp_path: Path):
    root = tmp_path / "research"
    _write_memo(root, "AAA.L", mode="initial", verdict="accumulate")
    _write_memo(root, "BBB.L", mode="initial", verdict="neutral")
    _write_memo(root, "CCC.L", mode="structured_verdict", verdict="accumulate")
    stats = count_research_store_modes(root)
    assert stats.sampled == 3
    assert stats.structured == 1
    assert stats.verdict_without_structured == 2


def test_evaluate_verdict_without_structured_mode_flags_deceptive_green(tmp_path: Path):
    root = tmp_path / "research"
    for idx in range(6):
        _write_memo(root, f"T{idx}.L", mode="initial", verdict="accumulate")
    findings = evaluate_indicator_integrity(
        research_root=root,
        receipt_path=tmp_path / "missing.json",
    )
    assert any(f.check_id == "verdict_fields_without_structured_mode" for f in findings)


def test_evaluate_research_docs_receipt_zero_writes(tmp_path: Path):
    now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    (tmp_path / "research").mkdir()
    receipt = build_research_docs_receipt(
        run_at=now,
        created=0,
        updated=0,
        skipped=12,
        errors=[],
        active_count=12,
        alumni_count=0,
        persisted_trees=0,
        touched_tickers=[],
        research_root=tmp_path / "research",
    )
    findings = evaluate_research_docs_receipt(receipt, now=now)
    assert any(f.check_id == "research_docs_claimed_zero_writes" for f in findings)


def test_evaluate_research_docs_receipt_writes_without_persist_or_modes(tmp_path: Path):
    root = tmp_path / "research"
    _write_memo(root, "AAA.L", mode="initial", verdict="accumulate")
    now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    receipt = {
        "claimed": True,
        "run_at": now.isoformat(),
        "created": 2,
        "updated": 1,
        "active_count": 3,
        "alumni_count": 0,
        "persisted_trees": 0,
        "structured_modes_in_committed_after": 0,
        "skipped": 0,
        "error_count": 0,
    }
    stats = count_research_store_modes(root)
    findings = evaluate_research_docs_receipt(receipt, live_stats=stats, now=now)
    ids = {f.check_id for f in findings}
    assert "research_docs_writes_not_persisted" in ids
    assert "research_docs_writes_without_structured_modes" in ids


def test_stale_receipt_is_ignored():
    old = datetime.now(UTC) - timedelta(days=30)
    receipt = {
        "claimed": True,
        "run_at": old.isoformat(),
        "created": 0,
        "updated": 0,
        "active_count": 10,
        "alumni_count": 0,
        "persisted_trees": 0,
    }
    assert evaluate_research_docs_receipt(receipt) == []


def test_write_and_ops_monitor_wrapper(tmp_path: Path):
    root = tmp_path / "research"
    for idx in range(5):
        _write_memo(root, f"Z{idx}.L", mode="initial", verdict="caution")
    receipt = build_research_docs_receipt(
        run_at=datetime.now(UTC),
        created=0,
        updated=0,
        skipped=5,
        errors=["boom"],
        active_count=5,
        alumni_count=0,
        persisted_trees=0,
        touched_tickers=[],
        research_root=root,
    )
    path = write_research_docs_receipt(receipt, committed_path=tmp_path / "receipt.json")
    assert path.is_file()
    findings = check_indicator_integrity(research_root=root, receipt_path=path)
    titles = [f.title.lower() for f in findings]
    assert any("zero memos" in title for title in titles)
    assert any("without structured" in title for title in titles)
