"""Multi-frame capture endpoint tests (contract v1.2, POST /v1/scan/multi)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from services.api.main import MAX_IMAGE_BYTES, app
from services.api.pipeline import ScanContext, real_pipeline_available, to_contract_json
from services.api.pipeline import request_key, choose_fixture
from services.api.real_pipeline import RealScanPipeline

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "samples"
SCHEMA = json.loads((ROOT / "contracts" / "v1" / "scan_response.schema.json").read_text())

client = TestClient(app)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

REAL_READY = real_pipeline_available()[0]
requires_real = pytest.mark.skipif(not REAL_READY, reason=f"real stack missing: {real_pipeline_available()[1]}")


def _image_for_fixture(target_key: str, client_name: str = "test", max_tries: int = 5000) -> bytes:
    for i in range(max_tries):
        data = PNG_MAGIC + b"multi-seed-%d" % i
        if choose_fixture(request_key(data, client_name, None))["key"] == target_key:
            return data
    raise AssertionError(f"no image found for fixture {target_key!r}")


def _post_multi(images, *, client_name: str = "test", mode: str | None = None, hints: str | None = None, headers=None):
    form = {"client": client_name}
    if mode is not None:
        form["mode"] = mode
    if hints is not None:
        form["hints"] = hints
    files = [
        ("images", (f"frame{index}.png", data, "image/png")) for index, data in enumerate(images)
    ]
    return client.post("/v1/scan/multi", files=files, data=form, headers=headers or {})


def _validate(payload: dict) -> None:
    jsonschema.validate(instance=payload, schema=SCHEMA)


# --------------------------------------------------------------------------
# Mock mode (deterministic, no heavy deps)
# --------------------------------------------------------------------------
def test_mock_multi_capture_and_determinism():
    images = [_image_for_fixture("metformin_ok"), _image_for_fixture("amoxicillin_ok")]
    response = _post_multi(images)
    assert response.status_code == 200
    payload = response.json()
    _validate(payload)
    assert payload["contract_version"] == "1.2.0"
    assert payload["mode"] == "mock"
    assert payload["status"] == "ok"
    assert payload["capture"]["fusion"] == "multi_frame"
    assert payload["capture"]["frames_requested"] == 2
    assert payload["capture"]["frames_used"] == 2
    assert [frame["status"] for frame in payload["capture"]["per_frame"]] == ["accepted", "accepted"]
    assert "fused_from_2_frames" in payload["uncertainty"]["reasons"]
    assert payload["medication"]["name"]["value"] in {"Metformin", "Amoxicillin"}
    assert payload["instructions"]["dose"]

    second = _post_multi(images).json()
    assert second["capture"] == payload["capture"]
    assert second["medication"] == payload["medication"]
    assert second["instructions"] == payload["instructions"]


def test_mock_multi_mixed_statuses():
    images = [_image_for_fixture("blurry_rescan"), _image_for_fixture("metformin_ok")]
    payload = _post_multi(images).json()
    _validate(payload)
    statuses = [frame["status"] for frame in payload["capture"]["per_frame"]]
    assert statuses == ["needs_rescan", "accepted"]
    assert payload["capture"]["frames_used"] == 1
    assert payload["medication"]["name"]["value"] == "Metformin"


def test_mock_multi_all_rejected():
    images = [_image_for_fixture("blurry_rescan"), _image_for_fixture("blurry_rescan")]
    payload = _post_multi(images).json()
    _validate(payload)
    assert payload["status"] == "needs_rescan"
    assert payload["capture"]["frames_used"] == 0
    assert payload["uncertainty"]["rescan_required"] is True
    assert payload["medication"]["name"]["value"] is None


def test_mock_multi_no_bottle_frames():
    images = [_image_for_fixture("no_bottle"), _image_for_fixture("no_bottle")]
    payload = _post_multi(images).json()
    _validate(payload)
    assert payload["status"] == "no_medication_found"
    assert payload["capture"]["frames_used"] == 0
    assert payload["uncertainty"]["rescan_required"] is False


# --------------------------------------------------------------------------
# Transport validation
# --------------------------------------------------------------------------
def test_multi_requires_at_least_two_frames():
    response = _post_multi([_image_for_fixture("metformin_ok")])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FRAME_COUNT"


def test_multi_rejects_more_than_six_frames():
    image = _image_for_fixture("metformin_ok")
    response = _post_multi([image] * 7)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FRAME_COUNT"


def test_multi_requires_images():
    response = client.post("/v1/scan/multi", data={"client": "test", "mode": "mock"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_multi_rejects_bad_content_type_per_frame():
    image = _image_for_fixture("metformin_ok")
    response = client.post(
        "/v1/scan/multi",
        files=[
            ("images", ("frame0.png", image, "image/png")),
            ("images", ("frame1.gif", b"GIF89a", "image/gif")),
        ],
        data={"client": "test", "mode": "mock"},
    )
    assert response.status_code == 415
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_IMAGE_TYPE"
    assert body["error"]["detail"] == {"index": 1}


def test_multi_rejects_oversize_frame():
    image = _image_for_fixture("metformin_ok")
    big = PNG_MAGIC + b"x" * MAX_IMAGE_BYTES
    response = client.post(
        "/v1/scan/multi",
        files=[
            ("images", ("frame0.png", image, "image/png")),
            ("images", ("frame1.png", big, "image/png")),
        ],
        data={"client": "test", "mode": "mock"},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert body["error"]["detail"] == {"index": 1}


def test_multi_rejects_invalid_mode_and_hints():
    images = [_image_for_fixture("metformin_ok"), _image_for_fixture("amoxicillin_ok")]
    bad_mode = _post_multi(images, mode="bogus")
    assert bad_mode.status_code == 400
    assert bad_mode.json()["error"]["code"] == "INVALID_MODE"
    bad_hints = _post_multi(images, hints="{not-json")
    assert bad_hints.status_code == 400
    assert bad_hints.json()["error"]["code"] == "INVALID_HINTS"


def test_multi_auth_enforced(monkeypatch):
    monkeypatch.setenv("MEDCHECK_API_KEY", "multi-secret")
    images = [_image_for_fixture("metformin_ok"), _image_for_fixture("amoxicillin_ok")]
    assert _post_multi(images).status_code == 401
    assert _post_multi(images, headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = _post_multi(images, headers={"Authorization": "Bearer multi-secret"})
    assert ok.status_code == 200
    assert ok.json()["mode"] == "mock"


# --------------------------------------------------------------------------
# Real mode (Vision + OCR + fusion)
# --------------------------------------------------------------------------
def _real_ctx(path: Path, index: int = 0) -> ScanContext:
    return ScanContext(
        request_id="req-multi-real00",
        image=path.read_bytes(),
        content_type="image/png",
        client="test",
        requested_mode="real",
        hints=None,
    )


def _run_real_multi(paths):
    response = asyncio.run(RealScanPipeline().scan_multi([_real_ctx(path) for path in paths]))
    payload = to_contract_json(response)
    _validate(payload)
    return payload


@requires_real
def test_real_multi_long_label_fuses():
    payload = _run_real_multi(
        [
            SAMPLES / "long_label_left.png",
            SAMPLES / "long_label_middle.png",
            SAMPLES / "long_label_right.png",
        ]
    )
    assert payload["mode"] == "real"
    assert payload["medication"]["name"]["value"] == "Hydrochlorothiazide"
    assert payload["medication"]["strength"]["value"] == 25
    assert payload["medication"]["strength"]["unit"] == "mg"
    assert payload["instructions"]["parsed"], "fused instructions missing"
    assert payload["instructions"]["dose"]["quantity"] == 1
    assert payload["capture"]["frames_used"] == 2
    assert payload["capture"]["per_frame"][2]["status"] == "no_medication_found"
    assert "fused_from_2_frames" in payload["uncertainty"]["reasons"]
    assert payload["uncertainty"]["rescan_required"] is False


@requires_real
def test_real_multi_blurry_plus_good():
    payload = _run_real_multi(
        [
            SAMPLES / "label_metformin.png",
            SAMPLES / "label_metformin_blurry.png",
            SAMPLES / "label_metformin_dark.png",
        ]
    )
    assert payload["capture"]["frames_used"] == 2
    statuses = [frame["status"] for frame in payload["capture"]["per_frame"]]
    assert statuses[1] == "needs_rescan"
    assert payload["medication"]["name"]["value"] == "Metformin"
    assert "fused_from_2_frames" in payload["uncertainty"]["reasons"]


@requires_real
def test_real_multi_no_frames_accepted():
    payload = _run_real_multi(
        [SAMPLES / "label_metformin_blurry.png", SAMPLES / "label_metformin_blurry.png"]
    )
    assert payload["status"] == "needs_rescan"
    assert payload["capture"]["frames_used"] == 0
    assert all(frame["status"] == "needs_rescan" for frame in payload["capture"]["per_frame"])
    assert payload["uncertainty"]["rescan_required"] is True


@requires_real
def test_real_multi_over_http():
    files = [
        ("images", ("left.png", (SAMPLES / "long_label_left.png").read_bytes(), "image/png")),
        ("images", ("middle.png", (SAMPLES / "long_label_middle.png").read_bytes(), "image/png")),
    ]
    response = client.post(
        "/v1/scan/multi",
        files=files,
        data={"mode": "real", "client": "test"},
    )
    assert response.status_code == 200
    payload = response.json()
    _validate(payload)
    assert payload["mode"] == "real"
    assert payload["capture"]["fusion"] == "multi_frame"
    assert payload["medication"]["name"]["value"] == "Hydrochlorothiazide"
