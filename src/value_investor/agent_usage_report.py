"""Weekly and plan-cycle roll-up of the real agent token ledger.

The estimated-USD ledger (``budget.estimated_spend_*``, about $0.40 per memo)
stays the hard gate. This report puts server ``raw_cost_cents`` beside that
estimate so the owner can calibrate ``token_usage_weekly_warning_raw_usd``.
Null threshold is measuring mode: an info finding, not a warn.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    DEFAULT_PLAN_REFRESH_DAY,
    load_policy,
)
from value_investor.agent_usage import (
    DEFAULT_LOG_PATH,
    backfill_pending_costs,
    parse_usage_timestamp,
    read_usage_rows,
)
from value_investor.storage import write_json

DEFAULT_WEEKLY_PATH = Path("docs/data/agent_usage_weekly.json")
ESTIMATED_MEMO_USD = 0.4
WARN_FRACTION = 0.8
COVERAGE_GAP_FRACTION = 0.10
PENDING_STALE = timedelta(hours=48)

MEASURING_TITLE = "Agent token usage (measuring)"
NEAR_TITLE = "Agent token usage near weekly warning"
OVER_TITLE = "Agent token usage over weekly warning"
COVERAGE_TITLE = "Agent token usage coverage gap"

_TOKEN_KINDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
    "reasoning_tokens",
)


def iso_week_id(moment: datetime) -> str:
    iso = moment.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def plan_cycle_id(moment: datetime, refresh_day: int) -> str:
    """Match ``record_estimated_spend``: calendar month plus the refresh day.

    The id is ``YYYY-MM-dN`` from ``budget.plan_refresh_day_of_month``. It is
    the same label the estimated-USD ledger stores on ``budget.cycle_id``.
    """
    day = max(1, min(28, int(refresh_day)))
    return f"{moment.year}-{moment.month:02d}-d{day}"


def _percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percent / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    fraction = rank - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _empty_tokens() -> dict[str, int]:
    return {name: 0 for name in _TOKEN_KINDS}


def _add_tokens(total: dict[str, int], row: dict[str, Any]) -> None:
    for name in _TOKEN_KINDS:
        value = row.get(name)
        if value is None:
            continue
        try:
            total[name] += int(value)
        except (TypeError, ValueError):
            continue


def _cents_to_usd(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / 100.0
    except (TypeError, ValueError):
        return None


def _new_bucket(bucket_id: str) -> dict[str, Any]:
    return {
        "id": bucket_id,
        "runs": 0,
        "usage_error_runs": 0,
        "cost_pending_runs": 0,
        "cost_pending_after_48h_runs": 0,
        "coverage_gap_rows": 0,
        "coverage_gap_fraction": 0.0,
        "tokens": _empty_tokens(),
        "raw_cost_usd": 0.0,
        "charged_usd": 0.0,
        "by_job": {},
        "by_model": {},
        "research_memo_raw_costs_usd": [],
    }


def _group(bucket: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    groups = bucket[key]
    row = groups.get(label)
    if row is None:
        row = {
            "runs": 0,
            "pending": 0,
            "usage_errors": 0,
            "tokens": _empty_tokens(),
            "raw_cost_usd": 0.0,
            "charged_usd": 0.0,
        }
        groups[label] = row
    return row


def _accumulate(bucket: dict[str, Any], row: dict[str, Any], *, now: datetime) -> None:
    bucket["runs"] += 1
    usage_error = bool(row.get("usage_error"))
    pending = bool(row.get("cost_pending"))
    stamp = parse_usage_timestamp(row.get("timestamp"))
    stale_pending = False
    if pending and stamp is not None and (now - stamp) >= PENDING_STALE:
        stale_pending = True
        bucket["cost_pending_after_48h_runs"] += 1
    if usage_error:
        bucket["usage_error_runs"] += 1
    if pending:
        bucket["cost_pending_runs"] += 1
    if usage_error or stale_pending:
        bucket["coverage_gap_rows"] += 1
    _add_tokens(bucket["tokens"], row)
    raw = _cents_to_usd(row.get("raw_cost_cents"))
    charged = _cents_to_usd(row.get("charged_cents"))
    if raw is not None and not pending:
        bucket["raw_cost_usd"] = round(bucket["raw_cost_usd"] + raw, 6)
    if charged is not None and not pending:
        bucket["charged_usd"] = round(bucket["charged_usd"] + charged, 6)
    job = str(row.get("job") or "unknown")
    model = str(row.get("model") or "unknown")
    for key, label in (("by_job", job), ("by_model", model)):
        group = _group(bucket, key, label)
        group["runs"] += 1
        if pending:
            group["pending"] += 1
        if usage_error:
            group["usage_errors"] += 1
        _add_tokens(group["tokens"], row)
        if raw is not None and not pending:
            group["raw_cost_usd"] = round(group["raw_cost_usd"] + raw, 6)
        if charged is not None and not pending:
            group["charged_usd"] = round(group["charged_usd"] + charged, 6)
    if job == "research_memo" and raw is not None and not pending:
        bucket["research_memo_raw_costs_usd"].append(raw)


def _finish_bucket(bucket: dict[str, Any], *, estimated_memo_usd: float) -> dict[str, Any]:
    runs = int(bucket["runs"])
    gap = int(bucket["coverage_gap_rows"])
    costs = list(bucket.pop("research_memo_raw_costs_usd"))
    memo_runs = int((bucket["by_job"].get("research_memo") or {}).get("runs") or 0)
    bucket["coverage_gap_fraction"] = round(gap / runs, 4) if runs else 0.0
    bucket["raw_cost_usd"] = round(float(bucket["raw_cost_usd"]), 4)
    bucket["charged_usd"] = round(float(bucket["charged_usd"]), 4)
    for group in list(bucket["by_job"].values()) + list(bucket["by_model"].values()):
        group["raw_cost_usd"] = round(float(group["raw_cost_usd"]), 4)
        group["charged_usd"] = round(float(group["charged_usd"]), 4)
    median = _percentile(costs, 50)
    p90 = _percentile(costs, 90)
    bucket["research_memo"] = {
        "runs": memo_runs,
        "runs_with_raw_cost": len(costs),
        "raw_cost_usd_median": None if median is None else round(median, 4),
        "raw_cost_usd_p90": None if p90 is None else round(p90, 4),
        "estimated_memo_usd": estimated_memo_usd,
    }
    return bucket


def _policy_context(policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = policy if policy is not None else load_policy()
    budget = policy.get("budget") or {}
    ladder = policy.get("ladder") or {}
    refresh = int(budget.get("plan_refresh_day_of_month") or DEFAULT_PLAN_REFRESH_DAY)
    threshold = budget.get("token_usage_weekly_warning_raw_usd")
    if threshold is not None:
        threshold = float(threshold)
    memo = ladder.get("estimated_memo_usd")
    try:
        estimated_memo = float(memo) if memo is not None else ESTIMATED_MEMO_USD
    except (TypeError, ValueError):
        estimated_memo = ESTIMATED_MEMO_USD
    return {
        "policy": policy,
        "refresh_day": refresh,
        "threshold": threshold,
        "estimated_memo_usd": estimated_memo,
        "week_id": budget.get("week_id"),
        "cycle_id": budget.get("cycle_id"),
        "estimated_spend_usd_this_week": budget.get("estimated_spend_usd_this_week"),
        "estimated_spend_usd_this_cycle": budget.get("estimated_spend_usd_this_cycle"),
    }


def build_usage_report(
    rows: list[dict[str, Any]] | None = None,
    *,
    log_path: Path | None = None,
    policy: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    context = _policy_context(policy)
    source = rows if rows is not None else read_usage_rows(log_path)
    weeks: dict[str, dict[str, Any]] = {}
    cycles: dict[str, dict[str, Any]] = {}
    for row in source:
        stamp = parse_usage_timestamp(row.get("timestamp"))
        if stamp is None:
            continue
        week_key = iso_week_id(stamp)
        cycle_key = plan_cycle_id(stamp, context["refresh_day"])
        weeks.setdefault(week_key, _new_bucket(week_key))
        cycles.setdefault(cycle_key, _new_bucket(cycle_key))
        _accumulate(weeks[week_key], row, now=moment)
        _accumulate(cycles[cycle_key], row, now=moment)

    estimated_memo = float(context["estimated_memo_usd"])
    week_rows = [
        _finish_bucket(bucket, estimated_memo_usd=estimated_memo)
        for _, bucket in sorted(weeks.items())
    ]
    cycle_rows = [
        _finish_bucket(bucket, estimated_memo_usd=estimated_memo)
        for _, bucket in sorted(cycles.items())
    ]
    for bucket in week_rows:
        matches = bucket["id"] == context["week_id"]
        bucket["estimated_ledger_usd_this_week"] = (
            context["estimated_spend_usd_this_week"] if matches else None
        )
        bucket["estimated_ledger_week_matches"] = bool(matches)
    for bucket in cycle_rows:
        matches = bucket["id"] == context["cycle_id"]
        bucket["estimated_ledger_usd_this_cycle"] = (
            context["estimated_spend_usd_this_cycle"] if matches else None
        )
        bucket["estimated_ledger_cycle_matches"] = bool(matches)

    return {
        "schema_version": 1,
        "generated_at": moment.isoformat(),
        "plan_refresh_day_of_month": context["refresh_day"],
        "estimated_memo_usd": estimated_memo,
        "token_usage_weekly_warning_raw_usd": context["threshold"],
        "current_week_id": iso_week_id(moment),
        "current_cycle_id": plan_cycle_id(moment, context["refresh_day"]),
        "weeks": week_rows,
        "cycles": cycle_rows,
    }


def _money(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if abs(number) >= 0.01:
        return f"${number:.2f}"
    return f"${number:.4f}"


def _top_jobs(bucket: dict[str, Any], limit: int = 3) -> str:
    jobs = bucket.get("by_job") or {}
    ranked = sorted(
        jobs.items(),
        key=lambda item: (-float(item[1].get("raw_cost_usd") or 0), -int(item[1].get("runs") or 0)),
    )
    if not ranked:
        return "none"
    parts = []
    for name, row in ranked[:limit]:
        parts.append(f"{name} {_money(row.get('raw_cost_usd'))} ({int(row.get('runs') or 0)} runs)")
    return ", ".join(parts)


def _summary(bucket: dict[str, Any], *, threshold: float | None, mode: str) -> str:
    tokens = bucket.get("tokens") or {}
    memo = bucket.get("research_memo") or {}
    ledger = bucket.get("estimated_ledger_usd_this_week")
    ledger_bit = (
        f"Estimated-USD ledger this week {_money(ledger)}."
        if bucket.get("estimated_ledger_week_matches")
        else "Estimated-USD ledger has no total for this ISO week (policy week_id differs)."
    )
    threshold_bit = (
        "Measuring mode (token_usage_weekly_warning_raw_usd is null)."
        if threshold is None
        else f"Warning threshold {_money(threshold)} ({mode})."
    )
    return (
        f"Week {bucket.get('id')}: raw {_money(bucket.get('raw_cost_usd'))}, "
        f"charged {_money(bucket.get('charged_usd'))}, "
        f"tokens {int(tokens.get('total_tokens') or 0)} "
        f"(in {int(tokens.get('input_tokens') or 0)} / "
        f"out {int(tokens.get('output_tokens') or 0)} / "
        f"cache_read {int(tokens.get('cache_read_tokens') or 0)} / "
        f"cache_write {int(tokens.get('cache_write_tokens') or 0)}). "
        f"Top jobs: {_top_jobs(bucket)}. "
        f"Research memo raw median {_money(memo.get('raw_cost_usd_median'))} / "
        f"p90 {_money(memo.get('raw_cost_usd_p90'))} vs ledger estimate "
        f"{_money(memo.get('estimated_memo_usd'))} "
        f"({int(memo.get('runs_with_raw_cost') or 0)} of "
        f"{int(memo.get('runs') or 0)} runs with cost). "
        f"{ledger_bit} {threshold_bit}"
    )


def usage_warning_findings(
    report: dict[str, Any],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Observe findings. ``auto_fixable`` is always false.

    Measuring mode (null threshold) is info. A numeric threshold warns at 80%
    and at 100% of week-to-date raw cost. Coverage is info when more than 10%
    of the current week's rows have ``usage_error`` or are still cost-pending
    after 48 hours.
    """
    del now
    week_id = str(report.get("current_week_id") or "")
    bucket = next((row for row in report.get("weeks") or [] if row.get("id") == week_id), None)
    if bucket is None or int(bucket.get("runs") or 0) <= 0:
        return []
    threshold = report.get("token_usage_weekly_warning_raw_usd")
    raw = float(bucket.get("raw_cost_usd") or 0.0)
    findings: list[dict[str, Any]] = []
    if threshold is None:
        findings.append(
            {
                "severity": "info",
                "category": "budget",
                "title": MEASURING_TITLE,
                "summary": _summary(bucket, threshold=None, mode="measuring"),
                "auto_fixable": False,
            }
        )
    else:
        limit = float(threshold)
        if limit > 0 and raw >= limit:
            mode = "over 100%"
            title = OVER_TITLE
            severity = "warn"
        elif limit > 0 and raw >= limit * WARN_FRACTION:
            mode = "at least 80%"
            title = NEAR_TITLE
            severity = "warn"
        elif limit <= 0 and raw > 0:
            mode = "over a zero threshold"
            title = OVER_TITLE
            severity = "warn"
        else:
            mode = "under 80%"
            title = MEASURING_TITLE
            severity = "info"
        findings.append(
            {
                "severity": severity,
                "category": "budget",
                "title": title,
                "summary": _summary(bucket, threshold=limit, mode=mode),
                "auto_fixable": False,
            }
        )
    fraction = float(bucket.get("coverage_gap_fraction") or 0.0)
    if fraction > COVERAGE_GAP_FRACTION:
        findings.append(
            {
                "severity": "info",
                "category": "budget",
                "title": COVERAGE_TITLE,
                "summary": (
                    f"Week {bucket.get('id')}: {int(bucket.get('coverage_gap_rows') or 0)} of "
                    f"{int(bucket.get('runs') or 0)} rows "
                    f"({fraction:.0%}) have usage_error or are still cost-pending after 48h "
                    f"(usage_error {int(bucket.get('usage_error_runs') or 0)}, "
                    f"pending after 48h {int(bucket.get('cost_pending_after_48h_runs') or 0)}). "
                    "Coverage gap only — the estimated-USD cap is unchanged."
                ),
                "auto_fixable": False,
            }
        )
    return findings


def write_usage_report(
    report: dict[str, Any],
    path: Path | None = None,
) -> Path:
    target = Path(path) if path is not None else DEFAULT_WEEKLY_PATH
    return write_json(target, report, compact=False)


def collect_token_usage_report(
    *,
    log_path: Path | None = None,
    weekly_path: Path | None = None,
    policy: dict[str, Any] | None = None,
    policy_path: Path | None = None,
    now: datetime | None = None,
    backfill: bool | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    """Backfill pending cost when enabled, write the weekly roll-up, build findings."""
    moment = now or datetime.now(UTC)
    do_backfill = _should_backfill(backfill)
    backfill_report = None
    if do_backfill:
        backfill_report = backfill_pending_costs(log_path=log_path, now=moment)
    loaded = policy if policy is not None else load_policy(policy_path)
    report = build_usage_report(log_path=log_path, policy=loaded, now=moment)
    if backfill_report is not None:
        report["backfill"] = {
            "queried_agents": backfill_report.get("queried_agents"),
            "updated_rows": backfill_report.get("updated_rows"),
            "still_pending": backfill_report.get("still_pending"),
            "skipped": backfill_report.get("skipped"),
            "reason": backfill_report.get("reason"),
            "read_only": backfill_report.get("read_only"),
            "method": backfill_report.get("method"),
            "errors": backfill_report.get("errors"),
        }
    write_usage_report(report, weekly_path)
    return report, usage_warning_findings(report, now=moment), backfill_report


def _should_backfill(backfill: bool | None) -> bool:
    if backfill is not None:
        return backfill
    from value_investor.agent_usage import _backfill_enabled

    return _backfill_enabled()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Roll up Cursor agent token usage")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_WEEKLY_PATH)
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Re-query cost_pending rows (read-only get_usage; no model send)",
    )
    parser.add_argument("--no-backfill", action="store_true")
    args = parser.parse_args(argv)
    backfill: bool | None
    if args.backfill:
        backfill = True
    elif args.no_backfill:
        backfill = False
    else:
        backfill = None
    report, findings, _backfill = collect_token_usage_report(
        log_path=args.log,
        weekly_path=args.out,
        policy_path=args.policy,
        backfill=backfill,
    )
    print(
        json.dumps(
            {
                "wrote": str(args.out),
                "findings": findings,
                "current_week_id": report.get("current_week_id"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
