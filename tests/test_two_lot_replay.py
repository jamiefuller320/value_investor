"""Observe-only two-lot retention replay."""

import json
from pathlib import Path

from value_investor.two_lot_replay import (
    EDGE_MIN,
    FINDING_TITLE,
    STORE_FAILED_TITLE,
    build_two_lot_replay,
    ops_finding_from_two_lot_replay,
    replay_policy,
)


def _pass(day: int, price: float, *, in_set: bool = True) -> dict:
    candidates = [
        {
            "ticker": "AAA.L",
            "price": price,
            "signal": "buy" if in_set else "hold",
            "timing_signal": "neutral",
            "trade_plan": {},
        }
    ]
    return {
        "acted": True,
        "logged_at": f"2026-09-{day:02d}T09:00:00+00:00",
        "nav_before": 100.0,
        "nav_after": 100.0,
        "max_positions": 5,
        "candidates": candidates,
        "selection": {
            "skip_timing_wait": True,
            "exit_confirm_screens": 2,
            "reentry_cooldown_screens": 1,
            "min_rebalance_notional_gbp": 0.0,
        },
    }


def _replay(passes: list[dict], policy: str) -> dict:
    return replay_policy(
        passes,
        policy,
        buy_cost=0.0,
        sell_cost=0.0,
        exit_confirm=2,
        reentry_cooldown=1,
        min_notional=0.0,
        max_positions=5,
        starting_cash=100.0,
    )


def test_core_kept_holds_through_a_rank_exit_and_later_rally():
    passes = [
        _pass(1, 100.0, in_set=True),
        _pass(2, 100.0, in_set=False),
        _pass(3, 100.0, in_set=False),
        _pass(4, 150.0, in_set=False),
    ]
    full = _replay(passes, "full_exit")
    kept = _replay(passes, "core_kept")
    assert full["nav"] == 100.0
    assert kept["names_with_core"] == 1
    assert kept["core_value"] == 97.5
    assert kept["nav"] > full["nav"]
    assert kept["rank_exits"] == 1


def test_profit_residual_keeps_only_the_gain_and_misses_a_further_rally():
    passes = [
        _pass(1, 100.0),
        _pass(2, 120.0),
        _pass(3, 150.0),
    ]
    full = _replay(passes, "full_exit")
    residual = _replay(passes, "profit_residual")
    assert full["nav"] == 150.0
    assert residual["residual_donations"] == 1
    assert residual["names_with_core"] == 1
    assert residual["core_value"] == 25.0
    assert residual["cash"] == 100.0
    assert residual["nav"] < full["nav"]


def test_profit_residual_beats_full_exit_when_the_name_is_sold_into_a_drop():
    passes = [
        _pass(1, 100.0, in_set=True),
        _pass(2, 120.0, in_set=True),
        _pass(3, 80.0, in_set=False),
        _pass(4, 80.0, in_set=False),
    ]
    full = _replay(passes, "full_exit")
    residual = _replay(passes, "profit_residual")
    assert full["nav"] == 80.0
    assert residual["residual_donations"] == 1
    assert residual["nav"] > full["nav"]


def test_harvest_skim_sells_half_the_gain_and_keeps_the_rest():
    passes = [_pass(1, 100.0), _pass(2, 120.0), _pass(3, 120.0)]
    skim = _replay(passes, "harvest_skim")
    assert skim["skims"] == 1
    assert skim["names_with_core"] == 1
    # Half of the £20 gain is sold; the other £110 of shares stays.
    assert skim["core_value"] == 110.0
    assert skim["cash"] == 10.0


def test_finding_requires_a_faithful_window_and_a_one_point_edge():
    quiet = {
        "status": "ok",
        "track_id": "buy_tier_level",
        "passes": 8,
        "window": {"from": "2026-09-01", "to": "2026-09-10"},
        "best_variant": {"policy": "core_kept", "delta_vs_full_exit": EDGE_MIN - 0.001},
        "variants": {"core_kept": {"core_value": 1, "rank_exits": 0}},
    }
    assert ops_finding_from_two_lot_replay(quiet) is None
    assert ops_finding_from_two_lot_replay({**quiet, "status": "unreliable"}) is None
    hit = {
        **quiet,
        "best_variant": {"policy": "core_kept", "delta_vs_full_exit": 0.02},
    }
    finding = ops_finding_from_two_lot_replay(hit)
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False


def test_build_marks_a_short_log_thin(tmp_path: Path):
    track = tmp_path / "buy_tier_level"
    track.mkdir()
    (track / "automated_fund.json").write_text(
        json.dumps({"config": {"buy_cost_pct": 0.00525, "sell_cost_pct": 0.00025}}),
        encoding="utf-8",
    )
    (track / "rebalance_log.json").write_text(json.dumps([_pass(1, 100.0)]), encoding="utf-8")
    payload = build_two_lot_replay(tmp_path)
    assert payload["status"] == "thin"
    assert payload["observe_only"] is True


def test_check_persists_store(tmp_path: Path):
    from value_investor.ops_monitor import check_two_lot_replay

    root = tmp_path / "paper"
    track = root / "buy_tier_level"
    track.mkdir(parents=True)
    passes = [_pass(day, 100.0) for day in range(1, 10)]
    (track / "rebalance_log.json").write_text(json.dumps(passes), encoding="utf-8")
    (track / "automated_fund.json").write_text(
        json.dumps(
            {
                "config": {
                    "buy_cost_pct": 0.0,
                    "sell_cost_pct": 0.0,
                    "initial_cash": 100.0,
                    "max_positions": 5,
                }
            }
        ),
        encoding="utf-8",
    )
    store = tmp_path / "two_lot_replay.json"
    findings = check_two_lot_replay(paper_root=root, store_path=store)
    payload = json.loads(store.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert set(payload["variants"]) == {
        "full_exit",
        "core_kept",
        "harvest_skim",
        "profit_residual",
    }
    assert findings == []


def test_check_warns_when_the_replay_raises(tmp_path: Path, monkeypatch):
    from value_investor.ops_monitor import check_two_lot_replay

    def _boom(*_args, **_kwargs):
        raise ValueError("bad log")

    monkeypatch.setattr("value_investor.two_lot_replay.refresh_two_lot_replay", _boom)
    root = tmp_path / "paper"
    root.mkdir()
    failed = check_two_lot_replay(paper_root=root, store_path=tmp_path / "fail.json")
    assert failed and failed[0].title == STORE_FAILED_TITLE
    assert failed[0].auto_fixable is False
