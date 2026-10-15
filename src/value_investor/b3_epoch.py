"""B3 scoreboard epoch: evidentiary demotion + matched-30 cold-start helpers.

Owner lock (2026-10-15): freeze/demote 3-name ``ai_judgment_fair`` as adoption
truth; cold-start fixed-stake judgment observe (N210) + matched-30 fund twin
with matched top-30 buy-tier control — both shadow until volume gates.

Does **not** enlarge live ``max_positions`` / ``sector_cap`` mid-flight.
Does **not** crown a new ``assessment_model`` primary until gates clear.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.assessment_model import (
    apply_assessment_model,
    record_policy_change,
)
from value_investor.fair_cost_lab import spawn_matched30_twins
from value_investor.n210_ai_judgment_observe import (
    DEFERRED_ID,
    REGISTRATION_ID,
    refresh_n210_ai_judgment_observe,
)

POLICY_ID = "evidentiary_demotion_ai_judgment_fair_v1"
EPOCH_REGISTRATION_PATH = Path("docs/data/b3_scoreboard_epoch_registration.json")
DEFAULT_PAPER_ROOT = Path("docs/data/paper_automation")

AI_MATCHED30_TRACK_ID = "ai_judgment_matched30_fair"
BUY_TIER_MATCHED30_TRACK_ID = "buy_tier_matched30_fair"
HOLD5_TRACK_ID = "ai_judgment_hold5_fair"
GRADUATED_TRACK_ID = "ai_judgment_graduated_fair"


def build_epoch_registration(*, applied_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "epoch_id": "b3-scoreboard-evidence-v1",
        "locked_at": "2026-10-15",
        "applied_at": applied_at,
        "fork": "B3",
        "owner_lock": {
            "B": "freeze_demote_evidentiary_primary",
            "B3": "fixed_stake_judgment_observe_plus_matched30_fund_twin_both_shadow",
            "anti_C": "no_mid_flight_enlarge_live_3_name_book",
        },
        "demoted_evidentiary_primary": "ai_judgment_fair",
        "continuity": {
            "ai_judgment_fair": (
                "Keeps trading as history / continuity NAV; not adoption truth; "
                "do not back-label prior NAV as evidence for the new epoch."
            )
        },
        "frozen_with_epoch": [HOLD5_TRACK_ID, GRADUATED_TRACK_ID],
        "judgment_observe": {
            "deferred_id": DEFERRED_ID,
            "registration_id": REGISTRATION_ID,
            "primary_metric": "fair_cost_episode_pct",
            "influences_live": False,
            "volume_gate": {"min_episodes": 48, "min_weeks": 8},
        },
        "matched30_fund_pair": {
            "filter_track": AI_MATCHED30_TRACK_ID,
            "control_track": BUY_TIER_MATCHED30_TRACK_ID,
            "max_positions": 30,
            "sector_cap": 0.2,
            "role": "shadow_paper_twins",
            "nav_compare": "only_matched_pair",
            "full_buy_tier_level": "strand_a_diagnostic_baseline",
            "not_assessment_primary_until_gates": True,
        },
        "policy_change_id": POLICY_ID,
        "constraints": [
            "f4_no_new_screen_extras",
            "f8_fail_closed",
            "o3_alone_first",
            "fixed_stake_v0_judgment",
            "twins_over_edits",
            "no_back_label",
        ],
        "ops_doc": "docs/ops/b3-scoreboard-epoch.md",
    }


def apply_b3_lock(
    paper_root: Path | None = None,
    *,
    data_dir: Path | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Spawn matched-30 twins, demote evidentiary primary, freeze 3-name twins, seal N210."""
    root = Path(paper_root) if paper_root is not None else DEFAULT_PAPER_ROOT
    data = Path(data_dir) if data_dir is not None else Path("docs/data")
    when = now or datetime.now(UTC)
    when_s = when.isoformat()

    if dry_run:
        return {
            "dry_run": True,
            "would_apply": True,
            "policy_id": POLICY_ID,
            "freeze": [HOLD5_TRACK_ID, GRADUATED_TRACK_ID],
            "spawn": [AI_MATCHED30_TRACK_ID, BUY_TIER_MATCHED30_TRACK_ID],
            "n210": REGISTRATION_ID,
        }

    spawn = spawn_matched30_twins(root, dry_run=False)
    policy = record_policy_change(
        root,
        policy_id=POLICY_ID,
        summary=(
            "B3 evidentiary demotion: ai_judgment_fair (3-name sleeve) is no longer "
            "adoption / filter-skill truth. Judgment evidence moves to N210 fixed-stake "
            "fair-cost episode %; portfolio continuity via matched-30 fund twin pair. "
            "Do not enlarge live max_positions/sector_cap mid-flight. Do not back-label "
            "prior 3-name NAV as evidence for the new epoch. F8: trailing primary-vs-control "
            "gap never alone applies knobs or fills."
        ),
        history_note=(
            "Marks and NAV on ai_judgment_fair before and after effective_at remain "
            "continuity / observe history. They are underpowered and confounded "
            "(sleeve N=3 vs control ~55) and must not be read as filter skill or as "
            "evidence for matched-30 / N210 skill. assessment_model.primary_track may "
            "still name ai_judgment_fair for product continuity until volume gates; "
            "policy_changes.evidentiary_demotion_ai_judgment_fair_v1 is the demotion stamp."
        ),
        audit={
            "fork": "B3",
            "demoted_track": "ai_judgment_fair",
            "judgment_observe": REGISTRATION_ID,
            "matched30": [AI_MATCHED30_TRACK_ID, BUY_TIER_MATCHED30_TRACK_ID],
            "frozen_twins": [HOLD5_TRACK_ID, GRADUATED_TRACK_ID],
        },
        now=when,
    )
    model = apply_assessment_model(
        root,
        primary="ai_judgment_fair",
        control="buy_tier_level",
        freeze={
            HOLD5_TRACK_ID: {
                "reason": (
                    "B3: 3-name hold-buffer twin inherits underpowered parent sleeve; "
                    "freeze with parent evidentiary demotion. Re-spawn from matched-30 "
                    "epoch later if the exit-buffer LQ is still open."
                ),
                "superseded_by": AI_MATCHED30_TRACK_ID,
            },
            GRADUATED_TRACK_ID: {
                "reason": (
                    "B3: 3-name graduated twin inherits underpowered parent sleeve; "
                    "freeze with parent evidentiary demotion. Re-spawn from matched-30 "
                    "epoch later if graduated sizing LQ is still open."
                ),
                "superseded_by": AI_MATCHED30_TRACK_ID,
            },
        },
        reason=(
            "B3 lock: freeze underpowered 3-name twins; keep ai_judgment_fair as "
            "continuity primary (evidentiary demotion via policy_changes); cold-start "
            "matched-30 shadows + N210 observe — do not crown new primary until gates."
        ),
        now=when,
    )
    n210 = refresh_n210_ai_judgment_observe(
        output_dir=data,
        store_path=data / "n210_ai_judgment_observe.json",
        registration_path=data / "n210_ai_judgment_registration.json",
        persist=True,
        now=when,
    )
    epoch = build_epoch_registration(applied_at=when_s)
    epoch_path = data / EPOCH_REGISTRATION_PATH.name
    epoch_path.write_text(json.dumps(epoch, indent=2) + "\n", encoding="utf-8")
    return {
        "applied_at": when_s,
        "policy": policy,
        "spawn": spawn,
        "frozen_tracks": sorted((model.get("frozen_tracks") or {}).keys()),
        "n210_registration_id": n210.get("registration_id"),
        "epoch_path": str(epoch_path),
        "primary_track": model.get("primary_track"),
        "note": (
            "ai_judgment_fair remains primary_track for continuity but is "
            "evidentiary-demoted; matched-30 twins are shadow paper; N210 is observe stub."
        ),
    }
