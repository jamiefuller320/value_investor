"""Compact price-chart payloads for buy-tier dashboard popups."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.storage import (
    COMMITTED_HISTORY_DIR,
    history_snapshot_paths,
    read_json,
    write_json,
)

logger = logging.getLogger(__name__)

MAX_CHART_POINTS = 180
CHART_LOOKBACK_PERIOD = "1y"
BUY_TIER_SIGNALS = {"strong_buy", "buy"}
CROSSING_LEVEL_KEYS = (
    "core_limit",
    "tactical_limit",
    "stop_loss",
    "take_profit",
    "sma50",
    "sma200",
)
LEVEL_LABELS = {
    "last": "Last",
    "core_limit": "Core buy",
    "tactical_limit": "Tactical buy",
    "stop_loss": "Stop",
    "take_profit": "Target",
    "sma50": "SMA 50",
    "sma200": "SMA 200",
}


def slug_ticker(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", ticker)


def chart_filename(ticker: str) -> str:
    return f"{slug_ticker(ticker)}.json"


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return round(number, 2)


def _downsample(series: pd.Series, *, max_points: int = MAX_CHART_POINTS) -> pd.Series:
    clean = series.dropna()
    if len(clean) <= max_points:
        return clean
    step = max(1, len(clean) // max_points)
    sampled = clean.iloc[::step]
    # Always keep the latest close.
    if sampled.index[-1] != clean.index[-1]:
        sampled = pd.concat([sampled, clean.iloc[[-1]]])
    return sampled


def levels_from_trade_plan(
    trade_plan: dict[str, Any] | None,
    *,
    last: float | None = None,
    sma50: float | None = None,
    sma200: float | None = None,
) -> dict[str, float | None]:
    plan = trade_plan or {}
    return {
        "last": _round_price(last),
        "sma50": _round_price(sma50),
        "sma200": _round_price(sma200),
        "core_limit": _round_price(plan.get("core_limit")),
        "tactical_limit": _round_price(plan.get("tactical_limit")),
        "stop_loss": _round_price(plan.get("tactical_stop_loss") or plan.get("stop_loss")),
        "take_profit": _round_price(plan.get("tactical_take_profit") or plan.get("take_profit")),
    }


def _as_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text[:10]


def trade_plan_from_signal_row(row: dict[str, Any] | None) -> dict[str, Any]:
    plan = row or {}
    return {
        "core_limit": plan.get("core_limit"),
        "tactical_limit": plan.get("tactical_limit"),
        "tactical_stop_loss": plan.get("tactical_stop_loss"),
        "tactical_take_profit": plan.get("tactical_take_profit"),
        "stop_loss": plan.get("stop_loss"),
        "take_profit": plan.get("take_profit"),
    }


def indicators_as_of(series: pd.Series, as_of: str) -> dict[str, float | None]:
    """Last close / SMAs using only bars on or before ``as_of``."""
    clean = series.dropna()
    if clean.empty:
        return {"last": None, "sma50": None, "sma200": None}
    idx = pd.to_datetime(clean.index, utc=True, errors="coerce")
    clean = pd.Series(clean.to_numpy(), index=idx).dropna()
    cutoff = pd.Timestamp(as_of)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    upto = clean[clean.index <= cutoff]
    if upto.empty:
        return {"last": None, "sma50": None, "sma200": None}
    last = float(upto.iloc[-1])
    sma50 = float(upto.rolling(50).mean().iloc[-1]) if len(upto) >= 50 else None
    sma200 = float(upto.rolling(200).mean().iloc[-1]) if len(upto) >= 200 else None
    if sma50 is not None and pd.isna(sma50):
        sma50 = None
    if sma200 is not None and pd.isna(sma200):
        sma200 = None
    return {"last": last, "sma50": sma50, "sma200": sma200}


def first_level_crossings(
    dates: list[str],
    closes: list[float],
    levels: dict[str, Any] | None,
    *,
    since: str | None,
) -> list[dict[str, Any]]:
    """First date after ``since`` that close crosses each frozen trade level."""
    if not dates or len(dates) != len(closes) or not levels:
        return []
    start = _as_date(since)
    rows: list[dict[str, Any]] = []
    for key in CROSSING_LEVEL_KEYS:
        price = _round_price(levels.get(key))
        if price is None:
            continue
        prev_close: float | None = None
        crossed_on: str | None = None
        direction: str | None = None
        for date, close in zip(dates, closes, strict=True):
            if start and date < start:
                prev_close = close
                continue
            if prev_close is None:
                prev_close = close
                continue
            prev_side = prev_close - price
            curr_side = close - price
            if prev_side == 0 and curr_side == 0:
                prev_close = close
                continue
            if prev_side * curr_side <= 0 and prev_side != curr_side:
                crossed_on = date
                direction = "up" if close > prev_close else "down"
                break
            prev_close = close
        rows.append(
            {
                "key": key,
                "label": LEVEL_LABELS.get(key, key),
                "price": price,
                "date": crossed_on,
                "direction": direction,
            }
        )
    return rows


def initial_levels_from_run_snapshots(
    history_dirs: list[Path],
    *,
    ticker: str,
    signal_since: str | None,
    series: pd.Series | None = None,
) -> tuple[dict[str, float | None] | None, str | None]:
    """First buy-tier trade plan on/after ``signal_since`` from archived screens."""
    target = _as_date(signal_since)
    seen: set[Path] = set()
    candidates: list[tuple[str, dict[str, Any]]] = []
    for history_dir in history_dirs:
        if history_dir is None or not Path(history_dir).exists():
            continue
        for path in history_snapshot_paths(Path(history_dir)):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                payload = read_json(path)
            except (OSError, ValueError) as exc:
                logger.warning("Skipping unreadable snapshot %s: %s", path.name, exc)
                continue
            if not isinstance(payload, dict):
                continue
            run_date = _as_date(payload.get("run_at"))
            if not run_date:
                continue
            if target and run_date < target:
                continue
            for row in payload.get("signals") or []:
                if not isinstance(row, dict) or str(row.get("ticker")) != ticker:
                    continue
                if str(row.get("signal") or "") not in BUY_TIER_SIGNALS:
                    continue
                plan = trade_plan_from_signal_row(row)
                if not any(value is not None and not pd.isna(value) for value in plan.values()):
                    continue
                candidates.append((run_date, plan))
                break
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0])
    run_date, plan = candidates[0]
    last = sma50 = sma200 = None
    if series is not None:
        indicators = indicators_as_of(series, run_date)
        last = indicators["last"]
        sma50 = indicators["sma50"]
        sma200 = indicators["sma200"]
    return levels_from_trade_plan(plan, last=last, sma50=sma50, sma200=sma200), run_date


def resolve_initial_levels(
    *,
    ticker: str,
    series: pd.Series,
    signal_since: str | None,
    current_levels: dict[str, float | None],
    current_as_of: str | None,
    existing: dict[str, Any] | None = None,
    snapshot_dirs: list[Path] | None = None,
) -> tuple[dict[str, float | None] | None, str | None]:
    """Reuse a stored snapshot, else archive history, else this week's levels."""
    since = _as_date(signal_since)
    if existing:
        stored_as_of = _as_date(existing.get("initial_levels_as_of"))
        stored = existing.get("initial_levels")
        if stored_as_of and since and stored_as_of == since and isinstance(stored, dict):
            indicators = indicators_as_of(series, stored_as_of)
            merged = dict(stored)
            if merged.get("sma50") is None:
                merged["sma50"] = _round_price(indicators["sma50"])
            if merged.get("sma200") is None:
                merged["sma200"] = _round_price(indicators["sma200"])
            if merged.get("last") is None:
                merged["last"] = _round_price(indicators["last"])
            return merged, stored_as_of

    dirs = list(snapshot_dirs or [])
    if COMMITTED_HISTORY_DIR not in dirs:
        dirs.append(COMMITTED_HISTORY_DIR)
    snapshot_levels, snapshot_as_of = initial_levels_from_run_snapshots(
        dirs,
        ticker=ticker,
        signal_since=since,
        series=series,
    )
    if snapshot_levels:
        return snapshot_levels, snapshot_as_of

    as_of = _as_date(current_as_of)
    if since and as_of and since == as_of:
        return current_levels, as_of
    return None, None


def build_price_chart_payload(
    *,
    ticker: str,
    name: str | None,
    series: pd.Series,
    trade_plan: dict[str, Any] | None = None,
    signal: str | None = None,
    as_of: datetime | None = None,
    signal_since: str | None = None,
    initial_levels: dict[str, Any] | None = None,
    initial_levels_as_of: str | None = None,
    existing: dict[str, Any] | None = None,
    snapshot_dirs: list[Path] | None = None,
) -> dict[str, Any] | None:
    """Build a compact chart JSON for one ticker."""
    clean = series.dropna()
    if clean.empty:
        return None

    sampled = _downsample(clean)
    dates = [pd.Timestamp(index).strftime("%Y-%m-%d") for index in sampled.index]
    closes = [_round_price(float(value)) for value in sampled.to_numpy()]
    closes = [value for value in closes if value is not None]
    if len(closes) != len(dates):
        # Re-align if rounding dropped values (shouldn't happen for floats).
        pairs = [
            (pd.Timestamp(index).strftime("%Y-%m-%d"), _round_price(float(value)))
            for index, value in sampled.items()
        ]
        dates = [date for date, value in pairs if value is not None]
        closes = [value for _, value in pairs if value is not None]
    if not closes:
        return None

    sma50 = float(clean.rolling(50).mean().iloc[-1]) if len(clean) >= 50 else None
    sma200 = float(clean.rolling(200).mean().iloc[-1]) if len(clean) >= 200 else None
    if sma50 is not None and pd.isna(sma50):
        sma50 = None
    if sma200 is not None and pd.isna(sma200):
        sma200 = None

    as_of_iso = (as_of or datetime.now(UTC)).isoformat()
    # Prefer an explicit streak start; fall back to this screen's as-of date.
    marker = None
    if signal_since:
        marker = str(signal_since)[:10]
    elif as_of_iso:
        marker = as_of_iso[:10]

    current_levels = levels_from_trade_plan(
        trade_plan,
        last=closes[-1],
        sma50=sma50,
        sma200=sma200,
    )
    resolved_initial = initial_levels
    resolved_initial_as_of = _as_date(initial_levels_as_of)
    if resolved_initial is None:
        resolved_initial, resolved_initial_as_of = resolve_initial_levels(
            ticker=ticker,
            series=clean,
            signal_since=marker,
            current_levels=current_levels,
            current_as_of=as_of_iso,
            existing=existing,
            snapshot_dirs=snapshot_dirs,
        )

    crossings = first_level_crossings(
        dates,
        closes,
        resolved_initial,
        since=resolved_initial_as_of or marker,
    )

    return {
        "ticker": ticker,
        "name": name or ticker,
        "signal": signal,
        "as_of": as_of_iso,
        "signal_since": marker,
        "levels_as_of": as_of_iso[:10],
        "period": CHART_LOOKBACK_PERIOD,
        "dates": dates,
        "closes": closes,
        "levels": current_levels,
        "initial_levels": resolved_initial,
        "initial_levels_as_of": resolved_initial_as_of,
        "level_crossings": crossings,
    }


def write_price_chart(chart_dir: Path, payload: dict[str, Any]) -> Path:
    chart_dir.mkdir(parents=True, exist_ok=True)
    path = chart_dir / chart_filename(str(payload["ticker"]))
    write_json(path, payload, compact=True, compress=False)
    return path


def _existing_chart(chart_dir: Path, ticker: str) -> dict[str, Any] | None:
    path = Path(chart_dir) / chart_filename(ticker)
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_buy_tier_charts_from_history(
    *,
    signals: pd.DataFrame,
    history: dict[str, pd.Series],
    chart_dir: Path,
    as_of: datetime | None = None,
    snapshot_dirs: list[Path] | None = None,
) -> list[Path]:
    """Persist chart payloads for strong_buy / buy rows that have price history."""
    if signals.empty or "ticker" not in signals.columns or "signal" not in signals.columns:
        return []

    chart_dir = Path(chart_dir)
    dirs = list(snapshot_dirs or [])
    parent_history = chart_dir.parent / "history"
    if parent_history not in dirs:
        dirs.append(parent_history)

    written: list[Path] = []
    buy_tier = signals[signals["signal"].isin(["strong_buy", "buy"])]
    for _, row in buy_tier.iterrows():
        ticker = str(row["ticker"])
        series = history.get(ticker)
        if series is None or series.empty:
            continue
        trade_plan = trade_plan_from_signal_row(row.to_dict())
        payload = build_price_chart_payload(
            ticker=ticker,
            name=str(row.get("name") or ticker),
            series=series,
            trade_plan=trade_plan,
            signal=str(row.get("signal") or ""),
            as_of=as_of,
            signal_since=str(row["signal_since"])
            if row.get("signal_since") is not None and not pd.isna(row.get("signal_since"))
            else None,
            existing=_existing_chart(chart_dir, ticker),
            snapshot_dirs=dirs,
        )
        if payload is None:
            continue
        written.append(write_price_chart(chart_dir, payload))
    return written


def ensure_buy_tier_charts(
    *,
    reports: list[dict[str, Any]],
    chart_dir: Path,
    as_of: datetime | None = None,
    fetch: bool = True,
) -> list[Path]:
    """
    Ensure chart JSON exists for buy-tier reports.

    Uses on-disk charts when present; optionally fetches missing price history.
    """
    chart_dir.mkdir(parents=True, exist_ok=True)
    buy_tier = [r for r in reports if r.get("signal") in ("strong_buy", "buy") and r.get("ticker")]
    missing = [
        report
        for report in buy_tier
        if not (chart_dir / chart_filename(str(report["ticker"]))).exists()
    ]
    written: list[Path] = []
    if not missing:
        return [
            chart_dir / chart_filename(str(report["ticker"]))
            for report in buy_tier
            if (chart_dir / chart_filename(str(report["ticker"]))).exists()
        ]

    if not fetch:
        return written

    from value_investor.technical_analysis import fetch_close_history

    history = fetch_close_history([str(r["ticker"]) for r in missing])
    for report in missing:
        ticker = str(report["ticker"])
        series = history.get(ticker)
        if series is None or series.empty:
            logger.warning("No price history for chart: %s", ticker)
            continue
        payload = build_price_chart_payload(
            ticker=ticker,
            name=str(report.get("name") or ticker),
            series=series,
            trade_plan=report.get("trade_plan")
            if isinstance(report.get("trade_plan"), dict)
            else None,
            signal=str(report.get("signal") or ""),
            as_of=as_of,
            signal_since=str(report["signal_since"]) if report.get("signal_since") else None,
            existing=_existing_chart(chart_dir, ticker),
            snapshot_dirs=[chart_dir.parent / "history", COMMITTED_HISTORY_DIR],
        )
        if payload is None:
            continue
        written.append(write_price_chart(chart_dir, payload))
    return written


def copy_charts_to_dashboard(
    *,
    source_dir: Path,
    dest_dir: Path,
    tickers: list[str] | None = None,
) -> list[str]:
    """Copy chart JSON files into the dashboard data tree; return relative paths."""
    if not source_dir.exists():
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    wanted = {slug_ticker(ticker) for ticker in tickers} if tickers is not None else None
    for path in sorted(source_dir.glob("*.json")):
        if wanted is not None and path.stem not in wanted:
            continue
        target = dest_dir / path.name
        target.write_bytes(path.read_bytes())
        paths.append(f"data/charts/{path.name}")
    return paths
