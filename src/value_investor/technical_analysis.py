"""Technical analysis and market-timing signals from price history."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

MIN_BARS = 200
LOOKBACK_PERIOD = "1y"


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

    unique = list(dict.fromkeys(tickers))
    try:
        if len(unique) == 1:
            data = yf.download(unique[0], period=period, interval="1d", progress=False, auto_adjust=True)
            series = _extract_close_series(data, unique[0])
            return {unique[0]: series} if series is not None else {}
        data = yf.download(unique, period=period, interval="1d", progress=False, auto_adjust=True, group_by="column")
        out: dict[str, pd.Series] = {}
        for ticker in unique:
            series = _extract_close_series(data, ticker)
            if series is not None:
                out[ticker] = series
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Batch price download failed: %s", exc)
        return {}


def enrich_signals_with_technicals(signals: pd.DataFrame) -> pd.DataFrame:
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
            tech = compute_indicators(series)

        value_signal = str(out.loc[out["ticker"] == ticker, "signal"].iloc[0])
        tech.action_note = combined_action(value_signal, tech.timing_signal.value)
        rows.append({"ticker": ticker, **tech.to_dict()})

    tech_df = pd.DataFrame(rows)
    return out.merge(tech_df, on="ticker", how="left")


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
