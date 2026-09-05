"""Yahoo ticker → LEI cache and GLEIF search."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.research.issuer_identifiers import (
    cached_cbe,
    cached_isin,
    cached_issuer_identity,
    cached_lei,
    resolve_lei,
    save_issuer_identity,
    save_issuer_lei,
    search_lei_gleif,
)


def _gleif_record(lei: str, name: str, country: str) -> dict:
    return {
        "id": lei,
        "attributes": {
            "entity": {
                "legalName": {"name": name, "language": "en"},
                "legalAddress": {"country": country},
            }
        },
    }


def test_cached_lei_builtin_aed_br(tmp_path: Path):
    empty = tmp_path / "missing.json"
    assert cached_lei("AED.BR", path=empty) == "529900DTKNXL0AXQFN28"
    assert cached_lei("AED", path=empty) == "529900DTKNXL0AXQFN28"


def test_cached_belgium_identity_builtins(tmp_path: Path):
    empty = tmp_path / "missing.json"
    assert cached_isin("AED.BR", path=empty) == "BE0003851681"
    assert cached_cbe("AED.BR", path=empty) == "0877248501"
    assert cached_isin("ABI.BR", path=empty) == "BE0974293251"
    assert cached_cbe("ABI.BR", path=empty) == "0417497106"
    abi = cached_issuer_identity("ABI.BR", path=empty)
    assert abi["mic"] == "XBRU"
    assert cached_isin("ABI", path=empty) is None


def test_save_issuer_identity_keeps_lei(tmp_path: Path):
    path = tmp_path / "ids.json"
    save_issuer_lei(
        "AED.BR",
        "529900DTKNXL0AXQFN28",
        path=path,
        lei_name="AEDIFICA",
        lei_country="BE",
        source="gleif",
    )
    save_issuer_identity(
        "AED.BR",
        path=path,
        isin="BE0003851681",
        cbe="0877.248.501",
        mic="XBRU",
        source="belgium_official",
    )
    row = cached_issuer_identity("AED.BR", path=path)
    assert row["lei"] == "529900DTKNXL0AXQFN28"
    assert row["isin"] == "BE0003851681"
    assert row["cbe"] == "0877248501"


def test_resolve_lei_uses_cache_before_gleif(tmp_path: Path):
    path = tmp_path / "ids.json"
    save_issuer_lei(
        "SAP.DE",
        "529900D6BF99LW9R2E68",
        path=path,
        lei_name="SAP SE",
        lei_country="DE",
        source="manual",
    )
    calls = {"n": 0}

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("GLEIF should not run when cached")

    lei = resolve_lei(
        "SAP.DE",
        company_name="SAP SE",
        country_hint="DE",
        path=path,
        search=True,
        persist=False,
        http_get=boom,
    )
    assert lei == "529900D6BF99LW9R2E68"
    assert calls["n"] == 0


def test_search_lei_gleif_prefers_be_over_it():
    payload = {
        "data": [
            _gleif_record("81560012EC0C63747453", "AEDIFICA S.R.L.", "IT"),
            _gleif_record("529900DTKNXL0AXQFN28", "AEDIFICA", "BE"),
        ]
    }

    def fake_get(url: str, **kwargs):
        assert "filter" in url
        return json.dumps(payload).encode("utf-8")

    found = search_lei_gleif(
        company_name="Aedifica",
        ticker="AED.BR",
        country_hint="BE",
        http_get=fake_get,
    )
    assert found is not None
    assert found["lei"] == "529900DTKNXL0AXQFN28"
    assert found["lei_country"] == "BE"


def test_search_lei_gleif_rejects_country_mismatch():
    payload = {"data": [_gleif_record("81560012EC0C63747453", "AEDIFICA S.R.L.", "IT")]}

    def fake_get(url: str, **kwargs):
        return json.dumps(payload).encode("utf-8")

    found = search_lei_gleif(
        company_name="Aedifica",
        ticker="AED.BR",
        country_hint="BE",
        http_get=fake_get,
    )
    assert found is None


def test_resolve_lei_persists_gleif_hit(tmp_path: Path):
    path = tmp_path / "ids.json"
    payload = {"data": [_gleif_record("529900D6BF99LW9R2E68", "SAP SE", "DE")]}

    def fake_get(url: str, **kwargs):
        return json.dumps(payload).encode("utf-8")

    lei = resolve_lei(
        "SAP.DE",
        company_name="SAP SE",
        country_hint="DE",
        path=path,
        search=True,
        persist=True,
        http_get=fake_get,
    )
    assert lei == "529900D6BF99LW9R2E68"
    assert cached_lei("SAP.DE", path=path) == "529900D6BF99LW9R2E68"
