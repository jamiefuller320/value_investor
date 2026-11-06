"""Peak memory and time of the strategy-book US rehearsal at the owner's data shape.

Writes synthetic build directories and Sharadar-shaped tables of the real
shape: about 1,070 ``sp500`` names over 5.2M daily rows and 3,380 cap-rank
names over 12.5M daily rows, with staggered listings, delistings, index
changes and names that move from the cap-rank set into ``sp500``. Then runs
the input load, ``develop`` and ``reveal`` each in a fresh process and reports
each one's peak resident memory and time. No licensed data is read, nothing
touches the network, and every file is written under a temporary directory.

The cap-rank month sets are written with the data and passed to the runner
in place of ``cap_rank_month_sets`` (the SEP ranking pass streams the export
in fixed chunks and is not part of this measure). The registration is the
repository's, so the windows, bootstrap resamples and cuts are the real ones.

    python scripts/strategy_book_rehearsal_scale.py
    python scripts/strategy_book_rehearsal_scale.py --batch-size 200
    python scripts/strategy_book_rehearsal_scale.py --data-dir D:/tmp/scale --keep

Peak memory is ``ru_maxrss`` on Linux and macOS, ``peak_wset`` from psutil on
Windows, and the tracemalloc peak (Python allocations only) when neither is
available.
"""

from __future__ import annotations

import argparse
import inspect
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SECTORS = (
    "Technology",
    "Industrials",
    "Healthcare",
    "Energy",
    "Utilities",
    "Financial Services",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Basic Materials",
    "Real Estate",
    "Communication Services",
)
FIRST_SESSION = "1998-01-02"
LAST_SESSION = "2025-09-30"
FIRST_MONTH = "2000-01"
SLOTS = 500
READY = "ready.json"


# --- Memory ---------------------------------------------------------------------------------


def _start_measure() -> str:
    try:
        import resource  # noqa: F401

        return "ru_maxrss"
    except ImportError:
        pass
    try:
        import psutil

        if getattr(psutil.Process().memory_info(), "peak_wset", None) is not None:
            return "peak_wset"
    except ImportError:
        pass
    import tracemalloc

    tracemalloc.start()
    return "tracemalloc"


def _peak_mb(method: str) -> float:
    if method == "ru_maxrss":
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / 2**20 if sys.platform == "darwin" else peak / 1024
    if method == "peak_wset":
        import psutil

        return psutil.Process().memory_info().peak_wset / 2**20
    import tracemalloc

    return tracemalloc.get_traced_memory()[1] / 2**20


# --- Synthetic data -------------------------------------------------------------------------


def _slots(
    rng: np.random.Generator, periods: int, occupants: int, first_label: int, prefix: str
) -> list[tuple[str, int, int]]:
    """(ticker, first period, last period) for ``SLOTS`` seats and ``occupants`` holders."""
    changes = np.sort(rng.integers(1, periods, size=occupants - SLOTS))
    seats = rng.integers(0, SLOTS, size=len(changes))
    starts = [[0] for _ in range(SLOTS)]
    for seat, period in zip(seats.tolist(), changes.tolist(), strict=True):
        if period > starts[seat][-1]:
            starts[seat].append(period)
    out = []
    label = first_label
    for seat_starts in starts:
        for index, start in enumerate(seat_starts):
            stop = seat_starts[index + 1] - 1 if index + 1 < len(seat_starts) else periods - 1
            out.append((f"{prefix}{label:04d}", start, stop))
            label += 1
    return out


def _listing(
    rng: np.random.Generator, first: int, last: int, sessions: int, *, before: int, gone: float
) -> tuple[int, int]:
    start = 0 if first == 0 else max(0, first - int(rng.integers(0, before)))
    stop = sessions - 1
    if last < sessions - 1 and rng.random() < gone:
        stop = min(sessions - 1, last + int(rng.integers(5, 250)))
    return start, stop


def make_shape(seed: int) -> dict[str, Any]:
    """Membership, listings and month sets of the real shape (no prices yet)."""
    rng = np.random.default_rng(seed)
    calendar = pd.bdate_range(FIRST_SESSION, LAST_SESSION)
    sessions = len(calendar)
    months = pd.Series(calendar).groupby(calendar.to_period("M")).max()
    month_ends = [day for period, day in months.items() if str(period) >= FIRST_MONTH]
    month_pos = calendar.get_indexer(pd.DatetimeIndex(month_ends))
    first_signal = int(calendar.searchsorted(pd.Timestamp("2000-01-03")))

    sp500 = _slots(rng, sessions - first_signal, 1_070, 0, "A")
    sp500 = [(t, a + first_signal if a else 0, b + first_signal) for t, a, b in sp500]
    mid = _slots(rng, len(month_ends), 3_250, 0, "M")
    listing: dict[str, tuple[int, int]] = {}
    for ticker, a, b in sp500:
        listing[ticker] = _listing(rng, a, b, sessions, before=2_800, gone=0.55)
    mid_spans: dict[str, tuple[int, int]] = {}
    for ticker, a, b in mid:
        first, last = int(month_pos[a]) if a else 0, int(month_pos[b])
        listing[ticker] = _listing(rng, first, last, sessions, before=1_750, gone=0.33)
        mid_spans[ticker] = (a, b)
    # Names that rank 501-1000 for up to two years and then join sp500.
    joiners = [row for row in sp500 if row[1] > month_pos[24]][:150]
    for ticker, a, _b in joiners:
        joined = int(np.searchsorted(month_pos, a))
        mid_spans[ticker] = (max(0, joined - int(rng.integers(6, 25))), joined)
    month_sets: dict[str, list[str]] = {}
    for index, day in enumerate(month_ends):
        month_sets[day.date().isoformat()] = sorted(
            t for t, (a, b) in mid_spans.items() if a <= index <= b
        )
    return {
        "calendar": calendar,
        "month_ends": month_ends,
        "month_pos": month_pos,
        "sp500": sp500,
        "joiners": {t for t, _a, _b in joiners},
        "mid": [t for t, _a, _b in mid],
        "listing": listing,
        "month_sets": month_sets,
    }


def _write_daily(path: Path, tickers: list[str], shape: dict[str, Any], seed: int) -> int:
    calendar = shape["calendar"]
    stamps = np.asarray(calendar.strftime("%Y-%m-%d"))
    rows = 0
    first = True
    for start in range(0, len(tickers), 200):
        frames = []
        for ticker in tickers[start : start + 200]:
            rng = np.random.default_rng([seed, int(ticker[1:]), ord(ticker[0])])
            a, b = shape["listing"][ticker]
            n = b - a + 1
            shocks = rng.normal(rng.uniform(-0.0002, 0.0006), 0.02, n)
            shocks[rng.random(n) < 0.004] -= 0.08
            close = 30.0 * np.exp(np.cumsum(shocks))
            spread = np.abs(rng.normal(0.0, 0.01, n))
            frames.append(
                pd.DataFrame(
                    {
                        "date": stamps[a : b + 1],
                        "ticker": ticker,
                        "open": close,
                        "high": close * (1 + spread),
                        "low": close * (1 - spread),
                        "close": close,
                    }
                )
            )
            rows += n
        pd.concat(frames, ignore_index=True).to_csv(
            path,
            mode="w" if first else "a",
            header=first,
            index=False,
            float_format="%.4f",
            compression={"method": "gzip", "compresslevel": 1},
        )
        first = False
    return rows


def _members_by_month(shape: dict[str, Any]) -> dict[str, list[list[str]]]:
    pos = shape["month_pos"]
    sp500 = [[] for _ in pos]
    for ticker, a, b in shape["sp500"]:
        for index in np.flatnonzero((pos >= a) & (pos <= b)).tolist():
            sp500[index].append(ticker)
    mid = [shape["month_sets"][day.date().isoformat()] for day in shape["month_ends"]]
    return {"sp500": sp500, "midcap": mid}


def _write_build(
    root: Path, universe: str, members: list[list[str]], shape: dict[str, Any], seed: int
) -> int:
    from value_investor import historical_screen_replay as hsr

    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng([seed, len(universe)])
    tickers = sorted({t for month in members for t in month})
    rows = _write_daily(root / "daily.csv.gz", tickers, shape, seed)
    sector = {t: SECTORS[int(t[1:]) % len(SECTORS)] for t in tickers}
    state: dict[str, bool] = {}
    panel_rows, cache_rows = [], []
    passes = [f"model_{index:02d}" for index in range(22)]
    for day, month in zip(shape["month_ends"], members, strict=True):
        as_of = day.date().isoformat()
        draws = rng.random((len(month), 3))
        for ticker, (u, v, w) in zip(month, draws.tolist(), strict=True):
            buy = u < (0.6 if state.get(ticker) else 0.08)
            state[ticker] = buy
            signal = (
                ("strong_buy" if v < 0.2 else "buy") if buy else ("hold" if v < 0.55 else "avoid")
            )
            panel_rows.append(
                {
                    "as_of": as_of,
                    "ticker": ticker,
                    "name": f"Synthetic {ticker}",
                    "sector": sector[ticker],
                    **{f"field_{k:02d}": w * (k + 1) for k in range(30)},
                    "market_cap": 1e9 * (1 + 20 * w),
                    "profit_margins": 0.02 + 0.2 * v,
                    "debt_to_equity": 40 + 100 * u,
                    "revenue_growth": v - 0.4,
                    "earnings_growth": w - 0.5,
                    "free_cashflow": 1e8 * (w - 0.2),
                    "enterprise_value": 1.2e9 * (1 + 20 * w),
                    "ebit": 1.5e8 * (v + 0.1),
                }
            )
            cache_rows.append(
                {
                    "as_of": f"{as_of} 00:00:00+00:00",
                    "ticker": ticker,
                    "signal": signal,
                    "conviction_score": round(w, 4),
                    "sector": sector[ticker],
                    "earnings_yield": 0.02 + 0.1 * w,
                    "composite_score": round(v, 4),
                    "data_quality_score": 1.0,
                    **{
                        f"{hsr.MODEL_PASS_PREFIX}{p}": int(w > k / 22) for k, p in enumerate(passes)
                    },
                    **{
                        f"{hsr.MODEL_SCORE_PREFIX}{p}": round(w * k, 3)
                        for k, p in enumerate(passes)
                    },
                }
            )
    pd.DataFrame(panel_rows).to_csv(root / "panel.csv.gz", index=False)
    pd.DataFrame(cache_rows).to_csv(root / hsr.SIGNAL_CACHE_NAME, index=False)
    key = hsr.signal_cache_key(pd.read_csv(root / "panel.csv.gz"), None)
    (root / f"{hsr.SIGNAL_CACHE_NAME}.key.json").write_text(json.dumps(key))
    pd.DataFrame(
        {"date": [shape["month_ends"][0].date()], "ticker": [tickers[0]], "close": [1.0]}
    ).to_csv(root / "prices.csv.gz", index=False)
    (root / "terminal_baseline.csv").write_text("ticker,terminal\n")
    return rows


def _write_vendor(root: Path, shape: dict[str, Any], seed: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng([seed, 99])
    calendar = shape["calendar"]
    last = len(calendar) - 1
    listing = shape["listing"]
    names = sorted(listing)
    delisted = {t for t in names if listing[t][1] < last}
    mergers = sorted(t for t in delisted if int(t[1:]) % 2 == 0)
    pd.DataFrame(
        {
            "table": "SF1",
            "ticker": names,
            "name": [f"Synthetic {t}" for t in names],
            "sector": [SECTORS[int(t[1:]) % len(SECTORS)] for t in names],
            "currency": "USD",
            "isdelisted": ["Y" if t in delisted else "N" for t in names],
            "category": "Domestic Common Stock",
        }
    ).to_csv(root / "tickers.csv", index=False)
    pd.DataFrame(
        {
            "date": [calendar[listing[t][1]].date().isoformat() for t in mergers],
            "action": "acquisitionby",
            "ticker": mergers,
            "name": "",
            "value": "",
            "contraticker": "A0001",
            "contraname": "",
        }
    ).to_csv(root / "actions.csv", index=False)
    rows = []
    stamp = lambda i: calendar[i].date().isoformat()  # noqa: E731
    for ticker, a, b in shape["sp500"]:
        if a == 0:
            rows.append({"date": stamp(0), "action": "historical", "ticker": ticker})
        else:
            rows.append({"date": stamp(a), "action": "added", "ticker": ticker})
        if b < last:
            rows.append({"date": stamp(b + 1), "action": "removed", "ticker": ticker})
        else:
            rows.append({"date": stamp(last), "action": "current", "ticker": ticker})
    pd.DataFrame(rows).assign(name="", contraticker="", contraname="", note="").to_csv(
        root / "sp500.csv", index=False
    )
    quarters = pd.date_range("1996-03-31", LAST_SESSION, freq="QE")
    frames = []
    for ticker in names:
        a, b = listing[ticker]
        q = quarters[(quarters >= calendar[a] - pd.Timedelta(days=730)) & (quarters <= calendar[b])]
        n = len(q)
        level = 1e9 * np.exp(np.cumsum(rng.normal(0.01, 0.07, n)))
        margin = np.clip(0.12 + np.cumsum(rng.normal(0, 0.01, n)), -0.2, 0.4)
        filed = (q + pd.to_timedelta(rng.integers(25, 80, n), unit="D")).strftime("%Y-%m-%d")
        cal = q.strftime("%Y-%m-%d")
        for dimension, scale in (("ART", 1.0), ("ARQ", 0.25), ("MRT", 1.0)):
            revenue = level * scale
            frames.append(
                pd.DataFrame(
                    {
                        "ticker": ticker,
                        "dimension": dimension,
                        "calendardate": cal,
                        "datekey": filed,
                        "reportperiod": cal,
                        "lastupdated": "2025-10-01",
                        "revenue": revenue,
                        "opinc": revenue * margin,
                        "ebit": revenue * (margin + 0.01),
                        "epsdil": revenue * margin / 1e8,
                        "eps": revenue * margin / 1e8,
                        "fcf": revenue * (margin - 0.02),
                        "marketcap": level * 3,
                        **{f"extra_{k:02d}": revenue * k for k in range(20)},
                    }
                )
            )
    pd.concat(frames, ignore_index=True).to_csv(
        root / "fundamentals.csv.gz",
        index=False,
        float_format="%.6g",
        compression={"method": "gzip", "compresslevel": 1},
    )
    (root / "stocks.csv").write_text(
        "ticker,date,open,high,low,close,volume,closeadj,closeunadj,lastupdated\n"
    )


def generate(data: Path, seed: int) -> dict[str, Any]:
    started = time.perf_counter()
    shape = make_shape(seed)
    members = _members_by_month(shape)
    report = {
        "sessions": len(shape["calendar"]),
        "month_ends": len(shape["month_ends"]),
        "sp500_unique_members": len({t for m in members["sp500"] for t in m}),
        "midcap_unique_members": len({t for m in members["midcap"] for t in m}),
        "joiners": len(shape["joiners"]),
    }
    report["sp500_daily_rows"] = _write_build(
        data / "hsr-sp500", "sp500", members["sp500"], shape, seed
    )
    report["midcap_daily_rows"] = _write_build(
        data / "hsr-midcap", "midcap", members["midcap"], shape, seed
    )
    _write_vendor(data / "vendor", shape, seed)
    (data / "month_sets.json").write_text(json.dumps(shape["month_sets"]))
    report["generate_s"] = round(time.perf_counter() - started, 1)
    (data / READY).write_text(json.dumps(report, indent=1))
    return report


# --- Phases ---------------------------------------------------------------------------------


def _repo(root: Path) -> Path:
    from value_investor import strategy_book_us_rehearsal as rehearsal

    shutil.rmtree(root, ignore_errors=True)
    (root / rehearsal.STORE_PATH).parent.mkdir(parents=True)
    shutil.copy(REPO / rehearsal.PARENT_SEAL, root / rehearsal.PARENT_SEAL)
    shutil.copy(REPO / rehearsal.REGISTRATION_PATH, root / rehearsal.REGISTRATION_PATH)
    return root


def run_phase(phase: str, data: Path, batch_size: int | None) -> dict[str, Any]:
    method = _start_measure()
    from value_investor import strategy_book_us_rehearsal as rehearsal
    from value_investor import strategy_book_us_tape as tape

    month_sets = {
        date.fromisoformat(day): set(names)
        for day, names in json.loads((data / "month_sets.json").read_text()).items()
    }
    tape.cap_rank_month_sets = lambda *_args, **_kwargs: month_sets
    build, mid, vendor = data / "hsr-sp500", data / "hsr-midcap", data / "vendor"
    batched = "batch_size" in inspect.signature(rehearsal.develop).parameters
    extra = {"batch_size": batch_size} if batched and batch_size else {}
    repo = data / "repo"
    out: dict[str, Any] = {"phase": phase, "batched": batched, **extra}
    started = time.perf_counter()
    if phase == "load":
        registration = rehearsal.load_registration(_repo(data / "repo-load"))
        dirs = (tape.BuildDir(build, "sp500"), tape.BuildDir(mid, "midcap"), vendor, registration)
        if batched:
            last = registration["windows"]["confirmation"]["last_signal"]
            source = tape.prepare(
                *dirs,
                work_dir=data / "scratch-load",
                batch_size=batch_size or tape.DEFAULT_BATCH_SIZE,
                cross_options=rehearsal.walk_options(registration, last),
            )
            out["names_walked"] = source.names_walked
            out["sessions"] = len(source.calendar)
            source.remove()
        else:
            inputs = tape.build_inputs(*dirs)
            out["names_walked"] = len(inputs.specs)
    elif phase == "develop":
        store = rehearsal.develop(
            build, mid, vendor, repo_root=_repo(repo), scratch=data / "scratch", **extra
        )["store"]
        out["development_mature_primary"] = store["development"]["primary"]["mature"]
        out["run_counts"] = store["run_counts"]
    else:
        store = rehearsal.reveal(
            build, mid, vendor, repo_root=repo, scratch=data / "scratch", **extra
        )["store"]
        out["confirmation_mature_primary"] = store["confirmation"]["primary"]["mature"]
        out["development_reproduced"] = store["confirmation"]["development_reproduced"]
    out["seconds"] = round(time.perf_counter() - started, 1)
    out["peak_rss_mb"] = round(_peak_mb(method))
    out["memory_method"] = method
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, help="Passed to the runner when it batches")
    parser.add_argument("--data-dir", type=Path, help="Reuse or keep generated data here")
    parser.add_argument("--keep", action="store_true", help="Keep the generated data")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--phases", default="load,develop,reveal")
    parser.add_argument("--phase", choices=("load", "develop", "reveal"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.phase:
        print(json.dumps(run_phase(args.phase, args.data_dir, args.batch_size)))
        return 0
    data = args.data_dir or Path(tempfile.mkdtemp(prefix="rehearsal-scale-"))
    data.mkdir(parents=True, exist_ok=True)
    try:
        ready = data / READY
        shape = json.loads(ready.read_text()) if ready.exists() else generate(data, args.seed)
        report: dict[str, Any] = {"shape": shape, "phases": []}
        for phase in args.phases.split(","):
            command = [sys.executable, __file__, "--phase", phase, "--data-dir", str(data)]
            if args.batch_size:
                command += ["--batch-size", str(args.batch_size)]
            done = subprocess.run(command, capture_output=True, text=True)
            if done.returncode:
                report["phases"].append(
                    {"phase": phase, "failed": done.returncode, "stderr": done.stderr[-2000:]}
                )
                break
            report["phases"].append(json.loads(done.stdout.strip().splitlines()[-1]))
        print(json.dumps(report, indent=1))
    finally:
        if not (args.keep or args.data_dir):
            shutil.rmtree(data, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
