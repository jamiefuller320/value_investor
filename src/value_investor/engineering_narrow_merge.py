"""Independent verify + scoped auto-merge for narrow engineering PR classes.

Deterministic path/CI/tests gates (not a standing LLM listener). Each class is
opt-in via ``engineering.auto_merge.<class>``: ``off`` | ``observe`` | ``merge``.

Classes:

* ``ingest_narrow`` — task area ``ingest`` (#651-class)
* ``scoring_narrow`` — task area ``scoring`` (#653-class)
* ``compile_cap_drain`` — idle role-coherence / compile-cap drain tasks (any area;
  source ``compile_cap_drain``)

Shared rules: actual changed files stay within the task allowlist *and*
the CI-fix auto-merge safe prefixes, include a ``tests/`` path (configurable),
and stay under the path cap.
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
from value_investor.engineering_tasks import (
    EngineeringTask,
    path_matches_blocked_pattern,
)

NARROW_POLICY_VALUES = frozenset({"off", "observe", "merge"})

# merge_class → task areas that qualify (parked hunter always excluded).
# ``compile_cap_drain`` is source-gated in ``task_narrow_merge_class`` (any area).
NARROW_CLASS_AREAS: dict[str, frozenset[str]] = {
    "ingest_narrow": frozenset({"ingest"}),
    "scoring_narrow": frozenset({"scoring"}),
    "compile_cap_drain": frozenset(),
}

NARROW_MERGE_CLASSES: tuple[str, ...] = tuple(NARROW_CLASS_AREAS)

NARROW_CLASS_DEFAULT_POLICY: dict[str, str] = {
    "ingest_narrow": "merge",
    "scoring_narrow": "merge",
    "compile_cap_drain": "merge",
}

INDEPENDENTLY_VERIFIED_MERGE_CLASSES = frozenset(
    {
        "ingest_narrow",
        "scoring_narrow",
        "compile_cap_drain",
        "ci_fix",
        "parked_hunter",
    }
)

COMPILE_CAP_DRAIN_SOURCE = "compile_cap_drain"


@dataclass
class NarrowVerifyResult:
    ok: bool
    verdict: str
    reason: str
    merge_class: str | None = None
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


def is_parked_hunter(task: EngineeringTask) -> bool:
    from value_investor.hunter_auto_merge import is_parked_source_hunter_task

    return is_parked_source_hunter_task(task)


def _auto_merge_block() -> dict[str, Any]:
    from value_investor.agent_model_policy import load_policy

    return dict((load_policy().get("engineering") or {}).get("auto_merge") or {})


def narrow_policy(merge_class: str) -> str:
    block = _auto_merge_block()
    default = NARROW_CLASS_DEFAULT_POLICY.get(merge_class, "off")
    raw = str(block.get(merge_class) or default).strip().lower()
    return raw if raw in NARROW_POLICY_VALUES else "off"


def narrow_require_tests(merge_class: str) -> bool:
    block = _auto_merge_block()
    key = f"{merge_class}_require_tests"
    if key in block:
        return bool(block[key])
    if "narrow_require_tests" in block:
        return bool(block["narrow_require_tests"])
    return True


def task_narrow_merge_class(task: EngineeringTask) -> str | None:
    """Return the narrow merge class for this task, or None."""
    if is_parked_hunter(task):
        return None
    if str(task.source or "").strip() == COMPILE_CAP_DRAIN_SOURCE:
        return "compile_cap_drain"
    area = str(task.area or "").strip().lower()
    for merge_class, areas in NARROW_CLASS_AREAS.items():
        if merge_class == "compile_cap_drain":
            continue
        if area in areas:
            return merge_class
    return None


def task_is_narrow_candidate(task: EngineeringTask, *, merge_class: str | None = None) -> bool:
    found = task_narrow_merge_class(task)
    if found is None:
        return False
    if merge_class is None:
        return True
    return found == merge_class


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


def changed_files_eligible_for_narrow(
    changed_files: list[str],
    *,
    task: EngineeringTask,
    merge_class: str,
    require_tests: bool | None = None,
) -> tuple[bool, str]:
    """Gate on the *actual* PR diff, not the wide area allowlist stored on the task."""
    require_tests = narrow_require_tests(merge_class) if require_tests is None else require_tests
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
        return False, f"{merge_class} merge requires a tests/ path in the diff"
    return True, f"{merge_class} diff eligible"


def evaluate_narrow_verify(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    pr_number: int | None = None,
    merge_class: str | None = None,
    policy: str | None = None,
) -> NarrowVerifyResult:
    resolved_class = merge_class or task_narrow_merge_class(task)
    if resolved_class is None:
        return NarrowVerifyResult(
            ok=True,
            verdict="skipped",
            reason="not a narrow-merge candidate",
            task_id=task.id,
            pr_number=pr_number,
            changed_files=list(changed_files),
            policy="off",
        )

    policy_value = (policy or narrow_policy(resolved_class)).strip().lower()
    if policy_value not in NARROW_POLICY_VALUES:
        policy_value = "off"

    if not task_is_narrow_candidate(task, merge_class=resolved_class):
        return NarrowVerifyResult(
            ok=True,
            verdict="skipped",
            reason=f"not a {resolved_class} candidate",
            merge_class=resolved_class,
            task_id=task.id,
            pr_number=pr_number,
            changed_files=list(changed_files),
            policy=policy_value,
        )
    if policy_value == "off":
        return NarrowVerifyResult(
            ok=True,
            verdict="skipped",
            reason=f"{resolved_class} policy is off",
            merge_class=resolved_class,
            task_id=task.id,
            pr_number=pr_number,
            changed_files=list(changed_files),
            policy=policy_value,
        )

    from value_investor.engineering_narrow_scope import task_has_narrow_cohesion_bypass

    if task_has_narrow_cohesion_bypass(task):
        bypass_reason = str((task.evidence or {}).get("narrow_scope_reason") or "").strip()
        detail = bypass_reason or "coding objective needs a wider cohesive diff"
        return NarrowVerifyResult(
            ok=True,
            verdict="skipped",
            reason=f"narrow_cohesion_bypass — human merge ({detail})",
            merge_class=resolved_class,
            task_id=task.id,
            pr_number=pr_number,
            changed_files=list(changed_files),
            policy=policy_value,
        )

    eligible, reason = changed_files_eligible_for_narrow(
        changed_files, task=task, merge_class=resolved_class
    )
    if not eligible:
        return NarrowVerifyResult(
            ok=False,
            verdict="reject",
            reason=reason,
            merge_class=resolved_class,
            task_id=task.id,
            pr_number=pr_number,
            changed_files=list(changed_files),
            policy=policy_value,
        )

    verdict = "observe" if policy_value == "observe" else "approve"
    return NarrowVerifyResult(
        ok=True,
        verdict=verdict,
        reason=reason,
        merge_class=resolved_class,
        task_id=task.id,
        pr_number=pr_number,
        changed_files=list(changed_files),
        policy=policy_value,
    )


def narrow_merge_allowed(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    merge_class: str | None = None,
    policy: str | None = None,
) -> tuple[bool, str, str | None]:
    """Return whether evaluate_auto_merge may merge via a narrow class."""
    result = evaluate_narrow_verify(
        task=task,
        changed_files=changed_files,
        merge_class=merge_class,
        policy=policy,
    )
    if result.verdict == "approve" and result.ok:
        return True, f"{result.merge_class} approved: {result.reason}", result.merge_class
    if result.verdict == "observe" and result.ok:
        return (
            False,
            f"{result.merge_class} observe-only: {result.reason}",
            result.merge_class,
        )
    if result.verdict == "skipped":
        return False, result.reason, result.merge_class
    return False, result.reason, result.merge_class


def classify_merge_class(task: EngineeringTask | None, *, auto_merged: bool) -> str:
    if task is None:
        return "human"
    if is_parked_hunter(task) and auto_merged:
        return "parked_hunter"
    if str(getattr(task, "source", "") or "").strip() == COMPILE_CAP_DRAIN_SOURCE and auto_merged:
        return "compile_cap_drain"
    if bool(task.auto_merge) and auto_merged:
        return "ci_fix"
    narrow = task_narrow_merge_class(task)
    if narrow and auto_merged:
        return narrow
    if auto_merged:
        return "auto_other"
    return "human"


def ingest_narrow_policy() -> str:
    return narrow_policy("ingest_narrow")


def scoring_narrow_policy() -> str:
    return narrow_policy("scoring_narrow")


def task_is_ingest_narrow_candidate(task: EngineeringTask) -> bool:
    return task_is_narrow_candidate(task, merge_class="ingest_narrow")


def task_is_scoring_narrow_candidate(task: EngineeringTask) -> bool:
    return task_is_narrow_candidate(task, merge_class="scoring_narrow")


def evaluate_ingest_narrow_verify(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    pr_number: int | None = None,
    policy: str | None = None,
) -> NarrowVerifyResult:
    return evaluate_narrow_verify(
        task=task,
        changed_files=changed_files,
        pr_number=pr_number,
        merge_class="ingest_narrow",
        policy=policy,
    )


def evaluate_scoring_narrow_verify(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    pr_number: int | None = None,
    policy: str | None = None,
) -> NarrowVerifyResult:
    return evaluate_narrow_verify(
        task=task,
        changed_files=changed_files,
        pr_number=pr_number,
        merge_class="scoring_narrow",
        policy=policy,
    )


def ingest_narrow_merge_allowed(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    policy: str | None = None,
) -> tuple[bool, str]:
    allowed, reason, _cls = narrow_merge_allowed(
        task=task,
        changed_files=changed_files,
        merge_class="ingest_narrow",
        policy=policy,
    )
    return allowed, reason


def scoring_narrow_merge_allowed(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    policy: str | None = None,
) -> tuple[bool, str]:
    allowed, reason, _cls = narrow_merge_allowed(
        task=task,
        changed_files=changed_files,
        merge_class="scoring_narrow",
        policy=policy,
    )
    return allowed, reason


def _parse_iso_day(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return (
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            .astimezone(UTC)
            .date()
            .isoformat()
        )
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
                "independently_verified": merge_class in INDEPENDENTLY_VERIFIED_MERGE_CLASSES,
            }
        )
    rows.sort(key=lambda row: str(row.get("merged_at") or ""), reverse=True)
    return rows
