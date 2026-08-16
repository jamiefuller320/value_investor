"""Decision-review learning on the automated paper book (stage 1 / L1).

Reviews paper-auto outcomes after costs and proposes small clamped updates to
trading knobs. Does not mutate screen signals or model weights.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.backtest import BENCHMARK_TICKER
from value_investor.paper_automation import (
    CONFIG_FILENAME,
    DEFAULT_AUTOMATION_DIR,
    FUND_FILENAME,
    AutomationConfig,
    ensure_automated_fund,
    save_automated_fund,
)
from value_investor.paper_fund import PaperFund
from value_investor.portfolio_diversity import DEFAULT_TARGET_SECTOR_CAP

logger = logging.getLogger(__name__)

REVIEW_FILENAME = "decision_review.json"
REVIEW_HISTORY_FILENAME = "decision_review_history.json"
SHARD_META_FILENAME = "shard_meta.json"
KNOB_EPOCH_FILENAME = "knob_epoch.json"
KNOB_EPOCHS_HISTORY_FILENAME = "knob_epochs.json"

MIN_EQUITY_MARKS = 4
MIN_TRADES = 2
MIN_EPOCH_MARKS = 2
MIN_EPOCH_TRADES = 1

MAX_POSITIONS_BOUNDS = (3, 8)
MIN_CONVICTION_BOUNDS = (0.0, 0.6)
SECTOR_CAP_BOUNDS = (0.20, 1.0)

MAX_POSITIONS_STEP = 1
MIN_CONVICTION_STEP = 0.05
SECTOR_CAP_STEP = 0.05

HIGH_COST_DRAG = 0.04
WEAK_EXCESS = -0.02
STRONG_EXCESS = 0.02
HIGH_CASH_FRACTION = 0.45
HISTORY_KEEP = 52


@dataclass
class LearningKnobs:
    max_positions: int = 5
    skip_timing_wait: bool = True
    min_conviction: float = 0.0
    sector_cap: float = DEFAULT_TARGET_SECTOR_CAP

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_positions": int(self.max_positions),
            "skip_timing_wait": bool(self.skip_timing_wait),
            "min_conviction": round(float(self.min_conviction), 4),
            "sector_cap": round(float(self.sector_cap), 4),
        }

    @classmethod
    def from_config(cls, config: AutomationConfig) -> LearningKnobs:
        return cls(
            max_positions=int(config.max_positions),
            skip_timing_wait=bool(config.skip_timing_wait),
            min_conviction=float(config.min_conviction),
            sector_cap=float(config.sector_cap),
        )

    def apply_to_config(self, config: AutomationConfig) -> None:
        config.max_positions = int(self.max_positions)
        config.skip_timing_wait = bool(self.skip_timing_wait)
        config.min_conviction = float(self.min_conviction)
        config.sector_cap = float(self.sector_cap)


@dataclass
class KnobEpoch:
    """Performance baseline after a decision-review knob apply."""

    started_at: str
    baseline_nav: float
    baseline_contributed_capital: float
    knobs: dict[str, Any]
    trade_count_at_start: int = 0
    equity_marks_at_start: int = 0
    seeded_from_history: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "baseline_nav": round(self.baseline_nav, 2),
            "baseline_contributed_capital": round(self.baseline_contributed_capital, 2),
            "knobs": dict(self.knobs),
            "trade_count_at_start": int(self.trade_count_at_start),
            "equity_marks_at_start": int(self.equity_marks_at_start),
            "seeded_from_history": bool(self.seeded_from_history),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> KnobEpoch | None:
        raw = data or {}
        started = str(raw.get("started_at") or "").strip()
        if not started:
            return None
        knobs = raw.get("knobs")
        if not isinstance(knobs, dict):
            knobs = {}
        return cls(
            started_at=started,
            baseline_nav=float(raw.get("baseline_nav") or 0.0),
            baseline_contributed_capital=float(
                raw.get("baseline_contributed_capital") or raw.get("baseline_nav") or 0.0
            ),
            knobs=knobs,
            trade_count_at_start=int(raw.get("trade_count_at_start") or 0),
            equity_marks_at_start=int(raw.get("equity_marks_at_start") or 0),
            seeded_from_history=bool(raw.get("seeded_from_history", False)),
        )


@dataclass
class BookMetrics:
    portfolio_value: float
    contributed_capital: float
    total_return: float
    total_costs: float
    cost_drag: float
    trade_count: int
    buy_count: int
    sell_count: int
    positions: int
    cash_fraction: float
    equity_marks: int
    max_sector_weight: float
    dominant_sector: str | None
    benchmark_return: float | None
    excess_after_costs: float | None
    note: str = ""
    epoch: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "portfolio_value": round(self.portfolio_value, 2),
            "contributed_capital": round(self.contributed_capital, 2),
            "total_return": round(self.total_return, 4),
            "total_costs": round(self.total_costs, 2),
            "cost_drag": round(self.cost_drag, 4),
            "trade_count": self.trade_count,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "positions": self.positions,
            "cash_fraction": round(self.cash_fraction, 4),
            "equity_marks": self.equity_marks,
            "max_sector_weight": round(self.max_sector_weight, 4),
            "dominant_sector": self.dominant_sector,
            "benchmark_return": (
                None if self.benchmark_return is None else round(self.benchmark_return, 4)
            ),
            "excess_after_costs": (
                None if self.excess_after_costs is None else round(self.excess_after_costs, 4)
            ),
            "note": self.note,
        }
        if self.epoch:
            payload["epoch"] = self.epoch
        return payload


@dataclass
class DecisionReviewResult:
    reviewed_at: str
    enough_history: bool
    applied: bool
    knobs_before: dict[str, Any]
    knobs_after: dict[str, Any]
    proposed_changes: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    counterfactual_preview: dict[str, Any] | None = None
    note: str = ""
    track_id: str = "rules"
    track_label: str = ""
    is_primary_learning_track: bool = False
    success_criterion: str = (
        "Outperformance after costs vs market benchmark (^FTSE); "
        "knob updates only when excess persistently justifies them."
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload.get("counterfactual_preview") is None:
            payload.pop("counterfactual_preview", None)
        return payload


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _trade_dt(trade: Any) -> datetime | None:
    return _parse_iso_date(str(getattr(trade, "acted_at", "") or ""))


def _events_since(
    fund: PaperFund,
    started_at: str,
) -> tuple[list[Any], list[dict[str, Any]]]:
    start_dt = _parse_iso_date(started_at)
    if start_dt is None:
        return list(fund.trades), list(fund.equity_curve)
    trades = [
        trade
        for trade in fund.trades
        if (_trade_dt(trade) or datetime.min.replace(tzinfo=UTC)) > start_dt
    ]
    marks = [
        mark
        for mark in fund.equity_curve
        if (_parse_iso_date(str((mark or {}).get("at") or "")) or datetime.min.replace(tzinfo=UTC))
        > start_dt
    ]
    return trades, marks


def load_knob_epoch(output_dir: Path) -> KnobEpoch | None:
    path = Path(output_dir) / KNOB_EPOCH_FILENAME
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return KnobEpoch.from_dict(raw if isinstance(raw, dict) else None)


def save_knob_epoch(output_dir: Path, epoch: KnobEpoch) -> None:
    path = Path(output_dir) / KNOB_EPOCH_FILENAME
    path.write_text(json.dumps(epoch.to_dict(), indent=2) + "\n", encoding="utf-8")


def _append_knob_epoch_history(output_dir: Path, epoch: KnobEpoch) -> None:
    path = Path(output_dir) / KNOB_EPOCHS_HISTORY_FILENAME
    history: list[dict[str, Any]] = []
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                history = [row for row in raw if isinstance(row, dict)]
        except (json.JSONDecodeError, OSError):
            history = []
    history.append(epoch.to_dict())
    history = history[-HISTORY_KEEP:]
    path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")


def seed_knob_epoch_from_history(output_dir: Path) -> KnobEpoch | None:
    """Backfill the active epoch from the last applied knob change in review history."""
    history_path = Path(output_dir) / REVIEW_HISTORY_FILENAME
    if not history_path.exists():
        return None
    try:
        raw = json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, list):
        return None
    for row in reversed(raw):
        if not isinstance(row, dict) or not row.get("applied"):
            continue
        changes = row.get("proposed_changes") or {}
        if not changes:
            continue
        metrics = row.get("metrics") or {}
        knobs_after = row.get("knobs_after") or {}
        return KnobEpoch(
            started_at=str(row.get("reviewed_at") or ""),
            baseline_nav=float(metrics.get("portfolio_value") or 0.0),
            baseline_contributed_capital=float(
                metrics.get("contributed_capital") or metrics.get("portfolio_value") or 0.0
            ),
            knobs=dict(knobs_after),
            trade_count_at_start=int(metrics.get("trade_count") or 0),
            equity_marks_at_start=int(metrics.get("equity_marks") or 0),
            seeded_from_history=True,
        )
    return None


def ensure_knob_epoch(output_dir: Path) -> KnobEpoch | None:
    epoch = load_knob_epoch(output_dir)
    if epoch is not None:
        return epoch
    seeded = seed_knob_epoch_from_history(output_dir)
    if seeded is not None:
        save_knob_epoch(output_dir, seeded)
    return seeded


def start_knob_epoch(
    output_dir: Path,
    fund: PaperFund,
    knobs: LearningKnobs,
    *,
    reviewed_at: str,
) -> KnobEpoch:
    prices = _mark_prices(fund)
    perf = fund.performance(prices)
    epoch = KnobEpoch(
        started_at=reviewed_at,
        baseline_nav=float(perf["portfolio_value"] or 0.0),
        baseline_contributed_capital=float(perf["contributed_capital"] or 0.0),
        knobs=knobs.to_dict(),
        trade_count_at_start=len(fund.trades),
        equity_marks_at_start=len(fund.equity_curve),
        seeded_from_history=False,
    )
    save_knob_epoch(output_dir, epoch)
    _append_knob_epoch_history(output_dir, epoch)
    return epoch


def _compute_epoch_metrics(
    fund: PaperFund,
    epoch: KnobEpoch,
    *,
    benchmark_return: float | None = None,
    fetch_benchmark: bool = True,
    benchmark_ticker: str | None = None,
) -> dict[str, Any]:
    prices = _mark_prices(fund)
    perf = fund.performance(prices)
    nav = float(perf["portfolio_value"] or 0.0)
    baseline = float(epoch.baseline_nav or 0.0)
    epoch_trades, epoch_marks = _events_since(fund, epoch.started_at)
    epoch_costs = sum(float(t.cost or 0.0) for t in epoch_trades)
    buys = sum(1 for t in epoch_trades if t.side == "buy")
    sells = sum(1 for t in epoch_trades if t.side == "sell")
    epoch_return = ((nav - baseline) / baseline) if baseline > 0 else 0.0
    cost_drag = (epoch_costs / baseline) if baseline > 0 else 0.0
    cash_fraction = (float(fund.cash) / nav) if nav > 0 else 1.0
    max_sector_weight, dominant = _sector_concentration(fund, prices)

    bench = benchmark_return
    ticker = benchmark_ticker or BENCHMARK_TICKER
    note = ""
    if bench is None and fetch_benchmark and len(epoch_marks) >= 2:
        start_dt = _parse_iso_date(epoch.started_at)
        end_dt = _parse_iso_date(str((epoch_marks[-1] or {}).get("at") or ""))
        if start_dt and end_dt:
            bench = fetch_benchmark_return(start_dt, end_dt, ticker=ticker)
            if bench is None:
                note = "Benchmark unavailable for epoch window."
        else:
            note = "Epoch mark timestamps missing."
    elif bench is None and len(epoch_marks) < 2:
        note = "Insufficient epoch marks for benchmark span."

    excess = None if bench is None else epoch_return - float(bench)

    return {
        "started_at": epoch.started_at,
        "knobs": dict(epoch.knobs),
        "seeded_from_history": bool(epoch.seeded_from_history),
        "baseline_nav": round(baseline, 2),
        "portfolio_value": round(nav, 2),
        "total_return": round(epoch_return, 4),
        "total_costs": round(epoch_costs, 2),
        "cost_drag": round(cost_drag, 4),
        "trade_count": len(epoch_trades),
        "buy_count": buys,
        "sell_count": sells,
        "positions": int(perf["positions"]),
        "cash_fraction": round(cash_fraction, 4),
        "equity_marks": len(epoch_marks),
        "max_sector_weight": round(max_sector_weight, 4),
        "dominant_sector": dominant,
        "benchmark_return": None if bench is None else round(float(bench), 4),
        "excess_after_costs": None if excess is None else round(excess, 4),
        "note": note,
    }


def metrics_for_review(metrics: BookMetrics) -> BookMetrics:
    """Prefer epoch-scoped metrics when the active epoch has enough post-change data."""
    epoch = metrics.epoch
    if not epoch:
        return metrics
    if epoch.get("equity_marks", 0) < MIN_EPOCH_MARKS:
        return metrics
    if epoch.get("trade_count", 0) < MIN_EPOCH_TRADES:
        return metrics
    return BookMetrics(
        portfolio_value=float(epoch.get("portfolio_value") or metrics.portfolio_value),
        contributed_capital=float(epoch.get("baseline_nav") or metrics.contributed_capital),
        total_return=float(epoch.get("total_return") or 0.0),
        total_costs=float(epoch.get("total_costs") or 0.0),
        cost_drag=float(epoch.get("cost_drag") or 0.0),
        trade_count=int(epoch.get("trade_count") or 0),
        buy_count=int(epoch.get("buy_count") or 0),
        sell_count=int(epoch.get("sell_count") or 0),
        positions=int(epoch.get("positions") or metrics.positions),
        cash_fraction=float(epoch.get("cash_fraction") or metrics.cash_fraction),
        equity_marks=int(epoch.get("equity_marks") or 0),
        max_sector_weight=float(epoch.get("max_sector_weight") or metrics.max_sector_weight),
        dominant_sector=epoch.get("dominant_sector") or metrics.dominant_sector,
        benchmark_return=epoch.get("benchmark_return"),
        excess_after_costs=epoch.get("excess_after_costs"),
        note=str(epoch.get("note") or metrics.note),
        epoch=epoch,
    )


def enough_epoch_history(epoch: dict[str, Any] | None) -> bool:
    if not epoch:
        return False
    return (
        int(epoch.get("equity_marks") or 0) >= MIN_EPOCH_MARKS
        and int(epoch.get("trade_count") or 0) >= MIN_EPOCH_TRADES
    )


def _ticker_sector_map(fund: PaperFund) -> dict[str, str]:
    sectors: dict[str, str] = {}
    for ticker, pos in fund.holdings.items():
        sectors[str(ticker)] = str(pos.sector or "Unknown") or "Unknown"
    return sectors


def _would_pass_sector_cap(
    *,
    sector: str,
    sector_cap: float,
    max_positions: int,
    holdings: dict[str, dict[str, Any]],
) -> bool:
    if max_positions <= 0:
        return False
    sector = str(sector or "Unknown") or "Unknown"
    per_sector_cap = max(1, int(max_positions * sector_cap))
    same_sector = sum(1 for row in holdings.values() if row.get("sector") == sector)
    return same_sector < per_sector_cap


def estimate_counterfactual_preview(
    fund: PaperFund,
    *,
    knobs: LearningKnobs,
) -> dict[str, Any]:
    """
    Lightweight lifetime replay: which historical trades would have been blocked
    by max_positions / sector_cap if those knobs had applied from inception.

    min_conviction, skip_timing_wait, and AI gates need archived screen snapshots
    for a full path replay — omitted here by design.
    """
    sectors = _ticker_sector_map(fund)
    holdings: dict[str, dict[str, Any]] = {}
    executed = 0
    blocked_buys = 0
    blocked_sells = 0
    blocked_costs = 0.0
    simulated_costs = 0.0
    actual_costs = sum(float(t.cost or 0.0) for t in fund.trades)

    for trade in fund.trades:
        ticker = str(trade.ticker)
        cost = float(trade.cost or 0.0)
        if trade.side == "sell":
            if ticker in holdings:
                del holdings[ticker]
                executed += 1
                simulated_costs += cost
            else:
                blocked_sells += 1
                blocked_costs += cost
            continue

        sector = sectors.get(ticker, "Unknown")
        at_cap = len(holdings) >= int(knobs.max_positions)
        sector_blocked = not _would_pass_sector_cap(
            sector=sector,
            sector_cap=float(knobs.sector_cap),
            max_positions=int(knobs.max_positions),
            holdings=holdings,
        )
        if at_cap or sector_blocked:
            blocked_buys += 1
            blocked_costs += cost
            continue

        holdings[ticker] = {"sector": sector}
        executed += 1
        simulated_costs += cost

    contributed = float(fund.contributed_capital or fund.config.initial_cash or 0.0)
    actual_drag = (actual_costs / contributed) if contributed > 0 else 0.0
    simulated_drag = (simulated_costs / contributed) if contributed > 0 else 0.0
    return {
        "scope": "lifetime_trade_replay",
        "knobs": knobs.to_dict(),
        "limitations": (
            "Replay uses max_positions and sector_cap only; min_conviction, "
            "skip_timing_wait, and AI gates need archived weekly screens for "
            "full counterfactual P&L."
        ),
        "executed_trades": executed,
        "blocked_buys": blocked_buys,
        "blocked_orphan_sells": blocked_sells,
        "actual_total_costs": round(actual_costs, 2),
        "simulated_total_costs": round(simulated_costs, 2),
        "estimated_cost_savings_gbp": round(blocked_costs, 2),
        "actual_cost_drag": round(actual_drag, 4),
        "simulated_cost_drag": round(simulated_drag, 4),
        "cost_drag_delta": round(actual_drag - simulated_drag, 4),
    }


def estimate_counterfactual_with_log(
    output_dir: Path,
    fund: PaperFund,
    *,
    knobs: LearningKnobs,
) -> dict[str, Any]:
    """Prefer rebalance-log replay when enough acted entries exist."""
    from value_investor.rebalance_log import (
        MIN_LOG_ACTED_ENTRIES,
        acted_log_entries,
        compare_rebalance_counterfactual_previews,
        load_rebalance_log,
        replay_counterfactual_from_log,
    )

    entries = load_rebalance_log(output_dir)
    acted = acted_log_entries(entries)
    if len(acted) >= MIN_LOG_ACTED_ENTRIES:
        replay = replay_counterfactual_from_log(
            entries,
            max_positions=int(knobs.max_positions),
            skip_timing_wait=bool(knobs.skip_timing_wait),
            min_conviction=float(knobs.min_conviction),
            sector_cap=float(knobs.sector_cap),
            actual_fund=fund,
        )
        if replay is not None:
            comparison = compare_rebalance_counterfactual_previews(
                output_dir,
                max_positions=int(knobs.max_positions),
                skip_timing_wait=bool(knobs.skip_timing_wait),
                min_conviction=float(knobs.min_conviction),
                sector_cap=float(knobs.sector_cap),
                actual_fund=fund,
            )
            if comparison is not None:
                replay["archive_rebalance_replay"] = comparison.get("archive_preview")
                replay["archive_vs_log"] = comparison.get("comparison")
            return replay

    preview = estimate_counterfactual_preview(fund, knobs=knobs)
    preview["log_entries_replayed"] = len(acted)
    preview["graduates_at_acted_entries"] = MIN_LOG_ACTED_ENTRIES
    return preview


def _mark_prices(fund: PaperFund) -> dict[str, float]:
    prices: dict[str, float] = {}
    if fund.equity_curve:
        last = fund.equity_curve[-1] or {}
        # Prefer last known holding marks from avg_cost when curve lacks per-ticker prices.
        for ticker, pos in fund.holdings.items():
            prices[ticker] = float(pos.avg_cost or 0)
        _ = last  # curve used for span / NAV elsewhere
    for ticker, pos in fund.holdings.items():
        prices.setdefault(ticker, float(pos.avg_cost or 0))
    return prices


def _sector_concentration(fund: PaperFund, prices: dict[str, float]) -> tuple[float, str | None]:
    weights: dict[str, float] = {}
    invested = 0.0
    for ticker, pos in fund.holdings.items():
        price = prices.get(ticker) or pos.avg_cost or 0.0
        value = float(pos.shares) * float(price)
        if value <= 0:
            continue
        sector = str(pos.sector or "Unknown") or "Unknown"
        weights[sector] = weights.get(sector, 0.0) + value
        invested += value
    if invested <= 0:
        return 0.0, None
    dominant = max(weights.items(), key=lambda item: item[1])
    return dominant[1] / invested, dominant[0]


def load_shard_meta(base_dir: Path) -> dict[str, Any] | None:
    """Load shard_meta.json when present (market paper shards)."""
    path = Path(base_dir) / SHARD_META_FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def benchmark_ticker_for_dir(base_dir: Path | None = None, *, output_dir: Path | None = None) -> str:
    """Resolve benchmark ticker from shard meta or default FTSE."""
    for candidate in (base_dir, output_dir, (output_dir.parent if output_dir else None)):
        if not candidate:
            continue
        meta = load_shard_meta(Path(candidate))
        if meta and meta.get("benchmark_ticker"):
            return str(meta["benchmark_ticker"])
    return BENCHMARK_TICKER


def fetch_benchmark_return(
    start: datetime,
    end: datetime,
    *,
    ticker: str | None = None,
) -> float | None:
    """Buy-and-hold benchmark return over the equity-curve span (best effort)."""
    if end <= start:
        return None
    symbol = ticker or BENCHMARK_TICKER
    try:
        import yfinance as yf

        hist = yf.Ticker(symbol).history(
            start=start.date().isoformat(),
            end=(end.date()).isoformat(),
            auto_adjust=True,
        )
        if hist is None or hist.empty or "Close" not in hist.columns:
            return None
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            return None
        start_px = float(closes.iloc[0])
        end_px = float(closes.iloc[-1])
        if start_px <= 0:
            return None
        return (end_px - start_px) / start_px
    except Exception as exc:  # noqa: BLE001
        logger.info("Benchmark fetch skipped: %s", exc)
        return None


def compute_book_metrics(
    fund: PaperFund,
    *,
    benchmark_return: float | None = None,
    fetch_benchmark: bool = True,
    benchmark_ticker: str | None = None,
    knob_epoch: KnobEpoch | None = None,
) -> BookMetrics:
    prices = _mark_prices(fund)
    perf = fund.performance(prices)
    contributed = float(perf["contributed_capital"] or 0.0)
    total_costs = sum(float(t.cost or 0.0) for t in fund.trades)
    cost_drag = (total_costs / contributed) if contributed > 0 else 0.0
    buys = sum(1 for t in fund.trades if t.side == "buy")
    sells = sum(1 for t in fund.trades if t.side == "sell")
    nav = float(perf["portfolio_value"] or 0.0)
    cash_fraction = (float(fund.cash) / nav) if nav > 0 else 1.0
    max_sector_weight, dominant = _sector_concentration(fund, prices)

    bench = benchmark_return
    ticker = benchmark_ticker or BENCHMARK_TICKER
    note = ""
    if bench is None and fetch_benchmark and len(fund.equity_curve) >= 2:
        start_dt = _parse_iso_date(str((fund.equity_curve[0] or {}).get("at") or ""))
        end_dt = _parse_iso_date(str((fund.equity_curve[-1] or {}).get("at") or ""))
        if start_dt and end_dt:
            bench = fetch_benchmark_return(start_dt, end_dt, ticker=ticker)
            if bench is None:
                note = "Benchmark unavailable; excess_after_costs omitted."
        else:
            note = "Equity curve timestamps missing; excess_after_costs omitted."
    elif bench is None:
        note = "Insufficient marks for benchmark span."

    total_return = float(perf["total_return"] or 0.0)
    excess = None if bench is None else total_return - float(bench)

    epoch_metrics = None
    if knob_epoch is not None:
        epoch_metrics = _compute_epoch_metrics(
            fund,
            knob_epoch,
            benchmark_return=benchmark_return,
            fetch_benchmark=fetch_benchmark,
            benchmark_ticker=benchmark_ticker,
        )

    return BookMetrics(
        portfolio_value=nav,
        contributed_capital=contributed,
        total_return=total_return,
        total_costs=total_costs,
        cost_drag=cost_drag,
        trade_count=len(fund.trades),
        buy_count=buys,
        sell_count=sells,
        positions=int(perf["positions"]),
        cash_fraction=cash_fraction,
        equity_marks=len(fund.equity_curve),
        max_sector_weight=max_sector_weight,
        dominant_sector=dominant,
        benchmark_return=bench,
        excess_after_costs=excess,
        note=note,
        epoch=epoch_metrics,
    )


def propose_knob_updates(
    metrics: BookMetrics,
    knobs: LearningKnobs,
) -> tuple[LearningKnobs, dict[str, Any], list[str]]:
    """
    Heuristic, small-step proposals from reviewed book outcomes.

    Rules favour lower churn / higher selectivity when costs dominate, tighter
    sector limits when concentrated, and slightly more breadth only when excess
    is clearly positive with low cost drag.
    """
    proposed = LearningKnobs(
        max_positions=knobs.max_positions,
        skip_timing_wait=knobs.skip_timing_wait,
        min_conviction=knobs.min_conviction,
        sector_cap=knobs.sector_cap,
    )
    reasons: list[str] = []
    changes: dict[str, Any] = {}

    excess = metrics.excess_after_costs
    # 1) Cost drag / churn → raise conviction floor or enable timing skip.
    if metrics.cost_drag >= HIGH_COST_DRAG and metrics.trade_count >= 4:
        if not proposed.skip_timing_wait:
            proposed.skip_timing_wait = True
            changes["skip_timing_wait"] = True
            reasons.append("High cost drag with churn — enable skip_timing_wait.")
        else:
            new_floor = round(
                _clamp(
                    proposed.min_conviction + MIN_CONVICTION_STEP,
                    *MIN_CONVICTION_BOUNDS,
                ),
                4,
            )
            if new_floor > proposed.min_conviction + 1e-9:
                proposed.min_conviction = new_floor
                changes["min_conviction"] = new_floor
                reasons.append(f"High cost drag ({metrics.cost_drag:.1%}) — raise min_conviction.")

    # 2) Weak excess + costs → shrink book slightly.
    if excess is not None and excess <= WEAK_EXCESS and metrics.cost_drag >= HIGH_COST_DRAG / 2:
        new_max = int(_clamp(proposed.max_positions - MAX_POSITIONS_STEP, *MAX_POSITIONS_BOUNDS))
        if new_max < proposed.max_positions:
            proposed.max_positions = new_max
            changes["max_positions"] = new_max
            reasons.append(f"Weak excess after costs ({excess:+.1%}) — reduce max_positions.")

    # 3) Strong excess + tight cash use → allow one more sleeve.
    if (
        excess is not None
        and excess >= STRONG_EXCESS
        and metrics.cost_drag < HIGH_COST_DRAG
        and metrics.cash_fraction < 0.15
        and metrics.positions >= knobs.max_positions
    ):
        new_max = int(_clamp(proposed.max_positions + MAX_POSITIONS_STEP, *MAX_POSITIONS_BOUNDS))
        if new_max > proposed.max_positions:
            proposed.max_positions = new_max
            changes["max_positions"] = new_max
            reasons.append(f"Strong excess after costs ({excess:+.1%}) — raise max_positions.")

    # 4) Sector concentration above current cap → tighten.
    if metrics.max_sector_weight > proposed.sector_cap + 1e-9 and metrics.positions >= 2:
        new_cap = round(
            _clamp(proposed.sector_cap - SECTOR_CAP_STEP, *SECTOR_CAP_BOUNDS),
            4,
        )
        if new_cap < proposed.sector_cap - 1e-9:
            proposed.sector_cap = new_cap
            changes["sector_cap"] = new_cap
            sector = metrics.dominant_sector or "sector"
            reasons.append(
                f"Holdings concentrated in {sector} "
                f"({metrics.max_sector_weight:.0%}) — tighten sector_cap."
            )

    # 5) Idle cash with no excess signal yet — do not loosen aggressively; only
    #    nudge conviction floor down if it was raised previously and drag is low.
    if (
        metrics.cash_fraction >= HIGH_CASH_FRACTION
        and metrics.cost_drag < HIGH_COST_DRAG / 2
        and proposed.min_conviction > MIN_CONVICTION_BOUNDS[0] + 1e-9
        and (excess is None or excess >= 0)
    ):
        new_floor = round(
            _clamp(
                proposed.min_conviction - MIN_CONVICTION_STEP,
                *MIN_CONVICTION_BOUNDS,
            ),
            4,
        )
        if new_floor < proposed.min_conviction - 1e-9:
            proposed.min_conviction = new_floor
            changes["min_conviction"] = new_floor
            reasons.append("Large idle cash with low cost drag — ease min_conviction.")

    if not reasons:
        reasons.append("No knob change warranted from current reviewed outcomes.")

    return proposed, changes, reasons


def enough_history(metrics: BookMetrics) -> bool:
    return metrics.equity_marks >= MIN_EQUITY_MARKS and metrics.trade_count >= MIN_TRADES


def _append_history(path: Path, payload: dict[str, Any]) -> None:
    history: list[dict[str, Any]] = []
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                history = [row for row in raw if isinstance(row, dict)]
        except (json.JSONDecodeError, OSError):
            history = []
    history.append(payload)
    history = history[-HISTORY_KEEP:]
    path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")


def run_decision_review(
    *,
    output_dir: Path = DEFAULT_AUTOMATION_DIR,
    apply: bool = False,
    force: bool = False,
    benchmark_return: float | None = None,
    fetch_benchmark: bool = True,
    benchmark_ticker: str | None = None,
    counterfactual: bool = True,
) -> DecisionReviewResult:
    """
    Review the automated paper book and optionally write clamped knob updates.

    Default is propose-only. When ``apply`` is true and history is thick enough
    (or ``force``), updates ``config.json`` and syncs ``max_positions`` onto the fund.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / CONFIG_FILENAME
    fund_path = output_dir / FUND_FILENAME
    bench_ticker = benchmark_ticker or benchmark_ticker_for_dir(output_dir=output_dir)

    if config_path.exists():
        config = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    else:
        config = AutomationConfig()

    fund = ensure_automated_fund(fund_path, config)
    knobs_before = LearningKnobs.from_config(config)
    knob_epoch = ensure_knob_epoch(output_dir)
    metrics = compute_book_metrics(
        fund,
        benchmark_return=benchmark_return,
        fetch_benchmark=fetch_benchmark,
        benchmark_ticker=bench_ticker,
        knob_epoch=knob_epoch,
    )
    epoch_ok = enough_epoch_history(metrics.epoch)
    history_ok = enough_history(metrics)
    if metrics.epoch and epoch_ok:
        review_metrics = metrics_for_review(metrics)
        review_history_ok = True
    else:
        review_metrics = metrics
        review_history_ok = history_ok
    proposed, changes, reasons = propose_knob_updates(review_metrics, knobs_before)

    reviewed_at = datetime.now(tz=UTC).isoformat()
    applied = False
    note = "Proposal only — history too thin to apply."
    if not review_history_ok and not force:
        knobs_after = knobs_before
    else:
        knobs_after = proposed
        if apply and changes:
            knobs_after.apply_to_config(config)
            config_path.write_text(json.dumps(config.to_dict(), indent=2) + "\n", encoding="utf-8")
            from value_investor.paper_automation import sync_fund_from_automation_config

            sync_fund_from_automation_config(fund, config)
            save_automated_fund(fund_path, fund)
            start_knob_epoch(output_dir, fund, knobs_after, reviewed_at=reviewed_at)
            applied = True
            note = "Applied clamped knob updates from decision review; started new knob epoch."
            metrics = compute_book_metrics(
                fund,
                benchmark_return=benchmark_return,
                fetch_benchmark=fetch_benchmark,
                benchmark_ticker=bench_ticker,
                knob_epoch=load_knob_epoch(output_dir),
            )
        elif apply and not changes:
            note = "Reviewed; no knob changes to apply."
            knobs_after = knobs_before
        elif force and not apply:
            note = "Forced proposal with thin history (not applied)."
        else:
            note = "Proposal ready; re-run with --apply to write config."

    if not review_history_ok:
        reasons = [
            (
                f"Need ≥{MIN_EPOCH_MARKS} epoch marks and ≥{MIN_EPOCH_TRADES} epoch trades "
                f"since last knob apply (or ≥{MIN_EQUITY_MARKS} lifetime marks and "
                f"≥{MIN_TRADES} trades when no epoch yet) — "
                f"epoch marks={((metrics.epoch or {}).get('equity_marks'))}, "
                f"epoch trades={((metrics.epoch or {}).get('trade_count'))}, "
                f"lifetime marks={metrics.equity_marks}, "
                f"lifetime trades={metrics.trade_count}."
            ),
            *reasons,
        ]

    counterfactual_preview = None
    if counterfactual and (changes or force):
        counterfactual_preview = estimate_counterfactual_with_log(
            output_dir,
            fund,
            knobs=proposed if (changes or force) else knobs_after,
        )

    result = DecisionReviewResult(
        reviewed_at=reviewed_at,
        enough_history=review_history_ok,
        applied=applied,
        knobs_before=knobs_before.to_dict(),
        knobs_after=knobs_after.to_dict(),
        proposed_changes=changes if review_history_ok or force else {},
        reasons=reasons,
        metrics=metrics.to_dict(),
        counterfactual_preview=counterfactual_preview,
        note=note,
        track_id=str(config.track_id or "rules"),
        track_label=str(config.track_label or ""),
        is_primary_learning_track=bool(config.is_primary_learning_track),
        success_criterion=(
            f"Outperformance after costs vs market benchmark ({bench_ticker}) on this track; "
            "AI-judgment is the primary learning track, rules is the control."
            if config.is_primary_learning_track
            else (
                "Timing/levels baseline — stock-picking tracks should beat this "
                "after costs; uses trade_plan stops/targets, not conviction rebalance."
                if str(config.track_id or "") == "technical"
                else (
                    "Control track — compare excess_after_costs to the primary AI-judgment "
                    "book; do not treat rules outperformance alone as learning success."
                )
            )
        ),
    )
    payload = result.to_dict()
    (output_dir / REVIEW_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    _append_history(output_dir / REVIEW_HISTORY_FILENAME, payload)
    return result


def format_review_text(result: DecisionReviewResult) -> str:
    m = result.metrics
    lines = [
        "Decision review (paper-auto learning)",
        f"  Track: {result.track_id} ({result.track_label or '—'})"
        f"{' [PRIMARY]' if result.is_primary_learning_track else ' [control]'}",
        f"  Success criterion: {result.success_criterion}",
        f"  Status: {result.note}",
        f"  Enough history: {result.enough_history}",
        f"  Applied: {result.applied}",
        (
            f"  Book return: {m.get('total_return', 0):+.1%} | "
            f"cost drag: {m.get('cost_drag', 0):.1%} | "
            f"trades: {m.get('trade_count', 0)}"
        ),
    ]
    epoch = m.get("epoch") or {}
    if epoch:
        lines.append(
            f"  Epoch since {epoch.get('started_at', '—')}: "
            f"return {epoch.get('total_return', 0):+.1%} | "
            f"cost drag {epoch.get('cost_drag', 0):.1%} | "
            f"trades {epoch.get('trade_count', 0)}"
        )
    excess = m.get("excess_after_costs")
    if excess is not None:
        lines.append(
            f"  Excess after costs vs benchmark: {excess:+.1%} "
            f"(benchmark {m.get('benchmark_return'):+.1%})"
        )
    else:
        lines.append("  Excess after costs vs benchmark: unavailable (need benchmark + marks)")
    epoch_excess = epoch.get("excess_after_costs")
    if epoch and epoch_excess is not None:
        lines.append(
            f"  Epoch excess vs benchmark: {epoch_excess:+.1%} "
            f"(benchmark {epoch.get('benchmark_return'):+.1%})"
        )
    if result.proposed_changes:
        lines.append(f"  Proposed: {result.proposed_changes}")
    preview = result.counterfactual_preview or {}
    if preview:
        scope = preview.get("scope", "lifetime_trade_replay")
        if scope == "rebalance_log_replay":
            lines.append(
                "  Counterfactual (log replay): "
                f"{preview.get('log_entries_replayed', 0)} passes | "
                f"sim return {preview.get('simulated_return', 0):+.1%} | "
                f"actual {preview.get('actual_return_over_window', 0):+.1%} | "
                f"cost drag Δ {preview.get('cost_drag_delta_vs_actual', 0):+.1%}"
            )
            archive_vs_log = preview.get("archive_vs_log") or {}
            if archive_vs_log.get("archive_passes_replayed"):
                lines.append(
                    "  Counterfactual (archive replay): "
                    f"{archive_vs_log.get('archive_passes_replayed', 0)} archive passes | "
                    f"archive Δ {archive_vs_log.get('archive_return_delta_vs_actual', 0):+.1%} "
                    f"vs log Δ {archive_vs_log.get('log_return_delta_vs_actual', 0):+.1%} "
                    f"(gap {archive_vs_log.get('return_delta_gap_archive_minus_log', 0):+.1%})"
                )
        else:
            lines.append(
                "  Counterfactual (lifetime replay): "
                f"blocked {preview.get('blocked_buys', 0)} buys, "
                f"est. cost savings £{preview.get('estimated_cost_savings_gbp', 0):.2f}, "
                f"drag delta {preview.get('cost_drag_delta', 0):+.1%}"
            )
            acted = preview.get("log_entries_replayed")
            need = preview.get("graduates_at_acted_entries")
            if acted is not None and need is not None:
                lines.append(
                    f"  Log replay: {acted}/{need} acted entries "
                    "(full replay unlocks with more weekday passes)."
                )
    for reason in result.reasons[:6]:
        lines.append(f"  - {reason}")
    return "\n".join(lines)


def compare_learning_tracks(
    *,
    base_dir: Path = DEFAULT_AUTOMATION_DIR,
    apply: bool = False,
    force: bool = False,
    fetch_benchmark: bool = True,
    counterfactual: bool = True,
) -> dict[str, Any]:
    """
    Review rules (control) + AI judgment (primary) and summarize outperformance.

    Success for the primary track = excess_after_costs vs ^FTSE (and ideally
    beating the rules control on the same window).
    """
    from value_investor.paper_automation import (
        AI_JUDGMENT_TRACK_ID,
        RULES_TRACK_ID,
        ensure_learning_track_configs,
        learning_track_dirs,
    )

    base_dir = Path(base_dir)
    ensure_learning_track_configs(base_dir)
    dirs = learning_track_dirs(base_dir)
    bench_ticker = benchmark_ticker_for_dir(base_dir)
    reviews: dict[str, Any] = {}
    for track_id, track_dir in dirs.items():
        result = run_decision_review(
            output_dir=track_dir,
            apply=apply,
            force=force,
            fetch_benchmark=fetch_benchmark,
            benchmark_ticker=bench_ticker,
            counterfactual=counterfactual,
        )
        reviews[track_id] = result.to_dict()

    primary = reviews.get(AI_JUDGMENT_TRACK_ID) or {}
    control = reviews.get(RULES_TRACK_ID) or {}
    primary_excess = (primary.get("metrics") or {}).get("excess_after_costs")
    control_excess = (control.get("metrics") or {}).get("excess_after_costs")
    beat_market = primary_excess is not None and primary_excess > 0
    beat_control = (
        primary_excess is not None
        and control_excess is not None
        and primary_excess > control_excess
    )
    summary = {
        "schema_version": 1,
        "primary_learning_track": AI_JUDGMENT_TRACK_ID,
        "success_criterion": (
            f"Primary AI-judgment track outperforms {bench_ticker} after costs; "
            "rules track is the control datum."
        ),
        "benchmark_ticker": bench_ticker,
        "primary_excess_after_costs": primary_excess,
        "control_excess_after_costs": control_excess,
        "beat_market": beat_market,
        "beat_control": beat_control,
        "verdict": (
            "outperforming"
            if beat_market and beat_control
            else (
                "beating_market"
                if beat_market
                else ("underperforming" if primary_excess is not None else "insufficient_data")
            )
        ),
        "reviews": reviews,
    }
    (base_dir / "learning_tracks_review.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    from value_investor.churn_health import write_churn_health

    summary["churn_health"] = write_churn_health(base_dir)
    return summary
