#!/usr/bin/env python3
"""MedCheck local test console — tiny proxy server (stdlib only).

Serves the test UI and forwards uploads to the MedCheck API so the browser
does not need CORS.

Every scan is saved locally for debugging (image + response JSON) under
~/.medcheck/scans/ (override with MEDCHECK_SAVE_DIR; set MEDCHECK_SAVE_SCANS=0
to disable). Nothing leaves the machine.

Usage:  python tools/local_scan/server.py            # UI on http://127.0.0.1:8400
Env:    MEDCHECK_API (default http://127.0.0.1:8300)
        MEDCHECK_TOOL_PORT (default 8400)
        MEDCHECK_SAVE_DIR (default ~/.medcheck/scans)
        MEDCHECK_SAVE_SCANS (default 1)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))  # so `services.vision` imports work from any cwd

API = os.environ.get("MEDCHECK_API", "http://127.0.0.1:8300").rstrip("/")
PORT = int(os.environ.get("MEDCHECK_TOOL_PORT", "8400"))
MAX_FORWARD_BYTES = 16 * 1024 * 1024  # hard stop above the API's 12 MiB image limit
SAVE_SCANS = os.environ.get("MEDCHECK_SAVE_SCANS", "1") not in ("0", "false", "no")
SAVE_DIR = Path(os.environ.get("MEDCHECK_SAVE_DIR", str(Path.home() / ".medcheck" / "scans")))
KEEP_SCANS = 40

_ANALYZE = None


def _analyze_frame(image_bytes: bytes):
    """Lazy import + cache of the vision entrypoint (used by /api/live)."""
    global _ANALYZE
    if _ANALYZE is None:
        from services.vision.pipeline import analyze_frame  # noqa: PLC0415

        _ANALYZE = analyze_frame
    return _ANALYZE(image_bytes)


def _save_bundle(images: list[tuple[bytes, str]], meta: dict, response: bytes, status: int) -> None:
    """Save one scan bundle: zero or more frames + the response JSON.

    `images` is a list of (bytes, content_type); multi-frame scans save `_f1`, `_f2`, …
    """
    if not SAVE_SCANS:
        return
    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:6]}"
        for index, (data, ctype) in enumerate(images):
            ext = "png" if "png" in (ctype or "") else "jpg"
            suffix = "" if len(images) == 1 else f"_f{index + 1}"
            (SAVE_DIR / f"{stamp}{suffix}.{ext}").write_bytes(data)
        try:
            payload = json.loads(response)
        except Exception:  # noqa: BLE001
            payload = {"raw": response.decode("utf-8", "replace")[:4000]}
        (SAVE_DIR / f"{stamp}.json").write_text(json.dumps({
            "saved_at": stamp, "http_status": status, "frames": len(images), "meta": meta,
            "status": payload.get("status"), "response": payload,
        }, indent=2))
        # rotate (one bundle = json + its frames)
        bundles = sorted(SAVE_DIR.glob("*.json"))
        for old in bundles[:-KEEP_SCANS]:
            stem = old.with_suffix("")
            for leftover in SAVE_DIR.glob(stem.name + "*"):
                leftover.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - debug saving must never break a scan
        pass


def _extract_multipart_parts(body: bytes, content_type: str, field: str) -> list[tuple[bytes, str]]:
    """Every `field` part in a multipart body as (bytes, content_type)."""
    m = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type or "")
    if not m:
        return []
    boundary = (m.group(1) or m.group(2)).strip().encode()
    marker = ('name="%s"' % field).encode()
    parts: list[tuple[bytes, str]] = []
    for part in body.split(b"--" + boundary):
        head, _, data = part.partition(b"\r\n\r\n")
        if marker not in head:
            continue
        cm = re.search(rb"Content-Type:\s*([\w/+.-]+)", head)
        parts.append((data.rstrip(b"\r\n"), cm.group(1).decode() if cm else "image/png"))
    return parts


def _extract_multipart_image(body: bytes, content_type: str) -> tuple[bytes | None, str]:
    """Best-effort pull of the `image` part out of a multipart body (for saving)."""
    m = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type or "")
    if not m:
        return None, ""
    boundary = (m.group(1) or m.group(2)).strip().encode()
    for part in body.split(b"--" + boundary):
        head, _, data = part.partition(b"\r\n\r\n")
        if b'name="image"' not in head:
            continue
        ctype = ""
        cm = re.search(rb"Content-Type:\s*([\w/+.-]+)", head)
        if cm:
            ctype = cm.group(1).decode()
        return data.rstrip(b"\r\n"), ctype
    return None, ""


class Handler(BaseHTTPRequestHandler):
    server_version = "MedCheckLocal/0.2"

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

    def _forward(self, path: str, body: bytes | None, ctype: str | None, method: str = "POST") -> tuple[int, bytes, str]:
        headers = {"Accept": "application/json"}
        if ctype:
            headers["Content-Type"] = ctype
        req = urllib.request.Request(API + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get("Content-Type", "application/json")
        except Exception as exc:  # noqa: BLE001
            err = json.dumps({"error": {"code": "GATEWAY", "message": f"API unreachable: {exc}"}}).encode()
            return 502, err, "application/json"

    # ---------- routes ----------
    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._respond(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/health":
            code, body, ctype = self._forward("/health", None, None, "GET")
            self._respond(code, body, ctype)
        elif path == "/api/ready":
            code, body, ctype = self._forward("/ready", None, None, "GET")
            self._respond(code, body, ctype)
        elif path == "/api/scans":
            items = []
            if SAVE_DIR.exists():
                for j in sorted(SAVE_DIR.glob("*.json"))[-KEEP_SCANS:]:
                    try:
                        meta = json.loads(j.read_text())
                    except Exception:  # noqa: BLE001
                        continue
                    stem = j.with_suffix("")
                    img = next((p.name for p in (stem.with_suffix(".png"), stem.with_suffix(".jpg")) if p.exists()), None)
                    items.append({"bundle": j.name, "image": img, "status": meta.get("status"), "saved_at": meta.get("saved_at")})
            self._json(200, {"dir": str(SAVE_DIR), "count": len(items), "items": items})
        elif path.startswith("/api/scans/"):
            name = Path(urllib.parse.unquote(path.split("/api/scans/", 1)[1])).name
            target = SAVE_DIR / name
            if target.is_file() and target.parent == SAVE_DIR:
                ctype = "image/png" if target.suffix == ".png" else ("application/json" if target.suffix == ".json" else "image/jpeg")
                self._respond(200, target.read_bytes(), ctype)
            else:
                self._json(404, {"error": {"code": "NOT_FOUND", "message": name}})
        else:
            self._json(404, {"error": {"code": "NOT_FOUND", "message": path}})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/live":
            self._handle_live()
            return
        if parsed.path == "/api/multi":
            self._handle_multi()
            return
        if parsed.path != "/api/scan":
            self._json(404, {"error": {"code": "NOT_FOUND", "message": parsed.path}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._json(400, {"error": {"code": "EMPTY_BODY", "message": "no body"}})
            return
        if length > MAX_FORWARD_BYTES:
            self._json(413, {"error": {"code": "PAYLOAD_TOO_LARGE", "message": "over 16 MiB"}})
            return

        body = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        params = urllib.parse.parse_qs(parsed.query)
        meta = {
            "mode": (params.get("mode") or [""])[0],
            "client": (params.get("client") or [""])[0],
            "hints": (params.get("hints") or [""])[0],
        }
        image: bytes | None = None
        image_type = ctype

        if ctype.startswith("image/"):
            # Raw image + query params: save once, build the multipart for the API.
            image, image_type = body, ctype
            boundary = "----medcheck" + uuid.uuid4().hex
            parts = [
                f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="scan{".png" if "png" in ctype else ".jpg"}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n".encode(),
                body,
                f"\r\n--{boundary}".encode(),
            ]
            for key in ("mode", "client", "hints"):
                if meta.get(key):
                    parts.append(f'\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{meta[key]}\r\n--{boundary}'.encode())
            parts.append(b"--\r\n")
            forward_body = b"".join(parts)
            forward_type = f"multipart/form-data; boundary={boundary}"
        elif ctype.startswith("multipart/form-data"):
            image, image_type = _extract_multipart_image(body, ctype)
            forward_body, forward_type = body, ctype
        else:
            self._json(415, {"error": {"code": "UNSUPPORTED_MEDIA_TYPE", "message": ctype}})
            return

        code, resp, resp_type = self._forward("/v1/scan", forward_body, forward_type)
        _save_bundle([(image, image_type)] if image else [], meta, resp, code)
        self._respond(code, resp, resp_type)

    def _handle_live(self) -> None:
        """Fast vision-only pass for live guidance: quality + bottle + label (~100 ms)."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 4 * 1024 * 1024:
            self._json(400, {"error": {"code": "BAD_FRAME", "message": "empty or over 4 MiB"}})
            return
        body = self.rfile.read(length)
        try:
            started = time.perf_counter()
            result = _analyze_frame(body)
            elapsed = (time.perf_counter() - started) * 1000.0
        except Exception as exc:  # noqa: BLE001
            self._json(200, {"error": {"code": "VISION_ERROR", "message": str(exc)}})
            return
        payload = result.model_dump(mode="json")
        payload["timing_ms"] = round(elapsed, 2)
        self._json(200, payload)

    def _handle_multi(self) -> None:
        """Proxy a multi-frame capture (repeated `images`) to /v1/scan/multi."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_FORWARD_BYTES:
            self._json(413, {"error": {"code": "BAD_BODY", "message": "empty or over 16 MiB"}})
            return
        body = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            self._json(415, {"error": {"code": "UNSUPPORTED_MEDIA_TYPE", "message": ctype}})
            return
        code, resp, resp_type = self._forward("/v1/scan/multi", body, ctype)
        frames = _extract_multipart_parts(body, ctype, "images")
        _save_bundle(frames, {"endpoint": "multi", "frames": len(frames)}, resp, code)
        self._respond(code, resp, resp_type)

    def log_message(self, fmt: str, *args) -> None:  # keep the console quiet
        if os.environ.get("MEDCHECK_TOOL_VERBOSE"):
            super().log_message(fmt, *args)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"MedCheck local test console → http://127.0.0.1:{PORT}  (API: {API})")
    if SAVE_SCANS:
        print(f"Scans saved for debugging → {SAVE_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
