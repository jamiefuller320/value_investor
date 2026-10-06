"""Single scoreboard for the paper learning tracks under the assessment model.

Replaces the dual-suite (stress A vs fair B) view with one table on one fair
cost basis. For every active track it shows:

- total return (dividends credited) vs ``FTAL.L`` total return, on the clean
  epoch when a fair book still carries early stress-cost trades
  (``total_return_view.json``);
- the 90% interval and verdict on annualised active return from
  ``track_statistics.json`` (daily price NAV vs the price index; the interval is
  the uncertainty band, the total-return columns are the level);
- the same excess with every trade in the window re-priced at a 3% per-side
  stress cost, as a cost-sensitivity column;
- whether the AI research gate binds (share of the buy tier it lets through,
  from ``screen_premise_backtest.json``);
- the primary vs control difference on their common window.

Frozen books are listed with their final record from ``assessment_model.json``.
Daily ops-monitor refreshes ``docs/data/assessment_scoreboard.json`` after the
stores it reads. Never changes books, knobs or gates.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")
DEFAULT_STORE_PATH = Path("docs/data/assessment_scoreboard.json")
TOTAL_RETURN_VIEW_FILENAME = "total_return_view.json"
TRACK_STATISTICS_FILENAME = "track_statistics.json"
SCREEN_PREMISE_FILENAME = "screen_premise_backtest.json"
FUND_FILENAME = "automated_fund.json"
CONFIG_FILENAME = "config.json"

STRESS_COST_PER_SIDE = 0.03
GATE_BINDS_BELOW_PASS_SHARE = 0.8
PRIMARY_CONTROL_GAP = 0.05

FINDING_TITLE = "Primary book trails its control on total return"
STORE_FAILED_TITLE = "Assessment scoreboard observe failed"


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def stress_cost_sensitivity(
    trades: list[dict[str, Any]],
    *,
    start: datetime | None,
    end: datetime | None,
    base_capital: float | None,
) -> dict[str, Any] | None:
    """Extra cost (as a share of base capital) if every window trade paid 3% per side."""
    if not base_capital or base_capital <= 0 or start is None or end is None:
        return None
    gross = 0.0
    paid = 0.0
    count = 0
    for trade in trades:
        at = _parse_dt(trade.get("acted_at"))
        if at is None or at <= start or at > end:
            continue
        gross += abs(float(trade.get("gross") or 0.0))
        paid += float(trade.get("cost") or 0.0)
        count += 1
    stress = gross * STRESS_COST_PER_SIDE
    return {
        "trades": count,
        "turnover": round(gross / base_capital, 3),
        "costs_paid_pct": round(paid / base_capital, 4),
        "costs_at_stress_pct": round(stress / base_capital, 4),
        "extra_drag_at_stress": round(max(0.0, stress - paid) / base_capital, 4),
    }


def gate_status(config: dict[str, Any], screen_premise: dict[str, Any]) -> dict[str, Any]:
    """Does this track's AI research gate actually filter the buy tier?"""
    if not config.get("require_research_accumulate"):
        return {"gate": None, "binds": None}
    shares = [
        horizon.get("ai_gate_pass_share")
        for horizon in (screen_premise.get("horizons") or {}).values()
        if isinstance(horizon, dict) and horizon.get("ai_gate_pass_share") is not None
    ]
    pass_share = shares[0] if shares else None
    return {
        "gate": "research_verdict == accumulate",
        "min_conviction": config.get("min_conviction"),
        "buy_tier_pass_share": pass_share,
        "binds": None if pass_share is None else pass_share < GATE_BINDS_BELOW_PASS_SHARE,
    }


def _statistics_row(stats: dict[str, Any]) -> dict[str, Any]:
    if stats.get("status") != "ok":
        return {"status": stats.get("status") or "missing", "periods": stats.get("periods")}
    return {
        "status": "ok",
        "vs": stats.get("vs"),
        "annualized_active_return": stats.get("annualized_active_return"),
        "ci90": stats.get("ci_annualized_active_return"),
        "verdict": stats.get("verdict"),
        "years_to_detect_3pct_edge": stats.get("years_to_detect_target_edge"),
    }


def _role(track_id: str, primary: str, control: str) -> str:
    if track_id == primary:
        return "primary"
    if track_id == control:
        return "control"
    return "active"


def build_assessment_scoreboard(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    paper_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    from value_investor.assessment_model import load_assessment_model
    from value_investor.paper_automation import learning_track_dirs

    data_dir = Path(data_dir)
    root = Path(paper_root) if paper_root is not None else data_dir / "paper_automation"
    model = load_assessment_model(root)
    primary = str(model.get("primary_track") or "ai_judgment")
    control = str(model.get("control_track") or "rules")
    frozen = model.get("frozen_tracks") or {}
    total_return = _read(data_dir / TOTAL_RETURN_VIEW_FILENAME)
    statistics = _read(data_dir / TRACK_STATISTICS_FILENAME)
    screen_premise = _read(data_dir / SCREEN_PREMISE_FILENAME)
    tr_tracks = total_return.get("tracks") or {}
    stat_tracks = statistics.get("tracks") or {}

    rows: list[dict[str, Any]] = []
    for track_id, track_dir in sorted(learning_track_dirs(root).items()):
        if track_id in frozen:
            continue
        entry = tr_tracks.get(track_id) or {}
        view = entry.get("clean_epoch") or entry.get("lifetime") or {}
        config = _read(Path(track_dir) / CONFIG_FILENAME)
        fund = _read(Path(track_dir) / FUND_FILENAME)
        sensitivity = stress_cost_sensitivity(
            [t for t in fund.get("trades") or [] if isinstance(t, dict)],
            start=_parse_dt(view.get("start")),
            end=_parse_dt(view.get("end")),
            base_capital=view.get("base_capital"),
        )
        excess = view.get("excess_total_return")
        rows.append(
            {
                "track_id": track_id,
                "role": _role(track_id, primary, control),
                "label": config.get("track_label"),
                "basis": "clean_epoch" if entry.get("clean_epoch") else "lifetime",
                "start": view.get("start"),
                "end": view.get("end"),
                "marks": view.get("marks"),
                "total_return": view.get("total_return"),
                "benchmark_total_return": view.get("benchmark_total_return"),
                "excess_total_return": excess,
                "dividends_gbp": view.get("dividends_gbp"),
                "excess_total_return_at_stress_cost": (
                    None
                    if excess is None or sensitivity is None
                    else round(excess - sensitivity["extra_drag_at_stress"], 4)
                ),
                "cost_sensitivity": sensitivity,
                "statistics": _statistics_row(stat_tracks.get(track_id) or {}),
                "ai_gate": gate_status(config, screen_premise),
                "configured_buy_cost_pct": config.get("buy_cost_pct"),
            }
        )
    order = {"primary": 0, "control": 1, "active": 2}
    rows.sort(key=lambda row: (order[row["role"]], row["track_id"]))

    comparison = None
    for pair in (total_return.get("pairs") or {}).values():
        if (pair.get("left"), pair.get("right")) == (primary, control):
            comparison = {
                "primary": primary,
                "control": control,
                "start": pair.get("start"),
                "primary_total_return": pair.get("left_total_return"),
                "control_total_return": pair.get("right_total_return"),
                "difference": pair.get("difference"),
                "note": (
                    "Common window, total return. Positive means the primary's filter "
                    "added value over the unfiltered buy tier. Not yet tested for "
                    "significance."
                ),
            }

    frozen_rows = []
    for track_id, record in sorted(frozen.items()):
        lifetime = (tr_tracks.get(track_id) or {}).get("lifetime") or {}
        frozen_rows.append(
            {
                "track_id": track_id,
                "frozen_at": record.get("frozen_at"),
                "reason": record.get("reason"),
                "superseded_by": record.get("superseded_by"),
                "final_nav": record.get("final_nav"),
                "final_contributed_capital": record.get("final_contributed_capital"),
                "trade_count": record.get("trade_count"),
                "lifetime_total_return": lifetime.get("total_return"),
                "lifetime_excess_total_return": lifetime.get("excess_total_return"),
            }
        )

    return {
        "schema_version": 1,
        "generated_at": (now or datetime.now(UTC)).isoformat(),
        "observe_only": True,
        "primary_track": primary,
        "control_track": control,
        "benchmark": (total_return.get("benchmarks") or {}).get("total_return") or "FTAL.L",
        "stress_cost_per_side": STRESS_COST_PER_SIDE,
        "sources": {
            "total_return_view_updated_at": total_return.get("updated_at"),
            "track_statistics_updated_at": statistics.get("updated_at"),
            "screen_premise_generated_at": screen_premise.get("generated_at"),
        },
        "headline": headline(rows, comparison),
        "tracks": rows,
        "primary_vs_control": comparison,
        "frozen_tracks": frozen_rows,
    }


def _pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):+.1%}"


def headline(rows: list[dict[str, Any]], comparison: dict[str, Any] | None) -> str:
    primary = next((row for row in rows if row["role"] == "primary"), None)
    if primary is None or primary.get("total_return") is None:
        return "Primary book has no scored window yet."
    stats = primary.get("statistics") or {}
    verdict = {
        "positive": "ahead of the market with 90% confidence",
        "negative": "behind the market with 90% confidence",
        "indistinguishable_from_noise": "not yet distinguishable from the market",
    }.get(str(stats.get("verdict")), "too few marks to judge")
    text = (
        f"{primary['track_id']}: total return {_pct(primary['total_return'])} vs "
        f"FTAL.L {_pct(primary.get('benchmark_total_return'))} since "
        f"{str(primary.get('start') or '')[:10]} — {verdict}."
    )
    if comparison and comparison.get("difference") is not None:
        text += (
            f" vs {comparison['control']}: {_pct(comparison['difference'])} on the common window."
        )
    return text


def refresh_assessment_scoreboard(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    persist: bool = True,
) -> dict[str, Any]:
    payload = build_assessment_scoreboard(data_dir)
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_finding_from_assessment_scoreboard(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Warn when the primary trails its control by ≥5pp total return on the common window."""
    comparison = payload.get("primary_vs_control") or {}
    difference = comparison.get("difference")
    if difference is None or difference > -PRIMARY_CONTROL_GAP:
        return None
    return {
        "severity": "warn",
        "category": "paper",
        "title": FINDING_TITLE,
        "summary": (
            f"{comparison['primary']} total return {_pct(comparison.get('primary_total_return'))} "
            f"vs {comparison['control']} {_pct(comparison.get('control_total_return'))} since "
            f"{str(comparison.get('start') or '')[:10]} ({_pct(difference)}). The primary's "
            "filter is costing return against the unfiltered buy tier. Observe-only: do not "
            "change the primary from this alone. See docs/ops/assessment-scoreboard.md."
        ),
        "auto_fixable": False,
    }
