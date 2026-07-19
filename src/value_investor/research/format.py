"""Format research documents for email reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from value_investor.research.document import ResearchDocument, ResearchSummary
from value_investor.summary import CompanyReport

if TYPE_CHECKING:
    from value_investor.research.gap_fill import GapFillSummary


VERDICT_LABELS = {
    "accumulate": "Accumulate",
    "neutral": "Neutral",
    "caution": "Caution",
    "pass": "Pass",
}


def _verdict_change_note(doc: ResearchDocument) -> str | None:
    if doc.mode not in {"weekly_update", "gap_fill"} or not doc.weekly_updates:
        return None
    latest = doc.weekly_updates[-1]
    prior_verdict = latest.get("prior_verdict")
    if prior_verdict and prior_verdict != doc.research_verdict:
        prior = VERDICT_LABELS.get(prior_verdict, prior_verdict)
        current = VERDICT_LABELS.get(doc.research_verdict or "", doc.research_verdict or "—")
        prefix = "Gap-fill verdict" if latest.get("kind") == "gap_fill" or doc.mode == "gap_fill" else "Verdict"
        return f"{prefix} revised: {prior} → {current}"
    return None


def _latest_weekly_summary(doc: ResearchDocument) -> str | None:
    if not doc.weekly_updates:
        return None
    summary = doc.weekly_updates[-1].get("summary", "").strip()
    return summary or None


def format_gap_fill_text(summary: GapFillSummary | None) -> str | None:
    if summary is None or (
        not summary.targets
        and not summary.errors
        and not summary.model_suggestions
    ):
        return None
    lines = ["Red-flag gap-fill loop:"]
    lines.append(
        f"  Targets {len(summary.targets)}, created {summary.created}, "
        f"updated {summary.updated}, errors {len(summary.errors)}"
    )
    for target in summary.targets:
        q0 = target.questions[0] if target.questions else "qualitative follow-up"
        lines.append(f"  • {target.name} ({target.ticker}) — {q0[:160]}{'…' if len(q0) > 160 else ''}")
    by_ticker = {doc.ticker: doc for doc in summary.documents}
    for target in summary.targets:
        doc = by_ticker.get(target.ticker)
        if doc is None or not doc.weekly_updates:
            continue
        latest = doc.weekly_updates[-1].get("summary", "").strip()
        if latest:
            snippet = latest.replace("\n", " ")
            lines.append(f"    Gap-fill: {snippet[:220]}{'…' if len(snippet) > 220 else ''}")
    unresolved = [
        row
        for row in summary.question_outcomes
        if str(row.get("status") or "").startswith("unresolved")
        or str(row.get("status") or "").startswith("partially")
    ]
    if unresolved:
        lines.append("  Open / partial questions:")
        for row in unresolved[:6]:
            nxt = row.get("next_sources") or "alternate source TBD"
            lines.append(
                f"    • {row.get('ticker')}: {str(row.get('question') or '')[:120]} "
                f"→ next: {str(nxt)[:100]}"
            )
    if summary.model_suggestions:
        lines.append("  Research-model suggestions:")
        for row in summary.model_suggestions[:8]:
            lines.append(
                f"    • [{row.get('priority', 'medium')}/{row.get('area', 'research')}] "
                f"{str(row.get('suggestion') or '')[:180]}"
            )
    if summary.parked_suggestions:
        lines.append(
            f"  Parked {len(summary.parked_suggestions)} high-priority suggestion(s) "
            "into deferred-ideas for review."
        )
    for error in summary.errors:
        lines.append(f"  ! {error}")
    return "\n".join(lines)


def format_gap_fill_html(summary: GapFillSummary | None) -> str:
    text = format_gap_fill_text(summary)
    if not text:
        return ""
    body = text.replace("\n", "<br>")
    return f"""
  <div style="background:#fff5f5;padding:16px;border-radius:8px;margin:16px 0;border-left:4px solid #c53030">
    <h3 style="margin-top:0">Red-flag research loop</h3>
    <p style="margin-bottom:0">{body}</p>
  </div>
"""


def research_documents_for_reports(
    reports: list[CompanyReport],
    documents: list[ResearchDocument],
) -> list[ResearchDocument]:
    by_ticker = {doc.ticker: doc for doc in documents}
    ordered: list[ResearchDocument] = []
    for report in reports:
        if report.signal not in ("strong_buy", "buy"):
            continue
        doc = by_ticker.get(report.ticker)
        if doc is not None:
            ordered.append(doc)
    return ordered


def format_research_text(summary: ResearchSummary | None, documents: list[ResearchDocument]) -> str | None:
    if not documents:
        return None
    lines = ["Research memos (strong buy + top buys):"]
    if summary is not None:
        lines.append(
            f"  Created {summary.created}, updated {summary.updated}, "
            f"unchanged {summary.skipped}"
        )
        for error in summary.errors:
            lines.append(f"  ! {error}")
    for doc in documents:
        verdict = VERDICT_LABELS.get(doc.research_verdict or "", doc.research_verdict or "—")
        change = _verdict_change_note(doc)
        lines.append(
            f"  • {doc.name} ({doc.ticker}) — v{doc.version}, updated {doc.updated_at[:10]}, verdict {verdict}"
        )
        if change:
            lines.append(f"    {change}")
        weekly = _latest_weekly_summary(doc)
        if weekly:
            snippet = weekly.replace("\n", " ")
            lines.append(f"    Weekly: {snippet[:180]}{'…' if len(snippet) > 180 else ''}")
        if doc.executive_summary:
            snippet = doc.executive_summary.replace("\n", " ")
            lines.append(f"    {snippet[:220]}{'…' if len(snippet) > 220 else ''}")
        if doc.research_path:
            lines.append(f"    Full memo: {doc.research_path}")
    return "\n".join(lines)


def format_research_html(documents: list[ResearchDocument], summary: ResearchSummary | None = None) -> str:
    if not documents:
        return ""
    meta = ""
    if summary is not None:
        meta = (
            f"<p style='color:#666;font-size:13px;margin-top:0'>"
            f"Created {summary.created}, updated {summary.updated}, unchanged {summary.skipped}"
            f"</p>"
        )
    rows = []
    for doc in documents:
        snippet = doc.executive_summary.replace("\n", "<br>") if doc.executive_summary else "No summary yet."
        verdict = VERDICT_LABELS.get(doc.research_verdict or "", doc.research_verdict or "—")
        change = _verdict_change_note(doc)
        weekly = _latest_weekly_summary(doc)
        weekly_html = (
            f"<br><span style='color:#666;font-size:12px'><strong>Weekly:</strong> {weekly}</span>"
            if weekly
            else ""
        )
        change_html = (
            f"<br><span style='color:#b33a3a;font-size:12px;font-weight:bold'>{change}</span>"
            if change
            else ""
        )
        path_html = (
            f"<br><span style='color:#666;font-size:12px'>Memo: {doc.research_path}</span>"
            if doc.research_path
            else ""
        )
        rows.append(
            f"""
            <tr>
              <td style="padding:10px;border-bottom:1px solid #eee;vertical-align:top">
                <strong>{doc.name}</strong><br>
                <span style="color:#666">{doc.ticker}</span>
              </td>
              <td style="padding:10px;border-bottom:1px solid #eee;vertical-align:top">
                v{doc.version} · {doc.updated_at[:10]}<br>
                <span style="font-weight:bold">{verdict}</span>{change_html}
              </td>
              <td style="padding:10px;border-bottom:1px solid #eee">{snippet}{weekly_html}{path_html}</td>
            </tr>
            """
        )
    return f"""
  <div style="background:#faf5ff;padding:16px;border-radius:8px;margin:16px 0;border-left:4px solid #6b46c1">
    <h3 style="margin-top:0">Research memos</h3>
  {meta}
    <table style="width:100%;border-collapse:collapse;margin-top:8px">
      <thead>
        <tr style="background:#efe7fb">
          <th style="padding:10px;text-align:left">Company</th>
          <th style="padding:10px;text-align:left">Version / verdict</th>
          <th style="padding:10px;text-align:left">Executive summary</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </div>
"""
