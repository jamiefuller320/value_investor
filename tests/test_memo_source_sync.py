"""Tests for committed ↔ output research source sync helpers."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.research.memo_backfill import (
    sync_committed_memos_to_output,
    sync_committed_sources_to_output,
    sync_output_research_to_committed,
)


def test_sync_committed_sources_to_output_copies_filings(tmp_path: Path):
    data_dir = tmp_path / "docs_data"
    committed = data_dir / "research" / "AAA.L" / "sources" / "filings"
    committed.mkdir(parents=True)
    (committed / "filings_index.json").write_text('{"summary":{"with_body":3}}', encoding="utf-8")
    body = committed / "bodies"
    body.mkdir()
    (body / "a.txt").write_text("annual accounts", encoding="utf-8")

    output_dir = tmp_path / "output"
    synced = sync_committed_sources_to_output(output_dir, data_dir=data_dir)
    assert synced == 1
    dest = output_dir / "research" / "AAA.L" / "sources" / "filings" / "bodies" / "a.txt"
    assert dest.read_text(encoding="utf-8") == "annual accounts"


def test_sync_committed_sources_to_output_filters_tickers(tmp_path: Path):
    data_dir = tmp_path / "docs_data"
    for ticker in ("AAA.L", "BBB.L"):
        sources = data_dir / "research" / ticker / "sources"
        sources.mkdir(parents=True)
        (sources / "news_manifest.json").write_text("{}", encoding="utf-8")

    output_dir = tmp_path / "output"
    synced = sync_committed_sources_to_output(output_dir, data_dir=data_dir, tickers=["BBB.L"])
    assert synced == 1
    assert (output_dir / "research" / "BBB.L" / "sources" / "news_manifest.json").exists()
    assert not (output_dir / "research" / "AAA.L").exists()


def test_sync_committed_memos_to_output_seeds_research_json(tmp_path: Path):
    data_dir = tmp_path / "docs_data"
    ticker_dir = data_dir / "research" / "CCC.L"
    ticker_dir.mkdir(parents=True)
    (ticker_dir / "research.json").write_text(
        json.dumps({"ticker": "CCC.L", "mode": "initial", "research_verdict": "accumulate"}),
        encoding="utf-8",
    )
    (ticker_dir / "research.md").write_text("# CCC\n", encoding="utf-8")
    # Sources-only tickers must not count as memo seeds.
    sources_only = data_dir / "research" / "DDD.L" / "sources"
    sources_only.mkdir(parents=True)
    (sources_only / "news_manifest.json").write_text("{}", encoding="utf-8")

    output_dir = tmp_path / "output"
    synced = sync_committed_memos_to_output(output_dir, data_dir=data_dir)
    assert synced == 1
    seeded = json.loads((output_dir / "research" / "CCC.L" / "research.json").read_text())
    assert seeded["mode"] == "initial"
    assert (output_dir / "research" / "CCC.L" / "research.md").exists()
    assert not (output_dir / "research" / "DDD.L").exists()


def test_sync_output_research_to_committed_round_trip(tmp_path: Path):
    output_dir = tmp_path / "output"
    data_dir = tmp_path / "docs_data"
    out_ticker = output_dir / "research" / "EEE.L"
    out_ticker.mkdir(parents=True)
    payload = {"ticker": "EEE.L", "mode": "structured_verdict_update", "research_verdict": "neutral"}
    (out_ticker / "research.json").write_text(json.dumps(payload), encoding="utf-8")
    (out_ticker / "research.md").write_text("# EEE structured\n", encoding="utf-8")

    synced = sync_output_research_to_committed(output_dir, data_dir=data_dir, tickers=["EEE.L"])
    assert synced == 1
    committed = json.loads((data_dir / "research" / "EEE.L" / "research.json").read_text())
    assert committed["mode"] == "structured_verdict_update"
