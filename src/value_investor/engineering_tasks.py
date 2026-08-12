"""Compile and manage supervised engineering tasks from weekly run artifacts."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.post_run_review import _parse_post_run_review
from value_investor.research.gap_fill import DEFAULT_SUGGESTIONS_PATH
from value_investor.research.ingest_improvement import (
    map_suggestion_to_source_ids,
)
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_TASKS_PATH = Path("output/engineering_tasks.json")
COMMITTED_TASKS_PATH = Path("docs/data/engineering_tasks.json")
DEFAULT_MAX_COMPILE_TASKS = 8
DEFAULT_MAX_RUN_TASKS = 1
DEFAULT_MIN_METRICS_FOR_SCREEN = 25
TERMINAL_TASK_STATUSES = frozenset({"merged", "completed", "failed", "cancelled", "parked"})

BLOCKED_PATHS = (
    "src/value_investor/paper_fund.py",
    "src/value_investor/simulator.py",
    "src/value_investor/paper_automation_cli.py",
    ".github/workflows/paper-auto.yml",
    "docs/data/library/policy.json",
)

AREA_ALLOWED_PATHS: dict[str, list[str]] = {
    "ingest": [
        "src/value_investor/research/filings.py",
        "src/value_investor/research/gap_fill_sources.py",
        "src/value_investor/research/ingest.py",
        "src/value_investor/research/ingest_improvement.py",
        "src/value_investor/research/companies_house.py",
        "src/value_investor/companies_house.py",
        "tests/test_research_filings.py",
        "tests/test_gap_fill_deepen.py",
        "tests/test_ingest_improvement.py",
    ],
    "scoring": [
        "src/value_investor/pipeline.py",
        "src/value_investor/summary.py",
        "src/value_investor/models/",
        "src/value_investor/scoring/",
        "tests/test_pipeline.py",
        "tests/test_summary.py",
    ],
    "prompt": [
        "src/value_investor/research/agent.py",
        "src/value_investor/deep_analysis.py",
        "src/value_investor/research/gap_fill.py",
        "tests/test_deep_analysis.py",
        "tests/test_research_gap_fill.py",
    ],
    "coverage": [
        "src/value_investor/publish.py",
        "src/value_investor/emailer.py",
        "src/value_investor/research/ingest.py",
        "tests/test_publish.py",
    ],
    "ops": [
        "src/value_investor/automation_status.py",
        "src/value_investor/email_agent.py",
        "src/value_investor/ops_monitor.py",
        "src/value_investor/backtest_health.py",
        "src/value_investor/engineering_recovery.py",
        "src/value_investor/engineering_sync.py",
        "src/value_investor/engineering_pr_notify.py",
        ".github/workflows/ops-monitor.yml",
        ".github/workflows/engineering-agent.yml",
        ".github/workflows/engineering-queue.yml",
        "tests/test_automation_status.py",
        "tests/test_ops_monitor.py",
        "tests/test_backtest_health.py",
        "tests/test_engineering_sync.py",
        "tests/test_engineering_pr_notify.py",
    ],
    "ci": [
        ".github/workflows/ci.yml",
        ".github/workflows/ci-main-nightly.yml",
        ".github/workflows/ci-fix-responder.yml",
        ".github/workflows/engineering-auto-merge.yml",
        "scripts/check_committed_data_json.py",
        "scripts/check_changed_python.py",
        "src/value_investor/committed_data_json.py",
        "src/value_investor/python_quality.py",
        "src/value_investor/ci_fix_tasks.py",
        "src/value_investor/engineering_auto_merge.py",
        "tests/conftest.py",
        "tests/test_committed_data_json.py",
        "tests/test_python_quality.py",
        "tests/test_ci_fix_tasks.py",
        "tests/test_engineering_auto_merge.py",
        "pyproject.toml",
    ],
}

LIBRARY_METRICS_ALLOWED_PATHS = [
    "src/value_investor/providers.py",
    "src/value_investor/fetch.py",
    "src/value_investor/data_library.py",
    "src/value_investor/financials.py",
    "src/value_investor/library_screen.py",
    "tests/test_providers.py",
    "tests/test_data_library.py",
    "tests/test_constituents_fetch.py",
    "tests/test_library_screen.py",
]

_CODE_KEYWORDS = (
    "implement",
    "pipeline",
    "populate",
    "parser",
    "ixbrl",
    "universal",
    "replace google",
    "export ",
    "persist ",
    "overlay",
    "classification override",
    "allowlist",
    "structured extract",
    "field population",
    "headline-pattern",
    "reclassification",
    "dual-source",
)

_TICKER_RE = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b")
_PLAN_LINE = re.compile(
    r"^\s*(?P<index>\d+)\.\s*\*\*\[(?P<area>[^\]]+)\]\s*(?P<title>.+)$",
    re.IGNORECASE,
)


@dataclass
class EngineeringTask:
    id: str
    area: str
    title: str
    summary: str
    priority: str
    priority_score: float
    source: str
    evidence: dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    blocked_paths: list[str] = field(default_factory=list)
    auto_merge: bool = False
    status: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "area": self.area,
            "title": self.title,
            "summary": self.summary,
            "priority": self.priority,
            "priority_score": self.priority_score,
            "source": self.source,
            "evidence": self.evidence,
            "acceptance_criteria": self.acceptance_criteria,
            "allowed_paths": self.allowed_paths,
            "blocked_paths": self.blocked_paths,
            "auto_merge": self.auto_merge,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EngineeringTask:
        return cls(
            id=str(data["id"]),
            area=str(data.get("area") or "research"),
            title=str(data.get("title") or ""),
            summary=str(data.get("summary") or ""),
            priority=str(data.get("priority") or "medium"),
            priority_score=float(data.get("priority_score") or 0.0),
            source=str(data.get("source") or ""),
            evidence=dict(data.get("evidence") or {}),
            acceptance_criteria=list(data.get("acceptance_criteria") or []),
            allowed_paths=list(data.get("allowed_paths") or []),
            blocked_paths=list(data.get("blocked_paths") or BLOCKED_PATHS),
            auto_merge=bool(data.get("auto_merge")),
            status=str(data.get("status") or "open"),
        )


def _normalize_area(area: str) -> str:
    value = str(area or "").strip().lower()
    if value in AREA_ALLOWED_PATHS:
        return value
    if value in {"research", "model"}:
        return "prompt"
    return value if value in AREA_ALLOWED_PATHS else "ingest"


def needs_engineering_implementation(
    *,
    area: str,
    suggestion: str,
    source_ids: list[str] | None = None,
) -> bool:
    """Return True when a suggestion needs code changes, not ingest retry only."""
    normalized = _normalize_area(area)
    text = str(suggestion or "").lower()
    if normalized in {"scoring", "prompt", "coverage", "ops", "ci"}:
        return True
    if normalized != "ingest":
        return False
    if any(keyword in text for keyword in _CODE_KEYWORDS):
        return True
    mapped = source_ids if source_ids is not None else map_suggestion_to_source_ids(suggestion)
    if mapped and not any(keyword in text for keyword in _CODE_KEYWORDS):
        return False
    return True


def _extract_tickers(*chunks: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        for match in _TICKER_RE.findall(chunk or ""):
            token = match.upper()
            if token in seen:
                continue
            seen.add(token)
            found.append(token)
    return found


def _allowed_paths_for_area(area: str) -> list[str]:
    normalized = _normalize_area(area)
    paths = list(AREA_ALLOWED_PATHS.get(normalized) or AREA_ALLOWED_PATHS["ingest"])
    return paths


def _default_acceptance_criteria(area: str, tickers: list[str]) -> list[str]:
    normalized = _normalize_area(area)
    ticker_note = f" for {tickers[0]}" if tickers else ""
    if normalized == "ingest":
        return [
            f"Add or extend fetch logic with a focused regression test{ticker_note}",
            "Do not change live signal thresholds or paper-fund behaviour",
            "Existing ingest-improvement pass can fetch new bodies on the next dry run",
        ]
    if normalized == "scoring":
        return [
            "Export or overlay behaviour is covered by a unit test",
            "Strong-buy confirmation logic remains backward compatible unless task says otherwise",
            "No edits under blocked_paths",
        ]
    if normalized == "ci":
        return [
            "Fix the failing pytest module(s) with minimal diff",
            "Run the relevant pytest subset locally before finishing",
            "Diff stays within allowed_paths and does not touch blocked_paths",
        ]
    return [
        "Prompt or export change is covered by a parser/unit test",
        "No edits under blocked_paths",
    ]


def _task_from_plan_line(
    *,
    index: int,
    area: str,
    title: str,
    run_stamp: str,
    seq: int,
) -> EngineeringTask | None:
    clean_title = re.sub(r"\s*—\s*expected impact:.*$", "", title, flags=re.IGNORECASE).strip()
    clean_title = clean_title.strip("* ").strip()
    if not clean_title:
        return None
    normalized = _normalize_area(area)
    if not needs_engineering_implementation(area=normalized, suggestion=clean_title):
        return None
    tickers = _extract_tickers(clean_title)
    priority_score = 100.0 - float(index)
    if normalized == "scoring":
        priority_score += 2.0
    return EngineeringTask(
        id=f"eng-{run_stamp}-{seq:02d}",
        area=normalized,
        title=clean_title[:160],
        summary=clean_title,
        priority="high",
        priority_score=priority_score,
        source="post_run_review",
        evidence={"tickers": tickers, "plan_index": index},
        acceptance_criteria=_default_acceptance_criteria(normalized, tickers),
        allowed_paths=_allowed_paths_for_area(normalized),
        blocked_paths=list(BLOCKED_PATHS),
    )


def _parse_post_run_plan(post_run_path: Path) -> list[EngineeringTask]:
    if not post_run_path.exists():
        return []
    review = _parse_post_run_review(post_run_path.read_text(encoding="utf-8"))
    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    tasks: list[EngineeringTask] = []
    seq = 1
    for line in review.improvement_plan.splitlines():
        match = _PLAN_LINE.match(line.strip())
        if not match:
            continue
        raw_title = match.group("title").strip().strip("*").strip()
        task = _task_from_plan_line(
            index=int(match.group("index")),
            area=match.group("area"),
            title=raw_title,
            run_stamp=run_stamp,
            seq=seq,
        )
        if task is None:
            continue
        tasks.append(task)
        seq += 1
    return tasks


def _tasks_from_suggestions(
    suggestions_path: Path,
    *,
    run_stamp: str,
    seq_start: int,
) -> list[EngineeringTask]:
    if not suggestions_path.exists():
        return []
    try:
        payload = read_json(suggestions_path)
    except (OSError, ValueError, TypeError):
        return []
    tasks: list[EngineeringTask] = []
    seq = seq_start
    for row in payload.get("suggestions") or []:
        area = _normalize_area(str(row.get("area") or ""))
        if area not in {"ingest", "scoring", "prompt", "coverage", "ops"}:
            continue
        suggestion = str(row.get("suggestion") or "").strip()
        if not suggestion or suggestion == "--":
            continue
        if not needs_engineering_implementation(area=area, suggestion=suggestion):
            continue
        priority = str(row.get("priority") or "medium").lower()
        score = {"high": 40.0, "medium": 20.0, "low": 5.0}.get(priority, 20.0)
        if area == "scoring":
            score += 3.0
        ticker = str(row.get("ticker") or "").strip().upper()
        tickers = [ticker] if ticker else _extract_tickers(suggestion)
        tasks.append(
            EngineeringTask(
                id=f"eng-{run_stamp}-{seq:02d}",
                area=area,
                title=suggestion[:160],
                summary=suggestion,
                priority=priority,
                priority_score=score,
                source="research_model_suggestions",
                evidence={
                    "tickers": tickers,
                    "recorded_at": row.get("recorded_at"),
                },
                acceptance_criteria=_default_acceptance_criteria(area, tickers),
                allowed_paths=_allowed_paths_for_area(area),
                blocked_paths=list(BLOCKED_PATHS),
            )
        )
        seq += 1
    return tasks


def _tasks_from_gap_fill(
    gap_fill_path: Path, *, run_stamp: str, seq_start: int
) -> list[EngineeringTask]:
    if not gap_fill_path.exists():
        return []
    try:
        payload = read_json(gap_fill_path)
    except (OSError, ValueError, TypeError):
        return []
    tasks: list[EngineeringTask] = []
    seq = seq_start
    for row in payload.get("fetch_attempts") or []:
        fetched = int(row.get("fetched") or 0)
        attempted = int(row.get("attempted") or 0)
        if attempted <= 0 or fetched > 0:
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        title = (
            f"Investigate zero-yield filing refetch for {ticker} "
            f"({fetched}/{attempted} bodies fetched)"
        )
        tasks.append(
            EngineeringTask(
                id=f"eng-{run_stamp}-{seq:02d}",
                area="ingest",
                title=title,
                summary=title,
                priority="medium",
                priority_score=25.0,
                source="gap_fill_summary",
                evidence={"tickers": [ticker], "fetch_attempt": row},
                acceptance_criteria=_default_acceptance_criteria("ingest", [ticker]),
                allowed_paths=_allowed_paths_for_area("ingest"),
                blocked_paths=list(BLOCKED_PATHS),
            )
        )
        seq += 1
    return tasks


def task_title_key(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip().lower())[:120]


def _title_keys_match(left: str, right: str) -> bool:
    a = task_title_key(left)
    b = task_title_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return longer.startswith(shorter) or shorter in longer


def _merge_task_rows(
    existing_rows: list[dict[str, Any]],
    compiled_tasks: list[EngineeringTask],
) -> list[dict[str, Any]]:
    """Preserve lifecycle fields for tasks that already ran or merged."""
    by_title = {task_title_key(str(row.get("title") or "")): row for row in existing_rows}
    by_id = {str(row.get("id") or ""): row for row in existing_rows}
    merged: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    matched_ids: set[str] = set()

    def _find_prior(task: EngineeringTask) -> dict[str, Any] | None:
        direct = by_title.get(task_title_key(task.title)) or by_id.get(task.id)
        if direct is not None:
            return direct
        for row in existing_rows:
            if _title_keys_match(str(row.get("title") or ""), task.title):
                return row
        return None

    for task in compiled_tasks:
        key = task_title_key(task.title)
        seen_titles.add(key)
        prior = _find_prior(task)
        row = task.to_dict()
        if prior is not None:
            matched_ids.add(str(prior.get("id") or ""))
            prior_status = str(prior.get("status") or "open")
            if prior_status != "open":
                row["status"] = prior_status
            for field in (
                "result_path",
                "branch_name",
                "pr_url",
                "pr_number",
                "completed_at",
                "merged_at",
            ):
                if prior.get(field) is not None:
                    row[field] = prior[field]
            if prior_status != "open" and prior.get("id"):
                row["id"] = prior["id"]
        merged.append(row)

    for row in existing_rows:
        if str(row.get("id") or "") in matched_ids:
            continue
        key = task_title_key(str(row.get("title") or ""))
        if key in seen_titles:
            continue
        status = str(row.get("status") or "open")
        if status in TERMINAL_TASK_STATUSES or status in {"pr_open", "open"}:
            merged.append(row)
    merged.sort(key=lambda row: -float(row.get("priority_score") or 0.0))
    return merged


def open_task_ids_dropped_by_merge(
    existing_rows: list[dict[str, Any]],
    compiled_tasks: list[EngineeringTask],
) -> list[str]:
    """Return open task ids that would disappear after a compile merge."""
    before = {
        str(row.get("id") or "")
        for row in existing_rows
        if str(row.get("status") or "open") == "open" and str(row.get("id") or "")
    }
    merged = _merge_task_rows(existing_rows, compiled_tasks)
    after = {
        str(row.get("id") or "")
        for row in merged
        if str(row.get("status") or "open") == "open" and str(row.get("id") or "")
    }
    return sorted(before - after)


def build_compiled_task_list(
    *,
    output_dir: Path,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    max_tasks: int = DEFAULT_MAX_COMPILE_TASKS,
) -> list[EngineeringTask]:
    """Build compiled tasks from run artifacts without writing queue files."""
    output_dir = Path(output_dir)
    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    tasks: list[EngineeringTask] = []
    tasks.extend(_parse_post_run_plan(output_dir / "post_run_review.md"))
    seq = len(tasks) + 1
    tasks.extend(_tasks_from_suggestions(suggestions_path, run_stamp=run_stamp, seq_start=seq))
    seq = len(tasks) + 1
    tasks.extend(
        _tasks_from_gap_fill(
            output_dir / "gap_fill_summary.json", run_stamp=run_stamp, seq_start=seq
        )
    )
    return _dedupe_tasks(tasks)[: max(0, int(max_tasks))]


def sync_committed_engineering_tasks(
    *,
    output_path: Path = DEFAULT_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
) -> dict[str, Any] | None:
    """Merge output queue into committed path without clobbering lifecycle fields."""
    output_path = Path(output_path)
    committed_path = Path(committed_path)
    if not output_path.exists():
        return load_engineering_tasks(committed_path) if committed_path.exists() else None

    output_payload = load_engineering_tasks(output_path)
    committed_payload = (
        load_engineering_tasks(committed_path) if committed_path.exists() else {"tasks": []}
    )
    merged_rows = _merge_task_rows(
        list(committed_payload.get("tasks") or []),
        [EngineeringTask.from_dict(row) for row in output_payload.get("tasks") or []],
    )
    payload = {
        **committed_payload,
        **{k: v for k, v in output_payload.items() if k != "tasks"},
        "tasks": merged_rows,
        "task_count": len(merged_rows),
    }
    committed_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(committed_path, payload, compact=False)
    return payload


def _dedupe_tasks(tasks: list[EngineeringTask]) -> list[EngineeringTask]:
    seen: set[str] = set()
    unique: list[EngineeringTask] = []
    for task in sorted(tasks, key=lambda row: -row.priority_score):
        key = re.sub(r"\s+", " ", task.title.lower())[:120]
        if key in seen:
            continue
        seen.add(key)
        unique.append(task)
    return unique


def compile_engineering_tasks(
    *,
    output_dir: Path,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    max_tasks: int = DEFAULT_MAX_COMPILE_TASKS,
    tasks_path: Path = DEFAULT_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
) -> dict[str, Any]:
    """Build a supervised engineering queue from Sunday run artifacts."""
    output_dir = Path(output_dir)
    tasks = build_compiled_task_list(
        output_dir=output_dir,
        suggestions_path=suggestions_path,
        max_tasks=max_tasks,
    )

    existing_rows: list[dict[str, Any]] = []
    for candidate in (committed_path, tasks_path):
        if Path(candidate).exists():
            existing_rows = list(load_engineering_tasks(candidate).get("tasks") or [])
            if existing_rows:
                break

    before_ids = {str(row.get("id") or "") for row in existing_rows if row.get("id")}

    merged_rows = _merge_task_rows(existing_rows, tasks)
    added_open_ids = [
        str(row.get("id") or "")
        for row in merged_rows
        if str(row.get("id") or "") not in before_ids and str(row.get("status") or "open") == "open"
    ]
    from value_investor.engineering_queue import snapshot_ingest_health

    ingest_health = snapshot_ingest_health()
    payload = {
        "compiled_at": datetime.now(UTC).isoformat(),
        "run_at": _read_run_at(output_dir),
        "task_count": len(merged_rows),
        "tasks": merged_rows,
        "ingest_health": ingest_health,
    }
    tasks_path = Path(tasks_path)
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(tasks_path, payload, compact=False)
    committed_path = Path(committed_path)
    committed_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(committed_path, payload, compact=False)
    try:
        from value_investor.engineering_queue import refresh_engineering_queue_ui

        refresh_engineering_queue_ui(tasks_path=committed_path)
    except OSError:
        pass
    payload["added_open_task_ids"] = added_open_ids
    payload["added_open_count"] = len(added_open_ids)
    return payload


def compile_ingest_engineering_tasks_micro(
    *,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    max_tasks: int = 3,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
    latest_path: Path = Path("docs/data/latest.json"),
) -> dict[str, Any]:
    """Append ingest-only engineering tasks when weekday ingest health stalls."""
    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    existing_payload = load_engineering_tasks(committed_path)
    existing_rows = list(existing_payload.get("tasks") or [])
    if any(
        str(row.get("area") or "").lower() == "ingest"
        and str(row.get("status") or "open") in {"open", "pr_open"}
        for row in existing_rows
    ):
        return {"compiled_count": 0, "reason": "open ingest engineering task already queued"}

    prefix = f"eng-{run_stamp}-"
    used_seq = [
        int(str(row.get("id") or "").removeprefix(prefix))
        for row in existing_rows
        if str(row.get("id") or "").startswith(prefix)
        and str(row.get("id") or "").removeprefix(prefix).isdigit()
    ]
    seq_start = max(used_seq, default=0) + 1
    compiled = [
        task
        for task in _tasks_from_suggestions(
            suggestions_path,
            run_stamp=run_stamp,
            seq_start=seq_start,
        )
        if task.area == "ingest"
    ]
    compiled = sorted(compiled, key=lambda row: -row.priority_score)[: max(0, int(max_tasks))]
    if not compiled:
        return {"compiled_count": 0, "reason": "no ingest suggestions eligible"}

    merged_rows = _merge_task_rows(existing_rows, compiled)
    open_ids_before = {
        str(row.get("id") or "")
        for row in existing_rows
        if str(row.get("status") or "open") == "open"
    }
    newly_open = [
        row
        for row in merged_rows
        if str(row.get("status") or "open") == "open"
        and str(row.get("id") or "") not in open_ids_before
    ]
    from value_investor.engineering_queue import snapshot_ingest_health

    ingest_health = snapshot_ingest_health(latest_path=latest_path)
    payload = {
        **existing_payload,
        "compiled_at": datetime.now(UTC).isoformat(),
        "task_count": len(merged_rows),
        "tasks": merged_rows,
        "ingest_health": ingest_health,
        "micro_compile_source": "weekday_ingest_loop",
    }
    committed_path = Path(committed_path)
    tasks_path = Path(tasks_path)
    committed_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(committed_path, payload, compact=False)
    if tasks_path != committed_path:
        write_json(tasks_path, payload, compact=False)
    return {
        "compiled_count": len(newly_open),
        "task_ids": [str(row.get("id") or "") for row in newly_open],
        "task_count": len(merged_rows),
    }


def compile_ingest_engineering_task_from_trial(
    trial: dict[str, Any],
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
    data_dir: Path = Path("docs/data"),
) -> dict[str, Any]:
    """Queue a scoped ingest engineering task when a gap trial fails to fetch bodies."""
    from value_investor.ingest_gap_closure import (
        DEFAULT_RUNS_PATH,
        MAX_GAP_CLOSURE_CHAIN_ROUNDS,
        gap_closure_chain_root_id,
        gap_closure_refetch_stats,
        should_auto_compile_gap_engineering,
    )

    chain_root = gap_closure_chain_root_id(trial)
    should_compile, compile_reason = should_auto_compile_gap_engineering(
        trial,
        data_dir=data_dir,
        tasks_path=committed_path,
        runs_path=DEFAULT_RUNS_PATH,
    )
    if not should_compile:
        return {"compiled_count": 0, "reason": compile_reason}

    run_id = str(trial.get("id") or "")
    ticker = str(trial.get("ticker") or "").strip().upper()
    existing_payload = load_engineering_tasks(committed_path)
    existing_rows = list(existing_payload.get("tasks") or [])
    for row in existing_rows:
        evidence = row.get("evidence") or {}
        linked = str(evidence.get("gap_closure_run_id") or evidence.get("trial_id") or "")
        if linked == run_id:
            status = str(row.get("status") or "open")
            if status in {"open", "pr_open"}:
                return {
                    "compiled_count": 0,
                    "reason": "engineering task already queued for gap-closure run",
                    "task_id": row.get("id"),
                }

    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    seq = _next_engineering_seq_from_rows(existing_rows, run_stamp)
    stats = gap_closure_refetch_stats(trial)
    chain_round = (
        sum(
            1
            for row in existing_rows
            if str(row.get("source") or "") in {"ingest_gap_closure", "ingest_trial"}
            and str((row.get("evidence") or {}).get("chain_root_id") or "") == chain_root
            and str(row.get("status") or "open") not in {"cancelled", "failed", "parked"}
        )
        + 1
    )
    title = (
        f"Close stubborn ingest gaps for {ticker} "
        f"(chain {chain_round}/{MAX_GAP_CLOSURE_CHAIN_ROUNDS}: "
        f"{stats['fetched']}/{stats['attempted']} bodies, run {run_id})"
    )
    task = EngineeringTask(
        id=f"eng-{run_stamp}-{seq:02d}",
        area="ingest",
        title=title,
        summary=(
            f"Ingest gap-closure run {run_id} (chain root {chain_root}, round {chain_round}) targeted "
            f"{ticker} with outstanding indexed gaps after refetch yield "
            f"{stats['fetched']}/{stats['attempted']}. Investigate source mapping, URL "
            "resolution, or parser gaps; add a focused fix and regression test so the "
            "next pinned verification run closes the gap."
        ),
        priority="high",
        priority_score=88.0,
        source="ingest_gap_closure",
        evidence={
            "gap_closure_run_id": run_id,
            "trial_id": run_id,
            "chain_root_id": chain_root,
            "chain_round": chain_round,
            "tickers": [ticker],
            "ticker": ticker,
            "rerun_ingest_gap_closure": True,
            "rerun_ingest_trial": True,
            "refetch_attempted": stats["attempted"],
            "refetch_fetched": stats["fetched"],
            "gap_closure_params": dict(trial.get("params") or {}),
            "trial_params": dict(trial.get("params") or {}),
            "compile_reason": compile_reason,
        },
        acceptance_criteria=_default_acceptance_criteria("ingest", [ticker]),
        allowed_paths=_allowed_paths_for_area("ingest"),
        blocked_paths=list(BLOCKED_PATHS),
    )
    merged_rows = _merge_task_rows(existing_rows, [task])
    open_ids_before = {
        str(row.get("id") or "")
        for row in existing_rows
        if str(row.get("status") or "open") == "open"
    }
    newly_open = [
        row
        for row in merged_rows
        if str(row.get("status") or "open") == "open"
        and str(row.get("id") or "") not in open_ids_before
    ]
    payload = {
        **existing_payload,
        "compiled_at": datetime.now(UTC).isoformat(),
        "task_count": len(merged_rows),
        "tasks": merged_rows,
        "micro_compile_source": "ingest_gap_closure",
        "source_gap_closure_run_id": run_id,
        "source_trial_id": run_id,
        "source_chain_root_id": chain_root,
    }
    committed_path = Path(committed_path)
    tasks_path = Path(tasks_path)
    committed_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(committed_path, payload, compact=False)
    if tasks_path != committed_path:
        write_json(tasks_path, payload, compact=False)
    try:
        from value_investor.engineering_queue import refresh_engineering_queue_ui

        refresh_engineering_queue_ui(tasks_path=committed_path)
    except OSError:
        pass
    if newly_open:
        from value_investor.ingest_gap_closure import attach_engineering_task_to_run

        attach_engineering_task_to_run(run_id, str(newly_open[0].get("id") or ""))
    return {
        "compiled_count": len(newly_open),
        "task_ids": [str(row.get("id") or "") for row in newly_open],
        "task_count": len(merged_rows),
        "gap_closure_run_id": run_id,
        "trial_id": run_id,
        "ticker": ticker,
    }


def _next_engineering_seq_from_rows(existing_rows: list[dict[str, Any]], run_stamp: str) -> int:
    prefix = f"eng-{run_stamp}-"
    used = [
        int(str(row.get("id") or "").removeprefix(prefix))
        for row in existing_rows
        if str(row.get("id") or "").startswith(prefix)
        and str(row.get("id") or "").removeprefix(prefix).isdigit()
    ]
    return max(used, default=0) + 1


def _open_library_metrics_task_for_market(
    existing_rows: list[dict[str, Any]], market_id: str
) -> bool:
    market_lower = market_id.lower()
    for row in existing_rows:
        status = str(row.get("status") or "open")
        if status in TERMINAL_TASK_STATUSES:
            continue
        area = str(row.get("area") or "").lower()
        if area not in {"coverage", "ingest"}:
            continue
        evidence = row.get("evidence") or {}
        if str(evidence.get("market") or "") == market_id:
            return True
        if str(evidence.get("focus_market") or "") == market_id:
            return True
        title = str(row.get("title") or "").lower()
        if market_lower in title and (
            "library metrics" in title or "screen-lite" in title or "stooq" in title
        ):
            return True
    return False


def ladder_metrics_block_assessment(
    ladder_result: dict[str, Any],
    *,
    root: Path,
    policy_path: Path | None = None,
) -> dict[str, Any] | None:
    """Return block metadata when focus market cannot run screen-lite on usable metrics."""
    from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy
    from value_investor.data_library import library_status
    from value_investor.library_screen import assess_library_metrics_health

    focus = str(ladder_result.get("focus_market") or "").strip()
    if not focus:
        return None

    layers = ladder_result.get("layers") or {}
    fundamentals = layers.get("fundamentals") or {}
    if fundamentals.get("skipped") and not fundamentals.get("status"):
        return None

    policy_path = policy_path or DEFAULT_POLICY_PATH
    policy = load_policy(policy_path)
    ladder_cfg = policy.get("ladder") or {}
    min_metrics = int(ladder_cfg.get("min_metrics_for_screen") or DEFAULT_MIN_METRICS_FOR_SCREEN)

    screen = layers.get("screen_lite") or {}
    if screen.get("skipped") and screen.get("reason") is None and not screen.get("failed"):
        return None

    health = assess_library_metrics_health(root, focus)
    usable = int(health.get("usable_rows") or 0)
    if usable >= min_metrics:
        return None

    status_rows = library_status(root, markets=[focus])
    status_row = status_rows[0] if status_rows else {}
    ticker_count = int(status_row.get("ticker_count") or 0)
    total_rows = int(health.get("total_rows") or 0)
    if ticker_count <= 0 and total_rows <= 0:
        return None

    screen_failed = bool(screen.get("failed"))
    screen_skipped = bool(screen.get("skipped"))
    if screen_skipped:
        block_reason = "screen_lite_skipped"
    elif screen_failed:
        block_reason = "screen_lite_failed"
    else:
        block_reason = "usable_metrics_below_threshold"

    manifest_coverage = int(status_row.get("coverage_count") or 0)
    if screen.get("manifest_coverage_count") is not None:
        manifest_coverage = int(screen.get("manifest_coverage_count") or manifest_coverage)

    return {
        "market": focus,
        "focus_market": focus,
        "min_metrics_for_screen": min_metrics,
        "usable_metrics_rows": usable,
        "total_metrics_rows": total_rows,
        "ticker_count": ticker_count,
        "manifest_coverage_count": manifest_coverage,
        "blocked_layer": "screen_lite",
        "block_reason": block_reason,
        "screen_reason": screen.get("reason"),
        "screen_error": screen.get("error"),
        "sample_tickers": list(health.get("sample_tickers") or []),
        "sample_errors": list(health.get("sample_errors") or []),
        "metrics_path": health.get("metrics_path"),
    }


def draft_library_ladder_engineering_tasks(
    ladder_result: dict[str, Any],
    *,
    root: Path,
    policy_path: Path | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
    max_tasks: int = 1,
) -> dict[str, Any]:
    """Draft a supervised coverage task when library ladder cannot screen the focus market."""
    if max_tasks <= 0:
        return {"drafted_count": 0, "reason": "max_tasks=0"}

    assessment = ladder_metrics_block_assessment(
        ladder_result,
        root=root,
        policy_path=policy_path,
    )
    if assessment is None:
        return {"drafted_count": 0, "reason": "no library metrics block detected"}

    market = str(assessment["market"])
    payload = load_engineering_tasks(committed_path)
    existing_rows = list(payload.get("tasks") or [])
    if _open_library_metrics_task_for_market(existing_rows, market):
        return {
            "drafted_count": 0,
            "reason": f"open library metrics task already exists for {market}",
            "market": market,
        }

    from value_investor.data_library import MARKET_REGISTRY

    spec = MARKET_REGISTRY.get(market)
    label = spec.label if spec is not None else market
    sample_err_text = "; ".join(assessment.get("sample_errors") or [])[:240]
    title = (
        f"Fix library metrics fetch for {label} ({market}): "
        "provider mapping / Yahoo fallback so screen-lite can run"
    )[:160]

    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    seq = _next_engineering_seq_from_rows(existing_rows, run_stamp)
    summary = (
        f"Focus market {market} has {assessment['ticker_count']} constituents but only "
        f"{assessment['usable_metrics_rows']} usable metrics rows "
        f"(need >={assessment['min_metrics_for_screen']} for screen-lite). "
        f"Manifest coverage_count={assessment['manifest_coverage_count']}. "
        f"Block: {assessment['block_reason']}."
    )
    if assessment.get("screen_error"):
        summary += f" Screen error: {assessment['screen_error']}."
    if sample_err_text:
        summary += f" Sample errors: {sample_err_text}."
    summary += (
        f" Fix provider suffix mapping, Yahoo/yfinance fallback, and metrics grow; "
        f"verify ftse-library grow --markets {market} + screen succeed offline."
    )

    min_metrics = int(assessment["min_metrics_for_screen"])
    acceptance = [
        f"After grow, {market} metrics/latest has ≥{min_metrics} usable fundamentals rows",
        f"load_library_metrics / run_library_screen can run on {market} without empty-universe failure",
        "Add regression tests for the provider/suffix fix on representative tickers",
        "No change to live FTSE 350 screen path or blocked_paths",
    ]

    task = EngineeringTask(
        id=f"eng-{run_stamp}-{seq:02d}",
        area="coverage",
        title=title,
        summary=summary[:500],
        priority="high",
        priority_score=92.0,
        source="library_ladder",
        evidence={
            **assessment,
            "doc": "docs/ops/market-scrutiny.md",
            "ladder_run_at": ladder_result.get("run_at"),
        },
        acceptance_criteria=acceptance,
        allowed_paths=list(LIBRARY_METRICS_ALLOWED_PATHS),
        blocked_paths=list(BLOCKED_PATHS),
    )

    merged_rows = _merge_task_rows(existing_rows, [task])
    open_ids_before = {
        str(row.get("id") or "")
        for row in existing_rows
        if str(row.get("status") or "open") == "open"
    }
    newly_open = [
        row
        for row in merged_rows
        if str(row.get("status") or "open") == "open"
        and str(row.get("id") or "") not in open_ids_before
    ]
    payload = {
        **payload,
        "compiled_at": datetime.now(UTC).isoformat(),
        "task_count": len(merged_rows),
        "tasks": merged_rows,
        "library_ladder_compiled": True,
    }
    committed_path = Path(committed_path)
    tasks_path = Path(tasks_path)
    committed_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(committed_path, payload, compact=False)
    if tasks_path != committed_path:
        write_json(tasks_path, payload, compact=False)

    return {
        "drafted_count": len(newly_open),
        "task_ids": [str(row.get("id") or "") for row in newly_open],
        "market": market,
        "assessment": assessment,
    }


def _read_run_at(output_dir: Path) -> str | None:
    gap_fill = output_dir / "gap_fill_summary.json"
    if gap_fill.exists():
        try:
            data = read_json(gap_fill)
            if data.get("run_at"):
                return str(data["run_at"])
        except (OSError, ValueError, TypeError):
            pass
    return None


def load_engineering_tasks(path: Path = DEFAULT_TASKS_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"tasks": []}
    try:
        return read_json(path)
    except (OSError, ValueError, TypeError):
        return {"tasks": []}


def select_engineering_tasks(
    payload: dict[str, Any] | None = None,
    *,
    path: Path = DEFAULT_TASKS_PATH,
    task_id: str | None = None,
    max_tasks: int = DEFAULT_MAX_RUN_TASKS,
) -> list[EngineeringTask]:
    data = payload or load_engineering_tasks(path)
    tasks = [
        EngineeringTask.from_dict(row)
        for row in data.get("tasks") or []
        if str(row.get("status") or "open") == "open"
    ]
    if task_id:
        wanted = str(task_id).strip()
        return [task for task in tasks if task.id == wanted]
    tasks.sort(key=lambda row: -row.priority_score)
    return tasks[: max(0, int(max_tasks))]


def _write_task_queue(payload: dict[str, Any], *, path: Path) -> None:
    write_json(path, payload, compact=False)


def _update_task_queue(
    task_id: str,
    *,
    path: Path,
    committed_path: Path = COMMITTED_TASKS_PATH,
    **fields: Any,
) -> EngineeringTask | None:
    data = load_engineering_tasks(path)
    updated: EngineeringTask | None = None
    for row in data.get("tasks") or []:
        if str(row.get("id")) != task_id:
            continue
        row.update(fields)
        updated = EngineeringTask.from_dict(row)
        break
    if updated is not None:
        _write_task_queue(data, path=path)
        committed = Path(committed_path)
        committed.parent.mkdir(parents=True, exist_ok=True)
        _write_task_queue(data, path=committed)
        if committed.resolve() == Path(COMMITTED_TASKS_PATH).resolve() and "status" in fields:
            try:
                from value_investor.engineering_queue import refresh_engineering_queue_ui

                refresh_engineering_queue_ui(tasks_path=committed)
            except OSError:
                pass
    return updated


def mark_task_status(
    task_id: str,
    status: str,
    *,
    path: Path = DEFAULT_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
    result_path: str | None = None,
    branch_name: str | None = None,
    pr_url: str | None = None,
    pr_number: int | None = None,
    **extra_fields: Any,
) -> EngineeringTask | None:
    data = load_engineering_tasks(path)
    prior_row = next(
        (row for row in data.get("tasks") or [] if str(row.get("id")) == task_id),
        None,
    )
    fields: dict[str, Any] = {"status": status, **extra_fields}
    if result_path:
        fields["result_path"] = result_path
    if branch_name:
        fields["branch_name"] = branch_name
    if pr_url:
        fields["pr_url"] = pr_url
    if pr_number is not None:
        fields["pr_number"] = pr_number
    if status == "failed":
        fields["failure_count"] = int((prior_row or {}).get("failure_count") or 0) + 1
        fields["last_failed_at"] = datetime.now(UTC).isoformat()
    if status in {"pr_open", "merged"}:
        fields["no_diff_count"] = 0
    if status == "parked":
        fields.setdefault("parked_at", datetime.now(UTC).isoformat())
        fields.setdefault("parked_reason", "manual review required")
    if status == "cancelled":
        fields.setdefault("cancelled_at", datetime.now(UTC).isoformat())
    if status in {"pr_open", "completed"}:
        fields["completed_at"] = datetime.now(UTC).isoformat()
    if status == "merged":
        fields["merged_at"] = datetime.now(UTC).isoformat()
    return _update_task_queue(
        task_id,
        path=path,
        committed_path=committed_path,
        **fields,
    )


def mark_task_merged_for_branch(
    branch: str,
    *,
    path: Path = COMMITTED_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
    pr_url: str | None = None,
    pr_number: int | None = None,
) -> EngineeringTask | None:
    from value_investor.engineering_queue import task_id_from_branch

    task_id = task_id_from_branch(branch)
    if not task_id:
        return None
    data = load_engineering_tasks(path)
    for row in data.get("tasks") or []:
        if str(row.get("id")) == task_id or str(row.get("branch_name") or "") == branch:
            return mark_task_status(
                str(row["id"]),
                "merged",
                path=path,
                committed_path=committed_path,
                branch_name=branch,
                pr_url=pr_url,
                pr_number=pr_number,
            )
    return mark_task_status(
        task_id,
        "merged",
        path=path,
        committed_path=committed_path,
        branch_name=branch,
        pr_url=pr_url,
        pr_number=pr_number,
    )


def normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").strip().lstrip("./")


def path_matches_allowed_pattern(changed: str, pattern: str) -> bool:
    """Return True when *changed* is within an allowed file or directory pattern."""
    changed = normalize_repo_path(changed)
    pattern = normalize_repo_path(pattern)
    if not pattern:
        return False
    if pattern.endswith("/"):
        return changed.startswith(pattern) or changed == pattern.rstrip("/")
    return changed == pattern


def path_matches_blocked_pattern(changed: str, blocked: str) -> bool:
    changed = normalize_repo_path(changed)
    blocked = normalize_repo_path(blocked)
    return changed == blocked


@dataclass
class PathGuardResult:
    ok: bool
    violations: list[str]
    task_id: str | None = None
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "skipped": self.skipped,
            "task_id": self.task_id,
            "violations": list(self.violations),
        }


def find_engineering_task(
    task_id: str,
    *,
    path: Path = COMMITTED_TASKS_PATH,
) -> EngineeringTask | None:
    wanted = str(task_id).strip()
    for row in load_engineering_tasks(path).get("tasks") or []:
        if str(row.get("id")) == wanted:
            return EngineeringTask.from_dict(row)
    return None


def expand_task_allowed_paths(
    task_id: str,
    extra_paths: list[str],
    *,
    path: Path = COMMITTED_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
) -> tuple[EngineeringTask | None, list[str]]:
    """Append safe paths to a task allowlist (used by CI path-guard autofix)."""
    task = find_engineering_task(task_id, path=path)
    if task is None:
        return None, []

    blocked = list(dict.fromkeys([*BLOCKED_PATHS, *(task.blocked_paths or [])]))
    allowed = list(task.allowed_paths or [])
    added: list[str] = []

    for raw in extra_paths:
        normalized = normalize_repo_path(raw)
        if not normalized or normalized in allowed:
            continue
        if any(path_matches_blocked_pattern(normalized, pattern) for pattern in blocked):
            continue
        allowed.append(normalized)
        added.append(normalized)

    if not added:
        return task, []

    return mark_task_status(
        task_id,
        str(task.status or "open"),
        path=path,
        committed_path=committed_path,
        allowed_paths=allowed,
    ), added


def validate_engineering_pr_paths(
    *,
    task: EngineeringTask,
    changed_files: list[str],
) -> PathGuardResult:
    """Validate PR file changes against task allow/block lists and global BLOCKED_PATHS."""
    blocked = list(dict.fromkeys([*BLOCKED_PATHS, *(task.blocked_paths or [])]))
    allowed = list(task.allowed_paths or [])
    normalized = [normalize_repo_path(path) for path in changed_files]
    normalized = [path for path in normalized if path]

    if not normalized:
        return PathGuardResult(ok=True, violations=[], task_id=task.id)

    violations: list[str] = []
    for changed in normalized:
        for blocked_path in blocked:
            if path_matches_blocked_pattern(changed, blocked_path):
                violations.append(f"blocked path touched: {changed} (matches {blocked_path})")
                break
        else:
            if not allowed:
                violations.append(f"outside allowed_paths: {changed} (task has no allowed_paths)")
            elif not any(path_matches_allowed_pattern(changed, pattern) for pattern in allowed):
                violations.append(f"outside allowed_paths: {changed}")

    return PathGuardResult(ok=not violations, violations=violations, task_id=task.id)


def validate_engineering_pr_paths_for_task_id(
    task_id: str,
    changed_files: list[str],
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> PathGuardResult:
    task = find_engineering_task(task_id, path=tasks_path)
    if task is None:
        return PathGuardResult(
            ok=False,
            violations=[f"unknown engineering task id: {task_id}"],
            task_id=task_id,
        )
    return validate_engineering_pr_paths(task=task, changed_files=changed_files)
