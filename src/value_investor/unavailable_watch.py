"""Unavailable / bypass watchlist for suggested trades.

Names stay in the screening universe and can keep updating, but are excluded from
actionable trade suggestions and paper auto-entries until restored. The dashboard
browser list is the primary UX; this module backs an optional server-side JSON
mirror under ``docs/data/library/t212_coverage/`` (legacy ``ii_coverage/`` still read).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.storage import read_json, write_json

DEFAULT_UNAVAILABLE_PATH = DEFAULT_LIBRARY_ROOT / "t212_coverage" / "unavailable_watch.json"
LEGACY_UNAVAILABLE_PATH = DEFAULT_LIBRARY_ROOT / "ii_coverage" / "unavailable_watch.json"


def default_unavailable_path(library_root: Path | None = None) -> Path:
    root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    preferred = root / "t212_coverage" / "unavailable_watch.json"
    if preferred.exists() or (root / "t212_coverage").exists():
        return preferred
    legacy = root / "ii_coverage" / "unavailable_watch.json"
    if legacy.exists():
        return legacy
    return preferred


def empty_unavailable_watch() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "updated_at": None,
        "note": (
            "Tickers marked unavailable to trade on Trading 212 (or otherwise "
            "unactionable). Keep screening/watching; exclude from suggested trades until restored."
        ),
        "items": [],
    }


def load_unavailable_watch(path: Path | None = None) -> dict[str, Any]:
    if path is not None:
        target = Path(path)
    else:
        target = default_unavailable_path()
        if not target.exists() and LEGACY_UNAVAILABLE_PATH.exists():
            target = LEGACY_UNAVAILABLE_PATH
    if not target.exists():
        return empty_unavailable_watch()
    payload = read_json(target)
    if not isinstance(payload, dict):
        return empty_unavailable_watch()
    items = payload.get("items") or []
    payload["items"] = [dict(row) for row in items if isinstance(row, dict) and row.get("ticker")]
    return payload


def save_unavailable_watch(payload: dict[str, Any], path: Path | None = None) -> Path:
    target = Path(path or default_unavailable_path())
    out = dict(payload)
    out["schema_version"] = 1
    out["updated_at"] = datetime.now(UTC).isoformat()
    out.setdefault("note", empty_unavailable_watch()["note"])
    write_json(target, out, compact=False)
    return target


def unavailable_tickers(path: Path | None = None) -> set[str]:
    payload = load_unavailable_watch(path)
    return {str(row["ticker"]).strip().upper() for row in payload.get("items") or [] if row.get("ticker")}


def mark_unavailable(
    ticker: str,
    *,
    name: str | None = None,
    reason: str = "unavailable_on_t212",
    path: Path | None = None,
) -> dict[str, Any]:
    key = str(ticker or "").strip().upper()
    if not key:
        raise ValueError("ticker required")
    payload = load_unavailable_watch(path)
    items = list(payload.get("items") or [])
    existing = next((row for row in items if str(row.get("ticker", "")).upper() == key), None)
    now = datetime.now(UTC).isoformat()
    if existing:
        existing["reason"] = reason
        existing["updated_at"] = now
        if name:
            existing["name"] = name
        existing["status"] = "watching"
    else:
        items.append(
            {
                "ticker": key,
                "name": name,
                "reason": reason,
                "status": "watching",
                "marked_at": now,
                "updated_at": now,
            }
        )
    payload["items"] = items
    save_unavailable_watch(payload, path)
    return payload


def restore_unavailable(ticker: str, *, path: Path | None = None) -> dict[str, Any]:
    key = str(ticker or "").strip().upper()
    payload = load_unavailable_watch(path)
    items = [row for row in (payload.get("items") or []) if str(row.get("ticker", "")).upper() != key]
    payload["items"] = items
    save_unavailable_watch(payload, path)
    return payload


def is_unavailable(ticker: str, *, path: Path | None = None) -> bool:
    return str(ticker or "").strip().upper() in unavailable_tickers(path)
