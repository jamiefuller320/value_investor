"""Hold-period counterfactual for the FTSE paper learning tracks (L531).

Learning question: would holding positions longer (fewer rank-driven
"left target set" exits) improve after-cost return on the live books?

Observe-only. For each headline track the logged rebalance passes are replayed
with the live knobs (baseline) and with longer exit buffers
(``exit_confirm_screens``). Variants are scored against the *baseline replay*,
not against the live book, so both sides share the same pricing.

A replay is only trusted when its baseline reproduces the logged book: the
window starts at the earliest acted pass whose baseline replay ends within
``FIDELITY_TOLERANCE`` of the last logged ``nav_after``. That skips log holes
(unlogged trades between passes) and seed bursts (warm-start passes with a reset
exit-streak state). Tracks without enough faithful passes are reported, not scored.

Realised holding period (FIFO closed lots) and annualised turnover come from the
live fund trades. Daily ops-monitor refreshes
``docs/data/hold_period_counterfactual.json``. Never changes books or knobs.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from value_investor.rebalance_log import (
    acted_log_entries,
    load_rebalance_log,
    replay_counterfactual_from_log,
)
from value_investor.total_return_view import (
    TickerHistory,
    _close_before,
    _marks,
    _read_json,
    _trades,
    fetch_ticker_history,
)

logger = logging.getLogger(__name__)

DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
DEFAULT_STORE_PATH = Path("docs/data/hold_period_counterfactual.json")
FUND_FILENAME = "automated_fund.json"

HEADLINE_TRACKS = ("ai_judgment", "rules", "ai_judgment_fair", "rules_fair")
EXIT_CONFIRM_VARIANTS = (5, 10, 20)
FIDELITY_TOLERANCE = 0.01
MIN_FAITHFUL_PASSES = 8
HOLD_EDGE_MIN = 0.01

LEARNING_QUESTION = (
    "Would holding positions longer (fewer rank-driven exits) improve after-cost "
    "return on the live books?"
)
FINDING_TITLE = "Longer holds beat live exit buffer in replay"
STORE_FAILED_TITLE = "Hold-period counterfactual observe failed"

HistoryFetcher = Callable[[str, date, date], TickerHistory]


def realised_holding_stats(fund: dict[str, Any]) -> dict[str, Any]:
    """FIFO closed-lot hold days and annualised sell turnover from fund trades."""
    lots: dict[str, deque[list[Any]]] = {}
    hold_days: list[float] = []
    sell_gross = 0.0
    trades = _trades(fund)
    for trade in trades:
        ticker = str(trade["ticker"])
        shares = float(trade.get("shares") or 0.0)
        if shares <= 0:
            continue
        if trade.get("side") == "buy":
            lots.setdefault(ticker, deque()).append([trade["_at"], shares])
            continue
        if trade.get("side") != "sell":
            continue
        sell_gross += float(trade.get("gross") or 0.0)
        queue = lots.get(ticker) or deque()
        remaining = shares
        while remaining > 1e-9 and queue:
            opened, lot_shares = queue[0]
            used = min(lot_shares, remaining)
            remaining -= used
            if lot_shares - used <= 1e-9:
                queue.popleft()
                hold_days.append((trade["_at"] - opened).total_seconds() / 86400.0)
            else:
                queue[0][1] = lot_shares - used
    marks = _marks(fund)
    window_days = 0.0
    if trades:
        end = marks[-1][0] if marks and marks[-1][0] > trades[-1]["_at"] else trades[-1]["_at"]
        window_days = (end - trades[0]["_at"]).total_seconds() / 86400.0
    avg_nav = sum(m[1] for m in marks) / len(marks) if marks else 0.0
    turnover = None
    if avg_nav > 0 and window_days >= 7:
        turnover = round(sell_gross / avg_nav * 365.0 / window_days, 2)
    ordered = sorted(hold_days)
    return {
        "closed_lots": len(ordered),
        "median_hold_days": round(median(ordered), 1) if ordered else None,
        "p75_hold_days": round(ordered[int(0.75 * (len(ordered) - 1))], 1) if ordered else None,
        "max_hold_days": round(ordered[-1], 1) if ordered else None,
        "annualised_sell_turnover": turnover,
        "window_days": round(window_days, 1),
    }


def price_ratio_from_history(
    history_fetcher: HistoryFetcher,
) -> Callable[[str, date, date], float | None]:
    """Close-to-close ratio (same Yahoo unit both ends), fetched lazily per ticker."""
    cache: dict[str, dict[date, float]] = {}

    def ratio(ticker: str, from_day: date, to_day: date) -> float | None:
        if ticker not in cache:
            end = datetime.now(UTC).date()
            try:
                cache[ticker] = history_fetcher(ticker, end - timedelta(days=400), end).closes
            except Exception as exc:  # noqa: BLE001
                logger.info("Hold-period ratio unavailable for %s: %s", ticker, exc)
                cache[ticker] = {}
        closes = cache[ticker]
        start = _close_before(closes, from_day + timedelta(days=1))
        stop = _close_before(closes, to_day + timedelta(days=1))
        if not start or not stop:
            return None
        return stop / start

    return ratio


def _replay(
    passes: list[dict[str, Any]],
    ratio: Callable[[str, date, date], float | None],
    exit_confirm_screens: int | None = None,
) -> dict[str, Any] | None:
    return replay_counterfactual_from_log(
        passes,
        max_positions=int(passes[0].get("max_positions") or 3),
        use_logged_knobs=True,
        exit_confirm_screens=exit_confirm_screens,
        held_price_ratio=ratio,
    )


def _fidelity_gap(passes: list[dict[str, Any]], replay: dict[str, Any]) -> float | None:
    base = float(passes[0].get("nav_before") or 0.0)
    logged = passes[-1].get("nav_after")
    if base <= 0 or logged is None:
        return None
    return (float(replay["simulated_nav"]) - float(logged)) / base


def faithful_window(
    acted: list[dict[str, Any]],
    ratio: Callable[[str, date, date], float | None],
) -> tuple[int, dict[str, Any], float] | None:
    """Earliest start pass whose baseline replay reproduces the logged end NAV."""
    for start in range(len(acted) - MIN_FAITHFUL_PASSES + 1):
        passes = acted[start:]
        replay = _replay(passes, ratio)
        if replay is None:
            continue
        gap = _fidelity_gap(passes, replay)
        if gap is not None and abs(gap) <= FIDELITY_TOLERANCE:
            return start, replay, gap
    return None


def _live_exit_confirm(acted: list[dict[str, Any]]) -> int | None:
    value = (acted[-1].get("selection") or {}).get("exit_confirm_screens")
    return int(value) if value is not None else None


def score_track(
    track_id: str,
    track_dir: Path,
    ratio: Callable[[str, date, date], float | None],
) -> dict[str, Any]:
    fund = _read_json(track_dir / FUND_FILENAME) or {}
    acted = acted_log_entries(load_rebalance_log(track_dir))
    row: dict[str, Any] = {
        "track_id": track_id,
        "acted_passes": len(acted),
        "live_exit_confirm_screens": _live_exit_confirm(acted) if acted else None,
        "realised": realised_holding_stats(fund),
    }
    window = faithful_window(acted, ratio) if len(acted) >= MIN_FAITHFUL_PASSES else None
    if window is None:
        row["status"] = "unreliable"
        row["reason"] = (
            f"no window of ≥{MIN_FAITHFUL_PASSES} acted passes whose baseline replay "
            f"reproduces the logged NAV within {FIDELITY_TOLERANCE:.0%}"
        )
        return row
    start, baseline, gap = window
    passes = acted[start:]
    base_return = float(baseline["simulated_return"])
    variants = []
    for screens in EXIT_CONFIRM_VARIANTS:
        replay = _replay(passes, ratio, exit_confirm_screens=screens)
        if replay is None:
            continue
        variants.append(
            {
                "exit_confirm_screens": screens,
                "simulated_return": replay["simulated_return"],
                "delta_vs_baseline": round(float(replay["simulated_return"]) - base_return, 4),
                "trade_count": replay["simulated_trade_count"],
                "cost_drag": replay["simulated_cost_drag"],
                "held_price_fills": replay["held_price_fills"],
                "held_price_avg_cost_fallbacks": replay["held_price_avg_cost_fallbacks"],
            }
        )
    best = max(variants, key=lambda v: v["delta_vs_baseline"], default=None)
    row.update(
        {
            "status": "ok",
            "window": {
                "from": baseline["replay_from"],
                "to": baseline["replay_to"],
                "passes": len(passes),
                "skipped_passes": start,
                "fidelity_gap": round(gap, 4),
            },
            "baseline": {
                "simulated_return": baseline["simulated_return"],
                "trade_count": baseline["simulated_trade_count"],
                "cost_drag": baseline["simulated_cost_drag"],
            },
            "variants": variants,
            "best_variant": best,
        }
    )
    return row


def build_hold_period_counterfactual(
    paper_root: Path = DEFAULT_PAPER_ROOT,
    *,
    history_fetcher: HistoryFetcher = fetch_ticker_history,
    tracks: tuple[str, ...] = HEADLINE_TRACKS,
) -> dict[str, Any]:
    from value_investor.paper_automation import learning_track_dirs

    dirs = learning_track_dirs(Path(paper_root))
    ratio = price_ratio_from_history(history_fetcher)
    rows = {
        track_id: score_track(track_id, dirs[track_id], ratio)
        for track_id in tracks
        if track_id in dirs and (dirs[track_id] / FUND_FILENAME).exists()
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "learning_question": LEARNING_QUESTION,
        "method": {
            "variants": "exit_confirm_screens " + "/".join(str(v) for v in EXIT_CONFIRM_VARIANTS),
            "scored_against": "baseline replay with logged per-pass knobs",
            "fidelity_tolerance": FIDELITY_TOLERANCE,
            "min_faithful_passes": MIN_FAITHFUL_PASSES,
            "hold_edge_min": HOLD_EDGE_MIN,
        },
        "tracks": rows,
        "limitations": (
            "Weeks of passes on 3-name books: a positive delta is a hypothesis for a "
            "cold-start twin, not adoption evidence. Replays only see names in logged "
            "candidates; held names missing from a pass are marked from Yahoo closes."
        ),
    }


def refresh_hold_period_counterfactual(
    paper_root: Path = DEFAULT_PAPER_ROOT,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    history_fetcher: HistoryFetcher = fetch_ticker_history,
    persist: bool = True,
) -> dict[str, Any]:
    payload = build_hold_period_counterfactual(paper_root, history_fetcher=history_fetcher)
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_finding_from_hold_period_counterfactual(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Warn when a faithful replay shows a longer exit buffer beating live by ≥1pp."""
    lines: list[str] = []
    for track_id, row in (payload.get("tracks") or {}).items():
        best = row.get("best_variant") or {}
        if row.get("status") != "ok" or float(best.get("delta_vs_baseline") or 0.0) < HOLD_EDGE_MIN:
            continue
        realised = row.get("realised") or {}
        window = row.get("window") or {}
        lines.append(
            f"{track_id}: exit_confirm_screens {best['exit_confirm_screens']} vs live "
            f"{row.get('live_exit_confirm_screens')} {best['delta_vs_baseline']:+.1%} over "
            f"{window.get('passes')} passes ({best['trade_count']} vs "
            f"{(row.get('baseline') or {}).get('trade_count')} trades; realised median hold "
            f"{realised.get('median_hold_days')}d)"
        )
    if not lines:
        return None
    return {
        "severity": "warn",
        "category": "paper",
        "title": FINDING_TITLE,
        "summary": (
            "Faithful replay of logged passes with a longer exit buffer beats the live "
            f"knob by ≥{HOLD_EDGE_MIN:.0%}: "
            + "; ".join(lines)
            + ". Observe-only: candidate for a cold-start hold-buffer twin, not a knob "
            "edit. See docs/ops/hold-period-counterfactual.md."
        ),
        "auto_fixable": False,
    }
