"""Tests for Cursor API key env resolution."""

from __future__ import annotations

from value_investor.cursor_api_key import (
    CURSOR_API_KEY_ENV,
    CURSOR_API_KEY_V2_ENV,
    api_key_fingerprint,
    cursor_api_key_diagnostics,
    resolve_cursor_api_key,
)


def test_fingerprint_masks_secret():
    assert api_key_fingerprint("crsr_abcdefghijklmnop") == "crsr_… len=21"
    assert api_key_fingerprint("") == "(empty)"
    assert api_key_fingerprint("   ") == "(empty)"


def test_resolve_prefers_v2(monkeypatch):
    monkeypatch.setenv(CURSOR_API_KEY_V2_ENV, "v2-key")
    monkeypatch.setenv(CURSOR_API_KEY_ENV, "legacy-key")
    key, source = resolve_cursor_api_key()
    assert key == "v2-key"
    assert source == CURSOR_API_KEY_V2_ENV


def test_resolve_falls_back_to_legacy(monkeypatch):
    monkeypatch.delenv(CURSOR_API_KEY_V2_ENV, raising=False)
    monkeypatch.setenv(CURSOR_API_KEY_ENV, "legacy-key")
    key, source = resolve_cursor_api_key()
    assert key == "legacy-key"
    assert source == CURSOR_API_KEY_ENV


def test_resolve_v2_only(monkeypatch):
    monkeypatch.setenv(CURSOR_API_KEY_V2_ENV, "v2-key")
    monkeypatch.setenv(CURSOR_API_KEY_ENV, "legacy-key")
    key, source = resolve_cursor_api_key(source="v2")
    assert key == "v2-key"
    assert source == CURSOR_API_KEY_V2_ENV


def test_resolve_legacy_only(monkeypatch):
    monkeypatch.setenv(CURSOR_API_KEY_V2_ENV, "v2-key")
    monkeypatch.setenv(CURSOR_API_KEY_ENV, "legacy-key")
    key, source = resolve_cursor_api_key(source="legacy")
    assert key == "legacy-key"
    assert source == CURSOR_API_KEY_ENV


def test_diagnostics_lists_both_env_vars(monkeypatch):
    monkeypatch.setenv(CURSOR_API_KEY_V2_ENV, "crsr_v2secret")
    monkeypatch.delenv(CURSOR_API_KEY_ENV, raising=False)
    lines = cursor_api_key_diagnostics()
    assert any("CURSOR_API_KEY_V2" in line and "crsr_…" in line for line in lines)
    assert any("CURSOR_API_KEY: not set" in line for line in lines)
