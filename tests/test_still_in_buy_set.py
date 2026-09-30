"""Still-in-buy-set cold-start twin: rank-gated hold + never-left-candidates."""

from pathlib import Path

from value_investor.paper_automation import (
    RULES_TRACK_ID,
    STILL_IN_BUY_SET_REENTRY_COOLDOWN_SCREENS,
    STILL_IN_BUY_SET_TRACK_ID,
    default_still_in_buy_set_config,
    ensure_learning_track_configs,
    learning_track_dirs,
)
from value_investor.paper_fund import (
    PaperFund,
    PaperFundConfig,
    Position,
    preview_automated_plan,
    run_automated_rebalance,
)


def _fund_with_holding(*, ticker: str = "PAF.L", entry_rank: int = 7) -> PaperFund:
    fund = PaperFund.create(
        PaperFundConfig(
            name="Still-in-buy-set twin",
            mode="automated",
            initial_cash=0,
            trade_cost_pct=0.03,
            max_positions=3,
        )
    )
    fund.holdings[ticker] = Position(
        ticker=ticker,
        shares=10,
        avg_cost=100,
        name=ticker,
        sector="Mining",
    )
    fund.rebalance_state.entry_candidate_rank[ticker] = entry_rank
    return fund


def _capacity_bump_candidates() -> list[dict]:
    # Top 3 targets: KLR, PPH, BP. PAF still buyish at rank 8 (drop 1 from entry 7).
    return [
        {
            "ticker": "KLR.L",
            "name": "Keller",
            "signal": "strong_buy",
            "conviction_score": 0.99,
            "price": 100,
            "timing_signal": "neutral",
            "sector": "Construction",
        },
        {
            "ticker": "PPH.L",
            "name": "PPHE",
            "signal": "buy",
            "conviction_score": 0.95,
            "price": 100,
            "timing_signal": "neutral",
            "sector": "Hotels",
        },
        {
            "ticker": "BP.L",
            "name": "BP",
            "signal": "buy",
            "conviction_score": 0.90,
            "price": 100,
            "timing_signal": "neutral",
            "sector": "Energy",
        },
        {
            "ticker": "X1.L",
            "name": "X1",
            "signal": "buy",
            "conviction_score": 0.85,
            "price": 100,
            "timing_signal": "neutral",
            "sector": "A",
        },
        {
            "ticker": "X2.L",
            "name": "X2",
            "signal": "buy",
            "conviction_score": 0.80,
            "price": 100,
            "timing_signal": "neutral",
            "sector": "B",
        },
        {
            "ticker": "X3.L",
            "name": "X3",
            "signal": "buy",
            "conviction_score": 0.75,
            "price": 100,
            "timing_signal": "neutral",
            "sector": "C",
        },
        {
            "ticker": "X4.L",
            "name": "X4",
            "signal": "buy",
            "conviction_score": 0.70,
            "price": 100,
            "timing_signal": "neutral",
            "sector": "D",
        },
        {
            "ticker": "PAF.L",
            "name": "Pan African",
            "signal": "buy",
            "conviction_score": 0.65,
            "price": 100,
            "timing_signal": "neutral",
            "sector": "Mining",
        },
    ]


def test_default_still_in_buy_set_config_knobs():
    cfg = default_still_in_buy_set_config()
    assert cfg.track_id == STILL_IN_BUY_SET_TRACK_ID
    assert cfg.is_churn_policy_twin is True
    assert cfg.churn_policy_parent_track == RULES_TRACK_ID
    assert cfg.still_in_buy_set_hold is True
    assert cfg.block_rebuy_while_in_candidates is True
    assert cfg.rank_drop_exit_min == 3
    assert cfg.reentry_cooldown_screens == STILL_IN_BUY_SET_REENTRY_COOLDOWN_SCREENS
    assert cfg.use_adjusted_signal is False
    assert cfg.trade_cost_pct == 0.03


def test_ensure_writes_cold_start_twin(tmp_path: Path):
    root = tmp_path / "paper"
    root.mkdir()
    (root / "config.json").write_text(
        '{"enabled": true, "track_id": "rules", "initial_cash": 1000, '
        '"trade_cost_pct": 0.03, "max_positions": 3}\n',
        encoding="utf-8",
    )
    configs = ensure_learning_track_configs(root)
    assert STILL_IN_BUY_SET_TRACK_ID in configs
    twin = configs[STILL_IN_BUY_SET_TRACK_ID]
    assert twin.still_in_buy_set_hold is True
    assert twin.reentry_cooldown_screens == 2
    twin_dir = learning_track_dirs(root)[STILL_IN_BUY_SET_TRACK_ID]
    assert (twin_dir / "config.json").exists()
    assert (twin_dir / "still_in_buy_set_provenance.json").exists()
    assert not (twin_dir / "automated_fund.json").exists()


def test_rank_gated_hold_blocks_capacity_bump_exit():
    fund = _fund_with_holding(entry_rank=7)
    candidates = _capacity_bump_candidates()

    plan = preview_automated_plan(
        fund,
        candidates,
        still_in_buy_set_hold=True,
        rank_drop_exit_min=3,
        exit_confirm_screens=0,
        reentry_cooldown_screens=0,
    )
    assert "PAF.L" not in {e["ticker"] for e in plan["anticipated_exits"]}
    assert any(
        h["ticker"] == "PAF.L" and "Still-in-buy-set hold" in str(h.get("reason"))
        for h in plan["anticipated_holds"]
    )

    run_automated_rebalance(
        fund,
        candidates,
        acted_at="2026-09-25T09:15:00+01:00",
        still_in_buy_set_hold=True,
        rank_drop_exit_min=3,
        exit_confirm_screens=0,
        reentry_cooldown_screens=0,
    )
    assert "PAF.L" in fund.holdings


def test_large_rank_drop_allows_exit():
    fund = _fund_with_holding(entry_rank=1)  # drop 8-1=7 >= 3
    candidates = _capacity_bump_candidates()

    run_automated_rebalance(
        fund,
        candidates,
        acted_at="2026-09-25T09:15:00+01:00",
        still_in_buy_set_hold=True,
        rank_drop_exit_min=3,
        exit_confirm_screens=0,
        reentry_cooldown_screens=0,
        block_rebuy_while_in_candidates=True,
    )
    assert "PAF.L" not in fund.holdings
    assert fund.rebalance_state.still_in_candidates_block.get("PAF.L") is True


def test_never_left_candidates_blocks_rebuy():
    fund = PaperFund.create(
        PaperFundConfig(
            name="Rebuy block",
            mode="automated",
            initial_cash=1000,
            trade_cost_pct=0.0,
            max_positions=3,
        )
    )
    fund.rebalance_state.still_in_candidates_block["PAF.L"] = True
    candidates = _capacity_bump_candidates()
    # Make PAF a target (top conviction).
    for row in candidates:
        if row["ticker"] == "PAF.L":
            row["conviction_score"] = 0.999

    plan = preview_automated_plan(
        fund,
        candidates,
        block_rebuy_while_in_candidates=True,
        exit_confirm_screens=0,
        reentry_cooldown_screens=0,
    )
    assert any(
        s["ticker"] == "PAF.L" and "Still-in-candidates" in str(s.get("reason"))
        for s in plan["skipped"]
    )

    run_automated_rebalance(
        fund,
        candidates,
        acted_at="2026-09-29T09:15:00+01:00",
        block_rebuy_while_in_candidates=True,
        exit_confirm_screens=0,
        reentry_cooldown_screens=0,
    )
    assert "PAF.L" not in fund.holdings
