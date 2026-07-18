"""Cross-market ticker identity and dedupe for offline libraries.

Index slices overlap heavily (e.g. S&P 500 ∩ Nasdaq-100). Exact Yahoo ticker
match is the identity key — dual-listed names with different suffixes (SHEL.L vs
SHEL) are treated as distinct because they are separate Yahoo instruments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


def canonical_library_ticker(ticker: str) -> str:
    """Normalise a Yahoo-style ticker for cross-market equality checks."""
    return str(ticker or "").strip().upper()


def existing_library_research_tickers(root: Path) -> set[str]:
    """
    Tickers that already have a ``research.md`` under any market library.

    Used so a buy-tier name researched under ``sp500`` is not memo'd again under
    ``nasdaq100``.
    """
    markets_root = Path(root) / "markets"
    found: set[str] = set()
    if not markets_root.is_dir():
        return found
    for market_dir in markets_root.iterdir():
        if not market_dir.is_dir():
            continue
        research = market_dir / "screen" / "research"
        if not research.is_dir():
            continue
        for entry in research.iterdir():
            if entry.is_dir() and (entry / "research.md").exists():
                found.add(canonical_library_ticker(entry.name))
    return found


def research_home_market(root: Path, ticker: str) -> str | None:
    """First market (lexicographic path order) that already holds a memo for ticker."""
    key = canonical_library_ticker(ticker)
    markets_root = Path(root) / "markets"
    if not markets_root.is_dir():
        return None
    for market_dir in sorted(markets_root.iterdir(), key=lambda p: p.name):
        if (market_dir / "screen" / "research" / key / "research.md").exists():
            return market_dir.name
        # Directory names preserve original casing from when memo was written.
        research = market_dir / "screen" / "research"
        if not research.is_dir():
            continue
        for entry in research.iterdir():
            if entry.is_dir() and canonical_library_ticker(entry.name) == key:
                if (entry / "research.md").exists():
                    return market_dir.name
    return None


def select_deduped_research_targets(
    *,
    research_markets: list[str],
    per_market_queues: dict[str, list[Any]],
    research_cap: int,
    already_researched: set[str] | None = None,
) -> tuple[list[tuple[str, Any]], list[dict[str, str]]]:
    """
    Round-robin pick buy-tier targets, skipping tickers already claimed.

    Preference: earlier ``research_markets`` order wins within a run; tickers in
    ``already_researched`` (existing memos) are skipped entirely.

    Returns ``(selected, skipped)`` where skipped entries explain dedupe reasons.
    """
    seen = {canonical_library_ticker(t) for t in (already_researched or set())}
    # Copy queues so callers retain originals if needed.
    queues: dict[str, list[Any]] = {
        mid: list(per_market_queues.get(mid) or []) for mid in research_markets
    }
    selected: list[tuple[str, Any]] = []
    skipped: list[dict[str, str]] = []

    while len(selected) < max(0, int(research_cap)):
        progressed = False
        for mid in research_markets:
            queue = queues.get(mid) or []
            while queue:
                report = queue.pop(0)
                key = canonical_library_ticker(getattr(report, "ticker", ""))
                if not key:
                    continue
                if key in seen:
                    skipped.append(
                        {
                            "market": mid,
                            "ticker": str(getattr(report, "ticker", key)),
                            "reason": "duplicate_ticker",
                        }
                    )
                    continue
                seen.add(key)
                selected.append((mid, report))
                progressed = True
                break
            if len(selected) >= research_cap:
                break
        if not progressed:
            break
    return selected, skipped


def summarize_ticker_overlaps(
    market_tickers: dict[str, Iterable[str]],
) -> dict[str, Any]:
    """ pairwise exact-ticker overlaps for status / CLI."""
    normalized: dict[str, set[str]] = {
        mid: {canonical_library_ticker(t) for t in tickers if t}
        for mid, tickers in market_tickers.items()
    }
    mids = sorted(normalized)
    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(mids):
        for b in mids[i + 1 :]:
            inter = sorted(normalized[a] & normalized[b])
            if not inter:
                continue
            pairs.append(
                {
                    "markets": [a, b],
                    "overlap_count": len(inter),
                    "sample": inter[:10],
                }
            )
    pairs.sort(key=lambda row: (-int(row["overlap_count"]), row["markets"][0], row["markets"][1]))
    multi = 0
    inv: dict[str, set[str]] = {}
    for mid, tickers in normalized.items():
        for t in tickers:
            inv.setdefault(t, set()).add(mid)
    multi = sum(1 for ms in inv.values() if len(ms) >= 2)
    return {
        "markets": mids,
        "tickers_in_multiple_markets": multi,
        "pairs": pairs,
        "note": (
            "Exact Yahoo ticker match only. Dual-listed names with different "
            "suffixes are not merged."
        ),
    }
