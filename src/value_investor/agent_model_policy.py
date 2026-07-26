"""Select and periodically review the cheapest Cursor agent model for budget work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from value_investor.storage import read_json, write_json

# Approximate API list prices ($ / 1M tokens) from https://cursor.com/docs/models
# Used only for ranking; actual billing follows Cursor's current pools.
MODEL_API_RATES: dict[str, tuple[float, float]] = {
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5.1-codex-mini": (0.25, 2.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "composer-2.5": (0.50, 2.50),
    "gemini-3-flash": (0.50, 3.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.6-luna": (1.00, 6.00),
    "default": (1.25, 6.00),  # Auto flat rate
    "composer-2": (1.25, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gemini-3.5-flash": (1.50, 9.00),
    "kimi-k2.7-code": (0.95, 4.00),
    "glm-5.2": (1.40, 4.40),
    "grok-4.5": (2.00, 6.00),
}

# Draw from the generous first-party pool on individual plans (prefer for subscription budget).
FIRST_PARTY_MODEL_IDS = frozenset({"default", "composer-2.5", "grok-4.5"})

DEFAULT_POLICY_PATH = Path("docs/data/library/policy.json")
DEFAULT_PLAN_MONTHLY_USD = 20.0  # Cursor Pro subscription (included pool metadata)
DEFAULT_SPEND_CHECKPOINT_USD = 60.0
DEFAULT_WEEKLY_OPS_CAP_USD = 50.0
SPEND_POOL_WEEKLY_OPS = "weekly_ops"
SPEND_POOL_AD_HOC = "ad_hoc"
VALID_SPEND_POOLS = frozenset({SPEND_POOL_WEEKLY_OPS, SPEND_POOL_AD_HOC})
DEFAULT_PLAN_REFRESH_DAY = 8  # User billing cycle day-of-month
DEFAULT_FOCUS_MARKET = "sp500"
# Flag constraining when remaining weekly USD is below this share of the envelope.
NEAR_LIMIT_REMAINING_FRACTION = 0.20
# Index slices that map toward Trading 212 tradable coverage (offline).
# Live FTSE 350 screen is unchanged. Confirm tradability via t212-catalogue/t212-align.
DEFAULT_MARKET_QUEUE = [
    "sp500",
    "euro_stoxx50",
    "asx200",
    "ftse_smallcap",
    "nasdaq100",
    "dax",
    "cac40",
    "tsx60",
    # Graduated offline slices
    "aim",
    "ibex35",
    "ftse_mib",
    "aex",
    "bel20",
    "hang_seng",
    "sti",
    "us_adr_asia",
    # T212 venue-gap ladder
    "atx",
    "psi20",
    "smi",
    "omxs30",
    "iseq20",
]


@dataclass(frozen=True)
class ModelPick:
    model_id: str
    display_name: str
    input_per_m: float
    output_per_m: float
    pool: str  # "first_party" | "api"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "input_per_m_usd": self.input_per_m,
            "output_per_m_usd": self.output_per_m,
            "pool": self.pool,
            "reason": self.reason,
        }


def _rate_score(input_per_m: float, output_per_m: float) -> float:
    # Weight output a bit higher (research memos are generation-heavy).
    return input_per_m + 1.5 * output_per_m


def rank_models(available_ids: list[str] | None = None) -> list[ModelPick]:
    """Rank known models; if available_ids given, restrict to those present."""
    ids = list(available_ids) if available_ids is not None else list(MODEL_API_RATES)
    picks: list[ModelPick] = []
    for model_id in ids:
        rates = MODEL_API_RATES.get(model_id)
        if not rates:
            continue
        inp, out = rates
        pool = "first_party" if model_id in FIRST_PARTY_MODEL_IDS else "api"
        display = "Auto" if model_id == "default" else model_id
        if pool == "first_party":
            reason = "First-party pool (preferred for subscription budget)"
        else:
            reason = f"API pool ~${inp}/M in + ${out}/M out"
        picks.append(
            ModelPick(
                model_id=model_id,
                display_name=display,
                input_per_m=inp,
                output_per_m=out,
                pool=pool,
                reason=reason,
            )
        )

    def sort_key(p: ModelPick) -> tuple[int, float, str]:
        # Prefer first-party for plan efficiency, then lowest rate score.
        pool_rank = 0 if p.pool == "first_party" else 1
        # Within first-party, prefer composer-2.5 over Auto/Grok for lower token rates.
        return (pool_rank, _rate_score(p.input_per_m, p.output_per_m), p.model_id)

    return sorted(picks, key=sort_key)


def recommend_cheapest_model(available_ids: list[str] | None = None) -> ModelPick:
    ranked = rank_models(available_ids)
    if not ranked:
        return ModelPick(
            model_id="composer-2.5",
            display_name="composer-2.5",
            input_per_m=0.5,
            output_per_m=2.5,
            pool="first_party",
            reason="Fallback — no ranked models available",
        )
    return ranked[0]


def default_policy() -> dict[str, Any]:
    pick = recommend_cheapest_model()
    return {
        "schema_version": 1,
        "focus_market": DEFAULT_FOCUS_MARKET,
        "market_queue": list(DEFAULT_MARKET_QUEUE),
        "graduated_markets": [],
        "focus_graduation": {
            "min_coverage_pct": 0.95,
            "max_stale_pct": 0.15,
            "auto_advance": True,
            "maintenance_enabled": True,
            "maintenance_max_tickers": "full",
            "maintenance_include_focus_when_queue_complete": True,
            "maintenance_refresh_constituents": True,
            "history": [],
            "note": (
                "Advance to next queue market when focus meets floors; "
                "graduated markets get a full-universe maintenance refresh "
                "(set maintenance_max_tickers to an int to throttle later)."
            ),
        },
        "research_model": pick.to_dict(),
        "budget": {
            "plan_name": "Cursor Pro",
            "plan_monthly_usd": DEFAULT_PLAN_MONTHLY_USD,
            "plan_refresh_day_of_month": DEFAULT_PLAN_REFRESH_DAY,
            "surplus_day_before_refresh": True,
            "estimated_spend_usd_this_cycle": 0.0,
            "estimated_spend_usd_this_week": 0.0,
            "week_id": None,
            "cycle_id": None,
            "weekly_ops_cap_usd": DEFAULT_WEEKLY_OPS_CAP_USD,
            "enforce_weekly_ops_cap": True,
            "estimated_spend_weekly_ops_usd_this_week": 0.0,
            "note": (
                "Cursor subscription (plan_monthly_usd) is metadata only. "
                "weekly_ops_cap_usd ring-fences the orchestrator Sunday bundle "
                "(email report + ladder selective research). Ad-hoc depth passes "
                "use ladder.spend_since_checkpoint_usd. Spend is estimated from "
                "agent runs — Cursor does not expose remaining credits."
            ),
        },
        "model_review": {
            "last_reviewed_at": None,
            "review_interval_days": 14,
            "history": [],
        },
        "paper_fx": {
            "reporting_currency": "GBP",
            "hedge_assumption": "none",
            "rate_source": "yahoo_finance",
            "note": (
                "Paper NAV converts foreign marks into reporting_currency at spot. "
                "No FX hedging is assumed. Cash is treated as reporting_currency."
            ),
        },
        "macro_context": {
            "enabled": True,
            "refresh_on_ladder": True,
            "use_in_scoring": False,
            "note": (
                "Offline macro / regime markers for research memos and paper notes only. "
                "Never wire into quantitative scores or weights."
            ),
        },
        "updated_at": None,
    }


def load_policy(path: Path | None = None) -> dict[str, Any]:
    path = path or DEFAULT_POLICY_PATH
    if not path.exists():
        return default_policy()
    data = read_json(path)
    base = default_policy()
    base.update(data)
    # Ensure nested defaults
    for key in ("budget", "model_review", "focus_graduation", "paper_fx", "macro_context"):
        merged = default_policy()[key]
        file_section = dict(data.get(key) or {})
        merged.update(file_section)
        base[key] = merged
    base["budget"] = normalize_budget(base.get("budget"))
    if "ladder" in data or True:
        ladder = {
            "enabled": True,
            "layers": ["fundamentals", "screen_lite", "selective_research"],
            "min_metrics_for_screen": 25,
            "estimated_memo_usd": 0.4,
            "research_hard_cap": 50,
            # When True (default), research buy-tier shortlists across focus +
            # graduated markets — not only the focus market.
            "research_all_graduated": True,
            "last_run": None,
        }
        ladder.update(dict(data.get("ladder") or {}))
        base["ladder"] = ladder
    if not base.get("market_queue"):
        base["market_queue"] = list(DEFAULT_MARKET_QUEUE)
    if not base.get("focus_market"):
        base["focus_market"] = DEFAULT_FOCUS_MARKET
    if not isinstance(base.get("graduated_markets"), list):
        base["graduated_markets"] = list(data.get("graduated_markets") or [])
    return base


def normalize_budget(budget: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize budget fields for the two-pool spend model."""
    budget = dict(budget or {})
    monthly = float(budget.get("plan_monthly_usd") or DEFAULT_PLAN_MONTHLY_USD)
    budget["plan_monthly_usd"] = monthly
    cap = float(budget.get("weekly_ops_cap_usd") or DEFAULT_WEEKLY_OPS_CAP_USD)
    budget["weekly_ops_cap_usd"] = round(max(0.0, cap), 2)
    if "enforce_weekly_ops_cap" not in budget:
        budget["enforce_weekly_ops_cap"] = True
    budget["estimated_spend_weekly_ops_usd_this_week"] = round(
        float(budget.get("estimated_spend_weekly_ops_usd_this_week") or 0.0), 4
    )
    for legacy_key in (
        "allocation_basis",
        "weekly_usage_gbp",
        "gbp_usd_rate",
        "weekly_library_fraction",
        "weekly_library_usd",
        "enforce_weekly_research_cap",
    ):
        budget.pop(legacy_key, None)
    return budget


def save_policy(policy: dict[str, Any], path: Path | None = None) -> Path:
    path = path or DEFAULT_POLICY_PATH
    policy = dict(policy)
    policy["updated_at"] = datetime.now(UTC).isoformat()
    policy["budget"] = normalize_budget(policy.get("budget"))
    return write_json(path, policy, compact=False)


def review_model(
    path: Path | None = None,
    *,
    list_models_fn: Callable[[], list[str]] | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Re-rank models available to the key and persist the cheapest pick."""
    available: list[str] | None = None
    if list_models_fn is not None:
        available = list(list_models_fn())
    elif api_key:
        from value_investor.verify_key import verify_cursor_api_key

        result = verify_cursor_api_key(api_key, list_models=True)
        if result.ok and result.models:
            available = [m.id for m in result.models]

    pick = recommend_cheapest_model(available)
    policy = load_policy(path)
    previous = (policy.get("research_model") or {}).get("model_id")
    policy["research_model"] = pick.to_dict()
    review = dict(policy.get("model_review") or {})
    history = list(review.get("history") or [])
    history.append(
        {
            "reviewed_at": datetime.now(UTC).isoformat(),
            "model_id": pick.model_id,
            "previous_model_id": previous,
            "pool": pick.pool,
            "available_count": len(available) if available is not None else None,
        }
    )
    review["history"] = history[-20:]
    review["last_reviewed_at"] = datetime.now(UTC).isoformat()
    policy["model_review"] = review
    save_policy(policy, path)
    return {"pick": pick.to_dict(), "changed": previous != pick.model_id, "previous": previous}


def focus_markets(policy: dict[str, Any] | None = None) -> list[str]:
    policy = policy or load_policy()
    market = str(policy.get("focus_market") or DEFAULT_FOCUS_MARKET).strip()
    return [market] if market else [DEFAULT_FOCUS_MARKET]


def is_surplus_spend_day(
    today: datetime | None = None,
    *,
    plan_refresh_day: int = DEFAULT_PLAN_REFRESH_DAY,
) -> bool:
    """True on the calendar day immediately before plan_refresh_day_of_month."""
    today = today or datetime.now(UTC)
    day = today.day
    refresh = max(1, min(28, int(plan_refresh_day)))
    # Day before refresh (handle month wrap: refresh on 1 → surplus is last day of month)
    if refresh == 1:
        # Last day of current month
        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month = today.replace(month=today.month + 1, day=1)
        last_day = (next_month - timedelta(days=1)).day
        return day == last_day
    return day == refresh - 1


def weekly_ops_budget_status(
    policy: dict[str, Any] | None = None,
    *,
    estimated_memo_usd: float | None = None,
) -> dict[str, Any]:
    """Ring-fenced envelope for orchestrator weekly runs (email + ladder research)."""
    policy = policy or load_policy()
    budget = normalize_budget(policy.get("budget"))
    ladder = policy.get("ladder") or {}
    memo = float(
        estimated_memo_usd
        if estimated_memo_usd is not None
        else (ladder.get("estimated_memo_usd") or 0.4)
    )
    cap = float(budget.get("weekly_ops_cap_usd") or DEFAULT_WEEKLY_OPS_CAP_USD)
    spent_ops = float(budget.get("estimated_spend_weekly_ops_usd_this_week") or 0.0)
    spent_total = float(budget.get("estimated_spend_usd_this_week") or 0.0)
    remaining = max(0.0, round(cap - spent_ops, 4))
    enforce = bool(budget.get("enforce_weekly_ops_cap", True))
    constraining = bool(enforce and remaining < memo)
    near_limit = bool(enforce and cap > 0 and (remaining / cap) <= NEAR_LIMIT_REMAINING_FRACTION)
    return {
        "pool": SPEND_POOL_WEEKLY_OPS,
        "plan_monthly_usd": float(budget.get("plan_monthly_usd") or 0.0),
        "weekly_ops_cap_usd": cap,
        "estimated_spend_weekly_ops_usd_this_week": spent_ops,
        "estimated_spend_usd_this_week": spent_total,
        "remaining_weekly_ops_usd": remaining,
        "estimated_memo_usd": memo,
        "enforce_weekly_ops_cap": enforce,
        "constraining": constraining,
        "near_limit": near_limit,
        "flag": (
            "constraining"
            if constraining
            else ("near_limit" if near_limit else ("enforced" if enforce else "unconstrained"))
        ),
        "note": (
            "Weekly orchestrator envelope is constraining — raise weekly_ops_cap_usd, "
            "wait for week rollover, or set enforce_weekly_ops_cap=false."
            if constraining
            else (
                "Weekly orchestrator envelope nearly spent (≤20% remaining)."
                if near_limit
                else None
            )
        ),
    }


def research_model_id(policy: dict[str, Any] | None = None) -> str:
    policy = policy or load_policy()
    model = policy.get("research_model") or {}
    return str(model.get("model_id") or "composer-2.5")


def weekly_ops_cap_usd(policy: dict[str, Any] | None = None) -> float:
    policy = policy or load_policy()
    budget = normalize_budget(policy.get("budget"))
    return float(budget.get("weekly_ops_cap_usd") or DEFAULT_WEEKLY_OPS_CAP_USD)


def enforce_weekly_ops_cap(policy: dict[str, Any] | None = None) -> bool:
    policy = policy or load_policy()
    budget = policy.get("budget") or {}
    return bool(budget.get("enforce_weekly_ops_cap", True))


def remaining_weekly_ops_usd(policy: dict[str, Any] | None = None) -> float:
    policy = policy or load_policy()
    budget = normalize_budget(policy.get("budget"))
    cap = float(budget.get("weekly_ops_cap_usd") or DEFAULT_WEEKLY_OPS_CAP_USD)
    spent = float(budget.get("estimated_spend_weekly_ops_usd_this_week") or 0.0)
    return max(0.0, round(cap - spent, 4))


def _sync_week_rollover(budget: dict[str, Any]) -> None:
    now = datetime.now(UTC)
    week_id = now.strftime("%G-W%V")
    if budget.get("week_id") != week_id:
        budget["week_id"] = week_id
        budget["estimated_spend_usd_this_week"] = 0.0
        budget["estimated_spend_weekly_ops_usd_this_week"] = 0.0


def estimate_agent_spend_usd(agent_calls: int, *, memo_usd: float = 0.4) -> float:
    """Heuristic Cursor spend from a count of agent invocations."""
    return round(max(0, int(agent_calls)) * float(memo_usd), 4)


def record_email_run_spend(
    *,
    deep_analysis_ran: bool,
    research_created: int = 0,
    research_updated: int = 0,
    gap_fill_revisions: int = 0,
    post_run_review_ran: bool = False,
    memo_usd: float = 0.4,
    path: Path | None = None,
) -> dict[str, Any]:
    """Record estimated spend from a weekly email report run into weekly_ops."""
    calls = int(research_created) + int(research_updated) + int(gap_fill_revisions)
    if deep_analysis_ran:
        calls += 1
    if post_run_review_ran:
        calls += 1
    amount = estimate_agent_spend_usd(calls, memo_usd=memo_usd)
    if amount <= 0:
        return weekly_ops_budget_status(load_policy(path))
    record_estimated_spend(amount, path, pool=SPEND_POOL_WEEKLY_OPS)
    return weekly_ops_budget_status(load_policy(path))


def record_estimated_spend(
    amount_usd: float,
    path: Path | None = None,
    *,
    pool: str = SPEND_POOL_AD_HOC,
) -> dict[str, Any]:
    """Accumulate estimated Cursor spend against weekly / cycle budgets."""
    if pool not in VALID_SPEND_POOLS:
        raise ValueError(f"Unknown spend pool {pool!r}; expected one of {sorted(VALID_SPEND_POOLS)}")
    policy = load_policy(path)
    budget = dict(policy.get("budget") or {})
    now = datetime.now(UTC)
    cycle_day = int(budget.get("plan_refresh_day_of_month") or 1)
    cycle_id = f"{now.year}-{now.month:02d}-d{cycle_day}"
    _sync_week_rollover(budget)
    if budget.get("cycle_id") != cycle_id:
        budget["cycle_id"] = cycle_id
        budget["estimated_spend_usd_this_cycle"] = 0.0
    budget["estimated_spend_usd_this_week"] = round(
        float(budget.get("estimated_spend_usd_this_week") or 0.0) + float(amount_usd), 4
    )
    budget["estimated_spend_usd_this_cycle"] = round(
        float(budget.get("estimated_spend_usd_this_cycle") or 0.0) + float(amount_usd), 4
    )
    if pool == SPEND_POOL_WEEKLY_OPS:
        budget["estimated_spend_weekly_ops_usd_this_week"] = round(
            float(budget.get("estimated_spend_weekly_ops_usd_this_week") or 0.0)
            + float(amount_usd),
            4,
        )
    policy["budget"] = normalize_budget(budget)
    save_policy(policy, path)
    return normalize_budget(load_policy(path).get("budget"))


def spend_since_checkpoint_usd(policy: dict[str, Any] | None = None) -> float:
    """Estimated spend accumulated since the last approval checkpoint."""
    policy = policy or load_policy()
    ladder = policy.get("ladder") or {}
    return float(ladder.get("spend_since_checkpoint_usd") or 0.0)


def spend_checkpoint_usd(policy: dict[str, Any] | None = None) -> float:
    """Configured spend checkpoint size (default $60)."""
    policy = policy or load_policy()
    ladder = policy.get("ladder") or {}
    return float(ladder.get("spend_checkpoint_usd") or DEFAULT_SPEND_CHECKPOINT_USD)


def record_spend_with_checkpoint(
    amount_usd: float,
    path: Path | None = None,
    *,
    checkpoint_usd: float | None = None,
) -> dict[str, Any]:
    """
    Record estimated spend and return checkpoint status.

    When ``spend_since_checkpoint_usd`` reaches ``checkpoint_usd``, callers
    should pause and request human approval before continuing research.
    """
    policy = load_policy(path)
    budget = record_estimated_spend(amount_usd, path)
    policy = load_policy(path)
    ladder = dict(policy.get("ladder") or {})
    since = round(float(ladder.get("spend_since_checkpoint_usd") or 0.0) + float(amount_usd), 4)
    ladder["spend_since_checkpoint_usd"] = since
    limit = float(checkpoint_usd if checkpoint_usd is not None else spend_checkpoint_usd(policy))
    ladder["spend_checkpoint_usd"] = limit
    policy["ladder"] = ladder
    save_policy(policy, path)
    return {
        "budget": budget,
        "spend_since_checkpoint_usd": since,
        "spend_checkpoint_usd": limit,
        "checkpoint_reached": since >= limit,
        "remaining_until_checkpoint_usd": round(max(0.0, limit - since), 4),
    }


def approve_spend_checkpoint(path: Path | None = None) -> dict[str, Any]:
    """Reset spend-since-checkpoint after human approval to continue research."""
    policy = load_policy(path)
    ladder = dict(policy.get("ladder") or {})
    ladder["spend_since_checkpoint_usd"] = 0.0
    ladder["last_checkpoint_approved_at"] = datetime.now(UTC).isoformat()
    policy["ladder"] = ladder
    save_policy(policy, path)
    return {
        "spend_since_checkpoint_usd": 0.0,
        "spend_checkpoint_usd": spend_checkpoint_usd(policy),
        "approved_at": ladder["last_checkpoint_approved_at"],
    }


def grow_ticker_budget(
    policy: dict[str, Any] | None = None,
    *,
    base_max_tickers: int = 40,
    surplus_max_tickers: int = 120,
    today: datetime | None = None,
) -> dict[str, Any]:
    """
    Translate plan budget policy into a fundamentals grow size for the focus market.

    Fundamentals grow is Yahoo-side (no Cursor credits). Orchestrator selective
    research is capped by ``budget.weekly_ops_cap_usd``. On surplus day we
    accelerate fundamentals grow before the plan refresh.
    """
    policy = policy or load_policy()
    budget = normalize_budget(policy.get("budget"))
    refresh_day = int(budget.get("plan_refresh_day_of_month") or 1)
    surplus = bool(budget.get("surplus_day_before_refresh", True)) and is_surplus_spend_day(
        today, plan_refresh_day=refresh_day
    )
    max_tickers = surplus_max_tickers if surplus else base_max_tickers
    ops_status = weekly_ops_budget_status(policy)
    cap = float(ops_status["weekly_ops_cap_usd"])
    remaining = float(ops_status["remaining_weekly_ops_usd"])
    enforce = bool(ops_status["enforce_weekly_ops_cap"])
    return {
        "focus_markets": focus_markets(policy),
        "max_tickers": max_tickers,
        "surplus_day": surplus,
        "weekly_ops_cap_usd": cap,
        "remaining_weekly_ops_usd": remaining,
        "enforce_weekly_ops_cap": enforce,
        "constraining": ops_status["constraining"],
        "near_limit": ops_status["near_limit"],
        "budget_flag": ops_status["flag"],
        "research_model": research_model_id(policy),
        "allow_research": (not enforce) or remaining > 0 or surplus,
        "weekly_ops_research_budget_usd": (
            None
            if not enforce
            else round(remaining + (cap if surplus else 0.0), 4)
        ),
    }
