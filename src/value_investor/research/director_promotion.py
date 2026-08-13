"""Promote director–worker adjudication metadata onto live research memos."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from value_investor.research.document import ResearchDocument
from value_investor.research.store import ResearchStore


def promote_director_baseline_to_store(
    *,
    store: ResearchStore,
    director_doc: ResearchDocument,
    run_id: str,
    trial_output_dir: str,
    run_at: datetime | None = None,
) -> ResearchDocument:
    """
    Merge director baseline onto the live Composer memo without replacing memo body.

    The frozen baseline enables shadow re-escalation checks on subsequent Composer runs.
    Director verdict/confidence are stored on the baseline package for comparison.
    """
    live = store.load(director_doc.ticker)
    if live is None:
        raise ValueError(
            f"No live research memo for {director_doc.ticker!r} — "
            "run ftse-research before promoting a director baseline"
        )

    baseline = dict(director_doc.director_baseline or {})
    if not baseline:
        raise ValueError(f"Director document for {director_doc.ticker!r} has no director_baseline")

    baseline = {
        **baseline,
        "promoted_at": datetime.now(UTC).isoformat(),
        "trial_run_id": run_id,
        "trial_output_dir": trial_output_dir,
        "director_mode": director_doc.mode,
    }

    updated = replace(
        live,
        director_baseline=baseline,
        updated_at=datetime.now(UTC).isoformat(),
    )
    store.save(updated, run_at=run_at or datetime.now(UTC))
    return updated


def promotion_record(
    *,
    ticker: str,
    run_id: str,
    trial_output_dir: str,
    live_path: str,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "run_id": run_id,
        "trial_output_dir": trial_output_dir,
        "live_research_path": live_path,
        "promoted_at": datetime.now(UTC).isoformat(),
    }


__all__ = [
    "promote_director_baseline_to_store",
    "promotion_record",
]
