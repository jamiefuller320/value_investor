"""Cursor SDK deep analysis for top screening candidates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.data_quality import MIN_QUALITY_FOR_ANALYSIS
from value_investor.summary import CompanyReport


@dataclass
class DeepAnalysis:
    executive_intro: str
    top_picks_analysis: str
    red_flags: str

    @property
    def full_text(self) -> str:
        parts = [self.executive_intro]
        if self.top_picks_analysis:
            parts.append(self.top_picks_analysis)
        if self.red_flags:
            parts.append(self.red_flags)
        return "\n\n".join(p.strip() for p in parts if p.strip())


def _eligible_for_deep_analysis(reports: list[CompanyReport]) -> list[CompanyReport]:
    """Exclude low-data or weak-signal names from agent review."""
    return [
        report
        for report in reports
        if report.data_quality_score >= MIN_QUALITY_FOR_ANALYSIS
        and report.signal in ("strong_buy", "buy")
    ]


def _build_analysis_payload(
    reports: list[CompanyReport],
    model_results: list[dict[str, Any]],
    *,
    top_n: int = 5,
) -> dict[str, Any]:
    eligible = _eligible_for_deep_analysis(reports)
    top_reports = [r.to_dict() for r in eligible[:top_n]]
    top_tickers = {r["ticker"] for r in top_reports}
    top_model_results = [row for row in model_results if row.get("ticker") in top_tickers]

    signal_counts: dict[str, int] = {}
    sector_counts: dict[str, int] = {}
    for report in reports:
        signal_counts[report.signal] = signal_counts.get(report.signal, 0) + 1
        if report.sector:
            sector_counts[report.sector] = sector_counts.get(report.sector, 0) + 1

    return {
        "signal_distribution": signal_counts,
        "sector_distribution": sector_counts,
        "top_candidates": top_reports,
        "model_results_for_top_candidates": top_model_results,
    }


def _build_deep_analysis_prompt(payload_path: Path) -> str:
    return f"""You are a value investing analyst reviewing FTSE screening output.

Read the structured JSON at: {payload_path}

It contains signal distribution, top candidates with per-company summaries, and detailed
per-model pass/fail reasons for those candidates.

Write THREE sections with plain-text headings exactly as shown:

EXECUTIVE INTRO
3–5 sentences on overall market tone (strong buys vs avoids), sector clusters among top picks,
and one caution about data limitations.

TOP PICKS ANALYSIS
For each of the top candidates (up to 5), write a short paragraph covering:
- Why quantitative models flagged it (cite model passes and key metrics from the JSON)
- Sector concentration risk if relevant
- Verdict: accumulate / watchlist / pass with one-sentence rationale
Do not invent figures — only use data from the JSON.

RED FLAGS
List qualitative risks NOT captured by the screen for the top candidates:
regulatory risk, cyclicality, pension deficits, governance, or balance-sheet concerns.
If data is insufficient, say so explicitly as an open question.
Prefer bullet lines that start with the ticker (e.g. ``AEP.L: …``).

NAMES WORTH DEEPER RESEARCH
Up to 3 tickers from the top candidates, one bullet each:
``TICKER — open qualitative question to resolve``
"""


def run_deep_analysis(
    *,
    reports: list[CompanyReport],
    model_results_df,
    output_dir: Path,
    api_key: str,
    model: str = "composer-2.5",
    top_n: int = 5,
    cwd: str | None = None,
) -> DeepAnalysis:
    """Run Cursor agent deep analysis on top screening candidates."""
    import os

    payload = _build_analysis_payload(
        reports,
        model_results_df.to_dict(orient="records"),
        top_n=top_n,
    )
    if not payload["top_candidates"]:
        raise RuntimeError(
            "No candidates meet data-quality threshold for deep analysis "
            f"(requires score >= {MIN_QUALITY_FOR_ANALYSIS:.0%} and buy/strong_buy signal)"
        )
    payload_path = output_dir / "deep_analysis_payload.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    from value_investor.storage import write_json

    write_json(payload_path, payload, compact=True)

    try:
        agent_result = Agent.prompt(
            _build_deep_analysis_prompt(payload_path.resolve()),
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=cwd or os.getcwd()),
            ),
        )
    except CursorAgentError as err:
        raise RuntimeError(f"Agent startup failed: {err.message}") from err

    if agent_result.status == "error":
        raise RuntimeError(f"Agent run failed: {agent_result.id}")

    text = (agent_result.result or "").strip()
    return _parse_deep_analysis(text)


def _normalize_heading(line: str) -> str:
    """Strip markdown/bold wrappers so section titles still match."""
    text = line.strip()
    text = text.lstrip("#").strip()
    if text.startswith("**") and text.endswith("**") and len(text) > 4:
        text = text[2:-2].strip()
    return text.rstrip(":").strip().upper()


def _parse_deep_analysis(text: str) -> DeepAnalysis:
    sections = {
        "executive_intro": "",
        "top_picks_analysis": "",
        "red_flags": "",
    }
    current = "executive_intro"
    lines: list[str] = []

    for line in text.splitlines():
        upper = _normalize_heading(line)
        if upper in {"EXECUTIVE INTRO", "EXECUTIVE SUMMARY"}:
            if lines:
                sections[current] = "\n".join(lines).strip()
                lines = []
            current = "executive_intro"
            continue
        if upper in {"TOP PICKS ANALYSIS", "TOP PICKS"}:
            if lines:
                sections[current] = "\n".join(lines).strip()
                lines = []
            current = "top_picks_analysis"
            continue
        if upper in {
            "RED FLAGS",
            "NAMES WORTH DEEPER RESEARCH",
            "NAMES FOR DEEPER RESEARCH",
            "OPEN QUESTIONS",
        }:
            if lines:
                chunk = "\n".join(lines).strip()
                if current == "red_flags" and sections["red_flags"]:
                    sections["red_flags"] = f"{sections['red_flags']}\n\n{chunk}".strip()
                else:
                    sections[current] = chunk
                lines = []
            current = "red_flags"
            # Keep the heading label inside red_flags when it names the deeper-research list
            # so extractors can still find "worth deeper research" wording.
            if upper != "RED FLAGS":
                lines.append(line.strip())
            continue
        lines.append(line)

    trailing = "\n".join(lines).strip()
    if trailing:
        if current == "red_flags" and sections["red_flags"]:
            sections["red_flags"] = f"{sections['red_flags']}\n\n{trailing}".strip()
        else:
            sections[current] = trailing

    # Fallback: models sometimes dump everything under the first heading.
    if not sections["red_flags"] and sections["executive_intro"]:
        intro = sections["executive_intro"]
        for marker in (
            "NAMES WORTH DEEPER RESEARCH",
            "NAMES FOR DEEPER RESEARCH",
            "RED FLAGS",
            "Names worth deeper research",
        ):
            idx = intro.upper().find(marker.upper())
            if idx >= 0:
                sections["red_flags"] = intro[idx:].strip()
                sections["executive_intro"] = intro[:idx].strip()
                break

    return DeepAnalysis(**sections)
