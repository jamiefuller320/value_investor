"""Tests for Trading 212 coverage overlay + catalogue matching."""

from __future__ import annotations

from pathlib import Path

from value_investor.data_library import empty_manifest, save_manifest
from value_investor.storage import write_json
from value_investor.t212_coverage import (
    annotate_shortlist_rows,
    build_catalogue_index,
    build_t212_overlays,
    classify_ticker,
    match_catalogue,
    parse_t212_ticker,
    save_catalogue,
    yahoo_epic,
    yahoo_suffix,
)


def test_yahoo_helpers_and_parse_ticker():
    assert yahoo_suffix("AAPL") == ""
    assert yahoo_suffix("SHEL.L") == ".L"
    assert yahoo_epic("SHEL.L") == "SHEL"
    assert parse_t212_ticker("AAPL_US_EQ") == ("AAPL", "US", "EQ")
    assert parse_t212_ticker("VOD_LN_EQ") == ("VOD", "LN", "EQ")


def test_catalogue_match_by_isin_and_short_name():
    instruments = [
        {
            "ticker": "AAPL_US_EQ",
            "shortName": "AAPL",
            "isin": "US0378331005",
            "type": "STOCK",
            "currencyCode": "USD",
            "name": "Apple",
        },
        {
            "ticker": "SAP_DE_EQ",
            "shortName": "SAP",
            "isin": "DE0007164600",
            "type": "STOCK",
            "currencyCode": "EUR",
            "name": "SAP",
        },
        {
            "ticker": "SAP_US_EQ",
            "shortName": "SAP",
            "isin": "US8030542042",
            "type": "STOCK",
            "currencyCode": "USD",
            "name": "SAP ADR",
        },
    ]
    index = build_catalogue_index(instruments)
    policy = {"yahoo_suffix_to_t212_exchanges": {"": ["US"], ".DE": ["DE"]}}

    by_isin = match_catalogue(
        "AAPL", isin="US0378331005", index=index, policy=policy
    )
    assert by_isin is not None
    assert by_isin["ticker"] == "AAPL_US_EQ"

    de = match_catalogue("SAP.DE", index=index, policy=policy)
    assert de is not None
    assert de["ticker"] == "SAP_DE_EQ"

    us = match_catalogue("SAP", index=index, policy=policy)
    assert us is not None
    assert us["ticker"] == "SAP_US_EQ"


def test_classify_prefers_catalogue_then_allowlist(tmp_path: Path):
    root = tmp_path / "library"
    t212 = root / "t212_coverage"
    t212.mkdir(parents=True)
    write_json(
        t212 / "policy.json",
        {
            "schema_version": 2,
            "broker": "trading212",
            "as_of": "2026-07-22",
            "exchanges": [
                {
                    "ii_label": "United States",
                    "venues": ["NYSE", "NASDAQ"],
                    "yahoo_suffixes": [""],
                    "online_dealable": True,
                    "phone_only": False,
                },
                {
                    "ii_label": "Germany",
                    "venues": ["Xetra"],
                    "yahoo_suffixes": [".DE"],
                    "online_dealable": True,
                    "phone_only": False,
                },
                {
                    "ii_label": "Sweden",
                    "venues": ["Nasdaq Stockholm"],
                    "yahoo_suffixes": [".ST"],
                    "online_dealable": False,
                    "phone_only": True,
                },
            ],
            "market_defaults": {},
            "next_slices": [],
        },
        compact=False,
    )
    write_json(t212 / "exceptions.json", {"exceptions": {}}, compact=False)
    save_catalogue(
        [
            {
                "ticker": "AAPL_US_EQ",
                "shortName": "AAPL",
                "isin": "US0378331005",
                "type": "STOCK",
                "currencyCode": "USD",
            }
        ],
        library_root=root,
        env="demo",
        source="fixture",
    )

    from value_investor import t212_coverage

    policy = t212_coverage.load_t212_policy(t212)
    exceptions = t212_coverage.load_t212_exceptions(t212)
    index = t212_coverage.load_catalogue_index(root)

    us = classify_ticker(
        "AAPL",
        market_id="sp500",
        policy=policy,
        exceptions=exceptions,
        catalogue_index=index,
    )
    assert us["tradable_on_t212"] is True
    assert us["tradable_on_ii"] is True
    assert us["broker_basis"] == "catalogue_hit"
    assert us["broker_confidence"] == "verified"
    assert us["t212_ticker"] == "AAPL_US_EQ"

    de = classify_ticker(
        "SAP.DE",
        market_id="dax",
        policy=policy,
        exceptions=exceptions,
        catalogue_index=index,
    )
    assert de["tradable_on_t212"] is True
    assert de["broker_basis"] == "exchange_allowlist"
    assert de["broker_confidence"] == "assumed"

    se = classify_ticker(
        "VOLV-B.ST",
        market_id="euro_stoxx50",
        policy=policy,
        exceptions=exceptions,
        catalogue_index=index,
    )
    assert se["tradable_on_t212"] is False
    assert se["deal_channel"] == "phone"


def test_build_overlays_catalogue_and_exceptions(tmp_path: Path):
    root = tmp_path / "library"
    from value_investor.data_library import MARKET_REGISTRY

    t212 = root / "t212_coverage"
    t212.mkdir(parents=True)
    write_json(
        t212 / "policy.json",
        {
            "schema_version": 2,
            "as_of": "2026-07-22",
            "exchanges": [
                {
                    "ii_label": "Germany",
                    "venues": ["Xetra"],
                    "yahoo_suffixes": [".DE"],
                    "online_dealable": True,
                    "phone_only": False,
                },
                {
                    "ii_label": "France",
                    "venues": ["Euronext Paris"],
                    "yahoo_suffixes": [".PA"],
                    "online_dealable": True,
                    "phone_only": False,
                },
            ],
            "market_defaults": {},
            "next_slices": [{"id": "t212_catalogue", "status": "ready"}],
        },
        compact=False,
    )
    write_json(
        t212 / "exceptions.json",
        {
            "exceptions": {
                "NDA-FI.HE": {
                    "tradable_on_t212": False,
                    "deal_channel": "n/a",
                    "t212_exchange": "Nasdaq Helsinki",
                    "confidence": "curated",
                    "basis": "exception",
                    "exception_reason": "curated non-tradable",
                }
            }
        },
        compact=False,
    )
    save_catalogue(
        [
            {
                "ticker": "SAP_DE_EQ",
                "shortName": "SAP",
                "isin": "DE0007164600",
                "type": "STOCK",
                "currencyCode": "EUR",
            }
        ],
        library_root=root,
        env="demo",
        source="fixture",
    )

    spec = MARKET_REGISTRY["euro_stoxx50"]
    manifest = empty_manifest(spec)
    manifest["tickers"] = ["SAP.DE", "MC.PA", "NDA-FI.HE"]
    manifest["ticker_count"] = 3
    save_manifest(root, "euro_stoxx50", manifest)

    summary = build_t212_overlays(root, markets=["euro_stoxx50"], write=True)
    stats = summary["markets"]["euro_stoxx50"]
    assert stats["ticker_count"] == 3
    assert stats["tradable_count"] == 2
    assert stats["catalogue_hit_count"] == 1
    assert stats["curated_exception_count"] == 1
    assert (t212 / "by_market" / "euro_stoxx50.csv").exists()
    assert (t212 / "summary.json").exists()

    annotated = annotate_shortlist_rows(
        [{"ticker": "SAP.DE", "signal": "buy"}],
        market_id="euro_stoxx50",
        library_root=root,
    )
    assert annotated[0]["tradable_on_t212"] is True
    assert annotated[0]["ii_tradable"] is True
    assert annotated[0]["broker_basis"] == "catalogue_hit"
