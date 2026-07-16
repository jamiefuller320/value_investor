#!/usr/bin/env python3
"""Run S&P library research under the weekly selection model (cost-impact test).

Uses DEFAULT_RESEARCH_WEEKLY_CAP (12): quality strong buys first, then buys.
Intentionally bypasses the depleted weekly $2 strand gate so we can measure
spend against the monthly Pro pool. Records estimated spend in policy.json.
"""

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
from value_investor.research.runner import (
    DEFAULT_RESEARCH_WEEKLY_CAP,
    eligible_research_targets,
    run_research_for_strong_buys,
)
from value_investor.summary import build_company_reports

ROOT = Path("docs/data/library")
POLICY = ROOT / "policy.json"
SCREEN = ROOT / "markets" / "sp500" / "screen"
LOG = SCREEN / "research_cost_test.json"
ESTIMATED_MEMO_USD = 0.40


def main() -> int:
    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        raise SystemExit("CURSOR_API_KEY missing")

    policy = load_policy(POLICY)
    model = research_model_id(policy)
    memo_cost = float((policy.get("ladder") or {}).get("estimated_memo_usd") or ESTIMATED_MEMO_USD)
    weekly_cap = DEFAULT_RESEARCH_WEEKLY_CAP

    signals = pd.read_csv(SCREEN / "latest_signals.csv")
    model_results = pd.read_csv(SCREEN / "latest_model_results.csv")
    reports = build_company_reports(signals, model_results)
    targets = eligible_research_targets(reports, weekly_cap=weekly_cap)

    before_week = float((policy.get("budget") or {}).get("estimated_spend_usd_this_week") or 0.0)
    before_cycle = float((policy.get("budget") or {}).get("estimated_spend_usd_this_cycle") or 0.0)
    remaining_before = remaining_weekly_budget_usd(policy)

    log: dict = {
        "test": "sp500_research_cost_impact",
        "started_at": datetime.now(UTC).isoformat(),
        "model": model,
        "weekly_cap": weekly_cap,
        "selection_rule": "eligible_research_targets: quality strong_buy first, then buy to fill cap",
        "budget_gate_bypassed": True,
        "budget_gate_note": (
            "Weekly library strand nearly exhausted; run continues for cost-impact "
            "measurement against monthly Pro pool."
        ),
        "estimated_memo_usd": memo_cost,
        "remaining_weekly_usd_before": remaining_before,
        "estimated_spend_usd_this_week_before": before_week,
        "estimated_spend_usd_this_cycle_before": before_cycle,
        "targets": [
            {
                "ticker": t.ticker,
                "name": t.name,
                "signal": t.signal,
                "conviction_score": t.conviction_score,
                "data_quality_score": t.data_quality_score,
            }
            for t in targets
        ],
    }
    LOG.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    print(
        f"Research cost test: {len(targets)} targets, model={model}, "
        f"cap={weekly_cap}, remaining_weekly=${remaining_before:.2f}",
        flush=True,
    )
    for row in log["targets"]:
        print(
            f"  {row['ticker']:5} {row['signal']:11} "
            f"conv={row['conviction_score']:.3f} q={row['data_quality_score']:.2f}",
            flush=True,
        )

    t0 = time.time()
    summary = run_research_for_strong_buys(
        reports=reports,
        output_dir=SCREEN,
        api_key=api_key,
        model=model,
        weekly_cap=weekly_cap,
        continue_alumni=True,
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
        "screen_shortlist": int((signals["signal"].isin(["strong_buy", "buy"])).sum())
        if "signal" in signals.columns
        else None,
        "research": {
            "test": "cost_impact",
            "model": model,
            "research_cap": weekly_cap,
            "budget_gate_bypassed": True,
            "remaining_usd_before": remaining_before,
            "targets": log["targets"],
            "executed": executed,
            "created": summary.created,
            "updated": summary.updated,
            "skipped": summary.skipped,
            "errors": summary.errors,
            "alumni_updated": summary.alumni_updated,
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
            "skipped": summary.skipped,
            "alumni_updated": summary.alumni_updated,
            "errors": summary.errors,
            "executed": executed,
            "estimated_spend_usd": estimated_spend,
            "estimated_spend_usd_this_week_after": (
                policy_after.get("budget") or {}
            ).get("estimated_spend_usd_this_week"),
            "estimated_spend_usd_this_cycle_after": (
                policy_after.get("budget") or {}
            ).get("estimated_spend_usd_this_cycle"),
            "remaining_weekly_usd_after": remaining_weekly_budget_usd(policy_after),
            "documents": [d.ticker for d in summary.documents],
        }
    )
    LOG.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: log[k] for k in (
        "executed", "created", "updated", "errors", "estimated_spend_usd",
        "elapsed_seconds", "estimated_spend_usd_this_week_after",
        "estimated_spend_usd_this_cycle_after", "remaining_weekly_usd_after",
    )}, indent=2), flush=True)
    return 0 if not summary.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
