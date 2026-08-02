"""Supervised dev agent for a single engineering task."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.engineering_tasks import EngineeringTask
from value_investor.storage import write_json

logger = logging.getLogger(__name__)

DEFAULT_ENGINEERING_MODEL = "composer-2.5"
DEFAULT_ESTIMATED_USD = 1.2


@dataclass
class EngineeringRunResult:
    task: EngineeringTask
    agent_id: str | None
    summary: str
    result_path: Path
    payload_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task.id,
            "agent_id": self.agent_id,
            "summary": self.summary,
            "result_path": str(self.result_path),
            "payload_path": str(self.payload_path),
            "completed_at": datetime.now(UTC).isoformat(),
        }


def _build_engineering_prompt(*, task: EngineeringTask, task_path: Path, output_dir: Path) -> str:
    result_path = output_dir / f"engineering_result_{task.id}.md"
    return f"""You are a supervised engineering agent for the FTSE Value Investor repository.

Read the engineering task JSON at: {task_path}

Implement ONLY that one task. Rules:
1. Edit files only under `allowed_paths` from the task JSON.
2. Never edit any path listed in `blocked_paths`.
3. Keep the diff minimal and focused — no drive-by refactors.
4. Add or update tests that prove the behaviour described in `acceptance_criteria`.
5. Run the most relevant pytest subset before finishing (e.g. tests covering changed modules).
6. Do NOT merge branches, open pull requests, or change GitHub workflows unless the task explicitly requires it.
7. Do NOT change paper-fund, simulator, or live signal thresholds unless the task explicitly requires it.
8. When `auto_merge` is true on the task, keep the diff minimal and within `allowed_paths` so CI and the path guard can merge automatically.

When finished, write a markdown report to:
{result_path}

Report sections (plain-text headings):
ENGINEERING SUMMARY
What you changed and why (3–6 sentences).

FILES CHANGED
Bullet list of paths touched.

TESTS
Which tests you added/ran and their outcome.

VERIFY NEXT RUN
How the next Sunday email / ingest pass should confirm the fix.

RISKS
Anything left manual or uncertain.
"""


def run_engineering_agent(
    *,
    task: EngineeringTask,
    output_dir: Path,
    api_key: str,
    model: str = DEFAULT_ENGINEERING_MODEL,
    cwd: str | None = None,
) -> EngineeringRunResult:
    """Run one supervised engineering task via the Cursor local agent."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload_path = output_dir / f"engineering_task_{task.id}.json"
    write_json(payload_path, task.to_dict(), compact=False)

    try:
        agent_result = Agent.prompt(
            _build_engineering_prompt(
                task=task,
                task_path=payload_path.resolve(),
                output_dir=output_dir,
            ),
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=cwd or os.getcwd()),
            ),
        )
    except CursorAgentError as err:
        raise RuntimeError(f"Engineering agent startup failed: {err.message}") from err

    if agent_result.status == "error":
        raise RuntimeError(f"Engineering agent run failed: {agent_result.id}")

    summary = (agent_result.result or "").strip()
    result_path = output_dir / f"engineering_result_{task.id}.md"
    if not result_path.exists():
        result_path.write_text(
            f"ENGINEERING SUMMARY\n{summary or 'Agent completed without a written report.'}\n",
            encoding="utf-8",
        )
    elif summary and len(summary) > len(result_path.read_text(encoding="utf-8")):
        result_path.write_text(summary, encoding="utf-8")

    run_meta_path = output_dir / f"engineering_run_{task.id}.json"
    result = EngineeringRunResult(
        task=task,
        agent_id=agent_result.id,
        summary=summary or result_path.read_text(encoding="utf-8")[:2000],
        result_path=result_path,
        payload_path=payload_path,
    )
    write_json(run_meta_path, result.to_dict(), compact=True)
    return result


def record_engineering_spend(
    *,
    path: Path | None = None,
    estimated_usd: float = DEFAULT_ESTIMATED_USD,
) -> dict[str, Any]:
    """Record engineering agent spend against the ad-hoc checkpoint pool."""
    from value_investor.agent_model_policy import (
        SPEND_POOL_AD_HOC,
        record_estimated_spend,
        spend_since_checkpoint_usd,
        spend_checkpoint_usd,
        load_policy,
    )

    record_estimated_spend(estimated_usd, path, pool=SPEND_POOL_AD_HOC)
    policy = load_policy(path)
    since = spend_since_checkpoint_usd(policy)
    limit = spend_checkpoint_usd(policy)
    return {
        "estimated_usd": estimated_usd,
        "spend_since_checkpoint_usd": since,
        "spend_checkpoint_usd": limit,
        "checkpoint_reached": since >= limit,
        "remaining_until_checkpoint_usd": round(max(0.0, limit - since), 4),
    }
