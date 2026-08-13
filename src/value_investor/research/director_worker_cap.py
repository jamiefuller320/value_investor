"""Weekly cap ledger and auto-tighten guard for director–worker runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from value_investor.agent_model_policy import load_policy, save_policy
from value_investor.storage import read_json, write_json

DEFAULT_DW_LEDGER_PATH = Path("docs/data/research_director_worker/ledger.json")

DEFAULT_DW_EXPLORATION_CAP = 15
DEFAULT_DW_STEADY_CAP = 5
DEFAULT_DW_AUTO_TIGHTEN_MIN_WEEKS = 8
DEFAULT_DW_AUTO_TIGHTEN_MAX_REESCALATION_RATE = 0.35

PHASE_EXPLORATION = "exploration"
PHASE_STEADY = "steady"


@dataclass(frozen=True)
class DirectorWorkerCapStatus:
    allowed: bool
    phase: str
    weekly_cap: int
    runs_this_week: int
    remaining: int
    is_reescalation: bool
    week_id: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "phase": self.phase,
            "weekly_cap": self.weekly_cap,
            "runs_this_week": self.runs_this_week,
            "remaining": self.remaining,
            "is_reescalation": self.is_reescalation,
            "week_id": self.week_id,
            "reason": self.reason,
        }


def default_director_worker_policy() -> dict[str, Any]:
    return {
        "phase": PHASE_EXPLORATION,
        "exploration_weekly_cap": DEFAULT_DW_EXPLORATION_CAP,
        "steady_weekly_cap": DEFAULT_DW_STEADY_CAP,
        "enforce_weekly_cap": True,
        "auto_tighten_enabled": True,
        "auto_tighten_min_weeks": DEFAULT_DW_AUTO_TIGHTEN_MIN_WEEKS,
        "auto_tighten_max_reescalation_rate": DEFAULT_DW_AUTO_TIGHTEN_MAX_REESCALATION_RATE,
        "note": (
            "Exploration phase allows a higher weekly director–worker cap while "
            "paper turnover is unknown; auto-tighten moves to steady cap when "
            "re-escalation rate stabilises over several weeks."
        ),
    }


def director_worker_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_policy()
    merged = default_director_worker_policy()
    merged.update(dict(policy.get("director_worker") or {}))
    return merged


def save_director_worker_policy(
    section: dict[str, Any],
    *,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    policy = load_policy(policy_path)
    current = director_worker_policy(policy)
    current.update(section)
    policy["director_worker"] = current
    save_policy(policy, policy_path)
    return current


def iso_week_id(when: datetime | None = None) -> str:
    when = when or datetime.now(UTC)
    year, week, _ = when.isocalendar()
    return f"{year}-W{week:02d}"


def default_ledger() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "weeks": {},
        "weekly_history": [],
        "tighten_history": [],
        "updated_at": None,
    }


def load_ledger(path: Path = DEFAULT_DW_LEDGER_PATH) -> dict[str, Any]:
    if not path.exists():
        return default_ledger()
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return default_ledger()
    base = default_ledger()
    base.update(payload)
    base.setdefault("weeks", {})
    base.setdefault("weekly_history", [])
    base.setdefault("tighten_history", [])
    return base


def save_ledger(ledger: dict[str, Any], path: Path = DEFAULT_DW_LEDGER_PATH) -> Path:
    ledger = dict(ledger)
    ledger["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    return write_json(path, ledger, compact=False)


def _prior_tickers(ledger: dict[str, Any]) -> set[str]:
    seen: set[str] = set()
    for week in (ledger.get("weeks") or {}).values():
        for row in week.get("runs") or []:
            ticker = str(row.get("ticker") or "").upper()
            if ticker:
                seen.add(ticker)
    return seen


def effective_weekly_cap(dw_policy: dict[str, Any]) -> int:
    phase = str(dw_policy.get("phase") or PHASE_EXPLORATION)
    if phase == PHASE_STEADY:
        return int(dw_policy.get("steady_weekly_cap") or DEFAULT_DW_STEADY_CAP)
    return int(dw_policy.get("exploration_weekly_cap") or DEFAULT_DW_EXPLORATION_CAP)


def _week_bucket(ledger: dict[str, Any], week_id: str) -> dict[str, Any]:
    weeks = ledger.setdefault("weeks", {})
    bucket = weeks.setdefault(
        week_id,
        {
            "runs": [],
            "unique_tickers": [],
            "reescalation_count": 0,
            "total_runs": 0,
        },
    )
    return bucket


def _rollup_week(ledger: dict[str, Any], week_id: str) -> dict[str, Any]:
    bucket = _week_bucket(ledger, week_id)
    runs = list(bucket.get("runs") or [])
    tickers = sorted({str(row.get("ticker") or "").upper() for row in runs if row.get("ticker")})
    reescalations = sum(1 for row in runs if row.get("is_reescalation"))
    summary = {
        "week_id": week_id,
        "unique_tickers": len(tickers),
        "reescalation_count": reescalations,
        "total_runs": len(runs),
        "reescalation_rate": round(reescalations / len(runs), 4) if runs else 0.0,
    }
    history = [row for row in ledger.get("weekly_history") or [] if row.get("week_id") != week_id]
    history.append(summary)
    history.sort(key=lambda row: str(row.get("week_id") or ""))
    ledger["weekly_history"] = history[-52:]
    bucket["unique_tickers"] = tickers
    bucket["reescalation_count"] = reescalations
    bucket["total_runs"] = len(runs)
    return summary


def check_director_worker_cap(
    ticker: str,
    *,
    policy_path: Path | None = None,
    ledger_path: Path = DEFAULT_DW_LEDGER_PATH,
    when: datetime | None = None,
) -> DirectorWorkerCapStatus:
    """Return whether a director–worker run is allowed under the weekly cap."""
    policy = load_policy(policy_path)
    dw_policy = director_worker_policy(policy)
    ledger = load_ledger(ledger_path)
    week_id = iso_week_id(when)
    cap = effective_weekly_cap(dw_policy)
    bucket = _week_bucket(ledger, week_id)
    runs_this_week = len(bucket.get("runs") or [])
    remaining = max(0, cap - runs_this_week)
    is_reescalation = ticker.upper() in _prior_tickers(ledger)
    enforce = bool(dw_policy.get("enforce_weekly_cap", True))

    if enforce and runs_this_week >= cap:
        return DirectorWorkerCapStatus(
            allowed=False,
            phase=str(dw_policy.get("phase") or PHASE_EXPLORATION),
            weekly_cap=cap,
            runs_this_week=runs_this_week,
            remaining=0,
            is_reescalation=is_reescalation,
            week_id=week_id,
            reason=(
                f"Weekly director–worker cap reached ({runs_this_week}/{cap} in {week_id}). "
                "Wait for next ISO week, raise the cap in policy, or pass --skip-dw-cap."
            ),
        )

    return DirectorWorkerCapStatus(
        allowed=True,
        phase=str(dw_policy.get("phase") or PHASE_EXPLORATION),
        weekly_cap=cap,
        runs_this_week=runs_this_week,
        remaining=remaining if enforce else cap,
        is_reescalation=is_reescalation,
        week_id=week_id,
    )


def record_director_worker_run(
    *,
    ticker: str,
    run_id: str,
    policy_path: Path | None = None,
    ledger_path: Path = DEFAULT_DW_LEDGER_PATH,
    when: datetime | None = None,
) -> dict[str, Any]:
    """Record a completed director–worker run and apply auto-tighten if warranted."""
    ledger = load_ledger(ledger_path)
    week_id = iso_week_id(when)
    is_reescalation = ticker.upper() in _prior_tickers(ledger)
    bucket = _week_bucket(ledger, week_id)
    bucket.setdefault("runs", []).append(
        {
            "ticker": ticker.upper(),
            "run_id": run_id,
            "is_reescalation": is_reescalation,
            "recorded_at": (when or datetime.now(UTC)).isoformat(),
        }
    )
    week_summary = _rollup_week(ledger, week_id)
    save_ledger(ledger, ledger_path)
    tighten = maybe_auto_tighten(policy_path=policy_path, ledger_path=ledger_path)
    return {
        "week_id": week_id,
        "is_reescalation": is_reescalation,
        "week_summary": week_summary,
        "auto_tighten": tighten,
    }


def maybe_auto_tighten(
    *,
    policy_path: Path | None = None,
    ledger_path: Path = DEFAULT_DW_LEDGER_PATH,
) -> dict[str, Any]:
    """Move from exploration to steady cap when weekly history stabilises."""
    policy = load_policy(policy_path)
    dw_policy = director_worker_policy(policy)
    if not bool(dw_policy.get("auto_tighten_enabled", True)):
        return {"applied": False, "reason": "auto_tighten_disabled"}
    if str(dw_policy.get("phase") or PHASE_EXPLORATION) != PHASE_EXPLORATION:
        return {"applied": False, "reason": "already_steady"}

    ledger = load_ledger(ledger_path)
    history = list(ledger.get("weekly_history") or [])
    min_weeks = int(dw_policy.get("auto_tighten_min_weeks") or DEFAULT_DW_AUTO_TIGHTEN_MIN_WEEKS)
    if len(history) < min_weeks:
        return {
            "applied": False,
            "reason": "insufficient_weeks",
            "weeks_recorded": len(history),
            "weeks_required": min_weeks,
        }

    recent = history[-min_weeks:]
    total_runs = sum(int(row.get("total_runs") or 0) for row in recent)
    if total_runs == 0:
        return {"applied": False, "reason": "no_runs_in_window"}

    reescalations = sum(int(row.get("reescalation_count") or 0) for row in recent)
    reescalation_rate = reescalations / total_runs
    max_rate = float(
        dw_policy.get("auto_tighten_max_reescalation_rate")
        or DEFAULT_DW_AUTO_TIGHTEN_MAX_REESCALATION_RATE
    )
    unique_counts = [int(row.get("unique_tickers") or 0) for row in recent]
    median_unique = float(median(unique_counts))

    if reescalation_rate > max_rate:
        return {
            "applied": False,
            "reason": "reescalation_rate_high",
            "reescalation_rate": round(reescalation_rate, 4),
            "max_rate": max_rate,
            "median_unique_tickers": median_unique,
        }

    steady_cap = int(dw_policy.get("steady_weekly_cap") or DEFAULT_DW_STEADY_CAP)
    updated = save_director_worker_policy(
        {"phase": PHASE_STEADY},
        policy_path=policy_path,
    )
    ledger.setdefault("tighten_history", []).append(
        {
            "applied_at": datetime.now(UTC).isoformat(),
            "from_phase": PHASE_EXPLORATION,
            "to_phase": PHASE_STEADY,
            "weeks_considered": min_weeks,
            "reescalation_rate": round(reescalation_rate, 4),
            "median_unique_tickers": median_unique,
            "steady_weekly_cap": steady_cap,
        }
    )
    save_ledger(ledger, ledger_path)
    return {
        "applied": True,
        "phase": updated.get("phase"),
        "steady_weekly_cap": steady_cap,
        "reescalation_rate": round(reescalation_rate, 4),
        "median_unique_tickers": median_unique,
    }


__all__ = [
    "DEFAULT_DW_AUTO_TIGHTEN_MAX_REESCALATION_RATE",
    "DEFAULT_DW_AUTO_TIGHTEN_MIN_WEEKS",
    "DEFAULT_DW_EXPLORATION_CAP",
    "DEFAULT_DW_LEDGER_PATH",
    "DEFAULT_DW_STEADY_CAP",
    "DirectorWorkerCapStatus",
    "check_director_worker_cap",
    "default_director_worker_policy",
    "director_worker_policy",
    "effective_weekly_cap",
    "iso_week_id",
    "load_ledger",
    "maybe_auto_tighten",
    "record_director_worker_run",
    "save_director_worker_policy",
]
