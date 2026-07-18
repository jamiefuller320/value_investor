"""One-shot / CLI maintenance for offline multi-market libraries."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from value_investor.data_library import (
    MARKET_REGISTRY,
    market_dir,
    refresh_metrics,
)
from value_investor.research.filings import ingest_filings
from value_investor.storage import read_json

logger = logging.getLogger(__name__)

DEFAULT_SCREEN_KEEP_RUNS = 2

_SCREEN_DATED_GLOBS = (
    "signals_*.csv",
    "model_results_*.csv",
    "universe_*.csv",
    "summary_*.json",
    "summary_*.json.gz",
)
_HISTORY_DATED_GLOBS = (
    "run_*.json",
    "run_*.json.gz",
    "models_*.json",
    "models_*.json.gz",
)
_RUN_STAMP_RE = re.compile(r"_(\d{8}_\d{6})(?:\.[^.]+)*$")


def _run_stamp(path: Path) -> str | None:
    match = _RUN_STAMP_RE.search(path.name)
    return match.group(1) if match else None


def _company_name_for_memo(ticker_dir: Path, ticker: str) -> str:
    research_path = ticker_dir / "research.json"
    if research_path.exists():
        try:
            payload = read_json(research_path)
        except (OSError, ValueError):
            payload = {}
        name = payload.get("name") or payload.get("company_name")
        if name:
            return str(name)

    index_path = ticker_dir / "sources" / "filings" / "filings_index.json"
    if index_path.exists():
        try:
            index = read_json(index_path)
        except (OSError, ValueError):
            index = {}
        name = index.get("company_name")
        if name:
            return str(name)

    snapshots = ticker_dir / "sources" / "snapshots"
    if snapshots.exists():
        latest = sorted(snapshots.glob("*.json"), reverse=True)
        if latest:
            try:
                snap = read_json(latest[0])
            except (OSError, ValueError):
                snap = {}
            name = snap.get("name") or snap.get("company_name")
            if name:
                return str(name)

    return ticker


def list_research_filings_targets(
    root: Path,
    markets: list[str],
    *,
    only_unsupported: bool = True,
) -> list[dict[str, Any]]:
    """Enumerate research memos whose filings index should be re-ingested."""
    targets: list[dict[str, Any]] = []
    for market_id in markets:
        research_root = market_dir(root, market_id) / "screen" / "research"
        if not research_root.exists():
            continue
        for ticker_dir in sorted(p for p in research_root.iterdir() if p.is_dir()):
            index_path = ticker_dir / "sources" / "filings" / "filings_index.json"
            regime = None
            if index_path.exists():
                try:
                    index = read_json(index_path)
                except (OSError, ValueError):
                    index = {}
                regime = index.get("regime") or index.get("status")
            if only_unsupported and regime not in {None, "unsupported"}:
                continue
            ticker = ticker_dir.name
            targets.append(
                {
                    "market": market_id,
                    "ticker": ticker,
                    "company_name": _company_name_for_memo(ticker_dir, ticker),
                    "sources_dir": ticker_dir / "sources",
                    "prior_regime": regime,
                }
            )
    return targets


def reingest_research_filings(
    root: Path,
    markets: list[str],
    *,
    only_unsupported: bool = True,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Re-run ``ingest_filings`` for existing research memos.

    Used to backfill ASX / Euro regimes written before those sources existed.
    """
    targets = list_research_filings_targets(
        root, markets, only_unsupported=only_unsupported
    )
    results: list[dict[str, Any]] = []
    for target in targets:
        meta = ingest_filings(
            ticker=target["ticker"],
            company_name=target["company_name"],
            sources_dir=target["sources_dir"],
            api_key=api_key,
            market=target["market"],
        )
        summary = meta.get("filings_summary") or {}
        results.append(
            {
                "market": target["market"],
                "ticker": target["ticker"],
                "prior_regime": target["prior_regime"],
                "regime": meta.get("filings_regime"),
                "filings_total": summary.get("total", 0),
                "with_body": summary.get("with_body", 0),
            }
        )
        logger.info(
            "Re-ingested filings %s/%s → regime=%s total=%s",
            target["market"],
            target["ticker"],
            meta.get("filings_regime"),
            summary.get("total", 0),
        )
    return {
        "markets": list(markets),
        "only_unsupported": only_unsupported,
        "target_count": len(targets),
        "results": results,
    }


def list_failed_metric_tickers(root: Path, market_id: str) -> list[str]:
    """Tickers in latest metrics that still carry fetch errors."""
    path = market_dir(root, market_id) / "metrics" / "latest.json.gz"
    alt = market_dir(root, market_id) / "metrics" / "latest.json"
    metrics_path = path if path.exists() else alt
    if not metrics_path.exists():
        return []
    rows = read_json(metrics_path)
    return [
        str(row["ticker"])
        for row in rows
        if row.get("ticker") and row.get("errors")
    ]


def retry_failed_metrics(
    root: Path,
    markets: list[str],
    *,
    fetch_fn=None,
) -> list[dict[str, Any]]:
    """Re-fetch every metrics row that currently has errors."""
    summaries: list[dict[str, Any]] = []
    for market_id in markets:
        if market_id not in MARKET_REGISTRY:
            raise ValueError(f"Unknown market {market_id!r}")
        failed = list_failed_metric_tickers(root, market_id)
        if not failed:
            summaries.append(
                {
                    "market": market_id,
                    "selected": [],
                    "updated": 0,
                    "errors": 0,
                    "still_failed": [],
                }
            )
            continue
        result = refresh_metrics(
            root,
            market_id,
            max_tickers=len(failed),
            only_tickers=failed,
            fetch_fn=fetch_fn,
        )
        still = list_failed_metric_tickers(root, market_id)
        result["still_failed"] = still
        summaries.append(result)
        logger.info(
            "Retried failed metrics %s: %d selected, %d still failed",
            market_id,
            len(failed),
            len(still),
        )
    return summaries


def _prune_dated_by_keep_runs(directory: Path, patterns: tuple[str, ...], *, keep_runs: int) -> list[Path]:
    if keep_runs < 1 or not directory.exists():
        return []
    stamped: dict[str, list[Path]] = {}
    for pattern in patterns:
        for path in directory.glob(pattern):
            if not path.is_file():
                continue
            if path.name.startswith("latest"):
                continue
            stamp = _run_stamp(path)
            if stamp is None:
                continue
            stamped.setdefault(stamp, []).append(path)
    if not stamped:
        return []
    ordered = sorted(stamped.keys(), reverse=True)
    keep = set(ordered[:keep_runs])
    removed: list[Path] = []
    for stamp, paths in stamped.items():
        if stamp in keep:
            continue
        for path in paths:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


def prune_library_screen_history(
    root: Path,
    markets: list[str] | None = None,
    *,
    keep_runs: int = DEFAULT_SCREEN_KEEP_RUNS,
) -> dict[str, Any]:
    """
    Prune dated screen CSV/JSON copies under each market's ``screen/``.

    Always keeps ``latest_*`` and ``signal_history.csv``. Retains the newest
    ``keep_runs`` timestamped run groups (and matching ``history/`` snapshots).
    """
    selected = markets or [mid for mid in MARKET_REGISTRY if mid != "ftse350"]
    per_market: dict[str, dict[str, int]] = {}
    total_removed = 0
    for market_id in selected:
        screen_dir = market_dir(root, market_id) / "screen"
        if not screen_dir.exists():
            continue
        removed_screen = _prune_dated_by_keep_runs(
            screen_dir, _SCREEN_DATED_GLOBS, keep_runs=keep_runs
        )
        removed_history = _prune_dated_by_keep_runs(
            screen_dir / "history", _HISTORY_DATED_GLOBS, keep_runs=keep_runs
        )
        count = len(removed_screen) + len(removed_history)
        per_market[market_id] = {
            "screen_removed": len(removed_screen),
            "history_removed": len(removed_history),
            "removed": count,
        }
        total_removed += count
    return {
        "keep_runs": keep_runs,
        "markets": selected,
        "total_removed": total_removed,
        "per_market": per_market,
    }
