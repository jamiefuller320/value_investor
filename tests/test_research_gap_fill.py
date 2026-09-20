"""Tests for deep-analysis red-flag extraction and gap-fill parsing."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.deep_analysis import DeepAnalysis, _parse_deep_analysis
from value_investor.research.agent import (
    _augment_research_worker_prompt,
    _gap_fill_followup_prompt,
    _gap_fill_prompt,
    filing_extraction_discipline,
    gap_fill_ch_refetch_discipline,
    is_actionable_research_model_suggestion,
    news_extraction_discipline,
    research_model_suggestions_discipline,
    screen_filing_reconciliation_discipline,
    worker_task_extraction_rules,
)
from value_investor.research.document import parse_research_sections
from value_investor.research.format import format_gap_fill_text
from value_investor.research.gap_fill import (
    GapFillSummary,
    GapFillTarget,
    _persist_model_suggestions,
    _unresolved_questions,
    ch_refetch_passed,
    ch_three_year_margin_secured_series_present,
    extract_gap_fill_targets,
    filter_questions_for_ticker,
    gap_fill_ch_refetch_prompt_context,
    supplement_deal_structure_questions,
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


def test_parse_deep_analysis_accepts_markdown_and_names_section():
    text = """## EXECUTIVE INTRO
Selective tape.

**TOP PICKS ANALYSIS**
AEP.L looks clean on balance sheet.

## NAMES WORTH DEEPER RESEARCH
- **AEP.L** — pending OCF / qualitative business review
- **ITV.L** — high yield vs cyclical ad market
"""
    parsed = _parse_deep_analysis(text)
    assert "Selective" in parsed.executive_intro
    assert "AEP.L looks clean" in parsed.top_picks_analysis
    assert "AEP.L" in parsed.red_flags
    assert "ITV.L" in parsed.red_flags


def test_parse_deep_analysis_fallback_splits_dumped_intro():
    text = """EXECUTIVE INTRO
Broad caution across the tape.

**Names worth deeper research (up to 3):** **AEP.L** (pristine metrics), **ITV.L** (timing + yield).
"""
    parsed = _parse_deep_analysis(text)
    assert "Broad caution" in parsed.executive_intro
    assert "AEP.L" in parsed.red_flags
    assert "Names worth deeper research" not in parsed.executive_intro


def test_worker_extraction_rules_cover_filing_and_news_discipline():
    filing = worker_task_extraction_rules("summarize_filing_body")
    assert "continuing" in filing.lower()
    assert "held-for-sale" in filing.lower()
    assert "dividend cover" in filing.lower()
    assert "reporting currency" in filing.lower()

    news = worker_task_extraction_rules(
        "digest_news_manifest", ticker="ITV.L", company_name="ITV plc"
    )
    assert "carve-out" in news.lower()
    assert "ITV-the-broadcaster" in news


def test_augment_research_worker_prompt_appends_rules():
    base = """You are a **research worker** on ITV plc (ITV.L).

Task id: t1
Task type: summarize_filing_body
Focus: FY25 results
Read only: /tmp/body.txt

Return JSON only.
"""
    augmented = _augment_research_worker_prompt(base)
    assert augmented != base
    assert filing_extraction_discipline() in augmented


def test_news_extraction_discipline_ignores_itv_broadcaster_noise_for_itv_l():
    text = news_extraction_discipline(ticker="ITV.L", company_name="ITV plc")
    assert "entertainment noise" in text.lower()
    generic = news_extraction_discipline(ticker="AAA.L", company_name="Alpha PLC")
    assert "ITV-the-broadcaster" not in generic


def test_filter_questions_for_ticker_drops_foreign_listed_tickers():
    questions = [
        "Does FGP.L dividend policy affect ME Group coach exposure?",
        "What is interim FCF/dividend cover on MEGP.L filing bodies?",
    ]
    kept = filter_questions_for_ticker(questions, "MEGP.L")
    assert len(kept) == 1
    assert "FGP.L" not in kept[0]
    assert "MEGP.L" in kept[0]


def test_gap_fill_prompt_requires_screen_filing_reconciliation():
    prompt = _gap_fill_prompt(
        ticker="MEGP.L",
        company_name="ME Group International plc",
        sources_dir=Path("/tmp/sources"),
        existing_markdown_path=Path("/tmp/research.md"),
        open_questions=["Reconcile dividend cover on filings"],
    )
    discipline = screen_filing_reconciliation_discipline()
    assert discipline.splitlines()[0] in prompt
    assert "adjusted_signal" in prompt
    assert "dual" in prompt.lower() or "OCF" in prompt
    assert research_model_suggestions_discipline() in prompt


def test_ch_refetch_passed_detects_companies_house_fetch():
    assert ch_refetch_passed(ch_refetch={"fetched": 1})
    assert ch_refetch_passed(body_refetch={"companies_house": {"fetched": 2}})
    assert not ch_refetch_passed(ch_refetch={"fetched": 0}, body_refetch={"fetched": 0})


def _write_mgns_style_ch_sources(tmp_path: Path, *, year_count: int) -> Path:
    sources_dir = tmp_path / "sources"
    filings_dir = sources_dir / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    templates = {
        2023: (
            "2023 in numbers\nRevenue\n£3,800.0m\n(2022: £3,500.0m)\n"
            "Operating profit (adjusted*)\n£130.0m\n(2022: £120.0m)\n"
            "Secured workload\n£8,500.0m\n(2022: £7,900.0m)\n"
        ),
        2024: (
            "2024 in numbers\nStrong operating performance\nRevenue\n£4,546.2m\n"
            "(2023: £4,117.7m)\nOperating profit (adjusted*)\n£162.6m\n(2023: £141.3m)\n"
            "Secured workload\n£11,419.3m\n(2023: £8,920.2m)\nMateriality\n"
        ),
        2025: (
            "2025 in numbers\nStrong operating performance\n"
            "Revenue Operating profit (adjusted*)\n£5,018.6m £225.7m\n"
            "(2024 £4,546.2m) (2024 £162.6m)\nOperating profit Secured workload\n"
            "£224.9m £11,972.2m\n(2024 £162.0m) (2024 £11,419.3m)\nFinancial strength\n"
        ),
    }
    index_rows = []
    for year in sorted(templates)[:year_count]:
        body_id = f"ch_{year}"
        path = bodies_dir / f"{body_id}.txt"
        path.write_text(templates[year], encoding="utf-8")
        index_rows.append(
            {
                "id": body_id,
                "source": "companies_house",
                "headline": "Full accounts made up to 31 December",
                "period": "annual",
                "has_body": True,
                "body_path": str(path),
                "published_at": f"{year + 1}-03-01",
            }
        )
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"filings": index_rows}),
        encoding="utf-8",
    )
    return sources_dir


def test_ch_three_year_margin_secured_series_present(tmp_path: Path):
    sources_two = _write_mgns_style_ch_sources(tmp_path / "two", year_count=2)
    sources_three = _write_mgns_style_ch_sources(tmp_path / "three", year_count=3)
    assert not ch_three_year_margin_secured_series_present(sources_two, ticker="MGNS.L")
    assert ch_three_year_margin_secured_series_present(sources_three, ticker="MGNS.L")


def test_gap_fill_ch_refetch_prompt_requires_three_year_series(tmp_path: Path):
    sources_dir = _write_mgns_style_ch_sources(tmp_path, year_count=3)
    context = gap_fill_ch_refetch_prompt_context(
        sources_dir,
        ticker="MGNS.L",
        ch_refetch={"fetched": 1},
    )
    assert "ch_*.txt" in context
    assert "≥3 fiscal years" in context
    assert "secured-workload" in context.lower()

    prompt = _gap_fill_followup_prompt(
        ticker="MGNS.L",
        company_name="Morgan Sindall Group plc",
        sources_dir=sources_dir,
        existing_markdown_path=Path("/tmp/research.md"),
        open_questions=["Confirm cyclical peak risk"],
        body_refetch={"fetched": 1},
        extra_evidence_discipline=f"\n{context}\n",
    )
    assert gap_fill_ch_refetch_discipline(require_margin_secured_series=True) in prompt


def test_gap_fill_ch_refetch_prompt_skipped_without_ch_fetch():
    assert (
        gap_fill_ch_refetch_prompt_context(
            Path("/tmp/empty"),
            ticker="MGNS.L",
            ch_refetch={"fetched": 0},
        )
        == ""
    )


def test_is_actionable_research_model_suggestion_rejects_memo_status():
    assert not is_actionable_research_model_suggestion(
        "Updated in `output/research/MEGP.L/research.md`."
    )
    assert not is_actionable_research_model_suggestion(
        "Also written to `output/research/MGNS.L/research.md`."
    )
    assert not is_actionable_research_model_suggestion(
        "The memo at `output/research/MEGP.L/research.md` has been updated to version 3."
    )
    assert not is_actionable_research_model_suggestion(
        "`output/research/ITV.L/research.md` is updated with these sections."
    )
    assert not is_actionable_research_model_suggestion(
        "The memo at `output/research/HIK.L/research.md` has been updated to version 2 "
        "(gap_fill mode) with these sections."
    )
    assert is_actionable_research_model_suggestion(
        "Index trading-update RNS for MEGP.L when filings_index trading_update count is zero"
    )


def test_engineering_compile_skips_memo_status_suggestions(tmp_path: Path):
    from value_investor.engineering_tasks import build_compiled_task_candidates

    suggestions_path = tmp_path / "research_model_suggestions.json"
    suggestions_path.write_text(
        """{
  "suggestions": [
    {
      "ticker": "ITV.L",
      "area": "research",
      "priority": "medium",
      "suggestion": "`output/research/ITV.L/research.md` is updated with these sections.",
      "recorded_at": "2026-09-13T08:06:10.268038+00:00"
    },
    {
      "ticker": "MEGP.L",
      "area": "ingest",
      "priority": "high",
      "suggestion": "Index trading-update RNS for MEGP.L when filings_index trading_update count is zero",
      "recorded_at": "2026-09-13T08:06:10.268038+00:00"
    }
  ]
}""",
        encoding="utf-8",
    )
    candidates = build_compiled_task_candidates(
        output_dir=tmp_path,
        suggestions_path=suggestions_path,
        scope="full",
        tasks_path=tmp_path / "missing_tasks.json",
        lookback_days=14,
    )
    titles = [task.title for task in candidates]
    assert not any("ITV.L/research.md" in title for title in titles)
    assert any("MEGP.L" in title for title in titles)


def test_persist_model_suggestions_skips_memo_status_lines(tmp_path: Path):
    path = tmp_path / "research_model_suggestions.json"
    appended = _persist_model_suggestions(
        [
            {
                "area": "research",
                "priority": "medium",
                "suggestion": "Also written to `output/research/MGNS.L/research.md`.",
            },
            {
                "area": "research",
                "priority": "medium",
                "suggestion": "Updated in `output/research/MEGP.L/research.md`.",
            },
            {
                "area": "research",
                "priority": "medium",
                "suggestion": "`output/research/ITV.L/research.md` is updated with these sections.",
            },
            {
                "area": "ingest",
                "priority": "high",
                "suggestion": "Pull IR PDFs when RNS bodies are empty",
            },
        ],
        path=path,
    )
    assert len(appended) == 1
    assert appended[0]["suggestion"].startswith("Pull IR PDFs")


def test_supplement_deal_structure_questions_adds_filing_prompts():
    enriched = supplement_deal_structure_questions(
        ["high yield vs cyclical ad market"],
        "ITV.L carve-out to Sky; dividend yield looks high on screen",
        ticker="ITV.L",
        name="ITV plc",
    )
    assert len(enriched) >= 2
    joined = " ".join(enriched).lower()
    assert "continuing" in joined
    assert "free cash flow" in joined


def test_extract_gap_fill_targets_from_red_flags():
    analysis = DeepAnalysis(
        executive_intro="Tone is cautious.",
        top_picks_analysis="",
        red_flags=(
            "NAMES WORTH DEEPER RESEARCH\n"
            "- **AEP.L** — pending OCF/qualitative business review\n"
            "- **ITV.L** — Sky carve-out leaves stub equity; screen yield vs filing FCF/dividend cover\n"
            "- **HIK.L** — negative FCF vs dividend puzzle\n"
        ),
    )
    reports = [
        _report("AEP.L", "Anglo-Eastern"),
        _report("ITV.L", "ITV", signal="buy"),
        _report("HIK.L", "Hikma", signal="buy"),
        _report("MEGP.L", "Morgan Sindall", signal="hold"),
    ]
    targets = extract_gap_fill_targets(analysis, reports, max_targets=3)
    assert [t.ticker for t in targets] == ["AEP.L", "ITV.L", "HIK.L"]
    assert any("OCF" in q for q in targets[0].questions)
    assert any("FCF" in q or "dividend" in q for q in targets[2].questions)
    itv = next(t for t in targets if t.ticker == "ITV.L")
    assert any("continuing" in q.lower() for q in itv.questions)


def test_parse_gap_fill_update_section():
    text = """GAP FILL UPDATE
Q: Is FCF negative structural?
Status: partially_resolved
Evidence: FY2025 cash flow still working-capital heavy.

FINANCIAL REVIEW
Filing bodies show operating cash positive.

RISKS AND RED FLAGS
Dividend cover remains the open debate.

RESEARCH VERDICT
Verdict: neutral
Risk: medium
Confidence: 0.55
Rationale: Gap-fill clarifies cash generation but not dividend sustainability.
"""
    sections = parse_research_sections(text)
    assert "partially_resolved" in sections["gap_fill_update"]
    assert "operating cash" in sections["financial_review"]
    assert "Dividend cover" in sections["risks_and_flags"]
    assert "Verdict: neutral" in sections["research_verdict"]


def test_format_gap_fill_text_lists_targets():
    report = _report("AEP.L", "Anglo-Eastern")
    summary = GapFillSummary(
        targets=[
            GapFillTarget(
                ticker="AEP.L",
                name="Anglo-Eastern",
                report=report,
                questions=["pending OCF review"],
            )
        ],
        updated=1,
        question_outcomes=[
            {
                "ticker": "AEP.L",
                "question": "pending OCF review",
                "status": "unresolved",
                "next_sources": "Companies House accounts",
            }
        ],
        model_suggestions=[
            {
                "ticker": "AEP.L",
                "area": "ingest",
                "priority": "high",
                "suggestion": "Add Companies House PDF body extract for UK names",
            }
        ],
    )
    text = format_gap_fill_text(summary)
    assert text is not None
    assert "AEP.L" in text
    assert "pending OCF" in text
    assert "Companies House" in text
    assert "Research-model suggestions" in text


def test_parse_model_suggestions_and_outcomes():
    from value_investor.research.gap_fill_sources import (
        parse_model_suggestions,
        parse_question_outcomes,
        suggest_alternate_sources,
    )

    outcomes = parse_question_outcomes(
        """
Q: Is FCF negative structural?
Status: unresolved
Evidence: Filing bodies missing cash-flow note.
SourcesTried: filings_bodies, yahoo_financials, alternate_news
NextSources: Companies House annual report PDF; IR presentation
"""
    )
    assert outcomes[0]["status"] == "unresolved"
    assert "Companies House" in outcomes[0]["next_sources"]

    suggestions = parse_model_suggestions(
        """
- area: ingest | priority: high | suggestion: Add Companies House PDF ingest for UK memos
- area: prompt | priority: medium | suggestion: Ask explicitly for FCF bridge when Yahoo FCF conflicts with filings
"""
    )
    assert suggestions[0]["area"] == "ingest"
    assert suggestions[0]["priority"] == "high"
    assert "Companies House" in suggestions[0]["suggestion"]

    planned = suggest_alternate_sources(
        ticker="HIK.L",
        market="ftse350",
        inventory={"thin": ["filings_bodies"]},
        open_questions=["negative FCF vs dividend puzzle", "pension risk"],
    )
    assert planned
    assert any(item["id"] == "companies_house_accounts" for item in planned)


def test_unresolved_questions_filters_statuses():
    outcomes = [
        {"question": "Q1", "status": "resolved"},
        {"question": "Q2", "status": "partially_resolved"},
        {"question": "Q3", "status": "unresolved"},
        {"question": "", "status": "unresolved"},
    ]
    assert _unresolved_questions(outcomes) == ["Q2", "Q3"]


def test_parse_research_model_suggestions_section():
    text = """GAP FILL UPDATE
Q: test
Status: resolved
Evidence: ok
SourcesTried: filings_bodies
NextSources: none

RESEARCH MODEL SUGGESTIONS
- area: ingest | priority: high | suggestion: Pull IR PDFs when RNS bodies are empty
"""
    sections = parse_research_sections(text)
    assert "IR PDFs" in sections["research_model_suggestions"]
