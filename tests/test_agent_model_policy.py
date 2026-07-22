"""Tests for cheapest-agent selection and library budget policy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.agent_model_policy import (
    enforce_weekly_research_cap,
    grow_ticker_budget,
    is_surplus_spend_day,
    load_policy,
    recommend_cheapest_model,
    record_estimated_spend,
    review_model,
    save_policy,
    weekly_budget_status,
)
from value_investor.data_library_cli import main as library_main
from value_investor.fetch import resolve_yahoo_ticker_for_market


def test_recommend_prefers_first_party_composer():
    pick = recommend_cheapest_model(
        ["gpt-5.4-nano", "composer-2.5", "claude-opus-4-8", "default"]
    )
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
    policy["budget"]["allocation_basis"] = "plan_fraction"
    policy["budget"]["plan_monthly_usd"] = 20
    policy["budget"]["weekly_library_fraction"] = 0.10
    policy["budget"]["enforce_weekly_research_cap"] = False
    policy["budget"]["plan_refresh_day_of_month"] = 8
    save_policy(policy, path)
    policy = load_policy(path)

    normal = grow_ticker_budget(
        policy, base_max_tickers=40, today=datetime(2026, 7, 16, tzinfo=UTC)
    )
    assert normal["focus_markets"] == ["sp500"]
    assert normal["max_tickers"] == 40
    assert normal["surplus_day"] is False
    assert normal["weekly_library_usd"] == 2.0
    assert normal["enforce_weekly_research_cap"] is False
    assert normal["allow_research"] is True
    assert normal["constraining"] is False

    # Surplus day is the 7th when refresh is the 8th
    surplus = grow_ticker_budget(
        policy,
        base_max_tickers=40,
        surplus_max_tickers=120,
        today=datetime(2026, 7, 7, tzinfo=UTC),
    )
    assert surplus["surplus_day"] is True
    assert surplus["max_tickers"] == 120


def test_usage_weekly_gbp_allocation(tmp_path: Path):
    path = tmp_path / "policy.json"
    policy = load_policy(path)
    policy["budget"]["allocation_basis"] = "usage_weekly_gbp"
    policy["budget"]["weekly_usage_gbp"] = 30.0
    policy["budget"]["gbp_usd_rate"] = 1.27
    policy["budget"]["enforce_weekly_research_cap"] = True
    policy["budget"]["estimated_spend_usd_this_week"] = 0.8
    policy["budget"]["week_id"] = datetime.now(UTC).strftime("%G-W%V")
    save_policy(policy, path)
    policy = load_policy(path)

    assert policy["budget"]["weekly_library_usd"] == 38.1
    status = weekly_budget_status(policy)
    assert status["allocation_basis"] == "usage_weekly_gbp"
    assert status["weekly_usage_gbp"] == 30.0
    assert status["remaining_weekly_usd"] == 37.3
    assert status["constraining"] is False
    assert status["flag"] == "enforced"

    plan = grow_ticker_budget(
        policy, base_max_tickers=40, today=datetime(2026, 7, 16, tzinfo=UTC)
    )
    assert plan["weekly_library_usd"] == 38.1
    assert plan["allow_research"] is True
    assert plan["budget_flag"] == "enforced"


def test_weekly_budget_constraining_flag(tmp_path: Path):
    path = tmp_path / "policy.json"
    policy = load_policy(path)
    policy["budget"]["allocation_basis"] = "usage_weekly_gbp"
    policy["budget"]["weekly_usage_gbp"] = 30.0
    policy["budget"]["gbp_usd_rate"] = 1.27
    policy["budget"]["enforce_weekly_research_cap"] = True
    policy["budget"]["estimated_spend_usd_this_week"] = 38.1
    policy["budget"]["week_id"] = datetime.now(UTC).strftime("%G-W%V")
    save_policy(policy, path)
    policy = load_policy(path)

    status = weekly_budget_status(policy)
    assert status["constraining"] is True
    assert status["flag"] == "constraining"
    assert status["remaining_weekly_usd"] == 0.0
    assert "constraining" in (status.get("note") or "")

    gated = grow_ticker_budget(
        policy, base_max_tickers=40, today=datetime(2026, 7, 16, tzinfo=UTC)
    )
    assert gated["allow_research"] is False
    assert gated["constraining"] is True


def test_weekly_research_cap_can_be_re_enabled(tmp_path: Path):
    path = tmp_path / "policy.json"
    policy = load_policy(path)
    policy["budget"]["allocation_basis"] = "plan_fraction"
    policy["budget"]["weekly_library_fraction"] = 0.10
    policy["budget"]["plan_monthly_usd"] = 20
    policy["budget"]["enforce_weekly_research_cap"] = True
    policy["budget"]["estimated_spend_usd_this_week"] = 2.0
    policy["budget"]["week_id"] = datetime.now(UTC).strftime("%G-W%V")
    save_policy(policy, path)
    policy = load_policy(path)
    assert enforce_weekly_research_cap(policy) is True
    assert policy["budget"]["weekly_library_usd"] == 2.0
    gated = grow_ticker_budget(
        policy, base_max_tickers=40, today=datetime(2026, 7, 16, tzinfo=UTC)
    )
    assert gated["allow_research"] is False


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
    # Usage mode must survive spend recording (not reset via plan_fraction).
    assert budget["allocation_basis"] == "usage_weekly_gbp"
    assert budget["weekly_library_usd"] == 38.1


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
                "--plan-monthly-usd",
                "20",
                "--weekly-fraction",
                "0.1",
                "--refresh-day",
                "12",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Focus market: sp500" in out
    assert "$2.0/week" in out or "$2/week" in out

    assert (
        library_main(
            [
                "--policy",
                str(path),
                "policy",
                "--weekly-usage-gbp",
                "30",
                "--gbp-usd-rate",
                "1.27",
                "--enforce-weekly-research-cap",
            ]
        )
        == 0
    )
    usage_out = capsys.readouterr().out
    assert "£30" in usage_out or "£30.0" in usage_out
    assert "flag=" in usage_out
    assert library_main(["--policy", str(path), "review-model", "--json"]) == 0
    review_out = capsys.readouterr().out
    assert "composer-2.5" in review_out or "gpt-5.4-nano" in review_out
