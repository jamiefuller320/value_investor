"""Suite B — fair T212-shaped cost lab (parallel to 3% stress Suite A).

Spawns warm-start AI + rules books stamped with ``cost_fields_for_config("ftse350")``.
Decision-review ``--apply`` may tune these tracks; Suite A primary stays on stress
until human promotion (N48).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.calibration_warm_start import ENDURANCE_ZERO_DATUM_KEY
from value_investor.decision_review import (
    LearningKnobs,
    _compute_epoch_metrics,
    save_knob_epoch,
    start_knob_epoch,
)
from value_investor.market_trading_costs import LIVE_PAPER_MARKET_ID, cost_fields_for_config
from value_investor.paper_automation import (
    AI_JUDGMENT_TRACK_ID,
    CONFIG_FILENAME,
    FUND_FILENAME,
    RULES_TRACK_ID,
    AutomationConfig,
    default_ai_judgment_config,
    default_rules_config,
    ensure_automated_fund,
    save_automated_fund,
    sync_fund_from_automation_config,
)
from value_investor.rebalance_log import (
    build_replay_fund_from_log,
    load_rebalance_log,
    resolve_track_dir,
)
from value_investor.storage import read_json, write_json

AI_JUDGMENT_FAIR_TRACK_ID = "ai_judgment_fair"
RULES_FAIR_TRACK_ID = "rules_fair"
AI_JUDGMENT_FAIR_SUBDIR = "ai_judgment_fair"
RULES_FAIR_SUBDIR = "rules_fair"
FAIR_COST_LAB_TRACK_IDS: tuple[str, ...] = (
    AI_JUDGMENT_FAIR_TRACK_ID,
    RULES_FAIR_TRACK_ID,
)
FAIR_COST_LAB_PROVENANCE_FILENAME = "fair_cost_lab_provenance.json"
FAIR_TWIN_SUFFIX = "_fair"
MIRRORABLE_EXPERIMENT_KINDS = frozenset(
    {"calibration_shadow", "exclusion_shadow", "experimental_paper_track"}
)
DEFAULT_FAIR_TWIN_MAX_SPAWNS = 2

_FAIR_PARENTS: dict[str, str] = {
    AI_JUDGMENT_FAIR_TRACK_ID: AI_JUDGMENT_TRACK_ID,
    RULES_FAIR_TRACK_ID: RULES_TRACK_ID,
}
_FAIR_SUBDIRS: dict[str, str] = {
    AI_JUDGMENT_FAIR_TRACK_ID: AI_JUDGMENT_FAIR_SUBDIR,
    RULES_FAIR_TRACK_ID: RULES_FAIR_SUBDIR,
}


def fair_twin_track_id(parent_track_id: str) -> str:
    tid = str(parent_track_id or "").strip()
    if not tid:
        raise ValueError("parent_track_id is required")
    if tid.endswith(FAIR_TWIN_SUFFIX):
        raise ValueError(f"{tid} is already a fair-cost track")
    return f"{tid}{FAIR_TWIN_SUFFIX}"


def fair_cost_lab_subdir(track_id: str) -> str:
    tid = str(track_id or "").strip()
    if tid in _FAIR_SUBDIRS:
        return _FAIR_SUBDIRS[tid]
    if is_fair_cost_lab_track_id(tid):
        return tid
    raise ValueError(f"Unknown fair-cost lab track_id: {track_id!r}")


def fair_cost_lab_parent_track_id(track_id: str) -> str:
    tid = str(track_id or "").strip()
    if tid in _FAIR_PARENTS:
        return _FAIR_PARENTS[tid]
    if tid.endswith(FAIR_TWIN_SUFFIX) and len(tid) > len(FAIR_TWIN_SUFFIX):
        return tid[: -len(FAIR_TWIN_SUFFIX)]
    raise ValueError(f"Unknown fair-cost lab track_id: {track_id!r}")


def is_fair_cost_lab_track_id(track_id: str | None) -> bool:
    tid = str(track_id or "").strip()
    return tid in FAIR_COST_LAB_TRACK_IDS or tid.endswith(FAIR_TWIN_SUFFIX)


def discover_fair_cost_lab_track_ids(paper_root: Path) -> list[str]:
    """Return Suite B track ids that already have a config under paper_root."""
    root = Path(paper_root)
    found: list[str] = []
    seen: set[str] = set()
    for track_id, subdir in _FAIR_SUBDIRS.items():
        if (root / subdir / CONFIG_FILENAME).exists():
            found.append(track_id)
            seen.add(track_id)
    if not root.is_dir():
        return found
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name in seen:
            continue
        config_path = child / CONFIG_FILENAME
        if not config_path.exists():
            continue
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        track_id = str((raw or {}).get("track_id") or child.name).strip()
        if not track_id or track_id in seen:
            continue
        if bool((raw or {}).get("is_fair_cost_lab")) or is_fair_cost_lab_track_id(track_id):
            found.append(track_id)
            seen.add(track_id)
    return found


def stamp_fair_costs(config: AutomationConfig, *, market_id: str = LIVE_PAPER_MARKET_ID) -> None:
    """Stamp T212-shaped fair buy/sell costs onto an automation config."""
    fields = cost_fields_for_config(market_id)
    config.trade_cost_pct = float(fields["trade_cost_pct"])
    config.buy_cost_pct = float(fields["buy_cost_pct"])
    config.sell_cost_pct = float(fields["sell_cost_pct"])


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_parent_config(paper_root: Path, parent_track_id: str) -> AutomationConfig:
    parent_dir = resolve_track_dir(paper_root, parent_track_id)
    path = parent_dir / CONFIG_FILENAME
    if path.exists():
        return AutomationConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if parent_track_id == AI_JUDGMENT_TRACK_ID:
        return default_ai_judgment_config()
    return default_rules_config()


def _build_fair_config(
    *,
    track_id: str,
    parent: AutomationConfig,
    market_id: str,
) -> AutomationConfig:
    parent_track_id = fair_cost_lab_parent_track_id(track_id)
    if parent_track_id == AI_JUDGMENT_TRACK_ID:
        cfg = default_ai_judgment_config(parent)
        cfg.track_label = "AI judgment fair-cost lab (Suite B)"
    else:
        cfg = default_rules_config(parent)
        cfg.track_label = "Screen rules fair-cost lab (Suite B)"

    # Transplant stress-surviving knobs from the parent book (priors only).
    cfg.min_conviction = float(parent.min_conviction)
    cfg.skip_timing_wait = bool(parent.skip_timing_wait)
    cfg.sector_cap = float(parent.sector_cap)
    cfg.max_positions = int(parent.max_positions)
    cfg.exit_confirm_screens = int(parent.exit_confirm_screens)
    cfg.reentry_cooldown_screens = int(parent.reentry_cooldown_screens)
    cfg.min_rebalance_notional_gbp = float(parent.min_rebalance_notional_gbp)

    cfg.track_id = track_id
    cfg.is_primary_learning_track = False
    cfg.is_calibration_shadow = False
    cfg.calibration_parent_track = None
    cfg.is_exclusion_shadow = False
    cfg.exclusion_parent_track = None
    cfg.exclusion_ladder_step_id = None
    cfg.is_fair_cost_lab = True
    cfg.fair_cost_parent_track = parent_track_id
    stamp_fair_costs(cfg, market_id=market_id)
    return cfg


def spawn_fair_cost_lab_track(
    paper_root: Path,
    track_id: str,
    *,
    market_id: str = LIVE_PAPER_MARKET_ID,
    force: bool = False,
) -> dict[str, Any]:
    """Create one Suite B fair-cost track directory + config (idempotent)."""
    paper_root = Path(paper_root)
    tid = str(track_id or "").strip()
    if tid not in FAIR_COST_LAB_TRACK_IDS:
        return {"spawned": False, "track_id": tid, "reason": f"unknown track_id {tid!r}"}

    parent_track_id = fair_cost_lab_parent_track_id(tid)
    parent = _load_parent_config(paper_root, parent_track_id)
    shadow_dir = paper_root / fair_cost_lab_subdir(tid)
    shadow_dir.mkdir(parents=True, exist_ok=True)
    config_path = shadow_dir / CONFIG_FILENAME
    fund_path = shadow_dir / FUND_FILENAME
    provenance_path = shadow_dir / FAIR_COST_LAB_PROVENANCE_FILENAME

    existed = config_path.exists()
    if existed and not force:
        cfg = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
        cfg.is_fair_cost_lab = True
        cfg.fair_cost_parent_track = parent_track_id
        cfg.is_primary_learning_track = False
        stamp_fair_costs(cfg, market_id=market_id)
        config_path.write_text(json.dumps(cfg.to_dict(), indent=2) + "\n", encoding="utf-8")
        ensure_automated_fund(fund_path, cfg)
        return {
            "spawned": True,
            "created": False,
            "track_id": tid,
            "parent_track_id": parent_track_id,
            "track_dir": str(shadow_dir),
            "reason": "already exists — refreshed fair-cost stamps",
        }

    cfg = _build_fair_config(track_id=tid, parent=parent, market_id=market_id)
    if fund_path.exists() and force:
        fund_path.unlink()
    config_path.write_text(json.dumps(cfg.to_dict(), indent=2) + "\n", encoding="utf-8")
    ensure_automated_fund(fund_path, cfg)

    provenance = {
        "schema_version": 1,
        "suite": "B",
        "spawned_at": _utcnow_iso(),
        "track_id": tid,
        "parent_track_id": parent_track_id,
        "market_id": market_id,
        "fair_costs": cost_fields_for_config(market_id),
        "parent_knobs_at_spawn": {
            "min_conviction": parent.min_conviction,
            "exit_confirm_screens": parent.exit_confirm_screens,
            "reentry_cooldown_screens": parent.reentry_cooldown_screens,
            "max_positions": parent.max_positions,
            "sector_cap": parent.sector_cap,
        },
        "note": (
            "Suite B fair-cost lab — decision-review --apply may tune this track only. "
            "Do not flip Suite A primary off 3% stress until B clears promotion gates (N48)."
        ),
    }
    write_json(provenance_path, provenance, compact=False)

    return {
        "spawned": True,
        "created": not existed or force,
        "track_id": tid,
        "parent_track_id": parent_track_id,
        "track_dir": str(shadow_dir),
        "provenance_path": str(provenance_path),
        "fair_costs": provenance["fair_costs"],
    }


def spawn_fair_cost_lab(
    paper_root: Path,
    *,
    market_id: str = LIVE_PAPER_MARKET_ID,
    force: bool = False,
    track_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Spawn the default Suite B pair (AI + rules) or a subset."""
    wanted = list(track_ids) if track_ids else list(FAIR_COST_LAB_TRACK_IDS)
    rows = [
        spawn_fair_cost_lab_track(paper_root, tid, market_id=market_id, force=force)
        for tid in wanted
    ]
    return {
        "spawned_count": sum(1 for r in rows if r.get("spawned")),
        "created_count": sum(1 for r in rows if r.get("created")),
        "market_id": market_id,
        "tracks": rows,
    }


def _build_fair_twin_config(
    *,
    twin_id: str,
    parent: AutomationConfig,
    parent_track_id: str,
    market_id: str,
) -> AutomationConfig:
    cfg = AutomationConfig.from_dict(parent.to_dict())
    cfg.track_id = twin_id
    parent_label = str(parent.track_label or parent_track_id)
    cfg.track_label = f"{parent_label} fair-cost twin (Suite B)"
    cfg.is_primary_learning_track = False
    cfg.is_fair_cost_lab = True
    cfg.fair_cost_parent_track = parent_track_id
    stamp_fair_costs(cfg, market_id=market_id)
    return cfg


def spawn_fair_cost_twin_for_parent(
    paper_root: Path,
    parent_track_id: str,
    *,
    market_id: str = LIVE_PAPER_MARKET_ID,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Spawn one fair-cost twin of an existing Suite A experiment track."""
    paper_root = Path(paper_root)
    parent_id = str(parent_track_id or "").strip()
    if not parent_id:
        return {"spawned": False, "reason": "parent_track_id required"}
    if is_fair_cost_lab_track_id(parent_id):
        return {
            "spawned": False,
            "parent_track_id": parent_id,
            "reason": "parent is already a fair-cost track",
        }
    if parent_id in {AI_JUDGMENT_TRACK_ID, RULES_TRACK_ID}:
        return {
            "spawned": False,
            "parent_track_id": parent_id,
            "reason": "base AI/rules fair books already exist — use spawn-fair-lab",
        }

    try:
        twin_id = fair_twin_track_id(parent_id)
    except ValueError as exc:
        return {"spawned": False, "parent_track_id": parent_id, "reason": str(exc)}

    parent_dir = resolve_track_dir(paper_root, parent_id)
    if not (parent_dir / CONFIG_FILENAME).exists():
        return {
            "spawned": False,
            "parent_track_id": parent_id,
            "twin_track_id": twin_id,
            "reason": f"parent config missing at {parent_dir / CONFIG_FILENAME}",
        }

    shadow_dir = paper_root / fair_cost_lab_subdir(twin_id)
    config_path = shadow_dir / CONFIG_FILENAME
    if dry_run:
        return {
            "spawned": False,
            "dry_run": True,
            "would_spawn": not config_path.exists() or force,
            "parent_track_id": parent_id,
            "twin_track_id": twin_id,
            "track_dir": str(shadow_dir),
            "reason": "dry_run",
        }

    parent = _load_parent_config(paper_root, parent_id)
    shadow_dir.mkdir(parents=True, exist_ok=True)
    fund_path = shadow_dir / FUND_FILENAME
    provenance_path = shadow_dir / FAIR_COST_LAB_PROVENANCE_FILENAME
    existed = config_path.exists()
    if existed and not force:
        cfg = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
        cfg.is_fair_cost_lab = True
        cfg.fair_cost_parent_track = parent_id
        cfg.is_primary_learning_track = False
        stamp_fair_costs(cfg, market_id=market_id)
        config_path.write_text(json.dumps(cfg.to_dict(), indent=2) + "\n", encoding="utf-8")
        ensure_automated_fund(fund_path, cfg)
        return {
            "spawned": True,
            "created": False,
            "track_id": twin_id,
            "parent_track_id": parent_id,
            "track_dir": str(shadow_dir),
            "reason": "already exists — refreshed fair-cost stamps",
        }

    cfg = _build_fair_twin_config(
        twin_id=twin_id,
        parent=parent,
        parent_track_id=parent_id,
        market_id=market_id,
    )
    if fund_path.exists() and force:
        fund_path.unlink()
    config_path.write_text(json.dumps(cfg.to_dict(), indent=2) + "\n", encoding="utf-8")
    ensure_automated_fund(fund_path, cfg)
    provenance = {
        "schema_version": 1,
        "suite": "B",
        "spawned_at": _utcnow_iso(),
        "track_id": twin_id,
        "parent_track_id": parent_id,
        "market_id": market_id,
        "spawn_reason": "experiment_assessment_recommend",
        "fair_costs": cost_fields_for_config(market_id),
        "parent_knobs_at_spawn": {
            "min_conviction": parent.min_conviction,
            "exit_confirm_screens": parent.exit_confirm_screens,
            "reentry_cooldown_screens": parent.reentry_cooldown_screens,
            "max_positions": parent.max_positions,
            "sector_cap": parent.sector_cap,
        },
        "note": (
            "Selective Suite B twin of a recommend-state Suite A experiment. "
            "Human spawn only — do not auto-fork every shadow (N53)."
        ),
    }
    write_json(provenance_path, provenance, compact=False)
    return {
        "spawned": True,
        "created": not existed or force,
        "track_id": twin_id,
        "parent_track_id": parent_id,
        "track_dir": str(shadow_dir),
        "provenance_path": str(provenance_path),
        "fair_costs": provenance["fair_costs"],
    }


def recommend_rows_for_fair_twins(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    """Return experiment_assessment rows eligible for a selective A→B twin."""
    rows: list[dict[str, Any]] = []
    for row in assessment.get("experiments") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") != "recommend":
            continue
        if str(row.get("kind") or "") not in MIRRORABLE_EXPERIMENT_KINDS:
            continue
        track_id = str(row.get("track_id") or "").strip()
        if not track_id or is_fair_cost_lab_track_id(track_id):
            continue
        if track_id in {AI_JUDGMENT_TRACK_ID, RULES_TRACK_ID}:
            continue
        rows.append(row)
    return rows


def spawn_fair_cost_twins_for_recommendations(
    paper_root: Path,
    data_dir: Path,
    *,
    dry_run: bool = True,
    max_spawns: int = DEFAULT_FAIR_TWIN_MAX_SPAWNS,
    experiment_id: str | None = None,
    market_id: str = LIVE_PAPER_MARKET_ID,
    force: bool = False,
) -> dict[str, Any]:
    """Spawn fair-cost twins only for recommend-state Suite A experiments."""
    from value_investor.experiment_assessment import ASSESSMENT_FILENAME

    paper_root = Path(paper_root)
    assessment_path = Path(data_dir) / ASSESSMENT_FILENAME
    try:
        raw = read_json(assessment_path)
        assessment = raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, FileNotFoundError):
        assessment = {}

    candidates = recommend_rows_for_fair_twins(assessment)
    if experiment_id:
        wanted = str(experiment_id).strip()
        candidates = [
            row
            for row in candidates
            if str(row.get("experiment_id") or "") == wanted
            or str(row.get("track_id") or "") == wanted
        ]

    cap = max(0, int(max_spawns))
    selected = candidates[:cap]
    skipped_budget = candidates[cap:]
    rows = [
        spawn_fair_cost_twin_for_parent(
            paper_root,
            str(row.get("track_id") or ""),
            market_id=market_id,
            force=force,
            dry_run=dry_run,
        )
        | {
            "experiment_id": row.get("experiment_id"),
            "kind": row.get("kind"),
            "status": row.get("status"),
        }
        for row in selected
    ]
    return {
        "dry_run": dry_run,
        "recommend_count": len(candidates),
        "selected_count": len(selected),
        "spawned_count": sum(1 for r in rows if r.get("spawned")),
        "created_count": sum(1 for r in rows if r.get("created")),
        "skipped_budget": [
            {
                "experiment_id": row.get("experiment_id"),
                "track_id": row.get("track_id"),
                "reason": "max_spawns",
            }
            for row in skipped_budget
        ],
        "tracks": rows,
        "note": (
            "Human gate only — recommend rows never auto-spawn (N41/N53). "
            "Default dry_run=True; pass dry_run=False to write configs."
        ),
    }


def warm_start_fair_cost_lab_track(
    paper_root: Path,
    track_id: str,
    *,
    sim_start: str | None = None,
    force: bool = False,
    fetch_benchmark: bool = False,
) -> dict[str, Any]:
    """
    PIT warm-start a Suite B track from its Suite A parent rebalance_log.

    Seed P&L is diagnostic only — endurance uses ``endurance_zero_datum.started_at``.
    """
    paper_root = Path(paper_root)
    tid = str(track_id or "").strip()
    if tid not in FAIR_COST_LAB_TRACK_IDS:
        return {"warm_started": False, "track_id": tid, "reason": f"unknown track_id {tid!r}"}

    parent_track_id = fair_cost_lab_parent_track_id(tid)
    shadow_dir = paper_root / fair_cost_lab_subdir(tid)
    config_path = shadow_dir / CONFIG_FILENAME
    fund_path = shadow_dir / FUND_FILENAME
    provenance_path = shadow_dir / FAIR_COST_LAB_PROVENANCE_FILENAME

    if not config_path.exists():
        return {
            "warm_started": False,
            "track_id": tid,
            "reason": f"Fair-lab config missing at {config_path} — spawn first",
        }

    if provenance_path.exists():
        try:
            raw = read_json(provenance_path)
            provenance: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            provenance = {}
    else:
        provenance = {}

    existing_zero = provenance.get(ENDURANCE_ZERO_DATUM_KEY)
    if isinstance(existing_zero, dict) and existing_zero.get("started_at") and not force:
        return {
            "warm_started": False,
            "track_id": tid,
            "skipped": True,
            "reason": "endurance_zero_datum already present (pass force=True to re-seed)",
            "endurance_zero_datum": existing_zero,
        }

    cfg = AutomationConfig.from_dict(read_json(config_path))
    stamp_fair_costs(cfg)
    cfg.is_fair_cost_lab = True
    cfg.fair_cost_parent_track = parent_track_id
    cfg.is_primary_learning_track = False
    config_path.write_text(json.dumps(cfg.to_dict(), indent=2) + "\n", encoding="utf-8")

    parent_dir = resolve_track_dir(paper_root, parent_track_id)
    entries = load_rebalance_log(parent_dir)
    if not entries:
        return {
            "warm_started": False,
            "track_id": tid,
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
        fund_name=cfg.track_label or tid,
    )
    if built is None:
        return {
            "warm_started": False,
            "track_id": tid,
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
        "suite": "B",
        "sim_start": stats.get("sim_start_applied") or sim_start,
        "seed_end": stats.get("replay_to") or epoch.started_at,
        "log_entries_replayed": stats.get("log_entries_replayed"),
        "replay_from": stats.get("replay_from"),
        "replay_to": stats.get("replay_to"),
        "knobs": knobs.to_dict(),
        "note": (
            "Suite B warm-start seed complete. Survivor / endurance gates must use only "
            "post-seed forward marks after started_at — seed P&L is diagnostic only."
        ),
    }

    provenance["schema_version"] = max(int(provenance.get("schema_version") or 1), 1)
    provenance[ENDURANCE_ZERO_DATUM_KEY] = zero_datum
    provenance["warm_started_at"] = _utcnow_iso()
    provenance["warm_start_force"] = bool(force)
    write_json(provenance_path, provenance, compact=False)

    post_seed = _compute_epoch_metrics(fund, epoch, fetch_benchmark=bool(fetch_benchmark))

    return {
        "warm_started": True,
        "track_id": tid,
        "parent_track_id": parent_track_id,
        "track_dir": str(shadow_dir),
        "fund_path": str(fund_path),
        "provenance_path": str(provenance_path),
        "endurance_zero_datum": zero_datum,
        "seed_stats": stats,
        "post_seed_metrics": post_seed,
        "positions": len(fund.holdings),
    }


def warm_start_fair_cost_lab(
    paper_root: Path,
    *,
    track_ids: list[str] | None = None,
    sim_start: str | None = None,
    force: bool = False,
    fetch_benchmark: bool = False,
) -> dict[str, Any]:
    wanted = list(track_ids) if track_ids else list(FAIR_COST_LAB_TRACK_IDS)
    rows = [
        warm_start_fair_cost_lab_track(
            paper_root,
            tid,
            sim_start=sim_start,
            force=force,
            fetch_benchmark=fetch_benchmark,
        )
        for tid in wanted
    ]
    return {
        "warm_started_count": sum(1 for r in rows if r.get("warm_started")),
        "skipped_count": sum(1 for r in rows if r.get("skipped")),
        "tracks": rows,
    }


def filter_track_ids_for_suite(
    track_ids: list[str] | tuple[str, ...],
    suite: str | None,
) -> list[str]:
    """
    Filter track ids by learning suite.

    ``A`` = stress / non-fair lab tracks; ``B`` = fair-cost lab only; ``all``/None = unchanged.
    """
    ids = [str(t) for t in track_ids]
    suite_norm = str(suite or "all").strip().lower()
    if suite_norm in {"", "all", "*"}:
        return ids
    if suite_norm in {"b", "suite_b", "fair", "fair_lab"}:
        return [t for t in ids if is_fair_cost_lab_track_id(t)]
    if suite_norm in {"a", "suite_a", "stress"}:
        return [t for t in ids if not is_fair_cost_lab_track_id(t)]
    raise ValueError(f"Unknown suite filter: {suite!r} (use A, B, or all)")
