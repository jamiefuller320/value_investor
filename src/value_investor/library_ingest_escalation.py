"""FTSE-parity ingest escalation for offline library markets.

Reusable across library market pilots (euro_depth first). Mirrors live
``ingest_loop`` stall detection and gap-closure engineering compile, scoped
by ``market_id`` so later markets can copy the same weekday loop wiring.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.engineering_tasks import (
    BLOCKED_PATHS,
    COMMITTED_TASKS_PATH,
    PARKED_SOURCE_HUNTER_PRIORITY_SCORE,
    PARKED_SOURCE_HUNTER_SOURCE,
    EngineeringTask,
    _allowed_paths_for_area,
    _merge_task_rows,
    _next_engineering_seq_from_rows,
    load_engineering_tasks,
)
from value_investor.ingest_loop import has_open_ingest_engineering_tasks
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_STALL_RUNS = 2
DEFAULT_FTSE_EQUIVALENT_MARKETS = ("sp500",)
LIBRARY_INGEST_STALL_SOURCES = frozenset(
    {"library_ingest_stall", "library_ingest_gap_closure", "ingest_gap_closure", "ingest_trial"}
)


def ftse_equivalent_markets(policy: dict[str, Any] | None = None) -> list[str]:
    """Markets that must match live FTSE filing + trajectory depth (canonical only)."""
    if policy is None:
        try:
            from value_investor.agent_model_policy import load_policy

            policy = load_policy()
        except (OSError, ValueError, TypeError):
            policy = {}
    raw = policy.get("ftse_equivalent_markets")
    if raw is None:
        raw = DEFAULT_FTSE_EQUIVALENT_MARKETS
    return [str(mid).strip() for mid in raw if str(mid).strip()]


def is_ftse_equivalent_market(
    market_id: str,
    policy: dict[str, Any] | None = None,
) -> bool:
    return str(market_id or "").strip() in set(ftse_equivalent_markets(policy))


def library_ingest_health_log_path(library_root: Path, market_id: str) -> Path:
    return Path(library_root) / "markets" / market_id / "ingest_health_log.json"


def library_ingest_summary_path(library_root: Path, market_id: str) -> Path:
    return Path(library_root) / "markets" / market_id / "ingest_summary.json"


def resolve_library_ingest_health_log_path(library_root: Path, market_id: str) -> Path:
    """Prefer per-market log; fall back to legacy euro_depth aggregate file."""
    primary = library_ingest_health_log_path(library_root, market_id)
    if primary.exists():
        return primary
    legacy = Path(library_root) / "euro_ingest_health_log.json"
    if market_id == "euro_depth" and legacy.exists():
        return legacy
    return primary


def library_ingest_filing_gaps(health: dict[str, Any]) -> int:
    return int(health.get("unmeasured_buy_tier") or 0) + int(health.get("zero_body_buy_tier") or 0)


def library_ingest_ticker_has_gaps(
    ticker: str,
    *,
    market_id: str,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
) -> bool:
    from value_investor.library_ingest_loop import _filing_coverage_for_ticker

    coverage = _filing_coverage_for_ticker(
        ticker,
        library_root=library_root,
        market_id=market_id,
        canonical_only=is_ftse_equivalent_market(market_id),
    )
    total = int(coverage.get("filings_total") or 0)
    with_body = int(coverage.get("filings_with_body") or 0)
    if total == 0 or with_body == 0:
        return True
    return with_body < max(3, total // 2)


def _entries_for_market(payload: dict[str, Any], market_id: str) -> list[dict[str, Any]]:
    entries = list(payload.get("entries") or [])
    scoped = [row for row in entries if str(row.get("market_id") or "") == market_id]
    if scoped:
        return scoped
    if market_id == "euro_depth":
        return [row for row in entries if not row.get("market_id")]
    return []


def library_ingest_health_stalled(
    log_path: Path,
    *,
    market_id: str,
    min_runs: int = DEFAULT_STALL_RUNS,
) -> bool:
    """True when buy-tier filing gaps are unchanged across recent library ingest runs."""
    if not log_path.exists():
        return False
    try:
        payload = read_json(log_path)
    except (OSError, ValueError, TypeError):
        return False
    entries = _entries_for_market(payload, market_id)
    if len(entries) < max(2, int(min_runs)):
        return False
    recent = entries[-max(2, int(min_runs)) :]
    gap_counts = [library_ingest_filing_gaps(row.get("health_after") or {}) for row in recent]
    if not gap_counts or gap_counts[0] <= 0:
        return False
    if len(set(gap_counts)) != 1:
        return False
    for row in recent:
        before = library_ingest_filing_gaps(row.get("health_before") or {})
        after = library_ingest_filing_gaps(row.get("health_after") or {})
        if after < before:
            return False
        if int(row.get("improved") or 0) > 0:
            return False
    return True


def has_open_library_ingest_task_for_market(
    market_id: str,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> bool:
    payload = load_engineering_tasks(tasks_path)
    for row in payload.get("tasks") or []:
        if str(row.get("area") or "").lower() != "ingest":
            continue
        if str(row.get("status") or "open") not in {"open", "pr_open"}:
            continue
        if str(row.get("source") or "") == PARKED_SOURCE_HUNTER_SOURCE:
            continue
        evidence = row.get("evidence") or {}
        if str(evidence.get("market_id") or "") == market_id:
            return True
        source = str(row.get("source") or "")
        if (
            source in LIBRARY_INGEST_STALL_SOURCES
            and str(evidence.get("market_id") or "") == market_id
        ):
            return True
    return False


def compile_library_ingest_engineering_tasks_micro(
    *,
    market_id: str,
    health_after: dict[str, Any],
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
    max_tasks: int = 1,
) -> dict[str, Any]:
    """Queue a market-scoped ingest task when library filing deepen stalls."""
    if max_tasks <= 0:
        return {"compiled_count": 0, "reason": "max_tasks=0"}
    if has_open_ingest_engineering_tasks(tasks_path):
        return {"compiled_count": 0, "reason": "open ingest engineering task already queued"}
    if has_open_library_ingest_task_for_market(market_id, tasks_path=tasks_path):
        return {
            "compiled_count": 0,
            "reason": f"open library ingest task already exists for {market_id}",
        }

    filing_gaps = library_ingest_filing_gaps(health_after)
    if filing_gaps <= 0:
        return {"compiled_count": 0, "reason": "no filing gaps remain"}

    from value_investor.data_library import MARKET_REGISTRY

    spec = MARKET_REGISTRY.get(market_id)
    label = spec.label if spec is not None else market_id
    sample_unmeasured = list(health_after.get("unmeasured_tickers") or [])[:5]
    sample_zero = list(health_after.get("zero_body_tickers") or [])[:5]

    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    existing_payload = load_engineering_tasks(committed_path)
    existing_rows = list(existing_payload.get("tasks") or [])
    seq = _next_engineering_seq_from_rows(existing_rows, run_stamp)
    title = (
        f"Close library ingest filing gaps for {label} ({market_id}): "
        f"{filing_gaps} buy-tier gaps after stalled weekday loop"
    )[:160]
    summary = (
        f"Library market {market_id} buy-tier filing deepen stalled with "
        f"{health_after.get('unmeasured_buy_tier', 0)} unmeasured and "
        f"{health_after.get('zero_body_buy_tier', 0)} zero-body names "
        f"(buy_tier_count={health_after.get('buy_tier_count', 0)}). "
        f"Improve euro_filings / ESEF / IR allowlist source coverage for representative "
        f"tickers and add regression tests; verify with "
        f"ftse-library ingest-loop --market {market_id}."
    )
    if sample_unmeasured:
        summary += f" Sample unmeasured: {', '.join(sample_unmeasured)}."
    if sample_zero:
        summary += f" Sample zero-body: {', '.join(sample_zero)}."

    task = EngineeringTask(
        id=f"eng-{run_stamp}-{seq:02d}",
        area="ingest",
        title=title,
        summary=summary[:500],
        priority="high",
        priority_score=86.0,
        source="library_ingest_stall",
        evidence={
            "market_id": market_id,
            "library_market": market_id,
            "universe": "library",
            "filing_health": dict(health_after),
            "filing_gaps": filing_gaps,
            "sample_unmeasured": sample_unmeasured,
            "sample_zero_body": sample_zero,
            "rerun_library_ingest_loop": True,
            "doc": "docs/ops/library-ingest-escalation.md",
        },
        acceptance_criteria=[
            f"Representative {market_id} buy-tier tickers gain filing indexes with bodies under the market canonical screen path",
            f"ftse-library ingest-loop --market {market_id} reports improved > 0 on a verification run",
            "Add focused regression tests for the source/parser fix",
            "No change to live FTSE 350 ingest path or blocked_paths",
        ],
        allowed_paths=_allowed_paths_for_area("ingest"),
        blocked_paths=list(BLOCKED_PATHS),
    )
    merged_rows = _merge_task_rows(existing_rows, [task][: max(0, int(max_tasks))])
    open_ids_before = {
        str(row.get("id") or "")
        for row in existing_rows
        if str(row.get("status") or "open") == "open"
    }
    newly_open = [
        row
        for row in merged_rows
        if str(row.get("status") or "open") == "open"
        and str(row.get("id") or "") not in open_ids_before
    ]
    payload = {
        **existing_payload,
        "compiled_at": datetime.now(UTC).isoformat(),
        "task_count": len(merged_rows),
        "tasks": merged_rows,
        "library_ingest_health": health_after,
        "micro_compile_source": "library_ingest_loop",
        "library_market_id": market_id,
    }
    committed_path = Path(committed_path)
    tasks_path = Path(tasks_path)
    committed_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(committed_path, payload, compact=False)
    if tasks_path != committed_path:
        write_json(tasks_path, payload, compact=False)
    return {
        "compiled_count": len(newly_open),
        "task_ids": [str(row.get("id") or "") for row in newly_open],
        "task_count": len(merged_rows),
        "market_id": market_id,
    }


def _open_parked_hunter_task(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get("source") or "") != PARKED_SOURCE_HUNTER_SOURCE:
            continue
        if str(row.get("status") or "open") in {"open", "pr_open"}:
            return row
    return None


def _tried_parked_hunter_keys(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    tried: set[tuple[str, str]] = set()
    for row in rows:
        if str(row.get("source") or "") != PARKED_SOURCE_HUNTER_SOURCE:
            continue
        if str(row.get("status") or "") == "cancelled":
            continue
        evidence = row.get("evidence") or {}
        market_id = str(evidence.get("market_id") or evidence.get("hunter_market_id") or "").strip()
        ticker = str(evidence.get("hunter_ticker") or "").strip().upper()
        if market_id and ticker:
            tried.add((market_id, ticker))
    return tried


def compile_parked_source_hunter_task(
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy: dict[str, Any] | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    committed_path: Path = COMMITTED_TASKS_PATH,
) -> dict[str, Any]:
    """Queue one low-priority parked-ticker source hunt at the back of the queue.

    After the current hunter task is merged, call again to compile the next
    parked ticker. Stall / gap-closure compile ignores this source so it cannot
    block higher-priority ingest work.
    """
    from value_investor.library_ingest_exhaustion import iter_parked_hunter_candidates

    if policy is None:
        from value_investor.agent_model_policy import load_policy

        try:
            policy = load_policy()
        except (OSError, ValueError, TypeError):
            policy = {}

    existing_payload = load_engineering_tasks(committed_path)
    existing_rows = list(existing_payload.get("tasks") or [])
    open_hunter = _open_parked_hunter_task(existing_rows)
    if open_hunter is not None:
        return {
            "compiled_count": 0,
            "reason": "open parked-source hunter already queued",
            "task_id": open_hunter.get("id"),
        }

    tried = _tried_parked_hunter_keys(existing_rows)
    candidates = iter_parked_hunter_candidates(library_root=library_root, policy=policy)
    next_row: tuple[str, str, dict[str, Any]] | None = None
    for market_id, ticker, parked in candidates:
        if (market_id, ticker.upper()) in tried:
            continue
        next_row = (market_id, ticker, parked)
        break
    if next_row is None:
        return {
            "compiled_count": 0,
            "reason": "no parked leftover tickers remaining for hunter",
            "tried_count": len(tried),
            "candidate_count": len(candidates),
        }

    market_id, ticker, parked = next_row
    from value_investor.data_library import MARKET_REGISTRY

    spec = MARKET_REGISTRY.get(market_id)
    label = spec.label if spec is not None else market_id
    reason = str(parked.get("reason") or "leftover_thin_or_iwb")
    revisit = str(parked.get("revisit_when") or "")
    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    seq = _next_engineering_seq_from_rows(existing_rows, run_stamp)
    title = f"Hunt fetchable IR source for parked {market_id} leftover {ticker}"[:160]
    summary = (
        f"Library market {market_id} ({label}) parked {ticker} after ingest avenues "
        f"were exhausted ({reason}). Look at this one ticker only: if a fetchable IR "
        "or statutory filing URL exists, add an allowlist entry and a regression test. "
        "If nothing fetchable exists, record a PARKED_SOURCE_HUNTER_SKIP reason in "
        "tests/test_research_filings.py — do not invent URLs. auto_merge is off; this "
        "task is priority=low so it sits at the back of the engineering queue."
    )
    if revisit:
        summary += f" Revisit when: {revisit}."
    task = EngineeringTask(
        id=f"eng-{run_stamp}-{seq:02d}",
        area="ingest",
        title=title,
        summary=summary[:500],
        priority="low",
        priority_score=PARKED_SOURCE_HUNTER_PRIORITY_SCORE,
        source=PARKED_SOURCE_HUNTER_SOURCE,
        auto_merge=False,
        evidence={
            "market_id": market_id,
            "library_market": market_id,
            "hunter_market_id": market_id,
            "hunter_ticker": ticker.upper(),
            "parked_reason": reason,
            "parked_revisit_when": revisit,
            "universe": "library",
            "doc": "docs/ops/library-ingest-escalation.md",
        },
        acceptance_criteria=[
            f"Inspect IR / exchange sources for {ticker} only — do not invent URLs",
            "If a fetchable statutory/IR body exists, add allowlist + regression test",
            "If none exists, add PARKED_SOURCE_HUNTER_SKIP with a one-line reason",
            "No change to live FTSE 350 ingest path, blocked_paths, or paper-fund",
        ],
        allowed_paths=_allowed_paths_for_area("ingest"),
        blocked_paths=list(BLOCKED_PATHS),
    )
    merged_rows = _merge_task_rows(existing_rows, [task])
    open_ids_before = {
        str(row.get("id") or "")
        for row in existing_rows
        if str(row.get("status") or "open") == "open"
    }
    newly_open = [
        row
        for row in merged_rows
        if str(row.get("status") or "open") == "open"
        and str(row.get("id") or "") not in open_ids_before
    ]
    payload = {
        **existing_payload,
        "compiled_at": datetime.now(UTC).isoformat(),
        "task_count": len(merged_rows),
        "tasks": merged_rows,
        "micro_compile_source": PARKED_SOURCE_HUNTER_SOURCE,
        "library_market_id": market_id,
        "hunter_ticker": ticker.upper(),
    }
    committed_path = Path(committed_path)
    tasks_path = Path(tasks_path)
    committed_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(committed_path, payload, compact=False)
    if tasks_path != committed_path:
        write_json(tasks_path, payload, compact=False)
    return {
        "compiled_count": len(newly_open),
        "task_ids": [str(row.get("id") or "") for row in newly_open],
        "task_count": len(merged_rows),
        "market_id": market_id,
        "hunter_ticker": ticker.upper(),
        "priority_score": PARKED_SOURCE_HUNTER_PRIORITY_SCORE,
    }


def snapshot_library_buy_tier_filing_health(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarise buy-tier filing body coverage for a library market screen."""
    from value_investor.library_ingest_loop import (
        _filing_coverage_for_ticker,
        load_library_buy_tier_reports,
    )

    library_root = Path(library_root)
    ftse_equivalent = is_ftse_equivalent_market(market_id, policy)
    coverage_scope = "canonical" if ftse_equivalent else "canonical_plus_shards"
    empty = {
        "snapshot_at": datetime.now(UTC).isoformat(),
        "market_id": market_id,
        "buy_tier_count": 0,
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
        "bodies_min": None,
        "bodies_median": None,
        "bodies_max": None,
        "coverage_scope": coverage_scope,
        "ftse_equivalent": ftse_equivalent,
        "unmeasured_tickers": [],
        "zero_body_tickers": [],
        "thin_body_tickers": [],
        "indexed_without_body_tickers": [],
        "indexed_without_body_by_ticker": {},
    }
    try:
        reports = load_library_buy_tier_reports(library_root, market_id)
    except FileNotFoundError:
        return {**empty, "error": "screen shortlist missing"}

    unmeasured_tickers: list[str] = []
    zero_body_tickers: list[str] = []
    thin_body_tickers: list[str] = []
    indexed_without_body = 0
    indexed_without_body_tickers: list[str] = []
    indexed_without_body_by_ticker: dict[str, int] = {}
    body_counts: list[int] = []
    for report in reports:
        coverage = _filing_coverage_for_ticker(
            report.ticker,
            library_root=library_root,
            market_id=market_id,
            canonical_only=ftse_equivalent,
        )
        total = int(coverage.get("filings_total") or 0)
        with_body = int(coverage.get("filings_with_body") or 0)
        iwb = int(coverage.get("indexed_without_body") or 0)
        indexed_without_body += iwb
        if iwb > 0:
            indexed_without_body_tickers.append(report.ticker)
            indexed_without_body_by_ticker[report.ticker] = iwb
        if with_body > 0:
            body_counts.append(with_body)
        if total == 0:
            unmeasured_tickers.append(report.ticker)
        elif with_body == 0:
            zero_body_tickers.append(report.ticker)
        elif with_body < max(3, total // 2):
            thin_body_tickers.append(report.ticker)

    snapshot = {
        "snapshot_at": datetime.now(UTC).isoformat(),
        "market_id": market_id,
        "buy_tier_count": len(reports),
        "unmeasured_buy_tier": len(unmeasured_tickers),
        "zero_body_buy_tier": len(zero_body_tickers),
        "thin_body_buy_tier": len(thin_body_tickers),
        "indexed_without_body": indexed_without_body,
        "bodies_min": min(body_counts) if body_counts else None,
        "bodies_median": median(body_counts) if body_counts else None,
        "bodies_max": max(body_counts) if body_counts else None,
        "coverage_scope": coverage_scope,
        "ftse_equivalent": ftse_equivalent,
        "unmeasured_tickers": unmeasured_tickers,
        "zero_body_tickers": zero_body_tickers,
        "thin_body_tickers": thin_body_tickers,
        "indexed_without_body_tickers": indexed_without_body_tickers,
        "indexed_without_body_by_ticker": indexed_without_body_by_ticker,
    }
    from value_investor.library_ingest_exhaustion import apply_stored_exhaustion_overlay

    return apply_stored_exhaustion_overlay(
        snapshot,
        market_id=market_id,
        library_root=library_root,
    )


def snapshot_library_ingest_health(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return snapshot_library_buy_tier_filing_health(
        market_id,
        library_root=library_root,
        policy=policy,
    )


__all__ = [
    "DEFAULT_FTSE_EQUIVALENT_MARKETS",
    "DEFAULT_STALL_RUNS",
    "compile_library_ingest_engineering_tasks_micro",
    "compile_parked_source_hunter_task",
    "ftse_equivalent_markets",
    "has_open_library_ingest_task_for_market",
    "is_ftse_equivalent_market",
    "library_ingest_filing_gaps",
    "library_ingest_health_log_path",
    "library_ingest_health_stalled",
    "library_ingest_summary_path",
    "library_ingest_ticker_has_gaps",
    "resolve_library_ingest_health_log_path",
    "snapshot_library_buy_tier_filing_health",
    "snapshot_library_ingest_health",
]
