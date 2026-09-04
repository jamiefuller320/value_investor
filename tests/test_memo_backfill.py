"""Tests for buy-tier memo backfill selection and publish merge."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.research.document import ResearchDocument
from value_investor.research.memo_backfill import (
    has_published_memo,
    list_missing_memo_reports,
    publish_memo_backfill_batch,
    run_missing_memo_backfill,
)
from value_investor.summary import CompanyReport


def _report(ticker: str, signal: str = "buy", conviction: float = 0.5) -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=f"{ticker} plc",
        sector="Industrials",
        signal=signal,
        models_passed=5,
        model_count=10,
        composite_score=0.7,
        sector_composite_score=0.65,
        families_passed=3,
        passed_families="cheapness,quality",
        data_quality_score=0.9,
        metrics_present=18,
        metrics_total=20,
        weeks_at_signal=2,
        signal_trend="stable",
        conviction_score=conviction,
        stability_label="stable",
        timing_signal="neutral",
        timing_score=0.5,
        rsi_14=45.0,
        price_vs_sma200_pct=-0.05,
        action_note="",
        trade_plan=None,
        summary="summary",
        passed_models=["pe"],
        key_metrics={},
    )


def test_has_published_memo_checks_docs_markdown(tmp_path: Path):
    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    (memo_dir / "ABC.L.md").write_text("# memo", encoding="utf-8")
    assert has_published_memo("ABC.L", memo_dir=memo_dir, committed_dir=tmp_path / "data")


def test_list_missing_memo_reports_prioritizes_strong_buy(tmp_path: Path):
    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    reports = [
        _report("BUY.L", signal="buy", conviction=0.9),
        _report("SB.L", signal="strong_buy", conviction=0.4),
    ]
    missing = list_missing_memo_reports(
        reports,
        memo_dir=memo_dir,
        committed_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
    )
    assert [row.ticker for row in missing] == ["SB.L", "BUY.L"]


def test_publish_memo_backfill_batch_merges_research_index(tmp_path: Path):
    docs = tmp_path / "docs"
    data = docs / "data"
    data.mkdir(parents=True)
    (docs / "research").mkdir()
    latest = data / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "ticker": "NEW.L",
                        "name": "New plc",
                        "sector": "Industrials",
                        "signal": "buy",
                        "models_passed": 5,
                        "model_count": 10,
                        "composite_score": 0.7,
                        "sector_composite_score": 0.65,
                        "families_passed": 3,
                        "passed_families": "cheapness",
                        "data_quality_score": 0.9,
                        "metrics_present": 18,
                        "metrics_total": 20,
                        "weeks_at_signal": 1,
                        "signal_trend": "new",
                        "conviction_score": 0.6,
                        "stability_label": "new",
                        "timing_signal": "neutral",
                        "timing_score": 0.5,
                        "rsi_14": 40.0,
                        "price_vs_sma200_pct": 0.0,
                        "action_note": "",
                        "trade_plan": None,
                        "summary": "summary",
                        "passed_models": [],
                        "key_metrics": {},
                    }
                ],
                "research": [{"ticker": "OLD.L", "name": "Old plc"}],
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "output"
    ticker_dir = output / "research" / "NEW.L"
    ticker_dir.mkdir(parents=True)
    doc = ResearchDocument(
        ticker="NEW.L",
        name="New plc",
        signal="buy",
        version=1,
        created_at="2026-08-01T00:00:00+00:00",
        updated_at="2026-08-01T00:00:00+00:00",
        mode="initial",
        executive_summary="Exec",
        research_verdict="accumulate",
        research_risk_level="medium",
        research_confidence=0.7,
        research_rationale="ok",
    )
    (ticker_dir / "research.json").write_text(json.dumps(doc.to_dict()), encoding="utf-8")
    (ticker_dir / "research.md").write_text("# NEW.L memo", encoding="utf-8")

    result = publish_memo_backfill_batch(output, dest_dir=docs, latest_path=latest)
    assert result["new_memo_entries"] == 1
    raw = latest.read_text(encoding="utf-8")
    assert "\n" not in raw.strip()  # compact, same as ftse-publish
    payload = json.loads(raw)
    tickers = {row["ticker"] for row in payload["research"]}
    assert tickers == {"OLD.L", "NEW.L"}
    assert payload["reports"][0]["research_verdict"] == "accumulate"
    assert (docs / "research" / "NEW.L.md").exists()


@patch("value_investor.research.memo_backfill._process_ticker")
def test_run_missing_memo_backfill_dry_run(mock_process: object, tmp_path: Path):
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "reports": [
                    _report("ONE.L").to_dict(),
                    _report("TWO.L").to_dict(),
                ]
            }
        ),
        encoding="utf-8",
    )
    summary = run_missing_memo_backfill(
        latest_path=latest,
        output_dir=tmp_path / "output",
        memo_dir=tmp_path / "memos",
        committed_dir=tmp_path / "committed",
        state_path=tmp_path / "state.json",
        batch_size=1,
        api_key="key",
        dry_run=True,
        dest_dir=tmp_path / "docs",
    )
    assert summary.selected == ["ONE.L"]
    assert len(summary.remaining) == 1
    mock_process.assert_not_called()


def test_list_legacy_rememo_reports_prioritizes_strong_buy(tmp_path: Path):
    from value_investor.research.memo_backfill import list_legacy_rememo_reports

    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    (memo_dir / "SB.L.md").write_text("# memo", encoding="utf-8")
    (memo_dir / "LEG.L.md").write_text("# memo", encoding="utf-8")
    reports = [
        _report("LEG.L", signal="buy", conviction=0.9),
        _report("SB.L", signal="strong_buy", conviction=0.4),
    ]
    legacy = list_legacy_rememo_reports(
        reports,
        memo_dir=memo_dir,
        committed_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
    )
    assert [row.ticker for row in legacy] == ["SB.L", "LEG.L"]
