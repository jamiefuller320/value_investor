"""Cursor agent prompts for deep research and weekly updates."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.research.document import ResearchDocument, parse_research_sections
from value_investor.research.verdict import parse_research_verdict
from value_investor.summary import CompanyReport


def _initial_prompt(
    *,
    ticker: str,
    company_name: str,
    sources_dir: Path,
) -> str:
    return f"""You are a UK equity research analyst writing a deep first-pass memo on {company_name} ({ticker}).

Read the source files in: {sources_dir.resolve()}

- `financials_annual.json` — up to five years of income statement, balance sheet, and cash flow
- `screening_snapshot.json` — quantitative value screen output (models passed, metrics, timing)
- `news_manifest.json` — up to one year of news headlines from yfinance and Google News RSS

Write a research memo with EXACTLY these plain-text section headings:

EXECUTIVE SUMMARY
3–5 sentences: investment case, valuation hook, and key debate.

INVESTMENT THESIS
Why this is a strong buy for a value investor. Tie quantitative screen results to business quality.

FINANCIAL REVIEW
Analyse the five-year financial trend: revenue, margins, leverage, cash generation, and balance-sheet strength.
Cite figures from `financials_annual.json` only — do not invent numbers.

RISKS AND RED FLAGS
Regulatory, cyclical, governance, pension, or competitive risks not fully captured by screens.

NEWS HIGHLIGHTS
Summarise material news from the past year: strategy shifts, management changes, regulatory actions, M&A.
Cite article titles/dates from the manifest. Flag if news coverage is thin.

RESEARCH VERDICT
Structured conviction overlay for the quantitative screen (does not replace the screen signal).
Use EXACTLY these lines:
Verdict: accumulate | neutral | caution | pass
Risk: low | medium | high
Confidence: 0.00–1.00 (decimal, e.g. 0.75)
Rationale: One sentence on whether deep research confirms, is neutral on, or weakens the strong buy case.

Rules:
- UK English, concise professional tone.
- Do not give buy/sell price targets.
- If a source is missing data, say so explicitly.
"""


def _weekly_update_prompt(
    *,
    ticker: str,
    company_name: str,
    sources_dir: Path,
    news_batch_path: Path,
    existing_markdown_path: Path,
) -> str:
    return f"""You are updating an existing research memo on {company_name} ({ticker}).

Existing memo: {existing_markdown_path.resolve()}
New news batch since last update: {news_batch_path.resolve()}
Full news archive: {(sources_dir / 'news_manifest.json').resolve()}
Updated financials (if refreshed): {(sources_dir / 'financials_annual.json').resolve()}

Write ONE section with the heading exactly as shown:

WEEKLY UPDATE
Summarise any new information from the news batch and whether it changes the thesis, risks, or timing.
If nothing material changed, say so in 2–3 sentences.
Reference article titles and dates where relevant.
Do not repeat the full prior memo.

Then add a RESEARCH VERDICT section (revise conviction only if material news changes the investment case; otherwise repeat the prior verdict unchanged):

RESEARCH VERDICT
Use EXACTLY these lines:
Verdict: accumulate | neutral | caution | pass
Risk: low | medium | high
Confidence: 0.00–1.00 (decimal, e.g. 0.75)
Rationale: One sentence on whether this week's news confirms, is neutral on, or weakens the strong buy case.
"""


def _run_agent_prompt(
    *,
    prompt: str,
    api_key: str,
    model: str,
    cwd: str | None,
    agent_id: str | None = None,
) -> tuple[str, str | None]:
    options = AgentOptions(
        api_key=api_key,
        model=model,
        local=LocalAgentOptions(cwd=cwd or os.getcwd()),
    )
    agent: Agent
    if agent_id:
        try:
            agent = Agent.resume(agent_id, options)
        except CursorAgentError:
            agent = Agent.create(options)
    else:
        agent = Agent.create(options)

    try:
        result = agent.send(prompt).wait()
    except CursorAgentError as err:
        raise RuntimeError(f"Agent run failed: {err.message}") from err
    finally:
        try:
            agent.close()
        except CursorAgentError:
            pass

    if result.result is None:
        raise RuntimeError("Agent returned empty research output")

    return result.result.strip(), agent.agent_id


def run_initial_research_agent(
    *,
    report: CompanyReport,
    sources_dir: Path,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
) -> tuple[ResearchDocument, str | None]:
    prompt = _initial_prompt(
        ticker=report.ticker,
        company_name=report.name,
        sources_dir=sources_dir,
    )
    text, agent_id = _run_agent_prompt(
        prompt=prompt,
        api_key=api_key,
        model=model,
        cwd=cwd,
    )
    sections = parse_research_sections(text)
    verdict_fields = parse_research_verdict(sections.get("research_verdict", ""))
    now = datetime.now(UTC).isoformat()
    doc = ResearchDocument(
        ticker=report.ticker,
        name=report.name,
        signal=report.signal,
        version=1,
        created_at=now,
        updated_at=now,
        mode="initial",
        executive_summary=sections["executive_summary"],
        investment_thesis=sections["investment_thesis"],
        financial_review=sections["financial_review"],
        risks_and_flags=sections["risks_and_flags"],
        news_highlights=sections["news_highlights"],
        research_verdict=verdict_fields["research_verdict"],  # type: ignore[arg-type]
        research_risk_level=verdict_fields["research_risk_level"],  # type: ignore[arg-type]
        research_confidence=verdict_fields["research_confidence"],  # type: ignore[arg-type]
        research_rationale=verdict_fields["research_rationale"],  # type: ignore[arg-type]
        agent_id=agent_id,
    )
    return doc, agent_id


def run_weekly_research_update_agent(
    *,
    existing: ResearchDocument,
    sources_dir: Path,
    news_batch_path: Path,
    markdown_path: Path,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
) -> ResearchDocument:
    prompt = _weekly_update_prompt(
        ticker=existing.ticker,
        company_name=existing.name,
        sources_dir=sources_dir,
        news_batch_path=news_batch_path,
        existing_markdown_path=markdown_path,
    )
    text, agent_id = _run_agent_prompt(
        prompt=prompt,
        api_key=api_key,
        model=model,
        cwd=cwd,
        agent_id=existing.agent_id,
    )
    sections = parse_research_sections(text)
    update_summary = sections.get("weekly_update", "").strip()
    verdict_fields = parse_research_verdict(sections.get("research_verdict", ""))
    now = datetime.now(UTC)
    new_verdict = verdict_fields.get("research_verdict") or existing.research_verdict
    new_risk = verdict_fields.get("research_risk_level") or existing.research_risk_level
    new_confidence = (
        verdict_fields.get("research_confidence")
        if verdict_fields.get("research_confidence") is not None
        else existing.research_confidence
    )
    new_rationale = verdict_fields.get("research_rationale") or existing.research_rationale
    weekly_entry: dict[str, str] = {
        "date": now.strftime("%Y-%m-%d"),
        "as_of": now.isoformat(),
        "summary": update_summary,
    }
    if existing.research_verdict != new_verdict:
        weekly_entry["prior_verdict"] = existing.research_verdict or ""
        weekly_entry["new_verdict"] = new_verdict or ""
    updated = ResearchDocument(
        ticker=existing.ticker,
        name=existing.name,
        signal=existing.signal,
        version=existing.version + 1,
        created_at=existing.created_at,
        updated_at=now.isoformat(),
        mode="weekly_update",
        executive_summary=existing.executive_summary,
        investment_thesis=existing.investment_thesis,
        financial_review=existing.financial_review,
        risks_and_flags=existing.risks_and_flags,
        news_highlights=existing.news_highlights,
        research_verdict=new_verdict,
        research_risk_level=new_risk,
        research_confidence=new_confidence,
        research_rationale=new_rationale,
        weekly_updates=[
            *existing.weekly_updates,
            weekly_entry,
        ],
        source_counts=existing.source_counts,
        agent_id=agent_id or existing.agent_id,
    )
    return updated
