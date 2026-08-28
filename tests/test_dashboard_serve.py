"""Tests for local dashboard serve + progress-report API."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from value_investor.dashboard_serve_cli import make_handler
from value_investor.storage import write_json


def _seed_docs(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    data = docs / "data"
    data.mkdir(parents=True)
    (docs / "index.html").write_text("<html><body>ok</body></html>\n", encoding="utf-8")
    write_json(
        data / "progress_report.json",
        {"schema_version": 1, "overall": "ok", "generated_at": "2026-08-28T00:00:00+00:00"},
    )
    (data / "progress_report.md").write_text("# FTSE progress report\n", encoding="utf-8")
    write_json(tmp_path / "docs/deferred-ideas.json", {"version": 1, "ideas": [], "fragments": []})
    write_json(
        data / "latest.json", {"run_at": "2026-08-27T18:00:00+00:00", "meta": {"company_count": 10}}
    )
    write_json(data / "ops_status.json", {"run_at": "2026-08-27T12:00:00+00:00", "overall": "ok"})
    write_json(data / "engineering_tasks.json", {"tasks": []})
    write_json(data / "automation.json", {"settings": {"library": {"graduated_count": 0}}})
    return docs


def test_dashboard_serve_get_and_generate(tmp_path: Path, monkeypatch):
    docs = _seed_docs(tmp_path)
    monkeypatch.chdir(tmp_path)
    handler = make_handler(docs, tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 200
        assert b"ok" in body

        conn.request("GET", "/api/progress-report")
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert payload["ok"] is True
        assert payload["report"]["overall"] == "ok"

        conn.request(
            "POST", "/api/progress-report", body=b"{}", headers={"Content-Type": "application/json"}
        )
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert payload["ok"] is True
        assert payload["report"]["schema_version"] == 1
        assert (tmp_path / "docs/data/progress_report.md").exists()
    finally:
        server.shutdown()
        server.server_close()
