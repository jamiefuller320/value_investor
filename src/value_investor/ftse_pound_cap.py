"""Pound market caps for the live FTSE 350 screen.

The 11 Oct 2026 history run stores London prices. Most of those prices are
pence (``GBp``). A pound cap is that price, in pounds, times ordinary shares.

Share counts come from ``financials_annual.json`` when the repo already has
them. Names that have a stored price but no statement share count use
``docs/data/ftse350_ordinary_shares.json``, where each figure is labelled with
the source it was taken from. Same-name filings and library market caps are
used only when that name still has no share count. Repo macro rates convert
USD, EUR, AUD and CAD caps. No rate is invented for HKD or SEK.
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCREEN_PRICE_RUN_PREFIX = "20261011"
MACRO_SNAPSHOT = "docs/data/library/macro/2026-10-16.json"
SOURCED_SHARES = "docs/data/ftse350_ordinary_shares.json"

_SHARE_FIELDS = (
    "Ordinary Shares Number",
    "Share Issued",
    "Basic Average Shares",
)
_FX_CURRENCIES = frozenset({"USD", "EUR", "AUD", "CAD"})
_SUFFIXES = re.compile(
    r"\b(plc|public limited company|inc|incorporated|ltd|limited|corp|"
    r"corporation|sa|nv|ag|se|spa|oyj|ab|ord|the)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PoundCap:
    """One FTSE 350 name and its pound market cap, if the inputs exist."""

    ticker: str
    name: str
    cap_gbp: float | None
    method: str
    detail: str


@dataclass(frozen=True)
class _ShareCount:
    shares: float
    year: str
    field: str
    path: str
    priority: int


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def normalize_issuer_name(name: str) -> str:
    """Fold legal suffixes so Unilever PLC and Unilever PLC match.

    ``Group`` is kept, so Domino's Pizza Group does not match Domino's Pizza, Inc.
    """

    text = (name or "").lower().replace("&", " and ").replace("'", "")
    text = text.replace(".", " ")
    text = _SUFFIXES.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def listing_currency(ticker: str) -> str:
    """Listing currency implied by the Yahoo ticker suffix."""

    if ticker.endswith(".L"):
        return "GBP"
    if ticker.endswith(".HK"):
        return "HKD"
    if ticker.endswith(".ST"):
        return "SEK"
    if ticker.endswith(".SW"):
        return "CHF"
    if ticker.endswith(".AX"):
        return "AUD"
    if ticker.endswith(".TO"):
        return "CAD"
    if ticker.endswith(".SI"):
        return "SGD"
    if ticker.endswith((".AS", ".PA", ".DE", ".MC", ".MI", ".BR", ".IR", ".LS", ".HE", ".VI")):
        return "EUR"
    if "." not in ticker:
        return "USD"
    return "OTHER"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fx_usd_per_unit(root: Path) -> dict[str, float]:
    snapshot = _load_json(root / MACRO_SNAPSHOT)
    domains = snapshot["domains"]
    return {
        "GBP": float(domains["uk"]["markers"]["gbp_usd"]["value"]),
        "EUR": float(domains["euro"]["markers"]["eur_usd"]["value"]),
        "AUD": float(domains["au"]["markers"]["aud_usd"]["value"]),
        "CAD": float(domains["ca"]["markers"]["cad_usd"]["value"]),
        "USD": 1.0,
    }


def _screen_prices(root: Path) -> dict[str, float]:
    history = root / "docs/data/history"
    paths = sorted(history.glob(f"run_{SCREEN_PRICE_RUN_PREFIX}_*.json.gz"))
    if not paths:
        return {}
    with gzip.open(paths[-1], "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    prices = payload.get("prices") or {}
    out: dict[str, float] = {}
    for ticker, raw in prices.items():
        if raw is None:
            continue
        out[str(ticker)] = float(raw)
    return out


def _ftse_names(root: Path) -> list[tuple[str, str]]:
    latest = _load_json(root / "docs/data/latest.json")
    rows: list[tuple[str, str]] = []
    for key in ("reports", "trust_reports"):
        for row in latest.get(key) or []:
            ticker = str(row.get("ticker") or "")
            if ticker:
                rows.append((ticker, str(row.get("name") or "")))
    return rows


def _statement_shares(payload: dict[str, Any]) -> tuple[str, str, float] | None:
    balance = payload.get("balance_sheet") or {}
    if not isinstance(balance, dict) or not balance:
        return None
    for year in sorted(balance, reverse=True):
        row = balance[year]
        if not isinstance(row, dict):
            continue
        for field in _SHARE_FIELDS:
            raw = row.get(field)
            if raw:
                return str(year), field, float(raw)
    return None


def _financial_shares(root: Path) -> dict[str, _ShareCount]:
    patterns = (
        "docs/data/research/*/sources/financials_annual.json",
        "docs/data/library/markets/*/screen/research/*/sources/financials_annual.json",
    )
    found: dict[str, list[_ShareCount]] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            ticker = path.parent.parent.name
            try:
                payload = _load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            parsed = _statement_shares(payload)
            if parsed is None:
                continue
            year, field, shares = parsed
            priority = 0 if pattern.startswith("docs/data/research/") else 1
            found.setdefault(ticker, []).append(
                _ShareCount(
                    shares=shares,
                    year=year,
                    field=field,
                    path=path.relative_to(root).as_posix(),
                    priority=priority,
                )
            )
    chosen: dict[str, _ShareCount] = {}
    for ticker, rows in found.items():
        ordered = sorted(rows, key=lambda row: row.year, reverse=True)
        ordered = sorted(ordered, key=lambda row: row.priority)
        chosen[ticker] = ordered[0]
    return chosen


def _sourced_shares(root: Path) -> dict[str, dict[str, Any]]:
    path = root / SOURCED_SHARES
    if not path.exists():
        return {}
    payload = _load_json(path)
    tickers = payload.get("tickers") or {}
    out: dict[str, dict[str, Any]] = {}
    for ticker, row in tickers.items():
        if not isinstance(row, dict):
            continue
        shares = row.get("ordinary_shares")
        if not shares or float(shares) <= 0:
            continue
        out[str(ticker)] = row
    return out


def _library_caps(root: Path) -> dict[str, list[tuple[str, str, float]]]:
    """Ticker -> (market, issuer name, market cap) from each latest metrics file."""

    found: dict[str, list[tuple[str, str, float]]] = {}
    markets = root / "docs/data/library/markets"
    if not markets.exists():
        return found
    for market_dir in sorted(path for path in markets.iterdir() if path.is_dir()):
        path = market_dir / "metrics" / "latest.json.gz"
        if not path.exists():
            continue
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            rows = json.load(handle)
        for row in rows:
            cap = row.get("market_cap")
            ticker = str(row.get("ticker") or "")
            if not ticker or not cap:
                continue
            found.setdefault(ticker, []).append(
                (market_dir.name, str(row.get("name") or ""), float(cap))
            )
    return found


def _stable_cap(entries: list[tuple[str, float]]) -> float | None:
    """Use one stored cap when duplicates agree. Disagreeing caps are not averaged."""

    if not entries:
        return None
    ordered = sorted(entries, key=lambda item: item[0])
    first = ordered[0][1]
    if first <= 0:
        return None
    for _, cap in ordered[1:]:
        if abs(cap - first) / first > 0.01:
            return None
    return first


def _gbp_from_price(
    price: float,
    shares: float,
    quote_currency: str,
    usd_per_unit: dict[str, float],
) -> float | None:
    if shares <= 0 or price <= 0:
        return None
    if quote_currency == "GBp":
        return price * shares / 100.0
    if quote_currency == "GBP":
        return price * shares
    if quote_currency == "USD":
        gbp_usd = usd_per_unit.get("GBP")
        if not gbp_usd:
            return None
        return price * shares / gbp_usd
    if quote_currency == "EUR":
        gbp_usd = usd_per_unit.get("GBP")
        eur_usd = usd_per_unit.get("EUR")
        if not gbp_usd or not eur_usd:
            return None
        return price * shares * eur_usd / gbp_usd
    return None


def _fx_to_gbp(cap: float, currency: str, usd_per_unit: dict[str, float]) -> float | None:
    gbp_usd = usd_per_unit.get("GBP")
    per_usd = usd_per_unit.get(currency)
    if cap <= 0 or not gbp_usd or not per_usd:
        return None
    return cap * per_usd / gbp_usd


def compute_ftse350_pound_caps(root: Path | None = None) -> list[PoundCap]:
    """Return one row per FTSE 350 name, largest inputs first in the method order.

    Missing inputs stay missing. Caps are not filled with a guessed share count
    or a currency rate the macro file does not contain.
    """

    root = Path(root or repo_root_from_here())
    names = _ftse_names(root)
    prices = _screen_prices(root)
    financials = _financial_shares(root)
    sourced = _sourced_shares(root)
    library = _library_caps(root)
    usd_per_unit = _fx_usd_per_unit(root)

    ticker_name = {ticker: name for ticker, name in names}
    for ticker, entries in library.items():
        ticker_name.setdefault(ticker, entries[0][1])

    by_name: dict[str, list[str]] = {}
    for ticker, name in ticker_name.items():
        key = normalize_issuer_name(name)
        if key:
            by_name.setdefault(key, []).append(ticker)

    results: list[PoundCap] = []
    for ticker, name in names:
        cap, method, detail = _cap_for_ticker(
            ticker,
            name,
            prices=prices,
            financials=financials,
            sourced=sourced,
            library=library,
            by_name=by_name,
            usd_per_unit=usd_per_unit,
        )
        results.append(
            PoundCap(
                ticker=ticker,
                name=name,
                cap_gbp=cap,
                method=method,
                detail=detail,
            )
        )
    return results


def _cap_for_ticker(
    ticker: str,
    name: str,
    *,
    prices: dict[str, float],
    financials: dict[str, _ShareCount],
    sourced: dict[str, dict[str, Any]],
    library: dict[str, list[tuple[str, str, float]]],
    by_name: dict[str, list[str]],
    usd_per_unit: dict[str, float],
) -> tuple[float | None, str, str]:
    price = prices.get(ticker)
    own = financials.get(ticker)
    if price is not None and own is not None:
        cap = _gbp_from_price(price, own.shares, "GBp", usd_per_unit)
        if cap is not None:
            return (
                cap,
                "price_x_financials_shares",
                f"pence {SCREEN_PRICE_RUN_PREFIX} × {own.field} {own.year} from {own.path} / 100",
            )

    extra = sourced.get(ticker)
    if price is not None and extra is not None:
        currency = str(extra.get("quote_currency") or "")
        cap = _gbp_from_price(price, float(extra["ordinary_shares"]), currency, usd_per_unit)
        if cap is not None:
            return (
                cap,
                "price_x_sourced_shares",
                str(extra.get("source") or "sourced ordinary shares"),
            )

    key = normalize_issuer_name(name)
    same_shares = []
    for other in by_name.get(key, []):
        if other != ticker and other in financials:
            same_shares.append(other)
    unique_same = sorted(set(same_shares))
    if price is not None and len(unique_same) == 1:
        other = unique_same[0]
        count = financials[other]
        cap = _gbp_from_price(price, count.shares, "GBp", usd_per_unit)
        if cap is not None:
            return (
                cap,
                "price_x_same_name_shares",
                f"pence {SCREEN_PRICE_RUN_PREFIX} × {count.field} {other} / 100",
            )

    if listing_currency(ticker) == "GBP":
        own_caps = [(market, cap) for market, _, cap in library.get(ticker, [])]
        cap = _stable_cap(own_caps)
        if cap is not None:
            market = sorted(own_caps)[0][0]
            return cap, "library_gbp_cap", f"library {market} market_cap in GBP"

    convertible: dict[str, list[tuple[str, float]]] = {}
    for other in by_name.get(key, []):
        if other == ticker:
            continue
        currency = listing_currency(other)
        if currency not in _FX_CURRENCIES:
            continue
        for market, _, cap in library.get(other, []):
            convertible.setdefault(other, []).append((market, cap))
    if len(convertible) == 1:
        other, entries = next(iter(convertible.items()))
        local = _stable_cap(entries)
        currency = listing_currency(other)
        cap = _fx_to_gbp(local, currency, usd_per_unit) if local is not None else None
        if cap is not None:
            return (
                cap,
                "same_name_fx_cap",
                f"{other} {local:.6g} {currency} × repo {currency} to GBP",
            )
    return None, "missing", "no stored price, share count, or convertible cap"


def computable_pound_caps(root: Path | None = None) -> list[PoundCap]:
    return [row for row in compute_ftse350_pound_caps(root) if row.cap_gbp is not None]


def missing_pound_caps(root: Path | None = None) -> list[PoundCap]:
    return [row for row in compute_ftse350_pound_caps(root) if row.cap_gbp is None]
