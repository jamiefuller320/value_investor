"""Week-first then iterative-backward pack assemble order (archive lane only).

Pinned design for the cold universe filing archive / data-pack lane. This order
is **separate from the live fat/spare cascade** (buy-tier deepen on the focus
head). Archive coverage prefers calendar freshness across the admitted roster:

1. Current ISO week × all markets (broad surface)
2. Then week-1, week-2, … iteratively backward

Within a week, markets keep a stable roster order. No ticker crawl lives here —
callers attach tickers later. See ``docs/ops/universe-filing-archive-pack.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1
PACK_ORDER_ID = "week_first_then_backward"
DEFAULT_LOOKBACK_WEEKS = 12


@dataclass(frozen=True)
class PackCoverageUnit:
    """One archive coverage unit: ISO week × market."""

    iso_year: int
    iso_week: int
    market_id: str
    week_start: date  # Monday of the ISO week (UTC calendar)
    week_end: date  # Sunday of the ISO week
    rank: int  # 0 = current week first across markets

    @property
    def unit_id(self) -> str:
        return f"{self.iso_year}-W{self.iso_week:02d}:{self.market_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "iso_year": self.iso_year,
            "iso_week": self.iso_week,
            "market_id": self.market_id,
            "week_start": self.week_start.isoformat(),
            "week_end": self.week_end.isoformat(),
            "rank": self.rank,
        }


def _as_date(value: date | datetime | None) -> date:
    if value is None:
        return datetime.now(UTC).date()
    if isinstance(value, datetime):
        clock = value
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=UTC)
        else:
            clock = clock.astimezone(UTC)
        return clock.date()
    return value


def iso_week_bounds(iso_year: int, iso_week: int) -> tuple[date, date]:
    """Return Monday–Sunday dates for an ISO week."""
    monday = date.fromisocalendar(int(iso_year), int(iso_week), 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def iter_iso_weeks_backward(
    *,
    as_of: date | datetime | None = None,
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
) -> list[tuple[int, int, date, date]]:
    """Current ISO week first, then prior weeks (iterative backward)."""
    day = _as_date(as_of)
    weeks = max(1, int(lookback_weeks))
    out: list[tuple[int, int, date, date]] = []
    # Anchor on Monday of the as_of ISO week, then walk back.
    year, week, _ = day.isocalendar()
    monday, sunday = iso_week_bounds(year, week)
    for _ in range(weeks):
        y, w, _ = monday.isocalendar()
        out.append((y, w, monday, sunday))
        monday = monday - timedelta(days=7)
        sunday = monday + timedelta(days=6)
    return out


def normalize_market_roster(markets: Sequence[str] | None) -> list[str]:
    """Stable de-duplicated market ids (preserve first-seen order)."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in markets or ():
        mid = str(raw or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out


def build_week_first_pack_plan(
    markets: Sequence[str],
    *,
    as_of: date | datetime | None = None,
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
    max_units: int | None = None,
) -> dict[str, Any]:
    """Build the week-first → backward coverage plan for archive pack assemble.

    Does **not** start fetches. Callers pass the admitted (+ live) roster.
    """
    roster = normalize_market_roster(markets)
    weeks = iter_iso_weeks_backward(as_of=as_of, lookback_weeks=lookback_weeks)
    units: list[PackCoverageUnit] = []
    rank = 0
    for iso_year, iso_week, week_start, week_end in weeks:
        for mid in roster:
            units.append(
                PackCoverageUnit(
                    iso_year=iso_year,
                    iso_week=iso_week,
                    market_id=mid,
                    week_start=week_start,
                    week_end=week_end,
                    rank=rank,
                )
            )
            rank += 1
            if max_units is not None and rank >= int(max_units):
                break
        if max_units is not None and rank >= int(max_units):
            break

    day = _as_date(as_of)
    return {
        "schema_version": SCHEMA_VERSION,
        "pack_order": PACK_ORDER_ID,
        "as_of": day.isoformat(),
        "lookback_weeks": max(1, int(lookback_weeks)),
        "market_count": len(roster),
        "markets": roster,
        "unit_count": len(units),
        "units": [u.to_dict() for u in units],
        "note": (
            "Archive-only week-first coverage then iterative backward looks. "
            "Not the live fat/spare buy-tier cascade."
        ),
    }


def units_from_plan(plan: dict[str, Any] | None) -> list[PackCoverageUnit]:
    """Rehydrate PackCoverageUnit rows from a plan dict."""
    out: list[PackCoverageUnit] = []
    for raw in (plan or {}).get("units") or []:
        if not isinstance(raw, dict):
            continue
        try:
            week_start = date.fromisoformat(str(raw.get("week_start") or ""))
            week_end = date.fromisoformat(str(raw.get("week_end") or ""))
        except ValueError:
            continue
        mid = str(raw.get("market_id") or "").strip()
        if not mid:
            continue
        out.append(
            PackCoverageUnit(
                iso_year=int(raw.get("iso_year") or week_start.isocalendar()[0]),
                iso_week=int(raw.get("iso_week") or week_start.isocalendar()[1]),
                market_id=mid,
                week_start=week_start,
                week_end=week_end,
                rank=int(raw.get("rank") or len(out)),
            )
        )
    return out


def summarize_plan_by_week(plan: dict[str, Any] | Iterable[PackCoverageUnit]) -> list[dict[str, Any]]:
    """Roll plan units into per-week market counts (for bottleneck / CLI summary)."""
    if isinstance(plan, dict):
        rows = units_from_plan(plan)
    else:
        rows = list(plan)
    buckets: dict[tuple[int, int], dict[str, Any]] = {}
    for unit in rows:
        key = (unit.iso_year, unit.iso_week)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "iso_year": unit.iso_year,
                "iso_week": unit.iso_week,
                "week_start": unit.week_start.isoformat(),
                "week_end": unit.week_end.isoformat(),
                "market_count": 0,
                "markets": [],
                "first_rank": unit.rank,
            }
            buckets[key] = bucket
        bucket["market_count"] = int(bucket["market_count"]) + 1
        markets = bucket["markets"]
        assert isinstance(markets, list)
        markets.append(unit.market_id)
    return sorted(buckets.values(), key=lambda r: int(r.get("first_rank") or 0))


__all__ = [
    "DEFAULT_LOOKBACK_WEEKS",
    "PACK_ORDER_ID",
    "SCHEMA_VERSION",
    "PackCoverageUnit",
    "build_week_first_pack_plan",
    "iso_week_bounds",
    "iter_iso_weeks_backward",
    "normalize_market_roster",
    "summarize_plan_by_week",
    "units_from_plan",
]
