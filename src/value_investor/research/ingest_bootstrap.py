"""Canonical buy-tier research stores and Sunday/weekday ingest bootstrap."""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_COMMITTED_DATA_DIR = Path("docs/data")
BOOTSTRAP_SEED_CAP = 20


def research_roots(output_dir: Path) -> list[Path]:
    return [
        Path(output_dir) / "research",
        Path("docs/data/research"),
        Path("output/research"),
        Path("docs/data/library/markets"),
    ]


def canonical_sources_dir(output_dir: Path, ticker: str) -> Path:
    return Path(output_dir) / "research" / ticker.strip().upper() / "sources"


def canonical_filings_dir(output_dir: Path, ticker: str) -> Path:
    return canonical_sources_dir(output_dir, ticker) / "filings"


def find_filing_index_paths(ticker: str, *, output_dir: Path) -> list[Path]:
    from value_investor.engineering_queue import _filing_index_paths_for_ticker

    paths = _filing_index_paths_for_ticker(ticker, roots=research_roots(output_dir))
    canonical = canonical_filings_dir(output_dir, ticker) / "filings_index.json"
    ordered: list[Path] = []
    if canonical.exists():
        ordered.append(canonical)
    for path in paths:
        if path not in ordered:
            ordered.append(path)
    return ordered


def prefer_filing_index_path(ticker: str, *, output_dir: Path) -> Path | None:
    paths = find_filing_index_paths(ticker, output_dir=output_dir)
    return paths[0] if paths else None


def _copy_filings_tree(*, source_filings_dir: Path, dest_filings_dir: Path) -> None:
    dest_filings_dir.mkdir(parents=True, exist_ok=True)
    src_index = source_filings_dir / "filings_index.json"
    if src_index.exists():
        shutil.copy2(src_index, dest_filings_dir / "filings_index.json")
    src_bodies = source_filings_dir / "bodies"
    if src_bodies.is_dir():
        shutil.copytree(src_bodies, dest_filings_dir / "bodies", dirs_exist_ok=True)


def ensure_canonical_research_store(
    ticker: str,
    company_name: str,
    *,
    output_dir: Path,
    screening_snapshot: dict[str, Any] | None = None,
    market: str | None = "ftse350",
    seed_if_missing: bool = False,
) -> dict[str, Any]:
    """
    Ensure ``{output_dir}/research/{TICKER}/`` exists.

    Migrates an existing library/off-path filings index into the canonical store
    when needed so CI commits under ``docs/data/research/**`` persist bodies.
    """
    ticker = ticker.strip().upper()
    filings_dir = canonical_filings_dir(output_dir, ticker)
    index_path = filings_dir / "filings_index.json"
    result: dict[str, Any] = {
        "ticker": ticker,
        "canonical_index": str(index_path),
        "action": "exists",
    }

    if index_path.exists():
        return result

    sources_dir = canonical_sources_dir(output_dir, ticker)
    sources_dir.mkdir(parents=True, exist_ok=True)

    for alt_path in find_filing_index_paths(ticker, output_dir=output_dir):
        if alt_path == index_path:
            continue
        _copy_filings_tree(source_filings_dir=alt_path.parent, dest_filings_dir=filings_dir)
        result["action"] = "migrated"
        result["source_index"] = str(alt_path)
        return result

    if not seed_if_missing:
        result["action"] = "pending"
        return result

    from value_investor.research.ingest import ingest_research_sources

    snapshot = screening_snapshot or {"ticker": ticker, "name": company_name}
    ingest_research_sources(
        ticker=ticker,
        company_name=company_name,
        screening_snapshot=snapshot,
        sources_dir=sources_dir,
        since=None,
        market=market,
        deepen_history=False,
    )
    result["action"] = "seeded"
    return result


def bootstrap_buy_tier_research(
    reports: list[CompanyReport],
    *,
    output_dir: Path = DEFAULT_COMMITTED_DATA_DIR,
    market: str | None = "ftse350",
    seed_cap: int = BOOTSTRAP_SEED_CAP,
) -> dict[str, Any]:
    """Prepare canonical research dirs for all buy-tier names before ingest improvement."""
    buy_reports = [row for row in reports if row.signal in ("strong_buy", "buy")]
    buy_reports.sort(
        key=lambda row: (0 if row.signal == "strong_buy" else 1, row.ticker),
    )

    results: list[dict[str, Any]] = []
    seeded = 0
    migrated = 0
    existing = 0
    pending = 0

    for report in buy_reports:
        # Strong_buy first (sort above); seed any buy-tier missing a canonical index.
        seed = seeded < seed_cap
        row = ensure_canonical_research_store(
            report.ticker,
            report.name,
            output_dir=output_dir,
            screening_snapshot=report.to_dict(),
            market=market,
            seed_if_missing=seed,
        )
        results.append(row)
        action = row.get("action")
        if action == "seeded":
            seeded += 1
        elif action == "migrated":
            migrated += 1
        elif action == "exists":
            existing += 1
        else:
            pending += 1

    summary = {
        "run_at": datetime.now(UTC).isoformat(),
        "buy_tier_count": len(buy_reports),
        "existing": existing,
        "migrated": migrated,
        "seeded": seeded,
        "pending": pending,
        "seed_cap": seed_cap,
        "results": results,
    }
    write_json(
        Path(output_dir) / "ingest_bootstrap_summary.json",
        summary,
        compact=True,
    )
    return summary


def write_screening_snapshot(
    ticker: str,
    *,
    output_dir: Path,
    screening_snapshot: dict[str, Any],
) -> Path:
    sources_dir = canonical_sources_dir(output_dir, ticker)
    sources_dir.mkdir(parents=True, exist_ok=True)
    path = sources_dir / "screening_snapshot.json"
    write_json(path, screening_snapshot, compact=True)
    return path
