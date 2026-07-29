"""Evaluate whether to auto-dispatch the next supervised engineering task."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    load_policy,
    spend_checkpoint_usd,
    spend_since_checkpoint_usd,
)
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    EngineeringTask,
    load_engineering_tasks,
    select_engineering_tasks,
    task_title_key,
)
from value_investor.storage import write_json

ENGINEERING_BRANCH_RE = re.compile(r"^cursor/eng-\d{8}-\d{2}-1de3$")
ENGINEERING_PR_TITLE_PREFIX = "feat(engineering):"

TERMINAL_STATUSES = frozenset({"merged", "completed", "failed", "cancelled", "parked"})
DISPATCHABLE_STATUS = "open"
IN_FLIGHT_STATUS = "pr_open"


@dataclass
class EngineeringQueueStatus:
    open_count: int
    pr_open_count: int
    parked_count: int
    merged_count: int
    failed_count: int
    next_task: EngineeringTask | None
    in_flight_branch: str | None
    in_flight_pr: int | None
    spend_since_checkpoint_usd: float
    spend_checkpoint_usd: float
    spend_blocked: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "open_count": self.open_count,
            "pr_open_count": self.pr_open_count,
            "parked_count": self.parked_count,
            "merged_count": self.merged_count,
            "failed_count": self.failed_count,
            "next_task_id": self.next_task.id if self.next_task else None,
            "in_flight_branch": self.in_flight_branch,
            "in_flight_pr": self.in_flight_pr,
            "spend_since_checkpoint_usd": self.spend_since_checkpoint_usd,
            "spend_checkpoint_usd": self.spend_checkpoint_usd,
            "spend_blocked": self.spend_blocked,
        }


@dataclass
class EngineeringDispatchDecision:
    should_dispatch: bool
    reason: str
    status: EngineeringQueueStatus
    next_task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "should_dispatch": self.should_dispatch,
            "reason": self.reason,
            "next_task_id": self.next_task_id,
            "status": self.status.to_dict(),
            "evaluated_at": datetime.now(UTC).isoformat(),
        }
        return payload


def is_engineering_branch(branch: str | None) -> bool:
    return bool(branch and ENGINEERING_BRANCH_RE.match(branch.strip()))


def is_engineering_pr_title(title: str | None) -> bool:
    return bool(title and title.strip().lower().startswith(ENGINEERING_PR_TITLE_PREFIX))


def find_in_flight_pr(open_prs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the newest open engineering PR, if any."""
    candidates: list[dict[str, Any]] = []
    for row in open_prs:
        branch = str(row.get("headRefName") or row.get("head_branch") or "")
        title = str(row.get("title") or "")
        if is_engineering_branch(branch) or is_engineering_pr_title(title):
            candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda row: str(row.get("createdAt") or row.get("created_at") or ""), reverse=True)
    return candidates[0]


def task_id_from_branch(branch: str) -> str | None:
    match = re.match(r"^cursor/(eng-\d{8}-\d{2})-1de3$", branch.strip())
    return match.group(1) if match else None


def branch_has_open_pr(branch: str, open_prs: list[dict[str, Any]] | None = None) -> bool:
    wanted = branch.strip()
    for row in open_prs or []:
        head = str(row.get("headRefName") or row.get("head_branch") or "").strip()
        if head == wanted:
            return True
    return False


def is_safe_to_clear_stale_branch(
    branch: str,
    open_prs: list[dict[str, Any]] | None = None,
) -> bool:
    """True when an engineering branch has no open PR and may be deleted before re-push."""
    if not is_engineering_branch(branch):
        return False
    return not branch_has_open_pr(branch, open_prs)


def summarize_queue(
    payload: dict[str, Any] | None = None,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    policy_path: Path | None = None,
    open_prs: list[dict[str, Any]] | None = None,
) -> EngineeringQueueStatus:
    data = payload or load_engineering_tasks(tasks_path)
    rows = list(data.get("tasks") or [])
    open_count = sum(1 for row in rows if str(row.get("status") or "open") == DISPATCHABLE_STATUS)
    pr_open_count = sum(1 for row in rows if str(row.get("status") or "") == IN_FLIGHT_STATUS)
    parked_count = sum(1 for row in rows if str(row.get("status") or "") == "parked")
    merged_count = sum(
        1 for row in rows if str(row.get("status") or "") in {"merged", "completed"}
    )
    failed_count = sum(1 for row in rows if str(row.get("status") or "") == "failed")

    next_tasks = select_engineering_tasks(data, max_tasks=1)
    next_task = next_tasks[0] if next_tasks else None

    in_flight = find_in_flight_pr(open_prs or [])
    in_flight_branch = None
    in_flight_pr = None
    if in_flight is not None:
        in_flight_branch = str(in_flight.get("headRefName") or in_flight.get("head_branch") or "") or None
        in_flight_pr = int(in_flight["number"]) if in_flight.get("number") is not None else None

    policy = load_policy(policy_path)
    since = spend_since_checkpoint_usd(policy)
    limit = spend_checkpoint_usd(policy)

    return EngineeringQueueStatus(
        open_count=open_count,
        pr_open_count=pr_open_count,
        parked_count=parked_count,
        merged_count=merged_count,
        failed_count=failed_count,
        next_task=next_task,
        in_flight_branch=in_flight_branch,
        in_flight_pr=in_flight_pr,
        spend_since_checkpoint_usd=since,
        spend_checkpoint_usd=limit,
        spend_blocked=since >= limit,
    )


def evaluate_engineering_dispatch(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    policy_path: Path | None = None,
    open_prs: list[dict[str, Any]] | None = None,
    engineering_agent_running: bool = False,
    force: bool = False,
) -> EngineeringDispatchDecision:
    """Decide whether the queue processor should dispatch engineering-agent."""
    status = summarize_queue(
        tasks_path=tasks_path,
        policy_path=policy_path,
        open_prs=open_prs,
    )

    if engineering_agent_running:
        return EngineeringDispatchDecision(
            should_dispatch=False,
            reason="engineering-agent workflow already running",
            status=status,
        )

    if status.in_flight_pr is not None:
        return EngineeringDispatchDecision(
            should_dispatch=False,
            reason=f"open engineering PR #{status.in_flight_pr} ({status.in_flight_branch})",
            status=status,
        )

    if status.next_task is None:
        return EngineeringDispatchDecision(
            should_dispatch=False,
            reason="no open engineering tasks in queue",
            status=status,
        )

    if status.spend_blocked and not force:
        return EngineeringDispatchDecision(
            should_dispatch=False,
            reason=(
                f"ad-hoc spend checkpoint reached "
                f"(${status.spend_since_checkpoint_usd:.2f} / ${status.spend_checkpoint_usd:.2f})"
            ),
            status=status,
        )

    return EngineeringDispatchDecision(
        should_dispatch=True,
        reason="queue ready — dispatch next open task",
        status=status,
        next_task_id=status.next_task.id,
    )


def reconcile_orphaned_pr_open_tasks(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    open_prs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reset pr_open tasks that have no matching open engineering PR."""
    data = load_engineering_tasks(tasks_path)
    open_branches = {
        str(row.get("headRefName") or row.get("head_branch") or "").strip()
        for row in (open_prs or [])
        if str(row.get("headRefName") or row.get("head_branch") or "").strip()
    }
    reset_ids: list[str] = []
    for row in data.get("tasks") or []:
        if str(row.get("status") or "") != IN_FLIGHT_STATUS:
            continue
        branch = str(row.get("branch_name") or "").strip()
        if branch and branch in open_branches:
            continue
        row["status"] = DISPATCHABLE_STATUS
        for key in ("branch_name", "completed_at", "pr_number", "pr_url", "result_path"):
            row.pop(key, None)
        reset_ids.append(str(row["id"]))
    if reset_ids:
        tasks_path = Path(tasks_path)
        tasks_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(tasks_path, data, compact=False)
    return {"reset": reset_ids, "count": len(reset_ids)}


_INGEST_KEYWORDS = (
    "companies house",
    "filed-accounts",
    "filed accounts",
    "pdf",
    "investegate",
    "google news",
    "wrapper",
    "rns",
    "sedar",
    "dual-source",
    "dual-listed",
    "body",
    "ixbrl",
)


def _title_keywords(title: str) -> set[str]:
    lowered = task_title_key(title)
    return {word for word in _INGEST_KEYWORDS if word in lowered}


def _filing_index_paths_for_ticker(ticker: str, *, roots: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        direct = root / ticker / "sources" / "filings" / "filings_index.json"
        if direct.exists():
            paths.append(direct)
        paths.extend(root.glob(f"**/screen/research/{ticker}/sources/filings/filings_index.json"))
    return paths


def _coverage_from_index(path: Path) -> dict[str, int]:
    from value_investor.storage import read_json

    coverage = {
        "filings_total": 0,
        "filings_with_body": 0,
        "indexed_without_body": 0,
    }
    try:
        index = read_json(path)
    except (OSError, ValueError, TypeError):
        return coverage
    summary = index.get("summary") or {}
    filings = list(index.get("filings") or [])
    coverage["filings_total"] = int(summary.get("total") or len(filings))
    coverage["filings_with_body"] = int(summary.get("with_body") or 0)
    coverage["indexed_without_body"] = sum(1 for row in filings if not row.get("has_body"))
    return coverage


def _buy_tier_tickers(latest_path: Path) -> list[str]:
    from value_investor.storage import read_json

    if not latest_path.exists():
        return []
    try:
        payload = read_json(latest_path)
    except (OSError, ValueError, TypeError):
        return []
    tickers: list[str] = []
    for row in payload.get("reports") or []:
        if str(row.get("signal") or "") in {"strong_buy", "buy"}:
            ticker = str(row.get("ticker") or "").strip().upper()
            if ticker:
                tickers.append(ticker)
    return tickers


def snapshot_ingest_health(
    *,
    latest_path: Path = Path("docs/data/latest.json"),
    research_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """Summarise buy-tier filing body coverage from committed research stores."""
    roots = research_roots or [
        Path("docs/data/research"),
        Path("output/research"),
        Path("docs/data/library/markets"),
    ]
    tickers = _buy_tier_tickers(latest_path)
    zero_body = 0
    indexed_without_body = 0
    with_body = 0
    measured = 0
    for ticker in tickers:
        paths = _filing_index_paths_for_ticker(ticker, roots=roots)
        if not paths:
            continue
        measured += 1
        coverage = _coverage_from_index(paths[0])
        with_body += coverage["filings_with_body"]
        indexed_without_body += coverage["indexed_without_body"]
        if coverage["filings_with_body"] == 0 and coverage["filings_total"] > 0:
            zero_body += 1
        elif coverage["filings_total"] == 0:
            zero_body += 1
    return {
        "snapshot_at": datetime.now(UTC).isoformat(),
        "buy_tier_count": len(tickers),
        "measured_tickers": measured,
        "zero_body_buy_tier": zero_body,
        "indexed_without_body": indexed_without_body,
        "filings_with_body": with_body,
    }


def reprioritize_queue_after_ingest_merge(
    *,
    merged_task_id: str,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    latest_path: Path = Path("docs/data/latest.json"),
) -> dict[str, Any]:
    """
    Deterministically nudge open queue priorities after an ingest engineering merge.

  No agent call — uses filing coverage deltas and keyword overlap with the merged task.
    """
    from value_investor.engineering_tasks import load_engineering_tasks
    from value_investor.storage import write_json

    payload = load_engineering_tasks(tasks_path)
    merged_row = next(
        (row for row in payload.get("tasks") or [] if str(row.get("id")) == merged_task_id),
        None,
    )
    if merged_row is None:
        return {"skipped": True, "reason": f"task {merged_task_id} not found"}
    if str(merged_row.get("area") or "").lower() != "ingest":
        return {"skipped": True, "reason": "merged task is not ingest area"}

    before = dict(payload.get("ingest_health") or {})
    after = snapshot_ingest_health(latest_path=latest_path)
    merged_keywords = _title_keywords(str(merged_row.get("title") or ""))
    adjustments: list[dict[str, Any]] = []

    zero_before = int(before.get("zero_body_buy_tier") or after["zero_body_buy_tier"])
    zero_after = int(after["zero_body_buy_tier"])
    improved = zero_after < zero_before

    for row in payload.get("tasks") or []:
        if str(row.get("status") or "open") != DISPATCHABLE_STATUS:
            continue
        area = str(row.get("area") or "").lower()
        score = float(row.get("priority_score") or 0.0)
        delta = 0.0
        title = str(row.get("title") or "")
        overlap = _title_keywords(title) & merged_keywords

        if area == "ingest":
            if overlap:
                delta -= 4.0
            elif not improved:
                delta += 2.0
        elif area in {"scoring", "prompt"} and improved:
            delta += 5.0
        elif area in {"scoring", "prompt"} and zero_after > 0:
            delta -= 1.0

        if delta:
            row["priority_score"] = round(max(0.0, min(100.0, score + delta)), 1)
            adjustments.append(
                {
                    "task_id": row.get("id"),
                    "delta": delta,
                    "priority_score": row["priority_score"],
                }
            )

    payload["tasks"] = sorted(
        list(payload.get("tasks") or []),
        key=lambda row: -float(row.get("priority_score") or 0.0),
    )
    payload["ingest_health"] = after
    payload["ingest_health_before"] = before or after
    payload["reprioritized_at"] = datetime.now(UTC).isoformat()
    payload["reprioritized_after_task"] = merged_task_id
    write_json(tasks_path, payload, compact=False)
    return {
        "skipped": False,
        "merged_task_id": merged_task_id,
        "improved": improved,
        "ingest_health_before": before,
        "ingest_health_after": after,
        "adjustments": adjustments,
    }
