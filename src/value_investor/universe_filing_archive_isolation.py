"""Isolation firewall for the universe filing archive / data-pack lane (L499).

Design-only gate: never starts a crawler, never shares critical-path rate-limit
identity, and never claims a fourth equal sprint stream. Callers that later
add a cold-lane poll must consult ``archive_lane_gate`` before any fetch.

Hard isolation requirements (from ``docs/ops/universe-filing-archive-pack.md``):

1. Separate per-source rate-limit **budget IDs** (critical path never shares quota)
2. Preemptible / separate runner class (never delay fat-slot / ingest-loop / gap-closure)
3. Cold storage off the live publish path
4. Auto-suspend when focus has unmeasured/zero-body stalls, 429s, or timeout pressure
5. Quiet-window preference (weekend / post-close) — necessary but not sufficient
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any, Literal

from value_investor.storage import read_json

SCHEMA_VERSION = 1
DEFAULT_DISPATCH_PATH = Path("docs/data/library/euro_ingest_dispatch.json")
DEFAULT_MARKET_STATUS_PATH = Path("docs/data/market_status.json")

# Distinct budget identities — archive must never borrow critical-path quota.
CRITICAL_PATH_BUDGET_ID = "critical_path"
ARCHIVE_LANE_BUDGET_ID = "universe_filing_archive"

# Per-source archive budget suffixes (compose as f"{ARCHIVE_LANE_BUDGET_ID}:{source}").
ARCHIVE_SOURCE_KEYS = (
    "sec",
    "companies_house",
    "esef",
    "news",
    "ir_pdf",
    "yahoo",
)

LaneDecision = Literal["allow", "suspend", "quiet_only"]

# Quiet windows (UTC): weekend all-day + nightly post-close band on weekdays.
WEEKDAY_QUIET_START = time(21, 0)  # 21:00 UTC
WEEKDAY_QUIET_END = time(5, 0)  # 05:00 UTC next morning

FOCUS_PRESSURE_FLAG_IDS = frozenset({"unmeasured_stuck", "zero_body_stuck"})


def archive_budget_id(source: str) -> str:
    """Return the archive-lane rate-limit budget id for one source family."""
    key = str(source or "").strip().lower() or "unknown"
    return f"{ARCHIVE_LANE_BUDGET_ID}:{key}"


def critical_budget_id(source: str) -> str:
    """Return the critical-path rate-limit budget id for one source family."""
    key = str(source or "").strip().lower() or "unknown"
    return f"{CRITICAL_PATH_BUDGET_ID}:{key}"


def budgets_share_quota(left: str, right: str) -> bool:
    """True only when both ids resolve to the same top-level budget family."""
    a = str(left or "").split(":", 1)[0].strip()
    b = str(right or "").split(":", 1)[0].strip()
    return bool(a) and a == b


def in_quiet_window(now: datetime | None = None) -> bool:
    """Return True during weekend UTC days or weekday post-close quiet band."""
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    else:
        clock = clock.astimezone(UTC)
    # Mon=0 … Sun=6
    if clock.weekday() >= 5:
        return True
    t = clock.time()
    if t >= WEEKDAY_QUIET_START or t < WEEKDAY_QUIET_END:
        return True
    return False


def _safe_read(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def focus_pressure_reasons(
    *,
    dispatch: dict[str, Any] | None = None,
    market_status: dict[str, Any] | None = None,
) -> list[str]:
    """Reasons the archive lane must auto-suspend (focus head under pressure)."""
    reasons: list[str] = []
    dispatch = dispatch or {}
    health = _as_dict(dispatch.get("filing_health"))
    unmeasured = int(health.get("unmeasured_buy_tier") or 0)
    zero_body = int(health.get("zero_body_buy_tier") or 0)
    if unmeasured > 0:
        reasons.append(f"focus_unmeasured_buy_tier={unmeasured}")
    if zero_body > 0:
        reasons.append(f"focus_zero_body_buy_tier={zero_body}")

    mode = str(dispatch.get("mode") or "").strip()
    sprint_complete = bool(dispatch.get("ingest_sprint_complete"))
    if mode == "sprint" and not sprint_complete:
        # Fat slot still active — archive must not compete for shared runners/sources.
        reasons.append("focus_fat_slot_sprint_active")

    status = market_status or {}
    markets = _as_dict(status.get("markets")) or _as_dict(status.get("by_market"))
    focus = str(dispatch.get("focus_market") or dispatch.get("market_id") or "").strip()
    focus_row = _as_dict(markets.get(focus)) if focus else {}
    flags = focus_row.get("flags") or focus_row.get("admission_flags") or []
    flag_ids: set[str] = set()
    for flag in _as_list(flags):
        if isinstance(flag, dict):
            fid = str(flag.get("id") or flag.get("flag_id") or "").strip()
        else:
            fid = str(flag or "").strip()
        if fid:
            flag_ids.add(fid)
    for fid in sorted(flag_ids & FOCUS_PRESSURE_FLAG_IDS):
        reasons.append(f"market_status_flag={fid}")

    return reasons


def archive_lane_gate(
    *,
    now: datetime | None = None,
    dispatch_path: Path = DEFAULT_DISPATCH_PATH,
    market_status_path: Path = DEFAULT_MARKET_STATUS_PATH,
    dispatch: dict[str, Any] | None = None,
    market_status: dict[str, Any] | None = None,
    require_quiet_window: bool = True,
    allow_outside_quiet_for_pilot: bool = False,
) -> dict[str, Any]:
    """Evaluate whether an archive-lane poll may proceed (observe / gate only).

    Fail-closed on focus pressure. Quiet window is preferred; weekday daytime
    runs stay suspended unless ``allow_outside_quiet_for_pilot`` is set for a
    documented tiny pilot (still blocked when focus pressure is non-empty).
    """
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    else:
        clock = clock.astimezone(UTC)

    dispatch_payload = dispatch if dispatch is not None else _safe_read(Path(dispatch_path))
    status_payload = (
        market_status if market_status is not None else _safe_read(Path(market_status_path))
    )
    pressure = focus_pressure_reasons(
        dispatch=dispatch_payload,
        market_status=status_payload,
    )
    if not dispatch_payload:
        pressure = list(pressure) + ["dispatch_unavailable"]
    quiet = in_quiet_window(clock)

    decision: LaneDecision
    if pressure:
        decision = "suspend"
        allowed = False
    elif require_quiet_window and not quiet and not allow_outside_quiet_for_pilot:
        decision = "quiet_only"
        allowed = False
    else:
        decision = "allow"
        allowed = True

    return {
        "schema_version": SCHEMA_VERSION,
        "evaluated_at": clock.isoformat(),
        "lane": ARCHIVE_LANE_BUDGET_ID,
        "preemptible": True,
        "max_concurrency": 1,
        "fourth_equal_sprint_stream": False,
        "budget_ids": {
            "lane": ARCHIVE_LANE_BUDGET_ID,
            "critical": CRITICAL_PATH_BUDGET_ID,
            "sources": {key: archive_budget_id(key) for key in ARCHIVE_SOURCE_KEYS},
        },
        "in_quiet_window": quiet,
        "require_quiet_window": require_quiet_window,
        "focus_pressure_reasons": pressure,
        "decision": decision,
        "allowed": allowed,
        "focus_market": str(
            (dispatch_payload or {}).get("focus_market")
            or (dispatch_payload or {}).get("market_id")
            or ""
        )
        or None,
        "focus_mode": str((dispatch_payload or {}).get("mode") or "") or None,
        "ingest_sprint_complete": bool((dispatch_payload or {}).get("ingest_sprint_complete")),
        "note": (
            "Gate only — no crawler. Separate budget IDs + preemptible + quiet window "
            "are required before any archive poll; focus pressure always suspends."
        ),
    }


__all__ = [
    "ARCHIVE_LANE_BUDGET_ID",
    "ARCHIVE_SOURCE_KEYS",
    "CRITICAL_PATH_BUDGET_ID",
    "DEFAULT_DISPATCH_PATH",
    "DEFAULT_MARKET_STATUS_PATH",
    "FOCUS_PRESSURE_FLAG_IDS",
    "SCHEMA_VERSION",
    "WEEKDAY_QUIET_END",
    "WEEKDAY_QUIET_START",
    "archive_budget_id",
    "archive_lane_gate",
    "budgets_share_quota",
    "critical_budget_id",
    "focus_pressure_reasons",
    "in_quiet_window",
]
