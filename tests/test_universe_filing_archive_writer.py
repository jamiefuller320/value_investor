"""Tests for thin quiet cold-store archive writers + bounded apply path."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.universe_filing_archive_hydrate import pack_index_path, try_hydrate_pack
from value_investor.universe_filing_archive_isolation import (
    ARCHIVE_LANE_BUDGET_ID,
    CRITICAL_PATH_BUDGET_ID,
)
from value_investor.universe_filing_archive_pack_run import run_universe_filing_archive_pack
from value_investor.universe_filing_archive_writer import (
    ArchiveFetchBudget,
    assemble_archive_pack_units,
    select_archive_tickers,
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
    assert isinstance(pack_run.get("unit_results"), list)
    assert pack_run["unit_results"]
    assert pack_run["unit_status_counts"].get("completed", 0) >= 1
    completed_markets = {
        str(row.get("market_id"))
        for row in pack_run["unit_results"]
        if row.get("status") == "completed" and row.get("market_id")
    }
    assert completed_markets
    review = result["bottleneck_review"]
    assert review["throughput"]["units_completed"] >= 1
    assert review["auto_rewrite_deepen"] is False
    for mid in completed_markets:
        assert review["by_market"][mid]["units_attempted"] >= 1
        assert review["by_market"][mid]["units_completed"] >= 1
    assert review["unit_status_counts"].get("completed", 0) >= 1
    persisted = json.loads(pack_run_path.read_text(encoding="utf-8"))
    assert persisted["unit_results"]
    bn_persisted = json.loads(bottleneck_path.read_text(encoding="utf-8"))
    for mid in completed_markets:
        assert bn_persisted["by_market"][mid]["units_completed"] >= 1


def test_workflow_schedule_applies_with_tiny_caps() -> None:
    text = Path(".github/workflows/universe-filing-archive-pack.yml").read_text(encoding="utf-8")
    assert "--apply" in text
    # Schedule/blank dispatch resolve caps from committed stage ladder (not pinned 8/32).
    assert "committed stage ladder" in text
    assert "github.event.inputs.max_units || ''" in text
    assert "github.event.inputs.max_http_fetches || ''" in text
    assert "github.event.inputs.max_units || '8'" not in text
    assert "github.event.inputs.max_http_fetches || '32'" not in text
    assert "github.event.inputs.max_units || '4'" not in text
    assert "github.event.inputs.max_http_fetches || '16'" not in text
    assert "github.event.inputs.max_units || '2'" not in text
    assert "github.event.inputs.max_http_fetches || '8'" not in text
    assert 'if [ -n "${MAX_UNITS}" ]' in text
    assert "cancel-in-progress: true" in text
    assert "NOT a fourth" in text or "not a fourth" in text.lower()
    assert "universe_filings" in Path(".gitignore").read_text(encoding="utf-8")


def _write_universe(library: Path, market_id: str, rows: list[tuple[str, str]]) -> None:
    screen = library / "markets" / market_id / "screen"
    screen.mkdir(parents=True, exist_ok=True)
    lines = ["ticker,name", *[f"{ticker},{name}" for ticker, name in rows]]
    (screen / "latest_universe.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed_hydrated_pack(cold: Path, market_id: str, ticker: str) -> None:
    write_cold_objects(
        market_id=market_id,
        ticker=ticker,
        unit_id=f"seed:{market_id}",
        filings=[{"url": f"https://example.test/{ticker}", "source": "sec", "title": ticker}],
        bodies={f"https://example.test/{ticker}": f"Existing pack for {ticker} " * 8},
        cold_root=cold,
        budget_ids=[f"{ARCHIVE_LANE_BUDGET_ID}:sec"],
    )


def _filing_discover(calls: list[str]):
    def discover(market_id: str, ticker: str, company_name: str) -> list[dict]:
        _ = market_id, company_name
        calls.append(ticker)
        return [{"url": f"https://example.test/{ticker}", "source": "sec", "title": ticker}]

    return discover


def _body_fetch(url: str, source: str) -> str | None:
    _ = source
    return f"Body for {url} with enough characters to pass the pilot threshold."


def test_select_skips_hydrated_packs_and_rotates_within_cap(tmp_path: Path) -> None:
    library = tmp_path / "library"
    cold = tmp_path / "cold"
    rows = [("AAA", "A"), ("BBB", "B"), ("CCC", "C"), ("DDD", "D"), ("EEE", "E")]
    _write_universe(library, "sp500", rows)
    _seed_hydrated_pack(cold, "sp500", "AAA")
    _seed_hydrated_pack(cold, "sp500", "BBB")

    selected = select_pilot_tickers(
        "sp500",
        max_tickers=2,
        library_root=library,
        cold_root=cold,
    )
    assert [row["ticker"] for row in selected] == ["CCC", "DDD"]
    detail = select_archive_tickers(
        "sp500",
        max_tickers=2,
        library_root=library,
        cold_root=cold,
    )
    assert detail["skipped_hydrated"] == 2
    assert detail["scanned"] == 4
    assert detail["skip_hydrated"] is True

    # Without a cold root the nightly bug remains: first N rows, including packed names.
    first_n = select_pilot_tickers("sp500", max_tickers=2, library_root=library)
    assert [row["ticker"] for row in first_n] == ["AAA", "BBB"]


def test_empty_or_unreadable_pack_index_is_not_treated_as_hydrated(tmp_path: Path) -> None:
    library = tmp_path / "library"
    cold = tmp_path / "cold"
    _write_universe(library, "sp500", [("AAA", "A"), ("BBB", "B"), ("CCC", "C")])
    empty = pack_index_path("sp500", "AAA", cold_root=cold)
    empty.parent.mkdir(parents=True)
    empty.write_text('{"objects": []}\n', encoding="utf-8")
    broken = pack_index_path("sp500", "BBB", cold_root=cold)
    broken.parent.mkdir(parents=True)
    broken.write_text("{", encoding="utf-8")

    detail = select_archive_tickers(
        "sp500",
        max_tickers=2,
        library_root=library,
        cold_root=cold,
    )
    assert [row["ticker"] for row in detail["tickers"]] == ["AAA", "BBB"]
    assert detail["skipped_hydrated"] == 0


def test_assemble_skips_hydrated_and_second_pass_does_not_rewrite(tmp_path: Path) -> None:
    library = tmp_path / "library"
    cold = tmp_path / "cold"
    _write_universe(
        library,
        "sp500",
        [("AAA", "A"), ("BBB", "B"), ("CCC", "C"), ("DDD", "D")],
    )
    _seed_hydrated_pack(cold, "sp500", "AAA")
    _seed_hydrated_pack(cold, "sp500", "BBB")
    calls: list[str] = []
    plan = {
        "unit_count": 1,
        "units": [{"unit_id": "2026-W40:sp500", "market_id": "sp500"}],
    }
    first = assemble_archive_pack_units(
        plan,
        cold_root=cold,
        library_root=library,
        max_tickers_per_unit=2,
        max_bodies_per_ticker=1,
        max_http_fetches=8,
        discover_fn=_filing_discover(calls),
        body_fetch_fn=_body_fetch,
    )
    assert calls == ["CCC", "DDD"]
    assert first["tickers_skipped_hydrated"] == 2
    assert first["tickers_selected"] == 2
    assert first["objects_written"] == 2
    assert first["fourth_equal_sprint_stream"] is False
    assert first["capacity_isolation"]["preemptible"] is True
    assert first["capacity_isolation"]["http_fetches"] == 4
    assert first["capacity_isolation"]["isolation_ok"] is True
    completed = next(row for row in first["unit_results"] if row["status"] == "completed")
    assert completed["tickers"] == ["CCC", "DDD"]
    assert completed["skipped_hydrated"] == 2

    calls.clear()
    second = assemble_archive_pack_units(
        plan,
        cold_root=cold,
        library_root=library,
        max_tickers_per_unit=2,
        max_bodies_per_ticker=1,
        max_http_fetches=8,
        discover_fn=_filing_discover(calls),
        body_fetch_fn=_body_fetch,
    )
    assert calls == []
    assert second["objects_written"] == 0
    assert second["tickers_skipped_hydrated"] == 4
    assert second["capacity_isolation"]["http_fetches"] == 0
    assert second["capacity_isolation"]["preemptible"] is True
    assert second["unit_results"][0]["status"] == "skipped_hydrated"


def test_assemble_rotation_stays_inside_http_budget(tmp_path: Path) -> None:
    library = tmp_path / "library"
    cold = tmp_path / "cold"
    _write_universe(library, "sp500", [("AAA", "A"), ("BBB", "B"), ("CCC", "C")])
    _seed_hydrated_pack(cold, "sp500", "AAA")
    calls: list[str] = []
    plan = {
        "unit_count": 1,
        "units": [{"unit_id": "2026-W40:sp500", "market_id": "sp500"}],
    }
    # Discover + body is two archive fetches. Cap 2 so only one uncovered ticker runs.
    assembled = assemble_archive_pack_units(
        plan,
        cold_root=cold,
        library_root=library,
        max_tickers_per_unit=2,
        max_bodies_per_ticker=1,
        max_http_fetches=2,
        discover_fn=_filing_discover(calls),
        body_fetch_fn=_body_fetch,
    )
    assert calls == ["BBB"]
    assert assembled["objects_written"] == 1
    assert assembled["capacity_isolation"]["http_fetches"] == 2
    assert assembled["capacity_isolation"]["max_http_fetches"] == 2
    assert assembled["fourth_equal_sprint_stream"] is False


def test_later_unit_rotates_past_packs_written_this_run(tmp_path: Path) -> None:
    library = tmp_path / "library"
    cold = tmp_path / "cold"
    _write_universe(library, "sp500", [("AAA", "A"), ("BBB", "B")])
    calls: list[str] = []
    plan = {
        "unit_count": 2,
        "units": [
            {"unit_id": "2026-W40:sp500", "market_id": "sp500"},
            {"unit_id": "2026-W39:sp500", "market_id": "sp500"},
        ],
    }
    assembled = assemble_archive_pack_units(
        plan,
        cold_root=cold,
        library_root=library,
        max_tickers_per_unit=1,
        max_bodies_per_ticker=1,
        max_http_fetches=8,
        discover_fn=_filing_discover(calls),
        body_fetch_fn=_body_fetch,
    )
    assert calls == ["AAA", "BBB"]
    assert assembled["objects_written"] == 2
    assert assembled["units_completed"] == 2
    assert assembled["tickers_skipped_hydrated"] == 1
    assert assembled["capacity_isolation"]["preemptible"] is True
    assert assembled["fourth_equal_sprint_stream"] is False


def test_archive_job_apply_skips_hydrated_and_records_rotation(tmp_path: Path) -> None:
    library = tmp_path / "library"
    cold = tmp_path / "cold"
    # Live screen is always first on the roster, so max_units=1 plans ftse350.
    _write_universe(library, "ftse350", [("AAA.L", "Alpha"), ("BBB.L", "Beta")])
    _seed_hydrated_pack(cold, "ftse350", "AAA.L")
    calls: list[str] = []
    status = tmp_path / "market_status.json"
    policy = tmp_path / "policy.json"
    status.write_text(json.dumps({"admitted_markets": ["sp500"]}), encoding="utf-8")
    policy.write_text("{}", encoding="utf-8")
    result = run_universe_filing_archive_pack(
        now=datetime(2026, 10, 1, 22, 0, tzinfo=UTC),
        dry_run=False,
        lookback_weeks=1,
        max_units=1,
        max_tickers_per_unit=1,
        max_http_fetches=8,
        market_status_path=status,
        policy_path=policy,
        pack_run_path=tmp_path / "pack_run.json",
        bottleneck_path=tmp_path / "bottleneck.json",
        cold_root=cold,
        library_root=library,
        persist=True,
        force_allow_for_test=True,
        discover_fn=_filing_discover(calls),
        body_fetch_fn=_body_fetch,
    )
    assert "AAA.L" not in calls
    assert calls == ["BBB.L"]
    pack_run = result["pack_run"]
    assert pack_run["outcome"] == "apply_complete"
    assert pack_run["tickers_skipped_hydrated"] == 1
    assert pack_run["tickers_selected"] == 1
    assert pack_run["objects_written"] == 1
    assert pack_run["preemptible"] is True
    assert pack_run["fourth_equal_sprint_stream"] is False
    assert pack_run["capacity_isolation"]["isolation_ok"] is True
    assert result["bottleneck_review"]["throughput"]["tickers_skipped_hydrated"] == 1
    persisted = json.loads((tmp_path / "pack_run.json").read_text(encoding="utf-8"))
    assert persisted["tickers_skipped_hydrated"] == 1
