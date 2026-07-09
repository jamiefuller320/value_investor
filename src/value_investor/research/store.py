"""Filesystem persistence for per-ticker research."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.research.document import ResearchDocument, render_research_markdown


class ResearchStore:
    def __init__(self, output_dir: Path):
        self.root = output_dir / "research"

    def ticker_dir(self, ticker: str) -> Path:
        return self.root / ticker

    def sources_dir(self, ticker: str) -> Path:
        return self.ticker_dir(ticker) / "sources"

    def metadata_path(self, ticker: str) -> Path:
        return self.ticker_dir(ticker) / "research.json"

    def markdown_path(self, ticker: str) -> Path:
        return self.ticker_dir(ticker) / "research.md"

    def agent_id_path(self, ticker: str) -> Path:
        return self.ticker_dir(ticker) / "agent_id.txt"

    def exists(self, ticker: str) -> bool:
        return self.metadata_path(ticker).exists()

    def load(self, ticker: str) -> ResearchDocument | None:
        path = self.metadata_path(ticker)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        doc = ResearchDocument.from_dict(data)
        doc.research_path = str(self.markdown_path(ticker))
        return doc

    def save(self, doc: ResearchDocument) -> None:
        ticker_dir = self.ticker_dir(doc.ticker)
        ticker_dir.mkdir(parents=True, exist_ok=True)
        doc.research_path = str(self.markdown_path(doc.ticker))
        self.metadata_path(doc.ticker).write_text(
            json.dumps(doc.to_dict(), indent=2),
            encoding="utf-8",
        )
        self.markdown_path(doc.ticker).write_text(render_research_markdown(doc), encoding="utf-8")
        if doc.agent_id:
            self.agent_id_path(doc.ticker).write_text(doc.agent_id, encoding="utf-8")

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
