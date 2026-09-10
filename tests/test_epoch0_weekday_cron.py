"""Tests for epoch-0 weekday cron ensure on learning admit."""

from __future__ import annotations

from unittest.mock import patch

from value_investor.epoch0_weekday_cron import (
    EPOCH0_WEEKDAY_SLOTS,
    cron_keys_for_market,
    cron_keys_for_policy,
    ensure_epoch0_weekday_crons,
    unmapped_admitted_markets,
)
from value_investor.market_shard_admission import admit_market_to_learning


def test_cron_keys_for_known_markets():
    assert cron_keys_for_market("asx200") == ["library-epoch0-weekday-asx"]
    assert cron_keys_for_market("euro_depth") == ["library-epoch0-weekday-euro"]
    assert cron_keys_for_market("ftse_smallcap") == ["library-epoch0-weekday-euro"]
    assert cron_keys_for_market("sp500") == [
        "library-epoch0-weekday-us-edt",
        "library-epoch0-weekday-us-est",
    ]


def test_cron_keys_for_policy_unions_admitted_timezones():
    policy = {
        "ladder": {"admitted_learning_markets": ["sp500", "asx200", "euro_depth"]},
    }
    assert cron_keys_for_policy(policy) == [
        "library-epoch0-weekday-us-edt",
        "library-epoch0-weekday-us-est",
        "library-epoch0-weekday-asx",
        "library-epoch0-weekday-euro",
    ]


def test_unmapped_admitted_markets_empty_for_current_roster():
    policy = {
        "ladder": {"admitted_learning_markets": ["sp500", "asx200", "euro_depth", "ftse_smallcap"]},
    }
    assert unmapped_admitted_markets(policy) == []


def test_ensure_dry_run_builds_payloads():
    result = ensure_epoch0_weekday_crons(
        keys=["library-epoch0-weekday-us-edt"],
        dry_run=True,
    )
    assert result["skipped"] is False
    assert result["dry_run"] is True
    assert len(result["results"]) == 1
    job = result["results"][0]["payload"]["job"]
    assert job["title"] == EPOCH0_WEEKDAY_SLOTS["library-epoch0-weekday-us-edt"]["title"]
    assert job["schedule"]["hours"] == [14]
    assert job["schedule"]["minutes"] == [15]
    assert "library-epoch0-weekday.yml" in job["url"]


def test_ensure_skips_without_secrets(monkeypatch):
    monkeypatch.delenv("CRONJOB_API_KEY", raising=False)
    monkeypatch.delenv("WORKFLOW_DISPATCH_PAT", raising=False)
    result = ensure_epoch0_weekday_crons(markets=["sp500"], dry_run=False)
    assert result["skipped"] is True
    assert result["reason"] == "CRONJOB_API_KEY not set"


def test_ensure_skips_without_workflow_pat(monkeypatch):
    monkeypatch.setenv("CRONJOB_API_KEY", "cron-test-key")
    monkeypatch.delenv("WORKFLOW_DISPATCH_PAT", raising=False)
    result = ensure_epoch0_weekday_crons(markets=["asx200"], dry_run=False)
    assert result["skipped"] is True
    assert result["reason"] == "WORKFLOW_DISPATCH_PAT not set"


def test_admit_market_ensures_crons_once():
    policy: dict = {"ladder": {"admitted_learning_markets": []}}
    with patch("value_investor.market_shard_admission._ensure_epoch0_crons_after_admit") as ensure:
        ensure.return_value = {"skipped": False, "keys": ["library-epoch0-weekday-asx"]}
        assert admit_market_to_learning(policy, "asx200") is True
        ensure.assert_called_once_with("asx200")
        assert admit_market_to_learning(policy, "asx200") is False
        ensure.assert_called_once_with("asx200")


def test_admit_market_can_skip_cron_ensure():
    policy: dict = {"ladder": {"admitted_learning_markets": []}}
    with patch("value_investor.market_shard_admission._ensure_epoch0_crons_after_admit") as ensure:
        assert admit_market_to_learning(policy, "sp500", ensure_crons=False) is True
        ensure.assert_not_called()


def test_refresh_dispatch_sync_cron_ensures_epoch0():
    from value_investor.library_ingest_dispatch import refresh_euro_ingest_dispatch

    with (
        patch(
            "value_investor.library_ingest_dispatch.evaluate_euro_ingest_dispatch",
            return_value={"mode": "sprint", "cron_morning": True},
        ),
        patch("value_investor.library_ingest_dispatch.write_euro_ingest_dispatch"),
        patch(
            "value_investor.euro_ingest_cron_sync.sync_euro_ingest_cron_jobs",
            return_value={"results": []},
        ),
        patch(
            "value_investor.library_ingest_dispatch.load_policy",
            return_value={"ladder": {"admitted_learning_markets": ["sp500"]}},
        ),
        patch(
            "value_investor.epoch0_weekday_cron.ensure_epoch0_weekday_crons_for_policy",
            return_value={"skipped": False, "keys": ["library-epoch0-weekday-us-edt"]},
        ) as epoch0,
        patch("value_investor.market_status.write_market_status", return_value="status.json"),
    ):
        evaluation = refresh_euro_ingest_dispatch(sync_cron=True)
    assert evaluation["epoch0_cron_sync"]["keys"] == ["library-epoch0-weekday-us-edt"]
    epoch0.assert_called_once()
