"""Trading 212 Public API client (catalogue / metadata only).

Credentials (env):
  TRADING212_API_KEY
  TRADING212_API_SECRET
  TRADING212_ENV = demo|live  (default: demo)

Does not place orders — see deferred N14 / stage 6.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEMO_BASE = "https://demo.trading212.com"
LIVE_BASE = "https://live.trading212.com"

INSTRUMENTS_PATH = "/api/v0/equity/metadata/instruments"
EXCHANGES_PATH = "/api/v0/equity/metadata/exchanges"


class Trading212AuthError(RuntimeError):
    """Missing credentials or unauthorized / forbidden API response."""


class Trading212APIError(RuntimeError):
    """Non-auth failure talking to the Trading 212 API."""


def t212_base_url(env: str | None = None) -> str:
    chosen = (env or os.environ.get("TRADING212_ENV") or "demo").strip().lower()
    if chosen in {"live", "real", "prod", "production"}:
        return LIVE_BASE
    return DEMO_BASE


def t212_credentials(
    api_key: str | None = None,
    api_secret: str | None = None,
) -> tuple[str, str]:
    key = (api_key or os.environ.get("TRADING212_API_KEY") or "").strip()
    secret = (api_secret or os.environ.get("TRADING212_API_SECRET") or "").strip()
    if not key or not secret:
        raise Trading212AuthError(
            "Set TRADING212_API_KEY and TRADING212_API_SECRET "
            "(API key needs the metadata scope)."
        )
    return key, secret


def _auth_header(api_key: str, api_secret: str) -> str:
    token = base64.b64encode(f"{api_key}:{api_secret}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def t212_request(
    path: str,
    *,
    env: str | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
    timeout: float = 120.0,
) -> Any:
    """GET a Trading 212 API path and return parsed JSON."""
    key, secret = t212_credentials(api_key, api_secret)
    url = t212_base_url(env).rstrip("/") + path
    req = Request(
        url,
        headers={
            "Authorization": _auth_header(key, secret),
            "Accept": "application/json",
            "User-Agent": "value-investor-t212-catalogue/1.0",
        },
        method="GET",
    )
    context = ssl.create_default_context()
    try:
        with urlopen(req, timeout=timeout, context=context) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        if exc.code in {401, 403}:
            raise Trading212AuthError(
                f"Trading 212 auth failed ({exc.code}) for {path}: {body[:300]}"
            ) from exc
        raise Trading212APIError(
            f"Trading 212 HTTP {exc.code} for {path}: {body[:300]}"
        ) from exc
    except URLError as exc:
        raise Trading212APIError(f"Trading 212 network error for {path}: {exc}") from exc

    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Trading212APIError(f"Invalid JSON from {path}: {exc}") from exc


def fetch_instruments(
    *,
    env: str | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
    timeout: float = 120.0,
) -> list[dict[str, Any]]:
    """Return the full tradable instrument catalogue."""
    payload = t212_request(
        INSTRUMENTS_PATH,
        env=env,
        api_key=api_key,
        api_secret=api_secret,
        timeout=timeout,
    )
    if not isinstance(payload, list):
        raise Trading212APIError(
            f"Expected instrument list, got {type(payload).__name__}"
        )
    return [row for row in payload if isinstance(row, dict)]


def fetch_exchanges(
    *,
    env: str | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
    timeout: float = 60.0,
) -> list[dict[str, Any]]:
    """Return exchange / working-schedule metadata."""
    payload = t212_request(
        EXCHANGES_PATH,
        env=env,
        api_key=api_key,
        api_secret=api_secret,
        timeout=timeout,
    )
    if not isinstance(payload, list):
        raise Trading212APIError(
            f"Expected exchanges list, got {type(payload).__name__}"
        )
    return [row for row in payload if isinstance(row, dict)]
