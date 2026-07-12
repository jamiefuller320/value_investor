"""Per-ticker deep research for strong buy recommendations."""

from value_investor.research.document import ResearchDocument, ResearchSummary
from value_investor.research.overlay import apply_research_overlay, enrich_signals_with_research
from value_investor.research.timeline import get_research_as_of
from value_investor.research.runner import run_research_for_strong_buys
from value_investor.research.verdict import (
    adjust_conviction_for_research,
    compute_adjusted_signal,
    format_research_action_note,
    parse_research_verdict,
)

__all__ = [
    "ResearchDocument",
    "ResearchSummary",
    "apply_research_overlay",
    "adjust_conviction_for_research",
    "compute_adjusted_signal",
    "enrich_signals_with_research",
    "get_research_as_of",
    "format_research_action_note",
    "parse_research_verdict",
    "run_research_for_strong_buys",
]
