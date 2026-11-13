"""FTSE 350 delisting-leaver selection. No network."""

from __future__ import annotations

from value_investor.ftse350_leavers import (
    _extra_tokens,
    classify_note,
    display_name,
    epic_supports_name,
    expected_years,
    is_uk_listed_plc,
    names_match,
    records_from_leavers,
    search_names,
    select_leavers,
)


def _event(
    day: str,
    index: str,
    deleted: str,
    notes: str,
    added: str = "",
) -> dict:
    return {
        "date": day,
        "index": index,
        "deleted": deleted,
        "added": added,
        "notes": notes,
        "page": 1,
    }


def test_takeover_is_a_leaver_and_a_demotion_is_not() -> None:
    events = [
        _event(
            "2014-03-01",
            "ftse250",
            "Acme",
            "Corporate Event – acquisition of Acme by BigCo",
        ),
        _event("2015-06-19", "ftse100", "Gamma", "", added="Beta"),
        _event("2015-06-19", "ftse250", "Beta", "", added="Gamma"),
        _event(
            "2016-04-01",
            "ftse100",
            "Old Parent",
            "Corporate Event – demerger of Spin Co from Old Parent",
            added="Spin Co",
        ),
    ]
    leavers, _diag = select_leavers(events)
    names = {row["deleted"]: row["reason_class"] for row in leavers}
    assert names == {"Acme": "takeover"}


def test_failure_and_listing_move_are_leavers() -> None:
    assert (
        classify_note(
            "NMC Health",
            "Corporate Event – deleted following continued suspension of listing",
        )
        == "failure"
    )
    assert (
        classify_note(
            "CRH",
            "transfer of CRH shares from a Premium to an ineligible Standard Listing",
        )
        == "other"
    )
    assert classify_note("Widget", "") is None
    assert (
        classify_note(
            "Smufit Kappa Group",
            "combination between Smurfit Kappa Group and WestRock Company",
        )
        == "takeover"
    )


def test_company_number_name_match_rejects_a_different_entity() -> None:
    assert names_match("Wood Group (John)", "JOHN WOOD GROUP PLC")
    assert names_match("GKN", "GKN PLC")
    assert names_match("AZ Electronic Materials", "AZ ELECTRONIC MATERIALS (UK) LIMITED")
    assert not names_match("Sky", "SKYSCANNER LIMITED")
    assert not names_match("ARM Holdings", "ARMAGH LIMITED")
    assert not names_match(
        "AZ Electronic Materials", "MERCK PERFORMANCE MATERIALS SERVICES UK LIMITED"
    )
    assert is_uk_listed_plc(
        {
            "company_number": "00166023",
            "type": "ltd",
            "jurisdiction": "england-wales",
            "company_name": "INVENSYS LIMITED",
            "previous_company_names": [{"name": "INVENSYS PLC"}],
        }
    )
    assert not is_uk_listed_plc(
        {
            "company_number": "06790365",
            "type": "ltd",
            "jurisdiction": "england-wales",
            "company_name": "AZ ELECTRONIC MATERIALS (UK) LIMITED",
            "previous_company_names": [],
        }
    )
    assert not is_uk_listed_plc(
        {
            "company_number": "FC031899",
            "type": "oversea-company",
            "jurisdiction": "jersey",
            "company_name": "KENTZ MANAGEMENT LIMITED",
            "previous_company_names": [],
        }
    )
    assert _extra_tokens("GKN", "GKN PLC") == 0
    assert _extra_tokens("GKN", "GKN HOLDINGS PLC") == 1
    assert _extra_tokens("Aegis", "AEGIS GROUP PLC") == 1
    assert _extra_tokens("Aegis", "AEGIS GROUP HOLDINGS PLC") == 2


def test_expected_years_start_at_the_window_when_already_a_member() -> None:
    assert expected_years("", "2018-04-24")[0] == 2013
    assert expected_years("", "2018-04-24")[-1] == 2018
    assert expected_years("2016-09-05", "2018-10-12") == [2016, 2017, 2018]


def test_display_name_fixes_a_glyph_and_does_not_drop_a_token() -> None:
    assert (
        display_name(
            "Smufit Kappa Group",
            "combination between Smurfit Kappa Group and WestRock Company",
        )
        == "Smurfit Kappa Group"
    )
    assert (
        display_name(
            "AZ Electronic Materials",
            "offer for AZ Electronic Materials by Merck",
        )
        == "AZ Electronic Materials"
    )
    assert (
        display_name(
            "International Distribution Services",
            "cash offer for International Distributiojn Services by EP UK Bidco",
        )
        == "International Distribution Services"
    )
    assert display_name("Jardine Lloyd Thompson Group", "Jardine Lloyd Thomson Group") == (
        "Jardine Lloyd Thompson Group"
    )
    assert (
        search_names(
            {
                "name": "Smith (DS)",
                "reason": "combination between International Paper and Smith (DS)",
            }
        )[0]
        == "DS Smith"
    )
    assert "Wm Morrison Supermarkets" in search_names(
        {
            "name": "Morrison",
            "reason": "cash offer for Morrison (Wm) Supermarkets by CD&R Bidco",
        }
    )
    assert (
        epic_supports_name("Betfair Group", "https://en.wikipedia.org/wiki/The_Rank_Group") is False
    )
    assert (
        epic_supports_name("LXI REIT", "https://en.wikipedia.org/wiki/LondonMetric_Property")
        is False
    )
    assert epic_supports_name("DS Smith", "https://en.wikipedia.org/wiki/DS_Smith") is True


def test_sky_and_gkn_keep_the_hand_verified_keys() -> None:
    rows = [
        {
            "date": "2018-10-12",
            "index": "ftse100",
            "deleted": "Sky",
            "notes": "Acquisition of Sky by Comcast",
            "reason_class": "takeover",
            "spell_start": "",
            "page": 14,
        },
        {
            "date": "2018-04-24",
            "index": "ftse100",
            "deleted": "GKN",
            "notes": "Acquisition of GKN by Melrose Industries",
            "reason_class": "takeover",
            "spell_start": "2002-05-29",
            "page": 14,
        },
    ]
    records = records_from_leavers(rows)
    by_key = {row["key"]: row for row in records}
    assert set(by_key) == {"sky", "gkn"}
    assert by_key["sky"]["ch_applicable"] is None
    assert by_key["gkn"]["source_url"].endswith("ftse-100-constituent-history.pdf")
