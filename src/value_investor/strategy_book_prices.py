"""Daily close refresh for the strategy book (registration section 11).

Rebuilds a chart whose last close is behind that market's latest completed
session and leaves a current chart alone. Uses ``ensure_price_charts`` and
``fetch_price_history`` (adjusted closes, ``auto_adjust=True``). Does not
score episodes.

Ops limits below are not registration thresholds. They keep one run inside
the weekday job's time and Yahoo's batch behaviour. The trigger is a named
weekday cron after the cash closes, not ops-monitor: see
``docs/ops/strategy-book-observe.md``.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from value_investor.price_charts import (
    chart_filename,
    chart_last_close_date,
    ensure_price_charts,
)
from value_investor.storage import read_json, write_json
from value_investor.strategy_book_rules import (
    CLOSES_STATE_NAME,
    MARKET_CLOSE_LOCAL,
    STALE_CLOSE_MAX_SHARE,
    UnknownMarketClose,
    session_close,
)
from value_investor.strategy_book_signals import (
    BUY_SIGNALS,
    history_dir_for,
    newest_screen_run,
    repo_paths,
    screen_rows,
    universe_markets,
)

# One run may download this many names. The rest wait for the next weekday.
NAMES_PER_RUN = 500
# Pause between market batches. Tests pass 0.
PAUSE_SECONDS = 1.0
SAMPLE_TICKERS = 8


def previous_weekday(day: date) -> date:
    """The weekday before ``day``. Monday returns Friday."""
    step = day - timedelta(days=1)
    while step.weekday() >= 5:
        step -= timedelta(days=1)
    return step


def latest_completed_session(market: str, now: datetime) -> date | None:
    """Latest weekday whose cash close is at or before ``now``.

    Unknown markets return None. Weekends are not sessions.
    """
    moment = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    try:
        zone_name, _hhmm = MARKET_CLOSE_LOCAL[market]
    except KeyError:
        return None
    local_day = moment.astimezone(ZoneInfo(zone_name)).date()
    for offset in range(12):
        day = local_day - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        try:
            closed = session_close(market, day)
        except UnknownMarketClose:
            return None
        if closed <= moment:
            return day
    return None


def _aware(now: datetime) -> datetime:
    return now if now.tzinfo is not None else now.replace(tzinfo=UTC)


def _last_close(path: Path) -> date | None:
    if not path.is_file():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return chart_last_close_date(payload)


def _buy_rows(history: Path, session: date) -> dict[str, dict[str, Any]]:
    _path, payload, _day = newest_screen_run(history, session)
    rows: dict[str, dict[str, Any]] = {}
    for ticker, row in screen_rows(payload).items():
        if str(row.get("signal") or "").strip() in BUY_SIGNALS:
            rows[ticker] = row
    return rows


def _extra_tickers(observe_path: Path) -> dict[str, set[str]]:
    """Open-episode names and their basket members, by market."""
    extra: dict[str, set[str]] = {}
    if not observe_path.is_file():
        return extra
    try:
        payload = read_json(observe_path)
    except (OSError, ValueError, TypeError):
        return extra
    if not isinstance(payload, dict):
        return extra
    for episode in payload.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        market = str(episode.get("market") or "")
        if not market:
            continue
        bucket = extra.setdefault(market, set())
        if episode.get("status") == "open" and episode.get("ticker"):
            bucket.add(str(episode["ticker"]).upper())
        basket = episode.get("basket") if isinstance(episode.get("basket"), dict) else {}
        for member in basket.get("members") or []:
            if isinstance(member, dict) and member.get("ticker"):
                bucket.add(str(member["ticker"]).upper())
    return extra


def _report(ticker: str, row: dict[str, Any] | None) -> dict[str, Any]:
    source = row or {}
    return {
        "ticker": ticker,
        "name": str(source.get("name") or ticker),
        "signal": str(source.get("signal") or ""),
    }


def plan_close_refresh(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    budget: int = NAMES_PER_RUN,
) -> dict[str, Any]:
    """Which charts would refresh. Does not download or write.

    A name is due when its last close is missing or earlier than that
    market's latest completed session. Current charts are left alone.
    """
    moment = _aware(now or datetime.now(UTC))
    paths = repo_paths(repo_root)
    markets = universe_markets(paths.market_status)
    extras = _extra_tickers(paths.observe)
    remaining = max(int(budget), 0)
    planned: dict[str, Any] = {}
    errors: list[str] = []
    for market in markets:
        completed = latest_completed_session(market, moment)
        if completed is None:
            errors.append(f"{market}: unknown close")
            continue
        prior = previous_weekday(completed)
        rows = _buy_rows(history_dir_for(paths, market), completed)
        wanted = list(rows)
        for ticker in sorted(extras.get(market) or ()):
            if ticker not in rows:
                wanted.append(ticker)
        due: list[str] = []
        current: list[str] = []
        behind_session: list[str] = []
        for ticker in wanted:
            last = _last_close(paths.charts / chart_filename(ticker))
            if last is None or last < completed:
                due.append(ticker)
            else:
                current.append(ticker)
            if ticker in rows and (last is None or last < prior):
                behind_session.append(ticker)
        take = due[:remaining]
        remaining -= len(take)
        buy_count = len(rows)
        share = (len(behind_session) / buy_count) if buy_count else 0.0
        planned[market] = {
            "closes_through": completed.isoformat(),
            "prior_session": prior.isoformat(),
            "buy_tier": buy_count,
            "covered": len(wanted),
            "would_refresh": len(due),
            "left_alone": len(current),
            "budget_take": len(take),
            "refresh_tickers": take,
            "more_than_one_session_behind": len(behind_session),
            "stale_share": round(share, 4),
            "stale": share > STALE_CLOSE_MAX_SHARE,
            "sample_tickers": behind_session[:SAMPLE_TICKERS],
            "reports": {ticker: _report(ticker, rows.get(ticker)) for ticker in take},
        }
    return {
        "generated_at": moment.isoformat(),
        "dry_run": True,
        "budget": int(budget),
        "markets": planned,
        "errors": errors,
        "would_refresh": sum(int(row["would_refresh"]) for row in planned.values()),
        "left_alone": sum(int(row["left_alone"]) for row in planned.values()),
        "budget_take": sum(int(row["budget_take"]) for row in planned.values()),
    }


def run_close_refresh(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    apply: bool = False,
    persist: bool | None = None,
    budget: int = NAMES_PER_RUN,
    pause_seconds: float = PAUSE_SECONDS,
) -> dict[str, Any]:
    """Refresh due charts when ``apply`` is true. A dry run only lists them.

    ``persist`` defaults to ``apply``. The state file records ``closes_through``
    per market. Charts that are already current are not rewritten.
    """
    moment = _aware(now or datetime.now(UTC))
    plan = plan_close_refresh(repo_root=repo_root, now=moment, budget=budget)
    # Each market's due list is keyed on its latest completed session, so a
    # Friday slot that GitHub starts on Saturday still fetches Friday's closes.
    # A weekend run with nothing due fetches and writes nothing.
    if apply and moment.weekday() >= 5 and int(plan.get("budget_take") or 0) == 0:
        plan["dry_run"] = True
        plan["skipped"] = "weekend"
        plan["fetched"] = 0
        return _public_plan(plan)
    paths = repo_paths(repo_root)
    fetched = 0
    if apply:
        for market, row in plan["markets"].items():
            take = list(row.get("refresh_tickers") or [])
            if not take:
                continue
            reports = list((row.get("reports") or {}).values())
            try:
                ensure_price_charts(
                    reports=reports,
                    chart_dir=paths.charts,
                    tickers=take,
                    as_of=moment,
                    fetch=True,
                    market=market,
                    refresh_stale=False,
                    closes_through=date.fromisoformat(str(row["closes_through"])),
                    last_session=date.fromisoformat(str(row["closes_through"])),
                )
            except (OSError, ValueError, TypeError) as exc:
                plan["errors"].append(f"{market}: {exc}")
                continue
            fetched += len(take)
            if pause_seconds > 0:
                time.sleep(pause_seconds)
        plan["dry_run"] = False
    plan["fetched"] = fetched
    # Remember the buy-tier names that were behind so the post-refresh
    # measure does not need another screen read. The planner already counted
    # them; remeasure reads the chart dates again after a fetch.
    for market, row in plan["markets"].items():
        completed = date.fromisoformat(str(row["closes_through"]))
        prior = date.fromisoformat(str(row["prior_session"]))
        rows = _buy_rows(history_dir_for(paths, market), completed)
        behind: list[str] = []
        short: list[str] = []
        for ticker in rows:
            last = _last_close(paths.charts / chart_filename(ticker))
            if last is None or last < prior:
                behind.append(ticker)
            if last is None or last < completed:
                short.append(ticker)
        buy_count = len(rows)
        share = (len(behind) / buy_count) if buy_count else 0.0
        row["more_than_one_session_behind"] = len(behind)
        row["stale_share"] = round(share, 4)
        row["stale"] = share > STALE_CLOSE_MAX_SHARE
        row["sample_tickers"] = behind[:SAMPLE_TICKERS]
        # Not the registration stale rule. Counts buy-tier charts that still
        # end before closes_through, e.g. when Yahoo has not yet published the
        # session's daily bar. The next slot retries them.
        row["short_of_session"] = len(short)
        row["short_sample_tickers"] = short[:SAMPLE_TICKERS]
        row.pop("reports", None)
    public = _public_plan(plan)
    should_persist = apply if persist is None else persist
    if should_persist:
        state = {
            "generated_at": public["generated_at"],
            "dry_run": public["dry_run"],
            "fetched": public["fetched"],
            "closes_through": {
                market: row["closes_through"] for market, row in public["markets"].items()
            },
            "markets": public["markets"],
            "errors": public["errors"],
        }
        dest = paths.data / CLOSES_STATE_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        stored = {
            **state,
            "markets": {
                market: {key: value for key, value in row.items() if key != "refresh_tickers"}
                for market, row in state["markets"].items()
            },
        }
        write_json(dest, stored, compact=False)
        public["wrote"] = str(dest)
    return public


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Drop the in-memory report rows. Counts and ticker names stay."""
    markets: dict[str, Any] = {}
    for market, row in (plan.get("markets") or {}).items():
        markets[market] = {key: value for key, value in row.items() if key != "reports"}
    return {
        "generated_at": plan.get("generated_at"),
        "dry_run": bool(plan.get("dry_run", True)),
        "skipped": plan.get("skipped"),
        "budget": plan.get("budget"),
        "fetched": int(plan.get("fetched") or 0),
        "would_refresh": int(plan.get("would_refresh") or 0),
        "left_alone": int(plan.get("left_alone") or 0),
        "budget_take": int(plan.get("budget_take") or 0),
        "markets": markets,
        "errors": list(plan.get("errors") or []),
    }


def short_markets(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Markets whose buy-tier charts still end before ``closes_through`` after a fetch."""
    if not isinstance(state, dict) or state.get("dry_run"):
        return []
    found: list[dict[str, Any]] = []
    markets = state.get("markets") if isinstance(state.get("markets"), dict) else {}
    for market, row in markets.items():
        if not isinstance(row, dict) or int(row.get("short_of_session") or 0) <= 0:
            continue
        found.append(
            {
                "market": market,
                "closes_through": row.get("closes_through"),
                "buy_tier": row.get("buy_tier"),
                "short": int(row.get("short_of_session") or 0),
                "sample_tickers": list(row.get("short_sample_tickers") or []),
            }
        )
    return found


def stale_markets(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Markets whose post-refresh buy tier is more than a tenth behind."""
    if not isinstance(state, dict):
        return []
    found: list[dict[str, Any]] = []
    markets = state.get("markets") if isinstance(state.get("markets"), dict) else {}
    for market, row in markets.items():
        if not isinstance(row, dict) or not row.get("stale"):
            continue
        found.append(
            {
                "market": market,
                "buy_tier": row.get("buy_tier"),
                "behind": row.get("more_than_one_session_behind"),
                "sample_tickers": list(row.get("sample_tickers") or []),
            }
        )
    return found
