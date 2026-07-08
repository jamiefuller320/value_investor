"""Fetch fundamental data for screening."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

METRIC_KEYS = [
    "ticker",
    "name",
    "sector",
    "market_cap",
    "trailing_pe",
    "forward_pe",
    "price_to_book",
    "dividend_yield",
    "current_ratio",
    "debt_to_equity",
    "return_on_equity",
    "profit_margins",
    "revenue_growth",
    "earnings_growth",
    "free_cashflow",
    "enterprise_value",
    "ebitda",
    "total_revenue",
    "total_debt",
    "total_cash",
]


@dataclass
class CompanyMetrics:
    ticker: str
    name: str | None = None
    sector: str | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    price_to_book: float | None = None
    dividend_yield: float | None = None
    current_ratio: float | None = None
    debt_to_equity: float | None = None
    return_on_equity: float | None = None
    profit_margins: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    free_cashflow: float | None = None
    enterprise_value: float | None = None
    ebitda: float | None = None
    total_revenue: float | None = None
    total_debt: float | None = None
    total_cash: float | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {k: getattr(self, k) for k in METRIC_KEYS}
        data["errors"] = self.errors
        return data


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def fetch_company_metrics(ticker: str, name: str | None = None, sector: str | None = None) -> CompanyMetrics:
    """Pull screening metrics for a single LSE ticker via yfinance."""
    metrics = CompanyMetrics(ticker=ticker, name=name, sector=sector)

    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        fast = getattr(stock, "fast_info", None)

        metrics.name = info.get("longName") or info.get("shortName") or name
        metrics.sector = info.get("sector") or sector
        metrics.market_cap = _safe_float(info.get("marketCap") or getattr(fast, "market_cap", None))
        metrics.trailing_pe = _safe_float(info.get("trailingPE"))
        metrics.forward_pe = _safe_float(info.get("forwardPE"))
        metrics.price_to_book = _safe_float(info.get("priceToBook"))
        metrics.dividend_yield = _safe_float(info.get("dividendYield"))
        metrics.current_ratio = _safe_float(info.get("currentRatio"))
        metrics.debt_to_equity = _safe_float(info.get("debtToEquity"))
        metrics.return_on_equity = _safe_float(info.get("returnOnEquity"))
        metrics.profit_margins = _safe_float(info.get("profitMargins"))
        metrics.revenue_growth = _safe_float(info.get("revenueGrowth"))
        metrics.earnings_growth = _safe_float(info.get("earningsGrowth"))
        metrics.free_cashflow = _safe_float(info.get("freeCashflow"))
        metrics.enterprise_value = _safe_float(info.get("enterpriseValue"))
        metrics.ebitda = _safe_float(info.get("ebitda"))
        metrics.total_revenue = _safe_float(info.get("totalRevenue"))
        metrics.total_debt = _safe_float(info.get("totalDebt"))
        metrics.total_cash = _safe_float(info.get("totalCash"))

        if metrics.market_cap is None and not info:
            metrics.errors.append("no market data returned")

    except Exception as exc:  # noqa: BLE001 — collect per-ticker failures for batch runs
        logger.warning("Failed to fetch %s: %s", ticker, exc)
        metrics.errors.append(str(exc))

    return metrics


def fetch_universe(
    tickers: pd.DataFrame,
    *,
    limit: int | None = None,
) -> pd.DataFrame:
    """
    Fetch metrics for all tickers in a constituents DataFrame.

    Args:
        tickers: DataFrame with at least `ticker`; optional `name`, `sector`.
        limit: Optional cap for dry runs / development.
    """
    rows: list[dict[str, Any]] = []
    subset = tickers.head(limit) if limit else tickers

    for _, row in subset.iterrows():
        metrics = fetch_company_metrics(
            ticker=row["ticker"],
            name=row.get("name"),
            sector=row.get("sector"),
        )
        rows.append(metrics.to_dict())

    return pd.DataFrame(rows)
