"""Tests for post-exit shadow cohort learning (observe-only)."""

from datetime import date, timedelta

from value_investor.exit_shadow import (
    ExitShadowConfig,
    ExitShadowRecord,
    build_exit_shadow_review,
    classify_exit_kind,
    ingest_new_exits,
    load_exit_shadow,
    run_exit_shadow_pass,
    update_shadow_scores,
    verdict_from_path,
)
from value_investor.paper_fund import PaperFund, PaperFundConfig, Position


def _fund_with_sell() -> PaperFund:
    fund = PaperFund.create(
        PaperFundConfig(
            name="Shadow test",
            mode="automated",
            initial_cash=0,
            trade_cost_pct=0.0,
            max_positions=5,
        )
    )
    fund.holdings["OLD.L"] = Position(
        ticker="OLD.L",
        shares=10,
        avg_cost=100,
        name="Old",
        momentum_grace=True,
        grace_started_at="2026-07-01T09:00:00+01:00",
    )
    fund.sell(
        ticker="OLD.L",
        price=120,
        sizing_mode="shares",
        amount=10,
        note="Momentum grace exit",
        acted_at="2026-07-10T09:15:00+01:00",
    )
    return fund


def test_classify_exit_kind_grace_and_rotation():
    assert classify_exit_kind(note="Momentum grace exit", momentum_grace=True) == "grace"
    assert (
        classify_exit_kind(note="Automated exit — left target set", momentum_grace=False)
        == "screen_rotation"
    )


def test_ingest_new_exits_from_full_position_sell():
    fund = _fund_with_sell()
    store = {"records": []}
    added = ingest_new_exits(fund, store, track_id="momentum_grace")
    assert added == 1
    record = store["records"][0]
    assert record["ticker"] == "OLD.L"
    assert record["exit_kind"] == "grace"
    assert record["momentum_grace"] is True
    assert record["avg_cost"] == 100
    assert record["realized_return_pct"] == 0.2


def test_update_shadow_scores_adds_checkpoints_and_closes(tmp_path):
    fund = _fund_with_sell()
    store = {"records": []}
    ingest_new_exits(fund, store, track_id="momentum_grace")
    exit_date = date(2026, 7, 10)
    as_of = (exit_date + timedelta(days=90)).isoformat()
    updated = update_shadow_scores(
        store,
        {"OLD.L": 130.0},
        as_of=as_of,
        config=ExitShadowConfig(shadow_windows_days=(7, 28, 56, 84)),
    )
    assert updated >= 4
    record = ExitShadowRecord.from_dict(store["records"][0])
    assert record.status == "closed"
    assert record.verdict in {"early_exit", "good_exit", "neutral"}
    assert len(record.checkpoints) == 4


def test_verdict_early_exit_when_price_runs_after_sell():
    assert (
        verdict_from_path(
            peak_since_exit_pct=0.12,
            trough_since_exit_pct=0.0,
            final_return_pct=0.02,
        )
        == "early_exit"
    )


def test_run_exit_shadow_pass_writes_artifacts(tmp_path):
    fund = _fund_with_sell()
    review = run_exit_shadow_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="momentum_grace",
        prices_by_ticker={"OLD.L": 125.0},
        as_of="2026-07-20T09:15:00+01:00",
    )
    assert review["track_id"] == "momentum_grace"
    assert (tmp_path / "exit_shadow.json").exists()
    assert (tmp_path / "exit_shadow_review.json").exists()
    store = load_exit_shadow(tmp_path / "exit_shadow.json")
    assert len(store["records"]) == 1


def test_build_exit_shadow_review_summarizes_by_kind():
    store = {
        "records": [
            {
                "trade_id": "a",
                "ticker": "AAA.L",
                "name": "A",
                "track_id": "momentum_grace",
                "exited_at": "2026-06-01",
                "exit_price": 100,
                "avg_cost": 90,
                "realized_return_pct": 0.11,
                "exit_reason": "grace",
                "exit_kind": "grace",
                "momentum_grace": True,
                "status": "closed",
                "checkpoints": [],
                "verdict": "early_exit",
                "peak_since_exit_pct": 0.15,
                "trough_since_exit_pct": -0.01,
                "last_return_since_exit_pct": 0.05,
            }
        ]
    }
    review = build_exit_shadow_review(store, track_id="momentum_grace")
    assert review["closed_count"] == 1
    assert review["by_exit_kind"]["grace"]["count"] == 1
    assert "observe-only" in review["note"].lower()
