"""Weekday ingest-assess-improve loop for live FTSE buy-tier filing coverage."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.engineering_queue import snapshot_ingest_health
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    compile_ingest_engineering_tasks_micro,
    load_engineering_tasks,
)
from value_investor.research.gap_fill import DEFAULT_SUGGESTIONS_PATH
from value_investor.research.ingest_improvement import (
    DEFAULT_INGEST_IMPROVEMENT_CAP,
    DEFAULT_WEEKDAY_BOOTSTRAP_SEED_CAP,
    IngestImprovementSummary,
    run_ingest_improvement_pass,
)
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_HEALTH_LOG_PATH = Path("docs/data/ingest_health_log.json")
DEFAULT_RESEARCH_ROOTS = [
    Path("docs/data/research"),
    Path("output/research"),
    Path("docs/data/library/markets"),
]
HEALTH_LOG_KEEP = 52
DEFAULT_STALL_RUNS = 2
DEFAULT_WEEKDAY_MAX_RUNTIME_SECONDS = 2400.0


def load_health_log_payload(
    path: Path,
    *,
    backup_corrupt: bool = True,
) -> dict[str, Any]:
    """
    Load ingest health log JSON, recovering from corrupt or malformed files.

    When the file cannot be parsed or does not have a list ``entries`` field,
    optionally copies the raw bytes to a sibling ``*.corrupt.<timestamp>.json``
    file before returning an empty payload.
    """
    path = Path(path)
    if not path.exists():
        return {"entries": []}

    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Corrupt ingest health log at %s: %s", path, exc)
        if backup_corrupt:
            _backup_corrupt_health_log(path)
        return {"entries": []}

    if not isinstance(payload, dict):
        logger.warning("Ingest health log at %s is not a JSON object — resetting", path)
        if backup_corrupt:
            _backup_corrupt_health_log(path)
        return {"entries": []}

    entries = payload.get("entries")
    if entries is None:
        return {"entries": []}
    if not isinstance(entries, list):
        logger.warning("Ingest health log entries at %s is not a list — resetting", path)
        if backup_corrupt:
            _backup_corrupt_health_log(path)
        return {"entries": []}

    return payload


def _backup_corrupt_health_log(path: Path) -> Path | None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.stem}.corrupt.{stamp}{path.suffix}")
    try:
        backup.write_bytes(path.read_bytes())
        logger.warning("Backed up corrupt ingest health log to %s", backup)
        return backup
    except OSError:
        logger.exception("Failed to back up corrupt ingest health log at %s", path)
        return None


@dataclass
class IngestLoopResult:
    health_before: dict[str, Any]
    health_after: dict[str, Any]
    ingest_summary: IngestImprovementSummary | None
    micro_compiled: bool
    micro_compile: dict[str, Any] = field(default_factory=dict)
    stalled: bool = False
    partial: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "health_before": self.health_before,
            "health_after": self.health_after,
            "ingest_summary": self.ingest_summary.to_dict() if self.ingest_summary else None,
            "micro_compiled": self.micro_compiled,
            "micro_compile": self.micro_compile,
            "stalled": self.stalled,
            "partial": self.partial,
        }
        if self.error:
            payload["error"] = self.error
        return payload


def reports_from_latest(path: Path = DEFAULT_LATEST_PATH) -> list[CompanyReport]:
    if not path.exists():
        return []
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return []
    reports: list[CompanyReport] = []
    for row in payload.get("reports") or []:
        if not isinstance(row, dict) or not row.get("ticker"):
            continue
        try:
            reports.append(CompanyReport.from_dict(row))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping latest.json report row: %s", exc)
    return reports


def append_health_log_entry(
    entry: dict[str, Any],
    *,
    path: Path = DEFAULT_HEALTH_LOG_PATH,
    keep: int = HEALTH_LOG_KEEP,
) -> dict[str, Any]:
    path = Path(path)
    payload = load_health_log_payload(path)
    entries = list(payload.get("entries") or [])
    entries.append(entry)
    payload["entries"] = entries[-max(1, int(keep)) :]
    payload["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)
    return payload


def ingest_health_stalled(
    log_path: Path = DEFAULT_HEALTH_LOG_PATH,
    *,
    min_runs: int = DEFAULT_STALL_RUNS,
) -> bool:
    """True when buy-tier zero-body count is unchanged across recent weekday runs."""
    if not log_path.exists():
        return False
    try:
        payload = read_json(log_path)
    except (OSError, ValueError, TypeError):
        return False
    entries = list(payload.get("entries") or [])
    if len(entries) < max(2, int(min_runs)):
        return False
    recent = entries[-max(2, int(min_runs)) :]
    zero_counts = [
        int((row.get("health_after") or {}).get("zero_body_buy_tier") or 0) for row in recent
    ]
    if not zero_counts or zero_counts[0] <= 0:
        return False
    if len(set(zero_counts)) != 1:
        return False
    for row in recent:
        before = int((row.get("health_before") or {}).get("zero_body_buy_tier") or zero_counts[0])
        after = int((row.get("health_after") or {}).get("zero_body_buy_tier") or zero_counts[0])
        if after < before:
            return False
    return True


def has_open_ingest_engineering_tasks(
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> bool:
    payload = load_engineering_tasks(tasks_path)
    for row in payload.get("tasks") or []:
        if str(row.get("area") or "").lower() != "ingest":
            continue
        if str(row.get("status") or "open") in {"open", "pr_open"}:
            return True
    return False


def run_weekday_ingest_loop(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    data_dir: Path = DEFAULT_DATA_DIR,
    health_log_path: Path = DEFAULT_HEALTH_LOG_PATH,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    research_roots: list[Path] | None = None,
    max_targets: int = DEFAULT_INGEST_IMPROVEMENT_CAP,
    stall_runs: int = DEFAULT_STALL_RUNS,
    micro_compile_max_tasks: int = 3,
    market: str = "ftse350",
    bootstrap_seed_cap: int = DEFAULT_WEEKDAY_BOOTSTRAP_SEED_CAP,
    max_runtime_seconds: float = DEFAULT_WEEKDAY_MAX_RUNTIME_SECONDS,
) -> IngestLoopResult:
    """
    Run bounded ingest improvement on the current buy-tier universe, log health,
    and micro-compile ingest engineering tasks when coverage stalls.
    """
    roots = research_roots or list(DEFAULT_RESEARCH_ROOTS)
    health_before = snapshot_ingest_health(latest_path=latest_path, research_roots=roots)
    reports = reports_from_latest(latest_path)

    ingest_summary: IngestImprovementSummary | None = None
    if reports:
        ingest_summary = run_ingest_improvement_pass(
            reports=reports,
            output_dir=data_dir,
            market=market,
            max_targets=max_targets,
            suggestions_path=suggestions_path,
            bootstrap_seed_cap=bootstrap_seed_cap,
            max_runtime_seconds=max_runtime_seconds,
        )
    else:
        logger.warning("No reports in %s — skipping ingest-improvement pass", latest_path)

    health_after = snapshot_ingest_health(latest_path=latest_path, research_roots=roots)
    improved_tickers = []
    if ingest_summary is not None:
        improved_tickers = [
            str(row.get("ticker"))
            for row in ingest_summary.results
            if row.get("improved")
        ]

    append_health_log_entry(
        {
            "run_at": datetime.now(UTC).isoformat(),
            "source": "weekday_ingest_loop",
            "health_before": health_before,
            "health_after": health_after,
            "delta_zero_body": int(health_before.get("zero_body_buy_tier") or 0)
            - int(health_after.get("zero_body_buy_tier") or 0),
            "ingest_targets": len(ingest_summary.targets) if ingest_summary else 0,
            "ingest_improved": len(improved_tickers),
            "improved_tickers": improved_tickers,
        },
        path=health_log_path,
    )

    stalled = ingest_health_stalled(health_log_path, min_runs=stall_runs)
    micro_compiled = False
    micro_compile: dict[str, Any] = {"skipped": True}
    if stalled and not has_open_ingest_engineering_tasks(tasks_path):
        micro_compile = compile_ingest_engineering_tasks_micro(
            suggestions_path=suggestions_path,
            max_tasks=micro_compile_max_tasks,
            committed_path=tasks_path,
            tasks_path=tasks_path,
            latest_path=latest_path,
        )
        micro_compiled = int(micro_compile.get("compiled_count") or 0) > 0
    elif stalled:
        micro_compile = {"skipped": True, "reason": "open ingest engineering task already queued"}
    else:
        micro_compile = {"skipped": True, "reason": "ingest health not stalled"}

    partial = bool(ingest_summary and ingest_summary.partial)

    return IngestLoopResult(
        health_before=health_before,
        health_after=health_after,
        ingest_summary=ingest_summary,
        micro_compiled=micro_compiled,
        micro_compile=micro_compile,
        stalled=stalled,
        partial=partial,
    )
