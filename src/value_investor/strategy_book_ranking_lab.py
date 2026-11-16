"""Slot-ranking lab: which strategy-book signals should take a slot (exploratory).

The 20-slot book takes signals in a fixed order and skips the rest once every slot
is full. In the US rehearsal about 70% of primary signals were skipped and the
book's return matched random ordering, so the order is unexamined leverage (L691).
This lab re-runs the slot book on the primary's own episodes with a few ranking and
skip rules, fixed here before the first run, and boards each against the
registered order on both US windows and their halves. It is design input for the
strategy book version review, not evidence: both windows were already read.

Scores are point in time. A feature's score on a signal is its percentile among
the primary signals of strictly earlier signal sessions in the same walk; until
``WARMUP_SIGNALS`` earlier values exist the score is missing, which neither ranks
nor skips.
"""

from __future__ import annotations

import bisect
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from value_investor.strategy_book_rules import (
    CAPITAL_YEAR_DAYS,
    SLOT_BOOK_RANDOM_SEED,
    SLOT_COUNT,
    SLOT_RANDOM_ORDERS,
)

LAB_ID = "strategy-book-slot-ranking-lab-v0"
LAB_STORE_NAME = "strategy_book_ranking_lab.json"
WARMUP_SIGNALS = 250
SKIP_BELOW = 0.2
NEUTRAL_SCORE = 0.5

# Scored features. Sign +1: a higher value scores higher.
FEATURES: dict[str, str] = {
    "lo252": "lo252_dist_pct",
    "sma200": "close_vs_sma200",
    "ret126": "return_126",
}
TREND_PARTS = ("lo252", "sma200", "ret126")
TREND_MIN_PARTS = 2


@dataclass(frozen=True)
class RankRule:
    """One variant: an optional skip on a score and an optional within-day order."""

    column: str
    rank: str | None
    descending: bool = True
    skip: str | None = None
    note: str = ""

    def describe(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "rank_by": self.rank,
            "rank_order": None
            if self.rank is None
            else ("high_first" if self.descending else "low_first"),
            "skip_bottom_share_of": self.skip,
            "skip_below": SKIP_BELOW if self.skip else None,
            "note": self.note,
        }


RANK_RULES: tuple[RankRule, ...] = (
    RankRule("rank_lo252", "lo252", note="Furthest above the 52-week low first"),
    RankRule("rank_sma200", "sma200", note="Highest close versus the 200-day average first"),
    RankRule("rank_ret126", "ret126", note="Highest 6-month return first"),
    RankRule("rank_trend3", "trend3", note="Highest mean of the three trend scores first"),
    RankRule(
        "rank_deep_dip",
        "lo252",
        descending=False,
        note="Contrast: closest to the 52-week low first",
    ),
    RankRule(
        "skip_lo252", None, skip="lo252", note="Skip the bottom fifth by 52-week-low distance"
    ),
    RankRule("skip_trend3", None, skip="trend3", note="Skip the bottom fifth by trend score"),
    RankRule(
        "skip_trend3_rank_trend3",
        "trend3",
        skip="trend3",
        note="Skip the bottom fifth by trend score, then highest trend score first",
    ),
)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def feature_value(episode: Mapping[str, Any], feature: str) -> float | None:
    raw = (episode.get("snapshot") or {}).get(feature)
    if raw is None:
        raw = (episode.get("channels") or {}).get(feature)
    return _finite(raw)


def _key(episode: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(episode.get("market") or ""),
        str(episode.get("ticker") or ""),
        str(episode.get("signal_session") or "")[:10],
    )


def point_in_time_scores(
    episodes: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str], dict[str, float | None]]:
    """Each episode's percentile per feature among strictly earlier signal sessions."""
    by_session: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for episode in episodes:
        by_session[str(episode.get("signal_session") or "")[:10]].append(episode)
    seen: dict[str, list[float]] = {name: [] for name in FEATURES}
    out: dict[tuple[str, str, str], dict[str, float | None]] = {}
    for session in sorted(by_session):
        day = by_session[session]
        for episode in day:
            scores: dict[str, float | None] = {}
            for name, feature in FEATURES.items():
                value = feature_value(episode, feature)
                prior = seen[name]
                if value is None or len(prior) < WARMUP_SIGNALS:
                    scores[name] = None
                    continue
                below = bisect.bisect_left(prior, value)
                equal = bisect.bisect_right(prior, value) - below
                scores[name] = (below + 0.5 * equal) / len(prior)
            parts = [v for name in TREND_PARTS if (v := scores[name]) is not None]
            scores["trend3"] = statistics.fmean(parts) if len(parts) >= TREND_MIN_PARTS else None
            out[_key(episode)] = scores
        for episode in day:
            for name, feature in FEATURES.items():
                value = feature_value(episode, feature)
                if value is not None:
                    bisect.insort(seen[name], value)
    return out


def end_cutoffs(episodes: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """The raw value at the skip line among every signal in the window (for a forward rule)."""
    out: dict[str, dict[str, Any]] = {}
    for name, feature in FEATURES.items():
        values = sorted(v for e in episodes if (v := feature_value(e, feature)) is not None)
        index = int(SKIP_BELOW * len(values))
        out[name] = {
            "feature": feature,
            "present": len(values),
            "value_at_skip_line": values[index] if values else None,
        }
    return out


# --- Slot book -----------------------------------------------------------------------------


def simulate(
    episodes: Sequence[Mapping[str, Any]],
    order_key: Callable[[Mapping[str, Any]], Any],
) -> dict[str, Any]:
    """The book's 20-slot simulation (``strategy_book_observe._slot_book``) with a given order.

    Signals due on a fill session are offered in ``order_key`` order; a signal is taken
    while a slot and cash are free, else skipped. Also counts contested sessions, where
    more signals were due than slots were free.
    """
    rows = [e for e in episodes if e.get("fill_session")]
    if not rows:
        return {
            "trades_taken": 0,
            "trades_skipped": 0,
            "annualised_return": None,
            "max_drawdown": None,
            "taken": [],
            "contested_sessions": 0,
            "fill_sessions": 0,
            "skipped_contested": 0,
            "skipped_full": 0,
        }
    ordered = sorted(rows, key=order_key)
    days = sorted(
        {str(e["fill_session"]) for e in ordered}
        | {str(e["exit_session"]) for e in ordered if e.get("exit_session")}
    )
    due_by_day: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for episode in ordered:
        due_by_day[str(episode["fill_session"])].append(episode)
    cash = 1.0
    positions: list[dict[str, Any]] = []
    taken: list[Mapping[str, Any]] = []
    skipped = 0
    contested = 0
    skipped_contested = 0
    skipped_full = 0
    nav_path: list[float] = []
    for day in days:
        still = []
        for position in positions:
            if position["exit_session"] == day:
                cash += position["alloc"] * (1.0 + position["ret"])
            else:
                still.append(position)
        positions = still
        nav = cash + sum(p["alloc"] * (1.0 + p["ret"]) for p in positions)
        due = due_by_day.get(day, [])
        alloc = nav / SLOT_COUNT if SLOT_COUNT else 0.0
        free = SLOT_COUNT - len(positions)
        is_contest = bool(due) and 0 < free < len(due)
        contested += is_contest
        for episode in due:
            if len(positions) >= SLOT_COUNT or cash <= 1e-12:
                skipped += 1
                if is_contest:
                    skipped_contested += 1
                else:
                    skipped_full += 1
                continue
            ret = episode.get("fair_cost_return")
            if ret is None:
                skipped += 1
                continue
            spend = min(alloc, cash)
            cash -= spend
            positions.append(
                {
                    "alloc": spend,
                    "ret": float(ret),
                    "exit_session": str(episode.get("exit_session") or day),
                }
            )
            taken.append(episode)
        nav_path.append(cash + sum(p["alloc"] * (1.0 + p["ret"]) for p in positions))
    for position in positions:
        cash += position["alloc"] * (1.0 + position["ret"])
    span = max((datetime.fromisoformat(days[-1]) - datetime.fromisoformat(days[0])).days, 1)
    annualised = None if cash <= 0 else cash ** (CAPITAL_YEAR_DAYS / span) - 1.0
    peak, max_dd = 1.0, 0.0
    for nav in nav_path:
        peak = max(peak, nav)
        if peak:
            max_dd = min(max_dd, nav / peak - 1.0)
    return {
        "trades_taken": len(taken),
        "trades_skipped": skipped,
        "annualised_return": annualised,
        "max_drawdown": max_dd,
        "taken": taken,
        "contested_sessions": contested,
        "fill_sessions": len(due_by_day),
        "skipped_contested": skipped_contested,
        "skipped_full": skipped_full,
    }


def registered_order(episode: Mapping[str, Any]) -> tuple[str, str]:
    return (str(episode["fill_session"]), str(episode["ticker"]))


def rule_order(
    rule: RankRule, scores: Mapping[tuple[str, str, str], Mapping[str, float | None]]
) -> Callable[[Mapping[str, Any]], Any]:
    def key(episode: Mapping[str, Any]) -> tuple[str, float, str]:
        score = (scores.get(_key(episode)) or {}).get(rule.rank or "")
        value = NEUTRAL_SCORE if score is None else float(score)
        return (
            str(episode["fill_session"]),
            -value if rule.descending else value,
            str(episode["ticker"]),
        )

    return key if rule.rank else registered_order


def kept(
    rule: RankRule,
    episodes: Sequence[Mapping[str, Any]],
    scores: Mapping[tuple[str, str, str], Mapping[str, float | None]],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    if not rule.skip:
        return list(episodes), []
    keep: list[Mapping[str, Any]] = []
    drop: list[Mapping[str, Any]] = []
    for episode in episodes:
        score = (scores.get(_key(episode)) or {}).get(rule.skip)
        (drop if score is not None and score < SKIP_BELOW else keep).append(episode)
    return keep, drop


def random_order_median(episodes: Sequence[Mapping[str, Any]], seed: int) -> float | None:
    values = []
    for offset in range(SLOT_RANDOM_ORDERS):
        rng = random.Random(seed + offset)
        draws = {id(e): rng.random() for e in sorted(episodes, key=registered_order)}

        def key(episode: Mapping[str, Any], _draws: dict[int, float] = draws) -> tuple[str, float]:
            return (str(episode["fill_session"]), _draws[id(episode)])

        result = simulate(episodes, key)["annualised_return"]
        if result is not None:
            values.append(float(result))
    return _median(values)


# --- Boards --------------------------------------------------------------------------------


def _week_error(groups: Mapping[str, list[float]]) -> float | None:
    means = [statistics.fmean(v) for v in groups.values() if v]
    if len(means) < 2:
        return None
    return statistics.stdev(means) / math.sqrt(len(means))


def _set_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    fair = [v for r in rows if (v := _finite(r.get("decision_return_floor"))) is not None]
    excess = [v for r in rows if (v := _finite(r.get("matched_excess"))) is not None]
    return {
        "count": len(rows),
        "fair_cost_median": _median(fair),
        "fair_cost_mean": _mean(fair),
        "matched_excess_median": _median(excess),
        "share_above_zero": None if not fair else sum(v > 0 for v in fair) / len(fair),
    }


def _kept_vs_dropped(
    keep: Sequence[Mapping[str, Any]], drop: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    def values(rows: Sequence[Mapping[str, Any]]) -> tuple[list[float], dict[str, list[float]]]:
        out: list[float] = []
        weeks: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            value = _finite(row.get("decision_return_floor"))
            if value is None:
                continue
            out.append(value)
            weeks[str(row.get("entry_week"))].append(value)
        return out, weeks

    a, wa = values(keep)
    b, wb = values(drop)
    ea, eb = _week_error(wa), _week_error(wb)
    diff = None if not a or not b else statistics.fmean(a) - statistics.fmean(b)
    error = None if ea is None or eb is None else math.sqrt(ea**2 + eb**2)
    return {
        "kept": _set_stats(keep),
        "dropped": _set_stats(drop),
        "mean_difference_kept_minus_dropped": diff,
        "standard_error": error,
        "t": None if diff is None or not error else diff / error,
        "pairing": "unpaired",
    }


def _slot_board(result: Mapping[str, Any], random_median: float | None) -> dict[str, Any]:
    return {
        "annualised_return": result.get("annualised_return"),
        "max_drawdown": result.get("max_drawdown"),
        "random_order_median": random_median,
        "trades_taken": result.get("trades_taken"),
        "trades_skipped": result.get("trades_skipped"),
    }


def window_board(
    episodes: Sequence[Mapping[str, Any]],
    scores: Mapping[tuple[str, str, str], Mapping[str, float | None]],
    rules: Sequence[RankRule] = RANK_RULES,
    seed: int = SLOT_BOOK_RANDOM_SEED,
) -> dict[str, Any]:
    """Registered order and every rule on one window's mature primary episodes."""
    base = simulate(episodes, registered_order)
    base_random = random_order_median(episodes, seed)
    base_taken = _set_stats(base["taken"])
    board: dict[str, Any] = {
        "registered_order": {
            "all_signals": _set_stats(episodes),
            "slot_book": _slot_board(base, base_random),
            "taken": base_taken,
            "contest": {
                "fill_sessions": base["fill_sessions"],
                "contested_sessions": base["contested_sessions"],
                "skipped_contested": base["skipped_contested"],
                "skipped_full": base["skipped_full"],
            },
            "scored_share": {
                name: (
                    None
                    if not episodes
                    else sum(
                        1 for e in episodes if (scores.get(_key(e)) or {}).get(name) is not None
                    )
                    / len(episodes)
                )
                for name in (*FEATURES, "trend3")
            },
        },
        "variants": {},
    }
    base_return = base.get("annualised_return")
    for rule in rules:
        keep, drop = kept(rule, episodes, scores)
        result = simulate(keep, rule_order(rule, scores))
        mine = result.get("annualised_return")
        row: dict[str, Any] = {
            "slot_book": _slot_board(
                result, random_order_median(keep, seed) if rule.skip else base_random
            ),
            "taken": _set_stats(result["taken"]),
            "annualised_vs_registered": None
            if mine is None or base_return is None
            else mine - base_return,
            "taken_overlap_share": _overlap(base["taken"], result["taken"]),
        }
        if rule.skip:
            row["skip"] = _kept_vs_dropped(keep, drop)
        board["variants"][rule.column] = row
    return board


def _overlap(left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]]) -> float | None:
    if not left:
        return None
    mine = {_key(e) for e in right}
    return sum(1 for e in left if _key(e) in mine) / len(left)


def halves_of(first: str, last: str) -> tuple[tuple[str, str], tuple[str, str]]:
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    middle = date.fromordinal((start.toordinal() + end.toordinal()) // 2)
    second = date.fromordinal(middle.toordinal() + 1)
    return (first, middle.isoformat()), (second.isoformat(), last)


def lab_boards(
    episodes: Sequence[Mapping[str, Any]],
    windows: Mapping[str, tuple[str, str]],
    rules: Sequence[RankRule] = RANK_RULES,
) -> dict[str, Any]:
    """Boards for each named window and its two calendar halves.

    ``episodes`` are the primary's mature episodes across every window, so scores
    in a later window read the earlier windows' signals as history.
    """
    ordered = sorted(episodes, key=lambda e: str(e.get("signal_session") or ""))
    scores = point_in_time_scores(ordered)

    def within(first: str, last: str) -> list[Mapping[str, Any]]:
        return [e for e in ordered if first <= str(e.get("signal_session") or "")[:10] <= last]

    out: dict[str, Any] = {}
    for name, (first, last) in windows.items():
        rows = within(first, last)
        block: dict[str, Any] = {
            "signal_window": {"first": first, "last": last},
            "whole": window_board(rows, scores, rules),
            "end_cutoffs": end_cutoffs(rows),
        }
        for label, (a, b) in zip(
            ("first_half", "second_half"), halves_of(first, last), strict=True
        ):
            block[label] = {
                "signal_window": {"first": a, "last": b},
                **window_board(within(a, b), scores, rules),
            }
        out[name] = block
    return out


def apply_choice_rule(boards: Mapping[str, Any]) -> dict[str, Any]:
    """Fixed before the lab first ran.

    Eligible: in every half of every window, the slot-book annualised return is above
    both the registered order's and its random-order median; and in every whole
    window the taken trades' median matched excess is not below the registered
    order's. The pick is the eligible rule with the largest smallest whole-window
    gain over the registered order. No eligible rule means no pick.
    """
    failed: dict[str, list[str]] = {}
    eligible: list[tuple[float, str]] = []
    columns: list[str] = []
    for block in boards.values():
        for column in (block.get("whole") or {}).get("variants") or {}:
            if column not in columns:
                columns.append(column)
    for column in columns:
        reasons: list[str] = []
        gains: list[float] = []
        for name, block in boards.items():
            for label in ("first_half", "second_half"):
                half = block.get(label) or {}
                base = ((half.get("registered_order") or {}).get("slot_book")) or {}
                row = ((half.get("variants") or {}).get(column) or {}).get("slot_book") or {}
                mine = row.get("annualised_return")
                if (
                    mine is None
                    or base.get("annualised_return") is None
                    or mine <= base["annualised_return"]
                ):
                    reasons.append(f"not_above_registered_{name}_{label}")
                if (
                    mine is None
                    or base.get("random_order_median") is None
                    or mine <= base["random_order_median"]
                ):
                    reasons.append(f"not_above_random_{name}_{label}")
            whole = block.get("whole") or {}
            base_excess = ((whole.get("registered_order") or {}).get("taken") or {}).get(
                "matched_excess_median"
            )
            variant = (whole.get("variants") or {}).get(column) or {}
            excess = (variant.get("taken") or {}).get("matched_excess_median")
            if excess is None or base_excess is None or excess < base_excess:
                reasons.append(f"matched_excess_below_registered_{name}")
            gain = variant.get("annualised_vs_registered")
            if gain is not None:
                gains.append(float(gain))
        if not reasons and len(gains) == len(boards):
            eligible.append((min(gains), column))
        else:
            failed[column] = reasons or ["gain_missing"]
    eligible.sort(key=lambda item: (-item[0], item[1]))
    return {
        "eligible": [column for _gain, column in eligible],
        "pick": eligible[0][1] if eligible else None,
        "failed": failed,
    }
