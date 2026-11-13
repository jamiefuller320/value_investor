"""UK/Europe point-in-time replay of the signed strategy book (plan step 3.3).

The draft registration is not sealed. This runner refuses every EODHD call
until ``docs/data/strategy_book_uk_replay_registration.json`` is sealed against
the registration document. It does not seal that file itself.

The walk is ``strategy_book_observe.walk_book`` with the US rehearsal options.
Window aggregates, the family interval and the verdict rules are the US
rehearsal helpers, pointed at the windows and the four-test family below.
Licensed prices and statement values stay in the gitignored cache.

Constants live in ``REGISTRATION_CONSTANTS`` and nowhere else.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import math
import os
import tempfile
import time
from array import array
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor import strategy_book_uk_tape as tape
from value_investor import strategy_book_us_rehearsal as rehearsal
from value_investor.ch_failed_name_statements import load_store
from value_investor.eodhd_coverage_check import EodhdClient, redact_token
from value_investor.models.ranking import compute_derived_columns
from value_investor.scoring import evaluate_universe, summarize_by_ticker
from value_investor.sector_scoring import add_sector_scores
from value_investor.signals import build_signals
from value_investor.strategy_book_observe import (
    US_REHEARSAL_MODE,
    GateTape,
    NameSpec,
    ScreenFact,
    options_for,
    walk_book,
)
from value_investor.strategy_book_us_rehearsal import (
    BASELINE,
    SENSITIVITY,
)
from value_investor.strategy_book_us_tape import with_variant

# --- Registration constants ---------------------------------------------------------------
# Draft strategy-book-uk-replay-registration, appendix, plus the currency-band
# and list-size figures in sections 2 and 8. One block. Do not copy a number
# out of here into another module.

REGISTRATION_CONSTANTS: dict[str, Any] = {
    "registration_id": "strategy-book-uk-replay-v0",
    "parent_registration_id": "owner-strategy-book-v0",
    "FTSE_RANK_COUNT": 350,
    "DAX_RANK_COUNT": 40,
    "CAC_RANK_COUNT": 40,
    "TAPE_START": "2013-01-01",
    "DEVELOPMENT_START": "2013-01-01",
    "DEVELOPMENT_END": "2018-12-31",
    "HOLDOUT_START": "2019-01-01",
    "HOLDOUT_END": "2025-09-30",
    "HOLDOUT_HALF_SPLIT": "2022-01-01",
    "WARMUP_CALENDAR_DAYS": 420,
    "EOD_FROM": "2011-11-08",
    "FILING_LAG_DAYS": 2,
    "STATEMENT_LAG_DAYS": 180,
    "INTERIM_STATEMENT_LAG_DAYS": 90,
    "STALE_FILING_DAYS": 456,
    "SHARES_DATE_FIELD": "dateFormatted",
    "REVENUE_DROP_PCT": 0.05,
    "REVENUE_FLAT_TOLERANCE_PCT": 0.01,
    "MARGIN_DROP_PP": 0.03,
    "EPS_ANNUAL_DROP_PCT": 0.20,
    "EPS_INTERIM_DROP_PCT": 0.10,
    "INTERIM_REVENUE_DROP_PCT": 0.05,
    "INTERIM_YOY_WINDOW_DAYS": 45,
    "INTERIM_MAX_AGE_DAYS": 460,
    "FCF_SHARP_FALL_PCT": 0.50,
    "SOFT_SIGNALS_TO_DECLINE": 2,
    "MIN_MEMBERS_WITH_DATA": 4,
    "MIN_COVERAGE_SHARE": 0.60,
    "PRICE_BREADTH_HEADWIND": 0.65,
    "SECTOR_RETURN_126D_HEADWIND": -0.10,
    "RETURN_LOOKBACK_126D": 126,
    "EARNINGS_BREADTH_HEADWIND": 0.50,
    "RSI_PERIOD": 14,
    "RSI_LEVEL": 35,
    "LOW_WINDOW_SESSIONS": 10,
    "ALT_RSI_LEVEL": 40,
    "ALT_SMA_WINDOW": 10,
    "ALT_SMA_DISTANCE": 0.03,
    "MAX_FILL_GAP_CALENDAR_DAYS": 5,
    "LAUNCH_RETURN": 0.10,
    "FAIL_TO_LAUNCH_INDEX": 63,
    "TIME_CAP_INDEX": 252,
    "REVIEW_INDEXES": [63, 126, 189],
    "DRAFT_HIGH_WINDOW": 10,
    "DRAFT_SWING_LIMIT_INDEX": 15,
    "DRAFT_REVIEW_SPACING": 63,
    "DRAFT_REVIEW_COUNT": 4,
    "RECOVERY_DROP": 0.08,
    "COOLDOWN_SESSIONS": 10,
    "STAKE_UNITS": 100,
    "MATURITY_SESSIONS": 63,
    "THESIS_CONFIRM_OBSERVATIONS": 2,
    "BASKET_MIN_NAMES": 5,
    "DEEP_DIP_LOOKBACK": 20,
    "DEEP_DIP_DROP": 0.08,
    "REGIME_SMA_SESSIONS": 200,
    "REGIME_ABOVE_SHARE": 0.5,
    "REGIME_MIN_NAMES": 5,
    "CHART_NOT_DAILY_GAP_SHARE": 0.05,
    "CHART_NOT_DAILY_GAP_DAYS": 5,
    "DELIST_HAIRCUT_BASELINE": 0.0,
    "DELIST_HAIRCUT_SENSITIVITY": -0.30,
    "TRADING_DAYS_TOLERANCE": 10,
    "FAMILY_ERROR": 0.10,
    "FAMILY_SIZE": 4,
    "FAMILY_COVERAGE": 0.975,
    "RESAMPLE_COUNT": 10000,
    "TAIL_BAR": -0.20,
    "DRAWDOWN_MULTIPLE": 1.5,
    "REGIME_HALF_MIN_MATURE": 12,
    "SLOT_COUNT": 20,
    "SLOT_RANDOM_ORDERS": 15,
    "SLOT_BOOK_RANDOM_SEED": 20261104,
    "FX_CARRY_DAYS": 5,
    "SMALL_CELL": 5,
    "MARKET_COSTS": {
        "ftse350": {"buy": 0.00525, "sell": 0.00025},
        "dax": {"buy": 0.00175, "sell": 0.00175},
        "cac40": {"buy": 0.00175, "sell": 0.00175},
    },
    "LEGACY_STRESS_TRADE_COST_PCT": 0.03,
    "DAILY_CALL_LIMIT": 100000,
    "DAILY_CALL_BUDGET_SOFT_CAP": 90000,
    "FUNDAMENTALS_CALL_WEIGHT": 10,
    "EOD_CALL_WEIGHT": 1,
    "DIV_CALL_WEIGHT": 1,
    "SPLIT_CALL_WEIGHT": 1,
    "LIST_CALL_WEIGHT": 1,
    "MAX_REQUESTS_PER_SEC": 5,
    "BUDGET_PROBE_SYMBOLS": 1,
    "LSE_WEIGHTED_CALLS": 86818,
    "LSE_ACTIVE_MEASURED": 3794,
    "LSE_DELISTED_MEASURED": 2884,
    "EURGBP_SANITY_LOW": 0.70,
    "EURGBP_SANITY_HIGH": 0.95,
    "USDGBP_SANITY_LOW": 0.65,
    "USDGBP_SANITY_HIGH": 0.90,
    "SUBSCRIPTION_START": "2026-11-12",
    "SUBSCRIPTION_END": "2026-12-10",
    "SEAL_TARGET": "2026-11-18",
    "EUROPE_FETCH_DEADLINE": "2026-11-24",
    "DEVELOPMENT_COMMIT": "2026-11-25",
    "REVEAL_TARGET": "2026-12-03",
    "STRONG_BUY_COMPOSITE": 0.70,
    "BUY_COMPOSITE": 0.55,
    "STRONG_BUY_PASS_FRACTION": 0.35,
    "STRONG_BUY_PASS_FLOOR": 5,
    "BUY_PASS_FRACTION": 0.22,
    "BUY_PASS_FLOOR": 3,
    "HOLD_PASS_RATE": 0.15,
    "HOLD_COMPOSITE": 0.45,
    "RISK_VETO_STRONG": 0.55,
    "RISK_VETO_BUY": 0.35,
    "MIN_QUALITY_FOR_ANALYSIS": 0.50,
    "MIN_QUALITY_FOR_BUY": 0.50,
    "MIN_QUALITY_FOR_STRONG_BUY": 0.65,
    "CHANNEL_DIRECTION_R2": 0.25,
    "DIVIDEND_YIELD_LOOKBACK_DAYS": 365,
    "DEBT_TO_EQUITY_SCALE": 100,
    "CAP_IMPLAUSIBLE_HIGH_GBP": 500_000_000_000,
    "CAP_IMPLAUSIBLE_LOW_GBP": 1_000_000,
    "EXCHANGES": {
        "LSE": {"market": "ftse350", "rank_count": 350, "rank_currency": "GBP"},
        "XETRA": {"market": "dax", "rank_count": 40, "rank_currency": "EUR"},
        "PA": {"market": "cac40", "rank_count": 40, "rank_currency": "EUR"},
    },
    "PROBE_CLASSES": [
        {"key": "carillion", "known_end": "2018-01-15", "klass": "known_failure"},
        {"key": "thomas_cook", "known_end": "2019-09-23", "klass": "known_failure"},
        {"key": "debenhams", "known_end": "2019-04-09", "klass": "known_failure"},
        {"key": "patisserie_holdings", "known_end": "2019-01-10", "klass": "known_failure"},
        {"key": "intu", "known_end": "2020-06-26", "klass": "known_failure"},
        {"key": "wirecard", "known_end": "2020-06-25", "klass": "known_failure"},
        {"key": "sirius", "known_end": "2020-03-03", "klass": "known_takeover"},
        {"key": "gkn", "known_end": "2018-03-29", "klass": "known_takeover"},
        {"key": "sky", "known_end": "2018-09-26", "klass": "known_takeover"},
        {"key": "aggreko", "known_end": "2021-08-16", "klass": "known_takeover"},
        {"key": "morrison", "known_end": "2021-10-04", "klass": "known_takeover"},
    ],
    "FX_PAIRS": ["EURGBP.FOREX", "USDGBP.FOREX"],
    "STATEMENT_BASIS": "eodhd_annual",
    "UNIVERSE_BASIS": {
        "ftse350": "lse_operating_cap_rank_1_350",
        "dax": "xetra_operating_cap_rank_1_40",
        "cac40": "pa_operating_cap_rank_1_40",
    },
    "DATA_QUALITY_BASIS": "three_fields",
    "SECTOR_LABEL_BASIS": "eodhd_general_current",
    "F9_STATUS": "f9_unverified",
    "RESEARCH_VERDICT": "absent",
    "MEMO_LABEL": "not_applicable",
    "ADJUSTED_SIGNAL": "absent",
    "T212_LISTED": "not_applicable",
    "LATE_SIGNAL": "not_applicable",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRATION_PATH = Path("docs/data/strategy_book_uk_replay_registration.json")
CURSOR_SAVE_EVERY = 25
FETCH_MAX_MINUTES_ENV = "UK_REPLAY_MAX_MINUTES"
STORE_PATH = Path("docs/data/strategy_book_uk_replay.json")
DOCUMENT_PATH = Path("docs/ops/strategy-book-uk-replay-registration-draft.md")
RUNBOOK_PATH = "docs/ops/strategy-book-uk-replay-runbook.md"
TITLE = "Strategy-book UK replay"
TITLE_FAILED = "Strategy-book UK replay store unreadable"
CACHE_ENV = "UK_REPLAY_CACHE"
_GATE_LABELS = (
    None,
    "clear",
    "declining",
    "insufficient_data",
    "sound",
    "headwind",
    "sector_missing",
)
_FORBIDDEN_KEYS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
        "raw_close",
        "last_price",
        "exit_fill",
        "entry_fill",
        "entry_first_seen",
        "ticker",
        "symbol",
        "totalRevenue",
        "netIncome",
        "totalAssets",
        "freeCashFlow",
        "Income_Statement",
        "Balance_Sheet",
        "Cash_Flow",
        "fundamentals",
        "financials",
        "dividends",
        "shares",
        "api_token",
        "token",
    }
)
_PROBE_KEYS = frozenset(row["key"] for row in REGISTRATION_CONSTANTS["PROBE_CLASSES"])


class ReplayRefused(RuntimeError):
    """The runner will not continue. No EODHD call is made after this."""


class UnsealedRegistration(ReplayRefused):
    """No sealed registration, so EODHD must not be called."""


class RevealRefused(ReplayRefused):
    """Holdout aggregates stay unwritten."""


class BudgetExhausted(RuntimeError):
    """The soft cap stopped the day. The cursor is saved. Nothing is dropped quietly."""


class TimeBudgetExhausted(RuntimeError):
    """The wall-clock budget stopped the run before the job limit. The cursor is saved."""


class WeightProbeFailed(ReplayRefused):
    """The probe response did not carry the planned call weight."""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def document_sha256(repo_root: Path = REPO_ROOT) -> str:
    return _sha256_file(Path(repo_root) / DOCUMENT_PATH)


def registration_payload(*, sealed: bool = False) -> dict[str, Any]:
    """The unsealed registration file. ``seal`` is what adds the owner stamp."""
    return {
        "registration_id": REGISTRATION_CONSTANTS["registration_id"],
        "parent_registration_id": REGISTRATION_CONSTANTS["parent_registration_id"],
        "sealed": sealed,
        "status": "sealed" if sealed else "draft",
        "document": str(DOCUMENT_PATH),
        "document_sha256": None,
        "sealed_at": None,
        "sealed_by": None,
        "reveal_stamp": None,
        "observe_only": True,
        "influences_live": False,
        "plan_step": "3.3",
        "constants": json.loads(json.dumps(REGISTRATION_CONSTANTS)),
    }


def load_registration(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    path = Path(repo_root) / REGISTRATION_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReplayRefused(f"{REGISTRATION_PATH} is missing or unreadable.") from exc
    if not isinstance(payload, dict):
        raise ReplayRefused(f"{REGISTRATION_PATH} is not an object.")
    return payload


def write_registration(payload: Mapping[str, Any], repo_root: Path = REPO_ROOT) -> Path:
    path = Path(repo_root) / REGISTRATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def seal_registration(owner: str, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Record the document sha256 and the owner stamp. Does not call EODHD."""
    if not str(owner).strip():
        raise ReplayRefused("seal needs an owner stamp.")
    payload = load_registration(repo_root)
    payload["sealed"] = True
    payload["status"] = "sealed"
    payload["document_sha256"] = document_sha256(repo_root)
    payload["sealed_at"] = _now()
    payload["sealed_by"] = str(owner).strip()
    payload["constants"] = json.loads(json.dumps(REGISTRATION_CONSTANTS))
    payload["influences_live"] = False
    write_registration(payload, repo_root)
    return payload


def require_sealed(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Refuse before any EODHD call unless the committed seal matches the document."""
    payload = load_registration(repo_root)
    if payload.get("sealed") is not True:
        raise UnsealedRegistration(
            f"{REGISTRATION_PATH} is not sealed. No replay call to EODHD is allowed. "
            f"The owner seals it with `ftse-strategy-book-uk-replay seal --owner <name>`."
        )
    digest = document_sha256(repo_root)
    if payload.get("document_sha256") != digest:
        raise UnsealedRegistration(
            "The registration document does not match the sealed sha256. "
            "No replay call to EODHD is allowed."
        )
    return payload


def stamp_reveal(owner: str, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Authorise the single holdout write. Does not call EODHD and does not seal."""
    if not str(owner).strip():
        raise RevealRefused("The reveal stamp needs an owner name.")
    store = _read_store(repo_root)
    if not store or not store.get("development"):
        raise RevealRefused(
            "No development result is committed. The reveal stamp waits for that block."
        )
    payload = load_registration(repo_root)
    payload["reveal_stamp"] = {"at": _now(), "by": str(owner).strip()}
    payload["sealed"] = bool(payload.get("sealed"))
    write_registration(payload, repo_root)
    return payload


def _read_store(repo_root: Path) -> dict[str, Any] | None:
    path = Path(repo_root) / STORE_PATH
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def default_cache_dir() -> Path:
    override = os.environ.get(CACHE_ENV)
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "strategy_book_uk_replay"


def _outside_repo(path: Path, repo_root: Path) -> None:
    resolved = path.expanduser().resolve()
    root = Path(repo_root).resolve()
    if resolved == root or root in resolved.parents:
        raise ReplayRefused(
            f"{resolved} is inside the repository. Licensed EODHD files stay in a temp dir."
        )


# --- Call budget and cursor ----------------------------------------------------------------


def _utc_day(moment: datetime | None = None) -> str:
    moment = moment or datetime.now(UTC)
    return moment.date().isoformat()


def empty_cursor(day: str) -> dict[str, Any]:
    return {
        "utc_day": day,
        "today_weighted": 0,
        "today_http": 0,
        "done": {},
        "lists": {},
        "fx": {},
        "probe_ok": False,
        "status": "partial",
        "history": [],
        "europe_not_fetched": False,
    }


def load_cursor(cache: Path, day: str) -> dict[str, Any]:
    path = cache / "cursor.json"
    if not path.exists():
        return empty_cursor(day)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_cursor(day)
    if not isinstance(payload, dict):
        return empty_cursor(day)
    if payload.get("utc_day") != day:
        history = list(payload.get("history") or [])
        history.append(
            {
                "utc_day": payload.get("utc_day"),
                "weighted": payload.get("today_weighted") or 0,
                "http": payload.get("today_http") or 0,
                "partial": payload.get("status") != "complete",
            }
        )
        payload["history"] = history
        payload["utc_day"] = day
        payload["today_weighted"] = 0
        payload["today_http"] = 0
    payload.setdefault("done", {})
    payload.setdefault("lists", {})
    payload.setdefault("fx", {})
    return payload


def _write_atomic(path: Path, text: str) -> None:
    """A killed job leaves the old file or the new one, never a truncated one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, path)


def _readable_json(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return True


def save_cursor(cache: Path, cursor: Mapping[str, Any]) -> None:
    _write_atomic(cache / "cursor.json", json.dumps(cursor, indent=2) + "\n")


class _Budget:
    """Soft cap for one UTC day. Exhaustion raises; it does not return an empty body."""

    def __init__(
        self,
        client: EodhdClient,
        cursor: dict[str, Any],
        cap: int,
        *,
        stop_at: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.cursor = cursor
        self.cap = cap
        self.stop_at = stop_at
        self.clock = clock

    def remaining(self) -> int:
        return self.cap - int(self.cursor.get("today_weighted") or 0)

    def call(self, weight: int, fetch: Callable[[], Any]) -> Any:
        if self.stop_at is not None and self.clock() >= self.stop_at:
            self.cursor["status"] = "partial"
            raise TimeBudgetExhausted("The wall-clock budget is spent. The next run resumes.")
        if self.remaining() < weight:
            self.cursor["status"] = "partial"
            raise BudgetExhausted(
                f"Soft cap {self.cap} weighted calls would be exceeded "
                f"({self.cursor.get('today_weighted')} used, next weight {weight})."
            )
        before = self.client.calls_used
        self.client.max_calls = before + weight
        self.client.budget_exhausted = False
        payload = fetch()
        if self.client.budget_exhausted and self.client.calls_used == before:
            self.cursor["status"] = "partial"
            raise BudgetExhausted("The client refused the call under the soft cap.")
        used = self.client.calls_used - before
        self.cursor["today_weighted"] = int(self.cursor.get("today_weighted") or 0) + used
        self.cursor["today_http"] = int(self.cursor.get("today_http") or 0) + 1
        return payload


def _weight_header(headers: Mapping[str, str]) -> int | None:
    raw = headers.get("x-call-weight")
    if raw is None:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _check_probe_weight(headers: Mapping[str, str], expected: int, kind: str) -> None:
    found = _weight_header(headers)
    if found is None:
        return
    if found != expected:
        raise WeightProbeFailed(
            f"Probe {kind} weighed {found}, not {expected}. The loop does not start."
        )


def _symbol_code(row: Mapping[str, Any], exchange: str) -> str:
    code = str(row.get("Code") or row.get("code") or "").strip()
    if not code:
        return ""
    if "." in code:
        return code
    return f"{code}.{exchange}"


def run_fetch(
    client: EodhdClient,
    *,
    repo_root: Path = REPO_ROOT,
    cache: Path | None = None,
    today: date | None = None,
    exchanges: Sequence[str] | None = None,
    max_minutes: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Fill the gitignored cache. A sealed registration is required before the first call.

    ``max_minutes`` stops the run cleanly before the CI job limit, so the cursor
    and cache are saved instead of being cut off mid-write.
    """
    require_sealed(repo_root)
    cache = Path(cache) if cache is not None else default_cache_dir()
    _outside_repo(cache, repo_root)
    cache.mkdir(parents=True, exist_ok=True)
    day = (today or datetime.now(UTC).date()).isoformat()
    cursor = load_cursor(cache, day)
    cap = int(REGISTRATION_CONSTANTS["DAILY_CALL_BUDGET_SOFT_CAP"])
    stop_at = clock() + max_minutes * 60 if max_minutes else None
    budget = _Budget(client, cursor, cap, stop_at=stop_at, clock=clock)
    wanted = list(exchanges or ("LSE", "XETRA", "PA"))
    deadline = date.fromisoformat(str(REGISTRATION_CONSTANTS["EUROPE_FETCH_DEADLINE"]))
    if (today or datetime.now(UTC).date()) > deadline:
        for exchange in ("XETRA", "PA"):
            if exchange in wanted and not cursor["lists"].get(f"{exchange}:active"):
                cursor["europe_not_fetched"] = True
                wanted = [item for item in wanted if item == "LSE"]
    status = "complete"
    stopped_by = None
    try:
        _fetch_lists(budget, cache, cursor, wanted)
        _fetch_fx(budget, cache, cursor)
        _require_fx_band(cache, cursor)
        _probe(budget, cache, cursor)
        _fetch_names(budget, cache, cursor, wanted)
    except BudgetExhausted:
        status = "partial"
        cursor["status"] = "partial"
        stopped_by = "soft_cap"
    except TimeBudgetExhausted:
        status = "partial"
        cursor["status"] = "partial"
        stopped_by = "time_budget"
    else:
        pending = [
            symbol
            for symbol, done in cursor["done"].items()
            if not done and symbol.split(".", 1)[-1] in wanted
        ]
        cursor["status"] = "partial" if pending else "complete"
        status = cursor["status"]
    save_cursor(cache, cursor)
    summary = {
        "status": status,
        "phase": "fetch",
        "stopped_by": stopped_by,
        "utc_day": day,
        "weighted": cursor["today_weighted"],
        "http": cursor["today_http"],
        "done_symbols": sum(1 for done in cursor["done"].values() if done),
        "europe_not_fetched": bool(cursor.get("europe_not_fetched")),
        "calls": _call_rows(cursor),
    }
    return summary


def _fetch_lists(
    budget: _Budget, cache: Path, cursor: dict[str, Any], exchanges: Sequence[str]
) -> None:
    for exchange in exchanges:
        for delisted in (False, True):
            key = f"{exchange}:{'delisted' if delisted else 'active'}"
            if cursor["lists"].get(key):
                continue
            rows = budget.call(
                int(REGISTRATION_CONSTANTS["LIST_CALL_WEIGHT"]),
                lambda exchange=exchange, delisted=delisted: budget.client.exchange_symbol_list(
                    exchange, delisted=delisted
                ),
            )
            _write_atomic(
                cache / "lists" / f"{key}.json", json.dumps(rows if isinstance(rows, list) else [])
            )
            cursor["lists"][key] = True


def _fetch_fx(budget: _Budget, cache: Path, cursor: dict[str, Any]) -> None:
    for symbol in REGISTRATION_CONSTANTS["FX_PAIRS"]:
        if cursor["fx"].get(symbol):
            continue
        rows = budget.call(
            int(REGISTRATION_CONSTANTS["EOD_CALL_WEIGHT"]),
            lambda symbol=symbol: budget.client.eod(
                symbol, from_date=str(REGISTRATION_CONSTANTS["EOD_FROM"])
            ),
        )
        _write_atomic(
            cache / "fx" / f"{symbol}.json", json.dumps(rows if isinstance(rows, list) else [])
        )
        cursor["fx"][symbol] = True


def _require_fx_band(cache: Path, cursor: Mapping[str, Any]) -> None:
    pairs = REGISTRATION_CONSTANTS["FX_PAIRS"]
    if not all(cursor.get("fx", {}).get(symbol) for symbol in pairs):
        return
    series = []
    for symbol in pairs:
        path = cache / "fx" / f"{symbol}.json"
        rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        series.append(list(_fx_map(rows).items()))
    ok, reason = tape.fx_band_ok(series[0], series[1])
    if not ok:
        raise ReplayRefused(reason or "FX sanity band failed. Pairs are not inverted.")


def _listed_symbols(cache: Path, exchange: str) -> list[str]:
    symbols = []
    for kind in ("active", "delisted"):
        path = cache / "lists" / f"{exchange}:{kind}.json"
        if not path.exists():
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            if isinstance(row, dict):
                code = _symbol_code(row, exchange)
                if code:
                    symbols.append(code)
    return sorted(set(symbols))


def _probe(budget: _Budget, cache: Path, cursor: dict[str, Any]) -> None:
    if cursor.get("probe_ok"):
        return
    symbols = _listed_symbols(cache, "LSE")
    if not symbols:
        cursor["probe_ok"] = True
        return
    symbol = symbols[0]
    fund_weight = int(REGISTRATION_CONSTANTS["FUNDAMENTALS_CALL_WEIGHT"])
    div_weight = int(REGISTRATION_CONSTANTS["DIV_CALL_WEIGHT"])
    fundamentals = budget.call(fund_weight, lambda: budget.client.fundamentals(symbol))
    _check_probe_weight(budget.client.last_headers, fund_weight, "fundamentals")
    _write_raw(cache, symbol, "fundamentals", fundamentals or {})
    dividends = budget.call(div_weight, lambda: budget.client.dividends(symbol))
    _check_probe_weight(budget.client.last_headers, div_weight, "dividends")
    _write_raw(cache, symbol, "dividends", dividends)
    cursor["probe_ok"] = True


def _write_raw(cache: Path, symbol: str, kind: str, payload: Any) -> None:
    _write_atomic(cache / "raw" / symbol / f"{kind}.json", json.dumps(payload))


def _fetch_names(
    budget: _Budget, cache: Path, cursor: dict[str, Any], exchanges: Sequence[str]
) -> None:
    eod_from = str(REGISTRATION_CONSTANTS["EOD_FROM"])
    weights = {
        "eod": int(REGISTRATION_CONSTANTS["EOD_CALL_WEIGHT"]),
        "fundamentals": int(REGISTRATION_CONSTANTS["FUNDAMENTALS_CALL_WEIGHT"]),
        "dividends": int(REGISTRATION_CONSTANTS["DIV_CALL_WEIGHT"]),
        "splits": int(REGISTRATION_CONSTANTS["SPLIT_CALL_WEIGHT"]),
    }
    finished = 0
    for exchange in exchanges:
        for symbol in _listed_symbols(cache, exchange):
            if cursor["done"].get(symbol):
                continue
            parts = {
                "eod": lambda symbol=symbol: budget.client.eod(symbol, from_date=eod_from),
                "fundamentals": lambda symbol=symbol: budget.client.fundamentals(symbol),
                "dividends": lambda symbol=symbol: budget.client.dividends(symbol),
                "splits": lambda symbol=symbol: budget.client.splits(symbol),
            }
            for kind, fetch in parts.items():
                target = cache / "raw" / symbol / f"{kind}.json"
                if target.exists() and _readable_json(target):
                    continue
                payload = budget.call(weights[kind], fetch)
                _write_raw(cache, symbol, kind, payload if payload is not None else [])
            cursor["done"][symbol] = True
            finished += 1
            if finished % CURSOR_SAVE_EVERY == 0:
                save_cursor(cache, cursor)
                print(
                    f"fetch progress: {exchange} {finished} names this run, "
                    f"{cursor['today_weighted']} weighted today",
                    flush=True,
                )


def _call_rows(cursor: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {
            "utc_day": item.get("utc_day"),
            "weighted": item.get("weighted"),
            "http": item.get("http"),
            "partial": item.get("partial"),
        }
        for item in cursor.get("history") or []
        if isinstance(item, dict)
    ]
    rows.append(
        {
            "utc_day": cursor.get("utc_day"),
            "weighted": cursor.get("today_weighted"),
            "http": cursor.get("today_http"),
            "partial": cursor.get("status") != "complete",
        }
    )
    return rows


# --- Walk ------------------------------------------------------------------------------------


def _family_registration() -> dict[str, Any]:
    constants = REGISTRATION_CONSTANTS
    return {
        "confirmation_family": {
            "alpha": constants["FAMILY_ERROR"],
            "family_size": constants["FAMILY_SIZE"],
            "resamples": constants["RESAMPLE_COUNT"],
            "tests": [
                {"name": "primary"},
                {"name": "deep_dip"},
                {"name": "revenue_growing"},
                {"name": "trend_not_falling"},
            ],
        },
        "windows": {
            "development": {
                "first_signal": constants["DEVELOPMENT_START"],
                "last_signal": constants["DEVELOPMENT_END"],
            },
            "confirmation": {
                "first_signal": constants["HOLDOUT_START"],
                "last_signal": constants["HOLDOUT_END"],
                "halves": [
                    f"{constants['HOLDOUT_START']}/{constants['HOLDOUT_HALF_SPLIT']}",
                    f"{constants['HOLDOUT_HALF_SPLIT']}/{constants['HOLDOUT_END']}",
                ],
            },
        },
        "prices": {
            "delisting_sensitivity_haircut_non_merger": constants["DELIST_HAIRCUT_SENSITIVITY"]
        },
    }


def _bars(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        day = tape._parse_date(row.get("date"))
        close = tape.finite(row.get("close"))
        adjusted = tape.finite(row.get("adjusted_close"))
        if day is None or close is None or adjusted is None:
            continue
        high, low = tape.scaled_high_low(
            tape.finite(row.get("high")), tape.finite(row.get("low")), close, adjusted
        )
        out.append(
            {
                "date": day,
                "close": close,
                "adjusted": adjusted,
                "high": high,
                "low": low,
            }
        )
    out.sort(key=lambda item: item["date"])
    return out


_DAYS: dict[date, date] = {}
_DAY_BEFORE: dict[date, date] = {}
_GENERAL_KEYS = (
    "Name",
    "name",
    "Sector",
    "sector",
    "GicSector",
    "Industry",
    "industry",
    "Type",
    "type",
    "CurrencyCode",
    "ISIN",
)
_SMA_RESET_EVERY = 200
_SMA_TIE_TOLERANCE = 1e-7


def _day(day: date) -> date:
    """One ``date`` object per calendar day across every name."""
    return _DAYS.setdefault(day, day)


def _day_before(day: date) -> date:
    found = _DAY_BEFORE.get(day)
    if found is None:
        found = _DAY_BEFORE[day] = _day(day - timedelta(days=1))
    return found


class _Bars:
    """``_bars`` rows as columns. A missing high or low is NaN."""

    __slots__ = ("adjusted", "close", "dates", "high", "highs_ok", "low", "lows_ok")

    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self.dates = [_day(row["date"]) for row in rows]
        self.close = array("d", [row["close"] for row in rows])
        self.adjusted = array("d", [row["adjusted"] for row in rows])
        self.highs_ok = all(row["high"] is not None for row in rows)
        self.lows_ok = all(row["low"] is not None for row in rows)
        self.high = array("d", [math.nan if row["high"] is None else row["high"] for row in rows])
        self.low = array("d", [math.nan if row["low"] is None else row["low"] for row in rows])

    def __len__(self) -> int:
        return len(self.dates)

    def close_on(self, day: date) -> float | None:
        """Raw close of the first bar dated ``day``."""
        position = bisect_left(self.dates, day)
        if position < len(self.dates) and self.dates[position] == day:
            return self.close[position]
        return None


def _share_rows(block: Any) -> list[dict[str, Any]]:
    field = str(tape._const("SHARES_DATE_FIELD"))
    rows = block.values() if isinstance(block, Mapping) else (block or ())
    return [
        {field: row.get(field), "shares": row.get("shares")}
        for row in rows
        if isinstance(row, Mapping)
    ]


def _slim_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Keep what develop and reveal read; drop raw prices and statement JSON.

    Statements are parsed once here, not once per session.
    """
    if record.get("slim"):
        return dict(record)
    fundamentals = record.get("fundamentals") or {}
    general = fundamentals.get("General") or {}
    shares = fundamentals.get("outstandingShares") or {}
    return {
        "slim": True,
        "symbol": record.get("symbol"),
        "market": record.get("market"),
        "name": record.get("name"),
        "currency": record.get("currency"),
        "general_type": record.get("general_type"),
        "sector": record.get("sector"),
        "isin": record.get("isin"),
        "delisted": bool(record.get("delisted")),
        "ch_key": record.get("ch_key"),
        "ch_filings": record.get("ch_filings"),
        "general": {key: general[key] for key in _GENERAL_KEYS if key in general},
        "eodhd_annual": tape.eodhd_annual_statements(fundamentals),
        "quarterly": tape.eodhd_quarterly(fundamentals),
        "interim": tape.interim_eps_rows(fundamentals),
        "shares_annual": _share_rows(shares.get("annual")),
        "shares_quarterly": _share_rows(shares.get("quarterly")),
        "bars": _Bars(_bars(record.get("eod") or [])),
        "dividends": record.get("dividends") or [],
        "splits": record.get("splits") or [],
    }


class _VerdictTape:
    """``decline_verdict`` per session, computed once per run of identical inputs.

    The verdict reads the session only through which rows are visible: a row
    enters at ``visible_from`` and leaves when stale (annual) or too old
    (quarterly, interim EPS). Between those days the verdict cannot change.
    """

    def __init__(
        self,
        annual: Sequence[Mapping[str, Any]],
        quarterly: Sequence[Mapping[str, Any]],
        interim: Sequence[Mapping[str, Any]],
    ) -> None:
        self.annual = annual
        self.quarterly = quarterly
        self.interim = interim
        points: set[date] = set()
        stale = timedelta(days=int(tape._const("STALE_FILING_DAYS")) + 1)
        aged = timedelta(days=int(tape._const("INTERIM_MAX_AGE_DAYS")) + 1)
        for rows, gone in ((annual, stale), (quarterly, aged), (interim, aged)):
            for row in rows:
                visible = row.get("visible_from")
                period_end = row.get("period_end")
                if visible is None or period_end is None:
                    continue
                points.add(visible)
                points.add(period_end + gone)
        self.points = sorted(points)
        self.verdicts: dict[int, dict[str, Any]] = {}

    def segment(self, session: date) -> int:
        index = bisect_right(self.points, session)
        if index not in self.verdicts:
            self.verdicts[index] = tape.decline_verdict(
                self.annual, self.quarterly, self.interim, session
            )
        return index


def _gate_detail(
    tape_rows: _VerdictTape,
    segments: Sequence[int],
    basis: Callable[[int], tuple[str | None, str | None]],
) -> Callable[[int], dict[str, Any]]:
    seen: dict[int, dict[str, Any]] = {}

    def _detail(index: int) -> dict[str, Any]:
        if index not in seen:
            verdict = tape_rows.verdicts[segments[index]]
            sector_basis, sector_name = basis(index)
            seen[index] = {
                "checks": copy.deepcopy(verdict["checks"]),
                "soft_checks": list(verdict["soft"]),
                "sector_basis": sector_basis,
                "sector_name": sector_name,
            }
        return seen[index]

    return _detail


def _resolved_fx(
    eurgbp: Mapping[date, float] | None,
    usdgbp: Mapping[date, float] | None,
    cache: Path | None,
) -> tuple[tape.FxSeries, tape.FxSeries]:
    """Prefer an explicit series. A fetch cache supplies the pair files."""
    loaded_eur: dict[date, float] = {}
    loaded_usd: dict[date, float] = {}
    if cache is not None:
        loaded_eur, loaded_usd = _fx_from_cache(cache)
    return tape.FxSeries(eurgbp if eurgbp is not None else loaded_eur), tape.FxSeries(
        usdgbp if usdgbp is not None else loaded_usd
    )


def _fx_from_cache(cache: Path) -> tuple[dict[date, float], dict[date, float]]:
    loaded = []
    for symbol in REGISTRATION_CONSTANTS["FX_PAIRS"]:
        path = cache / "fx" / f"{symbol}.json"
        rows: list[Any] = []
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else []
        loaded.append(_fx_map(rows))
    return loaded[0], loaded[1]


def _fx_map(rows: Sequence[Mapping[str, Any]]) -> dict[date, float]:
    found = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        day = tape._parse_date(row.get("date"))
        close = tape.finite(row.get("close"))
        if day is not None and close is not None and close > 0:
            found[day] = close
    return found


def assemble_specs(
    records: Sequence[Mapping[str, Any]],
    *,
    eurgbp: Mapping[date, float],
    usdgbp: Mapping[date, float],
    ch_store: Mapping[str, Any] | None = None,
    score: bool = True,
) -> dict[str, Any]:
    """Build walker ``NameSpec`` rows from parsed EODHD records. Nothing is written.

    ``prepared`` in the result carries each name's resolved Companies House key
    and merged statements for ``apply_sector_frame`` and the probe flags.
    """
    ch_store = ch_store if ch_store is not None else {"names": []}
    eurgbp = eurgbp if isinstance(eurgbp, tape.FxSeries) else tape.FxSeries(eurgbp)
    usdgbp = usdgbp if isinstance(usdgbp, tape.FxSeries) else tape.FxSeries(usdgbp)
    prepared = []
    for record in records:
        slim = _slim_record(record)
        symbol = str(slim.get("symbol") or "")
        market = str(slim.get("market") or "")
        bars: _Bars = slim["bars"]
        if not symbol or not market or not len(bars):
            continue
        general = slim["general"]
        name = slim.get("name") or general.get("Name")
        ch_key = slim.get("ch_key") or tape.match_ch_record(
            ch_store,
            symbol=symbol,
            name=str(name or "") or None,
            last_bar=bars.dates[-1],
        )
        ch_filings = slim.get("ch_filings") or tape.ch_filings_for_key(ch_store, ch_key or "")
        prepared.append(
            {
                "symbol": symbol,
                "market": market,
                "currency": slim.get("currency") or general.get("CurrencyCode"),
                "general_type": slim.get("general_type") or general.get("Type"),
                "sector": slim.get("sector") or general.get("Sector") or general.get("GicSector"),
                "name": name,
                "delisted": bool(slim.get("delisted")),
                "ch_key": ch_key,
                "isin": slim.get("isin") or general.get("ISIN"),
                "bars": bars,
                "annual": tape.merge_statement_years(
                    slim["eodhd_annual"], tape.ch_statements(ch_filings)
                ),
                "quarterly": slim["quarterly"],
                "interim": slim["interim"],
                "shares_annual": slim["shares_annual"],
                "shares_quarterly": slim["shares_quarterly"],
                "dividends": slim["dividends"],
                "splits": slim["splits"],
                "ch_filings": ch_filings,
                "fund_or_trust": tape.fund_or_trust(symbol, general),
            }
        )
    by_market: dict[str, list[dict[str, Any]]] = {}
    for row in prepared:
        by_market.setdefault(row["market"], []).append(row)
    month_sets: dict[str, list[tuple[date, set[str]]]] = {}
    bias_rows: list[dict[str, Any]] = []
    counters = Counter()
    for market, rows in by_market.items():
        sessions = sorted({day for row in rows for day in row["bars"].dates})
        ends = [
            day
            for day in tape.month_end_dates(sessions)
            if day >= date.fromisoformat(str(REGISTRATION_CONSTANTS["TAPE_START"]))
        ]
        exchange = next(
            (
                code
                for code, meta in REGISTRATION_CONSTANTS["EXCHANGES"].items()
                if meta["market"] == market
            ),
            None,
        )
        meta = REGISTRATION_CONSTANTS["EXCHANGES"].get(exchange or "", {})
        rank_count = int(meta.get("rank_count") or REGISTRATION_CONSTANTS["FTSE_RANK_COUNT"])
        rank_currency = str(meta.get("rank_currency") or "GBP")
        sets = []
        for day in ends:
            cap_rows = []
            for row in rows:
                last = row["bars"].dates[-1]
                if not tape.listed_on(day, delisted=row["delisted"], last_bar=last):
                    continue
                close = row["bars"].close_on(day)
                shares = tape.select_shares(row["shares_annual"], row["shares_quarterly"], day)
                scaled, unparsed = (None, False)
                if shares is not None:
                    scaled, unparsed = tape.scale_shares(
                        shares["shares"], shares["date"], row["splits"], day
                    )
                cap = tape.cap_in_rank_currency(
                    close,
                    row["currency"],
                    scaled,
                    rank_currency=rank_currency,
                    session=day,
                    eurgbp=eurgbp,
                    usdgbp=usdgbp,
                )
                if unparsed:
                    cap = {"cap": None, "reason": "cap_not_computable"}
                cap_rows.append(
                    {
                        "symbol": row["symbol"],
                        "general_type": row["general_type"],
                        "fund_or_trust": row["fund_or_trust"],
                        "cap": cap.get("cap"),
                        "cap_reason": cap.get("reason"),
                        "split_unparsed": unparsed,
                    }
                )
            ranked = tape.rank_month(cap_rows, rank_count=rank_count)
            counters["cap_tie_broken_by_symbol"] += ranked["cap_tie_broken_by_symbol"]
            counters["split_unparsed"] += ranked["split_unparsed"]
            members = set(ranked["members"])
            sets.append((day, members))
            missing_revenue = 0
            for row in rows:
                if row["symbol"] not in members:
                    continue
                verdict = tape.decline_verdict(row["annual"], [], [], day)
                if not verdict["revenue_evaluable"]:
                    missing_revenue += 1
            bias_rows.append(
                {
                    "ranked": len(members),
                    "revenue_not_evaluable": missing_revenue,
                    "list_status": "later_delisted"
                    if any(row["delisted"] and row["symbol"] in members for row in rows)
                    else "still_listed",
                    "considered": ranked["considered"],
                    "cap_not_computable": ranked["cap_not_computable"],
                    "excluded_fund_or_trust": ranked["excluded_fund_or_trust"],
                }
            )
        month_sets[market] = sets
    last_session = max(row["bars"].dates[-1] for row in prepared)
    issuers = {row["symbol"]: tape.issuer_key(row["symbol"], row.get("isin")) for row in prepared}
    overlap = 0
    # Drop cross-market names session by session, then rebuild spans from the kept sets.
    trimmed: dict[str, list[tuple[date, set[str]]]] = {market: [] for market in month_sets}
    dates = sorted({day for sets in month_sets.values() for day, _members in sets})
    for day in dates:
        current = {
            market: members
            for market, sets in month_sets.items()
            for end, members in sets
            if end == day
        }
        kept, dropped = tape.drop_overlap(current, issuers)
        overlap += dropped
        for market, members in kept.items():
            trimmed[market].append((day, members))
    spans = {market: tape.membership_spans(sets, last_session) for market, sets in trimmed.items()}
    panel_rows = _panel_rows(prepared, trimmed, eurgbp, usdgbp)
    signals = _score_panel(panel_rows) if score and panel_rows else []
    specs, haircuts = _specs_from(prepared, spans, signals, issuers)
    ranked_symbols = {
        symbol for market_spans in spans.values() for symbol, rows in market_spans.items() if rows
    }
    for row in prepared:
        del row["bars"]
    return {
        "specs": specs,
        "haircuts": haircuts,
        "bias_rows": bias_rows,
        "overlap_excluded": overlap,
        "counts": dict(counters),
        "markets": sorted({row["market"] for row in prepared}),
        "ranked_symbols": ranked_symbols,
        "prepared": prepared,
    }


def _panel_rows(
    prepared: Sequence[Mapping[str, Any]],
    month_sets: Mapping[str, Sequence[tuple[date, set[str]]]],
    eurgbp: Mapping[date, float],
    usdgbp: Mapping[date, float],
) -> list[dict[str, Any]]:
    rows = []
    by_symbol = {row["symbol"]: row for row in prepared}
    for market, sets in month_sets.items():
        meta = next(
            (
                item
                for item in REGISTRATION_CONSTANTS["EXCHANGES"].values()
                if item["market"] == market
            ),
            {"rank_currency": "GBP"},
        )
        for day, members in sets:
            for symbol in sorted(members):
                row = by_symbol[symbol]
                close = row["bars"].close_on(day)
                if close is None:
                    continue
                shares = tape.select_shares(row["shares_annual"], row["shares_quarterly"], day)
                scaled = None
                if shares is not None:
                    scaled, unparsed = tape.scale_shares(
                        shares["shares"], shares["date"], row["splits"], day
                    )
                    if unparsed:
                        scaled = None
                cap = tape.cap_in_rank_currency(
                    close,
                    row["currency"],
                    scaled,
                    rank_currency=str(meta["rank_currency"]),
                    session=day,
                    eurgbp=eurgbp,
                    usdgbp=usdgbp,
                )
                annual = row["annual"]
                visible = [
                    item
                    for item in annual
                    if item.get("visible_from") is not None
                    and item["visible_from"] <= day
                    and not tape.is_stale(day, item.get("period_end"))
                ]
                latest = max(visible, key=lambda item: item["year"]) if visible else None
                prior = None
                if latest is not None:
                    prior = next(
                        (item for item in visible if int(item["year"]) == int(latest["year"]) - 1),
                        None,
                    )
                fields = tape.panel_row_from_statement(
                    latest,
                    prior,
                    market_cap=cap.get("cap"),
                    raw_close=close,
                    dividend=tape.dividend_yield(row["dividends"], day, close),
                    sector=row.get("sector"),
                    shares_fallback=scaled,
                )
                fields["as_of"] = day.isoformat()
                fields["ticker"] = symbol
                fields["name"] = row.get("name")
                rows.append(fields)
    return rows


def _score_panel(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(rows)
    scored: list[dict[str, Any]] = []
    for as_of, group in frame.groupby("as_of", sort=True):
        universe = group.drop(columns=["as_of"]).copy()
        quality = universe["data_quality_score"].tolist()
        universe = compute_derived_columns(universe)
        universe = add_sector_scores(universe)
        universe["data_quality_score"] = quality
        model_results = evaluate_universe(universe)
        summary = summarize_by_ticker(model_results)
        signals = build_signals(universe, model_results, summary)
        for _, signal_row in signals.iterrows():
            scored.append(
                {
                    "as_of": str(as_of)[:10],
                    "ticker": str(signal_row["ticker"]),
                    "signal": str(signal_row.get("signal") or ""),
                    "composite_score": tape.finite(signal_row.get("composite_score")),
                    "data_quality_score": tape.finite(signal_row.get("data_quality_score")),
                    "conviction_score": tape.finite(signal_row.get("conviction_score")),
                    "models_passed": int(tape.finite(signal_row.get("models_passed")) or 0),
                    "sector": signal_row.get("sector"),
                }
            )
    return scored


def _specs_from(
    prepared: Sequence[Mapping[str, Any]],
    spans: Mapping[str, Mapping[str, list[tuple[date, date]]]],
    signals: Sequence[Mapping[str, Any]],
    issuers: Mapping[str, str],
) -> tuple[list[NameSpec], dict[str, dict[str, float]]]:
    by_symbol_signals: dict[str, list[Mapping[str, Any]]] = {}
    for row in signals:
        by_symbol_signals.setdefault(str(row["ticker"]), []).append(row)
    specs: list[NameSpec] = []
    haircuts: dict[str, dict[str, float]] = {}
    for row in prepared:
        symbol = row["symbol"]
        market = row["market"]
        bars: _Bars = row["bars"]
        sessions = bars.dates
        screens = []
        for signal in by_symbol_signals.get(symbol, []):
            screens.append(
                ScreenFact(
                    run_date=date.fromisoformat(str(signal["as_of"])[:10]),
                    signal=signal.get("signal"),
                    adjusted_signal=None,
                    research_verdict=str(REGISTRATION_CONSTANTS["RESEARCH_VERDICT"]),
                    sector=signal.get("sector") or row.get("sector"),
                    fields={
                        "composite_score": signal.get("composite_score"),
                        "data_quality_score": signal.get("data_quality_score"),
                        "conviction_score": signal.get("conviction_score"),
                        "models_passed": signal.get("models_passed"),
                        "data_quality_basis": REGISTRATION_CONSTANTS["DATA_QUALITY_BASIS"],
                    },
                )
            )
        gates = _gate_tape(row, sessions)
        spec = NameSpec(
            market=market,
            ticker=symbol,
            sessions=sessions,
            closes=bars.adjusted.tolist(),
            highs=bars.high.tolist() if bars.highs_ok else None,
            lows=bars.low.tolist() if bars.lows_ok else None,
            screens=screens,
            gates=gates,
            universe=list(spans.get(market, {}).get(symbol) or []),
            book_key=issuers.get(symbol),
            terminal_haircut=None,
        )
        specs.append(spec)
        if row["delisted"]:
            haircuts[symbol] = {
                BASELINE: float(
                    tape.haircut_for(row.get("ch_key"), variant="baseline", delisted=True) or 0.0
                ),
                SENSITIVITY: float(
                    tape.haircut_for(row.get("ch_key"), variant="sensitivity", delisted=True) or 0.0
                ),
            }
    return specs, haircuts


def _gate_tape(row: Mapping[str, Any], sessions: list[date]) -> GateTape:
    verdicts = _VerdictTape(row["annual"], row["quarterly"], row["interim"])
    sector_name = row.get("sector")
    # Price breadth is filled by ``sector_frame`` when several names share a sector.
    # A name walked alone keeps the price side uncovered, so the table says
    # insufficient_data unless the label itself is missing.
    decision = tape.sector_decision(
        price_coverage=False,
        price_trigger=False,
        decline_coverage=False,
        decline_breadth=None,
        sector_missing=not sector_name,
    )
    labels = {label: index for index, label in enumerate(_GATE_LABELS)}
    segments = array("i", [verdicts.segment(session) for session in sessions])
    codes_decline = array("b", [labels[verdicts.verdicts[index]["verdict"]] for index in segments])
    codes_sector = array("b", [labels[decision["verdict"]]]) * len(sessions)
    return GateTape(
        [_day_before(day) for day in sessions],
        codes_decline,
        codes_sector,
        _GATE_LABELS,
        _gate_detail(verdicts, segments, lambda _index: (decision["sector_basis"], sector_name)),
    )


def apply_sector_frame(specs: list[NameSpec], prepared: Sequence[Mapping[str, Any]]) -> None:
    """Replace single-name sector labels with the market's price and decline breadth.

    ``assemble_specs`` leaves the price side uncovered. This pass is the section
    3.3 table once every name in the market is known. ``prepared`` is
    ``assemble_specs(...)["prepared"]``.
    """
    by_ticker = {row["symbol"]: row for row in prepared}
    markets: dict[str, list[NameSpec]] = {}
    for spec in specs:
        markets.setdefault(spec.market, []).append(spec)
    for _market, group in markets.items():
        if not any(spec.sessions for spec in group):
            continue
        _paint_sector(group, by_ticker)


def _paint_sector(
    group: list[NameSpec],
    by_ticker: Mapping[str, Mapping[str, Any]],
) -> None:
    """One decline pass per name, then the shared sector table on those verdicts.

    The table depends on the sector label and the session, not on the name
    asking, so it is built once per label.
    """
    sectors: dict[str, list[str]] = {}
    verdicts: dict[str, _VerdictTape] = {}
    series: dict[str, tuple[list[date], list[float]]] = {}
    for spec in group:
        row = by_ticker.get(spec.ticker) or {}
        label = str(row.get("sector") or "")
        if label:
            sectors.setdefault(label, []).append(spec.ticker)
        verdicts[spec.ticker] = _VerdictTape(
            row.get("annual") or [], row.get("quarterly") or [], row.get("interim") or []
        )
        days: list[date] = []
        values: list[float] = []
        for day, price in zip(spec.sessions or [], spec.closes or [], strict=False):
            if days and days[-1] == day:
                values[-1] = price
            elif days and day < days[-1]:
                raise ValueError(f"{spec.ticker} sessions are not sorted")
            else:
                days.append(day)
                values.append(price)
        series[spec.ticker] = (days, values)
    tables = {label: _sector_table(peers, series, verdicts) for label, peers in sectors.items()}
    empty = _sector_decision_from(0, 0, 0, [], 0, 0)
    missing = {"verdict": "sector_missing", "sector_basis": "sector_missing"}
    labels = {name: position for position, name in enumerate(_GATE_LABELS)}
    for spec in group:
        row = by_ticker.get(spec.ticker) or {}
        label = str(row.get("sector") or "")
        table = tables.get(label, {})
        sessions = spec.sessions or []
        own = verdicts[spec.ticker]
        segments = array("i", [own.segment(day) for day in sessions])
        decisions = [missing if not label else table.get(day, empty) for day in sessions]
        spec.gates = GateTape(
            [_day_before(day) for day in sessions],
            array("b", [labels[own.verdicts[index]["verdict"]] for index in segments]),
            array("b", [labels[decision["verdict"]] for decision in decisions]),
            _GATE_LABELS,
            _gate_detail(
                own,
                segments,
                lambda index, decisions=decisions, label=label: (
                    decisions[index]["sector_basis"],
                    label or None,
                ),
            ),
        )


def _sector_table(
    peers: Sequence[str],
    series: Mapping[str, tuple[list[date], list[float]]],
    verdicts: Mapping[str, _VerdictTape],
) -> dict[date, dict[str, Any]]:
    """Section 3.3 decision for every session any peer has.

    Price breadth uses each name's own last 200 adjusted closes, not calendar days.
    Trend values are summed in peer order, as one pass over the peers per day would.
    """
    lookback = int(REGISTRATION_CONSTANTS["RETURN_LOOKBACK_126D"])
    sma = int(REGISTRATION_CONSTANTS["REGIME_SMA_SESSIONS"])
    # members, with_sma, below, with_verdict, declining, trend values
    stats: dict[date, list[Any]] = {}
    for ticker in peers:
        days, values = series.get(ticker) or ([], [])
        tape_rows = verdicts.get(ticker)
        running = 0.0
        for position, day in enumerate(days):
            row = stats.get(day)
            if row is None:
                row = stats[day] = [0, 0, 0, 0, 0, []]
            row[0] += 1
            close = values[position]
            running += close
            if position >= sma:
                running -= values[position - sma]
            if position + 1 >= sma:
                if (position + 1 - sma) % _SMA_RESET_EVERY == 0:
                    running = math.fsum(values[position - sma + 1 : position + 1])
                row[1] += 1
                if _below_sma(close, running, values, position, sma):
                    row[2] += 1
            if position >= lookback:
                base = values[position - lookback]
                if base and base > 0:
                    row[5].append(close / base - 1.0)
            if tape_rows is not None:
                verdict = tape_rows.verdicts[tape_rows.segment(day)]["verdict"]
                if verdict in {"clear", "declining"}:
                    row[3] += 1
                    row[4] += int(verdict == "declining")
    return {
        day: _sector_decision_from(row[0], row[1], row[2], row[5], row[3], row[4])
        for day, row in stats.items()
    }


def _below_sma(
    close: float, running: float, values: Sequence[float], position: int, sma: int
) -> bool:
    """``close < sum(window) / len(window)``, exact near a tie."""
    mean = running / sma
    scale = max(abs(close), abs(mean), 1e-300)
    if abs(close - mean) > _SMA_TIE_TOLERANCE * scale:
        return close < mean
    window = values[position - sma + 1 : position + 1]
    return close < sum(window) / len(window)


def _sector_decision_from(
    members: int,
    with_sma: int,
    below: int,
    trend_values: Sequence[float],
    with_verdict: int,
    declining: int,
) -> dict[str, Any]:
    price_covered = tape.coverage_met(with_sma, members) and tape.coverage_met(
        len(trend_values), members
    )
    breadth = None if not with_sma else below / with_sma
    trend = None if not trend_values else sum(trend_values) / len(trend_values)
    decline_covered = tape.coverage_met(with_verdict, members)
    breadth_decline = None if not with_verdict else declining / with_verdict
    return tape.sector_decision(
        price_coverage=price_covered,
        price_trigger=tape.price_trigger(breadth, trend, covered=price_covered),
        decline_coverage=decline_covered,
        decline_breadth=breadth_decline,
        sector_missing=False,
    )


def walk_variants(
    specs: list[NameSpec],
    haircuts: Mapping[str, Mapping[str, float]],
    *,
    last_signal: str,
) -> dict[str, dict[str, Any]]:
    """Both delisting haircuts, through the sealed walker. The walker owns exits."""
    options = dataclasses.replace(
        options_for(US_REHEARSAL_MODE),
        entry_not_before=date.fromisoformat(str(REGISTRATION_CONSTANTS["DEVELOPMENT_START"])),
        entry_not_after=date.fromisoformat(last_signal),
    )
    out = {}
    for variant in (BASELINE, SENSITIVITY):
        out[variant] = walk_book(with_variant(specs, haircuts, variant), options=options)
    return out


def _window_block(
    episodes: list[dict[str, Any]],
    events: list[dict[str, Any]],
    window: tuple[str, str],
    *,
    holdout: bool,
    scoring: date,
    delisted: set[str],
) -> dict[str, Any]:
    fam = rehearsal.family(_family_registration())
    coverage = fam["coverage"] if holdout else fam["development_coverage"]
    halves = None
    if holdout:
        split = str(REGISTRATION_CONSTANTS["HOLDOUT_HALF_SPLIT"])
        halves = (
            (str(REGISTRATION_CONSTANTS["HOLDOUT_START"]), split),
            (split, str(REGISTRATION_CONSTANTS["HOLDOUT_END"])),
        )
    block = rehearsal.window_block(
        episodes,
        events,
        window,
        coverage=coverage,
        fam=fam,
        scoring=scoring,
        delisted=delisted,
        halves=halves,
        label="bonferroni" if holdout else "development_descriptive",
    )
    primary = [row for row in episodes if row.get("column") == "primary" and row.get("mature")]
    primary = [
        row for row in primary if window[0] <= str(row.get("signal_session"))[:10] <= window[1]
    ]
    block["bench"]["trend_not_falling"] = rehearsal._bench_block(
        primary, "trend_not_falling", coverage, fam, fam["seed"] + 12, halves
    )
    block["by_market"] = {
        market: rehearsal._mini([row for row in primary if row.get("market") == market])
        for market in ("ftse350", "dax", "cac40")
    }
    return block


def _dirty_flags(
    block: Mapping[str, Any],
    sensitivity_verdict: str,
    episodes: Sequence[Mapping[str, Any]],
    *,
    eurgbp: Mapping[date, float] | None,
) -> dict[str, bool]:
    primary = block.get("primary") or {}
    verdict = rehearsal.primary_verdict(
        primary.get("fair_cost_median"),
        primary.get("interval") or {},
        int(primary.get("mature") or 0),
    )
    tails = block.get("tails") or {}
    p5 = tails.get("p5_fair_cost")
    sterling_missing, sterling_miss = _sterling_flags(episodes, eurgbp)
    return {
        "pass_delisting_sensitive": verdict == "pass" and sensitivity_verdict != "pass",
        "tail_breach": p5 is not None and float(p5) < float(REGISTRATION_CONSTANTS["TAIL_BAR"]),
        "drawdown_breach": _drawdown_breach(episodes),
        "single_market_dependence": _market_dependence(episodes),
        "regime_spread_miss": _regime_spread(episodes),
        "sterling_slot_miss": sterling_miss,
        "sterling_fx_missing": sterling_missing,
    }


def _fx_factor(episode: Mapping[str, Any], eurgbp: Mapping[date, float] | None) -> float | None:
    """GBP names stay put. A euro name scales by the EURGBP move from fill to exit."""
    if episode.get("market") not in {"dax", "cac40"}:
        return 1.0
    if not eurgbp or not episode.get("fill_session") or not episode.get("exit_session"):
        return None
    entry = date.fromisoformat(str(episode["fill_session"])[:10])
    exit_day = date.fromisoformat(str(episode["exit_session"])[:10])
    fx_in = tape._fx_on(eurgbp, entry)
    fx_out = tape._fx_on(eurgbp, exit_day)
    if fx_in is None or fx_out is None or fx_in <= 0:
        return None
    return fx_out / fx_in


def _sterling_flags(
    episodes: Sequence[Mapping[str, Any]], eurgbp: Mapping[date, float] | None
) -> tuple[bool, bool]:
    """``(fx_missing, slot_miss)``. A missing euro rate leaves the book uncomputed."""
    converted: list[dict[str, Any]] = []
    needs_fx = False
    for episode in episodes:
        if episode.get("column") != "primary" or not episode.get("mature"):
            continue
        local = episode.get("fair_cost_return")
        if local is None:
            continue
        if episode.get("market") in {"dax", "cac40"}:
            needs_fx = True
        factor = _fx_factor(episode, eurgbp)
        if factor is None:
            return True, False
        copy = dict(episode)
        copy["fair_cost_return"] = (1.0 + float(local)) * factor - 1.0
        basket = episode.get("basket") or {}
        gross = basket.get("basket_gross")
        if gross is not None:
            copy["basket"] = {**basket, "basket_gross": (1.0 + float(gross)) * factor - 1.0}
        converted.append(copy)
    if needs_fx and not eurgbp:
        return True, False
    if not converted:
        return False, False
    book = rehearsal.sbo._slot_book(
        converted, seed=int(REGISTRATION_CONSTANTS["SLOT_BOOK_RANDOM_SEED"])
    )
    basket_rows = []
    for episode in converted:
        gross = (episode.get("basket") or {}).get("basket_gross")
        if gross is None:
            continue
        row = dict(episode)
        row["fair_cost_return"] = gross
        basket_rows.append(row)
    basket = rehearsal.sbo._slot_book(
        basket_rows, seed=int(REGISTRATION_CONSTANTS["SLOT_BOOK_RANDOM_SEED"])
    )
    book_nav = book.get("end_nav")
    basket_nav = basket.get("end_nav")
    book_return = None if book_nav is None else float(book_nav) - 1.0
    basket_return = None if basket_nav is None else float(basket_nav) - 1.0
    miss = (
        book_return is None
        or book_return <= 0
        or basket_return is None
        or book_return <= basket_return
    )
    return False, miss


def _market_dependence(episodes: Sequence[Mapping[str, Any]]) -> bool:
    mature = [
        row
        for row in episodes
        if row.get("column") == "primary"
        and row.get("mature")
        and row.get("matched_excess") is not None
    ]
    if not mature:
        return False
    overall = rehearsal._median([float(row["matched_excess"]) for row in mature])
    if overall is None or overall <= 0:
        return False
    counts = Counter(str(row.get("market")) for row in mature)
    biggest = max(counts, key=lambda market: (counts[market], market))
    rest = [float(row["matched_excess"]) for row in mature if row.get("market") != biggest]
    rest_median = rehearsal._median(rest)
    return rest_median is not None and rest_median <= 0


def _regime_spread(episodes: Sequence[Mapping[str, Any]]) -> bool:
    minimum = int(REGISTRATION_CONSTANTS["REGIME_HALF_MIN_MATURE"])
    for regime in ("above", "below"):
        rows = [
            row
            for row in episodes
            if row.get("column") == "primary"
            and row.get("mature")
            and row.get("regime") == regime
            and row.get("matched_excess") is not None
        ]
        if len(rows) < minimum:
            return True
        median = rehearsal._median([float(row["matched_excess"]) for row in rows])
        if median is None or median < 0:
            return True
    return False


def _drawdown_breach(episodes: Sequence[Mapping[str, Any]]) -> bool:
    book = rehearsal.sbo._slot_book(
        list(episodes), seed=int(REGISTRATION_CONSTANTS["SLOT_BOOK_RANDOM_SEED"])
    )
    basket_episodes = []
    for episode in episodes:
        if episode.get("column") != "primary":
            continue
        gross = (episode.get("basket") or {}).get("basket_gross")
        if gross is None:
            continue
        copy = dict(episode)
        copy["fair_cost_return"] = gross
        basket_episodes.append(copy)
    basket = rehearsal.sbo._slot_book(
        basket_episodes, seed=int(REGISTRATION_CONSTANTS["SLOT_BOOK_RANDOM_SEED"])
    )
    book_dd = book.get("max_drawdown")
    basket_dd = basket.get("max_drawdown")
    if book_dd is None or basket_dd is None or basket_dd == 0:
        return False
    return abs(float(book_dd)) > float(REGISTRATION_CONSTANTS["DRAWDOWN_MULTIPLE"]) * abs(
        float(basket_dd)
    )


def committed_store(
    *,
    results: Mapping[str, Mapping[str, Any]] | None,
    phase: str,
    calls: Sequence[Mapping[str, Any]] | None = None,
    bias_rows: Sequence[Mapping[str, Any]] | None = None,
    overlap_excluded: int = 0,
    markets: Sequence[str] = (),
    europe_not_fetched: bool = False,
    previous: Mapping[str, Any] | None = None,
    probe: Mapping[str, Mapping[str, bool]] | None = None,
    eurgbp: Mapping[date, float] | None = None,
    holdout: bool = False,
) -> dict[str, Any]:
    """Aggregates only. The licence scan rejects prices and statement values."""
    constants = REGISTRATION_CONSTANTS
    store: dict[str, Any] = {
        "registration_id": constants["registration_id"],
        "parent_registration_id": constants["parent_registration_id"],
        "observe_only": True,
        "influences_live": False,
        "statement_basis": constants["STATEMENT_BASIS"],
        "data_quality_basis": constants["DATA_QUALITY_BASIS"],
        "sector_label_basis": constants["SECTOR_LABEL_BASIS"],
        "universe_basis": {
            market: constants["UNIVERSE_BASIS"][market]
            for market in markets
            if market in constants["UNIVERSE_BASIS"]
        },
        "markets_scored": list(markets),
        "europe_not_fetched": europe_not_fetched,
        "labels": {
            "f9_status": constants["F9_STATUS"],
            "research_verdict": constants["RESEARCH_VERDICT"],
            "memo": constants["MEMO_LABEL"],
            "adjusted_signal": constants["ADJUSTED_SIGNAL"],
            "t212_listed": constants["T212_LISTED"],
            "late_signal": constants["LATE_SIGNAL"],
            "fcf_agrees": "not_a_test",
            "provenance_missing": "not_used",
        },
        "family": {
            "m": constants["FAMILY_SIZE"],
            "coverage": constants["FAMILY_COVERAGE"],
            "tests": ["primary", "deep_dip", "revenue_growing", "trend_not_falling"],
        },
        "phase": phase,
        "status": phase,
        "development": None,
        "holdout": None,
        "reveal": None,
        "delisting_sensitivity": {"development": None, "holdout": None},
        "regime_cuts": {},
        "bias": {
            **tape.bias_shares(list(bias_rows or [])),
            "overlap_excluded": overlap_excluded,
        },
        "probe": {key: dict(probe[key]) for key in sorted(_PROBE_KEYS) if probe and key in probe},
        "month_series": [],
        "licensed_data": {"first_used_at": None, "deleted_at": None},
        "calls": list(calls or []),
        "amendments": [],
    }
    if previous:
        for key in (
            "development",
            "delisting_sensitivity",
            "regime_cuts",
            "licensed_data",
            "amendments",
            "reveal",
        ):
            if previous.get(key) is not None:
                store[key] = previous[key]
        if previous.get("licensed_data"):
            store["licensed_data"] = dict(previous["licensed_data"])
    if results:
        base = results[BASELINE]
        scoring = date.fromisoformat(str(base["scoring_date"])[:10])
        delisted = set((results[BASELINE].get("counts") or {}).get("delisted_names") or [])
        # Haircut keys are the delisted symbols. Pass them when the caller set them.
        window_name = "holdout" if holdout else "development"
        window = (
            (constants["HOLDOUT_START"], constants["HOLDOUT_END"])
            if holdout
            else (constants["DEVELOPMENT_START"], constants["DEVELOPMENT_END"])
        )
        block = _window_block(
            base["episodes"],
            base.get("events") or [],
            window,
            holdout=holdout,
            scoring=scoring,
            delisted=delisted,
        )
        sens = rehearsal.sensitivity_block(
            results[SENSITIVITY]["episodes"],
            window,
            rehearsal.family(_family_registration())[
                "coverage" if holdout else "development_coverage"
            ],
            rehearsal.family(_family_registration()),
        )
        sens_primary = sens["primary"]
        sens_verdict = rehearsal.primary_verdict(
            sens_primary.get("fair_cost_median"),
            sens_primary.get("interval") or {},
            int(sens_primary.get("mature") or 0),
        )
        sens["verdict"] = sens_verdict
        if holdout:
            verdict = rehearsal.primary_verdict(
                block["primary"].get("fair_cost_median"),
                block["primary"].get("interval") or {},
                int(block["primary"].get("mature") or 0),
            )
            flags = _dirty_flags(block, sens_verdict, base["episodes"], eurgbp=eurgbp)
            clean = verdict == "pass" and not any(flags.values())
            block["verdicts"] = {
                "primary": verdict,
                "clean_pass": clean,
                "costs_failed": (block["primary"].get("fair_cost_median") is not None)
                and block["primary"]["fair_cost_median"] <= 0,
                "bench": {
                    column: (block["bench"].get(column) or {}).get("verdict")
                    for column in ("deep_dip", "revenue_growing", "trend_not_falling")
                },
            }
            for column in ("deep_dip", "revenue_growing", "trend_not_falling"):
                bench = block["bench"].get(column) or {}
                halves = [
                    1.0
                    if item.get("sign") == "positive"
                    else -1.0
                    if item.get("sign") == "negative"
                    else None
                    for item in bench.get("halves") or []
                ]
                bench["verdict"] = rehearsal.candidate_verdict(bench, halves)
            block["flags"] = flags
            store["holdout"] = {"computed_at": _now(), **block}
            store["delisting_sensitivity"] = {
                **(store.get("delisting_sensitivity") or {}),
                "holdout": sens,
            }
            store["reveal"] = {"at": _now(), "evidence": "single_holdout_write"}
            store["status"] = "revealed"
        else:
            store["development"] = {"computed_at": _now(), **block}
            store["delisting_sensitivity"] = {
                **(store.get("delisting_sensitivity") or {}),
                "development": sens,
            }
            store["month_series"] = rehearsal.month_series(base["episodes"], window)
            store["status"] = "development_committed"
        store["phase"] = window_name
    if store["licensed_data"].get("first_used_at") is None and results:
        store["licensed_data"]["first_used_at"] = _now()
    assert_store_has_no_licensed_numbers(store)
    return store


def assert_store_has_no_licensed_numbers(
    payload: Mapping[str, Any], token: str | None = None
) -> None:
    """Raise if a price, a statement value, a per-episode row or the token is present."""

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                parent = path.rsplit(".", 1)[-1]
                interval_bound = parent == "interval" and key in {"low", "high"}
                if key in _FORBIDDEN_KEYS and key not in _PROBE_KEYS and not interval_bound:
                    raise ValueError(f"Forbidden licensed field at {path}.{key}")
                if key not in _PROBE_KEYS and key not in {
                    "probe",
                    "in_universe",
                    "had_exit",
                    "statement_every_year",
                    "price_ended_before_known_event",
                }:
                    if isinstance(value, float) and abs(value) >= 1000:
                        raise ValueError(f"Licensed-looking number at {path}.{key}")
                if isinstance(value, str) and token and token in value:
                    raise ValueError(f"API token at {path}.{key}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                if isinstance(value, dict) and (
                    "exit_fill" in value or "adjusted_close" in value or "close" in value
                ):
                    raise ValueError(f"Per-episode licensed row at {path}[{index}]")
                walk(value, f"{path}[{index}]")

    walk(payload, "root")


def write_store(payload: Mapping[str, Any], repo_root: Path = REPO_ROOT) -> Path:
    assert_store_has_no_licensed_numbers(payload)
    path = Path(repo_root) / STORE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def delete_licensed_cache(cache: Path) -> None:
    """Remove prices and statements. Call totals already sit in the aggregate store.

    Only after the reveal: development leaves them for the holdout walk.
    """
    _remove_tree(cache / "raw")
    _remove_tree(cache / "fx")


def wipe_cache(cache: Path) -> None:
    """Drop the resume cache after the owner confirms deletion."""
    _remove_tree(cache / "raw")
    _remove_tree(cache / "fx")
    _remove_tree(cache / "lists")
    cursor = cache / "cursor.json"
    if cursor.exists():
        cursor.unlink()


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    if path.is_dir():
        path.rmdir()
    elif path.exists():
        path.unlink()


def develop(
    *,
    repo_root: Path = REPO_ROOT,
    records: Sequence[Mapping[str, Any]] | None = None,
    eurgbp: Mapping[date, float] | None = None,
    usdgbp: Mapping[date, float] | None = None,
    ch_store: Mapping[str, Any] | None = None,
    calls: Sequence[Mapping[str, Any]] | None = None,
    client: EodhdClient | None = None,
    cache: Path | None = None,
    score: bool = True,
) -> dict[str, Any]:
    """Walk development signal sessions and commit that block. Holdout stays null."""
    previous = _read_store(repo_root)
    if previous and previous.get("reveal"):
        raise ReplayRefused("The holdout is already revealed. Development is not rewritten.")
    if previous and previous.get("development") and not previous.get("reveal"):
        raise ReplayRefused(
            "Development is already committed. A second pass is an amendment, not a silent rewrite."
        )
    if records is None:
        require_sealed(repo_root)
        if client is None:
            raise ReplayRefused("develop needs a sealed registration and an EODHD client.")
        cache = Path(cache) if cache is not None else default_cache_dir()
        summary = run_fetch(client, repo_root=repo_root, cache=cache)
        if summary["status"] != "complete":
            payload = committed_store(
                results=None,
                phase="fetch",
                calls=summary["calls"],
                europe_not_fetched=summary["europe_not_fetched"],
                previous=previous,
            )
            payload["status"] = "partial"
            write_store(payload, repo_root)
            return payload
        records = _records_from_cache(cache)
        calls = summary["calls"]
        eurgbp, usdgbp = _resolved_fx(eurgbp, usdgbp, cache)
    else:
        records = [_slim_record(record) for record in records]
        eurgbp, usdgbp = _resolved_fx(eurgbp, usdgbp, None)
    if not records:
        raise ReplayRefused("No cached EODHD records to walk. Re-run fetch before develop.")
    assembled = assemble_specs(
        records,
        eurgbp=eurgbp,
        usdgbp=usdgbp,
        ch_store=ch_store if ch_store is not None else _load_ch(repo_root),
        score=score,
    )
    if score:
        apply_sector_frame(assembled["specs"], assembled["prepared"])
    results = walk_variants(
        assembled["specs"],
        assembled["haircuts"],
        last_signal=str(REGISTRATION_CONSTANTS["DEVELOPMENT_END"]),
    )
    _attach_delisted(results, assembled["haircuts"])
    store = committed_store(
        results=results,
        phase="development",
        calls=calls,
        bias_rows=assembled["bias_rows"],
        overlap_excluded=assembled["overlap_excluded"],
        markets=assembled["markets"],
        previous=previous,
        probe=_probe_flags(
            records,
            results[BASELINE]["episodes"],
            ranked=assembled["ranked_symbols"],
            prepared=assembled["prepared"],
        ),
        eurgbp=eurgbp,
        holdout=False,
    )
    write_store(store, repo_root)
    return store


def reveal(
    *,
    repo_root: Path = REPO_ROOT,
    records: Sequence[Mapping[str, Any]] | None = None,
    eurgbp: Mapping[date, float] | None = None,
    usdgbp: Mapping[date, float] | None = None,
    client: EodhdClient | None = None,
    cache: Path | None = None,
    score: bool = True,
) -> dict[str, Any]:
    """One holdout write. Refuses without a committed development block and an owner stamp."""
    store = _read_store(repo_root)
    if not store or not store.get("development"):
        raise RevealRefused(
            "No development result is committed. Run development and read it before the reveal."
        )
    if store.get("reveal"):
        raise RevealRefused("The holdout was already revealed. There is one reveal.")
    registration = load_registration(repo_root)
    stamp = registration.get("reveal_stamp")
    if not isinstance(stamp, dict) or not stamp.get("at") or not stamp.get("by"):
        raise RevealRefused(
            "No owner reveal stamp. Run `ftse-strategy-book-uk-replay stamp-reveal --owner <name>`."
        )
    if records is None:
        require_sealed(repo_root)
        if client is None:
            raise RevealRefused("The reveal fetch needs an EODHD client.")
        cache = Path(cache) if cache is not None else default_cache_dir()
        summary = run_fetch(client, repo_root=repo_root, cache=cache)
        if summary["status"] != "complete":
            raise RevealRefused("The reveal fetch is partial. Resume it before the holdout write.")
        records = _records_from_cache(cache)
        eurgbp, usdgbp = _resolved_fx(eurgbp, usdgbp, cache)
    else:
        records = [_slim_record(record) for record in records]
        eurgbp, usdgbp = _resolved_fx(eurgbp, usdgbp, None)
    if not records:
        raise RevealRefused("No cached EODHD records to walk. The holdout is not written.")
    assembled = assemble_specs(
        records,
        eurgbp=eurgbp,
        usdgbp=usdgbp,
        ch_store=_load_ch(repo_root),
        score=score,
    )
    if score:
        apply_sector_frame(assembled["specs"], assembled["prepared"])
    results = walk_variants(
        assembled["specs"],
        assembled["haircuts"],
        last_signal=str(REGISTRATION_CONSTANTS["HOLDOUT_END"]),
    )
    _attach_delisted(results, assembled["haircuts"])
    updated = committed_store(
        results=results,
        phase="holdout",
        calls=store.get("calls"),
        bias_rows=assembled["bias_rows"],
        overlap_excluded=assembled["overlap_excluded"],
        markets=assembled["markets"],
        previous=store,
        probe=_probe_flags(
            records,
            results[BASELINE]["episodes"],
            ranked=assembled["ranked_symbols"],
            prepared=assembled["prepared"],
        ),
        eurgbp=eurgbp,
        holdout=True,
    )
    write_store(updated, repo_root)
    if cache is not None:
        delete_licensed_cache(cache)
    return updated


def _attach_delisted(results: dict[str, dict[str, Any]], haircuts: Mapping[str, Any]) -> None:
    for result in results.values():
        counts = dict(result.get("counts") or {})
        counts["delisted_names"] = sorted(haircuts)
        result["counts"] = counts


def _prepared_view(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Sector-pass rows from record-level Companies House filings only.

    ``develop`` and ``reveal`` pass ``assemble_specs(...)["prepared"]`` instead,
    which also carries filings matched from the Companies House store.
    """
    view = []
    for record in records:
        slim = _slim_record(record)
        general = slim["general"]
        view.append(
            {
                "symbol": slim.get("symbol"),
                "sector": slim.get("sector") or general.get("Sector") or general.get("GicSector"),
                "annual": tape.merge_statement_years(
                    slim["eodhd_annual"], tape.ch_statements(slim.get("ch_filings") or [])
                ),
                "quarterly": slim["quarterly"],
                "interim": slim["interim"],
            }
        )
    return view


def _probe_flags(
    records: Sequence[Mapping[str, Any]],
    episodes: Sequence[Mapping[str, Any]],
    *,
    ranked: set[str] | None = None,
    prepared: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, bool]]:
    """``prepared`` supplies the Companies House key and filings matched from the store."""
    exits = {
        str(row.get("ticker"))
        for row in episodes
        if row.get("column") == "primary" and row.get("exit_reason")
    }
    resolved = {str(row["symbol"]): row for row in prepared or ()}
    slims = [_slim_record(record) for record in records]
    out = {}
    for spec in REGISTRATION_CONSTANTS["PROBE_CLASSES"]:
        key = spec["key"]
        matched = [
            row
            for row in slims
            if (resolved.get(str(row.get("symbol"))) or row).get("ch_key") == key
            or tape.match_ch_key(str(row.get("name") or "")) == key
        ]
        last = None
        if matched:
            bars = matched[0]["bars"]
            last = bars.dates[-1] if len(bars) else None
        known = date.fromisoformat(spec["known_end"])
        first = resolved.get(str(matched[0].get("symbol"))) if matched else None
        out[key] = {
            "in_universe": any(str(row.get("symbol")) in (ranked or set()) for row in matched),
            "had_exit": any(str(row.get("symbol")) in exits for row in matched),
            "statement_every_year": _every_year(first or matched[0], known) if matched else False,
            "price_ended_before_known_event": tape.price_ended_before_known_event(last, known),
        }
    return out


def _every_year(row: Mapping[str, Any], known_end: date) -> bool:
    """``row`` is a prepared row (merged statements) or a slim record."""
    annual = row.get("annual")
    if annual is None:
        annual = tape.merge_statement_years(
            row.get("eodhd_annual") or [], tape.ch_statements(row.get("ch_filings") or [])
        )
    years = {int(item["year"]) for item in annual}
    return all(year in years for year in range(2013, known_end.year + 1))


def _load_ch(repo_root: Path) -> dict[str, Any]:
    path = Path(repo_root) / "docs/data/ch_failed_name_statements.json"
    if not path.exists():
        return {"names": []}
    return load_store(path)


def _records_from_cache(cache: Path) -> list[dict[str, Any]]:
    records = []
    raw = cache / "raw"
    if not raw.exists():
        return records
    lists = {}
    for path in (cache / "lists").glob("*.json") if (cache / "lists").exists() else []:
        lists[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    meta: dict[str, dict[str, Any]] = {}
    for key, rows in lists.items():
        exchange, _, kind = key.partition(":")
        market = REGISTRATION_CONSTANTS["EXCHANGES"].get(exchange, {}).get("market")
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            symbol = _symbol_code(row, exchange)
            meta[symbol] = {
                "market": market,
                "delisted": kind == "delisted",
                "name": row.get("Name"),
                "currency": row.get("Currency"),
                "isin": row.get("Isin") or row.get("ISIN"),
            }
    for symbol_dir in sorted(path for path in raw.iterdir() if path.is_dir()):
        symbol = symbol_dir.name
        info = meta.get(symbol, {})

        def _read(kind: str, symbol_dir: Path = symbol_dir) -> Any:
            path = symbol_dir / f"{kind}.json"
            if not path.exists():
                return [] if kind != "fundamentals" else {}
            return json.loads(path.read_text(encoding="utf-8"))

        # One symbol's raw JSON at a time: the full cache does not fit in memory.
        records.append(
            _slim_record(
                {
                    "symbol": symbol,
                    "market": info.get("market"),
                    "name": info.get("name"),
                    "currency": info.get("currency"),
                    "delisted": info.get("delisted", False),
                    "isin": info.get("isin"),
                    "eod": _read("eod"),
                    "fundamentals": _read("fundamentals") or {},
                    "dividends": _read("dividends") or [],
                    "splits": _read("splits") or [],
                }
            )
        )
    return records


def confirm_deleted(repo_root: Path = REPO_ROOT, cache: Path | None = None) -> dict[str, Any]:
    store = _read_store(repo_root)
    if store is None:
        raise ReplayRefused(f"{STORE_PATH} is missing.")
    if cache is not None:
        wipe_cache(cache)
    licensed = dict(store.get("licensed_data") or {})
    licensed["deleted_at"] = _now()
    store["licensed_data"] = licensed
    write_store(store, repo_root)
    return store


def findings(repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    """Info with phase and verdict. Warn when the store is unreadable. Nothing when absent."""
    path = Path(repo_root) / STORE_PATH
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [
            {
                "severity": "warn",
                "title": TITLE_FAILED,
                "summary": f"{STORE_PATH} is not valid JSON.",
            }
        ]
    if not isinstance(payload, dict):
        return [
            {
                "severity": "warn",
                "title": TITLE_FAILED,
                "summary": f"{STORE_PATH} is not an object.",
            }
        ]
    phase = str(payload.get("phase") or payload.get("status") or "unknown")
    verdicts = (
        ((payload.get("holdout") or {}).get("verdicts") or {}) if payload.get("holdout") else {}
    )
    verdict = verdicts.get("primary") or "not_revealed"
    return [
        {
            "severity": "info",
            "title": TITLE,
            "summary": (
                f"Phase {phase}. Verdict {verdict}. "
                f"Markets {', '.join(payload.get('markets_scored') or []) or 'none'}. "
                f"See {RUNBOOK_PATH}."
            ),
        }
    ]


def fetch_plan() -> dict[str, Any]:
    """The LSE plan from the measured list size. No EODHD call."""
    plan = tape.lse_fetch_plan()
    plan["europe_name_cap"] = tape.europe_name_cap()
    plan["note"] = (
        "XETRA and PA add four list calls, 13 weighted calls per name and two FX calls. "
        "Names above the one-day cap resume the next UTC day. "
        "A fetch unfinished after the Europe deadline is europe_not_fetched."
    )
    return plan


# --- CLI -------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ftse-strategy-book-uk-replay",
        description="UK/Europe strategy-book replay. Refuses EODHD until the registration is sealed.",
    )
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="Print the fetch plan. Does not call EODHD.")
    seal_p = sub.add_parser("seal", help="Stamp the registration. Does not call EODHD.")
    seal_p.add_argument("--owner", required=True)
    stamp_p = sub.add_parser("stamp-reveal", help="Authorise the single holdout write.")
    stamp_p.add_argument("--owner", required=True)
    fetch_p = sub.add_parser("fetch", help="Fill the gitignored cache under the soft cap.")
    fetch_p.add_argument("--cache", type=Path)
    fetch_p.add_argument(
        "--max-minutes",
        type=float,
        default=None,
        help=f"Stop cleanly after this many minutes (default ${FETCH_MAX_MINUTES_ENV}, else none).",
    )
    dev_p = sub.add_parser("develop", help="Development walk. Commits aggregates only.")
    dev_p.add_argument("--cache", type=Path)
    rev_p = sub.add_parser("reveal", help="The single holdout write.")
    rev_p.add_argument("--cache", type=Path)
    sub.add_parser("status", help="Print the aggregate store status.")
    del_p = sub.add_parser("confirm-deleted", help="Stamp licensed_data.deleted_at.")
    del_p.add_argument("--cache", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            print(json.dumps(fetch_plan(), indent=2))
            return 0
        if args.command == "seal":
            print(
                json.dumps({"sealed": seal_registration(args.owner, args.repo)["sealed"]}, indent=2)
            )
            return 0
        if args.command == "stamp-reveal":
            print(json.dumps(stamp_reveal(args.owner, args.repo)["reveal_stamp"], indent=2))
            return 0
        if args.command == "status":
            print(json.dumps(findings(args.repo), indent=2))
            return 0
        if args.command == "confirm-deleted":
            confirm_deleted(args.repo, args.cache)
            return 0
        token = os.environ.get("EODHD_API_TOKEN") or ""
        if args.command in {"fetch", "develop", "reveal"} and not token:
            print("EODHD_API_TOKEN is not set. Nothing was called and nothing was committed.")
            return 0
        client = EodhdClient(token, max_calls=int(REGISTRATION_CONSTANTS["DAILY_CALL_LIMIT"]))
        if args.command == "fetch":
            max_minutes = args.max_minutes
            if max_minutes is None and os.environ.get(FETCH_MAX_MINUTES_ENV):
                max_minutes = float(os.environ[FETCH_MAX_MINUTES_ENV])
            summary = run_fetch(
                client, repo_root=args.repo, cache=args.cache, max_minutes=max_minutes
            )
            previous = _read_store(args.repo)
            payload = committed_store(
                results=None,
                phase="fetch",
                calls=summary["calls"],
                europe_not_fetched=summary["europe_not_fetched"],
                previous=previous,
            )
            payload["status"] = summary["status"]
            write_store(payload, args.repo)
            print(
                json.dumps(
                    {
                        "status": summary["status"],
                        "stopped_by": summary["stopped_by"],
                        "weighted": summary["weighted"],
                        "done_symbols": summary["done_symbols"],
                    }
                )
            )
            return 0
        if args.command == "develop":
            develop(repo_root=args.repo, client=client, cache=args.cache)
            return 0
        reveal(repo_root=args.repo, client=client, cache=args.cache)
        return 0
    except ReplayRefused as exc:
        print(redact_token(str(exc), os.environ.get("EODHD_API_TOKEN")), flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
