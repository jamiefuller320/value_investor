"""Material-change detection for Composer monitor vs frozen director baseline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from value_investor.summary import CompanyReport

SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


@dataclass(frozen=True)
class MaterialChangeDecision:
    material_change: bool
    reasons: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_change": self.material_change,
            "reasons": list(self.reasons),
            "triggers": list(self.triggers),
        }


def figure_fingerprint(worker_results: list[dict[str, Any]]) -> str:
    """Stable hash of worker figure tables for baseline comparison."""
    rows: list[tuple[str, str, str]] = []
    for result in worker_results:
        for figure in result.get("figures") or []:
            if not isinstance(figure, dict):
                continue
            rows.append(
                (
                    str(figure.get("metric") or ""),
                    str(figure.get("value") or ""),
                    str(figure.get("period") or ""),
                )
            )
    rows.sort()
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def source_fingerprint(
    *,
    inventory: dict[str, Any] | None,
    source_counts: dict[str, int] | None,
) -> dict[str, Any]:
    counts = dict(source_counts or {})
    inv = inventory or {}
    return {
        "thin": sorted(str(step) for step in (inv.get("thin") or [])),
        "filings_total": int(counts.get("filings_total") or 0),
        "filings_with_body": int(counts.get("filings_with_body") or 0),
        "filings_annual": int(counts.get("filings_annual") or 0),
        "filings_interim": int(counts.get("filings_interim") or 0),
        "news_articles": int(counts.get("news_articles") or 0),
        "financial_years": int(counts.get("financial_years") or 0),
    }


def build_director_baseline(
    *,
    report: CompanyReport,
    task_plan: dict[str, Any],
    worker_results: list[dict[str, Any]],
    inventory: dict[str, Any],
    source_counts: dict[str, int],
    run_id: str,
    output_dir: str,
    research_verdict: str | None,
    research_confidence: float | None,
) -> dict[str, Any]:
    """Freeze director adjudication package for Composer monitoring."""
    from datetime import UTC, datetime

    return {
        "schema_version": 1,
        "run_id": run_id,
        "output_dir": output_dir,
        "created_at": datetime.now(UTC).isoformat(),
        "screen_signal": report.signal,
        "open_questions": list(task_plan.get("open_questions") or []),
        "meta_reflection": list(task_plan.get("meta_reflection") or []),
        "research_verdict": research_verdict,
        "research_confidence": research_confidence,
        "figure_fingerprint": figure_fingerprint(worker_results),
        "source_fingerprint": source_fingerprint(
            inventory=inventory,
            source_counts=source_counts,
        ),
        "worker_count": len(worker_results),
    }


def evaluate_material_change(
    *,
    baseline: dict[str, Any] | None,
    report: CompanyReport,
    inventory: dict[str, Any] | None,
    source_counts: dict[str, int] | None,
) -> MaterialChangeDecision:
    """Rule-based check for whether Composer monitor should re-escalate to director."""
    if not baseline:
        return MaterialChangeDecision(
            material_change=True,
            reasons=["No director baseline recorded"],
            triggers=["missing_baseline"],
        )

    reasons: list[str] = []
    triggers: list[str] = []
    current = source_fingerprint(inventory=inventory, source_counts=source_counts)
    prior = dict(baseline.get("source_fingerprint") or {})

    prior_signal = str(baseline.get("screen_signal") or "")
    if prior_signal and report.signal != prior_signal:
        old_rank = SIGNAL_RANK.get(prior_signal, -1)
        new_rank = SIGNAL_RANK.get(report.signal, -1)
        if old_rank != new_rank:
            triggers.append("screen_signal_change")
            reasons.append(f"Screen signal changed {prior_signal} → {report.signal}")

    for key in ("filings_annual", "filings_interim"):
        if int(current.get(key) or 0) > int(prior.get(key) or 0):
            triggers.append(f"new_{key}")
            reasons.append(f"{key} count increased {prior.get(key)} → {current.get(key)}")

    if int(current.get("filings_with_body") or 0) > int(prior.get("filings_with_body") or 0):
        if "new_filing_bodies" not in triggers:
            triggers.append("new_filing_bodies")
            reasons.append(
                "Filing bodies increased "
                f"{prior.get('filings_with_body')} → {current.get('filings_with_body')}"
            )

    if inventory is not None:
        prior_thin = set(prior.get("thin") or [])
        current_thin = set(current.get("thin") or [])
        if current_thin < prior_thin:
            triggers.append("ladder_improved")
            reasons.append(f"Thin ladder steps reduced: {sorted(prior_thin - current_thin)}")

    return MaterialChangeDecision(
        material_change=bool(triggers),
        reasons=reasons or ["No material source or signal change since director baseline"],
        triggers=triggers,
    )


__all__ = [
    "MaterialChangeDecision",
    "build_director_baseline",
    "evaluate_material_change",
    "figure_fingerprint",
    "source_fingerprint",
]
