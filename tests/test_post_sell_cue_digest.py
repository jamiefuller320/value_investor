"""Tests for observe-only post-sell cue digest (package M + epoch gate)."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.ops_monitor import check_post_sell_cue_digest
from value_investor.post_sell_cue_digest import (
    FINDING_TITLE,
    WIDEN_GATE,
    build_post_sell_cue_digest,
    refresh_post_sell_cue_digest,
)
from value_investor.review_payload_slim import slim_post_sell_cue_digest


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _base_inputs(data_dir: Path, paper: Path) -> None:
    _write(
        data_dir / "n200_tech_timing_observe.json",
        {
            "registration_id": "strand-b-plain-value-tech-timing-v0",
            "completed_entry_episodes": 10,
            "per_lever_scoreboards": {
                "entry_verdict": "win",
                "exit_verdict": "lose",
            },
            "volume_gate": {"met": True},
        },
    )
    _write(
        paper / "learning_tracks_exit_timing.json",
        {
            "tracks": {
                "buy_tier_level": {
                    "readiness": {
                        "ready_for_probability_analysis": False,
                        "hold_closed_count": 29,
                        "swap_closed_count": 0,
                        "gaps": ["swap_rotation closed rotations=0"],
                    }
                },
                "buy_tier_level_dca": {
                    "readiness": {
                        "ready_for_probability_analysis": False,
                        "hold_closed_count": 14,
                        "swap_closed_count": 0,
                        "gaps": ["swap_rotation closed rotations=0"],
                    }
                },
                "ai_judgment_fair": {
                    "readiness": {
                        "ready_for_probability_analysis": False,
                        "hold_closed_count": 11,
                        "swap_closed_count": 0,
                        "gaps": ["swap_rotation closed rotations=0"],
                    }
                },
            }
        },
    )
    _write(
        paper / "learning_tracks_exit_shadow.json",
        {
            "tracks": {
                "buy_tier_level": {
                    "closed_count": 0,
                    "open_count": 29,
                    "by_exit_kind": {"screen_rotation": 29},
                }
            }
        },
    )
    _write(
        data_dir / "exit_timing_near_miss_review.json",
        {
            "generated_at": "2026-08-25T00:00:00+00:00",
            "readiness": {
                "ready_for_probability_analysis": True,
                "hold_closed_count": 202,
                "swap_closed_count": 209,
            },
        },
    )
    _write(
        data_dir / "latest.json",
        {
            "reports": [
                {"ticker": "AAA.L", "signal": "buy"},
                {"ticker": "BBB.L", "signal": "hold"},
            ]
        },
    )
    _write(
        data_dir / "loser_snapshot_cards.json",
        {
            "cards": [
                {
                    "ticker": "BBB.L",
                    "cohorts": ["avoid"],
                    "screen": {
                        "signal": "avoid",
                        "conviction_score": 0.1,
                        "composite_score": 0.2,
                    },
                }
            ]
        },
    )


def _selection_knobs(**overrides: object) -> dict:
    base = {
        "skip_timing_wait": True,
        "min_conviction": 0.0,
        "sector_cap": 1.0,
        "use_adjusted_signal": False,
        "require_research_accumulate": False,
        "use_momentum_grace": False,
        "use_graduated_allocation": False,
        "exit_confirm_screens": 2,
        "reentry_cooldown_screens": 1,
        "min_rebalance_notional_gbp": 10.0,
    }
    base.update(overrides)
    return base


def _rebalance_pass(
    *,
    logged_at: str,
    trades: list[dict],
    screen_buy_tier: list[dict],
    selection: dict | None = None,
    knob_epoch_started_at: str | None = None,
    include_knob_field: bool = True,
) -> dict:
    entry: dict = {
        "schema_version": 2,
        "logged_at": logged_at,
        "track_id": "buy_tier_level",
        "track_label": "Buy-tier level cohort (raw screen, Suite B costs, cold start)",
        "screen_source": {
            "path": "docs/data/latest.json",
            "run_at": "2026-10-09T06:00:00+00:00",
            "generated_at": "2026-10-10T06:00:00+00:00",
        },
        "acted": True,
        "selection": selection or _selection_knobs(),
        "trade_cost_pct": 0.0028,
        "candidates": list(screen_buy_tier),
        "screen_buy_tier": screen_buy_tier,
        "trades": trades,
        "holdings_before": [],
        "holdings_after": [],
    }
    if include_knob_field:
        entry["knob_epoch_started_at"] = knob_epoch_started_at
    return entry


def test_build_digest_timing_and_selection_skeleton(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    paper = data_dir / "paper_automation"
    _base_inputs(data_dir, paper)
    _write(
        paper / "buy_tier_level" / "automated_fund.json",
        {
            "config": {
                "name": "Buy-tier level cohort (raw screen, Suite B costs, cold start)",
                "created_at": "2026-09-07T08:29:59.366634+00:00",
            },
            "trades": [
                {
                    "side": "buy",
                    "ticker": "AAA.L",
                    "acted_at": "2026-09-20T12:00:00+00:00",
                    "price": 100.0,
                },
                {
                    "id": "sell-aaa",
                    "side": "sell",
                    "position_closed": True,
                    "ticker": "AAA.L",
                    "name": "Aaa",
                    "acted_at": "2026-10-10T12:00:00+00:00",
                    "price": 110.0,
                    "avg_cost_at_exit": 100.0,
                    "note": "left target set",
                },
                {
                    "side": "buy",
                    "ticker": "BBB.L",
                    "acted_at": "2026-10-01T12:00:00+00:00",
                    "price": 100.0,
                },
                {
                    "id": "sell-bbb",
                    "side": "sell",
                    "position_closed": True,
                    "ticker": "BBB.L",
                    "name": "Bbb",
                    "acted_at": "2026-10-11T12:00:00+00:00",
                    "price": 80.0,
                    "avg_cost_at_exit": 100.0,
                    "note": "left target set",
                },
                {
                    "side": "buy",
                    "ticker": "CCC.L",
                    "price": 1.0,
                },
            ],
        },
    )
    _write(
        paper / "buy_tier_level" / "rebalance_log.json",
        [
            _rebalance_pass(
                logged_at="2026-10-10T11:00:00+00:00",
                trades=[
                    {
                        "id": "sell-aaa",
                        "side": "sell",
                        "ticker": "AAA.L",
                        "acted_at": "2026-10-10T12:00:00+00:00",
                    }
                ],
                screen_buy_tier=[
                    {"ticker": "AAA.L", "signal": "hold", "name": "Aaa"},
                    {"ticker": "ZZZ.L", "signal": "buy", "name": "Zzz"},
                ],
            ),
            _rebalance_pass(
                logged_at="2026-10-11T11:00:00+00:00",
                trades=[
                    {
                        "id": "sell-bbb",
                        "side": "sell",
                        "ticker": "BBB.L",
                        "acted_at": "2026-10-11T12:00:00+00:00",
                    }
                ],
                screen_buy_tier=[
                    {"ticker": "BBB.L", "signal": "hold", "name": "Bbb"},
                ],
            ),
        ],
    )
    _write(
        paper / "buy_tier_level" / "exit_shadow.json",
        {
            "records": [
                {
                    "trade_id": "sell-aaa",
                    "ticker": "AAA.L",
                    "exit_kind": "screen_rotation",
                    "exited_at": "2026-10-10T12:00:00+00:00",
                    "checkpoints": [
                        {
                            "days_after": 7,
                            "return_since_exit_pct": 0.02,
                            "peak_since_exit_pct": 0.03,
                        }
                    ],
                },
                {
                    "trade_id": "sell-bbb",
                    "ticker": "BBB.L",
                    "exit_kind": "screen_rotation",
                    "exited_at": "2026-10-11T12:00:00+00:00",
                    "checkpoints": [],
                },
            ]
        },
    )

    payload = build_post_sell_cue_digest(data_dir=data_dir, paper_root=paper)
    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    assert payload["schema_version"] == 2
    assert payload["widen_gate"]["widened"] is False
    assert payload["widen_gate"]["locked"] is True
    assert WIDEN_GATE["fork"] == "F"

    n200_cue = next(c for c in payload["timing_cues"] if c["cue_id"] == "n200_entry_exit_levers")
    assert n200_cue["registration_id"] == "strand-b-plain-value-tech-timing-v0"
    assert "population ≠ FTSE control" in n200_cue["claim"]
    assert any(c["cue_id"] == "exit_timing_ready_ftse" for c in payload["timing_cues"])
    assert not any(
        str(c["cue_id"]).startswith("exit_timing_ready:") for c in payload["timing_cues"]
    )
    assert any(c["lane"] == "selection" for c in payload["selection_cues"])

    skeleton = payload["selection_postmortem_skeleton"]
    assert skeleton["sealed"] is False
    assert skeleton["feeds"] == "N205"
    assert skeleton["row_count"] == 2
    rows = {r["ticker"]: r for r in skeleton["rows"]}
    assert rows["AAA.L"]["in_buy_set_now"] is True
    assert rows["AAA.L"]["still_in_buy_set"] is True  # legacy alias = now
    assert rows["AAA.L"]["still_in_buy_set_as_of"] == "latest_json_now"
    assert rows["AAA.L"]["in_buy_set_at_exit"] is False
    assert rows["AAA.L"]["realized_pct"] == 10.0
    assert rows["AAA.L"]["entry_at"] == "2026-09-20T12:00:00+00:00"
    assert rows["AAA.L"]["hold_days"] == 20
    assert rows["AAA.L"]["exit_kind"] == "screen_rotation"
    assert rows["AAA.L"]["epoch_join_ok"] is True
    assert rows["AAA.L"]["epoch_lesson_status"] == "current_epoch"
    assert "knob_epoch_started_at" in rows["AAA.L"]["epoch"]
    assert rows["AAA.L"]["epoch"]["selection_fingerprint"]
    assert rows["AAA.L"]["epoch"]["screen_source_generated_at"]
    assert rows["AAA.L"]["post_exit_7d"]["post_exit_7d_return_pct"] == 2.0
    assert rows["BBB.L"]["in_buy_set_now"] is False
    assert rows["BBB.L"]["in_buy_set_at_exit"] is False
    assert rows["BBB.L"]["loser_card"]["signal"] == "avoid"

    assert payload["epoch"]["epoch_unknown_count"] == 0
    assert payload["control_closed_sells"]["cue_closed_sell_count"] == 2

    hub = payload["hub_feed"]
    assert hub["push_candidates"] == []
    assert len(hub["explore_candidates"]) >= 1
    assert all(c.get("not_today") for c in hub["explore_candidates"])
    slim = slim_post_sell_cue_digest(payload)
    assert slim is not None
    assert slim["selection_postmortem_skeleton"]["sealed"] is False
    assert slim["artifact"] == "docs/data/post_sell_cue_digest.json"


def test_epoch_join_fail_closed_excludes_unknown_from_cues(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    paper = data_dir / "paper_automation"
    _base_inputs(data_dir, paper)
    _write(
        paper / "buy_tier_level" / "automated_fund.json",
        {
            "config": {"created_at": "2026-09-07T00:00:00+00:00"},
            "trades": [
                {
                    "id": "sell-joined",
                    "side": "sell",
                    "position_closed": True,
                    "ticker": "JOIN.L",
                    "acted_at": "2026-10-10T12:00:00+00:00",
                    "price": 110.0,
                    "avg_cost_at_exit": 100.0,
                },
                {
                    "id": "sell-orphan",
                    "side": "sell",
                    "position_closed": True,
                    "ticker": "ORPH.L",
                    "acted_at": "2026-10-11T12:00:00+00:00",
                    "price": 90.0,
                    "avg_cost_at_exit": 100.0,
                },
            ],
        },
    )
    _write(
        paper / "buy_tier_level" / "rebalance_log.json",
        [
            _rebalance_pass(
                logged_at="2026-10-10T11:00:00+00:00",
                trades=[
                    {
                        "id": "sell-joined",
                        "side": "sell",
                        "ticker": "JOIN.L",
                        "acted_at": "2026-10-10T12:00:00+00:00",
                    }
                ],
                screen_buy_tier=[{"ticker": "JOIN.L", "signal": "hold"}],
            )
        ],
    )

    payload = build_post_sell_cue_digest(data_dir=data_dir, paper_root=paper)
    rows = {r["ticker"]: r for r in payload["selection_postmortem_skeleton"]["rows"]}
    assert rows["JOIN.L"]["epoch_join_ok"] is True
    assert rows["ORPH.L"]["epoch_join_ok"] is False
    assert rows["ORPH.L"]["epoch_lesson_status"] == "epoch_unknown"
    assert rows["ORPH.L"]["epoch"] is None
    assert payload["epoch"]["epoch_unknown_count"] == 1
    assert payload["control_closed_sells"]["cue_closed_sell_count"] == 1
    # Orphan must not appear in cue sample / buckets population count.
    bucket_cue = next(
        c for c in payload["selection_cues"] if c["cue_id"] == "selection_realized_buckets"
    )
    assert bucket_cue["evidence"]["closed_sell_count_cue"] == 1
    assert bucket_cue["evidence"]["epoch_unknown_excluded"] == 1
    assert "ORPH.L" not in bucket_cue["evidence"].get("sample_tickers", [])


def test_epoch_join_missing_knob_field_fail_closed(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    paper = data_dir / "paper_automation"
    _base_inputs(data_dir, paper)
    _write(
        paper / "buy_tier_level" / "automated_fund.json",
        {
            "config": {"created_at": "2026-09-07T00:00:00+00:00"},
            "trades": [
                {
                    "id": "sell-noknob",
                    "side": "sell",
                    "position_closed": True,
                    "ticker": "NOK.L",
                    "acted_at": "2026-10-10T12:00:00+00:00",
                    "price": 100.0,
                    "avg_cost_at_exit": 100.0,
                }
            ],
        },
    )
    _write(
        paper / "buy_tier_level" / "rebalance_log.json",
        [
            _rebalance_pass(
                logged_at="2026-10-10T11:00:00+00:00",
                trades=[
                    {
                        "id": "sell-noknob",
                        "side": "sell",
                        "ticker": "NOK.L",
                        "acted_at": "2026-10-10T12:00:00+00:00",
                    }
                ],
                screen_buy_tier=[{"ticker": "NOK.L", "signal": "hold"}],
                include_knob_field=False,
            )
        ],
    )
    payload = build_post_sell_cue_digest(data_dir=data_dir, paper_root=paper)
    row = payload["selection_postmortem_skeleton"]["rows"][0]
    assert row["epoch_join_ok"] is False
    assert row["epoch_lesson_status"] == "epoch_unknown"
    assert any(c["cue_id"] == "selection_epoch_join_failed" for c in payload["selection_cues"])


def test_stratify_older_epoch_excluded_from_default_cues(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    paper = data_dir / "paper_automation"
    _base_inputs(data_dir, paper)
    _write(
        paper / "buy_tier_level" / "automated_fund.json",
        {
            "config": {"created_at": "2026-09-07T00:00:00+00:00"},
            "trades": [
                {
                    "id": "sell-old",
                    "side": "sell",
                    "position_closed": True,
                    "ticker": "OLD.L",
                    "acted_at": "2026-09-15T12:00:00+00:00",
                    "price": 90.0,
                    "avg_cost_at_exit": 100.0,
                },
                {
                    "id": "sell-new",
                    "side": "sell",
                    "position_closed": True,
                    "ticker": "NEW.L",
                    "acted_at": "2026-10-12T12:00:00+00:00",
                    "price": 120.0,
                    "avg_cost_at_exit": 100.0,
                },
            ],
        },
    )
    old_sel = _selection_knobs(exit_confirm_screens=1)
    new_sel = _selection_knobs(exit_confirm_screens=2)
    _write(
        paper / "buy_tier_level" / "rebalance_log.json",
        [
            _rebalance_pass(
                logged_at="2026-09-15T11:00:00+00:00",
                trades=[
                    {
                        "id": "sell-old",
                        "side": "sell",
                        "ticker": "OLD.L",
                        "acted_at": "2026-09-15T12:00:00+00:00",
                    }
                ],
                screen_buy_tier=[{"ticker": "OLD.L", "signal": "hold"}],
                selection=old_sel,
                knob_epoch_started_at=None,
            ),
            _rebalance_pass(
                logged_at="2026-10-12T11:00:00+00:00",
                trades=[
                    {
                        "id": "sell-new",
                        "side": "sell",
                        "ticker": "NEW.L",
                        "acted_at": "2026-10-12T12:00:00+00:00",
                    }
                ],
                screen_buy_tier=[{"ticker": "NEW.L", "signal": "hold"}],
                selection=new_sel,
                knob_epoch_started_at="2026-10-01T00:00:00+00:00",
            ),
        ],
    )
    payload = build_post_sell_cue_digest(data_dir=data_dir, paper_root=paper)
    rows = {r["ticker"]: r for r in payload["selection_postmortem_skeleton"]["rows"]}
    assert rows["OLD.L"]["epoch_lesson_status"] == "older_epoch"
    assert rows["NEW.L"]["epoch_lesson_status"] == "current_epoch"
    assert payload["epoch"]["older_epoch_count"] == 1
    assert payload["control_closed_sells"]["cue_closed_sell_count"] == 1
    assert payload["control_closed_sells"]["realized_pct_buckets"] == {"ge_10": 1}


def test_check_post_sell_cue_digest_persists_and_reports(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    paper = data_dir / "paper_automation"
    store = data_dir / "post_sell_cue_digest.json"
    _write(data_dir / "n200_tech_timing_observe.json", {"per_lever_scoreboards": {}})
    _write(paper / "learning_tracks_exit_timing.json", {"tracks": {}})
    _write(paper / "learning_tracks_exit_shadow.json", {"tracks": {}})
    _write(paper / "buy_tier_level" / "automated_fund.json", {"trades": []})
    _write(paper / "buy_tier_level" / "rebalance_log.json", [])

    findings = check_post_sell_cue_digest(
        data_dir=data_dir,
        paper_root=paper,
        store_path=store,
        persist=True,
    )
    assert store.is_file()
    assert any(f.title == FINDING_TITLE for f in findings)
    assert all(f.auto_fixable is False for f in findings)
    refreshed = refresh_post_sell_cue_digest(
        data_dir=data_dir,
        paper_root=paper,
        store_path=store,
        persist=True,
    )
    assert refreshed["schema_version"] == 2
    assert refreshed["widen_gate"]["widened"] is False
