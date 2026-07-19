"""Per-ticker deep research for buy-tier recommendations."""

from value_investor.research.document import ResearchDocument, ResearchSummary
from value_investor.research.overlay import apply_research_overlay, enrich_signals_with_research
from value_investor.research.timeline import get_research_as_of
from value_investor.research.gap_fill import (
    DEFAULT_GAP_FILL_CAP,
    extract_gap_fill_targets,
    run_red_flag_gap_fill,
)
from value_investor.research.runner import (
    DEFAULT_RESEARCH_ALUMNI_CAP,
    DEFAULT_RESEARCH_WEEKLY_CAP,
    eligible_alumni_research_targets,
    eligible_research_targets,
    run_research_for_strong_buys,
    select_research_targets,
)
from value_investor.research.verdict import (
    adjust_conviction_for_research,
    compute_adjusted_signal,
    format_research_action_note,
    parse_research_verdict,
)

__all__ = [
    "DEFAULT_GAP_FILL_CAP",
    "DEFAULT_RESEARCH_ALUMNI_CAP",
    "DEFAULT_RESEARCH_WEEKLY_CAP",
    "ResearchDocument",
    "ResearchSummary",
    "apply_research_overlay",
    "adjust_conviction_for_research",
    "compute_adjusted_signal",
    "eligible_alumni_research_targets",
    "eligible_research_targets",
    "enrich_signals_with_research",
    "extract_gap_fill_targets",
    "get_research_as_of",
    "format_research_action_note",
    "parse_research_verdict",
    "run_red_flag_gap_fill",
    "run_research_for_strong_buys",
    "select_research_targets",
]
