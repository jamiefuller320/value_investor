"""Research document schema and parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


RESEARCH_SECTIONS = (
    "executive_summary",
    "investment_thesis",
    "financial_review",
    "risks_and_flags",
    "news_highlights",
)

SECTION_HEADINGS = {
    "executive_summary": "EXECUTIVE SUMMARY",
    "investment_thesis": "INVESTMENT THESIS",
    "financial_review": "FINANCIAL REVIEW",
    "risks_and_flags": "RISKS AND RED FLAGS",
    "news_highlights": "NEWS HIGHLIGHTS",
    "weekly_update": "WEEKLY UPDATE",
}


@dataclass
class ResearchDocument:
    ticker: str
    name: str
    signal: str
    version: int
    created_at: str
    updated_at: str
    mode: str
    executive_summary: str = ""
    investment_thesis: str = ""
    financial_review: str = ""
    risks_and_flags: str = ""
    news_highlights: str = ""
    weekly_updates: list[dict[str, str]] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    agent_id: str | None = None
    research_path: str | None = None

    @property
    def full_text(self) -> str:
        parts = [
            self.executive_summary,
            self.investment_thesis,
            self.financial_review,
            self.risks_and_flags,
            self.news_highlights,
        ]
        body = "\n\n".join(p.strip() for p in parts if p.strip())
        if self.weekly_updates:
            update_bits = [
                f"### {item['date']}\n{item['summary']}"
                for item in self.weekly_updates
                if item.get("summary")
            ]
            if update_bits:
                body = f"{body}\n\n## Weekly updates\n\n" + "\n\n".join(update_bits)
        return body.strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "signal": self.signal,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "mode": self.mode,
            "executive_summary": self.executive_summary,
            "investment_thesis": self.investment_thesis,
            "financial_review": self.financial_review,
            "risks_and_flags": self.risks_and_flags,
            "news_highlights": self.news_highlights,
            "weekly_updates": self.weekly_updates,
            "source_counts": self.source_counts,
            "agent_id": self.agent_id,
            "research_path": self.research_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchDocument:
        return cls(
            ticker=str(data["ticker"]),
            name=str(data.get("name") or data["ticker"]),
            signal=str(data.get("signal") or "strong_buy"),
            version=int(data.get("version") or 1),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            mode=str(data.get("mode") or "initial"),
            executive_summary=str(data.get("executive_summary") or ""),
            investment_thesis=str(data.get("investment_thesis") or ""),
            financial_review=str(data.get("financial_review") or ""),
            risks_and_flags=str(data.get("risks_and_flags") or ""),
            news_highlights=str(data.get("news_highlights") or ""),
            weekly_updates=list(data.get("weekly_updates") or []),
            source_counts=dict(data.get("source_counts") or {}),
            agent_id=data.get("agent_id"),
            research_path=data.get("research_path"),
        )


@dataclass
class ResearchSummary:
    documents: list[ResearchDocument]
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def has_documents(self) -> bool:
        return bool(self.documents)


def parse_research_sections(text: str) -> dict[str, str]:
    """Parse agent output into named research sections."""
    sections = {key: "" for key in (*RESEARCH_SECTIONS, "weekly_update")}
    heading_to_key = {v.upper(): k for k, v in SECTION_HEADINGS.items()}

    current = "executive_summary"
    lines: list[str] = []

    for line in text.splitlines():
        upper = line.strip().upper()
        if upper in heading_to_key:
            if lines:
                sections[current] = "\n".join(lines).strip()
                lines = []
            current = heading_to_key[upper]
            continue
        lines.append(line)

    sections[current] = "\n".join(lines).strip()
    return sections


def render_research_markdown(doc: ResearchDocument) -> str:
    """Render a full research memo as markdown."""
    lines = [
        f"# {doc.name} ({doc.ticker}) — Research memo",
        "",
        f"_Version {doc.version} · Updated {doc.updated_at} · Mode: {doc.mode}_",
        "",
        f"## {SECTION_HEADINGS['executive_summary']}",
        doc.executive_summary,
        "",
        f"## {SECTION_HEADINGS['investment_thesis']}",
        doc.investment_thesis,
        "",
        f"## {SECTION_HEADINGS['financial_review']}",
        doc.financial_review,
        "",
        f"## {SECTION_HEADINGS['risks_and_flags']}",
        doc.risks_and_flags,
        "",
        f"## {SECTION_HEADINGS['news_highlights']}",
        doc.news_highlights,
    ]
    if doc.weekly_updates:
        lines.extend(["", "## Weekly updates"])
        for item in doc.weekly_updates:
            lines.extend(["", f"### {item.get('date', 'Update')}", item.get("summary", "")])
    return "\n".join(lines).strip() + "\n"
