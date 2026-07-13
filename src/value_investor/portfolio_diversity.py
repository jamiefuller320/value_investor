"""Diversification advice for actioned holdings and screen candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_TARGET_SECTOR_CAP = 0.30
DEFAULT_MAX_POSITIONS = 8
DEFAULT_MIN_CANDIDATES = 3


@dataclass
class PortfolioHolding:
    ticker: str
    sector: str | None = None
    weight: float = 0.0
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "sector": self.sector,
            "weight": round(self.weight, 4),
        }


@dataclass
class CandidatePick:
    ticker: str
    name: str
    sector: str | None
    signal: str
    conviction_score: float
    already_held: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "sector": self.sector,
            "signal": self.signal,
            "conviction_score": round(self.conviction_score, 4),
            "already_held": self.already_held,
        }


@dataclass
class RankedCandidate:
    ticker: str
    name: str
    sector: str | None
    signal: str
    conviction_score: float
    diversity_score: float
    combined_score: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "sector": self.sector,
            "signal": self.signal,
            "conviction_score": round(self.conviction_score, 4),
            "diversity_score": round(self.diversity_score, 4),
            "combined_score": round(self.combined_score, 4),
            "rationale": self.rationale,
        }


@dataclass
class DiversificationAdvice:
    holdings_count: int
    sector_weights: dict[str, float]
    concentration_warnings: list[str] = field(default_factory=list)
    underweight_sectors: list[str] = field(default_factory=list)
    ranked_candidates: list[RankedCandidate] = field(default_factory=list)
    summary: str = ""
    target_sector_cap: float = DEFAULT_TARGET_SECTOR_CAP
    max_positions: int = DEFAULT_MAX_POSITIONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "holdings_count": self.holdings_count,
            "sector_weights": {k: round(v, 4) for k, v in self.sector_weights.items()},
            "concentration_warnings": self.concentration_warnings,
            "underweight_sectors": self.underweight_sectors,
            "ranked_candidates": [c.to_dict() for c in self.ranked_candidates],
            "summary": self.summary,
            "target_sector_cap": self.target_sector_cap,
            "max_positions": self.max_positions,
        }


def _normalize_weights(holdings: list[PortfolioHolding]) -> list[PortfolioHolding]:
    if not holdings:
        return []
    positive = [h for h in holdings if h.weight > 0]
    if not positive:
        equal = 1.0 / len(holdings)
        return [
            PortfolioHolding(ticker=h.ticker, sector=h.sector, weight=equal, name=h.name)
            for h in holdings
        ]
    total = sum(h.weight for h in positive)
    if total <= 0:
        return positive
    return [
        PortfolioHolding(
            ticker=h.ticker,
            sector=h.sector,
            weight=h.weight / total,
            name=h.name,
        )
        for h in positive
    ]


def sector_weights(holdings: list[PortfolioHolding]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for holding in _normalize_weights(holdings):
        sector = holding.sector or "Unknown"
        weights[sector] = weights.get(sector, 0.0) + holding.weight
    return dict(sorted(weights.items(), key=lambda item: item[1], reverse=True))


def _diversity_score(sector: str | None, weights: dict[str, float], *, sector_cap: float) -> float:
    current = weights.get(sector or "Unknown", 0.0)
    if current >= sector_cap:
        return 0.0
    # Prefer empty/underweight sectors; score falls as sector fills toward the cap.
    return max(0.0, 1.0 - (current / sector_cap))


def advise_diversification(
    holdings: list[PortfolioHolding],
    candidates: list[CandidatePick],
    *,
    sector_cap: float = DEFAULT_TARGET_SECTOR_CAP,
    max_positions: int = DEFAULT_MAX_POSITIONS,
    conviction_weight: float = 0.55,
    diversity_weight: float = 0.45,
    top_n: int = 5,
) -> DiversificationAdvice:
    """
    Rank buy-tier candidates that improve sector diversification versus current holdings.

    Equal-weight holdings are assumed when weights are missing/zero. Already-held
    tickers are excluded from ranked suggestions. Hold/avoid candidates are ignored
    by callers (pass only actionable names).
    """
    normalized = _normalize_weights(holdings)
    weights = sector_weights(normalized)
    held_tickers = {h.ticker for h in normalized}

    warnings: list[str] = []
    if len(normalized) >= max_positions:
        warnings.append(
            f"Open book already has {len(normalized)} names (soft cap {max_positions}). "
            "Prefer adding only when replacing or trimming concentrated sectors."
        )
    for sector, weight in weights.items():
        if weight >= sector_cap:
            warnings.append(
                f"{sector} is {weight:.0%} of the book (cap {sector_cap:.0%}). "
                "Favour other sectors for the next action."
            )

    underweight = [
        sector
        for sector, weight in sorted(weights.items(), key=lambda item: item[1])
        if weight < sector_cap * 0.5
    ]
    # Also surface sectors present in candidates but absent from holdings.
    candidate_sectors = {
        (c.sector or "Unknown") for c in candidates if c.ticker not in held_tickers
    }
    for sector in sorted(candidate_sectors):
        if sector not in weights and sector not in underweight:
            underweight.append(sector)

    ranked: list[RankedCandidate] = []
    for candidate in candidates:
        if candidate.ticker in held_tickers:
            continue
        if candidate.signal not in ("strong_buy", "buy"):
            continue
        sector = candidate.sector or "Unknown"
        diversity = _diversity_score(sector, weights, sector_cap=sector_cap)
        conviction = max(0.0, min(1.0, candidate.conviction_score))
        combined = (conviction_weight * conviction) + (diversity_weight * diversity)
        if diversity >= 0.75:
            rationale = f"Adds {sector} exposure while the book is light there"
        elif diversity >= 0.35:
            rationale = f"Acceptable {sector} add — sector not yet at the {sector_cap:.0%} cap"
        elif diversity > 0:
            rationale = f"Increases {sector} toward the concentration cap — size carefully"
        else:
            rationale = f"Would deepen an already heavy {sector} sleeve — deprioritise"
        ranked.append(
            RankedCandidate(
                ticker=candidate.ticker,
                name=candidate.name,
                sector=candidate.sector,
                signal=candidate.signal,
                conviction_score=conviction,
                diversity_score=diversity,
                combined_score=combined,
                rationale=rationale,
            )
        )

    ranked.sort(key=lambda item: (item.combined_score, item.conviction_score), reverse=True)
    ranked = ranked[:top_n]

    if not normalized:
        summary = (
            "No actioned holdings yet. Log fills from Strong buys / Buys, then use this "
            "panel to prefer underweight sectors on the next recommendation."
        )
    elif warnings and ranked:
        summary = (
            f"{len(normalized)} open name(s). Address concentration first: "
            f"next best diversified candidate is {ranked[0].name} ({ranked[0].ticker})."
        )
    elif ranked:
        summary = (
            f"{len(normalized)} open name(s) across {len(weights)} sector(s). "
            f"Next diversified pick: {ranked[0].name} ({ranked[0].ticker}) — "
            f"{ranked[0].rationale}."
        )
    else:
        summary = (
            f"{len(normalized)} open name(s). No unused buy-tier candidates available "
            "to improve diversification this week."
        )

    return DiversificationAdvice(
        holdings_count=len(normalized),
        sector_weights=weights,
        concentration_warnings=warnings,
        underweight_sectors=underweight[:6],
        ranked_candidates=ranked,
        summary=summary,
        target_sector_cap=sector_cap,
        max_positions=max_positions,
    )


def holdings_from_actions(
    actions: list[dict[str, Any]],
    *,
    reports_by_ticker: dict[str, dict[str, Any]] | None = None,
    execution_mode: str | None = None,
) -> list[PortfolioHolding]:
    """
    Build equal-weight (or quantity-weighted) holdings from open action log rows.

    Expected action keys: ticker, status, sector?, name?, quantity?, allocation_pct?,
    execution_mode? ("simulated" | "live"; missing treated as live).
    When execution_mode is set, only matching rows are included.
    """
    reports_by_ticker = reports_by_ticker or {}
    open_actions = [
        action
        for action in actions
        if str(action.get("status") or "open").lower() == "open"
        and action.get("ticker")
        and (
            execution_mode is None
            or normalize_execution_mode(action.get("execution_mode")) == execution_mode
        )
    ]
    if not open_actions:
        return []

    # Collapse multiple legs for the same ticker into one holding.
    by_ticker: dict[str, dict[str, Any]] = {}
    for action in open_actions:
        ticker = str(action["ticker"])
        report = reports_by_ticker.get(ticker) or {}
        entry = by_ticker.setdefault(
            ticker,
            {
                "ticker": ticker,
                "name": action.get("name") or report.get("name"),
                "sector": action.get("sector") or report.get("sector"),
                "weight": 0.0,
            },
        )
        qty = action.get("quantity")
        alloc = action.get("allocation_pct")
        if qty is not None and float(qty) > 0:
            entry["weight"] += float(qty)
        elif alloc is not None and float(alloc) > 0:
            entry["weight"] += float(alloc)
        else:
            entry["weight"] += 1.0

    return [
        PortfolioHolding(
            ticker=item["ticker"],
            name=item.get("name"),
            sector=item.get("sector"),
            weight=float(item["weight"]),
        )
        for item in by_ticker.values()
    ]


def normalize_execution_mode(value: Any) -> str:
    mode = str(value or "live").strip().lower()
    return "simulated" if mode == "simulated" else "live"


def build_simulated_action(
    report: dict[str, Any],
    *,
    run_at: str | None = None,
    acted_at: str | None = None,
    leg: str = "core",
    action_id: str | None = None,
) -> dict[str, Any]:
    """Build one simulated open action prefilled from a report trade_plan."""
    plan = report.get("trade_plan") or {}
    if leg == "tactical":
        order_type = plan.get("tactical_order") or "limit"
        limit_price = plan.get("tactical_limit")
        allocation_pct = plan.get("tactical_allocation_pct")
    elif leg == "combined":
        order_type = plan.get("core_order") or "limit"
        limit_price = plan.get("core_limit")
        if limit_price is None:
            limit_price = plan.get("tactical_limit")
        allocation_pct = 1.0
    else:
        order_type = plan.get("core_order") or "market"
        limit_price = plan.get("core_limit")
        allocation_pct = plan.get("core_allocation_pct")

    return {
        "id": action_id or f"sim-{report.get('ticker')}-{leg}",
        "ticker": report.get("ticker"),
        "name": report.get("name"),
        "sector": report.get("sector"),
        "signal_at_action": report.get("signal"),
        "run_at": run_at,
        "acted_at": acted_at,
        "status": "open",
        "side": "buy",
        "execution_mode": "simulated",
        "leg": leg,
        "order_type": order_type,
        "limit_price": limit_price,
        "stop_loss": plan.get("tactical_stop_loss"),
        "take_profit": plan.get("tactical_take_profit"),
        "allocation_pct": allocation_pct,
        "quantity": None,
        "notes": "Seeded simulated buy from current screen",
        "suggested": dict(plan) if plan else {},
    }


def seed_simulated_buys(
    reports: list[dict[str, Any]],
    *,
    existing_actions: list[dict[str, Any]] | None = None,
    run_at: str | None = None,
    acted_at: str | None = None,
    max_names: int = 5,
    include_tactical: bool = True,
) -> list[dict[str, Any]]:
    """
    Create simulated open buys from current buy-tier recommendations.

    Prefers diversification ranking against the existing simulated book, then
    fills remaining slots by conviction. Skips tickers already open in simulated mode.
    """
    existing_actions = existing_actions or []
    holdings = holdings_from_actions(existing_actions, execution_mode="simulated")
    held = {h.ticker for h in holdings}
    candidates = candidates_from_reports(reports)
    advice = advise_diversification(holdings, candidates, top_n=max_names * 2)
    ordered_tickers = [c.ticker for c in advice.ranked_candidates]
    # Append any remaining buy-tier names by conviction.
    remaining = sorted(
        (c for c in candidates if c.ticker not in ordered_tickers),
        key=lambda c: c.conviction_score,
        reverse=True,
    )
    ordered_tickers.extend(c.ticker for c in remaining)

    by_ticker = {str(r["ticker"]): r for r in reports if r.get("ticker")}
    seeded: list[dict[str, Any]] = []
    added = 0
    for ticker in ordered_tickers:
        if added >= max_names:
            break
        if ticker in held:
            continue
        report = by_ticker.get(ticker)
        if not report or report.get("signal") not in ("strong_buy", "buy"):
            continue
        seeded.append(
            build_simulated_action(
                report,
                run_at=run_at,
                acted_at=acted_at,
                leg="core",
                action_id=f"sim-{ticker}-core-{added}",
            )
        )
        if include_tactical and (report.get("trade_plan") or {}).get("tactical_limit") is not None:
            seeded.append(
                build_simulated_action(
                    report,
                    run_at=run_at,
                    acted_at=acted_at,
                    leg="tactical",
                    action_id=f"sim-{ticker}-tactical-{added}",
                )
            )
        held.add(ticker)
        added += 1
    return seeded


def candidates_from_reports(reports: list[dict[str, Any]]) -> list[CandidatePick]:
    return [
        CandidatePick(
            ticker=str(report["ticker"]),
            name=str(report.get("name") or report["ticker"]),
            sector=report.get("sector"),
            signal=str(report.get("signal") or ""),
            conviction_score=float(report.get("conviction_score") or 0),
            already_held=False,
        )
        for report in reports
        if report.get("ticker") and report.get("signal") in ("strong_buy", "buy")
    ]
