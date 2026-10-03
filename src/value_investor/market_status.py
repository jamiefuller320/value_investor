"""Slim per-market status grid for the dashboard Overview tab."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy
from value_investor.data_library import (
    DEFAULT_LIBRARY_ROOT,
    MARKET_REGISTRY,
    load_manifest,
)
from value_investor.held_vs_market import (
    assemble_held_vs_market,
    bench_closes_for_market,
    contribution_deltas_from_marks,
    empty_held_vs_market,
    load_macro_index_closes,
    market_values_with_contributions,
    marks_from_fund,
    merge_branch_series,
)
from value_investor.library_equal_support import PACKAGE_FILENAME as EQUAL_SUPPORT_FILENAME
from value_investor.library_ingest_dispatch import (
    DEFAULT_DISPATCH_PATH,
    MODE_MAINTENANCE,
    MODE_SPRINT,
    PARALLEL_SPRINT_POLICY_KEYS,
    sprint_ingest_complete,
)
from value_investor.library_ingest_escalation import (
    ftse_equivalent_markets,
    resolve_library_ingest_health_log_path,
)
from value_investor.library_learning_depth import (
    TRAJECTORY_READY_MIN_SPAN_WEEKS,
    TRAJECTORY_READY_MIN_UNIQUE_DAYS,
    learning_depth_path,
)
from value_investor.library_near_miss_watch import NEAR_MISS_FILENAME
from value_investor.library_screen import screen_dir_for
from value_investor.library_sim import ingest_profile_observe_sim_markets
from value_investor.macro_context import DEFAULT_MACRO_ROOT
from value_investor.market_shard_admission import admitted_learning_markets_for_policy
from value_investor.market_shard_phases import (
    DEFAULT_SHARD_ROOT,
    evaluate_market_phase,
    shard_root_for_market,
)
from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 3
LIVE_MARKET_ID = "ftse350"
DEFAULT_MARKET_STATUS_PATH = Path("docs/data/market_status.json")
DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
DEFAULT_CHARTS_DIR = Path("docs/data/charts")
BUY_TIER_LEVEL_TRACK = "buy_tier_level"
BUY_TIER_LEVEL_DCA_TRACK = "buy_tier_level_dca"
BUY_TIER_LEVEL_NATIVE_TRACK = "buy_tier_level_native"
BUY_TIER_LEVEL_DCA_MARKET_BRANCH = "buy_tier_level_dca_market"
GBP_FX_WARPED_BRANCH = "buy_tier_level_gbp_fx_warped"
EXPECTED_ADMITTED_BLOCKER_NEEDLE = "weekly_paper_shard_markets"
SPRINT_PROGRESS_WINDOW_DAYS = 2
STALE_SCREEN_AFTER_DAYS = 8

ROLE_LIVE = "live"
ROLE_FOCUS = "focus"
ROLE_SPRINT = "sprint"
ROLE_ADMITTED = "admitted"
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
EPOCH0_PHASE_LABEL = "Epoch-0 level"
INGEST_ONLY_PHASE_LABEL = "Ingest only"

GATE_START = "start"
GATE_BODIES = "bodies"
GATE_SPRINT = "sprint_complete"
GATE_ADMIT = "admit"
GATE_EPOCH0 = "epoch0"
GATE_FTSE_PARITY = "ftse_parity_learning"
GATE_LIVE_READY = "live_ready"
GATE_STEP_IDS = (
    GATE_START,
    GATE_BODIES,
    GATE_SPRINT,
    GATE_ADMIT,
    GATE_EPOCH0,
    GATE_FTSE_PARITY,
    GATE_LIVE_READY,
)
GATE_STEP_LABELS = {
    GATE_START: "Start",
    GATE_BODIES: "Bodies",
    GATE_SPRINT: "Sprint",
    GATE_ADMIT: "Admit",
    GATE_EPOCH0: "Epoch-0",
    GATE_FTSE_PARITY: "Parity",
    GATE_LIVE_READY: "Live",
}
GATE_STEP_GATES = {
    GATE_START: "ingest_clock",
    GATE_BODIES: "unmeasured_zero_clear",
    GATE_SPRINT: "sprint_ingest_complete",
    GATE_ADMIT: "l322_admit",
    GATE_EPOCH0: "epoch0_marks",
    GATE_FTSE_PARITY: "learning_ready",
    GATE_LIVE_READY: "phase_4_live_screen",
}

ROLE_ORDER = {
    ROLE_LIVE: 0,
    ROLE_FOCUS: 1,
    ROLE_SPRINT: 2,
    ROLE_ADMITTED: 3,
    ROLE_QUEUE: 4,
    ROLE_GRADUATED: 5,
    ROLE_OTHER: 6,
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


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
        dispatch_key = (
            "parallel_sprint_markets" if stream == 1 else f"parallel_sprint_{stream}_markets"
        )
        listed.extend(
            str(m).strip() for m in _as_list(dispatch.get(dispatch_key)) if str(m).strip()
        )
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
            "ingest_exhausted": bool(dispatch.get("ingest_exhausted")),
            "filing_gaps": _int(dispatch.get("filing_gaps")),
            "filing_health": _slim_filing_health(dispatch.get("filing_health")),
            "phase_blockers": [
                str(item) for item in _as_list(dispatch.get("phase_blockers")) if str(item)
            ],
            "current_phase": _optional_int(dispatch.get("current_phase")),
            "next_phase": _optional_int(dispatch.get("next_phase")),
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
                "ingest_exhausted": bool(row.get("ingest_exhausted")),
                "filing_gaps": _int(row.get("filing_gaps")),
                "filing_health": _slim_filing_health(row.get("filing_health")),
                "phase_blockers": [
                    str(item) for item in _as_list(row.get("phase_blockers")) if str(item)
                ],
                "current_phase": _optional_int(row.get("current_phase")),
                "next_phase": _optional_int(row.get("next_phase")),
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
        "ingest_exhausted": bool(health.get("ingest_exhausted")),
        "parked_count": _int(health.get("parked_count")),
        "zero_body_tickers": [str(t) for t in _as_list(health.get("zero_body_tickers"))[:8]],
        "thin_body_tickers": [str(t) for t in _as_list(health.get("thin_body_tickers"))[:8]],
        "unmeasured_tickers": [str(t) for t in _as_list(health.get("unmeasured_tickers"))[:8]],
        "parked_tickers": [str(t) for t in _as_list(health.get("parked_tickers"))[:8]],
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
    admitted: set[str],
    ingest: str,
) -> str:
    if market_id == LIVE_MARKET_ID:
        return ROLE_LIVE
    if market_id == focus:
        return ROLE_FOCUS
    if ingest == INGEST_SPRINT:
        return ROLE_SPRINT
    if market_id in admitted:
        return ROLE_ADMITTED
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


def _phase_label(
    current_phase: int | None,
    *,
    is_live: bool,
    epoch0: dict[str, Any] | None = None,
    ingest: str | None = None,
) -> str:
    if is_live:
        return PHASE_LABELS[4]
    if epoch0 and epoch0.get("present") and (current_phase or 0) <= 1:
        return EPOCH0_PHASE_LABEL
    if current_phase in (None, 0) and ingest == INGEST_SPRINT:
        return INGEST_ONLY_PHASE_LABEL
    if current_phase is None:
        return PHASE_LABELS[0]
    return PHASE_LABELS.get(current_phase, f"Phase {current_phase}")


def _slim_learning_depth(library_root: Path, market_id: str) -> dict[str, Any] | None:
    """Cached learning-depth snapshot only — do not re-assess filings here."""
    raw = _as_dict(_safe_read(learning_depth_path(library_root, market_id)))
    if not raw:
        return None
    screen = _as_dict(raw.get("screen"))
    return {
        "filing_ready": bool(raw.get("filing_ready")),
        "trajectory_ready": bool(raw.get("trajectory_ready")),
        "learning_ready": bool(raw.get("learning_ready")),
        "span_weeks": _float(screen.get("span_weeks")),
        "unique_days": _optional_int(screen.get("unique_days")),
        "assessed_at": raw.get("assessed_at"),
    }


def _weeks_to_parity(span_weeks: float | None, unique_days: int | None) -> tuple[float, int]:
    weeks_left = max(0.0, round(TRAJECTORY_READY_MIN_SPAN_WEEKS - float(span_weeks or 0.0), 2))
    days_left = max(0, TRAJECTORY_READY_MIN_UNIQUE_DAYS - int(unique_days or 0))
    return weeks_left, days_left


def _gap_bits(remain: dict[str, Any]) -> str:
    return ", ".join(
        [
            f"unmeas {remain.get('unmeasured', 0)}",
            f"zero {remain.get('zero_body', 0)}",
            f"thin {remain.get('thin', 0)}",
            f"IWB {remain.get('indexed_without_body', 0)}",
        ]
    )


def build_learning_gate_indicator(
    *,
    is_live: bool,
    is_admitted: bool = False,
    ingest: str | None = None,
    ingest_parity_met: bool | None = None,
    ingest_exhausted: bool = False,
    sprint_progress: dict[str, Any] | None = None,
    learning_depth: dict[str, Any] | None = None,
    filing_health: dict[str, Any] | None = None,
    remaining_gaps: dict[str, Any] | None = None,
    epoch0: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Observe-only Start → … → live-ready stepper from published shard gates.

    Intermediate nodes are existing fields only (bodies / leftover-park /
    sprint_ingest_complete / L322 admit / epoch-0 marks / 12w clock). Live FTSE
    reports live-path status, not a self catch-up. No NAV blend or knobs.
    """
    depth = _as_dict(learning_depth)
    sprint = _as_dict(sprint_progress)
    epoch = _as_dict(epoch0)
    remain_src: dict[str, Any] | None = None
    if isinstance(remaining_gaps, dict) and remaining_gaps:
        remain_src = remaining_gaps
    elif isinstance(sprint.get("remaining"), dict) and sprint.get("remaining"):
        remain_src = sprint.get("remaining")
    elif filing_health:
        remain_src = _gap_counts(filing_health)
    remain = _as_dict(remain_src)
    ingest_key = str(ingest or "").strip().lower()
    has_gap_snapshot = remain_src is not None

    filing_ready = bool(depth.get("filing_ready")) if depth else False
    if not depth:
        filing_ready = bool(
            is_admitted or ingest_parity_met or ingest_exhausted or sprint.get("admission_ready")
        )

    start_complete = bool(
        is_live
        or is_admitted
        or ingest_key in {INGEST_LIVE, INGEST_SPRINT, INGEST_MAINTENANCE, INGEST_QUEUED}
        or has_gap_snapshot
        or filing_ready
    )
    unmeasured = _int(remain.get("unmeasured"))
    zero_body = _int(remain.get("zero_body"))
    leftover = _int(remain.get("thin")) + _int(remain.get("indexed_without_body"))
    sprint_complete = bool(
        is_live
        or is_admitted
        or ingest_parity_met
        or ingest_exhausted
        or sprint.get("admission_ready")
        or filing_ready
    )
    bodies_complete = bool(
        is_live or sprint_complete or (has_gap_snapshot and unmeasured == 0 and zero_body == 0)
    )
    admit_complete = bool(is_live or is_admitted)
    epoch0_complete = bool(is_live or epoch.get("present"))
    span_weeks = _float(depth.get("span_weeks"))
    unique_days = _optional_int(depth.get("unique_days"))
    trajectory_ready = bool(depth.get("trajectory_ready")) if depth else False
    if not depth and span_weeks is not None and unique_days is not None:
        trajectory_ready = (
            span_weeks >= TRAJECTORY_READY_MIN_SPAN_WEEKS
            and unique_days >= TRAJECTORY_READY_MIN_UNIQUE_DAYS
        )
    if depth.get("learning_ready") is not None:
        learning_ready = bool(depth.get("learning_ready"))
    else:
        learning_ready = bool(filing_ready and trajectory_ready)
    if is_live:
        start_complete = bodies_complete = sprint_complete = True
        admit_complete = epoch0_complete = learning_ready = True
        filing_ready = True
        trajectory_ready = True
    if sprint_complete:
        bodies_complete = True
    if admit_complete:
        sprint_complete = bodies_complete = start_complete = True
    live_complete = bool(is_live)

    complete = {
        GATE_START: start_complete,
        GATE_BODIES: bodies_complete,
        GATE_SPRINT: sprint_complete,
        GATE_ADMIT: admit_complete,
        GATE_EPOCH0: epoch0_complete,
        GATE_FTSE_PARITY: learning_ready,
        GATE_LIVE_READY: live_complete,
    }
    current_id = GATE_LIVE_READY
    for step_id in GATE_STEP_IDS:
        if not complete[step_id]:
            current_id = step_id
            break

    def _status(step_id: str) -> str:
        if complete[step_id]:
            return "done"
        if step_id == current_id:
            return "current"
        return "pending"

    steps = [
        {
            "id": step_id,
            "label": GATE_STEP_LABELS[step_id],
            "gate": GATE_STEP_GATES[step_id],
            "status": _status(step_id),
        }
        for step_id in GATE_STEP_IDS
    ]

    leftover_via = (
        "raw ingest_parity_met"
        if ingest_parity_met
        else "leftover thin/IWB parked (ingest_exhausted)"
        if ingest_exhausted
        else "leftover thin/IWB parked or raw ingest_parity_met"
    )
    weeks_left, days_left = _weeks_to_parity(span_weeks, unique_days)
    span_txt = (
        f"{span_weeks:g}w / {unique_days} unique days"
        if span_weeks is not None and unique_days is not None
        else "span not yet published in learning_depth.json"
    )
    epoch_marks = _int(epoch.get("epoch0_batch_count") or epoch.get("weekday_batch_count"))
    epoch_holdings = epoch.get("holdings")

    if is_live:
        next_gate = {
            "id": "live_path",
            "name": "Live-path utilization (P1)",
            "gate": "live_ftse350",
            "criteria": (
                "FTSE 350 is already the live screen. Next work is weekday "
                "paper-auto evidence (filings, FCF, overlay, memo recency on "
                "holdings and buy-tier), not catching this tile up to itself. "
                "Stage 4 live expansion waits on persistent AI-track excess vs "
                "^FTSE plus one shard completing Phase 3."
            ),
            "timeframe": (
                "Not calendar — project stage 4 after Phase 3 evidence. "
                "Live screener stays FTSE 350 until then."
            ),
        }
    elif current_id == GATE_START:
        next_gate = {
            "id": GATE_START,
            "name": "Ingest clock",
            "gate": "ingest_clock",
            "criteria": (
                "Start: Layer A / market_queue / sprint or maintenance ingest so "
                "a buy-tier screen and filing snapshot exist."
            ),
            "timeframe": "Next grow/screen-lite or sprint seating — not a 12-week wait.",
        }
    elif current_id == GATE_BODIES:
        next_gate = {
            "id": GATE_BODIES,
            "name": "Unmeasured / zero-body clear",
            "gate": "unmeasured_zero_clear",
            "criteria": (
                "Bootstrap filing bar: unmeasured=0 and zero-body=0 (cannot park). "
                f"Remaining {_gap_bits(remain)}."
            ),
            "timeframe": (
                "Sprint deepen until those two counts hit zero. Leftover thin/IWB "
                "park cannot fire while unmeasured or zero-body remain."
            ),
        }
    elif current_id == GATE_SPRINT:
        next_gate = {
            "id": GATE_SPRINT,
            "name": "sprint_ingest_complete",
            "gate": "sprint_ingest_complete",
            "criteria": (
                "sprint_ingest_complete / filing_ready: raw ingest_parity_met "
                f"(all four gap counts zero) or leftover thin/IWB parked. Now via "
                f"{leftover_via}. Remaining {_gap_bits(remain)}."
            ),
            "timeframe": (
                "Sprint until exhaustion or raw parity. Extra jobs do not create "
                "unique weeks. Fat slot serializes one head at a time."
            ),
        }
    elif current_id == GATE_ADMIT:
        next_gate = {
            "id": GATE_ADMIT,
            "name": "L322 admit",
            "gate": "l322_admit",
            "criteria": (
                "admit_market_to_learning (L322) after sprint_ingest_complete: "
                "equal-support package, not weekly AI paper and not knob apply."
            ),
            "timeframe": (
                "Policy flip on threshold — not calendar. Epoch-0 weekday crons "
                "register on first admit."
            ),
        }
    elif current_id == GATE_EPOCH0:
        held = f"{epoch_holdings} holdings" if epoch_holdings is not None else "no book yet"
        next_gate = {
            "id": GATE_EPOCH0,
            "name": "Epoch-0 marks",
            "gate": "epoch0_marks",
            "criteria": (
                "Frozen buy_tier_level epoch-0 book with weekday local-open marks "
                f"({held}; {epoch_marks} epoch-0/weekday batches). Needs one current "
                "screen, prices, and a paper runner — not learning_ready."
            ),
            "timeframe": (
                "Starts the same week as admit (Sunday stamp + weekday session). "
                "Do not wait 12 archives to open the book."
            ),
        }
    elif current_id == GATE_FTSE_PARITY:
        next_gate = {
            "id": GATE_FTSE_PARITY,
            "name": "FTSE-parity learning",
            "gate": "learning_ready",
            "criteria": (
                "learning_ready = filing_ready and ≥12 weeks / 12 unique screen "
                f"days (canonical filings). Now {span_txt}."
            ),
            "timeframe": (
                f"Sunday archive clock: ~{weeks_left:g}w and {days_left} unique "
                "day(s) remaining. Extra deepen jobs do not shorten the calendar."
            ),
        }
    else:
        next_gate = {
            "id": GATE_LIVE_READY,
            "name": "Live screen inclusion",
            "gate": "phase_4_live_screen",
            "criteria": (
                "Phase 2 (≥8 weekly paper batches + beat control) then Phase 3 "
                "weekday pilot (8–12 weeks, capacity 1) then project stage 4: "
                "persistent FTSE AI-track excess vs ^FTSE and one shard through "
                "Phase 3. Do not fork shard AI or apply knobs yet."
            ),
            "timeframe": (
                "~2 months Phase 2 + 8–12 weeks Phase 3, then stage 4 is not "
                "calendar-driven. Live screen stays FTSE 350."
            ),
        }

    annotation = (
        f"Next: {next_gate['name']} — {next_gate['criteria']} Timeframe: {next_gate['timeframe']}"
    )
    return {
        "schema_version": 2,
        "observe_only": True,
        "current_id": current_id,
        "start_complete": start_complete,
        "bodies_complete": bodies_complete,
        "sprint_complete": sprint_complete,
        "admit_complete": admit_complete,
        "epoch0_complete": epoch0_complete,
        "trajectory_ready": trajectory_ready,
        "learning_ready": learning_ready,
        "live_ready": live_complete,
        "filing_ready": filing_ready if not is_live else True,
        "span_weeks": span_weeks,
        "unique_days": unique_days,
        "leftover": leftover,
        "steps": steps,
        "next_gate": next_gate,
        "annotation": annotation,
    }


def _phase_from_dispatch(dispatch_row: dict[str, Any]) -> dict[str, Any] | None:
    if dispatch_row.get("current_phase") is None:
        return None
    return _slim_phase(
        {
            "current_phase": dispatch_row.get("current_phase"),
            "next_phase": dispatch_row.get("next_phase"),
            "blockers": dispatch_row.get("phase_blockers") or [],
        }
    )


def _should_live_evaluate_phase(
    market_id: str,
    *,
    ingest: str,
    profile_markets: set[str],
    admitted: set[str],
) -> bool:
    if ingest == INGEST_SPRINT:
        return True
    if market_id in profile_markets:
        return True
    return market_id in admitted


def _resolve_learning_phase(
    market_id: str,
    *,
    cached: dict[str, Any] | None,
    dispatch_row: dict[str, Any],
    ingest: str,
    profile_markets: set[str],
    admitted: set[str],
    library_root: Path,
    shard_base: Path,
    policy: dict[str, Any],
) -> dict[str, Any] | None:
    """Prefer committed rollup, then live dispatch, then evaluate sprint/profile books."""
    if cached:
        return cached
    from_dispatch = _phase_from_dispatch(dispatch_row)
    if from_dispatch:
        return from_dispatch
    if not _should_live_evaluate_phase(
        market_id,
        ingest=ingest,
        profile_markets=profile_markets,
        admitted=admitted,
    ):
        return None
    try:
        evaluation = evaluate_market_phase(
            market_id,
            library_root=library_root,
            shard_root=shard_root_for_market(market_id, base=shard_base),
            policy=policy,
        )
    except Exception:  # noqa: BLE001 — dashboard must still assemble
        return None
    return _slim_phase(evaluation)


def _is_expected_admitted_blocker(text: str) -> bool:
    return EXPECTED_ADMITTED_BLOCKER_NEEDLE in str(text or "").lower()


def _is_no_benchmark_blocker(text: str) -> bool:
    return "no benchmark configured" in str(text or "").lower()


def _coalesce_phase_blockers(
    *,
    dispatch_blockers: list[str],
    phase_row: dict[str, Any] | None,
    current_phase: int | None,
) -> list[str]:
    """Prefer live phase blockers when dispatch still says the clock has no benchmark."""
    live = [str(item) for item in _as_list((phase_row or {}).get("blockers")) if str(item)]
    stale_benchmark = any(_is_no_benchmark_blocker(item) for item in dispatch_blockers)
    if current_phase and current_phase >= 1 and stale_benchmark:
        return live or [item for item in dispatch_blockers if not _is_no_benchmark_blocker(item)]
    if dispatch_blockers:
        return dispatch_blockers
    return live


def _health_blockers(blockers: list[str], *, is_admitted: bool) -> list[str]:
    if not is_admitted:
        return blockers
    return [item for item in blockers if not _is_expected_admitted_blocker(item)]


def _queue_rank(market_id: str, queue: list[str]) -> int | None:
    try:
        return queue.index(market_id) + 1
    except ValueError:
        return None


def _parse_iso_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _gap_counts(health: Any) -> dict[str, int]:
    row = _as_dict(health)
    unmeasured = _int(row.get("unmeasured_buy_tier"))
    zero_body = _int(row.get("zero_body_buy_tier"))
    return {
        "unmeasured": unmeasured,
        "zero_body": zero_body,
        "thin": _int(row.get("thin_body_buy_tier")),
        "indexed_without_body": _int(row.get("indexed_without_body")),
        "filing_gaps": unmeasured + zero_body,
    }


def _gap_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {key: _int(after.get(key)) - _int(before.get(key)) for key in after}


def _admission_warning(
    warning_id: str,
    summary: str,
    *,
    severity: str = "warn",
) -> dict[str, str]:
    return {"id": warning_id, "severity": severity, "summary": summary}


def _parallel_sprint_entered_at(policy: dict[str, Any], market_id: str) -> datetime | None:
    """Latest parallel-sprint graduation / reseed timestamp that seated ``market_id``."""
    history = _as_list(_as_dict(policy.get("parallel_sprint_graduation")).get("history"))
    latest: datetime | None = None
    for row in history:
        payload = _as_dict(row)
        if str(payload.get("to_market") or "").strip() != market_id:
            continue
        at = _parse_iso_dt(payload.get("at"))
        if at is None:
            continue
        if latest is None or at > latest:
            latest = at
    return latest


def _load_ingest_health_entries(library_root: Path, market_id: str) -> list[dict[str, Any]]:
    path = resolve_library_ingest_health_log_path(library_root, market_id)
    payload = _as_dict(_safe_read(path))
    return [row for row in _as_list(payload.get("entries")) if isinstance(row, dict)]


def _sprint_progress(
    market_id: str,
    *,
    library_root: Path,
    ingest: str,
    last_screen_at: str | None,
    filing_health: dict[str, Any] | None,
    ingest_parity: bool | None,
    ingest_exhausted: bool,
    now: datetime,
    sprint_entered_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Two-day ingest rollup and admission-progress flags for sprint tiles."""
    if ingest != INGEST_SPRINT:
        return None
    as_of = now if now.tzinfo else now.replace(tzinfo=UTC)
    window_start = as_of - timedelta(days=SPRINT_PROGRESS_WINDOW_DAYS)
    window: list[dict[str, Any]] = []
    for row in _load_ingest_health_entries(library_root, market_id):
        run_at = _parse_iso_dt(row.get("run_at"))
        if run_at is not None and run_at >= window_start:
            window.append(row)

    targets = sum(_int(row.get("targets")) for row in window)
    improved = sum(_int(row.get("improved")) for row in window)
    improved_tickers: list[str] = []
    seen: set[str] = set()
    for row in window:
        for ticker in _as_list(row.get("improved_tickers")):
            name = str(ticker or "").strip()
            if name and name not in seen:
                seen.add(name)
                improved_tickers.append(name)
    cutoff_runs = sum(1 for row in window if row.get("runtime_cutoff") or row.get("partial"))
    error_runs = sum(1 for row in window if _as_list(row.get("errors")))
    first = window[0] if window else None
    last = window[-1] if window else None
    remaining = _gap_counts(filing_health or (last.get("health_after") if last else None))
    gaps_before = _gap_counts(first.get("health_before") if first else remaining)
    gaps_after = _gap_counts((last.get("health_after") if last else None) or remaining)
    delta = _gap_delta(gaps_before, gaps_after)
    gate_health = dict(_as_dict(filing_health))
    if ingest_exhausted:
        gate_health["ingest_exhausted"] = True
    ready = bool(ingest_parity) or sprint_ingest_complete(gate_health)

    entered_in_window = sprint_entered_at is not None and sprint_entered_at >= window_start

    warnings: list[dict[str, str]] = []
    if not window:
        if entered_in_window:
            entered_day = sprint_entered_at.date().isoformat() if sprint_entered_at else "?"
            warnings.append(
                _admission_warning(
                    "awaiting_first_ingest",
                    f"Entered sprint on {entered_day}; waiting on the first deepen slot",
                )
            )
        else:
            warnings.append(
                _admission_warning(
                    "no_ingest_in_window",
                    f"No ingest runs in the last {SPRINT_PROGRESS_WINDOW_DAYS} days",
                    severity="high",
                )
            )
    if cutoff_runs:
        warnings.append(
            _admission_warning(
                "runtime_cutoff",
                f"{cutoff_runs} ingest run(s) hit the runtime cutoff",
                severity="high",
            )
        )
    if error_runs:
        samples = [
            str(item).strip()
            for row in window
            for item in _as_list(row.get("errors"))
            if str(item).strip()
        ]
        detail = f": {samples[0][:120]}" if samples else ""
        warnings.append(
            _admission_warning(
                "ingest_errors",
                f"{error_runs} ingest run(s) recorded errors{detail}",
            )
        )
    if (
        window
        and improved == 0
        and (
            remaining["filing_gaps"] > 0
            or remaining["thin"] > 0
            or remaining["indexed_without_body"] > 0
        )
    ):
        warnings.append(
            _admission_warning(
                "zero_improve_stall",
                "Last 2 days improved nobody while filing gaps remain",
                severity="high",
            )
        )
    if window and remaining["unmeasured"] > 0 and delta.get("unmeasured", 0) >= 0:
        warnings.append(
            _admission_warning(
                "unmeasured_stuck",
                f"{remaining['unmeasured']} unmeasured buy-tier name(s) unchanged "
                "(cannot park; blocks sprint_ingest_complete)",
                severity="high",
            )
        )
    if window and remaining["zero_body"] > 0 and delta.get("zero_body", 0) >= 0:
        warnings.append(
            _admission_warning(
                "zero_body_stuck",
                f"{remaining['zero_body']} zero-body buy-tier name(s) unchanged "
                "(cannot park; blocks sprint_ingest_complete)",
                severity="high",
            )
        )
    screen_at = _parse_iso_dt(last_screen_at)
    if screen_at is None or (as_of.date() - screen_at.date()) > timedelta(
        days=STALE_SCREEN_AFTER_DAYS
    ):
        age = (
            "no dated screen"
            if screen_at is None
            else f"last screen {screen_at.date().isoformat()}"
        )
        if entered_in_window:
            warnings.append(
                _admission_warning(
                    "stale_buy_tier_screen",
                    f"Buy-tier screen is stale ({age}); sprint-entry screen-lite "
                    "will refresh on the next deepen slot",
                )
            )
        else:
            warnings.append(
                _admission_warning(
                    "stale_buy_tier_screen",
                    f"Buy-tier screen is stale ({age}); ingest is deepening an old shortlist",
                )
            )
    from value_investor.library_sim import MARKET_BENCHMARKS

    if market_id not in MARKET_BENCHMARKS:
        warnings.append(
            _admission_warning(
                "no_observe_benchmark",
                "No Yahoo benchmark — Sunday screen-lite cannot refresh the buy-tier clock",
            )
        )

    last_run_at = None
    if last:
        last_run_at = last.get("run_at")
    return {
        "window_days": SPRINT_PROGRESS_WINDOW_DAYS,
        "run_count": len(window),
        "targets": targets,
        "improved": improved,
        "improved_tickers": improved_tickers[:12],
        "last_run_at": last_run_at,
        "runtime_cutoff_runs": cutoff_runs,
        "error_runs": error_runs,
        "gaps_before": gaps_before,
        "gaps_after": gaps_after,
        "gap_delta": delta,
        "remaining": remaining,
        "admission_ready": ready,
        "admission_gate": "sprint_ingest_complete",
        "admission_warnings": warnings,
        "sprint_entered_at": sprint_entered_at.isoformat() if sprint_entered_at else None,
    }


def _index_equal_support(library_root: Path) -> dict[str, Any]:
    raw = _as_dict(_safe_read(Path(library_root) / EQUAL_SUPPORT_FILENAME))
    markets = raw.get("markets") if isinstance(raw.get("markets"), dict) else {}
    return {
        "generated_at": raw.get("generated_at"),
        "admitted": [str(m) for m in _as_list(raw.get("admitted")) if str(m).strip()],
        "ai_judgment": bool(raw.get("ai_judgment")),
        "knob_apply": bool(raw.get("knob_apply")),
        "markets": {str(mid): value for mid, value in markets.items() if isinstance(value, dict)},
    }


def _slim_near_miss(raw: Any) -> dict[str, Any] | None:
    payload = _as_dict(raw)
    if not payload or payload.get("skipped"):
        return None
    watch = payload.get("buy_tier_not_now") or payload.get("buy_not_now") or []
    hold = payload.get("hold_near_buy") or []
    return {
        "buy_tier_not_now_count": _int(payload.get("buy_tier_not_now_count")),
        "hold_near_buy_count": _int(payload.get("hold_near_buy_count")),
        "not_buy_tier_count": _int(payload.get("not_buy_tier_count")),
        "never_buy_tier_count": _int(payload.get("never_buy_tier_count")),
        "timing_signal_present": bool(payload.get("timing_signal_present")),
        "observe_only": True,
        "watch_cut": "buy_not_now + hold_near_buy",
        "census_groups": "not_buy_tier + never_buy_tier",
        "buy_tier_not_now_sample": [
            _as_dict(row).get("ticker")
            for row in _as_list(watch)[:8]
            if _as_dict(row).get("ticker")
        ],
        "hold_near_buy_sample": [
            _as_dict(row).get("ticker") for row in _as_list(hold)[:8] if _as_dict(row).get("ticker")
        ],
    }


def _slim_equal_support_row(raw: Any) -> dict[str, Any] | None:
    row = _as_dict(raw)
    if not row:
        return None
    near = _as_dict(row.get("near_miss")) if isinstance(row.get("near_miss"), dict) else {}
    rememo = _as_dict(row.get("rememo")) if isinstance(row.get("rememo"), dict) else {}
    timing = _as_dict(row.get("timing")) if isinstance(row.get("timing"), dict) else {}
    archives = _as_dict(row.get("archives")) if isinstance(row.get("archives"), dict) else {}
    exclusion = _as_dict(archives.get("exclusion"))
    return {
        "present": True,
        "ai_judgment": bool(row.get("ai_judgment", False)),
        "knob_apply": bool(row.get("knob_apply", False)),
        "paper_instrument": row.get("paper_instrument") or BUY_TIER_LEVEL_TRACK,
        "timing_signal_present": bool(
            row.get("timing_signal_present")
            if "timing_signal_present" in row
            else timing.get("timing_signal_present")
        ),
        "buy_tier_not_now_count": _int(
            row.get("buy_tier_not_now_count", near.get("buy_tier_not_now_count"))
        ),
        "hold_near_buy_count": _int(
            row.get("hold_near_buy_count", near.get("hold_near_buy_count"))
        ),
        "not_buy_tier_count": _int(row.get("not_buy_tier_count", near.get("not_buy_tier_count"))),
        "never_buy_tier_count": _int(
            row.get("never_buy_tier_count", near.get("never_buy_tier_count"))
        ),
        "rememo_eligible_count": _int(
            row.get("rememo_eligible_count", rememo.get("eligible_count"))
        ),
        "exclusion_ready_for_priors": (
            row.get("exclusion_ready_for_priors")
            if "exclusion_ready_for_priors" in row
            else exclusion.get("ready_for_priors")
        ),
    }


def _paper_fund_path(
    market_id: str,
    *,
    paper_root: Path,
    shard_root: Path,
) -> Path:
    if market_id == LIVE_MARKET_ID:
        return paper_root / BUY_TIER_LEVEL_TRACK / "automated_fund.json"
    return (
        shard_root_for_market(market_id, base=shard_root)
        / BUY_TIER_LEVEL_TRACK
        / "automated_fund.json"
    )


def _native_paper_fund_path(
    market_id: str,
    *,
    shard_root: Path,
) -> Path:
    return (
        shard_root_for_market(market_id, base=shard_root)
        / BUY_TIER_LEVEL_NATIVE_TRACK
        / "automated_fund.json"
    )


def _observe_summary_path(library_root: Path, market_id: str) -> Path:
    return screen_dir_for(library_root, market_id) / "sim" / "observe_summary.json"


def _held_vs_market_row(
    market_id: str,
    *,
    currency: str | None,
    library_root: Path,
    paper_root: Path,
    shard_root: Path,
    charts_dir: Path | None,
    macro_closes: dict[str, dict[str, float]],
) -> dict[str, Any]:
    fund_path = _paper_fund_path(market_id, paper_root=paper_root, shard_root=shard_root)
    fund = _as_dict(_safe_read(fund_path))
    paper_instrument = BUY_TIER_LEVEL_TRACK
    chart_currency = currency
    # Non-UK shards: prefer the N153 native-currency twin when it has marks so
    # held-vs-market is not the GBP day-0 FX-warped book.
    if market_id != LIVE_MARKET_ID:
        native_path = _native_paper_fund_path(market_id, shard_root=shard_root)
        native_fund = _as_dict(_safe_read(native_path))
        native_curve = native_fund.get("equity_curve") if native_fund else None
        if isinstance(native_curve, list) and native_curve:
            fund = native_fund
            paper_instrument = BUY_TIER_LEVEL_NATIVE_TRACK
            fund_ccy = _as_dict(native_fund.get("config")).get("reporting_currency")
            if fund_ccy:
                chart_currency = str(fund_ccy)
    observe = None
    if market_id != LIVE_MARKET_ID:
        observe = _as_dict(_safe_read(_observe_summary_path(library_root, market_id)))
    try:
        payload = assemble_held_vs_market(
            market_id,
            fund=fund or None,
            observe=observe or None,
            charts_dir=charts_dir if market_id == LIVE_MARKET_ID else None,
            bench_closes=bench_closes_for_market(market_id, macro_closes=macro_closes),
            currency=chart_currency,
            allow_chart_densify=market_id == LIVE_MARKET_ID,
        )
    except Exception:  # noqa: BLE001 — grid must still render
        return empty_held_vs_market(
            market_id=market_id,
            currency=chart_currency,
            reason="Held vs market series failed to assemble",
        )
    if isinstance(payload, dict):
        payload["paper_instrument"] = paper_instrument
    if market_id == LIVE_MARKET_ID:
        payload = _overlay_ftse_dca_realism(
            payload,
            paper_root=paper_root,
            macro_closes=macro_closes,
        )
    elif paper_instrument == BUY_TIER_LEVEL_NATIVE_TRACK:
        payload = _overlay_gbp_fx_warped_archive(
            payload,
            market_id=market_id,
            paper_root=paper_root,
            shard_root=shard_root,
        )
    else:
        native_dir = shard_root_for_market(market_id, base=shard_root) / BUY_TIER_LEVEL_NATIVE_TRACK
        if (native_dir / "config.json").exists() and not (
            native_dir / "automated_fund.json"
        ).exists():
            payload = merge_branch_series(
                payload,
                branch_id=BUY_TIER_LEVEL_NATIVE_TRACK,
                label="Native-currency twin (pending)",
                values={},
                knobs={"capital_epoch": "n153_native_currency", "policy": "buy_tier_level"},
                status="pending",
            )
    return payload


def _overlay_gbp_fx_warped_archive(
    payload: dict[str, Any],
    *,
    market_id: str,
    paper_root: Path,
    shard_root: Path,
) -> dict[str, Any]:
    """Overlay the contaminated GBP buy_tier_level book as an observe archive branch."""
    gbp_path = _paper_fund_path(market_id, paper_root=paper_root, shard_root=shard_root)
    gbp_fund = _as_dict(_safe_read(gbp_path))
    if not gbp_fund:
        return payload
    gbp_marks = marks_from_fund(gbp_fund)
    held_values = {
        str(row["date"]): float(row["held"])
        for row in gbp_marks
        if row.get("date") is not None and _float(row.get("held")) is not None
    }
    return merge_branch_series(
        payload,
        branch_id=GBP_FX_WARPED_BRANCH,
        label="GBP book (FX-warped archive)",
        values=held_values,
        knobs={
            "reporting_currency": "GBP",
            "capital_epoch": "contaminated_gbp_unit_mismatch",
            "note": "Do not treat as adoption-truth NAV; compare only with FX disclaimer.",
        },
        status="active" if held_values else "pending",
    )


def _overlay_ftse_dca_realism(
    payload: dict[str, Any],
    *,
    paper_root: Path,
    macro_closes: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Overlay FTSE £500/mo DCA twin + deposit-matched ^FTSE on the epoch-0 chart."""
    dca_path = Path(paper_root) / BUY_TIER_LEVEL_DCA_TRACK / "automated_fund.json"
    dca_fund = _as_dict(_safe_read(dca_path))
    if not dca_fund:
        # Pending branch so the legend shows the experiment before first fill.
        return merge_branch_series(
            payload,
            branch_id=BUY_TIER_LEVEL_DCA_TRACK,
            label="DCA £500/mo book",
            values={},
            knobs={"monthly_deposit": 500.0, "policy": "buy_tier_level"},
            status="pending",
        )

    dca_marks = marks_from_fund(dca_fund)
    held_values = {
        str(row["date"]): float(row["held"])
        for row in dca_marks
        if row.get("date") is not None and _float(row.get("held")) is not None
    }
    payload = merge_branch_series(
        payload,
        branch_id=BUY_TIER_LEVEL_DCA_TRACK,
        label="DCA £500/mo book",
        values=held_values,
        knobs={"monthly_deposit": 500.0, "policy": "buy_tier_level"},
        status="active" if held_values else "pending",
    )

    dates = [str(row.get("date")) for row in _as_list(payload.get("points")) if row.get("date")]
    if not dates:
        dates = list(held_values)
    bench = bench_closes_for_market(LIVE_MARKET_ID, macro_closes=macro_closes)
    deltas = contribution_deltas_from_marks(dca_marks)
    market_map, _path = market_values_with_contributions(
        dates,
        bench,
        contribution_deltas=deltas,
    )
    if market_map:
        payload = merge_branch_series(
            payload,
            branch_id=BUY_TIER_LEVEL_DCA_MARKET_BRANCH,
            label="DCA £500/mo in ^FTSE",
            values=market_map,
            knobs={"monthly_deposit": 500.0, "kind": "deposit_matched_index"},
            status="active",
        )
    payload = dict(payload)
    payload["note"] = (
        "Held-stock value vs the same capital in ^FTSE (recycling epoch-0). "
        "DCA £500/mo book overlays the cold-start realism twin; "
        "DCA £500/mo in ^FTSE is the deposit-matched index path for that twin."
    )
    return payload


def _slim_epoch0(market_id: str, *, shard_root: Path | None = None) -> dict[str, Any] | None:
    root = shard_root_for_market(market_id, base=shard_root or DEFAULT_SHARD_ROOT)
    fund = _as_dict(_safe_read(root / BUY_TIER_LEVEL_TRACK / "automated_fund.json"))
    log = _as_dict(_safe_read(root / "weekday_batch_log.json"))
    entries = [row for row in _as_list(log.get("entries")) if isinstance(row, dict)]
    epoch_entries = [row for row in entries if str(row.get("cadence") or "") == "epoch0"]
    latest_batch = (epoch_entries or entries or [None])[-1]
    if not fund and not latest_batch:
        return None
    curve = [row for row in _as_list(fund.get("equity_curve")) if isinstance(row, dict)]
    last_mark = curve[-1] if curve else {}
    holdings = fund.get("holdings") if isinstance(fund.get("holdings"), dict) else {}
    tracks_acted = _as_dict((latest_batch or {}).get("tracks_acted"))
    return {
        "present": True,
        "paper_instrument": BUY_TIER_LEVEL_TRACK,
        "ai_judgment": bool((latest_batch or {}).get("ai_judgment", False)),
        "knob_apply": bool((latest_batch or {}).get("knob_apply", False)),
        "acted": bool(tracks_acted.get(BUY_TIER_LEVEL_TRACK, latest_batch is not None)),
        "last_run_at": (latest_batch or {}).get("run_at")
        or last_mark.get("at")
        or log.get("updated_at"),
        "holdings": len(holdings),
        "nav": _float(last_mark.get("portfolio_value")),
        "cash": _float(fund.get("cash") if fund else last_mark.get("cash")),
        "contributed_capital": _float(
            fund.get("contributed_capital") if fund else last_mark.get("contributed_capital")
        ),
        "weekday_batch_count": len(entries),
        "epoch0_batch_count": len(epoch_entries),
    }


def live_inputs_from_latest(latest_path: Path | None = None) -> dict[str, Any]:
    """Pull FTSE live tile inputs from the last published dashboard bundle."""
    latest = _as_dict(_safe_read(Path(latest_path or DEFAULT_LATEST_PATH)))
    meta = _as_dict(latest.get("meta"))
    progress = _as_dict(latest.get("project_progress"))
    stalled = bool(_as_dict(progress.get("ingest_bottleneck")).get("stalled"))
    counts = _signal_counts(meta.get("signal_counts"))
    return {
        "live_meta": {
            "company_count": meta.get("company_count"),
            "signal_counts": counts,
            "universe": meta.get("universe"),
        },
        "live_signal_counts": counts,
        "live_run_at": latest.get("run_at"),
        "live_ingest_stalled": stalled,
    }


def build_market_status(
    *,
    library_root: Path | None = None,
    policy_path: Path | None = None,
    dispatch_path: Path | None = None,
    shard_root: Path | None = None,
    paper_root: Path | None = None,
    charts_dir: Path | None = None,
    macro_root: Path | None = None,
    live_meta: dict[str, Any] | None = None,
    live_signal_counts: dict[str, int] | None = None,
    live_run_at: str | None = None,
    live_ingest_stalled: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble a slim per-market status grid from cached library artifacts."""
    library_root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    as_of = now or datetime.now(UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    policy_path = Path(policy_path or DEFAULT_POLICY_PATH)
    dispatch_path = Path(dispatch_path or DEFAULT_DISPATCH_PATH)
    paper_base = Path(paper_root or DEFAULT_PAPER_ROOT)
    charts_base = Path(charts_dir) if charts_dir is not None else DEFAULT_CHARTS_DIR
    macro_closes = load_macro_index_closes(Path(macro_root or DEFAULT_MACRO_ROOT))

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
    equal_support = _index_equal_support(library_root)
    admitted_list = admitted_learning_markets_for_policy(policy)
    admitted = set(admitted_list)
    equivalent = set(ftse_equivalent_markets(policy))
    profile_markets = set(ingest_profile_observe_sim_markets(policy))
    shard_base = Path(shard_root or DEFAULT_SHARD_ROOT)

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
    exhausted_markets = {
        str(m).strip() for m in _as_list(policy.get("ingest_exhausted_markets")) if str(m).strip()
    }
    exhausted_markets.update(
        str(m).strip() for m in _as_list(dispatch.get("ingest_exhausted_markets")) if str(m).strip()
    )
    live_meta = live_meta or {}
    live_counts = _signal_counts(live_signal_counts or live_meta.get("signal_counts"))

    markets: list[dict[str, Any]] = []
    for market_id, spec in MARKET_REGISTRY.items():
        status = status_by_market.get(market_id) or {}
        if not status and market_id != LIVE_MARKET_ID:
            status = _coverage_from_manifest(library_root, market_id)
        screen = (
            None if market_id == LIVE_MARKET_ID else _load_screen_summary(library_root, market_id)
        )
        dispatch_row = health_by_market.get(market_id) or {}
        cached_phase = _slim_phase(phases_by_market.get(market_id))
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
            admitted=admitted,
            ingest=ingest,
        )
        is_admitted = market_id in admitted
        equal_row = _slim_equal_support_row(equal_support["markets"].get(market_id))
        near_miss = None
        if market_id != LIVE_MARKET_ID:
            near_miss = _slim_near_miss(
                _safe_read(screen_dir_for(library_root, market_id) / NEAR_MISS_FILENAME)
            )
            if near_miss is None and equal_row:
                near_miss = {
                    "buy_tier_not_now_count": equal_row.get("buy_tier_not_now_count"),
                    "hold_near_buy_count": equal_row.get("hold_near_buy_count"),
                    "not_buy_tier_count": equal_row.get("not_buy_tier_count"),
                    "never_buy_tier_count": equal_row.get("never_buy_tier_count"),
                    "timing_signal_present": equal_row.get("timing_signal_present"),
                    "observe_only": True,
                    "watch_cut": "buy_not_now + hold_near_buy",
                    "census_groups": "not_buy_tier + never_buy_tier",
                }
        epoch0 = (
            None if market_id == LIVE_MARKET_ID else _slim_epoch0(market_id, shard_root=shard_base)
        )
        if market_id == LIVE_MARKET_ID:
            signal_counts = live_counts
            ticker_count = _int(live_meta.get("company_count") or status.get("ticker_count"))
            shortlist_count = _int(signal_counts.get("strong_buy")) + _int(signal_counts.get("buy"))
            last_screen_at = live_run_at
            coverage_pct = 1.0 if ticker_count else _float(status.get("coverage_pct"))
            current_phase = 4
            blockers: list[str] = []
            phase_row = cached_phase
        else:
            signal_counts = _signal_counts((screen or {}).get("signal_counts"))
            ticker_count = _int((screen or {}).get("ticker_count") or status.get("ticker_count"))
            shortlist_count = _int((screen or {}).get("shortlist_count"))
            last_screen_at = (screen or {}).get("run_at")
            coverage_pct = _float(status.get("coverage_pct"))
            phase_row = _resolve_learning_phase(
                market_id,
                cached=cached_phase,
                dispatch_row=dispatch_row,
                ingest=ingest,
                profile_markets=profile_markets,
                admitted=admitted,
                library_root=library_root,
                shard_base=shard_base,
                policy=policy,
            )
            current_phase = phase_row.get("current_phase") if phase_row else None
            blockers = _coalesce_phase_blockers(
                dispatch_blockers=list(dispatch_row.get("phase_blockers") or []),
                phase_row=phase_row,
                current_phase=current_phase,
            )

        stale = _int(status.get("stale"))
        filing_gaps = _int(dispatch_row.get("filing_gaps"))
        health = _health_tone(
            ingest=ingest,
            coverage_pct=coverage_pct,
            stale=stale,
            filing_gaps=filing_gaps,
            blockers=_health_blockers(blockers, is_admitted=is_admitted),
            live_ingest_stalled=live_ingest_stalled and market_id == LIVE_MARKET_ID,
        )
        filing_health = dispatch_row.get("filing_health")
        ingest_exhausted = bool(
            dispatch_row.get("ingest_exhausted")
            or _as_dict(filing_health).get("ingest_exhausted")
            or market_id in exhausted_markets
        )
        sprint_progress = _sprint_progress(
            market_id,
            library_root=library_root,
            ingest=ingest,
            last_screen_at=str(last_screen_at) if last_screen_at else None,
            filing_health=_as_dict(filing_health) or None,
            ingest_parity=(
                None
                if dispatch_row.get("ingest_parity_met") is None
                else bool(dispatch_row.get("ingest_parity_met"))
            ),
            ingest_exhausted=ingest_exhausted,
            now=as_of,
            sprint_entered_at=_parallel_sprint_entered_at(policy, market_id),
        )
        held_vs_market = _held_vs_market_row(
            market_id,
            currency=spec.currency,
            library_root=library_root,
            paper_root=paper_base,
            shard_root=shard_base,
            charts_dir=charts_base,
            macro_closes=macro_closes,
        )
        learning_depth = (
            None if market_id == LIVE_MARKET_ID else _slim_learning_depth(library_root, market_id)
        )
        learning_gate = build_learning_gate_indicator(
            is_live=market_id == LIVE_MARKET_ID,
            is_admitted=is_admitted,
            ingest=ingest,
            ingest_parity_met=(
                None
                if dispatch_row.get("ingest_parity_met") is None
                else bool(dispatch_row.get("ingest_parity_met"))
            ),
            ingest_exhausted=ingest_exhausted,
            sprint_progress=sprint_progress,
            learning_depth=learning_depth,
            filing_health=_as_dict(filing_health) or None,
            remaining_gaps=_as_dict(_as_dict(sprint_progress).get("remaining")) or None,
            epoch0=epoch0,
        )
        paper_instrument = None
        if held_vs_market.get("status") == "ok" and held_vs_market.get("paper_instrument"):
            paper_instrument = held_vs_market.get("paper_instrument")
        elif epoch0 or (equal_row and is_admitted) or market_id == LIVE_MARKET_ID:
            paper_instrument = BUY_TIER_LEVEL_TRACK
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
                "is_admitted": is_admitted,
                "is_ftse_equivalent": market_id in equivalent,
                "ingest": ingest,
                "ingest_stream": stream,
                "ingest_reason": dispatch_row.get("reason"),
                "ingest_parity_met": dispatch_row.get("ingest_parity_met"),
                "ingest_exhausted": ingest_exhausted,
                "queue_rank": _queue_rank(market_id, queue),
                "shared_maintenance": market_id in maintenance_markets,
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
                    (screen or {}).get("strong_buy") if screen else signal_counts.get("strong_buy")
                ),
                "buy": _int((screen or {}).get("buy") if screen else signal_counts.get("buy")),
                "learning_phase": current_phase,
                "learning_phase_label": _phase_label(
                    current_phase,
                    is_live=market_id == LIVE_MARKET_ID,
                    epoch0=epoch0,
                    ingest=ingest,
                ),
                "phase_blockers": blockers,
                "expected_epoch0_blockers": [
                    item for item in blockers if _is_expected_admitted_blocker(item)
                ]
                if is_admitted
                else [],
                "learning": phase_row,
                "filing_health": filing_health,
                "filing_gaps": filing_gaps if dispatch_row else None,
                "paper_instrument": paper_instrument,
                "ai_judgment": False if is_admitted else None,
                "knob_apply": False if is_admitted else None,
                "epoch0": epoch0,
                "equal_support": equal_row,
                "near_miss": near_miss,
                "sprint_progress": sprint_progress,
                "held_vs_market": held_vs_market,
                "learning_depth": learning_depth,
                "learning_gate": learning_gate,
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
        "generated_at": as_of.isoformat(),
        "note": (
            "Per-market stage and health snapshot for the dashboard grid. "
            "Ingest mode uses cached dispatch + policy lists; signal mix comes from "
            "the live FTSE screen or each library latest_summary.json. "
            "Admitted markets show epoch-0 buy-tier-level + equal-support near-miss "
            "(watch cut: buy-not-now / hold-near-buy). Sprint tiles add a 2-day ingest "
            "rollup and admission-progress flags. learning_gate is an observe-only "
            "Start → Bodies → Sprint → Admit → Epoch-0 → Parity → live-ready stepper with next-gate "
            "criteria and timeframe; live FTSE shows live-path status, not self catch-up. "
            "held_vs_market plots held-stock value vs local-index equivalent; "
            "knob-changed branches overlay the same dates when applied. "
            "Do not blend NAV into the gate graphic."
        ),
        "focus_market": focus or None,
        "admitted_markets": admitted_list,
        "summary": {
            "market_count": len(markets),
            "ingest_counts": ingest_counts,
            "role_counts": role_counts,
            "sprint_count": ingest_counts.get(INGEST_SPRINT, 0),
            "maintenance_count": ingest_counts.get(INGEST_MAINTENANCE, 0),
            "live_count": ingest_counts.get(INGEST_LIVE, 0),
            "admitted_count": len(admitted_list),
            "should_run_library_maintenance": bool(
                dispatch.get("should_run_library_maintenance") or maintenance_markets
            ),
            "maintenance_markets": sorted(maintenance_markets),
            "spare_sprint": {
                str(stream): market_id for market_id, stream in sprint_streams.items()
            },
            "equal_support_generated_at": equal_support.get("generated_at"),
        },
        "markets": markets,
    }


def write_market_status(
    *,
    library_root: Path | None = None,
    policy_path: Path | None = None,
    dispatch_path: Path | None = None,
    shard_root: Path | None = None,
    paper_root: Path | None = None,
    charts_dir: Path | None = None,
    macro_root: Path | None = None,
    latest_path: Path | None = None,
    path: Path | None = None,
) -> Path:
    """Rebuild ``docs/data/market_status.json`` without a full screen publish."""
    live = live_inputs_from_latest(latest_path)
    payload = build_market_status(
        library_root=library_root,
        policy_path=policy_path,
        dispatch_path=dispatch_path,
        shard_root=shard_root,
        paper_root=paper_root,
        charts_dir=charts_dir,
        macro_root=macro_root,
        live_meta=live["live_meta"],
        live_signal_counts=live["live_signal_counts"],
        live_run_at=live["live_run_at"],
        live_ingest_stalled=live["live_ingest_stalled"],
    )
    target = Path(path or DEFAULT_MARKET_STATUS_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, payload, compact=False)
    return target


__all__ = [
    "DEFAULT_MARKET_STATUS_PATH",
    "EPOCH0_PHASE_LABEL",
    "GATE_ADMIT",
    "GATE_BODIES",
    "GATE_EPOCH0",
    "GATE_FTSE_PARITY",
    "GATE_LIVE_READY",
    "GATE_SPRINT",
    "GATE_START",
    "INGEST_IDLE",
    "INGEST_LIVE",
    "INGEST_MAINTENANCE",
    "INGEST_QUEUED",
    "INGEST_SPRINT",
    "LIVE_MARKET_ID",
    "ROLE_ADMITTED",
    "ROLE_FOCUS",
    "ROLE_GRADUATED",
    "ROLE_LIVE",
    "ROLE_OTHER",
    "ROLE_QUEUE",
    "ROLE_SPRINT",
    "SCHEMA_VERSION",
    "build_learning_gate_indicator",
    "build_market_status",
    "live_inputs_from_latest",
    "write_market_status",
]
