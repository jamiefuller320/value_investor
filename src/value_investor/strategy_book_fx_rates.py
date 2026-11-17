"""Observe-only daily USD closes for CHF, SEK, HKD and SGD.

The step 3.2 sterling and drawdown bars read point-in-time rates. Dated macro
snapshots already price GBP, EUR, AUD and CAD. These four currencies had no
series, so a counted episode in one of them stayed ``insufficient_data``.

This store is that series. Each point's date is the Yahoo session date. The
proof board uses the latest ``as_of`` on or before the episode date. It does
not call a live spot. A missing point is still a gap: no rate is invented.

``influences_live`` is false. The store does not change the sealed fair-cost
formula, the primary exit, or the seven proof bars.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.storage import write_json

STORE_NAME = "strategy_book_fx_rates.json"
# Before the forward book's first session (2026-11-10), so those fills have a prior close.
HISTORY_START = date(2026, 10, 1)
STALE_AFTER = timedelta(days=5)

# Yahoo "=X" symbols quote USD per 1 unit, the same way GBPUSD=X quotes USD per 1 pound.
PAIRS: dict[str, str] = {
    "CHF": "CHFUSD=X",
    "SEK": "SEKUSD=X",
    "HKD": "HKDUSD=X",
    "SGD": "SGDUSD=X",
}
# Wide bands around USD per 1 unit. A quote outside its band is refused, not stored.
BANDS: dict[str, tuple[float, float]] = {
    "CHF": (0.8, 1.6),
    "SEK": (0.05, 0.20),
    "HKD": (0.10, 0.16),
    "SGD": (0.60, 0.90),
}

TITLE_INFO = "Strategy book FX rates refreshed"
TITLE_MISSING = "Strategy book FX rates missing"
TITLE_UNREADABLE = "Strategy book FX rates unreadable"
TITLE_INCOMPLETE = "Strategy book FX rates incomplete"
TITLE_STALE = "Strategy book FX rates stale"

# (symbol, start, end) -> list of (session date, positive close)
HistoryFetcher = Callable[[str, date, date], list[tuple[date, float]]]


def store_path(repo_root: Path) -> Path:
    return Path(repo_root) / "docs" / "data" / STORE_NAME


def _day(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number <= 0:
            return None
        return number
    return None


def empty_store() -> dict[str, Any]:
    return {
        "instrument": "strategy_book_fx_rates",
        "influences_live": False,
        "observe_only": True,
        "changes_fair_cost": False,
        "changes_primary_exit": False,
        "source": "yahoo_session_close",
        "quote": "USD per 1 unit of the currency",
        "history_start": HISTORY_START.isoformat(),
        "generated_at": None,
        "pairs": {code: [] for code in PAIRS},
        "errors": [],
    }


def read_store(repo_root: Path) -> dict[str, Any] | None:
    path = store_path(repo_root)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not an object")
    return payload


def series_from_store(payload: dict[str, Any] | None) -> dict[str, list[tuple[date, float]]]:
    """First point for a session date wins. Later rows for that date are ignored."""
    series: dict[str, list[tuple[date, float]]] = {code: [] for code in PAIRS}
    if not isinstance(payload, dict):
        return series
    pairs = payload.get("pairs")
    if not isinstance(pairs, dict):
        return series
    for code in PAIRS:
        rows = pairs.get(code)
        if not isinstance(rows, list):
            continue
        seen: set[date] = set()
        points: list[tuple[date, float]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            day = _day(row.get("as_of"))
            rate = _as_float(row.get("value"))
            if day is None or rate is None or day in seen:
                continue
            seen.add(day)
            points.append((day, rate))
        series[code] = sorted(points, key=lambda item: item[0])
    return series


def _in_band(code: str, points: list[tuple[date, float]]) -> bool:
    if not points:
        return False
    low, high = BANDS[code]
    ordered = sorted(rate for _day, rate in points)
    median = ordered[len(ordered) // 2]
    return low <= median <= high


def _merge_points(
    existing: list[tuple[date, float]], fresh: list[tuple[date, float]]
) -> list[dict[str, Any]]:
    chosen: dict[date, float] = {}
    for day, rate in existing:
        chosen.setdefault(day, rate)
    for day, rate in fresh:
        chosen.setdefault(day, rate)
    return [
        {"as_of": day.isoformat(), "value": round(chosen[day], 6)}
        for day in sorted(chosen)
    ]


def yahoo_history(symbol: str, start: date, end: date) -> list[tuple[date, float]]:
    """Daily Yahoo closes from ``start`` through ``end``, inclusive."""
    import yfinance as yf

    hist = yf.Ticker(symbol).history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=True,
    )
    if hist is None or hist.empty or "Close" not in hist.columns:
        return []
    points: list[tuple[date, float]] = []
    closes = hist["Close"].dropna()
    for stamp, value in closes.items():
        day = stamp.date() if hasattr(stamp, "date") else _day(stamp)
        rate = _as_float(value)
        if day is None or rate is None:
            continue
        points.append((day, rate))
    return points


def refresh_store(
    repo_root: Path,
    *,
    fetcher: HistoryFetcher | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Add new session closes. A date already stored is kept."""
    moment = today or datetime.now(UTC).date()
    fetch = fetcher or yahoo_history
    try:
        current = read_store(repo_root)
    except (OSError, ValueError, TypeError):
        current = None
    existing = series_from_store(current)
    payload = empty_store()
    if isinstance(current, dict) and isinstance(current.get("pairs"), dict):
        payload["pairs"] = {
            code: [
                {"as_of": day.isoformat(), "value": rate} for day, rate in existing[code]
            ]
            for code in PAIRS
        }
    errors: list[str] = []
    for code, symbol in PAIRS.items():
        try:
            fresh = fetch(symbol, HISTORY_START, moment)
        except Exception as exc:  # noqa: BLE001 — a feed miss must not wipe the store
            errors.append(f"{code}: {exc}")
            continue
        if not fresh:
            errors.append(f"{code}: no closes")
            continue
        if not _in_band(code, fresh):
            errors.append(f"{code}: closes sit outside the USD-per-unit band; not stored")
            continue
        payload["pairs"][code] = _merge_points(existing[code], fresh)
    payload["generated_at"] = datetime.now(UTC).isoformat()
    payload["errors"] = errors
    payload["influences_live"] = False
    return payload


def write_store(repo_root: Path, payload: dict[str, Any]) -> Path:
    payload["influences_live"] = False
    return write_json(store_path(repo_root), payload, compact=False, compress=False)


def _parse_generated_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def findings_for_store(repo_root: Path, *, now: datetime | None = None) -> list[dict[str, Any]]:
    path = store_path(repo_root)
    moment = now or datetime.now(UTC)
    if not path.is_file():
        return [
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_MISSING,
                "summary": (
                    f"{STORE_NAME} is absent. Sterling and drawdown bars stay "
                    "insufficient_data for CHF, SEK, HKD and SGD. influences_live is false."
                ),
                "auto_fixable": False,
            }
        ]
    try:
        payload = read_store(repo_root)
        series = series_from_store(payload)
    except (OSError, ValueError, TypeError):
        return [
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_UNREADABLE,
                "summary": f"{STORE_NAME} is not a readable FX store. influences_live is false.",
                "auto_fixable": False,
            }
        ]
    empty = [code for code, rows in series.items() if not rows]
    if empty:
        return [
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_INCOMPLETE,
                "summary": (
                    f"{STORE_NAME} has no closes for {', '.join(empty)}. "
                    "No rate is invented. influences_live is false."
                ),
                "auto_fixable": False,
            }
        ]
    generated = _parse_generated_at((payload or {}).get("generated_at"))
    if generated is None or moment - generated > STALE_AFTER:
        age = "missing generated_at" if generated is None else generated.date().isoformat()
        return [
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_STALE,
                "summary": (
                    f"{STORE_NAME} generated_at is {age}. "
                    f"Stale means older than {STALE_AFTER.days} days. influences_live is false."
                ),
                "auto_fixable": False,
            }
        ]
    spans = []
    for code, rows in series.items():
        spans.append(f"{code} {rows[0][0].isoformat()} to {rows[-1][0].isoformat()} ({len(rows)})")
    return [
        {
            "severity": "info",
            "category": "research",
            "title": TITLE_INFO,
            "summary": (
                "Observe-only USD closes: "
                + "; ".join(spans)
                + ". influences_live is false. The fair-cost formula is unchanged."
            ),
            "auto_fixable": False,
        }
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh observe-only USD closes for CHF, SEK, HKD and SGD. "
            "Does not change the fair-cost formula or open live capital."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the store on disk. Does not fetch and does not write.",
    )
    args = parser.parse_args(argv)
    if args.no_write:
        payload = read_store(args.repo_root)
        if payload is None:
            print(json.dumps({"missing": True, "influences_live": False}))
            return 0
        print(json.dumps(payload, indent=2))
        return 0
    payload = refresh_store(args.repo_root)
    write_store(args.repo_root, payload)
    counts = {
        code: len(rows)
        for code, rows in series_from_store(payload).items()
    }
    print(
        json.dumps(
            {
                "wrote": STORE_NAME,
                "influences_live": False,
                "counts": counts,
                "errors": payload.get("errors"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
