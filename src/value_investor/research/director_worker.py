"""Trial director–worker research orchestration (Grok director, Composer workers)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    SPEND_POOL_AD_HOC,
    record_estimated_spend,
)
from value_investor.research.agent import _run_agent_prompt
from value_investor.research.document import (
    ResearchDocument,
    parse_research_sections,
    render_research_markdown,
)
from value_investor.research.gap_fill_sources import EVIDENCE_LADDER
from value_investor.research.model_ab import (
    estimate_model_memo_usd,
    prepare_shared_research_sources,
    report_for_ticker,
    score_memo_rubric,
)
from value_investor.research.source_quality import score_research_sources
from value_investor.research.store import ResearchStore
from value_investor.research.verdict import parse_research_verdict, parse_risk_tags
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

DEFAULT_DIRECTOR_MODEL = "grok-4.6"
DEFAULT_WORKER_MODEL = "composer-2.5"
DEFAULT_DW_OUTPUT_DIR = Path("docs/data/research_director_worker")
DEFAULT_MAX_WORKER_TASKS = 5
ORCHESTRATION_VERSION = 1

VALID_TASK_TYPES = frozenset(
    {
        "summarize_filing_body",
        "digest_news_manifest",
        "screen_context",
        "gap_inventory",
    }
)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class DirectorWorkerRun:
    ticker: str
    company_name: str
    signal: str
    run_id: str
    output_dir: Path
    director_model: str
    worker_model: str
    task_plan: dict[str, Any]
    worker_results: list[dict[str, Any]]
    document: ResearchDocument
    rubric: dict[str, Any]
    estimated_cost_usd: float
    director_agent_ids: tuple[str | None, str | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "orchestration_version": ORCHESTRATION_VERSION,
            "ticker": self.ticker,
            "company_name": self.company_name,
            "signal": self.signal,
            "run_id": self.run_id,
            "output_dir": str(self.output_dir),
            "director_model": self.director_model,
            "worker_model": self.worker_model,
            "estimated_cost_usd": self.estimated_cost_usd,
            "director_agent_ids": {
                "plan": self.director_agent_ids[0],
                "synthesis": self.director_agent_ids[1],
            },
            "task_plan": self.task_plan,
            "worker_results": self.worker_results,
            "rubric": self.rubric,
            "research_verdict": self.document.research_verdict,
            "research_confidence": self.document.research_confidence,
            "markdown_path": str(self.output_dir / "research.md"),
        }


def load_report_from_latest(
    ticker: str,
    latest_json: Path = Path("docs/data/latest.json"),
) -> CompanyReport | None:
    """Load a CompanyReport from published dashboard JSON when CSV screen is absent."""
    if not latest_json.exists():
        return None
    payload = read_json(latest_json)
    reports = payload.get("reports") if isinstance(payload, dict) else None
    if not isinstance(reports, list):
        return None
    row = next(
        (item for item in reports if str(item.get("ticker", "")).upper() == ticker.upper()), None
    )
    if row is None:
        return None
    return CompanyReport.from_dict(row)


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object from agent output (fenced or raw)."""
    text = text.strip()
    match = _JSON_BLOCK_RE.search(text)
    if match:
        return json.loads(match.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("No JSON object found in agent output")


def _screen_signal_label(signal: str) -> str:
    labels = {"strong_buy": "strong buy", "buy": "buy"}
    return labels.get(signal, signal.replace("_", " "))


def _normalize_source_target(raw: str, sources_dir: Path) -> str:
    """Map index body paths to paths relative to ``sources_dir``."""
    text = str(raw or "").strip()
    if not text:
        return text
    normalized = text.replace("\\", "/")
    if "/filings/bodies/" in normalized:
        return "filings/bodies/" + normalized.rsplit("/filings/bodies/", 1)[-1]
    path = Path(text)
    candidate = sources_dir / "filings" / "bodies" / path.name
    if path.name and candidate.exists():
        return f"filings/bodies/{path.name}"
    try:
        resolved = path if path.is_absolute() else (sources_dir / path)
        return str(resolved.resolve().relative_to(sources_dir.resolve()))
    except ValueError:
        return text


def _filing_body_tasks(sources_dir: Path, *, limit: int) -> list[dict[str, Any]]:
    index_path = sources_dir / "filings" / "filings_index.json"
    if not index_path.exists():
        return []
    try:
        payload = read_json(index_path)
    except (OSError, ValueError, TypeError):
        return []
    filings = list(payload.get("filings") or [])
    tasks: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def add_task(filing: dict[str, Any], period: str) -> None:
        if len(tasks) >= limit:
            return
        body_path = _normalize_source_target(
            str(filing.get("body_path") or filing.get("local_body") or ""),
            sources_dir,
        )
        if not body_path or body_path in seen_paths:
            return
        seen_paths.add(body_path)
        tasks.append(
            {
                "id": f"filing_{len(tasks) + 1}",
                "type": "summarize_filing_body",
                "target": body_path,
                "focus": (
                    f"Extract P&L, cash, leverage, covenants, and going-concern language "
                    f"for {period} filing"
                ),
                "priority": 1 if period in {"annual", "interim"} else 2,
            }
        )

    for period in ("annual", "interim", "other"):
        for filing in filings:
            if str(filing.get("period") or "").lower() == period:
                add_task(filing, period)
    for filing in filings:
        if len(tasks) >= limit:
            break
        add_task(filing, str(filing.get("period") or "other"))
    return tasks[:limit]


def build_fallback_task_plan(
    *,
    report: CompanyReport,
    inventory: dict[str, Any],
    sources_dir: Path,
    max_tasks: int = DEFAULT_MAX_WORKER_TASKS,
) -> dict[str, Any]:
    """Rule-based task plan when director JSON is missing or invalid."""
    thin = list(inventory.get("thin") or [])
    open_questions = [
        f"Which evidence-ladder steps are thin locally ({', '.join(thin)})?"
        if thin
        else "Confirm filing coverage is sufficient for financial review."
    ]
    if report.interim_quality_overlay:
        open_questions.append(
            "Does interim-quality overlay weaken the strong-buy case after latest filing trends?"
        )

    tasks: list[dict[str, Any]] = []
    filing_tasks = _filing_body_tasks(sources_dir, limit=max(1, max_tasks - 2))
    tasks.extend(filing_tasks)

    available = dict(inventory.get("available") or {})
    if available.get("news_manifest") and len(tasks) < max_tasks:
        tasks.append(
            {
                "id": "news_digest",
                "type": "digest_news_manifest",
                "target": "news_manifest.json",
                "focus": "Material strategy, regulatory, and governance news in the past year",
                "priority": 2,
            }
        )
    if available.get("screening_snapshot") and len(tasks) < max_tasks:
        tasks.append(
            {
                "id": "screen_context",
                "type": "screen_context",
                "target": "screening_snapshot.json",
                "focus": "Models passed, composite score, timing, and overlay flags",
                "priority": 3,
            }
        )
    if thin and len(tasks) < max_tasks:
        tasks.append(
            {
                "id": "gap_inventory",
                "type": "gap_inventory",
                "target": "source_inventory",
                "focus": f"Document thin ladder steps: {', '.join(thin)}",
                "priority": 1,
            }
        )

    return {
        "schema_version": 1,
        "orchestration_version": ORCHESTRATION_VERSION,
        "source": "fallback_rules",
        "open_questions": open_questions,
        "procedural_suggestions": [],
        "tasks": tasks[:max_tasks],
    }


def _director_plan_prompt(
    *,
    report: CompanyReport,
    sources_dir: Path,
    inventory: dict[str, Any],
    max_tasks: int,
) -> str:
    signal_label = _screen_signal_label(report.signal)
    thin = ", ".join(inventory.get("thin") or []) or "(none)"
    ladder = ", ".join(EVIDENCE_LADDER)
    return f"""You are the **research director** for a director–worker trial on {report.name} ({report.ticker}).

The quantitative screen rates this name as a {signal_label}.
Sources directory (read inventory only — do NOT draft the final memo yet): {sources_dir.resolve()}
Evidence ladder order: {ladder}
Thin local steps: {thin}

Read ONLY:
- filings/filings_index.json (catalog; note annual vs interim)
- screening_snapshot.json if present
- news_manifest.json headline list if present
- financials_annual.json metadata if present

Your job:
1. List open qualitative questions for a verify-before-trade memo.
2. Propose up to {max_tasks} **worker tasks** for Composer agents (bounded reads only).
3. Suggest procedural improvements (ingest, prompt, source gaps) — do not implement them.

Return a single JSON object (no prose outside JSON) with this shape:
{{
  "schema_version": 1,
  "open_questions": ["..."],
  "procedural_suggestions": [{{"area": "ingest|prompt|sources", "summary": "..."}}],
  "tasks": [
    {{
      "id": "unique_id",
      "type": "summarize_filing_body|digest_news_manifest|screen_context|gap_inventory",
      "target": "relative path under sources/ or 'source_inventory'",
      "focus": "what the worker must extract",
      "priority": 1
    }}
  ]
}}

Rules:
- Prefer filing bodies over Yahoo for financial figures.
- Assign summarize_filing_body tasks for annual and interim bodies when present.
- Include gap_inventory when thin steps exist.
- Do not assign tasks that require inventing unavailable sources.
"""


def _worker_task_prompt(
    *,
    report: CompanyReport,
    sources_dir: Path,
    task: dict[str, Any],
) -> str:
    task_id = task.get("id") or "task"
    task_type = task.get("type") or "summarize_filing_body"
    target = task.get("target") or ""
    focus = task.get("focus") or ""
    target_path = sources_dir / target if target != "source_inventory" else sources_dir
    return f"""You are a **research worker** on {report.name} ({report.ticker}).

Task id: {task_id}
Task type: {task_type}
Focus: {focus}
Read only: {target_path.resolve()}

Extract facts from the assigned source. Do not write a full memo.
Return a single JSON object (no prose outside JSON):
{{
  "task_id": "{task_id}",
  "task_type": "{task_type}",
  "status": "completed|partial|failed",
  "findings": ["bullet findings with source path references"],
  "figures": [
    {{"metric": "...", "value": "...", "period": "...", "source_path": "...", "note": "..."}}
  ],
  "gaps": ["what remains unresolved in this source"],
  "sources_read": ["paths actually inspected"]
}}

Rules:
- Do not invent numbers; cite source_path for every figure.
- If data is missing, set status to partial and list gaps.
- UK English.
"""


def _director_synthesis_prompt(
    *,
    report: CompanyReport,
    task_plan: dict[str, Any],
    worker_results: list[dict[str, Any]],
    sources_dir: Path,
) -> str:
    signal_label = _screen_signal_label(report.signal)
    plan_json = json.dumps(task_plan, ensure_ascii=False, indent=2)
    results_json = json.dumps(worker_results, ensure_ascii=False, indent=2)
    return f"""You are the **research director** synthesising the final memo for {report.name} ({report.ticker}).

Screen signal: {signal_label}
Sources directory: {sources_dir.resolve()}

You have a task plan and structured worker outputs. Use worker JSON as primary evidence.
You may spot-check source files only to resolve conflicts — do not ignore worker gaps.

TASK PLAN:
{plan_json}

WORKER RESULTS:
{results_json}

Write the research memo with EXACTLY these plain-text section headings:

EXECUTIVE SUMMARY
INVESTMENT THESIS
FINANCIAL REVIEW
RISKS AND RED FLAGS
NEWS HIGHLIGHTS
RESEARCH VERDICT

FINANCIAL REVIEW must cite filing paths from worker figures/findings first.
RISKS must end with one RiskTags line:
RiskTags: regulatory | cyclical | governance | pension | competitive | liquidity | leverage | customer_concentration | key_person | litigation | accounting | other

RESEARCH VERDICT must use EXACTLY:
Verdict: accumulate | neutral | caution | pass
Risk: low | medium | high
Confidence: 0.00–1.00
Rationale: one sentence

Rules:
- UK English; no price targets.
- Prefer unresolved over false confidence when workers report gaps.
- Do not contradict worker figures without stating a conflict check.
"""


def normalize_task_plan(
    raw: dict[str, Any],
    *,
    max_tasks: int,
    sources_dir: Path | None = None,
) -> dict[str, Any]:
    tasks_in = list(raw.get("tasks") or [])
    tasks: list[dict[str, Any]] = []
    for idx, task in enumerate(tasks_in[:max_tasks], start=1):
        if not isinstance(task, dict):
            continue
        task_type = str(task.get("type") or "summarize_filing_body")
        if task_type not in VALID_TASK_TYPES:
            task_type = "summarize_filing_body"
        target_raw = str(task.get("target") or "")
        if sources_dir is not None and target_raw not in {"", "source_inventory"}:
            target = _normalize_source_target(target_raw, sources_dir)
        else:
            target = target_raw
        tasks.append(
            {
                "id": str(task.get("id") or f"task_{idx}"),
                "type": task_type,
                "target": target,
                "focus": str(task.get("focus") or ""),
                "priority": int(task.get("priority") or idx),
            }
        )
    return {
        "schema_version": 1,
        "orchestration_version": ORCHESTRATION_VERSION,
        "source": str(raw.get("source") or "director"),
        "open_questions": [str(q) for q in (raw.get("open_questions") or []) if str(q).strip()],
        "procedural_suggestions": list(raw.get("procedural_suggestions") or []),
        "tasks": tasks,
    }


def run_director_plan(
    *,
    report: CompanyReport,
    sources_dir: Path,
    inventory: dict[str, Any],
    api_key: str,
    director_model: str,
    cwd: str | None,
    max_tasks: int,
) -> tuple[dict[str, Any], str | None]:
    prompt = _director_plan_prompt(
        report=report,
        sources_dir=sources_dir,
        inventory=inventory,
        max_tasks=max_tasks,
    )
    text, agent_id = _run_agent_prompt(
        prompt=prompt,
        api_key=api_key,
        model=director_model,
        cwd=cwd,
    )
    try:
        raw = extract_json_object(text)
        plan = normalize_task_plan(raw, max_tasks=max_tasks, sources_dir=sources_dir)
        if not plan["tasks"]:
            raise ValueError("Director plan contained no tasks")
        plan["source"] = "director"
        return plan, agent_id
    except (ValueError, json.JSONDecodeError):
        fallback = build_fallback_task_plan(
            report=report,
            inventory=inventory,
            sources_dir=sources_dir,
            max_tasks=max_tasks,
        )
        fallback["director_parse_error"] = True
        fallback["director_raw_excerpt"] = text[:2000]
        return fallback, agent_id


def run_worker_task(
    *,
    report: CompanyReport,
    sources_dir: Path,
    task: dict[str, Any],
    api_key: str,
    worker_model: str,
    cwd: str | None,
) -> dict[str, Any]:
    prompt = _worker_task_prompt(report=report, sources_dir=sources_dir, task=task)
    text, agent_id = _run_agent_prompt(
        prompt=prompt,
        api_key=api_key,
        model=worker_model,
        cwd=cwd,
    )
    try:
        payload = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        payload = {
            "task_id": task.get("id"),
            "task_type": task.get("type"),
            "status": "failed",
            "findings": [],
            "figures": [],
            "gaps": ["Worker output was not valid JSON"],
            "sources_read": [],
            "raw_excerpt": text[:1500],
        }
    payload.setdefault("task_id", task.get("id"))
    payload.setdefault("task_type", task.get("type"))
    payload["worker_model"] = worker_model
    payload["worker_agent_id"] = agent_id
    return payload


def run_director_synthesis(
    *,
    report: CompanyReport,
    sources_dir: Path,
    task_plan: dict[str, Any],
    worker_results: list[dict[str, Any]],
    api_key: str,
    director_model: str,
    cwd: str | None,
) -> tuple[ResearchDocument, str | None]:
    prompt = _director_synthesis_prompt(
        report=report,
        task_plan=task_plan,
        worker_results=worker_results,
        sources_dir=sources_dir,
    )
    text, agent_id = _run_agent_prompt(
        prompt=prompt,
        api_key=api_key,
        model=director_model,
        cwd=cwd,
    )
    sections = parse_research_sections(text)
    verdict_fields = parse_research_verdict(sections.get("research_verdict", ""))
    risk_tags = parse_risk_tags(sections.get("risks_and_flags", "")) or parse_risk_tags(text)
    now = datetime.now(UTC).isoformat()
    doc = ResearchDocument(
        ticker=report.ticker,
        name=report.name,
        signal=report.signal,
        version=1,
        created_at=now,
        updated_at=now,
        mode="director_worker",
        executive_summary=sections["executive_summary"],
        investment_thesis=sections["investment_thesis"],
        financial_review=sections["financial_review"],
        risks_and_flags=sections["risks_and_flags"],
        news_highlights=sections["news_highlights"],
        research_verdict=verdict_fields["research_verdict"],  # type: ignore[arg-type]
        research_risk_level=verdict_fields["research_risk_level"],  # type: ignore[arg-type]
        research_confidence=verdict_fields["research_confidence"],  # type: ignore[arg-type]
        research_rationale=verdict_fields["research_rationale"],  # type: ignore[arg-type]
        risk_tags=risk_tags,
        agent_id=agent_id,
    )
    return doc, agent_id


def estimate_director_worker_cost_usd(
    *,
    worker_count: int,
    director_model: str,
    worker_model: str,
    memo_usd: float = 0.4,
) -> float:
    director_unit = estimate_model_memo_usd(director_model, baseline_usd=memo_usd)
    worker_unit = estimate_model_memo_usd(worker_model, baseline_usd=memo_usd)
    # Director plan is lighter than full memo; synthesis is similar to full memo.
    return round(director_unit * 0.6 + worker_unit * worker_count + director_unit, 2)


def run_director_worker_trial(
    *,
    report: CompanyReport,
    api_key: str,
    output_root: Path = DEFAULT_DW_OUTPUT_DIR,
    primary_output_dir: Path | None = None,
    director_model: str = DEFAULT_DIRECTOR_MODEL,
    worker_model: str = DEFAULT_WORKER_MODEL,
    cwd: str | None = None,
    market: str | None = None,
    max_worker_tasks: int = DEFAULT_MAX_WORKER_TASKS,
    memo_usd: float = 0.4,
    record_spend: bool = True,
    policy_path: Path | None = None,
) -> DirectorWorkerRun:
    """Run a single-ticker director–worker research trial."""
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root / report.ticker / run_id
    sources_dir = run_dir / "sources"
    workers_dir = run_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)

    primary_store = ResearchStore(primary_output_dir or Path("output"))
    inventory, source_counts = prepare_shared_research_sources(
        report=report,
        primary_store=primary_store,
        sources_dir=sources_dir,
        market=market,
    )
    write_json(run_dir / "source_inventory.json", inventory, compact=False)

    task_plan, plan_agent_id = run_director_plan(
        report=report,
        sources_dir=sources_dir,
        inventory=inventory,
        api_key=api_key,
        director_model=director_model,
        cwd=cwd,
        max_tasks=max_worker_tasks,
    )
    task_plan["director_agent_id"] = plan_agent_id
    write_json(run_dir / "director_plan.json", task_plan, compact=False)

    worker_results: list[dict[str, Any]] = []
    for task in task_plan.get("tasks") or []:
        result = run_worker_task(
            report=report,
            sources_dir=sources_dir,
            task=task,
            api_key=api_key,
            worker_model=worker_model,
            cwd=cwd,
        )
        worker_results.append(result)
        task_id = str(result.get("task_id") or task.get("id") or len(worker_results))
        write_json(workers_dir / f"{task_id}.json", result, compact=False)

    write_json(run_dir / "worker_results.json", worker_results, compact=False)

    document, synthesis_agent_id = run_director_synthesis(
        report=report,
        sources_dir=sources_dir,
        task_plan=task_plan,
        worker_results=worker_results,
        api_key=api_key,
        director_model=director_model,
        cwd=cwd,
    )
    document.source_counts = dict(source_counts)
    rubric = score_memo_rubric(document, inventory=inventory)
    source_quality = score_research_sources(
        source_counts=source_counts,
        inventory=inventory,
        question_outcomes=document.question_outcomes,
    )

    markdown_path = run_dir / "research.md"
    markdown_path.write_text(render_research_markdown(document), encoding="utf-8")
    write_json(run_dir / "research.json", document.to_dict(), compact=True)

    estimated = estimate_director_worker_cost_usd(
        worker_count=len(worker_results),
        director_model=director_model,
        worker_model=worker_model,
        memo_usd=memo_usd,
    )

    run = DirectorWorkerRun(
        ticker=report.ticker,
        company_name=report.name,
        signal=report.signal,
        run_id=run_id,
        output_dir=run_dir,
        director_model=director_model,
        worker_model=worker_model,
        task_plan=task_plan,
        worker_results=worker_results,
        document=document,
        rubric=rubric.to_dict(),
        estimated_cost_usd=estimated,
        director_agent_ids=(plan_agent_id, synthesis_agent_id),
    )
    write_json(run_dir / "manifest.json", run.to_dict(), compact=False)
    write_json(
        run_dir / "trial_summary.json",
        {
            "source_quality": source_quality,
            "rubric": rubric.to_dict(),
            "worker_count": len(worker_results),
        },
        compact=False,
    )

    if record_spend:
        record_estimated_spend(estimated, policy_path, pool=SPEND_POOL_AD_HOC)

    return run


def preview_director_worker_trial(
    *,
    report: CompanyReport,
    primary_output_dir: Path | None = None,
    market: str | None = None,
    max_worker_tasks: int = DEFAULT_MAX_WORKER_TASKS,
) -> dict[str, Any]:
    """Build fallback task plan from local inventory without calling agents."""
    run_dir = Path("/tmp") / "dw_preview" / report.ticker
    sources_dir = run_dir / "sources"
    primary_store = ResearchStore(primary_output_dir or Path("output"))
    inventory, _source_counts = prepare_shared_research_sources(
        report=report,
        primary_store=primary_store,
        sources_dir=sources_dir,
        market=market,
    )
    plan = build_fallback_task_plan(
        report=report,
        inventory=inventory,
        sources_dir=sources_dir,
        max_tasks=max_worker_tasks,
    )
    return {
        "ticker": report.ticker,
        "inventory": inventory,
        "task_plan": plan,
        "estimated_tasks": len(plan.get("tasks") or []),
    }


__all__ = [
    "DEFAULT_DIRECTOR_MODEL",
    "DEFAULT_DW_OUTPUT_DIR",
    "DEFAULT_MAX_WORKER_TASKS",
    "DEFAULT_WORKER_MODEL",
    "DirectorWorkerRun",
    "build_fallback_task_plan",
    "extract_json_object",
    "load_report_from_latest",
    "preview_director_worker_trial",
    "report_for_ticker",
    "run_director_worker_trial",
]
