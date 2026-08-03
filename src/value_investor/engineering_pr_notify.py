"""SMTP alerts when the engineering agent opens a supervised PR."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from value_investor.emailer import EmailConfig, send_email

logger = logging.getLogger(__name__)


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
    <li><strong>Draft:</strong> {'yes' if note.is_draft else 'no'}</li>
    <li><strong>Auto-merge:</strong> {'yes' if note.auto_merge else 'no'}</li>
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
