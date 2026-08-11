"""Persist and resume ingest-improvement targets after runtime cutoff."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_BACKLOG_PATH = Path("docs/data/ingest_backlog.json")


def load_ingest_backlog(path: Path = DEFAULT_BACKLOG_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        logger.warning("Could not read ingest backlog at %s — ignoring", path)
        return {}
    return payload if isinstance(payload, dict) else {}


def backlog_tickers(payload: dict[str, Any]) -> list[str]:
    tickers: list[str] = []
    for raw in payload.get("remaining_tickers") or []:
        ticker = str(raw or "").strip().upper()
        if ticker:
            tickers.append(ticker)
    return tickers


def prioritize_backlog_targets(
    candidates: list[Any],
    backlog_tickers: list[str],
) -> list[Any]:
    """Reorder ranked candidates so backlog tickers run first (stable backlog order)."""
    if not backlog_tickers:
        return list(candidates)
    by_ticker = {row.ticker.upper(): row for row in candidates}
    ordered: list[Any] = []
    seen: set[str] = set()
    for raw in backlog_tickers:
        ticker = str(raw or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        row = by_ticker.get(ticker)
        if row is None:
            continue
        ordered.append(row)
        seen.add(ticker)
    for row in candidates:
        key = row.ticker.upper()
        if key not in seen:
            ordered.append(row)
            seen.add(key)
    return ordered


def record_ingest_backlog_after_pass(
    *,
    targets: list[Any],
    completed_tickers: list[str],
    runtime_cutoff: bool,
    path: Path = DEFAULT_BACKLOG_PATH,
) -> dict[str, Any]:
    """Write remaining tickers after cutoff, or clear backlog when the pass completes."""
    path = Path(path)
    if runtime_cutoff:
        completed = {str(t or "").strip().upper() for t in completed_tickers}
        remaining = [row.ticker for row in targets if row.ticker.upper() not in completed]
        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "reason": "runtime_cutoff",
            "remaining_tickers": remaining,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload, compact=False)
        return payload

    if path.exists():
        try:
            path.unlink()
        except OSError:
            logger.warning("Could not clear ingest backlog at %s", path)
    return {"cleared": True, "updated_at": datetime.now(UTC).isoformat()}
