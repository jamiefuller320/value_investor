"""Deterministic auto-merge gates for parked-source hunter engineering PRs."""

from __future__ import annotations

import ast
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import load_policy
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    PARKED_SOURCE_HUNTER_SOURCE,
    EngineeringTask,
    find_engineering_task,
    load_engineering_tasks,
    mark_task_status,
    validate_engineering_pr_paths,
)

HUNTER_AUTO_MERGE_ALLOWED_FILES = frozenset(
    {
        "src/value_investor/research/filings.py",
        "tests/test_research_filings.py",
        "docs/data/engineering_tasks.json",
    }
)
HUNTER_MAX_NEW_URLS = 3
HUNTER_MIN_SKIP_REASON_CHARS = 20
HUNTER_TEST_NAME_RE = re.compile(r"^def (test_parked_source_hunter_[a-z0-9_]+)\(", re.MULTILINE)


class HunterOutcome(StrEnum):
    SKIP = "skip"
    ALLOWLIST = "allowlist"
    UNKNOWN = "unknown"


class HunterResolution(StrEnum):
    SKIP = "skip"
    ALLOWLIST = "allowlist"


class HunterFixKind(StrEnum):
    MISSING_TEST = "missing_test"
    SHORT_SKIP = "short_skip"
    LIVE_FETCH_FAILED = "live_fetch_failed"


HUNTER_FIXABLE_KINDS = frozenset(HunterFixKind)


@dataclass
class HunterDiffAnalysis:
    outcome: HunterOutcome
    hunter_ticker: str
    new_skip_reason: str | None = None
    new_urls: list[str] | None = None
    added_test_names: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "hunter_ticker": self.hunter_ticker,
            "new_skip_reason": self.new_skip_reason,
            "new_urls": list(self.new_urls or []),
            "added_test_names": list(self.added_test_names or []),
        }


@dataclass
class HunterGateResult:
    ok: bool
    reason: str
    analysis: HunterDiffAnalysis | None = None
    tier: str | None = None
    fix_kind: HunterFixKind | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "reason": self.reason,
            "tier": self.tier,
            "fix_kind": self.fix_kind.value if self.fix_kind else None,
        }
        if self.analysis is not None:
            payload["analysis"] = self.analysis.to_dict()
        return payload


def is_parked_source_hunter_task(task: EngineeringTask | dict[str, Any] | None) -> bool:
    if task is None:
        return False
    source = task.source if isinstance(task, EngineeringTask) else str(task.get("source") or "")
    return source == PARKED_SOURCE_HUNTER_SOURCE


def hunter_task_ticker(task: EngineeringTask | dict[str, Any]) -> str:
    evidence = task.evidence if isinstance(task, EngineeringTask) else (task.get("evidence") or {})
    return str(evidence.get("hunter_ticker") or "").strip().upper()


def _engineering_policy() -> dict[str, Any]:
    policy = load_policy()
    block = policy.get("engineering")
    return dict(block) if isinstance(block, dict) else {}


def hunter_auto_merge_policy_tier() -> str:
    """Return off | skip | allowlist from policy.engineering.auto_merge.parked_hunter."""
    auto_merge = _engineering_policy().get("auto_merge") or {}
    tier = str(auto_merge.get("parked_hunter") or "off").strip().lower()
    if tier not in {"off", "skip", "allowlist"}:
        return "off"
    return tier


def hunter_verify_observer_enabled() -> bool:
    auto_merge = _engineering_policy().get("auto_merge") or {}
    value = auto_merge.get("parked_hunter_verify_observer")
    if value is None:
        return True
    return bool(value)


def _hunter_fix_policy() -> dict[str, Any]:
    auto_merge = _engineering_policy().get("auto_merge") or {}
    block = auto_merge.get("hunter_fix") or {}
    return dict(block) if isinstance(block, dict) else {}


def hunter_fix_enabled() -> bool:
    block = _hunter_fix_policy()
    if "enabled" in block:
        return bool(block.get("enabled"))
    return True


def hunter_fix_max_rounds() -> int:
    block = _hunter_fix_policy()
    try:
        return max(0, int(block.get("max_rounds") or 1))
    except (TypeError, ValueError):
        return 1


def hunter_live_fetch_retry_config() -> tuple[int, tuple[float, ...]]:
    block = _hunter_fix_policy()
    try:
        retries = max(1, int(block.get("live_fetch_retries") or 3))
    except (TypeError, ValueError):
        retries = 3
    raw_backoff = block.get("live_fetch_backoff_seconds") or [1.0, 2.0]
    backoff: list[float] = []
    if isinstance(raw_backoff, list):
        for value in raw_backoff:
            try:
                backoff.append(max(0.0, float(value)))
            except (TypeError, ValueError):
                continue
    if not backoff:
        backoff = [1.0, 2.0]
    return retries, tuple(backoff)


def classify_hunter_fix_kind(result: HunterGateResult) -> HunterFixKind | None:
    """Return a fixable failure kind, or None when human triage is required."""
    if result.ok:
        return None
    reason = result.reason.lower()
    if "missing new test_parked_source_hunter" in reason:
        return HunterFixKind.MISSING_TEST
    if "skip reason too short" in reason:
        return HunterFixKind.SHORT_SKIP
    if "live-fetch failed" in reason or "body too short" in reason:
        return HunterFixKind.LIVE_FETCH_FAILED
    return None


def hunter_fix_attempt_count(task: EngineeringTask | dict[str, Any]) -> int:
    evidence = task.evidence if isinstance(task, EngineeringTask) else (task.get("evidence") or {})
    try:
        return max(0, int(evidence.get("hunter_fix_attempts") or 0))
    except (TypeError, ValueError):
        return 0


def hunter_fix_eligible(
    *,
    task: EngineeringTask,
    gate: HunterGateResult,
) -> tuple[bool, str, HunterFixKind | None]:
    if not hunter_fix_enabled():
        return False, "hunter_fix disabled by policy", None
    fix_kind = classify_hunter_fix_kind(gate)
    if fix_kind is None:
        return False, "gate failure is not hunter-fix eligible", None
    attempts = hunter_fix_attempt_count(task)
    max_rounds = hunter_fix_max_rounds()
    if attempts >= max_rounds:
        return False, f"hunter_fix exhausted ({attempts}/{max_rounds})", fix_kind
    return True, "eligible", fix_kind


def _git_show(ref: str, path: str, *, cwd: Path | None = None) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _git_diff_names(base_ref: str, head_ref: str, *, cwd: Path | None = None) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _dict_assign_node(source: str, name: str) -> ast.Dict | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        value_node: ast.expr | None = None
        target_name: str | None = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    target_name = target.id
                    value_node = node.value
                    break
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                target_name = node.target.id
                value_node = node.value
        if target_name == name and isinstance(value_node, ast.Dict):
            return value_node
    return None


def _dict_string_key(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _dict_value_as_str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
        joined = "".join(parts)
        return joined or None
    if isinstance(node, ast.Tuple):
        parts = [_dict_value_as_str(elt) or "" for elt in node.elts]
        return " ".join(part for part in parts if part).strip() or None
    return None


def _parse_skip_map(source: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    node = _dict_assign_node(source, "PARKED_SOURCE_HUNTER_SKIP")
    if node is None:
        return mapping
    for key_node, value_node in zip(node.keys, node.values, strict=False):
        key = _dict_string_key(key_node)
        if not key:
            continue
        reason = _dict_value_as_str(value_node)
        if reason:
            mapping[key.upper()] = reason.strip()
    return mapping


def _parse_builtin_urls(source: str) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    node = _dict_assign_node(source, "_BUILTIN_IR_URLS")
    if node is None:
        return mapping
    for key_node, value_node in zip(node.keys, node.values, strict=False):
        key = _dict_string_key(key_node)
        if not key or not isinstance(value_node, ast.List):
            continue
        urls: list[str] = []
        for elt in value_node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                cleaned = elt.value.strip()
                if cleaned:
                    urls.append(cleaned)
        mapping[key.upper()] = urls
    return mapping


def _added_test_names(base_tests: str, head_tests: str) -> list[str]:
    base_names = set(HUNTER_TEST_NAME_RE.findall(base_tests or ""))
    head_names = set(HUNTER_TEST_NAME_RE.findall(head_tests or ""))
    return sorted(head_names - base_names)


def default_filings_path(*, cwd: Path | None = None) -> Path:
    return Path(cwd or Path.cwd()) / "src/value_investor/research/filings.py"


def hunter_ticker_resolution_in_filings(
    filings_source: str,
    ticker: str,
) -> HunterResolution | None:
    """Return how a ticker is already recorded in filings.py, if at all."""
    token = ticker.strip().upper()
    if not token:
        return None
    if token in _parse_skip_map(filings_source):
        return HunterResolution.SKIP
    if _parse_builtin_urls(filings_source).get(token):
        return HunterResolution.ALLOWLIST
    return None


def hunter_ticker_already_resolved_on_main(
    ticker: str,
    *,
    filings_path: Path | None = None,
    cwd: Path | None = None,
) -> tuple[bool, HunterResolution | None, str]:
    """True when committed filings.py already records SKIP or ALLOWLIST for ticker."""
    path = filings_path or default_filings_path(cwd=cwd)
    if not path.exists():
        return False, None, "filings.py not found"
    resolution = hunter_ticker_resolution_in_filings(path.read_text(encoding="utf-8"), ticker)
    if resolution is None:
        return False, None, "not resolved on main"
    return True, resolution, f"already {resolution.value} on main"


def reconcile_superseded_parked_hunter_tasks(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    filings_path: Path | None = None,
    cwd: Path | None = None,
    apply: bool = True,
) -> list[dict[str, Any]]:
    """Cancel open/pr_open hunter tasks whose ticker is already resolved in filings.py."""
    data = load_engineering_tasks(tasks_path)
    cancelled: list[dict[str, Any]] = []
    for row in data.get("tasks") or []:
        if str(row.get("source") or "") != PARKED_SOURCE_HUNTER_SOURCE:
            continue
        status = str(row.get("status") or "")
        if status not in {"open", "pr_open"}:
            continue
        ticker = str((row.get("evidence") or {}).get("hunter_ticker") or "").strip().upper()
        if not ticker:
            continue
        resolved, kind, detail = hunter_ticker_already_resolved_on_main(
            ticker,
            filings_path=filings_path,
            cwd=cwd,
        )
        if not resolved or kind is None:
            continue
        task_id = str(row.get("id") or "")
        evidence = dict(row.get("evidence") or {})
        evidence["superseded_resolution"] = kind.value
        evidence["superseded_reason"] = detail
        evidence["superseded_at"] = datetime.now(UTC).isoformat()
        if apply:
            mark_task_status(
                task_id,
                "cancelled",
                path=tasks_path,
                committed_path=tasks_path,
                evidence=evidence,
            )
        cancelled.append(
            {
                "task_id": task_id,
                "ticker": ticker,
                "from_status": status,
                "resolution": kind.value,
                "detail": detail,
            }
        )
    return cancelled


def analyze_hunter_pr_diff(
    *,
    base_ref: str,
    head_ref: str,
    hunter_ticker: str,
    changed_files: list[str] | None = None,
    cwd: Path | None = None,
) -> HunterDiffAnalysis:
    """Classify a hunter PR diff as SKIP, ALLOWLIST, or UNKNOWN."""
    ticker = hunter_ticker.strip().upper()
    files = changed_files or _git_diff_names(base_ref, head_ref, cwd=cwd)
    base_filings = _git_show(f"{base_ref}", "src/value_investor/research/filings.py", cwd=cwd) or ""
    head_filings = _git_show(f"{head_ref}", "src/value_investor/research/filings.py", cwd=cwd) or ""
    base_tests = _git_show(f"{base_ref}", "tests/test_research_filings.py", cwd=cwd) or ""
    head_tests = _git_show(f"{head_ref}", "tests/test_research_filings.py", cwd=cwd) or ""

    base_skip = _parse_skip_map(base_filings)
    head_skip = _parse_skip_map(head_filings)
    base_urls = _parse_builtin_urls(base_filings)
    head_urls = _parse_builtin_urls(head_filings)

    added_skip = head_skip.get(ticker) if ticker in head_skip and ticker not in base_skip else None
    previous_urls = base_urls.get(ticker, [])
    current_urls = head_urls.get(ticker, [])
    new_urls = [url for url in current_urls if url not in previous_urls]
    added_tests = _added_test_names(base_tests, head_tests)

    if added_skip and new_urls:
        return HunterDiffAnalysis(
            outcome=HunterOutcome.UNKNOWN,
            hunter_ticker=ticker,
            new_skip_reason=added_skip,
            new_urls=new_urls,
            added_test_names=added_tests,
        )
    if added_skip:
        return HunterDiffAnalysis(
            outcome=HunterOutcome.SKIP,
            hunter_ticker=ticker,
            new_skip_reason=added_skip,
            added_test_names=added_tests,
        )
    if new_urls:
        return HunterDiffAnalysis(
            outcome=HunterOutcome.ALLOWLIST,
            hunter_ticker=ticker,
            new_urls=new_urls,
            added_test_names=added_tests,
        )
    if files and all(path in HUNTER_AUTO_MERGE_ALLOWED_FILES for path in files):
        return HunterDiffAnalysis(
            outcome=HunterOutcome.UNKNOWN,
            hunter_ticker=ticker,
            added_test_names=added_tests,
        )
    return HunterDiffAnalysis(outcome=HunterOutcome.UNKNOWN, hunter_ticker=ticker)


def validate_hunter_diff_scope(changed_files: list[str]) -> tuple[bool, str]:
    if not changed_files:
        return False, "no changed files"
    extra = sorted(set(changed_files) - HUNTER_AUTO_MERGE_ALLOWED_FILES)
    if extra:
        return False, f"unexpected changed files: {', '.join(extra[:5])}"
    if "src/value_investor/research/filings.py" not in changed_files:
        return False, "filings.py must change on hunter PRs"
    return True, "scope ok"


def _tier_allows_outcome(tier: str, outcome: HunterOutcome) -> bool:
    if tier == "off":
        return False
    if tier == "skip":
        return outcome == HunterOutcome.SKIP
    if tier == "allowlist":
        return outcome in {HunterOutcome.SKIP, HunterOutcome.ALLOWLIST}
    return False


def live_fetch_hunter_urls(
    urls: list[str],
    *,
    ticker: str,
    max_attempts: int | None = None,
    backoff_seconds: tuple[float, ...] | None = None,
) -> tuple[bool, str]:
    from value_investor.research.filings import (
        IR_BODY_MIN_CHARS,
        _fetch_ir_allowlist_body,
        _ir_allowlist_period_from_url,
    )

    if not urls:
        return False, "no URLs to live-fetch"
    if max_attempts is None or backoff_seconds is None:
        configured_attempts, configured_backoff = hunter_live_fetch_retry_config()
        max_attempts = max_attempts or configured_attempts
        backoff_seconds = backoff_seconds if backoff_seconds is not None else configured_backoff

    for url in urls:
        if not url.lower().startswith("https://"):
            return False, f"URL must be HTTPS: {url}"
        row = {
            "id": "hunter_gate",
            "url": url,
            "period": _ir_allowlist_period_from_url(url),
            "source": "ir_allowlist",
        }
        last_reason = f"live-fetch failed or body too short for {url}"
        for attempt in range(max(1, max_attempts)):
            body, _source = _fetch_ir_allowlist_body(row, ticker=ticker)
            if body and len(body) >= IR_BODY_MIN_CHARS:
                break
            if attempt + 1 < max_attempts:
                delay = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                if delay > 0:
                    time.sleep(delay)
        else:
            return False, last_reason
    return True, f"live-fetch ok for {len(urls)} URL(s)"


def _finalize_gate_result(result: HunterGateResult) -> HunterGateResult:
    if result.ok or result.fix_kind is not None:
        return result
    return HunterGateResult(
        ok=result.ok,
        reason=result.reason,
        analysis=result.analysis,
        tier=result.tier,
        fix_kind=classify_hunter_fix_kind(result),
    )


def verify_merged_hunter_allowlist_urls(
    task: EngineeringTask | dict[str, Any],
    *,
    merge_base_ref: str = "HEAD^",
    merge_head_ref: str = "HEAD",
    cwd: Path | None = None,
) -> tuple[bool, str]:
    """Re-live-fetch allowlist URLs introduced by a merged hunter task."""
    if not is_parked_source_hunter_task(task):
        return True, "not a hunter task"
    ticker = hunter_task_ticker(task)
    if not ticker:
        return True, "missing hunter ticker"
    analysis = analyze_hunter_pr_diff(
        base_ref=merge_base_ref,
        head_ref=merge_head_ref,
        hunter_ticker=ticker,
        cwd=cwd,
    )
    if analysis.outcome != HunterOutcome.ALLOWLIST:
        return True, "merged hunter outcome is not ALLOWLIST"
    urls = list(analysis.new_urls or [])
    if not urls:
        return True, "no new allowlist URLs in merge commit"
    ok, reason = live_fetch_hunter_urls(urls, ticker=ticker)
    if ok:
        return True, reason
    return False, f"post-merge hunter URL verify failed: {reason}"


def evaluate_hunter_merge_gate(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    base_ref: str,
    head_ref: str,
    tier: str | None = None,
    cwd: Path | None = None,
    skip_live_fetch: bool = False,
) -> HunterGateResult:
    """Validate a hunter PR for auto-merge (CI gate + merge-time check)."""
    tier = tier or hunter_auto_merge_policy_tier()
    if tier == "off":
        return HunterGateResult(True, "parked_hunter auto-merge disabled — gate skipped", tier=tier)

    ticker = hunter_task_ticker(task)
    if not ticker:
        return _finalize_gate_result(
            HunterGateResult(False, "hunter task missing evidence.hunter_ticker", tier=tier)
        )

    scope_ok, scope_reason = validate_hunter_diff_scope(changed_files)
    if not scope_ok:
        return _finalize_gate_result(HunterGateResult(False, scope_reason, tier=tier))

    guard = validate_engineering_pr_paths(task=task, changed_files=changed_files)
    if not guard.ok:
        return _finalize_gate_result(
            HunterGateResult(
                False,
                f"path guard failed: {'; '.join(guard.violations[:3])}",
                tier=tier,
            )
        )

    analysis = analyze_hunter_pr_diff(
        base_ref=base_ref,
        head_ref=head_ref,
        hunter_ticker=ticker,
        changed_files=changed_files,
        cwd=cwd,
    )
    if analysis.outcome == HunterOutcome.UNKNOWN:
        base_filings = (
            _git_show(f"{base_ref}", "src/value_investor/research/filings.py", cwd=cwd) or ""
        )
        base_resolution = hunter_ticker_resolution_in_filings(base_filings, ticker)
        if base_resolution is not None:
            reason = (
                f"hunter ticker already resolved on base ({base_resolution.value}) — "
                "no new SKIP or ALLOWLIST outcome in diff"
            )
        else:
            reason = "could not classify hunter diff as SKIP or ALLOWLIST"
        return _finalize_gate_result(
            HunterGateResult(
                False,
                reason,
                analysis=analysis,
                tier=tier,
            )
        )
    if not _tier_allows_outcome(tier, analysis.outcome):
        return _finalize_gate_result(
            HunterGateResult(
                False,
                f"policy tier {tier!r} does not allow {analysis.outcome.value} auto-merge",
                analysis=analysis,
                tier=tier,
            )
        )

    if not analysis.added_test_names:
        return _finalize_gate_result(
            HunterGateResult(
                False,
                "missing new test_parked_source_hunter_* regression test",
                analysis=analysis,
                tier=tier,
            )
        )

    if analysis.outcome == HunterOutcome.SKIP:
        reason = analysis.new_skip_reason or ""
        if len(reason.strip()) < HUNTER_MIN_SKIP_REASON_CHARS:
            return _finalize_gate_result(
                HunterGateResult(
                    False,
                    f"SKIP reason too short (need >= {HUNTER_MIN_SKIP_REASON_CHARS} chars)",
                    analysis=analysis,
                    tier=tier,
                )
            )
        return HunterGateResult(True, "SKIP hunter gate passed", analysis=analysis, tier=tier)

    new_urls = list(analysis.new_urls or [])
    if not new_urls or len(new_urls) > HUNTER_MAX_NEW_URLS:
        return _finalize_gate_result(
            HunterGateResult(
                False,
                f"ALLOWLIST requires 1–{HUNTER_MAX_NEW_URLS} new URL(s)",
                analysis=analysis,
                tier=tier,
            )
        )

    if skip_live_fetch:
        return HunterGateResult(
            True,
            "ALLOWLIST hunter gate passed (live-fetch skipped)",
            analysis=analysis,
            tier=tier,
        )

    fetch_ok, fetch_reason = live_fetch_hunter_urls(new_urls, ticker=ticker)
    if not fetch_ok:
        return _finalize_gate_result(
            HunterGateResult(False, fetch_reason, analysis=analysis, tier=tier)
        )
    return HunterGateResult(True, fetch_reason, analysis=analysis, tier=tier)


def hunter_task_eligible_for_auto_merge(task: EngineeringTask) -> bool:
    if not is_parked_source_hunter_task(task):
        return False
    return hunter_auto_merge_policy_tier() != "off"


def evaluate_hunter_auto_merge(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    base_ref: str = "origin/main",
    head_ref: str = "HEAD",
    cwd: Path | None = None,
) -> HunterGateResult:
    """Final hunter auto-merge eligibility using repo refs on disk."""
    tier = hunter_auto_merge_policy_tier()
    if tier == "off":
        return HunterGateResult(False, "parked_hunter auto-merge disabled by policy", tier=tier)
    return evaluate_hunter_merge_gate(
        task=task,
        changed_files=changed_files,
        base_ref=base_ref,
        head_ref=head_ref,
        tier=tier,
        cwd=cwd,
    )


def load_hunter_task_for_branch(
    branch: str,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> EngineeringTask | None:
    from value_investor.engineering_queue import task_id_from_branch

    task_id = task_id_from_branch(branch)
    if not task_id:
        return None
    return find_engineering_task(task_id, path=tasks_path)


__all__ = [
    "HunterDiffAnalysis",
    "HunterFixKind",
    "HunterGateResult",
    "HunterOutcome",
    "HunterResolution",
    "analyze_hunter_pr_diff",
    "classify_hunter_fix_kind",
    "evaluate_hunter_auto_merge",
    "evaluate_hunter_merge_gate",
    "hunter_auto_merge_policy_tier",
    "hunter_fix_eligible",
    "hunter_fix_enabled",
    "hunter_fix_max_rounds",
    "hunter_live_fetch_retry_config",
    "hunter_task_eligible_for_auto_merge",
    "hunter_task_ticker",
    "hunter_ticker_already_resolved_on_main",
    "hunter_ticker_resolution_in_filings",
    "hunter_verify_observer_enabled",
    "is_parked_source_hunter_task",
    "live_fetch_hunter_urls",
    "load_hunter_task_for_branch",
    "reconcile_superseded_parked_hunter_tasks",
    "validate_hunter_diff_scope",
    "verify_merged_hunter_allowlist_urls",
]
