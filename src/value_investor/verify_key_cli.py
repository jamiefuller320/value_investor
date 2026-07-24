"""CLI to verify CURSOR_API_KEY against the Cursor API."""

from __future__ import annotations

import argparse
import sys

from value_investor.cursor_api_key import (
    CURSOR_API_KEY_ENV,
    CURSOR_API_KEY_V2_ENV,
    cursor_api_key_diagnostics,
    resolve_cursor_api_key,
)
from value_investor.verify_key import verify_cursor_api_key


def _resolve_cli_api_key(
    explicit_key: str | None,
    *,
    key_source: str,
) -> tuple[str | None, str | None]:
    if explicit_key is not None:
        normalized = explicit_key.strip()
        return (normalized or None), "--api-key" if normalized else None
    return resolve_cursor_api_key(source=key_source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that a Cursor API key authenticates with the Cursor API. "
            f"Defaults to {CURSOR_API_KEY_V2_ENV} when set, otherwise {CURSOR_API_KEY_ENV}."
        )
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "Cursor API key (overrides env). "
            f"Otherwise uses {CURSOR_API_KEY_V2_ENV} then {CURSOR_API_KEY_ENV}."
        ),
    )
    parser.add_argument(
        "--key-source",
        choices=["auto", "v2", "legacy"],
        default="auto",
        help=(
            "Which env var to use when --api-key is omitted: "
            f"auto ({CURSOR_API_KEY_V2_ENV} then {CURSOR_API_KEY_ENV}), "
            f"v2 ({CURSOR_API_KEY_V2_ENV} only), or legacy ({CURSOR_API_KEY_ENV} only)"
        ),
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Also list models available to this key",
    )
    args = parser.parse_args(argv)

    api_key, selected_source = _resolve_cli_api_key(args.api_key, key_source=args.key_source)
    diagnostics = cursor_api_key_diagnostics(selected_source=selected_source)

    result = verify_cursor_api_key(api_key, list_models=args.list_models)
    print(result.to_text(show_models=args.list_models, diagnostics=diagnostics))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
