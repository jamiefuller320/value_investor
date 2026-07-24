"""Resolve Cursor API keys from environment variables."""

from __future__ import annotations

import os

CURSOR_API_KEY_ENV = "CURSOR_API_KEY"
CURSOR_API_KEY_V2_ENV = "CURSOR_API_KEY_V2"


def api_key_fingerprint(key: str | None) -> str:
    """Safe fingerprint for logs (prefix + length, never the full secret)."""
    normalized = (key or "").strip()
    if not normalized:
        return "(empty)"
    prefix = normalized[:5]
    return f"{prefix}… len={len(normalized)}"


def env_key_status(env_name: str) -> str:
    """Describe whether an env var is unset, blank, or populated."""
    if env_name not in os.environ:
        return "not set"
    normalized = (os.environ.get(env_name) or "").strip()
    if not normalized:
        return "set but blank"
    return api_key_fingerprint(normalized)


def resolve_cursor_api_key(*, source: str = "auto") -> tuple[str, str | None]:
    """Return (api_key, env_name_used).

    source:
      auto   — prefer CURSOR_API_KEY_V2, then CURSOR_API_KEY
      v2     — CURSOR_API_KEY_V2 only
      legacy — CURSOR_API_KEY only
    """
    if source == "v2":
        candidates = (CURSOR_API_KEY_V2_ENV,)
    elif source == "legacy":
        candidates = (CURSOR_API_KEY_ENV,)
    else:
        candidates = (CURSOR_API_KEY_V2_ENV, CURSOR_API_KEY_ENV)

    for env_name in candidates:
        key = (os.environ.get(env_name) or "").strip()
        if key:
            return key, env_name
    return "", None


def cursor_api_key_diagnostics(*, selected_source: str | None = None) -> list[str]:
    """Diagnostic lines comparing both env vars without printing secrets."""
    lines = [
        f"  {CURSOR_API_KEY_V2_ENV}: {env_key_status(CURSOR_API_KEY_V2_ENV)}",
        f"  {CURSOR_API_KEY_ENV}: {env_key_status(CURSOR_API_KEY_ENV)}",
    ]
    if selected_source:
        lines.append(f"  Verifying: {selected_source}")
    else:
        _, resolved = resolve_cursor_api_key()
        lines.append(f"  Verifying: {resolved or '(none)'}")
    return lines
