"""Tests for the model-independent entry DCA overlay."""

import json
from pathlib import Path

from value_investor.entry_dca_overlay import (
    DEFAULT_CADENCES,
    EPISODES_FILENAME,
    REVIEW_FILENAME,
    DcaCadence,
    EntryDcaConfig,
    assess_framework_readiness,
    build_entry_dca_review,
    ingest_new_entries,
    run_entry_dca_overlay_pass,
    score_cadence,
    score_episode,
    summarize_learning_tracks_entry_dca,
    update_open_episodes,
)
from value_investor.review_payload_slim import slim_entry_dca


def _new_buy_trade(*, price: float = 100.0, notional: float = 1000.0, at: str = "2026-09-01T09:15:00+01:00"):
    return {
        "side": "buy",
        "ticker": "AAA.L",
        "price": price,
        "gross": notional,
        "shares": notional / price,
        "acted_at": at,
    }


def test_ingest_opens_episode_only_for_new_sleeves():
    store: dict = {"episodes": []}
    added = ingest_new_entries(
        store,
        track_id="rules",
        trades=[_new_buy_trade()],
        holdings_before=[],
        candidates=[{"ticker": "AAA.L", "signal": "buy", "timing_signal": "accumulate", "conviction_score": 0.7}],
        buy_cost_pct=0.03,
        as_of="2026-09-01T09:15:00+01:00",
    )
    assert added == 1
    episode = store["episodes"][0]
    assert episode["lifecycle_stage"] == "starter"
    assert episode["entry_kind"] == "first_entry"
    assert episode["status"] == "open"
    assert episode["conviction_score"] == 0.7

    added_again = ingest_new_entries(
        store,
        track_id="rules",
        trades=[_new_buy_trade()],
        holdings_before=[],
        candidates=[],
        buy_cost_pct=0.03,
        as_of="2026-09-01T09:15:00+01:00",
    )
    assert added_again == 0

    skipped_top_up = ingest_new_entries(
        store,
        track_id="rules",
        trades=[_new_buy_trade(at="2026-09-08T09:15:00+01:00")],
        holdings_before=[{"ticker": "AAA.L", "shares": 10}],
        candidates=[],
        buy_cost_pct=0.03,
        as_of="2026-09-08T09:15:00+01:00",
    )
    # Open episode already exists; also held — still skip.
    assert skipped_top_up == 0


def test_ingest_tags_recommit_after_prior_sell():
    store: dict = {"episodes": []}
    ingest_new_entries(
        store,
        track_id="rules",
        trades=[_new_buy_trade()],
        holdings_before=[],
        candidates=[],
        buy_cost_pct=0.03,
        as_of="2026-09-01T09:15:00+01:00",
        alumni_tickers={"AAA.L"},
    )
    episode = store["episodes"][0]
    assert episode["entry_kind"] == "recommit"
    assert episode["lifecycle_stage"] == "recommit"


def test_cadence_review_ranks_first_entry_only():
    store = {
        "episodes": [
            {
                "status": "closed",
                "entry_kind": "first_entry",
                "any_de_risk": True,
                "winning_cadence": "dca_2x_weekly",
                "cadence_scores": [
                    {"id": "dca_2x_weekly", "scored": True, "end_value_delta": 10.0, "de_risk_gbp": 5.0},
                ],
            },
            {
                "status": "closed",
                "entry_kind": "recommit",
                "any_de_risk": True,
                "winning_cadence": "dca_4x_weekly",
                "cadence_scores": [
                    {"id": "dca_4x_weekly", "scored": True, "end_value_delta": 99.0, "de_risk_gbp": 9.0},
                ],
            },
        ]
    }
    review = build_entry_dca_review(store, track_id="rules")
    assert review["scored_count"] == 1
    assert review["recommit_scored_count"] == 1
    assert review["winning_cadence_counts"] == {"dca_2x_weekly": 1}
    assert "dca_4x_weekly" not in review["winning_cadence_counts"]


def test_dca_de_risks_when_price_drops_after_entry():
    episode = {
        "started_at": "2026-09-01",
        "entry_price": 100.0,
        "notional": 1000.0,
        "buy_cost_pct": 0.0,
        "marks": [
            {"as_of": "2026-09-01", "price": 100.0},
            {"as_of": "2026-09-08", "price": 80.0},
        ],
    }
    lump = score_cadence(episode, DcaCadence("lump_sum", 1, 0, "lump"))
    weekly = score_cadence(episode, DcaCadence("dca_2x_weekly", 2, 7, "50/50"))
    assert weekly["avg_fill"] < lump["avg_fill"]
    assert weekly["fill_advantage_pct"] > 0
    summary = score_episode(episode)
    dca = next(row for row in summary["cadence_scores"] if row["id"] == "dca_2x_weekly")
    assert dca["de_risk_gbp"] > 0


def test_dca_opportunity_cost_when_price_runs():
    episode = {
        "started_at": "2026-09-01",
        "entry_price": 100.0,
        "notional": 1000.0,
        "buy_cost_pct": 0.0,
        "marks": [
            {"as_of": "2026-09-01", "price": 100.0},
            {"as_of": "2026-09-08", "price": 120.0},
        ],
    }
    weekly = score_cadence(episode, DcaCadence("dca_2x_weekly", 2, 7, "50/50"))
    assert weekly["avg_fill"] > 100.0
    assert weekly["end_value_delta"] < 0


def test_update_closes_after_window_and_scores():
    store: dict = {"episodes": []}
    ingest_new_entries(
        store,
        track_id="ai_judgment",
        trades=[_new_buy_trade()],
        holdings_before=[],
        candidates=[],
        buy_cost_pct=0.01,
        as_of="2026-09-01T09:15:00+01:00",
    )
    cfg = EntryDcaConfig(cadences=DEFAULT_CADENCES)
    progress = update_open_episodes(
        store,
        prices_by_ticker={"AAA.L": 90.0},
        held_tickers={"AAA.L"},
        as_of="2026-09-29T09:15:00+01:00",
        cfg=cfg,
    )
    assert progress["closed"] == 1
    episode = store["episodes"][0]
    assert episode["status"] == "closed"
    assert episode["close_reason"] == "window_elapsed"
    assert episode["winning_cadence"]


def test_run_pass_writes_artifacts(tmp_path: Path):
    review = run_entry_dca_overlay_pass(
        output_dir=tmp_path,
        track_id="rules",
        trades=[_new_buy_trade()],
        holdings_before=[],
        holdings_after_tickers={"AAA.L"},
        candidates=[{"ticker": "AAA.L", "signal": "buy"}],
        prices_by_ticker={"AAA.L": 100.0},
        buy_cost_pct=0.03,
        as_of="2026-09-01T09:15:00+01:00",
    )
    assert review["open_count"] == 1
    assert (tmp_path / EPISODES_FILENAME).exists()
    assert (tmp_path / REVIEW_FILENAME).exists()


def test_readiness_and_slim_rollup(tmp_path: Path):
    assert assess_framework_readiness(closed_episodes=4, tracks_with_closed=1)[
        "ready_for_cadence_analysis"
    ] is False
    assert assess_framework_readiness(closed_episodes=12, tracks_with_closed=2)[
        "ready_for_cadence_analysis"
    ] is True

    paper = tmp_path / "paper"
    paper.mkdir(parents=True)
    (paper / REVIEW_FILENAME).write_text(
        json.dumps(
            {
                "scored_count": 8,
                "closed_count": 8,
                "any_de_risk_count": 5,
                "winning_cadence_counts": {"dca_2x_weekly": 5, "dca_4x_weekly": 3},
            }
        ),
        encoding="utf-8",
    )
    ai = paper / "ai_judgment"
    ai.mkdir(parents=True)
    (ai / REVIEW_FILENAME).write_text(
        json.dumps(
            {
                "scored_count": 6,
                "closed_count": 6,
                "any_de_risk_count": 4,
                "winning_cadence_counts": {"dca_2x_weekly": 4},
            }
        ),
        encoding="utf-8",
    )
    rollup = summarize_learning_tracks_entry_dca(paper)
    assert rollup["scored_count"] == 14
    assert rollup["tracks_with_closed"] == 2
    assert rollup["leading_cadence"] == "dca_2x_weekly"
    assert rollup["model_independent_hint"] is True
    assert rollup["readiness"]["ready_for_cadence_analysis"] is True
    assert rollup["lifecycle_catalog"]["coverage"]["perpetual"] is True

    slim = slim_entry_dca(rollup)
    assert slim is not None
    assert slim["leading_cadence"] == "dca_2x_weekly"
    assert slim["readiness"]["ready_for_cadence_analysis"] is True
    assert slim["lifecycle_coverage"]["perpetual"] is True
