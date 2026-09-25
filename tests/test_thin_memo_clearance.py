"""Thin-memo so-what clearance rollup and ingest pin augmentation."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.library_ingest_loop import (
    _augment_reports_for_pin_tickers,
)
from value_investor.summary import CompanyReport
from value_investor.thin_memo_clearance import (
    THIN_MEMO_FLAG_ID,
    build_thin_memo_clearance_status,
    render_thin_memo_clearance_markdown,
)


def test_build_thin_memo_clearance_status_euro_depth(tmp_path: Path):
    library = tmp_path / "library"
    market = "euro_depth"
    for idx in range(6):
        ticker = f"ZZ{idx}.PA"
        research = library / "markets" / market / "screen" / "research" / ticker
        research.mkdir(parents=True)
        (research / "research.json").write_text(
            json.dumps(
                {
                    "ticker": ticker,
                    "name": f"Thin Zero {idx}",
                    "signal": "buy",
                    "mode": "initial",
                    "memo_quality": {"grade": "adequate", "filings_with_body": 0},
                    "source_counts": {"filings_with_body": 0},
                }
            ),
            encoding="utf-8",
        )
    (library / "policy.json").write_text(
        json.dumps({"focus_market": market, "ladder": {"focus_market": market}}),
        encoding="utf-8",
    )
    (library / "last_ladder.json").write_text(
        json.dumps({"focus_market": market, "layers": {}, "plan": {}}),
        encoding="utf-8",
    )
    data = tmp_path / "data"
    data.mkdir()
    (data / "system_gaps.json").write_text(
        json.dumps(
            {
                "flags": [
                    {
                        "id": THIN_MEMO_FLAG_ID,
                        "severity": "medium",
                        "layer": "produce",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    status = build_thin_memo_clearance_status(data_dir=data, library_root=library)
    assert status["market_id"] == market
    assert status["zero_body_target_count"] >= 1
    assert "ZZ0.PA" in (status.get("zero_body_tickers") or [])
    assert status["cleared"] is False
    md = render_thin_memo_clearance_markdown(status)
    assert "deepen-thin" in md
    assert THIN_MEMO_FLAG_ID in md or "thin" in md.lower()


def test_deepen_thin_cli_defaults_root():
    """deepen-thin must inherit --root so thin-memo-clearance --run-deepen works."""
    from value_investor.data_library_cli import build_parser

    args = build_parser().parse_args(["deepen-thin", "--markets", "euro_depth"])
    assert hasattr(args, "root")
    assert str(args.root).endswith("library") or "library" in str(args.root)


def test_sanitize_http_url_quotes_spaces():
    from value_investor.research.filings import _sanitize_http_url

    raw = (
        "https://filings.xbrl.org/549300WSX3VBUFFJOO66/2024-12-31/ESEF/NL/0/"
        "Netherlands ESEF/reports/file.xhtml"
    )
    cleaned = _sanitize_http_url(raw)
    assert " " not in cleaned
    assert "Netherlands%20ESEF" in cleaned


def test_run_thin_memo_factory_heal_deepens_zero_body(tmp_path: Path, monkeypatch):
    library = tmp_path / "library"
    market = "euro_depth"
    ticker = "ZZ0.PA"
    research = library / "markets" / market / "screen" / "research" / ticker
    (research / "sources").mkdir(parents=True)
    (research / "research.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "name": "Thin Zero",
                "signal": "buy",
                "mode": "initial",
                "memo_quality": {"grade": "thin", "filings_with_body": 0},
                "source_counts": {"filings_with_body": 0},
            }
        ),
        encoding="utf-8",
    )
    (library / "policy.json").write_text(
        json.dumps({"focus_market": market, "ladder": {"focus_market": market}}),
        encoding="utf-8",
    )
    (library / "last_ladder.json").write_text(
        json.dumps({"focus_market": market, "layers": {}, "plan": {}}),
        encoding="utf-8",
    )
    data = tmp_path / "data"
    data.mkdir()
    (data / "system_gaps.json").write_text(json.dumps({"flags": []}), encoding="utf-8")

    calls: list[dict] = []

    def _fake_deepen(root, targets, **kwargs):
        calls.append({"targets": [t["ticker"] for t in targets], **kwargs})
        # Simulate body landing on disk so rememo_pending can see it.
        bodies = research / "sources" / "filings" / "bodies"
        bodies.mkdir(parents=True, exist_ok=True)
        (bodies / "body_1.txt").write_text("annual report " * 50, encoding="utf-8")
        return {
            "target_count": len(targets),
            "deepened": len(targets),
            "rememoed": 0,
            "errors": [],
            "results": [],
        }

    monkeypatch.setattr(
        "value_investor.library_maintenance.deepen_library_research_memos",
        _fake_deepen,
    )
    from value_investor.thin_memo_clearance import run_thin_memo_factory_heal

    heal = run_thin_memo_factory_heal(
        data_dir=data,
        library_root=library,
        apply_deepen=True,
        apply_rememo=False,
        refresh_system_gaps=False,
    )
    assert calls
    assert ticker in calls[0]["targets"]
    assert calls[0]["rememo_when_improved"] is False
    assert heal["market_id"] == market
    assert heal["deepen"]["deepened"] == 1


def test_augment_reports_for_pin_tickers_off_shortlist(tmp_path: Path):

    library = tmp_path / "library"
    market = "euro_depth"
    ticker_dir = library / "markets" / market / "screen" / "research" / "BN.PA"
    ticker_dir.mkdir(parents=True)
    (ticker_dir / "research.json").write_text(
        json.dumps({"ticker": "BN.PA", "name": "Danone S.A.", "signal": "buy"}),
        encoding="utf-8",
    )
    (library / "markets" / market / "screen").mkdir(parents=True, exist_ok=True)
    (library / "markets" / market / "screen" / "latest.json").write_text("{}", encoding="utf-8")

    base = [
        CompanyReport(
            ticker="ACKB.BR",
            name="Ack",
            sector=None,
            signal="buy",
            models_passed=0,
            model_count=0,
            composite_score=None,
            sector_composite_score=None,
            families_passed=0,
            passed_families=None,
            data_quality_score=0.0,
            metrics_present=0,
            metrics_total=0,
            weeks_at_signal=0,
            signal_trend="unknown",
            conviction_score=0.5,
            stability_label="unknown",
            timing_signal="unknown",
            timing_score=0.0,
            rsi_14=None,
            price_vs_sma200_pct=None,
            action_note="",
            trade_plan=None,
            summary="",
            passed_models=[],
            key_metrics={},
        )
    ]
    merged = _augment_reports_for_pin_tickers(
        base,
        pin_tickers=["BN.PA"],
        library_root=library,
        market_id=market,
    )
    tickers = {row.ticker for row in merged}
    assert "BN.PA" in tickers
