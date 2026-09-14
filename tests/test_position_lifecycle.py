"""Tests for the entry–exit lifecycle factor catalog."""

from value_investor.position_lifecycle import (
    LIFECYCLE_STAGE_IDS,
    catalog_coverage,
    factors_for_stage,
    lifecycle_catalog,
    stage_for_phase,
)


def test_catalog_covers_all_stages_with_an_observing_experiment():
    catalog = lifecycle_catalog()
    stage_ids = [str(stage["id"]) for stage in catalog["stages"]]
    assert tuple(stage_ids) == LIFECYCLE_STAGE_IDS
    coverage = catalog_coverage(catalog)
    assert coverage["perpetual"] is True
    assert coverage["stages_without_observing_experiment"] == []
    assert coverage["by_status"]["observing"] >= 7
    assert coverage["model_independent_factors"] >= 2


def test_dca_factors_are_model_independent():
    starter = {row["id"]: row for row in factors_for_stage("starter")}
    assert starter["entry_dca_cadence"]["model_independent"] is True
    assert starter["entry_dca_cadence"]["status"] == "observing"
    build = {row["id"]: row for row in factors_for_stage("build")}
    assert build["add_cadence"]["model_independent"] is True
    assert build["add_only_if_cheaper"]["status"] == "planned"
    assert build["skim_linked_remaining_adds"]["status"] == "planned"
    assert build["skim_linked_remaining_adds"]["model_independent"] is True


def test_stage_for_phase_collapses_labels():
    assert stage_for_phase("prospect_ready") == "prospect"
    assert stage_for_phase("starter") == "starter"
    assert stage_for_phase("exit_buffer") == "exit"
    assert stage_for_phase("hold") == "full"
    assert stage_for_phase("recommit") == "recommit"


def test_recommit_stage_is_observing_via_entry_kind_tag():
    recommit = {row["id"]: row for row in factors_for_stage("recommit")}
    assert recommit["entry_kind_tag"]["status"] == "observing"
    assert recommit["held_addon_pyramid"]["status"] == "deferred"


def test_board_columns_cover_every_catalog_factor():
    from value_investor.position_lifecycle import BOARD_COLUMN_IDS, BOARD_COLUMNS, board_column_defs

    catalog = lifecycle_catalog()
    factor_ids = {str(factor["id"]) for stage in catalog["stages"] for factor in stage["factors"]}
    mapped = {fid for col in BOARD_COLUMNS for fid in col["factor_ids"]}
    assert tuple(col["id"] for col in BOARD_COLUMNS) == BOARD_COLUMN_IDS
    assert mapped == factor_ids
    columns = board_column_defs(
        assessment={
            "experiments": [
                {
                    "experiment_id": "entry_dca_overlay",
                    "title": "DCA overlay",
                    "status": "recommend",
                    "kind": "lifecycle_overlay",
                    "human_ack_required": False,
                    "human_acked": True,
                    "forward_evidence": {
                        "scored_count": 22,
                        "tracks_with_closed": 9,
                        "leading_cadence": "dca_4x_weekly",
                        "ready_for_cadence_analysis": True,
                    },
                }
            ],
            "entry_dca_adoption": {
                "current_stage": "out_of_sample_first_entry",
                "acked": True,
                "stages": [
                    {
                        "id": "out_of_sample_first_entry",
                        "status": "open",
                        "ready": False,
                        "revisit_when": "ai_judgment first_entry>=3, rules first_entry>=1",
                        "do_not": "Do not treat failing calibration shadows as live-book confirmation",
                    }
                ],
            },
        }
    )
    assert len(columns) == len(BOARD_COLUMN_IDS)
    starter = next(col for col in columns if col["id"] == "just_bought")
    dca = next(row for row in starter["experiments"] if row["factor_id"] == "entry_dca_cadence")
    assert dca["assessment_status"] == "recommend"
    assert dca["model_independent"] is True
    assert dca["aim"]
    assert dca["progress"]["scored_count"] == 22
    assert dca["initiation"]["ready_to_initiate"] is False
    assert "first_entry" in str(dca["initiation"]["waiting_for"])
    planned = next(
        row for row in starter["experiments"] if row["factor_id"] == "first_fill_adverse_pause"
    )
    assert planned["initiation"]["kind"] == "planned"
    assert planned["initiation"]["ready_to_initiate"] is False
