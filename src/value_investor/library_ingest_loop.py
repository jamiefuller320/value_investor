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
        }


def _research_roots_for_market(library_root: Path, market_id: str) -> list[Path]:
    library_root = Path(library_root)
    return [
        library_root / "markets",
        Path("docs/data/library/markets"),
        screen_dir_for(library_root, market_id),
        Path("docs/data/research"),
    ]


def _filing_coverage_for_ticker(
    ticker: str,
    *,
    library_root: Path,
    market_id: str,
) -> dict[str, int]:
    roots = _research_roots_for_market(library_root, market_id)
    paths = _filing_index_paths_for_ticker(ticker, roots=roots)
    if not paths:
        return {"filings_total": 0, "filings_with_body": 0}
    try:
        read_json(paths[0])
    except (OSError, ValueError, TypeError):
        return {"filings_total": 0, "filings_with_body": 0}
    summary = _coverage_from_index(paths[0])
    return {
        "filings_total": int(summary.get("filings_total") or 0),
        "filings_with_body": int(summary.get("filings_with_body") or 0),
    }


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
) -> list[LibraryIngestTarget]:
    scored: list[LibraryIngestTarget] = []
    for report in reports:
        coverage = _filing_coverage_for_ticker(
            report.ticker,
            library_root=library_root,
            market_id=market_id,
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
) -> dict[str, Any]:
    screen_dir = screen_dir_for(library_root, market_id)
    store = ResearchStore(screen_dir)
    sources_dir = store.sources_dir(target.ticker)
    sources_dir.mkdir(parents=True, exist_ok=True)
    before = _filing_coverage_for_ticker(
        target.ticker,
        library_root=library_root,
        market_id=market_id,
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
    health_log_path: Path = DEFAULT_LIBRARY_INGEST_HEALTH_LOG,
) -> LibraryIngestLoopResult:
    """
      Weekday deepen pass for library buy-tier names (euro_depth / euro_stoxx50).

    No weekly_ops spend — filing fetches only, mirroring FTSE ingest-loop economics.
    """
    library_root = Path(library_root)
    result = LibraryIngestLoopResult(market_id=market_id)
    try:
        reports = load_library_buy_tier_reports(library_root, market_id)
    except FileNotFoundError as exc:
        result.errors.append(str(exc))
        return result

    if not reports:
        result.errors.append(f"No buy-tier reports for {market_id}")
        return result

    result.targets = select_library_ingest_targets(
        reports,
        library_root=library_root,
        market_id=market_id,
        max_targets=max_targets,
    )
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

    append_library_ingest_health_log(
        {
            "run_at": datetime.now(UTC).isoformat(),
            "market_id": market_id,
            "targets": len(result.targets),
            "improved": len(result.improved),
            "runtime_cutoff": result.runtime_cutoff,
            "errors": result.errors[:5],
        },
        path=health_log_path,
    )
    write_json(
        library_root / "euro_ingest_summary.json",
        {"run_at": datetime.now(UTC).isoformat(), **result.to_dict()},
        compact=False,
    )
    if market_id == "euro_depth":
        try:
            from value_investor.euro_depth_ingest_dispatch import refresh_euro_ingest_dispatch

            refresh_euro_ingest_dispatch(library_root=library_root, market_id=market_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Euro ingest dispatch refresh failed: %s", exc)
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
