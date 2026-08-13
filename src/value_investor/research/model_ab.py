"""L88 selective frontier-model A/B compare for research memos."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    MODEL_API_RATES,
    SPEND_POOL_AD_HOC,
    record_estimated_spend,
)
from value_investor.research.agent import run_initial_research_agent
from value_investor.research.document import RESEARCH_SECTIONS, ResearchDocument, render_research_markdown
from value_investor.research.gap_fill_sources import inspect_local_sources
from value_investor.research.ingest import ingest_research_sources
from value_investor.research.source_quality import score_research_sources
from value_investor.research.store import ResearchStore
from value_investor.storage import write_json
from value_investor.summary import CompanyReport

DEFAULT_BASELINE_MODEL = "composer-2.5"
DEFAULT_CHALLENGER_MODEL = "grok-4.6"
DEFAULT_AB_OUTPUT_DIR = Path("docs/data/research_model_ab")

_FILING_MARKERS = (
    "filings/bodies",
    "filings_index",
    "filing body",
    "annual report",
    "interim report",
    "10-k",
    "10-q",
    "rns",
    "companies house",
)
_YAHOO_MARKERS = ("financials_annual.json", "yahoo", "yfinance")
_GAP_MARKERS = (
    "missing",
    "unavailable",
    "not disclosed",
    "not available",
    "thin coverage",
    "gap",
    "could not verify",
)
_CURRENCY_FIGURE_RE = re.compile(r"[£$€]\s?[\d,]+|[\d,]+\s?(?:m|bn|million|billion)\b", re.I)


@dataclass(frozen=True)
class MemoRubricScore:
    citation_accuracy: float
    filing_alignment: float
    gap_honesty: float
    structural: float
    composite: float
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_accuracy": self.citation_accuracy,
            "filing_alignment": self.filing_alignment,
            "gap_honesty": self.gap_honesty,
            "structural": self.structural,
            "composite": self.composite,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ModelAbVariant:
    model_id: str
    document: ResearchDocument
    rubric: MemoRubricScore
    source_quality: dict[str, Any]
    estimated_cost_usd: float
    markdown_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "agent_id": self.document.agent_id,
            "research_verdict": self.document.research_verdict,
            "research_confidence": self.document.research_confidence,
            "rubric": self.rubric.to_dict(),
            "source_quality": self.source_quality,
            "estimated_cost_usd": self.estimated_cost_usd,
            "markdown_path": self.markdown_path,
        }


@dataclass(frozen=True)
class ModelAbComparison:
    ticker: str
    company_name: str
    signal: str
    run_id: str
    baseline: ModelAbVariant
    challenger: ModelAbVariant
    winner: str
    output_dir: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ticker": self.ticker,
            "company_name": self.company_name,
            "signal": self.signal,
            "run_id": self.run_id,
            "winner": self.winner,
            "output_dir": str(self.output_dir),
            "baseline": self.baseline.to_dict(),
            "challenger": self.challenger.to_dict(),
            "rubric_weights": {
                "citation_accuracy": 0.35,
                "filing_alignment": 0.30,
                "gap_honesty": 0.20,
                "structural": 0.15,
            },
        }


def _marker_hits(text: str, markers: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for marker in markers if marker in lowered)


def score_memo_rubric(
    doc: ResearchDocument,
    *,
    inventory: dict[str, Any] | None = None,
) -> MemoRubricScore:
    """Heuristic rubric for memo quality on the same source snapshot."""
    full_text = doc.full_text
    financial = doc.financial_review or ""
    notes: list[str] = []

    filing_hits = _marker_hits(full_text, _FILING_MARKERS)
    yahoo_hits = _marker_hits(full_text, _YAHOO_MARKERS)
    if filing_hits or yahoo_hits:
        citation_accuracy = round(filing_hits / max(filing_hits + yahoo_hits, 1), 3)
    else:
        citation_accuracy = 0.0
        notes.append("No filing or Yahoo source markers detected.")

    financial_filing_hits = _marker_hits(financial, _FILING_MARKERS)
    has_currency_figures = bool(_CURRENCY_FIGURE_RE.search(financial))
    filing_alignment = round(
        min(1.0, (financial_filing_hits + (1.0 if has_currency_figures else 0.0)) / 4.0),
        3,
    )
    if financial_filing_hits == 0:
        notes.append("FINANCIAL REVIEW does not cite filing sources.")

    thin = list((inventory or {}).get("thin") or [])
    gap_hits = _marker_hits(full_text, _GAP_MARKERS)
    if thin:
        gap_honesty = round(min(1.0, gap_hits / 2.0), 3)
        if gap_hits == 0:
            notes.append(f"Sources thin ({', '.join(thin[:3])}) but memo does not flag gaps.")
    else:
        gap_honesty = 1.0 if gap_hits <= 2 else round(max(0.0, 1.0 - (gap_hits - 2) * 0.1), 3)

    section_count = sum(1 for key in RESEARCH_SECTIONS if getattr(doc, key, "").strip())
    verdict_ok = bool(doc.research_verdict and doc.research_confidence is not None)
    structural = round(min(1.0, (section_count / len(RESEARCH_SECTIONS)) * (1.0 if verdict_ok else 0.7)), 3)
    if not verdict_ok:
        notes.append("RESEARCH VERDICT block incomplete.")

    composite = round(
        0.35 * citation_accuracy
        + 0.30 * filing_alignment
        + 0.20 * gap_honesty
        + 0.15 * structural,
        3,
    )
    return MemoRubricScore(
        citation_accuracy=citation_accuracy,
        filing_alignment=filing_alignment,
        gap_honesty=gap_honesty,
        structural=structural,
        composite=composite,
        notes=tuple(notes),
    )


def estimate_model_memo_usd(model_id: str, *, baseline_usd: float = 0.4) -> float:
    """Scale the baseline memo estimate by published token rates."""
    rates = MODEL_API_RATES.get(model_id)
    baseline_rates = MODEL_API_RATES.get(DEFAULT_BASELINE_MODEL)
    if not rates or not baseline_rates:
        return baseline_usd
    inp, out = rates
    b_inp, b_out = baseline_rates
    baseline_score = b_inp + 1.5 * b_out
    model_score = inp + 1.5 * out
    if baseline_score <= 0:
        return baseline_usd
    return round(baseline_usd * (model_score / baseline_score), 2)


def _source_counts_from_inventory(inventory: dict[str, Any], sources_dir: Path) -> dict[str, int]:
    filings_summary = dict(inventory.get("filings_summary") or {})
    financial_years = 0
    financial_path = sources_dir / "financials_annual.json"
    if financial_path.exists():
        try:
            from value_investor.storage import read_json

            payload = read_json(financial_path)
            financial_years = len(payload.get("annual") or payload.get("years") or [])
        except (OSError, ValueError, TypeError):
            financial_years = 0
    return {
        "financial_years": financial_years,
        "news_articles": int(inventory.get("news_article_count") or 0),
        "filings_total": int(filings_summary.get("total") or 0),
        "filings_annual": int(filings_summary.get("annual") or 0),
        "filings_interim": int(filings_summary.get("interim") or 0),
        "filings_with_body": int(
            filings_summary.get("with_body") or inventory.get("filings_indexed_bodies") or 0
        ),
    }


def _prepare_shared_sources(
    *,
    report: CompanyReport,
    primary_store: ResearchStore,
    sources_dir: Path,
    market: str | None,
) -> tuple[dict[str, Any], dict[str, int]]:
    primary_sources = primary_store.sources_dir(report.ticker)
    if primary_sources.exists() and any(primary_sources.iterdir()):
        sources_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(primary_sources, sources_dir, dirs_exist_ok=True)
        inventory = inspect_local_sources(sources_dir)
        return inventory, _source_counts_from_inventory(inventory, sources_dir)

    source_meta = ingest_research_sources(
        ticker=report.ticker,
        company_name=report.name,
        screening_snapshot=report.to_dict(),
        sources_dir=sources_dir,
        market=market,
        deepen_history=True,
    )
    inventory = inspect_local_sources(sources_dir)
    filings_summary = source_meta.get("filings_summary") or {}
    source_counts = {
        "financial_years": int(source_meta.get("financial_years") or 0),
        "news_articles": int(source_meta.get("news_total") or 0),
        "filings_total": int(filings_summary.get("total") or 0),
        "filings_annual": int(filings_summary.get("annual") or 0),
        "filings_interim": int(filings_summary.get("interim") or 0),
        "filings_with_body": int(filings_summary.get("with_body") or 0),
    }
    return inventory, source_counts


def _pick_winner(baseline: MemoRubricScore, challenger: MemoRubricScore) -> str:
    if challenger.composite > baseline.composite:
        return "challenger"
    if baseline.composite > challenger.composite:
        return "baseline"
    if challenger.citation_accuracy > baseline.citation_accuracy:
        return "challenger"
    if baseline.citation_accuracy > challenger.citation_accuracy:
        return "baseline"
    return "tie"


def _variant_dir(run_dir: Path, label: str) -> Path:
    path = run_dir / label
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_variant(
    *,
    label: str,
    model_id: str,
    report: CompanyReport,
    sources_dir: Path,
    run_dir: Path,
    api_key: str,
    cwd: str | None,
    inventory: dict[str, Any],
    source_counts: dict[str, int],
    memo_usd: float,
) -> ModelAbVariant:
    doc, _agent_id = run_initial_research_agent(
        report=report,
        sources_dir=sources_dir,
        api_key=api_key,
        model=model_id,
        cwd=cwd,
    )
    doc.source_counts = dict(source_counts)
    rubric = score_memo_rubric(doc, inventory=inventory)
    source_quality = score_research_sources(
        source_counts=source_counts,
        inventory=inventory,
        question_outcomes=doc.question_outcomes,
    )
    variant_dir = _variant_dir(run_dir, label)
    markdown_path = variant_dir / "research.md"
    markdown_path.write_text(render_research_markdown(doc), encoding="utf-8")
    write_json(variant_dir / "research.json", doc.to_dict(), compact=True)
    return ModelAbVariant(
        model_id=model_id,
        document=doc,
        rubric=rubric,
        source_quality=source_quality,
        estimated_cost_usd=estimate_model_memo_usd(model_id, baseline_usd=memo_usd),
        markdown_path=str(markdown_path),
    )


def format_comparison_markdown(comparison: ModelAbComparison) -> str:
    base = comparison.baseline
    chall = comparison.challenger
    lines = [
        f"# Research model A/B — {comparison.company_name} ({comparison.ticker})",
        "",
        f"- Run: `{comparison.run_id}`",
        f"- Screen signal: **{comparison.signal}**",
        f"- Winner (rubric): **{comparison.winner}**",
        "",
        "## Rubric (same source snapshot)",
        "",
        "| Dimension | Baseline ({}) | Challenger ({}) |".format(
            base.model_id,
            chall.model_id,
        ),
        "| --- | ---: | ---: |",
        f"| Citation accuracy | {base.rubric.citation_accuracy:.3f} | {chall.rubric.citation_accuracy:.3f} |",
        f"| Filing alignment | {base.rubric.filing_alignment:.3f} | {chall.rubric.filing_alignment:.3f} |",
        f"| Gap honesty | {base.rubric.gap_honesty:.3f} | {chall.rubric.gap_honesty:.3f} |",
        f"| Structural | {base.rubric.structural:.3f} | {chall.rubric.structural:.3f} |",
        f"| **Composite** | **{base.rubric.composite:.3f}** | **{chall.rubric.composite:.3f}** |",
        "",
        "## Verdict overlay",
        "",
        f"- Baseline: {base.document.research_verdict} "
        f"(confidence {base.document.research_confidence}, risk {base.document.research_risk_level})",
        f"- Challenger: {chall.document.research_verdict} "
        f"(confidence {chall.document.research_confidence}, risk {chall.document.research_risk_level})",
        "",
        "## Estimated cost",
        "",
        f"- Baseline: ${base.estimated_cost_usd:.2f}",
        f"- Challenger: ${chall.estimated_cost_usd:.2f}",
        f"- Delta: ${chall.estimated_cost_usd - base.estimated_cost_usd:+.2f}",
        "",
        "## Notes",
        "",
    ]
    for label, variant in (("Baseline", base), ("Challenger", chall)):
        if variant.rubric.notes:
            lines.append(f"**{label} ({variant.model_id})**")
            for note in variant.rubric.notes:
                lines.append(f"- {note}")
            lines.append("")
    lines.extend(
        [
            "## Human review",
            "",
            "Read both memos side-by-side and confirm:",
            "1. Filing figures match `sources/filings/bodies/` extracts.",
            "2. Open risks are explicit rather than invented.",
            "3. Verdict confidence matches evidence depth.",
            "",
            f"- Baseline memo: `{base.markdown_path}`",
            f"- Challenger memo: `{chall.markdown_path}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run_model_ab_compare(
    *,
    report: CompanyReport,
    api_key: str,
    output_root: Path = DEFAULT_AB_OUTPUT_DIR,
    primary_output_dir: Path | None = None,
    baseline_model: str = DEFAULT_BASELINE_MODEL,
    challenger_model: str = DEFAULT_CHALLENGER_MODEL,
    cwd: str | None = None,
    market: str | None = None,
    memo_usd: float = 0.4,
    record_spend: bool = True,
    policy_path: Path | None = None,
) -> ModelAbComparison:
    """Run baseline vs challenger initial memos on one ticker (L88 pilot)."""
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root / report.ticker / run_id
    sources_dir = run_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    primary_store = ResearchStore(primary_output_dir or Path("output"))
    inventory, source_counts = _prepare_shared_sources(
        report=report,
        primary_store=primary_store,
        sources_dir=sources_dir,
        market=market,
    )
    write_json(run_dir / "source_inventory.json", inventory, compact=False)

    baseline = _run_variant(
        label="baseline",
        model_id=baseline_model,
        report=report,
        sources_dir=sources_dir,
        run_dir=run_dir,
        api_key=api_key,
        cwd=cwd,
        inventory=inventory,
        source_counts=source_counts,
        memo_usd=memo_usd,
    )
    challenger = _run_variant(
        label="challenger",
        model_id=challenger_model,
        report=report,
        sources_dir=sources_dir,
        run_dir=run_dir,
        api_key=api_key,
        cwd=cwd,
        inventory=inventory,
        source_counts=source_counts,
        memo_usd=memo_usd,
    )
    winner = _pick_winner(baseline.rubric, challenger.rubric)
    comparison = ModelAbComparison(
        ticker=report.ticker,
        company_name=report.name,
        signal=report.signal,
        run_id=run_id,
        baseline=baseline,
        challenger=challenger,
        winner=winner,
        output_dir=run_dir,
    )
    write_json(run_dir / "comparison.json", comparison.to_dict(), compact=False)
    (run_dir / "comparison.md").write_text(format_comparison_markdown(comparison), encoding="utf-8")

    if record_spend:
        total = baseline.estimated_cost_usd + challenger.estimated_cost_usd
        record_estimated_spend(total, policy_path, pool=SPEND_POOL_AD_HOC)

    return comparison


def report_for_ticker(reports: list[CompanyReport], ticker: str) -> CompanyReport | None:
    normalized = ticker.strip().upper()
    for report in reports:
        if report.ticker.upper() == normalized:
            return report
    return None
