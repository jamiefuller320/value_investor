"""Detect and repair engineering queue / agent synchronisation issues."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from value_investor.engineering_queue import (
    evaluate_engineering_dispatch,
    summarize_queue,
)
from value_investor.engineering_recovery import recover_engineering_queue
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    CompileScope,
    build_compiled_task_list,
    load_engineering_tasks,
    open_task_ids_dropped_by_merge,
    select_engineering_tasks,
)
from value_investor.storage import read_json, resolve_json_path, write_json

logger = logging.getLogger(__name__)

ENGINEERING_AGENT_WORKFLOW = "engineering-agent.yml"

ParseQuality = Literal["ocr", "ixbrl"]

_CH_PARSE_QUALITY_INSTRUCTION = (
    " When ch_refetch.body_parse_quality marks a filing parse_quality ocr, treat that CH "
    "body as strategic/OCR-only — not full filed accounts coverage; prefer ixbrl-tagged "
    "bodies or alternate sources for statement and note evidence."
)


def classify_ch_body_parse_quality(text: str) -> ParseQuality:
    """Classify on-disk Companies House body text for gap-fill memo discipline."""
    from value_investor.research.filings import (
        _ch_body_is_garbled_ocr,
        _ch_body_lacks_financial_depth,
    )

    if _ch_body_is_garbled_ocr(text):
        return "ocr"
    if _ch_body_lacks_financial_depth(text):
        return "ocr"
    return "ixbrl"


def collect_ch_filing_body_parse_quality(filings_dir: Path) -> list[dict[str, str]]:
    """Tag each indexed Companies House body with parse_quality ocr|ixbrl."""
    from value_investor.research.filings import _is_ch_filing_row

    filings_dir = Path(filings_dir)
    index_path = filings_dir / "filings_index.json"
    bodies_dir = filings_dir / "bodies"
    if not index_path.is_file():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []

    tags: list[dict[str, str]] = []
    for row in payload.get("filings") or []:
        if not isinstance(row, dict) or not _is_ch_filing_row(row) or not row.get("has_body"):
            continue
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            continue
        body_path = row.get("body_path")
        candidate = Path(str(body_path)) if body_path else bodies_dir / f"{row_id}.txt"
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        tags.append(
            {
                "filing_id": row_id,
                "parse_quality": classify_ch_body_parse_quality(text),
            }
        )
    return tags


def enrich_gap_fill_ch_refetch_parse_quality(
    sources_dir: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """After a successful CH refetch, stamp body parse_quality on gap_fill_source_map."""
    ch_refetch = dict(payload.get("ch_refetch") or {})
    if int(ch_refetch.get("fetched") or 0) <= 0:
        return payload

    filings_dir = Path(sources_dir) / "filings"
    tags = collect_ch_filing_body_parse_quality(filings_dir)
    if not tags:
        return payload

    ch_refetch["body_parse_quality"] = tags
    payload = dict(payload)
    payload["ch_refetch"] = ch_refetch

    instructions = str(payload.get("instructions") or "")
    if "body_parse_quality" not in instructions:
        payload["instructions"] = instructions.rstrip() + _CH_PARSE_QUALITY_INSTRUCTION

    map_path = resolve_json_path(Path(sources_dir) / "gap_fill_source_map.json")
    if map_path is not None:
        try:
            source_map = read_json(map_path)
        except (OSError, ValueError, TypeError):
            source_map = dict(payload)
        else:
            source_map = dict(source_map)
        source_map["ch_refetch"] = ch_refetch
        map_instructions = str(source_map.get("instructions") or payload.get("instructions") or "")
        if "body_parse_quality" not in map_instructions:
            map_instructions = map_instructions.rstrip() + _CH_PARSE_QUALITY_INSTRUCTION
        source_map["instructions"] = map_instructions
        write_json(map_path, source_map, compact=False, compress=False)

    return payload


def ensure_gap_fill_ch_parse_quality_hooks() -> None:
    """Wrap gap-fill source pack build so CH refetch success exports body parse_quality."""
    from value_investor.research import gap_fill_sources

    if getattr(gap_fill_sources.prepare_gap_fill_source_pack, "_ch_parse_quality_installed", False):
        return

    _original_prepare = gap_fill_sources.prepare_gap_fill_source_pack

    def _prepare_with_ch_parse_quality(**kwargs: Any) -> dict[str, Any]:
        payload = _original_prepare(**kwargs)
        try:
            return enrich_gap_fill_ch_refetch_parse_quality(Path(kwargs["sources_dir"]), payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("CH parse_quality enrichment skipped: %s", exc)
            return payload

    _prepare_with_ch_parse_quality._ch_parse_quality_installed = True  # type: ignore[attr-defined]
    gap_fill_sources.prepare_gap_fill_source_pack = _prepare_with_ch_parse_quality


@dataclass
class EngineeringSyncReport:
    dropped_open_task_ids: list[str]
    recent_agent_failures: int
    stale_dispatch_task_id: str | None
    should_redispatch: bool
    repairs: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dropped_open_task_ids": self.dropped_open_task_ids,
            "recent_agent_failures": self.recent_agent_failures,
            "stale_dispatch_task_id": self.stale_dispatch_task_id,
            "should_redispatch": self.should_redispatch,
            "repairs": self.repairs,
        }


def resolve_dispatch_task_id(
    task_id: str | None,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> str | None:
    """Return task_id when still open, otherwise the current top open task."""
    wanted = str(task_id or "").strip()
    if wanted and select_engineering_tasks(path=tasks_path, task_id=wanted):
        return wanted
    tasks = select_engineering_tasks(path=tasks_path, max_tasks=1)
    return tasks[0].id if tasks else None


def task_id_still_open(
    task_id: str | None,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> bool:
    wanted = str(task_id or "").strip()
    if not wanted:
        return False
    return bool(select_engineering_tasks(path=tasks_path, task_id=wanted))


def audit_compile_drop_risk(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    output_dir: Path = Path("output"),
    scope: CompileScope = "full",
) -> list[str]:
    """Open task ids that would be dropped if compile ran against output artifacts."""
    output_dir = Path(output_dir)
    if not (output_dir / "post_run_review.md").exists():
        return []
    existing_rows = list(load_engineering_tasks(tasks_path).get("tasks") or [])
    compiled = build_compiled_task_list(
        output_dir=output_dir,
        scope=scope,
        tasks_path=tasks_path,
    )
    return open_task_ids_dropped_by_merge(existing_rows, compiled)


def run_engineering_sync(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    output_dir: Path = Path("output"),
    open_prs: list[dict[str, Any]] | None = None,
    recent_agent_failures: list[dict[str, Any]] | None = None,
    apply: bool = False,
    repo: str | None = None,
    token: str | None = None,
    latest_success_by_workflow: dict[str, dict] | None = None,
) -> EngineeringSyncReport:
    """
    Detect queue/agent desync and optionally reconcile queue state.

    Repairs are limited to queue reconciliation — they never rewrite task payloads.
    """
    dropped = audit_compile_drop_risk(tasks_path=tasks_path, output_dir=output_dir)
    failures = list(recent_agent_failures or [])
    status = summarize_queue(tasks_path=tasks_path, open_prs=open_prs)
    repairs: list[dict[str, str]] = []

    stale_dispatch: str | None = None
    if failures and status.open_count > 0 and status.in_flight_pr is None:
        stale_dispatch = status.next_task.id if status.next_task else None

    needs_repair = bool(dropped) or (
        bool(failures) and status.open_count > 0 and status.in_flight_pr is None
    )

    if apply and needs_repair:
        recovery = recover_engineering_queue(
            tasks_path=tasks_path,
            open_prs=open_prs,
            repo=repo,
            token=token,
            recent_agent_failures=failures,
            latest_success_by_workflow=latest_success_by_workflow,
            apply=True,
        )
        if recovery.merged:
            repairs.append(
                {
                    "action": "mark_merged_pr",
                    "detail": ", ".join(recovery.merged),
                }
            )
        if recovery.cancelled:
            repairs.append(
                {
                    "action": "cancel_resolved_workflow_failure",
                    "detail": ", ".join(row.task_id for row in recovery.cancelled),
                }
            )
        if recovery.reconciled:
            repairs.append(
                {
                    "action": "reconcile_pr_open",
                    "detail": ", ".join(recovery.reconciled),
                }
            )
        if recovery.reopened:
            repairs.append(
                {
                    "action": "reopen_failed_tasks",
                    "detail": ", ".join(recovery.reopened),
                }
            )
        if recovery.parked:
            repairs.append(
                {
                    "action": "park_blocked_tasks",
                    "detail": ", ".join(row.task_id for row in recovery.parked),
                }
            )

    dispatch = evaluate_engineering_dispatch(tasks_path=tasks_path, open_prs=open_prs)
    should_redispatch = dispatch.should_dispatch and (
        needs_repair or bool(repairs) or (bool(failures) and status.open_count > 0)
    )

    return EngineeringSyncReport(
        dropped_open_task_ids=dropped,
        recent_agent_failures=len(failures),
        stale_dispatch_task_id=stale_dispatch,
        should_redispatch=should_redispatch,
        repairs=repairs,
    )


def summarize_sync_findings(
    report: EngineeringSyncReport,
    *,
    status_open_count: int,
    in_flight_pr: int | None,
) -> list[dict[str, str]]:
    """Human-readable finding summaries for ops monitor."""
    rows: list[dict[str, str]] = []
    if report.dropped_open_task_ids:
        rows.append(
            {
                "severity": "fail",
                "title": "Engineering compile would drop open tasks",
                "summary": (
                    f"{len(report.dropped_open_task_ids)} open task(s) would be removed by compile: "
                    f"{', '.join(report.dropped_open_task_ids[:5])}"
                ),
            }
        )
    if report.recent_agent_failures and status_open_count > 0 and in_flight_pr is None:
        rows.append(
            {
                "severity": "fail",
                "title": "Engineering agent sync failures",
                "summary": (
                    f"{report.recent_agent_failures} engineering-agent failure(s) in the last 6h "
                    "while open tasks remain and no engineering PR is in flight."
                ),
            }
        )
    return rows


ensure_gap_fill_ch_parse_quality_hooks()
