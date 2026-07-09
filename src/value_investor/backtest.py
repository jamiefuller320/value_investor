"""Backtest screening signals against forward returns."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

BENCHMARK_TICKER = "^FTSE"
HISTORY_DIR = "history"
HORIZON_DAYS = (7, 28, 84)  # ~1 week, ~1 month, ~3 months


@dataclass
class HorizonResult:
    horizon_days: int
    signal: str
    avg_return: float
    count: int
    benchmark_return: float
    excess_return: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon_days": self.horizon_days,
            "signal": self.signal,
            "avg_return": round(self.avg_return, 4),
            "count": self.count,
            "benchmark_return": round(self.benchmark_return, 4),
            "excess_return": round(self.excess_return, 4),
        }


@dataclass
class BacktestSummary:
    run_count: int
    horizons: list[HorizonResult] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_count": self.run_count,
            "horizons": [h.to_dict() for h in self.horizons],
            "note": self.note,
        }

    def has_results(self) -> bool:
        return bool(self.horizons)


def _safe_price(ticker: str) -> float | None:
    try:
        stock = yf.Ticker(ticker)
        fast = getattr(stock, "fast_info", None)
        price = getattr(fast, "last_price", None) if fast else None
        if price is None:
            info = stock.info or {}
            price = info.get("regularMarketPrice") or info.get("previousClose")
        return float(price) if price is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("Price fetch failed for %s: %s", ticker, exc)
        return None


def snapshot_prices(tickers: list[str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for ticker in tickers:
        price = _safe_price(ticker)
        if price is not None:
            prices[ticker] = price
    bench = _safe_price(BENCHMARK_TICKER)
    if bench is not None:
        prices[BENCHMARK_TICKER] = bench
    return prices


@dataclass
class RunSnapshot:
    run_at: str
    prices: dict[str, float]
    signals: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_at": self.run_at,
            "prices": self.prices,
            "signals": self.signals,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunSnapshot:
        return cls(
            run_at=str(data["run_at"]),
            prices={k: float(v) for k, v in data["prices"].items()},
            signals=list(data["signals"]),
        )


def save_run_snapshot(
    output_dir: Path,
    *,
    run_at: datetime,
    signals: pd.DataFrame,
) -> Path:
    """Persist prices and signals for future backtest evaluation."""
    history_dir = output_dir / HISTORY_DIR
    history_dir.mkdir(parents=True, exist_ok=True)

    tickers = signals["ticker"].tolist()
    prices = snapshot_prices(tickers)

    snapshot = RunSnapshot(
        run_at=run_at.isoformat(),
        prices=prices,
        signals=signals[
            ["ticker", "signal", "conviction_score", "data_quality_score"]
        ].to_dict(orient="records"),
    )

    stamp = run_at.strftime("%Y%m%d_%H%M%S")
    path = history_dir / f"run_{stamp}.json"
    path.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    return path


def load_run_snapshots(output_dir: Path) -> list[RunSnapshot]:
    history_dir = output_dir / HISTORY_DIR
    if not history_dir.exists():
        return []

    snapshots: list[RunSnapshot] = []
    for path in sorted(history_dir.glob("run_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            snapshots.append(RunSnapshot.from_dict(data))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Skipping corrupt snapshot %s: %s", path, exc)
    return snapshots


def _parse_run_at(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _find_exit_snapshot(
    entry: RunSnapshot,
    snapshots: list[RunSnapshot],
    horizon_days: int,
) -> RunSnapshot | None:
    entry_at = _parse_run_at(entry.run_at)
    target = entry_at.timestamp() + horizon_days * 86400
    candidates = [
        s
        for s in snapshots
        if _parse_run_at(s.run_at).timestamp() >= target
        and _parse_run_at(s.run_at) > entry_at
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda s: _parse_run_at(s.run_at).timestamp())


def compute_backtest(snapshots: list[RunSnapshot]) -> BacktestSummary:
    """Evaluate average forward returns by signal bucket across stored runs."""
    if len(snapshots) < 2:
        return BacktestSummary(
            run_count=len(snapshots),
            note="Need at least 2 archived runs to compute forward returns.",
        )

    results: list[HorizonResult] = []
    for horizon in HORIZON_DAYS:
        by_signal: dict[str, list[float]] = {}
        benchmark_returns: list[float] = []

        for entry in snapshots[:-1]:
            exit_snap = _find_exit_snapshot(entry, snapshots, horizon)
            if exit_snap is None:
                continue

            bench_entry = entry.prices.get(BENCHMARK_TICKER)
            bench_exit = exit_snap.prices.get(BENCHMARK_TICKER)
            if bench_entry and bench_exit and bench_entry > 0:
                benchmark_returns.append((bench_exit - bench_entry) / bench_entry)

            for row in entry.signals:
                ticker = row["ticker"]
                signal = str(row["signal"])
                p0 = entry.prices.get(ticker)
                p1 = exit_snap.prices.get(ticker)
                if p0 is None or p1 is None or p0 <= 0:
                    continue
                ret = (p1 - p0) / p0
                by_signal.setdefault(signal, []).append(ret)

        if not by_signal:
            continue

        bench_avg = sum(benchmark_returns) / len(benchmark_returns) if benchmark_returns else 0.0
        for signal, returns in sorted(by_signal.items()):
            avg = sum(returns) / len(returns)
            results.append(
                HorizonResult(
                    horizon_days=horizon,
                    signal=signal,
                    avg_return=avg,
                    count=len(returns),
                    benchmark_return=bench_avg,
                    excess_return=avg - bench_avg,
                )
            )

    note = ""
    if not results:
        note = "No horizons have enough archived run pairs yet — keep running weekly."

    return BacktestSummary(run_count=len(snapshots), horizons=results, note=note)


def format_backtest_text(summary: BacktestSummary) -> str:
    if not summary.has_results():
        return summary.note or "Backtest data not yet available."

    lines = ["Signal backtest (vs FTSE 100 benchmark):"]
    current_horizon: int | None = None
    for result in summary.horizons:
        if result.horizon_days != current_horizon:
            current_horizon = result.horizon_days
            weeks = result.horizon_days // 7
            lines.append(f"  ~{weeks}w horizon:")
        excess = f"{result.excess_return:+.1%} vs benchmark"
        lines.append(
            f"    {result.signal}: {result.avg_return:+.1%} avg "
            f"(n={result.count}, {excess})"
        )
    lines.append(f"Based on {summary.run_count} archived runs.")
    return "\n".join(lines)
