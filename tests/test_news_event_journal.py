"""Tests for the observe-only material-event news journal."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.news_event_journal import (
    JOURNAL_FILENAME,
    RULES_FILENAME,
    STATE_FILENAME,
    FilingRow,
    assess_evidence,
    classify_headline,
    extract_event_facts,
    issuer_mentioned,
    join_later_filing,
    run_news_event_journal,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _article(article_id: str, title: str, published_at: str, summary: str = "") -> dict:
    return {
        "id": article_id,
        "source": "test",
        "title": title,
        "summary": summary,
        "published_at": published_at,
        "url": "https://example.test",
    }


def test_classify_headline_event_types():
    leadership = classify_headline("Alpha Plc CEO John Smith resigns")
    assert leadership["primary_event_type"] == "leadership"
    assert "leadership:0" in leadership["matched_rules"]

    deal = classify_headline("Alpha agrees acquisition of rival")
    assert deal["primary_event_type"] == "m_and_a"

    contract = classify_headline("Alpha wins major contract in defence")
    assert contract["primary_event_type"] == "contract"

    strategy = classify_headline("Alpha launches strategic review of retail")
    assert strategy["primary_event_type"] == "strategy"

    none = classify_headline("Alpha Plc trading update in line with expectations")
    assert none["primary_event_type"] is None

    assert classify_headline("GSK Stock Down 14%: Time to Buy, Hold or Exit?")["primary_event_type"] is None
    assert classify_headline(
        "Do Alfa Financial Software Holdings' Earnings Warrant Your Attention?"
    )["primary_event_type"] is None
    assert classify_headline(
        "Balfour Beatty (BBY) Acquires 455,285 Shares at 807p in Latest Buyback"
    )["primary_event_type"] is None


def test_issuer_mentioned_rejects_currency_homonym():
    assert issuer_mentioned(
        "Aedifica NV appoints new CEO after board review",
        "",
        company_name="Aedifica NV/SA",
        ticker="AED.BR",
    )
    assert not issuer_mentioned(
        "AED hits new high versus the dollar",
        "Dirham strengthens on oil",
        company_name="Aedifica NV/SA",
        ticker="AED.BR",
    )
    assert not issuer_mentioned(
        "Oil prices rise as OPEC meets",
        "",
        company_name="Alpha Plc",
        ticker="AAA.L",
    )


def test_assess_evidence_flags_missing_size():
    facts = extract_event_facts("Sky agrees to buy ITV for up to £1.6 billion")
    assert facts["size"]["found"] is True
    assert facts["likelihood"]["found"] is True

    rich = assess_evidence(
        "m_and_a",
        "Sky agrees to buy ITV for up to £1.6 billion",
    )
    assert rich["seek_richer_source"] is False
    assert rich["evidence_status"] == "sufficient"

    thin = assess_evidence("contract", "Alpha wins major contract with NHS")
    assert thin["seek_richer_source"] is True
    assert thin["missing_fields"] == ["size"]
    assert thin["richer_source"] == "guardian_open_platform"

    leadership = assess_evidence("leadership", "Alpha Plc CEO Jane Roe resigns")
    assert leadership["seek_richer_source"] is False


def test_join_later_filing_headline_and_body():
    event_at = datetime(2026, 3, 1, tzinfo=UTC)
    headline_hit = FilingRow(
        filing_id="rns-1",
        published_at=datetime(2026, 3, 2, tzinfo=UTC),
        headline="Directorate change — CEO resignation",
        has_body=False,
        body_text="",
    )
    joined = join_later_filing(
        published_at=event_at,
        event_type="leadership",
        title="Alpha Plc CEO John Smith resigns",
        company_name="Alpha Plc",
        ticker="AAA.L",
        filings=[headline_hit],
    )
    assert joined["confirmation_kind"] == "headline_match"
    assert joined["days_to_later_filing"] == 1

    body_hit = FilingRow(
        filing_id="ar-1",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        headline="Annual Report 2026",
        has_body=True,
        body_text="The board notes that John Smith resigned as CEO in March.",
    )
    joined_body = join_later_filing(
        published_at=event_at,
        event_type="leadership",
        title="Alpha Plc CEO John Smith resigns",
        company_name="Alpha Plc",
        ticker="AAA.L",
        filings=[body_hit],
    )
    assert joined_body["confirmation_kind"] == "body_match"

    too_old = FilingRow(
        filing_id="old",
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
        headline="CEO resignation",
        has_body=False,
        body_text="",
    )
    empty = join_later_filing(
        published_at=event_at,
        event_type="leadership",
        title="Alpha Plc CEO John Smith resigns",
        company_name="Alpha Plc",
        ticker="AAA.L",
        filings=[too_old],
    )
    assert empty["later_filing_available"] is False
    assert empty["confirmation_kind"] is None


def _seed_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    for week in range(6):
        run_at = datetime(2026, 7, 1, tzinfo=UTC) + timedelta(days=7 * week)
        payload = {
            "run_at": run_at.isoformat(),
            "prices": {"AAA.L": 100.0 * (1.01**week)},
            "signals": [
                {
                    "ticker": "AAA.L",
                    "signal": "buy",
                    "conviction_score": 0.4,
                    "name": "Alpha Plc",
                }
            ],
        }
        stamp = run_at.strftime("%Y%m%d_%H%M%S")
        _write_json(data_dir / "history" / f"run_{stamp}.json", payload)

    _write_json(
        data_dir / "latest.json",
        {
            "reports": [
                {
                    "ticker": "AAA.L",
                    "name": "Alpha Plc",
                    "signal": "buy",
                    "conviction_score": 0.4,
                    "sector": "Test",
                }
            ]
        },
    )
    _write_json(data_dir / "trajectory_boundary_watch.json", {"schema_version": 1, "panel": []})

    sources = data_dir / "research" / "AAA.L" / "sources"
    _write_json(
        sources / "news_manifest.json",
        {
            "ticker": "AAA.L",
            "articles": [
                _article(
                    "a1",
                    "Alpha Plc CEO Jane Roe resigns",
                    "2026-07-02T12:00:00+00:00",
                ),
                _article(
                    "a2",
                    "AED hits new high versus the dollar",
                    "2026-07-03T12:00:00+00:00",
                    "Dirham strengthens",
                ),
                _article(
                    "a3",
                    "Alpha Plc trading in line",
                    "2026-07-04T12:00:00+00:00",
                ),
                _article(
                    "a4",
                    "Alpha wins major contract with NHS",
                    "2026-07-15T12:00:00+00:00",
                ),
            ],
        },
    )
    filings_dir = sources / "filings"
    _write_json(
        filings_dir / "filings_index.json",
        {
            "filings": [
                {
                    "id": "rns-ceo",
                    "headline": "Directorate change — CEO resignation",
                    "published_at": "2026-07-02T15:00:00+00:00",
                    "has_body": False,
                },
                {
                    "id": "ar-2026",
                    "headline": "Annual Report",
                    "published_at": "2026-08-01T09:00:00+00:00",
                    "has_body": True,
                },
            ]
        },
    )
    body = filings_dir / "bodies" / "ar-2026.txt"
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text(
        "The group won a major contract with NHS during the period.",
        encoding="utf-8",
    )
    return data_dir


def test_run_news_event_journal_full_and_rolling(tmp_path: Path):
    data_dir = _seed_data_dir(tmp_path)
    payload = run_news_event_journal(data_dir, mode="full")
    journal = payload["journal"]
    assert journal["observe_only"] is True
    assert journal["event_count"] == 2
    assert journal["issuer_reject_count"] == 1
    types = {row["primary_event_type"] for row in journal["events"]}
    assert types == {"leadership", "contract"}
    by_type = {row["primary_event_type"]: row for row in journal["events"]}
    assert by_type["leadership"]["confirmation_kind"] == "headline_match"
    assert by_type["leadership"]["seek_richer_source"] is False
    assert by_type["contract"]["confirmation_kind"] == "body_match"
    assert by_type["contract"]["seek_richer_source"] is True
    assert by_type["contract"]["missing_fields"] == ["size"]
    assert journal["seek_richer_source_count"] == 1
    assert (data_dir / JOURNAL_FILENAME).is_file()
    assert (data_dir / RULES_FILENAME).is_file()
    assert (data_dir / STATE_FILENAME).is_file()

    payload2 = run_news_event_journal(data_dir, mode="rolling")
    assert payload2["journal"]["event_count"] == 2
    assert payload2["journal"]["per_ticker"][0]["new_event_count"] == 0
