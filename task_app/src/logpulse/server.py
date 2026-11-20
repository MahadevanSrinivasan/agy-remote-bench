"""Lightweight localhost HTTP metrics server for logpulse."""

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from logpulse.parser import summarize_file


def make_server(
    jsonl_path: Path,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    """Create a ThreadingHTTPServer serving ``/healthz`` and ``/metrics``.

    ``GET /healthz`` must return HTTP 200 with ``{"status": "ok"}``.
    ``GET /metrics`` must return HTTP 200 with a freshly computed summary from
    ``summarize_file(jsonl_path)`` on every request. Other paths return HTTP 404.
    """
    cached_payload = summarize_file(jsonl_path)

    class MetricsHandler(BaseHTTPRequestHandler):
        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/metrics":
                self._send_json(HTTPStatus.OK, cached_payload)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def log_message(self, fmt: str, *args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), MetricsHandler)
