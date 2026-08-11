"""Tests for monthly horizon scan synthesis."""

from pathlib import Path

from value_investor.horizon_scan import (
    apply_fragment_actions,
    apply_park_proposals,
    build_horizon_payload,
    compile_horizon_tasks,
    has_enough_horizon_inputs,
    parse_fragment_actions,
    parse_horizon_scan,
    parse_park_proposals,
    promote_horizon_engineering_tasks,
)

SAMPLE_REVIEW = """
STAGE READINESS
- Stage 2b focus; paper marks thin.

EVIDENCE STRANDS
- exit_timing cohorts collecting.

AUTOMATION RISKS
- No auto knob apply yet.

COUNTERFACTUAL GAPS
- Archive replay incomplete for near-miss names.

FRAGMENT CLUSTERING
- Cluster A: exit timing
- DROP frag-20260811-01
- PROMOTE frag-20260811-02 → **Hold buffer priors** — needs archive sim. Revisit when: 15 closed holds

PARK
- **Archive daily marks** — optional resolution upgrade. Revisit when: weekly snapshots too coarse

ACCELERATE
1. [offline_sim] Run near-miss archive sim monthly — priors for grace knobs
"""


def test_parse_horizon_scan_sections():
    review = parse_horizon_scan(SAMPLE_REVIEW)
    assert "Stage 2b" in review.stage_readiness
    assert "exit_timing" in review.evidence_strands
    assert "offline_sim" in review.accelerate


def test_parse_park_proposals_extracts_revisit():
    proposals = parse_park_proposals(
        "- **Daily marks lab** — walk forward prices. Revisit when: checkpoints misaligned"
    )
    assert len(proposals) == 1
    assert proposals[0]["title"] == "Daily marks lab"
    assert "walk forward" in proposals[0]["summary"]
    assert "checkpoints" in proposals[0]["revisit_when"]


def test_parse_fragment_actions_drop_and_promote():
    drops, promotes = parse_fragment_actions(
        "- DROP frag-20260811-01\n"
        "- PROMOTE frag-20260811-02 → **Title** — summary. Revisit when: N>=15"
    )
    assert drops == ["frag-20260811-01"]
    assert promotes[0]["fragment_id"] == "frag-20260811-02"
    assert promotes[0]["title"] == "Title"


def test_apply_park_and_fragments(tmp_path: Path):
    store = tmp_path / "deferred-ideas.json"
    from value_investor.deferred_ideas import add_fragment

    drop_frag, _ = add_fragment("drop me", store_path=store)
    promote_frag, _ = add_fragment("promote this", store_path=store)

    text = (
        f"- DROP {drop_frag['id']}\n"
        f"- PROMOTE {promote_frag['id']} → **Promoted idea** — from fragment. "
        "Revisit when: test gate\n"
    )
    result = apply_fragment_actions(text, store_path=store, promote_to_defer=True)
    assert drop_frag["id"] in result["dropped_fragments"]
    assert promote_frag["id"] in result["promoted_fragments"]
    assert result["deferred_ids"]

    added = apply_park_proposals(
        parse_park_proposals("- **New park** — summary line. Revisit when: later"),
        store_path=store,
    )
    assert added


def test_compile_horizon_tasks(tmp_path: Path):
    review = parse_horizon_scan(SAMPLE_REVIEW)
    tasks_path = tmp_path / "horizon_tasks.json"
    payload = compile_horizon_tasks(review, tasks_path=tasks_path)
    assert payload["task_count"] >= 1
    assert any(row.get("id", "").startswith("hor-") for row in payload["tasks"])


def test_build_horizon_payload_includes_fragments(tmp_path: Path):
    defer = tmp_path / "deferred-ideas.json"
    from value_investor.deferred_ideas import add_fragment

    add_fragment("scratch thought", tags=["test"], store_path=defer)
    payload = build_horizon_payload(
        data_dir=tmp_path,
        output_dir=tmp_path / "out",
        deferred_path=defer,
    )
    assert len(payload.get("open_fragments") or []) == 1
    ok, _ = has_enough_horizon_inputs(payload)
    assert ok


def test_promote_horizon_engineering_tasks(tmp_path: Path):
    horizon_path = tmp_path / "horizon_tasks.json"
    eng_path = tmp_path / "engineering_tasks.json"
    eng_path.write_text('{"tasks": []}\n', encoding="utf-8")
    review = parse_horizon_scan(
        "ACCELERATE\n"
        "1. [offline_sim] Archive replay — full P&L\n"
        "2. [paper_knobs] Hold knobs — manual only\n"
    )
    compile_horizon_tasks(review, tasks_path=horizon_path)
    result = promote_horizon_engineering_tasks(
        promote_all_engineering=True,
        horizon_tasks_path=horizon_path,
        engineering_tasks_path=eng_path,
    )
    assert len(result["promoted"]) == 1
    assert any(skip["reason"].startswith("area paper_knobs") for skip in result["skipped"])
    eng = __import__("json").loads(eng_path.read_text())
    assert any(row["id"].startswith("eng-") for row in eng["tasks"])
