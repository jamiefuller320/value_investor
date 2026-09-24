"""Tests for observe-only FTSE holdings ∪ buy-tier decision-input inventory."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.decision_input_inventory import (
    VERDICT_GREEN,
    format_decision_input_summary,
    ops_finding_from_decision_input_inventory,
    run_decision_input_inventory,
)
from value_investor.ops_monitor import check_decision_input_inventory


def _write_index(
    research_root: Path,
    ticker: str,
    *,
    annual_bodies: int = 1,
    interim_bodies: int = 1,
) -> None:
    filings_dir = research_root / ticker / "sources" / "filings"
    bodies = filings_dir / "bodies"
    bodies.mkdir(parents=True)
    filings = []
    for i in range(max(annual_bodies, 1)):
        has = i < annual_bodies
        filings.append(
            {
                "period": "annual",
                "has_body": has,
                "body_path": f"bodies/a{i}.txt" if has else None,
            }
        )
        if has:
            (bodies / f"a{i}.txt").write_text("annual", encoding="utf-8")
    for i in range(max(interim_bodies, 1)):
        has = i < interim_bodies
        filings.append(
            {
                "period": "interim",
                "has_body": has,
                "body_path": f"bodies/i{i}.txt" if has else None,
            }
        )
        if has:
            (bodies / f"i{i}.txt").write_text("interim", encoding="utf-8")
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "fetched_at": "2026-09-20T00:00:00+00:00",
                "filings": filings,
                "summary": {
                    "total": len(filings),
                    "with_body": sum(1 for r in filings if r.get("has_body")),
                    "period_coverage": {
                        "annual": {
                            "total": max(annual_bodies, 1),
                            "with_body": annual_bodies,
                        },
                        "interim": {
                            "total": max(interim_bodies, 1),
                            "with_body": interim_bodies,
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _write_research(
    research_root: Path,
    ticker: str,
    *,
    updated_at: str,
    verdict: str = "accumulate",
) -> None:
    path = research_root / ticker / "research.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ticker": ticker,
                "created_at": updated_at,
                "updated_at": updated_at,
                "research_verdict": verdict,
            }
        ),
        encoding="utf-8",
    )


def _write_fund(path: Path, holdings: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"holdings": {t: {"shares": 1.0, "avg_cost": 1.0, "ticker": t} for t in holdings}}
        ),
        encoding="utf-8",
    )


def test_inventory_holdings_union_buy_tier_and_rollup(tmp_path: Path):
    latest = tmp_path / "latest.json"
    research = tmp_path / "research"
    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    fund = tmp_path / "automated_fund.json"
    store = tmp_path / "decision_input_inventory.json"
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    recent = (now - timedelta(days=3)).isoformat()
    stale = (now - timedelta(days=40)).isoformat()

    # READY: buy-tier, full binds, recent memo
    _write_index(research, "READY.L")
    _write_research(research, "READY.L", updated_at=recent)
    # HELD: held only (not buy), missing FCF bind + no verdict
    _write_index(research, "HELD.L")
    _write_research(research, "HELD.L", updated_at=recent, verdict="")
    # GAPBODY: buy-tier, no annual bodies
    _write_index(research, "GAPBODY.L", annual_bodies=0, interim_bodies=1)
    _write_research(research, "GAPBODY.L", updated_at=recent)
    # STALE: buy-tier, stale memo
    _write_index(research, "STALE.L")
    _write_research(research, "STALE.L", updated_at=stale)
    # NOV: buy-tier, no research verdict on report or disk
    _write_index(research, "NOV.L")

    _write_fund(fund, ["HELD.L", "READY.L"])

    latest.write_text(
        json.dumps(
            {
                "run_at": "2026-09-21T00:00:00+00:00",
                "reports": [
                    {
                        "ticker": "READY.L",
                        "name": "Ready",
                        "signal": "buy",
                        "adjusted_signal": "buy",
                        "fcf_basis_overlay": False,
                        "research_verdict": "accumulate",
                    },
                    {
                        "ticker": "HELD.L",
                        "name": "Held",
                        "signal": "hold",
                        "adjusted_signal": "hold",
                        # no fcf_basis_overlay → unbound
                        "research_verdict": None,
                    },
                    {
                        "ticker": "GAPBODY.L",
                        "name": "Gap Body",
                        "signal": "strong_buy",
                        "adjusted_signal": "buy",
                        "fcf_basis_overlay": True,
                        "research_verdict": "accumulate",
                    },
                    {
                        "ticker": "STALE.L",
                        "name": "Stale",
                        "signal": "buy",
                        "adjusted_signal": "buy",
                        "fcf_basis_overlay": True,
                        "research_verdict": "neutral",
                    },
                    {
                        "ticker": "NOV.L",
                        "name": "No Verdict",
                        "signal": "buy",
                        "adjusted_signal": "buy",
                        "fcf_basis_overlay": True,
                    },
                    {
                        "ticker": "IGNORE.L",
                        "name": "Ignore",
                        "signal": "hold",
                        "adjusted_signal": "hold",
                        "fcf_basis_overlay": True,
                        "research_verdict": "pass",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = run_decision_input_inventory(
        latest_path=latest,
        research_root=research,
        memo_dir=memo_dir,
        paper_fund_path=fund,
        store_path=store,
        memo_max_age_days=21,
        green_enough_max_gaps=2,
        now=now,
        persist=True,
    )

    tickers = {row["ticker"] for row in payload["rows"]}
    assert tickers == {"READY.L", "HELD.L", "GAPBODY.L", "STALE.L", "NOV.L"}
    assert "IGNORE.L" not in tickers

    by = {row["ticker"]: row for row in payload["rows"]}
    assert by["READY.L"]["in_buy_tier"] is True
    assert by["READY.L"]["in_holdings"] is True
    assert by["READY.L"]["key_filing_bodies"] is True
    assert by["READY.L"]["fcf_basis_bound"] is True
    assert by["READY.L"]["overlay_bound"] is True
    assert by["READY.L"]["memo_recent"] is True
    assert by["READY.L"]["gaps"] == []

    assert by["HELD.L"]["in_buy_tier"] is False
    assert by["HELD.L"]["in_holdings"] is True
    assert by["HELD.L"]["fcf_basis_bound"] is False
    assert by["HELD.L"]["overlay_bound"] is False
    assert "fcf_basis_bound" in by["HELD.L"]["gaps"]
    assert "overlay_bound" in by["HELD.L"]["gaps"]

    assert by["GAPBODY.L"]["key_filing_bodies"] is False
    assert by["STALE.L"]["memo_recent"] is False
    assert by["STALE.L"]["memo_age_days"] is not None
    assert by["STALE.L"]["memo_age_days"] >= 21
    assert by["NOV.L"]["overlay_bound"] is False
    assert by["NOV.L"]["research_verdict"] is None

    rollup = payload["rollup"]
    assert rollup["inventory_count"] == 5
    assert rollup["held_count"] == 2
    assert rollup["buy_tier_count"] == 4
    # Four names miss memo_recent? READY recent; HELD recent; GAPBODY recent;
    # STALE stale; NOV has no memo → memo_recent false. So memo_recent gaps = 2.
    # overlay_bound: HELD + NOV = 2
    # key_filing_bodies: GAPBODY = 1
    # fcf_basis_bound: HELD = 1
    # With green_enough_max_gaps=2 and max=2 → green-enough
    assert rollup["verdict"] == VERDICT_GREEN
    assert payload["summary"]["sunday_bind_field"] == VERDICT_GREEN
    assert store.is_file()

    text = format_decision_input_summary(payload)
    assert "decision-input inventory" in text
    assert VERDICT_GREEN in text


def test_inventory_names_dominant_gap_and_ops_warn(tmp_path: Path):
    latest = tmp_path / "latest.json"
    research = tmp_path / "research"
    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    fund = tmp_path / "automated_fund.json"
    store = tmp_path / "out.json"
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    recent = (now - timedelta(days=2)).isoformat()

    reports = []
    for i in range(5):
        ticker = f"G{i}.L"
        _write_index(research, ticker)
        # No research.json: overlay unbound + memo not recent (disk fallback absent).
        reports.append(
            {
                "ticker": ticker,
                "name": ticker,
                "signal": "buy",
                "adjusted_signal": "buy",
                "fcf_basis_overlay": True,
            }
        )
    # One clean name so inventory is not empty of ready paths
    _write_index(research, "OK.L")
    _write_research(research, "OK.L", updated_at=recent)
    reports.append(
        {
            "ticker": "OK.L",
            "name": "OK",
            "signal": "buy",
            "adjusted_signal": "buy",
            "fcf_basis_overlay": True,
            "research_verdict": "accumulate",
        }
    )
    _write_fund(fund, [])
    latest.write_text(
        json.dumps({"run_at": "2026-09-21T00:00:00+00:00", "reports": reports}),
        encoding="utf-8",
    )

    payload = run_decision_input_inventory(
        latest_path=latest,
        research_root=research,
        memo_dir=memo_dir,
        paper_fund_path=fund,
        store_path=store,
        now=now,
        green_enough_max_gaps=2,
        persist=True,
    )
    assert payload["rollup"]["verdict"] == "overlay_bound"
    assert payload["rollup"]["dominant_gap_field"] == "overlay_bound"
    assert payload["rollup"]["gap_counts"]["overlay_bound"] == 5

    finding = ops_finding_from_decision_input_inventory(payload, warn_min_gaps=3)
    assert finding is not None
    assert finding["severity"] == "warn"
    assert "overlay_bound" in finding["summary"]

    # Below warn threshold → no finding
    assert ops_finding_from_decision_input_inventory(payload, warn_min_gaps=6) is None


def test_check_decision_input_inventory_ops_hook(tmp_path: Path):
    latest = tmp_path / "latest.json"
    research = tmp_path / "research"
    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    fund = tmp_path / "fund.json"
    store = tmp_path / "inv.json"
    now_iso = "2026-09-24T12:00:00+00:00"

    reports = []
    for i in range(4):
        t = f"W{i}.L"
        _write_index(research, t)
        reports.append(
            {
                "ticker": t,
                "signal": "buy",
                "adjusted_signal": "buy",
                "fcf_basis_overlay": True,
            }
        )
    latest.write_text(
        json.dumps({"updated_at": now_iso, "reports": reports}),
        encoding="utf-8",
    )
    _write_fund(fund, [])

    findings = check_decision_input_inventory(
        latest_path=latest,
        research_root=research,
        memo_dir=memo_dir,
        paper_fund_path=fund,
        store_path=store,
        persist=True,
    )
    assert len(findings) == 1
    assert findings[0].severity == "warn"
    assert (
        "decision-input" in findings[0].title.lower() or "utilization" in findings[0].title.lower()
    )
    assert store.is_file()
