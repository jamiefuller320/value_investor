"""Tests for committed ↔ output research source sync helpers."""

from __future__ import annotations

from pathlib import Path

from value_investor.research.memo_backfill import sync_committed_sources_to_output


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
    synced = sync_committed_sources_to_output(
        output_dir, data_dir=data_dir, tickers=["BBB.L"]
    )
    assert synced == 1
    assert (output_dir / "research" / "BBB.L" / "sources" / "news_manifest.json").exists()
    assert not (output_dir / "research" / "AAA.L").exists()
