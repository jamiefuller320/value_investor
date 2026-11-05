"""Archive replay of the strategy book (plan step 2.2).

Reads a directory shaped like ``docs/data``: charts, weekly runs via
``load_run_snapshots``, market graduation, and the decline and sector stores.
The three section 9 results stay separate. ``archive_full_strategy`` is
published empty when no dated verdict is in force. The snapshot ``prices``
map is not a fill. Chart ``signal`` and ``levels`` are ignored.

This module does not walk the committed tree. The CLI refuses that walk
until ``registration_signed`` is true.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from value_investor.backtest import load_run_snapshots
from value_investor.price_charts import chart_filename
from value_investor.sector_headwind_gate import FTSE_MARKET
from value_investor.storage import read_json
from value_investor.strategy_book_observe import (
    F9Fact,
    GateFact,
    NameSpec,
    ScreenFact,
    walk_book,
)
from value_investor.strategy_book_rules import (
    ARCHIVE_BUY_TIER_ONLY,
    ARCHIVE_FULL_STRATEGY,
    COLUMN_ALTERNATIVE,
    COLUMN_BUY_ON_SIGNAL,
    INFLUENCES_LIVE,
    LOOKAHEAD_CURRENT_GATES,
    REGISTRATION_ID,
    VALUE_SET_SIGNALS,
)
from value_investor.strategy_book_signals import (
    _binds,
    parse_day,
    session_end,
    universe_markets,
)

# Section 9. Stored on the chart at build time. Not an entry, and not a fill.
_CHART_IGNORED = ("sma50_series", "sma200_series", "levels", "signal", "level_crossings")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "none", "nan", "null"}:
        return None
    return text


def _chart_file(charts: Path, ticker: str) -> Path | None:
    direct = charts / f"{ticker}.json"
    if direct.is_file():
        return direct
    named = charts / chart_filename(ticker)
    if named.is_file():
        return named
    return None


def _read_chart(
    path: Path,
) -> tuple[list[date], list[float], list[float] | None, list[float] | None] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    # Touch the ignored keys only to drop them. Their values are not used.
    for key in _CHART_IGNORED:
        payload.pop(key, None)
    raw_dates = payload.get("dates") or []
    raw_closes = payload.get("closes") or []
    if not isinstance(raw_dates, list) or not isinstance(raw_closes, list):
        return None
    sessions: list[date] = []
    closes: list[float] = []
    for raw_day, raw_close in zip(raw_dates, raw_closes, strict=False):
        day = parse_day(raw_day)
        if day is None:
            continue
        try:
            close = float(raw_close)
        except (TypeError, ValueError):
            continue
        sessions.append(day)
        closes.append(close)
    if not sessions:
        return None
    highs = _aligned(payload.get("highs"), len(raw_dates), sessions, raw_dates)
    lows = _aligned(payload.get("lows"), len(raw_dates), sessions, raw_dates)
    return sessions, closes, highs, lows


def _aligned(
    raw: Any,
    declared: int,
    sessions: list[date],
    raw_dates: list[Any],
) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) != declared:
        return None
    kept: list[float] = []
    for raw_day, value in zip(raw_dates, raw, strict=False):
        day = parse_day(raw_day)
        if day is None or day not in sessions:
            continue
        try:
            kept.append(float(value))
        except (TypeError, ValueError):
            return None
    if len(kept) != len(sessions):
        return None
    return kept


def _screens_from_snapshots(snapshots: list[Any]) -> dict[str, list[ScreenFact]]:
    grouped: dict[str, list[ScreenFact]] = {}
    for snap in snapshots:
        run_day = parse_day(getattr(snap, "run_at", None))
        if run_day is None:
            continue
        for row in getattr(snap, "signals", []) or []:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            fields = {
                key: value
                for key, value in row.items()
                if key not in {"ticker", "signal", "adjusted_signal", "research_verdict", "sector"}
            }
            grouped.setdefault(ticker, []).append(
                ScreenFact(
                    run_date=run_day,
                    signal=_clean(row.get("signal")),
                    adjusted_signal=_clean(row.get("adjusted_signal")),
                    research_verdict=_clean(row.get("research_verdict")),
                    sector=_clean(row.get("sector")),
                    fields=fields,
                )
            )
    return grouped


def _lookup(mapping: Any, key: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    if key in mapping:
        return mapping[key]
    folded = key.casefold()
    for raw, value in mapping.items():
        if str(raw).casefold() == folded:
            return value
    return None


def _gate_for(
    decline: dict[str, Any] | None,
    sector: dict[str, Any] | None,
    market: str,
    ticker: str,
) -> list[GateFact]:
    decline_as_of = parse_day((decline or {}).get("as_of"))
    sector_as_of = parse_day((sector or {}).get("as_of"))
    decline_entry = _lookup((decline or {}).get("names"), ticker)
    if isinstance(decline_entry, dict):
        entry_market = _clean(decline_entry.get("market"))
        if entry_market is not None and entry_market != market:
            decline_entry = None
    else:
        decline_entry = None
    by_market = (sector or {}).get("names_by_market")
    sector_entry = _lookup(_lookup(by_market, market), ticker)
    if not isinstance(sector_entry, dict):
        sector_entry = None
    if decline_entry is None and sector_entry is None:
        return []
    if decline_as_of is not None and sector_as_of is not None:
        as_of = max(decline_as_of, sector_as_of)
    else:
        as_of = decline_as_of or sector_as_of
    if as_of is None:
        return []
    checks = decline_entry.get("checks") if isinstance(decline_entry, dict) else None
    return [
        GateFact(
            as_of=as_of,
            decline=_clean(decline_entry.get("verdict"))
            if isinstance(decline_entry, dict)
            else None,
            sector=_clean(sector_entry.get("sector_verdict"))
            if isinstance(sector_entry, dict)
            else None,
            sector_basis=_clean(sector_entry.get("sector_basis"))
            if isinstance(sector_entry, dict)
            else None,
            region=_clean(sector_entry.get("region")) if isinstance(sector_entry, dict) else None,
            sector_name=_clean(sector_entry.get("sector"))
            if isinstance(sector_entry, dict)
            else None,
            earnings_breadth_sources=sector_entry.get("earnings_breadth_sources")
            if isinstance(sector_entry, dict)
            and isinstance(sector_entry.get("earnings_breadth_sources"), dict)
            else None,
            checks=checks if isinstance(checks, dict) else None,
        )
    ]


def _research_root(root: Path, market: str) -> Path:
    if market == FTSE_MARKET:
        return root / "research"
    return root / "library" / "markets" / market / "screen" / "research"


def _f9_facts(
    root: Path,
    market: str,
    ticker: str,
    screens: list[ScreenFact],
    sessions: list[date],
) -> list[F9Fact]:
    """Filing, cash-flow and overlay binds from files dated on or before a session.

    The memo bind is not required on the archive (section 2). A missing
    research folder leaves the list empty, so ``archive_full_strategy`` does
    not invent a pass.
    """
    research = _research_root(root, market)
    if not (research / ticker).is_dir():
        return []
    dates = sorted({fact.run_date for fact in screens} | set(sessions[-1:] if sessions else []))
    facts: list[F9Fact] = []
    for day in dates:
        row: dict[str, Any] = {}
        in_force = [fact for fact in screens if fact.run_date <= day]
        if in_force:
            latest = max(in_force, key=lambda item: item.run_date)
            row = {
                "signal": latest.signal,
                "adjusted_signal": latest.adjusted_signal,
                "research_verdict": latest.research_verdict,
                **latest.fields,
            }
        binds, _paths = _binds(
            market=market,
            ticker=ticker,
            row=row,
            research_root=research,
            session=day,
            memo_as_of=session_end(day),
        )
        bodies = bool(binds["key_filing_bodies"].passed)
        fcf = bool(binds["fcf_basis_bound"].passed)
        overlay = bool(binds["overlay_bound"].passed)
        memo = bool(binds["memo_recent"].passed)
        if bodies and fcf and overlay:
            facts.append(
                F9Fact(
                    as_of=day,
                    key_filing_bodies=True,
                    fcf_basis_bound=True,
                    overlay_bound=True,
                    memo_recent=memo,
                )
            )
    return facts


def _hash_files(root: Path, paths: list[Path]) -> tuple[list[str], dict[str, bytes]]:
    rels: list[str] = []
    blobs: dict[str, bytes] = {}
    for path in paths:
        if not path.is_file():
            continue
        try:
            rel = str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            rel = str(path)
        try:
            blobs[rel] = path.read_bytes()
        except OSError:
            continue
        rels.append(rel)
    return rels, blobs


def load_archive(root: Path) -> dict[str, Any]:
    """Name specs and the names the archive could not trade.

    ``prices`` on a weekly run are ignored. A buy-tier name with no chart is
    ``no_chart``. A market that is not graduated is not loaded.
    """
    root = Path(root)
    markets = universe_markets(root / "market_status.json")
    charts = root / "charts"
    decline = _load_json(root / "operating_decline_gate.json")
    sector = _load_json(root / "sector_headwind_gate.json")
    library_root = root / "library" / "markets"
    skipped: list[str] = []
    if library_root.is_dir():
        for path in sorted(library_root.iterdir()):
            if path.is_dir() and path.name not in markets:
                skipped.append(path.name)
    specs: list[NameSpec] = []
    no_chart: list[dict[str, str]] = []
    for market in markets:
        if market == FTSE_MARKET:
            snapshots = load_run_snapshots(root)
            library = False
        else:
            snapshots = load_run_snapshots(library_root / market / "screen")
            library = True
        grouped = _screens_from_snapshots(snapshots)
        for ticker, screens in sorted(grouped.items()):
            if not any(str(fact.signal or "") in VALUE_SET_SIGNALS for fact in screens):
                continue
            chart_path = _chart_file(charts, ticker)
            chart = _read_chart(chart_path) if chart_path is not None else None
            paths = [path for path in (chart_path,) if path is not None]
            rels, blobs = _hash_files(root, paths)
            common = dict(
                market=market,
                ticker=ticker,
                screens=screens,
                gates=_gate_for(decline, sector, market, ticker),
                graduated=True,
                library=library,
                input_paths=rels,
                files=blobs or None,
                committed=dict(blobs) if blobs else None,
            )
            if chart is None:
                no_chart.append({"market": market, "ticker": ticker})
                specs.append(NameSpec(**common))
                continue
            sessions, closes, highs, lows = chart
            specs.append(
                NameSpec(
                    **common,
                    sessions=sessions,
                    closes=closes,
                    highs=highs,
                    lows=lows,
                    f9=_f9_facts(root, market, ticker, screens, sessions),
                )
            )
    return {
        "specs": specs,
        "no_chart": no_chart,
        "skipped_ungraduated": skipped,
        "markets": markets,
    }


def _column(result: dict[str, Any], column: str) -> list[dict[str, Any]]:
    return [episode for episode in result.get("episodes") or [] if episode.get("column") == column]


def _view(result: dict[str, Any]) -> dict[str, Any]:
    """One result. Episodes, events and boards are that walk's own objects."""
    return {
        "episodes": list(result.get("episodes") or []),
        "events": list(result.get("events") or []),
        "boards": result.get("boards") or {},
        "counts": result.get("counts") or {},
        "scoring_date": result.get("scoring_date"),
        "cap_would_block_days": result.get("cap_would_block_days"),
    }


def run_replay(root: Path) -> dict[str, Any]:
    """The three archive results, the alternative column, and the buy-on-signal control.

    Results are not averaged. An empty full-strategy walk is returned empty.
    """
    loaded = load_archive(root)
    specs: list[NameSpec] = loaded["specs"]
    buy = walk_book(specs, mode=ARCHIVE_BUY_TIER_ONLY)
    full = walk_book(specs, mode=ARCHIVE_FULL_STRATEGY)
    lookahead = walk_book(specs, mode=LOOKAHEAD_CURRENT_GATES)
    buy_view = _view(buy)
    return {
        "registration_id": REGISTRATION_ID,
        "influences_live": INFLUENCES_LIVE,
        ARCHIVE_BUY_TIER_ONLY: buy_view,
        ARCHIVE_FULL_STRATEGY: _view(full),
        LOOKAHEAD_CURRENT_GATES: _view(lookahead),
        "buy_on_signal": {
            "eligibility": ARCHIVE_BUY_TIER_ONLY,
            "episodes": _column(buy_view, COLUMN_BUY_ON_SIGNAL),
        },
        "alternative": {
            "column": COLUMN_ALTERNATIVE,
            "inside": ARCHIVE_BUY_TIER_ONLY,
            "episodes": _column(buy_view, COLUMN_ALTERNATIVE),
        },
        "no_chart": loaded["no_chart"],
        "skipped_ungraduated": loaded["skipped_ungraduated"],
        "markets": loaded["markets"],
    }


def result_medians_are_separate(payload: dict[str, Any]) -> bool:
    """The three boards are distinct objects and there is no blended median."""
    keys = (ARCHIVE_BUY_TIER_ONLY, ARCHIVE_FULL_STRATEGY, LOOKAHEAD_CURRENT_GATES)
    if any(key not in payload for key in keys):
        return False
    if "blended_median" in payload or "combined_median" in payload:
        return False
    boards = [payload[key].get("boards") for key in keys]
    return boards[0] is not boards[1] and boards[1] is not boards[2] and boards[0] is not boards[2]
