"""N215 soft-band technical veto observe (labels only).

Frozen feature→score recipe + PASS/WARN/SOFT_VETO/HARD_CANDIDATE bands on
sealed N200 closed episodes (N210 anecdote). Point-in-time bars with
``date <= buy_ts`` only. Never influences live fills.

See ``docs/ops/n215-technical-veto-observe.md`` and Project store
``technical-veto-adaptive-approaches.md``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.price_charts import chart_filename

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/n215_technical_veto_observe.json")
DEFAULT_REGISTRATION_PATH = Path("docs/data/n215_technical_veto_registration.json")
DEFAULT_OPS_DOC = Path("docs/ops/n215-technical-veto-observe.md")
DEFAULT_N200_STORE = Path("docs/data/n200_tech_timing_observe.json")
DEFAULT_N206_STORE = Path("docs/data/n206_plain_ey_observe.json")
DEFAULT_N210_STORE = Path("docs/data/n210_ai_judgment_observe.json")
DEFAULT_CHARTS_DIR = Path("docs/data/charts")

REGISTRATION_ID = "n215-soft-band-veto-v0"
RECIPE_ID = "n215-soft-score-recipe-v0"
GRIND_MID60_RULE_ID = "n215-grind-mid60-pass-v0"
DEFERRED_ID = "N215"
SCHEMA_VERSION = 1

# Companion alone rule (frozen 2026-10-22): soft PASS ∧ mid_range_60 ≥ thr.
# Discovery = N206; alone-benefit primary = N200. Not a soft weight tweak. Not live.
GRIND_MID60_LOOKBACK = 60
GRIND_MID60_THR = 0.50
GRIND_MID60_LEARNING_QUESTION = (
    "On sealed closed buys that soft-band labels PASS, does blocking entries "
    "whose close sits at or above the midpoint of the prior 60 trading-day "
    "range catch deep losers alone, with acceptable large-winner miss and "
    "positive alone net fair-cost benefit vs the unfiltered sealed cohort?"
)

LEARNING_QUESTION = (
    "For each pre-registered soft-veto band threshold on sealed N200 closed "
    "episodes (charts ≤ buy_ts), what is catch rate among deep losers "
    "(fair-cost ≤ −10%) vs miss rate among large winners (≥ +10%)? "
    "Companion: risk_score distribution. Observe labels only — no live gate."
)

FINDING_TITLE = "N215 soft-band technical veto observe refreshed"
STORE_FAILED_TITLE = "N215 soft-band technical veto observe failed"

# ---------------------------------------------------------------------------
# Frozen pins (pre-registered before scoring — do not retune on this cohort)
# ---------------------------------------------------------------------------

LOOKBACK_TRADING_DAYS = 126
MIN_BARS_FOR_SCORE = 60
FRACTAL_N = 5
TWIN_PEAK_TOL = 0.02
TWIN_TROUGH_MIN = 0.10
DEEP_LOSER = -0.10
LARGE_WINNER = 0.10

# Hard-rule companion pins (first-pass comparison; not soft-score inputs)
NEAR_HIGH_PCT = 0.03
I02_R20_MIN = 0.08
I01_ELEV_ABS_MAX = 0.05
I05_BREAK_LOOKBACK = 15
I05_PRIOR_HIGH_LOOKBACK = 63
I07_CROSS_LOOKBACK = 10
I08_ABOVE_LOOKBACK = 20
I10_RSI_OB = 70.0
I10_RSI_LOOKBACK = 5
RSI_PERIOD = 14

# Soft-score normalization scales (frozen)
ELEV_ABS_SCALE = 0.10  # full elev risk at peak; ~0.5 at 5% below
ELEV_RANGE_SCALE = 0.30
NEAR_HIGH_SCALE = 0.10
R20_SCALE = 0.15
RSI_LEVEL_FLOOR = 50.0
RSI_LEVEL_SPAN = 30.0

# Frozen weights (sum = 1.0)
FEATURE_WEIGHTS: dict[str, float] = {
    "f_elev_abs": 0.15,
    "f_elev_range": 0.10,
    "f_near_high": 0.12,
    "f_r20": 0.10,
    "f_failed_bo": 0.18,
    "f_rsi_fail": 0.15,
    "f_rsi_level": 0.08,
    "f_death_cross": 0.06,
    "f_lost_200": 0.06,
}

# Band cuts: PASS < WARN_LO ≤ WARN < SOFT_LO ≤ SOFT_VETO < HARD_LO ≤ HARD_CANDIDATE
BAND_WARN_LO = 0.35
BAND_SOFT_LO = 0.55
BAND_HARD_LO = 0.75

BAND_ORDER = ("PASS", "WARN", "SOFT_VETO", "HARD_CANDIDATE")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _clamp01(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _sma(closes: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if period <= 0 or len(closes) < period:
        return out
    window_sum = sum(closes[:period])
    out[period - 1] = window_sum / period
    for i in range(period, len(closes)):
        window_sum += closes[i] - closes[i - period]
        out[i] = window_sum / period
    return out


def _rsi_wilder(closes: list[float], period: int = RSI_PERIOD) -> list[float | None]:
    """Wilder RSI aligned to ``closes`` (None until warm)."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        gains[i] = max(delta, 0.0)
        losses[i] = max(-delta, 0.0)
    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    return out


def _fractal_high_indices(closes: list[float], n: int = FRACTAL_N) -> list[int]:
    """Local highs: close[i] >= closes in [i-n, i+n] (asymmetric near end)."""
    highs: list[int] = []
    last = len(closes) - 1
    for i in range(n, last + 1):
        left = closes[i - n : i]
        right = closes[i + 1 : min(last, i + n) + 1]
        peak = closes[i]
        if left and any(c > peak for c in left):
            continue
        if right and any(c > peak for c in right):
            continue
        # Require at least one bar on each side when interior; end-allowed when
        # right window is short but left is full (first-pass asymmetric rule).
        if not left:
            continue
        highs.append(i)
    return highs


@dataclass(frozen=True)
class TwinPeak:
    i1: int
    i2: int
    peak1: float
    peak2: float
    trough: float
    peak_hi: float


def _find_twin_peak(closes: list[float]) -> TwinPeak | None:
    """Two fractal highs within tol; intervening trough deep enough."""
    highs = _fractal_high_indices(closes)
    if len(highs) < 2:
        return None
    best: TwinPeak | None = None
    for a in range(len(highs)):
        for b in range(a + 1, len(highs)):
            i1, i2 = highs[a], highs[b]
            p1, p2 = closes[i1], closes[i2]
            peak_hi = max(p1, p2)
            if peak_hi <= 0:
                continue
            if abs(p1 - p2) / peak_hi > TWIN_PEAK_TOL:
                continue
            trough = min(closes[i1 : i2 + 1])
            if (peak_hi - trough) / peak_hi < TWIN_TROUGH_MIN:
                continue
            cand = TwinPeak(i1=i1, i2=i2, peak1=p1, peak2=p2, trough=trough, peak_hi=peak_hi)
            if best is None or cand.i2 > best.i2 or (cand.i2 == best.i2 and cand.i1 > best.i1):
                best = cand
    return best


def load_chart_bars_leq(
    charts_dir: Path,
    ticker: str,
    buy_day: str,
) -> tuple[list[str], list[float], list[float | None], list[float | None]] | None:
    """Load chart closes/SMA with ``date <= buy_day``. None if missing."""
    path = Path(charts_dir) / chart_filename(ticker)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    dates = payload.get("dates") or []
    closes = payload.get("closes") or []
    sma50 = payload.get("sma50_series") or []
    sma200 = payload.get("sma200_series") or []
    out_d: list[str] = []
    out_c: list[float] = []
    out_s50: list[float | None] = []
    out_s200: list[float | None] = []
    for i, raw_d in enumerate(dates):
        day = str(raw_d)[:10]
        if day > buy_day:
            break
        if i >= len(closes) or closes[i] is None:
            continue
        try:
            c = float(closes[i])
        except (TypeError, ValueError):
            continue
        out_d.append(day)
        out_c.append(c)
        s50 = None
        s200 = None
        if i < len(sma50) and sma50[i] is not None:
            try:
                s50 = float(sma50[i])
            except (TypeError, ValueError):
                s50 = None
        if i < len(sma200) and sma200[i] is not None:
            try:
                s200 = float(sma200[i])
            except (TypeError, ValueError):
                s200 = None
        out_s50.append(s50)
        out_s200.append(s200)
    if not out_c:
        return None
    return out_d, out_c, out_s50, out_s200


def band_for_score(score: float) -> str:
    if score >= BAND_HARD_LO:
        return "HARD_CANDIDATE"
    if score >= BAND_SOFT_LO:
        return "SOFT_VETO"
    if score >= BAND_WARN_LO:
        return "WARN"
    return "PASS"


def extract_features(
    closes: list[float],
    *,
    sma50: list[float | None] | None = None,
    sma200: list[float | None] | None = None,
) -> dict[str, Any]:
    """Compute raw + normalized soft features on PIT closes (window already cut)."""
    n = len(closes)
    t0 = closes[-1]
    window = closes[-LOOKBACK_TRADING_DAYS:] if n > LOOKBACK_TRADING_DAYS else closes
    w_max = max(window)
    w_min = min(window)
    w_range = w_max - w_min

    dist_abs = (w_max - t0) / w_max if w_max > 0 else 1.0
    elev_range = (w_max - t0) / w_range if w_range > 0 else 1.0
    r20 = 0.0
    if n >= 21 and closes[-21] > 0:
        r20 = (t0 / closes[-21]) - 1.0

    # Companion grind feature (not in soft weights): position in 60d range.
    mid_range_60: float | None = None
    if n >= 40:
        w60 = closes[-GRIND_MID60_LOOKBACK:] if n >= GRIND_MID60_LOOKBACK else closes
        wr60 = max(w60) - min(w60)
        if wr60 > 0:
            mid_range_60 = (t0 - min(w60)) / wr60

    twin = _find_twin_peak(window)
    # Remap twin indices to full series offset when window truncated.
    twin_offset = n - len(window)
    elev_abs: float | None = None
    elev_range_twin: float | None = None
    twin_detail: dict[str, Any] | None = None
    if twin is not None and twin.peak_hi > 0:
        elev_abs = (twin.peak_hi - t0) / twin.peak_hi
        elev_range_twin = (twin.peak_hi - t0) / w_range if w_range > 0 else None
        twin_detail = {
            "i1": twin.i1 + twin_offset,
            "i2": twin.i2 + twin_offset,
            "peak1": twin.peak1,
            "peak2": twin.peak2,
            "trough": twin.trough,
            "peak_hi": twin.peak_hi,
            "elev_abs": elev_abs,
            "elev_range": elev_range_twin,
        }

    # Failed breakout (I05 structure)
    failed_bo = False
    failed_bo_detail: dict[str, Any] | None = None
    if n >= I05_PRIOR_HIGH_LOOKBACK + 2:
        look_end = n - 1
        for j in range(max(0, look_end - I05_BREAK_LOOKBACK), look_end):
            prior = closes[max(0, j - I05_PRIOR_HIGH_LOOKBACK) : j]
            if not prior:
                continue
            level = max(prior)
            if closes[j] > level and t0 <= level:
                failed_bo = True
                failed_bo_detail = {
                    "break_i": j,
                    "level": level,
                    "spike": closes[j],
                    "t0": t0,
                }
                break

    rsi_series = _rsi_wilder(closes, RSI_PERIOD)
    rsi_t0 = rsi_series[-1]
    rsi_fail = False
    rsi_fail_detail: dict[str, Any] | None = None
    if rsi_t0 is not None:
        start = max(0, n - I10_RSI_LOOKBACK)
        ob_idxs = [
            i
            for i in range(start, n)
            if rsi_series[i] is not None and float(rsi_series[i]) >= I10_RSI_OB
        ]
        if ob_idxs:
            peak_close = max(closes[i] for i in ob_idxs)
            if t0 < peak_close:
                rsi_fail = True
                rsi_fail_detail = {
                    "peak_close": peak_close,
                    "t0": t0,
                    "rsi_t0": rsi_t0,
                }

    # SMA series: prefer chart series; else compute
    s50 = sma50 if sma50 is not None and len(sma50) == n else _sma(closes, 50)
    s200 = sma200 if sma200 is not None and len(sma200) == n else _sma(closes, 200)
    death_cross = False
    lost_200 = False
    if s50[-1] is not None and s200[-1] is not None:
        # Fresh death cross within lookback
        for i in range(max(1, n - I07_CROSS_LOOKBACK), n):
            if s50[i] is None or s200[i] is None or s50[i - 1] is None or s200[i - 1] is None:
                continue
            if s50[i - 1] >= s200[i - 1] and s50[i] < s200[i] and t0 < s50[i] and t0 < s200[i]:
                death_cross = True
                break
        # Lost 200 after recent above
        if t0 < float(s200[-1]):
            for i in range(max(0, n - I08_ABOVE_LOOKBACK), n):
                if s200[i] is not None and closes[i] > float(s200[i]):
                    lost_200 = True
                    break

    # Normalized soft features
    f_elev_abs = 0.0
    if elev_abs is not None:
        f_elev_abs = _clamp01(1.0 - float(elev_abs) / ELEV_ABS_SCALE)
    f_elev_range = 0.0
    if elev_range_twin is not None:
        f_elev_range = _clamp01(1.0 - float(elev_range_twin) / ELEV_RANGE_SCALE)
    f_near_high = _clamp01(1.0 - dist_abs / NEAR_HIGH_SCALE)
    f_r20 = _clamp01(r20 / R20_SCALE) if r20 > 0 else 0.0
    f_failed_bo = 1.0 if failed_bo else 0.0
    f_rsi_fail = 1.0 if rsi_fail else 0.0
    f_rsi_level = 0.0
    if rsi_t0 is not None:
        f_rsi_level = _clamp01((float(rsi_t0) - RSI_LEVEL_FLOOR) / RSI_LEVEL_SPAN)
    f_death_cross = 1.0 if death_cross else 0.0
    f_lost_200 = 1.0 if lost_200 else 0.0

    features = {
        "f_elev_abs": f_elev_abs,
        "f_elev_range": f_elev_range,
        "f_near_high": f_near_high,
        "f_r20": f_r20,
        "f_failed_bo": f_failed_bo,
        "f_rsi_fail": f_rsi_fail,
        "f_rsi_level": f_rsi_level,
        "f_death_cross": f_death_cross,
        "f_lost_200": f_lost_200,
    }
    raw = {
        "t0": t0,
        "w_max": w_max,
        "w_min": w_min,
        "dist_abs": dist_abs,
        "elev_range_of_window": elev_range,
        "r20": r20,
        "rsi_t0": rsi_t0,
        "mid_range_60": mid_range_60,
        "twin": twin_detail,
        "failed_bo": failed_bo_detail,
        "rsi_fail": rsi_fail_detail,
        "death_cross": death_cross,
        "lost_200": lost_200,
        "bars": n,
        "lookback_used": len(window),
    }
    # Hard-rule fires (companion first-pass comparison)
    i01 = bool(
        twin is not None and elev_abs is not None and 0.0 <= float(elev_abs) <= I01_ELEV_ABS_MAX
    )
    i02 = bool(dist_abs <= NEAR_HIGH_PCT and r20 >= I02_R20_MIN)
    hard_fires = {
        "I01": i01,
        "I02": i02,
        "I05": failed_bo,
        "I07": death_cross,
        "I08": lost_200,
        "I10": rsi_fail,
    }
    return {"features": features, "raw": raw, "hard_fires": hard_fires}


def score_features(features: dict[str, float]) -> tuple[float, list[dict[str, Any]]]:
    """Weighted sum → risk_score; return contributions for justification trail."""
    score = 0.0
    contribs: list[dict[str, Any]] = []
    for key, weight in FEATURE_WEIGHTS.items():
        val = float(features.get(key) or 0.0)
        part = weight * val
        score += part
        if val > 0:
            contribs.append(
                {
                    "feature": key,
                    "value": round(val, 6),
                    "weight": weight,
                    "contribution": round(part, 6),
                }
            )
    contribs.sort(key=lambda c: c["contribution"], reverse=True)
    return _clamp01(score), contribs


def build_reasons(
    *,
    band: str,
    score: float,
    contribs: list[dict[str, Any]],
    raw: dict[str, Any],
    hard_fires: dict[str, bool],
) -> list[str]:
    reasons: list[str] = [
        f"recipe={RECIPE_ID} risk_score={score:.4f} band={band}",
    ]
    for c in contribs[:5]:
        reasons.append(
            f"{c['feature']}={c['value']:.3f}×w{c['weight']:.2f}→{c['contribution']:.3f}"
        )
    twin = raw.get("twin")
    if isinstance(twin, dict):
        reasons.append(
            f"twin_peak elev_abs={twin.get('elev_abs')} elev_range={twin.get('elev_range')}"
        )
    if raw.get("failed_bo"):
        reasons.append("failed_breakout_structure")
    if raw.get("rsi_fail"):
        reasons.append(f"rsi_climax_fail rsi_t0={raw.get('rsi_t0')}")
    fired = [k for k, v in hard_fires.items() if v]
    if fired:
        reasons.append("hard_fires=" + ",".join(fired))
    else:
        reasons.append("hard_fires=none")
    return reasons


def outcome_bucket(fair_cost: float | None) -> str:
    if fair_cost is None:
        return "unknown"
    if fair_cost <= DEEP_LOSER:
        return "deep_loser"
    if fair_cost >= LARGE_WINNER:
        return "large_winner"
    return "other"


def score_episode(
    *,
    ticker: str,
    book: str,
    buy_ts: str,
    fair_cost: float | None,
    charts_dir: Path,
) -> dict[str, Any]:
    """Score one sealed episode. Missing/short history → fail-closed PASS."""
    buy_day = str(buy_ts)[:10]
    base: dict[str, Any] = {
        "ticker": ticker,
        "book": book,
        "buy_ts": buy_ts,
        "buy_day": buy_day,
        "fair_cost": fair_cost,
        "bucket": outcome_bucket(fair_cost),
        "recipe_id": RECIPE_ID,
        "influences_live": False,
        "observe_only": True,
    }
    loaded = load_chart_bars_leq(charts_dir, ticker, buy_day)
    if loaded is None:
        return {
            **base,
            "coverage": False,
            "fail_closed": True,
            "risk_score": 0.0,
            "band": "PASS",
            "reasons": ["missing_chart → fail-closed PASS"],
            "cited_features": {},
            "feature_contributions": [],
            "hard_fires": {},
            "mid_range_60": None,
            "grind_mid60_fire": False,
            "raw": {},
        }
    _dates, closes, sma50, sma200 = loaded
    if len(closes) < MIN_BARS_FOR_SCORE:
        return {
            **base,
            "coverage": False,
            "fail_closed": True,
            "bars_pre_buy": len(closes),
            "risk_score": 0.0,
            "band": "PASS",
            "reasons": [f"insufficient_bars={len(closes)}<{MIN_BARS_FOR_SCORE} → fail-closed PASS"],
            "cited_features": {},
            "feature_contributions": [],
            "hard_fires": {},
            "mid_range_60": None,
            "grind_mid60_fire": False,
            "raw": {"bars": len(closes)},
        }
    extracted = extract_features(closes, sma50=sma50, sma200=sma200)
    features = extracted["features"]
    score, contribs = score_features(features)
    band = band_for_score(score)
    reasons = build_reasons(
        band=band,
        score=score,
        contribs=contribs,
        raw=extracted["raw"],
        hard_fires=extracted["hard_fires"],
    )
    mid60 = extracted["raw"].get("mid_range_60")
    grind_fire = bool(
        band == "PASS" and mid60 is not None and float(mid60) >= GRIND_MID60_THR
    )
    if grind_fire:
        reasons.append(
            f"companion={GRIND_MID60_RULE_ID} mid_range_60={float(mid60):.4f}>={GRIND_MID60_THR}"
        )
    return {
        **base,
        "coverage": True,
        "fail_closed": False,
        "bars_pre_buy": len(closes),
        "risk_score": round(score, 6),
        "band": band,
        "reasons": reasons,
        "cited_features": {k: round(float(v), 6) for k, v in features.items()},
        "feature_contributions": contribs,
        "hard_fires": extracted["hard_fires"],
        "mid_range_60": round(float(mid60), 6) if mid60 is not None else None,
        "grind_mid60_fire": grind_fire,
        "raw": {
            "t0": extracted["raw"].get("t0"),
            "dist_abs": extracted["raw"].get("dist_abs"),
            "r20": extracted["raw"].get("r20"),
            "rsi_t0": extracted["raw"].get("rsi_t0"),
            "mid_range_60": mid60,
            "twin": extracted["raw"].get("twin"),
            "failed_bo": extracted["raw"].get("failed_bo"),
            "death_cross": extracted["raw"].get("death_cross"),
            "lost_200": extracted["raw"].get("lost_200"),
            "bars": extracted["raw"].get("bars"),
            "lookback_used": extracted["raw"].get("lookback_used"),
        },
    }


def _load_closed_episodes(store_path: Path, book: str) -> list[dict[str, Any]]:
    if not store_path.is_file():
        return []
    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("lifecycle_episodes") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").lower() != "closed":
            continue
        ticker = str(row.get("ticker") or "").strip()
        buy_ts = str(row.get("entry_run_at") or "").strip()
        if not ticker or not buy_ts:
            continue
        fc = row.get("fair_cost_return")
        try:
            fair_cost = float(fc) if fc is not None else None
        except (TypeError, ValueError):
            fair_cost = None
        out.append(
            {
                "ticker": ticker,
                "book": book,
                "buy_ts": buy_ts,
                "exit_run_at": row.get("exit_run_at"),
                "fair_cost": fair_cost,
            }
        )
    return out


def _rollup_band_catch_miss(rows: list[dict[str, Any]]) -> dict[str, Any]:
    deep = [r for r in rows if r.get("bucket") == "deep_loser" and r.get("book") == "N200"]
    large = [r for r in rows if r.get("bucket") == "large_winner" and r.get("book") == "N200"]
    n200 = [r for r in rows if r.get("book") == "N200"]

    def _count_band(subset: list[dict[str, Any]], band: str, *, cumulative: bool) -> int:
        thr = {
            "PASS": 0.0,
            "WARN": BAND_WARN_LO,
            "SOFT_VETO": BAND_SOFT_LO,
            "HARD_CANDIDATE": BAND_HARD_LO,
        }[band]
        if cumulative:
            if band == "PASS":
                return sum(1 for r in subset if float(r.get("risk_score") or 0) < BAND_WARN_LO)
            return sum(1 for r in subset if float(r.get("risk_score") or 0) >= thr)
        return sum(1 for r in subset if r.get("band") == band)

    exclusive: dict[str, Any] = {}
    cumulative: dict[str, Any] = {}
    for band in BAND_ORDER:
        d_ex = _count_band(deep, band, cumulative=False)
        l_ex = _count_band(large, band, cumulative=False)
        exclusive[band] = {
            "deep_catch": f"{d_ex}/{len(deep)}",
            "deep_n": d_ex,
            "large_miss": f"{l_ex}/{len(large)}",
            "large_n": l_ex,
            "all_n200": _count_band(n200, band, cumulative=False),
        }
        if band == "PASS":
            continue
        d_cu = _count_band(deep, band, cumulative=True)
        l_cu = _count_band(large, band, cumulative=True)
        cumulative[f">={band}"] = {
            "deep_catch": f"{d_cu}/{len(deep)}",
            "deep_n": d_cu,
            "large_miss": f"{l_cu}/{len(large)}",
            "large_n": l_cu,
            "all_n200": _count_band(n200, band, cumulative=True),
            "threshold": {
                "WARN": BAND_WARN_LO,
                "SOFT_VETO": BAND_SOFT_LO,
                "HARD_CANDIDATE": BAND_HARD_LO,
            }[band],
        }

    # Hard-rule companion (same cohort / same feature extractors)
    def _hard_catch_miss(pred) -> dict[str, Any]:
        deep_hits = sum(1 for r in deep if pred(r))
        large_hits = sum(1 for r in large if pred(r))
        all_f = sum(1 for r in n200 if pred(r))
        return {
            "deep_catch": f"{deep_hits}/{len(deep)}",
            "deep_n": deep_hits,
            "large_miss": f"{large_hits}/{len(large)}",
            "large_n": large_hits,
            "all_n200_fires": all_f,
        }

    hard = {
        "I01_or_I02": _hard_catch_miss(
            lambda r: (
                bool((r.get("hard_fires") or {}).get("I01"))
                or bool((r.get("hard_fires") or {}).get("I02"))
            )
        ),
        "any_of_six": _hard_catch_miss(
            lambda r: any(bool(v) for v in (r.get("hard_fires") or {}).values())
        ),
    }

    scores_deep = [float(r["risk_score"]) for r in deep]
    scores_large = [float(r["risk_score"]) for r in large]
    scores_all = [float(r["risk_score"]) for r in n200]

    def _med(xs: list[float]) -> float | None:
        if not xs:
            return None
        ys = sorted(xs)
        m = len(ys) // 2
        if len(ys) % 2:
            return ys[m]
        return (ys[m - 1] + ys[m]) / 2.0

    return {
        "n200_closed": len(n200),
        "deep_losers": len(deep),
        "large_winners": len(large),
        "exclusive_bands": exclusive,
        "cumulative_bands": cumulative,
        "hard_rule_companion": hard,
        "companion_grind_mid60": _rollup_grind_mid60(rows),
        "score_distribution": {
            "deep_median": _med(scores_deep),
            "large_median": _med(scores_large),
            "all_n200_median": _med(scores_all),
            "deep_mean": (sum(scores_deep) / len(scores_deep)) if scores_deep else None,
            "large_mean": (sum(scores_large) / len(scores_large)) if scores_large else None,
        },
    }


def _med_fc(xs: list[float]) -> float | None:
    if not xs:
        return None
    ys = sorted(xs)
    m = len(ys) // 2
    if len(ys) % 2:
        return ys[m]
    return (ys[m - 1] + ys[m]) / 2.0


def _book_grind_cell(rows: list[dict[str, Any]], book: str) -> dict[str, Any]:
    book_rows = [r for r in rows if r.get("book") == book]
    deep = [r for r in book_rows if r.get("bucket") == "deep_loser"]
    large = [r for r in book_rows if r.get("bucket") == "large_winner"]
    fired = [r for r in book_rows if r.get("grind_mid60_fire")]
    deep_catch = sum(1 for r in deep if r.get("grind_mid60_fire"))
    large_miss = sum(1 for r in large if r.get("grind_mid60_fire"))
    base_fcs = [float(r["fair_cost"]) for r in book_rows if r.get("fair_cost") is not None]
    alt_fcs = [
        float(r["fair_cost"])
        for r in book_rows
        if r.get("fair_cost") is not None and not r.get("grind_mid60_fire")
    ]
    base_sum = sum(base_fcs) if base_fcs else 0.0
    alt_sum = sum(alt_fcs) if alt_fcs else 0.0
    return {
        "closed": len(book_rows),
        "coverage": sum(1 for r in book_rows if r.get("coverage")),
        "fired": len(fired),
        "deep_catch": f"{deep_catch}/{len(deep)}",
        "deep_n": deep_catch,
        "deep_total": len(deep),
        "large_miss": f"{large_miss}/{len(large)}",
        "large_n": large_miss,
        "large_total": len(large),
        "base_fc_median": _med_fc(base_fcs),
        "alt_fc_median": _med_fc(alt_fcs),
        "base_fc_sum": round(base_sum, 6),
        "alt_fc_sum": round(alt_sum, 6),
        "delta_fc_sum": round(alt_sum - base_sum, 6),
        "live_veto": False,
    }


def _rollup_grind_mid60(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Alone companion: PASS ∧ mid_range_60 ≥ thr. N200 primary; N206 report-only."""
    return {
        "rule_id": GRIND_MID60_RULE_ID,
        "rule": f"soft_band==PASS AND mid_range_60 >= {GRIND_MID60_THR}",
        "mid_range_60": (
            f"(close_t0 - min_{GRIND_MID60_LOOKBACK}) / "
            f"(max_{GRIND_MID60_LOOKBACK} - min_{GRIND_MID60_LOOKBACK})"
        ),
        "threshold": GRIND_MID60_THR,
        "lookback_trading_days": GRIND_MID60_LOOKBACK,
        "learning_question": GRIND_MID60_LEARNING_QUESTION,
        "discovery_book": "N206",
        "alone_benefit_primary": "N200",
        "influences_live": False,
        "observe_only": True,
        "N200": _book_grind_cell(rows, "N200"),
        "N206": _book_grind_cell(rows, "N206"),
        "admit_recommendation": {
            "live_veto": False,
            "note": (
                "Companion alone rule after counterfactual discovery. "
                "N200 is alone-benefit primary; N206 is discovery/report-only — "
                "do not retune threshold on N206. Not live."
            ),
        },
    }


def frozen_recipe_blob() -> dict[str, Any]:
    return {
        "recipe_id": RECIPE_ID,
        "registration_id": REGISTRATION_ID,
        "lookback_trading_days": LOOKBACK_TRADING_DAYS,
        "min_bars_for_score": MIN_BARS_FOR_SCORE,
        "fractal_n": FRACTAL_N,
        "twin_peak_tol": TWIN_PEAK_TOL,
        "twin_trough_min": TWIN_TROUGH_MIN,
        "deep_loser": DEEP_LOSER,
        "large_winner": LARGE_WINNER,
        "normalization": {
            "elev_abs_scale": ELEV_ABS_SCALE,
            "elev_range_scale": ELEV_RANGE_SCALE,
            "near_high_scale": NEAR_HIGH_SCALE,
            "r20_scale": R20_SCALE,
            "rsi_level_floor": RSI_LEVEL_FLOOR,
            "rsi_level_span": RSI_LEVEL_SPAN,
        },
        "weights": dict(FEATURE_WEIGHTS),
        "bands": {
            "PASS": f"< {BAND_WARN_LO}",
            "WARN": f"[{BAND_WARN_LO}, {BAND_SOFT_LO})",
            "SOFT_VETO": f"[{BAND_SOFT_LO}, {BAND_HARD_LO})",
            "HARD_CANDIDATE": f">= {BAND_HARD_LO}",
        },
        "band_cuts": {
            "warn_lo": BAND_WARN_LO,
            "soft_lo": BAND_SOFT_LO,
            "hard_lo": BAND_HARD_LO,
        },
        "note": (
            "Pre-registered before scoring. No grid search / no fit to KLR "
            "on this cohort for admission claims."
        ),
    }


def build_registration_payload(*, generated_at: str | None = None) -> dict[str, Any]:
    return {
        "registration_id": REGISTRATION_ID,
        "recipe_id": RECIPE_ID,
        "deferred_id": DEFERRED_ID,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or _utc_now(),
        "observe_only": True,
        "influences_live": False,
        "learning_question": LEARNING_QUESTION,
        "ops_doc": str(DEFAULT_OPS_DOC),
        "recipe": frozen_recipe_blob(),
        "companion_rules": {
            GRIND_MID60_RULE_ID: {
                "rule_id": GRIND_MID60_RULE_ID,
                "frozen_at": "2026-10-22",
                "rule": f"soft_band==PASS AND mid_range_60 >= {GRIND_MID60_THR}",
                "threshold": GRIND_MID60_THR,
                "lookback_trading_days": GRIND_MID60_LOOKBACK,
                "learning_question": GRIND_MID60_LEARNING_QUESTION,
                "discovery_book": "N206",
                "alone_benefit_primary": "N200",
                "influences_live": False,
            }
        },
        "cohort": {
            "primary": "N200 closed lifecycle episodes with charts",
            "companion_report": "N206 closed for grind mid60 report-only",
            "anecdote": "N210 closed until volume_gate.met",
        },
    }


def build_n215_observe(
    episodes: list[dict[str, Any]],
    *,
    charts_dir: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Pure score over sealed episode dicts."""
    chart_root = Path(charts_dir) if charts_dir is not None else DEFAULT_CHARTS_DIR
    rows: list[dict[str, Any]] = []
    for ep in episodes:
        rows.append(
            score_episode(
                ticker=str(ep["ticker"]),
                book=str(ep.get("book") or "N200"),
                buy_ts=str(ep["buy_ts"]),
                fair_cost=ep.get("fair_cost"),
                charts_dir=chart_root,
            )
        )
    rollup = _rollup_band_catch_miss(rows)
    n200_cov = sum(1 for r in rows if r.get("book") == "N200" and r.get("coverage"))
    n206_rows = [r for r in rows if r.get("book") == "N206"]
    n206_cov = sum(1 for r in n206_rows if r.get("coverage"))
    n210_rows = [r for r in rows if r.get("book") == "N210"]
    grind = (
        rollup.get("companion_grind_mid60")
        if isinstance(rollup.get("companion_grind_mid60"), dict)
        else {}
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "recipe_id": RECIPE_ID,
        "deferred_id": DEFERRED_ID,
        "generated_at": generated_at or _utc_now(),
        "observe_only": True,
        "influences_live": False,
        "learning_question": LEARNING_QUESTION,
        "ops_doc": str(DEFAULT_OPS_DOC),
        "recipe": frozen_recipe_blob(),
        "companion_rules": {
            GRIND_MID60_RULE_ID: {
                "rule_id": GRIND_MID60_RULE_ID,
                "threshold": GRIND_MID60_THR,
                "lookback_trading_days": GRIND_MID60_LOOKBACK,
                "learning_question": GRIND_MID60_LEARNING_QUESTION,
                "influences_live": False,
            }
        },
        "cohort": {
            "N200_closed": rollup["n200_closed"],
            "N200_coverage": n200_cov,
            "N206_closed": len(n206_rows),
            "N206_coverage": n206_cov,
            "N210_closed": len(n210_rows),
            "deep_losers": rollup["deep_losers"],
            "large_winners": rollup["large_winners"],
            "note": (
                "Soft-band catch/miss primary remains N200. N206 scored for "
                f"companion {GRIND_MID60_RULE_ID} report-only (discovery book)."
            ),
        },
        "rollup": rollup,
        "episodes": rows,
        "admit_recommendation": {
            "live_veto": False,
            "any_band_admit_worthy": False,
            "grind_mid60_live_veto": False,
            "note": (
                "Observe success = durable band×catch/miss table. "
                "Progressive admission of a hard gate requires alone net benefit "
                "on a later propose — not claimed from this shadow. "
                f"Companion {GRIND_MID60_RULE_ID}: "
                f"N200 Δsum={((grind.get('N200') or {}).get('delta_fc_sum'))}; "
                "not live."
            ),
        },
    }


def refresh_n215_technical_veto_observe(
    *,
    output_dir: Path | None = None,
    store_path: Path | None = None,
    registration_path: Path | None = None,
    n200_store: Path | None = None,
    n206_store: Path | None = None,
    n210_store: Path | None = None,
    charts_dir: Path | None = None,
    persist: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Load sealed N200/N206/N210 closed episodes + charts; score soft bands.

    Soft-band primary rollup stays N200. N206 is loaded so companion
    ``n215-grind-mid60-pass-v0`` can report discovery/holdout cells (not live).
    """
    data_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    store = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
    reg_path = (
        Path(registration_path) if registration_path is not None else DEFAULT_REGISTRATION_PATH
    )
    n200_path = (
        Path(n200_store) if n200_store is not None else data_dir / "n200_tech_timing_observe.json"
    )
    n206_path = (
        Path(n206_store) if n206_store is not None else data_dir / "n206_plain_ey_observe.json"
    )
    n210_path = (
        Path(n210_store) if n210_store is not None else data_dir / "n210_ai_judgment_observe.json"
    )
    chart_root = Path(charts_dir) if charts_dir is not None else data_dir / "charts"

    episodes = _load_closed_episodes(n200_path, "N200")
    episodes.extend(_load_closed_episodes(n206_path, "N206"))
    episodes.extend(_load_closed_episodes(n210_path, "N210"))
    payload = build_n215_observe(
        episodes,
        charts_dir=chart_root,
        generated_at=generated_at,
    )
    # Fill admit note from rollup (still never live)
    rollup = payload.get("rollup") if isinstance(payload.get("rollup"), dict) else {}
    cum = rollup.get("cumulative_bands") if isinstance(rollup.get("cumulative_bands"), dict) else {}
    soft = cum.get(">=SOFT_VETO") if isinstance(cum.get(">=SOFT_VETO"), dict) else {}
    hard = cum.get(">=HARD_CANDIDATE") if isinstance(cum.get(">=HARD_CANDIDATE"), dict) else {}
    deep_n = int(rollup.get("deep_losers") or 0)
    large_n = int(rollup.get("large_winners") or 0)
    soft_catch = int(soft.get("deep_n") or 0)
    soft_miss = int(soft.get("large_n") or 0)
    hard_catch = int(hard.get("deep_n") or 0)
    hard_miss = int(hard.get("large_n") or 0)
    # Heuristic observe read only — not an admit claim
    any_worthy = False
    note_bits = [
        f"SOFT_VETO+ catch {soft_catch}/{deep_n} miss {soft_miss}/{large_n};",
        f"HARD_CANDIDATE+ catch {hard_catch}/{deep_n} miss {hard_miss}/{large_n}.",
    ]
    if deep_n > 0 and large_n > 0:
        # Alone net-benefit sketch: catch rate > miss rate and catch >= half deep set
        soft_ok = soft_catch / deep_n > soft_miss / large_n and soft_catch >= max(1, deep_n // 2)
        hard_ok = hard_catch / deep_n > hard_miss / large_n and hard_catch >= max(1, deep_n // 2)
        any_worthy = bool(soft_ok or hard_ok)
        if any_worthy:
            note_bits.append(
                "Observe sketch only — still NOT live-admit; needs progressive propose."
            )
        else:
            note_bits.append("No band clears even an observe sketch net-benefit bar.")
    payload["admit_recommendation"] = {
        "live_veto": False,
        "any_band_admit_worthy": False,  # hard lock: this slice never admits live
        "observe_sketch_band_looks_interesting": any_worthy,
        "note": " ".join(note_bits),
    }

    registration = build_registration_payload(generated_at=payload["generated_at"])
    if persist:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(registration, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_findings_from_n215_observe(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Map observe store → ops-monitor finding dicts (warn-only)."""
    cohort = payload.get("cohort") if isinstance(payload.get("cohort"), dict) else {}
    rollup = payload.get("rollup") if isinstance(payload.get("rollup"), dict) else {}
    cum = rollup.get("cumulative_bands") if isinstance(rollup.get("cumulative_bands"), dict) else {}
    soft = cum.get(">=SOFT_VETO") if isinstance(cum.get(">=SOFT_VETO"), dict) else {}
    hard_cmp = (
        rollup.get("hard_rule_companion")
        if isinstance(rollup.get("hard_rule_companion"), dict)
        else {}
    )
    any6 = hard_cmp.get("any_of_six") if isinstance(hard_cmp.get("any_of_six"), dict) else {}
    grind = (
        rollup.get("companion_grind_mid60")
        if isinstance(rollup.get("companion_grind_mid60"), dict)
        else {}
    )
    g200 = grind.get("N200") if isinstance(grind.get("N200"), dict) else {}
    admit = (
        payload.get("admit_recommendation")
        if isinstance(payload.get("admit_recommendation"), dict)
        else {}
    )
    return [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"{REGISTRATION_ID}: N200 closed={cohort.get('N200_closed')}; "
                f"deep={cohort.get('deep_losers')} large={cohort.get('large_winners')}; "
                f"SOFT_VETO+ catch={soft.get('deep_catch')} miss={soft.get('large_miss')}; "
                f"hard any-of-six catch={any6.get('deep_catch')} miss={any6.get('large_miss')}. "
                f"{GRIND_MID60_RULE_ID}: N200 catch={g200.get('deep_catch')} "
                f"miss={g200.get('large_miss')} Δsum={g200.get('delta_fc_sum')}. "
                f"live_veto={admit.get('live_veto')} "
                f"observe_sketch_interesting={admit.get('observe_sketch_band_looks_interesting')}. "
                "Observe-only — no live writes (F8)."
            ),
            "auto_fixable": False,
        }
    ]


def format_n215_observe_text(payload: dict[str, Any]) -> str:
    cohort = payload.get("cohort") if isinstance(payload.get("cohort"), dict) else {}
    rollup = payload.get("rollup") if isinstance(payload.get("rollup"), dict) else {}
    cum = rollup.get("cumulative_bands") if isinstance(rollup.get("cumulative_bands"), dict) else {}
    excl = rollup.get("exclusive_bands") if isinstance(rollup.get("exclusive_bands"), dict) else {}
    hard = (
        rollup.get("hard_rule_companion")
        if isinstance(rollup.get("hard_rule_companion"), dict)
        else {}
    )
    admit = (
        payload.get("admit_recommendation")
        if isinstance(payload.get("admit_recommendation"), dict)
        else {}
    )
    lines = [
        f"N215 {payload.get('registration_id')} (observe-only soft-band)",
        f"recipe={payload.get('recipe_id')} influences_live={payload.get('influences_live')}",
        (
            f"cohort N200={cohort.get('N200_closed')} "
            f"(cov={cohort.get('N200_coverage')}) "
            f"N210={cohort.get('N210_closed')} "
            f"deep={cohort.get('deep_losers')} large={cohort.get('large_winners')}"
        ),
        "exclusive bands (deep catch / large miss):",
    ]
    for band in BAND_ORDER:
        cell = excl.get(band) if isinstance(excl.get(band), dict) else {}
        lines.append(
            f"  {band}: catch {cell.get('deep_catch')} miss {cell.get('large_miss')} "
            f"(all={cell.get('all_n200')})"
        )
    lines.append("cumulative:")
    for key in (">=WARN", ">=SOFT_VETO", ">=HARD_CANDIDATE"):
        cell = cum.get(key) if isinstance(cum.get(key), dict) else {}
        lines.append(
            f"  {key}: catch {cell.get('deep_catch')} miss {cell.get('large_miss')} "
            f"(all={cell.get('all_n200')})"
        )
    i01 = hard.get("I01_or_I02") if isinstance(hard.get("I01_or_I02"), dict) else {}
    any6 = hard.get("any_of_six") if isinstance(hard.get("any_of_six"), dict) else {}
    lines.append(f"hard I01|I02: catch {i01.get('deep_catch')} miss {i01.get('large_miss')}")
    lines.append(f"hard any-of-six: catch {any6.get('deep_catch')} miss {any6.get('large_miss')}")
    grind = (
        rollup.get("companion_grind_mid60")
        if isinstance(rollup.get("companion_grind_mid60"), dict)
        else {}
    )
    g200 = grind.get("N200") if isinstance(grind.get("N200"), dict) else {}
    g206 = grind.get("N206") if isinstance(grind.get("N206"), dict) else {}
    lines.append(
        f"companion {GRIND_MID60_RULE_ID}: "
        f"N200 catch {g200.get('deep_catch')} miss {g200.get('large_miss')} "
        f"Δsum={g200.get('delta_fc_sum')}; "
        f"N206 report catch {g206.get('deep_catch')} miss {g206.get('large_miss')} "
        f"Δsum={g206.get('delta_fc_sum')}"
    )
    lines.append(f"admit: {admit.get('note')}")
    return "\n".join(lines) + "\n"
