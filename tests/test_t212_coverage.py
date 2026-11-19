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

    by_isin = match_catalogue("AAPL", isin="US0378331005", index=index, policy=policy)
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


def test_assess_alignment_with_catalogue(tmp_path: Path):
    root = tmp_path / "library"
    from value_investor.data_library import MARKET_REGISTRY, empty_manifest, save_manifest
    from value_investor.t212_coverage import assess_t212_alignment, save_catalogue

    t212 = root / "t212_coverage"
    t212.mkdir(parents=True)
    write_json(
        t212 / "policy.json",
        {
            "schema_version": 2,
            "exchanges": [
                {
                    "yahoo_suffixes": [".DE"],
                    "venues": ["Xetra"],
                    "online_dealable": True,
                    "phone_only": False,
                }
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
    manifest["tickers"] = ["SAP.DE", "MC.PA"]
    manifest["ticker_count"] = 2
    save_manifest(root, "euro_stoxx50", manifest)

    report = assess_t212_alignment(root, markets=["euro_stoxx50"], write=True)
    assert report["catalogue_loaded"] is True
    assert report["markets"][0]["catalogue_hit_count"] == 1
    assert (t212 / "alignment_report.json").exists()


def test_t212_venue_reads_both_ticker_styles():
    from value_investor.t212_coverage import t212_venue

    assert t212_venue("AAPL_US_EQ") == "US"
    assert t212_venue("TPR_EQ_US") == "US"
    assert t212_venue("SHOP_CA_EQ") == "CA"
    assert t212_venue("VODl_EQ") == "LSE"
    assert t212_venue("BIRG1l_EQ") == "LSE"
    assert t212_venue("BAYNd_EQ") == "DE"
    assert t212_venue("ABNa_EQ") == "AS"
    assert t212_venue("ABBNsEQ") == "SW"
    assert t212_venue("weird") is None


def _cross_venue_index():
    return build_catalogue_index(
        [
            # Same short names as ASX / TSX / LSE names, different companies.
            {"ticker": "CSL_US_EQ", "shortName": "CSL", "isin": "US1423391002", "type": "STOCK"},
            {"ticker": "T_US_EQ", "shortName": "T", "isin": "US00206R1023", "type": "STOCK"},
            {"ticker": "ABC_US_EQ", "shortName": "ABC", "isin": "US03073E1055", "type": "STOCK"},
            {"ticker": "VODl_EQ", "shortName": "VOD", "isin": "GB00BH4HKS39", "type": "STOCK"},
            {"ticker": "BAYNd_EQ", "shortName": "BAYN", "isin": "DE000BAY0017", "type": "STOCK"},
            # Eni trades on T212 only on a Brussels line, same ISIN as Milan.
            {
                "ticker": "ENI_BE_EQ",
                "shortName": "ENI",
                "isin": "IT0003132476",
                "type": "STOCK",
                "name": "Eni",
            },
        ]
    )


def test_short_name_on_another_venue_is_not_a_match():
    from value_investor.t212_coverage import DEFAULT_SUFFIX_EXCHANGES

    index = _cross_venue_index()
    policy = {"yahoo_suffix_to_t212_exchanges": DEFAULT_SUFFIX_EXCHANGES}
    assert match_catalogue("CSL.AX", index=index, policy=policy) is None
    assert match_catalogue("T.TO", index=index, policy=policy) is None
    assert match_catalogue("ABC.L", index=index, policy=policy) is None


def test_short_name_on_own_venue_and_isin_on_any_venue_match():
    from value_investor.t212_coverage import DEFAULT_SUFFIX_EXCHANGES

    index = _cross_venue_index()
    policy = {"yahoo_suffix_to_t212_exchanges": DEFAULT_SUFFIX_EXCHANGES}
    assert match_catalogue("VOD.L", index=index, policy=policy)["ticker"] == "VODl_EQ"
    assert match_catalogue("BAYN.DE", index=index, policy=policy)["ticker"] == "BAYNd_EQ"
    eni = match_catalogue("ENI.MI", isin="IT0003132476", index=index, policy=policy)
    assert eni["ticker"] == "ENI_BE_EQ"


def test_short_name_on_another_venue_matches_with_home_country_isin():
    from value_investor.t212_coverage import DEFAULT_SUFFIX_EXCHANGES

    index = _cross_venue_index()
    policy = {"yahoo_suffix_to_t212_exchanges": DEFAULT_SUFFIX_EXCHANGES}
    eni = match_catalogue("ENI.MI", index=index, policy=policy, name="Eni S.p.A.")
    assert eni["ticker"] == "ENI_BE_EQ"
    # No name to confirm it, or a Swiss namesake: not a hit.
    assert match_catalogue("ENI.MI", index=index, policy=policy) is None
    assert match_catalogue("ENI.SW", index=index, policy=policy, name="Eni") is None


def test_home_country_isin_still_needs_the_company_name():
    from value_investor.t212_coverage import DEFAULT_SUFFIX_EXCHANGES

    index = build_catalogue_index(
        [
            # Australian-registered, listed in London as ALL; not Aristocrat Leisure.
            {
                "ticker": "IRRl_EQ",
                "shortName": "ALL",
                "isin": "AU0000237554",
                "type": "STOCK",
                "name": "Atlantic Lithium",
            },
            {
                "ticker": "BLTl_EQ",
                "shortName": "BHP",
                "isin": "AU000000BHP4",
                "type": "STOCK",
                "name": "BHP Group",
            },
        ]
    )
    policy = {"yahoo_suffix_to_t212_exchanges": DEFAULT_SUFFIX_EXCHANGES}
    assert match_catalogue("ALL.AX", index=index, policy=policy, name="Aristocrat Leisure") is None
    bhp = match_catalogue("BHP.AX", index=index, policy=policy, name="BHP Group Ltd")
    assert bhp["ticker"] == "BLTl_EQ"


def test_venue_letter_is_not_part_of_the_symbol():
    from value_investor.t212_coverage import DEFAULT_SUFFIX_EXCHANGES, t212_symbol

    assert t212_symbol("BNp_EQ") == "BN"
    assert t212_symbol("AAPL_US_EQ") == "AAPL"
    assert t212_symbol("BIRG1l_EQ") == "BIRG1"
    index = build_catalogue_index(
        [{"ticker": "BNp_EQ", "shortName": "BN", "isin": "FR0000120644", "type": "STOCK"}]
    )
    # An index built before the fix filed Danone under "BNP" as well.
    index["by_short_name"]["BNP"] = ["BNp_EQ"]
    policy = {"yahoo_suffix_to_t212_exchanges": DEFAULT_SUFFIX_EXCHANGES}
    assert match_catalogue("BNP.PA", index=index, policy=policy) is None
    assert match_catalogue("BN.PA", index=index, policy=policy)["ticker"] == "BNp_EQ"


def test_catalogue_hit_keeps_our_isin(tmp_path: Path):
    from value_investor.t212_coverage import DEFAULT_SUFFIX_EXCHANGES

    row = classify_ticker(
        "ENI.MI",
        market_id="ftse_mib",
        isin="IT0003132476",
        policy={"yahoo_suffix_to_t212_exchanges": DEFAULT_SUFFIX_EXCHANGES, "exchanges": []},
        exceptions={},
        catalogue_index=_cross_venue_index(),
    )
    assert row["broker_basis"] == "catalogue_hit"
    assert row["isin"] == "IT0003132476"
    assert row["t212_ticker"] == "ENI_BE_EQ"


def test_default_overlay_covers_ftse350_from_screen_snapshot(tmp_path: Path):
    import gzip
    import json

    root = tmp_path / "library"
    t212 = root / "t212_coverage"
    t212.mkdir(parents=True)
    write_json(
        t212 / "policy.json",
        {"schema_version": 2, "as_of": "2026-07-22", "exchanges": [], "market_defaults": {}},
        compact=False,
    )
    write_json(t212 / "exceptions.json", {"exceptions": {}}, compact=False)
    save_catalogue(
        [{"ticker": "VODl_EQ", "shortName": "VOD", "isin": "GB00BH4HKS39", "type": "STOCK"}],
        library_root=root,
        env="demo",
        source="fixture",
    )
    history = tmp_path / "history"
    history.mkdir()
    with gzip.open(history / "run_20261101_073321.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(
            {"run_at": "2026-11-01", "signals": [{"ticker": "VOD.L"}, {"ticker": "ZZZ.L"}]}, fh
        )

    summary = build_t212_overlays(root, write=True)
    stats = summary["markets"]["ftse350"]
    assert stats["ticker_count"] == 2
    assert stats["catalogue_hit_count"] == 1
    assert (t212 / "by_market" / "ftse350.json").exists()


def _name_join_index():
    return build_catalogue_index(
        [
            {
                "ticker": "ENL1d_EQ",
                "shortName": "ENL",
                "isin": "IT0003128367",
                "type": "STOCK",
                "name": "Enel",
            },
            {
                "ticker": "ENIC_US_EQ",
                "shortName": "ENIC",
                "isin": "US29278D1054",
                "type": "STOCK",
                "name": "Enel Chile",
            },
            {
                "ticker": "RACE_US_EQ",
                "shortName": "RACE",
                "isin": "NL0011585146",
                "type": "STOCK",
                "name": "Ferrari",
            },
            {
                "ticker": "FERGRa_EQ",
                "shortName": "FERGR",
                "isin": "GB00BN0VZ646",
                "type": "STOCK",
                "name": "Ferrari Group",
            },
            {
                "ticker": "04Qd_EQ",
                "shortName": "04Q",
                "isin": "FI4000297767",
                "type": "STOCK",
                "name": "Nordea Bank",
            },
            {
                "ticker": "NRDBY_US_EQ",
                "shortName": "NRDBY",
                "isin": "US65558R1095",
                "type": "STOCK",
                "name": "Nordea Bank",
            },
            {
                "ticker": "STMpp_EQ",
                "shortName": "STMPA",
                "isin": "NL0000226223",
                "type": "STOCK",
                "name": "STMicroelectronics",
            },
            {
                "ticker": "STMd_EQ",
                "shortName": "STM",
                "isin": "DE000STAB1L8",
                "type": "STOCK",
                "name": "Stabilus",
            },
            {
                "ticker": "SGJHd_EQ",
                "shortName": "SGJH",
                "isin": "CNE1000004C8",
                "type": "STOCK",
                "name": "Sinopec Shanghai Petrochemical",
            },
            {
                "ticker": "BRSTd_EQ",
                "shortName": "BRST",
                "isin": "US1111111111",
                "type": "STOCK",
                "name": "Brightstar Lottery",
            },
            {
                "ticker": "IRRl_EQ",
                "shortName": "ALL",
                "isin": "AU0000237554",
                "type": "STOCK",
                "name": "Atlantic Lithium",
            },
            {
                "ticker": "SVHHd_EQ",
                "shortName": "SVHH",
                "isin": "SE0007100599",
                "type": "STOCK",
                "name": "Svenska Handelsbanken (Class A)",
            },
            {
                "ticker": "EQT_US_EQ",
                "shortName": "EQT",
                "isin": "US26884L1098",
                "type": "STOCK",
                "name": "EQT",
            },
            {
                "ticker": "EQ6d_EQ",
                "shortName": "EQ6",
                "isin": "US26884L1098",
                "type": "STOCK",
                "name": "EQT",
            },
            {
                "ticker": "SKp_EQ",
                "shortName": "SK",
                "isin": "FR0000121709",
                "type": "STOCK",
                "name": "SEB",
            },
            {
                "ticker": "BOOHl_EQ",
                "shortName": "DEBS",
                "isin": "JE00BG6L7297",
                "type": "STOCK",
                "name": "boohoo",
            },
            {
                "ticker": "MCONl_EQ",
                "shortName": "MCON",
                "isin": "IE00BD64C665",
                "type": "STOCK",
                "name": "Mincon",
            },
            {
                "ticker": "APA_US_EQ",
                "shortName": "APA",
                "isin": "US03743Q1085",
                "type": "STOCK",
                "name": "APA",
            },
        ]
    )


def test_company_name_joins_a_different_symbol_and_refuses_namesakes():
    from value_investor.t212_coverage import DEFAULT_SUFFIX_EXCHANGES

    index = _name_join_index()
    policy = {"yahoo_suffix_to_t212_exchanges": DEFAULT_SUFFIX_EXCHANGES}
    enel = match_catalogue("ENEL.MI", index=index, policy=policy, name="Enel")
    assert enel["ticker"] == "ENL1d_EQ"
    # Milan has no local line. The exact company name still matches its own cross-listing.
    assert match_catalogue("ENEL.MI", index=index, policy=policy, name="Enel Chile")["ticker"] == (
        "ENIC_US_EQ"
    )
    assert match_catalogue("RACE.MI", index=index, policy=policy, name="Ferrari")["isin"] == (
        "NL0011585146"
    )
    nordea = match_catalogue("NDA-FI.HE", index=index, policy=policy, name="Nordea")
    assert nordea["isin"] == "FI4000297767"
    assert (
        match_catalogue("SHB-A.ST", index=index, policy=policy, name="Handelsbanken A")["ticker"]
        == "SVHHd_EQ"
    )
    assert match_catalogue("STMPA.PA", index=index, policy=policy)["ticker"] == "STMpp_EQ"
    assert (
        match_catalogue("STM.DE", index=index, policy=policy, name="Stabilus")["ticker"]
        == "STMd_EQ"
    )
    assert match_catalogue("0386.HK", index=index, policy=policy, name="Sinopec Corp") is None
    assert (
        match_catalogue("TLC.AX", index=index, policy=policy, name="The Lottery Corporation")
        is None
    )
    assert match_catalogue("ALL.AX", index=index, policy=policy, name="Aristocrat Leisure") is None
    assert match_catalogue("ENEL.MI", index=index, policy=policy) is None
    # Same short name, other country: not this listing.
    assert match_catalogue("EQT.ST", index=index, policy=policy, name="EQT") is None
    assert match_catalogue("SEB-A.ST", index=index, policy=policy, name="SEB A") is None
    # Home-country line, our name only adds a generic word.
    assert match_catalogue("BOO.L", index=index, policy=policy, name="Boohoo Group plc")[
        "isin"
    ] == ("JE00BG6L7297")
    assert match_catalogue("MIO.IR", index=index, policy=policy, name="Mincon group")["isin"] == (
        "IE00BD64C665"
    )
    assert match_catalogue("APA.AX", index=index, policy=policy, name="APA Group") is None


def test_maintenance_drops_unlisted_names_and_keeps_the_ftse_screen(tmp_path: Path):
    from types import SimpleNamespace

    from value_investor.t212_coverage import drop_unlisted_for_maintenance

    root = tmp_path / "library"
    t212 = root / "t212_coverage"
    t212.mkdir(parents=True)
    write_json(
        t212 / "policy.json",
        {"schema_version": 2, "exchanges": [], "yahoo_suffix_to_t212_exchanges": {}},
        compact=False,
    )
    save_catalogue(
        [
            {
                "ticker": "ENL1d_EQ",
                "shortName": "ENL",
                "isin": "IT0003128367",
                "type": "STOCK",
                "name": "Enel",
            }
        ],
        library_root=root,
        env="demo",
        source="fixture",
    )
    reports = [
        SimpleNamespace(ticker="ENEL.MI", name="Enel"),
        SimpleNamespace(ticker="A2A.MI", name="A2A"),
    ]
    kept, skipped = drop_unlisted_for_maintenance(reports, market_id="ftse_mib", library_root=root)
    assert [row.ticker for row in kept] == ["ENEL.MI"]
    assert skipped == ["A2A.MI"]
    ftse_kept, ftse_skipped = drop_unlisted_for_maintenance(
        reports, market_id="ftse350", library_root=root
    )
    assert [row.ticker for row in ftse_kept] == ["ENEL.MI", "A2A.MI"]
    assert ftse_skipped == []


def test_maintenance_closed_list_keeps_one_isin_and_refuses_a_choice(tmp_path: Path):
    from types import SimpleNamespace

    from value_investor.t212_coverage import (
        _CLOSED_MAINTENANCE_ISIN,
        drop_unlisted_for_maintenance,
    )

    assert _CLOSED_MAINTENANCE_ISIN == {
        "SLN.L": "US82686Q1013",
        "NEXN.L": "IL0012165630",
        "AZN.ST": "GB0009895292",
        "HMSO.IR": "GB00BRJQ8J25",
        "BOL.ST": "US09752V1026",
        "EPI-A.ST": "US29429L4023",
        "MB.MI": "US58502K1060",
        "TRN.MI": "US88088L1035",
        "O39.SI": "US6903331097",
        "0388.HK": "US43858F1093",
        "0285.HK": "HK0285041858",
        "0960.HK": "US54303R1014",
        "1177.HK": "KYG8167W1380",
        "6690.HK": "CNE1000031C1",
        "0386.HK": "CNE1000002Q2",
        "FLT.AX": "AU000000FLT9",
        "LTR.AX": "AU000000LTR4",
        "SGM.AX": "US8291601008",
        "MTS.MC": "LU1598757687",
        "ABB.ST": "CH0012221716",
        "ERIC-B.ST": "SE0000108656",
        "NDA-SE.ST": "FI4000297767",
        "0175.HK": "KYG3777B1032",
    }

    root = tmp_path / "library"
    t212 = root / "t212_coverage"
    t212.mkdir(parents=True)
    write_json(
        t212 / "policy.json",
        {"schema_version": 2, "exchanges": [], "yahoo_suffix_to_t212_exchanges": {}},
        compact=False,
    )
    save_catalogue(
        [
            {
                "ticker": "SLN_US_EQ",
                "shortName": "SLN",
                "isin": "US82686Q1013",
                "type": "STOCK",
                "name": "Silence Therapeutics",
            },
            {
                "ticker": "FLT_US_EQ",
                "shortName": "FLT",
                "isin": "CA92865M1023",
                "type": "STOCK",
                "name": "Volatus Aerospace",
            },
            {
                "ticker": "FLId_EQ",
                "shortName": "FLI",
                "isin": "AU000000FLT9",
                "type": "STOCK",
                "name": "Flight Centre",
            },
            {
                "ticker": "MTd_EQ",
                "shortName": "MT",
                "isin": "LU1598757687",
                "type": "STOCK",
                "name": "ArcelorMittal",
            },
            {
                "ticker": "MT_US_EQ",
                "shortName": "MT",
                "isin": "US03938L2034",
                "type": "STOCK",
                "name": "ArcelorMittal",
            },
            {
                "ticker": "ERCBd_EQ",
                "shortName": "ERCB",
                "isin": "SE0000108656",
                "type": "STOCK",
                "name": "Telefonaktiebolaget LM Ericsson (Class B)",
            },
            {
                "ticker": "ERCGd_EQ",
                "shortName": "ERCG",
                "isin": "SE0000108649",
                "type": "STOCK",
                "name": "Telefonaktiebolaget LM Ericsson (Class A)",
            },
            {
                "ticker": "ERIC_US_EQ",
                "shortName": "ERIC",
                "isin": "US2948216088",
                "type": "STOCK",
                "name": "Ericsson",
            },
            {
                "ticker": "ATLCY_US_EQ",
                "shortName": "ATLCY",
                "isin": "US0492558053",
                "type": "STOCK",
                "name": "Atlas Copco",
            },
            {
                "ticker": "ATLKY_US_EQ",
                "shortName": "ATLKY",
                "isin": "US0492557063",
                "type": "STOCK",
                "name": "Atlas Copco",
            },
            {
                "ticker": "EQT_US_EQ",
                "shortName": "EQT",
                "isin": "US26884L1098",
                "type": "STOCK",
                "name": "EQT",
            },
            {
                "ticker": "SK_US_EQ",
                "shortName": "SK",
                "isin": "FR0000121709",
                "type": "STOCK",
                "name": "SEB",
            },
            {
                "ticker": "APA_US_EQ",
                "shortName": "APA",
                "isin": "US03743Q1085",
                "type": "STOCK",
                "name": "APA",
            },
            {
                "ticker": "BRSTd_EQ",
                "shortName": "BRST",
                "isin": "US1111111111",
                "type": "STOCK",
                "name": "Brightstar Lottery",
            },
            {
                "ticker": "ENL1d_EQ",
                "shortName": "ENL",
                "isin": "IT0003128367",
                "type": "STOCK",
                "name": "Enel",
            },
        ],
        library_root=root,
        env="demo",
        source="fixture",
    )
    # The closed list is not a name-match rule.
    assert match_catalogue("SLN.L", index=build_catalogue_index([]), policy={}) is None
    index = build_catalogue_index(
        [
            {
                "ticker": "SLN_US_EQ",
                "shortName": "SLN",
                "isin": "US82686Q1013",
                "type": "STOCK",
                "name": "Silence Therapeutics",
            }
        ]
    )
    assert match_catalogue("SLN.L", index=index, policy={}, name="Silence Therapeutics") is None
    reports = [
        SimpleNamespace(ticker="SLN.L", name="Silence Therapeutics"),
        SimpleNamespace(ticker="FLT.AX", name="Flight Centre"),
        SimpleNamespace(ticker="MTS.MC", name="ArcelorMittal"),
        SimpleNamespace(ticker="ERIC-B.ST", name="Ericsson B"),
        SimpleNamespace(ticker="ATCO-A.ST", name="Atlas Copco A"),
        SimpleNamespace(ticker="EQT.ST", name="EQT"),
        SimpleNamespace(ticker="SEB-A.ST", name="SEB A"),
        SimpleNamespace(ticker="APA.AX", name="APA Group"),
        SimpleNamespace(ticker="TLC.AX", name="The Lottery Corporation"),
        SimpleNamespace(ticker="ENEL.MI", name="Enel"),
        SimpleNamespace(ticker="A2A.MI", name="A2A"),
    ]
    kept, skipped = drop_unlisted_for_maintenance(
        reports, market_id="omx_stockholm", library_root=root
    )
    assert [row.ticker for row in kept] == ["SLN.L", "FLT.AX", "MTS.MC", "ERIC-B.ST", "ENEL.MI"]
    assert skipped == ["ATCO-A.ST", "EQT.ST", "SEB-A.ST", "APA.AX", "TLC.AX", "A2A.MI"]
    # Only the ADR is present, so the Madrid ordinary stays off.
    save_catalogue(
        [
            {
                "ticker": "MT_US_EQ",
                "shortName": "MT",
                "isin": "US03938L2034",
                "type": "STOCK",
                "name": "ArcelorMittal",
            },
            {
                "ticker": "ENL1d_EQ",
                "shortName": "ENL",
                "isin": "IT0003128367",
                "type": "STOCK",
                "name": "Enel",
            },
        ],
        library_root=root,
        env="demo",
        source="fixture",
    )
    adr_kept, adr_skipped = drop_unlisted_for_maintenance(
        [
            SimpleNamespace(ticker="MTS.MC", name="ArcelorMittal"),
            SimpleNamespace(ticker="ENEL.MI", name="Enel"),
        ],
        market_id="ibex",
        library_root=root,
    )
    assert [row.ticker for row in adr_kept] == ["ENEL.MI"]
    assert adr_skipped == ["MTS.MC"]
    bare = tmp_path / "empty"
    bare.mkdir()
    missing_kept, missing_skipped = drop_unlisted_for_maintenance(
        reports, market_id="omx_stockholm", library_root=bare
    )
    assert [row.ticker for row in missing_kept] == [row.ticker for row in reports]
    assert missing_skipped == []


def test_cross_listing_name_matches_without_a_local_venue():
    from value_investor.t212_coverage import DEFAULT_SUFFIX_EXCHANGES

    index = build_catalogue_index(
        [
            {
                "ticker": "HSBAl_EQ",
                "shortName": "HSBA",
                "isin": "GB0005405286",
                "type": "STOCK",
                "name": "HSBC",
            },
            {
                "ticker": "BABA_US_EQ",
                "shortName": "BABA",
                "isin": "US01609W1027",
                "type": "STOCK",
                "name": "Alibaba",
            },
            {
                "ticker": "TWYd_EQ",
                "shortName": "TWY",
                "isin": "BMG0171K1018",
                "type": "STOCK",
                "name": "Alibaba Health Information Technology",
            },
            {
                "ticker": "APA_US_EQ",
                "shortName": "APA",
                "isin": "US03743Q1085",
                "type": "STOCK",
                "name": "APA",
            },
            {
                "ticker": "WWRd_EQ",
                "shortName": "WWR",
                "isin": "AU000000WOW2",
                "type": "STOCK",
                "name": "Woolworths",
            },
            {
                "ticker": "RACE_US_EQ",
                "shortName": "RACE",
                "isin": "NL0011585146",
                "type": "STOCK",
                "name": "Ferrari",
            },
            {
                "ticker": "FERGRa_EQ",
                "shortName": "FERGR",
                "isin": "GB00BN0VZ646",
                "type": "STOCK",
                "name": "Ferrari Group",
            },
            {
                "ticker": "BRSTd_EQ",
                "shortName": "BRST",
                "isin": "US1111111111",
                "type": "STOCK",
                "name": "Brightstar Lottery",
            },
            {
                "ticker": "EQT_US_EQ",
                "shortName": "EQT",
                "isin": "US26884L1098",
                "type": "STOCK",
                "name": "EQT",
            },
            {
                "ticker": "HRB_US_EQ",
                "shortName": "HRB",
                "isin": "US0936711052",
                "type": "STOCK",
                "name": "H&R Block",
            },
            {
                "ticker": "SQ_US_EQ",
                "shortName": "XYZ",
                "isin": "US8522341036",
                "type": "STOCK",
                "name": "Block",
            },
        ]
    )
    policy = {"yahoo_suffix_to_t212_exchanges": DEFAULT_SUFFIX_EXCHANGES}
    assert (
        match_catalogue("0005.HK", index=index, policy=policy, name="HSBC Holdings plc")["ticker"]
        == "HSBAl_EQ"
    )
    assert (
        match_catalogue("9988.HK", index=index, policy=policy, name="Alibaba Group")["isin"]
        == "US01609W1027"
    )
    assert match_catalogue("APA.AX", index=index, policy=policy, name="APA Group") is None
    assert (
        match_catalogue("WOW.AX", index=index, policy=policy, name="Woolworths Group")["isin"]
        == "AU000000WOW2"
    )
    assert match_catalogue("RACE.MI", index=index, policy=policy, name="Ferrari")["isin"] == (
        "NL0011585146"
    )
    assert (
        match_catalogue("TLC.AX", index=index, policy=policy, name="The Lottery Corporation")
        is None
    )
    assert match_catalogue("EQT.ST", index=index, policy=policy, name="EQT") is None
    assert match_catalogue("XYX.AX", index=index, policy=policy, name="Block, Inc.")["isin"] == (
        "US8522341036"
    )
