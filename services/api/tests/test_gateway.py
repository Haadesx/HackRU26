"""Endpoint tests for the MedCheck API gateway (mock mode, ASGI transport)."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from services.api.fixtures import FIXTURES, fixture_by_key
from services.api.main import APP_VERSION, MAX_IMAGE_BYTES, app
from services.api.pipeline import choose_fixture, request_key

client = TestClient(app)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts" / "v1" / "scan_response.schema.json").read_text()
)

FIXTURE_KEYS = [fixture["key"] for fixture in FIXTURES]


def _png(seed: int = 0) -> bytes:
    return PNG_MAGIC + b"mock-image-" + str(seed).encode()


def _image_for_fixture(target_key: str, client_name: str = "test", hints=None, max_tries: int = 5000) -> bytes:
    """Brute-force small PNG-magic blobs until the request hash picks target_key."""
    for i in range(max_tries):
        data = _png(i)
        if choose_fixture(request_key(data, client_name, hints))["key"] == target_key:
            return data
    raise AssertionError(f"no image found for fixture {target_key!r}")


def _post_scan(data: bytes, *, client_name: str = "test", mode: str | None = None, hints: str | None = None):
    form = {"client": client_name}
    if mode is not None:
        form["mode"] = mode
    if hints is not None:
        form["hints"] = hints
    return client.post("/v1/scan", files={"image": ("label.png", data, "image/png")}, data=form)


# --------------------------------------------------------------------------
# Health / readiness
# --------------------------------------------------------------------------
def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "medcheck-inference"
    assert body["version"] == APP_VERSION
    assert body["uptime_s"] >= 0


def test_ready_mock():
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["mode"] == "mock"
    assert body["components"]["pipeline"] == "mock"


def test_ready_real_mode_when_components_present(monkeypatch):
    monkeypatch.setenv("MEDCHECK_API_MODE", "real")
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["mode"] == "real"
    assert body["components"]["pipeline"] == "real"
    assert body["components"]["vision"] == "ready"
    assert body["components"]["ocr"] == "ready"


def test_ready_503_when_components_missing(monkeypatch):
    import services.api.main as main_module

    monkeypatch.setenv("MEDCHECK_API_MODE", "real")
    monkeypatch.setattr(
        main_module, "real_pipeline_available", lambda: (False, ["missing:rapidocr_onnxruntime"])
    )
    monkeypatch.setattr(
        main_module,
        "real_component_status",
        lambda: {"vision": "ready", "ocr": "missing", "pipeline": "unavailable", "vlm": "disabled"},
    )
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert "missing:rapidocr_onnxruntime" in body["reasons"]


# --------------------------------------------------------------------------
# /v1/scan — happy paths
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_key", FIXTURE_KEYS)
def test_scan_fixture_statuses(fixture_key):
    data = _image_for_fixture(fixture_key)
    response = _post_scan(data)
    assert response.status_code == 200
    payload = response.json()
    jsonschema.validate(instance=payload, schema=SCHEMA)

    fixture = fixture_by_key(fixture_key)
    assert payload["contract_version"] == "1.1.0"
    assert payload["status"] == fixture["status"]
    assert payload["mode"] == "mock"
    assert payload["request_id"].startswith("req-")
    assert response.headers["X-Request-ID"] == payload["request_id"]

    # Safety block is mandatory on every response.
    assert payload["safety"]["ingestion_not_inferred"] is True
    assert payload["safety"]["backend_authoritative"] is True
    assert payload["safety"]["disclaimer"]

    if payload["status"] == "needs_rescan":
        assert payload["frame_quality"]["acceptable"] is False
        assert payload["uncertainty"]["rescan_required"] is True
        assert payload["frame_quality"]["guidance"]


def test_scan_ok_returns_fixture_medication():
    data = _image_for_fixture("metformin_ok")
    payload = _post_scan(data).json()
    assert payload["status"] == "ok"
    assert payload["medication"]["name"]["value"] == "Metformin"
    assert payload["medication"]["strength"]["value"] == 500
    assert payload["medication"]["strength"]["unit"] == "mg"
    assert payload["label"]["text"] is not None  # raw text preserved verbatim
    assert payload["candidates"][0]["name"] == "Metformin"


def test_scan_is_deterministic_for_same_request():
    data = _image_for_fixture("amoxicillin_ok")
    first = _post_scan(data).json()
    second = _post_scan(data).json()

    assert first["status"] == second["status"]
    assert first["medication"] == second["medication"]
    assert first["label"] == second["label"]
    assert first["candidates"] == second["candidates"]


def test_scan_accepts_valid_hints():
    data = _png(42)
    hints = json.dumps({"known_candidates": [{"name": "Metformin", "strength": {"value": 500, "unit": "mg"}}], "locale": "en-US"})
    response = _post_scan(data, hints=hints)
    assert response.status_code == 200
    assert response.json()["mode"] == "mock"


# --------------------------------------------------------------------------
# /v1/scan — transport-level rejections
# --------------------------------------------------------------------------
def test_rejects_oversize_image():
    data = PNG_MAGIC + b"x" * MAX_IMAGE_BYTES  # 12 MiB + magic
    response = _post_scan(data)
    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert body["request_id"].startswith("req-")


def test_rejects_non_image_content_type():
    response = client.post(
        "/v1/scan",
        files={"image": ("label.gif", b"GIF89a....", "image/gif")},
        data={"client": "test"},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_IMAGE_TYPE"


def test_rejects_missing_image():
    response = client.post("/v1/scan", data={"client": "test"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_rejects_empty_image():
    response = client.post(
        "/v1/scan",
        files={"image": ("label.png", b"", "image/png")},
        data={"client": "test"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_IMAGE"


def test_rejects_invalid_mode():
    response = _post_scan(_png(1), mode="bogus")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_MODE"


def test_rejects_invalid_client():
    response = _post_scan(_png(1), client_name="bogus")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CLIENT"


def test_rejects_invalid_hints_json():
    response = _post_scan(_png(1), hints="{not-json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_HINTS"


def test_rejects_non_object_hints():
    response = _post_scan(_png(1), hints="[1, 2, 3]")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_HINTS"


def test_real_mode_503_when_pipeline_unavailable(monkeypatch):
    import services.api.main as main_module
    from services.api.pipeline import PipelineUnavailable

    original = main_module.get_pipeline

    def fake_get_pipeline(mode):
        if mode == "real":
            raise PipelineUnavailable("test: components missing")
        return original(mode)

    monkeypatch.setattr(main_module, "get_pipeline", fake_get_pipeline)
    response = _post_scan(_png(1), mode="real")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REAL_PIPELINE_UNAVAILABLE"


# --------------------------------------------------------------------------
# /v1/scan — domain error stays HTTP 200
# --------------------------------------------------------------------------
def test_undecodable_image_is_domain_error():
    response = _post_scan(b"definitely-not-an-image")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_IMAGE"
    assert payload["mode"] == "mock"
    assert payload["safety"]["ingestion_not_inferred"] is True
    jsonschema.validate(instance=payload, schema=SCHEMA)
