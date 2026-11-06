"""Episode walker for the strategy book (plan step 2.3).

Pure function of closes, screen facts, gate facts and memo facts. It does not
read the committed data tree and it does not score a live book. The
registration is unsigned: callers that would score ``docs/data`` go through
the CLIs, which refuse without ``registration_signed``.

Entry arithmetic is ``strategy_book_signals.price_flags`` (RSI via
``technical_analysis._rsi``). Exits call ``core_sell_reason``,
``note_thesis_streak`` and ``thesis_break_confirmed``. Returns call
``episode_return`` and ``costs_for_market``. Channel columns call
``channel_diagnostics.channel_columns``.
"""

from __future__ import annotations

import copy
import hashlib
import math
import random
import statistics
from array import array
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from value_investor.channel_diagnostics import (
    CONTEXT_WINDOW as CHANNEL_CONTEXT_WINDOW,
)
from value_investor.channel_diagnostics import (
    PIVOT_SPAN as CHANNEL_PIVOT_SPAN,
)
from value_investor.channel_diagnostics import (
    PRIMARY_WINDOW as CHANNEL_PRIMARY_WINDOW,
)
from value_investor.channel_diagnostics import (
    SESSIONS_PER_YEAR as CHANNEL_YEAR_SESSIONS,
)
from value_investor.channel_diagnostics import (
    _as_float as _channel_float,
)
from value_investor.channel_diagnostics import channel_columns
from value_investor.core_sell_trigger import (
    core_sell_reason,
    note_thesis_streak,
    thesis_break_confirmed,
)
from value_investor.decision_input_inventory import _memo_age_days
from value_investor.market_trading_costs import costs_for_market
from value_investor.n200_tech_timing_observe import episode_return
from value_investor.strategy_book_rules import (
    ARCHIVE_BUY_TIER_ONLY,
    ARCHIVE_FULL_STRATEGY,
    BASKET_MIN_NAMES,
    BENCH_MIN_COUNTED,
    BENCH_SLOTS,
    BENCH_STANDARD_ERRORS,
    CAP_BLOCKS_ENTRIES,
    CAPITAL_YEAR_DAYS,
    CHART_NOT_DAILY_GAP_DAYS,
    CHART_NOT_DAILY_GAP_SHARE,
    CHECKPOINTS,
    COLUMN_ALTERNATIVE,
    COLUMN_BUY_ON_SIGNAL,
    COLUMN_DECLINE_SHADOW,
    COLUMN_DRAFT,
    COLUMN_LADDER,
    COLUMN_LEAVE_TIER,
    COLUMN_PRIMARY,
    COLUMN_SECTOR_SHADOW,
    COOLDOWN_SESSIONS,
    DEEP_DIP_DROP,
    DEEP_DIP_LOOKBACK,
    DRAFT_HIGH_WINDOW,
    DRAFT_REVIEW_COUNT,
    DRAFT_REVIEW_SPACING,
    DRAFT_SWING_LIMIT_INDEX,
    EXIT_FAIL_TO_LAUNCH,
    EXIT_FLOOR,
    EXIT_HOLD_63,
    EXIT_INELIGIBLE_RUNS,
    EXIT_RECOVERY_TARGET,
    EXIT_REVIEW_CAP,
    EXIT_REVIEW_INSUFFICIENT,
    EXIT_SWING_HIGH,
    EXIT_THESIS,
    EXIT_TIME_CAP,
    FAIL_TO_LAUNCH_INDEX,
    FLOOR_AT_OR_ABOVE_LAST,
    INFLUENCES_LIVE,
    INITIAL_BENCH,
    INTERIM_WEEKS,
    LOOKAHEAD_CURRENT_GATES,
    MARKET_BOARD_MIN_MATURE,
    MATURITY_SESSIONS,
    MAX_FILL_GAP_CALENDAR_DAYS,
    MEMO_MAX_AGE_DAYS,
    RECOVERY_CAPITAL_LONG_SESSIONS,
    RECOVERY_DROP,
    RECOVERY_SHARE_LINE,
    RECOVERY_SHARE_MIN_OPEN,
    REGIME_ABOVE_SHARE,
    REGIME_MIN_NAMES,
    REGIME_SMA_SESSIONS,
    REGISTRATION_ID,
    REVIEW_INDEXES,
    SELECTION_FIFTHS,
    SLOT_BOOK_RANDOM_SEED,
    SLOT_COUNT,
    SLOT_RANDOM_ORDERS,
    STAKE_UNITS,
    STALE_CHART_CALENDAR_DAYS,
    STRESS_PER_SIDE,
    T212_CATALOGUE_MAX_AGE_DAYS,
    THESIS_CONFIRM_OBSERVATIONS,
    THICKNESS_MAX_PER_ENTRY_WEEK,
    THICKNESS_MIN_COUNTED,
    THICKNESS_MIN_SPAN_SESSIONS,
    TIME_CAP_INDEX,
    VALUE_SET_SIGNALS,
    UnknownMarketClose,
    floor_for_checkpoint,
    highest_checkpoint,
    session_close,
)
from value_investor.strategy_book_signals import (
    PRICE_FLAG_TAIL,
    chart_is_thinned,
    price_flags,
    rsi_path,
)

US_REHEARSAL_MODE = "us_rehearsal"
EXIT_DELISTED = "delisted"
# Rows ``channel_columns`` and the price features read back from the signal
# session; a longer prefix changes only the ``bars`` count.
_FEATURE_TAIL = (
    max(CHANNEL_CONTEXT_WINDOW, CHANNEL_YEAR_SESSIONS, CHANNEL_PRIMARY_WINDOW + CHANNEL_PIVOT_SPAN)
    + CHANNEL_PIVOT_SPAN
    + 1
)

# Section 8. Numeric snapshot fields that the selection board splits into fifths.
# Categorical fields are stored and reported as coverage, not ranked.
NUMERIC_SNAPSHOT_FEATURES: tuple[str, ...] = (
    "composite_score",
    "signal_rank",
    "weeks_at_signal",
    "conviction_score",
    "models_passed",
    "data_quality_score",
    "fcf_yield",
    "ev_ebit",
    "earnings_yield_pe",
    "roic_proxy",
    "profit_margins",
    "debt_to_equity",
    "revenue_growth",
    "earnings_growth",
    "market_cap",
    "vol_60",
    "close_vs_sma200",
    "fall_from_high_252",
    "return_126",
    "range_pos_126",
    "return_20",
    "rsi_14",
    "memo_age_days",
)

# Section 8. Numeric ``channel_columns`` fields join the same fifths.
# Buckets, directions and booleans stay on the channel split, not ranked.
CHANNEL_NUMERIC_FEATURES: tuple[str, ...] = (
    "ch126_slope_pct_yr",
    "ch126_r2",
    "ch126_z",
    "ch126_lower",
    "ch126_upper",
    "ch252_slope_pct_yr",
    "ch252_r2",
    "ch252_z",
    "ch252_lower",
    "ch252_upper",
    "bb20_pct_b",
    "bb20_width_pct",
    "dc20_pos",
    "dc55_pos",
    "support_dist_pct",
    "resistance_dist_pct",
    "sma50_dist_pct",
    "sma200_dist_pct",
    "hi252_dist_pct",
    "lo252_dist_pct",
)

_ENTRY_COLUMNS = (COLUMN_PRIMARY, COLUMN_ALTERNATIVE, COLUMN_DECLINE_SHADOW, COLUMN_SECTOR_SHADOW)
_LADDER_COLUMNS = (COLUMN_PRIMARY, COLUMN_ALTERNATIVE, COLUMN_DECLINE_SHADOW, COLUMN_SECTOR_SHADOW)


@dataclass
class ScreenFact:
    """One weekly screen row. Applies to sessions strictly after ``run_date``."""

    run_date: date
    signal: str | None = None
    adjusted_signal: str | None = None
    research_verdict: str | None = None
    research_confidence: float | None = None
    sector: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    path: str | None = None


@dataclass
class GateFact:
    """One decline and sector observation. Applies strictly after ``as_of``."""

    as_of: date
    decline: str | None = None
    sector: str | None = None
    sector_basis: str | None = None
    region: str | None = None
    sector_name: str | None = None
    earnings_breadth_sources: dict[str, int] | None = None
    sector_inputs: dict[str, Any] | None = None
    checks: dict[str, Any] | None = None
    soft_checks: list[str] | None = None
    path: str | None = None


@dataclass
class MemoFact:
    finished_at: datetime
    verdict: str | None = None
    rationale: str | None = None
    by_signal_job: bool = False
    path: str | None = None


@dataclass
class F9Fact:
    """Filing, cash-flow and overlay binds dated on or before a session.

    ``memo_recent`` is optional here. The forward book reads memos at the fill.
    """

    as_of: date
    key_filing_bodies: bool = False
    fcf_basis_bound: bool = False
    overlay_bound: bool = False
    memo_recent: bool | None = None
    path: str | None = None


@dataclass
class ListingFact:
    basis: str
    fetched_at: date | None = None
    path: str | None = None


@dataclass
class Download:
    """One adjusted-close download. Decisions use the first download that contains the session."""

    as_of: date
    sessions: list[date]
    closes: list[float]
    highs: list[float] | None = None
    lows: list[float] | None = None

    def __post_init__(self) -> None:
        order = sorted(zip(self.sessions, self.closes, strict=False), key=lambda item: item[0])
        self.sessions = [item[0] for item in order]
        self.closes = [float(item[1]) for item in order]
        self._index = _DayIndex(self.sessions)
        self._dups = self._index.duplicates
        self._rsi: array | None = None
        self._bars: array | None = None

    def find(self, session: date) -> int | None:
        """Position of ``session``. A repeated date resolves to its last row."""
        return self._index.find(session)

    def has(self, session: date) -> bool:
        return self._index.find(session) is not None

    def close(self, session: date) -> float | None:
        index = self._index.find(session)
        return None if index is None else self.closes[index]

    def count_through(self, session: date) -> int:
        """Rows dated on or before ``session``."""
        return bisect_right(self.sessions, session)

    def channel_bars_before(self, count: int) -> int:
        """Closes ``channel_columns`` would count among the first ``count`` rows."""
        if self._bars is None:
            self._bars = array("i", [0]) * (len(self.closes) + 1)
            running = 0
            for position, value in enumerate(self.closes):
                running += _channel_float(value) is not None
                self._bars[position + 1] = running
        return self._bars[count]

    def rsi_at(self, count: int) -> float | None:
        """``rsi_last`` of the first ``count`` rows (no repeated dates)."""
        if self._rsi is None:
            self._rsi = array("d", [math.nan if v is None else v for v in rsi_path(self.closes)])
        if count <= 0:
            return None
        value = self._rsi[count - 1]
        return None if math.isnan(value) else value


class _DayIndex:
    """Day-ordinal slots for a sorted date list: O(1) lookups without a dict per bar."""

    __slots__ = ("days", "duplicates", "first", "slots")

    def __init__(self, days: list[date]) -> None:
        self.days = days
        self.duplicates = False
        if not days:
            self.first = 0
            self.slots = array("i")
            return
        self.first = days[0].toordinal()
        self.slots = array("i", [-1]) * (days[-1].toordinal() - self.first + 1)
        previous = None
        for position, day in enumerate(days):
            if day == previous:
                self.duplicates = True
            self.slots[day.toordinal() - self.first] = position
            previous = day

    def find(self, day: date) -> int | None:
        offset = day.toordinal() - self.first
        if offset < 0 or offset >= len(self.slots):
            return None
        position = self.slots[offset]
        if position < 0 or self.days[position] != day:
            return None
        return position

    def __contains__(self, day: date) -> bool:
        return self.find(day) is not None


class GateTape:
    """Daily gate observations held as codes rather than one ``GateFact`` each.

    ``as_of`` is strictly increasing. ``decline`` and ``sector`` index ``labels``.
    ``detail(i)`` returns the remaining ``GateFact`` fields for observation *i*
    (checks, soft checks, sector inputs, basis); it is called only when a
    snapshot or a position needs them.
    """

    def __init__(
        self,
        as_of: list[date],
        decline: Sequence[int],
        sector: Sequence[int],
        labels: Sequence[str | None],
        detail: Callable[[int], dict[str, Any]] | None = None,
    ) -> None:
        if not (len(as_of) == len(decline) == len(sector)):
            raise ValueError("gate tape columns differ in length")
        self.as_of = as_of
        self._decline = decline
        self._sector = sector
        self._labels = tuple(labels)
        self._detail = detail

    def __len__(self) -> int:
        return len(self.as_of)

    def decline(self, index: int) -> str | None:
        return self._labels[self._decline[index]]

    def sector(self, index: int) -> str | None:
        return self._labels[self._sector[index]]

    def fact(self, index: int) -> GateFact:
        extra = self._detail(index) if self._detail is not None else {}
        return GateFact(
            as_of=self.as_of[index],
            decline=self.decline(index),
            sector=self.sector(index),
            **extra,
        )

    def latest(self) -> GateFact | None:
        return self.fact(len(self.as_of) - 1) if self.as_of else None


class _GateList:
    """``GateFact`` list in the order the walker reads it (stable by ``as_of``)."""

    def __init__(self, facts: list[GateFact]) -> None:
        self.facts = sorted(facts, key=lambda item: item.as_of)
        self.as_of = [fact.as_of for fact in self.facts]
        self._latest = max(facts, key=lambda item: item.as_of) if facts else None

    def __len__(self) -> int:
        return len(self.facts)

    def decline(self, index: int) -> str | None:
        return self.facts[index].decline

    def sector(self, index: int) -> str | None:
        return self.facts[index].sector

    def fact(self, index: int) -> GateFact:
        return self.facts[index]

    def latest(self) -> GateFact | None:
        return self._latest


@dataclass
class NameSpec:
    market: str
    ticker: str
    sessions: list[date] | None = None
    closes: list[float] | None = None
    highs: list[float] | None = None
    lows: list[float] | None = None
    downloads: list[Download] | None = None
    screens: list[ScreenFact] = field(default_factory=list)
    gates: list[GateFact] = field(default_factory=list)
    memos: list[MemoFact] = field(default_factory=list)
    f9: list[F9Fact] | None = None
    listing: ListingFact | None = None
    signal_seen_at: dict[date, datetime] | None = None
    graduated: bool = True
    library: bool = False
    input_paths: list[str] = field(default_factory=list)
    files: dict[str, bytes] | None = None
    committed: dict[str, bytes] | None = None
    omit_hash_on: set[str] = field(default_factory=set)
    # Inclusive (first, last) sessions in the universe. None is always in.
    # Outside them a name cannot enter; an open episode still runs its exits.
    universe: list[tuple[date, date]] | None = None
    # Specs sharing a key are one name for the one-open rule and the cooldown.
    book_key: str | None = None
    # Set for a delisted name: an episode still open at its last bar exits
    # there at ``close * (1 + terminal_haircut)``.
    terminal_haircut: float | None = None


@dataclass
class WalkOptions:
    """Which registration gates this walk applies. Presets match section 9."""

    apply_gates: bool = True
    apply_f9: bool = True
    apply_memo: bool = True
    apply_late_signal: bool = True
    paint_gates: bool = False
    alternative: bool = False
    drop_last_bar: bool = False
    include_controls: bool = True
    # Section 2: the memo bind is a forward rule. Archive walks do not require it.
    f9_require_memo: bool = True
    scoring_date: date | None = None
    decision_date: date | None = None
    data_commit: str | None = None
    # Sessions before this date are not entry sessions. The forward job sets
    # it from the seal so August–October stays in the archive.
    entry_not_before: date | None = None
    # No signal session after this date. Later sessions still fill and exit.
    entry_not_after: date | None = None
    # Episode label when no catalogue applies (US rehearsal: not_applicable).
    t212_label: str | None = None
    # Keep each basket member's prices on the episode. Off keeps only the mean.
    basket_members: bool = True
    # A carried screen row with no signal is not on the screen for the basket.
    basket_skips_blank_screen: bool = False
    # Build the section 8 boards inside ``walk_book``.
    boards: bool = True


def options_for(mode: str) -> WalkOptions:
    """``forward``, ``archive_buy_tier``, ``archive_full``, ``lookahead`` or ``us_rehearsal``."""
    if mode == "forward":
        return WalkOptions()
    if mode == US_REHEARSAL_MODE:
        # Registration strategy-book-us-rehearsal-v0 sections 3–4: point-in-time
        # gates, no F9-B, memo, late-signal clock or catalogue.
        return WalkOptions(
            apply_gates=True,
            apply_f9=False,
            apply_memo=False,
            apply_late_signal=False,
            alternative=True,
            drop_last_bar=True,
            include_controls=True,
            f9_require_memo=False,
            t212_label="not_applicable",
            basket_members=False,
            basket_skips_blank_screen=True,
            boards=False,
        )
    if mode == ARCHIVE_BUY_TIER_ONLY or mode == "archive_buy_tier":
        return WalkOptions(
            apply_gates=False,
            apply_f9=False,
            apply_memo=False,
            apply_late_signal=False,
            alternative=True,
            drop_last_bar=True,
            include_controls=True,
            f9_require_memo=False,
        )
    if mode == ARCHIVE_FULL_STRATEGY or mode == "archive_full":
        return WalkOptions(
            apply_gates=True,
            apply_f9=True,
            apply_memo=False,
            apply_late_signal=False,
            drop_last_bar=True,
            include_controls=False,
            f9_require_memo=False,
        )
    if mode == LOOKAHEAD_CURRENT_GATES or mode == "lookahead":
        return WalkOptions(
            apply_gates=True,
            apply_f9=False,
            apply_memo=False,
            apply_late_signal=False,
            paint_gates=True,
            drop_last_bar=True,
            include_controls=False,
            f9_require_memo=False,
        )
    raise ValueError(f"unknown walk mode: {mode}")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def chart_long_gap_share(sessions: list[date]) -> float:
    """Share of successive gaps longer than the section 9 daily-gap limit."""
    if len(sessions) < 2:
        return 0.0
    ordered = sorted(sessions)
    gaps = [(b - a).days for a, b in zip(ordered, ordered[1:], strict=False)]
    long = sum(1 for gap in gaps if gap > CHART_NOT_DAILY_GAP_DAYS)
    return long / len(gaps)


def series_refusal(sessions: list[date]) -> str | None:
    """``thinned`` (downsampled tape) or ``chart_not_daily`` (section 9), else None."""
    if len(sessions) < 2:
        return None
    if chart_is_thinned(sorted(sessions)):
        return "thinned"
    if chart_long_gap_share(sessions) > CHART_NOT_DAILY_GAP_SHARE:
        return "chart_not_daily"
    return None


def entry_week(day: date) -> str:
    year, week, _weekday = day.isocalendar()
    return f"{year}-W{week:02d}"


def _iso_monday(token: str) -> date:
    year_text, week_text = str(token).split("-W")
    return date.fromisocalendar(int(year_text), int(week_text), 1)


def period_halves(
    episodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split episodes at the calendar midpoint of their entry weeks.

    The span is every ISO week from the first counted entry week through the
    last, including weeks with no episode. The midpoint is halfway between
    those two Mondays. Weeks on or before that midpoint's ISO week are the
    first half, so an odd span puts the middle week in the first half.
    One function owns the cut: a different owner choice edits only this body.
    """
    dated: list[tuple[str, dict[str, Any]]] = []
    for episode in episodes:
        token = episode.get("entry_week")
        if not token and episode.get("fill_session"):
            try:
                token = entry_week(date.fromisoformat(str(episode["fill_session"])[:10]))
            except ValueError:
                token = None
        if not token:
            continue
        dated.append((str(token), episode))
    if not dated:
        return [], []
    weeks = sorted({token for token, _episode in dated})
    first_monday = _iso_monday(weeks[0])
    last_monday = _iso_monday(weeks[-1])
    midpoint = first_monday + (last_monday - first_monday) / 2
    cut = entry_week(midpoint)
    first = [episode for token, episode in dated if token <= cut]
    second = [episode for token, episode in dated if token > cut]
    return first, second


def _cash_close(market: str, day: date) -> datetime | None:
    """Local cash close, or None when the market has no registered close."""
    try:
        return session_close(market, day)
    except UnknownMarketClose:
        return None


def t212_listed(listing: ListingFact | None, entry_day: date) -> bool | str:
    """True only on a catalogue hit. Allowlist is false. Older than 35 days is unknown."""
    if listing is None or listing.fetched_at is None:
        return "unknown"
    if (entry_day - listing.fetched_at).days > T212_CATALOGUE_MAX_AGE_DAYS:
        return "unknown"
    if listing.basis == "catalogue_hit":
        return True
    return False


def entry_week_standard_error(diffs_by_week: dict[str, list[float]]) -> float | None:
    """Standard error of the mean from entry-week averages (section 8)."""
    means = [statistics.fmean(values) for values in diffs_by_week.values() if values]
    if len(means) < 2:
        return None
    return statistics.stdev(means) / math.sqrt(len(means))


def capital_days_return(episodes: list[dict[str, Any]]) -> float | None:
    """Sum of fair-cost P&L divided by stake-days, times 365 (section 8).

    P&L is ``fair_cost_return * stake``. Stake-days is ``stake * calendar days
    held``. Open episodes use the latest-close fair-cost return.
    """
    pnl = 0.0
    stake_days = 0.0
    for episode in episodes:
        ret = episode.get("capital_return")
        stake = episode.get("stake")
        days = episode.get("held_calendar_days")
        if ret is None or stake is None or days is None:
            continue
        pnl += float(ret) * float(stake)
        stake_days += float(stake) * float(days)
    if stake_days <= 0:
        return None
    return pnl / stake_days * CAPITAL_YEAR_DAYS


class PriceBook:
    def __init__(self, downloads: list[Download]) -> None:
        self.downloads = sorted(downloads, key=lambda item: (item.as_of, id(item)))
        if len(self.downloads) == 1 and not self.downloads[0]._dups:
            only = self.downloads[0]
            self.calendar = only.sessions
            self._days = only._index
        else:
            self.calendar = sorted({day for item in self.downloads for day in item.sessions})
            self._days = _DayIndex(self.calendar)
        self._chosen: dict[date, Download | None] = {}

    def position(self, session: date) -> int | None:
        """Index of ``session`` in ``calendar``."""
        return self._days.find(session)

    def has_session(self, session: date) -> bool:
        return self._days.find(session) is not None

    def download_for(self, session: date) -> Download | None:
        """Earliest download that already contains ``session``."""
        if len(self.downloads) == 1:
            only = self.downloads[0]
            return only if only.has(session) else None
        if session in self._chosen:
            return self._chosen[session]
        chosen = self._download_for(session)
        self._chosen[session] = chosen
        return chosen

    def _download_for(self, session: date) -> Download | None:
        chosen: Download | None = None
        for download in self.downloads:
            if not download.has(session):
                continue
            if download.as_of < session:
                continue
            if chosen is None or download.as_of < chosen.as_of:
                chosen = download
        if chosen is not None:
            return chosen
        # A download taken on a later rebuild still contains the session, but a
        # download whose as_of is before the session cannot be that session's tape.
        for download in self.downloads:
            if download.has(session) and (chosen is None or download.as_of < chosen.as_of):
                chosen = download
        return chosen

    def latest(self) -> Download | None:
        if not self.downloads:
            return None
        return max(self.downloads, key=lambda item: item.as_of)

    def prefix(self, session: date) -> tuple[Download | None, list[date], list[float]]:
        download = self.download_for(session)
        if download is None:
            return None, [], []
        count = download.count_through(session)
        days = download.sessions[:count]
        if download._dups:
            closes = [download.closes[download.find(day)] for day in days]
        else:
            closes = download.closes[:count]
        return download, days, closes

    def tail(self, session: date, rows: int) -> tuple[Download | None, int, list[float]]:
        """``prefix`` closes, last ``rows`` only, plus the full prefix length."""
        download = self.download_for(session)
        if download is None:
            return None, 0, []
        if download._dups:
            _download, days, closes = self.prefix(session)
            return download, len(closes), closes[-rows:]
        count = download.count_through(session)
        return download, count, download.closes[max(0, count - rows) : count]


@dataclass
class _Pending:
    column: str
    signal_session: date
    fill_session: date


@dataclass
class _Position:
    column: str
    market: str
    ticker: str
    signal_session: date
    fill_session: date
    entry_first_seen: float
    phase: str = "swing"
    launched: bool = False
    launch_index: int | None = None
    launch_session: date | None = None
    highest_checkpoint: float | None = None
    floor: float | None = None
    floor_history: list[dict[str, Any]] = field(default_factory=list)
    recovery: bool = False
    recovery_index: int | None = None
    pending_exit: str | None = None
    pending_exit_session: date | None = None
    pending_reasons: list[str] = field(default_factory=list)
    status: str = "open"
    exit_reason: str | None = None
    exit_signal_session: date | None = None
    exit_session: date | None = None
    exit_fill: float | None = None
    return_entry: float | None = None
    fair_cost_return: float | None = None
    gross_return: float | None = None
    stress_return: float | None = None
    matched_excess: float | None = None
    basket: dict[str, Any] | None = None
    gap_shortfall: float | None = None
    reviews: list[dict[str, Any]] = field(default_factory=list)
    decision_log: list[dict[str, Any]] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    provenance_missing: bool = True
    snapshot: dict[str, Any] = field(default_factory=dict)
    channels: dict[str, Any] = field(default_factory=dict)
    bench: dict[str, bool] = field(default_factory=dict)
    t212: bool | str = "unknown"
    t212_fetched_at: str | None = None
    regime: str = "regime_unknown"
    f9_status: str = "unverified"
    sector_basis: str | None = None
    region: str | None = None
    earnings_breadth_bucket: str | None = None
    adjusted_signal: str | None = None
    memo_age_days: float | None = None
    memo_by_signal_job: bool = False
    memo_verdict: str | None = None
    memo_rationale: str | None = None
    entry_run: date | None = None
    download_as_of: str | None = None
    mark_entry: float | None = None
    mark_exit: float | None = None
    floor_return: float | None = None
    capital_return: float | None = None
    stake: float = STAKE_UNITS
    buy_cost_pct: float = 0.0
    sell_cost_pct: float = 0.0
    currency: str = ""
    out_of_median: bool = False
    data_commit: str | None = None


@dataclass
class _Name:
    spec: NameSpec
    prices: PriceBook
    refusal: str | None
    pendings: list[_Pending] = field(default_factory=list)
    positions: list[_Position] = field(default_factory=list)
    streaks: dict[str, int] = field(default_factory=dict)
    screen_cursor: date | None = None
    gate_cursor: date | None = None
    last_exit_fill: dict[str, date] = field(default_factory=dict)
    seen_insufficient: set[date] = field(default_factory=set)
    # Specs with the same ``book_key`` (this one included).
    siblings: list[_Name] = field(default_factory=list)
    # Open positions in the order they were opened (a subset of ``positions``).
    open_positions: list[_Position] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.siblings:
            self.siblings = [self]
        # ``sorted`` is stable: equal run dates keep the spec's order.
        self.screens = sorted(self.spec.screens, key=lambda item: item.run_date)
        self.run_dates = [fact.run_date for fact in self.screens]
        # First fact of each run date, which ``max`` would pick among ties.
        self.tie_first: list[int] = []
        for position, run_date in enumerate(self.run_dates):
            if position and self.run_dates[position - 1] == run_date:
                self.tie_first.append(self.tie_first[-1])
            else:
                self.tie_first.append(position)
        gates = self.spec.gates
        self.gates: GateTape | _GateList = (
            gates if isinstance(gates, GateTape) else _GateList(list(gates or []))
        )
        self.screen_pos = 0
        self.gate_pos = 0
        self._gate_fact: tuple[int, GateFact] | None = None
        self._flags: tuple[tuple[int, int], dict[str, Any]] | None = None
        self._entry_cache: dict[tuple[date, int], dict[str, Any]] = {}
        self._channel_cache: dict[date, dict[str, Any]] = {}
        spans = self.spec.universe
        self.universe = sorted(spans) if spans is not None else None
        self.universe_starts = [span[0] for span in self.universe] if self.universe else []


def _downloads_of(spec: NameSpec) -> list[Download]:
    if spec.downloads:
        return list(spec.downloads)
    sessions = list(spec.sessions or [])
    closes = [float(value) for value in (spec.closes or [])]
    if not sessions or not closes:
        return []
    return [
        Download(
            as_of=max(sessions),
            sessions=sessions,
            closes=closes,
            highs=spec.highs,
            lows=spec.lows,
        )
    ]


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        from datetime import UTC

        return moment.replace(tzinfo=UTC)
    return moment


def _fair(entry: float, exit_px: float, market: str) -> float:
    costs = costs_for_market(market)
    return episode_return(
        entry,
        exit_px,
        buy_cost_pct=costs.buy_pct,
        sell_cost_pct=costs.sell_pct,
    )


def _stress(entry: float, exit_px: float) -> float:
    return episode_return(entry, exit_px, trade_cost_pct=STRESS_PER_SIDE)


def _screen_in_force(name: _Name, session: date) -> ScreenFact | None:
    """Latest run strictly before ``session``; the first such fact among equal run dates."""
    position = bisect_left(name.run_dates, session) - 1
    if position < 0:
        return None
    return name.screens[name.tie_first[position]]


def _screens_between(name: _Name, after: date, before: date) -> list[ScreenFact]:
    """Runs with ``after < run_date < before``, in run-date order."""
    low = bisect_right(name.run_dates, after)
    high = bisect_left(name.run_dates, before)
    return name.screens[low:high]


def _gate_index(name: _Name, session: date) -> int:
    """Index of the gate observation in force at ``session`` (as_of strictly before), or -1."""
    return bisect_left(name.gates.as_of, session) - 1


def _gate_fact(name: _Name, index: int) -> GateFact:
    cached = name._gate_fact
    if cached is not None and cached[0] == index:
        return cached[1]
    fact = name.gates.fact(index)
    name._gate_fact = (index, fact)
    return fact


def _gate_in_force(name: _Name, session: date) -> GateFact | None:
    index = _gate_index(name, session)
    return None if index < 0 else _gate_fact(name, index)


def _latest_gate(name: _Name) -> GateFact | None:
    return name.gates.latest()


def _eligibility_gate(name: _Name, session: date, options: WalkOptions) -> GateFact | None:
    if options.paint_gates:
        return _latest_gate(name)
    return _gate_in_force(name, session)


def _gate_verdicts(
    name: _Name, session: date, options: WalkOptions
) -> tuple[bool, str | None, str | None]:
    """(present, decline, sector) of the eligibility gate without building a fact."""
    if options.paint_gates:
        gate = _latest_gate(name)
        return (False, None, None) if gate is None else (True, gate.decline, gate.sector)
    index = _gate_index(name, session)
    if index < 0:
        return False, None, None
    return True, name.gates.decline(index), name.gates.sector(index)


def _in_universe(name: _Name, session: date) -> bool:
    if name.universe is None:
        return True
    position = bisect_right(name.universe_starts, session) - 1
    return position >= 0 and session <= name.universe[position][1]


def _price_flags_at(name: _Name, session: date) -> dict[str, Any] | None:
    """``price_flags`` of the prefix through ``session``, or None without closes."""
    download = name.prices.download_for(session)
    if download is None:
        return None
    if download._dups:
        _download, _days, closes = name.prices.prefix(session)
        return price_flags(closes) if closes else None
    count = download.count_through(session)
    if count <= 0:
        return None
    key = (id(download), count)
    cached = name._flags
    if cached is not None and cached[0] == key:
        return cached[1]
    tail = download.closes[max(0, count - PRICE_FLAG_TAIL) : count]
    flags = price_flags(tail, rsi=download.rsi_at(count))
    name._flags = (key, flags)
    return flags


def _f9_in_force(spec: NameSpec, session: date) -> F9Fact | None:
    chosen: F9Fact | None = None
    for fact in spec.f9 or []:
        if fact.as_of <= session and (chosen is None or fact.as_of > chosen.as_of):
            chosen = fact
    return chosen


def _f9_ok(fact: F9Fact | None, *, require_memo: bool) -> bool:
    if fact is None:
        return False
    if not (fact.key_filing_bodies and fact.fcf_basis_bound and fact.overlay_bound):
        return False
    if require_memo and fact.memo_recent is not True:
        return False
    return True


def _research_blocks(verdict: str | None) -> bool:
    return core_sell_reason({"research_verdict": verdict}) is not None


def _index_of(prices: PriceBook, fill: date, session: date) -> int | None:
    start = prices.position(fill)
    end = prices.position(session)
    if start is None or end is None:
        return None
    return end - start


def _next_bar(calendar: list[date], session: date) -> date | None:
    position = bisect_right(calendar, session)
    return calendar[position] if position < len(calendar) else None


def _gap_ok(start: date, end: date) -> bool:
    return (end - start).days <= MAX_FILL_GAP_CALENDAR_DAYS


def _cooldown_open(name: _Name, column: str, session: date) -> bool:
    last = name.last_exit_fill.get(column)
    if last is None:
        return True
    index = _index_of(name.prices, last, session)
    return index is not None and index >= COOLDOWN_SESSIONS


def _hash_inputs(spec: NameSpec, kind: str) -> tuple[list[dict[str, Any]], bool]:
    paths = list(spec.input_paths)
    if kind in spec.omit_hash_on:
        rows = [{"path": path, "sha256": None} for path in paths] or [
            {"path": None, "sha256": None}
        ]
        return rows, True
    if spec.files is None or not paths:
        rows = [{"path": path, "sha256": None} for path in paths] or [
            {"path": None, "sha256": None}
        ]
        return rows, True
    missing = False
    rows = []
    for path in paths:
        blob = spec.files.get(path)
        if blob is None:
            rows.append({"path": path, "sha256": None})
            missing = True
            continue
        digest = sha256_bytes(blob)
        rows.append({"path": path, "sha256": digest})
        if spec.committed is not None:
            committed = spec.committed.get(path)
            if committed is None or sha256_bytes(committed) != digest:
                missing = True
    return rows, missing


def _bump(streaks: dict[str, int], key: str, kind: str) -> None:
    if kind == "missing":
        row = None
    elif kind == "fail":
        row = {"signal": "avoid"}
    else:
        row = {"signal": "buy"}
    note_thesis_streak(streaks, key, row)


def _consume_observations(name: _Name, session: date, options: WalkOptions) -> None:
    """Advance the thesis streaks through every observation in force at ``session``.

    Observations are read once, in date order, so a caller may skip sessions
    and catch up later with the same streaks.
    """
    spec = name.spec
    screens = name.screens
    while name.screen_pos < len(screens) and screens[name.screen_pos].run_date < session:
        fact = screens[name.screen_pos]
        name.screen_pos += 1
        if name.screen_cursor is not None and fact.run_date <= name.screen_cursor:
            continue
        signal = str(fact.signal or "").strip().lower()
        if signal == "avoid":
            _bump(name.streaks, f"{spec.ticker}:screen_avoid", "fail")
        elif signal:
            _bump(name.streaks, f"{spec.ticker}:screen_avoid", "reset")
        else:
            _bump(name.streaks, f"{spec.ticker}:screen_avoid", "missing")
        verdict = fact.research_verdict
        if verdict is None or str(verdict).strip() == "":
            _bump(name.streaks, f"{spec.ticker}:research", "missing")
        elif _research_blocks(str(verdict)):
            _bump(name.streaks, f"{spec.ticker}:research", "fail")
        else:
            _bump(name.streaks, f"{spec.ticker}:research", "reset")
        name.screen_cursor = fact.run_date
    if not options.apply_gates:
        return
    gates = name.gates
    as_of = gates.as_of
    while name.gate_pos < len(as_of) and as_of[name.gate_pos] < session:
        index = name.gate_pos
        name.gate_pos += 1
        if name.gate_cursor is not None and as_of[index] <= name.gate_cursor:
            continue
        _gate_bump(name, "declining", gates.decline(index), fail="declining", reset="clear")
        _gate_bump(name, "headwind", gates.sector(index), fail="headwind", reset="sound")
        name.gate_cursor = as_of[index]


def _gate_bump(name: _Name, reason: str, verdict: str | None, *, fail: str, reset: str) -> None:
    key = f"{name.spec.ticker}:{reason}"
    if verdict == fail:
        _bump(name.streaks, key, "fail")
    elif verdict == reset:
        _bump(name.streaks, key, "reset")
    else:
        _bump(name.streaks, key, "missing")


def _confirmed_reasons(name: _Name, options: WalkOptions) -> list[str]:
    ticker = name.spec.ticker
    found: list[str] = []
    if options.apply_gates and thesis_break_confirmed(
        name.streaks.get(f"{ticker}:declining", 0), THESIS_CONFIRM_OBSERVATIONS
    ):
        found.append("declining")
    if options.apply_gates and thesis_break_confirmed(
        name.streaks.get(f"{ticker}:headwind", 0), THESIS_CONFIRM_OBSERVATIONS
    ):
        found.append("headwind")
    if thesis_break_confirmed(
        name.streaks.get(f"{ticker}:screen_avoid", 0), THESIS_CONFIRM_OBSERVATIONS
    ):
        found.append("screen_avoid")
    if thesis_break_confirmed(
        name.streaks.get(f"{ticker}:research", 0), THESIS_CONFIRM_OBSERVATIONS
    ):
        found.append("research_failed")
    return found


def _stale(options: WalkOptions, session: date) -> bool:
    if options.decision_date is None:
        return False
    return (options.decision_date - session).days > STALE_CHART_CALENDAR_DAYS


def _base_eligible(
    name: _Name,
    session: date,
    options: WalkOptions,
    *,
    price: bool,
) -> tuple[bool, str]:
    spec = name.spec
    if spec.library and not spec.graduated:
        return False, "not_graduated"
    if name.refusal:
        return False, name.refusal
    if not name.prices.calendar:
        return False, "no_chart"
    if not _in_universe(name, session):
        return False, "not_in_universe"
    screen = _screen_in_force(name, session)
    if screen is None or str(screen.signal or "") not in VALUE_SET_SIGNALS:
        return False, "not_buy_tier"
    if _research_blocks(screen.research_verdict):
        return False, "research_failed"
    if options.apply_gates:
        present, decline, sector = _gate_verdicts(name, session, options)
        if not present or decline != "clear" or sector != "sound":
            return False, "gate"
    if options.apply_f9 and not _f9_ok(
        _f9_in_force(spec, session), require_memo=options.f9_require_memo
    ):
        return False, "f9"
    if price:
        flags = _price_flags_at(name, session)
        if not flags or not flags["primary"]:
            return False, "price"
    if _stale(options, session):
        return False, "stale_chart"
    return True, "ok"


def _shadow_columns(name: _Name, session: date, options: WalkOptions) -> list[str]:
    if not options.apply_gates:
        return []
    spec = name.spec
    if spec.library and not spec.graduated:
        return []
    if name.refusal or not name.prices.calendar:
        return []
    if not _in_universe(name, session):
        return []
    screen = _screen_in_force(name, session)
    if screen is None or str(screen.signal or "") not in VALUE_SET_SIGNALS:
        return []
    if _research_blocks(screen.research_verdict):
        return []
    if options.apply_f9 and not _f9_ok(
        _f9_in_force(spec, session), require_memo=options.f9_require_memo
    ):
        return []
    flags = _price_flags_at(name, session)
    if not flags or not flags["primary"]:
        return []
    if _stale(options, session):
        return []
    present, decline, sector = _gate_verdicts(name, session, options)
    if not present:
        return []
    decline_fail = decline == "declining"
    sector_fail = sector == "headwind"
    kinds: list[str] = []
    if decline_fail and (sector == "sound" or sector_fail):
        kinds.append(COLUMN_DECLINE_SHADOW)
    if sector_fail and (decline == "clear" or decline_fail):
        kinds.append(COLUMN_SECTOR_SHADOW)
    return kinds


def _open_position(name: _Name, column: str) -> _Position | None:
    for position in name.open_positions:
        if position.column == column and position.status == "open":
            return position
    return None


def _pending(name: _Name, column: str) -> bool:
    return any(item.column == column for item in name.pendings)


def _book_busy(name: _Name, column: str) -> bool:
    """One open or pending episode per column across specs that share a ``book_key``."""
    return any(
        (other.open_positions and _open_position(other, column)) or _pending(other, column)
        for other in name.siblings
    )


def _memo_outcome(spec: NameSpec, fill_session: date) -> tuple[str, MemoFact | None]:
    # Section 2: earlier than the fill session's close in the market's zone.
    cutoff = _cash_close(spec.market, fill_session)
    if cutoff is None:
        return "memo_not_ready", None
    ready = [memo for memo in spec.memos if _aware(memo.finished_at) <= cutoff]
    if not ready:
        return "memo_not_ready", None
    latest = max(ready, key=lambda memo: _aware(memo.finished_at))
    age = _memo_age_days(_aware(latest.finished_at), now=cutoff)
    if age is None or age > float(MEMO_MAX_AGE_DAYS):
        return "memo_not_ready", latest
    if _research_blocks(latest.verdict):
        return "memo_blocked", latest
    return "ok", latest


def _is_late(
    spec: NameSpec, signal_session: date, fill_session: date, options: WalkOptions
) -> bool:
    if not options.apply_late_signal or spec.signal_seen_at is None:
        return False
    seen = spec.signal_seen_at.get(signal_session)
    if seen is None:
        return False
    # The next session's cash close. An unknown market cannot be filled.
    cutoff = _cash_close(spec.market, fill_session)
    if cutoff is None:
        return True
    return _aware(seen) > cutoff


def _breadth_bucket(sources: dict[str, int] | None) -> str:
    if not sources:
        return "none"
    growth = int(sources.get("screen_earnings_growth") or 0)
    decline = int(sources.get("decline_store") or 0)
    total = growth + decline
    if total <= 0 or growth <= 0:
        return "none"
    if growth / total < 0.5:
        return "under_half"
    return "half_or_more"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _last_returns(closes: list[float], count: int) -> list[float]:
    """The last ``count`` one-session returns, skipping a zero previous close."""
    found: list[float] = []
    index = len(closes) - 1
    while index >= 1 and len(found) < count:
        if closes[index - 1]:
            found.append(closes[index] / closes[index - 1] - 1.0)
        index -= 1
    found.reverse()
    return found


def _price_features(
    closes: list[float], highs: list[float] | None, *, rsi: Any = None, rsi_given: bool = False
) -> dict[str, Any]:
    """Price features on the prefix through the signal session.

    Every feature reads at most the last 252 rows, so a caller may pass a
    tail of ``_FEATURE_TAIL`` rows with ``rsi`` from the full prefix.
    """
    features: dict[str, Any] = {
        "vol_60": None,
        "close_vs_sma200": None,
        "fall_from_high_252": None,
        "return_126": None,
        "range_pos_126": None,
        "return_20": None,
        "rsi_14": None,
    }
    if len(closes) >= 2:
        rets = _last_returns(closes, 60)
        if len(rets) >= 60:
            features["vol_60"] = statistics.pstdev(rets[-60:])
    if len(closes) >= REGIME_SMA_SESSIONS:
        sma = sum(closes[-REGIME_SMA_SESSIONS:]) / REGIME_SMA_SESSIONS
        if sma:
            features["close_vs_sma200"] = closes[-1] / sma - 1.0
    if len(closes) >= 252:
        window_high = max(highs[-252:]) if highs and len(highs) >= 252 else max(closes[-252:])
        if window_high:
            features["fall_from_high_252"] = closes[-1] / window_high - 1.0
    if len(closes) > 126 and closes[-127]:
        features["return_126"] = closes[-1] / closes[-127] - 1.0
        sample = closes[-126:]
        span = max(sample) - min(sample)
        features["range_pos_126"] = None if span <= 0 else (closes[-1] - min(sample)) / span
    if len(closes) > 20 and closes[-21]:
        features["return_20"] = closes[-1] / closes[-21] - 1.0
    if rsi_given:
        features["rsi_14"] = rsi
    else:
        features["rsi_14"] = price_flags(closes)["rsi"]
    return features


def _snapshot_price_features(name: _Name, session: date) -> dict[str, Any]:
    download = name.prices.download_for(session)
    highs_ok = bool(
        download is not None and download.highs and len(download.highs) == len(download.sessions)
    )
    if download is not None and not download._dups:
        count = download.count_through(session)
        start = max(0, count - _FEATURE_TAIL)
        closes = download.closes[start:count]
        if 0.0 not in closes or start == 0:
            highs = download.highs[start:count] if highs_ok else None
            return _price_features(closes, highs, rsi=download.rsi_at(count), rsi_given=True)
    _download, days, closes = name.prices.prefix(session)
    highs = None
    if highs_ok:
        highs = [
            high
            for day, high in zip(download.sessions, download.highs, strict=False)
            if day <= session
        ]
    return _price_features(closes, highs)


def _snapshot(
    name: _Name,
    session: date,
    *,
    memo: MemoFact | None,
    options: WalkOptions,
) -> dict[str, Any]:
    spec = name.spec
    screen = _screen_in_force(name, session)
    gate = _gate_in_force(name, session)
    features = _snapshot_price_features(name, session)
    payload: dict[str, Any] = {
        "signal_session": session.isoformat(),
        "screen_run_date": screen.run_date.isoformat() if screen else None,
        "gate_as_of": gate.as_of.isoformat() if gate else None,
        "market": spec.market,
    }
    if screen is not None:
        payload["signal"] = screen.signal
        payload["adjusted_signal"] = screen.adjusted_signal
        payload["research_verdict"] = screen.research_verdict
        payload["research_confidence"] = screen.research_confidence
        payload["sector"] = screen.sector or (gate.sector_name if gate else None)
        for key, value in screen.fields.items():
            payload[key] = value
    if gate is not None:
        payload["sector_basis"] = gate.sector_basis
        payload["region"] = gate.region
        payload["earnings_breadth_sources"] = gate.earnings_breadth_sources
        payload["sector_inputs"] = gate.sector_inputs
        payload["decline_checks"] = gate.checks
        payload["soft_checks"] = list(gate.soft_checks or [])
        revenue = (gate.checks or {}).get("revenue") if gate.checks else None
        if isinstance(revenue, dict):
            payload["revenue_change_pct"] = revenue.get("change_pct")
    if memo is not None:
        closed_at = _cash_close(spec.market, session)
        payload["memo_age_days"] = (
            None if closed_at is None else _memo_age_days(_aware(memo.finished_at), now=closed_at)
        )
        payload["memo_by_signal_job"] = bool(memo.by_signal_job)
    else:
        payload["memo_age_days"] = None
        payload["memo_by_signal_job"] = False
    payload.update(features)
    # Files dated on or after the signal session are not in force, so they are absent.
    payload["inputs_not_after_signal"] = True
    if screen is not None and screen.run_date >= session:
        payload["inputs_not_after_signal"] = False
    if gate is not None and gate.as_of >= session:
        payload["inputs_not_after_signal"] = False
    return payload


def _channels(name: _Name, session: date) -> dict[str, Any]:
    download = name.prices.download_for(session)
    if download is None:
        return {"channel_status": "no_bar_on_or_before_as_of"}
    highs = (
        download.highs if download.highs and len(download.highs) == len(download.sessions) else None
    )
    lows = download.lows if download.lows and len(download.lows) == len(download.sessions) else None
    count = download.count_through(session)
    if count <= 0:
        return {"channel_status": "no_bar_on_or_before_as_of"}
    start = 0
    if not download._dups and count > _FEATURE_TAIL:
        # ``channel_columns`` reads the last 252 rows; only ``bars`` needs the rest.
        start = count - _FEATURE_TAIL
    days = download.sessions[start:count]
    if download._dups:
        closes = [download.closes[download.find(day)] for day in days]
    else:
        closes = download.closes[start:count]
    out = channel_columns(
        [day.isoformat() for day in days],
        closes,
        None if highs is None else highs[start:count],
        None if lows is None else lows[start:count],
        as_of=session.isoformat(),
    )
    if start and out.get("channel_status") == "ok":
        out["bars"] = int(out["bars"]) + download.channel_bars_before(start)
    return out


def _bench_flags(name: _Name, session: date, snapshot: dict[str, Any]) -> dict[str, bool]:
    _download, _count, closes = name.prices.tail(session, DEEP_DIP_LOOKBACK + 1)
    deep = False
    if len(closes) > DEEP_DIP_LOOKBACK and closes[-1 - DEEP_DIP_LOOKBACK]:
        prior = closes[-1 - DEEP_DIP_LOOKBACK]
        deep = closes[-1] <= prior * (1.0 - DEEP_DIP_DROP)
    change = _finite(snapshot.get("revenue_change_pct"))
    adjusted = snapshot.get("adjusted_signal")
    return {
        "deep_dip": deep,
        "revenue_growing": change is not None and change > 0,
        "fcf_agrees": str(adjusted or "") in VALUE_SET_SIGNALS,
    }


def _sma_above(closes: list[float]) -> bool:
    sma = sum(closes[-REGIME_SMA_SESSIONS:]) / REGIME_SMA_SESSIONS
    return bool(sma and closes[-1] > sma)


class _RegimeTable:
    """Per-session counts behind ``_regime`` for one market, built in one pass.

    Only for names with one download and no repeated dates. A window mean
    within 1e-9 of the close is recomputed with ``_sma_above`` itself, so a
    rounding difference cannot flip a name.
    """

    def __init__(self, names: list[_Name], market: str) -> None:
        self.counted: dict[int, int] = defaultdict(int)
        self.above: dict[int, int] = defaultdict(int)
        for name in names:
            if name.spec.market == market and not name.refusal:
                self.add(name)

    def add(self, name: _Name) -> None:
        window = REGIME_SMA_SESSIONS
        download = name.prices.downloads[0]
        closes = np.asarray(download.closes, dtype="float64")
        if len(closes) < window:
            return
        sums = np.convolve(closes, np.ones(window), mode="valid")
        means = sums / window
        last = closes[window - 1 :]
        gap = last - means
        near = np.abs(gap) <= 1e-9 * np.maximum(np.abs(last), 1.0)
        flags = (gap > 0) & (means != 0)
        for offset in np.nonzero(near)[0]:
            end = int(offset) + window
            flags[offset] = _sma_above(download.closes[:end])
        for offset, day in enumerate(download.sessions[window - 1 :]):
            key = day.toordinal()
            self.counted[key] += 1
            if flags[offset]:
                self.above[key] += 1

    @staticmethod
    def usable(names: list[_Name], market: str) -> bool:
        return all(
            len(name.prices.downloads) == 1 and not name.prices.downloads[0]._dups
            for name in names
            if name.spec.market == market and not name.refusal
        )

    def counts(self, session: date) -> tuple[int, int]:
        key = session.toordinal()
        return self.counted.get(key, 0), self.above.get(key, 0)


def _regime(names: list[_Name], market: str, session: date) -> str:
    cross = getattr(names, "cross", None)
    if cross is not None:
        return cross.regime(market, session)
    cache = getattr(names, "regime_cache", None)
    if cache is not None and (market, session) in cache:
        return cache[(market, session)]
    tables = getattr(names, "regime_tables", None)
    if tables is not None and market not in tables:
        tables[market] = _RegimeTable(names, market) if _RegimeTable.usable(names, market) else None
    table = tables.get(market) if tables is not None else None
    if table is not None:
        counted, above = table.counts(session)
    else:
        counted = 0
        above = 0
        for name in names:
            if name.spec.market != market or name.refusal:
                continue
            _download, _days, closes = name.prices.prefix(session)
            if len(closes) < REGIME_SMA_SESSIONS:
                continue
            counted += 1
            if _sma_above(closes):
                above += 1
    label = _regime_label(counted, above)
    if cache is not None:
        cache[(market, session)] = label
    return label


def _regime_label(counted: int, above: int) -> str:
    if counted < REGIME_MIN_NAMES:
        return "regime_unknown"
    if above / counted >= REGIME_ABOVE_SHARE:
        return "above"
    return "below"


def _log(
    position: _Position,
    session: date,
    index: int,
    close: float,
    entry_px: float,
    action: str,
    reasons: list[str] | None = None,
) -> None:
    row: dict[str, Any] = {
        "session": session.isoformat(),
        "index": index,
        "close": close,
        "entry_fill": entry_px,
        "action": action,
        "launched": position.launched,
        "floor": position.floor,
        "highest_checkpoint": position.highest_checkpoint,
        "recovery": position.recovery,
    }
    if reasons:
        row["reasons"] = list(reasons)
    position.decision_log.append(row)


def _raise_floor(position: _Position, index: int, session: date, gain: float) -> None:
    checkpoint = highest_checkpoint(gain)
    if checkpoint is None:
        return
    if not position.launched:
        position.launched = True
        position.launch_index = index
        position.launch_session = session
    if position.highest_checkpoint is None or checkpoint > position.highest_checkpoint:
        position.highest_checkpoint = checkpoint
        position.floor = floor_for_checkpoint(checkpoint)
        if gain > CHECKPOINTS[-1][0]:
            position.floor = FLOOR_AT_OR_ABOVE_LAST
        position.floor_history.append(
            {
                "index": index,
                "session": session.isoformat(),
                "checkpoint": checkpoint,
                "floor": position.floor,
            }
        )


def _review_decision(
    *,
    gate: GateFact | None,
    screen: ScreenFact | None,
    review_number: int | None,
    comparison: bool,
    require_gates: bool,
) -> str | None:
    """Section 5 review table. A single unconfirmed avoid does not sell.

    When the walk is not applying gates (archive buy-tier rehearsal), a missing
    gate is not a review failure. A gate that is present and not clear/sound
    still ends the hold.
    """
    gates_bad = gate is None or gate.decline != "clear" or gate.sector != "sound"
    if require_gates and gates_bad:
        return EXIT_REVIEW_INSUFFICIENT
    if gate is not None and (gate.decline != "clear" or gate.sector != "sound"):
        return EXIT_REVIEW_INSUFFICIENT
    if screen is None:
        return EXIT_REVIEW_INSUFFICIENT
    signal = str(screen.signal or "").strip().lower()
    research_missing = screen.research_verdict is None or str(screen.research_verdict).strip() == ""
    research_failed = _research_blocks(screen.research_verdict)
    gates_ok = not require_gates or (
        gate is not None and gate.decline == "clear" and gate.sector == "sound"
    )
    hold = gates_ok and signal != "avoid" and not research_failed
    research_hold = hold or (research_missing and gates_ok and signal != "avoid")
    if comparison and review_number is not None and review_number >= DRAFT_REVIEW_COUNT:
        if screen is None or (require_gates and gates_bad):
            return EXIT_REVIEW_INSUFFICIENT
        return EXIT_REVIEW_CAP
    if research_hold or hold:
        return None
    if signal == "avoid" or research_failed:
        return None
    return EXIT_REVIEW_INSUFFICIENT


def _step_primary(
    position: _Position,
    *,
    index: int,
    session: date,
    close: float,
    entry_px: float,
    reasons: list[str],
    gate: GateFact | None,
    screen: ScreenFact | None,
    require_gates: bool,
) -> str | None:
    if reasons:
        position.pending_reasons = list(reasons)
        _log(position, session, index, close, entry_px, EXIT_THESIS, reasons)
        return EXIT_THESIS
    gain = close / entry_px - 1.0 if entry_px else 0.0
    before = position.floor
    _raise_floor(position, index, session, gain)
    if position.launched and before != position.floor:
        _log(position, session, index, close, entry_px, "checkpoint")
    elif position.launched and position.launch_session == session:
        _log(position, session, index, close, entry_px, "launch")
    if (
        position.launched
        and position.floor is not None
        and close <= entry_px * (1.0 + position.floor)
    ):
        _log(position, session, index, close, entry_px, EXIT_FLOOR)
        return EXIT_FLOOR
    if not position.launched and index >= FAIL_TO_LAUNCH_INDEX:
        _log(position, session, index, close, entry_px, EXIT_FAIL_TO_LAUNCH)
        return EXIT_FAIL_TO_LAUNCH
    if index >= TIME_CAP_INDEX:
        _log(position, session, index, close, entry_px, EXIT_TIME_CAP)
        return EXIT_TIME_CAP
    if index in REVIEW_INDEXES:
        decision = _review_decision(
            gate=gate,
            screen=screen,
            review_number=None,
            comparison=False,
            require_gates=require_gates,
        )
        position.reviews.append(
            {
                "index": index,
                "session": session.isoformat(),
                "action": decision or "hold",
            }
        )
        if decision:
            _log(position, session, index, close, entry_px, decision)
            return decision
    if not position.launched and close <= entry_px * (1.0 - RECOVERY_DROP):
        if not position.recovery:
            position.recovery = True
            _log(position, session, index, close, entry_px, "recovery_label")
    return None


def _step_draft(
    position: _Position,
    *,
    index: int,
    session: date,
    close: float,
    entry_px: float,
    reasons: list[str],
    recent: list[float],
    gate: GateFact | None,
    screen: ScreenFact | None,
    buy: float,
    sell: float,
    require_gates: bool,
) -> str | None:
    if reasons:
        position.pending_reasons = list(reasons)
        _log(position, session, index, close, entry_px, EXIT_THESIS, reasons)
        return EXIT_THESIS
    if position.phase == "swing":
        threshold = entry_px * (1.0 + buy + sell)
        is_high = len(recent) >= DRAFT_HIGH_WINDOW and close == max(recent[-DRAFT_HIGH_WINDOW:])
        if is_high and close >= threshold:
            return EXIT_SWING_HIGH
        if close <= entry_px * (1.0 - RECOVERY_DROP) or index >= DRAFT_SWING_LIMIT_INDEX:
            position.phase = "recovery"
            position.recovery = True
            position.recovery_index = index
    if position.phase == "recovery":
        if close >= entry_px:
            return EXIT_RECOVERY_TARGET
        if position.recovery_index is not None:
            elapsed = index - position.recovery_index
            if elapsed > 0 and elapsed % DRAFT_REVIEW_SPACING == 0:
                review_number = elapsed // DRAFT_REVIEW_SPACING
                decision = _review_decision(
                    gate=gate,
                    screen=screen,
                    review_number=review_number,
                    comparison=True,
                    require_gates=require_gates,
                )
                position.reviews.append(
                    {
                        "index": index,
                        "session": session.isoformat(),
                        "review_number": review_number,
                        "action": decision or "hold",
                    }
                )
                if decision:
                    return decision
    return None


def _step_ladder(
    position: _Position,
    *,
    index: int,
    session: date,
    close: float,
    entry_px: float,
    reasons: list[str],
    gate: GateFact | None,
    screen: ScreenFact | None,
    require_gates: bool,
) -> str | None:
    if reasons:
        position.pending_reasons = list(reasons)
        _log(position, session, index, close, entry_px, EXIT_THESIS, reasons)
        return EXIT_THESIS
    gain = close / entry_px - 1.0 if entry_px else 0.0
    _raise_floor(position, index, session, gain)
    if (
        position.launched
        and position.floor is not None
        and close <= entry_px * (1.0 + position.floor)
    ):
        return EXIT_FLOOR
    if position.launched and index >= TIME_CAP_INDEX:
        return EXIT_TIME_CAP
    if position.launched and index in REVIEW_INDEXES:
        decision = _review_decision(
            gate=gate,
            screen=screen,
            review_number=None,
            comparison=False,
            require_gates=require_gates,
        )
        position.reviews.append(
            {"index": index, "session": session.isoformat(), "action": decision or "hold"}
        )
        if decision:
            return decision
    # Unlaunched: draft review timing only. It does not sell at the entry fill.
    if not position.launched:
        if position.recovery_index is None and (
            close <= entry_px * (1.0 - RECOVERY_DROP) or index >= DRAFT_SWING_LIMIT_INDEX
        ):
            position.recovery = True
            position.recovery_index = index
        if position.recovery_index is not None:
            elapsed = index - position.recovery_index
            if elapsed > 0 and elapsed % DRAFT_REVIEW_SPACING == 0:
                review_number = elapsed // DRAFT_REVIEW_SPACING
                decision = _review_decision(
                    gate=gate,
                    screen=screen,
                    review_number=review_number,
                    comparison=True,
                    require_gates=require_gates,
                )
                position.reviews.append(
                    {
                        "index": index,
                        "session": session.isoformat(),
                        "review_number": review_number,
                        "action": decision or "hold",
                    }
                )
                if decision:
                    return decision
    return None


def _signal_exit(position: _Position, session: date, reason: str, nxt: date | None) -> None:
    position.pending_exit = reason
    position.pending_exit_session = session
    position.exit_reason = reason
    position.exit_signal_session = session
    if nxt is None:
        position.pending_exit = reason


def _basket(
    names: list[_Name],
    episode_name: _Name,
    signal_session: date,
    entry_session: date,
    exit_session: date,
    entry_px: float,
    exit_px: float,
    vintage: date,
) -> tuple[float | None, dict[str, Any]]:
    """Gross episode return minus the equal-weight basket over the same sessions.

    A name with ``terminal_haircut`` whose last bar falls strictly between the
    entry and the exit is priced at that bar times ``1 + terminal_haircut``.
    """
    market = episode_name.spec.market
    cross = getattr(names, "cross", None)
    if cross is not None:
        return cross.basket(
            market, signal_session, entry_session, exit_session, entry_px, exit_px, vintage
        )
    options = getattr(names, "options", None)
    members: list[tuple[_Name, ScreenFact]] = []
    screened: list[_Name] = []
    for name, screen in _basket_candidates(names, market, signal_session, options):
        if name.prices.download_for(entry_session) is None:
            continue
        if (
            name.prices.download_for(exit_session) is None
            and _delisted_between(name, entry_session, exit_session) is None
        ):
            continue
        screened.append(name)
        if str(screen.signal or "") in VALUE_SET_SIGNALS:
            members.append((name, screen))
    source = "buy_tier"
    chosen = [name for name, _screen in members]
    if len(chosen) < BASKET_MIN_NAMES:
        source = "whole_screen"
        chosen = screened
    grosses: list[float] = []
    used: list[dict[str, Any]] = []
    for name in chosen:
        download = _vintage_download(name, vintage) or name.prices.download_for(exit_session)
        end_scale = 1.0
        exit_day = exit_session
        if download is None or not download.has(exit_session):
            last = _delisted_between(name, entry_session, exit_session)
            if last is not None:
                download = name.prices.download_for(last)
                exit_day = last
                end_scale = 1.0 + float(name.spec.terminal_haircut or 0.0)
        if download is None:
            continue
        start = download.close(entry_session)
        end = download.close(exit_day)
        if start is None or end is None or start <= 0:
            continue
        end = end * end_scale if end_scale != 1.0 else end
        gross = end / start - 1.0
        grosses.append(gross)
        used.append({"ticker": name.spec.ticker, "entry": start, "exit": end, "gross": gross})
    detail = {
        "source": source,
        "count": len(grosses),
        "fallback": source == "whole_screen",
        "download_as_of": vintage.isoformat(),
        "members": used if options is None or options.basket_members else None,
    }
    if not grosses or entry_px <= 0:
        return None, detail
    episode_gross = exit_px / entry_px - 1.0
    excess = episode_gross - statistics.fmean(grosses)
    detail["episode_gross"] = episode_gross
    detail["basket_gross"] = statistics.fmean(grosses)
    return excess, detail


def _basket_candidates(
    names: list[_Name], market: str, signal_session: date, options: WalkOptions | None
) -> list[tuple[_Name, ScreenFact]]:
    """Names of ``market`` with a screen row carried onto ``signal_session``."""
    cache = getattr(names, "basket_cache", None)
    key = (market, signal_session)
    if cache is not None and key in cache:
        return cache[key]
    skip_blank = bool(options is not None and options.basket_skips_blank_screen)
    found: list[tuple[_Name, ScreenFact]] = []
    for name in names:
        if name.spec.market != market or name.refusal or not name.prices.calendar:
            continue
        screen = _screen_in_force(name, signal_session)
        if screen is None:
            continue
        if skip_blank and not str(screen.signal or "").strip():
            continue
        if not _in_universe(name, signal_session):
            continue
        found.append((name, screen))
    if cache is not None:
        if len(cache) >= _BASKET_CACHE_KEYS:
            cache.pop(next(iter(cache)))
        cache[key] = found
    return found


# About a year of signal sessions per market; older keys are rebuilt on demand.
_BASKET_CACHE_KEYS = 600


def _delisted_between(name: _Name, entry_session: date, exit_session: date) -> date | None:
    """Last bar of a delisted name when it falls strictly inside the holding."""
    if name.spec.terminal_haircut is None or not name.prices.calendar:
        return None
    last = name.prices.calendar[-1]
    return last if entry_session < last < exit_session else None


class _Book(list):
    """The walk's names plus caches shared by every episode of one walk."""

    def __init__(self, names: list[_Name], options: WalkOptions) -> None:
        super().__init__(names)
        self.options = options
        self.basket_cache: dict[tuple[str, date], list[tuple[_Name, ScreenFact]]] = {}
        self.regime_cache: dict[tuple[str, date], str] = {}
        self.regime_tables: dict[str, _RegimeTable | None] = {}
        self.cross: CrossNameTape | None = None


# Signal sessions of controls fall up to MAX_FILL_GAP_CALENDAR_DAYS before the first
# entry session; the tape keeps this many days before ``entry_not_before``.
_CROSS_MARGIN_DAYS = 60


class CrossNameTape:
    """What one name's walk reads about the other names, so the book can be walked in batches.

    ``walk_book`` reads other names in two places: the matched basket (every
    name of the market with a screen row carried onto the signal session) and
    the market regime. This tape holds both for the whole book in compact
    arrays: closes on the walk's sessions, a basket-candidate code per session,
    each name's last bar, and the regime counts. ``walk_book(batch, cross=tape)``
    then walks a subset of names and prices baskets and regimes as the
    whole-book walk does. Specs sharing a ``book_key`` must be in one batch.

    Add every spec with ``add`` (in batches), call ``finish``, then walk.
    """

    def __init__(self, options: WalkOptions) -> None:
        self.options = options
        start = options.entry_not_before
        self._start = (
            None if start is None else (start - timedelta(days=_CROSS_MARGIN_DAYS)).toordinal()
        )
        self._pending: list[dict[str, Any]] = []
        self._days: set[int] = set()
        self._regimes: dict[str, _RegimeTable] = {}
        self.book_keys: Counter[str] = Counter()
        self.calendar: list[date] = []
        self.markets: dict[str, np.ndarray] = {}
        self.tickers: list[str] = []
        self._finished = False

    def add(self, specs: Iterable[NameSpec]) -> None:
        if self._finished:
            raise ValueError("cross-name tape already finished")
        skip_blank = self.options.basket_skips_blank_screen
        for spec in specs:
            book = PriceBook(_downloads_of(spec))
            if len(book.downloads) > 1 or (book.downloads and book.downloads[0]._dups):
                raise ValueError(
                    f"{spec.market}:{spec.ticker}: a batched walk needs one download per name "
                    "without repeated dates"
                )
            refusal = series_refusal(book.calendar) if book.calendar else "no_chart"
            name = _Name(spec=spec, prices=book, refusal=refusal)
            if spec.book_key:
                self.book_keys[spec.book_key] += 1
            ords = np.fromiter((day.toordinal() for day in book.calendar), dtype=np.int64)
            self._days.update(ords.tolist())
            row: dict[str, Any] = {
                "market": spec.market,
                "ticker": spec.ticker,
                "haircut": spec.terminal_haircut,
                "candidate": not refusal and bool(book.calendar),
                "last_ord": int(ords[-1]) if len(ords) else 0,
                "last_close": float(book.downloads[0].closes[-1]) if len(ords) else math.nan,
            }
            if row["candidate"]:
                keep = ords >= self._start if self._start is not None else slice(None)
                row["ords"] = ords[keep]
                row["closes"] = np.asarray(book.downloads[0].closes, dtype=np.float64)[keep]
                row["run_ords"] = np.fromiter(
                    (day.toordinal() for day in name.run_dates), dtype=np.int64
                )
                codes = np.zeros(len(name.run_dates), dtype=np.int8)
                for position, first in enumerate(name.tie_first):
                    signal = str(name.screens[first].signal or "")
                    if skip_blank and not signal.strip():
                        continue
                    codes[position] = 2 if signal in VALUE_SET_SIGNALS else 1
                row["codes"] = codes
                row["universe"] = (
                    None
                    if name.universe is None
                    else (
                        np.array([a.toordinal() for a, _b in name.universe], dtype=np.int64),
                        np.array([b.toordinal() for _a, b in name.universe], dtype=np.int64),
                    )
                )
                self._regimes.setdefault(spec.market, _RegimeTable([], spec.market)).add(name)
            self._pending.append(row)

    def finish(self) -> CrossNameTape:
        """Lay the added names out as matrices over the walk's sessions and screen dates."""
        if self._finished:
            return self
        self.calendar = [date.fromordinal(day) for day in sorted(self._days)]
        grid = set(self._days)
        for row in self._pending:
            if row["candidate"]:
                grid.update(row["run_ords"].tolist())
        if self._start is not None:
            grid = {day for day in grid if day >= self._start}
        self._grid = np.array(sorted(grid), dtype=np.int64)
        self._row = {int(day): index for index, day in enumerate(self._grid.tolist())}
        rows, width = len(self._grid), len(self._pending)
        self._close = np.full((rows, width), np.nan, dtype=np.float64)
        self._codes = np.zeros((rows, width), dtype=np.int8)
        self._last_ord = np.zeros(width, dtype=np.int64)
        self._last_close = np.full(width, np.nan, dtype=np.float64)
        self._haircut = np.full(width, np.nan, dtype=np.float64)
        by_market: dict[str, list[int]] = defaultdict(list)
        for column, row in enumerate(self._pending):
            by_market[row["market"]].append(column)
            self.tickers.append(row["ticker"])
            self._last_ord[column] = row["last_ord"]
            self._last_close[column] = row["last_close"]
            if row["haircut"] is not None:
                self._haircut[column] = float(row["haircut"])
            if not row["candidate"]:
                continue
            self._close[np.searchsorted(self._grid, row["ords"]), column] = row["closes"]
            position = np.searchsorted(row["run_ords"], self._grid, side="left") - 1
            codes = np.where(position >= 0, row["codes"][np.maximum(position, 0)], 0)
            if row["universe"] is not None:
                starts, ends = row["universe"]
                if len(starts):
                    span = np.searchsorted(starts, self._grid, side="right") - 1
                    inside = (span >= 0) & (self._grid <= ends[np.maximum(span, 0)])
                else:
                    inside = np.zeros(rows, dtype=bool)
                codes = np.where(inside, codes, 0)
            self._codes[:, column] = codes
        self._pending = []
        self.markets = {
            market: np.array(columns, dtype=np.int64) for market, columns in by_market.items()
        }
        self._finished = True
        return self

    def with_haircuts(self, haircuts: Callable[[str], float | None]) -> CrossNameTape:
        """The same tape with each name's ``terminal_haircut`` replaced (a delisting variant)."""
        if not self._finished:
            raise ValueError("finish the cross-name tape first")
        view = copy.copy(self)
        values = [haircuts(ticker) for ticker in self.tickers]
        view._haircut = np.array(
            [math.nan if value is None else float(value) for value in values], dtype=np.float64
        )
        return view

    def _index(self, day: date) -> int:
        index = self._row.get(day.toordinal())
        if index is None:
            raise ValueError(f"{day} is outside the cross-name tape")
        return index

    def regime(self, market: str, session: date) -> str:
        table = self._regimes.get(market)
        counted, above = table.counts(session) if table is not None else (0, 0)
        return _regime_label(counted, above)

    def basket(
        self,
        market: str,
        signal_session: date,
        entry_session: date,
        exit_session: date,
        entry_px: float,
        exit_px: float,
        vintage: date,
    ) -> tuple[float | None, dict[str, Any]]:
        """``_basket`` over every name of ``market`` in the tape."""
        columns = self.markets.get(market, np.zeros(0, dtype=np.int64))
        codes = self._codes[self._index(signal_session), columns]
        start = self._close[self._index(entry_session), columns]
        end = self._close[self._index(exit_session), columns]
        has_entry = ~np.isnan(start)
        has_exit = ~np.isnan(end)
        haircut = self._haircut[columns]
        last = self._last_ord[columns]
        delisted = (
            ~np.isnan(haircut)
            & (last > entry_session.toordinal())
            & (last < exit_session.toordinal())
        )
        screened = (codes > 0) & has_entry & (has_exit | delisted)
        members = screened & (codes == 2)
        source = "buy_tier"
        chosen = members
        if int(members.sum()) < BASKET_MIN_NAMES:
            source = "whole_screen"
            chosen = screened
        end = np.where(has_exit, end, self._last_close[columns] * (1.0 + np.nan_to_num(haircut)))
        used = chosen & (start > 0)
        grosses_array = end[used] / start[used] - 1.0
        grosses = grosses_array.tolist()
        detail: dict[str, Any] = {
            "source": source,
            "count": len(grosses),
            "fallback": source == "whole_screen",
            "download_as_of": vintage.isoformat(),
            "members": [
                {
                    "ticker": self.tickers[int(column)],
                    "entry": float(a),
                    "exit": float(b),
                    "gross": g,
                }
                for column, a, b, g in zip(
                    columns[used].tolist(), start[used], end[used], grosses, strict=True
                )
            ]
            if self.options.basket_members
            else None,
        }
        if not grosses or entry_px <= 0:
            return None, detail
        episode_gross = exit_px / entry_px - 1.0
        mean = statistics.fmean(grosses)
        detail["episode_gross"] = episode_gross
        detail["basket_gross"] = mean
        return episode_gross - mean, detail

    def check_batch(self, names: list[_Name]) -> None:
        """Every spec of each ``book_key`` in the batch is in the batch."""
        present = Counter(name.spec.book_key for name in names if name.spec.book_key)
        for key, count in present.items():
            if count != self.book_keys.get(key, 0):
                raise ValueError(f"book_key {key!r} is split across batches")


def recovery_cap(
    calendar: list[date], open_counts: Sequence[int], labelled_counts: Sequence[int]
) -> tuple[int, list[dict[str, Any]]]:
    """Cap days and share samples from per-session open and recovery-labelled primary counts."""
    cap_days = 0
    samples: list[dict[str, Any]] = []
    for session, open_count, labelled in zip(calendar, open_counts, labelled_counts, strict=True):
        if not open_count:
            continue
        share = labelled / open_count
        if open_count >= RECOVERY_SHARE_MIN_OPEN and share >= RECOVERY_SHARE_LINE:
            cap_days += 1
            samples.append(
                {
                    "session": session.isoformat(),
                    "share": share,
                    "open": open_count,
                    "blocked": CAP_BLOCKS_ENTRIES,
                }
            )
    return cap_days, samples


def _vintage_download(name: _Name, vintage: date) -> Download | None:
    matches = [download for download in name.prices.downloads if download.as_of == vintage]
    if matches:
        return matches[0]
    return None


def _attach_costs(position: _Position) -> None:
    costs = costs_for_market(position.market)
    position.buy_cost_pct = float(costs.buy_pct)
    position.sell_cost_pct = float(costs.sell_pct)
    position.currency = costs.currency
    position.stake = float(STAKE_UNITS)


def _open_position_record(
    name: _Name,
    *,
    column: str,
    signal_session: date,
    fill_session: date,
    entry_px: float,
    download: Download,
    options: WalkOptions,
    memo: MemoFact | None,
    names: list[_Name],
) -> _Position:
    spec = name.spec
    screen = _screen_in_force(name, signal_session)
    gate = _gate_in_force(name, signal_session)
    # Paired columns share one signal session: snapshot and channels once.
    snapshot_key = (signal_session, id(memo))
    snapshot = name._entry_cache.get(snapshot_key)
    if snapshot is None:
        snapshot = _snapshot(name, signal_session, memo=memo, options=options)
        name._entry_cache[snapshot_key] = snapshot
    channels = name._channel_cache.get(signal_session)
    if channels is None:
        channels = _channels(name, signal_session)
        name._channel_cache[signal_session] = channels
    inputs, missing = _hash_inputs(spec, "entry")
    position = _Position(
        column=column,
        market=spec.market,
        ticker=spec.ticker,
        signal_session=signal_session,
        fill_session=fill_session,
        entry_first_seen=entry_px,
        snapshot=snapshot,
        channels=channels,
        bench=_bench_flags(name, signal_session, snapshot) if column == COLUMN_PRIMARY else {},
        t212=options.t212_label
        if options.t212_label is not None
        else t212_listed(spec.listing, fill_session),
        t212_fetched_at=spec.listing.fetched_at.isoformat()
        if spec.listing and spec.listing.fetched_at
        else None,
        regime=_regime(names, spec.market, signal_session),
        f9_status="f9_unverified" if not options.apply_memo else "pass",
        sector_basis=gate.sector_basis if gate else None,
        region=gate.region if gate else None,
        earnings_breadth_bucket=_breadth_bucket(gate.earnings_breadth_sources) if gate else None,
        adjusted_signal=screen.adjusted_signal if screen else None,
        entry_run=screen.run_date if screen else None,
        download_as_of=download.as_of.isoformat(),
        data_commit=options.data_commit,
    )
    if memo is not None:
        closed_at = _cash_close(position.market, fill_session)
        position.memo_age_days = (
            None if closed_at is None else _memo_age_days(_aware(memo.finished_at), now=closed_at)
        )
        position.memo_by_signal_job = bool(memo.by_signal_job)
        position.memo_verdict = memo.verdict
        position.memo_rationale = memo.rationale
    _attach_costs(position)
    position.inputs = {"entry": inputs, "reviews": [], "exit": None}
    position.provenance_missing = missing
    position.decision_log.append(
        {
            "session": fill_session.isoformat(),
            "index": 0,
            "close": entry_px,
            "entry_fill": entry_px,
            "action": "fill",
            "launched": False,
            "floor": None,
            "download_as_of": download.as_of.isoformat(),
        }
    )
    return position


def _close_position(
    position: _Position,
    name: _Name,
    names: list[_Name],
    session: date,
    close: float,
    download: Download,
) -> None:
    entry_px = download.close(position.fill_session)
    if entry_px is None or entry_px <= 0:
        entry_px = position.entry_first_seen
    position.return_entry = entry_px
    position.exit_fill = close
    position.exit_session = session
    position.status = "closed"
    name.open_positions.remove(position)
    position.fair_cost_return = _fair(entry_px, close, position.market)
    position.gross_return = close / entry_px - 1.0
    position.stress_return = _stress(entry_px, close)
    position.capital_return = position.fair_cost_return
    position.download_as_of = download.as_of.isoformat()
    if position.exit_reason == EXIT_FLOOR and position.floor is not None:
        floor_px = entry_px * (1.0 + position.floor)
        position.gap_shortfall = max(0.0, floor_px - close)
    excess, basket = _basket(
        names,
        name,
        position.signal_session,
        position.fill_session,
        session,
        entry_px,
        close,
        download.as_of,
    )
    position.matched_excess = excess
    position.basket = basket
    exit_inputs, missing = _hash_inputs(name.spec, "exit")
    position.inputs["exit"] = exit_inputs
    if missing:
        position.provenance_missing = True
    if position.column in _ENTRY_COLUMNS or position.column == COLUMN_BUY_ON_SIGNAL:
        name.last_exit_fill[position.column] = session
    elif position.column == COLUMN_PRIMARY:
        name.last_exit_fill[COLUMN_PRIMARY] = session


def _remark_open(position: _Position, name: _Name, names: list[_Name], scoring: date) -> None:
    latest = name.prices.latest()
    if latest is None:
        return
    entry_px = latest.close(position.fill_session)
    calendar = name.prices.calendar
    through = bisect_right(calendar, scoring)
    last_session = calendar[through - 1] if through else None
    if entry_px is None or last_session is None:
        return
    latest_close = latest.close(last_session)
    if latest_close is None:
        return
    position.mark_entry = entry_px
    position.mark_exit = latest_close
    position.capital_return = _fair(entry_px, latest_close, position.market)
    if position.launched and position.floor is not None:
        position.floor_return = _fair(entry_px, entry_px * (1.0 + position.floor), position.market)
    excess, basket = _basket(
        names,
        name,
        position.signal_session,
        position.fill_session,
        last_session,
        entry_px,
        entry_px * (1.0 + position.floor)
        if position.launched and position.floor is not None
        else latest_close,
        latest.as_of,
    )
    # Section 1: an open launched episode uses its floor value against the basket
    # at the latest close. Costs cancel, so both sides stay gross.
    if position.launched and position.floor is not None:
        floor_px = entry_px * (1.0 + position.floor)
        rows = basket.get("members")
        if rows is None:
            mean = basket.get("basket_gross")
        else:
            grosses = [row["gross"] for row in rows if row.get("gross") is not None]
            mean = statistics.fmean(grosses) if grosses else None
        if mean is not None and entry_px:
            position.matched_excess = (floor_px / entry_px - 1.0) - mean
            basket = dict(basket)
            basket["episode_gross"] = floor_px / entry_px - 1.0
            basket["marked"] = "floor"
            position.basket = basket
        else:
            position.matched_excess = excess
            position.basket = basket
    else:
        position.matched_excess = excess
        position.basket = basket


def _schedule(
    name: _Name,
    column: str,
    session: date,
    options: WalkOptions,
    events: list[dict[str, Any]],
) -> None:
    if _book_busy(name, column):
        if column == COLUMN_PRIMARY:
            events.append(
                {
                    "kind": "already_open_skip",
                    "market": name.spec.market,
                    "ticker": name.spec.ticker,
                    "session": session.isoformat(),
                }
            )
        return
    if column in _ENTRY_COLUMNS and not _cooldown_open(name, column, session):
        events.append(
            {
                "kind": "cooldown_skip",
                "market": name.spec.market,
                "ticker": name.spec.ticker,
                "session": session.isoformat(),
                "column": column,
            }
        )
        return
    nxt = _next_bar(name.prices.calendar, session)
    if nxt is None:
        kind = "no_next_bar" if options.drop_last_bar else "pending_fill"
        events.append(
            {
                "kind": kind,
                "market": name.spec.market,
                "ticker": name.spec.ticker,
                "session": session.isoformat(),
                "column": column,
            }
        )
        return
    if not _gap_ok(session, nxt):
        events.append(
            {
                "kind": "gap_drop",
                "market": name.spec.market,
                "ticker": name.spec.ticker,
                "session": session.isoformat(),
                "next_session": nxt.isoformat(),
                "column": column,
            }
        )
        return
    name.pendings.append(_Pending(column=column, signal_session=session, fill_session=nxt))


def _fill_entries(
    name: _Name,
    session: date,
    options: WalkOptions,
    names: list[_Name],
    events: list[dict[str, Any]],
) -> None:
    due = [item for item in name.pendings if item.fill_session == session]
    name.pendings = [item for item in name.pendings if item.fill_session != session]
    download = name.prices.download_for(session)
    if download is None:
        return
    close = download.close(session)
    if close is None:
        return
    for pending in due:
        if not _gap_ok(pending.signal_session, session):
            events.append(
                {
                    "kind": "gap_drop",
                    "market": name.spec.market,
                    "ticker": name.spec.ticker,
                    "session": pending.signal_session.isoformat(),
                    "column": pending.column,
                }
            )
            continue
        if _is_late(name.spec, pending.signal_session, session, options):
            seen = (
                name.spec.signal_seen_at.get(pending.signal_session)
                if name.spec.signal_seen_at
                else None
            )
            hours = None
            closed_at = _cash_close(name.spec.market, session)
            if seen is not None and closed_at is not None:
                # Hours after the next session's cash close, the late-signal clock.
                hours = (_aware(seen) - closed_at).total_seconds() / 3600.0
            events.append(
                {
                    "kind": "late_signal",
                    "market": name.spec.market,
                    "ticker": name.spec.ticker,
                    "session": pending.signal_session.isoformat(),
                    "fill_session": session.isoformat(),
                    "hours_after_signal_close": hours,
                    "column": pending.column,
                }
            )
            continue
        memo: MemoFact | None = None
        if options.apply_memo and pending.column in (
            COLUMN_PRIMARY,
            COLUMN_DECLINE_SHADOW,
            COLUMN_SECTOR_SHADOW,
        ):
            outcome, memo = _memo_outcome(name.spec, session)
            if outcome != "ok":
                events.append(
                    {
                        "kind": outcome,
                        "market": name.spec.market,
                        "ticker": name.spec.ticker,
                        "session": pending.signal_session.isoformat(),
                        "fill_session": session.isoformat(),
                        "verdict": None if memo is None else memo.verdict,
                        "rationale": None if memo is None else memo.rationale,
                        "column": pending.column,
                    }
                )
                continue
        elif options.apply_memo:
            outcome, memo = _memo_outcome(name.spec, session)
            if outcome != "ok":
                memo = None
        position = _open_position_record(
            name,
            column=pending.column,
            signal_session=pending.signal_session,
            fill_session=session,
            entry_px=close,
            download=download,
            options=options,
            memo=memo,
            names=names,
        )
        name.positions.append(position)
        name.open_positions.append(position)
        events.append(
            {
                "kind": "filled",
                "market": name.spec.market,
                "ticker": name.spec.ticker,
                "session": pending.signal_session.isoformat(),
                "fill_session": session.isoformat(),
                "column": pending.column,
            }
        )
        if pending.column == COLUMN_PRIMARY:
            for column in (COLUMN_DRAFT, COLUMN_LADDER, COLUMN_LEAVE_TIER):
                paired = _open_position_record(
                    name,
                    column=column,
                    signal_session=pending.signal_session,
                    fill_session=session,
                    entry_px=close,
                    download=download,
                    options=options,
                    memo=memo,
                    names=names,
                )
                paired.bench = {}
                name.positions.append(paired)
                name.open_positions.append(paired)


def _fill_exits(name: _Name, session: date, names: list[_Name]) -> None:
    download = name.prices.download_for(session)
    if download is None:
        return
    close = download.close(session)
    if close is None:
        return
    for position in list(name.open_positions):
        if (
            position.status != "open"
            or not position.pending_exit
            or position.pending_exit_session is None
        ):
            continue
        nxt = _next_bar(name.prices.calendar, position.pending_exit_session)
        if nxt != session:
            continue
        if not _gap_ok(position.pending_exit_session, session):
            position.pending_exit = None
            position.exit_reason = None
            position.exit_signal_session = None
            continue
        position.exit_reason = position.pending_exit
        position.pending_exit = None
        _close_position(position, name, names, session, close, download)


def _step_positions(name: _Name, session: date, options: WalkOptions, names: list[_Name]) -> None:
    download = name.prices.download_for(session)
    if download is None:
        return
    close = download.close(session)
    if close is None:
        return
    _download, _count, closes = name.prices.tail(session, DRAFT_HIGH_WINDOW)
    reasons = _confirmed_reasons(name, options)
    gate = _gate_in_force(name, session) if options.apply_gates else None
    screen = _screen_in_force(name, session)
    costs = costs_for_market(name.spec.market)
    for position in list(name.open_positions):
        if position.status != "open" or position.pending_exit:
            continue
        if position.fill_session > session:
            continue
        index = _index_of(name.prices, position.fill_session, session)
        if index is None:
            continue
        entry_px = download.close(position.fill_session)
        if entry_px is None or entry_px <= 0:
            entry_px = position.entry_first_seen
        action: str | None = None
        if position.column in _LADDER_COLUMNS:
            action = _step_primary(
                position,
                index=index,
                session=session,
                close=close,
                entry_px=entry_px,
                reasons=reasons,
                gate=gate,
                screen=screen,
                require_gates=options.apply_gates,
            )
        elif position.column == COLUMN_DRAFT:
            action = _step_draft(
                position,
                index=index,
                session=session,
                close=close,
                entry_px=entry_px,
                reasons=reasons,
                recent=closes,
                gate=gate,
                screen=screen,
                buy=float(costs.buy_pct),
                sell=float(costs.sell_pct),
                require_gates=options.apply_gates,
            )
        elif position.column == COLUMN_LADDER:
            action = _step_ladder(
                position,
                index=index,
                session=session,
                close=close,
                entry_px=entry_px,
                reasons=reasons,
                gate=gate,
                screen=screen,
                require_gates=options.apply_gates,
            )
        elif position.column == COLUMN_BUY_ON_SIGNAL:
            action = _step_control(position, name, index, session, screen)
            if action == "fill_now":
                position.exit_reason = EXIT_INELIGIBLE_RUNS
                position.exit_signal_session = session
                _close_position(position, name, names, session, close, download)
                continue
        elif position.column == COLUMN_LEAVE_TIER:
            action = _step_leave_tier(position, name, session)
            if action == "fill_now":
                position.exit_reason = EXIT_INELIGIBLE_RUNS
                position.exit_signal_session = session
                _close_position(position, name, names, session, close, download)
                continue
        if action and position.column != COLUMN_LEAVE_TIER:
            nxt = _next_bar(name.prices.calendar, session)
            _signal_exit(position, session, action, nxt)
            if action in {
                EXIT_REVIEW_INSUFFICIENT,
                EXIT_REVIEW_CAP,
                EXIT_THESIS,
            } or action.startswith("review"):
                review_inputs, missing = _hash_inputs(name.spec, "review")
                position.inputs.setdefault("reviews", []).append(
                    {
                        "session": session.isoformat(),
                        "index": index,
                        "inputs": review_inputs,
                        "action": action,
                    }
                )
                if missing:
                    position.provenance_missing = True


def _step_control(
    position: _Position,
    name: _Name,
    index: int,
    session: date,
    screen: ScreenFact | None,
) -> str | None:
    if index >= FAIL_TO_LAUNCH_INDEX:
        return EXIT_HOLD_63
    if position.entry_run is None:
        return None
    runs = _screens_between(name, position.entry_run, session)
    # Also count a run that comes into force today (run_date < session includes it
    # once the cursor has moved). ``runs`` above uses run_date < session.
    streak = 0
    confirming: ScreenFact | None = None
    for fact in runs:
        eligible = str(fact.signal or "") in VALUE_SET_SIGNALS and not _research_blocks(
            fact.research_verdict
        )
        if eligible:
            streak = 0
        else:
            streak += 1
            if streak >= THESIS_CONFIRM_OBSERVATIONS:
                confirming = fact
                break
    if confirming is None:
        return None
    nxt = _next_bar(name.prices.calendar, confirming.run_date)
    if nxt == session and _gap_ok(confirming.run_date, session):
        return "fill_now"
    return None


def _step_leave_tier(position: _Position, name: _Name, session: date) -> str | None:
    if position.entry_run is None:
        return None
    runs = _screens_between(name, position.entry_run, session)
    streak = 0
    confirming: ScreenFact | None = None
    for fact in runs:
        if str(fact.signal or "") in VALUE_SET_SIGNALS:
            streak = 0
        else:
            streak += 1
            if streak >= THESIS_CONFIRM_OBSERVATIONS:
                confirming = fact
                break
    if confirming is None:
        return None
    nxt = _next_bar(name.prices.calendar, confirming.run_date)
    if nxt == session and _gap_ok(confirming.run_date, session):
        return "fill_now"
    return None


def _maybe_control(
    name: _Name,
    session: date,
    options: WalkOptions,
    names: list[_Name],
    events: list[dict[str, Any]],
) -> None:
    if name.refusal or not name.prices.calendar:
        return
    if _book_busy(name, COLUMN_BUY_ON_SIGNAL):
        return
    screen = _screen_in_force(name, session)
    if screen is None:
        return
    if options.entry_not_after is not None and screen.run_date > options.entry_not_after:
        return
    first = _next_bar(name.prices.calendar, screen.run_date)
    if first != session or not _gap_ok(screen.run_date, session):
        return
    ok, _reason = _base_eligible(name, session, options, price=False)
    prev = _screen_in_force(name, screen.run_date)
    if prev is not None:
        prev_session = _next_bar(name.prices.calendar, prev.run_date) or session
        prev_ok, _prev_reason = _base_eligible(name, prev_session, options, price=False)
    else:
        prev_ok = False
    if not ok or prev_ok:
        return
    if not _cooldown_open(name, COLUMN_BUY_ON_SIGNAL, session):
        return
    download = name.prices.download_for(session)
    if download is None or download.close(session) is None:
        return
    memo: MemoFact | None = None
    if options.apply_memo:
        outcome, memo = _memo_outcome(name.spec, session)
        if outcome != "ok":
            events.append(
                {
                    "kind": outcome,
                    "market": name.spec.market,
                    "ticker": name.spec.ticker,
                    "session": screen.run_date.isoformat(),
                    "fill_session": session.isoformat(),
                    "column": COLUMN_BUY_ON_SIGNAL,
                    "verdict": None if memo is None else memo.verdict,
                    "rationale": None if memo is None else memo.rationale,
                }
            )
            return
    position = _open_position_record(
        name,
        column=COLUMN_BUY_ON_SIGNAL,
        signal_session=screen.run_date,
        fill_session=session,
        entry_px=float(download.close(session) or 0.0),
        download=download,
        options=options,
        memo=memo,
        names=names,
    )
    position.entry_run = screen.run_date
    name.positions.append(position)
    name.open_positions.append(position)
    events.append(
        {
            "kind": "buy_on_signal",
            "market": name.spec.market,
            "ticker": name.spec.ticker,
            "session": session.isoformat(),
            "run_date": screen.run_date.isoformat(),
        }
    )


def _recovery_counts(names: list[_Name]) -> tuple[int, int]:
    """(recovery-labelled, all) open primary positions."""
    open_primary = [
        position
        for name in names
        for position in name.open_positions
        if position.column == COLUMN_PRIMARY and position.status == "open"
    ]
    return sum(1 for position in open_primary if position.recovery), len(open_primary)


def _recovery_share(names: list[_Name]) -> tuple[float | None, int]:
    labelled, open_count = _recovery_counts(names)
    if not open_count:
        return None, 0
    return labelled / open_count, open_count


def _note_insufficient(
    name: _Name, session: date, options: WalkOptions, events: list[dict[str, Any]]
) -> None:
    if not options.apply_gates:
        return
    present, decline, sector = _gate_verdicts(name, session, options)
    if not present:
        return
    if decline != "insufficient_data" and sector != "insufficient_data":
        return
    gate = _eligibility_gate(name, session, options)
    if gate.as_of in name.seen_insufficient:
        return
    if not _in_universe(name, session):
        return
    screen = _screen_in_force(name, session)
    if screen is None or str(screen.signal or "") not in VALUE_SET_SIGNALS:
        return
    flags = _price_flags_at(name, session)
    if not flags or not flags["primary"]:
        return
    name.seen_insufficient.add(gate.as_of)
    events.append(
        {
            "kind": "insufficient_data",
            "market": name.spec.market,
            "ticker": name.spec.ticker,
            "session": session.isoformat(),
            "decline": gate.decline,
            "sector": gate.sector,
        }
    )


def _link_siblings(names: list[_Name]) -> None:
    """Specs with one ``book_key`` share the one-open rule and the exit cooldown."""
    groups: dict[str, list[_Name]] = defaultdict(list)
    for name in names:
        if name.spec.book_key:
            groups[name.spec.book_key].append(name)
    for group in groups.values():
        shared: dict[str, date] = {}
        for name in group:
            name.siblings = group
            name.last_exit_fill = shared


def _close_delisted(names: list[_Name], calendar: list[date]) -> None:
    """Registration rehearsal section 4: a delisted name's open episode exits at its last bar.

    The exit is that bar's close times ``1 + terminal_haircut``. An exit already
    signalled keeps its reason; otherwise the reason is ``delisted``.
    """
    if not calendar:
        return
    tape_end = calendar[-1]
    for name in names:
        if name.spec.terminal_haircut is None or not name.open_positions:
            continue
        days = name.prices.calendar
        if not days or days[-1] >= tape_end:
            continue
        last = days[-1]
        download = name.prices.download_for(last)
        if download is None:
            continue
        close = download.close(last)
        if close is None:
            continue
        price = close * (1.0 + float(name.spec.terminal_haircut))
        for position in list(name.open_positions):
            if position.status != "open":
                continue
            if position.pending_exit:
                position.exit_reason = position.pending_exit
                position.pending_exit = None
            else:
                position.exit_reason = EXIT_DELISTED
                position.exit_signal_session = last
            _close_position(position, name, names, last, price, download)


def walk_book(
    specs: list[NameSpec],
    *,
    options: WalkOptions | None = None,
    mode: str | None = None,
    cross: CrossNameTape | None = None,
) -> dict[str, Any]:
    """Walk every name and build the section 8 boards.

    ``mode`` selects a section 9 preset. ``options`` overrides it. The walk
    uses only the facts on ``specs``.

    With ``cross``, ``specs`` is one batch of a larger book: baskets, regimes
    and the session calendar come from the tape, no boards are built, and the
    recovery-share counts are returned per calendar session
    (``recovery_open``, ``recovery_labelled``) for ``recovery_cap`` over all
    batches.
    """
    if mode is not None and options is None:
        options = options_for(mode)
    options = options or WalkOptions()
    if cross is not None and (options.boards or CAP_BLOCKS_ENTRIES):
        raise ValueError("a batched walk needs boards off and a cap that does not block entries")
    built: list[_Name] = []
    for spec in specs:
        downloads = _downloads_of(spec)
        book = PriceBook(downloads)
        refusal = series_refusal(book.calendar) if book.calendar else "no_chart"
        built.append(_Name(spec=spec, prices=book, refusal=refusal))
    names = _Book(built, options)
    if cross is not None:
        cross.check_batch(names)
        names.cross = cross
    _link_siblings(names)
    events: list[dict[str, Any]] = []
    for name in names:
        if name.refusal:
            events.append(
                {
                    "kind": name.refusal,
                    "market": name.spec.market,
                    "ticker": name.spec.ticker,
                }
            )
    if cross is not None:
        calendar = cross.calendar
        recovery_open = array("i", [0]) * len(calendar)
        recovery_labelled = array("i", [0]) * len(calendar)
    else:
        calendar = sorted({day for name in names for day in name.prices.calendar})
    cap_days = 0
    share_samples: list[dict[str, Any]] = []
    for session_index, session in enumerate(calendar):
        if options.entry_not_before is not None and session < options.entry_not_before:
            continue
        for name in names:
            # Without an open or pending episode nothing below changes state;
            # the streaks catch up at the next session that needs them.
            if not name.open_positions and not name.pendings:
                continue
            if not name.prices.has_session(session):
                continue
            _consume_observations(name, session, options)
            _fill_entries(name, session, options, names, events)
            _fill_exits(name, session, names)
            _step_positions(name, session, options, names)
        holding = [name for name in names if name.open_positions]
        entries_open = options.entry_not_after is None or session <= options.entry_not_after
        blocked = False
        if cross is not None:
            labelled, open_count = _recovery_counts(holding)
            recovery_open[session_index] = open_count
            recovery_labelled[session_index] = labelled
            share = None
        else:
            share, open_count = _recovery_share(holding)
        if (
            share is not None
            and open_count >= RECOVERY_SHARE_MIN_OPEN
            and share >= RECOVERY_SHARE_LINE
        ):
            cap_days += 1
            blocked = CAP_BLOCKS_ENTRIES
            share_samples.append(
                {
                    "session": session.isoformat(),
                    "share": share,
                    "open": open_count,
                    "blocked": blocked,
                }
            )
        for name in names:
            if name.refusal or not name.prices.has_session(session):
                continue
            # Every entry path below needs a buy-tier row in force; the control
            # also needs the row's next bar, which a non-buy row cannot open.
            screen = _screen_in_force(name, session)
            if screen is None or str(screen.signal or "") not in VALUE_SET_SIGNALS:
                continue
            if options.include_controls:
                _maybe_control(name, session, options, names, events)
            if not entries_open:
                continue
            _note_insufficient(name, session, options, events)
            if blocked:
                continue
            ok, _reason = _base_eligible(name, session, options, price=True)
            if ok:
                _schedule(name, COLUMN_PRIMARY, session, options, events)
            else:
                for column in _shadow_columns(name, session, options):
                    _schedule(name, column, session, options, events)
            if options.alternative:
                alt_ok, _alt_reason = _base_eligible(name, session, options, price=False)
                flags = _price_flags_at(name, session) if alt_ok else None
                if alt_ok and flags and flags["alternative"]:
                    _schedule(name, COLUMN_ALTERNATIVE, session, options, events)
    _close_delisted(names, calendar)
    scoring = options.scoring_date or (calendar[-1] if calendar else date.today())
    for name in names:
        for position in name.positions:
            if position.status == "open":
                _remark_open(position, name, names, scoring)
            else:
                position.mark_entry = position.return_entry
                position.mark_exit = position.exit_fill
    episodes = [
        _episode_dict(position, name, scoring) for name in names for position in name.positions
    ]
    boards = (
        build_boards(
            episodes,
            events=events,
            scoring_date=scoring,
            cap_would_block_days=cap_days,
            names=names,
            options=options,
        )
        if options.boards
        else None
    )
    result = {
        "registration_id": REGISTRATION_ID,
        "influences_live": INFLUENCES_LIVE,
        "episodes": episodes,
        "events": events,
        "boards": boards,
        "cap_would_block_days": cap_days,
        "recovery_share_samples": share_samples,
        "scoring_date": scoring.isoformat(),
        "counts": _counts(events, episodes),
    }
    if cross is not None:
        result["cap_would_block_days"] = None
        result["recovery_share_samples"] = None
        result["recovery_open"] = recovery_open
        result["recovery_labelled"] = recovery_labelled
    return result


def _held_days(position: _Position, scoring: date) -> int | None:
    end = position.exit_session or scoring
    if position.fill_session is None:
        return None
    return max((end - position.fill_session).days, 0)


def _sessions_after(calendar: list[date], fill: date, scoring: date) -> int:
    """Days with ``fill < day <= scoring`` in a sorted, duplicate-free calendar."""
    if scoring <= fill:
        return 0
    return bisect_right(calendar, scoring) - bisect_right(calendar, fill)


def _episode_dict(position: _Position, name: _Name, scoring: date) -> dict[str, Any]:
    mature = (
        _sessions_after(name.prices.calendar, position.fill_session, scoring) >= MATURITY_SESSIONS
    )
    held = _held_days(position, scoring)
    if position.status == "closed":
        decision_floor = position.fair_cost_return
        decision_close = position.fair_cost_return
    elif position.launched and position.floor_return is not None:
        decision_floor = position.floor_return
        decision_close = position.capital_return
    else:
        decision_floor = position.capital_return
        decision_close = position.capital_return
    return {
        "episode_id": f"{position.market}:{position.ticker}:{position.column}:{position.signal_session.isoformat()}",
        "market": position.market,
        "ticker": position.ticker,
        "column": position.column,
        "status": position.status,
        "signal_session": position.signal_session.isoformat(),
        "fill_session": position.fill_session.isoformat(),
        "entry_fill_first_seen": position.entry_first_seen,
        "return_entry_fill": position.return_entry
        if position.return_entry is not None
        else position.mark_entry,
        "exit_session": None
        if position.exit_session is None
        else position.exit_session.isoformat(),
        "exit_fill": position.exit_fill,
        "exit_reason": position.exit_reason,
        "exit_signal_session": None
        if position.exit_signal_session is None
        else position.exit_signal_session.isoformat(),
        "launched": position.launched,
        "launch_index": position.launch_index,
        "launch_session": None
        if position.launch_session is None
        else position.launch_session.isoformat(),
        "sessions_to_launch": position.launch_index,
        "highest_checkpoint": position.highest_checkpoint,
        "floor": position.floor,
        "floor_history": position.floor_history,
        "recovery_label": position.recovery,
        "fair_cost_return": position.fair_cost_return
        if position.status == "closed"
        else position.capital_return,
        "gross_return": position.gross_return,
        "stress_return": position.stress_return if position.status == "closed" else None,
        "matched_excess": position.matched_excess,
        "basket": position.basket,
        "gap_shortfall": position.gap_shortfall,
        "mature": mature,
        "decision_return_floor": None if not mature else decision_floor,
        "decision_return_close": None if not mature else decision_close,
        "capital_return": position.capital_return
        if position.status == "closed"
        else position.capital_return,
        "held_calendar_days": held,
        "held_sessions": _sessions_after(
            name.prices.calendar, position.fill_session, position.exit_session or scoring
        ),
        "stake": position.stake,
        "buy_cost_pct": position.buy_cost_pct,
        "sell_cost_pct": position.sell_cost_pct,
        "currency": position.currency,
        "t212_listed": position.t212,
        "t212_fetched_at": position.t212_fetched_at,
        "regime": position.regime,
        "f9_status": position.f9_status,
        "sector_basis": position.sector_basis,
        "region": position.region,
        "earnings_breadth_bucket": position.earnings_breadth_bucket,
        "adjusted_signal": position.adjusted_signal,
        "memo_age_days": position.memo_age_days,
        "memo_by_signal_job": position.memo_by_signal_job,
        "memo_verdict": position.memo_verdict,
        "memo_rationale": position.memo_rationale,
        "entry_week": entry_week(position.fill_session),
        "snapshot": position.snapshot,
        "channels": position.channels,
        "bench": position.bench,
        "reviews": position.reviews,
        "decision_log": position.decision_log,
        "inputs": position.inputs,
        "provenance_missing": position.provenance_missing,
        "data_commit": position.data_commit,
        "download_as_of": position.download_as_of,
        "out_of_control_median": position.column == COLUMN_LEAVE_TIER
        and position.status != "closed",
        "pending_exit": position.pending_exit,
    }


def _counts(events: list[dict[str, Any]], episodes: list[dict[str, Any]]) -> dict[str, int]:
    kinds = [
        "filled",
        "memo_not_ready",
        "memo_blocked",
        "late_signal",
        "gap_drop",
        "already_open_skip",
        "thinned",
        "chart_not_daily",
        "no_chart",
        "insufficient_data",
        "no_next_bar",
        "pending_fill",
        "buy_on_signal",
    ]
    counts = {kind: sum(1 for event in events if event.get("kind") == kind) for kind in kinds}
    counts["episodes"] = len(episodes)
    counts["provenance_missing"] = sum(
        1 for episode in episodes if episode.get("provenance_missing")
    )
    return counts


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.fmean(values))


def _primary(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [episode for episode in episodes if episode.get("column") == COLUMN_PRIMARY]


def _mature_primary(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [episode for episode in _primary(episodes) if episode.get("mature")]


def _decision_values(episodes: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for episode in episodes:
        raw = episode.get(key)
        if raw is None:
            continue
        values.append(float(raw))
    return values


def _group_weeks(episodes: list[dict[str, Any]], value_of) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for episode in episodes:
        value = value_of(episode)
        if value is None:
            continue
        grouped[str(episode.get("entry_week"))].append(float(value))
    return grouped


def _paired_board(episodes: list[dict[str, Any]], column: str) -> dict[str, Any]:
    primary = {
        (episode["market"], episode["ticker"], episode["signal_session"]): episode
        for episode in _mature_primary(episodes)
    }
    diffs: list[float] = []
    by_week: dict[str, list[float]] = defaultdict(list)
    better = 0
    for episode in episodes:
        if episode.get("column") != column or not episode.get("mature"):
            continue
        key = (episode["market"], episode["ticker"], episode["signal_session"])
        base = primary.get(key)
        if base is None:
            continue
        left = base.get("decision_return_floor")
        right = episode.get("decision_return_close")
        if left is None or right is None:
            continue
        diff = float(left) - float(right)
        diffs.append(diff)
        by_week[str(base.get("entry_week"))].append(diff)
        if diff > 0:
            better += 1
    return {
        "column": column,
        "n": len(diffs),
        "entry_weeks": len(by_week),
        "median_difference": _median(diffs),
        "mean_difference": _mean(diffs),
        "standard_error": entry_week_standard_error(by_week),
        "share_primary_better": None if not diffs else better / len(diffs),
    }


def _overall(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    mature = _mature_primary(episodes)
    floor_vals = _decision_values(mature, "decision_return_floor")
    close_vals = _decision_values(mature, "decision_return_close")
    return {
        "count": len(mature),
        "median_fair_cost": _median(floor_vals),
        "median_fair_cost_at_latest_close": _median(close_vals),
        "mean_fair_cost": _mean(floor_vals),
    }


def _excess_board(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    mature = _mature_primary(episodes)
    values = [
        float(episode["matched_excess"])
        for episode in mature
        if episode.get("matched_excess") is not None
    ]
    by_week = _group_weeks(mature, lambda episode: episode.get("matched_excess"))
    fallback = sum(1 for episode in mature if (episode.get("basket") or {}).get("fallback"))
    return {
        "count": len(values),
        "median": _median(values),
        "mean": _mean(values),
        "standard_error": entry_week_standard_error(by_week),
        "share_above_zero": None
        if not values
        else sum(1 for value in values if value > 0) / len(values),
        "fallback_baskets": fallback,
    }


def _split_board(episodes: list[dict[str, Any]], key: str, buckets: list[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for bucket in buckets:
        chosen = [episode for episode in _mature_primary(episodes) if episode.get(key) == bucket]
        overall = _overall(chosen) if False else None
        # _overall filters to primary again; ``chosen`` is already primary.
        floor_vals = _decision_values(chosen, "decision_return_floor")
        excess = [
            float(episode["matched_excess"])
            for episode in chosen
            if episode.get("matched_excess") is not None
        ]
        out[str(bucket)] = {
            "count": len(chosen),
            "median_fair_cost": _median(floor_vals),
            "median_matched_excess": _median(excess),
        }
        del overall
    return out


def _feature_number(episode: dict[str, Any], feature: str) -> float | None:
    raw = (episode.get("snapshot") or {}).get(feature)
    if raw is None:
        raw = (episode.get("channels") or {}).get(feature)
    return _finite(raw)


def _fifths(episodes: list[dict[str, Any]], feature: str) -> list[dict[str, Any]]:
    rows = []
    for episode in _mature_primary(episodes):
        number = _feature_number(episode, feature)
        if number is None:
            continue
        rows.append((number, episode))
    rows.sort(key=lambda item: item[0])
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(SELECTION_FIFTHS)]
    total = len(rows)
    for index, (_value, episode) in enumerate(rows):
        slot = min(SELECTION_FIFTHS - 1, index * SELECTION_FIFTHS // total) if total else 0
        buckets[slot].append(episode)
    report = []
    for slot, group in enumerate(buckets, start=1):
        returns = _decision_values(group, "decision_return_floor")
        launched = [episode for episode in group if episode.get("launched")]
        by_week = _group_weeks(group, lambda episode: episode.get("decision_return_floor"))
        report.append(
            {
                "fifth": slot,
                "count": len(group),
                "launch_share": None if not group else len(launched) / len(group),
                "median_fair_cost": _median(returns),
                "capital_days_return": capital_days_return(group),
                "standard_error": entry_week_standard_error(by_week),
            }
        )
    return report


def _gate_count(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    counted = [
        episode
        for episode in _mature_primary(episodes)
        if not episode.get("provenance_missing") and episode.get("status") != "pending_fill"
    ]
    by_week: dict[str, int] = defaultdict(int)
    for episode in counted:
        by_week[str(episode.get("entry_week"))] += 1
    capped = {week: min(THICKNESS_MAX_PER_ENTRY_WEEK, count) for week, count in by_week.items()}
    return {
        "mature_episodes": len(_mature_primary(episodes)),
        "counted_before_cap": len(counted),
        "counted": sum(capped.values()),
        "per_week": capped,
        "cap": THICKNESS_MAX_PER_ENTRY_WEEK,
        "min_counted": THICKNESS_MIN_COUNTED,
        "provenance_missing_excluded": sum(
            1 for episode in _mature_primary(episodes) if episode.get("provenance_missing")
        ),
    }


def _single_market_dependence(episodes: list[dict[str, Any]]) -> bool:
    mature = _mature_primary(episodes)
    overall = _median(_decision_values(mature, "decision_return_floor"))
    if overall is None or overall <= 0:
        return False
    counts: dict[str, int] = defaultdict(int)
    for episode in mature:
        counts[str(episode.get("market"))] += 1
    if not counts:
        return False
    biggest = max(counts, key=lambda market: (counts[market], market))
    rest = [episode for episode in mature if episode.get("market") != biggest]
    rest_median = _median(_decision_values(rest, "decision_return_floor"))
    return rest_median is not None and rest_median <= 0


def _signed_difference(
    kept_rows: list[dict[str, Any]], all_rows: list[dict[str, Any]]
) -> float | None:
    left = _mean(_decision_values(kept_rows, "decision_return_floor"))
    right = _mean(_decision_values(all_rows, "decision_return_floor"))
    if left is None or right is None:
        return None
    return left - right


def _same_sign(left: float | None, right: float | None) -> bool:
    if left is None or right is None or left == 0 or right == 0:
        return False
    return (left > 0) == (right > 0)


def _bench_report(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    primary = _mature_primary(episodes)
    all_returns = _decision_values(primary, "decision_return_floor")
    all_mean = _mean(all_returns)
    counted_primary = [episode for episode in primary if not episode.get("provenance_missing")]
    first_half, second_half = period_halves(counted_primary)
    report: dict[str, Any] = {}
    for column in INITIAL_BENCH:
        kept = [episode for episode in primary if (episode.get("bench") or {}).get(column)]
        kept_counted = [episode for episode in kept if not episode.get("provenance_missing")]
        dropped_missing = [episode for episode in kept if episode.get("provenance_missing")]
        kept_returns = _decision_values(kept, "decision_return_floor")
        by_week = _group_weeks(
            kept_counted,
            lambda episode: episode.get("decision_return_floor"),
        )
        kept_mean = _mean(_decision_values(kept_counted, "decision_return_floor"))
        difference = None if kept_mean is None or all_mean is None else kept_mean - all_mean
        error = entry_week_standard_error(by_week)
        kept_capital = capital_days_return(kept_counted)
        primary_capital = capital_days_return(counted_primary)
        first_diff = _signed_difference(
            [episode for episode in first_half if (episode.get("bench") or {}).get(column)],
            first_half,
        )
        second_diff = _signed_difference(
            [episode for episode in second_half if (episode.get("bench") or {}).get(column)],
            second_half,
        )
        both_halves = _same_sign(first_diff, second_diff)
        capital_days_met = bool(
            kept_capital is not None
            and primary_capital is not None
            and kept_capital >= primary_capital
        )
        count_met = len(kept_counted) >= BENCH_MIN_COUNTED
        difference_met = bool(
            difference is not None
            and error not in (None, 0)
            and abs(difference) > BENCH_STANDARD_ERRORS * error
            and difference > 0
        )
        report[column] = {
            "kept": len(kept),
            "kept_share": None if not primary else len(kept) / len(primary),
            "mean_kept": _mean(kept_returns),
            "mean_all": all_mean,
            "mean_difference": difference,
            "standard_error": error,
            "counted_mature": len(kept_counted),
            "provenance_missing_excluded": len(dropped_missing),
            "promotion_bar": {
                "min_counted": BENCH_MIN_COUNTED,
                "standard_errors": BENCH_STANDARD_ERRORS,
                "count_met": count_met,
                "difference_met": difference_met,
                "both_halves_same_sign": both_halves,
                "first_half_difference": first_diff,
                "second_half_difference": second_diff,
                "capital_days_met": capital_days_met,
                "kept_capital_days": kept_capital,
                "primary_capital_days": primary_capital,
                "met": bool(count_met and difference_met and capital_days_met and both_halves),
            },
        }
    return report


def _slot_book(episodes: list[dict[str, Any]], *, seed: int) -> dict[str, Any]:
    primary = [
        episode
        for episode in episodes
        if episode.get("column") == COLUMN_PRIMARY and episode.get("fill_session")
    ]
    if not primary:
        return {
            "trades_taken": 0,
            "trades_skipped": 0,
            "skipped_ids": [],
            "annualised_return": None,
            "max_drawdown": None,
            "annualised_volatility": None,
            "average_idle_cash": None,
            "worst_five_share": None,
            "random_order_median": None,
        }

    def _simulate(order_key) -> dict[str, Any]:
        ordered = sorted(primary, key=order_key)
        days = sorted(
            {episode["fill_session"] for episode in ordered}
            | {episode["exit_session"] for episode in ordered if episode.get("exit_session")}
        )
        cash = 1.0
        positions: list[dict[str, Any]] = []
        taken: list[str] = []
        skipped: list[str] = []
        nav_path: list[float] = []
        cash_path: list[float] = []
        pnl_by_name: dict[str, float] = defaultdict(float)
        due_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for episode in ordered:
            due_by_day[episode["fill_session"]].append(episode)
        for day in days:
            still: list[dict[str, Any]] = []
            for position in positions:
                if position["exit_session"] == day:
                    proceeds = position["alloc"] * (1.0 + position["ret"])
                    cash += proceeds
                    pnl_by_name[position["ticker"]] += proceeds - position["alloc"]
                else:
                    still.append(position)
            positions = still
            nav = cash + sum(position["alloc"] * (1.0 + position["mark"]) for position in positions)
            due = due_by_day.get(day, [])
            alloc = nav / SLOT_COUNT if SLOT_COUNT else 0.0
            for episode in due:
                if len(positions) >= SLOT_COUNT or cash <= 1e-12:
                    skipped.append(str(episode.get("episode_id") or episode.get("ticker")))
                    continue
                spend = min(alloc, cash)
                ret = episode.get("fair_cost_return")
                if ret is None:
                    skipped.append(str(episode.get("episode_id") or episode.get("ticker")))
                    continue
                cash -= spend
                positions.append(
                    {
                        "episode_id": str(episode.get("episode_id") or episode.get("ticker")),
                        "ticker": episode["ticker"],
                        "alloc": spend,
                        "ret": float(ret),
                        "mark": float(ret),
                        "exit_session": episode.get("exit_session") or day,
                    }
                )
                taken.append(str(episode.get("episode_id") or episode.get("ticker")))
            nav = cash + sum(position["alloc"] * (1.0 + position["mark"]) for position in positions)
            nav_path.append(nav)
            cash_path.append(cash)
        for position in positions:
            cash += position["alloc"] * (1.0 + position["ret"])
            pnl_by_name[position["ticker"]] += position["alloc"] * position["ret"]
        end_nav = cash
        start_day = datetime.fromisoformat(days[0])
        end_day = datetime.fromisoformat(days[-1])
        span = max((end_day - start_day).days, 1)
        annualised = None if end_nav <= 0 else (end_nav / 1.0) ** (CAPITAL_YEAR_DAYS / span) - 1.0
        peak = 1.0
        max_dd = 0.0
        prev = 1.0
        rets: list[float] = []
        for nav in nav_path:
            peak = max(peak, nav)
            if peak:
                max_dd = min(max_dd, nav / peak - 1.0)
            if prev:
                rets.append(nav / prev - 1.0)
            prev = nav
        vol = None
        if len(rets) >= 2:
            vol = statistics.stdev(rets) * math.sqrt(252)
        worst = sorted(pnl_by_name.values())[:5]
        return {
            "trades_taken": len(taken),
            "trades_skipped": len(skipped),
            "skipped_ids": skipped,
            "taken_ids": taken,
            "annualised_return": annualised,
            "max_drawdown": max_dd,
            "annualised_volatility": vol,
            "average_idle_cash": statistics.fmean(cash_path) if cash_path else None,
            "worst_five_share": sum(worst) / 1.0 if worst else None,
            "end_nav": end_nav,
        }

    base = _simulate(lambda episode: (episode["fill_session"], episode["ticker"]))
    random_returns: list[float] = []
    for offset in range(SLOT_RANDOM_ORDERS):
        rng = random.Random(seed + offset)

        def _key(episode: dict[str, Any], _rng: random.Random = rng) -> tuple[str, float]:
            return (str(episode["fill_session"]), _rng.random())

        sample = _simulate(_key)
        if sample["annualised_return"] is not None:
            random_returns.append(float(sample["annualised_return"]))
    base["random_order_median"] = _median(random_returns)
    base["random_orders"] = SLOT_RANDOM_ORDERS
    return base


def _buy_and_hold(
    episodes: list[dict[str, Any]], names: list[_Name], options: WalkOptions, scoring: date
) -> dict[str, Any]:
    """Equal stake in each name on the day it first becomes eligible. Price only."""
    del episodes
    positions: dict[str, dict[str, Any]] = {}
    calendar = sorted({day for name in names for day in name.prices.calendar if day <= scoring})
    ordered = sorted(names, key=lambda item: (item.spec.market, item.spec.ticker))
    by_key: dict[str, _Name] = {}
    for name in names:
        by_key.setdefault(f"{name.spec.market}:{name.spec.ticker}", name)
    for session in calendar:
        for name in ordered:
            key = f"{name.spec.market}:{name.spec.ticker}"
            if key in positions or name.refusal:
                continue
            # A session missing from the chart has no download, so no position.
            if not name.prices.has_session(session):
                continue
            ok, _reason = _base_eligible(name, session, options, price=False)
            if not ok:
                continue
            download = name.prices.download_for(session)
            if download is None or download.close(session) is None:
                continue
            positions[key] = {
                "market": name.spec.market,
                "ticker": name.spec.ticker,
                "stake": float(STAKE_UNITS),
                "entry_session": session.isoformat(),
                "entry": download.close(session),
            }
    values: list[float] = []
    for key, position in positions.items():
        market, ticker = key.split(":", 1)
        name = by_key[key]
        latest = name.prices.latest()
        through = bisect_right(name.prices.calendar, scoring)
        last = name.prices.calendar[through - 1] if through else None
        if latest is None or last is None or position["entry"] in (None, 0):
            continue
        end = latest.close(last)
        if end is None:
            continue
        position["exit"] = end
        position["fair_cost_return"] = _fair(float(position["entry"]), end, market)
        values.append(position["stake"] * (1.0 + position["fair_cost_return"]))
    contributed = sum(position["stake"] for position in positions.values()) or None
    nav = None if contributed is None else sum(values) / contributed if contributed else None
    return {
        "positions": positions,
        "names": len(positions),
        "stake_each": float(STAKE_UNITS),
        "contributed": contributed,
        "fair_cost_nav_multiple": nav,
    }


def build_boards(
    episodes: list[dict[str, Any]],
    *,
    events: list[dict[str, Any]] | None = None,
    scoring_date: date | None = None,
    cap_would_block_days: int = 0,
    names: list[_Name] | None = None,
    options: WalkOptions | None = None,
) -> dict[str, Any]:
    """Section 8 boards. Medians use every mature primary episode."""
    events = events or []
    mature = _mature_primary(episodes)
    launched = [episode for episode in mature if episode.get("launched")]
    launch_sessions = [
        int(episode["sessions_to_launch"])
        for episode in launched
        if episode.get("sessions_to_launch") is not None
    ]
    by_market: dict[str, Any] = {}
    markets = sorted({str(episode.get("market")) for episode in mature})
    counts: dict[str, int] = defaultdict(int)
    for episode in mature:
        counts[str(episode.get("market"))] += 1
    if "ftse350" in counts:
        by_market["ftse350"] = _overall(
            [episode for episode in episodes if episode.get("market") == "ftse350"]
        )
    pooled: list[dict[str, Any]] = []
    for market in markets:
        if market == "ftse350":
            continue
        chosen = [episode for episode in episodes if episode.get("market") == market]
        if counts[market] >= MARKET_BOARD_MIN_MATURE:
            by_market[market] = _overall(chosen)
        else:
            pooled.extend(episode for episode in chosen if episode.get("column") == COLUMN_PRIMARY)
    if pooled:
        by_market["other"] = _overall(pooled)

    def _exit_slice(reason: str) -> dict[str, Any]:
        rows = [episode for episode in mature if episode.get("exit_reason") == reason]
        returns = [
            float(episode["fair_cost_return"])
            for episode in rows
            if episode.get("fair_cost_return") is not None
        ]
        return {"count": len(rows), "median_fair_cost": _median(returns)}

    floor_rows = [episode for episode in mature if episode.get("exit_reason") == EXIT_FLOOR]
    checkpoints: dict[str, int] = defaultdict(int)
    for episode in floor_rows:
        checkpoints[str(episode.get("highest_checkpoint"))] += 1
    shortfall = sum(float(episode.get("gap_shortfall") or 0.0) for episode in floor_rows)
    fail_rows = [episode for episode in mature if episode.get("exit_reason") == EXIT_FAIL_TO_LAUNCH]
    fail_returns = [
        float(episode["fair_cost_return"])
        for episode in fail_rows
        if episode.get("fair_cost_return") is not None
    ]
    below_fill = 0
    for episode in fail_rows:
        entry = episode.get("return_entry_fill")
        exit_px = episode.get("exit_fill")
        if entry and exit_px is not None and float(exit_px) < float(entry):
            below_fill += 1
    thesis_rows = [episode for episode in mature if episode.get("exit_reason") == EXIT_THESIS]
    thesis_by_reason: dict[str, int] = defaultdict(int)
    for episode in thesis_rows:
        reasons = []
        for row in episode.get("decision_log") or []:
            if row.get("action") == EXIT_THESIS:
                reasons.extend(row.get("reasons") or [])
        # Reason codes live on the pending list captured in the log only when present.
        if not reasons:
            reasons = ["unspecified"]
        for reason in reasons:
            thesis_by_reason[str(reason)] += 1
    recovery_rows = [episode for episode in _primary(episodes) if episode.get("recovery_label")]
    recovery_returns = [
        float(episode["fair_cost_return"])
        for episode in recovery_rows
        if episode.get("fair_cost_return") is not None
    ]
    shadows = {}
    for column in (COLUMN_DECLINE_SHADOW, COLUMN_SECTOR_SHADOW):
        rows = [
            episode
            for episode in episodes
            if episode.get("column") == column and episode.get("mature")
        ]
        returns = _decision_values(rows, "decision_return_floor")
        launched_rows = [episode for episode in rows if episode.get("launched")]
        shadows[column] = {
            "count": len(rows),
            "median_fair_cost": _median(returns),
            "launch_share": None if not rows else len(launched_rows) / len(rows),
            "capital_days_return": capital_days_return(rows),
        }
    controls = {
        COLUMN_BUY_ON_SIGNAL: _overall(
            [episode for episode in episodes if episode.get("column") == COLUMN_BUY_ON_SIGNAL]
        ),
        COLUMN_LEAVE_TIER: _overall(
            [
                episode
                for episode in episodes
                if episode.get("column") == COLUMN_LEAVE_TIER
                and not episode.get("out_of_control_median")
            ]
        ),
    }
    # _overall filters COLUMN_PRIMARY. Rebuild control medians directly.
    for column, rows in (
        (
            COLUMN_BUY_ON_SIGNAL,
            [
                episode
                for episode in episodes
                if episode.get("column") == COLUMN_BUY_ON_SIGNAL and episode.get("mature")
            ],
        ),
        (
            COLUMN_LEAVE_TIER,
            [
                episode
                for episode in episodes
                if episode.get("column") == COLUMN_LEAVE_TIER
                and episode.get("mature")
                and not episode.get("out_of_control_median")
            ],
        ),
    ):
        values = _decision_values(rows, "decision_return_floor")
        controls[column] = {"count": len(rows), "median_fair_cost": _median(values)}
    book_median = _overall(episodes).get("median_fair_cost")
    for board in controls.values():
        other = board.get("median_fair_cost")
        board["median_difference_vs_primary"] = (
            None if book_median is None or other is None else float(book_median) - float(other)
        )
    primary_rows = _primary(episodes)
    capital_rows = primary_rows
    recovery_capital = [episode for episode in capital_rows if episode.get("recovery_label")]
    unlaunched = [episode for episode in capital_rows if not episode.get("launched")]
    long_holds = [
        episode
        for episode in capital_rows
        if (episode.get("held_sessions") or 0) > RECOVERY_CAPITAL_LONG_SESSIONS
    ]
    total_days = sum(
        float(episode.get("held_calendar_days") or 0) * float(episode.get("stake") or 0)
        for episode in capital_rows
    )

    def _share(rows: list[dict[str, Any]]) -> float | None:
        if total_days <= 0:
            return None
        used = sum(
            float(episode.get("held_calendar_days") or 0) * float(episode.get("stake") or 0)
            for episode in rows
        )
        return used / total_days

    first_fills = [episode["fill_session"] for episode in primary_rows]
    interim_ready = False
    if scoring_date is not None and first_fills:
        first = min(date.fromisoformat(value) for value in first_fills)
        interim_ready = (scoring_date - first).days >= INTERIM_WEEKS * 7
    paired = {
        COLUMN_DRAFT: _paired_board(episodes, COLUMN_DRAFT),
        COLUMN_LADDER: _paired_board(episodes, COLUMN_LADDER),
    }
    stress_values = []
    for episode in mature:
        entry = episode.get("return_entry_fill")
        exit_px = episode.get("exit_fill")
        if episode.get("status") == "closed" and entry and exit_px:
            stress_values.append(_stress(float(entry), float(exit_px)))
        elif episode.get("launched") and episode.get("floor") is not None and entry:
            stress_values.append(
                _stress(float(entry), float(entry) * (1.0 + float(episode["floor"])))
            )
    selection_features = NUMERIC_SNAPSHOT_FEATURES + CHANNEL_NUMERIC_FEATURES
    counted_for_fifths = [
        episode for episode in _mature_primary(episodes) if not episode.get("provenance_missing")
    ]
    fifth_halves = period_halves(counted_for_fifths)
    selection = {
        feature: {
            "whole": _fifths(counted_for_fifths, feature),
            "first_half": _fifths(fifth_halves[0], feature),
            "second_half": _fifths(fifth_halves[1], feature),
        }
        for feature in selection_features
    }
    coverage = {}
    for feature in selection_features:
        have = sum(
            1
            for episode in _mature_primary(episodes)
            if _feature_number(episode, feature) is not None
        )
        coverage[feature] = {"present": have, "mature": len(mature)}
    memo_board: dict[str, Any] = {
        "by_market": defaultdict(lambda: defaultdict(int)),
        "by_week": defaultdict(lambda: defaultdict(int)),
    }
    for event in events:
        if event.get("kind") not in {"filled", "memo_not_ready", "memo_blocked"}:
            continue
        if event.get("column") not in (None, COLUMN_PRIMARY):
            continue
        market = str(event.get("market"))
        week = event.get("session", "")[:10]
        try:
            week_key = entry_week(date.fromisoformat(week))
        except ValueError:
            week_key = week
        memo_board["by_market"][market][event["kind"]] += 1
        memo_board["by_week"][week_key][event["kind"]] += 1
    memo_board["by_market"] = {key: dict(value) for key, value in memo_board["by_market"].items()}
    memo_board["by_week"] = {key: dict(value) for key, value in memo_board["by_week"].items()}
    late: dict[str, Any] = {"by_market": defaultdict(int), "by_week": defaultdict(list)}
    for event in events:
        if event.get("kind") != "late_signal":
            continue
        late["by_market"][str(event.get("market"))] += 1
        day = str(event.get("session") or "")[:10]
        try:
            week_key = entry_week(date.fromisoformat(day))
        except ValueError:
            week_key = day
        late["by_week"][week_key].append(event.get("hours_after_signal_close"))
    late["by_market"] = dict(late["by_market"])
    late["by_week"] = {key: list(value) for key, value in late["by_week"].items()}
    hl_counts: dict[str, int] = defaultdict(int)
    for episode in _primary(episodes):
        basis = (episode.get("channels") or {}).get("hl_basis")
        if basis:
            hl_counts[str(basis)] += 1
    channel_splits: dict[str, Any] = {}
    for episode in mature:
        channels = episode.get("channels") or {}
        bucket = channels.get("ch126_bucket")
        direction = channels.get("ch126_direction")
        context = channels.get("ch252_bucket")
        if not bucket and not direction:
            continue
        key = f"{bucket}|{direction}|{context}"
        channel_splits.setdefault(key, []).append(episode)
    channel_board = {}
    for key, rows in channel_splits.items():
        returns = _decision_values(rows, "decision_return_floor")
        launched_rows = [episode for episode in rows if episode.get("launched")]
        channel_board[key] = {
            "count": len(rows),
            "launch_share": None if not rows else len(launched_rows) / len(rows),
            "median_fair_cost": _median(returns),
            "capital_days_return": capital_days_return(rows),
        }
    agrees = [
        episode
        for episode in mature
        if str(episode.get("adjusted_signal") or "") in VALUE_SET_SIGNALS
    ]
    disagrees = [
        episode
        for episode in mature
        if episode.get("adjusted_signal") not in (None, "")
        and str(episode.get("adjusted_signal")) not in VALUE_SET_SIGNALS
    ]
    missing_adjusted = [episode for episode in mature if not episode.get("adjusted_signal")]

    def _mini(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(rows),
            "median_fair_cost": _median(_decision_values(rows, "decision_return_floor")),
            "median_matched_excess": _median(
                [
                    float(episode["matched_excess"])
                    for episode in rows
                    if episode.get("matched_excess") is not None
                ]
            ),
        }

    tradable = {
        "listed": _mini([episode for episode in mature if episode.get("t212_listed") is True]),
        "not_listed": _mini([episode for episode in mature if episode.get("t212_listed") is False]),
        "unknown": _mini(
            [episode for episode in mature if episode.get("t212_listed") == "unknown"]
        ),
    }
    regime = {
        label: _mini([episode for episode in mature if episode.get("regime") == label])
        for label in ("above", "below", "regime_unknown")
    }
    span = 0
    if primary_rows:
        first = min(date.fromisoformat(episode["fill_session"]) for episode in primary_rows)
        last = scoring_date or max(
            date.fromisoformat(episode["fill_session"]) for episode in primary_rows
        )
        span = _sessions_after(
            sorted({date.fromisoformat(episode["fill_session"]) for episode in primary_rows}),
            first,
            last,
        )
        # Span of chart sessions is carried on the episodes via held path; the gate
        # uses sessions from the first fill, which callers also see as mature count.
        del span
    gate = _gate_count(episodes)
    first_fill = min(
        (date.fromisoformat(episode["fill_session"]) for episode in primary_rows), default=None
    )
    last_session = scoring_date
    span_sessions = None
    if first_fill is not None and last_session is not None:
        span_sessions = (last_session - first_fill).days
    gate["calendar_days_from_first_fill"] = span_sessions
    gate["span_met"] = bool(
        span_sessions is not None and span_sessions >= THICKNESS_MIN_SPAN_SESSIONS
    )
    # The span gate is chart sessions. Calendar days are reported beside it.
    # Callers that walked a tape can overwrite ``span_sessions`` ; the default
    # uses the longest primary held_sessions from the first fill's name, which
    # the episode already stores when the tape continued.
    longest = max((int(episode.get("held_sessions") or 0) for episode in primary_rows), default=0)
    if names is not None and scoring_date is not None and primary_rows:
        first_fill_day = min(
            date.fromisoformat(episode["fill_session"]) for episode in primary_rows
        )
        spanned = [
            _sessions_after(name.prices.calendar, first_fill_day, scoring_date) for name in names
        ]
        if spanned:
            longest = max(spanned)
    gate["span_sessions"] = longest
    gate["span_met"] = longest >= THICKNESS_MIN_SPAN_SESSIONS
    gate["ready"] = gate["counted"] >= THICKNESS_MIN_COUNTED and gate["span_met"]
    return {
        "overall": _overall(episodes),
        "matched_excess": _excess_board(episodes),
        "launch": {
            "mature": len(mature),
            "launched": len(launched),
            "launch_share": None if not mature else len(launched) / len(mature),
            "median_sessions_to_launch": _median([float(value) for value in launch_sessions]),
        },
        "floor_exits": {
            "count": len(floor_rows),
            "median_fair_cost": _median(
                [
                    float(episode["fair_cost_return"])
                    for episode in floor_rows
                    if episode.get("fair_cost_return") is not None
                ]
            ),
            "checkpoints": dict(checkpoints),
            "gap_shortfall": shortfall,
        },
        "fail_to_launch": {
            "count": len(fail_rows),
            "median_fair_cost": _median(fail_returns),
            "share_below_fill": None if not fail_rows else below_fill / len(fail_rows),
        },
        "thesis_breaks": {
            "count": len(thesis_rows),
            "by_reason": dict(thesis_by_reason),
            "median_fair_cost": _median(
                [
                    float(episode["fair_cost_return"])
                    for episode in thesis_rows
                    if episode.get("fair_cost_return") is not None
                ]
            ),
            "launched": sum(1 for episode in thesis_rows if episode.get("launched")),
        },
        "review_and_time_cap": {
            "review_insufficient_data": _exit_slice(EXIT_REVIEW_INSUFFICIENT),
            "time_cap": _exit_slice(EXIT_TIME_CAP),
            "review_cap": _exit_slice(EXIT_REVIEW_CAP),
        },
        "recovery_label": {
            "count": len(recovery_rows),
            "launch_share": None
            if not recovery_rows
            else sum(1 for episode in recovery_rows if episode.get("launched"))
            / len(recovery_rows),
            "median_fair_cost": _median(recovery_returns),
        },
        "by_market": by_market,
        "single_market_dependence": _single_market_dependence(episodes),
        "paired_exits": paired,
        "interim_read": {
            "published": interim_ready,
            "weeks": INTERIM_WEEKS,
            **(
                paired[COLUMN_DRAFT]
                if interim_ready
                else {"standard_error": None, "mean_difference": None}
            ),
        },
        "stress": {"count": len(stress_values), "median_fair_cost": _median(stress_values)},
        "shadows": shadows,
        "selection_fifths": selection,
        "selection_coverage": coverage,
        "channels": {"hl_basis": dict(hl_counts), "splits": channel_board},
        "bench": _bench_report(episodes),
        "controls": controls,
        "capital_view": {
            "capital_days_return": capital_days_return(capital_rows),
            "recovery_hold_capital_share": _share(recovery_capital),
            "unlaunched_capital_share": _share(unlaunched),
            "long_hold_capital_share": _share(long_holds),
            "recovery_hold_fair_cost_sum": sum(
                float(episode["capital_return"])
                for episode in recovery_capital
                if episode.get("capital_return") is not None
            ),
            "cap_would_block_days": cap_would_block_days,
            "recovery_share_line": RECOVERY_SHARE_LINE,
            "slot_book": _slot_book(episodes, seed=SLOT_BOOK_RANDOM_SEED),
            "buy_and_hold": _buy_and_hold(
                episodes, names or [], options or WalkOptions(), scoring_date or date.today()
            )
            if names is not None
            else {"positions": {}, "names": 0, "stake_each": float(STAKE_UNITS)},
        },
        "sector_fallback": {
            "basis": _split_board(episodes, "sector_basis", ["own_market", "regional", None]),
            "earnings_breadth": _split_board(
                episodes,
                "earnings_breadth_bucket",
                ["none", "under_half", "half_or_more", None],
            ),
        },
        "cash_flow_agreement": {
            "agrees": _mini(agrees),
            "disagrees": _mini(disagrees),
            "missing": _mini(missing_adjusted),
        },
        "tradable": tradable,
        "regime": regime,
        "memo_readiness": memo_board,
        "late_signals": late,
        "thickness_gate": gate,
        "provenance_missing": sum(1 for episode in episodes if episode.get("provenance_missing")),
    }


def add_bench_column(
    store: dict[str, Any],
    column_id: str,
    *,
    version_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a bench column. After scores exist, only a logged version review may."""
    columns = list(store.get("bench_columns") or list(INITIAL_BENCH))
    if column_id in columns:
        store["bench_columns"] = columns
        return store
    if len(columns) >= BENCH_SLOTS:
        raise ValueError(f"bench already holds {BENCH_SLOTS} columns")
    scored = bool(store.get("episodes")) or bool(store.get("scored_at"))
    if scored:
        if not isinstance(version_review, dict):
            raise ValueError("a bench column cannot be added once the forward store has scores")
        if (
            version_review.get("column") != column_id
            or not str(version_review.get("id") or "").strip()
        ):
            raise ValueError("version review must name the column and carry an id")
        store.setdefault("version_reviews", []).append(dict(version_review))
    columns.append(column_id)
    store["bench_columns"] = columns
    return store


def filter_kept(episodes: list[dict[str, Any]], column: str) -> list[dict[str, Any]]:
    """Filter challengers keep book entries. They do not open new ones."""
    if column not in INITIAL_BENCH and column not in {
        *(episode.get("column") for episode in episodes)
    }:
        return [
            episode for episode in _primary(episodes) if (episode.get("bench") or {}).get(column)
        ]
    return [episode for episode in _primary(episodes) if (episode.get("bench") or {}).get(column)]
