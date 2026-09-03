"""Slim per-market status grid for the dashboard Overview tab."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy
from value_investor.data_library import (
    DEFAULT_LIBRARY_ROOT,
    MARKET_REGISTRY,
    load_manifest,
)
from value_investor.library_ingest_dispatch import (
    DEFAULT_DISPATCH_PATH,
    MODE_MAINTENANCE,
    MODE_SPRINT,
    PARALLEL_SPRINT_POLICY_KEYS,
)
from value_investor.library_screen import screen_dir_for
from value_investor.storage import read_json

SCHEMA_VERSION = 1
LIVE_MARKET_ID = "ftse350"

ROLE_LIVE = "live"
ROLE_FOCUS = "focus"
ROLE_SPRINT = "sprint"
ROLE_QUEUE = "queue"
ROLE_GRADUATED = "graduated"
ROLE_OTHER = "other"

INGEST_LIVE = "live"
INGEST_SPRINT = MODE_SPRINT
INGEST_MAINTENANCE = MODE_MAINTENANCE
INGEST_QUEUED = "queued"
INGEST_IDLE = "idle"

PHASE_LABELS = {
    0: "Not started",
    1: "Observe",
    2: "Weekly paper",
    3: "Weekday paper",
    4: "Live screen",
}

ROLE_ORDER = {
    ROLE_LIVE: 0,
    ROLE_FOCUS: 1,
    ROLE_SPRINT: 2,
    ROLE_QUEUE: 3,
    ROLE_GRADUATED: 4,
    ROLE_OTHER: 5,
}


def _safe_read(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:  # noqa: BLE001 — dashboard must still assemble
        return None


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _signal_counts(raw: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(raw, dict):
        return counts
    for key, value in raw.items():
        counts[str(key)] = _int(value)
    return counts


def _index_library_status(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    rows = _as_list((_as_dict(payload)).get("markets"))
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        market_id = str(row.get("market") or "").strip()
        if market_id:
            indexed[market_id] = row
    return indexed


def _graduated_ids(policy: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for row in _as_list(policy.get("graduated_markets")):
        if isinstance(row, dict) and row.get("market"):
            out.add(str(row["market"]).strip())
        elif isinstance(row, str) and row.strip():
            out.add(row.strip())
    return out


def _queue_ids(policy: dict[str, Any]) -> list[str]:
    return [str(m).strip() for m in _as_list(policy.get("market_queue")) if str(m).strip()]


def _sprint_stream_map(policy: dict[str, Any], dispatch: dict[str, Any]) -> dict[str, int]:
    streams: dict[str, int] = {}
    for stream, key in PARALLEL_SPRINT_POLICY_KEYS.items():
        listed = [str(m).strip() for m in _as_list(policy.get(key)) if str(m).strip()]
        dispatch_key = "parallel_sprint_markets" if stream == 1 else f"parallel_sprint_{stream}_markets"
        listed.extend(str(m).strip() for m in _as_list(dispatch.get(dispatch_key)) if str(m).strip())
        for market_id in listed:
            streams.setdefault(market_id, stream)
    return streams


def _filing_health_index(dispatch: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    focus_id = str(dispatch.get("market_id") or "").strip()
    if focus_id:
        indexed[focus_id] = {
            "mode": dispatch.get("mode"),
            "reason": dispatch.get("reason"),
            "ingest_parity_met": bool(dispatch.get("ingest_parity_met")),
            "filing_gaps": _int(dispatch.get("filing_gaps")),
            "filing_health": _slim_filing_health(dispatch.get("filing_health")),
            "phase_blockers": [
                str(item) for item in _as_list(dispatch.get("phase_blockers")) if str(item)
            ],
        }
    for key in ("parallel_sprint_status", "parallel_sprint_2_status"):
        for row in _as_list(dispatch.get(key)):
            if not isinstance(row, dict):
                continue
            market_id = str(row.get("market_id") or "").strip()
            if not market_id:
                continue
            indexed[market_id] = {
                "mode": row.get("mode"),
                "reason": row.get("reason"),
                "ingest_parity_met": bool(row.get("ingest_parity_met")),
                "filing_gaps": _int(row.get("filing_gaps")),
                "filing_health": _slim_filing_health(row.get("filing_health")),
                "phase_blockers": [
                    str(item) for item in _as_list(row.get("phase_blockers")) if str(item)
                ],
            }
    return indexed


def _slim_filing_health(raw: Any) -> dict[str, Any] | None:
    health = _as_dict(raw)
    if not health:
        return None
    return {
        "buy_tier_count": _int(health.get("buy_tier_count")),
        "unmeasured_buy_tier": _int(health.get("unmeasured_buy_tier")),
        "zero_body_buy_tier": _int(health.get("zero_body_buy_tier")),
        "thin_body_buy_tier": _int(health.get("thin_body_buy_tier")),
        "indexed_without_body": _int(health.get("indexed_without_body")),
        "bodies_median": _float(health.get("bodies_median")),
        "coverage_scope": health.get("coverage_scope"),
        "ftse_equivalent": bool(health.get("ftse_equivalent")),
        "zero_body_tickers": [str(t) for t in _as_list(health.get("zero_body_tickers"))[:8]],
        "thin_body_tickers": [str(t) for t in _as_list(health.get("thin_body_tickers"))[:8]],
        "unmeasured_tickers": [str(t) for t in _as_list(health.get("unmeasured_tickers"))[:8]],
    }


def _slim_phase(raw: Any) -> dict[str, Any] | None:
    phase = _as_dict(raw)
    if not phase:
        return None
    current = _int(phase.get("current_phase"), default=0)
    return {
        "current_phase": current,
        "next_phase": _int(phase.get("next_phase"), default=current),
        "phase1_ready": bool(phase.get("phase1_ready")),
        "phase2_ready": bool(phase.get("phase2_ready")),
        "phase3_ready": bool(phase.get("phase3_ready")),
        "weekly_paper_enabled": bool(phase.get("weekly_paper_enabled")),
        "weekday_paper_enabled": bool(phase.get("weekday_paper_enabled")),
        "blockers": [str(item) for item in _as_list(phase.get("blockers")) if str(item)],
        "phase1": {
            "screen_archives": _int((_as_dict(phase.get("phase1"))).get("screen_archives")),
            "observe_snapshot_count": _int(
                (_as_dict(phase.get("phase1"))).get("observe_snapshot_count")
            ),
        },
        "phase2": {
            "weekly_batch_count": _int((_as_dict(phase.get("phase2"))).get("weekly_batch_count")),
            "min_weekly_batches": _int((_as_dict(phase.get("phase2"))).get("min_weekly_batches")),
        },
    }


def _coverage_from_manifest(library_root: Path, market_id: str) -> dict[str, Any]:
    """Fill coverage/freshness when library_status.json omitted this market."""
    try:
        manifest = load_manifest(library_root, market_id)
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(manifest, dict) or not manifest.get("ticker_count"):
        return {}
    return {
        "ticker_count": manifest.get("ticker_count") or 0,
        "coverage_pct": manifest.get("coverage_pct"),
        "last_constituents_refresh": manifest.get("last_constituents_refresh"),
        "last_metrics_refresh": manifest.get("last_metrics_refresh"),
    }


def _load_screen_summary(library_root: Path, market_id: str) -> dict[str, Any] | None:
    path = screen_dir_for(library_root, market_id) / "latest_summary.json"
    raw = _safe_read(path)
    return raw if isinstance(raw, dict) else None


def _classify_ingest(
    market_id: str,
    *,
    focus: str,
    graduated: set[str],
    queue: set[str],
    sprint_markets: set[str],
    maintenance_markets: set[str],
    sprint_streams: dict[str, int],
    dispatch_mode: str | None,
) -> tuple[str, int | None]:
    if market_id == LIVE_MARKET_ID:
        return INGEST_LIVE, None
    if market_id in sprint_markets or market_id in sprint_streams:
        stream = sprint_streams.get(market_id)
        if market_id == focus:
            stream = None
        return INGEST_SPRINT, stream
    if market_id in maintenance_markets:
        return INGEST_MAINTENANCE, None
    if market_id == focus:
        mode = str(dispatch_mode or INGEST_SPRINT).strip().lower()
        if mode == INGEST_MAINTENANCE:
            return INGEST_MAINTENANCE, None
        return INGEST_SPRINT, None
    if market_id in graduated:
        return INGEST_MAINTENANCE, None
    if market_id in queue:
        return INGEST_QUEUED, None
    return INGEST_IDLE, None


def _classify_role(
    market_id: str,
    *,
    focus: str,
    graduated: set[str],
    queue: set[str],
    ingest: str,
) -> str:
    if market_id == LIVE_MARKET_ID:
        return ROLE_LIVE
    if market_id == focus:
        return ROLE_FOCUS
    if ingest == INGEST_SPRINT:
        return ROLE_SPRINT
    if market_id in queue:
        return ROLE_QUEUE
    if market_id in graduated:
        return ROLE_GRADUATED
    return ROLE_OTHER


def _health_tone(
    *,
    ingest: str,
    coverage_pct: float | None,
    stale: int,
    filing_gaps: int,
    blockers: list[str],
    live_ingest_stalled: bool,
) -> str:
    if ingest == INGEST_LIVE and live_ingest_stalled:
        return "fail"
    if ingest == INGEST_SPRINT and filing_gaps > 0:
        return "warn"
    if coverage_pct is not None and coverage_pct < 0.5:
        return "fail"
    if coverage_pct is not None and coverage_pct < 0.9:
        return "warn"
    if stale > 0 or blockers:
        return "warn"
    if ingest in {INGEST_QUEUED, INGEST_IDLE}:
        return "info"
    return "ok"


def _phase_label(current_phase: int | None, *, is_live: bool) -> str:
    if is_live:
        return PHASE_LABELS[4]
    if current_phase is None:
        return PHASE_LABELS[0]
    return PHASE_LABELS.get(current_phase, f"Phase {current_phase}")


def build_market_status(
    *,
    library_root: Path | None = None,
    policy_path: Path | None = None,
    dispatch_path: Path | None = None,
    live_meta: dict[str, Any] | None = None,
    live_signal_counts: dict[str, int] | None = None,
    live_run_at: str | None = None,
    live_ingest_stalled: bool = False,
) -> dict[str, Any]:
    """Assemble a slim per-market status grid from cached library artifacts."""
    library_root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    policy_path = Path(policy_path or DEFAULT_POLICY_PATH)
    dispatch_path = Path(dispatch_path or DEFAULT_DISPATCH_PATH)

    try:
        policy = load_policy(policy_path)
    except Exception:  # noqa: BLE001
        policy = {}
    if not isinstance(policy, dict):
        policy = {}

    library_status = _as_dict(_safe_read(library_root / "library_status.json"))
    shard_phases = _as_dict(_safe_read(library_root / "shard_phases.json"))
    dispatch = _as_dict(_safe_read(dispatch_path))
    status_by_market = _index_library_status(library_status)
    phases_by_market = {
        str(key): value
        for key, value in _as_dict(shard_phases.get("markets")).items()
        if isinstance(value, dict)
    }
    health_by_market = _filing_health_index(dispatch)

    focus = str(policy.get("focus_market") or "").strip()
    graduated = _graduated_ids(policy)
    queue = _queue_ids(policy)
    queue_set = set(queue)
    sprint_streams = _sprint_stream_map(policy, dispatch)
    sprint_markets = {
        str(m).strip() for m in _as_list(dispatch.get("sprint_markets")) if str(m).strip()
    }
    sprint_markets.update(sprint_streams)
    if focus and str(dispatch.get("mode") or "").strip().lower() == INGEST_SPRINT:
        sprint_markets.add(focus)
    maintenance_markets = {
        str(m).strip() for m in _as_list(dispatch.get("maintenance_markets")) if str(m).strip()
    }
    live_meta = live_meta or {}
    live_counts = _signal_counts(live_signal_counts or live_meta.get("signal_counts"))

    markets: list[dict[str, Any]] = []
    for market_id, spec in MARKET_REGISTRY.items():
        status = status_by_market.get(market_id) or {}
        if not status and market_id != LIVE_MARKET_ID:
            status = _coverage_from_manifest(library_root, market_id)
        screen = None if market_id == LIVE_MARKET_ID else _load_screen_summary(library_root, market_id)
        dispatch_row = health_by_market.get(market_id) or {}
        phase_row = _slim_phase(phases_by_market.get(market_id))
        ingest, stream = _classify_ingest(
            market_id,
            focus=focus,
            graduated=graduated,
            queue=queue_set,
            sprint_markets=sprint_markets,
            maintenance_markets=maintenance_markets,
            sprint_streams=sprint_streams,
            dispatch_mode=str(dispatch.get("mode") or "") if market_id == focus else None,
        )
        role = _classify_role(
            market_id,
            focus=focus,
            graduated=graduated,
            queue=queue_set,
            ingest=ingest,
        )
        if market_id == LIVE_MARKET_ID:
            signal_counts = live_counts
            ticker_count = _int(live_meta.get("company_count") or status.get("ticker_count"))
            shortlist_count = _int(signal_counts.get("strong_buy")) + _int(signal_counts.get("buy"))
            last_screen_at = live_run_at
            coverage_pct = 1.0 if ticker_count else _float(status.get("coverage_pct"))
            current_phase = 4
            blockers: list[str] = []
        else:
            signal_counts = _signal_counts((screen or {}).get("signal_counts"))
            ticker_count = _int((screen or {}).get("ticker_count") or status.get("ticker_count"))
            shortlist_count = _int((screen or {}).get("shortlist_count"))
            last_screen_at = (screen or {}).get("run_at")
            coverage_pct = _float(status.get("coverage_pct"))
            current_phase = phase_row.get("current_phase") if phase_row else None
            blockers = list(dispatch_row.get("phase_blockers") or [])
            if phase_row and phase_row.get("blockers") and not blockers:
                blockers = list(phase_row["blockers"])

        stale = _int(status.get("stale"))
        filing_gaps = _int(dispatch_row.get("filing_gaps"))
        health = _health_tone(
            ingest=ingest,
            coverage_pct=coverage_pct,
            stale=stale,
            filing_gaps=filing_gaps,
            blockers=blockers,
            live_ingest_stalled=live_ingest_stalled and market_id == LIVE_MARKET_ID,
        )
        markets.append(
            {
                "market_id": market_id,
                "label": spec.label,
                "exchange": spec.exchange,
                "currency": spec.currency,
                "role": role,
                "is_live": market_id == LIVE_MARKET_ID,
                "is_focus": market_id == focus,
                "is_graduated": market_id in graduated,
                "is_queue": market_id in queue_set,
                "ingest": ingest,
                "ingest_stream": stream,
                "ingest_reason": dispatch_row.get("reason"),
                "ingest_parity_met": dispatch_row.get("ingest_parity_met"),
                "health": health,
                "coverage_pct": coverage_pct,
                "honest_coverage_pct": _float(status.get("honest_coverage_pct")),
                "ticker_count": ticker_count,
                "stale": stale,
                "fresh": _int(status.get("fresh")),
                "failed_fetch_count": _int(status.get("failed_fetch_count")),
                "last_metrics_refresh": status.get("last_metrics_refresh"),
                "last_constituents_refresh": status.get("last_constituents_refresh"),
                "last_screen_at": last_screen_at,
                "signal_counts": signal_counts,
                "shortlist_count": shortlist_count,
                "strong_buy": _int(
                    (screen or {}).get("strong_buy")
                    if screen
                    else signal_counts.get("strong_buy")
                ),
                "buy": _int((screen or {}).get("buy") if screen else signal_counts.get("buy")),
                "learning_phase": current_phase,
                "learning_phase_label": _phase_label(
                    current_phase, is_live=market_id == LIVE_MARKET_ID
                ),
                "phase_blockers": blockers,
                "learning": phase_row,
                "filing_health": dispatch_row.get("filing_health"),
                "filing_gaps": filing_gaps if dispatch_row else None,
            }
        )

    markets.sort(
        key=lambda row: (
            ROLE_ORDER.get(str(row.get("role")), 9),
            _int(row.get("ingest_stream"), default=9),
            str(row.get("label") or ""),
        )
    )

    ingest_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    for row in markets:
        ingest_key = str(row.get("ingest") or INGEST_IDLE)
        role_key = str(row.get("role") or ROLE_OTHER)
        ingest_counts[ingest_key] = ingest_counts.get(ingest_key, 0) + 1
        role_counts[role_key] = role_counts.get(role_key, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "note": (
            "Per-market stage and health snapshot for the dashboard grid. "
            "Ingest mode uses cached dispatch + policy lists; signal mix comes from "
            "the live FTSE screen or each library latest_summary.json."
        ),
        "focus_market": focus or None,
        "summary": {
            "market_count": len(markets),
            "ingest_counts": ingest_counts,
            "role_counts": role_counts,
            "sprint_count": ingest_counts.get(INGEST_SPRINT, 0),
            "maintenance_count": ingest_counts.get(INGEST_MAINTENANCE, 0),
            "live_count": ingest_counts.get(INGEST_LIVE, 0),
        },
        "markets": markets,
    }


__all__ = [
    "INGEST_IDLE",
    "INGEST_LIVE",
    "INGEST_MAINTENANCE",
    "INGEST_QUEUED",
    "INGEST_SPRINT",
    "LIVE_MARKET_ID",
    "ROLE_FOCUS",
    "ROLE_GRADUATED",
    "ROLE_LIVE",
    "ROLE_OTHER",
    "ROLE_QUEUE",
    "ROLE_SPRINT",
    "SCHEMA_VERSION",
    "build_market_status",
]
