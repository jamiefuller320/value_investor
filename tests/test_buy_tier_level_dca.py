"""FTSE buy_tier_level_dca realism twin (£500/mo capital epoch)."""

from pathlib import Path

from value_investor.fair_cost_lab import is_cohort_lab_track_id, is_suite_b_track_id
from value_investor.market_status import _overlay_ftse_dca_realism
from value_investor.paper_automation import (
    BUY_TIER_LEVEL_DCA_MONTHLY_DEPOSIT,
    BUY_TIER_LEVEL_DCA_TRACK_ID,
    BUY_TIER_LEVEL_TRACK_ID,
    default_buy_tier_level_dca_config,
    ensure_learning_track_configs,
    learning_track_dirs,
)
from value_investor.held_vs_market import build_held_vs_market_payload


def test_default_dca_config_is_suite_b_cohort_with_deposit():
    cfg = default_buy_tier_level_dca_config()
    assert cfg.track_id == BUY_TIER_LEVEL_DCA_TRACK_ID
    assert cfg.monthly_deposit == BUY_TIER_LEVEL_DCA_MONTHLY_DEPOSIT
    assert cfg.is_cohort_lab is True
    assert cfg.buy_cost_pct == 0.00525
    assert is_cohort_lab_track_id(BUY_TIER_LEVEL_DCA_TRACK_ID)
    assert is_suite_b_track_id(BUY_TIER_LEVEL_DCA_TRACK_ID)
    assert is_cohort_lab_track_id(BUY_TIER_LEVEL_TRACK_ID)


def test_ensure_learning_track_configs_writes_dca_cold_start(tmp_path: Path):
    # Seed a rules root config so ensure has a base.
    root = tmp_path / "paper"
    root.mkdir()
    (root / "config.json").write_text(
        '{"enabled": true, "track_id": "rules", "initial_cash": 1000}\n',
        encoding="utf-8",
    )
    configs = ensure_learning_track_configs(root)
    assert BUY_TIER_LEVEL_DCA_TRACK_ID in configs
    dca = configs[BUY_TIER_LEVEL_DCA_TRACK_ID]
    assert dca.monthly_deposit == 500.0
    dca_dir = learning_track_dirs(root)[BUY_TIER_LEVEL_DCA_TRACK_ID]
    assert (dca_dir / "config.json").exists()
    assert not (dca_dir / "automated_fund.json").exists()


def test_overlay_pending_without_fund():
    payload = build_held_vs_market_payload(
        market_id="ftse350",
        marks=[
            {
                "date": "2026-09-01",
                "held": 1000.0,
                "nav": 1000.0,
                "cash": 0.0,
                "positions": 1,
                "branches": {},
            },
            {
                "date": "2026-09-08",
                "held": 1010.0,
                "nav": 1010.0,
                "cash": 0.0,
                "positions": 1,
                "branches": {},
            },
        ],
        bench_closes={"2026-09-01": 100.0, "2026-09-08": 101.0},
    )
    overlay = _overlay_ftse_dca_realism(
        payload,
        paper_root=Path("/tmp/no-such-paper-root-for-dca"),
        macro_closes={},
    )
    assert any(b["id"] == BUY_TIER_LEVEL_DCA_TRACK_ID for b in overlay["branches"])
    assert overlay["branches"][0]["status"] == "pending"


def test_overlay_active_with_dca_fund_and_matched_market(tmp_path: Path):
    paper = tmp_path / "paper"
    dca_dir = paper / BUY_TIER_LEVEL_DCA_TRACK_ID
    dca_dir.mkdir(parents=True)
    (dca_dir / "automated_fund.json").write_text(
        """
{
  "config": {"monthly_deposit": 500, "reporting_currency": "GBP"},
  "contributed_capital": 1500,
  "equity_curve": [
    {
      "at": "2026-09-01T09:30:00+01:00",
      "portfolio_value": 1000.0,
      "cash": 0.0,
      "positions": 1,
      "contributed_capital": 1000.0
    },
    {
      "at": "2026-10-01T09:30:00+01:00",
      "portfolio_value": 1480.0,
      "cash": 0.0,
      "positions": 2,
      "contributed_capital": 1500.0
    }
  ]
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    payload = build_held_vs_market_payload(
        market_id="ftse350",
        marks=[
            {
                "date": "2026-09-01",
                "held": 1000.0,
                "nav": 1000.0,
                "cash": 0.0,
                "positions": 1,
                "branches": {},
            },
            {
                "date": "2026-10-01",
                "held": 990.0,
                "nav": 990.0,
                "cash": 0.0,
                "positions": 1,
                "branches": {},
            },
        ],
        bench_closes={"2026-09-01": 100.0, "2026-10-01": 110.0},
    )
    overlay = _overlay_ftse_dca_realism(
        payload,
        paper_root=paper,
        macro_closes={"^FTSE": {"2026-09-01": 100.0, "2026-10-01": 110.0}},
    )
    branch_ids = {b["id"] for b in overlay["branches"]}
    assert BUY_TIER_LEVEL_DCA_TRACK_ID in branch_ids
    assert "buy_tier_level_dca_market" in branch_ids
    assert overlay["points"][-1]["branches"][BUY_TIER_LEVEL_DCA_TRACK_ID] == 1480.0
    assert overlay["points"][-1]["branches"]["buy_tier_level_dca_market"] == 1600.0
    assert "deposit-matched" in (overlay.get("note") or "")
