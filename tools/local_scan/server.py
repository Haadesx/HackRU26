#!/usr/bin/env python3
"""MedCheck local test console — tiny proxy server (stdlib only).

Serves the test UI and forwards uploads to the MedCheck API so the browser
does not need CORS. Images are forwarded in memory and never stored.

Usage:  python tools/local_scan/server.py            # UI on http://127.0.0.1:8400
Env:    MEDCHECK_API (default http://127.0.0.1:8300)
        MEDCHECK_TOOL_PORT (default 8400)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = os.environ.get("MEDCHECK_API", "http://127.0.0.1:8300").rstrip("/")
PORT = int(os.environ.get("MEDCHECK_TOOL_PORT", "8400"))
MAX_FORWARD_BYTES = 16 * 1024 * 1024  # hard stop above the API's 12 MiB image limit


class Handler(BaseHTTPRequestHandler):
    server_version = "MedCheckLocal/0.1"

    # ---------- helpers ----------
    def _respond(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._respond(code, json.dumps(payload).encode(), "application/json")

    def _proxy(self, method: str, path: str, body: bytes | None, ctype: str | None) -> None:
        headers = {"Accept": "application/json"}
        if ctype:
            headers["Content-Type"] = ctype
        req = urllib.request.Request(API + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                self._respond(resp.status, resp.read(), resp.headers.get("Content-Type", "application/json"))
        except urllib.error.HTTPError as exc:
            self._respond(exc.code, exc.read(), exc.headers.get("Content-Type", "application/json"))
        except Exception as exc:  # noqa: BLE001
            self._json(502, {"error": {"code": "GATEWAY", "message": f"API unreachable: {exc}"}})

    # ---------- routes ----------
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._respond(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/health":
            self._proxy("GET", "/health", None, None)
        elif self.path == "/api/ready":
            self._proxy("GET", "/ready", None, None)
        else:
            self._json(404, {"error": {"code": "NOT_FOUND", "message": self.path}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/scan":
            self._json(404, {"error": {"code": "NOT_FOUND", "message": self.path}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._json(400, {"error": {"code": "EMPTY_BODY", "message": "no multipart body"}})
            return
        if length > MAX_FORWARD_BYTES:
            self._json(413, {"error": {"code": "PAYLOAD_TOO_LARGE", "message": "over 16 MiB"}})
            return
        body = self.rfile.read(length)
        self._proxy("POST", "/v1/scan", body, self.headers.get("Content-Type"))

    def log_message(self, fmt: str, *args) -> None:  # keep the console quiet
        if os.environ.get("MEDCHECK_TOOL_VERBOSE"):
            super().log_message(fmt, *args)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"MedCheck local test console → http://127.0.0.1:{PORT}  (API: {API})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
