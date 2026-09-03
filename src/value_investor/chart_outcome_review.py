"""Observe-only buy-tier chart outcome rollup from frozen initial levels."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from value_investor.storage import read_json, write_json


def _as_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text[:10]


def _round_price(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return round(number, 2)

REVIEW_FILENAME = "chart_outcome_review.json"
REVIEW_MD_FILENAME = "chart_outcome_review.md"

TERRIBLE_RETURN = -0.15
TERRIBLE_DRAWDOWN = -0.25
STOP_TERRIBLE_RETURN = -0.10
WELL_TIMED_RETURN = 0.05
WELL_TIMED_MAX_DRAWDOWN = -0.08

OUTCOME_WELL_TIMED = "well_timed"
OUTCOME_GIVEBACK = "giveback"
OUTCOME_UNDERWATER = "underwater"
OUTCOME_INTACT_POSITIVE = "intact_positive"
OUTCOME_FLAT = "flat"
OUTCOME_TERRIBLE = "terrible"
OUTCOME_INSUFFICIENT = "insufficient_data"

VERDICT_MIXED_NO_TERRIBLE = "mixed_no_terrible"
VERDICT_CONSTRUCTIVE = "constructive"
VERDICT_HAS_TERRIBLE = "has_terrible"
VERDICT_MIXED = "mixed"
VERDICT_EMPTY = "empty"

VERDICT_LABELS = {
    VERDICT_MIXED_NO_TERRIBLE: "Mixed story — no terrible outcomes",
    VERDICT_CONSTRUCTIVE: "Constructive — well timed, no terrible outcomes",
    VERDICT_HAS_TERRIBLE: "Has terrible outcomes",
    VERDICT_MIXED: "Mixed",
    VERDICT_EMPTY: "No buy-tier charts",
}


def _crossing(payload: dict[str, Any], key: str) -> dict[str, Any]:
    for row in payload.get("level_crossings") or []:
        if isinstance(row, dict) and str(row.get("key") or "") == key:
            return row
    return {}


def _hit(crossing: dict[str, Any], *, direction: str | None = None) -> bool:
    if not crossing.get("date"):
        return False
    if direction and str(crossing.get("direction") or "") != direction:
        return False
    return True


def _pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _days_between(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        first = datetime.fromisoformat(start)
        last = datetime.fromisoformat(end)
    except ValueError:
        return None
    return max(0, (last - first).days)


def score_chart_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Score one buy-tier chart against frozen recommendation levels."""
    dates = [str(d)[:10] for d in (payload.get("dates") or [])]
    closes_raw = payload.get("closes") or []
    closes: list[float] = []
    for value in closes_raw:
        price = _round_price(value)
        if price is None:
            closes.append(float("nan"))
        else:
            closes.append(price)
    pairs = [
        (date, close)
        for date, close in zip(dates, closes, strict=False)
        if date and close == close
    ]
    since = _as_date(payload.get("initial_levels_as_of") or payload.get("signal_since"))
    initial = payload.get("initial_levels") if isinstance(payload.get("initial_levels"), dict) else {}
    entry = _round_price((initial or {}).get("last"))
    after = [(date, close) for date, close in pairs if not since or date >= since]
    if entry is None and after:
        entry = after[0][1]
    last = pairs[-1][1] if pairs else None
    min_close = min((close for _, close in after), default=None)
    max_close = max((close for _, close in after), default=None)
    return_since = ((last / entry) - 1.0) if entry and last else None
    max_drawdown = ((min_close / entry) - 1.0) if entry and min_close else None
    runup = ((max_close / entry) - 1.0) if entry and max_close else None

    stop = _crossing(payload, "stop_loss")
    target = _crossing(payload, "take_profit")
    stop_hit = _hit(stop, direction="down")
    target_hit = _hit(target, direction="up")

    outcome = classify_chart_outcome(
        return_since=return_since,
        max_drawdown=max_drawdown,
        stop_hit=stop_hit,
        target_hit=target_hit,
        has_entry=entry is not None,
    )
    return {
        "ticker": payload.get("ticker"),
        "name": payload.get("name") or payload.get("ticker"),
        "signal": payload.get("signal"),
        "signal_since": _as_date(payload.get("signal_since")),
        "initial_levels_as_of": _as_date(payload.get("initial_levels_as_of")),
        "entry": entry,
        "last": last,
        "return_since": _pct(return_since),
        "max_drawdown": _pct(max_drawdown),
        "runup": _pct(runup),
        "stop_hit": stop_hit,
        "target_hit": target_hit,
        "stop_date": _as_date(stop.get("date")),
        "target_date": _as_date(target.get("date")),
        "days_to_target": _days_between(since, _as_date(target.get("date"))) if target_hit else None,
        "bars_since": len(after),
        "has_initial_levels": bool(initial),
        "outcome": outcome,
    }


def classify_chart_outcome(
    *,
    return_since: float | None,
    max_drawdown: float | None,
    stop_hit: bool,
    target_hit: bool,
    has_entry: bool,
) -> str:
    """Label one recommendation path. Terrible is reserved for large losses / stop blows."""
    if not has_entry or return_since is None:
        return OUTCOME_INSUFFICIENT
    drawdown = max_drawdown if max_drawdown is not None else 0.0
    if return_since <= TERRIBLE_RETURN or drawdown <= TERRIBLE_DRAWDOWN:
        return OUTCOME_TERRIBLE
    if stop_hit and return_since <= STOP_TERRIBLE_RETURN:
        return OUTCOME_TERRIBLE
    if target_hit and not stop_hit and return_since >= 0 and drawdown > WELL_TIMED_MAX_DRAWDOWN:
        return OUTCOME_WELL_TIMED
    if return_since >= WELL_TIMED_RETURN and drawdown > WELL_TIMED_MAX_DRAWDOWN:
        return OUTCOME_WELL_TIMED
    if target_hit and return_since < 0:
        return OUTCOME_GIVEBACK
    if return_since < 0:
        return OUTCOME_UNDERWATER
    if return_since > 0:
        return OUTCOME_INTACT_POSITIVE
    return OUTCOME_FLAT


def verdict_from_counts(counts: dict[str, int]) -> str:
    chart_count = int(counts.get("chart_count") or 0)
    if chart_count == 0:
        return VERDICT_EMPTY
    terrible = int(counts.get(OUTCOME_TERRIBLE) or 0)
    well_timed = int(counts.get(OUTCOME_WELL_TIMED) or 0)
    faded = int(counts.get(OUTCOME_GIVEBACK) or 0) + int(counts.get(OUTCOME_UNDERWATER) or 0)
    if terrible > 0:
        return VERDICT_HAS_TERRIBLE
    if well_timed > 0 and faded > 0:
        return VERDICT_MIXED_NO_TERRIBLE
    if well_timed > 0:
        return VERDICT_CONSTRUCTIVE
    return VERDICT_MIXED


def load_chart_payloads(chart_dir: Path) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    if not chart_dir.exists():
        return payloads
    for path in sorted(chart_dir.glob("*.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("ticker"):
            payloads.append(payload)
    return payloads


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return _pct(float(median(values)))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return _pct(sum(values) / len(values))


def build_chart_outcome_review(
    *,
    chart_dir: Path,
    run_at: datetime | None = None,
) -> dict[str, Any]:
    rows = [score_chart_payload(payload) for payload in load_chart_payloads(Path(chart_dir))]
    rows.sort(key=lambda row: (str(row.get("outcome") or ""), str(row.get("ticker") or "")))
    outcome_counts = {
        OUTCOME_WELL_TIMED: 0,
        OUTCOME_GIVEBACK: 0,
        OUTCOME_UNDERWATER: 0,
        OUTCOME_INTACT_POSITIVE: 0,
        OUTCOME_FLAT: 0,
        OUTCOME_TERRIBLE: 0,
        OUTCOME_INSUFFICIENT: 0,
    }
    for row in rows:
        key = str(row.get("outcome") or OUTCOME_INSUFFICIENT)
        if key not in outcome_counts:
            outcome_counts[key] = 0
        outcome_counts[key] += 1

    returns = [float(row["return_since"]) for row in rows if row.get("return_since") is not None]
    drawdowns = [float(row["max_drawdown"]) for row in rows if row.get("max_drawdown") is not None]
    counts = {
        "chart_count": len(rows),
        **outcome_counts,
        "stop_hit": sum(1 for row in rows if row.get("stop_hit")),
        "target_hit": sum(1 for row in rows if row.get("target_hit")),
        "missing_initial_levels": sum(1 for row in rows if not row.get("has_initial_levels")),
        "positive": sum(1 for value in returns if value > 0),
        "negative": sum(1 for value in returns if value < 0),
        "flat": sum(1 for value in returns if value == 0),
    }
    verdict = verdict_from_counts(counts)
    well_timed = sorted(
        [row for row in rows if row.get("outcome") == OUTCOME_WELL_TIMED],
        key=lambda row: float(row.get("return_since") or 0),
        reverse=True,
    )
    weakest = sorted(
        [row for row in rows if row.get("return_since") is not None],
        key=lambda row: float(row.get("return_since") or 0),
    )[:8]
    headline = _headline(verdict, counts, well_timed)
    return {
        "schema_version": 1,
        "scope": "chart_outcome_review",
        "observe_only": True,
        "generated_at": (run_at or datetime.now(UTC)).isoformat(),
        "verdict": verdict,
        "verdict_label": VERDICT_LABELS.get(verdict, verdict),
        "headline": headline,
        "counts": counts,
        "stats": {
            "median_return": _median(returns),
            "mean_return": _mean(returns),
            "min_return": _pct(min(returns)) if returns else None,
            "max_return": _pct(max(returns)) if returns else None,
            "median_drawdown": _median(drawdowns),
            "worst_drawdown": _pct(min(drawdowns)) if drawdowns else None,
        },
        "well_timed": well_timed[:8],
        "weakest": weakest,
        "rows": rows,
        "note": (
            "Observe-only rollup of buy-tier chart JSON. Entry is the frozen initial last "
            "(recommendation-week close), not the first bar after signal_since. Short-term "
            "underwater is expected while the hypothesis stands — the test is the longer path. "
            "Do not apply decision-review knobs or entry-timing overlays from this file."
        ),
    }


def _headline(verdict: str, counts: dict[str, int], well_timed: list[dict[str, Any]]) -> str:
    names = ", ".join(
        f"{row.get('ticker')} ({_fmt_pct(row.get('return_since'))})" for row in well_timed[:3]
    )
    if verdict == VERDICT_EMPTY:
        return "No buy-tier chart payloads to score."
    if verdict == VERDICT_HAS_TERRIBLE:
        return (
            f"{counts.get(OUTCOME_TERRIBLE, 0)} terrible path(s) among {counts.get('chart_count', 0)} "
            "buy-tier charts — inspect weakest names before treating timing as benign."
        )
    if names:
        return (
            f"{VERDICT_LABELS[verdict]}. "
            f"{counts.get(OUTCOME_WELL_TIMED, 0)} well timed"
            f"{f' (including {names})' if names else ''}; "
            f"{counts.get(OUTCOME_GIVEBACK, 0)} target-then-fade; "
            f"{counts.get(OUTCOME_UNDERWATER, 0)} underwater; "
            f"{counts.get('stop_hit', 0)} stop hits."
        )
    return (
        f"{VERDICT_LABELS[verdict]}. "
        f"{counts.get('chart_count', 0)} charts, {counts.get('stop_hit', 0)} stop hits."
    )


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.1f}%"


def format_chart_outcome_markdown(payload: dict[str, Any]) -> str:
    counts = payload.get("counts") or {}
    stats = payload.get("stats") or {}
    lines = [
        "# Buy-tier chart outcomes",
        "",
        payload.get("headline") or "",
        "",
        f"**Verdict:** {payload.get('verdict_label') or payload.get('verdict')} "
        f"(`{payload.get('verdict')}`)",
        "",
        "Observe-only. Frozen initial recommendation levels + first crossings. "
        "Not a decision-review input.",
        "",
        "Short-term underwater is expected while the hypothesis stands. "
        "The test is the longer path — do not retune entry timing from this mix.",
        "",
        "## Counts",
        "",
        f"- Charts: {counts.get('chart_count', 0)}",
        f"- Well timed: {counts.get(OUTCOME_WELL_TIMED, 0)}",
        f"- Target then fade: {counts.get(OUTCOME_GIVEBACK, 0)}",
        f"- Underwater (no target): {counts.get(OUTCOME_UNDERWATER, 0)}",
        f"- Intact positive: {counts.get(OUTCOME_INTACT_POSITIVE, 0)}",
        f"- Flat: {counts.get(OUTCOME_FLAT, 0)}",
        f"- Terrible: {counts.get(OUTCOME_TERRIBLE, 0)}",
        f"- Stop hits: {counts.get('stop_hit', 0)}",
        f"- Target hits: {counts.get('target_hit', 0)}",
        "",
        "## Returns since recommendation",
        "",
        f"- Median: {_fmt_pct(stats.get('median_return'))}",
        f"- Mean: {_fmt_pct(stats.get('mean_return'))}",
        f"- Range: {_fmt_pct(stats.get('min_return'))} to {_fmt_pct(stats.get('max_return'))}",
        f"- Median drawdown: {_fmt_pct(stats.get('median_drawdown'))}",
        f"- Worst drawdown: {_fmt_pct(stats.get('worst_drawdown'))}",
        "",
        "## Well timed",
        "",
    ]
    well_timed = payload.get("well_timed") or []
    if not well_timed:
        lines.append("_None this pass._")
    else:
        lines.append("| Ticker | Signal | Return | Drawdown | Days to target |")
        lines.append("|---|---|---:|---:|---:|")
        for row in well_timed:
            lines.append(
                f"| {row.get('ticker')} | {row.get('signal')} | "
                f"{_fmt_pct(row.get('return_since'))} | {_fmt_pct(row.get('max_drawdown'))} | "
                f"{row.get('days_to_target') if row.get('days_to_target') is not None else '—'} |"
            )
    lines.extend(["", "## Weakest open returns", ""])
    weakest = payload.get("weakest") or []
    if not weakest:
        lines.append("_None this pass._")
    else:
        lines.append("| Ticker | Signal | Return | Drawdown | Outcome | Stop | Target |")
        lines.append("|---|---|---:|---:|---|---|---|")
        for row in weakest:
            lines.append(
                f"| {row.get('ticker')} | {row.get('signal')} | "
                f"{_fmt_pct(row.get('return_since'))} | {_fmt_pct(row.get('max_drawdown'))} | "
                f"{row.get('outcome')} | "
                f"{'yes' if row.get('stop_hit') else 'no'} | "
                f"{'yes' if row.get('target_hit') else 'no'} |"
            )
    if payload.get("note"):
        lines.extend(["", f"_{payload['note']}_", ""])
    return "\n".join(lines) + "\n"


def slim_chart_outcome_review(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact chart-outcome context for analysis-review — no full row dump."""
    if not isinstance(payload, dict):
        return None

    def _slim_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "ticker": row.get("ticker"),
            "signal": row.get("signal"),
            "return_since": row.get("return_since"),
            "max_drawdown": row.get("max_drawdown"),
            "outcome": row.get("outcome"),
            "target_hit": row.get("target_hit"),
            "stop_hit": row.get("stop_hit"),
            "days_to_target": row.get("days_to_target"),
        }

    return {
        "purpose": (
            "Buy-tier chart timing vs frozen initial levels — observe-only context. "
            "Do not propose knob applies or scoring experiments from this alone."
        ),
        "observe_only": True,
        "verdict": payload.get("verdict"),
        "verdict_label": payload.get("verdict_label"),
        "headline": payload.get("headline"),
        "counts": payload.get("counts"),
        "stats": payload.get("stats"),
        "well_timed": [_slim_row(row) for row in (payload.get("well_timed") or [])[:6]],
        "weakest": [_slim_row(row) for row in (payload.get("weakest") or [])[:6]],
        "note": payload.get("note"),
    }


def run_chart_outcome_review(
    *,
    data_dir: Path = Path("docs/data"),
    chart_dir: Path | None = None,
    run_at: datetime | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    source = Path(chart_dir) if chart_dir is not None else data_dir / "charts"
    payload = build_chart_outcome_review(chart_dir=source, run_at=run_at)
    write_json(data_dir / REVIEW_FILENAME, payload, compact=True)
    (data_dir / REVIEW_MD_FILENAME).write_text(
        format_chart_outcome_markdown(payload), encoding="utf-8"
    )
    return payload


__all__ = [
    "REVIEW_FILENAME",
    "REVIEW_MD_FILENAME",
    "build_chart_outcome_review",
    "classify_chart_outcome",
    "format_chart_outcome_markdown",
    "run_chart_outcome_review",
    "score_chart_payload",
    "slim_chart_outcome_review",
    "verdict_from_counts",
]
