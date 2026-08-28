"""Local dashboard server with progress-report generate API.

GitHub Pages is static and cannot run ``ftse-progress-report``. This CLI serves
``docs/`` and exposes ``POST /api/progress-report`` so the Overview Generate
button can refresh artifacts while developing locally.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from value_investor.progress_report import (
    DEFAULT_MARKDOWN_PATH,
    DEFAULT_REPORT_PATH,
    write_progress_report,
)

DEFAULT_DOCS_ROOT = Path("docs")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _json_bytes(payload: dict[str, Any], *, status: int = 200) -> tuple[int, bytes, str]:
    body = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    return status, body, "application/json; charset=utf-8"


def make_handler(docs_root: Path, repo_root: Path) -> type[BaseHTTPRequestHandler]:
    docs_root = docs_root.resolve()
    repo_root = repo_root.resolve()

    class DashboardHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            sys.stderr.write(f"{self.address_string()} - {format % args}\n")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path or "/"
            if path == "/api/progress-report":
                report_path = (repo_root / DEFAULT_REPORT_PATH).resolve()
                if not report_path.exists():
                    status, body, ctype = _json_bytes(
                        {"ok": False, "error": "progress_report.json missing — generate first"},
                        status=404,
                    )
                    self._send(status, body, ctype)
                    return
                payload = json.loads(report_path.read_text(encoding="utf-8"))
                status, body, ctype = _json_bytes({"ok": True, "report": payload})
                self._send(status, body, ctype)
                return

            rel = "index.html" if path in {"/", ""} else path.lstrip("/")
            candidate = (docs_root / rel).resolve()
            if not str(candidate).startswith(str(docs_root)) or not candidate.is_file():
                self._send(404, b"Not found\n", "text/plain; charset=utf-8")
                return
            data = candidate.read_bytes()
            ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in {
                "application/javascript",
                "application/json",
            }:
                ctype = f"{ctype}; charset=utf-8"
            self._send(200, data, ctype)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/progress-report":
                self._send(404, b"Not found\n", "text/plain; charset=utf-8")
                return
            try:
                payload = write_progress_report(
                    json_path=repo_root / DEFAULT_REPORT_PATH,
                    markdown_path=repo_root / DEFAULT_MARKDOWN_PATH,
                )
            except Exception as exc:  # noqa: BLE001 — surface to UI
                status, body, ctype = _json_bytes(
                    {
                        "ok": False,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                    status=500,
                )
                self._send(status, body, ctype)
                return
            status, body, ctype = _json_bytes(
                {
                    "ok": True,
                    "report": payload,
                    "paths": {
                        "json": str(DEFAULT_REPORT_PATH),
                        "markdown": str(DEFAULT_MARKDOWN_PATH),
                    },
                }
            )
            self._send(status, body, ctype)

    return DashboardHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve the docs/ dashboard locally with progress-report generate API",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--docs-root", type=Path, default=DEFAULT_DOCS_ROOT)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repo root used for writing progress_report artifacts",
    )
    args = parser.parse_args(argv)

    docs_root = args.docs_root
    if not docs_root.is_dir():
        print(f"docs root not found: {docs_root}", file=sys.stderr)
        return 1

    handler = make_handler(docs_root, args.repo_root)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving dashboard at {url}")
    print("POST /api/progress-report  →  ftse-progress-report build --write")
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
