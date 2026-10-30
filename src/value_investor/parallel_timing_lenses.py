"""Parallel timing lenses on shared candidates (L652) — observe-only.

Owner-locked v0 catalog (2026-10-30): buy trio + sell learning quartet +
``sell_mechanical_leave`` baseline (beside the sell cap, not a fifth hero).

Extends ``cue_consumer_mft`` / ``entry_blind`` trails — not a sealed zoo, not
Package L, never ``influences_live``. Fixed-stake v0 per lens episode; favourite
vs late lenses keep separate marks. Concurrence companion is observe-only (N241
risk sizing parked).

Stub vs live join (v0):
- ``buy_news_improve_path`` — **live join** to L650 ``entry_news_polarity``
  (``improvement_path`` cue; never a hard filter).
- Other buy/sell fire rules — **deterministic stubs** over judgment/screen cites
  and exit_reason maps; LLM optional later.
- Outcome gaps (``had_but_ignored`` / ``missing_that_might_help``) — deterministic
  cite-aware stubs at enter/abandon/close; not Package L auto-tune.

See ``docs/ops/parallel-timing-lenses.md``.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 1
INSTRUMENT_ID = "parallel_timing_lenses"
DEFERRED_ID = "L652"
PACKAGE = "M"
STORE_FILENAME = "parallel_timing_lenses.json"
OPS_DOC = "docs/ops/parallel-timing-lenses.md"
FINDING_TITLE = "Parallel timing lenses (observe)"
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_STORE_PATH = DEFAULT_DATA_DIR / STORE_FILENAME

FIXED_STAKE_UNITS = 100.0
# Days peers keep looking after favourite entry / spawn before durable abandon.
LOOK_TIMEOUT_DAYS = 21
# Concurrence window around favourite entry (calendar days, inclusive).
CONCURRENCE_WINDOW_DAYS = 1
MAX_CANDIDATES = 80
MAX_TRAIL_EVENTS = 40

# --- Owner-locked v0 catalog -------------------------------------------------

BUY_LENS_IDS: tuple[str, ...] = (
    "buy_support_bounce",
    "buy_news_improve_path",
    "buy_cheap_trend_confirm",
)
SELL_LEARNING_LENS_IDS: tuple[str, ...] = (
    "sell_target_reached",
    "sell_thesis_break",
    "sell_tech_break",
    "sell_failed_breakout",
)
SELL_BASELINE_LENS_ID = "sell_mechanical_leave"
SELL_CAP = 4  # learning lenses only; mechanical sits beside the cap

LENS_CATALOG: dict[str, dict[str, Any]] = {
    "buy_support_bounce": {
        "side": "buy",
        "role": "learning",
        "name": "Support / technical bounce",
        "intent": "Enter on plausible support bounce / sensible technical setup",
        "rule_kind": "stub_technical",
        "stub_note": "Deterministic stub on B2 / price_vs_sma200_pct / timing_score cites",
    },
    "buy_news_improve_path": {
        "side": "buy",
        "role": "learning",
        "name": "News-polarity improvement path",
        "intent": "Enter when PIT news cites improvement_path as cue (not hard filter)",
        "rule_kind": "live_join_l650",
        "stub_note": "Live join to entry_news_polarity.label == improvement_path",
    },
    "buy_cheap_trend_confirm": {
        "side": "buy",
        "role": "learning",
        "name": "Cheap + trend confirmation",
        "intent": "Enter when cheapness holds and trend/momentum confirms",
        "rule_kind": "stub_cheap_trend",
        "stub_note": "Deterministic stub: B1 cheapness cite + positive timing/mom cite",
    },
    "sell_target_reached": {
        "side": "sell",
        "role": "learning",
        "name": "Target reached",
        "intent": "Exit when declared target / realism band is hit",
        "rule_kind": "stub_exit_map",
        "stub_note": "Stub: exit_reason / S-cell target cite",
    },
    "sell_thesis_break": {
        "side": "sell",
        "role": "learning",
        "name": "Thesis break / identity",
        "intent": "Exit on identity / thesis break evidence",
        "rule_kind": "stub_exit_map",
        "stub_note": "Stub: identity_break_* exit_reason map",
    },
    "sell_tech_break": {
        "side": "sell",
        "role": "learning",
        "name": "Technical break / support fail",
        "intent": "Exit when support / trend structure fails",
        "rule_kind": "stub_tech_exit",
        "stub_note": "Stub: adverse SMA / support-fail cite; distinct from failed_breakout",
    },
    "sell_failed_breakout": {
        "side": "sell",
        "role": "learning",
        "name": "Failed breakout / resistance reject",
        "intent": (
            "Take profits when price fails to break resistance ahead of give-back; "
            "may arm observe-only buy watch at next level (no auto-fill)"
        ),
        "rule_kind": "stub_failed_breakout",
        "stub_note": (
            "Stub: resistance-reject cite; arms buy_watch observe cue only — never auto-fill"
        ),
        "arms_buy_watch": True,
    },
    "sell_mechanical_leave": {
        "side": "sell",
        "role": "baseline",
        "name": "Mechanical leave (baseline, not lens hero)",
        "intent": "Max-days / leave-buy-cohort / hard-rule exit — scoreboard baseline",
        "rule_kind": "baseline_mechanical",
        "stub_note": "Always recorded beside sell learning cap; never elevated as hero",
    },
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _utcnow()).isoformat()


def _day(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:10]


def _parse_day(value: Any) -> datetime | None:
    day = _day(value)
    if not day:
        return None
    try:
        return datetime.fromisoformat(day).replace(tzinfo=UTC)
    except ValueError:
        return None


def _safe_read(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def catalog_payload() -> dict[str, Any]:
    return {
        "buy_learning": list(BUY_LENS_IDS),
        "sell_learning": list(SELL_LEARNING_LENS_IDS),
        "sell_baseline": SELL_BASELINE_LENS_ID,
        "sell_learning_cap": SELL_CAP,
        "lenses": {lid: dict(meta) for lid, meta in LENS_CATALOG.items()},
        "owner_locked_at": "2026-10-30",
        "note": (
            "Sell learning cap=4; sell_mechanical_leave sits beside the cap as baseline. "
            "No Package L; influences_live=false."
        ),
    }


def candidate_id(*, ticker: str, side: str, source_key: str) -> str:
    raw = f"{ticker}|{side}|{source_key}".encode()
    return "ptl_" + hashlib.sha1(raw).hexdigest()[:16]


def _empty_outcome_review() -> dict[str, Any]:
    return {
        "had_but_ignored": {"text": None, "cites": []},
        "missing_that_might_help": {"text": None, "cites": []},
        "scored_at": None,
        "influences_live": False,
    }


def _lens_shell(
    lens_id: str,
    *,
    role: str,
    status: str = "looking",
) -> dict[str, Any]:
    meta = LENS_CATALOG[lens_id]
    return {
        "lens_id": lens_id,
        "name": meta["name"],
        "side": meta["side"],
        "role": role,  # favourite | peer | baseline
        "catalog_role": meta["role"],  # learning | baseline
        "status": status,  # looking | entered | abandoned | baseline_recorded
        "rule_kind": meta["rule_kind"],
        "stub_note": meta["stub_note"],
        "trail": [],
        "episode": {
            "fixed_stake_units": FIXED_STAKE_UNITS,
            "sizing_mode": "fixed_stake",
            "scoreboard_unit": "fair_cost_episode_pct",
            "entry_at": None,
            "exit_at": None,
            "fair_cost_episode_pct": None,
            "drawdown_depth": None,
            "drawdown_duration_days": None,
            "independent_of_favourite_nav": True,
            "influences_live": False,
        },
        "outcome_review": _empty_outcome_review(),
        "buy_watch": None,
        "influences_live": False,
    }


def _append_trail(
    lens: dict[str, Any],
    *,
    day: str,
    action: str,
    cites: list[str] | None = None,
    note: str | None = None,
) -> None:
    trail = list(lens.get("trail") or [])
    # One keep_looking per day max; enter/abandon always append.
    if action == "keep_looking" and trail:
        last = trail[-1]
        if (
            isinstance(last, dict)
            and last.get("action") == "keep_looking"
            and _day(last.get("day")) == day
        ):
            return
    event = {
        "day": day,
        "action": action,  # keep_looking | enter | abandon | baseline
        "cites": [str(c).strip() for c in (cites or []) if str(c).strip()][:8],
        "note": note,
        "influences_live": False,
    }
    trail.append(event)
    lens["trail"] = trail[-MAX_TRAIL_EVENTS:]


def _judgment_cites(evidence: dict[str, Any] | None) -> list[str]:
    out: list[str] = []
    if not isinstance(evidence, dict):
        return out
    judgment = evidence.get("judgment_in_the_round")
    if not isinstance(judgment, dict):
        return out
    for side in ("buy", "sell"):
        block = judgment.get(side) or {}
        if not isinstance(block, dict):
            continue
        for cell_id, cell in block.items():
            if not isinstance(cell, dict):
                continue
            for cite in cell.get("cites") or []:
                text = str(cite).strip()
                if text:
                    out.append(f"{cell_id}:{text}")
    return out[:20]


def _entry_detail(evidence: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        return {}
    detail = evidence.get("entry_detail")
    return detail if isinstance(detail, dict) else {}


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _polarity_label(ctx: dict[str, Any]) -> str | None:
    pol = ctx.get("entry_news_polarity")
    if isinstance(pol, dict):
        label = str(pol.get("label") or "").strip()
        return label or None
    return None


def evaluate_buy_lens_fire(
    lens_id: str,
    *,
    ctx: dict[str, Any],
) -> tuple[bool, list[str], str]:
    """Return (fires, cites, note). Deterministic stubs + L650 live join."""
    cites = list(ctx.get("judgment_cites") or [])
    detail = ctx.get("entry_detail") if isinstance(ctx.get("entry_detail"), dict) else {}
    sma = _finite_float(detail.get("price_vs_sma200_pct"))
    timing = _finite_float(detail.get("timing_score"))
    mom = _finite_float(detail.get("mom_12_1") or detail.get("momentum_12_1"))
    families = str(detail.get("passed_families") or "").lower()
    cheap = "cheapness" in families or "cheap" in families
    # Also infer cheapness from judgment cite text.
    if not cheap and any("cheap" in c.lower() for c in cites):
        cheap = True
    tech_cited = any(
        c.startswith("B2:") or "timing_score" in c or "price_vs_sma200" in c for c in cites
    )

    if lens_id == "buy_news_improve_path":
        label = _polarity_label(ctx)
        if label == "improvement_path":
            return (
                True,
                [f"entry_news_polarity.label={label}", "join=l650_live"],
                "live_join_l650_improvement_path",
            )
        if label:
            return (
                False,
                [f"entry_news_polarity.label={label}", "join=l650_live"],
                "l650_label_not_improvement_path",
            )
        return (False, ["entry_news_polarity=missing"], "l650_missing_fail_closed")

    if lens_id == "buy_support_bounce":
        fire_cites: list[str] = []
        if sma is not None:
            fire_cites.append(f"price_vs_sma200_pct={sma}")
        if timing is not None:
            fire_cites.append(f"timing_score={timing}")
        if tech_cited:
            fire_cites.extend([c for c in cites if c.startswith("B2:")][:3])
        # Near/below SMA200 with non-negative timing, or B2 technicals cited.
        near_support = sma is not None and -12.0 <= sma <= 3.0
        timing_ok = timing is not None and timing >= 0.0
        if (near_support and (timing_ok or timing is None)) or (tech_cited and near_support):
            return (True, fire_cites or ["stub_support_bounce"], "stub_support_bounce_fire")
        if tech_cited and timing_ok:
            return (True, fire_cites or cites[:3], "stub_b2_timing_fire")
        return (False, fire_cites or ["stub_support_bounce_no_fire"], "stub_support_bounce_wait")

    if lens_id == "buy_cheap_trend_confirm":
        fire_cites = []
        if cheap:
            fire_cites.append("cheapness=true")
        if timing is not None:
            fire_cites.append(f"timing_score={timing}")
        if mom is not None:
            fire_cites.append(f"mom_12_1={mom}")
        trend_ok = (timing is not None and timing > 0) or (mom is not None and mom > 0)
        if cheap and trend_ok:
            return (True, fire_cites, "stub_cheap_trend_fire")
        if cheap and tech_cited:
            # Soft confirm via B2 when mom fields absent.
            return (True, fire_cites + ["B2_soft_confirm"], "stub_cheap_b2_soft_confirm")
        return (False, fire_cites or ["stub_cheap_trend_wait"], "stub_cheap_trend_wait")

    return (False, [], f"unknown_buy_lens:{lens_id}")


def evaluate_sell_lens_fire(
    lens_id: str,
    *,
    ctx: dict[str, Any],
) -> tuple[bool, list[str], str]:
    """Sell learning/baseline fire evaluation (stubs + exit_reason map)."""
    exit_reason = str(ctx.get("exit_reason") or "").strip().lower()
    cites = list(ctx.get("judgment_cites") or [])
    detail = ctx.get("entry_detail") if isinstance(ctx.get("entry_detail"), dict) else {}
    sma = _finite_float(detail.get("price_vs_sma200_pct"))
    ret = _finite_float(ctx.get("return_pct"))

    if lens_id == SELL_BASELINE_LENS_ID:
        mechanical = (
            exit_reason in {"hold_trading_days", "max_days", "leave_buy_cohort", "leave_buy_tier"}
            or exit_reason.startswith("leave_buy")
            or exit_reason.startswith("hold_trading")
        )
        if mechanical or not exit_reason:
            # Baseline always recordable at close; prefer mechanical reasons.
            note = "baseline_mechanical" if mechanical else "baseline_recorded_at_close"
            return (True, [f"exit_reason={exit_reason or 'unknown'}"], note)
        return (False, [f"exit_reason={exit_reason}"], "non_mechanical_exit")

    if lens_id == "sell_thesis_break":
        if "identity_break" in exit_reason or "thesis" in exit_reason:
            return (True, [f"exit_reason={exit_reason}"], "stub_thesis_break_map")
        if any("identity" in c.lower() or "thesis" in c.lower() for c in cites):
            return (
                True,
                [c for c in cites if "identity" in c.lower() or "thesis" in c.lower()][:3],
                "stub_thesis_cite",
            )
        return (False, [], "stub_thesis_wait")

    if lens_id == "sell_target_reached":
        if "target" in exit_reason or "realism" in exit_reason:
            return (True, [f"exit_reason={exit_reason}"], "stub_target_map")
        if ret is not None and ret >= 0.15:
            return (True, [f"return_pct={ret}", "stub_target_band"], "stub_target_return_band")
        if any("target" in c.lower() or "S4:" in c or "S3:" in c for c in cites):
            return (
                True,
                [c for c in cites if "target" in c.lower() or c.startswith("S")][:3],
                "stub_target_cite",
            )
        return (False, [], "stub_target_wait")

    if lens_id == "sell_tech_break":
        if "support" in exit_reason or "tech_break" in exit_reason or "sma" in exit_reason:
            return (True, [f"exit_reason={exit_reason}"], "stub_tech_break_map")
        if sma is not None and sma <= -8.0:
            return (True, [f"price_vs_sma200_pct={sma}"], "stub_support_fail")
        if any("support" in c.lower() or "sma" in c.lower() for c in cites):
            return (
                True,
                [c for c in cites if "support" in c.lower() or "sma" in c.lower()][:3],
                "stub_tech_cite",
            )
        return (False, [], "stub_tech_break_wait")

    if lens_id == "sell_failed_breakout":
        if "failed_breakout" in exit_reason or "resistance" in exit_reason:
            return (True, [f"exit_reason={exit_reason}"], "stub_failed_breakout_map")
        # Stub: profitable exit that is not mechanical / identity / deep support fail
        # → treat as possible resistance reject take-profit.
        mechanical = exit_reason.startswith("hold_") or exit_reason.startswith("leave_buy")
        identity = "identity_break" in exit_reason
        deep_fail = sma is not None and sma <= -8.0
        if ret is not None and ret > 0 and not mechanical and not identity and not deep_fail:
            return (
                True,
                [f"return_pct={ret}", "stub_resistance_reject"],
                "stub_failed_breakout_take_profit",
            )
        if any("resistance" in c.lower() or "breakout" in c.lower() for c in cites):
            return (
                True,
                [c for c in cites if "resistance" in c.lower() or "breakout" in c.lower()][:3],
                "stub_failed_breakout_cite",
            )
        return (False, [], "stub_failed_breakout_wait")

    return (False, [], f"unknown_sell_lens:{lens_id}")


def _arm_buy_watch(*, ticker: str, day: str, cites: list[str]) -> dict[str, Any]:
    """Observe-only next-level buy watch — never auto-fill."""
    return {
        "armed": True,
        "armed_at": day,
        "ticker": ticker,
        "level_note": "next_support_or_reentry_level",
        "cites": cites[:5],
        "auto_fill": False,
        "influences_live": False,
        "note": (
            "sell_failed_breakout may arm observe buy watch only; "
            "requires separate buy-lens fire + durable trail before any fill"
        ),
    }


def build_outcome_review(
    lens: dict[str, Any],
    *,
    ctx: dict[str, Any],
    asof: str,
) -> dict[str, Any]:
    """Deterministic had_but_ignored / missing_that_might_help stubs (+ cites)."""
    available: list[str] = []
    used = {str(c) for ev in (lens.get("trail") or []) for c in (ev.get("cites") or [])}
    polarity = _polarity_label(ctx)
    if polarity:
        available.append(f"entry_news_polarity.label={polarity}")
    for cite in ctx.get("judgment_cites") or []:
        available.append(str(cite))
    detail = ctx.get("entry_detail") if isinstance(ctx.get("entry_detail"), dict) else {}
    for key in ("price_vs_sma200_pct", "timing_score", "passed_families", "mom_12_1"):
        if detail.get(key) is not None:
            available.append(f"{key}={detail.get(key)}")

    ignored = [c for c in available if c not in used][:5]
    had_text = None
    if ignored:
        had_text = f"PIT info available but not weighted by {lens.get('lens_id')}: " + "; ".join(
            ignored[:3]
        )
    elif available:
        had_text = "No clear unused PIT cite beyond what the lens trail already recorded."

    missing: list[str] = []
    missing_text_bits: list[str] = []
    if polarity in (None, "no_usable_news"):
        missing.append("entry_news_polarity=no_usable_news")
        missing_text_bits.append("no usable PIT news polarity (L650)")
    if not any(str(c).startswith("B1:") for c in (ctx.get("judgment_cites") or [])):
        missing.append("judgment.B1=missing")
        missing_text_bits.append("no B1 cheapness cite")
    if not any(str(c).startswith("B2:") for c in (ctx.get("judgment_cites") or [])):
        missing.append("judgment.B2=missing")
        missing_text_bits.append("no B2 technical cite")
    if detail.get("price_vs_sma200_pct") is None and lens.get("lens_id") in {
        "buy_support_bounce",
        "sell_tech_break",
        "sell_failed_breakout",
    }:
        missing.append("price_vs_sma200_pct=missing")
        missing_text_bits.append("no marked SMA/support level")

    missing_text = None
    if missing_text_bits:
        missing_text = "Missing info that might have helped: " + "; ".join(missing_text_bits)
    else:
        missing_text = "No obvious missing PIT field for this stub review."

    return {
        "had_but_ignored": {"text": had_text, "cites": ignored},
        "missing_that_might_help": {"text": missing_text, "cites": missing},
        "scored_at": asof,
        "influences_live": False,
        "package_l": False,
        "note": "Deterministic stub review — Package M alignment only; never auto-tunes knobs",
    }


def compute_concurrence(
    lenses: list[dict[str, Any]],
    *,
    favourite_entry_at: str | None,
    window_days: int = CONCURRENCE_WINDOW_DAYS,
) -> dict[str, Any]:
    """Observe-only concurrence count in a short window around favourite entry."""
    fav_day = _parse_day(favourite_entry_at)
    agreeing: list[str] = []
    if fav_day is not None:
        for lens in lenses:
            if lens.get("catalog_role") == "baseline":
                continue
            if lens.get("status") != "entered":
                continue
            entry = _parse_day((lens.get("episode") or {}).get("entry_at"))
            if entry is None:
                continue
            delta = abs((entry.date() - fav_day.date()).days)
            if delta <= int(window_days):
                agreeing.append(str(lens.get("lens_id")))
    return {
        "window_days": int(window_days),
        "favourite_entry_at": _day(favourite_entry_at),
        "count": len(agreeing),
        "lens_ids": agreeing,
        "influences_live": False,
        "risk_sizing": False,
        "n241": "not_now",
        "note": (
            "Observe companion only — count + which lenses within window of favourite entry; "
            "late hits outside window do not inflate concurrence; never sizes risk (N241)"
        ),
    }


def _mark_enter(
    lens: dict[str, Any],
    *,
    day: str,
    cites: list[str],
    note: str,
    ticker: str,
) -> None:
    lens["status"] = "entered"
    ep = dict(lens.get("episode") or {})
    ep["entry_at"] = day
    ep["fixed_stake_units"] = FIXED_STAKE_UNITS
    ep["influences_live"] = False
    ep["independent_of_favourite_nav"] = True
    lens["episode"] = ep
    _append_trail(lens, day=day, action="enter", cites=cites, note=note)
    if lens.get("lens_id") == "sell_failed_breakout":
        lens["buy_watch"] = _arm_buy_watch(ticker=ticker, day=day, cites=cites)


def _mark_abandon(lens: dict[str, Any], *, day: str, note: str) -> None:
    lens["status"] = "abandoned"
    _append_trail(lens, day=day, action="abandon", cites=[], note=note)


def _advance_looking_lenses(
    candidate: dict[str, Any],
    *,
    asof_day: str,
    ctx: dict[str, Any],
) -> None:
    side = str(candidate.get("side") or "buy")
    ticker = str(candidate.get("ticker") or "")
    spawned = _parse_day(candidate.get("spawned_at"))
    asof_dt = _parse_day(asof_day) or _utcnow()
    fav_entry = _day(candidate.get("favourite_entry_at"))

    for lens in candidate.get("lenses") or []:
        if not isinstance(lens, dict):
            continue
        status = str(lens.get("status") or "")
        if status not in {"looking", "baseline_recorded"}:
            continue
        if status == "baseline_recorded":
            continue

        lens_id = str(lens.get("lens_id") or "")
        if side == "buy":
            fires, cites, note = evaluate_buy_lens_fire(lens_id, ctx=ctx)
        else:
            fires, cites, note = evaluate_sell_lens_fire(lens_id, ctx=ctx)

        if fires:
            _mark_enter(lens, day=asof_day, cites=cites, note=note, ticker=ticker)
            if lens.get("role") == "favourite" and not fav_entry:
                candidate["favourite_entry_at"] = asof_day
                fav_entry = asof_day
            continue

        # Timeout abandon relative to favourite entry (or spawn if favourite not yet in).
        anchor = _parse_day(fav_entry) or spawned
        if anchor is not None:
            age = (asof_dt.date() - anchor.date()).days
            if age >= LOOK_TIMEOUT_DAYS:
                _mark_abandon(
                    lens,
                    day=asof_day,
                    note=f"look_timeout_{LOOK_TIMEOUT_DAYS}d",
                )
                continue
        _append_trail(
            lens,
            day=asof_day,
            action="keep_looking",
            cites=cites,
            note=note,
        )


def _ensure_favourite(candidate: dict[str, Any], *, asof_day: str, ctx: dict[str, Any]) -> None:
    """Pick favourite among learning lenses: first firer on asof, else default first id."""
    if candidate.get("favourite_lens_id"):
        return
    side = str(candidate.get("side") or "buy")
    learning = [
        lens
        for lens in (candidate.get("lenses") or [])
        if isinstance(lens, dict) and lens.get("catalog_role") == "learning"
    ]
    firers: list[dict[str, Any]] = []
    for lens in learning:
        lid = str(lens.get("lens_id") or "")
        if side == "buy":
            fires, cites, note = evaluate_buy_lens_fire(lid, ctx=ctx)
        else:
            fires, cites, note = evaluate_sell_lens_fire(lid, ctx=ctx)
        if fires:
            firers.append({"lens": lens, "cites": cites, "note": note})
    if firers:
        chosen = firers[0]["lens"]
        chosen["role"] = "favourite"
        for other in learning:
            if other is not chosen and other.get("role") != "baseline":
                other["role"] = "peer"
        candidate["favourite_lens_id"] = chosen["lens_id"]
        _mark_enter(
            chosen,
            day=asof_day,
            cites=firers[0]["cites"],
            note=firers[0]["note"],
            ticker=str(candidate.get("ticker") or ""),
        )
        candidate["favourite_entry_at"] = asof_day
        return

    # No firer yet — designate default favourite still looking.
    default_id = BUY_LENS_IDS[0] if side == "buy" else SELL_LEARNING_LENS_IDS[0]
    for lens in learning:
        if lens.get("lens_id") == default_id:
            lens["role"] = "favourite"
            candidate["favourite_lens_id"] = default_id
        elif lens.get("catalog_role") == "learning":
            lens["role"] = "peer"


def _score_outcomes(candidate: dict[str, Any], *, asof: str, ctx: dict[str, Any]) -> None:
    for lens in candidate.get("lenses") or []:
        if not isinstance(lens, dict):
            continue
        status = str(lens.get("status") or "")
        review = lens.get("outcome_review") if isinstance(lens.get("outcome_review"), dict) else {}
        if review.get("scored_at"):
            continue
        if status in {"entered", "abandoned", "baseline_recorded"}:
            # Attach marks for entered lenses when source episode has return.
            if status == "entered" and ctx.get("return_pct") is not None:
                ep = dict(lens.get("episode") or {})
                # Only attach shared close mark to favourite; late lenses keep null
                # until their own episode closes (do not back-label favourite NAV).
                if lens.get("role") == "favourite":
                    ep["fair_cost_episode_pct"] = _finite_float(ctx.get("return_pct"))
                    ep["exit_at"] = _day(ctx.get("exit_at")) or asof
                lens["episode"] = ep
            lens["outcome_review"] = build_outcome_review(lens, ctx=ctx, asof=asof)


def spawn_buy_candidate(
    *,
    ticker: str,
    source_episode_id: str,
    source: str,
    entry_at: str | None,
    evidence: dict[str, Any] | None,
    polarity: dict[str, Any] | None,
    asof: str,
) -> dict[str, Any]:
    cid = candidate_id(
        ticker=ticker, side="buy", source_key=source_episode_id or entry_at or ticker
    )
    lenses = [_lens_shell(lid, role="peer") for lid in BUY_LENS_IDS]
    candidate = {
        "candidate_id": cid,
        "ticker": ticker,
        "side": "buy",
        "shared_from": source,
        "source_episode_id": source_episode_id,
        "spawned_at": _day(entry_at) or _day(asof),
        "favourite_lens_id": None,
        "favourite_entry_at": None,
        "lenses": lenses,
        "concurrence": None,
        "influences_live": False,
        "observe_only": True,
        "package": PACKAGE,
    }
    ctx = {
        "judgment_cites": _judgment_cites(evidence),
        "entry_detail": _entry_detail(evidence),
        "entry_news_polarity": polarity,
    }
    asof_day = _day(entry_at) or _day(asof) or _day(_iso())
    assert asof_day is not None
    _ensure_favourite(candidate, asof_day=asof_day, ctx=ctx)
    _advance_looking_lenses(candidate, asof_day=asof_day, ctx=ctx)
    candidate["concurrence"] = compute_concurrence(
        list(candidate.get("lenses") or []),
        favourite_entry_at=candidate.get("favourite_entry_at"),
    )
    return candidate


def spawn_sell_candidate(
    *,
    ticker: str,
    source_episode_id: str,
    source: str,
    exit_at: str | None,
    exit_reason: str | None,
    return_pct: float | None,
    evidence: dict[str, Any] | None,
    asof: str,
) -> dict[str, Any]:
    cid = candidate_id(
        ticker=ticker, side="sell", source_key=source_episode_id or exit_at or ticker
    )
    lenses = [_lens_shell(lid, role="peer") for lid in SELL_LEARNING_LENS_IDS]
    baseline = _lens_shell(SELL_BASELINE_LENS_ID, role="baseline", status="looking")
    lenses.append(baseline)
    candidate = {
        "candidate_id": cid,
        "ticker": ticker,
        "side": "sell",
        "shared_from": source,
        "source_episode_id": source_episode_id,
        "spawned_at": _day(exit_at) or _day(asof),
        "favourite_lens_id": None,
        "favourite_entry_at": None,
        "lenses": lenses,
        "concurrence": None,
        "influences_live": False,
        "observe_only": True,
        "package": PACKAGE,
        "sell_learning_cap": SELL_CAP,
        "baseline_beside_cap": SELL_BASELINE_LENS_ID,
    }
    ctx = {
        "judgment_cites": _judgment_cites(evidence),
        "entry_detail": _entry_detail(evidence),
        "exit_reason": exit_reason,
        "return_pct": return_pct,
        "exit_at": exit_at,
    }
    asof_day = _day(exit_at) or _day(asof) or _day(_iso())
    assert asof_day is not None

    # Record mechanical baseline beside cap when it applies.
    fires_b, cites_b, note_b = evaluate_sell_lens_fire(SELL_BASELINE_LENS_ID, ctx=ctx)
    if fires_b:
        baseline["status"] = "baseline_recorded"
        baseline["role"] = "baseline"
        _append_trail(baseline, day=asof_day, action="baseline", cites=cites_b, note=note_b)

    _ensure_favourite(candidate, asof_day=asof_day, ctx=ctx)
    _advance_looking_lenses(candidate, asof_day=asof_day, ctx=ctx)
    _score_outcomes(candidate, asof=asof_day, ctx=ctx)
    candidate["concurrence"] = compute_concurrence(
        [lens for lens in lenses if lens.get("catalog_role") == "learning"],
        favourite_entry_at=candidate.get("favourite_entry_at"),
    )
    return candidate


def _episode_samples(
    mft: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(mft, dict):
        return [], []
    open_eps = [
        e
        for e in (mft.get("open_lab_episodes_sample") or mft.get("open_episodes_sample") or [])
        if isinstance(e, dict)
    ]
    closed_eps = [
        e
        for e in (mft.get("closed_lab_episodes_sample") or mft.get("closed_episodes_sample") or [])
        if isinstance(e, dict)
    ]
    # Some payloads nest samples under episode_walker.
    walker = mft.get("episode_walker") if isinstance(mft.get("episode_walker"), dict) else {}
    if not open_eps:
        open_eps = [e for e in (walker.get("open_episodes_sample") or []) if isinstance(e, dict)]
    if not closed_eps:
        closed_eps = [
            e for e in (walker.get("closed_episodes_sample") or []) if isinstance(e, dict)
        ]
    return open_eps, closed_eps


def _polarity_for_ticker(
    *,
    ticker: str,
    entry_at: str | None,
    data_dir: Path,
    cards_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    card = cards_by_ticker.get(ticker)
    if isinstance(card, dict) and isinstance(card.get("entry_news_polarity"), dict):
        return card["entry_news_polarity"]
    try:
        from value_investor.entry_news_polarity import derive_entry_news_polarity

        return derive_entry_news_polarity(
            ticker=ticker,
            entry_at=entry_at,
            data_dir=data_dir,
        )
    except Exception:  # noqa: BLE001 — observe fail-closed
        return {"label": "no_usable_news", "join_ok": False, "influences_live": False, "cites": []}


def build_parallel_timing_lenses(
    *,
    data_dir: Path | None = None,
    mft: dict[str, Any] | None = None,
    entry_blind: dict[str, Any] | None = None,
    prior: dict[str, Any] | None = None,
    asof: str | None = None,
) -> dict[str, Any]:
    """Build / advance L652 store from MFT + entry_blind shared candidates."""
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    when = asof or _iso()
    asof_day = _day(when) or _day(_iso())
    assert asof_day is not None

    mft_payload = mft if mft is not None else _safe_read(root / "cue_consumer_mft_observe.json")
    blind = (
        entry_blind
        if entry_blind is not None
        else _safe_read(root / "entry_blind_review_queue.json")
    )
    prior_store = prior if prior is not None else _safe_read(root / STORE_FILENAME)

    prior_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(prior_store, dict):
        for row in prior_store.get("candidates") or []:
            if isinstance(row, dict) and row.get("candidate_id"):
                prior_by_id[str(row["candidate_id"])] = dict(row)

    cards_by_ticker: dict[str, dict[str, Any]] = {}
    if isinstance(blind, dict):
        for card in blind.get("active") or []:
            if isinstance(card, dict) and card.get("ticker"):
                cards_by_ticker[str(card["ticker"])] = card

    open_eps, closed_eps = _episode_samples(mft_payload)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Buy slates from open lab episodes (shared stock-choice candidates).
    for ep in open_eps:
        ticker = str(ep.get("ticker") or "").strip()
        if not ticker:
            continue
        eid = str(ep.get("episode_id") or "").strip() or f"{ticker}:{ep.get('entry_run_at')}"
        cid = candidate_id(ticker=ticker, side="buy", source_key=eid)
        if cid in seen:
            continue
        seen.add(cid)
        evidence = ep.get("evidence") if isinstance(ep.get("evidence"), dict) else {}
        polarity = _polarity_for_ticker(
            ticker=ticker,
            entry_at=str(ep.get("entry_run_at") or ep.get("decision_ts") or ""),
            data_dir=root,
            cards_by_ticker=cards_by_ticker,
        )
        if cid in prior_by_id:
            candidate = prior_by_id[cid]
            ctx = {
                "judgment_cites": _judgment_cites(evidence),
                "entry_detail": _entry_detail(evidence),
                "entry_news_polarity": polarity,
            }
            _advance_looking_lenses(candidate, asof_day=asof_day, ctx=ctx)
            candidate["concurrence"] = compute_concurrence(
                list(candidate.get("lenses") or []),
                favourite_entry_at=candidate.get("favourite_entry_at"),
            )
        else:
            candidate = spawn_buy_candidate(
                ticker=ticker,
                source_episode_id=eid,
                source="cue_consumer_mft",
                entry_at=str(ep.get("entry_run_at") or ep.get("decision_ts") or asof_day),
                evidence=evidence,
                polarity=polarity,
                asof=asof_day,
            )
        candidates.append(candidate)

    # Also seed from entry_blind lab cards not already covered (extend trail).
    for card in cards_by_ticker.values():
        if card.get("population") not in {None, "lab"} and card.get("book_id") not in {
            None,
            "cue_consumer_mft",
            "lab",
        }:
            # Prefer lab; still allow if book_tag mentions lab / MFT.
            tag = str(card.get("book_tag") or card.get("book_id") or "").lower()
            if "lab" not in tag and "mft" not in tag and "cue" not in tag:
                continue
        ticker = str(card.get("ticker") or "").strip()
        if not ticker:
            continue
        eid = str(card.get("review_id") or card.get("family_id") or "").strip() or ticker
        cid = candidate_id(ticker=ticker, side="buy", source_key=eid)
        # Skip if same ticker already has an active buy slate from MFT.
        if any(c.get("ticker") == ticker and c.get("side") == "buy" for c in candidates):
            continue
        if cid in seen:
            continue
        seen.add(cid)
        polarity = (
            card.get("entry_news_polarity")
            if isinstance(card.get("entry_news_polarity"), dict)
            else None
        )
        if cid in prior_by_id:
            candidate = prior_by_id[cid]
            ctx = {
                "judgment_cites": [],
                "entry_detail": {},
                "entry_news_polarity": polarity,
            }
            _advance_looking_lenses(candidate, asof_day=asof_day, ctx=ctx)
            candidate["concurrence"] = compute_concurrence(
                list(candidate.get("lenses") or []),
                favourite_entry_at=candidate.get("favourite_entry_at"),
            )
        else:
            candidate = spawn_buy_candidate(
                ticker=ticker,
                source_episode_id=eid,
                source="entry_blind",
                entry_at=str(card.get("entry_at") or asof_day),
                evidence=None,
                polarity=polarity,
                asof=asof_day,
            )
        candidates.append(candidate)

    # Sell slates from closed lab episodes.
    for ep in closed_eps:
        ticker = str(ep.get("ticker") or "").strip()
        if not ticker:
            continue
        eid = str(ep.get("episode_id") or "").strip() or f"{ticker}:exit:{ep.get('exit_run_at')}"
        cid = candidate_id(ticker=ticker, side="sell", source_key=eid)
        if cid in seen:
            continue
        seen.add(cid)
        evidence = ep.get("evidence") if isinstance(ep.get("evidence"), dict) else {}
        if cid in prior_by_id:
            candidate = prior_by_id[cid]
            ctx = {
                "judgment_cites": _judgment_cites(evidence),
                "entry_detail": _entry_detail(evidence),
                "exit_reason": ep.get("exit_reason"),
                "return_pct": ep.get("return_pct"),
                "exit_at": ep.get("exit_run_at"),
            }
            _advance_looking_lenses(candidate, asof_day=asof_day, ctx=ctx)
            _score_outcomes(candidate, asof=asof_day, ctx=ctx)
            candidate["concurrence"] = compute_concurrence(
                [
                    lens
                    for lens in (candidate.get("lenses") or [])
                    if isinstance(lens, dict) and lens.get("catalog_role") == "learning"
                ],
                favourite_entry_at=candidate.get("favourite_entry_at"),
            )
        else:
            candidate = spawn_sell_candidate(
                ticker=ticker,
                source_episode_id=eid,
                source="cue_consumer_mft",
                exit_at=str(ep.get("exit_run_at") or asof_day),
                exit_reason=str(ep.get("exit_reason") or "") or None,
                return_pct=_finite_float(ep.get("return_pct")),
                evidence=evidence,
                asof=asof_day,
            )
        candidates.append(candidate)

    # Preserve prior candidates not refreshed this cycle (cap).
    for cid, row in prior_by_id.items():
        if cid in seen:
            continue
        candidates.append(row)
        seen.add(cid)

    candidates = candidates[:MAX_CANDIDATES]

    # Summary rollups
    buy_n = sum(1 for c in candidates if c.get("side") == "buy")
    sell_n = sum(1 for c in candidates if c.get("side") == "sell")
    looking = entered = abandoned = 0
    concurrence_counts: list[int] = []
    buy_watch_armed = 0
    for c in candidates:
        conc = c.get("concurrence") if isinstance(c.get("concurrence"), dict) else None
        if conc and conc.get("count") is not None:
            concurrence_counts.append(int(conc["count"]))
        for lens in c.get("lenses") or []:
            if not isinstance(lens, dict):
                continue
            st = str(lens.get("status") or "")
            if st == "looking":
                looking += 1
            elif st == "entered":
                entered += 1
            elif st == "abandoned":
                abandoned += 1
            if isinstance(lens.get("buy_watch"), dict) and lens["buy_watch"].get("armed"):
                buy_watch_armed += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "instrument_id": INSTRUMENT_ID,
        "deferred_id": DEFERRED_ID,
        "generated_at": when if "T" in str(when) else _iso(),
        "asof": asof_day,
        "observe_only": True,
        "influences_live": False,
        "package": PACKAGE,
        "ops_doc": OPS_DOC,
        "fixed_stake_units": FIXED_STAKE_UNITS,
        "look_timeout_days": LOOK_TIMEOUT_DAYS,
        "concurrence_window_days": CONCURRENCE_WINDOW_DAYS,
        "catalog": catalog_payload(),
        "stub_vs_live": {
            "buy_news_improve_path": "live_join_l650_entry_news_polarity",
            "other_buy_lenses": "deterministic_stub",
            "sell_learning_lenses": "deterministic_stub_exit_map",
            "sell_mechanical_leave": "baseline_beside_cap",
            "outcome_review": "deterministic_stub_gaps",
            "llm": "optional_later",
        },
        "summary": {
            "candidate_count": len(candidates),
            "buy_candidates": buy_n,
            "sell_candidates": sell_n,
            "lenses_looking": looking,
            "lenses_entered": entered,
            "lenses_abandoned": abandoned,
            "buy_watch_armed": buy_watch_armed,
            "concurrence_mean": (
                round(sum(concurrence_counts) / len(concurrence_counts), 3)
                if concurrence_counts
                else None
            ),
            "concurrence_samples": len(concurrence_counts),
        },
        "candidates": candidates,
        "product_claim": (
            "Parallel timing/policy lenses on shared MFT/entry_blind candidates — "
            "favourite may enter while peers keep looking daily; fixed-stake v0; "
            "concurrence observe companion; influences_live=false; no Package L / no sealed zoo"
        ),
        "learning_question": (
            "Do competing buy/sell timing lenses on a shared candidate improve MoM "
            "lever learning (stock choice vs buy/sell timing vs strategy) versus a "
            "single-thesis path — without live influence?"
        ),
    }


def refresh_parallel_timing_lenses(
    *,
    data_dir: Path | None = None,
    store_path: Path | None = None,
    persist: bool = True,
    asof: str | None = None,
) -> dict[str, Any]:
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    dest = Path(store_path) if store_path is not None else (root / STORE_FILENAME)
    payload = build_parallel_timing_lenses(data_dir=root, asof=asof)
    if persist:
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_json(dest, payload, compact=False)
        payload["path"] = str(dest)
    return payload


def bind_parallel_timing_lenses_summary(
    item: dict[str, Any],
    *,
    store: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach a compact observe summary for entry_blind cards (no outcome leakage)."""
    ticker = str(item.get("ticker") or "").strip()
    summary: dict[str, Any] = {
        "present": False,
        "influences_live": False,
        "observe_only": True,
        "ops_doc": OPS_DOC,
    }
    if not ticker or not isinstance(store, dict):
        item["parallel_timing_lenses"] = summary
        return item
    match = None
    for row in store.get("candidates") or []:
        if not isinstance(row, dict):
            continue
        if row.get("side") != "buy":
            continue
        if str(row.get("ticker") or "") == ticker:
            match = row
            break
    if match is None:
        item["parallel_timing_lenses"] = summary
        return item
    lenses = [lens for lens in (match.get("lenses") or []) if isinstance(lens, dict)]
    fav = str(match.get("favourite_lens_id") or "") or None
    conc = match.get("concurrence") if isinstance(match.get("concurrence"), dict) else {}
    summary.update(
        {
            "present": True,
            "candidate_id": match.get("candidate_id"),
            "favourite_lens_id": fav,
            "favourite_entry_at": match.get("favourite_entry_at"),
            "lens_statuses": {
                str(lens.get("lens_id")): str(lens.get("status"))
                for lens in lenses
                if lens.get("lens_id")
            },
            "concurrence_count": conc.get("count"),
            "concurrence_lens_ids": list(conc.get("lens_ids") or []),
            "looking_n": sum(1 for lens in lenses if lens.get("status") == "looking"),
            "entered_n": sum(1 for lens in lenses if lens.get("status") == "entered"),
            "abandoned_n": sum(1 for lens in lenses if lens.get("status") == "abandoned"),
        }
    )
    item["parallel_timing_lenses"] = summary
    return item


def ops_findings_from_parallel_timing_lenses(
    payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return [
            {
                "severity": "info",
                "category": "research",
                "title": FINDING_TITLE,
                "summary": (
                    "Parallel timing lenses store missing — fail-closed until refresh. "
                    "influences_live=false; Package M; see "
                    f"{OPS_DOC}."
                ),
                "auto_fixable": False,
            }
        ]
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"L652 parallel timing lenses: candidates={summary.get('candidate_count', 0)} "
                f"(buy={summary.get('buy_candidates', 0)} sell={summary.get('sell_candidates', 0)}); "
                f"looking={summary.get('lenses_looking', 0)} entered={summary.get('lenses_entered', 0)} "
                f"abandoned={summary.get('lenses_abandoned', 0)}; "
                f"concurrence_mean={summary.get('concurrence_mean')}; "
                f"buy_watch_armed={summary.get('buy_watch_armed', 0)}. "
                "Observe-only fixed-stake v0; concurrence companion only (N241 not_now); "
                "no Package L / no sealed zoo. "
                f"See {OPS_DOC}."
            ),
            "auto_fixable": False,
        }
    ]


__all__ = [
    "BUY_LENS_IDS",
    "CONCURRENCE_WINDOW_DAYS",
    "DEFERRED_ID",
    "DEFAULT_DATA_DIR",
    "DEFAULT_STORE_PATH",
    "FINDING_TITLE",
    "FIXED_STAKE_UNITS",
    "INSTRUMENT_ID",
    "LENS_CATALOG",
    "LOOK_TIMEOUT_DAYS",
    "OPS_DOC",
    "SCHEMA_VERSION",
    "SELL_BASELINE_LENS_ID",
    "SELL_CAP",
    "SELL_LEARNING_LENS_IDS",
    "STORE_FILENAME",
    "bind_parallel_timing_lenses_summary",
    "build_outcome_review",
    "build_parallel_timing_lenses",
    "catalog_payload",
    "compute_concurrence",
    "evaluate_buy_lens_fire",
    "evaluate_sell_lens_fire",
    "ops_findings_from_parallel_timing_lenses",
    "refresh_parallel_timing_lenses",
    "spawn_buy_candidate",
    "spawn_sell_candidate",
]
