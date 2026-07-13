"""Filesystem persistence for per-ticker research."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.research.document import ResearchDocument, render_research_markdown
from value_investor.research.timeline import archive_revision
from value_investor.storage import read_json, write_json


class ResearchStore:
    def __init__(self, output_dir: Path):
        self.root = output_dir / "research"
        self.output_dir = output_dir

    def ticker_dir(self, ticker: str) -> Path:
        return self.root / ticker

    def sources_dir(self, ticker: str) -> Path:
        return self.ticker_dir(ticker) / "sources"

    def metadata_path(self, ticker: str) -> Path:
        return self.ticker_dir(ticker) / "research.json"

    def markdown_path(self, ticker: str) -> Path:
        return self.ticker_dir(ticker) / "research.md"

    def timeline_path(self, ticker: str) -> Path:
        return self.ticker_dir(ticker) / "timeline.json"

    def agent_id_path(self, ticker: str) -> Path:
        return self.ticker_dir(ticker) / "agent_id.txt"

    def exists(self, ticker: str) -> bool:
        return self.metadata_path(ticker).exists()

    def load(self, ticker: str) -> ResearchDocument | None:
        path = self.metadata_path(ticker)
        if not path.exists():
            return None
        data = read_json(path)
        doc = ResearchDocument.from_dict(data)
        doc.research_path = str(self.markdown_path(ticker))
        return doc

    def save(
        self,
        doc: ResearchDocument,
        *,
        run_at: datetime | None = None,
        sources_as_of: dict[str, Any] | None = None,
        delta: dict[str, Any] | None = None,
    ) -> str:
        ticker_dir = self.ticker_dir(doc.ticker)
        ticker_dir.mkdir(parents=True, exist_ok=True)
        doc.research_path = str(self.markdown_path(doc.ticker))

        if not doc.updated_at:
            doc.updated_at = datetime.now(UTC).isoformat()

        write_json(self.metadata_path(doc.ticker), doc.to_dict(), compact=True)
        self.markdown_path(doc.ticker).write_text(render_research_markdown(doc), encoding="utf-8")
        if doc.agent_id:
            self.agent_id_path(doc.ticker).write_text(doc.agent_id, encoding="utf-8")

        return archive_revision(
            ticker_dir,
            doc=doc,
            run_at=run_at,
            sources_as_of=sources_as_of,
            delta=delta,
        )

    def load_agent_id(self, ticker: str) -> str | None:
        path = self.agent_id_path(ticker)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8").strip() or None

    def list_documents(self) -> list[ResearchDocument]:
        if not self.root.exists():
            return []
        docs: list[ResearchDocument] = []
        for path in sorted(self.root.glob("*/research.json")):
            ticker = path.parent.name
            doc = self.load(ticker)
            if doc is not None:
                docs.append(doc)
        return docs
