"""Compact price-chart payloads for buy-tier dashboard popups."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.storage import write_json

logger = logging.getLogger(__name__)

MAX_CHART_POINTS = 180
CHART_LOOKBACK_PERIOD = "1y"


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


def build_price_chart_payload(
    *,
    ticker: str,
    name: str | None,
    series: pd.Series,
    trade_plan: dict[str, Any] | None = None,
    signal: str | None = None,
    as_of: datetime | None = None,
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

    return {
        "ticker": ticker,
        "name": name or ticker,
        "signal": signal,
        "as_of": (as_of or datetime.now(UTC)).isoformat(),
        "period": CHART_LOOKBACK_PERIOD,
        "dates": dates,
        "closes": closes,
        "levels": levels_from_trade_plan(
            trade_plan,
            last=closes[-1],
            sma50=sma50,
            sma200=sma200,
        ),
    }


def write_price_chart(chart_dir: Path, payload: dict[str, Any]) -> Path:
    chart_dir.mkdir(parents=True, exist_ok=True)
    path = chart_dir / chart_filename(str(payload["ticker"]))
    write_json(path, payload, compact=True, compress=False)
    return path


def write_buy_tier_charts_from_history(
    *,
    signals: pd.DataFrame,
    history: dict[str, pd.Series],
    chart_dir: Path,
    as_of: datetime | None = None,
) -> list[Path]:
    """Persist chart payloads for strong_buy / buy rows that have price history."""
    if signals.empty or "ticker" not in signals.columns or "signal" not in signals.columns:
        return []

    written: list[Path] = []
    buy_tier = signals[signals["signal"].isin(["strong_buy", "buy"])]
    for _, row in buy_tier.iterrows():
        ticker = str(row["ticker"])
        series = history.get(ticker)
        if series is None or series.empty:
            continue
        trade_plan = {
            "core_limit": row.get("core_limit"),
            "tactical_limit": row.get("tactical_limit"),
            "tactical_stop_loss": row.get("tactical_stop_loss"),
            "tactical_take_profit": row.get("tactical_take_profit"),
            "stop_loss": row.get("stop_loss"),
            "take_profit": row.get("take_profit"),
        }
        payload = build_price_chart_payload(
            ticker=ticker,
            name=str(row.get("name") or ticker),
            series=series,
            trade_plan=trade_plan,
            signal=str(row.get("signal") or ""),
            as_of=as_of,
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
            trade_plan=report.get("trade_plan") if isinstance(report.get("trade_plan"), dict) else None,
            signal=str(report.get("signal") or ""),
            as_of=as_of,
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
