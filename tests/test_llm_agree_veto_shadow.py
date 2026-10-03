"""Tests for observe-only algo → LLM agree/veto shadow cards."""

from value_investor.llm_agree_veto_shadow import (
    authorize_live_llm_influence,
    build_shadow_pass,
    extract_algo_proposals,
    has_justifying_evidence,
    judge_proposal,
    run_llm_agree_veto_shadow_pass,
)


def test_extract_algo_proposals_from_plan():
    plan = {
        "exits": [{"ticker": "PAF.L", "name": "Pan African", "reason": "left target"}],
        "holds": [{"ticker": "KLR.L", "name": "Keller", "reason": "near target"}],
        "buys": [{"ticker": "BP.L", "name": "BP", "reason": "New sleeve"}],
        "skipped": [
            {
                "ticker": "IMB.L",
                "name": "IMB",
                "reason": "Still-in-candidates rebuy block — name never left",
            }
        ],
    }
    proposals = extract_algo_proposals(plan=plan, trades=[])
    actions = {(p["ticker"], p["algo_action"]) for p in proposals}
    assert ("PAF.L", "sell") in actions
    assert ("KLR.L", "hold") in actions
    assert ("BP.L", "buy") in actions
    assert ("IMB.L", "rebuy_skip") in actions


def test_judge_vetoes_capacity_bump_sell():
    proposal = {
        "ticker": "PAF.L",
        "name": "Pan African",
        "algo_action": "sell",
        "algo_reason": "Automated exit — left target set",
    }
    candidate = {
        "ticker": "PAF.L",
        "signal": "buy",
        "conviction_score": 0.7,
        "research_verdict": "accumulate",
    }
    card = judge_proposal(
        proposal,
        candidate=candidate,
        buy_ranks={"PAF.L": 8},
        entry_ranks={"PAF.L": 7},
        rank_drop_exit_min=3,
        track_id="rules",
    )
    assert card.shadow_verdict == "veto"
    assert card.influences_live is False
    assert card.observe_only is True
    assert has_justifying_evidence(card)
    assert authorize_live_llm_influence(card) is False


def test_judge_agrees_decisive_leave_sell():
    proposal = {
        "ticker": "MEGP.L",
        "name": "MEGP",
        "algo_action": "sell",
        "algo_reason": "Automated exit — left target set",
    }
    candidate = {
        "ticker": "MEGP.L",
        "signal": "hold",
        "conviction_score": 0.2,
    }
    card = judge_proposal(
        proposal,
        candidate=candidate,
        buy_ranks={},
        entry_ranks={"MEGP.L": 2},
        track_id="rules",
    )
    assert card.shadow_verdict == "agree"
    assert has_justifying_evidence(card)


def test_fail_closed_live_influence_requires_evidence_and_flag():
    bare = {
        "influences_live": True,
        "observe_only": False,
        "reasons": [],
        "evidence": [],
    }
    assert authorize_live_llm_influence(bare) is False

    rich = {
        "influences_live": True,
        "observe_only": False,
        "reasons": ["Decisive leave"],
        "evidence": [{"kind": "screen_signal", "source": "candidates", "detail": "hold"}],
    }
    assert authorize_live_llm_influence(rich) is True

    # Observe cards never authorize even with evidence.
    observe = {
        "influences_live": False,
        "observe_only": True,
        "reasons": ["Decisive leave"],
        "evidence": [{"kind": "screen_signal", "source": "candidates", "detail": "hold"}],
    }
    assert authorize_live_llm_influence(observe) is False


def test_run_pass_writes_store_and_never_influences_live(tmp_path):
    plan = {
        "exits": [
            {
                "ticker": "PAF.L",
                "name": "Pan African",
                "reason": "No longer in the top conviction target set",
            }
        ],
        "holds": [],
        "buys": [],
        "skipped": [],
    }
    candidates = [
        {
            "ticker": "PAF.L",
            "name": "Pan African",
            "signal": "buy",
            "conviction_score": 0.71,
            "research_verdict": "accumulate",
        },
        {
            "ticker": "BP.L",
            "name": "BP",
            "signal": "buy",
            "conviction_score": 0.72,
        },
    ]
    payload = run_llm_agree_veto_shadow_pass(
        output_dir=tmp_path,
        track_id="rules",
        plan=plan,
        trades=[],
        candidates=candidates,
        holdings_before=[{"ticker": "PAF.L"}],
        rebalance_state_before={"entry_candidate_rank": {"PAF.L": 7}},
        as_of="2026-10-01T09:00:00+00:00",
    )
    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    assert payload["card_count"] == 1
    assert payload["cards"][0]["shadow_verdict"] == "veto"
    assert (tmp_path / "llm_agree_veto_shadow.json").exists()
    assert (tmp_path / "llm_agree_veto_shadow_review.json").exists()
    review = payload["review"]
    assert review["promotion_gate"]["ready_for_hard_veto"] is False
    assert review["veto_sell_count"] == 1


def test_judge_cards_carry_judge_spec_id():
    proposal = {
        "ticker": "PAF.L",
        "name": "Pan African",
        "algo_action": "sell",
        "algo_reason": "Automated exit — left target set",
    }
    card = judge_proposal(
        proposal,
        candidate={"ticker": "PAF.L", "signal": "buy", "conviction_score": 0.7},
        buy_ranks={"PAF.L": 8},
        entry_ranks={"PAF.L": 7},
        track_id="rules",
    )
    assert card.judge_spec_id == "heuristic.v1"
    payload = card.to_dict()
    assert payload["judge_spec_id"] == "heuristic.v1"
    assert "parent_spec_id" not in payload


def test_judge_cites_p1_live_inputs_without_live_influence():
    proposal = {
        "ticker": "KLR.L",
        "name": "Keller",
        "algo_action": "hold",
        "algo_reason": "Near target",
    }
    candidate = {
        "ticker": "KLR.L",
        "signal": "buy",
        "adjusted_signal": "buy",
        "conviction_score": 0.61,
        "research_verdict": "accumulate",
        "fcf_basis_overlay": False,
        "key_filing_bodies": True,
        "filings_with_body": 69,
        "has_index": True,
        "overlay_bound": True,
        "interim_eps_decline_pct": 0.02,
    }
    card = judge_proposal(
        proposal,
        candidate=candidate,
        buy_ranks={"KLR.L": 2},
        entry_ranks={"KLR.L": 2},
        holdings_before={"KLR.L"},
        track_id="ai_judgment",
    )
    kinds = {item["kind"] for item in card.evidence}
    assert kinds >= {
        "fcf_basis_overlay",
        "filing_presence",
        "overlay_bound",
        "interim_eps_decline_pct",
        "research_verdict",
    }
    assert card.influences_live is False
    assert card.observe_only is True
    assert card.meta["p1_live_inputs"]["key_filing_bodies"] is True

    challenger = judge_proposal(
        proposal,
        candidate={"ticker": "PAF.L", "signal": "buy", "conviction_score": 0.7},
        buy_ranks={"PAF.L": 8},
        entry_ranks={"PAF.L": 7},
        track_id="rules",
        judge_spec_id="heuristic.v2_rank_drop_4",
        parent_spec_id="heuristic.v1",
    ).to_dict()
    assert challenger["judge_spec_id"] == "heuristic.v2_rank_drop_4"
    assert challenger["parent_spec_id"] == "heuristic.v1"
    assert challenger["influences_live"] is False


def test_build_shadow_pass_includes_judge_spec_id():
    payload = build_shadow_pass(
        track_id="rules",
        plan={"exits": [{"ticker": "KLR.L", "reason": "left"}], "holds": [], "buys": []},
        trades=[],
        candidates=[{"ticker": "KLR.L", "signal": "hold", "conviction_score": 0.1}],
    )
    assert payload["judge_spec_id"] == "heuristic.v1"
    assert all(c.get("judge_spec_id") == "heuristic.v1" for c in payload["cards"])


def test_build_shadow_pass_strips_live_influence():
    payload = build_shadow_pass(
        track_id="ai_judgment",
        plan={"exits": [], "holds": [{"ticker": "KLR.L", "reason": "near target"}], "buys": []},
        trades=[],
        candidates=[{"ticker": "KLR.L", "signal": "buy", "conviction_score": 0.9}],
    )
    assert payload["card_count"] == 1
    assert all(c["influences_live"] is False for c in payload["cards"])
    assert all(c["observe_only"] is True for c in payload["cards"])
    assert all(has_justifying_evidence(c) for c in payload["cards"])
