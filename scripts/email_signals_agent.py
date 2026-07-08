#!/usr/bin/env python3
"""Convenience wrapper — prefer `ftse-email` or `python -m value_investor.email_agent`."""

from value_investor.email_agent import main

if __name__ == "__main__":
    raise SystemExit(main())
