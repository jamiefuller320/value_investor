"""Tests for legacy ii_coverage import path (Trading 212 north star aliases)."""

from __future__ import annotations

from pathlib import Path

from value_investor.data_library import empty_manifest, save_manifest
from value_investor.ii_coverage import (
    annotate_shortlist_rows,
    build_ii_overlays,
    classify_ticker,
    yahoo_suffix,
)
from value_investor.storage import write_json


def test_yahoo_suffix():
    assert yahoo_suffix("AAPL") == ""
    assert yahoo_suffix("SHEL.L") == ".L"
    assert yahoo_suffix("NDA-FI.HE") == ".HE"


def test_classify_online_phone_and_unknown(tmp_path: Path):
    ii_root = tmp_path / "library" / "ii_coverage"
    ii_root.mkdir(parents=True)
    write_json(
        ii_root / "policy.json",
        {
            "schema_version": 1,
            "as_of": "2026-07-18",
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
    write_json(ii_root / "exceptions.json", {"exceptions": {}}, compact=False)

    from value_investor import ii_coverage

    policy = ii_coverage.load_ii_policy(ii_root)
    exceptions = ii_coverage.load_ii_exceptions(ii_root)

    us = classify_ticker("AAPL", market_id="sp500", policy=policy, exceptions=exceptions)
    assert us["tradable_on_ii"] is True
    assert us["deal_channel"] == "online"
    assert us["confidence"] == "assumed"

    de = classify_ticker("SAP.DE", market_id="dax", policy=policy, exceptions=exceptions)
    assert de["tradable_on_ii"] is True
    assert de["ii_exchange"] == "Xetra"

    se = classify_ticker("VOLV-B.ST", market_id="euro_stoxx50", policy=policy, exceptions=exceptions)
    assert se["tradable_on_ii"] is False
    assert se["deal_channel"] == "phone"

    he = classify_ticker("NDA-FI.HE", market_id="euro_stoxx50", policy=policy, exceptions=exceptions)
    assert he["tradable_on_ii"] is False
    assert he["basis"] == "unknown_venue"


def test_build_overlays_and_exceptions(tmp_path: Path):
    root = tmp_path / "library"
    from value_investor.data_library import MARKET_REGISTRY

    # Minimal ii policy + exception
    ii_root = root / "ii_coverage"
    ii_root.mkdir(parents=True)
    write_json(
        ii_root / "policy.json",
        {
            "schema_version": 1,
            "as_of": "2026-07-18",
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
            "next_slices": [{"id": "aim", "label": "AIM", "priority": 1, "status": "candidate"}],
        },
        compact=False,
    )
    write_json(
        ii_root / "exceptions.json",
        {
            "exceptions": {
                "NDA-FI.HE": {
                    "tradable_on_ii": False,
                    "deal_channel": "n/a",
                    "ii_exchange": "Nasdaq Helsinki",
                    "confidence": "curated",
                    "basis": "exception",
                    "exception_reason": "Helsinki not on II list",
                }
            }
        },
        compact=False,
    )

    # Seed euro_stoxx50 manifest
    spec = MARKET_REGISTRY["euro_stoxx50"]
    manifest = empty_manifest(spec)
    manifest["tickers"] = ["SAP.DE", "MC.PA", "NDA-FI.HE"]
    manifest["ticker_count"] = 3
    save_manifest(root, "euro_stoxx50", manifest)

    summary = build_ii_overlays(root, markets=["euro_stoxx50"], write=True)
    stats = summary["markets"]["euro_stoxx50"]
    assert stats["ticker_count"] == 3
    assert stats["tradable_count"] == 2
    assert stats["curated_exception_count"] == 1
    assert (ii_root / "by_market" / "euro_stoxx50.csv").exists()
    assert (ii_root / "summary.json").exists()

    annotated = annotate_shortlist_rows(
        [{"ticker": "SAP.DE", "signal": "buy"}],
        market_id="euro_stoxx50",
        library_root=root,
    )
    assert annotated[0]["tradable_on_ii"] is True
    assert annotated[0]["ii_confidence"] == "assumed"
