"""Exit-policy counterfactual replay for index stress archive sim."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from value_investor.backtest import RunSnapshot
from value_investor.momentum_grace import MomentumGraceConfig, evaluate_grace_holding
from value_investor.paper_fund import DEFAULT_EXIT_CONFIRM_SCREENS, select_automated_targets


@dataclass
class ExitPolicyReplayConfig:
    exit_confirm_screens: int = DEFAULT_EXIT_CONFIRM_SCREENS
    use_momentum_grace: bool = True
    max_positions: int = 3
    min_conviction: float = 0.0
    sector_cap: float = 1.0
    grace_config: MomentumGraceConfig = field(default_factory=MomentumGraceConfig)


@dataclass
class _SimHolding:
    ticker: str
    name: str
    avg_cost: float
    stop_loss: float | None = None
    take_profit: float | None = None
    momentum_grace: bool = False
    grace_started_at: str | None = None
    grace_entry_stop: float | None = None
    exit_streak: int = 0


def _effective_signal(row: dict[str, Any]) -> str:
    adjusted = str(row.get("adjusted_signal") or "").strip()
    if adjusted:
        return adjusted
    return str(row.get("signal") or "")


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


def _row_for_ticker(snapshot: RunSnapshot, ticker: str) -> dict[str, Any] | None:
    for row in snapshot.signals:
        if str(row.get("ticker")) == ticker:
            merged = dict(row)
            price = snapshot.prices.get(ticker)
            if price is not None:
                merged["price"] = float(price)
            return merged
    return None


def _candidate_rows(snapshot: RunSnapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in snapshot.signals:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        merged = dict(row)
        price = snapshot.prices.get(ticker)
        if price is not None:
            merged["price"] = float(price)
        rows.append(merged)
    return rows


def _tactical_stop(row: dict[str, Any]) -> float | None:
    stop = _optional_float(row.get("tactical_stop_loss"))
    if stop is None:
        stop = _optional_float((row.get("trade_plan") or {}).get("tactical_stop_loss"))
    return stop


def _tactical_take_profit(row: dict[str, Any]) -> float | None:
    target = _optional_float(row.get("tactical_take_profit"))
    if target is None:
        target = _optional_float((row.get("trade_plan") or {}).get("tactical_take_profit"))
    return target


def _tactical_stop_hit(holding: _SimHolding, row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    mark = _optional_float(row.get("price"))
    stop = holding.stop_loss if holding.stop_loss is not None else _tactical_stop(row)
    if mark is None or stop is None or mark > stop:
        return None
    return {
        "ticker": holding.ticker,
        "kind": "tactical_stop",
        "stop_loss": stop,
        "mark": mark,
    }


def _seed_holdings(first: RunSnapshot, *, policy: ExitPolicyReplayConfig) -> dict[str, _SimHolding]:
    targets = select_automated_targets(
        _candidate_rows(first),
        max_positions=policy.max_positions,
        min_conviction=policy.min_conviction,
        sector_cap=policy.sector_cap,
    )
    holdings: dict[str, _SimHolding] = {}
    for row in targets:
        ticker = str(row["ticker"])
        price = _optional_float(row.get("price")) or 1.0
        holdings[ticker] = _SimHolding(
            ticker=ticker,
            name=str(row.get("name") or ticker),
            avg_cost=price,
            stop_loss=_tactical_stop(row),
            take_profit=_tactical_take_profit(row),
        )
    return holdings


def replay_exit_policy_counterfactual(
    snapshots: list[RunSnapshot],
    *,
    stress_by_window: list[bool],
    policy: ExitPolicyReplayConfig | None = None,
) -> dict[str, Any]:
    """
    Walk archived snapshots with tactical stops, exit_confirm_screens buffer,
    and optional momentum grace — compare mechanical exits on stress vs normal weeks.
    """
    policy = policy or ExitPolicyReplayConfig()
    if len(snapshots) < 2:
        return {
            "windows": 0,
            "tactical_stop_hits": 0,
            "rotation_exits": 0,
            "grace_exits": 0,
            "buffer_holds": 0,
            "stress_mechanical_exits": 0,
            "counterfactual_exits_avoided": 0,
            "episodes": [],
        }

    holdings = _seed_holdings(snapshots[0], policy=policy)
    episodes: list[dict[str, Any]] = []

    totals = {
        "tactical_stop_hits": 0,
        "rotation_exits": 0,
        "grace_exits": 0,
        "buffer_holds": 0,
        "stress_mechanical_exits": 0,
    }

    for idx, end in enumerate(snapshots[1:], start=1):
        start = snapshots[idx - 1]
        stressed = stress_by_window[idx - 1] if idx - 1 < len(stress_by_window) else False
        candidates = _candidate_rows(end)
        targets = select_automated_targets(
            candidates,
            max_positions=policy.max_positions,
            min_conviction=policy.min_conviction,
            sector_cap=policy.sector_cap,
        )
        target_tickers = {str(row["ticker"]) for row in targets}

        window_events: list[dict[str, Any]] = []
        grace_kept: set[str] = set()

        # Tactical stops and grace evaluation on existing holdings.
        for ticker in list(holdings):
            holding = holdings[ticker]
            row = _row_for_ticker(end, ticker)
            mark = _optional_float((row or {}).get("price"))

            stop_hit = _tactical_stop_hit(holding, row)
            if stop_hit is not None:
                window_events.append({**stop_hit, "stressed_window": stressed})
                totals["tactical_stop_hits"] += 1
                if stressed:
                    totals["stress_mechanical_exits"] += 1
                if not stressed:
                    del holdings[ticker]
                continue

            if policy.use_momentum_grace and row is not None and mark is not None:
                signal = _effective_signal(row)
                decision = evaluate_grace_holding(
                    row,
                    signal=signal,
                    avg_cost=holding.avg_cost,
                    mark=mark,
                    momentum_grace=holding.momentum_grace,
                    grace_started_at=holding.grace_started_at,
                    stop_loss=holding.stop_loss,
                    take_profit=holding.take_profit,
                    grace_entry_stop=holding.grace_entry_stop,
                    as_of=end.run_at,
                    config=policy.grace_config,
                )
                if decision.keep:
                    grace_kept.add(ticker)
                    if decision.enter_grace:
                        holding.momentum_grace = True
                        holding.grace_started_at = end.run_at
                        holding.grace_entry_stop = (
                            decision.stop_loss or holding.stop_loss or holding.avg_cost
                        )
                    if decision.stop_loss is not None:
                        holding.stop_loss = decision.stop_loss
                    if decision.take_profit is not None:
                        holding.take_profit = decision.take_profit
                    if decision.enter_grace or holding.momentum_grace:
                        window_events.append(
                            {
                                "ticker": ticker,
                                "kind": "grace_hold",
                                "reason": decision.reason,
                                "stressed_window": stressed,
                            }
                        )
                    continue

                if decision.exit_grace and holding.momentum_grace:
                    window_events.append(
                        {
                            "ticker": ticker,
                            "kind": "grace_exit",
                            "reason": decision.reason,
                            "stressed_window": stressed,
                        }
                    )
                    totals["grace_exits"] += 1
                    if stressed:
                        totals["stress_mechanical_exits"] += 1
                    if not stressed:
                        del holdings[ticker]
                    continue

        # Screen rotation with exit_confirm_screens buffer.
        for ticker in list(holdings):
            if ticker in target_tickers or ticker in grace_kept:
                holdings[ticker].exit_streak = 0
                continue
            holding = holdings[ticker]
            holding.exit_streak += 1
            if holding.exit_streak < policy.exit_confirm_screens:
                totals["buffer_holds"] += 1
                window_events.append(
                    {
                        "ticker": ticker,
                        "kind": "buffer_hold",
                        "exit_streak": holding.exit_streak,
                        "exit_confirm_screens": policy.exit_confirm_screens,
                        "stressed_window": stressed,
                    }
                )
                continue

            window_events.append(
                {
                    "ticker": ticker,
                    "kind": "rotation_exit",
                    "exit_streak": holding.exit_streak,
                    "stressed_window": stressed,
                }
            )
            totals["rotation_exits"] += 1
            if stressed:
                totals["stress_mechanical_exits"] += 1
            if not stressed:
                del holdings[ticker]

        # Fill empty sleeves from targets (simplified — no cash model).
        for row in targets:
            ticker = str(row["ticker"])
            if ticker in holdings:
                continue
            if len(holdings) >= policy.max_positions:
                break
            price = _optional_float(row.get("price")) or 1.0
            holdings[ticker] = _SimHolding(
                ticker=ticker,
                name=str(row.get("name") or ticker),
                avg_cost=price,
                stop_loss=_tactical_stop(row),
                take_profit=_tactical_take_profit(row),
            )
            window_events.append({"ticker": ticker, "kind": "enter", "stressed_window": stressed})

        episodes.append(
            {
                "window_start": start.run_at,
                "window_end": end.run_at,
                "stressed": stressed,
                "events": window_events,
                "holding_count": len(holdings),
            }
        )

    mechanical_total = (
        totals["tactical_stop_hits"] + totals["rotation_exits"] + totals["grace_exits"]
    )
    return {
        "windows": len(episodes),
        "policy": {
            "exit_confirm_screens": policy.exit_confirm_screens,
            "use_momentum_grace": policy.use_momentum_grace,
            "max_positions": policy.max_positions,
        },
        **totals,
        "mechanical_exits_total": mechanical_total,
        "counterfactual_exits_avoided": totals["stress_mechanical_exits"],
        "episodes": episodes,
    }


__all__ = [
    "ExitPolicyReplayConfig",
    "replay_exit_policy_counterfactual",
]
