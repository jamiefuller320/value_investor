"""Tests for observe-only post-sell cue digest (package M)."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.ops_monitor import check_post_sell_cue_digest
from value_investor.post_sell_cue_digest import (
    FINDING_TITLE,
    build_post_sell_cue_digest,
    refresh_post_sell_cue_digest,
)
from value_investor.review_payload_slim import slim_post_sell_cue_digest


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_digest_timing_and_selection_skeleton(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    paper = data_dir / "paper_automation"
    _write(
        data_dir / "n200_tech_timing_observe.json",
        {
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
                }
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
                    "by_exit_kind": {},
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
    _write(
        paper / "buy_tier_level" / "automated_fund.json",
        {
            "trades": [
                {
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
            ]
        },
    )

    payload = build_post_sell_cue_digest(data_dir=data_dir, paper_root=paper)
    assert payload["observe_only"] is True
    assert payload["influences_live"] is False
    assert any(c["cue_id"] == "n200_entry_exit_levers" for c in payload["timing_cues"])
    assert any(c["lane"] == "selection" for c in payload["selection_cues"])
    skeleton = payload["selection_postmortem_skeleton"]
    assert skeleton["sealed"] is False
    assert skeleton["feeds"] == "N205"
    assert skeleton["row_count"] == 2
    rows = {r["ticker"]: r for r in skeleton["rows"]}
    assert rows["AAA.L"]["still_in_buy_set"] is True
    assert rows["AAA.L"]["realized_pct"] == 10.0
    assert rows["BBB.L"]["still_in_buy_set"] is False
    assert rows["BBB.L"]["loser_card"]["signal"] == "avoid"
    hub = payload["hub_feed"]
    assert hub["push_candidates"] == []
    assert len(hub["explore_candidates"]) >= 1
    assert all(c.get("not_today") for c in hub["explore_candidates"])
    slim = slim_post_sell_cue_digest(payload)
    assert slim is not None
    assert slim["selection_postmortem_skeleton"]["sealed"] is False
    assert slim["artifact"] == "docs/data/post_sell_cue_digest.json"


def test_check_post_sell_cue_digest_persists_and_reports(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    paper = data_dir / "paper_automation"
    store = data_dir / "post_sell_cue_digest.json"
    _write(data_dir / "n200_tech_timing_observe.json", {"per_lever_scoreboards": {}})
    _write(paper / "learning_tracks_exit_timing.json", {"tracks": {}})
    _write(paper / "learning_tracks_exit_shadow.json", {"tracks": {}})
    _write(paper / "buy_tier_level" / "automated_fund.json", {"trades": []})

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
    assert refreshed["schema_version"] == 1
