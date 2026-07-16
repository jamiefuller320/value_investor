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
DEFAULT_PLAN_MONTHLY_USD = 20.0  # Cursor Pro included API pool
DEFAULT_WEEKLY_BUDGET_FRACTION = 0.10
DEFAULT_PLAN_REFRESH_DAY = 8  # User billing cycle day-of-month
DEFAULT_FOCUS_MARKET = "sp500"
DEFAULT_MARKET_QUEUE = ["sp500", "euro_stoxx50", "asx200"]


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
            "maintenance_max_tickers": 15,
            "history": [],
            "note": (
                "Advance to next queue market when focus meets floors; "
                "graduated markets keep a light maintenance grow."
            ),
        },
        "research_model": pick.to_dict(),
        "budget": {
            "plan_monthly_usd": DEFAULT_PLAN_MONTHLY_USD,
            "weekly_library_fraction": DEFAULT_WEEKLY_BUDGET_FRACTION,
            "weekly_library_usd": round(
                DEFAULT_PLAN_MONTHLY_USD * DEFAULT_WEEKLY_BUDGET_FRACTION, 2
            ),
            "plan_refresh_day_of_month": DEFAULT_PLAN_REFRESH_DAY,
            "surplus_day_before_refresh": True,
            "estimated_spend_usd_this_cycle": 0.0,
            "estimated_spend_usd_this_week": 0.0,
            "week_id": None,
            "cycle_id": None,
            "note": (
                "Cursor does not expose remaining credits to this repo. "
                "Set plan_monthly_usd and plan_refresh_day_of_month to match your billing page. "
                "Spend is estimated from research runs."
            ),
        },
        "model_review": {
            "last_reviewed_at": None,
            "review_interval_days": 14,
            "history": [],
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
    for key in ("budget", "model_review", "focus_graduation"):
        merged = default_policy()[key]
        merged.update(dict(data.get(key) or {}))
        base[key] = merged
    if "ladder" in data or True:
        ladder = {
            "enabled": True,
            "layers": ["fundamentals", "screen_lite", "selective_research"],
            "min_metrics_for_screen": 25,
            "estimated_memo_usd": 0.4,
            "research_hard_cap": 5,
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


def save_policy(policy: dict[str, Any], path: Path | None = None) -> Path:
    path = path or DEFAULT_POLICY_PATH
    policy = dict(policy)
    policy["updated_at"] = datetime.now(UTC).isoformat()
    budget = dict(policy.get("budget") or {})
    monthly = float(budget.get("plan_monthly_usd") or DEFAULT_PLAN_MONTHLY_USD)
    frac = float(budget.get("weekly_library_fraction") or DEFAULT_WEEKLY_BUDGET_FRACTION)
    budget["plan_monthly_usd"] = monthly
    budget["weekly_library_fraction"] = frac
    budget["weekly_library_usd"] = round(monthly * frac, 2)
    policy["budget"] = budget
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


def weekly_budget_usd(policy: dict[str, Any] | None = None) -> float:
    policy = policy or load_policy()
    budget = policy.get("budget") or {}
    return float(budget.get("weekly_library_usd") or 0.0)


def remaining_weekly_budget_usd(policy: dict[str, Any] | None = None) -> float:
    policy = policy or load_policy()
    budget = policy.get("budget") or {}
    weekly = float(budget.get("weekly_library_usd") or 0.0)
    spent = float(budget.get("estimated_spend_usd_this_week") or 0.0)
    return max(0.0, round(weekly - spent, 4))


def research_model_id(policy: dict[str, Any] | None = None) -> str:
    policy = policy or load_policy()
    model = policy.get("research_model") or {}
    return str(model.get("model_id") or "composer-2.5")


def record_estimated_spend(
    amount_usd: float,
    path: Path | None = None,
) -> dict[str, Any]:
    """Accumulate estimated Cursor spend against weekly / cycle budgets."""
    policy = load_policy(path)
    budget = dict(policy.get("budget") or {})
    now = datetime.now(UTC)
    week_id = now.strftime("%G-W%V")
    cycle_day = int(budget.get("plan_refresh_day_of_month") or 1)
    cycle_id = f"{now.year}-{now.month:02d}-d{cycle_day}"
    if budget.get("week_id") != week_id:
        budget["week_id"] = week_id
        budget["estimated_spend_usd_this_week"] = 0.0
    if budget.get("cycle_id") != cycle_id:
        budget["cycle_id"] = cycle_id
        budget["estimated_spend_usd_this_cycle"] = 0.0
    budget["estimated_spend_usd_this_week"] = round(
        float(budget.get("estimated_spend_usd_this_week") or 0.0) + float(amount_usd), 4
    )
    budget["estimated_spend_usd_this_cycle"] = round(
        float(budget.get("estimated_spend_usd_this_cycle") or 0.0) + float(amount_usd), 4
    )
    policy["budget"] = budget
    save_policy(policy, path)
    return budget


def grow_ticker_budget(
    policy: dict[str, Any] | None = None,
    *,
    base_max_tickers: int = 40,
    surplus_max_tickers: int = 120,
    today: datetime | None = None,
) -> dict[str, Any]:
    """
    Translate plan budget policy into a fundamentals grow size for the focus market.

    Fundamentals grow is Yahoo-side (no Cursor credits). Cursor budget gates research
    separately; on surplus day we accelerate fundamentals to use spare capacity before
    refresh, and allow research spend up to remaining weekly + soft surplus headroom.
    """
    policy = policy or load_policy()
    budget = policy.get("budget") or {}
    refresh_day = int(budget.get("plan_refresh_day_of_month") or 1)
    surplus = bool(budget.get("surplus_day_before_refresh", True)) and is_surplus_spend_day(
        today, plan_refresh_day=refresh_day
    )
    weekly = weekly_budget_usd(policy)
    remaining = remaining_weekly_budget_usd(policy)
    max_tickers = surplus_max_tickers if surplus else base_max_tickers
    return {
        "focus_markets": focus_markets(policy),
        "max_tickers": max_tickers,
        "surplus_day": surplus,
        "weekly_library_usd": weekly,
        "remaining_weekly_usd": remaining,
        "research_model": research_model_id(policy),
        "allow_research": remaining > 0 or surplus,
        "research_budget_usd": round(remaining + (weekly if surplus else 0.0), 4),
    }
