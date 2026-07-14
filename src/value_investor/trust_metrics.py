"""Investment-trust metrics: NAV proxy, discount, and trust-specific quality."""

from __future__ import annotations

from typing import Any

import pandas as pd

from value_investor.fetch import _load_ticker_payload, _safe_float
from value_investor.constituents import to_lse_ticker
from value_investor.providers import apply_fallback_providers

# Metrics that matter for closed-end fund / investment-trust screens.
# Book value is used as a NAV proxy when Yahoo does not expose navPrice for LSE trusts.
TRUST_KEY_METRICS = [
    "market_cap",
    "last_price",
    "price_to_book",
    "book_value",
    "discount_to_nav",
    "dividend_yield",
    "trailing_pe",
    "average_volume",
    "fifty_two_week_low",
    "fifty_two_week_high",
    "shares_outstanding",
]

MIN_TRUST_QUALITY_FOR_ANALYSIS = 0.4
MIN_TRUST_QUALITY_FOR_BUY = 0.45
MIN_TRUST_QUALITY_FOR_STRONG_BUY = 0.55


def normalize_yield(value: float | None) -> float | None:
    """Return a fractional yield (0.05 = 5%). Yahoo LSE yields are often percent-scaled."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    number = float(value)
    if number > 1.0:
        return number / 100.0
    return number


def _price_in_pounds(
    *,
    last_price: float | None,
    book_value: float | None,
    market_cap: float | None,
    shares_outstanding: float | None,
) -> float | None:
    """
    Convert Yahoo LSE last prices to pounds when quotes are in pence.

    Prefer market_cap / shares when available; otherwise use book-value scale.
    """
    if (
        market_cap is not None
        and shares_outstanding is not None
        and shares_outstanding > 0
    ):
        return float(market_cap) / float(shares_outstanding)

    if last_price is None:
        return None
    price = float(last_price)
    if book_value is not None and book_value > 0 and price > (float(book_value) * 5):
        return price / 100.0
    if price > 50:
        return price / 100.0
    return price


def resolve_trust_dividend_yield(
    *,
    dividend_yield: float | None,
    dividend_rate: float | None,
    last_price: float | None,
    book_value: float | None,
    market_cap: float | None,
    shares_outstanding: float | None,
) -> float | None:
    """
    Prefer Yahoo ``dividendYield`` (percent or fraction). Else derive from
    ``trailingAnnualDividendRate`` / price-in-pounds.
    """
    direct = normalize_yield(dividend_yield)
    if direct is not None and direct > 0:
        return direct

    if dividend_rate is None or dividend_rate <= 0:
        return None
    price_gbp = _price_in_pounds(
        last_price=last_price,
        book_value=book_value,
        market_cap=market_cap,
        shares_outstanding=shares_outstanding,
    )
    if price_gbp is None or price_gbp <= 0:
        return None
    derived = float(dividend_rate) / price_gbp
    if derived <= 0 or derived > 0.5:
        return None
    return derived


def discount_from_price_to_book(price_to_book: float | None) -> float | None:
    """
    Discount(+) / premium(−) versus book value (NAV proxy).

    ``discount = 1 - P/B``. A trust at 0.70× book is a 30% discount.
    """
    if price_to_book is None or (isinstance(price_to_book, float) and pd.isna(price_to_book)):
        return None
    pb = float(price_to_book)
    if pb <= 0:
        return None
    return 1.0 - pb


def _metric_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    return True


def score_trust_data_quality(row: dict[str, Any]) -> tuple[float, int, int]:
    present = sum(1 for key in TRUST_KEY_METRICS if _metric_present(row.get(key)))
    total = len(TRUST_KEY_METRICS)
    score = present / total if total else 0.0
    errors = row.get("errors")
    if errors:
        if isinstance(errors, str) and errors not in ("[]", ""):
            score *= 0.75
        elif isinstance(errors, list) and errors:
            score *= 0.75
    return round(max(0.0, min(1.0, score)), 4), present, total


def add_trust_derived_metrics(universe: pd.DataFrame) -> pd.DataFrame:
    """Normalize yields and attach discount / 52-week position columns."""
    out = universe.copy()
    if "dividend_yield" in out.columns:
        out["dividend_yield"] = out["dividend_yield"].map(normalize_yield)

    if "price_to_book" in out.columns:
        out["discount_to_nav"] = out["price_to_book"].map(discount_from_price_to_book)
    else:
        out["discount_to_nav"] = None

    # Book value is the NAV proxy label used in reports.
    out["nav_proxy"] = out["book_value"] if "book_value" in out.columns else None
    out["nav_proxy_source"] = "book_value"

    if (
        "last_price" in out.columns
        and "fifty_two_week_low" in out.columns
        and "fifty_two_week_high" in out.columns
    ):
        low = out["fifty_two_week_low"]
        high = out["fifty_two_week_high"]
        span = (high - low).replace(0, pd.NA)
        out["price_vs_52w_range"] = (out["last_price"] - low) / span
    else:
        out["price_vs_52w_range"] = None

    return out


def add_trust_data_quality_scores(universe: pd.DataFrame) -> pd.DataFrame:
    out = universe.copy()
    scores: list[float] = []
    present_counts: list[int] = []
    totals: list[int] = []
    for _, row in out.iterrows():
        score, present, total = score_trust_data_quality(row.to_dict())
        scores.append(score)
        present_counts.append(present)
        totals.append(total)
    out["data_quality_score"] = scores
    out["metrics_present"] = present_counts
    out["metrics_total"] = totals
    return out


def fetch_trust_metrics(
    ticker: str,
    name: str | None = None,
    sector: str | None = None,
) -> dict[str, Any]:
    """
    Lightweight trust quote fetch (no full financial statements).

    Uses Yahoo ``info`` plus the shared fallback cascade for price/mcap/yield gaps.
    """
    resolved = to_lse_ticker(ticker)
    row: dict[str, Any] = {
        "ticker": resolved,
        "name": name,
        "sector": sector,
        "market_cap": None,
        "trailing_pe": None,
        "price_to_book": None,
        "dividend_yield": None,
        "book_value": None,
        "shares_outstanding": None,
        "last_price": None,
        "average_volume": None,
        "fifty_two_week_low": None,
        "fifty_two_week_high": None,
        "beta": None,
        "errors": [],
        "data_sources": {},
        "track": "trust",
    }

    try:
        _stock, info, fast = _load_ticker_payload(resolved)
        if not info and fast is None:
            row["errors"].append("no market data returned")
        else:
            row["name"] = info.get("longName") or info.get("shortName") or name
            row["sector"] = info.get("sector") or sector
            row["market_cap"] = _safe_float(info.get("marketCap") or getattr(fast, "market_cap", None))
            row["trailing_pe"] = _safe_float(info.get("trailingPE"))
            row["price_to_book"] = _safe_float(info.get("priceToBook"))
            row["book_value"] = _safe_float(info.get("bookValue"))
            row["shares_outstanding"] = _safe_float(
                info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            )
            row["last_price"] = _safe_float(
                info.get("regularMarketPrice")
                or info.get("currentPrice")
                or getattr(fast, "last_price", None)
            )
            row["average_volume"] = _safe_float(
                info.get("averageVolume") or info.get("averageDailyVolume10Day")
            )
            row["fifty_two_week_low"] = _safe_float(info.get("fiftyTwoWeekLow"))
            row["fifty_two_week_high"] = _safe_float(info.get("fiftyTwoWeekHigh"))
            row["beta"] = _safe_float(info.get("beta"))
            row["dividend_yield"] = resolve_trust_dividend_yield(
                dividend_yield=_safe_float(info.get("dividendYield")),
                dividend_rate=_safe_float(
                    info.get("trailingAnnualDividendRate") or info.get("dividendRate")
                ),
                last_price=row["last_price"],
                book_value=row["book_value"],
                market_cap=row["market_cap"],
                shares_outstanding=row["shares_outstanding"],
            )
            if row["market_cap"] is None and not info:
                row["errors"].append("no market data returned")
    except Exception as exc:  # noqa: BLE001
        row["errors"].append(str(exc))

    updated, source_map, provider_errors = apply_fallback_providers(resolved, row)
    for key, value in updated.items():
        if key in ("errors", "data_sources"):
            continue
        if row.get(key) is None and value is not None:
            row[key] = value
    if source_map:
        row["data_sources"] = source_map
        if row.get("market_cap") is not None or row.get("last_price") is not None:
            row["errors"] = [
                error for error in row["errors"] if "no market data returned" not in error.lower()
            ]
    elif provider_errors:
        for error in provider_errors:
            if error and error not in row["errors"]:
                row["errors"].append(error)

    # Re-resolve yield if fallbacks filled price/mcap but yield is still empty.
    if row.get("dividend_yield") is None:
        row["dividend_yield"] = resolve_trust_dividend_yield(
            dividend_yield=None,
            dividend_rate=None,
            last_price=row.get("last_price"),
            book_value=row.get("book_value"),
            market_cap=row.get("market_cap"),
            shares_outstanding=row.get("shares_outstanding"),
        )
    else:
        row["dividend_yield"] = normalize_yield(row.get("dividend_yield"))
    row["discount_to_nav"] = discount_from_price_to_book(row.get("price_to_book"))
    row["nav_proxy"] = row.get("book_value")
    row["nav_proxy_source"] = "book_value"
    return row


def fetch_trust_universe(
    tickers: pd.DataFrame,
    *,
    limit: int | None = None,
) -> pd.DataFrame:
    """Fetch trust metrics for a constituents DataFrame."""
    rows: list[dict[str, Any]] = []
    subset = tickers.head(limit) if limit else tickers
    for _, item in subset.iterrows():
        rows.append(
            fetch_trust_metrics(
                ticker=item["ticker"],
                name=item.get("name"),
                sector=item.get("sector"),
            )
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = add_trust_derived_metrics(frame)
    return add_trust_data_quality_scores(frame)
