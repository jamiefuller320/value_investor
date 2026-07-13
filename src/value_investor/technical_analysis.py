"""Technical analysis and market-timing signals from price history."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from value_investor.constituents import to_lse_ticker

logger = logging.getLogger(__name__)

MIN_BARS = 200
LOOKBACK_PERIOD = "1y"

# Trade plan thresholds (tunable)
CORE_LIMIT_BELOW_SPOT = 0.99
TACTICAL_LIMIT_BELOW_SPOT = 0.95
TACTICAL_STOP_BELOW_SUPPORT = 0.97
SUPPORT_FLOOR_BELOW_SPOT = 0.92
TACTICAL_TARGET_ABOVE_LIMIT = 1.06
TACTICAL_TARGET_ABOVE_SPOT = 1.05
EXTENDED_ABOVE_SMA200 = 1.03


class TimingSignal(str, Enum):
    ACCUMULATE = "accumulate"
    NEUTRAL = "neutral"
    WAIT = "wait"
    INSUFFICIENT_DATA = "insufficient_data"


TIMING_LABELS = {
    TimingSignal.ACCUMULATE: "Accumulate",
    TimingSignal.NEUTRAL: "Neutral",
    TimingSignal.WAIT: "Wait",
    TimingSignal.INSUFFICIENT_DATA: "N/A",
}


@dataclass
class TradePlan:
    """Order levels for building a core holding plus tactical dip entries."""

    core_order: str | None = None
    core_limit: float | None = None
    core_allocation_pct: float | None = None
    tactical_order: str | None = None
    tactical_limit: float | None = None
    tactical_allocation_pct: float | None = None
    tactical_stop_loss: float | None = None
    tactical_take_profit: float | None = None
    trade_plan_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "core_order": self.core_order,
            "core_limit": self.core_limit,
            "core_allocation_pct": self.core_allocation_pct,
            "tactical_order": self.tactical_order,
            "tactical_limit": self.tactical_limit,
            "tactical_allocation_pct": self.tactical_allocation_pct,
            "tactical_stop_loss": self.tactical_stop_loss,
            "tactical_take_profit": self.tactical_take_profit,
            "trade_plan_summary": self.trade_plan_summary,
        }


@dataclass
class TechnicalIndicators:
    close: float | None = None
    rsi_14: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    macd_histogram: float | None = None
    macd_histogram_prev: float | None = None
    price_vs_sma200_pct: float | None = None
    timing_signal: TimingSignal = TimingSignal.INSUFFICIENT_DATA
    timing_score: float = 0.0
    timing_reasons: list[str] = field(default_factory=list)
    action_note: str = ""
    trade_plan: TradePlan | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "close": self.close,
            "rsi_14": self.rsi_14,
            "sma_50": self.sma_50,
            "sma_200": self.sma_200,
            "macd_histogram": self.macd_histogram,
            "price_vs_sma200_pct": self.price_vs_sma200_pct,
            "timing_signal": self.timing_signal.value,
            "timing_score": round(self.timing_score, 4),
            "timing_reasons": self.timing_reasons,
            "action_note": self.action_note,
        }


def _round_price(value: float) -> float:
    return round(value, 2)


def _recent_low(close: pd.Series, days: int = 20) -> float | None:
    if len(close) < days:
        return None
    return float(close.tail(days).min())


def compute_trade_plan(
    close: pd.Series,
    tech: TechnicalIndicators,
    *,
    value_signal: str,
) -> TradePlan | None:
    """
    Recommend core + tactical orders for strong buys and buys.

    Core leg builds the long-term holding; tactical limit orders exploit
    short-term dips with a defined stop-loss and take-profit.
    """
    if value_signal not in ("strong_buy", "buy") or tech.close is None:
        return None

    price = tech.close
    sma50 = tech.sma_50
    sma200 = tech.sma_200
    recent_low = _recent_low(close)
    timing = tech.timing_signal
    rsi = tech.rsi_14 or 50.0

    if timing == TimingSignal.ACCUMULATE:
        core_pct = 0.75 if rsi < 40 else 0.65
        core_order = "market"
        if rsi >= 35 or (sma200 is not None and price > sma200 * EXTENDED_ABOVE_SMA200):
            core_order = "limit"
    elif timing == TimingSignal.WAIT:
        core_pct = 0.50
        core_order = "limit"
    else:
        core_pct = 0.60
        core_order = "limit"

    tactical_pct = round(1.0 - core_pct, 2)

    core_limit = None
    if core_order == "limit":
        candidates = [price * CORE_LIMIT_BELOW_SPOT]
        if sma50 is not None and sma50 < price:
            candidates.append(sma50)
        core_limit = _round_price(min(candidates))

    tactical_candidates = [price * TACTICAL_LIMIT_BELOW_SPOT]
    if recent_low is not None:
        tactical_candidates.append(recent_low)
    if sma200 is not None and sma200 < price:
        tactical_candidates.append(sma200)
    if sma50 is not None and sma50 < price * 0.98:
        tactical_candidates.append(sma50 * 0.98)
    tactical_limit = _round_price(min(tactical_candidates))

    support_floor = min(
        p for p in [recent_low, sma200, tactical_limit, price * SUPPORT_FLOOR_BELOW_SPOT] if p is not None
    )
    tactical_stop_loss = _round_price(support_floor * TACTICAL_STOP_BELOW_SUPPORT)

    if sma50 is not None and price < sma50:
        tactical_take_profit = _round_price(sma50)
    else:
        tactical_take_profit = _round_price(
            max(tactical_limit * TACTICAL_TARGET_ABOVE_LIMIT, price * TACTICAL_TARGET_ABOVE_SPOT)
        )

    summary = format_trade_plan_summary(
        core_order=core_order,
        core_limit=core_limit,
        core_allocation_pct=core_pct,
        tactical_limit=tactical_limit,
        tactical_allocation_pct=tactical_pct,
        tactical_stop_loss=tactical_stop_loss,
        tactical_take_profit=tactical_take_profit,
        close=price,
    )

    return TradePlan(
        core_order=core_order,
        core_limit=core_limit,
        core_allocation_pct=core_pct,
        tactical_order="limit",
        tactical_limit=tactical_limit,
        tactical_allocation_pct=tactical_pct,
        tactical_stop_loss=tactical_stop_loss,
        tactical_take_profit=tactical_take_profit,
        trade_plan_summary=summary,
    )


def format_trade_plan_summary(
    *,
    core_order: str,
    core_limit: float | None,
    core_allocation_pct: float,
    tactical_limit: float,
    tactical_allocation_pct: float,
    tactical_stop_loss: float,
    tactical_take_profit: float,
    close: float,
) -> str:
    core_pct = f"{core_allocation_pct:.0%}"
    tactical_pct = f"{tactical_allocation_pct:.0%}"
    if core_order == "market":
        core_text = f"core {core_pct} at market (~£{close:.2f})"
    else:
        core_text = f"core {core_pct} limit £{core_limit:.2f}"
    tactical_text = f"tactical {tactical_pct} limit £{tactical_limit:.2f}"
    risk_text = (
        f"tactical stop £{tactical_stop_loss:.2f}, target £{tactical_take_profit:.2f}"
    )
    return f"Trade plan: {core_text}; {tactical_text}; {risk_text}."


def format_trade_plan_text(plan: TradePlan | None) -> str:
    if plan is None or not plan.trade_plan_summary:
        return ""
    return plan.trade_plan_summary


def trade_plan_from_row(row: pd.Series) -> TradePlan | None:
    """Reconstruct a trade plan from flattened signal columns."""
    summary = row.get("trade_plan_summary")
    if summary is not None and isinstance(summary, float) and pd.isna(summary):
        summary = None
    elif summary is not None:
        summary = str(summary)

    core_order = row.get("core_order")
    if core_order is not None and isinstance(core_order, float) and pd.isna(core_order):
        core_order = None

    if not summary and core_order is None:
        return None

    def _optional_float(key: str) -> float | None:
        value = row.get(key)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)

    tactical_order = row.get("tactical_order")
    if tactical_order is not None and isinstance(tactical_order, float) and pd.isna(tactical_order):
        tactical_order = None

    return TradePlan(
        core_order=str(core_order) if core_order is not None else None,
        core_limit=_optional_float("core_limit"),
        core_allocation_pct=_optional_float("core_allocation_pct"),
        tactical_order=str(tactical_order) if tactical_order is not None else None,
        tactical_limit=_optional_float("tactical_limit"),
        tactical_allocation_pct=_optional_float("tactical_allocation_pct"),
        tactical_stop_loss=_optional_float("tactical_stop_loss") or _optional_float("stop_loss"),
        tactical_take_profit=_optional_float("tactical_take_profit") or _optional_float("take_profit"),
        trade_plan_summary=summary,
    )


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def _macd_histogram(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd - signal, macd


def compute_indicators(close: pd.Series) -> TechnicalIndicators:
    """Compute RSI, moving averages, MACD, and timing signal from daily closes."""
    clean = close.dropna()
    if len(clean) < MIN_BARS:
        return TechnicalIndicators(timing_signal=TimingSignal.INSUFFICIENT_DATA)

    rsi_series = _rsi(clean)
    hist, _ = _macd_histogram(clean)
    sma_50 = clean.rolling(50).mean()
    sma_200 = clean.rolling(200).mean()

    last_close = float(clean.iloc[-1])
    rsi_14 = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else None
    sma50 = float(sma_50.iloc[-1]) if pd.notna(sma_50.iloc[-1]) else None
    sma200 = float(sma_200.iloc[-1]) if pd.notna(sma_200.iloc[-1]) else None
    macd_hist = float(hist.iloc[-1]) if pd.notna(hist.iloc[-1]) else None
    macd_hist_prev = float(hist.iloc[-2]) if len(hist) > 1 and pd.notna(hist.iloc[-2]) else None

    vs_sma200 = None
    if sma200 and sma200 > 0:
        vs_sma200 = (last_close - sma200) / sma200

    timing_signal, timing_score, reasons = assign_timing_signal(
        rsi=rsi_14,
        close=last_close,
        sma_50=sma50,
        sma_200=sma200,
        macd_histogram=macd_hist,
        macd_histogram_prev=macd_hist_prev,
    )

    return TechnicalIndicators(
        close=last_close,
        rsi_14=rsi_14,
        sma_50=sma50,
        sma_200=sma200,
        macd_histogram=macd_hist,
        macd_histogram_prev=macd_hist_prev,
        price_vs_sma200_pct=vs_sma200,
        timing_signal=timing_signal,
        timing_score=timing_score,
        timing_reasons=reasons,
    )


def assign_timing_signal(
    *,
    rsi: float | None,
    close: float | None,
    sma_50: float | None,
    sma_200: float | None,
    macd_histogram: float | None,
    macd_histogram_prev: float | None,
) -> tuple[TimingSignal, float, list[str]]:
    """
    Score market timing for value entries.

    Favourable: oversold RSI, trading below/near 200-day MA, MACD turning up.
    Unfavourable: overbought, extended above MAs, negative momentum.
    """
    if close is None or rsi is None:
        return TimingSignal.INSUFFICIENT_DATA, 0.0, ["insufficient price history"]

    points = 0
    reasons: list[str] = []

    if rsi < 30:
        points += 2
        reasons.append(f"RSI oversold ({rsi:.0f})")
    elif rsi < 45:
        points += 1
        reasons.append(f"RSI below neutral ({rsi:.0f})")
    elif rsi > 70:
        points -= 2
        reasons.append(f"RSI overbought ({rsi:.0f})")
    elif rsi > 55:
        points -= 1
        reasons.append(f"RSI elevated ({rsi:.0f})")

    if sma_200 is not None:
        vs_200 = (close - sma_200) / sma_200
        if vs_200 < -0.05:
            points += 1
            reasons.append("below 200-day MA")
        elif vs_200 > 0.15:
            points -= 1
            reasons.append("extended above 200-day MA")

    if sma_50 is not None and sma_200 is not None:
        if close > sma_50 > sma_200:
            points += 1
            reasons.append("uptrend (price > 50 > 200 MA)")
        elif close < sma_50 < sma_200:
            points -= 1
            reasons.append("downtrend (price < 50 < 200 MA)")

    if macd_histogram is not None and macd_histogram_prev is not None:
        if macd_histogram > 0 and macd_histogram > macd_histogram_prev:
            points += 1
            reasons.append("MACD momentum improving")
        elif macd_histogram < 0 and macd_histogram < macd_histogram_prev:
            points -= 1
            reasons.append("MACD momentum weakening")

    if points >= 2:
        signal = TimingSignal.ACCUMULATE
    elif points <= -2:
        signal = TimingSignal.WAIT
    else:
        signal = TimingSignal.NEUTRAL

    # Normalise rough score to 0–1 for display
    timing_score = max(0.0, min(1.0, 0.5 + points * 0.125))
    return signal, timing_score, reasons


def combined_action(value_signal: str, timing_signal: str) -> str:
    """Merge fundamental value signal with technical timing."""
    if value_signal in ("avoid", "insufficient_data"):
        return "Pass — weak fundamentals"
    if timing_signal == TimingSignal.INSUFFICIENT_DATA.value:
        return f"{value_signal.replace('_', ' ').title()} — timing data unavailable"

    value_label = value_signal.replace("_", " ").title()
    timing = timing_signal

    if value_signal in ("strong_buy", "buy"):
        if timing == TimingSignal.ACCUMULATE.value:
            return f"{value_label} — favourable entry timing"
        if timing == TimingSignal.WAIT.value:
            return f"{value_label} — wait for pullback"
        return f"{value_label} — neutral timing"

    if value_signal == "hold" and timing == TimingSignal.ACCUMULATE.value:
        return "Hold — technically attractive, fundamentals mixed"

    return f"{value_label} — {timing} timing"


def _extract_close_series(data: pd.DataFrame, ticker: str) -> pd.Series | None:
    if data.empty:
        return None
    if isinstance(data.columns, pd.MultiIndex):
        if "Close" in data.columns.get_level_values(0):
            if ticker in data["Close"].columns:
                return data["Close"][ticker]
        return None
    if "Close" in data.columns:
        return data["Close"]
    return None


def fetch_close_history(tickers: list[str], *, period: str = LOOKBACK_PERIOD) -> dict[str, pd.Series]:
    """Batch-fetch daily close prices for technical indicators."""
    if not tickers:
        return {}

    # Resolve Yahoo symbols but return series keyed by the original ticker labels.
    unique = list(dict.fromkeys(tickers))
    symbol_by_ticker = {
        ticker: (ticker if ticker.startswith("^") else to_lse_ticker(ticker)) for ticker in unique
    }
    symbols = list(dict.fromkeys(symbol_by_ticker.values()))
    try:
        if len(symbols) == 1:
            symbol = symbols[0]
            data = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=True)
            series = _extract_close_series(data, symbol)
            if series is None:
                return {}
            return {ticker: series for ticker, mapped in symbol_by_ticker.items() if mapped == symbol}
        data = yf.download(symbols, period=period, interval="1d", progress=False, auto_adjust=True, group_by="column")
        out: dict[str, pd.Series] = {}
        for ticker, symbol in symbol_by_ticker.items():
            series = _extract_close_series(data, symbol)
            if series is not None:
                out[ticker] = series
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Batch price download failed: %s", exc)
        return {}


def _technical_row_dict(tech: TechnicalIndicators) -> dict[str, Any]:
    """Serialize indicators; flatten trade plan only at the DataFrame boundary."""
    row = tech.to_dict()
    if tech.trade_plan is not None:
        row.update(tech.trade_plan.to_dict())
    return row


def enrich_signals_with_technicals(
    signals: pd.DataFrame,
    *,
    chart_dir: Path | None = None,
) -> pd.DataFrame:
    """Add technical indicators and timing signals to the signals DataFrame."""
    out = signals.copy()
    tickers = out["ticker"].tolist()
    history = fetch_close_history(tickers)

    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        series = history.get(ticker)
        if series is None or series.empty:
            tech = TechnicalIndicators()
        else:
            value_signal = str(out.loc[out["ticker"] == ticker, "signal"].iloc[0])
            tech = compute_indicators(series)
            tech.action_note = combined_action(value_signal, tech.timing_signal.value)
            if (
                value_signal in ("strong_buy", "buy")
                and tech.timing_signal != TimingSignal.INSUFFICIENT_DATA
            ):
                tech.trade_plan = compute_trade_plan(series, tech, value_signal=value_signal)
            rows.append({"ticker": ticker, **_technical_row_dict(tech)})
            continue

        rows.append({"ticker": ticker, **_technical_row_dict(tech)})

    tech_df = pd.DataFrame(rows)
    enriched = out.merge(tech_df, on="ticker", how="left")

    if chart_dir is not None:
        from value_investor.price_charts import write_buy_tier_charts_from_history

        write_buy_tier_charts_from_history(
            signals=enriched,
            history=history,
            chart_dir=Path(chart_dir),
        )

    return enriched


def timing_label(timing_signal: str) -> str:
    try:
        return TIMING_LABELS[TimingSignal(timing_signal)]
    except ValueError:
        return timing_signal.replace("_", " ").title()


def format_timing_summary(timing_signal: str, rsi: float | None, reasons: list[str] | str) -> str:
    label = timing_label(timing_signal)
    rsi_text = f", RSI {rsi:.0f}" if rsi is not None else ""
    if isinstance(reasons, str):
        reason_text = reasons
    elif reasons:
        reason_text = "; ".join(reasons[:3])
    else:
        reason_text = "no clear technical edge"
    return f"Timing: {label}{rsi_text} ({reason_text})"
