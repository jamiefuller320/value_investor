"""Cyclical-exposure overlay — flag dividend-sustainability risk on cyclical names."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from value_investor.scoring.fcf import (
    fcf_dividend_coverage,
    load_filing_bodies_for_ticker,
    resolve_free_cashflow,
)
from value_investor.scoring.interim_quality_overlay import (
    FCF_DIVIDEND_COVERAGE_MAX,
    quality_family_passed,
)

INTERIM_EPS_DECLINE_THRESHOLD = 0.03

CYCLICAL_KEYWORD_FRAGMENTS = (
    "consumer spending",
    "discretionary spend",
    "discretionary",
    "travel",
    "recession",
    "economic downturn",
    "leisure",
)

ADVERTISING_BROADCASTER_FRAGMENTS = (
    "advertising revenue",
    "total advertising",
    "linear advertising",
    "ad market",
    "ad-funded",
    "broadcast advertising",
)

_AD_BROADCASTER_RES = tuple(
    re.compile(re.escape(fragment), re.IGNORECASE) for fragment in ADVERTISING_BROADCASTER_FRAGMENTS
)

_CYCLICAL_KEYWORD_RES = tuple(
    re.compile(re.escape(fragment), re.IGNORECASE) for fragment in CYCLICAL_KEYWORD_FRAGMENTS
)


def cyclical_exposure_detected(text: str) -> bool:
    """True when filing prose cites principal cyclical or discretionary demand risks."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _CYCLICAL_KEYWORD_RES)


def advertising_broadcaster_detected(
    text: str,
    *,
    sector: str | None = None,
    name: str | None = None,
) -> bool:
    """True for ad-funded broadcasters (ITV-style) even without generic cyclical prose."""
    sector_l = (sector or "").lower()
    name_l = (name or "").lower()
    sector_match = "communication" in sector_l and (
        "broadcast" in name_l or "television" in name_l or " itv" in f" {name_l}"
    )
    if text and any(pattern.search(text) for pattern in _AD_BROADCASTER_RES):
        return True
    return sector_match and bool(text) and "advertising" in text.lower()


def cyclical_exposure_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
    sector: str | None = None,
    name: str | None = None,
) -> bool:
    """Scan cached filing bodies for cyclical-exposure or ad-broadcaster language."""
    bodies = load_filing_bodies_for_ticker(ticker, output_dir=output_dir)
    return any(
        cyclical_exposure_detected(body)
        or advertising_broadcaster_detected(body, sector=sector, name=name)
        for body in bodies
    )


def _dividend_family_passed(passed_families: str | None) -> bool:
    if not passed_families:
        return False
    return "dividend" in {part.strip() for part in str(passed_families).split(",") if part.strip()}


def cyclical_exposure_overlay_triggered(
    *,
    cyclical_exposure_detected_flag: bool,
    passed_families: str | None,
    interim_eps_decline_pct: float | None,
    fcf_dividend_coverage_net: float | None,
    free_cashflow: float | None = None,
    dividends_paid: float | None = None,
    advertising_broadcaster_flag: bool = False,
) -> bool:
    """Cyclical exposure, quality passes, interim EPS decline, and thin net FCF/dividend cover."""
    if not cyclical_exposure_detected_flag:
        return False

    coverage = fcf_dividend_coverage_net
    if coverage is None:
        coverage = fcf_dividend_coverage(free_cashflow, dividends_paid)
    if advertising_broadcaster_flag and _dividend_family_passed(passed_families):
        if coverage is not None and coverage < FCF_DIVIDEND_COVERAGE_MAX:
            return True

    if not quality_family_passed(passed_families):
        return False
    if interim_eps_decline_pct is None or (
        isinstance(interim_eps_decline_pct, float) and pd.isna(interim_eps_decline_pct)
    ):
        return False
    if float(interim_eps_decline_pct) <= INTERIM_EPS_DECLINE_THRESHOLD:
        return False
    if coverage is None or coverage >= FCF_DIVIDEND_COVERAGE_MAX:
        return False
    return True


def cap_signal_for_cyclical_exposure_overlay(signal: str) -> str:
    """Cap at research-equivalent caution: strong_buy -> buy, buy -> hold."""
    if signal == "strong_buy":
        return "buy"
    if signal == "buy":
        return "hold"
    return signal


_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def _more_conservative_signal(current: str, candidate: str) -> str:
    current_rank = _SIGNAL_RANK.get(current, 0)
    candidate_rank = _SIGNAL_RANK.get(candidate, 0)
    return current if current_rank <= candidate_rank else candidate


def apply_cyclical_exposure_overlay_to_signal(
    signal: str,
    *,
    cyclical_exposure_detected_flag: bool,
    passed_families: str | None,
    interim_eps_decline_pct: float | None,
    fcf_dividend_coverage_net: float | None,
    free_cashflow: float | None = None,
    dividends_paid: float | None = None,
    advertising_broadcaster_flag: bool = False,
    adjusted_signal: str | None = None,
) -> tuple[bool, str]:
    """Return overlay flag and conservative adjusted signal."""
    base_adjusted = adjusted_signal or signal
    if not cyclical_exposure_overlay_triggered(
        cyclical_exposure_detected_flag=cyclical_exposure_detected_flag,
        passed_families=passed_families,
        interim_eps_decline_pct=interim_eps_decline_pct,
        fcf_dividend_coverage_net=fcf_dividend_coverage_net,
        free_cashflow=free_cashflow,
        dividends_paid=dividends_paid,
        advertising_broadcaster_flag=advertising_broadcaster_flag,
    ):
        return False, base_adjusted
    capped = cap_signal_for_cyclical_exposure_overlay(signal)
    return True, _more_conservative_signal(base_adjusted, capped)


def enrich_signals_with_cyclical_exposure_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Add cyclical-exposure overlay flag and cap ``adjusted_signal`` when triggered."""
    _ = model_results
    out = signals.copy()
    flags: list[bool] = []
    detected_flags: list[bool] = []
    ad_broadcaster_flags: list[bool] = []
    adjusted: list[str] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        cyclical_flag = row.get("cyclical_exposure_detected")
        sector = row.get("sector")
        name = row.get("name")
        if cyclical_flag is not None and not (
            isinstance(cyclical_flag, float) and pd.isna(cyclical_flag)
        ):
            cyclical_detected = bool(cyclical_flag)
        else:
            cyclical_detected = cyclical_exposure_for_ticker(
                ticker,
                output_dir=output_dir,
                sector=str(sector) if sector is not None else None,
                name=str(name) if name is not None else None,
            )

        ad_broadcaster_flag = row.get("advertising_broadcaster_detected")
        if ad_broadcaster_flag is not None and not (
            isinstance(ad_broadcaster_flag, float) and pd.isna(ad_broadcaster_flag)
        ):
            advertising_broadcaster = bool(ad_broadcaster_flag)
        else:
            bodies = load_filing_bodies_for_ticker(ticker, output_dir=output_dir)
            advertising_broadcaster = any(
                advertising_broadcaster_detected(
                    body,
                    sector=str(sector) if sector is not None else None,
                    name=str(name) if name is not None else None,
                )
                for body in bodies
            )

        interim_decline = row.get("interim_eps_decline_pct")
        interim_eps_decline_pct = (
            float(interim_decline)
            if interim_decline is not None
            and not (isinstance(interim_decline, float) and pd.isna(interim_decline))
            else None
        )

        dividends = row.get("dividends_paid")
        dividends_paid = (
            float(dividends)
            if dividends is not None and not (isinstance(dividends, float) and pd.isna(dividends))
            else None
        )

        coverage_net = row.get("fcf_dividend_coverage_net")
        fcf_dividend_coverage_net = (
            float(coverage_net)
            if coverage_net is not None
            and not (isinstance(coverage_net, float) and pd.isna(coverage_net))
            else None
        )

        cyclical_detected = cyclical_detected or advertising_broadcaster

        triggered, new_adjusted = apply_cyclical_exposure_overlay_to_signal(
            str(row.get("signal") or "hold"),
            cyclical_exposure_detected_flag=cyclical_detected,
            passed_families=row.get("passed_families"),
            interim_eps_decline_pct=interim_eps_decline_pct,
            fcf_dividend_coverage_net=fcf_dividend_coverage_net,
            free_cashflow=resolve_free_cashflow(row),
            dividends_paid=dividends_paid,
            advertising_broadcaster_flag=advertising_broadcaster,
            adjusted_signal=existing_adjusted,
        )
        flags.append(triggered)
        detected_flags.append(cyclical_detected)
        ad_broadcaster_flags.append(advertising_broadcaster)
        adjusted.append(new_adjusted)

    out["cyclical_exposure_detected"] = detected_flags
    out["advertising_broadcaster_detected"] = ad_broadcaster_flags
    out["cyclical_exposure_overlay"] = flags
    out["adjusted_signal"] = adjusted
    return out
