"""Stamp facts the statement payload, or a stored price file, already states.

A reporting currency is copied only from the statement payload. A positive
ordinary-share count is copied from the statement balance sheet. A price quote
currency is copied only when the history price or ``ftse350_ordinary_shares.json``
already names it. Nothing here is inferred from a ticker suffix.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from value_investor.ftse_gap_scan import share_count_from_balance
from value_investor.ftse_pound_cap import SOURCED_SHARES
from value_investor.storage import read_json, resolve_json_path, write_json

REPORTING_CURRENCY_KEYS = ("reporting_currency", "financialCurrency", "currency")
PRICE_QUOTE_NAME = "price_quote.json"
REPORTING_CURRENCY_NAME = "reporting_currency.json"
ORDINARY_SHARES_NAME = "ordinary_shares.json"


@dataclass(frozen=True)
class StatementStamps:
    ticker: str
    ordinary_shares: Path | None
    reporting_currency: Path | None
    price_quote: Path | None


def reporting_currency_from_payload(payload: dict[str, Any]) -> str | None:
    """Return a reporting currency the payload already carries. Do not guess."""

    for key in REPORTING_CURRENCY_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def price_quote_from_stored(
    ticker: str,
    *,
    history_price: Any = None,
    sourced_shares: dict[str, Any] | None = None,
) -> tuple[str, str] | None:
    """Quote currency already stated by the history entry or the shares file."""

    if isinstance(history_price, dict):
        for key in ("quote_currency", "currency"):
            value = history_price.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), "history price"
    entry = (sourced_shares or {}).get(ticker)
    if isinstance(entry, dict):
        value = entry.get("quote_currency")
        if isinstance(value, str) and value.strip():
            return value.strip(), SOURCED_SHARES
    return None


def stamp_statement(
    payload: dict[str, Any],
    sources_dir: Path,
    *,
    price_quote: tuple[str, str] | None = None,
) -> StatementStamps:
    """Write stamps beside one statement. Missing facts are left unstamped."""

    sources_dir = Path(sources_dir)
    ticker = str(payload.get("ticker") or sources_dir.parent.name)
    shares = share_count_from_balance(payload)
    share_path: Path | None = None
    if shares is not None:
        share_path = write_json(
            sources_dir / ORDINARY_SHARES_NAME,
            {"ticker": ticker, **shares},
            compact=True,
            compress=False,
        )
    currency = reporting_currency_from_payload(payload)
    currency_path: Path | None = None
    if currency is not None:
        currency_path = write_json(
            sources_dir / REPORTING_CURRENCY_NAME,
            {"ticker": ticker, "reporting_currency": currency},
            compact=True,
            compress=False,
        )
    quote_path: Path | None = None
    if price_quote is not None:
        quote, source = price_quote
        quote_path = write_json(
            sources_dir / PRICE_QUOTE_NAME,
            {"ticker": ticker, "quote_currency": quote, "source": source},
            compact=True,
            compress=False,
        )
    return StatementStamps(ticker, share_path, currency_path, quote_path)


def stamp_stored_statements(root: Path) -> list[StatementStamps]:
    """Stamp every stored annual statement under ``root``."""

    root = Path(root)
    sourced = _sourced_share_entries(root)
    history = _history_price_entries(root)
    results: list[StatementStamps] = []
    research = root / "docs/data/research"
    if not research.exists():
        return results
    for path in sorted(research.glob("*/sources/financials_annual.json")):
        payload = read_json(path)
        if not isinstance(payload, dict):
            continue
        ticker = path.parent.parent.name
        results.append(
            stamp_statement(
                payload,
                path.parent,
                price_quote=price_quote_from_stored(
                    ticker,
                    history_price=history.get(ticker),
                    sourced_shares=sourced,
                ),
            )
        )
    return results


def _sourced_share_entries(root: Path) -> dict[str, Any]:
    path = resolve_json_path(root / SOURCED_SHARES)
    if path is None:
        return {}
    payload = read_json(path)
    tickers = payload.get("tickers") if isinstance(payload, dict) else None
    return tickers if isinstance(tickers, dict) else {}


def _history_price_entries(root: Path) -> dict[str, Any]:
    from value_investor.ftse_pound_cap import SCREEN_PRICE_RUN_PREFIX

    history = root / "docs/data/history"
    paths = sorted(history.glob(f"run_{SCREEN_PRICE_RUN_PREFIX}_*.json.gz"))
    if not paths:
        paths = sorted(history.glob(f"run_{SCREEN_PRICE_RUN_PREFIX}_*.json"))
    if not paths:
        return {}
    payload = read_json(paths[-1])
    prices = payload.get("prices") if isinstance(payload, dict) else None
    if not isinstance(prices, dict):
        return {}
    # Floats carry no unit. Keep the raw entry so a dict can still name one.
    return {str(ticker): raw for ticker, raw in prices.items()}
