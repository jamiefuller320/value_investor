"""Tests for library weekday ingest loop."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.data_library_cli import main as library_main
from value_investor.library_ingest_loop import (
    LibraryIngestLoopResult,
    _filing_coverage_for_ticker,
    run_library_ingest_loop,
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


def test_select_library_ingest_targets_prioritizes_unmeasured(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    screen_dir = root / "markets" / market / "screen"
    research_dir = screen_dir / "research"
    for ticker in ("AAA.DE", "BBB.DE"):
        filings_dir = research_dir / ticker / "sources" / "filings"
        filings_dir.mkdir(parents=True)
        write_json(
            filings_dir / "filings_index.json",
            {
                "summary": {"total": 0 if ticker == "AAA.DE" else 5, "with_body": 0},
                "filings": [],
            },
            compact=False,
        )
    reports = [_report("AAA.DE"), _report("BBB.DE", conviction=0.9)]
    targets = select_library_ingest_targets(
        reports,
        library_root=root,
        market_id=market,
        max_targets=2,
    )
    assert targets[0].ticker == "AAA.DE"
    assert targets[0].reason == "unmeasured"


def test_filing_coverage_prefers_market_canonical_index_over_stale_shard(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    ticker = "ZZCANON.AS"

    stale_dir = root / "markets" / "aex" / "screen" / "research" / ticker / "sources" / "filings"
    stale_dir.mkdir(parents=True)
    write_json(
        stale_dir / "filings_index.json",
        {"summary": {"total": 0, "with_body": 0}, "filings": []},
        compact=False,
    )

    canonical_dir = (
        root / "markets" / market / "screen" / "research" / ticker / "sources" / "filings"
    )
    canonical_dir.mkdir(parents=True)
    write_json(
        canonical_dir / "filings_index.json",
        {"summary": {"total": 2, "with_body": 2}, "filings": []},
        compact=False,
    )

    coverage = _filing_coverage_for_ticker(
        ticker,
        library_root=root,
        market_id=market,
    )
    assert coverage == {"filings_total": 2, "filings_with_body": 2, "indexed_without_body": 0}


def test_filing_coverage_uses_best_fallback_when_canonical_missing(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    # Synthetic ticker — must not collide with committed docs/data/library names.
    ticker = "ZZFALLBACK.AS"

    stale_dir = root / "markets" / "aex" / "screen" / "research" / ticker / "sources" / "filings"
    stale_dir.mkdir(parents=True)
    write_json(
        stale_dir / "filings_index.json",
        {"summary": {"total": 0, "with_body": 0}, "filings": []},
        compact=False,
    )

    other_dir = root / "markets" / "dax" / "screen" / "research" / ticker / "sources" / "filings"
    other_dir.mkdir(parents=True)
    write_json(
        other_dir / "filings_index.json",
        {"summary": {"total": 4, "with_body": 3}, "filings": [{}, {}, {}, {}]},
        compact=False,
    )

    coverage = _filing_coverage_for_ticker(
        ticker,
        library_root=root,
        market_id=market,
    )
    assert coverage == {"filings_total": 4, "filings_with_body": 3, "indexed_without_body": 4}


def test_filing_coverage_canonical_only_ignores_other_shard(tmp_path: Path):
    root = tmp_path / "library"
    ticker = "ZZZZTEST"
    nasdaq_dir = (
        root / "markets" / "nasdaq100" / "screen" / "research" / ticker / "sources" / "filings"
    )
    nasdaq_dir.mkdir(parents=True)
    write_json(
        nasdaq_dir / "filings_index.json",
        {"summary": {"total": 20, "with_body": 18}, "filings": []},
        compact=False,
    )
    fallback = _filing_coverage_for_ticker(
        ticker,
        library_root=root,
        market_id="sp500",
        canonical_only=False,
    )
    assert fallback["filings_with_body"] == 18
    canonical = _filing_coverage_for_ticker(
        ticker,
        library_root=root,
        market_id="sp500",
        canonical_only=True,
    )
    assert canonical == {"filings_total": 0, "filings_with_body": 0, "indexed_without_body": 0}


def test_library_ingest_loop_cli_writes_json_path(tmp_path: Path):
    """CI must read clean JSON from --json-path even if stdout has warnings."""
    out_path = tmp_path / "euro_ingest_loop.json"
    result = LibraryIngestLoopResult(
        market_id="euro_depth",
        improved=["AAA.DE"],
        partial=False,
        health_before={"unmeasured_buy_tier": 2},
        health_after={"unmeasured_buy_tier": 1},
    )
    with patch(
        "value_investor.library_ingest_loop.run_library_ingest_loop",
        return_value=result,
    ):
        assert (
            library_main(
                [
                    "ingest-loop",
                    "--market",
                    "euro_depth",
                    "--json-path",
                    str(out_path),
                    "--root",
                    str(tmp_path / "library"),
                ]
            )
            == 0
        )
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["market_id"] == "euro_depth"
    assert payload["improved"] == ["AAA.DE"]
    assert payload["health_after"]["unmeasured_buy_tier"] == 1


def test_euro_ingest_dispatch_cli_writes_json_path(tmp_path: Path):
    out_path = tmp_path / "euro_ingest_dispatch.json"
    dispatch = {
        "mode": "sprint",
        "should_run_ingest": True,
        "max_daily_successes": 4,
        "max_targets": 24,
        "reason": "test",
    }
    with patch(
        "value_investor.euro_depth_ingest_dispatch.evaluate_euro_ingest_dispatch",
        return_value=dispatch,
    ):
        assert (
            library_main(
                [
                    "euro-ingest-dispatch",
                    "--json-path",
                    str(out_path),
                    "--root",
                    str(tmp_path / "library"),
                ]
            )
            == 0
        )
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "sprint"
    assert payload["should_run_ingest"] is True


def test_library_ingest_json_path_survives_stdout_pollution(tmp_path: Path, capsys):
    """Reproduce morning failure mode: stdout noise must not taint --json-path."""
    out_path = tmp_path / "euro_ingest_loop.json"
    result = LibraryIngestLoopResult(market_id="euro_depth", improved=["BBB.DE"])

    def _run(*_a, **_k):
        print(
            "warning: The `fitz` API is deprecated and will be removed in future. "
            "Use `import pymupdf` instead."
        )
        return result

    with patch(
        "value_investor.library_ingest_loop.run_library_ingest_loop",
        side_effect=_run,
    ):
        assert (
            library_main(
                [
                    "ingest-loop",
                    "--json",
                    "--json-path",
                    str(out_path),
                    "--root",
                    str(tmp_path / "library"),
                ]
            )
            == 0
        )
    captured = capsys.readouterr().out
    assert "fitz" in captured
    # Teeing stdout would break; the dedicated path must stay parseable.
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["improved"] == ["BBB.DE"]


def test_run_library_ingest_loop_counts_discovery_toward_runtime(tmp_path: Path):
    """Discovery must consume the runtime budget so GHA jobs can finish before timeout."""
    root = tmp_path / "library"
    market = "euro_depth"
    research = root / "markets" / market / "screen" / "research"
    for ticker in ("AAA.DE", "BBB.DE"):
        filings = research / ticker / "sources" / "filings"
        filings.mkdir(parents=True)
        write_json(
            filings / "filings_index.json",
            {"summary": {"total": 0, "with_body": 0}, "filings": []},
            compact=False,
        )
    reports = [_report("AAA.DE"), _report("BBB.DE")]

    class _Scan:
        scanned = 2
        hits = 0
        new_rows_total = 0
        curiosity_total = 0
        errors = 0
        prioritization_weights: dict = {}
        tickers: list = []

    ingest_calls: list[str] = []

    def _slow_discovery(*_a, **_k):
        import time

        time.sleep(0.05)
        return _Scan()

    def _track_ingest(target, **_k):
        ingest_calls.append(target.ticker)
        return {"ticker": target.ticker, "improved": False}

    with (
        patch(
            "value_investor.library_ingest_loop.load_library_buy_tier_reports",
            return_value=reports,
        ),
        patch(
            "value_investor.library_ingest_loop.snapshot_library_ingest_health",
            return_value={"unmeasured_buy_tier": 2, "zero_body_buy_tier": 0},
        ),
        patch("value_investor.library_ingest_loop.append_library_ingest_health_log"),
        patch(
            "value_investor.library_discovery_scan.run_library_buy_tier_discovery_scan",
            side_effect=_slow_discovery,
        ),
        patch(
            "value_investor.library_ingest_loop._ingest_single_library_target",
            side_effect=_track_ingest,
        ),
        patch(
            "value_investor.ingest_critical_path.assess_library_ingest_critical_path",
            return_value=type(
                "CP",
                (),
                {
                    "force_discovery_scan": False,
                    "auto_pin_tickers": [],
                    "primary_blocker": "none",
                    "to_dict": lambda self: {},
                },
            )(),
        ),
        patch("value_investor.ingest_critical_path.persist_ingest_critical_path"),
        patch(
            "value_investor.ingest_critical_path.apply_critical_path_to_target_order",
            side_effect=lambda targets, _c: targets,
        ),
    ):
        result = run_library_ingest_loop(
            market,
            library_root=root,
            max_targets=2,
            max_runtime_seconds=0.01,
            discovery_scan=True,
            deepen_history=False,
        )

    assert result.runtime_cutoff is True
    assert result.partial is True
    assert ingest_calls == []
