#!/usr/bin/env python3
"""Finish remaining quality strong-buy research memos for the S&P library screen."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.agent_model_policy import (
    load_policy,
    record_estimated_spend,
    remaining_weekly_budget_usd,
    research_model_id,
    save_policy,
)
from value_investor.data_quality import MIN_QUALITY_FOR_STRONG_BUY
from value_investor.research.runner import run_research_for_strong_buys
from value_investor.research.store import ResearchStore
from value_investor.summary import build_company_reports

ROOT = Path("docs/data/library")
POLICY = ROOT / "policy.json"
SCREEN = ROOT / "markets" / "sp500" / "screen"
LOG = SCREEN / "research_remaining_finish.json"
ESTIMATED_MEMO_USD = 0.40


def main() -> int:
    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        raise SystemExit("CURSOR_API_KEY missing")

    policy = load_policy(POLICY)
    model = research_model_id(policy)
    memo_cost = float((policy.get("ladder") or {}).get("estimated_memo_usd") or ESTIMATED_MEMO_USD)

    signals = pd.read_csv(SCREEN / "latest_signals.csv")
    model_results = pd.read_csv(SCREEN / "latest_model_results.csv")
    reports = build_company_reports(signals, model_results)
    store = ResearchStore(SCREEN)
    existing = {doc.ticker for doc in store.list_documents()}

    remaining = [
        report
        for report in reports
        if report.signal == "strong_buy"
        and report.data_quality_score >= MIN_QUALITY_FOR_STRONG_BUY
        and report.ticker not in existing
    ]
    remaining.sort(
        key=lambda r: (
            r.conviction_score,
            r.composite_score if r.composite_score is not None else -1.0,
        ),
        reverse=True,
    )
    if not remaining:
        print("No remaining quality strong buys without memos.", flush=True)
        return 0

    before_cycle = float((policy.get("budget") or {}).get("estimated_spend_usd_this_cycle") or 0.0)
    log: dict = {
        "test": "sp500_finish_remaining_strong_buys",
        "started_at": datetime.now(UTC).isoformat(),
        "model": model,
        "estimated_memo_usd": memo_cost,
        "estimated_spend_usd_this_cycle_before": before_cycle,
        "existing_memos": sorted(existing),
        "targets": [
            {
                "ticker": t.ticker,
                "name": t.name,
                "signal": t.signal,
                "conviction_score": t.conviction_score,
                "data_quality_score": t.data_quality_score,
            }
            for t in remaining
        ],
    }
    LOG.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    print(f"Finishing {len(remaining)} remaining strong buys with {model}", flush=True)
    for row in log["targets"]:
        print(
            f"  {row['ticker']:5} conv={row['conviction_score']:.3f} q={row['data_quality_score']:.2f}",
            flush=True,
        )

    t0 = time.time()
    summary = run_research_for_strong_buys(
        reports=remaining,
        output_dir=SCREEN,
        api_key=api_key,
        model=model,
        weekly_cap=len(remaining),
        continue_alumni=False,
        market="sp500",
    )
    elapsed = time.time() - t0
    executed = int(summary.created) + int(summary.updated)
    estimated_spend = round(executed * memo_cost, 4)
    if executed > 0:
        record_estimated_spend(estimated_spend, POLICY)

    policy_after = load_policy(POLICY)
    ladder = policy_after.setdefault("ladder", {})
    ladder["last_run"] = {
        "run_at": datetime.now(UTC).isoformat(),
        "focus_market": "sp500",
        "focus_market_after": "sp500",
        "research": {
            "test": "finish_remaining_strong_buys",
            "model": model,
            "research_cap": len(remaining),
            "enforce_weekly_research_cap": bool(
                (policy_after.get("budget") or {}).get("enforce_weekly_research_cap", False)
            ),
            "targets": log["targets"],
            "executed": executed,
            "created": summary.created,
            "updated": summary.updated,
            "errors": summary.errors,
            "estimated_spend_usd": estimated_spend,
            "elapsed_seconds": round(elapsed, 1),
            "remaining_usd_after": remaining_weekly_budget_usd(policy_after),
        },
        "graduation": {"skipped": True},
        "maintenance": {"skipped": True},
    }
    save_policy(policy_after, POLICY)

    log.update(
        {
            "finished_at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(elapsed, 1),
            "created": summary.created,
            "updated": summary.updated,
            "errors": summary.errors,
            "executed": executed,
            "estimated_spend_usd": estimated_spend,
            "estimated_spend_usd_this_cycle_after": (
                policy_after.get("budget") or {}
            ).get("estimated_spend_usd_this_cycle"),
            "documents": [d.ticker for d in summary.documents],
        }
    )
    LOG.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: log[k] for k in (
        "executed", "created", "updated", "errors", "estimated_spend_usd",
        "elapsed_seconds", "estimated_spend_usd_this_cycle_after", "documents",
    )}, indent=2), flush=True)
    return 0 if not summary.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
