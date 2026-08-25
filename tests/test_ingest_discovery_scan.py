"""Tests for scan-then-target FTSE discovery ingest."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.ingest_discovery_scan import (
    KNOWN_FILING_SOURCES,
    collect_curiosity_for_rows,
    merge_discovery_into_index,
    run_buy_tier_discovery_scan,
)
from value_investor.research.ingest_improvement import (
    _priority_score,
    run_ingest_improvement_pass,
    select_ingest_improvement_targets,
)
from value_investor.summary import CompanyReport


def _report(ticker: str, name: str, signal: str = "strong_buy") -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=name,
        sector="Industrials",
        signal=signal,
        models_passed=5,
        model_count=10,
        composite_score=0.7,
        sector_composite_score=0.8,
        families_passed=4,
        passed_families="cheapness,quality",
        data_quality_score=0.9,
        metrics_present=18,
        metrics_total=20,
        weeks_at_signal=1,
        signal_trend="new",
        conviction_score=0.5,
        stability_label="new",
        timing_signal="neutral",
        timing_score=0.0,
        rsi_14=50.0,
        price_vs_sma200_pct=0.0,
        action_note="",
        trade_plan=None,
        summary="test",
        passed_models=[],
        key_metrics={},
    )


def test_collect_curiosity_flags_unknown_source_and_host():
    rows = [
        {
            "id": "1",
            "source": "ticker_rns_api",
            "url": "https://www.londonstockexchange.com/news/1",
            "headline": "Known",
        },
        {
            "id": "2",
            "source": "brand_new_registrar",
            "url": "https://filings.example-odd-host.test/doc.pdf",
            "headline": "Novel",
        },
    ]
    items = collect_curiosity_for_rows(rows)
    kinds = {item.kind for item in items}
    assert "unknown_source" in kinds
    assert "unknown_host" in kinds
    assert "brand_new_registrar" not in KNOWN_FILING_SOURCES


def test_merge_discovery_preserves_existing_bodies(tmp_path: Path):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    prior = [
        {
            "id": "old1",
            "source": "companies_house",
            "headline": "Annual Report 2024",
            "published_at": "2024-03-01",
            "url": "https://example.com/old",
            "has_body": True,
            "body_path": "bodies/old1.txt",
            "priority": 1,
        }
    ]
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"filings": prior}),
        encoding="utf-8",
    )
    discovered = [
        {
            "id": "old1",
            "source": "companies_house",
            "headline": "Annual Report 2024",
            "published_at": "2024-03-01",
            "url": "https://example.com/old",
            "has_body": False,
            "body_path": None,
            "priority": 1,
        },
        {
            "id": "new1",
            "source": "ticker_rns_api",
            "headline": "Trading Update",
            "published_at": "2026-08-01",
            "url": "https://www.londonstockexchange.com/news/new",
            "has_body": False,
            "body_path": None,
            "priority": 2,
        },
    ]
    meta = merge_discovery_into_index(
        filings_dir=filings_dir,
        ticker="AAA.L",
        company_name="AAA",
        discovered=discovered,
    )
    payload = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in payload["filings"]}
    assert by_id["old1"]["has_body"] is True
    assert by_id["old1"]["body_path"] == "bodies/old1.txt"
    assert by_id["new1"]["has_body"] is False
    assert meta["merged_count"] == 2


def test_scan_detects_new_rows_and_writes_curiosity(tmp_path: Path):
    output_dir = tmp_path / "data"
    research = output_dir / "research" / "AAA.L" / "sources" / "filings"
    research.mkdir(parents=True)
    (research / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": "old",
                        "source": "companies_house",
                        "headline": "Old",
                        "published_at": "2024-01-01",
                        "url": "https://example.com/old",
                        "has_body": True,
                        "body_path": "bodies/old.txt",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    listed = [
        {
            "id": "old",
            "source": "companies_house",
            "headline": "Old",
            "published_at": "2024-01-01",
            "url": "https://example.com/old",
        },
        {
            "id": "new",
            "source": "mystery_feed",
            "headline": "Brand New Filing",
            "published_at": "2026-08-20",
            "url": "https://odd.example.org/x",
        },
    ]
    with patch(
        "value_investor.ingest_discovery_scan.list_uk_filings_index_only",
        return_value=listed,
    ):
        summary = run_buy_tier_discovery_scan(
            [_report("AAA.L", "AAA")],
            output_dir=output_dir,
            summary_path=output_dir / "ingest_discovery_scan_summary.json",
            curiosity_path=output_dir / "ingest_discovery_curiosity.json",
        )
    assert summary.scanned == 1
    assert summary.hits == 1
    assert summary.new_rows_total == 1
    assert summary.curiosity_total >= 1
    hit = summary.tickers[0]
    assert hit.new_row_count == 1
    assert hit.priority_bonus() > 0
    curiosity = json.loads(
        (output_dir / "ingest_discovery_curiosity.json").read_text(encoding="utf-8")
    )
    assert curiosity["engineering_never_complete"] is True
    assert curiosity["entries"]


def test_discovery_bonus_raises_priority_and_selects_hit(tmp_path: Path):
    output_dir = tmp_path / "data"
    for ticker, total, with_body in (("HIT.L", 5, 5), ("OTH.L", 5, 5)):
        filings = output_dir / "research" / ticker / "sources" / "filings"
        filings.mkdir(parents=True)
        rows = [
            {
                "id": f"{ticker}-{i}",
                "headline": f"H{i}",
                "published_at": f"2024-0{i + 1}-01",
                "period": "annual",
                "has_body": True,
                "body_path": f"bodies/{i}.txt",
            }
            for i in range(total)
        ]
        (filings / "filings_index.json").write_text(
            json.dumps(
                {
                    "summary": {"total": total, "with_body": with_body, "annual": total},
                    "filings": rows,
                }
            ),
            encoding="utf-8",
        )

    coverage = {
        "filings_total": 5,
        "filings_with_body": 5,
        "indexed_without_body": 0,
        "filings_annual": 5,
        "annual_with_body": 5,
        "filings_interim": 0,
        "interim_with_body": 0,
        "filings_trading_update": 0,
        "trading_update_with_body": 0,
    }
    base = _priority_score(coverage, [], signal="strong_buy", ticker="HIT.L")
    boosted = _priority_score(
        coverage, [], signal="strong_buy", ticker="HIT.L", discovery_bonus=12.0
    )
    assert boosted > base

    targets = select_ingest_improvement_targets(
        [_report("HIT.L", "Hit"), _report("OTH.L", "Other")],
        output_dir=output_dir,
        max_targets=1,
        discovery_bonus_by_ticker={"HIT.L": 20.0},
    )
    assert targets
    assert targets[0].ticker == "HIT.L"


def test_run_ingest_improvement_pass_runs_discovery_before_select(tmp_path: Path):
    output_dir = tmp_path / "data"
    report = _report("ZZZ.L", "Zed")
    listed = [
        {
            "id": "n1",
            "source": "ticker_rns_api",
            "headline": "New RNS",
            "published_at": "2026-08-21",
            "url": "https://www.londonstockexchange.com/n1",
            "period": "trading_update",
            "priority": 2,
        }
    ]

    def _fake_scan(reports, **kwargs):
        from value_investor.ingest_discovery_scan import DiscoveryScanSummary, TickerDiscoveryHit

        hit = TickerDiscoveryHit(
            ticker="ZZZ.L",
            name="Zed",
            signal="strong_buy",
            new_row_count=1,
            new_rows=listed,
            listed_count=1,
        )
        summary = DiscoveryScanSummary(scanned=1, hits=1, new_rows_total=1, tickers=[hit])
        return summary

    with (
        patch(
            "value_investor.research.ingest_improvement.bootstrap_buy_tier_research",
            return_value={},
        ),
        patch(
            "value_investor.ingest_discovery_scan.run_buy_tier_discovery_scan",
            side_effect=_fake_scan,
        ),
        patch(
            "value_investor.research.ingest_improvement.ingest_research_sources",
            return_value={"filings_summary": {"total": 1, "with_body": 0}},
        ),
        patch(
            "value_investor.research.ingest_improvement.refetch_uk_primary_filing_bodies",
            return_value={"attempted": 0, "fetched": 0},
        ),
        patch(
            "value_investor.research.ingest_improvement.refetch_ir_allowlist_filing_bodies",
            return_value={"attempted": 0, "fetched": 0},
        ),
        patch(
            "value_investor.research.ingest_improvement.execute_planned_alternate_sources",
            return_value={"fetched": 0},
        ),
        patch(
            "value_investor.research.ingest_improvement.deepen_thin_filings_if_needed",
            return_value={"skipped": True},
        ),
        patch(
            "value_investor.research.ingest_improvement.sanitize_filings_index",
            return_value={},
        ),
        patch(
            "value_investor.research.filings.reconcile_filings_index_body_flags",
            return_value={},
        ),
        patch(
            "value_investor.research.ingest_improvement.attach_screen_run_manifest",
            return_value={},
        ),
        patch(
            "value_investor.research.ingest_improvement.inspect_local_sources",
            return_value={"mapped_source_ids": [], "thin_sources": []},
        ),
        patch(
            "value_investor.research.ingest_improvement._filing_coverage",
            return_value={
                "filings_total": 1,
                "filings_with_body": 0,
                "indexed_without_body": 1,
                "filings_annual": 0,
                "annual_with_body": 0,
                "filings_interim": 0,
                "interim_with_body": 0,
                "filings_trading_update": 1,
                "trading_update_with_body": 0,
            },
        ),
    ):
        summary = run_ingest_improvement_pass(
            reports=[report],
            output_dir=output_dir,
            market="ftse350",
            max_targets=1,
            discovery_scan=True,
            bootstrap_seed_cap=0,
        )
    assert summary.discovery_scan is not None
    assert summary.discovery_scan["hits"] == 1
    assert summary.targets
    assert summary.targets[0].ticker == "ZZZ.L"
