"""Per-market dashboard board: screen/paper names in visual lifecycle columns.

Observe-only. Does not mutate paper books or implement the deferred L177
per-holding state machine — it classifies existing screen + fund artifacts.
"""

from __future__ import annotations

import csv
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.capital_allocation import classify_lifecycle_phase
from value_investor.data_library import DEFAULT_LIBRARY_ROOT, MARKET_REGISTRY
from value_investor.library_near_miss_watch import DEFAULT_PRE_BUY_CONVICTION, NEAR_MISS_FILENAME
from value_investor.library_screen import screen_dir_for
from value_investor.market_shard_phases import DEFAULT_SHARD_ROOT, shard_root_for_market
from value_investor.market_status import LIVE_MARKET_ID
from value_investor.paper_automation import (
    BUY_TIER_LEVEL_TRACK_ID,
    CONFIG_FILENAME,
    FUND_FILENAME,
    LEARNING_TRACK_IDS,
    learning_track_dirs,
)
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.position_lifecycle import (
    BOARD_COLUMN_IDS,
    STARTER_RATIO_CEILING,
    board_column_defs,
    stage_for_phase,
)
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_LIFECYCLE_BOARD_PATH = Path("docs/data/lifecycle_board.json")
DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_EXPERIMENT_ASSESSMENT_PATH = Path("docs/data/experiment_assessment.json")

JUST_BOUGHT_DAYS = 14
JUST_SOLD_DAYS = 14
POST_SALE_DAYS = 84

# Time-in-column heatmap (held: days since open; sold: days since close).
TENURE_LONG_DAYS = 56  # 8 weeks
TENURE_BANDS: tuple[tuple[int | None, str], ...] = (
    (7, "fresh"),
    (21, "recent"),
    (42, "aging"),
    (TENURE_LONG_DAYS, "stale"),
    (None, "long"),
)
HELD_TENURE_COLUMNS = frozenset({"just_bought", "growth", "near_sell"})
SOLD_TENURE_COLUMNS = frozenset({"just_sold", "post_sale"})

COLUMN_SHOW_CAPS = {
    "not_buy_tier": 16,
    "not_now": 32,
    "near_buy": 32,
    "just_bought": 40,
    "growth": 40,
    "near_sell": 40,
    "just_sold": 32,
    "post_sale": 32,
}

SCREEN_COLUMN_IDS = ("not_buy_tier", "not_now", "near_buy")
POSITION_COLUMN_IDS = ("just_bought", "growth", "near_sell", "just_sold", "post_sale")

MAIN_TRACK_IDS = tuple(
    track_id
    for track_id in LEARNING_TRACK_IDS
    if track_id
    not in {
        "ai_judgment_calibrated",
    }
)

_SHADOW_TRACK_PREFIXES = ("ai_judgment_calibrated", "exclusion_", "fair_cost_")


def _safe_read(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:  # noqa: BLE001 — dashboard must still assemble
        return None


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def tenure_band_for_days(days: float | None) -> str | None:
    """Map days-in-column onto the green→red heatmap band."""
    if days is None:
        return None
    try:
        elapsed = max(0.0, float(days))
    except (TypeError, ValueError):
        return None
    for ceiling, name in TENURE_BANDS:
        if ceiling is None or elapsed <= ceiling:
            return name
    return "long"


def tenure_scale() -> dict[str, Any]:
    return {
        "long_days": TENURE_LONG_DAYS,
        "bands": [
            {"id": "fresh", "max_days": 7, "label": "≤7d new"},
            {"id": "recent", "max_days": 21, "label": "≤3w"},
            {"id": "aging", "max_days": 42, "label": "≤6w"},
            {"id": "stale", "max_days": TENURE_LONG_DAYS, "label": "≤8w"},
            {"id": "long", "max_days": None, "label": ">8w"},
        ],
        "note": (
            "Held columns use days since opened_at. Sold columns use days since "
            "the closing mark. Screen columns (not buy-tier / not now / near buy) "
            "use days since signal_since (fallback: weeks_at_signal × 7)."
        ),
    }


def _days_since(value: str | None, now: datetime) -> float | None:
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    return (now - parsed).total_seconds() / 86400.0


def _signal(row: dict[str, Any]) -> str:
    adjusted = str(row.get("adjusted_signal") or "").strip().lower()
    if adjusted:
        return adjusted
    return str(row.get("signal") or "").strip().lower()


def _timing(row: dict[str, Any]) -> str:
    return str(row.get("timing_signal") or "").strip().lower()


def _conviction(row: dict[str, Any]) -> float:
    for key in ("conviction_score", "composite_score"):
        value = _optional_float(row.get(key))
        if value is not None:
            return value
    return 0.0


def _ticker(row: dict[str, Any] | str | None) -> str:
    if isinstance(row, str):
        return row.strip()
    if not isinstance(row, dict):
        return ""
    return str(row.get("ticker") or "").strip()


def classify_board_column(
    *,
    held: bool,
    signal: str = "",
    timing: str = "",
    conviction: float = 0.0,
    phase: str | None = None,
    opened_at: str | None = None,
    sold_at: str | None = None,
    cooldown: bool = False,
    now: datetime | None = None,
    just_bought_days: int = JUST_BOUGHT_DAYS,
    just_sold_days: int = JUST_SOLD_DAYS,
    post_sale_days: int = POST_SALE_DAYS,
    near_buy_conviction: float = DEFAULT_PRE_BUY_CONVICTION,
) -> str:
    """Place one name on a visual board column. Held/sold beat screen labels."""
    as_of = now or datetime.now(UTC)
    signal_key = str(signal or "").strip().lower()
    timing_key = str(timing or "").strip().lower()
    phase_key = str(phase or "")
    stage = stage_for_phase(phase_key)

    if held:
        if stage in {"harvest", "grace", "exit"}:
            return "near_sell"
        opened_days = _days_since(opened_at, as_of)
        if stage == "starter" or (opened_days is not None and opened_days <= just_bought_days):
            return "just_bought"
        return "growth"

    sold_days = _days_since(sold_at, as_of)
    if sold_days is not None and sold_days <= just_sold_days:
        return "just_sold"
    if cooldown or (sold_days is not None and sold_days <= post_sale_days):
        return "post_sale"

    if phase_key == "prospect_waitlist" or (signal_key in BUY_SIGNALS and timing_key == "wait"):
        return "not_now"
    if phase_key == "prospect_ready" or signal_key in BUY_SIGNALS:
        return "near_buy"
    if signal_key == "hold" and conviction >= near_buy_conviction:
        return "near_buy"
    return "not_buy_tier"


def _column_reason(
    column_id: str,
    *,
    phase: str | None,
    timing: str,
    sold_days: float | None,
    opened_days: float | None,
) -> str:
    if column_id == "not_now":
        return "timing wait"
    if column_id == "near_buy" and timing == "wait":
        return "timing wait"
    if column_id == "near_buy":
        return "buy-tier ready" if phase and "prospect" in str(phase) else "near buy"
    if column_id == "just_bought":
        if opened_days is not None and opened_days <= JUST_BOUGHT_DAYS:
            return f"opened {int(opened_days)}d ago"
        return str(phase or "starter")
    if column_id == "near_sell":
        return str(phase or "harvest")
    if column_id == "just_sold" and sold_days is not None:
        return f"sold {int(sold_days)}d ago"
    if column_id == "post_sale":
        return "reentry cooldown" if phase is None else str(phase)
    if column_id == "growth":
        return str(phase or "full")
    return str(phase or "below buy-tier")


def _slim_card(
    *,
    ticker: str,
    row: dict[str, Any] | None,
    holding: dict[str, Any] | None,
    column_id: str,
    phase: str | None,
    opened_at: str | None,
    sold_at: str | None,
    now: datetime,
) -> dict[str, Any]:
    src = row or {}
    hold = holding or {}
    signal = _signal(src) or str(hold.get("signal") or "")
    timing = _timing(src)
    conviction = _conviction(src)
    opened_days = _days_since(opened_at, now)
    sold_days = _days_since(sold_at, now)
    avg_cost = _optional_float(hold.get("avg_cost"))
    mark = _optional_float(src.get("last_price"))
    if mark is None:
        mark = _optional_float(src.get("price"))
    pnl_pct = None
    if avg_cost and avg_cost > 0 and mark and mark > 0:
        pnl_pct = round((mark - avg_cost) / avg_cost, 4)
    card = {
        "ticker": ticker,
        "name": str(src.get("name") or hold.get("name") or ticker),
        "signal": signal or None,
        "timing_signal": timing or None,
        "conviction_score": round(conviction, 4) if conviction else None,
        "lifecycle_phase": phase,
        "column_reason": _column_reason(
            column_id,
            phase=phase,
            timing=timing,
            sold_days=sold_days,
            opened_days=opened_days,
        ),
    }
    if opened_at:
        card["opened_at"] = opened_at
    if sold_at:
        card["sold_at"] = sold_at
    if avg_cost is not None:
        card["avg_cost"] = avg_cost
    if pnl_pct is not None:
        card["unrealized_pnl_pct"] = pnl_pct
    days_in_column: float | None = None
    tenure_basis: str | None = None
    if column_id in HELD_TENURE_COLUMNS:
        days_in_column = opened_days
        tenure_basis = "opened_at"
    elif column_id in SOLD_TENURE_COLUMNS:
        days_in_column = sold_days
        tenure_basis = "sold_at"
    elif column_id in SCREEN_COLUMN_IDS:
        signal_since = str(src.get("signal_since") or "").strip() or None
        if signal_since:
            card["signal_since"] = signal_since
        days_in_column = _days_since(signal_since, now)
        if days_in_column is not None:
            tenure_basis = "signal_since"
        else:
            weeks = _optional_float(src.get("weeks_at_signal"))
            if weeks is not None:
                days_in_column = max(0.0, float(weeks) * 7.0)
                tenure_basis = "weeks_at_signal"
                card["weeks_at_signal"] = weeks
    if days_in_column is not None:
        card["days_in_column"] = int(days_in_column)
        card["tenure_band"] = tenure_band_for_days(days_in_column)
        card["tenure_basis"] = tenure_basis
    return card


def _empty_columns() -> dict[str, list[dict[str, Any]]]:
    return {column_id: [] for column_id in BOARD_COLUMN_IDS}


def _pack_columns(
    buckets: dict[str, list[dict[str, Any]]],
    *,
    column_ids: tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    packed: dict[str, dict[str, Any]] = {}
    for column_id in column_ids or BOARD_COLUMN_IDS:
        items = list(buckets.get(column_id) or [])
        cap = COLUMN_SHOW_CAPS.get(column_id, 32)

        def _sort_key(card: dict[str, Any]) -> tuple[Any, ...]:
            conv = card.get("conviction_score")
            conv_val = -float(conv) if conv is not None else 0.0
            opened = str(card.get("opened_at") or card.get("sold_at") or "")
            return (conv_val, opened, str(card.get("ticker") or ""))

        items.sort(key=_sort_key)
        packed[column_id] = {
            "count": len(items),
            "shown": items[:cap],
            "truncated": max(0, len(items) - cap),
        }
    return packed


def merge_track_columns(
    screen_columns: dict[str, Any] | None,
    track: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Overlay paper-book columns onto the shared screen funnel for one track."""
    occupied = {str(ticker) for ticker in (track or {}).get("occupied_tickers") or [] if ticker}
    removed = _as_dict((track or {}).get("screen_occupied"))
    merged: dict[str, dict[str, Any]] = {}
    for column_id in SCREEN_COLUMN_IDS:
        packed = _as_dict((screen_columns or {}).get(column_id))
        shown = [
            card
            for card in _as_list(packed.get("shown"))
            if isinstance(card, dict) and str(card.get("ticker") or "") not in occupied
        ]
        count = max(0, int(packed.get("count") or 0) - int(removed.get(column_id) or 0))
        merged[column_id] = {
            "count": count,
            "shown": shown,
            "truncated": max(0, count - len(shown)),
        }
    position = _as_dict((track or {}).get("position_columns") or (track or {}).get("columns"))
    for column_id in POSITION_COLUMN_IDS:
        packed = _as_dict(position.get(column_id))
        merged[column_id] = {
            "count": int(packed.get("count") or 0),
            "shown": [card for card in _as_list(packed.get("shown")) if isinstance(card, dict)],
            "truncated": int(packed.get("truncated") or 0),
        }
    return merged


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return [
                {str(key): value for key, value in row.items() if key}
                for row in csv.DictReader(handle)
            ]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def _index_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = _ticker(row)
        if ticker:
            index[ticker] = row
    return index


def _last_closed_sells(trades: list[Any]) -> dict[str, dict[str, Any]]:
    closed: dict[str, dict[str, Any]] = {}
    for raw in trades:
        trade = _as_dict(raw)
        if str(trade.get("side") or "").lower() != "sell":
            continue
        if not trade.get("position_closed"):
            continue
        ticker = _ticker(trade)
        if not ticker:
            continue
        prev = closed.get(ticker)
        acted = str(trade.get("acted_at") or "")
        if prev is None or acted >= str(prev.get("acted_at") or ""):
            closed[ticker] = trade
    return closed


def _holding_phase(
    *,
    holding: dict[str, Any],
    row: dict[str, Any] | None,
    target_value: float,
    exit_streak: int,
) -> str:
    shares = _float(holding.get("shares"))
    price = _optional_float((row or {}).get("last_price"))
    if price is None:
        price = _optional_float((row or {}).get("price"))
    if price is None or price <= 0:
        price = _float(holding.get("avg_cost"))
    current_value = shares * price if price else 0.0
    signal = _signal(row or {})
    in_target = signal in BUY_SIGNALS
    return classify_lifecycle_phase(
        held=True,
        in_target_set=in_target,
        current_value=current_value,
        target_value=target_value,
        exit_streak=exit_streak,
        momentum_grace=bool(holding.get("momentum_grace")),
        row=row,
        use_adjusted_signal=bool((row or {}).get("adjusted_signal")),
    )


def _screen_phase(row: dict[str, Any]) -> str:
    return classify_lifecycle_phase(
        held=False,
        in_target_set=False,
        current_value=0.0,
        target_value=0.0,
        exit_streak=0,
        momentum_grace=False,
        row=row,
        use_adjusted_signal=bool(row.get("adjusted_signal")),
    )


def _classify_market_track(
    *,
    screen_rows: list[dict[str, Any]],
    fund: dict[str, Any] | None,
    now: datetime,
) -> dict[str, list[dict[str, Any]]]:
    buckets = _empty_columns()
    row_index = _index_rows(screen_rows)
    fund = fund or {}
    holdings = fund.get("holdings") if isinstance(fund.get("holdings"), dict) else {}
    rebalance = _as_dict(fund.get("rebalance_state"))
    exit_streaks = _as_dict(rebalance.get("exit_streak"))
    cooldowns = _as_dict(rebalance.get("reentry_cooldown"))
    closed_sells = _last_closed_sells(_as_list(fund.get("trades")))
    curve = [row for row in _as_list(fund.get("equity_curve")) if isinstance(row, dict)]
    last_mark = curve[-1] if curve else {}
    nav = _float(last_mark.get("portfolio_value") or fund.get("cash"))
    max_positions = int(_as_dict(fund.get("config")).get("max_positions") or 0)
    target_each = (nav / max_positions) if nav > 0 and max_positions > 0 else 0.0

    placed: set[str] = set()

    for ticker, raw_holding in holdings.items():
        ticker_key = str(ticker).strip()
        if not ticker_key:
            continue
        holding = _as_dict(raw_holding)
        holding.setdefault("ticker", ticker_key)
        row = row_index.get(ticker_key)
        phase = _holding_phase(
            holding=holding,
            row=row,
            target_value=target_each,
            exit_streak=int(exit_streaks.get(ticker_key) or 0),
        )
        column_id = classify_board_column(
            held=True,
            signal=_signal(row or {}),
            timing=_timing(row or {}),
            conviction=_conviction(row or {}),
            phase=phase,
            opened_at=str(holding.get("opened_at") or "") or None,
            now=now,
        )
        buckets[column_id].append(
            _slim_card(
                ticker=ticker_key,
                row=row,
                holding=holding,
                column_id=column_id,
                phase=phase,
                opened_at=str(holding.get("opened_at") or "") or None,
                sold_at=None,
                now=now,
            )
        )
        placed.add(ticker_key)

    for ticker_key, trade in closed_sells.items():
        if ticker_key in placed:
            continue
        row = row_index.get(ticker_key)
        cooldown = int(cooldowns.get(ticker_key) or 0) > 0
        column_id = classify_board_column(
            held=False,
            signal=_signal(row or {}),
            timing=_timing(row or {}),
            conviction=_conviction(row or {}),
            sold_at=str(trade.get("acted_at") or "") or None,
            cooldown=cooldown,
            now=now,
        )
        if column_id not in {"just_sold", "post_sale"}:
            continue
        buckets[column_id].append(
            _slim_card(
                ticker=ticker_key,
                row=row,
                holding={"name": trade.get("name"), "avg_cost": trade.get("avg_cost_at_exit")},
                column_id=column_id,
                phase="exit" if column_id == "just_sold" else "recommit",
                opened_at=None,
                sold_at=str(trade.get("acted_at") or "") or None,
                now=now,
            )
        )
        placed.add(ticker_key)

    for ticker_key, remaining in cooldowns.items():
        ticker_key = str(ticker_key).strip()
        if not ticker_key or ticker_key in placed:
            continue
        if int(remaining or 0) <= 0:
            continue
        row = row_index.get(ticker_key)
        buckets["post_sale"].append(
            _slim_card(
                ticker=ticker_key,
                row=row,
                holding=None,
                column_id="post_sale",
                phase="recommit",
                opened_at=None,
                sold_at=None,
                now=now,
            )
        )
        placed.add(ticker_key)

    for ticker_key, row in row_index.items():
        if ticker_key in placed:
            continue
        phase = _screen_phase(row)
        column_id = classify_board_column(
            held=False,
            signal=_signal(row),
            timing=_timing(row),
            conviction=_conviction(row),
            phase=phase,
            now=now,
        )
        buckets[column_id].append(
            _slim_card(
                ticker=ticker_key,
                row=row,
                holding=None,
                column_id=column_id,
                phase=phase,
                opened_at=None,
                sold_at=None,
                now=now,
            )
        )
        placed.add(ticker_key)

    return buckets


def _is_main_track(track_id: str, config: dict[str, Any]) -> bool:
    if config.get("is_calibration_shadow") or config.get("is_exclusion_shadow"):
        return False
    if config.get("is_fair_cost_lab"):
        return False
    tid = str(track_id or "")
    if any(tid.startswith(prefix) for prefix in _SHADOW_TRACK_PREFIXES):
        return False
    if MAIN_TRACK_IDS and tid not in MAIN_TRACK_IDS and tid != BUY_TIER_LEVEL_TRACK_ID:
        return False
    return True


def _paper_root_for_market(
    market_id: str,
    *,
    paper_root: Path,
    shard_root: Path,
) -> Path:
    if market_id == LIVE_MARKET_ID:
        return Path(paper_root)
    return shard_root_for_market(market_id, base=shard_root)


def _load_tracks(
    market_id: str,
    *,
    paper_root: Path,
    shard_root: Path,
) -> list[dict[str, Any]]:
    root = _paper_root_for_market(market_id, paper_root=paper_root, shard_root=shard_root)
    if not root.exists():
        return []
    tracks: list[dict[str, Any]] = []
    try:
        dirs = learning_track_dirs(root)
    except Exception:  # noqa: BLE001
        dirs = {}
    for track_id, track_dir in dirs.items():
        fund_path = Path(track_dir) / FUND_FILENAME
        if not fund_path.exists():
            continue
        fund = _as_dict(_safe_read(fund_path))
        if not fund:
            continue
        config = _as_dict(_safe_read(Path(track_dir) / CONFIG_FILENAME))
        if not config:
            config = _as_dict(fund.get("config"))
        if not _is_main_track(str(track_id), config):
            continue
        holdings = fund.get("holdings") if isinstance(fund.get("holdings"), dict) else {}
        tracks.append(
            {
                "track_id": str(track_id),
                "track_label": config.get("track_label") or str(track_id),
                "is_primary": bool(config.get("is_primary_learning_track")),
                "is_cohort_lab": bool(config.get("is_cohort_lab")),
                "holdings_count": len(holdings),
                "fund": fund,
            }
        )
    tracks.sort(
        key=lambda row: (
            0 if row.get("track_id") == BUY_TIER_LEVEL_TRACK_ID else 1,
            0 if row.get("is_primary") else 1,
            str(row.get("track_id") or ""),
        )
    )
    return tracks


def _default_track_id(tracks: list[dict[str, Any]]) -> str | None:
    if not tracks:
        return None
    for preferred in (BUY_TIER_LEVEL_TRACK_ID, "ai_judgment", "rules"):
        if any(row.get("track_id") == preferred for row in tracks):
            return preferred
    primary = next((row for row in tracks if row.get("is_primary")), None)
    if primary:
        return str(primary["track_id"])
    return str(tracks[0]["track_id"])


def _load_screen_rows(
    market_id: str,
    *,
    library_root: Path,
    live_reports: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if market_id == LIVE_MARKET_ID:
        return [row for row in (live_reports or []) if isinstance(row, dict) and _ticker(row)]
    path = screen_dir_for(library_root, market_id) / "latest_signals.csv"
    rows = _load_csv_rows(path)
    if rows:
        return rows
    watch = _as_dict(_safe_read(screen_dir_for(library_root, market_id) / NEAR_MISS_FILENAME))
    if not watch or watch.get("skipped"):
        return []
    combined: list[dict[str, Any]] = []
    for key in ("buy_tier_not_now", "hold_near_buy", "not_buy_tier"):
        for row in _as_list(watch.get(key)):
            if isinstance(row, dict) and _ticker(row):
                combined.append(row)
    return combined


def _has_market_data(
    market_id: str,
    *,
    screen_rows: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
    admitted: set[str],
    focus: str,
) -> bool:
    if market_id == LIVE_MARKET_ID:
        return True
    if tracks:
        return True
    if market_id == focus or market_id in admitted:
        return bool(screen_rows)
    return False


def _market_order_key(market_id: str, *, admitted: set[str], focus: str) -> tuple[int, str]:
    if market_id == LIVE_MARKET_ID:
        return (0, market_id)
    if market_id == focus:
        return (1, market_id)
    if market_id in admitted:
        return (2, market_id)
    return (3, market_id)


def _load_live_reports(latest_path: Path | None) -> tuple[list[dict[str, Any]], str | None]:
    raw = _as_dict(_safe_read(Path(latest_path or DEFAULT_LATEST_PATH)))
    reports = [row for row in _as_list(raw.get("reports")) if isinstance(row, dict)]
    return reports, raw.get("run_at") if isinstance(raw.get("run_at"), str) else None


def _load_assessment(path: Path | None) -> dict[str, Any] | None:
    raw = _safe_read(Path(path or DEFAULT_EXPERIMENT_ASSESSMENT_PATH))
    return raw if isinstance(raw, dict) else None


def _policy_sets(policy_path: Path | None) -> tuple[set[str], str]:
    admitted: set[str] = set()
    focus = ""
    try:
        from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy
        from value_investor.market_shard_admission import admitted_learning_markets_for_policy

        policy = load_policy(Path(policy_path or DEFAULT_POLICY_PATH))
        if isinstance(policy, dict):
            admitted = set(admitted_learning_markets_for_policy(policy))
            focus = str(policy.get("focus_market") or "").strip()
    except Exception:  # noqa: BLE001
        return admitted, focus
    return admitted, focus


def build_lifecycle_board(
    *,
    library_root: Path | None = None,
    paper_root: Path | None = None,
    shard_root: Path | None = None,
    latest_path: Path | None = None,
    assessment_path: Path | None = None,
    live_reports: list[dict[str, Any]] | None = None,
    live_run_at: str | None = None,
    experiment_assessment: dict[str, Any] | None = None,
    policy_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the per-market lifecycle board payload for the dashboard."""
    as_of = now or datetime.now(UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    library_root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    paper_root = Path(paper_root or DEFAULT_PAPER_ROOT)
    shard_root = Path(shard_root or DEFAULT_SHARD_ROOT)

    if live_reports is None:
        live_reports, latest_run = _load_live_reports(latest_path)
        live_run_at = live_run_at or latest_run
    if experiment_assessment is None:
        experiment_assessment = _load_assessment(assessment_path)

    columns = board_column_defs(assessment=experiment_assessment)
    admitted, focus = _policy_sets(policy_path)

    market_ids = [LIVE_MARKET_ID]
    market_ids.extend(mid for mid in MARKET_REGISTRY if mid != LIVE_MARKET_ID)

    markets: list[dict[str, Any]] = []
    for market_id in market_ids:
        spec = MARKET_REGISTRY.get(market_id)
        screen_rows = _load_screen_rows(
            market_id, library_root=library_root, live_reports=live_reports
        )
        tracks_raw = _load_tracks(market_id, paper_root=paper_root, shard_root=shard_root)
        if not _has_market_data(
            market_id,
            screen_rows=screen_rows,
            tracks=tracks_raw,
            admitted=admitted,
            focus=focus,
        ):
            continue
        default_track = _default_track_id(tracks_raw)
        screen_buckets = _classify_market_track(screen_rows=screen_rows, fund=None, now=as_of)
        screen_columns = _pack_columns(screen_buckets, column_ids=SCREEN_COLUMN_IDS)
        track_payloads: list[dict[str, Any]] = []
        source_tracks = tracks_raw or [
            {
                "track_id": "screen",
                "track_label": "Screen only (no paper book)",
                "is_primary": False,
                "is_cohort_lab": False,
                "holdings_count": 0,
                "fund": None,
            }
        ]
        for track in source_tracks:
            buckets = _classify_market_track(
                screen_rows=screen_rows,
                fund=track.get("fund"),
                now=as_of,
            )
            occupied: list[str] = []
            for column_id in POSITION_COLUMN_IDS:
                for card in buckets.get(column_id) or []:
                    ticker = str(card.get("ticker") or "")
                    if ticker and ticker not in occupied:
                        occupied.append(ticker)
            occupied_set = set(occupied)
            screen_occupied = {
                column_id: sum(
                    1
                    for card in screen_buckets.get(column_id) or []
                    if str(card.get("ticker") or "") in occupied_set
                )
                for column_id in SCREEN_COLUMN_IDS
            }
            track_payloads.append(
                {
                    "track_id": track["track_id"],
                    "track_label": track["track_label"],
                    "is_primary": track["is_primary"],
                    "is_cohort_lab": track["is_cohort_lab"],
                    "is_default": track["track_id"] == (default_track or "screen"),
                    "holdings_count": track["holdings_count"],
                    "occupied_tickers": occupied,
                    "screen_occupied": screen_occupied,
                    "position_columns": _pack_columns(buckets, column_ids=POSITION_COLUMN_IDS),
                }
            )
        default_row = next(
            (row for row in track_payloads if row.get("is_default")),
            track_payloads[0],
        )
        merged_default = merge_track_columns(screen_columns, default_row)
        counts = {
            column_id: int((merged_default.get(column_id) or {}).get("count") or 0)
            for column_id in BOARD_COLUMN_IDS
        }
        markets.append(
            {
                "market_id": market_id,
                "label": spec.label if spec else market_id,
                "exchange": spec.exchange if spec else None,
                "currency": spec.currency if spec else None,
                "is_live": market_id == LIVE_MARKET_ID,
                "is_focus": market_id == focus,
                "is_admitted": market_id == LIVE_MARKET_ID or market_id in admitted,
                "screen_count": len(screen_rows),
                "default_track_id": default_track or track_payloads[0]["track_id"],
                "column_counts": counts,
                "screen_columns": screen_columns,
                "tracks": track_payloads,
            }
        )

    markets.sort(
        key=lambda row: _market_order_key(str(row["market_id"]), admitted=admitted, focus=focus)
    )
    default_market = LIVE_MARKET_ID
    if markets and not any(row["market_id"] == default_market for row in markets):
        default_market = str(markets[0]["market_id"])

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": as_of.isoformat(),
        "live_run_at": live_run_at,
        "observe_only": True,
        "note": (
            "Per-market funnel of screen names plus paper-book holdings. "
            "Classification is diagnostic — it does not run the deferred per-holding "
            "state machine. Experiments are the position-lifecycle catalog, joined to "
            "the unified assessment ledger when present. Switch market (and paper track) "
            "rather than stacking every universe on one board."
        ),
        "just_bought_days": JUST_BOUGHT_DAYS,
        "just_sold_days": JUST_SOLD_DAYS,
        "post_sale_days": POST_SALE_DAYS,
        "starter_ratio_ceiling": STARTER_RATIO_CEILING,
        "near_buy_conviction": DEFAULT_PRE_BUY_CONVICTION,
        "tenure": tenure_scale(),
        "default_market_id": default_market,
        "columns": columns,
        "markets": markets,
    }


def write_lifecycle_board(
    *,
    library_root: Path | None = None,
    paper_root: Path | None = None,
    shard_root: Path | None = None,
    latest_path: Path | None = None,
    assessment_path: Path | None = None,
    live_reports: list[dict[str, Any]] | None = None,
    live_run_at: str | None = None,
    experiment_assessment: dict[str, Any] | None = None,
    policy_path: Path | None = None,
    path: Path | None = None,
    now: datetime | None = None,
) -> Path:
    """Rebuild ``docs/data/lifecycle_board.json`` without a full screen publish."""
    payload = build_lifecycle_board(
        library_root=library_root,
        paper_root=paper_root,
        shard_root=shard_root,
        latest_path=latest_path,
        assessment_path=assessment_path,
        live_reports=live_reports,
        live_run_at=live_run_at,
        experiment_assessment=experiment_assessment,
        policy_path=policy_path,
        now=now,
    )
    target = Path(path or DEFAULT_LIFECYCLE_BOARD_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, payload, compact=False)
    return target


def tickers_on_lifecycle_board(
    board: dict[str, Any] | None,
    *,
    shown_only: bool = True,
) -> list[str]:
    """Return unique tickers shown on the lifecycle board (all markets / tracks)."""
    by_market = lifecycle_tickers_by_market(board, shown_only=shown_only)
    found: list[str] = []
    seen: set[str] = set()
    for tickers in by_market.values():
        for ticker in tickers:
            if ticker in seen:
                continue
            seen.add(ticker)
            found.append(ticker)
    return found


def lifecycle_tickers_by_market(
    board: dict[str, Any] | None,
    *,
    shown_only: bool = True,
) -> dict[str, list[str]]:
    """Map market_id → unique shown/occupied tickers on the lifecycle board."""
    if not isinstance(board, dict):
        return {}

    def _add(ticker: Any, *, seen: set[str], found: list[str]) -> None:
        text = str(ticker or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        found.append(text)

    out: dict[str, list[str]] = {}
    for market in _as_list(board.get("markets")):
        if not isinstance(market, dict):
            continue
        market_id = str(market.get("market_id") or "").strip()
        if not market_id:
            continue
        found: list[str] = []
        seen: set[str] = set()

        for packed in _as_dict(market.get("screen_columns")).values():
            for card in _as_list(_as_dict(packed).get("shown")):
                if isinstance(card, dict):
                    _add(card.get("ticker"), seen=seen, found=found)
        for track in _as_list(market.get("tracks")):
            if not isinstance(track, dict):
                continue
            for ticker in _as_list(track.get("occupied_tickers")):
                _add(ticker, seen=seen, found=found)
            position = track.get("position_columns") or track.get("columns") or {}
            for packed in _as_dict(position).values():
                for card in _as_list(_as_dict(packed).get("shown")):
                    if isinstance(card, dict):
                        _add(card.get("ticker"), seen=seen, found=found)
        out[market_id] = found
    return out


__all__ = [
    "COLUMN_SHOW_CAPS",
    "DEFAULT_LIFECYCLE_BOARD_PATH",
    "JUST_BOUGHT_DAYS",
    "JUST_SOLD_DAYS",
    "POST_SALE_DAYS",
    "POSITION_COLUMN_IDS",
    "SCREEN_COLUMN_IDS",
    "SCHEMA_VERSION",
    "TENURE_LONG_DAYS",
    "build_lifecycle_board",
    "classify_board_column",
    "merge_track_columns",
    "tenure_band_for_days",
    "tenure_scale",
    "tickers_on_lifecycle_board",
    "lifecycle_tickers_by_market",
    "write_lifecycle_board",
]
