"""Deterministic fragment weeding."""

from pathlib import Path

from value_investor.deferred_ideas import add_fragment, add_idea, list_open_fragments
from value_investor.fragment_weeder import (
    apply_fragment_weeds,
    propose_fragment_weeds,
    weed_fragments,
)


def test_weeder_drops_near_duplicate_keeps_oldest(tmp_path: Path):
    store = tmp_path / "deferred-ideas.json"
    first, _ = add_fragment(
        "exit timing versus counterfactual replay still fuzzy",
        store_path=store,
    )
    add_fragment(
        "exit timing vs counterfactual replay is still fuzzy",
        store_path=store,
    )
    add_fragment("unrelated ingest filing body gap on euro_depth", store_path=store)

    proposal = propose_fragment_weeds(store_path=store)
    drops = [row for row in proposal["actions"] if row["action"] == "DROP"]
    keeps = [row for row in proposal["actions"] if row["action"] == "KEEP"]
    assert proposal["drop_count"] == 1
    assert drops[0]["reason"] == "near_duplicate"
    assert drops[0]["canonical_id"] == first["id"]
    assert any(row["reason"] == "unique" for row in keeps)

    applied = apply_fragment_weeds(proposal, store_path=store)
    assert applied["dropped"] == [drops[0]["fragment_id"]]
    open_ids = {row["id"] for row in list_open_fragments(store_path=store)}
    assert first["id"] in open_ids
    assert drops[0]["fragment_id"] not in open_ids


def test_weeder_drops_fragment_already_an_open_idea(tmp_path: Path):
    store = tmp_path / "deferred-ideas.json"
    add_idea(
        title="Dashboard card for system_gaps flags",
        summary="Show high learning-path integrity flags on the overview dashboard.",
        store_path=store,
    )
    frag, _ = add_fragment(
        "Dashboard card for system_gaps flags on the overview",
        store_path=store,
    )
    proposal = propose_fragment_weeds(store_path=store)
    drop = next(row for row in proposal["actions"] if row["fragment_id"] == frag["id"])
    assert drop["action"] == "DROP"
    assert drop["reason"] == "already_open_idea"


def test_weeder_drops_fragment_already_a_done_idea(tmp_path: Path):
    store = tmp_path / "deferred-ideas.json"
    add_idea(
        title="Fragment weeding and cluster-dedupe",
        summary="Weed near-duplicate fragments before raising the director cap.",
        status="done",
        store_path=store,
    )
    frag, _ = add_fragment(
        "Fragment weeding and cluster-dedupe before raising the director cap",
        store_path=store,
    )
    proposal = propose_fragment_weeds(store_path=store)
    drop = next(row for row in proposal["actions"] if row["fragment_id"] == frag["id"])
    assert drop["reason"] == "already_done_idea"


def test_weed_fragments_apply_roundtrip(tmp_path: Path):
    store = tmp_path / "deferred-ideas.json"
    add_fragment("same thought about overlay persist hole", store_path=store)
    add_fragment("same thought about overlay persist hole again", store_path=store)
    result = weed_fragments(store_path=store, apply=True)
    assert result["applied"] is True
    assert result["apply"]["open_remaining"] == 1
