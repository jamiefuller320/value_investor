"""Screening snapshot persistence and research verdict propagation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.research.verdict import compute_adjusted_signal
from value_investor.scoring.fcf import screen_ttm_from_row
from value_investor.scoring.fcf_basis_overlay import apply_fcf_export_enforcement
from value_investor.storage import read_json, write_json


def merge_research_verdict_into_snapshot(
    snapshot: dict[str, Any],
    *,
    research_verdict: str | None,
    research_risk_level: str | None = None,
    research_confidence: float | None = None,
    research_rationale: str | None = None,
) -> dict[str, Any]:
    """Overlay structured research verdict fields onto a screening snapshot dict."""
    if not research_verdict:
        return snapshot

    updated = dict(snapshot)
    updated["research_verdict"] = research_verdict
    if research_risk_level is not None:
        updated["research_risk_level"] = research_risk_level
    if research_confidence is not None:
        updated["research_confidence"] = research_confidence
    if research_rationale is not None:
        updated["research_rationale"] = research_rationale

    screen_signal = str(updated.get("signal") or "hold")
    research_adjusted = compute_adjusted_signal(screen_signal, research_verdict)  # type: ignore[arg-type]
    fcf = updated.get("fcf") if isinstance(updated.get("fcf"), dict) else {}
    screen_ttm = fcf.get("screen_ttm")
    if screen_ttm is None:
        screen_ttm = screen_ttm_from_row(pd.Series(updated))

    overlay, adjusted, conviction = apply_fcf_export_enforcement(
        signal=screen_signal,
        adjusted_signal=research_adjusted,
        conviction_score=float(updated.get("conviction_score") or 0.0),
        action_note=str(updated.get("action_note") or ""),
        fcf_basis_overlay=bool(updated.get("fcf_basis_overlay")),
        fcf_bundle=fcf if fcf else None,
        screen_ttm=screen_ttm,
    )
    updated["adjusted_signal"] = adjusted
    updated["fcf_basis_overlay"] = overlay
    updated["conviction_score"] = conviction
    return updated


def write_screening_snapshot(sources_dir: Path, snapshot: dict[str, Any]) -> Path:
    sources_dir.mkdir(parents=True, exist_ok=True)
    path = sources_dir / "screening_snapshot.json"
    write_json(path, snapshot, compact=True, compress=False)
    return path


def refresh_snapshot_from_document(output_dir: Path, doc: Any) -> bool:
    """Merge gap-fill verdict fields into an on-disk ``screening_snapshot.json``."""
    if not doc.research_verdict:
        return False

    snapshot_path = output_dir / "research" / doc.ticker / "sources" / "screening_snapshot.json"
    if not snapshot_path.exists():
        return False

    snapshot = read_json(snapshot_path)
    if not isinstance(snapshot, dict):
        return False

    merged = merge_research_verdict_into_snapshot(
        snapshot,
        research_verdict=doc.research_verdict,
        research_risk_level=doc.research_risk_level,
        research_confidence=doc.research_confidence,
        research_rationale=doc.research_rationale,
    )
    write_json(snapshot_path, merged, compact=True, compress=False)
    return True


def sync_research_verdict_snapshots(
    output_dir: Path,
    reports: list[Any],
    documents: list[Any],
) -> int:
    """Write research overlay fields back to per-ticker screening snapshots."""
    by_ticker = {doc.ticker: doc for doc in documents if doc.research_verdict}
    if not by_ticker:
        return 0

    report_by_ticker = {report.ticker: report for report in reports}
    updated = 0
    for ticker, doc in by_ticker.items():
        report = report_by_ticker.get(ticker)
        sources_dir = output_dir / "research" / ticker / "sources"
        if report is not None:
            snapshot = merge_research_verdict_into_snapshot(
                report.to_dict(),
                research_verdict=doc.research_verdict,
                research_risk_level=doc.research_risk_level,
                research_confidence=doc.research_confidence,
                research_rationale=doc.research_rationale,
            )
            write_screening_snapshot(sources_dir, snapshot)
            updated += 1
        elif refresh_snapshot_from_document(output_dir, doc):
            updated += 1
    return updated
