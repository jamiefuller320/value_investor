"""Tests for investment-vehicle universe filtering."""

from __future__ import annotations

import pandas as pd

from value_investor.universe_filters import (
    is_investment_vehicle,
    partition_investment_vehicles,
)


def test_marks_investment_trust_sectors():
    assert is_investment_vehicle(name="Anything", sector="Investment Trusts")
    assert is_investment_vehicle(name="Anything", sector="Collective Investments")
    assert is_investment_vehicle(name="Anything", sector="Real Estate Investment Trusts")


def test_marks_trust_and_fund_names():
    assert is_investment_vehicle(name="Patria Private Equity Trust", sector="Financial Services")
    assert is_investment_vehicle(name="Bluefield Solar Income Fund Limited", sector="Financial Services")
    assert is_investment_vehicle(name="Temple Bar Ord", sector="Financial Services")
    assert is_investment_vehicle(name="Molten Ventures Plc", sector="Financial Services")
    assert is_investment_vehicle(name="Greencoat UK Wind", sector="Gas, Water & Multiutilities")


def test_keeps_operating_companies_and_asset_managers():
    assert not is_investment_vehicle(name="Shell plc", sector="Energy")
    assert not is_investment_vehicle(name="Jupiter Fund Management Plc", sector="Financial Services")
    assert not is_investment_vehicle(name="3i Group", sector="Financial Services")
    # Wikipedia "Ord" share-class suffix is treated as a trust listing style.
    assert is_investment_vehicle(name="3i Group Ord", sector="Financial Services")


def test_partition_investment_vehicles():
    frame = pd.DataFrame(
        [
            {"ticker": "SHEL.L", "name": "Shell", "sector": "Energy"},
            {"ticker": "SMT.L", "name": "Scottish Mortgage Ord", "sector": "Collective investments"},
            {"ticker": "JUP.L", "name": "Jupiter Fund Management Plc", "sector": "Financial Services"},
            {"ticker": "FCIT.L", "name": "F&C Investment Trust Ord", "sector": "Investment Trusts"},
        ]
    )
    kept, excluded = partition_investment_vehicles(frame)
    assert set(kept["ticker"]) == {"SHEL.L", "JUP.L"}
    assert set(excluded["ticker"]) == {"SMT.L", "FCIT.L"}
