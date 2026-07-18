"""FX helpers for multi-currency paper books (reporting currency conversion).

Hedging is not modelled — NAV conversion is mark-to-market at spot only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_CURRENCIES = ("GBP", "USD", "EUR", "AUD", "CAD", "HKD", "SGD")

# Yahoo FX pairs quoted as BASEQUOTE=X → price of 1 BASE in QUOTE units.
_YAHOO_PAIR: dict[tuple[str, str], str] = {
    ("GBP", "USD"): "GBPUSD=X",
    ("EUR", "USD"): "EURUSD=X",
    ("AUD", "USD"): "AUDUSD=X",
    ("CAD", "USD"): "CADUSD=X",
    ("HKD", "USD"): "HKDUSD=X",
    ("SGD", "USD"): "SGDUSD=X",
    ("GBP", "EUR"): "GBPEUR=X",
    ("EUR", "GBP"): "EURGBP=X",
    ("AUD", "GBP"): "AUDGBP=X",
    ("CAD", "GBP"): "CADGBP=X",
    ("HKD", "GBP"): "HKDGBP=X",
    ("SGD", "GBP"): "SGDGBP=X",
    ("USD", "GBP"): "GBPUSD=X",  # invert
    ("USD", "EUR"): "EURUSD=X",  # invert
    ("USD", "AUD"): "AUDUSD=X",  # invert
    ("USD", "CAD"): "USDCAD=X",
    ("USD", "HKD"): "USDHKD=X",
    ("USD", "SGD"): "USDSGD=X",
}

_INVERT_PAIRS = {
    ("USD", "GBP"),
    ("USD", "EUR"),
    ("USD", "AUD"),
}

MARKET_CURRENCY = {
    "ftse350": "GBP",
    "ftse_smallcap": "GBP",
    "aim": "GBP",
    "sp500": "USD",
    "nasdaq100": "USD",
    "us_adr_asia": "USD",
    "euro_stoxx50": "EUR",
    "dax": "EUR",
    "cac40": "EUR",
    "ibex35": "EUR",
    "ftse_mib": "EUR",
    "aex": "EUR",
    "bel20": "EUR",
    "asx200": "AUD",
    "tsx60": "CAD",
    "hang_seng": "HKD",
    "sti": "SGD",
}


@dataclass(frozen=True)
class PaperFxPolicy:
    """L28 paper FX policy — reporting currency + unhedged MTM conversion."""

    reporting_currency: str = "GBP"
    hedge_assumption: str = "none"
    rate_source: str = "yahoo_finance"
    note: str = (
        "Paper NAV converts foreign marks into reporting_currency at spot. "
        "No FX hedging is assumed. Cash is treated as reporting_currency."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reporting_currency": self.reporting_currency,
            "hedge_assumption": self.hedge_assumption,
            "rate_source": self.rate_source,
            "note": self.note,
            "supported_currencies": list(SUPPORTED_CURRENCIES),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PaperFxPolicy:
        data = data or {}
        ccy = str(data.get("reporting_currency") or "GBP").upper()
        if ccy not in SUPPORTED_CURRENCIES:
            ccy = "GBP"
        return cls(
            reporting_currency=ccy,
            hedge_assumption=str(data.get("hedge_assumption") or "none"),
            rate_source=str(data.get("rate_source") or "yahoo_finance"),
            note=str(
                data.get("note")
                or (
                    "Paper NAV converts foreign marks into reporting_currency at spot. "
                    "No FX hedging is assumed. Cash is treated as reporting_currency."
                )
            ),
        )


def currency_for_market(market: str | None) -> str:
    return MARKET_CURRENCY.get((market or "").strip().lower(), "GBP")


def currency_for_ticker(ticker: str, *, market: str | None = None) -> str:
    if market:
        return currency_for_market(market)
    t = (ticker or "").upper()
    if t.endswith(".L"):
        return "GBP"
    if t.endswith(".AX"):
        return "AUD"
    if t.endswith(".TO"):
        return "CAD"
    if any(t.endswith(s) for s in (".DE", ".PA", ".AS", ".MI", ".BR", ".HE", ".MC")):
        return "EUR"
    if t.endswith(".HK"):
        return "HKD"
    if t.endswith(".SI"):
        return "SGD"
    return "USD"


def _spot_pair(base: str, quote: str) -> float | None:
    base_u, quote_u = base.upper(), quote.upper()
    if base_u == quote_u:
        return 1.0
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance unavailable for FX")
        return None

    key = (base_u, quote_u)
    symbol = _YAHOO_PAIR.get(key)
    invert = key in _INVERT_PAIRS
    if symbol is None:
        # Try via USD bridge
        to_usd = _spot_pair(base_u, "USD")
        quote_to_usd = _spot_pair(quote_u, "USD")
        if to_usd and quote_to_usd and quote_to_usd > 0:
            return to_usd / quote_to_usd
        return None
    try:
        hist = yf.Ticker(symbol).history(period="5d")
        if hist is None or hist.empty:
            return None
        px = float(hist["Close"].dropna().iloc[-1])
        if px <= 0:
            return None
        return (1.0 / px) if invert else px
    except Exception as exc:  # noqa: BLE001
        logger.debug("FX fetch failed %s/%s: %s", base_u, quote_u, exc)
        return None


def fetch_fx_rates(
    *,
    reporting_currency: str = "GBP",
    currencies: list[str] | None = None,
) -> dict[str, Any]:
    """Return map foreign→reporting multipliers (1 unit foreign = X reporting)."""
    reporting = reporting_currency.upper()
    wanted = [c.upper() for c in (currencies or list(SUPPORTED_CURRENCIES))]
    rates: dict[str, float] = {reporting: 1.0}
    errors: dict[str, str] = {}
    for ccy in wanted:
        if ccy == reporting:
            continue
        spot = _spot_pair(ccy, reporting)
        if spot is None:
            errors[ccy] = "unavailable"
            continue
        rates[ccy] = round(float(spot), 6)
    return {
        "fetched_at": datetime.now(UTC).isoformat(),
        "reporting_currency": reporting,
        "rates": rates,  # multiply foreign price by rates[ccy] → reporting
        "errors": errors,
        "source": "yahoo_finance",
        "hedge_assumption": "none",
    }


def convert_prices_to_reporting(
    prices: dict[str, float],
    *,
    price_currencies: dict[str, str],
    reporting_currency: str = "GBP",
    rates: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """
    Convert a ticker→local-price map into reporting currency.

    ``rates`` maps foreign currency → reporting multiplier. Missing rates leave
    the local price unchanged and record an error (fail-open for single-currency books).
    """
    reporting = reporting_currency.upper()
    fx = rates
    meta: dict[str, Any]
    if fx is None:
        needed = sorted({(price_currencies.get(t) or reporting).upper() for t in prices})
        bundle = fetch_fx_rates(reporting_currency=reporting, currencies=needed)
        fx = dict(bundle.get("rates") or {})
        meta = bundle
    else:
        meta = {
            "reporting_currency": reporting,
            "rates": fx,
            "source": "provided",
            "hedge_assumption": "none",
        }

    converted: dict[str, float] = {}
    issues: list[str] = []
    for ticker, price in prices.items():
        ccy = (price_currencies.get(ticker) or reporting).upper()
        if ccy == reporting:
            converted[ticker] = float(price)
            continue
        mult = fx.get(ccy)
        if mult is None or mult <= 0:
            converted[ticker] = float(price)
            issues.append(f"{ticker}:{ccy}:no_rate")
            continue
        converted[ticker] = float(price) * float(mult)
    meta["conversion_issues"] = issues
    return converted, meta
