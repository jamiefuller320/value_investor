"""Mirror strategy-book primary orders onto the Trading 212 practice account.

Observe-only. The ledger never feeds the book, its scores, the registration,
or a knob. Order HTTP is allowed only against the demo host, and only with
``TRADING212_DEMO_API_KEY`` / ``TRADING212_DEMO_API_SECRET``.

See ``docs/ops/strategy-book-demo-mirror.md``.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import math
import re
import ssl
import time
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from value_investor.market_trading_costs import costs_for_market
from value_investor.strategy_book_rules import (
    STAKE_UNITS,
    T212_CATALOGUE_MAX_AGE_DAYS,
    UnknownMarketClose,
    session_close,
)
from value_investor.t212_client import DEMO_BASE

logger = logging.getLogger(__name__)

INSTRUMENT_ID = "strategy-book-demo-mirror-v0"
STORE_NAME = "strategy_book_demo_ledger.json"
SCHEMA_VERSION = 1
PRIMARY = "primary"
ORDER_CAP = 20
DEMO_KEY_ENV = "TRADING212_DEMO_API_KEY"
DEMO_SECRET_ENV = "TRADING212_DEMO_API_SECRET"
DEMO_HOST = "demo.trading212.com"
TIME_VALIDITY = "GOOD_TILL_CANCEL"
QTY_QUANTUM = Decimal("0.0001")
PRICE_QUANTUM = Decimal("0.0001")
QTY_TOLERANCE = 1e-4
CASH_TOLERANCE = 0.01
# GBP stake versus a GBX (pence) quote. No other cross-rate is applied.
_MINOR_UNITS = {("GBP", "GBX"): Decimal("100")}
_NO_RETRY = frozenset(
    {
        "submitting",
        "submit_unknown",
        "placed",
        "partial",
        "filled",
        "rejected",
        "cancelled",
        "cancelling",
    }
)
_CORPORATE_FILL_TYPES = frozenset(
    {
        "STOCK_SPLIT",
        "STOCK_DISTRIBUTION",
        "FOP",
        "FOP_CORRECTION",
        "CUSTOM_STOCK_DISTRIBUTION",
        "EQUITY_RIGHTS",
        "SCRIP_STOCK_DIVIDENDS",
        "STOCK_DIVIDENDS",
        "STOCK_ACQUISITION",
        "CASH_AND_STOCK_ACQUISITION",
        "SPIN_OFF",
    }
)

TITLE_NOT_CONFIGURED = "Strategy book demo mirror not configured"
TITLE_ORDERS_PLACED = "Strategy book demo orders placed"
TITLE_MISMATCH = "Strategy book demo reconciliation mismatch"
TITLE_SLIPPAGE = "Strategy book demo slippage"

_LIMIT_PATH = "/api/v0/equity/orders/limit"
_ORDERS_PATH = "/api/v0/equity/orders"
_POSITIONS_PATH = "/api/v0/equity/positions"
_HISTORY_ORDERS = "/api/v0/equity/history/orders"
_HISTORY_DIVIDENDS = "/api/v0/equity/history/dividends"
_HISTORY_TRANSACTIONS = "/api/v0/equity/history/transactions"
_ACCOUNT_SUMMARY = "/api/v0/equity/account/summary"


class DemoMirrorSafetyError(RuntimeError):
    """Placement refused before an order request. The live host is never used."""


class DemoOrderRejected(RuntimeError):
    """The demo host rejected the order. It was not accepted."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class DemoAuthError(DemoMirrorSafetyError):
    """401/403. The order was not accepted. Later runs may try again."""


class DemoTransportError(RuntimeError):
    """Network, timeout, or rate limit. The order may or may not exist."""


class _RefuseRedirect(HTTPRedirectHandler):
    """Never follow a redirect. A demo call must not land on the live host."""

    def redirect_request(  # type: ignore[override]
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise DemoMirrorSafetyError(f"refusing redirect ({code}) to {newurl}")


def _require_demo_transport(transport: Any) -> str:
    base = getattr(transport, "base", None)
    if not isinstance(base, str) or not base.strip():
        raise DemoMirrorSafetyError("refusing order transport: no base URL")
    return demo_base_url(base)


def demo_base_url(base: str | None = None) -> str:
    """Return the demo origin, or raise. Live and any other host are refused."""
    raw = (DEMO_BASE if base is None else base).strip()
    from urllib.parse import urlsplit

    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host != DEMO_HOST:
        raise DemoMirrorSafetyError(f"refusing order transport: host {host!r} is not {DEMO_HOST}")
    if parts.port not in (None, 443):
        raise DemoMirrorSafetyError("refusing order transport: unexpected port")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise DemoMirrorSafetyError("refusing order transport: unexpected base URL")
    if parts.path not in ("", "/"):
        raise DemoMirrorSafetyError("refusing order transport: unexpected base path")
    return f"https://{DEMO_HOST}"


def demo_credentials(env: Mapping[str, str] | None = None) -> tuple[str, str] | None:
    """Demo key pair, or None when either value is missing.

    Reads only the demo secret names. A missing key is a dry run, not an error.
    """
    source: Mapping[str, str] = env if env is not None else _os_environ()
    key = str(source.get(DEMO_KEY_ENV, "") or "").strip()
    secret = str(source.get(DEMO_SECRET_ENV, "") or "").strip()
    if not key or not secret:
        return None
    return key, secret


def _os_environ() -> Mapping[str, str]:
    import os

    return os.environ


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _parse_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _chart_filename(ticker: str) -> str:
    """Same slug as ``price_charts.chart_filename``."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", ticker) + ".json"


def next_weekday(day: date) -> date:
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def window_open(market: str, fill_session: Any, now: datetime) -> bool | None:
    """True while ``now`` is still at or before the fill session's cash close.

    None when the market has no registered close. Callers fail closed.
    """
    day = _parse_day(fill_session)
    if day is None:
        return None
    try:
        close_at = session_close(str(market or ""), day)
    except UnknownMarketClose:
        return None
    return _aware(now) <= close_at


def round_price(value: float) -> float:
    return float(Decimal(str(value)).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP))


def share_quantity(
    stake: float,
    price: float,
    stake_currency: str,
    price_currency: str,
) -> tuple[float | None, str | None]:
    """Floored share count, or ``(None, reason)`` when the currencies do not match."""
    stake_ccy = str(stake_currency or "").upper()
    price_ccy = str(price_currency or "").upper()
    level = _positive(price)
    notional = _positive(stake)
    if level is None or notional is None:
        return None, "insufficient_data"
    if stake_ccy == price_ccy:
        minor = Decimal("1")
    else:
        minor = _MINOR_UNITS.get((stake_ccy, price_ccy))
        if minor is None:
            return None, "currency_mismatch"
    raw = Decimal(str(notional)) * minor / Decimal(str(level))
    qty = raw.quantize(QTY_QUANTUM, rounding=ROUND_DOWN)
    if qty <= 0:
        return None, "quantity_below_minimum"
    return float(qty), None


def floor_shares(value: float) -> float | None:
    number = _positive(value)
    if number is None:
        return None
    qty = Decimal(str(number)).quantize(QTY_QUANTUM, rounding=ROUND_DOWN)
    if qty <= 0:
        return None
    return float(qty)


def account_accepts(account_currency: str, instrument_currency: str) -> bool:
    """True when the practice account can trade this instrument currency.

    A GBP account may trade GBX names (London pence quotes). No FX rate is applied.
    """
    account = str(account_currency or "").upper()
    instrument = str(instrument_currency or "").upper()
    if not account or not instrument:
        return False
    if account == instrument:
        return True
    return account == "GBP" and instrument == "GBX"


def compute_slippage(
    *,
    side: str,
    raw_price: Any,
    book_price: Any,
    half_spread: Any,
) -> dict[str, Any]:
    """Price slippage of a raw fill versus the book's adjusted close.

    Positive means worse than the book (paid more, or sold for less).
    """
    raw = _positive(raw_price)
    book = _positive(book_price)
    if raw is None or book is None:
        return {"status": "insufficient_data", "price_basis": "raw_fill_vs_book_adjusted_close"}
    side_name = str(side or "").upper()
    if side_name == "BUY":
        pct = raw / book - 1.0
        per_share = raw - book
    elif side_name == "SELL":
        pct = 1.0 - (raw / book)
        per_share = book - raw
    else:
        return {"status": "insufficient_data", "price_basis": "raw_fill_vs_book_adjusted_close"}
    spread = _positive(half_spread)
    if spread is None:
        try:
            spread_value = float(half_spread)
        except (TypeError, ValueError):
            spread_value = None
        else:
            spread_value = (
                spread_value if math.isfinite(spread_value) and spread_value >= 0 else None
            )
    else:
        spread_value = spread
    return {
        "status": "measured",
        "slippage_pct": pct,
        "slippage_per_share": per_share,
        "half_spread": spread_value,
        "vs_half_spread": None if spread_value is None else pct - spread_value,
        "raw_price": raw,
        "book_price": book,
        "price_basis": "raw_fill_vs_book_adjusted_close",
    }


def client_order_ref(episode_id: str, leg: str) -> str:
    return f"sbdemo:{episode_id}:{leg}"


def ledger_path(repo_root: Path) -> Path:
    return Path(repo_root) / "docs" / "data" / STORE_NAME


def load_ledger(repo_root: Path) -> dict[str, Any] | None:
    path = ledger_path(repo_root)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{STORE_NAME} is not an object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _overlay_index(repo_root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    root = Path(repo_root) / "docs" / "data" / "library" / "t212_coverage" / "by_market"
    found: dict[tuple[str, str], dict[str, Any]] = {}
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*.json")):
        payload = _read_json(path)
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            continue
        market = path.stem
        for row in rows:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "")
            if ticker and (market, ticker) not in found:
                found[(market, ticker)] = row
    return found


def _listing_decision(row: dict[str, Any] | None, on_day: date) -> tuple[str, str | None]:
    if not row:
        return "unmapped", "unmapped_instrument"
    updated = _parse_day(row.get("updated_at"))
    if updated is None:
        return "unknown", "t212_unknown"
    if (on_day - updated).days > T212_CATALOGUE_MAX_AGE_DAYS:
        return "unknown", "t212_unknown"
    basis = str(row.get("basis") or row.get("broker_basis") or "")
    tradable = row.get("tradable_on_t212")
    ticker = str(row.get("t212_ticker") or "").strip()
    if basis != "catalogue_hit" or tradable is not True:
        return "not_listed", "not_listed"
    if not ticker:
        return "unmapped", "unmapped_instrument"
    return "mirror", None


def _signal_close(repo_root: Path, ticker: str, session: date) -> dict[str, Any]:
    path = Path(repo_root) / "docs" / "data" / "charts" / _chart_filename(ticker)
    if not path.is_file():
        return {"status": "insufficient_data", "reason": "no_chart"}
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return {"status": "insufficient_data", "reason": "no_chart"}
    dates = payload.get("dates") if isinstance(payload.get("dates"), list) else []
    closes = payload.get("closes") if isinstance(payload.get("closes"), list) else []
    last = str(dates[-1])[:10] if dates else None
    token = session.isoformat()
    close: float | None = None
    for day, value in zip(dates, closes, strict=False):
        if str(day)[:10] == token:
            close = _positive(value)
    if close is None:
        if last is not None and last < token:
            return {"status": "not_mirrored", "reason": "stale_quote", "chart_last": last}
        return {"status": "insufficient_data", "reason": "no_signal_close", "chart_last": last}
    return {
        "status": "ok",
        "close": close,
        "currency_label": payload.get("currency"),
        "as_of": payload.get("as_of"),
        "chart_last": last,
    }


def _blank_plan(
    *,
    episode_id: str,
    leg: str,
    market: str,
    ticker: str,
    column: str,
    signal_session: str | None,
    observe_data_commit: Any,
    planned_at: str,
) -> dict[str, Any]:
    return {
        "client_order_ref": client_order_ref(episode_id, leg),
        "episode_id": episode_id,
        "leg": leg,
        "action": "not_mirrored",
        "reason": None,
        "column": column,
        "market": market,
        "ticker": ticker,
        "signal_session": signal_session,
        "fill_session": None,
        "side": "BUY" if leg == "entry" else "SELL",
        "order_type": "LIMIT",
        "time_validity": TIME_VALIDITY,
        "t212_ticker": None,
        "t212_listed": None,
        "currency": None,
        "instrument_currency": None,
        "stake": None,
        "limit_price": None,
        "limit_currency": None,
        "quantity": None,
        "half_spread": None,
        "chart_close": None,
        "chart_currency_label": None,
        "chart_as_of": None,
        "price_basis": None,
        "observe_data_commit": observe_data_commit,
        "planned_at": planned_at,
        "broker_order_id": None,
        "influences_live": False,
    }


def _plan_candidate(
    *,
    repo_root: Path,
    overlay: dict[tuple[str, str], dict[str, Any]],
    episode_id: str,
    leg: str,
    market: str,
    ticker: str,
    column: str,
    signal_session: str | None,
    listed_override: Any,
    observe_data_commit: Any,
    now: datetime,
) -> dict[str, Any]:
    planned_at = _aware(now).isoformat()
    plan = _blank_plan(
        episode_id=episode_id,
        leg=leg,
        market=market,
        ticker=ticker,
        column=column,
        signal_session=signal_session,
        observe_data_commit=observe_data_commit,
        planned_at=planned_at,
    )
    if column != PRIMARY:
        plan["reason"] = "not_primary"
        return plan
    signal_day = _parse_day(signal_session)
    if not market or not ticker or signal_day is None:
        plan["action"] = "insufficient_data"
        plan["reason"] = "insufficient_data"
        return plan
    plan["signal_session"] = signal_day.isoformat()
    if listed_override is False:
        plan["t212_listed"] = False
        plan["reason"] = "not_listed"
        return plan
    if listed_override is not None and listed_override is not True:
        plan["t212_listed"] = listed_override
        plan["reason"] = "t212_unknown"
        return plan
    row = overlay.get((market, ticker))
    state, reason = _listing_decision(row, signal_day)
    if listed_override is True and state != "mirror":
        plan["t212_listed"] = True
        plan["reason"] = "unmapped_instrument" if state != "not_listed" else "not_listed"
        if state == "unknown":
            plan["reason"] = "t212_unknown"
        return plan
    if state != "mirror" or row is None:
        plan["t212_listed"] = False if state == "not_listed" else "unknown"
        plan["reason"] = reason
        return plan
    plan["t212_listed"] = True
    plan["t212_ticker"] = str(row.get("t212_ticker") or "").strip()
    plan["instrument_currency"] = str(row.get("t212_currency") or "").upper() or None
    plan["limit_currency"] = plan["instrument_currency"]
    costs = costs_for_market(market)
    plan["currency"] = costs.currency
    plan["stake"] = float(STAKE_UNITS)
    plan["half_spread"] = float(costs.half_spread)
    fill_day = next_weekday(signal_day)
    plan["fill_session"] = fill_day.isoformat()
    quote = _signal_close(repo_root, ticker, signal_day)
    plan["chart_as_of"] = quote.get("as_of")
    plan["chart_currency_label"] = quote.get("currency_label")
    if quote.get("status") != "ok":
        plan["action"] = str(quote.get("status") or "insufficient_data")
        plan["reason"] = quote.get("reason")
        return plan
    plan["chart_close"] = quote["close"]
    plan["limit_price"] = round_price(float(quote["close"]))
    plan["price_basis"] = "signal_session_chart_close_as_instrument_currency"
    open_now = window_open(market, fill_day, now)
    if open_now is None:
        plan["action"] = "insufficient_data"
        plan["reason"] = "no_session_close"
        return plan
    if not open_now:
        plan["reason"] = "missed_fill_session"
        return plan
    if leg == "exit":
        plan["action"] = "would_place"
        plan["reason"] = None
        return plan
    qty, qty_reason = share_quantity(
        float(STAKE_UNITS),
        float(plan["limit_price"]),
        str(costs.currency),
        str(plan["instrument_currency"] or ""),
    )
    if qty is None:
        plan["reason"] = qty_reason
        if qty_reason == "insufficient_data":
            plan["action"] = "insufficient_data"
        return plan
    plan["quantity"] = qty
    plan["action"] = "would_place"
    plan["reason"] = None
    return plan


def _episode_id(market: str, ticker: str, column: str, signal_session: str) -> str:
    return f"{market}:{ticker}:{column}:{signal_session}"


def build_plans(
    repo_root: Path,
    observe: Mapping[str, Any],
    now: datetime,
    *,
    overlay: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Plan rows for pending entries and pending exits. Does not place orders."""
    root = Path(repo_root)
    listing = overlay if overlay is not None else _overlay_index(root)
    commit = observe.get("data_commit")
    plans: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(plan: dict[str, Any]) -> None:
        ref = str(plan.get("client_order_ref") or "")
        if not ref or ref in seen:
            return
        seen.add(ref)
        plans.append(plan)

    events = observe.get("events") if isinstance(observe.get("events"), list) else []
    episodes = observe.get("episodes") if isinstance(observe.get("episodes"), list) else []
    open_ids = {
        str(row.get("episode_id") or "")
        for row in episodes
        if isinstance(row, dict) and str(row.get("status") or "") in {"open", "closed"}
    }
    for event in events:
        if not isinstance(event, dict) or event.get("kind") != "pending_fill":
            continue
        market = str(event.get("market") or "")
        ticker = str(event.get("ticker") or "")
        column = str(event.get("column") or "")
        signal = str(event.get("session") or "")[:10] or None
        episode_id = _episode_id(market, ticker, column, signal or "")
        if episode_id in open_ids:
            add(
                {
                    "client_order_ref": client_order_ref(episode_id, "entry"),
                    "episode_id": episode_id,
                    "leg": "entry",
                    "action": "not_mirrored",
                    "reason": "already_open",
                    "market": market,
                    "ticker": ticker,
                    "column": column,
                    "signal_session": signal,
                    "side": "BUY",
                    "observe_data_commit": commit,
                    "planned_at": _aware(now).isoformat(),
                    "influences_live": False,
                }
            )
            continue
        add(
            _plan_candidate(
                repo_root=root,
                overlay=listing,
                episode_id=episode_id,
                leg="entry",
                market=market,
                ticker=ticker,
                column=column,
                signal_session=signal,
                listed_override=None,
                observe_data_commit=commit,
                now=now,
            )
        )

    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        market = str(episode.get("market") or "")
        ticker = str(episode.get("ticker") or "")
        column = str(episode.get("column") or "")
        signal = str(episode.get("signal_session") or "")[:10] or None
        episode_id = str(
            episode.get("episode_id") or _episode_id(market, ticker, column, signal or "")
        )
        listed = episode.get("t212_listed") if "t212_listed" in episode else None
        if episode.get("status") == "pending_fill":
            add(
                _plan_candidate(
                    repo_root=root,
                    overlay=listing,
                    episode_id=episode_id,
                    leg="entry",
                    market=market,
                    ticker=ticker,
                    column=column,
                    signal_session=signal,
                    listed_override=listed,
                    observe_data_commit=commit,
                    now=now,
                )
            )
        if episode.get("pending_exit"):
            exit_signal = str(episode.get("exit_signal_session") or "")[:10] or signal
            add(
                _plan_candidate(
                    repo_root=root,
                    overlay=listing,
                    episode_id=episode_id,
                    leg="exit",
                    market=market,
                    ticker=ticker,
                    column=column,
                    signal_session=exit_signal,
                    listed_override=listed,
                    observe_data_commit=commit,
                    now=now,
                )
            )
    return plans


def ledger_quantities(events: list[dict[str, Any]]) -> dict[str, float]:
    """Share balance by Trading 212 ticker. Delistings do not change the quantity."""
    qty: dict[str, float] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        ticker = str(event.get("t212_ticker") or "")
        if not ticker:
            continue
        kind = str(event.get("type") or "")
        if kind == "fill":
            shares = _positive(event.get("quantity"))
            if shares is None:
                continue
            sign = 1.0 if str(event.get("side") or "").upper() == "BUY" else -1.0
            qty[ticker] = qty.get(ticker, 0.0) + sign * shares
        elif kind in {"split", "corporate_action"} and event.get("quantity") is not None:
            try:
                qty[ticker] = qty.get(ticker, 0.0) + float(event["quantity"])
            except (TypeError, ValueError):
                continue
    return qty


def attach_exit_quantities(plans: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    held = ledger_quantities(events)
    for plan in plans:
        if plan.get("leg") != "exit" or plan.get("action") != "would_place":
            continue
        ticker = str(plan.get("t212_ticker") or "")
        qty = floor_shares(held.get(ticker, 0.0))
        if qty is None:
            plan["action"] = "not_mirrored"
            plan["reason"] = "no_demo_position"
            plan["quantity"] = None
            continue
        plan["quantity"] = qty


def apply_order_cap(plans: list[dict[str, Any]], order_cap: int | None = None) -> int:
    """Mark placeable rows past the hard cap as ``capped``. Returns the cap used."""
    requested = ORDER_CAP if order_cap is None else int(order_cap)
    cap = max(0, min(requested, ORDER_CAP))
    placeable = [plan for plan in plans if plan.get("action") == "would_place"]
    placeable.sort(
        key=lambda plan: (
            0 if plan.get("leg") == "exit" else 1,
            str(plan.get("ticker") or ""),
            str(plan.get("client_order_ref") or ""),
        )
    )
    for index, plan in enumerate(placeable):
        if index >= cap:
            plan["action"] = "capped"
            plan["reason"] = "order_cap"
    return cap


def merge_prior_plans(
    fresh: list[dict[str, Any]],
    prior_plans: list[dict[str, Any]] | None,
    prior_orders: list[dict[str, Any]] | None,
    now: datetime,
) -> list[dict[str, Any]]:
    """Keep sent orders from being planned again. Close unsent rows whose window ended."""
    by_ref = {str(plan.get("client_order_ref") or ""): plan for plan in fresh}
    orders = {
        str(row.get("client_order_ref") or ""): row
        for row in (prior_orders or [])
        if isinstance(row, dict)
    }
    for old in prior_plans or []:
        if not isinstance(old, dict):
            continue
        ref = str(old.get("client_order_ref") or "")
        if not ref:
            continue
        order = orders.get(ref) or {}
        sent = (
            str(order.get("status") or "") in _NO_RETRY or str(old.get("action") or "") in _NO_RETRY
        )
        current = by_ref.get(ref)
        if current is not None:
            if sent and current.get("action") == "would_place":
                current["action"] = "already_working"
                current["reason"] = None
                current["broker_order_id"] = order.get("broker_order_id") or old.get(
                    "broker_order_id"
                )
            continue
        if str(old.get("action") or "") not in {"would_place", "capped"} and not sent:
            continue
        if sent:
            if current is None:
                row = dict(old)
                row["planned_at"] = _aware(now).isoformat()
                row["influences_live"] = False
                row["action"] = "already_working"
                row["broker_order_id"] = order.get("broker_order_id") or old.get("broker_order_id")
                fresh.append(row)
                by_ref[ref] = row
            continue
        row = dict(old)
        row["planned_at"] = _aware(now).isoformat()
        row["influences_live"] = False
        closed = window_open(str(row.get("market") or ""), row.get("fill_session"), now)
        row["action"] = "not_mirrored"
        row["reason"] = "missed_fill_session" if closed is False else "signal_gone"
        fresh.append(row)
        by_ref[ref] = row
    return fresh


def _book_price(episode: Mapping[str, Any] | None, leg: str) -> float | None:
    if not episode:
        return None
    status = str(episode.get("status") or "")
    if leg == "entry":
        if status not in {"open", "closed"}:
            return None
        value = episode.get("return_entry_fill")
        if value is None:
            value = episode.get("entry_fill_first_seen")
        return _positive(value)
    if status == "closed":
        return _positive(episode.get("exit_fill"))
    return None


def _episodes_by_id(observe: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = observe.get("episodes") if isinstance(observe.get("episodes"), list) else []
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("episode_id"):
            found[str(row["episode_id"])] = row
    return found


def normalize_history_item(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """One historical order/fill row from ``GET /api/v0/equity/history/orders``."""
    if not isinstance(item, dict):
        return None
    order = item.get("order") if isinstance(item.get("order"), dict) else {}
    fill = item.get("fill") if isinstance(item.get("fill"), dict) else {}
    if not order and not fill:
        return None
    instrument = order.get("instrument") if isinstance(order.get("instrument"), dict) else {}
    wallet = fill.get("walletImpact") if isinstance(fill.get("walletImpact"), dict) else {}
    taxes = wallet.get("taxes") if isinstance(wallet.get("taxes"), list) else []
    ticker = order.get("ticker") or instrument.get("ticker")
    return {
        "order_id": order.get("id"),
        "fill_id": fill.get("id"),
        "ticker": ticker,
        "side": order.get("side"),
        "status": order.get("status"),
        "quantity": fill.get("quantity"),
        "price": fill.get("price"),
        "filled_at": fill.get("filledAt"),
        "fill_type": fill.get("type") or "TRADE",
        "wallet_net": wallet.get("netValue"),
        "wallet_currency": wallet.get("currency"),
        "taxes": [row for row in taxes if isinstance(row, dict)],
        "currency": order.get("currency") or instrument.get("currency"),
    }


def normalize_dividend(item: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    instrument = item.get("instrument") if isinstance(item.get("instrument"), dict) else {}
    return {
        "reference": item.get("reference"),
        "ticker": item.get("ticker") or instrument.get("ticker"),
        "amount": item.get("amount"),
        "currency": item.get("currency"),
        "paid_on": item.get("paidOn"),
        "gross_amount_per_share": item.get("grossAmountPerShare"),
        "instrument_currency": item.get("tickerCurrency") or instrument.get("currency"),
        "quantity": item.get("quantity"),
        "dividend_type": item.get("type"),
    }


def normalize_transaction(item: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "reference": item.get("reference"),
        "amount": item.get("amount"),
        "currency": item.get("currency"),
        "date_time": item.get("dateTime"),
        "transaction_type": item.get("type"),
    }


def normalize_position(item: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    instrument = item.get("instrument") if isinstance(item.get("instrument"), dict) else {}
    ticker = item.get("ticker") or instrument.get("ticker")
    if not ticker or item.get("quantity") is None:
        return None
    try:
        quantity = float(item["quantity"])
    except (TypeError, ValueError):
        return None
    return {"ticker": str(ticker), "quantity": quantity}


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [row for row in payload["items"] if isinstance(row, dict)]
    return []


def ingest_statement(
    events: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    statement: Mapping[str, Any],
    orders: Mapping[str, Mapping[str, Any]],
    episodes: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Append new raw-price events. Returns gap notes. Does not invent missing ids."""
    known = {str(event.get("event_id") or "") for event in events}
    gaps: list[str] = []
    by_broker = {
        str(row.get("broker_order_id")): row
        for row in orders.values()
        if row.get("broker_order_id") is not None
    }
    for raw in statement.get("history_orders") or []:
        if not isinstance(raw, dict):
            continue
        item = raw if "fill_type" in raw and "order_id" in raw else normalize_history_item(raw)
        if not item:
            continue
        fill_id = item.get("fill_id")
        if fill_id is None:
            gaps.append("history fill without fill.id")
            continue
        fill_type = str(item.get("fill_type") or "TRADE")
        order = by_broker.get(str(item.get("order_id")))
        ticker = str(item.get("ticker") or (order or {}).get("t212_ticker") or "")
        if fill_type == "TRADE":
            event_id = f"fill:{fill_id}"
            if event_id in known:
                continue
            side = str(item.get("side") or (order or {}).get("side") or "").upper()
            quantity = _positive(item.get("quantity"))
            price = _positive(item.get("price"))
            if quantity is None or price is None or side not in {"BUY", "SELL"}:
                gaps.append(f"fill {fill_id} missing price, quantity, or side")
                continue
            episode_id = str((order or {}).get("episode_id") or "")
            leg = str((order or {}).get("leg") or "entry")
            slippage = compute_slippage(
                side=side,
                raw_price=price,
                book_price=_book_price(episodes.get(episode_id), leg),
                half_spread=(order or {}).get("half_spread"),
            )
            event = {
                "event_id": event_id,
                "type": "fill",
                "episode_id": episode_id or None,
                "client_order_ref": (order or {}).get("client_order_ref"),
                "broker_order_id": item.get("order_id"),
                "fill_id": fill_id,
                "t212_ticker": ticker or None,
                "side": side,
                "quantity": quantity,
                "price": price,
                "currency": item.get("currency"),
                "filled_at": item.get("filled_at"),
                "cash": item.get("wallet_net"),
                "cash_currency": item.get("wallet_currency"),
                "taxes": item.get("taxes") or [],
                "slippage": slippage,
                "influences_live": False,
            }
            events.append(event)
            fills.append(event)
            known.add(event_id)
            continue
        event_id = f"corporate:{fill_id}"
        if event_id in known:
            continue
        try:
            quantity = float(item["quantity"]) if item.get("quantity") is not None else None
        except (TypeError, ValueError):
            quantity = None
        if quantity is None:
            gaps.append(f"corporate action {fill_id} missing quantity")
            continue
        kind = "split" if fill_type == "STOCK_SPLIT" else "corporate_action"
        events.append(
            {
                "event_id": event_id,
                "type": kind,
                "fill_type": fill_type,
                "broker_order_id": item.get("order_id"),
                "fill_id": fill_id,
                "t212_ticker": ticker or None,
                "quantity": quantity,
                "price": item.get("price"),
                "event_time": item.get("filled_at"),
                "cash": item.get("wallet_net"),
                "cash_currency": item.get("wallet_currency"),
                "influences_live": False,
            }
        )
        known.add(event_id)
    for raw in statement.get("dividends") or []:
        if not isinstance(raw, dict):
            continue
        item = raw if "paid_on" in raw else normalize_dividend(raw)
        if not item:
            continue
        reference = item.get("reference")
        paid_on = item.get("paid_on")
        if not reference or not paid_on or item.get("amount") is None:
            gaps.append("dividend missing reference, pay date, or amount")
            continue
        event_id = f"dividend:{reference}"
        if event_id in known:
            continue
        events.append(
            {
                "event_id": event_id,
                "type": "dividend",
                "reference": reference,
                "t212_ticker": item.get("ticker"),
                "pay_date": str(paid_on)[:10],
                "paid_on": paid_on,
                "cash": item.get("amount"),
                "currency": item.get("currency"),
                "gross_amount_per_share": item.get("gross_amount_per_share"),
                "instrument_currency": item.get("instrument_currency"),
                "quantity": item.get("quantity"),
                "dividend_type": item.get("dividend_type"),
                "influences_live": False,
            }
        )
        known.add(event_id)
    for raw in statement.get("transactions") or []:
        if not isinstance(raw, dict):
            continue
        item = raw if "transaction_type" in raw else normalize_transaction(raw)
        if not item:
            continue
        reference = item.get("reference")
        if not reference or item.get("amount") is None:
            gaps.append("transaction missing reference or amount")
            continue
        event_id = f"transaction:{reference}"
        if event_id in known:
            continue
        events.append(
            {
                "event_id": event_id,
                "type": "transaction",
                "reference": reference,
                "transaction_type": item.get("transaction_type"),
                "cash": item.get("amount"),
                "currency": item.get("currency"),
                "date_time": item.get("date_time"),
                "influences_live": False,
            }
        )
        known.add(event_id)
    return gaps


def note_delistings(events: list[dict[str, Any]], positions: list[dict[str, Any]]) -> None:
    """Record a delisting when shares we ledger are absent from the account.

    Does not zero the quantity and does not invent a cash value.
    """
    held = ledger_quantities(events)
    actual = {str(row.get("ticker") or ""): row for row in positions}
    known = {str(event.get("event_id") or "") for event in events}
    for ticker, quantity in held.items():
        if quantity <= QTY_TOLERANCE:
            continue
        if ticker in actual:
            continue
        event_id = f"delisting:{ticker}"
        if event_id in known:
            continue
        events.append(
            {
                "event_id": event_id,
                "type": "delisting",
                "t212_ticker": ticker,
                "ledger_quantity": quantity,
                "reason": "delisted",
                "cash": None,
                "influences_live": False,
            }
        )


def _cash_totals(
    rows: list[Mapping[str, Any]], amount_key: str, currency_key: str
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        amount = row.get(amount_key)
        currency = str(row.get(currency_key) or "")
        if amount is None or not currency:
            continue
        try:
            number = float(amount)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        totals[currency] = totals.get(currency, 0.0) + number
    return totals


def reconcile(events: list[dict[str, Any]], statement: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compare the ledger to a normalized demo statement."""
    if statement is None:
        return {"status": "skipped", "reason": "not_configured", "diffs": []}
    diffs: list[dict[str, Any]] = []
    gaps: list[str] = list(statement.get("gaps") or [])
    positions = statement.get("positions")
    if isinstance(positions, list):
        expected = ledger_quantities(events)
        actual: dict[str, float] = {}
        for row in positions:
            if (
                not isinstance(row, dict)
                or row.get("ticker") is None
                or row.get("quantity") is None
            ):
                gaps.append("position row incomplete")
                continue
            try:
                actual[str(row["ticker"])] = float(row["quantity"])
            except (TypeError, ValueError):
                gaps.append("position quantity not numeric")
                continue
        for ticker in sorted(set(expected) | set(actual)):
            lhs = expected.get(ticker, 0.0)
            rhs = actual.get(ticker, 0.0)
            if abs(lhs - rhs) > QTY_TOLERANCE:
                diffs.append(
                    {
                        "kind": "position",
                        "ticker": ticker,
                        "ledger_quantity": lhs,
                        "account_quantity": rhs,
                    }
                )
    else:
        gaps.append("positions missing")
    ledger_fills = {
        str(event.get("fill_id")): event
        for event in events
        if event.get("type") == "fill" and event.get("fill_id") is not None
    }
    for raw in statement.get("history_orders") or []:
        if not isinstance(raw, dict):
            continue
        item = raw if "fill_type" in raw else normalize_history_item(raw)
        if not item or str(item.get("fill_type") or "TRADE") != "TRADE":
            continue
        fill_id = item.get("fill_id")
        if fill_id is None:
            continue
        event = ledger_fills.get(str(fill_id))
        if event is None:
            diffs.append({"kind": "fill", "fill_id": fill_id, "detail": "missing_from_ledger"})
            continue
        price = _positive(item.get("price"))
        if price is not None and abs(price - float(event.get("price") or 0)) > CASH_TOLERANCE:
            diffs.append(
                {
                    "kind": "fill",
                    "fill_id": fill_id,
                    "field": "price",
                    "ledger": event.get("price"),
                    "account": price,
                }
            )
    ledger_refs = {
        str(event.get("reference")): event
        for event in events
        if event.get("type") in {"dividend", "transaction"} and event.get("reference")
    }
    for raw in statement.get("dividends") or []:
        if not isinstance(raw, dict):
            continue
        item = raw if "paid_on" in raw else normalize_dividend(raw)
        if not item or not item.get("reference"):
            continue
        event = ledger_refs.get(str(item["reference"]))
        if event is None or event.get("type") != "dividend":
            diffs.append(
                {
                    "kind": "dividend",
                    "reference": item["reference"],
                    "detail": "missing_from_ledger",
                }
            )
            continue
        try:
            if abs(float(item["amount"]) - float(event.get("cash"))) > CASH_TOLERANCE:
                diffs.append(
                    {
                        "kind": "dividend",
                        "reference": item["reference"],
                        "ledger": event.get("cash"),
                        "account": item.get("amount"),
                    }
                )
        except (TypeError, ValueError):
            gaps.append(f"dividend {item['reference']} amount not numeric")
    for raw in statement.get("transactions") or []:
        if not isinstance(raw, dict):
            continue
        item = raw if "transaction_type" in raw else normalize_transaction(raw)
        if not item or not item.get("reference"):
            continue
        event = ledger_refs.get(str(item["reference"]))
        if event is None or event.get("type") != "transaction":
            diffs.append(
                {
                    "kind": "transaction",
                    "reference": item["reference"],
                    "detail": "missing_from_ledger",
                }
            )
    corporate = {
        str(event.get("fill_id")): event
        for event in events
        if event.get("type") in {"split", "corporate_action"} and event.get("fill_id") is not None
    }
    for raw in statement.get("history_orders") or []:
        if not isinstance(raw, dict):
            continue
        item = raw if "fill_type" in raw else normalize_history_item(raw)
        if not item or str(item.get("fill_type") or "TRADE") == "TRADE":
            continue
        fill_id = item.get("fill_id")
        if fill_id is None:
            continue
        if str(fill_id) not in corporate:
            diffs.append(
                {
                    "kind": "corporate_action",
                    "fill_id": fill_id,
                    "detail": "missing_from_ledger",
                }
            )
    if diffs:
        status = "mismatch"
    elif gaps or statement.get("incomplete"):
        status = "insufficient_data"
    else:
        status = "match"
    return {"status": status, "diffs": diffs, "gaps": gaps}


def slippage_summary(fills: list[dict[str, Any]]) -> dict[str, Any]:
    measured = [
        row
        for row in fills
        if isinstance(row, dict) and (row.get("slippage") or {}).get("status") == "measured"
    ]
    pcts = [float(row["slippage"]["slippage_pct"]) for row in measured]
    median = None
    if pcts:
        ordered = sorted(pcts)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            median = ordered[mid]
        else:
            median = (ordered[mid - 1] + ordered[mid]) / 2.0
    return {"measured_count": len(measured), "median_pct": median}


def summarize(payload: Mapping[str, Any]) -> dict[str, Any]:
    plans = [row for row in (payload.get("plans") or []) if isinstance(row, dict)]
    counts = Counter(str(row.get("action") or "") for row in plans)
    slip = slippage_summary(list(payload.get("fills") or []))
    names = [
        {
            "ticker": row.get("ticker"),
            "column": row.get("column"),
            "leg": row.get("leg"),
            "action": row.get("action"),
            "reason": row.get("reason"),
            "side": row.get("side"),
            "quantity": row.get("quantity"),
            "limit_price": row.get("limit_price"),
            "limit_currency": row.get("limit_currency"),
            "fill_session": row.get("fill_session"),
            "t212_ticker": row.get("t212_ticker"),
        }
        for row in plans
    ]
    return {
        "influences_live": False,
        "demo_credentials_present": bool(payload.get("demo_credentials_present")),
        "placement": payload.get("placement"),
        "observe_data_commit": payload.get("observe_data_commit"),
        "planned_at": payload.get("planned_at"),
        "order_cap": payload.get("order_cap"),
        "orders_sent": int(payload.get("orders_sent") or 0),
        "would_place": counts.get("would_place", 0),
        "placed": counts.get("placed", 0),
        "not_mirrored": counts.get("not_mirrored", 0),
        "capped": counts.get("capped", 0),
        "insufficient_data": counts.get("insufficient_data", 0),
        "rejected": counts.get("rejected", 0),
        "partial": counts.get("partial", 0),
        "cancelled": counts.get("cancelled", 0),
        "already_working": counts.get("already_working", 0),
        "submit_unknown": counts.get("submit_unknown", 0),
        "actions": dict(counts),
        "reconciliation": (payload.get("reconciliation") or {}).get("status"),
        "slippage_measured": slip["measured_count"],
        "slippage_median_pct": slip["median_pct"],
        "names": names,
        "errors": list(payload.get("errors") or []),
    }


def findings_from_ledger(ledger: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Ops-monitor rows. Does not place orders. Every row is ``auto_fixable`` false."""
    if not isinstance(ledger, dict):
        return [
            {
                "severity": "info",
                "category": "research",
                "title": TITLE_NOT_CONFIGURED,
                "summary": (
                    "No demo-mirror ledger yet, so no practice-account order is sent. "
                    "Add TRADING212_DEMO_API_KEY and TRADING212_DEMO_API_SECRET "
                    "on a Trading 212 practice account. "
                    "See docs/ops/strategy-book-demo-mirror.md."
                ),
                "auto_fixable": False,
            }
        ]
    rows: list[dict[str, Any]] = []
    summary = ledger.get("summary") if isinstance(ledger.get("summary"), dict) else {}
    if not ledger.get("demo_credentials_present"):
        waiting = int(summary.get("would_place") or 0)
        rows.append(
            {
                "severity": "info",
                "category": "research",
                "title": TITLE_NOT_CONFIGURED,
                "summary": (
                    "Demo API secrets are absent, so no practice-account order is sent. "
                    f"Latest plan has {waiting} would_place row(s). "
                    "Add TRADING212_DEMO_API_KEY and TRADING212_DEMO_API_SECRET "
                    "(practice account only). See docs/ops/strategy-book-demo-mirror.md."
                ),
                "auto_fixable": False,
            }
        )
    sent = int(summary.get("orders_sent") or ledger.get("orders_sent") or 0)
    if sent > 0:
        rows.append(
            {
                "severity": "info",
                "category": "research",
                "title": TITLE_ORDERS_PLACED,
                "summary": (
                    f"{sent} limit order(s) sent to the Trading 212 demo host this run. "
                    "The book is unchanged. See docs/ops/strategy-book-demo-mirror.md."
                ),
                "auto_fixable": False,
            }
        )
    reconciliation = (
        ledger.get("reconciliation") if isinstance(ledger.get("reconciliation"), dict) else {}
    )
    if reconciliation.get("status") == "mismatch":
        diffs = reconciliation.get("diffs") if isinstance(reconciliation.get("diffs"), list) else []
        rows.append(
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_MISMATCH,
                "summary": (
                    f"{len(diffs)} difference(s) between the raw-price ledger and the demo statement. "
                    "No cash value is invented. See docs/ops/strategy-book-demo-mirror.md."
                ),
                "auto_fixable": False,
            }
        )
    slip = slippage_summary(list(ledger.get("fills") or []))
    if slip["measured_count"]:
        median = slip["median_pct"]
        median_text = "n/a" if median is None else f"{median:.4%}"
        rows.append(
            {
                "severity": "info",
                "category": "research",
                "title": TITLE_SLIPPAGE,
                "summary": (
                    f"{slip['measured_count']} fill(s), median price slippage {median_text} "
                    "versus the book's adjusted close. The assumed half-spread is not replaced. "
                    "See docs/ops/strategy-book-demo-mirror.md."
                ),
                "auto_fixable": False,
            }
        )
    return rows


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "[redacted]")
    return out[:300]


class DemoTransport:
    """HTTP transport that can only talk to the demo host."""

    def __init__(
        self,
        *,
        base: str | None = None,
        env: Mapping[str, str] | None = None,
        opener: Any = None,
        min_interval_s: float = 2.0,
        timeout: float = 60.0,
    ) -> None:
        self.base = demo_base_url(base)
        self._env = env
        self._opener = opener
        self.min_interval_s = float(min_interval_s)
        self.timeout = timeout
        self._last_mutation = 0.0
        self._secrets: tuple[str, ...] = ()
        creds = demo_credentials(env)
        if creds:
            self._secrets = creds

    def _pace(self) -> None:
        if self.min_interval_s <= 0 or not self._last_mutation:
            self._last_mutation = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_mutation
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_mutation = time.monotonic()

    def _request(self, method: str, path: str, body: dict[str, Any] | None, *, mutate: bool) -> Any:
        self.base = demo_base_url(self.base)
        if not path.startswith("/api/"):
            raise DemoMirrorSafetyError(f"refusing path {path}")
        url = self.base + path
        if not url.startswith(f"https://{DEMO_HOST}/"):
            raise DemoMirrorSafetyError(f"refusing URL {url}")
        creds = demo_credentials(self._env)
        if creds is None:
            raise DemoMirrorSafetyError("demo credentials missing")
        self._secrets = creds
        if mutate:
            self._pace()
        data = None if body is None else json.dumps(body).encode("utf-8")
        token = base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode("ascii")
        req = Request(
            url,
            data=data,
            headers={
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "value-investor-strategy-book-demo/1.0",
            },
            method=method,
        )
        status, raw = self._send(req)
        return self._parse(status, raw, method)

    def _send(self, req: Request) -> tuple[int, str]:
        if self._opener is not None:
            status, raw = self._opener(req)
            return int(status), str(raw)
        opener = build_opener(
            _RefuseRedirect,
            HTTPSHandler(context=ssl.create_default_context()),
        )
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                return int(resp.status), resp.read().decode("utf-8")
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = str(exc)
            return int(exc.code), detail
        except URLError as exc:
            raise DemoTransportError(f"network error: {exc}") from exc

    def _parse(self, status: int, raw: str, method: str) -> Any:
        detail = _redact(raw, self._secrets)
        if status in {401, 403}:
            raise DemoAuthError(f"Trading 212 demo auth failed ({status}): {detail}")
        if status == 400 and method != "GET":
            raise DemoOrderRejected(status, detail)
        if status in {408, 429} or status >= 400:
            raise DemoTransportError(f"HTTP {status}: {detail}")
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DemoTransportError(f"invalid JSON ({status})") from exc

    def place_limit(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = self._request("POST", _LIMIT_PATH, body, mutate=True)
        if not isinstance(payload, dict):
            raise DemoTransportError("limit order response was not an object")
        return payload

    def pending_orders(self) -> list[dict[str, Any]]:
        return _as_list(self._request("GET", _ORDERS_PATH, None, mutate=False))

    def cancel(self, order_id: Any) -> Any:
        return self._request("DELETE", f"/api/v0/equity/orders/{order_id}", None, mutate=True)

    def positions(self) -> list[dict[str, Any]]:
        return _as_list(self._request("GET", _POSITIONS_PATH, None, mutate=False))

    def account_summary(self) -> dict[str, Any]:
        payload = self._request("GET", _ACCOUNT_SUMMARY, None, mutate=False)
        if not isinstance(payload, dict):
            raise DemoTransportError("account summary was not an object")
        return payload

    def _pages(self, path: str) -> list[dict[str, Any]]:
        from urllib.parse import urlsplit

        rows: list[dict[str, Any]] = []
        next_path: str | None = path
        for _ in range(20):
            if not next_path:
                break
            payload = self._request("GET", next_path, None, mutate=False)
            if isinstance(payload, list):
                rows.extend(row for row in payload if isinstance(row, dict))
                break
            if not isinstance(payload, dict):
                raise DemoTransportError(f"history payload from {path} was not an object")
            items = payload.get("items")
            if isinstance(items, list):
                rows.extend(row for row in items if isinstance(row, dict))
            link = payload.get("nextPagePath")
            if not link:
                break
            link_text = str(link)
            if link_text.startswith("http"):
                parts = urlsplit(link_text)
                if (parts.hostname or "").lower() != DEMO_HOST:
                    raise DemoMirrorSafetyError(f"refusing history page host {parts.hostname}")
                next_path = parts.path + (f"?{parts.query}" if parts.query else "")
            elif link_text.startswith("/api/"):
                next_path = link_text
            else:
                raise DemoMirrorSafetyError(f"refusing history page {link_text}")
        return rows

    def history_orders(self) -> list[dict[str, Any]]:
        return self._pages(_HISTORY_ORDERS)

    def history_dividends(self) -> list[dict[str, Any]]:
        return self._pages(_HISTORY_DIVIDENDS)

    def history_transactions(self) -> list[dict[str, Any]]:
        return self._pages(_HISTORY_TRANSACTIONS)


def _order_body(plan: Mapping[str, Any]) -> dict[str, Any]:
    quantity = float(plan["quantity"])
    if str(plan.get("side") or "").upper() == "SELL":
        quantity = -abs(quantity)
    else:
        quantity = abs(quantity)
    return {
        "ticker": plan["t212_ticker"],
        "quantity": quantity,
        "limitPrice": plan["limit_price"],
        "timeValidity": TIME_VALIDITY,
    }


def _apply_broker_status(
    plan: dict[str, Any], record: dict[str, Any], response: Mapping[str, Any]
) -> None:
    status = str(response.get("status") or "")
    record["broker_order_id"] = response.get("id")
    record["broker_status"] = status
    record["broker_filled_quantity"] = response.get("filledQuantity")
    plan["broker_order_id"] = response.get("id")
    plan["broker_status"] = status
    mapped = {
        "REJECTED": "rejected",
        "PARTIALLY_FILLED": "partial",
        "FILLED": "filled",
        "CANCELLED": "cancelled",
        "CANCELLING": "cancelling",
    }.get(status, "placed")
    record["status"] = mapped
    plan["action"] = mapped
    plan["reason"] = "rejected" if mapped == "rejected" else None


def _sync_working(plan: dict[str, Any], record: Mapping[str, Any]) -> None:
    status = str(record.get("status") or "")
    if status in _NO_RETRY or status == "auth_blocked":
        plan["broker_order_id"] = record.get("broker_order_id")
        plan["broker_status"] = record.get("broker_status")
    if status in {"placed", "partial", "filled", "rejected", "cancelled", "submit_unknown"}:
        plan["action"] = "partial" if status == "partial" else status
        if status == "rejected":
            plan["reason"] = "rejected"


def _adopt_pending(record: dict[str, Any], pending: list[dict[str, Any]]) -> bool:
    matches = []
    for row in pending:
        if str(row.get("ticker") or "") != str(record.get("t212_ticker") or ""):
            continue
        side = str(row.get("side") or "").upper()
        if side != str(record.get("side") or "").upper():
            continue
        try:
            limit = float(row.get("limitPrice"))
            quantity = abs(float(row.get("quantity")))
        except (TypeError, ValueError):
            continue
        if abs(limit - float(record.get("limit_price") or 0)) > 1e-4:
            continue
        if abs(quantity - abs(float(record.get("quantity") or 0))) > 1e-4:
            continue
        matches.append(row)
    if len(matches) != 1:
        return False
    record["broker_order_id"] = matches[0].get("id")
    record["broker_status"] = matches[0].get("status")
    record["status"] = "partial" if matches[0].get("status") == "PARTIALLY_FILLED" else "placed"
    return True


def _execute(
    *,
    plans: list[dict[str, Any]],
    orders: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    transport: Any,
    episodes: Mapping[str, Mapping[str, Any]],
    now: datetime,
    cap: int,
    checkpoint: Any,
    errors: list[str],
) -> tuple[dict[str, Any], int]:
    _require_demo_transport(transport)
    try:
        summary = transport.account_summary()
    except DemoMirrorSafetyError:
        raise
    except (DemoAuthError, DemoTransportError, OSError) as exc:
        errors.append(f"account summary unavailable: {type(exc).__name__}")
        return {"incomplete": True, "gaps": ["account summary unavailable"], "positions": None}, 0
    account_ccy = str(summary.get("currency") or "").upper()
    if not account_ccy:
        for plan in plans:
            if plan.get("action") == "would_place":
                plan["action"] = "insufficient_data"
                plan["reason"] = "account_currency_missing"
        return {"incomplete": True, "gaps": ["account currency missing"], "positions": None}, 0
    try:
        pending = list(transport.pending_orders())
    except (DemoAuthError, DemoTransportError, OSError) as exc:
        errors.append(f"pending orders unavailable: {type(exc).__name__}")
        pending = []
    for record in orders.values():
        if record.get("broker_order_id"):
            continue
        if str(record.get("status") or "") not in {"submitting", "submit_unknown"}:
            continue
        if _adopt_pending(record, pending):
            checkpoint()
        elif str(record.get("status") or "") == "submitting":
            record["status"] = "submit_unknown"
            checkpoint()
    attempts = 0
    accepted = 0
    ordered = [plan for plan in plans if plan.get("action") == "would_place"]
    ordered.sort(
        key=lambda plan: (
            0 if plan.get("leg") == "exit" else 1,
            str(plan.get("ticker") or ""),
            str(plan.get("client_order_ref") or ""),
        )
    )
    for plan in ordered:
        if attempts >= cap:
            plan["action"] = "capped"
            plan["reason"] = "order_cap"
            continue
        if not account_accepts(account_ccy, str(plan.get("instrument_currency") or "")):
            plan["action"] = "not_mirrored"
            plan["reason"] = "account_currency"
            plan["account_currency"] = account_ccy
            continue
        ref = str(plan["client_order_ref"])
        prior = orders.get(ref)
        if prior and str(prior.get("status") or "") in _NO_RETRY:
            plan["action"] = "already_working"
            plan["broker_order_id"] = prior.get("broker_order_id")
            continue
        record = {
            "client_order_ref": ref,
            "episode_id": plan.get("episode_id"),
            "leg": plan.get("leg"),
            "market": plan.get("market"),
            "ticker": plan.get("ticker"),
            "t212_ticker": plan.get("t212_ticker"),
            "side": plan.get("side"),
            "quantity": plan.get("quantity"),
            "limit_price": plan.get("limit_price"),
            "limit_currency": plan.get("limit_currency"),
            "time_validity": TIME_VALIDITY,
            "fill_session": plan.get("fill_session"),
            "half_spread": plan.get("half_spread"),
            "status": "submitting",
            "submitted_at": _aware(now).isoformat(),
            "influences_live": False,
        }
        orders[ref] = record
        checkpoint()
        attempts += 1
        try:
            response = transport.place_limit(_order_body(plan))
        except DemoOrderRejected as exc:
            record["status"] = "rejected"
            record["broker_status"] = exc.status
            record["detail"] = exc.detail
            plan["action"] = "rejected"
            plan["reason"] = "rejected"
            checkpoint()
            continue
        except DemoAuthError as exc:
            record["status"] = "auth_blocked"
            record["detail"] = str(exc)[:300]
            plan["action"] = "would_place"
            plan["reason"] = "auth_blocked"
            errors.append("demo auth failed; placement stopped")
            checkpoint()
            break
        except DemoMirrorSafetyError:
            record["status"] = "submit_unknown"
            plan["action"] = "submit_unknown"
            checkpoint()
            raise
        except (DemoTransportError, OSError) as exc:
            record["status"] = "submit_unknown"
            record["detail"] = type(exc).__name__
            plan["action"] = "submit_unknown"
            checkpoint()
            continue
        _apply_broker_status(plan, record, response)
        if str(record.get("status") or "") in {"placed", "partial", "filled"}:
            accepted += 1
        checkpoint()
    statement = _fetch_statement(transport, errors)
    statement["account_currency"] = account_ccy
    gaps = ingest_statement(events, fills, statement, orders, episodes)
    statement.setdefault("gaps", []).extend(gaps)
    if isinstance(statement.get("positions"), list):
        note_delistings(events, list(statement["positions"]))
    _cancel_expired(
        plans,
        orders,
        list(statement.get("pending") or pending),
        transport,
        now,
        checkpoint,
    )
    return statement, accepted


def _fetch_statement(transport: Any, errors: list[str]) -> dict[str, Any]:
    statement: dict[str, Any] = {
        "positions": [],
        "history_orders": [],
        "dividends": [],
        "transactions": [],
        "pending": [],
        "gaps": [],
        "incomplete": False,
    }
    try:
        statement["positions"] = [
            row for row in (normalize_position(item) for item in transport.positions()) if row
        ]
    except (DemoAuthError, DemoTransportError, DemoMirrorSafetyError, OSError) as exc:
        errors.append(f"positions unavailable: {type(exc).__name__}")
        statement["incomplete"] = True
        statement["positions"] = None
    for key, method in (
        ("history_orders", "history_orders"),
        ("dividends", "history_dividends"),
        ("transactions", "history_transactions"),
        ("pending", "pending_orders"),
    ):
        try:
            statement[key] = list(getattr(transport, method)())
        except (DemoAuthError, DemoTransportError, DemoMirrorSafetyError, OSError) as exc:
            errors.append(f"{key} unavailable: {type(exc).__name__}")
            statement["incomplete"] = True
    return statement


def _cancel_expired(
    plans: list[dict[str, Any]],
    orders: dict[str, dict[str, Any]],
    pending: list[dict[str, Any]],
    transport: Any,
    now: datetime,
    checkpoint: Any,
) -> None:
    pending_ids = {str(row.get("id")) for row in pending if row.get("id") is not None}
    plans_by_ref = {str(plan.get("client_order_ref") or ""): plan for plan in plans}
    for ref, record in orders.items():
        if str(record.get("status") or "") not in {"placed", "partial"}:
            continue
        closed = window_open(str(record.get("market") or ""), record.get("fill_session"), now)
        if closed is not False:
            continue
        broker_id = record.get("broker_order_id")
        if broker_id is None or str(broker_id) not in pending_ids:
            continue
        try:
            transport.cancel(broker_id)
        except DemoOrderRejected:
            continue
        except (DemoAuthError, DemoTransportError, DemoMirrorSafetyError, OSError):
            record["cancel_error"] = True
            checkpoint()
            continue
        if record["status"] == "placed":
            record["status"] = "cancelled"
        record["remainder_cancelled"] = True
        plan = plans_by_ref.get(ref)
        if plan is not None and record["status"] == "cancelled":
            plan["action"] = "cancelled"
            plan["reason"] = "fill_window_ended"
        checkpoint()


def _empty_store(
    now: datetime, *, placement: str, configured: bool, error: str | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "instrument": INSTRUMENT_ID,
        "influences_live": False,
        "registration_id": None,
        "generated_at": _aware(now).isoformat(),
        "demo_credentials_present": configured,
        "placement": placement,
        "base_url": demo_base_url(DEMO_BASE),
        "order_cap": ORDER_CAP,
        "observe_data_commit": None,
        "observe_generated_at": None,
        "planned_at": _aware(now).isoformat(),
        "plans": [],
        "orders": [],
        "fills": [],
        "ledger": [],
        "reconciliation": {"status": "skipped", "reason": "observe_missing", "diffs": []},
        "slippage": {"measured_count": 0, "median_pct": None},
        "orders_sent": 0,
        "errors": [error] if error else [],
    }
    payload["summary"] = summarize(payload)
    return payload


def run_mirror(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    apply: bool = False,
    place: bool = False,
    transport: Any = None,
    env: Mapping[str, str] | None = None,
    order_cap: int | None = None,
    min_interval_s: float = 2.0,
) -> dict[str, Any]:
    """Plan, and place only when ``place`` and ``apply`` are set and demo keys exist."""
    moment = _aware(now or datetime.now(UTC))
    root = Path(repo_root) if repo_root is not None else Path()
    creds = demo_credentials(env)
    configured = creds is not None
    observe_path = root / "docs" / "data" / "strategy_book_observe.json"
    try:
        observe = _read_json(observe_path)
    except json.JSONDecodeError as exc:
        payload = _empty_store(
            moment,
            placement="skipped",
            configured=configured,
            error=f"observe store unreadable: {exc}",
        )
        if apply:
            _write_json(ledger_path(root), payload)
        return payload
    if not isinstance(observe, dict):
        payload = _empty_store(
            moment,
            placement="skipped",
            configured=configured,
            error="observe store missing",
        )
        if apply:
            _write_json(ledger_path(root), payload)
        return payload
    prior = None
    try:
        prior = load_ledger(root)
    except (OSError, ValueError, TypeError) as exc:
        prior = None
        prior_error = f"prior ledger unreadable: {exc}"
    else:
        prior_error = None
    prior = prior or {}
    plans = build_plans(root, observe, moment)
    prior_orders = [row for row in (prior.get("orders") or []) if isinstance(row, dict)]
    prior_plans = [row for row in (prior.get("plans") or []) if isinstance(row, dict)]
    plans = merge_prior_plans(plans, prior_plans, prior_orders, moment)
    events = [dict(row) for row in (prior.get("ledger") or []) if isinstance(row, dict)]
    fills = [dict(row) for row in (prior.get("fills") or []) if isinstance(row, dict)]
    attach_exit_quantities(plans, events)
    cap = apply_order_cap(plans, order_cap)
    orders = {
        str(row.get("client_order_ref")): dict(row)
        for row in prior_orders
        if row.get("client_order_ref")
    }
    for plan in plans:
        existing = orders.get(str(plan.get("client_order_ref") or ""))
        if (
            existing
            and str(existing.get("status") or "") in _NO_RETRY
            and plan.get("action") == "would_place"
        ):
            plan["action"] = "already_working"
            plan["broker_order_id"] = existing.get("broker_order_id")
    if transport is not None:
        _require_demo_transport(transport)
    placing = bool(place) and configured and bool(apply)
    if place and not configured:
        placement = "skipped_no_credentials"
    elif place and not apply:
        placement = "skipped_place_requires_apply"
    elif placing:
        placement = "live_demo"
    else:
        placement = "dry_run"
    errors: list[str] = []
    if prior_error:
        errors.append(prior_error)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "instrument": INSTRUMENT_ID,
        "influences_live": False,
        "registration_id": observe.get("registration_id"),
        "generated_at": moment.isoformat(),
        "demo_credentials_present": configured,
        "placement": placement,
        "base_url": demo_base_url(DEMO_BASE),
        "order_cap": cap,
        "observe_data_commit": observe.get("data_commit"),
        "observe_generated_at": observe.get("generated_at"),
        "planned_at": moment.isoformat(),
        "plans": plans,
        "orders": list(orders.values()),
        "fills": fills,
        "ledger": events,
        "reconciliation": {"status": "skipped", "reason": placement, "diffs": []},
        "orders_sent": 0,
        "errors": errors,
    }

    def checkpoint() -> None:
        payload["orders"] = list(orders.values())
        payload["plans"] = plans
        payload["fills"] = fills
        payload["ledger"] = events
        payload["orders_sent"] = sent_box[0]
        payload["summary"] = summarize(payload)
        payload["slippage"] = slippage_summary(fills)
        if apply:
            _write_json(ledger_path(root), payload)

    sent_box = [0]
    statement: dict[str, Any] | None = None
    if placing:
        active = transport or DemoTransport(env=env, min_interval_s=min_interval_s)
        # Refuse a non-demo transport before any order, even when nothing is placeable.
        _require_demo_transport(active)
        statement, sent_box[0] = _execute(
            plans=plans,
            orders=orders,
            events=events,
            fills=fills,
            transport=active,
            episodes=_episodes_by_id(observe),
            now=moment,
            cap=cap,
            checkpoint=checkpoint,
            errors=errors,
        )
        payload["errors"] = errors
        if statement is not None:
            payload["reconciliation"] = reconcile(events, statement)
    else:
        payload["reconciliation"] = {
            "status": "skipped",
            "reason": "not_configured" if not configured else placement,
            "diffs": [],
        }
    for plan in plans:
        record = orders.get(str(plan.get("client_order_ref") or ""))
        if record:
            _sync_working(plan, record)
    payload["orders"] = list(orders.values())
    payload["plans"] = plans
    payload["fills"] = fills
    payload["ledger"] = events
    payload["orders_sent"] = sent_box[0]
    payload["errors"] = errors
    payload["slippage"] = slippage_summary(fills)
    payload["summary"] = summarize(payload)
    payload["influences_live"] = False
    if apply:
        _write_json(ledger_path(root), payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Strategy book Trading 212 demo mirror (observe-only, demo host only)"
    )
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write docs/data/strategy_book_demo_ledger.json",
    )
    parser.add_argument(
        "--place",
        action="store_true",
        help="Send limit orders. Requires demo secrets and --apply. Demo host only.",
    )
    parser.add_argument("--as-of", help="Planning time (ISO-8601). Default: now UTC.")
    args = parser.parse_args(argv)
    moment = None
    if args.as_of:
        moment = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
    try:
        store = run_mirror(
            repo_root=args.repo_root,
            now=moment,
            apply=args.apply,
            place=args.place,
        )
    except DemoMirrorSafetyError as exc:
        print(json.dumps({"influences_live": False, "errors": [str(exc)]}, indent=2))
        return 1
    print(json.dumps(summarize(store), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
