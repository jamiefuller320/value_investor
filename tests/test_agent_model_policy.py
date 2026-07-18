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
    policy["budget"]["plan_monthly_usd"] = 20
    policy["budget"]["weekly_library_fraction"] = 0.10
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
    # Weekly research dollar strand is off by default; research still allowed.
    assert normal["enforce_weekly_research_cap"] is False
    assert normal["allow_research"] is True

    # Surplus day is the 7th when refresh is the 8th
    surplus = grow_ticker_budget(
        policy,
        base_max_tickers=40,
        surplus_max_tickers=120,
        today=datetime(2026, 7, 7, tzinfo=UTC),
    )
    assert surplus["surplus_day"] is True
    assert surplus["max_tickers"] == 120


def test_weekly_research_cap_can_be_re_enabled(tmp_path: Path):
    path = tmp_path / "policy.json"
    policy = load_policy(path)
    policy["budget"]["enforce_weekly_research_cap"] = True
    policy["budget"]["estimated_spend_usd_this_week"] = 2.0
    policy["budget"]["weekly_library_usd"] = 2.0
    policy["budget"]["week_id"] = datetime.now(UTC).strftime("%G-W%V")
    save_policy(policy, path)
    policy = load_policy(path)
    assert enforce_weekly_research_cap(policy) is True
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
    assert library_main(["--policy", str(path), "review-model", "--json"]) == 0
    review_out = capsys.readouterr().out
    assert "composer-2.5" in review_out or "gpt-5.4-nano" in review_out
