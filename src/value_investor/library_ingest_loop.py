"""Weekday buy-tier filing deepen loop for offline library markets (euro_depth pilot)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.engineering_queue import _coverage_from_index, _filing_index_paths_for_ticker
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    compile_ingest_engineering_task_from_trial,
)
from value_investor.ingest_loop import has_open_ingest_engineering_tasks
from value_investor.library_ingest_escalation import (
    DEFAULT_STALL_RUNS,
    compile_library_ingest_engineering_tasks_micro,
    library_ingest_health_stalled,
    library_ingest_summary_path,
    resolve_library_ingest_health_log_path,
    snapshot_library_ingest_health,
)
from value_investor.library_screen import screen_dir_for
from value_investor.market_paper_adapter import load_library_screen_result
from value_investor.research.filings import (
    refetch_ir_allowlist_filing_bodies,
    refetch_residual_filing_bodies,
)
from value_investor.research.ingest import ingest_research_sources
from value_investor.research.store import ResearchStore
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_LIBRARY_INGEST_HEALTH_LOG = Path("docs/data/library/euro_ingest_health_log.json")
DEFAULT_WEEKDAY_BATCH_MAX_TARGETS = 12
DEFAULT_WEEKDAY_MAX_RUNTIME_SECONDS = 2100.0
DEFAULT_MAINTENANCE_MAX_TARGETS = 62
UNMEASURED_PRIORITY_BONUS = 12.0
ZERO_BODY_PRIORITY_BONUS = 8.0


@dataclass
class LibraryIngestTarget:
    ticker: str
    name: str
    signal: str
    priority_score: float
    filings_total: int = 0
    filings_with_body: int = 0
    reason: str = ""


@dataclass
class LibraryIngestLoopResult:
    market_id: str
    targets: list[LibraryIngestTarget] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    improved: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    runtime_cutoff: bool = False
    partial: bool = False
    health_before: dict[str, Any] = field(default_factory=dict)
    health_after: dict[str, Any] = field(default_factory=dict)
    stalled: bool = False
    micro_compiled: bool = False
    micro_compile: dict[str, Any] = field(default_factory=dict)
    recorded_gap_closure: bool = False
    gap_closure_compiled: bool = False
    gap_closure_compile: dict[str, Any] = field(default_factory=dict)
    discovery_scan: dict[str, Any] | None = None
    maintenance_mode: bool = False
    parity_handoff: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_id": self.market_id,
            "targets": [t.ticker for t in self.targets],
            "target_details": [
                {
                    "ticker": t.ticker,
                    "priority_score": t.priority_score,
                    "filings_total": t.filings_total,
                    "filings_with_body": t.filings_with_body,
                    "reason": t.reason,
                }
                for t in self.targets
            ],
            "results": self.results,
            "improved": self.improved,
            "errors": self.errors,
            "runtime_cutoff": self.runtime_cutoff,
            "partial": self.partial,
            "health_before": self.health_before,
            "health_after": self.health_after,
            "stalled": self.stalled,
            "micro_compiled": self.micro_compiled,
            "micro_compile": self.micro_compile,
            "recorded_gap_closure": self.recorded_gap_closure,
            "gap_closure_compiled": self.gap_closure_compiled,
            "gap_closure_compile": self.gap_closure_compile,
            "discovery_scan": self.discovery_scan,
            "maintenance_mode": self.maintenance_mode,
            "parity_handoff": self.parity_handoff,
        }


def _research_roots_for_market(library_root: Path, market_id: str) -> list[Path]:
    library_root = Path(library_root)
    return [
        library_root / "markets",
        Path("docs/data/library/markets"),
        screen_dir_for(library_root, market_id),
        Path("docs/data/research"),
    ]


def _canonical_filing_index_path(
    ticker: str,
    *,
    library_root: Path,
    market_id: str,
) -> Path:
    return (
        screen_dir_for(library_root, market_id)
        / "research"
        / ticker
        / "sources"
        / "filings"
        / "filings_index.json"
    )


def _empty_filing_coverage() -> dict[str, int]:
    return {"filings_total": 0, "filings_with_body": 0, "indexed_without_body": 0}


def _coverage_from_filing_index_path(path: Path) -> dict[str, int] | None:
    try:
        read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    summary = _coverage_from_index(path)
    total = int(summary.get("filings_total") or 0)
    with_body = int(summary.get("filings_with_body") or 0)
    indexed = int(summary.get("indexed_without_body") or 0)
    if indexed == 0 and total > with_body:
        indexed = total - with_body
    return {
        "filings_total": total,
        "filings_with_body": with_body,
        "indexed_without_body": indexed,
    }


def _best_filing_coverage(paths: list[Path]) -> dict[str, int]:
    best = _empty_filing_coverage()
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        coverage = _coverage_from_filing_index_path(path)
        if coverage is None:
            continue
        total = coverage["filings_total"]
        with_body = coverage["filings_with_body"]
        if with_body > best["filings_with_body"] or (
            with_body == best["filings_with_body"] and total > best["filings_total"]
        ):
            best = coverage
    return best


def _filing_coverage_for_ticker(
    ticker: str,
    *,
    library_root: Path,
    market_id: str,
    canonical_only: bool = False,
) -> dict[str, int]:
    """
    Return filing coverage for a library market ticker.

    Prefer the active market's canonical screen research index so stale empty
    indexes from other graduated shards (e.g. aex vs euro_depth) do not shadow
    fresh euro_depth ingest writes.

    When ``canonical_only`` is true (FTSE-equivalent markets such as ``sp500``),
    do **not** fall back to other shards — nasdaq100 overlap must not count as
    S&P parity.
    """
    canonical = _canonical_filing_index_path(
        ticker,
        library_root=library_root,
        market_id=market_id,
    )
    if canonical.exists():
        coverage = _coverage_from_filing_index_path(canonical)
        if coverage is not None:
            return coverage
        if canonical_only:
            return _empty_filing_coverage()

    if canonical_only:
        return _empty_filing_coverage()

    roots = _research_roots_for_market(library_root, market_id)
    paths = _filing_index_paths_for_ticker(ticker, roots=roots)
    if not paths:
        return _empty_filing_coverage()
    return _best_filing_coverage(paths)


def load_library_buy_tier_reports(
    library_root: Path,
    market_id: str,
) -> list[CompanyReport]:
    """Buy-tier reports from the latest library screen-lite shortlist."""
    from value_investor.library_screen import library_research_reports

    result = load_library_screen_result(library_root, market_id)
    reports = library_research_reports(result)
    buy = [row for row in reports if row.signal in ("strong_buy", "buy")]
    buy.sort(
        key=lambda row: (0 if row.signal == "strong_buy" else 1, -row.conviction_score, row.ticker)
    )
    return buy


def select_library_ingest_targets(
    reports: list[CompanyReport],
    *,
    library_root: Path,
    market_id: str,
    max_targets: int,
    discovery_bonus_by_ticker: dict[str, float] | None = None,
    canonical_only: bool | None = None,
) -> list[LibraryIngestTarget]:
    bonuses = discovery_bonus_by_ticker or {}
    if canonical_only is None:
        from value_investor.library_ingest_escalation import is_ftse_equivalent_market

        canonical_only = is_ftse_equivalent_market(market_id)
    scored: list[LibraryIngestTarget] = []
    for report in reports:
        coverage = _filing_coverage_for_ticker(
            report.ticker,
            library_root=library_root,
            market_id=market_id,
            canonical_only=canonical_only,
        )
        total = coverage["filings_total"]
        with_body = coverage["filings_with_body"]
        score = 0.0
        reason = "maintain"
        if total == 0:
            score += UNMEASURED_PRIORITY_BONUS
            reason = "unmeasured"
        elif with_body == 0:
            score += ZERO_BODY_PRIORITY_BONUS
            reason = "zero_body"
        elif with_body < max(3, total // 2):
            score += 4.0
            reason = "thin_bodies"
        if report.signal == "strong_buy":
            score += 2.0
        score += float(report.conviction_score or 0.0)
        score += float(bonuses.get(report.ticker) or bonuses.get(report.ticker.upper()) or 0.0)
        scored.append(
            LibraryIngestTarget(
                ticker=report.ticker,
                name=report.name,
                signal=report.signal,
                priority_score=score,
                filings_total=total,
                filings_with_body=with_body,
                reason=reason,
            )
        )
    scored.sort(key=lambda row: (-row.priority_score, row.ticker))
    return scored[: max(1, int(max_targets))]


def _ingest_single_library_target(
    target: LibraryIngestTarget,
    *,
    library_root: Path,
    market_id: str,
    deepen_history: bool = True,
    max_bodies: int = 20,
    canonical_only: bool | None = None,
) -> dict[str, Any]:
    screen_dir = screen_dir_for(library_root, market_id)
    store = ResearchStore(screen_dir)
    sources_dir = store.sources_dir(target.ticker)
    sources_dir.mkdir(parents=True, exist_ok=True)
    if canonical_only is None:
        from value_investor.library_ingest_escalation import is_ftse_equivalent_market

        canonical_only = is_ftse_equivalent_market(market_id)
    before = _filing_coverage_for_ticker(
        target.ticker,
        library_root=library_root,
        market_id=market_id,
        canonical_only=canonical_only,
    )

    meta = ingest_research_sources(
        ticker=target.ticker,
        company_name=target.name,
        screening_snapshot={
            "ticker": target.ticker,
            "name": target.name,
            "signal": target.signal,
            "market": market_id,
        },
        sources_dir=sources_dir,
        since=None,
        market=market_id,
        deepen_history=deepen_history,
    )
    filings_dir = sources_dir / "filings"
    refetch_residual_filing_bodies(
        filings_dir,
        ticker=target.ticker,
        company_name=target.name,
        max_bodies=max_bodies,
    )
    refetch_ir_allowlist_filing_bodies(
        filings_dir,
        ticker=target.ticker,
        max_bodies=max_bodies,
    )
    after = _filing_coverage_for_ticker(
        target.ticker,
        library_root=library_root,
        market_id=market_id,
        canonical_only=canonical_only,
    )
    improved = (
        after["filings_with_body"] > before["filings_with_body"]
        or after["filings_total"] > before["filings_total"]
    )
    filings_summary = meta.get("filings_summary") or {}
    return {
        "ticker": target.ticker,
        "reason": target.reason,
        "before": before,
        "after": after,
        "improved": improved,
        "regime": meta.get("filings_regime"),
        "filings_summary": filings_summary,
    }


def run_library_ingest_loop(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    max_targets: int = DEFAULT_WEEKDAY_BATCH_MAX_TARGETS,
    max_runtime_seconds: float = DEFAULT_WEEKDAY_MAX_RUNTIME_SECONDS,
    max_bodies: int = 20,
    deepen_history: bool = True,
    health_log_path: Path | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    stall_runs: int = DEFAULT_STALL_RUNS,
    micro_compile_max_tasks: int = 1,
    record_gap_closure: dict[str, Any] | None = None,
    record_trial: dict[str, Any] | None = None,
    pin_tickers: list[str] | None = None,
    discovery_scan: bool | None = None,
    maintenance_mode: bool = False,
) -> LibraryIngestLoopResult:
    """
    Weekday deepen pass for library buy-tier names (euro_depth pilot and successors).

    Mirrors live FTSE ``run_weekday_ingest_loop`` escalation: health snapshots,
    stall detection, micro-compile of ingest engineering tasks, and optional
    gap-closure recording for horizon / verification reruns.
    """
    library_root = Path(library_root)
    health_log_path = Path(
        health_log_path or resolve_library_ingest_health_log_path(library_root, market_id)
    )
    result = LibraryIngestLoopResult(market_id=market_id, maintenance_mode=maintenance_mode)
    result.health_before = snapshot_library_ingest_health(market_id, library_root=library_root)
    if discovery_scan is None:
        discovery_scan = maintenance_mode
    if maintenance_mode and max_targets == DEFAULT_WEEKDAY_BATCH_MAX_TARGETS:
        max_targets = DEFAULT_MAINTENANCE_MAX_TARGETS

    gap_closure_spec = record_gap_closure or record_trial
    gap_closure_require_gaps = bool(gap_closure_spec)

    try:
        reports = load_library_buy_tier_reports(library_root, market_id)
    except FileNotFoundError as exc:
        result.errors.append(str(exc))
        result.health_after = dict(result.health_before)
        return result

    if not reports:
        result.errors.append(f"No buy-tier reports for {market_id}")
        result.health_after = dict(result.health_before)
        return result

    gap_closure_record: dict[str, Any] | None = None
    if gap_closure_spec:
        from value_investor.ingest_gap_closure import record_ingest_gap_closure_run

        preview_targets = select_library_ingest_targets(
            reports,
            library_root=library_root,
            market_id=market_id,
            max_targets=max(1, int(max_targets)),
        )
        gap_ticker = preview_targets[0].ticker if preview_targets else ""
        if pin_tickers and not gap_ticker:
            gap_ticker = str(pin_tickers[0] or "").strip().upper()
        params = {
            "max_targets": max_targets,
            "max_bodies": max_bodies,
            "max_runtime_seconds": max_runtime_seconds,
            "require_outstanding_gaps": gap_closure_require_gaps,
            "intensive_gap_closure": gap_closure_require_gaps,
            "pin_tickers": list(pin_tickers or []),
            "market_id": market_id,
            "universe": "library",
        }
        parent_run_id = str(
            gap_closure_spec.get("parent_run_id") or gap_closure_spec.get("parent_trial_id") or ""
        )
        gap_closure_record = record_ingest_gap_closure_run(
            title=str(gap_closure_spec.get("title") or "Library ingest gap-closure run"),
            summary=str(gap_closure_spec.get("summary") or ""),
            ticker=gap_ticker,
            params=params,
            review_trigger=str(gap_closure_spec.get("review_trigger") or "horizon_scan"),
            parent_run_id=parent_run_id,
            trigger=str(gap_closure_spec.get("trigger") or ""),
        )
        result.recorded_gap_closure = True

    if pin_tickers:
        pin_set = {str(t or "").strip().upper() for t in pin_tickers if str(t or "").strip()}
        pinned = [row for row in reports if row.ticker.upper() in pin_set]
        if pinned:
            reports = pinned

    discovery_bonus_by_ticker: dict[str, float] = {}
    if discovery_scan:
        from value_investor.library_discovery_scan import run_library_buy_tier_discovery_scan

        scan = run_library_buy_tier_discovery_scan(
            reports,
            library_root=library_root,
            market_id=market_id,
            persist_index=True,
            persist_summary=True,
        )
        discovery_bonus_by_ticker = {
            hit.ticker: hit.priority_bonus(scan.prioritization_weights) for hit in scan.tickers
        }
        result.discovery_scan = {
            "scanned": scan.scanned,
            "hits": scan.hits,
            "new_rows_total": scan.new_rows_total,
            "curiosity_total": scan.curiosity_total,
            "errors": scan.errors,
            "prioritization_weights": scan.prioritization_weights,
        }

    result.targets = select_library_ingest_targets(
        reports,
        library_root=library_root,
        market_id=market_id,
        max_targets=max_targets,
        discovery_bonus_by_ticker=discovery_bonus_by_ticker,
    )
    if pin_tickers and result.targets:
        pin_set = {str(t or "").strip().upper() for t in pin_tickers if str(t or "").strip()}
        result.targets = [
            row for row in result.targets if row.ticker.upper() in pin_set
        ] or result.targets[:1]

    started = time.monotonic()
    for target in result.targets:
        elapsed = time.monotonic() - started
        if elapsed >= max_runtime_seconds:
            result.runtime_cutoff = True
            result.partial = True
            break
        try:
            row = _ingest_single_library_target(
                target,
                library_root=library_root,
                market_id=market_id,
                deepen_history=deepen_history,
                max_bodies=max_bodies,
            )
            result.results.append(row)
            if row.get("improved"):
                result.improved.append(target.ticker)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Library ingest failed for %s: %s", target.ticker, exc)
            result.errors.append(f"{target.ticker}: {exc}")
        if time.monotonic() - started >= max_runtime_seconds:
            result.runtime_cutoff = True
            result.partial = True
            break

    result.health_after = snapshot_library_ingest_health(market_id, library_root=library_root)

    from value_investor.library_ingest_escalation import library_ingest_filing_gaps

    gaps_before = library_ingest_filing_gaps(result.health_before)
    gaps_after = library_ingest_filing_gaps(result.health_after)
    if gaps_before > 0 and gaps_after == 0:
        try:
            from value_investor.library_ingest_maintenance import (
                maybe_handoff_focus_on_ingest_parity,
            )

            result.parity_handoff = maybe_handoff_focus_on_ingest_parity(
                market_id=market_id,
                library_root=library_root,
                health=result.health_after,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ingest parity handoff failed for %s: %s", market_id, exc)
            result.parity_handoff = {"error": str(exc)}

    append_library_ingest_health_log(
        {
            "run_at": datetime.now(UTC).isoformat(),
            "source": "library_ingest_loop",
            "market_id": market_id,
            "health_before": result.health_before,
            "health_after": result.health_after,
            "targets": len(result.targets),
            "improved": len(result.improved),
            "improved_tickers": list(result.improved),
            "runtime_cutoff": result.runtime_cutoff,
            "errors": result.errors[:5],
        },
        path=health_log_path,
    )
    summary_path = library_ingest_summary_path(library_root, market_id)
    write_json(
        summary_path,
        {"run_at": datetime.now(UTC).isoformat(), **result.to_dict()},
        compact=False,
    )
    legacy_summary = library_root / "euro_ingest_summary.json"
    if market_id == "euro_depth":
        write_json(
            legacy_summary,
            {"run_at": datetime.now(UTC).isoformat(), **result.to_dict()},
            compact=False,
        )

    try:
        from value_investor.library_ingest_dispatch import refresh_euro_ingest_dispatch

        refresh_euro_ingest_dispatch(library_root=library_root, market_id=market_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Library ingest dispatch refresh failed: %s", exc)

    result.stalled = library_ingest_health_stalled(
        health_log_path,
        market_id=market_id,
        min_runs=stall_runs,
    )
    if result.stalled and not has_open_ingest_engineering_tasks(tasks_path):
        result.micro_compile = compile_library_ingest_engineering_tasks_micro(
            market_id=market_id,
            health_after=result.health_after,
            library_root=library_root,
            tasks_path=tasks_path,
            committed_path=tasks_path,
            max_tasks=micro_compile_max_tasks,
        )
        result.micro_compiled = int(result.micro_compile.get("compiled_count") or 0) > 0
    elif result.stalled:
        result.micro_compile = {
            "skipped": True,
            "reason": "open ingest engineering task already queued",
        }
    else:
        result.micro_compile = {"skipped": True, "reason": "library ingest health not stalled"}

    finalized_gap_closure: dict[str, Any] | None = None
    if gap_closure_record is not None:
        from value_investor.ingest_gap_closure import finalize_pending_gap_closure_run

        finalized_gap_closure = finalize_pending_gap_closure_run(
            health_before=result.health_before,
            health_after=result.health_after,
            ingest_summary=result,
        )

    if finalized_gap_closure is not None:
        result.gap_closure_compile = compile_ingest_engineering_task_from_trial(
            finalized_gap_closure,
            tasks_path=tasks_path,
            committed_path=tasks_path,
        )
        result.gap_closure_compiled = int(result.gap_closure_compile.get("compiled_count") or 0) > 0

    if result.micro_compiled or result.gap_closure_compiled:
        from value_investor.engineering_queue import refresh_engineering_queue_ui

        refresh_engineering_queue_ui(tasks_path=tasks_path)

    return result


def append_library_ingest_health_log(
    entry: dict[str, Any],
    *,
    path: Path = DEFAULT_LIBRARY_INGEST_HEALTH_LOG,
    keep: int = 52,
) -> None:
    path = Path(path)
    payload: dict[str, Any]
    if path.exists():
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            payload = {"entries": []}
    else:
        payload = {"entries": []}
    entries = list(payload.get("entries") or [])
    entries.append(entry)
    payload["entries"] = entries[-max(1, int(keep)) :]
    payload["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)
