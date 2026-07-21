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

MIN_EQUITY_MARKS = 4
MIN_TRADES = 2

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

    def to_dict(self) -> dict[str, Any]:
        return {
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
                None
                if self.excess_after_costs is None
                else round(self.excess_after_costs, 4)
            ),
            "note": self.note,
        }


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
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def fetch_benchmark_return(start: datetime, end: datetime) -> float | None:
    """FTSE 100 buy-and-hold over the equity-curve span (best effort)."""
    if end <= start:
        return None
    try:
        import yfinance as yf

        from value_investor.backtest import BENCHMARK_TICKER

        hist = yf.Ticker(BENCHMARK_TICKER).history(
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
    note = ""
    if bench is None and fetch_benchmark and len(fund.equity_curve) >= 2:
        start_dt = _parse_iso_date(str((fund.equity_curve[0] or {}).get("at") or ""))
        end_dt = _parse_iso_date(str((fund.equity_curve[-1] or {}).get("at") or ""))
        if start_dt and end_dt:
            bench = fetch_benchmark_return(start_dt, end_dt)
            if bench is None:
                note = "Benchmark unavailable; excess_after_costs omitted."
        else:
            note = "Equity curve timestamps missing; excess_after_costs omitted."
    elif bench is None:
        note = "Insufficient marks for benchmark span."

    total_return = float(perf["total_return"] or 0.0)
    excess = None if bench is None else total_return - float(bench)

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
                reasons.append(
                    f"High cost drag ({metrics.cost_drag:.1%}) — raise min_conviction."
                )

    # 2) Weak excess + costs → shrink book slightly.
    if (
        excess is not None
        and excess <= WEAK_EXCESS
        and metrics.cost_drag >= HIGH_COST_DRAG / 2
    ):
        new_max = int(
            _clamp(proposed.max_positions - MAX_POSITIONS_STEP, *MAX_POSITIONS_BOUNDS)
        )
        if new_max < proposed.max_positions:
            proposed.max_positions = new_max
            changes["max_positions"] = new_max
            reasons.append(
                f"Weak excess after costs ({excess:+.1%}) — reduce max_positions."
            )

    # 3) Strong excess + tight cash use → allow one more sleeve.
    if (
        excess is not None
        and excess >= STRONG_EXCESS
        and metrics.cost_drag < HIGH_COST_DRAG
        and metrics.cash_fraction < 0.15
        and metrics.positions >= knobs.max_positions
    ):
        new_max = int(
            _clamp(proposed.max_positions + MAX_POSITIONS_STEP, *MAX_POSITIONS_BOUNDS)
        )
        if new_max > proposed.max_positions:
            proposed.max_positions = new_max
            changes["max_positions"] = new_max
            reasons.append(
                f"Strong excess after costs ({excess:+.1%}) — raise max_positions."
            )

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

    if config_path.exists():
        config = AutomationConfig.from_dict(
            json.loads(config_path.read_text(encoding="utf-8"))
        )
    else:
        config = AutomationConfig()

    fund = ensure_automated_fund(fund_path, config)
    knobs_before = LearningKnobs.from_config(config)
    metrics = compute_book_metrics(
        fund,
        benchmark_return=benchmark_return,
        fetch_benchmark=fetch_benchmark,
    )
    history_ok = enough_history(metrics)
    proposed, changes, reasons = propose_knob_updates(metrics, knobs_before)

    applied = False
    note = "Proposal only — history too thin to apply."
    if not history_ok and not force:
        knobs_after = knobs_before
    else:
        knobs_after = proposed
        if apply and changes:
            knobs_after.apply_to_config(config)
            config_path.write_text(
                json.dumps(config.to_dict(), indent=2) + "\n", encoding="utf-8"
            )
            from value_investor.paper_automation import sync_fund_from_automation_config

            sync_fund_from_automation_config(fund, config)
            save_automated_fund(fund_path, fund)
            applied = True
            note = "Applied clamped knob updates from decision review."
        elif apply and not changes:
            note = "Reviewed; no knob changes to apply."
            knobs_after = knobs_before
        elif force and not apply:
            note = "Forced proposal with thin history (not applied)."
        else:
            note = "Proposal ready; re-run with --apply to write config."

    if not history_ok:
        reasons = [
            (
                f"Need ≥{MIN_EQUITY_MARKS} equity marks and ≥{MIN_TRADES} trades "
                f"(have {metrics.equity_marks} marks, {metrics.trade_count} trades)."
            ),
            *reasons,
        ]

    result = DecisionReviewResult(
        reviewed_at=datetime.now(tz=UTC).isoformat(),
        enough_history=history_ok,
        applied=applied,
        knobs_before=knobs_before.to_dict(),
        knobs_after=knobs_after.to_dict(),
        proposed_changes=changes if history_ok or force else {},
        reasons=reasons,
        metrics=metrics.to_dict(),
        note=note,
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
        f"  Status: {result.note}",
        f"  Enough history: {result.enough_history}",
        f"  Applied: {result.applied}",
        (
            f"  Book return: {m.get('total_return', 0):+.1%} | "
            f"cost drag: {m.get('cost_drag', 0):.1%} | "
            f"trades: {m.get('trade_count', 0)}"
        ),
    ]
    excess = m.get("excess_after_costs")
    if excess is not None:
        lines.append(
            f"  Excess after costs vs FTSE: {excess:+.1%} "
            f"(benchmark {m.get('benchmark_return'):+.1%})"
        )
    if result.proposed_changes:
        lines.append(f"  Proposed: {result.proposed_changes}")
    for reason in result.reasons[:6]:
        lines.append(f"  - {reason}")
    return "\n".join(lines)
