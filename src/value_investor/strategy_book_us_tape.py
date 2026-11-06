"""Point-in-time inputs for the strategy-book US rehearsal.

Registration ``strategy-book-us-rehearsal-v0`` sections 2–4, 11 and 12. Reads
the owner's local Sharadar exports and the hsr-v2 / hsr-mid-v2 build
directories, and returns walker ``NameSpec`` rows. Nothing here writes a file
and nothing here is committed: every value it returns is licensed data.

* Part 1 — the baseline ``signals_cache.csv.gz`` beside each panel, checked
  against ``signal_cache_key`` so a stale cache is never scored.
* Part 2 — the decline gate from ART and ARQ rows filed at least two days
  before the session (``statement_basis`` ``art_ttm``).
* Part 3 — price-only sector breadth inside each universe.
* Universes — ``membership_on`` on every session for ``sp500``; cap ranks
  501–1000 carried from month-end for ``sp400``, minus that session's
  ``sp500`` members.
"""

from __future__ import annotations

import dataclasses
import json
import math
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from value_investor import historical_screen_replay as hsr
from value_investor import sharadar_replay_adapter as sra
from value_investor.strategy_book_observe import (
    CrossNameTape,
    Download,
    GateTape,
    NameSpec,
    ScreenFact,
    WalkOptions,
)
from value_investor.strategy_book_rules import VALUE_SET_SIGNALS

SP500 = "sp500"
SP400 = "sp400"
GATE_LABELS: tuple[str | None, ...] = (
    None,
    "clear",
    "declining",
    "insufficient_data",
    "sound",
    "headwind",
    "sector_missing",
)
_CODE = {label: index for index, label in enumerate(GATE_LABELS)}
SECTOR_BASIS = "price_only"
STATEMENT_BASIS = "art_ttm"
HL_HIGH_LOW = "high_low"
HL_CLOSES = "closes"
PANEL_FIELDS = (
    "market_cap",
    "profit_margins",
    "debt_to_equity",
    "revenue_growth",
    "earnings_growth",
)
_PANEL_READ = (*PANEL_FIELDS, "free_cashflow", "enterprise_value", "ebit")
_CACHE_FIELDS = ("conviction_score", "composite_score", "data_quality_score")
_ART_COLUMNS = ("revenue", "opinc", "ebit", "epsdil", "eps", "fcf")
_ARQ_COLUMNS = ("revenue", "epsdil", "eps")
_EPOCH_ORDINAL = date(1970, 1, 1).toordinal()


class InputsMissing(RuntimeError):
    """A build file or a current signals cache is missing. The message says how to make it."""


@dataclass(frozen=True)
class BuildDir:
    """One ``ftse-historical-replay build-panel`` output directory."""

    root: Path
    universe: str  # ``sp500`` (hsr-v2) or ``midcap`` (hsr-mid-v2)

    @property
    def panel(self) -> Path:
        return self.root / "panel.csv.gz"

    @property
    def prices(self) -> Path:
        return self.root / "prices.csv.gz"

    @property
    def daily(self) -> Path:
        return self.root / "daily.csv.gz"

    @property
    def terminal(self) -> Path:
        return self.root / "terminal_baseline.csv"

    @property
    def cache(self) -> Path:
        return self.root / hsr.SIGNAL_CACHE_NAME

    @property
    def cache_key(self) -> Path:
        return self.cache.with_name(self.cache.name + ".key.json")

    @property
    def hsr_store(self) -> Path:
        return hsr.MIDCAP_STORE_PATH if self.universe == "midcap" else hsr.DEFAULT_STORE_PATH

    def universe_flag(self) -> str:
        return " --universe midcap" if self.universe == "midcap" else ""

    def build_command(self) -> str:
        return (
            f"ftse-historical-replay build-panel{self.universe_flag()} "
            f"--sharadar-dir <your Sharadar directory> --out {self.root}"
        )

    def cache_command(self) -> str:
        """The baseline cache build. Never ``--reveal-holdout``; the run rewrites the hsr store."""
        return (
            f"ftse-historical-replay run{self.universe_flag()} --panel {self.panel} "
            f"--prices {self.prices} --terminal {self.terminal}\n"
            f"git restore {self.hsr_store}"
        )


@dataclass
class SharadarFiles:
    tickers: Path
    actions: Path
    sp500: Path
    fundamentals: Path
    stocks: Path

    @classmethod
    def find(cls, root: Path) -> SharadarFiles:
        return cls(
            tickers=sra.find_table(root, "tickers"),
            actions=sra.find_table(root, "actions"),
            sp500=sra.find_table(root, "sp500"),
            fundamentals=sra.find_table(root, "fundamentals"),
            stocks=sra.find_table(root, "stocks"),
        )


@dataclass
class DeclineRules:
    """Section 3.2 constants, read from the registration's ``decline_gate`` block."""

    revenue_drop: float = 0.05
    flat_tolerance: float = 0.01
    margin_drop_pp: float = 0.03
    eps_annual_drop: float = 0.20
    eps_interim_drop: float = 0.10
    fcf_sharp_fall: float = 0.50
    soft_to_decline: int = 2
    filing_lag_days: int = 2
    stale_filing_days: int = 456
    interim_window_days: int = 45
    interim_max_age_days: int = 460

    @classmethod
    def from_registration(cls, registration: Mapping[str, Any]) -> DeclineRules:
        gate = registration.get("decline_gate") or {}
        limits = gate.get("thresholds_existing") or {}
        return cls(
            revenue_drop=float(limits.get("revenue_drop_pct", 0.05)),
            flat_tolerance=float(limits.get("revenue_flat_tolerance_pct", 0.01)),
            margin_drop_pp=float(limits.get("margin_drop_pp", 0.03)),
            eps_annual_drop=float(limits.get("eps_annual_drop_pct", 0.20)),
            eps_interim_drop=float(limits.get("eps_interim_drop_pct", 0.10)),
            fcf_sharp_fall=float(limits.get("fcf_sharp_fall_pct", 0.50)),
            soft_to_decline=int(limits.get("soft_signals_to_decline", 2)),
            filing_lag_days=int(gate.get("filing_lag_days", 2)),
            stale_filing_days=int(gate.get("stale_filing_days", 456)),
            interim_window_days=int(gate.get("interim_yoy_window_days", 45)),
            interim_max_age_days=int(gate.get("interim_max_age_days", 460)),
        )


@dataclass
class SectorRules:
    breadth_headwind: float = 0.65
    trend_headwind: float = -0.10
    lookback: int = 126
    sma: int = 200
    min_members: int = 4
    min_share: float = 0.60

    @classmethod
    def from_registration(cls, registration: Mapping[str, Any]) -> SectorRules:
        gate = registration.get("sector_gate") or {}
        return cls(
            breadth_headwind=float(gate.get("price_breadth_headwind", 0.65)),
            trend_headwind=float(gate.get("sector_return_126d_headwind", -0.10)),
            lookback=int(gate.get("return_lookback_sessions", 126)),
            sma=int(gate.get("sma_sessions", 200)),
            min_members=int(gate.get("minimum_members_with_data", 4)),
            min_share=float(gate.get("minimum_coverage_share", 0.60)),
        )


@dataclass
class RehearsalInputs:
    """Everything the walk needs. Licensed values: keep in memory or scratch only."""

    specs: list[NameSpec]
    haircuts: dict[str, dict[str, float]]
    tickers: set[str]
    hl_basis: str
    cache_keys: dict[str, dict[str, Any]]
    counts: dict[str, int] = field(default_factory=dict)

    def with_variant(self, variant: str) -> list[NameSpec]:
        """Specs with the baseline or the sensitivity delisting haircut."""
        out = []
        for spec in self.specs:
            cut = self.haircuts.get(spec.ticker)
            haircut = None if cut is None else cut[variant]
            out.append(
                spec
                if spec.terminal_haircut == haircut
                else dataclasses.replace(spec, terminal_haircut=haircut)
            )
        return out


# --- Small helpers -------------------------------------------------------------------------

_DAY_CACHE: dict[int, date] = {}


def _day(ordinal: int) -> date:
    """One shared ``date`` per calendar day, so decades of bars do not copy dates."""
    found = _DAY_CACHE.get(ordinal)
    if found is None:
        found = date.fromordinal(ordinal)
        _DAY_CACHE[ordinal] = found
    return found


def _ordinals(values: pd.Series) -> np.ndarray:
    stamps = pd.to_datetime(values, errors="coerce", utc=True).dt.tz_convert(None)
    days = stamps.values.astype("datetime64[D]").astype("int64")
    return days + _EPOCH_ORDINAL


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _year_back(day: date, years: int = 1) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def _change(now: float | None, prior: float | None) -> float | None:
    if now is None or prior is None or prior <= 0:
        return None
    return now / prior - 1.0


def export_hl_basis(stocks_path: Path) -> str:
    """``high_low`` when the SEP export has both columns, read before ``load_stocks`` fills them."""
    columns = {str(column).strip().lower() for column in pd.read_csv(stocks_path, nrows=0).columns}
    return HL_HIGH_LOW if {"high", "low"} <= columns else HL_CLOSES


# --- Part 1: the baseline caches ------------------------------------------------------------


def checked_cache(build: BuildDir) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """(cache, panel, key) once the cache key equals ``signal_cache_key(panel)``."""
    for path in (build.panel, build.prices, build.daily):
        if not path.exists():
            raise InputsMissing(f"{path} is missing. Build it with:\n  {build.build_command()}")
    if not build.cache.exists() or not build.cache_key.exists():
        raise InputsMissing(
            f"No baseline signals cache beside {build.panel}. Build it without "
            f"--reveal-holdout:\n  {build.cache_command()}"
        )
    panel = pd.read_csv(build.panel)
    expected = hsr.signal_cache_key(panel, None)
    try:
        found = json.loads(build.cache_key.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        found = None
    if found != expected:
        raise InputsMissing(
            f"The signals cache beside {build.panel} was built from a different panel or "
            f"screen code. Rebuild it without --reveal-holdout:\n  {build.cache_command()}"
        )
    cache = pd.read_csv(build.cache)
    return cache, panel, expected


def _truthy(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    if not columns:
        return np.zeros(len(frame), dtype=int)
    flags = frame[columns].astype(str).apply(lambda col: col.str.strip().str.lower())
    return flags.isin(("true", "1", "1.0")).sum(axis=1).to_numpy()


_SCREEN_COLUMNS = ("signal", *_CACHE_FIELDS, "earnings_yield")


class ScreenTable:
    """One universe's cache rows merged with the panel fields the snapshot reads.

    ``facts(ticker)`` gives the monthly ``ScreenFact`` rows for one name, so a
    batched walk builds screen facts for one batch at a time.
    """

    def __init__(
        self, cache: pd.DataFrame, panel: pd.DataFrame, sectors: Mapping[str, str | None]
    ) -> None:
        cache = cache.copy()
        cache["day"] = _ordinals(cache["as_of"])
        cache = cache.loc[cache["day"] > 0]
        cache["ticker"] = cache["ticker"].astype(str)
        cache["models_passed"] = _truthy(
            cache, [c for c in cache.columns if c.startswith(hsr.MODEL_PASS_PREFIX)]
        )
        cache = cache[
            ["day", "ticker", "models_passed", *[c for c in _SCREEN_COLUMNS if c in cache.columns]]
        ]
        keep = ["as_of", "ticker", *[c for c in _PANEL_READ if c in panel.columns]]
        panel_rows = panel[keep].copy()
        panel_rows["day"] = _ordinals(panel_rows["as_of"])
        panel_rows["ticker"] = panel_rows["ticker"].astype(str)
        panel_rows = panel_rows.drop(columns=["as_of"]).drop_duplicates(
            ["day", "ticker"], keep="last"
        )
        merged = cache.merge(panel_rows, on=["day", "ticker"], how="left")
        self.dates = sorted(int(day) for day in merged["day"].dropna().unique())
        self.frame = merged.sort_values("day").reset_index(drop=True)
        self.rows = {
            str(ticker): rows
            for ticker, rows in self.frame.groupby("ticker", sort=True).indices.items()
        }
        self.sectors = sectors

    @property
    def tickers(self) -> list[str]:
        return list(self.rows)

    def facts(self, ticker: str) -> list[ScreenFact]:
        """Blank rows after a name's first cache date are missing observations, not ``avoid``."""
        rows = self.frame.iloc[self.rows[ticker]]
        by_day = {int(row["day"]): row for row in rows.to_dict("records")}
        first = min(by_day)
        sector = self.sectors.get(ticker)
        facts: list[ScreenFact] = []
        streak = 0
        for day in self.dates:
            if day < first:
                continue
            row = by_day.get(day)
            run_date = _day(day)
            if row is None:
                streak = 0
                facts.append(ScreenFact(run_date=run_date, signal=None, sector=sector))
                continue
            raw = row.get("signal")
            signal = None if raw is None or (isinstance(raw, float) and math.isnan(raw)) else raw
            signal = None if signal is None else str(signal).strip().lower() or None
            buy = signal in VALUE_SET_SIGNALS
            streak = streak + 1 if buy else 0
            facts.append(
                ScreenFact(
                    run_date=run_date,
                    signal=signal,
                    sector=sector,
                    fields=_snapshot_fields(row, streak) if buy else {},
                )
            )
        return facts


def screen_facts(
    cache: pd.DataFrame,
    panel: pd.DataFrame,
    sectors: Mapping[str, str | None],
) -> dict[str, list[ScreenFact]]:
    """Monthly ``ScreenFact`` rows per ticker, with section 12 Q4–Q5 snapshot fields.

    A cache date after a name's first row on which the name has no row is a
    blank row: the name left the screen, so it cannot enter, and a blank row
    is a missing observation rather than ``avoid``.
    """
    table = ScreenTable(cache, panel, sectors)
    return {ticker: table.facts(ticker) for ticker in table.tickers}


def _snapshot_fields(row: Mapping[str, Any], streak: int) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for column in _CACHE_FIELDS:
        value = _finite(row.get(column))
        if value is not None:
            fields[column] = value
            sources[column] = "cache"
    earnings_yield = _finite(row.get("earnings_yield"))
    if earnings_yield is not None:
        fields["earnings_yield_pe"] = earnings_yield
        sources["earnings_yield_pe"] = "cache"
    fields["weeks_at_signal"] = streak
    fields["models_passed"] = int(row.get("models_passed") or 0)
    sources["weeks_at_signal"] = sources["models_passed"] = "cache_count"
    for column in PANEL_FIELDS:
        value = _finite(row.get(column))
        if value is not None:
            fields[column] = value
            sources[column] = "panel"
    cap = _finite(row.get("market_cap"))
    fcf = _finite(row.get("free_cashflow"))
    if cap is not None and cap > 0 and fcf is not None:
        fields["fcf_yield"] = fcf / cap
        sources["fcf_yield"] = "panel_ratio"
    ev = _finite(row.get("enterprise_value"))
    ebit = _finite(row.get("ebit"))
    if ebit is not None and ebit > 0 and ev is not None:
        fields["ev_ebit"] = ev / ebit
        sources["ev_ebit"] = "panel_ratio"
    fields["feature_sources"] = sources
    return fields


# --- Daily tape -----------------------------------------------------------------------------


def load_tapes(
    daily_paths: Iterable[Path], tickers: set[str], *, hl_basis: str
) -> dict[str, Download]:
    """One adjusted download per ticker; the first file that has a ticker wins."""
    out: dict[str, Download] = {}
    for path in daily_paths:
        frame = pd.read_csv(
            path,
            usecols=lambda c: c in {"date", "ticker", "high", "low", "close"},
            dtype={"ticker": "category"},
        )
        frame = frame.loc[frame["ticker"].isin(tickers - set(out))]
        if frame.empty:
            continue
        frame = frame.assign(day=_ordinals(frame["date"])).dropna(subset=["close"])
        frame = frame.drop_duplicates(["ticker", "day"], keep="last")
        frame = frame.sort_values(["ticker", "day"], kind="stable")
        codes = frame["ticker"].cat.codes.to_numpy()
        labels = frame["ticker"].cat.categories
        days = frame["day"].to_numpy()
        closes = frame["close"].to_numpy(dtype=float)
        highs = frame["high"].to_numpy(dtype=float) if "high" in frame else None
        lows = frame["low"].to_numpy(dtype=float) if "low" in frame else None
        cuts = np.flatnonzero(np.diff(codes)) + 1
        for start, stop in zip(
            np.concatenate(([0], cuts)), np.concatenate((cuts, [len(codes)])), strict=True
        ):
            if stop <= start:
                continue
            ticker = str(labels[codes[start]])
            sessions = [_day(int(value)) for value in days[start:stop]]
            use_hl = hl_basis == HL_HIGH_LOW and highs is not None and lows is not None
            out[ticker] = Download(
                as_of=sessions[-1],
                sessions=sessions,
                closes=closes[start:stop].tolist(),
                highs=highs[start:stop].tolist() if use_hl else None,
                lows=lows[start:stop].tolist() if use_hl else None,
            )
    return out


# --- Universes ------------------------------------------------------------------------------


def spans_from_days(
    calendar: list[date], members_by_day: list[set[str]]
) -> dict[str, list[tuple[date, date]]]:
    """Inclusive spans of consecutive calendar sessions on which each ticker is a member."""
    spans: dict[str, list[list[int]]] = {}
    for index, members in enumerate(members_by_day):
        for ticker in members:
            rows = spans.setdefault(ticker, [])
            if rows and rows[-1][1] == index - 1:
                rows[-1][1] = index
            else:
                rows.append([index, index])
    return {ticker: [(calendar[a], calendar[b]) for a, b in rows] for ticker, rows in spans.items()}


def sp500_members_by_day(sp500: pd.DataFrame, calendar: list[date]) -> list[set[str]]:
    stamps = [pd.Timestamp(day) for day in calendar]
    members = sra.membership_on(sp500, stamps)
    return [set(members[stamp.normalize()]) for stamp in stamps]


def sp400_members_by_day(
    month_sets: Mapping[date, set[str]],
    calendar: list[date],
    sp500_by_day: list[set[str]],
) -> tuple[list[set[str]], int]:
    """Cap-rank set of the month-end on or before each session, minus its ``sp500`` members."""
    ends = sorted(month_sets)
    out: list[set[str]] = []
    overlap = 0
    position = -1
    for index, day in enumerate(calendar):
        while position + 1 < len(ends) and ends[position + 1] <= day:
            position += 1
        if position < 0:
            out.append(set())
            continue
        ranked = month_sets[ends[position]]
        both = ranked & sp500_by_day[index]
        overlap += len(both)
        out.append(ranked - both if both else set(ranked))
    return out, overlap


def cap_rank_month_sets(
    files: SharadarFiles,
    tickers: pd.DataFrame,
    month_ends: list[date],
    *,
    rank_from: int,
    rank_to: int,
) -> dict[date, set[str]]:
    """hsr-mid-v2 ranks at the cache's month-ends, with marks from 18 months earlier."""
    if not month_ends:
        return {}
    eligible = sra.eligible_common_stocks(tickers)
    calendar = sra.load_trading_calendar(files.stocks)
    first, last = pd.Timestamp(month_ends[0]), pd.Timestamp(month_ends[-1])
    marks = sra.month_end_trading_days(calendar, first - pd.DateOffset(months=18), last)
    closes = sra.load_closes_on(
        files.stocks, eligible, set(marks) | {pd.Timestamp(d) for d in month_ends}
    )
    caps = sra.load_market_caps(files.fundamentals, eligible)
    ranked = sra.cap_rank_membership(
        caps,
        closes,
        [pd.Timestamp(day) for day in month_ends],
        rank_from=rank_from,
        rank_to=rank_to,
    )
    return {stamp.date(): set(names) for stamp, names in ranked.items()}


# --- Part 3: price-only sector breadth ------------------------------------------------------


@dataclass
class SectorTape:
    """Per-session verdict and inputs for one (universe, sector)."""

    codes: np.ndarray
    breadth_share: np.ndarray
    breadth_members: np.ndarray
    trend_mean: np.ndarray
    trend_members: np.ndarray
    members: np.ndarray

    def inputs(self, index: int) -> dict[str, Any]:
        def _num(array: np.ndarray) -> float | None:
            value = float(array[index])
            return value if math.isfinite(value) else None

        return {
            "basis": SECTOR_BASIS,
            "members": int(self.members[index]),
            "breadth_members": int(self.breadth_members[index]),
            "breadth_share": _num(self.breadth_share),
            "trend_members": int(self.trend_members[index]),
            "trend_mean": _num(self.trend_mean),
        }


def _own_bar_flags(
    download: Download, calendar_ord: np.ndarray, rules: SectorRules
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(calendar positions, below-SMA flag or -1, 126-session return or NaN) on own bars."""
    closes = np.asarray(download.closes, dtype=float)
    ords = np.fromiter((day.toordinal() for day in download.sessions), dtype=np.int64)
    positions = np.searchsorted(calendar_ord, ords)
    below = np.full(len(closes), -1, dtype=np.int8)
    if len(closes) >= rules.sma:
        sums = np.concatenate(([0.0], np.cumsum(closes)))
        sma = (sums[rules.sma :] - sums[: -rules.sma]) / rules.sma
        below[rules.sma - 1 :] = (closes[rules.sma - 1 :] < sma).astype(np.int8)
    trend = np.full(len(closes), np.nan, dtype=np.float64)
    if len(closes) > rules.lookback:
        base = closes[: -rules.lookback]
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(base > 0, closes[rules.lookback :] / base - 1.0, np.nan)
        trend[rules.lookback :] = ratio
    keep = (positions < len(calendar_ord)) & (
        calendar_ord[np.minimum(positions, len(calendar_ord) - 1)] == ords
    )
    return positions[keep], below[keep], trend[keep]


def sector_tapes(
    calendar: list[date],
    members_by_day: list[set[str]],
    sectors: Mapping[str, str | None],
    tapes: Mapping[str, Download],
    rules: SectorRules,
) -> dict[str, SectorTape]:
    """Section 3.3 verdicts per sector of one universe, on every calendar session."""
    calendar_ord = np.fromiter((day.toordinal() for day in calendar), dtype=np.int64)
    sessions = len(calendar)
    tickers = sorted(
        {ticker for members in members_by_day for ticker in members if sectors.get(ticker)}
    )
    column = {ticker: index for index, ticker in enumerate(tickers)}
    member_all = np.zeros((sessions, len(tickers)), dtype=bool)
    for index, today in enumerate(members_by_day):
        slots = [column[ticker] for ticker in today if ticker in column]
        member_all[index, slots] = True
    below_all = np.full((sessions, len(tickers)), -1, dtype=np.int8)
    trend_all = np.full((sessions, len(tickers)), np.nan, dtype=np.float32)
    for ticker, slot in column.items():
        download = tapes.get(ticker)
        if download is None or not download.sessions:
            continue
        positions, low, ret = _own_bar_flags(download, calendar_ord, rules)
        below_all[positions, slot] = low
        trend_all[positions, slot] = ret
    by_sector: dict[str, list[int]] = {}
    for ticker, slot in column.items():
        by_sector.setdefault(str(sectors[ticker]), []).append(slot)
    return {
        label: _sector_tape(member_all[:, slots], below_all[:, slots], trend_all[:, slots], rules)
        for label, slots in by_sector.items()
    }


def _sector_tape(
    member: np.ndarray, below: np.ndarray, trend: np.ndarray, rules: SectorRules
) -> SectorTape:
    """One sector's verdicts from (session x member) membership, below-SMA and trend flags."""
    sessions = member.shape[0]
    has_sma = member & (below >= 0)
    has_trend = member & np.isfinite(trend)
    members = member.sum(axis=1)
    breadth_n = has_sma.sum(axis=1)
    trend_n = has_trend.sum(axis=1)
    below_n = (has_sma & (below == 1)).sum(axis=1)
    trend_sum = np.where(has_trend, trend, 0.0).sum(axis=1, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.where(breadth_n > 0, below_n / breadth_n, np.nan)
        mean = np.where(trend_n > 0, trend_sum / trend_n, np.nan)
        breadth_ok = (breadth_n >= rules.min_members) & (breadth_n >= rules.min_share * members)
        trend_ok = (trend_n >= rules.min_members) & (trend_n >= rules.min_share * members)
    covered = breadth_ok & trend_ok & (members > 0)
    trigger = (share >= rules.breadth_headwind) & (mean < rules.trend_headwind)
    codes = np.full(sessions, _CODE["insufficient_data"], dtype=np.int8)
    codes[covered & trigger] = _CODE["headwind"]
    codes[covered & ~trigger] = _CODE["sound"]
    return SectorTape(
        codes=codes,
        breadth_share=share,
        breadth_members=breadth_n,
        trend_mean=mean,
        trend_members=trend_n,
        members=members,
    )


# --- Part 2: the decline gate ---------------------------------------------------------------


def load_statements(path: Path, tickers: set[str]) -> pd.DataFrame:
    """ART and ARQ rows with the section 3.2 indicators; ``filed`` is ``datekey`` else ``date``."""
    wanted = {"ticker", "dimension", "datekey", "date", "calendardate", *_ART_COLUMNS}
    chunks = []
    for chunk in pd.read_csv(
        path, usecols=lambda c: c in wanted, chunksize=500_000, low_memory=False
    ):
        chunk = chunk.loc[chunk["ticker"].isin(tickers) & chunk["dimension"].isin(("ART", "ARQ"))]
        if not chunk.empty:
            chunks.append(chunk)
    if not chunks:
        return pd.DataFrame(columns=["ticker", "dimension", "filed", "cal", *_ART_COLUMNS])
    frame = pd.concat(chunks, ignore_index=True)
    filed_col = "datekey" if "datekey" in frame.columns else "date"
    frame["filed"] = _ordinals(frame[filed_col])
    frame["cal"] = _ordinals(frame["calendardate"])
    frame = frame.loc[(frame["filed"] > 0) & (frame["cal"] > 0)]
    for column in _ART_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce") if column in frame else np.nan
    return frame[["ticker", "dimension", "filed", "cal", *_ART_COLUMNS]]


class _Statements:
    """One ticker's rows of one dimension, ordered by filing date."""

    def __init__(self, rows: pd.DataFrame, columns: tuple[str, ...]) -> None:
        rows = rows.sort_values(["filed", "cal"], kind="stable")
        self.filed = rows["filed"].to_numpy(dtype=np.int64)
        self.cal = rows["cal"].to_numpy(dtype=np.int64)
        self.values = {column: rows[column].to_numpy(dtype=float) for column in columns}
        self.best = np.zeros(len(self.cal), dtype=np.int64)
        self.by_cal: dict[int, list[int]] = {}
        best = -1
        for index, cal in enumerate(self.cal):
            if best < 0 or cal >= self.cal[best]:
                best = index
            self.best[index] = best
            self.by_cal.setdefault(int(cal), []).append(index)

    def __len__(self) -> int:
        return len(self.cal)

    def value(self, column: str, index: int | None) -> float | None:
        if index is None:
            return None
        return _finite(self.values[column][index])

    def at_cal(self, cal: int, visible: int) -> int | None:
        """Latest-filed row with this ``calendardate`` among the first ``visible + 1`` rows."""
        found = None
        for index in self.by_cal.get(cal, ()):
            if index > visible:
                break
            found = index
        return found

    def near(self, cal: int, visible: int, window: int, exclude_cal: int) -> int | None:
        best: tuple[int, int] | None = None
        for index in range(visible + 1):
            other = int(self.cal[index])
            if other == exclude_cal:
                continue
            gap = abs(other - cal)
            if gap > window:
                continue
            if best is None or gap < best[0] or (gap == best[0] and index > best[1]):
                best = (gap, index)
        return None if best is None else best[1]


def _pick(stats: _Statements, columns: tuple[str, ...], now: int, prior: int | None):
    for column in columns:
        a, b = stats.value(column, now), stats.value(column, prior)
        if a is not None and b is not None:
            return column, a, b
    return None, None, None


def decline_verdict(
    art: _Statements,
    arq: _Statements,
    art_visible: int,
    art_fresh: bool,
    arq_visible: int,
    arq_fresh: bool,
    rules: DeclineRules,
) -> tuple[str, dict[str, Any], list[str]]:
    """Section 3.2 verdict, check figures and soft reasons for one visibility state."""
    hard: list[str] = []
    soft: list[str] = []
    checks: dict[str, Any] = {"statement_basis": STATEMENT_BASIS}
    revenue_ok = margin_ok = eps_annual_ok = eps_interim_ok = False
    if art_visible >= 0 and art_fresh:
        now = int(art.best[art_visible])
        cal = date.fromordinal(int(art.cal[now]))
        prev = art.at_cal(_year_back(cal).toordinal(), art_visible)
        prev2 = art.at_cal(_year_back(cal, 2).toordinal(), art_visible)
        change = _change(art.value("revenue", now), art.value("revenue", prev))
        prior_change = _change(art.value("revenue", prev), art.value("revenue", prev2))
        revenue_ok = change is not None
        if change is not None and change < -rules.revenue_drop:
            hard.append("revenue_decline")
        if (
            change is not None
            and prior_change is not None
            and change < -rules.flat_tolerance
            and prior_change < -rules.flat_tolerance
        ):
            hard.append("revenue_two_year_decline")
        checks["revenue"] = {
            "change_pct": change,
            "prior_change_pct": prior_change,
            "evaluable": revenue_ok,
        }
        margin = None
        pair = None
        revenue_now, revenue_prev = art.value("revenue", now), art.value("revenue", prev)
        if revenue_now and revenue_prev and revenue_now > 0 and revenue_prev > 0:
            for column in ("opinc", "ebit"):
                a, b = art.value(column, now), art.value(column, prev)
                if a is not None and b is not None:
                    pair = f"{column}/revenue"
                    margin = a / revenue_now - b / revenue_prev
                    break
        margin_ok = margin is not None
        if margin is not None and -margin > rules.margin_drop_pp:
            hard.append("operating_margin_drop")
        checks["operating_margin"] = {"pair": pair, "change_pp": margin, "evaluable": margin_ok}
        column, eps_now, eps_prev = _pick(art, ("epsdil", "eps"), now, prev)
        eps_annual_ok = column is not None
        if (
            eps_prev is not None
            and eps_prev > 0
            and eps_now < eps_prev * (1 - rules.eps_annual_drop)
        ):
            soft.append("eps_decline_annual")
        checks["eps_annual"] = {
            "field": column,
            "change_pct": _change(eps_now, eps_prev),
            "evaluable": eps_annual_ok,
        }
        fcf_now, fcf_prev = art.value("fcf", now), art.value("fcf", prev)
        if fcf_now is not None and fcf_prev is not None and fcf_prev > 0:
            if fcf_now < 0:
                hard.append("fcf_turned_negative")
            elif fcf_now < fcf_prev * (1 - rules.fcf_sharp_fall):
                soft.append("fcf_sharp_fall")
        checks["fcf"] = {
            "change_pct": _change(fcf_now, fcf_prev),
            "evaluable": fcf_now is not None and fcf_prev is not None,
        }
    else:
        checks["revenue"] = {"change_pct": None, "prior_change_pct": None, "evaluable": False}
    if arq_visible >= 0 and arq_fresh:
        now = int(arq.best[arq_visible])
        cal = date.fromordinal(int(arq.cal[now]))
        prior = arq.near(
            _year_back(cal).toordinal(), arq_visible, rules.interim_window_days, int(arq.cal[now])
        )
        change = _change(arq.value("revenue", now), arq.value("revenue", prior))
        if change is not None and change < -rules.revenue_drop:
            hard.append("interim_revenue_decline")
        checks["interim_revenue"] = {"change_pct": change, "evaluable": change is not None}
        column, eps_now, eps_prev = _pick(arq, ("epsdil", "eps"), now, prior)
        eps_interim_ok = column is not None
        if (
            eps_prev is not None
            and eps_prev > 0
            and eps_now < eps_prev * (1 - rules.eps_interim_drop)
        ):
            soft.append("eps_decline_interim")
        checks["eps_interim"] = {
            "field": column,
            "change_pct": _change(eps_now, eps_prev),
            "evaluable": eps_interim_ok,
        }
    checks["hard_reasons"] = list(hard)
    if hard or len(soft) >= rules.soft_to_decline:
        verdict = "declining"
    elif not revenue_ok or not (margin_ok or eps_annual_ok or eps_interim_ok):
        verdict = "insufficient_data"
    else:
        verdict = "clear"
    return verdict, checks, soft


def decline_codes(
    statements: pd.DataFrame, session_ords: np.ndarray, rules: DeclineRules
) -> tuple[np.ndarray, np.ndarray, list[tuple[dict[str, Any], list[str]]]]:
    """(verdict code per session, detail index per session, details) for one ticker."""
    art = _Statements(statements.loc[statements["dimension"] == "ART"], _ART_COLUMNS)
    arq = _Statements(statements.loc[statements["dimension"] == "ARQ"], _ARQ_COLUMNS)
    cutoff = session_ords - rules.filing_lag_days
    k = np.searchsorted(art.filed, cutoff, side="right") - 1
    j = np.searchsorted(arq.filed, cutoff, side="right") - 1
    art_fresh = np.zeros(len(session_ords), dtype=bool)
    if len(art):
        best = art.best[np.maximum(k, 0)]
        art_fresh = (k >= 0) & (session_ords - art.filed[best] <= rules.stale_filing_days)
    arq_fresh = np.zeros(len(session_ords), dtype=bool)
    if len(arq):
        best = arq.best[np.maximum(j, 0)]
        arq_fresh = (j >= 0) & (session_ords - arq.cal[best] <= rules.interim_max_age_days)
    width = 2 * (len(arq) + 1)
    key = ((k + 1) * 2 + art_fresh) * width + (j + 1) * 2 + arq_fresh
    unique, inverse = np.unique(key, return_inverse=True)
    codes = np.zeros(len(unique), dtype=np.int8)
    details: list[tuple[dict[str, Any], list[str]]] = []
    for slot, value in enumerate(unique.tolist()):
        art_part, arq_part = divmod(int(value), width)
        verdict, checks, soft = decline_verdict(
            art,
            arq,
            art_part // 2 - 1,
            bool(art_part % 2),
            arq_part // 2 - 1,
            bool(arq_part % 2),
            rules,
        )
        codes[slot] = _CODE[verdict]
        details.append((checks, soft))
    return codes[inverse], inverse.astype(np.int32), details


def gate_tape(
    sessions: list[date],
    decline: tuple[np.ndarray, np.ndarray, list[tuple[dict[str, Any], list[str]]]],
    sector_name: str | None,
    sector: SectorTape | None,
    calendar_index: np.ndarray,
) -> GateTape:
    """Daily observations dated the day before each session, so the walker reads them on it."""
    decline_code, detail_index, details = decline
    if sector is None:
        missing = _CODE["sector_missing"] if not sector_name else _CODE["insufficient_data"]
        sector_codes = np.full(len(sessions), missing, dtype=np.int8)
    else:
        sector_codes = sector.codes[calendar_index]

    def _detail(index: int) -> dict[str, Any]:
        checks, soft = details[int(detail_index[index])]
        return {
            "checks": checks,
            "soft_checks": list(soft),
            "sector_basis": SECTOR_BASIS,
            "sector_name": sector_name,
            "sector_inputs": None if sector is None else sector.inputs(int(calendar_index[index])),
        }

    return GateTape(
        [_day(day.toordinal() - 1) for day in sessions],
        decline_code,
        sector_codes,
        GATE_LABELS,
        _detail,
    )


# --- Assembly -------------------------------------------------------------------------------


def delisting_haircuts(
    tickers: pd.DataFrame,
    actions: pd.DataFrame,
    names: Iterable[str],
    *,
    baseline: float,
    sensitivity_non_merger: float,
) -> dict[str, dict[str, float]]:
    flag = tickers.get("isdelisted", pd.Series(dtype=str)).astype(str).str.upper()
    mergers = sra.merger_exits(actions)
    out: dict[str, dict[str, float]] = {}
    for ticker in names:
        merged = ticker in mergers
        if flag.get(ticker) == "Y" or merged:
            out[ticker] = {
                "baseline": float(baseline),
                "sensitivity": float(baseline) if merged else float(sensitivity_non_merger),
            }
    return out


# --- Batched source -------------------------------------------------------------------------

DEFAULT_BATCH_SIZE = 400
TAPE_SPLIT_PREFIX = "_tapes-"
_TAPE_ROW = np.dtype(
    [("ticker", "<i4"), ("day", "<i4"), ("close", "<f8"), ("high", "<f8"), ("low", "<f8")]
)
_DAILY_CHUNK_ROWS = 1_000_000
_MEMBERSHIP_CHUNK = 256


class TapeSplit:
    """Both builds' daily bars split by ticker batch into binary files outside the repo.

    One streaming pass per ``daily.csv.gz``. As in ``load_tapes``, the first file
    with a valid bar for a ticker wins and later duplicate dates win within it.
    ``load(bucket)`` returns one batch's downloads.
    """

    def __init__(self, directory: Path, tickers: list[str], batch_size: int, hl_basis: str):
        self.directory = Path(directory)
        self.tickers = list(tickers)
        self.code = {ticker: index for index, ticker in enumerate(self.tickers)}
        self.batch_size = max(1, int(batch_size))
        self.buckets = -(-len(self.tickers) // self.batch_size)
        self.hl_basis = hl_basis
        self.present = np.zeros(len(self.tickers), dtype=bool)
        self.high_low = np.zeros(len(self.tickers), dtype=bool)
        self.days: set[int] = set()
        self.rows = 0

    def bucket_of(self, ticker: str) -> int:
        return self.code[ticker] // self.batch_size

    def _path(self, bucket: int) -> Path:
        return self.directory / f"bucket-{bucket:05d}.bin"

    def split(self, daily_paths: Iterable[Path], first_day: int) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in daily_paths:
            found = np.zeros(len(self.tickers), dtype=bool)
            for chunk in pd.read_csv(
                path,
                usecols=lambda c: c in {"date", "ticker", "high", "low", "close"},
                dtype={"ticker": str},
                chunksize=_DAILY_CHUNK_ROWS,
            ):
                high_low = "high" in chunk.columns and "low" in chunk.columns
                code = chunk["ticker"].map(self.code).to_numpy(dtype=float)
                close = pd.to_numeric(chunk["close"], errors="coerce").to_numpy(dtype=float)
                day = _ordinals(chunk["date"])
                keep = ~np.isnan(code) & ~np.isnan(close) & (day > 0)
                code = code[keep].astype(np.int32)
                fresh = ~self.present[code]
                if not fresh.all():
                    keep[np.flatnonzero(keep)[~fresh]] = False
                    code = code[fresh]
                if not len(code):
                    continue
                rows = np.empty(len(code), dtype=_TAPE_ROW)
                rows["ticker"] = code
                rows["day"] = day[keep]
                rows["close"] = close[keep]
                for column in ("high", "low"):
                    rows[column] = (
                        pd.to_numeric(chunk[column], errors="coerce").to_numpy(dtype=float)[keep]
                        if high_low
                        else np.nan
                    )
                found[code] = True
                self.high_low[code] = high_low
                self.days.update(np.unique(rows["day"][rows["day"] >= first_day]).tolist())
                self.rows += len(rows)
                bucket = code // self.batch_size
                order = np.argsort(bucket, kind="stable")
                rows, bucket = rows[order], bucket[order]
                cuts = np.flatnonzero(np.diff(bucket)) + 1
                for part in np.split(rows, cuts):
                    with open(self._path(int(part["ticker"][0]) // self.batch_size), "ab") as out:
                        out.write(part.tobytes())
            self.present |= found

    def present_tickers(self) -> set[str]:
        return {self.tickers[index] for index in np.flatnonzero(self.present)}

    def load(self, bucket: int) -> dict[str, Download]:
        path = self._path(bucket)
        if not path.exists():
            return {}
        rows = np.fromfile(path, dtype=_TAPE_ROW)
        rows = rows[np.lexsort((np.arange(len(rows)), rows["day"], rows["ticker"]))]
        repeat = (rows["ticker"][1:] == rows["ticker"][:-1]) & (rows["day"][1:] == rows["day"][:-1])
        rows = rows[np.concatenate((~repeat, [True]))]
        out: dict[str, Download] = {}
        cuts = np.flatnonzero(np.diff(rows["ticker"])) + 1
        for part in np.split(rows, cuts):
            if not len(part):
                continue
            code = int(part["ticker"][0])
            sessions = [_day(int(value)) for value in part["day"]]
            use_hl = self.hl_basis == HL_HIGH_LOW and bool(self.high_low[code])
            out[self.tickers[code]] = Download(
                as_of=sessions[-1],
                sessions=sessions,
                closes=part["close"].tolist(),
                highs=part["high"].tolist() if use_hl else None,
                lows=part["low"].tolist() if use_hl else None,
            )
        return out

    def remove(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


def _sp500_matrix(
    sp500: pd.DataFrame, calendar: list[date], column: Mapping[str, int]
) -> np.ndarray:
    """(session x ticker) ``sp500`` membership from ``membership_on``."""
    out = np.zeros((len(calendar), len(column)), dtype=bool)
    for start in range(0, len(calendar), _MEMBERSHIP_CHUNK):
        stamps = [pd.Timestamp(day) for day in calendar[start : start + _MEMBERSHIP_CHUNK]]
        members = sra.membership_on(sp500, stamps)
        for offset, stamp in enumerate(stamps):
            slots = [column[str(t)] for t in members[stamp.normalize()] if str(t) in column]
            out[start + offset, slots] = True
    return out


def _sp400_matrix(
    month_sets: Mapping[date, set[str]],
    calendar: list[date],
    sp500: np.ndarray,
    column: Mapping[str, int],
) -> tuple[np.ndarray, int]:
    """Cap-rank set of the month-end on or before each session, minus its ``sp500`` members."""
    ends = sorted(month_sets)
    slots = {end: [column[t] for t in month_sets[end] if t in column] for end in ends}
    out = np.zeros_like(sp500)
    overlap = 0
    position = -1
    for index, day in enumerate(calendar):
        while position + 1 < len(ends) and ends[position + 1] <= day:
            position += 1
        if position < 0:
            continue
        row = out[index]
        row[slots[ends[position]]] = True
        overlap += int(np.count_nonzero(row & sp500[index]))
        row &= ~sp500[index]
    return out, overlap


def _matrix_spans(
    matrix: np.ndarray, calendar: list[date], tickers: list[str]
) -> dict[str, list[tuple[date, date]]]:
    out: dict[str, list[tuple[date, date]]] = {}
    for slot in np.flatnonzero(matrix.any(axis=0)):
        edges = np.diff(np.concatenate(([0], matrix[:, slot].astype(np.int8), [0])))
        starts = np.flatnonzero(edges == 1)
        stops = np.flatnonzero(edges == -1) - 1
        out[tickers[slot]] = [
            (calendar[a], calendar[b]) for a, b in zip(starts.tolist(), stops.tolist(), strict=True)
        ]
    return out


def _universe_sector_tapes(
    matrix: np.ndarray,
    tickers: list[str],
    flag_column: Mapping[str, int],
    below_all: np.ndarray,
    trend_all: np.ndarray,
    sectors: Mapping[str, str | None],
    rules: SectorRules,
) -> dict[str, SectorTape]:
    by_sector: dict[str, tuple[list[int], list[int]]] = {}
    for slot in np.flatnonzero(matrix.any(axis=0)).tolist():
        ticker = tickers[slot]
        if not sectors.get(ticker):
            continue
        member_slots, flag_slots = by_sector.setdefault(str(sectors[ticker]), ([], []))
        member_slots.append(slot)
        flag_slots.append(flag_column[ticker])
    return {
        label: _sector_tape(matrix[:, a], below_all[:, b], trend_all[:, b], rules)
        for label, (a, b) in by_sector.items()
    }


@dataclass
class RehearsalSource:
    """The rehearsal's inputs held compactly, with walker specs built one batch at a time.

    Whole-book tables stay in memory: screen rows, universe spans, sector
    verdicts, statement rows and (when built) the ``CrossNameTape``. Daily bars
    stay in the tape split on disk until a batch's specs are built. ``remove``
    deletes the split.
    """

    hl_basis: str
    cache_keys: dict[str, dict[str, Any]]
    counts: dict[str, int]
    haircuts: dict[str, dict[str, float]]
    tickers: set[str]
    calendar: list[date]
    batches: list[tuple[int, list[str]]]
    split: TapeSplit
    screens: dict[str, ScreenTable]
    spans: dict[str, dict[str, list[tuple[date, date]]]]
    sectors: Mapping[str, str | None]
    first_signal: date
    decline_rules: DeclineRules
    cross: CrossNameTape | None = None
    sector_by_universe: dict[str, dict[str, SectorTape]] = field(default_factory=dict)
    statements: pd.DataFrame | None = None
    statement_rows: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def names_walked(self) -> int:
        return self.counts["names_walked_sp500"] + self.counts["names_walked_sp400"]

    def order(self) -> dict[tuple[str, str], int]:
        """Position of each (market, ticker) in the whole-book spec list of ``build_inputs``."""
        walked = sorted(ticker for _bucket, tickers in self.batches for ticker in tickers)
        keys = [
            (market, ticker)
            for market in (SP500, SP400)
            for ticker in walked
            if ticker in self.screens[market].rows
        ]
        return {key: index for index, key in enumerate(keys)}

    def specs(self, position: int, *, gates: bool = True) -> list[NameSpec]:
        bucket, tickers = self.batches[position]
        return self._specs(tickers, self.split.load(bucket), gates=gates)

    def _specs(
        self, tickers: list[str], downloads: Mapping[str, Download], *, gates: bool
    ) -> list[NameSpec]:
        calendar_ord = np.fromiter((day.toordinal() for day in self.calendar), dtype=np.int64)
        empty = None if self.statements is None else self.statements.iloc[0:0]
        out: list[NameSpec] = []
        for market in (SP500, SP400):
            table = self.screens[market]
            for ticker in tickers:
                download = downloads.get(ticker)
                if ticker not in table.rows or download is None:
                    continue
                label = self.sectors.get(ticker)
                cut = self.haircuts.get(ticker)
                tape: GateTape | list = []
                if gates:
                    sessions = [day for day in download.sessions if day >= self.first_signal]
                    ords = np.fromiter((day.toordinal() for day in sessions), dtype=np.int64)
                    rows = self.statement_rows.get(ticker)
                    statements = empty if rows is None else self.statements.iloc[rows]
                    tape = gate_tape(
                        sessions,
                        decline_codes(statements, ords, self.decline_rules),
                        label,
                        self.sector_by_universe[market].get(label) if label else None,
                        np.searchsorted(calendar_ord, ords),
                    )
                out.append(
                    NameSpec(
                        market=market,
                        ticker=ticker,
                        downloads=[download],
                        screens=table.facts(ticker),
                        gates=tape,
                        universe=self.spans[market].get(ticker, []),
                        book_key=ticker,
                        terminal_haircut=None if cut is None else cut["baseline"],
                    )
                )
        return out

    def remove(self) -> None:
        self.split.remove()


def prepare(
    sp500_build: BuildDir,
    mid_build: BuildDir,
    sharadar_dir: Path,
    registration: Mapping[str, Any],
    *,
    work_dir: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    cross_options: WalkOptions | None = None,
) -> RehearsalSource:
    """Read every licensed input once, compactly; daily bars go to a tape split in ``work_dir``.

    With ``cross_options`` the source also carries the whole book's
    ``CrossNameTape`` for those walk options, so batches can be walked alone.
    Batches group tickers, not universes: a ticker's ``sp500`` and ``sp400``
    specs share a book key and must be walked together.
    """
    first_signal = date.fromisoformat(registration["windows"]["development"]["first_signal"])
    sp500_cache, sp500_panel, sp500_key = checked_cache(sp500_build)
    mid_cache, mid_panel, mid_key = checked_cache(mid_build)
    files = SharadarFiles.find(Path(sharadar_dir))
    hl_basis = export_hl_basis(files.stocks)
    tickers = sra.load_tickers(files.tickers)
    actions = sra.load_actions(files.actions)
    sp500_table = sra.load_sp500(files.sp500)
    sectors = {
        str(ticker): (str(label).strip() or None) if isinstance(label, str) else None
        for ticker, label in tickers.get("sector", pd.Series(dtype=str)).items()
    }
    screens = {
        SP500: ScreenTable(sp500_cache, sp500_panel, sectors),
        SP400: ScreenTable(mid_cache, mid_panel, sectors),
    }
    del sp500_cache, sp500_panel, mid_cache, mid_panel
    universe_rule = registration["universes"][SP400]
    month_sets = cap_rank_month_sets(
        files,
        tickers,
        [_day(day) for day in screens[SP400].dates],
        rank_from=int(universe_rule["rank_from"]),
        rank_to=int(universe_rule["rank_to"]),
    )
    screened = set(screens[SP500].rows) | set(screens[SP400].rows)
    wanted = sorted(screened | set().union(*month_sets.values()))
    work = Path(work_dir).expanduser()
    work.mkdir(parents=True, exist_ok=True)
    split = TapeSplit(
        Path(tempfile.mkdtemp(prefix=TAPE_SPLIT_PREFIX, dir=work)), wanted, batch_size, hl_basis
    )
    try:
        split.split([sp500_build.daily, mid_build.daily], first_signal.toordinal())
        calendar = [_day(day) for day in sorted(split.days)]
        calendar_ord = np.fromiter((day.toordinal() for day in calendar), dtype=np.int64)
        present = split.present_tickers()
        space = sorted({str(t) for t in sp500_table.get("ticker", [])} | set(wanted))
        column = {ticker: index for index, ticker in enumerate(space)}
        sp500_matrix = _sp500_matrix(sp500_table, calendar, column)
        sp400_matrix, overlap = _sp400_matrix(month_sets, calendar, sp500_matrix, column)
        spans = {
            SP500: _matrix_spans(sp500_matrix, calendar, space),
            SP400: _matrix_spans(sp400_matrix, calendar, space),
        }
        absent = np.array([ticker not in present for ticker in space], dtype=bool)
        without_tape = int(
            np.count_nonzero(sp500_matrix[:, absent]) + np.count_nonzero(sp400_matrix[:, absent])
        )
        ever = sp500_matrix.any(axis=0) | sp400_matrix.any(axis=0)
        flagged = [space[slot] for slot in np.flatnonzero(ever) if sectors.get(space[slot])]
        flag_column = {ticker: index for index, ticker in enumerate(flagged)}
        below_all = np.full((len(calendar), len(flagged)), -1, dtype=np.int8)
        trend_all = np.full((len(calendar), len(flagged)), np.nan, dtype=np.float32)

        walked = sorted(screened & present)
        grouped: dict[int, list[str]] = {}
        for ticker in walked:
            grouped.setdefault(split.bucket_of(ticker), []).append(ticker)
        prices = registration.get("prices") or {}
        source = RehearsalSource(
            hl_basis=hl_basis,
            cache_keys={SP500: sp500_key, SP400: mid_key},
            counts={
                "names_walked_sp500": sum(1 for t in walked if t in screens[SP500].rows),
                "names_walked_sp400": sum(1 for t in walked if t in screens[SP400].rows),
                "overlap_excluded_from_sp400": overlap,
                "member_sessions_without_tape": without_tape,
                "screened_names_without_tape": len(screened - present),
            },
            haircuts=delisting_haircuts(
                tickers,
                actions,
                walked,
                baseline=float(prices.get("delisting_baseline_haircut", 0.0)),
                sensitivity_non_merger=float(
                    prices.get("delisting_sensitivity_haircut_non_merger", -0.3)
                ),
            ),
            tickers=present | screened,
            calendar=calendar,
            batches=sorted(grouped.items()),
            split=split,
            screens=screens,
            spans=spans,
            sectors=sectors,
            first_signal=first_signal,
            decline_rules=DeclineRules.from_registration(registration),
            cross=None if cross_options is None else CrossNameTape(cross_options),
        )
        sector_rules = SectorRules.from_registration(registration)
        for bucket in range(split.buckets):
            downloads = split.load(bucket)
            for ticker, download in downloads.items():
                slot = flag_column.get(ticker)
                if slot is None or not download.sessions:
                    continue
                positions, low, ret = _own_bar_flags(download, calendar_ord, sector_rules)
                below_all[positions, slot] = low
                trend_all[positions, slot] = ret
            if source.cross is not None and bucket in grouped:
                source.cross.add(source._specs(grouped[bucket], downloads, gates=False))
            del downloads
        source.sector_by_universe = {
            market: _universe_sector_tapes(
                matrix, space, flag_column, below_all, trend_all, sectors, sector_rules
            )
            for market, matrix in ((SP500, sp500_matrix), (SP400, sp400_matrix))
        }
        del sp500_matrix, sp400_matrix, below_all, trend_all
        statements = load_statements(files.fundamentals, set(walked))
        for name in ("ticker", "dimension"):
            statements[name] = statements[name].astype(str).astype("category")
        source.statements = statements
        source.statement_rows = {
            str(ticker): rows
            for ticker, rows in statements.groupby(
                "ticker", sort=False, observed=True
            ).indices.items()
        }
        if source.cross is not None:
            source.cross.finish()
        return source
    except BaseException:
        split.remove()
        raise


def build_inputs(
    sp500_build: BuildDir,
    mid_build: BuildDir,
    sharadar_dir: Path,
    registration: Mapping[str, Any],
) -> RehearsalInputs:
    """Read every licensed input and return the walker specs (both universes, one book)."""
    with tempfile.TemporaryDirectory(prefix="rehearsal-") as work:
        source = prepare(
            sp500_build,
            mid_build,
            sharadar_dir,
            registration,
            work_dir=Path(work),
            batch_size=1 << 30,
        )
        try:
            specs = [spec for index in range(len(source.batches)) for spec in source.specs(index)]
        finally:
            source.remove()
    order = source.order()
    specs.sort(key=lambda spec: order[(spec.market, spec.ticker)])
    return RehearsalInputs(
        specs=specs,
        haircuts=source.haircuts,
        tickers=source.tickers,
        hl_basis=source.hl_basis,
        cache_keys=source.cache_keys,
        counts=source.counts,
    )
