"""Tests for research runner orchestration."""

from unittest.mock import patch

import pandas as pd

from value_investor.research.document import ResearchDocument
from value_investor.research.runner import (
    eligible_alumni_research_targets,
    eligible_research_targets,
    eligible_strong_buys,
    run_research_for_strong_buys,
    select_research_targets,
)
from value_investor.research.store import ResearchStore
from value_investor.summary import build_company_reports


def _report(
    *,
    ticker: str = "AAA.L",
    name: str = "Alpha PLC",
    signal: str = "strong_buy",
    data_quality_score: float = 0.85,
    conviction_score: float = 0.72,
    composite_score: float = 0.8,
):
    signals = pd.DataFrame([
        {
            "ticker": ticker,
            "name": name,
            "sector": "Financials",
            "signal": signal,
            "models_passed": 10,
            "model_count": 18,
            "composite_score": composite_score,
            "sector_composite_score": 0.82,
            "families_passed": 3,
            "passed_families": "cheapness,quality,dividend",
            "data_quality_score": data_quality_score,
            "metrics_present": 18,
            "metrics_total": 20,
            "weeks_at_signal": 3,
            "signal_trend": "stable",
            "conviction_score": conviction_score,
            "stability_label": "building",
            "timing_signal": "accumulate",
            "timing_score": 0.75,
            "rsi_14": 34.0,
            "price_vs_sma200_pct": -0.08,
            "timing_reasons": ["RSI below neutral (34)"],
            "action_note": "Strong Buy — favourable entry timing",
        }
    ])
    model_results = pd.DataFrame([
        {
            "ticker": ticker,
            "model_name": "Graham Defensive",
            "passed": True,
            "score": 1.0,
            "reasons": "[]",
            "failed_criteria": "[]",
        }
    ])
    return build_company_reports(signals, model_results)[0]


def _strong_buy_report():
    return _report()


def test_eligible_strong_buys_filters_low_quality():
    report = _strong_buy_report()
    report_low_quality = _strong_buy_report()
    report_low_quality.data_quality_score = 0.4
    eligible = eligible_strong_buys([report, report_low_quality])
    assert len(eligible) == 1
    assert eligible[0].ticker == "AAA.L"


def test_eligible_research_targets_includes_buys_after_strong_buys():
    strong = _report(ticker="AAA.L", name="Alpha", signal="strong_buy", conviction_score=0.9)
    buy_high = _report(
        ticker="BBB.L",
        name="Beta",
        signal="buy",
        data_quality_score=0.7,
        conviction_score=0.8,
        composite_score=0.7,
    )
    buy_low = _report(
        ticker="CCC.L",
        name="Gamma",
        signal="buy",
        data_quality_score=0.7,
        conviction_score=0.5,
        composite_score=0.6,
    )
    hold = _report(ticker="DDD.L", name="Delta", signal="hold", data_quality_score=0.9)

    eligible = eligible_research_targets(
        [buy_low, hold, buy_high, strong],
        weekly_cap=3,
    )

    assert [r.ticker for r in eligible] == ["AAA.L", "BBB.L", "CCC.L"]
    assert all(r.signal in ("strong_buy", "buy") for r in eligible)


def test_eligible_research_targets_prioritises_all_strong_buys_within_cap():
    strong_a = _report(ticker="AAA.L", conviction_score=0.6, composite_score=0.5)
    strong_b = _report(ticker="BBB.L", name="Beta", conviction_score=0.9, composite_score=0.8)
    buy = _report(
        ticker="CCC.L",
        name="Gamma",
        signal="buy",
        conviction_score=0.99,
        composite_score=0.99,
    )

    eligible = eligible_research_targets([buy, strong_a, strong_b], weekly_cap=2)

    assert [r.ticker for r in eligible] == ["BBB.L", "AAA.L"]
    assert all(r.signal == "strong_buy" for r in eligible)


def test_eligible_research_targets_respects_zero_cap():
    assert eligible_research_targets([_strong_buy_report()], weekly_cap=0) == []


def test_eligible_research_targets_filters_low_quality_buys():
    buy_ok = _report(ticker="BBB.L", name="Beta", signal="buy", data_quality_score=0.6)
    buy_low = _report(ticker="CCC.L", name="Gamma", signal="buy", data_quality_score=0.4)

    eligible = eligible_research_targets([buy_ok, buy_low], weekly_cap=8)
    assert [r.ticker for r in eligible] == ["BBB.L"]


@patch("value_investor.research.runner.run_initial_research_agent")
@patch("value_investor.research.runner.ingest_research_sources")
def test_run_research_for_strong_buys_creates_initial_memo(mock_ingest, mock_initial, tmp_path):
    mock_ingest.return_value = {
        "financials_path": "f.json",
        "snapshot_path": "s.json",
        "news_manifest_path": "n.json",
        "news_batch_path": "b.json",
        "financial_years": 5,
        "news_total": 12,
        "news_new": 12,
    }
    mock_initial.return_value = (
        ResearchDocument(
            ticker="AAA.L",
            name="Alpha PLC",
            signal="strong_buy",
            version=1,
            created_at="2026-07-08T00:00:00+00:00",
            updated_at="2026-07-08T00:00:00+00:00",
            mode="initial",
            executive_summary="Deep memo.",
            agent_id="agent-1",
        ),
        "agent-1",
    )

    summary = run_research_for_strong_buys(
        reports=[_strong_buy_report()],
        output_dir=tmp_path,
        api_key="test-key",
    )

    assert summary.created == 1
    assert summary.documents[0].executive_summary == "Deep memo."
    assert (tmp_path / "research" / "AAA.L" / "research.md").exists()
    assert mock_ingest.call_args.kwargs["deepen_history"] is True


@patch("value_investor.research.runner.run_initial_research_agent")
@patch("value_investor.research.runner.ingest_research_sources")
def test_run_research_includes_capped_buys(mock_ingest, mock_initial, tmp_path):
    mock_ingest.return_value = {
        "financials_path": "f.json",
        "snapshot_path": "s.json",
        "news_manifest_path": "n.json",
        "news_batch_path": "b.json",
        "financial_years": 5,
        "news_total": 4,
        "news_new": 4,
    }

    def _fake_initial(*, report, **_kwargs):
        return (
            ResearchDocument(
                ticker=report.ticker,
                name=report.name,
                signal=report.signal,
                version=1,
                created_at="2026-07-08T00:00:00+00:00",
                updated_at="2026-07-08T00:00:00+00:00",
                mode="initial",
                executive_summary=f"Memo for {report.ticker}",
                agent_id="agent-1",
            ),
            "agent-1",
        )

    mock_initial.side_effect = _fake_initial

    summary = run_research_for_strong_buys(
        reports=[
            _report(ticker="AAA.L", signal="strong_buy"),
            _report(ticker="BBB.L", name="Beta", signal="buy", data_quality_score=0.7),
            _report(ticker="CCC.L", name="Gamma", signal="hold"),
        ],
        output_dir=tmp_path,
        api_key="test-key",
        weekly_cap=8,
    )

    tickers = {doc.ticker for doc in summary.documents}
    assert tickers == {"AAA.L", "BBB.L"}
    assert summary.created == 2


def test_eligible_alumni_prefers_oldest_and_skips_active_buys(tmp_path):
    store = ResearchStore(tmp_path)
    older = ResearchDocument(
        ticker="OLD.L",
        name="Old Co",
        signal="buy",
        version=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        mode="initial",
        executive_summary="Old memo",
    )
    newer = ResearchDocument(
        ticker="NEW.L",
        name="New Co",
        signal="buy",
        version=1,
        created_at="2026-06-01T00:00:00+00:00",
        updated_at="2026-06-01T00:00:00+00:00",
        mode="initial",
        executive_summary="Newer memo",
    )
    still_buy = ResearchDocument(
        ticker="BUY.L",
        name="Buy Co",
        signal="buy",
        version=1,
        created_at="2026-02-01T00:00:00+00:00",
        updated_at="2026-02-01T00:00:00+00:00",
        mode="initial",
        executive_summary="Still buy",
    )
    store.save(older)
    store.save(newer)
    store.save(still_buy)

    reports = [
        _report(ticker="OLD.L", name="Old Co", signal="hold"),
        _report(ticker="NEW.L", name="New Co", signal="avoid"),
        _report(ticker="BUY.L", name="Buy Co", signal="buy", data_quality_score=0.8),
        _report(ticker="FRESH.L", name="Fresh", signal="strong_buy"),
    ]
    alumni = eligible_alumni_research_targets(reports, store, alumni_cap=8)
    assert [r.ticker for r in alumni] == ["OLD.L", "NEW.L"]

    active, alumni_sel = select_research_targets(
        reports, store, weekly_cap=8, continue_alumni=True, alumni_cap=8
    )
    assert [r.ticker for r in active] == ["FRESH.L", "BUY.L"]
    assert [r.ticker for r in alumni_sel] == ["OLD.L", "NEW.L"]


@patch("value_investor.research.runner.run_weekly_research_update_agent")
@patch("value_investor.research.runner.run_initial_research_agent")
@patch("value_investor.research.runner.ingest_research_sources")
def test_run_research_updates_alumni(mock_ingest, mock_initial, mock_weekly, tmp_path):
    mock_ingest.return_value = {
        "financials_path": "f.json",
        "snapshot_path": "s.json",
        "news_manifest_path": "n.json",
        "news_batch_path": str(tmp_path / "b.json"),
        "financial_years": 5,
        "news_total": 2,
        "news_new": 1,
        "filings_summary": {},
    }
    (tmp_path / "b.json").write_text("[]", encoding="utf-8")

    store = ResearchStore(tmp_path)
    store.save(
        ResearchDocument(
            ticker="OLD.L",
            name="Old Co",
            signal="buy",
            version=1,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            mode="initial",
            executive_summary="Prior memo",
            agent_id="agent-old",
        )
    )

    mock_initial.return_value = (
        ResearchDocument(
            ticker="AAA.L",
            name="Alpha PLC",
            signal="strong_buy",
            version=1,
            created_at="2026-07-08T00:00:00+00:00",
            updated_at="2026-07-08T00:00:00+00:00",
            mode="initial",
            executive_summary="New memo",
            agent_id="agent-1",
        ),
        "agent-1",
    )
    mock_weekly.return_value = ResearchDocument(
        ticker="OLD.L",
        name="Old Co",
        signal="hold",
        version=2,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
        mode="weekly_update",
        executive_summary="Prior memo",
        weekly_updates=[{"date": "2026-07-16", "summary": "Still monitoring."}],
        agent_id="agent-old",
    )

    summary = run_research_for_strong_buys(
        reports=[
            _report(ticker="AAA.L", signal="strong_buy"),
            _report(ticker="OLD.L", name="Old Co", signal="hold"),
        ],
        output_dir=tmp_path,
        api_key="test-key",
        weekly_cap=8,
        continue_alumni=True,
        alumni_cap=8,
    )

    assert summary.active_count == 1
    assert summary.alumni_count == 1
    assert summary.created == 1
    assert summary.alumni_updated == 1
    assert {doc.ticker for doc in summary.documents} == {"AAA.L", "OLD.L"}
    mock_weekly.assert_called_once()
    assert mock_weekly.call_args.kwargs["screen_signal"] == "hold"
