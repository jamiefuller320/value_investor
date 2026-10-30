"""L650 entry news polarity — PIT join, discrete labels, cite freshness metadata."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.entry_blind_review import build_entry_blind_review_queue
from value_investor.entry_news_polarity import (
    DEFAULT_LOOKBACK_DAYS,
    FRESHNESS_MEDIUM_DAYS,
    FRESHNESS_RECENT_DAYS,
    bind_entry_news_polarity,
    build_entry_news_polarity_panel,
    cite_recency_meta,
    derive_entry_news_polarity,
    freshness_band,
    ops_findings_from_entry_news_polarity,
    pit_manifest_articles,
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


def _seed_manifest(data_dir: Path, ticker: str, articles: list[dict]) -> None:
    _write_json(
        data_dir / "research" / ticker / "sources" / "news_manifest.json",
        {"ticker": ticker, "articles": articles},
    )


def test_default_lookback_is_hard_90_days():
    assert DEFAULT_LOOKBACK_DAYS == 90


def test_freshness_bands_are_display_only():
    assert freshness_band(0) == "recent"
    assert freshness_band(FRESHNESS_RECENT_DAYS) == "recent"
    assert freshness_band(FRESHNESS_RECENT_DAYS + 1) == "medium"
    assert freshness_band(FRESHNESS_MEDIUM_DAYS) == "medium"
    assert freshness_band(FRESHNESS_MEDIUM_DAYS + 1) == "stale"
    from datetime import date

    meta = cite_recency_meta(published_at="2026-10-10T12:00:00+00:00", asof_day=date(2026, 10, 20))
    assert meta == {"age_days": 10, "freshness": "recent"}
    # No fade_score / weight key — metadata only.
    assert "fade" not in meta and "weight" not in meta


def test_pit_cutoff_drops_post_buy_and_outside_window(tmp_path: Path):
    ticker = "AAA.L"
    _seed_manifest(
        tmp_path,
        ticker,
        [
            _article("post", "Alpha Plc profit warning", "2026-10-25T10:00:00+00:00"),
            _article("in", "Alpha Plc wins contract", "2026-10-10T10:00:00+00:00"),
            _article("old", "Alpha Plc going concern", "2026-06-01T10:00:00+00:00"),
        ],
    )
    rows = pit_manifest_articles(tmp_path, ticker, asof="2026-10-20", lookback_days=90)
    ids = {str(r["id"]) for r in rows}
    assert ids == {"in"}
    assert "post" not in ids
    assert "old" not in ids


def test_empty_manifest_fail_closed_no_usable_news(tmp_path: Path):
    pol = derive_entry_news_polarity(
        ticker="ZZZ.L",
        entry_at="2026-10-20",
        name="Zed Co",
        data_dir=tmp_path,
    )
    assert pol["label"] == "no_usable_news"
    assert pol["join_ok"] is False
    assert pol["influences_live"] is False
    assert pol["cites"] == []


def test_structural_title_label_and_cite(tmp_path: Path):
    ticker = "AAA.L"
    _seed_manifest(
        tmp_path,
        ticker,
        [
            _article(
                "a1",
                "Alpha Plc issues profit warning amid going concern review",
                "2026-10-15T10:00:00+00:00",
            )
        ],
    )
    pol = derive_entry_news_polarity(
        ticker=ticker,
        entry_at="2026-10-20",
        name="Alpha Plc",
        data_dir=tmp_path,
    )
    assert pol["label"] == "structural_negative"
    assert pol["join_ok"] is True
    assert pol["cites"]
    cite = pol["cites"][0]
    assert cite["valence_hint"] == "structural_negative"
    assert cite["age_days"] == 5
    assert cite["freshness"] == "recent"
    assert "fade_score" not in cite
    assert "weight" not in pol


def test_contract_win_improvement_path(tmp_path: Path):
    ticker = "AAA.L"
    _seed_manifest(
        tmp_path,
        ticker,
        [_article("c1", "Alpha Plc wins major contract in defence", "2026-10-05T10:00:00+00:00")],
    )
    pol = derive_entry_news_polarity(
        ticker=ticker,
        entry_at="2026-10-20",
        name="Alpha Plc",
        data_dir=tmp_path,
    )
    assert pol["label"] == "improvement_path"
    assert any(c.get("event_type") == "contract" for c in pol["cites"])


def test_conflicting_cites_mixed_or_unclear(tmp_path: Path):
    ticker = "AAA.L"
    _seed_manifest(
        tmp_path,
        ticker,
        [
            _article("n1", "Alpha Plc profit warning", "2026-10-18T10:00:00+00:00"),
            _article("p1", "Alpha Plc wins contract", "2026-10-12T10:00:00+00:00"),
        ],
    )
    pol = derive_entry_news_polarity(
        ticker=ticker,
        entry_at="2026-10-20",
        name="Alpha Plc",
        data_dir=tmp_path,
    )
    assert pol["label"] == "mixed_or_unclear"
    assert pol["counts"]["structural_hints"] >= 1
    assert pol["counts"]["improvement_hints"] >= 1


def test_journal_row_after_buy_day_ignored(tmp_path: Path):
    ticker = "AAA.L"
    _seed_manifest(
        tmp_path,
        ticker,
        [_article("weak", "Alpha Plc trading update", "2026-10-10T10:00:00+00:00")],
    )
    _write_json(
        tmp_path / "news_event_journal.json",
        {
            "events": [
                {
                    "event_id": "postbuy",
                    "ticker": ticker,
                    "article_id": "weak",
                    "published_at": "2026-10-25T10:00:00+00:00",
                    "title": "Alpha Plc wins contract",
                    "primary_event_type": "contract",
                }
            ]
        },
    )
    pol = derive_entry_news_polarity(
        ticker=ticker,
        entry_at="2026-10-20",
        name="Alpha Plc",
        data_dir=tmp_path,
    )
    # Weak headline only → mixed_or_unclear; post-buy journal must not flip to improvement.
    assert pol["label"] == "mixed_or_unclear"
    assert pol["counts"]["journal_hits"] == 0


def test_bind_on_entry_blind_card_and_panel(tmp_path: Path):
    ticker = "LAB.L"
    _seed_manifest(
        tmp_path,
        ticker,
        [_article("x1", "Lab Co issues profit warning", "2026-10-18T09:00:00+00:00")],
    )
    sealed = {
        "models": [
            {
                "model_id": "n200",
                "label": "N200",
                "columns": {
                    "just_bought": {
                        "chips": [
                            {
                                "ticker": "AAA.L",
                                "name": "Alpha",
                                "status": "open",
                                "entry_run_at": "2026-10-20T10:00:00+00:00",
                                "days_in_phase": 2,
                            }
                        ]
                    }
                },
            }
        ]
    }
    lab = {
        "lab_id": "cue_consumer_mft",
        "open_lab_buys": [
            {"ticker": ticker, "name": "Lab Co", "entry_at": "2026-10-22T09:00:00+00:00"}
        ],
    }
    payload = build_entry_blind_review_queue(
        data_dir=tmp_path,
        sealed=sealed,
        lab=lab,
        labels={"events": [], "actioned_review_ids": [], "active_replies": []},
    )
    lab_card = next(row for row in payload["active"] if row["ticker"] == ticker)
    assert "entry_news_polarity" in lab_card
    assert lab_card["entry_news_polarity"]["label"] == "structural_negative"
    assert lab_card["entry_news_polarity"]["influences_live"] is False
    # AAA has no manifest → fail-closed
    aaa = next(row for row in payload["active"] if row["ticker"] == "AAA.L")
    assert aaa["entry_news_polarity"]["label"] == "no_usable_news"
    assert payload["entry_news_polarity_summary"]["cards_with_usable_news"] >= 1
    assert payload["clocks"]["entry_news_polarity_lookback_days"] == 90

    panel = build_entry_news_polarity_panel(data_dir=tmp_path, cards=payload["active"])
    findings = ops_findings_from_entry_news_polarity(panel)
    assert findings and findings[0]["auto_fixable"] is False
    assert "Entry news polarity" in findings[0]["title"]


def test_bind_entry_news_polarity_does_not_mutate_buy_decision(tmp_path: Path):
    item = {
        "ticker": "AAA.L",
        "entry_at": "2026-10-20",
        "name": "Alpha",
        "buy_decision": {"code": "x", "label": "y", "join_ok": True},
    }
    before = dict(item["buy_decision"])
    bind_entry_news_polarity(item, data_dir=tmp_path)
    assert item["buy_decision"] == before
    assert item["entry_news_polarity"]["label"] == "no_usable_news"
