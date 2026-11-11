"""EODHD UK/Europe coverage check for plan step 3.3 (observe-only).

Learning question: is EOD Historical Data good enough for a survivorship-free,
point-in-time replay of the strategy book in UK/Europe?

No raw prices, fundamentals or API responses are committed. Token from
``EODHD_API_TOKEN`` only; never logged or stored.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.constituents import fetch_ftse350_constituents
from value_investor.data_library import DEFAULT_LIBRARY_ROOT, market_dir
from value_investor.storage import read_json

DEFAULT_STORE_PATH = Path("docs/data/eodhd_coverage_check.json")
SCHEMA_VERSION = 1
API_BASE = "https://eodhd.com/api/"
DEFAULT_MAX_CALLS = 3000
DEFAULT_OUT = DEFAULT_STORE_PATH
REQUEST_TIMEOUT_SEC = 60
MAX_REQUESTS_PER_SEC = 5
MIN_INTERVAL_SEC = 1.0 / MAX_REQUESTS_PER_SEC
FUNDAMENTALS_CALL_WEIGHT = 10
TRADING_DAYS_TOLERANCE = 10

# Pass bars (fixed before any data is seen).
CHECK_A_MIN_FOUND_WITH_PRICES_TO_END = 8
CHECK_A_MIN_WITH_FUNDAMENTALS = 7
CHECK_A_TOTAL_NAMES = 11
CHECK_B_DEPTH_FROM_2013_PCT = 0.80
CHECK_B_DATED_ANNUAL_PCT = 0.70
CHECK_B_CURRENCY_PCT = 0.95
CHECK_B_SHARES_HISTORY_PCT = 0.80
CHECK_D_MARKET_CAP_COMPUTABLE_PCT = 0.80

FTSE_ACTIVE_SAMPLE_SIZE = 30
EURO_ACTIVE_SAMPLE_SIZE = 10
EURO_MARKETS = ("dax", "cac40")
MEMBERSHIP_DATES = ("2014-06-30", "2017-06-30", "2020-06-30", "2023-06-30")
FUNDAMENTALS_YEAR_FROM = 2013
FUNDAMENTALS_YEAR_TO = 2025
ANNUAL_YEAR_SPAN = tuple(range(FUNDAMENTALS_YEAR_FROM, FUNDAMENTALS_YEAR_TO + 1))

LEARNING_QUESTION = (
    "Is EODHD data for UK and European listings good enough for a survivorship-free "
    "point-in-time replay of the strategy book (plan step 3.3)?"
)

STORE_FAILED_TITLE = "EODHD coverage check store unreadable"
FINDING_TITLE = "EODHD coverage check"

PASS_BARS = {
    "check_a_min_found_with_prices_to_end": CHECK_A_MIN_FOUND_WITH_PRICES_TO_END,
    "check_a_min_with_fundamentals": CHECK_A_MIN_WITH_FUNDAMENTALS,
    "check_a_total_names": CHECK_A_TOTAL_NAMES,
    "check_b_depth_from_2013_pct": CHECK_B_DEPTH_FROM_2013_PCT,
    "check_b_dated_annual_pct": CHECK_B_DATED_ANNUAL_PCT,
    "check_b_currency_pct": CHECK_B_CURRENCY_PCT,
    "check_b_shares_history_pct": CHECK_B_SHARES_HISTORY_PCT,
    "check_d_market_cap_computable_pct": CHECK_D_MARKET_CAP_COMPUTABLE_PCT,
}

KNOWN_FAILURE_CASES: tuple[dict[str, Any], ...] = (
    {"key": "carillion", "name": "Carillion", "exchange": "LSE", "known_end": "2018-01-15"},
    {
        "key": "thomas_cook",
        "name": "Thomas Cook Group",
        "exchange": "LSE",
        "known_end": "2019-09-23",
    },
    {"key": "debenhams", "name": "Debenhams", "exchange": "LSE", "known_end": "2019-04-09"},
    {
        "key": "patisserie_holdings",
        "name": "Patisserie Holdings",
        "exchange": "LSE",
        "known_end": "2019-01-10",
    },
    {"key": "intu", "name": "intu properties", "exchange": "LSE", "known_end": "2020-06-26"},
    {"key": "sirius", "name": "Sirius Minerals", "exchange": "LSE", "known_end": "2020-03-03"},
    {"key": "gkn", "name": "GKN", "exchange": "LSE", "known_end": "2018-03-29"},
    {"key": "sky", "name": "Sky", "exchange": "LSE", "known_end": "2018-09-26"},
    {"key": "aggreko", "name": "Aggreko", "exchange": "LSE", "known_end": "2021-08-16"},
    {
        "key": "morrison",
        "name": "Wm Morrison Supermarkets",
        "exchange": "LSE",
        "known_end": "2021-10-04",
    },
    {"key": "wirecard", "name": "Wirecard", "exchange": "XETRA", "known_end": "2020-06-25"},
)

FORBIDDEN_REPORT_KEYS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
        "revenue",
        "netIncome",
        "totalAssets",
        "raw",
        "financials",
        "Income_Statement",
        "Balance_Sheet",
        "Cash_Flow",
    }
)


def redact_token(text: str, token: str | None) -> str:
    if not token:
        return text
    return text.replace(token, "***")


def _norm_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _parse_date(value: Any) -> date | None:
    if not value or value == "absent":
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _trading_days_between(start: date, end: date) -> int:
    if end < start:
        start, end = end, start
    days = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(days=1)
    return days


METRIC_FLOAT_KEYS = frozenset(
    {"annual_dated_share", "annual_period_count", "annual_periods_with_filing_or_report_date"}
)


def _safe_cell(value: Any, *, key: str = "") -> Any:
    if value is None:
        return "absent"
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if key in METRIC_FLOAT_KEYS or key.endswith("_share") or key.endswith("_count"):
            return value
        return "absent"
    if isinstance(value, list):
        return [_safe_cell(v) for v in value]
    if isinstance(value, dict):
        return {k: _safe_cell(v, key=k) for k, v in value.items() if k not in FORBIDDEN_REPORT_KEYS}
    return "absent"


class EodhdClient:
    """Minimal EODHD HTTP client with pacing, retries and call budget."""

    def __init__(
        self,
        token: str,
        *,
        max_calls: int = DEFAULT_MAX_CALLS,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.token = token
        self.max_calls = max_calls
        self.calls_used = 0
        self.budget_exhausted = False
        self._last_request_at = 0.0
        self._opener = opener or urllib.request.urlopen
        self._delisted_cache: dict[str, list[dict[str, Any]]] = {}

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_INTERVAL_SEC:
            time.sleep(MIN_INTERVAL_SEC - elapsed)

    def _count(self, weight: int = 1) -> bool:
        if self.calls_used + weight > self.max_calls:
            self.budget_exhausted = True
            return False
        self.calls_used += weight
        return True

    def get_json(self, path: str, *, params: dict[str, str] | None = None, weight: int = 1) -> Any:
        if self.budget_exhausted or not self._count(weight):
            return None
        query = {"api_token": self.token, "fmt": "json"}
        if params:
            query.update(params)
        url = API_BASE + path.lstrip("/") + "?" + urllib.parse.urlencode(query)
        last_exc: Exception | None = None
        for attempt in range(4):
            self._pace()
            try:
                with self._opener(url, timeout=REQUEST_TIMEOUT_SEC) as resp:
                    raw = resp.read().decode("utf-8")
                self._last_request_at = time.monotonic()
                return json.loads(raw)
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code in {429, 500, 502, 503, 504} and attempt < 3:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise RuntimeError(redact_token(str(exc), self.token)) from exc
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
                last_exc = exc
                if attempt < 3:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise RuntimeError(redact_token(str(exc), self.token)) from exc
            except Exception as exc:
                raise RuntimeError(redact_token(str(exc), self.token)) from exc
        raise RuntimeError(redact_token(str(last_exc), self.token))

    def exchange_symbol_list(
        self, exchange: str, *, delisted: bool = False
    ) -> list[dict[str, Any]]:
        key = f"{exchange}:{'delisted' if delisted else 'active'}"
        if key in self._delisted_cache:
            return self._delisted_cache[key]
        params = {"type": "common_stock"}
        if delisted:
            params["delisted"] = "1"
        rows = self.get_json(f"exchange-symbol-list/{exchange}", params=params)
        out = rows if isinstance(rows, list) else []
        self._delisted_cache[key] = out
        return out

    def search(self, query: str, *, exchange: str) -> list[dict[str, Any]]:
        rows = self.get_json(f"search/{urllib.parse.quote(query)}", params={"exchange": exchange})
        return rows if isinstance(rows, list) else []

    def eod(self, symbol: str, *, from_date: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if from_date:
            params["from"] = from_date
        rows = self.get_json(f"eod/{symbol}", params=params or None)
        return rows if isinstance(rows, list) else []

    def fundamentals(self, symbol: str) -> dict[str, Any] | None:
        payload = self.get_json(f"fundamentals/{symbol}", weight=FUNDAMENTALS_CALL_WEIGHT)
        return payload if isinstance(payload, dict) else None


def yahoo_to_eodhd_symbol(ticker: str, exchange: str) -> str:
    code = ticker.split(".", 1)[0].upper()
    return f"{code}.{exchange}"


def resolve_known_failure(client: EodhdClient, case: dict[str, Any]) -> dict[str, Any]:
    """Resolve a survivorship name via search then delisted list (not ticker reuse)."""
    exchange = str(case["exchange"])
    target = _norm_name(str(case["name"]))
    resolved_code = "absent"
    resolved_symbol = "absent"
    match_source = "absent"

    for row in client.search(str(case["name"]), exchange=exchange):
        if not isinstance(row, dict):
            continue
        name = _norm_name(str(row.get("Name") or row.get("name") or ""))
        code = str(row.get("Code") or row.get("code") or "").strip()
        if code and (target in name or name in target):
            resolved_code = code
            resolved_symbol = f"{code}.{exchange}"
            match_source = "search"
            break

    if resolved_code == "absent":
        for row in client.exchange_symbol_list(exchange, delisted=True):
            if not isinstance(row, dict):
                continue
            name = _norm_name(str(row.get("Name") or ""))
            if target in name or name in target:
                code = str(row.get("Code") or "").strip()
                if code:
                    resolved_code = code
                    resolved_symbol = f"{code}.{exchange}"
                    match_source = "delisted_list"
                    break

    return {
        "key": case["key"],
        "name": case["name"],
        "exchange": exchange,
        "known_end": case["known_end"],
        "found": resolved_code != "absent",
        "resolved_code": resolved_code,
        "resolved_symbol": resolved_symbol,
        "match_source": match_source,
    }


def _summarize_eod(rows: list[dict[str, Any]], *, from_year: int = 2013) -> dict[str, Any]:
    if not rows:
        return {
            "eod_first_date": "absent",
            "eod_last_date": "absent",
            "eod_from_2013": False,
            "adjusted_close_present": False,
        }
    dates: list[date] = []
    adj_present = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = _parse_date(row.get("date"))
        if d:
            dates.append(d)
        if row.get("adjusted_close") is not None:
            adj_present = True
    if not dates:
        return {
            "eod_first_date": "absent",
            "eod_last_date": "absent",
            "eod_from_2013": False,
            "adjusted_close_present": adj_present,
        }
    first, last = min(dates), max(dates)
    return {
        "eod_first_date": first.isoformat(),
        "eod_last_date": last.isoformat(),
        "eod_from_2013": first.year <= from_year,
        "adjusted_close_present": adj_present,
    }


def _annual_income_rows(fundamentals: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not fundamentals:
        return []
    fin = fundamentals.get("Financials") or {}
    income = fin.get("Income_Statement") or {}
    yearly = income.get("yearly")
    if isinstance(yearly, dict):
        return [v for v in yearly.values() if isinstance(v, dict)]
    if isinstance(yearly, list):
        return [v for v in yearly if isinstance(v, dict)]
    return []


def _fundamentals_summary(fundamentals: dict[str, Any] | None) -> dict[str, Any]:
    general = (fundamentals or {}).get("General") or {}
    currency = general.get("CurrencyCode")
    currency_code = currency if isinstance(currency, str) and currency.strip() else "absent"

    annual_rows = _annual_income_rows(fundamentals)
    years_with_data: set[int] = set()
    dated_periods = 0
    annual_periods = 0
    for row in annual_rows:
        annual_periods += 1
        label = str(row.get("date") or row.get("filing_date") or "")[:4]
        if label.isdigit():
            year = int(label)
            if year >= FUNDAMENTALS_YEAR_FROM:
                years_with_data.add(year)
        filing = row.get("filing_date") or row.get("reportDate")
        if filing:
            dated_periods += 1

    years_available = sorted(y for y in years_with_data if y >= FUNDAMENTALS_YEAR_FROM)
    dated_share = (dated_periods / annual_periods) if annual_periods else None

    shares = (fundamentals or {}).get("outstandingShares") or {}
    shares_hist = shares.get("annual") or shares.get("quarterly")
    shares_history_present = bool(shares_hist)

    earn = (fundamentals or {}).get("Earnings") or {}
    history = earn.get("History")
    if isinstance(history, dict) and history:
        shares_history_present = shares_history_present or True

    depth_from_2013 = bool(years_available) and min(years_available) <= FUNDAMENTALS_YEAR_FROM

    return {
        "fundamentals_years_from_2013": years_available or "absent",
        "fundamentals_depth_from_2013": depth_from_2013,
        "annual_period_count": annual_periods,
        "annual_periods_with_filing_or_report_date": dated_periods,
        "annual_dated_share": round(dated_share, 4) if dated_share is not None else "absent",
        "currency_code": currency_code,
        "shares_outstanding_history_present": shares_history_present,
    }


def _prices_to_known_end(eod_last: Any, known_end: str) -> bool:
    last = _parse_date(eod_last)
    end = _parse_date(known_end)
    if not last or not end:
        return False
    gap = _trading_days_between(last, end)
    return gap <= TRADING_DAYS_TOLERANCE


def _load_library_constituents(
    library_root: Path, market_id: str, *, limit: int
) -> list[dict[str, str]]:
    path = market_dir(library_root, market_id) / "constituents" / "latest.json"
    rows = read_json(path) if path.exists() else []
    out: list[dict[str, str]] = []
    if not isinstance(rows, list):
        return out
    for row in sorted(rows, key=lambda r: str(r.get("ticker") or "")):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        name = str(row.get("name") or ticker).strip()
        if ticker:
            out.append({"ticker": ticker, "name": name, "market": market_id})
        if len(out) >= limit:
            break
    return out


def active_sample_names(library_root: Path = DEFAULT_LIBRARY_ROOT) -> list[dict[str, str]]:
    frame = fetch_ftse350_constituents()
    ftse: list[dict[str, str]] = []
    for _, row in frame.sort_values("ticker").head(FTSE_ACTIVE_SAMPLE_SIZE).iterrows():
        ftse.append(
            {
                "ticker": str(row["ticker"]),
                "name": str(row.get("name") or row["ticker"]),
                "market": "ftse350",
                "exchange": "LSE",
            }
        )
    euro: list[dict[str, str]] = []
    per_market = EURO_ACTIVE_SAMPLE_SIZE // len(EURO_MARKETS)
    exchange_by_market = {"dax": "XETRA", "cac40": "PA"}
    for market_id in EURO_MARKETS:
        chunk = _load_library_constituents(library_root, market_id, limit=per_market)
        for row in chunk:
            euro.append({**row, "exchange": exchange_by_market[market_id]})
    return ftse + euro


def _evaluate_active_row(
    client: EodhdClient, row: dict[str, str]
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    exchange = str(row["exchange"])
    symbol = yahoo_to_eodhd_symbol(str(row["ticker"]), exchange)
    eod_rows = client.eod(symbol, from_date=f"{FUNDAMENTALS_YEAR_FROM}-01-01")
    fundamentals = client.fundamentals(symbol)
    eod = _summarize_eod(eod_rows)
    fund = _fundamentals_summary(fundamentals)
    summary = {
        "ticker": row["ticker"],
        "name": row["name"],
        "market": row.get("market", "absent"),
        "exchange": exchange,
        "symbol": symbol,
        "currency_code_present": fund["currency_code"] not in ("absent", ""),
        **eod,
        **fund,
    }
    return summary, eod_rows, fundamentals


def _shares_on_or_before(fundamentals: dict[str, Any] | None, as_of: date) -> bool:
    if not fundamentals:
        return False
    shares = fundamentals.get("outstandingShares") or {}
    candidates: list[date] = []
    for bucket in ("quarterly", "annual"):
        block = shares.get(bucket)
        if not isinstance(block, dict):
            continue
        for key, row in block.items():
            if not isinstance(row, dict):
                continue
            d = _parse_date(row.get("date") or key)
            if d and d <= as_of and row.get("shares") is not None:
                candidates.append(d)
    return bool(candidates)


def _close_on_or_before(eod_rows: list[dict[str, Any]], as_of: date) -> bool:
    best: date | None = None
    for row in eod_rows:
        if not isinstance(row, dict):
            continue
        d = _parse_date(row.get("date"))
        if d and d <= as_of and row.get("close") is not None:
            if best is None or d > best:
                best = d
    return best is not None


def _share_pass(
    rows: list[dict[str, Any]], key: str, threshold: float
) -> tuple[bool, float | None]:
    if not rows:
        return False, None
    good = sum(1 for r in rows if r.get(key) is True)
    share = good / len(rows)
    return share >= threshold, round(share, 4)


def _dated_share_pass(rows: list[dict[str, Any]], threshold: float) -> tuple[bool, float | None]:
    scored = [
        r
        for r in rows
        if isinstance(r.get("annual_dated_share"), (int, float)) and r.get("annual_period_count", 0)
    ]
    if not scored:
        return False, None
    avg = sum(float(r["annual_dated_share"]) for r in scored) / len(scored)
    return avg >= threshold, round(avg, 4)


def compute_verdict(
    check_a: dict[str, Any],
    check_b: dict[str, Any],
    check_d: dict[str, Any],
    *,
    budget_exhausted: bool = False,
) -> dict[str, Any]:
    reasons: list[str] = []
    if budget_exhausted:
        reasons.append("API call budget exhausted before checks completed")

    a_pass = check_a.get("pass") is True
    b_pass = check_b.get("pass") is True
    d_pass = check_d.get("pass") is True

    if not a_pass:
        for key in ("found_with_prices_to_end", "with_fundamentals"):
            short = check_a.get(f"shortfall_{key}")
            if short:
                reasons.append(short)
    if not b_pass:
        for key in ("depth", "dated", "currency", "shares"):
            short = check_b.get(f"shortfall_{key}")
            if short:
                reasons.append(short)
    if not d_pass and check_d.get("shortfall"):
        reasons.append(str(check_d["shortfall"]))

    if budget_exhausted:
        verdict = "partial"
    elif a_pass and b_pass and d_pass:
        verdict = "pass"
    elif a_pass:
        verdict = "partial"
    else:
        verdict = "fail"

    return {"verdict": verdict, "reasons": reasons}


def run_eodhd_coverage_check(
    client: EodhdClient,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    # Check C — universe breadth (LSE only, report-only).
    lse_active = client.exchange_symbol_list("LSE", delisted=False)
    lse_delisted = client.exchange_symbol_list("LSE", delisted=True)
    check_c = {
        "lse_active_common_stock_count": len(lse_active),
        "lse_delisted_common_stock_count": len(lse_delisted),
    }

    # Check A — known failures.
    survivorship_rows: list[dict[str, Any]] = []
    for case in KNOWN_FAILURE_CASES:
        if client.budget_exhausted:
            break
        base = resolve_known_failure(client, case)
        if base["found"] and base["resolved_symbol"] != "absent":
            eod_rows = client.eod(str(base["resolved_symbol"]), from_date="2005-01-01")
            fundamentals = client.fundamentals(str(base["resolved_symbol"]))
            eod = _summarize_eod(eod_rows)
            fund = _fundamentals_summary(fundamentals)
            base.update(eod)
            base.update(fund)
            base["prices_to_known_end"] = _prices_to_known_end(
                eod["eod_last_date"], case["known_end"]
            )
            base["has_fundamentals"] = fund["fundamentals_depth_from_2013"] is True
        else:
            base.update(
                {
                    "eod_first_date": "absent",
                    "eod_last_date": "absent",
                    "prices_to_known_end": False,
                    "adjusted_close_present": False,
                    "has_fundamentals": False,
                    "fundamentals_depth_from_2013": False,
                }
            )
        survivorship_rows.append(_safe_cell(base))

    found_with_end = sum(1 for r in survivorship_rows if r.get("prices_to_known_end"))
    with_fund = sum(1 for r in survivorship_rows if r.get("has_fundamentals"))
    a_prices_ok = found_with_end >= CHECK_A_MIN_FOUND_WITH_PRICES_TO_END
    a_fund_ok = with_fund >= CHECK_A_MIN_WITH_FUNDAMENTALS
    check_a: dict[str, Any] = {
        "rows": survivorship_rows,
        "found_with_prices_to_end_count": found_with_end,
        "with_fundamentals_count": with_fund,
        "pass_prices_to_end": a_prices_ok,
        "pass_fundamentals": a_fund_ok,
        "pass": a_prices_ok and a_fund_ok,
    }
    if not a_prices_ok:
        check_a["shortfall_found_with_prices_to_end"] = (
            f"Check A: only {found_with_end} of {CHECK_A_TOTAL_NAMES} names have prices "
            f"within {TRADING_DAYS_TOLERANCE} trading days of the known end "
            f"(need {CHECK_A_MIN_FOUND_WITH_PRICES_TO_END})."
        )
    if not a_fund_ok:
        check_a["shortfall_with_fundamentals"] = (
            f"Check A: only {with_fund} of {CHECK_A_TOTAL_NAMES} names have fundamentals "
            f"depth from {FUNDAMENTALS_YEAR_FROM} (need {CHECK_A_MIN_WITH_FUNDAMENTALS})."
        )

    # Check B — active sample.
    active_rows: list[dict[str, Any]] = []
    sample = active_sample_names(library_root)
    fundamentals_by_symbol: dict[str, dict[str, Any] | None] = {}
    eod_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in sample:
        if client.budget_exhausted:
            break
        evaluated, eod_rows, fundamentals = _evaluate_active_row(client, row)
        active_rows.append(_safe_cell(evaluated))
        sym = str(evaluated["symbol"])
        eod_by_symbol[sym] = eod_rows
        fundamentals_by_symbol[sym] = fundamentals

    depth_ok, depth_share = _share_pass(
        active_rows, "fundamentals_depth_from_2013", CHECK_B_DEPTH_FROM_2013_PCT
    )
    dated_ok, dated_share = _dated_share_pass(active_rows, CHECK_B_DATED_ANNUAL_PCT)
    currency_ok, currency_share = _share_pass(
        active_rows, "currency_code_present", CHECK_B_CURRENCY_PCT
    )
    shares_ok, shares_share = _share_pass(
        active_rows, "shares_outstanding_history_present", CHECK_B_SHARES_HISTORY_PCT
    )
    eod_ok, eod_share = _share_pass(active_rows, "eod_from_2013", CHECK_B_DEPTH_FROM_2013_PCT)

    b_pass = depth_ok and dated_ok and currency_ok and shares_ok and eod_ok
    check_b: dict[str, Any] = {
        "sample_sources": {
            "ftse350": "value_investor.constituents.fetch_ftse350_constituents",
            "euro": "docs/data/library/markets/{dax,cac40}/constituents/latest.json",
        },
        "sample_size": len(active_rows),
        "shares": {
            "depth_from_2013": depth_share,
            "eod_from_2013": eod_share,
            "dated_annual_periods": dated_share,
            "currency_code": currency_share,
            "shares_history": shares_share,
        },
        "pass": b_pass,
        "rows": active_rows,
    }
    if not depth_ok or not eod_ok:
        check_b["shortfall_depth"] = (
            f"Check B: fundamentals or EOD depth from {FUNDAMENTALS_YEAR_FROM} on "
            f"{depth_share or 0:.0%} / {eod_share or 0:.0%} of the sample (need "
            f"{CHECK_B_DEPTH_FROM_2013_PCT:.0%})."
        )
    if not dated_ok:
        check_b["shortfall_dated"] = (
            f"Check B: annual periods with filing/report dates average "
            f"{dated_share or 0:.0%} (need {CHECK_B_DATED_ANNUAL_PCT:.0%})."
        )
    if not currency_ok:
        check_b["shortfall_currency"] = (
            f"Check B: currency code present on {currency_share or 0:.0%} "
            f"(need {CHECK_B_CURRENCY_PCT:.0%})."
        )
    if not shares_ok:
        check_b["shortfall_shares"] = (
            f"Check B: shares-outstanding history on {shares_share or 0:.0%} "
            f"(need {CHECK_B_SHARES_HISTORY_PCT:.0%})."
        )

    # Check D — membership feasibility on sample (reuse in-memory fetches).
    d_rows: list[dict[str, Any]] = []
    for as_of_s in MEMBERSHIP_DATES:
        as_of = date.fromisoformat(as_of_s)
        computable = 0
        considered = 0
        for row in active_rows:
            sym = str(row.get("symbol") or "")
            if not sym or sym == "absent":
                continue
            considered += 1
            eod_rows = eod_by_symbol.get(sym) or []
            fund = fundamentals_by_symbol.get(sym)
            if _close_on_or_before(eod_rows, as_of) and _shares_on_or_before(fund, as_of):
                computable += 1
        share = (computable / considered) if considered else None
        d_rows.append(
            {
                "as_of": as_of_s,
                "computable_count": computable,
                "sample_count": considered,
                "computable_share": round(share, 4) if share is not None else "absent",
            }
        )
    d_shares = [
        r["computable_share"] for r in d_rows if isinstance(r["computable_share"], (int, float))
    ]
    d_avg = sum(d_shares) / len(d_shares) if d_shares else 0.0
    d_pass = d_avg >= CHECK_D_MARKET_CAP_COMPUTABLE_PCT
    check_d: dict[str, Any] = {
        "rows": d_rows,
        "mean_computable_share": round(d_avg, 4),
        "pass": d_pass,
    }
    if not d_pass:
        check_d["shortfall"] = (
            f"Check D: close × shares computable on average {d_avg:.0%} of membership dates "
            f"(need {CHECK_D_MARKET_CAP_COMPUTABLE_PCT:.0%})."
        )

    verdict_block = compute_verdict(
        check_a, check_b, check_d, budget_exhausted=client.budget_exhausted
    )

    estimated_calls = (
        2  # LSE active + delisted counts
        + 1  # XETRA delisted list for Wirecard resolution
        + sum(2 + 1 + FUNDAMENTALS_CALL_WEIGHT for _ in KNOWN_FAILURE_CASES)  # search, eod, fund
        + len(sample) * (1 + FUNDAMENTALS_CALL_WEIGHT)
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "learning_question": LEARNING_QUESTION,
        "observe_only": True,
        "influences_live": False,
        "pass_bars": PASS_BARS,
        "calls_used": client.calls_used,
        "max_calls": client.max_calls,
        "budget_exhausted": client.budget_exhausted,
        "estimated_calls_full_run": estimated_calls,
        "verdict": verdict_block["verdict"],
        "reasons": verdict_block["reasons"],
        "checks": {
            "a_survivorship": check_a,
            "b_active_sample": check_b,
            "c_universe_breadth": check_c,
            "d_membership_feasibility": check_d,
        },
    }


def assert_report_has_no_licensed_numbers(payload: dict[str, Any]) -> None:
    """Raise if forbidden numeric price/fundamental fields appear in the serialised store."""

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key in FORBIDDEN_REPORT_KEYS:
                    raise ValueError(f"Forbidden licensed field at {path}.{key}")
                walk(val, f"{path}.{key}")
        elif isinstance(obj, list):
            for idx, val in enumerate(obj):
                walk(val, f"{path}[{idx}]")

    walk(payload, "root")


def write_report(payload: dict[str, Any], path: Path = DEFAULT_STORE_PATH) -> None:
    assert_report_has_no_licensed_numbers(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_report(path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ops_findings_from_eodhd_coverage(
    payload: dict[str, Any] | None,
    *,
    path: Path = DEFAULT_STORE_PATH,
) -> list[dict[str, Any]]:
    if not payload:
        return []
    verdict = str(payload.get("verdict") or "absent")
    generated = str(payload.get("generated_at") or "")[:10]
    summary = (
        f"EODHD coverage check verdict {verdict} "
        f"(generated {generated or 'unknown'}). "
        f"Calls used {payload.get('calls_used')}/{payload.get('max_calls')}. "
        "See docs/ops/eodhd-coverage-check.md."
    )
    if payload.get("reasons"):
        summary += " " + "; ".join(str(r) for r in payload["reasons"][:3])
    return [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": summary,
            "auto_fixable": False,
        }
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EODHD UK/Europe coverage check (step 3.3).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Report JSON path")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument(
        "--library-root",
        type=Path,
        default=DEFAULT_LIBRARY_ROOT,
        help="Library root for euro constituent lists",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("EODHD_API_TOKEN", "").strip()
    if not token:
        print(
            "EODHD_API_TOKEN is not set; coverage check skipped (no file written).", file=sys.stderr
        )
        return 0

    client = EodhdClient(token, max_calls=args.max_calls)
    try:
        payload = run_eodhd_coverage_check(client, library_root=args.library_root)
        write_report(payload, args.out)
    except Exception as exc:
        msg = redact_token(str(exc), token)
        print(f"EODHD coverage check failed: {msg}", file=sys.stderr)
        return 1
    print(f"Wrote {args.out} — verdict {payload.get('verdict')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
