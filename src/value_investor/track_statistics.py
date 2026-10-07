"""Statistical power and significance for paper learning tracks (L529).

Observe-only. Turns each track's committed equity curve into period returns,
compares them with the track benchmark, and reports how much of the measured
excess could be noise: tracking error, information ratio, a block-bootstrap
confidence interval on annualised active return, the minimum edge the current
history could detect, and a Bonferroni-corrected significance flag across the
unfrozen tracks plus the primary-minus-control pair (``assessment_model.json``).

Daily ops-monitor refreshes ``docs/data/track_statistics.json`` and warns only
when the published learning-tracks verdict (``beat_market`` / ``beat_control``)
claims a win that the statistics do not support. Never applies knobs itself.
Non-FTSE decision-review reads each track's verdict as its apply gate
(significance_gate_v1). FTSE books apply on the total-return proposal window
versus FTAL.L, so this price series cannot open their gate.
"""

from __future__ import annotations

import json
import logging
import math
import random
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist, fmean, stdev
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
DEFAULT_STORE_PATH = Path("docs/data/track_statistics.json")
LEARNING_TRACKS_REVIEW_FILENAME = "learning_tracks_review.json"
FUND_FILENAME = "automated_fund.json"

FINDING_TITLE = "Learning-track verdict not statistically supported"
STORE_FAILED_TITLE = "Track statistics observe failed"

MIN_PERIODS = 20
CI_LEVEL = 0.90
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_BLOCK = 5
BOOTSTRAP_SEED = 529
FAMILY_ALPHA = 0.05
DETECTION_Z = 2.0
TARGET_EDGE_ANNUAL = 0.03

PRIMARY_VS_CONTROL = "primary_vs_control"

BenchmarkFetcher = Callable[[str, date, date], dict[date, float]]


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


def daily_marks(equity_curve: list[dict[str, Any]]) -> list[tuple[date, float, float]]:
    """Last mark per calendar date as ``(date, nav, contributed_capital)``."""
    by_day: dict[date, tuple[datetime, float, float]] = {}
    for mark in equity_curve or []:
        if not isinstance(mark, dict):
            continue
        at = _parse_dt(mark.get("at"))
        nav = mark.get("portfolio_value")
        if at is None or nav is None:
            continue
        contributed = float(mark.get("contributed_capital") or 0.0)
        day = at.astimezone(UTC).date()
        prior = by_day.get(day)
        if prior is None or at >= prior[0]:
            by_day[day] = (at, float(nav), contributed)
    return [(day, nav, contrib) for day, (_at, nav, contrib) in sorted(by_day.items())]


def period_returns(marks: list[tuple[date, float, float]]) -> list[tuple[date, float]]:
    """Flow-adjusted returns between consecutive daily marks (deposits are not gains)."""
    out: list[tuple[date, float]] = []
    for (_d0, v0, c0), (d1, v1, c1) in zip(marks, marks[1:], strict=False):
        if v0 <= 0:
            continue
        flow = c1 - c0
        out.append((d1, (v1 - flow) / v0 - 1.0))
    return out


def _close_before(closes: list[tuple[date, float]], day: date) -> float | None:
    """Last benchmark close strictly before ``day`` (marks land ~09:30 London)."""
    found: float | None = None
    for close_day, price in closes:
        if close_day >= day:
            break
        found = price
    return found


def benchmark_period_returns(
    mark_days: list[date],
    closes: dict[date, float],
) -> dict[date, float]:
    ordered = sorted((d, float(p)) for d, p in closes.items() if p and p > 0)
    out: dict[date, float] = {}
    for d0, d1 in zip(mark_days, mark_days[1:], strict=False):
        p0 = _close_before(ordered, d0)
        p1 = _close_before(ordered, d1)
        if p0 is None or p1 is None or p0 <= 0:
            continue
        out[d1] = p1 / p0 - 1.0
    return out


def fetch_benchmark_closes(ticker: str, start: date, end: date) -> dict[date, float]:
    """Daily closes from Yahoo (best effort; empty on failure)."""
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(
            start=(start - timedelta(days=7)).isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("Benchmark closes unavailable for %s: %s", ticker, exc)
        return {}
    if hist is None or getattr(hist, "empty", True) or "Close" not in hist.columns:
        return {}
    closes: dict[date, float] = {}
    for idx, value in hist["Close"].dropna().items():
        closes[idx.date()] = float(value)
    return closes


def _block_bootstrap_means(
    values: list[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    block: int = BOOTSTRAP_BLOCK,
    seed: int = BOOTSTRAP_SEED,
) -> list[float]:
    """Circular block bootstrap of the mean.

    Blocks keep short-run autocorrelation; wrapping gives every observation equal
    weight (a plain moving-block bootstrap under-samples the first and last days,
    which skews the interval when an outlier sits at either end).
    """
    n = len(values)
    block = max(1, min(block, n))
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(resamples):
        sample: list[float] = []
        while len(sample) < n:
            s = rng.randrange(n)
            sample.extend(values[(s + k) % n] for k in range(block))
        means.append(fmean(sample[:n]))
    means.sort()
    return means


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def summarize_active_returns(
    rows: list[tuple[date, float]],
    *,
    z_crit: float,
) -> dict[str, Any]:
    """Annualised active-return statistics for a dated return series."""
    n = len(rows)
    if n < MIN_PERIODS:
        return {"status": "insufficient_data", "periods": n, "min_periods": MIN_PERIODS}
    values = [r for _d, r in rows]
    span_days = max(1, (rows[-1][0] - rows[0][0]).days)
    years = span_days / 365.25
    per_year = n / years
    mean = fmean(values)
    sd = stdev(values)
    ann_active = mean * per_year
    tracking_error = sd * math.sqrt(per_year)
    t_stat = mean / (sd / math.sqrt(n)) if sd > 0 else None
    means = _block_bootstrap_means(values)
    tail = (1.0 - CI_LEVEL) / 2.0
    ci_low = _quantile(means, tail) * per_year
    ci_high = _quantile(means, 1.0 - tail) * per_year
    if ci_low > 0:
        verdict = "positive"
    elif ci_high < 0:
        verdict = "negative"
    else:
        verdict = "indistinguishable_from_noise"
    mde = DETECTION_Z * tracking_error / math.sqrt(years) if years > 0 else None
    years_needed = (
        (DETECTION_Z * tracking_error / TARGET_EDGE_ANNUAL) ** 2 if tracking_error > 0 else None
    )
    return {
        "status": "ok",
        "periods": n,
        "first_date": rows[0][0].isoformat(),
        "last_date": rows[-1][0].isoformat(),
        "span_days": span_days,
        "periods_per_year": round(per_year, 1),
        "annualized_active_return": round(ann_active, 4),
        "tracking_error": round(tracking_error, 4),
        "information_ratio": round(ann_active / tracking_error, 3) if tracking_error > 0 else None,
        "t_stat": None if t_stat is None else round(t_stat, 3),
        "ci_level": CI_LEVEL,
        "ci_annualized_active_return": [round(ci_low, 4), round(ci_high, 4)],
        "verdict": verdict,
        "significant_after_correction": bool(t_stat is not None and abs(t_stat) > z_crit),
        "min_detectable_annual_edge": None if mde is None else round(mde, 4),
        "years_to_detect_target_edge": None if years_needed is None else round(years_needed, 2),
    }


def _load_curve(track_dir: Path) -> list[dict[str, Any]]:
    path = Path(track_dir) / FUND_FILENAME
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    curve = payload.get("equity_curve") if isinstance(payload, dict) else None
    return curve if isinstance(curve, list) else []


def build_track_statistics(
    paper_root: Path = DEFAULT_PAPER_ROOT,
    *,
    benchmark_fetcher: BenchmarkFetcher = fetch_benchmark_closes,
    now: datetime | None = None,
) -> dict[str, Any]:
    from value_investor.assessment_model import control_track_id, frozen_tracks, primary_track_id
    from value_investor.decision_review import benchmark_ticker_for_dir
    from value_investor.paper_automation import learning_track_dirs

    root = Path(paper_root)
    bench_ticker = benchmark_ticker_for_dir(root)
    primary = primary_track_id(root)
    control = control_track_id(root)
    frozen = frozen_tracks(root)
    pair_specs = [(PRIMARY_VS_CONTROL, primary, control)]
    track_returns: dict[str, list[tuple[date, float]]] = {}
    track_days: dict[str, list[date]] = {}
    for track_id, track_dir in learning_track_dirs(root).items():
        if track_id in frozen:
            continue
        marks = daily_marks(_load_curve(track_dir))
        if len(marks) < 2:
            continue
        track_returns[track_id] = period_returns(marks)
        track_days[track_id] = [m[0] for m in marks]

    all_days = sorted({d for days in track_days.values() for d in days})
    closes = benchmark_fetcher(bench_ticker, all_days[0], all_days[-1]) if all_days else {}

    eligible = [tid for tid, rows in track_returns.items() if len(rows) >= MIN_PERIODS]
    tests = max(1, len(eligible) + len(pair_specs))
    z_crit = NormalDist().inv_cdf(1.0 - FAMILY_ALPHA / (2.0 * tests))

    tracks: dict[str, Any] = {}
    for track_id, rows in sorted(track_returns.items()):
        bench = benchmark_period_returns(track_days[track_id], closes)
        active = [(d, r - bench[d]) for d, r in rows if d in bench]
        stats = summarize_active_returns(active, z_crit=z_crit)
        stats["vs"] = bench_ticker
        if not bench:
            stats["note"] = "Benchmark closes unavailable — active returns not computed."
        tracks[track_id] = stats

    pairs: dict[str, Any] = {}
    for pair_id, left, right in pair_specs:
        if left not in track_returns or right not in track_returns:
            continue
        right_by_day = dict(track_returns[right])
        diff = [(d, r - right_by_day[d]) for d, r in track_returns[left] if d in right_by_day]
        stats = summarize_active_returns(diff, z_crit=z_crit)
        stats["left"] = left
        stats["right"] = right
        pairs[pair_id] = stats

    return {
        "schema_version": 1,
        "updated_at": (now or datetime.now(UTC)).isoformat(),
        "observe_only": True,
        "benchmark_ticker": bench_ticker,
        "method": {
            "returns": "flow-adjusted daily-mark NAV returns; benchmark close before mark date",
            "ci": (
                f"{int(CI_LEVEL * 100)}% circular block bootstrap (block {BOOTSTRAP_BLOCK}, "
                f"{BOOTSTRAP_RESAMPLES} resamples) on annualised mean active return"
            ),
            "correction": (
                f"Bonferroni across {tests} tests at family alpha {FAMILY_ALPHA} "
                f"(|t| > {z_crit:.2f})"
            ),
            "min_detectable_edge": f"{DETECTION_Z:g} x tracking error / sqrt(years)",
            "target_edge_annual": TARGET_EDGE_ANNUAL,
            "nav_basis": "equity_curve marks (market prices), not decision-review cost-basis NAV",
            "dividends": "not credited in paper NAV (see L528)",
        },
        "primary_track": primary,
        "control_track": control,
        "excluded_frozen_tracks": sorted(frozen),
        "tests_corrected_for": tests,
        "z_critical": round(z_crit, 3),
        "tracks": tracks,
        "pairs": pairs,
    }


def refresh_track_statistics(
    paper_root: Path = DEFAULT_PAPER_ROOT,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    benchmark_fetcher: BenchmarkFetcher = fetch_benchmark_closes,
    persist: bool = True,
) -> dict[str, Any]:
    payload = build_track_statistics(paper_root, benchmark_fetcher=benchmark_fetcher)
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_learning_tracks_review(paper_root: Path) -> dict[str, Any] | None:
    path = Path(paper_root) / LEARNING_TRACKS_REVIEW_FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _describe(label: str, stats: dict[str, Any] | None) -> str:
    stats = stats or {}
    if stats.get("status") != "ok":
        return f"{label}: insufficient data ({stats.get('periods', 0)} periods)"
    low, high = stats.get("ci_annualized_active_return") or [None, None]
    return (
        f"{label}: annualised {stats['annualized_active_return']:+.1%}, "
        f"{int(CI_LEVEL * 100)}% CI [{low:+.1%}, {high:+.1%}], "
        f"min detectable edge {stats['min_detectable_annual_edge']:.1%}/yr"
    )


def ops_finding_from_track_statistics(
    payload: dict[str, Any],
    review: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Warn when beat_market / beat_control is claimed without a positive CI."""
    if not review:
        return None
    from value_investor.assessment_model import LEGACY_CONTROL_TRACK_ID, LEGACY_PRIMARY_TRACK_ID

    primary_id = str(payload.get("primary_track") or LEGACY_PRIMARY_TRACK_ID)
    control_id = str(payload.get("control_track") or LEGACY_CONTROL_TRACK_ID)
    unsupported: list[str] = []
    primary = (payload.get("tracks") or {}).get(primary_id)
    if review.get("beat_market") and (primary or {}).get("verdict") != "positive":
        unsupported.append("beat_market — " + _describe(f"{primary_id} vs benchmark", primary))
    pair = (payload.get("pairs") or {}).get(PRIMARY_VS_CONTROL)
    if review.get("beat_control") and (pair or {}).get("verdict") != "positive":
        unsupported.append("beat_control — " + _describe(f"{primary_id} minus {control_id}", pair))
    if not unsupported:
        return None
    return {
        "severity": "warn",
        "category": "paper",
        "title": FINDING_TITLE,
        "summary": (
            "learning_tracks_review claims "
            + "; ".join(unsupported)
            + ". The confidence interval does not show a positive edge, so do not cite "
            "this as outperformance or promote knobs/tracks on it. "
            "See docs/ops/track-statistics.md."
        ),
        "auto_fixable": False,
    }
