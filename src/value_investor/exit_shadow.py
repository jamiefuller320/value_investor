"""Post-exit shadow cohort for momentum / rules exit-quality learning (observe-only)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from value_investor.paper_fund import PaperFund, PaperTrade

SHADOW_FILENAME = "exit_shadow.json"
REVIEW_FILENAME = "exit_shadow_review.json"
DEFAULT_WINDOWS_DAYS = (7, 28, 56, 84)  # 1, 4, 8, 12 weeks
VERDICT_THRESHOLD = 0.03
SCHEMA_VERSION = 2
EXIT_KINDS = ("grace", "screen_rotation", "stop", "take_profit", "other")


@dataclass
class ExitShadowConfig:
    shadow_windows_days: tuple[int, ...] = DEFAULT_WINDOWS_DAYS
    verdict_threshold: float = VERDICT_THRESHOLD
    record_partial_sells: bool = False


@dataclass
class ShadowCheckpoint:
    scored_at: str
    days_after: int
    price: float
    return_since_exit_pct: float
    peak_since_exit_pct: float
    trough_since_exit_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "scored_at": self.scored_at,
            "days_after": self.days_after,
            "price": round(self.price, 4),
            "return_since_exit_pct": round(self.return_since_exit_pct, 4),
            "peak_since_exit_pct": round(self.peak_since_exit_pct, 4),
            "trough_since_exit_pct": round(self.trough_since_exit_pct, 4),
        }


@dataclass
class ExitShadowRecord:
    trade_id: str
    ticker: str
    name: str
    track_id: str
    exited_at: str
    exit_price: float
    avg_cost: float
    realized_return_pct: float
    exit_reason: str
    exit_kind: str
    momentum_grace: bool = False
    grace_started_at: str | None = None
    status: str = "open"
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    closed_at: str | None = None
    verdict: str | None = None
    peak_since_exit_pct: float = 0.0
    trough_since_exit_pct: float = 0.0
    last_price: float | None = None
    last_return_since_exit_pct: float | None = None
    market_id: str = ""
    episode_index: int = 1
    first_episode: bool = True
    join_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["exit_price"] = round(self.exit_price, 4)
        payload["avg_cost"] = round(self.avg_cost, 4)
        payload["realized_return_pct"] = round(self.realized_return_pct, 4)
        payload["peak_since_exit_pct"] = round(self.peak_since_exit_pct, 4)
        payload["trough_since_exit_pct"] = round(self.trough_since_exit_pct, 4)
        if self.last_price is not None:
            payload["last_price"] = round(self.last_price, 4)
        if self.last_return_since_exit_pct is not None:
            payload["last_return_since_exit_pct"] = round(self.last_return_since_exit_pct, 4)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExitShadowRecord:
        return cls(
            trade_id=str(data["trade_id"]),
            ticker=str(data["ticker"]),
            name=str(data.get("name") or data["ticker"]),
            track_id=str(data.get("track_id") or "rules"),
            exited_at=str(data["exited_at"]),
            exit_price=float(data["exit_price"]),
            avg_cost=float(data.get("avg_cost") or 0),
            realized_return_pct=float(data.get("realized_return_pct") or 0),
            exit_reason=str(data.get("exit_reason") or ""),
            exit_kind=str(data.get("exit_kind") or "other"),
            momentum_grace=bool(data.get("momentum_grace", False)),
            grace_started_at=data.get("grace_started_at"),
            status=str(data.get("status") or "open"),
            checkpoints=list(data.get("checkpoints") or []),
            closed_at=data.get("closed_at"),
            verdict=data.get("verdict"),
            peak_since_exit_pct=float(data.get("peak_since_exit_pct") or 0),
            trough_since_exit_pct=float(data.get("trough_since_exit_pct") or 0),
            last_price=_optional_float(data.get("last_price")),
            last_return_since_exit_pct=_optional_float(data.get("last_return_since_exit_pct")),
            market_id=str(data.get("market_id") or ""),
            episode_index=_episode_index(data.get("episode_index")),
            first_episode=bool(data.get("first_episode", True)),
            join_key=str(data.get("join_key") or ""),
        )


def _episode_index(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, number)


def canonical_exit_shadow_market_id(market_id: str | None) -> str:
    """Live FTSE paper root is not under ``markets/<id>/`` — stamp ``ftse350``."""
    from value_investor.market_trading_costs import normalize_market_id

    return normalize_market_id(market_id)


def tagged_join_key(
    *,
    market_id: str,
    track_id: str,
    ticker: str,
    episode_index: int,
) -> str:
    """Stable concat key so ``track_id=buy_tier_level`` does not collide across books."""
    mid = canonical_exit_shadow_market_id(market_id)
    return f"{mid}|{track_id}|{ticker}|{int(episode_index)}"


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


def _parse_date(value: str | date | datetime | None) -> date | None:
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


def _days_between(start: str, end: str | date | datetime) -> int:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if start_date is None or end_date is None:
        return 0
    return max(0, (end_date - start_date).days)


def classify_exit_kind(*, note: str, momentum_grace: bool) -> str:
    note_l = (note or "").lower()
    if momentum_grace or "grace" in note_l:
        return "grace"
    if "stop" in note_l:
        return "stop"
    if "take-profit" in note_l or "profit" in note_l:
        return "take_profit"
    if "left target" in note_l or "automated exit" in note_l:
        return "screen_rotation"
    return "other"


def verdict_from_path(
    *,
    peak_since_exit_pct: float,
    trough_since_exit_pct: float,
    final_return_pct: float,
    threshold: float = VERDICT_THRESHOLD,
) -> str:
    """Classify a closed shadow cohort (observe-only; not used for live tuning yet)."""
    if peak_since_exit_pct >= threshold and final_return_pct < peak_since_exit_pct * 0.5:
        return "early_exit"
    if trough_since_exit_pct <= -threshold:
        return "good_exit"
    return "neutral"


def _trade_from_fund(trade: PaperTrade | dict[str, Any]) -> dict[str, Any]:
    if isinstance(trade, PaperTrade):
        return trade.to_dict()
    return dict(trade)


def stamp_shadow_identity(
    store: dict[str, Any],
    *,
    market_id: str | None,
    track_id: str,
) -> dict[str, Any]:
    """Stamp ``market_id`` + first-episode identity on every record (observe-only)."""
    mid = canonical_exit_shadow_market_id(market_id)
    tid = str(track_id or store.get("track_id") or "rules")
    store["schema_version"] = SCHEMA_VERSION
    store["market_id"] = mid
    store["track_id"] = tid
    records = [dict(row) for row in (store.get("records") or []) if isinstance(row, dict)]
    grouped: dict[str, list[int]] = {}
    for index, row in enumerate(records):
        ticker = str(row.get("ticker") or "")
        grouped.setdefault(ticker, []).append(index)
    for idxs in grouped.values():
        ordered = sorted(
            idxs,
            key=lambda i: (
                _parse_date(str(records[i].get("exited_at") or "")) or date.min,
                str(records[i].get("trade_id") or ""),
            ),
        )
        for episode, i in enumerate(ordered, start=1):
            row = records[i]
            ticker = str(row.get("ticker") or "")
            row["market_id"] = mid
            row["track_id"] = str(row.get("track_id") or tid)
            row["episode_index"] = episode
            row["first_episode"] = episode == 1
            row["join_key"] = tagged_join_key(
                market_id=mid,
                track_id=str(row["track_id"]),
                ticker=ticker,
                episode_index=episode,
            )
    store["records"] = records
    return store


def ingest_new_exits(
    fund: PaperFund,
    store: dict[str, Any],
    *,
    track_id: str,
    market_id: str | None = None,
    config: ExitShadowConfig | None = None,
) -> int:
    """Append shadow records for sell trades not yet in the store."""
    cfg = config or ExitShadowConfig()
    mid = canonical_exit_shadow_market_id(market_id or store.get("market_id"))
    known = {str(row.get("trade_id")) for row in store.get("records") or []}
    added = 0
    records: list[dict[str, Any]] = list(store.get("records") or [])

    for raw in fund.trades:
        trade = _trade_from_fund(raw)
        if str(trade.get("side")) != "sell":
            continue
        trade_id = str(trade.get("id") or "")
        if not trade_id or trade_id in known:
            continue
        if not cfg.record_partial_sells and not bool(trade.get("position_closed")):
            continue

        exit_price = float(trade.get("price") or 0)
        avg_cost = float(trade.get("avg_cost_at_exit") or 0)
        if exit_price <= 0:
            continue
        realized = ((exit_price - avg_cost) / avg_cost) if avg_cost > 0 else 0.0
        note = str(trade.get("note") or "")
        momentum_grace = bool(trade.get("momentum_grace_at_exit", False))
        record = ExitShadowRecord(
            trade_id=trade_id,
            ticker=str(trade.get("ticker")),
            name=str(trade.get("name") or trade.get("ticker")),
            track_id=track_id,
            exited_at=str(trade.get("acted_at")),
            exit_price=exit_price,
            avg_cost=avg_cost,
            realized_return_pct=realized,
            exit_reason=note,
            exit_kind=classify_exit_kind(note=note, momentum_grace=momentum_grace),
            momentum_grace=momentum_grace,
            grace_started_at=trade.get("grace_started_at_at_exit"),
            market_id=mid,
        )
        records.append(record.to_dict())
        known.add(trade_id)
        added += 1

    store["records"] = records
    stamp_shadow_identity(store, market_id=mid, track_id=track_id)
    return added


def update_shadow_scores(
    store: dict[str, Any],
    prices_by_ticker: dict[str, float],
    *,
    as_of: str | datetime | None = None,
    config: ExitShadowConfig | None = None,
) -> int:
    """Refresh open shadow cohorts with latest marks and window checkpoints."""
    cfg = config or ExitShadowConfig()
    when = as_of or datetime.now(UTC).isoformat()
    when_text = when.isoformat() if isinstance(when, datetime) else str(when)
    updated = 0
    records: list[ExitShadowRecord] = [
        ExitShadowRecord.from_dict(row) for row in (store.get("records") or [])
    ]
    max_window = max(cfg.shadow_windows_days) if cfg.shadow_windows_days else 84

    for record in records:
        if record.status != "open":
            continue
        price = prices_by_ticker.get(record.ticker)
        if price is None or price <= 0:
            continue

        ret = (price - record.exit_price) / record.exit_price if record.exit_price > 0 else 0.0
        record.peak_since_exit_pct = max(record.peak_since_exit_pct, ret)
        record.trough_since_exit_pct = min(record.trough_since_exit_pct, ret)
        record.last_price = price
        record.last_return_since_exit_pct = ret

        scored_days = {int(cp.get("days_after") or 0) for cp in record.checkpoints}
        days_elapsed = _days_between(record.exited_at, when_text)
        for window in cfg.shadow_windows_days:
            if days_elapsed < window or window in scored_days:
                continue
            record.checkpoints.append(
                ShadowCheckpoint(
                    scored_at=when_text,
                    days_after=window,
                    price=price,
                    return_since_exit_pct=ret,
                    peak_since_exit_pct=record.peak_since_exit_pct,
                    trough_since_exit_pct=record.trough_since_exit_pct,
                ).to_dict()
            )
            updated += 1

        if days_elapsed >= max_window:
            record.status = "closed"
            record.closed_at = when_text
            record.verdict = verdict_from_path(
                peak_since_exit_pct=record.peak_since_exit_pct,
                trough_since_exit_pct=record.trough_since_exit_pct,
                final_return_pct=ret,
                threshold=cfg.verdict_threshold,
            )

    store["records"] = [row.to_dict() for row in records]
    return updated


def summarize_shadow_rows(rows: list[ExitShadowRecord] | list[dict[str, Any]]) -> dict[str, Any]:
    parsed: list[ExitShadowRecord] = []
    for row in rows:
        if isinstance(row, ExitShadowRecord):
            parsed.append(row)
        elif isinstance(row, dict):
            parsed.append(ExitShadowRecord.from_dict(row))
    if not parsed:
        return {"count": 0, "verdicts": {}}
    verdicts: dict[str, int] = {}
    peaks: list[float] = []
    troughs: list[float] = []
    finals: list[float] = []
    for row in parsed:
        if row.verdict:
            verdicts[row.verdict] = verdicts.get(row.verdict, 0) + 1
        peaks.append(row.peak_since_exit_pct)
        troughs.append(row.trough_since_exit_pct)
        if row.last_return_since_exit_pct is not None:
            finals.append(row.last_return_since_exit_pct)
    return {
        "count": len(parsed),
        "verdicts": verdicts,
        "avg_peak_since_exit_pct": round(sum(peaks) / len(peaks), 4) if peaks else None,
        "avg_trough_since_exit_pct": round(sum(troughs) / len(troughs), 4) if troughs else None,
        "avg_final_return_since_exit_pct": round(sum(finals) / len(finals), 4) if finals else None,
    }


def _cohort_block(rows: list[ExitShadowRecord]) -> dict[str, Any]:
    open_records = [r for r in rows if r.status == "open"]
    closed_records = [r for r in rows if r.status == "closed"]
    by_kind: dict[str, Any] = {}
    for kind in EXIT_KINDS:
        kind_rows = [r for r in closed_records if r.exit_kind == kind]
        by_kind[kind] = summarize_shadow_rows(kind_rows)
    grace_closed = [r for r in closed_records if r.exit_kind == "grace"]
    rotation_closed = [r for r in closed_records if r.exit_kind == "screen_rotation"]
    return {
        "open_count": len(open_records),
        "closed_count": len(closed_records),
        "by_exit_kind": by_kind,
        "grace_vs_rotation": {
            "grace_closed": summarize_shadow_rows(grace_closed),
            "screen_rotation_closed": summarize_shadow_rows(rotation_closed),
        },
    }


def build_exit_shadow_review(
    store: dict[str, Any],
    *,
    track_id: str,
    market_id: str | None = None,
) -> dict[str, Any]:
    mid = canonical_exit_shadow_market_id(market_id or store.get("market_id"))
    records = [ExitShadowRecord.from_dict(row) for row in (store.get("records") or [])]
    closed_records = [r for r in records if r.status == "closed"]
    first_episode = [r for r in records if r.first_episode]

    note = (
        "Observe-only shadow cohort — scores post-exit price paths for learning; "
        "does not auto-tune momentum grace knobs yet. Tagged by market_id; "
        "first-episode strip excludes buy-sell-buy fragments from later stats."
    )
    if len(closed_records) < 5:
        note += f" Only {len(closed_records)} closed exit(s) so far; wait for a thicker cohort."

    return {
        "schema_version": SCHEMA_VERSION,
        "market_id": mid,
        "track_id": track_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "observe_only": True,
        **_cohort_block(records),
        "first_episode": _cohort_block(first_episode),
        "note": note,
    }


def load_exit_shadow(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "track_id": "", "market_id": "", "records": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"schema_version": SCHEMA_VERSION, "track_id": "", "market_id": "", "records": []}
    data.setdefault("records", [])
    return data


def save_exit_shadow(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def run_exit_shadow_pass(
    *,
    output_dir: Path,
    fund: PaperFund,
    track_id: str,
    prices_by_ticker: dict[str, float],
    as_of: str | None = None,
    config: ExitShadowConfig | None = None,
    market_id: str | None = None,
) -> dict[str, Any]:
    """Ingest new sells, score open cohorts, and write per-track review artifacts."""
    output_dir = Path(output_dir)
    cfg = config or ExitShadowConfig()
    shadow_path = output_dir / SHADOW_FILENAME
    review_path = output_dir / REVIEW_FILENAME
    mid = canonical_exit_shadow_market_id(market_id)

    store = load_exit_shadow(shadow_path)
    store["schema_version"] = SCHEMA_VERSION
    store["track_id"] = track_id
    store["market_id"] = mid
    store["updated_at"] = datetime.now(UTC).isoformat()

    added = ingest_new_exits(fund, store, track_id=track_id, market_id=mid, config=cfg)
    scored = update_shadow_scores(store, prices_by_ticker, as_of=as_of, config=cfg)
    stamp_shadow_identity(store, market_id=mid, track_id=track_id)
    review = build_exit_shadow_review(store, track_id=track_id, market_id=mid)
    review["ingested_this_pass"] = added
    review["checkpoints_added_this_pass"] = scored

    save_exit_shadow(shadow_path, store)
    review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    return review


def summarize_learning_tracks_exit_shadow(base_dir: Path) -> dict[str, Any]:
    """Roll up per-track exit-shadow reviews under the paper-automation root."""
    from value_investor.paper_automation import learning_track_dirs

    base_dir = Path(base_dir)
    tracks: dict[str, Any] = {}
    for track_id, track_dir in learning_track_dirs(base_dir).items():
        review_path = track_dir / REVIEW_FILENAME
        if not review_path.exists():
            continue
        tracks[track_id] = json.loads(review_path.read_text(encoding="utf-8"))

    market_id = ""
    for review in tracks.values():
        if isinstance(review, dict) and review.get("market_id"):
            market_id = str(review.get("market_id") or "")
            break
    if not market_id:
        from value_investor.paper_automation import infer_paper_market_id

        market_id = canonical_exit_shadow_market_id(infer_paper_market_id(base_dir))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "market_id": market_id,
        "observe_only": True,
        "tracks": tracks,
        "note": (
            "Post-exit shadow learning (observe-only). Compare grace vs screen_rotation "
            "once closed cohorts thicken; knob auto-tune is deferred. "
            "Tagged market_id is required for a cross-market join — do not concat on "
            "track_id alone."
        ),
    }
