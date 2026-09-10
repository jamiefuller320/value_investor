"""Non-blocking verify observer for parked-source hunter PRs."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.engineering_tasks import EngineeringTask
from value_investor.hunter_auto_merge import (
    HunterDiffAnalysis,
    HunterGateResult,
    HunterOutcome,
    analyze_hunter_pr_diff,
    evaluate_hunter_merge_gate,
    hunter_task_ticker,
    hunter_verify_observer_enabled,
    is_parked_source_hunter_task,
)
from value_investor.storage import write_json

logger = logging.getLogger(__name__)

DEFAULT_VERIFY_MODEL = "composer-2.5"


@dataclass
class HunterVerifyObserverResult:
    task_id: str
    pr_number: int | None
    verdict: str
    summary: str
    agent_id: str | None = None
    deterministic_gate: dict[str, Any] | None = None
    skipped: bool = False
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "pr_number": self.pr_number,
            "verdict": self.verdict,
            "summary": self.summary,
            "agent_id": self.agent_id,
            "deterministic_gate": self.deterministic_gate,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "completed_at": datetime.now(UTC).isoformat(),
        }


def _build_verify_prompt(
    *,
    task: EngineeringTask,
    analysis: HunterDiffAnalysis,
    gate: HunterGateResult,
    diff_excerpt: str,
) -> str:
    ticker = hunter_task_ticker(task)
    market = str((task.evidence or {}).get("market_id") or "")
    return f"""You are an independent read-only reviewer for a parked-source hunter engineering PR.

Task id: {task.id}
Market: {market}
Ticker: {ticker}
Title: {task.title}

Deterministic gate result: {json.dumps(gate.to_dict(), indent=2)}
Diff analysis: {json.dumps(analysis.to_dict(), indent=2)}

Diff excerpt (filings/tests only):
{diff_excerpt[:12000]}

Review ONLY whether:
1. Proposed IR URLs (if any) plausibly belong to the issuer for {ticker} in market {market}.
2. A SKIP reason (if any) matches the evidence — do not invent alternative URLs.
3. The change stays one-ticker scoped with no scope creep.

You MUST NOT suggest code edits, new URLs, or merges. This is a non-blocking observer.

Reply with plain markdown using exactly these headings:

VERDICT
One of: approve | concern | reject

SUMMARY
3–6 sentences explaining your verdict.

ISSUES
Bullet list of concrete concerns, or "None".

URL CHECK
For each proposed URL, one line: url — ok | concern | reject — reason.
If no URLs, write "N/A (SKIP outcome)".
"""


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


def _parse_verdict(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("VERDICT"):
            tail = stripped.split(":", 1)[-1].split("VERDICT", 1)[-1].strip(" :-").lower()
            for candidate in ("approve", "concern", "reject"):
                if candidate in tail:
                    return candidate
    lowered = text.lower()
    if "reject" in lowered:
        return "reject"
    if "concern" in lowered:
        return "concern"
    return "approve"


def format_observer_pr_comment(result: HunterVerifyObserverResult) -> str:
    lines = [
        "## Hunter verify observer (non-blocking)",
        "",
        f"- **Task:** `{result.task_id}`",
        f"- **Verdict:** `{result.verdict}`",
    ]
    if result.skipped:
        lines.append(f"- **Skipped:** {result.skip_reason or 'yes'}")
    if result.agent_id:
        lines.append(f"- **Agent id:** `{result.agent_id}`")
    lines.extend(["", result.summary.strip() or "_No summary returned._", ""])
    if result.deterministic_gate is not None:
        gate_ok = result.deterministic_gate.get("ok")
        lines.append(
            f"Deterministic merge gate: **{'pass' if gate_ok else 'fail'}** — "
            f"{result.deterministic_gate.get('reason', '')}"
        )
        lines.append("")
        lines.append(
            "_This comment is informational only and does not block merge or auto-merge._"
        )
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


def run_hunter_verify_observer(
    *,
    task: EngineeringTask,
    changed_files: list[str],
    base_ref: str = "origin/main",
    head_ref: str = "HEAD",
    pr_number: int | None = None,
    output_dir: Path | None = None,
    api_key: str | None = None,
    model: str = DEFAULT_VERIFY_MODEL,
    cwd: str | None = None,
    skip_agent: bool = False,
) -> HunterVerifyObserverResult:
    """Run deterministic gate summary + optional LLM observer; never raises."""
    output_dir = Path(output_dir or Path("output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    if not is_parked_source_hunter_task(task):
        return HunterVerifyObserverResult(
            task_id=task.id,
            pr_number=pr_number,
            verdict="skipped",
            summary="Not a parked_source_hunter task.",
            skipped=True,
            skip_reason="not_hunter_task",
        )

    if not hunter_verify_observer_enabled():
        return HunterVerifyObserverResult(
            task_id=task.id,
            pr_number=pr_number,
            verdict="skipped",
            summary=(
                "Verify observer disabled in "
                "policy.engineering.auto_merge.parked_hunter_verify_observer."
            ),
            skipped=True,
            skip_reason="observer_disabled",
        )

    gate = evaluate_hunter_merge_gate(
        task=task,
        changed_files=changed_files,
        base_ref=base_ref,
        head_ref=head_ref,
        cwd=Path(cwd) if cwd else None,
        skip_live_fetch=False,
    )
    analysis = analyze_hunter_pr_diff(
        base_ref=base_ref,
        head_ref=head_ref,
        hunter_ticker=hunter_task_ticker(task),
        changed_files=changed_files,
        cwd=Path(cwd) if cwd else None,
    )

    if skip_agent or not api_key:
        reason = "CURSOR_API_KEY not set" if not api_key else "agent skipped"
        summary = (
            f"Deterministic gate: {'pass' if gate.ok else 'fail'} — {gate.reason}. "
            f"Outcome: {analysis.outcome.value}. LLM observer not run ({reason})."
        )
        result = HunterVerifyObserverResult(
            task_id=task.id,
            pr_number=pr_number,
            verdict="skipped",
            summary=summary,
            deterministic_gate=gate.to_dict(),
            skipped=True,
            skip_reason=reason,
        )
        write_json(output_dir / f"hunter_verify_{task.id}.json", result.to_dict(), compact=False)
        return result

    diff_excerpt = _git_diff_excerpt(base_ref, head_ref, cwd=Path(cwd) if cwd else None)
    prompt = _build_verify_prompt(
        task=task,
        analysis=analysis,
        gate=gate,
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
            agent_text = f"Verify agent error: {agent_result.id}"
        else:
            agent_text = (agent_result.result or "").strip()
    except CursorAgentError as err:
        agent_text = f"Verify agent startup failed: {err.message}"

    verdict = _parse_verdict(agent_text)
    if analysis.outcome == HunterOutcome.UNKNOWN and verdict == "approve":
        verdict = "concern"

    result = HunterVerifyObserverResult(
        task_id=task.id,
        pr_number=pr_number,
        verdict=verdict,
        summary=agent_text or "Verify agent returned no text.",
        agent_id=agent_id,
        deterministic_gate=gate.to_dict(),
    )
    write_json(output_dir / f"hunter_verify_{task.id}.json", result.to_dict(), compact=False)
    return result


__all__ = [
    "HunterVerifyObserverResult",
    "format_observer_pr_comment",
    "post_pr_comment",
    "run_hunter_verify_observer",
]
