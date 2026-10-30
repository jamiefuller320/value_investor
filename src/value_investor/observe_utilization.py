"""Instrument-specific observe-utilization dashboard rollup (L461).

Surfaces buy-tier flip-lag and FTSE decision-input inventory beyond ops-monitor
overall status: warn state, cohort / gap counts, freshness, and trajectory
deltas vs the prior cycle.

Observe-only — does not rememo, deepen ingest, or dispatch engineering.
Persists a slim history series in ``docs/data/observe_utilization.json``
(committed via ops-monitor / queue-health refresh). Raw instrument stores
(``buy_tier_flip_lag.json``, ``decision_input_inventory.json``) are also
committed from ops-monitor (L460).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

DEFAULT_STORE_PATH = Path("docs/data/observe_utilization.json")
DEFAULT_OPS_STATUS_PATH = Path("docs/data/ops_status.json")
DEFAULT_FLIP_LAG_PATH = Path("docs/data/buy_tier_flip_lag.json")
DEFAULT_DECISION_INPUT_PATH = Path("docs/data/decision_input_inventory.json")
DEFAULT_SHARD_NAV_FX_PATH = Path("docs/data/shard_nav_fx_warp.json")
DEFAULT_ARCHIVE_MISS_PATH = Path("docs/data/universe_filing_archive_miss_rate.json")
DEFAULT_COMBINED_TAGGED_PATH = Path("docs/data/combined_tagged_learning.json")
DEFAULT_CUE_CONSUMER_MFT_PATH = Path("docs/data/cue_consumer_mft_observe.json")
DEFAULT_PARALLEL_TIMING_LENSES_PATH = Path("docs/data/parallel_timing_lenses.json")

SCHEMA_VERSION = 1
# Ops-monitor runs ~2×/day; past this the surface is obviously stale.
DEFAULT_STALE_AFTER_HOURS = 30.0
# Store lag vs ops run_at — anomaly after L460 (raw stores commit with ops).
DEFAULT_STORE_LAG_WARN_HOURS = 2.0
HISTORY_KEEP = 28
# Min gap between history points when metrics are unchanged.
HISTORY_MIN_INTERVAL_HOURS = 6.0

FLIP_LAG_FINDING_TITLE = "New buy-tier not yet usable"
DECISION_INPUT_FINDING_TITLE = "FTSE decision-input utilization gap"
SHARD_NAV_FX_FINDING_TITLE = "Shard NAV FX unit mismatch"
ARCHIVE_MISS_FINDING_TITLE = "Universe archive body-miss rate elevated"
COMBINED_TAGGED_FINDING_TITLE = "Combined tagged learning store stale"
CUE_CONSUMER_MFT_FINDING_TITLE = "Cue-consumer MFT episode walker (lab paper fills)"
CUE_CONSUMER_MFT_ARMED_TITLE = "Cue-consumer MFT lab armed (observe)"
PARALLEL_TIMING_LENSES_FINDING_TITLE = "Parallel timing lenses (observe)"
LAB_LEARNING_PROGRESS_FINDING_TITLE = "Lab learning progress (observe)"

_WARN_COUNT_RE = re.compile(r"^(\d+)\s+recent buy-tier flip", re.I)
_GAP_COUNT_RE = re.compile(r"(\d+)\s+of\s+\d+\s+names", re.I)


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _outcome_gap_theme(cite: str) -> str:
    """Map a deterministic outcome-gap cite to a stable theme bucket."""
    text = str(cite or "").strip()
    low = text.lower()
    if text.startswith("B1") or "judgment.b1" in low or low.startswith("judgment.b1"):
        return "B1_cheapness"
    if text.startswith("B2") or "judgment.b2" in low or low.startswith("judgment.b2"):
        return "B2_technical"
    if "entry_news" in low or "polarity" in low or "news" in low:
        return "news_polarity"
    if "sma" in low or "support" in low:
        return "sma_level"
    if "timing" in low or "mom_" in low:
        return "timing"
    head = text.split("=", 1)[0].strip()
    return head[:40] if head else "untyped"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 6)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 6)


def _aggregate_lab_learning_companions(
    *,
    mft_store: dict[str, Any] | None,
    lenses_store: dict[str, Any] | None,
) -> dict[str, Any]:
    """Join MFT + L652 into learning companions; fail-closed ``—`` fields when missing."""
    mft = mft_store if isinstance(mft_store, dict) else {}
    lenses = lenses_store if isinstance(lenses_store, dict) else {}
    summary = lenses.get("summary") if isinstance(lenses.get("summary"), dict) else {}

    open_n = mft.get("open_lab_episodes")
    closed_n = mft.get("closed_lab_episodes")
    try:
        open_i = int(open_n) if open_n is not None else None
    except (TypeError, ValueError):
        open_i = None
    try:
        closed_i = int(closed_n) if closed_n is not None else None
    except (TypeError, ValueError):
        closed_i = None

    path_board = mft.get("path_scoreboard") if isinstance(mft.get("path_scoreboard"), dict) else {}
    median_fc = _finite_float(path_board.get("smooth_ret_cohort_median"))

    levers_raw = mft.get("mom_levers") or []
    lever_rows: list[dict[str, Any]] = []
    if isinstance(levers_raw, list):
        for row in levers_raw:
            if not isinstance(row, dict):
                continue
            lever_rows.append(
                {
                    "id": row.get("id"),
                    "mom_score": row.get("mom_score"),
                    "status": row.get("status"),
                }
            )

    looking = summary.get("lenses_looking")
    entered = summary.get("lenses_entered")
    abandoned = summary.get("lenses_abandoned")
    try:
        looking_i = int(looking) if looking is not None else None
    except (TypeError, ValueError):
        looking_i = None
    try:
        entered_i = int(entered) if entered is not None else None
    except (TypeError, ValueError):
        entered_i = None
    try:
        abandoned_i = int(abandoned) if abandoned is not None else None
    except (TypeError, ValueError):
        abandoned_i = None
    concurrence_mean = _finite_float(summary.get("concurrence_mean"))

    entered_by_lens: dict[str, int] = {}
    dd_depths: list[float] = []
    dd_durs: list[float] = []
    fair_by_band: dict[int, list[float]] = {}
    had_themes: dict[str, int] = {}
    miss_themes: dict[str, int] = {}
    scored_outcome_reviews = 0
    lens_fair_cost_n = 0
    candidates = lenses.get("candidates") if isinstance(lenses.get("candidates"), list) else []

    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        conc_block = cand.get("concurrence") if isinstance(cand.get("concurrence"), dict) else {}
        conc_n = conc_block.get("count")
        try:
            conc_i = int(conc_n) if conc_n is not None else None
        except (TypeError, ValueError):
            conc_i = None
        for lens in cand.get("lenses") or []:
            if not isinstance(lens, dict):
                continue
            lens_id = str(lens.get("lens_id") or "").strip()
            status = str(lens.get("status") or "").strip()
            if status == "entered" and lens_id:
                entered_by_lens[lens_id] = entered_by_lens.get(lens_id, 0) + 1
            ep = lens.get("episode") if isinstance(lens.get("episode"), dict) else {}
            dd = _finite_float(ep.get("drawdown_depth"))
            if dd is not None:
                dd_depths.append(dd)
            dd_days = _finite_float(ep.get("drawdown_duration_days"))
            if dd_days is not None:
                dd_durs.append(dd_days)
            fc = _finite_float(ep.get("fair_cost_episode_pct"))
            if fc is not None:
                lens_fair_cost_n += 1
                if conc_i is not None:
                    fair_by_band.setdefault(conc_i, []).append(fc)
            orv = lens.get("outcome_review") if isinstance(lens.get("outcome_review"), dict) else {}
            had = orv.get("had_but_ignored") if isinstance(orv.get("had_but_ignored"), dict) else {}
            miss = (
                orv.get("missing_that_might_help")
                if isinstance(orv.get("missing_that_might_help"), dict)
                else {}
            )
            if (
                orv.get("scored_at")
                or had.get("text")
                or miss.get("text")
                or had.get("cites")
                or miss.get("cites")
            ):
                scored_outcome_reviews += 1
            for cite in had.get("cites") or []:
                theme = _outcome_gap_theme(str(cite))
                had_themes[theme] = had_themes.get(theme, 0) + 1
            for cite in miss.get("cites") or []:
                theme = _outcome_gap_theme(str(cite))
                miss_themes[theme] = miss_themes.get(theme, 0) + 1

    concurrence_bands: list[dict[str, Any]] = []
    for band, vals in sorted(fair_by_band.items()):
        concurrence_bands.append(
            {
                "concurrence": band,
                "n": len(vals),
                "median_fair_cost_episode_pct": _median(vals),
            }
        )
    if concurrence_bands:
        concurrence_outcome_note = (
            "Fair-cost by concurrence band (observe companion; N241 sizing not_now)."
            if len(concurrence_bands) >= 2
            else (
                "Thin fair-cost×concurrence join (single band) — "
                "show concurrence mean; thick LQ dashboard parked."
            )
        )
    else:
        concurrence_outcome_note = "Concurrence mean only — awaiting fair-cost by concurrence band."

    if scored_outcome_reviews > 0 or had_themes or miss_themes:
        gap_note = None
    else:
        gap_note = "awaiting scored episodes"

    learning_marks_n = (closed_i or 0) + lens_fair_cost_n

    return {
        "lab": {
            "open_lab_episodes": open_i,
            "closed_lab_episodes": closed_i,
            "path_median_fair_cost_pct": median_fc,
            "mom_levers": lever_rows,
            "evolutionary_shadows_eligible": mft.get("evolutionary_shadows_eligible"),
            "pipeline_status": mft.get("pipeline_status"),
            "walker_status": (mft.get("episode_walker") or {}).get("status")
            if isinstance(mft.get("episode_walker"), dict)
            else None,
        },
        "lenses": {
            "lenses_looking": looking_i,
            "lenses_entered": entered_i,
            "lenses_abandoned": abandoned_i,
            "concurrence_mean": concurrence_mean,
            "entered_by_lens": dict(sorted(entered_by_lens.items())),
            "candidate_count": summary.get("candidate_count"),
        },
        "companions": {
            "drawdown_depth_median": _median(dd_depths),
            "drawdown_depth_n": len(dd_depths),
            "drawdown_duration_days_median": _median(dd_durs),
            "drawdown_duration_n": len(dd_durs),
            "concurrence_mean": concurrence_mean,
            "concurrence_fair_cost_bands": concurrence_bands,
            "concurrence_outcome_note": concurrence_outcome_note,
            "had_but_ignored_theme_counts": dict(
                sorted(had_themes.items(), key=lambda kv: (-kv[1], kv[0]))
            ),
            "missing_that_might_help_theme_counts": dict(
                sorted(miss_themes.items(), key=lambda kv: (-kv[1], kv[0]))
            ),
            "scored_outcome_reviews": scored_outcome_reviews,
            "outcome_gap_note": gap_note,
            "lens_fair_cost_n": lens_fair_cost_n,
        },
        "learning_marks_n": learning_marks_n if (mft or lenses) else None,
    }


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _hours_since(then: datetime | None, *, now: datetime) -> float | None:
    if then is None:
        return None
    return round((now - then).total_seconds() / 3600.0, 2)


def _safe_read(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _findings_by_title(ops_status: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not ops_status:
        return out
    for row in ops_status.get("findings") or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if title:
            out[title] = row
    return out


def _freshness_block(
    *,
    as_of: datetime | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
    present: bool,
) -> dict[str, Any]:
    age_h = _hours_since(as_of, now=now)
    store_lag_h = None
    if as_of is not None and ops_run_at is not None and ops_run_at > as_of:
        store_lag_h = round((ops_run_at - as_of).total_seconds() / 3600.0, 2)

    if not present:
        state = "missing"
        label = "Missing"
        detail = "Instrument store not published yet."
    elif age_h is None:
        state = "unknown"
        label = "Unknown"
        detail = "Store present but no usable timestamp."
    elif age_h >= stale_after_hours:
        state = "stale"
        label = "Stale"
        detail = f"Last refresh {age_h:.1f}h ago (limit {stale_after_hours:.0f}h)."
    elif store_lag_h is not None and store_lag_h >= store_lag_warn_hours:
        state = "lagging"
        label = "Lagging ops"
        detail = (
            f"Store trails ops_status by {store_lag_h:.1f}h "
            f"(raw stores should commit with ops-monitor — check commit path)."
        )
    else:
        state = "fresh"
        label = "Fresh"
        detail = f"Last refresh {age_h:.1f}h ago."

    return {
        "state": state,
        "label": label,
        "detail": detail,
        "as_of": as_of.isoformat() if as_of else None,
        "age_hours": age_h,
        "store_lag_hours": store_lag_h,
        "stale_after_hours": float(stale_after_hours),
    }


def _delta(current: int | float | None, previous: int | float | None) -> dict[str, Any]:
    if current is None or previous is None:
        return {
            "delta": None,
            "direction": "unknown",
            "label": "No prior cycle",
        }
    try:
        cur_f = float(current)
        prev_f = float(previous)
    except (TypeError, ValueError):
        return {"delta": None, "direction": "unknown", "label": "No prior cycle"}
    delta = cur_f - prev_f
    # Lower warn/gap counts = improving for these instruments.
    if abs(delta) < 1e-9:
        direction = "flat"
        label = "Unchanged vs last cycle"
    elif delta < 0:
        direction = "improving"
        label = "Better since last cycle"
    else:
        direction = "worsening"
        label = "Worse since last cycle"
    # Prefer int display when whole numbers.
    if float(delta).is_integer():
        delta_out: int | float = int(delta)
    else:
        delta_out = round(delta, 2)
    return {"delta": delta_out, "direction": direction, "label": label}


def _flip_lag_instrument(
    *,
    store: dict[str, Any] | None,
    finding: dict[str, Any] | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
) -> dict[str, Any]:
    summary = (store or {}).get("summary") or {}
    warn_count = summary.get("warn_not_usable")
    open_count = summary.get("open_not_usable")
    cohort_count = summary.get("cohort_count")
    if warn_count is None and finding:
        match = _WARN_COUNT_RE.match(str(finding.get("summary") or ""))
        if match:
            warn_count = int(match.group(1))
    as_of = _parse_dt((store or {}).get("updated_at"))
    freshness = _freshness_block(
        as_of=as_of,
        now=now,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=store is not None,
    )
    warn_active = finding is not None or (
        isinstance(warn_count, (int, float)) and int(warn_count) > 0
    )
    open_rows = [row for row in ((store or {}).get("open") or []) if isinstance(row, dict)]
    warn_rows = [row for row in ((store or {}).get("warn_open") or []) if isinstance(row, dict)]
    sibling_home_open = 0
    true_no_memo_open = 0
    for row in open_rows:
        home = str(row.get("memo_home_market") or "").strip()
        market = str(row.get("market_id") or "").strip()
        if row.get("has_memo") and home and home != market:
            sibling_home_open += 1
        if not row.get("has_memo"):
            true_no_memo_open += 1

    def _slim_flip_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "ticker": row.get("ticker"),
            "market_id": row.get("market_id"),
            "blocking_stage": row.get("blocking_stage"),
            "has_memo": row.get("has_memo"),
            "memo_home_market": row.get("memo_home_market"),
            "hours_since_flip": row.get("hours_since_flip"),
        }

    return {
        "id": "buy_tier_flip_lag",
        "title": "Buy-tier flip → usable",
        "finding_title": FLIP_LAG_FINDING_TITLE,
        "observe_only": True,
        "warn_active": bool(warn_active),
        "severity": (finding or {}).get("severity")
        if finding
        else ("warn" if warn_active else "ok"),
        "finding_summary": (finding or {}).get("summary"),
        "metrics": {
            "warn_not_usable": int(warn_count) if warn_count is not None else None,
            "open_not_usable": int(open_count) if open_count is not None else None,
            "cohort_count": int(cohort_count) if cohort_count is not None else None,
            "usable_in_window": summary.get("usable_in_window"),
            "market_count": summary.get("market_count"),
            "blocking_stage_counts": summary.get("blocking_stage_counts") or {},
            "sibling_home_open_count": sibling_home_open,
            "true_no_memo_open_count": true_no_memo_open,
            "warn_sample": [_slim_flip_row(row) for row in (warn_rows or open_rows)[:8]],
        },
        "primary_metric": "warn_not_usable",
        "primary_value": int(warn_count) if warn_count is not None else None,
        "primary_label": "Warn cohort (≥24h path-incomplete)",
        "freshness": freshness,
    }


def _decision_input_instrument(
    *,
    store: dict[str, Any] | None,
    finding: dict[str, Any] | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
) -> dict[str, Any]:
    summary = (store or {}).get("summary") or {}
    rollup = (store or {}).get("rollup") or {}
    gap_counts = dict(summary.get("gap_counts") or rollup.get("gap_counts") or {})
    dominant = str(
        rollup.get("dominant_gap_field")
        or summary.get("verdict")
        or summary.get("sunday_bind_field")
        or ""
    )
    if dominant in {"", "P1 green-enough"}:
        dominant_count = 0
    else:
        dominant_count = gap_counts.get(dominant)
        if dominant_count is None and finding:
            match = _GAP_COUNT_RE.search(str(finding.get("summary") or ""))
            if match:
                dominant_count = int(match.group(1))
    as_of = _parse_dt((store or {}).get("generated_at") or (store or {}).get("updated_at"))
    freshness = _freshness_block(
        as_of=as_of,
        now=now,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=store is not None,
    )
    verdict = str(summary.get("verdict") or rollup.get("verdict") or "—")
    warn_active = finding is not None or (
        verdict not in {"P1 green-enough", "—", ""}
        and isinstance(dominant_count, (int, float))
        and int(dominant_count) >= 3
    )
    return {
        "id": "decision_input_inventory",
        "title": "FTSE decision-input inventory",
        "finding_title": DECISION_INPUT_FINDING_TITLE,
        "observe_only": True,
        "warn_active": bool(warn_active),
        "severity": (finding or {}).get("severity")
        if finding
        else ("warn" if warn_active else "ok"),
        "finding_summary": (finding or {}).get("summary"),
        "metrics": {
            "inventory_count": summary.get("inventory_count") or rollup.get("inventory_count"),
            "fully_ready_count": summary.get("fully_ready_count")
            or rollup.get("fully_ready_count"),
            "names_with_any_gap": summary.get("names_with_any_gap")
            or rollup.get("names_with_any_gap"),
            "dominant_gap_field": dominant or None,
            "dominant_gap_count": int(dominant_count) if dominant_count is not None else None,
            "gap_counts": gap_counts,
            "verdict": verdict,
        },
        "primary_metric": "dominant_gap_count",
        "primary_value": int(dominant_count) if dominant_count is not None else None,
        "primary_label": (
            f"Dominant gap ({dominant})"
            if dominant and dominant != "P1 green-enough"
            else "Dominant gap"
        ),
        "freshness": freshness,
    }


def _shard_nav_fx_instrument(
    *,
    store: dict[str, Any] | None,
    finding: dict[str, Any] | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
) -> dict[str, Any]:
    summary = (store or {}).get("summary") or {}
    warn_count = summary.get("warn_count")
    as_of = _parse_dt((store or {}).get("updated_at"))
    freshness = _freshness_block(
        as_of=as_of,
        now=now,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=store is not None,
    )
    warn_active = finding is not None or (
        isinstance(warn_count, (int, float)) and int(warn_count) > 0
    )
    return {
        "id": "shard_nav_fx_warp",
        "title": "Shard NAV FX unit mismatch",
        "finding_title": SHARD_NAV_FX_FINDING_TITLE,
        "observe_only": True,
        "warn_active": bool(warn_active),
        "severity": (finding or {}).get("severity")
        if finding
        else ("warn" if warn_active else "ok"),
        "finding_summary": (finding or {}).get("summary"),
        "metrics": {
            "warn_count": int(warn_count) if warn_count is not None else None,
            "gbp_warp_count": summary.get("gbp_warp_count"),
            "native_twin_active": summary.get("native_twin_active"),
            "native_twin_pending": summary.get("native_twin_pending"),
            "market_count": summary.get("market_count"),
            "warn_markets": summary.get("warn_markets") or [],
        },
        "primary_metric": "warn_count",
        "primary_value": int(warn_count) if warn_count is not None else None,
        "primary_label": "Markets with GBP warp and no active native twin",
        "freshness": freshness,
    }


def _archive_miss_instrument(
    *,
    store: dict[str, Any] | None,
    finding: dict[str, Any] | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
) -> dict[str, Any]:
    summary = (store or {}).get("summary") or {}
    miss_rate = summary.get("miss_rate")
    miss_count = summary.get("enter_body_miss_count")
    cohort = summary.get("cohort_count")
    open_missing = summary.get("open_still_missing_bodies")
    as_of = _parse_dt((store or {}).get("updated_at"))
    freshness = _freshness_block(
        as_of=as_of,
        now=now,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=store is not None,
    )
    warn_flag = bool(summary.get("warn"))
    warn_active = finding is not None or warn_flag
    # Primary metric: open still missing bodies (lower is better for trajectory).
    primary = int(open_missing) if open_missing is not None else None
    return {
        "id": "universe_filing_archive_miss_rate",
        "title": "Universe archive body-miss (proxy)",
        "finding_title": ARCHIVE_MISS_FINDING_TITLE,
        "observe_only": True,
        "warn_active": bool(warn_active),
        "severity": (finding or {}).get("severity")
        if finding
        else ("warn" if warn_active else "ok"),
        "finding_summary": (finding or {}).get("summary"),
        "metrics": {
            "miss_rate": miss_rate,
            "enter_body_miss_count": int(miss_count) if miss_count is not None else None,
            "cohort_count": int(cohort) if cohort is not None else None,
            "open_still_missing_bodies": primary,
            "by_market": summary.get("by_market") or {},
        },
        "primary_metric": "open_still_missing_bodies",
        "primary_value": primary,
        "primary_label": "Open flips still missing key bodies (archive-miss proxy)",
        "freshness": freshness,
    }


def _combined_tagged_instrument(
    *,
    store: dict[str, Any] | None,
    finding: dict[str, Any] | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
) -> dict[str, Any]:
    summary = (store or {}).get("summary") or {}
    missing = summary.get("source_records_missing_market_id")
    as_of = _parse_dt((store or {}).get("updated_at"))
    freshness = _freshness_block(
        as_of=as_of,
        now=now,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=store is not None,
    )
    warn_active = finding is not None
    primary = int(missing) if missing is not None else None
    return {
        "id": "combined_tagged_learning",
        "title": "Combined tagged exit_shadow join",
        "finding_title": COMBINED_TAGGED_FINDING_TITLE,
        "observe_only": True,
        "warn_active": bool(warn_active),
        "severity": (finding or {}).get("severity")
        if finding
        else ("warn" if warn_active else "ok"),
        "finding_summary": (finding or {}).get("summary"),
        "metrics": {
            "market_count": summary.get("market_count"),
            "open_count": summary.get("open_count"),
            "closed_count": summary.get("closed_count"),
            "first_episode_closed_count": summary.get("first_episode_closed_count"),
            "source_records_missing_market_id": primary,
            "source_files": summary.get("source_files"),
        },
        "primary_metric": "source_records_missing_market_id",
        "primary_value": primary,
        "primary_label": "Source exit_shadow rows still missing market_id",
        "freshness": freshness,
    }


def _cue_consumer_mft_instrument(
    *,
    store: dict[str, Any] | None,
    finding: dict[str, Any] | None,
    armed_finding: dict[str, Any] | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
) -> dict[str, Any]:
    """L640 — lab open/closed + MoM lever visibility without hunting JSON."""
    as_of = _parse_dt((store or {}).get("generated_at") or (store or {}).get("lab_armed_at"))
    freshness = _freshness_block(
        as_of=as_of,
        now=now,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=store is not None,
    )
    open_n = (store or {}).get("open_lab_episodes")
    closed_n = (store or {}).get("closed_lab_episodes")
    try:
        open_i = int(open_n) if open_n is not None else None
    except (TypeError, ValueError):
        open_i = None
    try:
        closed_i = int(closed_n) if closed_n is not None else None
    except (TypeError, ValueError):
        closed_i = None

    levers_raw = (store or {}).get("mom_levers") or []
    lever_rows: list[dict[str, Any]] = []
    if isinstance(levers_raw, list):
        for row in levers_raw:
            if not isinstance(row, dict):
                continue
            lever_rows.append(
                {
                    "id": row.get("id"),
                    "mom_score": row.get("mom_score"),
                    "status": row.get("status"),
                }
            )

    path_board = (store or {}).get("path_scoreboard") or {}
    if not isinstance(path_board, dict):
        path_board = {}
    walker = (store or {}).get("episode_walker") or {}
    if not isinstance(walker, dict):
        walker = {}
    gate = (store or {}).get("start_gate_cohort") or {}
    if not isinstance(gate, dict):
        gate = {}

    pipeline = str((store or {}).get("pipeline_status") or "")
    warn_active = finding is not None and str((finding or {}).get("severity") or "") in {
        "warn",
        "fail",
        "error",
    }
    # Prefer walker finding summary; fall back to armed.
    finding_summary = (finding or {}).get("summary") or (armed_finding or {}).get("summary")

    return {
        "id": "cue_consumer_mft",
        "title": "Cue-consumer MFT (super book)",
        "finding_title": CUE_CONSUMER_MFT_FINDING_TITLE,
        "observe_only": True,
        "influences_live": False,
        "warn_active": bool(warn_active),
        "severity": (finding or {}).get("severity")
        if finding
        else ("ok" if store is not None else "warn"),
        "finding_summary": finding_summary,
        "metrics": {
            "pipeline_status": pipeline or None,
            "open_lab_episodes": open_i,
            "closed_lab_episodes": closed_i,
            "walker_status": walker.get("status"),
            "cues_accepted": walker.get("cues_accepted"),
            "path_median_fair_cost_pct": path_board.get("smooth_ret_cohort_median"),
            "evolutionary_shadows_eligible": (store or {}).get("evolutionary_shadows_eligible"),
            "q8b_proposed_n": gate.get("proposed_n"),
            "q8b_frozen_n": gate.get("frozen_n"),
            "q8b_owner_freeze_pending": gate.get("owner_freeze_pending"),
            "mom_levers": lever_rows,
            "judgment_fill_status": ((store or {}).get("judgment_in_the_round") or {}).get(
                "fill_status"
            ),
            "declared_incomparable": (store or {}).get("declared_incomparable"),
        },
        "primary_metric": "open_lab_episodes",
        "primary_value": open_i,
        "primary_label": (
            f"Open lab episodes (closed={closed_i if closed_i is not None else '—'})"
        ),
        "freshness": freshness,
        "trajectory_note": (
            "Activity delta vs prior cycle — not a warn/gap instrument; "
            "rising open/closed is expected while the walker runs."
        ),
    }


def _parallel_timing_lenses_instrument(
    *,
    store: dict[str, Any] | None,
    finding: dict[str, Any] | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
) -> dict[str, Any]:
    """L652 — looking/entered/abandoned + concurrence (observe-only)."""
    as_of = _parse_dt((store or {}).get("generated_at") or (store or {}).get("asof"))
    freshness = _freshness_block(
        as_of=as_of,
        now=now,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=store is not None,
    )
    summary = (store or {}).get("summary") if isinstance((store or {}).get("summary"), dict) else {}
    looking = summary.get("lenses_looking")
    entered = summary.get("lenses_entered")
    abandoned = summary.get("lenses_abandoned")
    try:
        looking_i = int(looking) if looking is not None else None
    except (TypeError, ValueError):
        looking_i = None
    try:
        entered_i = int(entered) if entered is not None else None
    except (TypeError, ValueError):
        entered_i = None
    try:
        abandoned_i = int(abandoned) if abandoned is not None else None
    except (TypeError, ValueError):
        abandoned_i = None

    warn_active = finding is not None and str((finding or {}).get("severity") or "") in {
        "warn",
        "fail",
        "error",
    }
    return {
        "id": "parallel_timing_lenses",
        "title": "Parallel timing lenses (L652)",
        "finding_title": PARALLEL_TIMING_LENSES_FINDING_TITLE,
        "observe_only": True,
        "influences_live": False,
        "warn_active": bool(warn_active),
        "severity": (finding or {}).get("severity")
        if finding
        else ("ok" if store is not None else "warn"),
        "finding_summary": (finding or {}).get("summary"),
        "metrics": {
            "candidate_count": summary.get("candidate_count"),
            "buy_candidates": summary.get("buy_candidates"),
            "sell_candidates": summary.get("sell_candidates"),
            "lenses_looking": looking_i,
            "lenses_entered": entered_i,
            "lenses_abandoned": abandoned_i,
            "concurrence_mean": summary.get("concurrence_mean"),
            "buy_watch_armed": summary.get("buy_watch_armed"),
            "package": (store or {}).get("package"),
        },
        "primary_metric": "lenses_looking",
        "primary_value": looking_i,
        "primary_label": (
            f"Lenses looking (entered={entered_i if entered_i is not None else '—'}; "
            f"abandoned={abandoned_i if abandoned_i is not None else '—'})"
        ),
        "freshness": freshness,
        "trajectory_note": (
            "Activity delta vs prior cycle — looking→entered/abandoned is expected; "
            "not a P1 gap instrument."
        ),
    }


def _lab_learning_progress_instrument(
    *,
    mft_store: dict[str, Any] | None,
    lenses_store: dict[str, Any] | None,
    finding: dict[str, Any] | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
) -> dict[str, Any]:
    """Weekly lab learning strip — MFT + L652 + companions (Package M observe)."""
    as_candidates: list[datetime | None] = []
    if isinstance(mft_store, dict):
        as_candidates.append(
            _parse_dt(mft_store.get("generated_at") or mft_store.get("lab_armed_at"))
        )
    if isinstance(lenses_store, dict):
        as_candidates.append(
            _parse_dt(lenses_store.get("generated_at") or lenses_store.get("asof"))
        )
    present_ts = [dt for dt in as_candidates if dt is not None]
    as_of = min(present_ts) if present_ts else None
    present = mft_store is not None or lenses_store is not None
    freshness = _freshness_block(
        as_of=as_of,
        now=now,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=present,
    )
    rollup = _aggregate_lab_learning_companions(
        mft_store=mft_store,
        lenses_store=lenses_store,
    )
    primary = rollup.get("learning_marks_n")
    try:
        primary_i = int(primary) if primary is not None else None
    except (TypeError, ValueError):
        primary_i = None

    warn_active = finding is not None and str((finding or {}).get("severity") or "") in {
        "warn",
        "fail",
        "error",
    }
    lab = rollup.get("lab") or {}
    lenses = rollup.get("lenses") or {}
    companions = rollup.get("companions") or {}
    return {
        "id": "lab_learning_progress",
        "title": "Lab learning progress",
        "finding_title": LAB_LEARNING_PROGRESS_FINDING_TITLE,
        "observe_only": True,
        "influences_live": False,
        "package": "M",
        "warn_active": bool(warn_active),
        "severity": (finding or {}).get("severity") if finding else ("ok" if present else "warn"),
        "finding_summary": (finding or {}).get("summary"),
        "metrics": {
            "lab_open": lab.get("open_lab_episodes"),
            "lab_closed": lab.get("closed_lab_episodes"),
            "lab_median_fair_cost_pct": lab.get("path_median_fair_cost_pct"),
            "mom_levers": lab.get("mom_levers") or [],
            "evolutionary_shadows_eligible": lab.get("evolutionary_shadows_eligible"),
            "lab_pipeline_status": lab.get("pipeline_status"),
            "lab_walker_status": lab.get("walker_status"),
            "lenses_looking": lenses.get("lenses_looking"),
            "lenses_entered": lenses.get("lenses_entered"),
            "lenses_abandoned": lenses.get("lenses_abandoned"),
            "concurrence_mean": lenses.get("concurrence_mean"),
            "entered_by_lens": lenses.get("entered_by_lens") or {},
            "candidate_count": lenses.get("candidate_count"),
            "drawdown_depth_median": companions.get("drawdown_depth_median"),
            "drawdown_depth_n": companions.get("drawdown_depth_n"),
            "drawdown_duration_days_median": companions.get("drawdown_duration_days_median"),
            "drawdown_duration_n": companions.get("drawdown_duration_n"),
            "concurrence_fair_cost_bands": companions.get("concurrence_fair_cost_bands") or [],
            "concurrence_outcome_note": companions.get("concurrence_outcome_note"),
            "had_but_ignored_theme_counts": companions.get("had_but_ignored_theme_counts") or {},
            "missing_that_might_help_theme_counts": companions.get(
                "missing_that_might_help_theme_counts"
            )
            or {},
            "scored_outcome_reviews": companions.get("scored_outcome_reviews"),
            "outcome_gap_note": companions.get("outcome_gap_note"),
            "lens_fair_cost_n": companions.get("lens_fair_cost_n"),
            "learning_marks_n": primary_i,
        },
        "primary_metric": "learning_marks_n",
        "primary_value": primary_i,
        "primary_label": ("Learning marks (MFT closed + lens fair-cost episodes)"),
        "freshness": freshness,
        "trajectory_note": (
            "Learning-volume delta vs prior cycle — rising marks expected while "
            "the lab/lenses score; not a P1 gap instrument. Fair-cost primary; "
            "drawdown / concurrence×outcome / gap themes are companions."
        ),
    }


def _history_point(instruments: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    point: dict[str, Any] = {"at": now.isoformat()}
    for inst in instruments:
        point[inst["id"]] = {
            "primary_value": inst.get("primary_value"),
            "warn_active": bool(inst.get("warn_active")),
            "freshness_state": (inst.get("freshness") or {}).get("state"),
        }
    return point


def _append_history(
    prior: dict[str, Any] | None,
    point: dict[str, Any],
    *,
    now: datetime,
    keep: int = HISTORY_KEEP,
    min_interval_hours: float = HISTORY_MIN_INTERVAL_HOURS,
) -> list[dict[str, Any]]:
    history = list((prior or {}).get("history") or [])
    if history:
        last = history[-1]
        last_at = _parse_dt(last.get("at"))
        same_metrics = all(last.get(key) == point.get(key) for key in point if key != "at")
        if (
            same_metrics
            and last_at is not None
            and (now - last_at) < timedelta(hours=min_interval_hours)
        ):
            return history[-keep:]
    history.append(point)
    return history[-keep:]


def _attach_trajectory(
    instruments: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> None:
    prior_point = history[-2] if len(history) >= 2 else None
    for inst in instruments:
        iid = inst["id"]
        prev_row = (prior_point or {}).get(iid) if prior_point else None
        prev_val = (prev_row or {}).get("primary_value") if isinstance(prev_row, dict) else None
        traj = _delta(inst.get("primary_value"), prev_val)
        traj["prior_value"] = prev_val
        traj["prior_at"] = (prior_point or {}).get("at")
        inst["trajectory"] = traj


def build_observe_utilization_snapshot(
    *,
    flip_lag_path: Path = DEFAULT_FLIP_LAG_PATH,
    decision_input_path: Path = DEFAULT_DECISION_INPUT_PATH,
    shard_nav_fx_path: Path = DEFAULT_SHARD_NAV_FX_PATH,
    archive_miss_path: Path = DEFAULT_ARCHIVE_MISS_PATH,
    combined_tagged_path: Path = DEFAULT_COMBINED_TAGGED_PATH,
    cue_consumer_mft_path: Path = DEFAULT_CUE_CONSUMER_MFT_PATH,
    parallel_timing_lenses_path: Path = DEFAULT_PARALLEL_TIMING_LENSES_PATH,
    ops_status_path: Path = DEFAULT_OPS_STATUS_PATH,
    prior_path: Path = DEFAULT_STORE_PATH,
    now: datetime | None = None,
    stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
    store_lag_warn_hours: float = DEFAULT_STORE_LAG_WARN_HOURS,
) -> dict[str, Any]:
    """Build instrument cards + freshness + trajectory for the dashboard."""
    clock = now or datetime.now(UTC)
    ops_status = _safe_read(Path(ops_status_path))
    findings = _findings_by_title(ops_status)
    ops_run_at = _parse_dt((ops_status or {}).get("run_at"))
    flip_store = _safe_read(Path(flip_lag_path))
    decision_store = _safe_read(Path(decision_input_path))
    shard_fx_store = _safe_read(Path(shard_nav_fx_path))
    archive_miss_store = _safe_read(Path(archive_miss_path))
    combined_store = _safe_read(Path(combined_tagged_path))
    mft_store = _safe_read(Path(cue_consumer_mft_path))
    lenses_store = _safe_read(Path(parallel_timing_lenses_path))
    prior = _safe_read(Path(prior_path))

    instruments = [
        _flip_lag_instrument(
            store=flip_store,
            finding=findings.get(FLIP_LAG_FINDING_TITLE),
            now=clock,
            ops_run_at=ops_run_at,
            stale_after_hours=stale_after_hours,
            store_lag_warn_hours=store_lag_warn_hours,
        ),
        _decision_input_instrument(
            store=decision_store,
            finding=findings.get(DECISION_INPUT_FINDING_TITLE),
            now=clock,
            ops_run_at=ops_run_at,
            stale_after_hours=stale_after_hours,
            store_lag_warn_hours=store_lag_warn_hours,
        ),
        _archive_miss_instrument(
            store=archive_miss_store,
            finding=findings.get(ARCHIVE_MISS_FINDING_TITLE),
            now=clock,
            ops_run_at=ops_run_at,
            stale_after_hours=stale_after_hours,
            store_lag_warn_hours=store_lag_warn_hours,
        ),
        _shard_nav_fx_instrument(
            store=shard_fx_store,
            finding=findings.get(SHARD_NAV_FX_FINDING_TITLE),
            now=clock,
            ops_run_at=ops_run_at,
            stale_after_hours=stale_after_hours,
            store_lag_warn_hours=store_lag_warn_hours,
        ),
        _combined_tagged_instrument(
            store=combined_store,
            finding=findings.get(COMBINED_TAGGED_FINDING_TITLE),
            now=clock,
            ops_run_at=ops_run_at,
            stale_after_hours=stale_after_hours,
            store_lag_warn_hours=store_lag_warn_hours,
        ),
        _cue_consumer_mft_instrument(
            store=mft_store,
            finding=findings.get(CUE_CONSUMER_MFT_FINDING_TITLE),
            armed_finding=findings.get(CUE_CONSUMER_MFT_ARMED_TITLE),
            now=clock,
            ops_run_at=ops_run_at,
            stale_after_hours=stale_after_hours,
            store_lag_warn_hours=store_lag_warn_hours,
        ),
        _parallel_timing_lenses_instrument(
            store=lenses_store,
            finding=findings.get(PARALLEL_TIMING_LENSES_FINDING_TITLE),
            now=clock,
            ops_run_at=ops_run_at,
            stale_after_hours=stale_after_hours,
            store_lag_warn_hours=store_lag_warn_hours,
        ),
        _lab_learning_progress_instrument(
            mft_store=mft_store,
            lenses_store=lenses_store,
            finding=findings.get(LAB_LEARNING_PROGRESS_FINDING_TITLE),
            now=clock,
            ops_run_at=ops_run_at,
            stale_after_hours=stale_after_hours,
            store_lag_warn_hours=store_lag_warn_hours,
        ),
    ]

    history = _append_history(prior, _history_point(instruments, now=clock), now=clock)
    _attach_trajectory(instruments, history)

    freshness_states = [(inst.get("freshness") or {}).get("state") for inst in instruments]
    if "missing" in freshness_states:
        surface_freshness = "degraded"
    elif "stale" in freshness_states:
        surface_freshness = "stale"
    elif "lagging" in freshness_states:
        surface_freshness = "lagging"
    elif all(s == "fresh" for s in freshness_states):
        surface_freshness = "fresh"
    else:
        surface_freshness = "unknown"

    warn_count = sum(1 for inst in instruments if inst.get("warn_active"))
    improving = sum(
        1 for inst in instruments if (inst.get("trajectory") or {}).get("direction") == "improving"
    )
    worsening = sum(
        1 for inst in instruments if (inst.get("trajectory") or {}).get("direction") == "worsening"
    )

    if surface_freshness in {"stale", "degraded"}:
        headline = "Observe utilization surface is stale/incomplete — do not trust absolute counts."
    elif surface_freshness == "lagging":
        headline = (
            "Instrument stores lag ops_status (commit-path anomaly) — "
            "prefer trajectory only if history looks continuous."
        )
    elif warn_count and worsening:
        headline = f"{warn_count} warn instrument(s); trajectory worsening on {worsening}."
    elif warn_count and improving:
        headline = f"{warn_count} warn instrument(s); improving vs last cycle on {improving}."
    elif warn_count:
        headline = f"{warn_count} observe utilization warn(s) — cohorts need attention."
    elif improving:
        headline = "Observe utilization quiet; trajectory improving."
    else:
        headline = "Observe utilization quiet (P1 path looks green-enough)."

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "observe_only": True,
        "headline": headline,
        "surface_freshness": surface_freshness,
        "ops_run_at": ops_run_at.isoformat() if ops_run_at else None,
        "warn_instrument_count": warn_count,
        "trajectory_summary": {
            "improving": improving,
            "worsening": worsening,
            "flat": sum(
                1
                for inst in instruments
                if (inst.get("trajectory") or {}).get("direction") == "flat"
            ),
            "unknown": sum(
                1
                for inst in instruments
                if (inst.get("trajectory") or {}).get("direction") == "unknown"
            ),
            "history_points": len(history),
            "note": (
                "Deltas vs prior dashboard cycle (warn/gap counts; lower is better). "
                "Raw instrument stores commit with ops-monitor (L460)."
            ),
        },
        "instruments": instruments,
        "history": history,
    }


def refresh_observe_utilization(
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    flip_lag_path: Path = DEFAULT_FLIP_LAG_PATH,
    decision_input_path: Path = DEFAULT_DECISION_INPUT_PATH,
    shard_nav_fx_path: Path = DEFAULT_SHARD_NAV_FX_PATH,
    archive_miss_path: Path = DEFAULT_ARCHIVE_MISS_PATH,
    combined_tagged_path: Path = DEFAULT_COMBINED_TAGGED_PATH,
    cue_consumer_mft_path: Path = DEFAULT_CUE_CONSUMER_MFT_PATH,
    parallel_timing_lenses_path: Path = DEFAULT_PARALLEL_TIMING_LENSES_PATH,
    ops_status_path: Path = DEFAULT_OPS_STATUS_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write ``observe_utilization.json`` and return the snapshot."""
    store_path = Path(store_path)
    snapshot = build_observe_utilization_snapshot(
        flip_lag_path=flip_lag_path,
        decision_input_path=decision_input_path,
        shard_nav_fx_path=shard_nav_fx_path,
        archive_miss_path=archive_miss_path,
        combined_tagged_path=combined_tagged_path,
        cue_consumer_mft_path=cue_consumer_mft_path,
        parallel_timing_lenses_path=parallel_timing_lenses_path,
        ops_status_path=ops_status_path,
        prior_path=store_path,
        now=now,
    )
    store_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(store_path, snapshot, compact=False)
    return snapshot


def build_lab_learning_progress_finding(
    *,
    mft_store: dict[str, Any] | None = None,
    lenses_store: dict[str, Any] | None = None,
    cue_consumer_mft_path: Path = DEFAULT_CUE_CONSUMER_MFT_PATH,
    parallel_timing_lenses_path: Path = DEFAULT_PARALLEL_TIMING_LENSES_PATH,
) -> dict[str, Any]:
    """Info finding for the weekly lab learning strip (observe / warn-only)."""
    mft = mft_store if mft_store is not None else _safe_read(Path(cue_consumer_mft_path))
    lenses = (
        lenses_store if lenses_store is not None else _safe_read(Path(parallel_timing_lenses_path))
    )
    rollup = _aggregate_lab_learning_companions(mft_store=mft, lenses_store=lenses)
    lab = rollup.get("lab") or {}
    lens = rollup.get("lenses") or {}
    companions = rollup.get("companions") or {}
    med = lab.get("path_median_fair_cost_pct")
    med_bit = f"{med:.4f}" if isinstance(med, (int, float)) else "—"
    had = companions.get("had_but_ignored_theme_counts") or {}
    miss = companions.get("missing_that_might_help_theme_counts") or {}
    gap_bit = companions.get("outcome_gap_note") or (
        f"had_themes={len(had)} miss_themes={len(miss)} "
        f"scored_reviews={companions.get('scored_outcome_reviews', 0)}"
    )
    return {
        "severity": "info",
        "category": "research",
        "title": LAB_LEARNING_PROGRESS_FINDING_TITLE,
        "summary": (
            f"Lab learning progress: MFT open/closed="
            f"{lab.get('open_lab_episodes')} / {lab.get('closed_lab_episodes')}; "
            f"median fair-cost={med_bit}; shadows_eligible="
            f"{lab.get('evolutionary_shadows_eligible')}; "
            f"L652 looking/entered/abandoned="
            f"{lens.get('lenses_looking')}/{lens.get('lenses_entered')}/"
            f"{lens.get('lenses_abandoned')}; concurrence_mean="
            f"{lens.get('concurrence_mean')}; learning_marks="
            f"{rollup.get('learning_marks_n')}; gaps={gap_bit}. "
            "Package M observe strip; influences_live=false; never Package L / N241. "
            "Dashboard: Automation → Observe utilization."
        ),
        "auto_fixable": False,
    }


__all__ = [
    "ARCHIVE_MISS_FINDING_TITLE",
    "COMBINED_TAGGED_FINDING_TITLE",
    "CUE_CONSUMER_MFT_ARMED_TITLE",
    "CUE_CONSUMER_MFT_FINDING_TITLE",
    "DECISION_INPUT_FINDING_TITLE",
    "DEFAULT_ARCHIVE_MISS_PATH",
    "DEFAULT_COMBINED_TAGGED_PATH",
    "DEFAULT_CUE_CONSUMER_MFT_PATH",
    "DEFAULT_DECISION_INPUT_PATH",
    "DEFAULT_FLIP_LAG_PATH",
    "DEFAULT_OPS_STATUS_PATH",
    "DEFAULT_PARALLEL_TIMING_LENSES_PATH",
    "DEFAULT_SHARD_NAV_FX_PATH",
    "DEFAULT_STALE_AFTER_HOURS",
    "DEFAULT_STORE_LAG_WARN_HOURS",
    "DEFAULT_STORE_PATH",
    "FLIP_LAG_FINDING_TITLE",
    "LAB_LEARNING_PROGRESS_FINDING_TITLE",
    "PARALLEL_TIMING_LENSES_FINDING_TITLE",
    "SCHEMA_VERSION",
    "SHARD_NAV_FX_FINDING_TITLE",
    "build_lab_learning_progress_finding",
    "build_observe_utilization_snapshot",
    "refresh_observe_utilization",
]
