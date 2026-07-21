"""Verify-before-trade decision packs (stage 2 / L27).

Assembles a fixed five-step pack — signal → thesis → levels → size → risks —
plus an explicit verify checklist. Missing research or levels become gaps;
never invent confidence or price targets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from value_investor.research.document import ResearchDocument
from value_investor.summary import CompanyReport
from value_investor.technical_analysis import TradePlan

THESIS_GAP = "No research memo yet — thesis unverified. Do not treat the screen signal as confirmed."
LEVELS_GAP = "No structured trade-plan levels — set limits/stops manually before acting."
SIZE_GAP = "No allocation guidance — size manually (paper-auto uses equal-weight sleeves when automated)."
RISKS_GAP = "No research risk section — review filings and news yourself before sizing."

VERIFY_BASE = [
    "Confirm live broker price vs the plan levels (Yahoo/screen marks can lag).",
    "Re-read open filing or data gaps before committing size.",
    "If unavailable on Interactive Investor, park on the watchlist — do not force a substitute.",
]


@dataclass
class DecisionPack:
    ticker: str
    name: str
    signal: str
    thesis: str
    levels: str
    size: str
    risks: str
    verify: list[str] = field(default_factory=list)
    timing_signal: str | None = None
    adjusted_signal: str | None = None
    conviction_score: float | None = None
    research_verdict: str | None = None
    research_confidence: float | None = None
    research_risk_level: str | None = None
    action_note: str | None = None
    gaps: list[str] = field(default_factory=list)
    high_conviction: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.conviction_score is not None:
            payload["conviction_score"] = round(float(self.conviction_score), 4)
        if self.research_confidence is not None:
            payload["research_confidence"] = round(float(self.research_confidence), 4)
        return payload


def _as_report_dict(report: CompanyReport | dict[str, Any]) -> dict[str, Any]:
    if isinstance(report, CompanyReport):
        return report.to_dict()
    return dict(report)


def _clip(text: str, *, max_chars: int = 480) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _trade_plan_from_report(data: dict[str, Any]) -> TradePlan | None:
    raw = data.get("trade_plan")
    if isinstance(raw, TradePlan):
        return raw
    if not isinstance(raw, dict):
        return None
    if not raw.get("trade_plan_summary") and raw.get("core_order") is None:
        return None
    return TradePlan(
        core_order=raw.get("core_order"),
        core_limit=raw.get("core_limit"),
        core_allocation_pct=raw.get("core_allocation_pct"),
        tactical_order=raw.get("tactical_order"),
        tactical_limit=raw.get("tactical_limit"),
        tactical_allocation_pct=raw.get("tactical_allocation_pct"),
        tactical_stop_loss=raw.get("tactical_stop_loss"),
        tactical_take_profit=raw.get("tactical_take_profit"),
        trade_plan_summary=raw.get("trade_plan_summary"),
    )


def _format_levels(plan: TradePlan | None) -> tuple[str, bool]:
    if plan is None:
        return LEVELS_GAP, True
    if plan.trade_plan_summary:
        return str(plan.trade_plan_summary), False
    parts: list[str] = []
    if plan.core_order:
        core = f"core {plan.core_order}"
        if plan.core_limit is not None:
            core += f" @ £{float(plan.core_limit):.2f}"
        if plan.core_allocation_pct is not None:
            core += f" ({float(plan.core_allocation_pct):.0%})"
        parts.append(core)
    if plan.tactical_limit is not None:
        tac = f"tactical limit £{float(plan.tactical_limit):.2f}"
        if plan.tactical_allocation_pct is not None:
            tac += f" ({float(plan.tactical_allocation_pct):.0%})"
        parts.append(tac)
    if plan.tactical_stop_loss is not None and plan.tactical_take_profit is not None:
        parts.append(
            f"stop £{float(plan.tactical_stop_loss):.2f}, "
            f"target £{float(plan.tactical_take_profit):.2f}"
        )
    if not parts:
        return LEVELS_GAP, True
    return "Trade plan: " + "; ".join(parts) + ".", False


def _format_size(plan: TradePlan | None, *, timing: str | None) -> tuple[str, bool]:
    if plan is None or (
        plan.core_allocation_pct is None and plan.tactical_allocation_pct is None
    ):
        return SIZE_GAP, True
    bits: list[str] = []
    if plan.core_allocation_pct is not None:
        bits.append(f"core sleeve ≈ {float(plan.core_allocation_pct):.0%} of planned stake")
    if plan.tactical_allocation_pct is not None:
        bits.append(
            f"tactical add ≈ {float(plan.tactical_allocation_pct):.0%} on the dip limit"
        )
    if timing == "wait":
        bits.append("timing is wait — prefer smaller starter size or delay entry")
    bits.append("Keep total book exposure inside your sector/position caps.")
    return "; ".join(bits) + ".", False


def _thesis_from_sources(
    data: dict[str, Any],
    research: ResearchDocument | None,
) -> tuple[str, bool]:
    if research is not None:
        body = (research.investment_thesis or "").strip() or (
            research.executive_summary or ""
        ).strip()
        if body:
            return _clip(body), False
    rationale = str(data.get("research_rationale") or "").strip()
    if rationale:
        return _clip(rationale), False
    summary = str(data.get("summary") or "").strip()
    if summary:
        return _clip(f"Screen summary only (unverified): {summary}"), True
    return THESIS_GAP, True


def _risks_from_sources(
    data: dict[str, Any],
    research: ResearchDocument | None,
) -> tuple[str, bool]:
    gaps: list[str] = []
    bits: list[str] = []
    if research is not None and (research.risks_and_flags or "").strip():
        bits.append(_clip(research.risks_and_flags))
    risk_level = data.get("research_risk_level") or (
        research.research_risk_level if research else None
    )
    if risk_level:
        bits.append(f"Research risk level: {risk_level}.")
    dq = data.get("data_quality_score")
    try:
        if dq is not None and float(dq) < 0.6:
            bits.append(f"Data quality is weak ({float(dq):.0%}) — treat metrics cautiously.")
            gaps.append("low_data_quality")
    except (TypeError, ValueError):
        pass
    if not bits:
        return RISKS_GAP, True
    return " ".join(bits), False


def _verify_checklist(
    data: dict[str, Any],
    *,
    gaps: list[str],
    research_verdict: str | None,
    research_confidence: float | None,
) -> tuple[list[str], bool]:
    items = list(VERIFY_BASE)
    high_conviction = True

    if "thesis" in gaps or "risks" in gaps:
        items.append("Memo incomplete — do not size as high-conviction.")
        high_conviction = False
    if "levels" in gaps:
        items.append("Define your own limit/stop before sending an order.")
        high_conviction = False

    verdict = (research_verdict or "").lower()
    if verdict in {"caution", "pass"}:
        items.append(
            f"Research verdict is {verdict} — de-size or skip despite the screen signal."
        )
        high_conviction = False

    if research_confidence is not None and float(research_confidence) < 0.5:
        items.append(
            f"Research confidence is low ({float(research_confidence):.0%}) — "
            "prefer a starter size or wait for better evidence."
        )
        high_conviction = False

    if data.get("ii_tradable") is False:
        items.append("II overlay marks this name non-tradable — do not force a substitute venue.")
        high_conviction = False

    timing = str(data.get("timing_signal") or "")
    if timing == "wait":
        items.append("Timing signal is wait — verify you are not chasing an extended entry.")
        high_conviction = False

    if high_conviction:
        items.append("Evidence looks adequate for a routine manual check — still verify figures.")

    return items, high_conviction


def build_decision_pack(
    report: CompanyReport | dict[str, Any],
    research: ResearchDocument | None = None,
) -> DecisionPack:
    """Build a verify-before-trade pack from a screen report (+ optional memo)."""
    data = _as_report_dict(report)
    ticker = str(data.get("ticker") or "")
    name = str(data.get("name") or ticker)
    signal = str(data.get("signal") or "")
    timing = data.get("timing_signal")
    plan = _trade_plan_from_report(data)

    gaps: list[str] = []
    thesis, thesis_gap = _thesis_from_sources(data, research)
    if thesis_gap:
        gaps.append("thesis")
    levels, levels_gap = _format_levels(plan)
    if levels_gap:
        gaps.append("levels")
    size, size_gap = _format_size(plan, timing=str(timing) if timing else None)
    if size_gap:
        gaps.append("size")
    risks, risks_gap = _risks_from_sources(data, research)
    if risks_gap:
        gaps.append("risks")

    research_verdict = data.get("research_verdict") or (
        research.research_verdict if research else None
    )
    research_confidence = data.get("research_confidence")
    if research_confidence is None and research is not None:
        research_confidence = research.research_confidence
    research_risk = data.get("research_risk_level") or (
        research.research_risk_level if research else None
    )

    verify, high_conviction = _verify_checklist(
        data,
        gaps=gaps,
        research_verdict=str(research_verdict) if research_verdict else None,
        research_confidence=(
            float(research_confidence) if research_confidence is not None else None
        ),
    )

    return DecisionPack(
        ticker=ticker,
        name=name,
        signal=signal,
        thesis=thesis,
        levels=levels,
        size=size,
        risks=risks,
        verify=verify,
        timing_signal=str(timing) if timing else None,
        adjusted_signal=data.get("adjusted_signal"),
        conviction_score=(
            float(data["conviction_score"])
            if data.get("conviction_score") is not None
            else None
        ),
        research_verdict=str(research_verdict) if research_verdict else None,
        research_confidence=(
            float(research_confidence) if research_confidence is not None else None
        ),
        research_risk_level=str(research_risk) if research_risk else None,
        action_note=str(data.get("action_note") or "") or None,
        gaps=gaps,
        high_conviction=high_conviction,
    )


def build_decision_packs(
    reports: list[CompanyReport] | list[dict[str, Any]],
    research_documents: list[ResearchDocument] | None = None,
    *,
    signals: set[str] | None = None,
) -> list[DecisionPack]:
    """Build packs for buy-tier (default) reports, keyed by research ticker when present."""
    wanted = signals or {"strong_buy", "buy"}
    by_ticker = {
        doc.ticker: doc for doc in (research_documents or []) if getattr(doc, "ticker", None)
    }
    packs: list[DecisionPack] = []
    for report in reports:
        data = _as_report_dict(report)
        if str(data.get("signal") or "") not in wanted:
            continue
        ticker = str(data.get("ticker") or "")
        packs.append(build_decision_pack(report, by_ticker.get(ticker)))
    return packs


def attach_decision_packs(
    reports: list[dict[str, Any]],
    research_documents: list[ResearchDocument] | None = None,
) -> list[dict[str, Any]]:
    """Mutate/return report dicts with an embedded ``decision_pack`` for buy-tier names."""
    by_ticker = {
        doc.ticker: doc for doc in (research_documents or []) if getattr(doc, "ticker", None)
    }
    for report in reports:
        if str(report.get("signal") or "") not in {"strong_buy", "buy"}:
            continue
        pack = build_decision_pack(report, by_ticker.get(str(report.get("ticker") or "")))
        report["decision_pack"] = pack.to_dict()
    return reports


def format_decision_pack_text(pack: DecisionPack) -> str:
    signal = pack.signal.replace("_", " ")
    lines = [
        f"{pack.name} ({pack.ticker}) — {signal}",
        f"  Signal: {signal}"
        + (f" · timing {pack.timing_signal}" if pack.timing_signal else "")
        + (f" · conviction {pack.conviction_score:.0%}" if pack.conviction_score is not None else "")
        + (
            f" · research {pack.research_verdict}"
            if pack.research_verdict
            else ""
        ),
        f"  Thesis: {pack.thesis}",
        f"  Levels: {pack.levels}",
        f"  Size: {pack.size}",
        f"  Risks: {pack.risks}",
        "  Verify before trade:",
    ]
    for item in pack.verify:
        lines.append(f"    - {item}")
    return "\n".join(lines)


def format_decision_packs_text(packs: list[DecisionPack]) -> str | None:
    if not packs:
        return None
    blocks = [
        "Manual verify-before-trade packs (signal → thesis → levels → size → risks).",
        "Gaps are explicit — do not invent confidence when evidence is thin.",
        "",
    ]
    for pack in packs:
        blocks.append(format_decision_pack_text(pack))
        blocks.append("")
    return "\n".join(blocks).rstrip()


def format_decision_pack_html(pack: DecisionPack) -> str:
    verify_items = "".join(f"<li>{_escape(item)}</li>" for item in pack.verify)
    conf = (
        f"{pack.research_confidence:.0%}"
        if pack.research_confidence is not None
        else "—"
    )
    return f"""
    <div style="margin:12px 0;padding:10px 0;border-top:1px solid #ddd">
      <strong>{_escape(pack.name)}</strong>
      <span style="color:#666">({_escape(pack.ticker)})</span>
      <div style="font-size:13px;margin-top:6px;line-height:1.45">
        <div><strong>Signal:</strong> {_escape(pack.signal.replace('_', ' '))}
          · timing {_escape(pack.timing_signal or '—')}
          · research {_escape(pack.research_verdict or '—')} ({conf})</div>
        <div><strong>Thesis:</strong> {_escape(pack.thesis)}</div>
        <div><strong>Levels:</strong> {_escape(pack.levels)}</div>
        <div><strong>Size:</strong> {_escape(pack.size)}</div>
        <div><strong>Risks:</strong> {_escape(pack.risks)}</div>
        <div><strong>Verify before trade:</strong>
          <ul style="margin:4px 0 0 18px;padding:0">{verify_items}</ul>
        </div>
      </div>
    </div>
    """.strip()


def format_decision_packs_html(packs: list[DecisionPack]) -> str:
    if not packs:
        return ""
    body = "\n".join(format_decision_pack_html(pack) for pack in packs)
    return f"""
    <h2 style="margin-top:28px">Verify-before-trade packs</h2>
    <p style="color:#555;font-size:13px">
      Signal → thesis → levels → size → risks. Explicit gaps mean evidence is incomplete —
      do not upgrade confidence to fill them.
    </p>
    {body}
    """


def _escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
