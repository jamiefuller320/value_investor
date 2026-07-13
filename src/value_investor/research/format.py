"""Format research documents for email reports."""

from __future__ import annotations

from value_investor.research.document import ResearchDocument, ResearchSummary
from value_investor.summary import CompanyReport


VERDICT_LABELS = {
    "accumulate": "Accumulate",
    "neutral": "Neutral",
    "caution": "Caution",
    "pass": "Pass",
}


def _verdict_change_note(doc: ResearchDocument) -> str | None:
    if doc.mode != "weekly_update" or not doc.weekly_updates:
        return None
    latest = doc.weekly_updates[-1]
    prior_verdict = latest.get("prior_verdict")
    if prior_verdict and prior_verdict != doc.research_verdict:
        prior = VERDICT_LABELS.get(prior_verdict, prior_verdict)
        current = VERDICT_LABELS.get(doc.research_verdict or "", doc.research_verdict or "—")
        return f"Verdict revised: {prior} → {current}"
    return None


def _latest_weekly_summary(doc: ResearchDocument) -> str | None:
    if not doc.weekly_updates:
        return None
    summary = doc.weekly_updates[-1].get("summary", "").strip()
    return summary or None


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
