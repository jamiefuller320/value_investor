"""Capped hunter-fix agent for parked_source_hunter merge-gate failures."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    EngineeringTask,
    load_engineering_tasks,
    mark_task_status,
)
from value_investor.hunter_auto_merge import (
    HunterFixKind,
    HunterGateResult,
    evaluate_hunter_merge_gate,
    hunter_fix_eligible,
    hunter_task_ticker,
    is_parked_source_hunter_task,
    strip_unexpected_hunter_files,
)
from value_investor.storage import write_json

logger = logging.getLogger(__name__)

DEFAULT_FIX_MODEL = "composer-2.5"
_HUNTER_GATE_FAIL_MARKERS = (
    "hunter-merge-gate: fail",
    "hunter-merge-gate",
)
_HUNTER_FIX_COMMIT_PREFIX = "chore(hunter-fix):"


@dataclass
class HunterFixResult:
    task_id: str
    fix_kind: HunterFixKind | None
    gate_before: dict[str, Any]
    gate_after: dict[str, Any] | None
    agent_id: str | None
    summary: str
    skipped: bool = False
    skip_reason: str | None = None
    changed_files: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "fix_kind": self.fix_kind.value if self.fix_kind else None,
            "gate_before": self.gate_before,
            "gate_after": self.gate_after,
            "agent_id": self.agent_id,
            "summary": self.summary,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "changed_files": list(self.changed_files or []),
            "completed_at": datetime.now(UTC).isoformat(),
        }


def ci_log_shows_hunter_gate_failure(log_text: str) -> bool:
    """True when failed CI logs include a hunter-merge-gate failure."""
    text = str(log_text or "")
    if "hunter-merge-gate: fail" in text:
        return True
    if "hunter-merge-gate" in text and re.search(
        r"hunter-merge-gate.*\bfail\b", text, flags=re.IGNORECASE
    ):
        return True
    return False


def latest_commit_is_hunter_fix(*, cwd: Path | None = None) -> bool:
    result = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    subject = (result.stdout or "").strip()
    return subject.startswith(_HUNTER_FIX_COMMIT_PREFIX)


def hunter_fix_kind_from_commit_subject(subject: str) -> str | None:
    """Parse fix kind from `chore(hunter-fix): address hunter-merge-gate <kind>`."""
    text = str(subject or "").strip()
    match = re.search(r"address hunter-merge-gate ([a-z0-9_]+)$", text)
    return match.group(1) if match else None


def tip_hunter_fix_kind(*, cwd: Path | None = None) -> str | None:
    result = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return hunter_fix_kind_from_commit_subject((result.stdout or "").strip())


def _git_diff_excerpt(base_ref: str, head_ref: str, *, cwd: Path | None = None) -> str:
    paths = [
        "src/value_investor/research/filings.py",
        "tests/test_research_filings.py",
    ]
    chunks: list[str] = []
    for path in paths:
        result = subprocess.run(
            ["git", "diff", f"{base_ref}...{head_ref}", "--", path],
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        if result.stdout.strip():
            chunks.append(result.stdout)
    return "\n".join(chunks)


def _fix_instructions(fix_kind: HunterFixKind) -> str:
    if fix_kind == HunterFixKind.MISSING_TEST:
        return (
            "Add exactly one new `test_parked_source_hunter_*` regression test in "
            "`tests/test_research_filings.py` that asserts the hunter ticker appears in "
            "`PARKED_SOURCE_HUNTER_SKIP` or `_BUILTIN_IR_URLS` as appropriate."
        )
    if fix_kind == HunterFixKind.SHORT_SKIP:
        return (
            "Expand the SKIP reason for this ticker in `PARKED_SOURCE_HUNTER_SKIP` to at "
            "least 20 characters with concrete evidence (sites searched, document types "
            "missing, etc.). Do not add URLs."
        )
    if fix_kind == HunterFixKind.LIVE_FETCH_FAILED:
        return (
            "The proposed allowlist URL(s) failed live-fetch. Either replace with a "
            "fetchable HTTPS issuer IR URL that returns substantive body text, or convert "
            "the outcome to SKIP with a detailed reason (>= 20 chars) and remove the bad "
            "URL(s). Keep at most 3 new URLs."
        )
    if fix_kind == HunterFixKind.TOO_MANY_URLS:
        return (
            "Trim the new `_BUILTIN_IR_URLS` entry for this ticker to 1–3 HTTPS issuer IR "
            "URLs (prefer the newest annual + one interim if both exist). Update the "
            "matching `test_parked_source_hunter_*` / allowlist regression assertions to "
            "the same URL set. Do not add SKIP. Do not edit docs/data/*.json except "
            "`docs/data/engineering_tasks.json`."
        )
    if fix_kind == HunterFixKind.UNEXPECTED_FILES:
        return (
            "Remove or revert any files outside the hunter allowlist "
            "(`src/value_investor/research/filings.py`, `tests/test_research_filings.py`, "
            "`docs/data/engineering_tasks.json`). Prefer restoring incidental docs/data "
            "paths from origin/main."
        )
    return "Fix the hunter merge-gate failure."


def _build_fix_prompt(
    *,
    task: EngineeringTask,
    gate: HunterGateResult,
    fix_kind: HunterFixKind,
    diff_excerpt: str,
) -> str:
    ticker = hunter_task_ticker(task)
    market = str((task.evidence or {}).get("market_id") or "")
    return f"""You are fixing a parked-source hunter engineering PR that failed the deterministic merge gate.

Task id: {task.id}
Market: {market}
Ticker: {ticker}
Title: {task.title}

Gate failure: {json.dumps(gate.to_dict(), indent=2)}
Fix kind: {fix_kind.value}

Required fix:
{_fix_instructions(fix_kind)}

Allowed edits ONLY under:
- src/value_investor/research/filings.py
- tests/test_research_filings.py
- docs/data/engineering_tasks.json (increment evidence.hunter_fix_attempts only if present)

Rules:
1. One ticker only — do not touch other tickers.
2. Keep the diff minimal; no drive-by refactors.
3. Run `ruff check --fix` and `ruff format` on edited Python files.
4. Do not merge, open PRs, or edit workflows.
5. Do not change unrelated hunter entries.

Diff excerpt:
{diff_excerpt[:12000]}

When done, reply with markdown headings:

HUNTER FIX SUMMARY
3–6 sentences on what you changed.

FILES CHANGED
Bullet list of paths edited.
"""


def record_hunter_fix_attempt(
    task_id: str,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    apply: bool = True,
    fix_kind: HunterFixKind | str | None = None,
) -> int:
    """Increment evidence.hunter_fix_attempts; return new count."""
    payload = load_engineering_tasks(tasks_path)
    row = next(
        (task for task in payload.get("tasks") or [] if str(task.get("id") or "") == task_id),
        None,
    )
    if not isinstance(row, dict):
        return 0
    evidence = dict(row.get("evidence") or {})
    try:
        attempts = max(0, int(evidence.get("hunter_fix_attempts") or 0))
    except (TypeError, ValueError):
        attempts = 0
    attempts += 1
    evidence["hunter_fix_attempts"] = attempts
    kind_value = (
        fix_kind.value
        if isinstance(fix_kind, HunterFixKind)
        else str(fix_kind or "").strip() or None
    )
    if kind_value:
        kinds = [
            str(item).strip()
            for item in (evidence.get("hunter_fix_kinds_attempted") or [])
            if str(item or "").strip()
        ]
        if kind_value not in kinds:
            kinds.append(kind_value)
        evidence["hunter_fix_kinds_attempted"] = kinds
        evidence["last_hunter_fix_kind"] = kind_value
    if apply:
        mark_task_status(
            task_id,
            str(row.get("status") or "pr_open"),
            path=tasks_path,
            committed_path=tasks_path,
            evidence=evidence,
        )
    return attempts


def format_hunter_fix_pr_comment(result: HunterFixResult) -> str:
    lines = [
        "## Hunter fix agent (capped rework)",
        "",
        f"- **Task:** `{result.task_id}`",
        f"- **Fix kind:** `{result.fix_kind.value if result.fix_kind else 'n/a'}`",
    ]
    if result.skipped:
        lines.append(f"- **Skipped:** {result.skip_reason or 'yes'}")
    if result.agent_id:
        lines.append(f"- **Agent id:** `{result.agent_id}`")
    before_ok = (result.gate_before or {}).get("ok")
    lines.append(
        f"- **Gate before:** {'pass' if before_ok else 'fail'} — "
        f"{(result.gate_before or {}).get('reason', '')}"
    )
    if result.gate_after is not None:
        after_ok = result.gate_after.get("ok")
        lines.append(
            f"- **Gate after:** {'pass' if after_ok else 'fail'} — "
            f"{result.gate_after.get('reason', '')}"
        )
    lines.extend(["", result.summary.strip() or "_No summary returned._", ""])
    return "\n".join(lines)


def post_pr_comment(*, pr_number: int, body: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["gh", "pr", "comment", str(pr_number), "--body", body],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "gh pr comment failed").strip()
        return False, detail
    return True, "comment posted"


def run_hunter_fix_agent(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    base_ref: str = "origin/main",
    head_ref: str = "HEAD",
    pr_number: int | None = None,
    output_dir: Path | None = None,
    api_key: str | None = None,
    model: str = DEFAULT_FIX_MODEL,
    cwd: str | None = None,
    skip_agent: bool = False,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    record_attempt: bool = True,
) -> HunterFixResult:
    """Run one capped hunter-fix round; re-runs merge gate after agent edits."""
    output_dir = Path(output_dir or Path("output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(cwd) if cwd else Path.cwd()

    if not is_parked_source_hunter_task(task):
        return HunterFixResult(
            task_id=task.id,
            fix_kind=None,
            gate_before={},
            gate_after=None,
            agent_id=None,
            summary="Not a parked_source_hunter task.",
            skipped=True,
            skip_reason="not_hunter_task",
        )

    gate = evaluate_hunter_merge_gate(
        task=task,
        changed_files=changed_files,
        base_ref=base_ref,
        head_ref=head_ref,
        cwd=workdir,
        skip_live_fetch=False,
    )
    eligible, eligibility_reason, fix_kind = hunter_fix_eligible(task=task, gate=gate)
    gate_before = gate.to_dict()

    def _persist(result: HunterFixResult) -> HunterFixResult:
        write_json(output_dir / f"hunter_fix_{task.id}.json", result.to_dict(), compact=False)
        if pr_number is not None:
            ok, detail = post_pr_comment(
                pr_number=pr_number,
                body=format_hunter_fix_pr_comment(result),
            )
            if not ok:
                logger.warning("Hunter fix PR comment failed for #%s: %s", pr_number, detail)
        return result

    if not eligible or fix_kind is None:
        return _persist(
            HunterFixResult(
                task_id=task.id,
                fix_kind=fix_kind,
                gate_before=gate_before,
                gate_after=None,
                agent_id=None,
                summary=eligibility_reason,
                skipped=True,
                skip_reason=eligibility_reason,
            )
        )

    if record_attempt:
        record_hunter_fix_attempt(task.id, tasks_path=tasks_path, fix_kind=fix_kind)

    def _current_changed() -> list[str]:
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            check=False,
            capture_output=True,
            text=True,
            cwd=workdir,
        )
        names = [line.strip() for line in diff_result.stdout.splitlines() if line.strip()]
        dirty = subprocess.run(
            ["git", "diff", "--name-only"],
            check=False,
            capture_output=True,
            text=True,
            cwd=workdir,
        )
        for line in dirty.stdout.splitlines():
            path_name = line.strip()
            if path_name and path_name not in names:
                names.append(path_name)
        return names

    # Deterministic strip for scope pollution — no LLM needed.
    if fix_kind == HunterFixKind.UNEXPECTED_FILES:
        stripped = strip_unexpected_hunter_files(base_ref=base_ref, cwd=workdir)
        changed_after = _current_changed()
        gate_after_obj = evaluate_hunter_merge_gate(
            task=task,
            changed_files=changed_after or changed_files,
            base_ref=base_ref,
            head_ref="HEAD",
            cwd=workdir,
            skip_live_fetch=False,
        )
        summary = (
            f"Stripped unexpected files: {', '.join(stripped) or '(none)'}. "
            f"Gate after: {gate_after_obj.reason}"
        )
        return _persist(
            HunterFixResult(
                task_id=task.id,
                fix_kind=fix_kind,
                gate_before=gate_before,
                gate_after=gate_after_obj.to_dict(),
                agent_id=None,
                summary=summary,
                changed_files=changed_after,
            )
        )

    if skip_agent or not api_key:
        reason = "CURSOR_API_KEY not set" if not api_key else "agent skipped"
        return _persist(
            HunterFixResult(
                task_id=task.id,
                fix_kind=fix_kind,
                gate_before=gate_before,
                gate_after=None,
                agent_id=None,
                summary=f"Hunter fix not run ({reason}).",
                skipped=True,
                skip_reason=reason,
            )
        )

    diff_excerpt = _git_diff_excerpt(base_ref, head_ref, cwd=workdir)
    prompt = _build_fix_prompt(
        task=task,
        gate=gate,
        fix_kind=fix_kind,
        diff_excerpt=diff_excerpt,
    )
    agent_id: str | None = None
    agent_text = ""
    try:
        agent_result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=cwd or os.getcwd()),
            ),
        )
        agent_id = agent_result.id
        if agent_result.status == "error":
            agent_text = f"Hunter fix agent error: {agent_result.id}"
        else:
            agent_text = (agent_result.result or "").strip()
    except CursorAgentError as err:
        agent_text = f"Hunter fix agent startup failed: {err.message}"

    # Always drop incidental files the agent may have touched.
    strip_unexpected_hunter_files(base_ref=base_ref, cwd=workdir)
    changed_after = _current_changed()
    gate_after_obj = evaluate_hunter_merge_gate(
        task=task,
        changed_files=changed_after or changed_files,
        base_ref=base_ref,
        head_ref="HEAD",
        cwd=workdir,
        skip_live_fetch=False,
    )
    return _persist(
        HunterFixResult(
            task_id=task.id,
            fix_kind=fix_kind,
            gate_before=gate_before,
            gate_after=gate_after_obj.to_dict(),
            agent_id=agent_id,
            summary=agent_text or "Hunter fix agent returned no text.",
            changed_files=changed_after,
        )
    )


__all__ = [
    "HunterFixResult",
    "ci_log_shows_hunter_gate_failure",
    "format_hunter_fix_pr_comment",
    "latest_commit_is_hunter_fix",
    "post_pr_comment",
    "record_hunter_fix_attempt",
    "run_hunter_fix_agent",
]
