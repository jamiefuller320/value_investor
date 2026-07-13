"""Point-in-time research revision archive and lookup."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.research.document import ResearchDocument


def _parse_as_of(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def revision_id_from_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


@dataclass
class ResearchRevisionMeta:
    revision_id: str
    as_of: str
    run_at: str | None
    mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "as_of": self.as_of,
            "run_at": self.run_at,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchRevisionMeta:
        return cls(
            revision_id=str(data["revision_id"]),
            as_of=str(data["as_of"]),
            run_at=data.get("run_at"),
            mode=str(data.get("mode") or "initial"),
        )


@dataclass
class ResearchRevision:
    revision_id: str
    as_of: str
    run_at: str | None
    mode: str
    document: dict[str, Any]
    sources_as_of: dict[str, Any] = field(default_factory=dict)
    delta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "revision_id": self.revision_id,
            "as_of": self.as_of,
            "run_at": self.run_at,
            "mode": self.mode,
            "document": self.document,
            "sources_as_of": self.sources_as_of,
        }
        if self.delta is not None:
            payload["delta"] = self.delta
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchRevision:
        return cls(
            revision_id=str(data["revision_id"]),
            as_of=str(data["as_of"]),
            run_at=data.get("run_at"),
            mode=str(data.get("mode") or "initial"),
            document=dict(data["document"]),
            sources_as_of=dict(data.get("sources_as_of") or {}),
            delta=data.get("delta"),
        )

    def to_document(self) -> ResearchDocument:
        return ResearchDocument.from_dict(self.document)


def build_sources_as_of(
    *,
    sources_dir: Path,
    source_meta: dict[str, Any],
    as_of: datetime,
    revision_id: str,
) -> dict[str, Any]:
    """Summarise which inputs were visible at a revision's knowledge cutoff."""
    as_of_dt = _parse_as_of(as_of)
    article_ids: list[str] = []
    news_through: str | None = None

    from value_investor.storage import read_json, resolve_json_path, write_json

    manifest_path = resolve_json_path(sources_dir / "news_manifest.json")
    if manifest_path is not None:
        manifest = read_json(manifest_path)
        for article in manifest.get("articles") or []:
            published = article.get("published_at")
            if not published:
                continue
            try:
                published_dt = _parse_as_of(str(published))
            except ValueError:
                continue
            if published_dt <= as_of_dt:
                article_ids.append(str(article.get("id") or ""))
                if news_through is None or published > news_through:
                    news_through = str(published)

    financials_through: str | None = None
    financials_path = resolve_json_path(sources_dir / "financials_annual.json")
    if financials_path is not None:
        financials = read_json(financials_path)
        years = list((financials.get("income_statement") or {}).keys())
        if years:
            financials_through = max(years)

    snapshot_path = f"sources/snapshots/{revision_id}.json"
    screening_src = resolve_json_path(sources_dir / "screening_snapshot.json")
    snapshots_dir = sources_dir / "snapshots"
    if screening_src is not None:
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        dest = snapshots_dir / f"{revision_id}.json"
        if screening_src.name.endswith(".gz"):
            write_json(dest, read_json(screening_src), compact=True, compress=False)
        else:
            shutil.copy2(screening_src, dest)

    news_batch = source_meta.get("news_batch_path")
    news_batch_rel = None
    if news_batch:
        batch_path = Path(news_batch)
        try:
            news_batch_rel = str(batch_path.relative_to(sources_dir.parent))
        except ValueError:
            news_batch_rel = batch_path.name

    return {
        "news_through": news_through,
        "financials_through": financials_through,
        "news_article_ids": [item for item in article_ids if item][:100],
        "screening_snapshot_path": snapshot_path if screening_src is not None else None,
        "news_batch_path": news_batch_rel,
    }


def archive_revision(
    ticker_dir: Path,
    *,
    doc: ResearchDocument,
    run_at: datetime | None,
    sources_as_of: dict[str, Any] | None,
    delta: dict[str, Any] | None = None,
) -> str:
    """Append an immutable revision snapshot and update timeline.json."""
    as_of_dt = _parse_as_of(doc.updated_at or datetime.now(UTC))
    revision_id = revision_id_from_datetime(as_of_dt)
    as_of = as_of_dt.isoformat()
    run_at_str = _parse_as_of(run_at).isoformat() if run_at is not None else None

    revision = ResearchRevision(
        revision_id=revision_id,
        as_of=as_of,
        run_at=run_at_str,
        mode=doc.mode,
        document=doc.to_dict(),
        sources_as_of=sources_as_of or {},
        delta=delta,
    )

    revisions_dir = ticker_dir / "revisions"
    revisions_dir.mkdir(parents=True, exist_ok=True)
    from value_investor.storage import read_json, write_json

    write_json(
        revisions_dir / f"{revision_id}.json",
        revision.to_dict(),
        compact=True,
        compress=True,
    )

    timeline_path = ticker_dir / "timeline.json"
    timeline: dict[str, Any]
    if timeline_path.exists():
        timeline = read_json(timeline_path)
    else:
        timeline = {"ticker": doc.ticker, "revisions": []}

    entries = [ResearchRevisionMeta.from_dict(item) for item in timeline.get("revisions") or []]
    if not any(entry.revision_id == revision_id for entry in entries):
        entries.append(
            ResearchRevisionMeta(
                revision_id=revision_id,
                as_of=as_of,
                run_at=run_at_str,
                mode=doc.mode,
            )
        )
    entries.sort(key=lambda item: item.as_of)
    timeline["revisions"] = [entry.to_dict() for entry in entries]
    write_json(timeline_path, timeline, compact=True)
    return revision_id


def load_revision(ticker_dir: Path, revision_id: str) -> ResearchRevision | None:
    from value_investor.storage import read_json, resolve_json_path

    path = resolve_json_path(ticker_dir / "revisions" / f"{revision_id}.json")
    if path is None:
        return None
    return ResearchRevision.from_dict(read_json(path))


def list_revision_metas(ticker_dir: Path) -> list[ResearchRevisionMeta]:
    from value_investor.storage import read_json

    timeline_path = ticker_dir / "timeline.json"
    if not timeline_path.exists():
        return []
    timeline = read_json(timeline_path)
    return [ResearchRevisionMeta.from_dict(item) for item in timeline.get("revisions") or []]


def get_research_as_of(
    output_dir: Path,
    ticker: str,
    as_of: datetime | str,
) -> ResearchDocument | None:
    """
    Return the research memo as it stood at or before ``as_of``.

    Uses the append-only revision archive. Falls back to latest research.json when
    no timeline exists yet (legacy memos).
    """
    ticker_dir = output_dir / "research" / ticker
    query = _parse_as_of(as_of)
    metas = list_revision_metas(ticker_dir)

    if metas:
        eligible = [meta for meta in metas if _parse_as_of(meta.as_of) <= query]
        if not eligible:
            return None
        chosen = max(eligible, key=lambda meta: _parse_as_of(meta.as_of))
        revision = load_revision(ticker_dir, chosen.revision_id)
        if revision is not None:
            return revision.to_document()

    legacy_path = ticker_dir / "research.json"
    if not legacy_path.exists():
        return None
    from value_investor.storage import read_json

    doc = ResearchDocument.from_dict(read_json(legacy_path))
    if doc.updated_at and _parse_as_of(doc.updated_at) > query:
        return None
    return doc


def build_weekly_delta(
    *,
    prior: ResearchDocument,
    updated: ResearchDocument,
    weekly_summary: str,
) -> dict[str, Any]:
    delta: dict[str, Any] = {
        "weekly_update": weekly_summary,
        "verdict_changed": prior.research_verdict != updated.research_verdict,
    }
    if prior.research_verdict != updated.research_verdict:
        delta["prior_verdict"] = prior.research_verdict
        delta["new_verdict"] = updated.research_verdict
    return delta
