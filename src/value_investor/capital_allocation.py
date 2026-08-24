"""Graduated capital allocation — entry/exit appetite scoring for paper tracks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

BUY_SIGNALS = frozenset({"strong_buy", "buy"})


@dataclass
class CapitalAllocationConfig:
    """Tunable thresholds for graduated entry, harvest skims, and swap gating."""

    skim_urgency_threshold: float = 0.55
    harvest_gain_pct_floor: float = 0.15
    default_starter_fraction: float = 0.5
    min_entry_fraction: float = 0.35
    max_entry_fraction: float = 0.85
    swap_cost_multiplier: float = 2.0
    max_skim_fraction: float = 0.4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CapitalAllocationConfig:
        raw = data or {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})


DEFAULT_CAPITAL_ALLOCATION_CONFIG = CapitalAllocationConfig()


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
    for key in ("price", "last", "close", "mark"):
        value = _optional_float(row.get(key))
        if value is not None and value > 0:
            return value
    plan = row.get("trade_plan") or {}
    for key in ("core_limit", "tactical_limit"):
        value = _optional_float(plan.get(key))
        if value is not None and value > 0:
            return value
    return None


def _screen_signal(
    row: dict[str, Any],
    *,
    use_adjusted_signal: bool = False,
) -> str:
    signal = str(row.get("signal") or "")
    if use_adjusted_signal:
        adjusted = row.get("adjusted_signal")
        if adjusted is not None and str(adjusted).strip():
            return str(adjusted)
    return signal


def unrealized_gain_pct(*, mark: float, avg_cost: float) -> float:
    if avg_cost <= 0:
        return 0.0
    return (mark - avg_cost) / avg_cost


def entry_appetite(
    row: dict[str, Any],
    *,
    use_adjusted_signal: bool = False,
) -> float:
    """
    Score 0–1 for how aggressively to add to a name this rebalance.

    Higher when value + timing align; lower when timing says wait.
    """
    signal = _screen_signal(row, use_adjusted_signal=use_adjusted_signal)
    if signal not in BUY_SIGNALS:
        return 0.0

    timing = str(row.get("timing_signal") or "insufficient_data")
    timing_base = {
        "accumulate": 0.85,
        "neutral": 0.65,
        "wait": 0.35,
        "insufficient_data": 0.25,
    }.get(timing, 0.4)

    score = timing_base
    conviction = float(row.get("conviction_score") or 0)
    if conviction >= 0.7:
        score += 0.08
    elif conviction >= 0.5:
        score += 0.04
    if signal == "strong_buy":
        score += 0.05
    return max(0.0, min(1.0, score))


def exit_urgency(
    *,
    row: dict[str, Any] | None,
    mark: float | None,
    avg_cost: float,
    in_target_set: bool,
    exit_streak: int = 0,
    momentum_grace: bool = False,
    use_adjusted_signal: bool = False,
) -> float:
    """
    Score 0–1 for how urgently to reduce or exit a holding.

  Harvest (still in target) vs rotation (left target) use the same scale.
    """
    score = 0.0
    signal = _screen_signal(row or {}, use_adjusted_signal=use_adjusted_signal)

    if signal not in BUY_SIGNALS:
        score += 0.35
        score += min(0.25, 0.08 * max(0, exit_streak))

    timing = str((row or {}).get("timing_signal") or "")
    if timing == "wait":
        score += 0.2

    if mark is not None and avg_cost > 0:
        gain = unrealized_gain_pct(mark=mark, avg_cost=avg_cost)
        if gain >= 0.3:
            score += 0.2
        elif gain >= 0.15:
            score += 0.1
        elif gain <= -0.1:
            score += 0.12

        plan = (row or {}).get("trade_plan") or {}
        take_profit = _optional_float(plan.get("tactical_take_profit"))
        if take_profit is not None and mark >= take_profit * 0.98:
            score += 0.25

    if momentum_grace:
        score = max(0.0, score - 0.2)

    if in_target_set and signal in BUY_SIGNALS and timing != "wait":
        score = min(score, 0.45)

    return max(0.0, min(1.0, score))


def entry_sleeve_fraction(
    row: dict[str, Any],
    *,
    config: CapitalAllocationConfig | None = None,
    use_adjusted_signal: bool = False,
) -> float:
    """Fraction of equal-weight target sleeve to deploy on entry/top-up."""
    cfg = config or DEFAULT_CAPITAL_ALLOCATION_CONFIG
    plan = row.get("trade_plan") or {}
    core_pct = _optional_float(plan.get("core_allocation_pct"))
    if core_pct is not None and 0 < core_pct <= 1:
        return max(cfg.min_entry_fraction, min(cfg.max_entry_fraction, core_pct))

    appetite = entry_appetite(row, use_adjusted_signal=use_adjusted_signal)
    if appetite <= 0:
        return 0.0
    span = cfg.max_entry_fraction - cfg.min_entry_fraction
    return cfg.min_entry_fraction + span * appetite


def skim_fraction(
    urgency: float,
    *,
    config: CapitalAllocationConfig | None = None,
) -> float:
    """Portion of excess above target to trim when harvesting."""
    cfg = config or DEFAULT_CAPITAL_ALLOCATION_CONFIG
    if urgency < cfg.skim_urgency_threshold:
        return 0.0
    raw = (urgency - cfg.skim_urgency_threshold) / max(1e-9, 1.0 - cfg.skim_urgency_threshold)
    return min(cfg.max_skim_fraction, max(0.15, raw * cfg.max_skim_fraction))


def swap_score(
    *,
    exit_urgency_value: float,
    entry_appetite_value: float,
    trade_cost_pct: float,
    config: CapitalAllocationConfig | None = None,
) -> float:
    """
    Positive when rotating capital from exit candidate to entry candidate
    likely beats holding after costs.
    """
    cfg = config or DEFAULT_CAPITAL_ALLOCATION_CONFIG
    cost_penalty = float(trade_cost_pct) * cfg.swap_cost_multiplier
    return entry_appetite_value - exit_urgency_value - cost_penalty


def classify_lifecycle_phase(
    *,
    held: bool,
    in_target_set: bool,
    current_value: float,
    target_value: float,
    exit_streak: int,
    momentum_grace: bool,
    row: dict[str, Any] | None,
    use_adjusted_signal: bool = False,
) -> str:
    """Human-readable lifecycle label for logs and cohort analysis."""
    if not held:
        appetite = entry_appetite(row or {}, use_adjusted_signal=use_adjusted_signal)
        if appetite >= 0.75:
            return "prospect_ready"
        if appetite > 0:
            return "prospect_waitlist"
        return "prospect_ineligible"

    if momentum_grace:
        return "grace"

    if not in_target_set:
        if exit_streak > 0:
            return "exit_buffer"
        return "exit_pending"

    if target_value <= 0:
        return "hold"

    ratio = current_value / target_value if target_value > 0 else 0.0
    if ratio < 0.85:
        return "build"
    if ratio > 1.08:
        signal = _screen_signal(row or {}, use_adjusted_signal=use_adjusted_signal)
        timing = str((row or {}).get("timing_signal") or "")
        if timing == "wait" or signal not in BUY_SIGNALS:
            return "harvest"
        return "full"
    return "full"


def score_rebalance_candidates(
    *,
    targets: list[dict[str, Any]],
    holdings: dict[str, Any],
    price_map: dict[str, float],
    target_each: float,
    target_tickers: set[str],
    exit_streaks: dict[str, int],
    use_adjusted_signal: bool = False,
    config: CapitalAllocationConfig | None = None,
) -> dict[str, Any]:
    """Build a diagnostic snapshot for rebalance logs and director payload."""
    cfg = config or DEFAULT_CAPITAL_ALLOCATION_CONFIG
    entries: list[dict[str, Any]] = []
    for row in targets:
        ticker = str(row["ticker"])
        price = price_map.get(ticker) or _row_price(row) or 0.0
        position = holdings.get(ticker)
        current_value = (position.shares * price) if position and price else 0.0
        appetite = entry_appetite(row, use_adjusted_signal=use_adjusted_signal)
        fraction = entry_sleeve_fraction(
            row, config=cfg, use_adjusted_signal=use_adjusted_signal
        )
        entries.append(
            {
                "ticker": ticker,
                "entry_appetite": round(appetite, 4),
                "entry_sleeve_fraction": round(fraction, 4),
                "target_value": round(target_each * fraction, 2),
                "lifecycle": classify_lifecycle_phase(
                    held=position is not None,
                    in_target_set=True,
                    current_value=current_value,
                    target_value=target_each,
                    exit_streak=0,
                    momentum_grace=bool(getattr(position, "momentum_grace", False)),
                    row=row,
                    use_adjusted_signal=use_adjusted_signal,
                ),
            }
        )

    exits: list[dict[str, Any]] = []
    for ticker, position in holdings.items():
        row = next((r for r in targets if str(r.get("ticker")) == ticker), None)
        price = price_map.get(ticker) or float(position.avg_cost or 0)
        mark = price if price > 0 else None
        in_target = ticker in target_tickers
        streak = int(exit_streaks.get(ticker, 0))
        urgency = exit_urgency(
            row=row,
            mark=mark,
            avg_cost=float(position.avg_cost or 0),
            in_target_set=in_target,
            exit_streak=streak,
            momentum_grace=bool(position.momentum_grace),
            use_adjusted_signal=use_adjusted_signal,
        )
        current_value = (position.shares * price) if price else 0.0
        exits.append(
            {
                "ticker": ticker,
                "exit_urgency": round(urgency, 4),
                "skim_fraction": round(skim_fraction(urgency, config=cfg), 4),
                "lifecycle": classify_lifecycle_phase(
                    held=True,
                    in_target_set=in_target,
                    current_value=current_value,
                    target_value=target_each,
                    exit_streak=streak,
                    momentum_grace=bool(position.momentum_grace),
                    row=row,
                    use_adjusted_signal=use_adjusted_signal,
                ),
            }
        )

    return {
        "config": cfg.to_dict(),
        "entries": entries,
        "exits": exits,
    }
