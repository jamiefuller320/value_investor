"""Cycle-end Cursor surplus → provisional weekly_ops bump with next-cycle review.

Cursor does not expose remaining plan credits. The operator declares unused
fraction (Ultra usage page — included-pool meter). A transfer fraction of that
leftover becomes a *provisional* raise of ``weekly_ops_cap_usd`` (estimated
on-demand USD meter), never past ``weekly_ops_plan_credit_share_cap`` of listed
plan credit (default 15% / week). Do not infer leftover dollars from estimated
token spend divided by a usage-page percentage. Rememo daily caps stay fixed.

Human review at the next billing-cycle end keeps or reverts the bump.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    DEFAULT_PLAN_REFRESH_DAY,
    DEFAULT_WEEKLY_OPS_PLAN_CREDIT_SHARE_CAP,
    load_policy,
    normalize_budget,
    save_policy,
    weekly_ops_budget_status,
)
from value_investor.storage import read_json, write_json

DEFAULT_ARTIFACT_PATH = Path("docs/data/cycle_budget_surplus.json")
DEFAULT_TRANSFER_FRACTION = 0.25
DEFAULT_MAX_WEEKLY_BUMP_USD = 20.0
DEFAULT_ULTRA_MONTHLY_USD = 200.0
DEFAULT_PLAN_CREDIT_SHARE_CAP = DEFAULT_WEEKLY_OPS_PLAN_CREDIT_SHARE_CAP
WEEKS_PER_CYCLE = 4.0
APPLY_ACTIONS = frozenset({"propose_bump", "replace_provisional", "clamp_to_ceiling"})


def current_cycle_id(
    *,
    now: datetime | None = None,
    refresh_day: int = DEFAULT_PLAN_REFRESH_DAY,
) -> str:
    now = now or datetime.now(UTC)
    day = max(1, min(28, int(refresh_day)))
    return f"{now.year}-{now.month:02d}-d{day}"


def next_cycle_id(cycle_id: str, *, refresh_day: int | None = None) -> str:
    """``2026-09-d8`` → ``2026-10-d8`` (same refresh day)."""
    text = str(cycle_id or "").strip()
    parts = text.split("-")
    if len(parts) < 3:
        raise ValueError(f"invalid cycle_id: {cycle_id!r}")
    year = int(parts[0])
    month = int(parts[1])
    day = refresh_day
    if day is None:
        day_token = parts[2]
        day = int(day_token[1:]) if day_token.startswith("d") else int(day_token)
    day = max(1, min(28, int(day)))
    if month == 12:
        return f"{year + 1}-01-d{day}"
    return f"{year}-{month + 1:02d}-d{day}"


def _round_usd(value: float) -> float:
    return round(float(value), 2)


def weekly_ops_plan_credit_ceiling_usd(
    plan_monthly_usd: float,
    share: float = DEFAULT_PLAN_CREDIT_SHARE_CAP,
) -> float:
    """Max weekly_ops envelope as a share of listed plan credit."""
    return _round_usd(max(0.0, float(plan_monthly_usd) * float(share)))


def _resolved_plan_credit_share(
    *,
    share: float | None,
    budget: dict[str, Any],
) -> float:
    if share is not None:
        return max(0.0, min(1.0, float(share)))
    raw = budget.get("weekly_ops_plan_credit_share_cap")
    if raw is None:
        return DEFAULT_PLAN_CREDIT_SHARE_CAP
    return max(0.0, min(1.0, float(raw)))


def assess_cycle_surplus(
    *,
    unused_fraction: float | None = None,
    unused_usd: float | None = None,
    plan_monthly_usd: float = DEFAULT_ULTRA_MONTHLY_USD,
    transfer_fraction: float = DEFAULT_TRANSFER_FRACTION,
    max_weekly_bump_usd: float = DEFAULT_MAX_WEEKLY_BUMP_USD,
    plan_credit_share_cap: float | None = None,
    replace_provisional: bool = False,
    policy: dict[str, Any] | None = None,
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Propose a provisional weekly_ops bump from declared cycle leftover."""
    if unused_usd is None and unused_fraction is None:
        raise ValueError("unused_usd or unused_fraction is required")
    if unused_usd is not None and unused_usd < 0:
        raise ValueError("unused_usd must be >= 0")
    if unused_fraction is not None and (unused_fraction < 0 or unused_fraction > 1):
        raise ValueError("unused_fraction must be between 0 and 1")
    if transfer_fraction < 0 or transfer_fraction > 1:
        raise ValueError("transfer_fraction must be between 0 and 1")
    if plan_credit_share_cap is not None and (
        plan_credit_share_cap < 0 or plan_credit_share_cap > 1
    ):
        raise ValueError("plan_credit_share_cap must be between 0 and 1")

    policy = policy or load_policy(path)
    budget = normalize_budget(policy.get("budget"))
    ops = weekly_ops_budget_status(policy)
    refresh_day = int(budget.get("plan_refresh_day_of_month") or DEFAULT_PLAN_REFRESH_DAY)
    now = now or datetime.now(UTC)
    cycle_id = str(budget.get("cycle_id") or current_cycle_id(now=now, refresh_day=refresh_day))
    review_cycle = next_cycle_id(cycle_id, refresh_day=refresh_day)
    existing = dict(budget.get("cycle_surplus_provisional") or {})

    live_cap = float(ops.get("weekly_ops_cap_usd") or 0.0)
    rebase_cap = live_cap
    if replace_provisional and existing.get("status") == "provisional":
        previous = float(existing.get("previous_weekly_ops_cap_usd") or 0.0)
        if previous > 0:
            rebase_cap = previous

    if unused_usd is not None:
        unused_monthly = _round_usd(unused_usd)
        unused_frac = (
            round(unused_monthly / float(plan_monthly_usd), 4) if plan_monthly_usd else None
        )
    else:
        unused_frac = round(float(unused_fraction), 4)
        unused_monthly = _round_usd(float(plan_monthly_usd) * float(unused_fraction))

    transfer = _round_usd(max(0.0, unused_monthly * float(transfer_fraction)))
    raw_weekly = transfer / WEEKS_PER_CYCLE
    cap_limit = min(float(max_weekly_bump_usd), rebase_cap * 0.5 if rebase_cap else 0.0)
    surplus_bump = _round_usd(max(0.0, min(raw_weekly, cap_limit)))
    unclamped_cap = _round_usd(rebase_cap + surplus_bump)
    share = _resolved_plan_credit_share(share=plan_credit_share_cap, budget=budget)
    ceiling = weekly_ops_plan_credit_ceiling_usd(plan_monthly_usd, share)
    proposed_cap = _round_usd(min(unclamped_cap, ceiling)) if plan_monthly_usd else unclamped_cap
    weekly_bump = _round_usd(proposed_cap - rebase_cap)
    ceiling_bound = bool(plan_monthly_usd and unclamped_cap > ceiling)

    if abs(proposed_cap - live_cap) < 0.01:
        action = "none"
    elif ceiling_bound and proposed_cap < live_cap:
        action = "clamp_to_ceiling"
    elif existing.get("status") == "provisional" and existing.get("review_cycle_id"):
        action = "replace_provisional" if replace_provisional else "already_provisional"
    elif weekly_bump > 0:
        action = "propose_bump"
    else:
        action = "none"

    return {
        "schema_version": 1,
        "assessed_at": now.isoformat(),
        "cycle_id": cycle_id,
        "review_cycle_id": review_cycle,
        "plan_name": budget.get("plan_name") or "Cursor",
        "plan_monthly_usd": _round_usd(plan_monthly_usd),
        "unused_fraction": unused_frac,
        "unused_usd_declared": unused_usd is not None,
        "unused_monthly_usd": unused_monthly,
        "transfer_fraction": round(float(transfer_fraction), 4),
        "transfer_usd": transfer,
        "weekly_bump_usd": weekly_bump,
        "surplus_weekly_bump_usd": surplus_bump,
        "unclamped_weekly_ops_cap_usd": unclamped_cap,
        "plan_credit_share_cap": share,
        "plan_credit_ceiling_usd": ceiling,
        "ceiling_bound": ceiling_bound,
        "max_weekly_bump_usd": _round_usd(max_weekly_bump_usd),
        "current_weekly_ops_cap_usd": live_cap,
        "rebase_weekly_ops_cap_usd": rebase_cap,
        "proposed_weekly_ops_cap_usd": proposed_cap,
        "weekly_ops_remaining_usd": float(ops.get("remaining_weekly_ops_usd") or 0.0),
        "weekly_ops_spent_usd": float(ops.get("estimated_spend_weekly_ops_usd_this_week") or 0.0),
        "rememo_daily_cap_unchanged": True,
        "replace_provisional": bool(replace_provisional),
        "existing_provisional": existing or None,
        "action": action,
        "note": (
            "Declared unused plan leftover (Cursor usage page). Cursor does not "
            "expose remaining credits to the API. --unused-usd is preferred when "
            "leftover exceeds listed plan_monthly_usd. Transfer is a provisional "
            "weekly_ops_cap raise only — rememo daily caps stay at 3. "
            "weekly_ops cannot exceed plan_credit_share_cap of plan_monthly_usd "
            "(default 15%) so included credit remains for development."
        ),
    }


def write_cycle_surplus(assessment: dict[str, Any], *, path: Path | None = None) -> Path:
    return write_json(path or DEFAULT_ARTIFACT_PATH, assessment)


def apply_cycle_surplus(
    assessment: dict[str, Any] | None = None,
    *,
    policy_path: Path | None = None,
    artifact_path: Path = DEFAULT_ARTIFACT_PATH,
    update_plan_metadata: bool = False,
    plan_name: str | None = None,
    replace_provisional: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write a provisional weekly_ops cap. Does not raise rememo caps."""
    if assessment is None:
        if not artifact_path.exists():
            raise FileNotFoundError(f"no surplus assessment at {artifact_path}")
        loaded = read_json(artifact_path)
        if not isinstance(loaded, dict):
            raise ValueError("cycle surplus artifact must be an object")
        assessment = loaded

    action = str(assessment.get("action") or "")
    replacing = bool(replace_provisional) or action == "replace_provisional"
    if action == "already_provisional" and not replacing:
        raise ValueError(
            "a provisional bump is already active; re-assess with "
            "--replace-provisional or review it before applying another"
        )
    if action == "none" or action not in APPLY_ACTIONS:
        raise ValueError("assessment has no weekly_ops change to apply")
    proposed = float(assessment["proposed_weekly_ops_cap_usd"])
    bump = float(assessment.get("weekly_bump_usd") or 0.0)

    policy = load_policy(policy_path)
    budget = normalize_budget(policy.get("budget"))
    now = now or datetime.now(UTC)
    existing = dict(budget.get("cycle_surplus_provisional") or {})
    previous = float(budget.get("weekly_ops_cap_usd") or 0.0)
    if replacing and existing.get("status") == "provisional":
        original = float(existing.get("previous_weekly_ops_cap_usd") or 0.0)
        if original > 0:
            previous = original
    share = float(
        assessment.get("plan_credit_share_cap")
        if assessment.get("plan_credit_share_cap") is not None
        else _resolved_plan_credit_share(share=None, budget=budget)
    )
    ceiling = float(
        assessment.get("plan_credit_ceiling_usd")
        if assessment.get("plan_credit_ceiling_usd") is not None
        else weekly_ops_plan_credit_ceiling_usd(
            float(assessment.get("plan_monthly_usd") or budget.get("plan_monthly_usd") or 0.0),
            share,
        )
    )
    if ceiling > 0:
        proposed = min(proposed, ceiling)
    provisional = {
        "status": "provisional",
        "previous_weekly_ops_cap_usd": previous,
        "applied_weekly_ops_cap_usd": proposed,
        "weekly_bump_usd": bump,
        "applied_at": now.isoformat(),
        "source_cycle_id": assessment.get("cycle_id"),
        "review_cycle_id": assessment.get("review_cycle_id"),
        "unused_fraction": assessment.get("unused_fraction"),
        "unused_monthly_usd": assessment.get("unused_monthly_usd"),
        "unused_usd_declared": assessment.get("unused_usd_declared"),
        "transfer_fraction": assessment.get("transfer_fraction"),
        "plan_monthly_usd": assessment.get("plan_monthly_usd"),
        "plan_credit_share_cap": share,
        "plan_credit_ceiling_usd": ceiling,
        "ceiling_bound": bool(assessment.get("ceiling_bound")),
        "replaced_prior_provisional": bool(replacing and existing.get("status") == "provisional"),
    }
    budget["weekly_ops_cap_usd"] = proposed
    budget["weekly_ops_plan_credit_share_cap"] = share
    budget["cycle_surplus_provisional"] = provisional
    if update_plan_metadata:
        if plan_name:
            budget["plan_name"] = plan_name
        if assessment.get("plan_monthly_usd") is not None:
            budget["plan_monthly_usd"] = float(assessment["plan_monthly_usd"])
    policy["budget"] = budget
    save_policy(policy, policy_path)

    spent = float(assessment.get("weekly_ops_spent_usd") or 0.0)
    applied = {
        **assessment,
        "action": "applied_provisional",
        "applied_at": now.isoformat(),
        "provisional": provisional,
        "current_weekly_ops_cap_usd": proposed,
        "proposed_weekly_ops_cap_usd": proposed,
        "weekly_ops_remaining_usd": max(0.0, round(proposed - spent, 2)),
    }
    write_cycle_surplus(applied, path=artifact_path)
    return applied


def review_cycle_surplus(
    *,
    keep: bool | None = None,
    policy_path: Path | None = None,
    artifact_path: Path = DEFAULT_ARTIFACT_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Recommend keep/revert; apply when ``keep`` is set."""
    policy = load_policy(policy_path)
    budget = normalize_budget(policy.get("budget"))
    ops = weekly_ops_budget_status(policy)
    now = now or datetime.now(UTC)
    refresh_day = int(budget.get("plan_refresh_day_of_month") or DEFAULT_PLAN_REFRESH_DAY)
    cycle_id = str(budget.get("cycle_id") or current_cycle_id(now=now, refresh_day=refresh_day))
    provisional = dict(budget.get("cycle_surplus_provisional") or {})

    if not provisional or provisional.get("status") not in {"provisional", "review_ready"}:
        result = {
            "action": "none",
            "reason": "no_provisional_bump",
            "cycle_id": cycle_id,
        }
        write_cycle_surplus({**_artifact_or_empty(artifact_path), **result}, path=artifact_path)
        return result

    review_cycle = str(provisional.get("review_cycle_id") or "")
    due = bool(review_cycle) and cycle_id >= review_cycle
    previous = float(provisional.get("previous_weekly_ops_cap_usd") or 0.0)
    share = _resolved_plan_credit_share(
        share=provisional.get("plan_credit_share_cap"),
        budget=budget,
    )
    monthly = float(provisional.get("plan_monthly_usd") or budget.get("plan_monthly_usd") or 0.0)
    ceiling = weekly_ops_plan_credit_ceiling_usd(monthly, share)
    revert_to = min(previous, ceiling) if ceiling > 0 else previous
    spent = float(ops.get("estimated_spend_weekly_ops_usd_this_week") or 0.0)
    used_extra = previous > 0 and spent > previous * 0.8
    recommend = "keep" if used_extra else "revert"

    result: dict[str, Any] = {
        "schema_version": 1,
        "reviewed_at": now.isoformat(),
        "cycle_id": cycle_id,
        "review_cycle_id": review_cycle,
        "review_due": due,
        "recommend": recommend,
        "used_extra_headroom": used_extra,
        "weekly_ops_spent_usd": spent,
        "previous_weekly_ops_cap_usd": previous,
        "revert_weekly_ops_cap_usd": revert_to,
        "plan_credit_share_cap": share,
        "plan_credit_ceiling_usd": ceiling,
        "current_weekly_ops_cap_usd": float(ops.get("weekly_ops_cap_usd") or 0.0),
        "provisional": provisional,
        "note": (
            "Keep if weekly_ops regularly used the extra room; revert if leftover "
            "stayed high. Revert still respects the plan-credit share ceiling. "
            "Human must pass --keep or --revert."
        ),
    }
    if keep is None:
        result["action"] = "recommend_only" if due else "too_early"
        write_cycle_surplus(result, path=artifact_path)
        return result
    if not due:
        result["action"] = "too_early"
        write_cycle_surplus(result, path=artifact_path)
        return result

    if keep:
        live = float(budget.get("weekly_ops_cap_usd") or 0.0)
        if ceiling > 0:
            budget["weekly_ops_cap_usd"] = min(live, ceiling)
        budget["weekly_ops_plan_credit_share_cap"] = share
        budget["cycle_surplus_provisional"] = {
            **provisional,
            "status": "kept",
            "reviewed_at": now.isoformat(),
            "review_decision": "keep",
        }
        result["action"] = "kept"
        result["current_weekly_ops_cap_usd"] = float(budget["weekly_ops_cap_usd"])
    else:
        budget["weekly_ops_cap_usd"] = revert_to
        budget["weekly_ops_plan_credit_share_cap"] = share
        budget["cycle_surplus_provisional"] = {
            **provisional,
            "status": "reverted",
            "reviewed_at": now.isoformat(),
            "review_decision": "revert",
            "reverted_to_usd": revert_to,
        }
        result["action"] = "reverted"
        result["current_weekly_ops_cap_usd"] = revert_to
    policy["budget"] = budget
    save_policy(policy, policy_path)
    write_cycle_surplus(result, path=artifact_path)
    return result


def _artifact_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}
