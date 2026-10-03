"""Tests for observe-only combined vs per-market tagged exit_shadow join."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.combined_tagged_learning import (
    FINDING_TITLE,
    build_combined_tagged_learning,
    ops_finding_from_combined_tagged_learning,
    update_combined_tagged_learning,
)
from value_investor.ops_monitor import check_combined_tagged_learning
from value_investor.storage import write_json


def _shadow_record(
    *,
    trade_id: str,
    ticker: str,
    track_id: str = "buy_tier_level",
    status: str = "open",
    exit_kind: str = "grace",
    market_id: str | None = None,
    exited_at: str = "2026-07-01",
) -> dict:
    row = {
        "trade_id": trade_id,
        "ticker": ticker,
        "name": ticker,
        "track_id": track_id,
        "exited_at": exited_at,
        "exit_price": 100,
        "avg_cost": 90,
        "realized_return_pct": 0.11,
        "exit_reason": exit_kind,
        "exit_kind": exit_kind,
        "status": status,
        "checkpoints": [],
        "verdict": "early_exit" if status == "closed" else None,
        "peak_since_exit_pct": 0.1 if status == "closed" else 0.0,
        "trough_since_exit_pct": 0.0,
    }
    if market_id is not None:
        row["market_id"] = market_id
    return row


def _write_shadow(path: Path, *, track_id: str, records: list[dict], market_id: str | None = None):
    payload = {"schema_version": 1, "track_id": track_id, "records": records}
    if market_id is not None:
        payload["market_id"] = market_id
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)


def test_combined_rollup_tags_live_and_shards_without_track_id_collision(tmp_path: Path):
    paper = tmp_path / "paper_automation"
    policy = tmp_path / "policy.json"
    write_json(
        policy,
        {"ladder": {"admitted_learning_markets": ["euro_depth", "sp500"]}},
        compact=False,
    )
    _write_shadow(
        paper / "buy_tier_level" / "exit_shadow.json",
        track_id="buy_tier_level",
        records=[
            _shadow_record(trade_id="ftse-1", ticker="AAA.L", status="open", market_id="ftse350"),
            _shadow_record(
                trade_id="ftse-2",
                ticker="AAA.L",
                status="closed",
                exit_kind="screen_rotation",
                market_id="ftse350",
                exited_at="2026-08-01",
            ),
        ],
        market_id="ftse350",
    )
    _write_shadow(
        paper / "markets" / "euro_depth" / "buy_tier_level" / "exit_shadow.json",
        track_id="buy_tier_level",
        records=[
            _shadow_record(
                trade_id="eu-1",
                ticker="AIR.PA",
                status="closed",
                exit_kind="grace",
                market_id="euro_depth",
            )
        ],
        market_id="euro_depth",
    )
    _write_shadow(
        paper / "markets" / "sp500" / "buy_tier_level" / "exit_shadow.json",
        track_id="buy_tier_level",
        records=[],
        market_id="sp500",
    )

    payload = build_combined_tagged_learning(paper_root=paper, policy_path=policy)
    assert payload["observe_only"] is True
    assert payload["live_market_id"] == "ftse350"
    assert payload["summary"]["warn"] is False
    assert payload["summary"]["closed_count"] == 2
    assert payload["summary"]["open_count"] == 1
    # First episode strip drops the second AAA.L sell (buy-sell-buy fragment).
    assert payload["summary"]["first_episode_closed_count"] == 1
    assert payload["combined"]["by_exit_kind"]["grace"]["count"] == 1
    assert payload["combined"]["by_exit_kind"]["screen_rotation"]["count"] == 1
    by_market = payload["by_market"]
    assert by_market["ftse350"]["closed_count"] == 1
    assert by_market["euro_depth"]["closed_count"] == 1
    assert by_market["sp500"]["closed_count"] == 0
    assert by_market["sp500"]["open_count"] == 0
    ftse_track = by_market["ftse350"]["tracks"]["buy_tier_level"]
    euro_track = by_market["euro_depth"]["tracks"]["buy_tier_level"]
    assert ftse_track["track_id"] == euro_track["track_id"] == "buy_tier_level"
    assert ftse_track["market_id"] != euro_track["market_id"]
    assert ftse_track["first_episode"]["closed_count"] == 0
    assert euro_track["first_episode"]["closed_count"] == 1
    finding = ops_finding_from_combined_tagged_learning(payload, store_present=True)
    assert finding is None


def test_unstamped_live_book_infers_ftse350(tmp_path: Path):
    paper = tmp_path / "paper_automation"
    policy = tmp_path / "policy.json"
    write_json(policy, {"ladder": {"admitted_learning_markets": []}}, compact=False)
    _write_shadow(
        paper / "buy_tier_level" / "exit_shadow.json",
        track_id="buy_tier_level",
        records=[_shadow_record(trade_id="a", ticker="AAA.L", status="open")],
    )
    payload = build_combined_tagged_learning(
        paper_root=paper, policy_path=policy, markets=["ftse350"]
    )
    assert payload["by_market"]["ftse350"]["open_count"] == 1
    assert payload["summary"]["source_records_missing_market_id"] == 1
    assert payload["summary"]["closed_count"] == 0


def test_ops_check_persists_and_stays_quiet_on_zero_closed(tmp_path: Path):
    paper = tmp_path / "paper"
    store = tmp_path / "combined_tagged_learning.json"
    policy = tmp_path / "policy.json"
    write_json(policy, {"ladder": {"admitted_learning_markets": ["sp500"]}}, compact=False)
    _write_shadow(
        paper / "markets" / "sp500" / "buy_tier_level" / "exit_shadow.json",
        track_id="buy_tier_level",
        records=[],
        market_id="sp500",
    )
    findings = check_combined_tagged_learning(
        store_path=store,
        policy_path=policy,
        paper_root=paper,
        persist=True,
    )
    assert findings == []
    saved = json.loads(store.read_text(encoding="utf-8"))
    assert saved["summary"]["closed_count"] == 0
    assert saved["observe_only"] is True
    assert "N23" in saved["note"]

    missing = ops_finding_from_combined_tagged_learning(None, store_present=False)
    assert missing is not None
    assert missing["title"] == FINDING_TITLE
    assert missing["auto_fixable"] is False


def test_update_combined_tagged_learning_cli_shape(tmp_path: Path):
    paper = tmp_path / "paper"
    store = tmp_path / "out.json"
    policy = tmp_path / "policy.json"
    write_json(policy, {"ladder": {}}, compact=False)
    payload = update_combined_tagged_learning(
        store_path=store,
        paper_root=paper,
        policy_path=policy,
        markets=["ftse350"],
        persist=True,
    )
    assert store.exists()
    assert payload["summary"]["market_count"] == 1
    assert "by_exit_kind" in payload["combined"]
    assert "grace_vs_rotation" in payload["combined"]
    assert "first_episode" in payload["combined"]
