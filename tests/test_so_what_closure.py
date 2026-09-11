"""Tests for periodic so-what gap closure."""

from __future__ import annotations

from pathlib import Path

from value_investor.so_what_closure import (
    CLOSURE_AUTO_QUEUE,
    CLOSURE_HUMAN_GATE,
    apply_so_what_auto_queue,
    build_so_what_section,
    group_so_what_rows,
    render_so_what_markdown,
    scan_so_what_issues,
)
from value_investor.storage import read_json, write_json


def _report(
    *,
    ticker: str,
    signal: str = "strong_buy",
    adjusted: str | None = None,
    overlay: bool = False,
    screen: float = 200.0,
    filing: float | None = 100.0,
    note: str = "Strong Buy | FCF basis mismatch: filing vs screen TTM",
) -> dict:
    return {
        "ticker": ticker,
        "signal": signal,
        "adjusted_signal": adjusted if adjusted is not None else signal,
        "fcf_basis_overlay": overlay,
        "action_note": note,
        "fcf": {"screen_ttm": screen, "filing_aligned": filing},
    }


def test_scan_flags_uncapped_buy_tier_mismatch(tmp_path: Path):
    findings = scan_so_what_issues(
        reports=[_report(ticker="FAKE.L")],
        artifacts_dir=tmp_path,
    )
    kinds = {f.kind for f in findings}
    closures = {f.recommended_closure for f in findings}
    assert "fcf_enforcement_gap" in kinds
    assert CLOSURE_AUTO_QUEUE in closures
    # Filing present ⇒ auto majority / filing fallback; no human bridge gate.
    assert CLOSURE_HUMAN_GATE not in closures
    assert "fcf_bridge_needed" not in kinds


def test_scan_human_gate_only_without_auto_resolvable_basis(tmp_path: Path):
    report = {
        "ticker": "NOFILING.L",
        "signal": "buy",
        "adjusted_signal": "buy",
        "fcf_basis_overlay": True,
        "action_note": "Buy | FCF basis mismatch: screen TTM only",
        "fcf": {"screen_ttm": 200.0, "filing_aligned": None},
    }
    findings = scan_so_what_issues(reports=[report], artifacts_dir=tmp_path)
    kinds = {f.kind for f in findings}
    assert "fcf_bridge_needed" in kinds
    assert any(f.recommended_closure == CLOSURE_HUMAN_GATE for f in findings)


def test_scan_skips_when_overlay_present_and_bridge_resolved(tmp_path: Path):
    bridge_dir = tmp_path / "research" / "OK.L" / "sources"
    bridge_dir.mkdir(parents=True)
    write_json(
        bridge_dir / "fcf_bridge.json",
        {"resolved": True, "policy_fcf": 200.0, "policy_basis": "filing_aligned"},
        compact=False,
    )
    findings = scan_so_what_issues(
        reports=[_report(ticker="OK.L", overlay=True)],
        artifacts_dir=tmp_path,
    )
    assert findings == []


def test_apply_auto_queue_is_idempotent(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    snap_path = tmp_path / "so_what_closure.json"
    write_json(tasks_path, {"tasks": []}, compact=False)
    findings = scan_so_what_issues(
        reports=[_report(ticker="FAKE.L")],
        artifacts_dir=tmp_path,
    )
    first = apply_so_what_auto_queue(
        findings,
        dry_run=False,
        tasks_path=tasks_path,
        snapshot_path=snap_path,
        artifacts_dir=tmp_path,
    )
    second = apply_so_what_auto_queue(
        findings,
        dry_run=False,
        tasks_path=tasks_path,
        snapshot_path=snap_path,
        artifacts_dir=tmp_path,
    )
    assert first["counts"]["tasks_created"] == 1
    assert second["counts"]["tasks_created"] == 0
    assert second["counts"]["tasks_skipped"] == 1
    payload = read_json(tasks_path)
    so_what_tasks = [t for t in payload["tasks"] if t.get("source") == "so_what_closure"]
    assert len(so_what_tasks) == 1
    assert so_what_tasks[0]["area"] == "scoring"
    assert so_what_tasks[0]["status"] == "open"
    assert so_what_tasks[0]["evidence"]["batched"] is True


def test_apply_auto_queue_batches_same_kind_tickers(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    snap_path = tmp_path / "so_what_closure.json"
    write_json(tasks_path, {"tasks": []}, compact=False)
    findings = scan_so_what_issues(
        reports=[
            _report(ticker="ALPHA.L"),
            _report(ticker="BETA.L"),
        ],
        artifacts_dir=tmp_path,
    )
    out = apply_so_what_auto_queue(
        findings,
        dry_run=False,
        tasks_path=tasks_path,
        snapshot_path=snap_path,
        artifacts_dir=tmp_path,
    )
    assert out["counts"]["tasks_created"] == 1
    payload = read_json(tasks_path)
    task = payload["tasks"][0]
    assert task["title"] == "Close FCF basis enforcement gap (batched tickers)"
    assert set(task["evidence"]["tickers"]) == {"ALPHA.L", "BETA.L"}
    assert task["evidence"]["finding_count"] == 2


def test_dry_run_does_not_write_tasks(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    snap_path = tmp_path / "so_what_closure.json"
    write_json(tasks_path, {"tasks": []}, compact=False)
    findings = scan_so_what_issues(
        reports=[_report(ticker="FAKE.L")],
        artifacts_dir=tmp_path,
    )
    out = apply_so_what_auto_queue(
        findings,
        dry_run=True,
        tasks_path=tasks_path,
        snapshot_path=snap_path,
        artifacts_dir=tmp_path,
    )
    assert out["counts"]["tasks_created"] == 1
    assert read_json(tasks_path)["tasks"] == []
    assert not snap_path.exists()


def test_build_section_and_markdown(tmp_path: Path):
    latest = tmp_path / "latest.json"
    write_json(latest, {"reports": [_report(ticker="FAKE.L")]}, compact=False)
    section = build_so_what_section(
        apply=False,
        latest_path=latest,
        artifacts_dir=tmp_path,
        tasks_path=tmp_path / "engineering_tasks.json",
        snapshot_path=tmp_path / "so_what_closure.json",
    )
    assert section["counts"]["auto_queue"] >= 1
    md = render_so_what_markdown(section)
    assert "So what?" in md
    assert "FAKE.L" in md


def test_group_so_what_rows_collapses_same_kind():
    rows = [
        {
            "finding_id": "fcf_bridge_needed:AAA.L",
            "kind": "fcf_bridge_needed",
            "ticker": "AAA.L",
            "severity": "medium",
            "so_what": "missing filing",
            "recommended_closure": CLOSURE_HUMAN_GATE,
            "human_action": "write docs/data/research/AAA.L/sources/fcf_bridge.json",
            "human_doc_path": "docs/ops/fcf-basis-bridges.md",
        },
        {
            "finding_id": "fcf_bridge_needed:BBB.L",
            "kind": "fcf_bridge_needed",
            "ticker": "BBB.L",
            "severity": "medium",
            "so_what": "missing filing",
            "recommended_closure": CLOSURE_HUMAN_GATE,
            "human_action": "write docs/data/research/BBB.L/sources/fcf_bridge.json",
            "human_doc_path": "docs/ops/fcf-basis-bridges.md",
        },
    ]
    groups = group_so_what_rows(rows)
    assert len(groups) == 1
    assert groups[0]["count"] == 2
    assert groups[0]["tickers"] == ["AAA.L", "BBB.L"]
    assert "<ticker>" in (groups[0]["human_action"] or "")


def test_markdown_groups_same_issue_names(tmp_path: Path):
    latest = tmp_path / "latest.json"
    write_json(
        latest,
        {
            "reports": [
                _report(ticker="AAA.L", filing=None, overlay=True),
                _report(ticker="BBB.L", filing=None, overlay=True),
            ]
        },
        compact=False,
    )
    section = build_so_what_section(
        apply=False,
        latest_path=latest,
        artifacts_dir=tmp_path,
        tasks_path=tmp_path / "engineering_tasks.json",
        snapshot_path=tmp_path / "so_what_closure.json",
    )
    assert section["counts"]["human_gate"] >= 2
    assert section["human_gate_groups"]
    assert section["human_gate_groups"][0]["count"] >= 2
    md = render_so_what_markdown(section)
    assert "names" in md
    assert "AAA.L" in md and "BBB.L" in md


def test_scan_backfills_filing_from_action_note_clears_bridge_gate(tmp_path: Path):
    """Stale exports keep mismatch notes but drop structured fcf — recover bases."""
    report = {
        "ticker": "ABDN.L",
        "signal": "buy",
        "adjusted_signal": "hold",
        "fcf_basis_overlay": True,
        "action_note": (
            "Buy — favourable entry timing | FCF basis mismatch: filing £406M | "
            "screen TTM £967.8M | RSI 42"
        ),
        "fcf": None,
    }
    findings = scan_so_what_issues(reports=[report], artifacts_dir=tmp_path)
    assert "fcf_bridge_needed" not in {f.kind for f in findings}
