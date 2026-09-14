"""Market-agnostic research store resolution and rememo eligibility."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.research.document import ResearchDocument
from value_investor.research.market_store import (
    library_rememo_eligible_tickers,
    rememo_reason,
    resolve_library_rememo_target,
    resolve_research_documents,
    seed_home_filings_from_canonical,
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


def test_rememo_reason_requires_body_lag_not_thin_alone():
    assert rememo_reason(grade="thin", memo_bodies=0, disk_bodies=0) is None
    assert rememo_reason(grade="thin", memo_bodies=0, disk_bodies=12) == (
        "stale_thin_grade_zero_body_catchup_12"
    )
    assert rememo_reason(grade="strong", memo_bodies=5, disk_bodies=40).startswith(
        "strong_grade_large_body_lag_"
    )
    assert rememo_reason(grade="strong", memo_bodies=5, disk_bodies=8, has_verdict=False) == (
        "missing_verdict"
    )


def test_rememo_reason_zero_body_catchup_before_full_lag_threshold():
    """Ingest that lands a few bodies after a 0-body first pass must rememo.

    The default lag threshold (10) must not leave adequate/thin shells marked
    fresh while disk already has filings — that is the learning-path gap behind
    thin_memo_counted_as_coverage with rememo_eligible_count 0.
    """
    assert rememo_reason(
        grade="adequate", memo_bodies=0, disk_bodies=4, body_lag_threshold=10
    ) == "stale_adequate_grade_zero_body_catchup_4"
    assert rememo_reason(
        grade="thin", memo_bodies=0, disk_bodies=1, body_lag_threshold=10
    ) == "stale_thin_grade_zero_body_catchup_1"
    # Non-zero memo still waits for the full threshold (no catchup churn).
    assert (
        rememo_reason(
            grade="adequate", memo_bodies=2, disk_bodies=6, body_lag_threshold=10
        )
        is None
    )
    assert rememo_reason(
        grade="adequate", memo_bodies=2, disk_bodies=12, body_lag_threshold=10
    ) == "stale_adequate_grade_body_lag_10"


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
    assert eligible["ERIC-B.ST"] == "stale_thin_grade_zero_body_catchup_18"
    assert "FRESH.ST" not in eligible


def test_library_rememo_eligible_zero_body_catchup_below_lag_threshold(tmp_path: Path):
    root = tmp_path / "library"
    research = root / "markets" / "euro_depth" / "screen" / "research"
    _write_memo(research, "AED.BR", verdict="accumulate", grade="adequate", memo_bodies=0, disk_bodies=0)
    write_json(
        research / "AED.BR" / "sources" / "filings" / "filings_index.json",
        {"summary": {"with_body": 4, "total": 4}},
        compact=True,
    )
    _write_memo(research, "AGS.BR", verdict="accumulate", grade="adequate", memo_bodies=0, disk_bodies=0)

    eligible = library_rememo_eligible_tickers(
        root,
        tickers=["AED.BR", "AGS.BR"],
        market_id="euro_depth",
        body_lag_threshold=10,
    )
    assert eligible["AED.BR"] == "stale_adequate_grade_zero_body_catchup_4"
    assert "AGS.BR" not in eligible


def test_seed_home_filings_from_canonical_copies_when_focus_ahead(tmp_path: Path):
    root = tmp_path / "library"
    home = root / "markets" / "euro_stoxx50" / "screen" / "research"
    canonical = root / "markets" / "euro_depth" / "screen" / "research"
    _write_memo(
        home, "TTE.PA", verdict="accumulate", grade="strong", memo_bodies=57, disk_bodies=57
    )
    (canonical / "TTE.PA" / "sources" / "filings").mkdir(parents=True)
    write_json(
        canonical / "TTE.PA" / "sources" / "filings" / "filings_index.json",
        {"summary": {"with_body": 91, "total": 95}},
        compact=True,
    )
    (canonical / "TTE.PA" / "sources" / "filings" / "extra.txt").write_text(
        "body", encoding="utf-8"
    )

    seeded = seed_home_filings_from_canonical(root, "TTE.PA", market_id="euro_depth")
    assert seeded["action"] == "seeded"
    assert seeded["canonical_bodies"] == 91
    assert seeded["home_bodies_before"] == 57
    assert seeded["home_bodies_after"] == 91
    assert (home / "TTE.PA" / "sources" / "filings" / "extra.txt").read_text(
        encoding="utf-8"
    ) == "body"

    again = seed_home_filings_from_canonical(root, "TTE.PA", market_id="euro_depth")
    assert again["action"] == "home_ahead_or_same_store"


def test_resolve_library_rememo_target_rewrites_home(tmp_path: Path):
    root = tmp_path / "library"
    home = root / "markets" / "euro_stoxx50" / "screen" / "research"
    canonical = root / "markets" / "euro_depth" / "screen" / "research"
    _write_memo(
        home, "TTE.PA", verdict="accumulate", grade="strong", memo_bodies=57, disk_bodies=57
    )
    (canonical / "TTE.PA" / "sources" / "filings").mkdir(parents=True)
    write_json(
        canonical / "TTE.PA" / "sources" / "filings" / "filings_index.json",
        {"summary": {"with_body": 91, "total": 95}},
        compact=True,
    )

    first_time = resolve_library_rememo_target(
        root,
        "NEW.PA",
        selected_market="euro_depth",
        focus_market="euro_depth",
        rememo_reasons={},
    )
    assert first_time["market"] == "euro_depth"
    assert first_time["force_initial"] is False

    rememo = resolve_library_rememo_target(
        root,
        "TTE.PA",
        selected_market="euro_depth",
        focus_market="euro_depth",
        rememo_reasons={"TTE.PA": "strong_grade_large_body_lag_34"},
    )
    assert rememo["market"] == "euro_stoxx50"
    assert rememo["force_initial"] is True
    assert rememo["seed"]["action"] == "seeded"


def test_resolve_library_rememo_target_seeds_selected_not_focus(tmp_path: Path):
    root = tmp_path / "library"
    home = root / "markets" / "nasdaq100" / "screen" / "research"
    canonical = root / "markets" / "sp500" / "screen" / "research"
    _write_memo(home, "AAPL", verdict="accumulate", grade="thin", memo_bodies=0, disk_bodies=0)
    (canonical / "AAPL" / "sources" / "filings").mkdir(parents=True)
    write_json(
        canonical / "AAPL" / "sources" / "filings" / "filings_index.json",
        {"summary": {"with_body": 22, "total": 24}},
        compact=True,
    )
    (canonical / "AAPL" / "sources" / "filings" / "10k.txt").write_text("body", encoding="utf-8")

    rememo = resolve_library_rememo_target(
        root,
        "AAPL",
        selected_market="sp500",
        focus_market="euro_depth",
        rememo_reasons={"AAPL": "stale_thin_grade_body_lag_22"},
    )
    assert rememo["market"] == "nasdaq100"
    assert rememo["force_initial"] is True
    assert rememo["seed"]["action"] == "seeded"
    assert rememo["seed"]["focus_market"] == "sp500"
    assert rememo["seed"]["canonical_bodies"] == 22
