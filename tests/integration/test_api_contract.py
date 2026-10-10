"""Orchestrator-owned integration tests: full API contract against the real app.

Runs after the API branch is merged into main. Requires the api extra:
    .venv/bin/pip install -e ".[api,dev]"
    .venv/bin/pytest tests/integration -q
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts/v1/scan_response.schema.json").read_text())
SAMPLES = ROOT / "samples"


def _app():
    from services.api.main import app  # imported lazily so collection works before merge

    return app


def run(coro):
    return asyncio.run(coro)


def test_health_ready_scan_contract() -> None:
    async def scenario():
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            assert health.status_code == 200, health.text
            h = health.json()
            assert h["status"] == "ok" and h["service"] == "medcheck-inference"

            ready = await client.get("/ready")
            assert ready.status_code in (200, 503), ready.text

            image = (SAMPLES / "label_metformin.png").read_bytes()
            resp = await client.post(
                "/v1/scan",
                files={"image": ("label.png", image, "image/png")},
                data={"mode": "mock", "client": "test"},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            validate(body, SCHEMA)
            assert body["mode"] == "mock"
            assert body["safety"]["ingestion_not_inferred"] is True
            assert body["safety"]["backend_authoritative"] is True
            assert body["status"] in {"ok", "needs_rescan", "uncertain", "no_medication_found"}

    run(scenario())


def test_scan_rejects_non_image_and_oversize() -> None:
    async def scenario():
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            bad = await client.post(
                "/v1/scan",
                files={"image": ("note.txt", b"not an image", "text/plain")},
                data={"mode": "mock"},
            )
            assert 400 <= bad.status_code < 500

            big = b"\x89PNG\r\n\x1a\n" + b"0" * (13 * 1024 * 1024)
            huge = await client.post(
                "/v1/scan",
                files={"image": ("big.png", big, "image/png")},
                data={"mode": "mock"},
            )
            assert huge.status_code in (400, 413)

    run(scenario())
