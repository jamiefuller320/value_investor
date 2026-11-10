"""Documented cold-store archive pack stage ladder + quiet-night auto-widen.

Extends the runbook stage table (pilot → thin → moderate → thick) with a
committed quiet ``isolation_ok`` streak. After ``QUIET_NIGHTS_REQUIRED`` clean
apply nights at the current stage, promote **one** documented step (hard ceiling
at stage 3). Isolation / suspend / shared-path failures fail-closed and reset
the streak — they do **not** invent stages past the ladder or eng-spray.

Persisted on ``universe_filing_archive_status.json`` → ``stage_ladder``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json

SCHEMA_VERSION = 1

# Documented ladder — do not invent stages past MAX_DOCUMENTED_STAGE.
ARCHIVE_STAGE_LADDER: tuple[dict[str, Any], ...] = (
    {
        "stage": 0,
        "name": "pilot",
        "max_units": 2,
        "max_http_fetches": 8,
        "max_tickers_per_unit": 2,
        "max_bodies_per_ticker": 1,
    },
    {
        "stage": 1,
        "name": "thin",
        "max_units": 4,
        "max_http_fetches": 16,
        "max_tickers_per_unit": 2,
        "max_bodies_per_ticker": 1,
    },
    {
        "stage": 2,
        "name": "moderate",
        "max_units": 8,
        "max_http_fetches": 32,
        "max_tickers_per_unit": 2,
        "max_bodies_per_ticker": 1,
    },
    {
        "stage": 3,
        "name": "thick",
        "max_units": 16,
        "max_http_fetches": 64,
        "max_tickers_per_unit": 2,
        "max_bodies_per_ticker": 1,
    },
)

MAX_DOCUMENTED_STAGE = 3
# Default pace / post-stage-2 runbook: 5 quiet isolation_ok apply nights.
QUIET_NIGHTS_REQUIRED = 5
# Shipped floor after #1351 (stage-2 moderate quiet).
DEFAULT_STAGE = 2

FINDING_TITLE_AUTO_WIDEN = "Cold-store archive pack auto-widened"
FINDING_TITLE_AT_CEILING = "Cold-store archive pack at max documented stage"
# Ops-monitor surfaces a recent promote for one quiet cycle (~36h like bottleneck stale).
AUTO_WIDEN_FINDING_HOURS = 36.0

RUNBOOK = "docs/ops/universe-filing-archive-pack.md"


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _safe_read(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_dt(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def stage_row(stage: int) -> dict[str, Any]:
    """Return a copy of the ladder row for ``stage`` (clamped to documented max)."""
    sid = max(0, min(int(stage), MAX_DOCUMENTED_STAGE))
    for row in ARCHIVE_STAGE_LADDER:
        if int(row["stage"]) == sid:
            return dict(row)
    return dict(ARCHIVE_STAGE_LADDER[DEFAULT_STAGE])


def caps_for_stage(stage: int) -> dict[str, int]:
    row = stage_row(stage)
    return {
        "max_units": int(row["max_units"]),
        "max_http_fetches": int(row["max_http_fetches"]),
        "max_tickers_per_unit": int(row["max_tickers_per_unit"]),
        "max_bodies_per_ticker": int(row["max_bodies_per_ticker"]),
    }


def infer_stage_from_caps(
    *,
    max_units: Any = None,
    max_http_fetches: Any = None,
) -> int | None:
    """Match caps to a documented stage, or None if they do not fit the ladder."""
    try:
        units = int(max_units) if max_units is not None else None
        fetches = int(max_http_fetches) if max_http_fetches is not None else None
    except (TypeError, ValueError):
        return None
    if units is None and fetches is None:
        return None
    for row in ARCHIVE_STAGE_LADDER:
        u_ok = units is None or int(row["max_units"]) == units
        f_ok = fetches is None or int(row["max_http_fetches"]) == fetches
        if u_ok and f_ok:
            return int(row["stage"])
    return None


def _extract_stage_ladder(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept a full status blob or a bare ``stage_ladder`` dict."""
    nested = _as_dict(payload.get("stage_ladder"))
    if nested:
        return nested
    # Bare ladder (e.g. advance() chaining its own return value).
    if "current_stage" in payload or "quiet_isolation_ok_streak" in payload:
        return dict(payload)
    return {}


def load_stage_ladder_state(
    *,
    status_path: Path | None = None,
    status: dict[str, Any] | None = None,
    pack_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load committed stage/streak state, seeding from status or last pack caps."""
    payload = status if status is not None else (
        _safe_read(Path(status_path)) if status_path is not None else {}
    )
    prior = _extract_stage_ladder(_as_dict(payload))
    stage = prior.get("current_stage")
    if stage is None:
        caps = _as_dict(payload.get("current_caps"))
        stage = infer_stage_from_caps(
            max_units=caps.get("max_units"),
            max_http_fetches=caps.get("max_http_fetches"),
        )
    if stage is None and pack_run is not None:
        run = _as_dict(pack_run)
        assemble = _as_dict(run.get("assemble_caps"))
        stage = infer_stage_from_caps(
            max_units=run.get("max_units"),
            max_http_fetches=assemble.get("max_http_fetches") or run.get("max_http_fetches"),
        )
    if stage is None:
        stage = DEFAULT_STAGE
    stage = max(0, min(int(stage), MAX_DOCUMENTED_STAGE))
    streak = int(prior.get("quiet_isolation_ok_streak") or 0)
    if streak < 0:
        streak = 0
    caps = caps_for_stage(stage)
    next_stage = stage + 1 if stage < MAX_DOCUMENTED_STAGE else None
    return {
        "schema_version": SCHEMA_VERSION,
        "current_stage": stage,
        "stage_name": stage_row(stage)["name"],
        "max_documented_stage": MAX_DOCUMENTED_STAGE,
        "at_ceiling": stage >= MAX_DOCUMENTED_STAGE,
        "quiet_isolation_ok_streak": streak,
        "required_streak": QUIET_NIGHTS_REQUIRED,
        "auto_widen_enabled": True,
        "current_caps": caps,
        "next_stage": next_stage,
        "next_stage_caps": caps_for_stage(next_stage) if next_stage is not None else None,
        "last_clean_run_id": prior.get("last_clean_run_id"),
        "last_reset_reason": prior.get("last_reset_reason"),
        "last_auto_widen": prior.get("last_auto_widen"),
        "runbook": RUNBOOK,
    }


def resolve_apply_caps(
    *,
    max_units: int | None = None,
    max_http_fetches: int | None = None,
    status_path: Path | None = None,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve effective apply caps.

    Explicit CLI/workflow overrides win. Otherwise use the committed stage
    ladder (fail-closed to ``DEFAULT_STAGE`` when status is missing).
    """
    state = load_stage_ladder_state(status_path=status_path, status=status)
    caps = dict(state["current_caps"])
    override_units = max_units is not None
    override_fetches = max_http_fetches is not None
    if override_units:
        caps["max_units"] = int(max_units)
    if override_fetches:
        caps["max_http_fetches"] = int(max_http_fetches)
    inferred = infer_stage_from_caps(
        max_units=caps["max_units"],
        max_http_fetches=caps["max_http_fetches"],
    )
    return {
        "max_units": int(caps["max_units"]),
        "max_http_fetches": int(caps["max_http_fetches"]),
        "max_tickers_per_unit": int(caps["max_tickers_per_unit"]),
        "max_bodies_per_ticker": int(caps["max_bodies_per_ticker"]),
        "stage": inferred if inferred is not None else state["current_stage"],
        "from_stage_ladder": not (override_units or override_fetches),
        "override_units": override_units,
        "override_fetches": override_fetches,
        "stage_ladder": state,
    }


def classify_quiet_night(
    *,
    outcome: str,
    dry_run: bool,
    isolation: dict[str, Any] | None = None,
    errors: list[Any] | None = None,
    fourth_equal_sprint_stream: bool | None = None,
) -> tuple[str, str]:
    """Return ``(verdict, reason)`` for streak accounting.

    verdict: ``clean`` | ``reset`` | ``ignore``
    """
    key = str(outcome or "").strip().lower()
    iso = isolation if isinstance(isolation, dict) else {}
    err_list = [str(e) for e in (errors or []) if str(e).strip()]

    if key in {"suspend", "quiet_only"}:
        return "reset", f"outcome={key}"
    if key == "error" or err_list:
        return "reset", "errors" if err_list else "outcome=error"
    if dry_run or key == "dry_complete":
        return "ignore", "dry_run"
    if key != "apply_complete":
        return "reset", f"outcome={key or 'unknown'}"

    if iso.get("isolation_ok") is False:
        return "reset", "isolation_ok=false"
    if bool(iso.get("shared_critical_path")):
        return "reset", "shared_critical_path"
    fourth = fourth_equal_sprint_stream
    if fourth is None:
        fourth = bool(iso.get("fourth_equal_sprint_stream"))
    if fourth:
        return "reset", "fourth_equal_sprint_stream"
    if iso.get("isolation_ok") is not True:
        return "reset", "isolation_ok_missing"

    return "clean", "apply_complete_isolation_ok"


def advance_stage_ladder(
    prior: dict[str, Any] | None,
    *,
    outcome: str,
    dry_run: bool,
    isolation: dict[str, Any] | None = None,
    errors: list[Any] | None = None,
    fourth_equal_sprint_stream: bool | None = None,
    run_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Update streak / promote one documented stage when the quiet gate is met."""
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    else:
        clock = clock.astimezone(UTC)

    base = load_stage_ladder_state(status=prior or {})
    stage = int(base["current_stage"])
    streak = int(base["quiet_isolation_ok_streak"])
    last_auto = base.get("last_auto_widen")
    last_clean = base.get("last_clean_run_id")
    last_reset = base.get("last_reset_reason")
    promoted = False
    promote_from: int | None = None
    promote_to: int | None = None

    verdict, reason = classify_quiet_night(
        outcome=outcome,
        dry_run=dry_run,
        isolation=isolation,
        errors=errors,
        fourth_equal_sprint_stream=fourth_equal_sprint_stream,
    )

    if verdict == "reset":
        streak = 0
        last_reset = reason
    elif verdict == "clean":
        # Idempotent: same run_id must not double-count.
        if run_id and run_id == last_clean:
            pass
        else:
            streak += 1
            last_clean = run_id
            last_reset = None
            if streak >= QUIET_NIGHTS_REQUIRED and stage < MAX_DOCUMENTED_STAGE:
                promote_from = stage
                stage = stage + 1
                promote_to = stage
                streak = 0
                promoted = True
                last_auto = {
                    "at": clock.isoformat(),
                    "from_stage": promote_from,
                    "to_stage": promote_to,
                    "from_caps": caps_for_stage(promote_from),
                    "to_caps": caps_for_stage(promote_to),
                    "run_id": run_id,
                    "required_streak": QUIET_NIGHTS_REQUIRED,
                    "reason": "quiet_isolation_ok_streak_met",
                }

    caps = caps_for_stage(stage)
    next_stage = stage + 1 if stage < MAX_DOCUMENTED_STAGE else None
    return {
        "schema_version": SCHEMA_VERSION,
        "current_stage": stage,
        "stage_name": stage_row(stage)["name"],
        "max_documented_stage": MAX_DOCUMENTED_STAGE,
        "at_ceiling": stage >= MAX_DOCUMENTED_STAGE,
        "quiet_isolation_ok_streak": streak,
        "required_streak": QUIET_NIGHTS_REQUIRED,
        "auto_widen_enabled": True,
        "current_caps": caps,
        "next_stage": next_stage,
        "next_stage_caps": caps_for_stage(next_stage) if next_stage is not None else None,
        "last_clean_run_id": last_clean,
        "last_reset_reason": last_reset,
        "last_auto_widen": last_auto,
        "last_verdict": verdict,
        "last_verdict_reason": reason,
        "promoted": promoted,
        "runbook": RUNBOOK,
        "updated_at": clock.isoformat(),
    }


def ops_finding_from_stage_ladder(
    stage_ladder: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    finding_hours: float = AUTO_WIDEN_FINDING_HOURS,
) -> dict[str, Any] | None:
    """Info finding when a recent auto-widen fired (observe-only; no eng-spray)."""
    state = _as_dict(stage_ladder)
    event = _as_dict(state.get("last_auto_widen"))
    if not event:
        return None
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    else:
        clock = clock.astimezone(UTC)
    at = _parse_dt(event.get("at"))
    if at is None:
        return None
    age_h = (clock - at).total_seconds() / 3600.0
    if age_h < 0 or age_h > float(finding_hours):
        return None
    from_stage = event.get("from_stage")
    to_stage = event.get("to_stage")
    to_caps = _as_dict(event.get("to_caps"))
    return {
        "severity": "info",
        "category": "ingest",
        "title": FINDING_TITLE_AUTO_WIDEN,
        "summary": (
            f"Quiet isolation_ok streak met ({event.get('required_streak') or QUIET_NIGHTS_REQUIRED} "
            f"nights); auto-widened cold-store archive pack stage {from_stage}→{to_stage} "
            f"(max_units={to_caps.get('max_units')}, "
            f"max_http_fetches={to_caps.get('max_http_fetches')}). "
            f"Hard ceiling remains stage {MAX_DOCUMENTED_STAGE}. "
            "Observe-only notice — N180/N181 still parked; no fourth sprint / eng-spray."
        ),
        "auto_fixable": False,
        "stage_ladder": {
            "from_stage": from_stage,
            "to_stage": to_stage,
            "at": event.get("at"),
            "run_id": event.get("run_id"),
        },
    }


__all__ = [
    "ARCHIVE_STAGE_LADDER",
    "AUTO_WIDEN_FINDING_HOURS",
    "DEFAULT_STAGE",
    "FINDING_TITLE_AT_CEILING",
    "FINDING_TITLE_AUTO_WIDEN",
    "MAX_DOCUMENTED_STAGE",
    "QUIET_NIGHTS_REQUIRED",
    "RUNBOOK",
    "SCHEMA_VERSION",
    "advance_stage_ladder",
    "caps_for_stage",
    "classify_quiet_night",
    "infer_stage_from_caps",
    "load_stage_ladder_state",
    "ops_finding_from_stage_ladder",
    "resolve_apply_caps",
    "stage_row",
]
