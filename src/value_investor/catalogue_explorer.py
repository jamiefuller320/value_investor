"""One Trading 212 catalogue name per idle spare slot.

Phase E. After the seated backlog has nothing left to fetch, either spare
stream takes the next STOCK the library does not already hold. Venue order is US, then
Xetra (DE), then LSE. One name is fetched to completion and the seconds are
stored on ``docs/data/library/catalogue_explorer.json``. Fundamentals are
screened on that same walk. The stream stops once the filing list and the
buy signal are saved. A buy or strong buy is queued for a separate research
ingest and is not downloaded inside the stream. A later pass can see
where a parallel fetch would help. This module does not parallelise, and it
does not add the name to an index or an investment book.

The name match stays the catalogue's own ticker, ISIN, and symbol. Held
overlay rows are skipped. A miss is still marked completed so the cursor
cannot sit on the same line.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.storage import read_json, write_json
from value_investor.t212_coverage import t212_symbol, t212_venue

VENUE_ORDER = ("US", "DE", "LSE")
STATE_NAME = "catalogue_explorer.json"
EXPLORER_TITLE = "Catalogue explorer"
BODY_CAP = 4
BUY_SIGNALS = frozenset({"buy", "strong_buy"})
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

FetchFn = Callable[[dict[str, Any]], Any]


def state_path(library_root: Path | None = None) -> Path:
    root = Path(library_root) if library_root is not None else DEFAULT_LIBRARY_ROOT
    return root / STATE_NAME


def load_state(library_root: Path | None = None) -> dict[str, Any]:
    path = state_path(library_root)
    if not path.exists():
        return {"schema_version": 1, "completed": [], "runs": [], "last": None}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {"schema_version": 1, "completed": [], "runs": [], "last": None}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "completed": [], "runs": [], "last": None}
    payload.setdefault("completed", [])
    payload.setdefault("runs", [])
    return payload


def save_state(state: dict[str, Any], library_root: Path | None = None) -> Path:
    path = state_path(library_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, state, compact=False)
    return path


def yahoo_ticker(t212_ticker: str) -> str | None:
    """Map a catalogue ticker onto the symbol the filing fetchers expect."""
    venue = t212_venue(t212_ticker)
    symbol = t212_symbol(t212_ticker)
    if not venue or not symbol:
        return None
    if venue == "US":
        return symbol
    if venue == "DE":
        return f"{symbol}.DE"
    if venue == "LSE":
        return f"{symbol}.L"
    return None


def load_held_keys(library_root: Path | None = None) -> set[str]:
    """ISINs, catalogue tickers, and yahoo symbols already on the overlay."""
    root = Path(library_root) if library_root is not None else DEFAULT_LIBRARY_ROOT
    folder = root / "t212_coverage" / "by_market"
    keys: set[str] = set()
    if not folder.exists():
        return keys
    for path in sorted(folder.glob("*.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for field in ("isin", "t212_isin", "t212_ticker", "ticker"):
                token = str(row.get(field) or "").strip().upper()
                if token:
                    keys.add(token)
    return keys


def _held(row: dict[str, Any], held: set[str]) -> bool:
    raw = str(row.get("ticker") or "").strip()
    ticker = raw.upper()
    isin = str(row.get("isin") or "").strip().upper()
    # Venue letters such as the LSE ``l`` are case-sensitive. Uppercase only the key.
    yahoo = (yahoo_ticker(raw) or "").upper()
    if ticker and ticker in held:
        return True
    if isin and isin in held:
        return True
    if yahoo and yahoo in held:
        return True
    return False


def next_unheld(
    instruments: list[dict[str, Any]],
    *,
    held: set[str],
    completed: set[str],
) -> dict[str, Any] | None:
    """Next STOCK in venue order, then ticker order, that the library does not hold."""
    buckets: dict[str, list[dict[str, Any]]] = {venue: [] for venue in VENUE_ORDER}
    for row in instruments:
        if not isinstance(row, dict):
            continue
        if str(row.get("type") or "").upper() != "STOCK":
            continue
        ticker = str(row.get("ticker") or "").strip()
        venue = t212_venue(ticker)
        if venue not in buckets or not ticker:
            continue
        if ticker.upper() in completed or _held(row, held):
            continue
        buckets[venue].append(row)
    for venue in VENUE_ORDER:
        rows = sorted(buckets[venue], key=lambda item: str(item.get("ticker") or ""))
        if rows:
            return rows[0]
    return None


def _slim_rows(rows: list[Any]) -> list[dict[str, Any]]:
    slim: list[dict[str, Any]] = []
    for row in rows[:20]:
        if not isinstance(row, dict):
            slim.append({"value": str(row)[:200]})
            continue
        slim.append(
            {
                "title": row.get("title") or row.get("name"),
                "date": row.get("date") or row.get("published") or row.get("period_end"),
                "url": row.get("url") or row.get("document_url"),
                "has_body": bool(row.get("has_body") or row.get("body")),
            }
        )
    return slim


def complete_one(
    state: dict[str, Any],
    instrument: dict[str, Any],
    *,
    fetch: FetchFn,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch one catalogue name and record it, including a miss or an error."""
    ticker = str(instrument.get("ticker") or "").strip()
    started = time.perf_counter()
    outcome = "miss"
    detail: dict[str, Any] = {"rows": 0}
    try:
        payload = fetch(instrument)
        filings, extra = _unpack_fetch(payload)
        outcome = "saved" if filings else "miss"
        detail = {"rows": len(filings), "filings": _slim_rows(filings), **extra}
    except Exception as exc:  # noqa: BLE001 — a failed name must still move the cursor
        outcome = "error"
        detail = {"rows": 0, "error": str(exc)}
    seconds = round(time.perf_counter() - started, 3)
    stamp = (now or datetime.now(UTC)).isoformat()
    record = {
        "t212_ticker": ticker,
        "venue": t212_venue(ticker),
        "yahoo": yahoo_ticker(ticker),
        "isin": instrument.get("isin"),
        "name": instrument.get("shortName") or instrument.get("name"),
        "seconds": seconds,
        "outcome": outcome,
        "at": stamp,
        **detail,
    }
    completed = [str(item).upper() for item in (state.get("completed") or [])]
    token = ticker.upper()
    if token and token not in completed:
        completed.append(token)
    state["completed"] = completed
    runs = [row for row in (state.get("runs") or []) if isinstance(row, dict)]
    runs.append({key: value for key, value in record.items() if key != "filings"})
    state["runs"] = runs[-40:]
    state["last"] = record
    state["updated_at"] = stamp
    state["schema_version"] = 1
    return record


def default_fetch(instrument: dict[str, Any]) -> list[dict[str, Any]]:
    """Filing list for one name, then up to four bodies. No index membership."""
    ticker = str(instrument.get("ticker") or "")
    venue = t212_venue(ticker)
    yahoo = yahoo_ticker(ticker) or ""
    company = str(instrument.get("shortName") or instrument.get("name") or yahoo)
    rows: list[dict[str, Any]] = []
    if venue == "US":
        from value_investor.research.filings import fetch_filings_sec_edgar

        rows = list(fetch_filings_sec_edgar(ticker=yahoo) or [])
    elif venue == "DE":
        from value_investor.research.filings import fetch_filings_esef_direct

        rows = list(fetch_filings_esef_direct(company_name=company, ticker=yahoo) or [])
    elif venue == "LSE":
        from value_investor.research.companies_house import fetch_filings_companies_house

        rows = list(fetch_filings_companies_house(ticker=yahoo, company_name=company) or [])
    from value_investor.research.filings import fetch_filing_body

    saved = 0
    for row in rows:
        if saved >= BODY_CAP:
            break
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or row.get("document_url") or "")
        if not url:
            continue
        body = fetch_filing_body(url)
        if body:
            row["has_body"] = True
            saved += 1
    return rows


def _unpack_fetch(payload: Any) -> tuple[list[Any], dict[str, Any]]:
    if isinstance(payload, dict) and "filings" in payload:
        filings = list(payload.get("filings") or [])
        extra: dict[str, Any] = {}
        if payload.get("screen") is not None:
            extra["screen"] = payload["screen"]
        if payload.get("full_ingest") is not None:
            extra["full_ingest"] = payload["full_ingest"]
        return filings, extra
    if payload is None:
        return [], {}
    return list(payload), {}


def screen_metrics_row(row: dict[str, Any]) -> dict[str, Any]:
    """Score one fundamentals row with the same buy signals as the library screen."""
    import pandas as pd

    from value_investor.data_quality import add_data_quality_scores
    from value_investor.models.ranking import compute_derived_columns
    from value_investor.scoring import evaluate_universe, summarize_by_ticker
    from value_investor.sector_scoring import add_sector_scores
    from value_investor.signals import build_signals

    frame = pd.DataFrame([row])
    if "ticker" not in frame.columns:
        frame["ticker"] = ""
    frame = compute_derived_columns(frame)
    for col in (
        "roic_proxy",
        "fcf_yield",
        "ev_ebitda",
        "ev_ebit",
        "earnings_yield_ebit",
        "earnings_yield_pe",
        "ncav_to_market",
        "asset_turnover",
        "total_assets",
        "total_current_liabilities",
        "ncav",
    ):
        if col not in frame.columns:
            frame[col] = pd.NA
    frame = add_data_quality_scores(frame)
    frame = add_sector_scores(frame)
    model_results = evaluate_universe(frame)
    summary = summarize_by_ticker(model_results)
    signals = build_signals(frame, model_results, summary)
    if signals.empty:
        return {"signal": None, "fits": False, "data_quality_score": None}
    signal = str(signals.iloc[0].get("signal") or "")
    quality = signals.iloc[0].get("data_quality_score")
    quality_value = None if quality is None or pd.isna(quality) else float(quality)
    return {
        "signal": signal or None,
        "fits": signal in BUY_SIGNALS,
        "data_quality_score": quality_value,
    }


def _slim_ingest(result: dict[str, Any], *, seconds: float) -> dict[str, Any]:
    summary = (
        result.get("filings_summary") if isinstance(result.get("filings_summary"), dict) else {}
    )
    return {
        "seconds": seconds,
        "financial_years": result.get("financial_years"),
        "filings_summary": summary,
        "snapshot_path": result.get("snapshot_path"),
        "error": result.get("error"),
    }


def default_full_ingest(
    instrument: dict[str, Any],
    screen: dict[str, Any],
    library_root: Path,
) -> dict[str, Any]:
    """Research ingest for one name that already fits the buy screen."""
    from value_investor.research.ingest import ingest_research_sources

    ticker = str(instrument.get("ticker") or "")
    yahoo = yahoo_ticker(ticker) or ticker
    company = str(instrument.get("shortName") or instrument.get("name") or yahoo)
    safe = _SAFE.sub("_", yahoo)
    sources = Path(library_root) / "catalogue_explorer" / "research" / safe / "sources"
    return ingest_research_sources(
        ticker=yahoo,
        company_name=company,
        screening_snapshot={
            "ticker": yahoo,
            "signal": screen.get("signal"),
            "fits": True,
        },
        sources_dir=sources,
        include_filings=True,
    )


def default_walk(
    instrument: dict[str, Any],
    *,
    library_root: Path | None = None,
    filings_fetch: FetchFn | None = None,
    metrics_fetch: Callable[[str, str], Any] | None = None,
    screen: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Filing list and a buy signal. Research ingest is a later handoff."""
    del library_root
    fetch_rows = filings_fetch or default_fetch
    filings = list(fetch_rows(instrument) or [])
    screen_started = time.perf_counter()
    screen_result: dict[str, Any]
    try:
        if screen is not None:
            screen_result = dict(screen(instrument))
        else:
            from value_investor.fetch import fetch_company_metrics

            yahoo = yahoo_ticker(str(instrument.get("ticker") or "")) or ""
            company = str(instrument.get("shortName") or instrument.get("name") or yahoo)
            loader = metrics_fetch or fetch_company_metrics
            metrics = loader(yahoo, company)
            row = metrics.to_dict() if hasattr(metrics, "to_dict") else dict(metrics)
            row.setdefault("ticker", yahoo)
            screen_result = screen_metrics_row(row)
    except Exception as exc:  # noqa: BLE001 — the cursor still records the screen miss
        screen_result = {"signal": None, "fits": False, "error": str(exc)}
    screen_result["seconds"] = round(time.perf_counter() - screen_started, 3)
    return {"filings": filings, "screen": screen_result}


def _instrument_rows(index: dict[str, Any]) -> list[dict[str, Any]]:
    by_ticker = index.get("by_ticker") if isinstance(index, dict) else None
    if not isinstance(by_ticker, dict):
        return []
    rows: list[dict[str, Any]] = []
    for ticker, row in by_ticker.items():
        if isinstance(row, dict):
            rows.append({**row, "ticker": row.get("ticker") or ticker})
    return rows


def write_name_artifact(
    library_root: Path,
    record: dict[str, Any],
) -> Path | None:
    ticker = str(record.get("t212_ticker") or "")
    if not ticker:
        return None
    safe = _SAFE.sub("_", ticker)
    path = Path(library_root) / "catalogue_explorer" / "names" / f"{safe}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record, compact=False)
    return path


def explore_one(
    library_root: Path | None = None,
    *,
    fetch: FetchFn | None = None,
    instruments: list[dict[str, Any]] | None = None,
    held: set[str] | None = None,
) -> dict[str, Any]:
    """Take one unheld STOCK, or report that the three venues are covered."""
    root = Path(library_root) if library_root is not None else DEFAULT_LIBRARY_ROOT
    state = load_state(root)
    if instruments is None:
        from value_investor.t212_coverage import load_catalogue_index

        index = load_catalogue_index(root)
        if not isinstance(index, dict):
            return {
                "action": "idle",
                "reason": "no_catalogue",
                "completed": len(state.get("completed") or []),
            }
        instruments = _instrument_rows(index)
    held_keys = held if held is not None else load_held_keys(root)
    completed = {str(item).upper() for item in (state.get("completed") or [])}
    chosen = next_unheld(instruments, held=held_keys, completed=completed)
    if chosen is None:
        return {
            "action": "idle",
            "reason": "catalogue_covered",
            "completed": len(completed),
            "venues": list(VENUE_ORDER),
        }
    walker = fetch or (lambda instrument: default_walk(instrument, library_root=root))
    record = complete_one(state, chosen, fetch=walker)
    queued = queue_handoff(state, record)
    save_state(state, root)
    write_name_artifact(root, record)
    if queued is not None:
        record["handoff_saved"] = True
    return {"action": "ran", **record}


def queue_handoff(state: dict[str, Any], record: dict[str, Any]) -> dict[str, Any] | None:
    """Record a buy or strong buy for the separate ingest routine."""
    screen = record.get("screen")
    if not isinstance(screen, dict) or not screen.get("fits"):
        return None
    signal = str(screen.get("signal") or "")
    if signal not in BUY_SIGNALS:
        return None
    ticker = str(record.get("t212_ticker") or "").strip()
    if not ticker:
        return None
    handoffs = [row for row in (state.get("handoffs") or []) if isinstance(row, dict)]
    for row in handoffs:
        if str(row.get("t212_ticker") or "").upper() == ticker.upper():
            record["handoff"] = {
                "status": row.get("status") or "pending",
                "signal": row.get("signal") or signal,
                "t212_ticker": ticker,
            }
            return row
    item = {
        "t212_ticker": ticker,
        "yahoo": record.get("yahoo"),
        "name": record.get("name"),
        "signal": signal,
        "status": "pending",
        "queued_at": record.get("at"),
    }
    handoffs.append(item)
    state["handoffs"] = handoffs
    record["handoff"] = {"status": "pending", "signal": signal, "t212_ticker": ticker}
    state["last"] = record
    return item


def run_one_handoff(
    library_root: Path | None = None,
    *,
    ingest: Callable[[dict[str, Any], dict[str, Any], Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ingest one queued buy. The spare stream does not call this."""
    root = Path(library_root) if library_root is not None else DEFAULT_LIBRARY_ROOT
    state = load_state(root)
    handoffs = [row for row in (state.get("handoffs") or []) if isinstance(row, dict)]
    pending = next((row for row in handoffs if row.get("status") == "pending"), None)
    if pending is None:
        return {"action": "idle", "reason": "no_handoff", "pending": 0}
    instrument = {
        "ticker": pending.get("t212_ticker"),
        "shortName": pending.get("name"),
    }
    screen = {"signal": pending.get("signal"), "fits": True}
    started = time.perf_counter()
    try:
        runner = ingest or default_full_ingest
        raw = runner(instrument, screen, root)
        pending["ingest"] = _slim_ingest(raw if isinstance(raw, dict) else {}, seconds=0.0)
        pending["status"] = "done"
        pending.pop("error", None)
    except Exception as exc:  # noqa: BLE001 — a failed handoff stays visible and is not retried here
        pending["status"] = "error"
        pending["error"] = str(exc)
        pending["ingest"] = {"error": str(exc)}
    pending["ingest"]["seconds"] = round(time.perf_counter() - started, 3)
    pending["finished_at"] = datetime.now(UTC).isoformat()
    state["handoffs"] = handoffs
    state["updated_at"] = pending["finished_at"]
    save_state(state, root)
    return {"action": "ran", **pending}


def finding_summary(state: dict[str, Any] | None) -> str:
    if not state:
        return (
            "Catalogue explorer has not started. An idle spare stream slot "
            "takes one unheld Trading 212 stock, US then Xetra then LSE, and "
            "records how many seconds that one name took."
        )
    completed = state.get("completed") or []
    last = state.get("last") if isinstance(state.get("last"), dict) else None
    count = len(completed) if isinstance(completed, list) else 0
    if not last:
        return f"Catalogue explorer has {count} completed names and no last timing record."
    return (
        f"Completed {count} catalogue names, one at a time. "
        f"Last {last.get('t212_ticker')} ({last.get('venue')}) took "
        f"{last.get('seconds')}s, outcome {last.get('outcome')}"
        + (
            f", screen {last['screen'].get('signal')}."
            if isinstance(last.get("screen"), dict)
            else "."
        )
    )
