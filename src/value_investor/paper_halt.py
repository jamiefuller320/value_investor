"""Observe-only paper halt on drawdown and concentration (L564).

Computes whether a book would freeze new buys. Does not freeze anything,
does not flatten, and does not touch the fund. Live broker stays out (N13).

A single-currency book does not warn on currency. A GBP book warns when more
than half the NAV is outside GBP. A multi-currency book warns when one
currency is more than 60% of NAV.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.paper_fund import PaperFund

DEFAULT_STORE_PATH = Path("docs/data/paper_halt.json")
DRAWDOWN_HALT = 0.20
NAME_WEIGHT_HALT = 0.40
SECTOR_WEIGHT_HALT = 0.50
NON_REPORTING_CURRENCY_HALT = 0.50
ONE_CURRENCY_HALT = 0.60
FINDING_TITLE = "Paper book would halt on drawdown or concentration"


def _position_value(position: Any) -> float:
    price = float(position.avg_cost or 0.0)
    if price <= 0:
        return 0.0
    return float(position.shares) * price


def _drawdown(fund: PaperFund) -> float | None:
    values = [
        float(mark["portfolio_value"])
        for mark in fund.equity_curve
        if isinstance(mark, dict) and mark.get("portfolio_value") is not None
    ]
    if len(values) < 2:
        return None
    peak = max(values)
    if peak <= 0:
        return None
    return round((peak - values[-1]) / peak, 4)


def evaluate_fund(fund: PaperFund, *, track_id: str) -> dict[str, Any]:
    """Read-only halt state. Weights use average cost, labelled as such."""
    reporting = str(fund.config.reporting_currency or "GBP")
    values: dict[str, float] = {}
    sectors: dict[str, float] = {}
    currencies: dict[str, float] = {}
    invested = 0.0
    for ticker, position in fund.holdings.items():
        value = _position_value(position)
        if value <= 0:
            continue
        values[ticker] = value
        invested += value
        sector = str(position.sector or "Unknown") or "Unknown"
        sectors[sector] = sectors.get(sector, 0.0) + value
        currency = str(position.currency or reporting)
        currencies[currency] = currencies.get(currency, 0.0) + value
    cash = float(fund.cash)
    nav = cash + invested
    currencies[reporting] = currencies.get(reporting, 0.0) + max(cash, 0.0)
    holding_currencies = {
        str(position.currency or reporting) for position in fund.holdings.values()
    }
    multi_currency = len({c for c in holding_currencies if c} | {reporting}) > 1 and any(
        c != reporting for c in holding_currencies
    )

    def weight(amount: float) -> float:
        return 0.0 if nav <= 0 else amount / nav

    max_name, max_name_value = ("", 0.0)
    if values:
        max_name, max_name_value = max(values.items(), key=lambda item: item[1])
    max_sector, max_sector_value = ("", 0.0)
    if sectors:
        max_sector, max_sector_value = max(sectors.items(), key=lambda item: item[1])
    max_currency, max_currency_value = (reporting, currencies.get(reporting, 0.0))
    if currencies:
        max_currency, max_currency_value = max(currencies.items(), key=lambda item: item[1])
    non_reporting = sum(amount for currency, amount in currencies.items() if currency != reporting)

    drawdown = _drawdown(fund)
    name_weight = round(weight(max_name_value), 4)
    sector_weight = round(weight(max_sector_value), 4)
    non_reporting_weight = round(weight(non_reporting), 4)
    currency_weight = round(weight(max_currency_value), 4)

    breaches: list[str] = []
    if drawdown is not None and drawdown >= DRAWDOWN_HALT:
        breaches.append(f"drawdown {drawdown:.0%} ≥ {DRAWDOWN_HALT:.0%}")
    if name_weight >= NAME_WEIGHT_HALT:
        breaches.append(f"{max_name} weight {name_weight:.0%} ≥ {NAME_WEIGHT_HALT:.0%}")
    if sector_weight >= SECTOR_WEIGHT_HALT:
        breaches.append(f"{max_sector} weight {sector_weight:.0%} ≥ {SECTOR_WEIGHT_HALT:.0%}")
    if reporting == "GBP" and non_reporting_weight > NON_REPORTING_CURRENCY_HALT:
        breaches.append(
            f"non-GBP weight {non_reporting_weight:.0%} > {NON_REPORTING_CURRENCY_HALT:.0%}"
        )
    elif multi_currency and currency_weight > ONE_CURRENCY_HALT:
        breaches.append(f"{max_currency} weight {currency_weight:.0%} > {ONE_CURRENCY_HALT:.0%}")

    return {
        "track_id": track_id,
        "weight_basis": "average_cost",
        "drawdown": drawdown,
        "max_name": max_name or None,
        "max_name_weight": name_weight,
        "max_sector": max_sector or None,
        "max_sector_weight": sector_weight,
        "reporting_currency": reporting,
        "non_reporting_currency_weight": non_reporting_weight,
        "max_currency": max_currency,
        "max_currency_weight": currency_weight,
        "multi_currency": multi_currency,
        "breaches": breaches,
        "would_halt": bool(breaches),
        "action_if_promoted": "freeze new buys or flatten to cash, then wait for a human",
    }


def build_paper_halt(
    funds: list[tuple[str, PaperFund]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    rows = [evaluate_fund(fund, track_id=track_id) for track_id, fund in funds]
    return {
        "schema": "paper_halt.v1",
        "generated_at": (now or datetime.now(UTC)).isoformat(),
        "observe_only": True,
        "books_unchanged": True,
        "thresholds": {
            "drawdown": DRAWDOWN_HALT,
            "name_weight": NAME_WEIGHT_HALT,
            "sector_weight": SECTOR_WEIGHT_HALT,
            "non_gbp_weight": NON_REPORTING_CURRENCY_HALT,
            "one_currency_weight": ONE_CURRENCY_HALT,
        },
        "tracks": rows,
    }


def finding_for_halt(payload: dict[str, Any]) -> dict[str, Any] | None:
    halted = [row for row in payload.get("tracks") or [] if row.get("would_halt")]
    if not halted:
        return None
    bits = [f"{row['track_id']}: " + "; ".join(row.get("breaches") or []) for row in halted]
    return {
        "severity": "warn",
        "category": "paper",
        "title": FINDING_TITLE,
        "summary": (
            "Observe-only. Books were not frozen or flattened. "
            + " | ".join(bits)
            + ". See docs/ops/paper-halt.md."
        ),
        "auto_fixable": False,
    }


def load_learning_funds(paper_root: Path) -> list[tuple[str, PaperFund]]:
    from value_investor.paper_automation import FUND_FILENAME, learning_track_dirs

    root = Path(paper_root)
    if not root.exists():
        return []
    funds: list[tuple[str, PaperFund]] = []
    for track_id, track_dir in learning_track_dirs(root).items():
        path = Path(track_dir) / FUND_FILENAME
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            funds.append((track_id, PaperFund.from_dict(payload)))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return funds


def refresh_paper_halt(
    paper_root: Path,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    persist: bool = True,
) -> dict[str, Any]:
    payload = build_paper_halt(load_learning_funds(paper_root))
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
