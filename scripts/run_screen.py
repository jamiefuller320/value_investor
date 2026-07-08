#!/usr/bin/env python3
"""Convenience wrapper — prefer `ftse-screen` or `python -m value_investor.cli`."""

from value_investor.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
