"""PIT warm-start for calibrated shadows: seed via log replay, then forward-only endurance."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.decision_review import (
    LearningKnobs,
    _compute_epoch_metrics,
    save_knob_epoch,
    start_knob_epoch,
)
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
    AutomationConfig,
    save_automated_fund,
    sync_fund_from_automation_config,
)
from value_investor.rebalance_log import (
    build_replay_fund_from_log,
    load_rebalance_log,
    resolve_track_dir,
)
from value_investor.storage import read_json, write_json

ENDURANCE_ZERO_DATUM_KEY = "endurance_zero_datum"


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_endurance_zero_datum(track_dir: Path) -> dict[str, Any] | None:
    """Prefer provenance warm-start datum; fall back to knob_epoch.json."""
    provenance = load_calibration_provenance(track_dir) or {}
    zero = provenance.get(ENDURANCE_ZERO_DATUM_KEY)
    if isinstance(zero, dict) and str(zero.get("started_at") or "").strip():
        return dict(zero)
    epoch_path = Path(track_dir) / "knob_epoch.json"
    if epoch_path.exists():
        try:
            raw = read_json(epoch_path)
        except (OSError, ValueError):
            raw = None
        if isinstance(raw, dict) and str(raw.get("started_at") or "").strip():
            return {
                "started_at": raw.get("started_at"),
                "baseline_nav": raw.get("baseline_nav"),
                "baseline_contributed_capital": raw.get("baseline_contributed_capital"),
                "equity_marks_at_start": raw.get("equity_marks_at_start"),
                "trade_count_at_start": raw.get("trade_count_at_start"),
                "seed_source": "knob_epoch",
                "knobs": raw.get("knobs") or {},
            }
    return None


def warm_start_calibration_shadow(
    paper_root: Path,
    *,
    rank: int = 1,
    parent_track_id: str = AI_JUDGMENT_TRACK_ID,
    sim_start: str | None = None,
    source: str = "log",
    force: bool = False,
    fetch_benchmark: bool = False,
) -> dict[str, Any]:
    """
    Populate a calibrated shadow via PIT rebalance-log replay, then freeze a
    forward-only endurance zero datum at seed end.

    Backdated seed P&L must not count toward survivor status — only post-seed
    weekday marks after ``endurance_zero_datum.started_at`` do.
    """
    paper_root = Path(paper_root)
    source_norm = str(source or "log").strip().lower()
    if source_norm != "log":
        return {
            "warm_started": False,
            "rank": int(rank),
            "reason": f"source={source_norm!r} not supported yet (use log)",
        }

    track_id = calibrated_shadow_track_id(int(rank))
    shadow_dir = paper_root / calibrated_shadow_subdir(int(rank))
    config_path = shadow_dir / CONFIG_FILENAME
    fund_path = shadow_dir / FUND_FILENAME
    provenance_path = shadow_dir / CALIBRATION_PROVENANCE_FILENAME

    if not config_path.exists():
        return {
            "warm_started": False,
            "rank": int(rank),
            "shadow_track_id": track_id,
            "reason": f"Shadow config missing at {config_path} — spawn first",
        }

    provenance = load_calibration_provenance(shadow_dir) or {}
    existing_zero = provenance.get(ENDURANCE_ZERO_DATUM_KEY)
    if isinstance(existing_zero, dict) and existing_zero.get("started_at") and not force:
        return {
            "warm_started": False,
            "rank": int(rank),
            "shadow_track_id": track_id,
            "skipped": True,
            "reason": "endurance_zero_datum already present (pass force=True to re-seed)",
            "endurance_zero_datum": existing_zero,
        }

    cfg = AutomationConfig.from_dict(read_json(config_path))
    parent_dir = resolve_track_dir(paper_root, parent_track_id)
    entries = load_rebalance_log(parent_dir)
    if not entries:
        return {
            "warm_started": False,
            "rank": int(rank),
            "shadow_track_id": track_id,
            "reason": f"No rebalance_log under parent {parent_dir}",
        }

    built = build_replay_fund_from_log(
        entries,
        max_positions=int(cfg.max_positions),
        skip_timing_wait=bool(cfg.skip_timing_wait),
        min_conviction=float(cfg.min_conviction),
        sector_cap=float(cfg.sector_cap),
        use_adjusted_signal=bool(cfg.use_adjusted_signal),
        require_research_accumulate=bool(cfg.require_research_accumulate),
        exit_confirm_screens=int(cfg.exit_confirm_screens),
        candidate_source="auto",
        sim_start=sim_start,
        fund_name=cfg.track_label or track_id,
    )
    if built is None:
        return {
            "warm_started": False,
            "rank": int(rank),
            "shadow_track_id": track_id,
            "reason": "No acted parent log entries to replay (after sim_start filter)",
        }

    fund, stats = built
    sync_fund_from_automation_config(fund, cfg)
    save_automated_fund(fund_path, fund)

    knobs = LearningKnobs.from_config(cfg)
    seed_end = _utcnow_iso()
    if fund.equity_curve:
        seed_end = str((fund.equity_curve[-1] or {}).get("at") or seed_end)
    epoch = start_knob_epoch(
        shadow_dir,
        fund,
        knobs,
        reviewed_at=seed_end,
    )
    # Mark as warm-start seed so dashboards can distinguish from L1 apply epochs.
    epoch.seeded_from_history = True
    save_knob_epoch(shadow_dir, epoch)

    zero_datum = {
        "started_at": epoch.started_at,
        "baseline_nav": epoch.baseline_nav,
        "baseline_contributed_capital": epoch.baseline_contributed_capital,
        "equity_marks_at_start": epoch.equity_marks_at_start,
        "trade_count_at_start": epoch.trade_count_at_start,
        "seed_source": "log",
        "parent_track_id": parent_track_id,
        "sim_start": stats.get("sim_start_applied") or sim_start,
        "seed_end": stats.get("replay_to") or epoch.started_at,
        "log_entries_replayed": stats.get("log_entries_replayed"),
        "replay_from": stats.get("replay_from"),
        "replay_to": stats.get("replay_to"),
        "knobs": knobs.to_dict(),
        "note": (
            "Warm-start seed complete. Survivor / endurance gates must use only "
            "post-seed forward marks after started_at — seed P&L is diagnostic only."
        ),
    }

    provenance = dict(provenance) if isinstance(provenance, dict) else {}
    provenance["schema_version"] = max(int(provenance.get("schema_version") or 2), 3)
    provenance[ENDURANCE_ZERO_DATUM_KEY] = zero_datum
    provenance["warm_started_at"] = _utcnow_iso()
    provenance["warm_start_force"] = bool(force)
    write_json(provenance_path, provenance, compact=False)

    post_seed = _compute_epoch_metrics(fund, epoch, fetch_benchmark=bool(fetch_benchmark))

    return {
        "warm_started": True,
        "rank": int(rank),
        "shadow_track_id": track_id,
        "shadow_dir": str(shadow_dir),
        "fund_path": str(fund_path),
        "provenance_path": str(provenance_path),
        "endurance_zero_datum": zero_datum,
        "seed_stats": stats,
        "post_seed_metrics": post_seed,
        "positions": len(fund.holdings),
    }


def warm_start_calibration_shadows(
    paper_root: Path,
    *,
    ranks: list[int] | None = None,
    parent_track_id: str = AI_JUDGMENT_TRACK_ID,
    sim_start: str | None = None,
    source: str = "log",
    force: bool = False,
) -> dict[str, Any]:
    """Warm-start all discovered calibrated shadows (or an explicit rank list)."""
    paper_root = Path(paper_root)
    if ranks is None:
        ranks = discover_calibration_shadow_ranks(paper_root)
    if not ranks:
        return {
            "warm_started": False,
            "reason": "No calibrated shadow ranks found — spawn first",
            "shadows": [],
        }
    results = [
        warm_start_calibration_shadow(
            paper_root,
            rank=int(rank),
            parent_track_id=parent_track_id,
            sim_start=sim_start,
            source=source,
            force=force,
        )
        for rank in ranks
    ]
    any_ok = any(row.get("warm_started") for row in results)
    return {
        "warm_started": any_ok,
        "shadows": results,
        "count": len(results),
        "warm_started_count": sum(1 for row in results if row.get("warm_started")),
    }
