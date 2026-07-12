"""Pre-flight checks before the first weekly production run."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from value_investor.backtest import load_run_snapshots


@dataclass
class PreflightCheck:
    name: str
    status: str  # ok | warn | fail
    detail: str


@dataclass
class PreflightReport:
    checks: list[PreflightCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.status != "fail" for check in self.checks)

    def to_text(self) -> str:
        lines = ["FTSE 100 Value Investor — preflight", "=" * 48, ""]
        for check in self.checks:
            prefix = {"ok": "✓", "warn": "!", "fail": "✗"}.get(check.status, "?")
            lines.append(f"{prefix} {check.name}: {check.detail}")
        lines.append("")
        lines.append("Ready for weekly run." if self.ok else "Fix failures before the weekly run.")
        return "\n".join(lines)


def run_preflight(
    output_dir: Path,
    *,
    require_email: bool = False,
    require_agents: bool = False,
) -> PreflightReport:
    report = PreflightReport()
    output_dir = Path(output_dir)

    if output_dir.exists() and os.access(output_dir, os.W_OK):
        report.checks.append(PreflightCheck("output_dir", "ok", f"Writable: {output_dir.resolve()}"))
    else:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            report.checks.append(PreflightCheck("output_dir", "ok", f"Created: {output_dir.resolve()}"))
        except OSError as err:
            report.checks.append(PreflightCheck("output_dir", "fail", str(err)))

    email_vars = ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"]
    missing_email = [name for name in email_vars if not os.environ.get(name)]
    if not missing_email:
        report.checks.append(PreflightCheck("smtp", "ok", "SMTP secrets present"))
    elif require_email:
        report.checks.append(
            PreflightCheck("smtp", "fail", f"Missing: {', '.join(missing_email)}")
        )
    else:
        report.checks.append(
            PreflightCheck(
                "smtp",
                "warn",
                f"Email not configured ({', '.join(missing_email)}) — use --dry-run or set secrets",
            )
        )

    if os.environ.get("CURSOR_API_KEY"):
        report.checks.append(PreflightCheck("cursor_api", "ok", "CURSOR_API_KEY set"))
    elif require_agents:
        report.checks.append(PreflightCheck("cursor_api", "fail", "CURSOR_API_KEY required for agents"))
    else:
        report.checks.append(
            PreflightCheck(
                "cursor_api",
                "warn",
                "CURSOR_API_KEY not set — deep analysis and research updates will be skipped",
            )
        )

    snapshots = load_run_snapshots(output_dir)
    if len(snapshots) >= 2:
        report.checks.append(
            PreflightCheck(
                "history",
                "ok",
                f"{len(snapshots)} archived weekly runs (backtest, simulation, historical analysis enabled)",
            )
        )
    elif len(snapshots) == 1:
        report.checks.append(
            PreflightCheck(
                "history",
                "warn",
                "1 archived run — backtest/historical analysis need a second weekly run",
            )
        )
    else:
        report.checks.append(
            PreflightCheck(
                "history",
                "warn",
                "No archived runs yet — first screen seeds history; performance metrics appear from week 2",
            )
        )

    research_dir = output_dir / "research"
    memo_count = len(list(research_dir.glob("*/research.json"))) if research_dir.exists() else 0
    if memo_count:
        report.checks.append(
            PreflightCheck("research_memos", "ok", f"{memo_count} research memo(s) on disk")
        )
    else:
        report.checks.append(
            PreflightCheck(
                "research_memos",
                "warn",
                "No research memos yet — run ftse-research or ftse-email --research-docs on first strong buys",
            )
        )

    timeline_count = sum(
        1 for ticker_dir in research_dir.glob("*") if (ticker_dir / "timeline.json").exists()
    ) if research_dir.exists() else 0
    if timeline_count:
        report.checks.append(
            PreflightCheck(
                "research_timeline",
                "ok",
                f"{timeline_count} ticker timeline(s) for point-in-time replay",
            )
        )
    elif memo_count:
        report.checks.append(
            PreflightCheck(
                "research_timeline",
                "warn",
                "Memos exist but no revision timelines — re-save research to archive revisions",
            )
        )

    docs_data = Path("docs/data/latest.json")
    if docs_data.exists():
        report.checks.append(PreflightCheck("dashboard", "ok", "Dashboard data present in docs/data/"))
    else:
        report.checks.append(
            PreflightCheck(
                "dashboard",
                "warn",
                "No docs/data/latest.json — run ftse-publish or ftse-email --publish-dashboard after first screen",
            )
        )

    return report
