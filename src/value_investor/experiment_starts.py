"""Durable human Start authorizations for lifecycle recommend rows.

Sunday assessment refresh rebuilds the ledger from evidence. Starts live in
``docs/data/experiment_starts.json`` so authorizing graduated execute is not
wiped. Matching is by experiment id plus leading finding key (for the DCA
overlay: ``leading_cadence``). A new leading cadence re-opens Start.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

STARTS_FILENAME = "experiment_starts.json"
START_DECISIONS = frozenset({"start_execute_graduated"})


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def load_starts(data_dir: Path) -> dict[str, Any]:
    path = Path(data_dir) / STARTS_FILENAME
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return {"schema_version": 1, "starts": []}
    if not isinstance(raw, dict):
        return {"schema_version": 1, "starts": []}
    starts = [row for row in (raw.get("starts") or []) if isinstance(row, dict)]
    return {"schema_version": 1, "starts": starts, "updated_at": raw.get("updated_at")}


def matching_start(
    starts: dict[str, Any] | None,
    *,
    experiment_id: str,
    finding: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    experiment_id = str(experiment_id or "").strip()
    if not experiment_id:
        return None
    finding = _as_dict(finding)
    lead = str(finding.get("leading_cadence") or "").strip() or None
    for row in (starts or {}).get("starts") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("experiment_id") or "") != experiment_id:
            continue
        if str(row.get("status") or "open") != "open":
            continue
        start_lead = (
            str((_as_dict(row.get("finding")).get("leading_cadence")) or "").strip() or None
        )
        if lead and start_lead and lead != start_lead:
            continue
        return row
    return None


def record_start(
    data_dir: Path,
    *,
    experiment_id: str,
    decision: str = "start_execute_graduated",
    note: str = "",
    finding: dict[str, Any] | None = None,
    source: str = "",
    started_by: str = "human",
    track_id: str = "graduated_allocation",
    cadence: str = "dca_4x_weekly",
) -> dict[str, Any]:
    """Append or refresh an open Start authorization. Returns the stored row."""
    experiment_id = str(experiment_id or "").strip()
    if not experiment_id:
        raise ValueError("experiment_id is required")
    decision = str(decision or "start_execute_graduated").strip()
    if decision not in START_DECISIONS:
        raise ValueError(f"Unknown start decision {decision!r}; allowed: {sorted(START_DECISIONS)}")
    store = load_starts(data_dir)
    finding = _as_dict(finding)
    existing = matching_start(store, experiment_id=experiment_id, finding=finding)
    now = _utcnow()
    row = {
        "experiment_id": experiment_id,
        "decision": decision,
        "status": "open",
        "started_at": now,
        "started_by": started_by,
        "note": str(note or "").strip(),
        "finding": finding,
        "source": str(source or "").strip(),
        "track_id": str(track_id or "graduated_allocation").strip(),
        "cadence": str(cadence or "dca_4x_weekly").strip(),
    }
    starts = list(store.get("starts") or [])
    if existing:
        starts = [item for item in starts if item is not existing]
    starts.append(row)
    payload = {"schema_version": 1, "updated_at": now, "starts": starts}
    dest = Path(data_dir) / STARTS_FILENAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, payload, compact=False)
    row["path"] = str(dest)
    return row


__all__ = [
    "STARTS_FILENAME",
    "START_DECISIONS",
    "load_starts",
    "matching_start",
    "record_start",
]
