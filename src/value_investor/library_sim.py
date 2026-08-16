"""Observe-only offline paper sims for graduated library markets (stage 3)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from value_investor.backtest import HISTORY_DIR, RunSnapshot, load_run_snapshots
from value_investor.library_screen import screen_dir_for
from value_investor.research.verdict import coerce_research_verdict, compute_adjusted_signal
from value_investor.simulator import SimulationSummary, SimulatorConfig, run_simulation
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

MARKET_BENCHMARKS: dict[str, str] = {
    "sp500": "^GSPC",
    "nasdaq100": "^NDX",
    "euro_stoxx50": "^STOXX50E",
    "asx200": "^AXJO",
    "dax": "^GDAXI",
    "cac40": "^FCHI",
    "tsx60": "^GSPTSE",
    "iseq20": "^IETP",
}

_STAMP_RE = re.compile(r"signals_(\d{8}_\d{6})\.csv$")


DEFAULT_OBSERVE_SIM_MARKETS: tuple[str, ...] = ("sp500",)
OBSERVE_SIM_MARKETS_MODE_EXPLICIT = "explicit"
OBSERVE_SIM_MARKETS_MODE_GRADUATED_BENCHMARK = "graduated_benchmark"


def observe_sim_markets_for_policy(policy: dict[str, Any]) -> list[str]:
    """Markets that get an observe-only sim refresh after screen-lite in the ladder."""
    ladder = policy.get("ladder") or {}
    if not ladder.get("observe_sim_after_screen", True):
        return []
    mode = str(ladder.get("observe_sim_markets_mode") or OBSERVE_SIM_MARKETS_MODE_EXPLICIT)
    if mode == OBSERVE_SIM_MARKETS_MODE_GRADUATED_BENCHMARK:
        from value_investor.library_graduation import graduated_market_ids

        markets = graduated_market_ids(policy)
    else:
        configured = ladder.get("observe_sim_markets")
        if configured is None:
            markets = list(DEFAULT_OBSERVE_SIM_MARKETS)
        else:
            markets = [str(mid) for mid in configured if str(mid).strip()]
    extra = [
        str(mid) for mid in (ladder.get("observe_sim_markets_extra") or []) if str(mid).strip()
    ]
    ordered: list[str] = []
    for mid in [*markets, *extra]:
        if mid not in ordered:
            ordered.append(mid)
    return [mid for mid in ordered if mid in MARKET_BENCHMARKS]


def run_observe_sims_for_screened_markets(
    root: Path,
    policy: dict[str, Any],
    screened_markets: set[str] | list[str],
) -> dict[str, Any]:
    """Refresh observe-only sims for configured markets that were screened this run."""
    targets = [
        mid for mid in observe_sim_markets_for_policy(policy) if mid in set(screened_markets)
    ]
    if not targets:
        return {
            "skipped": True,
            "reason": "no observe-sim markets screened this run",
            "eligible": observe_sim_markets_for_policy(policy),
        }
    markets_out: dict[str, Any] = {}
    for mid in targets:
        try:
            result = run_library_observe_sim(root, mid, rebuild_snapshots=True)
            screen = result.tracks.get("screen_rules") or {}
            markets_out[mid] = {
                "snapshot_count": result.snapshot_count,
                "benchmark": result.benchmark,
                "comparison_note": result.comparison_note,
                "screen_rules_excess": screen.get("excess_return"),
                "screen_rules_return": screen.get("total_return"),
                "trade_count": screen.get("trade_count"),
                "path": f"markets/{mid}/screen/sim/observe_summary.json",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Observe sim for %s failed: %s", mid, exc)
            markets_out[mid] = {"error": str(exc)}
    return {"skipped": False, "markets": markets_out}


@dataclass
class LibraryObserveSimResult:
    market: str
    benchmark: str
    generated_at: str
    snapshot_count: int
    tracks: dict[str, dict[str, Any]]
    comparison_note: str
    caveat: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "benchmark": self.benchmark,
            "generated_at": self.generated_at,
            "snapshot_count": self.snapshot_count,
            "observe_only": True,
            "tracks": self.tracks,
            "comparison_note": self.comparison_note,
            "caveat": self.caveat,
        }


def benchmark_for_market(market_id: str) -> str:
    return MARKET_BENCHMARKS.get(market_id, "^GSPC")


def _parse_stamp(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y%m%d_%H%M%S").replace(tzinfo=UTC)


def iter_library_screen_runs(screen_dir: Path) -> list[tuple[datetime, Path, Path]]:
    """Return dated (run_at, signals_path, universe_path) tuples, oldest first."""
    runs: list[tuple[datetime, Path, Path]] = []
    for signals_path in sorted(screen_dir.glob("signals_*.csv")):
        if signals_path.name.startswith("latest_"):
            continue
        match = _STAMP_RE.match(signals_path.name)
        if not match:
            continue
        stamp = match.group(1)
        universe_path = screen_dir / f"universe_{stamp}.csv"
        if not universe_path.exists():
            logger.warning("Missing universe for %s", signals_path.name)
            continue
        runs.append((_parse_stamp(stamp), signals_path, universe_path))
    runs.sort(key=lambda row: row[0])
    return runs


def _load_research_index(research_dir: Path) -> dict[str, list[tuple[datetime, dict[str, Any]]]]:
    """Ticker -> sorted list of (created_at, fields) from library memos."""
    index: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    if not research_dir.exists():
        return index
    for memo_path in research_dir.glob("*/research.json"):
        try:
            doc = read_json(memo_path)
        except (OSError, ValueError, TypeError):
            continue
        ticker = str(doc.get("ticker") or memo_path.parent.name).strip().upper()
        created_raw = str(doc.get("created_at") or doc.get("updated_at") or "")
        try:
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
        except ValueError:
            created = datetime.min.replace(tzinfo=UTC)
        verdict = coerce_research_verdict(str(doc.get("research_verdict") or ""))
        index.setdefault(ticker, []).append(
            (
                created,
                {
                    "research_verdict": verdict,
                    "research_confidence": doc.get("research_confidence"),
                },
            )
        )
    for rows in index.values():
        rows.sort(key=lambda item: item[0])
    return index


def _research_as_of(
    index: dict[str, list[tuple[datetime, dict[str, Any]]]],
    ticker: str,
    run_at: datetime,
) -> dict[str, Any] | None:
    rows = index.get(str(ticker).strip().upper()) or []
    chosen: dict[str, Any] | None = None
    for created, fields in rows:
        if created <= run_at:
            chosen = fields
        else:
            break
    return chosen


def enrich_signals_with_library_research(
    signals: pd.DataFrame,
    *,
    research_dir: Path,
    run_at: datetime,
) -> pd.DataFrame:
    if signals.empty or not research_dir.exists():
        return signals
    index = _load_research_index(research_dir)
    if not index:
        return signals
    out = signals.copy()
    verdicts: list[str | None] = []
    adjusted: list[str] = []
    for row in out.itertuples(index=False):
        ticker = str(getattr(row, "ticker", ""))
        signal = str(getattr(row, "signal", "hold"))
        memo = _research_as_of(index, ticker, run_at)
        if not memo:
            verdicts.append(None)
            adjusted.append(signal)
            continue
        verdict = memo.get("research_verdict")
        verdicts.append(verdict)
        adjusted.append(compute_adjusted_signal(signal, verdict))
    out["research_verdict"] = verdicts
    out["adjusted_signal"] = adjusted
    return out


def _benchmark_closes(
    symbol: str,
    start: datetime,
    end: datetime,
) -> pd.Series:
    try:
        hist = yf.Ticker(symbol).history(
            start=(start - timedelta(days=7)).date().isoformat(),
            end=(end + timedelta(days=2)).date().isoformat(),
            auto_adjust=True,
        )
        if hist is None or hist.empty or "Close" not in hist.columns:
            return pd.Series(dtype=float)
        closes = hist["Close"].dropna()
        if closes.index.tz is None:
            closes.index = closes.index.tz_localize("UTC")
        else:
            closes.index = closes.index.tz_convert("UTC")
        return closes
    except Exception as exc:  # noqa: BLE001
        logger.warning("Benchmark history fetch failed for %s: %s", symbol, exc)
        return pd.Series(dtype=float)


def _benchmark_price_on(closes: pd.Series, run_at: datetime) -> float | None:
    if closes.empty:
        return None
    target = run_at if run_at.tzinfo else run_at.replace(tzinfo=UTC)
    eligible = closes[closes.index <= target]
    if eligible.empty:
        return float(closes.iloc[0])
    return float(eligible.iloc[-1])


def build_library_run_snapshot(
    *,
    signals: pd.DataFrame,
    universe: pd.DataFrame,
    run_at: datetime,
    benchmark: str,
    benchmark_closes: pd.Series,
) -> RunSnapshot:
    price_by_ticker = {}
    if "ticker" in universe.columns and "last_price" in universe.columns:
        for row in universe.itertuples(index=False):
            ticker = str(getattr(row, "ticker", "")).strip()
            price = getattr(row, "last_price", None)
            if ticker and price is not None and not pd.isna(price):
                price_by_ticker[ticker] = float(price)

    bench_px = _benchmark_price_on(benchmark_closes, run_at)
    prices = dict(price_by_ticker)
    if bench_px is not None:
        prices[benchmark] = bench_px

    signals = signals.copy()
    if "conviction_score" not in signals.columns:
        signals["conviction_score"] = 0.0
    if "data_quality_score" not in signals.columns:
        signals["data_quality_score"] = 1.0

    signal_cols = ["ticker", "signal", "conviction_score", "data_quality_score"]
    for optional in ("adjusted_signal", "research_verdict", "timing_signal"):
        if optional in signals.columns:
            signal_cols.append(optional)

    slim = signals[signal_cols].copy()
    for col in ("conviction_score", "data_quality_score"):
        if col in slim.columns:
            slim[col] = pd.to_numeric(slim[col], errors="coerce").fillna(0.0)

    return RunSnapshot(
        run_at=run_at.isoformat(),
        prices=prices,
        signals=slim.to_dict(orient="records"),
    )


def save_library_run_snapshots(
    root: Path,
    market_id: str,
    *,
    benchmark: str | None = None,
) -> list[Path]:
    """Backfill sim-ready RunSnapshot files from dated screen-lite CSV archives."""
    screen_dir = screen_dir_for(root, market_id)
    runs = iter_library_screen_runs(screen_dir)
    if not runs:
        return []

    bench = benchmark or benchmark_for_market(market_id)
    closes = _benchmark_closes(bench, runs[0][0], runs[-1][0])
    research_dir = screen_dir / "research"
    history_dir = screen_dir / HISTORY_DIR
    history_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for run_at, signals_path, universe_path in runs:
        signals = pd.read_csv(signals_path)
        universe = pd.read_csv(universe_path)
        signals = enrich_signals_with_library_research(
            signals,
            research_dir=research_dir,
            run_at=run_at,
        )
        snapshot = build_library_run_snapshot(
            signals=signals,
            universe=universe,
            run_at=run_at,
            benchmark=bench,
            benchmark_closes=closes,
        )
        stamp = run_at.strftime("%Y%m%d_%H%M%S")
        path = history_dir / f"run_{stamp}.json.gz"
        write_json(path, snapshot.to_dict(), compact=True, compress=True)
        written.append(path)
    return written


def _comparison_note(
    screen: SimulationSummary,
    overlay: SimulationSummary,
    ai: SimulationSummary,
) -> str:
    parts: list[str] = []
    if screen.has_results() and overlay.has_results():
        delta = overlay.total_return - screen.total_return
        if abs(delta) >= 0.0001:
            direction = "outperformed" if delta > 0 else "underperformed"
            parts.append(f"Research overlay {direction} screen rules by {delta:+.1%}.")
    if overlay.has_results() and ai.has_results():
        delta = ai.total_return - overlay.total_return
        if abs(delta) >= 0.0001:
            direction = "outperformed" if delta > 0 else "underperformed"
            parts.append(f"AI-judgment gate {direction} research overlay by {delta:+.1%}.")
    if screen.has_results():
        parts.append(
            f"Screen rules excess vs benchmark: {screen.excess_return:+.1%} "
            f"({screen.periods} periods)."
        )
    return " ".join(parts) if parts else "Insufficient archived runs for comparison."


def run_library_observe_sim(
    root: Path,
    market_id: str,
    *,
    benchmark: str | None = None,
    initial_capital: float = 1000.0,
    trade_cost_pct: float = 0.03,
    max_positions: int = 5,
    rebuild_snapshots: bool = True,
) -> LibraryObserveSimResult:
    """
    Observe-only offline paper sim for a library market.

    Writes snapshots under screen/history/ and summary under screen/sim/.
    Does not touch live FTSE paper automation or decision-review knobs.
    """
    bench = benchmark or benchmark_for_market(market_id)
    screen_dir = screen_dir_for(root, market_id)
    sim_dir = screen_dir / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)

    if rebuild_snapshots:
        save_library_run_snapshots(root, market_id, benchmark=bench)

    snapshots = load_run_snapshots(screen_dir)
    base = SimulatorConfig(
        initial_capital=initial_capital,
        trade_cost_pct=trade_cost_pct,
        max_positions=max_positions,
        benchmark_ticker=bench,
    )

    screen_rules = run_simulation(snapshots, base)
    research_overlay = run_simulation(
        snapshots,
        SimulatorConfig(
            initial_capital=base.initial_capital,
            trade_cost_pct=base.trade_cost_pct,
            max_positions=base.max_positions,
            benchmark_ticker=bench,
            use_adjusted_signal=True,
        ),
    )
    ai_judgment = run_simulation(
        snapshots,
        SimulatorConfig(
            initial_capital=base.initial_capital,
            trade_cost_pct=base.trade_cost_pct,
            max_positions=base.max_positions,
            benchmark_ticker=bench,
            use_adjusted_signal=True,
            require_research_accumulate=True,
        ),
    )

    result = LibraryObserveSimResult(
        market=market_id,
        benchmark=bench,
        generated_at=datetime.now(UTC).isoformat(),
        snapshot_count=len(snapshots),
        tracks={
            "screen_rules": screen_rules.to_dict(),
            "research_overlay": research_overlay.to_dict(),
            "ai_judgment": ai_judgment.to_dict(),
        },
        comparison_note=_comparison_note(screen_rules, research_overlay, ai_judgment),
        caveat=(
            "Observe-only library sim — not wired to ftse-decision-review or live paper books. "
            "History is still thin; treat as pressure-test signal, not promotion evidence."
        ),
    )

    write_json(sim_dir / "observe_summary.json", result.to_dict(), compact=False)
    return result
