"""Tests for thin quiet cold-store archive writers + bounded apply path."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.universe_filing_archive_hydrate import try_hydrate_pack
from value_investor.universe_filing_archive_isolation import (
    ARCHIVE_LANE_BUDGET_ID,
    CRITICAL_PATH_BUDGET_ID,
)
from value_investor.universe_filing_archive_pack_run import run_universe_filing_archive_pack
from value_investor.universe_filing_archive_writer import (
    ArchiveFetchBudget,
    assemble_archive_pack_units,
    select_pilot_tickers,
    write_cold_objects,
)


def test_archive_fetch_budget_never_uses_critical_path() -> None:
    budget = ArchiveFetchBudget(max_fetches=3)
    bid = budget.record("sec")
    assert bid.startswith(f"{ARCHIVE_LANE_BUDGET_ID}:")
    assert not bid.startswith(CRITICAL_PATH_BUDGET_ID)
    assert budget.try_record("esef") is not None
    assert budget.try_record("ir_pdf") is not None
    assert budget.try_record("sec") is None  # exhausted
    snap = budget.snapshot()
    assert snap["isolation_ok"] is True
    assert snap["shared_critical_path"] is False
    assert snap["fourth_equal_sprint_stream"] is False
    assert snap["http_fetches"] == 3


def test_select_pilot_tickers_from_universe_csv(tmp_path: Path) -> None:
    root = tmp_path / "library" / "markets" / "euro_depth" / "screen"
    root.mkdir(parents=True)
    (root / "latest_universe.csv").write_text(
        "ticker,name\nAAA.PA,Alpha\nBBB.DE,Beta\nCCC.AS,Gamma\n",
        encoding="utf-8",
    )
    rows = select_pilot_tickers(
        "euro_depth",
        max_tickers=2,
        library_root=tmp_path / "library",
    )
    assert [r["ticker"] for r in rows] == ["AAA.PA", "BBB.DE"]


def test_write_cold_objects_hydrate_hit(tmp_path: Path) -> None:
    cold = tmp_path / "cold"
    index = write_cold_objects(
        market_id="euro_depth",
        ticker="AAA.PA",
        unit_id="2026-W40:euro_depth",
        filings=[
            {
                "url": "https://example.test/a",
                "source": "esef",
                "title": "Annual",
            }
        ],
        bodies={
            "https://example.test/a": "Filing body text " * 20,
        },
        cold_root=cold,
        budget_ids=[f"{ARCHIVE_LANE_BUDGET_ID}:esef"],
    )
    assert index["object_count"] == 1
    hit = try_hydrate_pack("euro_depth", "AAA.PA", cold_root=cold)
    assert hit.status == "hit"
    assert hit.object_count == 1
    assert hit.fail_open is True


def test_assemble_and_apply_pack_with_injectable_fetch(tmp_path: Path) -> None:
    cold = tmp_path / "cold"
    library = tmp_path / "library"
    for mid, tick, name in (
        ("ftse350", "AAA.L", "Alpha UK"),
        ("sp500", "AAA", "Alpha Co"),
    ):
        screen = library / "markets" / mid / "screen"
        screen.mkdir(parents=True)
        (screen / "latest_universe.csv").write_text(
            f"ticker,name\n{tick},{name}\nBBB,Beta Co\n",
            encoding="utf-8",
        )

    def discover(market_id: str, ticker: str, company_name: str) -> list[dict]:
        _ = market_id, company_name
        return [
            {
                "url": f"https://example.test/{ticker}",
                "source": "sec",
                "title": f"{ticker} 10-K",
            }
        ]

    def body_fetch(url: str, source: str) -> str | None:
        _ = source
        return f"Body for {url} with enough characters to pass the pilot threshold."

    plan = {
        "unit_count": 1,
        "units": [
            {
                "unit_id": "2026-W40:sp500",
                "market_id": "sp500",
                "iso_year": 2026,
                "iso_week": 40,
            }
        ],
    }
    assembled = assemble_archive_pack_units(
        plan,
        cold_root=cold,
        library_root=library,
        max_tickers_per_unit=1,
        max_bodies_per_ticker=1,
        max_http_fetches=8,
        discover_fn=discover,
        body_fetch_fn=body_fetch,
    )
    assert assembled["units_completed"] == 1
    assert assembled["objects_written"] >= 1
    assert assembled["hydrate_hits"] >= 1
    isolation = assembled["capacity_isolation"]
    assert isolation["isolation_ok"] is True
    assert isolation["http_fetches"] >= 1
    assert all(b.startswith(f"{ARCHIVE_LANE_BUDGET_ID}:") for b in isolation["source_budgets_used"])

    pack_run_path = tmp_path / "pack_run.json"
    bottleneck_path = tmp_path / "bottleneck.json"
    status = tmp_path / "market_status.json"
    policy = tmp_path / "policy.json"
    status.write_text(json.dumps({"admitted_markets": ["sp500"]}), encoding="utf-8")
    policy.write_text("{}", encoding="utf-8")
    result = run_universe_filing_archive_pack(
        now=datetime(2026, 10, 1, 22, 0, tzinfo=UTC),
        dry_run=False,
        lookback_weeks=1,
        max_units=1,
        market_status_path=status,
        policy_path=policy,
        pack_run_path=pack_run_path,
        bottleneck_path=bottleneck_path,
        cold_root=cold,
        library_root=library,
        persist=True,
        force_allow_for_test=True,
        discover_fn=discover,
        body_fetch_fn=body_fetch,
    )
    assert result["exit_code"] == 0
    pack_run = result["pack_run"]
    assert pack_run["outcome"] == "apply_complete"
    assert pack_run["dry_run"] is False
    assert pack_run["fourth_equal_sprint_stream"] is False
    assert pack_run["capacity_isolation"]["isolation_ok"] is True
    assert pack_run["objects_written"] >= 1
    assert result["bottleneck_review"]["throughput"]["units_completed"] >= 1
    assert result["bottleneck_review"]["auto_rewrite_deepen"] is False


def test_workflow_schedule_applies_with_tiny_caps() -> None:
    text = Path(".github/workflows/universe-filing-archive-pack.yml").read_text(encoding="utf-8")
    assert "--apply" in text
    assert 'default: "2"' in text
    assert "cancel-in-progress: true" in text
    assert "NOT a fourth" in text or "not a fourth" in text.lower()
    assert "universe_filings" in Path(".gitignore").read_text(encoding="utf-8")
