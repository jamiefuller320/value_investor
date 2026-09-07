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
from value_investor.library_near_miss_watch import NEAR_MISS_FILENAME
from value_investor.library_screen import screen_dir_for
from value_investor.market_shard_admission import admitted_learning_markets_for_policy
from value_investor.market_shard_phases import DEFAULT_SHARD_ROOT, shard_root_for_market
from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 3
LIVE_MARKET_ID = "ftse350"
DEFAULT_MARKET_STATUS_PATH = Path("docs/data/market_status.json")
DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
BUY_TIER_LEVEL_TRACK = "buy_tier_level"
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
) -> str:
    if is_live:
        return PHASE_LABELS[4]
    if epoch0 and epoch0.get("present") and (current_phase or 0) <= 1:
        return EPOCH0_PHASE_LABEL
    if current_phase is None:
        return PHASE_LABELS[0]
    return PHASE_LABELS.get(current_phase, f"Phase {current_phase}")


def _is_expected_admitted_blocker(text: str) -> bool:
    return EXPECTED_ADMITTED_BLOCKER_NEEDLE in str(text or "").lower()


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

    warnings: list[dict[str, str]] = []
    if not window:
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
        age = "no dated screen" if screen_at is None else f"last screen {screen_at.date().isoformat()}"
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
                "paper_instrument": (
                    BUY_TIER_LEVEL_TRACK if epoch0 or (equal_row and is_admitted) else None
                ),
                "ai_judgment": False if is_admitted else None,
                "knob_apply": False if is_admitted else None,
                "epoch0": epoch0,
                "equal_support": equal_row,
                "near_miss": near_miss,
                "sprint_progress": sprint_progress,
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
            "rollup and admission-progress flags."
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
    "build_market_status",
    "live_inputs_from_latest",
    "write_market_status",
]
