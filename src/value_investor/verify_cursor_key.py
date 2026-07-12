"""Validate CURSOR_API_KEY against the Cursor API."""

from __future__ import annotations

import os
import sys

from cursor_sdk import Cursor, CursorAgentError


def verify_cursor_api_key(api_key: str | None = None) -> tuple[bool, str]:
    key = (api_key or os.environ.get("CURSOR_API_KEY") or "").strip()
    if not key:
        return False, "CURSOR_API_KEY is not set"

    if not key.startswith(("crsr_", "cursor_")):
        return False, "Key should start with crsr_ or cursor_"

    try:
        user = Cursor.me(api_key=key)
    except CursorAgentError as err:
        return False, f"Cursor API rejected the key: {err.message}"
    except Exception as err:  # noqa: BLE001
        return False, f"Cursor API check failed: {err}"

    name_bits = [bit for bit in (user.user_first_name, user.user_last_name) if bit]
    owner = " ".join(name_bits) if name_bits else (user.user_email or "authenticated")
    key_name = user.api_key_name or "API key"
    return True, f"Authenticated as {owner} ({key_name})"


def main(argv: list[str] | None = None) -> int:
    ok, message = verify_cursor_api_key()
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
