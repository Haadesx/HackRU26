"""Real-mode pipeline tests: Vision -> OCR -> (matcher) -> (mocked VLM).

Requires the composed runtime stack (vision + OCR installed in the venv). The
tests use the orchestrator sample labels and never touch the network — the
optional VLM call is exercised through an injected ``httpx.MockTransport``.
"""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import cv2
import httpx
import jsonschema
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from services.api.main import app
from services.api.pipeline import (
    ScanContext,
    get_pipeline,
    real_pipeline_available,
    to_contract_json,
)
from services.api.real_pipeline import (
    RealScanPipeline,
    extract_hints_from_request,
    known_candidates_from_request,
)
from services.common.contract import BBox, ScanResponse
from services.vision.pipeline import analyze_frame
from services.vlm.client import Qwen3VLClient, VlmConfig

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "samples"
SCHEMA = json.loads((ROOT / "contracts" / "v1" / "scan_response.schema.json").read_text())

SHARP = SAMPLES / "label_metformin.png"
DARK = SAMPLES / "label_metformin_dark.png"
BLURRY = SAMPLES / "label_metformin_blurry.png"

pytestmark = pytest.mark.skipif(
    not real_pipeline_available()[0],
    reason=f"real pipeline dependencies missing: {real_pipeline_available()[1]}",
)

client = TestClient(app)


def run_scan(data: bytes, *, hints=None, **pipeline_kwargs) -> tuple[ScanResponse, dict]:
    ctx = ScanContext(
        request_id="req-realtest0000",
        image=data,
        content_type="image/png",
        client="test",
        requested_mode="real",
        hints=hints,
    )
    pipeline = RealScanPipeline(**pipeline_kwargs)
    response = asyncio.run(pipeline.scan(ctx))
    payload = to_contract_json(response)
    jsonschema.validate(instance=payload, schema=SCHEMA)
    return response, payload


def _noise_png() -> bytes:
    image = Image.effect_noise((320, 320), 40).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _assert_safety(payload: dict) -> None:
    assert payload["safety"]["ingestion_not_inferred"] is True
    assert payload["safety"]["backend_authoritative"] is True
    assert payload["safety"]["disclaimer"]


# --------------------------------------------------------------------------
# Real sample path
# --------------------------------------------------------------------------
def test_real_scan_dark_sample_reads_metformin(monkeypatch):
    monkeypatch.delenv("MEDCHECK_VLM_ENABLED", raising=False)
    response, payload = run_scan(DARK.read_bytes())

    assert response.mode == "real"
    assert payload["status"] in {"ok", "uncertain"}
    assert payload["frame_quality"]["acceptable"] is True
    assert payload["label"]["text"]
    assert payload["medication"]["name"]["value"] == "Metformin"
    assert payload["medication"]["name"]["source"] == "ocr"
    assert payload["medication"]["strength"]["value"] == 500
    assert payload["medication"]["strength"]["unit"] == "mg"
    assert payload["interpretation"]["available"] is False
    assert payload["timing"]["stages"]["ocr"] >= 0
    assert all(candidate["source"] in {"registry", "ocr", "vlm"} for candidate in payload["candidates"])
    _assert_safety(payload)


@pytest.mark.parametrize("sample", [SHARP, DARK, BLURRY], ids=lambda p: p.name)
def test_real_scan_follows_vision_quality_verdict(sample, monkeypatch):
    """The API must obey vision's acceptable flag, whatever the calibration.

    Calibration-agnostic: it reads the verdict from analyze_frame itself, so it
    stays green when vision thresholds/samples change (e.g. Atlas's M2
    readable-bright refinement makes the flat samples acceptable).
    """
    monkeypatch.delenv("MEDCHECK_VLM_ENABLED", raising=False)
    data = sample.read_bytes()
    acceptable = analyze_frame(data).quality.acceptable

    _, payload = run_scan(data)
    assert payload["frame_quality"]["acceptable"] is acceptable
    assert payload["frame_quality"]["guidance"]
    if not acceptable:
        assert payload["status"] == "needs_rescan"
        assert payload["uncertainty"]["rescan_required"] is True
        assert "ocr" not in payload["timing"]["stages"]
        assert payload["label"].get("text") is None
        assert payload["medication"]["name"]["value"] is None
    else:
        assert payload["status"] != "needs_rescan"
        assert payload["uncertainty"]["rescan_required"] is False
        assert "ocr" in payload["timing"]["stages"]
    _assert_safety(payload)


def test_blurry_frame_skips_ocr(monkeypatch):
    monkeypatch.delenv("MEDCHECK_VLM_ENABLED", raising=False)
    _, payload = run_scan(BLURRY.read_bytes())
    assert payload["status"] == "needs_rescan"
    assert "ocr" not in payload["timing"]["stages"]
    assert payload["label"].get("text") is None
    assert payload["candidates"] == []


def test_real_scan_no_medication_found(monkeypatch):
    monkeypatch.delenv("MEDCHECK_VLM_ENABLED", raising=False)
    _, payload = run_scan(_noise_png())
    assert payload["status"] == "no_medication_found"
    assert payload["uncertainty"]["rescan_required"] is False
    assert "no_bottle_detected" in payload["uncertainty"]["reasons"]
    assert payload["frame_quality"]["guidance"]


def test_real_scan_invalid_image_is_domain_error(monkeypatch):
    monkeypatch.delenv("MEDCHECK_VLM_ENABLED", raising=False)
    _, payload = run_scan(b"\x89PNG\r\n\x1a\nnot-a-real-png")
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_IMAGE"
    assert payload["mode"] == "real"
    _assert_safety(payload)


def test_ocr_frame_decode_is_exif_safe(monkeypatch):
    """Vision bboxes refer to the EXIF-displayed orientation.

    Locks the adapter to services.vision.decode_image (EXIF-transposed) rather
    than a raw cv2 decode, so a rotated camera photo keeps bbox alignment.
    """
    from services.api import real_pipeline
    from services.ocr.types import OcrResult
    from services.vision.preprocess import decode_image

    image = Image.new("RGB", (600, 300), "white")
    exif = image.getexif()
    exif[274] = 6  # Orientation: rotate 90 CW for display
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    data = buffer.getvalue()

    displayed = decode_image(data).shape[:2]
    stored = cv2.imdecode(
        np.frombuffer(data, dtype=np.uint8),
        cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION,
    ).shape[:2]
    assert (stored, displayed) == ((300, 600), (600, 300)), "fixture must exercise EXIF rotation"

    captured = {}

    def fake_read_text(image_array, bbox=None, *, channel_order="bgr", engine=None):
        captured["shape"] = image_array.shape[:2]
        captured["channel_order"] = channel_order
        return OcrResult(raw_text="", lines=[], engine="fake")

    monkeypatch.setattr(real_pipeline, "read_text", fake_read_text)
    pipeline = real_pipeline.RealScanPipeline()
    pipeline._read_label_text(data, BBox(x=0.0, y=0.0, w=1.0, h=1.0))

    assert captured["shape"] == displayed
    assert captured["channel_order"] == "rgb"


def test_real_mode_over_http(monkeypatch):
    monkeypatch.delenv("MEDCHECK_VLM_ENABLED", raising=False)
    response = client.post(
        "/v1/scan",
        files={"image": ("label.png", DARK.read_bytes(), "image/png")},
        data={"mode": "real", "client": "test"},
    )
    assert response.status_code == 200
    payload = response.json()
    jsonschema.validate(instance=payload, schema=SCHEMA)
    assert payload["mode"] == "real"
    assert payload["medication"]["name"]["value"] == "Metformin"


def test_mock_pipeline_unchanged():
    assert get_pipeline("mock").mode == "mock"


# --------------------------------------------------------------------------
# Matcher seam (PI-2 matcher lands separately; injection proves the wiring)
# --------------------------------------------------------------------------
def test_matcher_injection_populates_candidates(monkeypatch):
    monkeypatch.delenv("MEDCHECK_VLM_ENABLED", raising=False)
    captured = {}

    def fake_matcher(fields, candidates, threshold=0.75):
        captured["fields"] = fields
        captured["candidates"] = candidates
        captured["threshold"] = threshold
        return [
            {
                "name": "Metformin",
                "strength": {"value": 500, "unit": "mg"},
                "score": 0.92,
                "source": "registry",
            }
        ]

    hints = {"known_candidates": [{"name": "Metformin", "strength": {"value": 500, "unit": "mg"}}]}
    _, payload = run_scan(DARK.read_bytes(), hints=hints, matcher=fake_matcher)

    assert payload["candidates"][0]["name"] == "Metformin"
    assert payload["candidates"][0]["source"] == "registry"
    assert captured["threshold"] == 0.75
    # Extraction is PI-2's preferred matcher input shape.
    assert captured["fields"].name.value == "Metformin"
    assert captured["fields"].strength.value == 500
    assert captured["candidates"] == hints["known_candidates"]


def test_escalation_config_matches_pi3_contract():
    """Lock the M3 keys agreed with PI-3 (services/vlm/EVAL.md)."""
    from services.api.real_pipeline import ESCALATION_FIELDS, escalation_config

    config = escalation_config(False)
    assert config["min_field_confidence"] == 0.75
    assert config["escalation_fields"] == ("name", "strength_value") == ESCALATION_FIELDS
    assert config["min_frame_score"] == 0.45
    assert config["candidate_mismatch"] is False
    assert escalation_config(True)["candidate_mismatch"] is True


def test_hint_extraction_helpers():
    hints = {
        "known_candidates": [{"name": "Metformin", "strength": {"value": 500, "unit": "mg"}}],
        "locale": "en-US",
    }
    derived = extract_hints_from_request(hints)
    assert derived["name"] == "Metformin"
    assert derived["lexicon"] == ["Metformin"]
    assert derived["strength_value"] == 500
    assert derived["strength_unit"] == "mg"
    assert known_candidates_from_request(hints) == hints["known_candidates"]
    assert extract_hints_from_request(None) == {}
    assert known_candidates_from_request(None) == []


# --------------------------------------------------------------------------
# VLM escalation — off by default; identity-critical, mocked HTTP when enabled
# --------------------------------------------------------------------------
#: Same-name/wrong-strength candidate -> matcher drops it (0.70 < 0.75) -> mismatch.
MISMATCH_HINTS = {"known_candidates": [{"name": "Metformin", "strength": {"value": 999, "unit": "mg"}}]}
MATCH_HINTS = {"known_candidates": [{"name": "Metformin", "strength": {"value": 500, "unit": "mg"}}]}


def _mock_vlm_factory(calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content.decode())
        assert payload["model"] == "Qwen/Test-VL"
        image_part = [part for part in payload["messages"][1]["content"] if part["type"] == "image_url"]
        assert image_part and image_part[0]["image_url"]["url"].startswith("data:image/png;base64,")
        content = json.dumps(
            {
                "summary": "Verified synthetic label read.",
                "fields": {
                    "name": {"value": "Metformin", "confidence": 0.98},
                    "strength_value": {"value": 500, "confidence": 0.98},
                    "strength_unit": {"value": "mg", "confidence": 0.98},
                    "form": {"value": "tablet", "confidence": 0.95},
                    "manufacturer": {"value": "ACME Labs", "confidence": 0.9},
                    "instructions": {
                        "value": "Take 1 tablet by mouth twice daily with meals.",
                        "confidence": 0.9,
                    },
                },
            }
        )
        return httpx.Response(
            200,
            json={"model": "Qwen/Test-VL", "choices": [{"message": {"content": content}}]},
        )

    def factory():
        return Qwen3VLClient(
            config=VlmConfig(base_url="http://vlm.test/v1", model="Qwen/Test-VL"),
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    return factory


def test_vlm_off_by_default(monkeypatch):
    monkeypatch.delenv("MEDCHECK_VLM_ENABLED", raising=False)

    def must_not_be_called():  # pragma: no cover - fails the test if reached
        raise AssertionError("VLM must not be called when MEDCHECK_VLM_ENABLED is unset")

    _, payload = run_scan(DARK.read_bytes(), hints=MISMATCH_HINTS, vlm_client_factory=must_not_be_called)
    assert payload["interpretation"]["available"] is False
    assert payload["timing"]["stages"]["vlm"] == 0.0


def test_candidate_mismatch_escalates_with_mocked_http(monkeypatch):
    """(a) confident OCR + mismatched registered candidates -> VLM invoked."""
    monkeypatch.setenv("MEDCHECK_VLM_ENABLED", "true")
    calls: list = []
    _, payload = run_scan(
        DARK.read_bytes(), hints=MISMATCH_HINTS, vlm_client_factory=_mock_vlm_factory(calls)
    )

    assert len(calls) == 1
    assert payload["candidates"] == []  # mismatched candidate was dropped
    assert payload["interpretation"]["available"] is True
    assert payload["interpretation"]["source"] == "vlm"
    assert payload["interpretation"]["model"] == "Qwen/Test-VL"
    assert payload["medication"]["manufacturer"]["value"] == "ACME Labs"
    assert payload["medication"]["manufacturer"]["source"] == "vlm"
    assert payload["medication"]["name"]["value"] == "Metformin"
    assert payload["status"] == "ok"
    assert payload["uncertainty"]["level"] == "low"
    assert payload["timing"]["stages"]["vlm"] >= 0
    _assert_safety(payload)


def test_matched_candidate_does_not_escalate(monkeypatch):
    """(b) registered candidate matched at/above threshold -> no VLM call."""
    monkeypatch.setenv("MEDCHECK_VLM_ENABLED", "true")
    calls: list = []
    _, payload = run_scan(
        DARK.read_bytes(), hints=MATCH_HINTS, vlm_client_factory=_mock_vlm_factory(calls)
    )

    assert calls == []
    assert payload["interpretation"]["available"] is False
    assert payload["candidates"] and payload["candidates"][0]["score"] >= 0.75
    assert payload["timing"]["stages"]["vlm"] == 0.0


def test_missing_optional_field_does_not_escalate(monkeypatch):
    """(c) missing manufacturer alone must not cost a VLM call.

    PI-3 M3 semantics: optional-field gaps keep level "medium" (usable but
    incomplete) but medium no longer escalates on its own — only missing/weak
    escalation fields (name, strength) do.
    """
    monkeypatch.setenv("MEDCHECK_VLM_ENABLED", "true")

    def must_not_be_called():  # pragma: no cover - fails the test if reached
        raise AssertionError("VLM invoked for a missing optional field")

    _, payload = run_scan(DARK.read_bytes(), vlm_client_factory=must_not_be_called)
    assert payload["interpretation"]["available"] is False
    assert payload["timing"]["stages"]["vlm"] == 0.0
    assert payload["uncertainty"]["level"] == "medium"
    assert "missing:manufacturer" in payload["uncertainty"]["reasons"]


def test_vlm_transport_failure_degrades(monkeypatch):
    monkeypatch.setenv("MEDCHECK_VLM_ENABLED", "true")

    def factory():
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise httpx.ConnectError("no vllm in tests", request=request)

        return Qwen3VLClient(
            config=VlmConfig(base_url="http://vlm.test/v1", model="Qwen/Test-VL"),
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    _, payload = run_scan(DARK.read_bytes(), hints=MISMATCH_HINTS, vlm_client_factory=factory)
    assert payload["interpretation"]["available"] is False
    assert payload["status"] in {"uncertain", "ok"}
    assert payload["medication"]["name"]["value"] == "Metformin"
    assert "vlm_unavailable" in payload["uncertainty"]["reasons"]
