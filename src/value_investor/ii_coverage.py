"""Backward-compatible re-exports for Trading 212 coverage.

Historical import path: ``value_investor.ii_coverage``.
Canonical implementation: ``value_investor.t212_coverage``.
"""

from __future__ import annotations

from value_investor.t212_coverage import (  # noqa: F401
    annotate_dashboard_reports,
    annotate_shortlist_rows,
    build_ii_overlays,
    build_market_overlay,
    build_t212_overlays,
    classify_ticker,
    ii_coverage_root,
    load_ii_exceptions,
    load_ii_policy,
    load_t212_exceptions,
    load_t212_policy,
    t212_coverage_root,
    yahoo_epic,
    yahoo_suffix,
)

DEFAULT_II_ROOT = t212_coverage_root()

__all__ = [
    "DEFAULT_II_ROOT",
    "annotate_dashboard_reports",
    "annotate_shortlist_rows",
    "build_ii_overlays",
    "build_market_overlay",
    "build_t212_overlays",
    "classify_ticker",
    "ii_coverage_root",
    "load_ii_exceptions",
    "load_ii_policy",
    "load_t212_exceptions",
    "load_t212_policy",
    "t212_coverage_root",
    "yahoo_epic",
    "yahoo_suffix",
]
