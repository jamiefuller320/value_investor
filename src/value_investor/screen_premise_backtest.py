"""Frozen-signal backtest of the value screen itself (L530, first version).

Learning question: do the screen's buy-tier names (``buy`` + ``strong_buy``)
out-earn the rest of the screened FTSE universe over the following weeks?

Uses only the weekly run snapshots in ``docs/data/history/`` (signals and prices
frozen at run time, so point-in-time by construction). Cross-sectional: every
weekly cohort compares ~60 buy-tier names with ~250 screened names, which is far
more evidence per week than a 3-name paper book.

Per horizon and cohort (runs at least 6 days apart, each with an exit run at or
after the horizon):

- ``buy_tier_spread``: equal-weight buy-tier forward return minus the
  equal-weight screened-universe return;
- ``avoid_spread``: same for ``avoid`` names (should be negative if the screen works);
- ``rank_ic``: Spearman correlation of ``conviction_score`` with forward return.

Cohort means get a 90% interval using an effective sample size that discounts
overlapping windows (cohorts × 7 / horizon); intervals and ``weeks_to_detect``
(weekly cohorts a 3%/yr buy-tier edge needs before the interval excludes zero)
are only published once that effective sample reaches ``MIN_EFFECTIVE_N``.

This is a weeks-long base rate, not the multi-year PIT test L530 asks for; that
needs dated fundamentals (L11). Daily ops-monitor refreshes
``docs/data/screen_premise_backtest.json``. Never changes signals or books.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from value_investor.backtest import RunSnapshot, _find_exit_snapshot, load_run_snapshots

DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/screen_premise_backtest.json")

HORIZON_DAYS = (7, 28)
BUY_TIER = frozenset({"buy", "strong_buy"})
MAX_ABS_RETURN = 0.5
MIN_COHORT_NAMES = 5
MIN_COHORT_GAP_DAYS = 6
MIN_EFFECTIVE_N = 4.0
Z90 = 1.645
TARGET_ANNUAL_EDGE = 0.03

LEARNING_QUESTION = (
    "Do the screen's buy-tier names out-earn the rest of the screened FTSE universe "
    "over the following weeks?"
)
FINDING_TITLE = "Value screen buy tier trails screened universe"
STORE_FAILED_TITLE = "Screen premise backtest observe failed"


def weekly_cohorts(snapshots: list[RunSnapshot]) -> list[RunSnapshot]:
    """Earliest runs spaced at least ``MIN_COHORT_GAP_DAYS`` apart (no same-week duplicates)."""
    out: list[RunSnapshot] = []
    for snap in sorted(snapshots, key=lambda s: s.run_at):
        at = _run_dt(snap)
        if out and (at - _run_dt(out[-1])).total_seconds() < MIN_COHORT_GAP_DAYS * 86400:
            continue
        out.append(snap)
    return out


def _run_dt(snap: RunSnapshot) -> datetime:
    parsed = datetime.fromisoformat(snap.run_at.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = mean(rx), mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def score_cohort(entry: RunSnapshot, exit_snap: RunSnapshot) -> dict[str, Any] | None:
    rows: list[tuple[str, float, float]] = []
    dropped = 0
    for row in entry.signals:
        ticker = str(row.get("ticker") or "")
        p0 = entry.prices.get(ticker)
        p1 = exit_snap.prices.get(ticker)
        if not p0 or not p1 or p0 <= 0:
            continue
        ret = p1 / p0 - 1.0
        if abs(ret) > MAX_ABS_RETURN:
            dropped += 1
            continue
        rows.append((str(row.get("signal") or ""), float(row.get("conviction_score") or 0.0), ret))
    buy = [r for s, _, r in rows if s in BUY_TIER]
    avoid = [r for s, _, r in rows if s == "avoid"]
    if len(rows) < MIN_COHORT_NAMES or len(buy) < MIN_COHORT_NAMES:
        return None
    universe = mean(r for _, _, r in rows)
    return {
        "entry": entry.run_at,
        "exit": exit_snap.run_at,
        "names": len(rows),
        "buy_tier_names": len(buy),
        "universe_return": round(universe, 4),
        "buy_tier_spread": round(mean(buy) - universe, 4),
        "avoid_spread": round(mean(avoid) - universe, 4) if avoid else None,
        "rank_ic": _round(spearman([c for _, c, _ in rows], [r for _, _, r in rows])),
        "dropped_unit_flips": dropped,
    }


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def summarise(values: list[float], horizon_days: int) -> dict[str, Any]:
    n = len(values)
    if n == 0:
        return {"cohorts": 0}
    avg = mean(values)
    sd = stdev(values) if n > 1 else None
    eff_n = max(1.0, n * 7.0 / horizon_days)
    half = Z90 * sd / math.sqrt(eff_n) if sd is not None and eff_n >= MIN_EFFECTIVE_N else None
    return {
        "cohorts": n,
        "effective_n": round(eff_n, 1),
        "mean": round(avg, 4),
        "stdev": _round(sd),
        "ci90_low": _round(avg - half) if half is not None else None,
        "ci90_high": _round(avg + half) if half is not None else None,
    }


def weeks_to_detect(stdev_per_cohort: float | None, horizon_days: int) -> float | None:
    """Weekly cohorts needed for a 3%/yr edge's 90% interval to exclude zero."""
    if not stdev_per_cohort:
        return None
    target = TARGET_ANNUAL_EDGE * horizon_days / 365.0
    eff_needed = (Z90 * stdev_per_cohort / target) ** 2
    return round(eff_needed * horizon_days / 7.0, 0)


def build_screen_premise_backtest(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, Any]:
    snapshots = load_run_snapshots(Path(data_dir))
    cohorts = weekly_cohorts(snapshots)
    horizons: dict[str, Any] = {}
    for horizon in HORIZON_DAYS:
        rows = []
        for entry in cohorts:
            exit_snap = _find_exit_snapshot(entry, snapshots, horizon)
            if exit_snap is None:
                continue
            scored = score_cohort(entry, exit_snap)
            if scored is not None:
                rows.append(scored)
        spread = summarise([r["buy_tier_spread"] for r in rows], horizon)
        horizons[str(horizon)] = {
            "horizon_days": horizon,
            "buy_tier_spread": spread,
            "avoid_spread": summarise(
                [r["avoid_spread"] for r in rows if r["avoid_spread"] is not None], horizon
            ),
            "rank_ic": summarise([r["rank_ic"] for r in rows if r["rank_ic"] is not None], horizon),
            "weeks_to_detect_3pct_annual": (
                weeks_to_detect(spread.get("stdev"), horizon)
                if spread.get("ci90_low") is not None
                else None
            ),
            "cohorts": rows,
        }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "learning_question": LEARNING_QUESTION,
        "snapshots": len(snapshots),
        "weekly_cohorts": len(cohorts),
        "first_run": snapshots[0].run_at if snapshots else None,
        "last_run": snapshots[-1].run_at if snapshots else None,
        "horizons": horizons,
        "limitations": (
            "Weeks of frozen FTSE snapshots, price return only (no dividends), FTSE 350 "
            "names that were screened at the time. Not the multi-year PIT test: that "
            "needs dated fundamentals and delisted names (L11)."
        ),
    }


def refresh_screen_premise_backtest(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    persist: bool = True,
) -> dict[str, Any]:
    payload = build_screen_premise_backtest(data_dir)
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_finding_from_screen_premise_backtest(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Warn when the buy-tier spread's 90% interval lies wholly below zero."""
    lines: list[str] = []
    for horizon in (payload.get("horizons") or {}).values():
        spread = horizon.get("buy_tier_spread") or {}
        high = spread.get("ci90_high")
        if high is None or high >= 0:
            continue
        lines.append(
            f"{horizon['horizon_days']}d: mean {spread['mean']:+.2%} per cohort "
            f"(90% CI {spread['ci90_low']:+.2%} to {high:+.2%}, {spread['cohorts']} cohorts)"
        )
    if not lines:
        return None
    return {
        "severity": "warn",
        "category": "backtest",
        "title": FINDING_TITLE,
        "summary": (
            "Frozen-signal backtest: buy/strong_buy names trail the equal-weight screened "
            "universe with a 90% interval below zero — "
            + "; ".join(lines)
            + ". Observe-only: question the screen before tuning overlays. "
            "See docs/ops/screen-premise-backtest.md."
        ),
        "auto_fixable": False,
    }
