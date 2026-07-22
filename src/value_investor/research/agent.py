"""Cursor agent prompts for deep research and weekly updates."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.research.document import ResearchDocument, parse_research_sections
from value_investor.research.verdict import parse_research_verdict
from value_investor.summary import CompanyReport


def _screen_signal_label(signal: str) -> str:
    labels = {
        "strong_buy": "strong buy",
        "buy": "buy",
    }
    return labels.get(signal, signal.replace("_", " "))


def _initial_prompt(
    *,
    ticker: str,
    company_name: str,
    sources_dir: Path,
    screen_signal: str = "strong_buy",
) -> str:
    signal_label = _screen_signal_label(screen_signal)
    filings_index = sources_dir / "filings" / "filings_index.json"
    filings_bodies = sources_dir / "filings" / "bodies"
    return f"""You are an equity research analyst writing a deep first-pass memo on {company_name} ({ticker}).

The quantitative screen currently rates this name as a {signal_label}.

Read the source files in: {sources_dir.resolve()}

Primary regulatory filings (preferred for FINANCIAL REVIEW — keep separate from Yahoo):
- `{filings_index.resolve()}` — catalog with period labels: annual, interim, or other
  (UK RNS, US SEC EDGAR 10-K/10-Q/8-K, ASX announcements, or Euro results discovery —
  see `regime` in the index)
- `{filings_bodies.resolve()}/` — plain-text extracts of filing bodies when downloadable

Secondary / context only (do not mix into a blended number set):
- `financials_annual.json` — Yahoo annual statements (and cached quarterly income). Use only when filing bodies lack the figure you need, and say you fell back to Yahoo.
- `screening_snapshot.json` — quantitative value screen output (models passed, metrics, timing)
- `news_manifest.json` — up to one year of news headlines from yfinance and Google News RSS
- `macro_context.json` — offline market-regime markers (rates/FX/index proxies). Optional colour only —
  do **not** use macro to auto-veto, reweight, or override the quantitative screen signal.

Write a research memo with EXACTLY these plain-text section headings:

EXECUTIVE SUMMARY
3–5 sentences: investment case, valuation hook, and key debate.

INVESTMENT THESIS
Why this is a {signal_label} for a value investor. Tie quantitative screen results to business quality.

FINANCIAL REVIEW
Analyse the financial trend using primary filings first.
Cover both annual results (annual report / 10-K) and interim (half-year / 10-Q / trading update) releases when present in `filings_index.json`.
Cite figures from filing body extracts under `filings/bodies/` when available; otherwise cite `financials_annual.json` and state the fallback explicitly.
Do not invent numbers. Note gaps if interim or annual filings are missing from the index.

RISKS AND RED FLAGS
Regulatory, cyclical, governance, pension, or competitive risks not fully captured by screens.
Use filing language (going concern, contingencies, covenants) when present in bodies.

NEWS HIGHLIGHTS
Summarise material news from the past year: strategy shifts, management changes, regulatory actions, M&A.
Cite article titles/dates from the manifest. Flag if news coverage is thin.

RESEARCH VERDICT
Structured conviction overlay for the quantitative screen (does not replace the screen signal).
Use EXACTLY these lines:
Verdict: accumulate | neutral | caution | pass
Risk: low | medium | high
Confidence: 0.00–1.00 (decimal, e.g. 0.75)
Rationale: One sentence on whether deep research confirms, is neutral on, or weakens the {signal_label} case.

Rules:
- UK English, concise professional tone.
- Do not give buy/sell price targets.
- If a source is missing data, say so explicitly.
- Prefer unresolved over false confidence when filings or figures are thin —
  verify-before-trade packs surface these gaps; do not invent certainty.
- Prefer one consistent primary source for each figure (filings over Yahoo).
"""


def _weekly_update_prompt(
    *,
    ticker: str,
    company_name: str,
    sources_dir: Path,
    news_batch_path: Path,
    existing_markdown_path: Path,
    screen_signal: str = "strong_buy",
) -> str:
    signal_label = _screen_signal_label(screen_signal)
    return f"""You are updating an existing research memo on {company_name} ({ticker}).

The quantitative screen currently rates this name as a {signal_label}.

Existing memo: {existing_markdown_path.resolve()}
New news batch since last update: {news_batch_path.resolve()}
Full news archive: {(sources_dir / 'news_manifest.json').resolve()}
Primary filings index (annual + interim; RNS / SEC / ASX / Euro): {(sources_dir / 'filings' / 'filings_index.json').resolve()}
Filing body extracts (if any): {(sources_dir / 'filings' / 'bodies').resolve()}
Yahoo financials (secondary only): {(sources_dir / 'financials_annual.json').resolve()}
Macro regime context (optional colour only — not a scoring input): {(sources_dir / 'macro_context.json').resolve()}

Write ONE section with the heading exactly as shown:

WEEKLY UPDATE
Summarise any new information from the news batch and any new/changed annual or interim filings (10-K/10-Q, RNS, ASX, or Euro results), and whether it changes the thesis, risks, or timing.
You may briefly note macro_context.json as background colour if relevant; do not let macro alone change the RESEARCH VERDICT.
If nothing material changed, say so in 2–3 sentences.
Reference article/filing titles and dates where relevant.
Do not repeat the full prior memo.

Then add a RESEARCH VERDICT section (revise conviction only if material news changes the investment case; otherwise repeat the prior verdict unchanged):

RESEARCH VERDICT
Use EXACTLY these lines:
Verdict: accumulate | neutral | caution | pass
Risk: low | medium | high
Confidence: 0.00–1.00 (decimal, e.g. 0.75)
Rationale: One sentence on whether this week's news confirms, is neutral on, or weakens the {signal_label} case.
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
        screen_signal=report.signal,
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


def _gap_fill_prompt(
    *,
    ticker: str,
    company_name: str,
    sources_dir: Path,
    existing_markdown_path: Path,
    open_questions: list[str],
    screen_signal: str = "strong_buy",
) -> str:
    signal_label = _screen_signal_label(screen_signal)
    numbered = "\n".join(f"{idx}. {question}" for idx, question in enumerate(open_questions, start=1))
    source_map = sources_dir / "gap_fill_source_map.json"
    return f"""You are closing qualitative research gaps on {company_name} ({ticker}).

The quantitative screen currently rates this name as a {signal_label}.

Existing memo: {existing_markdown_path.resolve()}
Source map (inventory + alternate plan): {source_map.resolve()}
Primary filings index: {(sources_dir / 'filings' / 'filings_index.json').resolve()}
Filing body extracts: {(sources_dir / 'filings' / 'bodies').resolve()}
Yahoo financials (secondary): {(sources_dir / 'financials_annual.json').resolve()}
News archive (includes alternate themed pulls): {(sources_dir / 'news_manifest.json').resolve()}
Alternate news batch: {(sources_dir / 'alternate_news.json').resolve()}
Screen snapshot: {(sources_dir / 'screening_snapshot.json').resolve()}
Macro context (colour only): {(sources_dir / 'macro_context.json').resolve()}

Open qualitative questions from this week's deep-analysis / email red-flag pass:
{numbered or '1. Resolve the qualitative risks highlighted for this name.'}

Evidence discipline:
1. Read ``gap_fill_source_map.json`` first and walk its ``evidence_ladder`` in order.
2. Prefer filing bodies, then filings index, Yahoo, news/alternate news, then screen snapshot.
3. If a question stays unresolved, choose concrete ``planned_alternate_sources`` (or equally specific external sources) and say what they would unlock — do not invent their contents.
4. Emit research-model improvements whenever local sources are structurally insufficient (thin RNS bodies, missing IR PDFs, prompt gaps, etc.).

Write these sections with headings EXACTLY as shown:

GAP FILL UPDATE
For EACH open question above, use this mini-block:
Q: <question text>
Status: resolved | partially_resolved | unresolved
Evidence: one or two sentences citing source titles/paths (or explicitly say still missing).
SourcesTried: comma-separated ladder steps actually inspected
NextSources: concrete alternate sources to seek next (or "none" if resolved)

FINANCIAL REVIEW
Rewrite the financial review to incorporate any newly resolved facts.
Prefer filing body extracts; if falling back to Yahoo/news, say so. Note remaining gaps.

RISKS AND RED FLAGS
Rewrite risks with the same honesty: evidenced vs still open, and which alternate source would close each open item.

RESEARCH VERDICT
Use EXACTLY these lines:
Verdict: accumulate | neutral | caution | pass
Risk: low | medium | high
Confidence: 0.00–1.00 (decimal, e.g. 0.75)
Rationale: One sentence on whether gap-fill strengthens, is neutral on, or weakens the {signal_label} case.

RESEARCH MODEL SUGGESTIONS
0–5 bullets for improving the research system itself (ingest, prompts, scoring overlay, data vendors).
Use EXACTLY this bullet shape:
- area: ingest | priority: high | suggestion: …
- area: prompt | priority: medium | suggestion: …
Allowed areas: ingest, prompt, scoring, coverage, ops.
Only suggest actionable pipeline changes (e.g. Companies House PDF ingest, deeper RNS body extract, IR presentation fetch). Skip empty platitudes.

Rules:
- UK English, concise professional tone.
- Do not invent numbers or filing language.
- Prefer unresolved over false confidence when sources are thin.
- Do not give buy/sell price targets.
"""


def _gap_fill_followup_prompt(
    *,
    ticker: str,
    company_name: str,
    sources_dir: Path,
    existing_markdown_path: Path,
    open_questions: list[str],
    body_refetch: dict[str, Any] | None = None,
) -> str:
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(open_questions, start=1))
    fetched = (body_refetch or {}).get("fetched")
    with_body = (body_refetch or {}).get("with_body_after")
    return f"""Follow-up gap-fill on {company_name} ({ticker}).

Newly available filing body extracts were fetched this pass
(fetched={fetched}, with_body_after={with_body}). Re-read:
- {(sources_dir / 'filings' / 'bodies').resolve()}
- {(sources_dir / 'filings' / 'filings_index.json').resolve()}
- Existing memo: {existing_markdown_path.resolve()}

Still-open questions only:
{numbered or '1. Resolve remaining qualitative gaps.'}

Rewrite ONLY these sections (same headings and mini-block format as before):

GAP FILL UPDATE
(For each still-open question: Q / Status / Evidence / SourcesTried / NextSources)

FINANCIAL REVIEW
RISKS AND RED FLAGS
RESEARCH VERDICT
RESEARCH MODEL SUGGESTIONS

Rules: UK English; do not invent filing language; cite body paths when used;
prefer unresolved over false confidence.
"""


@dataclass
class GapFillAgentResult:
    document: ResearchDocument
    question_outcomes: list[dict[str, str]]
    model_suggestions: list[dict[str, str]]


def run_gap_fill_research_agent(
    *,
    existing: ResearchDocument,
    sources_dir: Path,
    markdown_path: Path,
    open_questions: list[str],
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    screen_signal: str | None = None,
    follow_up: bool = False,
    body_refetch: dict[str, Any] | None = None,
) -> GapFillAgentResult:
    """Rewrite financial/risk sections to address open qualitative questions."""
    from value_investor.research.gap_fill_sources import (
        parse_model_suggestions,
        parse_question_outcomes,
    )

    if follow_up:
        prompt = _gap_fill_followup_prompt(
            ticker=existing.ticker,
            company_name=existing.name,
            sources_dir=sources_dir,
            existing_markdown_path=markdown_path,
            open_questions=open_questions,
            body_refetch=body_refetch,
        )
    else:
        prompt = _gap_fill_prompt(
            ticker=existing.ticker,
            company_name=existing.name,
            sources_dir=sources_dir,
            existing_markdown_path=markdown_path,
            open_questions=open_questions,
            screen_signal=screen_signal or existing.signal,
        )
    text, agent_id = _run_agent_prompt(
        prompt=prompt,
        api_key=api_key,
        model=model,
        cwd=cwd,
        agent_id=existing.agent_id,
    )
    sections = parse_research_sections(text)
    gap_summary = sections.get("gap_fill_update", "").strip()
    if not gap_summary:
        gap_summary = sections.get("weekly_update", "").strip()
    model_suggestions = parse_model_suggestions(sections.get("research_model_suggestions", ""))
    question_outcomes = parse_question_outcomes(gap_summary)
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
    financial_review = sections.get("financial_review", "").strip() or existing.financial_review
    risks_and_flags = sections.get("risks_and_flags", "").strip() or existing.risks_and_flags
    weekly_entry: dict[str, str] = {
        "date": now.strftime("%Y-%m-%d"),
        "as_of": now.isoformat(),
        "summary": gap_summary or ("Gap-fill follow-up completed." if follow_up else "Gap-fill pass completed."),
        "kind": "gap_fill_followup" if follow_up else "gap_fill",
    }
    if existing.research_verdict != new_verdict:
        weekly_entry["prior_verdict"] = existing.research_verdict or ""
        weekly_entry["new_verdict"] = new_verdict or ""
    document = ResearchDocument(
        ticker=existing.ticker,
        name=existing.name,
        signal=existing.signal,
        version=existing.version + 1,
        created_at=existing.created_at,
        updated_at=now.isoformat(),
        mode="gap_fill",
        executive_summary=existing.executive_summary,
        investment_thesis=existing.investment_thesis,
        financial_review=financial_review,
        risks_and_flags=risks_and_flags,
        news_highlights=existing.news_highlights,
        research_verdict=new_verdict,
        research_risk_level=new_risk,
        research_confidence=new_confidence,
        research_rationale=new_rationale,
        weekly_updates=[*existing.weekly_updates, weekly_entry],
        source_counts=existing.source_counts,
        agent_id=agent_id or existing.agent_id,
    )
    return GapFillAgentResult(
        document=document,
        question_outcomes=question_outcomes,
        model_suggestions=model_suggestions,
    )


def run_weekly_research_update_agent(
    *,
    existing: ResearchDocument,
    sources_dir: Path,
    news_batch_path: Path,
    markdown_path: Path,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    screen_signal: str | None = None,
) -> ResearchDocument:
    prompt = _weekly_update_prompt(
        ticker=existing.ticker,
        company_name=existing.name,
        sources_dir=sources_dir,
        news_batch_path=news_batch_path,
        existing_markdown_path=markdown_path,
        screen_signal=screen_signal or existing.signal,
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
