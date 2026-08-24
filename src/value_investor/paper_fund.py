"""Cash-backed paper funds with deposits, flexible sizing, and parallel strategies."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import uuid4

from value_investor.research.verdict import coerce_research_verdict

SizingMode = Literal["shares", "cash", "pct_nav"]
StrategyMode = Literal["manual", "technical", "automated"]

BUY_SIGNALS = frozenset({"strong_buy", "buy"})
DEFAULT_TRADE_COST_PCT = 0.03
DEFAULT_MAX_POSITIONS = 5
DEFAULT_INITIAL_CASH = 1000.0
DEFAULT_EXIT_CONFIRM_SCREENS = 2
DEFAULT_REENTRY_COOLDOWN_SCREENS = 1
DEFAULT_MIN_REBALANCE_NOTIONAL_GBP = 10.0
REBALANCE_TRIM_TOLERANCE = 1.02
REBALANCE_CASH_FLOOR = 0.01
STRATEGY_MODES: tuple[StrategyMode, ...] = ("manual", "technical", "automated")
SIZING_MODES: tuple[SizingMode, ...] = ("shares", "cash", "pct_nav")

STRATEGY_LABELS = {
    "manual": "Immediate buy/sell",
    "technical": "Follow technical cues",
    "automated": "Automated stock picking",
}


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_date(value: str | date | datetime | None) -> date:
    if value is None:
        return datetime.now(UTC).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text[:10])


def _month_index(value: date) -> int:
    return value.year * 12 + value.month


def create_fund_id() -> str:
    return str(uuid4())


@dataclass
class RebalanceState:
    """Per-fund churn guards for automated equal-weight rebalancing."""

    exit_streak: dict[str, int] = field(default_factory=dict)
    reentry_cooldown: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_streak": dict(self.exit_streak),
            "reentry_cooldown": dict(self.reentry_cooldown),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RebalanceState:
        raw = data or {}
        return cls(
            exit_streak={str(k): int(v) for k, v in (raw.get("exit_streak") or {}).items()},
            reentry_cooldown={
                str(k): int(v) for k, v in (raw.get("reentry_cooldown") or {}).items()
            },
        )


@dataclass
class PaperFundConfig:
    name: str
    mode: StrategyMode = "manual"
    initial_cash: float = DEFAULT_INITIAL_CASH
    monthly_deposit: float = 0.0
    trade_cost_pct: float = DEFAULT_TRADE_COST_PCT
    max_positions: int = DEFAULT_MAX_POSITIONS
    reporting_currency: str = "GBP"
    hedge_assumption: str = "none"
    id: str = field(default_factory=create_fund_id)
    created_at: str = field(default_factory=_utcnow_iso)

    def __post_init__(self) -> None:
        if self.mode not in STRATEGY_MODES:
            raise ValueError(f"Unknown strategy mode: {self.mode}")
        if self.initial_cash < 0:
            raise ValueError("initial_cash must be >= 0")
        if self.monthly_deposit < 0:
            raise ValueError("monthly_deposit must be >= 0")
        if self.trade_cost_pct < 0:
            raise ValueError("trade_cost_pct must be >= 0")
        if self.max_positions < 1:
            raise ValueError("max_positions must be >= 1")
        self.reporting_currency = str(self.reporting_currency or "GBP").upper()
        self.hedge_assumption = str(self.hedge_assumption or "none").lower()


@dataclass
class Position:
    ticker: str
    shares: float
    avg_cost: float
    name: str = ""
    sector: str = ""
    currency: str = "GBP"
    stop_loss: float | None = None
    take_profit: float | None = None
    opened_at: str = field(default_factory=_utcnow_iso)
    momentum_grace: bool = False
    grace_started_at: str | None = None
    grace_entry_stop: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "ticker": self.ticker,
            "shares": round(self.shares, 6),
            "avg_cost": round(self.avg_cost, 4),
            "name": self.name,
            "sector": self.sector,
            "currency": self.currency,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "opened_at": self.opened_at,
        }
        if self.momentum_grace:
            payload["momentum_grace"] = True
        if self.grace_started_at:
            payload["grace_started_at"] = self.grace_started_at
        if self.grace_entry_stop is not None:
            payload["grace_entry_stop"] = self.grace_entry_stop
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Position:
        return cls(
            ticker=str(data["ticker"]),
            shares=float(data["shares"]),
            avg_cost=float(data.get("avg_cost") or 0),
            name=str(data.get("name") or ""),
            sector=str(data.get("sector") or ""),
            currency=str(data.get("currency") or "GBP").upper(),
            stop_loss=_optional_float(data.get("stop_loss")),
            take_profit=_optional_float(data.get("take_profit")),
            opened_at=str(data.get("opened_at") or _utcnow_iso()),
            momentum_grace=bool(data.get("momentum_grace", False)),
            grace_started_at=data.get("grace_started_at"),
            grace_entry_stop=_optional_float(data.get("grace_entry_stop")),
        )


@dataclass
class PaperTrade:
    id: str
    fund_id: str
    acted_at: str
    ticker: str
    side: str
    sizing_mode: SizingMode
    shares: float
    price: float
    gross: float
    cost: float
    net_cash: float
    note: str = ""
    name: str = ""
    avg_cost_at_exit: float | None = None
    momentum_grace_at_exit: bool = False
    grace_started_at_at_exit: str | None = None
    position_closed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "fund_id": self.fund_id,
            "acted_at": self.acted_at,
            "ticker": self.ticker,
            "side": self.side,
            "sizing_mode": self.sizing_mode,
            "shares": round(self.shares, 6),
            "price": round(self.price, 4),
            "gross": round(self.gross, 2),
            "cost": round(self.cost, 2),
            "net_cash": round(self.net_cash, 2),
            "note": self.note,
            "name": self.name,
        }
        if self.avg_cost_at_exit is not None:
            payload["avg_cost_at_exit"] = round(self.avg_cost_at_exit, 4)
        if self.momentum_grace_at_exit:
            payload["momentum_grace_at_exit"] = True
        if self.grace_started_at_at_exit:
            payload["grace_started_at_at_exit"] = self.grace_started_at_at_exit
        if self.position_closed:
            payload["position_closed"] = True
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperTrade:
        return cls(
            id=str(data.get("id") or create_fund_id()),
            fund_id=str(data["fund_id"]),
            acted_at=str(data["acted_at"]),
            ticker=str(data["ticker"]),
            side=str(data["side"]),
            sizing_mode=str(data.get("sizing_mode") or "cash"),  # type: ignore[arg-type]
            shares=float(data["shares"]),
            price=float(data["price"]),
            gross=float(data["gross"]),
            cost=float(data["cost"]),
            net_cash=float(data["net_cash"]),
            note=str(data.get("note") or ""),
            name=str(data.get("name") or ""),
            avg_cost_at_exit=_optional_float(data.get("avg_cost_at_exit")),
            momentum_grace_at_exit=bool(data.get("momentum_grace_at_exit", False)),
            grace_started_at_at_exit=data.get("grace_started_at_at_exit"),
            position_closed=bool(data.get("position_closed", False)),
        )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def portfolio_value(cash: float, holdings: dict[str, Position], prices: dict[str, float]) -> float:
    equity = 0.0
    for ticker, position in holdings.items():
        price = prices.get(ticker)
        if price is None or price <= 0:
            # Fall back to average cost when a live mark is missing.
            price = position.avg_cost
        if price and price > 0:
            equity += position.shares * price
    return cash + equity


def resolve_order_shares(
    *,
    sizing_mode: SizingMode,
    amount: float,
    price: float,
    nav: float,
    cash: float,
    trade_cost_pct: float,
    side: str,
) -> float:
    """Convert shares / cash / % NAV into a share quantity before cash checks."""
    if amount is None or amount <= 0:
        raise ValueError("Order amount must be positive")
    if price <= 0:
        raise ValueError("Price must be positive")
    if sizing_mode not in SIZING_MODES:
        raise ValueError(f"Unknown sizing mode: {sizing_mode}")

    if sizing_mode == "shares":
        shares = float(amount)
    elif sizing_mode == "cash":
        if side == "buy":
            gross = float(amount) / (1 + trade_cost_pct)
        else:
            # Sell for a target net cash after costs.
            gross = float(amount) / (1 - trade_cost_pct) if trade_cost_pct < 1 else float(amount)
        shares = gross / price
    else:  # pct_nav
        if amount > 1.0000001:
            # Accept whole percents (e.g. 10 == 10%).
            amount = amount / 100.0
        notional = nav * float(amount)
        if side == "buy":
            gross = notional / (1 + trade_cost_pct)
        else:
            gross = notional / (1 - trade_cost_pct) if trade_cost_pct < 1 else notional
        shares = gross / price

    if side == "buy":
        max_gross = cash / (1 + trade_cost_pct)
        max_shares = max_gross / price if price > 0 else 0.0
        shares = min(shares, max_shares)
    return max(0.0, shares)


@dataclass
class PaperFund:
    config: PaperFundConfig
    cash: float = 0.0
    contributed_capital: float = 0.0
    deposits_applied: int = 0
    holdings: dict[str, Position] = field(default_factory=dict)
    trades: list[PaperTrade] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    last_mark_at: str | None = None
    rebalance_state: RebalanceState = field(default_factory=RebalanceState)

    @classmethod
    def create(cls, config: PaperFundConfig) -> PaperFund:
        fund = cls(
            config=config,
            cash=float(config.initial_cash),
            contributed_capital=float(config.initial_cash),
        )
        fund.record_mark(prices={}, acted_at=config.created_at, note="Fund opened")
        return fund

    def apply_deposits_to(self, as_of: str | date | datetime | None = None) -> float:
        """Credit any missing monthly deposits up to as_of (exclusive of start month)."""
        if self.config.monthly_deposit <= 0:
            return 0.0
        created = _parse_date(self.config.created_at)
        target = _parse_date(as_of)
        if target < created:
            return 0.0
        expected = max(0, _month_index(target) - _month_index(created))
        missing = expected - self.deposits_applied
        if missing <= 0:
            return 0.0
        total = missing * self.config.monthly_deposit
        self.cash += total
        self.contributed_capital += total
        self.deposits_applied += missing
        return total

    def nav(self, prices: dict[str, float]) -> float:
        return portfolio_value(self.cash, self.holdings, prices)

    def nav_reporting(
        self,
        prices: dict[str, float],
        *,
        price_currencies: dict[str, str] | None = None,
        rates: dict[str, float] | None = None,
    ) -> tuple[float, dict[str, Any]]:
        """
        NAV in ``config.reporting_currency``.

        Local prices are converted at spot (unhedged). Cash is already in the
        reporting currency.
        """
        from value_investor.fx import convert_prices_to_reporting, currency_for_ticker

        ccy_map = dict(price_currencies or {})
        for ticker, pos in self.holdings.items():
            ccy_map.setdefault(ticker, pos.currency or currency_for_ticker(ticker))
        converted, meta = convert_prices_to_reporting(
            prices,
            price_currencies=ccy_map,
            reporting_currency=self.config.reporting_currency,
            rates=rates,
        )
        return self.nav(converted), meta

    def record_mark(
        self,
        prices: dict[str, float],
        *,
        acted_at: str | None = None,
        note: str = "",
        price_currencies: dict[str, str] | None = None,
        rates: dict[str, float] | None = None,
        include_macro_note: bool = False,
        macro_market: str | None = None,
    ) -> dict[str, Any]:
        when = acted_at or _utcnow_iso()
        value, fx_meta = self.nav_reporting(
            prices,
            price_currencies=price_currencies,
            rates=rates,
        )
        mark_note = note
        if include_macro_note:
            try:
                from value_investor.macro_context import macro_regime_note

                regime = macro_regime_note(macro_market)
                mark_note = f"{note}; {regime}".strip("; ")
            except Exception:  # noqa: BLE001
                pass
        point = {
            "at": when,
            "portfolio_value": round(value, 2),
            "cash": round(self.cash, 2),
            "contributed_capital": round(self.contributed_capital, 2),
            "positions": len(self.holdings),
            "reporting_currency": self.config.reporting_currency,
            "hedge_assumption": self.config.hedge_assumption,
            "fx": {
                "rates": fx_meta.get("rates"),
                "issues": fx_meta.get("conversion_issues") or [],
            },
            "note": mark_note,
        }
        self.equity_curve.append(point)
        self.last_mark_at = when
        return point

    def performance(self, prices: dict[str, float]) -> dict[str, Any]:
        value = self.nav(prices)
        contributed = self.contributed_capital or 0.0
        gain = value - contributed
        total_return = (gain / contributed) if contributed > 0 else 0.0
        cost_basis = 0.0
        market_value = 0.0
        for ticker, pos in self.holdings.items():
            mark = prices.get(ticker)
            if mark is None or mark <= 0:
                mark = pos.avg_cost
            if mark and mark > 0:
                market_value += pos.shares * mark
            if pos.avg_cost and pos.avg_cost > 0:
                cost_basis += pos.shares * pos.avg_cost
        unrealized_pnl = market_value - cost_basis
        unrealized_pnl_pct = (unrealized_pnl / cost_basis) if cost_basis > 0 else 0.0
        return {
            "portfolio_value": round(value, 2),
            "cash": round(self.cash, 2),
            "invested_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 4),
            "contributed_capital": round(contributed, 2),
            "gain": round(gain, 2),
            "total_return": round(total_return, 4),
            "positions": len(self.holdings),
            "trade_count": len(self.trades),
            "deposits_applied": self.deposits_applied,
        }

    def buy(
        self,
        *,
        ticker: str,
        price: float,
        sizing_mode: SizingMode,
        amount: float,
        name: str = "",
        sector: str = "",
        stop_loss: float | None = None,
        take_profit: float | None = None,
        note: str = "",
        acted_at: str | None = None,
        prices_for_nav: dict[str, float] | None = None,
    ) -> PaperTrade:
        when = acted_at or _utcnow_iso()
        prices = dict(prices_for_nav or {})
        prices.setdefault(ticker, price)
        nav = self.nav(prices)
        shares = resolve_order_shares(
            sizing_mode=sizing_mode,
            amount=amount,
            price=price,
            nav=nav,
            cash=self.cash,
            trade_cost_pct=self.config.trade_cost_pct,
            side="buy",
        )
        if shares <= 1e-12:
            raise ValueError("Insufficient cash for this buy")
        if ticker not in self.holdings and len(self.holdings) >= self.config.max_positions:
            raise ValueError(
                f"Max positions ({self.config.max_positions}) reached; sell before buying a new name"
            )

        gross = shares * price
        cost = gross * self.config.trade_cost_pct
        spent = gross + cost
        if spent > self.cash + 1e-9:
            raise ValueError("Insufficient cash for this buy")

        self.cash -= spent
        existing = self.holdings.get(ticker)
        if existing:
            total_shares = existing.shares + shares
            existing.avg_cost = (
                (existing.avg_cost * existing.shares) + (price * shares)
            ) / total_shares
            existing.shares = total_shares
            if stop_loss is not None:
                existing.stop_loss = stop_loss
            if take_profit is not None:
                existing.take_profit = take_profit
            if name:
                existing.name = name
            if sector:
                existing.sector = sector
        else:
            from value_investor.fx import currency_for_ticker

            self.holdings[ticker] = Position(
                ticker=ticker,
                shares=shares,
                avg_cost=price,
                name=name or ticker,
                sector=sector or "",
                currency=currency_for_ticker(ticker),
                stop_loss=stop_loss,
                take_profit=take_profit,
                opened_at=when,
            )

        trade = PaperTrade(
            id=create_fund_id(),
            fund_id=self.config.id,
            acted_at=when,
            ticker=ticker,
            side="buy",
            sizing_mode=sizing_mode,
            shares=shares,
            price=price,
            gross=gross,
            cost=cost,
            net_cash=-spent,
            note=note,
            name=name or ticker,
        )
        self.trades.append(trade)
        return trade

    def sell(
        self,
        *,
        ticker: str,
        price: float,
        sizing_mode: SizingMode,
        amount: float,
        note: str = "",
        acted_at: str | None = None,
        prices_for_nav: dict[str, float] | None = None,
    ) -> PaperTrade:
        when = acted_at or _utcnow_iso()
        position = self.holdings.get(ticker)
        if not position or position.shares <= 0:
            raise ValueError(f"No open position in {ticker}")
        prices = dict(prices_for_nav or {})
        prices.setdefault(ticker, price)
        nav = self.nav(prices)
        shares = resolve_order_shares(
            sizing_mode=sizing_mode,
            amount=amount,
            price=price,
            nav=nav,
            cash=self.cash,
            trade_cost_pct=self.config.trade_cost_pct,
            side="sell",
        )
        shares = min(shares, position.shares)
        if shares <= 1e-12:
            raise ValueError("Sell quantity is zero")

        gross = shares * price
        cost = gross * self.config.trade_cost_pct
        proceeds = gross - cost
        self.cash += proceeds
        avg_cost_at_exit = float(position.avg_cost)
        momentum_grace_at_exit = bool(position.momentum_grace)
        grace_started_at_at_exit = position.grace_started_at
        position_closed = (position.shares - shares) <= 1e-9
        position.shares -= shares
        if position_closed:
            del self.holdings[ticker]

        trade = PaperTrade(
            id=create_fund_id(),
            fund_id=self.config.id,
            acted_at=when,
            ticker=ticker,
            side="sell",
            sizing_mode=sizing_mode,
            shares=shares,
            price=price,
            gross=gross,
            cost=cost,
            net_cash=proceeds,
            note=note,
            name=position.name if position else ticker,
            avg_cost_at_exit=avg_cost_at_exit,
            momentum_grace_at_exit=momentum_grace_at_exit,
            grace_started_at_at_exit=grace_started_at_at_exit,
            position_closed=position_closed,
        )
        self.trades.append(trade)
        return trade

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": asdict(self.config),
            "cash": round(self.cash, 2),
            "contributed_capital": round(self.contributed_capital, 2),
            "deposits_applied": self.deposits_applied,
            "holdings": {k: v.to_dict() for k, v in self.holdings.items()},
            "trades": [t.to_dict() for t in self.trades],
            "equity_curve": list(self.equity_curve),
            "last_mark_at": self.last_mark_at,
            "rebalance_state": self.rebalance_state.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperFund:
        cfg = data.get("config") or {}
        config = PaperFundConfig(
            id=str(cfg.get("id") or create_fund_id()),
            name=str(cfg.get("name") or "Untitled"),
            mode=str(cfg.get("mode") or "manual"),  # type: ignore[arg-type]
            initial_cash=float(cfg.get("initial_cash") or DEFAULT_INITIAL_CASH),
            monthly_deposit=float(cfg.get("monthly_deposit") or 0),
            trade_cost_pct=float(cfg.get("trade_cost_pct") or DEFAULT_TRADE_COST_PCT),
            max_positions=int(cfg.get("max_positions") or DEFAULT_MAX_POSITIONS),
            reporting_currency=str(cfg.get("reporting_currency") or "GBP"),
            hedge_assumption=str(cfg.get("hedge_assumption") or "none"),
            created_at=str(cfg.get("created_at") or _utcnow_iso()),
        )
        holdings = {str(k): Position.from_dict(v) for k, v in (data.get("holdings") or {}).items()}
        trades = [PaperTrade.from_dict(t) for t in data.get("trades") or []]
        return cls(
            config=config,
            cash=float(data.get("cash") or 0),
            contributed_capital=float(data.get("contributed_capital") or config.initial_cash),
            deposits_applied=int(data.get("deposits_applied") or 0),
            holdings=holdings,
            trades=trades,
            equity_curve=list(data.get("equity_curve") or []),
            last_mark_at=data.get("last_mark_at"),
            rebalance_state=RebalanceState.from_dict(data.get("rebalance_state")),
        )


@dataclass
class PaperFundBook:
    """Collection of parallel paper funds sharing the same capital template."""

    funds: list[PaperFund] = field(default_factory=list)
    active_fund_id: str | None = None

    def get(self, fund_id: str) -> PaperFund | None:
        for fund in self.funds:
            if fund.config.id == fund_id:
                return fund
        return None

    def active(self) -> PaperFund | None:
        if self.active_fund_id:
            found = self.get(self.active_fund_id)
            if found:
                return found
        return self.funds[0] if self.funds else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "active_fund_id": self.active_fund_id,
            "funds": [f.to_dict() for f in self.funds],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperFundBook:
        funds = [PaperFund.from_dict(item) for item in data.get("funds") or []]
        active = data.get("active_fund_id")
        if active is None and funds:
            active = funds[0].config.id
        return cls(funds=funds, active_fund_id=active)


def create_parallel_book(
    *,
    initial_cash: float = DEFAULT_INITIAL_CASH,
    monthly_deposit: float = 0.0,
    trade_cost_pct: float = DEFAULT_TRADE_COST_PCT,
    max_positions: int = DEFAULT_MAX_POSITIONS,
    created_at: str | None = None,
) -> PaperFundBook:
    """Create the three default parallel strategy funds with shared capital settings."""
    when = created_at or _utcnow_iso()
    funds: list[PaperFund] = []
    for mode in STRATEGY_MODES:
        config = PaperFundConfig(
            name=STRATEGY_LABELS[mode],
            mode=mode,
            initial_cash=initial_cash,
            monthly_deposit=monthly_deposit,
            trade_cost_pct=trade_cost_pct,
            max_positions=max_positions,
            created_at=when,
        )
        funds.append(PaperFund.create(config))
    return PaperFundBook(funds=funds, active_fund_id=funds[0].config.id)


def _candidate_price(candidate: dict[str, Any]) -> float | None:
    for key in ("price", "last", "close", "mark"):
        value = candidate.get(key)
        if value is not None and float(value) > 0:
            return float(value)
    plan = candidate.get("trade_plan") or {}
    for key in ("core_limit", "tactical_limit"):
        value = plan.get(key)
        if value is not None and float(value) > 0:
            return float(value)
    return None


def _candidate_screen_signal(
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


def _evaluate_momentum_grace_holdings(
    fund: PaperFund,
    candidates: list[dict[str, Any]],
    target_tickers: set[str],
    *,
    use_adjusted_signal: bool,
    acted_at: str,
    mutate: bool = True,
) -> tuple[set[str], list[dict[str, Any]]]:
    """Return tickers kept via momentum grace and planned grace transitions."""
    from value_investor.momentum_grace import evaluate_grace_holding

    by_ticker = {str(row.get("ticker")): row for row in candidates if row.get("ticker")}
    grace_kept: set[str] = set()
    transitions: list[dict[str, Any]] = []

    for ticker, position in fund.holdings.items():
        if ticker in target_tickers:
            if position.momentum_grace:
                transitions.append(
                    {
                        "ticker": ticker,
                        "action": "grace_clear",
                        "reason": "requalified on value screen",
                    }
                )
                if mutate:
                    position.momentum_grace = False
                    position.grace_started_at = None
                    position.grace_entry_stop = None
            continue

        row = by_ticker.get(ticker) or {"ticker": ticker, "signal": "hold"}
        mark = _candidate_price(row) or position.avg_cost
        decision = evaluate_grace_holding(
            row,
            signal=_candidate_screen_signal(row, use_adjusted_signal=use_adjusted_signal),
            avg_cost=position.avg_cost,
            mark=mark,
            momentum_grace=position.momentum_grace,
            grace_started_at=position.grace_started_at,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            grace_entry_stop=position.grace_entry_stop,
            as_of=acted_at,
        )
        if decision.keep:
            grace_kept.add(ticker)
            stop_loss = decision.stop_loss if decision.stop_loss is not None else position.stop_loss
            take_profit = (
                decision.take_profit if decision.take_profit is not None else position.take_profit
            )
            if mutate:
                if decision.enter_grace:
                    position.momentum_grace = True
                    position.grace_started_at = acted_at
                    position.grace_entry_stop = (
                        position.grace_entry_stop or position.stop_loss or position.avg_cost
                    )
                if decision.stop_loss is not None:
                    position.stop_loss = decision.stop_loss
                if decision.take_profit is not None:
                    position.take_profit = decision.take_profit
            transitions.append(
                {
                    "ticker": ticker,
                    "action": "grace_enter" if decision.enter_grace else "grace_hold",
                    "reason": decision.reason,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                }
            )
        else:
            if mutate and position.momentum_grace and decision.exit_grace:
                position.momentum_grace = False
                position.grace_started_at = None
                position.grace_entry_stop = None
            transitions.append(
                {
                    "ticker": ticker,
                    "action": "grace_exit" if decision.exit_grace else "sell",
                    "reason": decision.reason,
                }
            )
    return grace_kept, transitions


def tick_reentry_cooldowns(fund: PaperFund, *, skip_tickers: set[str] | None = None) -> None:
    """Advance re-entry cooldown counters once per rebalance pass."""
    state = fund.rebalance_state
    skip = set(skip_tickers or ())
    for ticker in list(state.reentry_cooldown):
        if ticker in skip:
            continue
        remaining = int(state.reentry_cooldown[ticker]) - 1
        if remaining <= 0:
            state.reentry_cooldown.pop(ticker, None)
        else:
            state.reentry_cooldown[ticker] = remaining


def reentry_blocked(fund: PaperFund, ticker: str) -> bool:
    return int(fund.rebalance_state.reentry_cooldown.get(ticker, 0)) > 0


def mark_reentry_cooldown(fund: PaperFund, ticker: str, screens: int) -> None:
    if screens > 0:
        fund.rebalance_state.reentry_cooldown[ticker] = int(screens)


def resolve_automated_holdings_to_exit(
    fund: PaperFund,
    *,
    target_tickers: set[str],
    grace_kept: set[str],
    exit_confirm_screens: int,
    mutate_state: bool = True,
    force_exit_tickers: set[str] | None = None,
) -> tuple[set[str], set[str]]:
    """
    Return (keep_tickers, full_exit_tickers).

    When ``exit_confirm_screens`` > 0, holdings must be outside the target set
    for that many consecutive rebalance passes before a full exit fires.
    ``force_exit_tickers`` bypass the hold buffer (e.g. momentum grace failures).
    """
    state = fund.rebalance_state
    forced = set(force_exit_tickers or ())
    buffer_held: set[str] = set()
    sell_tickers: set[str] = set()

    for ticker in fund.holdings:
        if ticker in target_tickers or ticker in grace_kept:
            if mutate_state:
                state.exit_streak.pop(ticker, None)
            continue

        if ticker in forced:
            sell_tickers.add(ticker)
            if mutate_state:
                state.exit_streak.pop(ticker, None)
            continue

        if exit_confirm_screens <= 0:
            sell_tickers.add(ticker)
            continue

        if mutate_state:
            streak = int(state.exit_streak.get(ticker, 0)) + 1
            state.exit_streak[ticker] = streak
        else:
            streak = int(state.exit_streak.get(ticker, 0)) + 1

        if streak >= exit_confirm_screens:
            sell_tickers.add(ticker)
            if mutate_state:
                state.exit_streak.pop(ticker, None)
        else:
            buffer_held.add(ticker)

    keep_tickers = set(target_tickers) | set(grace_kept) | buffer_held
    return keep_tickers, sell_tickers


def _rebalance_adjustment_worthwhile(gross_value: float, min_notional: float) -> bool:
    return gross_value >= float(min_notional)


def select_automated_targets(
    candidates: list[dict[str, Any]],
    *,
    max_positions: int,
    skip_timing_wait: bool = True,
    min_conviction: float = 0.0,
    sector_cap: float = 1.0,
    use_adjusted_signal: bool = False,
    require_research_accumulate: bool = False,
) -> list[dict[str, Any]]:
    """
    Rank buy-tier names by conviction, optionally skipping timing=wait.

    ``min_conviction`` drops weak names. ``sector_cap`` limits how many equal-weight
    sleeves can share one sector (count limit = max(1, floor(sector_cap * max_positions))).
    Pass ``sector_cap=1.0`` to disable the sector filter.

    When ``use_adjusted_signal`` is true, eligibility uses research overlay
    ``adjusted_signal`` when present (AI quasi-human gate). When
    ``require_research_accumulate`` is true, only names with
    ``research_verdict=accumulate`` are eligible.
    """
    ranked: list[tuple[float, dict[str, Any]]] = []
    floor = float(min_conviction or 0.0)
    for row in candidates:
        signal = str(row.get("signal") or "")
        if use_adjusted_signal:
            adjusted = row.get("adjusted_signal")
            if adjusted is not None and str(adjusted).strip():
                signal = str(adjusted)
        if signal not in BUY_SIGNALS:
            continue
        if require_research_accumulate:
            verdict = coerce_research_verdict(
                str(row.get("research_verdict"))
                if row.get("research_verdict") is not None
                else None
            )
            if verdict != "accumulate":
                continue
        if skip_timing_wait and row.get("timing_signal") == "wait":
            continue
        if _candidate_price(row) is None:
            continue
        conviction = float(row.get("conviction_score") or 0)
        if conviction < floor:
            continue
        ranked.append((conviction, row))
    ranked.sort(key=lambda item: item[0], reverse=True)

    cap = float(sector_cap) if sector_cap is not None else 1.0
    if cap >= 1.0 or max_positions < 1:
        return [row for _, row in ranked[:max_positions]]

    per_sector_limit = max(1, int(cap * max_positions + 1e-9))
    selected: list[dict[str, Any]] = []
    sector_counts: dict[str, int] = {}
    for _, row in ranked:
        if len(selected) >= max_positions:
            break
        sector = str(row.get("sector") or "").strip()
        # Missing sector data must not collapse into one synthetic bucket.
        if sector and sector_counts.get(sector, 0) >= per_sector_limit:
            continue
        selected.append(row)
        if sector:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
    return selected


def preview_automated_plan(
    fund: PaperFund,
    candidates: list[dict[str, Any]],
    *,
    skip_timing_wait: bool = True,
    min_conviction: float = 0.0,
    sector_cap: float = 1.0,
    use_adjusted_signal: bool = False,
    require_research_accumulate: bool = False,
    use_momentum_grace: bool = False,
    exit_confirm_screens: int = DEFAULT_EXIT_CONFIRM_SCREENS,
    reentry_cooldown_screens: int = DEFAULT_REENTRY_COOLDOWN_SCREENS,
    min_rebalance_notional_gbp: float = DEFAULT_MIN_REBALANCE_NOTIONAL_GBP,
) -> dict[str, Any]:
    """
    Dry-run the automated rebalance rules without mutating the fund.

    Returns a narrative-friendly plan: eligibility rules, target set, and
    anticipated sells / trims / buys with cash constraints noted.
    """
    if fund.config.mode != "automated":
        raise ValueError("Automated plan preview requires an automated fund")

    targets = select_automated_targets(
        candidates,
        max_positions=fund.config.max_positions,
        skip_timing_wait=skip_timing_wait,
        min_conviction=min_conviction,
        sector_cap=sector_cap,
        use_adjusted_signal=use_adjusted_signal,
        require_research_accumulate=require_research_accumulate,
    )
    target_tickers = {str(row["ticker"]) for row in targets}
    grace_kept: set[str] = set()
    grace_transitions: list[dict[str, Any]] = []
    grace_force_exit: set[str] = set()
    if use_momentum_grace:
        grace_kept, grace_transitions = _evaluate_momentum_grace_holdings(
            fund,
            candidates,
            target_tickers,
            use_adjusted_signal=use_adjusted_signal,
            acted_at=_utcnow_iso(),
            mutate=False,
        )
        grace_force_exit = {
            str(item["ticker"])
            for item in grace_transitions
            if item.get("action") in {"grace_exit", "sell"}
        }
    keep_tickers, sell_tickers = resolve_automated_holdings_to_exit(
        fund,
        target_tickers=target_tickers,
        grace_kept=grace_kept,
        exit_confirm_screens=exit_confirm_screens,
        mutate_state=False,
        force_exit_tickers=grace_force_exit,
    )
    buffer_held = keep_tickers - target_tickers - grace_kept
    price_map = {
        str(row["ticker"]): float(_candidate_price(row) or 0)
        for row in candidates
        if _candidate_price(row)
    }
    for ticker, position in fund.holdings.items():
        if ticker not in price_map and position.avg_cost > 0:
            price_map[ticker] = float(position.avg_cost)

    nav = fund.nav(price_map)
    cash = float(fund.cash)
    target_each = (nav / len(targets)) if targets else 0.0

    exits: list[dict[str, Any]] = []
    for ticker, position in fund.holdings.items():
        if ticker not in sell_tickers:
            continue
        price = price_map.get(ticker) or position.avg_cost
        value = position.shares * price if price else 0.0
        exits.append(
            {
                "action": "sell",
                "ticker": ticker,
                "name": position.name or ticker,
                "reason": "No longer in the top conviction target set",
                "shares": round(position.shares, 6),
                "price": round(float(price or 0), 4),
                "value": round(value, 2),
            }
        )
        cash += value * (1 - fund.config.trade_cost_pct)

    grace_holds = [
        item for item in grace_transitions if item.get("action") in {"grace_enter", "grace_hold"}
    ]

    # After hypothetical exits, recompute NAV for target sizing narrative.
    remaining_holdings = {t: p for t, p in fund.holdings.items() if t in keep_tickers}
    nav_after_exits = portfolio_value(cash, remaining_holdings, price_map)
    target_each = (nav_after_exits / len(targets)) if targets else 0.0

    trims: list[dict[str, Any]] = []
    buys: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in targets:
        ticker = str(row["ticker"])
        price = float(_candidate_price(row) or 0)
        if price <= 0:
            skipped.append(
                {
                    "ticker": ticker,
                    "name": str(row.get("name") or ticker),
                    "reason": "No usable price mark",
                }
            )
            continue
        current = remaining_holdings.get(ticker)
        current_value = (current.shares * price) if current else 0.0
        conviction = float(row.get("conviction_score") or 0)
        signal = str(row.get("signal") or "")
        if current and current_value > target_each * REBALANCE_TRIM_TOLERANCE:
            excess = current_value - target_each
            if _rebalance_adjustment_worthwhile(excess, min_rebalance_notional_gbp):
                trims.append(
                    {
                        "action": "trim",
                        "ticker": ticker,
                        "name": str(row.get("name") or ticker),
                        "reason": f"Overweight vs equal-weight sleeve ({target_each:,.0f} target)",
                        "value": round(excess, 2),
                        "price": round(price, 4),
                        "conviction_score": conviction,
                        "signal": signal,
                    }
                )
                cash += excess * (1 - fund.config.trade_cost_pct)
                current_value = target_each

        shortfall = target_each - current_value
        if abs(shortfall) <= 0.01 * max(1.0, target_each):
            holds.append(
                {
                    "action": "hold",
                    "ticker": ticker,
                    "name": str(row.get("name") or ticker),
                    "reason": "Already near equal-weight target",
                    "value": round(current_value, 2),
                    "target_value": round(target_each, 2),
                    "conviction_score": conviction,
                    "signal": signal,
                }
            )
            continue
        if shortfall <= 0:
            continue
        if reentry_blocked(fund, ticker):
            skipped.append(
                {
                    "ticker": ticker,
                    "name": str(row.get("name") or ticker),
                    "reason": (
                        f"Re-entry cooldown ({fund.rebalance_state.reentry_cooldown[ticker]} "
                        f"rebalance(s) remaining after recent exit)"
                    ),
                    "target_value": round(target_each, 2),
                    "conviction_score": conviction,
                    "signal": signal,
                }
            )
            continue
        budget = min(shortfall, cash)
        if budget <= REBALANCE_CASH_FLOOR:
            skipped.append(
                {
                    "ticker": ticker,
                    "name": str(row.get("name") or ticker),
                    "reason": "Insufficient cash after higher-conviction fills",
                    "target_value": round(target_each, 2),
                    "conviction_score": conviction,
                    "signal": signal,
                }
            )
            continue
        is_new_sleeve = current_value <= 0
        if not is_new_sleeve and not _rebalance_adjustment_worthwhile(
            budget, min_rebalance_notional_gbp
        ):
            holds.append(
                {
                    "action": "hold",
                    "ticker": ticker,
                    "name": str(row.get("name") or ticker),
                    "reason": (f"Top-up below min trade size (£{min_rebalance_notional_gbp:.0f})"),
                    "value": round(current_value, 2),
                    "target_value": round(target_each, 2),
                    "conviction_score": conviction,
                    "signal": signal,
                }
            )
            continue
        buys.append(
            {
                "action": "buy",
                "ticker": ticker,
                "name": str(row.get("name") or ticker),
                "reason": ("New sleeve" if current_value <= 0 else "Top-up to equal weight"),
                "value": round(budget, 2),
                "price": round(price, 4),
                "target_value": round(target_each, 2),
                "conviction_score": conviction,
                "signal": signal,
            }
        )
        cash -= budget

    for ticker in buffer_held:
        position = remaining_holdings.get(ticker)
        if position is None:
            continue
        price = price_map.get(ticker) or position.avg_cost
        streak = int(fund.rebalance_state.exit_streak.get(ticker, 0)) + 1
        holds.append(
            {
                "action": "hold",
                "ticker": ticker,
                "name": position.name or ticker,
                "reason": (
                    f"Hold buffer — outside target set "
                    f"({streak}/{exit_confirm_screens} screen(s) before exit)"
                ),
                "value": round(position.shares * float(price or 0), 2),
                "conviction_score": None,
                "signal": None,
            }
        )

    waitlisted = [
        {
            "ticker": str(row.get("ticker")),
            "name": str(row.get("name") or row.get("ticker")),
            "signal": str(row.get("signal") or ""),
            "conviction_score": float(row.get("conviction_score") or 0),
            "reason": "timing_signal=wait — skipped until timing improves",
        }
        for row in candidates
        if str(row.get("signal") or "") in BUY_SIGNALS and row.get("timing_signal") == "wait"
    ]
    waitlisted.sort(key=lambda r: r["conviction_score"], reverse=True)

    timing_rule = (
        "Timing filter: names with timing_signal=wait are excluded from new buys."
        if skip_timing_wait
        else "Timing filter: wait names remain eligible."
    )
    narrative = [
        "Universe: only strong_buy / buy names from the latest screen.",
        timing_rule,
        f"Conviction floor: min_conviction={min_conviction:.2f}.",
        (
            f"Sector cap: at most {max(1, int(float(sector_cap) * fund.config.max_positions + 1e-9))} "
            f"name(s) per known sector (cap={float(sector_cap):.0%})."
            if float(sector_cap) < 1.0
            else "Sector cap: disabled."
        ),
        f"Ranking: highest conviction_score first, keep at most {fund.config.max_positions} names.",
        "Sizing: equal-weight sleeves of current NAV after exits; buys limited by remaining cash.",
        f"Costs: {fund.config.trade_cost_pct:.1%} applied on each buy and sell.",
    ]
    if exit_confirm_screens > 0:
        narrative.append(
            f"Hold buffer: full exit only after {exit_confirm_screens} consecutive "
            "rebalance(s) outside the target set."
        )
    if reentry_cooldown_screens > 0:
        narrative.append(
            f"Re-entry cooldown: wait {reentry_cooldown_screens} rebalance(s) after a "
            "full exit before buying the same name again."
        )
    narrative.append(
        f"Dust guard: skip trim/top-up adjustments below £{min_rebalance_notional_gbp:.0f}."
    )

    if use_momentum_grace:
        narrative.append(
            "Momentum grace: holdings that leave buy-tier but still show strong price "
            "trend may be kept for up to 6 weeks with tightened trailing stops."
        )
    return {
        "rules": narrative,
        "nav": round(nav, 2),
        "cash": round(fund.cash, 2),
        "max_positions": fund.config.max_positions,
        "min_conviction": round(float(min_conviction), 4),
        "sector_cap": round(float(sector_cap), 4),
        "skip_timing_wait": bool(skip_timing_wait),
        "use_momentum_grace": bool(use_momentum_grace),
        "exit_confirm_screens": int(exit_confirm_screens),
        "reentry_cooldown_screens": int(reentry_cooldown_screens),
        "min_rebalance_notional_gbp": round(float(min_rebalance_notional_gbp), 2),
        "target_sleeve_value": round(target_each, 2),
        "targets": [
            {
                "ticker": str(row["ticker"]),
                "name": str(row.get("name") or row["ticker"]),
                "signal": str(row.get("signal") or ""),
                "conviction_score": float(row.get("conviction_score") or 0),
                "price": round(float(_candidate_price(row) or 0), 4),
            }
            for row in targets
        ],
        "anticipated_exits": exits,
        "anticipated_grace_holds": grace_holds,
        "anticipated_trims": trims,
        "anticipated_buys": buys,
        "anticipated_holds": holds,
        "skipped": skipped,
        "waitlisted": waitlisted[:8],
        "summary": _plan_summary(exits, trims, buys, holds, targets),
    }


def _plan_summary(
    exits: list[dict[str, Any]],
    trims: list[dict[str, Any]],
    buys: list[dict[str, Any]],
    holds: list[dict[str, Any]],
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return "No eligible buy-tier targets right now — the next rebalance would stay in cash / existing names that still qualify."
    parts = [
        f"Next rebalance would target {len(targets)} equal-weight sleeve(s)",
    ]
    if exits:
        parts.append(f"sell {len(exits)} name(s) that left the set")
    if trims:
        parts.append(f"trim {len(trims)} overweight sleeve(s)")
    if buys:
        parts.append(f"deploy cash into {len(buys)} buy(s)")
    if holds:
        parts.append(f"leave {len(holds)} near-target holding(s)")
    return "; ".join(parts) + "."


def run_automated_rebalance(
    fund: PaperFund,
    candidates: list[dict[str, Any]],
    *,
    acted_at: str | None = None,
    skip_timing_wait: bool = True,
    min_conviction: float = 0.0,
    sector_cap: float = 1.0,
    use_adjusted_signal: bool = False,
    require_research_accumulate: bool = False,
    use_momentum_grace: bool = False,
    exit_confirm_screens: int = DEFAULT_EXIT_CONFIRM_SCREENS,
    reentry_cooldown_screens: int = DEFAULT_REENTRY_COOLDOWN_SCREENS,
    min_rebalance_notional_gbp: float = DEFAULT_MIN_REBALANCE_NOTIONAL_GBP,
) -> list[PaperTrade]:
    """Equal-weight rebalance into top buy-tier names, constrained by cash + max positions."""
    if fund.config.mode != "automated":
        raise ValueError("Automated rebalance requires an automated fund")
    when = acted_at or _utcnow_iso()
    fund.apply_deposits_to(when)
    targets = select_automated_targets(
        candidates,
        max_positions=fund.config.max_positions,
        skip_timing_wait=skip_timing_wait,
        min_conviction=min_conviction,
        sector_cap=sector_cap,
        use_adjusted_signal=use_adjusted_signal,
        require_research_accumulate=require_research_accumulate,
    )
    target_tickers = {str(row["ticker"]) for row in targets}
    price_map = {
        str(row["ticker"]): float(_candidate_price(row) or 0)
        for row in candidates
        if _candidate_price(row)
    }
    for ticker, position in fund.holdings.items():
        if ticker not in price_map and position.avg_cost > 0:
            price_map[ticker] = float(position.avg_cost)
    trades: list[PaperTrade] = []

    grace_kept: set[str] = set()
    grace_force_exit: set[str] = set()
    sold_this_pass: set[str] = set()
    if use_momentum_grace:
        grace_kept, grace_transitions = _evaluate_momentum_grace_holdings(
            fund,
            candidates,
            target_tickers,
            use_adjusted_signal=use_adjusted_signal,
            acted_at=when,
            mutate=True,
        )
        grace_force_exit = {
            str(item["ticker"])
            for item in grace_transitions
            if item.get("action") in {"grace_exit", "sell"}
        }
    _, sell_tickers = resolve_automated_holdings_to_exit(
        fund,
        target_tickers=target_tickers,
        grace_kept=grace_kept,
        exit_confirm_screens=exit_confirm_screens,
        mutate_state=True,
        force_exit_tickers=grace_force_exit,
    )

    for ticker in list(fund.holdings):
        if ticker not in sell_tickers:
            continue
        price = price_map.get(ticker) or fund.holdings[ticker].avg_cost
        if not price or price <= 0:
            continue
        note = (
            "Momentum grace exit"
            if fund.holdings[ticker].momentum_grace
            else "Automated exit — left target set"
        )
        trades.append(
            fund.sell(
                ticker=ticker,
                price=price,
                sizing_mode="shares",
                amount=fund.holdings[ticker].shares,
                note=note,
                acted_at=when,
                prices_for_nav=price_map,
            )
        )
        sold_this_pass.add(ticker)
        mark_reentry_cooldown(fund, ticker, reentry_cooldown_screens)

    if not targets:
        fund.record_mark(price_map, acted_at=when, note="Automated rebalance (no targets)")
        return trades

    nav = fund.nav(price_map)
    target_each = nav / len(targets)

    for row in targets:
        ticker = str(row["ticker"])
        price = float(_candidate_price(row) or 0)
        if price <= 0:
            continue
        if reentry_blocked(fund, ticker):
            continue
        current = fund.holdings.get(ticker)
        current_value = (current.shares * price) if current else 0.0
        # Trim overweight
        if current and current_value > target_each * REBALANCE_TRIM_TOLERANCE:
            excess = current_value - target_each
            if _rebalance_adjustment_worthwhile(excess, min_rebalance_notional_gbp):
                trades.append(
                    fund.sell(
                        ticker=ticker,
                        price=price,
                        sizing_mode="cash",
                        amount=excess,
                        note="Automated trim",
                        acted_at=when,
                        prices_for_nav=price_map,
                    )
                )
                current = fund.holdings.get(ticker)
                current_value = (current.shares * price) if current else 0.0

        shortfall = target_each - current_value
        if shortfall <= REBALANCE_CASH_FLOOR or fund.cash <= REBALANCE_CASH_FLOOR:
            continue
        is_new_sleeve = current_value <= 0
        if not is_new_sleeve and not _rebalance_adjustment_worthwhile(
            shortfall, min_rebalance_notional_gbp
        ):
            continue
        budget = min(shortfall, fund.cash)
        try:
            trades.append(
                fund.buy(
                    ticker=ticker,
                    price=price,
                    sizing_mode="cash",
                    amount=budget,
                    name=str(row.get("name") or ticker),
                    sector=str(row.get("sector") or ""),
                    stop_loss=_optional_float(
                        (row.get("trade_plan") or {}).get("tactical_stop_loss")
                    ),
                    take_profit=_optional_float(
                        (row.get("trade_plan") or {}).get("tactical_take_profit")
                    ),
                    note="Automated buy",
                    acted_at=when,
                    prices_for_nav=price_map,
                )
            )
        except ValueError:
            continue

    tick_reentry_cooldowns(fund, skip_tickers=sold_this_pass)
    fund.record_mark(price_map, acted_at=when, note="Automated rebalance")
    return trades


def run_graduated_rebalance(
    fund: PaperFund,
    candidates: list[dict[str, Any]],
    *,
    acted_at: str | None = None,
    skip_timing_wait: bool = True,
    min_conviction: float = 0.0,
    sector_cap: float = 1.0,
    use_adjusted_signal: bool = False,
    require_research_accumulate: bool = False,
    use_momentum_grace: bool = False,
    exit_confirm_screens: int = DEFAULT_EXIT_CONFIRM_SCREENS,
    reentry_cooldown_screens: int = DEFAULT_REENTRY_COOLDOWN_SCREENS,
    min_rebalance_notional_gbp: float = DEFAULT_MIN_REBALANCE_NOTIONAL_GBP,
    capital_allocation_config: Any | None = None,
) -> list[PaperTrade]:
    """
    Graduated rebalance: trade-plan-weighted entries and urgency-based harvest skims.

    Still uses top-N conviction selection and churn guards; differs from equal-weight
    rebalance in per-sleeve target sizing and partial trims on extended winners.
    """
    from value_investor.capital_allocation import (
        CapitalAllocationConfig,
        entry_appetite,
        entry_sleeve_fraction,
        exit_urgency,
        skim_fraction,
        unrealized_gain_pct,
    )

    if fund.config.mode != "automated":
        raise ValueError("Graduated rebalance requires an automated fund")
    alloc_cfg = capital_allocation_config or CapitalAllocationConfig()
    when = acted_at or _utcnow_iso()
    fund.apply_deposits_to(when)
    targets = select_automated_targets(
        candidates,
        max_positions=fund.config.max_positions,
        skip_timing_wait=skip_timing_wait,
        min_conviction=min_conviction,
        sector_cap=sector_cap,
        use_adjusted_signal=use_adjusted_signal,
        require_research_accumulate=require_research_accumulate,
    )
    target_tickers = {str(row["ticker"]) for row in targets}
    by_ticker = {str(row.get("ticker")): row for row in candidates if row.get("ticker")}
    price_map = {
        str(row["ticker"]): float(_candidate_price(row) or 0)
        for row in candidates
        if _candidate_price(row)
    }
    for ticker, position in fund.holdings.items():
        if ticker not in price_map and position.avg_cost > 0:
            price_map[ticker] = float(position.avg_cost)
    trades: list[PaperTrade] = []

    grace_kept: set[str] = set()
    grace_force_exit: set[str] = set()
    sold_this_pass: set[str] = set()
    if use_momentum_grace:
        grace_kept, grace_transitions = _evaluate_momentum_grace_holdings(
            fund,
            candidates,
            target_tickers,
            use_adjusted_signal=use_adjusted_signal,
            acted_at=when,
            mutate=True,
        )
        grace_force_exit = {
            str(item["ticker"])
            for item in grace_transitions
            if item.get("action") in {"grace_exit", "sell"}
        }
    _, sell_tickers = resolve_automated_holdings_to_exit(
        fund,
        target_tickers=target_tickers,
        grace_kept=grace_kept,
        exit_confirm_screens=exit_confirm_screens,
        mutate_state=True,
        force_exit_tickers=grace_force_exit,
    )

    for ticker in list(fund.holdings):
        if ticker not in sell_tickers:
            continue
        price = price_map.get(ticker) or fund.holdings[ticker].avg_cost
        if not price or price <= 0:
            continue
        note = (
            "Momentum grace exit"
            if fund.holdings[ticker].momentum_grace
            else "Graduated exit — left target set"
        )
        trades.append(
            fund.sell(
                ticker=ticker,
                price=price,
                sizing_mode="shares",
                amount=fund.holdings[ticker].shares,
                note=note,
                acted_at=when,
                prices_for_nav=price_map,
            )
        )
        sold_this_pass.add(ticker)
        mark_reentry_cooldown(fund, ticker, reentry_cooldown_screens)

    if not targets:
        fund.record_mark(price_map, acted_at=when, note="Graduated rebalance (no targets)")
        return trades

    nav = fund.nav(price_map)
    target_each = nav / len(targets)

    # Harvest skims on in-target holdings approaching cycle end (extended / wait timing).
    for ticker, position in list(fund.holdings.items()):
        if ticker in sell_tickers or ticker not in target_tickers:
            continue
        price = price_map.get(ticker) or position.avg_cost
        if not price or price <= 0:
            continue
        row = by_ticker.get(ticker) or {}
        current_value = position.shares * float(price)
        if current_value <= target_each * REBALANCE_TRIM_TOLERANCE:
            continue
        urgency = exit_urgency(
            row=row,
            mark=float(price),
            avg_cost=float(position.avg_cost or 0),
            in_target_set=True,
            exit_streak=0,
            momentum_grace=bool(position.momentum_grace),
            use_adjusted_signal=use_adjusted_signal,
        )
        gain = unrealized_gain_pct(mark=float(price), avg_cost=float(position.avg_cost or 0))
        if urgency < alloc_cfg.skim_urgency_threshold:
            continue
        if gain < alloc_cfg.harvest_gain_pct_floor:
            continue
        excess = current_value - target_each
        trim_amount = excess * skim_fraction(urgency, config=alloc_cfg)
        if not _rebalance_adjustment_worthwhile(trim_amount, min_rebalance_notional_gbp):
            continue
        trades.append(
            fund.sell(
                ticker=ticker,
                price=float(price),
                sizing_mode="cash",
                amount=trim_amount,
                note="Graduated harvest skim",
                acted_at=when,
                prices_for_nav=price_map,
            )
        )

    ranked_targets = sorted(
        targets,
        key=lambda row: entry_appetite(row, use_adjusted_signal=use_adjusted_signal),
        reverse=True,
    )
    for row in ranked_targets:
        ticker = str(row["ticker"])
        price = float(_candidate_price(row) or 0)
        if price <= 0:
            continue
        if reentry_blocked(fund, ticker):
            continue
        sleeve_fraction = entry_sleeve_fraction(
            row,
            config=alloc_cfg,
            use_adjusted_signal=use_adjusted_signal,
        )
        sleeve_target = target_each * sleeve_fraction
        current = fund.holdings.get(ticker)
        current_value = (current.shares * price) if current else 0.0

        if current and current_value > sleeve_target * REBALANCE_TRIM_TOLERANCE:
            excess = current_value - sleeve_target
            if _rebalance_adjustment_worthwhile(excess, min_rebalance_notional_gbp):
                trades.append(
                    fund.sell(
                        ticker=ticker,
                        price=price,
                        sizing_mode="cash",
                        amount=excess,
                        note="Graduated trim to sleeve target",
                        acted_at=when,
                        prices_for_nav=price_map,
                    )
                )
                current = fund.holdings.get(ticker)
                current_value = (current.shares * price) if current else 0.0

        shortfall = sleeve_target - current_value
        if shortfall <= REBALANCE_CASH_FLOOR or fund.cash <= REBALANCE_CASH_FLOOR:
            continue
        is_new_sleeve = current_value <= 0
        if not is_new_sleeve and not _rebalance_adjustment_worthwhile(
            shortfall, min_rebalance_notional_gbp
        ):
            continue
        budget = min(shortfall, fund.cash)
        try:
            trades.append(
                fund.buy(
                    ticker=ticker,
                    price=price,
                    sizing_mode="cash",
                    amount=budget,
                    name=str(row.get("name") or ticker),
                    sector=str(row.get("sector") or ""),
                    stop_loss=_optional_float(
                        (row.get("trade_plan") or {}).get("tactical_stop_loss")
                    ),
                    take_profit=_optional_float(
                        (row.get("trade_plan") or {}).get("tactical_take_profit")
                    ),
                    note="Graduated buy",
                    acted_at=when,
                    prices_for_nav=price_map,
                )
            )
        except ValueError:
            continue

    tick_reentry_cooldowns(fund, skip_tickers=sold_this_pass)
    fund.record_mark(price_map, acted_at=when, note="Graduated rebalance")
    return trades


def run_technical_pass(
    fund: PaperFund,
    candidates: list[dict[str, Any]],
    *,
    acted_at: str | None = None,
    buy_pct_nav: float = 0.1,
) -> list[PaperTrade]:
    """
    Technical cue pass:
    - sell holdings that hit stop / take-profit
    - buy accumulate/neutral buy-tier names not yet held, sized as % of NAV at core limit / last
    """
    if fund.config.mode != "technical":
        raise ValueError("Technical pass requires a technical fund")
    when = acted_at or _utcnow_iso()
    fund.apply_deposits_to(when)
    by_ticker = {str(row["ticker"]): row for row in candidates}
    price_map = {
        ticker: float(_candidate_price(row) or 0)
        for ticker, row in by_ticker.items()
        if _candidate_price(row)
    }
    trades: list[PaperTrade] = []
    exited: set[str] = set()

    for ticker, position in list(fund.holdings.items()):
        price = price_map.get(ticker)
        if price is None or price <= 0:
            continue
        if position.stop_loss is not None and price <= position.stop_loss:
            trades.append(
                fund.sell(
                    ticker=ticker,
                    price=price,
                    sizing_mode="shares",
                    amount=position.shares,
                    note="Technical stop hit",
                    acted_at=when,
                    prices_for_nav=price_map,
                )
            )
            exited.add(ticker)
            continue
        if position.take_profit is not None and price >= position.take_profit:
            trades.append(
                fund.sell(
                    ticker=ticker,
                    price=price,
                    sizing_mode="shares",
                    amount=position.shares,
                    note="Technical take-profit hit",
                    acted_at=when,
                    prices_for_nav=price_map,
                )
            )
            exited.add(ticker)

    if len(fund.holdings) >= fund.config.max_positions or fund.cash <= 0:
        fund.record_mark(price_map, acted_at=when, note="Technical pass")
        return trades

    ranked = select_automated_targets(
        candidates,
        max_positions=fund.config.max_positions * 2,
        skip_timing_wait=True,
    )
    for row in ranked:
        if len(fund.holdings) >= fund.config.max_positions or fund.cash <= 0:
            break
        ticker = str(row["ticker"])
        if ticker in fund.holdings or ticker in exited:
            continue
        timing = row.get("timing_signal")
        if timing == "wait":
            continue
        plan = row.get("trade_plan") or {}
        price = _optional_float(plan.get("core_limit")) or _candidate_price(row)
        if price is None or price <= 0:
            continue
        try:
            trades.append(
                fund.buy(
                    ticker=ticker,
                    price=float(price),
                    sizing_mode="pct_nav",
                    amount=buy_pct_nav,
                    name=str(row.get("name") or ticker),
                    sector=str(row.get("sector") or ""),
                    stop_loss=_optional_float(plan.get("tactical_stop_loss")),
                    take_profit=_optional_float(plan.get("tactical_take_profit")),
                    note="Technical entry at core limit",
                    acted_at=when,
                    prices_for_nav=price_map,
                )
            )
        except ValueError:
            continue

    fund.record_mark(price_map, acted_at=when, note="Technical pass")
    return trades


def preview_technical_plan(
    fund: PaperFund,
    candidates: list[dict[str, Any]],
    *,
    buy_pct_nav: float = 0.1,
) -> dict[str, Any]:
    """Dry-run technical exits/entries without mutating the fund."""
    if fund.config.mode != "technical":
        raise ValueError("Technical plan preview requires a technical fund")

    by_ticker = {str(row["ticker"]): row for row in candidates}
    price_map = {
        ticker: float(_candidate_price(row) or 0)
        for ticker, row in by_ticker.items()
        if _candidate_price(row)
    }
    for ticker, position in fund.holdings.items():
        if ticker not in price_map and position.avg_cost > 0:
            price_map[ticker] = float(position.avg_cost)

    exits: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    for ticker, position in fund.holdings.items():
        price = price_map.get(ticker)
        if price is None or price <= 0:
            holds.append(
                {
                    "action": "hold",
                    "ticker": ticker,
                    "name": position.name or ticker,
                    "reason": "No mark available to evaluate stop/target",
                }
            )
            continue
        if position.stop_loss is not None and price <= position.stop_loss:
            exits.append(
                {
                    "action": "sell",
                    "ticker": ticker,
                    "name": position.name or ticker,
                    "reason": f"Stop hit (mark {price:.2f} ≤ stop {position.stop_loss:.2f})",
                    "shares": round(position.shares, 6),
                    "price": round(price, 4),
                    "value": round(position.shares * price, 2),
                }
            )
            continue
        if position.take_profit is not None and price >= position.take_profit:
            exits.append(
                {
                    "action": "sell",
                    "ticker": ticker,
                    "name": position.name or ticker,
                    "reason": (
                        f"Take-profit hit (mark {price:.2f} ≥ target {position.take_profit:.2f})"
                    ),
                    "shares": round(position.shares, 6),
                    "price": round(price, 4),
                    "value": round(position.shares * price, 2),
                }
            )
            continue
        holds.append(
            {
                "action": "hold",
                "ticker": ticker,
                "name": position.name or ticker,
                "reason": "Between stop and target (or levels not set)",
                "value": round(position.shares * price, 2),
            }
        )

    exited = {row["ticker"] for row in exits}
    open_slots = max(0, fund.config.max_positions - (len(fund.holdings) - len(exited)))
    nav = fund.nav(price_map)
    entries: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []

    if open_slots <= 0 or fund.cash <= 0:
        deferred.append(
            {
                "ticker": "—",
                "name": "New entries",
                "reason": "No open slots or cash available after exits",
            }
        )
    else:
        ranked = select_automated_targets(
            candidates,
            max_positions=fund.config.max_positions * 2,
            skip_timing_wait=True,
        )
        for row in ranked:
            if len(entries) >= open_slots:
                break
            ticker = str(row["ticker"])
            if ticker in fund.holdings or ticker in exited:
                continue
            if row.get("timing_signal") == "wait":
                deferred.append(
                    {
                        "ticker": ticker,
                        "name": str(row.get("name") or ticker),
                        "reason": "timing_signal=wait",
                        "conviction_score": float(row.get("conviction_score") or 0),
                        "signal": str(row.get("signal") or ""),
                    }
                )
                continue
            plan = row.get("trade_plan") or {}
            price = _optional_float(plan.get("core_limit")) or _candidate_price(row)
            if price is None or price <= 0:
                deferred.append(
                    {
                        "ticker": ticker,
                        "name": str(row.get("name") or ticker),
                        "reason": "No core limit / mark for entry",
                    }
                )
                continue
            notional = nav * buy_pct_nav
            entries.append(
                {
                    "action": "buy",
                    "ticker": ticker,
                    "name": str(row.get("name") or ticker),
                    "reason": (
                        f"Core-limit entry (~{buy_pct_nav:.0%} NAV)"
                        + (
                            f" at {float(price):.2f}"
                            if plan.get("core_limit") is not None
                            else " at last mark"
                        )
                    ),
                    "value": round(min(notional, fund.cash), 2),
                    "price": round(float(price), 4),
                    "conviction_score": float(row.get("conviction_score") or 0),
                    "signal": str(row.get("signal") or ""),
                }
            )

    rules = [
        "Exits first: full sell if last mark ≤ stop loss or ≥ take-profit.",
        "Entries next: unused buy-tier names (timing ≠ wait) at core limit when available.",
        f"Position size for new entries: about {buy_pct_nav:.0%} of current NAV, capped by cash.",
        "Names exited in the same pass are not re-bought immediately.",
        f"Hard cap: {fund.config.max_positions} open names.",
    ]
    parts = []
    if exits:
        parts.append(f"exit {len(exits)} holding(s) on stop/target")
    if entries:
        parts.append(f"enter {len(entries)} new name(s) near core limit")
    if holds:
        parts.append(f"keep {len(holds)} holding(s) between levels")
    summary = (
        ("Next technical pass would " + "; ".join(parts) + ".")
        if parts
        else "Next technical pass would make no trades on the current marks and screen."
    )
    return {
        "rules": rules,
        "nav": round(nav, 2),
        "cash": round(fund.cash, 2),
        "buy_pct_nav": buy_pct_nav,
        "anticipated_exits": exits,
        "anticipated_buys": entries,
        "anticipated_holds": holds,
        "deferred": deferred[:8],
        "summary": summary,
    }


def compare_funds(funds: list[PaperFund], prices: dict[str, float]) -> list[dict[str, Any]]:
    rows = []
    for fund in funds:
        perf = fund.performance(prices)
        rows.append(
            {
                "id": fund.config.id,
                "name": fund.config.name,
                "mode": fund.config.mode,
                "mode_label": STRATEGY_LABELS.get(fund.config.mode, fund.config.mode),
                **perf,
            }
        )
    rows.sort(key=lambda r: r["total_return"], reverse=True)
    return rows
