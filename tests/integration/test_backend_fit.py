"""Orchestrator-owned backend-fit test (contract v1.1 <-> Urvi's backend ingest).

Verifies that a real-mode ScanResponse carries everything the backend's
``POST /api/v1/scans`` needs, and that the documented client mapping builds a
payload with the exact field names/types that branch expects:

    {event_id, user_id, drug_name, strength{value,unit}|null, quantity, timestamp}

Run:  .venv-full/bin/python -m pytest tests/integration/test_backend_fit.py -q
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts/v1/scan_response.schema.json").read_text())
SAMPLE = ROOT / "samples" / "label_metformin.png"


def _app():
    from services.api.main import app

    return app


def _scan(mode: str = "real"):
    async def scenario():
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            image = SAMPLE.read_bytes()
            resp = await client.post(
                "/v1/scan",
                files={"image": ("label.png", image, "image/png")},
                data={"mode": mode, "client": "backend"},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            validate(body, SCHEMA)
            return body

    return asyncio.run(scenario())


def _backend_payload(scan: dict) -> dict:
    """The documented mapping from ScanResponse to Urvi's POST /api/v1/scans body."""
    med = scan["medication"]
    strength = med.get("strength") or {}
    dose = (scan["instructions"] or {}).get("dose") or {}
    quantity = dose.get("quantity")
    return {
        "event_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "drug_name": med["name"]["value"],
        "strength": {"value": strength.get("value"), "unit": strength.get("unit")} if strength.get("value") is not None else None,
        # Backend requires quantity > 0; fall back to the label's stated per-dose amount,
        # else 1 (client default) — never invented from the package size.
        "quantity": quantity if quantity is not None else 1,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def test_scan_response_feeds_backend_scan_payload() -> None:
    body = _scan("real")
    payload = _backend_payload(body)

    # Required by the backend ScanSchema (marshmallow): presence + types.
    assert isinstance(payload["event_id"], str) and uuid.UUID(payload["event_id"])
    assert isinstance(payload["user_id"], str) and uuid.UUID(payload["user_id"])
    assert payload["drug_name"] == "Metformin"
    assert payload["strength"] == {"value": 500.0, "unit": "mg"}
    assert payload["quantity"] == 1
    assert isinstance(payload["quantity"], (int, float)) and payload["quantity"] > 0
    assert payload["timestamp"].endswith("Z")

    # v1.1 dose object must be present and structured for the sharp sample.
    dose = body["instructions"]["dose"]
    assert dose is not None, "v1.1 instructions.dose missing from a real scan"
    assert dose["quantity"] == 1 and str(dose["unit"]).lower() == "tablet"
    assert dose["source"] == "ocr" and dose["confidence"] >= 0.5


def test_mock_scan_response_also_carries_v11_dose() -> None:
    body = _scan("mock")
    payload = _backend_payload(body)
    assert payload["quantity"] > 0
    # Mock mode must be schema/contract complete too (iOS develops against it).
    validate(body, SCHEMA)
