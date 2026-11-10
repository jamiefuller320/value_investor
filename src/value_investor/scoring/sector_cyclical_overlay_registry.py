"""Catalogue sector-specific and cyclical overlay hooks for screening exports."""

from __future__ import annotations

from typing import Any

import pandas as pd

from value_investor.scoring.healthcare_overlay import (
    healthcare_overlay_triggered,
    is_healthcare_sector,
    piotroski_score_for_ticker,
    trailing_free_cashflow_for_healthcare_overlay,
)
from value_investor.scoring.sector_overrides import (
    AGRICULTURE_COMMODITIES_SECTOR,
    resolve_scoring_sector,
)
from value_investor.scoring.uk_contractor_overlay import is_uk_listed_contractor

REGISTRY_VERSION = 1

HOOK_AGRICULTURE_COMMODITIES_PLANTATION = "agriculture_commodities_plantation"
HOOK_UK_CONTRACTOR_BACKLOG_MARGIN = "uk_contractor_backlog_margin"
HOOK_HEALTHCARE_NEGATIVE_FCF_LOW_PIOTROSKI = "healthcare_negative_fcf_low_piotroski"

SECTOR_CYCLICAL_OVERLAY_HOOK_IDS = (
    HOOK_AGRICULTURE_COMMODITIES_PLANTATION,
    HOOK_UK_CONTRACTOR_BACKLOG_MARGIN,
    HOOK_HEALTHCARE_NEGATIVE_FCF_LOW_PIOTROSKI,
)

SECTOR_CYCLICAL_OVERLAY_HOOK_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": HOOK_AGRICULTURE_COMMODITIES_PLANTATION,
        "label": "Agriculture/Commodities peer group for plantation issuers",
        "overlay_modules": ("sector_overrides",),
        "signal_columns": ("sector", "sector_composite_score"),
    },
    {
        "id": HOOK_UK_CONTRACTOR_BACKLOG_MARGIN,
        "label": "UK listed contractor backlog, margin, and public-capex cyclical hooks",
        "overlay_modules": (
            "uk_contractor_overlay",
            "cyclical_exposure_overlay",
            "cash_conversion_overlay",
        ),
        "signal_columns": (
            "uk_contractor",
            "uk_contractor_ch_backlog_margin_cyclical_detected",
            "uk_contractor_revenue_fcf_warning",
            "public_capex_exposure_detected",
            "cyclical_exposure_overlay",
        ),
    },
    {
        "id": HOOK_HEALTHCARE_NEGATIVE_FCF_LOW_PIOTROSKI,
        "label": "Healthcare negative trailing FCF with weak Piotroski cap",
        "overlay_modules": ("healthcare_overlay",),
        "signal_columns": ("healthcare_overlay", "adjusted_signal"),
    },
)


def _bool_cell(value: Any) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"1", "true", "yes"}


def _hook_agriculture_commodities_plantation(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
    ticker = data.get("ticker")
    sector = data.get("sector")
    name = data.get("name")
    scoring_sector = resolve_scoring_sector(ticker, sector, name)
    active = scoring_sector == AGRICULTURE_COMMODITIES_SECTOR
    return {
        "id": HOOK_AGRICULTURE_COMMODITIES_PLANTATION,
        "active": active,
        "scoring_sector": scoring_sector,
        "peer_group_override": bool(active and sector and scoring_sector != sector),
    }


def _hook_uk_contractor_backlog_margin(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
    contractor = _bool_cell(data.get("uk_contractor")) or is_uk_listed_contractor(
        data.get("ticker"),
        data.get("name"),
        data.get("sector"),
    )
    backlog = _bool_cell(data.get("uk_contractor_ch_backlog_margin_cyclical_detected"))
    public_capex = _bool_cell(data.get("public_capex_exposure_detected"))
    rev_fcf = _bool_cell(data.get("uk_contractor_revenue_fcf_warning"))
    active = contractor
    return {
        "id": HOOK_UK_CONTRACTOR_BACKLOG_MARGIN,
        "active": active,
        "uk_contractor": contractor,
        "uk_contractor_ch_backlog_margin_cyclical_detected": backlog,
        "public_capex_exposure_detected": public_capex,
        "uk_contractor_revenue_fcf_warning": rev_fcf,
    }


def _hook_healthcare_negative_fcf_low_piotroski(
    row: pd.Series | dict[str, Any],
    *,
    piotroski_f_score: int | None,
) -> dict[str, Any]:
    data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
    sector = data.get("sector")
    eligible = is_healthcare_sector(sector)
    series = row if isinstance(row, pd.Series) else pd.Series(data)
    free_cashflow = trailing_free_cashflow_for_healthcare_overlay(series)
    triggered = healthcare_overlay_triggered(
        sector=sector,
        free_cashflow=free_cashflow,
        piotroski_f_score=piotroski_f_score,
    )
    overlay_applied = _bool_cell(data.get("healthcare_overlay"))
    active = eligible
    return {
        "id": HOOK_HEALTHCARE_NEGATIVE_FCF_LOW_PIOTROSKI,
        "active": active,
        "eligible": eligible,
        "triggered": triggered,
        "overlay_applied": overlay_applied or triggered,
        "piotroski_f_score": piotroski_f_score,
    }


def build_sector_cyclical_overlay_registry(
    row: pd.Series | dict[str, Any],
    *,
    piotroski_f_score: int | None = None,
) -> dict[str, Any]:
    """Build per-issuer sector/cyclical overlay hook snapshot for JSON export."""
    hooks = [
        _hook_agriculture_commodities_plantation(row),
        _hook_uk_contractor_backlog_margin(row),
        _hook_healthcare_negative_fcf_low_piotroski(row, piotroski_f_score=piotroski_f_score),
    ]
    active_hook_ids = [str(h["id"]) for h in hooks if h.get("active")]
    return {
        "registry_version": REGISTRY_VERSION,
        "hooks": hooks,
        "active_hook_ids": active_hook_ids,
    }


def sector_cyclical_overlay_hooks_csv(active_hook_ids: list[str]) -> str:
    """Stable comma-separated hook list for signals CSV columns."""
    return ",".join(sorted(active_hook_ids))


def enrich_signals_with_sector_cyclical_overlay_registry(
    signals: pd.DataFrame,
    model_results: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Attach registry metadata after sector/cyclical overlay enrichment."""
    if signals.empty:
        return signals

    out = signals.copy()
    hook_cols: list[str] = []
    registry_objs: list[dict[str, Any]] = []

    for _, row in out.iterrows():
        piotroski: int | None = None
        if model_results is not None and not model_results.empty:
            ticker = str(row["ticker"])
            ticker_models = model_results[model_results["ticker"] == ticker]
            piotroski = piotroski_score_for_ticker(ticker_models)
        registry = build_sector_cyclical_overlay_registry(row, piotroski_f_score=piotroski)
        registry_objs.append(registry)
        hook_cols.append(sector_cyclical_overlay_hooks_csv(registry.get("active_hook_ids") or []))

    out["sector_cyclical_overlay_hooks"] = hook_cols
    out["sector_cyclical_overlay_registry"] = registry_objs
    return out
