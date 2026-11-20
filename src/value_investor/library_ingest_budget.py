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
# Maintenance names are not killed at 320s of wall clock. 320s is how long a
# fetch or a PDF parse may sit with no progress before that name stops.
# A single network read still uses its own shorter timeout.
DEFAULT_NO_PROGRESS_SECONDS = DEFAULT_PER_TICKER_MAX_SECONDS
DEFAULT_FETCH_TIMEOUT_SECONDS = 60.0


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
    """Scan unmeasured / zero-body, then thin / IWB names, before the rest of buy-tier."""
    prefer: list[str] = []
    seen: set[str] = set()

    def _add(ticker: str) -> None:
        key = str(ticker or "").strip().upper()
        if key and key not in seen:
            seen.add(key)
            prefer.append(key)

    for ticker in list(getattr(critical, "unmeasured", None) or []):
        _add(str(ticker))
    for ticker in list(getattr(critical, "zero_body", None) or []):
        _add(str(ticker))
    for ticker in list(getattr(critical, "thin_need_discovery", None) or []):
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


class IngestHangWatch:
    """Stop a maintenance name when work stops, not when the clock hits 320s.

    ``note_progress`` keeps a long PDF parse alive. ``hung_fetch`` stops a
    network read that exceeds the fetch timeout. ``parse_stall`` stops a parse
    that has started and then produced nothing. The shared slot deadline still
    ends the name so one parse cannot use the whole job.
    """

    def __init__(
        self,
        *,
        stall_seconds: float = DEFAULT_NO_PROGRESS_SECONDS,
        fetch_timeout_seconds: float = DEFAULT_FETCH_TIMEOUT_SECONDS,
        slot_deadline: float | None = None,
        now: float | None = None,
    ) -> None:
        self.stall_seconds = float(stall_seconds)
        self.fetch_timeout_seconds = float(fetch_timeout_seconds)
        self.slot_deadline = slot_deadline
        current = time.monotonic() if now is None else float(now)
        self.last_progress = current
        self.parse_started: float | None = None
        self.stop_reason: str | None = None

    def note_progress(self, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else float(now)
        self.last_progress = current
        self.parse_started = None
        self.stop_reason = None

    def begin_parse(self, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else float(now)
        self.parse_started = current
        self.last_progress = current
        self.stop_reason = None

    def note_parse_progress(self, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else float(now)
        self.last_progress = current

    def _slot_expired(self, current: float) -> bool:
        return self.slot_deadline is not None and current >= float(self.slot_deadline)

    def hung_fetch(self, elapsed_seconds: float, *, now: float | None = None) -> str | None:
        """Stop a fetch that has not returned within the network timeout."""
        current = time.monotonic() if now is None else float(now)
        if self._slot_expired(current):
            self.stop_reason = "runtime_budget"
            return self.stop_reason
        if float(elapsed_seconds) >= self.fetch_timeout_seconds:
            self.stop_reason = "hung_fetch"
            return self.stop_reason
        return None

    def parse_stall(self, *, now: float | None = None) -> str | None:
        """Stop a parse that has made no progress for ``stall_seconds``."""
        current = time.monotonic() if now is None else float(now)
        if self._slot_expired(current):
            self.stop_reason = "runtime_budget"
            return self.stop_reason
        if self.parse_started is None:
            return None
        if current - self.last_progress >= self.stall_seconds:
            self.stop_reason = "parse_no_progress"
            return self.stop_reason
        return None

    def allow_continuing(self, *, now: float | None = None) -> bool:
        """True while progress is recent and the shared slot is still open."""
        current = time.monotonic() if now is None else float(now)
        if self._slot_expired(current):
            self.stop_reason = "runtime_budget"
            return False
        if current - self.last_progress >= self.stall_seconds:
            self.stop_reason = "no_progress"
            return False
        self.stop_reason = None
        return True


_ACTIVE_HANG_WATCH: IngestHangWatch | None = None


def bind_hang_watch(watch: IngestHangWatch | None) -> None:
    """Install the maintenance watch so a PDF parse can see it."""
    global _ACTIVE_HANG_WATCH
    _ACTIVE_HANG_WATCH = watch


def active_hang_watch() -> IngestHangWatch | None:
    return _ACTIVE_HANG_WATCH


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
    "DEFAULT_FETCH_TIMEOUT_SECONDS",
    "DEFAULT_NO_PROGRESS_SECONDS",
    "IngestHangWatch",
    "active_hang_watch",
    "bind_hang_watch",
    "deadline_reached",
    "discovery_prefer_tickers",
    "discovery_runtime_budget",
    "select_blocker_ticker",
    "should_start_next_ticker",
    "ticker_deadline",
    "weekday_per_ticker_max_seconds",
]
