"""FTSE-equivalent learning-depth assessment for offline library markets.

S&P 500 must match the live FTSE shard on **canonical** filing indexes and
trajectory change indicators. Other-shard bodies (e.g. nasdaq100 overlap)
do not count as parity.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.backtest import load_run_snapshots
from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.library_ingest_dispatch import ingest_parity_met, sprint_ingest_complete
from value_investor.library_ingest_escalation import (
    DEFAULT_FTSE_EQUIVALENT_MARKETS,
    ftse_equivalent_markets,
    is_ftse_equivalent_market,
    snapshot_library_buy_tier_filing_health,
)
from value_investor.library_screen import screen_dir_for
from value_investor.library_sim import iter_library_screen_runs
from value_investor.storage import write_json
from value_investor.trajectory_evidence import (
    BOUNDARY_FILENAME,
    REVIEW_FILENAME,
    TRANSITIONS_FILENAME,
    build_boundary_watch_panel,
    build_model_focus_candidates,
    build_transition_events,
    format_trajectory_evidence_markdown,
    summarize_boundary_panel,
    summarize_transition_outcomes,
)

LEARNING_DEPTH_FILENAME = "learning_depth.json"
CANONICAL_RESEARCH_PATH_TMPL = "docs/data/library/markets/{market_id}/screen/research/{{TICKER}}/"
TRAJECTORY_READY_MIN_SPAN_WEEKS = 12.0
TRAJECTORY_READY_MIN_UNIQUE_DAYS = 12
SCREEN_STALE_AFTER_DAYS = 8


def learning_depth_path(library_root: Path, market_id: str) -> Path:
    return Path(library_root) / "markets" / market_id / LEARNING_DEPTH_FILENAME


def assess_screen_archive_span(
    library_root: Path,
    market_id: str,
    *,
    now: datetime | None = None,
    stale_after_days: int = SCREEN_STALE_AFTER_DAYS,
) -> dict[str, Any]:
    """Count dated screen-lite archives, unique days, and calendar span."""
    screen_dir = screen_dir_for(library_root, market_id)
    runs = iter_library_screen_runs(screen_dir)
    dates = sorted({row[0].date() for row in runs})
    as_of = now or datetime.now(UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    last_screen = dates[-1].isoformat() if dates else None
    first_screen = dates[0].isoformat() if dates else None
    span_days = (dates[-1] - dates[0]).days if len(dates) >= 2 else 0
    span_weeks = round(span_days / 7.0, 2)
    stale = False
    if dates:
        stale = (as_of.date() - dates[-1]) > timedelta(days=max(0, int(stale_after_days)))
    return {
        "archive_files": len(runs),
        "unique_days": len(dates),
        "span_days": span_days,
        "span_weeks": span_weeks,
        "first_screen": first_screen,
        "last_screen": last_screen,
        "stale": stale,
        "stale_after_days": int(stale_after_days),
    }


def _reports_for_trajectory(
    library_root: Path,
    market_id: str,
    snapshots: list[Any],
) -> list[dict[str, Any]]:
    try:
        from value_investor.library_screen import library_research_reports
        from value_investor.market_paper_adapter import load_library_screen_result

        result = load_library_screen_result(library_root, market_id)
        reports = [row.to_dict() for row in library_research_reports(result)]
        if reports:
            return reports
    except (FileNotFoundError, OSError, ValueError, TypeError):
        pass
    if snapshots:
        return list(getattr(snapshots[-1], "signals", None) or [])
    return []


def write_library_trajectory_artifacts(
    library_root: Path,
    market_id: str,
    *,
    snapshots: list[Any] | None = None,
    run_at: datetime | None = None,
) -> dict[str, Any]:
    """Persist trajectory_* JSON under markets/{id}/screen/ from library snapshots."""
    screen_dir = screen_dir_for(library_root, market_id)
    screen_dir.mkdir(parents=True, exist_ok=True)
    effective_run_at = run_at or datetime.now(UTC)
    if snapshots is None:
        snapshots = load_run_snapshots(screen_dir)
    events = build_transition_events(snapshots)
    reports = _reports_for_trajectory(library_root, market_id, snapshots)
    boundary = build_boundary_watch_panel(reports, snapshots=snapshots)
    boundary_summary = summarize_boundary_panel(boundary)
    outcome_summary = summarize_transition_outcomes(events)
    focus_candidates = build_model_focus_candidates(outcome_summary)

    transitions_path = screen_dir / TRANSITIONS_FILENAME
    boundary_path = screen_dir / BOUNDARY_FILENAME
    review_path = screen_dir / REVIEW_FILENAME
    review_md_path = screen_dir / "trajectory_evidence_review.md"

    transitions_doc = {
        "schema_version": 1,
        "scope": "library_trajectory_transitions",
        "market_id": market_id,
        "observe_only": True,
        "generated_at": effective_run_at.isoformat(),
        "snapshot_count": len(snapshots),
        "event_count": len(events),
        "events": events,
    }
    boundary_doc = {
        "schema_version": 2,
        "scope": "library_trajectory_boundary_watch",
        "market_id": market_id,
        "observe_only": True,
        "generated_at": effective_run_at.isoformat(),
        "panel_count": len(boundary),
        "summary": boundary_summary,
        "note": (
            "Names near tier boundaries (core tags required) — not the full hold tier. "
            "Generated from library screen snapshots; nasdaq100 overlap is not in scope."
        ),
        "panel": boundary,
    }
    review_doc = {
        "schema_version": 1,
        "scope": "library_trajectory_evidence_review",
        "market_id": market_id,
        "observe_only": True,
        "generated_at": effective_run_at.isoformat(),
        "snapshot_count": len(snapshots),
        "transition_event_count": len(events),
        "boundary_watch_count": len(boundary),
        "boundary_summary": boundary_summary,
        "outcome_summary": outcome_summary,
        "model_focus_candidates": focus_candidates,
    }
    write_json(transitions_path, transitions_doc, compact=True)
    write_json(boundary_path, boundary_doc, compact=True)
    write_json(review_path, review_doc, compact=True)
    review_md_path.write_text(format_trajectory_evidence_markdown(review_doc), encoding="utf-8")
    return {
        "generated": True,
        "snapshot_count": len(snapshots),
        "event_count": len(events),
        "boundary_count": len(boundary),
        "transitions_path": str(transitions_path),
        "boundary_path": str(boundary_path),
        "review_path": str(review_path),
        "outcome_summary": outcome_summary,
    }


def refresh_library_trajectory_artifacts(
    library_root: Path,
    market_id: str,
) -> dict[str, Any]:
    return write_library_trajectory_artifacts(library_root, market_id)


def _assess_trajectory(
    library_root: Path,
    market_id: str,
    screen: dict[str, Any],
    *,
    write: bool,
) -> dict[str, Any]:
    screen_dir = screen_dir_for(library_root, market_id)
    snapshots = load_run_snapshots(screen_dir)
    written: dict[str, Any] | None = None
    if write:
        written = write_library_trajectory_artifacts(
            library_root,
            market_id,
            snapshots=snapshots,
        )
        event_count = int(written.get("event_count") or 0)
        boundary_count = int(written.get("boundary_count") or 0)
        snapshot_count = int(written.get("snapshot_count") or 0)
    else:
        events = build_transition_events(snapshots) if snapshots else []
        reports = _reports_for_trajectory(library_root, market_id, snapshots)
        boundary = (
            build_boundary_watch_panel(reports, snapshots=snapshots) if snapshots or reports else []
        )
        event_count = len(events)
        boundary_count = len(boundary)
        snapshot_count = len(snapshots)

    span_weeks = float(screen.get("span_weeks") or 0.0)
    unique_days = int(screen.get("unique_days") or 0)
    trajectory_ready = (
        span_weeks >= TRAJECTORY_READY_MIN_SPAN_WEEKS
        and unique_days >= TRAJECTORY_READY_MIN_UNIQUE_DAYS
    )
    if trajectory_ready:
        ready_reason = (
            f"span {span_weeks}w >= {TRAJECTORY_READY_MIN_SPAN_WEEKS:g}w and "
            f"unique_days={unique_days} >= {TRAJECTORY_READY_MIN_UNIQUE_DAYS}"
        )
    else:
        ready_reason = (
            f"span {span_weeks}w < {TRAJECTORY_READY_MIN_SPAN_WEEKS:g}w "
            f"(unique_days={unique_days}; "
            f"need {TRAJECTORY_READY_MIN_UNIQUE_DAYS} unique days over "
            f"{TRAJECTORY_READY_MIN_SPAN_WEEKS:g} weeks)"
        )
    payload = {
        "generated": bool(written),
        "can_generate": snapshot_count > 1 or int(screen.get("archive_files") or 0) > 1,
        "snapshot_count": snapshot_count,
        "event_count": event_count,
        "boundary_count": boundary_count,
        "trajectory_ready": trajectory_ready,
        "ready_reason": ready_reason,
        "min_span_weeks": TRAJECTORY_READY_MIN_SPAN_WEEKS,
        "min_unique_days": TRAJECTORY_READY_MIN_UNIQUE_DAYS,
    }
    if written:
        payload["paths"] = {
            "transitions": written.get("transitions_path"),
            "boundary": written.get("boundary_path"),
            "review": written.get("review_path"),
        }
    return payload


def assess_library_learning_depth(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy: dict[str, Any] | None = None,
    write: bool = False,
    write_trajectory: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assess filing + trajectory readiness against the live FTSE bar."""
    library_root = Path(library_root)
    ftse_equivalent = is_ftse_equivalent_market(market_id, policy)
    health = snapshot_library_buy_tier_filing_health(
        market_id,
        library_root=library_root,
        policy=policy,
    )
    # Learning-depth filing_ready treats parked leftover thin/IWB as out of pool.
    # True FTSE maintenance parity (all four raw counts zero) stays on ingest_parity_met.
    filing_ready = sprint_ingest_complete(health)

    screen = assess_screen_archive_span(library_root, market_id, now=now)
    trajectory = _assess_trajectory(
        library_root,
        market_id,
        screen,
        write=write_trajectory,
    )
    learning_ready = bool(filing_ready and trajectory.get("trajectory_ready"))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "market_id": market_id,
        "assessed_at": (now or datetime.now(UTC)).isoformat(),
        "ftse_equivalent": ftse_equivalent,
        "coverage_scope": health.get("coverage_scope"),
        "canonical_path": CANONICAL_RESEARCH_PATH_TMPL.format(market_id=market_id),
        "note": (
            "Canonical screen research only. Other-shard filing indexes "
            "(e.g. nasdaq100) are not measured for FTSE-equivalent parity."
        ),
        "filing": {
            **{
                k: health.get(k)
                for k in (
                    "buy_tier_count",
                    "unmeasured_buy_tier",
                    "zero_body_buy_tier",
                    "thin_body_buy_tier",
                    "indexed_without_body",
                    "bodies_min",
                    "bodies_median",
                    "bodies_max",
                    "unmeasured_tickers",
                    "zero_body_tickers",
                    "thin_body_tickers",
                    "indexed_without_body_tickers",
                    "parked_tickers",
                    "ingest_exhausted",
                    "effective_thin_body_buy_tier",
                    "effective_indexed_without_body",
                )
            },
            "filing_ready": filing_ready,
            "ingest_parity_met": ingest_parity_met(health),
            "ingest_sprint_complete": sprint_ingest_complete(health),
        },
        "screen": screen,
        "trajectory": trajectory,
        "unmeasured_buy_tier": int(health.get("unmeasured_buy_tier") or 0),
        "unmeasured_tickers": list(health.get("unmeasured_tickers") or []),
        "filing_ready": filing_ready,
        "trajectory_ready": bool(trajectory.get("trajectory_ready")),
        "learning_ready": learning_ready,
    }
    if write:
        path = learning_depth_path(library_root, market_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload, compact=False)
        payload["path"] = str(path)
    return payload


__all__ = [
    "CANONICAL_RESEARCH_PATH_TMPL",
    "DEFAULT_FTSE_EQUIVALENT_MARKETS",
    "LEARNING_DEPTH_FILENAME",
    "SCREEN_STALE_AFTER_DAYS",
    "TRAJECTORY_READY_MIN_SPAN_WEEKS",
    "TRAJECTORY_READY_MIN_UNIQUE_DAYS",
    "assess_library_learning_depth",
    "assess_screen_archive_span",
    "ftse_equivalent_markets",
    "is_ftse_equivalent_market",
    "learning_depth_path",
    "refresh_library_trajectory_artifacts",
    "write_library_trajectory_artifacts",
]
