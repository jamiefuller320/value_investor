"""Apply research conviction overlay to screening outputs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from value_investor.research.document import ResearchDocument
from value_investor.research.store import ResearchStore
from value_investor.research.verdict import (
    adjust_conviction_for_research,
    compute_adjusted_signal,
    format_research_action_note,
)
from value_investor.summary import CompanyReport


def _documents_by_ticker(documents: list[ResearchDocument]) -> dict[str, ResearchDocument]:
    return {doc.ticker: doc for doc in documents}


def apply_research_overlay(
    reports: list[CompanyReport],
    documents: list[ResearchDocument],
) -> list[CompanyReport]:
    """Merge structured research verdicts into company reports."""
    by_ticker = _documents_by_ticker(documents)
    if not by_ticker:
        return reports

    updated: list[CompanyReport] = []
    for report in reports:
        doc = by_ticker.get(report.ticker)
        if doc is None or not doc.research_verdict:
            updated.append(report)
            continue

        verdict = doc.research_verdict
        adjusted = compute_adjusted_signal(report.signal, verdict)
        conviction = adjust_conviction_for_research(report.conviction_score, verdict)
        research_note = format_research_action_note(
            verdict=verdict,
            risk_level=doc.research_risk_level,
            rationale=doc.research_rationale,
            adjusted_signal=adjusted,
            signal=report.signal,
        )
        action_note = report.action_note
        if research_note:
            action_note = f"{action_note} | {research_note}" if action_note else research_note

        summary = report.summary
        if research_note and research_note not in summary:
            summary = f"{summary} Research overlay: {research_note}."

        updated.append(
            replace(
                report,
                adjusted_signal=adjusted,
                research_verdict=verdict,
                research_risk_level=doc.research_risk_level,
                research_confidence=doc.research_confidence,
                research_rationale=doc.research_rationale,
                conviction_score=conviction,
                action_note=action_note,
                summary=summary,
            )
        )
    return updated


def enrich_signals_with_research(signals: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    """Add research overlay columns from stored memos without changing the base signal."""
    out = signals.copy()
    store = ResearchStore(output_dir)
    documents = store.list_documents()
    by_ticker = _documents_by_ticker(documents)

    verdicts: list[str | None] = []
    risk_levels: list[str | None] = []
    confidences: list[float | None] = []
    rationales: list[str | None] = []
    adjusted_signals: list[str] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        signal = str(row.get("signal") or "hold")
        doc = by_ticker.get(ticker)
        if doc is None or not doc.research_verdict:
            verdicts.append(None)
            risk_levels.append(None)
            confidences.append(None)
            rationales.append(None)
            adjusted_signals.append(signal)
            continue

        verdicts.append(doc.research_verdict)
        risk_levels.append(doc.research_risk_level)
        confidences.append(doc.research_confidence)
        rationales.append(doc.research_rationale)
        adjusted_signals.append(compute_adjusted_signal(signal, doc.research_verdict))

    out["research_verdict"] = verdicts
    out["research_risk_level"] = risk_levels
    out["research_confidence"] = confidences
    out["research_rationale"] = rationales
    out["adjusted_signal"] = adjusted_signals
    return out
