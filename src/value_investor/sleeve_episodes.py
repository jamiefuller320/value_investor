"""Dual-path sleeve episodes (observe-only).

Widest lifecycle recording (v2):
  earliest = near-buy (hold + conviction >= pre_buy floor) or buy-tier
  latest   = momentum-grace end + ~1 month (fallback: leave wide zone ×
             confirms + 1 month)

Capital events tag episodes as on_book / off_book / never_funded without
changing paper NAV. Nested counterfactuals use stamped sub-markers.

Does not rewrite live books, knobs, or decision-review apply paths.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from value_investor.momentum_grace import MomentumGraceConfig, grace_expired
from value_investor.paper_fund import BUY_SIGNALS, PaperFund

HARD_EXIT = frozenset({"avoid"})
NEAR_BUY_SIGNALS = frozenset({"hold"})

EPISODES_FILENAME = "sleeve_episodes.json"
REVIEW_FILENAME = "sleeve_episodes_review.json"
ROLLUP_FILENAME = "learning_tracks_sleeve_episodes.json"
SCHEMA_VERSION = 2

CAPITAL_ON_BOOK = "on_book"
CAPITAL_OFF_BOOK = "off_book"
CAPITAL_NEVER_FUNDED = "never_funded"

DEFAULT_EXIT_CONFIRM_SCREENS = 2
DEFAULT_WINDOWS_DAYS = (7, 28, 56, 84)
DEFAULT_NEAR_BUY_MIN_CONVICTION = 0.28  # trajectory pre_buy floor
DEFAULT_POST_GRACE_EXTRA_DAYS = 30  # ~1 calendar month
READINESS_CLOSED_PER_TAG = 15


@dataclass
class SleeveEpisodeConfig:
    """Widest-marker recording policy (nested counterfactuals sit inside)."""

    exit_confirm_screens: int = DEFAULT_EXIT_CONFIRM_SCREENS
    shadow_windows_days: tuple[int, ...] = DEFAULT_WINDOWS_DAYS
    use_adjusted_signal: bool = False
    max_new_episodes_per_pass: int = 40
    near_buy_min_conviction: float = DEFAULT_NEAR_BUY_MIN_CONVICTION
    post_grace_extra_days: int = DEFAULT_POST_GRACE_EXTRA_DAYS
    grace_weeks: int = 6


@dataclass
class SleeveCheckpoint:
    scored_at: str
    days_after_entry: int
    price: float
    return_since_entry_pct: float
    capital_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scored_at": self.scored_at,
            "days_after_entry": self.days_after_entry,
            "price": round(self.price, 4),
            "return_since_entry_pct": round(self.return_since_entry_pct, 4),
            "capital_status": self.capital_status,
        }


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _parse_date(value: str | datetime | None):
    from datetime import date

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text[:10])


def _days_between(start: str, end: str | datetime | None) -> int:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if start_date is None or end_date is None:
        return 0
    return max(0, (end_date - start_date).days)


def _add_days(as_of: str, days: int) -> str:
    base = _parse_date(as_of)
    if base is None:
        return as_of
    return (base + timedelta(days=max(0, int(days)))).isoformat()


def _date_reached(as_of: str, due: str | None) -> bool:
    if not due:
        return False
    a = _parse_date(as_of)
    d = _parse_date(due)
    if a is None or d is None:
        return False
    return a >= d


def _candidate_signal(row: dict[str, Any], *, use_adjusted_signal: bool) -> str:
    if use_adjusted_signal:
        adjusted = row.get("adjusted_signal")
        if adjusted is not None and str(adjusted).strip():
            return str(adjusted)
    return str(row.get("signal") or "")


def _conviction(row: dict[str, Any]) -> float | None:
    raw = row.get("conviction_score")
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _is_near_buy(row: dict[str, Any], *, cfg: SleeveEpisodeConfig, use_adjusted: bool) -> bool:
    signal = _candidate_signal(row, use_adjusted_signal=use_adjusted)
    if signal not in NEAR_BUY_SIGNALS:
        return False
    conv = _conviction(row)
    if conv is None:
        return False
    return conv >= float(cfg.near_buy_min_conviction)


def _is_buy_tier(row: dict[str, Any], *, use_adjusted: bool) -> bool:
    return _candidate_signal(row, use_adjusted_signal=use_adjusted) in BUY_SIGNALS


def _in_wide_zone(row: dict[str, Any], *, cfg: SleeveEpisodeConfig, use_adjusted: bool) -> bool:
    return _is_buy_tier(row, use_adjusted=use_adjusted) or _is_near_buy(
        row, cfg=cfg, use_adjusted=use_adjusted
    )


def _candidate_price(row: dict[str, Any], prices: dict[str, float]) -> float | None:
    ticker = str(row.get("ticker") or "")
    if ticker and ticker in prices and prices[ticker] > 0:
        return float(prices[ticker])
    for key in ("price", "last", "close"):
        raw = row.get(key)
        if raw is None or raw == "":
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def framework_metadata() -> dict[str, Any]:
    return {
        "purpose": (
            "Observe-only dual-path sleeve lab: widest earliest/latest markers with "
            "capital_status tags (on_book / off_book / never_funded). "
            "NAV vs ^FTSE stays on the capital book; sleeve metrics stratify by tag."
        ),
        "schema_version": SCHEMA_VERSION,
        "recording": {
            "earliest_entry": (
                "First pass on near-buy (hold + conviction >= pre_buy floor 0.28) "
                "or buy-tier — whichever comes first"
            ),
            "latest_exit": (
                "Momentum-grace end + post_grace_extra_days (~1 month); "
                "fallback if grace never arms: leave wide zone × exit_confirm_screens "
                "+ post_grace_extra_days; or hard avoid"
            ),
            "sub_markers": [
                "first_near_buy_at",
                "first_buy_tier_at",
                "grace_started_at",
                "grace_ended_at",
                "experimental_exit_due_at",
            ],
            "best_policy": "Nested counterfactual inside the wide episode — not the freeze gate",
        },
        "capital_status": {
            CAPITAL_ON_BOOK: "Crossed threshold and currently (or once) held in the paper fund",
            CAPITAL_OFF_BOOK: "Capital sold while the experimental episode was still open",
            CAPITAL_NEVER_FUNDED: "Crossed threshold but never received paper capital",
        },
        "evidence_validity": (
            "Additive observe store — does not invalidate prior NAV / decision-review / "
            "exit_shadow marks. Those remain valid for what they measured. Do not "
            "back-label historical NAV as dual-path sleeve evidence."
        ),
    }


def empty_store(*, track_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "track_id": track_id,
        "framework": framework_metadata(),
        "open": [],
        "closed": [],
        "updated_at": _utcnow(),
    }


def load_store(path: Path, *, track_id: str) -> dict[str, Any]:
    if not path.exists():
        return empty_store(track_id=track_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return empty_store(track_id=track_id)
    raw.setdefault("schema_version", SCHEMA_VERSION)
    raw.setdefault("track_id", track_id)
    raw.setdefault("framework", framework_metadata())
    raw.setdefault("open", [])
    raw.setdefault("closed", [])
    return raw


def save_store(path: Path, store: dict[str, Any]) -> None:
    store["updated_at"] = _utcnow()
    store["schema_version"] = SCHEMA_VERSION
    store["framework"] = framework_metadata()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def _open_by_ticker(store: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in store.get("open") or []:
        if isinstance(row, dict) and row.get("ticker"):
            out[str(row["ticker"])] = row
    return out


def _new_episode(
    *,
    track_id: str,
    ticker: str,
    name: str,
    as_of: str,
    entry_price: float,
    signal: str,
    conviction: float | None,
    capital_status: str,
    opened_as_near_buy: bool,
    opened_as_buy_tier: bool,
) -> dict[str, Any]:
    return {
        "episode_id": str(uuid4()),
        "track_id": track_id,
        "ticker": ticker,
        "name": name,
        "status": "open",
        "earliest_entry_at": as_of,
        "earliest_entry_price": round(entry_price, 4),
        "earliest_entry_signal": signal,
        "earliest_entry_conviction": conviction,
        "first_near_buy_at": as_of if opened_as_near_buy else None,
        "first_buy_tier_at": as_of if opened_as_buy_tier else None,
        "grace_started_at": None,
        "grace_ended_at": None,
        "experimental_exit_due_at": None,
        "latest_exit_at": None,
        "latest_exit_price": None,
        "latest_exit_reason": None,
        "capital_status": capital_status,
        "on_book_at": as_of if capital_status == CAPITAL_ON_BOOK else None,
        "off_book_at": None,
        "exit_streak": 0,
        "checkpoints": [],
        "peak_return_pct": 0.0,
        "trough_return_pct": 0.0,
        "last_price": round(entry_price, 4),
        "last_return_since_entry_pct": 0.0,
    }


def _apply_mark(episode: dict[str, Any], *, price: float, as_of: str) -> None:
    entry = float(episode.get("earliest_entry_price") or 0)
    if entry <= 0 or price <= 0:
        return
    ret = (price - entry) / entry
    episode["last_price"] = round(price, 4)
    episode["last_return_since_entry_pct"] = round(ret, 4)
    episode["peak_return_pct"] = round(max(float(episode.get("peak_return_pct") or 0), ret), 4)
    episode["trough_return_pct"] = round(min(float(episode.get("trough_return_pct") or 0), ret), 4)
    days = _days_between(str(episode["earliest_entry_at"]), as_of)
    windows = set(DEFAULT_WINDOWS_DAYS)
    existing_days = {
        int(c.get("days_after_entry") or -1)
        for c in (episode.get("checkpoints") or [])
        if isinstance(c, dict)
    }
    for window in sorted(windows):
        if days < window or window in existing_days:
            continue
        episode.setdefault("checkpoints", []).append(
            SleeveCheckpoint(
                scored_at=as_of,
                days_after_entry=window,
                price=price,
                return_since_entry_pct=ret,
                capital_status=str(episode.get("capital_status") or CAPITAL_NEVER_FUNDED),
            ).to_dict()
        )
        existing_days.add(window)


def _close_episode(
    episode: dict[str, Any],
    *,
    as_of: str,
    price: float | None,
    reason: str,
) -> dict[str, Any]:
    episode["status"] = "closed"
    episode["latest_exit_at"] = as_of
    episode["latest_exit_reason"] = reason
    if price is not None and price > 0:
        episode["latest_exit_price"] = round(price, 4)
        _apply_mark(episode, price=price, as_of=as_of)
    episode["closed_at"] = as_of
    return episode


def _stamp_sub_markers(
    episode: dict[str, Any],
    *,
    row: dict[str, Any],
    fund: PaperFund,
    cfg: SleeveEpisodeConfig,
    as_of: str,
) -> None:
    use_adj = cfg.use_adjusted_signal
    if _is_near_buy(row, cfg=cfg, use_adjusted=use_adj) and not episode.get("first_near_buy_at"):
        episode["first_near_buy_at"] = as_of
    if _is_buy_tier(row, use_adjusted=use_adj) and not episode.get("first_buy_tier_at"):
        episode["first_buy_tier_at"] = as_of

    ticker = str(episode.get("ticker") or "")
    position = fund.holdings.get(ticker)
    in_grace = bool(position and position.momentum_grace)
    grace_cfg = MomentumGraceConfig(grace_weeks=int(cfg.grace_weeks))

    if in_grace and not episode.get("grace_started_at"):
        episode["grace_started_at"] = position.grace_started_at or as_of

    if episode.get("grace_started_at") and not episode.get("grace_ended_at"):
        started = str(episode["grace_started_at"])
        expired = grace_expired(started, as_of=as_of, config=grace_cfg)
        if (not in_grace) or expired:
            episode["grace_ended_at"] = as_of
            if not episode.get("experimental_exit_due_at"):
                episode["experimental_exit_due_at"] = _add_days(
                    as_of, int(cfg.post_grace_extra_days)
                )


def _update_trailing_window(
    episode: dict[str, Any],
    *,
    in_wide: bool,
    cfg: SleeveEpisodeConfig,
    as_of: str,
) -> None:
    """Arm experimental_exit_due_at after leaving the wide zone (fallback path)."""
    if in_wide:
        episode["exit_streak"] = 0
        # Re-entry into wide zone cancels a pending fallback due that was not
        # grace-based — keep grace-derived dues.
        if episode.get("experimental_exit_due_at") and not episode.get("grace_ended_at"):
            # Only clear fallback dues (no grace_ended yet).
            if not episode.get("grace_started_at"):
                episode["experimental_exit_due_at"] = None
        return

    streak = int(episode.get("exit_streak") or 0) + 1
    episode["exit_streak"] = streak
    if streak < max(1, int(cfg.exit_confirm_screens)):
        return
    # Grace path arms due via _stamp_sub_markers when grace ends.
    if episode.get("grace_started_at") and not episode.get("grace_ended_at"):
        return
    if episode.get("experimental_exit_due_at"):
        return
    episode["experimental_exit_due_at"] = _add_days(as_of, int(cfg.post_grace_extra_days))


def run_sleeve_episodes_pass(
    *,
    output_dir: Path,
    fund: PaperFund,
    track_id: str,
    candidates: list[dict[str, Any]],
    trades: list[dict[str, Any]] | None = None,
    prices_by_ticker: dict[str, float] | None = None,
    as_of: str | None = None,
    config: SleeveEpisodeConfig | None = None,
) -> dict[str, Any]:
    """Open/update/close widest sleeve episodes and stamp capital_status tags."""
    cfg = config or SleeveEpisodeConfig()
    when = as_of or _utcnow()
    prices = dict(prices_by_ticker or {})
    path = output_dir / EPISODES_FILENAME
    store = load_store(path, track_id=track_id)
    open_map = _open_by_ticker(store)
    held = set(fund.holdings.keys())

    sold_this_pass = {
        str(t.get("ticker"))
        for t in (trades or [])
        if str(t.get("side") or "") == "sell" and t.get("ticker")
    }

    by_ticker = {str(r.get("ticker")): r for r in candidates if r.get("ticker")}
    opened = 0
    closed = 0
    tagged_on_book = 0
    tagged_off_book = 0

    # 1) Open on near-buy or buy-tier (widest earliest), conviction-ranked.
    intake: list[dict[str, Any]] = []
    for row in candidates:
        ticker = str(row.get("ticker") or "")
        if not ticker or ticker in open_map:
            continue
        if not _in_wide_zone(row, cfg=cfg, use_adjusted=cfg.use_adjusted_signal):
            continue
        intake.append(row)

    intake.sort(key=lambda r: float(r.get("conviction_score") or 0), reverse=True)
    for row in intake[: max(0, int(cfg.max_new_episodes_per_pass))]:
        ticker = str(row["ticker"])
        price = _candidate_price(row, prices)
        if price is None:
            continue
        capital = CAPITAL_ON_BOOK if ticker in held else CAPITAL_NEVER_FUNDED
        if capital == CAPITAL_ON_BOOK:
            tagged_on_book += 1
        signal = _candidate_signal(row, use_adjusted_signal=cfg.use_adjusted_signal)
        episode = _new_episode(
            track_id=track_id,
            ticker=ticker,
            name=str(row.get("name") or ticker),
            as_of=when,
            entry_price=price,
            signal=signal,
            conviction=_conviction(row),
            capital_status=capital,
            opened_as_near_buy=_is_near_buy(
                row, cfg=cfg, use_adjusted=cfg.use_adjusted_signal
            ),
            opened_as_buy_tier=_is_buy_tier(row, use_adjusted=cfg.use_adjusted_signal),
        )
        store["open"].append(episode)
        open_map[ticker] = episode
        opened += 1

    # 2) Update open episodes: capital tags, sub-markers, trailing window / close.
    still_open: list[dict[str, Any]] = []
    for episode in list(store.get("open") or []):
        if not isinstance(episode, dict):
            continue
        ticker = str(episode.get("ticker") or "")
        row = by_ticker.get(ticker) or {"ticker": ticker, "signal": "hold"}
        signal = _candidate_signal(row, use_adjusted_signal=cfg.use_adjusted_signal)
        price = _candidate_price(row, prices) or float(episode.get("last_price") or 0) or None

        if ticker in held:
            if episode.get("capital_status") == CAPITAL_NEVER_FUNDED:
                episode["capital_status"] = CAPITAL_ON_BOOK
                episode["on_book_at"] = when
                tagged_on_book += 1
            elif episode.get("capital_status") == CAPITAL_OFF_BOOK:
                episode["capital_status"] = CAPITAL_ON_BOOK
                episode["on_book_at"] = episode.get("on_book_at") or when
                tagged_on_book += 1
        elif ticker in sold_this_pass or (
            episode.get("capital_status") == CAPITAL_ON_BOOK and ticker not in held
        ):
            if episode.get("capital_status") == CAPITAL_ON_BOOK:
                episode["capital_status"] = CAPITAL_OFF_BOOK
                episode["off_book_at"] = when
                tagged_off_book += 1

        if price is not None and price > 0:
            _apply_mark(episode, price=float(price), as_of=when)

        _stamp_sub_markers(episode, row=row, fund=fund, cfg=cfg, as_of=when)

        if signal in HARD_EXIT:
            closed_ep = _close_episode(
                episode,
                as_of=when,
                price=float(price) if price else None,
                reason="hard exit — screen avoid",
            )
            store.setdefault("closed", []).append(closed_ep)
            closed += 1
            continue

        in_wide = _in_wide_zone(row, cfg=cfg, use_adjusted=cfg.use_adjusted_signal)
        _update_trailing_window(episode, in_wide=in_wide, cfg=cfg, as_of=when)

        due = episode.get("experimental_exit_due_at")
        if due and _date_reached(when, str(due)):
            reason = (
                "grace end + post_grace_extra_days — latest experimental exit"
                if episode.get("grace_ended_at")
                else (
                    "left wide zone (near-buy/buy-tier) × confirms + "
                    "post_grace_extra_days — latest experimental exit"
                )
            )
            closed_ep = _close_episode(
                episode,
                as_of=when,
                price=float(price) if price else None,
                reason=reason,
            )
            store.setdefault("closed", []).append(closed_ep)
            closed += 1
            continue

        still_open.append(episode)

    store["open"] = still_open
    save_store(path, store)
    review = build_review(store, track_id=track_id, as_of=when)
    review["ingested_this_pass"] = {
        "opened": opened,
        "closed": closed,
        "tagged_on_book": tagged_on_book,
        "tagged_off_book": tagged_off_book,
    }
    (output_dir / REVIEW_FILENAME).write_text(
        json.dumps(review, indent=2) + "\n",
        encoding="utf-8",
    )
    return review


def build_review(
    store: dict[str, Any],
    *,
    track_id: str,
    as_of: str | None = None,
) -> dict[str, Any]:
    open_rows = [r for r in (store.get("open") or []) if isinstance(r, dict)]
    closed_rows = [r for r in (store.get("closed") or []) if isinstance(r, dict)]

    def _by_status(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = {
            CAPITAL_ON_BOOK: 0,
            CAPITAL_OFF_BOOK: 0,
            CAPITAL_NEVER_FUNDED: 0,
        }
        for row in rows:
            status = str(row.get("capital_status") or CAPITAL_NEVER_FUNDED)
            if status not in counts:
                counts[status] = 0
            counts[status] += 1
        return counts

    closed_by_tag = _by_status(closed_rows)
    open_by_tag = _by_status(open_rows)
    ready = all(
        int(closed_by_tag.get(tag) or 0) >= READINESS_CLOSED_PER_TAG
        for tag in (CAPITAL_ON_BOOK, CAPITAL_OFF_BOOK, CAPITAL_NEVER_FUNDED)
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "track_id": track_id,
        "generated_at": as_of or _utcnow(),
        "observe_only": True,
        "framework": framework_metadata(),
        "open_count": len(open_rows),
        "closed_count": len(closed_rows),
        "open_by_capital_status": open_by_tag,
        "closed_by_capital_status": closed_by_tag,
        "readiness": {
            "ready_for_sleeve_timing_analysis": ready,
            "closed_per_tag_target": READINESS_CLOSED_PER_TAG,
            "gaps": [
                f"{tag} closed={closed_by_tag.get(tag, 0)} (target>={READINESS_CLOSED_PER_TAG})"
                for tag in (CAPITAL_ON_BOOK, CAPITAL_OFF_BOOK, CAPITAL_NEVER_FUNDED)
                if int(closed_by_tag.get(tag) or 0) < READINESS_CLOSED_PER_TAG
            ],
            "note": (
                "Probability / nested counterfactual promotion waits until each "
                "capital_status tag has a thick closed cohort."
            ),
        },
        "note": (
            "Observe-only — does not change paper capital allocation. "
            "Stratify sleeve returns by capital_status; do not mix into NAV vs ^FTSE."
        ),
    }


def summarize_learning_tracks_sleeve_episodes(base_dir: Path) -> dict[str, Any]:
    """Roll up per-track sleeve episode reviews under a paper_automation root."""
    from value_investor.paper_automation import learning_track_dirs

    tracks: dict[str, Any] = {}
    dirs = learning_track_dirs(base_dir)
    for track_id, track_dir in dirs.items():
        review_path = track_dir / REVIEW_FILENAME
        if review_path.exists():
            try:
                tracks[track_id] = json.loads(review_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                tracks[track_id] = {"track_id": track_id, "error": "invalid_json"}
        else:
            store_path = track_dir / EPISODES_FILENAME
            if store_path.exists():
                store = load_store(store_path, track_id=track_id)
                tracks[track_id] = build_review(store, track_id=track_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utcnow(),
        "observe_only": True,
        "framework": framework_metadata(),
        "tracks": tracks,
    }
