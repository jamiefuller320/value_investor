"""Tests for GitHub Pages dashboard publishing."""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from value_investor.publish import (
    annotate_reports_with_research_source_prompts,
    build_dashboard_bundle,
    publish_dashboard,
    research_source_prompt_lines_for_ticker,
)
from value_investor.research.ingest import (
    extract_govuk_article_body,
    format_cma_ofcom_merger_research_prompt,
    parse_cma_cases_atom,
    resolve_cma_ofcom_merger_deal,
)


def _write_sample_output(output_dir: Path) -> None:
    signals = pd.DataFrame(
        [
            {
                "ticker": "AAA.L",
                "name": "Alpha PLC",
                "sector": "Financials",
                "signal": "strong_buy",
                "models_passed": 10,
                "model_count": 18,
                "composite_score": 0.8,
                "sector_composite_score": 0.82,
                "families_passed": 3,
                "passed_families": "cheapness,quality",
                "data_quality_score": 0.85,
                "metrics_present": 18,
                "metrics_total": 20,
                "weeks_at_signal": 2,
                "signal_trend": "stable",
                "conviction_score": 0.7,
                "stability_label": "building",
                "timing_signal": "accumulate",
                "timing_score": 0.75,
                "rsi_14": 34.0,
                "price_vs_sma200_pct": -0.05,
                "timing_reasons": "['RSI below neutral (34)']",
                "action_note": "Strong Buy — favourable entry timing",
                "run_at": "2026-07-08T07:00:00+00:00",
            },
            {
                "ticker": "BBB.L",
                "name": "Beta PLC",
                "sector": "Energy",
                "signal": "hold",
                "models_passed": 5,
                "model_count": 18,
                "composite_score": 0.5,
                "sector_composite_score": 0.48,
                "families_passed": 2,
                "passed_families": "cheapness",
                "data_quality_score": 0.7,
                "metrics_present": 14,
                "metrics_total": 20,
                "weeks_at_signal": 1,
                "signal_trend": "new",
                "conviction_score": 0.4,
                "stability_label": "new",
                "timing_signal": "neutral",
                "timing_score": 0.5,
                "rsi_14": 50.0,
                "price_vs_sma200_pct": 0.02,
                "timing_reasons": "[]",
                "action_note": "Hold — neutral timing",
                "run_at": "2026-07-08T07:00:00+00:00",
            },
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "AAA.L",
                "model_name": "Graham Defensive",
                "passed": True,
                "score": 1.0,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    signals.to_csv(output_dir / "latest_signals.csv", index=False)
    model_results.to_csv(output_dir / "latest_model_results.csv", index=False)
    (output_dir / "run_diff.json").write_text(
        json.dumps(
            {
                "new_strong_buys": ["Alpha (AAA.L)"],
                "persistent_strong_buys": [],
                "lost_strong_buys": [],
                "upgrades": [],
                "downgrades": [],
                "unchanged_top_signals": 1,
            }
        ),
        encoding="utf-8",
    )


def test_build_dashboard_bundle_from_signals(tmp_path: Path):
    _write_sample_output(tmp_path)
    paper = tmp_path / "paper_automation"
    paper.mkdir(parents=True)
    (paper / "last_run.json").write_text(
        json.dumps({"acted": True, "note": "test fixture"}),
        encoding="utf-8",
    )
    (paper / "knob_calibration_priors.json").write_text(
        json.dumps(
            {
                "scope": "knob_calibration_multi",
                "calibrated_at": "2026-08-20T12:00:00+00:00",
                "tracks": {
                    "ai_judgment": {
                        "ranking_mode": "full_period_retrospective",
                        "readiness": {
                            "acted_entries": 8,
                            "ready_for_shadow_bootstrap": True,
                            "ready_for_priors": True,
                            "score_gap_vs_runner_up": 0.01,
                        },
                        "bootstrap_priors": [
                            {
                                "rank": 1,
                                "shadow_track_id": "ai_judgment_calibrated",
                                "knobs": {"max_positions": 4, "min_conviction": 0.0},
                                "full_period_score": 0.1,
                                "confidence": "low",
                                "winner_loser": {
                                    "catch_rate": 0.4,
                                    "exclude_rate": 0.6,
                                    "top_buy_tier_caught": ["AAA.L"],
                                    "bottom_buy_tier_avoided": ["DDD.L"],
                                },
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (paper / "calibration_shadow_endurance.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-08-20T12:05:00+00:00",
                "shadows": [
                    {
                        "rank": 1,
                        "shadow_track_id": "ai_judgment_calibrated",
                        "status": "observing",
                        "knobs": {"max_positions": 4},
                        "metrics": {"excess_after_costs": None, "equity_marks": 1},
                    }
                ],
                "survivors": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "experiment_assessment.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "summary": {"total": 1, "recommend": 0},
                "experiments": [
                    {
                        "experiment_id": "ai_judgment_calibrated",
                        "kind": "calibration_shadow",
                        "status": "observing",
                    }
                ],
                "recommendations": [],
            }
        ),
        encoding="utf-8",
    )
    bundle = build_dashboard_bundle(tmp_path)
    assert bundle["meta"]["company_count"] == 2
    assert bundle["meta"]["strong_buy_count"] == 1
    assert bundle["reports"][0]["ticker"] == "AAA.L"
    assert bundle["run_diff"]["new_strong_buys"] == ["Alpha (AAA.L)"]
    assert bundle["meta"].get("broker_overlay") == "trading212"
    assert bundle["meta"].get("t212_overlay") is True
    assert bundle["meta"].get("ii_overlay") is True
    assert "unavailable_watch" in bundle
    # AAA.L maps to UK / LSE on the venue allowlist (or catalogue when present)
    assert bundle["reports"][0].get("tradable_on_t212") is True
    assert bundle["reports"][0].get("tradable_on_ii") is True
    assert bundle["reports"][0].get("ii_deal_channel") == "online"
    assert bundle.get("human_tasks_checklist", {}).get("sections")
    assert bundle["knob_calibration_priors"]["tracks"]["ai_judgment"]["ranking_mode"] == (
        "full_period_retrospective"
    )
    assert bundle["calibration_shadow_endurance"]["shadows"][0]["status"] == "observing"
    assert bundle["experiment_assessment"]["summary"]["total"] == 1
    assert "system_gaps" in bundle
    assert bundle.get("lifecycle_board", {}).get("schema_version") == 1
    assert any(
        row.get("market_id") == "ftse350" for row in bundle["lifecycle_board"].get("markets") or []
    )


def test_publish_dashboard_includes_sunday_review(tmp_path: Path):
    output_dir = tmp_path / "output"
    dest_dir = tmp_path / "docs"
    data_dir = dest_dir / "data"
    paper_root = data_dir / "paper_automation"
    paper_root.mkdir(parents=True)
    archive_dir = data_dir / "archive"
    archive_dir.mkdir(parents=True)

    _write_sample_output(output_dir)
    (paper_root / "learning_tracks_review.json").write_text(
        json.dumps(
            {
                "primary_learning_track": "ai_judgment",
                "reviews": {
                    "ai_judgment": {
                        "track_id": "ai_judgment",
                        "track_label": "AI judgment",
                        "metrics": {"excess_after_costs": -0.1, "equity_marks": 5},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "exclusion_universe_archive.json").write_text(
        json.dumps({"recommended_step": {"step_id": "u4"}, "ladder_results": []}),
        encoding="utf-8",
    )
    (data_dir / "experiment_assessment.json").write_text(
        json.dumps({"schema_version": 2, "summary": {"total": 0}, "experiments": []}),
        encoding="utf-8",
    )

    path = publish_dashboard(output_dir=output_dir, dest_dir=dest_dir, include_research=False)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("sunday_review", {}).get("schema_version") == 1
    assert "current" in data["sunday_review"]
    assert (data_dir / "review_history.json").exists()


def test_publish_dashboard_writes_latest_json(tmp_path: Path):
    output_dir = tmp_path / "output"
    dest_dir = tmp_path / "docs"
    _write_sample_output(output_dir)

    path = publish_dashboard(output_dir=output_dir, dest_dir=dest_dir, include_research=False)
    assert path.exists()
    raw = path.read_text(encoding="utf-8")
    assert "\n  " not in raw  # compact JSON
    data = json.loads(raw)
    assert data["meta"]["company_count"] == 2
    assert data["chart_outcome_review"]["observe_only"] is True
    assert (dest_dir / "data" / "chart_outcome_review.json").exists()
    assert (dest_dir / "data" / "archive" / "2026-07-08.json").exists()


def test_publish_research_index_is_summarized(tmp_path: Path):
    output_dir = tmp_path / "output"
    dest_dir = tmp_path / "docs"
    _write_sample_output(output_dir)

    research_dir = output_dir / "research" / "AAA.L"
    research_dir.mkdir(parents=True)
    long_summary = "Alpha thesis. " + ("Detail sentence. " * 80)
    (research_dir / "research.json").write_text(
        json.dumps(
            {
                "ticker": "AAA.L",
                "name": "Alpha PLC",
                "version": 1,
                "updated_at": "2026-07-08T07:00:00+00:00",
                "executive_summary": long_summary,
                "research_verdict": "accumulate",
            }
        ),
        encoding="utf-8",
    )
    (research_dir / "research.md").write_text("# Alpha\n\nFull memo.\n", encoding="utf-8")

    path = publish_dashboard(output_dir=output_dir, dest_dir=dest_dir, include_research=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["research"]) == 1
    assert len(data["research"][0]["executive_summary"]) < len(long_summary)
    assert data["research"][0]["executive_summary"].endswith("…")
    assert (dest_dir / "research" / "AAA.L.md").exists()


def test_publish_merges_committed_research_and_overlays_reports(tmp_path: Path):
    output_dir = tmp_path / "output"
    dest_dir = tmp_path / "docs"
    _write_sample_output(output_dir)

    committed = dest_dir / "data" / "research" / "BBB.L"
    committed.mkdir(parents=True)
    (committed / "research.json").write_text(
        json.dumps(
            {
                "ticker": "BBB.L",
                "name": "Beta PLC",
                "version": 1,
                "updated_at": "2026-08-01T00:00:00+00:00",
                "executive_summary": "Committed memo.",
                "research_verdict": "caution",
                "research_risk_level": "medium",
                "research_confidence": 0.4,
            }
        ),
        encoding="utf-8",
    )
    (committed / "research.md").write_text("# Beta\n", encoding="utf-8")

    path = publish_dashboard(output_dir=output_dir, dest_dir=dest_dir, include_research=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    tickers = {row["ticker"] for row in data["research"]}
    assert "BBB.L" in tickers
    reports = {row["ticker"]: row for row in data["reports"]}
    assert reports["BBB.L"]["research_verdict"] == "caution"


def test_parse_cma_cases_atom_selects_sky_itv_slug():
    """eng-20260920-04: CMA atom parser picks the Sky/ITV merger inquiry entry."""
    atom = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Other case</title>
    <link rel="alternate" href="https://www.gov.uk/cma-cases/other-case"/>
    <updated>2026-01-01T00:00:00+00:00</updated>
  </entry>
  <entry>
    <title>Sky / ITV merger inquiry</title>
    <link rel="alternate" href="https://www.gov.uk/cma-cases/sky-slash-itv-merger-inquiry"/>
    <updated>2026-07-23T07:00:33+01:00</updated>
  </entry>
</feed>"""
    rows = parse_cma_cases_atom(atom, case_slug="sky-slash-itv-merger-inquiry")
    assert len(rows) == 1
    assert rows[0]["slug"] == "sky-slash-itv-merger-inquiry"
    assert "Sky / ITV" in rows[0]["title"]


def test_extract_govuk_article_body_from_json_ld():
    html = (
        '<html><head><script type="application/ld+json">'
        '{"articleBody": "Phase 1 invitation to comment closes 6 August 2026."}'
        "</script></head></html>"
    )
    body = extract_govuk_article_body(html)
    assert "Phase 1 invitation" in body
    assert "6 August 2026" in body


def test_format_cma_ofcom_merger_research_prompt_exports_memo_line():
    meta = {
        "status": "ok",
        "deal_label": "Sky / ITV Media & Entertainment merger",
        "cma_case": {"title": "Sky / ITV merger inquiry"},
    }
    prompt = format_cma_ofcom_merger_research_prompt(meta)
    assert prompt
    assert "cma_ofcom_merger.json" in prompt
    assert "Sky / ITV Media & Entertainment merger" in prompt


def test_research_source_prompt_lines_for_itv_when_corpus_present(tmp_path: Path):
    sources = tmp_path / "research" / "ITV.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "cma_ofcom_merger.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "deal_label": "Sky / ITV Media & Entertainment merger",
                "cma_case": {"title": "Sky / ITV merger inquiry"},
            }
        ),
        encoding="utf-8",
    )
    lines = research_source_prompt_lines_for_ticker("ITV.L", output_dir=tmp_path)
    assert len(lines) == 1
    assert "cma_ofcom_merger.json" in lines[0]


def test_annotate_reports_adds_research_source_prompts(tmp_path: Path):
    sources = tmp_path / "research" / "ITV.L" / "sources"
    sources.mkdir(parents=True)
    (sources / "cma_ofcom_merger.json").write_text(
        json.dumps({"status": "ok", "deal_label": "Sky / ITV Media & Entertainment merger"}),
        encoding="utf-8",
    )
    reports = [{"ticker": "ITV.L", "name": "ITV plc", "signal": "strong_buy"}]
    annotated = annotate_reports_with_research_source_prompts(reports, output_dir=tmp_path)
    assert annotated[0].get("research_source_prompts")
    assert resolve_cma_ofcom_merger_deal("ITV.L") is not None


@patch("value_investor.research.ingest.fetch_cma_ofcom_merger_news", return_value=[])
@patch("value_investor.research.ingest.fetch_cma_merger_case_document")
@patch("value_investor.research.ingest._http_get_bytes")
def test_ingest_cma_ofcom_merger_writes_case_file(
    mock_http,
    mock_case,
    _mock_news,
    tmp_path: Path,
):
    from value_investor.research.ingest import ingest_cma_ofcom_merger_sources

    mock_http.return_value = (
        b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    )
    mock_case.return_value = {
        "source": "cma_gov_uk",
        "title": "Sky / ITV merger inquiry",
        "url": "https://www.gov.uk/cma-cases/sky-slash-itv-merger-inquiry",
        "slug": "sky-slash-itv-merger-inquiry",
        "body": "Phase 1 invitation to comment closes 6 August 2026. " * 5,
    }
    meta = ingest_cma_ofcom_merger_sources(
        ticker="ITV.L",
        company_name="ITV plc",
        sources_dir=tmp_path,
        market="ftse350",
    )
    assert meta["status"] == "ok"
    assert (tmp_path / "cma_ofcom_merger.json").is_file()
    body_files = list((tmp_path / "cma_ofcom_merger" / "bodies").glob("*.txt"))
    assert body_files
    assert "Phase 1" in body_files[0].read_text(encoding="utf-8")


def test_publish_prunes_old_dashboard_archives(tmp_path: Path):
    output_dir = tmp_path / "output"
    dest_dir = tmp_path / "docs"
    _write_sample_output(output_dir)
    archive = dest_dir / "data" / "archive"
    archive.mkdir(parents=True)
    for day in ("2026-01-01", "2026-02-01", "2026-03-01"):
        (archive / f"{day}.json").write_text("{}", encoding="utf-8")

    publish_dashboard(
        output_dir=output_dir, dest_dir=dest_dir, include_research=False, archive_keep=2
    )
    remaining = sorted(p.name for p in archive.iterdir())
    assert remaining == ["2026-03-01.json", "2026-07-08.json"]
