"""Focus-market graduation and maintenance grow for offline libraries."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import load_policy, save_policy
from value_investor.data_library import DEFAULT_STALE_DAYS, grow_library, library_status

DEFAULT_MIN_COVERAGE_PCT = 0.95
DEFAULT_MAX_STALE_PCT = 0.15
# Build-phase default: refresh every constituent each maintenance pass.
# Set an int (e.g. 100) later to throttle; rating-priority refresh is deferred (L33).
DEFAULT_MAINTENANCE_MAX_TICKERS: int | str = "full"
FULL_MAINTENANCE_FALLBACK_TICKERS = 10_000


def _is_full_maintenance_cap(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in {"full", "all", "*"}:
        return True
    if isinstance(value, (int, float)) and int(value) <= 0:
        return True
    return False


def resolve_maintenance_max_tickers(
    cfg: dict[str, Any],
    *,
    root: Path | None = None,
    markets: list[str] | None = None,
) -> tuple[int, bool]:
    """
    Return ``(max_tickers, is_full)``.

    ``"full"`` / null / ≤0 means refresh every constituent (cap derived from
    library ticker counts when available).
    """
    raw = cfg.get("maintenance_max_tickers", DEFAULT_MAINTENANCE_MAX_TICKERS)
    if not _is_full_maintenance_cap(raw):
        return max(1, int(raw)), False
    cap = FULL_MAINTENANCE_FALLBACK_TICKERS
    if root is not None and markets:
        status = library_status(root, markets=markets)
        counts = [int(row.get("ticker_count") or 0) for row in status]
        if counts and max(counts) > 0:
            cap = max(counts)
    return cap, True


def _graduation_config(policy: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(policy.get("focus_graduation") or {})
    cfg.setdefault("min_coverage_pct", DEFAULT_MIN_COVERAGE_PCT)
    cfg.setdefault("max_stale_pct", DEFAULT_MAX_STALE_PCT)
    cfg.setdefault("auto_advance", True)
    cfg.setdefault("maintenance_enabled", True)
    cfg.setdefault("maintenance_max_tickers", DEFAULT_MAINTENANCE_MAX_TICKERS)
    # Once the queue is finished, refresh every graduated market (including focus).
    cfg.setdefault("maintenance_include_focus_when_queue_complete", True)
    cfg.setdefault("maintenance_refresh_constituents", True)
    cfg.setdefault(
        "note",
        "Advance to next queue market only when focus meets these floors; "
        "graduated markets keep a full-universe maintenance refresh by default "
        "(set maintenance_max_tickers to an int to throttle later).",
    )
    return cfg


def stale_pct_from_status(row: dict[str, Any]) -> float:
    """Fraction of covered tickers whose metrics are stale (0–1)."""
    covered = int(row.get("coverage_count") or 0)
    if covered <= 0:
        return 1.0
    stale = int(row.get("stale") or 0)
    return round(stale / covered, 4)


def market_meets_graduation(
    status_row: dict[str, Any],
    *,
    min_coverage_pct: float = DEFAULT_MIN_COVERAGE_PCT,
    max_stale_pct: float = DEFAULT_MAX_STALE_PCT,
) -> bool:
    """True when coverage and freshness floors are met."""
    ticker_count = int(status_row.get("ticker_count") or 0)
    if ticker_count <= 0:
        return False
    coverage_pct = float(status_row.get("coverage_pct") or 0.0)
    if coverage_pct < float(min_coverage_pct):
        return False
    return stale_pct_from_status(status_row) <= float(max_stale_pct)


def graduated_market_ids(policy: dict[str, Any]) -> list[str]:
    rows = policy.get("graduated_markets") or []
    out: list[str] = []
    for row in rows:
        if isinstance(row, str):
            out.append(row)
        elif isinstance(row, dict) and row.get("market"):
            out.append(str(row["market"]))
    return out


def next_focus_market(policy: dict[str, Any]) -> str | None:
    """Next queue market that is not the current focus and not already graduated."""
    queue = list(policy.get("market_queue") or [])
    focus = str(policy.get("focus_market") or "")
    done = set(graduated_market_ids(policy))
    done.add(focus)
    for market in queue:
        if market not in done:
            return market
    return None


def evaluate_graduation(
    root: Path,
    policy: dict[str, Any],
    *,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> dict[str, Any]:
    """
    Inspect focus-market status against graduation floors (does not mutate policy).
    """
    cfg = _graduation_config(policy)
    focus = str(policy.get("focus_market") or "")
    status_rows = library_status(root, markets=[focus], stale_days=stale_days) if focus else []
    row = status_rows[0] if status_rows else {}
    stale_pct = stale_pct_from_status(row) if row else 1.0
    meets = bool(row) and market_meets_graduation(
        row,
        min_coverage_pct=float(cfg["min_coverage_pct"]),
        max_stale_pct=float(cfg["max_stale_pct"]),
    )
    nxt = next_focus_market(policy) if meets else None
    return {
        "focus_market": focus,
        "meets_floors": meets,
        "auto_advance": bool(cfg.get("auto_advance", True)),
        "coverage_pct": float(row.get("coverage_pct") or 0.0),
        "stale_pct": stale_pct,
        "min_coverage_pct": float(cfg["min_coverage_pct"]),
        "max_stale_pct": float(cfg["max_stale_pct"]),
        "next_focus": nxt,
        "status": row,
        "can_advance": bool(meets and cfg.get("auto_advance", True) and nxt),
        "queue_complete": bool(meets and nxt is None),
    }


def apply_graduation(
    policy: dict[str, Any],
    evaluation: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Advance focus_market when evaluation says we can. Returns (policy, event).
    """
    now = now or datetime.now(UTC)
    event: dict[str, Any] = {
        "graduated": False,
        "from_market": evaluation.get("focus_market"),
        "to_market": None,
        "reason": None,
    }
    if not evaluation.get("meets_floors"):
        event["reason"] = "floors_not_met"
        return policy, event
    if not evaluation.get("auto_advance"):
        event["reason"] = "auto_advance_disabled"
        return policy, event

    focus = str(evaluation.get("focus_market") or "")
    already = graduated_market_ids(policy)
    graduated = list(policy.get("graduated_markets") or [])
    if focus and focus not in already:
        graduated.append(
            {
                "market": focus,
                "graduated_at": now.isoformat(),
                "coverage_pct": evaluation.get("coverage_pct"),
                "stale_pct": evaluation.get("stale_pct"),
            }
        )
        policy["graduated_markets"] = graduated
        event["graduated"] = True

    nxt = evaluation.get("next_focus")
    if nxt:
        policy["focus_market"] = nxt
        event["to_market"] = nxt
        event["reason"] = "advanced"
    else:
        event["reason"] = "queue_complete"
        # Keep focus on the graduated market; only maintenance remains.
    history = list((policy.get("focus_graduation") or {}).get("history") or [])
    history.append(
        {
            "at": now.isoformat(),
            "from_market": focus,
            "to_market": nxt,
            "coverage_pct": evaluation.get("coverage_pct"),
            "stale_pct": evaluation.get("stale_pct"),
            "reason": event["reason"],
        }
    )
    fg = _graduation_config(policy)
    fg["history"] = history[-30:]
    policy["focus_graduation"] = fg
    return policy, event


def maybe_graduate_focus(
    root: Path,
    policy_path: Path,
    *,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> dict[str, Any]:
    """Load policy, evaluate focus, advance if floors met, persist."""
    policy = load_policy(policy_path)
    evaluation = evaluate_graduation(root, policy, stale_days=stale_days)
    focus = str(evaluation.get("focus_market") or "")
    already = focus in graduated_market_ids(policy)
    should_apply = bool(
        evaluation.get("meets_floors")
        and evaluation.get("auto_advance")
        and (evaluation.get("can_advance") or (evaluation.get("queue_complete") and not already))
    )
    if should_apply:
        policy, event = apply_graduation(policy, evaluation)
        save_policy(policy, policy_path)
        return {
            "evaluation": evaluation,
            "event": event,
            "policy_focus": policy.get("focus_market"),
        }

    if not evaluation.get("meets_floors"):
        reason = "floors_not_met"
    elif not evaluation.get("auto_advance"):
        reason = "auto_advance_disabled"
    elif already:
        reason = "already_graduated"
    else:
        reason = "no_action"
    return {
        "evaluation": evaluation,
        "event": {
            "graduated": False,
            "from_market": focus,
            "to_market": None,
            "reason": reason,
        },
        "policy_focus": policy.get("focus_market"),
    }


def run_maintenance_grow(
    root: Path,
    policy: dict[str, Any],
    *,
    stale_days: int = DEFAULT_STALE_DAYS,
    refresh_constituents_first: bool | None = None,
) -> dict[str, Any]:
    """
    Progressive refresh for graduated markets (stale-first via grow_library).

    While the queue still has a next focus market, skips the current focus so the
    main ladder grow is not diluted. When the queue is complete, refreshes every
    graduated market (including focus). Default cap is ``"full"`` (every
    constituent); set an int on ``maintenance_max_tickers`` to throttle later.
    """
    cfg = _graduation_config(policy)
    if not cfg.get("maintenance_enabled", True):
        return {"skipped": True, "reason": "maintenance_disabled", "markets": []}

    focus = str(policy.get("focus_market") or "")
    graduated = [m for m in graduated_market_ids(policy) if m]
    queue_complete = bool(graduated) and next_focus_market(policy) is None
    include_focus = bool(cfg.get("maintenance_include_focus_when_queue_complete", True))
    if queue_complete and include_focus:
        markets = graduated
    else:
        markets = [m for m in graduated if m != focus]
    if not markets:
        return {"skipped": True, "reason": "no_graduated_markets", "markets": []}

    max_tickers, is_full = resolve_maintenance_max_tickers(
        cfg, root=root, markets=markets
    )
    if refresh_constituents_first is None:
        refresh_constituents_first = bool(cfg.get("maintenance_refresh_constituents", True))
    results = grow_library(
        root,
        markets=markets,
        max_tickers_per_run=max_tickers,
        stale_days=stale_days,
        refresh_constituents_first=refresh_constituents_first,
    )
    status = library_status(root, markets=markets, stale_days=stale_days)
    return {
        "skipped": False,
        "markets": markets,
        "max_tickers": max_tickers,
        "maintenance_full_refresh": is_full,
        "queue_complete": queue_complete,
        "include_focus": bool(queue_complete and include_focus),
        "refresh_constituents_first": bool(refresh_constituents_first),
        "grew": results,
        "status": status,
    }
