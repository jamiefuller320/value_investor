"""Fetch fundamental data for screening."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import yfinance as yf

from value_investor.constituents import to_lse_ticker
from value_investor.financials import extract_statement_metrics

logger = logging.getLogger(__name__)

FETCH_ATTEMPTS = 3
FETCH_RETRY_DELAY_SECONDS = 2.0

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
    "return_on_assets",
    "profit_margins",
    "revenue_growth",
    "earnings_growth",
    "free_cashflow",
    "enterprise_value",
    "ebitda",
    "ebit",
    "total_revenue",
    "total_debt",
    "total_cash",
    "book_value",
    "total_assets",
    "total_current_assets",
    "total_liabilities",
    "total_current_liabilities",
    "net_income",
    "operating_cashflow",
    "gross_margin",
    "ncav",
    "shares_outstanding",
    "return_on_assets_prev",
    "gross_margin_prev",
    "current_ratio_bs",
    "current_ratio_bs_prev",
    "leverage",
    "leverage_prev",
    "asset_turnover",
    "asset_turnover_prev",
    "shares_outstanding_prev",
    "interest_expense",
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
    return_on_assets: float | None = None
    profit_margins: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    free_cashflow: float | None = None
    enterprise_value: float | None = None
    ebitda: float | None = None
    ebit: float | None = None
    total_revenue: float | None = None
    total_debt: float | None = None
    total_cash: float | None = None
    book_value: float | None = None
    total_assets: float | None = None
    total_current_assets: float | None = None
    total_liabilities: float | None = None
    total_current_liabilities: float | None = None
    net_income: float | None = None
    operating_cashflow: float | None = None
    gross_margin: float | None = None
    ncav: float | None = None
    shares_outstanding: float | None = None
    return_on_assets_prev: float | None = None
    gross_margin_prev: float | None = None
    current_ratio_bs: float | None = None
    current_ratio_bs_prev: float | None = None
    leverage: float | None = None
    leverage_prev: float | None = None
    asset_turnover: float | None = None
    asset_turnover_prev: float | None = None
    shares_outstanding_prev: float | None = None
    interest_expense: float | None = None
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


def _is_transient_fetch_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    transient_markers = (
        "timed out",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "remote end closed",
        "503",
        "502",
        "429",
        "too many requests",
    )
    return any(marker in message for marker in transient_markers)


def _load_ticker_payload(ticker: str) -> tuple[Any, dict[str, Any], Any]:
    """Fetch yfinance ticker payload with retries for transient network errors."""
    last_exc: BaseException | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            fast = getattr(stock, "fast_info", None)
            return stock, info, fast
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= FETCH_ATTEMPTS or not _is_transient_fetch_error(exc):
                raise
            delay = FETCH_RETRY_DELAY_SECONDS * attempt
            logger.warning(
                "Transient fetch error for %s (attempt %s/%s): %s; retrying in %.1fs",
                ticker,
                attempt,
                FETCH_ATTEMPTS,
                exc,
                delay,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def fetch_company_metrics(ticker: str, name: str | None = None, sector: str | None = None) -> CompanyMetrics:
    """Pull screening metrics for a single LSE ticker via yfinance."""
    resolved = to_lse_ticker(ticker)
    metrics = CompanyMetrics(ticker=resolved, name=name, sector=sector)

    try:
        stock, info, fast = _load_ticker_payload(resolved)

        # Quote-summary 404s often yield empty info without raising.
        if not info and fast is None:
            metrics.errors.append("no market data returned")
            return metrics

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
        metrics.return_on_assets = _safe_float(info.get("returnOnAssets"))
        metrics.profit_margins = _safe_float(info.get("profitMargins"))
        metrics.revenue_growth = _safe_float(info.get("revenueGrowth"))
        metrics.earnings_growth = _safe_float(info.get("earningsGrowth"))
        metrics.free_cashflow = _safe_float(info.get("freeCashflow"))
        metrics.enterprise_value = _safe_float(info.get("enterpriseValue"))
        metrics.ebitda = _safe_float(info.get("ebitda"))
        metrics.ebit = _safe_float(info.get("ebit") or info.get("operatingIncome"))
        metrics.total_revenue = _safe_float(info.get("totalRevenue"))
        metrics.total_debt = _safe_float(info.get("totalDebt"))
        metrics.total_cash = _safe_float(info.get("totalCash"))
        metrics.book_value = _safe_float(info.get("bookValue"))
        metrics.shares_outstanding = _safe_float(
            info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        )

        stmt: dict[str, Any] = {}
        try:
            stmt = extract_statement_metrics(
                getattr(stock, "balance_sheet", None),
                getattr(stock, "income_stmt", None),
                getattr(stock, "cashflow", None),
            )
            for key, value in stmt.items():
                if value is not None and hasattr(metrics, key):
                    setattr(metrics, key, value)
        except Exception as stmt_exc:  # noqa: BLE001
            logger.debug("Statement fetch partial for %s: %s", resolved, stmt_exc)

        if metrics.ebit is None and stmt.get("operating_income") is not None:
            metrics.ebit = stmt["operating_income"]

        if metrics.return_on_assets is None and stmt.get("return_on_assets") is not None:
            metrics.return_on_assets = stmt["return_on_assets"]

        if metrics.current_ratio is None and metrics.current_ratio_bs is not None:
            metrics.current_ratio = metrics.current_ratio_bs

        if metrics.market_cap is None and not info:
            metrics.errors.append("no market data returned")

    except Exception as exc:  # noqa: BLE001 — collect per-ticker failures for batch runs
        logger.warning("Failed to fetch %s: %s", resolved, exc)
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
