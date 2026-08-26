"""Backward-compatible re-exports — see ``library_ingest_dispatch``."""

from __future__ import annotations

from value_investor.library_ingest_dispatch import (  # noqa: F401
    DEFAULT_DISPATCH_PATH,
    EURO_INGEST_CRON_TITLES,
    MAINTENANCE_CONFIG,
    MODE_IDLE,
    MODE_MAINTENANCE,
    MODE_SPRINT,
    SPRINT_CONFIG,
    cron_enabled_for_dispatch,
    evaluate_euro_ingest_dispatch,
    evaluate_library_ingest_dispatch,
    ingest_parity_met,
    list_library_ingest_maintenance_markets,
    load_euro_ingest_dispatch,
    refresh_euro_ingest_dispatch,
    write_euro_ingest_dispatch,
)
from value_investor.library_ingest_escalation import snapshot_library_buy_tier_filing_health

# Legacy alias used in docs/tests.
MODE_CONFIG = {
    MODE_SPRINT: SPRINT_CONFIG,
    MODE_MAINTENANCE: MAINTENANCE_CONFIG,
    MODE_IDLE: MAINTENANCE_CONFIG,
}

__all__ = [
    "DEFAULT_DISPATCH_PATH",
    "EURO_INGEST_CRON_TITLES",
    "MODE_CONFIG",
    "MODE_IDLE",
    "MODE_MAINTENANCE",
    "MODE_SPRINT",
    "cron_enabled_for_dispatch",
    "evaluate_euro_ingest_dispatch",
    "evaluate_library_ingest_dispatch",
    "ingest_parity_met",
    "list_library_ingest_maintenance_markets",
    "load_euro_ingest_dispatch",
    "refresh_euro_ingest_dispatch",
    "snapshot_library_buy_tier_filing_health",
    "write_euro_ingest_dispatch",
]
