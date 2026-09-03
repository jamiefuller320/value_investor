"""Model-independent dollar-cost-averaging overlay on paper-track entries.

Watches new buys on **every** learning track and scores counterfactual cadences
against the actual lump-sum fill. Does not change live paper books, knobs, or
decision-review apply paths.

Questions:
  - Does spreading a decided notional cut peak adverse exposure (de-risk)?
  - Which cadence (weekly / biweekly / weekday) is effective after extra costs?
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.position_lifecycle import catalog_coverage, lifecycle_catalog, stage_for_phase

EPISODES_FILENAME = "entry_dca_overlay.json"
REVIEW_FILENAME = "entry_dca_overlay_review.json"
ROLLUP_FILENAME = "learning_tracks_entry_dca.json"

DEFAULT_MIN_CLOSED_EPISODES = 12
DEFAULT_MIN_TRACKS = 2
DEFAULT_MIN_MARKS_TO_SCORE = 2


@dataclass(frozen=True)
class DcaCadence:
    id: str
    tranches: int
    interval_days: int
    label: str

    @property
    def window_days(self) -> int:
        if self.tranches <= 1:
            return 0
        return int(self.interval_days) * (int(self.tranches) - 1)


DEFAULT_CADENCES: tuple[DcaCadence, ...] = (
    DcaCadence("lump_sum", tranches=1, interval_days=0, label="100% at decision"),
    DcaCadence("dca_2x_weekly", tranches=2, interval_days=7, label="50/50 over 1 week"),
    DcaCadence("dca_4x_weekly", tranches=4, interval_days=7, label="25% weekly × 4"),
    DcaCadence("dca_2x_biweekly", tranches=2, interval_days=14, label="50/50 over 2 weeks"),
    DcaCadence("dca_5x_weekday", tranches=5, interval_days=1, label="20% over 5 weekday marks"),
)


@dataclass
class EntryDcaConfig:
    cadences: tuple[DcaCadence, ...] = DEFAULT_CADENCES
    min_closed_episodes: int = DEFAULT_MIN_CLOSED_EPISODES
    min_tracks: int = DEFAULT_MIN_TRACKS
    min_marks_to_score: int = DEFAULT_MIN_MARKS_TO_SCORE

    @property
    def max_window_days(self) -> int:
        return max((item.window_days for item in self.cadences), default=0)


def _parse_date(value: str | datetime | date | None) -> date | None:
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


def _days_between(start: str, end: str | datetime | date | None) -> int:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if start_date is None or end_date is None:
        return 0
    return max(0, (end_date - start_date).days)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _held_tickers(holdings_before: list[dict[str, Any]] | dict[str, Any] | None) -> set[str]:
    if not holdings_before:
        return set()
    if isinstance(holdings_before, dict):
        return {str(ticker) for ticker in holdings_before}
    held: set[str] = set()
    for row in holdings_before:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            held.add(ticker)
    return held


def _candidate_map(candidates: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for row in candidates or []:
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            mapped[ticker] = row
            mapped[ticker.upper()] = row
    return mapped


def _episode_id(track_id: str, ticker: str, started_at: str) -> str:
    return f"{track_id}:{ticker}:{started_at}"


ENTRY_KIND_FIRST = "first_entry"
ENTRY_KIND_RECOMMIT = "recommit"


def alumni_tickers_from_trades(trades: list[dict[str, Any]] | None) -> set[str]:
    """Tickers that have already had a sell — prior cycle alumni."""
    alumni: set[str] = set()
    for trade in trades or []:
        if str(trade.get("side") or "").lower() != "sell":
            continue
        ticker = str(trade.get("ticker") or "").strip()
        if ticker:
            alumni.add(ticker)
    return alumni


def _prior_episode_tickers(store: dict[str, Any]) -> set[str]:
    return {
        str(row.get("ticker"))
        for row in (store.get("episodes") or [])
        if isinstance(row, dict) and row.get("ticker")
    }


def _entry_kind_of(episode: dict[str, Any]) -> str:
    kind = str(episode.get("entry_kind") or ENTRY_KIND_FIRST)
    if kind == ENTRY_KIND_RECOMMIT:
        return ENTRY_KIND_RECOMMIT
    return ENTRY_KIND_FIRST


def framework_metadata() -> dict[str, Any]:
    return {
        "purpose": (
            "Observe-only graduated-entry / DCA overlay. Score counterfactual "
            "cadences on the same decided notional across every paper model. "
            "Findings are expected to be largely independent of the underlying "
            "selection model."
        ),
        "lifecycle_stage": "starter (first_entry) or recommit (prior cycle)",
        "questions": [
            "Does spreading a decided notional cut peak adverse £ exposure vs lump-sum?",
            "Which cadence wins after extra buy costs and missed-upside opportunity?",
        ],
        "cadences": [
            {
                "id": item.id,
                "tranches": item.tranches,
                "interval_days": item.interval_days,
                "window_days": item.window_days,
                "label": item.label,
            }
            for item in DEFAULT_CADENCES
        ],
        "outcomes": [
            "fill_advantage_pct (positive = cheaper average fill than lump-sum)",
            "de_risk_gbp (positive = smaller peak unrealized £ loss than lump-sum)",
            "end_value_delta (DCA end value − lump-sum end value after extra costs)",
        ],
        "related_artifacts": [
            "graduated_allocation rebalance_log (starter sizing already live on one track)",
            "hypothesis_integrity (loss tolerance after the sleeve is on)",
            "exit_timing_cohorts (hold vs swap once the position exists)",
            "position_lifecycle catalog (perpetual factor inventory)",
        ],
    }


def load_entry_dca_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "episodes": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"schema_version": 1, "episodes": []}
    raw.setdefault("schema_version", 1)
    raw.setdefault("episodes", [])
    return raw


def save_entry_dca_store(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def ingest_new_entries(
    store: dict[str, Any],
    *,
    track_id: str,
    trades: list[dict[str, Any]],
    holdings_before: list[dict[str, Any]] | dict[str, Any] | None,
    candidates: list[dict[str, Any]] | None,
    buy_cost_pct: float,
    as_of: str,
    lifecycle_phase: str | None = None,
    alumni_tickers: set[str] | None = None,
) -> int:
    """Open an episode for each buy that starts a new sleeve this pass."""
    episodes: list[dict[str, Any]] = list(store.get("episodes") or [])
    open_tickers = {
        str(row.get("ticker")) for row in episodes if str(row.get("status") or "open") == "open"
    }
    held = _held_tickers(holdings_before)
    seen_before = _prior_episode_tickers(store) | set(alumni_tickers or ())
    cmap = _candidate_map(candidates)
    added = 0
    for trade in trades:
        if str(trade.get("side") or "").lower() != "buy":
            continue
        ticker = str(trade.get("ticker") or "").strip()
        if not ticker or ticker in held or ticker in open_tickers:
            continue
        price = _optional_float(trade.get("price"))
        notional = _optional_float(trade.get("gross"))
        shares = _optional_float(trade.get("shares"))
        if price is None or price <= 0 or notional is None or notional <= 0:
            continue
        started_at = str(trade.get("acted_at") or as_of)
        row = cmap.get(ticker) or cmap.get(ticker.upper()) or {}
        recommit = ticker in seen_before
        if lifecycle_phase:
            stage = stage_for_phase(lifecycle_phase)
        else:
            stage = "recommit" if recommit else "starter"
        episodes.append(
            {
                "id": _episode_id(track_id, ticker, started_at),
                "track_id": track_id,
                "ticker": ticker,
                "started_at": started_at,
                "status": "open",
                "lifecycle_stage": stage,
                "entry_kind": ENTRY_KIND_RECOMMIT if recommit else ENTRY_KIND_FIRST,
                "entry_price": round(price, 4),
                "notional": round(notional, 2),
                "shares": round(float(shares or (notional / price)), 6),
                "buy_cost_pct": float(buy_cost_pct),
                "screen_signal": str(row.get("signal") or ""),
                "timing_signal": str(row.get("timing_signal") or ""),
                "conviction_score": _optional_float(row.get("conviction_score")),
                "data_quality_score": _optional_float(row.get("data_quality_score")),
                "marks": [{"as_of": started_at, "price": round(price, 4)}],
            }
        )
        open_tickers.add(ticker)
        added += 1
    store["episodes"] = episodes
    return added


def _append_mark(episode: dict[str, Any], *, as_of: str, price: float) -> bool:
    marks = list(episode.get("marks") or [])
    for existing in marks:
        if str(existing.get("as_of")) == as_of:
            existing["price"] = round(price, 4)
            episode["marks"] = marks
            return False
    marks.append({"as_of": as_of, "price": round(price, 4)})
    episode["marks"] = marks
    return True


def _first_mark_on_or_after(marks: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    for mark in marks:
        mark_date = _parse_date(mark.get("as_of"))
        price = _optional_float(mark.get("price"))
        if mark_date is None or price is None or price <= 0:
            continue
        if mark_date >= target:
            return mark
    return None


def score_cadence(
    episode: dict[str, Any],
    cadence: DcaCadence,
) -> dict[str, Any]:
    """Counterfactual path for one cadence vs the episode's lump-sum fill."""
    entry_price = float(episode["entry_price"])
    notional = float(episode["notional"])
    cost_pct = float(episode.get("buy_cost_pct") or 0.0)
    marks = list(episode.get("marks") or [])
    start = _parse_date(episode.get("started_at"))
    if start is None or entry_price <= 0 or notional <= 0 or not marks:
        return {"id": cadence.id, "scored": False, "reason": "insufficient_data"}

    last_mark = marks[-1]
    last_price = float(last_mark["price"])
    tranche_notional = notional / max(1, cadence.tranches)
    fills: list[dict[str, Any]] = []
    invested = 0.0
    shares = 0.0
    extra_cost = 0.0
    peak_loss = 0.0
    peak_deployed_return = 0.0

    for index in range(cadence.tranches):
        target = start + timedelta(days=cadence.interval_days * index)
        mark = _first_mark_on_or_after(marks, target)
        if mark is None:
            continue
        fill_price = float(mark["price"])
        slice_shares = tranche_notional / fill_price
        shares += slice_shares
        invested += tranche_notional
        if index > 0:
            extra_cost += tranche_notional * cost_pct
        fills.append(
            {
                "tranche": index + 1,
                "as_of": mark.get("as_of"),
                "price": round(fill_price, 4),
            }
        )

        # Peak adverse on capital deployed so far, marked at this fill.
        if shares > 0 and invested > 0:
            avg = invested / shares
            unrealized = shares * (fill_price - avg)
            peak_loss = min(peak_loss, unrealized)
            peak_deployed_return = min(peak_deployed_return, (fill_price - avg) / avg)

    # Walk remaining marks for peak loss after the last fill.
    avg_fill = (invested / shares) if shares > 0 else entry_price
    for mark in marks:
        mark_date = _parse_date(mark.get("as_of"))
        price = float(mark["price"])
        if mark_date is None or shares <= 0:
            continue
        unrealized = shares * (price - avg_fill)
        peak_loss = min(peak_loss, unrealized)
        peak_deployed_return = min(peak_deployed_return, (price - avg_fill) / avg_fill)

    leftover_cash = max(0.0, notional - invested)
    end_value = shares * last_price + leftover_cash - extra_cost
    lump_shares = notional / entry_price
    lump_end = lump_shares * last_price
    fill_advantage = (entry_price - avg_fill) / entry_price if entry_price else 0.0

    return {
        "id": cadence.id,
        "label": cadence.label,
        "scored": True,
        "tranches_filled": len(fills),
        "tranches_target": cadence.tranches,
        "avg_fill": round(avg_fill, 4),
        "fill_advantage_pct": round(fill_advantage, 4),
        "extra_cost": round(extra_cost, 2),
        "leftover_cash": round(leftover_cash, 2),
        "peak_loss_gbp": round(peak_loss, 2),
        "peak_deployed_return": round(peak_deployed_return, 4),
        "end_value": round(end_value, 2),
        "end_value_delta": round(end_value - lump_end, 2),
        "fills": fills,
    }


def score_episode(
    episode: dict[str, Any],
    *,
    cfg: EntryDcaConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or EntryDcaConfig()
    scores = [score_cadence(episode, cadence) for cadence in cfg.cadences]
    scored = [row for row in scores if row.get("scored")]
    lump = next((row for row in scored if row.get("id") == "lump_sum"), None)
    for row in scored:
        if lump is None or row.get("id") == "lump_sum":
            row["de_risk_gbp"] = 0.0
            continue
        row["de_risk_gbp"] = round(
            float(row.get("peak_loss_gbp") or 0.0) - float(lump.get("peak_loss_gbp") or 0.0),
            2,
        )
        # peak_loss is negative; DCA de-risks when its peak is less negative.
        # de_risk_gbp = dca_peak - lump_peak  → positive when |dca| < |lump|?
        # If lump peak_loss = -100 and dca = -40, dca - lump = 60. Positive = de-risked.
        # Wait: dca_peak (-40) - lump_peak (-100) = 60. Yes positive = de-risked.
        # But I wrote dca_peak - lump_peak which is correct.

    dca_rows = [row for row in scored if row.get("id") != "lump_sum"]
    de_risking = [row for row in dca_rows if float(row.get("de_risk_gbp") or 0) > 0]
    pool = de_risking or dca_rows
    winner = None
    if pool:
        winner = max(pool, key=lambda row: float(row.get("end_value_delta") or 0.0))
    return {
        "cadence_scores": scores,
        "winning_cadence": winner.get("id") if winner else None,
        "winning_end_value_delta": winner.get("end_value_delta") if winner else None,
        "any_de_risk": bool(de_risking),
    }


def update_open_episodes(
    store: dict[str, Any],
    *,
    prices_by_ticker: dict[str, float],
    held_tickers: set[str],
    as_of: str,
    cfg: EntryDcaConfig | None = None,
) -> dict[str, int]:
    """Append marks and close episodes that finish their window or are sold."""
    cfg = cfg or EntryDcaConfig()
    marked = 0
    closed = 0
    for episode in store.get("episodes") or []:
        if str(episode.get("status") or "open") != "open":
            continue
        ticker = str(episode.get("ticker") or "")
        price = _optional_float(prices_by_ticker.get(ticker))
        if price is not None and price > 0:
            if _append_mark(episode, as_of=as_of, price=price):
                marked += 1
        elapsed = _days_between(str(episode.get("started_at") or ""), as_of)
        sold = ticker not in held_tickers
        window_done = elapsed >= cfg.max_window_days
        if not (sold or window_done):
            continue
        marks = episode.get("marks") or []
        if len(marks) < cfg.min_marks_to_score:
            episode["status"] = "closed"
            episode["closed_at"] = as_of
            episode["close_reason"] = "insufficient_marks"
            closed += 1
            continue
        summary = score_episode(episode, cfg=cfg)
        episode.update(summary)
        episode["status"] = "closed"
        episode["closed_at"] = as_of
        episode["close_reason"] = (
            "sold_before_window" if sold and not window_done else "window_elapsed"
        )
        closed += 1
    return {"marked": marked, "closed": closed}


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def assess_framework_readiness(
    *,
    closed_episodes: int,
    tracks_with_closed: int,
    cfg: EntryDcaConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or EntryDcaConfig()
    ready = closed_episodes >= cfg.min_closed_episodes and tracks_with_closed >= cfg.min_tracks
    return {
        "ready_for_cadence_analysis": ready,
        "closed_episodes": closed_episodes,
        "closed_target": cfg.min_closed_episodes,
        "tracks_with_closed": tracks_with_closed,
        "tracks_target": cfg.min_tracks,
        "note": (
            "Cadence ranking is collect-only until both gates clear. "
            "Do not promote starter-size or DCA knobs from this overlay alone."
        ),
    }


def build_entry_dca_review(
    store: dict[str, Any],
    *,
    track_id: str,
    cfg: EntryDcaConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or EntryDcaConfig()
    episodes = [row for row in (store.get("episodes") or []) if isinstance(row, dict)]
    open_rows = [row for row in episodes if str(row.get("status") or "open") == "open"]
    closed = [row for row in episodes if str(row.get("status") or "") == "closed"]
    scored = [row for row in closed if row.get("cadence_scores")]
    first_scored = [row for row in scored if _entry_kind_of(row) == ENTRY_KIND_FIRST]
    recommit_scored = [row for row in scored if _entry_kind_of(row) == ENTRY_KIND_RECOMMIT]
    # Cadence ranking uses first-entry only — recommit is a different decision.
    ranked = first_scored
    cadence_stats: dict[str, dict[str, Any]] = {}
    for cadence in cfg.cadences:
        if cadence.id == "lump_sum":
            continue
        deltas = [
            float(score.get("end_value_delta") or 0.0)
            for episode in ranked
            for score in (episode.get("cadence_scores") or [])
            if score.get("id") == cadence.id and score.get("scored")
        ]
        de_risks = [
            float(score.get("de_risk_gbp") or 0.0)
            for episode in ranked
            for score in (episode.get("cadence_scores") or [])
            if score.get("id") == cadence.id and score.get("scored")
        ]
        wins = sum(1 for episode in ranked if episode.get("winning_cadence") == cadence.id)
        cadence_stats[cadence.id] = {
            "label": cadence.label,
            "scored_episodes": len(deltas),
            "mean_end_value_delta": _mean(deltas),
            "mean_de_risk_gbp": _mean(de_risks),
            "de_risk_rate": round(sum(1 for value in de_risks if value > 0) / len(de_risks), 4)
            if de_risks
            else None,
            "win_count": wins,
        }
    winner_counts: dict[str, int] = {}
    for episode in ranked:
        winner = str(episode.get("winning_cadence") or "")
        if winner:
            winner_counts[winner] = winner_counts.get(winner, 0) + 1
    readiness = assess_framework_readiness(
        closed_episodes=len(first_scored),
        tracks_with_closed=1 if first_scored else 0,
        cfg=cfg,
    )
    readiness["first_entry_scored"] = len(first_scored)
    readiness["recommit_scored"] = len(recommit_scored)
    return {
        "schema_version": 1,
        "track_id": track_id,
        "observe_only": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "open_count": len(open_rows),
        "closed_count": len(closed),
        "scored_count": len(first_scored),
        "scored_count_all": len(scored),
        "recommit_scored_count": len(recommit_scored),
        "entry_kind_counts": {
            ENTRY_KIND_FIRST: len(first_scored),
            ENTRY_KIND_RECOMMIT: len(recommit_scored),
        },
        "any_de_risk_count": sum(1 for row in first_scored if row.get("any_de_risk")),
        "winning_cadence_counts": winner_counts,
        "cadence_stats": cadence_stats,
        "readiness": readiness,
        "note": (
            "Counterfactual only — paper books still fill lump-sum (or graduated "
            "starter size). Compare across tracks before treating a cadence as "
            "model-independent."
        ),
    }


def run_entry_dca_overlay_pass(
    *,
    output_dir: Path,
    track_id: str,
    trades: list[dict[str, Any]],
    holdings_before: list[dict[str, Any]] | dict[str, Any] | None,
    holdings_after_tickers: set[str],
    candidates: list[dict[str, Any]] | None,
    prices_by_ticker: dict[str, float],
    buy_cost_pct: float,
    as_of: str,
    cfg: EntryDcaConfig | None = None,
    alumni_tickers: set[str] | None = None,
    history_trades: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ingest new entries, mark open episodes, persist store + review."""
    cfg = cfg or EntryDcaConfig()
    output_dir = Path(output_dir)
    store_path = output_dir / EPISODES_FILENAME
    review_path = output_dir / REVIEW_FILENAME
    store = load_entry_dca_store(store_path)
    alumni = set(alumni_tickers or ())
    alumni |= alumni_tickers_from_trades(history_trades)
    added = ingest_new_entries(
        store,
        track_id=track_id,
        trades=trades,
        holdings_before=holdings_before,
        candidates=candidates,
        buy_cost_pct=buy_cost_pct,
        as_of=as_of,
        alumni_tickers=alumni,
    )
    progress = update_open_episodes(
        store,
        prices_by_ticker=prices_by_ticker,
        held_tickers=holdings_after_tickers,
        as_of=as_of,
        cfg=cfg,
    )
    save_entry_dca_store(store_path, store)
    review = build_entry_dca_review(store, track_id=track_id, cfg=cfg)
    review["ingested_this_pass"] = added
    review["marked_this_pass"] = progress["marked"]
    review["closed_this_pass"] = progress["closed"]
    review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    return review


def summarize_learning_tracks_entry_dca(base_dir: Path) -> dict[str, Any]:
    from value_investor.paper_automation import learning_track_dirs

    base_dir = Path(base_dir)
    tracks: dict[str, Any] = {}
    for track_id, track_dir in learning_track_dirs(base_dir).items():
        review_path = track_dir / REVIEW_FILENAME
        if review_path.exists():
            tracks[track_id] = json.loads(review_path.read_text(encoding="utf-8"))

    closed = 0
    scored = 0
    recommit_scored = 0
    de_risk = 0
    winner_counts: dict[str, int] = {}
    tracks_with_closed = 0
    for review in tracks.values():
        if not isinstance(review, dict):
            continue
        closed += int(review.get("closed_count") or 0)
        scored += int(review.get("scored_count") or 0)
        recommit_scored += int(review.get("recommit_scored_count") or 0)
        de_risk += int(review.get("any_de_risk_count") or 0)
        if int(review.get("scored_count") or 0) > 0:
            tracks_with_closed += 1
        for cadence, count in (review.get("winning_cadence_counts") or {}).items():
            winner_counts[str(cadence)] = winner_counts.get(str(cadence), 0) + int(count)

    leading = None
    if winner_counts:
        leading = max(winner_counts.items(), key=lambda item: item[1])[0]
    model_independent = tracks_with_closed >= DEFAULT_MIN_TRACKS and leading is not None

    readiness = assess_framework_readiness(
        closed_episodes=scored,
        tracks_with_closed=tracks_with_closed,
    )
    catalog = lifecycle_catalog()
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "framework": framework_metadata(),
        "lifecycle_catalog": {
            "purpose": catalog["purpose"],
            "coverage": catalog_coverage(catalog),
        },
        "tracks": tracks,
        "closed_count": closed,
        "scored_count": scored,
        "recommit_scored_count": recommit_scored,
        "any_de_risk_count": de_risk,
        "tracks_with_closed": tracks_with_closed,
        "winning_cadence_counts": winner_counts,
        "leading_cadence": leading,
        "model_independent_hint": model_independent,
        "readiness": readiness,
        "note": (
            "Observe-only DCA / graduated-entry overlay across all paper tracks. "
            "Pair with graduated_allocation (live starter sizing) and "
            "hypothesis_integrity (loss tolerance after entry)."
        ),
    }


__all__ = [
    "DEFAULT_CADENCES",
    "EPISODES_FILENAME",
    "REVIEW_FILENAME",
    "ROLLUP_FILENAME",
    "DcaCadence",
    "EntryDcaConfig",
    "ENTRY_KIND_FIRST",
    "ENTRY_KIND_RECOMMIT",
    "alumni_tickers_from_trades",
    "assess_framework_readiness",
    "build_entry_dca_review",
    "framework_metadata",
    "ingest_new_entries",
    "load_entry_dca_store",
    "run_entry_dca_overlay_pass",
    "score_cadence",
    "score_episode",
    "summarize_learning_tracks_entry_dca",
    "update_open_episodes",
]
