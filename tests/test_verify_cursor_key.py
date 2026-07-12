"""Tests for Cursor API key verification."""

from unittest.mock import MagicMock, patch

from value_investor.verify_cursor_key import verify_cursor_api_key


def test_verify_cursor_api_key_missing():
    ok, message = verify_cursor_api_key(api_key="")
    assert not ok
    assert "not set" in message


def test_verify_cursor_api_key_bad_prefix():
    ok, message = verify_cursor_api_key(api_key="bad_key_value")
    assert not ok
    assert "start with" in message


@patch("value_investor.verify_cursor_key.Cursor.me")
def test_verify_cursor_api_key_success(mock_me):
    mock_me.return_value = MagicMock(
        api_key_name="Test Key",
        user_first_name="Jamie",
        user_last_name="Fuller",
        user_email="jamie@example.com",
    )
    ok, message = verify_cursor_api_key(api_key="crsr_" + "a" * 64)
    assert ok
    assert "Jamie Fuller" in message
    assert "Test Key" in message
