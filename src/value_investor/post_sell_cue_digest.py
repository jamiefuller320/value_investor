"""Observe-only post-sell cue digest + selection postmortem skeleton (package M).

Learning question: can closed-episode timing + selection cues from inventory
already collected (N200 levers, exit-timing/shadow readiness, control closed
sells, archive near-miss) surface experiment backlog signals without sealing
N205 or applying knobs?

Produces ``docs/data/post_sell_cue_digest.json`` from daily ops-monitor.
Never changes books or knobs (``auto_fixable=False``).

Epoch gate (owner fork F, locked): every skeleton row and experiment cue must
carry a rebalance_log-joined epoch key (``knob_epoch_started_at`` present as a
field, plus screen/selection identity). Fail closed — abstain / drop cue claims
when the join fails; do not invent. Do **not** widen beyond FTSE control
``buy_tier_level`` closed sells until every cue/row carries the key.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.rebalance_log import load_rebalance_log
from value_investor.storage import write_json

SCHEMA_VERSION = 2
FINDING_TITLE = "Post-sell cue digest (observe)"
STORE_FAILED_TITLE = "Post-sell cue digest observe failed"
DEFAULT_STORE_PATH = Path("docs/data/post_sell_cue_digest.json")
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
CONTROL_TRACK_ID = "buy_tier_level"
CATEGORY = "research"
# While control closed-sell n is tiny, list all rows; cap for future widen only.
SELECTION_SAMPLE_LIMIT = 50
SELECTION_FULL_LIST_MAX = 50
OPS_DOC = "docs/ops/post-sell-cue-digest.md"
N200_REGISTRATION_ID = "strand-b-plain-value-tech-timing-v0"
JOIN_WINDOW_SECONDS = 2 * 86400

BUY_SIGNALS = frozenset({"buy", "strong_buy"})

# Stable subset for selection fingerprint (PIT autopsy / review pack).
_SELECTION_FP_KEYS: tuple[str, ...] = (
    "skip_timing_wait",
    "min_conviction",
    "use_adjusted_signal",
    "require_research_accumulate",
    "use_momentum_grace",
    "use_graduated_allocation",
    "exit_confirm_screens",
    "reentry_cooldown_screens",
    "sector_cap",
)

# Widen gate: FTSE control only until epoch keys are universal on every cue/row.
WIDEN_GATE = {
    "locked": True,
    "fork": "F",
    "rule": (
        "Require epoch key on every cue/row before widening beyond FTSE control "
        "buy_tier_level closed sells"
    ),
    "current_population": "ftse_control_buy_tier_level",
    "widened": False,
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_read(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _pct(price: float, avg_cost: float) -> float | None:
    if avg_cost <= 0:
        return None
    return round((price - avg_cost) / avg_cost * 100.0, 2)


def _bucket_realized(pct: float | None) -> str:
    if pct is None:
        return "unknown"
    if pct <= -10:
        return "le_m10"
    if pct < 0:
        return "m10_to_0"
    if pct < 10:
        return "0_to_10"
    return "ge_10"


def _buy_set_from_latest(latest: dict[str, Any] | None) -> set[str]:
    if not isinstance(latest, dict):
        return set()
    out: set[str] = set()
    for row in latest.get("reports") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("signal") or "") in BUY_SIGNALS:
            ticker = str(row.get("ticker") or "").strip()
            if ticker:
                out.add(ticker)
    return out


def _loser_card_index(cards_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(cards_payload, dict):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for card in cards_payload.get("cards") or []:
        if not isinstance(card, dict):
            continue
        ticker = str(card.get("ticker") or "").strip()
        if not ticker:
            continue
        screen = card.get("screen") if isinstance(card.get("screen"), dict) else {}
        index[ticker] = {
            "cohorts": list(card.get("cohorts") or [])[:4],
            "signal": screen.get("signal"),
            "conviction_score": screen.get("conviction_score"),
            "composite_score": screen.get("composite_score"),
        }
    return index


def _selection_fingerprint(
    selection: dict[str, Any] | None,
    *,
    trade_cost_pct: Any = None,
) -> str:
    payload: dict[str, Any] = {
        key: (selection or {}).get(key) for key in _SELECTION_FP_KEYS
    }
    if trade_cost_pct is not None:
        payload["trade_cost_pct"] = trade_cost_pct
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _capital_epoch_surrogate(
    *,
    track_label: str | None,
    fund_created_at: str | None,
) -> str:
    label = str(track_label or "").strip() or "unknown_label"
    created = str(fund_created_at or "").strip() or "unknown_created"
    return f"{label}|{created}"


def _epoch_key_from_pass(
    entry: dict[str, Any],
    *,
    fund_created_at: str | None,
) -> dict[str, Any]:
    selection = entry.get("selection") if isinstance(entry.get("selection"), dict) else {}
    screen = (
        entry.get("screen_source") if isinstance(entry.get("screen_source"), dict) else {}
    )
    # knob_epoch_started_at may be null but the field must be present (fail-closed
    # invents nothing — null is an honest cold-start stamp).
    knob_epoch = entry.get("knob_epoch_started_at", None)
    if "knob_epoch_started_at" not in entry:
        # Missing key entirely → treat as unjoinable epoch (do not invent).
        raise KeyError("knob_epoch_started_at")
    return {
        "track_id": str(entry.get("track_id") or CONTROL_TRACK_ID),
        "track_label": entry.get("track_label"),
        "capital_epoch": _capital_epoch_surrogate(
            track_label=str(entry.get("track_label") or ""),
            fund_created_at=fund_created_at,
        ),
        "knob_epoch_started_at": knob_epoch,
        "rebalance_schema_version": entry.get("schema_version"),
        "screen_source_generated_at": screen.get("generated_at"),
        "screen_source_run_at": screen.get("run_at"),
        "selection_fingerprint": _selection_fingerprint(
            selection, trade_cost_pct=entry.get("trade_cost_pct")
        ),
        "rebalance_logged_at": entry.get("logged_at"),
    }


def _knob_epoch_identity(epoch: dict[str, Any]) -> tuple[Any, ...]:
    """Capital/knob identity used to stratify lessons (not screen epoch)."""
    return (
        epoch.get("track_id"),
        epoch.get("capital_epoch"),
        epoch.get("knob_epoch_started_at"),
        epoch.get("rebalance_schema_version"),
        epoch.get("selection_fingerprint"),
    )


def _index_rebalance_passes_by_trade_id(
    entries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for trade in entry.get("trades") or []:
            if not isinstance(trade, dict):
                continue
            tid = str(trade.get("id") or "").strip()
            if tid:
                by_id[tid] = entry
    return by_id


def _join_exit_pass(
    *,
    trade: dict[str, Any],
    by_trade_id: dict[str, dict[str, Any]],
    entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Join a closed sell to its exit rebalance_log pass. Fail closed → None."""
    tid = str(trade.get("id") or "").strip()
    if tid and tid in by_trade_id:
        return by_trade_id[tid]
    ticker = str(trade.get("ticker") or "").strip()
    acted = _parse_dt(trade.get("acted_at"))
    if not ticker or acted is None:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for logged in entry.get("trades") or []:
            if not isinstance(logged, dict):
                continue
            if str(logged.get("side") or "") != "sell":
                continue
            if str(logged.get("ticker") or "").strip() != ticker:
                continue
            logged_at = _parse_dt(logged.get("acted_at"))
            if logged_at is None:
                continue
            delta = abs((logged_at - acted).total_seconds())
            if delta <= JOIN_WINDOW_SECONDS and (best is None or delta < best[0]):
                best = (delta, entry)
    return best[1] if best else None


def _in_buy_set_at_exit(entry: dict[str, Any] | None, ticker: str) -> bool | None:
    """Exit-pass buy-tier by raw screen signal (not holdings membership)."""
    if entry is None:
        return None
    for row in entry.get("screen_buy_tier") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker") or "").strip() != ticker:
            continue
        return str(row.get("signal") or "") in BUY_SIGNALS
    # Absent from screen_buy_tier entirely → not in buy set at exit.
    return False


def _entry_at_for_sell(
    trades: list[dict[str, Any]],
    *,
    ticker: str,
    exit_at: str,
) -> str | None:
    """Most recent buy for ticker at or before exit (episode open)."""
    exit_dt = _parse_dt(exit_at)
    best: str | None = None
    best_dt: datetime | None = None
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        if trade.get("side") != "buy":
            continue
        if str(trade.get("ticker") or "").strip() != ticker:
            continue
        acted = str(trade.get("acted_at") or "")
        acted_dt = _parse_dt(acted)
        if acted_dt is None:
            continue
        if exit_dt is not None and acted_dt > exit_dt:
            continue
        if best_dt is None or acted_dt >= best_dt:
            best_dt = acted_dt
            best = acted
    return best


def _hold_days(entry_at: str | None, exit_at: str | None) -> int | None:
    start = _parse_dt(entry_at)
    end = _parse_dt(exit_at)
    if start is None or end is None:
        return None
    return max(0, (end - start).days)


def _exit_shadow_index(
    shadow: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(shadow, dict):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for record in shadow.get("records") or []:
        if not isinstance(record, dict):
            continue
        tid = str(record.get("trade_id") or "").strip()
        ticker = str(record.get("ticker") or "").strip()
        if tid:
            index[f"id:{tid}"] = record
        if ticker:
            # Prefer first-episode / newest by exited_at when colliding.
            key = f"ticker:{ticker}"
            prior = index.get(key)
            if prior is None:
                index[key] = record
                continue
            prior_ex = _parse_dt(prior.get("exited_at"))
            this_ex = _parse_dt(record.get("exited_at"))
            if this_ex is not None and (prior_ex is None or this_ex >= prior_ex):
                index[key] = record
    return index


def _shadow_for_sell(
    index: dict[str, dict[str, Any]],
    *,
    trade_id: str,
    ticker: str,
) -> dict[str, Any] | None:
    if trade_id and f"id:{trade_id}" in index:
        return index[f"id:{trade_id}"]
    return index.get(f"ticker:{ticker}")


def _post_exit_7d(shadow: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(shadow, dict):
        return None
    for cp in shadow.get("checkpoints") or []:
        if not isinstance(cp, dict):
            continue
        if int(cp.get("days_after") or 0) == 7:
            ret = cp.get("return_since_exit_pct")
            peak = cp.get("peak_since_exit_pct")
            out: dict[str, Any] = {"days_after": 7}
            if ret is not None:
                out["return_since_exit_pct"] = ret
                # Keep pct-point form for digest readers when shadow stores fraction.
                try:
                    out["post_exit_7d_return_pct"] = round(float(ret) * 100.0, 2)
                except (TypeError, ValueError):
                    pass
            if peak is not None:
                out["peak_since_exit_pct"] = peak
                try:
                    out["peak_since_exit_return_pct"] = round(float(peak) * 100.0, 2)
                except (TypeError, ValueError):
                    pass
            return out
    return None


def _current_epoch_from_log(
    entries: list[dict[str, Any]],
    *,
    fund_created_at: str | None,
) -> dict[str, Any] | None:
    acted = [e for e in entries if isinstance(e, dict) and e.get("acted")]
    if not acted:
        acted = [e for e in entries if isinstance(e, dict)]
    if not acted:
        return None
    latest = max(acted, key=lambda e: str(e.get("logged_at") or ""))
    try:
        return _epoch_key_from_pass(latest, fund_created_at=fund_created_at)
    except KeyError:
        return None


def _lesson_status(
    epoch: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> str:
    if epoch is None:
        return "epoch_unknown"
    if current is None:
        return "epoch_joined"
    if _knob_epoch_identity(epoch) == _knob_epoch_identity(current):
        return "current_epoch"
    return "older_epoch"


def _n200_timing_cues(n200: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(n200, dict):
        return [
            {
                "cue_id": "n200_missing",
                "lane": "timing",
                "claim": "N200 tech-timing observe store missing",
                "why_matters": "Entry/exit lever scoreboards are the closest sealed timing cue",
                "falsify_or_promote": "Next ops-monitor refresh writes n200_tech_timing_observe.json",
                "severity": "info",
                "population": "n200_observe",
                "registration_id": N200_REGISTRATION_ID,
                "epoch_required": True,
                "evidence": {
                    "registration_id": N200_REGISTRATION_ID,
                    "population_note": "N200 observe ≠ FTSE control closed sells",
                },
            }
        ]
    levers = n200.get("per_lever_scoreboards") or {}
    entry_v = str(levers.get("entry_verdict") or "unknown")
    exit_v = str(levers.get("exit_verdict") or "unknown")
    volume = n200.get("volume_gate") or {}
    registration_id = str(n200.get("registration_id") or N200_REGISTRATION_ID)
    return [
        {
            "cue_id": "n200_entry_exit_levers",
            "lane": "timing",
            "claim": (
                f"N200 ({registration_id}) entry lever {entry_v}; exit lever {exit_v} "
                "(population ≠ FTSE control closed sells)"
            ),
            "why_matters": (
                "Per-lever fair-cost verdicts are independent of path P&L — "
                "exit lose + entry win is a factory timing signal, not a book rewrite"
            ),
            "falsify_or_promote": (
                "Volume gate met + thicker closed cohort; promote only via sealed "
                "observe design (F8), never mid-flight knob apply"
            ),
            "severity": "info",
            "population": "n200_observe",
            "registration_id": registration_id,
            "epoch_required": True,
            "evidence": {
                "registration_id": registration_id,
                "population_note": "N200 observe ≠ FTSE control closed sells",
                "entry_verdict": entry_v,
                "exit_verdict": exit_v,
                "volume_gate_met": volume.get("met"),
                "completed_entry_episodes": n200.get("completed_entry_episodes"),
            },
        }
    ]


def _exit_timing_cues(rollup: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One readiness cue for FTSE focus tracks (collapse clone-per-track)."""
    if not isinstance(rollup, dict):
        return []
    tracks = rollup.get("tracks") or {}
    if not isinstance(tracks, dict):
        return []
    focus_ids = (
        CONTROL_TRACK_ID,
        "buy_tier_level_dca",
        "ai_judgment_fair",
    )
    gaps_by_track: dict[str, Any] = {}
    any_ready = False
    for track_id in focus_ids:
        row = tracks.get(track_id)
        if not isinstance(row, dict):
            continue
        readiness = row.get("readiness") or {}
        ready = bool(readiness.get("ready_for_probability_analysis"))
        any_ready = any_ready or ready
        gaps_by_track[track_id] = {
            "ready_for_probability_analysis": ready,
            "hold_closed_count": readiness.get("hold_closed_count"),
            "swap_closed_count": readiness.get("swap_closed_count"),
            "gaps": list(readiness.get("gaps") or [])[:3],
        }
    if not gaps_by_track:
        return []
    ready_n = sum(
        1 for v in gaps_by_track.values() if v.get("ready_for_probability_analysis")
    )
    return [
        {
            "cue_id": "exit_timing_ready_ftse",
            "lane": "timing",
            "claim": (
                f"FTSE exit-timing readiness: {ready_n}/{len(gaps_by_track)} tracks "
                f"ready (control/DCA/AI-judgment)"
            ),
            "why_matters": "Live hold/swap probability stays parked until closed cohorts mature",
            "falsify_or_promote": (
                "ready_for_probability_analysis true with hold+swap closed targets; "
                "else keep collecting (L117/N25)"
            ),
            "severity": "info",
            "population": "ftse_paper_tracks",
            "epoch_required": True,
            "evidence": {
                "tracks": gaps_by_track,
                "any_ready": any_ready,
            },
        }
    ]


def _exit_shadow_cues(rollup: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(rollup, dict):
        return []
    tracks = rollup.get("tracks") or {}
    if not isinstance(tracks, dict):
        return []
    control = tracks.get(CONTROL_TRACK_ID) or {}
    if not isinstance(control, dict):
        return []
    closed = int(control.get("closed_count") or 0)
    open_n = int(control.get("open_count") or 0)
    return [
        {
            "cue_id": "exit_shadow_control",
            "lane": "timing",
            "claim": (f"Control exit-shadow closed={closed} open={open_n} (auto-tune still gated)"),
            "why_matters": "Post-exit path answers 'too early?' only after closed shadows thicken",
            "falsify_or_promote": "N25: ≥15 closed exits/track before exit-shadow→knob path",
            "severity": "info",
            "population": "ftse_control_buy_tier_level",
            "epoch_required": True,
            "evidence": {
                "track_id": CONTROL_TRACK_ID,
                "closed_count": closed,
                "open_count": open_n,
                "by_exit_kind": control.get("by_exit_kind"),
            },
        }
    ]


def _archive_near_miss_cue(review: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(review, dict):
        return []
    readiness = review.get("readiness") or {}
    ready = bool(readiness.get("ready_for_probability_analysis"))
    return [
        {
            "cue_id": "archive_near_miss_prior",
            "lane": "timing",
            "claim": (
                f"Archive near-miss readiness="
                f"{'true' if ready else 'false'} "
                f"(hold_closed={readiness.get('hold_closed_count')}, "
                f"swap_closed={readiness.get('swap_closed_count')})"
            ),
            "why_matters": "Offline priors exist for experiment design when live swap closed=0",
            "falsify_or_promote": (
                "L121: do not blend archive rates into live probability; priors only"
            ),
            "severity": "info",
            "population": "archive_near_miss",
            "epoch_required": True,
            "evidence": {
                "ready_for_probability_analysis": ready,
                "hold_closed_count": readiness.get("hold_closed_count"),
                "swap_closed_count": readiness.get("swap_closed_count"),
                "generated_at": review.get("generated_at"),
                "caveat": "L121 denominators not interchangeable with live",
                "population_note": "Offline archive epoch ≠ FTSE control paper closes",
            },
        }
    ]


def _control_closed_sells(
    fund: dict[str, Any] | None,
    *,
    buy_set_now: set[str],
    loser_index: dict[str, dict[str, Any]],
    rebalance_entries: list[dict[str, Any]],
    exit_shadow: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return sell buckets, selection skeleton rows, selection cues, epoch summary.

    Fail-closed: rows without a rebalance_log epoch join are tagged
    ``epoch_unknown`` and excluded from selection experiment-cue claims.
    Default cue population = current capital/knob epoch only.
    """
    trades = list((fund or {}).get("trades") or [])
    fund_cfg = (fund or {}).get("config") if isinstance((fund or {}).get("config"), dict) else {}
    fund_created_at = str(fund_cfg.get("created_at") or "") or None
    by_trade_id = _index_rebalance_passes_by_trade_id(rebalance_entries)
    current_epoch = _current_epoch_from_log(
        rebalance_entries, fund_created_at=fund_created_at
    )
    shadow_index = _exit_shadow_index(exit_shadow)

    closed_sells: list[dict[str, Any]] = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        if trade.get("side") != "sell":
            continue
        if not trade.get("position_closed"):
            continue
        ticker = str(trade.get("ticker") or "").strip()
        if not ticker:
            continue
        try:
            price = float(trade.get("price") or 0.0)
            avg = float(trade.get("avg_cost_at_exit") or 0.0)
        except (TypeError, ValueError):
            price, avg = 0.0, 0.0
        realized = _pct(price, avg)
        acted = str(trade.get("acted_at") or "")
        trade_id = str(trade.get("id") or "").strip()
        entry_at = _entry_at_for_sell(trades, ticker=ticker, exit_at=acted)
        hold_days = _hold_days(entry_at, acted)
        exit_pass = _join_exit_pass(
            trade=trade, by_trade_id=by_trade_id, entries=rebalance_entries
        )
        epoch: dict[str, Any] | None = None
        epoch_join_ok = False
        if exit_pass is not None:
            try:
                epoch = _epoch_key_from_pass(exit_pass, fund_created_at=fund_created_at)
                epoch_join_ok = True
            except KeyError:
                epoch = None
                epoch_join_ok = False
        lesson = _lesson_status(epoch if epoch_join_ok else None, current_epoch)
        in_at_exit = _in_buy_set_at_exit(exit_pass, ticker) if epoch_join_ok else None
        in_now = ticker in buy_set_now
        shadow = _shadow_for_sell(shadow_index, trade_id=trade_id, ticker=ticker)
        loser = loser_index.get(ticker)
        row: dict[str, Any] = {
            "ticker": ticker,
            "name": trade.get("name"),
            "trade_id": trade_id or None,
            "entry_at": entry_at,
            "exit_at": acted,
            "hold_days": hold_days,
            "exit_kind": (shadow or {}).get("exit_kind"),
            "realized_pct": realized,
            "realized_basis": "price_vs_avg_cost_at_exit",
            # Dual-stamp: do not treat today's buy-set as exit-time selection.
            "in_buy_set_at_exit": in_at_exit,
            "in_buy_set_now": in_now,
            "still_in_buy_set": in_now,  # legacy alias — means *now*, not at exit
            "still_in_buy_set_as_of": "latest_json_now",
            "exit_note": trade.get("note"),
            "loser_card": loser,
            "post_exit_7d": _post_exit_7d(shadow),
            "epoch": epoch,
            "epoch_join_ok": epoch_join_ok,
            "epoch_lesson_status": lesson,
            "feeds_n205": True,
            "observe_only": True,
            "sealed": False,
        }
        closed_sells.append(row)

    closed_sells.sort(key=lambda r: str(r.get("exit_at") or ""), reverse=True)

    # Experiment-cue population: current epoch + successful join only.
    cue_rows = [
        r
        for r in closed_sells
        if r.get("epoch_join_ok") and r.get("epoch_lesson_status") == "current_epoch"
    ]
    unknown_n = sum(1 for r in closed_sells if not r.get("epoch_join_ok"))
    older_n = sum(1 for r in closed_sells if r.get("epoch_lesson_status") == "older_epoch")
    current_n = len(cue_rows)

    buckets = Counter(_bucket_realized(r.get("realized_pct")) for r in cue_rows)
    left_at_exit = sum(1 for r in cue_rows if r.get("in_buy_set_at_exit") is False)
    still_at_exit = sum(1 for r in cue_rows if r.get("in_buy_set_at_exit") is True)
    still_now = sum(1 for r in cue_rows if r.get("in_buy_set_now"))
    left_now = sum(1 for r in cue_rows if not r.get("in_buy_set_now"))

    epoch_summary = {
        "current_epoch": current_epoch,
        "joined_count": sum(1 for r in closed_sells if r.get("epoch_join_ok")),
        "epoch_unknown_count": unknown_n,
        "current_epoch_count": current_n,
        "older_epoch_count": older_n,
        "cue_population": "current_epoch_only",
        "fail_closed": True,
        "widen_gate": WIDEN_GATE,
    }

    summary = {
        "track_id": CONTROL_TRACK_ID,
        "closed_sell_count": len(closed_sells),
        "cue_closed_sell_count": current_n,
        "realized_pct_buckets": dict(buckets),
        "realized_pct_buckets_scope": "current_epoch_joined_only",
        "in_buy_set_at_exit_count": still_at_exit,
        "left_buy_set_at_exit_count": left_at_exit,
        "in_buy_set_now_count": still_now,
        "left_buy_set_now_count": left_now,
        # Legacy fields retained but labeled as *now* (not exit-time).
        "still_in_buy_set_count": still_now,
        "left_buy_set_count": left_now,
        "with_loser_card_count": sum(1 for r in cue_rows if r.get("loser_card")),
        "epoch": epoch_summary,
        "note": (
            "Realized % is price vs avg_cost_at_exit on control closed sells — "
            "not a sealed selection scoreboard (N205 stays not_now). "
            "Buckets/cues use current-epoch joined rows only; epoch_unknown dropped. "
            "in_buy_set_now is today's latest.json — not exit-time selection."
        ),
    }

    if len(closed_sells) <= SELECTION_FULL_LIST_MAX:
        skeleton = list(closed_sells)
    else:
        skeleton = closed_sells[:SELECTION_SAMPLE_LIMIT]

    cues: list[dict[str, Any]] = []
    if cue_rows:
        epoch_ev = {
            "epoch_key": current_epoch,
            "cue_population": "current_epoch_only",
            "closed_sell_count_all": len(closed_sells),
            "closed_sell_count_cue": current_n,
            "epoch_unknown_excluded": unknown_n,
            "older_epoch_excluded": older_n,
        }
        cues.append(
            {
                "cue_id": "selection_buy_set_at_exit",
                "lane": "selection",
                "claim": (
                    f"Control closed sells (current epoch): {still_at_exit} in buy set "
                    f"at exit, {left_at_exit} left buy set at exit "
                    f"(n={current_n}; now still={still_now}/left={left_now})"
                ),
                "why_matters": (
                    "Exit-pass screen signal separates selection/thesis exits from "
                    "later screen drift; in_buy_set_now is labeled separately"
                ),
                "falsify_or_promote": (
                    "Thicken skeleton → sealed N205 selection lever only after "
                    "design review; no capital promote from this feed"
                ),
                "severity": "info",
                "population": "ftse_control_buy_tier_level",
                "epoch_required": True,
                "epoch_lesson_status": "current_epoch",
                "evidence": {
                    **epoch_ev,
                    "in_buy_set_at_exit_count": still_at_exit,
                    "left_buy_set_at_exit_count": left_at_exit,
                    "in_buy_set_now_count": still_now,
                    "left_buy_set_now_count": left_now,
                    "realized_pct_buckets": summary["realized_pct_buckets"],
                    "sample_tickers": [r["ticker"] for r in cue_rows[:5]],
                },
            }
        )
        ge10 = int(buckets.get("ge_10") or 0)
        le_m10 = int(buckets.get("le_m10") or 0)
        cues.append(
            {
                "cue_id": "selection_realized_buckets",
                "lane": "selection",
                "claim": (
                    f"Control realized buckets (current epoch): ≥10%={ge10}, "
                    f"≤−10%={le_m10} (of {current_n} joined closed sells)"
                ),
                "why_matters": "Crude well/poorly split for experiment backlog triage",
                "falsify_or_promote": (
                    "Replace with fair-cost episode % + peer rank when N205 seals"
                ),
                "severity": "info",
                "population": "ftse_control_buy_tier_level",
                "epoch_required": True,
                "epoch_lesson_status": "current_epoch",
                "evidence": {
                    **epoch_ev,
                    "realized_pct_buckets": summary["realized_pct_buckets"],
                },
            }
        )
    elif closed_sells and unknown_n == len(closed_sells):
        cues.append(
            {
                "cue_id": "selection_epoch_join_failed",
                "lane": "selection",
                "claim": (
                    f"All {len(closed_sells)} control closed sells failed rebalance_log "
                    "epoch join — selection cues abstained (fail closed)"
                ),
                "why_matters": "Unlabeled closes must not pool into experiment claims",
                "falsify_or_promote": "Repair rebalance_log coverage; do not invent epochs",
                "severity": "warn",
                "population": "ftse_control_buy_tier_level",
                "epoch_required": True,
                "epoch_lesson_status": "epoch_unknown",
                "evidence": {
                    "closed_sell_count": len(closed_sells),
                    "epoch_unknown_count": unknown_n,
                    "fail_closed": True,
                },
            }
        )
    elif closed_sells and current_n == 0:
        cues.append(
            {
                "cue_id": "selection_no_current_epoch_sells",
                "lane": "selection",
                "claim": (
                    f"No current-epoch control closed sells for cues "
                    f"(all={len(closed_sells)}, older={older_n}, unknown={unknown_n})"
                ),
                "why_matters": "Default cue population is current capital/knob epoch only",
                "falsify_or_promote": "Tag older-epoch rows as historical; do not unlabeled-pool",
                "severity": "info",
                "population": "ftse_control_buy_tier_level",
                "epoch_required": True,
                "epoch_lesson_status": "older_epoch",
                "evidence": {
                    "closed_sell_count": len(closed_sells),
                    "older_epoch_count": older_n,
                    "epoch_unknown_count": unknown_n,
                    "current_epoch": current_epoch,
                },
            }
        )
    else:
        cues.append(
            {
                "cue_id": "selection_no_closed_sells",
                "lane": "selection",
                "claim": "No control position_closed sells found for selection skeleton",
                "why_matters": "N205 feed needs ended control lifecycles",
                "falsify_or_promote": "Wait for closed sells on buy_tier_level",
                "severity": "info",
                "population": "ftse_control_buy_tier_level",
                "epoch_required": True,
            }
        )
    return summary, skeleton, cues, epoch_summary


def _hub_feed(
    timing_cues: list[dict[str, Any]],
    selection_cues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Contract for daily-hub Push/Explore (sibling-owned product ship)."""
    explore: list[dict[str, Any]] = []
    push: list[dict[str, Any]] = []
    for cue in [*timing_cues, *selection_cues]:
        card = {
            "id": f"post_sell:{cue.get('cue_id')}",
            "lane": "explore",
            "not_today": True,
            "claim": cue.get("claim"),
            "why_matters": cue.get("why_matters"),
            "falsify_or_promote": cue.get("falsify_or_promote"),
            "source": "post_sell_cue_digest",
            "cue_lane": cue.get("lane"),
            "population": cue.get("population"),
            "registration_id": cue.get("registration_id"),
            "epoch_lesson_status": cue.get("epoch_lesson_status"),
        }
        # Push only when a cue maps to a live human gate — v0: none (Explore default).
        explore.append(card)
    return {
        "schema_version": 1,
        "note": (
            "Sibling hub ship consumes explore_candidates (≤2) / push_candidates. "
            "Default lane is Explore (learning); Push stays empty unless a cue maps "
            "to a live human judgment gate."
        ),
        "explore_candidates": explore[:8],
        "push_candidates": push,
    }


def build_post_sell_cue_digest(
    *,
    data_dir: Path | None = None,
    paper_root: Path | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir or DEFAULT_DATA_DIR)
    paper_root = Path(paper_root or DEFAULT_PAPER_ROOT)
    control_dir = paper_root / CONTROL_TRACK_ID

    n200 = _safe_read(data_dir / "n200_tech_timing_observe.json")
    exit_timing = _safe_read(paper_root / "learning_tracks_exit_timing.json")
    exit_shadow_rollup = _safe_read(paper_root / "learning_tracks_exit_shadow.json")
    near_miss_review = _safe_read(data_dir / "exit_timing_near_miss_review.json")
    latest = _safe_read(data_dir / "latest.json")
    loser_cards = _safe_read(data_dir / "loser_snapshot_cards.json")
    fund = _safe_read(control_dir / "automated_fund.json")
    exit_shadow = _safe_read(control_dir / "exit_shadow.json")
    rebalance_entries = load_rebalance_log(control_dir)

    buy_set_now = _buy_set_from_latest(latest)
    loser_index = _loser_card_index(loser_cards)

    timing_cues = [
        *_n200_timing_cues(n200),
        *_exit_timing_cues(exit_timing),
        *_exit_shadow_cues(exit_shadow_rollup),
        *_archive_near_miss_cue(near_miss_review),
    ]
    sell_summary, skeleton, selection_cues, epoch_summary = _control_closed_sells(
        fund,
        buy_set_now=buy_set_now,
        loser_index=loser_index,
        rebalance_entries=rebalance_entries,
        exit_shadow=exit_shadow,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utcnow().isoformat(),
        "observe_only": True,
        "influences_live": False,
        "auto_fixable": False,
        "package": "M",
        "ops_doc": OPS_DOC,
        "product_claim": (
            "Cue readiness + selection skeleton feed — not full episode assessment "
            "and not cross-epoch truth"
        ),
        "learning_question": (
            "What timing + selection experiment cues follow from closed episodes "
            "and existing observe instruments without sealing N205 or applying knobs?"
        ),
        "widen_gate": WIDEN_GATE,
        "epoch": epoch_summary,
        "inputs": {
            "n200_tech_timing_observe": n200 is not None,
            "learning_tracks_exit_timing": exit_timing is not None,
            "learning_tracks_exit_shadow": exit_shadow_rollup is not None,
            "exit_timing_near_miss_review": near_miss_review is not None,
            "control_fund": fund is not None,
            "control_rebalance_log_entries": len(rebalance_entries),
            "control_exit_shadow": exit_shadow is not None,
            "latest_buy_set_size": len(buy_set_now),
            "loser_card_index_size": len(loser_index),
        },
        "timing_cues": timing_cues,
        "selection_cues": selection_cues,
        "control_closed_sells": sell_summary,
        "selection_postmortem_skeleton": {
            "schema_version": 2,
            "feeds": "N205",
            "sealed": False,
            "observe_only": True,
            "track_id": CONTROL_TRACK_ID,
            "row_limit": SELECTION_SAMPLE_LIMIT,
            "row_count": len(skeleton),
            "rows": skeleton,
            "note": (
                "Thin ended-control-lifecycle rows for N205 design feed — "
                "not a sealed selection scoreboard. Each row carries epoch key "
                "from rebalance_log join (or epoch_unknown). "
                "in_buy_set_now is today's latest.json; use in_buy_set_at_exit "
                "for exit-time selection."
            ),
        },
        "hub_feed": _hub_feed(timing_cues, selection_cues),
        "sunday_nest": {
            "checklist_id": "sunday-post-sell-cues",
            "neighbor": "sunday-ai-path-scoreboard",
            "summary": (
                f"{len(timing_cues)} timing + {len(selection_cues)} selection cues; "
                f"control closed sells={sell_summary.get('closed_sell_count', 0)}; "
                f"current-epoch cue n={sell_summary.get('cue_closed_sell_count', 0)}; "
                f"epoch_unknown={epoch_summary.get('epoch_unknown_count', 0)}"
            ),
            "artifact": str(DEFAULT_STORE_PATH),
        },
        "non_goals": [
            "no --apply",
            "no new paper track",
            "no N205 seal",
            "no LLM episode debriefs",
            "no archive→live probability blend",
            "no hard veto",
            "no widen beyond FTSE control until epoch keys on every cue/row",
        ],
    }


def ops_findings_from_digest(payload: dict[str, Any]) -> list[dict[str, Any]]:
    timing_n = len(payload.get("timing_cues") or [])
    selection_n = len(payload.get("selection_cues") or [])
    closed = ((payload.get("control_closed_sells") or {}).get("closed_sell_count")) or 0
    cue_n = ((payload.get("control_closed_sells") or {}).get("cue_closed_sell_count"))
    if cue_n is None:
        cue_n = closed
    skeleton_n = ((payload.get("selection_postmortem_skeleton") or {}).get("row_count")) or 0
    epoch = payload.get("epoch") or {}
    unknown = epoch.get("epoch_unknown_count")
    summary = (
        f"Observe digest refreshed: {timing_n} timing cues, {selection_n} selection cues, "
        f"{closed} control closed sells (current-epoch cue n={cue_n}, "
        f"skeleton {skeleton_n}"
        + (f", epoch_unknown={unknown}" if unknown is not None else "")
        + "). Hub Explore feed via hub_feed; no auto-fix / no N205 seal; "
        "widen gated on epoch keys."
    )
    return [
        {
            "severity": "info",
            "category": CATEGORY,
            "title": FINDING_TITLE,
            "summary": summary,
            "auto_fixable": False,
        }
    ]


def refresh_post_sell_cue_digest(
    *,
    data_dir: Path | None = None,
    paper_root: Path | None = None,
    store_path: Path | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    payload = build_post_sell_cue_digest(data_dir=data_dir, paper_root=paper_root)
    if persist:
        path = Path(store_path or DEFAULT_STORE_PATH)
        write_json(path, payload, compact=True)
    return payload


__all__ = [
    "CATEGORY",
    "DEFAULT_STORE_PATH",
    "FINDING_TITLE",
    "STORE_FAILED_TITLE",
    "WIDEN_GATE",
    "build_post_sell_cue_digest",
    "ops_findings_from_digest",
    "refresh_post_sell_cue_digest",
]
