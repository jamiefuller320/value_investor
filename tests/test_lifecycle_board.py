"""Tests for the per-market lifecycle dashboard board."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.lifecycle_board import (
    COLUMN_SHOW_CAPS,
    build_lifecycle_board,
    classify_board_column,
    merge_track_columns,
    tenure_band_for_days,
    tickers_on_lifecycle_board,
    write_lifecycle_board,
)
from value_investor.position_lifecycle import BOARD_COLUMN_IDS
from value_investor.storage import write_json

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def test_classify_board_column_funnel():
    assert (
        classify_board_column(held=False, signal="avoid", conviction=0.1, now=NOW) == "not_buy_tier"
    )
    assert (
        classify_board_column(held=False, signal="buy", timing="wait", conviction=0.6, now=NOW)
        == "not_now"
    )
    assert (
        classify_board_column(
            held=False, signal="buy", timing="accumulate", conviction=0.6, now=NOW
        )
        == "near_buy"
    )
    assert classify_board_column(held=False, signal="hold", conviction=0.4, now=NOW) == "near_buy"
    opened = (NOW - timedelta(days=3)).isoformat()
    assert (
        classify_board_column(held=True, phase="starter", opened_at=opened, now=NOW)
        == "just_bought"
    )
    assert (
        classify_board_column(
            held=True, phase="full", opened_at="2025-01-01T00:00:00+00:00", now=NOW
        )
        == "growth"
    )
    assert classify_board_column(held=True, phase="harvest", now=NOW) == "near_sell"
    sold = (NOW - timedelta(days=2)).isoformat()
    assert classify_board_column(held=False, sold_at=sold, now=NOW) == "just_sold"
    older = (NOW - timedelta(days=30)).isoformat()
    assert classify_board_column(held=False, sold_at=older, now=NOW) == "post_sale"
    assert classify_board_column(held=False, cooldown=True, now=NOW) == "post_sale"


def test_held_name_is_not_also_on_the_screen_funnel(tmp_path: Path):
    live_reports = [
        {
            "ticker": "HOLD.L",
            "name": "Held PLC",
            "signal": "buy",
            "timing_signal": "accumulate",
            "conviction_score": 0.7,
        },
        {
            "ticker": "WAIT.L",
            "name": "Wait PLC",
            "signal": "buy",
            "timing_signal": "wait",
            "conviction_score": 0.55,
            "signal_since": (NOW - timedelta(days=10)).date().isoformat(),
        },
        {
            "ticker": "NEAR.L",
            "name": "Near PLC",
            "signal": "hold",
            "timing_signal": "neutral",
            "conviction_score": 0.4,
            "signal_since": (NOW - timedelta(days=30)).date().isoformat(),
        },
        {
            "ticker": "SKIP.L",
            "name": "Skip PLC",
            "signal": "avoid",
            "timing_signal": "wait",
            "conviction_score": 0.1,
        },
    ]
    paper = tmp_path / "paper"
    btl = paper / "buy_tier_level"
    btl.mkdir(parents=True)
    write_json(
        btl / "config.json",
        {
            "track_id": "buy_tier_level",
            "track_label": "Buy-tier level",
            "is_cohort_lab": True,
            "max_positions": 10,
        },
    )
    write_json(
        btl / "automated_fund.json",
        {
            "config": {"max_positions": 10, "name": "BTL"},
            "cash": 500,
            "holdings": {
                "HOLD.L": {
                    "ticker": "HOLD.L",
                    "shares": 10,
                    "avg_cost": 1.0,
                    "name": "Held PLC",
                    "opened_at": (NOW - timedelta(days=3)).isoformat(),
                }
            },
            "trades": [
                {
                    "id": "t1",
                    "fund_id": "f1",
                    "acted_at": (NOW - timedelta(days=4)).isoformat(),
                    "ticker": "SOLD.L",
                    "side": "sell",
                    "sizing_mode": "shares",
                    "shares": 5,
                    "price": 1.2,
                    "gross": 6,
                    "cost": 0.1,
                    "net_cash": 5.9,
                    "position_closed": True,
                    "name": "Sold PLC",
                }
            ],
            "equity_curve": [{"at": NOW.isoformat(), "portfolio_value": 1500}],
            "rebalance_state": {"exit_streak": {}, "reentry_cooldown": {}},
        },
    )
    payload = build_lifecycle_board(
        library_root=tmp_path / "library",
        paper_root=paper,
        shard_root=tmp_path / "shards",
        live_reports=live_reports,
        live_run_at=NOW.isoformat(),
        experiment_assessment={"experiments": []},
        now=NOW,
    )
    ftse = next(row for row in payload["markets"] if row["market_id"] == "ftse350")
    track = next(row for row in ftse["tracks"] if row["track_id"] == "buy_tier_level")
    columns = merge_track_columns(ftse["screen_columns"], track)
    tickers = {
        column_id: {card["ticker"] for card in columns[column_id]["shown"]}
        for column_id in BOARD_COLUMN_IDS
    }
    assert "HOLD.L" in tickers["just_bought"]
    assert "HOLD.L" not in tickers["near_buy"]
    assert "HOLD.L" not in tickers["not_now"]
    assert "WAIT.L" in tickers["not_now"]
    assert "NEAR.L" in tickers["near_buy"]
    assert "SKIP.L" in tickers["not_buy_tier"]
    assert "SOLD.L" in tickers["just_sold"]
    hold_card = next(card for card in columns["just_bought"]["shown"] if card["ticker"] == "HOLD.L")
    assert hold_card["days_in_column"] == 3
    assert hold_card["tenure_band"] == "fresh"
    assert hold_card["avg_cost"] == 1.0
    sold_card = next(card for card in columns["just_sold"]["shown"] if card["ticker"] == "SOLD.L")
    assert sold_card["days_in_column"] == 4
    assert sold_card["tenure_band"] == "fresh"
    wait_card = next(card for card in columns["not_now"]["shown"] if card["ticker"] == "WAIT.L")
    assert wait_card["days_in_column"] == 10
    assert wait_card["tenure_band"] == "recent"
    assert wait_card["tenure_basis"] == "signal_since"
    near_card = next(card for card in columns["near_buy"]["shown"] if card["ticker"] == "NEAR.L")
    assert near_card["days_in_column"] == 30
    assert near_card["tenure_band"] == "aging"
    assert "signal_since" in payload["tenure"]["note"]
    assert payload["tenure"]["long_days"] == 56
    seen: set[str] = set()
    for column_id, names in tickers.items():
        overlap = seen & names
        assert not overlap, f"{overlap} appears in {column_id} and an earlier column"
        seen.update(names)


def test_library_market_is_isolated_from_live(tmp_path: Path):
    library = tmp_path / "library"
    screen = library / "markets" / "sp500" / "screen"
    screen.mkdir(parents=True)
    (screen / "latest_signals.csv").write_text(
        "ticker,name,signal,timing_signal,conviction_score\n"
        "AAA,Alpha,buy,wait,0.6\n"
        "BBB,Beta,hold,neutral,0.4\n"
        "CCC,Gamma,avoid,wait,0.05\n",
        encoding="utf-8",
    )
    shard = tmp_path / "shards" / "sp500" / "buy_tier_level"
    shard.mkdir(parents=True)
    write_json(
        shard / "config.json",
        {"track_id": "buy_tier_level", "track_label": "S&P epoch-0", "is_cohort_lab": True},
    )
    write_json(
        shard / "automated_fund.json",
        {
            "config": {"max_positions": 20, "name": "SP"},
            "cash": 1000,
            "holdings": {
                "AAA": {
                    "ticker": "AAA",
                    "shares": 2,
                    "avg_cost": 10,
                    "opened_at": (NOW - timedelta(days=40)).isoformat(),
                }
            },
            "trades": [],
            "equity_curve": [{"at": NOW.isoformat(), "portfolio_value": 2000}],
            "rebalance_state": {"exit_streak": {}, "reentry_cooldown": {}},
        },
    )
    payload = build_lifecycle_board(
        library_root=library,
        paper_root=tmp_path / "paper",
        shard_root=tmp_path / "shards",
        live_reports=[{"ticker": "ZZZ.L", "signal": "buy", "timing_signal": "accumulate"}],
        now=NOW,
    )
    ids = [row["market_id"] for row in payload["markets"]]
    assert "ftse350" in ids
    assert "sp500" in ids
    sp500 = next(row for row in payload["markets"] if row["market_id"] == "sp500")
    cols = merge_track_columns(sp500["screen_columns"], sp500["tracks"][0])
    shown = {card["ticker"] for card in cols["growth"]["shown"]} | {
        card["ticker"] for card in cols["just_bought"]["shown"]
    }
    assert "AAA" in shown
    held = next(
        card
        for card in list(cols["growth"]["shown"]) + list(cols["just_bought"]["shown"])
        if card["ticker"] == "AAA"
    )
    assert held["days_in_column"] == 40
    assert held["tenure_band"] == "aging"
    assert "ZZZ.L" not in shown
    assert {card["ticker"] for card in cols["near_buy"]["shown"]} == {"BBB"}
    assert {card["ticker"] for card in cols["not_buy_tier"]["shown"]} == {"CCC"}


def test_not_buy_tier_is_truncated(tmp_path: Path):
    reports = [
        {
            "ticker": f"T{i:03d}.L",
            "signal": "avoid",
            "timing_signal": "wait",
            "conviction_score": 0.01 * i,
        }
        for i in range(COLUMN_SHOW_CAPS["not_buy_tier"] + 5)
    ]
    payload = build_lifecycle_board(
        library_root=tmp_path / "library",
        paper_root=tmp_path / "paper",
        shard_root=tmp_path / "shards",
        live_reports=reports,
        now=NOW,
    )
    ftse = next(row for row in payload["markets"] if row["market_id"] == "ftse350")
    col = merge_track_columns(ftse["screen_columns"], ftse["tracks"][0])["not_buy_tier"]
    assert col["count"] == len(reports)
    assert len(col["shown"]) == COLUMN_SHOW_CAPS["not_buy_tier"]
    assert col["truncated"] == 5


def test_write_lifecycle_board_roundtrip(tmp_path: Path):
    dest = tmp_path / "lifecycle_board.json"
    path = write_lifecycle_board(
        library_root=tmp_path / "library",
        paper_root=tmp_path / "paper",
        shard_root=tmp_path / "shards",
        live_reports=[{"ticker": "AAA.L", "signal": "hold", "conviction_score": 0.5}],
        path=dest,
        now=NOW,
    )
    assert path == dest
    payload = build_lifecycle_board(
        library_root=tmp_path / "library",
        paper_root=tmp_path / "paper",
        shard_root=tmp_path / "shards",
        live_reports=[{"ticker": "AAA.L", "signal": "hold", "conviction_score": 0.5}],
        now=NOW,
    )
    assert payload["schema_version"] == 1
    assert payload["observe_only"] is True
    assert [col["id"] for col in payload["columns"]] == list(BOARD_COLUMN_IDS)
    assert dest.exists()


def test_full_sleeve_uses_opened_at_heatmap(tmp_path: Path):
    live_reports = [
        {
            "ticker": "OLD.L",
            "name": "Old PLC",
            "signal": "buy",
            "timing_signal": "accumulate",
            "conviction_score": 0.7,
            "last_price": 10.0,
        }
    ]
    paper = tmp_path / "paper"
    btl = paper / "buy_tier_level"
    btl.mkdir(parents=True)
    write_json(
        btl / "config.json",
        {"track_id": "buy_tier_level", "is_cohort_lab": True, "max_positions": 2},
    )
    write_json(
        btl / "automated_fund.json",
        {
            "config": {"max_positions": 2},
            "cash": 0,
            "holdings": {
                "OLD.L": {
                    "ticker": "OLD.L",
                    "shares": 100,
                    "avg_cost": 10,
                    "opened_at": (NOW - timedelta(days=60)).isoformat(),
                }
            },
            "trades": [],
            "equity_curve": [{"at": NOW.isoformat(), "portfolio_value": 2000}],
            "rebalance_state": {"exit_streak": {}, "reentry_cooldown": {}},
        },
    )
    payload = build_lifecycle_board(
        library_root=tmp_path / "library",
        paper_root=paper,
        shard_root=tmp_path / "shards",
        live_reports=live_reports,
        now=NOW,
    )
    ftse = next(row for row in payload["markets"] if row["market_id"] == "ftse350")
    cols = merge_track_columns(ftse["screen_columns"], ftse["tracks"][0])
    card = next(row for row in cols["growth"]["shown"] if row["ticker"] == "OLD.L")
    assert card["days_in_column"] == 60
    assert card["tenure_band"] == "long"


def test_tenure_band_for_days_spans_eight_weeks():
    assert tenure_band_for_days(None) is None
    assert tenure_band_for_days(0) == "fresh"
    assert tenure_band_for_days(7) == "fresh"
    assert tenure_band_for_days(21) == "recent"
    assert tenure_band_for_days(42) == "aging"
    assert tenure_band_for_days(56) == "stale"
    assert tenure_band_for_days(57) == "long"


def test_tickers_on_lifecycle_board_collects_shown_and_occupied():
    board = {
        "markets": [
            {
                "market_id": "ftse350",
                "screen_columns": {
                    "not_buy_tier": {
                        "shown": [{"ticker": "HOLD.L"}, {"ticker": "HOLD.L"}],
                        "count": 1,
                    }
                },
                "tracks": [
                    {
                        "track_id": "rules",
                        "occupied_tickers": ["OWN.L"],
                        "position_columns": {
                            "just_bought": {"shown": [{"ticker": "NEW.L"}], "count": 1}
                        },
                    }
                ],
            }
        ]
    }
    assert tickers_on_lifecycle_board(board) == ["HOLD.L", "OWN.L", "NEW.L"]


def test_dashboard_lifecycle_opens_experiment_cards():
    app = Path("docs/app.js").read_text(encoding="utf-8")
    html = Path("docs/index.html").read_text(encoding="utf-8")
    css = Path("docs/styles.css").read_text(encoding="utf-8")
    charts = Path("docs/charts.js").read_text(encoding="utf-8")
    assert "function openLifecycleExperimentCard(factorId)" in app
    assert "function renderLifecycleExperimentCard(factorId)" in app
    assert "data-lifecycle-experiment" in app
    assert "lifecycleTenureLegend(board.tenure)" in app
    assert 'id="lifecycle-experiment-dialog"' in html
    assert ".lifecycle-card.tenure-long" in css
    assert ".lifecycle-init-box" in css
    assert "data-lifecycle-start" in app
    assert "lifecycle-experiment-start" in app
    assert "startLifecycleExperimentFromCard" in app
    assert ".lifecycle-evidence-list" in css
    assert ".lifecycle-start-btn" in css
    assert "function openLifecycleTickerCard(ticker)" in app
    assert "function renderLifecycleTickerCard(ticker)" in app
    assert "data-lifecycle-ticker" in app
    assert "data-lifecycle-chart-mount" in app
    assert 'id="lifecycle-ticker-dialog"' in html
    assert ".lifecycle-ticker-chart" in css
    assert (
        "async function mountPriceChart(body, report)" in charts
        or "async function mountPriceChart(body, report, overlays)" in charts
    )
    assert "await mountPriceChart(body, report)" in charts
    assert "levelToggleBound" in charts
    assert "function sortLifecycleCards(shown, mode, dir)" in app
    assert 'id="lifecycle-chip-sort"' in app
    assert "LIFECYCLE_CHIP_SORT_KEY" in app
    assert ".lifecycle-board-controls" in css
    assert 'id="lifecycle-chip-sort-dir"' in app
    assert "LIFECYCLE_CHIP_SORT_DIR_KEY" in app
    assert "resolveLifecycleChipSortDir" in app
    assert "sma50_series" in charts
    assert "book_cost" in charts
    assert "mergeChartLevels" in charts
    assert "async function mountPriceChart(body, report, overlays)" in charts
