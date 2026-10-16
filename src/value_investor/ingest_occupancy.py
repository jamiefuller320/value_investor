"""Observe-only ingest occupancy row.

The fat slot is occupied only while ``head_needs_fat_slot`` is true. This row
records dispatch, the euro market-status badge, and whether those disagree.
It does not start a sprint, clear a park, or widen a stream.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.engineering_queue import COMMITTED_TASKS_PATH, DISPATCHABLE_STATUS
from value_investor.library_ingest_dispatch import DEFAULT_DISPATCH_PATH
from value_investor.market_status import DEFAULT_MARKET_STATUS_PATH
from value_investor.storage import read_json, write_json
from value_investor.universe_filing_archive_status import DEFAULT_PACK_RUN_PATH

DEFAULT_OCCUPANCY_PATH = Path("docs/data/ingest_occupancy.json")
SCHEMA_VERSION = 1
MISMATCH_TITLE = "Ingest occupancy mismatch"


def _read(path: Path | None) -> dict[str, Any]:
    if path is None or not Path(path).exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _euro_badge(status: dict[str, Any], focus: str) -> tuple[str | None, str | None]:
    markets = status.get("markets")
    row: dict[str, Any] = {}
    if isinstance(markets, dict):
        row = _as_dict(markets.get(focus))
    elif isinstance(markets, list):
        for item in markets:
            if isinstance(item, dict) and str(item.get("market_id") or "") == focus:
                row = item
                break
    if not row:
        return None, None
    ingest = str(row.get("ingest") or "").strip().lower() or None
    reason = row.get("ingest_reason")
    reason_text = str(reason).strip() if reason else None
    return ingest, reason_text


def _spare_should_run(dispatch: dict[str, Any]) -> bool | None:
    markets = [
        str(item).strip()
        for item in (dispatch.get("parallel_sprint_markets") or [])
        if str(item).strip()
    ]
    stream1 = markets[0] if markets else ""
    rows = dispatch.get("parallel_sprint_status") or []
    if not isinstance(rows, list):
        return None
    chosen: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if stream1 and str(row.get("market_id") or "") == stream1:
            chosen = row
            break
        if chosen is None:
            chosen = row
    if chosen is None or "should_run_parallel_ingest" not in chosen:
        return None
    return bool(chosen.get("should_run_parallel_ingest"))


def _eng_open_count(tasks: dict[str, Any]) -> int:
    rows = tasks.get("tasks") if isinstance(tasks.get("tasks"), list) else []
    return sum(
        1
        for row in rows
        if isinstance(row, dict) and str(row.get("status") or "") == DISPATCHABLE_STATUS
    )


def build_ingest_occupancy(
    *,
    dispatch: dict[str, Any] | None = None,
    market_status: dict[str, Any] | None = None,
    pack_run: dict[str, Any] | None = None,
    tasks: dict[str, Any] | None = None,
    dispatch_path: Path = DEFAULT_DISPATCH_PATH,
    market_status_path: Path = DEFAULT_MARKET_STATUS_PATH,
    pack_run_path: Path = DEFAULT_PACK_RUN_PATH,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One occupancy row. Missing files stay null; they do not invent a sprint."""
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    dispatch_row = dispatch if dispatch is not None else _read(dispatch_path)
    status_row = market_status if market_status is not None else _read(market_status_path)
    pack_row = pack_run if pack_run is not None else _read(pack_run_path)
    tasks_row = tasks if tasks is not None else _read(tasks_path)

    cascade = _as_dict(dispatch_row.get("ingest_cascade"))
    focus = str(
        dispatch_row.get("focus_market") or dispatch_row.get("market_id") or "euro_depth"
    ).strip() or "euro_depth"
    badge, badge_reason = _euro_badge(status_row, focus)
    bit_known = "head_needs_fat_slot" in cascade
    head_needs = bool(cascade.get("head_needs_fat_slot")) if bit_known else None
    badge_says_sprint = badge == "sprint"
    mismatch = bool(badge_says_sprint and head_needs is False)

    gate = _as_dict(pack_row.get("gate"))
    gate_at = gate.get("evaluated_at") or pack_row.get("generated_at")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "focus_market": focus,
        "dispatch_mode": str(dispatch_row.get("mode") or "") or None,
        "should_run_sprint_ingest": dispatch_row.get("should_run_sprint_ingest"),
        "head_needs_fat_slot": head_needs,
        "euro_ingest": badge,
        "euro_ingest_reason": badge_reason,
        "mismatch": mismatch,
        "cold_store_gate_at": gate_at,
        "cold_store_focus_pressure_reasons": list(gate.get("focus_pressure_reasons") or []),
        "dispatch_evaluated_at": dispatch_row.get("evaluated_at"),
        "spare_should_run_parallel_ingest": _spare_should_run(dispatch_row),
        "eng_open_count": _eng_open_count(tasks_row),
        "auto_fixable": False,
        "note": (
            "Fat slot is occupied only while head_needs_fat_slot is true. "
            "Badge/bit mismatch is observe-only."
        ),
    }


def occupancy_finding_summary(row: dict[str, Any]) -> str:
    return (
        f"dispatch mode={row.get('dispatch_mode')} "
        f"should_run_sprint_ingest={row.get('should_run_sprint_ingest')} "
        f"head_needs_fat_slot={row.get('head_needs_fat_slot')}; "
        f"euro ingest={row.get('euro_ingest')} ({row.get('euro_ingest_reason')}); "
        f"cold-store gate {row.get('cold_store_gate_at')} vs dispatch "
        f"{row.get('dispatch_evaluated_at')}; "
        f"spare should_run={row.get('spare_should_run_parallel_ingest')}; "
        f"eng open={row.get('eng_open_count')}."
    )


def write_ingest_occupancy(
    row: dict[str, Any],
    path: Path = DEFAULT_OCCUPANCY_PATH,
) -> dict[str, Any]:
    write_json(path, row)
    return row
