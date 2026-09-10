"""Preflight clash detection and local checks for the engineering queue.

Compares candidate tasks and branches against open PRs for file overlap, shared
mutable paths, allowlist overlap, and optional git merge-tree conflicts. Supports
dispatch overtaking: walk priority order and skip blocked tasks.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from value_investor.committed_data_json import check_path
from value_investor.engineering_auto_merge import changed_files_for_pr
from value_investor.engineering_tasks import (
    EngineeringTask,
    allowed_paths_overlap,
    effective_allowed_paths,
    normalize_repo_path,
    validate_engineering_pr_paths,
)
from value_investor.engineering_verify import (
    default_pytest_runner,
    preflight_pytest_paths,
)
from value_investor.python_quality import git_changed_files, run_ruff_on_files

logger = logging.getLogger(__name__)

_ENGINEERING_BRANCH_RE = re.compile(r"^cursor/(eng-\d{8}-\d{2})-1de3$")


def task_id_from_branch(branch: str) -> str | None:
    match = _ENGINEERING_BRANCH_RE.match(branch.strip())
    return match.group(1) if match else None


def engineering_branch_for_task_id(task_id: str) -> str | None:
    token = str(task_id or "").strip()
    if not token:
        return None
    branch = f"cursor/{token}-1de3"
    return branch if _ENGINEERING_BRANCH_RE.match(branch) else None


# Files that must not be edited concurrently across open engineering PRs.
SHARED_MUTABLE_FILES: frozenset[str] = frozenset(
    {
        "docs/data/engineering_tasks.json",
        "docs/data/library/policy.json",
        "docs/data/automation.json",
        "docs/data/latest.json",
    }
)

CLASH_KIND_ALLOWLIST = "allowlist_overlap"
CLASH_KIND_FILE = "file_overlap"
CLASH_KIND_SHARED = "shared_mutable"
CLASH_KIND_MERGE_TREE = "merge_tree"


def dispatch_merge_tree_enabled() -> bool:
    """When true, hourly dispatch also runs git merge-tree clash checks."""
    return os.environ.get("ENGINEERING_DISPATCH_MERGE_TREE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


@dataclass
class ClashBlocker:
    pr_number: int | None
    branch: str | None
    task_id: str | None
    title: str | None
    clash_files: list[str]
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pr_number": self.pr_number,
            "branch": self.branch,
            "task_id": self.task_id,
            "title": self.title,
            "clash_files": list(self.clash_files),
            "kind": self.kind,
        }


@dataclass
class TaskDispatchReport:
    task: EngineeringTask
    dispatch_eligible: bool
    blocked_by: list[ClashBlocker] = field(default_factory=list)
    estimated_files: list[str] = field(default_factory=list)
    effective_dispatch_rank: int | None = None
    clash_scan: str = "full"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task.id,
            "dispatch_eligible": self.dispatch_eligible,
            "blocked_by": [row.to_dict() for row in self.blocked_by],
            "estimated_files": list(self.estimated_files),
            "effective_dispatch_rank": self.effective_dispatch_rank,
            "clash_scan": self.clash_scan,
        }


@dataclass
class PreflightCheck:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass
class PreflightReport:
    task_id: str
    ok: bool
    checks: list[PreflightCheck] = field(default_factory=list)
    clash: TaskDispatchReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "ok": self.ok,
            "checks": [row.to_dict() for row in self.checks],
            "clash": self.clash.to_dict() if self.clash else None,
        }


def _normalize_files(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in paths:
        token = normalize_repo_path(str(raw or ""))
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def file_overlap(files_a: list[str], files_b: list[str]) -> list[str]:
    left = set(_normalize_files(files_a))
    right = set(_normalize_files(files_b))
    return sorted(left & right)


def estimated_task_files(task: EngineeringTask, *, include_shared: bool = True) -> list[str]:
    """Conservative changed-file estimate when no branch diff exists yet."""
    paths = _normalize_files(effective_allowed_paths(task))
    if include_shared:
        for shared in sorted(SHARED_MUTABLE_FILES):
            if shared not in paths:
                paths.append(shared)
    return paths


def git_changed_files_vs_main(
    branch: str,
    *,
    base_ref: str = "origin/main",
    repo_root: Path | None = None,
) -> list[str]:
    """Return paths changed on ``branch`` relative to ``base_ref``."""
    head = branch.strip()
    if not head:
        return []
    cwd = str(repo_root) if repo_root is not None else None
    for ref_pair in (f"{base_ref}...{head}", f"{base_ref}...origin/{head}"):
        proc = subprocess.run(
            ["git", "diff", "--name-only", ref_pair],
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return _normalize_files(proc.stdout.splitlines())
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if proc.returncode != 0:
        return []
    return _normalize_files(proc.stdout.splitlines())


def git_refs_exist(*refs: str, repo_root: Path | None = None) -> bool:
    cwd = str(repo_root) if repo_root is not None else None
    for ref in refs:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", ref],
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        if proc.returncode != 0:
            return False
    return True


def git_merge_tree_conflicts(
    ref_a: str,
    ref_b: str,
    *,
    repo_root: Path | None = None,
) -> bool:
    """Return True when merging ref_b into ref_a would produce conflicts."""
    cwd = str(repo_root) if repo_root is not None else None
    base_proc = subprocess.run(
        ["git", "merge-base", ref_a, ref_b],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if base_proc.returncode != 0 or not base_proc.stdout.strip():
        return False
    base = base_proc.stdout.strip()
    proc = subprocess.run(
        ["git", "merge-tree", base, ref_a, ref_b],
        check=False,
        capture_output=True,
        cwd=cwd,
    )
    raw = (proc.stdout or b"") + (proc.stderr or b"")
    if b"CONFLICT" in raw or b"<<<<<<<" in raw:
        return True
    text = raw.decode("utf-8", errors="replace")
    if "CONFLICT" in text.upper():
        return True
    return proc.returncode not in {0, None}


def _pr_row_branch(row: dict[str, Any]) -> str:
    return str(row.get("headRefName") or row.get("head_branch") or "").strip()


def _pr_row_number(row: dict[str, Any]) -> int | None:
    raw = row.get("number")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def resolve_pr_changed_files(
    pr_row: dict[str, Any],
    *,
    repo: str | None = None,
    cache: dict[int, list[str]] | None = None,
) -> list[str]:
    number = _pr_row_number(pr_row)
    if number is None:
        return []
    store = cache if cache is not None else {}
    if number in store:
        return list(store[number])
    files = _normalize_files(changed_files_for_pr(number, repo=repo))
    store[number] = files
    return files


def build_open_pr_file_index(
    open_prs: list[dict[str, Any]] | None,
    *,
    repo: str | None = None,
    cache: dict[int, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Enrich open PR rows with changed file lists."""
    enriched: list[dict[str, Any]] = []
    for row in open_prs or []:
        branch = _pr_row_branch(row)
        number = _pr_row_number(row)
        files = resolve_pr_changed_files(row, repo=repo, cache=cache) if number else []
        enriched.append(
            {
                "number": number,
                "branch": branch,
                "title": str(row.get("title") or ""),
                "task_id": task_id_from_branch(branch) if branch else None,
                "changed_files": files,
            }
        )
    return enriched


def _blocker_from_pr(
    pr: dict[str, Any],
    *,
    clash_files: list[str],
    kind: str,
) -> ClashBlocker:
    return ClashBlocker(
        pr_number=pr.get("number"),
        branch=pr.get("branch"),
        task_id=pr.get("task_id"),
        title=pr.get("title"),
        clash_files=list(clash_files),
        kind=kind,
    )


def predict_task_clashes(
    task: EngineeringTask,
    *,
    occupied_paths: list[str],
    open_pr_index: list[dict[str, Any]],
    candidate_files: list[str] | None = None,
    candidate_branch: str | None = None,
    occupied_files: set[str] | None = None,
    repo_root: Path | None = None,
    skip_merge_tree: bool = False,
    clash_scan: str = "full",
) -> TaskDispatchReport:
    """Return whether ``task`` can dispatch without clashing with in-flight work."""
    branch = (candidate_branch or str(task.branch_name or "").strip() or "").strip()

    files = _normalize_files(candidate_files or [])
    if not files and branch:
        files = git_changed_files_vs_main(branch, repo_root=repo_root)
    if not files:
        # Without a branch diff, avoid assuming every task will touch shared queue JSON.
        files = estimated_task_files(task, include_shared=False)

    blocked_by: list[ClashBlocker] = []
    task_paths = effective_allowed_paths(task)

    if occupied_files:
        overlap = file_overlap(files, sorted(occupied_files))
        if overlap:
            shared = [path for path in overlap if path in SHARED_MUTABLE_FILES]
            kind = CLASH_KIND_SHARED if shared else CLASH_KIND_FILE
            blocked_by.append(
                ClashBlocker(
                    pr_number=None,
                    branch=None,
                    task_id=None,
                    title="in-flight file overlap (batch dispatch)",
                    clash_files=overlap,
                    kind=kind,
                )
            )

    if occupied_paths and task_paths and allowed_paths_overlap(task_paths, occupied_paths):
        overlap_paths = [
            path
            for path in task_paths
            if any(allowed_paths_overlap([path], [occupied]) for occupied in occupied_paths)
        ]
        blocked_by.append(
            ClashBlocker(
                pr_number=None,
                branch=None,
                task_id=None,
                title="in-flight allowlist overlap",
                clash_files=overlap_paths[:5],
                kind=CLASH_KIND_ALLOWLIST,
            )
        )

    for pr in open_pr_index:
        pr_branch = str(pr.get("branch") or "")
        if pr_branch and branch and pr_branch == branch:
            continue
        pr_files = list(pr.get("changed_files") or [])
        overlap = file_overlap(files, pr_files)
        if overlap:
            shared = [path for path in overlap if path in SHARED_MUTABLE_FILES]
            kind = CLASH_KIND_SHARED if shared else CLASH_KIND_FILE
            blocked_by.append(
                _blocker_from_pr(pr, clash_files=overlap, kind=kind),
            )
            continue
        if (
            not skip_merge_tree
            and clash_scan == "full"
            and branch
            and pr_branch
            and git_refs_exist(f"origin/{branch}", f"origin/{pr_branch}", repo_root=repo_root)
            and git_merge_tree_conflicts(
                f"origin/{branch}",
                f"origin/{pr_branch}",
                repo_root=repo_root,
            )
        ):
            blocked_by.append(
                _blocker_from_pr(
                    pr,
                    clash_files=[],
                    kind=CLASH_KIND_MERGE_TREE,
                )
            )

    return TaskDispatchReport(
        task=task,
        dispatch_eligible=not blocked_by,
        blocked_by=blocked_by,
        estimated_files=files,
        clash_scan=clash_scan,
    )


def build_task_dispatch_reports(
    data: dict[str, Any],
    *,
    blocked_paths: list[str] | None = None,
    open_prs: list[dict[str, Any]] | None = None,
    repo: str | None = None,
    repo_root: Path | None = None,
    skip_merge_tree: bool = False,
) -> list[TaskDispatchReport]:
    """Dispatch reports for every open task, in priority order."""
    from value_investor.engineering_tasks import select_engineering_tasks

    clash_scan = "partial" if not open_prs else "full"
    cache: dict[int, list[str]] = {}
    pr_index = build_open_pr_file_index(open_prs, repo=repo, cache=cache)
    occupied = list(blocked_paths or [])
    reports: list[TaskDispatchReport] = []

    for task in select_engineering_tasks(data, max_tasks=999):
        report = predict_task_clashes(
            task,
            occupied_paths=occupied,
            open_pr_index=pr_index,
            candidate_branch=str(task.branch_name or "").strip() or None,
            repo_root=repo_root,
            skip_merge_tree=skip_merge_tree,
            clash_scan=clash_scan,
        )
        reports.append(report)
    return reports


def select_clash_aware_dispatch_tasks(
    data: dict[str, Any],
    *,
    max_tasks: int,
    blocked_paths: list[str] | None = None,
    open_prs: list[dict[str, Any]] | None = None,
    repo: str | None = None,
    repo_root: Path | None = None,
    skip_merge_tree: bool = False,
) -> tuple[list[EngineeringTask], list[TaskDispatchReport]]:
    """Pick highest-priority open tasks that are not blocked by clashes."""
    clash_scan = "partial" if not open_prs else "full"
    cache: dict[int, list[str]] = {}
    pr_index = build_open_pr_file_index(open_prs, repo=repo, cache=cache)
    occupied_paths = list(blocked_paths or [])
    occupied_files: set[str] = set()
    for pr in pr_index:
        occupied_files.update(pr.get("changed_files") or [])

    selected: list[EngineeringTask] = []
    all_reports: list[TaskDispatchReport] = []
    rank = 0

    from value_investor.engineering_tasks import select_engineering_tasks

    for task in select_engineering_tasks(data, max_tasks=999):
        branch = str(task.branch_name or "").strip()
        files = git_changed_files_vs_main(branch, repo_root=repo_root) if branch else []
        if not files:
            files = estimated_task_files(task, include_shared=False)

        report = predict_task_clashes(
            task,
            occupied_paths=occupied_paths,
            open_pr_index=pr_index,
            candidate_files=files,
            candidate_branch=branch or None,
            occupied_files=occupied_files,
            repo_root=repo_root,
            skip_merge_tree=skip_merge_tree,
            clash_scan=clash_scan,
        )
        all_reports.append(report)

        if not report.dispatch_eligible:
            continue

        rank += 1
        report.effective_dispatch_rank = rank
        selected.append(task)
        for path in effective_allowed_paths(task):
            if path not in occupied_paths:
                occupied_paths.append(path)
        occupied_files.update(files)

        if len(selected) >= max(0, int(max_tasks)):
            break

    return selected, all_reports


def annotate_dispatch_ranks(reports: list[TaskDispatchReport]) -> None:
    """Set effective_dispatch_rank on eligible reports in priority order."""
    rank = 0
    for report in reports:
        if report.dispatch_eligible:
            rank += 1
            report.effective_dispatch_rank = rank
        else:
            report.effective_dispatch_rank = None


def run_local_preflight(
    task: EngineeringTask,
    *,
    changed_files: list[str],
    open_prs: list[dict[str, Any]] | None = None,
    branch: str | None = None,
    base_ref: str = "origin/main",
    head_ref: str = "HEAD",
    repo: str | None = None,
    repo_root: Path | None = None,
    skip_pytest: bool = False,
    skip_clash: bool = False,
    skip_merge_tree: bool = False,
    pytest_runner=default_pytest_runner,
) -> PreflightReport:
    """Run path guard, ruff, JSON sanity, scoped pytest, and clash checks."""
    checks: list[PreflightCheck] = []
    normalized = _normalize_files(changed_files)

    guard = validate_engineering_pr_paths(task=task, changed_files=normalized)
    checks.append(
        PreflightCheck(
            name="path_guard",
            ok=guard.ok,
            detail="ok" if guard.ok else "; ".join(guard.violations[:5]),
        )
    )

    py_paths = [
        Path(path)
        for path in normalized
        if path.endswith(".py") and (path.startswith("src/") or path.startswith("tests/"))
    ]
    if py_paths:
        rc, logs = run_ruff_on_files(py_paths)
        checks.append(
            PreflightCheck(
                name="ruff",
                ok=rc == 0,
                detail="; ".join(logs[-3:])[:500],
            )
        )
    else:
        try:
            diff_py = git_changed_files(base_ref=base_ref, head_ref=head_ref, repo_root=repo_root)
            if diff_py:
                rc, logs = run_ruff_on_files(diff_py)
                checks.append(
                    PreflightCheck(
                        name="ruff",
                        ok=rc == 0,
                        detail="; ".join(logs[-3:])[:500],
                    )
                )
            else:
                checks.append(PreflightCheck(name="ruff", ok=True, detail="no python changes"))
        except RuntimeError as exc:
            checks.append(PreflightCheck(name="ruff", ok=True, detail=f"skipped: {exc}"))

    json_paths = [path for path in normalized if path.endswith(".json")]
    json_errors: list[str] = []
    root = repo_root or Path.cwd()
    for path in json_paths:
        json_errors.extend(check_path(root / path))
    checks.append(
        PreflightCheck(
            name="committed_json",
            ok=not json_errors,
            detail="ok" if not json_errors else "; ".join(json_errors[:5]),
        )
    )

    if skip_pytest:
        checks.append(PreflightCheck(name="pytest", ok=True, detail="skipped"))
    else:
        test_paths = preflight_pytest_paths(task, normalized)
        if test_paths:
            result = pytest_runner(test_paths, root)
            checks.append(
                PreflightCheck(
                    name="pytest",
                    ok=bool(result.get("ok")),
                    detail=str(result.get("output") or "")[:500],
                )
            )
        else:
            checks.append(PreflightCheck(name="pytest", ok=True, detail="no acceptance test paths"))

    clash_report: TaskDispatchReport | None = None
    if not skip_clash:
        pr_index = build_open_pr_file_index(open_prs, repo=repo)
        clash_report = predict_task_clashes(
            task,
            occupied_paths=[],
            open_pr_index=pr_index,
            candidate_files=normalized,
            candidate_branch=branch,
            repo_root=repo_root,
            skip_merge_tree=skip_merge_tree,
        )
        checks.append(
            PreflightCheck(
                name="clash",
                ok=clash_report.dispatch_eligible,
                detail=(
                    "ok"
                    if clash_report.dispatch_eligible
                    else "; ".join(
                        f"#{b.pr_number or '?'} {b.kind} {','.join(b.clash_files[:3])}"
                        for b in clash_report.blocked_by[:3]
                    )
                ),
            )
        )

    ok = all(row.ok for row in checks)
    return PreflightReport(task_id=task.id, ok=ok, checks=checks, clash=clash_report)


def clash_report_for_queue(
    data: dict[str, Any],
    *,
    blocked_paths: list[str] | None = None,
    open_prs: list[dict[str, Any]] | None = None,
    repo: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Summary clash report for dashboard / CLI."""
    reports = build_task_dispatch_reports(
        data,
        blocked_paths=blocked_paths,
        open_prs=open_prs,
        repo=repo,
        repo_root=repo_root,
    )
    annotate_dispatch_ranks(reports)
    eligible = [row for row in reports if row.dispatch_eligible]
    blocked = [row for row in reports if not row.dispatch_eligible]
    return {
        "open_task_count": len(reports),
        "dispatch_eligible_count": len(eligible),
        "blocked_count": len(blocked),
        "tasks": [row.to_dict() for row in reports],
    }
