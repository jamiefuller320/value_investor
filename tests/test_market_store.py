"""Market-agnostic research store resolution and rememo eligibility."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.research.document import ResearchDocument
from value_investor.research.market_store import (
    coverage_incomplete_reason,
    library_coverage_incomplete_tickers,
    library_rememo_eligible_tickers,
    rememo_reason,
    resolve_research_documents,
)
from value_investor.research.overlay_refresh import refresh_dashboard_bundle
from value_investor.storage import write_json


def _write_memo(
    research_root: Path,
    ticker: str,
    *,
    verdict: str = "accumulate",
    grade: str = "thin",
    memo_bodies: int = 0,
    disk_bodies: int = 0,
) -> None:
    ticker_dir = research_root / ticker
    (ticker_dir / "sources" / "filings").mkdir(parents=True)
    write_json(
        ticker_dir / "research.json",
        ResearchDocument(
            ticker=ticker,
            name=ticker,
            signal="buy",
            version=1,
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-01T00:00:00+00:00",
            mode="initial",
            research_verdict=verdict,
            research_confidence=0.7,
            memo_quality={"grade": grade, "filings_with_body": memo_bodies},
            source_counts={"filings_with_body": memo_bodies},
        ).to_dict(),
        compact=True,
    )
    (ticker_dir / "research.md").write_text(f"# {ticker}\n", encoding="utf-8")
    write_json(
        ticker_dir / "sources" / "filings" / "filings_index.json",
        {"summary": {"with_body": disk_bodies, "total": disk_bodies}},
        compact=True,
    )


def test_coverage_incomplete_reason_zero_body_or_missing_verdict():
    assert coverage_incomplete_reason(grade="thin", memo_bodies=0, has_verdict=True) == (
        "zero_body"
    )
    assert coverage_incomplete_reason(grade="strong", memo_bodies=20, has_verdict=True) is None
    assert coverage_incomplete_reason(grade="strong", memo_bodies=20, has_verdict=False) == (
        "missing_verdict"
    )


def test_library_coverage_incomplete_tickers_scans_all_shards(tmp_path: Path):
    _write_memo(
        tmp_path / "markets" / "euro_depth" / "screen" / "research",
        "ERIC-B.ST",
        verdict="accumulate",
        grade="thin",
        memo_bodies=0,
    )
    _write_memo(
        tmp_path / "markets" / "sp500" / "screen" / "research",
        "AAPL",
        verdict="accumulate",
        grade="strong",
        memo_bodies=40,
        disk_bodies=40,
    )
    incomplete = library_coverage_incomplete_tickers(tmp_path)
    assert incomplete["ERIC-B.ST"] == "zero_body"
    assert "AAPL" not in incomplete


def test_rememo_reason_requires_body_lag_not_thin_alone():
    assert rememo_reason(grade="thin", memo_bodies=0, disk_bodies=0) is None
    assert rememo_reason(grade="thin", memo_bodies=0, disk_bodies=12) == (
        "stale_thin_grade_body_lag_12"
    )
    assert rememo_reason(grade="strong", memo_bodies=5, disk_bodies=40).startswith(
        "strong_grade_large_body_lag_"
    )
    assert rememo_reason(grade="strong", memo_bodies=5, disk_bodies=8, has_verdict=False) == (
        "missing_verdict"
    )


def test_resolve_merges_committed_when_index_is_narrow(tmp_path: Path):
    committed = tmp_path / "research"
    _write_memo(committed, "JSG.L", verdict="accumulate", grade="strong", memo_bodies=61)
    output = tmp_path / "output"
    docs = resolve_research_documents(
        output_dir=output,
        bundle={"research": [{"ticker": "MEGP.L", "research_verdict": "accumulate"}]},
        committed_dir=committed,
    )
    by_ticker = {doc.ticker: doc for doc in docs}
    assert by_ticker["JSG.L"].research_verdict == "accumulate"
    assert by_ticker["MEGP.L"].research_verdict == "accumulate"


def test_refresh_dashboard_infers_sibling_committed_store(tmp_path: Path):
    committed = tmp_path / "research"
    _write_memo(committed, "JSG.L", verdict="accumulate", grade="strong", memo_bodies=61)
    bundle_path = tmp_path / "latest.json"
    write_json(
        bundle_path,
        {
            "reports": [
                {
                    "ticker": "JSG.L",
                    "name": "Johnson",
                    "signal": "strong_buy",
                    "models_passed": 10,
                    "model_count": 20,
                    "composite_score": 0.8,
                    "sector_composite_score": 0.7,
                    "families_passed": 4,
                    "data_quality_score": 1.0,
                    "metrics_present": 20,
                    "metrics_total": 20,
                    "weeks_at_signal": 1,
                    "signal_trend": "new",
                    "conviction_score": 0.8,
                    "stability_label": "new",
                    "timing_signal": "neutral",
                    "timing_score": 0.0,
                    "action_note": "",
                    "summary": "Screen only",
                    "passed_models": [],
                    "key_metrics": {},
                }
            ],
            "research": [],
        },
        compact=True,
    )

    count = refresh_dashboard_bundle(bundle_path, output_dir=tmp_path / "output")
    assert count >= 1
    report = json.loads(bundle_path.read_text(encoding="utf-8"))["reports"][0]
    assert report["research_verdict"] == "accumulate"
    assert report["adjusted_signal"] == "strong_buy"


def test_library_rememo_eligible_uses_canonical_filings_not_home_memo(tmp_path: Path):
    root = tmp_path / "library"
    home = root / "markets" / "omxs30" / "screen" / "research"
    canonical = root / "markets" / "euro_depth" / "screen" / "research"
    _write_memo(home, "ERIC-B.ST", verdict="accumulate", grade="thin", memo_bodies=0, disk_bodies=0)
    (canonical / "ERIC-B.ST" / "sources" / "filings").mkdir(parents=True)
    write_json(
        canonical / "ERIC-B.ST" / "sources" / "filings" / "filings_index.json",
        {"summary": {"with_body": 18, "total": 20}},
        compact=True,
    )

    eligible = library_rememo_eligible_tickers(
        root,
        tickers=["ERIC-B.ST", "FRESH.ST"],
        market_id="euro_depth",
        body_lag_threshold=10,
    )
    assert eligible["ERIC-B.ST"].startswith("stale_thin_grade_body_lag_")
    assert "FRESH.ST" not in eligible
