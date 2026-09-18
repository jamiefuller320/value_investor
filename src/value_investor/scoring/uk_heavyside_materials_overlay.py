"""UK heavyside construction-materials overlays — GB volume + cement-cycle tape."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from value_investor.scoring.fcf import load_filing_bodies_for_ticker
from value_investor.storage import read_json, resolve_json_path

_RESEARCH_ROOTS = (
    Path("docs/data/research"),
    Path("output/research"),
)

UK_HEAVYSIDE_TICKERS = frozenset({"BREE.L"})

UK_HEAVYSIDE_NAME_FRAGMENTS = (
    "breedon",
    "construction materials",
    "aggregates group",
    "heavyside",
    "heavy-side",
    "ready-mixed concrete",
    "ready mixed concrete",
)

GB_VOLUME_FRAGMENTS = (
    "gb volume",
    "gb volumes",
    "lower gb",
    "great britain volume",
    "great britain volumes",
    "volumes in gb",
    "volumes in great britain",
)

_GB_VOLUME_RES = tuple(
    re.compile(re.escape(fragment), re.IGNORECASE) for fragment in GB_VOLUME_FRAGMENTS
)

_CEMENT_CONTEXT_RES = re.compile(
    r"cement|back british cement",
    re.IGNORECASE,
)
_HISTORIC_LOW_RES = re.compile(
    r"historic\s+lows?|hits historic lows",
    re.IGNORECASE,
)


def _overlay_text(value: object | None) -> str:
    """Coerce pandas/NaN-safe text fields from screen rows (sector/name may be float)."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def is_uk_heavyside_construction_materials(
    ticker: str | None,
    name: str | None,
    sector: str | None = None,
) -> bool:
    """True for LSE heavyside construction-materials names (aggregates/cement)."""
    if ticker and str(ticker).upper() in UK_HEAVYSIDE_TICKERS:
        return True
    if not ticker or not str(ticker).strip().upper().endswith(".L"):
        return False
    name_l = _overlay_text(name).lower()
    if any(fragment in name_l for fragment in UK_HEAVYSIDE_NAME_FRAGMENTS):
        return True
    sector_l = _overlay_text(sector).lower()
    return "basic materials" in sector_l and "materials" in name_l


def gb_volume_language_detected(text: str) -> bool:
    """True when prose cites challenged Great Britain / GB product volumes."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _GB_VOLUME_RES)


def cement_output_historic_lows_detected(text: str) -> bool:
    """True when prose links cement output (or campaign) to historic-low language."""
    if not text:
        return False
    return bool(_CEMENT_CONTEXT_RES.search(text) and _HISTORIC_LOW_RES.search(text))


def heavyside_cyclical_tape_detected(text: str) -> bool:
    """Both GB volume and cement historic-low language appear on the same research tape."""
    if not text:
        return False
    return gb_volume_language_detected(text) and cement_output_historic_lows_detected(text)


def _news_manifest_candidates(ticker: str, output_dir: Path | None) -> list[Path]:
    ticker = ticker.strip().upper()
    candidates: list[Path] = []
    if output_dir is not None:
        candidates.append(Path(output_dir) / "research" / ticker / "sources" / "news_manifest.json")
    for root in _RESEARCH_ROOTS:
        candidates.append(root / ticker / "sources" / "news_manifest.json")
    return candidates


def load_news_tape_snippets(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> list[str]:
    """Load cached news manifest title/summary snippets for ``ticker``."""
    snippets: list[str] = []
    for path in _news_manifest_candidates(ticker, output_dir):
        resolved = resolve_json_path(path)
        if resolved is None:
            continue
        try:
            payload = read_json(resolved)
        except (OSError, ValueError, TypeError):
            continue
        articles = payload.get("articles") if isinstance(payload, dict) else payload
        if not isinstance(articles, list):
            continue
        for row in articles:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            summary = str(row.get("summary") or "").strip()
            text = f"{title}\n{summary}".strip()
            if text:
                snippets.append(text)
        if snippets:
            break
    return snippets


def load_heavyside_research_tape(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> str:
    """Filings bodies plus news snippets — the screening research tape for one ticker."""
    bodies = load_filing_bodies_for_ticker(ticker, output_dir=output_dir)
    news = load_news_tape_snippets(ticker, output_dir=output_dir)
    return "\n\n".join(part for part in (*bodies, *news) if part.strip())


def heavyside_cyclical_tape_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> bool:
    """True when GB volume and cement historic-low language share the same tape."""
    tape = load_heavyside_research_tape(ticker, output_dir=output_dir)
    if heavyside_cyclical_tape_detected(tape):
        return True
    bodies = load_filing_bodies_for_ticker(ticker, output_dir=output_dir)
    news = load_news_tape_snippets(ticker, output_dir=output_dir)
    return any(heavyside_cyclical_tape_detected(body) for body in (*bodies, *news))


def uk_heavyside_cyclical_overlay_triggered(
    *,
    uk_heavyside_materials: bool,
    heavyside_cyclical_tape_detected: bool,
) -> bool:
    if not uk_heavyside_materials or not heavyside_cyclical_tape_detected:
        return False
    return True


def enrich_signals_with_uk_heavyside_detection(
    signals: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Tag UK heavyside materials and GB/cement cyclical tape before downstream overlays."""
    if signals.empty:
        return signals

    out = signals.copy()
    heavyside_flags: list[bool] = []
    tape_flags: list[bool] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        heavyside = bool(
            row.get("uk_heavyside_materials")
        ) or is_uk_heavyside_construction_materials(
            ticker,
            row.get("name"),
            row.get("sector"),
        )
        tape_raw = row.get("heavyside_cyclical_tape_detected")
        if tape_raw is not None and not (isinstance(tape_raw, float) and pd.isna(tape_raw)):
            tape_detected = bool(tape_raw)
        elif heavyside:
            tape_detected = heavyside_cyclical_tape_for_ticker(ticker, output_dir=output_dir)
        else:
            tape_detected = False

        heavyside_flags.append(heavyside)
        tape_flags.append(tape_detected)

    out["uk_heavyside_materials"] = heavyside_flags
    out["heavyside_cyclical_tape_detected"] = tape_flags
    if "cyclical_exposure_detected" in out.columns:
        out["cyclical_exposure_detected"] = [
            bool(existing) or tape
            for existing, tape in zip(
                out["cyclical_exposure_detected"].tolist(),
                tape_flags,
                strict=True,
            )
        ]
    else:
        out["cyclical_exposure_detected"] = tape_flags

    return out
