"""Tests for observe-only buy-tier flip → usable lag pin."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.buy_tier_flip_lag import (
    format_flip_lag_summary,
    ops_finding_from_flip_lag,
    select_flip_cohort,
    update_buy_tier_flip_lag,
)
from value_investor.ops_monitor import check_buy_tier_flip_lag


def _write_index(
    research_root: Path,
    ticker: str,
    *,
    fetched_at: str,
    annual_bodies: int = 1,
    interim_bodies: int = 1,
    interim_total: int | None = None,
) -> None:
    interim_total = interim_bodies if interim_total is None else interim_total
    filings_dir = research_root / ticker / "sources" / "filings"
    filings_dir.mkdir(parents=True)
    filings = []
    for i in range(max(annual_bodies, 1)):
        filings.append(
            {
                "period": "annual",
                "has_body": i < annual_bodies,
                "body_path": f"bodies/a{i}.txt" if i < annual_bodies else None,
            }
        )
    for i in range(max(interim_total, 0)):
        filings.append(
            {
                "period": "interim",
                "has_body": i < interim_bodies,
                "body_path": f"bodies/i{i}.txt" if i < interim_bodies else None,
            }
        )
    bodies = filings_dir / "bodies"
    bodies.mkdir(exist_ok=True)
    for row in filings:
        if row.get("has_body") and row.get("body_path"):
            (filings_dir / row["body_path"]).write_text("body", encoding="utf-8")
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "fetched_at": fetched_at,
                "filings": filings,
                "summary": {
                    "total": len(filings),
                    "with_body": sum(1 for r in filings if r.get("has_body")),
                    "period_coverage": {
                        "annual": {"total": max(annual_bodies, 1), "with_body": annual_bodies},
                        "interim": {"total": interim_total, "with_body": interim_bodies},
                        "trading_update": {"total": 0, "with_body": 0},
                        "other": {"total": 0, "with_body": 0},
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _write_research_json(
    research_root: Path,
    ticker: str,
    *,
    created_at: str,
    verdict: str = "accumulate",
) -> None:
    path = research_root / ticker / "research.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ticker": ticker,
                "created_at": created_at,
                "updated_at": created_at,
                "research_verdict": verdict,
            }
        ),
        encoding="utf-8",
    )


def test_select_flip_cohort_lookback():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    reports = [
        {"ticker": "OLD.L", "signal": "buy", "signal_since": "2026-08-01"},
        {"ticker": "NEW.L", "signal": "buy", "signal_since": "2026-09-21"},
        {"ticker": "HOLD.L", "signal": "hold", "signal_since": "2026-09-21"},
    ]
    cohort = select_flip_cohort(reports, lookback_days=21, now=now)
    assert [r["ticker"] for r in cohort] == ["NEW.L"]


def test_update_flip_lag_tracks_stages_and_surface_events(tmp_path: Path):
    latest = tmp_path / "latest.json"
    research = tmp_path / "research"
    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    store = tmp_path / "buy_tier_flip_lag.json"
    flip_day = "2026-09-21"
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)

    # NEW.A: no research yet → open, blocking no_index
    # NEW.B: index + key bodies, no memo
    # NEW.C: full path usable
    _write_index(
        research,
        "NEW.B",
        fetched_at="2026-09-23T17:00:00+00:00",
        annual_bodies=1,
        interim_bodies=1,
    )
    _write_index(
        research,
        "NEW.C",
        fetched_at="2026-09-21T10:00:00+00:00",
        annual_bodies=1,
        interim_bodies=1,
    )
    _write_research_json(
        research,
        "NEW.C",
        created_at="2026-09-22T08:00:00+00:00",
        verdict="accumulate",
    )

    latest.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "ticker": "NEW.A",
                        "name": "No Index plc",
                        "signal": "buy",
                        "signal_since": flip_day,
                    },
                    {
                        "ticker": "NEW.B",
                        "name": "No Memo plc",
                        "signal": "buy",
                        "signal_since": flip_day,
                    },
                    {
                        "ticker": "NEW.C",
                        "name": "Usable plc",
                        "signal": "buy",
                        "signal_since": flip_day,
                        "research_verdict": "accumulate",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = update_buy_tier_flip_lag(
        latest_path=latest,
        research_root=research,
        memo_dir=memo_dir,
        store_path=store,
        now=now,
        persist=True,
    )
    assert store.is_file()
    assert payload["summary"]["cohort_count"] == 3
    assert payload["summary"]["open_not_usable"] == 2
    assert payload["summary"]["usable_in_window"] == 1
    assert payload["summary"]["blocking_stage_counts"]["no_index"] == 1
    assert payload["summary"]["blocking_stage_counts"]["no_memo"] == 1

    by_ticker = {row["ticker"]: row for row in payload["open"] + payload["recently_usable"]}
    assert by_ticker["NEW.A"]["blocking_stage"] == "no_index"
    assert by_ticker["NEW.B"]["blocking_stage"] == "no_memo"
    assert by_ticker["NEW.B"]["has_index"] is True
    assert by_ticker["NEW.B"]["key_bodies"] is True
    assert by_ticker["NEW.C"]["usable"] is True
    assert by_ticker["NEW.C"]["hours_to_usable"] is not None
    assert by_ticker["NEW.C"]["hours_to_usable"] >= 24.0

    events = payload["surface_events"]
    assert any(e["event"] == "flip_surfaced" and e["ticker"] == "NEW.A" for e in events)

    # Second pass: NEW.B gets memo → became_usable event; preserve first_surfaced_at
    first_a = by_ticker["NEW.A"]["first_surfaced_at"]
    _write_research_json(
        research,
        "NEW.B",
        created_at="2026-09-24T11:00:00+00:00",
        verdict="accumulate",
    )
    latest_payload = json.loads(latest.read_text(encoding="utf-8"))
    for row in latest_payload["reports"]:
        if row["ticker"] == "NEW.B":
            row["research_verdict"] = "accumulate"
    latest.write_text(json.dumps(latest_payload), encoding="utf-8")

    later = now + timedelta(hours=1)
    payload2 = update_buy_tier_flip_lag(
        latest_path=latest,
        research_root=research,
        memo_dir=memo_dir,
        store_path=store,
        now=later,
        persist=True,
    )
    assert payload2["summary"]["open_not_usable"] == 1
    assert payload2["names"]["NEW.A"]["first_surfaced_at"] == first_a
    assert any(
        e["event"] == "became_usable" and e["ticker"] == "NEW.B" for e in payload2["surface_events"]
    )

    finding = ops_finding_from_flip_lag(payload2)
    assert finding is not None
    assert finding["title"] == "New buy-tier not yet usable"
    assert "NEW.A" in finding["summary"]
    assert "no_index" in finding["summary"]
    assert "unmeasured" not in finding["title"].lower()

    text = format_flip_lag_summary(payload2)
    assert "not yet usable" in text.lower() or "Open not yet usable" in text


def test_check_buy_tier_flip_lag_ops_finding(tmp_path: Path):
    latest = tmp_path / "latest.json"
    research = tmp_path / "research"
    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    store = tmp_path / "flip_lag.json"
    flip_day = (datetime.now(UTC) - timedelta(days=3)).date().isoformat()
    latest.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "ticker": "LAG.L",
                        "name": "Lagging plc",
                        "signal": "buy",
                        "signal_since": flip_day,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    findings = check_buy_tier_flip_lag(
        latest_path=latest,
        research_root=research,
        memo_dir=memo_dir,
        store_path=store,
        persist=True,
    )
    assert len(findings) == 1
    assert findings[0].title == "New buy-tier not yet usable"
    assert findings[0].severity == "warn"
    assert findings[0].auto_fixable is False
    assert "LAG.L" in findings[0].summary
    assert store.is_file()


def test_check_buy_tier_flip_lag_quiet_when_fresh_or_usable(tmp_path: Path):
    latest = tmp_path / "latest.json"
    research = tmp_path / "research"
    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    store = tmp_path / "flip_lag.json"
    # Flip today (< warn_after_hours) → no finding even if incomplete
    today = datetime.now(UTC).date().isoformat()
    latest.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "ticker": "FRESH.L",
                        "name": "Fresh plc",
                        "signal": "buy",
                        "signal_since": today,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    findings = check_buy_tier_flip_lag(
        latest_path=latest,
        research_root=research,
        memo_dir=memo_dir,
        store_path=store,
        persist=True,
    )
    assert findings == []


def test_ops_warn_skips_non_accumulate_when_memo_exists(tmp_path: Path):
    """Hold/watch memo completes factory path; accumulate miss is tracked but not ops-warned."""
    latest = tmp_path / "latest.json"
    research = tmp_path / "research"
    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    store = tmp_path / "flip_lag.json"
    flip_day = (datetime.now(UTC) - timedelta(days=5)).date().isoformat()
    _write_index(
        research,
        "HOLD.L",
        fetched_at=f"{flip_day}T12:00:00+00:00",
        annual_bodies=1,
        interim_bodies=1,
    )
    _write_research_json(
        research,
        "HOLD.L",
        created_at=f"{flip_day}T18:00:00+00:00",
        verdict="hold",
    )
    latest.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "ticker": "HOLD.L",
                        "name": "Hold Memo plc",
                        "signal": "buy",
                        "signal_since": flip_day,
                        "research_verdict": "hold",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = update_buy_tier_flip_lag(
        latest_path=latest,
        research_root=research,
        memo_dir=memo_dir,
        store_path=store,
        persist=True,
    )
    assert payload["summary"]["open_not_usable"] == 1
    assert payload["open"][0]["blocking_stage"] == "no_accumulate_verdict"
    assert payload["warn_open"] == []
    assert ops_finding_from_flip_lag(payload) is None
    assert (
        check_buy_tier_flip_lag(
            latest_path=latest,
            research_root=research,
            memo_dir=memo_dir,
            store_path=store,
            persist=True,
        )
        == []
    )
