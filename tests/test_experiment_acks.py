"""Tests for durable experiment ack matching and catalog aliases."""

from __future__ import annotations

from pathlib import Path

from value_investor.experiment_acks import (
    apply_ack_to_experiment,
    canonical_experiment_id,
    experiment_id_aliases,
    matching_ack,
    record_ack,
)
from value_investor.storage import write_json


def test_catalog_track_alias_canonicalizes_to_ledger_id():
    assert experiment_id_aliases("graduated_allocation_track") == frozenset(
        {"graduated_allocation_track", "graduated_allocation"}
    )
    assert (
        canonical_experiment_id(
            "graduated_allocation_track",
            known_ids={"graduated_allocation", "entry_dca_overlay"},
        )
        == "graduated_allocation"
    )


def test_matching_ack_accepts_catalog_alias(tmp_path: Path):
    data_dir = tmp_path
    write_json(data_dir / "experiment_acks.json", {"schema_version": 1, "acks": []})
    record_ack(
        data_dir,
        experiment_id="graduated_allocation_track",
        known_ids={"graduated_allocation"},
    )
    store = {
        "schema_version": 1,
        "acks": [
            {
                "experiment_id": "graduated_allocation",
                "decision": "ack_observe",
                "status": "open",
                "finding": {},
            }
        ],
    }
    assert matching_ack(store, experiment_id="graduated_allocation_track") is not None
    row = apply_ack_to_experiment(
        {
            "experiment_id": "graduated_allocation",
            "status": "recommend",
            "human_ack_required": True,
        },
        store,
    )
    assert row["human_acked"] is True
    assert row["human_ack_required"] is False


def test_record_ack_rewrites_catalog_alias(tmp_path: Path):
    write_json(tmp_path / "experiment_acks.json", {"schema_version": 1, "acks": []})
    ack = record_ack(
        tmp_path,
        experiment_id="graduated_allocation_track",
        note="factor=entry_appetite",
        known_ids={"graduated_allocation"},
    )
    assert ack["experiment_id"] == "graduated_allocation"
