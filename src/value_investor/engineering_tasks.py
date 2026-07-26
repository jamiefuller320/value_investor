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
    KNOWN_SOURCE_IDS,
    map_suggestion_to_source_ids,
)
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_TASKS_PATH = Path("output/engineering_tasks.json")
COMMITTED_TASKS_PATH = Path("docs/data/engineering_tasks.json")
DEFAULT_MAX_COMPILE_TASKS = 8
DEFAULT_MAX_RUN_TASKS = 1
TERMINAL_TASK_STATUSES = frozenset({"merged", "completed", "failed", "cancelled"})

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
        "tests/test_automation_status.py",
    ],
}

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
    if normalized in {"scoring", "prompt", "coverage", "ops"}:
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


def _tasks_from_gap_fill(gap_fill_path: Path, *, run_stamp: str, seq_start: int) -> list[EngineeringTask]:
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
        if status in TERMINAL_TASK_STATUSES or status == "pr_open":
            merged.append(row)
    merged.sort(key=lambda row: -float(row.get("priority_score") or 0.0))
    return merged


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
    committed_payload = load_engineering_tasks(committed_path) if committed_path.exists() else {"tasks": []}
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
    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    tasks: list[EngineeringTask] = []
    tasks.extend(_parse_post_run_plan(output_dir / "post_run_review.md"))
    seq = len(tasks) + 1
    tasks.extend(
        _tasks_from_suggestions(suggestions_path, run_stamp=run_stamp, seq_start=seq)
    )
    seq = len(tasks) + 1
    tasks.extend(
        _tasks_from_gap_fill(output_dir / "gap_fill_summary.json", run_stamp=run_stamp, seq_start=seq)
    )
    tasks = _dedupe_tasks(tasks)[: max(0, int(max_tasks))]

    existing_rows: list[dict[str, Any]] = []
    for candidate in (committed_path, tasks_path):
        if Path(candidate).exists():
            existing_rows = list(load_engineering_tasks(candidate).get("tasks") or [])
            if existing_rows:
                break

    merged_rows = _merge_task_rows(existing_rows, tasks)
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
    return payload


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
) -> EngineeringTask | None:
    fields: dict[str, Any] = {"status": status}
    if result_path:
        fields["result_path"] = result_path
    if branch_name:
        fields["branch_name"] = branch_name
    if pr_url:
        fields["pr_url"] = pr_url
    if pr_number is not None:
        fields["pr_number"] = pr_number
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
