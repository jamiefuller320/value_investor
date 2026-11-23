"""Trading 212 catalogue walk for the two spare slots.

After the seated backlog has nothing left to fetch, stream 1 screens the next
STOCK the library does not already hold, commits, and takes another, until the
job must stop so that commit can finish. Venue order is US, then Xetra (DE),
then LSE. Stream 2 does not take catalogue names. It ingests the buy queue one
name at a time and commits each one. An empty queue exits.

Each new row stores the ticker, venue, total seconds, screen seconds, signal,
and outcome on ``docs/data/library/catalogue_explorer.json``. A buy or strong
buy is queued. The research ingest is stream 2's handoff, not part of the
screen. Both lanes reload that file before they write, and a push merges the
two copies, so a handoff commit does not wipe the cursor and a screen commit
does not wipe a finished ingest.

This module does not add a third screener, and it does not add the name to an
index or an investment book. Held overlay rows are skipped. A miss is still
marked completed so the cursor cannot sit on the same line.

A cursor saved before the venue-market quote (``cursor_epoch`` below
``CURSOR_EPOCH``) is cleared on the next screen or handoff. Those rows were
scored on the wrong Yahoo symbol. A later merge keeps the new epoch and does
not union the old names back.
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
# Yahoo market ids for the three catalogue venues. A bare US symbol is rewritten
# to ``.L`` when the quote is fetched with no market.
_VENUE_QUOTE_MARKET = {"US": "us", "DE": "dax", "LSE": "lse"}
# Bump when a saved cursor must be walked again. Epoch 1 was the London-symbol
# screen. Epoch 2 rescreens US, Xetra, and LSE with the venue market.
CURSOR_EPOCH = 2
CURSOR_RESET_REASON = (
    "Rescreen US, Xetra, and LSE. Prior rows were scored on the wrong Yahoo symbol."
)
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


def _cursor_epoch(state: dict[str, Any]) -> int:
    try:
        return int(state.get("cursor_epoch") or 0)
    except (TypeError, ValueError):
        return 0


def restart_cursor(state: dict[str, Any]) -> bool:
    """Drop a cursor scored before the venue-market quote. Keep a current one."""
    if _cursor_epoch(state) >= CURSOR_EPOCH:
        return False
    state["cursor_epoch"] = CURSOR_EPOCH
    state["cursor_reset_reason"] = CURSOR_RESET_REASON
    state["completed"] = []
    state["runs"] = []
    state["handoffs"] = []
    state["last"] = None
    state["totals"] = _empty_totals()
    state["schema_version"] = 1
    state["updated_at"] = datetime.now(UTC).isoformat()
    return True


def _load_ready_state(library_root: Path) -> dict[str, Any]:
    """Load the cursor, clearing one that was scored on the wrong symbol."""
    state = load_state(library_root)
    if restart_cursor(state):
        save_state(state, library_root)
    return state


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


def count_skipped_held(instruments: list[dict[str, Any]], held: set[str]) -> int:
    """Held STOCK lines on US, Xetra, and LSE. A count, not a second queue."""
    skipped = 0
    for row in instruments:
        if not isinstance(row, dict):
            continue
        if str(row.get("type") or "").upper() != "STOCK":
            continue
        ticker = str(row.get("ticker") or "").strip()
        if t212_venue(ticker) not in VENUE_ORDER:
            continue
        if _held(row, held):
            skipped += 1
    return skipped


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


def _fetch_record(
    instrument: dict[str, Any],
    *,
    fetch: FetchFn,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Time one catalogue fetch. Does not write the shared state file."""
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
    record = {
        "t212_ticker": ticker,
        "venue": t212_venue(ticker),
        "yahoo": yahoo_ticker(ticker),
        "isin": instrument.get("isin"),
        "name": instrument.get("shortName") or instrument.get("name"),
        "seconds": round(time.perf_counter() - started, 3),
        "outcome": outcome,
        "at": (now or datetime.now(UTC)).isoformat(),
        **detail,
    }
    _stamp_screen_fields(record)
    return record


def complete_one(
    state: dict[str, Any],
    instrument: dict[str, Any],
    *,
    fetch: FetchFn,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch one catalogue name and record it, including a miss or an error."""
    record = _fetch_record(instrument, fetch=fetch, now=now)
    apply_completion(state, record)
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

            raw_ticker = str(instrument.get("ticker") or "")
            yahoo = yahoo_ticker(raw_ticker) or ""
            company = str(instrument.get("shortName") or instrument.get("name") or yahoo)
            market = _VENUE_QUOTE_MARKET.get(t212_venue(raw_ticker) or "")
            if metrics_fetch is not None:
                metrics = metrics_fetch(yahoo, company)
            else:
                metrics = fetch_company_metrics(yahoo, company, market=market)
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
    """Take one unheld STOCK, or report that the three venues are covered.

    The fetch runs before the state file is reloaded, so a handoff that finished
    while this name was screening is still there when the screen is saved.
    """
    root = Path(library_root) if library_root is not None else DEFAULT_LIBRARY_ROOT
    state = _load_ready_state(root)
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
    record = _fetch_record(chosen, fetch=walker)
    fresh = _load_ready_state(root)
    queued = apply_completion(
        fresh,
        record,
        skipped_held=count_skipped_held(instruments, held_keys),
    )
    save_state(fresh, root)
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


def _stamp_screen_fields(record: dict[str, Any]) -> None:
    """Every new row keeps ticker, venue, total seconds, screen seconds, signal, outcome."""
    screen = record.get("screen") if isinstance(record.get("screen"), dict) else None
    if screen is None:
        record["screen_seconds"] = None
        record["signal"] = None
        return
    record["screen_seconds"] = screen.get("seconds")
    record["signal"] = screen.get("signal")


def _row_screen_seconds(row: dict[str, Any]) -> float | None:
    if row.get("screen_seconds") is not None:
        try:
            return float(row["screen_seconds"])
        except (TypeError, ValueError):
            return None
    screen = row.get("screen")
    if isinstance(screen, dict) and screen.get("seconds") is not None:
        try:
            return float(screen["seconds"])
        except (TypeError, ValueError):
            return None
    return None


def _row_signal(row: dict[str, Any]) -> str | None:
    if row.get("signal") is not None:
        return str(row["signal"])
    screen = row.get("screen")
    if isinstance(screen, dict) and screen.get("signal") is not None:
        return str(screen["signal"])
    return None


def _empty_totals() -> dict[str, Any]:
    return {
        "screened": 0,
        "signals": {},
        "signals_n": 0,
        "screen_seconds_sum": 0.0,
        "screen_seconds_n": 0,
        "outcomes": {},
    }


def _add_row_to_totals(state: dict[str, Any], record: dict[str, Any]) -> None:
    totals = state.get("totals")
    if not isinstance(totals, dict):
        totals = _empty_totals()
    signals = totals.get("signals")
    if not isinstance(signals, dict):
        signals = {}
    signal = _row_signal(record)
    key = signal if signal else "none"
    signals[key] = int(signals.get(key) or 0) + 1
    totals["signals"] = signals
    totals["signals_n"] = int(totals.get("signals_n") or 0) + 1
    seconds = _row_screen_seconds(record)
    if seconds is not None:
        totals["screen_seconds_sum"] = float(totals.get("screen_seconds_sum") or 0.0) + seconds
        totals["screen_seconds_n"] = int(totals.get("screen_seconds_n") or 0) + 1
    outcomes = totals.get("outcomes")
    if not isinstance(outcomes, dict):
        outcomes = {}
    outcome = str(record.get("outcome") or "unknown")
    outcomes[outcome] = int(outcomes.get(outcome) or 0) + 1
    totals["outcomes"] = outcomes
    state["totals"] = totals


def _backfill_totals_from_runs(state: dict[str, Any]) -> None:
    """Count rows already on file once, when the saved runs still cover them."""
    totals = state.get("totals") if isinstance(state.get("totals"), dict) else None
    completed = [str(item).upper() for item in (state.get("completed") or []) if str(item).strip()]
    already = int((totals or {}).get("signals_n") or 0)
    if totals is not None and already == len(completed):
        return
    if already > 0:
        return
    by_ticker: dict[str, dict[str, Any]] = {}
    for row in state.get("runs") or []:
        if not isinstance(row, dict):
            continue
        token = str(row.get("t212_ticker") or "").upper()
        if token:
            by_ticker[token] = row
    if any(token not in by_ticker for token in completed):
        return
    state["totals"] = _empty_totals()
    for token in completed:
        _add_row_to_totals(state, by_ticker[token])
    state["totals"]["screened"] = len(completed)


def apply_completion(
    state: dict[str, Any],
    record: dict[str, Any],
    *,
    skipped_held: int | None = None,
) -> dict[str, Any] | None:
    """Merge one screen onto ``state``. Does not drop a handoff it did not queue."""
    _backfill_totals_from_runs(state)
    ticker = str(record.get("t212_ticker") or "").strip()
    token = ticker.upper()
    completed = [str(item).upper() for item in (state.get("completed") or []) if str(item).strip()]
    if token and token not in completed:
        completed.append(token)
        _add_row_to_totals(state, record)
    state["completed"] = completed
    if isinstance(state.get("totals"), dict):
        state["totals"]["screened"] = len(completed)
    runs = [row for row in (state.get("runs") or []) if isinstance(row, dict)]
    slim = {key: value for key, value in record.items() if key != "filings"}
    stamp = str(record.get("at") or "")
    if not any(
        str(row.get("t212_ticker") or "") == ticker and str(row.get("at") or "") == stamp
        for row in runs
    ):
        runs.append(slim)
    state["runs"] = runs[-40:]
    queued = queue_handoff(state, record)
    state["last"] = record
    state["updated_at"] = record.get("at")
    state["schema_version"] = 1
    if skipped_held is not None:
        state["skipped_held"] = int(skipped_held)
    return queued


def run_one_handoff(
    library_root: Path | None = None,
    *,
    ingest: Callable[[dict[str, Any], dict[str, Any], Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ingest one queued buy. Stream 2 loops this. Stream 1 does not call it.

    The ingest runs before the state file is reloaded, so a screen saved during
    the parse stays on the cursor.
    """
    root = Path(library_root) if library_root is not None else DEFAULT_LIBRARY_ROOT
    state = _load_ready_state(root)
    handoffs = [row for row in (state.get("handoffs") or []) if isinstance(row, dict)]
    pending = next((row for row in handoffs if row.get("status") == "pending"), None)
    if pending is None:
        return {"action": "idle", "reason": "no_handoff", "pending": 0}
    ticker = str(pending.get("t212_ticker") or "")
    instrument = {
        "ticker": pending.get("t212_ticker"),
        "shortName": pending.get("name"),
    }
    screen = {"signal": pending.get("signal"), "fits": True}
    started = time.perf_counter()
    update: dict[str, Any]
    try:
        runner = ingest or default_full_ingest
        raw = runner(instrument, screen, root)
        update = {
            "status": "done",
            "ingest": _slim_ingest(raw if isinstance(raw, dict) else {}, seconds=0.0),
        }
    except Exception as exc:  # noqa: BLE001 — a failed handoff stays visible and is not retried here
        update = {
            "status": "error",
            "error": str(exc),
            "ingest": {"error": str(exc)},
        }
    ingest_row = update.get("ingest")
    if not isinstance(ingest_row, dict):
        ingest_row = {}
        update["ingest"] = ingest_row
    ingest_row["seconds"] = round(time.perf_counter() - started, 3)
    update["finished_at"] = datetime.now(UTC).isoformat()
    fresh = _load_ready_state(root)
    row, changed = _apply_handoff_update(fresh, ticker, update)
    if row is None:
        return {"action": "idle", "reason": "no_handoff", "pending": 0}
    if not changed:
        idle = {key: value for key, value in row.items() if key != "_unchanged"}
        return {"action": "idle", "reason": "already_finished", **idle}
    save_state(fresh, root)
    return {"action": "ran", **row}


def _apply_handoff_update(
    state: dict[str, Any],
    ticker: str,
    update: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    handoffs = [row for row in (state.get("handoffs") or []) if isinstance(row, dict)]
    row = next(
        (item for item in handoffs if str(item.get("t212_ticker") or "").upper() == ticker.upper()),
        None,
    )
    if row is None:
        return None, False
    if row.get("status") != "pending":
        return row, False
    row.update(update)
    if update.get("status") != "error":
        row.pop("error", None)
    state["handoffs"] = handoffs
    state["updated_at"] = update.get("finished_at")
    return row, True


_HANDOFF_RANK = {"pending": 0, "error": 1, "done": 2}


def _prefer_handoff(current: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    current_rank = _HANDOFF_RANK.get(str(current.get("status") or ""), 0)
    other_rank = _HANDOFF_RANK.get(str(other.get("status") or ""), 0)
    if other_rank > current_rank:
        winner, loser = other, current
    elif other_rank < current_rank:
        winner, loser = current, other
    else:
        other_at = str(other.get("finished_at") or other.get("queued_at") or "")
        current_at = str(current.get("finished_at") or current.get("queued_at") or "")
        winner, loser = (other, current) if other_at >= current_at else (current, other)
    merged = dict(loser)
    merged.update({key: value for key, value in winner.items() if value is not None})
    if isinstance(winner.get("ingest"), dict):
        merged["ingest"] = winner["ingest"]
    elif isinstance(loser.get("ingest"), dict):
        merged["ingest"] = loser["ingest"]
    if loser.get("queued_at") and not merged.get("queued_at"):
        merged["queued_at"] = loser["queued_at"]
    return merged


def _row_for(state: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    token = ticker.upper()
    matches: list[dict[str, Any]] = []
    last = state.get("last")
    if isinstance(last, dict) and str(last.get("t212_ticker") or "").upper() == token:
        matches.append(last)
    for row in state.get("runs") or []:
        if isinstance(row, dict) and str(row.get("t212_ticker") or "").upper() == token:
            matches.append(row)
    if not matches:
        return None
    with_seconds = [row for row in matches if _row_screen_seconds(row) is not None]
    return with_seconds[-1] if with_seconds else matches[-1]


def _completed_tokens(state: dict[str, Any]) -> list[str]:
    completed: list[str] = []
    seen: set[str] = set()
    for item in state.get("completed") or []:
        token = str(item).upper()
        if token and token not in seen:
            seen.add(token)
            completed.append(token)
    return completed


def _merge_newer_epoch(winner: dict[str, Any], loser: dict[str, Any]) -> dict[str, Any]:
    """Keep the newer cursor. Do not union names scored on the previous epoch."""
    completed = _completed_tokens(winner)
    runs = [row for row in (winner.get("runs") or []) if isinstance(row, dict)]
    runs.sort(key=lambda row: str(row.get("at") or ""))
    handoffs = [dict(row) for row in (winner.get("handoffs") or []) if isinstance(row, dict)]
    totals = winner.get("totals") if isinstance(winner.get("totals"), dict) else None
    if totals is None:
        totals = _empty_totals()
    else:
        totals = {
            "screened": len(completed),
            "signals": dict(totals.get("signals") or {}),
            "signals_n": int(totals.get("signals_n") or 0),
            "screen_seconds_sum": float(totals.get("screen_seconds_sum") or 0.0),
            "screen_seconds_n": int(totals.get("screen_seconds_n") or 0),
            "outcomes": dict(totals.get("outcomes") or {}),
        }
    skipped = winner.get("skipped_held")
    if skipped is None:
        skipped = loser.get("skipped_held")
    updated = max(str(winner.get("updated_at") or ""), str(loser.get("updated_at") or "")) or None
    merged: dict[str, Any] = {
        "schema_version": 1,
        "cursor_epoch": _cursor_epoch(winner),
        "completed": completed,
        "runs": runs[-40:],
        "handoffs": handoffs,
        "last": winner.get("last") if isinstance(winner.get("last"), dict) else None,
        "updated_at": updated,
        "totals": totals,
    }
    reason = winner.get("cursor_reset_reason")
    if reason:
        merged["cursor_reset_reason"] = reason
    if skipped is not None:
        merged["skipped_held"] = skipped
    return merged


def merge_states(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Union two catalogue states. A finished ingest wins over a stale pending row.

    A higher ``cursor_epoch`` replaces the older cursor, so names scored on the
    wrong Yahoo symbol are not unioned back after the rescreen starts.
    """
    base_epoch = _cursor_epoch(base)
    incoming_epoch = _cursor_epoch(incoming)
    if base_epoch != incoming_epoch:
        if incoming_epoch > base_epoch:
            return _merge_newer_epoch(incoming, base)
        return _merge_newer_epoch(base, incoming)
    completed: list[str] = []
    seen: set[str] = set()
    for source in (base, incoming):
        for item in source.get("completed") or []:
            token = str(item).upper()
            if token and token not in seen:
                seen.add(token)
                completed.append(token)
    by_ticker: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for source in (base, incoming):
        for row in source.get("handoffs") or []:
            if not isinstance(row, dict):
                continue
            key = str(row.get("t212_ticker") or "").upper()
            if not key:
                continue
            if key not in by_ticker:
                order.append(key)
                by_ticker[key] = dict(row)
            else:
                by_ticker[key] = _prefer_handoff(by_ticker[key], row)
    runs: list[dict[str, Any]] = []
    seen_runs: set[tuple[str, str]] = set()
    for source in (base, incoming):
        for row in source.get("runs") or []:
            if not isinstance(row, dict):
                continue
            key = (str(row.get("t212_ticker") or ""), str(row.get("at") or ""))
            if key in seen_runs:
                continue
            seen_runs.add(key)
            runs.append(row)
    runs.sort(key=lambda row: str(row.get("at") or ""))
    lasts = [row for row in (base.get("last"), incoming.get("last")) if isinstance(row, dict)]
    skipped = base.get("skipped_held")
    incoming_skipped = incoming.get("skipped_held")
    if str(incoming.get("updated_at") or "") >= str(base.get("updated_at") or ""):
        if incoming_skipped is not None:
            skipped = incoming_skipped
    elif skipped is None:
        skipped = incoming_skipped
    merged: dict[str, Any] = {
        "schema_version": 1,
        "cursor_epoch": base_epoch,
        "completed": completed,
        "runs": runs[-40:],
        "handoffs": [by_ticker[key] for key in order],
        "last": max(lasts, key=lambda row: str(row.get("at") or "")) if lasts else None,
        "updated_at": max(
            str(base.get("updated_at") or ""),
            str(incoming.get("updated_at") or ""),
        )
        or None,
        "totals": _merge_totals(base, incoming, completed),
    }
    reason = incoming.get("cursor_reset_reason") or base.get("cursor_reset_reason")
    if reason:
        merged["cursor_reset_reason"] = reason
    if skipped is not None:
        merged["skipped_held"] = skipped
    return merged


def _merge_totals(
    base: dict[str, Any],
    incoming: dict[str, Any],
    completed: list[str],
) -> dict[str, Any]:
    base_completed = {str(item).upper() for item in (base.get("completed") or [])}
    incoming_completed = {str(item).upper() for item in (incoming.get("completed") or [])}
    base_totals = base.get("totals") if isinstance(base.get("totals"), dict) else None
    incoming_totals = incoming.get("totals") if isinstance(incoming.get("totals"), dict) else None
    if base_totals is not None:
        totals = {
            "screened": int(base_totals.get("screened") or 0),
            "signals": dict(base_totals.get("signals") or {}),
            "signals_n": int(base_totals.get("signals_n") or 0),
            "screen_seconds_sum": float(base_totals.get("screen_seconds_sum") or 0.0),
            "screen_seconds_n": int(base_totals.get("screen_seconds_n") or 0),
            "outcomes": dict(base_totals.get("outcomes") or {}),
        }
        newcomers = [token for token in completed if token not in base_completed]
        source = incoming
    elif incoming_totals is not None:
        totals = {
            "screened": int(incoming_totals.get("screened") or 0),
            "signals": dict(incoming_totals.get("signals") or {}),
            "signals_n": int(incoming_totals.get("signals_n") or 0),
            "screen_seconds_sum": float(incoming_totals.get("screen_seconds_sum") or 0.0),
            "screen_seconds_n": int(incoming_totals.get("screen_seconds_n") or 0),
            "outcomes": dict(incoming_totals.get("outcomes") or {}),
        }
        newcomers = [token for token in completed if token not in incoming_completed]
        source = base
    else:
        totals = _empty_totals()
        newcomers = []
        source = incoming
    holder = {"totals": totals}
    for token in newcomers:
        row = _row_for(source, token) or _row_for(base, token)
        if row is None:
            continue
        _add_row_to_totals(holder, row)
    totals = holder["totals"]
    totals["screened"] = len(completed)
    return totals


def merge_state_files(base_path: Path, incoming_path: Path, dest_path: Path) -> dict[str, Any]:
    """Read two state files and write their union. Used when two lanes commit."""
    base = _read_state_file(base_path)
    incoming = _read_state_file(incoming_path)
    merged = merge_states(base, incoming)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, merged, compact=False)
    return merged


def _read_state_file(path: Path) -> dict[str, Any]:
    file = Path(path)
    if not file.exists():
        return {"schema_version": 1, "completed": [], "runs": [], "handoffs": []}
    try:
        payload = read_json(file)
    except (OSError, ValueError, TypeError):
        return {"schema_version": 1, "completed": [], "runs": [], "handoffs": []}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "completed": [], "runs": [], "handoffs": []}
    return payload


def _timing_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in (state.get("runs") or []) if isinstance(row, dict)]
    last = state.get("last")
    if isinstance(last, dict):
        key = (last.get("t212_ticker"), last.get("at"))
        if not any((row.get("t212_ticker"), row.get("at")) == key for row in rows):
            rows.append(last)
    return rows


def _covered_totals(state: dict[str, Any]) -> dict[str, Any] | None:
    totals = state.get("totals")
    completed = state.get("completed") or []
    count = len(completed) if isinstance(completed, list) else 0
    if not isinstance(totals, dict):
        return None
    if int(totals.get("signals_n") or 0) != count:
        return None
    return totals


def _format_signals(signals: dict[str, Any]) -> str:
    pairs = [(str(key), int(value)) for key, value in signals.items() if int(value or 0) > 0]
    if not pairs:
        return "Signals: none yet."
    pairs.sort(key=lambda item: item[0])
    body = ", ".join(f"{key} {value}" for key, value in pairs)
    return f"Signals: {body}."


def _rate_lines(state: dict[str, Any]) -> tuple[str, str]:
    totals = _covered_totals(state)
    if totals is not None:
        timed = int(totals.get("screen_seconds_n") or 0)
        if timed:
            mean = round(float(totals.get("screen_seconds_sum") or 0.0) / timed, 3)
            seconds_line = f"Seconds per screen {mean} over {timed}."
        else:
            seconds_line = "Seconds per screen not recorded yet."
        signals = totals.get("signals") if isinstance(totals.get("signals"), dict) else {}
        return seconds_line, _format_signals(signals)
    rows = _timing_rows(state)
    timed_values = [
        seconds for seconds in (_row_screen_seconds(row) for row in rows) if seconds is not None
    ]
    if timed_values:
        mean = round(sum(timed_values) / len(timed_values), 3)
        seconds_line = f"Seconds per screen {mean} over {len(timed_values)} saved rows."
    else:
        seconds_line = "Seconds per screen not recorded yet."
    signals: dict[str, int] = {}
    for row in rows:
        if (
            _row_signal(row) is None
            and _row_screen_seconds(row) is None
            and not isinstance(row.get("screen"), dict)
            and "signal" not in row
        ):
            continue
        key = _row_signal(row) or "none"
        signals[key] = signals.get(key, 0) + 1
    note = " from the latest saved rows" if rows else ""
    line = _format_signals(signals)
    if note and line != "Signals: none yet.":
        line = line[:-1] + note + "."
    return seconds_line, line


def finding_summary(state: dict[str, Any] | None) -> str:
    if not state:
        return (
            "Catalogue explorer has not started. Stream 1 screens one unheld "
            "Trading 212 stock at a time, US then Xetra then LSE, and stops "
            "while the job can still commit. Stream 2 ingests queued buys. "
            "This check does not fetch."
        )
    completed = state.get("completed") or []
    screened = len(completed) if isinstance(completed, list) else 0
    noun = "name" if screened == 1 else "names"
    parts = [f"Screened {screened} catalogue {noun}, one at a time."]
    last = state.get("last") if isinstance(state.get("last"), dict) else None
    if not last:
        parts.append("No last timing record.")
    else:
        detail = f"Last {last.get('t212_ticker')} ({last.get('venue')}) took {last.get('seconds')}s"
        screen_seconds = _row_screen_seconds(last)
        if screen_seconds is not None:
            detail += f", screen {screen_seconds}s"
        signal = _row_signal(last)
        if signal:
            detail += f", signal {signal}"
        detail += f", outcome {last.get('outcome')}."
        parts.append(detail)
    seconds_line, signals_line = _rate_lines(state)
    parts.append(seconds_line)
    parts.append(signals_line)
    handoffs = [row for row in (state.get("handoffs") or []) if isinstance(row, dict)]
    ingested = sum(1 for row in handoffs if row.get("status") == "done")
    errors = sum(1 for row in handoffs if row.get("status") == "error")
    handoff_line = f"Buys handed off {len(handoffs)}, ingested {ingested}."
    if errors:
        handoff_line = (
            f"Buys handed off {len(handoffs)}, ingested {ingested}, ingest errors {errors}."
        )
    parts.append(handoff_line)
    skipped = state.get("skipped_held")
    if skipped is None:
        parts.append("Skips not recorded yet.")
    else:
        parts.append(f"Skips {int(skipped)}.")
    return " ".join(parts)
