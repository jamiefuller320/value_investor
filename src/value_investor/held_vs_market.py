"""Held-book vs whole-market equivalent series for dashboard market cards.

The chart is **branch-ready**: extra series of ``kind=branch`` overlay the same
dates once a knob-changed book is applied. Do not spawn a warm-started twin
per knob (N99) — attach the overlay here.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.backtest import BENCHMARK_TICKER
from value_investor.library_sim import MARKET_BENCHMARKS, benchmark_for_market
from value_investor.macro_context import DEFAULT_MACRO_ROOT, EQUITY_INDEX_MARKERS, domain_for_market
from value_investor.price_charts import chart_filename
from value_investor.storage import read_json

SCHEMA_VERSION = 1
HELD_SERIES_ID = "held"
MARKET_SERIES_ID = "market"
MAX_POINTS = 180
LIVE_MARKET_ID = "ftse350"

# Macro snapshot marker key → Yahoo index symbol (dated files, no live fetch).
_MACRO_INDEX_MARKERS = EQUITY_INDEX_MARKERS

_DATED_MACRO = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")

BRANCH_PALETTE = ("#7c3aed", "#b8860b", "#0f766e", "#be185d")

SERIES_HELD = {
    "id": HELD_SERIES_ID,
    "label": "Held book",
    "kind": "held",
    "color": "#2b6cb0",
}
SERIES_MARKET = {
    "id": MARKET_SERIES_ID,
    "label": "Market equivalent",
    "kind": "market",
    "color": "#64748b",
}


def _safe_read(path: Path | None) -> dict[str, Any] | list[Any] | None:
    if path is None or not Path(path).exists():
        return None
    try:
        return read_json(Path(path))
    except Exception:  # noqa: BLE001 — dashboard must still assemble
        return None


def _as_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def date_key(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.date().isoformat()
    except ValueError:
        return None


def benchmark_ticker_for_market(market_id: str) -> str:
    if market_id == LIVE_MARKET_ID:
        return BENCHMARK_TICKER
    if market_id in MARKET_BENCHMARKS:
        return MARKET_BENCHMARKS[market_id]
    marker = EQUITY_INDEX_MARKERS.get(domain_for_market(market_id))
    if marker:
        return marker[1]
    return benchmark_for_market(market_id)


def empty_held_vs_market(
    *,
    market_id: str,
    currency: str | None = None,
    reason: str = "No paper marks yet",
    benchmark_ticker: str | None = None,
) -> dict[str, Any]:
    ticker = benchmark_ticker or benchmark_ticker_for_market(market_id)
    market_series = {**SERIES_MARKET, "label": f"{ticker} equivalent"}
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "empty",
        "reason": reason,
        "market_id": market_id,
        "source": None,
        "paper_instrument": None,
        "currency": currency,
        "benchmark_ticker": ticker,
        "held_path": None,
        "market_path": None,
        "branch_ready": True,
        "note": (
            "Held-stock value vs the same capital in the local index. "
            "Knob-changed branches overlay on this chart when applied — "
            "do not spawn a twin book per knob."
        ),
        "points": [],
        "series": [dict(SERIES_HELD), market_series],
        "branches": [],
        "last": None,
    }


def holdings_shares(fund: dict[str, Any] | None) -> dict[str, float]:
    holdings = _as_dict((_as_dict(fund)).get("holdings"))
    out: dict[str, float] = {}
    for ticker, pos in holdings.items():
        shares = _float(pos.get("shares") if isinstance(pos, dict) else pos)
        if shares and shares > 0:
            out[str(ticker)] = shares
    return out


def _curve_points(curve: list[Any]) -> list[dict[str, Any]]:
    """Collapse equity marks to one row per calendar date (last mark wins)."""
    by_date: dict[str, dict[str, Any]] = {}
    for raw in curve:
        row = _as_dict(raw)
        day = date_key(str(row.get("at") or row.get("run_at") or ""))
        if not day:
            continue
        nav = _float(row.get("portfolio_value") or row.get("nav") or row.get("value"))
        cash = _float(row.get("cash")) or 0.0
        if nav is None:
            continue
        held_stock = max(0.0, nav - cash)
        by_date[day] = {
            "date": day,
            "held": round(held_stock, 2),
            "nav": round(nav, 2),
            "held_stock": round(held_stock, 2),
            "cash": round(cash, 2),
            "positions": int(row.get("positions") or 0),
            "contributed_capital": _float(row.get("contributed_capital")),
            "branches": {},
        }
    return [by_date[day] for day in sorted(by_date)]


def _forward_fill(series: dict[str, float], day: str) -> float | None:
    if day in series:
        return series[day]
    prior = [key for key in series if key <= day]
    if not prior:
        return None
    return series[max(prior)]


def _market_values(
    dates: list[str],
    bench_closes: dict[str, float],
    *,
    start_value: float,
    start_date: str,
) -> tuple[dict[str, float], str]:
    """Scale ``start_value`` by index return from the first available close."""
    if not dates or start_value <= 0 or not bench_closes:
        return {}, "none"
    base_day = start_date
    base_px = _forward_fill(bench_closes, start_date)
    if base_px is None:
        later = [key for key in sorted(bench_closes) if key >= start_date]
        if not later:
            return {}, "none"
        base_day = later[0]
        base_px = bench_closes[base_day]
    if not base_px or base_px <= 0:
        return {}, "none"
    out: dict[str, float] = {}
    for day in dates:
        px = _forward_fill(bench_closes, day)
        if px is None or px <= 0:
            continue
        out[day] = round(start_value * (px / base_px), 2)
    path = "index_levels_aligned" if base_day != start_date else "index_levels"
    return out, path


def _endpoint_market(
    dates: list[str],
    *,
    start_value: float,
    benchmark_return: float | None,
) -> tuple[dict[str, float], str]:
    if not dates or start_value <= 0 or benchmark_return is None:
        return {}, "none"
    end_value = round(start_value * (1.0 + float(benchmark_return)), 2)
    return {dates[0]: round(start_value, 2), dates[-1]: end_value}, "period_return_endpoints"


def _downsample(
    points: list[dict[str, Any]], *, max_points: int = MAX_POINTS
) -> list[dict[str, Any]]:
    if len(points) <= max_points:
        return points
    step = max(1, len(points) // max_points)
    sampled = points[::step]
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled


def densify_held_from_charts(
    *,
    holdings: dict[str, float],
    closes_by_ticker: dict[str, dict[str, float]],
    start_date: str,
    end_date: str | None = None,
    cash_by_date: dict[str, float] | None = None,
    positions: int | None = None,
) -> list[dict[str, Any]]:
    """Mark the *current* book on daily chart closes from ``start_date`` onward."""
    if not holdings or not closes_by_ticker:
        return []
    covered = [ticker for ticker in holdings if ticker in closes_by_ticker]
    if not covered or len(covered) < max(1, int(0.5 * len(holdings))):
        return []
    dates: set[str] = set()
    for ticker in covered:
        dates.update(closes_by_ticker[ticker])
    ordered = [day for day in sorted(dates) if day >= start_date]
    if end_date:
        ordered = [day for day in ordered if day <= end_date]
    if len(ordered) < 2:
        return []
    cash_by_date = cash_by_date or {}
    rows: list[dict[str, Any]] = []
    for day in ordered:
        total = 0.0
        priced = 0
        for ticker, shares in holdings.items():
            px = _forward_fill(closes_by_ticker.get(ticker) or {}, day)
            if px is None or px <= 0:
                continue
            total += shares * px
            priced += 1
        if priced < max(1, int(0.5 * len(holdings))):
            continue
        cash = _forward_fill(cash_by_date, day) or 0.0
        held_stock = round(total, 2)
        rows.append(
            {
                "date": day,
                "held": held_stock,
                "nav": round(held_stock + cash, 2),
                "held_stock": held_stock,
                "cash": round(cash, 2),
                "positions": int(positions or len(holdings)),
                "contributed_capital": None,
                "branches": {},
            }
        )
    return rows


def _last_summary(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not points:
        return None
    row = points[-1]
    held = _float(row.get("held"))
    market = _float(row.get("market"))
    excess = None
    if held is not None and market is not None and market > 0:
        excess = round((held / market) - 1.0, 6)
    return {
        "date": row.get("date"),
        "held": held,
        "market": market,
        "nav": _float(row.get("nav")),
        "positions": row.get("positions"),
        "excess_pct": excess,
    }


def _series_defs(
    *,
    benchmark_ticker: str,
    branches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    series = [
        dict(SERIES_HELD),
        {**SERIES_MARKET, "label": f"{benchmark_ticker} equivalent"},
    ]
    for index, branch in enumerate(branches):
        color = branch.get("color") or BRANCH_PALETTE[index % len(BRANCH_PALETTE)]
        series.append(
            {
                "id": f"branch:{branch['id']}",
                "label": branch.get("label") or branch["id"],
                "kind": "branch",
                "status": branch.get("status") or "active",
                "color": color,
                "knobs": branch.get("knobs") or {},
            }
        )
    return series


def build_held_vs_market_payload(
    *,
    market_id: str,
    marks: list[dict[str, Any]],
    bench_closes: dict[str, float] | None = None,
    benchmark_return: float | None = None,
    branches: list[dict[str, Any]] | None = None,
    source: str = "paper_fund",
    paper_instrument: str | None = "buy_tier_level",
    currency: str | None = None,
    benchmark_ticker: str | None = None,
    held_path: str = "equity_marks",
    note: str | None = None,
) -> dict[str, Any]:
    """Assemble the dashboard series. ``marks`` already have ``held`` / date keys."""
    ticker = benchmark_ticker or benchmark_ticker_for_market(market_id)
    branch_rows = [row for row in (branches or []) if isinstance(row, dict) and row.get("id")]
    if not marks:
        payload = empty_held_vs_market(
            market_id=market_id,
            currency=currency,
            reason="No dated marks",
            benchmark_ticker=ticker,
        )
        payload["source"] = source
        payload["paper_instrument"] = paper_instrument
        return payload

    invested = [row for row in marks if (_float(row.get("held")) or 0) > 0]
    start_row = invested[0] if invested else marks[0]
    start_date = str(start_row["date"])
    start_value = float(start_row.get("held") or 0.0)
    dates = [str(row["date"]) for row in marks]
    market_map, market_path = _market_values(
        dates,
        dict(bench_closes or {}),
        start_value=start_value,
        start_date=start_date,
    )
    if not market_map:
        market_map, market_path = _endpoint_market(
            dates,
            start_value=start_value,
            benchmark_return=benchmark_return,
        )

    points: list[dict[str, Any]] = []
    for row in marks:
        day = str(row["date"])
        point = dict(row)
        point["market"] = market_map.get(day)
        branch_values = dict(point.get("branches") or {})
        for branch in branch_rows:
            values = _as_dict(branch.get("values"))
            if day in values:
                branch_values[str(branch["id"])] = _float(values[day])
        point["branches"] = branch_values
        points.append(point)
    points = _downsample(points)

    payload = empty_held_vs_market(
        market_id=market_id,
        currency=currency,
        reason="",
        benchmark_ticker=ticker,
    )
    payload.update(
        {
            "status": "ok",
            "reason": None,
            "source": source,
            "paper_instrument": paper_instrument,
            "held_path": held_path,
            "market_path": market_path if market_map else "none",
            "points": points,
            "series": _series_defs(benchmark_ticker=ticker, branches=branch_rows),
            "branches": [
                {
                    "id": row["id"],
                    "label": row.get("label") or row["id"],
                    "kind": "branch",
                    "status": row.get("status")
                    or ("pending" if not _as_dict(row.get("values")) else "active"),
                    "knobs": row.get("knobs") or {},
                    "point_count": len(_as_dict(row.get("values"))),
                }
                for row in branch_rows
            ],
            "last": _last_summary(points),
        }
    )
    if note:
        payload["note"] = note
    return payload


def merge_branch_series(
    payload: dict[str, Any],
    *,
    branch_id: str,
    label: str | None = None,
    values: dict[str, float] | None = None,
    knobs: dict[str, Any] | None = None,
    status: str = "active",
) -> dict[str, Any]:
    """Attach or replace one knob-changed overlay. Safe to call with empty values."""
    existing = [
        row
        for row in _as_list(payload.get("branches"))
        if str(_as_dict(row).get("id")) != str(branch_id)
    ]
    branch = {
        "id": str(branch_id),
        "label": label or branch_id,
        "kind": "branch",
        "status": status,
        "knobs": knobs or {},
        "values": {
            str(day): float(val) for day, val in (values or {}).items() if _float(val) is not None
        },
    }
    points = []
    for row in _as_list(payload.get("points")):
        point = dict(row)
        branches = dict(point.get("branches") or {})
        if str(point.get("date")) in branch["values"]:
            branches[str(branch_id)] = branch["values"][str(point["date"])]
        point["branches"] = branches
        points.append(point)
    payload = dict(payload)
    payload["points"] = points
    payload["branches"] = existing + [
        {
            "id": branch["id"],
            "label": branch["label"],
            "kind": "branch",
            "status": branch["status"] if branch["values"] else "pending",
            "knobs": branch["knobs"],
            "point_count": len(branch["values"]),
        }
    ]
    payload["series"] = _series_defs(
        benchmark_ticker=str(payload.get("benchmark_ticker") or BENCHMARK_TICKER),
        branches=payload["branches"],
    )
    payload["branch_ready"] = True
    payload["last"] = _last_summary(points)
    return payload


def load_macro_index_closes(macro_root: Path | None = None) -> dict[str, dict[str, float]]:
    """Dated macro snapshots → ``{symbol: {date: close}}``. No network."""
    root = Path(macro_root or DEFAULT_MACRO_ROOT)
    out: dict[str, dict[str, float]] = {}
    if not root.exists():
        return out
    for path in sorted(root.iterdir()):
        match = _DATED_MACRO.match(path.name)
        if not match:
            continue
        payload = _as_dict(_safe_read(path))
        domains = _as_dict(payload.get("domains"))
        for domain, (marker_key, symbol) in _MACRO_INDEX_MARKERS.items():
            marker = _as_dict(_as_dict(domains.get(domain)).get("markers")).get(marker_key)
            value = _float(_as_dict(marker).get("value"))
            as_of = date_key(str(_as_dict(marker).get("as_of") or match.group(1)))
            if value is None or not as_of:
                continue
            out.setdefault(symbol, {})[as_of] = value
    return out


def load_chart_closes(
    charts_dir: Path | None,
    tickers: list[str] | dict[str, float],
) -> dict[str, dict[str, float]]:
    if charts_dir is None:
        return {}
    root = Path(charts_dir)
    names = list(tickers) if not isinstance(tickers, dict) else list(tickers)
    out: dict[str, dict[str, float]] = {}
    for ticker in names:
        payload = _as_dict(_safe_read(root / chart_filename(ticker)))
        dates = _as_list(payload.get("dates"))
        closes = _as_list(payload.get("closes"))
        if not dates or len(dates) != len(closes):
            continue
        series: dict[str, float] = {}
        for day_raw, close_raw in zip(dates, closes, strict=False):
            day = date_key(str(day_raw))
            close = _float(close_raw)
            if day and close is not None and close > 0:
                series[day] = close
        if series:
            out[str(ticker)] = series
    return out


def marks_from_fund(fund: dict[str, Any] | None) -> list[dict[str, Any]]:
    return _curve_points(_as_list(_as_dict(fund).get("equity_curve")))


def marks_from_observe_sim(
    observe: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], float | None]:
    payload = _as_dict(observe)
    tracks = _as_dict(payload.get("tracks"))
    screen = _as_dict(tracks.get("screen_rules") or tracks.get("rules"))
    if not screen:
        return [], _float(payload.get("benchmark_return"))
    marks = _curve_points(_as_list(screen.get("equity_curve")))
    bench_ret = _float(screen.get("benchmark_return"))
    if bench_ret is None:
        bench_ret = _float(payload.get("benchmark_return"))
    return marks, bench_ret


def assemble_held_vs_market(
    market_id: str,
    *,
    fund: dict[str, Any] | None = None,
    observe: dict[str, Any] | None = None,
    charts_dir: Path | None = None,
    bench_closes: dict[str, float] | None = None,
    branches: list[dict[str, Any]] | None = None,
    currency: str | None = None,
    allow_chart_densify: bool = False,
) -> dict[str, Any]:
    """Pick the paper book when present, else the observe-sim clock."""
    ticker = benchmark_ticker_for_market(market_id)
    fund_marks = marks_from_fund(fund)
    observe_marks, observe_bench_ret = marks_from_observe_sim(observe)
    if fund_marks:
        marks = fund_marks
        source = "paper_fund"
        instrument = "buy_tier_level"
        held_path = "equity_marks"
        bench_ret = None
        if allow_chart_densify:
            holdings = holdings_shares(fund)
            start = next((row["date"] for row in fund_marks if row.get("held")), None)
            if holdings and start:
                cash_by_date = {row["date"]: float(row.get("cash") or 0.0) for row in fund_marks}
                dense = densify_held_from_charts(
                    holdings=holdings,
                    closes_by_ticker=load_chart_closes(charts_dir, holdings),
                    start_date=str(start),
                    cash_by_date=cash_by_date,
                    positions=len(holdings),
                )
                if len(dense) >= 2:
                    marks = dense
                    held_path = "current_book_marked"
        fund_ccy = _as_dict(_as_dict(fund).get("config")).get("reporting_currency")
        currency = currency or (str(fund_ccy) if fund_ccy else None)
    elif observe_marks:
        marks = observe_marks
        source = "observe_sim"
        instrument = "observe_sim"
        held_path = "equity_marks"
        bench_ret = observe_bench_ret
    else:
        return empty_held_vs_market(
            market_id=market_id,
            currency=currency,
            reason="No paper book or observe-sim marks",
            benchmark_ticker=ticker,
        )

    return build_held_vs_market_payload(
        market_id=market_id,
        marks=marks,
        bench_closes=bench_closes,
        benchmark_return=bench_ret,
        branches=branches,
        source=source,
        paper_instrument=instrument,
        currency=currency,
        benchmark_ticker=ticker,
        held_path=held_path,
    )


def bench_closes_for_market(
    market_id: str,
    *,
    macro_closes: dict[str, dict[str, float]] | None = None,
) -> dict[str, float]:
    ticker = benchmark_ticker_for_market(market_id)
    series = dict((macro_closes or {}).get(ticker) or {})
    if series:
        return series
    domain = domain_for_market(market_id)
    marker = _MACRO_INDEX_MARKERS.get(domain)
    if marker:
        return dict((macro_closes or {}).get(marker[1]) or {})
    return {}


__all__ = [
    "HELD_SERIES_ID",
    "MARKET_SERIES_ID",
    "SCHEMA_VERSION",
    "assemble_held_vs_market",
    "bench_closes_for_market",
    "benchmark_ticker_for_market",
    "build_held_vs_market_payload",
    "densify_held_from_charts",
    "empty_held_vs_market",
    "holdings_shares",
    "load_chart_closes",
    "load_macro_index_closes",
    "marks_from_fund",
    "marks_from_observe_sim",
    "merge_branch_series",
]
