"""Rules for escalating a name from Composer research to director–worker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from value_investor.research.document import ResearchDocument, unresolved_questions
from value_investor.summary import CompanyReport

SCREEN_BUY_SIGNALS = frozenset({"strong_buy", "buy"})
CAUTION_VERDICTS = frozenset({"caution", "pass", "neutral"})


@dataclass(frozen=True)
class EscalationDecision:
    should_escalate: bool
    reasons: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_escalate": self.should_escalate,
            "reasons": list(self.reasons),
            "triggers": list(self.triggers),
        }


def _screen_memo_mismatch(report: CompanyReport, doc: ResearchDocument) -> str | None:
    screen_buy = report.signal in SCREEN_BUY_SIGNALS
    verdict = str(doc.research_verdict or "").lower()
    if not screen_buy or not verdict:
        return None
    if verdict in CAUTION_VERDICTS:
        return (
            f"Screen is {report.signal} but memo verdict is {verdict} "
            f"(confidence {doc.research_confidence})"
        )
    if report.signal == "strong_buy" and verdict == "accumulate":
        confidence = doc.research_confidence
        if confidence is not None and confidence < 0.55:
            return (
                f"Strong-buy screen with weak accumulate confidence "
                f"({confidence:.2f}) — director adjudication warranted"
            )
    return None


def evaluate_director_escalation(
    *,
    report: CompanyReport,
    existing_doc: ResearchDocument | None,
    inventory: dict[str, Any] | None = None,
    source_quality: dict[str, Any] | None = None,
    require_composer_memo: bool = True,
) -> EscalationDecision:
    """
    Decide whether a ticker should run director–worker adjudication.

    Composer initial memo should exist first unless ``require_composer_memo`` is False.
    """
    reasons: list[str] = []
    triggers: list[str] = []
    inventory = inventory or {}
    source_quality = source_quality or {}

    if require_composer_memo and (
        existing_doc is None or existing_doc.mode not in {"initial", "weekly_update", "gap_fill"}
    ):
        return EscalationDecision(
            should_escalate=False,
            reasons=["No Composer initial memo in store — run ftse-research first"],
            triggers=[],
        )

    grade = str(source_quality.get("grade") or "").lower()
    if grade in {"thin", "poor"}:
        triggers.append("thin_sources")
        reasons.append(f"Source quality grade is {grade}")

    thin = list(inventory.get("thin") or source_quality.get("thin_gaps") or [])
    if len(thin) >= 3 and "thin_sources" not in triggers:
        triggers.append("thin_ladder")
        reasons.append(f"Evidence ladder thin on {len(thin)} steps: {', '.join(thin[:4])}")

    if report.interim_quality_overlay:
        triggers.append("interim_quality_overlay")
        reasons.append("Interim-quality overlay flag is set on the screen row")

    if existing_doc is not None:
        mismatch = _screen_memo_mismatch(report, existing_doc)
        if mismatch:
            triggers.append("screen_memo_mismatch")
            reasons.append(mismatch)

        open_questions = unresolved_questions(existing_doc.question_outcomes)
        if open_questions:
            triggers.append("unresolved_gap_fill")
            reasons.append(f"{len(open_questions)} unresolved gap-fill question(s)")

    should_escalate = bool(triggers)
    if not should_escalate:
        reasons = ["No escalation triggers fired — Composer memo is adequate for auto-routing"]

    return EscalationDecision(
        should_escalate=should_escalate,
        reasons=reasons,
        triggers=triggers,
    )


__all__ = [
    "EscalationDecision",
    "evaluate_director_escalation",
]
