"""Photobooth cyclical exposure — principal-risk language plus interim monthly revenue drops."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from value_investor.scoring.fcf import load_filing_bodies_for_ticker

PHOTOBOOTH_INTERIM_REVENUE_DECLINE_THRESHOLD = 0.10

_PRINCIPAL_RISK_HEADING_RE = re.compile(
    r"\bprincipal\s+risks?(?:\s+and\s+uncertainties)?\b",
    re.IGNORECASE,
)
_PRINCIPAL_RISK_NEXT_SECTION_RE = re.compile(
    r"\n\s*(?:Sustainability|TCFD|Longer-term viability|Corporate governance|"
    r"Directors['’] report|Governance|Financial statements)\b",
    re.IGNORECASE,
)

_PRINCIPAL_RISK_CYCLICAL_RES = (
    re.compile(r"\brecession\b", re.IGNORECASE),
    re.compile(r"\bdiscretionary\s+(?:spending|spend|demand)\b", re.IGNORECASE),
    re.compile(r"\bconsumer\s+spending\b", re.IGNORECASE),
    re.compile(r"\beconomic\s+downturn\b", re.IGNORECASE),
)

_PHOTOBOOTH_MONTH_DECLINE_RES = (
    re.compile(
        r"(?:Photo\.ME|photobooth(?:\s+(?:vending\s+)?revenue)?(?:\s+activity)?)"
        r"[^.\n]{0,160}?"
        r"(?:down|declin(?:e|ed)|decreas(?:e|ed)|fall(?:en)?|−|-)\s*"
        r"(\d+(?:\.\d+)?)\s*%"
        r"[^.\n]{0,100}?"
        r"\b(?:in|for|during)\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|for|during)\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\b"
        r"[^.\n]{0,120}?"
        r"(?:Photo\.ME|photobooth(?:\s+(?:vending\s+)?revenue)?)"
        r"[^.\n]{0,120}?"
        r"(?:down|declin(?:e|ed)|decreas(?:e|ed)|fall(?:en)?|−|-)\s*"
        r"(\d+(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    ),
)


def extract_principal_risk_section(text: str, *, max_chars: int = 8000) -> str:
    """Return filing prose from the principal-risks heading through the next major section."""
    if not text or not text.strip():
        return ""
    match = _PRINCIPAL_RISK_HEADING_RE.search(text)
    if match is None:
        return ""
    start = match.start()
    remainder = text[start:]
    section_end = _PRINCIPAL_RISK_NEXT_SECTION_RE.search(remainder[200:])
    if section_end is not None:
        end = start + 200 + section_end.start()
    else:
        end = min(len(text), start + max_chars)
    return text[start:end]


def principal_risk_cyclical_language_detected(text: str) -> bool:
    """True when principal-risk prose cites recession or discretionary demand risks."""
    section = extract_principal_risk_section(text)
    if not section or len(section.strip()) < 80:
        return False
    return any(pattern.search(section) for pattern in _PRINCIPAL_RISK_CYCLICAL_RES)


def principal_risk_cyclical_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> bool:
    """Scan indexed filing bodies for principal-risk cyclical language."""
    return any(
        principal_risk_cyclical_language_detected(body)
        for body in load_filing_bodies_for_ticker(ticker, output_dir=output_dir)
    )


def parse_photobooth_interim_month_revenue_declines(text: str) -> list[tuple[str, float]]:
    """Parse (month, positive decline fraction) pairs for Photo.ME / photobooth revenue."""
    if not text:
        return []
    found: list[tuple[str, float]] = []
    for pattern in _PHOTOBOOTH_MONTH_DECLINE_RES:
        for match in pattern.finditer(text):
            groups = match.groups()
            if len(groups) == 2 and groups[0] in (
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ):
                month, pct_raw = str(groups[0]), groups[1]
            else:
                pct_raw, month = groups[0], str(groups[1])
            try:
                pct = float(pct_raw) / 100.0
            except (TypeError, ValueError):
                continue
            if pct > 0:
                found.append((month, pct))
    return found


def max_photobooth_interim_month_revenue_decline_pct(text: str) -> float | None:
    """Largest interim-month photobooth revenue decline parsed from filing prose."""
    declines = parse_photobooth_interim_month_revenue_declines(text)
    if not declines:
        return None
    return max(pct for _, pct in declines)


def photobooth_interim_month_revenue_decline_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> float | None:
    """Largest Photo.ME / photobooth monthly revenue decline across indexed filing bodies."""
    best: float | None = None
    for body in load_filing_bodies_for_ticker(ticker, output_dir=output_dir):
        parsed = max_photobooth_interim_month_revenue_decline_pct(body)
        if parsed is None:
            continue
        if best is None or parsed > best:
            best = parsed
    return best


def photobooth_cyclical_profile_detected(
    *,
    principal_risk_cyclical: bool,
    photobooth_interim_revenue_decline_pct: float | None,
) -> bool:
    """Both principal-risk cyclical language and a >10% interim-month photobooth drop."""
    if not principal_risk_cyclical:
        return False
    if photobooth_interim_revenue_decline_pct is None or (
        isinstance(photobooth_interim_revenue_decline_pct, float)
        and pd.isna(photobooth_interim_revenue_decline_pct)
    ):
        return False
    return (
        float(photobooth_interim_revenue_decline_pct) > PHOTOBOOTH_INTERIM_REVENUE_DECLINE_THRESHOLD
    )


def photobooth_cyclical_overlay_triggered(
    *,
    photobooth_cyclical_detected: bool,
    passed_families: str | None,
    photobooth_interim_revenue_decline_pct: float | None,
    fcf_dividend_coverage_net: float | None,
    free_cashflow: float | None = None,
    dividends_paid: float | None = None,
) -> bool:
    """Principal-risk cyclicality with interim photobooth revenue drop and thin dividend cover."""
    from value_investor.scoring.fcf import fcf_dividend_coverage
    from value_investor.scoring.interim_quality_overlay import (
        FCF_DIVIDEND_COVERAGE_MAX,
        quality_family_passed,
    )

    if not photobooth_cyclical_detected:
        return False
    if not quality_family_passed(passed_families):
        return False
    if not photobooth_cyclical_profile_detected(
        principal_risk_cyclical=True,
        photobooth_interim_revenue_decline_pct=photobooth_interim_revenue_decline_pct,
    ):
        return False
    coverage = fcf_dividend_coverage_net
    if coverage is None:
        coverage = fcf_dividend_coverage(free_cashflow, dividends_paid)
    if coverage is None or coverage >= FCF_DIVIDEND_COVERAGE_MAX:
        return False
    return True


def enrich_signals_with_photobooth_cyclical_detection(
    signals: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Flag photobooth cyclical exposure before the cyclical-exposure overlay runs."""
    if signals.empty:
        return signals

    out = signals.copy()
    if "cyclical_exposure_detected" not in out.columns:
        out["cyclical_exposure_detected"] = False

    principal_flags: list[bool] = []
    decline_pcts: list[float | None] = []
    profile_flags: list[bool] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])

        principal_raw = row.get("principal_risk_cyclical_detected")
        if principal_raw is not None and not (
            isinstance(principal_raw, float) and pd.isna(principal_raw)
        ):
            principal_detected = bool(principal_raw)
        else:
            principal_detected = principal_risk_cyclical_for_ticker(ticker, output_dir=output_dir)

        decline_raw = row.get("photobooth_interim_revenue_decline_pct")
        if decline_raw is not None and not (
            isinstance(decline_raw, float) and pd.isna(decline_raw)
        ):
            decline_pct = float(decline_raw)
        else:
            decline_pct = photobooth_interim_month_revenue_decline_for_ticker(
                ticker,
                output_dir=output_dir,
            )

        profile = photobooth_cyclical_profile_detected(
            principal_risk_cyclical=principal_detected,
            photobooth_interim_revenue_decline_pct=decline_pct,
        )

        existing = row.get("cyclical_exposure_detected")
        cyclical_detected = False
        if existing is not None and not (isinstance(existing, float) and pd.isna(existing)):
            cyclical_detected = bool(existing)
        if profile:
            cyclical_detected = True

        principal_flags.append(principal_detected)
        decline_pcts.append(decline_pct)
        profile_flags.append(profile)
        out.at[row.name, "cyclical_exposure_detected"] = cyclical_detected

    out["principal_risk_cyclical_detected"] = principal_flags
    out["photobooth_interim_revenue_decline_pct"] = decline_pcts
    out["photobooth_cyclical_detected"] = profile_flags
    return out
