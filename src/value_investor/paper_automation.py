"""Independent daily paper-fund automation and owned-stock surveillance."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from value_investor.paper_fund import (
    DEFAULT_INITIAL_CASH,
    DEFAULT_MAX_POSITIONS,
    DEFAULT_TRADE_COST_PCT,
    PaperFund,
    PaperFundConfig,
    preview_automated_plan,
    run_automated_rebalance,
)
from value_investor.portfolio_diversity import DEFAULT_TARGET_SECTOR_CAP
from value_investor.technical_analysis import (
    compute_indicators,
    compute_trade_plan,
    fetch_price_history,
)

LONDON = ZoneInfo("Europe/London")
DEFAULT_MARKET_OPEN = time(8, 0)
DEFAULT_SETTLE_MINUTES = 75  # ~09:15 London after 08:00 open
DEFAULT_AUTOMATION_DIR = Path("output/paper_automation")
FUND_FILENAME = "automated_fund.json"
WATCHLIST_FILENAME = "owned_watchlist.json"
REPORT_FILENAME = "last_run.json"
CONFIG_FILENAME = "config.json"


@dataclass
class AutomationConfig:
    """Controls independent automated paper trading and surveillance."""

    enabled: bool = True
    timezone: str = "Europe/London"
    market_open: str = "08:00"  # HH:MM local
    settle_minutes_after_open: int = DEFAULT_SETTLE_MINUTES
    weekdays_only: bool = True
    auto_rebalance: bool = True
    surveil_paper_holdings: bool = True
    surveil_watchlist: bool = True
    initial_cash: float = DEFAULT_INITIAL_CASH
    monthly_deposit: float = 0.0
    trade_cost_pct: float = DEFAULT_TRADE_COST_PCT
    max_positions: int = DEFAULT_MAX_POSITIONS
    # Decision-review learning knobs (L1) — tuned by ftse-decision-review.
    skip_timing_wait: bool = True
    min_conviction: float = 0.0
    sector_cap: float = DEFAULT_TARGET_SECTOR_CAP

    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def market_open_time(self) -> time:
        hour, minute = self.market_open.split(":")
        return time(int(hour), int(minute))

    def settle_time(self) -> time:
        base = datetime.combine(date(2000, 1, 1), self.market_open_time())
        settled = base + timedelta(minutes=int(self.settle_minutes_after_open))
        return settled.time()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AutomationConfig:
        raw = data or {}
        return cls(
            enabled=bool(raw.get("enabled", True)),
            timezone=str(raw.get("timezone") or "Europe/London"),
            market_open=str(raw.get("market_open") or "08:00"),
            settle_minutes_after_open=int(
                raw.get("settle_minutes_after_open", DEFAULT_SETTLE_MINUTES)
            ),
            weekdays_only=bool(raw.get("weekdays_only", True)),
            auto_rebalance=bool(raw.get("auto_rebalance", True)),
            surveil_paper_holdings=bool(raw.get("surveil_paper_holdings", True)),
            surveil_watchlist=bool(raw.get("surveil_watchlist", True)),
            initial_cash=float(raw.get("initial_cash", DEFAULT_INITIAL_CASH)),
            monthly_deposit=float(raw.get("monthly_deposit") or 0),
            trade_cost_pct=float(raw.get("trade_cost_pct", DEFAULT_TRADE_COST_PCT)),
            max_positions=int(raw.get("max_positions", DEFAULT_MAX_POSITIONS)),
            skip_timing_wait=bool(raw.get("skip_timing_wait", True)),
            min_conviction=float(raw.get("min_conviction") or 0.0),
            sector_cap=float(
                raw.get("sector_cap", DEFAULT_TARGET_SECTOR_CAP)
                if raw.get("sector_cap") is not None
                else DEFAULT_TARGET_SECTOR_CAP
            ),
        )


def local_now(config: AutomationConfig, now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=config.tz())
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc).astimezone(config.tz())
    return now.astimezone(config.tz())


def is_trading_day(config: AutomationConfig, when: datetime | None = None) -> bool:
    local = local_now(config, when)
    if not config.weekdays_only:
        return True
    return local.weekday() < 5  # Mon-Fri


def is_after_open_settle(config: AutomationConfig, when: datetime | None = None) -> bool:
    """True once early open volatility window has elapsed for the local session."""
    local = local_now(config, when)
    if not is_trading_day(config, local):
        return False
    settle_at = datetime.combine(local.date(), config.settle_time(), tzinfo=config.tz())
    return local >= settle_at


def session_gate_status(config: AutomationConfig, when: datetime | None = None) -> dict[str, Any]:
    local = local_now(config, when)
    trading = is_trading_day(config, local)
    settled = is_after_open_settle(config, local)
    open_at = datetime.combine(local.date(), config.market_open_time(), tzinfo=config.tz())
    settle_at = datetime.combine(local.date(), config.settle_time(), tzinfo=config.tz())
    reason = "ok"
    if not config.enabled:
        reason = "automation disabled"
    elif not trading:
        reason = "non-trading day"
    elif local < open_at:
        reason = "before market open"
    elif not settled:
        reason = (
            f"waiting for open settle "
            f"({config.settle_minutes_after_open} min after {config.market_open} {config.timezone})"
        )
    return {
        "local_time": local.isoformat(),
        "trading_day": trading,
        "after_settle": settled,
        "market_open_at": open_at.isoformat(),
        "settle_at": settle_at.isoformat(),
        "can_act": bool(config.enabled and trading and settled),
        "reason": reason,
    }


@dataclass
class SurveillanceAlert:
    ticker: str
    name: str
    source: str  # paper | watchlist | live
    severity: str  # info | watch | action
    message: str
    mark: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    timing_signal: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def surveil_position(
    *,
    ticker: str,
    name: str,
    source: str,
    mark: float | None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    timing_signal: str | None = None,
    signal: str | None = None,
) -> list[SurveillanceAlert]:
    alerts: list[SurveillanceAlert] = []
    if mark is not None and stop_loss is not None and mark <= stop_loss:
        alerts.append(
            SurveillanceAlert(
                ticker=ticker,
                name=name,
                source=source,
                severity="action",
                message=f"Mark {mark:.2f} at/under stop {stop_loss:.2f}",
                mark=mark,
                stop_loss=stop_loss,
                take_profit=take_profit,
                timing_signal=timing_signal,
            )
        )
    if mark is not None and take_profit is not None and mark >= take_profit:
        alerts.append(
            SurveillanceAlert(
                ticker=ticker,
                name=name,
                source=source,
                severity="action",
                message=f"Mark {mark:.2f} at/over take-profit {take_profit:.2f}",
                mark=mark,
                stop_loss=stop_loss,
                take_profit=take_profit,
                timing_signal=timing_signal,
            )
        )
    if timing_signal == "wait":
        alerts.append(
            SurveillanceAlert(
                ticker=ticker,
                name=name,
                source=source,
                severity="watch",
                message="Technical timing is wait — avoid adding size",
                mark=mark,
                stop_loss=stop_loss,
                take_profit=take_profit,
                timing_signal=timing_signal,
            )
        )
    if signal in {"avoid", "hold"} and source in {"paper", "live", "watchlist"}:
        alerts.append(
            SurveillanceAlert(
                ticker=ticker,
                name=name,
                source=source,
                severity="watch",
                message=f"Screen signal is now {signal}",
                mark=mark,
                stop_loss=stop_loss,
                take_profit=take_profit,
                timing_signal=timing_signal,
            )
        )
    if not alerts:
        alerts.append(
            SurveillanceAlert(
                ticker=ticker,
                name=name,
                source=source,
                severity="info",
                message="No stop/target breach; continue monitoring",
                mark=mark,
                stop_loss=stop_loss,
                take_profit=take_profit,
                timing_signal=timing_signal,
            )
        )
    return alerts


def load_watchlist(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        rows = data.get("holdings") or data.get("tickers") or []
    else:
        rows = data
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, str):
            out.append({"ticker": row, "name": row, "source": "watchlist"})
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        out.append(
            {
                "ticker": ticker,
                "name": str(row.get("name") or ticker),
                "source": str(row.get("source") or "watchlist"),
                "stop_loss": row.get("stop_loss"),
                "take_profit": row.get("take_profit"),
                "shares": row.get("shares"),
            }
        )
    return out


def save_watchlist(path: Path, holdings: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "holdings": holdings,
        "note": "Real/live owned names for daily surveillance (not paper-fund cash).",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def sync_fund_from_automation_config(fund: PaperFund, config: AutomationConfig) -> None:
    """Keep live fund trading knobs aligned with automation config (incl. L1 updates)."""
    fund.config.max_positions = int(config.max_positions)
    fund.config.monthly_deposit = float(config.monthly_deposit)
    fund.config.trade_cost_pct = float(config.trade_cost_pct)


def ensure_automated_fund(path: Path, config: AutomationConfig) -> PaperFund:
    if path.exists():
        fund = PaperFund.from_dict(json.loads(path.read_text(encoding="utf-8")))
        sync_fund_from_automation_config(fund, config)
        return fund
    fund = PaperFund.create(
        PaperFundConfig(
            name="Automated stock picking",
            mode="automated",
            initial_cash=config.initial_cash,
            monthly_deposit=config.monthly_deposit,
            trade_cost_pct=config.trade_cost_pct,
            max_positions=config.max_positions,
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fund.to_dict(), indent=2), encoding="utf-8")
    return fund


def save_automated_fund(path: Path, fund: PaperFund) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fund.to_dict(), indent=2), encoding="utf-8")


def load_screen_candidates(reports_path: Path | None = None) -> list[dict[str, Any]]:
    """Load latest screen reports for candidate selection."""
    if reports_path is not None:
        path = Path(reports_path)
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        reports = payload.get("reports") if isinstance(payload, dict) else None
        return list(reports) if isinstance(reports, list) else []

    for path in (Path("docs/data/latest.json"), Path("output/dashboard_bundle.json")):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        reports = payload.get("reports") if isinstance(payload, dict) else None
        if isinstance(reports, list) and reports:
            return reports
    return []


def refresh_candidate_marks(
    candidates: list[dict[str, Any]],
    extra_tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Attach fresh last closes + timing signals for decisioning."""
    tickers = [str(row.get("ticker")) for row in candidates if row.get("ticker")]
    if extra_tickers:
        tickers.extend(extra_tickers)
    tickers = list(dict.fromkeys(t for t in tickers if t))
    if not tickers:
        return candidates

    history = fetch_price_history(tickers, period="6mo")
    by_ticker = {str(row.get("ticker")): dict(row) for row in candidates}
    for ticker in tickers:
        frame = history.get(ticker)
        row = by_ticker.get(ticker) or {"ticker": ticker, "name": ticker, "signal": "hold"}
        if frame is not None and not frame.empty and "Close" in frame.columns:
            series = frame["Close"]
            last = float(series.dropna().iloc[-1]) if not series.dropna().empty else None
            if last is not None:
                row["price"] = last
                row["last"] = last
            tech = compute_indicators(frame)
            row["timing_signal"] = tech.timing_signal.value
            row["timing_score"] = tech.timing_score
            row["rsi_14"] = tech.rsi_14
            row["atr_14"] = tech.atr_14
            row["volume_ratio_20"] = tech.volume_ratio_20
            signal = str(row.get("signal") or "hold")
            if tech.trade_plan is None and signal in {"strong_buy", "buy"}:
                tech.trade_plan = compute_trade_plan(series, tech, value_signal=signal)
            if tech.trade_plan is not None:
                existing = row.get("trade_plan") or {}
                plan = tech.trade_plan.to_dict()
                for key, value in plan.items():
                    existing.setdefault(key, value)
                row["trade_plan"] = existing
        by_ticker[ticker] = row
    return list(by_ticker.values())


def run_owned_surveillance(
    *,
    paper_fund: PaperFund | None,
    watchlist: list[dict[str, Any]],
    marked_rows: list[dict[str, Any]],
    config: AutomationConfig,
) -> list[SurveillanceAlert]:
    by_ticker = {str(row.get("ticker")): row for row in marked_rows}
    alerts: list[SurveillanceAlert] = []

    if config.surveil_paper_holdings and paper_fund is not None:
        for ticker, position in paper_fund.holdings.items():
            row = by_ticker.get(ticker) or {}
            mark = row.get("price") or row.get("last") or position.avg_cost
            alerts.extend(
                surveil_position(
                    ticker=ticker,
                    name=position.name or ticker,
                    source="paper",
                    mark=float(mark) if mark is not None else None,
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                    timing_signal=row.get("timing_signal"),
                    signal=row.get("signal"),
                )
            )

    if config.surveil_watchlist:
        for item in watchlist:
            ticker = str(item["ticker"])
            row = by_ticker.get(ticker) or {}
            mark = row.get("price") or row.get("last")
            stop = item.get("stop_loss")
            target = item.get("take_profit")
            if stop is None:
                stop = (row.get("trade_plan") or {}).get("tactical_stop_loss")
            if target is None:
                target = (row.get("trade_plan") or {}).get("tactical_take_profit")
            alerts.extend(
                surveil_position(
                    ticker=ticker,
                    name=str(item.get("name") or row.get("name") or ticker),
                    source=str(item.get("source") or "watchlist"),
                    mark=float(mark) if mark is not None else None,
                    stop_loss=float(stop) if stop is not None else None,
                    take_profit=float(target) if target is not None else None,
                    timing_signal=row.get("timing_signal"),
                    signal=row.get("signal"),
                )
            )
    return alerts


@dataclass
class AutomationRunResult:
    acted: bool
    gate: dict[str, Any]
    trades: list[dict[str, Any]] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    fund: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "acted": self.acted,
            "gate": self.gate,
            "trades": self.trades,
            "plan": self.plan,
            "alerts": self.alerts,
            "fund": self.fund,
            "note": self.note,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


def run_daily_automation(
    *,
    output_dir: Path = DEFAULT_AUTOMATION_DIR,
    config: AutomationConfig | None = None,
    reports_path: Path | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> AutomationRunResult:
    """
    Independent daily pass for the automated paper fund.

    Waits until post-open settle by default, refreshes marks/timing for owned
    and buy-tier names, optionally rebalances, and emits surveillance alerts.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / CONFIG_FILENAME
    if config is None:
        if config_path.exists():
            config = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
        else:
            config = AutomationConfig()
            config_path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
    else:
        config_path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")

    gate = session_gate_status(config, now)
    fund_path = output_dir / FUND_FILENAME
    fund = ensure_automated_fund(fund_path, config)
    watchlist = load_watchlist(output_dir / WATCHLIST_FILENAME)

    screen_rows = load_screen_candidates(reports_path)
    owned_tickers = list(fund.holdings.keys()) + [str(w["ticker"]) for w in watchlist]
    marked = refresh_candidate_marks(screen_rows, extra_tickers=owned_tickers)
    select_kwargs = {
        "skip_timing_wait": bool(config.skip_timing_wait),
        "min_conviction": float(config.min_conviction),
        "sector_cap": float(config.sector_cap),
    }

    plan = (
        preview_automated_plan(fund, marked, **select_kwargs)
        if fund.config.mode == "automated"
        else {}
    )
    alerts = [
        a.to_dict()
        for a in run_owned_surveillance(
            paper_fund=fund,
            watchlist=watchlist,
            marked_rows=marked,
            config=config,
        )
    ]

    trades: list[dict[str, Any]] = []
    acted = False
    note = gate["reason"]

    can_act = force or gate["can_act"]
    if can_act and config.auto_rebalance:
        fund.apply_deposits_to(gate["local_time"])
        executed = run_automated_rebalance(
            fund, marked, acted_at=gate["local_time"], **select_kwargs
        )
        trades = [t.to_dict() for t in executed]
        save_automated_fund(fund_path, fund)
        acted = True
        note = f"Rebalanced after open settle ({len(trades)} trade(s))."
        plan = preview_automated_plan(fund, marked, **select_kwargs)
        alerts = [
            a.to_dict()
            for a in run_owned_surveillance(
                paper_fund=fund,
                watchlist=watchlist,
                marked_rows=marked,
                config=config,
            )
        ]
    elif can_act and not config.auto_rebalance:
        note = "Settle window open but auto_rebalance is disabled; surveillance only."
    else:
        # Still persist deposit catch-up without trading when disabled/early.
        fund.apply_deposits_to(gate["local_time"])
        save_automated_fund(fund_path, fund)

    result = AutomationRunResult(
        acted=acted,
        gate=gate,
        trades=trades,
        plan=plan,
        alerts=alerts,
        fund=fund.to_dict(),
        note=note,
    )
    (output_dir / REPORT_FILENAME).write_text(
        json.dumps(result.to_dict(), indent=2),
        encoding="utf-8",
    )
    return result


def format_automation_text(result: AutomationRunResult) -> str:
    lines = [
        "Paper automation",
        f"  Status: {result.note}",
        f"  Local time: {result.gate.get('local_time')}",
        f"  Can act: {result.gate.get('can_act')} ({result.gate.get('reason')})",
        f"  Trades: {len(result.trades)}",
        f"  Alerts: {len(result.alerts)}",
    ]
    action_alerts = [a for a in result.alerts if a.get("severity") == "action"]
    if action_alerts:
        lines.append("  Action alerts:")
        for alert in action_alerts[:10]:
            lines.append(f"    - {alert['ticker']}: {alert['message']}")
    if result.plan.get("summary"):
        lines.append(f"  Plan: {result.plan['summary']}")
    return "\n".join(lines)
