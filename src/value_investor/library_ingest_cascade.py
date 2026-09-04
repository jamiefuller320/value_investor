"""P2 ingest effort cascade: fat slot on the learning-phase head, spare on the tail.

Doctrine (AGENTS.md): while the focus market still has FTSE-standard filing gaps,
parallel sprint streams must not run as equal peers. Stream 1 (next queue market)
keeps a reduced budget. Stream 2 yields the morning peak slots that overlap the
head sprint, and otherwise runs a small leftover budget.

A full preemptible GHA scheduler is later (L273). This module is the first slice.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

DEFAULT_STREAM_1_TARGET_FRACTION = 0.5
DEFAULT_STREAM_1_RUNTIME_FRACTION = 0.5
DEFAULT_STREAM_2_TARGET_FRACTION = 0.25
DEFAULT_STREAM_2_RUNTIME_FRACTION = 0.25
# Stream 2 crons are focus+60m. Peak euro slots are 07:15 / 10:15; stream 2 is 08:15 / 11:15.
DEFAULT_STREAM_2_YIELD_HOURS_UTC: tuple[int, ...] = (8, 11)
MIN_SPARE_TARGETS = 1
MIN_SPARE_RUNTIME_SECONDS = 60.0


@dataclass(frozen=True)
class IngestCascadeConfig:
    enabled: bool = True
    stream_1_target_fraction: float = DEFAULT_STREAM_1_TARGET_FRACTION
    stream_1_runtime_fraction: float = DEFAULT_STREAM_1_RUNTIME_FRACTION
    stream_2_target_fraction: float = DEFAULT_STREAM_2_TARGET_FRACTION
    stream_2_runtime_fraction: float = DEFAULT_STREAM_2_RUNTIME_FRACTION
    stream_2_yield_hours_utc: tuple[int, ...] = DEFAULT_STREAM_2_YIELD_HOURS_UTC

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
        "note": (
            "While focus (head) still has filing gaps, scale spare sprint streams "
            "and skip stream-2 peak hours that overlap the fat slot. Full caps "
            "return when the head reaches ingest parity."
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
    )


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


def head_needs_fat_slot(*, head_at_parity: bool, config: IngestCascadeConfig) -> bool:
    """True while the focus market still needs the high-tempo sprint (filing gaps)."""
    return bool(config.enabled) and not bool(head_at_parity)


def scale_spare_budget(
    stream: int,
    max_targets: int,
    max_runtime_seconds: float,
    *,
    config: IngestCascadeConfig,
    head_needs_fat: bool,
) -> tuple[int, float, str]:
    """Return (targets, runtime, mode) for a parallel sprint stream."""
    targets = max(1, int(max_targets))
    runtime = max(0.0, float(max_runtime_seconds))
    if not head_needs_fat or stream not in (1, 2):
        return targets, runtime, "full"
    if stream == 1:
        target_frac = config.stream_1_target_fraction
        runtime_frac = config.stream_1_runtime_fraction
    else:
        target_frac = config.stream_2_target_fraction
        runtime_frac = config.stream_2_runtime_fraction
    scaled_targets = max(MIN_SPARE_TARGETS, int(targets * target_frac))
    scaled_runtime = max(MIN_SPARE_RUNTIME_SECONDS, runtime * runtime_frac)
    return scaled_targets, scaled_runtime, "spare"


def should_skip_spare_stream(
    stream: int,
    *,
    hour_utc: int,
    config: IngestCascadeConfig,
    head_needs_fat: bool,
) -> bool:
    """Stream 2 skips peak hours that overlap the head fat slot."""
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
) -> IngestCascadeDecision:
    config = load_cascade_config(policy)
    when = now or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    hour = when.astimezone(UTC).hour
    head = head_market_id(policy)
    needs_fat = head_needs_fat_slot(head_at_parity=head_at_parity, config=config)
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
            "(fat slot may shift on the next focus advance)."
        )
    elif skip_stream_2:
        reason = (
            f"Head {head} still has filing gaps; stream 2 yields hour {hour:02d}:00 UTC "
            f"to the fat slot."
        )
    else:
        reason = (
            f"Head {head} still has filing gaps; stream 1/2 run spare fractions "
            f"({config.stream_1_target_fraction:.2f}/{config.stream_2_target_fraction:.2f})."
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
    "DEFAULT_STREAM_1_RUNTIME_FRACTION",
    "DEFAULT_STREAM_1_TARGET_FRACTION",
    "DEFAULT_STREAM_2_RUNTIME_FRACTION",
    "DEFAULT_STREAM_2_TARGET_FRACTION",
    "DEFAULT_STREAM_2_YIELD_HOURS_UTC",
    "IngestCascadeConfig",
    "IngestCascadeDecision",
    "default_ingest_effort_cascade_policy",
    "evaluate_ingest_cascade",
    "head_market_id",
    "head_needs_fat_slot",
    "load_cascade_config",
    "scale_spare_budget",
    "should_skip_spare_stream",
]
