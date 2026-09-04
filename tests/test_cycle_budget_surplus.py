"""Tests for cycle-end surplus → provisional weekly_ops bump."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.agent_model_policy import load_policy, save_policy
from value_investor.cycle_budget_surplus import (
    apply_cycle_surplus,
    assess_cycle_surplus,
    current_cycle_id,
    next_cycle_id,
    review_cycle_surplus,
    weekly_ops_plan_credit_ceiling_usd,
)
from value_investor.data_library_cli import main as library_main


def _policy(path: Path, *, cap: float = 80.0, spent: float = 22.0) -> Path:
    policy = load_policy(path)
    policy["budget"]["weekly_ops_cap_usd"] = cap
    policy["budget"]["estimated_spend_weekly_ops_usd_this_week"] = spent
    policy["budget"]["estimated_spend_usd_this_week"] = spent
    policy["budget"]["plan_refresh_day_of_month"] = 8
    policy["budget"]["cycle_id"] = "2026-09-d8"
    policy["budget"]["plan_name"] = "Cursor Pro"
    policy["budget"]["plan_monthly_usd"] = 20.0
    save_policy(policy, path)
    return path


def test_next_cycle_id_rolls_month_and_year():
    assert next_cycle_id("2026-09-d8") == "2026-10-d8"
    assert next_cycle_id("2026-12-d8") == "2027-01-d8"
    assert current_cycle_id(now=datetime(2026, 9, 4, tzinfo=UTC), refresh_day=8) == "2026-09-d8"


def test_assess_proposes_quarter_of_unused_as_weekly_bump(tmp_path: Path):
    path = _policy(tmp_path / "policy.json")
    policy = load_policy(path)
    # $200 Ultra × 40% unused = $80; 25% transfer = $20; /4 weeks = $5 weekly
    assessment = assess_cycle_surplus(
        unused_fraction=0.40,
        plan_monthly_usd=200.0,
        policy=policy,
        path=path,
        now=datetime(2026, 9, 4, tzinfo=UTC),
    )
    assert assessment["action"] == "propose_bump"
    assert assessment["unused_monthly_usd"] == 80.0
    assert assessment["transfer_usd"] == 20.0
    assert assessment["weekly_bump_usd"] == 5.0
    assert assessment["current_weekly_ops_cap_usd"] == 80.0
    assert assessment["proposed_weekly_ops_cap_usd"] == 85.0
    assert assessment["review_cycle_id"] == "2026-10-d8"
    assert assessment["rememo_daily_cap_unchanged"] is True


def test_assess_caps_weekly_bump(tmp_path: Path):
    path = _policy(tmp_path / "policy.json", cap=80.0)
    policy = load_policy(path)
    assessment = assess_cycle_surplus(
        unused_fraction=1.0,
        plan_monthly_usd=200.0,
        transfer_fraction=1.0,
        max_weekly_bump_usd=20.0,
        policy=policy,
        path=path,
    )
    assert assessment["weekly_bump_usd"] == 20.0
    assert assessment["proposed_weekly_ops_cap_usd"] == 100.0


def test_apply_and_review_keep_revert(tmp_path: Path):
    policy_path = _policy(tmp_path / "policy.json")
    artifact = tmp_path / "surplus.json"
    policy = load_policy(policy_path)
    assessment = assess_cycle_surplus(
        unused_fraction=0.40,
        plan_monthly_usd=200.0,
        policy=policy,
        path=policy_path,
    )
    applied = apply_cycle_surplus(
        assessment,
        policy_path=policy_path,
        artifact_path=artifact,
        update_plan_metadata=True,
        plan_name="Cursor Ultra",
    )
    assert applied["action"] == "applied_provisional"
    policy = load_policy(policy_path)
    assert policy["budget"]["weekly_ops_cap_usd"] == 85.0
    assert policy["budget"]["plan_name"] == "Cursor Ultra"
    assert policy["budget"]["plan_monthly_usd"] == 200.0
    assert policy["budget"]["cycle_surplus_provisional"]["status"] == "provisional"

    early = review_cycle_surplus(
        keep=True,
        policy_path=policy_path,
        artifact_path=artifact,
        now=datetime(2026, 9, 8, tzinfo=UTC),
    )
    assert early["action"] == "too_early"
    assert load_policy(policy_path)["budget"]["weekly_ops_cap_usd"] == 85.0

    # Advance cycle id so review is due; leftover still high → recommend revert
    policy = load_policy(policy_path)
    policy["budget"]["cycle_id"] = "2026-10-d8"
    policy["budget"]["estimated_spend_weekly_ops_usd_this_week"] = 22.0
    save_policy(policy, policy_path)
    rec = review_cycle_surplus(
        keep=None,
        policy_path=policy_path,
        artifact_path=artifact,
        now=datetime(2026, 10, 8, tzinfo=UTC),
    )
    assert rec["action"] == "recommend_only"
    assert rec["recommend"] == "revert"

    reverted = review_cycle_surplus(
        keep=False,
        policy_path=policy_path,
        artifact_path=artifact,
        now=datetime(2026, 10, 8, tzinfo=UTC),
    )
    assert reverted["action"] == "reverted"
    assert load_policy(policy_path)["budget"]["weekly_ops_cap_usd"] == 80.0


def test_review_keep_when_extra_headroom_used(tmp_path: Path):
    policy_path = _policy(tmp_path / "policy.json", spent=70.0)
    artifact = tmp_path / "surplus.json"
    policy = load_policy(policy_path)
    assessment = assess_cycle_surplus(
        unused_fraction=0.40,
        plan_monthly_usd=200.0,
        policy=policy,
        path=policy_path,
    )
    apply_cycle_surplus(assessment, policy_path=policy_path, artifact_path=artifact)
    policy = load_policy(policy_path)
    policy["budget"]["cycle_id"] = "2026-10-d8"
    policy["budget"]["estimated_spend_weekly_ops_usd_this_week"] = 70.0
    save_policy(policy, policy_path)
    kept = review_cycle_surplus(
        keep=True,
        policy_path=policy_path,
        artifact_path=artifact,
        now=datetime(2026, 10, 8, tzinfo=UTC),
    )
    assert kept["action"] == "kept"
    assert kept["recommend"] == "keep"
    assert load_policy(policy_path)["budget"]["weekly_ops_cap_usd"] == 85.0


def test_assess_unused_usd_replaces_provisional_from_original_cap(tmp_path: Path):
    policy_path = _policy(tmp_path / "policy.json")
    artifact = tmp_path / "surplus.json"
    policy = load_policy(policy_path)
    first = assess_cycle_surplus(
        unused_fraction=0.40,
        plan_monthly_usd=200.0,
        policy=policy,
        path=policy_path,
    )
    apply_cycle_surplus(first, policy_path=policy_path, artifact_path=artifact)
    policy = load_policy(policy_path)
    assert policy["budget"]["weekly_ops_cap_usd"] == 85.0

    # $730 leftover (declared USD) → 25% / 4 weeks = $45.62, capped at 50% of $80
    revised = assess_cycle_surplus(
        unused_usd=730.0,
        plan_monthly_usd=200.0,
        replace_provisional=True,
        max_weekly_bump_usd=40.0,
        policy=policy,
        path=policy_path,
    )
    assert revised["action"] == "replace_provisional"
    assert revised["unused_monthly_usd"] == 730.0
    assert revised["unused_usd_declared"] is True
    assert revised["rebase_weekly_ops_cap_usd"] == 80.0
    assert revised["weekly_bump_usd"] == 40.0
    assert revised["proposed_weekly_ops_cap_usd"] == 120.0

    applied = apply_cycle_surplus(
        revised,
        policy_path=policy_path,
        artifact_path=artifact,
        replace_provisional=True,
    )
    assert applied["action"] == "applied_provisional"
    policy = load_policy(policy_path)
    assert policy["budget"]["weekly_ops_cap_usd"] == 120.0
    prov = policy["budget"]["cycle_surplus_provisional"]
    assert prov["previous_weekly_ops_cap_usd"] == 80.0
    assert prov["weekly_bump_usd"] == 40.0
    assert prov["unused_monthly_usd"] == 730.0
    assert prov["replaced_prior_provisional"] is True


def test_cli_assess_apply(tmp_path: Path, monkeypatch, capsys):
    policy_path = _policy(tmp_path / "policy.json")
    (tmp_path / "docs" / "data").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    rc = library_main(
        [
            "cycle-surplus",
            "assess",
            "--policy",
            str(policy_path),
            "--unused-fraction",
            "0.40",
            "--plan-monthly-usd",
            "200",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "weekly bump $5.00" in out
    assert "85.00" in out
    assert (tmp_path / "docs" / "data" / "cycle_budget_surplus.json").is_file()


def test_plan_credit_ceiling_is_15pct_of_ultra():
    assert weekly_ops_plan_credit_ceiling_usd(200.0) == 30.0
    assert weekly_ops_plan_credit_ceiling_usd(200.0, 0.15) == 30.0


def test_assess_15pct_is_warning_not_a_hard_clamp(tmp_path: Path):
    path = _policy(tmp_path / "policy.json", cap=80.0)
    policy = load_policy(path)
    assessment = assess_cycle_surplus(
        unused_fraction=0.40,
        plan_monthly_usd=200.0,
        policy=policy,
        path=path,
    )
    assert assessment["plan_credit_share_cap"] == 0.15
    assert assessment["plan_credit_warning_usd"] == 30.0
    assert assessment["proposed_weekly_ops_cap_usd"] == 85.0
    assert assessment["weekly_bump_usd"] == 5.0
    assert assessment["plan_credit_share_is_warning"] is True
    assert assessment["ceiling_bound"] is True
    assert assessment["action"] == "propose_bump"


def test_review_revert_restores_original_cap_above_warning(tmp_path: Path):
    policy_path = _policy(tmp_path / "policy.json", cap=80.0)
    artifact = tmp_path / "surplus.json"
    policy = load_policy(policy_path)
    assessment = assess_cycle_surplus(
        unused_fraction=0.40,
        plan_monthly_usd=200.0,
        policy=policy,
        path=policy_path,
    )
    apply_cycle_surplus(assessment, policy_path=policy_path, artifact_path=artifact)
    policy = load_policy(policy_path)
    policy["budget"]["cycle_id"] = "2026-10-d8"
    policy["budget"]["estimated_spend_weekly_ops_usd_this_week"] = 22.0
    save_policy(policy, policy_path)
    reverted = review_cycle_surplus(
        keep=False,
        policy_path=policy_path,
        artifact_path=artifact,
        now=datetime(2026, 10, 8, tzinfo=UTC),
    )
    assert reverted["action"] == "reverted"
    assert reverted["revert_weekly_ops_cap_usd"] == 80.0
    assert load_policy(policy_path)["budget"]["weekly_ops_cap_usd"] == 80.0
