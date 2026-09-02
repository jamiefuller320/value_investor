"""Tests for weekday memo rememo candidate selection."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.research.weekday_rememo import (
    run_weekday_memo_rememo_pass,
    select_weekday_rememo_targets,
)


def _write_memo(
    root: Path,
    ticker: str,
    *,
    with_body: int,
    total: int,
    grade: str,
    published_bodies: int,
) -> None:
    ticker_dir = root / "research" / ticker
    (ticker_dir / "sources" / "filings").mkdir(parents=True)
    (ticker_dir / "research.json").write_text(
        json.dumps({"ticker": ticker, "name": ticker, "memo_quality": {"grade": grade}}),
        encoding="utf-8",
    )
    (ticker_dir / "sources" / "filings" / "filings_index.json").write_text(
        json.dumps({"summary": {"with_body": with_body, "total": total}}),
        encoding="utf-8",
    )
    (ticker_dir / "sources" / "screening_snapshot.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "name": ticker,
                "signal": "strong_buy",
                "data_quality_score": 1.0,
                "models_passed": 10,
                "model_count": 22,
            }
        ),
        encoding="utf-8",
    )


def test_select_prefers_ingest_improved_and_body_lag(tmp_path: Path):
    data = tmp_path / "docs_data"
    _write_memo(data, "AAA.L", with_body=40, total=40, grade="adequate", published_bodies=10)
    _write_memo(data, "BBB.L", with_body=50, total=50, grade="strong", published_bodies=50)
    _write_memo(data, "CCC.L", with_body=60, total=60, grade="adequate", published_bodies=5)

    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "research": [
                    {
                        "ticker": "AAA.L",
                        "name": "A",
                        "memo_quality": {
                            "grade": "adequate",
                            "filings_with_body": 10,
                            "filings_total": 40,
                        },
                    },
                    {
                        "ticker": "BBB.L",
                        "name": "B",
                        "memo_quality": {
                            "grade": "strong",
                            "filings_with_body": 50,
                            "filings_total": 50,
                        },
                    },
                    {
                        "ticker": "CCC.L",
                        "name": "C",
                        "memo_quality": {
                            "grade": "adequate",
                            "filings_with_body": 5,
                            "filings_total": 60,
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    targets = select_weekday_rememo_targets(
        latest_path=latest,
        committed_dir=data / "research",
        ingest_results=[{"ticker": "BBB.L", "improved": True, "with_body_after": 50}],
        max_targets=3,
        body_lag_threshold=10,
    )
    tickers = [t.ticker for t in targets]
    assert "BBB.L" in tickers  # ingest improved even if grade strong
    assert "CCC.L" in tickers  # large adequate lag
    assert "AAA.L" in tickers


def test_run_weekday_rememo_dry_run_respects_budget_and_writes_summary(tmp_path: Path, monkeypatch):
    data = tmp_path / "docs_data"
    _write_memo(data, "AAA.L", with_body=40, total=40, grade="adequate", published_bodies=5)
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "research": [
                    {
                        "ticker": "AAA.L",
                        "name": "A",
                        "memo_quality": {
                            "grade": "adequate",
                            "filings_with_body": 5,
                            "filings_total": 40,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    summary_path = tmp_path / "summary.json"

    monkeypatch.setattr(
        "value_investor.research.weekday_rememo.weekly_ops_budget_status",
        lambda estimated_memo_usd=0.4: {
            "remaining_weekly_ops_usd": 50.0,
            "constraining": False,
            "weekly_ops_cap_usd": 80.0,
        },
    )

    summary = run_weekday_memo_rememo_pass(
        api_key=None,
        latest_path=latest,
        committed_dir=data / "research",
        output_dir=tmp_path / "output",
        dest_dir=tmp_path / "docs",
        max_targets=2,
        summary_path=summary_path,
        dry_run=True,
        update_backlog_status=False,
        publish=False,
        record_spend=False,
    )
    assert summary.selected == ["AAA.L"]
    assert summary.rememoed == []
    assert summary_path.exists()


def test_run_weekday_rememo_skips_when_weekly_ops_tight(tmp_path: Path, monkeypatch):
    data = tmp_path / "docs_data"
    _write_memo(data, "AAA.L", with_body=40, total=40, grade="adequate", published_bodies=5)
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "research": [
                    {
                        "ticker": "AAA.L",
                        "name": "A",
                        "memo_quality": {
                            "grade": "adequate",
                            "filings_with_body": 5,
                            "filings_total": 40,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    summary_path = tmp_path / "summary.json"
    monkeypatch.setattr(
        "value_investor.research.weekday_rememo.weekly_ops_budget_status",
        lambda estimated_memo_usd=0.4: {
            "remaining_weekly_ops_usd": 5.0,
            "constraining": False,
            "weekly_ops_cap_usd": 80.0,
        },
    )
    summary = run_weekday_memo_rememo_pass(
        api_key="fake",
        latest_path=latest,
        committed_dir=data / "research",
        output_dir=tmp_path / "output",
        dest_dir=tmp_path / "docs",
        max_targets=2,
        summary_path=summary_path,
        dry_run=False,
        publish=False,
        record_spend=False,
        update_backlog_status=False,
    )
    assert summary.selected == ["AAA.L"]
    assert summary.rememoed == []
    assert "weekly_ops_headroom" in summary.skipped


def test_list_rememo_backlog_scans_committed_without_latest_index(tmp_path: Path):
    from value_investor.research.weekday_rememo import list_rememo_backlog

    data = tmp_path / "docs_data"
    _write_memo(data, "ZZZ.L", with_body=40, total=40, grade="adequate", published_bodies=5)
    # Commit memo_quality bodies onto research.json (source of truth for catch-up)
    meta = data / "research" / "ZZZ.L" / "research.json"
    payload = json.loads(meta.read_text(encoding="utf-8"))
    payload["memo_quality"] = {
        "grade": "adequate",
        "filings_with_body": 5,
        "filings_total": 40,
    }
    meta.write_text(json.dumps(payload), encoding="utf-8")
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps({"research": []}), encoding="utf-8")

    backlog = list_rememo_backlog(
        latest_path=latest,
        committed_dir=data / "research",
        scan_committed=True,
        body_lag_threshold=10,
    )
    assert [row.ticker for row in backlog] == ["ZZZ.L"]


def test_assess_rememo_backlog_flags_over_weekly_capacity(tmp_path: Path, monkeypatch):
    from value_investor.research import weekday_rememo as wr

    data = tmp_path / "docs_data"
    for i in range(4):
        ticker = f"T{i}.L"
        _write_memo(data, ticker, with_body=40, total=40, grade="adequate", published_bodies=5)
        meta = data / "research" / ticker / "research.json"
        payload = json.loads(meta.read_text(encoding="utf-8"))
        payload["memo_quality"] = {
            "grade": "adequate",
            "filings_with_body": 5,
            "filings_total": 40,
        }
        meta.write_text(json.dumps(payload), encoding="utf-8")
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps({"research": []}), encoding="utf-8")

    monkeypatch.setattr(
        wr,
        "weekly_ops_budget_status",
        lambda estimated_memo_usd=None: {
            "remaining_weekly_ops_usd": 50.0,
            "constraining": False,
        },
    )
    status = wr.assess_rememo_backlog(
        latest_path=latest,
        committed_dir=data / "research",
        per_day_cap=0,
        memo_usd=0.4,
        min_headroom_usd=8.0,
    )
    assert status["backlog_count"] == 4
    assert status["weekly_maintenance_capacity"] == 0
    assert status["over_weekly_capacity"] is True
    assert status["action"] == "catch_up"
    assert status["recommended_catchup_batch"] > 0


def test_ops_monitor_auto_activates_rememo_catchup(monkeypatch, tmp_path: Path):
    from value_investor import ops_monitor as om

    monkeypatch.setattr(
        om,
        "check_memo_rememo_backlog",
        lambda: [
            om.OpsFinding(
                severity="fail",
                category="research",
                title="Memo rememo backlog exceeds in-week capacity",
                summary="test backlog",
                auto_fixable=True,
            )
        ],
    )

    def _fake_write(**kwargs):
        path = tmp_path / "catchup.json"
        path.write_text("{}", encoding="utf-8")
        return {
            "backlog_count": 40,
            "catchup_request": {"active": True, "elevated_cap": 6},
        }

    monkeypatch.setattr(
        "value_investor.research.weekday_rememo.write_rememo_backlog_status",
        _fake_write,
    )
    findings = om.check_memo_rememo_backlog()
    fixes = om.apply_auto_fixes(findings, apply=True)
    assert any(row["action"] == "activate_memo_rememo_catchup" for row in fixes)
    assert findings[0].fixed is True
