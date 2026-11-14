"""Exit lab: trend-led exit variants scored on the US development window (exploratory).

Design input for the strategy book's exit challenger (deferred idea N259). Each
variant is a paired column on the primary's own entries, like the comparison
exits: it opens nothing and never changes the primary. The lab walks signal
sessions in the US rehearsal's development window only (2000–2012). Its scores
choose which single variant the owner may seal into the free bench slot; they are
not evidence for it. Evidence comes from forward marks.

Every variant keeps the section 5 thesis breaks and reviews (every 63 sessions,
without the four-review cap) and has no time cap. Variants differ in two parts:

* **unlaunched** — what ends a trade that has not reached the +10% launch;
* **launched** — what ends a trade once it has.

A close at or above the fill times 1.10 launches a trade, as on the primary.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from value_investor.strategy_book_rules import (
    COLUMN_PRIMARY,
    DRAFT_REVIEW_SPACING,
    EXIT_FAIL_TO_LAUNCH,
    FAIL_TO_LAUNCH_INDEX,
    SLOT_BOOK_RANDOM_SEED,
)

LAB_PREFIX = "lab_"
LAB_STORE_NAME = "strategy_book_exit_lab.json"

EXIT_TRAIL = "trail_exit"
EXIT_TREND = "trend_break"
EXIT_CHANNEL_LOW = "channel_low_exit"
EXIT_NEW_LOW = "new_low_exit"
EXIT_LEFT_TIER = "left_tier_exit"
EXIT_STOP = "stop_exit"

UNLAUNCHED_KINDS = ("deadline", "new_low", "none", "tier", "stop")
LAUNCHED_KINDS = ("ladder", "trail", "sma", "low", "tier", "ladder_tier")
# Rules that read the screen runs: out of the value set for the confirm count of runs.
TIER_KINDS = frozenset({"tier", "ladder_tier"})

# The longest close window any variant reads (a new low below the prior 252 closes).
MAX_LOOKBACK = 253


@dataclass(frozen=True)
class LabExit:
    """One exit variant. ``column`` is its episode column."""

    name: str
    launched: str
    launched_param: float
    unlaunched: str
    unlaunched_param: float = 0.0
    unlaunched_buffer: float = 0.0
    # Sessions after the fill at which an unlaunched trade also ends (0 = no deadline).
    unlaunched_deadline: int = 0

    def __post_init__(self) -> None:
        if self.launched not in LAUNCHED_KINDS:
            raise ValueError(f"unknown launched rule: {self.launched}")
        if self.unlaunched not in UNLAUNCHED_KINDS:
            raise ValueError(f"unknown unlaunched rule: {self.unlaunched}")

    @property
    def column(self) -> str:
        return LAB_PREFIX + self.name

    @property
    def reads_tier(self) -> bool:
        return self.launched in TIER_KINDS or self.unlaunched in TIER_KINDS

    def describe(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "launched": {"rule": self.launched, "param": self.launched_param},
            "unlaunched": {
                "rule": self.unlaunched,
                "param": self.unlaunched_param,
                "buffer": self.unlaunched_buffer,
                **({"deadline": self.unlaunched_deadline} if self.unlaunched_deadline else {}),
            },
            "time_cap": None,
            "review_spacing": DRAFT_REVIEW_SPACING,
        }


# Fixed before the lab is first run. Two isolate one part each; the rest pair a
# trend-led launched rule with the new-low rule for trades that have not started.
LAB_EXITS: tuple[LabExit, ...] = (
    LabExit("ladder_newlow252", "ladder", 0.0, "new_low", 252),
    LabExit("trail15_deadline63", "trail", 0.15, "deadline", FAIL_TO_LAUNCH_INDEX),
    LabExit("trail15_newlow252", "trail", 0.15, "new_low", 252),
    LabExit("trail25_newlow252", "trail", 0.25, "new_low", 252),
    LabExit("sma50_newlow252", "sma", 50, "new_low", 252),
    LabExit("low55_newlow252", "low", 55, "new_low", 252),
    LabExit("trail15_newlow252_b5", "trail", 0.15, "new_low", 252, 0.05),
    LabExit("trail15_none", "trail", 0.15, "none", 0),
)

# Round 2, fixed before it is first run: the leave-tier hold (sell after the confirm
# count of screen runs outside the value set) scored per capital-day, and the
# recovery leg (L688). Every variant keeps the thesis breaks and the 63-session reviews.
LAB_EXITS_ROUND_2: tuple[LabExit, ...] = (
    LabExit("tier_tier", "tier", 0.0, "tier", 0),
    LabExit("tier_deadline63", "tier", 0.0, "deadline", FAIL_TO_LAUNCH_INDEX),
    LabExit("laddertier_tier", "ladder_tier", 0.0, "tier", 0),
    LabExit("ladder_stop8_deadline63", "ladder", 0.0, "stop", 0.08, 0.0, FAIL_TO_LAUNCH_INDEX),
    LabExit("ladder_deadline32", "ladder", 0.0, "deadline", 32),
)
LAB_ROUNDS: dict[int, tuple[LabExit, ...]] = {1: LAB_EXITS, 2: LAB_EXITS_ROUND_2}


def lab_by_column(exits: Sequence[LabExit]) -> dict[str, LabExit]:
    return {rule.column: rule for rule in exits}


def is_review_session(index: int) -> bool:
    return index > 0 and index % DRAFT_REVIEW_SPACING == 0


def launched_signal(
    rule: LabExit,
    *,
    close: float,
    peak: float,
    closes: list[float],
    left_tier: bool = False,
) -> str | None:
    """Exit reason for a launched trade, or None. ``closes`` ends at today's close.

    ``ladder`` (and the floor half of ``ladder_tier``) is handled by the walker's
    checkpoint floor and returns None here.
    """
    if rule.launched in TIER_KINDS:
        return EXIT_LEFT_TIER if left_tier else None
    if rule.launched == "trail":
        return EXIT_TRAIL if close <= peak * (1.0 - rule.launched_param) else None
    if rule.launched == "sma":
        window = int(rule.launched_param)
        if len(closes) < window:
            return None
        return EXIT_TREND if close < statistics.fmean(closes[-window:]) else None
    if rule.launched == "low":
        window = int(rule.launched_param)
        prior = closes[-window - 1 : -1]
        if len(prior) < window:
            return None
        return EXIT_CHANNEL_LOW if close < min(prior) else None
    return None


def unlaunched_signal(
    rule: LabExit,
    *,
    index: int,
    close: float,
    closes: list[float],
    entry_px: float | None = None,
    left_tier: bool = False,
) -> str | None:
    """Exit reason for a trade that has not launched, or None."""
    reason = _unlaunched_rule(
        rule, index=index, close=close, closes=closes, entry_px=entry_px, left_tier=left_tier
    )
    if reason is None and rule.unlaunched_deadline and index >= rule.unlaunched_deadline:
        return EXIT_FAIL_TO_LAUNCH
    return reason


def _unlaunched_rule(
    rule: LabExit,
    *,
    index: int,
    close: float,
    closes: list[float],
    entry_px: float | None,
    left_tier: bool,
) -> str | None:
    if rule.unlaunched == "tier":
        return EXIT_LEFT_TIER if left_tier else None
    if rule.unlaunched == "stop":
        if not entry_px:
            return None
        return EXIT_STOP if close <= entry_px * (1.0 - rule.unlaunched_param) else None
    if rule.unlaunched == "deadline":
        return EXIT_FAIL_TO_LAUNCH if index >= int(rule.unlaunched_param) else None
    if rule.unlaunched == "new_low":
        if index < 1:
            return None
        window = int(rule.unlaunched_param)
        prior = closes[-window - 1 : -1]
        if not prior:
            return None
        return EXIT_NEW_LOW if close < min(prior) * (1.0 - rule.unlaunched_buffer) else None
    return None


# --- Boards --------------------------------------------------------------------------------


def _finite(value: Any) -> float | None:
    if value is None:
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


def _week_error(by_week: Mapping[str, list[float]]) -> float | None:
    means = [statistics.fmean(values) for values in by_week.values() if values]
    if len(means) < 2:
        return None
    return statistics.stdev(means) / math.sqrt(len(means))


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(row["market"]), str(row["ticker"]), str(row["signal_session"]))


def _paired(primary: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Variant minus primary on the same entries (both mature), entry-week standard error."""
    base = {_key(row): row for row in primary}
    diffs: list[float] = []
    by_week: dict[str, list[float]] = defaultdict(list)
    better = 0
    for row in rows:
        left = base.get(_key(row))
        if left is None:
            continue
        a = _finite(left.get("decision_return_floor"))
        b = _finite(row.get("decision_return_close"))
        if a is None or b is None:
            continue
        diff = b - a
        diffs.append(diff)
        by_week[str(left.get("entry_week"))].append(diff)
        better += diff > 0
    error = _week_error(by_week)
    mean = _mean(diffs)
    return {
        "n": len(diffs),
        "entry_weeks": len(by_week),
        "mean_difference_vs_primary": mean,
        "median_difference_vs_primary": _median(diffs),
        "standard_error": error,
        "t": None if mean is None or not error else mean / error,
        "share_variant_better": None if not diffs else better / len(diffs),
    }


def capital_days_return(rows: list[dict[str, Any]]) -> float | None:
    pnl = 0.0
    stake_days = 0.0
    for row in rows:
        ret = _finite(row.get("capital_return"))
        stake = _finite(row.get("stake"))
        days = _finite(row.get("held_calendar_days"))
        if ret is None or stake is None or days is None:
            continue
        pnl += ret * stake
        stake_days += stake * days
    return None if stake_days <= 0 else pnl / stake_days * 365


def column_board(
    rows: list[dict[str, Any]],
    primary: list[dict[str, Any]],
    slot_book,
) -> dict[str, Any]:
    """One column's aggregates. ``rows`` are that column's mature episodes."""
    fair = [v for row in rows if (v := _finite(row.get("decision_return_floor"))) is not None]
    excess = [v for row in rows if (v := _finite(row.get("matched_excess"))) is not None]
    held = [v for row in rows if (v := _finite(row.get("held_sessions"))) is not None]
    days = [v for row in rows if (v := _finite(row.get("held_calendar_days"))) is not None]
    slot = slot_book(
        [{**row, "column": COLUMN_PRIMARY} for row in rows], seed=SLOT_BOOK_RANDOM_SEED
    )
    mean_days = _mean(days)
    board: dict[str, Any] = {
        "mature": len(rows),
        "still_open": sum(1 for row in rows if row.get("status") != "closed"),
        "fair_cost_median": _median(fair),
        "fair_cost_mean": _mean(fair),
        "matched_excess_median": _median(excess),
        "share_above_zero": None if not fair else sum(v > 0 for v in fair) / len(fair),
        "launch_share": None
        if not rows
        else sum(bool(r.get("launched")) for r in rows) / len(rows),
        "held_sessions_median": _median(held),
        "held_calendar_days_mean": mean_days,
        "turns_per_slot_year": None if not mean_days else 365 / mean_days,
        "capital_days_return": capital_days_return(rows),
        "slot_book": {
            "annualised_return": slot.get("annualised_return"),
            "max_drawdown": slot.get("max_drawdown"),
            "random_order_median": slot.get("random_order_median"),
            "trades_taken": slot.get("trades_taken"),
            "trades_skipped": slot.get("trades_skipped"),
        },
        "by_exit_reason": {
            reason: {
                "count": count,
                "fair_cost_median": _median(
                    [
                        v
                        for row in rows
                        if str(row.get("exit_reason") or "open") == reason
                        and (v := _finite(row.get("decision_return_floor"))) is not None
                    ]
                ),
            }
            for reason, count in sorted(
                Counter(str(row.get("exit_reason") or "open") for row in rows).items()
            )
        },
    }
    if rows is not primary:
        board["paired"] = _paired(primary, rows)
    return board


def halves_of(first: str, last: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """Calendar-midpoint split of a signal window, the parent's ``period_halves`` reading."""
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    middle = date.fromordinal((start.toordinal() + end.toordinal()) // 2)
    second = date.fromordinal(middle.toordinal() + 1)
    return (first, middle.isoformat()), (second.isoformat(), last)


def lab_boards(
    episodes: list[dict[str, Any]],
    exits: Sequence[LabExit],
    window: tuple[str, str],
    slot_book,
    controls: Sequence[str] = (),
) -> dict[str, Any]:
    """Primary and every variant, over the window and its two calendar halves.

    ``controls`` are existing paired columns (for example the leave-tier control)
    boarded the same way; the choice rule does not read them.
    """

    def mature(column: str, first: str, last: str) -> list[dict[str, Any]]:
        return [
            row
            for row in episodes
            if row.get("column") == column
            and row.get("mature")
            and first <= str(row.get("signal_session"))[:10] <= last
        ]

    out: dict[str, Any] = {}
    for label, (first, last) in (
        ("whole", window),
        *zip(("first_half", "second_half"), halves_of(*window), strict=True),
    ):
        primary = mature(COLUMN_PRIMARY, first, last)
        block = {
            "signal_window": {"first": first, "last": last},
            "primary": column_board(primary, primary, slot_book),
            "variants": {
                rule.column: column_board(mature(rule.column, first, last), primary, slot_book)
                for rule in exits
            },
        }
        if controls:
            block["controls"] = {
                column: column_board(mature(column, first, last), primary, slot_book)
                for column in controls
            }
        out[label] = block
    return out


def apply_choice_rule(boards: Mapping[str, Any]) -> dict[str, Any]:
    """The bench-seal review's choice rule, fixed before the lab first ran.

    Eligible: paired mean above zero in both halves, capital-days return above the
    primary's in both halves, and whole-window median matched excess not below the
    primary's. The pick is the eligible variant with the highest whole-window
    capital-days return; no eligible variant means no pick.
    """
    whole = boards.get("whole") or {}
    halves = [boards.get("first_half") or {}, boards.get("second_half") or {}]
    base_excess = (whole.get("primary") or {}).get("matched_excess_median")
    failed: dict[str, list[str]] = {}
    eligible: list[tuple[float, str]] = []
    for column, board in (whole.get("variants") or {}).items():
        reasons: list[str] = []
        for label, half in zip(("first_half", "second_half"), halves, strict=True):
            row = (half.get("variants") or {}).get(column) or {}
            mean = (row.get("paired") or {}).get("mean_difference_vs_primary")
            if mean is None or mean <= 0:
                reasons.append(f"paired_mean_not_above_zero_{label}")
            mine = row.get("capital_days_return")
            base = (half.get("primary") or {}).get("capital_days_return")
            if mine is None or base is None or mine <= base:
                reasons.append(f"capital_days_not_above_primary_{label}")
        excess = board.get("matched_excess_median")
        if excess is None or base_excess is None or excess < base_excess:
            reasons.append("matched_excess_below_primary")
        capital = board.get("capital_days_return")
        if not reasons and capital is not None:
            eligible.append((capital, column))
        elif not reasons:
            reasons.append("capital_days_missing")
        if reasons:
            failed[column] = reasons
    eligible.sort(key=lambda item: (-item[0], item[1]))
    return {
        "eligible": [column for _capital, column in eligible],
        "pick": eligible[0][1] if eligible else None,
        "failed": failed,
    }
