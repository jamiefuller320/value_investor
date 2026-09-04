"""Tests for cheapest-agent selection and library budget policy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.agent_model_policy import (
    SPEND_POOL_WEEKLY_OPS,
    approve_spend_checkpoint,
    grow_ticker_budget,
    is_surplus_spend_day,
    load_policy,
    recommend_cheapest_model,
    record_email_run_spend,
    record_estimated_spend,
    record_spend_with_checkpoint,
    remaining_weekly_ops_usd,
    review_model,
    save_policy,
    spend_since_checkpoint_usd,
    weekly_ops_budget_status,
)
from value_investor.data_library_cli import main as library_main
from value_investor.fetch import resolve_yahoo_ticker_for_market


def test_recommend_prefers_first_party_composer():
    pick = recommend_cheapest_model(["gpt-5.4-nano", "composer-2.5", "claude-opus-4-8", "default"])
    assert pick.model_id == "composer-2.5"
    assert pick.pool == "first_party"


def test_recommend_falls_back_to_cheapest_api():
    pick = recommend_cheapest_model(["gpt-5.4-nano", "gpt-5-mini", "claude-sonnet-5"])
    assert pick.model_id == "gpt-5.4-nano"
    assert pick.pool == "api"


def test_surplus_day_before_refresh():
    # Pro billing on the 8th → surplus is the 7th
    assert is_surplus_spend_day(datetime(2026, 7, 7, tzinfo=UTC), plan_refresh_day=8)
    assert not is_surplus_spend_day(datetime(2026, 7, 8, tzinfo=UTC), plan_refresh_day=8)
    # Refresh on the 1st → surplus is last day of month
    assert is_surplus_spend_day(datetime(2026, 7, 31, tzinfo=UTC), plan_refresh_day=1)
    assert not is_surplus_spend_day(datetime(2026, 7, 30, tzinfo=UTC), plan_refresh_day=1)


def test_grow_budget_focus_and_surplus(tmp_path: Path):
    path = tmp_path / "policy.json"
    policy = load_policy(path)
    policy["focus_market"] = "sp500"
    policy["budget"]["plan_monthly_usd"] = 20
    policy["budget"]["plan_refresh_day_of_month"] = 8
    save_policy(policy, path)
    policy = load_policy(path)

    normal = grow_ticker_budget(
        policy, base_max_tickers=40, today=datetime(2026, 7, 16, tzinfo=UTC)
    )
    assert normal["focus_markets"] == ["sp500"]
    assert normal["max_tickers"] == 40
    assert normal["surplus_day"] is False
    assert normal["weekly_ops_cap_usd"] == 50.0
    assert normal["allow_research"] is True
    assert normal["constraining"] is False

    surplus = grow_ticker_budget(
        policy,
        base_max_tickers=40,
        surplus_max_tickers=120,
        today=datetime(2026, 7, 7, tzinfo=UTC),
    )
    assert surplus["surplus_day"] is True
    assert surplus["max_tickers"] == 120


def test_weekly_ops_allocation(tmp_path: Path):
    path = tmp_path / "policy.json"
    policy = load_policy(path)
    policy["budget"]["weekly_ops_cap_usd"] = 50.0
    policy["budget"]["estimated_spend_weekly_ops_usd_this_week"] = 0.8
    policy["budget"]["week_id"] = datetime.now(UTC).strftime("%G-W%V")
    save_policy(policy, path)
    policy = load_policy(path)

    status = weekly_ops_budget_status(policy)
    assert status["weekly_ops_cap_usd"] == 50.0
    assert status["remaining_weekly_ops_usd"] == 49.2
    assert status["constraining"] is False
    assert status["flag"] == "enforced"
    assert status["weekly_ops_plan_credit_share_cap"] == 0.15
    assert status["weekly_ops_plan_credit_warning_usd"] == 3.0
    assert status["weekly_ops_plan_credit_warning"] is False
    assert status["weekly_ops_cap_exceeds_plan_share"] is True

    plan = grow_ticker_budget(policy, base_max_tickers=40, today=datetime(2026, 7, 16, tzinfo=UTC))
    assert plan["weekly_ops_cap_usd"] == 50.0
    assert plan["allow_research"] is True
    assert plan["budget_flag"] == "enforced"


def test_weekly_ops_constraining_flag(tmp_path: Path):
    path = tmp_path / "policy.json"
    policy = load_policy(path)
    policy["budget"]["weekly_ops_cap_usd"] = 50.0
    policy["budget"]["estimated_spend_weekly_ops_usd_this_week"] = 50.0
    policy["budget"]["week_id"] = datetime.now(UTC).strftime("%G-W%V")
    save_policy(policy, path)
    policy = load_policy(path)

    status = weekly_ops_budget_status(policy)
    assert status["constraining"] is True
    assert status["flag"] == "constraining"
    assert status["remaining_weekly_ops_usd"] == 0.0
    assert "constraining" in (status.get("note") or "")

    gated = grow_ticker_budget(policy, base_max_tickers=40, today=datetime(2026, 7, 16, tzinfo=UTC))
    assert gated["allow_research"] is False
    assert gated["constraining"] is True


def test_plan_credit_share_warning_does_not_constrain(tmp_path: Path):
    path = tmp_path / "policy.json"
    policy = load_policy(path)
    policy["budget"]["plan_monthly_usd"] = 200.0
    policy["budget"]["weekly_ops_cap_usd"] = 80.0
    policy["budget"]["estimated_spend_weekly_ops_usd_this_week"] = 35.0
    policy["budget"]["week_id"] = datetime.now(UTC).strftime("%G-W%V")
    save_policy(policy, path)
    policy = load_policy(path)

    status = weekly_ops_budget_status(policy)
    assert status["weekly_ops_plan_credit_warning_usd"] == 30.0
    assert status["weekly_ops_plan_credit_warning"] is True
    assert status["constraining"] is False
    assert status["flag"] == "enforced"
    assert "warning only" in (status.get("note") or "")

    plan = grow_ticker_budget(policy, base_max_tickers=40, today=datetime(2026, 7, 16, tzinfo=UTC))
    assert plan["allow_research"] is True
    assert plan["constraining"] is False


def test_review_model_persists(tmp_path: Path):
    path = tmp_path / "policy.json"
    result = review_model(
        path,
        list_models_fn=lambda: ["gpt-5.4-nano", "composer-2.5", "grok-4.5"],
    )
    assert result["pick"]["model_id"] == "composer-2.5"
    loaded = load_policy(path)
    assert loaded["research_model"]["model_id"] == "composer-2.5"
    assert loaded["model_review"]["last_reviewed_at"]


def test_record_estimated_spend(tmp_path: Path):
    path = tmp_path / "policy.json"
    save_policy(load_policy(path), path)
    budget = record_estimated_spend(0.5, path)
    assert budget["estimated_spend_usd_this_week"] == 0.5
    budget = record_estimated_spend(0.25, path)
    assert budget["estimated_spend_usd_this_week"] == 0.75
    assert budget["weekly_ops_cap_usd"] == 50.0


def test_spend_checkpoint_pause_and_approve(tmp_path: Path):
    path = tmp_path / "policy.json"
    save_policy(load_policy(path), path)
    status = record_spend_with_checkpoint(30.0, path, checkpoint_usd=30.0)
    assert status["checkpoint_reached"] is True
    assert spend_since_checkpoint_usd(load_policy(path)) == 30.0
    loaded = load_policy(path)
    assert loaded["budget"]["estimated_spend_weekly_ops_usd_this_week"] == 0.0
    approval = approve_spend_checkpoint(path)
    assert approval["spend_since_checkpoint_usd"] == 0.0
    assert spend_since_checkpoint_usd(load_policy(path)) == 0.0


def test_weekly_ops_pool_ring_fenced_from_ad_hoc(tmp_path: Path):
    path = tmp_path / "policy.json"
    policy = load_policy(path)
    policy["budget"]["weekly_ops_cap_usd"] = 50.0
    save_policy(policy, path)

    record_estimated_spend(6.4, path, pool=SPEND_POOL_WEEKLY_OPS)
    loaded = load_policy(path)
    assert loaded["budget"]["estimated_spend_weekly_ops_usd_this_week"] == 6.4
    assert loaded["budget"]["estimated_spend_usd_this_week"] == 6.4
    assert spend_since_checkpoint_usd(loaded) == 0.0
    assert remaining_weekly_ops_usd(loaded) == 43.6

    record_spend_with_checkpoint(10.0, path, checkpoint_usd=60.0)
    loaded = load_policy(path)
    assert spend_since_checkpoint_usd(loaded) == 10.0
    assert loaded["budget"]["estimated_spend_weekly_ops_usd_this_week"] == 6.4
    assert loaded["budget"]["estimated_spend_usd_this_week"] == 16.4


def test_record_email_run_spend(tmp_path: Path):
    path = tmp_path / "policy.json"
    save_policy(load_policy(path), path)
    status = record_email_run_spend(
        deep_analysis_ran=True,
        research_created=2,
        research_updated=10,
        gap_fill_revisions=3,
        memo_usd=0.4,
        path=path,
    )
    assert status["estimated_spend_weekly_ops_usd_this_week"] == 6.4
    assert weekly_ops_budget_status(load_policy(path))["remaining_weekly_ops_usd"] == 43.6


def test_record_email_run_spend_includes_post_run_review(tmp_path: Path):
    path = tmp_path / "policy.json"
    save_policy(load_policy(path), path)
    status = record_email_run_spend(
        deep_analysis_ran=True,
        research_created=0,
        research_updated=0,
        gap_fill_revisions=0,
        post_run_review_ran=True,
        memo_usd=0.4,
        path=path,
    )
    assert status["estimated_spend_weekly_ops_usd_this_week"] == 0.8


def test_weekly_ops_budget_status_constraining(tmp_path: Path):
    path = tmp_path / "policy.json"
    policy = load_policy(path)
    policy["budget"]["weekly_ops_cap_usd"] = 0.5
    save_policy(policy, path)
    status = weekly_ops_budget_status(load_policy(path), estimated_memo_usd=0.6)
    assert status["constraining"] is True
    assert status["flag"] == "constraining"


def test_legacy_budget_fields_stripped_on_save(tmp_path: Path):
    path = tmp_path / "policy.json"
    policy = load_policy(path)
    policy["budget"]["weekly_usage_gbp"] = 30.0
    policy["budget"]["weekly_library_usd"] = 38.1
    policy["budget"]["enforce_weekly_research_cap"] = True
    save_policy(policy, path)
    loaded = load_policy(path)
    assert "weekly_usage_gbp" not in loaded["budget"]
    assert "weekly_library_usd" not in loaded["budget"]
    assert "enforce_weekly_research_cap" not in loaded["budget"]


def test_market_aware_yahoo_resolution():
    assert resolve_yahoo_ticker_for_market("AAPL", "sp500") == "AAPL"
    assert resolve_yahoo_ticker_for_market("AAPL", "nasdaq100") == "AAPL"
    assert resolve_yahoo_ticker_for_market("BHP", "asx200") == "BHP.AX"
    assert resolve_yahoo_ticker_for_market("BHP.AX", "asx200") == "BHP.AX"
    assert resolve_yahoo_ticker_for_market("BARC", "ftse350") == "BARC.L"
    assert resolve_yahoo_ticker_for_market("ASIT", "ftse_smallcap") == "ASIT.L"
    assert resolve_yahoo_ticker_for_market("ADS.DE", "euro_stoxx50") == "ADS.DE"
    assert resolve_yahoo_ticker_for_market("ADS-DE", "euro_stoxx50") == "ADS.DE"
    assert resolve_yahoo_ticker_for_market("ADS.DE", "dax") == "ADS.DE"
    assert resolve_yahoo_ticker_for_market("AEM", "tsx60") == "AEM.TO"


def test_cli_policy_and_review(tmp_path: Path, capsys):
    path = tmp_path / "policy.json"
    assert (
        library_main(
            [
                "--policy",
                str(path),
                "policy",
                "--focus",
                "sp500",
                "--weekly-ops-cap-usd",
                "45",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "weekly ops" in out.lower() or "Weekly ops" in out
    policy = load_policy(path)
    assert policy["focus_market"] == "sp500"
    assert policy["budget"]["weekly_ops_cap_usd"] == 45.0
