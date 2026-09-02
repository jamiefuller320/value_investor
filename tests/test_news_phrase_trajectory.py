"""Tests for offline news-phrase ↔ trajectory panel."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.news_phrase_trajectory import (
    LEXICON_FILENAME,
    PANEL_FILENAME,
    STATE_FILENAME,
    PhraseObservation,
    extract_phrases,
    run_news_phrase_trajectory,
    select_buy_boundary_cohort,
    walk_forward_lexicon,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _article(article_id: str, title: str, published_at: str) -> dict:
    return {
        "id": article_id,
        "source": "test",
        "title": title,
        "summary": "",
        "published_at": published_at,
        "url": "https://example.test",
    }


def _seed_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    for week in range(6):
        run_at = datetime(2026, 7, 1, tzinfo=UTC) + timedelta(days=7 * week)
        price_a = 100.0 * (1.02**week)
        price_b = 100.0 * (0.98**week)
        payload = {
            "run_at": run_at.isoformat(),
            "prices": {"AAA.L": price_a, "BBB.L": price_b},
            "signals": [
                {
                    "ticker": "AAA.L",
                    "signal": "buy",
                    "conviction_score": 0.4,
                    "name": "Alpha Plc",
                },
                {
                    "ticker": "BBB.L",
                    "signal": "hold",
                    "conviction_score": 0.3,
                    "name": "Beta Plc",
                },
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
                },
                {
                    "ticker": "CCC.L",
                    "name": "Gamma Plc",
                    "signal": "hold",
                    "conviction_score": 0.2,
                    "sector": "Test",
                },
            ]
        },
    )
    _write_json(
        data_dir / "trajectory_boundary_watch.json",
        {
            "schema_version": 1,
            "panel": [
                {
                    "ticker": "BBB.L",
                    "name": "Beta Plc",
                    "signal": "hold",
                    "conviction_score": 0.3,
                    "core_boundary_tags": ["pre_buy"],
                    "sector": "Test",
                }
            ],
        },
    )
    _write_json(
        data_dir / "trajectory_transitions.json",
        {"schema_version": 1, "events": []},
    )

    for ticker in ("AAA.L", "BBB.L"):
        _write_json(
            data_dir / "research" / ticker / "sources" / "news_manifest.json",
            {
                "ticker": ticker,
                "articles": [
                    _article(
                        f"{ticker}-1",
                        "Sudden profit warning hits outlook",
                        "2026-07-02T12:00:00+00:00",
                    ),
                    _article(
                        f"{ticker}-2",
                        "Dividend boost announced today",
                        "2026-07-03T12:00:00+00:00",
                    ),
                    _article(
                        f"{ticker}-3",
                        "Sudden profit warning revisited",
                        "2026-07-08T12:00:00+00:00",
                    ),
                    _article(
                        f"{ticker}-4",
                        "Contract win expands pipeline",
                        "2026-07-15T12:00:00+00:00",
                    ),
                    _article(
                        f"{ticker}-5",
                        "Sudden profit warning remains",
                        "2026-07-22T12:00:00+00:00",
                    ),
                ],
            },
        )
    return data_dir


def test_extract_phrases_filters_issuer_and_stopwords():
    phrases = extract_phrases(
        "Alpha Plc issues sudden profit warning",
        issuer_stops={"alpha"},
    )
    assert "sudden" in phrases
    assert "profit warning" in phrases
    assert "alpha" not in phrases
    assert "plc" not in phrases


def test_select_buy_boundary_cohort_unions_sources(tmp_path: Path):
    data_dir = _seed_data_dir(tmp_path)
    cohort = select_buy_boundary_cohort(data_dir)
    tickers = {row["ticker"] for row in cohort}
    assert tickers == {"AAA.L", "BBB.L"}
    by_ticker = {row["ticker"]: row for row in cohort}
    assert "buy_tier" in by_ticker["AAA.L"]["cohort_tags"]
    assert "boundary" in by_ticker["BBB.L"]["cohort_tags"]


def test_walk_forward_lexicon_ranks_cross_ticker_phrases():
    base = datetime(2026, 7, 1, tzinfo=UTC)
    observations: list[PhraseObservation] = []
    for index in range(8):
        published = base + timedelta(days=index)
        observations.append(
            PhraseObservation(
                ticker="AAA.L" if index % 2 == 0 else "BBB.L",
                article_id=f"a-{index}",
                published_at=published,
                phrase="profit warning",
                ngram=2,
                forward_return_4w=0.05 if index < 5 else -0.01,
                forward_return_8w=None,
                forward_return_12w=None,
                transition_key=None,
                transition_direction=None,
            )
        )
    result = walk_forward_lexicon(observations, train_fraction=0.7, min_train_count=2)
    phrases = {row["phrase"]: row for row in result["phrases"]}
    assert "profit warning" in phrases
    assert phrases["profit warning"]["ticker_count"] == 2


def test_run_news_phrase_trajectory_writes_artifacts(tmp_path: Path):
    data_dir = _seed_data_dir(tmp_path)
    payload = run_news_phrase_trajectory(data_dir, mode="full")
    assert (data_dir / PANEL_FILENAME).exists()
    assert (data_dir / LEXICON_FILENAME).exists()
    assert (data_dir / STATE_FILENAME).exists()
    panel = payload["panel"]
    assert panel["observe_only"] is True
    assert panel["source_pool"] == "buy_boundary"
    assert panel["cohort_ticker_count"] == 2
    assert panel["article_count"] == 10
    assert panel["observation_count"] > 0
    assert payload["state"]["ticker_watermarks"]

    payload2 = run_news_phrase_trajectory(data_dir, mode="rolling")
    assert payload2["lexicon"]["lexicon_generation"] == panel["lexicon_generation"] + 1
