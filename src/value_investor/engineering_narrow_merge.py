"""Independent verify + scoped auto-merge for narrow ingest engineering PRs.

This is the #651-class gate: task area ``ingest``, actual changed files stay
within the task allowlist *and* the CI-fix auto-merge safe prefixes, include a
test file, and stay under the path cap. Policy is independent of the authoring
agent (deterministic path/CI gate — not a standing LLM listener).

Policy knobs (``engineering.auto_merge``):

* ``ingest_narrow``: ``off`` | ``observe`` | ``merge`` (default ``merge``)
* ``ingest_narrow_require_tests``: require at least one ``tests/`` path (default true)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.ci_fix_tasks import (
    AUTO_MERGE_MAX_PATHS,
    task_allowed_paths_eligible_for_auto_merge,
)
from value_investor.engineering_tasks import EngineeringTask, path_matches_blocked_pattern

MERGE_CLASS = "ingest_narrow"
INGEST_NARROW_AREAS = frozenset({"ingest"})
INGEST_NARROW_POLICY_VALUES = frozenset({"off", "observe", "merge"})


@dataclass
class IngestNarrowVerifyResult:
    ok: bool
    verdict: str
    reason: str
    merge_class: str = MERGE_CLASS
    task_id: str | None = None
    pr_number: int | None = None
    changed_files: list[str] = field(default_factory=list)
    policy: str = "off"
    deterministic_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": self.ok,
            "verdict": self.verdict,
            "reason": self.reason,
            "merge_class": self.merge_class,
            "task_id": self.task_id,
            "pr_number": self.pr_number,
            "changed_files": list(self.changed_files),
            "policy": self.policy,
            "deterministic_only": self.deterministic_only,
            "completed_at": datetime.now(UTC).isoformat(),
        }


def ingest_narrow_policy() -> str:
    from value_investor.agent_model_policy import load_policy

    block = ((load_policy().get("engineering") or {}).get("auto_merge") or {})
    raw = str(block.get("ingest_narrow") or "merge").strip().lower()
    return raw if raw in INGEST_NARROW_POLICY_VALUES else "off"


def ingest_narrow_require_tests() -> bool:
    from value_investor.agent_model_policy import load_policy

    block = ((load_policy().get("engineering") or {}).get("auto_merge") or {})
    value = block.get("ingest_narrow_require_tests")
    if value is None:
        return True
    return bool(value)


def task_is_ingest_narrow_candidate(task: EngineeringTask) -> bool:
    """True when the task belongs to the ingest-narrow class (ignores auto_merge flag)."""
    if is_parked_hunter(task):
        return False
    area = str(task.area or "").strip().lower()
    return area in INGEST_NARROW_AREAS


def is_parked_hunter(task: EngineeringTask) -> bool:
    from value_investor.hunter_auto_merge import is_parked_source_hunter_task

    return is_parked_source_hunter_task(task)


def changed_files_eligible_for_ingest_narrow(
    changed_files: list[str],
    *,
    task: EngineeringTask,
    require_tests: bool | None = None,
) -> tuple[bool, str]:
    """Gate on the *actual* PR diff, not the wide area allowlist stored on the task."""
    require_tests = ingest_narrow_require_tests() if require_tests is None else require_tests
    changed = [str(path).strip().removeprefix("./") for path in changed_files if str(path).strip()]
    if not changed:
        return False, "no changed files"
    if len(changed) > AUTO_MERGE_MAX_PATHS:
        return False, f"too many changed files ({len(changed)} > {AUTO_MERGE_MAX_PATHS})"
    if not task_allowed_paths_eligible_for_auto_merge(changed):
        return False, "changed files fail CI-fix safe-prefix / blocked-path checks"
    allowed = [str(path).strip() for path in (task.allowed_paths or []) if str(path).strip()]
    if not allowed:
        return False, "task has no allowed_paths"
    for path in changed:
        if not _path_within_allowlist(path, allowed):
            return False, f"outside task allowed_paths: {path}"
        for blocked in task.blocked_paths or []:
            if path_matches_blocked_pattern(path, blocked):
                return False, f"touches blocked path: {path}"
    if require_tests and not any(path.startswith("tests/") for path in changed):
        return False, "narrow ingest merge requires a tests/ path in the diff"
    return True, "narrow ingest diff eligible"


def _path_within_allowlist(path: str, allowed: list[str]) -> bool:
    for entry in allowed:
        if not entry:
            continue
        if entry.endswith("/"):
            if path.startswith(entry) or path.startswith(entry.rstrip("/")):
                return True
        elif path == entry or path.startswith(f"{entry.rstrip('/')}/"):
            return True
    return False


def evaluate_ingest_narrow_verify(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    pr_number: int | None = None,
    policy: str | None = None,
) -> IngestNarrowVerifyResult:
    policy_value = (policy or ingest_narrow_policy()).strip().lower()
    if policy_value not in INGEST_NARROW_POLICY_VALUES:
        policy_value = "off"

    if not task_is_ingest_narrow_candidate(task):
        return IngestNarrowVerifyResult(
            ok=True,
            verdict="skipped",
            reason="not an ingest-narrow candidate",
            task_id=task.id,
            pr_number=pr_number,
            changed_files=list(changed_files),
            policy=policy_value,
        )
    if policy_value == "off":
        return IngestNarrowVerifyResult(
            ok=True,
            verdict="skipped",
            reason="ingest_narrow policy is off",
            task_id=task.id,
            pr_number=pr_number,
            changed_files=list(changed_files),
            policy=policy_value,
        )

    eligible, reason = changed_files_eligible_for_ingest_narrow(changed_files, task=task)
    if not eligible:
        return IngestNarrowVerifyResult(
            ok=False,
            verdict="reject",
            reason=reason,
            task_id=task.id,
            pr_number=pr_number,
            changed_files=list(changed_files),
            policy=policy_value,
        )

    verdict = "observe" if policy_value == "observe" else "approve"
    return IngestNarrowVerifyResult(
        ok=True,
        verdict=verdict,
        reason=reason,
        task_id=task.id,
        pr_number=pr_number,
        changed_files=list(changed_files),
        policy=policy_value,
    )


def ingest_narrow_merge_allowed(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    policy: str | None = None,
) -> tuple[bool, str]:
    """Return whether evaluate_auto_merge may merge via the ingest_narrow class."""
    result = evaluate_ingest_narrow_verify(
        task=task, changed_files=changed_files, policy=policy
    )
    if result.verdict == "approve" and result.ok:
        return True, f"ingest_narrow approved: {result.reason}"
    if result.verdict == "observe" and result.ok:
        return False, f"ingest_narrow observe-only: {result.reason}"
    if result.verdict == "skipped":
        return False, result.reason
    return False, result.reason


def classify_merge_class(task: EngineeringTask | None, *, auto_merged: bool) -> str:
    if task is None:
        return "human"
    if is_parked_hunter(task) and auto_merged:
        return "parked_hunter"
    if bool(task.auto_merge) and auto_merged:
        return "ci_fix"
    if task_is_ingest_narrow_candidate(task) and auto_merged:
        return MERGE_CLASS
    if auto_merged:
        return "auto_other"
    return "human"


def _parse_iso_day(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC).date().isoformat()
    except ValueError:
        return None


def list_todays_engineering_merges(
    *,
    tasks_path: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return engineering tasks merged today (UTC) for EOD digest / dashboard / email."""
    from value_investor.engineering_tasks import COMMITTED_TASKS_PATH, load_engineering_tasks

    now = now or datetime.now(UTC)
    today = now.astimezone(UTC).date().isoformat()
    path = Path(tasks_path) if tasks_path is not None else COMMITTED_TASKS_PATH
    payload = load_engineering_tasks(path)
    rows: list[dict[str, Any]] = []
    for raw in payload.get("tasks") or []:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "")
        if status not in {"merged", "completed"}:
            continue
        merged_day = _parse_iso_day(str(raw.get("merged_at") or ""))
        if merged_day != today:
            continue
        evidence = dict(raw.get("evidence") or {})
        merge_class = str(
            evidence.get("merge_class")
            or raw.get("merge_class")
            or ("ci_fix" if raw.get("auto_merge") else "human")
        )
        rows.append(
            {
                "task_id": str(raw.get("id") or ""),
                "title": str(raw.get("title") or ""),
                "area": str(raw.get("area") or ""),
                "pr_number": raw.get("pr_number"),
                "pr_url": raw.get("pr_url"),
                "merged_at": raw.get("merged_at"),
                "merge_class": merge_class,
                "auto_merge": bool(raw.get("auto_merge")),
                "independently_verified": merge_class
                in {MERGE_CLASS, "ci_fix", "parked_hunter"},
            }
        )
    rows.sort(key=lambda row: str(row.get("merged_at") or ""), reverse=True)
    return rows
