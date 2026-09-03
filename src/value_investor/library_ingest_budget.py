"""Split library ingest wall-clock between listing discovery and body deepen.

Euro sprint has been forcing a full buy-tier discovery scan, then hitting the
2700s GHA budget after 0–1 deepen targets. Discovery still runs (and still
counts toward the shared clock) but may use at most a quarter of the budget
and must leave most of the slot for body fetch.
"""

from __future__ import annotations

from typing import Any

DEFAULT_DISCOVERY_BUDGET_FRACTION = 0.25
DEFAULT_MIN_DEEPEN_FRACTION = 2.0 / 3.0
DEFAULT_MIN_DEEPEN_SECONDS_CAP = 1200.0


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


__all__ = [
    "DEFAULT_DISCOVERY_BUDGET_FRACTION",
    "DEFAULT_MIN_DEEPEN_FRACTION",
    "DEFAULT_MIN_DEEPEN_SECONDS_CAP",
    "discovery_prefer_tickers",
    "discovery_runtime_budget",
]
