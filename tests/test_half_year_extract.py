"""Half-year revenue and EPS extraction from results filing bodies."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.research.filings import (
    extract_filing_interim_financials,
    resolve_filing_body_path_for_row,
)
from value_investor.research.half_year_extract import parse_half_year_results

_GBP = "\n".join(
    [
        "Interim results for the six months ended 30 June 2026",
        "and the six months ended 30 June 2025",
        "£m H1 2026 H1 2025 Change",
        "Group revenue 1,887 1,848 2%",
        "Basic earnings per share (p) 12.3 10.1",
        "Diluted earnings per share (p) 12.1 10.0",
    ]
)

_USD = "\n".join(
    [
        "Interim results for the six months ended 30 June 2026",
        "US$m H1 2026 H1 2025",
        "Revenue 249.7 230.5",
        "Basic earnings per share (cents) 12.71 12.33",
    ]
)

_SEGMENT = "\n".join(
    [
        "Interim results for the six months ended 30 June 2026",
        "£m H1 2026 H1 2025",
        "Advertising revenue 100 90",
        "Group revenue 500 480",
    ]
)

_AMBIGUOUS = "\n".join(
    [
        "Interim results for the six months ended 30 June 2026",
        "Q1 2026 H1 2026 Q1 2025 H1 2025",
        "Revenue 10 100 9 90",
    ]
)

_PRIOR_MISSING = "\n".join(
    [
        "Interim results for the six months ended 30 June 2026",
        "six months ended 31 December 2024",
        "£m H1 2026 H1 2024",
        "Group revenue 100 80",
    ]
)


def test_gbp_table_extracts_revenue_and_basic_eps():
    parsed = parse_half_year_results(_GBP)
    assert parsed["status"] == "extracted"
    assert parsed["period_end"] == "2026-06-30"
    assert parsed["prior_period_end"] == "2025-06-30"
    assert parsed["prior_period_basis"] == "stated"
    revenue = parsed["revenue"]
    assert revenue["label"] == "Group revenue"
    assert revenue["current"] == 1887
    assert revenue["prior"] == 1848
    assert revenue["unit"] == "millions"
    assert revenue["currency"] == "GBP"
    assert "1,887" in revenue["snippet"]
    kinds = {item["kind"]: item for item in parsed["eps"]}
    assert kinds["basic"]["current"] == 12.3
    assert kinds["basic"]["prior"] == 10.1
    assert kinds["basic"]["unit"] == "pence"
    assert kinds["basic"]["currency"] == "GBP"
    assert kinds["diluted"]["current"] == 12.1
    assert kinds["diluted"]["prior"] == 10.0
    assert parsed["parse_confidence"] == "high"


def test_usd_table_extracts_revenue_and_cents():
    parsed = parse_half_year_results(_USD)
    assert parsed["status"] == "extracted"
    assert parsed["revenue"]["current"] == 249.7
    assert parsed["revenue"]["prior"] == 230.5
    assert parsed["revenue"]["unit"] == "millions"
    assert parsed["revenue"]["currency"] == "USD"
    eps = parsed["eps"][0]
    assert eps["kind"] == "basic"
    assert eps["current"] == 12.71
    assert eps["prior"] == 12.33
    assert eps["unit"] == "cents"
    assert eps["currency"] == "USD"


def test_segment_line_is_dropped_when_a_group_total_exists():
    parsed = parse_half_year_results(_SEGMENT)
    assert parsed["status"] == "extracted"
    assert parsed["revenue"]["label"] == "Group revenue"
    assert parsed["revenue"]["current"] == 500
    assert parsed["revenue"]["prior"] == 480
    assert "Advertising" not in parsed["revenue"]["snippet"]


def test_mixed_quarter_and_half_columns_are_not_extracted():
    parsed = parse_half_year_results(_AMBIGUOUS)
    assert parsed["status"] == "not_extracted"
    assert parsed["revenue"] is None


def test_prior_period_that_is_not_one_year_earlier_is_rejected():
    parsed = parse_half_year_results(_PRIOR_MISSING)
    assert parsed["status"] == "not_extracted"
    assert parsed["why"] == "prior_period_not_one_year"
    assert parsed["revenue"] is None


def test_body_path_prefers_bodies_basename_then_filing_id(tmp_path: Path):
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    named = bodies / "d19c5d3b8e0bb46a.txt"
    named.write_text("by basename", encoding="utf-8")
    elsewhere = tmp_path / "output.txt"
    elsewhere.write_text("stored path", encoding="utf-8")
    row = {
        "id": "0b6a182e697ac7a6",
        "body_path": "output/research/ITV.L/sources/filings/bodies/d19c5d3b8e0bb46a.txt",
    }
    assert resolve_filing_body_path_for_row(row, bodies) == named

    (bodies / "abc123.txt").write_text("by id", encoding="utf-8")
    id_row = {"id": "abc123", "body_path": "output/research/missing.txt"}
    assert resolve_filing_body_path_for_row(id_row, bodies) == bodies / "abc123.txt"

    direct = {"id": "nope", "body_path": str(elsewhere)}
    assert resolve_filing_body_path_for_row(direct, bodies) == elsewhere


def test_extract_writes_half_year_comparison_and_skips_unchanged(tmp_path: Path):
    filings = tmp_path / "filings"
    bodies = filings / "bodies"
    bodies.mkdir(parents=True)
    (bodies / "h1.txt").write_text(_GBP, encoding="utf-8")
    (filings / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": "other-id",
                        "period": "interim",
                        "has_body": True,
                        "headline": "2026 Interim Results",
                        "published_at": "2026-07-31T07:00:00+00:00",
                        "body_path": "output/research/EX.L/sources/filings/bodies/h1.txt",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sources = tmp_path / "sources"
    first = extract_filing_interim_financials(filings, "EX.L", sources_dir=sources)
    assert first["half_year_comparison"]["status"] == "extracted"
    assert first["half_year_comparison"]["revenue"]["current"] == 1887
    assert first["half_year_comparison"]["source_filing_id"] == "other-id"
    on_disk = json.loads((sources / "filing_interim_financials.json").read_text(encoding="utf-8"))
    assert on_disk["half_year_comparison"]["period_end"] == "2026-06-30"
    second = extract_filing_interim_financials(filings, "EX.L", sources_dir=sources)
    assert second["extracted_at"] == first["extracted_at"]


def test_extract_rejects_a_period_published_before_it_ended(tmp_path: Path):
    filings = tmp_path / "filings"
    bodies = filings / "bodies"
    bodies.mkdir(parents=True)
    (bodies / "late.txt").write_text(_GBP, encoding="utf-8")
    (filings / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": "late",
                        "period": "interim",
                        "has_body": True,
                        "headline": "Interim results",
                        "published_at": "2026-01-15",
                        "body_path": str(bodies / "late.txt"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = extract_filing_interim_financials(filings, "EX.L", sources_dir=None)
    record = payload["half_year_comparisons"][0]
    assert record["status"] == "not_extracted"
    assert record["why"] == "period_after_publication"
    assert payload["half_year_comparison"] is None
