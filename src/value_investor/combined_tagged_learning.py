"""Observe-only combined vs per-market exit_shadow join (tagged, not one book).

Concat on ``track_id`` alone would collide: live FTSE, euro_depth, and sp500 all
use ``buy_tier_level``. This producer stamps/reads ``market_id`` and rolls up
open/closed / by_exit_kind / grace_vs_rotation plus a first-episode strip.

Does **not** merge NAV, apply knobs, or change live exit policy (N23).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.exit_shadow import (
    SHADOW_FILENAME,
    ExitShadowRecord,
    _cohort_block,
    canonical_exit_shadow_market_id,
    load_exit_shadow,
    tagged_join_key,
)
from value_investor.market_shard_admission import admitted_learning_markets_for_policy
from value_investor.market_shard_phases import shard_root_for_market
from value_investor.market_trading_costs import LIVE_PAPER_MARKET_ID
from value_investor.storage import read_json, write_json

SCHEMA_VERSION = 1
DEFAULT_STORE_PATH = Path("docs/data/combined_tagged_learning.json")
DEFAULT_POLICY_PATH = Path("docs/data/library/policy.json")
DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
FINDING_TITLE = "Combined tagged learning store stale"
DEFAULT_STALE_AFTER_HOURS = 36.0


def _safe_read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iter_exit_shadow_files(root: Path, *, skip_markets: bool) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    found: list[Path] = []
    for path in root.rglob(SHADOW_FILENAME):
        if not path.is_file():
            continue
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if skip_markets and "markets" in rel_parts:
            continue
        found.append(path)
    return sorted(found)


def _track_id_from_path(path: Path, book_root: Path) -> str:
    parent = path.parent
    if parent == Path(book_root):
        return "rules"
    return parent.name


def _records_from_store(
    store: dict[str, Any],
    *,
    market_id: str,
    track_id: str,
) -> tuple[list[ExitShadowRecord], int]:
    """Parse records; infer tags without rewriting paper books."""
    mid = canonical_exit_shadow_market_id(market_id or store.get("market_id"))
    tid = str(store.get("track_id") or track_id or "rules")
    missing_market = 0
    parsed: list[ExitShadowRecord] = []
    raw_rows = [row for row in (store.get("records") or []) if isinstance(row, dict)]
    for row in raw_rows:
        if not str(row.get("market_id") or "").strip():
            missing_market += 1
        record = ExitShadowRecord.from_dict({**row, "track_id": row.get("track_id") or tid})
        if not record.market_id:
            record.market_id = mid
        if not record.track_id:
            record.track_id = tid
        parsed.append(record)
    # Recompute episode identity in-memory so unstamped books still join cleanly.
    by_ticker: dict[str, list[int]] = {}
    for index, record in enumerate(parsed):
        by_ticker.setdefault(record.ticker, []).append(index)
    for idxs in by_ticker.values():
        ordered = sorted(
            idxs,
            key=lambda i: (parsed[i].exited_at or "", parsed[i].trade_id),
        )
        for episode, i in enumerate(ordered, start=1):
            record = parsed[i]
            record.episode_index = episode
            record.first_episode = episode == 1
            record.join_key = tagged_join_key(
                market_id=record.market_id or mid,
                track_id=record.track_id or tid,
                ticker=record.ticker,
                episode_index=episode,
            )
    return parsed, missing_market


def _empty_cohort() -> dict[str, Any]:
    return _cohort_block([])


def _book_summary(
    records: list[ExitShadowRecord],
    *,
    market_id: str,
    track_id: str,
) -> dict[str, Any]:
    first = [r for r in records if r.first_episode]
    return {
        "market_id": market_id,
        "track_id": track_id,
        "record_count": len(records),
        **_cohort_block(records),
        "first_episode": _cohort_block(first),
    }


def discover_tagged_books(
    *,
    paper_root: Path = DEFAULT_PAPER_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    markets: list[str] | None = None,
) -> list[tuple[str, Path, bool]]:
    """(market_id, book_root, is_shard) for live FTSE + shard markets."""
    paper_root = Path(paper_root)
    policy = _safe_read(Path(policy_path)) or {}
    admitted = admitted_learning_markets_for_policy(policy)
    wanted = list(markets) if markets is not None else [LIVE_PAPER_MARKET_ID, *admitted]
    ordered: list[str] = []
    seen: set[str] = set()
    for mid in wanted:
        canon = canonical_exit_shadow_market_id(mid)
        if canon in seen:
            continue
        seen.add(canon)
        ordered.append(canon)
    if markets is None:
        shard_base = paper_root / "markets"
        if shard_base.is_dir():
            for child in sorted(p.name for p in shard_base.iterdir() if p.is_dir()):
                canon = canonical_exit_shadow_market_id(child)
                if canon not in seen:
                    seen.add(canon)
                    ordered.append(canon)
    shard_base = paper_root / "markets"
    books: list[tuple[str, Path, bool]] = []
    for mid in ordered:
        if mid == LIVE_PAPER_MARKET_ID:
            books.append((mid, paper_root, False))
        else:
            books.append((mid, shard_root_for_market(mid, base=shard_base), True))
    return books


def collect_tagged_exit_shadows(
    *,
    paper_root: Path = DEFAULT_PAPER_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    markets: list[str] | None = None,
) -> dict[str, Any]:
    books = discover_tagged_books(paper_root=paper_root, policy_path=policy_path, markets=markets)
    by_market: dict[str, Any] = {}
    all_records: list[ExitShadowRecord] = []
    missing_market_id = 0
    source_files = 0
    for market_id, root, is_shard in books:
        tracks: dict[str, Any] = {}
        market_records: list[ExitShadowRecord] = []
        for path in _iter_exit_shadow_files(root, skip_markets=not is_shard):
            store = load_exit_shadow(path)
            track_id = str(store.get("track_id") or _track_id_from_path(path, root))
            records, missing = _records_from_store(store, market_id=market_id, track_id=track_id)
            missing_market_id += missing
            source_files += 1
            tracks[track_id] = {
                "path": path.as_posix(),
                **_book_summary(records, market_id=market_id, track_id=track_id),
            }
            market_records.extend(records)
            all_records.extend(records)
        by_market[market_id] = {
            "market_id": market_id,
            "is_live": market_id == LIVE_PAPER_MARKET_ID,
            "book_root": root.as_posix(),
            "track_count": len(tracks),
            "tracks": tracks,
            **_book_summary(market_records, market_id=market_id, track_id="*"),
        }
        # Drop misleading track_id on the market rollup.
        by_market[market_id].pop("track_id", None)

    combined = _book_summary(all_records, market_id="combined", track_id="*")
    combined.pop("track_id", None)
    combined["market_id"] = "combined"
    join_keys = [r.join_key for r in all_records if r.join_key]
    return {
        "by_market": by_market,
        "combined": combined,
        "source_files": source_files,
        "record_count": len(all_records),
        "join_key_count": len(join_keys),
        "join_key_unique": len(set(join_keys)),
        "source_records_missing_market_id": missing_market_id,
        "markets": sorted(by_market),
    }


def build_combined_tagged_learning(
    *,
    paper_root: Path = DEFAULT_PAPER_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    markets: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    clock = now or datetime.now(UTC)
    collected = collect_tagged_exit_shadows(
        paper_root=paper_root, policy_path=policy_path, markets=markets
    )
    combined = _as_dict(collected.get("combined"))
    first = _as_dict(combined.get("first_episode"))
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": clock.isoformat(),
        "observe_only": True,
        "capital_epoch": None,
        "live_market_id": LIVE_PAPER_MARKET_ID,
        "note": (
            "Tagged analysis layer only. Independent paper books stay separate — "
            "no shared NAV, no knob apply, no live exit-policy change (N23). "
            "Zero closed N is expected until 84d shadows thicken. First-episode "
            "strip drops buy-sell-buy fragments from later stats. Join on "
            "market_id|track_id|ticker|episode_index."
        ),
        "summary": {
            "market_count": len(collected.get("markets") or []),
            "source_files": collected.get("source_files") or 0,
            "record_count": collected.get("record_count") or 0,
            "open_count": combined.get("open_count") or 0,
            "closed_count": combined.get("closed_count") or 0,
            "first_episode_open_count": first.get("open_count") or 0,
            "first_episode_closed_count": first.get("closed_count") or 0,
            "source_records_missing_market_id": collected.get("source_records_missing_market_id")
            or 0,
            "join_key_unique": collected.get("join_key_unique") or 0,
            "warn": False,
        },
        "combined": collected.get("combined") or _empty_cohort(),
        "by_market": collected.get("by_market") or {},
        "markets": collected.get("markets") or [],
    }


def update_combined_tagged_learning(
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    paper_root: Path = DEFAULT_PAPER_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    markets: list[str] | None = None,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = build_combined_tagged_learning(
        paper_root=paper_root,
        policy_path=policy_path,
        markets=markets,
        now=now,
    )
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload, compact=False)
    return payload


def ops_finding_from_combined_tagged_learning(
    payload: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
    store_present: bool = True,
) -> dict[str, Any] | None:
    """Warn only when the observe store is missing/stale — never on zero closed N."""
    if not store_present or not payload:
        return {
            "severity": "warn",
            "category": "paper",
            "title": FINDING_TITLE,
            "summary": (
                "Combined tagged learning store missing — weekday ops-monitor "
                "should publish docs/data/combined_tagged_learning.json. "
                "Observe-only; empty/zero-closed is OK once the store exists."
            ),
            "auto_fixable": False,
        }
    clock = now or datetime.now(UTC)
    as_of = _parse_dt(payload.get("updated_at"))
    if as_of is None:
        return {
            "severity": "warn",
            "category": "paper",
            "title": FINDING_TITLE,
            "summary": "Combined tagged learning store has no usable updated_at.",
            "auto_fixable": False,
        }
    age_h = (clock - as_of).total_seconds() / 3600.0
    if age_h >= stale_after_hours:
        return {
            "severity": "warn",
            "category": "paper",
            "title": FINDING_TITLE,
            "summary": (
                f"Combined tagged learning store last refresh {age_h:.1f}h ago "
                f"(limit {stale_after_hours:.0f}h). Observe-only; do not apply knobs."
            ),
            "auto_fixable": False,
        }
    return None


__all__ = [
    "DEFAULT_PAPER_ROOT",
    "DEFAULT_POLICY_PATH",
    "DEFAULT_STORE_PATH",
    "FINDING_TITLE",
    "SCHEMA_VERSION",
    "build_combined_tagged_learning",
    "collect_tagged_exit_shadows",
    "ops_finding_from_combined_tagged_learning",
    "update_combined_tagged_learning",
]
