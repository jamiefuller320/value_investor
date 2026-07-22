"""Assemble dashboard automation settings + dated achievement timeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.storage import read_json, write_json

DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
DEFAULT_AUTOMATION_PATH = Path("docs/data/automation.json")

WORKFLOW_SCHEDULES = {
    "orchestrator": {
        "name": "Automation Orchestrator",
        "cron_sunday": "17 6 * * 0",
        "cron_sunday_catchup": "17 9,12 * * 0",
        "cron_surplus": "30 5 * * *",
        "cron_paper": "17 8 * * 1-5",
        "cron_paper_catchup": "17 11 * * 1-5",
        "cadence": (
            "Dispatches child workflows via workflow_dispatch. "
            "Sunday 06:17 UTC quiet bundle (+ 09:17/12:17 catch-up); "
            "daily 05:30 UTC surplus-day ladder gate; "
            "weekdays 08:17 UTC paper automation (+ 11:17 catch-up). "
            "Skips children that already succeeded today. "
            "External cron setup: docs/ops/orchestrator-cron.md."
        ),
        "workflow": "automation-orchestrator.yml",
    },
    "paper_auto": {
        "name": "FTSE Paper Automation",
        "cron": "17 8 * * 1-5",
        "cadence": "Dispatched by orchestrator on weekdays 08:17 UTC (≈09:17 Europe/London in BST); 11:17 catch-up",
        "workflow": "paper-auto.yml",
    },
    "library_ladder": {
        "name": "FTSE Library Ladder",
        "cron_weekly": "17 6 * * 0",
        "cron_daily_surplus": "30 5 * * *",
        "cadence": "Dispatched by orchestrator — Sunday quiet bundle + catch-up + surplus-day gate",
        "workflow": "library-grow.yml",
    },
    "model_review": {
        "name": "Library model review",
        "cron": "17 6 * * 0",
        "cadence": "Sunday quiet bundle via orchestrator (skips if within review_interval_days)",
        "workflow": "library-model-review.yml",
    },
    "email_report": {
        "name": "Email report",
        "cron": "17 6 * * 0",
        "cadence": "Sunday quiet bundle via orchestrator (markets closed)",
        "workflow": "email-report.yml",
    },
    "pages": {
        "name": "Deploy GitHub Pages",
        "cadence": "On push to main when docs/** change",
        "workflow": "pages.yml",
    },
}


def _safe_read(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:  # noqa: BLE001
        return None


def _slim_ladder(last_ladder: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(last_ladder, dict):
        return None
    layers = last_ladder.get("layers") or {}
    research = layers.get("selective_research") or {}
    screen = layers.get("screen_lite") or {}
    maintenance = layers.get("maintenance") or {}
    fundamentals = layers.get("fundamentals") or {}
    graduation = layers.get("graduation") or {}
    return {
        "run_at": last_ladder.get("run_at"),
        "focus_market": last_ladder.get("focus_market"),
        "graduated_markets": last_ladder.get("graduated_markets") or [],
        "plan": {
            "max_tickers": (last_ladder.get("plan") or {}).get("max_tickers"),
            "surplus_day": (last_ladder.get("plan") or {}).get("surplus_day"),
            "research_model": (last_ladder.get("plan") or {}).get("research_model"),
            "allow_research": (last_ladder.get("plan") or {}).get("allow_research"),
        },
        "layers": {
            "fundamentals_skipped": bool(fundamentals.get("skipped")),
            "maintenance_skipped": bool(maintenance.get("skipped")),
            "maintenance_markets": maintenance.get("markets") or [],
            "screen_shortlist": screen.get("shortlist_count"),
            "screen_strong_buy": screen.get("strong_buy"),
            "screen_buy": screen.get("buy"),
            "research_executed": research.get("executed"),
            "research_created": research.get("created"),
            "research_updated": research.get("updated"),
            "research_estimated_spend_usd": research.get("estimated_spend_usd"),
            "graduation_skipped": bool(graduation.get("skipped")),
            "graduated_to": (graduation.get("to_market") if isinstance(graduation, dict) else None),
        },
    }


def _slim_paper_last_run(last_run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(last_run, dict):
        return None
    trades = last_run.get("trades") or []
    fund = last_run.get("fund") or last_run.get("fund_snapshot") or {}
    return {
        "generated_at": last_run.get("generated_at") or last_run.get("run_at"),
        "acted": last_run.get("acted"),
        "note": last_run.get("note"),
        "gate": last_run.get("gate"),
        "trade_count": len(trades),
        "trades_sample": [
            {
                "acted_at": t.get("acted_at"),
                "ticker": t.get("ticker"),
                "side": t.get("side"),
                "name": t.get("name"),
                "net_cash": t.get("net_cash"),
            }
            for t in trades[:12]
            if isinstance(t, dict)
        ],
        "fund": {
            "cash": fund.get("cash"),
            "nav": fund.get("nav") or fund.get("last_nav"),
            "holdings_count": len(fund.get("holdings") or {}),
        },
    }


def _timeline_events(
    *,
    policy: dict[str, Any],
    last_ladder: dict[str, Any] | None,
    milestones: dict[str, Any],
    paper_last: dict[str, Any] | None,
    advance_log: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for row in (policy.get("focus_graduation") or {}).get("history") or []:
        if not isinstance(row, dict) or not row.get("at"):
            continue
        frm = row.get("from_market") or "—"
        to = row.get("to_market")
        reason = row.get("reason") or "advanced"
        if to:
            title = f"Focus advanced: {frm} → {to}"
        else:
            title = f"Queue milestone: {frm} ({reason})"
        events.append(
            {
                "at": row["at"],
                "kind": "graduation",
                "title": title,
                "detail": row.get("note")
                or (
                    f"coverage={row.get('coverage_pct')} stale={row.get('stale_pct')} "
                    f"reason={reason}"
                ),
            }
        )

    for row in (policy.get("model_review") or {}).get("history") or []:
        if not isinstance(row, dict) or not row.get("reviewed_at"):
            continue
        events.append(
            {
                "at": row["reviewed_at"],
                "kind": "model_review",
                "title": f"Research model: {row.get('previous_model_id') or '—'} → {row.get('model_id')}",
                "detail": f"pool={row.get('pool') or '—'}",
            }
        )

    for market in policy.get("graduated_markets") or []:
        if not isinstance(market, dict) or not market.get("graduated_at"):
            continue
        events.append(
            {
                "at": market["graduated_at"],
                "kind": "graduated_market",
                "title": f"Graduated market: {market.get('market')}",
                "detail": (
                    f"coverage={market.get('coverage_pct')} "
                    f"stale={market.get('stale_pct')}"
                ),
            }
        )

    slim = _slim_ladder(last_ladder)
    if slim and slim.get("run_at"):
        layers = slim.get("layers") or {}
        events.append(
            {
                "at": slim["run_at"],
                "kind": "ladder_run",
                "title": f"Library ladder run (focus {slim.get('focus_market')})",
                "detail": (
                    f"shortlist={layers.get('screen_shortlist')} "
                    f"research created={layers.get('research_created')} "
                    f"updated={layers.get('research_updated')} "
                    f"spend≈{layers.get('research_estimated_spend_usd')}"
                ),
            }
        )

    ladder_complete = milestones.get("ladder_complete")
    if isinstance(ladder_complete, dict) and ladder_complete.get("completed_at"):
        events.append(
            {
                "at": ladder_complete["completed_at"],
                "kind": "milestone",
                "title": "Initial offline queue complete",
                "detail": (
                    f"focus={ladder_complete.get('focus_market')} "
                    f"graduated={len(ladder_complete.get('graduated_markets') or [])}"
                ),
            }
        )

    l34 = milestones.get("l34_slices")
    if isinstance(l34, dict) and l34.get("completed_at"):
        events.append(
            {
                "at": l34["completed_at"],
                "kind": "milestone",
                "title": "L34 next-slice markets complete",
                "detail": (
                    f"markets={', '.join(l34.get('new_markets') or [])}; "
                    f"memos={l34.get('research_memos_created')}; "
                    f"{l34.get('note') or ''}"
                ).strip(),
            }
        )

    if paper_last and (paper_last.get("generated_at") or paper_last.get("acted") is not None):
        at = paper_last.get("generated_at") or (
            (paper_last.get("gate") or {}).get("local_time")
        )
        if at:
            events.append(
                {
                    "at": at,
                    "kind": "paper_run",
                    "title": (
                        "Paper automation acted"
                        if paper_last.get("acted")
                        else "Paper automation checked (no action)"
                    ),
                    "detail": (
                        paper_last.get("note")
                        or f"trades={paper_last.get('trade_count', 0)}"
                    ),
                }
            )

    for row in advance_log:
        if not isinstance(row, dict) or not row.get("at"):
            continue
        events.append(
            {
                "at": row["at"],
                "kind": "advance_log",
                "title": f"Offline advance: {row.get('stage') or 'stage'}",
                "detail": (
                    f"market={row.get('market') or row.get('focus_market') or '—'} "
                    f"{row.get('note') or ''}"
                ).strip(),
            }
        )

    # Newest first; stable secondary key
    events.sort(key=lambda e: (str(e.get("at") or ""), str(e.get("kind") or "")), reverse=True)
    # Dedupe near-identical graduation + graduated_market pairs by title+at
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for event in events:
        key = (str(event.get("at")), str(event.get("title")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def build_automation_status(
    *,
    library_root: Path | None = None,
    paper_root: Path | None = None,
) -> dict[str, Any]:
    library_root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    paper_root = Path(paper_root or DEFAULT_PAPER_ROOT)

    policy_raw = _safe_read(library_root / "policy.json")
    policy = policy_raw if isinstance(policy_raw, dict) else {}
    last_ladder_raw = _safe_read(library_root / "last_ladder.json")
    last_ladder = last_ladder_raw if isinstance(last_ladder_raw, dict) else None
    ladder_complete = _safe_read(library_root / "ladder_complete_summary.json")
    l34 = _safe_read(library_root / "l34_slices_complete_summary.json")
    advance_raw = _safe_read(library_root / "ladder_advance_log.json")
    if isinstance(advance_raw, dict):
        advance_log = list(advance_raw.get("events") or advance_raw.get("entries") or [])
    elif isinstance(advance_raw, list):
        advance_log = advance_raw
    else:
        advance_log = []

    paper_config_raw = _safe_read(paper_root / "config.json")
    paper_config = paper_config_raw if isinstance(paper_config_raw, dict) else {}
    paper_last_raw = _safe_read(paper_root / "last_run.json")
    paper_last = _slim_paper_last_run(
        paper_last_raw if isinstance(paper_last_raw, dict) else None
    )

    from value_investor.agent_model_policy import weekly_budget_status

    focus_grad = policy.get("focus_graduation") or {}
    budget = policy.get("budget") or {}
    ladder = policy.get("ladder") or {}
    research_model = policy.get("research_model") or {}
    model_review = policy.get("model_review") or {}
    macro = policy.get("macro_context") or {}
    budget_status = weekly_budget_status(policy)

    graduated = [
        {
            "market": g.get("market"),
            "graduated_at": g.get("graduated_at"),
            "coverage_pct": g.get("coverage_pct"),
            "stale_pct": g.get("stale_pct"),
        }
        for g in (policy.get("graduated_markets") or [])
        if isinstance(g, dict)
    ]

    milestones = {
        "ladder_complete": ladder_complete if isinstance(ladder_complete, dict) else None,
        "l34_slices": l34 if isinstance(l34, dict) else None,
    }

    settings = {
        "paper": paper_config,
        "library": {
            "focus_market": policy.get("focus_market"),
            "market_queue": policy.get("market_queue") or [],
            "graduated_markets": graduated,
            "graduated_count": len(graduated),
            "queue_complete": all(
                any(g.get("market") == mid for g in graduated)
                for mid in (policy.get("market_queue") or [])
            )
            if policy.get("market_queue")
            else False,
            "focus_graduation": {
                "auto_advance": focus_grad.get("auto_advance"),
                "min_coverage_pct": focus_grad.get("min_coverage_pct"),
                "max_stale_pct": focus_grad.get("max_stale_pct"),
                "maintenance_enabled": focus_grad.get("maintenance_enabled"),
                "maintenance_max_tickers": focus_grad.get("maintenance_max_tickers"),
                "maintenance_include_focus_when_queue_complete": focus_grad.get(
                    "maintenance_include_focus_when_queue_complete"
                ),
                "note": focus_grad.get("note"),
            },
            "budget": {
                "plan_name": budget.get("plan_name"),
                "plan_monthly_usd": budget.get("plan_monthly_usd"),
                "allocation_basis": budget_status.get("allocation_basis"),
                "weekly_usage_gbp": budget_status.get("weekly_usage_gbp"),
                "gbp_usd_rate": budget_status.get("gbp_usd_rate"),
                "weekly_library_usd": budget_status.get("weekly_library_usd"),
                "weekly_library_fraction": budget.get("weekly_library_fraction"),
                "enforce_weekly_research_cap": budget_status.get(
                    "enforce_weekly_research_cap"
                ),
                "constraining": budget_status.get("constraining"),
                "near_limit": budget_status.get("near_limit"),
                "budget_flag": budget_status.get("flag"),
                "remaining_weekly_usd": budget_status.get("remaining_weekly_usd"),
                "budget_note": budget_status.get("note"),
                "plan_refresh_day_of_month": budget.get("plan_refresh_day_of_month"),
                "surplus_day_before_refresh": budget.get("surplus_day_before_refresh"),
                "estimated_spend_usd_this_week": budget_status.get(
                    "estimated_spend_usd_this_week"
                ),
                "estimated_spend_usd_this_cycle": budget.get(
                    "estimated_spend_usd_this_cycle"
                ),
                "week_id": budget.get("week_id"),
                "cycle_id": budget.get("cycle_id"),
            },
            "ladder": {
                "enabled": ladder.get("enabled"),
                "layers": ladder.get("layers"),
                "min_metrics_for_screen": ladder.get("min_metrics_for_screen"),
                "estimated_memo_usd": ladder.get("estimated_memo_usd"),
                "research_hard_cap": ladder.get("research_hard_cap"),
                "research_all_graduated": ladder.get("research_all_graduated"),
            },
            "research_model": {
                "model_id": research_model.get("model_id"),
                "pool": research_model.get("pool"),
            },
            "model_review": {
                "last_reviewed_at": model_review.get("last_reviewed_at"),
                "review_interval_days": model_review.get("review_interval_days"),
            },
            "macro_context": {
                "enabled": macro.get("enabled"),
                "refresh_on_ladder": macro.get("refresh_on_ladder"),
            },
            "updated_at": policy.get("updated_at"),
        },
        "workflows": WORKFLOW_SCHEDULES,
    }

    achievements = {
        "timeline": _timeline_events(
            policy=policy,
            last_ladder=last_ladder,
            milestones=milestones,
            paper_last=paper_last,
            advance_log=[r for r in advance_log if isinstance(r, dict)],
        ),
        "last_ladder": _slim_ladder(last_ladder),
        "milestones": milestones,
        "paper_last_run": paper_last,
        "graduation_history": list((focus_grad.get("history") or [])),
        "model_review_history": list((model_review.get("history") or [])),
    }

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "note": (
            "Current automation settings and a dated achievement log assembled from "
            "library policy, ladder artifacts, and paper automation files. "
            "Paper/ladder runs currently keep only the latest snapshot plus cumulative fund trades."
        ),
        "settings": settings,
        "achievements": achievements,
    }


def write_automation_status(
    *,
    library_root: Path | None = None,
    paper_root: Path | None = None,
    path: Path | None = None,
) -> Path:
    target = Path(path or DEFAULT_AUTOMATION_PATH)
    payload = build_automation_status(library_root=library_root, paper_root=paper_root)
    write_json(target, payload, compact=False)
    return target
