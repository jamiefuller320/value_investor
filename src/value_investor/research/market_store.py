"""Market-agnostic research store resolution and rememo eligibility.

FTSE live memos live under ``docs/data/research/``. Library shards live under
``docs/data/library/markets/<id>/screen/research/``. Overlay, publish, paper,
and the Sunday ladder all resolve documents through this module so a newly
in-scope market inherits the same wiring without a per-market special case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from value_investor.research.document import ResearchDocument
from value_investor.research.store import ResearchStore
from value_investor.storage import read_json

FTSE_MARKET_ID = "ftse350"
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_REMEMO_BODY_LAG_THRESHOLD = 10


def is_ftse_market(market_id: str | None) -> bool:
    mid = str(market_id or "").strip().lower()
    return mid in {"", FTSE_MARKET_ID, "ftse"}


def committed_research_dir(
    market_id: str | None = FTSE_MARKET_ID,
    *,
    library_root: Path | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> Path:
    """Canonical memo root for a market (FTSE or one library shard)."""
    if is_ftse_market(market_id):
        return Path(data_dir) / "research"
    root = Path(library_root or DEFAULT_LIBRARY_ROOT)
    return root / "markets" / str(market_id).strip() / "screen" / "research"


def sibling_research_dirs(
    library_root: Path,
    *,
    exclude: Path | None = None,
) -> list[Path]:
    """Every ``markets/*/screen/research`` tree under a library root."""
    markets = Path(library_root) / "markets"
    if not markets.is_dir():
        return []
    exclude_key = exclude.resolve() if exclude is not None and exclude.exists() else None
    found: list[Path] = []
    for market_dir in sorted(p for p in markets.iterdir() if p.is_dir()):
        research = market_dir / "screen" / "research"
        if not research.is_dir():
            continue
        if exclude_key is not None:
            try:
                if research.resolve() == exclude_key:
                    continue
            except OSError:
                pass
        found.append(research)
    return found


def library_research_dirs(library_root: Path, market_id: str) -> list[Path]:
    """Focus-market research dir first, then sibling shard homes."""
    focus = committed_research_dir(market_id, library_root=library_root)
    ordered = [focus]
    for path in sibling_research_dirs(library_root, exclude=focus):
        ordered.append(path)
    return ordered


def list_documents_from_research_root(research_root: Path) -> list[ResearchDocument]:
    """Load memos from a directory that already *is* the ``research/`` folder."""
    root = Path(research_root)
    if not root.is_dir():
        return []
    return ResearchStore(root.parent).list_documents()


def documents_from_research_index(items: list[dict[str, Any]]) -> list[ResearchDocument]:
    """Slim ``ResearchDocument`` list from a dashboard ``research[]`` index."""
    documents: list[ResearchDocument] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ticker = item.get("ticker")
        if not ticker:
            continue
        confidence = item.get("research_confidence")
        documents.append(
            ResearchDocument(
                ticker=str(ticker),
                name=str(item.get("name") or ticker),
                signal="strong_buy",
                version=int(item.get("version") or 1),
                created_at=str(item.get("updated_at") or ""),
                updated_at=str(item.get("updated_at") or ""),
                mode="initial",
                research_verdict=item.get("research_verdict"),
                research_risk_level=item.get("research_risk_level"),
                research_confidence=float(confidence) if confidence is not None else None,
            )
        )
    return documents


def merge_documents_by_ticker(
    *groups: Iterable[ResearchDocument],
) -> list[ResearchDocument]:
    """First group wins per ticker (case-insensitive)."""
    by_ticker: dict[str, ResearchDocument] = {}
    for group in groups:
        for doc in group:
            key = str(doc.ticker or "").strip().upper()
            if key and key not in by_ticker:
                by_ticker[key] = doc
    return list(by_ticker.values())


def resolve_research_documents(
    *,
    market_id: str | None = FTSE_MARKET_ID,
    output_dir: Path | None = None,
    bundle: dict[str, Any] | None = None,
    committed_dir: Path | None = None,
    library_root: Path | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> list[ResearchDocument]:
    """
    Union of this-run output, the committed market store, sibling library
    homes, and a dashboard ``research[]`` index.

    Earlier sources win so a just-written memo beats a committed copy, and a
    committed copy beats a stale publish index.
    """
    groups: list[list[ResearchDocument]] = []
    if output_dir is not None:
        groups.append(ResearchStore(Path(output_dir)).list_documents())

    committed = committed_dir
    if committed is None and library_root is not None and not is_ftse_market(market_id):
        committed = committed_research_dir(market_id, library_root=library_root, data_dir=data_dir)
    if committed is not None:
        groups.append(list_documents_from_research_root(committed))
        if library_root is not None and not is_ftse_market(market_id):
            for sibling in sibling_research_dirs(library_root, exclude=committed):
                groups.append(list_documents_from_research_root(sibling))

    if bundle is not None:
        groups.append(documents_from_research_index(list(bundle.get("research") or [])))

    return merge_documents_by_ticker(*groups)


def filing_body_count(research_ticker_dir: Path) -> int:
    idx = Path(research_ticker_dir) / "sources" / "filings" / "filings_index.json"
    if not idx.exists():
        return 0
    try:
        payload = read_json(idx)
    except (OSError, ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    summary = payload.get("summary") or {}
    return int(summary.get("with_body") or 0)


def rememo_reason(
    *,
    grade: str | None,
    memo_bodies: int,
    disk_bodies: int,
    body_lag_threshold: int = DEFAULT_REMEMO_BODY_LAG_THRESHOLD,
    ingest_improved: bool = False,
    has_verdict: bool = True,
) -> str | None:
    """Why a memo should be rewritten, or ``None`` if it is still fresh."""
    if ingest_improved:
        return "ingest_improved_bodies"
    if not has_verdict:
        return "missing_verdict"
    lag = int(disk_bodies) - int(memo_bodies)
    grade_key = str(grade or "").strip().lower()
    threshold = max(1, int(body_lag_threshold))
    if grade_key in {"adequate", "thin", "poor", ""} and lag >= threshold:
        return f"stale_{grade_key or 'missing'}_grade_body_lag_{lag}"
    if lag >= max(threshold * 2, 25):
        return f"strong_grade_large_body_lag_{lag}"
    return None


def _memo_quality_fields(meta: dict[str, Any]) -> tuple[str | None, int, bool]:
    mq = meta.get("memo_quality") or {}
    if not isinstance(mq, dict):
        mq = {}
    grade = str(mq.get("grade") or "").strip().lower() or None
    bodies = int(
        mq.get("filings_with_body")
        or (meta.get("source_counts") or {}).get("filings_with_body")
        or 0
    )
    has_verdict = bool(str(meta.get("research_verdict") or "").strip())
    return grade, bodies, has_verdict


def library_rememo_eligible_tickers(
    library_root: Path,
    *,
    tickers: Iterable[str],
    market_id: str,
    body_lag_threshold: int = DEFAULT_REMEMO_BODY_LAG_THRESHOLD,
) -> dict[str, str]:
    """
    Buy-tier tickers whose existing library memo is stale vs current filings.

    Disk body count is the max of the *canonical* market filing index (where
    ingest writes) and the memo's home-market sources. A thin first-pass memo
    is rememo'd only after bodies actually increase — not every Sunday.
    """
    from value_investor.library_dedupe import canonical_library_ticker, research_home_market

    root = Path(library_root)
    canonical = committed_research_dir(market_id, library_root=root)
    eligible: dict[str, str] = {}
    for raw in tickers:
        ticker = canonical_library_ticker(str(raw or ""))
        if not ticker:
            continue
        home_id = research_home_market(root, ticker)
        home_dir = (
            committed_research_dir(home_id, library_root=root) / ticker
            if home_id
            else None
        )
        if home_dir is None or not (home_dir / "research.json").exists():
            # Case-preserving home dir from research_home_market walk.
            if home_id:
                research = committed_research_dir(home_id, library_root=root)
                matches = [
                    p
                    for p in research.iterdir()
                    if p.is_dir() and canonical_library_ticker(p.name) == ticker
                ]
                home_dir = matches[0] if matches else None
        if home_dir is None or not (home_dir / "research.json").exists():
            continue
        try:
            meta = read_json(home_dir / "research.json")
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(meta, dict):
            continue
        grade, memo_bodies, has_verdict = _memo_quality_fields(meta)
        disk_bodies = max(
            filing_body_count(canonical / ticker),
            filing_body_count(home_dir),
        )
        reason = rememo_reason(
            grade=grade,
            memo_bodies=memo_bodies,
            disk_bodies=disk_bodies,
            body_lag_threshold=body_lag_threshold,
            has_verdict=has_verdict,
        )
        if reason:
            eligible[ticker] = reason
    return eligible
