"""Assemble north-star stage appraisal for the dashboard."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json

DEFAULT_PROGRESS_PATH = Path("docs/data/project_progress.json")
DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_OPS_PATH = Path("docs/data/ops_status.json")
DEFAULT_AUTOMATION_PATH = Path("docs/data/automation.json")
DEFAULT_AI_REVIEW_PATH = Path("docs/data/paper_automation/ai_judgment/decision_review.json")
DEFAULT_RULES_REVIEW_PATH = Path("docs/data/paper_automation/decision_review.json")
DEFAULT_INGEST_LOG_PATH = Path("docs/data/ingest_health_log.json")

STAGE_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "id": "0",
        "name": "UK quant core",
        "focus": "FTSE 350 screen, paper funds, post-open automation",
    },
    {
        "id": "1",
        "name": "Decision-review learning",
        "focus": "Book learns from outcomes after costs",
    },
    {
        "id": "2b",
        "name": "Primary learning track",
        "focus": "AI-judgment paper book vs ^FTSE and rules control",
    },
    {
        "id": "3",
        "name": "Library-ready global data",
        "focus": "Offline multi-market fundamentals without live screen impact",
    },
    {
        "id": "4",
        "name": "Controlled universe expansion",
        "focus": "First non-UK live screen at FTSE quality bar",
    },
    {
        "id": "5",
        "name": "Self-improving automation",
        "focus": "Walk-forward rule evolution with frozen signals",
    },
)


def _safe_read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except (OSError, ValueError, TypeError):
        return None


def _stage_status(stage_id: str, evidence: dict[str, Any]) -> str:
    if stage_id == "0":
        return "complete" if evidence.get("screen_company_count", 0) >= 200 else "in_progress"
    if stage_id == "1":
        return "complete" if evidence.get("decision_review_applied") else "in_progress"
    if stage_id == "2b":
        if evidence.get("ai_excess_after_costs") is None:
            return "in_progress"
        return "in_progress" if evidence.get("ai_excess_after_costs", 0) < 0 else "complete"
    if stage_id == "3":
        graduated = evidence.get("library_graduated_count", 0)
        return "complete" if graduated >= 10 else "in_progress"
    if stage_id in {"4", "5"}:
        return "not_started"
    return "in_progress"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.1f}%"


def build_project_progress(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    automation_path: Path = DEFAULT_AUTOMATION_PATH,
    ops_path: Path = DEFAULT_OPS_PATH,
    ai_review_path: Path = DEFAULT_AI_REVIEW_PATH,
    rules_review_path: Path = DEFAULT_RULES_REVIEW_PATH,
    ingest_log_path: Path = DEFAULT_INGEST_LOG_PATH,
) -> dict[str, Any]:
    latest = _safe_read(latest_path) or {}
    automation = _safe_read(automation_path) or {}
    ops = _safe_read(ops_path) or {}
    ai_review = _safe_read(ai_review_path) or {}
    rules_review = _safe_read(rules_review_path) or {}
    ingest_log = _safe_read(ingest_log_path) or {}

    meta = latest.get("meta") or {}
    library = (automation.get("settings") or {}).get("library") or {}
    ai_metrics = ai_review.get("metrics") or {}
    rules_metrics = rules_review.get("metrics") or {}

    ingest_entries = list(ingest_log.get("entries") or [])
    latest_ingest = ingest_entries[-1] if ingest_entries else {}
    health_after = latest_ingest.get("health_after") or {}

    if not health_after:
        from value_investor.engineering_queue import snapshot_ingest_health

        health_after = snapshot_ingest_health(latest_path=latest_path)

    evidence = {
        "screen_company_count": int(meta.get("company_count") or 0),
        "strong_buy_count": int(meta.get("strong_buy_count") or 0),
        "screen_run_at": latest.get("run_at"),
        "library_graduated_count": int(library.get("graduated_count") or len(library.get("graduated_markets") or [])),
        "library_focus_market": library.get("focus_market"),
        "decision_review_applied": bool(ai_review.get("applied") or rules_review.get("applied")),
        "ai_excess_after_costs": ai_metrics.get("excess_after_costs"),
        "rules_excess_after_costs": rules_metrics.get("excess_after_costs"),
        "ai_total_return": ai_metrics.get("total_return"),
        "rules_total_return": rules_metrics.get("total_return"),
        "ops_overall": ops.get("overall"),
        "zero_body_buy_tier": health_after.get("zero_body_buy_tier"),
        "unmeasured_buy_tier": health_after.get("unmeasured_buy_tier"),
        "measured_tickers": health_after.get("measured_tickers"),
        "buy_tier_count": health_after.get("buy_tier_count"),
        "ingest_stalled": bool(
            int(health_after.get("zero_body_buy_tier") or 0) > 0
            and int(latest_ingest.get("delta_zero_body") or 0) == 0
        ),
    }

    stages = []
    for stage in STAGE_DEFINITIONS:
        status = _stage_status(stage["id"], evidence)
        stages.append({**stage, "status": status})

    ai_excess = evidence.get("ai_excess_after_costs")
    rules_excess = evidence.get("rules_excess_after_costs")
    strengths = [
        "FTSE 350 live screen and published dashboard are operational.",
        f"Offline library: {evidence['library_graduated_count']} graduated markets (focus: {evidence['library_focus_market'] or '—'}).",
        "Ops automation in place: daily monitor, tier-1 backup, external cron scheduling.",
        "Engineering queue self-repair and 11 merged supervised tasks.",
    ]
    if ai_excess is not None and rules_excess is not None and ai_excess > rules_excess:
        strengths.append(
            f"AI-judgment track beating rules control ({_fmt_pct(ai_excess)} vs {_fmt_pct(rules_excess)} excess)."
        )

    gaps = []
    if ai_excess is not None and ai_excess < 0:
        gaps.append(
            f"Primary AI track still below ^FTSE after costs ({_fmt_pct(ai_excess)} excess; history still thin)."
        )
    if int(evidence.get("unmeasured_buy_tier") or 0) > 0:
        gaps.append(
            f"Ingest coverage gap: {evidence['unmeasured_buy_tier']} buy-tier tickers have no filings index yet."
        )
    if evidence.get("ingest_stalled"):
        gaps.append(
            f"Ingest bottleneck: zero_body_buy_tier stuck at {evidence.get('zero_body_buy_tier')}."
        )
    if evidence.get("screen_run_at"):
        gaps.append(f"Published screen bundle dated {evidence['screen_run_at'][:10]} — confirm Sunday refresh.")

    next_actions = [
        "Let the learning loop accumulate before adding tracks or knobs.",
        "Sunday chain: orchestrator → analysis-review → data-backup (cron now wired).",
        "Prioritise buy-tier filing depth (Companies House + RNS body fetch).",
        "Keep library growing offline; defer live universe expansion until stage 2b shows edge.",
    ]

    ingest_bottleneck = {
        "stalled": evidence.get("ingest_stalled", False),
        "zero_body_buy_tier": evidence.get("zero_body_buy_tier"),
        "health": health_after,
        "summary": (
            "Live buy-tier ingest now canonicalises under docs/data/research/, bootstraps "
            "missing indexes on Sunday/weekday passes, and sanitises mis-attributed RNS rows "
            "before refetching bodies."
        ),
        "fixes": [
            "Canonical path + library migration (implemented).",
            "Sunday bootstrap seeds strong_buy indexes when missing (capped).",
            "Misattribution filter + headline reclassify at pass start (implemented).",
            "Raise weekday caps and run ingest after Sunday screen (implemented).",
            "Targeted BREE.L ingest suggestions for engineering micro-compile.",
        ],
        "commands": [
            "ftse-ingest-loop status --json",
            "ftse-ingest-loop run --max-targets 10 --json",
            "gh workflow run ingest-loop.yml -f force=true -f max_targets=15",
        ],
    }

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "current_focus": "stage_2b",
        "headline": (
            "Infrastructure and offline library are ahead of schedule; "
            "the primary AI learning track is running but not yet beating the market."
        ),
        "stages": stages,
        "evidence": evidence,
        "appraisal": {
            "strengths": strengths,
            "gaps": gaps,
            "next_actions": next_actions,
        },
        "ingest_bottleneck": ingest_bottleneck,
    }


def write_project_progress(
    path: Path = DEFAULT_PROGRESS_PATH,
    **kwargs: Any,
) -> dict[str, Any]:
    payload = build_project_progress(**kwargs)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    from value_investor.storage import write_json

    write_json(path, payload, compact=False)
    return payload
