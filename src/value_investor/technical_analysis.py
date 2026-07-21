"""Technical analysis and market-timing signals from price history."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from value_investor.constituents import to_lse_ticker

logger = logging.getLogger(__name__)

MIN_BARS = 200
LOOKBACK_PERIOD = "1y"
ATR_PERIOD = 14
VOLUME_RATIO_WINDOW = 20


@dataclass
class TradePlanConfig:
    """Tunable trade-plan thresholds (L5). Defaults match the prior hard-coded values."""

    core_limit_below_spot: float = 0.99
    tactical_limit_below_spot: float = 0.95
    tactical_stop_below_support: float = 0.97
    support_floor_below_spot: float = 0.92
    tactical_target_above_limit: float = 1.06
    tactical_target_above_spot: float = 1.05
    extended_above_sma200: float = 1.03
    accumulate_core_pct_low_rsi: float = 0.75
    accumulate_core_pct: float = 0.65
    wait_core_pct: float = 0.50
    neutral_core_pct: float = 0.60
    accumulate_rsi_low: float = 40.0
    accumulate_rsi_limit_gate: float = 35.0
    sma50_tactical_haircut: float = 0.98
    recent_low_days: int = 20
    # When set, stop = min(support stop, close − k×ATR14) if ATR is available.
    atr_stop_multiplier: float | None = 2.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TradePlanConfig:
        raw = data or {}
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in raw.items() if k in known}
        return cls(**kwargs)


DEFAULT_TRADE_PLAN_CONFIG = TradePlanConfig()

# Backward-compatible aliases used by older imports/tests.
CORE_LIMIT_BELOW_SPOT = DEFAULT_TRADE_PLAN_CONFIG.core_limit_below_spot
TACTICAL_LIMIT_BELOW_SPOT = DEFAULT_TRADE_PLAN_CONFIG.tactical_limit_below_spot
TACTICAL_STOP_BELOW_SUPPORT = DEFAULT_TRADE_PLAN_CONFIG.tactical_stop_below_support
SUPPORT_FLOOR_BELOW_SPOT = DEFAULT_TRADE_PLAN_CONFIG.support_floor_below_spot
TACTICAL_TARGET_ABOVE_LIMIT = DEFAULT_TRADE_PLAN_CONFIG.tactical_target_above_limit
TACTICAL_TARGET_ABOVE_SPOT = DEFAULT_TRADE_PLAN_CONFIG.tactical_target_above_spot
EXTENDED_ABOVE_SMA200 = DEFAULT_TRADE_PLAN_CONFIG.extended_above_sma200


def load_trade_plan_config(path: Path) -> TradePlanConfig:
    if not path.exists():
        return TradePlanConfig()
    return TradePlanConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_trade_plan_config(path: Path, config: TradePlanConfig) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


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
    atr_14: float | None = None
    volume_ratio_20: float | None = None
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
            "atr_14": None if self.atr_14 is None else round(self.atr_14, 4),
            "volume_ratio_20": (
                None if self.volume_ratio_20 is None else round(self.volume_ratio_20, 4)
            ),
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
    config: TradePlanConfig | None = None,
) -> TradePlan | None:
    """
    Recommend core + tactical orders for strong buys and buys.

    Core leg builds the long-term holding; tactical limit orders exploit
    short-term dips with a defined stop-loss and take-profit.
    """
    if value_signal not in ("strong_buy", "buy") or tech.close is None:
        return None

    cfg = config or DEFAULT_TRADE_PLAN_CONFIG
    price = tech.close
    sma50 = tech.sma_50
    sma200 = tech.sma_200
    recent_low = _recent_low(close, days=int(cfg.recent_low_days))
    timing = tech.timing_signal
    rsi = tech.rsi_14 or 50.0

    if timing == TimingSignal.ACCUMULATE:
        core_pct = (
            cfg.accumulate_core_pct_low_rsi
            if rsi < cfg.accumulate_rsi_low
            else cfg.accumulate_core_pct
        )
        core_order = "market"
        if rsi >= cfg.accumulate_rsi_limit_gate or (
            sma200 is not None and price > sma200 * cfg.extended_above_sma200
        ):
            core_order = "limit"
    elif timing == TimingSignal.WAIT:
        core_pct = cfg.wait_core_pct
        core_order = "limit"
    else:
        core_pct = cfg.neutral_core_pct
        core_order = "limit"

    tactical_pct = round(1.0 - core_pct, 2)

    core_limit = None
    if core_order == "limit":
        candidates = [price * cfg.core_limit_below_spot]
        if sma50 is not None and sma50 < price:
            candidates.append(sma50)
        core_limit = _round_price(min(candidates))

    tactical_candidates = [price * cfg.tactical_limit_below_spot]
    if recent_low is not None:
        tactical_candidates.append(recent_low)
    if sma200 is not None and sma200 < price:
        tactical_candidates.append(sma200)
    if sma50 is not None and sma50 < price * cfg.sma50_tactical_haircut:
        tactical_candidates.append(sma50 * cfg.sma50_tactical_haircut)
    tactical_limit = _round_price(min(tactical_candidates))

    support_floor = min(
        p
        for p in [recent_low, sma200, tactical_limit, price * cfg.support_floor_below_spot]
        if p is not None
    )
    tactical_stop_loss = _round_price(support_floor * cfg.tactical_stop_below_support)
    if (
        cfg.atr_stop_multiplier is not None
        and tech.atr_14 is not None
        and tech.atr_14 > 0
    ):
        atr_stop = _round_price(price - float(cfg.atr_stop_multiplier) * float(tech.atr_14))
        if atr_stop > 0:
            tactical_stop_loss = _round_price(min(tactical_stop_loss, atr_stop))

    if sma50 is not None and price < sma50:
        tactical_take_profit = _round_price(sma50)
    else:
        tactical_take_profit = _round_price(
            max(
                tactical_limit * cfg.tactical_target_above_limit,
                price * cfg.tactical_target_above_spot,
            )
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


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, *, period: int = ATR_PERIOD) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _volume_ratio(volume: pd.Series, *, window: int = VOLUME_RATIO_WINDOW) -> float | None:
    clean = volume.dropna()
    if len(clean) < window + 1:
        return None
    avg = float(clean.tail(window).mean())
    last = float(clean.iloc[-1])
    if avg <= 0:
        return None
    return last / avg


def _split_price_input(
    price_data: pd.Series | pd.DataFrame,
) -> tuple[pd.Series, pd.Series | None, pd.Series | None, pd.Series | None]:
    if isinstance(price_data, pd.DataFrame):
        if "Close" not in price_data.columns:
            raise ValueError("OHLCV frame must include a Close column")
        close = price_data["Close"]
        high = price_data["High"] if "High" in price_data.columns else None
        low = price_data["Low"] if "Low" in price_data.columns else None
        volume = price_data["Volume"] if "Volume" in price_data.columns else None
        return close, high, low, volume
    return price_data, None, None, None


def compute_indicators(price_data: pd.Series | pd.DataFrame) -> TechnicalIndicators:
    """Compute RSI, MAs, MACD, timing, and optional ATR/volume from closes or OHLCV."""
    close, high, low, volume = _split_price_input(price_data)
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

    atr_14 = None
    if high is not None and low is not None:
        aligned = pd.concat(
            {"high": high, "low": low, "close": close}, axis=1
        ).dropna()
        if len(aligned) >= MIN_BARS:
            atr_series = _atr(aligned["high"], aligned["low"], aligned["close"])
            if pd.notna(atr_series.iloc[-1]):
                atr_14 = float(atr_series.iloc[-1])

    volume_ratio_20 = _volume_ratio(volume) if volume is not None else None

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
        atr_14=atr_14,
        volume_ratio_20=volume_ratio_20,
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
    frame = _extract_ohlcv_frame(data, ticker)
    if frame is None or frame.empty or "Close" not in frame.columns:
        return None
    return frame["Close"]


def _extract_ohlcv_frame(data: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    if data.empty:
        return None
    cols = ("Open", "High", "Low", "Close", "Volume")
    if isinstance(data.columns, pd.MultiIndex):
        level0 = data.columns.get_level_values(0)
        if "Close" not in level0:
            return None
        pieces: dict[str, pd.Series] = {}
        for col in cols:
            if col not in level0:
                continue
            block = data[col]
            if ticker in block.columns:
                pieces[col] = block[ticker]
        if "Close" not in pieces:
            return None
        return pd.DataFrame(pieces)
    present = [c for c in cols if c in data.columns]
    if "Close" not in present:
        return None
    return data[present].copy()


def fetch_price_history(
    tickers: list[str], *, period: str = LOOKBACK_PERIOD
) -> dict[str, pd.DataFrame]:
    """Batch-fetch daily OHLCV frames keyed by the original ticker labels."""
    if not tickers:
        return {}

    unique = list(dict.fromkeys(tickers))
    symbol_by_ticker = {
        ticker: (ticker if ticker.startswith("^") else to_lse_ticker(ticker)) for ticker in unique
    }
    symbols = list(dict.fromkeys(symbol_by_ticker.values()))
    try:
        if len(symbols) == 1:
            symbol = symbols[0]
            data = yf.download(
                symbol, period=period, interval="1d", progress=False, auto_adjust=True
            )
            frame = _extract_ohlcv_frame(data, symbol)
            if frame is None:
                return {}
            return {
                ticker: frame
                for ticker, mapped in symbol_by_ticker.items()
                if mapped == symbol
            }
        data = yf.download(
            symbols,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
            group_by="column",
        )
        out: dict[str, pd.DataFrame] = {}
        for ticker, symbol in symbol_by_ticker.items():
            frame = _extract_ohlcv_frame(data, symbol)
            if frame is not None and not frame.empty:
                out[ticker] = frame
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Batch price download failed: %s", exc)
        return {}


def fetch_close_history(tickers: list[str], *, period: str = LOOKBACK_PERIOD) -> dict[str, pd.Series]:
    """Batch-fetch daily close prices (thin wrapper over OHLCV history)."""
    frames = fetch_price_history(tickers, period=period)
    return {
        ticker: frame["Close"]
        for ticker, frame in frames.items()
        if "Close" in frame.columns and not frame["Close"].empty
    }


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
    trade_plan_config: TradePlanConfig | None = None,
) -> pd.DataFrame:
    """Add technical indicators and timing signals to the signals DataFrame."""
    out = signals.copy()
    tickers = out["ticker"].tolist()
    price_history = fetch_price_history(tickers)
    close_history = {
        ticker: frame["Close"]
        for ticker, frame in price_history.items()
        if "Close" in frame.columns
    }

    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        frame = price_history.get(ticker)
        if frame is None or frame.empty:
            tech = TechnicalIndicators()
        else:
            value_signal = str(out.loc[out["ticker"] == ticker, "signal"].iloc[0])
            tech = compute_indicators(frame)
            tech.action_note = combined_action(value_signal, tech.timing_signal.value)
            if (
                value_signal in ("strong_buy", "buy")
                and tech.timing_signal != TimingSignal.INSUFFICIENT_DATA
            ):
                tech.trade_plan = compute_trade_plan(
                    frame["Close"],
                    tech,
                    value_signal=value_signal,
                    config=trade_plan_config,
                )
            rows.append({"ticker": ticker, **_technical_row_dict(tech)})
            continue

        rows.append({"ticker": ticker, **_technical_row_dict(tech)})

    tech_df = pd.DataFrame(rows)
    enriched = out.merge(tech_df, on="ticker", how="left")

    if chart_dir is not None:
        from value_investor.price_charts import write_buy_tier_charts_from_history

        write_buy_tier_charts_from_history(
            signals=enriched,
            history=close_history,
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
