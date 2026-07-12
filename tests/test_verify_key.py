"""Tests for Cursor API key verification."""

from __future__ import annotations

from cursor_sdk import AuthenticationError, ConfigurationError, NetworkError
from cursor_sdk.types import SDKModel, SDKUser

from value_investor.verify_key import verify_cursor_api_key
from value_investor.verify_key_cli import main as verify_key_main


def _user(**overrides) -> SDKUser:
    base = dict(
        api_key_name="ftse-local",
        created_at="2026-01-01T00:00:00Z",
        user_id=1,
        user_email="investor@example.com",
        user_first_name="Jamie",
        user_last_name="Fuller",
    )
    base.update(overrides)
    return SDKUser(**base)


def _model(model_id: str) -> SDKModel:
    return SDKModel(id=model_id, display_name=model_id, description="", parameters=(), variants=())


def test_verify_key_missing(monkeypatch):
    monkeypatch.setattr("value_investor.verify_key.Cursor.me", lambda **_: None)
    result = verify_cursor_api_key(None)
    assert not result.ok
    assert "not set" in result.detail


def test_verify_key_blank(monkeypatch):
    result = verify_cursor_api_key("   ")
    assert not result.ok
    assert "not set" in result.detail


def test_verify_key_success(monkeypatch):
    user = _user()
    monkeypatch.setattr(
        "value_investor.verify_key.Cursor.me",
        lambda **kwargs: user if kwargs.get("api_key") == "cursor_test" else None,
    )
    result = verify_cursor_api_key("cursor_test")
    assert result.ok
    assert result.user is user
    text = result.to_text()
    assert "Authentication succeeded" in text
    assert "ftse-local" in text
    assert "investor@example.com" in text
    assert "cursor_test" not in text


def test_verify_key_lists_models(monkeypatch):
    user = _user()
    models = [_model("composer-2.5"), _model("gpt-5.4")]
    monkeypatch.setattr("value_investor.verify_key.Cursor.me", lambda **_: user)
    monkeypatch.setattr(
        "value_investor.verify_key.Cursor.models.list",
        lambda **_: models,
    )
    result = verify_cursor_api_key("cursor_test", list_models=True)
    assert result.ok
    assert [m.id for m in result.models] == ["composer-2.5", "gpt-5.4"]
    text = result.to_text(show_models=True)
    assert "composer-2.5" in text
    assert "gpt-5.4" in text


def test_verify_key_auth_failure(monkeypatch):
    def _raise(**_kwargs):
        raise AuthenticationError("invalid key")

    monkeypatch.setattr("value_investor.verify_key.Cursor.me", _raise)
    result = verify_cursor_api_key("bad-key")
    assert not result.ok
    assert "Authentication failed" in result.detail


def test_verify_key_configuration_error(monkeypatch):
    def _raise(**_kwargs):
        raise ConfigurationError("BAD_USER_API_KEY")

    monkeypatch.setattr("value_investor.verify_key.Cursor.me", _raise)
    result = verify_cursor_api_key("malformed")
    assert not result.ok
    assert "Invalid key" in result.detail


def test_verify_key_network_error(monkeypatch):
    def _raise(**_kwargs):
        raise NetworkError("offline")

    monkeypatch.setattr("value_investor.verify_key.Cursor.me", _raise)
    result = verify_cursor_api_key("cursor_test")
    assert not result.ok
    assert "Network error" in result.detail


def test_verify_key_model_list_failure(monkeypatch):
    user = _user()
    monkeypatch.setattr("value_investor.verify_key.Cursor.me", lambda **_: user)

    def _raise(**_kwargs):
        raise NetworkError("models offline")

    monkeypatch.setattr("value_investor.verify_key.Cursor.models.list", _raise)
    result = verify_cursor_api_key("cursor_test", list_models=True)
    assert not result.ok
    assert result.user is user
    assert "listing models failed" in result.detail


def test_cli_success(monkeypatch, capsys):
    user = _user()
    monkeypatch.setattr("value_investor.verify_key.Cursor.me", lambda **_: user)
    code = verify_key_main(["--api-key", "cursor_test"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Authentication succeeded" in out


def test_cli_missing_key(monkeypatch, capsys):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    code = verify_key_main([])
    assert code == 1
    out = capsys.readouterr().out
    assert "not set" in out
