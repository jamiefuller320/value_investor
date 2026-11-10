"""Named constants for ``owner-strategy-book-v0``.

Every threshold is the figure written in ``docs/ops/strategy-book-registration.md``.
The registration is not signed: nothing here opens a book or scores a store.
Existing project constants that the registration stamps unchanged are imported,
not re-typed. A signature note may change a proposed number once, in this module,
before any score store exists.

``SLOT_BOOK_RANDOM_SEED`` is not in the main registration. Section 8 says only
"15 fixed random orders". The seed is the value the US rehearsal registration
names, logged as a clarification at signature.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from value_investor.decision_input_inventory import DEFAULT_MEMO_MAX_AGE_DAYS
from value_investor.market_paper_shard import MARKET_SESSION_DEFAULTS
from value_investor.market_trading_costs import LEGACY_STRESS_TRADE_COST_PCT
from value_investor.paper_fund import BUY_SIGNALS, DEFAULT_EXIT_CONFIRM_SCREENS
from value_investor.storage import read_json

# Section 1 and the header. Proposed registration id. Not a live book.
REGISTRATION_ID = "owner-strategy-book-v0"
INFLUENCES_LIVE = False

# Section 2. The owner's value set, same pair as ``paper_fund.BUY_SIGNALS``.
VALUE_SET_SIGNALS = BUY_SIGNALS

# Section 2. Memo age uses the existing 21-day maximum.
MEMO_MAX_AGE_DAYS = DEFAULT_MEMO_MAX_AGE_DAYS


def _session_zone(market_id: str, fallback: str) -> str:
    """IANA zone from ``MARKET_SESSION_DEFAULTS`` when the shard names one."""
    row = MARKET_SESSION_DEFAULTS.get(market_id)
    if not row:
        return fallback
    return str(row["timezone"])


class UnknownMarketClose(KeyError):
    """No regular-session close is registered for this market. Fail closed."""


# Section 2. Regular cash-session closes. Exchange facts, not strategy numbers.
# A memo counts only when it is finished earlier than this close in the
# market's own time zone. ``euro_depth`` and ``sp400`` are not graduated, so
# they are absent and ``session_close`` refuses them.
# Zones for sp500, nasdaq100, tsx60, euro_stoxx50, asx200 and ftse_smallcap
# come from ``MARKET_SESSION_DEFAULTS``.
MARKET_CLOSE_LOCAL: dict[str, tuple[str, str]] = {
    # London Stock Exchange cash close 16:30.
    "ftse350": ("Europe/London", "16:30"),
    "aim": ("Europe/London", "16:30"),
    "ftse_smallcap": (_session_zone("ftse_smallcap", "Europe/London"), "16:30"),
    # NYSE and Nasdaq cash close 16:00.
    "sp500": (_session_zone("sp500", "America/New_York"), "16:00"),
    "nasdaq100": (_session_zone("nasdaq100", "America/New_York"), "16:00"),
    # Curated US ADRs. The venue is New York, not the home exchange.
    "us_adr_asia": ("America/New_York", "16:00"),
    # Toronto Stock Exchange cash close 16:00.
    "tsx60": (_session_zone("tsx60", "America/Toronto"), "16:00"),
    # ASX cash close 16:00.
    "asx200": (_session_zone("asx200", "Australia/Sydney"), "16:00"),
    # HKEX cash close 16:00.
    "hang_seng": ("Asia/Hong_Kong", "16:00"),
    # SGX securities market close 17:00.
    "sti": ("Asia/Singapore", "17:00"),
    # Euronext Paris, Amsterdam and Brussels cash close 17:30.
    # EURO STOXX 50 uses the Paris session named in the shard defaults.
    "cac40": ("Europe/Paris", "17:30"),
    "aex": ("Europe/Amsterdam", "17:30"),
    "bel20": ("Europe/Brussels", "17:30"),
    "euro_stoxx50": (_session_zone("euro_stoxx50", "Europe/Paris"), "17:30"),
    # Xetra cash close 17:30.
    "dax": ("Europe/Berlin", "17:30"),
    # Borsa Italiana cash close 17:30.
    "ftse_mib": ("Europe/Rome", "17:30"),
    # BME cash close 17:30.
    "ibex35": ("Europe/Madrid", "17:30"),
    # SIX cash close 17:30.
    "smi": ("Europe/Zurich", "17:30"),
    # Nasdaq Stockholm cash close 17:30.
    "omxs30": ("Europe/Stockholm", "17:30"),
    # Wiener Börse cash close 17:30.
    "atx": ("Europe/Vienna", "17:30"),
    # Euronext Dublin cash close 16:30.
    "iseq20": ("Europe/Dublin", "16:30"),
    # Euronext Lisbon cash close 16:30.
    "psi20": ("Europe/Lisbon", "16:30"),
}


def session_close(market: str, day: date) -> datetime:
    """Cash close of ``day`` as a UTC instant. Unknown markets raise.

    DST follows the IANA zone. This is the memo bind and the late-signal
    clock. Point-in-time file dating stays on ``session_end``.
    """
    row = MARKET_CLOSE_LOCAL.get(str(market or "").strip())
    if row is None:
        raise UnknownMarketClose(market)
    zone_name, hhmm = row
    hour_text, minute_text = hhmm.split(":")
    local = datetime.combine(
        day,
        time(int(hour_text), int(minute_text)),
        tzinfo=ZoneInfo(zone_name),
    )
    return local.astimezone(UTC)


# Section 2. A catalogue older than 35 days on the entry date is ``unknown``.
T212_CATALOGUE_MAX_AGE_DAYS = 35

# Section 3. Primary entry. RSI(14) strictly below 35, 10-session close low.
RSI_PERIOD = 14
RSI_LEVEL = 35
LOW_WINDOW_SESSIONS = 10

# Section 3. No fill when the next stored session is more than 5 calendar days
# after the signal, or when the signal is the last bar.
MAX_FILL_GAP_CALENDAR_DAYS = 5

# Section 3. A forward chart more than 5 calendar days behind the decision
# date produces no signal that day.
STALE_CHART_CALENDAR_DAYS = 5

# Section 3. Pre-registered alternative. Report-only. Not a forward entry.
ALT_RSI_LEVEL = 40
ALT_SMA_WINDOW = 10
ALT_SMA_DISTANCE = 0.03

# Section 4. Launch is the first checkpoint. Floor only rises. Above +100%
# the floor stays at +75%.
LAUNCH_RETURN = 0.10
CHECKPOINTS: tuple[tuple[float, float], ...] = (
    (0.10, 0.05),
    (0.15, 0.10),
    (0.20, 0.15),
    (0.25, 0.20),
    (0.30, 0.25),
    (0.40, 0.30),
    (0.50, 0.40),
    (0.75, 0.50),
    (1.00, 0.75),
)
FLOOR_AT_OR_ABOVE_LAST = 0.75

# Section 4. Fail-to-launch when the session index after the fill reaches 63.
# The fill session is index 0.
FAIL_TO_LAUNCH_INDEX = 63

# Section 4. Time cap when the session index reaches 252.
TIME_CAP_INDEX = 252

# Section 4. ``draft_v0_exit`` as written: 10-session high, 15-session swing
# limit, entry-price target, reviews every 63 sessions, sale at review 4.
DRAFT_HIGH_WINDOW = 10
DRAFT_SWING_LIMIT_INDEX = 15
DRAFT_REVIEW_SPACING = 63
DRAFT_REVIEW_COUNT = 4

# Section 5. Recovery label: 8% under the fill before launch. It does not sell.
RECOVERY_DROP = 0.08

# Section 5. Confirmation reuses the live exit-confirm screen count.
THESIS_CONFIRM_OBSERVATIONS = DEFAULT_EXIT_CONFIRM_SCREENS

# Section 5. Primary reviews. Index 252 is the time cap, not a fourth review.
REVIEW_INDEXES: tuple[int, ...] = (63, 126, 189)

# Section 6. Fixed stake. Report-only recovery-hold cap (section 13, question 5).
STAKE_UNITS = 100
COOLDOWN_SESSIONS = 10
RECOVERY_SHARE_MIN_OPEN = 5
RECOVERY_SHARE_LINE = 0.40
CAP_BLOCKS_ENTRIES = False

# Section 7. Stress is the legacy 3% per side. It does not decide the question.
STRESS_PER_SIDE = LEGACY_STRESS_TRADE_COST_PCT

# Section 8. An episode is mature once its fill is at least 63 chart sessions
# before the scoring date.
MATURITY_SESSIONS = 63

# Section 1. Fewer than 5 charted buy-tier names falls back to the whole screen.
BASKET_MIN_NAMES = 5

# Section 8. Regime: half of charted names above their own 200-session average.
# Fewer than 5 counted names is ``regime_unknown``.
REGIME_SMA_SESSIONS = 200
REGIME_ABOVE_SHARE = 0.5
REGIME_MIN_NAMES = 5

# Section 8. By-market board. Markets with fewer than 10 mature episodes pool.
MARKET_BOARD_MIN_MATURE = 10

# Section 8. Interim paired read. Not the thickness gate.
INTERIM_WEEKS = 26

# Section 8. Bench. Up to four columns. 2.5 standard errors, 48 counted mature
# episodes, both halves. Provenance-missing episodes are excluded.
BENCH_SLOTS = 4
BENCH_STANDARD_ERRORS = 2.5
BENCH_MIN_COUNTED = 48

# Section 8 and section 13 question 9. Initial filter challengers.
INITIAL_BENCH: tuple[str, ...] = ("deep_dip", "revenue_growing", "fcf_agrees")

# Section 8. Challengers sealed later, each at a logged version review whose rule
# text and hash are in the registration's ``bench_seals``.
REVIEW_BENCH: tuple[str, ...] = ("trend_not_falling",)
BENCH_COLUMNS: tuple[str, ...] = (*INITIAL_BENCH, *REVIEW_BENCH)
TREND_NOT_FALLING_DIRECTIONS = frozenset({"rising", "sideways"})
DEEP_DIP_LOOKBACK = 20
DEEP_DIP_DROP = 0.08

# Section 8. Capital view. 20 slots, ties by ticker, 15 fixed random orders.
# The main registration does not name a seed. 20261104 is the US rehearsal
# value, kept as the clarification logged at signature.
SLOT_COUNT = 20
SLOT_RANDOM_ORDERS = 15
SLOT_BOOK_RANDOM_SEED = 20261104
CAPITAL_YEAR_DAYS = 365
RECOVERY_CAPITAL_LONG_SESSIONS = 60

# Section 8. Selection board fifths.
SELECTION_FIFTHS = 5

# Section 9. More than 5% of successive gaps longer than 5 calendar days:
# ``chart_not_daily``, not traded. A downsampled tape is refused as well
# (section 12, ``chart_is_thinned``).
CHART_NOT_DAILY_GAP_DAYS = 5
CHART_NOT_DAILY_GAP_SHARE = 0.05

# Section 9. Thickness gate. Forward book only. At most 6 counted mature
# episodes per ISO entry week. The medians still use every mature episode.
THICKNESS_MIN_COUNTED = 48
THICKNESS_MAX_PER_ENTRY_WEEK = 6
THICKNESS_MIN_SPAN_SESSIONS = 63

# Section 1. Too rare: 39 weeks and still fewer than 48 counted mature episodes.
RARITY_WEEKS = 39
RARITY_MIN_MATURE = 48

# Section 9. Archive result keys. Never averaged together.
ARCHIVE_BUY_TIER_ONLY = "archive_buy_tier_only"
ARCHIVE_FULL_STRATEGY = "archive_full_strategy"
LOOKAHEAD_CURRENT_GATES = "lookahead_current_gates"

# Section 10. Later rule changes treat the first 26 weeks of the forward book
# as sealed evidence for v0.
SEALED_FORWARD_WEEKS = 26

# Column ids. Fixed columns do not use bench slots (section 8).
COLUMN_PRIMARY = "primary"
COLUMN_DRAFT = "draft_v0_exit"
COLUMN_LADDER = "ladder_no_deadline"
COLUMN_DECLINE_SHADOW = "decline_rejected_shadow"
COLUMN_SECTOR_SHADOW = "sector_rejected_shadow"
COLUMN_ALTERNATIVE = "alternative"
COLUMN_BUY_ON_SIGNAL = "buy_on_signal"
COLUMN_LEAVE_TIER = "leave_tier"

# Exit labels named by the registration. ``swing_high`` and ``recovery_target``
# describe the draft rules in section 4; the text does not give those two a label.
EXIT_FLOOR = "floor_exit"
EXIT_FAIL_TO_LAUNCH = "fail_to_launch"
EXIT_TIME_CAP = "time_cap"
EXIT_THESIS = "thesis_break"
EXIT_REVIEW_INSUFFICIENT = "review_insufficient_data"
EXIT_REVIEW_CAP = "review_cap"
EXIT_SWING_HIGH = "swing_high"
EXIT_RECOVERY_TARGET = "recovery_target"
EXIT_HOLD_63 = "hold_63"
EXIT_INELIGIBLE_RUNS = "ineligible_runs"

# Thesis reason codes (section 8). Screen and research match ``core_sell_trigger``.
REASON_DECLINING = "declining"
REASON_HEADWIND = "headwind"
REASON_SCREEN_AVOID = "screen_avoid"
REASON_RESEARCH_FAILED = "research_failed"

# Section 12. More than a tenth of a market's buy tier still more than one
# session behind after the close refresh, or late_signal over a tenth of a
# week's signals.
STALE_CLOSE_MAX_SHARE = 0.1
LATE_SIGNAL_MAX_SHARE = 0.1

# Section 12 store names. The forward job writes the observe store and the
# gate log only when the seal is signed and ``forward_live`` is true.
REPLAY_STORE_NAME = "strategy_book_replay.json"
REPLAY_DETAIL_STORE_NAME = "strategy_book_replay_episodes.json.gz"
OBSERVE_STORE_NAME = "strategy_book_observe.json"
REGISTRATION_STORE_NAME = "strategy_book_registration.json"
GATE_LOG_NAME = "strategy_book_gate_log.jsonl"
CLOSES_STATE_NAME = "strategy_book_closes.json"
FORWARD_STATUS_NAME = "strategy_book_forward_status.json"


class RegistrationUnsigned(RuntimeError):
    """A score of real data was refused because the registration is not signed."""


def registration_record(path: Path) -> dict[str, Any] | None:
    """The seal file, or None when it is missing or not a JSON object."""
    if not path.is_file():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _path_is_under(path: Path, parent: Path) -> bool:
    resolved = path.resolve()
    root = parent.resolve()
    if resolved == root:
        return True
    try:
        resolved.relative_to(root)
    except ValueError:
        return False
    return True


def scores_committed_tree(fixture: Path | None, repo_root: Path) -> bool:
    """True when a walk would read the repo's committed ``docs/data`` tree."""
    if fixture is None:
        return True
    return _path_is_under(fixture, Path(repo_root) / "docs" / "data")


def require_signature_for_score(repo_root: Path, fixture: Path | None) -> None:
    """Refuse a score of real data while the registration is unsigned.

    A ``--fixture-dir`` outside ``docs/data`` is a synthetic walk and is allowed.
    The default tree, and any fixture inside ``docs/data``, need a signature.
    """
    if not scores_committed_tree(fixture, repo_root):
        return
    path = Path(repo_root) / "docs" / "data" / REGISTRATION_STORE_NAME
    if not registration_signed(path):
        raise RegistrationUnsigned("strategy book registration is not signed")


def registration_signed(path: Path) -> bool:
    """True when the seal exists and carries a signature.

    Same signature test as ``strategy_book_memo_job.spend_enabled``: a
    non-empty ``signed_at``, ``signed`` true, a non-empty string
    ``signature``, or a non-empty signature object. The spend flag is separate.
    """
    payload = registration_record(path)
    if payload is None:
        return False
    signed_at = str(payload.get("signed_at") or "").strip()
    signature = payload.get("signature")
    signed_flag = payload.get("signed") is True
    signature_text = signature.strip() if isinstance(signature, str) else ""
    signature_obj = signature if isinstance(signature, dict) and signature else None
    return bool(signed_at or signed_flag or signature_text or signature_obj)


def forward_live(path: Path) -> bool:
    """True only when the seal is signed and ``forward_live`` is true.

    A missing file, a missing key, or an unsigned seal is false. Phase 1
    governs this go-live flag. The job may still dry-run while it is false.
    """
    if not registration_signed(path):
        return False
    payload = registration_record(path) or {}
    return payload.get("forward_live") is True


def forward_start_date(path: Path, *, decision: date) -> date:
    """First session the forward book may open.

    An explicit ``forward_start``, ``start_date`` or ``observe_start`` on the
    seal wins. Otherwise the signature's calendar date. Otherwise ``decision``.
    The archive keeps August–October; this date does not reach back for them.
    """
    payload = registration_record(path) or {}
    for key in ("forward_start", "start_date", "observe_start"):
        parsed = _iso_date(payload.get(key))
        if parsed is not None:
            return parsed
    signed = _iso_date(payload.get("signed_at"))
    if signed is not None:
        return signed
    return decision


def _iso_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def floor_for_checkpoint(level: float) -> float:
    """Floor that belongs to the highest checkpoint ``level`` reached.

    Above the last checkpoint the floor stays at +75% (section 4).
    """
    if level > CHECKPOINTS[-1][0]:
        return FLOOR_AT_OR_ABOVE_LAST
    chosen = 0.0
    for checkpoint, floor in CHECKPOINTS:
        if level + 1e-12 >= checkpoint:
            chosen = floor
    return chosen


def highest_checkpoint(return_multiple: float) -> float | None:
    """Highest checkpoint at or below a close's gain over the entry fill."""
    reached: float | None = None
    for checkpoint, _floor in CHECKPOINTS:
        if return_multiple + 1e-12 >= checkpoint:
            reached = checkpoint
    if return_multiple > CHECKPOINTS[-1][0]:
        return CHECKPOINTS[-1][0]
    return reached
