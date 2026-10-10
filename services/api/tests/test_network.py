"""Network-readiness tests: optional bearer auth + env-driven CORS."""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import services.api.main as main_module
from services.api.main import app

client = TestClient(app)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
KEY = "s3cret-key"


def _post_scan(headers=None):
    return client.post(
        "/v1/scan",
        files={"image": ("label.png", PNG_MAGIC + b"auth-test", "image/png")},
        data={"mode": "mock", "client": "test"},
        headers=headers or {},
    )


# --------------------------------------------------------------------------
# Bearer auth (optional; enabled only when MEDCHECK_API_KEY is set)
# --------------------------------------------------------------------------
def test_scan_requires_bearer_when_enabled(monkeypatch):
    monkeypatch.setenv("MEDCHECK_API_KEY", KEY)
    for headers in (
        None,
        {"Authorization": "Bearer wrong-key"},
        {"Authorization": KEY},  # missing "Bearer " prefix
    ):
        response = _post_scan(headers)
        assert response.status_code == 401, headers
        body = response.json()
        assert body["error"]["code"] == "UNAUTHORIZED"
        assert "bearer" in body["error"]["message"].lower()
        assert body["request_id"].startswith("req-")


def test_scan_accepts_correct_bearer(monkeypatch):
    monkeypatch.setenv("MEDCHECK_API_KEY", KEY)
    response = _post_scan({"Authorization": f"Bearer {KEY}"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "mock"
    assert body["contract_version"] == "1.1.0"


def test_auth_disabled_when_key_unset(monkeypatch):
    monkeypatch.delenv("MEDCHECK_API_KEY", raising=False)
    response = _post_scan()
    assert response.status_code == 200


def test_health_ready_stay_open_with_auth_enabled(monkeypatch):
    monkeypatch.setenv("MEDCHECK_API_KEY", KEY)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code in (200, 503)


# --------------------------------------------------------------------------
# CORS (off by default; enabled via MEDCHECK_CORS_ORIGINS)
# --------------------------------------------------------------------------
def test_cors_disabled_by_default():
    importlib.reload(main_module)
    with TestClient(main_module.app) as cors_client:
        response = cors_client.get("/health", headers={"Origin": "http://web.test"})
        assert "access-control-allow-origin" not in response.headers


def test_cors_allows_configured_origin(monkeypatch):
    monkeypatch.setenv("MEDCHECK_CORS_ORIGINS", "http://web.test, http://localhost:5173")
    importlib.reload(main_module)
    try:
        with TestClient(main_module.app) as cors_client:
            simple = cors_client.get("/health", headers={"Origin": "http://web.test"})
            assert simple.headers.get("access-control-allow-origin") == "http://web.test"

            preflight = cors_client.options(
                "/v1/scan",
                headers={
                    "Origin": "http://web.test",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"] == "http://web.test"
            assert "POST" in preflight.headers["access-control-allow-methods"]
            allowed_headers = preflight.headers["access-control-allow-headers"].lower()
            assert "authorization" in allowed_headers
            assert "content-type" in allowed_headers

            denied = cors_client.get("/health", headers={"Origin": "http://evil.test"})
            assert "access-control-allow-origin" not in denied.headers
    finally:
        monkeypatch.delenv("MEDCHECK_CORS_ORIGINS", raising=False)
        importlib.reload(main_module)
