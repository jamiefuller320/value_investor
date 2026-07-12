"""CLI entry for Cursor API key verification."""

from __future__ import annotations

import sys

from value_investor.verify_cursor_key import main

if __name__ == "__main__":
    sys.exit(main())
