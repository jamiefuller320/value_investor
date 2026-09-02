"""Structured research verdict parsing and signal overlay rules."""

from __future__ import annotations

import re
from typing import Literal

ResearchVerdict = Literal["accumulate", "neutral", "caution", "pass"]
ResearchRiskLevel = Literal["low", "medium", "high"]

VERDICT_LABELS = {
    "accumulate": "Accumulate",
    "neutral": "Neutral",
    "caution": "Caution",
    "pass": "Pass",
}

_RISK_LABELS = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
}

ALLOWED_RISK_TAGS = frozenset(
    {
        "regulatory",
        "cyclical",
        "governance",
        "pension",
        "competitive",
        "liquidity",
        "leverage",
        "customer_concentration",
        "key_person",
        "litigation",
        "accounting",
        "other",
    }
)

_RISK_TAG_ALIASES = {
    "customer-concentration": "customer_concentration",
    "customer concentration": "customer_concentration",
    "concentration": "customer_concentration",
    "key-person": "key_person",
    "key person": "key_person",
    "keyperson": "key_person",
    "balance sheet": "leverage",
    "going concern": "liquidity",
}


def parse_risk_tags(text: str) -> list[str]:
    """Parse ``RiskTags: a, b, c`` from risks prose or free text; keep known tags only."""
    tags: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if not (
            lower.startswith("risktags:")
            or lower.startswith("risk tags:")
            or lower.startswith("tags:")
        ):
            continue
        raw = stripped.split(":", 1)[1]
        for part in raw.split(","):
            token = re.sub(r"[^a-z0-9_\-\s]", "", part.strip().lower())
            token = token.strip()
            if not token:
                continue
            normalised = _RISK_TAG_ALIASES.get(token, token.replace("-", "_").replace(" ", "_"))
            if normalised in ALLOWED_RISK_TAGS and normalised not in tags:
                tags.append(normalised)
    return tags


def _normalise_verdict(value: str | None) -> ResearchVerdict | None:
    if not value:
        return None
    key = value.strip().lower()
    if key in VERDICT_LABELS:
        return key  # type: ignore[return-value]
    if key in ("buy", "confirm", "confirmed", "accumulate"):
        return "accumulate"
    if key in ("hold", "watch", "watchlist"):
        return "neutral"
    if key in ("avoid", "reject", "skip"):
        return "pass"
    if "caution" in key or "warn" in key:
        return "caution"
    return None


def coerce_research_verdict(value: str | None) -> ResearchVerdict | None:
    """
    Normalise a research verdict from a slug (``accumulate``) or a rendered block
    (``Verdict: accumulate\\nRisk: medium\\n...``).
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    direct = _normalise_verdict(text)
    if direct is not None:
        return direct
    if "\n" in text or text.lower().startswith("verdict:"):
        parsed = parse_research_verdict(text)
        verdict = parsed.get("research_verdict")
        if isinstance(verdict, str):
            return _normalise_verdict(verdict)
    return None


def _normalise_risk(value: str | None) -> ResearchRiskLevel | None:
    if not value:
        return None
    key = value.strip().lower()
    if key in _RISK_LABELS:
        return key  # type: ignore[return-value]
    return None


def parse_research_verdict(text: str) -> dict[str, str | float | None]:
    """Parse RESEARCH VERDICT section into structured fields."""
    verdict = None
    risk_level = None
    confidence = None
    rationale = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("verdict:"):
            verdict = _normalise_verdict(stripped.split(":", 1)[1])
        elif lower.startswith("risk level:") or lower.startswith("risk:"):
            risk_level = _normalise_risk(stripped.split(":", 1)[1])
        elif lower.startswith("confidence:"):
            raw = stripped.split(":", 1)[1].strip()
            match = re.search(r"(\d+(?:\.\d+)?)", raw)
            if match:
                value = float(match.group(1))
                confidence = value / 100 if value > 1 else value
        elif lower.startswith("rationale:"):
            rationale = stripped.split(":", 1)[1].strip()

    return {
        "research_verdict": verdict,
        "research_risk_level": risk_level,
        "research_confidence": confidence,
        "research_rationale": rationale,
    }


def compute_adjusted_signal(signal: str, verdict: ResearchVerdict | None) -> str:
    """Apply research overlay without mutating the quantitative screen signal."""
    if verdict is None or verdict in ("accumulate", "neutral"):
        return signal
    if verdict == "caution":
        if signal == "strong_buy":
            return "buy"
        if signal == "buy":
            return "hold"
        return signal
    if verdict == "pass":
        if signal in ("strong_buy", "buy"):
            return "hold"
        return signal
    return signal


_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def more_conservative_signal(*signals: str | None) -> str:
    """Return the most conservative non-null signal (lowest conviction tier)."""
    ranked = [str(signal) for signal in signals if signal]
    if not ranked:
        return "hold"
    return min(ranked, key=lambda signal: _SIGNAL_RANK.get(signal, 0))


def effective_screen_signal(report_signal: str, adjusted_signal: str | None) -> str:
    """Prefer FCF-/research-adjusted signal when present for gating spend."""
    if adjusted_signal:
        return more_conservative_signal(report_signal, adjusted_signal)
    return report_signal


def adjust_conviction_for_research(
    conviction_score: float,
    verdict: ResearchVerdict | None,
) -> float:
    if verdict is None:
        return conviction_score
    if verdict == "accumulate":
        return min(1.0, conviction_score + 0.05)
    if verdict == "neutral":
        return conviction_score
    if verdict == "caution":
        return max(0.0, conviction_score * 0.85)
    if verdict == "pass":
        return max(0.0, conviction_score * 0.7)
    return conviction_score


def format_research_action_note(
    *,
    verdict: ResearchVerdict | None,
    risk_level: ResearchRiskLevel | None,
    rationale: str | None,
    adjusted_signal: str | None,
    signal: str,
) -> str | None:
    if verdict is None:
        return None
    label = VERDICT_LABELS.get(verdict, verdict.title())
    risk_text = f", {_RISK_LABELS.get(risk_level, risk_level)} risk" if risk_level else ""
    note = f"Research: {label}{risk_text}"
    if adjusted_signal and adjusted_signal != signal:
        note += f" (adjusted to {adjusted_signal.replace('_', ' ')})"
    if rationale:
        note += f" — {rationale}"
    return note
