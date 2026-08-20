"""Forward endurance ledger for competing calibrated shadow sims (observe-only)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.knob_calibration import (
    CALIBRATION_PROVENANCE_FILENAME,
    calibrated_shadow_subdir,
    calibrated_shadow_track_id,
    discover_calibration_shadow_ranks,
    load_calibration_provenance,
)
from value_investor.paper_automation import (
    AI_JUDGMENT_TRACK_ID,
    CONFIG_FILENAME,
    FUND_FILENAME,
    RULES_TRACK_ID,
    AutomationConfig,
    learning_track_dirs,
)
from value_investor.paper_fund import PaperFund
from value_investor.storage import read_json, write_json

ENDURANCE_FILENAME = "calibration_shadow_endurance.json"
DEFAULT_MIN_MARKS_FOR_SURVIVOR = 4
DEFAULT_MIN_EXCESS_VS_MARKET = 0.0


def _fund_metrics_snapshot(track_dir: Path) -> dict[str, Any]:
    review_path = track_dir / "decision_review.json"
    if review_path.exists():
        payload = read_json(review_path)
        metrics = payload.get("metrics") or {}
        epoch = metrics.get("epoch") if isinstance(metrics.get("epoch"), dict) else {}
        return {
            "total_return": metrics.get("total_return"),
            "cost_drag": metrics.get("cost_drag"),
            "excess_after_costs": metrics.get("excess_after_costs"),
            "equity_marks": metrics.get("equity_marks"),
            "trade_count": metrics.get("trade_count"),
            "epoch_excess_after_costs": epoch.get("excess_after_costs"),
            "source": "decision_review",
        }

    fund_path = track_dir / FUND_FILENAME
    if not fund_path.exists():
        return {"source": "missing"}
    fund = PaperFund.from_dict(read_json(fund_path))
    marks = len(fund.equity_curve or [])
    perf = fund.performance({})
    return {
        "total_return": perf.get("total_return"),
        "cost_drag": None,
        "excess_after_costs": None,
        "equity_marks": marks,
        "trade_count": len(fund.trades or []),
        "epoch_excess_after_costs": None,
        "source": "fund",
    }


def _classify_status(
    *,
    marks: int | None,
    excess: float | None,
    vs_primary: float | None,
    vs_rules: float | None,
    min_marks: int,
    min_excess: float,
) -> str:
    if marks is None or marks < 2:
        return "observing"
    if excess is None:
        return "observing"
    if marks < min_marks:
        return "observing"
    beats_market = float(excess) >= float(min_excess)
    beats_rules = vs_rules is None or float(vs_rules) >= 0.0
    beats_primary = vs_primary is None or float(vs_primary) >= 0.0
    if beats_market and beats_rules:
        return "surviving" if beats_primary or beats_market else "surviving"
    if float(excess) < float(min_excess) - 0.02:
        return "failed"
    return "observing"


def refresh_calibration_endurance(
    paper_root: Path,
    *,
    min_marks_for_survivor: int = DEFAULT_MIN_MARKS_FOR_SURVIVOR,
    min_excess_vs_market: float = DEFAULT_MIN_EXCESS_VS_MARKET,
) -> dict[str, Any]:
    """
    Build/update an observe-only endurance ledger for calibrated shadows.

    Survivors are flagged for human review as learning-loop starting priors —
    never auto-applied.
    """
    paper_root = Path(paper_root)
    dirs = learning_track_dirs(paper_root)
    primary_metrics = (
        _fund_metrics_snapshot(dirs[AI_JUDGMENT_TRACK_ID])
        if AI_JUDGMENT_TRACK_ID in dirs
        else {}
    )
    rules_metrics = (
        _fund_metrics_snapshot(dirs[RULES_TRACK_ID]) if RULES_TRACK_ID in dirs else {}
    )
    primary_excess = primary_metrics.get("excess_after_costs")
    rules_excess = rules_metrics.get("excess_after_costs")

    ranks = discover_calibration_shadow_ranks(paper_root)
    shadows: list[dict[str, Any]] = []
    for rank in ranks:
        track_id = calibrated_shadow_track_id(rank)
        track_dir = paper_root / calibrated_shadow_subdir(rank)
        provenance = load_calibration_provenance(track_dir) or {}
        metrics = _fund_metrics_snapshot(track_dir)
        excess = metrics.get("excess_after_costs")
        vs_primary = None
        vs_rules = None
        if excess is not None and primary_excess is not None:
            vs_primary = round(float(excess) - float(primary_excess), 4)
        if excess is not None and rules_excess is not None:
            vs_rules = round(float(excess) - float(rules_excess), 4)
        marks = metrics.get("equity_marks")
        status = _classify_status(
            marks=int(marks) if marks is not None else None,
            excess=float(excess) if excess is not None else None,
            vs_primary=vs_primary,
            vs_rules=vs_rules,
            min_marks=min_marks_for_survivor,
            min_excess=min_excess_vs_market,
        )
        config_path = track_dir / CONFIG_FILENAME
        knobs = {}
        if config_path.exists():
            cfg = AutomationConfig.from_dict(read_json(config_path))
            knobs = {
                "max_positions": cfg.max_positions,
                "skip_timing_wait": cfg.skip_timing_wait,
                "min_conviction": cfg.min_conviction,
                "sector_cap": cfg.sector_cap,
                "exit_confirm_screens": cfg.exit_confirm_screens,
            }
        shadows.append(
            {
                "rank": rank,
                "shadow_track_id": track_id,
                "shadow_dir": str(track_dir),
                "spawned_at": provenance.get("spawned_at"),
                "knobs": knobs or provenance.get("shadow_knobs"),
                "full_period_score": provenance.get("full_period_score"),
                "confidence": provenance.get("confidence"),
                "metrics": metrics,
                "excess_vs_primary": vs_primary,
                "excess_vs_rules": vs_rules,
                "status": status,
                "provenance_path": str(track_dir / CALIBRATION_PROVENANCE_FILENAME),
            }
        )

    survivors = [row for row in shadows if row.get("status") == "surviving"]
    payload = {
        "schema_version": 1,
        "observe_only": True,
        "updated_at": datetime.now(UTC).isoformat(),
        "paper_root": str(paper_root),
        "benchmark_note": "excess_after_costs comes from decision_review when available",
        "gates": {
            "min_marks_for_survivor": min_marks_for_survivor,
            "min_excess_vs_market": min_excess_vs_market,
            "promotion": (
                "Survivors are starting priors for human learning-loop refinement only — "
                "never auto-apply to ai_judgment/config.json"
            ),
        },
        "primary": {"track_id": AI_JUDGMENT_TRACK_ID, "metrics": primary_metrics},
        "rules_control": {"track_id": RULES_TRACK_ID, "metrics": rules_metrics},
        "shadows": shadows,
        "survivors": [
            {
                "shadow_track_id": row["shadow_track_id"],
                "rank": row["rank"],
                "knobs": row.get("knobs"),
                "excess_after_costs": (row.get("metrics") or {}).get("excess_after_costs"),
            }
            for row in survivors
        ],
    }
    path = paper_root / ENDURANCE_FILENAME
    write_json(path, payload, compact=False)
    payload["path"] = str(path)
    return payload
