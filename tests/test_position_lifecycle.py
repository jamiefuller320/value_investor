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
