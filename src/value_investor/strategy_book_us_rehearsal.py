"""Strategy-book US point-in-time rehearsal runner (plan step 2.5).

Registration ``strategy-book-us-rehearsal-v0``
(``docs/ops/strategy-book-us-rehearsal-registration.md``). Observe-only: no
language model, no network, no live store. The walk is
``strategy_book_observe.walk_book`` in mode ``us_rehearsal``; this module only
feeds it licensed inputs (``strategy_book_us_tape``) and turns its episodes
into the aggregate blocks of ``docs/data/strategy_book_us_rehearsal.json``.

Order: ``develop`` (development signal sessions only), owner review, one
``reveal``, deletion, ``confirm-deleted``. Per-episode files go to a scratch
directory outside the repository. Every write of the committed store passes
``assert_private`` first.
"""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import json
import math
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from value_investor import historical_screen_replay as hsr
from value_investor import strategy_book_observe as sbo
from value_investor.strategy_book_rules import (
    COLUMN_ALTERNATIVE,
    COLUMN_BUY_ON_SIGNAL,
    COLUMN_DECLINE_SHADOW,
    COLUMN_DRAFT,
    COLUMN_LADDER,
    COLUMN_LEAVE_TIER,
    COLUMN_PRIMARY,
    COLUMN_SECTOR_SHADOW,
    REGISTRATION_STORE_NAME,
    SLOT_BOOK_RANDOM_SEED,
    RegistrationUnsigned,
    registration_signed,
)
from value_investor.strategy_book_us_tape import (
    DEFAULT_BATCH_SIZE,
    SP400,
    SP500,
    BuildDir,
    InputsMissing,
    RehearsalInputs,
    RehearsalSource,
    prepare,
    with_variant,
)

REPO_ROOT = hsr.REPO_ROOT
REGISTRATION_PATH = Path("docs/data/strategy_book_us_rehearsal_registration.json")
STORE_PATH = Path("docs/data/strategy_book_us_rehearsal.json")
PARENT_SEAL = Path("docs/data") / REGISTRATION_STORE_NAME
SCRATCH_DIRNAME = "strategy_book_rehearsal"
DELETION_DAYS = 30
BOOTSTRAP_SEED = 20261104
BASELINE = "baseline"
SENSITIVITY = "sensitivity"
BENCH_TESTS = ("deep_dip", "revenue_growing")
PAIRED_EXITS = (COLUMN_DRAFT, COLUMN_LADDER)
UNPAIRED = (
    COLUMN_DECLINE_SHADOW,
    COLUMN_SECTOR_SHADOW,
    COLUMN_BUY_ON_SIGNAL,
    COLUMN_LEAVE_TIER,
    COLUMN_ALTERNATIVE,
)
SELECTION_FEATURES = sbo.NUMERIC_SNAPSHOT_FEATURES + sbo.CHANNEL_NUMERIC_FEATURES

TITLE_DEVELOPMENT = "Strategy-book US rehearsal: development block committed"
TITLE_REVEALED = "Strategy-book US rehearsal: confirmation revealed"
TITLE_DELETION_DUE = "Strategy-book US rehearsal: licensed data deletion due"
TITLE_FAILED = "Strategy-book US rehearsal store unreadable"


class RehearsalRefused(RuntimeError):
    """A precondition of the registration is not met. Nothing was written."""


class PrivacyViolation(RuntimeError):
    """The store would publish a per-name value, a small cell, a path, or a key."""


# --- Privacy guard -------------------------------------------------------------------------

_IDENTITY_KEYS = frozenset(
    {
        "ticker",
        "tickers",
        "name",
        "names",
        "company",
        "episode_id",
        "episode_ids",
        "members",
        "positions",
        "taken_ids",
        "skipped_ids",
        "api_key",
        "apikey",
        "path",
        "paths",
        "panel_row",
        "cache_row",
        "rows",
        "per_week",
        "by_week",
        "week_returns",
    }
)
# Forbidden when they carry a number or a list of scalars: a price, a
# fundamental, or one episode's return.
_VALUE_KEYS = frozenset(
    {
        "price",
        "prices",
        "close",
        "closes",
        "entry",
        "exit",
        "entry_fill",
        "exit_fill",
        "return_entry_fill",
        "entry_fill_first_seen",
        "fair_cost_return",
        "gross_return",
        "matched_excess",
        "capital_return",
        "stress_return",
        "returns",
        "revenue",
        "eps",
        "epsdil",
        "fcf",
        "ebit",
        "opinc",
        "marketcap",
        "market_cap",
        "free_cashflow",
        "enterprise_value",
        "profit_margins",
        "debt_to_equity",
        "revenue_growth",
        "earnings_growth",
        "earnings_yield",
        "conviction_score",
        "composite_score",
        "episodes",
    }
)
_COUNT_KEYS = frozenset(
    {
        "count",
        "n",
        "mature",
        "mature_episodes",
        "episodes",
        "kept",
        "counted_mature",
        "trades_taken",
    }
)
_SECRET_ENV = re.compile(r"SHARADAR|NASDAQ|QUANDL|API_KEY", re.IGNORECASE)
_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9.]+")
_HOME_PATH = re.compile(r"(^|[\s'\"=(])(([a-z]:)?|/[a-z])/(users|home)/")


def _scalar(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _small(node: Mapping[str, Any], minimum: int) -> bool:
    return any(
        key in _COUNT_KEYS and _scalar(value) and value < minimum for key, value in node.items()
    )


def _secrets() -> list[str]:
    return [
        value
        for key, value in os.environ.items()
        if _SECRET_ENV.search(key) and isinstance(value, str) and len(value) >= 8
    ]


def privacy_violations(
    payload: Any,
    tickers: Iterable[str] = (),
    *,
    minimum: int = 5,
    home: str | None = None,
    secrets: Iterable[str] | None = None,
) -> list[str]:
    """Every reason ``payload`` may not be committed (empty when it may)."""
    names = {str(t) for t in tickers if str(t) and not str(t).isdigit()}
    home_text = (
        (home if home is not None else str(Path.home())).replace("\\", "/").rstrip("/").lower()
    )
    keys = [s for s in (secrets if secrets is not None else _secrets()) if s]
    found: list[str] = []

    def _text(text: str, where: str) -> None:
        lowered = text.lower()
        slashed = lowered.replace("\\", "/")
        if "sharadar" in lowered:
            found.append(f"{where}: mentions the vendor directory")
        if (home_text and home_text not in ("", "/") and home_text in slashed) or "~/" in slashed:
            found.append(f"{where}: contains a home-directory path")
        # POSIX homes, Windows drive paths (C:/Users), and MSYS/Git Bash drive paths (/c/Users).
        if _HOME_PATH.search(slashed):
            found.append(f"{where}: contains a home-directory path")
        for secret in keys:
            if secret in text:
                found.append(f"{where}: contains an API key")
        for token in _TOKEN_SPLIT.split(text):
            token = token.strip(".")
            if token and token in names:
                found.append(f"{where}: contains a universe ticker")
                break

    def _walk(node: Any, where: str) -> None:
        if isinstance(node, Mapping):
            if _small(node, minimum):
                for key, value in node.items():
                    if key in _COUNT_KEYS:
                        continue
                    if isinstance(value, float) and value is not None:
                        found.append(f"{where}.{key}: return statistic on a cell under {minimum}")
                    if isinstance(value, Mapping) and (
                        value.get("low") is not None or value.get("high") is not None
                    ):
                        found.append(f"{where}.{key}: interval on a cell under {minimum}")
            for key, value in node.items():
                key_text = str(key)
                here = f"{where}.{key_text}"
                _text(key_text, here)
                lowered = key_text.lower()
                if lowered in _IDENTITY_KEYS:
                    found.append(f"{here}: forbidden key")
                if lowered.startswith((hsr.MODEL_PASS_PREFIX, hsr.MODEL_SCORE_PREFIX)):
                    found.append(f"{here}: signal-cache column")
                if lowered in _VALUE_KEYS and (
                    _scalar(value)
                    or (isinstance(value, list) and any(not isinstance(v, Mapping) for v in value))
                ):
                    if not (lowered == "episodes" and isinstance(value, int)):
                        found.append(f"{here}: per-name or per-episode value")
                _walk(value, here)
        elif isinstance(node, list | tuple):
            for index, value in enumerate(node):
                _walk(value, f"{where}[{index}]")
        elif isinstance(node, str):
            _text(node, where)

    _walk(payload, "$")
    return found


def assert_private(payload: Any, tickers: Iterable[str] = (), **kwargs: Any) -> None:
    problems = privacy_violations(payload, tickers, **kwargs)
    if problems:
        raise PrivacyViolation("; ".join(sorted(set(problems))[:20]))


def suppress_small(node: Any, minimum: int = 5) -> Any:
    """Keep the counts of a cell under ``minimum`` and drop its return statistics."""
    if isinstance(node, Mapping):
        small = _small(node, minimum)
        out: dict[str, Any] = {}
        for key, value in node.items():
            if small and key not in _COUNT_KEYS and isinstance(value, float):
                out[key] = None
            elif small and isinstance(value, Mapping) and ("low" in value or "high" in value):
                out[key] = {**suppress_small(value, minimum), "low": None, "high": None}
            else:
                out[key] = suppress_small(value, minimum)
        return out
    if isinstance(node, list):
        return [suppress_small(value, minimum) for value in node]
    return node


# --- Paths and preconditions ---------------------------------------------------------------


def _inside(path: Path, root: Path) -> bool:
    return Path(path).expanduser().resolve().is_relative_to(Path(root).resolve())


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def load_registration(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    payload = _load_json(Path(repo_root) / REGISTRATION_PATH)
    if payload is None:
        raise RehearsalRefused(f"{REGISTRATION_PATH} is missing; the rehearsal is not registered.")
    return payload


def preflight(repo_root: Path, *paths: Path | None) -> dict[str, Any]:
    """Refuse an unsigned parent, a missing registration, or a licensed path inside the repo."""
    if not registration_signed(Path(repo_root) / PARENT_SEAL):
        raise RegistrationUnsigned(
            "The parent strategy book registration (owner-strategy-book-v0) is not signed."
        )
    registration = load_registration(repo_root)
    for path in paths:
        if path is not None and _inside(path, repo_root):
            raise RehearsalRefused(
                f"{path} is inside the repository. Licensed and derived files stay outside "
                "this public repo."
            )
    return registration


# --- Statistics ----------------------------------------------------------------------------


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _mean(values: list[float]) -> float | None:
    return float(statistics.fmean(values)) if values else None


def signal_week(episode: Mapping[str, Any]) -> str:
    return sbo.entry_week(date.fromisoformat(str(episode["signal_session"])[:10]))


def _weeks(rows: list[Mapping[str, Any]]) -> tuple[np.ndarray, int]:
    labels = [signal_week(row) for row in rows]
    order = {label: index for index, label in enumerate(sorted(set(labels)))}
    return np.array([order[label] for label in labels], dtype=np.int64), len(order)


def _week_draws(weeks: int, resamples: int, rng: np.random.Generator, chunk: int):
    """Week multiplicities for ``resamples`` whole-week bootstrap draws, in chunks."""
    done = 0
    while done < resamples:
        size = min(chunk, resamples - done)
        draws = rng.integers(0, weeks, size=(size, weeks))
        flat = (draws + np.arange(size)[:, None] * weeks).ravel()
        yield np.bincount(flat, minlength=size * weeks).reshape(size, weeks)
        done += size


def bootstrap_median(
    values: list[float], week_ids: np.ndarray, weeks: int, *, resamples: int, seed: int
) -> np.ndarray:
    """Median of each resample of whole signal weeks (with replacement)."""
    order = np.argsort(np.asarray(values, dtype=float), kind="stable")
    sorted_values = np.asarray(values, dtype=float)[order]
    week_of = week_ids[order]
    rng = np.random.default_rng(seed)
    chunk = max(1, 4_000_000 // max(len(values), 1))
    out: list[np.ndarray] = []
    for counts in _week_draws(weeks, resamples, rng, chunk):
        cumulative = np.cumsum(counts[:, week_of], axis=1)
        total = cumulative[:, -1]
        low = np.sum(cumulative <= ((total - 1) // 2)[:, None], axis=1)
        high = np.sum(cumulative <= (total // 2)[:, None], axis=1)
        out.append((sorted_values[low] + sorted_values[high]) / 2.0)
    return np.concatenate(out) if out else np.array([])


def bootstrap_mean_difference(
    values: list[float],
    kept: list[bool],
    week_ids: np.ndarray,
    weeks: int,
    *,
    resamples: int,
    seed: int,
) -> np.ndarray:
    """Mean of the kept rows minus the mean of all rows, per whole-week resample."""
    values_np = np.asarray(values, dtype=float)
    kept_np = np.asarray(kept, dtype=bool)
    sum_all = np.bincount(week_ids, weights=values_np, minlength=weeks)
    n_all = np.bincount(week_ids, minlength=weeks).astype(float)
    sum_kept = np.bincount(week_ids, weights=np.where(kept_np, values_np, 0.0), minlength=weeks)
    n_kept = np.bincount(week_ids, weights=kept_np.astype(float), minlength=weeks)
    rng = np.random.default_rng(seed)
    out: list[np.ndarray] = []
    for counts in _week_draws(weeks, resamples, rng, max(1, 4_000_000 // max(weeks, 1))):
        with np.errstate(divide="ignore", invalid="ignore"):
            kept_mean = (counts @ sum_kept) / (counts @ n_kept)
            all_mean = (counts @ sum_all) / (counts @ n_all)
        out.append(kept_mean - all_mean)
    return np.concatenate(out) if out else np.array([])


def interval(samples: np.ndarray, coverage: float) -> dict[str, Any]:
    finite = samples[np.isfinite(samples)] if samples.size else samples
    if finite.size == 0:
        return {"coverage": coverage, "low": None, "high": None}
    tail = (1.0 - coverage) / 2.0
    low, high = np.percentile(finite, [100.0 * tail, 100.0 * (1.0 - tail)])
    return {"coverage": coverage, "low": float(low), "high": float(high)}


def family(registration: Mapping[str, Any]) -> dict[str, Any]:
    block = registration.get("confirmation_family") or {}
    alpha = float(block.get("alpha", 0.10))
    size = int(block.get("family_size", 3))
    return {
        "m": size,
        "alpha": alpha,
        "coverage": 1.0 - alpha / size,
        "development_coverage": 1.0 - alpha,
        "tests": [test.get("name") for test in block.get("tests") or []]
        or ["primary", *BENCH_TESTS],
        "resamples": int(block.get("resamples", 10_000)),
        "resample_unit": block.get("resample_unit", "iso_entry_week_of_signal_session"),
        "seed": BOOTSTRAP_SEED,
    }


def primary_verdict(fair_median: float | None, excess: Mapping[str, Any], mature: int) -> str:
    """Section 6. ``insufficient_episodes`` when the cell is under the publication floor."""
    low, high = excess.get("low"), excess.get("high")
    if mature < 5 or fair_median is None or low is None or high is None:
        return "insufficient_episodes"
    if high < 0:
        return "fail_excess"
    if fair_median <= 0:
        return "fail_costs"
    if low > 0:
        return "pass"
    return "inconclusive"


def candidate_verdict(block: Mapping[str, Any], halves: list[float | None]) -> str:
    low, high = (block.get("interval") or {}).get("low"), (block.get("interval") or {}).get("high")
    if low is None or high is None:
        return "insufficient_episodes"
    if high < 0:
        return "fail"
    if low > 0 and all(value is not None and value > 0 for value in halves):
        return "pass"
    return "inconclusive"


# --- Blocks --------------------------------------------------------------------------------


def _between(episode: Mapping[str, Any], first: str, last: str) -> bool:
    return first <= str(episode.get("signal_session"))[:10] <= last


def _floor(episode: Mapping[str, Any]) -> float | None:
    return sbo._finite(episode.get("decision_return_floor"))


def _excess(episode: Mapping[str, Any]) -> float | None:
    return sbo._finite(episode.get("matched_excess"))


def _mature(rows: list[dict[str, Any]], column: str = COLUMN_PRIMARY) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("column") == column and row.get("mature")]


def _mini(rows: list[dict[str, Any]]) -> dict[str, Any]:
    launched = [row for row in rows if row.get("launched")]
    return {
        "mature": len(rows),
        "fair_cost_median": _median([v for v in map(_floor, rows) if v is not None]),
        "matched_excess_median": _median([v for v in map(_excess, rows) if v is not None]),
        "launch_share": None if not rows else len(launched) / len(rows),
    }


def _week_error(rows: list[dict[str, Any]], value_of) -> float | None:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = value_of(row)
        if value is not None:
            grouped[signal_week(row)].append(value)
    return sbo.entry_week_standard_error(grouped)


def _primary_block(
    rows: list[dict[str, Any]], coverage: float, fam: Mapping[str, Any]
) -> dict[str, Any]:
    fair_rows = [row for row in rows if _floor(row) is not None]
    excess_rows = [row for row in rows if _excess(row) is not None]
    fair = [_floor(row) for row in fair_rows]
    excess = [_excess(row) for row in excess_rows]
    excess_interval = {"coverage": coverage, "low": None, "high": None}
    fair_interval = {"coverage": coverage, "low": None, "high": None}
    if len(excess_rows) >= 5:
        weeks, count = _weeks(excess_rows)
        excess_interval = interval(
            bootstrap_median(excess, weeks, count, resamples=fam["resamples"], seed=fam["seed"]),
            coverage,
        )
    if len(fair_rows) >= 5:
        weeks, count = _weeks(fair_rows)
        fair_interval = interval(
            bootstrap_median(fair, weeks, count, resamples=fam["resamples"], seed=fam["seed"] + 1),
            coverage,
        )
    return {
        "mature": len(rows),
        "entry_weeks": len({signal_week(row) for row in rows}),
        "fair_cost_median": _median(fair),
        "fair_cost_mean": _mean(fair),
        "matched_excess_median": _median(excess),
        "matched_excess_mean": _mean(excess),
        "entry_week_standard_error": _week_error(excess_rows, _excess),
        "share_above_zero": None if not excess else sum(v > 0 for v in excess) / len(excess),
        "interval": excess_interval,
        "companion": {
            "statistic": "fair_cost_median",
            "label": "descriptive_not_a_test",
            "mature": len(fair_rows),
            "interval": fair_interval,
        },
    }


def _bench_block(
    rows: list[dict[str, Any]],
    column: str,
    coverage: float,
    fam: Mapping[str, Any],
    seed: int,
    halves: tuple[tuple[str, str], tuple[str, str]] | None,
) -> dict[str, Any]:
    scored = [row for row in rows if _floor(row) is not None]
    kept = [bool((row.get("bench") or {}).get(column)) for row in scored]
    values = [_floor(row) for row in scored]
    kept_values = [v for v, keep in zip(values, kept, strict=True) if keep]
    difference = None
    if kept_values and values:
        difference = statistics.fmean(kept_values) - statistics.fmean(values)
    block: dict[str, Any] = {
        "kept": sum(kept),
        "mature": len(scored),
        "kept_share": None if not scored else sum(kept) / len(scored),
        "mean_difference": difference,
        "interval": {"coverage": coverage, "low": None, "high": None},
    }
    if sum(kept) >= 5 and len(scored) >= 5:
        weeks, count = _weeks(scored)
        block["interval"] = interval(
            bootstrap_mean_difference(
                values, kept, weeks, count, resamples=fam["resamples"], seed=seed
            ),
            coverage,
        )
    if halves is not None:
        signs = []
        for first, last in halves:
            part = [row for row in scored if _between(row, first, last)]
            part_kept = [_floor(row) for row in part if (row.get("bench") or {}).get(column)]
            part_all = [_floor(row) for row in part]
            signs.append(
                None
                if len(part_kept) < 5 or not part_all
                else statistics.fmean(part_kept) - statistics.fmean(part_all)
            )
        block["halves"] = [
            {"window": f"{first}/{last}", "kept": None, "sign": _sign(value)}
            for (first, last), value in zip(halves, signs, strict=True)
        ]
        for entry, (first, last) in zip(block["halves"], halves, strict=True):
            entry["kept"] = sum(
                1
                for row in scored
                if _between(row, first, last) and (row.get("bench") or {}).get(column)
            )
        block["verdict"] = candidate_verdict(block, signs)
    else:
        block["verdict"] = None
    return block


def _sign(value: float | None) -> str | None:
    if value is None:
        return None
    return "positive" if value > 0 else "negative" if value < 0 else "zero"


def _unpaired(
    window_rows: list[dict[str, Any]], primary: list[dict[str, Any]], column: str
) -> dict[str, Any]:
    rows = _mature(window_rows, column)
    values = [v for v in map(_floor, rows) if v is not None]
    base = [v for v in map(_floor, primary) if v is not None]
    left = _week_error(rows, _floor)
    right = _week_error(primary, _floor)
    error = None if left is None or right is None else math.sqrt(left**2 + right**2)
    difference = (
        None if not values or not base else statistics.fmean(values) - statistics.fmean(base)
    )
    return {
        "column": column,
        "count": len(rows),
        "entry_weeks": len({signal_week(row) for row in rows}),
        "mean_difference_vs_primary": difference,
        "standard_error": error,
        "pairing": "unpaired",
    }


def _paired(window_rows: list[dict[str, Any]], column: str) -> dict[str, Any]:
    board = sbo._paired_board(window_rows, column)
    return {
        "column": column,
        "n": board["n"],
        "entry_weeks": board["entry_weeks"],
        "mean_difference": board["mean_difference"],
        "median_difference": board["median_difference"],
        "standard_error": board["standard_error"],
        "share_primary_better": board["share_primary_better"],
        "pairing": "same_entries",
    }


def _selection(primary: list[dict[str, Any]], *, rank: bool) -> dict[str, Any]:
    features: dict[str, Any] = {}
    gaps: list[tuple[float, str]] = []
    for feature in SELECTION_FEATURES:
        present = sum(1 for row in primary if sbo._feature_number(row, feature) is not None)
        fifths = [
            {
                "fifth": cell["fifth"],
                "count": cell["count"],
                "median_fair_cost": cell["median_fair_cost"],
            }
            for cell in sbo._fifths(primary, feature)
        ]
        features[feature] = {"present": present, "fifths": fifths}
        top, bottom = fifths[-1], fifths[0]
        if (
            top["count"] >= 5
            and bottom["count"] >= 5
            and top["median_fair_cost"] is not None
            and bottom["median_fair_cost"] is not None
        ):
            gaps.append((top["median_fair_cost"] - bottom["median_fair_cost"], feature))
    out: dict[str, Any] = {"features": features}
    if rank:
        ordered = sorted(gaps, key=lambda item: (-item[0], item[1]))
        out["rank"] = [
            {"rank": index, "feature": feature, "top_minus_bottom": gap}
            for index, (gap, feature) in enumerate(ordered, start=1)
        ]
    return out


def _split(primary: list[dict[str, Any]], value_of) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in primary:
        groups[str(value_of(row))].append(row)
    return {key: _mini(rows) for key, rows in sorted(groups.items())}


def _slices(window_rows: list[dict[str, Any]], scoring: date) -> dict[str, Any]:
    boards = sbo.build_boards(window_rows, events=[], scoring_date=scoring, names=None)
    floor = boards["floor_exits"]
    slot = boards["capital_view"]["slot_book"]
    return {
        "launch": boards["launch"],
        "floor_exits": {
            "count": floor["count"],
            "median_fair_cost": floor["median_fair_cost"],
            "checkpoints": floor["checkpoints"],
        },
        "fail_to_launch": boards["fail_to_launch"],
        "thesis_breaks": boards["thesis_breaks"],
        "review_and_time_cap": boards["review_and_time_cap"],
        "recovery_label": boards["recovery_label"],
        "stress": boards["stress"],
        "single_market_dependence": boards["single_market_dependence"],
        "capital": {
            "episodes": sum(1 for row in window_rows if row.get("column") == COLUMN_PRIMARY),
            "capital_days_return": boards["capital_view"]["capital_days_return"],
            "recovery_hold_capital_share": boards["capital_view"]["recovery_hold_capital_share"],
            "slot_book": {
                "trades_taken": slot.get("trades_taken"),
                "trades_skipped": slot.get("trades_skipped"),
                "annualised_return": slot.get("annualised_return"),
                "max_drawdown": slot.get("max_drawdown"),
                "random_order_median": slot.get("random_order_median"),
                "random_orders": slot.get("random_orders"),
                "seed": SLOT_BOOK_RANDOM_SEED,
            },
        },
    }


def window_block(
    episodes: list[dict[str, Any]],
    events: list[dict[str, Any]],
    window: tuple[str, str],
    *,
    coverage: float,
    fam: Mapping[str, Any],
    scoring: date,
    delisted: set[str],
    halves: tuple[tuple[str, str], tuple[str, str]] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Aggregates for the episodes whose signal session falls in ``window``."""
    first, last = window
    rows = [row for row in episodes if _between(row, first, last)]
    primary_all = [row for row in rows if row.get("column") == COLUMN_PRIMARY]
    primary = _mature(rows)
    fair = [v for v in map(_floor, primary) if v is not None]
    before_fill = sum(
        1
        for event in events
        if event.get("kind") == "no_next_bar"
        and event.get("column") == COLUMN_PRIMARY
        and event.get("ticker") in delisted
        and first <= str(event.get("session"))[:10] <= last
    )
    block: dict[str, Any] = {
        "signal_window": {"first": first, "last": last},
        "interval_label": label,
        "counts": {
            "episodes": len(primary_all),
            "mature_episodes": len(primary),
            "entry_weeks": len({signal_week(row) for row in primary}),
            "by_market": dict(Counter(str(row.get("market")) for row in primary_all)),
            "by_exit_reason": dict(
                Counter(str(row.get("exit_reason") or "open") for row in primary_all)
            ),
            "shadows": {
                c: len(_mature(rows, c)) for c in (COLUMN_DECLINE_SHADOW, COLUMN_SECTOR_SHADOW)
            },
            "controls": {
                c: len(_mature(rows, c)) for c in (COLUMN_BUY_ON_SIGNAL, COLUMN_LEAVE_TIER)
            },
            "alternative": len(_mature(rows, COLUMN_ALTERNATIVE)),
            "hl_basis": dict(
                Counter(str((row.get("channels") or {}).get("hl_basis")) for row in primary_all)
            ),
            "sector_basis": dict(Counter(str(row.get("sector_basis")) for row in primary_all)),
            "basket_fallback": sum(
                1 for row in primary if (row.get("basket") or {}).get("fallback")
            ),
            "f9_unverified": sum(
                1 for row in primary_all if row.get("f9_status") == "f9_unverified"
            ),
            "research_absent": sum(
                1 for row in primary_all if not (row.get("snapshot") or {}).get("research_verdict")
            ),
            "delisted": sum(
                1 for row in primary_all if row.get("exit_reason") == sbo.EXIT_DELISTED
            ),
            "delisted_before_fill": before_fill,
        },
        "primary": _primary_block(primary, coverage, fam),
        "by_market": {
            market: _mini([row for row in primary if row.get("market") == market])
            for market in (SP500, SP400)
        },
        "paired_exits": {column: _paired(rows, column) for column in PAIRED_EXITS},
        "unpaired_columns": {column: _unpaired(rows, primary, column) for column in UNPAIRED},
        "bench": {
            column: _bench_block(primary, column, coverage, fam, fam["seed"] + 10 + index, halves)
            for index, column in enumerate(BENCH_TESTS)
        },
        "selection": _selection(primary, rank=halves is None),
        "channels": {
            "by_band_bucket": _split(
                primary, lambda r: (r.get("channels") or {}).get("ch126_bucket")
            ),
            "by_direction": _split(
                primary, lambda r: (r.get("channels") or {}).get("ch126_direction")
            ),
        },
        "regime": {
            key: _mini([row for row in primary if row.get("regime") == key])
            for key in ("above", "below", "regime_unknown")
        },
        "tails": {
            "count": len(fair),
            "p5_fair_cost": float(np.percentile(fair, 5)) if fair else None,
        },
        **_slices(rows, scoring),
    }
    block["flags"] = {"single_market_dependence": block.pop("single_market_dependence")}
    return suppress_small(block)


def sensitivity_block(
    episodes: list[dict[str, Any]], window: tuple[str, str], coverage: float, fam: Mapping[str, Any]
) -> dict[str, Any]:
    rows = [row for row in _mature(episodes) if _between(row, *window)]
    primary = _primary_block(rows, coverage, fam)
    return suppress_small(
        {
            "haircut_non_merger": None,
            "signal_window": {"first": window[0], "last": window[1]},
            "primary": {
                key: primary[key]
                for key in ("mature", "fair_cost_median", "matched_excess_median", "interval")
            },
        }
    )


def regime_cut(episodes: list[dict[str, Any]], cut: Mapping[str, Any]) -> dict[str, Any]:
    first, last = str(cut["first_signal"]), str(cut["last_signal"])
    rows = [row for row in _mature(episodes) if _between(row, first, last)]
    return suppress_small({"block": cut.get("block"), "first": first, "last": last, **_mini(rows)})


def month_series(episodes: list[dict[str, Any]], window: tuple[str, str]) -> list[dict[str, Any]]:
    first, last = window
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _mature(episodes):
        if _between(row, first, last):
            groups[str(row["signal_session"])[:7]].append(row)
    months: list[str] = []
    year, month = int(first[:4]), int(first[5:7])
    while f"{year:04d}-{month:02d}" <= last[:7]:
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    out = []
    for key in months:
        rows = groups.get(key, [])
        cell: dict[str, Any] = {"month": key, "episodes": len(rows)}
        if len(rows) >= 5:
            cell["fair_cost_median"] = _median([v for v in map(_floor, rows) if v is not None])
            cell["matched_excess_median"] = _median(
                [v for v in map(_excess, rows) if v is not None]
            )
        out.append(cell)
    return out


# --- Walk ----------------------------------------------------------------------------------

# Episode keys no board or block reads; dropped from the rows kept in memory.
# The scratch files keep whole episodes.
_UNREAD_KEYS = frozenset(
    {
        "inputs",
        "reviews",
        "floor_history",
        "memo_rationale",
        "t212_fetched_at",
        "data_commit",
        "download_as_of",
    }
)
# Peak resident memory, calibrated on ``scripts/strategy_book_rehearsal_scale.py``
# at the real shape (4,448 names, 6,717 sessions): the input pass holds one
# batch of bars and specs, the walk one batch of walk state; both hold the
# whole-book tables and the cross-name tape (about 9 bytes per name-session).
MEMORY_LOAD_FIXED_MB = 450
MEMORY_LOAD_PER_NAME_MB = 2.6
MEMORY_WALK_FIXED_MB = 1100
MEMORY_WALK_PER_NAME_MB = 1.0
MEMORY_PER_CROSS_CELL_BYTES = 9


def walk_options(registration: Mapping[str, Any], last_signal: str) -> sbo.WalkOptions:
    first = date.fromisoformat(registration["windows"]["development"]["first_signal"])
    return dataclasses.replace(
        sbo.options_for(sbo.US_REHEARSAL_MODE),
        entry_not_before=first,
        entry_not_after=date.fromisoformat(last_signal),
    )


def walk(
    inputs: RehearsalInputs, registration: Mapping[str, Any], *, last_signal: str, variant: str
) -> dict[str, Any]:
    """Whole-book walk of materialised inputs (small books and tests)."""
    return sbo.walk_book(
        inputs.with_variant(variant), options=walk_options(registration, last_signal)
    )


def _compact(episode: Mapping[str, Any]) -> dict[str, Any]:
    out = {key: value for key, value in episode.items() if key not in _UNREAD_KEYS}
    if out.get("decision_log"):
        out["decision_log"] = [
            row for row in out["decision_log"] if row.get("action") == sbo.EXIT_THESIS
        ]
    return out


class _ScratchFiles:
    """Per-episode files of one variant, written as each batch is walked."""

    def __init__(self, target: Path, variant: str) -> None:
        self.episodes = gzip.open(target / f"episodes_{variant}.jsonl.gz", "wt", encoding="utf-8")
        self.events = gzip.open(target / f"events_{variant}.json.gz", "wt", encoding="utf-8")
        self.events.write("[")
        self._first_event = True

    def add(self, result: Mapping[str, Any]) -> None:
        for episode in result["episodes"]:
            self.episodes.write(json.dumps(episode, default=str) + "\n")
        for event in result["events"]:
            self.events.write(("" if self._first_event else ", ") + json.dumps(event, default=str))
            self._first_event = False

    def close(self) -> None:
        self.events.write("]")
        self.events.close()
        self.episodes.close()


def walk_batches(
    source: RehearsalSource,
    registration: Mapping[str, Any],
    *,
    last_signal: str,
    target: Path,
) -> dict[str, dict[str, Any]]:
    """Walk both delisting variants batch by batch against the source's cross-name tape.

    Whole episodes and events go to ``target`` as each batch finishes. The
    returned results hold what the blocks read: compact baseline episodes,
    compact sensitivity primary episodes, primary ``no_next_bar`` events,
    summed counts and the recovery cap from summed per-session counts. Their
    episodes are in whole-book order, so the blocks equal a whole-book walk's.
    """
    options = walk_options(registration, last_signal)
    cross = source.cross
    if cross is None:
        raise ValueError("the source was prepared without a cross-name tape")
    views = {
        BASELINE: cross,
        SENSITIVITY: cross.with_haircuts(
            lambda ticker: (source.haircuts.get(ticker) or {}).get(SENSITIVITY)
        ),
    }
    target.mkdir(parents=True, exist_ok=True)
    files = {variant: _ScratchFiles(target, variant) for variant in views}
    kept: dict[str, dict[str, Any]] = {
        variant: {
            "episodes": [],
            "events": [],
            "counts": {},
            "open": np.zeros(len(cross.calendar), dtype=np.int64),
            "labelled": np.zeros(len(cross.calendar), dtype=np.int64),
            "scoring_date": None,
        }
        for variant in views
    }
    try:
        for position in range(max(len(source.batches), 1)):
            specs = source.specs(position) if source.batches else []
            for variant, view in views.items():
                result = sbo.walk_book(
                    with_variant(specs, source.haircuts, variant), options=options, cross=view
                )
                files[variant].add(result)
                row = kept[variant]
                for episode in result["episodes"]:
                    if variant == BASELINE or episode.get("column") == COLUMN_PRIMARY:
                        row["episodes"].append(_compact(episode))
                row["events"].extend(
                    {key: event.get(key) for key in ("kind", "column", "ticker", "session")}
                    for event in result["events"]
                    if event.get("kind") == "no_next_bar" and event.get("column") == COLUMN_PRIMARY
                )
                for key, value in result["counts"].items():
                    row["counts"][key] = row["counts"].get(key, 0) + int(value)
                row["open"] += np.asarray(result["recovery_open"], dtype=np.int64)
                row["labelled"] += np.asarray(result["recovery_labelled"], dtype=np.int64)
                if row["scoring_date"] not in (None, result["scoring_date"]):
                    raise ValueError("batches disagree on the scoring date")
                row["scoring_date"] = result["scoring_date"]
                del result
            del specs
    finally:
        for handle in files.values():
            handle.close()
    order = source.order()
    out: dict[str, dict[str, Any]] = {}
    for variant, row in kept.items():
        row["episodes"].sort(key=lambda episode: order[(episode["market"], episode["ticker"])])
        cap_days, samples = sbo.recovery_cap(
            cross.calendar, row["open"].tolist(), row["labelled"].tolist()
        )
        out[variant] = {
            "episodes": row["episodes"],
            "events": row["events"],
            "counts": row["counts"],
            "cap_would_block_days": cap_days,
            "recovery_share_samples": samples,
            "scoring_date": row["scoring_date"],
        }
    return out


def memory_estimate_mb(names: int, sessions: int, batch_size: int) -> int:
    """Rough peak resident memory of ``develop`` or ``reveal`` for a book of this shape."""
    cross = names * sessions * MEMORY_PER_CROSS_CELL_BYTES / 2**20
    batch = min(max(batch_size, 1), max(names, 1))
    return int(
        cross
        + max(
            MEMORY_LOAD_FIXED_MB + MEMORY_LOAD_PER_NAME_MB * batch,
            MEMORY_WALK_FIXED_MB + MEMORY_WALK_PER_NAME_MB * batch,
        )
    )


def memory_warning(names: int, sessions: int, batch_size: int) -> str | None:
    """A warning when psutil reports less available memory than the run needs."""
    try:
        import psutil
    except ImportError:
        return None
    available = psutil.virtual_memory().available / 2**20
    need = memory_estimate_mb(names, sessions, batch_size)
    if available >= need:
        return None
    smaller = 25
    for size in range(min(batch_size, names) // 25 * 25, 25, -25):
        if memory_estimate_mb(names, sessions, size) <= available:
            smaller = size
            break
    return (
        f"warning: about {need} MB is needed with --batch-size {batch_size} but only "
        f"{int(available)} MB is available. Close other programs or pass a smaller "
        f"--batch-size (for example {smaller}); results do not depend on it."
    )


def _scratch_dir(scratch: Path | None, build: Path) -> Path:
    return (
        Path(scratch).expanduser()
        if scratch is not None
        else Path(build).expanduser() / SCRATCH_DIRNAME
    )


def write_summary(
    target: Path, run: str, results: Mapping[str, Mapping[str, Any]], source: RehearsalSource
) -> Path:
    """The run summary beside the per-episode files, outside the repository."""
    summary = {
        "run": run,
        "counts": source.counts,
        "hl_basis": source.hl_basis,
        "walk_counts": {variant: result["counts"] for variant, result in results.items()},
        "cap_would_block_days": {
            variant: result["cap_would_block_days"] for variant, result in results.items()
        },
    }
    (target / "summary.json").write_text(json.dumps(summary, indent=2, default=str), "utf-8")
    return target


def _run(
    build: Path,
    mid_build: Path,
    sharadar_dir: Path,
    registration: Mapping[str, Any],
    *,
    last_signal: str,
    scratch_dir: Path,
    run: str,
    batch_size: int,
    check: Callable[[RehearsalSource], None] | None = None,
) -> tuple[RehearsalSource, dict[str, dict[str, Any]], Path]:
    source = prepare(
        BuildDir(Path(build).expanduser(), "sp500"),
        BuildDir(Path(mid_build).expanduser(), "midcap"),
        Path(sharadar_dir).expanduser(),
        registration,
        work_dir=scratch_dir,
        batch_size=batch_size,
        cross_options=walk_options(registration, last_signal),
    )
    try:
        if check is not None:
            check(source)
        warning = memory_warning(source.names_walked, len(source.calendar), batch_size)
        if warning:
            print(warning, file=sys.stderr)
        target = Path(scratch_dir) / run
        results = walk_batches(source, registration, last_signal=last_signal, target=target)
        write_summary(target, run, results, source)
    finally:
        source.remove()
    return source, results, target


# --- Store ---------------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def deletion_due(store: Mapping[str, Any]) -> str | None:
    first = (store.get("licensed_data") or {}).get("first_used_at")
    if not first:
        return None
    moment = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
    return (moment + timedelta(days=DELETION_DAYS)).date().isoformat()


def _finite_only(node: Any) -> Any:
    if isinstance(node, float):
        return node if math.isfinite(node) else None
    if isinstance(node, np.floating | np.integer):
        return _finite_only(node.item())
    if isinstance(node, Mapping):
        return {key: _finite_only(value) for key, value in node.items()}
    if isinstance(node, list | tuple):
        return [_finite_only(value) for value in node]
    return node


def write_store(path: Path, payload: Mapping[str, Any], tickers: Iterable[str] = ()) -> None:
    payload = _finite_only(payload)
    assert_private(payload, tickers)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _base_store(registration: Mapping[str, Any], inputs: RehearsalSource) -> dict[str, Any]:
    screen_codes = sorted(
        {str(c) for key in inputs.cache_keys.values() if (c := key.get("screen_code"))}
    )
    return {
        "registration_id": registration.get("registration_id"),
        "parent_registration_id": registration.get("parent_registration_id"),
        "observe_only": True,
        "influences_live": False,
        "screen_code_fingerprint": screen_codes[0] if screen_codes else None,
        "universe_basis": {SP500: "sp500_members", SP400: "cap_rank_501_1000"},
        "labels": {
            "sector_label_basis": "tickers_current",
            "sector_basis": "price_only",
            "statement_basis": "art_ttm",
            "f9_status": "f9_unverified",
            "research_verdict": "absent",
            "t212_listed": "not_applicable",
            "hl_basis_export": inputs.hl_basis,
        },
        "family": family(registration),
        "development": None,
        "confirmation": None,
        "reveal": None,
        "delisting_sensitivity": {"development": None, "confirmation": None},
        "regime_cuts": {},
        "month_series": [],
        "input_keys": inputs.cache_keys,
        "licensed_data": {"first_used_at": None, "deleted_at": None},
        "amendments": [],
        "runs": [],
    }


def _windows(registration: Mapping[str, Any]) -> dict[str, Any]:
    windows = registration["windows"]
    dev = (windows["development"]["first_signal"], windows["development"]["last_signal"])
    conf = (windows["confirmation"]["first_signal"], windows["confirmation"]["last_signal"])
    halves = []
    for token in windows["confirmation"].get("halves") or []:
        a, b = str(token).split("/")
        halves.append((a, b))
    return {"development": dev, "confirmation": conf, "halves": tuple(halves) or None}


def _cuts(registration: Mapping[str, Any], block: str) -> dict[str, Mapping[str, Any]]:
    return {
        key: cut
        for key, cut in (registration.get("regime_cuts") or {}).items()
        if cut.get("block") == block
    }


def _delisted(inputs: RehearsalSource | RehearsalInputs) -> set[str]:
    return set(inputs.haircuts)


def _scoring(result: Mapping[str, Any]) -> date:
    return date.fromisoformat(str(result["scoring_date"])[:10])


def development_blocks(
    registration: Mapping[str, Any],
    inputs: RehearsalSource | RehearsalInputs,
    results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    fam = family(registration)
    windows = _windows(registration)
    dev = windows["development"]
    base = results[BASELINE]
    sensitivity = sensitivity_block(
        results[SENSITIVITY]["episodes"], dev, fam["development_coverage"], fam
    )
    sensitivity["haircut_non_merger"] = float(
        (registration.get("prices") or {}).get("delisting_sensitivity_haircut_non_merger", -0.3)
    )
    return {
        "development": window_block(
            base["episodes"],
            base["events"],
            dev,
            coverage=fam["development_coverage"],
            fam=fam,
            scoring=_scoring(base),
            delisted=_delisted(inputs),
            label="development_descriptive",
        ),
        "sensitivity": sensitivity,
        "cuts": {
            key: regime_cut(base["episodes"], cut)
            for key, cut in _cuts(registration, "development").items()
        },
        "months": month_series(base["episodes"], dev),
    }


def develop(
    build: Path,
    mid_build: Path,
    sharadar_dir: Path,
    *,
    scratch: Path | None = None,
    repo_root: Path = REPO_ROOT,
    amendment: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Walk development signal sessions and commit the development block."""
    scratch_dir = _scratch_dir(scratch, build)
    registration = preflight(repo_root, build, mid_build, sharadar_dir, scratch_dir)
    store_path = Path(repo_root) / STORE_PATH
    previous = _load_json(store_path)
    if previous and previous.get("development") and not (amendment or "").strip():
        raise RehearsalRefused(
            "A development block is already committed. Recompute it only under a logged "
            "amendment (--amendment 'what was wrong')."
        )
    if previous and previous.get("reveal"):
        raise RehearsalRefused("The confirmation window is revealed; development is sealed.")
    now = _now()
    inputs, results, scratch_path = _run(
        build,
        mid_build,
        sharadar_dir,
        registration,
        last_signal=_windows(registration)["development"][1],
        scratch_dir=scratch_dir,
        run=f"develop-{now.replace(':', '')}",
        batch_size=batch_size,
    )
    blocks = development_blocks(registration, inputs, results)
    store = {**_base_store(registration, inputs), **(previous or {})}
    store["input_keys"] = inputs.cache_keys
    store["development"] = {"computed_at": now, **blocks["development"]}
    store["delisting_sensitivity"] = {
        **(store.get("delisting_sensitivity") or {}),
        "development": blocks["sensitivity"],
    }
    store["regime_cuts"] = {**(store.get("regime_cuts") or {}), **blocks["cuts"]}
    store["month_series"] = blocks["months"]
    store["run_counts"] = {
        "overlap_excluded_from_sp400": inputs.counts.get("overlap_excluded_from_sp400", 0),
        "names_walked": inputs.names_walked,
        "chart_not_daily": results[BASELINE]["counts"].get("chart_not_daily", 0),
        "thinned": results[BASELINE]["counts"].get("thinned", 0),
    }
    licensed = dict(store.get("licensed_data") or {})
    licensed.setdefault("first_used_at", None)
    licensed["first_used_at"] = licensed["first_used_at"] or now
    licensed.setdefault("deleted_at", None)
    store["licensed_data"] = licensed
    if previous and previous.get("development"):
        store["amendments"] = [
            *(store.get("amendments") or []),
            {"at": now, "kind": "development_recomputed", "note": str(amendment).strip()},
        ]
    store["runs"] = [*(store.get("runs") or []), {"kind": "develop", "at": now}]
    store["status"] = "development_committed"
    write_store(store_path, store, inputs.tickers)
    return {"store": store, "scratch": scratch_path}


def reveal(
    build: Path,
    mid_build: Path,
    sharadar_dir: Path,
    *,
    scratch: Path | None = None,
    repo_root: Path = REPO_ROOT,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """The single reveal: confirmation boards, verdicts, and the delisting sensitivity."""
    scratch_dir = _scratch_dir(scratch, build)
    registration = preflight(repo_root, build, mid_build, sharadar_dir, scratch_dir)
    store_path = Path(repo_root) / STORE_PATH
    store = _load_json(store_path)
    if not store or not store.get("development"):
        raise RehearsalRefused(
            "No development block is committed. Run `develop` and review it first."
        )
    if store.get("reveal"):
        raise RehearsalRefused("The confirmation window was already revealed. There is one reveal.")
    windows = _windows(registration)
    fam = family(registration)
    conf = windows["confirmation"]

    def _same_inputs(source: RehearsalSource) -> None:
        if store.get("input_keys") and store["input_keys"] != source.cache_keys:
            raise RehearsalRefused(
                "The panels or signals caches changed since the development block. Recompute "
                "development under a logged amendment before the reveal."
            )

    now = _now()
    inputs, results, scratch_path = _run(
        build,
        mid_build,
        sharadar_dir,
        registration,
        last_signal=conf[1],
        scratch_dir=scratch_dir,
        run=f"reveal-{now.replace(':', '')}",
        batch_size=batch_size,
        check=_same_inputs,
    )
    base = results[BASELINE]
    block = window_block(
        base["episodes"],
        base["events"],
        conf,
        coverage=fam["coverage"],
        fam=fam,
        scoring=_scoring(base),
        delisted=_delisted(inputs),
        halves=windows["halves"],
        label="bonferroni",
    )
    primary = block["primary"]
    verdict = primary_verdict(primary["fair_cost_median"], primary["interval"], primary["mature"])
    sensitivity = sensitivity_block(results[SENSITIVITY]["episodes"], conf, fam["coverage"], fam)
    sensitivity["haircut_non_merger"] = float(
        (registration.get("prices") or {}).get("delisting_sensitivity_haircut_non_merger", -0.3)
    )
    sens_primary = sensitivity["primary"]
    sensitivity_verdict = primary_verdict(
        sens_primary["fair_cost_median"], sens_primary["interval"], sens_primary["mature"]
    )
    sensitivity["verdict"] = sensitivity_verdict
    final = verdict
    if verdict == "pass" and sensitivity_verdict != "pass":
        final = "pass_delisting_sensitive"
    block["verdicts"] = {
        "primary": final,
        "primary_baseline": verdict,
        "clean_pass": final == "pass",
        "bench": {column: block["bench"][column]["verdict"] for column in BENCH_TESTS},
    }
    block["flags"]["pass_delisting_sensitive"] = final == "pass_delisting_sensitive"
    recomputed = development_blocks(registration, inputs, results)["development"]
    reproduced = all(
        recomputed["primary"].get(key) == store["development"]["primary"].get(key)
        for key in ("mature", "fair_cost_median", "matched_excess_median")
    )
    store["confirmation"] = {"computed_at": now, "development_reproduced": reproduced, **block}
    store["delisting_sensitivity"] = {
        **(store.get("delisting_sensitivity") or {}),
        "confirmation": sensitivity,
    }
    store["regime_cuts"] = {
        **(store.get("regime_cuts") or {}),
        **{
            key: regime_cut(base["episodes"], cut)
            for key, cut in _cuts(registration, "confirmation").items()
        },
    }
    store["month_series"] = [
        *[row for row in store.get("month_series") or [] if row["month"] < conf[0][:7]],
        *month_series(base["episodes"], conf),
    ]
    store["reveal"] = {"at": now, "evidence": True}
    store["runs"] = [*(store.get("runs") or []), {"kind": "reveal", "at": now}]
    store["status"] = "revealed"
    write_store(store_path, store, inputs.tickers)
    return {"store": store, "scratch": scratch_path}


def confirm_deleted(
    *,
    at: str | None = None,
    repo_root: Path = REPO_ROOT,
    still_present: Iterable[Path] = (),
) -> dict[str, Any]:
    """Stamp ``licensed_data.deleted_at``, by default with the screen replay's own stamp."""
    left = [Path(path).expanduser() for path in still_present if Path(path).expanduser().exists()]
    if left:
        raise RehearsalRefused(
            f"{len(left)} licensed or derived path(s) still exist. Delete them before confirming."
        )
    store_path = Path(repo_root) / STORE_PATH
    store = _load_json(store_path)
    if not store:
        raise RehearsalRefused(f"{STORE_PATH} does not exist; nothing to confirm.")
    licensed = dict(store.get("licensed_data") or {})
    first = licensed.get("first_used_at")
    stamp = at
    if stamp is None:
        hsr_store = _load_json(Path(repo_root) / hsr.DEFAULT_STORE_PATH) or {}
        stamp = (hsr_store.get("licensed_data") or {}).get("deleted_at")
        if not stamp or (first and str(stamp) < str(first)):
            raise RehearsalRefused(
                "Run `ftse-historical-replay confirm-deleted` first (its stamp predates this "
                "rehearsal), or pass --at with the deletion time."
            )
    licensed["deleted_at"] = str(stamp)
    store["licensed_data"] = licensed
    write_store(store_path, store)
    return licensed


# --- Status and findings -------------------------------------------------------------------


def status(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    registration = _load_json(Path(repo_root) / REGISTRATION_PATH) or {}
    store = _load_json(Path(repo_root) / STORE_PATH) or {}
    development = store.get("development") or {}
    confirmation = store.get("confirmation") or {}
    return {
        "registration_id": registration.get("registration_id"),
        "registration_status": registration.get("status"),
        "parent_signed": registration_signed(Path(repo_root) / PARENT_SEAL),
        "store": str(STORE_PATH),
        "development_computed_at": development.get("computed_at"),
        "development_mature_episodes": (development.get("primary") or {}).get("mature"),
        "reveal": store.get("reveal"),
        "primary_verdict": (confirmation.get("verdicts") or {}).get("primary"),
        "licensed_data": store.get("licensed_data"),
        "deletion_due": deletion_due(store) if store else None,
        "amendments": len(store.get("amendments") or []),
    }


def findings(repo_root: Path = REPO_ROOT, now: datetime | None = None) -> list[dict[str, Any]]:
    """Observe-only findings for ops-monitor. Never auto-fixable."""
    path = Path(repo_root) / STORE_PATH
    if not path.exists():
        return []
    store = _load_json(path)
    if store is None:
        return [
            {
                "severity": "warn",
                "title": TITLE_FAILED,
                "summary": f"{STORE_PATH} is not valid JSON.",
            }
        ]
    out: list[dict[str, Any]] = []
    development = store.get("development") or {}
    if development:
        primary = development.get("primary") or {}
        out.append(
            {
                "severity": "info",
                "title": TITLE_DEVELOPMENT,
                "summary": (
                    f"Development block computed {development.get('computed_at')}: "
                    f"{primary.get('mature')} mature primary episodes. Owner review before the "
                    "single reveal; no registered number changes."
                ),
            }
        )
    reveal_row = store.get("reveal")
    if reveal_row:
        verdicts = (store.get("confirmation") or {}).get("verdicts") or {}
        out.append(
            {
                "severity": "info",
                "title": TITLE_REVEALED,
                "summary": (
                    f"Revealed {reveal_row.get('at')}: primary {verdicts.get('primary')}, bench "
                    f"{verdicts.get('bench')}. Method evidence only; the forward bench is unchanged."
                ),
            }
        )
    licensed = store.get("licensed_data") or {}
    due = deletion_due(store)
    if licensed.get("first_used_at") and not licensed.get("deleted_at") and due:
        moment = now or datetime.now(UTC)
        left = (date.fromisoformat(due) - moment.date()).days
        out.append(
            {
                "severity": "warn",
                "title": TITLE_DELETION_DUE,
                "summary": (
                    f"Licensed Sharadar files were first used {licensed['first_used_at']}; delete "
                    f"them and every derived file by {due} ({left} days), then run "
                    "`ftse-strategy-book-rehearsal confirm-deleted`."
                ),
            }
        )
    return out


# --- CLI -----------------------------------------------------------------------------------


def _paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--build", type=Path, required=True, help="hsr-v2 build directory")
    parser.add_argument("--mid-build", type=Path, required=True, help="hsr-mid-v2 build directory")
    parser.add_argument("--sharadar-dir", type=Path, required=True, help="Sharadar exports")
    parser.add_argument(
        "--scratch",
        type=Path,
        help=f"Per-episode output, outside the repo (default: <build>/{SCRATCH_DIRNAME})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=(
            f"Names walked together (default {DEFAULT_BATCH_SIZE}). Smaller uses less memory; "
            "results do not depend on it."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ftse-strategy-book-rehearsal",
        description="Strategy-book US point-in-time rehearsal (strategy-book-us-rehearsal-v0).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    dev_p = sub.add_parser("develop", help="Walk development signal sessions; commit that block")
    _paths(dev_p)
    dev_p.add_argument(
        "--amendment", help="Recompute a committed development block; the note is logged"
    )
    rev_p = sub.add_parser(
        "reveal", help="The single confirmation reveal and delisting sensitivity"
    )
    _paths(rev_p)
    sub.add_parser("status", help="Print the store status (reads the committed store only)")
    del_p = sub.add_parser("confirm-deleted", help="Stamp licensed_data.deleted_at after deletion")
    del_p.add_argument("--at", help="Deletion timestamp (default: the screen replay's deleted_at)")
    del_p.add_argument(
        "--check",
        type=Path,
        action="append",
        default=[],
        help="A path that must no longer exist (repeatable)",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            print(json.dumps(status(), indent=2))
            return 0
        if args.command == "confirm-deleted":
            print(json.dumps(confirm_deleted(at=args.at, still_present=args.check), indent=2))
            return 0
        run = develop if args.command == "develop" else reveal
        if args.batch_size < 1:
            parser.error("--batch-size must be at least 1")
        kwargs: dict[str, Any] = {"scratch": args.scratch, "batch_size": args.batch_size}
        if args.command == "develop":
            kwargs["amendment"] = args.amendment
        out = run(args.build, args.mid_build, args.sharadar_dir, **kwargs)
    except (RehearsalRefused, RegistrationUnsigned, InputsMissing, PrivacyViolation) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    store = out["store"]
    key = "development" if args.command == "develop" else "confirmation"
    summary = {
        "wrote": str(STORE_PATH),
        "scratch": "outside the repository (see --scratch)",
        "block": key,
        "primary": (store.get(key) or {}).get("primary"),
    }
    if args.command == "reveal":
        summary["verdicts"] = store["confirmation"].get("verdicts")
    print(json.dumps(summary, indent=2))
    print(f"scratch files: {out['scratch']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
