"""Observe-only post-sell cue digest + selection postmortem skeleton (package M).

Learning question: can closed-episode timing + selection cues from inventory
already collected (N200 levers, exit-timing/shadow readiness, control closed
sells, archive near-miss) surface experiment backlog signals without sealing
N205 or applying knobs?

Produces ``docs/data/post_sell_cue_digest.json`` from daily ops-monitor.
Never changes books or knobs (``auto_fixable=False``).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import write_json

SCHEMA_VERSION = 1
FINDING_TITLE = "Post-sell cue digest (observe)"
STORE_FAILED_TITLE = "Post-sell cue digest observe failed"
DEFAULT_STORE_PATH = Path("docs/data/post_sell_cue_digest.json")
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
CONTROL_TRACK_ID = "buy_tier_level"
CATEGORY = "research"
SELECTION_SAMPLE_LIMIT = 12
OPS_DOC = "docs/ops/post-sell-cue-digest.md"

BUY_SIGNALS = frozenset({"buy", "strong_buy"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_read(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


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
            }
        ]
    levers = n200.get("per_lever_scoreboards") or {}
    entry_v = str(levers.get("entry_verdict") or "unknown")
    exit_v = str(levers.get("exit_verdict") or "unknown")
    volume = n200.get("volume_gate") or {}
    cues: list[dict[str, Any]] = [
        {
            "cue_id": "n200_entry_exit_levers",
            "lane": "timing",
            "claim": f"N200 entry lever {entry_v}; exit lever {exit_v}",
            "why_matters": (
                "Per-lever fair-cost verdicts are independent of path P&L — "
                "exit lose + entry win is a factory timing signal, not a book rewrite"
            ),
            "falsify_or_promote": (
                "Volume gate met + thicker closed cohort; promote only via sealed "
                "observe design (F8), never mid-flight knob apply"
            ),
            "severity": "info",
            "evidence": {
                "entry_verdict": entry_v,
                "exit_verdict": exit_v,
                "volume_gate_met": volume.get("met"),
                "completed_entry_episodes": n200.get("completed_entry_episodes"),
            },
        }
    ]
    return cues


def _exit_timing_cues(rollup: dict[str, Any] | None) -> list[dict[str, Any]]:
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
    cues: list[dict[str, Any]] = []
    for track_id in focus_ids:
        row = tracks.get(track_id)
        if not isinstance(row, dict):
            continue
        readiness = row.get("readiness") or {}
        ready = bool(readiness.get("ready_for_probability_analysis"))
        gaps = list(readiness.get("gaps") or [])[:3]
        cues.append(
            {
                "cue_id": f"exit_timing_ready:{track_id}",
                "lane": "timing",
                "claim": (
                    f"{track_id} exit-timing "
                    f"{'ready' if ready else 'not ready'} for probability analysis"
                ),
                "why_matters": "Live hold/swap probability stays parked until closed cohorts mature",
                "falsify_or_promote": (
                    "ready_for_probability_analysis true with hold+swap closed targets; "
                    "else keep collecting (L117/N25)"
                ),
                "severity": "info",
                "evidence": {
                    "track_id": track_id,
                    "ready_for_probability_analysis": ready,
                    "hold_closed_count": readiness.get("hold_closed_count"),
                    "swap_closed_count": readiness.get("swap_closed_count"),
                    "gaps": gaps,
                },
            }
        )
    return cues


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
            "evidence": {
                "ready_for_probability_analysis": ready,
                "hold_closed_count": readiness.get("hold_closed_count"),
                "swap_closed_count": readiness.get("swap_closed_count"),
                "generated_at": review.get("generated_at"),
                "caveat": "L121 denominators not interchangeable with live",
            },
        }
    ]


def _control_closed_sells(
    fund: dict[str, Any] | None,
    *,
    buy_set: set[str],
    loser_index: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return sell buckets, selection skeleton rows, and selection cues."""
    trades = list((fund or {}).get("trades") or [])
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
        loser = loser_index.get(ticker)
        row = {
            "ticker": ticker,
            "name": trade.get("name"),
            "exit_at": acted,
            "realized_pct": realized,
            "realized_basis": "price_vs_avg_cost_at_exit",
            "still_in_buy_set": ticker in buy_set,
            "exit_note": trade.get("note"),
            "loser_card": loser,
            "feeds_n205": True,
            "observe_only": True,
            "sealed": False,
        }
        closed_sells.append(row)

    closed_sells.sort(key=lambda r: str(r.get("exit_at") or ""), reverse=True)
    buckets = Counter(_bucket_realized(r.get("realized_pct")) for r in closed_sells)
    summary = {
        "track_id": CONTROL_TRACK_ID,
        "closed_sell_count": len(closed_sells),
        "realized_pct_buckets": dict(buckets),
        "still_in_buy_set_count": sum(1 for r in closed_sells if r.get("still_in_buy_set")),
        "left_buy_set_count": sum(1 for r in closed_sells if not r.get("still_in_buy_set")),
        "with_loser_card_count": sum(1 for r in closed_sells if r.get("loser_card")),
        "note": (
            "Realized % is price vs avg_cost_at_exit on control closed sells — "
            "not a sealed selection scoreboard (N205 stays not_now)"
        ),
    }
    skeleton = closed_sells[:SELECTION_SAMPLE_LIMIT]
    cues: list[dict[str, Any]] = []
    if closed_sells:
        left = summary["left_buy_set_count"]
        still = summary["still_in_buy_set_count"]
        cues.append(
            {
                "cue_id": "selection_still_in_buy_set",
                "lane": "selection",
                "claim": (
                    f"Control closed sells: {still} still in buy set, "
                    f"{left} left buy set (n={len(closed_sells)})"
                ),
                "why_matters": (
                    "Separates timing-ish exits (still buy-tier) from selection/thesis "
                    "exits without sealing N205"
                ),
                "falsify_or_promote": (
                    "Thicken skeleton → sealed N205 selection lever only after "
                    "design review; no capital promote from this feed"
                ),
                "severity": "info",
                "evidence": {
                    "closed_sell_count": len(closed_sells),
                    "realized_pct_buckets": summary["realized_pct_buckets"],
                    "sample_tickers": [r["ticker"] for r in skeleton[:5]],
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
                    f"Control realized buckets: ≥10%={ge10}, ≤−10%={le_m10} "
                    f"(of {len(closed_sells)} closed sells)"
                ),
                "why_matters": "Crude well/poorly split for experiment backlog triage",
                "falsify_or_promote": (
                    "Replace with fair-cost episode % + peer rank when N205 seals"
                ),
                "severity": "info",
                "evidence": {"realized_pct_buckets": summary["realized_pct_buckets"]},
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
            }
        )
    return summary, skeleton, cues


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

    n200 = _safe_read(data_dir / "n200_tech_timing_observe.json")
    exit_timing = _safe_read(paper_root / "learning_tracks_exit_timing.json")
    exit_shadow = _safe_read(paper_root / "learning_tracks_exit_shadow.json")
    near_miss_review = _safe_read(data_dir / "exit_timing_near_miss_review.json")
    latest = _safe_read(data_dir / "latest.json")
    loser_cards = _safe_read(data_dir / "loser_snapshot_cards.json")
    fund = _safe_read(paper_root / CONTROL_TRACK_ID / "automated_fund.json")

    buy_set = _buy_set_from_latest(latest)
    loser_index = _loser_card_index(loser_cards)

    timing_cues = [
        *_n200_timing_cues(n200),
        *_exit_timing_cues(exit_timing),
        *_exit_shadow_cues(exit_shadow),
        *_archive_near_miss_cue(near_miss_review),
    ]
    sell_summary, skeleton, selection_cues = _control_closed_sells(
        fund, buy_set=buy_set, loser_index=loser_index
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utcnow().isoformat(),
        "observe_only": True,
        "influences_live": False,
        "auto_fixable": False,
        "package": "M",
        "ops_doc": OPS_DOC,
        "learning_question": (
            "What timing + selection experiment cues follow from closed episodes "
            "and existing observe instruments without sealing N205 or applying knobs?"
        ),
        "inputs": {
            "n200_tech_timing_observe": n200 is not None,
            "learning_tracks_exit_timing": exit_timing is not None,
            "learning_tracks_exit_shadow": exit_shadow is not None,
            "exit_timing_near_miss_review": near_miss_review is not None,
            "control_fund": fund is not None,
            "latest_buy_set_size": len(buy_set),
            "loser_card_index_size": len(loser_index),
        },
        "timing_cues": timing_cues,
        "selection_cues": selection_cues,
        "control_closed_sells": sell_summary,
        "selection_postmortem_skeleton": {
            "schema_version": 1,
            "feeds": "N205",
            "sealed": False,
            "observe_only": True,
            "track_id": CONTROL_TRACK_ID,
            "row_limit": SELECTION_SAMPLE_LIMIT,
            "row_count": len(skeleton),
            "rows": skeleton,
            "note": (
                "Thin ended-control-lifecycle rows for N205 design feed — "
                "not a sealed selection scoreboard"
            ),
        },
        "hub_feed": _hub_feed(timing_cues, selection_cues),
        "sunday_nest": {
            "checklist_id": "sunday-post-sell-cues",
            "neighbor": "sunday-ai-path-scoreboard",
            "summary": (
                f"{len(timing_cues)} timing + {len(selection_cues)} selection cues; "
                f"control closed sells={sell_summary.get('closed_sell_count', 0)}"
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
        ],
    }


def ops_findings_from_digest(payload: dict[str, Any]) -> list[dict[str, Any]]:
    timing_n = len(payload.get("timing_cues") or [])
    selection_n = len(payload.get("selection_cues") or [])
    closed = ((payload.get("control_closed_sells") or {}).get("closed_sell_count")) or 0
    skeleton_n = ((payload.get("selection_postmortem_skeleton") or {}).get("row_count")) or 0
    summary = (
        f"Observe digest refreshed: {timing_n} timing cues, {selection_n} selection cues, "
        f"{closed} control closed sells (skeleton sample {skeleton_n}). "
        "Hub Explore feed via hub_feed; no auto-fix / no N205 seal."
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
    "build_post_sell_cue_digest",
    "ops_findings_from_digest",
    "refresh_post_sell_cue_digest",
]
