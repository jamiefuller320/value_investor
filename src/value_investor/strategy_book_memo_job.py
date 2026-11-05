"""Signal-day and review-date memo job for the strategy book.

Observe-only. Spend is off until ``docs/data/strategy_book_registration.json``
exists, carries a signature, and sets ``spend_enabled`` true. While off, each
request is logged ``dry_run`` at the registered $0.40 estimate and no model
is called.

The forward walker is step 2.3 and is not imported here. This job evaluates
the shared entry signal itself, for each market close that has passed since
the last run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from value_investor.agent_model_policy import (
    SPEND_POOL_WEEKLY_OPS,
    record_estimated_spend,
    weekly_ops_budget_status,
)
from value_investor.library_decision_input_inventory import _memo_as_of
from value_investor.market_paper_shard import session_defaults_for_market
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.research.weekday_rememo import DEFAULT_MIN_HEADROOM_USD
from value_investor.sector_headwind_gate import FTSE_MARKET
from value_investor.storage import write_json
from value_investor.strategy_book_rules import registration_record, registration_signed
from value_investor.strategy_book_signals import (
    MEMO_MAX_AGE_DAYS,
    STALE_CHART_CALENDAR_DAYS,
    MarketSignals,
    RepoPaths,
    _load_json,
    _memo_age_days,
    evaluate_market,
    history_dir_for,
    load_chart_closes,
    newest_screen_run,
    repo_paths,
    research_root_for,
    review_memo_needs,
    screen_rows,
    session_end,
    universe_markets,
)

# Registration section 11: about $0.40 a memo, from the weekly_ops pool.
ESTIMATED_MEMO_USD = 0.40
# Registration section 11: about 25–35 memos a week (owner, 2026-11-05).
WEEKLY_MEMO_ESTIMATE_LOW = 25
WEEKLY_MEMO_ESTIMATE_HIGH = 35
# Registration section 12: memo_not_ready exceeds a fifth of otherwise-eligible signals.
MEMO_NOT_READY_MAX_SHARE = 0.2

SCHEMA_VERSION = 1

TITLE_REFRESHED = "Strategy book memo job refreshed"
TITLE_FAILED = "Strategy book memo job failed"
TITLE_NOT_RUN = "Strategy book memo job not run on a weekday"
TITLE_BEHIND = "Strategy book memo routine falling behind"

_LOG_KEY = ("market", "ticker", "kind", "session")


@dataclass
class MemoRequest:
    market: str
    ticker: str
    kind: str
    session: str
    review_index: int | None
    input_paths: list[str]
    screen_row: dict[str, Any] = field(default_factory=dict)


def spend_enabled(registration_path: Path) -> bool:
    """True only when the signature seal exists and ``spend_enabled`` is true.

    Signature creates ``docs/data/strategy_book_registration.json``. Until that
    file is present, signed, and the flag is true, the job does not call a model.
    The signature test is ``registration_signed``.
    """
    payload = registration_record(registration_path)
    if payload is None or payload.get("spend_enabled") is not True:
        return False
    return registration_signed(registration_path)


def data_commit(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.strip() or "unknown"


def _local_today(market: str, now: datetime) -> date:
    if market == FTSE_MARKET:
        zone = "Europe/London"
    else:
        zone = str(session_defaults_for_market(market).get("timezone") or "Europe/London")
    try:
        tz = ZoneInfo(zone)
    except Exception:  # noqa: BLE001 — unknown zone fails closed to London
        tz = ZoneInfo("Europe/London")
    moment = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return moment.astimezone(tz).date()


def _buy_tickers(history: Path, bound: date) -> list[str]:
    _path, payload, _day = newest_screen_run(history, bound)
    tickers: list[str] = []
    for ticker, row in screen_rows(payload).items():
        if str(row.get("signal") or "").strip() in BUY_SIGNALS:
            tickers.append(ticker)
    return tickers


def _chart_dates(paths: RepoPaths, tickers: list[str]) -> tuple[date | None, list[date]]:
    found: set[date] = set()
    latest: date | None = None
    for ticker in tickers:
        from value_investor.price_charts import chart_filename

        _days, _closes, all_days = load_chart_closes(
            paths.charts / chart_filename(ticker),
            date(9999, 12, 31),
        )
        for day in all_days:
            found.add(day)
            if latest is None or day > latest:
                latest = day
    return latest, sorted(found)


def plan_sessions(
    market: str,
    *,
    paths: RepoPaths,
    now: datetime,
    last_session: date | None,
    allow_stale: bool,
    replay_limit: int | None = None,
) -> dict[str, Any]:
    """Chart sessions whose close has passed and that this run should score.

    A session is due when the market's local date is after that session, so
    the close has passed without a separate close clock. The forward rule
    drops a session more than 5 calendar days behind the UTC decision date
    unless ``allow_stale`` (measurement replay).
    """
    decision = (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC).date()
    local_today = _local_today(market, now)
    history = history_dir_for(paths, market)
    tickers = _buy_tickers(history, local_today)
    latest, days = _chart_dates(paths, tickers)
    passed = [
        day for day in days if day < local_today and (last_session is None or day > last_session)
    ]
    # Newest first. The scheduled path only looks inside the 5-day window.
    # A measurement replay stops once it has ``replay_limit`` qualified closes,
    # so a two-year chart is not walked on the daily job.
    search = list(reversed(passed))
    latest_is_stale = (
        latest is not None
        and latest < local_today
        and (decision - latest).days > STALE_CHART_CALENDAR_DAYS
    )
    if not allow_stale:
        search = [day for day in search if (decision - day).days <= STALE_CHART_CALENDAR_DAYS]
    chosen_desc: list[date] = []
    for day in search:
        screen, _payload, _run_day = newest_screen_run(history, day)
        if screen is None:
            continue
        chosen_desc.append(day)
        if replay_limit is not None and len(chosen_desc) >= replay_limit:
            break
    chosen = list(reversed(chosen_desc))
    suppressed: list[str] = []
    if not allow_stale and latest_is_stale and latest is not None:
        suppressed.append(latest.isoformat())
    return {
        "market": market,
        "latest_bar": latest.isoformat() if latest else None,
        "local_today": local_today.isoformat(),
        "decision_date": decision.isoformat(),
        "buy_tier_probe": len(tickers),
        "sessions": [day.isoformat() for day in chosen],
        "suppressed_stale": suppressed,
    }


def _log_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _row_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(row.get(name) or "") for name in _LOG_KEY)  # type: ignore[return-value]


def _blocking_row(
    rows: list[dict[str, Any]], key: tuple[str, str, str, str], *, spend: bool
) -> bool:
    matches = [row for row in rows if _row_key(row) == key]
    if not matches:
        return False
    if any(row.get("action") in {"requested", "skipped"} for row in matches):
        return True
    if not spend:
        return any(row.get("action") == "dry_run" for row in matches)
    # A dry run is not a memo. Spend flipping on may still request this close.
    return False


def _sha256(path: Path, cache: dict[str, str]) -> str | None:
    key = str(path)
    if key in cache:
        return cache[key]
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    cache[key] = digest.hexdigest()
    return cache[key]


def _inputs(paths: list[str], *, repo_root: Path, cache: dict[str, str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        digest = _sha256(path, cache)
        if digest is None:
            continue
        try:
            rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel = path.as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        out.append({"path": rel, "sha256": digest})
    return out


def _week_key(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _empty_week() -> dict[str, Any]:
    return {
        "signals": 0,
        "all_but_memo": 0,
        "memo_needed": 0,
        "dry_run_requests": 0,
        "requested": 0,
        "skipped_budget": 0,
        "estimated_spend_usd": 0.0,
        "by_market": {},
        "sessions": [],
    }


def _market_bucket(week: dict[str, Any], market: str) -> dict[str, Any]:
    bucket = week["by_market"].get(market)
    if not isinstance(bucket, dict):
        bucket = {
            "signals": 0,
            "all_but_memo": 0,
            "memo_needed": 0,
            "dry_run_requests": 0,
            "requested": 0,
            "skipped_budget": 0,
            "estimated_spend_usd": 0.0,
        }
        week["by_market"][market] = bucket
    return bucket


def _add_counts(summary: dict[str, Any], market: str, session: str, counts: dict[str, int]) -> None:
    day = date.fromisoformat(session)
    weeks = summary.setdefault("weeks", {})
    week = weeks.setdefault(_week_key(day), _empty_week())
    sessions = week.setdefault("sessions", [])
    token = f"{market}|{session}"
    if token in sessions:
        return
    sessions.append(token)
    bucket = _market_bucket(week, market)
    for name in ("signals", "all_but_memo", "memo_needed"):
        week[name] = int(week.get(name) or 0) + int(counts.get(name) or 0)
        bucket[name] = int(bucket.get(name) or 0) + int(counts.get(name) or 0)
    _stamp_rate(week)


def _add_log_action(summary: dict[str, Any], row: dict[str, Any]) -> None:
    day = date.fromisoformat(str(row.get("session")))
    week = summary.setdefault("weeks", {}).setdefault(_week_key(day), _empty_week())
    market = str(row.get("market") or "")
    bucket = _market_bucket(week, market)
    action = str(row.get("action") or "")
    spend = float(row.get("estimated_spend_usd") or 0.0)
    if action == "dry_run":
        week["dry_run_requests"] = int(week.get("dry_run_requests") or 0) + 1
        bucket["dry_run_requests"] = int(bucket.get("dry_run_requests") or 0) + 1
        week["estimated_spend_usd"] = round(float(week.get("estimated_spend_usd") or 0) + spend, 2)
        bucket["estimated_spend_usd"] = round(
            float(bucket.get("estimated_spend_usd") or 0) + spend, 2
        )
    elif action == "requested":
        week["requested"] = int(week.get("requested") or 0) + 1
        bucket["requested"] = int(bucket.get("requested") or 0) + 1
        week["estimated_spend_usd"] = round(float(week.get("estimated_spend_usd") or 0) + spend, 2)
        bucket["estimated_spend_usd"] = round(
            float(bucket.get("estimated_spend_usd") or 0) + spend, 2
        )
    elif action == "skipped" and row.get("skip_reason") == "memo_not_ready_budget":
        week["skipped_budget"] = int(week.get("skipped_budget") or 0) + 1
        bucket["skipped_budget"] = int(bucket.get("skipped_budget") or 0) + 1
    _stamp_rate(week)


def _stamp_rate(week: dict[str, Any]) -> None:
    needed = int(week.get("memo_needed") or 0)
    if needed < WEEKLY_MEMO_ESTIMATE_LOW:
        position = "below"
    elif needed > WEEKLY_MEMO_ESTIMATE_HIGH:
        position = "above"
    else:
        position = "inside"
    distinct_days = sorted({token.split("|", 1)[1] for token in week.get("sessions") or []})
    week["versus_weekly_estimate"] = {
        "low": WEEKLY_MEMO_ESTIMATE_LOW,
        "high": WEEKLY_MEMO_ESTIMATE_HIGH,
        "memo_needed": needed,
        "position": position,
        "week_to_date": len(distinct_days) < 5,
        "session_days": len(distinct_days),
    }


def _headroom_allows(budget: dict[str, Any], *, reserved: float) -> bool:
    if budget.get("constraining"):
        return False
    remaining = float(budget.get("remaining_weekly_ops_usd") or 0.0) - reserved
    return remaining >= (ESTIMATED_MEMO_USD + float(DEFAULT_MIN_HEADROOM_USD))


def _default_budget() -> dict[str, Any]:
    return weekly_ops_budget_status(estimated_memo_usd=ESTIMATED_MEMO_USD)


def _default_record(amount: float) -> None:
    record_estimated_spend(amount, pool=SPEND_POOL_WEEKLY_OPS)


def default_memo_runner(
    *,
    market: str,
    ticker: str,
    screen_row: dict[str, Any],
    repo_root: Path,
    session: str,
) -> dict[str, Any]:
    """One memo via the research runner. The as-of instruction is step 1.3.

    ``run_initial_research_agent`` / ``run_weekly_research_update_agent`` append
    ``point_in_time_memo_discipline`` on every send. This function does not
    build a second prompt. Tests replace it; the default is not used while
    spend is off.
    """
    import os

    from value_investor.library_dedupe import research_home_market
    from value_investor.research.runner import _process_ticker
    from value_investor.research.store import ResearchStore
    from value_investor.summary import CompanyReport

    paths = repo_paths(repo_root)
    if market == FTSE_MARKET:
        output_dir = paths.data
        run_market = None
    else:
        home = research_home_market(paths.library, ticker) or market
        output_dir = paths.library / "markets" / home / "screen"
        run_market = home
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("CURSOR_API_KEY missing")
    report = CompanyReport.from_dict(
        {
            **screen_row,
            "ticker": ticker,
            "signal": screen_row.get("signal") or "buy",
        }
    )
    store = ResearchStore(output_dir)
    doc, action = _process_ticker(
        report=report,
        store=store,
        api_key=api_key,
        model="composer-2.5",
        cwd=str(repo_root),
        force_initial=not store.exists(ticker),
        run_at=datetime.now(UTC),
        market=run_market,
        spend_pool="weekly_ops",
    )
    return {
        "verdict": getattr(doc, "research_verdict", None),
        "finished_at": getattr(doc, "updated_at", None),
        "runner_action": action,
        "session": session,
    }


def _review_is_stale(
    paths: RepoPaths, market: str, ticker: str, session: date
) -> tuple[bool, list[str]]:
    root = research_root_for(paths, market)
    memo_path = root / ticker / "research.json"
    inputs = [str(paths.observe)]
    if memo_path.is_file():
        inputs.append(str(memo_path))
    has_memo, memo_at, _verdict = _memo_as_of(
        ticker, research_root=root, as_of=session_end(session)
    )
    if not has_memo or memo_at is None:
        return True, inputs
    age = _memo_age_days(memo_at, now=session_end(session))
    stale = age is None or age > float(MEMO_MAX_AGE_DAYS)
    return stale, inputs


def _signal_requests(result: MarketSignals) -> list[MemoRequest]:
    requests: list[MemoRequest] = []
    for name in result.names:
        if not name.memo_needed:
            continue
        requests.append(
            MemoRequest(
                market=name.market,
                ticker=name.ticker,
                kind="signal_day",
                session=name.session,
                review_index=None,
                input_paths=list(name.input_paths),
                screen_row=dict(name.screen_row),
            )
        )
    return requests


def _review_requests(
    paths: RepoPaths,
    market: str,
    session: date,
    observe: dict[str, Any] | None,
) -> list[MemoRequest]:
    requests: list[MemoRequest] = []
    for row in review_memo_needs(observe, market=market, session=session):
        stale, inputs = _review_is_stale(paths, market, row["ticker"], session)
        if not stale:
            continue
        requests.append(
            MemoRequest(
                market=market,
                ticker=row["ticker"],
                kind="review_date",
                session=session.isoformat(),
                review_index=int(row["review_index"]),
                input_paths=inputs,
            )
        )
    return requests


def _append_log(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _execute_request(
    request: MemoRequest,
    *,
    spend: bool,
    rows: list[dict[str, Any]],
    repo_root: Path,
    commit: str,
    cache: dict[str, str],
    runner: Any,
    budget_status: Any,
    record_spend: Any,
    reserved: float,
) -> tuple[dict[str, Any] | None, float]:
    key = (request.market, request.ticker, request.kind, request.session)
    if _blocking_row(rows, key, spend=spend):
        return None, reserved
    record: dict[str, Any] = {
        "ticker": request.ticker,
        "market": request.market,
        "kind": request.kind,
        "session": request.session,
        "review_index": request.review_index,
        "action": "dry_run",
        "skip_reason": None,
        "memo_finished_at": None,
        "verdict": None,
        "estimated_spend_usd": ESTIMATED_MEMO_USD,
        "inputs": _inputs(request.input_paths, repo_root=repo_root, cache=cache),
        "data_commit": commit,
    }
    extra_reserved = reserved
    if spend:
        budget = budget_status()
        if not _headroom_allows(budget if isinstance(budget, dict) else {}, reserved=reserved):
            record["action"] = "skipped"
            record["skip_reason"] = "memo_not_ready_budget"
        else:
            try:
                outcome = runner(
                    market=request.market,
                    ticker=request.ticker,
                    screen_row=request.screen_row,
                    repo_root=repo_root,
                    session=request.session,
                )
            except Exception as exc:  # noqa: BLE001 — log and continue; no partial model retry
                record["action"] = "skipped"
                record["skip_reason"] = f"runner_error: {exc}"
            else:
                record["action"] = "requested"
                if isinstance(outcome, dict):
                    record["verdict"] = outcome.get("verdict")
                    record["memo_finished_at"] = outcome.get("finished_at")
                record_spend(ESTIMATED_MEMO_USD)
                extra_reserved += ESTIMATED_MEMO_USD
    return record, extra_reserved


def run_strategy_book_memo_job(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    markets: list[str] | None = None,
    sessions_by_market: dict[str, list[str]] | None = None,
    allow_stale: bool = False,
    replay_limit: int | None = None,
    persist: bool = True,
    runner: Any = None,
    budget_status: Any = None,
    record_spend: Any = None,
) -> dict[str, Any]:
    """Score due closes and append memo-log rows. Does not call a model when spend is off."""
    root = Path(repo_root) if repo_root is not None else Path()
    paths = repo_paths(root)
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    spend = spend_enabled(paths.registration)
    commit = data_commit(root)
    prior = _load_json(paths.summary) or {}
    last_by_market = dict(prior.get("last_run_by_market") or {})
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": moment.isoformat(),
        "spend_enabled": spend,
        "estimated_memo_usd": ESTIMATED_MEMO_USD,
        "weekly_estimate": {
            "low": WEEKLY_MEMO_ESTIMATE_LOW,
            "high": WEEKLY_MEMO_ESTIMATE_HIGH,
        },
        "data_commit": commit,
        "last_run_at": moment.isoformat(),
        "last_run_by_market": last_by_market,
        "weeks": dict(prior.get("weeks") or {}),
        "markets": {},
        "errors": [],
        "logged": [],
        "observe_only": True,
        "influences_live": False,
    }
    chosen = markets if markets is not None else universe_markets(paths.market_status)
    rows = _log_rows(paths.memo_log)
    cache: dict[str, str] = {}
    observe = _load_json(paths.observe) if paths.observe.is_file() else None
    decline = _load_json(paths.decline)
    sector = _load_json(paths.sector)
    call_runner = runner or default_memo_runner
    call_budget = budget_status or _default_budget
    call_record = record_spend or _default_record
    reserved = 0.0
    new_rows: list[dict[str, Any]] = []

    for market in chosen:
        try:
            if sessions_by_market is not None and market in sessions_by_market:
                plan = {
                    "market": market,
                    "latest_bar": None,
                    "sessions": list(sessions_by_market[market]),
                    "suppressed_stale": [],
                    "buy_tier_probe": None,
                }
            else:
                last_raw = (last_by_market.get(market) or {}).get("session")
                last_day = date.fromisoformat(last_raw) if last_raw else None
                plan = plan_sessions(
                    market,
                    paths=paths,
                    now=moment,
                    last_session=last_day,
                    allow_stale=allow_stale,
                    replay_limit=replay_limit,
                )
            market_report: dict[str, Any] = {
                "latest_bar": plan.get("latest_bar"),
                "sessions": [],
                "suppressed_stale": plan.get("suppressed_stale") or [],
                "buy_tier": 0,
                "signals": 0,
                "all_but_memo": 0,
                "memo_needed": 0,
                "dry_run_requests": 0,
                "error": None,
            }
            for session_iso in plan.get("sessions") or []:
                session = date.fromisoformat(session_iso)
                evaluated = evaluate_market(
                    market,
                    session,
                    paths=paths,
                    decline_payload=decline,
                    sector_payload=sector,
                    load_stores=False,
                )
                counts = {
                    "signals": evaluated.signals,
                    "all_but_memo": evaluated.all_but_memo,
                    "memo_needed": evaluated.memo_needed,
                }
                _add_counts(summary, market, session_iso, counts)
                market_report["buy_tier"] += evaluated.buy_tier
                market_report["signals"] += evaluated.signals
                market_report["all_but_memo"] += evaluated.all_but_memo
                market_report["memo_needed"] += evaluated.memo_needed
                market_report["sessions"].append(
                    {
                        "session": session_iso,
                        "buy_tier": evaluated.buy_tier,
                        "signals": evaluated.signals,
                        "all_but_memo": evaluated.all_but_memo,
                        "memo_needed": evaluated.memo_needed,
                        "screen_run_at": evaluated.screen_run_at,
                        "error": evaluated.error,
                    }
                )
                requests = _signal_requests(evaluated)
                requests.extend(_review_requests(paths, market, session, observe))
                for request in requests:
                    logged, reserved = _execute_request(
                        request,
                        spend=spend,
                        rows=rows,
                        repo_root=root,
                        commit=commit,
                        cache=cache,
                        runner=call_runner,
                        budget_status=call_budget,
                        record_spend=call_record,
                        reserved=reserved,
                    )
                    if logged is None:
                        continue
                    rows.append(logged)
                    new_rows.append(logged)
                    _add_log_action(summary, logged)
                    if logged["action"] == "dry_run":
                        market_report["dry_run_requests"] += 1
            # Advance only through a close that was scored. A stale chart
            # stays unscored, so a measurement replay can still read it.
            scored = list(plan.get("sessions") or [])
            last_by_market[market] = {
                "session": scored[-1] if scored else None,
                "run_at": moment.isoformat(),
                "latest_bar": plan.get("latest_bar"),
                "stale": bool(plan.get("suppressed_stale")),
            }
            summary["markets"][market] = market_report
        except (OSError, ValueError, TypeError) as exc:
            summary["errors"].append(f"{market}: {exc}")
            summary["markets"][market] = {"error": str(exc)}

    summary["last_run_by_market"] = last_by_market
    summary["logged"] = [
        {
            "ticker": row["ticker"],
            "market": row["market"],
            "kind": row["kind"],
            "session": row["session"],
            "action": row["action"],
            "skip_reason": row.get("skip_reason"),
        }
        for row in new_rows
    ]
    summary["new_log_rows"] = len(new_rows)
    if persist:
        if new_rows:
            for row in new_rows:
                _append_log(paths.memo_log, row)
        stored = dict(summary)
        stored.pop("logged", None)
        write_json(paths.summary, stored, compact=False)
    summary["memo_log"] = str(paths.memo_log)
    summary["summary_path"] = str(paths.summary)
    return summary


def memo_routine_falling_behind(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Warn when budget skips exceed a fifth of the week's otherwise-eligible signals.

    Inert while spend is off. Dry runs are not ``memo_not_ready``, so the
    share is not computed and this returns None.
    """
    if not summary.get("spend_enabled"):
        return None
    weeks = summary.get("weeks") if isinstance(summary.get("weeks"), dict) else {}
    if not weeks:
        return None
    week_key = sorted(weeks)[-1]
    week = weeks.get(week_key) if isinstance(weeks.get(week_key), dict) else {}
    eligible = int(week.get("all_but_memo") or 0)
    skipped = int(week.get("skipped_budget") or 0)
    if eligible <= 0 or skipped <= eligible * MEMO_NOT_READY_MAX_SHARE:
        return None
    return {
        "severity": "warn",
        "category": "research",
        "title": TITLE_BEHIND,
        "summary": (
            f"{week_key}: memo_not_ready_budget {skipped} of {eligible} "
            f"otherwise-eligible signals (more than one fifth). "
            "No rememo or ingest from this finding."
        ),
        "auto_fixable": False,
    }


def _not_run_on_weekday(summary: dict[str, Any], now: datetime) -> bool:
    moment = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    if moment.weekday() >= 5:
        return False
    raw = summary.get("last_run_at")
    if not raw:
        return True
    try:
        ran = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if ran.tzinfo is None:
        ran = ran.replace(tzinfo=UTC)
    return ran.astimezone(UTC).date() < moment.astimezone(UTC).date()


def _preview_tickers(summary: dict[str, Any], limit: int = 5) -> list[str]:
    names = []
    for row in summary.get("logged") or []:
        if row.get("action") in {"dry_run", "requested", "skipped"}:
            names.append(f"{row.get('market')}:{row.get('ticker')}")
        if len(names) >= limit:
            break
    return names


def findings_from_memo_job(
    summary: dict[str, Any], *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Stable observe findings. Never auto-fixable. No rememo or ingest."""
    moment = now or datetime.now(UTC)
    markets = summary.get("markets") if isinstance(summary.get("markets"), dict) else {}
    bits: list[str] = []
    signals = all_but = needed = dry = 0
    for market, row in markets.items():
        if not isinstance(row, dict):
            continue
        signals += int(row.get("signals") or 0)
        all_but += int(row.get("all_but_memo") or 0)
        needed += int(row.get("memo_needed") or 0)
        dry += int(row.get("dry_run_requests") or 0)
        latest = row.get("latest_bar")
        stale = row.get("suppressed_stale") or []
        if stale:
            bits.append(f"{market} chart stale latest {latest}")
        elif row.get("sessions"):
            bits.append(
                f"{market} signals {row.get('signals')} "
                f"all_but_memo {row.get('all_but_memo')} "
                f"memo_needed {row.get('memo_needed')}"
            )
    preview = _preview_tickers(summary)
    preview_text = ", ".join(preview) if preview else "none"
    spend = "on" if summary.get("spend_enabled") else "off"
    refreshed = {
        "severity": "info",
        "category": "research",
        "title": TITLE_REFRESHED,
        "summary": (
            f"Spend {spend}. Signals {signals}, all-but-memo {all_but}, "
            f"memo needed {needed}, dry-run requests {dry}. "
            f"First tickers: {preview_text}. "
            + ("; ".join(bits[:8]) if bits else "No due session.")
            + " Observe-only; no rememo or ingest from this finding."
        ),
        "auto_fixable": False,
    }
    findings = [refreshed]
    errors = summary.get("errors") or []
    if errors:
        findings.append(
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_FAILED,
                "summary": "; ".join(str(item) for item in errors[:8]),
                "auto_fixable": False,
            }
        )
    if _not_run_on_weekday(summary, moment):
        findings.append(
            {
                "severity": "warn",
                "category": "research",
                "title": TITLE_NOT_RUN,
                "summary": "The signal-day memo job has no run dated today (UTC) on this weekday.",
                "auto_fixable": False,
            }
        )
    behind = memo_routine_falling_behind(summary)
    if behind is not None:
        findings.append(behind)
    return findings


__all__ = [
    "ESTIMATED_MEMO_USD",
    "MEMO_NOT_READY_MAX_SHARE",
    "TITLE_BEHIND",
    "TITLE_FAILED",
    "TITLE_NOT_RUN",
    "TITLE_REFRESHED",
    "WEEKLY_MEMO_ESTIMATE_HIGH",
    "WEEKLY_MEMO_ESTIMATE_LOW",
    "default_memo_runner",
    "findings_from_memo_job",
    "memo_routine_falling_behind",
    "plan_sessions",
    "run_strategy_book_memo_job",
    "spend_enabled",
]
