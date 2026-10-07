"""Total-return view of the FTSE paper learning tracks (L528 / L532 / L533).

Observe-only, published next to the existing price-only numbers. Paper funds do
not credit dividends and the adoption excess is measured against ``^FTSE`` (a
FTSE 100 *price* index) for a FTSE 350 book. Both understate a high-yield value
book. This view re-scores each track on:

- NAV from equity-curve marks (market prices), plus dividends the book would
  have received on shares held over each ex-date (credited as cash, not
  reinvested);
- a total-return benchmark: ``FTAL.L`` (SPDR FTSE UK All Share, accumulating);
- a clean epoch for fair-cost books that still carry trades charged at the 3%
  stress rate before their cost model switched (L533);
- a value-beta control: ``ai_judgment_fair`` minus the unfiltered
  ``buy_tier_level`` book on their common window (L532).

Dividends are credited as a yield ratio (dividend ÷ unadjusted close on the day
before ex-date, both from the same Yahoo series), applied to the position's
paper value, so pence/pound scaling between Yahoo and paper prices cancels.

Daily ops-monitor refreshes ``docs/data/total_return_view.json``. Never changes
live books, knobs or published adoption metrics.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
DEFAULT_STORE_PATH = Path("docs/data/total_return_view.json")
FUND_FILENAME = "automated_fund.json"
CONFIG_FILENAME = "config.json"
REVIEW_FILENAME = "decision_review.json"

PRICE_BENCHMARK = "^FTSE"
TR_BENCHMARK = "FTAL.L"
STRESS_COST_RATE = 0.02
MAX_PLAUSIBLE_YIELD = 0.15
PRIMARY_VS_CONTROL = "primary_vs_control"
MISSTATEMENT_GAP = 0.05

FINDING_TITLE = "Price-only excess misstates track performance"
STORE_FAILED_TITLE = "Total-return view observe failed"


@dataclass
class TickerHistory:
    """Unadjusted daily closes and cash dividends (same Yahoo unit per row)."""

    closes: dict[date, float] = field(default_factory=dict)
    dividends: dict[date, float] = field(default_factory=dict)


HistoryFetcher = Callable[[str, date, date], TickerHistory]


def fetch_ticker_history(ticker: str, start: date, end: date) -> TickerHistory:
    """Yahoo closes + dividends with pence/pound flips normalised (best effort)."""
    try:
        import yfinance as yf

        from value_investor.yahoo_price_units import normalize_ohlcv_frame

        frame = yf.Ticker(ticker).history(
            start=(start - timedelta(days=10)).isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            actions=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("History unavailable for %s: %s", ticker, exc)
        return TickerHistory()
    if frame is None or getattr(frame, "empty", True) or "Close" not in frame.columns:
        return TickerHistory()
    raw_close = frame["Close"].copy()
    frame, _meta = normalize_ohlcv_frame(frame)
    out = TickerHistory()
    for idx, value in frame["Close"].dropna().items():
        out.closes[idx.date()] = float(value)
    if "Dividends" in frame.columns:
        for idx, value in frame["Dividends"].items():
            if value and float(value) > 0:
                # Normalisation rescales Close only; keep the dividend in the raw
                # close unit of its own row by rescaling with the same factor.
                raw = float(raw_close.get(idx) or 0.0)
                norm = float(frame["Close"].get(idx) or 0.0)
                scale = (norm / raw) if raw > 0 and norm > 0 else 1.0
                out.dividends[idx.date()] = float(value) * scale
    return out


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _close_before(closes: dict[date, float], day: date) -> float | None:
    found: float | None = None
    for close_day in sorted(closes):
        if close_day >= day:
            break
        found = closes[close_day]
    return found


def _marks(fund: dict[str, Any]) -> list[tuple[datetime, float, float]]:
    out: list[tuple[datetime, float, float]] = []
    for mark in fund.get("equity_curve") or []:
        if not isinstance(mark, dict):
            continue
        at = _parse_dt(mark.get("at"))
        if at is None or mark.get("portfolio_value") is None:
            continue
        out.append(
            (at, float(mark["portfolio_value"]), float(mark.get("contributed_capital") or 0.0))
        )
    out.sort(key=lambda row: row[0])
    return out


def _trades(fund: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for trade in fund.get("trades") or []:
        if not isinstance(trade, dict):
            continue
        at = _parse_dt(trade.get("acted_at"))
        if at is None or not trade.get("ticker"):
            continue
        rows.append({**trade, "_at": at})
    rows.sort(key=lambda row: row["_at"])
    return rows


def dividend_credits(
    trades: list[dict[str, Any]],
    histories: dict[str, TickerHistory],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:
    """GBP dividends on shares held over each ex-date in ``(start, end]``.

    Shares count when bought on an earlier day than the ex-date and not sold
    before it. Returns ``(total, credited_rows, skipped_rows)``.
    """
    total = 0.0
    credited: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        by_ticker.setdefault(str(trade["ticker"]), []).append(trade)
    start_day = start.date() if start else None
    end_day = end.date() if end else None
    for ticker, rows in by_ticker.items():
        history = histories.get(ticker) or TickerHistory()
        for ex_day, dividend in sorted(history.dividends.items()):
            if start_day and ex_day <= start_day:
                continue
            if end_day and ex_day > end_day:
                continue
            shares = 0.0
            last_price = None
            last_day = None
            for trade in rows:
                if trade["_at"].date() >= ex_day:
                    break
                qty = float(trade.get("shares") or 0.0)
                shares += qty if trade.get("side") == "buy" else -qty
                if trade.get("price"):
                    last_price = float(trade["price"])
                    last_day = trade["_at"].date()
            if shares <= 1e-9 or last_price is None or last_day is None:
                continue
            close_ex = _close_before(history.closes, ex_day)
            close_ref = _close_before(history.closes, last_day + timedelta(days=1))
            if not close_ex or not close_ref:
                skipped.append({"ticker": ticker, "ex_date": ex_day.isoformat(), "why": "no close"})
                continue
            dividend_yield = dividend / close_ex
            if not 0 < dividend_yield <= MAX_PLAUSIBLE_YIELD:
                skipped.append(
                    {
                        "ticker": ticker,
                        "ex_date": ex_day.isoformat(),
                        "why": f"implausible yield {dividend_yield:.2%}",
                    }
                )
                continue
            paper_price_at_ex = last_price * (close_ex / close_ref)
            amount = shares * paper_price_at_ex * dividend_yield
            total += amount
            credited.append(
                {
                    "ticker": ticker,
                    "ex_date": ex_day.isoformat(),
                    "shares": round(shares, 6),
                    "yield": round(dividend_yield, 5),
                    "gbp": round(amount, 2),
                }
            )
    return total, credited, skipped


def _window_return(
    closes: dict[date, float],
    start: datetime,
    end: datetime,
) -> float | None:
    p0 = _close_before(closes, start.date())
    p1 = _close_before(closes, end.date())
    if not p0 or not p1:
        return None
    return p1 / p0 - 1.0


def score_window(
    marks: list[tuple[datetime, float, float]],
    trades: list[dict[str, Any]],
    histories: dict[str, TickerHistory],
    benchmarks: dict[str, TickerHistory],
    *,
    start_index: int = 0,
) -> dict[str, Any] | None:
    window = marks[start_index:]
    if len(window) < 2:
        return None
    start_at, nav0, contributed0 = window[0]
    end_at, nav1, contributed1 = window[-1]
    base = nav0 + (contributed1 - contributed0)
    if base <= 0:
        return None
    dividends, credited, skipped = dividend_credits(trades, histories, start=start_at, end=end_at)
    price_return = nav1 / base - 1.0
    total_return = (nav1 + dividends) / base - 1.0
    bench_price = _window_return(benchmarks[PRICE_BENCHMARK].closes, start_at, end_at)
    bench_tr = _window_return(benchmarks[TR_BENCHMARK].closes, start_at, end_at)
    return {
        "start": start_at.isoformat(),
        "end": end_at.isoformat(),
        "marks": len(window),
        "base_capital": round(base, 2),
        "nav_end": round(nav1, 2),
        "dividends_gbp": round(dividends, 2),
        "dividend_events": len(credited),
        "dividends_skipped": skipped,
        "price_return": round(price_return, 4),
        "total_return": round(total_return, 4),
        "benchmark_price_return": None if bench_price is None else round(bench_price, 4),
        "benchmark_total_return": None if bench_tr is None else round(bench_tr, 4),
        "excess_price_vs_price_index": (
            None if bench_price is None else round(price_return - bench_price, 4)
        ),
        "excess_total_return": None if bench_tr is None else round(total_return - bench_tr, 4),
    }


def proposal_window_active_returns(
    fund: dict[str, Any],
    started_at: datetime,
    *,
    history_fetcher: HistoryFetcher | None = None,
    tr_benchmark: str = TR_BENCHMARK,
) -> dict[str, Any]:
    """Daily active total returns versus ``tr_benchmark`` from ``started_at``.

    Marks before the measurement epoch are ignored. Dividend cash on an ex-date
    is added to that day's fund return as pounds divided by the prior mark's
    NAV. A missing price history adds no dividend and is counted. The equity
    curve is not rewritten.
    """
    from value_investor.track_statistics import (
        benchmark_period_returns,
        daily_marks,
        period_returns,
    )

    fetcher = history_fetcher or fetch_ticker_history
    empty: dict[str, Any] = {
        "active_returns": [],
        "fund_periods": 0,
        "benchmark_points": 0,
        "dividends_gbp": 0.0,
        "dividends_skipped": 0,
    }
    marks = [mark for mark in _marks(fund) if mark[0] >= started_at]
    if len(marks) < 2:
        return empty
    curve = [
        {
            "at": at.isoformat(),
            "portfolio_value": nav,
            "contributed_capital": contributed,
        }
        for at, nav, contributed in marks
    ]
    daily = daily_marks(curve)
    fund_returns = period_returns(daily)
    if not fund_returns:
        return {**empty, "fund_periods": 0}
    first, last = daily[0][0], daily[-1][0]
    trades = _trades(fund)
    trade_days = [trade["_at"].date() for trade in trades]
    fetch_start = min([first, *trade_days]) if trade_days else first
    tickers = sorted({str(trade["ticker"]) for trade in trades})
    histories = {ticker: fetcher(ticker, fetch_start, last) for ticker in tickers}
    benchmark = fetcher(tr_benchmark, first - timedelta(days=10), last)
    _total, credited, skipped = dividend_credits(
        trades, histories, start=marks[0][0], end=marks[-1][0]
    )
    div_by_day: dict[date, float] = {}
    for row in credited:
        day = date.fromisoformat(str(row["ex_date"]))
        div_by_day[day] = div_by_day.get(day, 0.0) + float(row["gbp"])
    total_returns: list[tuple[date, float]] = []
    for (day0, nav0, _contrib), (day1, price_ret) in zip(daily, fund_returns, strict=False):
        dividend = sum(amount for day, amount in div_by_day.items() if day0 < day <= day1)
        extra = (dividend / nav0) if nav0 > 0 else 0.0
        total_returns.append((day1, price_ret + extra))
    bench = benchmark_period_returns([day for day, _nav, _contrib in daily], benchmark.closes)
    active = [(day, fund_ret - bench[day]) for day, fund_ret in total_returns if day in bench]
    return {
        "active_returns": active,
        "fund_periods": len(fund_returns),
        "benchmark_points": len(benchmark.closes),
        "dividends_gbp": round(sum(div_by_day.values()), 2),
        "dividends_skipped": len(skipped),
    }


def total_return_excess_since(
    fund: dict[str, Any],
    started_at: datetime,
    *,
    history_fetcher: HistoryFetcher = fetch_ticker_history,
    tr_benchmark: str = TR_BENCHMARK,
) -> dict[str, Any] | None:
    """Total-return excess versus ``tr_benchmark`` using marks on or after ``started_at``.

    Needs two equity-curve marks in the window. Returns None when the window
    is thinner than that, so a new measurement epoch does not reuse lifetime
    price excess.
    """
    marks = _marks(fund)
    index = next((i for i, mark in enumerate(marks) if mark[0] >= started_at), None)
    if index is None or len(marks) - index < 2:
        return None
    window = marks[index:]
    trades = _trades(fund)
    first, last = window[0][0].date(), window[-1][0].date()
    tickers = sorted({str(trade["ticker"]) for trade in trades})
    histories = {ticker: history_fetcher(ticker, first, last) for ticker in tickers}
    benchmarks = {
        PRICE_BENCHMARK: history_fetcher(PRICE_BENCHMARK, first, last),
        TR_BENCHMARK: history_fetcher(tr_benchmark, first, last),
    }
    return score_window(marks, trades, histories, benchmarks, start_index=index)


def stress_cost_contamination(
    config: dict[str, Any] | None,
    trades: list[dict[str, Any]],
) -> datetime | None:
    """Last stress-rate trade in a book whose configured costs are fair (L533)."""
    buy_cost = (config or {}).get("buy_cost_pct")
    if buy_cost is None or float(buy_cost) >= STRESS_COST_RATE:
        return None
    last: datetime | None = None
    for trade in trades:
        gross = float(trade.get("gross") or 0.0)
        cost = float(trade.get("cost") or 0.0)
        if gross > 0 and cost / gross >= STRESS_COST_RATE:
            last = trade["_at"]
    return last


def build_total_return_view(
    paper_root: Path = DEFAULT_PAPER_ROOT,
    *,
    history_fetcher: HistoryFetcher = fetch_ticker_history,
    now: datetime | None = None,
) -> dict[str, Any]:
    from value_investor.assessment_model import (
        assessed_track_ids,
        control_track_id,
        primary_track_id,
    )
    from value_investor.paper_automation import learning_track_dirs

    root = Path(paper_root)
    assessed = assessed_track_ids(root)
    loaded: dict[str, dict[str, Any]] = {}
    for track_id, track_dir in learning_track_dirs(root).items():
        fund = _read_json(Path(track_dir) / FUND_FILENAME)
        if not fund:
            continue
        marks = _marks(fund)
        if len(marks) < 2:
            continue
        loaded[track_id] = {
            "marks": marks,
            "trades": _trades(fund),
            "config": _read_json(Path(track_dir) / CONFIG_FILENAME),
            "review": _read_json(Path(track_dir) / REVIEW_FILENAME),
        }

    if not loaded:
        return {
            "schema_version": 1,
            "updated_at": (now or datetime.now(UTC)).isoformat(),
            "observe_only": True,
            "assessed_tracks": assessed,
            "tracks": {},
            "pairs": {},
        }

    first = min(row["marks"][0][0] for row in loaded.values()).date()
    last = max(row["marks"][-1][0] for row in loaded.values()).date()
    tickers = sorted({str(t["ticker"]) for row in loaded.values() for t in row["trades"]})
    histories = {ticker: history_fetcher(ticker, first, last) for ticker in tickers}
    benchmarks = {
        PRICE_BENCHMARK: history_fetcher(PRICE_BENCHMARK, first, last),
        TR_BENCHMARK: history_fetcher(TR_BENCHMARK, first, last),
    }

    tracks: dict[str, Any] = {}
    for track_id, row in sorted(loaded.items()):
        lifetime = score_window(row["marks"], row["trades"], histories, benchmarks)
        if lifetime is None:
            continue
        published = ((row["review"] or {}).get("metrics") or {}).get("excess_after_costs")
        entry: dict[str, Any] = {
            "lifetime": lifetime,
            "published_excess_after_costs": published,
        }
        contaminated_until = stress_cost_contamination(row["config"], row["trades"])
        if contaminated_until is not None:
            clean_index = next(
                (i for i, mark in enumerate(row["marks"]) if mark[0] > contaminated_until),
                None,
            )
            entry["stress_cost_trades_until"] = contaminated_until.isoformat()
            entry["clean_epoch"] = (
                None
                if clean_index is None
                else score_window(
                    row["marks"], row["trades"], histories, benchmarks, start_index=clean_index
                )
            )
        tracks[track_id] = entry

    pairs: dict[str, Any] = {}
    left_id, right_id = primary_track_id(root), control_track_id(root)
    if left_id in loaded and right_id in loaded:
        common_start = max(loaded[left_id]["marks"][0][0], loaded[right_id]["marks"][0][0])
        scored = {}
        for track_id in (left_id, right_id):
            marks = loaded[track_id]["marks"]
            index = next((i for i, m in enumerate(marks) if m[0] >= common_start), None)
            scored[track_id] = (
                None
                if index is None
                else score_window(
                    marks, loaded[track_id]["trades"], histories, benchmarks, start_index=index
                )
            )
        left, right = scored[left_id], scored[right_id]
        if left and right:
            pairs[PRIMARY_VS_CONTROL] = {
                "left": left_id,
                "right": right_id,
                "start": common_start.isoformat(),
                "left_total_return": left["total_return"],
                "right_total_return": right["total_return"],
                "difference": round(left["total_return"] - right["total_return"], 4),
                "note": (
                    "Primary minus control (assessment_model.json) on their common window. "
                    "Positive means the primary's filter added value."
                ),
            }

    return {
        "schema_version": 1,
        "updated_at": (now or datetime.now(UTC)).isoformat(),
        "observe_only": True,
        "benchmarks": {
            "price": PRICE_BENCHMARK,
            "total_return": TR_BENCHMARK,
            "total_return_note": "SPDR FTSE UK All Share UCITS ETF (Acc) as All-Share TR proxy",
        },
        "method": {
            "nav": "equity_curve marks (market prices)",
            "dividends": (
                "shares held over each ex-date × paper price × (dividend ÷ prior close); "
                "credited as cash, not reinvested"
            ),
            "benchmark_alignment": "close before each mark date",
            "misstatement_gap": MISSTATEMENT_GAP,
        },
        "assessed_tracks": assessed,
        "tracks": tracks,
        "pairs": pairs,
    }


def refresh_total_return_view(
    paper_root: Path = DEFAULT_PAPER_ROOT,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    history_fetcher: HistoryFetcher = fetch_ticker_history,
    persist: bool = True,
) -> dict[str, Any]:
    payload = build_total_return_view(paper_root, history_fetcher=history_fetcher)
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_finding_from_total_return_view(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Warn when an assessed book's published excess is off by sign or ≥5pp.

    Frozen books keep their rows in ``tracks`` (the scoreboard's final records
    read them) but no longer raise this finding.
    """
    lines: list[str] = []
    for track_id in payload.get("assessed_tracks") or []:
        entry = (payload.get("tracks") or {}).get(track_id) or {}
        published = entry.get("published_excess_after_costs")
        view = entry.get("clean_epoch") or entry.get("lifetime") or {}
        tr_excess = view.get("excess_total_return")
        if published is None or tr_excess is None:
            continue
        flipped = (published > 0) != (tr_excess > 0)
        if flipped or abs(tr_excess - published) >= MISSTATEMENT_GAP:
            basis = "clean epoch" if entry.get("clean_epoch") else "lifetime"
            lines.append(
                f"{track_id}: published {published:+.1%} vs total-return {tr_excess:+.1%} "
                f"({basis}, dividends £{view.get('dividends_gbp', 0):.2f})"
            )
    if not lines:
        return None
    return {
        "severity": "warn",
        "category": "paper",
        "title": FINDING_TITLE,
        "summary": (
            "Published excess vs ^FTSE (price index, cost-basis NAV, no dividends) differs "
            f"from total-return excess vs {TR_BENCHMARK} by sign or ≥{MISSTATEMENT_GAP:.0%}: "
            + "; ".join(lines)
            + ". Cite the total-return view for performance. "
            "See docs/ops/total-return-view.md."
        ),
        "auto_fixable": False,
    }
