#!/usr/bin/env python3
"""Advance the offline library ladder one market at a time.

Steps for the current focus market when already grown:
  graduate (if floors met) → grow next focus → screen → research buy-tier
  (strong buys first up to hard cap) → optionally graduate again.

Use --stage to run a single step.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from value_investor.agent_model_policy import (
    load_policy,
    record_estimated_spend,
    research_model_id,
    save_policy,
)
from value_investor.data_library import grow_library, library_status, refresh_constituents
from value_investor.library_graduation import maybe_graduate_focus
from value_investor.library_screen import library_research_reports, run_library_screen
from value_investor.research.runner import eligible_research_targets, run_research_for_strong_buys

ROOT = Path("docs/data/library")
POLICY = ROOT / "policy.json"
LOG = ROOT / "ladder_advance_log.json"


def _append_log(entry: dict) -> None:
    rows: list = []
    if LOG.exists():
        try:
            rows = json.loads(LOG.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                rows = [rows]
        except json.JSONDecodeError:
            rows = []
    rows.append(entry)
    LOG.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def stage_graduate() -> dict:
    event = maybe_graduate_focus(ROOT, POLICY)
    policy = load_policy(POLICY)
    out = {
        "stage": "graduate",
        "at": datetime.now(UTC).isoformat(),
        "event": event,
        "focus_after": policy.get("focus_market"),
        "graduated_markets": policy.get("graduated_markets"),
    }
    _append_log(out)
    print(json.dumps(out, indent=2), flush=True)
    return out


def stage_grow(*, max_tickers: int | None = None) -> dict:
    policy = load_policy(POLICY)
    focus = str(policy.get("focus_market") or "")
    if not focus:
        raise SystemExit("No focus_market in policy")
    refresh_constituents(ROOT, focus)
    status_before = library_status(ROOT, markets=[focus])[0]
    # Grow everyone never-fetched / stale in one pass when max_tickers omitted.
    ticker_count = int(status_before.get("ticker_count") or 0)
    cap = int(max_tickers) if max_tickers is not None else max(ticker_count, 50)
    results = grow_library(
        ROOT,
        markets=[focus],
        max_tickers_per_run=cap,
        refresh_constituents_first=False,
    )
    status_after = library_status(ROOT, markets=[focus])[0]
    out = {
        "stage": "grow",
        "at": datetime.now(UTC).isoformat(),
        "market": focus,
        "max_tickers": cap,
        "result": results[0] if results else {},
        "status": status_after,
    }
    _append_log(out)
    print(json.dumps(out, indent=2), flush=True)
    return out


def stage_screen() -> dict:
    policy = load_policy(POLICY)
    focus = str(policy.get("focus_market") or "")
    result = run_library_screen(ROOT, focus)
    out = {
        "stage": "screen",
        "at": datetime.now(UTC).isoformat(),
        "market": focus,
        "summary": result.summary,
    }
    _append_log(out)
    print(json.dumps(out, indent=2), flush=True)
    return out


def stage_research(*, weekly_cap: int | None = None) -> dict:
    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        raise SystemExit("CURSOR_API_KEY missing")
    policy = load_policy(POLICY)
    focus = str(policy.get("focus_market") or "")
    model = research_model_id(policy)
    memo_cost = float((policy.get("ladder") or {}).get("estimated_memo_usd") or 0.4)
    hard_cap = int((policy.get("ladder") or {}).get("research_hard_cap") or 12)
    cap = int(weekly_cap) if weekly_cap is not None else hard_cap

    screen_result = run_library_screen(ROOT, focus)
    reports = library_research_reports(screen_result)
    targets = eligible_research_targets(reports, weekly_cap=cap)
    if not targets:
        out = {
            "stage": "research",
            "at": datetime.now(UTC).isoformat(),
            "market": focus,
            "executed": 0,
            "reason": "no eligible targets",
            "summary": screen_result.summary,
        }
        _append_log(out)
        print(json.dumps(out, indent=2), flush=True)
        return out

    summary = run_research_for_strong_buys(
        reports=reports,
        output_dir=screen_result.screen_dir,
        api_key=api_key,
        model=model,
        weekly_cap=cap,
        market=focus,
    )
    executed = int(summary.created) + int(summary.updated)
    spend = round(executed * memo_cost, 4)
    if executed > 0:
        record_estimated_spend(spend, POLICY)
    policy_after = load_policy(POLICY)
    ladder = policy_after.setdefault("ladder", {})
    ladder["last_run"] = {
        "run_at": datetime.now(UTC).isoformat(),
        "focus_market": focus,
        "focus_market_after": focus,
        "screen_shortlist": screen_result.summary.get("shortlist_count"),
        "research": {
            "model": model,
            "research_cap": cap,
            "executed": executed,
            "created": summary.created,
            "updated": summary.updated,
            "errors": summary.errors,
            "estimated_spend_usd": spend,
            "targets": [
                {"ticker": t.ticker, "signal": t.signal, "conviction_score": t.conviction_score}
                for t in targets
            ],
        },
    }
    save_policy(policy_after, POLICY)
    out = {
        "stage": "research",
        "at": datetime.now(UTC).isoformat(),
        "market": focus,
        "executed": executed,
        "created": summary.created,
        "updated": summary.updated,
        "errors": summary.errors,
        "estimated_spend_usd": spend,
        "targets": [t.ticker for t in targets],
        "cycle_spend_after": (policy_after.get("budget") or {}).get(
            "estimated_spend_usd_this_cycle"
        ),
    }
    _append_log(out)
    print(json.dumps(out, indent=2), flush=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("graduate", "grow", "screen", "research", "status"),
        required=True,
    )
    parser.add_argument("--max-tickers", type=int, default=None)
    parser.add_argument("--research-cap", type=int, default=None)
    args = parser.parse_args()

    if args.stage == "status":
        policy = load_policy(POLICY)
        payload = {
            "focus_market": policy.get("focus_market"),
            "graduated_markets": policy.get("graduated_markets"),
            "budget": policy.get("budget"),
            "status": library_status(ROOT),
        }
        print(json.dumps(payload, indent=2))
        return 0
    if args.stage == "graduate":
        stage_graduate()
    elif args.stage == "grow":
        stage_grow(max_tickers=args.max_tickers)
    elif args.stage == "screen":
        stage_screen()
    elif args.stage == "research":
        stage_research(weekly_cap=args.research_cap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
