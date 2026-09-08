"""Stagger shared library ingest maintenance so three+ books do not clip (L323)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

CURSOR_FILENAME = "maintenance_slot_cursor.json"
CROWDED_MARKET_THRESHOLD = 3
MAX_MARKETS_WHEN_CROWDED = 1


def rotate_after(markets: list[str], last_head: str | None) -> list[str]:
    """Stable-sort then start after the last served head (round-robin)."""
    ordered = sorted({str(m).strip() for m in markets if str(m).strip()})
    if not ordered:
        return []
    if not last_head or last_head not in ordered:
        return ordered
    idx = ordered.index(last_head)
    return ordered[idx + 1 :] + ordered[: idx + 1]


def load_maintenance_slot_cursor(library_root: Path) -> dict[str, Any]:
    path = Path(library_root) / CURSOR_FILENAME
    if not path.exists():
        return {}
    try:
        raw = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def write_maintenance_slot_cursor(
    library_root: Path,
    *,
    last_head: str,
    selected: list[str],
    deferred: list[str],
    when: datetime | None = None,
) -> Path:
    path = Path(library_root) / CURSOR_FILENAME
    payload = {
        "schema_version": 1,
        "updated_at": (when or datetime.now(UTC)).isoformat(),
        "last_head": last_head,
        "selected": list(selected),
        "deferred": list(deferred),
    }
    write_json(path, payload, compact=False)
    return path


def plan_maintenance_slot(
    markets: list[str],
    *,
    library_root: Path | None = None,
    last_head: str | None = None,
    crowded_threshold: int = CROWDED_MARKET_THRESHOLD,
    max_markets_when_crowded: int = MAX_MARKETS_WHEN_CROWDED,
) -> dict[str, Any]:
    """Pick this slot's maintenance markets.

    One sequential job at 62 targets / 3600s cannot finish three books inside
    ``timeout-minutes: 120`` (especially after the euro fat-slot wait). When the
    list is crowded, serve one market per slot and rotate.
    """
    wanted = [str(m).strip() for m in markets if str(m).strip()]
    unique = list(dict.fromkeys(wanted))
    if len(unique) < int(crowded_threshold):
        return {
            "staggered": False,
            "reason": "fits_in_one_job",
            "configured": unique,
            "selected": unique,
            "deferred": [],
            "last_head": last_head,
        }
    if last_head is None and library_root is not None:
        last_head = str(load_maintenance_slot_cursor(library_root).get("last_head") or "") or None
    rotated = rotate_after(unique, last_head)
    cap = max(1, int(max_markets_when_crowded))
    selected = rotated[:cap]
    deferred = rotated[cap:]
    return {
        "staggered": True,
        "reason": "crowded_rotate_one",
        "configured": unique,
        "selected": selected,
        "deferred": deferred,
        "last_head": last_head,
        "note": (
            "Three-plus maintenance books share one 120-minute job. "
            "This slot runs one market at full FTSE volume; the rest wait "
            "for the next cron (4 slots/day)."
        ),
    }


__all__ = [
    "CROWDED_MARKET_THRESHOLD",
    "CURSOR_FILENAME",
    "MAX_MARKETS_WHEN_CROWDED",
    "load_maintenance_slot_cursor",
    "plan_maintenance_slot",
    "rotate_after",
    "write_maintenance_slot_cursor",
]
