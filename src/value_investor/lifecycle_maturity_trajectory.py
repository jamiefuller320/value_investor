"""Lifecycle maturity / mix trajectory observe twin (L463).

Persists a slim per-market history of held-column shares, median sleeve age,
and underwater-by-stage from ``lifecycle_board.json``. Observe-only — does
**not** touch cumulative ``beat_market`` / ``excess_after_costs``, exit_shadow,
L462 WoW NAV twin, N153 FX bookkeeping, or decision-review knob apply.

Dashboard preference: trajectory (Better/Worse) + freshness over raw counts.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.paper_automation import BUY_TIER_LEVEL_TRACK_ID
from value_investor.storage import read_json, write_json

DEFAULT_STORE_PATH = Path("docs/data/lifecycle_maturity_trajectory.json")
DEFAULT_BOARD_PATH = Path("docs/data/lifecycle_board.json")
DEFAULT_OPS_STATUS_PATH = Path("docs/data/ops_status.json")

SCHEMA_VERSION = 1
DEFAULT_STALE_AFTER_HOURS = 30.0
DEFAULT_STORE_LAG_WARN_HOURS = 2.0
HISTORY_KEEP = 28
HISTORY_MIN_INTERVAL_HOURS = 6.0

HELD_COLUMNS = ("just_bought", "growth", "near_sell")
SOLD_COLUMNS = ("just_sold", "post_sale")
# Spot board uses fraction-of-cost; treat any negative mark as UW for mix.
# Hypothesis-integrity −5% band stays separate (do not unify here).
UNDERWATER_PCT = 0.0

FINDING_TITLE = "Lifecycle maturity mix trajectory stalled"
FINDING_CATEGORY = "observe"


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


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(statistics.median(values)), 2)


def _share(part: int, whole: int) -> float | None:
    if whole <= 0:
        return None
    return round(part / whole, 4)


def _freshness_block(
    *,
    content_as_of: datetime | None,
    store_as_of: datetime | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
    present: bool,
) -> dict[str, Any]:
    """Freshness for maturity twin.

    Staleness follows the **board** content age. Commit-path lag follows the
    **maturity store** refresh time (refreshed on ops / queue-health), not the
    board — publish can legitimately trail ops without a L460-style anomaly.
    """
    age_h = _hours_since(content_as_of, now=now)
    store_lag_h = None
    if store_as_of is not None and ops_run_at is not None and ops_run_at > store_as_of:
        store_lag_h = round((ops_run_at - store_as_of).total_seconds() / 3600.0, 2)

    if not present:
        state = "missing"
        label = "Missing"
        detail = "Lifecycle board not published yet."
    elif age_h is None:
        state = "unknown"
        label = "Unknown"
        detail = "Board present but no usable timestamp."
    elif age_h >= stale_after_hours:
        state = "stale"
        label = "Stale"
        detail = f"Board last refresh {age_h:.1f}h ago (limit {stale_after_hours:.0f}h)."
    elif store_lag_h is not None and store_lag_h >= store_lag_warn_hours:
        state = "lagging"
        label = "Lagging ops"
        detail = (
            f"Maturity store trails ops_status by {store_lag_h:.1f}h "
            f"(check ops-monitor commit path)."
        )
    else:
        state = "fresh"
        label = "Fresh"
        detail = f"Board last refresh {age_h:.1f}h ago."

    return {
        "state": state,
        "label": label,
        "detail": detail,
        "as_of": content_as_of.isoformat() if content_as_of else None,
        "store_as_of": store_as_of.isoformat() if store_as_of else None,
        "age_hours": age_h,
        "store_lag_hours": store_lag_h,
        "stale_after_hours": float(stale_after_hours),
    }


def _delta_lower_better(current: int | float | None, previous: int | float | None) -> dict[str, Any]:
    """Trajectory for maturity mix: lower early_share / UW rate = improving."""
    if current is None or previous is None:
        return {"delta": None, "direction": "unknown", "label": "No prior cycle"}
    try:
        cur_f = float(current)
        prev_f = float(previous)
    except (TypeError, ValueError):
        return {"delta": None, "direction": "unknown", "label": "No prior cycle"}
    delta = cur_f - prev_f
    if abs(delta) < 1e-9:
        direction = "flat"
        label = "Unchanged vs last cycle"
    elif delta < 0:
        direction = "improving"
        label = "Better since last cycle (more mature / less UW)"
    else:
        direction = "worsening"
        label = "Worse since last cycle (earlier / more UW)"
    if float(delta).is_integer():
        delta_out: int | float = int(delta)
    else:
        delta_out = round(delta, 2)
    return {"delta": delta_out, "direction": direction, "label": label}


def _select_track(market: dict[str, Any]) -> dict[str, Any] | None:
    tracks = [row for row in _as_list(market.get("tracks")) if isinstance(row, dict)]
    if not tracks:
        return None
    for preferred in (BUY_TIER_LEVEL_TRACK_ID, str(market.get("default_track_id") or "")):
        if not preferred:
            continue
        hit = next((row for row in tracks if row.get("track_id") == preferred), None)
        if hit is not None:
            return hit
    default = next((row for row in tracks if row.get("is_default")), None)
    if default is not None:
        return default
    primary = next((row for row in tracks if row.get("is_primary")), None)
    if primary is not None:
        return primary
    return tracks[0]


def _column_cards(track: dict[str, Any], column_id: str) -> tuple[int, list[dict[str, Any]], int]:
    packed = _as_dict(_as_dict(track.get("position_columns")).get(column_id))
    count = int(packed.get("count") or 0)
    shown = [card for card in _as_list(packed.get("shown")) if isinstance(card, dict)]
    truncated = int(packed.get("truncated") or max(0, count - len(shown)))
    return count, shown, truncated


def _column_rollups(shown: list[dict[str, Any]]) -> dict[str, Any]:
    days = [
        float(v)
        for card in shown
        if (v := _optional_float(card.get("days_in_column"))) is not None
    ]
    pnl_known = [
        float(v)
        for card in shown
        if (v := _optional_float(card.get("unrealized_pnl_pct"))) is not None
    ]
    uw = sum(1 for v in pnl_known if v < UNDERWATER_PCT)
    known = len(pnl_known)
    return {
        "median_days_in_column": _median(days),
        "uw_count": uw,
        "uw_known": known,
        "uw_rate": round(uw / known, 4) if known else None,
        "shown_with_days": len(days),
    }


def _market_metrics(market: dict[str, Any], track: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    by_column: dict[str, Any] = {}
    truncated_any = False
    held_days: list[float] = []
    held_pnl: list[float] = []

    for column_id in HELD_COLUMNS:
        count, shown, truncated = _column_cards(track, column_id)
        counts[column_id] = count
        if truncated:
            truncated_any = True
        rollup = _column_rollups(shown)
        by_column[column_id] = {
            "count": count,
            "truncated": truncated,
            **rollup,
        }
        for card in shown:
            days = _optional_float(card.get("days_in_column"))
            if days is not None:
                held_days.append(float(days))
            pnl = _optional_float(card.get("unrealized_pnl_pct"))
            if pnl is not None:
                held_pnl.append(float(pnl))

    sold_counts = {cid: _column_cards(track, cid)[0] for cid in SOLD_COLUMNS}
    held_count = sum(counts.values())
    sold_count = sum(sold_counts.values())
    early_count = counts["just_bought"] + counts["growth"]
    early_share = _share(early_count, held_count)
    near_sell_share = _share(counts["near_sell"], held_count)
    sold_share = _share(sold_count, held_count + sold_count) if (held_count + sold_count) else None

    uw_held = sum(1 for v in held_pnl if v < UNDERWATER_PCT)
    uw_known = len(held_pnl)
    uw_rate_held = round(uw_held / uw_known, 4) if uw_known else None
    uw_rate_growth = by_column["growth"].get("uw_rate")

    # Primary display value: early_share as percent (lower = more mature).
    primary_value = None if early_share is None else round(early_share * 100.0, 2)

    return {
        "held_count": held_count,
        "sold_count": sold_count,
        "just_bought_count": counts["just_bought"],
        "growth_count": counts["growth"],
        "near_sell_count": counts["near_sell"],
        "just_sold_count": sold_counts["just_sold"],
        "post_sale_count": sold_counts["post_sale"],
        "early_count": early_count,
        "early_share": early_share,
        "near_sell_share": near_sell_share,
        "sold_share": sold_share,
        "shares": {
            "just_bought": _share(counts["just_bought"], held_count),
            "growth": _share(counts["growth"], held_count),
            "near_sell": near_sell_share,
        },
        "median_days_held": _median(held_days),
        "median_days_by_column": {
            cid: by_column[cid].get("median_days_in_column") for cid in HELD_COLUMNS
        },
        "uw_rate_by_column": {cid: by_column[cid].get("uw_rate") for cid in HELD_COLUMNS},
        "uw_rate_growth": uw_rate_growth,
        "uw_rate_held": uw_rate_held,
        "uw_count_held": uw_held,
        "uw_known_held": uw_known,
        "by_column": by_column,
        "shown_truncated": truncated_any,
        "underwater_threshold_pct": UNDERWATER_PCT,
        "primary_value_pct": primary_value,
    }


def _eligible_markets(board: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not board:
        return []
    out: list[dict[str, Any]] = []
    for row in _as_list(board.get("markets")):
        if not isinstance(row, dict):
            continue
        if row.get("is_live") or row.get("is_admitted") or row.get("is_focus"):
            out.append(row)
    return out


def _market_card(
    market: dict[str, Any],
    *,
    now: datetime,
    ops_run_at: datetime | None,
    board_as_of: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
    board_present: bool,
) -> dict[str, Any] | None:
    track = _select_track(market)
    if track is None:
        return None
    metrics = _market_metrics(market, track)
    freshness = _freshness_block(
        content_as_of=board_as_of,
        store_as_of=now,
        now=now,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=board_present,
    )
    market_id = str(market.get("market_id") or "")
    label = str(market.get("label") or market_id)
    early_pct = metrics.get("primary_value_pct")
    return {
        "id": market_id,
        "market_id": market_id,
        "title": label,
        "track_id": track.get("track_id"),
        "track_label": track.get("track_label"),
        "is_live": bool(market.get("is_live")),
        "is_focus": bool(market.get("is_focus")),
        "is_admitted": bool(market.get("is_admitted")),
        "observe_only": True,
        "warn_active": False,
        "severity": "ok",
        "metrics": metrics,
        "primary_metric": "early_share_pct",
        "primary_value": early_pct,
        "primary_label": "Early share % (just_bought+growth)/held — lower = more mature",
        "freshness": freshness,
    }


def _history_point(markets: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    point: dict[str, Any] = {"at": now.isoformat()}
    for row in markets:
        mid = row["id"]
        metrics = row.get("metrics") or {}
        point[mid] = {
            "primary_value": row.get("primary_value"),
            "early_share": metrics.get("early_share"),
            "uw_rate_growth": metrics.get("uw_rate_growth"),
            "uw_rate_held": metrics.get("uw_rate_held"),
            "median_days_held": metrics.get("median_days_held"),
            "held_count": metrics.get("held_count"),
            "freshness_state": (row.get("freshness") or {}).get("state"),
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


def _attach_trajectory(markets: list[dict[str, Any]], history: list[dict[str, Any]]) -> None:
    prior_point = history[-2] if len(history) >= 2 else None
    for row in markets:
        mid = row["id"]
        prev_row = (prior_point or {}).get(mid) if prior_point else None
        prev_val = (prev_row or {}).get("primary_value") if isinstance(prev_row, dict) else None
        traj = _delta_lower_better(row.get("primary_value"), prev_val)
        traj["prior_value"] = prev_val
        traj["prior_at"] = (prior_point or {}).get("at")
        # Secondary UW trajectory (informational; not the primary badge).
        prev_uw = (prev_row or {}).get("uw_rate_growth") if isinstance(prev_row, dict) else None
        cur_uw = (row.get("metrics") or {}).get("uw_rate_growth")
        uw_traj = _delta_lower_better(
            None if cur_uw is None else round(float(cur_uw) * 100.0, 2),
            None if prev_uw is None else round(float(prev_uw) * 100.0, 2),
        )
        row["trajectory"] = traj
        row["uw_growth_trajectory"] = uw_traj


def build_lifecycle_maturity_snapshot(
    *,
    board_path: Path = DEFAULT_BOARD_PATH,
    ops_status_path: Path = DEFAULT_OPS_STATUS_PATH,
    prior_path: Path = DEFAULT_STORE_PATH,
    board: dict[str, Any] | None = None,
    now: datetime | None = None,
    stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
    store_lag_warn_hours: float = DEFAULT_STORE_LAG_WARN_HOURS,
) -> dict[str, Any]:
    """Build per-market maturity cards + freshness + trajectory for the dashboard."""
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)

    board_payload = board if isinstance(board, dict) else _safe_read(Path(board_path))
    ops_status = _safe_read(Path(ops_status_path))
    ops_run_at = _parse_dt((ops_status or {}).get("run_at"))
    prior = _safe_read(Path(prior_path))
    board_present = board_payload is not None
    board_as_of = _parse_dt((board_payload or {}).get("generated_at")) if board_present else None

    markets: list[dict[str, Any]] = []
    for market in _eligible_markets(board_payload):
        card = _market_card(
            market,
            now=clock,
            ops_run_at=ops_run_at,
            board_as_of=board_as_of,
            stale_after_hours=stale_after_hours,
            store_lag_warn_hours=store_lag_warn_hours,
            board_present=board_present,
        )
        if card is not None:
            markets.append(card)

    history = _append_history(prior, _history_point(markets, now=clock), now=clock)
    _attach_trajectory(markets, history)

    freshness_states = [(row.get("freshness") or {}).get("state") for row in markets]
    if not board_present:
        surface_freshness = "missing"
    elif not markets:
        surface_freshness = "degraded"
    elif "stale" in freshness_states:
        surface_freshness = "stale"
    elif "lagging" in freshness_states:
        surface_freshness = "lagging"
    elif all(s == "fresh" for s in freshness_states):
        surface_freshness = "fresh"
    else:
        surface_freshness = "unknown"

    improving = sum(
        1 for row in markets if (row.get("trajectory") or {}).get("direction") == "improving"
    )
    worsening = sum(
        1 for row in markets if (row.get("trajectory") or {}).get("direction") == "worsening"
    )
    focus = next((row for row in markets if row.get("is_focus")), None)
    focus_early = (focus or {}).get("primary_value") if focus else None

    if surface_freshness in {"missing", "degraded"}:
        headline = (
            "Lifecycle maturity trajectory incomplete — board missing or no admitted markets."
        )
    elif surface_freshness == "stale":
        headline = (
            "Lifecycle board is stale — do not trust absolute mix counts; prefer trajectory "
            "only when history looks continuous."
        )
    elif surface_freshness == "lagging":
        headline = (
            "Maturity store / board lags ops_status (commit-path anomaly) — "
            "prefer trajectory only if history looks continuous."
        )
    elif focus is not None and focus_early is not None and float(focus_early) >= 70.0:
        headline = (
            f"Focus {focus.get('title')} still early-lifecycle-heavy "
            f"({focus_early:.0f}% just_bought+growth) — expected for young books; "
            "not a heal cue."
        )
    elif improving and not worsening:
        headline = "Lifecycle mix trajectory maturing (early_share falling) on some markets."
    elif worsening and not improving:
        headline = "Lifecycle mix trajectory shifting earlier / more UW on some markets."
    else:
        headline = "Lifecycle maturity mix quiet — per-market trajectory over raw counts."

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "observe_only": True,
        "instrument_id": "lifecycle_maturity_trajectory",
        "separation": {
            "excludes": [
                "beat_market",
                "excess_after_costs",
                "exit_shadow",
                "l462_wow_nav",
                "n153_fx",
                "decision_review_knob_apply",
            ],
            "note": (
                "Composition / j-curve observe twin only. Ultimate book health stays on "
                "cumulative beat_market; post-exit path on exit_shadow."
            ),
        },
        "headline": headline,
        "surface_freshness": surface_freshness,
        "ops_run_at": ops_run_at.isoformat() if ops_run_at else None,
        "board_generated_at": board_as_of.isoformat() if board_as_of else None,
        "board_path": str(board_path),
        "market_count": len(markets),
        "trajectory_summary": {
            "improving": improving,
            "worsening": worsening,
            "flat": sum(
                1 for row in markets if (row.get("trajectory") or {}).get("direction") == "flat"
            ),
            "unknown": sum(
                1
                for row in markets
                if (row.get("trajectory") or {}).get("direction") == "unknown"
            ),
            "history_points": len(history),
            "note": (
                "Deltas vs prior dashboard cycle on early_share % (lower = more mature). "
                "UW-by-stage is secondary context; raw column counts are spot only."
            ),
        },
        "markets": markets,
        "history": history,
    }


def refresh_lifecycle_maturity_trajectory(
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    board_path: Path = DEFAULT_BOARD_PATH,
    ops_status_path: Path = DEFAULT_OPS_STATUS_PATH,
    board: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write ``lifecycle_maturity_trajectory.json`` and return the snapshot."""
    store_path = Path(store_path)
    snapshot = build_lifecycle_maturity_snapshot(
        board_path=board_path,
        ops_status_path=ops_status_path,
        prior_path=store_path,
        board=board,
        now=now,
    )
    store_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(store_path, snapshot, compact=False)
    return snapshot


def ops_finding_from_maturity(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Optional observe finding when the series is missing / stalled."""
    if not snapshot:
        return {
            "severity": "warn",
            "category": FINDING_CATEGORY,
            "title": FINDING_TITLE,
            "summary": "Lifecycle maturity trajectory store could not be built.",
            "auto_fixable": False,
        }
    surface = str(snapshot.get("surface_freshness") or "")
    if surface in {"missing", "degraded"}:
        return {
            "severity": "warn",
            "category": FINDING_CATEGORY,
            "title": FINDING_TITLE,
            "summary": str(snapshot.get("headline") or "Maturity trajectory incomplete."),
            "auto_fixable": False,
        }
    if surface == "stale":
        return {
            "severity": "warn",
            "category": FINDING_CATEGORY,
            "title": FINDING_TITLE,
            "summary": (
                "Lifecycle board / maturity history is stale "
                f"({snapshot.get('board_generated_at') or 'no board timestamp'})."
            ),
            "auto_fixable": False,
        }
    return None


__all__ = [
    "DEFAULT_BOARD_PATH",
    "DEFAULT_OPS_STATUS_PATH",
    "DEFAULT_STALE_AFTER_HOURS",
    "DEFAULT_STORE_LAG_WARN_HOURS",
    "DEFAULT_STORE_PATH",
    "FINDING_CATEGORY",
    "FINDING_TITLE",
    "HELD_COLUMNS",
    "SCHEMA_VERSION",
    "UNDERWATER_PCT",
    "build_lifecycle_maturity_snapshot",
    "ops_finding_from_maturity",
    "refresh_lifecycle_maturity_trajectory",
]
