"""Observe-only fair-value range for strategy-book episodes (plan step 4.1).

A separate deterministic pass. It does not call a model, does not edit memos,
and does not change the walker, the registration, or the observe store.
``influences_live`` is false.

At each episode's signal session it builds a low / mid / high value from
point-in-time annual statements already in the repo, then a margin of safety
against the signal-session close. Mature and closed episodes are scored in
fixed margin buckets. With fewer than ``BUCKET_MIN_N`` episodes in a bucket
the verdict is ``insufficient_data``.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import statistics
import subprocess
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.fx import currency_for_ticker
from value_investor.operating_decline_gate import EPS_LABELS, FCF_LABEL, _to_date, _year_series
from value_investor.sector_headwind_gate import FTSE_MARKET
from value_investor.strategy_book_proof import FxHistory
from value_investor.strategy_book_replay import _chart_file, _read_chart
from value_investor.strategy_book_rules import (
    COLUMN_PRIMARY,
    INFLUENCES_LIVE,
    OBSERVE_STORE_NAME,
    REGISTRATION_ID,
)
from value_investor.strategy_book_signals import parse_day, repo_paths, research_root_for

STORE_NAME = "strategy_book_fair_value.json"
SCHEMA_VERSION = 1
STALE_AFTER = timedelta(days=5)

TITLE_INFO = "Strategy book fair value"
TITLE_MISSING = "Strategy book fair value missing"
TITLE_UNREADABLE = "Strategy book fair value unreadable"
TITLE_STALE = "Strategy book fair value stale"

# v0 constants. Chosen before any outcome was read. Do not retune them on returns.
MIN_YEARS = 3
MAX_YEARS = 5
MULTIPLE_LOW = 10.0
MULTIPLE_MID = 15.0
MULTIPLE_HIGH = 20.0
# No-growth perpetuity. A higher discount is a lower value.
DISCOUNT_VALUE_LOW = 0.10
DISCOUNT_VALUE_MID = 0.08
DISCOUNT_VALUE_HIGH = 0.06
BUCKET_MIN_N = 12
BUCKET_MIDDLE_MAX = 0.33
PENCE_PER_POUND = 100
ENTRY_REFERENCE = "signal_session_close"

REASON_SIGNAL_SESSION = "signal_session_missing"
REASON_FINANCIALS_MISSING = "financials_missing"
REASON_FINANCIALS_UNDATED = "financials_undated"
REASON_FINANCIALS_AFTER = "financials_after_signal"
REASON_FEW_YEARS = "fewer_than_3_annual_eps"
REASON_NON_POSITIVE = "non_positive_normalised_earnings"
REASON_CLOSE_MISSING = "signal_close_missing"
REASON_CURRENCY = "reporting_currency_unstated"
REASON_CURRENCY_DISAGREE = "currency_sources_disagree"
REASON_FX = "fx_rate_missing"

SHARE_LABELS = ("Diluted Average Shares", "Basic Average Shares")
_FILING_CURRENCY = {
    "£": "GBP",
    "$": "USD",
    "€": "EUR",
}
_FILING_CURRENCY_RE = re.compile(r"filing(?: \(primary\))? ([£$€])")
_BUCKETS = (
    ("below_0", "margin < 0"),
    ("zero_to_0.33", "0 <= margin <= 0.33"),
    ("above_0.33", "margin > 0.33"),
)

CONSTANTS: dict[str, Any] = {
    "version": "v0",
    "tuned_on_outcomes": False,
    "min_years": MIN_YEARS,
    "max_years": MAX_YEARS,
    "eps_labels": list(EPS_LABELS),
    "fcf_label": FCF_LABEL,
    "share_labels": list(SHARE_LABELS),
    "multiples": {"low": MULTIPLE_LOW, "mid": MULTIPLE_MID, "high": MULTIPLE_HIGH},
    "reverse_dcf": {
        "growth": 0,
        "discounts": {
            "value_low": DISCOUNT_VALUE_LOW,
            "value_mid": DISCOUNT_VALUE_MID,
            "value_high": DISCOUNT_VALUE_HIGH,
        },
        "formula": "latest_per_share_in_price_units / discount",
    },
    "margin_of_safety": "1 - entry_reference_price / mid",
    "entry_reference": ENTRY_REFERENCE,
    "pence_per_pound": PENCE_PER_POUND,
    "london_price_unit": (
        "Tickers ending in .L are quoted in pence (GBX) on the chart, "
        "including when the chart currency field says GBP. "
        "Statement amounts are in major currency units, then multiplied by 100 "
        "after conversion into pounds."
    ),
    "bucket_min_n": BUCKET_MIN_N,
    "buckets": [{"id": name, "rule": rule} for name, rule in _BUCKETS],
    "scoring_population": (
        "Primary episodes with a range that are mature or closed. "
        "Other columns are stored and are not pooled into the primary buckets, "
        "because they are the same entry walked under a different exit."
    ),
    "point_in_time": (
        "Statement years after the signal year are dropped (the decline gate's "
        "year rule). A financials file is used only when fetched_at is on or "
        "before the signal session; a later fetched_at is replaced by the last "
        "git blob of that file on or before the session when one exists. "
        "Snapshot currency uses the same git rule, because the snapshot has no "
        "fetched_at. SEC currency uses a row whose first_filed is on or before "
        "the session, and only when the file's fetched_at is too. "
        "The entry price is the chart close dated on the signal session. "
        "Recovery uses chart closes after the signal session and up to the exit "
        "session. FX is the committed macro history, not a live spot."
    ),
}


def store_path(repo_root: Path) -> Path:
    return Path(repo_root) / "docs" / "data" / STORE_NAME


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    return None


def _round(value: float, places: int) -> float:
    return round(float(value), places)


def _rel(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_available(repo: Path) -> bool:
    return (Path(repo) / ".git").exists()


def _git_commit_day(repo: Path, path: Path) -> date | None:
    if not _git_available(repo):
        return None
    relative = _rel(repo, path)
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%cI", "--", relative],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return _to_date(result.stdout.strip())


def _git_blob_json(repo: Path, path: Path, session: date) -> Any | None:
    if not _git_available(repo):
        return None
    relative = _rel(repo, path)
    until = f"{session.isoformat()}T23:59:59"
    try:
        logged = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "log",
                "-1",
                "--until",
                until,
                "--format=%H",
                "--",
                relative,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        sha = logged.stdout.strip()
        if logged.returncode != 0 or not sha:
            return None
        shown = subprocess.run(
            ["git", "-C", str(repo), "show", f"{sha}:{relative}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if shown.returncode != 0 or not shown.stdout:
        return None
    try:
        return json.loads(shown.stdout)
    except (ValueError, TypeError):
        return None


def load_json_known_on(
    repo: Path,
    path: Path,
    session: date,
    *,
    date_field: str | None,
) -> tuple[dict[str, Any] | None, str]:
    """JSON known on ``session``.

    ``date_field`` (``fetched_at``) wins when it is on or before the session.
    A later ``fetched_at``, or a snapshot with no date field whose git commit
    is after the session, is replaced by the last blob on or before the session.
    A fixture outside git is the file on disk; ``fetched_at`` still applies.
    """
    if not path.is_file():
        return None, "missing"
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None, "unreadable"
    internal = _to_date(payload.get(date_field)) if date_field else None
    if date_field and internal is not None and internal <= session:
        return payload, "file"
    if not _git_available(repo):
        if date_field and internal is None:
            return payload, "file_undated"
        if date_field and internal is not None and internal > session:
            return payload, "file_after_signal"
        return payload, "file"
    commit_day = _git_commit_day(repo, path)
    if commit_day is not None and commit_day <= session:
        return payload, "file"
    historical = _git_blob_json(repo, path, session)
    if isinstance(historical, dict):
        return historical, "git_as_of"
    if date_field and internal is not None and internal > session:
        return payload, "file_after_signal"
    if date_field and internal is None:
        return None, "undated"
    return None, "committed_after_signal"


def _latest_years(series: dict[int, float], session: date) -> list[tuple[int, float]]:
    """Up to ``MAX_YEARS`` fiscal years on or before the signal year, newest last."""
    kept = [(year, value) for year, value in series.items() if year <= session.year]
    kept.sort()
    return kept[-MAX_YEARS:]


def _pick_label(
    statement: Any, labels: tuple[str, ...], session: date
) -> tuple[str | None, list[tuple[int, float]]]:
    best_label: str | None = None
    best: list[tuple[int, float]] = []
    for label in labels:
        years = _latest_years(_year_series(statement, label, session), session)
        if len(years) > len(best):
            best_label = label
            best = years
    return best_label, best


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.fmean(values))


def _price_unit(ticker: str, market: str) -> tuple[str, str]:
    """Return ``(price_unit, major_currency)``.

    London ``.L`` charts are pence. ``currency_for_ticker`` still says GBP,
    which is the major unit the statements convert into before the ×100.
    """
    major = currency_for_ticker(ticker, market=market) or "USD"
    if str(ticker).upper().endswith(".L") and major == "GBP":
        return "GBX", "GBP"
    return major, major


def _fx_to_major(
    fx: FxHistory | None,
    statement_currency: str,
    major: str,
    session: date,
) -> tuple[float | None, dict[str, Any] | None, str]:
    if statement_currency == major:
        return 1.0, None, ""
    if fx is None:
        return None, None, f"no FX history to convert {statement_currency} into {major}"
    sterling_per_statement, why_statement = fx.gbp_per_unit(statement_currency, session)
    if sterling_per_statement is None:
        return None, None, why_statement or f"no {statement_currency} rate"
    if major in {"GBP", "GBX"}:
        return (
            sterling_per_statement,
            {
                "pair": f"GBP per {statement_currency}",
                "rate": _round(sterling_per_statement, 6),
                "as_of_rule": "latest macro marker on or before the signal session",
            },
            "",
        )
    sterling_per_major, why_major = fx.gbp_per_unit(major, session)
    if sterling_per_major is None or sterling_per_major == 0:
        return None, None, why_major or f"no {major} rate"
    rate = sterling_per_statement / sterling_per_major
    return (
        rate,
        {
            "pair": f"{major} per {statement_currency}",
            "rate": _round(rate, 6),
            "as_of_rule": "latest macro marker on or before the signal session",
        },
        "",
    )


def _to_price_units(
    amount: float,
    *,
    statement_currency: str,
    price_unit: str,
    major: str,
    fx: FxHistory | None,
    session: date,
) -> tuple[float | None, dict[str, Any] | None, str]:
    rate, fx_meta, why = _fx_to_major(fx, statement_currency, major, session)
    if rate is None:
        return None, None, why
    scaled = amount * rate
    if price_unit == "GBX":
        scaled *= PENCE_PER_POUND
    return scaled, fx_meta, ""


def _multiple_band(per_share: float) -> dict[str, float]:
    return {
        "low": _round(per_share * MULTIPLE_LOW, 4),
        "mid": _round(per_share * MULTIPLE_MID, 4),
        "high": _round(per_share * MULTIPLE_HIGH, 4),
    }


def _reverse_dcf(latest_per_share: float) -> dict[str, Any]:
    """No-growth value of the latest year, not of the multi-year average."""
    if latest_per_share <= 0:
        return {
            "status": REASON_NON_POSITIVE,
            "growth": 0,
            "latest_per_share": _round(latest_per_share, 6),
        }
    low = latest_per_share / DISCOUNT_VALUE_LOW
    mid = latest_per_share / DISCOUNT_VALUE_MID
    high = latest_per_share / DISCOUNT_VALUE_HIGH
    return {
        "status": "computed",
        "growth": 0,
        "discounts": {
            "value_low": DISCOUNT_VALUE_LOW,
            "value_mid": DISCOUNT_VALUE_MID,
            "value_high": DISCOUNT_VALUE_HIGH,
        },
        "latest_per_share": _round(latest_per_share, 6),
        "low": _round(low, 4),
        "mid": _round(mid, 4),
        "high": _round(high, 4),
    }


def _cross_check(band: dict[str, float], probe: float | None) -> str:
    if probe is None:
        return "not_available"
    if band["low"] <= probe <= band["high"]:
        return "inside_band"
    return "outside_band"


def _bucket_id(margin: float) -> str:
    if margin < 0:
        return "below_0"
    if margin <= BUCKET_MIDDLE_MAX:
        return "zero_to_0.33"
    return "above_0.33"


def closes_in_window(
    sessions: list[date],
    closes: list[float],
    *,
    after: date,
    until: date,
) -> list[float]:
    """Closes with ``after < session <= until``. The signal close is not in the window."""
    found: list[float] = []
    for day, close in zip(sessions, closes, strict=False):
        if after < day <= until and close > 0 and math.isfinite(close):
            found.append(float(close))
    return found


def recovery_from_closes(
    closes: list[float],
    *,
    low: float,
    mid: float,
    closed: bool,
) -> dict[str, Any]:
    """Whether prices reached the range low and mid before exit.

    Reaching the mid counts as reaching the low, because the mid is above the low.
    An open episode is ``not_closed`` and is not a miss.
    """
    if not closed:
        return {
            "label": "not_closed",
            "reached_low": None,
            "reached_mid": None,
            "closes_used": 0,
        }
    if not closes:
        return {
            "label": "no_closes_in_window",
            "reached_low": False,
            "reached_mid": False,
            "closes_used": 0,
        }
    reached_mid = any(close >= mid for close in closes)
    reached_low = reached_mid or any(close >= low for close in closes)
    if reached_mid:
        label = "reached_mid"
    elif reached_low:
        label = "reached_low_only"
    else:
        label = "not_reached"
    return {
        "label": label,
        "reached_low": reached_low,
        "reached_mid": reached_mid,
        "closes_used": len(closes),
    }


def _per_share_rows(
    eps_years: list[tuple[int, float]],
    fcf_years: dict[int, float],
    share_years: dict[int, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year, eps in eps_years:
        shares = share_years.get(year)
        fcf = fcf_years.get(year)
        per_share = None
        if fcf is not None and shares is not None and shares > 0:
            per_share = fcf / shares
        rows.append(
            {
                "year": year,
                "eps": _round(eps, 6),
                "fcf": None if fcf is None else _round(fcf, 2),
                "shares": None if shares is None else _round(shares, 2),
                "fcf_per_share": None if per_share is None else _round(per_share, 6),
            }
        )
    return rows


def evaluate_statements(
    *,
    signal_session: date | None,
    entry_price: float | None,
    price_unit: str,
    major_currency: str,
    financials: dict[str, Any] | None,
    financials_state: str,
    financials_path: str | None,
    statement_currency: str | None,
    currency_detail: dict[str, Any],
    fx: FxHistory | None,
    window_closes: list[float],
    closed: bool,
) -> dict[str, Any]:
    """One episode's range, or one ``insufficient_data`` reason. No I/O."""
    base: dict[str, Any] = {
        "verdict": "insufficient_data",
        "reason": None,
        "reason_detail": "",
        "entry_reference": ENTRY_REFERENCE,
        "entry_reference_price": None if entry_price is None else _round(entry_price, 4),
        "entry_reference_unit": price_unit,
        "price_unit": price_unit,
        "major_currency": major_currency,
        "statement_currency": statement_currency,
        "currency": currency_detail,
        "method": None,
        "inputs": {
            "financials_path": financials_path,
            "financials_state": financials_state,
            "fetched_at": None,
            "eps_label": None,
            "years": [],
        },
        "range": None,
        "margin_of_safety": None,
        "reverse_dcf": None,
        "fcf_per_share_cross_check": None,
        "recovery": {
            "label": "not_closed" if not closed else "no_range",
            "reached_low": None,
            "reached_mid": None,
            "closes_used": 0,
        },
    }

    def fail(reason: str, detail: str) -> dict[str, Any]:
        base["reason"] = reason
        base["reason_detail"] = detail
        return base

    if signal_session is None:
        return fail(REASON_SIGNAL_SESSION, "The episode has no signal session date.")
    if financials is None:
        if financials_state == "undated":
            return fail(
                REASON_FINANCIALS_UNDATED,
                "financials_annual.json has no fetched_at, so the statements are undated.",
            )
        return fail(
            REASON_FINANCIALS_MISSING,
            "No financials_annual.json was found for this name.",
        )
    fetched = _to_date(financials.get("fetched_at"))
    base["inputs"]["fetched_at"] = None if fetched is None else fetched.isoformat()
    if fetched is None:
        return fail(
            REASON_FINANCIALS_UNDATED,
            "financials_annual.json has no fetched_at, so the statements are undated.",
        )
    if fetched > signal_session:
        return fail(
            REASON_FINANCIALS_AFTER,
            f"financials fetched_at {fetched.isoformat()} is after the signal session "
            f"{signal_session.isoformat()}.",
        )
    if not statement_currency:
        reason = str(currency_detail.get("reason") or REASON_CURRENCY)
        return fail(reason, str(currency_detail.get("detail") or "No statement currency."))

    income = financials.get("income_statement")
    cash_flow = financials.get("cash_flow")
    eps_label, eps_years = _pick_label(income, EPS_LABELS, signal_session)
    share_label, share_pairs = _pick_label(income, SHARE_LABELS, signal_session)
    fcf_pairs = _latest_years(_year_series(cash_flow, FCF_LABEL, signal_session), signal_session)
    share_years = {year: value for year, value in share_pairs}
    fcf_years = {year: value for year, value in fcf_pairs}
    rows = _per_share_rows(eps_years, fcf_years, share_years)
    base["inputs"]["eps_label"] = eps_label
    base["inputs"]["share_label"] = share_label
    base["inputs"]["years"] = rows

    eps_mean = _mean([value for _, value in eps_years]) if len(eps_years) >= MIN_YEARS else None
    fcf_aligned: list[tuple[int, float]] = []
    for year, fcf in fcf_pairs:
        shares = share_years.get(year)
        if shares is not None and shares > 0:
            fcf_aligned.append((year, fcf / shares))
    fcf_mean = _mean([value for _, value in fcf_aligned]) if len(fcf_aligned) >= MIN_YEARS else None

    method: str | None = None
    statement_per_share: float | None = None
    latest_statement: float | None = None
    if eps_mean is not None and eps_mean > 0:
        method = "normalised_earnings"
        statement_per_share = eps_mean
        latest_statement = eps_years[-1][1]
    elif fcf_mean is not None and fcf_mean > 0:
        method = "fcf_per_share"
        statement_per_share = fcf_mean
        latest_statement = fcf_aligned[-1][1]
    elif len(eps_years) < MIN_YEARS and (fcf_mean is None or fcf_mean <= 0):
        return fail(
            REASON_FEW_YEARS,
            f"{len(eps_years)} annual EPS year(s) on or before {signal_session.year} "
            f"(need {MIN_YEARS}). Free-cash-flow per share did not fill the gap.",
        )
    else:
        return fail(
            REASON_NON_POSITIVE,
            "The multi-year average EPS is not positive, and free-cash-flow per share "
            "is missing or not positive.",
        )

    base["method"] = method
    base["inputs"]["normalised_per_share"] = _round(statement_per_share, 6)
    base["inputs"]["latest_per_share"] = _round(latest_statement, 6)
    base["inputs"]["normalised_unit"] = statement_currency

    if entry_price is None or entry_price <= 0:
        return fail(
            REASON_CLOSE_MISSING,
            f"No positive chart close on the signal session {signal_session.isoformat()}.",
        )

    per_share, fx_meta, fx_why = _to_price_units(
        statement_per_share,
        statement_currency=statement_currency,
        price_unit=price_unit,
        major=major_currency,
        fx=fx,
        session=signal_session,
    )
    latest_px, _, latest_why = _to_price_units(
        latest_statement,
        statement_currency=statement_currency,
        price_unit=price_unit,
        major=major_currency,
        fx=fx,
        session=signal_session,
    )
    if per_share is None or latest_px is None:
        return fail(REASON_FX, fx_why or latest_why or "FX rate missing.")
    base["inputs"]["fx"] = fx_meta
    base["inputs"]["normalised_per_share_price_units"] = _round(per_share, 6)

    band = _multiple_band(per_share)
    margin = 1.0 - (entry_price / band["mid"])
    reverse = _reverse_dcf(latest_px)
    reverse["cross_check"] = _cross_check(band, _finite(reverse.get("mid")))
    if per_share > 0 and entry_price > 0:
        reverse["implied_earnings_yield"] = _round(per_share / entry_price, 6)

    fcf_check = None
    if method == "normalised_earnings" and fcf_mean is not None and fcf_mean > 0:
        fcf_px, _, _ = _to_price_units(
            fcf_mean,
            statement_currency=statement_currency,
            price_unit=price_unit,
            major=major_currency,
            fx=fx,
            session=signal_session,
        )
        if fcf_px is not None and fcf_px > 0:
            fcf_band = _multiple_band(fcf_px)
            fcf_check = {
                "method": "fcf_per_share",
                "normalised_per_share": _round(fcf_px, 6),
                "range": fcf_band,
                "cross_check": _cross_check(band, fcf_band["mid"]),
            }

    base["verdict"] = "range"
    base["reason"] = None
    base["reason_detail"] = ""
    base["range"] = {**band, "unit": price_unit}
    base["margin_of_safety"] = _round(margin, 6)
    base["reverse_dcf"] = reverse
    base["fcf_per_share_cross_check"] = fcf_check
    base["recovery"] = recovery_from_closes(
        window_closes,
        low=band["low"],
        mid=band["mid"],
        closed=closed,
    )
    if entry_price < band["low"]:
        base["entry_vs_range"] = "below_low"
    elif entry_price <= band["mid"]:
        base["entry_vs_range"] = "between_low_and_mid"
    elif entry_price <= band["high"]:
        base["entry_vs_range"] = "between_mid_and_high"
    else:
        base["entry_vs_range"] = "above_high"
    return base


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return _round(float(statistics.median(values)), 6)


def _is_scorable(row: dict[str, Any]) -> bool:
    if row.get("verdict") != "range":
        return False
    if row.get("mature") is True:
        return True
    return str(row.get("status") or "") == "closed"


def score_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Bucket medians for one column. Verdicts stay ``insufficient_data`` under the minimum."""
    population = [row for row in rows if _is_scorable(row)]
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name, _rule in _BUCKETS}
    for row in population:
        margin = _finite(row.get("margin_of_safety"))
        if margin is None:
            continue
        grouped[_bucket_id(margin)].append(row)

    buckets: list[dict[str, Any]] = []
    for name, rule in _BUCKETS:
        members = grouped[name]
        returns = [
            float(item["fair_cost_return"])
            for item in members
            if _finite(item.get("fair_cost_return")) is not None
        ]
        excess = [
            float(item["matched_excess"])
            for item in members
            if _finite(item.get("matched_excess")) is not None
        ]
        enough = len(members) >= BUCKET_MIN_N and len(returns) >= BUCKET_MIN_N
        buckets.append(
            {
                "id": name,
                "rule": rule,
                "n": len(members),
                "verdict": "scored" if enough else "insufficient_data",
                "median_fair_cost_return": _median(returns) if enough else None,
                "median_matched_excess": _median(excess) if enough and excess else None,
                "minimum_n": BUCKET_MIN_N,
            }
        )
    overall = (
        "scored"
        if buckets and all(item["verdict"] == "scored" for item in buckets)
        else "insufficient_data"
    )
    closed = [
        row
        for row in rows
        if row.get("verdict") == "range" and str(row.get("status") or "") == "closed"
    ]
    recovery_counts = Counter(str((row.get("recovery") or {}).get("label") or "") for row in closed)
    recovery_enough = len(closed) >= BUCKET_MIN_N
    return {
        "population": "mature or closed episodes with a range",
        "n": len(population),
        "n_with_range": sum(1 for row in rows if row.get("verdict") == "range"),
        "verdict": overall,
        "minimum_n": BUCKET_MIN_N,
        "buckets": buckets,
        "recovery": {
            "verdict": "scored" if recovery_enough else "insufficient_data",
            "n_closed_with_range": len(closed),
            "minimum_n": BUCKET_MIN_N,
            "reached_mid": recovery_counts.get("reached_mid", 0),
            "reached_low_only": recovery_counts.get("reached_low_only", 0),
            "not_reached": recovery_counts.get("not_reached", 0),
            "no_closes_in_window": recovery_counts.get("no_closes_in_window", 0),
        },
    }


def _sources_dir(repo: Path, market: str, ticker: str) -> Path:
    return research_root_for(repo_paths(repo), market) / ticker / "sources"


def _currency_from_snapshot(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    block = payload.get("fcf")
    if not isinstance(block, dict):
        return None
    raw = block.get("currency")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip().upper()


def _currency_from_sec(
    payload: dict[str, Any] | None, session: date
) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    fetched = _to_date(payload.get("fetched_at"))
    if fetched is None or fetched > session:
        return None, None
    annual = payload.get("annual")
    rows = annual if isinstance(annual, list) else []
    chosen: tuple[date, str] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        filed = _to_date(row.get("first_filed"))
        if filed is None:
            operating = row.get("operating_cashflow")
            if isinstance(operating, dict):
                filed = _to_date(operating.get("first_filed"))
        raw = row.get("currency")
        if not isinstance(raw, str) or not raw.strip():
            operating = row.get("operating_cashflow")
            raw = operating.get("unit") if isinstance(operating, dict) else None
        if filed is None or filed > session or not isinstance(raw, str) or not raw.strip():
            continue
        code = raw.strip().upper()
        if chosen is None or filed >= chosen[0]:
            chosen = (filed, code)
    if chosen is None:
        return None, None
    return chosen[1], chosen[0].isoformat()


def _note_currency(note: str) -> str | None:
    match = _FILING_CURRENCY_RE.search(note or "")
    if match is None:
        return None
    return _FILING_CURRENCY.get(match.group(1))


def _load_run(path: Path, cache: dict[str, Any]) -> dict[str, Any] | None:
    key = str(path)
    if key in cache:
        cached = cache[key]
        return cached if isinstance(cached, dict) else None
    payload: Any = None
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
        elif path.is_file():
            payload = _read_json(path)
    except (OSError, ValueError, TypeError):
        payload = None
    cache[key] = payload
    return payload if isinstance(payload, dict) else None


def _currency_from_screen(
    repo: Path,
    episode: dict[str, Any],
    session: date,
    cache: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    inputs = episode.get("inputs")
    entry = inputs.get("entry") if isinstance(inputs, dict) else None
    if not isinstance(entry, list):
        return None, None
    ticker = str(episode.get("ticker") or "").upper()
    for item in entry:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path") or "")
        if "history/run_" not in raw_path.replace("\\", "/"):
            continue
        path = Path(repo) / raw_path
        payload = _load_run(path, cache)
        if payload is None:
            continue
        run_day = _to_date(payload.get("run_at"))
        if run_day is None or run_day > session:
            continue
        for signal in payload.get("signals") or []:
            if not isinstance(signal, dict):
                continue
            if str(signal.get("ticker") or "").upper() != ticker:
                continue
            code = _note_currency(str(signal.get("action_note") or ""))
            if code is None:
                return None, None
            return code, {
                "source": "screen_action_note",
                "path": raw_path,
                "as_of": run_day.isoformat(),
            }
    return None, None


def resolve_statement_currency(
    *,
    snapshot: dict[str, Any] | None,
    snapshot_state: str,
    snapshot_path: str | None,
    sec: dict[str, Any] | None,
    sec_state: str,
    sec_path: str | None,
    session: date,
    screen_currency: str | None,
    screen_detail: dict[str, Any] | None,
) -> tuple[str | None, dict[str, Any]]:
    """Explicit currencies only. Disagreeing sources fail closed."""
    found: list[tuple[str, dict[str, Any]]] = []
    if snapshot_state in {"file", "git_as_of"}:
        code = _currency_from_snapshot(snapshot)
        if code:
            found.append(
                (
                    code,
                    {
                        "source": "screening_snapshot.fcf.currency",
                        "path": snapshot_path,
                        "state": snapshot_state,
                    },
                )
            )
    if sec_state in {"file", "git_as_of", "file_undated"}:
        code, filed = _currency_from_sec(sec, session)
        if code:
            found.append(
                (
                    code,
                    {
                        "source": "sec_companyfacts.annual.currency",
                        "path": sec_path,
                        "state": sec_state,
                        "first_filed": filed,
                    },
                )
            )
    if screen_currency and screen_detail:
        found.append((screen_currency, screen_detail))
    codes = {code for code, _meta in found}
    if len(codes) > 1:
        return None, {
            "reason": REASON_CURRENCY_DISAGREE,
            "detail": "Statement currency sources disagree: "
            + ", ".join(f"{meta['source']}={code}" for code, meta in found),
            "sources": [meta | {"currency": code} for code, meta in found],
        }
    if len(codes) == 1:
        code = next(iter(codes))
        return code, {
            "currency": code,
            "sources": [meta | {"currency": code} for code, meta in found],
        }
    return None, {
        "reason": REASON_CURRENCY,
        "detail": (
            "No statement currency on the screening snapshot, the SEC facts, "
            "or the point-in-time screen note."
        ),
        "sources": [],
    }


def _chart_series(repo: Path, ticker: str) -> tuple[list[date], list[float], str | None]:
    charts = Path(repo) / "docs" / "data" / "charts"
    path = _chart_file(charts, ticker)
    if path is None:
        return [], [], None
    parsed = _read_chart(path)
    relative = _rel(repo, path)
    if parsed is None:
        return [], [], relative
    sessions, closes, _highs, _lows = parsed
    return sessions, closes, relative


def _signal_close(sessions: list[date], closes: list[float], session: date) -> float | None:
    for day, close in zip(sessions, closes, strict=False):
        if day == session and close > 0 and math.isfinite(close):
            return float(close)
    return None


def build_episode_row(
    repo: Path,
    episode: dict[str, Any],
    *,
    fx: FxHistory | None,
    run_cache: dict[str, Any],
    file_cache: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    market = str(episode.get("market") or "")
    ticker = str(episode.get("ticker") or "")
    signal = parse_day(episode.get("signal_session"))
    price_unit, major = _price_unit(ticker, market)
    cache_key = (market, ticker, signal.isoformat() if signal else "")
    if cache_key not in file_cache:
        file_cache[cache_key] = _load_name_files(repo, market, ticker, signal, episode, run_cache)
    loaded = file_cache[cache_key]
    sessions = loaded["sessions"]
    closes = loaded["closes"]
    entry = None if signal is None else _signal_close(sessions, closes, signal)
    exit_day = parse_day(episode.get("exit_session"))
    closed = str(episode.get("status") or "") == "closed" or exit_day is not None
    window: list[float] = []
    if signal is not None and exit_day is not None:
        window = closes_in_window(sessions, closes, after=signal, until=exit_day)
    evaluated = evaluate_statements(
        signal_session=signal,
        entry_price=entry,
        price_unit=price_unit,
        major_currency=major,
        financials=loaded["financials"],
        financials_state=loaded["financials_state"],
        financials_path=loaded["financials_path"],
        statement_currency=loaded["statement_currency"],
        currency_detail=loaded["currency_detail"],
        fx=fx,
        window_closes=window,
        closed=closed and exit_day is not None,
    )
    evaluated["inputs"]["chart_path"] = loaded["chart_path"]
    return {
        "episode_id": episode.get("episode_id"),
        "market": market,
        "ticker": ticker,
        "column": episode.get("column"),
        "status": episode.get("status"),
        "signal_session": None if signal is None else signal.isoformat(),
        "exit_session": None if exit_day is None else exit_day.isoformat(),
        "mature": episode.get("mature"),
        "fair_cost_return": _finite(episode.get("fair_cost_return")),
        "matched_excess": _finite(episode.get("matched_excess")),
        **evaluated,
    }


def _load_name_files(
    repo: Path,
    market: str,
    ticker: str,
    signal: date | None,
    episode: dict[str, Any],
    run_cache: dict[str, Any],
) -> dict[str, Any]:
    sources = _sources_dir(repo, market or FTSE_MARKET, ticker)
    financials_path = sources / "financials_annual.json"
    snapshot_path = sources / "screening_snapshot.json"
    sec_path = sources / "sec_companyfacts.json"
    session = signal or date.min
    financials, financials_state = load_json_known_on(
        repo, financials_path, session, date_field="fetched_at"
    )
    if financials_state == "file_after_signal":
        # The helper returns the later file so the caller can see fetched_at.
        # evaluate_statements rejects that date. Keep the payload.
        pass
    elif financials_state == "file_undated":
        financials_state = "file"
    snapshot, snapshot_state = load_json_known_on(repo, snapshot_path, session, date_field=None)
    sec, sec_state = load_json_known_on(repo, sec_path, session, date_field="fetched_at")
    screen_currency, screen_detail = (None, None)
    if signal is not None:
        screen_currency, screen_detail = _currency_from_screen(repo, episode, signal, run_cache)
    currency, detail = resolve_statement_currency(
        snapshot=snapshot,
        snapshot_state=snapshot_state,
        snapshot_path=None if not snapshot_path.is_file() else _rel(repo, snapshot_path),
        sec=sec,
        sec_state=sec_state,
        sec_path=None if not sec_path.is_file() else _rel(repo, sec_path),
        session=session,
        screen_currency=screen_currency,
        screen_detail=screen_detail,
    )
    sessions, closes, chart_path = _chart_series(repo, ticker)
    state = financials_state
    if state == "missing":
        state = "missing"
    elif state == "file_undated":
        state = "file"
    return {
        "financials": financials,
        "financials_state": "missing" if financials is None and state == "missing" else state,
        "financials_path": _rel(repo, financials_path) if financials_path.is_file() else None,
        "statement_currency": currency,
        "currency_detail": detail,
        "sessions": sessions,
        "closes": closes,
        "chart_path": chart_path,
    }


def _episode_sort(row: dict[str, Any]) -> tuple[int, str, str, str]:
    primary = 0 if row.get("column") == COLUMN_PRIMARY else 1
    return (
        primary,
        str(row.get("column") or ""),
        str(row.get("ticker") or ""),
        str(row.get("signal_session") or ""),
    )


def _coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reasons = Counter(
        str(row.get("reason"))
        for row in rows
        if row.get("verdict") != "range" and row.get("reason")
    )
    primary = [row for row in rows if row.get("column") == COLUMN_PRIMARY]
    primary_margins = [
        float(row["margin_of_safety"])
        for row in primary
        if _finite(row.get("margin_of_safety")) is not None
    ]
    return {
        "episodes": len(rows),
        "with_range": sum(1 for row in rows if row.get("verdict") == "range"),
        "insufficient_data": sum(1 for row in rows if row.get("verdict") != "range"),
        "reasons": dict(sorted(reasons.items())),
        "primary_episodes": len(primary),
        "primary_with_range": sum(1 for row in primary if row.get("verdict") == "range"),
        "primary_insufficient_data": sum(1 for row in primary if row.get("verdict") != "range"),
        "primary_margin_median": _median(primary_margins),
    }


def build_fair_value_store(
    repo_root: Path,
    *,
    now: datetime | None = None,
    fx: FxHistory | None = None,
) -> dict[str, Any]:
    """Read the observe store and write nothing except the returned payload."""
    root = Path(repo_root)
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    observe_path = root / "docs" / "data" / OBSERVE_STORE_NAME
    observe: dict[str, Any] | None = None
    observe_error = None
    if not observe_path.is_file():
        observe_error = "missing"
    else:
        try:
            loaded = _read_json(observe_path)
        except (OSError, ValueError, TypeError) as exc:
            observe_error = str(exc)
            loaded = None
        observe = loaded if isinstance(loaded, dict) else None
        if observe is None and observe_error is None:
            observe_error = "unreadable"
    episodes_in = observe.get("episodes") if isinstance(observe, dict) else None
    if not isinstance(episodes_in, list):
        episodes_in = []
    history = fx if fx is not None else FxHistory.load(root)
    run_cache: dict[str, Any] = {}
    file_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
    rows = [
        build_episode_row(root, episode, fx=history, run_cache=run_cache, file_cache=file_cache)
        for episode in episodes_in
        if isinstance(episode, dict)
    ]
    rows.sort(key=_episode_sort)
    primary = [row for row in rows if row.get("column") == COLUMN_PRIMARY]
    by_column: dict[str, Any] = {}
    for row in rows:
        column = str(row.get("column") or "")
        by_column.setdefault(column, []).append(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "influences_live": INFLUENCES_LIVE,
        "registration_id": observe.get("registration_id")
        if isinstance(observe, dict)
        else REGISTRATION_ID,
        "generated_at": moment.astimezone(UTC).isoformat(),
        "observe_data_commit": observe.get("data_commit") if isinstance(observe, dict) else None,
        "observe_generated_at": observe.get("generated_at") if isinstance(observe, dict) else None,
        "observe_store": _rel(root, observe_path),
        "observe_error": observe_error,
        "constants": CONSTANTS,
        "fx": history.to_meta(),
        "coverage": _coverage(rows),
        "scoring": {
            "primary": score_rows(primary),
            "by_column": {
                column: score_rows(members) for column, members in sorted(by_column.items())
            },
        },
        "episodes": rows,
    }


def write_store(repo_root: Path, payload: dict[str, Any]) -> Path:
    path = store_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
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
    """Ops-monitor rows. Reads the fair-value store. Does not recompute it."""
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    path = store_path(repo_root)
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
    if not isinstance(payload, dict) or not isinstance(payload.get("coverage"), dict):
        return [
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_UNREADABLE,
                "summary": f"{path.name} has no coverage block.",
                "auto_fixable": False,
            }
        ]
    generated = _parse_generated_at(payload.get("generated_at"))
    if generated is None or moment - generated > STALE_AFTER:
        age = "missing generated_at" if generated is None else generated.date().isoformat()
        return [
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_STALE,
                "summary": (
                    f"{path.name} generated_at is {age}. "
                    f"Stale means older than {STALE_AFTER.days} days."
                ),
                "auto_fixable": False,
            }
        ]
    coverage = payload["coverage"]
    primary_median = coverage.get("primary_margin_median")
    median_text = "n/a" if primary_median is None else f"{primary_median:.3f}"
    scoring = payload.get("scoring") if isinstance(payload.get("scoring"), dict) else {}
    primary_score = scoring.get("primary") if isinstance(scoring.get("primary"), dict) else {}
    verdict = primary_score.get("verdict")
    return [
        {
            "severity": "info",
            "category": "research",
            "title": TITLE_INFO,
            "summary": (
                f"Primary episodes with a range "
                f"{coverage.get('primary_with_range')} of {coverage.get('primary_episodes')}, "
                f"insufficient_data {coverage.get('primary_insufficient_data')}, "
                f"primary median margin {median_text}. "
                f"All columns: {coverage.get('with_range')} with a range, "
                f"{coverage.get('insufficient_data')} insufficient_data. "
                f"Scoring verdict {verdict}. "
                "Observe-only; it does not change the book."
            ),
            "auto_fixable": False,
        }
    ]


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    primary = [
        {
            "ticker": row.get("ticker"),
            "column": row.get("column"),
            "verdict": row.get("verdict"),
            "reason": row.get("reason"),
            "margin_of_safety": row.get("margin_of_safety"),
            "range": row.get("range"),
            "method": row.get("method"),
            "statement_currency": row.get("statement_currency"),
            "entry_reference_price": row.get("entry_reference_price"),
        }
        for row in payload.get("episodes") or []
        if row.get("column") == COLUMN_PRIMARY
    ]
    scoring = payload.get("scoring") if isinstance(payload.get("scoring"), dict) else {}
    primary_score = scoring.get("primary") if isinstance(scoring.get("primary"), dict) else {}
    return {
        "influences_live": payload.get("influences_live"),
        "registration_id": payload.get("registration_id"),
        "generated_at": payload.get("generated_at"),
        "coverage": payload.get("coverage"),
        "scoring_verdict": primary_score.get("verdict"),
        "primary": primary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fair-value range and margin of safety for strategy-book episodes "
            "(observe-only). Does not change the book."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the summary without writing the store",
    )
    args = parser.parse_args(argv)
    payload = build_fair_value_store(args.repo_root)
    written = None
    if not args.no_write:
        written = str(write_store(args.repo_root, payload))
    summary = _summary(payload)
    summary["store"] = written
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
