"""Detect and normalize Yahoo GBp↔GBP (pence↔pounds) mid-series unit flips.

Yahoo LSE history occasionally mixes pence and pounds in the same close
series. A one-session ~100× jump then reads as a −99% wipeout in
``chart_outcome_review`` even though the name is still quoted normally.

This module chain-corrects those discontinuities so returns and SMAs use one
unit. It is intentionally unit-agnostic (pence or pounds): the latest finite
print is left numerically unchanged so the series stays aligned with the
vendor's current quote scale.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

# Yahoo's GBp/GBP mix is a clean factor of 100. Keep the acceptance band tight
# so ordinary multi-bagger days / real crashes are not rewritten.
UNIT_FACTOR = 100.0
MIN_FLIP_RATIO = 80.0
MAX_FLIP_RATIO = 125.0
_MAX_CHAIN_STEPS = 4


@dataclass(frozen=True)
class PriceUnitNormalization:
    """Result of normalizing a close series for GBp↔GBP flips."""

    values: list[float | None]
    flip_count: int
    scales: list[float]
    applied: bool

    def as_meta(self) -> dict[str, Any] | None:
        if not self.applied:
            return None
        return {
            "kind": "yahoo_gbp_unit_flip",
            "flip_count": self.flip_count,
            "unit_factor": UNIT_FACTOR,
            "anchor": "last",
        }


def is_unit_flip_ratio(ratio: float | None) -> bool:
    """True when ``ratio`` (or its reciprocal) sits in the ~100× flip band."""
    if ratio is None:
        return False
    try:
        value = float(ratio)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(value) or value <= 0:
        return False
    if MIN_FLIP_RATIO <= value <= MAX_FLIP_RATIO:
        return True
    inverse = 1.0 / value
    return MIN_FLIP_RATIO <= inverse <= MAX_FLIP_RATIO


def _finite_positive(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def align_price_to_reference(price: float | None, reference: float | None) -> float | None:
    """Scale ``price`` by 100^n when it is a pure unit mismatch vs ``reference``."""
    level = _finite_positive(price)
    ref = _finite_positive(reference)
    if level is None:
        return None if price is None else _finite_positive(price)
    if ref is None:
        return level
    adjusted = level
    for _ in range(_MAX_CHAIN_STEPS):
        ratio = adjusted / ref
        if not is_unit_flip_ratio(ratio):
            break
        if ratio >= MIN_FLIP_RATIO:
            adjusted /= UNIT_FACTOR
        else:
            adjusted *= UNIT_FACTOR
    return adjusted


def normalize_price_series(
    values: Sequence[Any],
    *,
    anchor: str = "last",
) -> PriceUnitNormalization:
    """
    Chain-correct ~100× discontinuities so the series shares one price unit.

    ``anchor='last'`` (default) keeps the final finite print unchanged and
    rewrites earlier bars into that unit. ``anchor='first'`` does the opposite.
    """
    raw: list[float | None] = []
    for value in values:
        number = _finite_positive(value)
        if number is None and value is not None:
            try:
                candidate = float(value)
            except (TypeError, ValueError):
                candidate = float("nan")
            raw.append(candidate if math.isfinite(candidate) else None)
        else:
            raw.append(number)

    if not raw:
        return PriceUnitNormalization(values=[], flip_count=0, scales=[], applied=False)

    forward: list[float | None] = [None] * len(raw)
    scales = [1.0] * len(raw)
    prev_out: float | None = None
    prev_raw_for_count: float | None = None
    flip_count = 0

    for index, value in enumerate(raw):
        if (
            value is not None
            and value > 0
            and prev_raw_for_count is not None
            and prev_raw_for_count > 0
            and is_unit_flip_ratio(value / prev_raw_for_count)
        ):
            flip_count += 1
        if value is not None and value > 0:
            prev_raw_for_count = value

        if value is None or value <= 0:
            forward[index] = value
            scales[index] = scales[index - 1] if index else 1.0
            continue
        if prev_out is None or prev_out <= 0:
            forward[index] = value
            scales[index] = 1.0
            prev_out = value
            continue

        adjusted = float(value)
        steps = 0
        while steps < _MAX_CHAIN_STEPS:
            ratio = adjusted / prev_out
            if ratio >= MIN_FLIP_RATIO:
                adjusted /= UNIT_FACTOR
                steps += 1
                continue
            if ratio <= (1.0 / MIN_FLIP_RATIO):
                adjusted *= UNIT_FACTOR
                steps += 1
                continue
            break

        forward[index] = adjusted
        scales[index] = adjusted / value if value else 1.0
        prev_out = adjusted

    if flip_count == 0:
        return PriceUnitNormalization(
            values=list(raw),
            flip_count=0,
            scales=[1.0] * len(raw),
            applied=False,
        )

    if anchor not in {"last", "first"}:
        raise ValueError(f"Unsupported anchor: {anchor}")

    if anchor == "last":
        last_idx = next(
            (i for i in range(len(raw) - 1, -1, -1) if raw[i] is not None and raw[i] > 0),
            None,
        )
        if last_idx is None or not forward[last_idx]:
            global_scale = 1.0
        else:
            global_scale = float(raw[last_idx]) / float(forward[last_idx])
    else:
        first_idx = next(
            (i for i, value in enumerate(raw) if value is not None and value > 0),
            None,
        )
        if first_idx is None or not forward[first_idx]:
            global_scale = 1.0
        else:
            global_scale = float(raw[first_idx]) / float(forward[first_idx])

    out: list[float | None] = []
    final_scales: list[float] = []
    for index, value in enumerate(forward):
        if value is None:
            out.append(None)
            final_scales.append(scales[index] * global_scale)
            continue
        adjusted = value * global_scale
        out.append(adjusted)
        if raw[index] and raw[index] > 0:
            final_scales.append(adjusted / float(raw[index]))
        else:
            final_scales.append(global_scale)

    return PriceUnitNormalization(
        values=out,
        flip_count=flip_count,
        scales=final_scales,
        applied=True,
    )


def normalize_close_series(series: pd.Series, *, anchor: str = "last") -> tuple[pd.Series, PriceUnitNormalization]:
    """Normalize a pandas close series; returns (series, meta)."""
    if series is None or series.empty:
        empty = PriceUnitNormalization(values=[], flip_count=0, scales=[], applied=False)
        return series, empty
    result = normalize_price_series(series.tolist(), anchor=anchor)
    if not result.applied:
        return series, result
    normalized = pd.Series(result.values, index=series.index, dtype="float64")
    return normalized, result


def normalize_ohlcv_frame(frame: pd.DataFrame, *, anchor: str = "last") -> tuple[pd.DataFrame, PriceUnitNormalization]:
    """Apply close-derived unit scales to OHLC columns when flips are detected."""
    if frame is None or frame.empty or "Close" not in frame.columns:
        empty = PriceUnitNormalization(values=[], flip_count=0, scales=[], applied=False)
        return frame, empty
    close = frame["Close"]
    result = normalize_price_series(close.tolist(), anchor=anchor)
    if not result.applied:
        return frame, result
    out = frame.copy()
    scale = pd.Series(result.scales, index=frame.index, dtype="float64")
    for column in ("Open", "High", "Low", "Close"):
        if column in out.columns:
            out[column] = out[column].astype("float64") * scale
    return out, result


__all__ = [
    "MAX_FLIP_RATIO",
    "MIN_FLIP_RATIO",
    "UNIT_FACTOR",
    "PriceUnitNormalization",
    "align_price_to_reference",
    "is_unit_flip_ratio",
    "normalize_close_series",
    "normalize_ohlcv_frame",
    "normalize_price_series",
]
