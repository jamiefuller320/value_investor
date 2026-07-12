"""CLI to verify CURSOR_API_KEY against the Cursor API."""

from __future__ import annotations

import argparse
import os
import sys

from value_investor.verify_key import verify_cursor_api_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify that CURSOR_API_KEY authenticates with the Cursor API"
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CURSOR_API_KEY"),
        help="Cursor API key (defaults to CURSOR_API_KEY env var)",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Also list models available to this key",
    )
    args = parser.parse_args(argv)

    result = verify_cursor_api_key(args.api_key, list_models=args.list_models)
    print(result.to_text(show_models=args.list_models))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
