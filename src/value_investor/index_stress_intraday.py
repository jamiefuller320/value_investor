"""Intraday (^FTSE hourly) index bars — fetch, persist, and stress features."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_INTRADAY_ROOT = Path("docs/data/library/macro/index_intraday")
FetchHourlyBars = Callable[[str, date, date], list[dict[str, Any]]]


def _parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _safe_return(current: float, prior: float) -> float | None:
    if prior <= 0 or current <= 0:
        return None
    return (current - prior) / prior


def default_fetch_hourly_bars(symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    """Fetch hourly OHLC from Yahoo Finance (best-effort; history depth is provider-limited)."""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance unavailable for hourly index fetch")
        return []

    # yfinance hourly history is capped (~730d); chunk in 60-day windows for reliability.
    bars: list[dict[str, Any]] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=60), end)
        try:
            frame = yf.Ticker(symbol).history(
                start=cursor.isoformat(),
                end=(chunk_end + timedelta(days=1)).isoformat(),
                interval="1h",
                auto_adjust=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Hourly fetch failed for %s %s-%s: %s", symbol, cursor, chunk_end, exc)
            cursor = chunk_end + timedelta(days=1)
            continue

        if frame is not None and not frame.empty:
            for idx, row in frame.iterrows():
                ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else _parse_ts(str(idx))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                close = float(row.get("Close") or 0)
                if close <= 0:
                    continue
                open_px = float(row.get("Open") or close)
                bars.append(
                    {
                        "ts": ts.isoformat(),
                        "date": ts.date().isoformat(),
                        "close": close,
                        "open": open_px,
                        "symbol": symbol,
                    }
                )
        cursor = chunk_end + timedelta(days=1)

    deduped: dict[str, dict[str, Any]] = {}
    for bar in bars:
        deduped[str(bar["ts"])] = bar
    return sorted(deduped.values(), key=lambda row: str(row["ts"]))


def aggregate_hourly_daily_features(hourly_bars: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per calendar day: worst hourly ROC, best hourly ROC, session open→close."""
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bar in hourly_bars:
        day = str(bar.get("date") or "")
        if day:
            by_day[day].append(bar)

    features: dict[str, dict[str, Any]] = {}
    for day, rows in sorted(by_day.items()):
        rows = sorted(rows, key=lambda row: str(row.get("ts") or ""))
        closes = [float(row["close"]) for row in rows if float(row.get("close") or 0) > 0]
        if not closes:
            continue
        min_hourly_return: float | None = None
        max_hourly_return: float | None = None
        for prev, cur in zip(closes, closes[1:], strict=False):
            ret = _safe_return(cur, prev)
            if ret is None:
                continue
            min_hourly_return = ret if min_hourly_return is None else min(min_hourly_return, ret)
            max_hourly_return = ret if max_hourly_return is None else max(max_hourly_return, ret)

        session_open = float(rows[0].get("open") or closes[0])
        session_close = closes[-1]
        session_return = _safe_return(session_close, session_open)

        features[day] = {
            "date": day,
            "hour_count": len(rows),
            "min_hourly_return": min_hourly_return,
            "max_hourly_return": max_hourly_return,
            "session_return": session_return,
            "session_open": session_open,
            "session_close": session_close,
        }
    return features


def intraday_stress_triggers(
    features: dict[str, Any],
    *,
    abs_1h: float,
    abs_session: float | None = None,
) -> list[str]:
    triggers: list[str] = []
    min_h = features.get("min_hourly_return")
    if min_h is not None and min_h <= abs_1h:
        triggers.append(f"abs_1h<={abs_1h:.2%}")
    session = features.get("session_return")
    if abs_session is not None and session is not None and session <= abs_session:
        triggers.append(f"session_return<={abs_session:.2%}")
    return triggers


def merge_intraday_into_daily_decisions(
    daily_decisions: list[Any],
    hourly_features: dict[str, dict[str, Any]],
    *,
    abs_1h: float,
    abs_session: float | None = None,
) -> list[Any]:
    """Augment daily IndexStressDecision rows with intraday triggers."""
    from value_investor.index_stress import IndexStressDecision

    merged: list[IndexStressDecision] = []
    for decision in daily_decisions:
        day_features = hourly_features.get(decision.date) or {}
        extra = intraday_stress_triggers(day_features, abs_1h=abs_1h, abs_session=abs_session)
        if not extra:
            merged.append(decision)
            continue
        triggers = list(decision.triggers) + extra
        merged.append(
            IndexStressDecision(
                date=decision.date,
                stressed=True,
                triggers=triggers,
                return_1d=decision.return_1d,
                return_5d=decision.return_5d,
                vol_z_1d=decision.vol_z_1d,
                drawdown=decision.drawdown,
            )
        )
    return merged


def load_intraday_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "bars": [], "updated_at": None}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {"schema_version": 1, "bars": [], "updated_at": None}
    payload.setdefault("bars", [])
    return payload


def persist_intraday_bars(
    *,
    symbol: str,
    hourly_bars: list[dict[str, Any]],
    root: Path = DEFAULT_INTRADAY_ROOT,
    max_bars: int = 4000,
) -> Path:
    """Append/merge hourly bars into the macro intraday store (more-data-now)."""
    root.mkdir(parents=True, exist_ok=True)
    safe_symbol = symbol.replace("^", "").lower()
    path = root / f"{safe_symbol}_1h.json"
    store = load_intraday_store(path)
    by_ts = {str(row.get("ts")): row for row in store.get("bars") or [] if row.get("ts")}
    for bar in hourly_bars:
        if bar.get("ts"):
            by_ts[str(bar["ts"])] = bar
    merged = sorted(by_ts.values(), key=lambda row: str(row.get("ts") or ""))[-max_bars:]
    payload = {
        "schema_version": 1,
        "symbol": symbol,
        "interval": "1h",
        "updated_at": datetime.now(UTC).isoformat(),
        "bar_count": len(merged),
        "bars": merged,
    }
    write_json(path, payload, compact=False)
    return path


def load_persisted_hourly_bars(
    symbol: str,
    *,
    root: Path = DEFAULT_INTRADAY_ROOT,
    start: date | None = None,
    end: date | None = None,
) -> list[dict[str, Any]]:
    safe_symbol = symbol.replace("^", "").lower()
    path = root / f"{safe_symbol}_1h.json"
    store = load_intraday_store(path)
    bars = list(store.get("bars") or [])
    if start is None and end is None:
        return bars
    filtered: list[dict[str, Any]] = []
    for bar in bars:
        day = date.fromisoformat(str(bar.get("date")))
        if start and day < start:
            continue
        if end and day > end:
            continue
        filtered.append(bar)
    return filtered


__all__ = [
    "DEFAULT_INTRADAY_ROOT",
    "FetchHourlyBars",
    "aggregate_hourly_daily_features",
    "default_fetch_hourly_bars",
    "intraday_stress_triggers",
    "load_persisted_hourly_bars",
    "merge_intraday_into_daily_decisions",
    "persist_intraday_bars",
]
