"""One-shot / CLI maintenance for offline multi-market libraries."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import (
    MARKET_REGISTRY,
    market_dir,
    refresh_metrics,
)
from value_investor.library_retention import (
    DEFAULT_MONTHLY_UNTIL_DAYS,
    DEFAULT_RETENTION_DAYS,
    dates_to_remove,
)
from value_investor.research.filings import ingest_filings
from value_investor.signal_stability import prune_signal_history_rows
from value_investor.storage import read_json

logger = logging.getLogger(__name__)

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


def _stamp_date(stamp: str) -> date | None:
    try:
        return datetime.strptime(stamp[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _collect_screen_run_files(screen_dir: Path) -> dict[str, list[Path]]:
    stamped: dict[str, list[Path]] = {}
    if not screen_dir.exists():
        return stamped
    for pattern in _SCREEN_DATED_GLOBS:
        for path in screen_dir.glob(pattern):
            if not path.is_file() or path.name.startswith("latest"):
                continue
            stamp = _run_stamp(path)
            if stamp is None:
                continue
            stamped.setdefault(stamp, []).append(path)
    history_dir = screen_dir / "history"
    if history_dir.is_dir():
        for pattern in _HISTORY_DATED_GLOBS:
            for path in history_dir.glob(pattern):
                if not path.is_file():
                    continue
                stamp = _run_stamp(path)
                if stamp is None:
                    continue
                stamped.setdefault(stamp, []).append(path)
    return stamped


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


def _simplified_company_name(name: str, ticker: str) -> str | None:
    """Shorter search label when a legal full name returns zero news hits."""
    text = (name or "").strip()
    if not text:
        return None
    simplified = text
    # Leading corporate prefixes (Euro/French listings often need the core brand).
    for prefix in ("Compagnie de ", "Compagnie ", "The "):
        if simplified.startswith(prefix):
            simplified = simplified[len(prefix) :]
            break
    # Drop common legal suffixes / punctuation noise.
    for token in (
        " S.A.",
        " SA",
        " SE",
        " NV",
        " N.V.",
        " plc",
        " PLC",
        " Limited",
        " Ltd.",
        " Ltd",
        " Corporation",
        " Corp.",
        " Inc.",
        " Inc",
        " Group",
    ):
        simplified = simplified.replace(token, " ")
    simplified = " ".join(simplified.split()).strip(" ,.-")
    if not simplified or simplified.lower() == text.lower():
        # Fall back to first two words of the original.
        parts = text.replace(",", " ").split()
        simplified = " ".join(parts[:2]).strip() if parts else ""
    if not simplified or simplified.lower() == text.lower():
        return None
    if simplified.upper() == ticker.upper():
        return None
    return simplified


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
        company_name = target["company_name"]
        meta = ingest_filings(
            ticker=target["ticker"],
            company_name=company_name,
            sources_dir=target["sources_dir"],
            api_key=api_key,
            market=target["market"],
        )
        summary = meta.get("filings_summary") or {}
        used_name = company_name
        if int(summary.get("total") or 0) == 0:
            alt = _simplified_company_name(company_name, target["ticker"])
            if alt:
                meta = ingest_filings(
                    ticker=target["ticker"],
                    company_name=alt,
                    sources_dir=target["sources_dir"],
                    api_key=api_key,
                    market=target["market"],
                )
                summary = meta.get("filings_summary") or {}
                used_name = alt
        results.append(
            {
                "market": target["market"],
                "ticker": target["ticker"],
                "prior_regime": target["prior_regime"],
                "regime": meta.get("filings_regime"),
                "company_name_used": used_name,
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


def prune_screen_dir(
    screen_dir: Path,
    *,
    keep_days: int = DEFAULT_RETENTION_DAYS,
    monthly_until_days: int = DEFAULT_MONTHLY_UNTIL_DAYS,
    now: datetime | date | None = None,
    prune_signal_history: bool = True,
) -> dict[str, Any]:
    """
    Apply decreasing-resolution retention to one market's screen-lite artifacts.

    Dated run groups (``signals_*``, ``universe_*``, ``summary_*``, ``history/*``)
    use the same dense → monthly → quarterly policy as fundamentals PIT snapshots.
    ``latest_*`` is never removed. ``signal_history.csv`` rows are thinned on the
    same cadence when ``prune_signal_history`` is true.
    """
    screen_dir = Path(screen_dir)
    stamped = _collect_screen_run_files(screen_dir)
    dated_stamps: list[tuple[str, date]] = []
    for stamp in stamped:
        stamp_day = _stamp_date(stamp)
        if stamp_day is not None:
            dated_stamps.append((stamp, stamp_day))

    drop_stamps = dates_to_remove(
        dated_stamps,
        keep_days=keep_days,
        monthly_until_days=monthly_until_days,
        now=now,
    )
    removed_screen = 0
    removed_history = 0
    for stamp in drop_stamps:
        for path in stamped.get(stamp, []):
            path.unlink(missing_ok=True)
            if path.parent.name == "history":
                removed_history += 1
            else:
                removed_screen += 1

    history_stats = {"removed_rows": 0, "removed_runs": 0}
    if prune_signal_history:
        history_stats = prune_signal_history_rows(
            screen_dir,
            keep_days=keep_days,
            monthly_until_days=monthly_until_days,
            now=now,
        )

    return {
        "screen_removed": removed_screen,
        "history_removed": removed_history,
        "runs_removed": len(drop_stamps),
        "signal_history_rows_removed": int(history_stats.get("removed_rows") or 0),
        "signal_history_runs_removed": int(history_stats.get("removed_runs") or 0),
        "removed": removed_screen + removed_history,
    }


def prune_library_screen_history(
    root: Path,
    markets: list[str] | None = None,
    *,
    keep_days: int = DEFAULT_RETENTION_DAYS,
    monthly_until_days: int = DEFAULT_MONTHLY_UNTIL_DAYS,
    now: datetime | date | None = None,
    prune_signal_history: bool = True,
) -> dict[str, Any]:
    """
    Prune dated screen-lite history under each market's ``screen/``.

    Same decreasing-resolution policy as fundamentals PIT retention. Always keeps
    ``latest_*``; thins ``signal_history.csv`` rows on the same schedule.
    """
    selected = markets or [mid for mid in MARKET_REGISTRY if mid != "ftse350"]
    per_market: dict[str, dict[str, int]] = {}
    total_removed = 0
    total_history_rows = 0
    for market_id in selected:
        screen_dir = market_dir(root, market_id) / "screen"
        if not screen_dir.exists():
            continue
        counts = prune_screen_dir(
            screen_dir,
            keep_days=keep_days,
            monthly_until_days=monthly_until_days,
            now=now,
            prune_signal_history=prune_signal_history,
        )
        per_market[market_id] = counts
        total_removed += int(counts.get("removed") or 0)
        total_history_rows += int(counts.get("signal_history_rows_removed") or 0)
    return {
        "keep_days": keep_days,
        "monthly_until_days": monthly_until_days,
        "markets": selected,
        "total_removed": total_removed,
        "total_signal_history_rows_removed": total_history_rows,
        "per_market": per_market,
    }
