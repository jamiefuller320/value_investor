"""Entry–exit lifecycle stages and the factors we keep experimenting on.

This is the inventory for perpetual, stage-scoped experiments. It does **not**
mutate paper books. Graduated allocation already scores appetite / harvest;
the full per-holding state machine remains deferred (L177).
"""

from __future__ import annotations

from typing import Any

# Held-book ratio vs sleeve target. Below this is a starter sleeve, not a build.
STARTER_RATIO_CEILING = 0.40
BUILD_RATIO_CEILING = 0.85
HARVEST_RATIO_FLOOR = 1.08

# Canonical stages — labels used in classify_lifecycle_phase + this catalog.
LIFECYCLE_STAGE_IDS = (
    "prospect",
    "starter",
    "build",
    "full",
    "harvest",
    "grace",
    "exit",
)

# Map diagnostic labels from capital_allocation.classify_lifecycle_phase → stage.
PHASE_TO_STAGE: dict[str, str] = {
    "prospect_ready": "prospect",
    "prospect_waitlist": "prospect",
    "prospect_ineligible": "prospect",
    "starter": "starter",
    "build": "build",
    "full": "full",
    "hold": "full",
    "harvest": "harvest",
    "grace": "grace",
    "exit_pending": "exit",
    "exit_buffer": "exit",
}


def stage_for_phase(phase: str | None) -> str:
    """Collapse diagnostic lifecycle labels onto the seven experiment stages."""
    if not phase:
        return "prospect"
    return PHASE_TO_STAGE.get(str(phase), str(phase))


def lifecycle_catalog() -> dict[str, Any]:
    """
    Stages, factors, and which experiment owns each factor.

    Status values:
      observing — evidence already accumulating
      planned — designed, not collecting yet
      deferred — parked until a revisit trigger
    """
    return {
        "schema_version": 1,
        "purpose": (
            "Break the entry–exit lifecycle into stages, name the factors that "
            "apply at each stage, and keep an experiment running on every factor. "
            "Dollar-cost averaging / graduated entry is watched across all paper "
            "models first — fill and de-risk findings are expected to be largely "
            "model-independent."
        ),
        "observe_only": True,
        "related": {
            "graduated_allocation_track": "Starter sizing + harvest skims on one rules book",
            "entry_dca_overlay": "Model-independent cadence overlay on every track's new buys",
            "hypothesis_first_exit": "Loss tolerance after entry — thesis before crude stops",
            "exit_timing_cohorts": "Hold-recovery vs swap after the position is on the book",
            "deferred_L177": "Full per-holding state machine in rebalance_state",
        },
        "stages": [
            {
                "id": "prospect",
                "label": "Prospect (not yet held)",
                "question": "Should this name receive any capital this cycle?",
                "phase_labels": [
                    "prospect_ready",
                    "prospect_waitlist",
                    "prospect_ineligible",
                ],
                "factors": [
                    {
                        "id": "entry_appetite",
                        "question": "How aggressively should we start a sleeve?",
                        "status": "observing",
                        "experiment": "graduated_allocation_track",
                        "artifact": "capital_allocation.entry_appetite",
                    },
                    {
                        "id": "timing_gate",
                        "question": "Does wait-timing block a new buy?",
                        "status": "observing",
                        "experiment": "paper_knobs.skip_timing_wait",
                        "artifact": "learning_tracks_review",
                    },
                    {
                        "id": "conviction_floor",
                        "question": "What conviction floor keeps losers out without starving the book?",
                        "status": "observing",
                        "experiment": "knob_calibration",
                        "artifact": "knob_calibration_priors.json",
                    },
                    {
                        "id": "research_gate",
                        "question": "Does a research-accumulate gate improve entry quality?",
                        "status": "observing",
                        "experiment": "ai_judgment_primary",
                        "artifact": "learning_tracks_review",
                    },
                ],
            },
            {
                "id": "starter",
                "label": "Starter (first capital deployed)",
                "question": "Can a partial first fill de-risk the entry versus lump-sum?",
                "phase_labels": ["starter"],
                "factors": [
                    {
                        "id": "starter_fraction",
                        "question": "What fraction of the sleeve should the first fill take?",
                        "status": "observing",
                        "experiment": "graduated_allocation_track",
                        "artifact": "capital_allocation.entry_sleeve_fraction",
                    },
                    {
                        "id": "entry_dca_cadence",
                        "question": (
                            "Does splitting the decided notional across weekday/weekly "
                            "tranches cut peak adverse exposure, and which cadence wins?"
                        ),
                        "status": "observing",
                        "experiment": "entry_dca_overlay",
                        "artifact": "learning_tracks_entry_dca.json",
                        "model_independent": True,
                    },
                    {
                        "id": "first_fill_adverse_pause",
                        "question": "Pause remaining tranches if MAE exceeds a band while thesis intact?",
                        "status": "planned",
                        "experiment": "entry_dca_overlay",
                        "artifact": None,
                        "revisit_when": "entry_dca_overlay ready_for_cadence_analysis",
                    },
                ],
            },
            {
                "id": "build",
                "label": "Build (adding toward full sleeve)",
                "question": "When and how fast should we complete the sleeve?",
                "phase_labels": ["build"],
                "factors": [
                    {
                        "id": "add_cadence",
                        "question": "Calendar DCA vs discretionary top-up — same overlay as starter.",
                        "status": "observing",
                        "experiment": "entry_dca_overlay",
                        "artifact": "learning_tracks_entry_dca.json",
                        "model_independent": True,
                    },
                    {
                        "id": "add_only_if_cheaper",
                        "question": "Add remaining tranches only when mark ≤ first fill?",
                        "status": "planned",
                        "experiment": "entry_dca_overlay",
                        "artifact": None,
                        "revisit_when": "entry_dca_overlay closed_episodes >= 12",
                    },
                    {
                        "id": "add_only_if_thesis_intact",
                        "question": "Skip remaining adds when hypothesis integrity is weakening/broken?",
                        "status": "planned",
                        "experiment": "entry_dca_overlay",
                        "artifact": None,
                        "revisit_when": "hypothesis_outcomes ready_for_thesis_outcome_analysis",
                    },
                    {
                        "id": "max_build_window",
                        "question": "How long may a sleeve stay below target before we stop adding?",
                        "status": "planned",
                        "experiment": "entry_dca_overlay",
                        "artifact": None,
                        "revisit_when": "entry_dca_overlay ready_for_cadence_analysis",
                    },
                ],
            },
            {
                "id": "full",
                "label": "Full (at target sleeve)",
                "question": "While at size, what loss tolerance and rebalance band apply?",
                "phase_labels": ["full", "hold"],
                "factors": [
                    {
                        "id": "rebalance_band",
                        "question": "How far from target before we trim or top up?",
                        "status": "observing",
                        "experiment": "paper_churn.min_rebalance_notional",
                        "artifact": "learning_tracks_churn_health.json",
                    },
                    {
                        "id": "loser_tolerance",
                        "question": "What share of intact underwater names is acceptable?",
                        "status": "observing",
                        "experiment": "hypothesis_first_exit",
                        "artifact": "learning_tracks_hypothesis_integrity.json",
                    },
                    {
                        "id": "thesis_monitoring",
                        "question": "Does a mark drawdown break the facts, or only the price?",
                        "status": "observing",
                        "experiment": "hypothesis_first_exit",
                        "artifact": "hypothesis_integrity.json",
                    },
                ],
            },
            {
                "id": "harvest",
                "label": "Harvest (skim extended winners)",
                "question": "When should we recycle gains without abandoning the thesis?",
                "phase_labels": ["harvest"],
                "factors": [
                    {
                        "id": "skim_urgency",
                        "question": "What urgency threshold starts a harvest skim?",
                        "status": "observing",
                        "experiment": "graduated_allocation_track",
                        "artifact": "capital_allocation.skim_fraction",
                    },
                    {
                        "id": "harvest_gain_floor",
                        "question": "Minimum unrealized gain before skimming?",
                        "status": "observing",
                        "experiment": "graduated_allocation_track",
                        "artifact": "CapitalAllocationConfig.harvest_gain_pct_floor",
                    },
                ],
            },
            {
                "id": "grace",
                "label": "Grace (hold buffer / momentum grace)",
                "question": "When a name leaves the target set, how long do we wait?",
                "phase_labels": ["grace", "exit_buffer"],
                "factors": [
                    {
                        "id": "exit_confirm_screens",
                        "question": "How many confirm screens before a rules exit?",
                        "status": "observing",
                        "experiment": "paper_churn.buffered_hold",
                        "artifact": "buffered_hold_counterfactual.json",
                    },
                    {
                        "id": "momentum_grace",
                        "question": "Does a momentum-grace overlay cut bad exits?",
                        "status": "observing",
                        "experiment": "momentum_grace_track",
                        "artifact": "learning_tracks_review",
                    },
                    {
                        "id": "intact_thesis_dampen",
                        "question": "Should an intact thesis dampen exit urgency?",
                        "status": "observing",
                        "experiment": "hypothesis_first_exit",
                        "artifact": "capital_allocation.exit_urgency",
                    },
                ],
            },
            {
                "id": "exit",
                "label": "Exit (leaving the book)",
                "question": "Rotate, hold for recovery, or cut a broken thesis?",
                "phase_labels": ["exit_pending", "exit_buffer"],
                "factors": [
                    {
                        "id": "thesis_broken_priority",
                        "question": "Rotate broken-thesis losers first?",
                        "status": "observing",
                        "experiment": "hypothesis_first_exit",
                        "artifact": "learning_tracks_hypothesis_outcomes.json",
                    },
                    {
                        "id": "swap_score_gate",
                        "question": "Only rotate when swap_score clears 2× round-trip cost?",
                        "status": "planned",
                        "experiment": "capital_rotation_coordinator",
                        "artifact": None,
                        "revisit_when": "exit_timing_cohorts >=10 closed swaps",
                    },
                    {
                        "id": "reentry_cooldown",
                        "question": "How long before a sold name may re-enter?",
                        "status": "observing",
                        "experiment": "paper_churn.reentry_cooldown",
                        "artifact": "paper_fund.reentry_cooldown",
                    },
                ],
            },
        ],
    }


def catalog_coverage(catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Count factors by status so the director can see uncovered stages."""
    payload = catalog or lifecycle_catalog()
    counts = {"observing": 0, "planned": 0, "deferred": 0, "other": 0}
    model_independent = 0
    uncovered_stages: list[str] = []
    by_stage: list[dict[str, Any]] = []
    for stage in payload.get("stages") or []:
        statuses = {"observing": 0, "planned": 0, "deferred": 0}
        for factor in stage.get("factors") or []:
            status = str(factor.get("status") or "other")
            if status in counts:
                counts[status] += 1
            else:
                counts["other"] += 1
            if status in statuses:
                statuses[status] += 1
            if factor.get("model_independent"):
                model_independent += 1
        if statuses["observing"] == 0:
            uncovered_stages.append(str(stage.get("id")))
        by_stage.append(
            {
                "id": stage.get("id"),
                "observing": statuses["observing"],
                "planned": statuses["planned"],
                "deferred": statuses["deferred"],
                "factor_count": sum(statuses.values()),
            }
        )
    total = sum(counts.values())
    return {
        "factor_count": total,
        "by_status": counts,
        "model_independent_factors": model_independent,
        "stages_without_observing_experiment": uncovered_stages,
        "by_stage": by_stage,
        "perpetual": not uncovered_stages,
        "note": (
            "Every stage should have ≥1 observing experiment. Planned factors "
            "activate when their revisit_when trigger fires — do not spawn a "
            "new paper book per factor."
        ),
    }


def factors_for_stage(stage_id: str, *, catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = catalog or lifecycle_catalog()
    for stage in payload.get("stages") or []:
        if str(stage.get("id")) == stage_id:
            return list(stage.get("factors") or [])
    return []


__all__ = [
    "BUILD_RATIO_CEILING",
    "HARVEST_RATIO_FLOOR",
    "LIFECYCLE_STAGE_IDS",
    "PHASE_TO_STAGE",
    "STARTER_RATIO_CEILING",
    "catalog_coverage",
    "factors_for_stage",
    "lifecycle_catalog",
    "stage_for_phase",
]
