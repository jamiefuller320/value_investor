"""Tests for observe-only buy-cross archive simulation."""

import json
from pathlib import Path

from value_investor.backtest import HISTORY_DIR
from value_investor.buy_cross_archive_sim import (
    COHORTS_FILENAME,
    REVIEW_FILENAME,
    BuyCrossArchiveConfig,
    run_buy_cross_archive_sim,
)


def _write_history_snapshot(
    output_dir: Path,
    filename: str,
    run_at: str,
    prices: dict[str, float],
    signals: list[dict],
) -> None:
    history = output_dir / HISTORY_DIR
    history.mkdir(parents=True, exist_ok=True)
    payload = {"run_at": run_at, "prices": prices, "signals": signals}
    (history / filename).write_text(json.dumps(payload), encoding="utf-8")


def _row(ticker: str, signal: str, price: float, *, conviction: float = 0.8) -> dict:
    return {
        "ticker": ticker,
        "signal": signal,
        "conviction_score": conviction,
        "timing_signal": "neutral",
        "price": price,
    }


def test_cross_skips_week0_and_never_enters_persistent_buy_tier(tmp_path: Path):
    sticky = _row("STICKY.L", "buy", 100.0)
    newbie = _row("NEW.L", "hold", 50.0)
    _write_history_snapshot(
        tmp_path,
        "run_20260101_100000.json",
        "2026-01-01T10:00:00+00:00",
        {"STICKY.L": 100.0, "NEW.L": 50.0, "^FTSE": 8000.0},
        [sticky, newbie],
    )
    newbie_buy = _row("NEW.L", "buy", 52.0)
    _write_history_snapshot(
        tmp_path,
        "run_20260108_100000.json",
        "2026-01-08T10:00:00+00:00",
        {"STICKY.L": 101.0, "NEW.L": 52.0, "^FTSE": 8050.0},
        [sticky, newbie_buy],
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260115_100000.json",
        "2026-01-15T10:00:00+00:00",
        {"STICKY.L": 102.0, "NEW.L": 55.0, "^FTSE": 8100.0},
        [sticky, newbie_buy],
    )

    review = run_buy_cross_archive_sim(tmp_path, config=BuyCrossArchiveConfig())
    assert review["snapshot_count"] == 3
    cross_weeks = review["cross"]["weekly"]
    assert cross_weeks[0]["holdings_count"] == 0
    assert cross_weeks[0]["cross_count"] == 0
    assert "NEW.L" in cross_weeks[1]["holdings"]
    assert "STICKY.L" not in cross_weeks[1]["holdings"]
    assert "STICKY.L" not in review["cross"]["final_holdings"]
    assert "NEW.L" in review["cross"]["final_holdings"]

    # Level comparison buys the full buy-tier from week 0, including the sticky name.
    level_weeks = review["level"]["weekly"]
    assert "STICKY.L" in level_weeks[0]["holdings"]
    assert "STICKY.L" in review["level"]["final_holdings"]

    assert (tmp_path / COHORTS_FILENAME).is_file()
    assert (tmp_path / REVIEW_FILENAME).is_file()


def test_cross_exits_after_two_screens_out_of_buy_tier(tmp_path: Path):
    buy = _row("FLIP.L", "buy", 10.0)
    hold = _row("FLIP.L", "hold", 10.0)
    _write_history_snapshot(
        tmp_path,
        "run_20260101_100000.json",
        "2026-01-01T10:00:00+00:00",
        {"FLIP.L": 10.0, "^FTSE": 8000.0},
        [_row("OTHER.L", "hold", 20.0)],
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260108_100000.json",
        "2026-01-08T10:00:00+00:00",
        {"FLIP.L": 10.0, "OTHER.L": 20.0, "^FTSE": 8000.0},
        [buy],
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260115_100000.json",
        "2026-01-15T10:00:00+00:00",
        {"FLIP.L": 11.0, "OTHER.L": 20.0, "^FTSE": 8000.0},
        [hold],
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260122_100000.json",
        "2026-01-22T10:00:00+00:00",
        {"FLIP.L": 12.0, "OTHER.L": 20.0, "^FTSE": 8000.0},
        [hold],
    )

    review = run_buy_cross_archive_sim(tmp_path, config=BuyCrossArchiveConfig())
    weeks = review["cross"]["weekly"]
    assert weeks[1]["holdings"] == ["FLIP.L"]
    # First week out of buy-tier: still held (exit buffer).
    assert "FLIP.L" in weeks[2]["holdings"]
    # Second consecutive week out: sold.
    assert "FLIP.L" not in weeks[3]["holdings"]
    assert weeks[3]["holdings_count"] == 0


def test_insufficient_history_is_not_ready(tmp_path: Path):
    review = run_buy_cross_archive_sim(tmp_path)
    assert review["readiness"]["ready_for_priors"] is False
    assert review["snapshot_count"] == 0
