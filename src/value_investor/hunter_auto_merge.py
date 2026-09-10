"""Deterministic auto-merge gates for parked-source hunter engineering PRs."""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import load_policy
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    EngineeringTask,
    PARKED_SOURCE_HUNTER_SOURCE,
    find_engineering_task,
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


class HunterOutcome(str, Enum):
    SKIP = "skip"
    ALLOWLIST = "allowlist"
    UNKNOWN = "unknown"


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

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "reason": self.reason,
            "tier": self.tier,
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
) -> tuple[bool, str]:
    from value_investor.research.filings import (
        IR_BODY_MIN_CHARS,
        _fetch_ir_allowlist_body,
        _ir_allowlist_period_from_url,
    )

    if not urls:
        return False, "no URLs to live-fetch"
    for url in urls:
        if not url.lower().startswith("https://"):
            return False, f"URL must be HTTPS: {url}"
        row = {
            "id": "hunter_gate",
            "url": url,
            "period": _ir_allowlist_period_from_url(url),
            "source": "ir_allowlist",
        }
        body, _source = _fetch_ir_allowlist_body(row, ticker=ticker)
        if not body or len(body) < IR_BODY_MIN_CHARS:
            return False, f"live-fetch failed or body too short for {url}"
    return True, f"live-fetch ok for {len(urls)} URL(s)"


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
        return HunterGateResult(False, "hunter task missing evidence.hunter_ticker", tier=tier)

    scope_ok, scope_reason = validate_hunter_diff_scope(changed_files)
    if not scope_ok:
        return HunterGateResult(False, scope_reason, tier=tier)

    guard = validate_engineering_pr_paths(task=task, changed_files=changed_files)
    if not guard.ok:
        return HunterGateResult(
            False,
            f"path guard failed: {'; '.join(guard.violations[:3])}",
            tier=tier,
        )

    analysis = analyze_hunter_pr_diff(
        base_ref=base_ref,
        head_ref=head_ref,
        hunter_ticker=ticker,
        changed_files=changed_files,
        cwd=cwd,
    )
    if analysis.outcome == HunterOutcome.UNKNOWN:
        return HunterGateResult(
            False,
            "could not classify hunter diff as SKIP or ALLOWLIST",
            analysis=analysis,
            tier=tier,
        )
    if not _tier_allows_outcome(tier, analysis.outcome):
        return HunterGateResult(
            False,
            f"policy tier {tier!r} does not allow {analysis.outcome.value} auto-merge",
            analysis=analysis,
            tier=tier,
        )

    if not analysis.added_test_names:
        return HunterGateResult(
            False,
            "missing new test_parked_source_hunter_* regression test",
            analysis=analysis,
            tier=tier,
        )

    if analysis.outcome == HunterOutcome.SKIP:
        reason = analysis.new_skip_reason or ""
        if len(reason.strip()) < HUNTER_MIN_SKIP_REASON_CHARS:
            return HunterGateResult(
                False,
                f"SKIP reason too short (need >= {HUNTER_MIN_SKIP_REASON_CHARS} chars)",
                analysis=analysis,
                tier=tier,
            )
        return HunterGateResult(True, "SKIP hunter gate passed", analysis=analysis, tier=tier)

    new_urls = list(analysis.new_urls or [])
    if not new_urls or len(new_urls) > HUNTER_MAX_NEW_URLS:
        return HunterGateResult(
            False,
            f"ALLOWLIST requires 1–{HUNTER_MAX_NEW_URLS} new URL(s)",
            analysis=analysis,
            tier=tier,
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
        return HunterGateResult(False, fetch_reason, analysis=analysis, tier=tier)
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
    "HunterGateResult",
    "HunterOutcome",
    "analyze_hunter_pr_diff",
    "evaluate_hunter_auto_merge",
    "evaluate_hunter_merge_gate",
    "hunter_auto_merge_policy_tier",
    "hunter_task_eligible_for_auto_merge",
    "hunter_task_ticker",
    "hunter_verify_observer_enabled",
    "is_parked_source_hunter_task",
    "live_fetch_hunter_urls",
    "load_hunter_task_for_branch",
    "validate_hunter_diff_scope",
]
