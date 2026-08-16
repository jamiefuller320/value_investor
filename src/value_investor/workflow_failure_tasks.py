"""Draft supervised engineering tasks from non-pytest workflow failure logs."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.engineering_tasks import (
    BLOCKED_PATHS,
    TERMINAL_TASK_STATUSES,
    EngineeringTask,
    _allowed_paths_for_area,
    _default_acceptance_criteria,
    _merge_task_rows,
    load_engineering_tasks,
)
from value_investor.storage import write_json

COMMITTED_TASKS_PATH = Path("docs/data/engineering_tasks.json")

_WORKFLOW_SIGNATURES: tuple[dict[str, Any], ...] = (
    {
        "workflow": "library-grow.yml",
        "patterns": (r"JSONDecodeError.*last_ladder", r"json\.decoder\.JSONDecodeError"),
        "title": "Workflow fix: library ladder last_ladder.json parse failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/library-grow.yml",
            "src/value_investor/library_ladder.py",
            "tests/test_library_ladder.py",
        ],
    },
    {
        "workflow": "ingest-loop.yml",
        "patterns": (r"ingest.improvement", r"ftse-ingest-loop", r"CurlError", r"HTTPError"),
        "title": "Workflow fix: ingest-loop failure on main",
        "area": "ingest",
        "allowed_paths": [
            ".github/workflows/ingest-loop.yml",
            "src/value_investor/ingest_loop.py",
            "src/value_investor/research/ingest_improvement.py",
            "tests/test_ingest_loop.py",
        ],
    },
    {
        "workflow": "email-report.yml",
        "patterns": (r"ftse-email", r"email.report", r"SMTP", r"post_run_review"),
        "title": "Workflow fix: Sunday email report failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/email-report.yml",
            "src/value_investor/email_agent.py",
            "tests/test_email.py",
        ],
    },
    {
        "workflow": "analysis-review.yml",
        "patterns": (r"analysis.review", r"ftse-analysis-review"),
        "title": "Workflow fix: analysis review failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/analysis-review.yml",
            "src/value_investor/analysis_review.py",
            "tests/test_analysis_review.py",
        ],
    },
    {
        "workflow": "library-model-review.yml",
        "patterns": (
            r"model.review",
            r"agent_model_policy",
            r"review_model",
            r"recommend_cheapest_model",
        ),
        "title": "Workflow fix: library model review failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/library-model-review.yml",
            "src/value_investor/agent_model_policy.py",
            "docs/data/library/policy.json",
            "tests/test_agent_model_policy.py",
        ],
    },
    {
        "workflow": "data-backup.yml",
        "patterns": (
            r"ftse-data-backup",
            r"data.backup",
            r"BACKUP_",
            r"tarfile",
            r"manifest",
        ),
        "title": "Workflow fix: data backup failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/data-backup.yml",
            "src/value_investor/data_backup.py",
            "src/value_investor/data_backup_cli.py",
            "tests/test_data_backup.py",
        ],
    },
    {
        "workflow": "paper-auto.yml",
        "patterns": (
            r"paper.auto",
            r"ftse-paper",
            r"paper_automation",
            r"surveillance",
        ),
        "title": "Workflow fix: paper automation failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/paper-auto.yml",
            "src/value_investor/paper_automation.py",
            "docs/data/paper_automation/",
            "tests/test_paper_automation.py",
        ],
    },
    {
        "workflow": "horizon-scan.yml",
        "patterns": (
            r"horizon.scan",
            r"ftse-horizon",
            r"horizon_scan",
            r"compile_horizon_tasks",
        ),
        "title": "Workflow fix: horizon scan failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/horizon-scan.yml",
            "src/value_investor/horizon_scan.py",
            "src/value_investor/horizon_scan_cli.py",
            "docs/data/horizon_scan.json",
            "tests/test_horizon_scan.py",
        ],
    },
    {
        "workflow": "automation-orchestrator.yml",
        "patterns": (
            r"orchestrator",
            r"dispatch_github_workflow",
            r"workflow_dispatch",
            r"automation.orchestrator",
        ),
        "title": "Workflow fix: automation orchestrator failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/automation-orchestrator.yml",
            "scripts/dispatch_orchestrator.sh",
            "scripts/dispatch_github_workflow.sh",
            "src/value_investor/automation_status.py",
            "tests/test_import_cron_jobs.py",
        ],
    },
)

_GENERIC_WORKFLOW_SPECS: dict[str, dict[str, Any]] = {
    "library-model-review.yml": {
        "workflow": "library-model-review.yml",
        "title": "Workflow fix: library model review failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/library-model-review.yml",
            "src/value_investor/agent_model_policy.py",
            "docs/data/library/policy.json",
            "tests/test_agent_model_policy.py",
        ],
    },
    "data-backup.yml": {
        "workflow": "data-backup.yml",
        "title": "Workflow fix: data backup failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/data-backup.yml",
            "src/value_investor/data_backup.py",
            "src/value_investor/data_backup_cli.py",
            "tests/test_data_backup.py",
        ],
    },
    "paper-auto.yml": {
        "workflow": "paper-auto.yml",
        "title": "Workflow fix: paper automation failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/paper-auto.yml",
            "src/value_investor/paper_automation.py",
            "docs/data/paper_automation/",
            "tests/test_paper_automation.py",
        ],
    },
    "horizon-scan.yml": {
        "workflow": "horizon-scan.yml",
        "title": "Workflow fix: horizon scan failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/horizon-scan.yml",
            "src/value_investor/horizon_scan.py",
            "src/value_investor/horizon_scan_cli.py",
            "docs/data/horizon_scan.json",
            "tests/test_horizon_scan.py",
        ],
    },
    "automation-orchestrator.yml": {
        "workflow": "automation-orchestrator.yml",
        "title": "Workflow fix: automation orchestrator failure",
        "area": "ops",
        "allowed_paths": [
            ".github/workflows/automation-orchestrator.yml",
            "scripts/dispatch_orchestrator.sh",
            "scripts/dispatch_github_workflow.sh",
            "src/value_investor/automation_status.py",
            "tests/test_import_cron_jobs.py",
        ],
    },
}

_FAILURE_LOG_MARKERS = re.compile(
    r"(?i)(##\[error\]|process completed with exit code [1-9]|traceback \(most recent|"
    r"AssertionError|fatal error|command failed)",
)


def _looks_like_failure_log(log_text: str) -> bool:
    text = (log_text or "").strip()
    if not text:
        return False
    return bool(_FAILURE_LOG_MARKERS.search(text))


def match_workflow_failure_signature(
    workflow_file: str,
    log_text: str,
) -> dict[str, Any] | None:
    """Return the first matching workflow failure signature for *workflow_file*."""
    workflow_file = str(workflow_file or "").strip()
    text = log_text or ""
    for spec in _WORKFLOW_SIGNATURES:
        if str(spec.get("workflow") or "") != workflow_file:
            continue
        for pattern in spec.get("patterns") or ():
            if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                return dict(spec)
    generic = _GENERIC_WORKFLOW_SPECS.get(workflow_file)
    if generic is not None and _looks_like_failure_log(text):
        return dict(generic)
    return None


def _next_engineering_seq(existing_rows: list[dict[str, Any]], run_stamp: str) -> int:
    prefix = f"eng-{run_stamp}-"
    used = [
        int(str(row.get("id") or "").removeprefix(prefix))
        for row in existing_rows
        if str(row.get("id") or "").startswith(prefix)
        and str(row.get("id") or "").removeprefix(prefix).isdigit()
    ]
    return max(used, default=0) + 1


def draft_workflow_failure_task(
    *,
    workflow_file: str,
    log_text: str,
    run_id: int | str | None = None,
    run_url: str | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    signature: dict[str, Any] | None = None,
) -> list[str]:
    """Queue a scoped workflow-failure engineering task when logs match a signature."""
    signature = signature or match_workflow_failure_signature(workflow_file, log_text)
    if signature is None:
        return []

    title = str(signature.get("title") or f"Workflow fix: {workflow_file}")[:160]
    title_key = title.strip().lower()
    area = str(signature.get("area") or "ops")
    allowed_paths = list(signature.get("allowed_paths") or _allowed_paths_for_area(area))

    payload = load_engineering_tasks(tasks_path)
    existing_rows = list(payload.get("tasks") or [])
    for row in existing_rows:
        if str(row.get("status") or "open") in TERMINAL_TASK_STATUSES:
            continue
        if str(row.get("title") or "").strip().lower() == title_key:
            return []
        if (
            str(row.get("source") or "") == "workflow_failure"
            and str(row.get("status") or "") == "open"
            and str((row.get("evidence") or {}).get("workflow") or "") == workflow_file
        ):
            return []

    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    seq = _next_engineering_seq(existing_rows, run_stamp)
    task_id = f"eng-{run_stamp}-{seq:02d}"
    summary_bits = [
        f"GitHub workflow {workflow_file} failed on main.",
        "Investigate the failed run log and fix the workflow or underlying code within allowed_paths.",
    ]
    if run_url:
        summary_bits.append(f"Run: {run_url}")

    drafted = EngineeringTask(
        id=task_id,
        area=area,
        title=title,
        summary=" ".join(summary_bits)[:500],
        priority="high",
        priority_score=90.0,
        source="workflow_failure",
        evidence={
            "workflow": workflow_file,
            "run_id": str(run_id) if run_id is not None else None,
            "run_url": run_url,
            "signature": signature.get("patterns"),
        },
        acceptance_criteria=_default_acceptance_criteria(area, allowed_paths),
        allowed_paths=allowed_paths,
        blocked_paths=list(BLOCKED_PATHS),
    )

    merged_rows = _merge_task_rows(existing_rows, [drafted])
    payload = {
        **payload,
        "compiled_at": datetime.now(UTC).isoformat(),
        "task_count": len(merged_rows),
        "tasks": merged_rows,
        "workflow_failure_compiled": True,
    }
    tasks_path = Path(tasks_path)
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(tasks_path, payload, compact=False)
    return [task_id]


__all__ = [
    "draft_workflow_failure_task",
    "match_workflow_failure_signature",
]
