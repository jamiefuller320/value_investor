"""L571 / hsr-v2: dividend yield percent→fraction at fetch and library load."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from value_investor.data_library import market_dir
from value_investor.historical_screen_replay import load_registration, screen_code_fingerprint
from value_investor.library_screen import load_library_metrics, normalize_metrics_dividend_yield
from value_investor.models.dividend import DividendGrowthModel, HighDividendYieldModel
from value_investor.models.neff import LowPEHighYieldModel, NeffPEGYModel
from value_investor.post_hsr_policy import _hsr_holdout_verdict
from value_investor.storage import write_json
from value_investor.trust_metrics import normalize_yield

pytestmark = pytest.mark.usefixtures("isolated_cwd")


def test_normalize_yield_percent_and_fraction():
    assert normalize_yield(2.5) == pytest.approx(0.025)
    assert normalize_yield(0.025) == pytest.approx(0.025)
    assert normalize_yield(None) is None


def test_normalize_metrics_frame_converts_yahoo_percent():
    frame = pd.DataFrame(
        {
            "ticker": ["A", "B", "C"],
            "dividend_yield": [2.5, 0.04, None],
        }
    )
    out = normalize_metrics_dividend_yield(frame)
    assert out["dividend_yield"].iloc[0] == pytest.approx(0.025)
    assert out["dividend_yield"].iloc[1] == pytest.approx(0.04)
    assert out["dividend_yield"].iloc[2] is None or pd.isna(out["dividend_yield"].iloc[2])


def test_load_library_metrics_normalises_percent_yield(tmp_path: Path):
    root = tmp_path / "library"
    rows = [
        {
            "ticker": "AAA",
            "trailing_pe": 10.0,
            "price_to_book": 1.0,
            "market_cap": 1e9,
            "dividend_yield": 3.0,  # Yahoo-style percent
        }
    ]
    write_json(market_dir(root, "sp500") / "metrics" / "latest.json.gz", rows, compress=True)
    write_json(
        market_dir(root, "sp500") / "manifest.json",
        {"tickers": ["AAA"], "ticker_count": 1},
    )
    frame = load_library_metrics(root, "sp500")
    assert frame.iloc[0]["dividend_yield"] == pytest.approx(0.03)


def test_dividend_floors_reject_percent_scale_without_normalisation():
    """Percent-scale yield clears the 3% floor; normalised fraction does not."""
    model = HighDividendYieldModel().fit(
        pd.DataFrame({"dividend_yield": [0.01, 0.02, 0.03, 0.04]})
    )
    assert HighDividendYieldModel.MIN_YIELD == 0.03
    assert 2.5 >= HighDividendYieldModel.MIN_YIELD
    assert normalize_yield(2.5) < HighDividendYieldModel.MIN_YIELD
    fixed = model.evaluate({"dividend_yield": normalize_yield(2.5), "trailing_pe": 12.0})
    assert not fixed.passed
    assert any("below" in f for f in fixed.failed_criteria)


def test_neff_pegy_uses_fraction_yield():
    pe, growth = 10.0, 0.10
    # Correct: PE / ((g + y) * 100) with y=0.025 → 10 / 12.5 = 0.8
    ok = NeffPEGYModel().evaluate(
        {"trailing_pe": pe, "earnings_growth": growth, "dividend_yield": 0.025}
    )
    assert bool(ok.passed)
    # Percent-as-fraction: y=2.5 → denominator huge → PEGY tiny → false pass
    buggy = NeffPEGYModel().evaluate(
        {"trailing_pe": pe, "earnings_growth": growth, "dividend_yield": 2.5}
    )
    assert bool(buggy.passed)
    assert "PEGY=" in buggy.reasons[0]
    # After normalisation the false pass goes away for a rich name
    rich = NeffPEGYModel().evaluate(
        {
            "trailing_pe": 40.0,
            "earnings_growth": 0.05,
            "dividend_yield": normalize_yield(2.5),
        }
    )
    assert not rich.passed


def test_low_pe_high_yield_floor_after_normalise():
    model = LowPEHighYieldModel()
    assert bool(model.evaluate({"trailing_pe": 8.0, "dividend_yield": 2.5}).passed)
    assert not model.evaluate({"trailing_pe": 8.0, "dividend_yield": normalize_yield(2.5)}).passed
    assert bool(model.evaluate({"trailing_pe": 8.0, "dividend_yield": 0.05}).passed)


def test_dividend_growth_floor_after_normalise():
    model = DividendGrowthModel()
    row = {"dividend_yield": normalize_yield(1.5), "earnings_growth": 0.05, "trailing_pe": 12.0}
    assert not model.evaluate(row).passed  # 1.5% < 2% floor


def test_hsr_v2_registration_matches_fingerprint_and_supersedes_v1():
    reg = load_registration()
    assert reg["registration_id"] == "hsr-v2"
    assert reg["screen_code_fingerprint"] == screen_code_fingerprint()
    assert "hsr-v1" in reg["supersedes"]


def test_post_hsr_reads_spent_epoch_verdict_not_empty_v2_slot():
    store = {
        "registration_id": "hsr-v2",
        "results": None,
        "spent_epochs": {
            "hsr-v1": {
                "registration_id": "hsr-v1",
                "results": {"horizons": {"30": {"holdout_verdict": "inconclusive"}}},
            }
        },
    }
    assert _hsr_holdout_verdict(store, spent_id="hsr-v1") == "inconclusive"
    assert _hsr_holdout_verdict({"results": None}, spent_id="hsr-v1") is None
