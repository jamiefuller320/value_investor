"""Graduated-only entry DCA execute helpers (human-gated via Lifecycle Start).

When ``entry_dca_execute_cadence`` is set on the graduated_allocation track,
new sleeves take the first tranche only and remaining tranches are scheduled in
``entry_dca_pending.json``. Never enables primary/live or other tracks.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.entry_dca_overlay import DEFAULT_CADENCES, DcaCadence
from value_investor.storage import read_json, write_json

PENDING_FILENAME = "entry_dca_pending.json"
DEFAULT_EXECUTE_TRACK = "graduated_allocation"
DEFAULT_EXECUTE_CADENCE = "dca_4x_weekly"


def resolve_cadence(cadence_id: str | None) -> DcaCadence | None:
    key = str(cadence_id or "").strip()
    if not key:
        return None
    for row in DEFAULT_CADENCES:
        if row.id == key:
            return row
    return None


def _parse_date(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text[:10])


def load_pending(path: Path) -> dict[str, Any]:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return {"schema_version": 1, "pending": []}
    if not isinstance(raw, dict):
        return {"schema_version": 1, "pending": []}
    pending = [row for row in (raw.get("pending") or []) if isinstance(row, dict)]
    return {
        "schema_version": 1,
        "pending": pending,
        "updated_at": raw.get("updated_at"),
        "cadence": raw.get("cadence"),
        "track_id": raw.get("track_id"),
    }


def save_pending(path: Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "schema_version": 1,
        "updated_at": datetime.now(UTC).isoformat(),
        "cadence": payload.get("cadence"),
        "track_id": payload.get("track_id") or DEFAULT_EXECUTE_TRACK,
        "pending": [row for row in (payload.get("pending") or []) if isinstance(row, dict)],
    }
    write_json(path, out, compact=False)
    return path


def schedule_remaining_tranches(
    *,
    ticker: str,
    sleeve_notional: float,
    cadence: DcaCadence,
    started_on: date,
    name: str = "",
    sector: str = "",
) -> list[dict[str, Any]]:
    """Return pending rows for tranches 2..N after the first fill."""
    tranches = max(1, int(cadence.tranches))
    if tranches <= 1:
        return []
    per = float(sleeve_notional) / float(tranches)
    rows: list[dict[str, Any]] = []
    for index in range(1, tranches):
        due = started_on + timedelta(days=int(cadence.interval_days) * index)
        rows.append(
            {
                "ticker": str(ticker),
                "tranche_index": index + 1,
                "tranches": tranches,
                "notional_gbp": round(per, 2),
                "due_on": due.isoformat(),
                "cadence": cadence.id,
                "name": name,
                "sector": sector,
                "status": "open",
            }
        )
    return rows


def first_tranche_notional(sleeve_notional: float, cadence: DcaCadence | None) -> float:
    if cadence is None or int(cadence.tranches) <= 1:
        return float(sleeve_notional)
    return float(sleeve_notional) / float(cadence.tranches)


def due_pending_rows(
    pending: dict[str, Any] | None,
    *,
    as_of: date,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in (pending or {}).get("pending") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "open") != "open":
            continue
        due = _parse_date(row.get("due_on"))
        if due is None or due > as_of:
            continue
        out.append(row)
    return out


def mark_pending_filled(pending: dict[str, Any], row: dict[str, Any], *, filled_at: str) -> None:
    for item in pending.get("pending") or []:
        if item is row:
            item["status"] = "filled"
            item["filled_at"] = filled_at
            return


def enable_graduated_entry_dca_execute(
    paper_root: Path,
    *,
    cadence: str = DEFAULT_EXECUTE_CADENCE,
    track_id: str = DEFAULT_EXECUTE_TRACK,
) -> dict[str, Any]:
    """Set execute cadence on graduated_allocation config only."""
    track_id = str(track_id or DEFAULT_EXECUTE_TRACK).strip() or DEFAULT_EXECUTE_TRACK
    cadence_id = str(cadence or DEFAULT_EXECUTE_CADENCE).strip() or DEFAULT_EXECUTE_CADENCE
    resolved = resolve_cadence(cadence_id)
    if resolved is None:
        raise ValueError(f"Unknown entry DCA cadence {cadence_id!r}")
    if track_id != DEFAULT_EXECUTE_TRACK:
        raise ValueError(
            f"Entry DCA execute is allowed only on {DEFAULT_EXECUTE_TRACK!r}; got {track_id!r}"
        )
    config_path = Path(paper_root) / track_id / "config.json"
    try:
        config = read_json(config_path)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Missing graduated config at {config_path}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"Invalid graduated config at {config_path}")
    config["entry_dca_execute_cadence"] = resolved.id
    config["use_graduated_allocation"] = True
    write_json(config_path, config, compact=False)
    pending_path = Path(paper_root) / track_id / PENDING_FILENAME
    if not pending_path.exists():
        save_pending(
            pending_path,
            {"cadence": resolved.id, "track_id": track_id, "pending": []},
        )
    return {
        "track_id": track_id,
        "cadence": resolved.id,
        "tranches": resolved.tranches,
        "interval_days": resolved.interval_days,
        "config_path": str(config_path),
        "pending_path": str(pending_path),
    }


__all__ = [
    "PENDING_FILENAME",
    "DEFAULT_EXECUTE_TRACK",
    "DEFAULT_EXECUTE_CADENCE",
    "resolve_cadence",
    "load_pending",
    "save_pending",
    "schedule_remaining_tranches",
    "first_tranche_notional",
    "due_pending_rows",
    "mark_pending_filled",
    "enable_graduated_entry_dca_execute",
]
