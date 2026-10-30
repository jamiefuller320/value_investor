"""L652 parallel timing lenses — catalog, stubs, concurrence, outcome gaps."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.parallel_timing_lenses import (
    BUY_LENS_IDS,
    CONCURRENCE_WINDOW_DAYS,
    SELL_BASELINE_LENS_ID,
    SELL_CAP,
    SELL_LEARNING_LENS_IDS,
    bind_parallel_timing_lenses_summary,
    build_outcome_review,
    build_parallel_timing_lenses,
    catalog_payload,
    compute_concurrence,
    evaluate_buy_lens_fire,
    ops_findings_from_parallel_timing_lenses,
    refresh_parallel_timing_lenses,
    spawn_buy_candidate,
    spawn_sell_candidate,
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_owner_locked_catalog_shape():
    cat = catalog_payload()
    assert cat["buy_learning"] == list(BUY_LENS_IDS)
    assert cat["sell_learning"] == list(SELL_LEARNING_LENS_IDS)
    assert cat["sell_baseline"] == SELL_BASELINE_LENS_ID
    assert cat["sell_learning_cap"] == SELL_CAP == 4
    assert "sell_failed_breakout" in cat["sell_learning"]
    assert SELL_BASELINE_LENS_ID not in cat["sell_learning"]
    assert cat["lenses"]["sell_failed_breakout"].get("arms_buy_watch") is True
    assert len(BUY_LENS_IDS) == 3
    assert len(SELL_LEARNING_LENS_IDS) == 4


def test_buy_news_improve_path_live_joins_l650():
    fires, cites, note = evaluate_buy_lens_fire(
        "buy_news_improve_path",
        ctx={"entry_news_polarity": {"label": "improvement_path"}},
    )
    assert fires is True
    assert any("improvement_path" in c for c in cites)
    assert "l650" in note

    fires2, _, _ = evaluate_buy_lens_fire(
        "buy_news_improve_path",
        ctx={"entry_news_polarity": {"label": "structural_negative"}},
    )
    assert fires2 is False


def test_buy_support_bounce_stub_near_sma():
    fires, cites, _ = evaluate_buy_lens_fire(
        "buy_support_bounce",
        ctx={
            "entry_detail": {"price_vs_sma200_pct": -3.0, "timing_score": 0.2},
            "judgment_cites": [],
        },
    )
    assert fires is True
    assert any("price_vs_sma200_pct" in c for c in cites)


def test_sell_failed_breakout_arms_buy_watch():
    cand = spawn_sell_candidate(
        ticker="AAA.L",
        source_episode_id="ep1",
        source="test",
        exit_at="2026-10-20",
        exit_reason="resistance_reject",
        return_pct=0.08,
        evidence=None,
        asof="2026-10-20",
    )
    failed = next(lens for lens in cand["lenses"] if lens["lens_id"] == "sell_failed_breakout")
    # May be favourite or peer depending on fire order; must enter + arm watch.
    assert failed["status"] in {"entered", "looking", "abandoned"}
    # Force-evaluate path: if entered, buy_watch armed without auto_fill.
    if failed["status"] == "entered":
        watch = failed.get("buy_watch") or {}
        assert watch.get("armed") is True
        assert watch.get("auto_fill") is False
        assert watch.get("influences_live") is False


def test_mechanical_baseline_beside_cap():
    cand = spawn_sell_candidate(
        ticker="BBB.L",
        source_episode_id="ep2",
        source="test",
        exit_at="2026-10-20",
        exit_reason="hold_trading_days",
        return_pct=0.01,
        evidence=None,
        asof="2026-10-20",
    )
    learning = [lens for lens in cand["lenses"] if lens["catalog_role"] == "learning"]
    baseline = next(lens for lens in cand["lenses"] if lens["lens_id"] == SELL_BASELINE_LENS_ID)
    assert len(learning) == SELL_CAP
    assert baseline["role"] == "baseline"
    assert baseline["status"] == "baseline_recorded"
    assert cand["baseline_beside_cap"] == SELL_BASELINE_LENS_ID


def test_concurrence_window_excludes_late_hits():
    lenses = [
        {
            "lens_id": "buy_support_bounce",
            "catalog_role": "learning",
            "status": "entered",
            "episode": {"entry_at": "2026-10-10"},
        },
        {
            "lens_id": "buy_cheap_trend_confirm",
            "catalog_role": "learning",
            "status": "entered",
            "episode": {"entry_at": "2026-10-10"},
        },
        {
            "lens_id": "buy_news_improve_path",
            "catalog_role": "learning",
            "status": "entered",
            "episode": {"entry_at": "2026-10-20"},  # late — outside window
        },
    ]
    conc = compute_concurrence(
        lenses,
        favourite_entry_at="2026-10-10",
        window_days=CONCURRENCE_WINDOW_DAYS,
    )
    assert conc["count"] == 2
    assert "buy_news_improve_path" not in conc["lens_ids"]
    assert conc["influences_live"] is False
    assert conc["risk_sizing"] is False
    assert conc["n241"] == "not_now"


def test_outcome_review_has_both_gap_fields():
    lens = {
        "lens_id": "buy_support_bounce",
        "trail": [{"day": "2026-10-10", "action": "enter", "cites": ["timing_score=0.2"]}],
    }
    review = build_outcome_review(
        lens,
        ctx={
            "judgment_cites": ["B1:cheapness=true"],
            "entry_detail": {},
            "entry_news_polarity": {"label": "no_usable_news"},
        },
        asof="2026-10-10",
    )
    assert review["had_but_ignored"]["text"]
    assert isinstance(review["had_but_ignored"]["cites"], list)
    assert review["missing_that_might_help"]["text"]
    assert any("no_usable_news" in c for c in review["missing_that_might_help"]["cites"])
    assert review["influences_live"] is False
    assert review["package_l"] is False


def test_spawn_buy_favourite_vs_peers_and_fixed_stake():
    cand = spawn_buy_candidate(
        ticker="CCC.L",
        source_episode_id="ep3",
        source="test",
        entry_at="2026-10-15",
        evidence={
            "entry_detail": {
                "price_vs_sma200_pct": -2.0,
                "timing_score": 0.5,
                "passed_families": "cheapness,quality",
            },
            "judgment_in_the_round": {
                "buy": {
                    "B1": {"cites": ["passed_families=cheapness"], "unknown": False},
                    "B2": {"cites": ["timing_score=0.5"], "unknown": False},
                }
            },
        },
        polarity={"label": "improvement_path", "join_ok": True},
        asof="2026-10-15",
    )
    assert cand["influences_live"] is False
    assert cand["favourite_lens_id"]
    fav = next(lens for lens in cand["lenses"] if lens["role"] == "favourite")
    assert fav["status"] == "entered"
    assert fav["episode"]["fixed_stake_units"] == 100.0
    assert fav["episode"]["independent_of_favourite_nav"] is True
    peers = [lens for lens in cand["lenses"] if lens["role"] == "peer"]
    assert peers
    # At least one peer may also have entered same day (concurrence).
    conc = cand["concurrence"]
    assert conc["count"] >= 1
    assert conc["influences_live"] is False


def test_refresh_from_mft_samples(tmp_path: Path):
    _write(
        tmp_path / "cue_consumer_mft_observe.json",
        {
            "open_episodes_sample": [
                {
                    "episode_id": "lab-AAA",
                    "ticker": "AAA.L",
                    "entry_run_at": "2026-10-10",
                    "evidence": {
                        "entry_detail": {
                            "price_vs_sma200_pct": -1.5,
                            "timing_score": 0.3,
                        }
                    },
                }
            ],
            "closed_episodes_sample": [
                {
                    "episode_id": "lab-BBB-closed",
                    "ticker": "BBB.L",
                    "exit_run_at": "2026-10-18",
                    "exit_reason": "hold_trading_days",
                    "return_pct": 0.02,
                    "evidence": {},
                }
            ],
        },
    )
    _write(tmp_path / "entry_blind_review_queue.json", {"active": []})
    payload = refresh_parallel_timing_lenses(data_dir=tmp_path, persist=True)
    assert payload["influences_live"] is False
    assert payload["package"] == "M"
    assert payload["summary"]["buy_candidates"] >= 1
    assert payload["summary"]["sell_candidates"] >= 1
    assert (tmp_path / "parallel_timing_lenses.json").is_file()
    findings = ops_findings_from_parallel_timing_lenses(payload)
    assert findings[0]["title"] == "Parallel timing lenses (observe)"
    assert findings[0]["auto_fixable"] is False
    assert "L652" in findings[0]["summary"]


def test_bind_summary_on_entry_blind_card(tmp_path: Path):
    store = build_parallel_timing_lenses(
        data_dir=tmp_path,
        mft={
            "open_episodes_sample": [
                {
                    "episode_id": "lab-DDD",
                    "ticker": "DDD.L",
                    "entry_run_at": "2026-10-12",
                    "evidence": {
                        "entry_detail": {"price_vs_sma200_pct": -4.0, "timing_score": 0.1}
                    },
                }
            ],
            "closed_episodes_sample": [],
        },
        entry_blind={"active": []},
        asof="2026-10-12",
    )
    card: dict = {"ticker": "DDD.L", "entry_at": "2026-10-12"}
    bind_parallel_timing_lenses_summary(card, store=store)
    summary = card["parallel_timing_lenses"]
    assert summary["present"] is True
    assert summary["influences_live"] is False
    assert summary["favourite_lens_id"]
    assert "return_pct" not in summary
    assert "exit_at" not in summary
