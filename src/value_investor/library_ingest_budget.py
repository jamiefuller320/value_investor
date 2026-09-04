"""Split library ingest wall-clock between listing discovery and body deepen.

Euro sprint has been forcing a full buy-tier discovery scan, then hitting the
2700s GHA budget after 0–1 deepen targets. Discovery still runs (and still
counts toward the shared clock) but may use at most a quarter of the budget
and must leave most of the slot for body fetch.
"""

from __future__ import annotations

import time
from typing import Any

DEFAULT_DISCOVERY_BUDGET_FRACTION = 0.25
DEFAULT_MIN_DEEPEN_FRACTION = 2.0 / 3.0
DEFAULT_MIN_DEEPEN_SECONDS_CAP = 1200.0
# Same default as FTSE ingest_improvement; library weekday batches abort mid-ticker.
DEFAULT_PER_TICKER_MAX_SECONDS = 320.0
DEFAULT_MIN_TICKER_START_SECONDS = 45.0
DEFAULT_BLOCKER_COOLDOWN_HOURS = 6.0


def discovery_runtime_budget(max_runtime_seconds: float) -> float:
    """Seconds discovery may consume from ``max_runtime_seconds``.

    Returns 0 when there is no budget. Never larger than 25% of the slot, and
    always leaves at least two-thirds of the slot (capped at 20 minutes) for
    deepen when the total budget is positive.
    """
    budget = float(max_runtime_seconds or 0.0)
    if budget <= 0:
        return 0.0
    fraction_cap = budget * DEFAULT_DISCOVERY_BUDGET_FRACTION
    min_deepen = min(budget * DEFAULT_MIN_DEEPEN_FRACTION, DEFAULT_MIN_DEEPEN_SECONDS_CAP)
    reserved_for_discovery = max(0.0, budget - min_deepen)
    return min(fraction_cap, reserved_for_discovery)


def discovery_prefer_tickers(critical: Any) -> list[str]:
    """Scan thin / unmeasured / zero-body / IWB names before the rest of buy-tier."""
    prefer: list[str] = []
    seen: set[str] = set()

    def _add(ticker: str) -> None:
        key = str(ticker or "").strip().upper()
        if key and key not in seen:
            seen.add(key)
            prefer.append(key)

    for ticker in list(getattr(critical, "thin_need_discovery", None) or []):
        _add(str(ticker))
    for ticker in list(getattr(critical, "unmeasured", None) or []):
        _add(str(ticker))
    for ticker in list(getattr(critical, "zero_body", None) or []):
        _add(str(ticker))
    for row in list(getattr(critical, "indexed_without_body", None) or []):
        if isinstance(row, dict):
            _add(str(row.get("ticker") or ""))
        else:
            _add(str(row))
    return prefer


def deadline_reached(deadline_monotonic: float | None, *, now: float | None = None) -> bool:
    """True when a monotonic deadline has passed. ``None`` means no deadline."""
    if deadline_monotonic is None:
        return False
    current = time.monotonic() if now is None else float(now)
    return current >= float(deadline_monotonic)


def weekday_per_ticker_max_seconds(
    *,
    pin_tickers: list[str] | None,
    record_gap_closure: bool,
    per_ticker_max_seconds: float | None = DEFAULT_PER_TICKER_MAX_SECONDS,
) -> float | None:
    """Weekday batches get a cap; intensive pin / gap-closure uses the remaining slot."""
    if pin_tickers or record_gap_closure:
        return None
    if per_ticker_max_seconds is None:
        return None
    budget = float(per_ticker_max_seconds)
    return budget if budget > 0 else None


def ticker_deadline(
    *,
    slot_started: float,
    max_runtime_seconds: float,
    per_ticker_max_seconds: float | None,
    now: float | None = None,
) -> float | None:
    """Monotonic deadline for one deepen ticker (slot end and optional per-ticker cap)."""
    current = time.monotonic() if now is None else float(now)
    slot = float(max_runtime_seconds or 0.0)
    slot_end = (slot_started + slot) if slot > 0 else None
    if per_ticker_max_seconds is None:
        return slot_end
    ticker_end = current + float(per_ticker_max_seconds)
    if slot_end is None:
        return ticker_end
    return min(slot_end, ticker_end)


def should_start_next_ticker(
    *,
    slot_started: float,
    max_runtime_seconds: float,
    min_start_seconds: float = DEFAULT_MIN_TICKER_START_SECONDS,
    now: float | None = None,
) -> bool:
    """Skip starting another ticker when the shared slot has almost no time left."""
    current = time.monotonic() if now is None else float(now)
    remaining = float(max_runtime_seconds or 0.0) - (current - float(slot_started))
    return remaining >= float(min_start_seconds)


def select_blocker_ticker(results: list[Any]) -> str | None:
    """First 0-improve deepen row that hit the ticker budget or exhausted IR retries."""
    if not isinstance(results, list):
        return None
    for row in results:
        if not isinstance(row, dict) or row.get("improved"):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        if row.get("ticker_budget_hit") or row.get("ir_exhausted"):
            return ticker
    return None


__all__ = [
    "DEFAULT_BLOCKER_COOLDOWN_HOURS",
    "DEFAULT_DISCOVERY_BUDGET_FRACTION",
    "DEFAULT_MIN_DEEPEN_FRACTION",
    "DEFAULT_MIN_DEEPEN_SECONDS_CAP",
    "DEFAULT_MIN_TICKER_START_SECONDS",
    "DEFAULT_PER_TICKER_MAX_SECONDS",
    "deadline_reached",
    "discovery_prefer_tickers",
    "discovery_runtime_budget",
    "select_blocker_ticker",
    "should_start_next_ticker",
    "ticker_deadline",
    "weekday_per_ticker_max_seconds",
]
