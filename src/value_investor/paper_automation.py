"""Independent daily paper-fund automation and owned-stock surveillance."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from value_investor.exit_shadow import run_exit_shadow_pass, summarize_learning_tracks_exit_shadow
from value_investor.exit_timing_cohorts import (
    run_exit_timing_cohort_pass,
    summarize_learning_tracks_exit_timing,
)
from value_investor.hypothesis_integrity import (
    ROLLUP_FILENAME as HYPOTHESIS_ROLLUP_FILENAME,
)
from value_investor.hypothesis_integrity import (
    run_hypothesis_integrity_pass,
    summarize_learning_tracks_hypothesis_integrity,
)
from value_investor.hypothesis_outcome_linker import (
    ROLLUP_FILENAME as HYPOTHESIS_OUTCOMES_ROLLUP_FILENAME,
)
from value_investor.hypothesis_outcome_linker import (
    run_hypothesis_outcome_link_pass,
    summarize_learning_tracks_hypothesis_outcomes,
)
from value_investor.paper_fund import (
    DEFAULT_EXIT_CONFIRM_SCREENS,
    DEFAULT_INITIAL_CASH,
    DEFAULT_MAX_POSITIONS,
    DEFAULT_MIN_REBALANCE_NOTIONAL_GBP,
    DEFAULT_REENTRY_COOLDOWN_SCREENS,
    DEFAULT_TRADE_COST_PCT,
    PaperFund,
    PaperFundConfig,
    preview_automated_plan,
    preview_technical_plan,
    run_automated_rebalance,
    run_graduated_rebalance,
    run_technical_pass,
)
from value_investor.portfolio_diversity import DEFAULT_TARGET_SECTOR_CAP
from value_investor.rebalance_log import (
    append_rebalance_log,
    build_rebalance_log_entry,
    collect_decision_candidates,
    collect_screen_buy_tier,
    gate_excluded_tickers,
    load_knob_epoch_started_at,
    resolve_screen_source,
    snapshot_holdings,
)
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


def _rebalance_kwargs(selection: dict[str, Any]) -> dict[str, Any]:
    """Strip track-mode flags that rebalance/plan helpers do not accept."""
    return {k: v for k, v in selection.items() if k != "use_graduated_allocation"}


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
    # Learning-track policy (primary = AI judgment vs market excess).
    strategy_mode: str = "automated"  # automated | technical
    track_id: str = "rules"
    track_label: str = "Screen rules (control)"
    is_primary_learning_track: bool = False
    use_adjusted_signal: bool = False
    require_research_accumulate: bool = False
    use_momentum_grace: bool = False
    use_graduated_allocation: bool = False
    # Calibration shadow — frozen knobs from knob_calibration priors (not decision-review).
    is_calibration_shadow: bool = False
    calibration_parent_track: str | None = None
    # Exclusion shadow — frozen knobs from exclusion-universe archive ladder priors.
    is_exclusion_shadow: bool = False
    exclusion_parent_track: str | None = None
    exclusion_ladder_step_id: str | None = None
    # Churn guards — tuneable via config.json (not decision-review knobs yet).
    exit_confirm_screens: int = DEFAULT_EXIT_CONFIRM_SCREENS
    reentry_cooldown_screens: int = DEFAULT_REENTRY_COOLDOWN_SCREENS
    min_rebalance_notional_gbp: float = DEFAULT_MIN_REBALANCE_NOTIONAL_GBP

    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def market_open_time(self) -> time:
        hour, minute = self.market_open.split(":")
        return time(int(hour), int(minute))

    def settle_time(self) -> time:
        base = datetime.combine(date(2000, 1, 1), self.market_open_time())
        settled = base + timedelta(minutes=int(self.settle_minutes_after_open))
        return settled.time()

    def selection_kwargs(self) -> dict[str, Any]:
        return {
            "skip_timing_wait": bool(self.skip_timing_wait),
            "min_conviction": float(self.min_conviction),
            "sector_cap": float(self.sector_cap),
            "use_adjusted_signal": bool(self.use_adjusted_signal),
            "require_research_accumulate": bool(self.require_research_accumulate),
            "use_momentum_grace": bool(self.use_momentum_grace),
            "use_graduated_allocation": bool(self.use_graduated_allocation),
            "exit_confirm_screens": int(self.exit_confirm_screens),
            "reentry_cooldown_screens": int(self.reentry_cooldown_screens),
            "min_rebalance_notional_gbp": round(float(self.min_rebalance_notional_gbp), 2),
        }

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
            track_id=str(raw.get("track_id") or "rules"),
            strategy_mode=str(raw.get("strategy_mode") or "automated"),
            track_label=str(raw.get("track_label") or "Screen rules (control)"),
            is_primary_learning_track=bool(raw.get("is_primary_learning_track", False)),
            use_adjusted_signal=bool(raw.get("use_adjusted_signal", False)),
            require_research_accumulate=bool(raw.get("require_research_accumulate", False)),
            use_momentum_grace=bool(raw.get("use_momentum_grace", False)),
            use_graduated_allocation=bool(raw.get("use_graduated_allocation", False)),
            is_calibration_shadow=bool(raw.get("is_calibration_shadow", False)),
            calibration_parent_track=(
                str(raw["calibration_parent_track"])
                if raw.get("calibration_parent_track")
                else None
            ),
            is_exclusion_shadow=bool(raw.get("is_exclusion_shadow", False)),
            exclusion_parent_track=(
                str(raw["exclusion_parent_track"]) if raw.get("exclusion_parent_track") else None
            ),
            exclusion_ladder_step_id=(
                str(raw["exclusion_ladder_step_id"])
                if raw.get("exclusion_ladder_step_id")
                else None
            ),
            exit_confirm_screens=int(raw.get("exit_confirm_screens", DEFAULT_EXIT_CONFIRM_SCREENS)),
            reentry_cooldown_screens=int(
                raw.get("reentry_cooldown_screens", DEFAULT_REENTRY_COOLDOWN_SCREENS)
            ),
            min_rebalance_notional_gbp=float(
                raw.get("min_rebalance_notional_gbp", DEFAULT_MIN_REBALANCE_NOTIONAL_GBP)
            ),
        )


AI_JUDGMENT_TRACK_ID = "ai_judgment"
AI_JUDGMENT_CALIBRATED_TRACK_ID = "ai_judgment_calibrated"
RULES_TRACK_ID = "rules"
MOMENTUM_GRACE_TRACK_ID = "momentum_grace"
GRADUATED_ALLOCATION_TRACK_ID = "graduated_allocation"
TECHNICAL_TRACK_ID = "technical"
AI_JUDGMENT_SUBDIR = "ai_judgment"
AI_JUDGMENT_CALIBRATED_SUBDIR = "ai_judgment_calibrated"
MOMENTUM_GRACE_SUBDIR = "momentum_grace"
GRADUATED_ALLOCATION_SUBDIR = "graduated_allocation"
TECHNICAL_SUBDIR = "technical"
LEARNING_TRACK_IDS = (
    RULES_TRACK_ID,
    AI_JUDGMENT_TRACK_ID,
    AI_JUDGMENT_CALIBRATED_TRACK_ID,
    MOMENTUM_GRACE_TRACK_ID,
    GRADUATED_ALLOCATION_TRACK_ID,
    TECHNICAL_TRACK_ID,
)


def default_ai_judgment_config(base: AutomationConfig | None = None) -> AutomationConfig:
    """Primary learning track: AI/research judgment at decision time."""
    cfg = AutomationConfig.from_dict((base or AutomationConfig()).to_dict())
    cfg.track_id = AI_JUDGMENT_TRACK_ID
    cfg.track_label = "AI judgment (research accumulate + adjusted_signal)"
    cfg.is_primary_learning_track = True
    cfg.use_adjusted_signal = True
    cfg.require_research_accumulate = True
    return cfg


def default_momentum_grace_config(base: AutomationConfig | None = None) -> AutomationConfig:
    """Experimental track: screen rules + momentum grace on value downgrades."""
    cfg = default_rules_config(base)
    cfg.track_id = MOMENTUM_GRACE_TRACK_ID
    cfg.track_label = "Screen rules + momentum grace"
    cfg.is_primary_learning_track = False
    cfg.use_momentum_grace = True
    return cfg


def default_graduated_allocation_config(base: AutomationConfig | None = None) -> AutomationConfig:
    """Experimental track: screen rules + trade-plan graduated entry/harvest skims."""
    cfg = default_rules_config(base)
    cfg.track_id = GRADUATED_ALLOCATION_TRACK_ID
    cfg.track_label = "Screen rules + graduated allocation"
    cfg.is_primary_learning_track = False
    cfg.use_graduated_allocation = True
    cfg.max_positions = max(int(cfg.max_positions), 4)
    return cfg


def default_technical_config(base: AutomationConfig | None = None) -> AutomationConfig:
    """Timing baseline: stops/targets from trade_plan, no conviction rebalance."""
    cfg = AutomationConfig.from_dict((base or AutomationConfig()).to_dict())
    cfg.track_id = TECHNICAL_TRACK_ID
    cfg.track_label = "Technical levels (stops / trade_plan)"
    cfg.is_primary_learning_track = False
    cfg.strategy_mode = "technical"
    cfg.use_adjusted_signal = False
    cfg.require_research_accumulate = False
    cfg.use_momentum_grace = False
    cfg.auto_rebalance = True
    return cfg


def default_rules_config(base: AutomationConfig | None = None) -> AutomationConfig:
    """Control track: raw screen buy-tier rules only."""
    cfg = AutomationConfig.from_dict((base or AutomationConfig()).to_dict())
    cfg.track_id = RULES_TRACK_ID
    cfg.track_label = "Screen rules (control)"
    cfg.is_primary_learning_track = False
    cfg.strategy_mode = "automated"
    cfg.use_adjusted_signal = False
    cfg.require_research_accumulate = False
    return cfg


def learning_track_dirs(base_dir: Path) -> dict[str, Path]:
    """Map track_id → output directory under the paper-automation root."""
    from value_investor.exclusion_ladder_replay import (
        discover_exclusion_shadow_step_ids,
        exclusion_shadow_subdir,
        exclusion_shadow_track_id,
    )
    from value_investor.knob_calibration import (
        calibrated_shadow_subdir,
        calibrated_shadow_track_id,
        discover_calibration_shadow_ranks,
    )

    root = Path(base_dir)
    dirs: dict[str, Path] = {
        RULES_TRACK_ID: root,
        AI_JUDGMENT_TRACK_ID: root / AI_JUDGMENT_SUBDIR,
        MOMENTUM_GRACE_TRACK_ID: root / MOMENTUM_GRACE_SUBDIR,
        GRADUATED_ALLOCATION_TRACK_ID: root / GRADUATED_ALLOCATION_SUBDIR,
        TECHNICAL_TRACK_ID: root / TECHNICAL_SUBDIR,
    }
    for rank in discover_calibration_shadow_ranks(root):
        track_id = calibrated_shadow_track_id(rank)
        dirs[track_id] = root / calibrated_shadow_subdir(rank)
    for step_id in discover_exclusion_shadow_step_ids(root):
        track_id = exclusion_shadow_track_id(step_id)
        dirs[track_id] = root / exclusion_shadow_subdir(step_id)
    return dirs


def local_now(config: AutomationConfig, now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=config.tz())
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC).astimezone(config.tz())
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


def already_rebalanced_today(
    output_dir: Path,
    config: AutomationConfig,
    when: datetime | None = None,
) -> bool:
    """True when this track already executed a rebalance on the local trading day."""
    last_path = Path(output_dir) / REPORT_FILENAME
    if not last_path.exists():
        return False
    try:
        payload = json.loads(last_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not payload.get("acted"):
        return False
    gate = payload.get("gate") or {}
    last_local = gate.get("local_time") or payload.get("generated_at")
    if not last_local:
        return False
    try:
        last_dt = datetime.fromisoformat(str(last_local).replace("Z", "+00:00"))
    except ValueError:
        return False
    current = local_now(config, when)
    return last_dt.astimezone(config.tz()).date() == current.date()


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
    avg_cost: float | None = None,
    screen_row: dict[str, Any] | None = None,
    use_adjusted_signal: bool = False,
) -> list[SurveillanceAlert]:
    from value_investor.hypothesis_integrity import (
        ACTION_EXIT_CANDIDATE,
        ACTION_WATCH_REVIEW,
        THESIS_BROKEN,
        THESIS_INTACT,
        THESIS_WEAKENING,
        assess_holding_hypothesis,
    )

    alerts: list[SurveillanceAlert] = []
    hypothesis: dict[str, Any] | None = None
    if avg_cost is not None and avg_cost > 0 and mark is not None:
        hypothesis = assess_holding_hypothesis(
            ticker=ticker,
            mark=mark,
            avg_cost=float(avg_cost),
            row=screen_row,
            use_adjusted_signal=use_adjusted_signal,
        )

    if mark is not None and stop_loss is not None and mark <= stop_loss:
        # Prefer hypothesis framing over a crude stop-only action alert.
        if hypothesis and hypothesis.get("thesis_status") == THESIS_INTACT:
            alerts.append(
                SurveillanceAlert(
                    ticker=ticker,
                    name=name,
                    source=source,
                    severity="watch",
                    message=(
                        f"Mark {mark:.2f} at/under tactical stop {stop_loss:.2f}, "
                        "but thesis intact — review facts before exiting"
                    ),
                    mark=mark,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    timing_signal=timing_signal,
                )
            )
        elif hypothesis and hypothesis.get("thesis_status") == THESIS_BROKEN:
            alerts.append(
                SurveillanceAlert(
                    ticker=ticker,
                    name=name,
                    source=source,
                    severity="action",
                    message=(
                        f"Stop + broken thesis ({mark:.2f} ≤ {stop_loss:.2f}): "
                        + "; ".join((hypothesis.get("reasons") or [])[:2])
                    ),
                    mark=mark,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    timing_signal=timing_signal,
                )
            )
        else:
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
    if hypothesis and hypothesis.get("underwater"):
        status = hypothesis.get("thesis_status")
        action = hypothesis.get("recommended_action")
        reason = "; ".join((hypothesis.get("reasons") or [])[:2]) or "see hypothesis card"
        if status == THESIS_BROKEN or action == ACTION_EXIT_CANDIDATE:
            alerts.append(
                SurveillanceAlert(
                    ticker=ticker,
                    name=name,
                    source=source,
                    severity="action",
                    message=f"Underwater + thesis broken — exit candidate: {reason}",
                    mark=mark,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    timing_signal=timing_signal,
                )
            )
        elif status == THESIS_WEAKENING or action == ACTION_WATCH_REVIEW:
            alerts.append(
                SurveillanceAlert(
                    ticker=ticker,
                    name=name,
                    source=source,
                    severity="watch",
                    message=f"Underwater — re-check hypothesis: {reason}",
                    mark=mark,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    timing_signal=timing_signal,
                )
            )
        elif status == THESIS_INTACT:
            alerts.append(
                SurveillanceAlert(
                    ticker=ticker,
                    name=name,
                    source=source,
                    severity="info",
                    message=(
                        f"Underwater but thesis intact — tolerate within loser band: {reason}"
                    ),
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
        "updated_at": datetime.now(UTC).isoformat(),
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
    mode = str(config.strategy_mode or "automated")
    if mode not in {"automated", "technical"}:
        mode = "automated"
    fund_name = config.track_label or (
        "Technical levels" if mode == "technical" else "Automated stock picking"
    )
    if path.exists():
        fund = PaperFund.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if fund.config.mode != mode:
            fund.config.mode = mode  # type: ignore[assignment]
        sync_fund_from_automation_config(fund, config)
        return fund
    fund = PaperFund.create(
        PaperFundConfig(
            name=fund_name,
            mode=mode,
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
        if isinstance(payload, list):
            return list(payload)
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
            row["sma_50"] = tech.sma_50
            row["sma_200"] = tech.sma_200
            row["macd_histogram"] = tech.macd_histogram
            row["macd_histogram_prev"] = tech.macd_histogram_prev
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
                    avg_cost=float(position.avg_cost or 0) or None,
                    screen_row=row or None,
                    use_adjusted_signal=bool(config.use_adjusted_signal),
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
            avg_cost = item.get("avg_cost") or item.get("cost")
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
                    avg_cost=float(avg_cost) if avg_cost is not None else None,
                    screen_row=row or None,
                    use_adjusted_signal=bool(config.use_adjusted_signal),
                )
            )
    return alerts


def _marked_price_map(
    marked_rows: list[dict[str, Any]],
    fund: PaperFund,
) -> dict[str, float]:
    prices: dict[str, float] = {}
    for row in marked_rows:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        for key in ("price", "last", "close"):
            value = row.get(key)
            if value is not None and float(value) > 0:
                prices[ticker] = float(value)
                break
    for ticker, position in fund.holdings.items():
        prices.setdefault(ticker, float(position.avg_cost or 0))
    for trade in fund.trades:
        if str(trade.side) == "sell" and trade.ticker not in prices:
            prices[trade.ticker] = float(trade.price)
    return prices


@dataclass
class AutomationRunResult:
    acted: bool
    gate: dict[str, Any]
    trades: list[dict[str, Any]] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    fund: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    exit_shadow_review: dict[str, Any] = field(default_factory=dict)
    exit_timing_cohorts_review: dict[str, Any] = field(default_factory=dict)
    hypothesis_integrity: dict[str, Any] = field(default_factory=dict)
    hypothesis_outcome_link: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "acted": self.acted,
            "gate": self.gate,
            "trades": self.trades,
            "plan": self.plan,
            "alerts": self.alerts,
            "fund": self.fund,
            "note": self.note,
            "exit_shadow_review": self.exit_shadow_review,
            "exit_timing_cohorts_review": self.exit_timing_cohorts_review,
            "hypothesis_integrity": self.hypothesis_integrity,
            "hypothesis_outcome_link": self.hypothesis_outcome_link,
            "generated_at": datetime.now(UTC).isoformat(),
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
    select_kwargs = config.selection_kwargs()
    rebalance_kwargs = _rebalance_kwargs(select_kwargs)

    price_map_pre = _marked_price_map(marked, fund)
    nav_before = fund.nav(price_map_pre)
    cash_before = float(fund.cash)
    contributed_before = float(fund.contributed_capital)
    holdings_before = snapshot_holdings(fund)
    rebalance_state_before = fund.rebalance_state.to_dict()
    decision_candidates = collect_decision_candidates(
        marked,
        fund,
        use_adjusted_signal=config.use_adjusted_signal,
    )
    screen_buy_tier = collect_screen_buy_tier(marked, fund)
    gate_excluded = gate_excluded_tickers(screen_buy_tier, decision_candidates)

    plan: dict[str, Any] = {}
    if fund.config.mode == "automated":
        plan = preview_automated_plan(fund, marked, **rebalance_kwargs)
    elif fund.config.mode == "technical":
        plan = preview_technical_plan(fund, marked)
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
    if (
        can_act
        and config.auto_rebalance
        and not force
        and already_rebalanced_today(output_dir, config, now)
    ):
        can_act = False
        note = (
            "Already rebalanced today for this track — skipping duplicate pass "
            "(use --force to override)."
        )
    if can_act and config.auto_rebalance:
        fund.apply_deposits_to(gate["local_time"])
        if fund.config.mode == "technical":
            executed = run_technical_pass(fund, marked, acted_at=gate["local_time"])
        elif config.use_graduated_allocation:
            executed = run_graduated_rebalance(
                fund, marked, acted_at=gate["local_time"], **rebalance_kwargs
            )
        else:
            executed = run_automated_rebalance(
                fund, marked, acted_at=gate["local_time"], **rebalance_kwargs
            )
        trades = [t.to_dict() for t in executed]
        save_automated_fund(fund_path, fund)
        acted = True
        note = (
            f"Technical pass after open settle ({len(trades)} trade(s))."
            if fund.config.mode == "technical"
            else f"Rebalanced after open settle ({len(trades)} trade(s))."
        )
        if fund.config.mode == "automated":
            plan = preview_automated_plan(fund, marked, **rebalance_kwargs)
        else:
            plan = preview_technical_plan(fund, marked)
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

    price_map = _marked_price_map(marked, fund)
    exit_shadow_review = run_exit_shadow_pass(
        output_dir=output_dir,
        fund=fund,
        track_id=config.track_id,
        prices_by_ticker=price_map,
        as_of=gate["local_time"],
    )
    exit_timing_cohorts_review = run_exit_timing_cohort_pass(
        output_dir=output_dir,
        fund=fund,
        track_id=config.track_id,
        candidates=decision_candidates,
        trades=trades,
        prices_by_ticker=price_map,
        trade_cost_pct=float(config.trade_cost_pct),
        as_of=gate["local_time"],
        use_adjusted_signal=bool(config.use_adjusted_signal),
    )
    hypothesis_integrity = run_hypothesis_integrity_pass(
        output_dir=output_dir,
        fund=fund,
        track_id=str(config.track_id or "rules"),
        candidates=marked,
        prices_by_ticker=price_map,
        use_adjusted_signal=bool(config.use_adjusted_signal),
        as_of=gate["local_time"],
    )
    hypothesis_outcome_link = run_hypothesis_outcome_link_pass(
        output_dir=output_dir,
        track_id=str(config.track_id or "rules"),
        candidates=decision_candidates,
        use_adjusted_signal=bool(config.use_adjusted_signal),
        as_of=gate["local_time"],
    )

    result = AutomationRunResult(
        acted=acted,
        gate=gate,
        trades=trades,
        plan=plan,
        alerts=alerts,
        fund=fund.to_dict(),
        note=note,
        exit_shadow_review=exit_shadow_review,
        exit_timing_cohorts_review=exit_timing_cohorts_review,
        hypothesis_integrity=hypothesis_integrity,
        hypothesis_outcome_link=hypothesis_outcome_link,
    )
    payload = result.to_dict()
    payload["track_id"] = config.track_id
    payload["track_label"] = config.track_label
    payload["is_primary_learning_track"] = config.is_primary_learning_track
    payload["selection"] = config.selection_kwargs()
    (output_dir / REPORT_FILENAME).write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    price_map_post = _marked_price_map(marked, fund)
    log_entry = build_rebalance_log_entry(
        track_id=str(config.track_id or "rules"),
        track_label=str(config.track_label or ""),
        strategy_mode=str(config.strategy_mode or "automated"),
        gate=gate,
        acted=acted,
        note=note,
        selection=config.selection_kwargs(),
        max_positions=int(config.max_positions),
        trade_cost_pct=float(config.trade_cost_pct),
        screen_source=resolve_screen_source(reports_path),
        knob_epoch_started_at=load_knob_epoch_started_at(output_dir),
        candidates=decision_candidates,
        screen_buy_tier=screen_buy_tier,
        gate_excluded=gate_excluded,
        plan=plan,
        trades=trades,
        nav_before=nav_before,
        cash_before=cash_before,
        contributed_capital_before=contributed_before,
        holdings_before=holdings_before,
        rebalance_state_before=rebalance_state_before,
        nav_after=fund.nav(price_map_post),
        cash_after=float(fund.cash),
        holdings_after=snapshot_holdings(fund),
        rebalance_state_after=fund.rebalance_state.to_dict(),
    )
    append_rebalance_log(output_dir, log_entry)
    return result


def ensure_learning_track_configs(base_dir: Path) -> dict[str, AutomationConfig]:
    """Ensure rules (control) + AI judgment (primary) configs exist under base_dir."""
    base_dir = Path(base_dir)
    dirs = learning_track_dirs(base_dir)
    configs: dict[str, AutomationConfig] = {}

    rules_path = dirs[RULES_TRACK_ID] / CONFIG_FILENAME
    if rules_path.exists():
        rules = AutomationConfig.from_dict(json.loads(rules_path.read_text(encoding="utf-8")))
        # Preserve knobs; stamp track metadata if missing/outdated.
        rules.track_id = RULES_TRACK_ID
        rules.is_primary_learning_track = False
        rules.strategy_mode = "automated"
        rules.use_adjusted_signal = False
        rules.require_research_accumulate = False
        if not rules.track_label or rules.track_label == "Screen rules (control)":
            rules.track_label = "Screen rules (control)"
    else:
        rules = default_rules_config()
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(json.dumps(rules.to_dict(), indent=2), encoding="utf-8")
    configs[RULES_TRACK_ID] = rules

    ai_dir = dirs[AI_JUDGMENT_TRACK_ID]
    ai_path = ai_dir / CONFIG_FILENAME
    ai_dir.mkdir(parents=True, exist_ok=True)
    if ai_path.exists():
        ai = AutomationConfig.from_dict(json.loads(ai_path.read_text(encoding="utf-8")))
        ai.track_id = AI_JUDGMENT_TRACK_ID
        ai.is_primary_learning_track = True
        ai.use_adjusted_signal = True
        ai.require_research_accumulate = True
        ai.track_label = ai.track_label or "AI judgment (research accumulate + adjusted_signal)"
        # Inherit shared operational settings from rules when unset-like.
        ai.timezone = rules.timezone
        ai.market_open = rules.market_open
        ai.settle_minutes_after_open = rules.settle_minutes_after_open
        ai.weekdays_only = rules.weekdays_only
        ai.trade_cost_pct = rules.trade_cost_pct
        ai.initial_cash = rules.initial_cash
    else:
        ai = default_ai_judgment_config(rules)
    ai_path.write_text(json.dumps(ai.to_dict(), indent=2), encoding="utf-8")
    configs[AI_JUDGMENT_TRACK_ID] = ai

    mg_dir = dirs[MOMENTUM_GRACE_TRACK_ID]
    mg_path = mg_dir / CONFIG_FILENAME
    mg_dir.mkdir(parents=True, exist_ok=True)
    if mg_path.exists():
        mg = AutomationConfig.from_dict(json.loads(mg_path.read_text(encoding="utf-8")))
        mg.track_id = MOMENTUM_GRACE_TRACK_ID
        mg.is_primary_learning_track = False
        mg.use_adjusted_signal = False
        mg.require_research_accumulate = False
        mg.use_momentum_grace = True
        mg.track_label = mg.track_label or "Screen rules + momentum grace"
        mg.timezone = rules.timezone
        mg.market_open = rules.market_open
        mg.settle_minutes_after_open = rules.settle_minutes_after_open
        mg.weekdays_only = rules.weekdays_only
        mg.trade_cost_pct = rules.trade_cost_pct
        mg.initial_cash = rules.initial_cash
    else:
        mg = default_momentum_grace_config(rules)
    mg_path.write_text(json.dumps(mg.to_dict(), indent=2), encoding="utf-8")
    configs[MOMENTUM_GRACE_TRACK_ID] = mg

    ga_dir = dirs[GRADUATED_ALLOCATION_TRACK_ID]
    ga_path = ga_dir / CONFIG_FILENAME
    ga_dir.mkdir(parents=True, exist_ok=True)
    if ga_path.exists():
        ga = AutomationConfig.from_dict(json.loads(ga_path.read_text(encoding="utf-8")))
        ga.track_id = GRADUATED_ALLOCATION_TRACK_ID
        ga.is_primary_learning_track = False
        ga.use_adjusted_signal = False
        ga.require_research_accumulate = False
        ga.use_graduated_allocation = True
        ga.use_momentum_grace = False
        ga.track_label = ga.track_label or "Screen rules + graduated allocation"
        ga.timezone = rules.timezone
        ga.market_open = rules.market_open
        ga.settle_minutes_after_open = rules.settle_minutes_after_open
        ga.weekdays_only = rules.weekdays_only
        ga.trade_cost_pct = rules.trade_cost_pct
        ga.initial_cash = rules.initial_cash
        if int(ga.max_positions) < 4:
            ga.max_positions = 4
    else:
        ga = default_graduated_allocation_config(rules)
    ga_path.write_text(json.dumps(ga.to_dict(), indent=2), encoding="utf-8")
    configs[GRADUATED_ALLOCATION_TRACK_ID] = ga

    tech_dir = dirs[TECHNICAL_TRACK_ID]
    tech_path = tech_dir / CONFIG_FILENAME
    tech_dir.mkdir(parents=True, exist_ok=True)
    if tech_path.exists():
        tech = AutomationConfig.from_dict(json.loads(tech_path.read_text(encoding="utf-8")))
        tech.track_id = TECHNICAL_TRACK_ID
        tech.is_primary_learning_track = False
        tech.strategy_mode = "technical"
        tech.use_adjusted_signal = False
        tech.require_research_accumulate = False
        tech.use_momentum_grace = False
        tech.track_label = tech.track_label or "Technical levels (stops / trade_plan)"
        tech.timezone = rules.timezone
        tech.market_open = rules.market_open
        tech.settle_minutes_after_open = rules.settle_minutes_after_open
        tech.weekdays_only = rules.weekdays_only
        tech.trade_cost_pct = rules.trade_cost_pct
        tech.initial_cash = rules.initial_cash
    else:
        tech = default_technical_config(rules)
    tech_path.write_text(json.dumps(tech.to_dict(), indent=2), encoding="utf-8")
    configs[TECHNICAL_TRACK_ID] = tech

    calibrated_dir = base_dir / AI_JUDGMENT_CALIBRATED_SUBDIR
    calibrated_path = calibrated_dir / CONFIG_FILENAME
    if calibrated_path.exists():
        calibrated = AutomationConfig.from_dict(
            json.loads(calibrated_path.read_text(encoding="utf-8"))
        )
        calibrated.track_id = AI_JUDGMENT_CALIBRATED_TRACK_ID
        calibrated.is_primary_learning_track = False
        calibrated.is_calibration_shadow = True
        calibrated.calibration_parent_track = (
            calibrated.calibration_parent_track or AI_JUDGMENT_TRACK_ID
        )
        calibrated.use_adjusted_signal = True
        calibrated.require_research_accumulate = True
        calibrated.track_label = calibrated.track_label or (
            "AI judgment calibrated shadow (frozen priors)"
        )
        calibrated.timezone = rules.timezone
        calibrated.market_open = rules.market_open
        calibrated.settle_minutes_after_open = rules.settle_minutes_after_open
        calibrated.weekdays_only = rules.weekdays_only
        calibrated.trade_cost_pct = rules.trade_cost_pct
        calibrated.initial_cash = rules.initial_cash
        calibrated_path.write_text(json.dumps(calibrated.to_dict(), indent=2), encoding="utf-8")
        configs[AI_JUDGMENT_CALIBRATED_TRACK_ID] = calibrated

    # Competing calibrated shadows (rank 2+)
    from value_investor.knob_calibration import (
        calibrated_shadow_subdir,
        calibrated_shadow_track_id,
        discover_calibration_shadow_ranks,
    )

    for rank in discover_calibration_shadow_ranks(base_dir):
        if rank <= 1:
            continue
        track_id = calibrated_shadow_track_id(rank)
        shadow_dir = base_dir / calibrated_shadow_subdir(rank)
        shadow_path = shadow_dir / CONFIG_FILENAME
        if not shadow_path.exists():
            continue
        shadow = AutomationConfig.from_dict(json.loads(shadow_path.read_text(encoding="utf-8")))
        shadow.track_id = track_id
        shadow.is_primary_learning_track = False
        shadow.is_calibration_shadow = True
        shadow.calibration_parent_track = shadow.calibration_parent_track or AI_JUDGMENT_TRACK_ID
        shadow.use_adjusted_signal = True
        shadow.require_research_accumulate = True
        shadow.track_label = shadow.track_label or (
            f"AI judgment calibrated shadow rank {rank} (frozen priors)"
        )
        shadow.timezone = rules.timezone
        shadow.market_open = rules.market_open
        shadow.settle_minutes_after_open = rules.settle_minutes_after_open
        shadow.weekdays_only = rules.weekdays_only
        shadow.trade_cost_pct = rules.trade_cost_pct
        shadow.initial_cash = rules.initial_cash
        shadow_path.write_text(json.dumps(shadow.to_dict(), indent=2), encoding="utf-8")
        configs[track_id] = shadow

    from value_investor.exclusion_ladder_replay import (
        discover_exclusion_shadow_step_ids,
        exclusion_shadow_subdir,
        exclusion_shadow_track_id,
    )

    for step_id in discover_exclusion_shadow_step_ids(base_dir):
        track_id = exclusion_shadow_track_id(step_id)
        shadow_dir = base_dir / exclusion_shadow_subdir(step_id)
        shadow_path = shadow_dir / CONFIG_FILENAME
        if not shadow_path.exists():
            continue
        shadow = AutomationConfig.from_dict(json.loads(shadow_path.read_text(encoding="utf-8")))
        shadow.track_id = track_id
        shadow.is_primary_learning_track = False
        shadow.is_exclusion_shadow = True
        shadow.exclusion_parent_track = shadow.exclusion_parent_track or AI_JUDGMENT_TRACK_ID
        shadow.exclusion_ladder_step_id = shadow.exclusion_ladder_step_id or step_id
        shadow.is_calibration_shadow = False
        shadow.use_adjusted_signal = True
        shadow.require_research_accumulate = True
        shadow.track_label = shadow.track_label or (
            f"AI judgment exclusion ladder {step_id} (frozen priors)"
        )
        shadow.timezone = rules.timezone
        shadow.market_open = rules.market_open
        shadow.settle_minutes_after_open = rules.settle_minutes_after_open
        shadow.weekdays_only = rules.weekdays_only
        shadow.trade_cost_pct = rules.trade_cost_pct
        shadow.initial_cash = rules.initial_cash
        shadow_path.write_text(json.dumps(shadow.to_dict(), indent=2), encoding="utf-8")
        configs[track_id] = shadow

    return configs


def run_learning_tracks(
    *,
    base_dir: Path = DEFAULT_AUTOMATION_DIR,
    reports_path: Path | None = None,
    now: datetime | None = None,
    force: bool = False,
    tracks: list[str] | None = None,
    surveillance_only: bool = False,
) -> dict[str, Any]:
    """
    Run the primary AI-judgment learning track plus the rules control book.

    Success for the primary track is later judged by decision-review excess
    vs the market benchmark (and vs the rules control), not by human trade confirms.
    """
    base_dir = Path(base_dir)
    configs = ensure_learning_track_configs(base_dir)
    dirs = learning_track_dirs(base_dir)
    default_tracks = [
        TECHNICAL_TRACK_ID,
        RULES_TRACK_ID,
        AI_JUDGMENT_TRACK_ID,
        MOMENTUM_GRACE_TRACK_ID,
        GRADUATED_ALLOCATION_TRACK_ID,
    ]
    shadow_ids = [
        track_id
        for track_id, cfg in configs.items()
        if getattr(cfg, "is_calibration_shadow", False)
        or getattr(cfg, "is_exclusion_shadow", False)
    ]
    insert_at = default_tracks.index(AI_JUDGMENT_TRACK_ID) + 1
    for track_id in sorted(shadow_ids):
        if track_id not in default_tracks:
            default_tracks.insert(insert_at, track_id)
            insert_at += 1
    wanted = list(tracks) if tracks else default_tracks
    results: dict[str, Any] = {}
    for track_id in wanted:
        if track_id not in configs:
            continue
        cfg = configs[track_id]
        if surveillance_only:
            cfg = AutomationConfig.from_dict(cfg.to_dict())
            cfg.auto_rebalance = False
        result = run_daily_automation(
            output_dir=dirs[track_id],
            config=cfg,
            reports_path=reports_path,
            now=now,
            force=force,
        )
        results[track_id] = {
            "output_dir": str(dirs[track_id]),
            "acted": result.acted,
            "trades": len(result.trades),
            "note": result.note,
            "is_primary_learning_track": cfg.is_primary_learning_track,
            "selection": cfg.selection_kwargs(),
        }
    summary = {
        "schema_version": 1,
        "primary_learning_track": AI_JUDGMENT_TRACK_ID,
        "success_criterion": (
            "Outperformance after costs vs market benchmark (^FTSE) on the "
            "primary AI-judgment track; rules track is the control; "
            "technical track is the timing/levels baseline; "
            "momentum_grace is an experimental exit overlay; "
            "graduated_allocation tests trade-plan entry sizing and harvest skims; "
            "hypothesis_integrity reviews underwater holdings before crude stops."
        ),
        "tracks": results,
    }
    (base_dir / "learning_tracks_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    shadow_summary = summarize_learning_tracks_exit_shadow(base_dir)
    (base_dir / "learning_tracks_exit_shadow.json").write_text(
        json.dumps(shadow_summary, indent=2) + "\n",
        encoding="utf-8",
    )
    timing_summary = summarize_learning_tracks_exit_timing(base_dir)
    (base_dir / "learning_tracks_exit_timing.json").write_text(
        json.dumps(timing_summary, indent=2) + "\n",
        encoding="utf-8",
    )
    hypothesis_summary = summarize_learning_tracks_hypothesis_integrity(base_dir)
    (base_dir / HYPOTHESIS_ROLLUP_FILENAME).write_text(
        json.dumps(hypothesis_summary, indent=2) + "\n",
        encoding="utf-8",
    )
    outcomes_summary = summarize_learning_tracks_hypothesis_outcomes(base_dir)
    (base_dir / HYPOTHESIS_OUTCOMES_ROLLUP_FILENAME).write_text(
        json.dumps(outcomes_summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


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
