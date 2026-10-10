"""Mocked-HTTP tests for the Qwen3-VL adapter (no GPU, no network)."""
from __future__ import annotations

import json

import httpx
import pytest

from services.vlm.client import (
    Qwen3VLClient,
    VlmConfig,
    VlmConfigError,
    VlmImageError,
    build_prompt,
    coerce_strength,
    encode_image_data_uri,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 64
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 64

MODEL = "Qwen/Qwen3-VL-8B-Instruct-FP8"


def make_config(**overrides) -> VlmConfig:
    base = dict(
        base_url="http://vlm.test:8100/v1",
        model=MODEL,
        api_key="test-key-not-real",
        timeout_s=5.0,
        max_retries=0,
    )
    base.update(overrides)
    return VlmConfig(**base)


def chat_response(content: str, model: str = MODEL, status: int = 200) -> httpx.Response:
    payload = {"model": model, "choices": [{"message": {"role": "assistant", "content": content}}]}
    return httpx.Response(status, json=payload)


def make_client(handler, config: VlmConfig | None = None) -> Qwen3VLClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, timeout=10.0)
    return Qwen3VLClient(config=config or make_config(), http_client=http)


VALID_CONTENT = json.dumps(
    {
        "summary": "A label for metformin 500 mg.",
        "fields": {
            "name": {"value": "Metformin HCl", "confidence": 0.93, "evidence": "front"},
            "strength_value": {"value": 500, "confidence": 0.9},
            "strength_unit": {"value": "mg", "confidence": 0.9},
            "form": {"value": "Tablet", "confidence": 0.8},
            "manufacturer": {"value": None, "confidence": 0.1},
            "instructions": {"value": "Take 1 tablet by mouth twice daily", "confidence": 0.85},
        },
    }
)


class TestConfig:
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("MEDCHECK_VLM_BASE_URL", "http://rig:8100/v1/")
        monkeypatch.setenv("MEDCHECK_VLM_MODEL", MODEL)
        monkeypatch.setenv("MEDCHECK_VLM_API_KEY", "secret-key")
        cfg = VlmConfig.from_env()
        assert cfg.base_url == "http://rig:8100/v1"
        assert cfg.chat_url == "http://rig:8100/v1/chat/completions"
        assert cfg.models_url == "http://rig:8100/v1/models"
        assert cfg.max_retries == 0  # retries off by default

    def test_from_env_requires_base_url(self):
        with pytest.raises(VlmConfigError):
            VlmConfig.from_env(env={})

    def test_from_env_rejects_non_http(self):
        with pytest.raises(VlmConfigError):
            VlmConfig.from_env(env={"MEDCHECK_VLM_BASE_URL": "rig:8100/v1"})


class TestImageEncoding:
    @pytest.mark.parametrize(
        ("data", "mime"),
        [(PNG_BYTES, "image/png"), (JPEG_BYTES, "image/jpeg"), (WEBP_BYTES, "image/webp")],
    )
    def test_magics(self, data, mime):
        assert encode_image_data_uri(data).startswith(f"data:{mime};base64,")

    def test_rejects_unknown_format(self):
        with pytest.raises(VlmImageError):
            encode_image_data_uri(b"not an image")

    def test_rejects_empty_and_oversized(self):
        with pytest.raises(VlmImageError):
            encode_image_data_uri(b"")
        with pytest.raises(VlmImageError):
            encode_image_data_uri(PNG_BYTES, max_bytes=4)


class TestInterpret:
    def test_success_payload_and_parsing(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("Authorization")
            seen["body"] = json.loads(request.content)
            return chat_response("```json\n" + VALID_CONTENT + "\n```")

        client = make_client(handler)
        result = client.interpret(PNG_BYTES)

        assert result.available is True
        assert result.error is None
        assert result.latency_ms >= 0
        assert result.model == MODEL
        assert result.summary == "A label for metformin 500 mg."
        assert result.fields["name"]["value"] == "Metformin HCl"
        assert result.fields["name"]["source"] == "vlm"
        assert result.fields["strength_value"]["value"] == 500
        assert result.fields["strength_unit"]["value"] == "mg"
        # null values are dropped, not fabricated
        assert "manufacturer" not in result.fields
        assert "Take 1 tablet" in result.fields["instructions"]["value"]

        assert seen["url"] == "http://vlm.test:8100/v1/chat/completions"
        assert seen["auth"] == "Bearer test-key-not-real"
        body = seen["body"]
        assert body["model"] == MODEL
        assert body["max_tokens"] > 0
        user_content = body["messages"][1]["content"]
        image_part = next(p for p in user_content if p["type"] == "image_url")
        assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
        # OCR mode off: no OCR block, no untrusted-data framing
        text_part = next(p for p in user_content if p["type"] == "text")
        assert "BEGIN OCR TEXT" not in text_part["text"]

    def test_ocr_mode_includes_untrusted_text(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return chat_response(VALID_CONTENT)

        client = make_client(handler)
        result = client.interpret(PNG_BYTES, ocr_text="Metformln 5OOmg\nTake 1 tablet")
        assert result.available is True
        prompt = seen["body"]["messages"][1]["content"][0]["text"]
        assert "Metformln 5OOmg" in prompt
        assert "BEGIN OCR TEXT" in prompt
        assert "untrusted data" in prompt

    def test_aliases_and_freeform_strength(self):
        content = json.dumps(
            {
                "fields": {
                    "drug_name": "Lisinopril",
                    "strength": "10 mg",
                    "directions": "Take once daily",
                }
            }
        )
        client = make_client(lambda request: chat_response(content))
        result = client.interpret(PNG_BYTES)
        assert result.fields["name"]["value"] == "Lisinopril"
        assert result.fields["strength_value"]["value"] == 10
        assert result.fields["strength_unit"]["value"] == "mg"
        assert result.fields["instructions"]["value"] == "Take once daily"

    def test_non_json_response_is_available_with_error(self):
        client = make_client(lambda request: chat_response("I cannot read this label."))
        result = client.interpret(PNG_BYTES)
        assert result.available is True
        assert result.fields == {}
        assert result.raw_text == "I cannot read this label."
        assert result.error is not None and result.error.startswith("response_not_json")

    def test_transport_failure_returns_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = make_client(handler)
        result = client.interpret(PNG_BYTES)
        assert result.available is False
        assert "ConnectError" in result.error

    def test_http_500_returns_unavailable(self):
        client = make_client(lambda request: httpx.Response(500, text="boom"))
        result = client.interpret(PNG_BYTES)
        assert result.available is False
        assert "500" in result.error

    def test_retries_when_enabled(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, text="loading")
            return chat_response(VALID_CONTENT)

        client = make_client(handler, config=make_config(max_retries=1))
        result = client.interpret(PNG_BYTES)
        assert calls["n"] == 2
        assert result.available is True

    def test_retries_off_by_default(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503, text="loading")

        client = make_client(handler)
        result = client.interpret(PNG_BYTES)
        assert calls["n"] == 1
        assert result.available is False

    def test_bad_image_raises(self):
        client = make_client(lambda request: chat_response(VALID_CONTENT))
        with pytest.raises(VlmImageError):
            client.interpret(b"garbage")

    def test_available_probe(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url).endswith("/v1/models")
            return httpx.Response(200, json={"data": [{"id": MODEL}]})

        assert make_client(handler).available() is True

        def broken(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope", request=request)

        assert make_client(broken).available() is False


class TestPromptAndHelpers:
    def test_build_prompt_modes(self):
        plain = build_prompt(question="What is this?")
        assert "OCR TEXT" not in plain
        with_ocr = build_prompt(ocr_text="Metformln")
        assert "Metformln" in with_ocr and "BEGIN OCR TEXT" in with_ocr

    def test_coerce_strength(self):
        assert coerce_strength("500 mg") == {"strength_value": 500, "strength_unit": "mg"}
        assert coerce_strength("0.5mg") == {"strength_value": 0.5, "strength_unit": "mg"}
        assert coerce_strength(250) == {"strength_value": 250}
        assert coerce_strength("unknown") == {}
        assert coerce_strength(None) == {}
