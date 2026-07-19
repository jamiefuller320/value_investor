"""Tests for progressive offline multi-market data libraries."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from value_investor.data_library import (
    MARKET_REGISTRY,
    PREQUALIFIED_YAHOO_MARKETS,
    _normalize_wiki_constituents,
    _pick_constituent_table,
    _select_refresh_tickers,
    apply_library_retention,
    empty_manifest,
    grow_library,
    library_status,
    load_manifest,
    refresh_constituents,
    refresh_metrics,
)

# Fixed "today" for retention tests (matches suite era).
_RETENTION_TODAY = date(2026, 7, 19)
from value_investor.data_library_cli import main as library_main
from value_investor.storage import read_json, write_json


def _fake_constituents(market_id: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": f"AAA{market_id[:2].upper()}",
                "name": "Alpha Co",
                "sector": "Tech",
                "epic": "AAA",
                "index": market_id,
                "market": market_id,
            },
            {
                "ticker": f"BBB{market_id[:2].upper()}",
                "name": "Beta Co",
                "sector": "Energy",
                "epic": "BBB",
                "index": market_id,
                "market": market_id,
            },
            {
                "ticker": f"CCC{market_id[:2].upper()}",
                "name": "Gamma Co",
                "sector": "Finance",
                "epic": "CCC",
                "index": market_id,
                "market": market_id,
            },
        ]
    )


def test_select_refresh_prefers_never_then_stale():
    now = datetime(2026, 7, 16, tzinfo=UTC)
    manifest = {
        "tickers": ["A", "B", "C", "D"],
        "ticker_state": {
            "B": {"last_refresh": (now - timedelta(days=30)).isoformat()},
            "C": {"last_refresh": (now - timedelta(days=1)).isoformat()},
            "D": {"last_refresh": (now - timedelta(days=10)).isoformat()},
        },
    }
    selected = _select_refresh_tickers(manifest, max_tickers=3, stale_days=7, now=now)
    assert selected == ["A", "B", "D"]


def test_refresh_constituents_writes_latest_and_dated(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(
        __import__("value_investor.data_library", fromlist=["CONSTITUENT_FETCHERS"]).CONSTITUENT_FETCHERS,
        "sp500",
        lambda: _fake_constituents("sp500"),
    )
    root = tmp_path / "library"
    manifest = refresh_constituents(root, "sp500")
    assert manifest["ticker_count"] == 3
    latest = read_json(root / "markets" / "sp500" / "constituents" / "latest.json")
    assert len(latest) == 3
    dated = list((root / "markets" / "sp500" / "constituents").glob("20*.json"))
    assert len(dated) == 1


def test_progressive_metrics_grow_and_status(tmp_path: Path, monkeypatch):
    from value_investor import data_library as dl

    monkeypatch.setitem(dl.CONSTITUENT_FETCHERS, "asx200", lambda: _fake_constituents("asx200"))

    def fake_fetch(ticker: str, name: str | None, sector: str | None):
        return SimpleNamespace(
            to_dict=lambda: {
                "ticker": ticker,
                "name": name,
                "sector": sector,
                "pe_ratio": 12.0,
                "price": 10.5,
                "errors": [],
            }
        )

    root = tmp_path / "library"
    first = refresh_metrics(
        root, "asx200", max_tickers=2, stale_days=7, fetch_fn=fake_fetch
    )
    assert first["updated"] == 2
    assert first["coverage_count"] == 2
    assert first["ticker_count"] == 3

    second = refresh_metrics(
        root, "asx200", max_tickers=2, stale_days=7, fetch_fn=fake_fetch
    )
    # Remaining never-fetched ticker plus one already covered (budget 2)
    assert second["coverage_count"] == 3
    assert len(second["selected"]) == 2

    status = library_status(root, markets=["asx200"], stale_days=7)
    assert status[0]["coverage_count"] == 3
    assert status[0]["never_fetched"] == 0
    assert status[0]["fresh"] == 3

    metrics = read_json(root / "markets" / "asx200" / "metrics" / "latest.json.gz")
    assert len(metrics) == 3


def test_grow_library_retention(tmp_path: Path, monkeypatch):
    from value_investor import data_library as dl

    monkeypatch.setitem(dl.CONSTITUENT_FETCHERS, "sp500", lambda: _fake_constituents("sp500"))

    def fake_fetch(ticker: str, name: str | None, sector: str | None):
        return {"ticker": ticker, "name": name, "sector": sector, "pe_ratio": 8.0}

    root = tmp_path / "library"
    grow_library(
        root,
        markets=["sp500"],
        max_tickers_per_run=10,
        refresh_constituents_first=True,
        retention_days=30,
        fetch_fn=fake_fetch,
    )

    metrics = root / "markets" / "sp500" / "metrics"
    # Same quarter beyond monthly window: keep newest only.
    older = metrics / "2020-01-01.json.gz"
    newer = metrics / "2020-03-15.json.gz"
    write_json(older, [{"ticker": "OLD"}], compact=True, compress=True)
    write_json(newer, [{"ticker": "NEWER"}], compact=True, compress=True)
    removed = apply_library_retention(
        root,
        keep_days=30,
        monthly_until_days=90,
        now=_RETENTION_TODAY,
    )
    assert removed >= 1
    assert not older.exists()
    assert newer.exists()
    assert (metrics / "latest.json.gz").exists()
    assert (root / "library_status.json").exists()


def test_tiered_library_retention_keeps_coarse_history(tmp_path: Path):
    root = tmp_path / "library"
    metrics = root / "markets" / "sp500" / "metrics"
    constituents = root / "markets" / "sp500" / "constituents"
    metrics.mkdir(parents=True)
    constituents.mkdir(parents=True)

    dense_a = metrics / "2026-07-10.json.gz"
    dense_b = metrics / "2026-07-01.json.gz"
    # monthly window: dense_cutoff=2026-06-19, monthly_cutoff=2025-06-14
    month_early = metrics / "2025-08-05.json.gz"
    month_late = metrics / "2025-08-28.json.gz"
    quarter_early = metrics / "2020-01-10.json.gz"
    quarter_late = metrics / "2020-02-20.json.gz"
    lone_quarter = metrics / "2019-08-01.json.gz"
    const_dup_a = constituents / "2020-01-05.json"
    const_dup_b = constituents / "2020-02-01.json"
    # Unrelated dated path must not be touched.
    other = root / "markets" / "sp500" / "screen" / "2020-01-01_run.json"
    other.parent.mkdir(parents=True)
    other.write_text("{}", encoding="utf-8")

    for path in (
        dense_a,
        dense_b,
        month_early,
        month_late,
        quarter_early,
        quarter_late,
        lone_quarter,
    ):
        write_json(path, [{"ticker": "X"}], compact=True, compress=True)
    write_json(const_dup_a, [{"ticker": "Y"}], compact=False)
    write_json(const_dup_b, [{"ticker": "Y"}], compact=False)

    removed = apply_library_retention(
        root,
        keep_days=30,
        monthly_until_days=400,
        now=_RETENTION_TODAY,
    )

    assert dense_a.exists() and dense_b.exists()
    assert not month_early.exists() and month_late.exists()
    assert not quarter_early.exists() and quarter_late.exists()
    assert lone_quarter.exists()  # sole quarterly anchor kept long-term
    assert not const_dup_a.exists() and const_dup_b.exists()
    assert other.exists()
    assert removed == 3


def test_empty_manifest_note_offline():
    note = empty_manifest(MARKET_REGISTRY["ftse350"])["note"]
    assert "not used by the live" in note.lower()


def test_euro_constituents_keep_yahoo_dots():
    from value_investor.data_library import _normalize_wiki_constituents

    table = pd.DataFrame(
        [
            {"Ticker": "ADS.DE", "Company": "Adidas", "Sector": "Consumer"},
            {"Ticker": "ASML.AS", "Company": "ASML", "Sector": "Tech"},
        ]
    )
    out = _normalize_wiki_constituents(
        table, market_id="euro_stoxx50", yahoo_suffix="", index_label="EURO STOXX 50"
    )
    assert list(out["ticker"]) == ["ADS.DE", "ASML.AS"]


def test_pick_constituent_table_prefers_code_listings():
    from value_investor.data_library import _pick_constituent_table

    small = pd.DataFrame({0: ["Foundation"], 1: ["2000"]})
    listing = pd.DataFrame(
        {
            "Code": ["BHP", "CBA"],
            "Company": ["BHP", "CBA"],
            "Sector": ["Materials", "Financials"],
        }
    )
    picked = _pick_constituent_table([small, listing])
    assert list(picked.columns) == ["Code", "Company", "Sector"]


def test_cli_list_and_status(tmp_path: Path, capsys):
    root = tmp_path / "library"
    assert library_main(["--root", str(root), "list"]) == 0
    out = capsys.readouterr().out
    assert "sp500" in out
    assert "Offline only" in out

    # Seed a minimal manifest for status
    manifest = empty_manifest(MARKET_REGISTRY["sp500"])
    manifest["tickers"] = ["AAA"]
    manifest["ticker_count"] = 1
    write_json(root / "markets" / "sp500" / "manifest.json", manifest, compact=False)
    assert library_main(["--root", str(root), "status", "--markets", "sp500"]) == 0
    status_out = capsys.readouterr().out
    assert "never_fetched=1" in status_out


def test_load_manifest_missing_is_empty(tmp_path: Path):
    manifest = load_manifest(tmp_path, "euro_stoxx50")
    assert manifest["ticker_count"] == 0
    assert manifest["market"] == "euro_stoxx50"


def test_ii_aligned_markets_registered():
    for mid in ("ftse_smallcap", "nasdaq100", "dax", "cac40", "tsx60"):
        assert mid in MARKET_REGISTRY
    assert "dax" in PREQUALIFIED_YAHOO_MARKETS
    assert "cac40" in PREQUALIFIED_YAHOO_MARKETS


def test_l34_next_slice_markets_registered():
    for mid in (
        "aim",
        "ibex35",
        "ftse_mib",
        "aex",
        "bel20",
        "hang_seng",
        "sti",
        "us_adr_asia",
    ):
        assert mid in MARKET_REGISTRY
    assert "ibex35" in PREQUALIFIED_YAHOO_MARKETS
    assert "bel20" in PREQUALIFIED_YAHOO_MARKETS


def test_hk_and_sg_yahoo_helpers():
    from value_investor.data_library import _to_hk_yahoo, _to_sg_yahoo, _to_bel_yahoo

    assert _to_hk_yahoo("SEHK: 5") == "0005.HK"
    assert _to_hk_yahoo("388") == "0388.HK"
    assert _to_sg_yahoo("SGX: A17U") == "A17U.SI"
    assert _to_bel_yahoo("Euronext Brussels:\xa0ABI") == "ABI.BR"


def test_normalize_keeps_prequalified_euro_tickers():
    table = pd.DataFrame(
        {"Ticker": ["ADS.DE", "AIR.PA"], "Company": ["Adidas", "Airbus"], "Sector": ["Consumer", "Industrials"]}
    )
    dax = _normalize_wiki_constituents(table, market_id="dax", yahoo_suffix="", index_label="DAX")
    assert list(dax["ticker"]) == ["ADS.DE", "AIR.PA"]


def test_normalize_tsx_appends_to_suffix():
    table = pd.DataFrame(
        {"Symbol": ["AEM", "BMO"], "Company": ["Agnico", "BMO"], "Sector": ["Materials", "Financials"]}
    )
    tsx = _normalize_wiki_constituents(table, market_id="tsx60", yahoo_suffix=".TO", index_label="TSX60")
    assert list(tsx["ticker"]) == ["AEM.TO", "BMO.TO"]


def test_pick_constituent_table_skips_multiindex_changelogs():
    listing = pd.DataFrame(
        {"Ticker": [f"T{i}" for i in range(100)], "Company": [f"Co{i}" for i in range(100)]}
    )
    changelog = pd.DataFrame(
        {
            ("Added", "Ticker"): ["X"],
            ("Added", "Security"): ["X Corp"],
            ("Removed", "Ticker"): ["Y"],
            ("Removed", "Security"): ["Y Corp"],
        }
    )
    # Force MultiIndex like Wikipedia Nasdaq change log
    changelog.columns = pd.MultiIndex.from_tuples(
        [("Added", "Ticker"), ("Added", "Security"), ("Removed", "Ticker"), ("Removed", "Security")]
    )
    picked = _pick_constituent_table([changelog, listing])
    assert list(picked.columns) == ["Ticker", "Company"]
    assert len(picked) == 100
