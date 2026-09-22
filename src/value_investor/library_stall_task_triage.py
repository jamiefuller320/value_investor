"""Analyze, annotate, supersede, and optionally reframe library ingest stall tasks."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    load_engineering_tasks,
    mark_task_status,
)
from value_investor.library_ingest_escalation import (
    library_ingest_filing_gaps,
    snapshot_library_buy_tier_filing_health,
)

logger = logging.getLogger(__name__)

LIBRARY_STALL_SOURCE = "library_ingest_stall"
_ACTIVE_STALL_STATUSES = frozenset({"open", "pr_open", "parked"})
_TASK_ID_RE = re.compile(r"^eng-(\d{8})-(\d+)$", re.IGNORECASE)

# Lane priority matches library ingest target selection (unmeasured → zero → IWB → thin).
_LANE_ORDER = ("unmeasured", "zero_body", "indexed_without_body", "thin_bodies")


@dataclass
class LibraryStallTriageAction:
    task_id: str
    action: str
    reason: str
    duplicate_of: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "task_id": self.task_id,
            "action": self.action,
            "reason": self.reason,
        }
        if self.duplicate_of:
            out["duplicate_of"] = self.duplicate_of
        return out


@dataclass
class LibraryStallTriageResult:
    cancelled: list[LibraryStallTriageAction] = field(default_factory=list)
    annotated: list[LibraryStallTriageAction] = field(default_factory=list)
    reframed: list[LibraryStallTriageAction] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cancelled": [row.to_dict() for row in self.cancelled],
            "annotated": [row.to_dict() for row in self.annotated],
            "reframed": [row.to_dict() for row in self.reframed],
            "skipped": list(self.skipped),
            "action_count": len(self.cancelled) + len(self.annotated) + len(self.reframed),
        }


def is_library_stall_engineering_row(row: dict[str, Any]) -> bool:
    return str(row.get("source") or "").strip() == LIBRARY_STALL_SOURCE


def library_stall_market_id(row: dict[str, Any]) -> str:
    evidence = row.get("evidence") or {}
    return str(evidence.get("market_id") or evidence.get("library_market") or "").strip()


def _task_id_sort_key(task_id: str) -> tuple[str, int, str]:
    match = _TASK_ID_RE.match(str(task_id or "").strip())
    if match:
        return (match.group(1), int(match.group(2)), task_id)
    return ("", 0, task_id)


def canonical_library_stall_task_id(
    tasks: list[dict[str, Any]],
    market_id: str,
) -> str | None:
    """Newest non-cancelled library stall row for ``market_id``."""
    market_id = str(market_id or "").strip()
    if not market_id:
        return None
    candidates: list[tuple[tuple[str, int, str], str]] = []
    for row in tasks:
        if not is_library_stall_engineering_row(row):
            continue
        if library_stall_market_id(row) != market_id:
            continue
        status = str(row.get("status") or "")
        if status == "cancelled":
            continue
        task_id = str(row.get("id") or "")
        if not task_id:
            continue
        candidates.append((_task_id_sort_key(task_id), task_id))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1]


def find_superseded_library_stall_canonical(
    row: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> str | None:
    """When ``row`` is an older duplicate stall task for its market, return the canonical id."""
    if not is_library_stall_engineering_row(row):
        return None
    market_id = library_stall_market_id(row)
    if not market_id:
        return None
    task_id = str(row.get("id") or "")
    canonical = canonical_library_stall_task_id(tasks, market_id)
    if not canonical or canonical == task_id:
        return None
    if _task_id_sort_key(task_id) >= _task_id_sort_key(canonical):
        return None
    return canonical


_STALL_TRIAGE_STABLE_KEYS = (
    "market_id",
    "filing_gaps",
    "lanes",
    "active_lanes",
    "bundled",
    "focus_ticker",
    "focus_lane",
    "reburn_loop",
    "recommendations",
)


def _stall_triage_semantics_changed(prior: dict[str, Any], current: dict[str, Any]) -> bool:
    """Ignore timestamp-only drift between recover-queue passes."""
    return any(prior.get(key) != current.get(key) for key in _STALL_TRIAGE_STABLE_KEYS)


def _lane_counts(health: dict[str, Any]) -> dict[str, int]:
    return {
        "unmeasured": int(health.get("unmeasured_buy_tier") or 0),
        "zero_body": int(health.get("zero_body_buy_tier") or 0),
        "indexed_without_body": int(health.get("indexed_without_body") or 0),
        "thin_bodies": int(health.get("thin_body_buy_tier") or 0),
    }


def _pick_focus_ticker(health: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(ticker, lane)`` for the highest-priority gap lane."""
    iwb_by = health.get("indexed_without_body_by_ticker") or {}
    if not isinstance(iwb_by, dict):
        iwb_by = {}
    for lane in _LANE_ORDER:
        if lane == "unmeasured":
            tickers = list(health.get("unmeasured_tickers") or [])
        elif lane == "zero_body":
            tickers = list(health.get("zero_body_tickers") or [])
        elif lane == "thin_bodies":
            tickers = list(health.get("thin_body_tickers") or [])
        elif lane == "indexed_without_body":
            tickers = list(health.get("indexed_without_body_tickers") or [])
            if tickers and iwb_by:
                tickers = sorted(tickers, key=lambda t: (-int(iwb_by.get(t) or 0), str(t)))
            elif iwb_by:
                tickers = sorted(iwb_by.keys(), key=lambda t: (-int(iwb_by.get(t) or 0), str(t)))
            else:
                tickers = []
        else:
            tickers = []
        if tickers:
            return str(tickers[0]), lane
    return None, None


def analyze_library_stall_task(
    row: dict[str, Any],
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    refresh_health: bool = True,
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``stall_triage`` payload for UI / recovery (no queue writes)."""
    market_id = library_stall_market_id(row)
    evidence = dict(row.get("evidence") or {})
    filing_health = dict(health or evidence.get("filing_health") or {})
    if refresh_health and market_id:
        try:
            filing_health = snapshot_library_buy_tier_filing_health(
                market_id,
                library_root=library_root,
            )
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            logger.debug("stall triage health refresh failed for %s: %s", market_id, exc)

    lanes = _lane_counts(filing_health)
    active_lanes = [name for name, count in lanes.items() if count > 0]
    focus_ticker, focus_lane = _pick_focus_ticker(filing_health)
    filing_gaps = library_ingest_filing_gaps(filing_health)
    bundled = len(active_lanes) > 1 or filing_gaps >= 8

    parked_policy = str(row.get("parked_policy") or "").strip()
    reburn = (
        parked_policy == "reburn_loop" or "reburn" in str(row.get("parked_reason") or "").lower()
    )

    recommendations: list[str] = []
    if focus_ticker and focus_lane:
        recommendations.append(f"narrow_reframe:{focus_ticker}:{focus_lane}")
        if focus_lane == "indexed_without_body":
            recommendations.append(f"parked_hunter:{focus_ticker}")
        if focus_lane in {"unmeasured", "zero_body"}:
            recommendations.append("intensive_pin_or_allowlist_batch")
    if bundled:
        recommendations.append("split_by_ticker_not_broad_market_task")

    return {
        "analyzed_at": datetime.now(UTC).isoformat(),
        "market_id": market_id,
        "task_id": str(row.get("id") or ""),
        "status": str(row.get("status") or ""),
        "filing_gaps": filing_gaps,
        "lanes": lanes,
        "active_lanes": active_lanes,
        "bundled": bundled,
        "focus_ticker": focus_ticker,
        "focus_lane": focus_lane,
        "reburn_loop": reburn,
        "recommendations": recommendations,
        "filing_health_snapshot_at": filing_health.get("snapshot_at"),
        "doc": "docs/ops/library-ingest-escalation.md#library-stall-task-triage",
    }


def library_stall_park_is_resolved(
    row: dict[str, Any],
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
) -> bool:
    if not is_library_stall_engineering_row(row):
        return False
    market_id = library_stall_market_id(row)
    if not market_id:
        return False
    try:
        health = snapshot_library_buy_tier_filing_health(market_id, library_root=library_root)
    except (OSError, ValueError, TypeError, RuntimeError):
        return False
    return library_ingest_filing_gaps(health) <= 0


def _narrow_title_summary(
    *,
    market_id: str,
    focus_ticker: str,
    focus_lane: str,
    filing_gaps: int,
) -> tuple[str, str]:
    title = (f"Library ingest stall ({market_id}): narrow fix for {focus_ticker} ({focus_lane})")[
        :160
    ]
    summary = (
        f"Reframed from broad market stall task — focus {focus_ticker} "
        f"({focus_lane}) while {filing_gaps} buy-tier filing gaps remain for {market_id}. "
        f"Add source/parser coverage or allowlist bodies for this ticker; verify with "
        f"ftse-library ingest-loop --market {market_id}."
    )[:500]
    return title, summary


def reframe_bundled_library_stall_task(
    row: dict[str, Any],
    triage: dict[str, Any],
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    apply: bool = True,
) -> LibraryStallTriageAction | None:
    """Rewrite a parked bundled stall task in place to a single-ticker scope."""
    if not triage.get("bundled") or not triage.get("focus_ticker"):
        return None
    if triage.get("reburn_loop"):
        return None
    if str(row.get("status") or "") != "parked":
        return None
    prior_evidence = row.get("evidence") or {}
    if not isinstance(prior_evidence, dict):
        prior_evidence = {}
    if prior_evidence.get("narrow_reframe_at"):
        return None

    task_id = str(row.get("id") or "")
    market_id = str(triage.get("market_id") or "")
    focus_ticker = str(triage.get("focus_ticker") or "")
    focus_lane = str(triage.get("focus_lane") or "gap")
    filing_gaps = int(triage.get("filing_gaps") or 0)
    title, summary = _narrow_title_summary(
        market_id=market_id,
        focus_ticker=focus_ticker,
        focus_lane=focus_lane,
        filing_gaps=filing_gaps,
    )
    evidence = dict(row.get("evidence") or {})
    evidence["stall_triage"] = triage
    evidence["focus_ticker"] = focus_ticker
    evidence["focus_lane"] = focus_lane
    evidence["narrow_reframe_at"] = datetime.now(UTC).isoformat()
    evidence["prior_title"] = str(row.get("title") or "")

    reason = f"narrow reframe → {focus_ticker} ({focus_lane})"
    if apply:
        mark_task_status(
            task_id,
            "parked",
            path=tasks_path,
            committed_path=tasks_path,
            title=title,
            summary=summary,
            evidence=evidence,
        )
    return LibraryStallTriageAction(task_id=task_id, action="reframe_narrow", reason=reason)


def triage_library_stall_tasks(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    apply: bool = True,
    now: datetime | None = None,
    auto_cancel_superseded: bool = True,
    auto_cancel_resolved: bool = True,
    auto_annotate: bool = True,
    auto_reframe_bundled: bool = False,
) -> LibraryStallTriageResult:
    """Run analysis / supersession / optional in-place reframe for library stall rows."""
    now = now or datetime.now(UTC)
    result = LibraryStallTriageResult()
    data = load_engineering_tasks(tasks_path)
    tasks = list(data.get("tasks") or [])

    for row in tasks:
        if not is_library_stall_engineering_row(row):
            continue
        status = str(row.get("status") or "")
        if status not in _ACTIVE_STALL_STATUSES:
            continue
        task_id = str(row.get("id") or "")
        if not task_id:
            continue

        if auto_cancel_superseded and status == "parked":
            canonical = find_superseded_library_stall_canonical(row, tasks)
            if canonical:
                cancel_reason = (
                    f"tier-1 housekeep: superseded library stall — duplicate of {canonical}"
                )
                if apply:
                    mark_task_status(
                        task_id,
                        "cancelled",
                        path=tasks_path,
                        committed_path=tasks_path,
                        parked_policy="duplicate",
                        duplicate_of=canonical,
                        cancelled_at=now.isoformat(),
                        cancelled_reason=cancel_reason,
                        cancelled_policy="superseded_library_stall",
                    )
                result.cancelled.append(
                    LibraryStallTriageAction(
                        task_id=task_id,
                        action="cancel_superseded_library_stall",
                        reason=cancel_reason,
                        duplicate_of=canonical,
                    )
                )
                continue

        if (
            auto_cancel_resolved
            and status == "parked"
            and library_stall_park_is_resolved(row, library_root=library_root)
        ):
            cancel_reason = (
                "tier-1 housekeep: library stall resolved — no buy-tier filing gaps remain"
            )
            if apply:
                mark_task_status(
                    task_id,
                    "cancelled",
                    path=tasks_path,
                    committed_path=tasks_path,
                    cancelled_at=now.isoformat(),
                    cancelled_reason=cancel_reason,
                    cancelled_policy="resolved_library_stall",
                )
            result.cancelled.append(
                LibraryStallTriageAction(
                    task_id=task_id,
                    action="cancel_resolved_library_stall",
                    reason=cancel_reason,
                )
            )
            continue

        if not auto_annotate and not auto_reframe_bundled:
            continue

        triage = analyze_library_stall_task(row, library_root=library_root, refresh_health=True)
        prior = (row.get("evidence") or {}).get("stall_triage") or {}
        if not isinstance(prior, dict):
            prior = {}
        triage_changed = _stall_triage_semantics_changed(prior, triage)

        if auto_reframe_bundled:
            reframed = reframe_bundled_library_stall_task(
                row, triage, tasks_path=tasks_path, apply=apply
            )
            if reframed is not None:
                result.reframed.append(reframed)
                continue

        if auto_annotate and triage_changed:
            evidence = dict(row.get("evidence") or {})
            evidence["stall_triage"] = triage
            reason = (
                f"stall_triage: focus={triage.get('focus_ticker')} "
                f"bundled={triage.get('bundled')} gaps={triage.get('filing_gaps')}"
            )
            if apply:
                mark_task_status(
                    task_id,
                    status,
                    path=tasks_path,
                    committed_path=tasks_path,
                    evidence=evidence,
                )
            result.annotated.append(
                LibraryStallTriageAction(
                    task_id=task_id,
                    action="annotate_stall_triage",
                    reason=reason,
                )
            )

    return result


__all__ = [
    "LIBRARY_STALL_SOURCE",
    "LibraryStallTriageAction",
    "LibraryStallTriageResult",
    "analyze_library_stall_task",
    "canonical_library_stall_task_id",
    "find_superseded_library_stall_canonical",
    "is_library_stall_engineering_row",
    "library_stall_market_id",
    "library_stall_park_is_resolved",
    "reframe_bundled_library_stall_task",
    "triage_library_stall_tasks",
]
