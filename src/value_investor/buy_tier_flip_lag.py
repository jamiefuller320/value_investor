"""Observe-only lag pin: new buy-tier flip → AI-usable clocks.

Tracks FTSE buy/strong_buy names from ``signal_since`` through filings index,
key bodies (annual + interim when indexed), first memo, and
``ai_track_buy_eligible`` (effective buy-tier + ``research_verdict=accumulate``).

Does not deepen ingest, rememo, or dispatch engineering. Persists
``docs/data/buy_tier_flip_lag.json`` so recurring lag can later justify
process tightening.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.paper_fund import BUY_SIGNALS
from value_investor.research.gap_fill_sources import inspect_local_sources
from value_investor.storage import read_json, resolve_json_path, write_json

logger = logging.getLogger(__name__)

DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_RESEARCH_ROOT = Path("docs/data/research")
DEFAULT_MEMO_DIR = Path("docs/research")
DEFAULT_STORE_PATH = Path("docs/data/buy_tier_flip_lag.json")

SCHEMA_VERSION = 1
DEFAULT_FLIP_LOOKBACK_DAYS = 21
# Surface ops warn after one weekday ingest day of remaining non-usable.
DEFAULT_WARN_AFTER_HOURS = 24.0
# Keep closed (became usable) rows for cohort review.
DEFAULT_CLOSED_KEEP_DAYS = 90

BLOCKING_STAGES = (
    "no_index",
    "no_key_bodies",
    "no_memo",
    "no_accumulate_verdict",
)
# Ops warn focuses on factory-path lag (ingest → first memo), not screen names
# whose memo already returned a non-accumulate verdict.
PATH_INCOMPLETE_STAGES = frozenset({"no_index", "no_key_bodies", "no_memo"})


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _hours_between(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 3600.0, 2)


def _date_start_utc(raw: Any) -> datetime | None:
    dt = _parse_dt(raw)
    if dt is None:
        return None
    return datetime(dt.year, dt.month, dt.day, tzinfo=UTC)


def _effective_buy_signal(signal: str, adjusted: str | None) -> str:
    if adjusted is not None and str(adjusted).strip():
        return str(adjusted).strip()
    return signal


def _key_bodies_ready(period_coverage: dict[str, Any], filings_total: int) -> bool:
    """Annual body required; interim body required only when interim rows are indexed."""
    if filings_total <= 0:
        return False
    annual = dict(period_coverage.get("annual") or {})
    interim = dict(period_coverage.get("interim") or {})
    annual_bodies = int(annual.get("with_body") or 0)
    interim_total = int(interim.get("total") or 0)
    interim_bodies = int(interim.get("with_body") or 0)
    if annual_bodies < 1:
        return False
    if interim_total > 0 and interim_bodies < 1:
        return False
    return True


def _load_latest_reports(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return []
    rows = payload.get("reports") or []
    return [row for row in rows if isinstance(row, dict)]


def _research_doc_times(
    ticker: str,
    *,
    research_root: Path,
) -> tuple[bool, datetime | None, str | None]:
    """Return (has_research_json, created_at, research_verdict_from_disk)."""
    path = resolve_json_path(research_root / ticker / "research.json")
    if path is None or not path.is_file():
        return False, None, None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return True, None, None
    created = _parse_dt(payload.get("created_at") or payload.get("updated_at"))
    verdict = payload.get("research_verdict")
    verdict_str = str(verdict) if verdict is not None else None
    return True, created, verdict_str


def _index_meta(
    ticker: str,
    *,
    research_root: Path,
) -> dict[str, Any]:
    sources_dir = research_root / ticker / "sources"
    index_path = resolve_json_path(sources_dir / "filings" / "filings_index.json")
    if index_path is None or not index_path.is_file():
        return {
            "has_index": False,
            "index_at": None,
            "filings_total": 0,
            "filings_with_body": 0,
            "period_coverage": {},
            "key_bodies": False,
        }
    try:
        payload = read_json(index_path)
    except (OSError, ValueError, TypeError):
        return {
            "has_index": True,
            "index_at": None,
            "filings_total": 0,
            "filings_with_body": 0,
            "period_coverage": {},
            "key_bodies": False,
        }
    summary = dict(payload.get("summary") or {})
    period_coverage = dict(summary.get("period_coverage") or {})
    if not period_coverage and sources_dir.is_dir():
        inventory = inspect_local_sources(sources_dir)
        period_coverage = dict(inventory.get("period_coverage") or {})
        summary = dict(inventory.get("filings_summary") or summary)
    filings_total = int(summary.get("total") or 0)
    filings_with_body = int(summary.get("with_body") or 0)
    index_at = _parse_dt(payload.get("fetched_at") or payload.get("ch_refetched_at"))
    return {
        "has_index": True,
        "index_at": index_at.isoformat() if index_at else None,
        "filings_total": filings_total,
        "filings_with_body": filings_with_body,
        "period_coverage": period_coverage,
        "key_bodies": _key_bodies_ready(period_coverage, filings_total),
    }


@dataclass
class FlipLagSnapshot:
    ticker: str
    name: str
    signal: str
    signal_since: str
    flip_at: str
    first_surfaced_at: str
    has_index: bool
    index_at: str | None
    key_bodies: bool
    has_memo: bool
    first_memo_at: str | None
    research_verdict: str | None
    ai_track_buy_eligible: bool
    usable: bool
    usable_at: str | None
    blocking_stage: str | None
    hours_since_flip: float | None
    hours_to_index: float | None = None
    hours_to_key_bodies: float | None = None
    hours_to_first_memo: float | None = None
    hours_to_usable: float | None = None
    status: str = "open"  # open | usable
    stages: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "signal": self.signal,
            "signal_since": self.signal_since,
            "flip_at": self.flip_at,
            "first_surfaced_at": self.first_surfaced_at,
            "has_index": self.has_index,
            "index_at": self.index_at,
            "key_bodies": self.key_bodies,
            "has_memo": self.has_memo,
            "first_memo_at": self.first_memo_at,
            "research_verdict": self.research_verdict,
            "ai_track_buy_eligible": self.ai_track_buy_eligible,
            "usable": self.usable,
            "usable_at": self.usable_at,
            "blocking_stage": self.blocking_stage,
            "hours_since_flip": self.hours_since_flip,
            "hours_to_index": self.hours_to_index,
            "hours_to_key_bodies": self.hours_to_key_bodies,
            "hours_to_first_memo": self.hours_to_first_memo,
            "hours_to_usable": self.hours_to_usable,
            "status": self.status,
            "stages": dict(self.stages),
        }


def _blocking_stage(
    *,
    has_index: bool,
    key_bodies: bool,
    has_memo: bool,
    ai_eligible: bool,
) -> str | None:
    if not has_index:
        return "no_index"
    if not key_bodies:
        return "no_key_bodies"
    if not has_memo:
        return "no_memo"
    if not ai_eligible:
        return "no_accumulate_verdict"
    return None


def _empty_store() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": None,
        "lookback_days": DEFAULT_FLIP_LOOKBACK_DAYS,
        "warn_after_hours": DEFAULT_WARN_AFTER_HOURS,
        "summary": {},
        "open": [],
        "recently_usable": [],
        "names": {},
        "surface_events": [],
    }


def load_flip_lag_store(path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return _empty_store()
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        logger.warning("Corrupt buy-tier flip lag store at %s — resetting", path)
        return _empty_store()
    if not isinstance(payload, dict):
        return _empty_store()
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("names", {})
    payload.setdefault("surface_events", [])
    payload.setdefault("open", [])
    payload.setdefault("recently_usable", [])
    return payload


def snapshot_flip_name(
    report: dict[str, Any],
    *,
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    now: datetime | None = None,
    prior: dict[str, Any] | None = None,
) -> FlipLagSnapshot | None:
    """Build lag snapshot for one buy-tier report row, or None if not a flip cohort member."""
    now = now or datetime.now(UTC)
    ticker = str(report.get("ticker") or "").strip().upper()
    if not ticker:
        return None
    signal = str(report.get("signal") or "")
    if signal not in BUY_SIGNALS:
        return None
    signal_since = str(report.get("signal_since") or "").strip()
    flip_at = _date_start_utc(signal_since)
    if flip_at is None:
        return None

    prior = prior or {}
    name = str(report.get("name") or prior.get("name") or "")
    adjusted = report.get("adjusted_signal")
    adjusted_str = str(adjusted) if adjusted is not None else None
    effective = _effective_buy_signal(signal, adjusted_str)

    index_meta = _index_meta(ticker, research_root=research_root)
    has_index = bool(index_meta["has_index"])
    key_bodies = bool(index_meta["key_bodies"])
    index_at = _parse_dt(index_meta.get("index_at"))

    has_disk_memo, memo_created, disk_verdict = _research_doc_times(
        ticker, research_root=research_root
    )
    memo_md = (Path(memo_dir) / f"{ticker}.md").is_file()
    has_memo = has_disk_memo or memo_md

    screen_verdict = report.get("research_verdict")
    verdict_str = (
        str(screen_verdict)
        if screen_verdict is not None
        else (disk_verdict if disk_verdict is not None else None)
    )
    ai_eligible = effective in BUY_SIGNALS and verdict_str == "accumulate"
    # Full path: index → key bodies → first memo → ai_track_buy_eligible.
    usable = bool(has_index and key_bodies and has_memo and ai_eligible)
    blocking = _blocking_stage(
        has_index=has_index,
        key_bodies=key_bodies,
        has_memo=has_memo,
        ai_eligible=ai_eligible,
    )

    first_surfaced = _parse_dt(prior.get("first_surfaced_at")) or now
    prior_usable_at = _parse_dt(prior.get("usable_at"))
    usable_at = prior_usable_at
    if usable and usable_at is None:
        usable_at = now

    # Preserve earliest observed stage timestamps.
    prior_index_at = _parse_dt(prior.get("index_at"))
    if index_at is None:
        index_at = prior_index_at
    elif prior_index_at is not None and prior_index_at < index_at:
        index_at = prior_index_at

    prior_memo_at = _parse_dt(prior.get("first_memo_at"))
    memo_at = memo_created or prior_memo_at
    if memo_created and prior_memo_at and prior_memo_at < memo_created:
        memo_at = prior_memo_at

    key_bodies_at = _parse_dt(prior.get("key_bodies_at"))
    if key_bodies and key_bodies_at is None:
        # Approximate: first observation where key bodies are present.
        key_bodies_at = index_at or now

    hours_since = _hours_between(flip_at, now)
    return FlipLagSnapshot(
        ticker=ticker,
        name=name,
        signal=signal,
        signal_since=signal_since[:10],
        flip_at=flip_at.isoformat(),
        first_surfaced_at=first_surfaced.isoformat(),
        has_index=has_index,
        index_at=index_at.isoformat() if index_at else None,
        key_bodies=key_bodies,
        has_memo=has_memo,
        first_memo_at=memo_at.isoformat() if memo_at else None,
        research_verdict=verdict_str,
        ai_track_buy_eligible=ai_eligible,
        usable=usable,
        usable_at=usable_at.isoformat() if usable_at else None,
        blocking_stage=None if usable else blocking,
        hours_since_flip=hours_since,
        hours_to_index=_hours_between(flip_at, index_at),
        hours_to_key_bodies=_hours_between(flip_at, key_bodies_at if key_bodies else None),
        hours_to_first_memo=_hours_between(flip_at, memo_at),
        hours_to_usable=_hours_between(flip_at, usable_at),
        status="usable" if usable else "open",
        stages={
            "index": has_index,
            "key_bodies": key_bodies,
            "first_memo": has_memo,
            "ai_track_buy_eligible": ai_eligible,
        },
    )


def select_flip_cohort(
    reports: list[dict[str, Any]],
    *,
    lookback_days: int = DEFAULT_FLIP_LOOKBACK_DAYS,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Buy-tier rows whose ``signal_since`` falls within the lookback window."""
    now = now or datetime.now(UTC)
    cutoff = datetime(now.year, now.month, now.day, tzinfo=UTC) - timedelta(
        days=max(0, int(lookback_days))
    )
    out: list[dict[str, Any]] = []
    for row in reports:
        signal = str(row.get("signal") or "")
        if signal not in BUY_SIGNALS:
            continue
        flip_at = _date_start_utc(row.get("signal_since"))
        if flip_at is None:
            continue
        if flip_at < cutoff:
            continue
        out.append(row)
    return out


def update_buy_tier_flip_lag(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    store_path: Path = DEFAULT_STORE_PATH,
    lookback_days: int = DEFAULT_FLIP_LOOKBACK_DAYS,
    warn_after_hours: float = DEFAULT_WARN_AFTER_HOURS,
    closed_keep_days: int = DEFAULT_CLOSED_KEEP_DAYS,
    now: datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Refresh observe store from latest buy-tier + research disks; optionally persist."""
    now = now or datetime.now(UTC)
    store = load_flip_lag_store(store_path)
    prior_names: dict[str, Any] = dict(store.get("names") or {})
    events: list[dict[str, Any]] = list(store.get("surface_events") or [])

    reports = _load_latest_reports(latest_path)
    cohort_rows = select_flip_cohort(reports, lookback_days=lookback_days, now=now)
    snapshots: list[FlipLagSnapshot] = []

    for row in cohort_rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        prior = dict(prior_names.get(ticker) or {})
        snap = snapshot_flip_name(
            row,
            research_root=research_root,
            memo_dir=memo_dir,
            now=now,
            prior=prior,
        )
        if snap is None:
            continue
        if ticker not in prior_names:
            events.append(
                {
                    "event": "flip_surfaced",
                    "ticker": ticker,
                    "at": snap.first_surfaced_at,
                    "signal_since": snap.signal_since,
                    "blocking_stage": snap.blocking_stage,
                }
            )
        elif prior.get("status") == "open" and snap.status == "usable":
            events.append(
                {
                    "event": "became_usable",
                    "ticker": ticker,
                    "at": snap.usable_at,
                    "hours_to_usable": snap.hours_to_usable,
                    "signal_since": snap.signal_since,
                }
            )
        prior_payload = snap.to_dict()
        if snap.key_bodies:
            prior_payload["key_bodies_at"] = prior.get("key_bodies_at") or (
                snap.index_at or now.isoformat()
            )
        prior_names[ticker] = prior_payload
        snapshots.append(snap)

    # Age out very old closed names still in the map but outside lookback.
    keep_cutoff = now - timedelta(days=max(1, int(closed_keep_days)))
    pruned: dict[str, Any] = {}
    for ticker, row in prior_names.items():
        status = str(row.get("status") or "")
        flip_at = _parse_dt(row.get("flip_at") or row.get("signal_since"))
        usable_at = _parse_dt(row.get("usable_at"))
        if status == "usable" and usable_at is not None and usable_at < keep_cutoff:
            continue
        if (
            status == "open"
            and flip_at is not None
            and flip_at < keep_cutoff - timedelta(days=lookback_days)
        ):
            # Drop stale open rows that left buy-tier long ago.
            if ticker not in {s.ticker for s in snapshots}:
                continue
        pruned[ticker] = row
    # Ensure current snapshots retained
    for snap in snapshots:
        pruned[snap.ticker] = {**pruned.get(snap.ticker, {}), **snap.to_dict()}
        if snap.key_bodies:
            pruned[snap.ticker]["key_bodies_at"] = pruned[snap.ticker].get("key_bodies_at") or (
                snap.index_at or now.isoformat()
            )

    open_rows = [
        pruned[s.ticker]
        for s in sorted(snapshots, key=lambda r: (-(r.hours_since_flip or 0), r.ticker))
        if not s.usable
    ]
    recently_usable = [
        pruned[s.ticker] for s in sorted(snapshots, key=lambda r: r.ticker) if s.usable
    ]

    warn_open = [
        row
        for row in open_rows
        if float(row.get("hours_since_flip") or 0) >= float(warn_after_hours)
        and str(row.get("blocking_stage") or "") in PATH_INCOMPLETE_STAGES
    ]

    summary = {
        "cohort_count": len(snapshots),
        "open_not_usable": len(open_rows),
        "warn_not_usable": len(warn_open),
        "usable_in_window": len(recently_usable),
        "blocking_stage_counts": {},
    }
    stage_counts: dict[str, int] = {}
    for row in open_rows:
        stage = str(row.get("blocking_stage") or "unknown")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    summary["blocking_stage_counts"] = stage_counts

    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now.isoformat(),
        "lookback_days": int(lookback_days),
        "warn_after_hours": float(warn_after_hours),
        "latest_path": str(latest_path),
        "research_root": str(research_root),
        "summary": summary,
        "open": open_rows,
        "warn_open": warn_open,
        "recently_usable": recently_usable,
        "names": pruned,
        "surface_events": events[-200:],
    }
    if persist:
        store_path = Path(store_path)
        store_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(store_path, payload, compact=False)
    return payload


def format_flip_lag_summary(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "Buy-tier flip → usable lag (observe-only)",
        f"  Updated: {payload.get('updated_at')}",
        f"  Lookback days: {payload.get('lookback_days')}",
        f"  Cohort flips: {summary.get('cohort_count')}",
        f"  Open not yet usable: {summary.get('open_not_usable')}",
        f"  Warn (>= {payload.get('warn_after_hours')}h): {summary.get('warn_not_usable')}",
        f"  Usable in window: {summary.get('usable_in_window')}",
    ]
    stages = summary.get("blocking_stage_counts") or {}
    if stages:
        parts = [f"{k}={v}" for k, v in sorted(stages.items())]
        lines.append(f"  Blocking stages: {', '.join(parts)}")
    warn_open = payload.get("warn_open") or payload.get("open") or []
    if warn_open:
        bits = []
        for row in warn_open[:12]:
            bits.append(
                f"{row.get('ticker')} ({row.get('blocking_stage')}, {row.get('hours_since_flip')}h)"
            )
        lines.append("  Not yet usable: " + ", ".join(bits))
        if len(warn_open) > 12:
            lines.append(f"  … +{len(warn_open) - 12} more")
    return "\n".join(lines)


def ops_finding_from_flip_lag(
    payload: dict[str, Any],
    *,
    warn_after_hours: float | None = None,
) -> dict[str, Any] | None:
    """Build a single ops finding dict when warn cohort is non-empty; else None."""
    threshold = float(
        warn_after_hours
        if warn_after_hours is not None
        else payload.get("warn_after_hours") or DEFAULT_WARN_AFTER_HOURS
    )
    warn_open = list(payload.get("warn_open") or [])
    if not warn_open:
        # Recompute from open if older stores lack warn_open
        warn_open = [
            row
            for row in (payload.get("open") or [])
            if float(row.get("hours_since_flip") or 0) >= threshold
            and str(row.get("blocking_stage") or "") in PATH_INCOMPLETE_STAGES
        ]
    if not warn_open:
        return None
    bits = []
    for row in warn_open[:10]:
        bits.append(
            f"{row.get('ticker')} ({row.get('blocking_stage') or 'unknown'}, "
            f"{row.get('hours_since_flip')}h since flip)"
        )
    extra = len(warn_open) - 10
    summary = (
        f"{len(warn_open)} recent buy-tier flip(s) still missing index / key bodies / "
        f"first memo after ≥{int(threshold)}h (AI-usable path incomplete): " + ", ".join(bits)
    )
    if extra > 0:
        summary += f" (+{extra} more)"
    stages = {}
    for row in warn_open:
        stage = str(row.get("blocking_stage") or "unknown")
        stages[stage] = stages.get(stage, 0) + 1
    stage_bits = ", ".join(f"{k}={v}" for k, v in sorted(stages.items()))
    if stage_bits:
        summary += f". Blocking: {stage_bits}."
    return {
        "severity": "warn",
        "category": "ingest",
        "title": "New buy-tier not yet usable",
        "summary": summary,
        "auto_fixable": False,
    }


__all__ = [
    "BLOCKING_STAGES",
    "DEFAULT_FLIP_LOOKBACK_DAYS",
    "DEFAULT_STORE_PATH",
    "DEFAULT_WARN_AFTER_HOURS",
    "PATH_INCOMPLETE_STAGES",
    "format_flip_lag_summary",
    "load_flip_lag_store",
    "ops_finding_from_flip_lag",
    "select_flip_cohort",
    "snapshot_flip_name",
    "update_buy_tier_flip_lag",
]
