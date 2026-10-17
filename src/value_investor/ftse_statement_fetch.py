"""Fetch missing FTSE annual statements through the existing Yahoo path.

``ingest_research_sources`` already writes ``financials_annual.json`` from
``fetch_annual_financials`` (yfinance). A dry run returns that payload and
writes nothing. Writing persists that same payload; it does not fetch again.

A payload with no annual income, balance-sheet, or cash-flow year is recorded
beside the statement path and is not fetched again. yfinance needs no API key.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from value_investor.storage import resolve_json_path, write_json

StatementFetcher = Callable[..., dict[str, Any]]
Sleeper = Callable[[float], None]

STATEMENT_NAME = "financials_annual.json"
EMPTY_RECORD_NAME = "financials_annual_empty.json"
BLOOMSBURY = "BMY.L"


@dataclass(frozen=True)
class StatementFetch:
    ticker: str
    payload: dict[str, Any]
    written: Path | None
    dry_run: bool


@dataclass(frozen=True)
class StatementPersist:
    ticker: str
    outcome: str
    path: Path | None
    detail: str


def fetch_one_annual_statement(
    ticker: str,
    *,
    sources_dir: Path | None = None,
    fetcher: StatementFetcher | None = None,
) -> StatementFetch:
    """Fetch annual statements for one ticker.

    ``sources_dir`` None is a dry run. A path writes ``financials_annual.json``
    there, which is the file ``ingest_research_sources`` writes. The default
    fetcher is ``fetch_annual_financials`` (yfinance, no API key).
    """

    resolved = _require_ticker(ticker)
    payload = _call_fetcher(resolved, fetcher)
    written: Path | None = None
    result = StatementFetch(
        ticker=resolved,
        payload=payload,
        written=None,
        dry_run=sources_dir is None,
    )
    if sources_dir is not None:
        written = write_fetched_statement(result, sources_dir)
        result = StatementFetch(
            ticker=resolved,
            payload=payload,
            written=written,
            dry_run=False,
        )
    return result


def write_fetched_statement(result: StatementFetch, sources_dir: Path) -> Path:
    """Write the dry-run payload. Does not fetch again."""

    return write_json(
        Path(sources_dir) / STATEMENT_NAME,
        result.payload,
        compact=True,
        compress=False,
    )


def bloomsbury_first(tickers: list[str]) -> list[str]:
    """Keep scan order, with Bloomsbury ahead of the other missing names."""

    ordered: list[str] = []
    for ticker in tickers:
        resolved = str(ticker).strip()
        if resolved and resolved not in ordered:
            ordered.append(resolved)
    if BLOOMSBURY not in ordered:
        return ordered
    return [BLOOMSBURY, *[ticker for ticker in ordered if ticker != BLOOMSBURY]]


def sources_dir_for(root: Path, ticker: str) -> Path:
    return Path(root) / "docs/data/research" / _require_ticker(ticker) / "sources"


def annual_statement_path(root: Path, ticker: str) -> Path | None:
    return resolve_json_path(sources_dir_for(root, ticker) / STATEMENT_NAME)


def empty_record_path(root: Path, ticker: str) -> Path | None:
    return resolve_json_path(sources_dir_for(root, ticker) / EMPTY_RECORD_NAME)


def payload_has_annual_statement(payload: dict[str, Any]) -> bool:
    summary = statement_key_summary(payload)
    return any(summary[key] > 0 for key in ("income_statement", "balance_sheet", "cash_flow"))


def persist_missing_annual_statements(
    tickers: list[str],
    *,
    root: Path,
    fetcher: StatementFetcher | None = None,
    sleeper: Sleeper | None = None,
    pause_seconds: float | None = None,
    attempts: int | None = None,
) -> list[StatementPersist]:
    """Write statements the caller lists, skipping names already stored or recorded empty.

    The pause and the attempt count come from the yfinance client in ``fetch.py``.
    A payload with no annual year is recorded once. A later call does not fetch it again.
    """

    root = Path(root)
    pause, attempt_limit, transient = _pace(pause_seconds, attempts)
    wait = sleeper or time.sleep
    results: list[StatementPersist] = []
    fetched = False
    for ticker in bloomsbury_first(tickers):
        if annual_statement_path(root, ticker) is not None:
            results.append(
                StatementPersist(ticker, "skipped_present", annual_statement_path(root, ticker), "")
            )
            continue
        if empty_record_path(root, ticker) is not None:
            results.append(
                StatementPersist(
                    ticker,
                    "skipped_empty",
                    empty_record_path(root, ticker),
                    "already recorded as returning nothing",
                )
            )
            continue
        if fetched and pause > 0:
            wait(pause)
        fetched = True
        outcome = _persist_one(
            ticker,
            root=root,
            fetcher=fetcher,
            sleeper=wait,
            pause_seconds=pause,
            attempts=attempt_limit,
            transient=transient,
        )
        results.append(outcome)
    return results


def _persist_one(
    ticker: str,
    *,
    root: Path,
    fetcher: StatementFetcher | None,
    sleeper: Sleeper,
    pause_seconds: float,
    attempts: int,
    transient: Callable[[BaseException], bool],
) -> StatementPersist:
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            dry = fetch_one_annual_statement(ticker, fetcher=fetcher)
        except Exception as exc:  # noqa: BLE001 — record the client error, do not invent a statement
            last_error = exc
            if attempt >= attempts or not transient(exc):
                break
            sleeper(pause_seconds * attempt)
            continue
        if not payload_has_annual_statement(dry.payload):
            path = _record_empty(root, ticker, payload=dry.payload, error=None)
            return StatementPersist(ticker, "empty", path, "no annual year in the payload")
        path = write_fetched_statement(dry, sources_dir_for(root, ticker))
        return StatementPersist(ticker, "written", path, "")
    message = str(last_error) if last_error is not None else "fetch failed"
    path = _record_empty(root, ticker, payload=None, error=message)
    return StatementPersist(ticker, "error", path, message)


def _record_empty(
    root: Path,
    ticker: str,
    *,
    payload: dict[str, Any] | None,
    error: str | None,
) -> Path:
    record: dict[str, Any] = {"ticker": ticker}
    if error:
        record["reason"] = "error"
        record["error"] = error
    else:
        summary = statement_key_summary(payload or {})
        record["reason"] = "empty"
        record["income_years"] = summary["income_statement"]
        record["balance_years"] = summary["balance_sheet"]
        record["cashflow_years"] = summary["cash_flow"]
        fetched_at = (payload or {}).get("fetched_at")
        if isinstance(fetched_at, str) and fetched_at.strip():
            record["fetched_at"] = fetched_at
    return write_json(
        sources_dir_for(root, ticker) / EMPTY_RECORD_NAME,
        record,
        compact=True,
        compress=False,
    )


def _require_ticker(ticker: str) -> str:
    resolved = str(ticker).strip()
    if not resolved:
        raise ValueError("ticker is required; this fetch does not walk the FTSE list")
    return resolved


def _call_fetcher(ticker: str, fetcher: StatementFetcher | None) -> dict[str, Any]:
    if fetcher is None:
        from value_investor.research.ingest import fetch_annual_financials

        fetcher = fetch_annual_financials
    payload = fetcher(ticker)
    if not isinstance(payload, dict):
        raise TypeError(f"{ticker} fetcher returned {type(payload).__name__}, expected a dict")
    return payload


def _pace(
    pause_seconds: float | None,
    attempts: int | None,
) -> tuple[float, int, Callable[[BaseException], bool]]:
    from value_investor.fetch import (
        FETCH_ATTEMPTS,
        FETCH_RETRY_DELAY_SECONDS,
        _is_transient_fetch_error,
    )

    pause = FETCH_RETRY_DELAY_SECONDS if pause_seconds is None else pause_seconds
    attempt_limit = FETCH_ATTEMPTS if attempts is None else attempts
    if attempt_limit < 1:
        raise ValueError("attempts must be at least 1")
    return float(pause), int(attempt_limit), _is_transient_fetch_error


def statement_key_summary(payload: dict[str, Any]) -> dict[str, int]:
    """Count stored year keys. Does not add or rescale a figure."""

    summary: dict[str, int] = {}
    for key in ("income_statement", "balance_sheet", "cash_flow"):
        block = payload.get(key)
        summary[key] = len(block) if isinstance(block, dict) else 0
    return summary
