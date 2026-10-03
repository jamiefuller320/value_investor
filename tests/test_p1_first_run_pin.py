"""Tests for the time-boxed #953 P1 first-run observe pin."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.ops_monitor import check_p1_first_run_pin
from value_investor.p1_first_run_pin import (
    MONDAY_FINDING_TITLE,
    PIN_STARTED_AT,
    SUNDAY_FINDING_TITLE,
    format_p1_first_run_summary,
    ops_findings_from_p1_first_run_pin,
    run_p1_first_run_pin,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fund(path: Path, holdings: list[str]) -> None:
    _write_json(
        path,
        {"holdings": {t: {"shares": 1.0, "avg_cost": 1.0, "ticker": t} for t in holdings}},
    )


def _latest(
    path: Path,
    *,
    run_at: str,
    reports: list[dict],
) -> None:
    _write_json(path, {"run_at": run_at, "reports": reports})


def _rebalance(
    track_dir: Path,
    *,
    logged_at: str,
    candidates: list[dict],
    screen_buy_tier: list[dict] | None = None,
) -> None:
    _write_json(
        track_dir / "rebalance_log.json",
        [
            {
                "logged_at": logged_at,
                "acted": True,
                "candidates": candidates,
                "screen_buy_tier": screen_buy_tier or [],
            }
        ],
    )


def test_pre_sunday_and_empty_inventory_are_not_warns(tmp_path: Path):
    latest = tmp_path / "latest.json"
    fund = tmp_path / "fund.json"
    track = tmp_path / "ai_judgment"
    store = tmp_path / "pin.json"
    _fund(fund, ["KLR.L"])
    _latest(
        latest,
        run_at="2026-09-27T08:00:00+00:00",
        reports=[{"ticker": "KLR.L", "signal": "hold"}],
    )
    now = datetime(2026, 10, 3, 18, 0, tzinfo=UTC)
    payload = run_p1_first_run_pin(
        latest_path=latest,
        paper_fund_path=fund,
        paper_track_dir=track,
        store_path=store,
        now=now,
    )
    assert payload["sunday"]["status"] == "pre_sunday"
    assert payload["monday"]["status"] == "pre_monday"
    assert payload["inventory_count"] == 1
    assert ops_findings_from_p1_first_run_pin(payload) == []

    missing = run_p1_first_run_pin(
        latest_path=tmp_path / "missing.json",
        paper_fund_path=tmp_path / "no-fund.json",
        paper_track_dir=track,
        store_path=store,
        persist=False,
        now=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
    )
    assert missing["inventory_count"] == 0
    assert missing["sunday"]["status"] == "pre_sunday"
    assert ops_findings_from_p1_first_run_pin(missing) == []


def test_sunday_zero_eps_warns_once_then_auto_oks(tmp_path: Path):
    latest = tmp_path / "latest.json"
    fund = tmp_path / "fund.json"
    track = tmp_path / "ai_judgment"
    store = tmp_path / "pin.json"
    _fund(fund, ["KLR.L"])
    reports = [
        {"ticker": "KLR.L", "signal": "hold"},
        {"ticker": "AAA.L", "signal": "buy"},
    ]
    _latest(latest, run_at="2026-10-04T09:00:00+00:00", reports=reports)
    now = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    payload = run_p1_first_run_pin(
        latest_path=latest,
        paper_fund_path=fund,
        paper_track_dir=track,
        store_path=store,
        now=now,
    )
    assert payload["inventory_count"] == 2
    assert payload["sunday"]["eps_from_body_count"] == 0
    assert payload["sunday"]["status"] == "warn"
    findings = ops_findings_from_p1_first_run_pin(payload)
    assert len(findings) == 1
    assert findings[0]["title"] == SUNDAY_FINDING_TITLE
    assert findings[0]["auto_fixable"] is False
    assert "0/2" in findings[0]["summary"]

    reports[0]["interim_eps_decline_pct"] = -12.5
    _latest(latest, run_at="2026-10-04T09:00:00+00:00", reports=reports)
    ok = run_p1_first_run_pin(
        latest_path=latest,
        paper_fund_path=fund,
        paper_track_dir=track,
        store_path=store,
        now=now,
    )
    assert ok["sunday"]["status"] == "ok"
    assert ok["sunday"]["eps_from_body_count"] == 1
    assert ops_findings_from_p1_first_run_pin(ok) == []


def test_monday_slim_zero_warns_then_clears_when_frozen(tmp_path: Path):
    latest = tmp_path / "latest.json"
    fund = tmp_path / "fund.json"
    track = tmp_path / "ai_judgment"
    store = tmp_path / "pin.json"
    _fund(fund, ["KLR.L"])
    reports = [
        {
            "ticker": "KLR.L",
            "signal": "hold",
            "adjusted_eps_growth_pct": 4.2,
        }
    ]
    _latest(latest, run_at="2026-10-04T09:00:00+00:00", reports=reports)
    _rebalance(
        track,
        logged_at="2026-10-05T08:20:00+00:00",
        candidates=[{"ticker": "KLR.L", "signal": "hold"}],
    )
    now = datetime(2026, 10, 5, 13, 0, tzinfo=UTC)
    payload = run_p1_first_run_pin(
        latest_path=latest,
        paper_fund_path=fund,
        paper_track_dir=track,
        store_path=store,
        now=now,
    )
    assert payload["sunday"]["status"] == "ok"
    assert payload["monday"]["status"] == "warn"
    assert payload["monday"]["eps_from_body_count"] == 0
    titles = {row["title"] for row in ops_findings_from_p1_first_run_pin(payload)}
    assert titles == {MONDAY_FINDING_TITLE}

    _rebalance(
        track,
        logged_at="2026-10-05T08:20:00+00:00",
        candidates=[
            {
                "ticker": "KLR.L",
                "signal": "hold",
                "interim_eps_decline_pct": -8.0,
            }
        ],
    )
    frozen = run_p1_first_run_pin(
        latest_path=latest,
        paper_fund_path=fund,
        paper_track_dir=track,
        store_path=store,
        now=now,
    )
    assert frozen["monday"]["status"] == "ok"
    assert frozen["monday"]["eps_from_body_count"] == 1
    assert ops_findings_from_p1_first_run_pin(frozen) == []
    text = format_p1_first_run_summary(frozen)
    assert "Monday slim EPS-from-body: 1/1 (ok)" in text


def test_expired_window_is_silent_even_at_zero(tmp_path: Path):
    latest = tmp_path / "latest.json"
    fund = tmp_path / "fund.json"
    track = tmp_path / "ai_judgment"
    store = tmp_path / "pin.json"
    _fund(fund, ["KLR.L"])
    _latest(
        latest,
        run_at="2026-10-04T09:00:00+00:00",
        reports=[{"ticker": "KLR.L", "signal": "hold"}],
    )
    _rebalance(
        track,
        logged_at="2026-10-05T08:20:00+00:00",
        candidates=[{"ticker": "KLR.L"}],
    )
    late = PIN_STARTED_AT + timedelta(days=11)
    payload = run_p1_first_run_pin(
        latest_path=latest,
        paper_fund_path=fund,
        paper_track_dir=track,
        store_path=store,
        now=late,
    )
    assert payload["sunday"]["status"] == "expired"
    assert payload["monday"]["status"] == "expired"
    assert payload["sunday"]["eps_from_body_count"] == 0
    assert ops_findings_from_p1_first_run_pin(payload) == []


def test_check_p1_first_run_pin_ops_hook(tmp_path: Path):
    latest = tmp_path / "latest.json"
    fund = tmp_path / "fund.json"
    track = tmp_path / "ai_judgment"
    store = tmp_path / "pin.json"
    _fund(fund, ["AAA.L"])
    _latest(
        latest,
        run_at="2026-10-04T09:00:00+00:00",
        reports=[{"ticker": "AAA.L", "signal": "buy"}],
    )
    findings = check_p1_first_run_pin(
        latest_path=latest,
        paper_fund_path=fund,
        paper_track_dir=track,
        store_path=store,
        now=datetime(2026, 10, 4, 12, 0, tzinfo=UTC),
    )
    assert len(findings) == 1
    assert findings[0].title == SUNDAY_FINDING_TITLE
    assert findings[0].auto_fixable is False
    assert findings[0].severity == "warn"
    stored = json.loads(store.read_text(encoding="utf-8"))
    assert stored["observe_only"] is True
    assert stored["influences_live"] is False
