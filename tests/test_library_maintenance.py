"""Tests for library filings re-ingest, failed-metric retry, and screen prune."""

from __future__ import annotations

from pathlib import Path

from value_investor.data_library import empty_manifest, save_manifest
from value_investor.library_maintenance import (
    _simplified_company_name,
    list_failed_metric_tickers,
    list_research_filings_targets,
    prune_library_screen_history,
    reingest_research_filings,
    retry_failed_metrics,
)
from value_investor.storage import write_json


def _seed_market(root: Path, market_id: str, tickers: list[str]) -> None:
    from value_investor.data_library import MARKET_REGISTRY, market_dir

    spec = MARKET_REGISTRY[market_id]
    manifest = empty_manifest(spec)
    manifest["tickers"] = tickers
    manifest["ticker_count"] = len(tickers)
    save_manifest(root, market_id, manifest)
    mdir = market_dir(root, market_id)
    (mdir / "constituents").mkdir(parents=True)
    write_json(
        mdir / "constituents" / "latest.json",
        [{"ticker": t, "name": f"Name {t}", "sector": "Tech"} for t in tickers],
        compact=True,
    )


def test_simplified_company_name_strips_legal_noise():
    assert _simplified_company_name("Compagnie de Saint-Gobain S.A.", "SGO.PA") == "Saint-Gobain"
    assert _simplified_company_name("Short", "AAA") is None


def test_list_and_reingest_unsupported_filings(tmp_path: Path, monkeypatch):
    root = tmp_path / "library"
    market = "asx200"
    ticker_dir = root / "markets" / market / "screen" / "research" / "AAA.AX"
    sources = ticker_dir / "sources"
    filings = sources / "filings"
    filings.mkdir(parents=True)
    write_json(
        ticker_dir / "research.json",
        {"ticker": "AAA.AX", "name": "Alpha ASX"},
        compact=True,
    )
    write_json(
        filings / "filings_index.json",
        {
            "ticker": "AAA.AX",
            "company_name": "Alpha ASX",
            "market": market,
            "regime": "unsupported",
            "filings": [],
        },
        compact=True,
    )
    # Supported memo should be skipped by default.
    ok_dir = root / "markets" / market / "screen" / "research" / "BBB.AX"
    ok_filings = ok_dir / "sources" / "filings"
    ok_filings.mkdir(parents=True)
    write_json(
        ok_dir / "research.json",
        {"ticker": "BBB.AX", "name": "Beta ASX"},
        compact=True,
    )
    write_json(
        ok_filings / "filings_index.json",
        {
            "ticker": "BBB.AX",
            "regime": "asx_announcements",
            "filings": [{"id": "x"}],
        },
        compact=True,
    )

    targets = list_research_filings_targets(root, [market], only_unsupported=True)
    assert [t["ticker"] for t in targets] == ["AAA.AX"]

    calls: list[dict] = []

    def fake_ingest(**kwargs):
        calls.append(kwargs)
        write_json(
            kwargs["sources_dir"] / "filings" / "filings_index.json",
            {
                "ticker": kwargs["ticker"],
                "company_name": kwargs["company_name"],
                "market": kwargs["market"],
                "regime": "asx_announcements",
                "summary": {"total": 2, "with_body": 1},
                "filings": [{"id": "1"}, {"id": "2"}],
            },
            compact=True,
        )
        return {
            "filings_regime": "asx_announcements",
            "filings_summary": {"total": 2, "with_body": 1},
        }

    monkeypatch.setattr(
        "value_investor.library_maintenance.ingest_filings",
        fake_ingest,
    )
    payload = reingest_research_filings(root, [market], only_unsupported=True)
    assert payload["target_count"] == 1
    assert calls[0]["company_name"] == "Alpha ASX"
    assert calls[0]["market"] == "asx200"
    assert payload["results"][0]["regime"] == "asx_announcements"


def test_retry_failed_metrics_only_errors(tmp_path: Path, monkeypatch):
    root = tmp_path / "library"
    market = "dax"
    _seed_market(root, market, ["AAA.DE", "BBB.DE"])
    metrics_dir = root / "markets" / market / "metrics"
    metrics_dir.mkdir(parents=True)
    write_json(
        metrics_dir / "latest.json.gz",
        [
            {"ticker": "AAA.DE", "market_cap": 1.0, "errors": ["boom"]},
            {"ticker": "BBB.DE", "market_cap": 2.0, "errors": []},
        ],
        compact=True,
        compress=True,
    )
    assert list_failed_metric_tickers(root, market) == ["AAA.DE"]

    fetched: list[str] = []

    def fake_fetch(ticker, name, sector):
        fetched.append(ticker)
        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "market_cap": 99.0,
            "trailing_pe": 10.0,
            "errors": [],
        }

    results = retry_failed_metrics(root, [market], fetch_fn=fake_fetch)
    assert fetched == ["AAA.DE"]
    assert results[0]["still_failed"] == []
    assert list_failed_metric_tickers(root, market) == []


def test_prune_library_screen_keeps_latest_and_n_runs(tmp_path: Path):
    root = tmp_path / "library"
    market = "nasdaq100"
    screen = root / "markets" / market / "screen"
    history = screen / "history"
    screen.mkdir(parents=True)
    history.mkdir(parents=True)

    for stamp in ("20260701_010101", "20260702_020202", "20260703_030303"):
        (screen / f"signals_{stamp}.csv").write_text("ticker\n", encoding="utf-8")
        (screen / f"model_results_{stamp}.csv").write_text("ticker\n", encoding="utf-8")
        (screen / f"universe_{stamp}.csv").write_text("ticker\n", encoding="utf-8")
        (screen / f"summary_{stamp}.json").write_text("{}", encoding="utf-8")
        (history / f"models_{stamp}.json.gz").write_bytes(b"x")

    (screen / "latest_signals.csv").write_text("ticker\n", encoding="utf-8")
    (screen / "latest_model_results.csv").write_text("ticker\n", encoding="utf-8")
    (screen / "signal_history.csv").write_text("ticker\n", encoding="utf-8")

    payload = prune_library_screen_history(root, markets=[market], keep_runs=2)
    assert payload["total_removed"] == 5  # 4 screen + 1 history for oldest stamp

    remaining = sorted(p.name for p in screen.iterdir() if p.is_file())
    assert "latest_signals.csv" in remaining
    assert "signal_history.csv" in remaining
    assert "signals_20260701_010101.csv" not in remaining
    assert "signals_20260702_020202.csv" in remaining
    assert "signals_20260703_030303.csv" in remaining
    hist_names = sorted(p.name for p in history.iterdir())
    assert hist_names == ["models_20260702_020202.json.gz", "models_20260703_030303.json.gz"]
