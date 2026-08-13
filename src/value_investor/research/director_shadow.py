"""Observe-only director escalation logging after Composer research runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.research.director_baseline import evaluate_material_change
from value_investor.research.director_escalation import evaluate_director_escalation
from value_investor.research.document import ResearchDocument
from value_investor.research.gap_fill_sources import inspect_local_sources
from value_investor.research.source_quality import score_research_sources
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

DEFAULT_DW_SHADOW_LOG = Path("docs/data/research_director_worker/shadow_log.json")
MAX_SHADOW_ENTRIES = 500

RECOMMEND_NONE = "none"
RECOMMEND_ESCALATE = "escalate_director"
RECOMMEND_RE_ESCALATE = "re_escalate_director"
RECOMMEND_MONITOR = "monitor_composer"


@dataclass(frozen=True)
class DirectorShadowDecision:
    ticker: str
    research_action: str
    recommended_action: str
    escalation: dict[str, Any]
    material_change: dict[str, Any] | None
    source_quality_grade: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "research_action": self.research_action,
            "recommended_action": self.recommended_action,
            "escalation": self.escalation,
            "material_change": self.material_change,
            "source_quality_grade": self.source_quality_grade,
        }


def _recommended_action(
    *,
    doc: ResearchDocument,
    escalation_should: bool,
    material_change: bool,
) -> str:
    if doc.director_baseline:
        if material_change:
            return RECOMMEND_RE_ESCALATE
        return RECOMMEND_MONITOR
    if escalation_should:
        return RECOMMEND_ESCALATE
    return RECOMMEND_NONE


def evaluate_director_shadow(
    *,
    report: CompanyReport,
    doc: ResearchDocument,
    sources_dir: Path | None = None,
    research_action: str,
) -> DirectorShadowDecision:
    """Evaluate escalation/material-change without calling director agents."""
    inventory = (
        inspect_local_sources(sources_dir)
        if sources_dir and sources_dir.exists()
        else None
    )
    source_quality = score_research_sources(
        source_counts=doc.source_counts,
        inventory=inventory,
        question_outcomes=doc.question_outcomes,
    )
    escalation = evaluate_director_escalation(
        report=report,
        existing_doc=doc,
        inventory=inventory,
        source_quality=source_quality,
    )
    material = None
    material_change = False
    if doc.director_baseline:
        material_decision = evaluate_material_change(
            baseline=doc.director_baseline,
            report=report,
            inventory=inventory,
            source_counts=doc.source_counts,
        )
        material = material_decision.to_dict()
        material_change = material_decision.material_change

    return DirectorShadowDecision(
        ticker=report.ticker,
        research_action=research_action,
        recommended_action=_recommended_action(
            doc=doc,
            escalation_should=escalation.should_escalate,
            material_change=material_change,
        ),
        escalation=escalation.to_dict(),
        material_change=material,
        source_quality_grade=str(source_quality.get("grade") or ""),
    )


def default_shadow_log() -> dict[str, Any]:
    return {"schema_version": 1, "entries": [], "updated_at": None}


def load_shadow_log(path: Path = DEFAULT_DW_SHADOW_LOG) -> dict[str, Any]:
    if not path.exists():
        return default_shadow_log()
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return default_shadow_log()
    base = default_shadow_log()
    base.update(payload)
    base.setdefault("entries", [])
    return base


def append_shadow_log_entry(
    entry: dict[str, Any],
    *,
    path: Path = DEFAULT_DW_SHADOW_LOG,
    max_entries: int = MAX_SHADOW_ENTRIES,
) -> dict[str, Any]:
    log = load_shadow_log(path)
    log.setdefault("entries", []).append(entry)
    log["entries"] = list(log["entries"])[-max_entries:]
    log["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, log, compact=False)
    return entry


def record_director_shadow_entry(
    *,
    report: CompanyReport,
    doc: ResearchDocument,
    sources_dir: Path | None,
    research_action: str,
    run_output_dir: str | None = None,
    shadow_log_path: Path = DEFAULT_DW_SHADOW_LOG,
) -> dict[str, Any]:
    """Evaluate shadow routing and append to the rolling observe-only log."""
    decision = evaluate_director_shadow(
        report=report,
        doc=doc,
        sources_dir=sources_dir,
        research_action=research_action,
    )
    entry = {
        **decision.to_dict(),
        "recorded_at": datetime.now(UTC).isoformat(),
        "mode": "shadow",
        "run_output_dir": run_output_dir,
        "has_director_baseline": bool(doc.director_baseline),
    }
    append_shadow_log_entry(entry, path=shadow_log_path)
    return entry


def write_shadow_run_summary(
    entries: list[dict[str, Any]],
    *,
    output_dir: Path,
) -> Path:
    """Write per-run shadow summary beside research outputs."""
    path = output_dir / "director_shadow.json"
    write_json(
        path,
        {
            "schema_version": 1,
            "recorded_at": datetime.now(UTC).isoformat(),
            "count": len(entries),
            "entries": entries,
        },
        compact=False,
    )
    return path


__all__ = [
    "DEFAULT_DW_SHADOW_LOG",
    "RECOMMEND_ESCALATE",
    "RECOMMEND_MONITOR",
    "RECOMMEND_NONE",
    "RECOMMEND_RE_ESCALATE",
    "DirectorShadowDecision",
    "append_shadow_log_entry",
    "evaluate_director_shadow",
    "record_director_shadow_entry",
    "write_shadow_run_summary",
]
