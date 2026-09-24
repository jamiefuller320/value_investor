"""Observe-only lag pin: buy-tier flip → usable clocks (admitted-set).

Tracks buy/strong_buy names from ``signal_since`` through filings index, key
bodies (annual + interim when indexed), and first memo. FTSE live path also
requires ``ai_track_buy_eligible`` (effective buy-tier +
``research_verdict=accumulate``). Admitted library shards use **factory-path**
usable (index → key bodies → memo) only — AI eligibility stays FTSE-scoped.

Universe: FTSE live ``latest.json`` ∪ ``ladder.admitted_learning_markets``.
Does not deepen ingest, rememo, or dispatch engineering. Persists
``docs/data/buy_tier_flip_lag.json`` so cohorts are comparable by ``market_id``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from value_investor.paper_fund import BUY_SIGNALS
from value_investor.research.gap_fill_sources import inspect_local_sources
from value_investor.research.market_store import (
    DEFAULT_LIBRARY_ROOT,
    FTSE_MARKET_ID,
    committed_research_dir,
)
from value_investor.storage import read_json, resolve_json_path, write_json

logger = logging.getLogger(__name__)

DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_RESEARCH_ROOT = Path("docs/data/research")
DEFAULT_MEMO_DIR = Path("docs/research")
DEFAULT_STORE_PATH = Path("docs/data/buy_tier_flip_lag.json")
DEFAULT_POLICY_PATH = Path("docs/data/library/policy.json")

SCHEMA_VERSION = 2
DEFAULT_FLIP_LOOKBACK_DAYS = 21
# Surface ops warn after one weekday ingest day of remaining non-usable.
DEFAULT_WARN_AFTER_HOURS = 24.0
# Keep closed (became usable) rows for cohort review.
DEFAULT_CLOSED_KEEP_DAYS = 90

UsableMode = Literal["ai_eligible", "factory_path"]

BLOCKING_STAGES = (
    "no_index",
    "no_key_bodies",
    "no_memo",
    "no_accumulate_verdict",
)
# Ops warn focuses on factory-path lag (ingest → first memo), not screen names
# whose memo already returned a non-accumulate verdict (FTSE AI gate only).
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


def name_key(market_id: str, ticker: str) -> str:
    """Stable store key so the same ticker can appear on FTSE and a shard."""
    mid = str(market_id or FTSE_MARKET_ID).strip() or FTSE_MARKET_ID
    tick = str(ticker or "").strip().upper()
    return f"{mid}:{tick}"


def _load_latest_reports(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return []
    rows = payload.get("reports") or []
    return [row for row in rows if isinstance(row, dict)]


def _load_library_policy(policy_path: Path) -> dict[str, Any]:
    path = Path(policy_path)
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_library_market_reports(
    library_root: Path,
    market_id: str,
) -> list[dict[str, Any]]:
    """Buy-tier provenance for a library shard: screen-lite → latest.json-shaped reports."""
    try:
        from value_investor.market_paper_adapter import build_market_reports_bundle
    except ImportError:
        logger.warning("market_paper_adapter unavailable — skip library market %s", market_id)
        return []
    try:
        bundle = build_market_reports_bundle(Path(library_root), market_id)
    except FileNotFoundError as exc:
        logger.info("Flip-lag skip %s: missing screen artifacts (%s)", market_id, exc)
        return []
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Flip-lag skip %s: failed to load screen bundle (%s)", market_id, exc)
        return []
    rows = bundle.get("reports") or []
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


@dataclass(frozen=True)
class FlipMarketSource:
    """Per-market screen + research provenance for the flip→usable observe pin."""

    market_id: str
    reports: list[dict[str, Any]]
    research_root: Path
    memo_dir: Path
    usable_mode: UsableMode
    screen_source: str


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
    ai_track_buy_eligible: bool | None
    usable: bool
    usable_at: str | None
    blocking_stage: str | None
    hours_since_flip: float | None
    market_id: str = FTSE_MARKET_ID
    usable_mode: UsableMode = "ai_eligible"
    hours_to_index: float | None = None
    hours_to_key_bodies: float | None = None
    hours_to_first_memo: float | None = None
    hours_to_usable: float | None = None
    status: str = "open"  # open | usable
    stages: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_id": self.market_id,
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
            "usable_mode": self.usable_mode,
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
    usable_mode: UsableMode,
) -> str | None:
    if not has_index:
        return "no_index"
    if not key_bodies:
        return "no_key_bodies"
    if not has_memo:
        return "no_memo"
    if usable_mode == "ai_eligible" and not ai_eligible:
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
        "markets": [],
    }


def _migrate_legacy_name_keys(names: dict[str, Any]) -> dict[str, Any]:
    """Schema v1 keyed by ticker only → v2 ``{market_id}:{ticker}`` (FTSE assumed)."""
    out: dict[str, Any] = {}
    for key, row in names.items():
        if not isinstance(row, dict):
            continue
        text = str(key)
        if ":" in text:
            mid = str(row.get("market_id") or text.split(":", 1)[0] or FTSE_MARKET_ID)
            tick = str(row.get("ticker") or text.split(":", 1)[-1]).strip().upper()
            row = {**row, "market_id": mid, "ticker": tick}
            out[name_key(mid, tick)] = row
            continue
        mid = str(row.get("market_id") or FTSE_MARKET_ID).strip() or FTSE_MARKET_ID
        tick = str(row.get("ticker") or text).strip().upper()
        if not tick:
            continue
        migrated = {**row, "market_id": mid, "ticker": tick}
        migrated.setdefault("usable_mode", "ai_eligible" if mid == FTSE_MARKET_ID else "factory_path")
        out[name_key(mid, tick)] = migrated
    return out


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
    payload.setdefault("markets", [])
    raw_names = dict(payload.get("names") or {})
    if int(payload.get("schema_version") or 1) < 2 or any(
        ":" not in str(k) for k in raw_names
    ):
        payload["names"] = _migrate_legacy_name_keys(raw_names)
        payload["schema_version"] = SCHEMA_VERSION
    return payload


def ftse_flip_source(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    market_id: str = FTSE_MARKET_ID,
) -> FlipMarketSource:
    return FlipMarketSource(
        market_id=str(market_id or FTSE_MARKET_ID),
        reports=_load_latest_reports(Path(latest_path)),
        research_root=Path(research_root),
        memo_dir=Path(memo_dir),
        usable_mode="ai_eligible",
        screen_source=str(latest_path),
    )


def library_flip_source(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
) -> FlipMarketSource | None:
    mid = str(market_id or "").strip()
    if not mid:
        return None
    research_root = committed_research_dir(mid, library_root=library_root)
    reports = _load_library_market_reports(Path(library_root), mid)
    return FlipMarketSource(
        market_id=mid,
        reports=reports,
        research_root=research_root,
        # Library memos live under screen/research/<TICKER>/research.md (alongside JSON).
        memo_dir=research_root,
        usable_mode="factory_path",
        screen_source=str(
            Path(library_root) / "markets" / mid / "screen" / "latest_signals.csv"
        ),
    )


def build_flip_market_sources(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    include_admitted: bool = True,
    markets: Sequence[str] | None = None,
    include_ftse: bool = True,
    ftse_market_id: str = FTSE_MARKET_ID,
) -> list[FlipMarketSource]:
    """FTSE live path plus admitted learning markets (or an explicit market filter)."""
    sources: list[FlipMarketSource] = []
    wanted = [str(m).strip() for m in (markets or []) if str(m).strip()]
    wanted_set = set(wanted)

    if include_ftse and (not wanted_set or ftse_market_id in wanted_set or "ftse" in wanted_set):
        sources.append(
            ftse_flip_source(
                latest_path=latest_path,
                research_root=research_root,
                memo_dir=memo_dir,
                market_id=ftse_market_id,
            )
        )

    if not include_admitted and not wanted_set:
        return sources

    from value_investor.market_shard_admission import admitted_learning_markets_for_policy

    policy = _load_library_policy(Path(policy_path))
    admitted = admitted_learning_markets_for_policy(policy)
    if wanted_set:
        market_ids = [m for m in wanted if m not in {ftse_market_id, "ftse"}]
    else:
        market_ids = list(admitted)

    for mid in market_ids:
        src = library_flip_source(mid, library_root=library_root)
        if src is not None:
            sources.append(src)
    return sources


def snapshot_flip_name(
    report: dict[str, Any],
    *,
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    now: datetime | None = None,
    prior: dict[str, Any] | None = None,
    market_id: str = FTSE_MARKET_ID,
    usable_mode: UsableMode = "ai_eligible",
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
    mid = str(market_id or prior.get("market_id") or FTSE_MARKET_ID).strip() or FTSE_MARKET_ID
    mode: UsableMode = (
        "factory_path"
        if str(usable_mode or prior.get("usable_mode") or "") == "factory_path"
        else "ai_eligible"
    )
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
    memo_md_flat = (Path(memo_dir) / f"{ticker}.md").is_file()
    memo_md_nested = (Path(research_root) / ticker / "research.md").is_file()
    has_memo = has_disk_memo or memo_md_flat or memo_md_nested

    screen_verdict = report.get("research_verdict")
    verdict_str = (
        str(screen_verdict)
        if screen_verdict is not None
        else (disk_verdict if disk_verdict is not None else None)
    )
    ai_eligible = effective in BUY_SIGNALS and verdict_str == "accumulate"
    if mode == "factory_path":
        # Shards: factory path complete; AI paper eligibility stays FTSE-only.
        usable = bool(has_index and key_bodies and has_memo)
        ai_field: bool | None = None
    else:
        usable = bool(has_index and key_bodies and has_memo and ai_eligible)
        ai_field = ai_eligible
    blocking = _blocking_stage(
        has_index=has_index,
        key_bodies=key_bodies,
        has_memo=has_memo,
        ai_eligible=ai_eligible,
        usable_mode=mode,
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
    stages = {
        "index": has_index,
        "key_bodies": key_bodies,
        "first_memo": has_memo,
    }
    if mode == "ai_eligible":
        stages["ai_track_buy_eligible"] = bool(ai_eligible)

    return FlipLagSnapshot(
        market_id=mid,
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
        ai_track_buy_eligible=ai_field,
        usable=usable,
        usable_at=usable_at.isoformat() if usable_at else None,
        usable_mode=mode,
        blocking_stage=None if usable else blocking,
        hours_since_flip=hours_since,
        hours_to_index=_hours_between(flip_at, index_at),
        hours_to_key_bodies=_hours_between(flip_at, key_bodies_at if key_bodies else None),
        hours_to_first_memo=_hours_between(flip_at, memo_at),
        hours_to_usable=_hours_between(flip_at, usable_at),
        status="usable" if usable else "open",
        stages=stages,
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


def _row_label(row: dict[str, Any]) -> str:
    mid = str(row.get("market_id") or "").strip()
    tick = str(row.get("ticker") or "").strip()
    if mid and mid != FTSE_MARKET_ID:
        return f"{mid}/{tick}"
    return tick or "?"


def update_buy_tier_flip_lag(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    memo_dir: Path = DEFAULT_MEMO_DIR,
    store_path: Path = DEFAULT_STORE_PATH,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    include_admitted: bool = True,
    markets: Sequence[str] | None = None,
    include_ftse: bool = True,
    sources: Sequence[FlipMarketSource] | None = None,
    lookback_days: int = DEFAULT_FLIP_LOOKBACK_DAYS,
    warn_after_hours: float = DEFAULT_WARN_AFTER_HOURS,
    closed_keep_days: int = DEFAULT_CLOSED_KEEP_DAYS,
    now: datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Refresh observe store from FTSE + admitted screens; optionally persist."""
    now = now or datetime.now(UTC)
    store = load_flip_lag_store(store_path)
    prior_names: dict[str, Any] = dict(store.get("names") or {})
    events: list[dict[str, Any]] = list(store.get("surface_events") or [])

    active_sources = list(
        sources
        if sources is not None
        else build_flip_market_sources(
            latest_path=latest_path,
            research_root=research_root,
            memo_dir=memo_dir,
            library_root=library_root,
            policy_path=policy_path,
            include_admitted=include_admitted,
            markets=markets,
            include_ftse=include_ftse,
        )
    )

    snapshots: list[FlipLagSnapshot] = []
    market_meta: list[dict[str, Any]] = []

    for source in active_sources:
        cohort_rows = select_flip_cohort(
            source.reports, lookback_days=lookback_days, now=now
        )
        market_meta.append(
            {
                "market_id": source.market_id,
                "usable_mode": source.usable_mode,
                "screen_source": source.screen_source,
                "research_root": str(source.research_root),
                "cohort_count": len(cohort_rows),
            }
        )
        for row in cohort_rows:
            ticker = str(row.get("ticker") or "").strip().upper()
            key = name_key(source.market_id, ticker)
            prior = dict(prior_names.get(key) or {})
            snap = snapshot_flip_name(
                row,
                research_root=source.research_root,
                memo_dir=source.memo_dir,
                now=now,
                prior=prior,
                market_id=source.market_id,
                usable_mode=source.usable_mode,
            )
            if snap is None:
                continue
            if key not in prior_names:
                events.append(
                    {
                        "event": "flip_surfaced",
                        "market_id": snap.market_id,
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
                        "market_id": snap.market_id,
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
            prior_names[key] = prior_payload
            snapshots.append(snap)

    # Age out very old closed names still in the map but outside lookback.
    keep_cutoff = now - timedelta(days=max(1, int(closed_keep_days)))
    active_keys = {name_key(s.market_id, s.ticker) for s in snapshots}
    pruned: dict[str, Any] = {}
    for key, row in prior_names.items():
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
            if key not in active_keys:
                continue
        pruned[key] = row
    # Ensure current snapshots retained
    for snap in snapshots:
        key = name_key(snap.market_id, snap.ticker)
        pruned[key] = {**pruned.get(key, {}), **snap.to_dict()}
        if snap.key_bodies:
            pruned[key]["key_bodies_at"] = pruned[key].get("key_bodies_at") or (
                snap.index_at or now.isoformat()
            )

    open_rows = [
        pruned[name_key(s.market_id, s.ticker)]
        for s in sorted(
            snapshots,
            key=lambda r: (-(r.hours_since_flip or 0), r.market_id, r.ticker),
        )
        if not s.usable
    ]
    recently_usable = [
        pruned[name_key(s.market_id, s.ticker)]
        for s in sorted(snapshots, key=lambda r: (r.market_id, r.ticker))
        if s.usable
    ]

    warn_open = [
        row
        for row in open_rows
        if float(row.get("hours_since_flip") or 0) >= float(warn_after_hours)
        and str(row.get("blocking_stage") or "") in PATH_INCOMPLETE_STAGES
    ]

    by_market: dict[str, dict[str, int]] = {}
    for snap in snapshots:
        bucket = by_market.setdefault(
            snap.market_id,
            {
                "cohort_count": 0,
                "open_not_usable": 0,
                "warn_not_usable": 0,
                "usable_in_window": 0,
            },
        )
        bucket["cohort_count"] += 1
        if snap.usable:
            bucket["usable_in_window"] += 1
        else:
            bucket["open_not_usable"] += 1
    for row in warn_open:
        mid = str(row.get("market_id") or FTSE_MARKET_ID)
        by_market.setdefault(
            mid,
            {
                "cohort_count": 0,
                "open_not_usable": 0,
                "warn_not_usable": 0,
                "usable_in_window": 0,
            },
        )
        by_market[mid]["warn_not_usable"] = by_market[mid].get("warn_not_usable", 0) + 1

    summary = {
        "cohort_count": len(snapshots),
        "open_not_usable": len(open_rows),
        "warn_not_usable": len(warn_open),
        "usable_in_window": len(recently_usable),
        "blocking_stage_counts": {},
        "by_market": by_market,
        "market_count": len(active_sources),
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
        "include_admitted": bool(include_admitted if sources is None else True),
        "markets": market_meta,
        "latest_path": str(latest_path),
        "research_root": str(research_root),
        "library_root": str(library_root),
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
        "Buy-tier flip → usable lag (observe-only, admitted-set)",
        f"  Updated: {payload.get('updated_at')}",
        f"  Lookback days: {payload.get('lookback_days')}",
        f"  Markets: {summary.get('market_count')}",
        f"  Cohort flips: {summary.get('cohort_count')}",
        f"  Open not yet usable: {summary.get('open_not_usable')}",
        f"  Warn (>= {payload.get('warn_after_hours')}h path-incomplete): "
        f"{summary.get('warn_not_usable')}",
        f"  Usable in window: {summary.get('usable_in_window')}",
    ]
    by_market = summary.get("by_market") or {}
    if by_market:
        bits = []
        for mid in sorted(by_market):
            b = by_market[mid]
            bits.append(
                f"{mid}: cohort={b.get('cohort_count')} open={b.get('open_not_usable')} "
                f"warn={b.get('warn_not_usable')}"
            )
        lines.append("  By market: " + "; ".join(bits))
    stages = summary.get("blocking_stage_counts") or {}
    if stages:
        parts = [f"{k}={v}" for k, v in sorted(stages.items())]
        lines.append(f"  Blocking stages: {', '.join(parts)}")
    warn_open = payload.get("warn_open") or payload.get("open") or []
    if warn_open:
        bits = []
        for row in warn_open[:12]:
            bits.append(
                f"{_row_label(row)} ({row.get('blocking_stage')}, {row.get('hours_since_flip')}h)"
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
            f"{_row_label(row)} ({row.get('blocking_stage') or 'unknown'}, "
            f"{row.get('hours_since_flip')}h since flip)"
        )
    extra = len(warn_open) - 10
    market_ids = sorted(
        {str(row.get("market_id") or FTSE_MARKET_ID) for row in warn_open}
    )
    market_bit = ", ".join(market_ids[:6])
    if len(market_ids) > 6:
        market_bit += f" (+{len(market_ids) - 6} more)"
    summary = (
        f"{len(warn_open)} recent buy-tier flip(s) still missing index / key bodies / "
        f"first memo after ≥{int(threshold)}h (path incomplete) across {market_bit}: "
        + ", ".join(bits)
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
    "DEFAULT_LIBRARY_ROOT",
    "DEFAULT_POLICY_PATH",
    "DEFAULT_STORE_PATH",
    "DEFAULT_WARN_AFTER_HOURS",
    "FTSE_MARKET_ID",
    "FlipLagSnapshot",
    "FlipMarketSource",
    "PATH_INCOMPLETE_STAGES",
    "SCHEMA_VERSION",
    "build_flip_market_sources",
    "format_flip_lag_summary",
    "ftse_flip_source",
    "library_flip_source",
    "load_flip_lag_store",
    "name_key",
    "ops_finding_from_flip_lag",
    "select_flip_cohort",
    "snapshot_flip_name",
    "update_buy_tier_flip_lag",
]
