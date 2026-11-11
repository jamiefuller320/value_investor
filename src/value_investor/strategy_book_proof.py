"""Observe-only proof board for plan step 3.2.

Scores the seven bars the owner signed on 2026-11-05. The wording of those
bars is read from ``step_3_2_proof_numbers`` in the strategy-book registration.
The numbers inside that wording are prose, so the thresholds below are named
constants checked against that prose before a pass is allowed.

This module reads the forward observe store and the archive replay. It writes
only ``docs/data/strategy_book_proof_board.json``. It does not change the
observe store, any sealed board, the thickness gate, or the registration.

Meeting every bar lets the owner consider plan step 5.5. It opens nothing.
``influences_live`` is false.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.fx import currency_for_ticker
from value_investor.strategy_book_observe import _slot_book, entry_week
from value_investor.strategy_book_rules import (
    COLUMN_PRIMARY,
    INFLUENCES_LIVE,
    OBSERVE_STORE_NAME,
    REGISTRATION_ID,
    REGISTRATION_STORE_NAME,
    REPLAY_DETAIL_STORE_NAME,
    SLOT_BOOK_RANDOM_SEED,
    SLOT_COUNT,
)

PROOF_STORE_NAME = "strategy_book_proof_board.json"
PLAN_RELATIVE = Path("docs/ops/strategy-reorientation-plan.md")
SECTION_START = "#### Step 3.2 proof numbers"
SECTION_END = "### Phase 4"
# Step 2.2 archive replay (the first score store). Not the lookahead arm.
ARCHIVE_ARM = "archive_buy_tier_only"
MACRO_RELATIVE = Path("docs/data/library/macro")

# Dated macro snapshots quote these as USD per 1 unit of the currency.
# Same markers as macro_context.DOMAIN_SERIES and ftse_pound_cap._fx_usd_per_unit.
# The seal does not list currencies. CHF, SEK, HKD and SGD have no daily series here.
FX_MARKERS: dict[str, tuple[str, str]] = {
    "GBP": ("uk", "gbp_usd"),
    "EUR": ("euro", "eur_usd"),
    "AUD": ("au", "aud_usd"),
    "CAD": ("ca", "cad_usd"),
}

# Prose in docs/data/strategy_book_registration.json → step_3_2_proof_numbers.
# requirement "Uncertainty": "10,000 resamples" of the "90% interval".
UNCERTAINTY_DRAWS = 10_000
UNCERTAINTY_LEVEL = 0.90
# The seal prose does not name a seed. 20261105 is the signature date of the bars.
BOOTSTRAP_SEED = 20261105
# requirement "Tail loss": "5th-percentile" "no worse than −20%".
TAIL_PERCENTILE = 5.0
TAIL_FLOOR = -0.20
# requirement "Drawdown": "no more than 1.5 times".
DRAWDOWN_MULTIPLE = 1.5
# requirement "Regime spread": "at least 12 counted mature episodes".
REGIME_MIN = 12
# requirement "Sterling slot book": "20-slot". Also strategy_book_rules.SLOT_COUNT.
SLOT_BOOK_SLOTS = 20

PROOF_STALE_AFTER = timedelta(days=5)

TITLE_INFO = "Strategy book proof board"
TITLE_MISSING = "Strategy book proof board missing"
TITLE_UNREADABLE = "Strategy book proof board unreadable"
TITLE_STALE = "Strategy book proof board stale"

OWNER_NOTE = (
    "Meeting every bar lets the owner consider step 5.5. It does not open live capital by itself."
)
BAR_ORDER = (
    "uncertainty",
    "tail_loss",
    "drawdown",
    "market_spread",
    "regime_spread",
    "sterling_slot_book",
    "tradable_subset",
)
SEAL_REQUIREMENT = {
    "uncertainty": "Uncertainty",
    "tail_loss": "Tail loss",
    "drawdown": "Drawdown",
    "market_spread": "Market spread",
    "regime_spread": "Regime spread",
    "sterling_slot_book": "Sterling slot book",
    "tradable_subset": "Tradable subset",
}
# Phrases that must appear in the sealed bar text before the constants are used.
SEAL_PHRASES: dict[str, tuple[str, ...]] = {
    "Uncertainty": ("10,000", "90%"),
    "Tail loss": ("5th-percentile", "20%"),
    "Drawdown": ("1.5",),
    "Market spread": ("above zero",),
    "Regime spread": ("12", "regime_unknown"),
    "Sterling slot book": ("20-slot", "positive"),
    "Tradable subset": ("t212_listed", "above zero"),
}

SAME_DATES = (
    "The reference slot book and the matched basket are both "
    "strategy_book_observe._slot_book on the same counted episodes, the same "
    "fill sessions and the same exit sessions. The slot book earns each "
    "episode's fair_cost_return after conversion into sterling. The basket "
    "earns that episode's basket_gross (equal-weight buy-tier price return "
    "from fill to exit) converted with the same two rates. Net asset value is "
    "marked on the union of those fill and exit dates. Total return is end "
    "net asset value minus 1, from a start of 1.0 in cash. The peak-to-trough "
    "fall is the absolute value of max_drawdown (nav/peak - 1 on those event "
    "dates, with each open position marked at its full holding return from the "
    "fill). The reference order is fill date then ticker. The 15 random orders "
    "inside _slot_book are not part of either bar."
)


def proof_store_path(repo_root: Path) -> Path:
    return Path(repo_root) / "docs" / "data" / PROOF_STORE_NAME


def sealed_section_text(plan: str) -> str | None:
    """Plan text from the step 3.2 heading up to, not including, Phase 4."""
    start = plan.find(SECTION_START)
    if start < 0:
        return None
    end = plan.find(SECTION_END, start)
    if end < 0:
        return None
    return plan[start:end]


def sealed_section_sha256(plan: str) -> str | None:
    text = sealed_section_text(plan)
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def linear_percentile(values: list[float], pct: float) -> float | None:
    """Linear percentile. ``pct`` is 0–100. Rank is ``(pct/100) * (n - 1)``.

    This is the same rank rule as NumPy's linear percentile. One value returns
    that value. An empty list returns None.
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    weight = rank - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    return None


def _day(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class FxHistory:
    """Point-in-time USD-per-unit rates from committed macro snapshots.

    A lookup for day D uses the latest marker whose ``as_of`` date is on or
    before D. The snapshot file name is the day the rate was fetched, not the
    rate's date. A later file never supplies a rate for an earlier day.
    Live Yahoo spots (``fx.fetch_fx_rates``) are not used.
    """

    def __init__(
        self,
        usd_per_unit: dict[str, list[tuple[date, float]]],
        *,
        source: str = "in-memory",
        files_read: int = 0,
        unreadable: int = 0,
    ) -> None:
        self.usd_per_unit = {
            currency: sorted(rows, key=lambda item: item[0])
            for currency, rows in usd_per_unit.items()
        }
        self.source = source
        self.files_read = files_read
        self.unreadable = unreadable

    @classmethod
    def load(cls, repo_root: Path) -> FxHistory:
        directory = Path(repo_root) / MACRO_RELATIVE
        # First file that records an as_of wins, so a later restatement of the
        # same quote date is not treated as known on that date.
        chosen: dict[tuple[str, date], float] = {}
        files_read = 0
        unreadable = 0
        if directory.is_dir():
            paths = sorted(
                path
                for path in directory.glob("*.json")
                if len(path.name) == 15 and path.name[4] == "-" and path.name[7] == "-"
            )
            for path in paths:
                try:
                    payload = _read_json(path)
                except (OSError, ValueError, TypeError):
                    unreadable += 1
                    continue
                if not isinstance(payload, dict):
                    unreadable += 1
                    continue
                files_read += 1
                domains = payload.get("domains")
                if not isinstance(domains, dict):
                    continue
                for currency, (domain, marker_key) in FX_MARKERS.items():
                    block = domains.get(domain)
                    if not isinstance(block, dict):
                        continue
                    markers = block.get("markers")
                    if not isinstance(markers, dict):
                        continue
                    marker = markers.get(marker_key)
                    if not isinstance(marker, dict):
                        continue
                    quote_day = _day(marker.get("as_of"))
                    rate = _as_float(marker.get("value"))
                    if quote_day is None or rate is None or rate <= 0:
                        continue
                    chosen.setdefault((currency, quote_day), rate)
        series: dict[str, list[tuple[date, float]]] = {key: [] for key in FX_MARKERS}
        for (currency, quote_day), rate in chosen.items():
            series[currency].append((quote_day, rate))
        return cls(
            series,
            source=str(MACRO_RELATIVE / "YYYY-MM-DD.json"),
            files_read=files_read,
            unreadable=unreadable,
        )

    def _latest(self, currency: str, day: date) -> tuple[date, float] | None:
        rows = self.usd_per_unit.get(currency) or []
        if not rows:
            return None
        dates = [item[0] for item in rows]
        # bisect without importing a second time: last date <= day.
        lo = 0
        hi = len(dates)
        while lo < hi:
            mid = (lo + hi) // 2
            if dates[mid] <= day:
                lo = mid + 1
            else:
                hi = mid
        if lo == 0:
            return None
        return rows[lo - 1]

    def gbp_per_unit(self, currency: str, day: date) -> tuple[float | None, str]:
        """Sterling per 1 unit of ``currency`` on or before ``day``.

        GBP is 1. A missing series is a cited gap, not a guessed rate.
        """
        code = (currency or "").strip().upper()
        if code in {"GBP", "GBX"}:
            # A pence quote and a pound quote are the same currency once the
            # figure is a return. No rate is applied.
            return 1.0, ""
        if code == "USD":
            sterling = self._latest("GBP", day)
            if sterling is None:
                return None, f"no committed GBPUSD rate on or before {day.isoformat()}"
            return 1.0 / sterling[1], ""
        if code not in FX_MARKERS:
            return None, (
                f"no committed daily FX history for {code or 'unknown currency'} "
                "(dated macro snapshots price GBP, EUR, AUD and CAD against USD)"
            )
        foreign = self._latest(code, day)
        sterling = self._latest("GBP", day)
        if foreign is None:
            return None, f"no committed {code}USD rate on or before {day.isoformat()}"
        if sterling is None:
            return None, f"no committed GBPUSD rate on or before {day.isoformat()}"
        return foreign[1] / sterling[1], ""

    def to_meta(self) -> dict[str, Any]:
        spans: dict[str, dict[str, str]] = {}
        for currency, rows in self.usd_per_unit.items():
            if not rows:
                continue
            spans[currency] = {
                "first_as_of": rows[0][0].isoformat(),
                "last_as_of": rows[-1][0].isoformat(),
                "points": len(rows),
            }
        return {
            "source": self.source,
            "point_in_time": (
                "Each rate's date is the marker as_of, not the snapshot file name "
                "and not a live spot. The converter uses the latest as_of on or "
                "before the episode date. fetch_fx_rates is not called."
            ),
            "usd_per_unit_markers": {
                currency: f"{domain}.{key}" for currency, (domain, key) in FX_MARKERS.items()
            },
            "sterling_per_unit": "usd_per_currency / usd_per_gbp; USD is 1 / usd_per_gbp",
            "spans": spans,
            "files_read": self.files_read,
            "unreadable_files": self.unreadable,
            "no_daily_series": ["CHF", "SEK", "HKD", "SGD"],
        }


def _seal_rows(registration: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(registration, dict):
        return []
    rows = registration.get("step_3_2_proof_numbers")
    if not isinstance(rows, list):
        return []
    copied: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        requirement = row.get("requirement")
        bar = row.get("bar")
        if isinstance(requirement, str) and isinstance(bar, str):
            copied.append({"requirement": requirement, "bar": bar})
    return copied


def seal_phrase_problems(rows: list[dict[str, str]]) -> list[str]:
    """The constants match the sealed prose only when these phrases are present."""
    by_requirement = {row["requirement"]: row["bar"] for row in rows}
    problems: list[str] = []
    for requirement, phrases in SEAL_PHRASES.items():
        text = by_requirement.get(requirement)
        if text is None:
            problems.append(f"seal step_3_2_proof_numbers has no {requirement!r} bar")
            continue
        for phrase in phrases:
            if phrase not in text:
                problems.append(f"seal bar {requirement!r} does not contain {phrase!r}")
    return problems


def _expected_section_hash(registration: dict[str, Any] | None) -> str | None:
    if not isinstance(registration, dict):
        return None
    sealed = registration.get("sealed_documents")
    if not isinstance(sealed, dict):
        return None
    plan = sealed.get(str(PLAN_RELATIVE))
    if not isinstance(plan, dict):
        return None
    value = plan.get("section_sha256")
    return value if isinstance(value, str) and value else None


def counted_episodes(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Mature primary episodes, with provenance_missing and pending fills out.

    The per-week cap of the thickness gate is not applied. Step 3.2 says that
    gate is not this standard.
    """
    mature = [
        episode
        for episode in episodes
        if episode.get("column") == COLUMN_PRIMARY and episode.get("mature")
    ]
    provenance = [episode for episode in mature if episode.get("provenance_missing")]
    pending = [
        episode
        for episode in mature
        if not episode.get("provenance_missing") and episode.get("status") == "pending_fill"
    ]
    counted = [
        episode
        for episode in mature
        if not episode.get("provenance_missing") and episode.get("status") != "pending_fill"
    ]
    return {
        "counted": counted,
        "provenance_missing_excluded": len(provenance),
        "pending_fill_excluded": len(pending),
    }


def biggest_market(episodes: list[dict[str, Any]]) -> str | None:
    """Market with the most episodes. A tie goes to the later market name.

    Same ordering as ``strategy_book_observe._single_market_dependence``.
    """
    counts: Counter[str] = Counter(str(episode.get("market") or "") for episode in episodes)
    if not counts:
        return None
    return max(counts, key=lambda market: (counts[market], market))


def _entry_weeks(episodes: list[dict[str, Any]]) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for episode in episodes:
        value = _as_float(episode.get("matched_excess"))
        if value is None:
            continue
        token = episode.get("entry_week")
        if not token:
            filled = _day(episode.get("fill_session"))
            token = entry_week(filled) if filled else None
        if not token:
            continue
        grouped[str(token)].append(value)
    return grouped


def block_bootstrap_medians(
    weeks: dict[str, list[float]],
    *,
    draws: int,
    seed: int,
) -> list[float]:
    """Median matched excess of each resample of whole ISO entry weeks.

    Each draw picks as many weeks as the sample has, with replacement, and
    keeps every excess in a drawn week (a week drawn twice is included twice).
    ``random.Random(seed)`` is local. Week order is sorted so the sequence
    does not depend on dict order.
    """
    keys = sorted(weeks)
    blocks = [weeks[key] for key in keys]
    if not blocks or draws < 1:
        return []
    rng = random.Random(seed)
    n_blocks = len(blocks)
    medians: list[float] = []
    for _ in range(draws):
        pooled: list[float] = []
        for _pick in range(n_blocks):
            pooled.extend(blocks[rng.randrange(n_blocks)])
        medians.append(float(statistics.median(pooled)))
    return medians


def _bar(
    *,
    verdict: str,
    n: int,
    statistic: Any,
    threshold: Any,
    reasons: list[str],
    bar_text: str | None,
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "n": n,
        "statistic": statistic,
        "threshold": threshold,
        "reasons": reasons,
        "seal_bar": bar_text,
    }


def _texts(bar_text: dict[str, str] | None) -> dict[str, str | None]:
    rows = bar_text or {}
    return {key: rows.get(SEAL_REQUIREMENT[key]) for key in BAR_ORDER}


def episode_currency(episode: dict[str, Any]) -> str:
    raw = episode.get("currency")
    if isinstance(raw, str) and raw.strip():
        code = raw.strip().upper()
        if code in {"GBP", "GBX"}:
            return "GBP"
        return code
    return currency_for_ticker(
        str(episode.get("ticker") or ""),
        market=str(episode.get("market") or "") or None,
    )


def sterling_return(
    local_return: float,
    currency: str,
    entry: date,
    exit_day: date,
    fx: FxHistory,
) -> tuple[float | None, str]:
    """(1 + local return) times the sterling FX ratio, minus 1.

    The ratio is sterling-per-unit on the exit date divided by sterling-per-unit
    on the fill date. Both rates are point-in-time. GBP stays the local return.
    """
    entry_rate, entry_reason = fx.gbp_per_unit(currency, entry)
    exit_rate, exit_reason = fx.gbp_per_unit(currency, exit_day)
    if entry_rate is None or exit_rate is None or entry_rate <= 0:
        return None, entry_reason or exit_reason or "missing point-in-time FX rate"
    return (1.0 + local_return) * (exit_rate / entry_rate) - 1.0, ""


def _fair_cost(episode: dict[str, Any]) -> float | None:
    """Fair-cost episode return: the observe board's decision_return_floor.

    ``fair_cost_return`` is the fallback when that field is absent. The slot
    book itself still reads ``fair_cost_return``, which is what ``_slot_book``
    already uses.
    """
    decided = _as_float(episode.get("decision_return_floor"))
    if decided is not None:
        return decided
    return _as_float(episode.get("fair_cost_return"))


def _exit_day(episode: dict[str, Any], scoring: date | None) -> date | None:
    closed = _day(episode.get("exit_session"))
    if closed is not None:
        return closed
    return scoring


def _slot_row(episode: dict[str, Any], ret: float) -> dict[str, Any]:
    return {
        "column": episode.get("column"),
        "fill_session": episode.get("fill_session"),
        "exit_session": episode.get("exit_session"),
        "fair_cost_return": ret,
        "episode_id": episode.get("episode_id"),
        "ticker": str(episode.get("ticker") or ""),
    }


def _fall(slot: dict[str, Any]) -> float | None:
    drawdown = _as_float(slot.get("max_drawdown"))
    if drawdown is None:
        return None
    return -drawdown


def _total_return(slot: dict[str, Any]) -> float | None:
    end_nav = _as_float(slot.get("end_nav"))
    if end_nav is None:
        return None
    return end_nav - 1.0


def _prepare_sterling(
    counted: list[dict[str, Any]],
    fx: FxHistory,
    scoring: date | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], int]:
    """Slot-book rows in sterling, or reasons the bar cannot be scored.

    The matched basket is the registration's (section 8): the entry run's raw
    buy tier, or the whole screen when that tier has fewer than 5 names. The
    last value counts the whole-screen fallbacks.
    """
    slot_rows: list[dict[str, Any]] = []
    basket_rows: list[dict[str, Any]] = []
    problems: list[str] = []
    fx_gaps: Counter[str] = Counter()
    fallback = 0
    missing_basket = 0
    missing_return = 0
    missing_dates = 0
    for episode in counted:
        local = _as_float(episode.get("fair_cost_return"))
        filled = _day(episode.get("fill_session"))
        exited = _exit_day(episode, scoring)
        if local is None:
            missing_return += 1
            continue
        if filled is None or exited is None:
            missing_dates += 1
            continue
        if exited < filled:
            missing_dates += 1
            continue
        currency = episode_currency(episode)
        converted, reason = sterling_return(local, currency, filled, exited, fx)
        if converted is None:
            fx_gaps[reason] += 1
            continue
        basket = episode.get("basket") if isinstance(episode.get("basket"), dict) else {}
        gross = _as_float(basket.get("basket_gross"))
        if basket.get("fallback") or basket.get("source") not in (None, "buy_tier"):
            fallback += 1
        if gross is None:
            missing_basket += 1
        basket_converted: float | None = None
        if gross is not None:
            basket_converted, basket_reason = sterling_return(gross, currency, filled, exited, fx)
            if basket_converted is None:
                fx_gaps[basket_reason or reason] += 1
        slot_rows.append(_slot_row(episode, converted))
        if basket_converted is not None:
            basket_rows.append(_slot_row(episode, basket_converted))
    if missing_return:
        problems.append(f"{missing_return} counted episodes have no fair_cost_return")
    if missing_dates:
        problems.append(
            f"{missing_dates} counted episodes have no fill date, or no exit date "
            "and no scoring date, for a point-in-time FX conversion"
        )
    for reason, count in sorted(fx_gaps.items()):
        problems.append(f"{count} counted episodes: {reason}")
    if missing_basket:
        problems.append(f"{missing_basket} counted episodes have no basket_gross")
    if problems:
        return [], [], problems, fallback
    if len(basket_rows) != len(slot_rows):
        return (
            [],
            [],
            ["matched buy-tier basket in sterling is missing for a counted episode"],
            fallback,
        )
    return slot_rows, basket_rows, [], fallback


def evaluate_population(
    episodes: list[dict[str, Any]],
    *,
    fx: FxHistory,
    scoring_date: date | None = None,
    label: str = "forward",
    survivorship_biased: bool = False,
    not_proof: bool = False,
    bar_text: dict[str, str] | None = None,
    bootstrap_draws: int | None = None,
    bootstrap_seed: int | None = None,
) -> dict[str, Any]:
    """Score the seven bars. Does not write and does not mutate ``episodes``."""
    draws = UNCERTAINTY_DRAWS if bootstrap_draws is None else bootstrap_draws
    seed = BOOTSTRAP_SEED if bootstrap_seed is None else bootstrap_seed
    texts = _texts(bar_text)
    split = counted_episodes(episodes)
    counted: list[dict[str, Any]] = split["counted"]
    n = len(counted)
    bars = {
        "uncertainty": _uncertainty(counted, texts["uncertainty"], draws=draws, seed=seed),
        "tail_loss": _tail(counted, texts["tail_loss"]),
        "market_spread": _market(counted, texts["market_spread"]),
        "regime_spread": _regime(counted, texts["regime_spread"]),
        "tradable_subset": _tradable(counted, texts["tradable_subset"]),
    }
    drawdown, sterling = _sterling_bars(
        counted,
        fx,
        scoring_date,
        drawdown_text=texts["drawdown"],
        sterling_text=texts["sterling_slot_book"],
    )
    bars["drawdown"] = drawdown
    bars["sterling_slot_book"] = sterling
    ordered = {key: bars[key] for key in BAR_ORDER}
    verdicts = [row["verdict"] for row in ordered.values()]
    if len(verdicts) == 7 and all(item == "pass" for item in verdicts):
        verdict = "all_bars_met"
        met = True
    elif any(item == "fail" for item in verdicts):
        verdict = "not_met"
        met = False
    else:
        verdict = "insufficient_data"
        met = False
    return {
        "label": label,
        "survivorship_biased": survivorship_biased,
        "not_proof": not_proof,
        "influences_live": INFLUENCES_LIVE,
        "opens_live_capital": False,
        "owner_note": OWNER_NOTE,
        "n": n,
        "provenance_missing_excluded": split["provenance_missing_excluded"],
        "pending_fill_excluded": split["pending_fill_excluded"],
        "verdict": verdict,
        "all_bars_met": met,
        "bars_passed": sum(1 for item in verdicts if item == "pass"),
        "bars": ordered,
        "scoring_date": None if scoring_date is None else scoring_date.isoformat(),
    }


def _uncertainty(
    counted: list[dict[str, Any]],
    bar_text: str | None,
    *,
    draws: int,
    seed: int,
) -> dict[str, Any]:
    weeks = _entry_weeks(counted)
    values = [value for block in weeks.values() for value in block]
    missing = sum(1 for episode in counted if _as_float(episode.get("matched_excess")) is None)
    threshold = {
        "interval": UNCERTAINTY_LEVEL,
        "draws": UNCERTAINTY_DRAWS,
        "rule": "lower end of the 90% interval > 0",
    }
    reasons: list[str] = []
    if missing:
        reasons.append(
            f"{missing} counted episodes have no matched excess and are not in the resamples"
        )
    if not weeks or not values:
        reasons.append("no counted episode has a matched excess and an entry week")
        return _bar(
            verdict="insufficient_data",
            n=0,
            statistic=None,
            threshold=threshold,
            reasons=reasons,
            bar_text=bar_text,
        )
    medians = block_bootstrap_medians(weeks, draws=draws, seed=seed)
    low = linear_percentile(medians, (1.0 - UNCERTAINTY_LEVEL) / 2.0 * 100.0)
    high = linear_percentile(medians, (1.0 + UNCERTAINTY_LEVEL) / 2.0 * 100.0)
    observed = float(statistics.median(values))
    if len(weeks) == 1:
        reasons.append("one entry week: every resample is that week, so the interval has no width")
    statistic = {
        "median_matched_excess": observed,
        "interval_low": low,
        "interval_high": high,
        "entry_weeks": len(weeks),
        "draws": draws,
        "seed": seed,
    }
    if low is None:
        reasons.append("bootstrap interval could not be computed")
        verdict = "insufficient_data"
    elif low > 0:
        verdict = "pass"
    else:
        verdict = "fail"
        reasons.append("the 90% interval is not wholly above zero")
    return _bar(
        verdict=verdict,
        n=len(values),
        statistic=statistic,
        threshold=threshold,
        reasons=reasons,
        bar_text=bar_text,
    )


def _tail(counted: list[dict[str, Any]], bar_text: str | None) -> dict[str, Any]:
    values = [value for episode in counted if (value := _fair_cost(episode)) is not None]
    threshold = {"percentile": TAIL_PERCENTILE, "floor": TAIL_FLOOR, "rule": "percentile >= -0.20"}
    if not values:
        return _bar(
            verdict="insufficient_data",
            n=0,
            statistic=None,
            threshold=threshold,
            reasons=["no counted episode has a fair-cost return"],
            bar_text=bar_text,
        )
    percentile = linear_percentile(values, TAIL_PERCENTILE)
    reasons: list[str] = []
    if percentile is None:
        verdict = "insufficient_data"
        reasons.append("5th percentile could not be computed")
    elif percentile >= TAIL_FLOOR:
        verdict = "pass"
    else:
        verdict = "fail"
        reasons.append("5th-percentile fair-cost return is worse than -20%")
    return _bar(
        verdict=verdict,
        n=len(values),
        statistic={"fair_cost_percentile_5": percentile},
        threshold=threshold,
        reasons=reasons,
        bar_text=bar_text,
    )


def _market(counted: list[dict[str, Any]], bar_text: str | None) -> dict[str, Any]:
    threshold = {"rule": "median matched excess > 0 after the largest market is removed"}
    if not counted:
        return _bar(
            verdict="insufficient_data",
            n=0,
            statistic=None,
            threshold=threshold,
            reasons=["no counted episodes"],
            bar_text=bar_text,
        )
    removed = biggest_market(counted)
    rest = [episode for episode in counted if str(episode.get("market") or "") != removed]
    values = [
        value for episode in rest if (value := _as_float(episode.get("matched_excess"))) is not None
    ]
    removed_n = sum(1 for episode in counted if str(episode.get("market") or "") == removed)
    reasons = [
        f"removed {removed} ({removed_n} counted episodes); "
        "a tie goes to the later market name, as in _single_market_dependence"
    ]
    if not rest or not values:
        reasons.append("nothing with a matched excess remains after that market is removed")
        return _bar(
            verdict="insufficient_data",
            n=len(values),
            statistic={
                "removed_market": removed,
                "removed_n": removed_n,
                "median_matched_excess": None,
            },
            threshold=threshold,
            reasons=reasons,
            bar_text=bar_text,
        )
    median = float(statistics.median(values))
    if median > 0:
        verdict = "pass"
    else:
        verdict = "fail"
        reasons.append("median matched excess after the removal is not above zero")
    return _bar(
        verdict=verdict,
        n=len(values),
        statistic={
            "removed_market": removed,
            "removed_n": removed_n,
            "median_matched_excess": median,
        },
        threshold=threshold,
        reasons=reasons,
        bar_text=bar_text,
    )


def _regime(counted: list[dict[str, Any]], bar_text: str | None) -> dict[str, Any]:
    threshold = {
        "min_n": REGIME_MIN,
        "rule": "median matched excess >= 0 in both above and below, each with n >= 12",
    }
    halves: dict[str, list[float]] = {"above": [], "below": []}
    sitting_out = 0
    for episode in counted:
        label = episode.get("regime")
        value = _as_float(episode.get("matched_excess"))
        if label not in ("above", "below"):
            sitting_out += 1
            continue
        if value is None:
            sitting_out += 1
            continue
        halves[str(label)].append(value)
    reasons = [f"{sitting_out} counted episodes sit out (regime_unknown or no matched excess)"]
    statistic = {
        "above": {"n": len(halves["above"]), "median_matched_excess": _median(halves["above"])},
        "below": {"n": len(halves["below"]), "median_matched_excess": _median(halves["below"])},
        "regime_unknown_sitting_out": sitting_out,
    }
    short = [name for name, values in halves.items() if len(values) < REGIME_MIN]
    if short:
        reasons.append(
            "need at least 12 counted mature episodes in each regime half; "
            f"short: {', '.join(short)}"
        )
        return _bar(
            verdict="insufficient_data",
            n=len(halves["above"]) + len(halves["below"]),
            statistic=statistic,
            threshold=threshold,
            reasons=reasons,
            bar_text=bar_text,
        )
    failed = [name for name, values in halves.items() if statistics.median(values) < 0]
    if failed:
        reasons.append(f"median matched excess is below zero in {', '.join(failed)}")
        verdict = "fail"
    else:
        verdict = "pass"
    return _bar(
        verdict=verdict,
        n=len(halves["above"]) + len(halves["below"]),
        statistic=statistic,
        threshold=threshold,
        reasons=reasons,
        bar_text=bar_text,
    )


def _tradable(counted: list[dict[str, Any]], bar_text: str | None) -> dict[str, Any]:
    listed = [episode for episode in counted if episode.get("t212_listed") is True]
    values = [
        value
        for episode in listed
        if (value := _as_float(episode.get("matched_excess"))) is not None
    ]
    threshold = {"rule": "median matched excess > 0 on t212_listed episodes"}
    sitting_out = sum(1 for episode in counted if episode.get("t212_listed") is not True)
    reasons = [f"{sitting_out} counted episodes are not t212_listed and sit out of this bar"]
    if not values:
        reasons.append("no counted t212_listed episode has a matched excess")
        return _bar(
            verdict="insufficient_data",
            n=0,
            statistic=None,
            threshold=threshold,
            reasons=reasons,
            bar_text=bar_text,
        )
    median = float(statistics.median(values))
    if median > 0:
        verdict = "pass"
    else:
        verdict = "fail"
        reasons.append("median matched excess on t212_listed episodes is not above zero")
    return _bar(
        verdict=verdict,
        n=len(values),
        statistic={"median_matched_excess": median},
        threshold=threshold,
        reasons=reasons,
        bar_text=bar_text,
    )


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _sterling_bars(
    counted: list[dict[str, Any]],
    fx: FxHistory,
    scoring: date | None,
    *,
    drawdown_text: str | None,
    sterling_text: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    drawdown_threshold = {
        "multiple": DRAWDOWN_MULTIPLE,
        "slots": SLOT_BOOK_SLOTS,
        "rule": "slot peak-to-trough fall <= 1.5 times the matched basket fall",
    }
    sterling_threshold = {
        "slots": SLOT_BOOK_SLOTS,
        "rule": "sterling total return > 0 and greater than the matched basket",
    }
    empty_reasons = ["no counted episodes"]
    if SLOT_COUNT != SLOT_BOOK_SLOTS:
        mismatch = (
            f"strategy_book_rules.SLOT_COUNT is {SLOT_COUNT}, "
            f"the sealed bar names a {SLOT_BOOK_SLOTS}-slot book"
        )
        return (
            _bar(
                verdict="insufficient_data",
                n=len(counted),
                statistic=None,
                threshold=drawdown_threshold,
                reasons=[mismatch],
                bar_text=drawdown_text,
            ),
            _bar(
                verdict="insufficient_data",
                n=len(counted),
                statistic=None,
                threshold=sterling_threshold,
                reasons=[mismatch],
                bar_text=sterling_text,
            ),
        )
    if not counted:
        return (
            _bar(
                verdict="insufficient_data",
                n=0,
                statistic=None,
                threshold=drawdown_threshold,
                reasons=list(empty_reasons),
                bar_text=drawdown_text,
            ),
            _bar(
                verdict="insufficient_data",
                n=0,
                statistic=None,
                threshold=sterling_threshold,
                reasons=list(empty_reasons),
                bar_text=sterling_text,
            ),
        )
    slot_rows, basket_rows, problems, fallbacks = _prepare_sterling(counted, fx, scoring)
    if problems:
        return (
            _bar(
                verdict="insufficient_data",
                n=len(counted),
                statistic=None,
                threshold=drawdown_threshold,
                reasons=problems,
                bar_text=drawdown_text,
            ),
            _bar(
                verdict="insufficient_data",
                n=len(counted),
                statistic=None,
                threshold=sterling_threshold,
                reasons=list(problems),
                bar_text=sterling_text,
            ),
        )
    slot = _slot_book(slot_rows, seed=SLOT_BOOK_RANDOM_SEED)
    basket = _slot_book(basket_rows, seed=SLOT_BOOK_RANDOM_SEED)
    slot_fall = _fall(slot)
    basket_fall = _fall(basket)
    slot_total = _total_return(slot)
    basket_total = _total_return(basket)
    dates = sorted(
        {str(row["fill_session"]) for row in slot_rows}
        | {str(row["exit_session"]) for row in slot_rows if row.get("exit_session")}
    )
    shared = {
        "event_dates_start": dates[0] if dates else None,
        "event_dates_end": dates[-1] if dates else None,
        "slot_trades_taken": slot.get("trades_taken"),
        "basket_trades_taken": basket.get("trades_taken"),
        "same_dates": SAME_DATES,
        "whole_screen_fallback_baskets": fallbacks,
    }
    drawdown_reasons: list[str] = []
    sterling_reasons: list[str] = []
    if slot.get("trades_taken") in (0, None) or slot_fall is None or basket_fall is None:
        drawdown_reasons.append("the reference slot book or the basket book took no trades")
        drawdown_verdict = "insufficient_data"
    elif slot_fall <= DRAWDOWN_MULTIPLE * basket_fall:
        drawdown_verdict = "pass"
    else:
        drawdown_verdict = "fail"
        drawdown_reasons.append(
            "the sterling slot book's peak-to-trough fall is more than 1.5 times the basket's"
        )
    if slot_total is None or basket_total is None or slot.get("trades_taken") in (0, None):
        sterling_reasons.append("the reference slot book has no sterling total return")
        sterling_verdict = "insufficient_data"
    elif slot_total > 0 and slot_total > basket_total:
        sterling_verdict = "pass"
    else:
        sterling_verdict = "fail"
        if slot_total <= 0:
            sterling_reasons.append("sterling total return is not positive")
        if slot_total <= basket_total:
            sterling_reasons.append("the sterling slot book does not beat the matched basket")
    ratio = None
    if slot_fall is not None and basket_fall not in (None, 0):
        ratio = slot_fall / basket_fall
    return (
        _bar(
            verdict=drawdown_verdict,
            n=len(slot_rows),
            statistic={
                **shared,
                "slot_fall": slot_fall,
                "basket_fall": basket_fall,
                "fall_ratio": ratio,
            },
            threshold=drawdown_threshold,
            reasons=drawdown_reasons,
            bar_text=drawdown_text,
        ),
        _bar(
            verdict=sterling_verdict,
            n=len(slot_rows),
            statistic={
                **shared,
                "slot_total_return": slot_total,
                "basket_total_return": basket_total,
            },
            threshold=sterling_threshold,
            reasons=sterling_reasons,
            bar_text=sterling_text,
        ),
    )


def _load_registration(repo_root: Path) -> dict[str, Any] | None:
    path = Path(repo_root) / "docs" / "data" / REGISTRATION_STORE_NAME
    if not path.is_file():
        return None
    try:
        payload = _read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_observe(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = Path(repo_root) / "docs" / "data" / OBSERVE_STORE_NAME
    meta: dict[str, Any] = {"path": f"docs/data/{OBSERVE_STORE_NAME}", "present": False}
    if not path.is_file():
        meta["reason"] = "forward observe store is missing"
        return [], meta
    try:
        payload = _read_json(path)
    except (OSError, ValueError, TypeError) as exc:
        meta["reason"] = f"forward observe store is unreadable: {exc}"
        return [], meta
    if not isinstance(payload, dict):
        meta["reason"] = "forward observe store is not a JSON object"
        return [], meta
    episodes = payload.get("episodes")
    meta["present"] = True
    meta["generated_at"] = payload.get("generated_at")
    meta["scoring_date"] = payload.get("scoring_date")
    meta["data_commit"] = payload.get("data_commit")
    meta["registration_id"] = payload.get("registration_id")
    if not isinstance(episodes, list):
        meta["reason"] = "forward observe store has no episode list"
        return [], meta
    return [row for row in episodes if isinstance(row, dict)], meta


def _load_archive(repo_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = Path(repo_root) / "docs" / "data" / REPLAY_DETAIL_STORE_NAME
    meta: dict[str, Any] = {
        "path": f"docs/data/{REPLAY_DETAIL_STORE_NAME}",
        "arm": ARCHIVE_ARM,
        "present": False,
        "survivorship_biased": True,
        "not_proof": True,
    }
    if not path.is_file():
        meta["reason"] = "archive replay detail store is missing"
        return [], meta
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError, gzip.BadGzipFile) as exc:
        meta["reason"] = f"archive replay detail store is unreadable: {exc}"
        return [], meta
    if not isinstance(payload, dict):
        meta["reason"] = "archive replay detail store is not a JSON object"
        return [], meta
    arm = payload.get(ARCHIVE_ARM)
    if isinstance(arm, dict) and isinstance(arm.get("episodes"), list):
        meta["present"] = True
        meta["scoring_date"] = arm.get("scoring_date")
        meta["registration_id"] = payload.get("registration_id")
        return [row for row in arm["episodes"] if isinstance(row, dict)], meta
    meta["reason"] = f"archive replay has no {ARCHIVE_ARM} episode list"
    return [], meta


def _bar_text_map(rows: list[dict[str, str]]) -> dict[str, str]:
    return {row["requirement"]: row["bar"] for row in rows}


def _demote_if_seal_broken(board: dict[str, Any], problems: list[str]) -> None:
    if not problems:
        return
    board["all_bars_met"] = False
    if board.get("verdict") == "all_bars_met":
        board["verdict"] = "not_met"
    notes = list(board.get("seal_problems") or [])
    notes.extend(problems)
    board["seal_problems"] = notes


def build_proof_board(
    repo_root: Path,
    *,
    fx: FxHistory | None = None,
    now: datetime | None = None,
    forward_episodes: list[dict[str, Any]] | None = None,
    archive_episodes: list[dict[str, Any]] | None = None,
    scoring_date: date | None = None,
) -> dict[str, Any]:
    """Build the proof board in memory. Does not write any store."""
    root = Path(repo_root)
    moment = now or datetime.now(UTC)
    registration = _load_registration(root)
    rows = _seal_rows(registration)
    phrase_problems = seal_phrase_problems(rows)
    plan_path = root / PLAN_RELATIVE
    computed_hash: str | None = None
    hash_problems: list[str] = []
    if not plan_path.is_file():
        hash_problems.append("strategy reorientation plan is missing")
    else:
        computed_hash = sealed_section_sha256(plan_path.read_text(encoding="utf-8"))
        if computed_hash is None:
            hash_problems.append("step 3.2 sealed section was not found in the plan")
    expected_hash = _expected_section_hash(registration)
    if expected_hash is None:
        hash_problems.append("registration has no sealed section hash for the plan")
    elif computed_hash is not None and computed_hash != expected_hash:
        hash_problems.append("step 3.2 sealed section hash does not match the registration")
    seal_ok = not phrase_problems and not hash_problems
    history = fx if fx is not None else FxHistory.load(root)
    texts = _bar_text_map(rows)
    if forward_episodes is None:
        forward_rows, forward_meta = _load_observe(root)
        forward_scoring = _day(forward_meta.get("scoring_date"))
    else:
        forward_rows = forward_episodes
        forward_meta = {"present": True, "path": "override", "scoring_date": None}
        forward_scoring = scoring_date
    if archive_episodes is None:
        archive_rows, archive_meta = _load_archive(root)
        archive_scoring = _day(archive_meta.get("scoring_date"))
    else:
        archive_rows = archive_episodes
        archive_meta = {
            "present": True,
            "path": "override",
            "arm": ARCHIVE_ARM,
            "survivorship_biased": True,
            "not_proof": True,
        }
        archive_scoring = scoring_date
    forward = evaluate_population(
        forward_rows,
        fx=history,
        scoring_date=forward_scoring,
        label="forward",
        survivorship_biased=False,
        not_proof=False,
        bar_text=texts,
    )
    forward["source"] = forward_meta
    archive = evaluate_population(
        archive_rows,
        fx=history,
        scoring_date=archive_scoring,
        label="archive_replay_report_only",
        survivorship_biased=True,
        not_proof=True,
        bar_text=texts,
    )
    archive["source"] = archive_meta
    if not archive_meta.get("present"):
        archive["verdict"] = "insufficient_data"
        archive["all_bars_met"] = False
        archive["archive_unavailable"] = archive_meta.get("reason")
    if not seal_ok:
        _demote_if_seal_broken(forward, phrase_problems + hash_problems)
    all_met = bool(forward.get("all_bars_met")) and seal_ok
    return {
        "registration_id": REGISTRATION_ID,
        "influences_live": False,
        "opens_live_capital": False,
        "owner_may_consider_step": "5.5",
        "owner_note": OWNER_NOTE,
        "step": "3.2",
        "status": "built_awaiting_owner_signoff",
        "generated_at": moment.astimezone(UTC).isoformat(),
        "seal_ok": seal_ok,
        "sealed_section_sha256": computed_hash,
        "sealed_section_sha256_expected": expected_hash,
        "seal_problems": phrase_problems + hash_problems,
        "seal_bars": rows,
        "all_bars_met": all_met,
        "verdict": forward["verdict"]
        if all_met or forward["verdict"] != "all_bars_met"
        else "not_met",
        "methods": {
            "population": (
                "Counted mature primary episodes. provenance_missing is excluded. "
                "pending_fill is excluded. The thickness gate's per-week cap is not applied."
            ),
            "bootstrap": (
                f"Block bootstrap of whole ISO entry weeks, {UNCERTAINTY_DRAWS} resamples, "
                f"random.Random seed {BOOTSTRAP_SEED} (the signature date; the seal does not "
                "name a seed). Each resample draws as many weeks as the counted set has, "
                "with replacement, and keeps every matched excess in a drawn week. "
                "The 90% interval is the linear 5th and 95th percentiles of those medians. "
                "The bar passes only when the lower end is above zero."
            ),
            "fx": history.to_meta()["point_in_time"],
            "same_dates": SAME_DATES,
            "archive": (
                "archive_replay_report_only is the buy-tier-only arm of the committed "
                "archive replay. It is survivorship-biased and is not the proof."
            ),
        },
        "fx": history.to_meta(),
        "forward": forward,
        "archive_replay_report_only": archive,
    }


def write_proof_board(repo_root: Path, board: dict[str, Any]) -> Path:
    path = proof_store_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _parse_generated_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def findings_for_store(
    repo_root: Path,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Ops-monitor rows. Reads the proof store. Does not rescore or write."""
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    path = proof_store_path(repo_root)
    if not path.is_file():
        return [
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_MISSING,
                "summary": f"{path.as_posix()} is missing. The forward job writes it.",
                "auto_fixable": False,
            }
        ]
    try:
        payload = _read_json(path)
    except (OSError, ValueError, TypeError) as exc:
        return [
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_UNREADABLE,
                "summary": f"{path.name} could not be read: {exc}",
                "auto_fixable": False,
            }
        ]
    if not isinstance(payload, dict) or not isinstance(payload.get("forward"), dict):
        return [
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_UNREADABLE,
                "summary": f"{path.name} has no forward proof board.",
                "auto_fixable": False,
            }
        ]
    generated = _parse_generated_at(payload.get("generated_at"))
    if generated is None or moment - generated > PROOF_STALE_AFTER:
        age = "missing generated_at" if generated is None else generated.date().isoformat()
        return [
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_STALE,
                "summary": (
                    f"{path.name} generated_at is {age}. "
                    f"Stale means older than {PROOF_STALE_AFTER.days} days."
                ),
                "auto_fixable": False,
            }
        ]
    forward = payload["forward"]
    passed = forward.get("bars_passed")
    counted = forward.get("n")
    verdict = payload.get("verdict")
    return [
        {
            "severity": "info",
            "category": "research",
            "title": TITLE_INFO,
            "summary": (
                f"Forward: {passed} of 7 bars pass, n={counted} counted mature episodes, "
                f"verdict {verdict}. {OWNER_NOTE}"
            ),
            "auto_fixable": False,
        }
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score the strategy book's step 3.2 proof bars (observe-only). "
            "Meeting every bar lets the owner consider step 5.5 and opens nothing."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the board without writing the store",
    )
    args = parser.parse_args(argv)
    board = build_proof_board(args.repo_root)
    if not args.no_write:
        write_proof_board(args.repo_root, board)
    print(json.dumps(board, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
