"""Post-merge acceptance verification with capped engineering rework.

After an engineering PR merges, run the task's scoped pytest paths on ``main``.
On failure, queue a linked rework task (new id / branch) up to
``MAX_VERIFY_REWORK_ROUNDS`` attempts in the verify chain. Ingest gap-closure
tasks keep their existing outcome-based verify chain and are skipped here.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    EngineeringTask,
    load_engineering_tasks,
    mark_task_status,
)
from value_investor.storage import write_json

logger = logging.getLogger(__name__)

MAX_VERIFY_REWORK_ROUNDS = 3
VERIFY_SOURCE = "post_merge_verify_rework"
PARKED_POLICY_VERIFY_EXHAUSTED = "verify_rework_exhausted"

PytestRunner = Callable[[list[str], Path], dict[str, Any]]


def acceptance_test_paths(task: dict[str, Any] | EngineeringTask) -> list[str]:
    """Return unique test file/dir paths listed on the task's allowed_paths."""
    allowed = (
        list(task.allowed_paths)
        if isinstance(task, EngineeringTask)
        else list(task.get("allowed_paths") or [])
    )
    paths: list[str] = []
    seen: set[str] = set()
    for raw in allowed:
        value = str(raw or "").strip().replace("\\", "/")
        if not value:
            continue
        if value == "tests" or value.startswith("tests/"):
            if value not in seen:
                seen.add(value)
                paths.append(value)
            continue
        # Directory allow-lists like tests/ sometimes end with /
        if value.rstrip("/") == "tests":
            if "tests" not in seen:
                seen.add("tests")
                paths.append("tests")
    return paths


def verify_chain_root_id(task: dict[str, Any]) -> str:
    evidence = task.get("evidence") or {}
    root = str(evidence.get("verify_chain_root_id") or "").strip()
    if root:
        return root
    return str(task.get("id") or "").strip()


def count_verify_chain_rounds(
    chain_root: str,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> int:
    """Count original + rework tasks that belong to this verify chain."""
    if not chain_root:
        return 0
    payload = load_engineering_tasks(tasks_path)
    count = 0
    for row in payload.get("tasks") or []:
        task_id = str(row.get("id") or "")
        evidence = row.get("evidence") or {}
        if task_id == chain_root:
            count += 1
            continue
        if str(evidence.get("verify_chain_root_id") or "") == chain_root:
            count += 1
            continue
        if str(evidence.get("parent_task_id") or "") == chain_root and str(
            row.get("source") or ""
        ) == VERIFY_SOURCE:
            count += 1
    return count


def has_open_verify_rework_for_chain(
    chain_root: str,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> bool:
    payload = load_engineering_tasks(tasks_path)
    for row in payload.get("tasks") or []:
        status = str(row.get("status") or "open")
        if status not in {"open", "pr_open"}:
            continue
        evidence = row.get("evidence") or {}
        if str(evidence.get("verify_chain_root_id") or "") == chain_root:
            return True
        if str(row.get("source") or "") == VERIFY_SOURCE and str(
            evidence.get("parent_task_id") or ""
        ) == chain_root:
            return True
    return False


def should_run_acceptance_verify(task: dict[str, Any]) -> tuple[bool, str]:
    """Whether this merged task should get the generic acceptance pytest gate."""
    status = str(task.get("status") or "")
    if status != "merged":
        return False, "task_not_merged"
    evidence = task.get("evidence") or {}
    if evidence.get("rerun_ingest_gap_closure") or evidence.get("rerun_ingest_trial"):
        return False, "ingest_gap_closure_owns_verification"
    if str(evidence.get("verify_status") or "") == "passed":
        return False, "already_verified"
    if str(evidence.get("verify_status") or "") == "exhausted":
        return False, "verify_chain_exhausted"
    if str(evidence.get("verify_status") or "") == "rework_queued":
        return False, "rework_already_queued"
    paths = acceptance_test_paths(task)
    if not paths:
        return False, "no_acceptance_test_paths"
    return True, "ok"


def default_pytest_runner(paths: list[str], cwd: Path) -> dict[str, Any]:
    """Run pytest on the given paths; return exit code + trimmed output."""
    existing = [p for p in paths if (cwd / p).exists()]
    if not existing:
        return {
            "ok": False,
            "returncode": 2,
            "paths": paths,
            "existing_paths": [],
            "output": "No acceptance test paths exist on disk",
        }
    cmd = ["python3", "-m", "pytest", "-q", "--tb=line", *existing]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": 124,
            "paths": paths,
            "existing_paths": existing,
            "output": f"pytest timed out after 600s: {exc}",
        }
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    if len(output) > 4000:
        output = output[-4000:]
    return {
        "ok": completed.returncode == 0,
        "returncode": int(completed.returncode),
        "paths": paths,
        "existing_paths": existing,
        "output": output,
    }


def _next_task_seq(existing_rows: list[dict[str, Any]], run_stamp: str) -> int:
    prefix = f"eng-{run_stamp}-"
    used: list[int] = []
    for row in existing_rows:
        task_id = str(row.get("id") or "")
        if not task_id.startswith(prefix):
            continue
        suffix = task_id.removeprefix(prefix)
        if suffix.isdigit():
            used.append(int(suffix))
    return max(used, default=0) + 1


def _write_tasks(payload: dict[str, Any], *, path: Path) -> None:
    write_json(path, payload, compact=False)


def _queue_rework_task(
    parent: dict[str, Any],
    *,
    chain_root: str,
    next_round: int,
    pytest_result: dict[str, Any],
    tasks_path: Path,
) -> dict[str, Any]:
    payload = load_engineering_tasks(tasks_path)
    rows = list(payload.get("tasks") or [])
    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    seq = _next_task_seq(rows, run_stamp)
    new_id = f"eng-{run_stamp}-{seq:02d}"
    parent_title = str(parent.get("title") or "").strip()
    title = f"Rework verify round {next_round}/{MAX_VERIFY_REWORK_ROUNDS}: {parent_title}"[:160]
    summary = (
        f"Post-merge acceptance pytest failed for {parent.get('id')}. "
        f"Re-implement until acceptance tests pass "
        f"(chain {chain_root}, round {next_round}/{MAX_VERIFY_REWORK_ROUNDS}). "
        f"pytest rc={pytest_result.get('returncode')}: "
        f"{str(pytest_result.get('output') or '')[:500]}"
    )
    evidence = {
        "verify_chain_root_id": chain_root,
        "parent_task_id": str(parent.get("id") or ""),
        "verify_round": next_round,
        "max_verify_rounds": MAX_VERIFY_REWORK_ROUNDS,
        "prior_pr_url": parent.get("pr_url"),
        "prior_pr_number": parent.get("pr_number"),
        "pytest_returncode": pytest_result.get("returncode"),
        "pytest_paths": list(pytest_result.get("existing_paths") or pytest_result.get("paths") or []),
        "tickers": list((parent.get("evidence") or {}).get("tickers") or []),
    }
    rework = EngineeringTask(
        id=new_id,
        area=str(parent.get("area") or "ops"),
        title=title,
        summary=summary,
        priority=str(parent.get("priority") or "high"),
        priority_score=float(parent.get("priority_score") or 0.0) + 1.0,
        source=VERIFY_SOURCE,
        evidence=evidence,
        acceptance_criteria=list(parent.get("acceptance_criteria") or []),
        allowed_paths=list(parent.get("allowed_paths") or []),
        blocked_paths=list(parent.get("blocked_paths") or []),
        auto_merge=bool(parent.get("auto_merge")),
        status="open",
    )
    rows.append(rework.to_dict())
    rows.sort(key=lambda row: -float(row.get("priority_score") or 0.0))
    payload["tasks"] = rows
    payload["task_count"] = len(rows)
    payload["compiled_at"] = datetime.now(UTC).isoformat()
    _write_tasks(payload, path=tasks_path)

    parent_evidence = dict(parent.get("evidence") or {})
    parent_evidence["verify_status"] = "rework_queued"
    parent_evidence["verify_chain_root_id"] = chain_root
    parent_evidence["verify_rework_task_id"] = new_id
    parent_evidence["verify_failed_at"] = datetime.now(UTC).isoformat()
    parent_evidence["verify_pytest"] = {
        "returncode": pytest_result.get("returncode"),
        "paths": pytest_result.get("existing_paths") or pytest_result.get("paths"),
        "output_tail": str(pytest_result.get("output") or "")[-1500:],
    }
    mark_task_status(
        str(parent.get("id") or ""),
        "merged",
        path=tasks_path,
        committed_path=tasks_path,
        evidence=parent_evidence,
    )
    return rework.to_dict()


def _mark_parent_verified(
    parent: dict[str, Any],
    *,
    chain_root: str,
    pytest_result: dict[str, Any],
    tasks_path: Path,
) -> None:
    evidence = dict(parent.get("evidence") or {})
    evidence["verify_status"] = "passed"
    evidence["verify_chain_root_id"] = chain_root
    evidence["verified_at"] = datetime.now(UTC).isoformat()
    evidence["verify_pytest"] = {
        "returncode": pytest_result.get("returncode"),
        "paths": pytest_result.get("existing_paths") or pytest_result.get("paths"),
        "output_tail": str(pytest_result.get("output") or "")[-1500:],
    }
    mark_task_status(
        str(parent.get("id") or ""),
        "merged",
        path=tasks_path,
        committed_path=tasks_path,
        evidence=evidence,
    )


def _mark_parent_exhausted(
    parent: dict[str, Any],
    *,
    chain_root: str,
    pytest_result: dict[str, Any],
    tasks_path: Path,
    rounds: int,
) -> None:
    evidence = dict(parent.get("evidence") or {})
    evidence["verify_status"] = "exhausted"
    evidence["verify_chain_root_id"] = chain_root
    evidence["verify_exhausted_at"] = datetime.now(UTC).isoformat()
    evidence["verify_rounds"] = rounds
    evidence["verify_pytest"] = {
        "returncode": pytest_result.get("returncode"),
        "paths": pytest_result.get("existing_paths") or pytest_result.get("paths"),
        "output_tail": str(pytest_result.get("output") or "")[-1500:],
    }
    mark_task_status(
        str(parent.get("id") or ""),
        "merged",
        path=tasks_path,
        committed_path=tasks_path,
        evidence=evidence,
        parked_reason=(
            f"Acceptance verify failed after {rounds}/{MAX_VERIFY_REWORK_ROUNDS} "
            f"chain rounds ({PARKED_POLICY_VERIFY_EXHAUSTED})"
        ),
    )


def verify_merged_task(
    task_id: str,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    cwd: Path | None = None,
    pytest_runner: PytestRunner | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    """Run post-merge acceptance pytest and queue capped rework on failure."""
    task_id = str(task_id or "").strip()
    payload = load_engineering_tasks(tasks_path)
    row = next(
        (task for task in payload.get("tasks") or [] if str(task.get("id") or "") == task_id),
        None,
    )
    if not isinstance(row, dict):
        return {
            "task_id": task_id,
            "action": "skip",
            "should_rework": False,
            "reason": "task not found",
        }

    should, reason = should_run_acceptance_verify(row)
    if not should:
        return {
            "task_id": task_id,
            "action": "skip",
            "should_rework": False,
            "reason": reason,
        }

    chain_root = verify_chain_root_id(row)
    if has_open_verify_rework_for_chain(chain_root, tasks_path=tasks_path):
        return {
            "task_id": task_id,
            "action": "skip",
            "should_rework": False,
            "reason": "open_rework_already_in_flight",
            "verify_chain_root_id": chain_root,
        }

    paths = acceptance_test_paths(row)
    runner = pytest_runner or default_pytest_runner
    workdir = Path(cwd or Path.cwd())
    pytest_result = runner(paths, workdir)
    rounds = count_verify_chain_rounds(chain_root, tasks_path=tasks_path)
    if rounds <= 0:
        rounds = 1

    if pytest_result.get("ok"):
        if apply:
            _mark_parent_verified(
                row,
                chain_root=chain_root,
                pytest_result=pytest_result,
                tasks_path=tasks_path,
            )
        return {
            "task_id": task_id,
            "action": "passed",
            "should_rework": False,
            "reason": "acceptance_pytest_passed",
            "verify_chain_root_id": chain_root,
            "verify_round": rounds,
            "pytest": pytest_result,
        }

    if rounds >= MAX_VERIFY_REWORK_ROUNDS:
        if apply:
            _mark_parent_exhausted(
                row,
                chain_root=chain_root,
                pytest_result=pytest_result,
                tasks_path=tasks_path,
                rounds=rounds,
            )
        return {
            "task_id": task_id,
            "action": "exhausted",
            "should_rework": False,
            "reason": "max_verify_rework_rounds",
            "verify_chain_root_id": chain_root,
            "verify_round": rounds,
            "max_verify_rounds": MAX_VERIFY_REWORK_ROUNDS,
            "pytest": pytest_result,
        }

    next_round = rounds + 1
    rework: dict[str, Any] | None = None
    if apply:
        rework = _queue_rework_task(
            row,
            chain_root=chain_root,
            next_round=next_round,
            pytest_result=pytest_result,
            tasks_path=tasks_path,
        )
    return {
        "task_id": task_id,
        "action": "rework_queued",
        "should_rework": True,
        "reason": "acceptance_pytest_failed",
        "verify_chain_root_id": chain_root,
        "verify_round": next_round,
        "max_verify_rounds": MAX_VERIFY_REWORK_ROUNDS,
        "rework_task_id": (rework or {}).get("id"),
        "pytest": pytest_result,
    }
