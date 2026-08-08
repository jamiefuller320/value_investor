"""Auto-merge engineering PRs when CI is green and the diff stays in scope."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from value_investor.engineering_queue import is_engineering_branch, task_id_from_branch
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    find_engineering_task,
    validate_engineering_pr_paths,
)
from value_investor.ci_fix_tasks import task_eligible_for_auto_merge

GITHUB_API_VERSION = "2022-11-28"


@dataclass
class AutoMergeDecision:
    should_merge: bool
    reason: str
    task_id: str | None = None
    pr_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_merge": self.should_merge,
            "reason": self.reason,
            "task_id": self.task_id,
            "pr_number": self.pr_number,
        }


def _github_token() -> str | None:
    from value_investor.workflow_pat import resolve_workflow_dispatch_pat

    pat = resolve_workflow_dispatch_pat()
    if pat:
        return pat
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value
    return None


def _github_repo() -> str | None:
    value = os.environ.get("GITHUB_REPOSITORY")
    if value and "/" in value:
        return value
    return None


def _api_get(path: str, *, token: str) -> Any:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _api_request(method: str, path: str, *, token: str, payload: dict | None = None) -> Any:
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def _run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def find_open_pr_for_branch(branch: str, *, repo: str | None = None) -> dict[str, Any] | None:
    repo = repo or _github_repo()
    if not repo:
        return None
    result = _run_gh(["pr", "list", "--head", branch, "--base", "main", "--state", "open", "--json", "number,title,isDraft,headRefName"])
    if result.returncode != 0:
        return None
    rows = json.loads(result.stdout or "[]")
    return rows[0] if rows else None


def pr_checks_successful(pr_number: int, *, repo: str | None = None) -> tuple[bool, str]:
    repo = repo or _github_repo()
    if not repo:
        return False, "GITHUB_REPOSITORY not set"
    result = _run_gh(["pr", "checks", str(pr_number), "--json", "name,state,conclusion"])
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "gh pr checks failed").strip()
    checks = json.loads(result.stdout or "[]")
    if not checks:
        return False, "no PR checks reported yet"
    pending = [row for row in checks if str(row.get("state") or "").upper() != "COMPLETED"]
    if pending:
        names = ", ".join(str(row.get("name") or "") for row in pending[:3])
        return False, f"checks still pending: {names}"
    failed = [
        row
        for row in checks
        if str(row.get("conclusion") or row.get("state") or "").lower() not in {"success", "skipped", "neutral"}
    ]
    if failed:
        names = ", ".join(str(row.get("name") or "") for row in failed[:3])
        return False, f"checks not green: {names}"
    return True, "all checks green"


def changed_files_for_pr(pr_number: int, *, repo: str | None = None) -> list[str]:
    repo = repo or _github_repo()
    token = _github_token()
    if not repo or not token:
        return []
    owner, name = repo.split("/", 1)
    payload = _api_get(f"/repos/{owner}/{name}/pulls/{pr_number}/files?per_page=100", token=token)
    if not isinstance(payload, list):
        return []
    return [str(row.get("filename") or "") for row in payload if row.get("filename")]


def evaluate_auto_merge(
    *,
    branch: str,
    tasks_path=COMMITTED_TASKS_PATH,
    repo: str | None = None,
) -> AutoMergeDecision:
    branch = branch.strip()
    if not is_engineering_branch(branch):
        return AutoMergeDecision(False, "not an engineering task branch", pr_number=None)

    task_id = task_id_from_branch(branch)
    if not task_id:
        return AutoMergeDecision(False, "could not parse task id from branch", pr_number=None)

    task = find_engineering_task(task_id, path=tasks_path)
    if task is None:
        return AutoMergeDecision(False, f"unknown task {task_id}", task_id=task_id)
    if str(task.status) != "pr_open":
        return AutoMergeDecision(
            False,
            f"task status is {task.status!r}, expected pr_open",
            task_id=task_id,
        )
    if not task_eligible_for_auto_merge(task):
        return AutoMergeDecision(
            False,
            "task is not eligible for auto-merge (auto_merge=false or scope too broad)",
            task_id=task_id,
        )

    pr = find_open_pr_for_branch(branch, repo=repo)
    if pr is None:
        return AutoMergeDecision(False, "no open PR for branch", task_id=task_id)
    pr_number = int(pr["number"])

    checks_ok, checks_reason = pr_checks_successful(pr_number, repo=repo)
    if not checks_ok:
        return AutoMergeDecision(False, checks_reason, task_id=task_id, pr_number=pr_number)

    changed = changed_files_for_pr(pr_number, repo=repo)
    guard = validate_engineering_pr_paths(task=task, changed_files=changed)
    if not guard.ok:
        return AutoMergeDecision(
            False,
            f"path guard failed: {'; '.join(guard.violations[:3])}",
            task_id=task_id,
            pr_number=pr_number,
        )

    return AutoMergeDecision(
        True,
        "CI green and diff within allowed_paths",
        task_id=task_id,
        pr_number=pr_number,
    )


def perform_auto_merge(
    decision: AutoMergeDecision,
    *,
    repo: str | None = None,
) -> tuple[bool, str]:
    if not decision.should_merge or decision.pr_number is None:
        return False, decision.reason

    pr_number = decision.pr_number
    pr = _run_gh(["pr", "view", str(pr_number), "--json", "isDraft,mergeable,state"])
    if pr.returncode != 0:
        return False, pr.stderr or pr.stdout or "gh pr view failed"
    payload = json.loads(pr.stdout or "{}")
    if str(payload.get("state") or "").upper() != "OPEN":
        return False, f"PR #{pr_number} is not open"
    if payload.get("isDraft"):
        ready = _run_gh(["pr", "ready", str(pr_number)])
        if ready.returncode != 0:
            return False, ready.stderr or ready.stdout or "gh pr ready failed"

    merge = _run_gh(
        [
            "pr",
            "merge",
            str(pr_number),
            "--squash",
            "--delete-branch",
            "--subject",
            f"feat(engineering): auto-merge {decision.task_id}",
        ]
    )
    if merge.returncode != 0:
        return False, merge.stderr or merge.stdout or "gh pr merge failed"
    return True, f"merged PR #{pr_number}"
