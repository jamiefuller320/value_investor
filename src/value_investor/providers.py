"""Alternate market-data providers and fallback cascade.

Primary screening still uses yfinance. When that fails or leaves key fields
empty, curated secondary providers fill gaps. This is intentionally not an
open web crawl — HTML scrapers are brittle and ToS-risky; providers here use
documented/stable CSV or JSON endpoints.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

USER_AGENT = "value-investor/0.1 (research screener; fallback providers)"
HTTP_TIMEOUT_SECONDS = 20
PROVIDER_RETRIES = 2

# Fields worth filling from secondary providers when the primary leaves gaps.
FALLBACK_METRIC_KEYS = (
    "market_cap",
    "trailing_pe",
    "forward_pe",
    "price_to_book",
    "dividend_yield",
    "current_ratio",
    "debt_to_equity",
    "return_on_equity",
    "return_on_assets",
    "profit_margins",
    "free_cashflow",
    "enterprise_value",
    "ebitda",
    "ebit",
    "total_revenue",
    "total_debt",
    "total_cash",
    "book_value",
    "shares_outstanding",
    "last_price",
)


@dataclass
class ProviderResult:
    """Partial metrics from one provider."""

    source: str
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.metrics) and not (
            len(self.errors) > 0 and not any(v is not None for v in self.metrics.values())
        )


class DataProvider(Protocol):
    name: str

    def fetch(self, ticker: str) -> ProviderResult:
        """Return whatever metrics this provider can supply for ``ticker``."""


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def http_get_text(url: str, *, timeout: int = HTTP_TIMEOUT_SECONDS) -> str:
    """GET URL text with light retries for transient network errors."""
    last_exc: BaseException | None = None
    request = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, PROVIDER_RETRIES + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt >= PROVIDER_RETRIES:
                break
            time.sleep(attempt)
    assert last_exc is not None
    raise last_exc


def missing_metric_keys(metrics: dict[str, Any], keys: tuple[str, ...] = FALLBACK_METRIC_KEYS) -> list[str]:
    missing: list[str] = []
    for key in keys:
        value = metrics.get(key)
        if value is None:
            missing.append(key)
    return missing


def merge_provider_result(
    metrics: dict[str, Any],
    result: ProviderResult,
    *,
    source_map: dict[str, str],
) -> list[str]:
    """
    Fill only missing metric keys from ``result``.

    Returns the list of keys newly populated.
    """
    filled: list[str] = []
    for key, value in result.metrics.items():
        if value is None:
            continue
        if metrics.get(key) is not None:
            continue
        metrics[key] = value
        source_map[key] = result.source
        filled.append(key)
    return filled


def to_stooq_symbol(ticker: str) -> str:
    """Convert Yahoo-style ``BT-A.L`` to Stooq ``bt_a.uk``."""
    symbol = ticker.strip().upper()
    if symbol.endswith(".L"):
        symbol = symbol[:-2]
    symbol = symbol.replace("-", "_").replace(".", "_").lower()
    return f"{symbol}.uk"


class YahooQuoteSummaryProvider:
    """Yahoo quoteSummary JSON modules — often works when yfinance ``.info`` fails."""

    name = "yahoo_quote_summary"

    def fetch(self, ticker: str) -> ProviderResult:
        modules = "price,summaryDetail,defaultKeyStatistics,financialData"
        url = (
            "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
            f"{ticker}?modules={modules}"
        )
        try:
            payload = json.loads(http_get_text(url))
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(source=self.name, errors=[f"{self.name}: {exc}"])

        try:
            result = payload["quoteSummary"]["result"][0]
        except (KeyError, IndexError, TypeError):
            error = (
                (payload.get("quoteSummary") or {}).get("error")
                or {"description": "empty quoteSummary"}
            )
            return ProviderResult(
                source=self.name,
                errors=[f"{self.name}: {error.get('description') or error}"],
            )

        price = result.get("price") or {}
        summary = result.get("summaryDetail") or {}
        stats = result.get("defaultKeyStatistics") or {}
        financials = result.get("financialData") or {}

        def raw(block: dict[str, Any], key: str) -> Any:
            node = block.get(key)
            if isinstance(node, dict):
                return node.get("raw", node.get("fmt"))
            return node

        metrics = {
            "name": price.get("longName") or price.get("shortName"),
            "last_price": _safe_float(raw(price, "regularMarketPrice")),
            "market_cap": _safe_float(raw(price, "marketCap")),
            "trailing_pe": _safe_float(raw(summary, "trailingPE") or raw(stats, "trailingPE")),
            "forward_pe": _safe_float(raw(summary, "forwardPE") or raw(stats, "forwardPE")),
            "price_to_book": _safe_float(raw(stats, "priceToBook")),
            "dividend_yield": _safe_float(raw(summary, "dividendYield")),
            "shares_outstanding": _safe_float(raw(stats, "sharesOutstanding")),
            "book_value": _safe_float(raw(stats, "bookValue")),
            "enterprise_value": _safe_float(raw(stats, "enterpriseValue")),
            "profit_margins": _safe_float(raw(financials, "profitMargins")),
            "return_on_equity": _safe_float(raw(financials, "returnOnEquity")),
            "return_on_assets": _safe_float(raw(financials, "returnOnAssets")),
            "debt_to_equity": _safe_float(raw(financials, "debtToEquity")),
            "current_ratio": _safe_float(raw(financials, "currentRatio")),
            "free_cashflow": _safe_float(raw(financials, "freeCashflow")),
            "ebitda": _safe_float(raw(financials, "ebitda")),
            "total_revenue": _safe_float(raw(financials, "totalRevenue")),
            "total_debt": _safe_float(raw(financials, "totalDebt")),
            "total_cash": _safe_float(raw(financials, "totalCash")),
        }
        return ProviderResult(source=self.name, metrics=metrics)


class YahooChartProvider:
    """Yahoo chart endpoint — last price / prior close when richer modules fail."""

    name = "yahoo_chart"

    def fetch(self, ticker: str) -> ProviderResult:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d"
        try:
            payload = json.loads(http_get_text(url))
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(source=self.name, errors=[f"{self.name}: {exc}"])

        try:
            meta = payload["chart"]["result"][0]["meta"]
        except (KeyError, IndexError, TypeError):
            return ProviderResult(source=self.name, errors=[f"{self.name}: empty chart result"])

        price = _safe_float(meta.get("regularMarketPrice") or meta.get("previousClose"))
        return ProviderResult(
            source=self.name,
            metrics={
                "last_price": price,
                "name": meta.get("longName") or meta.get("shortName"),
            },
        )


class StooqPriceProvider:
    """Stooq daily CSV — UK last close when Yahoo endpoints are unavailable."""

    name = "stooq"

    def fetch(self, ticker: str) -> ProviderResult:
        symbol = to_stooq_symbol(ticker)
        url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
        try:
            text = http_get_text(url)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(source=self.name, errors=[f"{self.name}: {exc}"])

        if not text or text.strip().lower().startswith("<!"):
            return ProviderResult(source=self.name, errors=[f"{self.name}: non-CSV response for {symbol}"])

        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return ProviderResult(source=self.name, errors=[f"{self.name}: no rows for {symbol}"])

        # Stooq returns newest last when sorted; take the final valid close.
        close: float | None = None
        for row in reversed(rows):
            close = _safe_float(row.get("Close") or row.get("close"))
            if close is not None:
                break
        if close is None:
            return ProviderResult(source=self.name, errors=[f"{self.name}: no close price for {symbol}"])

        return ProviderResult(source=self.name, metrics={"last_price": close})


DEFAULT_FALLBACK_PROVIDERS: tuple[DataProvider, ...] = (
    YahooQuoteSummaryProvider(),
    YahooChartProvider(),
    StooqPriceProvider(),
)


def apply_fallback_providers(
    ticker: str,
    metrics: dict[str, Any],
    *,
    providers: tuple[DataProvider, ...] | None = None,
    force: bool = False,
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """
    Fill missing screening fields from curated alternate providers.

    Runs when the primary fetch reported errors, left ``market_cap`` empty,
    or ``force`` is set — not on every partial row (avoids extra HTTP for
    healthy yfinance responses).

    Returns ``(metrics, source_map, provider_errors)``.
    """
    source_map: dict[str, str] = {}
    provider_errors: list[str] = []
    chain = providers if providers is not None else DEFAULT_FALLBACK_PROVIDERS

    errors = metrics.get("errors") or []
    needs_fallback = force or bool(errors) or metrics.get("market_cap") is None
    if not needs_fallback:
        return metrics, source_map, provider_errors

    for provider in chain:
        still_missing = missing_metric_keys(metrics)
        if not still_missing and not force:
            break
        try:
            result = provider.fetch(ticker)
        except Exception as exc:  # noqa: BLE001
            provider_errors.append(f"{provider.name}: {exc}")
            logger.warning("Fallback provider %s failed for %s: %s", provider.name, ticker, exc)
            continue

        provider_errors.extend(result.errors)
        filled = merge_provider_result(metrics, result, source_map=source_map)
        if filled:
            logger.info(
                "Fallback %s filled %s for %s",
                provider.name,
                ",".join(filled),
                ticker,
            )

    # Derive market cap if we recovered price + shares.
    if metrics.get("market_cap") is None:
        price = _safe_float(metrics.get("last_price"))
        shares = _safe_float(metrics.get("shares_outstanding"))
        if price is not None and shares is not None and price > 0 and shares > 0:
            metrics["market_cap"] = price * shares
            source_map["market_cap"] = source_map.get("last_price") or source_map.get(
                "shares_outstanding", "derived"
            )

    return metrics, source_map, provider_errors
