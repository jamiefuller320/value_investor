#!/usr/bin/env python3
"""CLI wrapper for committed data JSON integrity checks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from value_investor.committed_data_json import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
