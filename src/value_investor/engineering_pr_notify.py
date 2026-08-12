"""SMTP alerts for supervised engineering PRs and queue blockers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from value_investor.emailer import EmailConfig, send_email

logger = logging.getLogger(__name__)

QUEUE_ALERT_KINDS = frozenset(
    {
        "spend_blocked",
        "agent_failure",
        "orphan_reconcile",
        "task_parked",
    }
)


@dataclass
class EngineeringPrNotification:
    task_id: str
    branch: str
    pr_url: str
    pr_number: int | None
    is_draft: bool
    auto_merge: bool
    used_pat: bool
    ci_approval_hint: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "branch": self.branch,
            "pr_url": self.pr_url,
            "pr_number": self.pr_number,
            "is_draft": self.is_draft,
            "auto_merge": self.auto_merge,
            "used_pat": self.used_pat,
            "ci_approval_hint": self.ci_approval_hint,
        }


def format_engineering_pr_text(note: EngineeringPrNotification) -> str:
    lines = [
        "FTSE Engineering PR opened",
        "",
        f"Task: {note.task_id}",
        f"Branch: {note.branch}",
        f"PR: {note.pr_url}",
    ]
    if note.pr_number is not None:
        lines.append(f"Number: #{note.pr_number}")
    lines.append(f"Draft: {'yes' if note.is_draft else 'no'}")
    lines.append(f"Auto-merge eligible: {'yes' if note.auto_merge else 'no'}")
    lines.append(f"Opened via user PAT: {'yes' if note.used_pat else 'no (GITHUB_TOKEN)'}")
    lines.append("")
    if note.ci_approval_hint and not note.used_pat:
        lines.extend(
            [
                "CI backup: if GitHub shows action_required with no jobs, approve the CI",
                "workflow run in Actions before reviewing the PR.",
                "",
            ]
        )
    if note.is_draft:
        lines.append("Mark the PR ready for review when you want to merge.")
    elif note.auto_merge:
        lines.append("Scoped auto-merge will merge when CI and path guard are green.")
    else:
        lines.append("Review and merge when CI is green.")
    return "\n".join(lines)


def format_engineering_pr_html(note: EngineeringPrNotification) -> str:
    pat_note = (
        "Opened with user PAT — CI should start automatically."
        if note.used_pat
        else (
            "<strong>CI backup:</strong> if Actions shows "
            "<code>action_required</code> with no jobs, approve the CI run before review."
        )
    )
    draft_note = (
        "Draft PR — mark ready for review when you want to merge."
        if note.is_draft
        else (
            "Scoped auto-merge enabled when CI is green."
            if note.auto_merge
            else "Review and merge when CI is green."
        )
    )
    return f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;color:#222;max-width:720px">
  <h2>FTSE Engineering PR opened</h2>
  <ul>
    <li><strong>Task:</strong> {note.task_id}</li>
    <li><strong>Branch:</strong> {note.branch}</li>
    <li><strong>PR:</strong> <a href="{note.pr_url}">{note.pr_url}</a></li>
    <li><strong>Draft:</strong> {"yes" if note.is_draft else "no"}</li>
    <li><strong>Auto-merge:</strong> {"yes" if note.auto_merge else "no"}</li>
  </ul>
  <p>{pat_note}</p>
  <p>{draft_note}</p>
</body></html>"""


def send_engineering_pr_email(
    note: EngineeringPrNotification,
    *,
    config: EmailConfig | None = None,
) -> bool:
    """Send engineering PR alert. Returns False when SMTP is not configured."""
    try:
        resolved = config or EmailConfig.from_env()
    except RuntimeError as exc:
        logger.warning("Engineering PR email skipped: %s", exc)
        return False

    subject = f"FTSE Engineering PR — {note.task_id}"
    if note.is_draft:
        subject += " (draft)"
    send_email(
        subject=subject,
        text_body=format_engineering_pr_text(note),
        html_body=format_engineering_pr_html(note),
        config=resolved,
    )
    return True


@dataclass
class EngineeringQueueAlert:
    kind: str
    title: str
    summary: str
    task_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "summary": self.summary,
            "task_ids": self.task_ids,
        }


def collect_queue_block_alerts(
    *,
    recovery: dict[str, Any] | None = None,
    sync: dict[str, Any] | None = None,
    dispatch: dict[str, Any] | None = None,
) -> list[EngineeringQueueAlert]:
    """Build immediate email alerts for engineering queue blockers (L96)."""
    alerts: list[EngineeringQueueAlert] = []
    recovery = recovery or {}
    sync = sync or {}
    dispatch = dispatch or {}
    status = dict(dispatch.get("status") or {})

    merged = [str(task_id) for task_id in recovery.get("merged") or [] if task_id]
    if merged:
        alerts.append(
            EngineeringQueueAlert(
                kind="merged_reconcile",
                title="Merged engineering PRs reconciled",
                summary=(
                    f"Marked {len(merged)} task(s) merged from GitHub after queue drift: "
                    f"{', '.join(merged[:8])}"
                ),
                task_ids=merged,
            )
        )

    reconciled = [str(task_id) for task_id in recovery.get("reconciled") or [] if task_id]
    if reconciled:
        alerts.append(
            EngineeringQueueAlert(
                kind="orphan_reconcile",
                title="Orphaned pr_open tasks reconciled",
                summary=(
                    f"Reset {len(reconciled)} task(s) from pr_open to open because no matching "
                    "engineering PR was open: "
                    f"{', '.join(reconciled[:8])}"
                ),
                task_ids=reconciled,
            )
        )

    parked_rows = list(recovery.get("parked") or [])
    if parked_rows:
        task_ids = [str(row.get("task_id") or "") for row in parked_rows if row.get("task_id")]
        reasons = "; ".join(
            f"{row.get('task_id')}: {row.get('reason')}"
            for row in parked_rows[:5]
            if row.get("task_id")
        )
        alerts.append(
            EngineeringQueueAlert(
                kind="task_parked",
                title="Engineering task(s) parked",
                summary=reasons or f"{len(parked_rows)} task(s) moved to parked for manual review.",
                task_ids=task_ids,
            )
        )

    agent_failures = int(sync.get("recent_agent_failures") or 0)
    open_count = int(status.get("open_count") or 0)
    in_flight_pr = status.get("in_flight_pr")
    if agent_failures > 0 and open_count > 0 and not in_flight_pr:
        alerts.append(
            EngineeringQueueAlert(
                kind="agent_failure",
                title="Engineering agent sync failures",
                summary=(
                    f"{agent_failures} engineering-agent failure(s) in the last 6h while "
                    f"{open_count} open task(s) remain and no engineering PR is in flight."
                ),
            )
        )

    spend_blocked = bool(status.get("spend_blocked"))
    dispatch_reason = str(dispatch.get("reason") or "")
    if spend_blocked or "spend checkpoint" in dispatch_reason.lower():
        since = float(status.get("spend_since_checkpoint_usd") or 0.0)
        limit = float(status.get("spend_checkpoint_usd") or 0.0)
        alerts.append(
            EngineeringQueueAlert(
                kind="spend_blocked",
                title="Engineering spend checkpoint reached",
                summary=(
                    f"Agent dispatch paused at ${since:.2f} / ${limit:.2f}. "
                    "Approve checkpoint in policy or dispatch with force=true."
                ),
            )
        )

    return alerts


def format_queue_block_text(alerts: list[EngineeringQueueAlert]) -> str:
    lines = ["FTSE Engineering queue blocked", ""]
    for alert in alerts:
        lines.append(f"- {alert.title}")
        lines.append(f"  {alert.summary}")
        if alert.task_ids:
            lines.append(f"  Tasks: {', '.join(alert.task_ids)}")
        lines.append("")
    lines.append(
        "Check Actions engineering-queue / engineering-agent and merge or unpark as needed."
    )
    return "\n".join(lines).strip()


def format_queue_block_html(alerts: list[EngineeringQueueAlert]) -> str:
    items = []
    for alert in alerts:
        task_line = ""
        if alert.task_ids:
            task_line = f"<br><small>Tasks: {', '.join(alert.task_ids)}</small>"
        items.append(f"<li><strong>{alert.title}</strong><br>{alert.summary}{task_line}</li>")
    return f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;color:#222;max-width:720px">
  <h2>FTSE Engineering queue blocked</h2>
  <ul>{"".join(items)}</ul>
  <p>Check Actions <code>engineering-queue</code> / <code>engineering-agent</code> and merge or unpark as needed.</p>
</body></html>"""


def send_engineering_queue_block_email(
    alerts: list[EngineeringQueueAlert],
    *,
    config: EmailConfig | None = None,
) -> bool:
    """Send queue-block alert email. Returns False when SMTP is not configured."""
    if not alerts:
        return False
    try:
        resolved = config or EmailConfig.from_env()
    except RuntimeError as exc:
        logger.warning("Engineering queue-block email skipped: %s", exc)
        return False

    kinds = sorted({alert.kind for alert in alerts})
    subject = "FTSE Engineering queue blocked"
    if len(kinds) == 1:
        subject += f" — {kinds[0].replace('_', ' ')}"
    elif len(alerts) > 1:
        subject += f" ({len(alerts)} issues)"
    send_email(
        subject=subject,
        text_body=format_queue_block_text(alerts),
        html_body=format_queue_block_html(alerts),
        config=resolved,
    )
    return True
