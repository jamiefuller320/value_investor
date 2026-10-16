"""FTSE 350 pound caps from stored prices, share counts, and repo FX."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.ftse_pound_cap import (
    SCREEN_PRICE_RUN_PREFIX,
    compute_ftse350_pound_caps,
    normalize_issuer_name,
)

ROOT = Path(__file__).resolve().parents[1]


def test_issuer_name_keeps_group_and_folds_plc():
    assert normalize_issuer_name("Unilever PLC") == normalize_issuer_name("Unilever PLC")
    assert normalize_issuer_name("Domino's Pizza Group plc") != normalize_issuer_name(
        "Domino's Pizza, Inc."
    )


def test_ftse350_pound_caps_cover_priced_names():
    rows = compute_ftse350_pound_caps(ROOT)
    assert len(rows) == 350
    computable = [row for row in rows if row.cap_gbp is not None]
    missing = [row for row in rows if row.cap_gbp is None]
    by_ticker = {row.ticker: row for row in rows}

    assert len(computable) == 250
    assert len(missing) == 100

    shel = by_ticker["SHEL.L"]
    assert shel.method == "price_x_financials_shares"
    assert shel.cap_gbp == 3793.5 * 5_689_891_670 / 100

    assert by_ticker["ULVR.L"].method == "price_x_same_name_shares"
    assert by_ticker["REL.L"].method == "price_x_same_name_shares"
    assert by_ticker["CCEP.L"].method == "price_x_same_name_shares"
    assert by_ticker["YNGA.L"].method == "price_x_same_name_shares"

    iag = by_ticker["IAG.L"]
    assert iag.method == "same_name_fx_cap"
    assert abs(iag.cap_gbp - 21_306_484_736 * 1.124 / 1.3317) < 1

    hmso = by_ticker["HMSO.L"]
    assert hmso.method == "same_name_fx_cap"
    assert abs(hmso.cap_gbp - 2_041_640_448 * 1.124 / 1.3317) < 1

    grow = by_ticker["GROW.L"]
    assert grow.method == "library_gbp_cap"
    assert grow.cap_gbp == 1_140_995_456

    for ticker in ("HSBA.L", "AZN.L", "BA.L", "CRDA.L", "PNN.L", "CPG.L"):
        assert by_ticker[ticker].cap_gbp is not None
        assert by_ticker[ticker].method == "price_x_sourced_shares"

    # Compass and IHG are quoted in USD, Baltic Classifieds and Metlen in EUR.
    # Dividing those prices by 100 would shrink the cap by 100.
    assert by_ticker["CPG.L"].cap_gbp > 10_000_000_000
    assert by_ticker["IHG.L"].cap_gbp > 5_000_000_000
    assert by_ticker["BCG.L"].cap_gbp > 100_000_000
    assert by_ticker["MTLN.L"].cap_gbp > 1_000_000_000

    pnn = by_ticker["PNN.L"]
    assert pnn.cap_gbp == 357.0 * 471_981_423 / 100

    for row in missing:
        assert row.method == "missing"
        assert row.ticker not in {"HSBA.L", "AZN.L", "GROW.L", "HMSO.L", "SHEL.L"}

    assert by_ticker["LAND.L"].cap_gbp is None
    assert by_ticker["SMT.L"].cap_gbp is None
    assert by_ticker["3IN.L"].cap_gbp is not None
    assert by_ticker["III.L"].cap_gbp is not None
    assert SCREEN_PRICE_RUN_PREFIX == "20261011"


def test_sourced_share_file_labels_every_figure():
    payload = json.loads((ROOT / "docs/data/ftse350_ordinary_shares.json").read_text())
    tickers = payload["tickers"]
    assert len(tickers) == 150
    for ticker, row in tickers.items():
        assert row["ordinary_shares"] > 0
        assert row["quote_currency"] in {"GBp", "USD", "EUR"}
        assert row["source"]
        assert row["source_url"].startswith("https://")
        assert ticker.endswith(".L")
    assert "RNS" in tickers["PNN.L"]["source"]
    assert "Financial Times" in tickers["CRDA.L"]["source"]
    assert "sharesOutstanding" in tickers["HSBA.L"]["source"]
    assert tickers["CPG.L"]["quote_currency"] == "USD"
    assert tickers["BCG.L"]["quote_currency"] == "EUR"
