"""Per-market fair trading-cost assumptions (T212 Invest–shaped).

Paper books historically used a flat ``trade_cost_pct = 0.03`` (3% per side ≈ 6%
round-trip). That is a harsh churn tax, not broker reality for Trading 212 Invest.

This module encodes **documented, explicit** friction assumptions by market so
observe sims / shards / cost assessments can use fair rates without silently
rewriting the live FTSE learning book's stored 3% stress case.

Components (Invest account, commission-free):
- Half-spread each way (liquid large-caps)
- UK stamp duty reserve tax on **buys** of UK shares (~0.5%)
- FX conversion when the book is GBP-funded and the venue is non-GBP
  (T212-style ~0.15% on conversion; modelled per side when FX applies)

Rates are estimates for learning fairness — not a live brokerage quote.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Legacy stress default kept for continuity with live FTSE paper configs.
LEGACY_STRESS_TRADE_COST_PCT = 0.03

# Shared building blocks (decimals).
HALF_SPREAD_LIQUID = 0.00025  # 0.025% — half of ≤0.05% quoted spread
UK_STAMP_DUTY_BUY = 0.005  # 0.5% SDRT on UK share purchases (Invest)
FX_CONVERSION = 0.0015  # 0.15% T212-style FX on currency conversion


@dataclass(frozen=True)
class MarketTradingCosts:
    """Per-side friction for a market under fair T212-shaped assumptions."""

    market_id: str
    label: str
    buy_pct: float
    sell_pct: float
    currency: str
    fx_applies: bool
    stamp_duty_on_buy: bool
    half_spread: float
    notes: str
    source: str = "t212_invest_fair_v1"

    @property
    def round_trip_pct(self) -> float:
        return float(self.buy_pct) + float(self.sell_pct)

    @property
    def symmetric_proxy_pct(self) -> float:
        """Single rate approximating round-trip / 2 for legacy ``trade_cost_pct`` slots."""
        return self.round_trip_pct / 2.0

    def pct_for_side(self, side: str) -> float:
        side_l = str(side or "").lower()
        if side_l == "buy":
            return float(self.buy_pct)
        if side_l == "sell":
            return float(self.sell_pct)
        raise ValueError(f"Unknown side: {side!r}")

    def cost_on_gross(self, gross: float, *, side: str) -> float:
        return abs(float(gross)) * self.pct_for_side(side)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["round_trip_pct"] = self.round_trip_pct
        payload["symmetric_proxy_pct"] = self.symmetric_proxy_pct
        return payload


def _build(
    market_id: str,
    *,
    label: str,
    currency: str,
    fx_applies: bool,
    stamp_duty_on_buy: bool,
    half_spread: float = HALF_SPREAD_LIQUID,
    notes: str,
) -> MarketTradingCosts:
    fx = FX_CONVERSION if fx_applies else 0.0
    stamp = UK_STAMP_DUTY_BUY if stamp_duty_on_buy else 0.0
    buy = half_spread + stamp + fx
    sell = half_spread + fx
    return MarketTradingCosts(
        market_id=market_id,
        label=label,
        buy_pct=buy,
        sell_pct=sell,
        currency=currency,
        fx_applies=fx_applies,
        stamp_duty_on_buy=stamp_duty_on_buy,
        half_spread=half_spread,
        notes=notes,
    )


# Canonical fair tables. Unknown markets fall back via region heuristics.
MARKET_TRADING_COSTS: dict[str, MarketTradingCosts] = {
    "ftse350": _build(
        "ftse350",
        label="FTSE 350 (UK)",
        currency="GBP",
        fx_applies=False,
        stamp_duty_on_buy=True,
        notes="UK Invest: 0.5% stamp on buys + half-spread; no FX for GBP book.",
    ),
    "ftse_smallcap": _build(
        "ftse_smallcap",
        label="FTSE SmallCap (UK)",
        currency="GBP",
        fx_applies=False,
        stamp_duty_on_buy=True,
        half_spread=0.0005,
        notes="UK stamp + wider small-cap half-spread (0.05%).",
    ),
    "aim": _build(
        "aim",
        label="AIM (UK)",
        currency="GBP",
        fx_applies=False,
        stamp_duty_on_buy=True,
        half_spread=0.00075,
        notes="UK stamp + wider AIM half-spread; many AIM names are stamp-exempt — "
        "we keep stamp on for conservative learning until per-ticker exemption lands.",
    ),
    "sp500": _build(
        "sp500",
        label="S&P 500 (US)",
        currency="USD",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="Commission-free; FX ~0.15%/conversion when GBP-funded + half-spread.",
    ),
    "nasdaq100": _build(
        "nasdaq100",
        label="Nasdaq-100 (US)",
        currency="USD",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="Same shape as S&P 500 for GBP-funded T212 Invest.",
    ),
    "euro_stoxx50": _build(
        "euro_stoxx50",
        label="EURO STOXX 50",
        currency="EUR",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="No UK stamp; FX + half-spread for GBP-funded book.",
    ),
    "euro_depth": _build(
        "euro_depth",
        label="EU depth pilot (multi-currency)",
        currency="EUR",
        fx_applies=True,
        stamp_duty_on_buy=False,
        half_spread=0.00035,
        notes="Multi-ccy periphery (CHF/SEK/…); slightly wider half-spread + FX. "
        "Reporting NAV FX is separate (fx.py).",
    ),
    "dax": _build(
        "dax",
        label="DAX",
        currency="EUR",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="EUR venue; FX + half-spread.",
    ),
    "cac40": _build(
        "cac40",
        label="CAC 40",
        currency="EUR",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="EUR venue; FX + half-spread.",
    ),
    "aex": _build(
        "aex",
        label="AEX",
        currency="EUR",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="EUR venue; FX + half-spread.",
    ),
    "bel20": _build(
        "bel20",
        label="BEL 20",
        currency="EUR",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="EUR venue; FX + half-spread.",
    ),
    "ibex35": _build(
        "ibex35",
        label="IBEX 35",
        currency="EUR",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="EUR venue; FX + half-spread.",
    ),
    "ftse_mib": _build(
        "ftse_mib",
        label="FTSE MIB",
        currency="EUR",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="EUR venue; FX + half-spread.",
    ),
    "atx": _build(
        "atx",
        label="ATX",
        currency="EUR",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="EUR venue; FX + half-spread.",
    ),
    "psi20": _build(
        "psi20",
        label="PSI 20",
        currency="EUR",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="EUR venue; FX + half-spread.",
    ),
    "smi": _build(
        "smi",
        label="SMI",
        currency="CHF",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="CHF venue; FX + half-spread.",
    ),
    "omxs30": _build(
        "omxs30",
        label="OMXS30",
        currency="SEK",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="SEK venue; FX + half-spread.",
    ),
    "iseq20": _build(
        "iseq20",
        label="ISEQ 20",
        currency="EUR",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="EUR venue; FX + half-spread.",
    ),
    "asx200": _build(
        "asx200",
        label="ASX 200",
        currency="AUD",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="AUD venue; FX + half-spread (no UK stamp).",
    ),
    "tsx60": _build(
        "tsx60",
        label="TSX 60",
        currency="CAD",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="CAD venue; FX + half-spread.",
    ),
    "hang_seng": _build(
        "hang_seng",
        label="Hang Seng",
        currency="HKD",
        fx_applies=True,
        stamp_duty_on_buy=False,
        half_spread=0.0004,
        notes="HKD venue; FX + modestly wider half-spread.",
    ),
    "sti": _build(
        "sti",
        label="STI",
        currency="SGD",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="SGD venue; FX + half-spread.",
    ),
    "us_adr_asia": _build(
        "us_adr_asia",
        label="US ADR Asia",
        currency="USD",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="USD ADRs; same shape as US cash equities for GBP-funded book.",
    ),
}

# Live FTSE paper automation root (no market_id in path) maps here.
LIVE_PAPER_MARKET_ID = "ftse350"


def normalize_market_id(market_id: str | None) -> str:
    raw = str(market_id or "").strip().lower()
    if not raw or raw in {"ftse", "uk", "live", "paper"}:
        return LIVE_PAPER_MARKET_ID
    return raw


def costs_for_market(market_id: str | None) -> MarketTradingCosts:
    mid = normalize_market_id(market_id)
    if mid in MARKET_TRADING_COSTS:
        return MARKET_TRADING_COSTS[mid]
    # Heuristic fallback for unregistered ids.
    if mid.endswith("_uk") or mid.startswith("ftse"):
        return _build(
            mid,
            label=mid,
            currency="GBP",
            fx_applies=False,
            stamp_duty_on_buy=True,
            notes="Heuristic UK fallback.",
        )
    return _build(
        mid,
        label=mid,
        currency="USD",
        fx_applies=True,
        stamp_duty_on_buy=False,
        notes="Heuristic non-UK fallback (FX + half-spread).",
    )


def trade_cost_pct_for_market(market_id: str | None) -> float:
    """Symmetric proxy for legacy single-rate config slots."""
    return costs_for_market(market_id).symmetric_proxy_pct


def cost_fields_for_config(market_id: str | None) -> dict[str, float]:
    """Fields to stamp onto AutomationConfig / PaperFundConfig."""
    model = costs_for_market(market_id)
    return {
        "trade_cost_pct": model.symmetric_proxy_pct,
        "buy_cost_pct": model.buy_pct,
        "sell_cost_pct": model.sell_pct,
    }


def list_market_costs() -> list[dict[str, Any]]:
    return [MARKET_TRADING_COSTS[k].to_dict() for k in sorted(MARKET_TRADING_COSTS)]


def assess_trades_under_fair_costs(
    trades: list[dict[str, Any]],
    *,
    market_id: str | None,
    contributed_capital: float,
) -> dict[str, Any]:
    """
    Recompute friction on recorded trades under fair market assumptions.

    Uses each trade's ``gross`` and ``side``; does not mutate stored trades.
    """
    model = costs_for_market(market_id)
    recorded = 0.0
    fair = 0.0
    rows: list[dict[str, Any]] = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        side = str(trade.get("side") or "")
        if side not in {"buy", "sell"}:
            continue
        gross = abs(float(trade.get("gross") or 0.0))
        recorded_cost = abs(float(trade.get("cost") or 0.0))
        fair_cost = model.cost_on_gross(gross, side=side)
        recorded += recorded_cost
        fair += fair_cost
        rows.append(
            {
                "id": trade.get("id"),
                "ticker": trade.get("ticker"),
                "side": side,
                "gross": round(gross, 2),
                "recorded_cost": round(recorded_cost, 2),
                "fair_cost": round(fair_cost, 4),
                "recorded_pct": (recorded_cost / gross) if gross else None,
                "fair_pct": model.pct_for_side(side),
            }
        )
    capital = float(contributed_capital or 0.0)
    recorded_drag = (recorded / capital) if capital > 0 else None
    fair_drag = (fair / capital) if capital > 0 else None
    drag_relief = None
    if recorded_drag is not None and fair_drag is not None:
        drag_relief = recorded_drag - fair_drag
    return {
        "market_id": model.market_id,
        "assumptions": model.to_dict(),
        "trade_count": len(rows),
        "recorded_costs": round(recorded, 2),
        "fair_costs": round(fair, 4),
        "contributed_capital": round(capital, 2) if capital else capital,
        "recorded_cost_drag": recorded_drag,
        "fair_cost_drag": fair_drag,
        "cost_drag_relief": drag_relief,
        "note": (
            "Relief is estimated friction only — does not rebuild fills or excess vs ^FTSE. "
            "Add relief to a previously cost-penalised total return for a first-order view."
        ),
        "sample_trades": rows[:12],
    }


def assess_fund_payload_under_fair_costs(
    fund_payload: dict[str, Any],
    *,
    market_id: str | None,
) -> dict[str, Any]:
    """Assess a stored ``automated_fund.json`` payload under fair costs."""
    trades = list(fund_payload.get("trades") or [])
    capital = float(fund_payload.get("contributed_capital") or 0.0)
    if capital <= 0:
        cfg = fund_payload.get("config") or {}
        capital = float(cfg.get("initial_cash") or 0.0)
    assessment = assess_trades_under_fair_costs(
        trades,
        market_id=market_id,
        contributed_capital=capital,
    )
    cfg = fund_payload.get("config") or {}
    assessment["recorded_config"] = {
        "trade_cost_pct": cfg.get("trade_cost_pct"),
        "buy_cost_pct": cfg.get("buy_cost_pct"),
        "sell_cost_pct": cfg.get("sell_cost_pct"),
    }
    return assessment


def assess_paper_tracks_under_fair_costs(
    paper_root: Path,
    *,
    market_id: str | None = None,
    track_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Recompute friction for learning-track funds under a paper automation root.

    Does **not** rewrite live configs — assessment / shadow view only.
    """
    from value_investor.paper_automation import FUND_FILENAME, learning_track_dirs

    paper_root = Path(paper_root)
    mid = normalize_market_id(market_id)
    dirs = learning_track_dirs(paper_root)
    selected = track_ids or list(dirs.keys())
    tracks: dict[str, Any] = {}
    for track_id in selected:
        track_dir = dirs.get(track_id) or (paper_root / track_id)
        fund_path = track_dir / FUND_FILENAME
        if not fund_path.exists():
            tracks[track_id] = {"ok": False, "reason": f"missing {FUND_FILENAME}"}
            continue
        try:
            payload = json.loads(fund_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            tracks[track_id] = {"ok": False, "reason": str(exc)}
            continue
        if not isinstance(payload, dict):
            tracks[track_id] = {"ok": False, "reason": "invalid fund payload"}
            continue
        row = assess_fund_payload_under_fair_costs(payload, market_id=mid)
        row["ok"] = True
        row["fund_path"] = str(fund_path)
        tracks[track_id] = row
    return {
        "paper_root": str(paper_root),
        "market_id": mid,
        "assumptions": costs_for_market(mid).to_dict(),
        "tracks": tracks,
        "note": (
            "Live FTSE books keep the 3% stress config unless explicitly changed. "
            "Use this assessment to compare performance under fair T212-shaped friction."
        ),
    }
