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
