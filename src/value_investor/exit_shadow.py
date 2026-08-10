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
        )


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


def ingest_new_exits(
    fund: PaperFund,
    store: dict[str, Any],
    *,
    track_id: str,
    config: ExitShadowConfig | None = None,
) -> int:
    """Append shadow records for sell trades not yet in the store."""
    cfg = config or ExitShadowConfig()
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
        )
        records.append(record.to_dict())
        known.add(trade_id)
        added += 1

    store["records"] = records
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


def build_exit_shadow_review(store: dict[str, Any], *, track_id: str) -> dict[str, Any]:
    records = [ExitShadowRecord.from_dict(row) for row in (store.get("records") or [])]
    open_records = [r for r in records if r.status == "open"]
    closed_records = [r for r in records if r.status == "closed"]

    def _summarize(rows: list[ExitShadowRecord]) -> dict[str, Any]:
        if not rows:
            return {"count": 0}
        verdicts: dict[str, int] = {}
        peaks: list[float] = []
        troughs: list[float] = []
        finals: list[float] = []
        for row in rows:
            if row.verdict:
                verdicts[row.verdict] = verdicts.get(row.verdict, 0) + 1
            peaks.append(row.peak_since_exit_pct)
            troughs.append(row.trough_since_exit_pct)
            if row.last_return_since_exit_pct is not None:
                finals.append(row.last_return_since_exit_pct)
        return {
            "count": len(rows),
            "verdicts": verdicts,
            "avg_peak_since_exit_pct": round(sum(peaks) / len(peaks), 4) if peaks else None,
            "avg_trough_since_exit_pct": round(sum(troughs) / len(troughs), 4) if troughs else None,
            "avg_final_return_since_exit_pct": round(sum(finals) / len(finals), 4)
            if finals
            else None,
        }

    by_kind: dict[str, Any] = {}
    for kind in ("grace", "screen_rotation", "stop", "take_profit", "other"):
        kind_rows = [r for r in closed_records if r.exit_kind == kind]
        if kind_rows:
            by_kind[kind] = _summarize(kind_rows)

    grace_closed = [r for r in closed_records if r.exit_kind == "grace"]
    rotation_closed = [r for r in closed_records if r.exit_kind == "screen_rotation"]

    note = (
        "Observe-only shadow cohort — scores post-exit price paths for learning; "
        "does not auto-tune momentum grace knobs yet."
    )
    if len(closed_records) < 5:
        note += f" Only {len(closed_records)} closed exit(s) so far; wait for a thicker cohort."

    return {
        "schema_version": 1,
        "track_id": track_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "open_count": len(open_records),
        "closed_count": len(closed_records),
        "by_exit_kind": by_kind,
        "grace_vs_rotation": {
            "grace_closed": _summarize(grace_closed),
            "screen_rotation_closed": _summarize(rotation_closed),
        },
        "note": note,
    }


def load_exit_shadow(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "track_id": "", "records": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"schema_version": 1, "track_id": "", "records": []}
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
) -> dict[str, Any]:
    """Ingest new sells, score open cohorts, and write per-track review artifacts."""
    output_dir = Path(output_dir)
    cfg = config or ExitShadowConfig()
    shadow_path = output_dir / SHADOW_FILENAME
    review_path = output_dir / REVIEW_FILENAME

    store = load_exit_shadow(shadow_path)
    store["schema_version"] = 1
    store["track_id"] = track_id
    store["updated_at"] = datetime.now(UTC).isoformat()

    added = ingest_new_exits(fund, store, track_id=track_id, config=cfg)
    scored = update_shadow_scores(store, prices_by_ticker, as_of=as_of, config=cfg)
    review = build_exit_shadow_review(store, track_id=track_id)
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

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "tracks": tracks,
        "note": (
            "Post-exit shadow learning (observe-only). Compare grace vs screen_rotation "
            "once closed cohorts thicken; knob auto-tune is deferred."
        ),
    }
