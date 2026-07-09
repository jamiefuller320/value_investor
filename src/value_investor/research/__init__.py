"""Per-ticker deep research for strong buy recommendations."""

from value_investor.research.document import ResearchDocument, ResearchSummary
from value_investor.research.runner import run_research_for_strong_buys

__all__ = [
    "ResearchDocument",
    "ResearchSummary",
    "run_research_for_strong_buys",
]
