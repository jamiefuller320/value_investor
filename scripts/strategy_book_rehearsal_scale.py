"""Time the strategy-book US rehearsal on synthetic Sharadar-shaped tables.

Writes a random-walk SEP export and an ART/ARQ fundamentals export with
Sharadar column names into a temporary directory, builds the gate tapes and
name specs the way ``build_inputs`` does, then runs the real ``develop`` and
``reveal`` against a temporary copy of the registration. No licensed data is
read; the screen signals are random monthly draws instead of a replay cache.

    python scripts/strategy_book_rehearsal_scale.py --names 1000 --sessions 6500
"""

from __future__ import annotations

import argparse
import json
import resource
import shutil
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from value_investor import strategy_book_us_rehearsal as rehearsal
from value_investor import strategy_book_us_tape as tape
from value_investor.strategy_book_observe import NameSpec, ScreenFact

REPO = Path(__file__).resolve().parents[1]
SECTORS = ("Technology", "Industrials", "Healthcare", "Energy", "Utilities", "Financial Services")


def _rss_mb() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024)


def _calendar(first: date, sessions: int) -> list[date]:
    days: list[date] = []
    day = first
    while len(days) < sessions:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def write_tables(root: Path, tickers: list[str], calendar: list[date], seed: int) -> None:
    rng = np.random.default_rng(seed)
    stamps = pd.Index(pd.to_datetime(calendar)).strftime("%Y-%m-%d")
    with (root / "SHARADAR_SEP.csv").open("w", encoding="utf-8") as handle:
        handle.write("ticker,date,open,high,low,close,volume,closeadj,closeunadj,lastupdated\n")
        for ticker in tickers:
            rets = rng.normal(0.0003, 0.02, len(calendar))
            close = 50.0 * np.exp(np.cumsum(rets))
            spread = np.abs(rng.normal(0.0, 0.01, len(calendar)))
            frame = pd.DataFrame(
                {
                    "ticker": ticker,
                    "date": stamps,
                    "open": close,
                    "high": close * (1 + spread),
                    "low": close * (1 - spread),
                    "close": close,
                    "volume": 1_000_000,
                    "closeadj": close,
                    "closeunadj": close,
                    "lastupdated": "2026-11-06",
                }
            )
            frame.to_csv(handle, header=False, index=False, float_format="%.4f")
    quarters = pd.date_range(calendar[0] - timedelta(days=800), calendar[-1], freq="QE")
    rows = []
    for ticker in tickers:
        level = np.exp(np.cumsum(rng.normal(0.01, 0.06, len(quarters))))
        for index, quarter in enumerate(quarters):
            filed = quarter + timedelta(days=int(rng.integers(25, 70)))
            for dimension, scale in (("ARQ", 0.25), ("ART", 1.0)):
                revenue = 1000.0 * level[index] * scale
                rows.append(
                    (
                        ticker,
                        dimension,
                        quarter.date().isoformat(),
                        filed.date().isoformat(),
                        quarter.date().isoformat(),
                        revenue,
                        revenue * 0.12,
                        revenue * 0.13,
                        revenue * 0.002,
                        revenue * 0.002,
                        revenue * 0.08,
                        revenue * 5,
                    )
                )
    pd.DataFrame(
        rows,
        columns=[
            "ticker",
            "dimension",
            "calendardate",
            "datekey",
            "reportperiod",
            "revenue",
            "opinc",
            "ebit",
            "epsdil",
            "eps",
            "fcf",
            "marketcap",
        ],
    ).to_csv(root / "SHARADAR_SF1.csv", index=False)


def synthetic_inputs(
    root: Path, tickers: list[str], calendar: list[date], registration: dict[str, Any], seed: int
) -> tuple[tape.RehearsalInputs, dict[str, float]]:
    rng = np.random.default_rng(seed + 1)
    timings: dict[str, float] = {}
    first_signal = date.fromisoformat(registration["windows"]["development"]["first_signal"])
    half = len(tickers) // 2
    movers = set(tickers[half : half + max(1, len(tickers) // 20)])
    switch = calendar[len(calendar) // 2]
    sp500 = [
        {t for t in tickers[:half]} | ({t for t in movers} if day >= switch else set())
        for day in calendar
    ]
    sp400 = [set(tickers[half:]) - (movers if day >= switch else set()) for day in calendar]
    sectors = {ticker: SECTORS[index % len(SECTORS)] for index, ticker in enumerate(tickers)}

    started = time.perf_counter()
    tapes = tape.load_tapes([root / "SHARADAR_SEP.csv"], set(tickers), hl_basis=tape.HL_HIGH_LOW)
    timings["load_prices_s"] = time.perf_counter() - started

    started = time.perf_counter()
    statements = tape.load_statements(root / "SHARADAR_SF1.csv", set(tickers))
    grouped = {str(t): rows for t, rows in statements.groupby("ticker", sort=False)}
    timings["load_fundamentals_s"] = time.perf_counter() - started

    started = time.perf_counter()
    rules = tape.SectorRules.from_registration(registration)
    by_universe = {
        tape.SP500: tape.sector_tapes(calendar, sp500, sectors, tapes, rules),
        tape.SP400: tape.sector_tapes(calendar, sp400, sectors, tapes, rules),
    }
    spans = {
        tape.SP500: tape.spans_from_days(calendar, sp500),
        tape.SP400: tape.spans_from_days(calendar, sp400),
    }
    timings["sector_tapes_s"] = time.perf_counter() - started

    started = time.perf_counter()
    decline_rules = tape.DeclineRules.from_registration(registration)
    calendar_ord = np.fromiter((day.toordinal() for day in calendar), dtype=np.int64)
    month_ends = [
        calendar[i]
        for i in range(len(calendar) - 1)
        if calendar[i].month != calendar[i + 1].month and calendar[i] >= first_signal
    ]
    specs: list[NameSpec] = []
    for market, names in (
        (tape.SP500, tickers[:half] + sorted(movers)),
        (tape.SP400, tickers[half:]),
    ):
        for ticker in names:
            download = tapes[ticker]
            sessions = [day for day in download.sessions if day >= first_signal]
            ords = np.fromiter((day.toordinal() for day in sessions), dtype=np.int64)
            index = np.searchsorted(calendar_ord, ords)
            decline = tape.decline_codes(grouped[ticker], ords, decline_rules)
            draws = rng.choice(
                ["buy", "strong_buy", "hold", "avoid"], len(month_ends), p=[0.1, 0.03, 0.55, 0.32]
            )
            screens = [
                ScreenFact(
                    run_date=day,
                    signal=str(signal),
                    sector=sectors[ticker],
                    fields={
                        "composite_score": float(rng.uniform(40, 90)),
                        "earnings_yield_pe": float(rng.uniform(0.02, 0.2)),
                        "weeks_at_signal": int(rng.integers(1, 12)),
                        "models_passed": int(rng.integers(1, 6)),
                        "market_cap": float(rng.uniform(1e9, 5e10)),
                    }
                    if signal in ("buy", "strong_buy")
                    else {},
                )
                for day, signal in zip(month_ends, draws, strict=True)
            ]
            specs.append(
                NameSpec(
                    market=market,
                    ticker=ticker,
                    downloads=[download],
                    screens=screens,
                    gates=tape.gate_tape(
                        sessions,
                        decline,
                        sectors[ticker],
                        by_universe[market].get(sectors[ticker]),
                        index,
                    ),
                    universe=spans[market].get(ticker, []),
                    book_key=ticker,
                )
            )
    timings["gate_tapes_and_specs_s"] = time.perf_counter() - started
    delisted = {ticker: {"baseline": 0.0, "sensitivity": -0.3} for ticker in tickers[::37]}
    inputs = tape.RehearsalInputs(
        specs=specs,
        haircuts=delisted,
        tickers=set(tickers),
        hl_basis=tape.HL_HIGH_LOW,
        cache_keys={
            universe: {"screen_code": "synthetic", "panel": "synthetic"}
            for universe in ("sp500", "midcap")
        },
        counts={"overlap_excluded_from_sp400": 0},
    )
    return inputs, timings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--names", type=int, default=1000)
    parser.add_argument("--sessions", type=int, default=6500)
    parser.add_argument("--first-session", default="2000-01-03")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--keep", action="store_true", help="Keep the temporary directory.")
    args = parser.parse_args(argv)

    work = Path(tempfile.mkdtemp(prefix="rehearsal-scale-"))
    try:
        vendor = work / "vendor"
        vendor.mkdir()
        repo = work / "repo"
        (repo / rehearsal.STORE_PATH).parent.mkdir(parents=True)
        shutil.copy(REPO / rehearsal.PARENT_SEAL, repo / rehearsal.PARENT_SEAL)
        shutil.copy(REPO / rehearsal.REGISTRATION_PATH, repo / rehearsal.REGISTRATION_PATH)
        registration = rehearsal.load_registration(repo)
        tickers = [f"S{index:04d}" for index in range(args.names)]
        calendar = _calendar(date.fromisoformat(args.first_session), args.sessions)

        started = time.perf_counter()
        write_tables(vendor, tickers, calendar, args.seed)
        report: dict[str, Any] = {
            "names": args.names,
            "sessions": args.sessions,
            "calendar": [calendar[0].isoformat(), calendar[-1].isoformat()],
            "write_synthetic_tables_s": time.perf_counter() - started,
            "sep_mb": (vendor / "SHARADAR_SEP.csv").stat().st_size // 2**20,
        }
        started = time.perf_counter()
        inputs, timings = synthetic_inputs(vendor, tickers, calendar, registration, args.seed)
        report.update(timings)
        report["build_inputs_s"] = time.perf_counter() - started
        report["rss_after_inputs_mb"] = _rss_mb()

        rehearsal.build_inputs = lambda *_args, **_kwargs: inputs
        build = work / "build"
        for name in ("build", "mid"):
            (work / name).mkdir()
        started = time.perf_counter()
        developed = rehearsal.develop(build, work / "mid", vendor, repo_root=repo)
        report["develop_s"] = time.perf_counter() - started
        report["development_mature_primary"] = developed["store"]["development"]["primary"][
            "mature"
        ]
        report["rss_after_develop_mb"] = _rss_mb()
        started = time.perf_counter()
        revealed = rehearsal.reveal(build, work / "mid", vendor, repo_root=repo)
        report["reveal_s"] = time.perf_counter() - started
        confirmation = revealed["store"]["confirmation"]
        report["confirmation_mature_primary"] = confirmation["primary"]["mature"]
        report["development_reproduced"] = confirmation["development_reproduced"]
        report["store_kb"] = (repo / rehearsal.STORE_PATH).stat().st_size // 1024
        report["scratch_mb"] = (
            sum(path.stat().st_size for path in (build / rehearsal.SCRATCH_DIRNAME).rglob("*"))
            // 2**20
        )
        report["peak_rss_mb"] = _rss_mb()
        print(
            json.dumps(
                {k: round(v, 1) if isinstance(v, float) else v for k, v in report.items()}, indent=1
            )
        )
    finally:
        if args.keep:
            print(f"kept {work}", file=sys.stderr)
        else:
            shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
