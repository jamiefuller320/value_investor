"""P2 ingest effort cascade: priority slot on the learning-phase head, spare on the tail.

Doctrine: while ``head_needs_fat_slot`` is true the focus market still has
priority on the shared filing host. The priority slot uses the same width rule
as a spare: ``min(unfilled names, host budget left, names that fit in the time
left)`` for that kind, then the existing job ceiling. One unfilled name
reserves one name. The unused part of the old fixed sprint cap is not reserved.
Nothing unfilled means width 0. ``head_needs_fat_slot`` stays the release bit
(false at parity). Spare width is not a fixed 50%/25% cut, and spares subtract
``head_unfilled`` only. When the head bit is false, spares are not held to
those fractions. The priority slot is an ingest-head rule, not a boss over
non-ingest strands.

Runtime wait / leftover / fill-down lives in ``library_ingest_scheduler``.
This module is the static policy (dynamic width, hour-skip fallback, release gate).
``stream_*_fraction`` fields remain on the policy object so older JSON still
loads; they are not applied.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

DEFAULT_STREAM_1_TARGET_FRACTION = 0.5
DEFAULT_STREAM_1_RUNTIME_FRACTION = 0.5
DEFAULT_STREAM_2_TARGET_FRACTION = 0.25
DEFAULT_STREAM_2_RUNTIME_FRACTION = 0.25
# Legacy fraction fields stay loadable. Width no longer multiplies by them.
KIND_FILING_BODY = "filing_body"
KIND_DAILY_PRICE = "daily_price"
KIND_MEMO = "memo"
# Planning seconds for one name on this job's clock. Filing matches the spare
# slot shape (24 names in 2100s). Daily prices and memos are cheaper kinds.
KIND_SECONDS_PER_NAME: dict[str, float] = {
    KIND_FILING_BODY: 87.5,
    KIND_DAILY_PRICE: 5.0,
    KIND_MEMO: 60.0,
}
# Stream 2 crons are focus+60m. Peak euro slots are 07:15 / 10:15; stream 2 is 08:15 / 11:15.
DEFAULT_STREAM_2_YIELD_HOURS_UTC: tuple[int, ...] = (8, 11)
MIN_SPARE_TARGETS = 1
MIN_SPARE_RUNTIME_SECONDS = 60.0
HEAD_RELEASE_INGEST_PARITY = "ingest_parity"
HEAD_RELEASE_PHASE2 = "phase2_ready"
DEFAULT_HEAD_RELEASE_WHEN = HEAD_RELEASE_INGEST_PARITY
DEFAULT_LEFTOVER_MAX_AGE_SECONDS = 4 * 3600.0
DEFAULT_SPARE_WAIT_SECONDS = 2400.0
DEFAULT_MIN_LEFTOVER_SECONDS = 180.0


@dataclass(frozen=True)
class IngestCascadeConfig:
    enabled: bool = True
    stream_1_target_fraction: float = DEFAULT_STREAM_1_TARGET_FRACTION
    stream_1_runtime_fraction: float = DEFAULT_STREAM_1_RUNTIME_FRACTION
    stream_2_target_fraction: float = DEFAULT_STREAM_2_TARGET_FRACTION
    stream_2_runtime_fraction: float = DEFAULT_STREAM_2_RUNTIME_FRACTION
    stream_2_yield_hours_utc: tuple[int, ...] = DEFAULT_STREAM_2_YIELD_HOURS_UTC
    head_release_when: str = DEFAULT_HEAD_RELEASE_WHEN
    leftover_max_age_seconds: float = DEFAULT_LEFTOVER_MAX_AGE_SECONDS
    spare_wait_seconds: float = DEFAULT_SPARE_WAIT_SECONDS
    min_leftover_seconds: float = DEFAULT_MIN_LEFTOVER_SECONDS
    scheduler_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_ingest_effort_cascade_policy() -> dict[str, Any]:
    return {
        "enabled": True,
        "stream_1_target_fraction": DEFAULT_STREAM_1_TARGET_FRACTION,
        "stream_1_runtime_fraction": DEFAULT_STREAM_1_RUNTIME_FRACTION,
        "stream_2_target_fraction": DEFAULT_STREAM_2_TARGET_FRACTION,
        "stream_2_runtime_fraction": DEFAULT_STREAM_2_RUNTIME_FRACTION,
        "stream_2_yield_hours_utc": list(DEFAULT_STREAM_2_YIELD_HOURS_UTC),
        "head_release_when": DEFAULT_HEAD_RELEASE_WHEN,
        "leftover_max_age_seconds": DEFAULT_LEFTOVER_MAX_AGE_SECONDS,
        "spare_wait_seconds": DEFAULT_SPARE_WAIT_SECONDS,
        "min_leftover_seconds": DEFAULT_MIN_LEFTOVER_SECONDS,
        "scheduler_enabled": True,
        "note": (
            "While head_needs_fat_slot is true the head keeps host priority. "
            "Priority-slot width is min(unfilled names, host budget left, time "
            "left) for that kind, then the job ceiling. One unfilled name "
            "reserves one name; the unused part of the old fixed cap is not "
            "reserved. Nothing unfilled means width 0. The release bit stays "
            "head_needs_fat_slot (false at parity). Spares subtract "
            "head_unfilled only — not a fixed 50%/25% cut. Fractions below are "
            "legacy and unused. head_release_when=ingest_parity (default) or "
            "phase2_ready."
        ),
    }


def load_cascade_config(policy: dict[str, Any] | None) -> IngestCascadeConfig:
    raw = dict((policy or {}).get("ingest_effort_cascade") or {})
    hours_raw = raw.get("stream_2_yield_hours_utc", DEFAULT_STREAM_2_YIELD_HOURS_UTC)
    hours: list[int] = []
    for item in list(hours_raw or []):
        try:
            hour = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23:
            hours.append(hour)
    if not hours:
        hours = list(DEFAULT_STREAM_2_YIELD_HOURS_UTC)
    enabled = raw.get("enabled", True)
    return IngestCascadeConfig(
        enabled=bool(enabled),
        stream_1_target_fraction=_fraction(
            raw.get("stream_1_target_fraction"), DEFAULT_STREAM_1_TARGET_FRACTION
        ),
        stream_1_runtime_fraction=_fraction(
            raw.get("stream_1_runtime_fraction"), DEFAULT_STREAM_1_RUNTIME_FRACTION
        ),
        stream_2_target_fraction=_fraction(
            raw.get("stream_2_target_fraction"), DEFAULT_STREAM_2_TARGET_FRACTION
        ),
        stream_2_runtime_fraction=_fraction(
            raw.get("stream_2_runtime_fraction"), DEFAULT_STREAM_2_RUNTIME_FRACTION
        ),
        stream_2_yield_hours_utc=tuple(hours),
        head_release_when=_release_when(raw.get("head_release_when")),
        leftover_max_age_seconds=_positive_float(
            raw.get("leftover_max_age_seconds"), DEFAULT_LEFTOVER_MAX_AGE_SECONDS
        ),
        spare_wait_seconds=_positive_float(
            raw.get("spare_wait_seconds"), DEFAULT_SPARE_WAIT_SECONDS
        ),
        min_leftover_seconds=_positive_float(
            raw.get("min_leftover_seconds"), DEFAULT_MIN_LEFTOVER_SECONDS
        ),
        scheduler_enabled=bool(raw.get("scheduler_enabled", True)),
    )


def _release_when(raw: Any) -> str:
    value = str(raw or DEFAULT_HEAD_RELEASE_WHEN).strip().lower()
    if value == HEAD_RELEASE_PHASE2:
        return HEAD_RELEASE_PHASE2
    return HEAD_RELEASE_INGEST_PARITY


def _positive_float(raw: Any, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return value


def _fraction(raw: Any, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return min(1.0, value)


def head_market_id(policy: dict[str, Any] | None) -> str:
    return str((policy or {}).get("focus_market") or "euro_depth").strip() or "euro_depth"


def head_needs_fat_slot(
    *,
    head_at_parity: bool,
    config: IngestCascadeConfig,
    phase2_ready: bool = False,
) -> bool:
    """True while the focus market still holds the priority slot.

    This is the release bit. It is false at ingest parity (or phase-2 release).
    A width of 0 does not flip it.
    """
    if not config.enabled:
        return False
    if config.head_release_when == HEAD_RELEASE_PHASE2:
        return not bool(phase2_ready)
    return not bool(head_at_parity)


def kind_seconds(kind: str | None) -> float:
    """Seconds one name of this kind consumes on the job clock."""
    key = str(kind or KIND_FILING_BODY).strip().lower()
    return float(KIND_SECONDS_PER_NAME.get(key, KIND_SECONDS_PER_NAME[KIND_FILING_BODY]))


def names_that_fit(time_left_seconds: float, kind: str | None) -> int:
    """How many names of ``kind`` fit in the seconds still left on this job."""
    remaining = float(time_left_seconds or 0.0)
    per_name = kind_seconds(kind)
    if remaining <= 0 or per_name <= 0:
        return 0
    return int(remaining / per_name)


def dynamic_ingest_width(
    *,
    unfilled: int,
    host_budget_left: int,
    time_left_seconds: float,
    kind: str = KIND_FILING_BODY,
) -> int:
    """Names this strand may fetch this run.

    Width is ``min(unfilled, host budget left, names that fit in the time left)``.
    A strand with nothing to fetch returns 0. No fixed spare fraction is applied.
    """
    count = max(0, int(unfilled))
    if count <= 0:
        return 0
    host = max(0, int(host_budget_left))
    if host <= 0:
        return 0
    return min(count, host, names_that_fit(time_left_seconds, kind))


def priority_slot_width(
    *,
    unfilled: int,
    host_budget_left: int,
    time_left_seconds: float,
    kind: str = KIND_FILING_BODY,
    job_ceiling: int,
) -> int:
    """Names the head priority slot may fetch this run.

    Same rule as a spare, then the job ceiling so one strand cannot take an
    unbounded run. One unfilled name reserves one name. A ceiling of 24, or a
    workflow fallback of 12, is not a reservation of the unused names. Nothing
    unfilled returns 0. The release bit stays ``head_needs_fat_slot``.
    """
    width = dynamic_ingest_width(
        unfilled=unfilled,
        host_budget_left=host_budget_left,
        time_left_seconds=time_left_seconds,
        kind=kind,
    )
    ceiling = max(0, int(job_ceiling))
    if ceiling <= 0:
        return 0
    return min(width, ceiling)


def filing_names_unfilled(health: dict[str, Any] | None) -> int:
    """Unparked filing names still to fetch (unmeasured, zero-body, thin, IWB)."""
    row = health or {}
    unmeasured = int(row.get("unmeasured_buy_tier") or 0)
    zero_body = int(row.get("zero_body_buy_tier") or 0)
    if "effective_thin_body_buy_tier" in row or "effective_indexed_without_body" in row:
        thin = int(row.get("effective_thin_body_buy_tier") or 0)
        indexed = int(row.get("effective_indexed_without_body") or 0)
    else:
        thin = int(row.get("thin_body_buy_tier") or 0)
        indexed = int(row.get("indexed_without_body") or 0)
    return max(0, unmeasured + zero_body + thin + indexed)


def scale_spare_budget(
    stream: int,
    max_targets: int,
    max_runtime_seconds: float,
    *,
    config: IngestCascadeConfig,
    head_needs_fat: bool,
    unfilled: int | None = None,
    head_unfilled: int | None = None,
    kind: str = KIND_FILING_BODY,
    host_budget_left: int | None = None,
) -> tuple[int, float, str]:
    """Return (targets, runtime, mode) for a parallel sprint stream.

    ``config`` fractions are ignored. While the head needs the priority slot and
    ``head_unfilled`` is set, those names are reserved from the host budget
    first — one unfilled name, not the unused part of the head's job ceiling.
    When the head does not need the slot, the spare is not cut to 50%/25%.
    ``unfilled is None`` means the caller did not declare a count, so the job
    cap is the demand. An explicit 0 is an empty strand.
    """
    del config  # fractions are legacy; signature kept for callers
    cap = max(0, int(max_targets))
    runtime = max(0.0, float(max_runtime_seconds))
    if unfilled is not None and int(unfilled) <= 0:
        return 0, 0.0, "empty"
    if not head_needs_fat or stream not in (1, 2):
        if unfilled is None:
            return max(cap, 0) or 0, runtime, "full"
        host = cap if host_budget_left is None else max(0, int(host_budget_left))
        width = dynamic_ingest_width(
            unfilled=int(unfilled),
            host_budget_left=host,
            time_left_seconds=runtime,
            kind=kind,
        )
        width = min(width, cap) if cap else width
        if width <= 0:
            return 0, 0.0, "empty"
        return width, min(runtime, width * kind_seconds(kind)), "full"

    demand = cap if unfilled is None else max(0, int(unfilled))
    host = cap if host_budget_left is None else max(0, int(host_budget_left))
    if head_unfilled is not None and int(head_unfilled) > 0 and host > 0:
        host = max(0, host - min(int(head_unfilled), host))
    width = dynamic_ingest_width(
        unfilled=demand,
        host_budget_left=host,
        time_left_seconds=runtime,
        kind=kind,
    )
    if cap:
        width = min(width, cap)
    if width <= 0:
        return 0, 0.0, "empty"
    return width, min(runtime, width * kind_seconds(kind)), "spare"


def should_skip_spare_stream(
    stream: int,
    *,
    hour_utc: int,
    config: IngestCascadeConfig,
    head_needs_fat: bool,
) -> bool:
    """Stream 2 skips peak hours that overlap the head priority slot."""
    if not head_needs_fat or stream != 2:
        return False
    return int(hour_utc) in set(config.stream_2_yield_hours_utc)


@dataclass
class IngestCascadeDecision:
    enabled: bool
    head_market: str
    head_at_parity: bool
    head_needs_fat_slot: bool
    hour_utc: int
    skip_stream_2_now: bool
    stream_1_mode: str
    stream_2_mode: str
    reason: str
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "head_market": self.head_market,
            "head_at_parity": self.head_at_parity,
            "head_needs_fat_slot": self.head_needs_fat_slot,
            "hour_utc": self.hour_utc,
            "skip_stream_2_now": self.skip_stream_2_now,
            "stream_1_mode": self.stream_1_mode,
            "stream_2_mode": self.stream_2_mode,
            "reason": self.reason,
            "config": self.config,
        }


def evaluate_ingest_cascade(
    policy: dict[str, Any] | None,
    *,
    head_at_parity: bool,
    now: datetime | None = None,
    phase2_ready: bool = False,
) -> IngestCascadeDecision:
    config = load_cascade_config(policy)
    when = now or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    hour = when.astimezone(UTC).hour
    head = head_market_id(policy)
    needs_fat = head_needs_fat_slot(
        head_at_parity=head_at_parity,
        config=config,
        phase2_ready=phase2_ready,
    )
    skip_stream_2 = should_skip_spare_stream(
        2, hour_utc=hour, config=config, head_needs_fat=needs_fat
    )
    _t1, _r1, mode1 = scale_spare_budget(1, 24, 2100.0, config=config, head_needs_fat=needs_fat)
    _t2, _r2, mode2 = scale_spare_budget(2, 24, 2100.0, config=config, head_needs_fat=needs_fat)
    if not config.enabled:
        reason = "Cascade disabled — parallel streams use full peer budgets."
    elif not needs_fat:
        reason = (
            f"Head {head} is at ingest parity — spare streams return to full caps "
            "(priority slot may shift on the next focus advance)."
        )
    elif skip_stream_2:
        reason = (
            f"Head {head} still has filing gaps; stream 2 yields hour {hour:02d}:00 UTC "
            f"to the priority slot."
        )
    else:
        reason = (
            f"Head {head} still has filing gaps; spare width is each strand's "
            "unfilled names capped by host budget left and time left."
        )
    return IngestCascadeDecision(
        enabled=config.enabled,
        head_market=head,
        head_at_parity=bool(head_at_parity),
        head_needs_fat_slot=needs_fat,
        hour_utc=hour,
        skip_stream_2_now=skip_stream_2,
        stream_1_mode=mode1,
        stream_2_mode=mode2,
        reason=reason,
        config=config.to_dict(),
    )


__all__ = [
    "DEFAULT_HEAD_RELEASE_WHEN",
    "DEFAULT_LEFTOVER_MAX_AGE_SECONDS",
    "DEFAULT_MIN_LEFTOVER_SECONDS",
    "DEFAULT_SPARE_WAIT_SECONDS",
    "DEFAULT_STREAM_1_RUNTIME_FRACTION",
    "DEFAULT_STREAM_1_TARGET_FRACTION",
    "DEFAULT_STREAM_2_RUNTIME_FRACTION",
    "DEFAULT_STREAM_2_TARGET_FRACTION",
    "DEFAULT_STREAM_2_YIELD_HOURS_UTC",
    "HEAD_RELEASE_INGEST_PARITY",
    "HEAD_RELEASE_PHASE2",
    "IngestCascadeConfig",
    "IngestCascadeDecision",
    "default_ingest_effort_cascade_policy",
    "KIND_DAILY_PRICE",
    "KIND_FILING_BODY",
    "KIND_MEMO",
    "KIND_SECONDS_PER_NAME",
    "dynamic_ingest_width",
    "evaluate_ingest_cascade",
    "filing_names_unfilled",
    "head_market_id",
    "head_needs_fat_slot",
    "kind_seconds",
    "load_cascade_config",
    "names_that_fit",
    "priority_slot_width",
    "scale_spare_budget",
    "should_skip_spare_stream",
]
