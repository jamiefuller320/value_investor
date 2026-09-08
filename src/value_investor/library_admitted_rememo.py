"""Weekday rememo for admitted / epoch-0 markets (equal treatment, not Sunday spray).

Same body-lag rule and daily cap as FTSE weekday rememo. Does **not** flip
``research_all_graduated`` or rememo the 21-market graduated set.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    SPEND_POOL_WEEKLY_OPS,
    estimate_agent_spend_usd,
    load_policy,
    record_estimated_spend,
    weekly_ops_budget_status,
)
from value_investor.library_equal_support import admitted_buy_tier_rememo_targets
from value_investor.library_maintenance import _company_report_from_snapshot
from value_investor.library_screen import screen_dir_for
from value_investor.market_shard_admission import admitted_learning_markets_for_policy
from value_investor.research.market_store import (
    library_ticker_dir,
    resolve_library_rememo_target,
)
from value_investor.research.runner import _process_ticker
from value_investor.research.source_quality import score_research_sources
from value_investor.research.store import ResearchStore
from value_investor.research.weekday_rememo import (
    DEFAULT_CATCHUP_REMEMO_CAP,
    DEFAULT_MEMO_USD,
    DEFAULT_MIN_HEADROOM_USD,
    DEFAULT_WEEKDAY_REMEMO_CAP,
    weekly_rememo_maintenance_capacity,
)
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_SUMMARY_PATH = DEFAULT_LIBRARY_ROOT / "admitted_rememo_summary.json"
DEFAULT_BACKLOG_PATH = DEFAULT_LIBRARY_ROOT / "admitted_rememo_backlog.json"
WEEKDAYS = frozenset({0, 1, 2, 3, 4})  # Mon–Fri


def _utc_now() -> datetime:
    return datetime.now(UTC)


def already_ran_today(
    summary_path: Path = DEFAULT_SUMMARY_PATH, *, now: datetime | None = None
) -> bool:
    """True when a non-dry admitted rememo pass already ran this UTC day."""
    if not summary_path.exists():
        return False
    payload = read_json(summary_path)
    if not isinstance(payload, dict) or payload.get("dry_run"):
        return False
    raw = str(payload.get("run_at") or "")[:10]
    stamp = (now or _utc_now()).date().isoformat()
    if not raw or raw != stamp:
        return False
    if payload.get("skipped_reason") == "weekend":
        return False
    return True


def is_weekday(now: datetime | None = None) -> bool:
    return (now or _utc_now()).weekday() in WEEKDAYS


def list_admitted_rememo_backlog(
    library_root: Path,
    policy: dict[str, Any],
    *,
    markets: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Per-market body-lag rememo map (ticker → reason)."""
    wanted = list(markets or admitted_learning_markets_for_policy(policy))
    out: dict[str, dict[str, str]] = {}
    for mid in wanted:
        out[mid] = admitted_buy_tier_rememo_targets(library_root, policy, market_id=mid)
    return out


def _affordable_now(
    *,
    memo_usd: float = DEFAULT_MEMO_USD,
    min_headroom_usd: float = DEFAULT_MIN_HEADROOM_USD,
    budget: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    status = budget or weekly_ops_budget_status(estimated_memo_usd=memo_usd)
    remaining = float(status.get("remaining_weekly_ops_usd") or 0.0)
    affordable = 0
    if memo_usd > 0 and remaining > float(min_headroom_usd):
        affordable = max(
            0,
            int(math.floor((remaining - float(min_headroom_usd)) / float(memo_usd))),
        )
    return affordable, status


def assess_market_rememo(
    eligible: dict[str, str],
    *,
    per_day_cap: int = DEFAULT_WEEKDAY_REMEMO_CAP,
    affordable: int = 0,
) -> dict[str, Any]:
    """FTSE-equivalent capacity action for one admitted market."""
    count = len(eligible)
    capacity = weekly_rememo_maintenance_capacity(per_day_cap=per_day_cap)
    over = count > capacity
    if count == 0:
        action = "none"
    elif over and affordable > 0:
        action = "catch_up"
    elif over:
        action = "escalate"
    else:
        action = "maintain"
    recommended = 0
    if action == "catch_up":
        recommended = max(
            int(per_day_cap),
            min(
                count,
                affordable,
                max(int(per_day_cap) * 2, DEFAULT_CATCHUP_REMEMO_CAP),
            ),
        )
    cap = recommended if action == "catch_up" and recommended > 0 else int(per_day_cap)
    tickers = sorted(eligible)
    return {
        "eligible_count": count,
        "weekly_maintenance_capacity": capacity,
        "over_weekly_capacity": over,
        "action": action,
        "recommended_catchup_batch": recommended,
        "effective_cap": cap if count else 0,
        "selected": tickers[: max(0, cap if count else 0)],
        "reasons": {ticker: eligible[ticker] for ticker in tickers},
    }


def assess_admitted_rememo_backlog(
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy: dict[str, Any] | None = None,
    *,
    markets: list[str] | None = None,
    per_day_cap: int = DEFAULT_WEEKDAY_REMEMO_CAP,
    memo_usd: float = DEFAULT_MEMO_USD,
    min_headroom_usd: float = DEFAULT_MIN_HEADROOM_USD,
) -> dict[str, Any]:
    """Compare each admitted market's rememo backlog to in-week capacity."""
    policy = policy or load_policy()
    backlog = list_admitted_rememo_backlog(library_root, policy, markets=markets)
    affordable, budget = _affordable_now(memo_usd=memo_usd, min_headroom_usd=min_headroom_usd)
    remaining_affordable = affordable
    markets_out: dict[str, Any] = {}
    selected_total = 0
    for mid, eligible in backlog.items():
        row = assess_market_rememo(
            eligible,
            per_day_cap=per_day_cap,
            affordable=remaining_affordable,
        )
        take = min(len(row["selected"]), remaining_affordable)
        if take < len(row["selected"]):
            row["selected"] = row["selected"][:take]
            row["effective_cap"] = take
            if take == 0 and row["action"] == "catch_up":
                row["action"] = "escalate"
        remaining_affordable = max(0, remaining_affordable - take)
        selected_total += take
        markets_out[mid] = row
    return {
        "assessed_at": _utc_now().isoformat(),
        "admitted": list(backlog),
        "eligible_total": sum(len(v) for v in backlog.values()),
        "selected_total": selected_total,
        "per_day_cap": int(per_day_cap),
        "affordable_now": affordable,
        "markets": markets_out,
        "budget": budget,
        "note": (
            "Same 3/day weekday cap (catch-up 5 when a market exceeds 15) as FTSE. "
            "Not research_all_graduated / 21-market spray."
        ),
    }


def write_admitted_rememo_backlog(
    assessment: dict[str, Any],
    *,
    path: Path = DEFAULT_BACKLOG_PATH,
) -> dict[str, Any]:
    write_json(path, assessment)
    return assessment


def _report_for_ticker(
    library_root: Path,
    market_id: str,
    ticker: str,
    home_dir: Path | None,
) -> CompanyReport | None:
    if home_dir is not None:
        snap_path = home_dir / "sources" / "screening_snapshot.json"
        if snap_path.exists():
            try:
                snap = read_json(snap_path)
            except (OSError, ValueError, TypeError):
                snap = {}
            if isinstance(snap, dict) and snap.get("ticker"):
                return _company_report_from_snapshot(snap)
        meta_path = home_dir / "research.json"
        if meta_path.exists():
            try:
                meta = read_json(meta_path)
            except (OSError, ValueError, TypeError):
                meta = {}
            if isinstance(meta, dict) and (meta.get("ticker") or ticker):
                return _company_report_from_snapshot(
                    {
                        "ticker": ticker,
                        "name": meta.get("name") or ticker,
                        "signal": meta.get("signal") or "buy",
                        "data_quality_score": 1.0,
                        "models_passed": 0,
                        "model_count": 0,
                    }
                )
    screen = screen_dir_for(library_root, market_id)
    latest = screen / "latest_signals.csv"
    if latest.exists():
        import csv

        with latest.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("ticker") or "").strip().upper() == ticker.upper():
                    return _company_report_from_snapshot(
                        {
                            "ticker": ticker,
                            "name": row.get("name") or ticker,
                            "signal": row.get("signal") or "buy",
                            "conviction_score": row.get("conviction_score") or 0,
                            "data_quality_score": row.get("data_quality_score") or 1.0,
                            "models_passed": row.get("models_passed") or 0,
                            "model_count": row.get("model_count") or 0,
                        }
                    )
    return None


def run_admitted_rememo_pass(
    *,
    api_key: str | None,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy: dict[str, Any] | None = None,
    markets: list[str] | None = None,
    per_day_cap: int = DEFAULT_WEEKDAY_REMEMO_CAP,
    memo_usd: float = DEFAULT_MEMO_USD,
    min_headroom_usd: float = DEFAULT_MIN_HEADROOM_USD,
    model: str = "composer-2.5",
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    backlog_path: Path = DEFAULT_BACKLOG_PATH,
    dry_run: bool = False,
    force: bool = False,
    record_spend: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bounded weekday rememo for admitted epoch-0 markets."""
    now = now or _utc_now()
    policy = policy or load_policy()
    summary: dict[str, Any] = {
        "run_at": now.isoformat(),
        "dry_run": bool(dry_run),
        "markets": {},
        "selected": [],
        "rememoed": [],
        "skipped": [],
        "errors": [],
    }

    if not force and not is_weekday(now):
        summary["skipped"].append("weekend")
        summary["skipped_reason"] = "weekend"
        write_json(summary_path, summary)
        return summary
    if not force and already_ran_today(summary_path, now=now):
        summary["skipped"].append("already_ran_today")
        summary["skipped_reason"] = "already_ran_today"
        write_json(summary_path, summary)
        return summary

    assessment = assess_admitted_rememo_backlog(
        library_root,
        policy,
        markets=markets,
        per_day_cap=per_day_cap,
        memo_usd=memo_usd,
        min_headroom_usd=min_headroom_usd,
    )
    write_admitted_rememo_backlog(assessment, path=backlog_path)
    summary["backlog"] = {
        "eligible_total": assessment["eligible_total"],
        "selected_total": assessment["selected_total"],
        "affordable_now": assessment["affordable_now"],
    }
    summary["budget"] = assessment.get("budget") or {}

    planned: list[tuple[str, str, str]] = []
    for mid, row in (assessment.get("markets") or {}).items():
        reasons = row.get("reasons") or {}
        picked = list(row.get("selected") or [])
        summary["markets"][mid] = {
            "eligible_count": row.get("eligible_count"),
            "action": row.get("action"),
            "effective_cap": row.get("effective_cap"),
            "selected": picked,
        }
        for ticker in picked:
            planned.append((mid, ticker, str(reasons.get(ticker) or "body_lag")))
    summary["selected"] = [f"{mid}:{ticker}" for mid, ticker, _ in planned]

    if not planned:
        summary["skipped"].append("no_targets")
        write_json(summary_path, summary)
        return summary

    if dry_run:
        write_json(summary_path, summary)
        return summary

    if not api_key:
        summary["errors"].append("CURSOR_API_KEY required for admitted rememo")
        write_json(summary_path, summary)
        return summary

    model = (model or "composer-2.5").strip() or "composer-2.5"
    rememoed: list[str] = []

    for mid, ticker, reason in planned:
        dest = resolve_library_rememo_target(
            library_root,
            ticker,
            selected_market=mid,
            focus_market=mid,
            rememo_reasons={ticker: reason},
        )
        dest_market = str(dest.get("market") or mid)
        screen_dir = screen_dir_for(library_root, dest_market)
        research_root = screen_dir / "research"
        home_dir = library_ticker_dir(research_root, ticker)
        report = _report_for_ticker(library_root, dest_market, ticker, home_dir)
        if report is None:
            summary["errors"].append(f"{mid}/{ticker}: missing CompanyReport")
            continue
        try:
            if home_dir is not None:
                for name in ("research.json", "research.md", "agent_id.txt"):
                    path = home_dir / name
                    if path.exists():
                        path.unlink()
            store = ResearchStore(screen_dir)
            doc, action = _process_ticker(
                report=report,
                store=store,
                api_key=api_key,
                model=model,
                cwd=None,
                force_initial=True,
                run_at=now,
                market=dest_market,
            )
            mq = doc.memo_quality or score_research_sources(source_counts=doc.source_counts)
            key = f"{dest_market}:{ticker}"
            rememoed.append(key)
            summary["rememoed"] = rememoed
            market_row = summary["markets"].setdefault(mid, {})
            after = dict(market_row.get("grades_after") or {})
            after[ticker] = {
                "grade": mq.get("grade"),
                "bodies": f"{mq.get('filings_with_body')}/{mq.get('filings_total')}",
                "action": action,
                "reason": reason,
                "home_market": dest_market,
                "seed": dest.get("seed"),
            }
            market_row["grades_after"] = after
            logger.info("Admitted rememo %s/%s → %s", dest_market, ticker, mq.get("grade"))
            write_json(summary_path, summary)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Admitted rememo failed for %s/%s", mid, ticker)
            summary["errors"].append(f"{mid}/{ticker}: {exc}")
            write_json(summary_path, summary)

    if record_spend and rememoed:
        record_estimated_spend(
            estimate_agent_spend_usd(len(rememoed), memo_usd=memo_usd),
            pool=SPEND_POOL_WEEKLY_OPS,
        )
        summary["budget"] = {
            **(summary.get("budget") or {}),
            **weekly_ops_budget_status(estimated_memo_usd=memo_usd),
            "recorded_usd": estimate_agent_spend_usd(len(rememoed), memo_usd=memo_usd),
        }

    follow = assess_admitted_rememo_backlog(
        library_root,
        policy,
        markets=markets,
        per_day_cap=per_day_cap,
        memo_usd=memo_usd,
        min_headroom_usd=min_headroom_usd,
    )
    write_admitted_rememo_backlog(follow, path=backlog_path)
    summary["backlog_after"] = follow.get("eligible_total")
    write_json(summary_path, summary)
    return summary


__all__ = [
    "already_ran_today",
    "assess_admitted_rememo_backlog",
    "assess_market_rememo",
    "is_weekday",
    "list_admitted_rememo_backlog",
    "run_admitted_rememo_pass",
    "write_admitted_rememo_backlog",
]
