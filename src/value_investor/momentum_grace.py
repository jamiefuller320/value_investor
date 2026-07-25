"""Momentum grace overlay — hold winners after value-screen downgrade while trend holds."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

BUY_SIGNALS = frozenset({"strong_buy", "buy"})
HARD_EXIT_SIGNALS = frozenset({"avoid"})


@dataclass
class MomentumGraceConfig:
    """Tunable grace-period rules for the momentum paper track."""

    grace_weeks: int = 6
    min_unrealized_gain_pct: float = 0.0
    atr_stop_multiplier: float = 2.0
    sma50_stop_haircut: float = 0.97
    take_profit_extension_pct: float = 0.08
    archive_sma200_floor_pct: float = -0.02

    def grace_days(self) -> int:
        return max(1, int(self.grace_weeks) * 7)


@dataclass
class GraceDecision:
    keep: bool
    enter_grace: bool
    exit_grace: bool
    reason: str
    stop_loss: float | None = None
    take_profit: float | None = None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _row_price(row: dict[str, Any]) -> float | None:
    for key in ("price", "last", "close"):
        value = _optional_float(row.get(key))
        if value is not None and value > 0:
            return value
    return None


def _parse_date(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text[:10])


def unrealized_gain_pct(*, mark: float, avg_cost: float) -> float:
    if avg_cost <= 0:
        return 0.0
    return (mark - avg_cost) / avg_cost


def momentum_strength(row: dict[str, Any], *, config: MomentumGraceConfig | None = None) -> tuple[bool, list[str]]:
    """
    True when price trend still looks supportive after a value downgrade.

    Uses full technicals when present (live paper track); falls back to archive
    fields ``timing_signal`` and ``price_vs_sma200_pct`` for historical sims.
    """
    _ = config
    timing = str(row.get("timing_signal") or "insufficient_data")
    if timing == "wait":
        return False, ["timing=wait"]
    if timing == "insufficient_data":
        return False, ["insufficient timing data"]

    price = _row_price(row)
    sma50 = _optional_float(row.get("sma_50"))
    sma200 = _optional_float(row.get("sma_200"))
    reasons: list[str] = []

    if price is not None and sma50 is not None:
        if price < sma50:
            return False, ["price below 50-day MA"]
        reasons.append("above 50-day MA")
        if sma200 is not None and price > sma50 > sma200:
            reasons.append("uptrend (price > 50 > 200 MA)")
    else:
        vs200 = _optional_float(row.get("price_vs_sma200_pct"))
        if vs200 is not None:
            floor = (config or MomentumGraceConfig()).archive_sma200_floor_pct
            if vs200 < floor:
                return False, [f"price_vs_sma200_pct {vs200:+.1%} below floor"]
            reasons.append("near/above 200-day MA (archive proxy)")
        elif timing not in {"accumulate", "neutral"}:
            return False, ["no MA data and timing not supportive"]

    macd = _optional_float(row.get("macd_histogram"))
    macd_prev = _optional_float(row.get("macd_histogram_prev"))
    if macd is not None and macd_prev is not None:
        if macd > macd_prev or macd > 0:
            reasons.append("MACD momentum firm")
        else:
            return False, ["MACD weakening"]
    elif timing == "accumulate":
        reasons.append("favourable timing")

    return bool(reasons), reasons or ["momentum supportive"]


def momentum_broken(row: dict[str, Any], *, config: MomentumGraceConfig | None = None) -> tuple[bool, str]:
    cfg = config or MomentumGraceConfig()
    timing = str(row.get("timing_signal") or "")
    if timing == "wait":
        return True, "timing weakened to wait"

    price = _row_price(row)
    sma50 = _optional_float(row.get("sma_50"))
    if price is not None and sma50 is not None and price < sma50:
        return True, "price fell below 50-day MA"

    vs200 = _optional_float(row.get("price_vs_sma200_pct"))
    if vs200 is not None and vs200 < cfg.archive_sma200_floor_pct - 0.03:
        return True, "price materially below 200-day MA"

    macd = _optional_float(row.get("macd_histogram"))
    macd_prev = _optional_float(row.get("macd_histogram_prev"))
    if macd is not None and macd_prev is not None and macd < macd_prev and macd < 0:
        return True, "MACD turned down below zero"

    return False, ""


def compute_grace_levels(
    row: dict[str, Any],
    *,
    avg_cost: float,
    current_stop: float | None,
    current_take_profit: float | None,
    entry_stop_floor: float | None,
    config: MomentumGraceConfig | None = None,
) -> tuple[float | None, float | None]:
    """
    Trailing stop (never below entry floor) and stretched take-profit for grace mode.
    """
    cfg = config or MomentumGraceConfig()
    price = _row_price(row)
    if price is None or price <= 0:
        return current_stop, current_take_profit

    floor = entry_stop_floor or current_stop or avg_cost
    stops = [floor, avg_cost]
    if current_stop is not None:
        stops.append(current_stop)

    sma50 = _optional_float(row.get("sma_50"))
    if sma50 is not None and sma50 > 0:
        stops.append(sma50 * cfg.sma50_stop_haircut)

    atr = _optional_float(row.get("atr_14"))
    if atr is not None and atr > 0:
        stops.append(price - cfg.atr_stop_multiplier * atr)

    support = _optional_float((row.get("trade_plan") or {}).get("tactical_stop_loss"))
    if support is not None:
        stops.append(support)

    stop = max(s for s in stops if s is not None and s > 0)
    stop = min(stop, price * 0.999)

    targets = [price * (1 + cfg.take_profit_extension_pct)]
    if current_take_profit is not None:
        targets.append(current_take_profit)
    plan_tp = _optional_float((row.get("trade_plan") or {}).get("tactical_take_profit"))
    if plan_tp is not None:
        targets.append(plan_tp)
    if sma50 is not None and price > sma50:
        targets.append(price * 1.05)

    take_profit = max(targets)
    return round(stop, 2), round(take_profit, 2)


def grace_expired(grace_started_at: str | None, *, as_of: str | date | datetime, config: MomentumGraceConfig | None = None) -> bool:
    started = _parse_date(grace_started_at)
    current = _parse_date(as_of)
    if started is None or current is None:
        return False
    cfg = config or MomentumGraceConfig()
    return current >= started + timedelta(days=cfg.grace_days())


def evaluate_grace_holding(
    row: dict[str, Any],
    *,
    signal: str,
    avg_cost: float,
    mark: float | None,
    momentum_grace: bool,
    grace_started_at: str | None,
    stop_loss: float | None,
    take_profit: float | None,
    grace_entry_stop: float | None,
    as_of: str | date | datetime,
    config: MomentumGraceConfig | None = None,
) -> GraceDecision:
    """Decide whether to keep, enter, or exit momentum grace for one holding."""
    cfg = config or MomentumGraceConfig()
    signal = str(signal or "hold")

    if signal in HARD_EXIT_SIGNALS:
        return GraceDecision(
            keep=False,
            enter_grace=False,
            exit_grace=momentum_grace,
            reason="screen signal avoid — hard exit",
        )

    if mark is not None and stop_loss is not None and mark <= stop_loss:
        return GraceDecision(
            keep=False,
            enter_grace=False,
            exit_grace=momentum_grace,
            reason=f"stop hit ({mark:.2f} ≤ {stop_loss:.2f})",
        )
    if mark is not None and take_profit is not None and mark >= take_profit:
        return GraceDecision(
            keep=False,
            enter_grace=False,
            exit_grace=momentum_grace,
            reason=f"take-profit hit ({mark:.2f} ≥ {take_profit:.2f})",
        )

    if signal in BUY_SIGNALS:
        return GraceDecision(
            keep=True,
            enter_grace=False,
            exit_grace=momentum_grace,
            reason="still buy-tier",
        )

    if momentum_grace:
        if grace_expired(grace_started_at, as_of=as_of, config=cfg):
            return GraceDecision(
                keep=False,
                enter_grace=False,
                exit_grace=True,
                reason=f"grace period expired ({cfg.grace_weeks} weeks)",
            )
        broken, why = momentum_broken(row, config=cfg)
        if broken:
            return GraceDecision(
                keep=False,
                enter_grace=False,
                exit_grace=True,
                reason=why,
            )
        stop, target = compute_grace_levels(
            row,
            avg_cost=avg_cost,
            current_stop=stop_loss,
            current_take_profit=take_profit,
            entry_stop_floor=grace_entry_stop,
            config=cfg,
        )
        return GraceDecision(
            keep=True,
            enter_grace=False,
            exit_grace=False,
            reason="momentum grace active — trend intact",
            stop_loss=stop,
            take_profit=target,
        )

    if mark is None:
        return GraceDecision(
            keep=False,
            enter_grace=False,
            exit_grace=False,
            reason="no mark — exit",
        )

    gain = unrealized_gain_pct(mark=mark, avg_cost=avg_cost)
    if gain < cfg.min_unrealized_gain_pct:
        return GraceDecision(
            keep=False,
            enter_grace=False,
            exit_grace=False,
            reason="no unrealized gain for grace entry",
        )

    strong, reasons = momentum_strength(row, config=cfg)
    if not strong:
        return GraceDecision(
            keep=False,
            enter_grace=False,
            exit_grace=False,
            reason="momentum not strong enough for grace entry",
        )

    entry_floor = max(
        s
        for s in [grace_entry_stop, stop_loss, avg_cost]
        if s is not None and s > 0
    ) if any(s is not None and s > 0 for s in [grace_entry_stop, stop_loss, avg_cost]) else avg_cost
    stop, target = compute_grace_levels(
        row,
        avg_cost=avg_cost,
        current_stop=stop_loss,
        current_take_profit=take_profit,
        entry_stop_floor=entry_floor,
        config=cfg,
    )
    summary = "; ".join(reasons)
    return GraceDecision(
        keep=True,
        enter_grace=True,
        exit_grace=False,
        reason=f"enter momentum grace — {summary}",
        stop_loss=stop,
        take_profit=target,
    )


@dataclass
class SimGraceState:
    """Per-ticker grace metadata for the historical simulator."""

    active: bool = False
    started_at: str = ""
    entry_stop: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    avg_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "started_at": self.started_at,
            "entry_stop": self.entry_stop,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "avg_cost": self.avg_cost,
        }
