"""Apply research conviction overlay to screening outputs."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pandas as pd

from value_investor.research.document import ResearchDocument
from value_investor.research.store import ResearchStore
from value_investor.research.timeline import get_research_as_of
from value_investor.research.verdict import (
    adjust_conviction_for_research,
    compute_adjusted_signal,
    format_research_action_note,
)
from value_investor.summary import CompanyReport


def _documents_by_ticker(documents: list[ResearchDocument]) -> dict[str, ResearchDocument]:
    return {doc.ticker: doc for doc in documents}


def _resolve_run_at(row: pd.Series, default: datetime | str | None) -> datetime | str | None:
    if default is not None:
        return default
    value = row.get("run_at")
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


def _load_research_document(
    *,
    store: ResearchStore,
    ticker: str,
    as_of: datetime | str | None,
    latest_by_ticker: dict[str, ResearchDocument],
) -> ResearchDocument | None:
    if as_of is not None:
        doc = get_research_as_of(store.output_dir, ticker, as_of)
        if doc is not None:
            return doc
    return latest_by_ticker.get(ticker)


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


def enrich_signals_with_research(
    signals: pd.DataFrame,
    output_dir: Path,
    *,
    run_at: datetime | str | None = None,
) -> pd.DataFrame:
    """
    Add research overlay columns from stored memos without changing the base signal.

    When ``run_at`` is provided (or present on each row), uses the revision archive
    to apply only research knowledge available at that moment.
    """
    out = signals.copy()
    store = ResearchStore(output_dir)
    latest_by_ticker = _documents_by_ticker(store.list_documents())

    verdicts: list[str | None] = []
    risk_levels: list[str | None] = []
    confidences: list[float | None] = []
    rationales: list[str | None] = []
    adjusted_signals: list[str] = []
    research_as_ofs: list[str | None] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        signal = str(row.get("signal") or "hold")
        as_of = _resolve_run_at(row, run_at)
        doc = _load_research_document(
            store=store,
            ticker=ticker,
            as_of=as_of,
            latest_by_ticker=latest_by_ticker,
        )
        if doc is None or not doc.research_verdict:
            verdicts.append(None)
            risk_levels.append(None)
            confidences.append(None)
            rationales.append(None)
            adjusted_signals.append(signal)
            research_as_ofs.append(None)
            continue

        verdicts.append(doc.research_verdict)
        risk_levels.append(doc.research_risk_level)
        confidences.append(doc.research_confidence)
        rationales.append(doc.research_rationale)
        adjusted_signals.append(compute_adjusted_signal(signal, doc.research_verdict))
        research_as_ofs.append(doc.updated_at)

    out["research_verdict"] = verdicts
    out["research_risk_level"] = risk_levels
    out["research_confidence"] = confidences
    out["research_rationale"] = rationales
    out["adjusted_signal"] = adjusted_signals
    out["research_as_of"] = research_as_ofs
    return out
