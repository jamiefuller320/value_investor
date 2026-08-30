"""Tests for ingest critical-path assessment and automated actions."""

from __future__ import annotations

from pathlib import Path

from value_investor.ingest_critical_path import (
    apply_critical_path_to_target_order,
    assess_library_ingest_critical_path,
    persist_ingest_critical_path,
)
from value_investor.library_ingest_loop import (
    LibraryIngestTarget,
    select_library_ingest_targets,
)
from value_investor.storage import write_json
from value_investor.summary import CompanyReport


def _report(ticker: str, signal: str = "buy", conviction: float = 0.5) -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=f"{ticker} Co",
        sector="X",
        signal=signal,
        models_passed=5,
        model_count=10,
        composite_score=0.6,
        sector_composite_score=0.55,
        families_passed=3,
        passed_families="cheapness",
        data_quality_score=0.8,
        metrics_present=10,
        metrics_total=12,
        weeks_at_signal=1,
        signal_trend="stable",
        conviction_score=conviction,
        stability_label="stable",
        timing_signal="hold",
        timing_score=0.0,
        rsi_14=None,
        price_vs_sma200_pct=None,
        action_note="",
        trade_plan=None,
        summary="",
        passed_models=[],
        key_metrics={},
    )


def _write_index(
    root: Path,
    market: str,
    ticker: str,
    *,
    total: int,
    with_body: int,
) -> None:
    filings_dir = root / "markets" / market / "screen" / "research" / ticker / "sources" / "filings"
    filings_dir.mkdir(parents=True)
    indexed = max(0, total - with_body)
    write_json(
        filings_dir / "filings_index.json",
        {
            "summary": {
                "total": total,
                "with_body": with_body,
                "indexed_without_body": indexed,
            },
            "filings": [],
        },
        compact=False,
    )


def test_critical_path_prefers_iwb_and_forces_discovery(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    _write_index(root, market, "AAA.DE", total=0, with_body=0)
    _write_index(root, market, "BBB.DE", total=20, with_body=10)
    _write_index(root, market, "CCC.DE", total=2, with_body=2)
    reports = [_report("AAA.DE"), _report("BBB.DE", conviction=0.9), _report("CCC.DE")]
    path = assess_library_ingest_critical_path(market, library_root=root, reports=reports)
    assert path.primary_blocker == "unmeasured"
    assert "AAA.DE" in path.unmeasured
    assert path.indexed_without_body[0]["ticker"] == "BBB.DE"
    assert "CCC.DE" in path.thin_need_discovery
    assert path.force_discovery_scan is True
    assert path.auto_pin_tickers[0] in {"BBB.DE", "AAA.DE"}
    out = persist_ingest_critical_path(path, path=tmp_path / "cp.json", library_root=root)
    assert out.exists()
    assert (root / "markets" / market / "ingest_critical_path.json").exists()


def test_select_targets_prefers_iwb_over_thin_and_skips_maintain(tmp_path: Path):
    root = tmp_path / "library"
    market = "sp500"
    _write_index(root, market, "IWB", total=20, with_body=10)
    _write_index(root, market, "THIN", total=2, with_body=2)
    _write_index(root, market, "FULL", total=10, with_body=10)
    reports = [
        _report("FULL", conviction=0.99),
        _report("THIN", conviction=0.8),
        _report("IWB", conviction=0.1),
    ]
    targets = select_library_ingest_targets(
        reports,
        library_root=root,
        market_id=market,
        max_targets=5,
        canonical_only=True,
    )
    assert [t.ticker for t in targets] == ["IWB", "THIN"]
    assert targets[0].reason == "indexed_without_body"
    assert targets[1].reason == "thin_bodies"


def test_apply_critical_path_reorders_targets(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    _write_index(root, market, "A", total=10, with_body=5)
    _write_index(root, market, "B", total=0, with_body=0)
    reports = [_report("A"), _report("B")]
    assessment = assess_library_ingest_critical_path(market, library_root=root, reports=reports)
    targets = [
        LibraryIngestTarget("A", "A", "buy", 1.0, reason="indexed_without_body"),
        LibraryIngestTarget("B", "B", "buy", 1.0, reason="unmeasured"),
    ]
    ordered = apply_critical_path_to_target_order(targets, assessment)
    assert ordered[0].ticker in assessment.auto_pin_tickers
