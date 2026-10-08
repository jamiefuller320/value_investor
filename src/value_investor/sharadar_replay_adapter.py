"""Build the historical screen replay inputs from Sharadar bulk tables.

Reads the licensed bulk exports (fundamentals, stocks, tickers, actions, sp500)
from a local directory outside the repository and writes the three files that
``ftse-historical-replay run`` consumes. The registration's ``universe_rule``
picks the names: S&P 500 members (hsr-v1) or US market-cap ranks (hsr-mid-v1).

* ``panel.csv.gz`` — one row per (month-end rebalance, universe member) with the
  Yahoo-style metric columns the library screen reads, built only from filings
  available at least ``FILING_LAG_DAYS`` before the rebalance (plus
  ``total_assets_prev``, which only the model-mix search reads).
* ``prices.csv.gz`` — total-return closes (``closeadj``) on rebalance dates, on
  each horizon's exit dates, and on every delisted name's last trading date.
* ``terminal_baseline.csv`` / ``terminal_sensitivity.csv`` — delisting haircuts.
* ``daily.csv.gz`` — adjusted daily OHLC for every member, for the tactical
  slice replay and the rule search (``rule_search``).

``build_report.json`` holds coverage counts only (no per-ticker data), so it can
be pasted into the PR or runbook. Nothing here is part of the fingerprinted
screen code.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FILING_LAG_DAYS = 2
STALE_FILING_DAYS = 456
STOCKS_CHUNK_ROWS = 2_000_000
DAILY_HISTORY_DAYS = 420

TABLE_ALIASES: dict[str, tuple[str, ...]] = {
    "fundamentals": ("fundamentals", "sf1"),
    "stocks": ("stocks", "sep"),
    "tickers": ("tickers",),
    "actions": ("actions",),
    "sp500": ("sp500",),
}

# Delisted names that left through a merger or acquisition keep the baseline
# haircut in the sensitivity variant. Sharadar puts the departing company in
# ``ticker`` for these actions ...
MERGER_SELF_ACTIONS = frozenset({"acquisitionby", "mergerto"})
# ... and in ``contraticker`` for these.
MERGER_CONTRA_ACTIONS = frozenset({"mergerfrom", "acquisitionof"})

PANEL_COLUMNS = (
    "as_of",
    "ticker",
    "name",
    "sector",
    "market_cap",
    "trailing_pe",
    "price_to_book",
    "dividend_yield",
    "current_ratio",
    "debt_to_equity",
    "return_on_equity",
    "return_on_assets",
    "profit_margins",
    "revenue_growth",
    "earnings_growth",
    "free_cashflow",
    "operating_cashflow",
    "enterprise_value",
    "ebitda",
    "ebit",
    "total_revenue",
    "total_debt",
    "total_cash",
    "book_value",
    "total_assets",
    "total_current_assets",
    "total_liabilities",
    "total_current_liabilities",
    "net_income",
    "interest_expense",
    "gross_margin",
    "ncav",
    "shares_outstanding",
    "last_price",
    "return_on_assets_prev",
    "gross_margin_prev",
    "current_ratio_bs",
    "current_ratio_bs_prev",
    "leverage",
    "leverage_prev",
    "asset_turnover",
    "asset_turnover_prev",
    "shares_outstanding_prev",
    "total_assets_prev",
)


# --- Loading ------------------------------------------------------------------------------


def find_table(sharadar_dir: Path, table: str) -> Path:
    """Locate a bulk export by table name (``SHARADAR_SF1_x.zip``, ``fundamentals.csv``, ...)."""
    aliases = TABLE_ALIASES[table]
    candidates = sorted(
        p
        for p in Path(sharadar_dir).iterdir()
        if p.is_file()
        and p.name.lower().endswith((".csv", ".csv.gz", ".zip"))
        and any(
            p.name.lower().startswith((alias, f"sharadar_{alias}_", f"sharadar_{alias}."))
            for alias in aliases
        )
    )
    if not candidates:
        raise FileNotFoundError(f"No {table} export in {sharadar_dir} (looked for {aliases})")
    return candidates[-1]


def _dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def load_sp500(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=lambda c: c in {"date", "action", "ticker"})
    frame["date"] = _dates(frame["date"])
    frame["action"] = frame["action"].astype(str).str.lower().str.strip()
    frame["ticker"] = frame["ticker"].astype(str).str.strip()
    return frame.dropna(subset=["date"])


def load_tickers(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str)
    if "table" in frame.columns:
        sf1 = frame.loc[frame["table"].str.upper() == "SF1"]
        frame = sf1 if not sf1.empty else frame
    frame = frame.drop_duplicates(subset=["ticker"], keep="last")
    keep = [
        c for c in ("ticker", "name", "sector", "currency", "isdelisted", "category") if c in frame
    ]
    return frame[keep].set_index("ticker")


def load_actions(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path, usecols=lambda c: c in {"date", "action", "ticker", "contraticker"}, dtype=str
    )
    frame["action"] = frame["action"].str.lower().str.strip()
    return frame


def load_fundamentals(path: Path, tickers: set[str]) -> pd.DataFrame:
    """ART and ARQ rows for ``tickers``; ``filed`` is the SEC filing date."""
    chunks = []
    for chunk in pd.read_csv(path, chunksize=500_000, low_memory=False):
        chunk = chunk.loc[chunk["ticker"].isin(tickers) & chunk["dimension"].isin(("ART", "ARQ"))]
        if not chunk.empty:
            chunks.append(chunk)
    if not chunks:
        return pd.DataFrame(columns=["ticker", "dimension", "filed", "calendardate"])
    frame = pd.concat(chunks, ignore_index=True)
    filed_col = "datekey" if "datekey" in frame.columns else "date"
    frame["filed"] = _dates(frame[filed_col])
    frame["calendardate"] = _dates(frame["calendardate"])
    frame = frame.drop(columns=[c for c in ("datekey", "date") if c in frame.columns])
    return frame.dropna(subset=["filed", "calendardate"])


def load_stocks(path: Path, tickers: set[str]) -> pd.DataFrame:
    """Daily split-adjusted OHLC plus ``closeadj`` and ``closeunadj`` for ``tickers``."""
    cols = {"ticker", "date", "open", "high", "low", "close", "closeadj", "closeunadj"}
    chunks = []
    for chunk in pd.read_csv(path, usecols=lambda c: c in cols, chunksize=STOCKS_CHUNK_ROWS):
        chunk = chunk.loc[chunk["ticker"].isin(tickers)]
        if not chunk.empty:
            chunks.append(chunk)
    frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=list(cols))
    frame["date"] = _dates(frame["date"])
    for col in ("open", "high", "low", "closeunadj"):
        if col not in frame.columns:
            frame[col] = frame["close"]
    return frame.dropna(subset=["date"]).sort_values(["ticker", "date"]).reset_index(drop=True)


# --- Universe and calendar ---------------------------------------------------------------


def membership_on(sp500: pd.DataFrame, dates: Iterable[pd.Timestamp]) -> dict[pd.Timestamp, set]:
    """S&P 500 members on each date.

    Starts from the latest ``historical`` snapshot on or before the date and
    applies later ``added`` / ``removed`` events up to and including it. Before
    the first snapshot, walks back from the ``current`` list by undoing events
    after the date.
    """
    snapshots = {
        d: set(group["ticker"])
        for d, group in sp500.loc[sp500["action"] == "historical"].groupby("date")
    }
    snap_dates = sorted(snapshots)
    current = set(sp500.loc[sp500["action"] == "current", "ticker"])
    events = sp500.loc[sp500["action"].isin(("added", "removed"))].sort_values("date")
    out: dict[pd.Timestamp, set] = {}
    for raw in dates:
        d = pd.Timestamp(raw).normalize()
        prior = [s for s in snap_dates if s <= d]
        if prior:
            members = set(snapshots[prior[-1]])
            later = events.loc[(events["date"] > prior[-1]) & (events["date"] <= d)]
            for action, ticker in later[["action", "ticker"]].itertuples(index=False):
                if action == "added":
                    members.add(ticker)
                else:
                    members.discard(ticker)
        else:
            members = set(current)
            undo = events.loc[events["date"] > d].iloc[::-1]
            for action, ticker in undo[["action", "ticker"]].itertuples(index=False):
                if action == "added":
                    members.discard(ticker)
                else:
                    members.add(ticker)
        out[d] = members
    return out


def ever_members(sp500: pd.DataFrame, first: pd.Timestamp, last: pd.Timestamp) -> set[str]:
    """Every name in the index at any point in ``[first, last]``."""
    start = membership_on(sp500, [first])[pd.Timestamp(first).normalize()]
    in_window = (sp500["date"] > first) & (sp500["date"] <= last)
    added = sp500.loc[in_window & sp500["action"].isin(("added", "historical")), "ticker"]
    return start | set(added)


def eligible_common_stocks(tickers: pd.DataFrame) -> set[str]:
    """US domestic common stocks reporting in USD, listed or delisted.

    The ``exchange`` field is today's listing, so filtering on it would drop
    names that later fell to OTC or delisted (survivorship). Size ranks keep
    the universe to listed-scale companies instead.
    """
    category = tickers.get("category", pd.Series(dtype=str)).fillna("").astype(str)
    currency = tickers.get("currency", pd.Series(dtype=str)).fillna("USD").astype(str)
    ok = category.str.startswith("Domestic Common Stock") & (currency.str.upper() == "USD")
    return set(tickers.index[ok.reindex(tickers.index, fill_value=False)].astype(str))


def load_trading_calendar(path: Path) -> list[pd.Timestamp]:
    dates: set[str] = set()
    for chunk in pd.read_csv(path, usecols=["date"], chunksize=STOCKS_CHUNK_ROWS):
        dates.update(chunk["date"].astype(str).unique())
    return sorted(pd.to_datetime(list(dates)).normalize())


def load_closes_on(path: Path, tickers: set[str], dates: set[pd.Timestamp]) -> pd.DataFrame:
    """Split-adjusted ``close`` for ``tickers`` on ``dates`` only (a light pass over SEP)."""
    wanted = {d.strftime("%Y-%m-%d") for d in dates}
    chunks = []
    for chunk in pd.read_csv(
        path, usecols=lambda c: c in {"ticker", "date", "close"}, chunksize=STOCKS_CHUNK_ROWS
    ):
        chunk = chunk.loc[chunk["ticker"].isin(tickers) & chunk["date"].astype(str).isin(wanted)]
        if not chunk.empty:
            chunks.append(chunk)
    frame = (
        pd.concat(chunks, ignore_index=True)
        if chunks
        else pd.DataFrame(columns=["ticker", "date", "close"])
    )
    frame["date"] = _dates(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["date", "close"])


def load_market_caps(path: Path, tickers: set[str]) -> pd.DataFrame:
    """ART ``marketcap`` struck at each filing date, for ranking the universe."""
    chunks = []
    for chunk in pd.read_csv(
        path,
        usecols=lambda c: c in {"ticker", "dimension", "datekey", "date", "marketcap"},
        chunksize=500_000,
    ):
        chunk = chunk.loc[chunk["ticker"].isin(tickers) & (chunk["dimension"] == "ART")]
        if not chunk.empty:
            chunks.append(chunk)
    if not chunks:
        return pd.DataFrame(columns=["ticker", "filed", "marketcap"])
    frame = pd.concat(chunks, ignore_index=True)
    filed_col = "datekey" if "datekey" in frame.columns else "date"
    frame["filed"] = _dates(frame[filed_col])
    frame["marketcap"] = pd.to_numeric(frame["marketcap"], errors="coerce")
    return frame[["ticker", "filed", "marketcap"]].dropna()


def cap_rank_membership(
    caps: pd.DataFrame,
    closes: pd.DataFrame,
    rebalances: Iterable[pd.Timestamp],
    *,
    rank_from: int,
    rank_to: int,
) -> dict[pd.Timestamp, set]:
    """Names ranked ``rank_from``..``rank_to`` (1 = largest) by market cap on each date.

    Market cap is the latest filing's ``marketcap`` (filed at least
    ``FILING_LAG_DAYS`` before, at most ``STALE_FILING_DAYS`` old) rolled forward
    by the split-adjusted close from the last ranking date on or before the
    filing. ``closes`` must carry those earlier dates too. The roll misses up to
    a month of price change at the filing, which only moves names near the rank
    boundaries and uses nothing from after the date.
    """
    dates = sorted({pd.Timestamp(d).normalize() for d in rebalances})
    rows = closes.loc[closes["date"].isin(dates), ["ticker", "date", "close"]].rename(
        columns={"close": "close_d"}
    )
    rows = rows.loc[rows["close_d"] > 0].assign(
        cutoff=lambda f: f["date"] - pd.Timedelta(days=FILING_LAG_DAYS)
    )
    rows = _asof(rows, caps.sort_values("filed"), left_on="cutoff", right_on="filed")
    rows = rows.dropna(subset=["filed", "marketcap"])
    rows = rows.loc[(rows["date"] - rows["filed"]).dt.days <= STALE_FILING_DAYS]
    marks = closes.rename(columns={"date": "mark_date", "close": "close_m"})
    rows = _asof(rows, marks, left_on="filed", right_on="mark_date")
    rows["cap"] = rows["marketcap"] * _ratio(rows["close_d"], rows["close_m"], positive_den=True)
    rows = rows.loc[rows["cap"] > 0]
    out: dict[pd.Timestamp, set] = {}
    for d in dates:
        ranked = rows.loc[rows["date"] == d].sort_values(["cap", "ticker"], ascending=[False, True])
        out[d] = set(ranked["ticker"].iloc[rank_from - 1 : rank_to])
    return out


def month_end_trading_days(
    trading_days: Iterable[pd.Timestamp], first: pd.Timestamp, last: pd.Timestamp
) -> list[pd.Timestamp]:
    """Last trading day of each calendar month whose month falls in ``[first, last]``."""
    days = pd.Series(sorted(set(pd.to_datetime(list(trading_days)).normalize())))
    if days.empty:
        return []
    month_ends = days.groupby(days.dt.to_period("M")).max()
    lo, hi = pd.Timestamp(first).to_period("M"), pd.Timestamp(last).to_period("M")
    return [d for period, d in month_ends.items() if lo <= period <= hi]


# --- Point-in-time metrics -----------------------------------------------------------------


def _num(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce")


def _ratio(num: pd.Series, den: pd.Series, *, positive_den: bool = False) -> pd.Series:
    ok = den > 0 if positive_den else den.notna() & (den != 0)
    return (num / den).where(ok)


def _asof(left: pd.DataFrame, right: pd.DataFrame, *, left_on: str, right_on: str) -> pd.DataFrame:
    """Latest ``right`` row per ticker with ``right_on`` <= ``left_on``."""
    if right.empty:
        return left.assign(**{c: np.nan for c in right.columns if c not in left.columns})
    return pd.merge_asof(
        left.sort_values(left_on),
        right.sort_values(right_on),
        left_on=left_on,
        right_on=right_on,
        by="ticker",
        direction="backward",
    )


def _year_earlier(
    current: pd.DataFrame, rows: pd.DataFrame, cols: list[str], suffix: str
) -> pd.DataFrame:
    """Join the same-dimension row whose ``calendardate`` is one year earlier."""
    prev = rows[["ticker", "calendardate", "filed", *cols]].copy()
    prev["calendardate"] = prev["calendardate"] + pd.DateOffset(years=1)
    prev = prev.rename(columns={c: f"{c}{suffix}" for c in [*cols, "filed"]})
    prev = prev.sort_values(f"filed{suffix}").drop_duplicates(
        subset=["ticker", "calendardate"], keep="last"
    )
    merged = current.merge(prev, on=["ticker", "calendardate"], how="left")
    late = merged[f"filed{suffix}"] > merged["cutoff"]
    merged.loc[late, [f"{c}{suffix}" for c in cols]] = np.nan
    return merged.drop(columns=[f"filed{suffix}"])


def _quarterly_year_ago(rows: pd.DataFrame, fundamentals: pd.DataFrame) -> pd.DataFrame:
    """Latest ARQ quarter and the same quarter a year earlier (Yahoo growth is quarterly YoY)."""
    arq = fundamentals.loc[fundamentals["dimension"] == "ARQ"]
    cols = [c for c in ("revenue", "netinccmn") if c in arq.columns]
    if arq.empty or not cols:
        return rows
    q = arq[["ticker", "filed", "calendardate", *cols]].rename(
        columns={"filed": "q_filed", "calendardate": "q_cal", **{c: f"{c}_q" for c in cols}}
    )
    q = q.sort_values(["q_filed", "q_cal"]).drop_duplicates(["ticker", "q_filed"], keep="last")
    rows = _asof(rows, q, left_on="cutoff", right_on="q_filed")
    prev = q.assign(q_cal=q["q_cal"] + pd.DateOffset(years=1)).rename(
        columns={"q_filed": "q_filed_py", **{f"{c}_q": f"{c}_qpy" for c in cols}}
    )
    prev = prev.sort_values("q_filed_py").drop_duplicates(["ticker", "q_cal"], keep="last")
    rows = rows.merge(prev, on=["ticker", "q_cal"], how="left")
    rows.loc[rows["q_filed_py"] > rows["cutoff"], [f"{c}_qpy" for c in cols]] = np.nan
    return rows


def build_panel(
    members: Mapping[pd.Timestamp, set],
    fundamentals: pd.DataFrame,
    stocks: pd.DataFrame,
    tickers: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Point-in-time metric rows for every (rebalance date, member)."""
    base = pd.DataFrame(
        [(d, t) for d, names in members.items() for t in sorted(names)], columns=["as_of", "ticker"]
    )
    counts = {"member_rows": int(len(base))}
    if base.empty:
        return pd.DataFrame(columns=list(PANEL_COLUMNS)), counts
    base["cutoff"] = base["as_of"] - pd.Timedelta(days=FILING_LAG_DAYS)

    px = stocks[["ticker", "date", "close", "closeadj", "closeunadj"]]
    base = base.merge(
        px.rename(columns={"date": "as_of", "close": "close_d", "closeunadj": "last_price"}),
        on=["as_of", "ticker"],
        how="left",
    ).drop(columns=["closeadj"])
    no_price = base["close_d"].isna() | (base["close_d"] <= 0)
    counts["dropped_no_price"] = int(no_price.sum())
    base = base.loc[~no_price]

    art = fundamentals.loc[fundamentals["dimension"] == "ART"].drop(columns=["dimension"])
    art = art.sort_values(["filed", "calendardate"]).drop_duplicates(
        subset=["ticker", "filed"], keep="last"
    )
    rows = _asof(base, art, left_on="cutoff", right_on="filed")
    no_filing = rows["filed"].isna()
    counts["dropped_no_filing"] = int(no_filing.sum())
    rows = rows.loc[~no_filing]
    stale = (rows["as_of"] - rows["filed"]).dt.days > STALE_FILING_DAYS
    counts["dropped_stale_filing"] = int(stale.sum())
    rows = rows.loc[~stale]

    currency = tickers["currency"] if "currency" in tickers.columns else pd.Series(dtype=str)
    reporting = rows["ticker"].map(currency).fillna("USD").str.upper()
    non_usd = reporting != "USD"
    counts["dropped_non_usd"] = int(non_usd.sum())
    rows = rows.loc[~non_usd]

    filing_px = px[["ticker", "date", "close"]].rename(columns={"close": "close_f"})
    rows = _asof(rows, filing_px, left_on="filed", right_on="date").drop(columns=["date"])
    # Sharadar ``marketcap`` is struck at the filing date; roll it to the rebalance
    # with the split-adjusted close so splits in between cancel out.
    rows["price_scale"] = _ratio(_num(rows, "close_d"), _num(rows, "close_f"), positive_den=True)
    rows["market_cap_d"] = _num(rows, "marketcap") * rows["price_scale"]
    no_cap = rows["market_cap_d"].isna() | (rows["market_cap_d"] <= 0)
    counts["dropped_no_market_cap"] = int(no_cap.sum())
    rows = rows.loc[~no_cap]

    prev_cols = [
        "roa",
        "grossmargin",
        "assetsc",
        "liabilitiesc",
        "debt",
        "assets",
        "revenue",
        "netinccmn",
        "sharesbas",
    ]
    rows = _year_earlier(rows, art, [c for c in prev_cols if c in art.columns], "_py")
    rows = _quarterly_year_ago(rows, fundamentals)

    def growth(col: str) -> pd.Series:
        quarterly = _ratio(_num(rows, f"{col}_q"), _num(rows, f"{col}_qpy"), positive_den=True) - 1
        annual = _ratio(_num(rows, col), _num(rows, f"{col}_py"), positive_den=True) - 1
        return quarterly.fillna(annual)

    market_cap = _num(rows, "market_cap_d")
    equity = _num(rows, "equity")
    netinc = _num(rows, "netinccmn")
    debt, assets = _num(rows, "debt"), _num(rows, "assets")
    assetsc, liabilitiesc = _num(rows, "assetsc"), _num(rows, "liabilitiesc")
    revenue = _num(rows, "revenue")
    sector = tickers["sector"] if "sector" in tickers.columns else pd.Series(dtype=str)
    name = tickers["name"] if "name" in tickers.columns else pd.Series(dtype=str)
    out = pd.DataFrame(
        {
            "as_of": rows["as_of"].dt.strftime("%Y-%m-%d"),
            "ticker": rows["ticker"],
            "name": rows["ticker"].map(name),
            "sector": rows["ticker"].map(sector),
            "market_cap": market_cap,
            "trailing_pe": _ratio(market_cap, netinc, positive_den=True),
            "price_to_book": _ratio(market_cap, equity, positive_den=True),
            # Live Yahoo rows carry dividend yield in percent (2.5 = 2.5%); Sharadar is a fraction.
            "dividend_yield": _ratio(_num(rows, "divyield"), rows["price_scale"], positive_den=True)
            * 100.0,
            "current_ratio": _num(rows, "currentratio"),
            "debt_to_equity": _ratio(debt, equity, positive_den=True) * 100.0,
            "return_on_equity": _num(rows, "roe"),
            "return_on_assets": _num(rows, "roa"),
            "profit_margins": _num(rows, "netmargin"),
            "revenue_growth": growth("revenue"),
            "earnings_growth": growth("netinccmn"),
            "free_cashflow": _num(rows, "fcf"),
            "operating_cashflow": _num(rows, "ncfo"),
            "enterprise_value": market_cap + debt.fillna(0.0) - _num(rows, "cashneq").fillna(0.0),
            "ebitda": _num(rows, "ebitda"),
            "ebit": _num(rows, "ebit"),
            "total_revenue": revenue,
            "total_debt": debt,
            "total_cash": _num(rows, "cashneq"),
            "book_value": _num(rows, "bvps"),
            "total_assets": assets,
            "total_current_assets": assetsc,
            "total_liabilities": _num(rows, "liabilities"),
            "total_current_liabilities": liabilitiesc,
            "net_income": netinc,
            "interest_expense": _num(rows, "intexp"),
            "gross_margin": _num(rows, "grossmargin"),
            "ncav": assetsc - _num(rows, "liabilities"),
            "shares_outstanding": _num(rows, "sharesbas"),
            "last_price": _num(rows, "last_price"),
            "return_on_assets_prev": _num(rows, "roa_py"),
            "gross_margin_prev": _num(rows, "grossmargin_py"),
            "current_ratio_bs": _ratio(assetsc, liabilitiesc, positive_den=True),
            "current_ratio_bs_prev": _ratio(
                _num(rows, "assetsc_py"), _num(rows, "liabilitiesc_py"), positive_den=True
            ),
            "leverage": _ratio(debt, assets, positive_den=True),
            "leverage_prev": _ratio(
                _num(rows, "debt_py"), _num(rows, "assets_py"), positive_den=True
            ),
            "asset_turnover": _ratio(revenue, assets, positive_den=True),
            "asset_turnover_prev": _ratio(
                _num(rows, "revenue_py"), _num(rows, "assets_py"), positive_den=True
            ),
            "shares_outstanding_prev": _num(rows, "sharesbas_py"),
            "total_assets_prev": _num(rows, "assets_py"),
        }
    )
    out = out.sort_values(["as_of", "ticker"]).reset_index(drop=True)
    counts["panel_rows"] = int(len(out))
    return out[list(PANEL_COLUMNS)], counts


# --- Prices and delistings -----------------------------------------------------------------


def sparse_prices(
    stocks: pd.DataFrame, rebalances: list[pd.Timestamp], horizons_days: Iterable[int]
) -> pd.DataFrame:
    """``closeadj`` on rebalance dates, each horizon's first trading day on/after entry+h,
    and every ticker's last trading day (so delisting exits can be detected)."""
    calendar = pd.DatetimeIndex(sorted(stocks["date"].unique()))
    keep = set(rebalances)
    for entry in rebalances:
        for horizon in horizons_days:
            idx = calendar.searchsorted(entry + pd.Timedelta(days=int(horizon)))
            if idx < len(calendar):
                keep.add(calendar[idx])
    on_dates = stocks.loc[stocks["date"].isin(keep)]
    last_rows = stocks.sort_values("date").groupby("ticker").tail(1)
    frame = pd.concat([on_dates, last_rows]).drop_duplicates(subset=["date", "ticker"])
    frame = frame.loc[frame["date"] >= min(rebalances)] if rebalances else frame.iloc[0:0]
    out = frame[["date", "ticker", "closeadj"]].rename(columns={"closeadj": "close"})
    out = out.dropna(subset=["close"]).sort_values(["date", "ticker"])
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out.reset_index(drop=True)


def daily_adjusted_ohlc(stocks: pd.DataFrame, first: pd.Timestamp) -> pd.DataFrame:
    """Dividend- and split-adjusted daily OHLC (what Yahoo ``auto_adjust`` gives the live
    trade plan), from ``DAILY_HISTORY_DAYS`` before ``first`` so indicators are warm."""
    frame = stocks.loc[stocks["date"] >= first - pd.Timedelta(days=DAILY_HISTORY_DAYS)]
    factor = (frame["closeadj"] / frame["close"]).where(frame["close"] > 0)
    out = pd.DataFrame(
        {
            "date": frame["date"].dt.strftime("%Y-%m-%d"),
            "ticker": frame["ticker"],
            "open": frame["open"] * factor,
            "high": frame["high"] * factor,
            "low": frame["low"] * factor,
            "close": frame["closeadj"],
        }
    )
    return out.dropna(subset=["close"]).sort_values(["ticker", "date"]).reset_index(drop=True)


def merger_exits(actions: pd.DataFrame) -> set[str]:
    self_rows = actions.loc[actions["action"].isin(MERGER_SELF_ACTIONS), "ticker"]
    contra_rows = actions.loc[actions["action"].isin(MERGER_CONTRA_ACTIONS), "contraticker"]
    return set(self_rows.dropna().astype(str)) | set(contra_rows.dropna().astype(str))


def terminal_haircuts(
    tickers: pd.DataFrame,
    actions: pd.DataFrame,
    universe: set[str],
    *,
    baseline: float,
    sensitivity_non_merger: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    delisted_flag = tickers.get("isdelisted", pd.Series(dtype=str)).astype(str).str.upper()
    delisted = sorted(t for t in universe if delisted_flag.get(t) == "Y")
    mergers = merger_exits(actions)
    base = pd.DataFrame({"ticker": delisted, "haircut": float(baseline)})
    sens = base.assign(
        haircut=[
            float(baseline) if t in mergers else float(sensitivity_non_merger) for t in delisted
        ]
    )
    merged = sum(1 for t in delisted if t in mergers)
    return (
        base,
        sens,
        {
            "delisted_members": len(delisted),
            "delisted_via_merger": merged,
            "delisted_other": len(delisted) - merged,
        },
    )


# --- Orchestration -------------------------------------------------------------------------


def build_replay_inputs(
    sharadar_dir: Path, out_dir: Path, registration: Mapping[str, Any]
) -> dict[str, Any]:
    """Write panel, prices, terminal files and ``build_report.json`` into ``out_dir``."""
    sharadar_dir, out_dir = Path(sharadar_dir), Path(out_dir)
    windows = registration["windows"]
    first = pd.Timestamp(windows["development"]["first_entry"])
    last = pd.Timestamp(windows["holdout"]["last_entry"])
    horizons = [int(h) for h in registration["horizons_days"]]

    rule = registration.get("universe_rule") or {"kind": "sp500_members"}
    tickers = load_tickers(find_table(sharadar_dir, "tickers"))
    stocks_path = find_table(sharadar_dir, "stocks")
    if rule["kind"] == "sp500_members":
        sp500 = load_sp500(find_table(sharadar_dir, "sp500"))
        ever = ever_members(sp500, first - pd.offsets.MonthBegin(1), last + pd.offsets.MonthEnd(0))
        stocks = load_stocks(stocks_path, ever)
        rebalances = month_end_trading_days(stocks["date"], first, last)
        members = membership_on(sp500, rebalances)
        universe = set().union(*members.values()) if members else set()
    elif rule["kind"] == "us_cap_rank":
        eligible = eligible_common_stocks(tickers)
        calendar = load_trading_calendar(stocks_path)
        rebalances = month_end_trading_days(calendar, first, last)
        marks = month_end_trading_days(calendar, first - pd.DateOffset(months=18), last)
        closes = load_closes_on(stocks_path, eligible, set(marks))
        caps = load_market_caps(find_table(sharadar_dir, "fundamentals"), eligible)
        members = cap_rank_membership(
            caps,
            closes,
            rebalances,
            rank_from=int(rule["rank_from"]),
            rank_to=int(rule["rank_to"]),
        )
        universe = set().union(*members.values()) if members else set()
        stocks = load_stocks(stocks_path, universe)
    else:
        raise ValueError(f"Unknown universe_rule kind {rule['kind']!r}")

    actions = load_actions(find_table(sharadar_dir, "actions"))
    fundamentals = load_fundamentals(find_table(sharadar_dir, "fundamentals"), universe)
    panel, counts = build_panel(
        members, fundamentals, stocks.loc[stocks["ticker"].isin(universe)], tickers
    )
    member_stocks = stocks.loc[stocks["ticker"].isin(universe)]
    prices = sparse_prices(member_stocks, rebalances, horizons)
    daily = daily_adjusted_ohlc(member_stocks, first)
    delisting = registration.get("delisting") or {}
    base, sens, delist_counts = terminal_haircuts(
        tickers,
        actions,
        universe,
        baseline=float(delisting.get("baseline_haircut", 0.0)),
        sensitivity_non_merger=float(delisting.get("sensitivity_haircut_non_merger", -0.3)),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    panel.to_csv(out_dir / "panel.csv.gz", index=False)
    prices.to_csv(out_dir / "prices.csv.gz", index=False)
    daily.to_csv(out_dir / "daily.csv.gz", index=False)
    base.to_csv(out_dir / "terminal_baseline.csv", index=False)
    sens.to_csv(out_dir / "terminal_sensitivity.csv", index=False)

    per_date = panel.groupby("as_of")["ticker"].size() if not panel.empty else pd.Series(dtype=int)
    members_per_date = [len(v) for v in members.values()]
    report = {
        "built_at": datetime.now(UTC).isoformat(),
        "registration_id": registration.get("registration_id"),
        "rebalance_dates": len(rebalances),
        "first_rebalance": rebalances[0].date().isoformat() if rebalances else None,
        "last_rebalance": rebalances[-1].date().isoformat() if rebalances else None,
        "members_per_date": _spread(members_per_date),
        "panel_names_per_date": _spread(per_date.tolist()),
        "panel_coverage": round(counts.get("panel_rows", 0) / counts["member_rows"], 4)
        if counts.get("member_rows")
        else None,
        "unique_members": len(universe),
        "counts": counts,
        "delisting": delist_counts,
        "price_rows": int(len(prices)),
        "daily_rows": int(len(daily)),
        "metric_fill_rates": {
            col: round(float(panel[col].notna().mean()), 4)
            for col in PANEL_COLUMNS
            if col not in ("as_of", "ticker") and not panel.empty
        },
    }
    (out_dir / "build_report.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    return report


def _spread(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"min": None, "median": None, "max": None}
    return {"min": int(min(values)), "median": float(np.median(values)), "max": int(max(values))}
