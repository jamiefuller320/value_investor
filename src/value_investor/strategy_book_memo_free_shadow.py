"""Memo-free forward shadow for the sealed strategy book.

Report-only. It walks the same primary entry and primary exit as
``owner-strategy-book-v0``, with the same costs, fills, 100-unit stake, one
open name and cooldown. It does not require the four F9-B input-quality binds
or a memo verdict. Operating-decline and sector-headwind gates stay hard
filters. Every episode records which binds it would have failed.

The shadow never writes the sealed observe store, never opens a book episode,
and does not count toward the thickness gate or the bench. Past sessions use
the append-only gate and memo logs, the same way the forward book does, so a
later store cannot relabel them. A session the log never covered is not filled.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from value_investor.channel_diagnostics import channel_columns
from value_investor.n200_tech_timing_observe import episode_return
from value_investor.storage import read_json, write_json
from value_investor.strategy_book_forward import (
    _head_commit,
    _load_forward_specs,
    _read_log,
    latest_forward_slot,
)
from value_investor.strategy_book_observe import (
    NameSpec,
    WalkOptions,
    _f9_in_force,
    _memo_outcome,
    capital_days_return,
    walk_book,
)
from value_investor.strategy_book_prices import latest_completed_session
from value_investor.strategy_book_replay import _chart_file, _read_chart
from value_investor.strategy_book_rules import (
    COLUMN_PRIMARY,
    FAIL_TO_LAUNCH_INDEX,
    GATE_LOG_NAME,
    LAUNCH_RETURN,
    MARKET_CLOSE_LOCAL,
    OBSERVE_STORE_NAME,
    STAKE_UNITS,
    forward_start_date,
)
from value_investor.strategy_book_signals import repo_paths, universe_markets

STORE_NAME = "strategy_book_memo_free_shadow.json"
TITLE_REFRESHED = "Strategy book memo-free shadow refreshed"
TITLE_MISSING = "Strategy book memo-free shadow missing"
TITLE_STALE = "Strategy book memo-free shadow stale"
TITLE_UNREADABLE = "Strategy book memo-free shadow unreadable"

# Below this many episodes a median on the early-outcome board is not reported.
EARLY_OUTCOME_MIN_N = 8
EARLY_SESSIONS = (10, 20)
OUTCOME_SESSIONS = FAIL_TO_LAUNCH_INDEX
CHANNEL_DIRECTION = "ch126_direction"

F9_BIND_NAMES = (
    "key_filing_bodies",
    "fcf_basis_bound",
    "overlay_bound",
    "memo_recent",
)
RETURN_BUCKETS = (
    "under_minus_5pct",
    "minus_5_to_0",
    "zero_to_plus_5",
    "plus_5_to_plus_10",
    "plus_10_or_more",
)

DESIGN: dict[str, Any] = {
    "hard_filters": [
        "primary_entry_price",
        "operating_decline_clear",
        "sector_headwind_sound",
        "research_not_failed",
        "one_open_per_name",
        "cooldown",
        "late_signal",
    ],
    "relaxed_binds": list(F9_BIND_NAMES),
    "relaxed_memo_verdict": True,
    "stake_units": STAKE_UNITS,
    "exit": "primary",
    "influences_live": False,
    "counts_toward_thickness_gate": False,
    "counts_toward_bench": False,
    "why": (
        "The owner's strategy names a cheap price, no operating decline and no "
        "sector-wide trouble. The four F9-B binds (filing bodies, free-cash-flow "
        "basis, overlay, memo freshness) and the memo verdict are input-quality "
        "checks, not those filters. This shadow drops them as hard filters and "
        "keeps them as labels, so the count is the strategy the owner named."
    ),
}


def shadow_options(
    *,
    start: date | None = None,
    scoring: date | None = None,
    commit: str | None = None,
) -> WalkOptions:
    """Walker settings: gates on, memo off, F9 present but memo not required.

    Callers pass specs whose filing, cash-flow and overlay flags are forced
    true whenever a logged fact exists. A session with no fact still fails
    closed. ``apply_memo`` false drops the memo verdict at the fill.
    """
    return WalkOptions(
        apply_gates=True,
        apply_f9=True,
        apply_memo=False,
        apply_late_signal=True,
        include_controls=False,
        f9_require_memo=False,
        boards=False,
        entry_not_before=start,
        scoring_date=scoring,
        data_commit=commit,
    )


def covered_markets(market_status: Path) -> list[str]:
    """Markets whose daily charts the close refresh already keeps current.

    The refresh walks ``universe_markets`` and asks each one for a cash close.
    A market with no row in ``MARKET_CLOSE_LOCAL`` is skipped (``euro_depth``
    and ``sp400`` have none). This shadow does not add markets.
    """
    return [market for market in universe_markets(market_status) if market in MARKET_CLOSE_LOCAL]


def relax_spec(spec: NameSpec) -> NameSpec:
    """Copy a spec so logged F9 facts do not block the three non-memo binds.

    ``memo_recent`` is left as logged. The walk does not require it. Facts are
    not invented: a session with no fact stays empty and the walk fails closed.
    """
    facts = [
        replace(
            fact,
            key_filing_bodies=True,
            fcf_basis_bound=True,
            overlay_bound=True,
        )
        for fact in (spec.f9 or [])
    ]
    return replace(spec, f9=facts)


def signal_failed_binds(spec: NameSpec, signal_session: date) -> list[str]:
    """F9-B gaps in force on the signal session. No memo verdict yet.

    A pending fill has no fill close, so the memo verdict is not labelled
    until the episode opens. A fact dated after the signal is not in force.
    """
    fact = _f9_in_force(spec, signal_session)
    if fact is None:
        return ["unlogged"]
    return [name for name in F9_BIND_NAMES if getattr(fact, name) is not True]


def failed_binds(spec: NameSpec, signal_session: date, fill_session: date) -> list[str]:
    """Binds the sealed book would have failed, in a stable order.

    Read from the original spec, not the relaxed copy. A fact dated after the
    signal is not in force, so today's stores cannot relabel a past session.
    """
    found = signal_failed_binds(spec, signal_session)
    if "unlogged" in found:
        return found
    outcome, _memo = _memo_outcome(spec, fill_session)
    if outcome == "memo_not_ready" and "memo_recent" not in found and "unlogged" not in found:
        found.append("memo_recent")
    if outcome == "memo_blocked":
        found.append("memo_verdict")
    return found


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "")[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _index(sessions: list[date], day: date) -> int | None:
    for position, item in enumerate(sessions):
        if item == day:
            return position
    return None


def _channel_direction(
    sessions: list[date],
    closes: list[float],
    highs: list[float] | None,
    lows: list[float] | None,
    end: int,
) -> tuple[str | None, str]:
    """6-month channel direction on the prefix through ``end``, and its status."""
    if end < 0 or end >= len(sessions):
        return None, "no_bar"
    prefix = end + 1
    dates = [day.isoformat() for day in sessions[:prefix]]
    high_prefix = None if highs is None or len(highs) < prefix else highs[:prefix]
    low_prefix = None if lows is None or len(lows) < prefix else lows[:prefix]
    columns = channel_columns(
        dates,
        closes[:prefix],
        high_prefix,
        low_prefix,
        as_of=dates[-1],
    )
    raw = columns.get(CHANNEL_DIRECTION)
    direction = raw if isinstance(raw, str) else None
    status = str(columns.get("ch126_status") or columns.get("channel_status") or "")
    return direction, status


def early_marks_for_series(
    sessions: list[date],
    closes: list[float],
    *,
    fill_session: date,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    market: str = "ftse350",
    exit_session: date | None = None,
    realized: float | None = None,
) -> tuple[dict[str, Any], float | None, str]:
    """``early_marks`` plus the 63-session outcome and its basis.

    ``s10`` / ``s20`` are 10 and 20 chart sessions after the fill (the fill is
    index 0, the same index the book uses). ``return_from_fill`` is the gross
    close-to-close change, which is also the launch test. ``max_drawdown`` is
    the worst close versus the running peak from the fill through that bar,
    zero when the close never fell. ``launch_progress`` is that return divided
    by +10%, so 1 means the close is exactly at the launch level.
    ``launched`` is true once any close from the fill through that bar is at
    least +10%. ``channel_direction_change`` compares the 6-month channel
    (``ch126``) at the fill with the same channel at the mark.
    """
    fill_index = _index(sessions, fill_session)
    marks: dict[str, Any] = {}
    if fill_index is None or fill_index >= len(closes) or closes[fill_index] <= 0:
        for sessions_after in EARLY_SESSIONS:
            marks[f"s{sessions_after}"] = {
                "available": False,
                "reason": "no_fill_bar",
                "sessions_after_fill": sessions_after,
            }
        return marks, None, "no_fill_bar"
    entry = float(closes[fill_index])
    fill_direction, _fill_status = _channel_direction(sessions, closes, highs, lows, fill_index)
    for sessions_after in EARLY_SESSIONS:
        target = fill_index + sessions_after
        key = f"s{sessions_after}"
        if target >= len(closes):
            marks[key] = {
                "available": False,
                "reason": "not_yet",
                "sessions_after_fill": sessions_after,
            }
            continue
        window = closes[fill_index : target + 1]
        last = float(window[-1])
        gross = last / entry - 1.0
        peak = float(window[0])
        drawdown = 0.0
        launched = False
        for price in window:
            level = float(price)
            peak = max(peak, level)
            if peak > 0:
                drawdown = min(drawdown, level / peak - 1.0)
            if level / entry - 1.0 >= LAUNCH_RETURN:
                launched = True
        mark_direction, mark_status = _channel_direction(sessions, closes, highs, lows, target)
        changed = (
            fill_direction is not None
            and mark_direction is not None
            and fill_direction != mark_direction
        )
        marks[key] = {
            "available": True,
            "sessions_after_fill": sessions_after,
            "session": sessions[target].isoformat(),
            "return_from_fill": gross,
            "max_drawdown": drawdown,
            "launch_progress": gross / LAUNCH_RETURN,
            "launched": launched,
            "channel_direction_at_fill": fill_direction,
            "channel_direction_at_mark": mark_direction,
            "channel_direction_change": changed,
            "channel_window": "ch126",
            "channel_status_at_mark": mark_status,
        }
    outcome, basis = _outcome_63(
        sessions,
        closes,
        fill_index,
        entry,
        market=market,
        exit_session=exit_session,
        realized=realized,
    )
    return marks, outcome, basis


def _outcome_63(
    sessions: list[date],
    closes: list[float],
    fill_index: int,
    entry: float,
    *,
    market: str,
    exit_session: date | None,
    realized: float | None,
) -> tuple[float | None, str]:
    """Fair-cost return at 63 sessions, or the realized exit if it came first."""
    target = fill_index + OUTCOME_SESSIONS
    exit_index = None if exit_session is None else _index(sessions, exit_session)
    if exit_index is not None and (exit_index - fill_index) <= OUTCOME_SESSIONS:
        if realized is None:
            return None, "not_yet"
        return float(realized), "realized_exit"
    if target < len(closes) and closes[target] > 0:
        return (
            episode_return(
                entry,
                float(closes[target]),
                buy_cost_pct=_costs(market)[0],
                sell_cost_pct=_costs(market)[1],
            ),
            "mark_at_s63",
        )
    return None, "not_yet"


def _costs(market: str) -> tuple[float, float]:
    from value_investor.market_trading_costs import costs_for_market

    costs = costs_for_market(market)
    return float(costs.buy_pct), float(costs.sell_pct)


def _series_of(
    spec: NameSpec,
) -> tuple[list[date], list[float], list[float] | None, list[float] | None]:
    sessions = list(spec.sessions or [])
    closes = [float(value) for value in (spec.closes or [])]
    limit = min(len(sessions), len(closes))
    highs = list(spec.highs) if spec.highs and len(spec.highs) >= limit else None
    lows = list(spec.lows) if spec.lows and len(spec.lows) >= limit else None
    return sessions[:limit], closes[:limit], highs, lows


def annotate_episode(episode: dict[str, Any], spec: NameSpec | None) -> dict[str, Any]:
    """Add ``failed_binds``, ``early_marks`` and the 63-session outcome."""
    row = dict(episode)
    signal = _day(episode.get("signal_session"))
    fill = _day(episode.get("fill_session"))
    if spec is None or signal is None or fill is None:
        row["failed_binds"] = ["unlogged"]
        row["early_marks"] = {
            f"s{sessions_after}": {
                "available": False,
                "reason": "no_spec",
                "sessions_after_fill": sessions_after,
            }
            for sessions_after in EARLY_SESSIONS
        }
        row["outcome_63"] = None
        row["outcome_63_basis"] = "no_spec"
        return row
    row["failed_binds"] = failed_binds(spec, signal, fill)
    sessions, closes, highs, lows = _series_of(spec)
    realized = episode.get("fair_cost_return")
    realized_value = float(realized) if isinstance(realized, (int, float)) else None
    marks, outcome, basis = early_marks_for_series(
        sessions,
        closes,
        fill_session=fill,
        highs=highs,
        lows=lows,
        market=str(episode.get("market") or spec.market),
        exit_session=_day(episode.get("exit_session")),
        realized=realized_value,
    )
    row["early_marks"] = marks
    row["outcome_63"] = outcome
    row["outcome_63_basis"] = basis
    return row


def score_names(specs: list[NameSpec], options: WalkOptions | None = None) -> dict[str, Any]:
    """Walk relaxed copies and label episodes from the original specs."""
    options = options or shadow_options()
    originals = {(spec.market, spec.ticker): spec for spec in specs}
    result = walk_book([relax_spec(spec) for spec in specs], options=options)
    events = list(result.get("events") or [])
    episodes = [
        annotate_episode(episode, originals.get((episode.get("market"), episode.get("ticker"))))
        for episode in result.get("episodes") or []
        if episode.get("column") == COLUMN_PRIMARY
    ]
    pending: list[dict[str, Any]] = []
    for event in events:
        if event.get("kind") != "pending_fill" or event.get("column") != COLUMN_PRIMARY:
            continue
        spec = originals.get((event.get("market"), event.get("ticker")))
        signal = _day(event.get("session"))
        pending.append(
            {
                "market": event.get("market"),
                "ticker": event.get("ticker"),
                "signal_session": event.get("session"),
                "status": "pending_fill",
                "failed_binds": (
                    signal_failed_binds(spec, signal)
                    if spec is not None and signal
                    else ["unlogged"]
                ),
                "memo_verdict_checked": False,
            }
        )
    return {
        "episodes": episodes,
        "pending": pending,
        "events": events,
        "boards": build_boards(episodes),
        "scoring_date": result.get("scoring_date"),
    }


def _numbers(rows: list[dict[str, Any]], key: str) -> list[float]:
    found: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)):
            found.append(float(value))
    return found


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _launch_share(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    launched = sum(1 for row in rows if row.get("launched"))
    return launched / len(rows)


def _group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mature = [row for row in rows if row.get("mature")]
    return {
        "counted": len(rows),
        "open": sum(1 for row in rows if row.get("status") == "open"),
        "mature": len(mature),
        "median_fair_cost_return": _median(_numbers(mature, "fair_cost_return")),
        "median_matched_excess": _median(_numbers(mature, "matched_excess")),
        "launch_share": _launch_share(rows),
        "capital_days_return": capital_days_return(rows),
    }


def return_bucket(value: float) -> str:
    """Gross return bucket for an early mark. Edges are inclusive on the left."""
    if value < -0.05:
        return "under_minus_5pct"
    if value < 0.0:
        return "minus_5_to_0"
    if value < 0.05:
        return "zero_to_plus_5"
    if value < 0.10:
        return "plus_5_to_plus_10"
    return "plus_10_or_more"


def _outcome_cell(outcomes: list[float]) -> dict[str, Any]:
    count = len(outcomes)
    if count < EARLY_OUTCOME_MIN_N:
        return {
            "n": count,
            "median_outcome_63": None,
            "status": "insufficient_data",
        }
    return {
        "n": count,
        "median_outcome_63": _median(outcomes),
        "status": "ok",
    }


def early_outcome_board(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Median 63-session outcome by the s10/s20 return bucket, and by launch.

    An episode counts only when that early mark is available and ``outcome_63``
    is present. A cell with fewer than ``EARLY_OUTCOME_MIN_N`` episodes is
    ``insufficient_data`` and has no median.
    """
    by_s10: dict[str, list[float]] = {bucket: [] for bucket in RETURN_BUCKETS}
    by_s20: dict[str, list[float]] = {bucket: [] for bucket in RETURN_BUCKETS}
    launched: list[float] = []
    not_launched: list[float] = []
    for episode in episodes:
        outcome = episode.get("outcome_63")
        if not isinstance(outcome, (int, float)):
            continue
        marks = episode.get("early_marks") if isinstance(episode.get("early_marks"), dict) else {}
        s10 = marks.get("s10") if isinstance(marks.get("s10"), dict) else {}
        s20 = marks.get("s20") if isinstance(marks.get("s20"), dict) else {}
        if s10.get("available") and isinstance(s10.get("return_from_fill"), (int, float)):
            by_s10[return_bucket(float(s10["return_from_fill"]))].append(float(outcome))
        if s20.get("available") and isinstance(s20.get("return_from_fill"), (int, float)):
            by_s20[return_bucket(float(s20["return_from_fill"]))].append(float(outcome))
            if s20.get("launched") is True:
                launched.append(float(outcome))
            elif s20.get("launched") is False:
                not_launched.append(float(outcome))
    s10_cells = {bucket: _outcome_cell(by_s10[bucket]) for bucket in RETURN_BUCKETS}
    s20_cells = {bucket: _outcome_cell(by_s20[bucket]) for bucket in RETURN_BUCKETS}
    launch_cells = {
        "launched": _outcome_cell(launched),
        "not_launched": _outcome_cell(not_launched),
    }
    cells = [*s10_cells.values(), *s20_cells.values(), *launch_cells.values()]
    status = "ok" if any(cell["status"] == "ok" for cell in cells) else "insufficient_data"
    return {
        "min_n": EARLY_OUTCOME_MIN_N,
        "outcome": "fair-cost return at 63 sessions after the fill, or the realized exit if sooner",
        "status": status,
        "by_s10_return_bucket": s10_cells,
        "by_s20_return_bucket": s20_cells,
        "launched_by_s20": launch_cells,
    }


def build_boards(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Counted, open, mature, medians, launch share, by market and by label."""
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_set: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        by_market[str(episode.get("market") or "")].append(episode)
        labels = [str(item) for item in (episode.get("failed_binds") or [])]
        if not labels:
            by_label["none"].append(episode)
            by_set["none"].append(episode)
        else:
            for label in labels:
                by_label[label].append(episode)
            by_set["+".join(labels)].append(episode)
    return {
        **_group_summary(episodes),
        "by_market": {market: _group_summary(rows) for market, rows in sorted(by_market.items())},
        "by_failed_bind": {label: _group_summary(rows) for label, rows in sorted(by_label.items())},
        "by_failed_bind_set": {
            label: _group_summary(rows) for label, rows in sorted(by_set.items())
        },
        "early_outcomes": early_outcome_board(episodes),
    }


def _slim(episode: dict[str, Any]) -> dict[str, Any]:
    """Scoring row only. The sealed observe store keeps the full walker dump."""
    keep = (
        "episode_id",
        "market",
        "ticker",
        "column",
        "status",
        "signal_session",
        "fill_session",
        "exit_session",
        "exit_reason",
        "launched",
        "launch_index",
        "launch_session",
        "fair_cost_return",
        "gross_return",
        "matched_excess",
        "capital_return",
        "mature",
        "stake",
        "held_calendar_days",
        "held_sessions",
        "entry_week",
        "currency",
        "entry_fill_first_seen",
        "failed_binds",
        "early_marks",
        "outcome_63",
        "outcome_63_basis",
    )
    return {key: episode.get(key) for key in keep}


def book_early_marks(
    episodes: list[dict[str, Any]],
    series_for: Callable[
        [str, str], tuple[list[date], list[float], list[float] | None, list[float] | None] | None
    ],
) -> dict[str, Any]:
    """Early marks for sealed-book primary episodes, computed from charts.

    The observe store is read and not written. Marks live here so its boards
    stay untouched.
    """
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        if not episode.get("fill_session"):
            continue
        market = str(episode.get("market") or "")
        ticker = str(episode.get("ticker") or "")
        series = series_for(market, ticker)
        fill = _day(episode.get("fill_session"))
        realized = episode.get("fair_cost_return")
        realized_value = float(realized) if isinstance(realized, (int, float)) else None
        if series is None or fill is None:
            marks = {
                f"s{sessions_after}": {
                    "available": False,
                    "reason": "no_chart",
                    "sessions_after_fill": sessions_after,
                }
                for sessions_after in EARLY_SESSIONS
            }
            outcome, basis = None, "no_chart"
        else:
            sessions, closes, highs, lows = series
            marks, outcome, basis = early_marks_for_series(
                sessions,
                closes,
                fill_session=fill,
                highs=highs,
                lows=lows,
                market=market,
                exit_session=_day(episode.get("exit_session")),
                realized=realized_value,
            )
        rows.append(
            {
                "episode_id": episode.get("episode_id"),
                "column": episode.get("column"),
                "market": market,
                "ticker": ticker,
                "status": episode.get("status"),
                "fill_session": episode.get("fill_session"),
                "exit_session": episode.get("exit_session"),
                "mature": episode.get("mature"),
                "launched": episode.get("launched"),
                "fair_cost_return": realized_value,
                "early_marks": marks,
                "outcome_63": outcome,
                "outcome_63_basis": basis,
            }
        )
    return {
        "source": OBSERVE_STORE_NAME,
        "counted": len(rows),
        "episodes": rows,
        "outcome_board": early_outcome_board(rows),
    }


def _chart_series(
    paths: Any, market: str, ticker: str, now: datetime
) -> tuple[list[date], list[float], list[float] | None, list[float] | None] | None:
    completed = latest_completed_session(market, now)
    if completed is None or not ticker:
        return None
    path = _chart_file(paths.charts, ticker)
    if path is None:
        return None
    chart = _read_chart(path)
    if chart is None:
        return None
    sessions, closes, highs, lows = chart
    keep = [index for index, day in enumerate(sessions) if day <= completed]
    if not keep:
        return None
    last = keep[-1] + 1
    return (
        sessions[:last],
        closes[:last],
        None if highs is None else highs[:last],
        None if lows is None else lows[:last],
    )


def _book_section(paths: Any, now: datetime) -> dict[str, Any]:
    payload = _read_json_dict(paths.observe)
    if payload is None:
        empty = early_outcome_board([])
        return {
            "source": OBSERVE_STORE_NAME,
            "status": "missing",
            "counted": 0,
            "episodes": [],
            "outcome_board": empty,
        }
    episodes = payload.get("episodes") if isinstance(payload.get("episodes"), list) else []
    section = book_early_marks(
        [row for row in episodes if isinstance(row, dict)],
        lambda market, ticker: _chart_series(paths, market, ticker, now),
    )
    section["status"] = "ok"
    return section


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def run_memo_free_shadow(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Rebuild the shadow from ``forward_start``. Write only the shadow store."""
    moment = now if now is not None and now.tzinfo is not None else (now or datetime.now(UTC))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    paths = repo_paths(repo_root)
    start = forward_start_date(paths.registration, decision=moment.date())
    commit = _head_commit(paths.root)
    log_rows = _read_log(paths.data / GATE_LOG_NAME)
    loaded = _load_forward_specs(
        paths,
        start=start,
        now=moment,
        commit=commit,
        log_rows=log_rows,
    )
    options = shadow_options(start=start, scoring=moment.date(), commit=commit)
    scored = score_names(loaded["specs"], options)
    book = _book_section(paths, moment)
    markets = covered_markets(paths.market_status)
    # A market with no cash-close row is outside this shadow. The book records
    # "unknown close" for it; the shadow does not treat that as a failure.
    errors = [item for item in loaded["errors"] if not str(item).endswith(": unknown close")]
    store = {
        "instrument": "strategy_book_memo_free_shadow",
        "registration_id": "owner-strategy-book-v0",
        "influences_live": False,
        "component": "owner-approved strategy-book component",
        "generated_at": moment.isoformat(),
        "start_date": start.isoformat(),
        "scoring_date": scored.get("scoring_date"),
        "data_commit": commit,
        "design": DESIGN,
        "markets_covered": markets,
        "errors": errors,
        "episodes": [_slim(episode) for episode in scored["episodes"]],
        "pending": list(scored["pending"]),
        "boards": scored["boards"],
        "book_early_marks": book,
    }
    wrote = False
    if apply:
        dest = paths.data / STORE_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_json(dest, store, compact=False)
        wrote = True
    summary = public_summary(store)
    summary["wrote"] = wrote
    summary["dry_run"] = not apply
    return summary


def _tally(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    found: dict[str, int] = defaultdict(int)
    for row in rows:
        found[str(row.get(key) or "")] += 1
    return dict(sorted(found.items()))


def _label_tally(rows: list[dict[str, Any]]) -> dict[str, int]:
    found: dict[str, int] = defaultdict(int)
    for row in rows:
        labels = [str(item) for item in (row.get("failed_binds") or [])]
        if not labels:
            found["none"] += 1
        else:
            for label in labels:
                found[label] += 1
    return dict(sorted(found.items()))


def public_summary(store: dict[str, Any]) -> dict[str, Any]:
    """Counts for stdout. No episode bodies."""
    boards = store.get("boards") if isinstance(store.get("boards"), dict) else {}
    book = store.get("book_early_marks") if isinstance(store.get("book_early_marks"), dict) else {}
    pending = [row for row in (store.get("pending") or []) if isinstance(row, dict)]
    early = boards.get("early_outcomes") if isinstance(boards.get("early_outcomes"), dict) else {}
    book_board = book.get("outcome_board") if isinstance(book.get("outcome_board"), dict) else {}

    def counts(block: dict[str, Any] | None) -> dict[str, int]:
        if not isinstance(block, dict):
            return {}
        return {
            key: int((block.get(key) or {}).get("counted") or 0)
            for key in block
            if isinstance(block.get(key), dict)
        }

    return {
        "instrument": store.get("instrument"),
        "influences_live": False,
        "generated_at": store.get("generated_at"),
        "start_date": store.get("start_date"),
        "scoring_date": store.get("scoring_date"),
        "markets_covered": list(store.get("markets_covered") or []),
        "counted": int(boards.get("counted") or 0),
        "pending_fill": len(pending),
        "pending_by_market": _tally(pending, "market"),
        "pending_by_failed_bind": _label_tally(pending),
        "open": int(boards.get("open") or 0),
        "mature": int(boards.get("mature") or 0),
        "median_fair_cost_return": boards.get("median_fair_cost_return"),
        "median_matched_excess": boards.get("median_matched_excess"),
        "launch_share": boards.get("launch_share"),
        "capital_days_return": boards.get("capital_days_return"),
        "by_market": counts(boards.get("by_market")),
        "by_failed_bind": counts(boards.get("by_failed_bind")),
        "by_failed_bind_set": counts(boards.get("by_failed_bind_set")),
        "early_outcome_status": early.get("status"),
        "early_outcome_min_n": early.get("min_n"),
        "book_early_marks": int(book.get("counted") or 0),
        "book_by_column": _tally(
            [row for row in (book.get("episodes") or []) if isinstance(row, dict)],
            "column",
        ),
        "book_early_outcome_status": book_board.get("status"),
        "errors": list(store.get("errors") or []),
    }


def findings_from_store(
    store: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    unreadable: str | None = None,
) -> list[dict[str, Any]]:
    """One finding. Warns only when the store is missing, stale or unreadable."""
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if unreadable:
        return [_finding("warn", TITLE_UNREADABLE, unreadable)]
    if not store:
        return [
            _finding(
                "warn",
                TITLE_MISSING,
                "docs/data/strategy_book_memo_free_shadow.json is missing. "
                "The weekday forward workflow writes it after the book walk. "
                "No rememo or ingest.",
            )
        ]
    slot = latest_forward_slot(moment)
    stamp = _parse_dt(store.get("generated_at"))
    if stamp is None or stamp < slot:
        seen = store.get("generated_at")
        return [
            _finding(
                "warn",
                TITLE_STALE,
                f"Shadow store is older than the {slot.isoformat()} slot "
                f"(generated_at {seen}). No rememo or ingest.",
            )
        ]
    summary = public_summary(store)
    labels = summary.get("by_failed_bind") or {}
    label_text = ", ".join(f"{key} {value}" for key, value in list(labels.items())[:8]) or "none"
    markets = ", ".join(
        f"{key} {value}" for key, value in list((summary.get("by_market") or {}).items())[:8]
    )
    return [
        _finding(
            "info",
            TITLE_REFRESHED,
            f"Shadow episodes {summary.get('counted')} "
            f"(open {summary.get('open')}, mature {summary.get('mature')}, "
            f"pending fill {summary.get('pending_fill')}). "
            f"Markets: {markets or 'none'}. Failed-bind labels: {label_text}. "
            f"Early-outcome board {summary.get('early_outcome_status')} "
            f"(minimum {summary.get('early_outcome_min_n')}). "
            "Report-only. It does not open book episodes.",
        )
    ]


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp


def _finding(severity: str, title: str, summary: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": "research",
        "title": title,
        "summary": summary,
        "auto_fixable": False,
    }


def load_store(repo_root: Path | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Return the store, or (None, reason) when the file is missing or unreadable."""
    path = repo_paths(repo_root).data / STORE_NAME
    if not path.is_file():
        return None, None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "shadow store is not an object"
    return payload, None


def check_findings(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    store, error = load_store(repo_root)
    if error:
        return findings_from_store(None, now=now, unreadable=error)
    return findings_from_store(store, now=now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Memo-free forward shadow (report-only, does not write the book)"
    )
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument("--apply", action="store_true", help="Write the shadow store")
    parser.add_argument("--as-of", help="Override the run timestamp (ISO-8601)")
    args = parser.parse_args(argv)
    moment = None
    if args.as_of:
        moment = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
    summary = run_memo_free_shadow(repo_root=args.repo_root, now=moment, apply=args.apply)
    print(json.dumps(summary, indent=2, default=str))
    return 1 if summary.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
