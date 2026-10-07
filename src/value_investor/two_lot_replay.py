"""Two-lot retention replay on the wide buy-tier book (observe-only).

Learning question: after fair costs, does keeping a core lot and recycling only
a tactical slice beat selling the whole position when a name leaves the buy tier?

The live ``buy_tier_level`` book holds one lot per name and sells all of it
after ``exit_confirm_screens`` outside the target set. This replay does not
change that book, its knobs, or any fill. It walks the logged passes with the
same prices and scores three retention rules against a full-exit baseline
inside one engine:

- ``core_kept`` — about 65% of each new stake is a core lot that is not sold
  on rank, target, or stop. The rest is tactical.
- ``harvest_skim`` — the first time a lot is up 15%, sell half the gain and
  keep the remaining shares through later rank exits.
- ``profit_residual`` — the first time a lot is up 15%, sell shares worth the
  cost basis and keep only the profit as the core.
- ``core_thesis_exit`` — the same split as ``core_kept``. The core is sold
  only after a persisted thesis break (hard avoid, or a research verdict that
  the business case is gone). Rank, cheapness, and price do not sell it.

Tactical cash is not put back into the same name on the same pass. A target or
stop sale reopens the tactical sleeve only after a later pass trades at or
below 95% of the sale price, or when the name leaves the buy tier and returns.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.core_sell_trigger import (
    core_sell_reason,
    note_thesis_streak,
    thesis_break_confirmed,
)

DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
DEFAULT_STORE_PATH = Path("docs/data/two_lot_replay.json")
TRACK_ID = "buy_tier_level"
FUND_FILENAME = "automated_fund.json"

CORE_PCT = 0.65
GAIN_FLOOR = 0.15
HARVEST_SKIM_OF_PROFIT = 0.5
TARGET_ABOVE_FILL = 1.10
STOP_BELOW_FILL = 0.92
DIP_REOPEN = 0.95
EDGE_MIN = 0.01
FIDELITY_TOLERANCE = 0.02
MIN_PASSES = 8
BUY_SIGNALS = frozenset({"buy", "strong_buy"})
RETENTION_POLICIES = ("full_exit", "core_kept", "harvest_skim", "profit_residual")
POLICIES = (*RETENTION_POLICIES, "core_thesis_exit")

LEARNING_QUESTION = (
    "On the wide fair-cost buy-tier book, after costs, does keeping a core lot "
    "and recycling only a tactical slice beat selling the whole position when it "
    "leaves the buy tier?"
)
FINDING_TITLE = "Two-lot retention beats full exit in replay"
CORE_SELL_FINDING_TITLE = "Core thesis exit changes the kept-core replay"
STORE_FAILED_TITLE = "Two-lot replay observe failed"


def _load_acted(track_dir: Path) -> list[dict[str, Any]]:
    path = track_dir / "rebalance_log.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    rows = [row for row in payload if isinstance(row, dict) and row.get("acted")]

    def _key(entry: dict[str, Any]) -> str:
        gate = entry.get("gate") or {}
        return str(gate.get("local_time") or entry.get("logged_at") or "")

    return sorted(rows, key=_key)


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _blank_position() -> dict[str, Any]:
    return {
        "shares_core": 0.0,
        "shares_tactical": 0.0,
        "basis_core": 0.0,
        "basis_tactical": 0.0,
        "fill_core": 0.0,
        "fill_tactical": 0.0,
        "reopen_below": None,
        "skimmed": False,
    }


def _shares(pos: dict[str, Any]) -> float:
    return float(pos["shares_core"]) + float(pos["shares_tactical"])


def _avg_fill(pos: dict[str, Any], bucket: str) -> float | None:
    shares = float(pos[f"shares_{bucket}"])
    fill = float(pos[f"fill_{bucket}"])
    if shares <= 1e-12 or fill <= 0:
        return None
    return fill / shares


def _targets(entry: dict[str, Any]) -> list[dict[str, Any]]:
    selection = entry.get("selection") or {}
    skip_wait = bool(selection.get("skip_timing_wait", True))
    rows: list[dict[str, Any]] = []
    for row in entry.get("candidates") or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        price = _optional_float(row.get("price"))
        signal = str(row.get("signal") or "")
        if not ticker or price is None or price <= 0 or signal not in BUY_SIGNALS:
            continue
        if skip_wait and str(row.get("timing_signal") or "") == "wait":
            continue
        rows.append(row)
    return rows


def _entry_day(entry: dict[str, Any]) -> date | None:
    raw = str(entry.get("logged_at") or "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _price_map(entry: dict[str, Any], last_price: dict[str, float]) -> dict[str, float]:
    prices = dict(last_price)
    for row in entry.get("candidates") or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        price = _optional_float(row.get("price"))
        if ticker and price is not None and price > 0:
            prices[ticker] = price
    return prices


def _plan_level(row: dict[str, Any] | None, key: str) -> float | None:
    if not row:
        return None
    plan = row.get("trade_plan") or {}
    if not isinstance(plan, dict):
        return None
    level = _optional_float(plan.get(key))
    if level is None or level <= 0:
        return None
    return level


def _sell(
    book: dict[str, Any],
    ticker: str,
    bucket: str,
    shares: float,
    price: float,
    sell_cost: float,
) -> float:
    pos = book["positions"].get(ticker)
    if pos is None or price <= 0:
        return 0.0
    held = float(pos[f"shares_{bucket}"])
    shares = min(float(shares), held)
    if shares <= 1e-12:
        return 0.0
    frac = shares / held
    gross = shares * price
    cost = gross * sell_cost
    book["cash"] += gross - cost
    book["costs"] += cost
    book["sells"] += 1
    pos[f"shares_{bucket}"] = held - shares
    pos[f"basis_{bucket}"] = float(pos[f"basis_{bucket}"]) * (1.0 - frac)
    pos[f"fill_{bucket}"] = float(pos[f"fill_{bucket}"]) * (1.0 - frac)
    if _shares(pos) <= 1e-9:
        pos["skimmed"] = False
    return gross


def _buy(
    book: dict[str, Any],
    ticker: str,
    bucket: str,
    budget: float,
    price: float,
    buy_cost: float,
) -> None:
    budget = min(float(budget), float(book["cash"]))
    if price <= 0 or budget <= 1e-6:
        return
    shares = budget / (price * (1.0 + buy_cost))
    spent = shares * price * (1.0 + buy_cost)
    if spent > book["cash"] + 1e-9:
        return
    book["cash"] -= spent
    book["costs"] += shares * price * buy_cost
    book["buys"] += 1
    pos = book["positions"].setdefault(ticker, _blank_position())
    pos[f"shares_{bucket}"] = float(pos[f"shares_{bucket}"]) + shares
    pos[f"basis_{bucket}"] = float(pos[f"basis_{bucket}"]) + spent
    pos[f"fill_{bucket}"] = float(pos[f"fill_{bucket}"]) + shares * price


def _move_tactical_to_core(pos: dict[str, Any]) -> None:
    pos["shares_core"] = float(pos["shares_core"]) + float(pos["shares_tactical"])
    pos["basis_core"] = float(pos["basis_core"]) + float(pos["basis_tactical"])
    pos["fill_core"] = float(pos["fill_core"]) + float(pos["fill_tactical"])
    pos["shares_tactical"] = 0.0
    pos["basis_tactical"] = 0.0
    pos["fill_tactical"] = 0.0


def _nav(book: dict[str, Any], prices: dict[str, float]) -> float:
    total = float(book["cash"])
    for ticker, pos in book["positions"].items():
        price = prices.get(ticker)
        if price is None:
            continue
        total += _shares(pos) * price
    return total


def _drop_flat(book: dict[str, Any]) -> None:
    empty = [ticker for ticker, pos in book["positions"].items() if _shares(pos) <= 1e-9]
    for ticker in empty:
        if book["positions"][ticker].get("reopen_below") is None:
            book["positions"].pop(ticker, None)


def _candidate_rows(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in entry.get("candidates") or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            rows[ticker] = row
    return rows


def _sell_core_on_thesis(
    book: dict[str, Any],
    ticker: str,
    pos: dict[str, Any],
    row: dict[str, Any] | None,
    price: float,
    sell_cost: float,
    *,
    confirmed: bool,
) -> None:
    if not confirmed or float(pos["shares_core"]) <= 0:
        return
    _sell(book, ticker, "core", pos["shares_core"], price, sell_cost)
    book["core_thesis_exits"] += 1
    reason = core_sell_reason(row)
    if reason == "screen_avoid":
        book["screen_avoid_exits"] += 1
    elif reason == "research_failed":
        book["research_failed_exits"] += 1


def _apply_sells(
    book: dict[str, Any],
    policy: str,
    targets: dict[str, dict[str, Any]],
    prices: dict[str, float],
    streaks: dict[str, int],
    thesis_streaks: dict[str, int],
    candidate_rows: dict[str, dict[str, Any]],
    *,
    exit_confirm: int,
    sell_cost: float,
) -> None:
    for ticker, pos in list(book["positions"].items()):
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        row = targets.get(ticker)
        logged = candidate_rows.get(ticker)
        in_set = row is not None
        if in_set and streaks.get(ticker, 0) > 0:
            pos["reopen_below"] = None
        streak = 0 if in_set else streaks.get(ticker, 0)
        rank_exit = streak >= exit_confirm
        thesis_exit = thesis_break_confirmed(thesis_streaks.get(ticker, 0), exit_confirm)

        if policy == "full_exit":
            if rank_exit and _shares(pos) > 0:
                _sell(book, ticker, "tactical", pos["shares_tactical"], price, sell_cost)
                _sell(book, ticker, "core", pos["shares_core"], price, sell_cost)
                book["rank_exits"] += 1
                book["cooldown"][ticker] = int(book["reentry_cooldown"])
            continue

        if policy in {"core_kept", "core_thesis_exit"}:
            tactical = float(pos["shares_tactical"])
            if tactical > 0:
                fill = _avg_fill(pos, "tactical") or price
                target = _plan_level(row, "tactical_take_profit") or fill * TARGET_ABOVE_FILL
                stop = _plan_level(row, "tactical_stop_loss") or fill * STOP_BELOW_FILL
                if price >= target or price <= stop or rank_exit:
                    _sell(book, ticker, "tactical", tactical, price, sell_cost)
                    pos["reopen_below"] = price * DIP_REOPEN
                    if price >= target:
                        book["target_sales"] += 1
                    elif price <= stop:
                        book["stop_sales"] += 1
                    else:
                        book["rank_exits"] += 1
            if policy == "core_thesis_exit":
                _sell_core_on_thesis(
                    book,
                    ticker,
                    pos,
                    logged,
                    price,
                    sell_cost,
                    confirmed=thesis_exit,
                )
            continue

        if policy == "harvest_skim":
            tactical = float(pos["shares_tactical"])
            if tactical <= 0:
                continue
            fill = _avg_fill(pos, "tactical") or price
            gain = price / fill - 1.0 if fill > 0 else 0.0
            if in_set and not pos["skimmed"] and gain >= GAIN_FLOOR and price > fill:
                profit_mv = tactical * price - tactical * fill
                skim_shares = max(0.0, HARVEST_SKIM_OF_PROFIT * profit_mv / price)
                _sell(book, ticker, "tactical", skim_shares, price, sell_cost)
                _move_tactical_to_core(pos)
                pos["skimmed"] = True
                pos["reopen_below"] = price * DIP_REOPEN
                book["skims"] += 1
            elif rank_exit:
                _sell(book, ticker, "tactical", pos["shares_tactical"], price, sell_cost)
                book["rank_exits"] += 1
                book["cooldown"][ticker] = int(book["reentry_cooldown"])
            continue

        if policy == "profit_residual":
            tactical = float(pos["shares_tactical"])
            if tactical <= 0:
                continue
            fill = _avg_fill(pos, "tactical") or price
            gain = price / fill - 1.0 if fill > 0 else 0.0
            target = _plan_level(row, "tactical_take_profit")
            hit_target = target is not None and price >= target
            if price > fill and (gain >= GAIN_FLOOR or hit_target):
                basis_mv = tactical * fill
                sell_shares = min(tactical, basis_mv / price)
                _sell(book, ticker, "tactical", sell_shares, price, sell_cost)
                if float(pos["shares_tactical"]) > 1e-9:
                    _move_tactical_to_core(pos)
                    book["residual_donations"] += 1
                pos["reopen_below"] = price * DIP_REOPEN
            elif rank_exit:
                _sell(book, ticker, "tactical", pos["shares_tactical"], price, sell_cost)
                book["rank_exits"] += 1
                book["cooldown"][ticker] = int(book["reentry_cooldown"])


def _desired_budget(
    policy: str,
    pos: dict[str, Any] | None,
    *,
    slot: float,
    price: float,
    in_cooldown: bool,
    thesis_blocked: bool = False,
) -> tuple[float, float]:
    """Return (core budget, tactical budget) still to buy. Never negative."""
    if in_cooldown or slot <= 0 or price <= 0:
        return 0.0, 0.0
    pos = pos or _blank_position()
    core_value = float(pos["shares_core"]) * price
    tactical_value = float(pos["shares_tactical"]) * price
    reopen_below = pos.get("reopen_below")
    tactical_closed = reopen_below is not None and price > float(reopen_below)

    if policy == "full_exit":
        return 0.0, max(0.0, slot - core_value - tactical_value)
    if policy in {"core_kept", "core_thesis_exit"}:
        core_budget = max(0.0, CORE_PCT * slot - core_value)
        if policy == "core_thesis_exit" and thesis_blocked:
            core_budget = 0.0
        tactical_slot = 0.0 if tactical_closed else (1.0 - CORE_PCT) * slot
        return core_budget, max(0.0, tactical_slot - tactical_value)
    if policy in {"harvest_skim", "profit_residual"}:
        if tactical_closed or pos.get("skimmed"):
            tactical_slot = 0.0
        else:
            tactical_slot = max(0.0, slot - core_value)
        return 0.0, max(0.0, tactical_slot - tactical_value)
    return 0.0, 0.0


def replay_policy(
    passes: list[dict[str, Any]],
    policy: str,
    *,
    buy_cost: float,
    sell_cost: float,
    exit_confirm: int = 2,
    reentry_cooldown: int = 1,
    min_notional: float = 10.0,
    max_positions: int = 120,
    starting_cash: float = 1000.0,
    external_price: Callable[[str, date], float | None] | None = None,
) -> dict[str, Any]:
    """Replay one retention rule. ``full_exit`` keeps every share in one lot."""
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy}")
    book: dict[str, Any] = {
        "cash": float(starting_cash),
        "costs": 0.0,
        "buys": 0,
        "sells": 0,
        "rank_exits": 0,
        "target_sales": 0,
        "stop_sales": 0,
        "skims": 0,
        "residual_donations": 0,
        "core_thesis_exits": 0,
        "screen_avoid_exits": 0,
        "research_failed_exits": 0,
        "external_fills": 0,
        "positions": {},
        "cooldown": {},
        "reentry_cooldown": int(reentry_cooldown),
    }
    streaks: dict[str, int] = {}
    thesis_streaks: dict[str, int] = {}
    last_price: dict[str, float] = {}
    if not passes:
        return _result(book, policy, last_price, starting_cash)

    for entry in passes:
        prices = _price_map(entry, {})
        day = _entry_day(entry)
        if external_price is not None and day is not None:
            for ticker in list(book["positions"]):
                if ticker in prices:
                    continue
                filled = external_price(ticker, day)
                if filled is not None and filled > 0:
                    prices[ticker] = float(filled)
                    book["external_fills"] += 1
        for ticker, prev in last_price.items():
            prices.setdefault(ticker, prev)
        last_price = prices
        target_rows = _targets(entry)[: int(max_positions)]
        targets = {str(row["ticker"]): row for row in target_rows}
        logged_rows = _candidate_rows(entry)
        held = list(book["positions"])
        reentered: set[str] = set()
        for ticker in set(held) | set(targets):
            if ticker in targets:
                if streaks.get(ticker, 0) > 0:
                    reentered.add(ticker)
                streaks[ticker] = 0
            elif ticker in book["positions"]:
                streaks[ticker] = streaks.get(ticker, 0) + 1
        for ticker in held:
            note_thesis_streak(thesis_streaks, ticker, logged_rows.get(ticker))
        for ticker in reentered:
            pos = book["positions"].get(ticker)
            if pos is not None:
                pos["reopen_below"] = None
        _apply_sells(
            book,
            policy,
            targets,
            prices,
            streaks,
            thesis_streaks,
            logged_rows,
            exit_confirm=int(exit_confirm),
            sell_cost=float(sell_cost),
        )
        _drop_flat(book)
        nav = _nav(book, prices)
        slot = nav / len(targets) if targets else 0.0
        shortfalls: list[tuple[float, str, float, float, bool]] = []
        for ticker in targets:
            price = prices.get(ticker)
            if price is None:
                continue
            pos = book["positions"].get(ticker)
            if (
                pos is not None
                and pos.get("reopen_below") is not None
                and price <= float(pos["reopen_below"])
            ):
                pos["reopen_below"] = None
            if int(book["cooldown"].get(ticker) or 0) > 0:
                continue
            core_budget, tactical_budget = _desired_budget(
                policy,
                pos,
                slot=slot,
                price=price,
                in_cooldown=False,
                thesis_blocked=core_sell_reason(logged_rows.get(ticker)) is not None,
            )
            need = core_budget + tactical_budget
            is_new = pos is None or _shares(pos) <= 1e-12
            if need < min_notional and not is_new:
                continue
            if need > 1e-6:
                shortfalls.append((need, ticker, core_budget, tactical_budget, is_new))
        for _need, ticker, core_budget, tactical_budget, _is_new in sorted(
            shortfalls, key=lambda item: (-item[0], item[1])
        ):
            price = prices[ticker]
            if core_budget > 0:
                _buy(book, ticker, "core", core_budget, price, buy_cost)
            if tactical_budget > 0:
                _buy(book, ticker, "tactical", tactical_budget, price, buy_cost)
        for ticker in list(book["cooldown"]):
            book["cooldown"][ticker] = int(book["cooldown"][ticker]) - 1
            if book["cooldown"][ticker] <= 0:
                book["cooldown"].pop(ticker, None)

    return _result(book, policy, last_price, starting_cash)


def _result(
    book: dict[str, Any],
    policy: str,
    prices: dict[str, float],
    starting_cash: float,
) -> dict[str, Any]:
    core_value = 0.0
    tactical_value = 0.0
    names_with_core = 0
    for ticker, pos in book["positions"].items():
        price = prices.get(ticker)
        if price is None:
            continue
        core = float(pos["shares_core"]) * price
        tactical = float(pos["shares_tactical"]) * price
        core_value += core
        tactical_value += tactical
        if float(pos["shares_core"]) > 1e-9:
            names_with_core += 1
    nav = float(book["cash"]) + core_value + tactical_value
    base = float(starting_cash) if starting_cash > 0 else 1.0
    return {
        "policy": policy,
        "nav": _round(nav, 2),
        "return": _round((nav - base) / base),
        "cost_drag": _round(float(book["costs"]) / base),
        "cash": _round(float(book["cash"]), 2),
        "core_value": _round(core_value, 2),
        "tactical_value": _round(tactical_value, 2),
        "names_with_core": names_with_core,
        "buys": int(book["buys"]),
        "sells": int(book["sells"]),
        "rank_exits": int(book["rank_exits"]),
        "target_sales": int(book["target_sales"]),
        "stop_sales": int(book["stop_sales"]),
        "skims": int(book["skims"]),
        "residual_donations": int(book["residual_donations"]),
        "core_thesis_exits": int(book["core_thesis_exits"]),
        "screen_avoid_exits": int(book["screen_avoid_exits"]),
        "research_failed_exits": int(book["research_failed_exits"]),
        "external_fills": int(book["external_fills"]),
    }


def _costs_and_knobs(track_dir: Path, acted: list[dict[str, Any]]) -> dict[str, Any]:
    fund_path = track_dir / FUND_FILENAME
    fund: dict[str, Any] = {}
    if fund_path.exists():
        fund = json.loads(fund_path.read_text(encoding="utf-8"))
    config = fund.get("config") or {}
    selection = (acted[-1].get("selection") or {}) if acted else {}
    first = acted[0] if acted else {}
    buy_cost = _optional_float(config.get("buy_cost_pct"))
    sell_cost = _optional_float(config.get("sell_cost_pct"))
    if buy_cost is None or sell_cost is None:
        symmetric = _optional_float(first.get("trade_cost_pct")) or 0.0
        buy_cost = symmetric
        sell_cost = symmetric
    return {
        "buy_cost": float(buy_cost),
        "sell_cost": float(sell_cost),
        "exit_confirm": int(selection.get("exit_confirm_screens") or 2),
        "reentry_cooldown": int(selection.get("reentry_cooldown_screens") or 1),
        "min_notional": float(selection.get("min_rebalance_notional_gbp") or 10.0),
        "max_positions": int(first.get("max_positions") or config.get("max_positions") or 120),
        "starting_cash": float(first.get("nav_before") or config.get("initial_cash") or 1000.0),
        "logged_end_nav": _optional_float(acted[-1].get("nav_after")) if acted else None,
    }


def _lazy_external(
    fetcher: Callable[..., Any],
    start: date,
    end: date,
) -> Callable[[str, date], float | None]:
    from value_investor.total_return_view import _close_before

    cache: dict[str, dict[date, float]] = {}

    def lookup(ticker: str, day: date) -> float | None:
        if ticker not in cache:
            try:
                history = fetcher(ticker, start, end)
                closes = getattr(history, "closes", None) or {}
                cache[ticker] = {key: float(value) for key, value in closes.items()}
            except (OSError, ValueError, TypeError):
                cache[ticker] = {}
        return _close_before(cache[ticker], day + timedelta(days=1))

    return lookup


def _core_sell_summary(variants: dict[str, dict[str, Any]], confirm_screens: int) -> dict[str, Any]:
    thesis = variants["core_thesis_exit"]
    kept = variants["core_kept"]
    return {
        "policy": "core_thesis_exit",
        "confirm_screens": int(confirm_screens),
        "sells_on": ["screen signal avoid", "research verdict pass, sell, avoid, or exit"],
        "does_not_sell_on": [
            "left the buy tier",
            "cheapness family failed",
            "research caution or neutral",
            "price drop",
        ],
        "core_thesis_exits": int(thesis["core_thesis_exits"]),
        "screen_avoid_exits": int(thesis["screen_avoid_exits"]),
        "research_failed_exits": int(thesis["research_failed_exits"]),
        "core_value": thesis["core_value"],
        "nav": thesis["nav"],
        "delta_vs_core_kept": _round(float(thesis["return"]) - float(kept["return"])),
        "delta_vs_full_exit": thesis["delta_vs_full_exit"],
    }


def build_two_lot_replay(
    paper_root: Path = DEFAULT_PAPER_ROOT,
    *,
    track_id: str = TRACK_ID,
    history_fetcher: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    root = Path(paper_root)
    track_dir = root / track_id if track_id != "rules" else root
    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "learning_question": LEARNING_QUESTION,
        "track_id": track_id,
        "observe_only": True,
        "method": {
            "core_pct": CORE_PCT,
            "gain_floor": GAIN_FLOOR,
            "harvest_skim_of_profit": HARVEST_SKIM_OF_PROFIT,
            "target_above_fill": TARGET_ABOVE_FILL,
            "stop_below_fill": STOP_BELOW_FILL,
            "dip_reopen": DIP_REOPEN,
            "scored_against": "full_exit inside this engine",
            "fidelity_tolerance": FIDELITY_TOLERANCE,
            "edge_min": EDGE_MIN,
            "core_sell": (
                "hard screen avoid, or research verdict pass/sell/avoid/exit, "
                "held for exit_confirm_screens; rank and cheapness do not sell the core"
            ),
        },
        "status": "missing",
    }
    if track_dir is None or not (track_dir / "rebalance_log.json").exists():
        payload["reason"] = f"{track_id} has no rebalance log"
        return payload

    acted = _load_acted(track_dir)
    knobs = _costs_and_knobs(track_dir, acted)
    payload["passes"] = len(acted)
    payload["window"] = {
        "from": acted[0].get("logged_at") if acted else None,
        "to": acted[-1].get("logged_at") if acted else None,
        "logged_end_nav": knobs["logged_end_nav"],
        "starting_cash": knobs["starting_cash"],
        "buy_cost_pct": knobs["buy_cost"],
        "sell_cost_pct": knobs["sell_cost"],
        "exit_confirm_screens": knobs["exit_confirm"],
    }
    if len(acted) < MIN_PASSES:
        payload["status"] = "thin"
        payload["reason"] = f"fewer than {MIN_PASSES} acted passes"
        return payload

    common = {
        "buy_cost": knobs["buy_cost"],
        "sell_cost": knobs["sell_cost"],
        "exit_confirm": knobs["exit_confirm"],
        "reentry_cooldown": knobs["reentry_cooldown"],
        "min_notional": knobs["min_notional"],
        "max_positions": knobs["max_positions"],
        "starting_cash": knobs["starting_cash"],
    }
    if history_fetcher is not None:
        start_day = _entry_day(acted[0])
        end_day = _entry_day(acted[-1])
        if start_day is not None and end_day is not None:
            common["external_price"] = _lazy_external(history_fetcher, start_day, end_day)
    variants = {policy: replay_policy(acted, policy, **common) for policy in POLICIES}
    baseline = variants["full_exit"]
    logged = knobs["logged_end_nav"]
    start = float(knobs["starting_cash"]) or 1.0
    fidelity_gap = None
    if logged is not None and start > 0:
        fidelity_gap = _round((float(baseline["nav"]) - float(logged)) / start)
    for policy, row in variants.items():
        if policy == "full_exit":
            row["delta_vs_full_exit"] = 0.0
        else:
            row["delta_vs_full_exit"] = _round(float(row["return"]) - float(baseline["return"]))
    best_name = max(
        (name for name in RETENTION_POLICIES if name != "full_exit"),
        key=lambda name: float(variants[name]["delta_vs_full_exit"]),
    )
    best = variants[best_name]
    status = "ok"
    reason = None
    if fidelity_gap is None or abs(float(fidelity_gap)) > FIDELITY_TOLERANCE:
        status = "unreliable"
        reason = (
            "full-exit replay is outside "
            f"{FIDELITY_TOLERANCE:.0%} of logged NAV; deltas stay inside this engine"
        )
    payload.update(
        {
            "status": status,
            "reason": reason,
            "fidelity_gap": fidelity_gap,
            "external_price_fills": int(variants["core_kept"]["external_fills"]),
            "variants": variants,
            "best_variant": {
                "policy": best_name,
                "delta_vs_full_exit": best["delta_vs_full_exit"],
            },
            "core_sell": _core_sell_summary(variants, knobs["exit_confirm"]),
            "limitations": (
                "Price-only marks from the rebalance log, fair buy and sell costs, "
                "no dividends. core_kept never sells its core. core_thesis_exit sells "
                "the core only after a hard avoid or a failed research verdict has "
                "lasted the book's exit-confirm screens. Rank and a lost cheapness "
                "screen do not sell it. A positive delta is a hypothesis, not a change "
                "to buy_tier_level. Weeks of passes are not a multi-year value test."
            ),
        }
    )
    return payload


def refresh_two_lot_replay(
    paper_root: Path = DEFAULT_PAPER_ROOT,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    history_fetcher: Callable[..., Any] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    payload = build_two_lot_replay(paper_root, history_fetcher=history_fetcher)
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_finding_from_two_lot_replay(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Warn when a faithful replay shows a retention rule ahead of full exit by ≥1pp."""
    if payload.get("status") != "ok":
        return None
    best = payload.get("best_variant") or {}
    delta = float(best.get("delta_vs_full_exit") or 0.0)
    if delta < EDGE_MIN:
        return None
    policy = str(best.get("policy"))
    row = (payload.get("variants") or {}).get(policy) or {}
    window = payload.get("window") or {}
    return {
        "severity": "warn",
        "category": "paper",
        "title": FINDING_TITLE,
        "summary": (
            f"{payload.get('track_id')}: {policy} beats full exit by {delta:+.1%} "
            f"over {payload.get('passes')} passes "
            f"({window.get('from', '')[:10]} to {window.get('to', '')[:10]}; "
            f"core value £{row.get('core_value')}, "
            f"rank exits {row.get('rank_exits')} vs full exit). "
            "Observe-only. Do not edit buy_tier_level. "
            "See docs/ops/two-lot-replay.md."
        ),
        "auto_fixable": False,
    }


def ops_finding_from_core_sell(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Warn when a persisted thesis break moves the kept-core replay by ≥1pp."""
    if payload.get("status") != "ok":
        return None
    core_sell = payload.get("core_sell") or {}
    exits = int(core_sell.get("core_thesis_exits") or 0)
    delta = float(core_sell.get("delta_vs_core_kept") or 0.0)
    if exits < 1 or abs(delta) < EDGE_MIN:
        return None
    window = payload.get("window") or {}
    return {
        "severity": "warn",
        "category": "paper",
        "title": CORE_SELL_FINDING_TITLE,
        "summary": (
            f"{payload.get('track_id')}: selling the core after a persisted thesis "
            f"break ({exits} exit(s), {core_sell.get('screen_avoid_exits', 0)} hard "
            f"avoid, {core_sell.get('research_failed_exits', 0)} failed research) "
            f"changes the kept-core replay by {delta:+.1%} "
            f"over {payload.get('passes')} passes "
            f"({window.get('from', '')[:10]} to {window.get('to', '')[:10]}). "
            "Rank and a lost cheapness screen do not sell the core. "
            "Observe-only. Do not edit buy_tier_level. "
            "See docs/ops/two-lot-replay.md."
        ),
        "auto_fixable": False,
    }
